"""Warranty claims: proration variants, pinned snapshots, eligibility gates,
the appeal cycle, recovery posting, SoD, and OCC on claim creation."""
from test_helpers import (
    ApiErrorId,
    claim_event,
    create_claim,
    create_work_order_payload,
    get_success_data,
    get_wo_claims,
    line_event,
    make_fleet_manager_headers,
    make_warranty_clerk_headers,
    new_bus,
    new_mechanic,
    new_part,
    new_qa_mechanic,
    new_work_order,
    reserve_line,
    schedule_wo,
    setup_approved_claim,
    setup_closed_wo_scenario,
    start_wo,
    issue_line,
    add_labor,
    make_mechanic_headers,
    validate_error,
    validate_success,
    wo_event,
    wo_version,
)
from test_helpers import fixtures as fx


class TestExtendedProrationVariants:
    """Identical CLOSED work order (eligible 72000c): MILES vs TIME basis."""

    def _setup(self):
        bus = new_bus(
            fleet_number="B100", vin="VINB100", model_year=2020,
            in_service_date="2025-08-01", initial_odometer_miles=200_000,
            base_warranty_expiry_miles=100_000,
            base_warranty_expiry_date="2026-01-01",
            extended_warranty_limit_miles=400_000,
            extended_warranty_limit_months=24,
        )
        part = new_part(sku="P-ELG", description="Eligible sensor",
                        unit_cost_cents=23_000, warranty_eligible=True)
        lead = new_mechanic(name="Lead Tech", employee_ref="E1")
        wo = create_claim_ready_wo(bus, lead, part)
        return bus, wo

    def test_miles_basis_prorates_by_odometer_headroom(self, api):
        """PRD §3.10: "For `EXTENDED`, the eligible basis is the same as
        `BASE_OEM`, then prorated: with `proration_basis` `MILES`, the fraction
        is the greater of zero and (`extended_warranty_limit_miles` minus
        `odometer_at_open`) divided by `extended_warranty_limit_miles`"
        PRD §3.10: "For `BASE_OEM`, `eligible_cents` is the frozen
        `labor_total_cents` plus the sum of frozen line totals whose part is
        `warranty_eligible`."

        eligible = 46000 parts + 26000 labor = 72000; fraction
        (400000-200000)/400000 = 0.5 -> claimed 36000.

        Design: Difficulty/dual_variant_calc/warranty_proration_miles_vs_time_divergence
        """
        _, wo = self._setup()
        claim = create_claim(wo["id"], claim_type="EXTENDED",
                             proration_basis="MILES")
        submitted = validate_success(claim_event(claim["id"], "SUBMIT"))
        assert submitted["eligible_cents"] == 72_000
        assert submitted["claimed_cents"] == 36_000, (
            f"MILES fraction 0.5 must halve 72000; got "
            f"{submitted['claimed_cents']}"
        )

    def test_time_basis_prorates_by_calendar_headroom_and_diverges(self, api):
        """PRD §3.10: "with `proration_basis` `TIME`, the fraction is the
        greater of zero and (`extended_warranty_limit_months` multiplied by 30
        minus the days between `opened_date` and `in_service_date`) divided by
        (`extended_warranty_limit_months` multiplied by 30)."

        opened 2026-08-01 minus in-service 2025-08-01 = 365 days; fraction
        (720-365)/720 -> round_half_up(72000 * 355/720) = 35500, diverging
        from the MILES result on identical work-order data.

        Design: Difficulty/dual_variant_calc/warranty_proration_miles_vs_time_divergence
        """
        _, wo = self._setup()
        time_claim = create_claim(wo["id"], claim_type="EXTENDED",
                                  proration_basis="TIME")
        time_sub = validate_success(claim_event(time_claim["id"], "SUBMIT"))
        assert time_sub["eligible_cents"] == 72_000
        assert time_sub["claimed_cents"] == 35_500, (
            f"TIME fraction 355/720 of 72000 is 35500; got "
            f"{time_sub['claimed_cents']}"
        )

        miles_claim = create_claim(wo["id"], claim_type="EXTENDED",
                                   proration_basis="MILES")
        miles_sub = validate_success(claim_event(miles_claim["id"], "SUBMIT"))
        assert miles_sub["claimed_cents"] == 36_000
        assert miles_sub["claimed_cents"] != time_sub["claimed_cents"]


