"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the API server (via start.sh) before every individual
pytest test, so every fixture builds preconditions from an EMPTY database.
All setup helpers use get_success_data() (lenient validator) so setup-step
failures surface as clear "setup failed" messages.

Identity threading (PRD §2.1): Applicant is entity_backed:Applicant. After
a fixture creates an Applicant, every ownership-gated Applicant-role call
that follows uses make_applicant_headers(applicant["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_office_action_payload,
    create_office_action_response_payload,
    create_fee_payment_payload,
    create_pct_phase_entry_payload,
    create_pay_issue_fee_payload,
)
from .test_users import TEST_USERS, make_applicant_headers
from .constants import (
    filing_fee_cents,
    issue_fee_cents,
    extension_fee_cents,
    maintenance_base_fee_cents,
    maintenance_late_surcharge_cents,
)


# Convenience header aliases
EXAMINER = TEST_USERS["examiner_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 0: Clock primitive (PRD §3.11) ────────────────────────────────

def set_clock(to_iso8601: str):
    """Pin the server's logical clock (PRD §3.11). Only USPTOAdmin may call."""
    return get_success_data(api_client.set_current_utc(to_iso8601, ADMIN))


def run_sweep():
    """Synchronously run the deadline sweeper (PRD §3.11). Only USPTOAdmin."""
    return get_success_data(api_client.sweep_deadlines(ADMIN))


# ─── Tier 1: Applicant primitives (PRD §3.1) ────────────────────────────

def create_applicant(legal_name="Test Applicant", entity_size="LARGE",
                     prior_applications_filed=0,
                     micro_qualifying_year=None,
                     gross_income_prior_year_cents=None):
    """Create an Applicant (PRD §3.1). Created by USPTOAdmin (PRD §4 RBAC)."""
    return get_success_data(api_client.create_applicant(
        create_applicant_payload(
            legal_name=legal_name,
            entity_size=entity_size,
            prior_applications_filed=prior_applications_filed,
            micro_qualifying_year=micro_qualifying_year,
            gross_income_prior_year_cents=gross_income_prior_year_cents,
        ),
        ADMIN,
    ))


# ─── Tier 1: Application primitives (PRD §3.2) ──────────────────────────

def create_application(applicant, application_type="UTILITY",
                       title="Test invention", claim_count=10,
                       independent_claim_count=2,
                       parent_application_id=None, continuation_type=None):
    """File an Application (PRD §3.2). Threads applicant identity correctly."""
    headers = make_applicant_headers(applicant["id"])
    return get_success_data(api_client.create_application(
        create_application_payload(
            applicant_id=applicant["id"],
            application_type=application_type,
            title=title,
            claim_count=claim_count,
            independent_claim_count=independent_claim_count,
            parent_application_id=parent_application_id,
            continuation_type=continuation_type,
        ),
        headers,
    ))


def pay_filing_fee(applicant, application):
    """Post the FILING fee for `application` (PRD §3.3) at the exact expected amount."""
    expected = filing_fee_cents(application["application_type"], applicant["entity_size"])
    return get_success_data(api_client.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="FILING",
            amount_cents=expected,
        ),
        make_applicant_headers(applicant["id"]),
    ))


def docket_application(application_id):
    """Examiner dockets a FILED application (PRD §3.4). USPTOExaminer only."""
    return get_success_data(api_client.docket_application(application_id, EXAMINER))


def issue_office_action(application_id, action_type="NON_FINAL"):
    """Examiner issues an OfficeAction (PRD §3.4). Returns the OA dict."""
    return get_success_data(api_client.create_office_action(
        create_office_action_payload(application_id=application_id,
                                     action_type=action_type),
        EXAMINER,
    ))


def file_oa_response(applicant, office_action_id, extension_months_requested=0,
                     claim_amendment_count=10):
    """Applicant files an OfficeActionResponse (PRD §3.5)."""
    return get_success_data(api_client.create_office_action_response(
        create_office_action_response_payload(
            office_action_id=office_action_id,
            extension_months_requested=extension_months_requested,
            claim_amendment_count=claim_amendment_count,
        ),
        make_applicant_headers(applicant["id"]),
    ))


def get_application(application_id, applicant=None):
    """Read an application via GET. Uses Applicant identity if supplied,
    otherwise USPTOAdmin (which can read per PRD §4)."""
    headers = make_applicant_headers(applicant["id"]) if applicant else ADMIN
    return get_success_data(api_client.get_application(application_id, headers))


