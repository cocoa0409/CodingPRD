"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in this PRD require the system to be in a specific state
that takes several API calls to reach: brand -> territory -> franchisee (approve) ->
assign territory -> unit -> open, then layered flows (sales report -> accept ->
royalty statement -> issue -> close-period -> overdue -> write-off; audit schedule
-> start -> finalize with a target grade; vendor -> approve -> authorizations ->
national account -> distribute; agreement -> execute -> begin-renewal). These
helpers encapsulate those preambles so tests focus on assertions.

Every helper uses get_success_data() (lenient validator) internally so setup
failures surface as clear errors rather than confusing assertion mismatches. Each
test starts against an empty database (the harness restarts the server before every
test), so every helper builds its state from scratch using only PRD-declared
endpoints.

Identity threading: Franchisee is an entity_backed role (§2.1) — X-User-ID is
matched against the franchisee's owner_user_id. Any ownership-gated franchisee call
(unit open/close, sales-report create, vendor-authorization create) uses
make_franchisee_headers(owner_user_id) with the SAME owner_user_id string the
franchisee was created with. The four opaque operator roles use shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_brand_payload,
    create_territory_payload,
    assign_territory_payload,
    create_franchisee_payload,
    create_agreement_payload,
    create_unit_payload,
    create_sales_report_payload,
    create_royalty_statement_payload,
    create_vendor_payload,
    create_vendor_authorization_payload,
    create_audit_payload,
    finalize_audit_payload,
    create_national_account_payload,
    create_development_schedule_payload,
)
from .test_users import TEST_USERS, make_franchisee_headers

