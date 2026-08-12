"""Composite setup helpers.

The interesting PRD claims need the system in a state that takes many API
calls to reach (an APPROVED farm with valid paperwork, a VERIFIED offering,
a SIGNED planting agreement, ACCEPTED deliveries, adjudicated claims...).
These helpers encapsulate those chains so tests can focus on assertions.

All helpers build state exclusively through PRD-declared endpoints and use
the lenient get_success_data() validator so a setup failure surfaces as a
clear "Setup failed" message naming the failing step.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_claim_payload,
    create_compliance_document_payload,
    create_delivery_payload,
    create_farm_payload,
    create_forecast_line_payload,
    create_invoice_payload,
    create_kitchen_payload,
    create_offering_payload,
    create_product_payload,
    create_program_year_payload,
    create_receiving_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_claims_coordinator_headers,
    make_farm_manager_headers,
    make_kitchen_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
CLAIMS = TEST_USERS["claims_headers"]


def _setup_ok(resp, step: str):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at step '{step}': {exc}") from exc


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_program_year(open_it: bool = True, **overrides) -> dict:
    """Create a program year (PRD 3.1); open it unless open_it=False."""
    year = _setup_ok(
        api_client.create_program_year(create_program_year_payload(**overrides), ADMIN),
        "create program year",
    )
    if open_it:
        year = _setup_ok(
            api_client.open_program_year(year["id"], ADMIN), "open program year"
        )
    return year


def create_product(**overrides) -> dict:
    return _setup_ok(
        api_client.create_product(create_product_payload(**overrides), ADMIN),
        "create product",
    )


def create_kitchen(name: str = "Lincoln ES") -> dict:
    return _setup_ok(
        api_client.create_kitchen(create_kitchen_payload(name=name), ADMIN),
        "create kitchen",
    )


def create_receiving_window(
    kitchen_id: str,
    weekday: str = "MON",
    start_minute: int = 480,
    end_minute: int = 720,
    capacity_deliveries: int = 3,
) -> dict:
    payload = create_receiving_window_payload(
        kitchen_id=kitchen_id,
        weekday=weekday,
        start_minute=start_minute,
        end_minute=end_minute,
        capacity_deliveries=capacity_deliveries,
    )
    return _setup_ok(
        api_client.create_receiving_window(
            payload, make_kitchen_manager_headers(kitchen_id)
        ),
        "create receiving window",
    )


def create_farm(**overrides) -> dict:
    """Register a farm; it begins APPLIED (PRD 3.2)."""
    return _setup_ok(
        api_client.create_farm(create_farm_payload(**overrides), ADMIN),
        "create farm",
    )


def upload_safety_cert(
    farm_id: str,
    effective_on: str = "2026-01-01",
    expires_on: str = "2027-12-31",
) -> dict:
    payload = create_compliance_document_payload(
        farm_id=farm_id,
        doc_type="SAFETY_CERT",
        effective_on=effective_on,
        expires_on=expires_on,
    )
    return _setup_ok(
        api_client.create_compliance_document(
            payload, make_farm_manager_headers(farm_id)
        ),
        "upload safety cert",
    )


def upload_liability_insurance(
    farm_id: str,
    coverage_cents: int = 600000,
    effective_on: str = "2026-01-01",
    expires_on: str = "2027-12-31",
) -> dict:
    payload = create_compliance_document_payload(
        farm_id=farm_id,
        doc_type="LIABILITY_INSURANCE",
        issuer="InsCo",
        coverage_cents=coverage_cents,
        effective_on=effective_on,
        expires_on=expires_on,
    )
    return _setup_ok(
        api_client.create_compliance_document(
            payload, make_farm_manager_headers(farm_id)
        ),
        "upload liability insurance",
    )


def approve_farm(farm_id: str) -> dict:
    return _setup_ok(api_client.approve_farm(farm_id, ADMIN), "approve farm")


def create_approved_farm(
    distance_miles_to_hub: int = 30,
    acres: int = 100,
    coverage_cents: int = 600000,
    cert_expires_on: str = "2027-12-31",
    insurance_expires_on: str = "2027-12-31",
    legal_name: str = "Green Acres",
) -> dict:
    """Farm with a complete compliance file, approved (PRD 3.2)."""
    farm = create_farm(
        legal_name=legal_name,
        distance_miles_to_hub=distance_miles_to_hub,
        acres=acres,
    )
    upload_safety_cert(farm["id"], expires_on=cert_expires_on)
    upload_liability_insurance(
        farm["id"], coverage_cents=coverage_cents, expires_on=insurance_expires_on
    )
    return approve_farm(farm["id"])


def create_offering(
    farm_id: str,
    program_year_id: str,
    product_id: str,
    price_cents_per_unit: int = 250,
    max_weekly_quantity: int = 500,
    harvest_start_week: int = 4,
    harvest_end_week: int = 12,
):
    """Create a DRAFT offering. Returns the full response so callers may
    inspect either the created offering or the rejection error."""
    payload = create_offering_payload(
        farm_id=farm_id,
        program_year_id=program_year_id,
        product_id=product_id,
        price_cents_per_unit=price_cents_per_unit,
        max_weekly_quantity=max_weekly_quantity,
        harvest_start_week=harvest_start_week,
        harvest_end_week=harvest_end_week,
    )
    return api_client.create_offering(payload, make_farm_manager_headers(farm_id))


def create_verified_offering(
    farm_id: str,
    program_year_id: str,
    product_id: str,
    price_cents_per_unit: int = 250,
    harvest_start_week: int = 4,
    harvest_end_week: int = 12,
    max_weekly_quantity: int = 500,
) -> dict:
    """Offering walked DRAFT -> SUBMITTED -> VERIFIED (PRD 3.3)."""
    offering = _setup_ok(
        create_offering(
            farm_id,
            program_year_id,
            product_id,
            price_cents_per_unit=price_cents_per_unit,
            max_weekly_quantity=max_weekly_quantity,
            harvest_start_week=harvest_start_week,
            harvest_end_week=harvest_end_week,
        ),
        "create offering",
    )
    offering = _setup_ok(
        api_client.submit_offering(offering["id"], make_farm_manager_headers(farm_id)),
        "submit offering",
    )
    return _setup_ok(
        api_client.verify_offering(offering["id"], ADMIN), "verify offering"
    )


def create_forecast_line(
    program_year_id: str,
    product_id: str,
    week_number: int = 6,
    planned_quantity: int = 400,
) -> dict:
    payload = create_forecast_line_payload(
        program_year_id=program_year_id,
        product_id=product_id,
        week_number=week_number,
        planned_quantity=planned_quantity,
    )
    return _setup_ok(
        api_client.create_forecast_line(payload, ADMIN), "create forecast line"
    )


def create_agreement(
    program_year_id: str,
    offering_id: str,
    committed_quantity: int = 200,
    harvest_start_week: int = 5,
    harvest_end_week: int = 10,
):
    """Propose a planting agreement. Returns the full response so callers may
    inspect either the created agreement or the rejection error."""
    payload = create_agreement_payload(
        program_year_id=program_year_id,
        offering_id=offering_id,
        committed_quantity=committed_quantity,
        harvest_start_week=harvest_start_week,
        harvest_end_week=harvest_end_week,
    )
    return api_client.create_planting_agreement(payload, ADMIN)


def sign_agreement(agreement_id: str, farm_id: str) -> dict:
    return _setup_ok(
        api_client.sign_agreement(agreement_id, make_farm_manager_headers(farm_id)),
        "sign agreement",
    )


# ---------------------------------------------------------------------------
# Tier 2: the standard procurement chain
# ---------------------------------------------------------------------------

def setup_procurement_chain(
    committed_quantity: int = 200,
    price_cents_per_unit: int = 250,
    farm_distance: int = 30,
    farm_acres: int = 100,
    coverage_cents: int = 600000,
    cert_expires_on: str = "2027-12-31",
    window_capacity: int = 3,
    forecast_planned: int = 400,
    forecast_week: int = 6,
    preference_model: str = "TIERED",
    grant_award_cents: int = 1000000,
    agreement_window=(5, 10),
    offering_window=(4, 12),
    season=(1, 20),
    radius: int = 100,
    with_forecast: bool = True,
    with_kitchen: bool = True,
    with_agreement: bool = True,
    sign: bool = True,
    year_overrides: dict = None,
) -> SimpleNamespace:
    """The standard preamble shared by most claims:

    OPEN program year + ACTIVE product + APPROVED compliant farm +
    VERIFIED offering (+ forecast line, kitchen with a MON 480-720 window,
    planting agreement, optionally signed).

    Returns a namespace: year, product, farm, offering, forecast_line,
    kitchen, window, agreement (entries are None when opted out).
    """
    year_kw = {"preference_model": preference_model, "grant_award_cents": grant_award_cents,
               "local_radius_miles": radius}
    if year_overrides:
        year_kw.update(year_overrides)
    year = create_program_year(**year_kw)
    product = create_product(
        season_start_week=season[0], season_end_week=season[1]
    )
    farm = create_approved_farm(
        distance_miles_to_hub=farm_distance,
        acres=farm_acres,
        coverage_cents=coverage_cents,
        cert_expires_on=cert_expires_on,
    )
    offering = create_verified_offering(
        farm["id"],
        year["id"],
        product["id"],
        price_cents_per_unit=price_cents_per_unit,
        harvest_start_week=offering_window[0],
        harvest_end_week=offering_window[1],
    )
    forecast_line = (
        create_forecast_line(
            year["id"],
            product["id"],
            week_number=forecast_week,
            planned_quantity=forecast_planned,
        )
        if with_forecast
        else None
    )
    kitchen = create_kitchen() if with_kitchen else None
    window = (
        create_receiving_window(kitchen["id"], capacity_deliveries=window_capacity)
        if with_kitchen
        else None
    )
    agreement = None
    if with_agreement:
        agreement = _setup_ok(
            create_agreement(
                year["id"],
                offering["id"],
                committed_quantity=committed_quantity,
                harvest_start_week=agreement_window[0],
                harvest_end_week=agreement_window[1],
            ),
            "create agreement",
        )
        if sign:
            agreement = sign_agreement(agreement["id"], farm["id"])
    return SimpleNamespace(
        year=year,
        product=product,
        farm=farm,
        offering=offering,
        forecast_line=forecast_line,
        kitchen=kitchen,
        window=window,
        agreement=agreement,
    )


# ---------------------------------------------------------------------------
# Tier 3: delivery / invoice lifecycle shortcuts
# ---------------------------------------------------------------------------

def schedule_delivery(
    agreement_id: str,
    kitchen_id: str,
    window_id: str,
    farm_id: str,
    delivery_date: str = "2026-08-10",
    quantity: int = 40,
):
    """Schedule a delivery. Returns the full response (success or error)."""
    payload = create_delivery_payload(
        agreement_id=agreement_id,
        kitchen_id=kitchen_id,
        window_id=window_id,
        delivery_date=delivery_date,
        quantity=quantity,
    )
    return api_client.create_delivery(payload, make_farm_manager_headers(farm_id))


def check_in_delivery(delivery_id: str, kitchen_id: str) -> dict:
    return _setup_ok(
        api_client.check_in_delivery(
            delivery_id, make_kitchen_manager_headers(kitchen_id)
        ),
        "check in delivery",
    )


def accept_delivery(
    delivery_id: str, kitchen_id: str, accepted_quantity: int
) -> dict:
    check_in_delivery(delivery_id, kitchen_id)
    return _setup_ok(
        api_client.accept_delivery(
            delivery_id,
            {"accepted_quantity": accepted_quantity},
            make_kitchen_manager_headers(kitchen_id),
        ),
        "accept delivery",
    )


def create_accepted_delivery(
    agreement_id: str,
    kitchen_id: str,
    window_id: str,
    farm_id: str,
    delivery_date: str = "2026-08-10",
    quantity: int = 40,
    accepted_quantity: int = None,
) -> dict:
    """Schedule -> check in -> accept. Returns the ACCEPTED delivery."""
    delivery = _setup_ok(
        schedule_delivery(
            agreement_id, kitchen_id, window_id, farm_id, delivery_date, quantity
        ),
        "schedule delivery",
    )
    return accept_delivery(
        delivery["id"],
        kitchen_id,
        quantity if accepted_quantity is None else accepted_quantity,
    )


def create_invoice(delivery_id: str, farm_id: str, invoice_number: str):
    """Create a DRAFT invoice. Returns the full response (success or error)."""
    return api_client.create_invoice(
        create_invoice_payload(delivery_id=delivery_id, invoice_number=invoice_number),
        make_farm_manager_headers(farm_id),
    )


def create_approved_invoice(
    delivery_id: str,
    farm_id: str,
    invoice_number: str,
    approver_user_id: str = "admin-1",
) -> dict:
    """Invoice walked DRAFT -> SUBMITTED -> APPROVED (PRD 3.6)."""
    invoice = _setup_ok(
        create_invoice(delivery_id, farm_id, invoice_number), "create invoice"
    )
    _setup_ok(
        api_client.submit_invoice(invoice["id"], make_farm_manager_headers(farm_id)),
        "submit invoice",
    )
    return _setup_ok(
        api_client.approve_invoice(
            invoice["id"], make_admin_headers(approver_user_id)
        ),
        "approve invoice",
    )


# ---------------------------------------------------------------------------
# Tier 4: claim assembly helpers
# ---------------------------------------------------------------------------

def create_claim(program_year_id: str, period_month: str = "2026-08") -> dict:
    return _setup_ok(
        api_client.create_claim(
            create_claim_payload(
                program_year_id=program_year_id, period_month=period_month
            ),
            CLAIMS,
        ),
        "create claim",
    )


def get_claim(claim_id: str) -> dict:
    return _setup_ok(api_client.get_claim(claim_id, CLAIMS), "get claim")


def add_claim_line(claim_id: str, invoice_id: str) -> dict:
    """Add a claim line under the OCC rule (PRD 2.9): re-reads the claim to
    obtain the current version, then posts the line."""
    current = get_claim(claim_id)
    return _setup_ok(
        api_client.add_claim_line(
            claim_id,
            {"invoice_id": invoice_id, "expected_claim_version": current["version"]},
            CLAIMS,
        ),
        "add claim line",
    )


def find_claim_line_for_invoice(invoice_id: str) -> dict:
    resp = api_client.list_claim_lines(AUDITOR, params={"invoice_id": invoice_id})
    data = _setup_ok(resp, "list claim lines by invoice")
    items = data if isinstance(data, list) else data.get("items", data)
    assert items, f"Setup failed: no claim line found for invoice {invoice_id}"
    return items[0]


def submit_claim(claim_id: str, user_id: str = "claims-1") -> dict:
    return _setup_ok(
        api_client.submit_claim(
            claim_id, make_claims_coordinator_headers(user_id)
        ),
        "submit claim",
    )


def start_claim_review(claim_id: str) -> dict:
    return _setup_ok(api_client.start_claim_review(claim_id, AUDITOR), "start review")


def setup_claim_under_review(
    chain: SimpleNamespace,
    deliveries_and_numbers,
    period_month: str = "2026-08",
) -> SimpleNamespace:
    """Build an UNDER_REVIEW claim whose lines cover the given deliveries.

    deliveries_and_numbers: list of (delivery, invoice_number) pairs; each
    delivery must be ACCEPTED. Invoices are approved by admin-1 and the claim
    is submitted by claims-1, keeping the segregation-of-duties gate clean.
    """
    invoices = [
        create_approved_invoice(d["id"], chain.farm["id"], num)
        for d, num in deliveries_and_numbers
    ]
    claim = create_claim(chain.year["id"], period_month)
    lines = [add_claim_line(claim["id"], inv["id"]) for inv in invoices]
    claim = submit_claim(claim["id"])
    claim = start_claim_review(claim["id"])
    return SimpleNamespace(claim=claim, lines=lines, invoices=invoices)


# ---------------------------------------------------------------------------
# Tier 5: clock and misc
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD 2.8). Returns the raw response."""
    return api_client.set_clock(to_iso8601, ADMIN)


def advance_clock(to_iso8601: str):
    resp = set_clock(to_iso8601)
    assert resp.status_code == 200, (
        f"Setup failed at step 'advance clock': {resp.status_code} {resp.text}"
    )
    return resp
