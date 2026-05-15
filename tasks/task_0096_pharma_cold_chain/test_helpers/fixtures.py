"""Composite setup helpers — multi-step preambles tests can reuse.

The cold-chain pipeline is long: warehouse → zone(s) → bin(s) →
supplier → product → receipt → inspect → accept (mints Lot) → shipment
→ pick → pack → dispatch. Many test claims need the system in a
mid-pipeline state; these helpers reach those states with minimal
boilerplate.

IDENTITY THREADING — PRD §2.1:
  All five roles are OPAQUE. PRD §2.1 explicitly says the server does
  NOT compare X-User-ID to any entity's id. The shared-constant headers
  in test_users.TEST_USERS are therefore canonical.

  However, PRD §2.1 ALSO enforces segregation-of-duties by comparing
  the X-User-ID strings RECORDED on AuditLogEntry rows across two
  steps: the QAOfficer that accepts a receipt must differ from the
  X-User-ID that performed inspect; the QAOfficer that releases-from-
  quarantine must differ from the QAOfficer that quarantined; the
  RecallOfficer that announces a recall must differ from the QAOfficer
  X-User-ID that assessed any in-scope deviation. Fixtures therefore
  thread two distinct X-User-IDs through these chains by default — for
  example, the inspect step uses `receiver_headers` and the accept
  step uses `qa_officer_headers`, and release-from-quarantine uses
  `qa_officer_headers_alt` (different X-User-ID from the QAOfficer
  that performed the quarantine).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" with the underlying error_id
in the message — much clearer than an assertion failure on response
shape.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_scope_payload,
    assess_deviation_payload,
    clock_advance_payload,
    create_bin_payload,
    create_product_payload,
    create_receipt_payload,
    create_recall_payload,
    create_shipment_payload,
    create_supplier_payload,
    create_warehouse_payload,
    create_zone_payload,
    record_return_payload,
    temperature_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_qa_officer_headers,
    make_recall_officer_headers,
    make_receiver_headers,
)


# ===========================================================================
# Tier 1: Single-step atomic creates (all PRD §3.1 master data).
# ===========================================================================
def create_warehouse(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.create_warehouse(
        create_warehouse_payload(**overrides), headers,
    )
    return get_success_data(resp)


def create_zone(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.create_zone(
        warehouse_id, create_zone_payload(**overrides), headers,
    )
    return get_success_data(resp)


def create_bin(
    zone_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.create_bin(
        zone_id, create_bin_payload(**overrides), headers,
    )
    return get_success_data(resp)


def create_supplier(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.create_supplier(
        create_supplier_payload(**overrides), headers,
    )
    return get_success_data(resp)


def create_product(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.create_product(
        create_product_payload(**overrides), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1.5: Clock advance helper.
# ===========================================================================
def advance_clock(
    warehouse_id: str,
    minutes: int,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /warehouses/{wid}/_clock/advance — PRD §2.7."""
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.clock_advance(
        warehouse_id, clock_advance_payload(minutes=minutes), headers,
    )
    return get_success_data(resp)


