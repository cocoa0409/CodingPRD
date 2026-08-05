"""Conservation invariants (pole space, attacher balance), the expiry-over-credit
precedence pair, and role/ownership access control.

Queue A — compensating_invariant (occupied space across attach/abandon; balance
across issue/void), priority_pair_validation_conflict (estimate expiry beats
credit limit).
Queue B — rbac (unauthenticated create; peer-role estimate; foreign-application
withdraw).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_attacher_headers, make_engineer_headers,
    setup_owner, setup_pole, setup_attacher,
    submit_application, create_granted_application, create_accepted_application,
    create_estimate_issued_application, create_surveyed_application,
    deny_permit, set_clock, COMPLEX_SURVEY, api_client,
)

COORD = TEST_USERS["coordinator_headers"]


# ─── Queue A: compensating_invariant (pole occupied space) ─────────────────
def test_pole_occupied_space_conserved_attachment_abandoned(api):
    """PRD §3.5: "An abandonment advances the attachment `ACTIVE → ABANDONED`;
    again the caller must own it or the response is `ERR_UNAUTHORIZED`. The
    pole's `occupied_space_inches` falls by the abandoned attachment's
    `allotted_space_inches`, releasing that space for reuse."

    Design: Difficulty/compensating_invariant/pole_occupied_space_conserved_across_attach_abandon
    """
    ctx = create_granted_application(survey_overrides={"estimated_labor_hours": 4,
                                                       "make_ready_required": True,
                                                       "existing_attacher_count": 0,
                                                       "complexity_class": "SIMPLE"})
    attachment = ctx["attachment"]
    res = api.abandon_attachment(attachment["id"], make_attacher_headers(ctx["attacher"]["id"]))
    updated = validate_success(res, 200)
    assert updated["status"] == "ABANDONED"


def test_pole_occupied_space_zero_after_abandon(api):
    """PRD §2.8: "A pole's `occupied_space_inches` is the sum of
    `allotted_space_inches` over every `Attachment` on that pole whose `status`
    is `ACTIVE`; it starts at zero and is recomputed on every attachment create,
    transfer, abandon, permit grant, and finding legalization."

    Design: Difficulty/compensating_invariant/pole_occupied_space_conserved_across_attach_abandon
    """
    ctx = create_granted_application(survey_overrides={"estimated_labor_hours": 4,
                                                       "make_ready_required": True,
                                                       "existing_attacher_count": 0,
                                                       "complexity_class": "SIMPLE"})
    pole_before = get_success_data(api_client.get_pole(ctx["pole"]["id"], COORD))
    assert pole_before["occupied_space_inches"] == 6
    api.abandon_attachment(ctx["attachment"]["id"], make_attacher_headers(ctx["attacher"]["id"]))
    pole_after = get_success_data(api_client.get_pole(ctx["pole"]["id"], COORD))
    assert pole_after["occupied_space_inches"] == 0


# ─── Queue A: compensating_invariant (attacher balance) ────────────────────
def test_attacher_balance_conserved_issue_then_void(api):
    """PRD §2.8: "An attacher's `account_balance_cents` is the sum of
    `amount_cents` over every `Invoice` billed to that attacher whose `status`
    is `ISSUED` or `OVERDUE`; it starts at zero and is recomputed whenever an
    invoice is issued, paid, voided, or has its amount adjusted."

    Design: Difficulty/compensating_invariant/attacher_balance_conserved_across_issue_void
    """
    ctx = create_accepted_application(survey_overrides=COMPLEX_SURVEY)
    at_accept = get_success_data(api_client.get_attacher(ctx["attacher"]["id"], COORD))
    assert at_accept["account_balance_cents"] == 210450
    deny_permit(ctx["app"]["id"])
    at_deny = get_success_data(api_client.get_attacher(ctx["attacher"]["id"], COORD))
    assert at_deny["account_balance_cents"] == 0


def test_attacher_balance_matches_outstanding_sum_after_void(api):
    """PRD §2.8: "An attacher's `account_balance_cents` is the sum of
    `amount_cents` over every `Invoice` billed to that attacher whose `status`
    is `ISSUED` or `OVERDUE`; it starts at zero and is recomputed whenever an
    invoice is issued, paid, voided, or has its amount adjusted."

    Design: Difficulty/compensating_invariant/attacher_balance_conserved_across_issue_void
    """
    ctx = create_accepted_application(survey_overrides=COMPLEX_SURVEY)
    deny_permit(ctx["app"]["id"])
    attacher = get_success_data(api_client.get_attacher(ctx["attacher"]["id"], COORD))
    body = api_client.list_invoices(COORD, params={"attacher_id": ctx["attacher"]["id"]}).json()
    outstanding = sum(inv["amount_cents"] for inv in body["data"]
                      if inv["status"] in ("ISSUED", "OVERDUE"))
    assert attacher["account_balance_cents"] == outstanding == 0


# ─── Queue A: priority_pair (estimate expiry beats credit limit) ───────────
def _expired_over_credit_application():
    """Estimate issued (fee 210450) on an attacher with credit_limit 100, then
    the clock advances past estimate_expires_at so the application is EXPIRED."""
    ctx = create_estimate_issued_application(
        attacher_overrides={"credit_limit_cents": 100},
        survey_overrides=COMPLEX_SURVEY,
    )
    # Default estimate issued at 2026-05-01, expires 2026-05-31; advance past it.
    set_clock("2026-06-02T00:00:00Z")
    return ctx


def test_accept_estimate_expired_beats_credit_limit(api):
    """PRD §2.10: "Then the target's state validity for the requested transition,
    yielding `ERR_INVALID_STATE` (409) or a more specific state error. Then
    optimistic concurrency, yielding `ERR_STALE_VERSION` (412). Then segregation
    of duties on permit decisions, yielding `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.3: "the estimate must not have expired — the application must still be
    `ESTIMATE_ISSUED` and not `ESTIMATE_EXPIRED` — or the acceptance is rejected
    with `ERR_ESTIMATE_EXPIRED`".

    Design: Difficulty/priority_pair_validation_conflict/accept_estimate_state_expired_beats_credit_limit
    """
    ctx = _expired_over_credit_application()
    res = api.estimate_decision_application(
        ctx["app"]["id"], {"decision": "ACCEPT"}, make_attacher_headers(ctx["attacher"]["id"])
    )
    validate_error(res, "ERR_ESTIMATE_EXPIRED", expected_status=409)


def test_expired_application_state_masks_credit_check(api):
    """PRD §2.10: "A check earlier in this ordering always masks a check later in
    it."
    PRD §2.9: "every `AttachmentApplication` still `ESTIMATE_ISSUED` whose
    `estimate_expires_at` is now in the past transitions to `ESTIMATE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/accept_estimate_state_expired_beats_credit_limit
    """
    ctx = _expired_over_credit_application()
    api.estimate_decision_application(
        ctx["app"]["id"], {"decision": "ACCEPT"}, make_attacher_headers(ctx["attacher"]["id"])
    )
    after = get_success_data(api_client.get_application(ctx["app"]["id"], COORD))
    assert after["status"] == "ESTIMATE_EXPIRED", "expiry state must mask the credit-limit check"


# ─── Queue B: rbac ─────────────────────────────────────────────────────────
def test_create_application_unauthenticated_returns_401(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/create_application_unauthenticated_returns_401
    """
    owner = setup_owner()
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    headers = {"X-User-Role": "Attacher", "Content-Type": "application/json"}  # no X-User-ID
    res = api.create_application(
        {"pole_id": pole["id"], "attacher_id": attacher["id"], "requested_space_inches": 6,
         "requested_position_inches": 240, "purpose": "FIBER"},
        headers,
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_attacher_cannot_issue_estimate(api):
    """PRD §2.1: "When the headers are well formed but the role is not permitted
    to perform the requested operation — or an attacher attempts to act on a
    resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/attacher_cannot_issue_estimate
    """
    ctx = create_surveyed_application()
    res = api.estimate_application(
        ctx["app"]["id"], {"expected_application_version": ctx["app"]["version"]},
        make_attacher_headers(ctx["attacher"]["id"]),
    )
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_attacher_cannot_withdraw_foreign_application(api):
    """PRD §3.4: "At any point before it reaches a terminal outcome, the acting
    `Attacher` may withdraw the application, moving it to `WITHDRAWN` from
    `SUBMITTED`, `SURVEYED`, `ESTIMATE_ISSUED`, or `ESTIMATE_ACCEPTED`; a
    withdrawal by anyone other than the owning attacher is `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/attacher_cannot_withdraw_foreign_application
    """
    owner = setup_owner()
    pole = setup_pole(owner["id"])
    att_a = setup_attacher(company_name="A", cin="CINA", contact_email="a@x.com")
    att_b = setup_attacher(company_name="B", cin="CINB", contact_email="b@x.com")
    app = submit_application(pole["id"], att_a["id"])
    res = api.withdraw_application(app["id"], make_attacher_headers(att_b["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
