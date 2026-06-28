"""RBAC denials, missing-auth rejection, and additional terminal-state /
not-submittable error paths (rbac and errors sections from queue B).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_practice, create_consultant, create_client,
    setup_practice_with_consultant_and_client, create_consult,
    create_completed_consult, create_submitted_superbill,
    create_open_follow_up_plan, create_pending_dme,
    create_practice_payload, create_consult_payload, create_superbill_payload,
    create_feeding_assessment_payload,
    close_follow_up_plan, make_consultant_headers, make_client_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["practice_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
CONSULTANT_SHARED = TEST_USERS["consultant_headers"]


# ─── rbac / frontdesk_cannot_complete_consult_returns_403 ───────────────────

def test_frontdesk_cannot_complete_consult(api):
    """PRD §4 endpoint table: POST `/consults/{id}/complete` is authorized for role
    `Consultant` only.
    PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    FrontDesk calling the Consultant-exclusive complete endpoint is denied.

    Design: Corner/rbac/frontdesk_cannot_complete_consult_returns_403
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T15:00:00Z")
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")
    get_success_data(api.create_feeding_assessment(
        create_feeding_assessment_payload(consult["id"]), make_consultant_headers(cons["id"])))
    get_success_data(api.start_consult(consult["id"], make_consultant_headers(cons["id"])))

    resp = api.complete_consult(consult["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac / consultant_cannot_draft_superbill_returns_403 ───────────────────

def test_consultant_cannot_draft_superbill(api):
    """PRD §4 endpoint table: POST `/superbills` is authorized for role
    `BillingSpecialist` only.
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE`."

    A Consultant calling the BillingSpecialist-exclusive draft endpoint is denied.

    Design: Corner/rbac/consultant_cannot_draft_superbill_returns_403
    """
    ctx = create_completed_consult()
    resp = api.create_superbill(create_superbill_payload(
        ctx["consult"]["id"], 25000, 15000, is_aca_preventive=True),
        make_consultant_headers(ctx["consultant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac / client_cannot_create_consult_returns_403 ────────────────────────

def test_client_cannot_create_consult(api):
    """PRD §2.1: "A `Client` has read-only access to their own practice, clients
    record, consults, follow-up plans, weighted feeds, superbills, DME
    qualifications, and pediatrician referrals."
    PRD §4 endpoint table: POST `/consults` is authorized for FrontDesk,
    PracticeAdmin.

    The read-only Client role calling POST /consults is denied ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/client_cannot_create_consult_returns_403
    """
    prac = create_practice(name="Solo Practice")
    cons = create_consultant(prac["id"])
    client = create_client(prac["id"])
    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z"),
        make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── errors / missing_auth_context_returns_401 ──────────────────────────────

def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers. `X-User-ID` identifies the acting user, and
    `X-User-Role` declares the operational capacity under which they are acting. If
    either header is missing or malformed, the request is rejected with
    `ERR_MISSING_AUTH_CONTEXT`."

    POST /practices with no auth headers is rejected ERR_MISSING_AUTH_CONTEXT.

    Design: Corner/errors/missing_auth_context_returns_401
    """
    resp = api.create_practice(create_practice_payload(name="No Auth Practice"), {})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT.value)


# ─── errors / dme_adjudicate_not_pending_returns_error ──────────────────────

def test_adjudicate_already_qualified_dme_rejected(api):
    """PRD §3.10: "Adjudicating a DME qualification is a `BillingSpecialist` action on
    a `PENDING` qualification (otherwise `ERR_DME_NOT_PENDING`)."

    A second adjudicate on an already-QUALIFIED (terminal) DME is rejected
    ERR_DME_NOT_PENDING.

    Design: Corner/errors/dme_adjudicate_not_pending_returns_error
    """
    ctx = create_pending_dme(
        pump_type="HOSPITAL_GRADE",
        infant_dob="2026-06-01T00:00:00Z",
        consult_clock="2026-06-20T15:00:00Z",
        request_clock="2026-06-20T15:00:00Z")
    validate_success(api.adjudicate_dme_qualification(ctx["dme"]["id"], BILLING), 200)
    resp = api.adjudicate_dme_qualification(ctx["dme"]["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_DME_NOT_PENDING.value)


# ─── errors / close_already_closed_plan_returns_not_open ────────────────────

def test_close_already_closed_plan_rejected(api):
    """PRD §3.8: "Closing a follow-up plan is a `Consultant` action that advances
    `OPEN → CLOSED`; it requires the plan to be `OPEN`, otherwise `ERR_PLAN_NOT_OPEN`."

    A second close on a CLOSED plan is rejected ERR_PLAN_NOT_OPEN.

    Design: Corner/errors/close_already_closed_plan_returns_not_open
    """
    ctx = create_open_follow_up_plan(target_daily_transfer_grams=100)
    plan, cons = ctx["plan"], ctx["consultant"]
    close_follow_up_plan(plan["id"], cons["id"])
    resp = api.close_follow_up_plan(plan["id"], make_consultant_headers(cons["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_OPEN.value)


# ─── errors / superbill_resubmit_from_draft_only_when_draft_or_denied ───────

def test_submit_already_submitted_superbill_rejected(api):
    """PRD §3.9: "Submitting moves the superbill `DRAFT → SUBMITTED`; it requires the
    superbill to be in `DRAFT` (the not-submittable state error is
    `ERR_SUPERBILL_NOT_SUBMITTABLE`)".

    A second submit on an already-SUBMITTED superbill is rejected
    ERR_SUPERBILL_NOT_SUBMITTABLE.

    Design: Corner/errors/superbill_resubmit_from_draft_only_when_draft_or_denied
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000, is_aca_preventive=True)
    resp = api.submit_superbill(ctx["superbill"]["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_SUPERBILL_NOT_SUBMITTABLE.value)


# ─── errors / client_double_booked_returns_409 (covered in test_01) ─────────
# This instance's assertion is also exercised in test_01_consult_scheduling_and_fees.py
# (test_client_double_booked_overlap_rejected). One test per corner instance suffices.
