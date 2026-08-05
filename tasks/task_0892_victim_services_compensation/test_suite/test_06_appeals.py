"""Appeals: the reopen cascade, priority ordering on filing, and segregation of
duties (PRD §2.9, §2.10, §3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_counselor_headers"]
ADJ = TEST_USERS["adjudicator_headers"]


# --------------------------------------------------------------------------
# Difficulty — non_linear_state_machine: cyclic case reopen on appeal grant
# --------------------------------------------------------------------------
def test_appeal_grant_reopens_case_to_under_review(api):
    """PRD §3.9: "The target `VictimCase` is carried `INELIGIBLE → UNDER_REVIEW`: its
    `eligibility_status` is reset to `UNDETERMINED` and its `denied_at` is cleared."

    Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_on_appeal_grant
    """
    program, case, appeal, _ = fx.setup_ineligible_case_with_appeal_under_review(api, denier_id="adj-1")
    fx.appeal_transition(api, appeal["id"], "GRANTED", user_id="appeals-1")
    got = validate_success(api.get_case(case["id"], ADJ))
    assert got["status"] == "UNDER_REVIEW"


def test_appeal_grant_resets_eligibility_undetermined(api):
    """PRD §3.9: "The target `VictimCase` is carried `INELIGIBLE → UNDER_REVIEW`: its
    `eligibility_status` is reset to `UNDETERMINED` and its `denied_at` is cleared."

    Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_on_appeal_grant
    """
    program, case, appeal, _ = fx.setup_ineligible_case_with_appeal_under_review(api, denier_id="adj-1")
    fx.appeal_transition(api, appeal["id"], "GRANTED", user_id="appeals-1")
    got = validate_success(api.get_case(case["id"], ADJ))
    assert got["eligibility_status"] == "UNDETERMINED"


# --------------------------------------------------------------------------
# Difficulty — transitive_cascade: appeal grant -> case -> DENIED claims (depth 3)
# --------------------------------------------------------------------------
def test_appeal_grant_cascades_case_and_claim_to_under_review(api):
    """PRD §3.9: "That reopen in turn cascades to each of the case's claims that sits
    in `DENIED`, carrying every such claim `DENIED → UNDER_REVIEW` and clearing that
    claim's `denied_at` and `denied_by_user_id`, as described in §3.9."

    Design: Difficulty/transitive_cascade/appeal_grant_reopens_case_then_claim_depth3
    """
    program, case, appeal, claim = fx.setup_ineligible_case_with_appeal_under_review(
        api, denier_id="adj-1", with_denied_claim=True
    )
    fx.appeal_transition(api, appeal["id"], "GRANTED", user_id="appeals-1")
    case_got = validate_success(api.get_case(case["id"], ADJ))
    claim_got = validate_success(api.get_claim(claim["id"], ADJ))
    assert case_got["status"] == "UNDER_REVIEW"
    assert claim_got["status"] == "UNDER_REVIEW"


def test_appeal_grant_clears_claim_denial_and_writes_reopen_notification(api):
    """PRD §3.9: "carrying every such claim `DENIED → UNDER_REVIEW` and clearing that
    claim's `denied_at` and `denied_by_user_id`."
    PRD §3.9: "Finally a `Notification` with `event_type` `CASE_REOPENED` on the
    `VINE` channel is written for the case ..."

    Design: Difficulty/transitive_cascade/appeal_grant_reopens_case_then_claim_depth3
    """
    program, case, appeal, claim = fx.setup_ineligible_case_with_appeal_under_review(
        api, denier_id="adj-1", with_denied_claim=True
    )
    fx.appeal_transition(api, appeal["id"], "GRANTED", user_id="appeals-1")
    claim_got = validate_success(api.get_claim(claim["id"], ADJ))
    assert claim_got["denied_by_user_id"] is None
    notes, _meta = validate_paginated(api.list_case_notifications(case["id"], ADJ))
    assert any(n["event_type"] == "CASE_REOPENED" for n in notes), \
        "expected a CASE_REOPENED notification after the reopen cascade"


# --------------------------------------------------------------------------
# Difficulty — priority_pair_validation_conflict: referential beats temporal
# --------------------------------------------------------------------------
def _case_b_with_denied_claim(api, program_id):
    """Case B (UNDER_REVIEW) with one DENIED MEDICAL claim (denied by adj-1 at the
    default clock). Returns (case_b, claim_b)."""
    _, case_b = fx.make_under_review_case(api, program_id=program_id, victim_name="Case B", crime_type="ROBBERY")
    claim = fx.make_claim(api, case_b["id"], "MEDICAL", claimed_amount_cents=500000)
    fx.claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
    fx.claim_transition(api, claim["id"], "UNDER_REVIEW")
    claim = fx.claim_transition(api, claim["id"], "DENIED", user_id="adj-1")
    return case_b, claim


def test_referential_beats_temporal_on_appeal_create(api):
    """PRD §3.9: "When a `claim_id` is given, that claim must belong to the named
    `case_id`, or the filing is rejected with `ERR_REFERENCE_MISMATCH`."
    PRD §2.9: "After existence comes business-referential scoping
    (`ERR_REFERENCE_MISMATCH`, 409), then state-machine legality (`ERR_INVALID_STATE`,
    409), then cross-entity state preconditions, then segregation of duties, then
    program-closed checks, then the concurrency check, then temporal windows, then the
    remaining business constraints, and finally field-level shape validation
    (`ERR_VALIDATION`, 400)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_appeal_create
    """
    program = fx.make_program(api)
    case_a = fx.make_case(api, program["id"], victim_name="Case A")
    case_b, claim_b = _case_b_with_denied_claim(api, program["id"])
    # Advance clock so the appeal is also 61 days past the claim's denial (temporal expired).
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    resp = api.create_appeal(
        {"case_id": case_a["id"], "claim_id": claim_b["id"], "appeal_reason": "Cross-case appeal"}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH.value)


def test_appeal_claim_not_under_case_reference_mismatch(api):
    """PRD §3.9: "When a `claim_id` is given, that claim must belong to the named
    `case_id`, or the filing is rejected with `ERR_REFERENCE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_appeal_create
    """
    # No clock advance: the appeal is timely, isolating the referential-scoping check.
    program = fx.make_program(api)
    case_a = fx.make_case(api, program["id"], victim_name="Case A")
    case_b, claim_b = _case_b_with_denied_claim(api, program["id"])
    resp = api.create_appeal(
        {"case_id": case_a["id"], "claim_id": claim_b["id"], "appeal_reason": "Cross-case appeal"}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH.value)


# --------------------------------------------------------------------------
# Corner — segregation of duties on appeal decision (§2.10)
# --------------------------------------------------------------------------
def test_appeal_decider_same_as_denier_rejected(api):
    """PRD §2.10: "When an `AppealsOfficer` grants or denies an appeal, the acting
    `X-User-ID` must differ from the `denied_by_user_id` recorded on the target of the
    appeal ... If the same user who issued the denial attempts to decide its appeal,
    the transition is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/appeal_decider_same_as_denier_segregation_excluded
    """
    program, case, appeal, _ = fx.setup_ineligible_case_with_appeal_under_review(api, denier_id="adj-1")
    # Decider X-User-ID equals the denying Adjudicator's id -> blocked.
    resp = api.transition_appeal(appeal["id"], {"to_status": "GRANTED"}, make_headers("AppealsOfficer", "adj-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
