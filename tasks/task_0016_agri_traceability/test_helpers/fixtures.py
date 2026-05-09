"""Composite setup helpers for the Agri-Traceability API.

Identity-threading rule (PRD §2.1):
  - Grower is entity_backed: PlantingBatch.grower_id is captured from the
    creator's X-User-ID. Subsequent owner-gated calls (record application,
    record harvest, mint QR) must use make_grower_headers(<that grower_id>).
  - Distributor is entity_backed: LogisticsLeg.acknowledge requires
    X-User-ID == LogisticsLeg.to_party_id, and disposal requires the body's
    distributor_id == X-User-ID. Fixtures that build legs use the freshly
    registered Distributor.id as to_party_id and acknowledge with
    make_distributor_headers(<that Distributor.id>).
  - Inspector / RegulatoryOfficer / LogisticsOperator / Consumer identities
    are opaque — shared TEST_USERS constants are canonical for them.

All fixtures use get_success_data() (lenient) so setup failures yield clear
"Setup failed" errors, not noisy assertion failures.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_registry_payload,
    create_planting_batch_payload,
    create_agrochemical_application_payload,
    create_harvest_record_payload,
    create_storage_bin_payload,
    create_logistics_leg_payload,
    create_sensor_reading_payload,
    create_inspection_report_payload,
    create_distributor_payload,
    create_recall_payload,
    create_disposal_payload,
    unique_batch_code,
    unique_bin_code,
    unique_pesticide_registration_no,
    unique_idempotency_key,
)
from .test_users import (
    DEFAULT_GROWER_ID,
    DEFAULT_GROWER_ID_ALT,
    DEFAULT_DISTRIBUTOR_ID,
    TEST_USERS,
    make_grower_headers,
    make_distributor_headers,
    make_inspector_headers,
    make_regulatory_headers,
    make_logistics_headers,
    make_consumer_headers,
)


# Convenient handles -----------------------------------------------------------

REGULATORY_HEADERS = TEST_USERS["regulatory_headers"]
INSPECTOR_HEADERS = TEST_USERS["inspector_headers"]
LOGISTICS_HEADERS = TEST_USERS["logistics_headers"]
CONSUMER_HEADERS = TEST_USERS["consumer_headers"]


# ─── Tier 0: Primitive setup steps ──────────────────────────────────────────

def create_pesticide_registry_entry(
    *,
    registration_no: Optional[str] = None,
    withdrawal_period_days: int = 14,
    max_dosage_per_hectare_g: float = 200.0,
    prohibited: bool = False,
    prohibited_since: Optional[str] = None,
    category: str = "PESTICIDE",
    product_name: str = "Test Pesticide",
) -> Dict[str, Any]:
    """Create a PesticideRegistry row as RegulatoryOfficer."""
    payload: Dict[str, Any] = {
        "registration_no": registration_no or unique_pesticide_registration_no(),
        "product_name": product_name,
        "category": category,
        "withdrawal_period_days": withdrawal_period_days,
        "max_dosage_per_hectare_g": max_dosage_per_hectare_g,
    }
    if prohibited:
        payload["prohibited"] = True
        if prohibited_since is not None:
            payload["prohibited_since"] = prohibited_since
    elif prohibited_since is not None:
        payload["prohibited_since"] = prohibited_since
    res = api_client.create_registry(payload, REGULATORY_HEADERS)
    return get_success_data(res)


def create_storage_bin(
    *,
    capacity_kg: float = 1000.0,
    warehouse_zone: str = "COLD",
    bin_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a StorageBin as LogisticsOperator."""
    payload = create_storage_bin_payload(
        capacity_kg=capacity_kg,
        warehouse_zone=warehouse_zone,
        bin_code=bin_code or unique_bin_code(),
    )
    res = api_client.create_storage_bin(payload, LOGISTICS_HEADERS)
    return get_success_data(res)


def create_distributor(
    *,
    name: str = "Test Distributor",
    tier: str = "WHOLESALE",
) -> Dict[str, Any]:
    """Create a Distributor as RegulatoryOfficer."""
    payload = create_distributor_payload(name=name, tier=tier)
    res = api_client.create_distributor(payload, REGULATORY_HEADERS)
    return get_success_data(res)


# ─── Tier 1: PlantingBatch state progression ────────────────────────────────