def create_claim_ready_wo(bus, lead, part):
    """Closed CORRECTIVE WO: 2 eligible units consumed + 4h AM labor."""
    wo = new_work_order(bus["id"], lead_mechanic_id=lead["id"],
                        planned_start_date="2026-08-02",
                        planned_end_date="2026-08-03", estimated_labor_hours=4,
                        estimated_cost_cents=72_000)
    schedule_wo(wo["id"])
    start_wo(wo["id"])
    line = reserve_line(wo["id"], part["id"], qty=2)
    issue_line(line["id"])
    get_success_data(line_event(line["id"], "CONSUME"))
    add_labor(wo["id"], lead, work_date="2026-08-02", hours=4)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    qa = new_qa_mechanic()
    return get_success_data(
        wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))
    )


class TestDeniedAppealCycle:
    """DENIED -> APPEAL -> SUBMITTED may repeat exactly twice."""

    def _setup(self):
        bus, wo = setup_closed_wo_scenario(
            bus_overrides={
                "fleet_number": "B500", "vin": "VINB500",
                "initial_odometer_miles": 50_000,
                "base_warranty_expiry_miles": 100_000,
                "base_warranty_expiry_date": "2027-01-01",
            },
            part=new_part(sku="P-INJ", description="Injector",
                          unit_cost_cents=10_000, warranty_eligible=True),
            wo_overrides={"priority": "URGENT",
                          "planned_start_date": "2026-08-02",
                          "planned_end_date": "2026-08-02",
                          "estimated_cost_cents": 16_500},
        )
        claims = get_wo_claims(wo["id"])
        assert len(claims) == 1
        return wo, claims[0]

    def test_first_appeal_returns_to_submitted_with_count_one(self, api):
        """PRD §3.10: "A denied claim may be appealed, returning it to
        `SUBMITTED` and incrementing `appeal_count`, but only twice — an appeal
        with `appeal_count` already 2 is rejected with
        `ERR_APPEAL_LIMIT_EXCEEDED`."
        PRD §3.10: "For `BASE_OEM`, `eligible_cents` is the frozen
        `labor_total_cents` plus the sum of frozen line totals whose part is
        `warranty_eligible`."

        SUBMIT pins claimed 16500 (10000 eligible part + 6500 labor, fraction
        1 inside base warranty).

        Design: Difficulty/non_linear_state_machine/warranty_claim_denied_appeal_cycle_with_cap
        """
        _, claim = self._setup()
        clerk = make_warranty_clerk_headers("clerk-9")

        submitted = validate_success(claim_event(claim["id"], "SUBMIT",
                                                 headers=clerk))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["claimed_cents"] == 16_500

        denied = validate_success(
            claim_event(claim["id"], "RECORD_OEM_DECISION", headers=clerk,
                        decision_outcome="DENIED")
        )
        assert denied["status"] == "DENIED"
        assert denied["approved_cents"] == 0

        appealed = validate_success(
            claim_event(claim["id"], "APPEAL", headers=clerk,
                        appeal_note="resubmit with teardown photos")
        )
        assert appealed["status"] == "SUBMITTED", "appeal cycles back to SUBMITTED"
        assert appealed["appeal_count"] == 1

    def test_third_appeal_rejected_at_the_cap(self, api):
        """PRD §3.10: "A denied claim may be appealed, returning it to
        `SUBMITTED` and incrementing `appeal_count`, but only twice — an appeal
        with `appeal_count` already 2 is rejected with
        `ERR_APPEAL_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_denied_appeal_cycle_with_cap
        """
        _, claim = self._setup()
        clerk = make_warranty_clerk_headers("clerk-9")

        claim_event(claim["id"], "SUBMIT", headers=clerk)
        claim_event(claim["id"], "RECORD_OEM_DECISION", headers=clerk,
                    decision_outcome="DENIED")
        first = validate_success(claim_event(claim["id"], "APPEAL",
                                             headers=clerk))
        assert first["appeal_count"] == 1
        claim_event(claim["id"], "RECORD_OEM_DECISION", headers=clerk,
                    decision_outcome="DENIED")
        second = validate_success(claim_event(claim["id"], "APPEAL",
                                              headers=clerk))
        assert second["appeal_count"] == 2
        claim_event(claim["id"], "RECORD_OEM_DECISION", headers=clerk,
                    decision_outcome="DENIED")

        res = claim_event(claim["id"], "APPEAL", headers=clerk)
        validate_error(res, ApiErrorId.ERR_APPEAL_LIMIT_EXCEEDED)
        after = get_success_data(api.get_warranty_claim(claim["id"], fx.WC))
        assert after["status"] == "DENIED", "the claim stays DENIED at the cap"
        assert after["appeal_count"] == 2


