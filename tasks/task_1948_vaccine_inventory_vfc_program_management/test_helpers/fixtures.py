"""Composite setup helpers for the VFC domain (PRD §2–§3).

Every helper builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints, and returns parsed response data.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BOOT_CLOCK_UTC,
    DEFAULT_EXPIRES_ON,
    PEDIATRIC_DOB,
    VISIT_DATE,
)
from .factories import (
    create_allocation_receipt_payload,
    create_audit_payload,
    create_approve_order_payload,
    create_borrow_ticket_payload,
    create_dose_administration_payload,
    create_lot_payload,
    create_order_line_payload,
    create_patient_payload,
    create_payback_payload,
    create_provider_site_payload,
    create_reading_payload,
    create_screening_payload,
    create_storage_unit_payload,
    create_transfer_payload,
    create_vaccine_order_payload,
    create_vaccine_product_payload,
)
from .test_users import TEST_USERS

VM = TEST_USERS["vaccine_manager_headers"]
SPO = TEST_USERS["state_program_officer_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


# --- Tier 1: single-entity creation ------------------------------------------

def set_clock(to_iso8601=BOOT_CLOCK_UTC) -> dict:
    """Advance the logical clock (ComplianceAuditor only, PRD §2.10)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, CA))


def make_site(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider_site(create_provider_site_payload(**overrides), CA)
    )


def make_unit(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_storage_unit(site_id, create_storage_unit_payload(**overrides), VM)
    )


def make_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_vaccine_product(create_vaccine_product_payload(**overrides), CA)
    )


def make_private_lot(site_id, unit_id, product_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(
            site_id, create_lot_payload(unit_id, product_id, **overrides), VM
        )
    )


def make_patient(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient(site_id, create_patient_payload(**overrides), VM)
    )


def make_screening(patient_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_eligibility_screening(
            patient_id, create_screening_payload(**overrides), VM
        )
    )


def get_site(site_id) -> dict:
    return get_success_data(api_client.get_provider_site(site_id, VM))


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, VM))


def get_ticket(ticket_id) -> dict:
    return get_success_data(api_client.get_borrow_ticket(ticket_id, VM))


def get_order(site_id, order_id) -> dict:
    return get_success_data(api_client.get_vaccine_order(site_id, order_id, VM))


def get_unit(unit_id) -> dict:
    return get_success_data(api_client.get_storage_unit(unit_id, VM))


# --- Tier 2: order pipeline ---------------------------------------------------

def make_order(site_id, expected_vfc_doses=5) -> dict:
    return get_success_data(
        api_client.create_vaccine_order(
            site_id, create_vaccine_order_payload(expected_vfc_doses=expected_vfc_doses), VM
        )
    )


def add_order_line(site_id, order_id, product_id, requested_doses) -> dict:
    return get_success_data(
        api_client.add_order_line(
            site_id,
            order_id,
            create_order_line_payload(product_id, requested_doses=requested_doses),
            VM,
        )
    )


def submit_order(site_id, order_id) -> dict:
    return get_success_data(api_client.submit_order(site_id, order_id, VM))


def approve_order(site_id, order_id, approved_vfc_doses, line_allocations=None) -> dict:
    """Approve after reading the site's current version (OCC, PRD §2.8)."""
    site_version = get_site(site_id)["version"]
    payload = create_approve_order_payload(
        approved_vfc_doses, site_version, line_allocations=line_allocations
    )
    return get_success_data(api_client.approve_order(site_id, order_id, payload, SPO))


def make_approved_order(site_id, product_id, doses):
    """DRAFT -> SUBMITTED -> APPROVED with one line. Returns (order, line)."""
    order = make_order(site_id, expected_vfc_doses=doses)
    line = add_order_line(site_id, order["id"], product_id, requested_doses=doses)
    submit_order(site_id, order["id"])
    order = approve_order(site_id, order["id"], approved_vfc_doses=doses)
    return order, line


