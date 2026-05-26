"""Composite setup helpers for multi-step preconditions.

Each test in test_suite starts against an empty database (per-test-server
isolation). Every fixture here builds preconditions from scratch using only
PRD-declared endpoints, with the server clock pinned at the start so that
validity-window, daily-topup-window, and reimbursement-period behaviors are
deterministic.

Fixtures use `get_success_data` (lenient validator) internally so a setup
failure surfaces as a clear "Setup failed" message rather than a confusing
assertion failure inside a test body.
"""
from typing import Optional, List, Tuple, Dict, Any
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_household_payload,
    create_student_payload,
    create_allergy_profile_payload,
    create_meal_application_payload,
    create_eligibility_determination_payload,
    create_menu_item_payload,
    create_topup_payload,
    create_service_transaction_payload,
    create_reimbursement_claim_payload,
    create_approve_payload,
    create_deny_payload,
    create_appeal_payload,
    create_reject_tx_payload,
    create_refund_tx_payload,
    create_resolve_dispute_payload,
    create_revoke_determination_payload,
)
from .test_users import TEST_USERS, make_parent_headers
from .constants import DEFAULT_CLOCK_ISO


# ---------------------------------------------------------------------
# Low-level helpers (one-call wrappers)
# ---------------------------------------------------------------------

def set_clock(iso8601: str = DEFAULT_CLOCK_ISO) -> None:
    """Pin the server clock to the given ISO 8601 UTC instant (PRD §2.7)."""
    res = api_client.set_clock(iso8601, TEST_USERS["platform_admin_headers"])
    if not (200 <= res.status_code < 300):
        raise AssertionError(
            f"Setup failed: could not set clock to {iso8601}: "
            f"HTTP {res.status_code}: {res.text}"
        )


def advance_clock_and_expire(iso8601: str) -> dict:
    """Advance the server clock and run the expiry sweep (PRD §3.8)."""
    return get_success_data(
        api_client.advance_and_expire(iso8601, TEST_USERS["platform_admin_headers"])
    )


def create_household(**overrides) -> dict:
    return get_success_data(
        api_client.create_household(
            create_household_payload(**overrides),
            TEST_USERS["school_staff_headers"],
        )
    )


def create_student(household_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_student(
            create_student_payload(household_id, **overrides),
            TEST_USERS["school_staff_headers"],
        )
    )


def create_allergy_profile(
    student_id: str,
    allergens: Optional[List[str]] = None,
    severity: Optional[str] = None,
) -> dict:
    payload = create_allergy_profile_payload(student_id)
    if allergens is not None:
        payload["allergens"] = allergens
    if severity is not None:
        payload["severity"] = severity
    return get_success_data(
        api_client.create_allergy_profile(
            payload, TEST_USERS["school_staff_headers"]
        )
    )


def update_allergy_profile(
    profile_id: str,
    allergens: Optional[List[str]] = None,
    severity: Optional[str] = None,
) -> dict:
    payload: Dict[str, Any] = {}
    if allergens is not None:
        payload["allergens"] = allergens
    if severity is not None:
        payload["severity"] = severity
    return get_success_data(
        api_client.update_allergy_profile(
            profile_id, payload, TEST_USERS["school_staff_headers"]
        )
    )


def create_direct_cert_eligibility(
    household_id: str,
    tier: str = "FREE",
    valid_from_utc: str = "2026-01-01T00:00:00.000Z",
    valid_to_utc: str = "2026-08-31T23:59:59.000Z",
) -> dict:
    """Create a DIRECT_CERTIFICATION-sourced determination directly via the
    operator endpoint (PRD §3.4). Useful when a test needs an ACTIVE
    eligibility without walking the application path.
    """
    return get_success_data(
        api_client.create_eligibility_determination(
            create_eligibility_determination_payload(
                household_id,
                source="DIRECT_CERTIFICATION",
                tier=tier,
                valid_from_utc=valid_from_utc,
                valid_to_utc=valid_to_utc,
            ),
            TEST_USERS["school_staff_headers"],
        )
    )


def create_eligibility_determination(
    household_id: str,
    source: str,
    tier: str,
    valid_from_utc: str,
    valid_to_utc: str,
) -> dict:
    return get_success_data(
        api_client.create_eligibility_determination(
            create_eligibility_determination_payload(
                household_id,
                source=source,
                tier=tier,
                valid_from_utc=valid_from_utc,
                valid_to_utc=valid_to_utc,
            ),
            TEST_USERS["school_staff_headers"],
        )
    )


def create_menu_item(**overrides) -> dict:
    return get_success_data(
        api_client.create_menu_item(
            create_menu_item_payload(**overrides),
            TEST_USERS["school_staff_headers"],
        )
    )