def test_warranty_auto_draft_on_base_eligible_wo_close(api):
    """PRD §3.4: "Finally, if the `wo_type` is `CORRECTIVE`, `EMISSIONS`, or
    `CAMPAIGN` and the bus was inside its base warranty at the work order's
    open, a draft warranty claim is auto-created with `auto_created` set to
    true, ready for a `WarrantyClerk` to review and submit (see §3.10)."
    PRD §3.10: "At creation the claim's `bus_id` is denormalized from the work
    order, and the work order's `version` is incremented by one."

    Design: Corner/state_machines/warranty_auto_draft_on_base_eligible_wo_close
    """
    bus, wo = setup_closed_wo_scenario(
        bus_overrides={"fleet_number": "T8", "vin": "VINT8",
                       "initial_odometer_miles": 50_000,
                       "base_warranty_expiry_miles": 100_000,
                       "base_warranty_expiry_date": "2027-01-01"}
    )
    claims = get_wo_claims(wo["id"])
    assert len(claims) == 1, "exactly one claim is auto-created on close"
    claim = claims[0]
    assert claim["auto_created"] is True
    assert claim["status"] == "DRAFT"
    assert claim["bus_id"] == bus["id"]
    assert claim["work_order_id"] == wo["id"]


def test_warranty_claim_snapshot_ignores_post_submit_core_credit(api):
    """PRD §3.10: "The evaluation order is fixed: first the work order's
    `labor_total_cents` and parts line amounts are frozen as of the submit;
    then only core credits posted strictly before the submit are subtracted;
    then `eligible_cents` is computed per claim type from the frozen basis;
    then the proration fraction is applied; then a single final round-half-up
    produces `claimed_cents`."
    PRD §3.10: "Once submitted, `eligible_cents` and `claimed_cents` are pinned
    and never recomputed, even if later core credits or labor adjustments would
    otherwise change the basis."
    PRD §3.5: "`parts_net_cents` is `parts_total_cents` minus
    `core_credits_cents`, and `total_cost_cents` is `labor_total_cents` plus
    `parts_net_cents`."

    Design: Corner/calculations/warranty_claim_snapshot_ignores_post_submit_core_credit
    """
    part = new_part(sku="P-WS1", description="Alternator",
                    part_class="REBUILDABLE_CORE", unit_cost_cents=25_000,
                    initial_on_hand=3, warranty_eligible=True,
                    core_charge_cents=10_000)
    bus = new_bus(fleet_number="WS1", vin="VINWS1",
                  initial_odometer_miles=50_000,
                  base_warranty_expiry_miles=100_000,
                  base_warranty_expiry_date="2027-01-01")
    lead = new_mechanic(name="Lead", employee_ref="WS1A")
    qa = new_qa_mechanic()
    wo = new_work_order(bus["id"], lead_mechanic_id=lead["id"],
                        estimated_cost_cents=31_500)
    schedule_wo(wo["id"])
    start_wo(wo["id"])
    line = reserve_line(wo["id"], part["id"], qty=1)
    issue_line(line["id"])
    get_success_data(line_event(line["id"], "CONSUME"))
    add_labor(wo["id"], lead, work_date="2026-08-02", hours=1)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))

    claim = get_wo_claims(wo["id"])[0]
    submitted = validate_success(
        claim_event(claim["id"], "SUBMIT",
                    headers=make_warranty_clerk_headers("clerk-9"))
    )
    assert submitted["eligible_cents"] == 31_500, (
        "25000 eligible parts + 6500 labor, zero core credits before submit"
    )
    assert submitted["claimed_cents"] == 31_500, "BASE_OEM applies fraction 1"

    validate_success(line_event(line["id"], "CORE_RETURN", core_condition="GOOD"))
    wo_after = get_success_data(api.get_work_order(wo["id"], fx.WC))
    assert wo_after["core_credits_cents"] == 10_000
    assert wo_after["parts_net_cents"] == 15_000, (
        "parts_net 25000 - 10000 per the PRD §3.5 identity"
    )
    assert wo_after["total_cost_cents"] == 21_500

    claim_after = get_success_data(api.get_warranty_claim(claim["id"], fx.WC))
    assert claim_after["claimed_cents"] == 31_500, (
        "the pinned snapshot is immutable against the later core credit"
    )
    assert claim_after["eligible_cents"] == 31_500


