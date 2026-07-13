"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so each helper builds
all of its preconditions from scratch using only PRD-declared endpoints. Setup
calls use the lenient get_success_data() validator so failures surface clearly.

Identity threading (PRD §2.1): Inspector/Establishment are entity-backed roles, so
ownership-gated calls use make_<role>_headers(entity_id) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
)
from . import factories

ADMIN = TEST_USERS["program_admin_headers"]


# --------------------------------------------------------------------------- #
# Logical clock (PRD §2.9)
# --------------------------------------------------------------------------- #
def set_clock(iso8601: str):
    get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADMIN))


# --------------------------------------------------------------------------- #
# Primitive entity creators
# --------------------------------------------------------------------------- #
def create_establishment(name="Test Establishment", jurisdiction="CA-01") -> dict:
    payload = factories.create_establishment_payload(name=name, jurisdiction=jurisdiction)
    return get_success_data(api_client.create_establishment(payload, ADMIN))


def create_inspector(full_name="Test Inspector", badge_number=None, region=None) -> dict:
    payload = factories.create_inspector_payload(full_name=full_name)
    if badge_number is not None:
        payload["badge_number"] = badge_number
    if region is not None:
        payload["region"] = region
    return get_success_data(api_client.create_inspector(payload, ADMIN))


def register_device(establishment_id, device_type="SCALE", serial_number=None,
                    device_class=None) -> dict:
    payload = factories.create_device_payload(establishment_id, device_type=device_type)
    if serial_number is not None:
        payload["serial_number"] = serial_number
    if device_class is not None:
        payload["device_class"] = device_class
    return get_success_data(api_client.create_device(payload, ADMIN))


def create_complaint(device_id, complainant_name="Test Complainant",
                     description="Device reads inaccurately.") -> dict:
    payload = factories.create_complaint_payload(
        device_id, complainant_name=complainant_name, description=description)
    return get_success_data(api_client.create_complaint(payload, ADMIN))


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def get_device(device_id) -> dict:
    return get_success_data(api_client.get_device(device_id, ADMIN))


def device_version(device_id) -> int:
    return get_device(device_id)["version"]


def get_establishment(establishment_id) -> dict:
    return get_success_data(api_client.get_establishment(establishment_id, ADMIN))


def get_inspection(inspection_id) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, ADMIN))


def penalties_for_device(device_id) -> list:
    return get_success_data(api_client.list_penalties(ADMIN, {"device_id": device_id}))


def first_penalty_for_device(device_id):
    lst = penalties_for_device(device_id)
    return lst[0] if lst else None


def seals_for_device(device_id) -> list:
    return get_success_data(api_client.list_seals(ADMIN, {"device_id": device_id}))


def first_seal_for_device(device_id):
    lst = seals_for_device(device_id)
    return lst[0] if lst else None


def condemnations_for_device(device_id) -> list:
    return get_success_data(api_client.list_condemnations(ADMIN, {"device_id": device_id}))


def first_condemnation_for_device(device_id):
    lst = condemnations_for_device(device_id)
    return lst[0] if lst else None


def fee_invoices_for_device(device_id) -> list:
    return get_success_data(api_client.list_fee_invoices(ADMIN, {"device_id": device_id}))


def first_fee_invoice_for_device(device_id):
    lst = fee_invoices_for_device(device_id)
    return lst[0] if lst else None


# --------------------------------------------------------------------------- #
# Inspection lifecycle steps (entity-backed Inspector identity threaded)
# --------------------------------------------------------------------------- #
def schedule_inspection(device_id, inspector_id, scheduled_start, scheduled_end,
                        inspection_type="ACCURACY_TEST", expected_device_version=None,
                        complaint_id=None, headers=None) -> dict:
    if expected_device_version is None:
        expected_device_version = device_version(device_id)
    payload = {
        "device_id": device_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_device_version": expected_device_version,
    }
    if complaint_id is not None:
        payload["complaint_id"] = complaint_id
    hdr = headers if headers is not None else make_inspector_headers(inspector_id)
    return get_success_data(api_client.create_inspection(payload, hdr))


def start_inspection(inspection_id, inspector_id) -> dict:
    return get_success_data(
        api_client.start_inspection(inspection_id, make_inspector_headers(inspector_id)))


def add_reading(inspection_id, inspector_id, applied_load, indicated_value) -> dict:
    payload = factories.create_test_reading_payload(applied_load, indicated_value)
    return get_success_data(
        api_client.create_test_reading(inspection_id, payload, make_inspector_headers(inspector_id)))


def add_audit_item(inspection_id, inspector_id, item_sku, posted_price_cents,
                   scanned_price_cents) -> dict:
    payload = factories.create_audit_item_payload(item_sku, posted_price_cents, scanned_price_cents)
    return get_success_data(
        api_client.create_audit_item(inspection_id, payload, make_inspector_headers(inspector_id)))


def finalize_inspection(inspection_id, inspector_id) -> dict:
    return get_success_data(
        api_client.finalize_inspection(inspection_id, make_inspector_headers(inspector_id)))


# --------------------------------------------------------------------------- #
# Composite lifecycle shortcuts
# --------------------------------------------------------------------------- #
def in_progress_accuracy(inspector, device, scheduled_start, scheduled_end,
                         applied_load=3000, indicated_value=3004) -> dict:
    """Schedule an accuracy inspection on `device`, start it, record ONE reading.
    Returns the (IN_PROGRESS) inspection. Device left un-finalized."""
    ins = schedule_inspection(
        device["id"], inspector["id"], scheduled_start, scheduled_end,
        inspection_type="ACCURACY_TEST")
    start_inspection(ins["id"], inspector["id"])
    add_reading(ins["id"], inspector["id"], applied_load, indicated_value)
    return ins


def accuracy_pass_seal(inspector, device, scheduled_start, scheduled_end,
                       applied_load=3000, indicated_value=3000) -> dict:
    """Full clean accuracy pass that seals `device`. Returns the refreshed device."""
    ins = in_progress_accuracy(inspector, device, scheduled_start, scheduled_end,
                               applied_load, indicated_value)
    finalize_inspection(ins["id"], inspector["id"])
    return get_device(device["id"])


def accuracy_fail_condemn(inspector, device, scheduled_start, scheduled_end,
                          applied_load=3000, indicated_value=3004) -> dict:
    """Full accuracy fail that condemns `device`. Returns the refreshed device."""
    ins = in_progress_accuracy(inspector, device, scheduled_start, scheduled_end,
                               applied_load, indicated_value)
    finalize_inspection(ins["id"], inspector["id"])
    return get_device(device["id"])


def in_progress_price(inspector, device, scheduled_start, scheduled_end, items) -> dict:
    """Schedule a PRICE_VERIFICATION inspection, start it, record each item in `items`
    (list of (sku, posted, scanned) tuples). Returns the (IN_PROGRESS) inspection."""
    ins = schedule_inspection(
        device["id"], inspector["id"], scheduled_start, scheduled_end,
        inspection_type="PRICE_VERIFICATION")
    start_inspection(ins["id"], inspector["id"])
    for sku, posted, scanned in items:
        add_audit_item(ins["id"], inspector["id"], sku, posted, scanned)
    return ins


def bootstrap_est_inspector(est_name="Test Store", jurisdiction="CA-01",
                            inspector_name="Test Inspector"):
    """Most common preamble: one establishment + one inspector. Returns (est, inspector)."""
    est = create_establishment(name=est_name, jurisdiction=jurisdiction)
    inspector = create_inspector(full_name=inspector_name)
    return est, inspector