FRANCHISOR = TEST_USERS["franchisor_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# ─── Tier 1: base entities ───────────────────────────────────────────────────
def create_brand(**overrides) -> dict:
    """Create a Brand as Franchisor. Returns the brand entity."""
    return get_success_data(
        api_client.create_brand(create_brand_payload(**overrides), FRANCHISOR)
    )


def create_territory(brand_id: str, **overrides) -> dict:
    """Create an AVAILABLE Territory under a brand as Franchisor."""
    return get_success_data(
        api_client.create_territory(
            create_territory_payload(brand_id, **overrides), FRANCHISOR
        )
    )


def create_franchisee(brand_id: str, owner_user_id: str = "u_owner", **overrides) -> dict:
    """Create an APPLICANT Franchisee. owner_user_id is the string later threaded as
    X-User-ID for the entity_backed Franchisee role."""
    overrides.setdefault("owner_user_id", owner_user_id)
    return get_success_data(
        api_client.create_franchisee(
            create_franchisee_payload(brand_id, **overrides), FRANCHISOR
        )
    )


def approve_franchisee(franchisee_id: str) -> dict:
    """APPLICANT -> APPROVED."""
    return get_success_data(
        api_client.approve_franchisee(franchisee_id, FRANCHISOR)
    )


def assign_territory(territory_id: str, franchisee_id: str) -> dict:
    """Territory AVAILABLE -> ASSIGNED to the franchisee."""
    return get_success_data(
        api_client.assign_territory(
            territory_id, assign_territory_payload(franchisee_id), FRANCHISOR
        )
    )


def create_unit(franchisee_id: str, territory_id: str, **overrides) -> dict:
    """Create a PLANNED Unit under a franchisee+territory as Franchisor."""
    return get_success_data(
        api_client.create_unit(
            create_unit_payload(franchisee_id, territory_id, **overrides), FRANCHISOR
        )
    )


def open_unit(unit_id: str, owner_user_id: str) -> dict:
    """Open a unit as its owning Franchisee (ownership-gated). PLANNED -> OPEN."""
    return get_success_data(
        api_client.open_unit(unit_id, make_franchisee_headers(owner_user_id))
    )


def close_period(brand_id: str) -> dict:
    """Advance the brand clock one period as Franchisor; runs period-close cascades."""
    return get_success_data(api_client.close_period(brand_id, FRANCHISOR))


def get_brand_version(brand_id: str) -> int:
    """Read the brand's current version (for OCC-guarded writes)."""
    return get_success_data(api_client.get_brand(brand_id, FRANCHISOR))["version"]


# ─── Tier 2: base hierarchy (brand + approved franchisee + assigned territory) ─
def setup_brand_franchisee_territory(
    owner_user_id: str = "u_owner",
    territory_code: str = "T1",
    brand_overrides=None,
    franchisee_overrides=None,
):
    """Create brand + APPROVED franchisee + ASSIGNED territory.

    Returns (brand, franchisee, territory). The franchisee is APPROVED (not yet
    ACTIVE — that requires opening its first unit). owner_user_id is captured so
    callers can thread it through ownership-gated calls.
    """
    brand = create_brand(**(brand_overrides or {}))
    territory = create_territory(brand["id"], code=territory_code)
    franchisee = create_franchisee(
        brand["id"], owner_user_id=owner_user_id, **(franchisee_overrides or {})
    )
    approve_franchisee(franchisee["id"])
    territory = assign_territory(territory["id"], franchisee["id"])
    return brand, franchisee, territory


def setup_open_unit(
    owner_user_id: str = "u_owner",
    territory_code: str = "T1",
):
    """Full base: brand + APPROVED franchisee + ASSIGNED territory + one OPEN unit.

    Opening the first unit cascades the franchisee APPROVED -> ACTIVE. Returns
    (brand, franchisee, territory, unit).
    """
    brand, franchisee, territory = setup_brand_franchisee_territory(
        owner_user_id=owner_user_id, territory_code=territory_code
    )
    unit = create_unit(franchisee["id"], territory["id"])
    unit = open_unit(unit["id"], owner_user_id)
    return brand, franchisee, territory, unit


# ─── Tier 3: sales / royalty lifecycle ───────────────────────────────────────
def create_accepted_sales_report(
    unit_id: str, period_index: int, gross_sales_cents: int, discounts_cents: int = 0
) -> dict:
    """Ingest a POS report (as Franchisor) and accept it (as FinanceClerk).
    Returns the ACCEPTED report."""
    report = get_success_data(
        api_client.create_sales_report(
            create_sales_report_payload(
                unit_id,
                period_index,
                gross_sales_cents,
                discounts_cents=discounts_cents,
            ),
            FRANCHISOR,
        )
    )
    return get_success_data(api_client.accept_sales_report(report["id"], CLERK))


def create_issued_statement(
    unit_id: str, period_index: int
) -> dict:
    """Create a DRAFT royalty statement and issue it (as FinanceClerk). Requires at
    least one ACCEPTED sales report for the unit+period already to exist. Returns the
    ISSUED statement with computed royalty/ad_fund/total_due."""
    statement = get_success_data(
        api_client.create_royalty_statement(
            create_royalty_statement_payload(unit_id, period_index), CLERK
        )
    )
    return get_success_data(
        api_client.issue_royalty_statement(statement["id"], CLERK)
    )


def setup_issued_statement(
    gross_sales_cents: int,
    discounts_cents: int = 0,
    owner_user_id: str = "u_owner",
    territory_code: str = "T1",
):
    """Base open unit + one ACCEPTED sales report at period 0 + an ISSUED royalty
    statement for period 0.

    Returns (brand, franchisee, territory, unit, statement).
    """
    brand, franchisee, territory, unit = setup_open_unit(
        owner_user_id=owner_user_id, territory_code=territory_code
    )
    create_accepted_sales_report(
        unit["id"], 0, gross_sales_cents, discounts_cents=discounts_cents
    )
    statement = create_issued_statement(unit["id"], 0)
    return brand, franchisee, territory, unit, statement


def setup_overdue_statement(
    gross_sales_cents: int,
    extra_close_periods: int = 0,
    owner_user_id: str = "u_owner",
    territory_code: str = "T1",
):
    """ISSUED statement at period 0 driven OVERDUE by close-periods.

    The statement's due_period_index is 1, so the first close-period (current_period_index
    -> 1) does not yet make it overdue; the second close-period (-> 2) does. We always
    advance at least twice so the statement is OVERDUE, then advance extra_close_periods
    more (raising months_late = current_period_index - due_period_index).

    Returns (brand, franchisee, territory, unit, statement) with statement re-read so
    status reflects OVERDUE. Brand version reflects all close-periods applied.
    """
    brand, franchisee, territory, unit, statement = setup_issued_statement(
        gross_sales_cents,
        owner_user_id=owner_user_id,
        territory_code=territory_code,
    )
    total_advances = 2 + extra_close_periods
    for _ in range(total_advances):
        close_period(brand["id"])
    statement = get_success_data(
        api_client.get_royalty_statement(statement["id"], CLERK)
    )
    return brand, franchisee, territory, unit, statement


# ─── Tier 3b: audits ─────────────────────────────────────────────────────────
def create_in_progress_audit(unit_id: str) -> dict:
    """Schedule + start an audit on an OPEN unit (as ComplianceAuditor). Returns the
    IN_PROGRESS audit."""
    audit = get_success_data(
        api_client.create_audit(create_audit_payload(unit_id), AUDITOR)
    )
    return get_success_data(api_client.start_audit(audit["id"], AUDITOR))


def finalize_audit(
    audit_id: str,
    food_safety_score: int,
    cleanliness_score: int,
    service_score: int,
    brand_compliance_score: int,
) -> dict:
    """Finalize an IN_PROGRESS audit with section scores. Returns the FINALIZED
    audit (with computed weighted_score, overall_score, grade)."""
    return get_success_data(
        api_client.finalize_audit(
            audit_id,
            finalize_audit_payload(
                food_safety_score,
                cleanliness_score,
                service_score,
                brand_compliance_score,
            ),
            AUDITOR,
        )
    )


def setup_in_progress_audit(owner_user_id: str = "u_owner", territory_code: str = "T1"):
    """Base open unit + one IN_PROGRESS audit on it.

    Returns (brand, franchisee, territory, unit, audit).
    """
    brand, franchisee, territory, unit = setup_open_unit(
        owner_user_id=owner_user_id, territory_code=territory_code
    )
    audit = create_in_progress_audit(unit["id"])
    return brand, franchisee, territory, unit, audit


def setup_finalized_audit(
    food_safety_score: int,
    cleanliness_score: int,
    service_score: int,
    brand_compliance_score: int,
    owner_user_id: str = "u_owner",
    territory_code: str = "T1",
):
    """Base open unit + an audit finalized with the given section scores.

    Returns (brand, franchisee, territory, unit, audit).
    """
    brand, franchisee, territory, unit, audit = setup_in_progress_audit(
        owner_user_id=owner_user_id, territory_code=territory_code
    )
    audit = finalize_audit(
        audit["id"],
        food_safety_score,
        cleanliness_score,
        service_score,
        brand_compliance_score,
    )
    return brand, franchisee, territory, unit, audit


def setup_suspended_unit(owner_user_id: str = "u_owner", territory_code: str = "T1"):
    """Base open unit driven to compliance_status SUSPENDED by a single FAIL audit
    (all section scores 30 -> overall 30.0 -> FAIL). The owning franchisee's
    open_compliance_strikes becomes 1.

    Returns (brand, franchisee, territory, unit, fail_audit).
    """
    return setup_finalized_audit(
        30, 30, 30, 30, owner_user_id=owner_user_id, territory_code=territory_code
    )


# ─── Tier 4: vendors, authorizations, national accounts (rebate flows) ────────
def create_approved_vendor(brand_id: str, **overrides) -> dict:
    """Create a vendor (as ComplianceAuditor) and approve it. Returns APPROVED
    vendor."""
    vendor = get_success_data(
        api_client.create_vendor(create_vendor_payload(brand_id, **overrides), AUDITOR)
    )
    return get_success_data(api_client.approve_vendor(vendor["id"], AUDITOR))


def create_authorization(
    unit_id: str, vendor_id: str, qualifying_purchase_cents: int = 0
) -> dict:
    """Create an ACTIVE VendorAuthorization (as Franchisor — passes ownership since
    Franchisor is not ownership-gated). Returns the authorization."""
    return get_success_data(
        api_client.create_vendor_authorization(
            create_vendor_authorization_payload(
                unit_id,
                vendor_id,
                qualifying_purchase_cents=qualifying_purchase_cents,
            ),
            FRANCHISOR,
        )
    )


def setup_rebate_scenario(
    qualifying_purchases,
    rebate_pool_cents: int,
    min_qualifying_cents: int = 1_000_000,
    owner_user_id: str = "u_owner",
):
    """Brand + APPROVED vendor + one franchisee with N units, each carrying an ACTIVE
    VendorAuthorization for the vendor with the given qualifying_purchase_cents, plus
    an OPEN NationalAccount funded by that vendor.

    qualifying_purchases is an ordered list of ints; authorizations are created in
    that order (so created_at ASC matches list order, which is the rebate tie-break).
    The units are PLANNED (rebate eligibility keys off the authorization status ACTIVE
    and qualifying_purchase_cents, not unit operational status, per §3.9).

    Returns (brand, vendor, franchisee, territory, units, authorizations, account,
    brand_version).
    """
    brand, franchisee, territory = setup_brand_franchisee_territory(
        owner_user_id=owner_user_id
    )
    vendor = create_approved_vendor(brand["id"])
    units = []
    authorizations = []
    for i, qpc in enumerate(qualifying_purchases):
        unit = create_unit(
            franchisee["id"], territory["id"], address=f"U-{i}"
        )
        units.append(unit)
        authorizations.append(
            create_authorization(unit["id"], vendor["id"], qualifying_purchase_cents=qpc)
        )
    account = get_success_data(
        api_client.create_national_account(
            create_national_account_payload(
                brand["id"],
                vendor["id"],
                rebate_pool_cents,
                min_qualifying_cents=min_qualifying_cents,
            ),
            CLERK,
        )
    )
    brand_version = get_brand_version(brand["id"])
    return (
        brand,
        vendor,
        franchisee,
        territory,
        units,
        authorizations,
        account,
        brand_version,
    )


# ─── Tier 5: agreements (renewal / transfer / decline) ───────────────────────
def create_executed_agreement(
    franchisee_id: str, term_end_period_index: int, **overrides
) -> dict:
    """Create a DRAFT agreement and execute it. Returns the EXECUTED agreement."""
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(
                franchisee_id, term_end_period_index, **overrides
            ),
            FRANCHISOR,
        )
    )
    return get_success_data(api_client.execute_agreement(agreement["id"], FRANCHISOR))


