"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty database)
before every test. Setup calls use get_success_data() (lenient) so failures
surface as clear "Setup failed" messages rather than assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_aircraft_payload,
    create_checklist_item_payload,
    create_directive_payload,
    create_hangar_slot_payload,
    create_labor_entry_payload,
    create_logbook_entry_payload,
    create_mechanic_payload,
    create_owner_payload,
    create_part_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS, make_mechanic_headers, make_owner_headers

SM = TEST_USERS["shop_manager_headers"]
PC = TEST_USERS["parts_clerk_headers"]


def reset_clock(to_iso8601: str = LOGICAL_CLOCK_START):
    """Pin the shop logical clock; startup default is 2026-08-01T00:00:00Z."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, SM)
    get_success_data(res)


# ─── Tier 1: principals ────────────────────────────────


def create_owner(**overrides):
    """Register an owner. Returns the Owner dict."""
    return get_success_data(api_client.create_owner(create_owner_payload(**overrides), SM))


def create_mechanic(**overrides):
    """Register a mechanic. Returns the Mechanic dict."""
    return get_success_data(
        api_client.create_mechanic(create_mechanic_payload(**overrides), SM)
    )


def create_aircraft(owner_id: str, **overrides):
    """Register an aircraft. Returns the Aircraft dict."""
    return get_success_data(
        api_client.create_aircraft(create_aircraft_payload(owner_id, **overrides), SM)
    )


def create_slot(aircraft_id: str, **overrides):
    """Reserve a hangar slot. Returns the HangarSlot dict."""
    return get_success_data(
        api_client.create_hangar_slot(create_hangar_slot_payload(aircraft_id, **overrides), SM)
    )


# ─── Tier 2: work-order bootstrapping ──────────────────


def create_work_order(
    aircraft_id: str,
    slot: dict,
    mechanic_id: str,
    **overrides,
):
    """Open a work order against a slot, threading the slot's current version
    into the optimistic-concurrency field. Returns the WorkOrder dict."""
    payload = create_work_order_payload(
        aircraft_id,
        slot["id"],
        mechanic_id,
        expected_hangar_slot_version=slot["version"],
        **overrides,
    )
    return get_success_data(api_client.create_work_order(payload, SM))


def setup_shop(
    owner_cap: int = TEST_DEFAULTS["APPROVAL_CAP_CENTS"],
    slot_overrides: dict | None = None,
    pricing_mode: str = "HOURLY",
    scope_type: str = "ANNUAL",
    mechanic_class: str = "IA",
):
    """Owner + aircraft + mechanic + slot + DRAFT work order.

    Returns (owner, aircraft, mechanic, slot, work_order).
    """
    reset_clock()
    owner = create_owner(approval_cap_cents=owner_cap)
    aircraft = create_aircraft(owner["id"])
    mechanic = create_mechanic(certificate_class=mechanic_class)
    slot = create_slot(aircraft["id"], **(slot_overrides or {}))
    wo = create_work_order(
        aircraft["id"],
        slot,
        mechanic["id"],
        pricing_mode=pricing_mode,
        scope_type=scope_type,
    )
    return owner, aircraft, mechanic, slot, wo


def start_work_order(wo: dict, mechanic: dict):
    """Schedule then start a work order. Returns the IN_PROGRESS WorkOrder."""
    get_success_data(api_client.schedule_work_order(wo["id"], SM))
    started = api_client.start_work_order(wo["id"], make_mechanic_headers(mechanic["id"]))
    return get_success_data(started)


def add_checklist_item(wo_id: str, mechanic: dict, **overrides):
    """Add a checklist item. Returns the ChecklistItem dict."""
    return get_success_data(
        api_client.create_checklist_item(
            wo_id, create_checklist_item_payload(**overrides), make_mechanic_headers(mechanic["id"])
        )
    )


def record_checklist_item(wo_id: str, item_id: str, mechanic: dict, result: str):
    """Record PASS/FAIL/NA on a checklist item. Returns the updated item."""
    return get_success_data(
        api_client.record_checklist_item(
            wo_id,
            item_id,
            {"result": result, "inspected_by_mechanic_id": mechanic["id"]},
            make_mechanic_headers(mechanic["id"]),
        )
    )


def post_labor_entry(wo_id: str, mechanic: dict, **overrides):
    """Post a labor entry. Returns the LaborEntry dict."""
    overrides.setdefault("mechanic_id", mechanic["id"])
    return get_success_data(
        api_client.create_labor_entry(
            wo_id, create_labor_entry_payload(**overrides), make_mechanic_headers(mechanic["id"])
        )
    )


# ─── Tier 3: inspection pipeline ───────────────────────


def setup_wo_with_failed_inspection(
    owner_cap: int = TEST_DEFAULTS["APPROVAL_CAP_CENTS"],
    pricing_mode: str = "HOURLY",
    scope_type: str = "ANNUAL",
    slot_overrides: dict | None = None,
):
    """Drive a WO through: create -> schedule -> start -> one FAIL checklist
    item -> complete-inspection -> submit-for-approval.

    With the default (high) cap the auto-created discrepancy is under-cap and
    lands APPROVED, leaving the WO auto-advanced to APPROVED. With a low cap
    the discrepancy lands PENDING_OWNER_DECISION and the WO stands in
    AWAITING_OWNER_APPROVAL.

    Returns (owner, aircraft, mechanic, slot, wo, discrepancy).
    """
    owner, aircraft, mechanic, slot, wo = setup_shop(
        owner_cap=owner_cap, pricing_mode=pricing_mode, scope_type=scope_type,
        slot_overrides=slot_overrides,
    )
    mech_h = make_mechanic_headers(mechanic["id"])
    wo = start_work_order(wo, mechanic)
    item = add_checklist_item(wo["id"], mechanic)
    record_checklist_item(wo["id"], item["id"], mechanic, "FAIL")
    get_success_data(api_client.complete_inspection(wo["id"], mech_h))
    get_success_data(api_client.submit_for_approval(wo["id"], mech_h))
    discrepancies = get_success_data(
        api_client.list_work_order_discrepancies(wo["id"], mech_h)
    )
    discrepancy = discrepancies[0]
    return owner, aircraft, mechanic, slot, wo, discrepancy


def rectify_and_verify(
    wo_id: str,
    discrepancy_id: str,
    rectifying_mechanic: dict,
    verifying_mechanic: dict,
):
    """Rectify an APPROVED discrepancy then verify it with a second mechanic."""
    get_success_data(
        api_client.rectify_discrepancy(
            discrepancy_id, make_mechanic_headers(rectifying_mechanic["id"])
        )
    )
    return get_success_data(
        api_client.verify_discrepancy(
            discrepancy_id,
            {"outcome": "PASS", "verified_by_mechanic_id": verifying_mechanic["id"]},
            make_mechanic_headers(verifying_mechanic["id"]),
        )
    )


def setup_wo_ready_for_rts(
    owner_cap: int = TEST_DEFAULTS["APPROVAL_CAP_CENTS"],
    pricing_mode: str = "HOURLY",
    scope_type: str = "ANNUAL",
    slot_overrides: dict | None = None,
):
    """Drive a WO all the way to READY_FOR_RTS:
    FAIL inspection -> submit (auto-approve under cap) -> rectify -> verify ->
    begin-work -> ready-for-rts.

    Returns (owner, aircraft, mechanic, verifier, slot, wo).
    """
    owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection(
        owner_cap=owner_cap, pricing_mode=pricing_mode, scope_type=scope_type,
        slot_overrides=slot_overrides,
    )
    mech_h = make_mechanic_headers(mechanic["id"])
    verifier = create_mechanic(certificate_class="IA")
    rectify_and_verify(wo["id"], discrepancy["id"], mechanic, verifier)
    get_success_data(api_client.begin_work(wo["id"], mech_h))
    get_success_data(api_client.ready_for_rts(wo["id"], mech_h))
    return owner, aircraft, mechanic, verifier, slot, wo


def setup_wo_returned_to_service(
    owner_cap: int = TEST_DEFAULTS["APPROVAL_CAP_CENTS"],
    pricing_mode: str = "HOURLY",
    scope_type: str = "ANNUAL",
    slot_overrides: dict | None = None,
):
    """Full lifecycle through RETURNED_TO_SERVICE with an auto-created DRAFT
    invoice: adds the RTS_STATEMENT logbook entry then returns to service.

    Returns (owner, aircraft, mechanic, verifier, slot, wo, invoice).
    """
    owner, aircraft, mechanic, verifier, slot, wo = setup_wo_ready_for_rts(
        owner_cap=owner_cap, pricing_mode=pricing_mode, scope_type=scope_type,
        slot_overrides=slot_overrides,
    )
    mech_h = make_mechanic_headers(mechanic["id"])
    get_success_data(
        api_client.create_logbook_entry(
            create_logbook_entry_payload(aircraft["id"], wo["id"], mechanic["id"]),
            mech_h,
        )
    )
    get_success_data(api_client.return_to_service(wo["id"], mech_h))
    invoices = get_success_data(api_client.get_work_order_invoice(wo["id"], SM))
    invoice = invoices[0]
    return owner, aircraft, mechanic, verifier, slot, wo, invoice


# ─── Tier 4: parts pipeline ────────────────────────────


def request_part(discrepancy_id: str, mechanic: dict, **overrides):
    """Request a part against a discrepancy. Returns the Part dict."""
    return get_success_data(
        api_client.create_part(
            create_part_payload(discrepancy_id, **overrides),
            make_mechanic_headers(mechanic["id"]),
        )
    )


def source_and_receive_part(part_id: str):
    """Mark a part SOURCED then RECEIVED. Returns the RECEIVED Part dict."""
    get_success_data(api_client.mark_part_sourced(part_id, PC))
    return get_success_data(api_client.receive_part(part_id, PC))


def install_part(part_id: str, mechanic: dict):
    """Install a RECEIVED part. Returns the INSTALLED Part dict."""
    return get_success_data(
        api_client.install_part(part_id, make_mechanic_headers(mechanic["id"]))
    )
