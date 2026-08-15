"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so every test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear setup errors.

Identity threading: RetailerManager calls always use
make_retailer_manager_headers(store_id) with the actual Store id (the role is
entity-backed); RouteDriver calls use the route's assigned_driver_id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_audit_count_payload,
    create_markdown_authorization_payload,
    create_price_directive_payload,
    create_product_payload,
    create_program_payload,
    create_promotion_payload,
    create_route_payload,
    create_scan_event_payload,
    create_seasonal_set_payload,
    create_service_visit_payload,
    create_settlement_statement_payload,
    create_space_allocation_payload,
    create_store_payload,
    visit_count_line,
)
from .test_users import (
    TEST_USERS,
    make_field_auditor_headers,
    make_jobber_admin_headers,
    make_jobber_finance_headers,
    make_retailer_manager_headers,
    make_route_driver_headers,
)

ADMIN = TEST_USERS["jobber_admin_headers"]
FINANCE = TEST_USERS["jobber_finance_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]


# ─── Tier 0: clock + master data ─────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Advance the logical clock (JobberAdmin test-driving capability)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def new_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN))


def new_store(**overrides) -> dict:
    return get_success_data(
        api_client.create_store(create_store_payload(**overrides), ADMIN))


def new_product(program_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_product(
        create_product_payload(program_id, **overrides), ADMIN))


def new_route(program_id: str, driver_id: str = TEST_DEFAULTS["DRIVER_ID"],
              **overrides) -> dict:
    return get_success_data(api_client.create_route(
        create_route_payload(program_id, assigned_driver_id=driver_id,
                             **overrides),
        ADMIN))


# ─── Tier 1: agreement state progression ─────────────────────────────────────

def new_agreement(program_id: str, store_id: str, **overrides) -> dict:
    """Create a StoreAgreement (born DRAFT)."""
    return get_success_data(api_client.create_agreement(
        create_agreement_payload(program_id, store_id, **overrides), ADMIN))


def submit_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.submit_agreement(agreement_id, ADMIN))


def accept_agreement(agreement_id: str, store_id: str) -> dict:
    """PENDING_ACCEPTANCE -> ACTIVE by the store's own RetailerManager."""
    return get_success_data(api_client.accept_agreement(
        agreement_id, make_retailer_manager_headers(store_id)))


def new_active_agreement(program_id: str, store_id: str, **overrides) -> dict:
    """Create + submit + accept. Returns the ACTIVE agreement."""
    agreement = new_agreement(program_id, store_id, **overrides)
    submit_agreement(agreement["id"])
    return accept_agreement(agreement["id"], store_id)


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, ADMIN))


def current_agreement_version(agreement_id: str) -> int:
    return get_agreement(agreement_id)["version"]


# ─── Tier 2: pricing ─────────────────────────────────────────────────────────

def new_price_directive(agreement_id: str, product_id: str,
                        price_cents: int = TEST_DEFAULTS["DIRECTIVE_PRICE_CENTS"],
                        effective_from: str = CLOCK_START,
                        expected_version: int = None) -> dict:
    """Create a price directive (OCC-guarded; supersedes the incumbent).

    Reads the agreement fresh for the OCC version unless expected_version is
    given explicitly.
    """
    if expected_version is None:
        expected_version = current_agreement_version(agreement_id)
    return get_success_data(api_client.create_price_directive(
        create_price_directive_payload(
            agreement_id, product_id, expected_version,
            price_cents=price_cents, effective_from=effective_from),
        ADMIN))


def new_promotion(program_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_promotion(
        create_promotion_payload(program_id, product_id, **overrides), ADMIN))


def schedule_promotion(promotion_id: str) -> dict:
    return get_success_data(api_client.schedule_promotion(promotion_id, ADMIN))


# ─── Tier 2: the standard shop composite ─────────────────────────────────────

def setup_shop(clock: str = CLOCK_START,
               program_overrides: dict = None,
               store_overrides: dict = None,
               agreement_overrides: dict = None,
               product_overrides: dict = None,
               price_cents: int = TEST_DEFAULTS["DIRECTIVE_PRICE_CENTS"],
               effective_from: str = CLOCK_START,
               with_product: bool = True,
               with_directive: bool = True,
               with_route: bool = False,
               driver_id: str = TEST_DEFAULTS["DRIVER_ID"]) -> dict:
    """Clock + program + store + ACTIVE agreement (+ product + EFFECTIVE
    directive) (+ route). The most common test precondition bundle."""
    set_clock(clock)
    program = new_program(**(program_overrides or {}))
    store = new_store(**(store_overrides or {}))
    agreement = new_active_agreement(
        program["id"], store["id"], **(agreement_overrides or {}))
    ctx = {"program": program, "store": store, "agreement": agreement,
           "product": None, "directive": None, "route": None}
    if with_product:
        ctx["product"] = new_product(program["id"], **(product_overrides or {}))
        if with_directive:
            ctx["directive"] = new_price_directive(
                agreement["id"], ctx["product"]["id"],
                price_cents=price_cents, effective_from=effective_from)
    if with_route:
        ctx["route"] = new_route(program["id"], driver_id=driver_id)
    return ctx