def create_application(household_id: str, school_year: str = "2025-2026") -> dict:
    """Create a MealApplication in DRAFT. Uses Parent headers with X-User-ID
    == household_id, satisfying the ownership rule on later submit/withdraw/
    appeal calls."""
    return get_success_data(
        api_client.create_application(
            create_meal_application_payload(household_id, school_year=school_year),
            make_parent_headers(household_id),
        )
    )


def submit_application(application_id: str, household_id: str) -> dict:
    return get_success_data(
        api_client.submit_application(
            application_id, make_parent_headers(household_id)
        )
    )


def start_review(application_id: str) -> dict:
    return get_success_data(
        api_client.start_review_application(
            application_id, TEST_USERS["district_reviewer_headers"]
        )
    )


def approve_application(application_id: str, decision_reason: str = "verified") -> dict:
    return get_success_data(
        api_client.approve_application(
            application_id,
            create_approve_payload(decision_reason),
            TEST_USERS["district_reviewer_headers"],
        )
    )


def deny_application(application_id: str, decision_reason: str = "denied") -> dict:
    return get_success_data(
        api_client.deny_application(
            application_id,
            create_deny_payload(decision_reason),
            TEST_USERS["district_reviewer_headers"],
        )
    )


def appeal_application(
    application_id: str,
    household_id: str,
    appeal_reason: str,
    expected_mealapplication_version: int,
) -> dict:
    return get_success_data(
        api_client.appeal_application(
            application_id,
            create_appeal_payload(appeal_reason, expected_mealapplication_version),
            make_parent_headers(household_id),
        )
    )


def get_application(application_id: str) -> dict:
    return get_success_data(
        api_client.get_application(
            application_id, TEST_USERS["district_reviewer_headers"]
        )
    )


def get_service_transaction(tx_id: str) -> dict:
    return get_success_data(
        api_client.get_service_transaction(
            tx_id, TEST_USERS["school_staff_headers"]
        )
    )


def resolve_parent_account_id(household_id: str) -> str:
    """Resolve the ParentAccount.id for a household by reading the nested
    `/households/{id}/parent-account` collection (PRD §2.8: zero-or-one list).
    Required because PRD §2.9 says the parent account is created automatically
    when a household is created, but the parent_account_id may not equal the
    household_id — the only PRD-faithful way to find it is via the nested read.
    """
    data = get_success_data(
        api_client.get_household_parent_account(
            household_id, TEST_USERS["school_staff_headers"]
        )
    )
    # PRD §2.8 returns a list-shaped envelope of zero or one. Some
    # implementations may return the dict directly; handle both.
    if isinstance(data, list):
        if not data:
            raise AssertionError(
                f"Setup failed: no parent account found for household {household_id}"
            )
        return data[0]["id"]
    if isinstance(data, dict):
        return data["id"]
    raise AssertionError(
        f"Setup failed: unexpected parent-account envelope shape: {type(data)}"
    )


def topup_account(
    household_id: str,
    amount_cents: int,
    idempotency_key: Optional[str] = None,
    parent_account_id: Optional[str] = None,
) -> dict:
    """Top up the household's parent account (PRD §3.6). Resolves the
    parent_account_id via nested read if not supplied."""
    if parent_account_id is None:
        parent_account_id = resolve_parent_account_id(household_id)
    if idempotency_key is None:
        idempotency_key = f"key-{uuid.uuid4().hex[:10]}"
    return get_success_data(
        api_client.topup_parent_account(
            parent_account_id,
            create_topup_payload(amount_cents, idempotency_key),
            make_parent_headers(household_id),
        )
    )


def get_parent_account(household_id: str, parent_account_id: Optional[str] = None) -> dict:
    if parent_account_id is None:
        parent_account_id = resolve_parent_account_id(household_id)
    return get_success_data(
        api_client.get_parent_account(
            parent_account_id, make_parent_headers(household_id)
        )
    )


def create_service_transaction(
    student_id: str,
    menu_item_id: str,
    substitute_for_allergen: Optional[bool] = None,
) -> dict:
    payload = create_service_transaction_payload(student_id, menu_item_id)
    if substitute_for_allergen is not None:
        payload["substitute_for_allergen"] = substitute_for_allergen
    return get_success_data(
        api_client.create_service_transaction(
            payload, TEST_USERS["school_staff_headers"]
        )
    )


def settle_transaction(tx_id: str) -> dict:
    return get_success_data(
        api_client.settle_service_transaction(
            tx_id, TEST_USERS["school_staff_headers"]
        )
    )


def reject_transaction(tx_id: str, rejection_reason: str = "MANUAL") -> dict:
    return get_success_data(
        api_client.reject_service_transaction(
            tx_id, create_reject_tx_payload(rejection_reason),
            TEST_USERS["school_staff_headers"],
        )
    )


