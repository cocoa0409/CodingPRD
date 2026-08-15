"""Composite setup helpers.

Each helper drives the real API through the PRD-declared endpoints and returns
plain dicts of created resources. Every test runs against a freshly booted
server (logical clock at its default), so helpers never assume leftover state
and never move the clock unless that is their explicit purpose.

All setup calls use the lenient get_success_data() validator so a setup
failure surfaces as a clear "Setup failed" error rather than an assertion
tangle.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .factories import (
    complete_payload,
    create_part_payload,
    create_property_payload,
    create_resident_payload,
    create_technician_payload,
    create_vendor_payload,
    create_work_order_payload,
    dispatch_payload,
    purchase_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_resident_headers,
    make_technician_headers,
    make_vendor_headers,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators
# ---------------------------------------------------------------------------

def create_property(name: str = "Test Property", **policy_overrides) -> dict:
    resp = api_client.create_property(create_property_payload(name=name, **policy_overrides), MANAGER)
    return get_success_data(resp, 201)


def create_resident(property_id: str, unit_number: str = "101",
                    full_name: str = "Resident One", email: str = "resident@example.com") -> dict:
    resp = api_client.create_resident(
        create_resident_payload(
            property_id=property_id, unit_number=unit_number,
            full_name=full_name, email=email,
        ),
        MANAGER,
    )
    return get_success_data(resp, 201)


def create_technician(property_id: str, full_name: str = "Tech One", trade: str = "PLUMBING") -> dict:
    resp = api_client.create_technician(
        create_technician_payload(property_id=property_id, full_name=full_name, trade=trade),
        MANAGER,
    )
    return get_success_data(resp, 201)


def create_vendor(property_id: str, company_name: str = "Vendor Co", trade: str = "PLUMBING",
                  insurance_valid_until: str = "2027-01-01T00:00:00Z") -> dict:
    resp = api_client.create_vendor(
        create_vendor_payload(
            property_id=property_id, company_name=company_name, trade=trade,
            insurance_valid_until=insurance_valid_until,
        ),
        MANAGER,
    )
    return get_success_data(resp, 201)


def create_part(property_id: str, sku: str = "SKU-1", name: str = "Part",
                unit_cost_cents: int = 100, reorder_level: int = 0,
                initial_stock: int = 0) -> dict:
    resp = api_client.create_part(
        create_part_payload(
            property_id=property_id, sku=sku, name=name,
            unit_cost_cents=unit_cost_cents, reorder_level=reorder_level,
            initial_stock=initial_stock,
        ),
        MANAGER,
    )
    return get_success_data(resp, 201)


def create_work_order(property_id: str, resident_id: str, category: str = "PLUMBING",
                      priority: str = "ROUTINE", description: str = "Test job") -> dict:
    """Filed by the owning resident (resident_id must equal the caller's X-User-ID)."""
    resp = api_client.create_work_order(
        create_work_order_payload(
            property_id=property_id, resident_id=resident_id, category=category,
            priority=priority, description=description,
        ),
        make_resident_headers(resident_id),
    )
    return get_success_data(resp, 201)


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER)
    return get_success_data(resp, 200)


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, DISPATCHER), 200)


def get_part(part_id: str) -> dict:
    return get_success_data(api_client.get_part(part_id, MANAGER), 200)


def get_resident(resident_id: str) -> dict:
    return get_success_data(api_client.get_resident(resident_id, MANAGER), 200)


def get_chargebacks_for_work_order(work_order_id: str) -> List[dict]:
    resp = api_client.list_chargebacks(MANAGER, params={"work_order_id": work_order_id})
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 1: work-order state progression
# ---------------------------------------------------------------------------

