"""Validation-ladder priority conflicts, numeric/temporal boundary precision,
and single-rule validation rejections (PRD §2.11, §3.5, §3.6, §3.7).

Covers the priority_pair_validation_conflict and boundary_precision_check
difficulty instances plus validation corner probes.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, cleared_client, accepting_therapist, propose_match, accept_match,
    create_client, submit_intake, create_subscription, charge_cycle,
    create_therapist, add_license, activate_therapist,
    approve_financial_aid, raise_escalation, get_subscription_version,
    cancel_scheduled_subscription, active_match_with_credits, schedule_session,
    get_match_version,
    api_client, make_client_headers, make_therapist_headers,
)
from test_helpers import TEST_USERS
from datetime import datetime, timezone


def _instant(s):
    """Parse an ISO 8601 instant to a UTC datetime (format-agnostic: tolerates
    presence/absence of fractional seconds, which PRD §2.4/§2.10 leave
    unspecified for billing-period boundaries)."""
    txt = s[:-1] + "+00:00" if s.endswith("Z") else s
    return datetime.fromisoformat(txt).astimezone(timezone.utc)


def _client(cid):
    return make_client_headers(cid)


def _therapist(tid):
    return make_therapist_headers(tid)


def _clinical():
    return TEST_USERS["clinical_admin_headers"]


def _billing():
    return TEST_USERS["billing_admin_headers"]


# ==========================================================================
# Difficulty: priority_pair_validation_conflict — state (p7) before safety (p8)
# ==========================================================================
def test_reaccept_active_match_acute_client_reports_invalid_state(api):
    """PRD §2.11: "After a body is judged well-formed, the target resource's current state is
    checked against the requested transition, raising `ERR_INVALID_STATE` (HTTP 409) when the
    resource is not in a state from which the transition is legal. Business rules — risk blocks,
    intake clearance, license coverage, optimistic-concurrency version checks, scheduling
    conflicts, credit availability, and the rest — are evaluated after these structural rungs, in
    the priority order their workflows describe."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_accept_acute_already_active
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    accept_match(proposed["id"], client["id"])  # match now ACTIVE
    raise_escalation(client["id"], severity="ACUTE")  # client now ACUTE / SUSPENDED
    # re-accept the already-ACTIVE match: state check (p7) fires before risk-block (p8).
    resp = api.accept_match(proposed["id"], _client(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Difficulty: priority_pair_validation_conflict — intake gate (p9) before license (p10)
# ==========================================================================
def test_propose_uncleared_and_unlicensed_reports_intake_not_cleared(api):
    """PRD §2.11: "Business rules — risk blocks, intake clearance, license coverage,
    optimistic-concurrency version checks, scheduling conflicts, credit availability, and the rest
    — are evaluated after these structural rungs, in the priority order their workflows describe."
    PRD §3.3: "Proposal is blocked by the intake safety gate described in §3.1, surfacing
    `ERR_INTAKE_NOT_CLEARED` for an uncleared at-risk client, and a therapist with no `VALID`
    license for the client's `state_code` cannot be matched, which raises
    `ERR_LICENSE_STATE_MISMATCH` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_intake_uncleared_and_unlicensed
    """
    set_clock("2026-06-01T00:00:00Z")
    # Client in NY whose intake severity is 9 (uncleared gate) -> stays PENDING_INTAKE.
    client = create_client(state_code="NY")
    submit_intake(client["id"], severity_score=9)
    # Therapist ACCEPTING but licensed only in CA (no NY license).
    therapist = accepting_therapist(state_code="CA")
    resp = api.create_match(
        {"client_id": client["id"], "therapist_id": therapist["id"]}, _clinical()
    )
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_CLEARED.value)


# ==========================================================================
# Difficulty: boundary_precision_check — renewal due exactly at +7 days
# ==========================================================================
def test_renewal_charge_succeeds_exactly_at_seven_days(api):
    """PRD §3.6: "a renewal is only due once the clock has reached or passed `current_period_start`
    plus 7 days, and a premature renewal is rejected with `ERR_CYCLE_NOT_DUE` (HTTP 409)."
    PRD §3.6: "the subscription's `current_period_start` is set on the first cycle or advanced by
    exactly 7 days on a renewal."

    Design: Difficulty/boundary_precision_check/renewal_cycle_due_exactly_at_seven_days
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])  # current_period_start = 2026-06-01
    set_clock("2026-06-08T00:00:00Z")  # exactly +7 days (inclusive boundary)
    cycle2 = validate_success(api.charge_cycle(sub["id"], _billing()), 201)
    assert cycle2["status"] == "PAID", cycle2
    refetched = validate_success(api.get_subscription(sub["id"], _client(client["id"])))
    assert refetched["current_period_start"] == "2026-06-08T00:00:00Z", refetched


def test_renewal_charge_before_seven_days_rejected(api):
    """PRD §3.6: "a renewal is only due once the clock has reached or passed `current_period_start`
    plus 7 days, and a premature renewal is rejected with `ERR_CYCLE_NOT_DUE` (HTTP 409)."

    Design: Corner/validations/cycle_not_due_before_seven_days
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])
    set_clock("2026-06-07T00:00:00Z")  # +6 days, before the boundary
    resp = api.charge_cycle(sub["id"], _billing())
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_DUE.value)


