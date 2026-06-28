"""Composite setup helpers.

Every test runs against a freshly re-launched server with an empty database,
so each fixture builds all of its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data() (lenient) so a
broken precondition surfaces as a clear "Setup failed" rather than an obscure
assertion error.

Guardian is the only entity_backed role: ownership-gated guardian calls thread
the real Guardian.id through make_guardian_headers(guardian_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_director_headers, make_nurse_headers, make_guardian_headers,
    make_anonymous_headers,
)
from . import factories as F

DIRECTOR = make_director_headers()
NURSE = make_nurse_headers()
ANON = make_anonymous_headers()

DEFAULT_CLOCK = "2026-04-01T00:00:00Z"
DEFAULT_START = "2026-07-01T00:00:00Z"
DEFAULT_END = "2026-07-14T00:00:00Z"
DEFAULT_VISITING = "2026-07-07T00:00:00Z"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the logical clock (director-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def make_camp(clock=DEFAULT_CLOCK, **camp_overrides) -> dict:
    """Set the clock and create a Camp. Returns the Camp dict."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.create_camp(F.create_camp_payload(**camp_overrides), DIRECTOR))


def make_session(camp_id: str, **session_overrides) -> dict:
    """Create a Session under a Camp. Returns the Session dict."""
    return get_success_data(
        api_client.create_session(camp_id, F.create_session_payload(**session_overrides), DIRECTOR)
    )


def make_cabin(session_id: str, **cabin_overrides) -> dict:
    """Create a Cabin under a Session. Returns the Cabin dict."""
    return get_success_data(
        api_client.create_cabin(session_id, F.create_cabin_payload(**cabin_overrides), DIRECTOR)
    )


def make_cleared_staff(camp_id: str, role_kind="COUNSELOR", **overrides) -> dict:
    """Create a background-cleared StaffMember. Returns the StaffMember dict."""
    return get_success_data(
        api_client.create_staff(
            camp_id, F.create_staff_payload(role_kind=role_kind, **overrides), DIRECTOR
        )
    )


def assign_staff(cabin_id: str, staff_member_id: str) -> dict:
    """Create an ACTIVE CabinAssignment. Returns the assignment dict."""
    return get_success_data(
        api_client.create_cabin_assignment(
            F.create_cabin_assignment_payload(cabin_id, staff_member_id), DIRECTOR
        )
    )


def open_enrollment(session_id: str, expected_version: int) -> dict:
    """Move a Session PLANNING -> ENROLLING. Returns the updated Session dict."""
    return get_success_data(
        api_client.open_enrollment(session_id, {"expected_session_version": expected_version}, DIRECTOR)
    )


def register_guardian(**overrides) -> dict:
    """Register a Guardian (anonymous). Returns the Guardian dict."""
    return get_success_data(
        api_client.register_guardian(F.register_guardian_payload(**overrides), ANON)
    )


def make_camper(guardian_id: str, **overrides) -> dict:
    """Create a Camper owned by the guardian. Returns the Camper dict."""
    return get_success_data(
        api_client.create_camper(F.create_camper_payload(**overrides), make_guardian_headers(guardian_id))
    )


def make_health_form(guardian_id: str, camper_id: str, **overrides) -> dict:
    """Create a DRAFT HealthForm. Returns the HealthForm dict."""
    return get_success_data(
        api_client.create_health_form(
            F.create_health_form_payload(camper_id, **overrides), make_guardian_headers(guardian_id)
        )
    )


def submit_health_form(guardian_id: str, hf_id: str) -> dict:
    return get_success_data(api_client.submit_health_form(hf_id, make_guardian_headers(guardian_id)))


def clear_health_form(hf_id: str, review_note="ok") -> dict:
    return get_success_data(api_client.clear_health_form(hf_id, {"review_note": review_note}, NURSE))


def flag_health_form(hf_id: str, review_note="needs revision") -> dict:
    return get_success_data(api_client.flag_health_form(hf_id, {"review_note": review_note}, NURSE))


# ---------------------------------------------------------------------------
# Tier 1: open ENROLLING session builders
# ---------------------------------------------------------------------------
def setup_enrolling_session(camp_overrides=None, session_overrides=None, cabin_overrides=None):
    """Camp + Session + one Cabin + open-enrollment (Session now ENROLLING).

    Returns dict with keys: camp, session (post-open, current version), cabin.
    The cabin defaults to a BOYS 8-12 cabin large enough for ordinary tests.
    """
    camp = make_camp(**(camp_overrides or {}))
    session = make_session(camp["id"], **(session_overrides or {}))
    cabin = make_cabin(session["id"], **(cabin_overrides or {}))
    session = open_enrollment(session["id"], session["version"])
    return {"camp": camp, "session": session, "cabin": cabin}


