"""Repairs, warranty arithmetic, loaner occupancy and the five-level lot recall."""

from test_helpers import (
    ApiErrorId,
    approx_mm,
    assert_calendar_date,
    assert_lot_population_conservation,
    assert_repair_order,
    build_scenario,
    draft_claim,
    open_repair,
    schedule_and_apply_visit,
    schedule_visit,
    set_clock,
    validate_error,
    validate_success,
)


def test_out_of_warranty_labour_is_billed_in_quarter_hours_and_capped(api):
    """PRD §3.9: "On the billable branch, labour is billed in whole quarter-hours: `labor_units`
    is `labor_minutes` divided by 15 and rounded **up** to the next whole unit, the uncapped
    charge is `labor_units` multiplied by 2500 cents per unit, and `repair_charge_cents` is the
    smaller of that and a cap of half the custom-appliance fee schedule — 0.50 of 185000 cents,
    rounded half up, which is 92500 cents."
    PRD §3.9: "At 555 minutes the charge is exactly 37 units and 92500 cents; at 556 minutes it
    is 38 units, 95000 cents uncapped, and still 92500 cents after the cap binds."
    PRD §3.9: "`in_warranty` is true only when `reason` is `DEFECT` *and* `reported_on` is not
    later than the appliance's `warranty_end_date`, which sits 36 months after delivery."

    Design: Corner/calculations/out_of_warranty_repair_charge_is_capped_at_half_the_fee_schedule
    """
    scenario = build_scenario("delivered")
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    at_cap = open_repair(
        scenario, reason="WEAR", reported_on="2026-06-10", labor_minutes=555
    )
    over_cap = open_repair(
        scenario, reason="WEAR", reported_on="2026-06-11", labor_minutes=556
    )
    assert_repair_order(at_cap)
    assert at_cap["labor_units"] == 37
    assert at_cap["repair_charge_cents"] == 92500
    assert over_cap["labor_units"] == 38
    assert over_cap["repair_charge_cents"] == 92500
    assert at_cap["in_warranty"] is False, "WEAR is never an in-warranty defect"
    assert over_cap["billable"] is True


def test_lost_device_retires_and_voids_its_draft_continued_use_claim(api):
    """PRD §3.9: "For `LOSS` the order moves `OPEN → CLOSED_NOT_COVERED` immediately instead:
    `billable` is set to true and `repair_charge_cents` to 0, because a lost device is replaced
    rather than repaired, and a two-level cascade runs — the appliance is retired, resetting its
    `recall_status` to `NOT_SCHEDULED` and clearing `next_recall_due_on`, and every `DRAFT` claim
    of type `CONTINUED_USE` on that appliance is voided."
    PRD §3.9: "The retirement edge is declared out of `ACTIVE_THERAPY` and, identically, out of
    `IN_TITRATION`, where any visit still `SCHEDULED` or `HELD` on the device also moves to
    `SUPERSEDED`; a device lost mid-titration is retired just the same."

    Design: Corner/state_machines/loss_repair_retires_the_device_and_voids_its_draft_continued_use_claim
    """
    scenario = build_scenario("delivered")
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    claim = draft_claim(
        scenario, claim_type="CONTINUED_USE", billed_cents=20000,
        date_of_service="2026-06-04",
    )
    repair = open_repair(scenario, reason="LOSS", reported_on="2026-06-05")
    assert repair["status"] == "CLOSED_NOT_COVERED"
    assert repair["repair_charge_cents"] == 0
    assert repair["resets_useful_lifetime"] is False

    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["lifecycle_status"] == "RETIRED"
    assert appliance["recall_status"] == "NOT_SCHEDULED"
    voided = validate_success(api.get_claim(claim["id"], scenario["billing_headers"]))
    assert voided["status"] == "VOIDED"


def test_in_warranty_defect_repair_opens_at_the_lab_and_charges_nothing(api):
    """PRD §3.9: "`in_warranty` is true only when `reason` is `DEFECT` *and* `reported_on` is not
    later than the appliance's `warranty_end_date`, which sits 36 months after delivery."
    PRD §3.9: "For `DEFECT`, `WEAR` and `ABUSE` the order moves `OPEN → IN_LAB` immediately and
    the loaner interval, if a loaner was named, opens on that device."

    Design: Difficulty/resource_temporal_overlap/loaner_half_open_interval_on_spare_appliance
    """
    scenario = build_scenario("delivered", spare_appliance=True)
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-20T00:00:00Z")
    repair = open_repair(
        scenario, reason="DEFECT", reported_on="2026-06-20", labor_minutes=30,
        loaner_appliance_id=scenario["spare_id"],
    )
    assert repair["status"] == "IN_LAB"
    assert repair["in_warranty"] is True
    assert repair["billable"] is False
    assert repair["repair_charge_cents"] == 0