def pay_issue_fee(applicant, application):
    """Pay the issue fee at the exact expected amount and current version (PRD §3.7).
    Returns the post-issuance Application dict."""
    # Read live version (PRD §2.8: expected_application_version must equal current).
    app_now = get_application(application["id"], applicant)
    expected_amount = issue_fee_cents(application["application_type"],
                                      applicant["entity_size"])
    return get_success_data(api_client.pay_issue_fee(
        application["id"],
        create_pay_issue_fee_payload(
            amount_cents=expected_amount,
            expected_application_version=app_now["version"],
        ),
        make_applicant_headers(applicant["id"]),
    ))


def list_maintenance_fees(application_id, applicant):
    """List MaintenanceFees for an application (sorted by created_at asc per PRD §2.3)."""
    res = api_client.list_maintenance_fees(
        make_applicant_headers(applicant["id"]),
        params={"application_id": application_id},
    )
    return get_success_data(res)


# ─── Tier 2: State-progression composites ───────────────────────────────

def setup_applicant_and_application(entity_size="LARGE",
                                    application_type="UTILITY",
                                    legal_name=None,
                                    title=None,
                                    claim_count=10,
                                    independent_claim_count=2,
                                    micro_qualifying_year=None,
                                    gross_income_prior_year_cents=None,
                                    prior_applications_filed=0):
    """Create applicant + freshly-filed application in FILED state.
    Returns (applicant, application)."""
    applicant = create_applicant(
        legal_name=legal_name or f"{entity_size} Test Co",
        entity_size=entity_size,
        prior_applications_filed=prior_applications_filed,
        micro_qualifying_year=micro_qualifying_year,
        gross_income_prior_year_cents=gross_income_prior_year_cents,
    )
    application = create_application(
        applicant,
        application_type=application_type,
        title=title or f"{application_type} test invention",
        claim_count=claim_count,
        independent_claim_count=independent_claim_count,
    )
    return applicant, application


def setup_application_in_awaiting_examination(entity_size="LARGE",
                                              application_type="UTILITY",
                                              claim_count=10,
                                              independent_claim_count=2):
    """Applicant + Application paid + docketed → AWAITING_EXAMINATION.
    Returns (applicant, application)."""
    applicant, application = setup_applicant_and_application(
        entity_size=entity_size, application_type=application_type,
        claim_count=claim_count, independent_claim_count=independent_claim_count,
    )
    pay_filing_fee(applicant, application)
    docketed = docket_application(application["id"])
    return applicant, docketed


def setup_application_with_outstanding_oa(entity_size="LARGE",
                                          action_type="NON_FINAL",
                                          application_type="UTILITY",
                                          claim_count=10,
                                          independent_claim_count=2):
    """Applicant + Application docketed + one OUTSTANDING OA of the requested type.
    Returns (applicant, application, office_action)."""
    applicant, application = setup_application_in_awaiting_examination(
        entity_size=entity_size, application_type=application_type,
        claim_count=claim_count, independent_claim_count=independent_claim_count,
    )
    oa = issue_office_action(application["id"], action_type=action_type)
    return applicant, application, oa


def setup_application_in_allowed(entity_size="LARGE",
                                 application_type="UTILITY",
                                 claim_count=10,
                                 independent_claim_count=2):
    """Walk to ALLOWED via NOTICE_OF_ALLOWANCE directly from AWAITING_EXAMINATION
    (PRD §3.4 alternate happy path). Returns (applicant, application)."""
    applicant, application = setup_application_in_awaiting_examination(
        entity_size=entity_size, application_type=application_type,
        claim_count=claim_count, independent_claim_count=independent_claim_count,
    )
    issue_office_action(application["id"], action_type="NOTICE_OF_ALLOWANCE")
    return applicant, get_application(application["id"], applicant)


def setup_application_in_issued(entity_size="LARGE",
                                application_type="UTILITY"):
    """Walk fully to ISSUED. Returns (applicant, application_after_issue)."""
    applicant, application = setup_application_in_allowed(
        entity_size=entity_size, application_type=application_type,
    )
    issued = pay_issue_fee(applicant, application)
    return applicant, issued


def setup_utility_with_maintenance_fees(entity_size="LARGE"):
    """ISSUED UTILITY (which auto-generates W1/W2/W3 per PRD §3.7).
    Returns (applicant, application, [W1, W2, W3] sorted by window_number).
    """
    applicant, issued = setup_application_in_issued(
        entity_size=entity_size, application_type="UTILITY",
    )
    fees = list_maintenance_fees(issued["id"], applicant)
    fees_by_window = sorted(fees, key=lambda f: f["window_number"])
    return applicant, issued, fees_by_window