def run_sweep(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.sweep_run(warehouse_id, headers)
    return get_success_data(resp)


def get_warehouse(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    return get_success_data(api_client.get_warehouse(warehouse_id, headers))


def get_zone(
    zone_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    return get_success_data(api_client.get_zone(zone_id, headers))


def get_bin(
    zone_id: str,
    bin_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch a specific bin via the zone's bin-list endpoint.

    PRD §4 does not declare a GET /bins/{id} endpoint; bin state is
    inspected through the zone's bin list.
    """
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.list_bins(zone_id, headers, params={"limit": 100})
    data = get_success_data(resp)
    for b in data:
        if b.get("id") == bin_id:
            return b
    return None


def get_receipt(
    receipt_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    return get_success_data(api_client.get_receipt(receipt_id, headers))


def get_lot(
    lot_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    return get_success_data(api_client.get_lot(lot_id, headers))


def get_shipment(
    shipment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["picker_headers"]
    return get_success_data(api_client.get_shipment(shipment_id, headers))


def get_deviation(
    deviation_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    return get_success_data(
        api_client.get_deviation(deviation_id, headers),
    )


def get_capa(
    capa_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    return get_success_data(api_client.get_capa(capa_id, headers))


def get_recall(
    recall_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["recall_officer_headers"]
    return get_success_data(api_client.get_recall(recall_id, headers))


def list_deviations(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    return get_success_data(
        api_client.list_deviations(warehouse_id, headers, params),
    )


def list_lots(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    return get_success_data(
        api_client.list_lots(warehouse_id, headers, params),
    )


def list_shipments(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["picker_headers"]
    return get_success_data(
        api_client.list_shipments(warehouse_id, headers, params),
    )


def list_external_events(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    return get_success_data(
        api_client.list_external_events(warehouse_id, headers, params),
    )


def list_audit_log(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    return get_success_data(
        api_client.list_audit_log(warehouse_id, headers, params),
    )


def list_capas(
    warehouse_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    return get_success_data(
        api_client.list_capas(warehouse_id, headers, params),
    )


# ===========================================================================
# Tier 2: Warehouse topology — minimum viable cold-chain topology.
# ===========================================================================
def setup_basic_topology(
    *,
    zone_type: str = "REFRIGERATED",
    bin_volume_units: int = 100,
    bin_weight_limit_kg: float = 500.0,
    special_storage_tag: Optional[str] = None,
    include_quarantine: bool = True,
) -> Dict[str, Any]:
    """Create a Warehouse + storage Zone Z + Bin B + optional QUARANTINE
    zone and bin. Returns dict with keys: warehouse, zone, bin,
    quarantine_zone, quarantine_bin (None if include_quarantine=False).

    Default product zone is REFRIGERATED with target 2..8 / alarm 0..10.
    """
    warehouse = create_warehouse()
    zone = create_zone(warehouse["id"], zone_type=zone_type)
    bin_overrides = {
        "volume_units": bin_volume_units,
        "weight_limit_kg": bin_weight_limit_kg,
    }
    if special_storage_tag is not None:
        bin_overrides["special_storage_tag"] = special_storage_tag
    binx = create_bin(zone["id"], **bin_overrides)

    quarantine_zone = None
    quarantine_bin = None
    if include_quarantine:
        quarantine_zone = create_zone(
            warehouse["id"], zone_type="QUARANTINE",
        )
        # Quarantine bins default to NONE special_storage_tag and
        # generous capacity so they can receive any non-conforming
        # routing.
        quarantine_bin = create_bin(
            quarantine_zone["id"],
            volume_units=1000,
            weight_limit_kg=10_000.0,
        )

    return {
        "warehouse": warehouse,
        "zone": zone,
        "bin": binx,
        "quarantine_zone": quarantine_zone,
        "quarantine_bin": quarantine_bin,
    }


def setup_qualified_supplier_and_product(
    *,
    required_zone_type: str = "REFRIGERATED",
    special_storage_tag: Optional[str] = None,
    qualification_expiry_minutes: Optional[int] = None,
    unit_weight_kg: float = 1.0,
    supplier_qualified: bool = True,
    product_qualified: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Register one qualified Supplier and one qualified Product whose
    required_zone_type matches the storage Zone in the basic topology.
    """
    supplier_kwargs: Dict[str, Any] = {
        "qualified": supplier_qualified,
    }
    if qualification_expiry_minutes is not None:
        supplier_kwargs["qualification_expiry_minutes"] = \
            qualification_expiry_minutes
    supplier = create_supplier(**supplier_kwargs)

    product_kwargs: Dict[str, Any] = {
        "required_zone_type": required_zone_type,
        "qualified": product_qualified,
        "unit_weight_kg": unit_weight_kg,
    }
    if special_storage_tag is not None:
        product_kwargs["special_storage_tag"] = special_storage_tag
    product = create_product(**product_kwargs)

    return supplier, product


# ===========================================================================
# Tier 3: Inbound receipt — through INSPECTED.
# ===========================================================================
def create_pending_receipt(
    warehouse_id: str,
    supplier_id: str,
    product_id: str,
    *,
    quantity_units: int = 10,
    expiry_minutes: Optional[int] = None,
    visual_pass: bool = True,
    carrier_logger_readings: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /warehouses/{wid}/receipts — born in PENDING_INSPECTION
    per PRD §3.2."""
    headers = headers or TEST_USERS["receiver_headers"]
    payload = create_receipt_payload(
        supplier_id=supplier_id,
        product_id=product_id,
        quantity_units=quantity_units,
        expiry_minutes=expiry_minutes,
        visual_pass=visual_pass,
        carrier_logger_readings=carrier_logger_readings,
        **overrides,
    )
    resp = api_client.create_receipt(warehouse_id, payload, headers)
    return get_success_data(resp)


def inspect_receipt(
    receipt_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["receiver_headers"]
    resp = api_client.inspect_receipt(receipt_id, headers, payload)
    return get_success_data(resp)


def create_inspected_receipt(
    warehouse_id: str,
    supplier_id: str,
    product_id: str,
    *,
    inspector_headers: Optional[Dict[str, str]] = None,
    quantity_units: int = 10,
    expiry_minutes: Optional[int] = None,
    visual_pass: bool = True,
    carrier_logger_readings: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Pipeline shortcut: create receipt + inspect it. Returns the
    INSPECTED receipt with temp_chain_intact and nonconformance_reason
    computed.
    """
    inspector_headers = inspector_headers or TEST_USERS["receiver_headers"]
    receipt = create_pending_receipt(
        warehouse_id, supplier_id, product_id,
        quantity_units=quantity_units,
        expiry_minutes=expiry_minutes,
        visual_pass=visual_pass,
        carrier_logger_readings=carrier_logger_readings,
        headers=inspector_headers,
        **overrides,
    )
    return inspect_receipt(receipt["id"], headers=inspector_headers)


# ===========================================================================
# Tier 4: Inbound accept / quarantine / release-from-quarantine — full
# QA branch with SOD-distinct actors threaded automatically.
# ===========================================================================
def accept_receipt(
    receipt_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """POST /receipts/{id}/accept — PRD §3.2. Default actor is the
    primary qa_officer; if the inspector was the receiver (the default
    in create_inspected_receipt) SOD is satisfied since the two
    X-User-IDs differ.
    """
    headers = headers or TEST_USERS["qa_officer_headers"]
    resp = api_client.accept_receipt(receipt_id, headers, payload)
    return get_success_data(resp)


def quarantine_receipt(
    receipt_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    resp = api_client.quarantine_receipt(receipt_id, headers, payload)
    return get_success_data(resp)


def release_receipt_from_quarantine(
    receipt_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """POST /receipts/{id}/release-from-quarantine — PRD §3.2.

    SOD: the X-User-ID of the QAOfficer that performed the QUARANTINE
    transition must differ from the X-User-ID that performs release.
    Default actor here is qa_officer_headers_alt so callers that used
    the primary qa_officer_headers for quarantine will satisfy SOD by
    default.
    """
    headers = headers or TEST_USERS["qa_officer_headers_alt"]
    resp = api_client.release_receipt_from_quarantine(
        receipt_id, headers, payload,
    )
    return get_success_data(resp)


def reject_receipt(
    receipt_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    resp = api_client.reject_receipt(receipt_id, headers, payload)
    return get_success_data(resp)


def _in_range_temp_for(required_zone_type: str) -> float:
    """Return a temperature value that lies inside the default target
    range for the given zone type — used so that
    carrier_logger_readings produces temp_chain_intact=True regardless
    of the product's required_zone_type."""
    midpoint_by_zone = {
        "FROZEN": (TEST_DEFAULTS["FROZEN_TARGET_LOW_C"]
                   + TEST_DEFAULTS["FROZEN_TARGET_HIGH_C"]) / 2,
        "REFRIGERATED": (TEST_DEFAULTS["REFRIGERATED_TARGET_LOW_C"]
                         + TEST_DEFAULTS["REFRIGERATED_TARGET_HIGH_C"]) / 2,
        "COOL": (TEST_DEFAULTS["COOL_TARGET_LOW_C"]
                 + TEST_DEFAULTS["COOL_TARGET_HIGH_C"]) / 2,
        "ROOM_TEMP": (TEST_DEFAULTS["ROOM_TEMP_TARGET_LOW_C"]
                      + TEST_DEFAULTS["ROOM_TEMP_TARGET_HIGH_C"]) / 2,
        # CONTROLLED_TEMP — wider band matching factories.create_zone_payload.
        "CONTROLLED_TEMP": 20.0,
    }
    return midpoint_by_zone.get(required_zone_type, 5.0)


def setup_accepted_lot(
    *,
    quantity_units: int = 10,
    bin_volume_units: int = 100,
    bin_weight_limit_kg: float = 500.0,
    special_storage_tag: Optional[str] = None,
    required_zone_type: str = "REFRIGERATED",
    expiry_minutes: Optional[int] = None,
    unit_weight_kg: float = 1.0,
) -> Dict[str, Any]:
    """Composite: build basic topology + qualified supplier/product +
    create + inspect + accept a receipt. Returns a dict carrying
    warehouse, zone, bin, quarantine_zone, quarantine_bin, supplier,
    product, receipt, lot.

    Inspector is receiver_headers; accepter is qa_officer_headers — SOD
    is satisfied by default.
    """
    topology = setup_basic_topology(
        zone_type=required_zone_type,
        bin_volume_units=bin_volume_units,
        bin_weight_limit_kg=bin_weight_limit_kg,
        special_storage_tag=special_storage_tag,
        include_quarantine=True,
    )
    supplier, product = setup_qualified_supplier_and_product(
        required_zone_type=required_zone_type,
        special_storage_tag=special_storage_tag,
        unit_weight_kg=unit_weight_kg,
    )
    # Carrier logger readings must lie inside the product's required
    # zone temperature band so inspection computes temp_chain_intact=True
    # and nonconformance_reason=NONE — otherwise accept will be blocked
    # by the nonconformance check (PRD §3.2 acceptance only when reason
    # is NONE).
    in_range_c = _in_range_temp_for(required_zone_type)
    readings = [
        {"minutes": 0, "temp_c": in_range_c},
        {"minutes": 1, "temp_c": in_range_c},
    ]
    receipt = create_inspected_receipt(
        topology["warehouse"]["id"],
        supplier["id"], product["id"],
        quantity_units=quantity_units,
        expiry_minutes=expiry_minutes,
        carrier_logger_readings=readings,
    )
    accepted = accept_receipt(
        receipt["id"], headers=TEST_USERS["qa_officer_headers"],
    )
    # Fetch lot via list-lots filtered by receipt's product, since the
    # accept response is the InboundReceipt with assigned_bin_id; the
    # minted Lot's id is recoverable from the lots list.
    lots = list_lots(
        topology["warehouse"]["id"],
        params={"product_id": product["id"], "limit": 100},
    )
    # Lot.receipt_id ties back to the originating receipt.
    lot = None
    for L in lots:
        if L.get("receipt_id") == receipt["id"]:
            lot = L
            break
    assert lot is not None, (
        f"Setup failed: lot for receipt {receipt['id']} not found in "
        f"lots listing"
    )
    return {
        **topology,
        "supplier": supplier,
        "product": product,
        "receipt": accepted,
        "lot": lot,
    }


# ===========================================================================
# Tier 5: Outbound shipment — through PICKED / PACKED / DISPATCHED.
# ===========================================================================
def create_planned_shipment(
    warehouse_id: str,
    product_id: str,
    *,
    quantity_units: int = 1,
    packaging_kind: str = "INSULATED_PCM",
    pick_temp_c: float = 5.0,
    vehicle_precondition_temp_c: float = 5.0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /warehouses/{wid}/shipments — born PLANNED."""
    headers = headers or TEST_USERS["picker_headers"]
    payload = create_shipment_payload(
        product_id=product_id,
        quantity_units=quantity_units,
        packaging_kind=packaging_kind,
        pick_temp_c=pick_temp_c,
        vehicle_precondition_temp_c=vehicle_precondition_temp_c,
        **overrides,
    )
    resp = api_client.create_shipment(warehouse_id, payload, headers)
    return get_success_data(resp)


def pick_shipment(
    shipment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["picker_headers"]
    resp = api_client.pick_shipment(shipment_id, headers, payload)
    return get_success_data(resp)


def pack_shipment(
    shipment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["picker_headers"]
    resp = api_client.pack_shipment(shipment_id, headers, payload)
    return get_success_data(resp)


def dispatch_shipment(
    shipment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["picker_headers"]
    resp = api_client.dispatch_shipment(shipment_id, headers, payload)
    return get_success_data(resp)


def cancel_shipment(
    shipment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["picker_headers"]
    resp = api_client.cancel_shipment(shipment_id, headers, payload)
    return get_success_data(resp)


def setup_picked_shipment(
    *,
    quantity_units: int = 1,
    accepted_quantity_units: int = 10,
    packaging_kind: str = "INSULATED_PCM",
    pick_temp_c: float = 5.0,
    vehicle_precondition_temp_c: float = 5.0,
    required_zone_type: str = "REFRIGERATED",
    special_storage_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Composite: setup_accepted_lot + create + pick shipment.
    Returns the accepted-lot dict augmented with shipment.
    """
    ctx = setup_accepted_lot(
        quantity_units=accepted_quantity_units,
        required_zone_type=required_zone_type,
        special_storage_tag=special_storage_tag,
    )
    shipment = create_planned_shipment(
        ctx["warehouse"]["id"], ctx["product"]["id"],
        quantity_units=quantity_units,
        packaging_kind=packaging_kind,
        pick_temp_c=pick_temp_c,
        vehicle_precondition_temp_c=vehicle_precondition_temp_c,
    )
    picked = pick_shipment(shipment["id"])
    return {**ctx, "shipment": picked}


def setup_packed_shipment(
    *,
    quantity_units: int = 1,
    accepted_quantity_units: int = 10,
    packaging_kind: str = "INSULATED_PCM",
    pick_temp_c: float = 5.0,
    vehicle_precondition_temp_c: float = 5.0,
    required_zone_type: str = "REFRIGERATED",
    special_storage_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Composite: setup_picked_shipment + pack the shipment.

    For REFRIGERATED/COOL/CONTROLLED_TEMP zone products, packaging_kind
    must be INSULATED_PCM per PRD §3.5.
    """
    ctx = setup_picked_shipment(
        quantity_units=quantity_units,
        accepted_quantity_units=accepted_quantity_units,
        packaging_kind=packaging_kind,
        pick_temp_c=pick_temp_c,
        vehicle_precondition_temp_c=vehicle_precondition_temp_c,
        required_zone_type=required_zone_type,
        special_storage_tag=special_storage_tag,
    )
    packed = pack_shipment(ctx["shipment"]["id"])
    return {**ctx, "shipment": packed}


def setup_dispatched_shipment(
    *,
    quantity_units: int = 1,
    accepted_quantity_units: int = 10,
    packaging_kind: str = "INSULATED_PCM",
    pick_temp_c: float = 5.0,
    vehicle_precondition_temp_c: float = 5.0,
    required_zone_type: str = "REFRIGERATED",
    special_storage_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Composite: setup_packed_shipment + dispatch."""
    ctx = setup_packed_shipment(
        quantity_units=quantity_units,
        accepted_quantity_units=accepted_quantity_units,
        packaging_kind=packaging_kind,
        pick_temp_c=pick_temp_c,
        vehicle_precondition_temp_c=vehicle_precondition_temp_c,
        required_zone_type=required_zone_type,
        special_storage_tag=special_storage_tag,
    )
    dispatched = dispatch_shipment(ctx["shipment"]["id"])
    return {**ctx, "shipment": dispatched}


# ===========================================================================
# Tier 6: Temperature events, deviations, and CAPAs.
# ===========================================================================
def record_temperature_event(
    zone_id: str,
    *,
    at_minutes: int,
    temp_c: float,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["warehouse_admin_headers"]
    resp = api_client.record_temperature_event(
        zone_id,
        temperature_event_payload(at_minutes=at_minutes, temp_c=temp_c),
        headers,
    )
    return get_success_data(resp)


def assess_deviation(
    deviation_id: str,
    *,
    qa_decision: str = "RELEASE",
    capa_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    resp = api_client.assess_deviation(
        deviation_id,
        assess_deviation_payload(qa_decision=qa_decision, capa_id=capa_id),
        headers,
    )
    return get_success_data(resp)


def complete_capa(
    capa_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["qa_officer_headers"]
    resp = api_client.complete_capa(capa_id, headers)
    return get_success_data(resp)


def trigger_alarm_high_and_recover(
    zone_id: str,
    warehouse_id: str,
    *,
    alarm_temp_c: float = 12.0,
    in_range_temp_c: float = 5.0,
    start_minutes: int = 1,
    duration_minutes_to_advance: int = 0,
) -> Dict[str, Any]:
    """Compose: post an ALARM_HIGH event, optionally advance the clock,
    then post an IN_RANGE event that closes the deviation.

    Returns the closed Deviation (status=CLOSED_PENDING_QA) with
    classification computed.

    PRD §3.3: a temperature event's `at_minutes` must lie in
    [clock_minutes - 1, clock_minutes]. The warehouse clock starts at 0,
    so to post an event at `at_minutes=start_minutes` (≥1) we must first
    advance the clock to at least `start_minutes`. If `start_minutes==0`
    we post immediately (range [-1, 0] permits 0).
    """
    # PRD §3.3 timing: advance the clock so that at_minutes=start_minutes
    # falls inside [clock-1, clock].
    if start_minutes > 0:
        advance_clock(warehouse_id, start_minutes)
    # First out-of-range event opens deviation.
    record_temperature_event(
        zone_id, at_minutes=start_minutes, temp_c=alarm_temp_c,
    )
    if duration_minutes_to_advance > 0:
        advance_clock(warehouse_id, duration_minutes_to_advance)
        # Re-send out-of-range while the clock has moved.
        record_temperature_event(
            zone_id,
            at_minutes=start_minutes + duration_minutes_to_advance,
            temp_c=alarm_temp_c,
        )
        recovery_minute = (
            start_minutes + duration_minutes_to_advance + 1
        )
    else:
        recovery_minute = start_minutes + 1
    advance_clock(warehouse_id, 1)
    record_temperature_event(
        zone_id, at_minutes=recovery_minute, temp_c=in_range_temp_c,
    )
    # Fetch the most recent deviation on this zone.
    deviations = list_deviations(warehouse_id)
    if not deviations:
        raise AssertionError(
            "Setup failed: expected at least one deviation row"
        )
    # Pick the most recent (largest started_at_minutes); tie-break on
    # created_at.
    deviations.sort(
        key=lambda d: (d.get("started_at_minutes", 0), d.get("created_at", "")),
    )
    return deviations[-1]


# ===========================================================================
# Tier 7: Recall lifecycle — create / scope / announce / notify /
# record-return / close.
# ===========================================================================
def create_draft_recall(
    warehouse_id: str,
    *,
    classification: str = "CLASS_II",
    reason: str = "Test recall",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["recall_officer_headers"]
    resp = api_client.create_recall(
        warehouse_id,
        create_recall_payload(classification=classification, reason=reason),
        headers,
    )
    return get_success_data(resp)


def add_recall_scope(
    recall_id: str,
    *,
    lot_id: str,
    units: int,
    scope_kind: str,
    shipment_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["recall_officer_headers"]
    resp = api_client.add_recall_scope(
        recall_id,
        add_scope_payload(
            lot_id=lot_id, units=units,
            scope_kind=scope_kind, shipment_id=shipment_id,
        ),
        headers,
    )
    return get_success_data(resp)


def announce_recall(
    recall_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["recall_officer_headers"]
    resp = api_client.announce_recall(recall_id, headers, payload)
    return get_success_data(resp)


def notify_next_customer(
    recall_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["recall_officer_headers"]
    resp = api_client.notify_next_customer(recall_id, headers, payload)
    return get_success_data(resp)


def record_recall_return(
    recall_id: str,
    *,
    scope_entry_id: str,
    units: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["recall_officer_headers"]
    resp = api_client.record_recall_return(
        recall_id,
        record_return_payload(
            scope_entry_id=scope_entry_id, units=units,
        ),
        headers,
    )
    return get_success_data(resp)


def close_recall(
    recall_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["recall_officer_headers"]
    resp = api_client.close_recall(recall_id, headers, payload)
    return get_success_data(resp)


# ===========================================================================
# Tier 8: Composite difficulty-design recipes — non-trivial preambles
# directly addressing SCAFFOLD_DIFFICULTY_DESIGN test recipes.
# ===========================================================================
def setup_two_planned_shipments_for_one_lot(
    *,
    accepted_quantity_units: int = 10,
    shipment_quantity_units: int = 6,
) -> Dict[str, Any]:
    """Difficulty-design rule_id=dual_variant_calc /
    fefo_pick_provisional_vs_final_on_shipment.

    Setup: warehouse + REFRIGERATED zone + bin + lot with 10 units +
    two PLANNED shipments S1, S2 each for 6 units of the same product.
    Used to demonstrate that provisional preview subtracts in-flight
    reservations whereas final pick sees the post-commit physical
    stock.
    """
    ctx = setup_accepted_lot(
        quantity_units=accepted_quantity_units,
    )
    s1 = create_planned_shipment(
        ctx["warehouse"]["id"], ctx["product"]["id"],
        quantity_units=shipment_quantity_units,
    )
    s2 = create_planned_shipment(
        ctx["warehouse"]["id"], ctx["product"]["id"],
        quantity_units=shipment_quantity_units,
    )
    return {**ctx, "shipment_1": s1, "shipment_2": s2}


def setup_shipped_shipment_then_recall(
    *,
    accepted_quantity_units: int = 10,
    shipment_quantity_units: int = 5,
    customer_id: str = "customer-recall-1",
) -> Dict[str, Any]:
    """Difficulty-design rule_id=transitive_cascade /
    recall_announce_cascades_to_lot_recalled_and_shipment_recall_tag.

    Build a dispatched shipment so the recall has a SHIPPED scope
    entry tying back to that customer_id; useful for
    notifications_required calculation.
    """
    ctx = setup_accepted_lot(quantity_units=accepted_quantity_units)
    shipment = create_planned_shipment(
        ctx["warehouse"]["id"], ctx["product"]["id"],
        quantity_units=shipment_quantity_units,
        customer_id=customer_id,
    )
    picked = pick_shipment(shipment["id"])
    packed = pack_shipment(picked["id"])
    dispatched = dispatch_shipment(packed["id"])
    return {**ctx, "shipment": dispatched, "customer_id": customer_id}


def setup_zone_in_frozen_posture(
    *,
    accepted_quantity_units: int = 10,
) -> Dict[str, Any]:
    """Drive a zone into FROZEN posture via an ALARM_HIGH event.

    Returns ctx augmented with `deviation` (CLOSED_PENDING_QA — not
    yet assessed; zone still FROZEN per PRD §2.10 since open
    deviations are gone but assessment hasn't happened — actually
    per PRD §2.10 the zone returns to OPEN only when all deviations
    on the zone reach CLOSED_ASSESSED). The zone remains FROZEN at
    return time because we leave the deviation in CLOSED_PENDING_QA.
    """
    ctx = setup_accepted_lot(quantity_units=accepted_quantity_units)
    # Drive zone into ALARM_HIGH then back to IN_RANGE so a deviation
    # is opened then closed-pending-QA. The zone remains FROZEN until
    # the deviation reaches CLOSED_ASSESSED.
    deviation = trigger_alarm_high_and_recover(
        ctx["zone"]["id"], ctx["warehouse"]["id"],
        alarm_temp_c=12.0, in_range_temp_c=5.0,
        start_minutes=1,
    )
    return {**ctx, "deviation": deviation}


def setup_deviation_at_duration_boundary(
    *,
    target_duration_minutes: int = 60,
) -> Dict[str, Any]:
    """Difficulty-design rule_id=boundary_precision_check /
    deviation_classification_at_60min_boundary.

    Open a deviation, advance the warehouse clock by
    `target_duration_minutes - 1` minutes while keeping the zone
    out-of-range, then close with an IN_RANGE event so that
    duration_minutes = ended_at - started_at + 1 = target_duration_minutes.

    duration = (started_at + target_duration_minutes - 1) - started_at + 1
             = target_duration_minutes.

    Returns ctx augmented with `deviation` (CLOSED_PENDING_QA).
    """
    ctx = setup_basic_topology()
    zone_id = ctx["zone"]["id"]
    warehouse_id = ctx["warehouse"]["id"]
    # First event opens deviation at minute 1 (clock_minutes==0,
    # at_minutes=0 to fit window).
    record_temperature_event(zone_id, at_minutes=0, temp_c=12.0)
    # Hold out-of-range across the target duration: post additional
    # ALARM events as we advance the clock so max_magnitude_c is
    # recorded; the deviation row's duration_minutes is
    # ended_at - started_at + 1.
    # Advance clock by (target_duration_minutes - 1) minutes.
    advance_clock(warehouse_id, target_duration_minutes - 1)
    record_temperature_event(
        zone_id, at_minutes=target_duration_minutes - 1, temp_c=12.0,
    )
    # Advance one more minute so the IN_RANGE event lies in the
    # current-minute window.
    advance_clock(warehouse_id, 1)
    record_temperature_event(
        zone_id, at_minutes=target_duration_minutes, temp_c=5.0,
    )
    deviations = list_deviations(warehouse_id)
    if not deviations:
        raise AssertionError(
            "Setup failed: deviation not created at duration boundary"
        )
    return {**ctx, "deviation": deviations[-1]}


def setup_zone_at_capacity_minus_quantity(
    *,
    zone_capacity_units: int = 10,
    pre_loaded_quantity_units: int = 8,
) -> Dict[str, Any]:
    """Difficulty-design rule_id=resource_temporal_overlap /
    zone_capacity_aggregate_overlap_capacity.

    Build: REFRIGERATED zone with capacity_units=zone_capacity_units;
    two bins each with volume_units=8; ACCEPT one receipt of
    pre_loaded_quantity_units units into bin B1 (zone.utilization_units
    becomes pre_loaded_quantity_units); leave a second receipt INSPECTED
    so a follow-on test can attempt to accept it and see the zone-
    capacity ceiling triggered.

    Returns ctx with warehouse, zone, bin_1, bin_2, supplier, product,
    receipt_inspected (already INSPECTED, ready for accept attempt).
    """
    warehouse = create_warehouse()
    zone = create_zone(
        warehouse["id"], zone_type="REFRIGERATED",
        capacity_units=zone_capacity_units,
    )
    bin_1 = create_bin(zone["id"], volume_units=8, weight_limit_kg=500.0)
    bin_2 = create_bin(zone["id"], volume_units=8, weight_limit_kg=500.0)
    quarantine_zone = create_zone(
        warehouse["id"], zone_type="QUARANTINE",
        capacity_units=1000,
    )
    quarantine_bin = create_bin(
        quarantine_zone["id"], volume_units=1000, weight_limit_kg=10_000.0,
    )
    supplier, product = setup_qualified_supplier_and_product(
        required_zone_type="REFRIGERATED",
    )
    receipt_loaded = create_inspected_receipt(
        warehouse["id"], supplier["id"], product["id"],
        quantity_units=pre_loaded_quantity_units,
    )
    accepted = accept_receipt(receipt_loaded["id"])
    receipt_inspected = create_inspected_receipt(
        warehouse["id"], supplier["id"], product["id"],
        quantity_units=pre_loaded_quantity_units,
    )
    return {
        "warehouse": warehouse,
        "zone": zone,
        "bin_1": bin_1,
        "bin_2": bin_2,
        "quarantine_zone": quarantine_zone,
        "quarantine_bin": quarantine_bin,
        "supplier": supplier,
        "product": product,
        "receipt_loaded": accepted,
        "receipt_inspected": receipt_inspected,
    }


def setup_two_inspected_receipts_for_single_bin(
    *,
    quantity_units: int = 10,
) -> Dict[str, Any]:
    """Difficulty-design rule_id=resource_temporal_overlap /
    bin_single_lot_occupancy_overlap_inclusive.

    Build: warehouse with exactly ONE AVAILABLE bin in a REFRIGERATED
    zone; two INSPECTED receipts both eligible for that one bin. Used
    for race tests on POST /receipts/{id}/accept against the same bin.
    """
    warehouse = create_warehouse()
    zone = create_zone(warehouse["id"], zone_type="REFRIGERATED")
    binx = create_bin(
        zone["id"], volume_units=100, weight_limit_kg=500.0,
    )
    quarantine_zone = create_zone(
        warehouse["id"], zone_type="QUARANTINE", capacity_units=1000,
    )
    create_bin(
        quarantine_zone["id"],
        volume_units=1000, weight_limit_kg=10_000.0,
    )
    supplier, product = setup_qualified_supplier_and_product(
        required_zone_type="REFRIGERATED",
    )
    r1 = create_inspected_receipt(
        warehouse["id"], supplier["id"], product["id"],
        quantity_units=quantity_units,
    )
    r2 = create_inspected_receipt(
        warehouse["id"], supplier["id"], product["id"],
        quantity_units=quantity_units,
    )
    return {
        "warehouse": warehouse,
        "zone": zone,
        "bin": binx,
        "supplier": supplier,
        "product": product,
        "receipt_1": r1,
        "receipt_2": r2,
    }


__all__ = [
    # Tier 1
    "create_warehouse",
    "create_zone",
    "create_bin",
    "create_supplier",
    "create_product",
    # Tier 1.5
    "advance_clock",
    "run_sweep",
    "get_warehouse",
    "get_zone",
    "get_bin",
    "get_receipt",
    "get_lot",
    "get_shipment",
    "get_deviation",
    "get_capa",
    "get_recall",
    "list_deviations",
    "list_lots",
    "list_shipments",
    "list_external_events",
    "list_audit_log",
    "list_capas",
    # Tier 2
    "setup_basic_topology",
    "setup_qualified_supplier_and_product",
    # Tier 3
    "create_pending_receipt",
    "inspect_receipt",
    "create_inspected_receipt",
    # Tier 4
    "accept_receipt",
    "quarantine_receipt",
    "release_receipt_from_quarantine",
    "reject_receipt",
    "setup_accepted_lot",
    # Tier 5
    "create_planned_shipment",
    "pick_shipment",
    "pack_shipment",
    "dispatch_shipment",
    "cancel_shipment",
    "setup_picked_shipment",
    "setup_packed_shipment",
    "setup_dispatched_shipment",
    # Tier 6
    "record_temperature_event",
    "assess_deviation",
    "complete_capa",
    "trigger_alarm_high_and_recover",
    # Tier 7
    "create_draft_recall",
    "add_recall_scope",
    "announce_recall",
    "notify_next_customer",
    "record_recall_return",
    "close_recall",
    # Tier 8 (difficulty-design recipes)
    "setup_two_planned_shipments_for_one_lot",
    "setup_shipped_shipment_then_recall",
    "setup_zone_in_frozen_posture",
    "setup_deviation_at_duration_boundary",
    "setup_zone_at_capacity_minus_quantity",
    "setup_two_inspected_receipts_for_single_bin",
]