def setup_enrolling_session_with_staffed_cabin(camp_overrides=None, session_overrides=None,
                                               cabin_overrides=None, num_counselors=1):
    """Camp + Session + one Cabin with `num_counselors` cleared COUNSELORs
    assigned (staff_weight_x10 = 10 * num_counselors) + open-enrollment.

    Returns dict: camp, session, cabin, staff (list of StaffMember dicts).
    """
    camp = make_camp(**(camp_overrides or {}))
    session = make_session(camp["id"], **(session_overrides or {}))
    cabin = make_cabin(session["id"], **(cabin_overrides or {}))
    staff = []
    for i in range(num_counselors):
        sm = make_cleared_staff(camp["id"], role_kind="COUNSELOR", full_name=f"Counselor {i}")
        assign_staff(cabin["id"], sm["id"])
        staff.append(sm)
    session = open_enrollment(session["id"], session["version"])
    return {"camp": camp, "session": session, "cabin": cabin, "staff": staff}


# ---------------------------------------------------------------------------
# Tier 2/3: applicant lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_guardian_camper(email="g@x.com", camper_overrides=None, health_form_overrides=None,
                          submit_health=True, clear_health=False):
    """Register a guardian, create a camper, and (optionally) create+submit+clear
    a health form.

    Returns dict: guardian, camper, health_form (or None if not created).
    """
    guardian = register_guardian(email=email)
    camper = make_camper(guardian["id"], **(camper_overrides or {}))
    hf = None
    if health_form_overrides is not None or submit_health:
        hf = make_health_form(guardian["id"], camper["id"], **(health_form_overrides or {}))
        if submit_health:
            submit_health_form(guardian["id"], hf["id"])
            if clear_health:
                clear_health_form(hf["id"])
    return {"guardian": guardian, "camper": camper, "health_form": hf}


def setup_submitted_application(env, email="g@x.com", camper_overrides=None,
                                health_form_overrides=None, clear_health=False):
    """Given an ENROLLING-session env (from setup_enrolling_session*), build a
    guardian+camper+submitted-health-form and submit an application.

    Returns dict merged from setup_guardian_camper plus: application (post-submit).
    """
    gc = setup_guardian_camper(
        email=email, camper_overrides=camper_overrides,
        health_form_overrides=health_form_overrides, submit_health=True,
        clear_health=clear_health,
    )
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    app = get_success_data(
        api_client.create_application(
            F.create_application_payload(gc["camper"]["id"], env["session"]["id"]), g_headers
        )
    )
    app = get_success_data(api_client.submit_application(app["id"], g_headers))
    gc["application"] = app
    return gc


def setup_offered_application(env, email="g@x.com", camper_overrides=None,
                              health_form_overrides=None, clear_health=False):
    """Submitted application that landed in OFFERED (requires free capacity).
    Returns the same dict as setup_submitted_application."""
    return setup_submitted_application(
        env, email=email, camper_overrides=camper_overrides,
        health_form_overrides=health_form_overrides, clear_health=clear_health,
    )


def setup_deposit_paid_application(env, deposit_cents=25_000, email="g@x.com",
                                   camper_overrides=None, health_form_overrides=None,
                                   clear_health=False):
    """OFFERED application advanced to DEPOSIT_PAID by paying the deposit.
    Returns dict from setup_submitted_application with application updated to
    DEPOSIT_PAID."""
    gc = setup_submitted_application(
        env, email=email, camper_overrides=camper_overrides,
        health_form_overrides=health_form_overrides, clear_health=clear_health,
    )
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    app = get_success_data(
        api_client.pay_deposit(gc["application"]["id"], {"amount_cents": deposit_cents}, g_headers)
    )
    gc["application"] = app
    return gc


def assign_bunk(cabin_id: str, application_id: str):
    """Assign a DEPOSIT_PAID application's camper to a bunk in cabin_id,
    reading the cabin's live version for OCC. Returns updated Cabin dict."""
    cab = get_success_data(api_client.get_cabin(cabin_id, DIRECTOR))
    return get_success_data(
        api_client.assign_bunk(
            cabin_id,
            {"application_id": application_id, "expected_cabin_version": cab["version"]},
            DIRECTOR,
        )
    )