def dispatch_in_house(work_order_id: str, technician_id: str,
                      scheduled_start_at: str = DEFAULT_WINDOW_START,
                      scheduled_end_at: str = DEFAULT_WINDOW_END,
                      entry_authorization: str = "RESIDENT_CONSENT",
                      notice_posted_at: Optional[str] = None) -> dict:
    payload = dispatch_payload(
        assignment_type="IN_HOUSE",
        technician_id=technician_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        entry_authorization=entry_authorization,
    )
    if notice_posted_at is not None:
        payload["notice_posted_at"] = notice_posted_at
    resp = api_client.dispatch_work_order(work_order_id, payload, DISPATCHER)
    return get_success_data(resp, 200)


def dispatch_to_vendor(work_order_id: str, vendor_id: str,
                       scheduled_start_at: str = DEFAULT_WINDOW_START,
                       scheduled_end_at: str = DEFAULT_WINDOW_END,
                       entry_authorization: str = "RESIDENT_CONSENT",
                       notice_posted_at: Optional[str] = None) -> dict:
    payload = dispatch_payload(
        assignment_type="VENDOR",
        vendor_id=vendor_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        entry_authorization=entry_authorization,
    )
    if notice_posted_at is not None:
        payload["notice_posted_at"] = notice_posted_at
    resp = api_client.dispatch_work_order(work_order_id, payload, DISPATCHER)
    return get_success_data(resp, 200)


def start_as_technician(work_order_id: str, technician_id: str,
                        resident_consent_confirmed: bool = True) -> dict:
    resp = api_client.start_work_order(
        work_order_id,
        {"resident_consent_confirmed": resident_consent_confirmed},
        make_technician_headers(technician_id),
    )
    return get_success_data(resp, 200)


def start_as_vendor(work_order_id: str, vendor_id: str,
                    resident_consent_confirmed: bool = True) -> dict:
    resp = api_client.start_work_order(
        work_order_id,
        {"resident_consent_confirmed": resident_consent_confirmed},
        make_vendor_headers(vendor_id),
    )
    return get_success_data(resp, 200)


def sign_off(work_order_id: str, resident_id: str) -> dict:
    resp = api_client.sign_off_work_order(
        work_order_id, {}, make_resident_headers(resident_id)
    )
    return get_success_data(resp, 200)


def complete_as_technician(work_order_id: str, technician_id: str,
                           photo_urls: Optional[List[str]] = None,
                           damage_reported: bool = False,
                           estimated_damage_cost_cents: Optional[int] = None) -> dict:
    payload = complete_payload(
        photo_urls=photo_urls or ["https://example.com/photo-1.jpg"],
        damage_reported=damage_reported,
    )
    if estimated_damage_cost_cents is not None:
        payload["estimated_damage_cost_cents"] = estimated_damage_cost_cents
    resp = api_client.complete_work_order(
        work_order_id, payload, make_technician_headers(technician_id)
    )
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy bundles
# ---------------------------------------------------------------------------

def setup_property_resident_technician(property_name: str = "Test Property",
                                       unit_number: str = "101",
                                       trade: str = "PLUMBING",
                                       **policy_overrides) -> dict:
    """Property + one resident + one in-house technician of the given trade."""
    prop = create_property(property_name, **policy_overrides)
    resident = create_resident(prop["id"], unit_number=unit_number)
    technician = create_technician(prop["id"], trade=trade)
    return {"property": prop, "resident": resident, "technician": technician}


def setup_assigned_work_order(property_name: str = "Test Property",
                              category: str = "PLUMBING",
                              priority: str = "ROUTINE",
                              description: str = "Test job",
                              unit_number: str = "101",
                              window_start: str = DEFAULT_WINDOW_START,
                              window_end: str = DEFAULT_WINDOW_END,
                              entry_authorization: str = "RESIDENT_CONSENT",
                              **policy_overrides) -> dict:
    """Property + resident + technician + work order dispatched IN_HOUSE."""
    bundle = setup_property_resident_technician(
        property_name, unit_number=unit_number, trade=category, **policy_overrides
    )
    wo = create_work_order(
        bundle["property"]["id"], bundle["resident"]["id"],
        category=category, priority=priority, description=description,
    )
    wo = dispatch_in_house(
        wo["id"], bundle["technician"]["id"],
        scheduled_start_at=window_start, scheduled_end_at=window_end,
        entry_authorization=entry_authorization,
    )
    bundle["work_order"] = wo
    return bundle


