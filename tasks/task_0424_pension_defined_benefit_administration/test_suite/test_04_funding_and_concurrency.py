"""Funded-status posture, AFTAP boundary precision, filing supersede invariant, the
early-retirement age boundary, and optimistic concurrency on certify.

Translates boundary_precision_check, compensating_invariant (filing half),
priority_pair (vesting>funding) difficulty instances (queue A) and the funding /
concurrency / consistency corner instances (queue B).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_plan_payload,
    create_filing_payload,
    certify_payload,
    create_participant,
    add_standard_comp_330k,
    draft_election,
    setup_plan_with_certified_aftap,
    setup_restricted_plan,
    create_filing,
    certify_filing,
)

SPONSOR = TEST_USERS["plan_sponsor_headers"]
ACTUARY = TEST_USERS["plan_actuary_headers"]
ADMIN = TEST_USERS["benefits_admin_headers"]


# ---------------------------------------------------------------------------
# boundary_precision_check / aftap_restricted_floor_080_boundary
# ---------------------------------------------------------------------------
def test_aftap_exactly_080_yields_open_posture(api):
    """PRD §2.5: "When the attainment percentage is at least 0.80 the posture is `OPEN`."
    PRD §3.6: "On creation the filing is `DRAFT` and its `aftap_pct` is computed as
    `plan_assets_cents` divided by `funding_target_cents`, rounded to four decimal
    places."

    Design: Difficulty/boundary_precision_check/aftap_restricted_floor_080_boundary
    """
    plan, filing = setup_plan_with_certified_aftap(8_000_000_000, 10_000_000_000)
    assert filing["aftap_pct"] == 0.8
    assert plan["funding_posture"] == "OPEN"


def test_aftap_just_below_080_yields_restricted(api):
    """PRD §2.5: "When it is at least 0.60 but below 0.80 the posture is `RESTRICTED`,
    signalling benefit restrictions under which lump sums are limited."

    Design: Difficulty/boundary_precision_check/aftap_restricted_floor_080_boundary
    """
    # 0.79 < 0.80 -> RESTRICTED (the X-1 side of the >= 0.80 boundary).
    plan, filing = setup_plan_with_certified_aftap(7_900_000_000, 10_000_000_000)
    assert filing["aftap_pct"] == 0.79
    assert plan["funding_posture"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# boundary_precision_check / early_retirement_age_55_boundary_on_submit
# ---------------------------------------------------------------------------
def test_submit_at_exactly_age_55_succeeds(api):
    """PRD §3.4: "Finally, the `annuity_start_date` must imply an attained age of at
    least 55 — the early-retirement age — or the submission is rejected with
    `ERR_BENEFIT_NOT_AVAILABLE`."

    Design: Difficulty/boundary_precision_check/early_retirement_age_55_boundary_on_submit
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    # DOB 1969-06-01, ASD 2024-06-01 -> attained exactly 55.
    participant = create_participant(plan["id"], date_of_birth="1969-06-01", hire_date="2000-01-01")
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 12_000_000}, ADMIN))
    get_success_data(api.terminate_participant(participant["id"], ADMIN, {"termination_date": "2024-01-01"}))
    election = draft_election(participant["id"], "SINGLE_LIFE", "2024-06-01")
    submitted = validate_success(api.submit_election(election["id"], TEST_USERS["benefits_admin_a_headers"]))
    assert submitted["status"] == "SUBMITTED"


