"""Fiscal gates: budget gate, hard cap, committed-budget conservation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, event_types,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_draft_offer, create_offer_with_perks,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]


def test_submit_paused_requisition_beats_budget_error(api):
    """PRD §2.10: "a request failing both the state gate and the budget gate
    surfaces the state error." — tier 6 ("offer creation, submission, and
    letter generation against a non-`OPEN` requisition draw
    `ERR_REQUISITION_NOT_OPEN`") precedes tier 12 ("the submission budget gate
    (`ERR_REQUISITION_BUDGET_EXCEEDED`)").

    Design: Difficulty/priority_pair_validation_conflict/submit_paused_requisition_beats_budget_error
    """
    req = create_open_requisition(HM, title="Tight Budget", annual_budget_cents=20000000)
    cand = create_candidate_recruited(REC, full_name="Cand N")
    # fully_loaded = 20000000 + 6000000 = 26000000 > 20000000 budget
    offer = create_draft_offer(req, cand, REC, base_cents=20000000)
    validate_success(api.hold_requisition(req["id"], {"action": "PAUSE"}, HM))
    resp = api.submit_offer(offer["id"], REC)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "DRAFT"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 0


def test_submit_paused_requisition_state_error_leaves_no_trace(api):
    """PRD §2.10: "a request failing both the state gate and the budget gate
    surfaces the state error." When both fire on a PAUSED requisition the
    surfaced `ERR_REQUISITION_NOT_OPEN` leaves the offer in `DRAFT` and the
    committed budget untouched — no partial fiscal side effect leaks through.

    Design: Difficulty/priority_pair_validation_conflict/submit_paused_requisition_beats_budget_error
    """
    req = create_open_requisition(HM, title="Tight Budget", annual_budget_cents=20000000)
    cand = create_candidate_recruited(REC, full_name="Cand N2")
    offer = create_draft_offer(req, cand, REC, base_cents=20000000)
    validate_success(api.hold_requisition(req["id"], {"action": "PAUSE"}, HM))
    # state gate (tier 6) and fiscal gate (tier 12) both fail; state error wins
    validate_error(api.submit_offer(offer["id"], REC), ApiErrorId.ERR_REQUISITION_NOT_OPEN)
    offer_after = validate_success(api.get_offer(offer["id"], REC))
    assert offer_after["status"] == "DRAFT"
    assert validate_success(api.list_approval_steps(offer["id"], REC)) == []
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 0
    types = event_types(validate_success(api.list_offer_events(offer["id"], REC)))
    assert "SUBMITTED" not in types


def test_submit_paused_requisition_via_hold_resume_cycle(api):
    """PRD §3.5: "The requisition must be `OPEN`, else
    `ERR_REQUISITION_NOT_OPEN`." — the gate reads live requisition state, so the
    identical submit succeeds after RESUME.

    Design: Difficulty/cross_entity_state_dependency/offer_submit_gated_by_requisition_open
    """
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand U")
    offer = create_draft_offer(req, cand, REC, base_cents=18000000)
    validate_success(api.hold_requisition(req["id"], {"action": "PAUSE"}, HM))
    resp = api.submit_offer(offer["id"], REC)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)
    mid = validate_success(api.get_offer(offer["id"], REC))
    assert mid["status"] == "DRAFT"
    validate_success(api.hold_requisition(req["id"], {"action": "RESUME"}, HM))
    submitted = validate_success(api.submit_offer(offer["id"], REC))
    assert submitted["status"] == "PENDING_APPROVAL"


def test_submit_after_resume_commits_fully_loaded(api):
    """PRD §3.5: "recomputes the requisition's `committed_budget_cents` (the
    offer, now `PENDING_APPROVAL`, joins the counted set)". For base 18000000
    with no bonus/equity/perks the fully loaded cost is 18000000 + 5400000
    benefits = 23400000.

    Design: Difficulty/cross_entity_state_dependency/offer_submit_gated_by_requisition_open
    """
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand U2")
    offer = create_draft_offer(req, cand, REC, base_cents=18000000)
    validate_success(api.hold_requisition(req["id"], {"action": "PAUSE"}, HM))
    validate_error(api.submit_offer(offer["id"], REC), ApiErrorId.ERR_REQUISITION_NOT_OPEN)
    validate_success(api.hold_requisition(req["id"], {"action": "RESUME"}, HM))
    validate_success(api.submit_offer(offer["id"], REC))
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 23400000


def test_budget_exceeded_at_submit(api):
    """PRD §3.5: "The budget gate requires the offer's
    `fully_loaded_annual_cost_cents` to fit within the requisition's uncommitted
    balance — `annual_budget_cents` minus `committed_budget_cents` — else
    `ERR_REQUISITION_BUDGET_EXCEEDED`".

    Design: Corner/validations/budget_exceeded_at_submit
    """
    req = create_open_requisition(HM, title="Tight", annual_budget_cents=20000000)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand BE")
    # fully_loaded = 20000000 + 6000000 = 26000000 > 20000000 remaining
    offer = create_draft_offer(req, cand, REC, base_cents=20000000)
    resp = api.submit_offer(offer["id"], REC)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_BUDGET_EXCEEDED)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "DRAFT"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 0


def test_base_hard_cap_rejected_at_create(api):
    """PRD §3.3: "the base may not exceed one hundred twenty-five percent of
    the requisition's `salary_max_cents`, compared against the unrounded
    product, or the request fails with `ERR_BASE_EXCEEDS_HARD_CAP`."

    Design: Corner/validations/base_hard_cap_rejected_at_create
    """
    req = create_open_requisition(HM, headcount_authorized=2)
    cand1 = create_candidate_recruited(REC, full_name="Cand HC")
    cand2 = create_candidate_recruited(REC, full_name="Cand HC2")
    # 21000000 * 1.25 = 26250000; one cent over is rejected
    resp = api.create_offer(
        {"requisition_id": req["id"], "candidate_id": cand1["id"], "base_cents": 26250001,
         "bonus_target_pct": 0, "equity_shares": 0, "equity_fmv_cents": 0},
        REC,
    )
    validate_error(resp, ApiErrorId.ERR_BASE_EXCEEDS_HARD_CAP)
    ok = validate_success(api.create_offer(
        {"requisition_id": req["id"], "candidate_id": cand2["id"], "base_cents": 26250000,
         "bonus_target_pct": 0, "equity_shares": 0, "equity_fmv_cents": 0},
        REC,
    ), expected_status=201)
    assert ok["band"] == "EXCEPTION"


def test_submit_withdraw_committed_budget_conservation(api):
    """PRD §2.8: "`committed_budget_cents`, the sum of the fully loaded annual
    cost over exactly those of its offers in `PENDING_APPROVAL`, `APPROVED`,
    `LETTER_GENERATED`, `EXTENDED`, `COUNTERED`, `ACCEPTED`, or `HIRED` status,
    recomputed in full — never incrementally adjusted — whenever an offer enters
    or leaves that counted set". Because the counted set excludes `DRAFT` and
    `RETURNED`, a DRAFT offer contributes 0; submit adds; withdraw releases.

    Design: Difficulty/compensating_invariant/submit_withdraw_committed_budget_conservation
    """
    req = create_open_requisition(HM, headcount_authorized=2)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand Y")
    offer = create_draft_offer(req, cand, REC, base_cents=20000000)
    c0 = validate_success(api.get_requisition(req["id"], REC))["committed_budget_cents"]
    assert c0 == 0
    validate_success(api.submit_offer(offer["id"], REC))
    c1 = validate_success(api.get_requisition(req["id"], REC))["committed_budget_cents"]
    assert c1 == 26000000
    withdrawn = validate_success(api.withdraw_offer(offer["id"], {"reason": "pipeline frozen"}, REC))
    assert withdrawn["status"] == "WITHDRAWN"
    c2 = validate_success(api.get_requisition(req["id"], REC))["committed_budget_cents"]
    assert c2 == 0


def test_submit_withdraw_events_recorded(api):
    """PRD §3.5: a successful submission "appends `SUBMITTED`". PRD §3.9: "From
    `PENDING_APPROVAL` the unwind is deeper ... and `WITHDRAWN` is appended."

    Design: Difficulty/compensating_invariant/submit_withdraw_committed_budget_conservation
    """
    req = create_open_requisition(HM, headcount_authorized=2)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand Y2")
    offer = create_draft_offer(req, cand, REC, base_cents=20000000)
    validate_success(api.submit_offer(offer["id"], REC))
    validate_success(api.withdraw_offer(offer["id"], {"reason": "pipeline frozen"}, REC))
    types = event_types(validate_success(api.list_offer_events(offer["id"], REC)))
    assert "SUBMITTED" in types
    assert "WITHDRAWN" in types
    assert types.index("SUBMITTED") < types.index("WITHDRAWN")
