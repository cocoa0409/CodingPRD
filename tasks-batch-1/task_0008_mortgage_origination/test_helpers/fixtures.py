"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the server before every individual pytest test, so each
fixture builds its entire precondition graph from scratch using only PRD-declared
endpoints. Setup calls go through `get_success_data` (lenient validator) so
genuine setup failures surface as clear "setup failed" messages instead of
confusing assertion errors deep inside a test.

Roles in this PRD:
- Six opaque roles (LoanOfficer, Underwriter, Closer, Appraiser, TitleAgent,
  ComplianceOfficer) — X-User-ID is an arbitrary operator string the server
  does not reconcile against any entity.
- One entity-backed role (Applicant) — X-User-ID MUST equal the acting
  Applicant.id. Fixtures that need to acknowledge a disclosure call
  `make_applicant_headers(applicant['id'])` against the freshly-created applicant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_loan_application_payload,
    create_income_verification_payload,
    create_asset_verification_payload,
    create_appraisal_payload,
    complete_appraisal_payload,
    create_title_search_payload,
    create_rate_lock_payload,
    create_disclosure_payload,
    create_udaap_check_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_loan_officer_headers,
)


# ---------------------------------------------------------------------
# Tier 0: clock helper
# ---------------------------------------------------------------------
def set_clock(to_iso8601: str, role_headers: dict = None) -> None:
    """Pin the system clock to a fixed UTC instant (PRD §2.10).

    The clock endpoint is accepted from every role; we use LoanOfficer
    headers by default unless the caller passes its own."""
    headers = role_headers or TEST_USERS["loan_officer_headers"]
    res = api_client.set_clock(to_iso8601, headers)
    get_success_data(res)


# ---------------------------------------------------------------------
# Tier 1: state progression — single-entity advances
# ---------------------------------------------------------------------
def create_applicant(*, headers: dict = None, **overrides) -> dict:
    """Create one Applicant. Returns the applicant dict."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    res = api_client.create_applicant(create_applicant_payload(**overrides), headers)
    return get_success_data(res)


def create_loan_application(applicant_id: str, *, headers: dict = None, **overrides) -> dict:
    """Create one LoanApplication. Returns the application dict (DRAFT)."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    res = api_client.create_loan_application(
        create_loan_application_payload(applicant_id, **overrides),
        headers,
    )
    return get_success_data(res)


def prequalify_loan_application(app_id: str, *, headers: dict = None) -> dict:
    """Run prequalify on a DRAFT loan application. Returns the updated app."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    res = api_client.prequalify_loan_application(app_id, headers)
    return get_success_data(res)


def get_loan_application(app_id: str, *, headers: dict = None) -> dict:
    """Read a LoanApplication and return its dict (useful for fetching version)."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    res = api_client.get_loan_application(app_id, headers)
    return get_success_data(res)


# ---------------------------------------------------------------------
# Tier 2: composite — applicant + loan-application in given lifecycle state
# ---------------------------------------------------------------------
def setup_applicant_and_loan_application_draft(
    *,
    applicant_overrides: dict = None,
    loan_overrides: dict = None,
    headers: dict = None,
) -> tuple:
    """Empty DB → 1 Applicant + 1 LoanApplication in DRAFT.

    Returns (applicant, loan_application).
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    applicant = create_applicant(headers=headers, **(applicant_overrides or {}))
    app = create_loan_application(
        applicant["id"], headers=headers, **(loan_overrides or {})
    )
    return applicant, app


def setup_prequalified_loan_application(
    *,
    applicant_overrides: dict = None,
    loan_overrides: dict = None,
    headers: dict = None,
) -> tuple:
    """Empty DB → applicant + loan-app prequalified to PREQUALIFIED.

    Returns (applicant, loan_application_after_prequalify).
    Caller can read `version` off the returned loan_application.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides=applicant_overrides,
        loan_overrides=loan_overrides,
        headers=headers,
    )
    app_after = prequalify_loan_application(app["id"], headers=headers)
    return applicant, app_after


