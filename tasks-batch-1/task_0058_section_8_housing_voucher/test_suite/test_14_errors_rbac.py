"""Queue B (breadth) — error-catalogue conditions and RBAC denials."""
from test_helpers import (
    api_client, validate_success, validate_error, set_clock,
    create_region, create_landlord, create_unit, create_passed_initial_inspection,
    make_eligible_household, issue_voucher, create_payment_standard,
    create_payment_standard_payload, create_hap_contract_payload,
    create_region_payload, create_voucher_payload,
    ADMIN, CASEWORKER, INSPECTOR,
)
from test_helpers import TEST_USERS


# ── section: errors ────────────────────────────────────────


def test_duplicate_payment_standard_rejected():
    """PRD §3.1: "The region-and-bedroom pair must be unique: if a standard
    already exists for that region_id and bedroom_size, the creation is rejected
    with ERR_DUPLICATE_PAYMENT_STANDARD (HTTP 409)."

    Design: Corner/errors/duplicate_payment_standard_rejected
    """
    region = create_region(code="DUP_R")
    create_payment_standard(region["id"], bedroom_size=1, amount_cents=90000, fmr_cents=100000)
    dup = create_payment_standard_payload(
        region["id"], bedroom_size=1, amount_cents=95000, fmr_cents=100000
    )
    validate_error(
        api_client.create_payment_standard(dup, ADMIN),
        "ERR_DUPLICATE_PAYMENT_STANDARD", 409,
    )


def test_leaseup_on_expired_voucher_not_available():
    """PRD §3.5: "its status must be either ISSUED or PORTING_OUT (a ported
    voucher can still be leased), and a voucher in any other status is rejected
    with ERR_VOUCHER_NOT_AVAILABLE (HTTP 422)." A voucher expired via the expire
    endpoint is no longer available for lease-up.

    Design: Corner/errors/leaseup_on_terminated_voucher_not_available
    """
    set_clock("2026-06-01T00:00:00Z")
    region = create_region(code="VNA_REG")
    create_payment_standard(region["id"], bedroom_size=2, amount_cents=95000, fmr_cents=100000)
    household = make_eligible_household(
        region["id"], family_size=3, annual_income_cents=1800000, dependents_count=2
    )
    voucher = issue_voucher(household["id"], term_days=60)
    landlord = create_landlord()
    unit = create_unit(
        landlord["id"], region["id"], bedroom_size=2,
        asking_rent_cents=90000, comparable_rent_cents=90000,
    )
    create_passed_initial_inspection(unit["id"])
    set_clock("2026-09-01T00:00:00Z")
    expired = validate_success(api_client.expire_voucher(voucher["id"], ADMIN), 200)
    # Expiry cascades and bumps the voucher's version; pass the CURRENT version so
    # the OCC check (§2.6 priority 5) passes and the availability gate is reached.
    resp = api_client.create_hap_contract(
        create_hap_contract_payload(voucher["id"], unit["id"], 90000, expired["version"]),
        CASEWORKER,
    )
    validate_error(resp, "ERR_VOUCHER_NOT_AVAILABLE", 422)


# ── section: rbac ──────────────────────────────────────────


def test_caseworker_cannot_create_region():
    """PRD §2.1: "If the headers are present but the declared role is not
    permitted to perform the requested operation under the access matrix in
    Section 4, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)." PRD
    §4 lists POST /regions as ProgramAdmin-only.

    Design: Corner/rbac/caseworker_cannot_create_region
    """
    resp = api_client.create_region(
        create_region_payload(code="NOPE", name="Nope", fmr_year=2026), CASEWORKER
    )
    validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)


def test_inspector_cannot_issue_voucher():
    """PRD §2.1: "the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4 lists POST /vouchers as Caseworker-only, so an Inspector is forbidden.

    Design: Corner/rbac/inspector_cannot_issue_voucher
    """
    region = create_region(code="RBAC_R")
    household = make_eligible_household(region["id"], family_size=2, annual_income_cents=1500000)
    resp = api_client.create_voucher(create_voucher_payload(household["id"]), INSPECTOR)
    validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)


def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "Every request must be authenticated with two mandatory HTTP
    headers ... If either header is missing, the request is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api_client.list_regions(headers=None)
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)
