"""State-machine transitions: invalid jumps, terminal lockdown, valid moves,
cascades, and the branching candidate cure edge."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_party_headers,
    create_award_payload, create_appeal_payload, create_exchange_payload,
    create_deposit_payload,
)
from test_helpers.fixtures import (
    ADMIN, create_case, setup_hearing_case, setup_hearing_case_with_hearing,
    setup_selection_with_candidate, setup_issued_award,
    setup_filed_case_with_party, setup_paid_deposit_on_filed_case,
    add_party,
)

ADM = ADMIN


def _candidate(api, case_id, candidate_id):
    for c in validate_success(api.list_case_candidates(case_id, ADM), 200):
        if c["id"] == candidate_id:
            return c
    raise AssertionError("candidate not found")


# ---- Invalid transitions / terminal lockdown ----------------------------

def test_transition_case_filed_to_hearing_returns_invalid_state(api):
    """PRD 3.1: "A case may move out of `FILED` in two ways ... Opening candidate
    selection advances the case from `FILED` to `SELECTION` ... Alternatively the case
    may be abandoned from `FILED` to `WITHDRAWN`". PRD 2.8: "State — the target resource
    is in a state that permits the requested transition or action; otherwise
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/transition_case_filed_to_hearing_returns_invalid_state
    """
    case = create_case(api, claim_amount_cents=500_000)
    resp = api.transition_case(case["id"], {"to_status": "HEARING"}, ADM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_transition_withdrawn_case_is_terminal_locked(api):
    """PRD 3.1: "`CLOSED` and `WITHDRAWN` are the terminal states of a case." PRD 2.8:
    "State — the target resource is in a state that permits the requested transition or
    action; otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/transition_withdrawn_case_is_terminal_locked
    """
    case = create_case(api, claim_amount_cents=500_000)
    validate_success(api.transition_case(case["id"], {"to_status": "WITHDRAWN"}, ADM), 200)
    resp = api.transition_case(case["id"], {"to_status": "SELECTION"}, ADM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_finalize_award_from_draft_returns_invalid_state(api):
    """PRD 3.9: "Finalizing an award moves it from `ISSUED` to `FINAL` (terminal)". PRD
    2.8: "State — the target resource is in a state that permits the requested transition
    or action; otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/finalize_award_from_draft_returns_invalid_state
    """
    ctx = setup_hearing_case(api, claim_amount_cents=2_000_000)
    aw = validate_success(api.create_award(ctx["case"]["id"], create_award_payload(
        award_type="MONETARY", award_amount_cents=500_000), ADM), 201)
    resp = api.transition_award(aw["id"], {"to_status": "FINAL"}, ADM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_advance_appeal_filed_to_granted_returns_invalid_state(api):
    """PRD 3.9: "A `CaseAdministrator` advances an appeal from `FILED` to `UNDER_REVIEW`,
    and from `UNDER_REVIEW` to either `GRANTED` or `DENIED`". PRD 2.8: "State — the target
    resource is in a state that permits the requested transition or action; otherwise
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/advance_appeal_filed_to_granted_returns_invalid_state
    """
    ctx = setup_issued_award(api, claim_amount_cents=2_000_000, award_amount_cents=500_000,
                             clock="2026-06-01T00:00:00Z")
    ap = validate_success(api.create_appeal(create_appeal_payload(
        award_id=ctx["award"]["id"], ground="PROCEDURAL"),
        make_party_headers(ctx["pA"]["id"])), 201)
    resp = api.transition_appeal(ap["id"], {"to_status": "GRANTED"}, ADM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_deposit_twice_returns_invalid_state(api):
    """PRD 3.8: "A `Party` pays a requested deposit, moving it from `REQUESTED` to
    `PAID`". PRD 2.8: "State — the target resource is in a state that permits the
    requested transition or action; otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/pay_deposit_twice_returns_invalid_state
    """
    ctx = setup_paid_deposit_on_filed_case(api, amount_cents=100_000)
    resp = api.pay_deposit(ctx["deposit"]["id"], make_party_headers(ctx["pA"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_refund_deposit_before_case_closed_returns_invalid_state(api):
    """PRD 3.8: "a refund attempted while the case is not `CLOSED` is rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/refund_deposit_before_case_closed_returns_invalid_state
    """
    ctx = setup_paid_deposit_on_filed_case(api, amount_cents=100_000)
    resp = api.refund_deposit(ctx["deposit"]["id"], ADM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---- Valid transitions --------------------------------------------------

def test_submit_exchange_before_due_is_submitted(api):
    """PRD 3.7: "if the clock is at or before the exchange's `due_at`, the exchange
    becomes `SUBMITTED`".

    Design: Corner/state_machines/submit_exchange_before_due_is_submitted
    """
    ctx = setup_filed_case_with_party(api, clock="2026-06-05T00:00:00Z")
    ex = validate_success(api.create_exchange(ctx["case"]["id"], create_exchange_payload(
        exchange_type="BRIEFS", due_at="2026-06-10T00:00:00Z"), ADM), 201)
    data = validate_success(api.submit_exchange(ex["id"], make_party_headers(ctx["pA"]["id"])), 200)
    assert data["status"] == "SUBMITTED"


def test_submit_exchange_after_due_is_late(api):
    """PRD 3.7: "if the clock is past `due_at`, the same action instead lands the exchange
    in `LATE`."

    Design: Corner/state_machines/submit_exchange_after_due_is_late
    """
    ctx = setup_filed_case_with_party(api, clock="2026-06-15T00:00:00Z")
    ex = validate_success(api.create_exchange(ctx["case"]["id"], create_exchange_payload(
        exchange_type="BRIEFS", due_at="2026-06-10T00:00:00Z"), ADM), 201)
    data = validate_success(api.submit_exchange(ex["id"], make_party_headers(ctx["pA"]["id"])), 200)
    assert data["status"] == "LATE"


def test_mark_hearing_held_valid_transition(api):
    """PRD 3.6: "A `CaseAdministrator` marks a scheduled hearing `HELD` or `CANCELLED`
    (both terminal)."

    Design: Corner/state_machines/mark_hearing_held_valid_transition
    """
    ctx = setup_hearing_case_with_hearing(api)
    data = validate_success(api.transition_hearing(ctx["hearing"]["id"], {"to_status": "HELD"}, ADM), 200)
    assert data["status"] == "HELD"


# ---- Cascade ------------------------------------------------------------

def test_withdraw_case_cascades_candidate_not_selected(api):
    """PRD 3.1: "A case in `SELECTION` may also be withdrawn to `WITHDRAWN`; when it is,
    every candidate still open on the case — that is, every candidate in `PROPOSED`,
    `DISCLOSED`, `CLEARED`, or `OBJECTED` — is moved to `NOT_SELECTED`."

    Design: Corner/state_machines/withdraw_case_cascades_candidate_not_selected
    """
    ctx = setup_selection_with_candidate(api, disclose_it=True)
    validate_success(api.transition_case(ctx["case"]["id"], {"to_status": "WITHDRAWN"}, ADM), 200)
    cand = _candidate(api, ctx["case"]["id"], ctx["candidate"]["id"])
    assert cand["status"] == "NOT_SELECTED"


# ---- Difficulty: candidate objection cured back to CLEARED / disqualified ---

def test_candidate_objection_cured_back_to_cleared(api):
    """PRD 3.3: "from `OBJECTED` the administrator may cure the candidate back to
    `CLEARED` — again only when `has_conflict` is false, otherwise
    `ERR_CANDIDATE_HAS_CONFLICT` — or may instead move it from `OBJECTED` to
    `DISQUALIFIED`."

    Design: Difficulty/non_linear_state_machine/candidate_objection_cured_back_to_cleared
    """
    ctx = setup_selection_with_candidate(api, disclose_it=True, has_conflict=False)
    validate_success(api.transition_candidate(ctx["candidate"]["id"], {"to_status": "OBJECTED"}, ADM), 200)
    data = validate_success(api.transition_candidate(ctx["candidate"]["id"], {"to_status": "CLEARED"}, ADM), 200)
    assert data["status"] == "CLEARED"


def test_candidate_objection_forks_to_disqualified(api):
    """PRD 3.3: "from `OBJECTED` the administrator may cure the candidate back to
    `CLEARED` ... or may instead move it from `OBJECTED` to `DISQUALIFIED`."

    Design: Difficulty/non_linear_state_machine/candidate_objection_cured_back_to_cleared
    """
    ctx = setup_selection_with_candidate(api, disclose_it=True, has_conflict=False)
    validate_success(api.transition_candidate(ctx["candidate"]["id"], {"to_status": "OBJECTED"}, ADM), 200)
    data = validate_success(api.transition_candidate(ctx["candidate"]["id"], {"to_status": "DISQUALIFIED"}, ADM), 200)
    assert data["status"] == "DISQUALIFIED"