def test_warranty_base_claim_outside_warranty_rejected(api):
    """PRD §3.10: "A `BASE_OEM` claim requires the work order's
    `odometer_at_open` to be at or below the bus's `base_warranty_expiry_miles`
    and the `opened_date` to be on or before the `base_warranty_expiry_date`."
    PRD §3.10: "A violation of any of these gates is rejected with
    `ERR_WARRANTY_NOT_ELIGIBLE`."

    odometer_at_open 200000 > base_warranty_expiry_miles 100000.

    Design: Corner/validations/warranty_base_claim_outside_warranty_rejected
    """
    bus, wo = setup_closed_wo_scenario(
        bus_overrides={
            "fleet_number": "Y11", "vin": "VINY11", "model_year": 2020,
            "in_service_date": "2025-01-01", "initial_odometer_miles": 200_000,
            "base_warranty_expiry_miles": 100_000,
            "base_warranty_expiry_date": "2026-01-01",
        }
    )
    res = api.create_warranty_claim(
        {
            "work_order_id": wo["id"],
            "claim_type": "BASE_OEM",
            "expected_work_order_version": wo_version(wo["id"]),
        },
        fx.WC,
    )
    validate_error(res, ApiErrorId.ERR_WARRANTY_NOT_ELIGIBLE)


def test_recovery_exceeding_approved_rejected(api):
    """PRD §3.10: "The `received_cents` must not exceed `approved_cents`
    (otherwise `ERR_RECOVERY_EXCEEDS_APPROVED`), and the segregation-of-duties
    rule of §2.12 requires the caller's `X-User-ID` to differ from the claim's
    `submitted_by_user_id` (otherwise `ERR_SOD_RECOVERY_SELF_APPROVAL`)."

    Design: Corner/validations/recovery_exceeding_approved_rejected
    """
    part = new_part(sku="P-Y12", description="Pump", unit_cost_cents=10_000,
                    warranty_eligible=True)
    _, _, claim = setup_approved_claim(part=part, submitter_id="clerk-9")
    assert claim["status"] == "APPROVED"
    assert claim["approved_cents"] == 16_500

    res = claim_event(claim["id"], "POST_RECOVERY",
                      headers=make_fleet_manager_headers("fm-7"),
                      received_cents=17_000)
    validate_error(res, ApiErrorId.ERR_RECOVERY_EXCEEDS_APPROVED)
    after = get_success_data(api.get_warranty_claim(claim["id"], fx.WC))
    assert after["status"] == "APPROVED"