# ─── Tier 3: service visit cycle ─────────────────────────────────────────────

def new_service_visit(route_id: str, agreement_id: str,
                      scheduled_date: str = "2026-08-01") -> dict:
    return get_success_data(api_client.create_service_visit(
        create_service_visit_payload(route_id, agreement_id,
                                     scheduled_date=scheduled_date),
        ADMIN))


def check_in_visit(visit_id: str, driver_id: str = TEST_DEFAULTS["DRIVER_ID"]) -> dict:
    return get_success_data(api_client.check_in_service_visit(
        visit_id, make_route_driver_headers(driver_id)))


def submit_visit_counts(visit_id: str, lines: list,
                        driver_id: str = TEST_DEFAULTS["DRIVER_ID"]) -> dict:
    return get_success_data(api_client.submit_visit_counts(
        visit_id, {"lines": lines}, make_route_driver_headers(driver_id)))


def confirm_visit(visit_id: str, store_id: str) -> dict:
    return get_success_data(api_client.confirm_service_visit(
        visit_id, make_retailer_manager_headers(store_id)))


def get_visit(visit_id: str) -> dict:
    return get_success_data(api_client.get_service_visit(visit_id, ADMIN))


def run_restock_visit(route_id: str, agreement_id: str, store_id: str,
                      product_id: str, restock_units: int,
                      counted_units: int = 0,
                      scheduled_date: str = "2026-08-01",
                      driver_id: str = TEST_DEFAULTS["DRIVER_ID"]) -> dict:
    """Schedule a visit and drive it SCHEDULED -> CONFIRMED with a single
    count line, posting the restock to the inventory ledger."""
    visit = new_service_visit(route_id, agreement_id, scheduled_date)
    check_in_visit(visit["id"], driver_id)
    submit_visit_counts(
        visit["id"],
        [visit_count_line(product_id, counted_units, restock_units)],
        driver_id)
    return confirm_visit(visit["id"], store_id)


def setup_stocked_shop(restock_units: int = 40, counted_units: int = 0,
                       scheduled_date: str = "2026-08-01", **shop_kwargs) -> dict:
    """setup_shop + route + one confirmed restock visit. Adds 'visit'."""
    shop_kwargs.setdefault("with_route", True)
    ctx = setup_shop(**shop_kwargs)
    ctx["visit"] = run_restock_visit(
        ctx["route"]["id"], ctx["agreement"]["id"], ctx["store"]["id"],
        ctx["product"]["id"], restock_units, counted_units, scheduled_date)
    return ctx


# ─── Tier 3: scan ingestion ──────────────────────────────────────────────────

def post_scan(agreement_id: str, product_id: str, store_id: str, **overrides):
    """Raw scan-ingest call (returns the Response for status inspection)."""
    return api_client.create_scan_event(
        create_scan_event_payload(agreement_id, product_id, **overrides),
        make_retailer_manager_headers(store_id))


def post_matched_sale(agreement_id: str, product_id: str, store_id: str,
                      quantity: int, scanned_at: str,
                      client_event_id: str = None) -> dict:
    """Ingest a SALE expected to land MATCHED."""
    overrides = {"event_type": "SALE", "quantity": quantity,
                 "scanned_at": scanned_at}
    if client_event_id:
        overrides["client_event_id"] = client_event_id
    return get_success_data(post_scan(agreement_id, product_id, store_id,
                                      **overrides))


# ─── Tier 3: audits ──────────────────────────────────────────────────────────

def new_audit(agreement_id: str, scope: str = "FULL", category: str = None) -> dict:
    overrides = {"scope": scope}
    if category is not None:
        overrides["category"] = category
    return get_success_data(api_client.create_audit_count(
        create_audit_count_payload(agreement_id, **overrides), ADMIN))


def start_audit(audit_id: str, auditor_id: str = TEST_DEFAULTS["AUDITOR_ID"]) -> dict:
    return get_success_data(api_client.start_audit_count(
        audit_id, make_field_auditor_headers(auditor_id)))


def submit_audit(audit_id: str, counted_lines: list,
                 auditor_id: str = TEST_DEFAULTS["AUDITOR_ID"]) -> dict:
    return get_success_data(api_client.submit_audit_count(
        audit_id, {"counted_lines": counted_lines},
        make_field_auditor_headers(auditor_id)))


def get_audit(audit_id: str) -> dict:
    return get_success_data(api_client.get_audit_count(audit_id, ADMIN))


def certify_audit(audit_id: str, certifier_id: str = TEST_DEFAULTS["ADMIN_ID"],
                  expected_version: int = None) -> dict:
    """SUBMITTED -> CERTIFIED (OCC + SoD). Reads the audit fresh for the OCC
    version unless expected_version is given explicitly."""
    if expected_version is None:
        expected_version = get_audit(audit_id)["version"]
    return get_success_data(api_client.certify_audit_count(
        audit_id, {"expected_audit_count_version": expected_version},
        make_jobber_admin_headers(certifier_id)))