# ─── Tier 3: Provisional & continuation lifecycle composites ────────────

def setup_provisional_filed(entity_size="LARGE", title="Provisional widget"):
    """Provisional Application in FILED. Returns (applicant, application)."""
    return setup_applicant_and_application(
        entity_size=entity_size,
        application_type="PROVISIONAL",
        title=title,
    )


def setup_parent_application_in_filed(entity_size="LARGE"):
    """LARGE UTILITY parent application in FILED — suitable for continuation/CIP
    children whose parent must be living (PRD §3.2). Returns (applicant, parent)."""
    return setup_applicant_and_application(
        entity_size=entity_size, application_type="UTILITY",
        title="Parent invention",
    )


def setup_parent_application_abandoned():
    """LARGE UTILITY parent in ABANDONED via deadline sweep cascade (PRD §3.6).
    Returns (applicant, parent_after_sweep). Caller is responsible for setting
    the clock back to the desired point after this returns."""
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, _oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    set_clock("2026-08-01T00:00:00.000Z")  # past max_due (issue+6mo)
    run_sweep()
    return applicant, get_application(application["id"], applicant)


# ─── Tier 4: Maintenance-window targeting composites ────────────────────

def setup_utility_at_w1_due_date(entity_size="LARGE", issue_clock="2020-01-01T00:00:00.000Z",
                                 w1_due_clock="2024-01-01T00:00:00.000Z"):
    """Issued UTILITY at issue_clock (so W1 due = issue + 4 years); then clock
    set to w1_due_clock for an on-time payment. Returns (applicant, application,
    fees_sorted_by_window)."""
    set_clock(issue_clock)
    applicant, issued, fees = setup_utility_with_maintenance_fees(entity_size=entity_size)
    set_clock(w1_due_clock)
    return applicant, issued, fees


def pay_maintenance(applicant, application_id, fee_id, payment_category,
                    amount_cents):
    """Post a MAINTENANCE_W* fee payment at the supplied amount."""
    return get_success_data(api_client.create_fee_payment(
        create_fee_payment_payload(
            application_id=application_id,
            payment_category=payment_category,
            amount_cents=amount_cents,
            maintenance_fee_id=fee_id,
        ),
        make_applicant_headers(applicant["id"]),
    ))


# ─── Tier 5: PCT national-phase composites ──────────────────────────────

def setup_pct_application_with_entry(entity_size="LARGE",
                                     pct_international_filing_date="2024-01-01T00:00:00.000Z"):
    """PCT_NATIONAL Application with one PCTPhaseEntry already ENTERED.
    Returns (applicant, application, pct_entry)."""
    applicant, application = setup_applicant_and_application(
        entity_size=entity_size, application_type="PCT_NATIONAL",
        title="PCT widget",
    )
    entry = get_success_data(api_client.create_pct_phase_entry(
        create_pct_phase_entry_payload(
            application_id=application["id"],
            pct_international_filing_date=pct_international_filing_date,
        ),
        make_applicant_headers(applicant["id"]),
    ))
    return applicant, application, entry


# ─── Tier 6: Multi-OA cycle composites (for conservation/branching tests) ─

def setup_multi_oa_cycle(num_responded=2, final_outstanding=True,
                         entity_size="LARGE"):
    """Build an Application with `num_responded` RESPONDED OAs (each issued
    then responded in sequence) plus, when final_outstanding=True, one
    additional OUTSTANDING NON_FINAL OA. Returns
    (applicant, application, [responded_oas...], outstanding_oa_or_None).

    Each cycle (issue NON_FINAL → response with 0 extension) advances the
    Application status OFFICE_ACTION_OUTSTANDING → RESPONSE_FILED, then back
    to OFFICE_ACTION_OUTSTANDING on the next issuance (PRD §3.6 cycle).
    """
    applicant, application = setup_application_in_awaiting_examination(
        entity_size=entity_size, application_type="UTILITY",
    )
    responded = []
    for _ in range(num_responded):
        oa = issue_office_action(application["id"], action_type="NON_FINAL")
        file_oa_response(applicant, oa["id"],
                         extension_months_requested=0, claim_amendment_count=10)
        responded.append(oa)
    outstanding = None
    if final_outstanding:
        outstanding = issue_office_action(application["id"], action_type="NON_FINAL")
    return applicant, application, responded, outstanding