def test_submit_below_age_55_rejected(api):
    """PRD §3.4: "the `annuity_start_date` must imply an attained age of at least 55 —
    the early-retirement age — or the submission is rejected with
    `ERR_BENEFIT_NOT_AVAILABLE`."

    Design: Difficulty/boundary_precision_check/early_retirement_age_55_boundary_on_submit
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    # DOB 1970-06-01, ASD 2024-06-01 -> attained 54 (one below the floor).
    participant = create_participant(plan["id"], date_of_birth="1970-06-01", hire_date="2000-01-01")
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 12_000_000}, ADMIN))
    get_success_data(api.terminate_participant(participant["id"], ADMIN, {"termination_date": "2024-01-01"}))
    election = draft_election(participant["id"], "SINGLE_LIFE", "2024-06-01")
    resp = api.submit_election(election["id"], TEST_USERS["benefits_admin_a_headers"])
    validate_error(resp, ApiErrorId.ERR_BENEFIT_NOT_AVAILABLE.value)


# ---------------------------------------------------------------------------
# compensating_invariant / filing_supersede_conserves_single_certified_latest
# ---------------------------------------------------------------------------
def test_certify_later_filing_supersedes_prior_certified(api):
    """PRD §3.6: "Certifying a filing also supersedes any earlier certified filing: when
    a newly certified filing carries a `plan_year` greater than or equal to that of an
    existing `CERTIFIED` filing, the older one is moved by the system to the terminal
    `SUPERSEDED` state and the plan's posture is re-derived from the superseding filing."

    Design: Difficulty/compensating_invariant/filing_supersede_conserves_single_certified_latest
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    f24 = create_filing(plan["id"], 2024, 8_400_000_000, 10_000_000_000)
    certify_filing(f24["id"], plan["version"])
    plan_after1 = validate_success(api.get_plan(plan["id"], ACTUARY))
    f25 = create_filing(plan["id"], 2025, 6_500_000_000, 10_000_000_000)
    f25_certified = validate_success(api.certify_filing(
        f25["id"], certify_payload(plan_after1["version"]), ACTUARY))
    assert f25_certified["status"] == "CERTIFIED"
    assert f25_certified["aftap_pct"] == 0.65
    f24_refetched = validate_success(api.get_filing(f24["id"], ACTUARY))
    assert f24_refetched["status"] == "SUPERSEDED"


