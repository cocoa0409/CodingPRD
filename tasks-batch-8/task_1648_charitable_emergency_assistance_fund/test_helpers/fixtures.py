"""Composite setup helpers for the emergency-assistance workflows.

The runner restarts the API server before every test, so every helper builds
its preconditions from scratch against PRD-declared endpoints. Setup calls
use get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" message rather than a confusing assertion failure.

Canonical operator identities (PRD §2.8 segregation of duties):
  cw-1  intake caseworker (creates/submits applications, opens checks)
  cw-2  verifying caseworker (opens and completes verifications)
  pm-1  program manager (policy, sources, approve/deny/waitlist, runs, clock)
  fin-1 finance officer (payments)
  aud-1 auditor (reads, reports)
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    complete_verification_payload,
    create_application_payload,
    create_case_note_payload,
    create_document_payload,
    create_duplication_check_payload,
    create_funding_source_payload,
    create_household_payload,
    create_payment_payload,
    create_policy_payload,
    create_vendor_payload,
    deny_application_payload,
    deposit_payload,
    resolve_duplication_check_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS

CW1 = TEST_USERS["caseworker_headers"]
CW2 = TEST_USERS["caseworker2_headers"]
PM1 = TEST_USERS["program_manager_headers"]
FIN1 = TEST_USERS["finance_officer_headers"]
AUD1 = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and singleton resources
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_DEFAULT):
    """Point the server's logical clock at the given instant (PRD §2.4)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), PM1))


def create_active_policy(**overrides):
    """Create an eligibility policy and activate it. Returns the ACTIVE policy."""
    policy = get_success_data(api_client.create_policy(create_policy_payload(**overrides), PM1))
    return get_success_data(api_client.activate_policy(policy["id"], PM1))


def create_vendor(vendor_type="LANDLORD", **overrides):
    """Register a vendor (born ACTIVE). Returns the vendor."""
    return get_success_data(
        api_client.create_vendor(create_vendor_payload(vendor_type=vendor_type, **overrides), CW1)
    )


def create_household(**overrides):
    """Register a household. Returns the household at version 1."""
    return get_success_data(
        api_client.create_household(create_household_payload(**overrides), CW1)
    )


def create_funding_source(**overrides):
    """Create a funding source (born ACTIVE). Returns the source."""
    return get_success_data(
        api_client.create_funding_source(create_funding_source_payload(**overrides), PM1)
    )


def deposit(source_id, amount_cents):
    """Deposit additional budget into a non-CLOSED source. Returns the source."""
    return get_success_data(
        api_client.deposit_funding_source(source_id, deposit_payload(amount_cents), PM1)
    )


def get_source(source_id):
    return get_success_data(api_client.get_funding_source(source_id, PM1))


def get_application(application_id):
    return get_success_data(api_client.get_application(application_id, CW1))


def get_application_version(application_id):
    return get_application(application_id)["version"]


def get_award(award_id):
    return get_success_data(api_client.get_award(award_id, PM1))


def list_award_allocations(award_id):
    """All allocations of an award, ordered by rank_order ascending."""
    resp = api_client.list_allocations(AUD1, params={"award_id": award_id, "limit": 100})
    data = validate_success(resp)
    return sorted(data, key=lambda a: a["rank_order"])


def list_application_awards(application_id):
    resp = api_client.list_awards(AUD1, params={"application_id": application_id, "limit": 100})
    return validate_success(resp)


# ---------------------------------------------------------------------------
# Tier 1: application state progression
# ---------------------------------------------------------------------------

def create_application(household_id, vendor_id, cw_headers=None, **overrides):
    """Open an application (born INTAKE, intake_caseworker_id = caller)."""
    headers = cw_headers or CW1
    return get_success_data(
        api_client.create_application(
            create_application_payload(household_id, vendor_id, **overrides), headers
        )
    )


def attach_document(application_id, doc_type="EVICTION_NOTICE", file_reference=None, cw_headers=None):
    """Attach a supporting document while the application is in INTAKE."""
    headers = cw_headers or CW1
    ref = file_reference or f"s3://docs/{application_id}-{doc_type.lower()}.pdf"
    return get_success_data(
        api_client.attach_document(
            application_id, create_document_payload(doc_type, ref), headers
        )
    )