def post_receipt(site_id, order_id, line_id, unit_id, quantity_doses,
                 lot_number=None, expires_on=DEFAULT_EXPIRES_ON) -> dict:
    overrides = {"quantity_doses": quantity_doses, "expires_on": expires_on}
    if lot_number is not None:
        overrides["lot_number"] = lot_number
    return get_success_data(
        api_client.create_allocation_receipt(
            site_id, order_id,
            create_allocation_receipt_payload(line_id, unit_id, **overrides),
            VM,
        )
    )


def make_public_lot(site_id, unit_id, product_id, doses,
                    lot_number=None, expires_on=DEFAULT_EXPIRES_ON) -> dict:
    """Approved order + one full receipt -> PUBLIC_VFC lot (PRD §3.5).

    Returns {"order", "line", "receipt", "lot_id"}.
    """
    order, line = make_approved_order(site_id, product_id, doses)
    receipt = post_receipt(
        site_id, order["id"], line["id"], unit_id, doses,
        lot_number=lot_number, expires_on=expires_on,
    )
    return {"order": order, "line": line, "receipt": receipt, "lot_id": receipt["lot_id"]}


def make_public_lots(site_id, unit_id, product_id, quantities) -> dict:
    """One approved order for sum(quantities); one receipt (and lot) per entry."""
    order, line = make_approved_order(site_id, product_id, sum(quantities))
    lot_ids = []
    for qty in quantities:
        receipt = post_receipt(site_id, order["id"], line["id"], unit_id, qty)
        lot_ids.append(receipt["lot_id"])
    return {"order": order, "line": line, "lot_ids": lot_ids}


# --- Tier 3: clinic composites ------------------------------------------------

def make_clinic(public_doses=10, private_doses=8) -> dict:
    """Site + unit + product + one PUBLIC_VFC lot + one PRIVATE lot."""
    site = make_site()
    unit = make_unit(site["id"])
    product = make_product()
    pub = make_public_lot(site["id"], unit["id"], product["id"], public_doses)
    priv_lot = make_private_lot(
        site["id"], unit["id"], product["id"], quantity_on_hand=private_doses
    )
    return {
        "site": site,
        "unit": unit,
        "product": product,
        "order": pub["order"],
        "line": pub["line"],
        "pub_lot_id": pub["lot_id"],
        "priv_lot": priv_lot,
    }


def make_screened_patient(site_id, dob=PEDIATRIC_DOB, category="MEDICAID",
                          visit_date=VISIT_DATE):
    """Patient + one screening on visit_date. Returns (patient, screening)."""
    patient = make_patient(site_id, date_of_birth=dob, insurance_category=category)
    screening = make_screening(
        patient["id"], screening_date=visit_date, insurance_category_at_visit=category
    )
    return patient, screening


def administer_dose(site_id, patient_id, screening_id, lot_id,
                    administration_date=VISIT_DATE, **extra) -> dict:
    payload = create_dose_administration_payload(
        patient_id, screening_id, lot_id,
        administration_date=administration_date, **extra,
    )
    return get_success_data(api_client.create_dose_administration(site_id, payload, VM))


def make_public_dose(site_id, lot_id, dob=PEDIATRIC_DOB, visit_date=VISIT_DATE):
    """VFC-eligible patient + screening + one administered PUBLIC_VFC dose."""
    patient, screening = make_screened_patient(
        site_id, dob=dob, category="MEDICAID", visit_date=visit_date
    )
    dose = administer_dose(
        site_id, patient["id"], screening["id"], lot_id, administration_date=visit_date
    )
    return {"patient": patient, "screening": screening, "dose": dose}


# --- Tier 4: excursions --------------------------------------------------------

def post_reading(unit_id, recorded_at, temperature_c) -> dict:
    return get_success_data(
        api_client.record_temperature_reading(
            unit_id, create_reading_payload(recorded_at, temperature_c), VM
        )
    )


def list_excursions(unit_id) -> list:
    return get_success_data(api_client.list_excursions(unit_id, VM))


def open_excursion(unit_id, recorded_at="2026-08-01T10:00:00Z", temperature_c=12.0) -> dict:
    """One out-of-range reading opens an excursion; returns the excursion row."""
    post_reading(unit_id, recorded_at, temperature_c)
    return list_excursions(unit_id)[0]