def test_supersede_leaves_latest_certified_pointer_and_posture(api):
    """PRD §2.5: "Once filings are certified, the posture is driven exclusively by the
    certified filing with the greatest `plan_year`, whose identifier the plan exposes as
    `latest_certified_filing_id`."

    Design: Difficulty/compensating_invariant/filing_supersede_conserves_single_certified_latest
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    f24 = create_filing(plan["id"], 2024, 8_400_000_000, 10_000_000_000)
    certify_filing(f24["id"], plan["version"])
    plan_after1 = validate_success(api.get_plan(plan["id"], ACTUARY))
    f25 = create_filing(plan["id"], 2025, 6_500_000_000, 10_000_000_000)
    validate_success(api.certify_filing(f25["id"], certify_payload(plan_after1["version"]), ACTUARY))
    final_plan = validate_success(api.get_plan(plan["id"], ACTUARY))
    assert final_plan["funding_posture"] == "RESTRICTED"
    assert final_plan["latest_certified_filing_id"] == f25["id"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / vesting_beats_funding_on_lump_sum_submit
# ---------------------------------------------------------------------------
def test_vesting_gate_beats_funding_gate_on_lump_sum_submit(api):
    """PRD §3.4: "The participant's `vesting_status` must be `FULLY_VESTED`, or the
    submission is rejected with `ERR_PARTICIPANT_NOT_VESTED`. For a `LUMP_SUM` form, the
    plan's `funding_posture` must not be `FROZEN`, or the submission is rejected with
    `ERR_FUNDING_RESTRICTED`."

    Design: Difficulty/priority_pair_validation_conflict/vesting_beats_funding_on_lump_sum_submit
    """
    # FROZEN plan (aftap 0.50) AND a participant only PARTIALLY_VESTED (6.0y service).
    plan, filing = setup_plan_with_certified_aftap(5_000_000_000, 10_000_000_000, fap_accrual_rate=0.015)
    assert plan["funding_posture"] == "FROZEN"
    participant = create_participant(plan["id"], date_of_birth="1962-01-01", hire_date="2018-01-01")
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 12_000_000}, ADMIN))
    participant = get_success_data(api.terminate_participant(
        participant["id"], ADMIN, {"termination_date": "2024-07-01"}))
    assert participant["vesting_status"] == "PARTIALLY_VESTED"
    election = draft_election(participant["id"], "LUMP_SUM", "2024-08-01")
    resp = api.submit_election(election["id"], TEST_USERS["benefits_admin_a_headers"])
    # Vesting gate (listed before the funding gate) wins.
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_VESTED.value)


def test_frozen_plan_partially_vested_submit_is_409(api):
    """PRD §3.4: "The participant's `vesting_status` must be `FULLY_VESTED`, or the
    submission is rejected with `ERR_PARTICIPANT_NOT_VESTED`."

    Design: Difficulty/priority_pair_validation_conflict/vesting_beats_funding_on_lump_sum_submit
    """
    plan, filing = setup_plan_with_certified_aftap(5_000_000_000, 10_000_000_000, fap_accrual_rate=0.015)
    participant = create_participant(plan["id"], date_of_birth="1962-01-01", hire_date="2018-01-01")
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 12_000_000}, ADMIN))
    get_success_data(api.terminate_participant(participant["id"], ADMIN, {"termination_date": "2024-07-01"}))
    election = draft_election(participant["id"], "LUMP_SUM", "2024-08-01")
    resp = api.submit_election(election["id"], TEST_USERS["benefits_admin_a_headers"])
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Corner: state_machines / plan_terminate_blocked_when_restricted
# ---------------------------------------------------------------------------
def test_plan_terminate_blocked_when_restricted(api):
    """PRD §3.1: "It is refused when the plan's `funding_posture` is `RESTRICTED` — a
    restricted plan cannot be voluntarily standard-terminated — and that refusal carries
    `ERR_FUNDING_RESTRICTED`."

    Design: Corner/state_machines/plan_terminate_blocked_when_restricted
    """
    plan, filing = setup_restricted_plan(fap_accrual_rate=0.015)
    assert plan["funding_posture"] == "RESTRICTED"
    resp = api.terminate_plan(plan["id"], SPONSOR)
    validate_error(resp, ApiErrorId.ERR_FUNDING_RESTRICTED.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / occ_stale_plan_version_on_second_certify
# ---------------------------------------------------------------------------
def test_certify_with_stale_plan_version_rejected(api):
    """PRD §2.7: "If that value does not equal the plan's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_second_certify
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    v0 = plan["version"]
    f24 = create_filing(plan["id"], 2024, 8_400_000_000, 10_000_000_000)
    f25 = create_filing(plan["id"], 2025, 9_000_000_000, 10_000_000_000)
    certify_filing(f24["id"], v0)  # advances plan.version to v0+1
    resp = api.certify_filing(f25["id"], certify_payload(v0), ACTUARY)  # still holds v0
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / occ_correct_version_certify_succeeds_and_bumps
# ---------------------------------------------------------------------------
def test_certify_with_current_version_succeeds_and_bumps(api):
    """PRD §2.7: "A successful certification increments the plan's `version` by one,
    which is precisely why a second actuary holding the old number is turned away."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_certify_succeeds_and_bumps
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    f = create_filing(plan["id"], 2024, 8_400_000_000, 10_000_000_000)
    certified = validate_success(api.certify_filing(f["id"], certify_payload(plan["version"]), ACTUARY))
    assert certified["status"] == "CERTIFIED"
    assert certified["aftap_pct"] == 0.84
    refetched_plan = validate_success(api.get_plan(plan["id"], ACTUARY))
    assert refetched_plan["version"] == 2


# ---------------------------------------------------------------------------
# Corner: consistency_model / immediate_consistency_funding_posture_visible_in_same_response
# ---------------------------------------------------------------------------
def test_funding_posture_visible_immediately_after_certify(api):
    """PRD §2.5: "When it is at least 0.60 but below 0.80 the posture is `RESTRICTED`,
    signalling benefit restrictions under which lump sums are limited."
    PRD §3.6: "On success ... the plan's `funding_posture` is re-derived from this and
    any prior certified filings per the threshold rules in §2.5."

    Design: Corner/consistency_model/immediate_consistency_funding_posture_visible_in_same_response
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    f = create_filing(plan["id"], 2024, 6_500_000_000, 10_000_000_000)  # aftap 0.65 -> RESTRICTED
    validate_success(api.certify_filing(f["id"], certify_payload(plan["version"]), ACTUARY))
    refetched = validate_success(api.get_plan(plan["id"], ACTUARY))
    assert refetched["funding_posture"] == "RESTRICTED"