def refund_transaction(tx_id: str, expected_servicetransaction_version: int) -> dict:
    return get_success_data(
        api_client.refund_service_transaction(
            tx_id,
            create_refund_tx_payload(expected_servicetransaction_version),
            TEST_USERS["school_staff_headers"],
        )
    )


def dispute_transaction(tx_id: str, household_id: str) -> dict:
    return get_success_data(
        api_client.dispute_service_transaction(
            tx_id, make_parent_headers(household_id)
        )
    )


def resolve_dispute(tx_id: str, resolution: str) -> dict:
    return get_success_data(
        api_client.resolve_dispute_service_transaction(
            tx_id, create_resolve_dispute_payload(resolution),
            TEST_USERS["district_reviewer_headers"],
        )
    )


def revoke_eligibility(det_id: str, expected_eligibilitydetermination_version: int) -> dict:
    return get_success_data(
        api_client.revoke_eligibility_determination(
            det_id,
            create_revoke_determination_payload(
                expected_eligibilitydetermination_version
            ),
            TEST_USERS["usda_auditor_headers"],
        )
    )


def verify_eligibility(det_id: str) -> dict:
    return get_success_data(
        api_client.verify_eligibility_determination(
            det_id, TEST_USERS["usda_auditor_headers"]
        )
    )


def create_reimbursement_claim(
    school_code: str,
    period_start_utc: str,
    period_end_utc: str,
    accounting_basis: str = "CASH",
) -> dict:
    return get_success_data(
        api_client.create_reimbursement_claim(
            create_reimbursement_claim_payload(
                school_code, period_start_utc, period_end_utc, accounting_basis
            ),
            TEST_USERS["school_staff_headers"],
        )
    )


def submit_reimbursement_claim(claim_id: str) -> dict:
    return get_success_data(
        api_client.submit_reimbursement_claim(
            claim_id, TEST_USERS["school_staff_headers"]
        )
    )


# ---------------------------------------------------------------------
# Composite fixtures — each named for the state it leaves the system in
# ---------------------------------------------------------------------

def setup_clean_world(clock_iso: str = DEFAULT_CLOCK_ISO) -> None:
    """Pin the server clock — every test calls this first to anchor windows."""
    set_clock(clock_iso)


def setup_direct_cert_household(
    *,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    family_size: int = 4,
    annual_income_cents: int = 4_500_000,
    address_state: str = "CA",
    school_code: str = "ELEM-101",
    valid_from_utc: str = "2026-01-01T00:00:00.000Z",
    valid_to_utc: str = "2026-08-31T23:59:59.000Z",
) -> Tuple[dict, dict, dict]:
    """Pin clock + create DC-flagged Household + one Student + one ACTIVE FREE
    direct-cert eligibility. Returns (household, student, eligibility)."""
    setup_clean_world(clock_iso)
    household = create_household(
        family_size=family_size,
        annual_income_cents=annual_income_cents,
        address_state=address_state,
        direct_certification_flag=True,
    )
    student = create_student(household["id"], school_code=school_code)
    eligibility = create_direct_cert_eligibility(
        household["id"], tier="FREE",
        valid_from_utc=valid_from_utc, valid_to_utc=valid_to_utc,
    )
    return household, student, eligibility


def setup_approved_application(
    *,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    family_size: int = 4,
    annual_income_cents: int = 4_500_000,
    address_state: str = "CA",
    school_code: str = "ELEM-101",
    school_year: str = "2025-2026",
    decision_reason: str = "verified",
    direct_certification_flag: bool = False,
) -> Tuple[dict, dict, dict]:
    """Pin clock + create Household + Student + Application + walk it through
    DRAFT→SUBMITTED→UNDER_REVIEW→APPROVED. Returns (household, student,
    application_after_approve). The approval cascades into creating an
    EligibilityDetermination per PRD §3.3."""
    setup_clean_world(clock_iso)
    household = create_household(
        family_size=family_size,
        annual_income_cents=annual_income_cents,
        address_state=address_state,
        direct_certification_flag=direct_certification_flag,
    )
    student = create_student(household["id"], school_code=school_code)
    app = create_application(household["id"], school_year=school_year)
    submit_application(app["id"], household["id"])
    start_review(app["id"])
    approved = approve_application(app["id"], decision_reason=decision_reason)
    return household, student, approved


def setup_denied_application(
    *,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    family_size: int = 4,
    annual_income_cents: int = 4_500_000,
    address_state: str = "CA",
    school_year: str = "2025-2026",
    deny_reason: str = "missing documentation",
) -> Tuple[dict, dict]:
    """Pin clock + create Household + Application + walk it through
    DRAFT→SUBMITTED→UNDER_REVIEW→DENIED. Returns (household, application_after_deny)."""
    setup_clean_world(clock_iso)
    household = create_household(
        family_size=family_size,
        annual_income_cents=annual_income_cents,
        address_state=address_state,
        direct_certification_flag=False,
    )
    app = create_application(household["id"], school_year=school_year)
    submit_application(app["id"], household["id"])
    start_review(app["id"])
    denied = deny_application(app["id"], decision_reason=deny_reason)
    return household, denied