def setup_in_progress_work_order(*args, **kwargs) -> dict:
    """Assigned bundle, then started by the assigned technician."""
    bundle = setup_assigned_work_order(*args, **kwargs)
    bundle["work_order"] = start_as_technician(
        bundle["work_order"]["id"], bundle["technician"]["id"]
    )
    return bundle


def setup_signed_off_work_order(*args, **kwargs) -> dict:
    """In-progress bundle with the reporting resident's sign-off recorded."""
    bundle = setup_in_progress_work_order(*args, **kwargs)
    bundle["work_order"] = sign_off(
        bundle["work_order"]["id"], bundle["resident"]["id"]
    )
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_completed_work_order(damage_reported: bool = False,
                               estimated_damage_cost_cents: Optional[int] = None,
                               photo_urls: Optional[List[str]] = None,
                               **kwargs) -> dict:
    """Full lifecycle through COMPLETED at the current logical clock.

    Returns the bundle plus "chargebacks" (the chargebacks of the work order;
    exactly one when damage_reported is true).
    """
    bundle = setup_signed_off_work_order(**kwargs)
    bundle["work_order"] = complete_as_technician(
        bundle["work_order"]["id"], bundle["technician"]["id"],
        photo_urls=photo_urls,
        damage_reported=damage_reported,
        estimated_damage_cost_cents=estimated_damage_cost_cents,
    )
    bundle["chargebacks"] = get_chargebacks_for_work_order(bundle["work_order"]["id"])
    return bundle


def setup_billed_chargeback(line_items: List[dict],
                            estimated_damage_cost_cents: int = 10000,
                            **kwargs) -> dict:
    """Completed damage work order whose PENDING chargeback is then BILLED.

    Returns the bundle plus "chargeback" (the billed chargeback).
    """
    bundle = setup_completed_work_order(
        damage_reported=True,
        estimated_damage_cost_cents=estimated_damage_cost_cents,
        **kwargs,
    )
    cb = bundle["chargebacks"][0]
    resp = api_client.chargeback_event(
        cb["id"], {"event_type": "BILL", "line_items": line_items}, MANAGER
    )
    bundle["chargeback"] = get_success_data(resp, 200)
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: parts and purchase helpers
# ---------------------------------------------------------------------------

def reserve_part(work_order_id: str, part_id: str, quantity: int,
                 caller_headers: dict) -> dict:
    resp = api_client.reserve_part(
        work_order_id, {"part_id": part_id, "quantity": quantity}, caller_headers
    )
    return get_success_data(resp, 201)


def create_purchase_request(work_order_id: str, part_id: str, quantity: int,
                            quoted_unit_cost_cents: int, expected_work_order_version: int,
                            caller_headers: dict,
                            shipping_fee_cents: int = 0) -> dict:
    resp = api_client.create_purchase_request(
        work_order_id,
        purchase_request_payload(
            part_id=part_id,
            quantity=quantity,
            quoted_unit_cost_cents=quoted_unit_cost_cents,
            shipping_fee_cents=shipping_fee_cents,
            expected_work_order_version=expected_work_order_version,
        ),
        caller_headers,
    )
    return get_success_data(resp, 201)


def current_work_order_version(work_order_id: str) -> int:
    """Read the live work-order version (OCC guard fields must match it)."""
    return get_work_order(work_order_id)["version"]


def get_purchase_request(purchase_request_id: str) -> dict:
    return get_success_data(api_client.get_purchase_request(purchase_request_id, MANAGER), 200)


def get_chargeback(chargeback_id: str) -> dict:
    return get_success_data(api_client.get_chargeback(chargeback_id, MANAGER), 200)