# ---------------------------------------------------------------------
# Tier 2b: RateLock helper bound to an existing application
# ---------------------------------------------------------------------
def create_active_rate_lock(
    app_id: str,
    expected_application_version: int,
    *,
    locked_rate_bps: int = 687,
    lock_term_days: int = 30,
    headers: dict = None,
) -> dict:
    """Create one ACTIVE RateLock against an existing application.

    Returns the rate-lock dict.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    res = api_client.create_rate_lock(
        create_rate_lock_payload(
            app_id,
            expected_application_version,
            locked_rate_bps=locked_rate_bps,
            lock_term_days=lock_term_days,
        ),
        headers,
    )
    return get_success_data(res)


def setup_prequalified_with_active_lock(
    *,
    locked_rate_bps: int = 687,
    lock_term_days: int = 30,
    applicant_overrides: dict = None,
    loan_overrides: dict = None,
    clock_iso: str = None,
    headers: dict = None,
) -> tuple:
    """Empty DB → applicant + prequalified loan application + ACTIVE RateLock.

    If `clock_iso` is provided, the clock is pinned first so locked_at is
    deterministic.

    Returns (applicant, loan_application, lock).
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    if clock_iso:
        set_clock(clock_iso, role_headers=headers)
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides=applicant_overrides,
        loan_overrides=loan_overrides,
        headers=headers,
    )
    lock = create_active_rate_lock(
        app["id"],
        app["version"],
        locked_rate_bps=locked_rate_bps,
        lock_term_days=lock_term_days,
        headers=headers,
    )
    return applicant, app, lock


# ---------------------------------------------------------------------
# Tier 3: full APPROVED-ready chain
# ---------------------------------------------------------------------
def setup_under_review_with_all_green(
    *,
    locked_rate_bps: int = 687,
    lock_term_days: int = 60,
    annual_income_cents: int = 9_000_000,
    monthly_debt_cents: int = 50_000,
    property_value_cents: int = 35_000_000,
    appraised_value_cents: int = 35_000_000,
    udaap_outcome: str = "CLEARED",
    udaap_flagged_reasons=None,
    clock_iso: str = "2026-06-01T00:00:00Z",
    lo_user_id: str = "lo-001",
    uw_user_id: str = "uw-001",
) -> dict:
    """Empty DB → applicant + loan-application → prequalified → rate-lock →
    LE delivered → submit-for-review → IV ACCEPTED → AV ACCEPTED →
    Appraisal COMPLETED → TitleSearch CLEAR → UDAAPCheck recorded.

    The result is a LoanApplication in UNDER_REVIEW with every approve
    precondition satisfied EXCEPT (optionally) UDAAP outcome and SoD —
    callers can supply `udaap_outcome="FLAGGED"` or use the same X-User-ID for
    both LoanOfficer and Underwriter to test those gates.

    Returns a dict of relevant ids and the loan_application after submission:
      {
        "applicant": Applicant,
        "loan_application": LoanApplication (UNDER_REVIEW),
        "rate_lock": RateLock (ACTIVE),
        "loan_estimate": Disclosure (DELIVERED LOAN_ESTIMATE),
        "income_verification": IncomeVerification (ACCEPTED),
        "asset_verification": AssetVerification (ACCEPTED),
        "appraisal": Appraisal (COMPLETED),
        "title_search": TitleSearch (CLEAR),
        "udaap_check": UDAAPCheck,
        "lo_user_id": lo_user_id,
        "uw_user_id": uw_user_id,
      }
    """
    lo_headers = make_loan_officer_headers(lo_user_id)
    uw_headers = TEST_USERS["underwriter_headers"] if uw_user_id == "uw-001" \
        else {"X-User-ID": uw_user_id, "X-User-Role": "Underwriter", "Content-Type": "application/json"}
    appraiser_headers = TEST_USERS["appraiser_headers"]
    ta_headers = TEST_USERS["title_agent_headers"]
    co_headers = TEST_USERS["compliance_officer_headers"]

    set_clock(clock_iso, role_headers=lo_headers)
    applicant = create_applicant(
        headers=lo_headers,
        annual_income_cents=annual_income_cents,
        monthly_debt_cents=monthly_debt_cents,
    )
    app = create_loan_application(
        applicant["id"],
        headers=lo_headers,
        property_value_cents=property_value_cents,
    )
    app_after_prequal = prequalify_loan_application(app["id"], headers=lo_headers)

    lock = create_active_rate_lock(
        app["id"],
        app_after_prequal["version"],
        locked_rate_bps=locked_rate_bps,
        lock_term_days=lock_term_days,
        headers=lo_headers,
    )

    app_after_lock = get_loan_application(app["id"], headers=lo_headers)
    le_res = api_client.create_disclosure(
        create_disclosure_payload(
            app["id"], "LOAN_ESTIMATE", app_after_lock["version"]
        ),
        lo_headers,
    )
    le = get_success_data(le_res)
    le_delivered = get_success_data(
        api_client.deliver_disclosure(le["id"], lo_headers)
    )

    get_success_data(
        api_client.submit_for_review_loan_application(app["id"], lo_headers)
    )

    iv = get_success_data(
        api_client.create_income_verification(
            create_income_verification_payload(
                app["id"], verified_annual_income_cents=annual_income_cents
            ),
            lo_headers,
        )
    )
    iv_after = get_success_data(api_client.accept_income_verification(iv["id"], uw_headers))

    av = get_success_data(
        api_client.create_asset_verification(
            create_asset_verification_payload(app["id"]),
            lo_headers,
        )
    )
    av_after = get_success_data(api_client.accept_asset_verification(av["id"], uw_headers))

    appr = get_success_data(
        api_client.create_appraisal(
            create_appraisal_payload(app["id"]), lo_headers
        )
    )
    appr_after = get_success_data(
        api_client.complete_appraisal(
            appr["id"],
            complete_appraisal_payload(appraised_value_cents),
            appraiser_headers,
        )
    )

    ts = get_success_data(
        api_client.create_title_search(
            create_title_search_payload(app["id"]), lo_headers
        )
    )
    ts_after = get_success_data(
        api_client.mark_clear_title_search(ts["id"], ta_headers)
    )

    udaap_payload = create_udaap_check_payload(
        app["id"],
        review_outcome=udaap_outcome,
        flagged_reasons=udaap_flagged_reasons,
    )
    udaap = get_success_data(
        api_client.create_udaap_check(udaap_payload, co_headers)
    )

    # Re-read the loan application to surface the current version.
    app_under_review = get_loan_application(app["id"], headers=lo_headers)

    return {
        "applicant": applicant,
        "loan_application": app_under_review,
        "rate_lock": lock,
        "loan_estimate": le_delivered,
        "income_verification": iv_after,
        "asset_verification": av_after,
        "appraisal": appr_after,
        "title_search": ts_after,
        "udaap_check": udaap,
        "lo_user_id": lo_user_id,
        "uw_user_id": uw_user_id,
    }