def create_planting_batch(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    **payload_overrides,
) -> Dict[str, Any]:
    """Create a PlantingBatch in REGISTERED with grower_id captured from grower headers.

    PRD §3.2: "The registering grower's `X-User-ID` is captured as `grower_id`
    on the batch." So we mint headers whose X-User-ID == grower_id, post the
    batch, and the response is the batch in REGISTERED.
    """
    headers = make_grower_headers(grower_id)
    payload = create_planting_batch_payload(**payload_overrides)
    res = api_client.create_planting_batch(payload, headers)
    return get_success_data(res)


def declare_growing(batch: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.2: explicit advance from REGISTERED to GROWING (no body)."""
    headers = make_grower_headers(batch["grower_id"])
    res = api_client.declare_growing(batch["id"], headers)
    return get_success_data(res)


def record_application(
    batch: Dict[str, Any],
    *,
    registration_no: str,
    application_date: str = "2026-02-01T00:00:00.000Z",
    dosage_g_per_hectare: float = 50.0,
) -> Dict[str, Any]:
    """Record an AgrochemicalApplication on a batch as the owning grower."""
    headers = make_grower_headers(batch["grower_id"])
    payload = create_agrochemical_application_payload(
        registration_no=registration_no,
        application_date=application_date,
        dosage_g_per_hectare=dosage_g_per_hectare,
    )
    res = api_client.create_agrochemical_application(batch["id"], payload, headers)
    return get_success_data(res)


def record_harvest(
    batch: Dict[str, Any],
    bin_id: str,
    *,
    harvest_date: str = "2026-04-15T00:00:00.000Z",
    quantity_kg: float = 50.0,
    quality_grade: str = "A",
    packaging_spec: str = "5kg-carton-ventilated",
) -> Dict[str, Any]:
    """Record a HarvestRecord on a batch as the owning grower."""
    headers = make_grower_headers(batch["grower_id"])
    payload = create_harvest_record_payload(
        bin_id,
        harvest_date=harvest_date,
        quantity_kg=quantity_kg,
        quality_grade=quality_grade,
        packaging_spec=packaging_spec,
    )
    res = api_client.create_harvest_record(batch["id"], payload, headers)
    return get_success_data(res)


def mint_qr(batch: Dict[str, Any], harvest_record: Dict[str, Any]) -> Dict[str, Any]:
    """Mint the QR for a HarvestRecord as the owning grower."""
    headers = make_grower_headers(batch["grower_id"])
    res = api_client.mint_qr_code(harvest_record["id"], headers)
    return get_success_data(res)


# ─── Tier 2: Inspection lifecycle ───────────────────────────────────────────

def create_draft_inspection(
    batch: Dict[str, Any],
    *,
    inspector_id: str = "user-inspector-001",
    test_items: Optional[List[str]] = None,
    pesticide_residue_mg_per_kg: Optional[float] = None,
    heavy_metals_mg_per_kg: Optional[float] = None,
    microorganism_cfu_per_g: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a DRAFT InspectionReport.

    PRD §3.5 requires inspector_id != batch.grower_id at issuance time. This
    helper lets the caller choose any inspector_id, defaulting to one that
    differs from DEFAULT_GROWER_ID.
    """
    headers = make_inspector_headers(inspector_id)
    if test_items is None:
        test_items = ["PESTICIDE_RESIDUE", "HEAVY_METALS", "MICROORGANISMS"]
    overrides: Dict[str, Any] = {}
    if pesticide_residue_mg_per_kg is not None:
        overrides["pesticide_residue_mg_per_kg"] = pesticide_residue_mg_per_kg
    if heavy_metals_mg_per_kg is not None:
        overrides["heavy_metals_mg_per_kg"] = heavy_metals_mg_per_kg
    if microorganism_cfu_per_g is not None:
        overrides["microorganism_cfu_per_g"] = microorganism_cfu_per_g
    payload = create_inspection_report_payload(test_items=test_items, **overrides)
    res = api_client.create_inspection_report(batch["id"], payload, headers)
    return get_success_data(res)


def issue_inspection(
    report: Dict[str, Any],
    *,
    inspector_id: str = "user-inspector-001",
) -> Dict[str, Any]:
    """Issue the report. Inspector identity controls segregation-of-duties."""
    headers = make_inspector_headers(inspector_id)
    res = api_client.issue_inspection(report["id"], headers)
    return get_success_data(res)


def revoke_inspection(report: Dict[str, Any]) -> Dict[str, Any]:
    """Revoke an issued report (RegulatoryOfficer-only)."""
    res = api_client.revoke_inspection(report["id"], REGULATORY_HEADERS)
    return get_success_data(res)


# ─── Tier 3: Cross-entity scenarios ─────────────────────────────────────────

def setup_batch_growing(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    **batch_overrides,
) -> Dict[str, Any]:
    """REGISTERED -> declare-growing -> GROWING."""
    batch = create_planting_batch(grower_id=grower_id, **batch_overrides)
    return declare_growing(batch)


def setup_batch_harvested(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    capacity_kg: float = 1000.0,
    quantity_kg: float = 50.0,
    quality_grade: str = "A",
    **batch_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk a batch to HARVESTED. Returns (batch, bin, harvest)."""
    batch = setup_batch_growing(grower_id=grower_id, **batch_overrides)
    bin_obj = create_storage_bin(capacity_kg=capacity_kg)
    harvest = record_harvest(
        batch, bin_obj["id"],
        quantity_kg=quantity_kg,
        quality_grade=quality_grade,
    )
    # Refresh batch
    batch = get_success_data(
        api_client.get_planting_batch(batch["id"], make_grower_headers(grower_id))
    )
    return batch, bin_obj, harvest


def setup_batch_inspected_pass(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    inspector_id: str = "user-inspector-001",
    capacity_kg: float = 1000.0,
    quantity_kg: float = 50.0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk a batch to INSPECTED_PASS. Returns (batch, bin, harvest, report)."""
    batch, bin_obj, harvest = setup_batch_harvested(
        grower_id=grower_id, capacity_kg=capacity_kg, quantity_kg=quantity_kg
    )
    draft = create_draft_inspection(
        batch,
        inspector_id=inspector_id,
        test_items=["PESTICIDE_RESIDUE", "HEAVY_METALS", "MICROORGANISMS"],
        pesticide_residue_mg_per_kg=0.10,
        heavy_metals_mg_per_kg=0.05,
        microorganism_cfu_per_g=10000,
    )
    report = issue_inspection(draft, inspector_id=inspector_id)
    batch = get_success_data(
        api_client.get_planting_batch(batch["id"], make_grower_headers(grower_id))
    )
    return batch, bin_obj, harvest, report


def setup_batch_with_qr_inspected_pass(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    inspector_id: str = "user-inspector-001",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """INSPECTED_PASS + minted QR. Returns (batch, bin, harvest, report, qr)."""
    batch, bin_obj, harvest, report = setup_batch_inspected_pass(
        grower_id=grower_id, inspector_id=inspector_id
    )
    qr = mint_qr(batch, harvest)
    return batch, bin_obj, harvest, report, qr


def setup_logistics_leg_planned(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    inspector_id: str = "user-inspector-001",
    distributor_id: Optional[str] = None,
    leg_index: int = 1,
    depart_at: str = "2026-04-20T00:00:00.000Z",
    arrive_at: str = "2026-04-21T00:00:00.000Z",
    temperature_min_c: float = 2.0,
    temperature_max_c: float = 4.0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Set up batch through INSPECTED_PASS + QR, register a distributor, plan one leg.

    The leg's `to_party_id` is the freshly-registered Distributor.id. Tests
    that need to acknowledge the leg must therefore use
    make_distributor_headers(distributor["id"]).

    Returns (batch, leg, distributor).
    """
    batch, _bin, _harvest, _report, _qr = setup_batch_with_qr_inspected_pass(
        grower_id=grower_id, inspector_id=inspector_id
    )
    if distributor_id is None:
        distributor = create_distributor()
    else:
        distributor = create_distributor(name=f"Distributor for {distributor_id}")
    payload = create_logistics_leg_payload(
        leg_index=leg_index,
        from_party_id="party-from-001",
        to_party_id=distributor["id"],
        depart_at=depart_at,
        arrive_at=arrive_at,
        temperature_min_c=temperature_min_c,
        temperature_max_c=temperature_max_c,
    )
    res = api_client.create_logistics_leg(batch["id"], payload, LOGISTICS_HEADERS)
    leg = get_success_data(res)
    return batch, leg, distributor


def setup_logistics_leg_in_transit(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    **kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Plan + depart the leg. Returns (batch, leg, distributor)."""
    batch, leg, distributor = setup_logistics_leg_planned(grower_id=grower_id, **kwargs)
    res = api_client.depart_leg(leg["id"], LOGISTICS_HEADERS)
    leg = get_success_data(res)
    return batch, leg, distributor


def insert_sensor_reading(
    leg: Dict[str, Any],
    *,
    reading_at: str,
    temperature_c: float,
    idempotency_key: Optional[str] = None,
    device_id: str = "sensor-device-001",
):
    """Submit one SensorReading. Returns the raw response (200 vs 201 differs by
    idempotent replay vs new write — caller decides what to validate)."""
    payload = create_sensor_reading_payload(
        reading_at=reading_at,
        temperature_c=temperature_c,
        idempotency_key=idempotency_key or unique_idempotency_key(),
        device_id=device_id,
    )
    return api_client.create_sensor_reading(leg["id"], payload, LOGISTICS_HEADERS)


# ─── Tier 4: Recall lifecycle ───────────────────────────────────────────────

def initiate_recall(
    batch: Dict[str, Any],
    *,
    recall_class: str = "CLASS_II",
    reason_code: str = "CONSUMER_COMPLAINT",
) -> Dict[str, Any]:
    """RegulatoryOfficer initiates a recall."""
    payload = create_recall_payload(
        batch["id"], recall_class=recall_class, reason_code=reason_code
    )
    res = api_client.create_recall(payload, REGULATORY_HEADERS)
    return get_success_data(res)


def notify_recall(recall: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.notify_recall(recall["id"], REGULATORY_HEADERS)
    return get_success_data(res)


def record_disposal(
    recall: Dict[str, Any],
    distributor: Dict[str, Any],
    *,
    disposed_kg: float,
    disposed_at: str = "2026-04-22T00:00:00.000Z",
):
    """Distributor records a disposal entry. Returns the raw response so callers
    can also assert ERR_RECALL_OVER_DISPOSED via validate_error.

    Owner-gating: PRD §2.10 / §3.8 requires distributor's X-User-ID equal
    distributor_id supplied in body, so we mint headers from the distributor's
    id.
    """
    headers = make_distributor_headers(distributor["id"])
    payload = create_disposal_payload(
        distributor_id=distributor["id"],
        disposed_kg=disposed_kg,
        disposed_at=disposed_at,
    )
    return api_client.create_disposal(recall["id"], payload, headers)


def setup_recall_at_initiated(
    *,
    grower_id: str = DEFAULT_GROWER_ID,
    inspector_id: str = "user-inspector-001",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a batch through DELIVERED (or RECALLED-eligible) and open a recall.

    Returns (batch, recall, distributor, harvest).
    """
    batch, leg, distributor = setup_logistics_leg_in_transit(
        grower_id=grower_id, inspector_id=inspector_id
    )
    # Re-fetch harvest list to grab the harvest used at QR mint
    grower_h = make_grower_headers(grower_id)
    harvests, _meta = _list(api_client.list_harvest_records(batch["id"], grower_h))
    harvest = harvests[0] if harvests else {}
    # Acknowledge leg as the destination distributor → batch DELIVERED.
    dist_h = make_distributor_headers(distributor["id"])
    res = api_client.acknowledge_leg(leg["id"], dist_h)
    get_success_data(res)
    batch = get_success_data(
        api_client.get_planting_batch(batch["id"], make_grower_headers(grower_id))
    )
    recall = initiate_recall(batch)
    return batch, recall, distributor, harvest


# ─── Cold-chain scenario helpers ────────────────────────────────────────────

def insert_three_breach_readings(leg: Dict[str, Any]) -> List[Any]:
    """Insert three consecutive out-of-range readings inside the leg window.

    Returns the three response objects (caller may inspect the third for the
    leg's transition to ABNORMAL through a follow-up GET).
    """
    # Default leg window is [00:00, 24:00); pick 01:00, 02:00, 03:00 with
    # temp=8 (range was [2,4] → out_of_range).
    res1 = insert_sensor_reading(leg, reading_at="2026-04-20T01:00:00.000Z", temperature_c=8.0)
    res2 = insert_sensor_reading(leg, reading_at="2026-04-20T02:00:00.000Z", temperature_c=8.0)
    res3 = insert_sensor_reading(leg, reading_at="2026-04-20T03:00:00.000Z", temperature_c=8.0)
    return [res1, res2, res3]


# ─── Internal utilities ─────────────────────────────────────────────────────

def _list(resp):
    """Parse a paginated list response into (data, meta) without strict
    validation, so setup helpers don't fail on minor envelope differences."""
    body = resp.json() if hasattr(resp, "json") else {}
    return body.get("data", []), body.get("meta", {})