def test_warranty_clerk_cannot_post_recovery_forbidden(api):
    """PRD §3.10: "Warranty recovery is run by the `WarrantyClerk`, with cash
    posting reserved to the `FleetManager`."
    PRD §3.10: "Cash recovery is posted by a `FleetManager` from `APPROVED` or
    `PARTIALLY_APPROVED`."
    PRD §2.1: "A request whose role is not in the endpoint's authorized set is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/warranty_clerk_cannot_post_recovery_forbidden
    """
    _, _, claim = setup_approved_claim(submitter_id="clerk-9")
    assert claim["status"] == "APPROVED"

    res = claim_event(claim["id"], "POST_RECOVERY",
                      headers=make_warranty_clerk_headers("clerk-9"),
                      received_cents=6_500)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    after = get_success_data(api.get_warranty_claim(claim["id"], fx.WC))
    assert after["status"] == "APPROVED"


def test_sod_recovery_self_approval_rejected_then_other_manager_succeeds(api):
    """PRD §2.12: "Separately, a warranty clerk may not post the cash recovery
    against a claim they themselves submitted. On the post-recovery transition
    of a warranty claim, the caller's `X-User-ID` must not equal the claim's
    `submitted_by_user_id`; a violation is rejected with
    `ERR_SOD_RECOVERY_SELF_APPROVAL` (HTTP 403)."
    PRD §3.10: "On posting, `received_cents` and `recovered_by_user_id` are
    recorded, `variance_cents` is computed as `approved_cents` minus
    `received_cents`, and the claim moves to `RECOVERED`."

    Design: Corner/rbac/sod_recovery_self_approval_rejected_then_other_manager_succeeds
    """
    _, _, claim = setup_approved_claim(submitter_id="clerk-9")
    assert claim["status"] == "APPROVED"

    same_person = claim_event(
        claim["id"], "POST_RECOVERY",
        headers=make_fleet_manager_headers("clerk-9"), received_cents=6_500,
    )
    validate_error(same_person, ApiErrorId.ERR_SOD_RECOVERY_SELF_APPROVAL)

    recovered = validate_success(
        claim_event(claim["id"], "POST_RECOVERY",
                    headers=make_fleet_manager_headers("fm-7"),
                    received_cents=6_500)
    )
    assert recovered["status"] == "RECOVERED"
    assert recovered["received_cents"] == 6_500
    assert recovered["variance_cents"] == 0
    assert recovered["recovered_by_user_id"] == "fm-7"


def test_occ_stale_work_order_version_on_second_claim(api):
    """PRD §2.9: "When creating a warranty claim, the request must carry
    `expected_work_order_version`, set to the `version` of the target
    `WorkOrder` as the client last observed it. A mismatch with the work
    order's current `version` is rejected with
    `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), preventing a claim from being
    built on a labor or parts basis the client has not seen."
    PRD §3.10: "At creation the claim's `bus_id` is denormalized from the work
    order, and the work order's `version` is incremented by one."

    Design: Corner/cross_cutting/occ_stale_work_order_version_on_second_claim
    """
    bus, wo = setup_closed_wo_scenario(
        bus_overrides={"fleet_number": "O2", "vin": "VINO2",
                       "initial_odometer_miles": 50_000,
                       "base_warranty_expiry_miles": 100_000,
                       "base_warranty_expiry_date": "2027-01-01"}
    )
    observed = wo_version(wo["id"])

    first = validate_success(
        api.create_warranty_claim(
            {
                "work_order_id": wo["id"],
                "claim_type": "BASE_OEM",
                "expected_work_order_version": observed,
            },
            fx.WC,
        ),
        201,
    )
    assert first["status"] == "DRAFT"

    stale = api.create_warranty_claim(
        {
            "work_order_id": wo["id"],
            "claim_type": "BASE_OEM",
            "expected_work_order_version": observed,
        },
        fx.WC,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION)