def submit_application(application_id, cw_headers=None):
    """Submit an INTAKE application; returns the SUBMITTED application."""
    headers = cw_headers or CW1
    return get_success_data(api_client.submit_application(application_id, headers))


def open_duplication_check(application_id, expected_version, agency_name="County HHS", cw_headers=None):
    """Open a duplication-of-benefits check (OCC-guarded). Returns the PENDING check."""
    headers = cw_headers or CW1
    return get_success_data(
        api_client.create_duplication_check(
            application_id,
            create_duplication_check_payload(expected_version, agency_name),
            headers,
        )
    )


def resolve_duplication_check(check_id, result="CLEARED", resolution_notes=None, cw_headers=None):
    """Resolve a PENDING check to CLEARED or FLAGGED."""
    headers = cw_headers or CW1
    return get_success_data(
        api_client.resolve_duplication_check(
            check_id, resolve_duplication_check_payload(result, resolution_notes), headers
        )
    )


def open_cleared_duplication_check(application_id, expected_version, agency_name="County HHS"):
    """Open a check and resolve it CLEARED. Returns the CLEARED check."""
    check = open_duplication_check(application_id, expected_version, agency_name)
    return resolve_duplication_check(check["id"], "CLEARED")


def open_verification(application_id, expected_version, cw_headers=None):
    """Open a vendor verification (OCC-guarded). Returns the PENDING verification.

    The caller must differ from the application's intake_caseworker_id.
    """
    headers = cw_headers or CW2
    return get_success_data(
        api_client.create_verification(
            application_id, {"expected_application_version": expected_version}, headers
        )
    )


def complete_verification(verification_id, outcome, confirmed_amount_cents=None,
                          outcome_notes=None, cw_headers=None):
    """Record the vendor's answer on a PENDING verification."""
    headers = cw_headers or CW2
    return get_success_data(
        api_client.complete_verification(
            verification_id,
            complete_verification_payload(outcome, confirmed_amount_cents, outcome_notes),
            headers,
        )
    )


def pass_verification(application_id, confirmed_amount_cents, cw_headers=None):
    """Open and complete a PASSED verification; drives the application to
    PENDING_DECISION. Reads the application's current version first."""
    version = get_application_version(application_id)
    verification = open_verification(application_id, version, cw_headers)
    return complete_verification(
        verification["id"], "PASSED", confirmed_amount_cents, cw_headers=cw_headers
    )


def approve_application(application_id, pm_headers=None):
    """Approve a PENDING_DECISION application. Returns the APPROVED application."""
    headers = pm_headers or PM1
    return get_success_data(api_client.approve_application(application_id, headers))


def waitlist_application(application_id, pm_headers=None):
    """Move a PENDING_DECISION application to WAITLISTED."""
    headers = pm_headers or PM1
    return get_success_data(api_client.waitlist_application(application_id, headers))