# ==========================================================================
# Difficulty: boundary_precision_check — income exactly at ceiling falls to next band
# ==========================================================================
def test_aid_exactly_at_tier2_ceiling_falls_to_tier1(api):
    """PRD §3.6: "The adjusted income is then compared against three ceilings using a strict
    less-than at every boundary, so an adjusted income exactly equal to a ceiling falls into the
    next-less-generous band: an adjusted income below $25,000 (2,500,000 cents) awards `TIER_3`;
    otherwise an adjusted income below $40,000 (4,000,000 cents) awards `TIER_2`; otherwise an
    adjusted income below $60,000 (6,000,000 cents) awards `TIER_1`; and any adjusted income of
    $60,000 or more awards `NONE`."

    Design: Difficulty/boundary_precision_check/financial_aid_band_exactly_at_ceiling_falls_to_next_band
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    # adjusted_income = 4,600,000 - (2-1)*600,000 = 4,000,000 == TIER_2 ceiling -> TIER_1.
    app = approve_financial_aid(client["id"], annual_income_cents=4_600_000, household_size=2)
    assert app["awarded_tier"] == "TIER_1", app
    refetched = validate_success(api.get_client(client["id"], _client(client["id"])))
    assert refetched["financial_aid_tier"] == "TIER_1", refetched


# ==========================================================================
# Corner: duplicate non-terminal subscription rejected
# ==========================================================================
def test_duplicate_subscription_rejected(api):
    """PRD §3.6: "A client may hold only one non-terminal subscription at a time; an attempt to
    create a second is rejected with `ERR_DUPLICATE_SUBSCRIPTION` (HTTP 409)."

    Design: Corner/validations/duplicate_subscription_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    create_subscription(client["id"])  # first TRIALING subscription
    resp = api.create_subscription({"client_id": client["id"]}, _client(client["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION.value)


# ==========================================================================
# Corner: finalize-cancel before effective instant rejected
# ==========================================================================
def test_finalize_cancel_before_effective_rejected(api):
    """PRD §3.7: "The final transition to `CANCELLED` happens either when the clock reaches
    `cancel_effective_on` or when a `BillingAdmin` finalizes it, and it is only legal once the
    clock has reached or passed `cancel_effective_on`; a premature finalize is rejected with
    `ERR_CANCEL_NOT_DUE` (HTTP 409)."

    Design: Corner/validations/cancel_not_due_before_effective
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])  # current_period_start = 2026-06-01
    cancel_scheduled_subscription(client["id"], sub["id"])  # cancel_effective_on = 2026-06-08
    set_clock("2026-06-05T00:00:00Z")  # before effective
    resp = api.finalize_cancel_subscription(sub["id"], _billing())
    validate_error(resp, ApiErrorId.ERR_CANCEL_NOT_DUE.value)


# ==========================================================================
# Corner: pause resume_on beyond 84-day horizon -> ERR_VALIDATION (422)
# ==========================================================================
def test_pause_resume_beyond_horizon_rejected(api):
    """PRD §3.7: "The resume instant must be strictly after the current clock and no later than 84
    days after `current_period_start`; a resume instant beyond that 84-day horizon is rejected
    with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/validations/resume_on_beyond_pause_cap_validation_error
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])  # current_period_start = 2026-06-01; +84d = 2026-08-24
    version = get_subscription_version(sub["id"], client["id"])
    resp = api.pause_subscription(
        sub["id"],
        {"resume_on": "2026-09-15T00:00:00Z", "expected_subscription_version": version},
        _client(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ==========================================================================
# Corner: re-completing an already-COMPLETED session -> invalid state
# ==========================================================================
def test_complete_already_completed_session_rejected(api):
    """PRD §3.5: "The therapist completes it — legal only when the session is `SCHEDULED`, the
    clock has reached or passed `starts_at`, and the reserved credit is in `RESERVED` — which
    moves the session to `COMPLETED` and consumes the reserved credit"
    PRD §2.11: "the target resource's current state is checked against the requested transition,
    raising `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a state from which the
    transition is legal."

    Design: Corner/state_machines/complete_session_from_completed_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=1)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    therapist_id = info["therapist"]["id"]
    set_clock("2026-06-02T10:00:00Z")
    ls = schedule_session(match_id, client_id, "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    validate_success(api.complete_live_session(ls["id"], _therapist(therapist_id)))
    resp = api.complete_live_session(ls["id"], _therapist(therapist_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
