"""Shoot-day readiness gate: monitors, deposits, walkthroughs, closures, OCC."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_shoot_day,
    create_deposit_account_payload,
    create_street_closure_payload,
    get_success_data,
    setup_confirmed_monitor,
    setup_funded_deposit,
    setup_issued_permit,
    setup_planned_shoot_day,
    setup_production_with_executed_agreement,
    setup_ready_day,
    setup_signed_pre_walkthrough,
    setup_submitted_permit,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _fresh_day(api, production_id, day_id):
    return get_success_data(api.get_shoot_day(production_id, day_id, LM))


# ---------------------------------------------------------------------------
# Difficulty: monitors_required multibranch threshold formula
# ---------------------------------------------------------------------------

def test_monitors_required_all_branches_fire(api):
    """PRD §3.8: "the base is `shoot_hours_per_day` divided by 8 and rounded up to
    a whole number; one extra monitor is added when the permit's `closed_lanes`
    reaches or exceeds the jurisdiction's `police_monitor_lane_threshold`; and one
    further extra is added when the production's `cast_size` is strictly greater
    than the `large_cast_threshold`."
    PRD §3.8: "A new shoot day is born `PLANNED`, and the server computes its
    `monitors_required` immediately"

    Design: Difficulty/combinatorial_formula/monitors_required_multibranch_threshold_formula
    """
    scenario = setup_production_with_executed_agreement(
        production_overrides={"cast_size": 60},
    )
    permit, _, _ = setup_issued_permit(
        scenario, clock="2026-08-03T09:00:00Z", closed_lanes=2, shoot_hours_per_day=12,
    )
    day = setup_planned_shoot_day(scenario, permit, planned_hours=12)

    # ceil(12/8)=2, +1 (lanes 2 >= threshold 2), +1 (cast 60 > 50) -> 4.
    assert_shoot_day(day)
    assert day["monitors_required"] == 4, (
        f"Expected 2 base + 1 lane + 1 cast = 4, got {day['monitors_required']}"
    )
    assert day["monitors_confirmed"] == 0
    assert day["status"] == "PLANNED"


def test_monitors_required_no_branch_fires(api):
    """PRD §3.8: "the base is `shoot_hours_per_day` divided by 8 and rounded up to
    a whole number; one extra monitor is added when the permit's `closed_lanes`
    reaches or exceeds the jurisdiction's `police_monitor_lane_threshold`; and one
    further extra is added when the production's `cast_size` is strictly greater
    than the `large_cast_threshold`."

    Design: Difficulty/combinatorial_formula/monitors_required_multibranch_threshold_formula
    """
    scenario = setup_production_with_executed_agreement(
        production_overrides={"cast_size": 40},
    )
    permit, _, _ = setup_issued_permit(
        scenario, clock="2026-08-03T09:00:00Z", closed_lanes=1, shoot_hours_per_day=8,
    )
    day = setup_planned_shoot_day(scenario, permit, planned_hours=8)

    # ceil(8/8)=1, lanes 1 < threshold 2, cast 40 not > 50 -> 1.
    assert day["monitors_required"] == 1, (
        f"Expected base-only monitors_required 1, got {day['monitors_required']}"
    )
    assert day["monitors_confirmed"] == 0
    assert day["status"] == "PLANNED"


def test_monitors_required_police_type_gate_not_just_count(api):
    """PRD §3.8: "When the lane trigger fires, at least one of the assignments
    counted toward coverage must be of `monitor_type` `POLICE`, or the readiness
    gate fails even when the numeric count is met."
    PRD §3.8: "`monitors_confirmed` is at least `monitors_required` with the
    police-type requirement satisfied when the lane threshold fired (else
    `ERR_MONITOR_SHORTFALL`)"

    Design: Corner/calculations/monitors_required_police_type_gate_not_just_count
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit, _, _ = setup_issued_permit(
        scenario, clock="2026-08-03T09:00:00Z", closed_lanes=2, shoot_hours_per_day=8,
    )
    # Lanes > 0, so an APPROVED closure must also exist for mark-ready.
    closure = get_success_data(api.create_street_closure(
        production_id, create_street_closure_payload(permit["id"]), LM,
    ))
    get_success_data(api.approve_street_closure(production_id, closure["id"], FO))
    setup_funded_deposit(scenario)
    setup_signed_pre_walkthrough(scenario)
    day = setup_planned_shoot_day(scenario, permit)
    setup_confirmed_monitor(scenario, day, "FILM_OFFICER", "FO-1")
    setup_confirmed_monitor(scenario, day, "FILM_OFFICER", "FO-2")

    current = _fresh_day(api, production_id, day["id"])
    assert current["monitors_required"] == 2 and current["monitors_confirmed"] == 2, (
        "Setup: the numeric count must be met by the two FILM_OFFICERs"
    )
    resp = api.mark_shoot_day_ready(production_id, day["id"], current["version"], LM)
    validate_error(resp, ApiErrorId.ERR_MONITOR_SHORTFALL)
    assert _fresh_day(api, production_id, day["id"])["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Difficulty: fiscal gate and permit gate both fail at mark-ready
# ---------------------------------------------------------------------------

def test_mark_ready_unfunded_deposit_and_unissued_permit_reports_a_gate_error(api):
    """PRD §3.8: "the backing permit is `ISSUED` (else `ERR_PERMIT_NOT_ISSUED`)
    ... the location's deposit account is `FUNDED` (else
    `ERR_DEPOSIT_NOT_FUNDED`)"
    PRD §2.7: "then the business-rule checks specific to the operation (insurance
    sufficiency, lead time, notification adequacy, agreement chain, interval
    conflicts, caps, thresholds, funding, signatures, and the rest)"

    PRD §3.8 lists the readiness gates as a conjunction without pinning an
    evaluation order among them (contrast §3.9 wrap, which explicitly fixes
    gate order), so when both the permit gate and the deposit gate fail,
    either gate's error is a faithful outcome.

    Design: Difficulty/priority_pair_validation_conflict/mark_ready_deposit_vs_permit_priority
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    # Permit SUBMITTED (lead time satisfied) but ISSUE never decided.
    permit = setup_submitted_permit(scenario, clock="2026-08-03T09:00:00Z")
    assert permit["status"] == "SUBMITTED"
    # Deposit account exists but nothing deposited (held 0 < required 225000).
    get_success_data(api.create_deposit_account(
        production_id, create_deposit_account_payload(scenario["location"]["id"]), LM,
    ))
    day = setup_planned_shoot_day(scenario, permit)
    current = _fresh_day(api, production_id, day["id"])

    resp = api.mark_shoot_day_ready(production_id, day["id"], current["version"], LM)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_DEPOSIT_NOT_FUNDED,
        ApiErrorId.ERR_PERMIT_NOT_ISSUED,
    ])
    assert _fresh_day(api, production_id, day["id"])["status"] == "PLANNED"


def test_mark_ready_unfunded_deposit_blocks_even_when_permit_issued(api):
    """PRD §3.8: "the location's deposit account is `FUNDED` (else
    `ERR_DEPOSIT_NOT_FUNDED`)"
    PRD §3.7: "the moment the held amount reaches or exceeds the required amount,
    the account moves automatically to `FUNDED`. That funded posture is one of the
    readiness gates in §3.8."

    Design: Difficulty/priority_pair_validation_conflict/mark_ready_deposit_vs_permit_priority
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit, _, _ = setup_issued_permit(scenario, clock="2026-08-03T09:00:00Z")
    get_success_data(api.create_deposit_account(
        production_id, create_deposit_account_payload(scenario["location"]["id"]), LM,
    ))
    day = setup_planned_shoot_day(scenario, permit)
    current = _fresh_day(api, production_id, day["id"])

    resp = api.mark_shoot_day_ready(production_id, day["id"], current["version"], LM)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_FUNDED)
    assert _fresh_day(api, production_id, day["id"])["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Remaining single-gate mark-ready failures
# ---------------------------------------------------------------------------

def test_mark_ready_without_pre_walkthrough_rejected(api):
    """PRD §3.8: "a `SIGNED` `PRE` walkthrough exists for the location (else
    `ERR_PRE_WALKTHROUGH_MISSING`)"

    Design: Corner/state_machines/mark_ready_without_pre_walkthrough_rejected
    """
    result = setup_ready_day(with_pre_walkthrough=False, mark_ready=False)
    production_id = result["production"]["id"]
    day = result["shoot_day"]
    assert day["status"] == "PLANNED"
    current = _fresh_day(api, production_id, day["id"])
    resp = api.mark_shoot_day_ready(production_id, day["id"], current["version"], LM)
    validate_error(resp, ApiErrorId.ERR_PRE_WALKTHROUGH_MISSING)
    assert _fresh_day(api, production_id, day["id"])["status"] == "PLANNED"


def test_mark_ready_with_lanes_but_no_approved_closure_rejected(api):
    """PRD §3.8: "and, when the permit's `closed_lanes` is greater than zero, the
    `APPROVED` street closures needed for the day's lanes exist (else
    `ERR_CLOSURE_MISSING`)."

    Design: Corner/state_machines/mark_ready_with_lanes_but_no_approved_closure_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    # lanes 1 > 0 but below the police threshold (2): monitors_required 1.
    permit, _, _ = setup_issued_permit(
        scenario, clock="2026-08-03T09:00:00Z", closed_lanes=1, shoot_hours_per_day=8,
    )
    setup_funded_deposit(scenario)
    setup_signed_pre_walkthrough(scenario)
    day = setup_planned_shoot_day(scenario, permit)
    setup_confirmed_monitor(scenario, day, "FILM_OFFICER", "FO-1")
    current = _fresh_day(api, production_id, day["id"])

    resp = api.mark_shoot_day_ready(production_id, day["id"], current["version"], LM)
    validate_error(resp, ApiErrorId.ERR_CLOSURE_MISSING)
    assert _fresh_day(api, production_id, day["id"])["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# OCC on mark-ready
# ---------------------------------------------------------------------------

def test_mark_ready_stale_version_rejected(api):
    """PRD §2.6: "The mark-ready request must carry `expected_shoot_day_version`
    holding the client's last observed `version` of the ShootDay. A mismatch
    against the day's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412); the client must re-read the day and re-check the entire gate set
    before retrying."
    PRD §2.4: "any state change — whether client-initiated or fired automatically
    by a cascade or the operations sweep — advances `version` and refreshes
    `updated_at` on the mutated resource."

    Design: Corner/errors/mark_ready_stale_version_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit, _, _ = setup_issued_permit(scenario, clock="2026-08-03T09:00:00Z")
    setup_funded_deposit(scenario)
    setup_signed_pre_walkthrough(scenario)
    day = setup_planned_shoot_day(scenario, permit)
    stale_version = day["version"]
    # The confirm mutates the day's derived monitors_confirmed, advancing version.
    setup_confirmed_monitor(scenario, day, "FILM_OFFICER", "FO-1")

    resp = api.mark_shoot_day_ready(production_id, day["id"], stale_version, LM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert _fresh_day(api, production_id, day["id"])["status"] == "PLANNED"


def test_mark_ready_with_fresh_version_succeeds_and_activates_production(api):
    """PRD §3.8: "Success sets the day `READY`, increments its `version`, and — if
    the production was still in `PREP` — flips the production to `ACTIVE`."
    PRD §2.6: "The mark-ready request must carry `expected_shoot_day_version`
    holding the client's last observed `version` of the ShootDay."

    Design: Corner/errors/mark_ready_stale_version_rejected
    """
    result = setup_ready_day()
    day = result["shoot_day"]
    assert day["status"] == "READY", f"READY chain must reach READY, got {day['status']}"
    production = get_success_data(api.get_production(result["production"]["id"], LM))
    assert production["status"] == "ACTIVE"
