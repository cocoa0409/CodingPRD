"""
Composite setup helpers for multi-step test prerequisites.

Each fixture builds preconditions from an EMPTY database — the harness restarts
the API server (via start.sh) before every individual pytest test, so nothing
carries over between tests. All setup helpers use get_success_data() (lenient
validator) so setup-step failures surface as clear 'setup failed' messages.

Identity threading: PRD §2.1 declares Applicant and Cardholder as
entity_backed:Household. Whenever a fixture creates a Household and then makes
an ownership-gated call as Applicant or Cardholder against that household, it
MUST pass make_applicant_headers(household["id"]) or
make_cardholder_headers(household["id"]) — never the shared TEST_USERS
fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_household_payload,
    create_household_member_payload,
    create_application_payload,
    create_monthly_allotment_payload,
    create_eligible_item_category_payload,
    create_purchase_transaction_payload,
    create_fraud_flag_payload,
    create_abawd_waiver_payload,
    create_emergency_allotment_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_cardholder_headers,
)


# Convenience header aliases used throughout
CW = TEST_USERS["caseworker_headers"]
BI = TEST_USERS["benefit_issuer_headers"]
INV = TEST_USERS["fraud_investigator_headers"]
INV_B = TEST_USERS["fraud_investigator_b_headers"]
MER = TEST_USERS["merchant_headers"]
PA = TEST_USERS["policy_admin_headers"]


# ─── Tier 0: Clock primitive ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server's logical clock (PRD §3.10).
    PolicyAdmin is the only role permitted on POST /snap/_clock/set_current_utc."""
    return get_success_data(api_client.set_current_utc(to_iso8601, PA))


# ─── Tier 1: Single-entity primitives ───────────────────────────────────

def create_household(case_number, state_code="CA", address_line="1 Test St",
                     heap_recipient=None):
    """Create a Household in PENDING (PRD §3.1). Returns the Household dict."""
    return get_success_data(api_client.create_household(
        create_household_payload(
            case_number=case_number,
            state_code=state_code,
            address_line=address_line,
            heap_recipient=heap_recipient,
        ),
        CW,
    ))


def add_member(household_id, full_name="Member", date_of_birth="1980-01-01",
               relationship="HEAD", monthly_earned_income_cents=None,
               monthly_unearned_income_cents=None, disabled=None):
    """Add an ACTIVE HouseholdMember (PRD §3.1)."""
    return get_success_data(api_client.create_household_member(
        create_household_member_payload(
            household_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
            relationship=relationship,
            monthly_earned_income_cents=monthly_earned_income_cents,
            monthly_unearned_income_cents=monthly_unearned_income_cents,
            disabled=disabled,
        ),
        CW,
    ))


def create_eligible_category(code, name=None, eligible=True):
    """Create an EligibleItemCategory (PRD §3.8)."""
    return get_success_data(api_client.create_eligible_item_category(
        create_eligible_item_category_payload(code, name=name, eligible=eligible),
        PA,
    ))


# ─── Tier 2: Application workflow helpers ───────────────────────────────

def create_and_submit_application(household_id):
    """Create an Application in DRAFT, then submit it (PRD §3.2).
    Returns the SUBMITTED Application dict."""
    app = get_success_data(api_client.create_application(
        create_application_payload(household_id), CW,
    ))
    return get_success_data(api_client.submit_application(app["id"], CW))


def approve_application(app_id, decision_reason="Eligible per net income"):
    """Approve a SUBMITTED application (PRD §3.2). Returns APPROVED Application."""
    return get_success_data(api_client.approve_application(
        app_id, {"decision_reason": decision_reason}, CW,
    ))


# ─── Tier 3: Household-state progression to ACTIVE ──────────────────────

