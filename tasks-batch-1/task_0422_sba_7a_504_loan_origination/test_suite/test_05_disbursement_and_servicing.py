"""Boundary precision (size standard cap, over-disbursement boundary), half-open draw
windows, closed servicing intervals, and the cyclic / branching state machines.

Covers difficulty rules boundary_precision_check, resource_temporal_overlap, and
non_linear_state_machine.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_underwriting_application, create_draft_application,
    reach_authorized, reach_fully_disbursed, reach_pending_approval,
    create_and_post_disbursement,
    file_and_accept_servicing_report, file_servicing_report,
    author_credit_memo,
    add_collateral, cleared_form_package,
    create_lender, create_borrower, create_application,
    TEST_USERS,
)
from test_helpers.api_client import api_client

OFFICER = TEST_USERS["loan_officer_headers"]
APPROVER = TEST_USERS["credit_approver_headers"]
SBA = TEST_USERS["sba_officer_headers"]


# ─── boundary_precision_check: size standard financial prong inclusive cap ────

def test_size_standard_financial_prong_passes_at_inclusive_caps(api):
    """PRD §3.4: "The financial prong holds when the borrower's `tangible_net_worth_cents` is at most twenty million dollars (that is, at most 2,000,000,000 cents)".
    PRD §3.4: "its `avg_net_income_cents` is at most six and a half million dollars (650,000,000 cents)".
    PRD §3.4: "All three caps are inclusive: a value sitting exactly at a cap satisfies that comparison."

    Design: Difficulty/boundary_precision_check/size_standard_financial_prong_inclusive_cap
    """
    # tnw exactly 2000000000, ni exactly 650000000, emp 9000 (headcount fails) -> only the
    # financial prong at its inclusive cap can pass.
    ctx = create_draft_application(
        borrower_overrides={
            "tangible_net_worth_cents": 2_000_000_000,
            "avg_net_income_cents": 650_000_000,
            "affiliate_employee_count": 9000,
        })
    aid = ctx["application"]["id"]
    res = api.submit_application(aid, OFFICER)
    app = validate_success(res, 200)
    assert app["size_eligible"] is True
    assert app["status"] == "UNDERWRITING"


def test_size_standard_one_cent_over_financial_cap_fails(api):
    """PRD §3.4: "All three caps are inclusive: a value sitting exactly at a cap satisfies
    that comparison."
    PRD §3.4: "if the determination comes back ineligible, the submit is rejected with `ERR_SIZE_STANDARD_EXCEEDED` and no transition occurs."

    Design: Difficulty/boundary_precision_check/size_standard_financial_prong_inclusive_cap
    """
    # tnw 2000000001 (one cent over), ni 650000001 (one cent over), emp 9000 (headcount fails)
    # -> neither prong passes -> ineligible.
    ctx = create_draft_application(
        borrower_overrides={
            "tangible_net_worth_cents": 2_000_000_001,
            "avg_net_income_cents": 650_000_001,
            "affiliate_employee_count": 9000,
        })
    aid = ctx["application"]["id"]
    res = api.submit_application(aid, OFFICER)
    validate_error(res, ApiErrorId.ERR_SIZE_STANDARD_EXCEEDED.value)


# ─── boundary_precision_check: over-disbursement exact remaining boundary ─────

def test_disbursement_exact_remaining_amount_is_allowed(api):
    """PRD §3.7: "the running `disbursed_amount_cents` plus this draw's `amount_cents` must not exceed `requested_amount_cents`, or the post is rejected with `ERR_OVER_DISBURSEMENT`."

    Design: Difficulty/boundary_precision_check/over_disbursement_exact_remaining_boundary
    """
    # requested 50000000; first draw 30000000 POSTED [0,30); second draw exactly 20000000
    # [30,60) -> 30000000 + 20000000 == 50000000, boundary inclusive (allowed).
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    create_and_post_disbursement(aid, 30_000_000, 0, 30, label="Draw 1")
    d2 = validate_success(api.create_disbursement(
        {"application_id": aid, "amount_cents": 20_000_000, "tranche_label": "Draw 2",
         "draw_window_start_day": 30, "draw_window_end_day": 60}, OFFICER), 201)
    res = api.post_disbursement(d2["id"], OFFICER)
    posted = validate_success(res, 200)
    assert posted["status"] == "POSTED"
    app = validate_success(api.get_application(aid, SBA), 200)
    assert app["disbursed_amount_cents"] == 50_000_000


def test_disbursement_one_cent_over_remaining_is_rejected(api):
    """PRD §3.7: "the running `disbursed_amount_cents` plus this draw's `amount_cents` must not exceed `requested_amount_cents`, or the post is rejected with `ERR_OVER_DISBURSEMENT`."

    Design: Difficulty/boundary_precision_check/over_disbursement_exact_remaining_boundary
    """
    # requested 50000000; first draw 30000000 POSTED; second 20000001 -> 50000001 > 50000000.
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    create_and_post_disbursement(aid, 30_000_000, 0, 30, label="Draw 1")
    d2 = validate_success(api.create_disbursement(
        {"application_id": aid, "amount_cents": 20_000_001, "tranche_label": "Draw 2",
         "draw_window_start_day": 30, "draw_window_end_day": 60}, OFFICER), 201)
    res = api.post_disbursement(d2["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_OVER_DISBURSEMENT.value)


# ─── resource_temporal_overlap: half-open draw window overlap ─────────────────

def test_draw_window_genuine_overlap_rejected(api):
    """PRD §3.7: "this draw's half-open window must not overlap the window of any other already-`POSTED` draw on the same application; two windows that merely touch — where one window's `draw_window_end_day` equals another's `draw_window_start_day` — do not overlap, but any genuine overlap is rejected with `ERR_DRAW_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/disbursement_draw_window_halfopen_overlap
    """
    # first draw [0,30) POSTED; second draw [20,40) overlaps on [20,30) -> rejected.
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    create_and_post_disbursement(aid, 10_000_000, 0, 30, label="Draw 1")
    d2 = validate_success(api.create_disbursement(
        {"application_id": aid, "amount_cents": 10_000_000, "tranche_label": "Draw 2",
         "draw_window_start_day": 20, "draw_window_end_day": 40}, OFFICER), 201)
    res = api.post_disbursement(d2["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_DRAW_WINDOW_OVERLAP.value)
    app = validate_success(api.get_application(aid, SBA), 200)
    assert app["disbursed_amount_cents"] == 10_000_000


def test_draw_window_touching_endpoints_do_not_overlap(api):
    """PRD §3.7: "two windows that merely touch — where one window's `draw_window_end_day` equals another's `draw_window_start_day` — do not overlap".

    Design: Difficulty/resource_temporal_overlap/disbursement_draw_window_halfopen_overlap
    """
    # first draw [0,30) POSTED; second draw [30,60) touches at endpoint -> allowed.
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    create_and_post_disbursement(aid, 10_000_000, 0, 30, label="Draw 1")
    d2 = validate_success(api.create_disbursement(
        {"application_id": aid, "amount_cents": 10_000_000, "tranche_label": "Draw 2",
         "draw_window_start_day": 30, "draw_window_end_day": 60}, OFFICER), 201)
    res = api.post_disbursement(d2["id"], OFFICER)
    posted = validate_success(res, 200)
    assert posted["status"] == "POSTED"


# ─── resource_temporal_overlap: closed servicing interval contiguity ──────────

def test_servicing_period_overlapping_closed_interval_rejected(api):
    """PRD §3.9: "its `period_start_month` must equal one plus the largest `period_end_month` among already-accepted reports on the application, or 0 if this is the first accepted report; otherwise the accept is rejected with `ERR_PERIOD_OUT_OF_ORDER`."
    PRD §3.9: "The coverage interval is closed on both ends — it spans from `period_start_month` through `period_end_month` inclusive".

    Design: Difficulty/resource_temporal_overlap/servicing_period_interval_closed_contiguous
    """
    # First accepted report covers closed [0,2]; next must start at month 3. A report starting
    # at month 2 overlaps the prior closed end -> rejected.
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    file_and_accept_servicing_report(aid, 0, 2, principal_paid_cents=0, days_past_due=0)
    rpt1 = file_servicing_report(aid, 2, 4, principal_paid_cents=0, days_past_due=0, period_index=2)
    res = api.accept_servicing_report(rpt1["id"], SBA)
    validate_error(res, ApiErrorId.ERR_PERIOD_OUT_OF_ORDER.value)


def test_servicing_period_contiguous_next_interval_accepted(api):
    """PRD §3.9: "its `period_start_month` must equal one plus the largest `period_end_month` among already-accepted reports on the application, or 0 if this is the first accepted report".

    Design: Difficulty/resource_temporal_overlap/servicing_period_interval_closed_contiguous
    """
    # First accepted report covers closed [0,2]; the contiguous next starts at month 3 -> accepted.
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    file_and_accept_servicing_report(aid, 0, 2, principal_paid_cents=0, days_past_due=0)
    rpt1 = file_servicing_report(aid, 3, 4, principal_paid_cents=0, days_past_due=0, period_index=3)
    res = api.accept_servicing_report(rpt1["id"], SBA)
    accepted = validate_success(res, 200)
    assert accepted["status"] == "ACCEPTED"


# ─── non_linear_state_machine: application underwriting/revision cycle ────────

def test_application_revision_cycle_reenters_underwriting(api):
    """PRD §3.5: "A `CreditApprover` requests revision on a `PENDING_APPROVAL` application, which moves `status` to `REVISION` and sets the currently submitted credit memo back to `REJECTED`".
    PRD §3.5: "a `LoanOfficer` resubmits the revised application, moving `status` from `REVISION` back to `UNDERWRITING`; resubmission requires that a `DRAFT` credit memo exist (a revision must have been authored), or it is rejected with `ERR_NO_CREDIT_MEMO`."

    Design: Difficulty/non_linear_state_machine/application_underwriting_revision_cycle
    """
    ctx = reach_pending_approval(recommendation="APPROVE")
    aid = ctx["application"]["id"]
    cm1_id = ctx["credit_memo"]["id"]
    # Approver requests revision -> REVISION, cm1 REJECTED.
    validate_success(api.request_revision(aid, APPROVER), 200)
    # Officer authors a new DRAFT memo (cm2) and resubmits -> back to UNDERWRITING.
    cm2 = author_credit_memo(aid, recommendation="APPROVE", dscr=1.40, risk_rating=3)
    res = api.resubmit_application(aid, OFFICER)
    app = validate_success(res, 200)
    assert app["status"] == "UNDERWRITING"

    memos = validate_success(api.list_credit_memos(aid, SBA), 200)
    by_id = {m["id"]: m for m in memos}
    assert by_id[cm1_id]["status"] == "REJECTED"
    assert by_id[cm2["id"]]["status"] == "DRAFT"


def test_request_revision_rejects_submitted_credit_memo(api):
    """PRD §3.5: "A `CreditApprover` requests revision on a `PENDING_APPROVAL` application, which moves `status` to `REVISION` and sets the currently submitted credit memo back to `REJECTED`".

    Design: Difficulty/non_linear_state_machine/application_underwriting_revision_cycle
    """
    ctx = reach_pending_approval(recommendation="APPROVE")
    aid = ctx["application"]["id"]
    cm1_id = ctx["credit_memo"]["id"]
    revised = validate_success(api.request_revision(aid, APPROVER), 200)
    assert revised["status"] == "REVISION"
    memos = validate_success(api.list_credit_memos(aid, SBA), 200)
    by_id = {m["id"]: m for m in memos}
    assert by_id[cm1_id]["status"] == "REJECTED"


# ─── non_linear_state_machine: form package branching to FLAGGED ──────────────

def test_form_package_review_branches_to_flagged_when_not_cleared(api):
    """PRD §3.3: "When `character_cleared` is false, the package instead moves to `FLAGGED`, which leaves credit-memo submission blocked."

    Design: Difficulty/non_linear_state_machine/form_package_branching_submitted_to_flagged
    """
    ctx = create_underwriting_application()
    aid = ctx["application"]["id"]
    fp = validate_success(api.create_form_package(
        {"application_id": aid, "form_1919_complete": True, "form_1920_complete": True,
         "character_cleared": False}, OFFICER), 201)
    validate_success(api.submit_form_package(fp["id"], OFFICER), 200)
    res = api.review_form_package(fp["id"], APPROVER)
    reviewed = validate_success(res, 200)
    assert reviewed["status"] == "FLAGGED"


def test_flagged_form_package_reopens_to_incomplete(api):
    """PRD §3.3: "A `FLAGGED` package can be reopened by a `LoanOfficer`, which loops it back to `INCOMPLETE` for correction".

    Design: Difficulty/non_linear_state_machine/form_package_branching_submitted_to_flagged
    """
    ctx = create_underwriting_application()
    aid = ctx["application"]["id"]
    fp = validate_success(api.create_form_package(
        {"application_id": aid, "form_1919_complete": True, "form_1920_complete": True,
         "character_cleared": False}, OFFICER), 201)
    validate_success(api.submit_form_package(fp["id"], OFFICER), 200)
    validate_success(api.review_form_package(fp["id"], APPROVER), 200)  # -> FLAGGED
    res = api.reopen_form_package(fp["id"], OFFICER)
    reopened = validate_success(res, 200)
    assert reopened["status"] == "INCOMPLETE"