def test_loaner_occupied_by_an_open_repair_cannot_be_issued_again(api):
    """PRD §3.9: "Occupancy is a half-open interval running from the repair's `reported_on` up to
    but not including its `returned_on`; a repair still open occupies its loaner from
    `reported_on` onward without end. A new repair naming a loaner whose interval would overlap
    is refused with `ERR_LOANER_UNAVAILABLE`. Because the interval excludes its closing date, a
    device freed on a given date may be issued again to a repair reported on exactly that date."

    Design: Difficulty/resource_temporal_overlap/loaner_half_open_interval_on_spare_appliance
    """
    scenario = build_scenario("delivered", spare_appliance=True)
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-20T00:00:00Z")
    open_repair(
        scenario, reason="DEFECT", reported_on="2026-06-20", labor_minutes=30,
        loaner_appliance_id=scenario["spare_id"],
    )
    validate_error(
        api.create_repair_order(
            {
                "appliance_id": scenario["app_id"],
                "reason": "WEAR",
                "reported_on": "2026-06-25",
                "labor_minutes": 45,
                "loaner_appliance_id": scenario["spare_id"],
            },
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_LOANER_UNAVAILABLE.value,
    )


def test_loaner_freed_on_its_return_date_is_reissuable_the_same_day(api):
    """PRD §3.9: "Because the interval excludes its closing date, a device freed on a given date
    may be issued again to a repair reported on exactly that date."
    PRD §3.9: "`REPAIRED` moves the order `IN_LAB → CLOSED_REPAIRED`, stamps `returned_on` from
    the clock date — which closes the loaner interval and frees the loaner device — and leaves
    `resets_useful_lifetime` false and the appliance's dates untouched."
    PRD §3.9: "`resets_useful_lifetime` is false on every repair, in warranty or out: **no repair
    ever moves `useful_lifetime_end_date` or `warranty_end_date`.**"

    Design: Difficulty/resource_temporal_overlap/loaner_half_open_interval_on_spare_appliance
    """
    scenario = build_scenario("delivered", spare_appliance=True)
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-20T00:00:00Z")
    first = open_repair(
        scenario, reason="DEFECT", reported_on="2026-06-20", labor_minutes=30,
        loaner_appliance_id=scenario["spare_id"],
    )
    set_clock("2026-06-28T00:00:00Z")
    closed = validate_success(
        api.complete_repair_order(
            first["id"], {"outcome": "REPAIRED"}, scenario["dent_headers"]
        )
    )
    assert_calendar_date(closed["returned_on"], "2026-06-28", "RepairOrder.returned_on")

    reissued = validate_success(
        api.create_repair_order(
            {
                "appliance_id": scenario["app_id"],
                "reason": "WEAR",
                "reported_on": "2026-06-28",
                "labor_minutes": 45,
                "loaner_appliance_id": scenario["spare_id"],
            },
            scenario["dent_headers"],
        ),
        201,
    )
    assert reissued["status"] == "IN_LAB"
    assert reissued["billable"] is True
    assert reissued["labor_units"] == 3
    assert reissued["repair_charge_cents"] == 7500

    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert_calendar_date(
        appliance["useful_lifetime_end_date"], "2031-06-01",
        "Appliance.useful_lifetime_end_date",
    )


def _suspend_titration_scenario(api):
    """A disputed PARTIAL report, one open visit and one draft continued-use claim."""
    scenario = build_scenario("efficacy_submitted", efficacy_events=64)
    set_clock("2026-07-07T00:00:00Z")
    disputed = validate_success(
        api.physician_respond_to_efficacy_report(
            scenario["rep_id"],
            {"decision": "DISPUTED", "dispute_reason": "Residual AHI still above target"},
            scenario["phys_headers"],
        )
    )
    scenario["disputed_report"] = disputed
    scenario["open_visit"] = schedule_visit(
        scenario, scheduled_for="2026-07-20", requested_increment_mm=1.00
    )
    scenario["draft_claim"] = draft_claim(
        scenario, claim_type="CONTINUED_USE", billed_cents=20000,
        date_of_service="2026-07-07",
    )
    return scenario


def test_lot_recall_holds_the_device_and_voids_its_open_visit(api):
    """PRD §3.9: "The lot moves `ACTIVE → RECALL_ISSUED` with `recall_issued_on` stamped from the
    clock date, and the counters are computed over every appliance carrying that `lot_id`:
    `affected_device_count` is the number whose `lifecycle_status` is neither `RETIRED` nor
    `REPLACED`, `retired_count` is the number whose `lifecycle_status` is one of those two,
    `remediated_count` starts at 0, and `pending_remediation_count` starts equal to
    `affected_device_count`."
    PRD §3.9: "**Level 1:** every appliance in the lot whose `lifecycle_status` is neither
    `RETIRED` nor `REPLACED` moves `device_hold_status` `NONE → RECALL_HOLD`."
    PRD §3.9: "**Level 2:** every titration visit on those appliances still in `SCHEDULED` or
    `HELD` moves to `VOIDED_BY_HOLD`."

    Design: Difficulty/transitive_cascade/lot_recall_cascade_depth_five
    """
    scenario = _suspend_titration_scenario(api)
    assert scenario["disputed_report"]["outcome"] == "PARTIAL"
    assert scenario["disputed_report"]["status"] == "DISPUTED"

    lot = validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-1187", "recall_severity": "CLASS_II"},
            scenario["admin_headers"],
        )
    )
    assert lot["status"] == "RECALL_ISSUED"
    assert lot["affected_device_count"] == 1
    assert lot["pending_remediation_count"] == 1
    assert lot["remediated_count"] == 0

    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["device_hold_status"] == "RECALL_HOLD"
    visit = validate_success(
        api.get_titration_visit(scenario["open_visit"]["id"], scenario["dent_headers"])
    )
    assert visit["status"] == "VOIDED_BY_HOLD"