# ---------------------------------------------------------------------
# Tier 4: APPROVED-ready chain + approve action
# ---------------------------------------------------------------------
def setup_approved_loan_application(
    *,
    locked_rate_bps: int = 687,
    lock_term_days: int = 60,
    appraised_value_cents: int = 35_000_000,
    property_value_cents: int = 35_000_000,
    annual_income_cents: int = 9_000_000,
    clock_iso: str = "2026-06-01T00:00:00Z",
    lo_user_id: str = "lo-001",
    uw_user_id: str = "uw-001",
) -> dict:
    """Full chain through APPROVED. Returns the same dict shape as
    setup_under_review_with_all_green plus the approved loan_application.
    """
    ctx = setup_under_review_with_all_green(
        locked_rate_bps=locked_rate_bps,
        lock_term_days=lock_term_days,
        annual_income_cents=annual_income_cents,
        property_value_cents=property_value_cents,
        appraised_value_cents=appraised_value_cents,
        udaap_outcome="CLEARED",
        udaap_flagged_reasons=None,
        clock_iso=clock_iso,
        lo_user_id=lo_user_id,
        uw_user_id=uw_user_id,
    )
    uw_headers = (
        TEST_USERS["underwriter_headers"] if uw_user_id == "uw-001"
        else {"X-User-ID": uw_user_id, "X-User-Role": "Underwriter", "Content-Type": "application/json"}
    )
    approved = get_success_data(
        api_client.approve_loan_application(ctx["loan_application"]["id"], uw_headers)
    )
    ctx["loan_application"] = approved
    return ctx