def setup_renewal_pending_agreement(
    owner_user_id: str = "u_owner",
    territory_code: str = "T1",
    with_open_unit: bool = False,
):
    """Brand + APPROVED franchisee + ASSIGNED territory + an EXECUTED agreement with
    term_end_period_index=1, brand advanced one period (current_period_index=1, which
    is >= term_end - 1 = 0 so the renewal window is open), then begin-renewal applied
    so the agreement is RENEWAL_PENDING.

    If with_open_unit is True, a unit is created and opened before the agreement so the
    franchisee is ACTIVE (used by compliance-block flows). Returns
    (brand, franchisee, territory, agreement, unit_or_None).
    """
    brand, franchisee, territory = setup_brand_franchisee_territory(
        owner_user_id=owner_user_id, territory_code=territory_code
    )
    unit = None
    if with_open_unit:
        unit = create_unit(franchisee["id"], territory["id"])
        unit = open_unit(unit["id"], owner_user_id)
    agreement = create_executed_agreement(franchisee["id"], 1)
    close_period(brand["id"])  # current_period_index -> 1
    agreement = get_success_data(
        api_client.begin_renewal(agreement["id"], FRANCHISOR)
    )
    return brand, franchisee, territory, agreement, unit


def create_development_schedule(
    franchisee_id: str, required_units: int, deadline_period_index: int
) -> dict:
    """Create an ON_TRACK development schedule for a franchisee as Franchisor."""
    return get_success_data(
        api_client.create_development_schedule(
            create_development_schedule_payload(
                franchisee_id, required_units, deadline_period_index
            ),
            FRANCHISOR,
        )
    )
