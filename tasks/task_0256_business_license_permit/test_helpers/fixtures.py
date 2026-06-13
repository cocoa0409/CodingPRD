"""Composite setup helpers for multi-step test prerequisites.

Every individual pytest test runs against a freshly-restarted, empty-database
server, so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Fixtures use get_success_data() (lenient validator)
internally so setup failures surface as clear "Setup failed" errors.

Identity threading: the Applicant role is entity-backed:Business, so every
ownership-gated call (submit/withdraw/renew/surrender/settle/transfer-request)
threads make_applicant_headers(business["id"]). LicensingOfficer and
InspectionOfficer are opaque operator identities.

Time convention: the PRD keeps a logical clock that a LicensingOfficer advances
via /_clock/set_current_utc (§3.6, §3.10). Fixtures pin the clock to
DEFAULT_CLOCK = 2026-06-01T00:00:00Z before issuance so issued_on is that
instant and (for term_months=12) expires_on is 2027-06-01.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_activity_category_payload, create_business_payload,
    create_application_payload, create_inspection_payload,
    record_inspection_payload, create_endorsement_payload,
    create_transfer_payload, complete_transfer_payload, unique_code,
)
from .test_users import (
    TEST_USERS, make_applicant_headers,
    make_licensing_officer_headers, make_inspection_officer_headers,
)

OFFICER = TEST_USERS["licensing_officer_headers"]
INSPECTOR = TEST_USERS["inspection_officer_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
# A LicensingOfficer X-User-ID distinct from any inspector, used to issue
# licenses without tripping the segregation-of-duties check (§3.5).
ISSUER = make_licensing_officer_headers("officer-issuer")


# ─── Clock ─────────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the server logical clock (LicensingOfficer only)."""
    return get_success_data(api_client.set_clock(to_iso8601, OFFICER))


# ─── Low-level single-entity creators ──────────────────────────────────────
def make_activity_category(**overrides):
    """Create an ActivityCategory (LicensingOfficer). Returns the dict."""
    return get_success_data(
        api_client.create_activity_category(
            create_activity_category_payload(**overrides), OFFICER)
    )


def make_business(**overrides):
    """Register a Business (Applicant). Returns the dict."""
    return get_success_data(
        api_client.create_business(
            create_business_payload(**overrides), TEST_USERS["applicant_headers"])
    )


