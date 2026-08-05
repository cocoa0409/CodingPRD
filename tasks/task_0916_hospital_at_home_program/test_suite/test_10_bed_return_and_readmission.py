"""Converting an escalation into a physical bed return, and coming back home."""

from test_helpers import (
    ApiErrorId,
    assert_bed_census,
    assert_day_ledger,
    assert_same_instant,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMITTING_PHYSICIAN, PROGRAM_ADMIN


def test_bed_return_conversion_flips_the_escalation_and_the_episode(api):
    """PRD §3.8: "When it fires, the following all happen in one request: the
    escalation moves to `BED_RETURN_CONVERTED`, which is terminal; the episode's
    **earliest-created held reservation**, chosen by `held_at` ascending with
    `created_at` ascending breaking ties, moves `HELD → OCCUPIED` provided the
    logical clock is at or before its `hold_expires_at`, stamping `occupied_at`
    from the clock, decrementing the unit's `held_bed_count`, incrementing its
    `occupied_bed_count` and advancing the reservation's `version` by 1; the
    episode moves `ESCALATED → RETURNED_TO_FACILITY` with `returned_at` stamped
    from the clock"

    Design: Difficulty/transitive_cascade/bed_return_conversion_cascades_five_levels_to_voided_claim
    """
    parts = fx.setup_bed_return_cascade()
    episode_id = parts["episode"]["id"]

    converted = validate_success(
        api.convert_escalation_to_bed_return(
            parts["escalation"]["id"], ADMITTING_PHYSICIAN
        )
    )
    assert converted["status"] == "BED_RETURN_CONVERTED"

    episode = fx.read_episode(episode_id)
    assert episode["status"] == "RETURNED_TO_FACILITY"
    assert_same_instant(
        episode["returned_at"], "2026-06-02T13:03:00Z", "returned_at"
    )

    reservation = validate_success(
        api.get_bed_reservation(parts["reservation"]["id"], ADMITTING_PHYSICIAN)
    )
    assert reservation["status"] == "OCCUPIED"
    assert_bed_census(
        validate_success(api.get_inpatient_unit(parts["unit"]["id"], PROGRAM_ADMIN)),
        available=1,
        held=0,
        occupied=1,
    )


def test_bed_return_conversion_releases_the_kit_and_carves_the_current_day_out(api):
    """PRD §3.5: "the kit whose `assigned_episode_id` is that episode and whose
    `status` is `DEPLOYED` moves `DEPLOYED → IN_REFURB`, its
    `assigned_episode_id` is cleared to null, its `refurb_cycle_count` is
    incremented by 1, every one of its components sitting in `DEPLOYED` moves to
    `PENDING_RECONCILIATION`, and the kit's `version` advances by 1."
    PRD §3.5: "The release also reaches sideways into the day ledger: the
    released episode's compliance record whose `service_date` equals the UTC
    calendar date of the logical clock has its `kit_deployed_all_day` set to
    false, and if that record is still `PENDING` it is immediately scored and
    finalized through the daily verdict described in §3.4."
    PRD §3.4: "Because the clauses are ordered, a waiver day that satisfied the
    first three clauses and lost only its kit is the sole way `KIT_NOT_DEPLOYED`
    is ever produced."

    Design: Difficulty/transitive_cascade/bed_return_conversion_cascades_five_levels_to_voided_claim
    """
    parts = fx.setup_bed_return_cascade()
    episode_id = parts["episode"]["id"]

    fx.convert_to_bed_return(parts["escalation"]["id"])

    kit = validate_success(api.get_device_kit(parts["kit"]["id"], PROGRAM_ADMIN))
    assert kit["status"] == "IN_REFURB"
    assert kit["assigned_episode_id"] is None
    assert kit["refurb_cycle_count"] == 1

    component = fx.read_component(parts["kit"]["id"], parts["component"]["id"])
    assert component["reconciliation_status"] == "PENDING_RECONCILIATION"

    current_day = fx.compliance_day_for(episode_id, "2026-06-02")
    assert current_day["kit_deployed_all_day"] is False
    assert current_day["qualified_in_person_visit_count"] == 2, (
        "the day carries the two in-person visits the waiver track requires"
    )
    assert current_day["physician_eval_present"] is True
    assert current_day["monitoring_lapse_minutes"] == 0
    assert current_day["status"] == "CARVED_OUT"
    assert current_day["carve_out_reason"] == "KIT_NOT_DEPLOYED", (
        "clauses 1 to 3 all pass, so only the kit clause can fail"
    )


def test_bed_return_conversion_voids_the_built_claim_and_settles_the_siblings(api):
    """PRD §3.4: "**every** billing claim of that episode still sitting in
    `BUILT` is driven to `VOIDED`, and the record's `version` advances by 1."
    PRD §3.7: "When the episode is converted to a facility bed return, each of
    its plans in `ACTIVE` moves `ACTIVE → SUSPENDED`, `suspension_day_count` is
    incremented by exactly 1 — each suspension permanently forfeits one credited
    day — the plan's `credited_day_count` and `meal_credit_total_usd` are
    recomputed, the episode's `meal_credit_total_usd` is recomputed with them,
    and the plan's `version` advances by 1."
    PRD §3.6: "Separately, an order in any of `PENDING_AUTHORIZATION`,
    `AUTHORIZED`, `OUT_FOR_DELIVERY` or `REFUSED` is driven to `CANCELLED` by the
    system when its episode is converted to a facility bed return, with the
    order's `version` advancing by 1."

    Design: Difficulty/transitive_cascade/bed_return_conversion_cascades_five_levels_to_voided_claim
    """
    parts = fx.setup_bed_return_cascade()
    episode_id = parts["episode"]["id"]

    fx.convert_to_bed_return(parts["escalation"]["id"])

    claim = fx.read_claim(episode_id, parts["claim"]["id"])
    assert claim["status"] == "VOIDED"

    meal_plan = fx.read_meal_plan(episode_id, parts["meal_plan"]["id"])
    assert meal_plan["status"] == "SUSPENDED"
    assert meal_plan["suspension_day_count"] == 1

    order = fx.read_delivery_order(episode_id, parts["delivery_order"]["id"])
    assert order["status"] == "CANCELLED"

    episode = fx.read_episode(episode_id)
    assert_day_ledger(episode, service=2, billable=1, carved_out=1, pending=0)

    untouched = fx.compliance_day_for(episode_id, "2026-06-01")
    assert untouched["status"] == "COMPLIANT", (
        "the already-finalized 2026-06-01 day is untouched by the conversion"
    )


# ─── Conversion blocked by a lapsed hold ───────────────────────────────────

def test_hold_expires_lazily_before_the_conversion_is_attempted(api):
    """PRD §3.8: "A reservation still in `HELD` whose `hold_expires_at` the
    logical clock has passed — strictly greater, so a clock sitting exactly on
    `hold_expires_at` has not yet expired it — moves `HELD → EXPIRED` at the
    moment anyone looks: when that single reservation is read, when its inpatient
    unit is read, and when a new hold is attempted against the same `unit_id`."
    PRD §3.8: "Expiring a reservation decrements the unit's `held_bed_count` and
    increments its `available_bed_count`, and advances the reservation's
    `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/bed_return_conversion_blocked_when_reservation_has_expired
    """
    parts = fx.setup_escalated_episode_with_held_bed(
        clock="2026-06-02T09:00:00Z",
        eval_at="2026-06-02T07:00:00Z",
        reason="FALL",
        total_beds=2,
    )
    reservation = parts["reservation"]
    assert_same_instant(
        reservation["hold_expires_at"], "2026-06-02T11:32:00Z", "hold_expires_at"
    )

    fx.set_clock("2026-06-02T11:33:00Z")
    expired = validate_success(
        api.get_bed_reservation(reservation["id"], ADMITTING_PHYSICIAN)
    )
    assert expired["status"] == "EXPIRED"
    assert expired["occupied_at"] is None

    assert_bed_census(
        validate_success(api.get_inpatient_unit(parts["unit"]["id"], PROGRAM_ADMIN)),
        available=2,
        held=0,
        occupied=0,
    )


def test_bed_return_conversion_is_blocked_when_no_reservation_is_still_held(api):
    """PRD §3.8: "It requires an escalation in `TIER3_ACKED`, `TIER4_OPEN` or
    `TIER4_ACKED`, an episode currently in `ESCALATED`, and at least one
    reservation of that episode still in `HELD`; any of the three missing is
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/bed_return_conversion_blocked_when_reservation_has_expired
    """
    parts = fx.setup_escalated_episode_with_held_bed(
        clock="2026-06-02T09:00:00Z",
        eval_at="2026-06-02T07:00:00Z",
        reason="FALL",
        total_beds=2,
    )
    episode_id = parts["episode"]["id"]
    escalation_id = parts["escalation"]["id"]

    fx.set_clock("2026-06-02T11:33:00Z")
    validate_success(
        api.get_bed_reservation(parts["reservation"]["id"], ADMITTING_PHYSICIAN)
    )

    validate_error(
        api.convert_escalation_to_bed_return(escalation_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    escalation = fx.read_escalation(episode_id, escalation_id)
    assert escalation["status"] == "TIER4_OPEN"

    episode = fx.read_episode(episode_id)
    assert episode["status"] == "ESCALATED"
    assert episode["returned_at"] is None

    assert_bed_census(
        validate_success(api.get_inpatient_unit(parts["unit"]["id"], PROGRAM_ADMIN)),
        available=2,
        held=0,
        occupied=0,
    )


# ─── Readmission closes the cycle ──────────────────────────────────────────

def test_readmission_closes_the_episode_cycle(api):
    """PRD §3.8: "The episode must be in `RETURNED_TO_FACILITY`, and at least one
    kit somewhere in inventory must be `AVAILABLE`, because a readmission that
    cannot redeploy monitoring hardware is not a readmission at all; failing
    either precondition is `ERR_INVALID_STATE`."
    PRD §3.8: "Success moves the episode `RETURNED_TO_FACILITY → ACTIVE`,
    increments `readmission_count` by 1, drives every reservation of that episode
    in `HELD` or `OCCUPIED` to `RELEASED` — decrementing whichever of
    `held_bed_count` or `occupied_bed_count` that reservation was counted in,
    incrementing the unit's `available_bed_count`, and advancing each
    reservation's `version` by 1 — resumes every meal plan of the episode in
    `SUSPENDED` back to `ACTIVE`, back-fills every still-missing UTC date in the
    inclusive range from the `admitted_at` date to the clock date as a `PENDING`
    compliance record, recomputes `service_day_count`, `billable_day_count`,
    `carved_out_day_count` and `pending_day_count`, and advances the episode's
    `version` by 1."

    Design: Corner/state_machines/episode_readmit_closes_the_cycle_and_releases_bed_and_meal_plan
    """
    parts = fx.setup_active_episode(
        clock="2026-06-02T09:00:00Z",
        eval_at="2026-06-02T07:00:00Z",
        mrn="MRN-RA",
        full_name="Rita Readmit",
    )
    episode_id = parts["episode"]["id"]

    spare_kit = fx.register_kit(asset_tag="KIT-RA1")
    meal_plan = fx.open_meal_plan(episode_id, diet_code="NONE", daily_delivery_count=2)

    escalation, _ = fx.escalate_to_tier(
        episode_id, 3, "2026-06-02T09:00:00Z", acuity="STANDARD", reason="FALL"
    )
    unit = fx.register_unit(unit_code="UNIT-RA", total_beds=2)
    reservation = fx.hold_bed(unit["id"], episode_id, unit["version"])
    fx.set_clock("2026-06-02T10:03:00Z")
    escalation = validate_success(
        api.promote_escalation(escalation["id"], PROGRAM_ADMIN)
    )
    assert escalation["status"] == "TIER4_OPEN"
    fx.convert_to_bed_return(escalation["id"])

    readmitted = validate_success(
        api.readmit_episode(episode_id, ADMITTING_PHYSICIAN)
    )
    assert readmitted["status"] == "ACTIVE"
    assert readmitted["readmission_count"] == 1

    released = validate_success(
        api.get_bed_reservation(reservation["id"], ADMITTING_PHYSICIAN)
    )
    assert released["status"] == "RELEASED"
    assert_bed_census(
        validate_success(api.get_inpatient_unit(unit["id"], PROGRAM_ADMIN)),
        available=2,
        held=0,
        occupied=0,
    )

    resumed = fx.read_meal_plan(episode_id, meal_plan["id"])
    assert resumed["status"] == "ACTIVE"
    assert resumed["suspension_day_count"] == 1, (
        "the forfeited day is not restored by resuming the plan"
    )

    assert (
        fx.read_escalation(episode_id, escalation["id"])["status"]
        == "BED_RETURN_CONVERTED"
    )
    assert fx.read_episode(episode_id)["open_escalation_count"] == 0

    assert (
        validate_success(api.get_device_kit(spare_kit["id"], PROGRAM_ADMIN))["status"]
        == "AVAILABLE"
    ), "readmission does not itself deploy a kit"