def setup_bunked_application(env, cabin_id=None, deposit_cents=25_000, email="g@x.com",
                             camper_overrides=None, health_form_overrides=None,
                             clear_health=False):
    """DEPOSIT_PAID application with a bunk assigned in the env's cabin.
    Returns dict from setup_deposit_paid_application plus refreshed application."""
    gc = setup_deposit_paid_application(
        env, deposit_cents=deposit_cents, email=email, camper_overrides=camper_overrides,
        health_form_overrides=health_form_overrides, clear_health=clear_health,
    )
    target_cabin = cabin_id or env["cabin"]["id"]
    assign_bunk(target_cabin, gc["application"]["id"])
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    gc["application"] = get_success_data(api_client.get_application(gc["application"]["id"], g_headers))
    return gc


def setup_enrolled_application(env, cabin_id=None, deposit_cents=25_000, email="g@x.com",
                               camper_overrides=None, health_form_overrides=None):
    """Full lifecycle to ENROLLED: requires the env cabin to be staffed and the
    camper health-cleared. Returns dict from setup_bunked_application plus the
    enrolled application."""
    gc = setup_bunked_application(
        env, cabin_id=cabin_id, deposit_cents=deposit_cents, email=email,
        camper_overrides=camper_overrides, health_form_overrides=health_form_overrides,
        clear_health=True,
    )
    app = get_success_data(api_client.enroll_application(gc["application"]["id"], DIRECTOR))
    gc["application"] = app
    return gc


# ---------------------------------------------------------------------------
# Tier 4: financial-aid + balance shortcuts
# ---------------------------------------------------------------------------
def request_aid(guardian_id: str, application_id: str, amount_cents: int,
                kind="NEED_GRANT") -> dict:
    """Guardian requests a FinancialAidAward (REQUESTED). Returns the award."""
    return get_success_data(
        api_client.create_financial_aid(
            F.create_financial_aid_payload(application_id, amount_cents, kind=kind),
            make_guardian_headers(guardian_id),
        )
    )


def approve_aid(aid_id: str, application_id: str) -> dict:
    """Approve an aid award, reading the application's live version for OCC.
    Returns the updated award dict."""
    app = get_success_data(api_client.get_application(application_id, DIRECTOR))
    return get_success_data(
        api_client.approve_aid(aid_id, {"expected_application_version": app["version"]}, DIRECTOR)
    )


# ---------------------------------------------------------------------------
# Activity / canteen shortcuts
# ---------------------------------------------------------------------------
def make_activity(session_id: str, **overrides) -> dict:
    """Create an ActivityOffering. Returns the offering dict."""
    return get_success_data(
        api_client.create_activity(session_id, F.create_activity_payload(**overrides), DIRECTOR)
    )


def book_activity(guardian_id: str, offering_id: str, application_id: str) -> dict:
    """Book a camper into an elective (BOOKED). Returns the enrollment dict."""
    return get_success_data(
        api_client.create_activity_enrollment(
            F.create_activity_enrollment_payload(offering_id, application_id),
            make_guardian_headers(guardian_id),
        )
    )


def open_canteen_account(guardian_id: str, application_id: str) -> dict:
    """Open a CanteenAccount for an application. Returns the account dict."""
    return get_success_data(
        api_client.create_canteen_account(
            F.create_canteen_account_payload(application_id), make_guardian_headers(guardian_id)
        )
    )


def canteen_txn(guardian_id: str, account_id: str, kind: str, amount_cents: int) -> dict:
    """Record a canteen DEPOSIT/PURCHASE. Returns the transaction dict."""
    return get_success_data(
        api_client.create_canteen_transaction(
            account_id, F.create_canteen_transaction_payload(kind, amount_cents),
            make_guardian_headers(guardian_id),
        )
    )


def setup_canteen_with_balance(env, deposit_amount_cents, email="g@x.com"):
    """Submitted application + open canteen account + one DEPOSIT of
    deposit_amount_cents (balance == deposit_amount_cents).

    Returns dict: guardian, camper, application, account.
    """
    gc = setup_submitted_application(env, email=email)
    g_id = gc["guardian"]["id"]
    account = open_canteen_account(g_id, gc["application"]["id"])
    if deposit_amount_cents > 0:
        canteen_txn(g_id, account["id"], "DEPOSIT", deposit_amount_cents)
        account = get_success_data(
            api_client.get_canteen_account(account["id"], make_guardian_headers(g_id))
        )
    gc["account"] = account
    return gc