def setup_household_certified_active(case_number, state_code="CA",
                                     address_line="1 Main St",
                                     heap_recipient=None,
                                     member_overrides=None,
                                     clock_iso="2026-06-01T00:00:00Z",
                                     decision_reason="Eligible per net income"):
    """
    Full preamble: set clock → create PENDING Household with one ACTIVE
    HEAD member (disabled=true by default so ABAWD is bypassed) → create
    application → submit → approve. Household ends up in ACTIVE (PRD §3.2
    CERTIFIED→ACTIVE auto-advance).

    Returns (household, application). The household is the post-approve
    state (status='ACTIVE', certification_end_date set).
    """
    set_clock(clock_iso)
    hh = create_household(case_number=case_number, state_code=state_code,
                          address_line=address_line, heap_recipient=heap_recipient)
    member_kwargs = {
        "full_name": "Head Member",
        "date_of_birth": "1970-01-01",
        "relationship": "HEAD",
        "disabled": True,
    }
    if member_overrides:
        member_kwargs.update(member_overrides)
    add_member(hh["id"], **member_kwargs)
    app = create_and_submit_application(hh["id"])
    approved_app = approve_application(app["id"], decision_reason=decision_reason)
    # Re-fetch household to see the post-approve state.
    hh_after = get_success_data(api_client.get_household(hh["id"], CW))
    return hh_after, approved_app


def get_first_card_for_household(household_id):
    """List EBTCards for a household and return the first one (PRD §3.2:
    the approval cascade creates an EBTCard with status=PENDING_ISSUE)."""
    resp = api_client.list_ebt_cards(CW, params={"household_id": household_id})
    body = get_success_data(resp)
    # body is the list payload — validate_success returns the data list directly.
    assert isinstance(body, list) and len(body) >= 1, \
        f"Setup failed: expected at least 1 EBTCard for household, got {body!r}"
    return body[0]


def activate_first_card(household_id):
    """Locate the household's PENDING_ISSUE card and activate it (PRD §3.6).
    Returns the ACTIVE card dict."""
    card = get_first_card_for_household(household_id)
    return get_success_data(api_client.activate_ebt_card(card["id"], CW))


def setup_household_with_active_card(case_number, state_code="CA",
                                     address_line="1 Main St",
                                     heap_recipient=None,
                                     member_overrides=None,
                                     clock_iso="2026-06-01T00:00:00Z",
                                     decision_reason="Eligible per net income"):
    """
    Full preamble through to an ACTIVE Household with an ACTIVE EBTCard.

    Returns (household, application, card).
    """
    hh, app = setup_household_certified_active(
        case_number=case_number, state_code=state_code,
        address_line=address_line, heap_recipient=heap_recipient,
        member_overrides=member_overrides, clock_iso=clock_iso,
        decision_reason=decision_reason,
    )
    card = activate_first_card(hh["id"])
    return hh, app, card


# ─── Tier 4: Fraud-flag composite helpers ───────────────────────────────

def create_open_fraud_flag(household_id, trigger_rule="VELOCITY_SPIKE"):
    """Manually raise a FraudFlag (PRD §3.9 manual referral path).
    Returns the OPEN FraudFlag dict."""
    return get_success_data(api_client.create_fraud_flag(
        create_fraud_flag_payload(household_id, trigger_rule=trigger_rule),
        INV,
    ))


def claim_fraud_flag(ff_id):
    """Claim an OPEN FraudFlag, advancing it to UNDER_REVIEW (PRD §3.9).
    Returns the UNDER_REVIEW FraudFlag dict."""
    return get_success_data(api_client.claim_fraud_flag(ff_id, INV))


def substantiate_fraud_flag(ff_id, expected_version,
                            resolution_note="Confirmed"):
    """Substantiate an UNDER_REVIEW flag (PRD §3.9 + PRD §2.5 OCC).
    Returns the SUBSTANTIATED FraudFlag dict."""
    return get_success_data(api_client.substantiate_fraud_flag(
        ff_id,
        {"resolution_note": resolution_note,
         "expected_fraudflag_version": expected_version},
        INV,
    ))


def setup_substantiated_fraud_flag(household_id, trigger_rule="VELOCITY_SPIKE",
                                   resolution_note="Confirmed"):
    """Create → claim → substantiate a FraudFlag against the household
    (PRD §3.9 full lifecycle). Returns the SUBSTANTIATED FraudFlag dict."""
    ff = create_open_fraud_flag(household_id, trigger_rule=trigger_rule)
    claimed = claim_fraud_flag(ff["id"])
    return substantiate_fraud_flag(
        ff["id"], claimed["version"], resolution_note=resolution_note)


# ─── Tier 5: Household-with-fraud-then-suspend helper ───────────────────