def setup_pending_transaction(
    *,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    list_price_cents: int = 300,
    school_code: str = "ELEM-101",
    menu_overrides: Optional[Dict[str, Any]] = None,
    substitute_for_allergen: Optional[bool] = None,
    allergens: Optional[List[str]] = None,
    severity: Optional[str] = None,
) -> Tuple[dict, dict, dict, dict, dict]:
    """Pin clock + DC household + student (with optional allergy profile) +
    menu item + one PENDING ServiceTransaction. Returns
    (household, student, eligibility, menu_item, transaction)."""
    household, student, eligibility = setup_direct_cert_household(
        clock_iso=clock_iso, school_code=school_code
    )
    if allergens is not None or severity is not None:
        create_allergy_profile(student["id"], allergens=allergens, severity=severity)
    menu_payload: Dict[str, Any] = {
        "school_code": school_code,
        "list_price_cents": list_price_cents,
    }
    if menu_overrides:
        menu_payload.update(menu_overrides)
    menu = create_menu_item(**menu_payload)
    tx = create_service_transaction(
        student["id"], menu["id"], substitute_for_allergen=substitute_for_allergen
    )
    return household, student, eligibility, menu, tx


def setup_settled_transaction_paid_tier(
    *,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    list_price_cents: int = 300,
    school_code: str = "ELEM-101",
    topup_amount_cents: int = 5000,
    annual_income_cents: int = 8_000_000,  # high enough to land in PAID tier
    address_state: str = "CA",
    family_size: int = 4,
    school_year: str = "2025-2026",
) -> Tuple[dict, dict, dict, dict, int]:
    """Full chain: pin clock + Household (PAID-tier income) + Student +
    application APPROVED + topup + menu item + create transaction + settle.
    Returns (household, student, menu, settled_transaction, balance_after_settle).
    """
    household, student, _approved_app = setup_approved_application(
        clock_iso=clock_iso,
        family_size=family_size,
        annual_income_cents=annual_income_cents,
        address_state=address_state,
        school_code=school_code,
        school_year=school_year,
        decision_reason="PAID tier confirmed",
    )
    topup_account(household["id"], topup_amount_cents)
    menu = create_menu_item(school_code=school_code, list_price_cents=list_price_cents)
    tx = create_service_transaction(student["id"], menu["id"])
    settled = settle_transaction(tx["id"])
    balance_after_settle = get_parent_account(household["id"])["balance_cents"]
    return household, student, menu, settled, balance_after_settle


def setup_two_claims_scenario_setup(
    *,
    school_code: str = "ELEM-101",
    base_clock: str = "2026-01-15T08:00:00.000Z",
    after_period_clock: str = "2026-02-01T00:00:00.000Z",
    period_start: str = "2026-01-01T00:00:00.000Z",
    period_end: str = "2026-01-31T23:59:59.000Z",
    accounting_basis: str = "CASH",
) -> Tuple[dict, dict, dict, List[dict]]:
    """Build a DC household with one student at `school_code`, register a menu
    item, create 4 transactions on the base_clock day in patterns:
      tx1, tx2, tx3 → SETTLED
      tx4 → SETTLED then REFUNDED
    then advance clock past the period and create a claim in DRAFT.
    Returns (household, student, claim, [tx1, tx2, tx3, tx4]).

    Per PRD §3.7 the closure rule blocks claim submission when any DISPUTED
    transaction exists in the period, so the fixture deliberately avoids the
    DISPUTED state in order to leave the claim submittable.
    """
    household, student, _elig = setup_direct_cert_household(
        clock_iso=base_clock, school_code=school_code,
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code=school_code, list_price_cents=0,
        federal_reimbursement_free_cents=470,
        federal_reimbursement_reduced_cents=430,
        federal_reimbursement_paid_cents=70,
    )
    txs: List[dict] = []
    for _ in range(3):
        tx = create_service_transaction(student["id"], menu["id"])
        settled = settle_transaction(tx["id"])
        txs.append(settled)
    tx4 = create_service_transaction(student["id"], menu["id"])
    tx4_settled = settle_transaction(tx4["id"])
    tx4_refunded = refund_transaction(tx4_settled["id"], tx4_settled["version"])
    txs.append(tx4_refunded)
    # Advance clock past the period so the claim period is closed.
    set_clock(after_period_clock)
    claim = create_reimbursement_claim(
        school_code, period_start, period_end, accounting_basis=accounting_basis
    )
    return household, student, claim, txs