def open_and_close_excursion(
    unit_id,
    open_at="2026-08-01T10:00:00Z",
    open_temp=12.0,
    close_at="2026-08-01T11:00:00Z",
    close_temp=5.0,
) -> dict:
    """Out-of-range reading then an in-range one: excursion OPEN with closed_at set."""
    post_reading(unit_id, open_at, open_temp)
    post_reading(unit_id, close_at, close_temp)
    return list_excursions(unit_id)[0]


def resolve_excursion_viable(unit_id, excursion_id, notes="OK per mfg guidance") -> dict:
    get_success_data(api_client.begin_excursion_review(unit_id, excursion_id, VM))
    return get_success_data(
        api_client.resolve_excursion_viable(unit_id, excursion_id, {"resolution_notes": notes}, VM)
    )


def resolve_excursion_wasted(unit_id, excursion_id, notes="spoilage confirmed") -> dict:
    get_success_data(api_client.begin_excursion_review(unit_id, excursion_id, VM))
    return get_success_data(
        api_client.resolve_excursion_wasted(unit_id, excursion_id, {"resolution_notes": notes}, VM)
    )


# --- Tier 5: borrow tickets ----------------------------------------------------

def make_borrow_ticket(site_id, from_lot_id, to_lot_id, direction, borrowed_quantity,
                       reason_code="STOCK_OUT") -> dict:
    return get_success_data(
        api_client.create_borrow_ticket(
            site_id,
            create_borrow_ticket_payload(
                from_lot_id, to_lot_id,
                direction=direction, borrowed_quantity=borrowed_quantity,
                reason_code=reason_code,
            ),
            VM,
        )
    )


def record_payback_ok(site_id, ticket_id, payback_quantity, paying_lot_id,
                      expected_borrow_ticket_version) -> dict:
    return get_success_data(
        api_client.record_payback(
            site_id, ticket_id,
            create_payback_payload(
                payback_quantity, paying_lot_id, expected_borrow_ticket_version
            ),
            VM,
        )
    )


def setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                      direction="PUBLIC_FROM_PRIVATE") -> dict:
    """Clinic + one OPEN borrow ticket.

    For PUBLIC_FROM_PRIVATE the private lot lends to the public program
    (from_lot=private, to_lot=public); PRIVATE_FROM_PUBLIC mirrors it.
    """
    ctx = make_clinic(public_doses=public_doses, private_doses=private_doses)
    if direction == "PUBLIC_FROM_PRIVATE":
        from_lot, to_lot = ctx["priv_lot"]["id"], ctx["pub_lot_id"]
    else:
        from_lot, to_lot = ctx["pub_lot_id"], ctx["priv_lot"]["id"]
    ticket = make_borrow_ticket(
        ctx["site"]["id"], from_lot, to_lot, direction, borrow_qty
    )
    ctx.update({"ticket": ticket, "from_lot_id": from_lot, "to_lot_id": to_lot})
    return ctx


# --- Tier 6: transfers and audits ---------------------------------------------

def make_transfer(site_id, from_lot_id, destination_site_id, destination_unit_id,
                  quantity_doses, reason="short-dated, reallocate to high-volume site") -> dict:
    return get_success_data(
        api_client.create_short_date_transfer(
            site_id,
            create_transfer_payload(
                from_lot_id, destination_site_id, destination_unit_id,
                quantity_doses=quantity_doses, reason=reason,
            ),
            VM,
        )
    )


def make_audit(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_site_visit_audit(site_id, create_audit_payload(**overrides), CA)
    )


def begin_audit(site_id, audit_id) -> dict:
    return get_success_data(api_client.begin_audit(site_id, audit_id, CA))


def issue_findings(site_id, audit_id) -> dict:
    return get_success_data(api_client.issue_findings(site_id, audit_id, CA))


def make_audit_in_progress(site_id) -> dict:
    audit = make_audit(site_id)
    return begin_audit(site_id, audit["id"])


def make_audit_findings_issued(site_id) -> dict:
    audit = make_audit_in_progress(site_id)
    return issue_findings(site_id, audit["id"])