def test_lot_recall_suspends_titration_and_withdraws_the_open_report(api):
    """PRD §3.9: "**Level 3:** an appliance left with no `SCHEDULED` or `HELD` visit remaining,
    and which was in `IN_TITRATION`, moves `IN_TITRATION → TITRATION_SUSPENDED`."
    PRD §3.9: "**Level 4:** every efficacy report on those appliances in `DRAFT`, `SUBMITTED` or
    `DISPUTED` moves to `WITHDRAWN`, and its referral's `loop_status` returns to `OPEN` — with
    the referring physician's `open_efficacy_loop_count` recomputed for the reports that were
    `SUBMITTED` or `DISPUTED`."

    Design: Difficulty/transitive_cascade/lot_recall_cascade_depth_five
    """
    scenario = _suspend_titration_scenario(api)
    validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-1187", "recall_severity": "CLASS_II"},
            scenario["admin_headers"],
        )
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["lifecycle_status"] == "TITRATION_SUSPENDED"
    report = validate_success(
        api.get_efficacy_report(scenario["rep_id"], scenario["dent_headers"])
    )
    assert report["status"] == "WITHDRAWN"
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    assert referral["loop_status"] == "OPEN"


def test_lot_recall_voids_the_draft_continued_use_claim(api):
    """PRD §3.9: "**Level 5:** every claim on those appliances with `claim_type` `CONTINUED_USE`
    and `status` `DRAFT` moves to `VOIDED`."
    PRD §2.10: "An appliance's `current_advancement_mm` always equals its
    `starting_advancement_mm` plus the sum of `applied_increment_mm` over exactly those
    `TitrationVisit` rows on that appliance whose `status` is `APPLIED` or `REDUCED`; and it
    always lies between 0.00 and the appliance's `max_protrusive_mm` inclusive."

    Design: Difficulty/transitive_cascade/lot_recall_cascade_depth_five
    """
    scenario = _suspend_titration_scenario(api)
    validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-1187", "recall_severity": "CLASS_II"},
            scenario["admin_headers"],
        )
    )
    voided = validate_success(
        api.get_claim(scenario["draft_claim"]["id"], scenario["billing_headers"])
    )
    assert voided["status"] == "VOIDED"
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(7.75), (
        "the cascade moves no millimetres"
    )


def test_recall_issuance_partitions_the_lot_population(api):
    """PRD §3.9: "The lot moves `ACTIVE → RECALL_ISSUED` with `recall_issued_on` stamped from the
    clock date, and the counters are computed over every appliance carrying that `lot_id`:
    `affected_device_count` is the number whose `lifecycle_status` is neither `RETIRED` nor
    `REPLACED`, `retired_count` is the number whose `lifecycle_status` is one of those two,
    `remediated_count` starts at 0, and `pending_remediation_count` starts equal to
    `affected_device_count`."
    PRD §2.10: "From the instant a recall is issued and forever afterwards, a lot's
    `affected_device_count` equals its `remediated_count` plus its `pending_remediation_count`,
    and the `retired_count` bucket is disjoint from all three."

    Design: Difficulty/compensating_invariant/lot_device_population_conservation_across_remediation
    """
    scenario = build_scenario("delivered", spare_appliance=True)
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-20T00:00:00Z")
    lot = validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-2201", "recall_severity": "CLASS_I"},
            scenario["admin_headers"],
        )
    )
    assert lot["affected_device_count"] == 2
    assert lot["pending_remediation_count"] == 2
    assert lot["remediated_count"] == 0
    assert lot["retired_count"] == 0
    assert_lot_population_conservation(lot)