def deny_application(application_id, reason_code="PROGRAM_DIRECTED", pm_headers=None):
    """Deny a PENDING_DECISION or WAITLISTED application."""
    headers = pm_headers or PM1
    return get_success_data(
        api_client.deny_application(
            application_id, deny_application_payload(reason_code), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 2/3: canonical end-to-end chains
# ---------------------------------------------------------------------------

def default_doc_types(category, policy=None):
    """Document types the active policy requires for the category (defaults:
    EVICTION_NOTICE for RENT, UTILITY_BILL for UTILITY)."""
    if policy is None:
        return ["EVICTION_NOTICE"] if category == "RENT" else ["UTILITY_BILL"]
    required = []
    if category == "RENT":
        if policy.get("require_eviction_notice", True):
            required.append("EVICTION_NOTICE")
        if policy.get("require_lease_ledger", False):
            required.append("LEASE_LEDGER")
    elif policy.get("require_utility_bill", True):
        required.append("UTILITY_BILL")
    return required


def drive_application_to_pending_decision(
    household_id,
    vendor_id,
    category="RENT",
    requested_amount_cents=10000,
    service_month="2026-08",
    confirmed_amount_cents=None,
    doc_types=None,
):
    """Walk a fresh application on an existing household+vendor to
    PENDING_DECISION: create, attach required documents, submit, open and
    CLEARED-resolve a duplication check, open and PASS a verification.

    Returns {'application', 'check', 'verification'}.
    """
    application = create_application(
        household_id, vendor_id,
        category=category, requested_amount_cents=requested_amount_cents,
        service_month=service_month,
    )
    for doc_type in (doc_types if doc_types is not None else default_doc_types(category)):
        attach_document(application["id"], doc_type)
    submit_application(application["id"])
    check = open_cleared_duplication_check(
        application["id"], get_application_version(application["id"])
    )
    confirmed = (
        confirmed_amount_cents if confirmed_amount_cents is not None else requested_amount_cents
    )
    verification = pass_verification(application["id"], confirmed)
    return {
        "application": get_application(application["id"]),
        "check": check,
        "verification": verification,
    }


def drive_application_to_approved(household_id, vendor_id, **kwargs):
    """drive_application_to_pending_decision + approve. Returns the pending-
    decision dict plus 'award' and 'allocations' (rank-ordered)."""
    ctx = drive_application_to_pending_decision(household_id, vendor_id, **kwargs)
    approved = approve_application(ctx["application"]["id"])
    ctx["application"] = approved
    ctx["award"] = get_award(approved["active_award_id"])
    ctx["allocations"] = list_award_allocations(ctx["award"]["id"])
    return ctx


def setup_submitted_application(
    category="RENT",
    requested_amount_cents=10000,
    service_month="2026-08",
    policy_overrides=None,
    household_overrides=None,
    vendor_type=None,
    with_source=True,
    source_overrides=None,
    doc_types=None,
    clock=CLOCK_DEFAULT,
):
    """Clock + ACTIVE policy + vendor + household + (optional) source +
    application with the policy-required documents attached + submit.

    Returns a dict with the created records and the submitted application.
    """
    set_clock(clock)
    policy = create_active_policy(**(policy_overrides or {}))
    vtype = vendor_type or ("LANDLORD" if category == "RENT" else "UTILITY")
    vendor = create_vendor(vendor_type=vtype)
    household = create_household(**(household_overrides or {}))
    source = create_funding_source(**(source_overrides or {})) if with_source else None
    application = create_application(
        household["id"], vendor["id"],
        category=category, requested_amount_cents=requested_amount_cents,
        service_month=service_month,
    )
    if doc_types is None:
        doc_types = default_doc_types(category, policy)
    for doc_type in doc_types:
        attach_document(application["id"], doc_type)
    application = submit_application(application["id"])
    return {
        "policy": policy,
        "vendor": vendor,
        "household": household,
        "source": source,
        "application": application,
    }


def setup_pending_decision(
    category="RENT",
    requested_amount_cents=10000,
    confirmed_amount_cents=None,
    service_month="2026-08",
    policy_overrides=None,
    household_overrides=None,
    vendor_type=None,
    source_overrides=None,
    with_source=True,
    with_duplication_check=True,
    resolve_check="CLEARED",
    clock=CLOCK_DEFAULT,
):
    """Full canonical chain to PENDING_DECISION: submit, duplication check
    (resolved per `resolve_check`, left PENDING when resolve_check is None, or
    skipped entirely when with_duplication_check is False), then a PASSED
    verification. Returns the setup dict with 'verification' and 'check'."""
    ctx = setup_submitted_application(
        category=category,
        requested_amount_cents=requested_amount_cents,
        service_month=service_month,
        policy_overrides=policy_overrides,
        household_overrides=household_overrides,
        vendor_type=vendor_type,
        with_source=with_source,
        source_overrides=source_overrides,
        clock=clock,
    )
    app_id = ctx["application"]["id"]
    if with_duplication_check:
        check = open_duplication_check(app_id, get_application_version(app_id))
        if resolve_check is not None:
            check = resolve_duplication_check(check["id"], resolve_check)
        ctx["check"] = check
    else:
        ctx["check"] = None
    confirmed = (
        confirmed_amount_cents if confirmed_amount_cents is not None else requested_amount_cents
    )
    ctx["verification"] = pass_verification(app_id, confirmed)
    ctx["application"] = get_application(app_id)
    return ctx


def setup_approved(
    category="RENT",
    requested_amount_cents=10000,
    confirmed_amount_cents=None,
    service_month="2026-08",
    policy_overrides=None,
    household_overrides=None,
    vendor_type=None,
    source_overrides=None,
    sources=None,
    clock=CLOCK_DEFAULT,
):
    """Full canonical chain to APPROVED with an ACTIVE award and RESERVED
    allocations. `sources` may be a list of funding-source payload overrides
    to pre-create several sources (the first is created before the
    application; the rest follow, preserving creation order).

    Returns the setup dict plus 'award' (the created award record),
    'allocations' (rank-ordered), and 'sources' (list of sources)."""
    if sources:
        first, rest = sources[0], sources[1:]
    else:
        first, rest = (source_overrides or {}), []
    ctx = setup_pending_decision(
        category=category,
        requested_amount_cents=requested_amount_cents,
        confirmed_amount_cents=confirmed_amount_cents,
        service_month=service_month,
        policy_overrides=policy_overrides,
        household_overrides=household_overrides,
        vendor_type=vendor_type,
        source_overrides=first,
        clock=clock,
    )
    ctx["sources"] = [ctx["source"]] + [create_funding_source(**s) for s in rest]
    approved = approve_application(ctx["application"]["id"])
    ctx["application"] = approved
    ctx["award"] = get_award(approved["active_award_id"])
    ctx["allocations"] = list_award_allocations(ctx["award"]["id"])
    return ctx


def setup_paid(
    requested_amount_cents=10000,
    payment_date="2026-08-02T00:00:00Z",
    **kwargs,
):
    """Full chain through PAID: approve, issue one payment for the full award
    against the (single) source, clear it. Returns ctx plus 'payment'."""
    ctx = setup_approved(requested_amount_cents=requested_amount_cents, **kwargs)
    payment = get_success_data(
        api_client.create_payment(
            ctx["award"]["id"],
            create_payment_payload(
                ctx["vendor"]["id"], ctx["source"]["id"], requested_amount_cents,
                payment_date=payment_date,
            ),
            FIN1,
        )
    )
    ctx["payment"] = get_success_data(api_client.clear_payment(payment["id"], FIN1))
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def issue_payment(award_id, vendor_id, funding_source_id, amount_cents,
                  payment_date="2026-08-02T00:00:00Z", fin_headers=None):
    """Issue a direct-to-vendor payment against a RESERVED allocation."""
    headers = fin_headers or FIN1
    return get_success_data(
        api_client.create_payment(
            award_id,
            create_payment_payload(
                vendor_id, funding_source_id, amount_cents, payment_date=payment_date
            ),
            headers,
        )
    )


def clear_payment(payment_id, fin_headers=None):
    headers = fin_headers or FIN1
    return get_success_data(api_client.clear_payment(payment_id, headers))


def append_follow_up_note(application_id, body="family stable after payment",
                          outcome="CRISIS_RESOLVED", cw_headers=None):
    """Append a FOLLOW_UP case note with its mandatory outcome."""
    headers = cw_headers or CW1
    return get_success_data(
        api_client.create_case_note(
            application_id,
            create_case_note_payload("FOLLOW_UP", body, outcome=outcome),
            headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 4/5: waitlist + replenishment helpers
# ---------------------------------------------------------------------------

def build_pending_decision_on_existing_vendor(
    vendor_id,
    requested_amount_cents=10000,
    confirmed_amount_cents=None,
    household_overrides=None,
    service_month="2026-08",
    category="RENT",
    clock=None,
):
    """Build a PENDING_DECISION application on an EXISTING vendor, reusing the
    already-ACTIVE policy and existing sources (no new policy or source is
    created). A fresh household is registered per call. When `clock` is given,
    the logical clock is moved there first so waitlisted_at ordering across
    candidates is explicit.

    Returns a dict with household/application/check/verification and vendor_id.
    """
    if clock is not None:
        set_clock(clock)
    household = create_household(**(household_overrides or {}))
    ctx = drive_application_to_pending_decision(
        household["id"], vendor_id,
        category=category,
        requested_amount_cents=requested_amount_cents,
        service_month=service_month,
        confirmed_amount_cents=confirmed_amount_cents,
    )
    ctx["household"] = household
    ctx["vendor_id"] = vendor_id
    return ctx


def run_replenishment(pm_headers=None):
    """Launch a replenishment run. Returns the persisted ReplenishmentRun."""
    headers = pm_headers or PM1
    return get_success_data(api_client.create_replenishment_run(headers))