def setup_household_active_with_substantiated_flag(
        case_number, state_code="CA", clock_iso="2026-08-01T00:00:00Z"):
    """Household in ACTIVE with one substantiated FraudFlag.
    Returns (household, card, fraud_flag). The flag is the precondition for
    /suspend (PRD §3.7)."""
    hh, _app, card = setup_household_with_active_card(
        case_number=case_number, state_code=state_code, clock_iso=clock_iso,
    )
    ff = setup_substantiated_fraud_flag(hh["id"])
    # Refresh hh — its version has advanced through the fraud cascade nothing,
    # but caller may want the latest.
    hh_after = get_success_data(api_client.get_household(hh["id"], CW))
    return hh_after, card, ff


# ─── Tier 6: Purchase-transaction helpers ───────────────────────────────

def create_purchase(card_id, line_items, merchant_id="M001"):
    """Create a PurchaseTransaction in AUTHORIZED (PRD §3.8)."""
    return get_success_data(api_client.create_purchase_transaction(
        create_purchase_transaction_payload(
            card_id, merchant_id=merchant_id, line_items=line_items),
        MER,
    ))


def settle_purchase(tx_id):
    """Settle an AUTHORIZED PurchaseTransaction (PRD §3.8). Returns SETTLED dict."""
    return get_success_data(api_client.settle_purchase_transaction(tx_id, MER))


def create_and_settle_purchase(card_id, amount_cents, category_code="FRESH_PRODUCE",
                               merchant_id="M001"):
    """Create + settle one purchase. Returns the SETTLED PurchaseTransaction dict."""
    tx = create_purchase(
        card_id,
        line_items=[{"category_code": category_code,
                     "amount_cents": amount_cents, "quantity": 1}],
        merchant_id=merchant_id,
    )
    return settle_purchase(tx["id"])


# ─── Tier 7: MonthlyAllotment helpers ───────────────────────────────────

def create_monthly_allotment(household_id, benefit_month):
    """Create a DRAFT MonthlyAllotment (PRD §3.5)."""
    return get_success_data(api_client.create_monthly_allotment(
        create_monthly_allotment_payload(household_id, benefit_month), BI,
    ))


def issue_monthly_allotment(ma_id, expected_household_version):
    """Issue a DRAFT MonthlyAllotment (PRD §3.5 + PRD §2.5 OCC)."""
    return get_success_data(api_client.issue_monthly_allotment(
        ma_id,
        {"expected_household_version": expected_household_version},
        BI,
    ))


def adjust_monthly_allotment(ma_id):
    """Adjust an ISSUED MonthlyAllotment (PRD §3.5)."""
    return get_success_data(api_client.adjust_monthly_allotment(ma_id, BI))


def current_household_version(household_id):
    """Read the live Household.version for OCC pinning."""
    hh = get_success_data(api_client.get_household(household_id, BI))
    return hh["version"]


# ─── Tier 8: EmergencyAllotmentProclamation helpers ─────────────────────

def create_proclamation(state_code, benefit_month, min_supplement_cents=None):
    """Create a DRAFT EmergencyAllotmentProclamation (PRD §3.10)."""
    return get_success_data(api_client.create_emergency_allotment(
        create_emergency_allotment_payload(
            state_code, benefit_month,
            min_supplement_cents=min_supplement_cents),
        PA,
    ))


def activate_proclamation(p_id):
    """Activate a DRAFT proclamation (PRD §3.10). Returns ACTIVE proclamation."""
    return get_success_data(api_client.activate_emergency_allotment(p_id, PA))


def setup_active_proclamation(state_code, benefit_month,
                              min_supplement_cents=None):
    """Create + activate a proclamation. Returns the ACTIVE dict."""
    p = create_proclamation(state_code, benefit_month,
                            min_supplement_cents=min_supplement_cents)
    return activate_proclamation(p["id"])


# ─── Tier 9: ABAWD-waiver helpers ───────────────────────────────────────

def create_abawd_waiver(household_member_id, quarter="2026-Q3",
                        county_unemployment_pct=10.00, monthly_work_hours=0):
    """Create a PENDING ABAWDWaiver (PRD §3.3)."""
    return get_success_data(api_client.create_abawd_waiver(
        create_abawd_waiver_payload(
            household_member_id, quarter=quarter,
            county_unemployment_pct=county_unemployment_pct,
            monthly_work_hours=monthly_work_hours),
        CW,
    ))