def setup_submitted_audit(agreement_id: str, counted_lines: list,
                          auditor_id: str = TEST_DEFAULTS["AUDITOR_ID"],
                          scope: str = "FULL", category: str = None) -> dict:
    """Create + start + submit an audit. Returns the SUBMITTED audit (fresh)."""
    audit = new_audit(agreement_id, scope=scope, category=category)
    start_audit(audit["id"], auditor_id)
    submit_audit(audit["id"], counted_lines, auditor_id)
    return get_audit(audit["id"])


def setup_certified_audit(agreement_id: str, counted_lines: list,
                          auditor_id: str = TEST_DEFAULTS["AUDITOR_ID"],
                          certifier_id: str = TEST_DEFAULTS["ADMIN_ID"],
                          scope: str = "FULL", category: str = None) -> dict:
    """Full audit lifecycle through CERTIFIED."""
    audit = setup_submitted_audit(agreement_id, counted_lines,
                                  auditor_id=auditor_id, scope=scope,
                                  category=category)
    return certify_audit(audit["id"], certifier_id=certifier_id)


# ─── Tier 3: markdown authorizations ─────────────────────────────────────────

def new_markdown(agreement_id: str, product_id: str,
                 auth_type: str = "MARKDOWN", units: int = 1,
                 markdown_price_cents: int = None) -> dict:
    overrides = {"auth_type": auth_type, "units": units}
    if markdown_price_cents is not None:
        overrides["markdown_price_cents"] = markdown_price_cents
    return get_success_data(api_client.create_markdown_authorization(
        create_markdown_authorization_payload(agreement_id, product_id,
                                              **overrides),
        ADMIN))


def approve_markdown(markdown_id: str, store_id: str) -> dict:
    return get_success_data(api_client.approve_markdown_authorization(
        markdown_id, make_retailer_manager_headers(store_id)))


def apply_markdown(markdown_id: str) -> dict:
    return get_success_data(
        api_client.apply_markdown_authorization(markdown_id, ADMIN))


def get_markdown(markdown_id: str) -> dict:
    return get_success_data(
        api_client.get_markdown_authorization(markdown_id, ADMIN))


# ─── Tier 3: seasonal sets / space allocations ───────────────────────────────

def new_space_allocation(agreement_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_space_allocation(
        create_space_allocation_payload(agreement_id, **overrides), ADMIN))


def new_seasonal_set(agreement_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_seasonal_set(
        create_seasonal_set_payload(agreement_id, **overrides), ADMIN))


def get_seasonal_set(set_id: str) -> dict:
    return get_success_data(api_client.get_seasonal_set(set_id, ADMIN))


# ─── Tier 4/5: settlement statements ─────────────────────────────────────────

def new_statement(agreement_id: str, period_index: int = 0,
                  finance_id: str = TEST_DEFAULTS["FINANCE_ID"]) -> dict:
    """Generate a PROVISIONAL statement for a period."""
    return get_success_data(api_client.create_settlement_statement(
        create_settlement_statement_payload(agreement_id, period_index),
        make_jobber_finance_headers(finance_id)))


def get_statement(statement_id: str) -> dict:
    return get_success_data(
        api_client.get_settlement_statement(statement_id, ADMIN))


def finalize_statement(statement_id: str,
                       finance_id: str = TEST_DEFAULTS["FINANCE_ID"],
                       expected_version: int = None) -> dict:
    """PROVISIONAL -> FINALIZED (OCC). Reads the statement fresh for the OCC
    version unless expected_version is given explicitly."""
    if expected_version is None:
        expected_version = get_statement(statement_id)["version"]
    return get_success_data(api_client.finalize_settlement_statement(
        statement_id,
        {"expected_settlement_statement_version": expected_version},
        make_jobber_finance_headers(finance_id)))


def approve_statement(statement_id: str,
                      admin_id: str = TEST_DEFAULTS["ADMIN_ID"]) -> dict:
    return get_success_data(api_client.approve_settlement_statement(
        statement_id, make_jobber_admin_headers(admin_id)))


def pay_statement(statement_id: str,
                  finance_id: str = TEST_DEFAULTS["FINANCE_ID"]) -> dict:
    return get_success_data(api_client.pay_settlement_statement(
        statement_id, make_jobber_finance_headers(finance_id)))


# ─── Tier 2: inventory ledger reads ──────────────────────────────────────────

def list_balances(agreement_id: str, product_id: str = None) -> list:
    params = {"store_agreement_id": agreement_id}
    if product_id is not None:
        params["product_id"] = product_id
    return get_success_data(
        api_client.list_inventory_balances(ADMIN, params=params))


def get_balance(agreement_id: str, product_id: str):
    """The single balance row for the (agreement, product) pair, or None."""
    rows = list_balances(agreement_id, product_id)
    assert len(rows) <= 1, f"expected at most one balance row, got {len(rows)}"
    return rows[0] if rows else None
