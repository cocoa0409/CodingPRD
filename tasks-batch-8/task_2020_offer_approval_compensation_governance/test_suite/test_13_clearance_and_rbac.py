"""Clearance checks (machine edges, RBAC, waiver) and role-exclusive denials."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_candidate_headers,
    create_equity_snapshot_payload, create_candidate_payload,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_peer_snapshots, create_draft_offer, create_accepted_offer,
    create_lettered_offer, create_extended_offer,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]
VP = TEST_USERS["vp_headers"]
SCR = TEST_USERS["screener_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def _accepted_with_bg_initiated(api, peers=(17000000, 18000000, 19000000), cand_name="Cand"):
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", list(peers))
    cand = create_candidate_recruited(REC, full_name=cand_name)
    offer = create_accepted_offer(req, cand, REC, base_cents=18000000)
    bg = get_success_data(api.create_clearance_check(offer["id"], {"kind": "BACKGROUND"}, SCR))
    return req, cand, offer, bg


def test_check_skip_in_progress_returns_invalid_transition(api):
    """PRD §3.8: "The declared edges are `INITIATED → IN_PROGRESS`,
    `IN_PROGRESS → CLEARED`, `IN_PROGRESS → FLAGGED`, `FLAGGED → IN_PROGRESS`
    (the re-check cycle), and `FLAGGED → FAILED`; any other move — `INITIATED`
    directly to `CLEARED`, for instance — is rejected with
    `ERR_CHECK_INVALID_TRANSITION`."

    Design: Corner/state_machines/check_skip_in_progress_returns_invalid_transition
    """
    req, cand, offer, bg = _accepted_with_bg_initiated(api, cand_name="Cand CK")
    resp = api.transition_clearance_check(bg["id"], {"to": "CLEARED"}, SCR)
    validate_error(resp, ApiErrorId.ERR_CHECK_INVALID_TRANSITION)
    checks = validate_success(api.list_clearance_checks(offer["id"], REC))
    assert checks[0]["status"] == "INITIATED"
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "ACCEPTED"
    assert after["clearance_posture"] == "PENDING"


def test_duplicate_active_check_rejected(api):
    """PRD §3.8: "One active check per kind is the limit — a second check of
    the same kind while one exists in `INITIATED`, `IN_PROGRESS`, or `FLAGGED`
    is rejected with `ERR_DUPLICATE_ACTIVE_CHECK`."

    Design: Corner/validations/duplicate_active_check_rejected
    """
    req, cand, offer, bg = _accepted_with_bg_initiated(api, cand_name="Cand DC")
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    resp = api.create_clearance_check(offer["id"], {"kind": "BACKGROUND"}, SCR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CHECK)
    ref = validate_success(api.create_clearance_check(offer["id"], {"kind": "REFERENCE"}, SCR), expected_status=201)
    assert ref["status"] == "INITIATED"


def test_screener_exclusive_check_transition(api):
    """PRD §3.8: "The screener advances a check by naming the target status
    `to`" — the transition endpoint is BackgroundScreener-only per §4; a
    Recruiter is denied per §2.10 tier 3 ("Endpoint role membership ... else
    `ERR_UNAUTHORIZED_ROLE`").

    Design: Corner/rbac/screener_exclusive_check_transition
    """
    req, cand, offer, bg = _accepted_with_bg_initiated(api, cand_name="Cand RB")
    resp = api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, REC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    checks = validate_success(api.list_clearance_checks(offer["id"], REC))
    assert checks[0]["status"] == "INITIATED"


def test_comp_analyst_exclusive_snapshot_create(api):
    """PRD §3.2: "The internal-equity peer set is maintained one row at a time
    by a `CompAnalyst`." — a Recruiter is denied per §2.10 tier 3 ("Endpoint
    role membership ... else `ERR_UNAUTHORIZED_ROLE`").

    Design: Corner/rbac/comp_analyst_exclusive_snapshot_create
    """
    resp = api.create_equity_snapshot(
        create_equity_snapshot_payload(role_level="L5", geo_tier="T1", base_cents=19000000), REC
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_vp_exclusive_waive_then_waive_drives_hire(api):
    """PRD §3.8: "a `VPPeople` may waive a check in `IN_PROGRESS` or `FLAGGED`,
    supplying a mandatory `reason`; the check becomes `WAIVED`, `CHECK_WAIVED`
    is appended, and the posture recomputes." and "otherwise `CLEARED` when
    every check is `CLEARED` or `WAIVED`" with "A posture of `CLEARED` hires:
    the offer moves `ACCEPTED → HIRED`".

    Design: Corner/rbac/vp_exclusive_waive_then_waive_drives_hire
    """
    req, cand, offer, bg = _accepted_with_bg_initiated(api, cand_name="Cand WV")
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    # BackgroundScreener may not waive
    resp = api.waive_clearance_check(bg["id"], {"reason": "screener overreach"}, SCR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    # VPPeople waive resolves the single check -> posture CLEARED -> hire
    waived = validate_success(
        api.waive_clearance_check(bg["id"], {"reason": "executive sponsor approval"}, VP)
    )
    assert waived["status"] == "WAIVED"
    final = validate_success(api.get_offer(offer["id"], REC))
    assert final["status"] == "HIRED"


def test_hradmin_exclusive_policy_and_clock(api):
    """PRD §3.2: "Routing policy is configured by an `HRAdmin` as ApprovalPolicy
    rows." PRD §2.4: "An `HRAdmin` may advance it through a test-driving
    capability". A Recruiter is denied on both per §2.10 tier 3 ("Endpoint role
    membership ... else `ERR_UNAUTHORIZED_ROLE`").

    Design: Corner/rbac/hradmin_exclusive_policy_and_clock
    """
    e1 = api.create_approval_policy(
        {"min_band_severity": "ABOVE_BAND", "required_role": "CompAnalyst", "chain_position": 1}, REC
    )
    validate_error(e1, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    e2 = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, REC)
    validate_error(e2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_candidate_cannot_extend(api):
    """PRD §3.6: "Extension is the act of putting the letter in the candidate's
    hands. A `Recruiter` may extend only from `LETTER_GENERATED`" — the endpoint
    is Recruiter-only per §4, so even the offeree is denied at the role tier
    (§2.10 tier 3, before the ownership tier 4).

    Design: Corner/rbac/candidate_cannot_extend
    """
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", [17000000, 18000000, 19000000])
    cand = create_candidate_recruited(REC, full_name="Cand CX")
    offer, _letter = create_lettered_offer(req, cand, REC, base_cents=18000000)
    resp = api.extend_offer(offer["id"], make_candidate_headers(cand["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "LETTER_GENERATED"


def test_candidate_reading_others_offer_returns_not_owner(api):
    """PRD §2.1: "A Candidate may read only their own record and their own
    offers, and may act only on their own offers; anything else is
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/candidate_reading_others_offer_returns_not_owner
    """
    req = create_open_requisition(HM)
    cand_a = create_candidate_recruited(REC, full_name="Cand OA")
    cand_b = create_candidate_recruited(REC, full_name="Cand OB")
    offer = create_draft_offer(req, cand_a, REC, base_cents=18000000)
    resp = api.get_offer(offer["id"], make_candidate_headers(cand_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    ok = validate_success(api.get_offer(offer["id"], make_candidate_headers(cand_a["id"])))
    assert ok["id"] == offer["id"]