def make_draft_application(business_id, category_id, **overrides):
    """Create a DRAFT Application owned by business_id. Returns the dict."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(business_id, category_id, **overrides),
            make_applicant_headers(business_id))
    )


def make_endorsement(license_id, **overrides):
    """Attach an ACTIVE endorsement to a license (LicensingOfficer)."""
    return get_success_data(
        api_client.create_endorsement(
            create_endorsement_payload(license_id, **overrides), OFFICER)
    )


# ─── Inspection helpers ────────────────────────────────────────────────────
def schedule_inspection(application_id, inspector_user_id="insp-1", **overrides):
    """Schedule an inspection (InspectionOfficer). Returns the dict."""
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(application_id, inspector_user_id, **overrides),
            INSPECTOR)
    )


def record_passed_inspection(application_id, inspector_user_id="insp-1",
                             verified_employee_count=1, failed_item_count=0):
    """Schedule + record an inspection PASSED. Returns the recorded Inspection."""
    insp = schedule_inspection(application_id, inspector_user_id)
    return get_success_data(
        api_client.record_inspection(
            insp["id"],
            record_inspection_payload("PASSED", verified_employee_count, failed_item_count),
            INSPECTOR)
    )


# ─── Tier 1/2/3: Application progression → License issuance ────────────────
def setup_submitted_application(category_overrides=None, business_overrides=None,
                                application_overrides=None, clock=DEFAULT_CLOCK):
    """Clock + category + business + DRAFT application, then submit.

    Returns dict: {category, business, application(after submit), biz_headers}.
    The application is SUBMITTED with its provisional estimated_fee computed and
    an unsettled APPLICATION_FEE assessment open.
    """
    if clock:
        set_clock(clock)
    category = make_activity_category(**(category_overrides or {}))
    business = make_business(**(business_overrides or {}))
    biz_headers = make_applicant_headers(business["id"])
    app = make_draft_application(business["id"], category["id"],
                                 **(application_overrides or {}))
    app = get_success_data(api_client.submit_application(app["id"], biz_headers))
    return {
        "category": category,
        "business": business,
        "application": app,
        "biz_headers": biz_headers,
    }


def setup_zoning_cleared_application(category_overrides=None, business_overrides=None,
                                     application_overrides=None, clock=DEFAULT_CLOCK):
    """Submitted application that has cleared its zoning check (ZONING_CLEARED).

    Returns the same dict as setup_submitted_application with the application
    advanced past the zoning check.
    """
    ctx = setup_submitted_application(category_overrides, business_overrides,
                                      application_overrides, clock)
    ctx["application"] = get_success_data(
        api_client.zoning_check_application(ctx["application"]["id"], OFFICER))
    return ctx


def setup_approved_application(category_overrides=None, business_overrides=None,
                               application_overrides=None,
                               passed_inspections=None, clock=DEFAULT_CLOCK):
    """Zoning-cleared application with N passed inspections, then approved.

    passed_inspections: optional list of dicts, each with optional
    inspector_user_id / verified_employee_count / failed_item_count. Defaults to
    enough PASSED inspections to satisfy required_inspection_count.
    Returns the standard ctx dict; ctx["inspections"] holds the recorded list.
    """
    ctx = setup_zoning_cleared_application(category_overrides, business_overrides,
                                           application_overrides, clock)
    app_id = ctx["application"]["id"]
    needed = ctx["category"]["required_inspection_count"]
    specs = passed_inspections if passed_inspections is not None else \
        [{} for _ in range(needed)]
    inspections = []
    for spec in specs:
        inspections.append(record_passed_inspection(
            app_id,
            spec.get("inspector_user_id", "insp-1"),
            spec.get("verified_employee_count", 1),
            spec.get("failed_item_count", 0),
        ))
    ctx["inspections"] = inspections
    ctx["application"] = get_success_data(
        api_client.approve_application(app_id, OFFICER))
    return ctx


def setup_issued_license(category_overrides=None, business_overrides=None,
                         application_overrides=None, passed_inspections=None,
                         clock=DEFAULT_CLOCK, issuer_headers=ISSUER):
    """Full chain through issuance: ACTIVE License from an approved application.

    Returns the standard ctx dict plus ctx["license"]. The issuer header is a
    LicensingOfficer whose id differs from any inspector, so segregation of
    duties passes (§3.5).
    """
    ctx = setup_approved_application(category_overrides, business_overrides,
                                     application_overrides, passed_inspections, clock)
    ctx["license"] = get_success_data(
        api_client.issue_application(ctx["application"]["id"], issuer_headers))
    return ctx


# ─── Tier 4: Delinquency targeting ─────────────────────────────────────────
def setup_delinquent_license(risk_tier="MEDIUM", overdue_clock="2027-08-02T00:00:00Z",
                             category_overrides=None, clock=DEFAULT_CLOCK):
    """Issue an ACTIVE license (term 12, expires 2027-06-01), advance the clock
    past expiry, and assess delinquency so the license is DELINQUENT.

    overdue_clock controls how many days overdue at assessment:
      - 2027-07-01 = 30 days overdue (grace boundary, 0 penalty)
      - 2027-08-01 = 61 days overdue (tier B, 25%)
      - 2027-08-02 = 62 days overdue (tier B)
      - 2027-08-30 = 90 days overdue (revocation boundary, not yet revocable)
      - 2027-09-10 = >90 days overdue (revocable)
    Returns the standard ctx dict with ctx["license"] now DELINQUENT.
    """
    cat_over = {"risk_tier": risk_tier, "required_inspection_count": 0,
                "requires_zoning_check": False, "term_months": 12,
                "allowed_zones": ["C1"]}
    cat_over.update(category_overrides or {})
    ctx = setup_issued_license(category_overrides=cat_over, clock=clock)
    set_clock(overdue_clock)
    ctx["license"] = get_success_data(
        api_client.assess_delinquency(ctx["license"]["id"], OFFICER))
    return ctx


def get_license_fee_assessments(license_id, headers=OFFICER):
    """Fetch the fee-assessment ledger for a license (list helper)."""
    return get_success_data(
        api_client.list_license_fee_assessments(license_id, headers))


def get_application_fee_assessments(application_id, headers=OFFICER):
    """Fetch the fee-assessment ledger for an application (list helper)."""
    return get_success_data(
        api_client.list_application_fee_assessments(application_id, headers))


def settle_all_license_fees(license_id, biz_headers):
    """Settle every outstanding fee assessment on a license. Used to clear the
    outstanding-fee gate before surrender (§3.7) or to pay down before renewal."""
    ledger = get_license_fee_assessments(license_id)
    for fa in ledger:
        if not fa["settled"]:
            get_success_data(api_client.settle_fee_assessment(fa["id"], biz_headers))


# ─── Tier 3: Ownership transfer setups ─────────────────────────────────────
def setup_active_license_with_transfer(risk_tier="MEDIUM", clock=DEFAULT_CLOCK,
                                       category_overrides=None):
    """ACTIVE license held by a seller business with a REQUESTED transfer to a
    GOOD-standing buyer business.

    Returns dict: {category, business(seller), buyer, license, transfer,
    seller_headers, biz_headers (alias of seller_headers)}.
    """
    cat_over = {"risk_tier": risk_tier, "required_inspection_count": 0,
                "requires_zoning_check": False, "term_months": 12,
                "allowed_zones": ["C1"]}
    cat_over.update(category_overrides or {})
    ctx = setup_issued_license(category_overrides=cat_over, clock=clock)
    seller = ctx["business"]
    seller_headers = ctx["biz_headers"]
    buyer = make_business(legal_name="Buyer Co", owner_name="Buyer Owner", zone_code="C1")
    transfer = get_success_data(api_client.create_transfer(
        create_transfer_payload(ctx["license"]["id"], seller["id"], buyer["id"]),
        seller_headers))
    return {
        "category": ctx["category"],
        "business": seller,
        "seller": seller,
        "buyer": buyer,
        "license": ctx["license"],
        "transfer": transfer,
        "seller_headers": seller_headers,
        "biz_headers": seller_headers,
    }


def setup_approved_transfer(risk_tier="MEDIUM", clock=DEFAULT_CLOCK,
                            category_overrides=None):
    """As setup_active_license_with_transfer, but the transfer is APPROVED.

    Returns the same dict with transfer in APPROVED status, plus
    ctx["license_version"] = the license version observed at approval time.
    """
    ctx = setup_active_license_with_transfer(risk_tier, clock, category_overrides)
    ctx["transfer"] = get_success_data(
        api_client.approve_transfer(ctx["transfer"]["id"], OFFICER))
    cur = get_success_data(api_client.get_license(ctx["license"]["id"], OFFICER))
    ctx["license_version"] = cur["version"]
    return ctx