def test_lot_population_is_conserved_halfway_through_remediation(api):
    """PRD §2.10: "From the instant a recall is issued and forever afterwards, a lot's
    `affected_device_count` equals its `remediated_count` plus its `pending_remediation_count`,
    and the `retired_count` bucket is disjoint from all three."
    PRD §3.9: "On the lot, `remediated_count` rises by 1 and `pending_remediation_count` falls by
    1; when `pending_remediation_count` reaches 0 the lot moves `RECALL_ISSUED →
    REMEDIATION_COMPLETE`, which is terminal, and the lot stops blocking anything."

    Design: Difficulty/compensating_invariant/lot_device_population_conservation_across_remediation
    """
    scenario = build_scenario("delivered", spare_appliance=True)
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-20T00:00:00Z")
    validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-2201", "recall_severity": "CLASS_I"},
            scenario["admin_headers"],
        )
    )
    remediated = validate_success(
        api.remediate_recall(
            scenario["app_id"], {"remediation_action": "Retainer arm replaced"},
            scenario["dent_headers"],
        )
    )
    assert remediated["device_hold_status"] == "NONE"
    lot = validate_success(
        api.get_appliance_lot(scenario["lot_id"], scenario["admin_headers"])
    )
    assert lot["remediated_count"] == 1
    assert lot["pending_remediation_count"] == 1
    assert lot["status"] == "RECALL_ISSUED"
    assert_lot_population_conservation(lot)


def test_lot_closes_only_when_the_last_hold_clears(api):
    """PRD §3.9: "On the lot, `remediated_count` rises by 1 and `pending_remediation_count` falls
    by 1; when `pending_remediation_count` reaches 0 the lot moves `RECALL_ISSUED →
    REMEDIATION_COMPLETE`, which is terminal, and the lot stops blocking anything."
    PRD §3.9: "Remediation is the dentist's, one device at a time, recording a free-text
    `remediation_action`. The appliance's lot must be in `RECALL_ISSUED` and the appliance must
    be on a `RECALL_HOLD` — remediation is the single write that a held device still accepts."

    Design: Difficulty/compensating_invariant/lot_device_population_conservation_across_remediation
    """
    scenario = build_scenario("delivered", spare_appliance=True)
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-20T00:00:00Z")
    validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-2201", "recall_severity": "CLASS_I"},
            scenario["admin_headers"],
        )
    )
    validate_success(
        api.remediate_recall(
            scenario["app_id"], {"remediation_action": "Retainer arm replaced"},
            scenario["dent_headers"],
        )
    )
    validate_success(
        api.remediate_recall(
            scenario["spare_id"], {"remediation_action": "Retainer arm replaced"},
            scenario["dent_headers"],
        )
    )
    lot = validate_success(
        api.get_appliance_lot(scenario["lot_id"], scenario["admin_headers"])
    )
    assert lot["remediated_count"] == 2
    assert lot["pending_remediation_count"] == 0
    assert lot["status"] == "REMEDIATION_COMPLETE"
    assert_lot_population_conservation(lot)
    spare = validate_success(
        api.get_appliance(scenario["spare_id"], scenario["dent_headers"])
    )
    assert spare["device_hold_status"] == "NONE"


def test_recall_response_already_carries_the_cascaded_counters(api):
    """PRD §2.11: "Wherever a cascade writes to a row, that row's `updated_at` is refreshed and
    its `version` rises by exactly 1 — once for the whole request, as §2.5 requires — and the
    cascade is atomic with the operation that triggered it: either every level lands or the
    request fails and none does."
    PRD §3.9: "**Level 1:** every appliance in the lot whose `lifecycle_status` is neither
    `RETIRED` nor `REPLACED` moves `device_hold_status` `NONE → RECALL_HOLD`."

    Design: Corner/consistency_model/recall_response_already_carries_the_cascaded_counters
    """
    scenario = build_scenario("delivered")
    lot = validate_success(
        api.recall_appliance_lot(
            scenario["lot_id"],
            {"notice_reference": "FDA-2026-4402", "recall_severity": "CLASS_III"},
            scenario["admin_headers"],
        )
    )
    assert lot["status"] == "RECALL_ISSUED"
    assert lot["affected_device_count"] == 1
    assert lot["pending_remediation_count"] == 1
    assert_calendar_date(
        lot["recall_issued_on"], "2026-06-01", "ApplianceLot.recall_issued_on"
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["device_hold_status"] == "RECALL_HOLD"
