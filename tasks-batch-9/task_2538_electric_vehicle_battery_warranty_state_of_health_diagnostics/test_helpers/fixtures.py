"""Composite setup helpers.

The harness restarts the API server before every individual test, so every test
begins against an empty database and must build its own preconditions through the
public endpoints. These helpers do that building, in five tiers:

1. State progression — walk one resource along its lifecycle.
2. Entity hierarchy  — program, centre, technician, vehicle, installed pack.
3. Full lifecycle shortcuts — the canonical chain all the way to an adjudicated
   or fulfilled claim in one call.
4. Accumulation and threshold targeting — build the telemetry, inventory or
   ledger state a boundary rule needs.
5. Finalisation and terminal state — drive a resource to a state that refuses
   every further action.

Every helper accepts `**overrides` that are merged into the payload it posts, and
uses the lenient `get_success_data` so a setup failure reports the server's own
error identifier rather than a bare status code.
"""

from typing import Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    ADJUDICATOR_1_ID,
    ADJUDICATOR_2_ID,
    TEST_USERS,
    make_adjudicator_headers,
    make_owner_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
GATEWAY = TEST_USERS["gateway_headers"]
LAB = TEST_USERS["lab_headers"]
LIAISON = TEST_USERS["liaison_headers"]
ADJ_1 = TEST_USERS["adjudicator_headers"]
ADJ_2 = TEST_USERS["adjudicator_2_headers"]

# ─────────────────────── canonical telemetry windows ───────────────────────
# Five fresh rows at 20.0 C, so the correction factor is 1.00 throughout. The
# trimmed mean discards 55.000 and 57.000 and averages the middle three, giving
# exactly 56.000 kWh against an 80.000 kWh nominal basis: 70.00 % retention.
CANONICAL_SNAPSHOTS: List[Tuple[str, int, float]] = [
    ("2026-07-20T00:00:00Z", 71000, 55.000),
    ("2026-07-22T00:00:00Z", 71200, 56.000),
    ("2026-07-24T00:00:00Z", 71400, 56.000),
    ("2026-07-26T00:00:00Z", 71600, 56.000),
    ("2026-07-28T00:00:00Z", 71800, 57.000),
]

# Three fresh rows, all at 56.000 kWh: the plain mean applies below the window
# size, so the estimate is 56.000 kWh and the assessed odometer 71400.
THREE_SNAPSHOTS: List[Tuple[str, int, float]] = [
    ("2026-07-20T00:00:00Z", 71000, 56.000),
    ("2026-07-22T00:00:00Z", 71200, 56.000),
    ("2026-07-24T00:00:00Z", 71400, 56.000),
]

CANONICAL_IN_SERVICE_DATE = "2020-03-10"  # 76 elapsed months at the default clock


# ═════════════════════ tier 2: entity hierarchy ═════════════════════


def setup_program(api, **overrides) -> dict:
    """Register a warranty program on the reference price book."""
    payload = f.warranty_program_payload(**overrides)
    return get_success_data(api.create_warranty_program(payload, ADMIN))


def setup_center(api, **overrides) -> dict:
    """Register a high-voltage service centre, taking the reference defaults."""
    payload = f.service_center_payload(**overrides)
    return get_success_data(api.create_service_center(payload, ADMIN))


def setup_technician(api, center_id: str, **overrides) -> dict:
    """Register a technician at a centre."""
    payload = f.technician_payload(**overrides)
    return get_success_data(api.create_technician(center_id, payload, ADMIN))


def setup_vehicle(api, program_id: str, **overrides) -> dict:
    """Register a vehicle under a program."""
    overrides.setdefault("in_service_date", CANONICAL_IN_SERVICE_DATE)
    payload = f.vehicle_payload(program_id, **overrides)
    return get_success_data(api.create_vehicle(payload, ADMIN))


def setup_pack(api, **overrides) -> dict:
    """Register a battery pack; its modules are cascade-created healthy."""
    payload = f.battery_pack_payload(**overrides)
    return get_success_data(api.create_battery_pack(payload, ADMIN))


def setup_installed_pack(api, vehicle_id: str, **overrides) -> dict:
    """Register a pack already installed on a vehicle, so it lands IN_SERVICE."""
    return setup_pack(api, installed_vehicle_id=vehicle_id, **overrides)


# ═════════════════════ tier 1: state progression ═════════════════════


def ingest_snapshot(
    api, vehicle_id: str, captured_at: str, odometer_miles: int, capacity_kwh: float, **overrides
) -> dict:
    """Ingest one telematics snapshot as the gateway."""
    payload = f.snapshot_payload(captured_at, odometer_miles, capacity_kwh, **overrides)
    return get_success_data(api.ingest_snapshot(vehicle_id, payload, GATEWAY))


def ingest_snapshots(
    api,
    vehicle_id: str,
    rows: Sequence[Tuple[str, int, float]] = CANONICAL_SNAPSHOTS,
    **overrides,
) -> List[dict]:
    """Ingest a whole telemetry window in capture order."""
    return [
        ingest_snapshot(api, vehicle_id, captured_at, odometer, capacity, **overrides)
        for captured_at, odometer, capacity in rows
    ]


def read_vehicle_version(api, vehicle_id: str, technician_id: str) -> int:
    """Read the vehicle's current version, the token the assessment guard demands."""
    vehicle = get_success_data(
        api.get_vehicle(vehicle_id, make_technician_headers(technician_id))
    )
    return vehicle["version"]


def set_clock(api, current_utc: str) -> dict:
    """Move the logical clock forward. It never rewinds."""
    return get_success_data(api.set_clock(current_utc, ADMIN))


# ═════════════════════ tier 3: full lifecycle shortcuts ═════════════════════


def setup_base_world(
    api,
    program_overrides: Optional[dict] = None,
    center_overrides: Optional[dict] = None,
    technician_overrides: Optional[dict] = None,
    vehicle_overrides: Optional[dict] = None,
    pack_overrides: Optional[dict] = None,
    snapshots: Optional[Sequence[Tuple[str, int, float]]] = CANONICAL_SNAPSHOTS,
    snapshot_overrides: Optional[dict] = None,
) -> dict:
    """The canonical chain up to a fully telemetered vehicle.

    Returns a mutable world dictionary carrying every created record, the ids
    tests index most, and the entity-backed header dictionaries for the
    technician and the vehicle owner.
    """
    program = setup_program(api, **(program_overrides or {}))
    center = setup_center(api, **(center_overrides or {}))
    technician = setup_technician(api, center["id"], **(technician_overrides or {}))
    vehicle = setup_vehicle(api, program["id"], **(vehicle_overrides or {}))
    pack = setup_installed_pack(api, vehicle["id"], **(pack_overrides or {}))
    snapshot_rows = (
        ingest_snapshots(api, vehicle["id"], snapshots, **(snapshot_overrides or {}))
        if snapshots
        else []
    )
    return {
        "program": program,
        "center": center,
        "technician": technician,
        "vehicle": vehicle,
        "pack": pack,
        "snapshots": snapshot_rows,
        "program_id": program["id"],
        "center_id": center["id"],
        "technician_id": technician["id"],
        "vehicle_id": vehicle["id"],
        "pack_id": pack["id"],
        "tech_headers": make_technician_headers(technician["id"]),
        "owner_headers": make_owner_headers(vehicle["id"]),
        "admin_headers": ADMIN,
        "gateway_headers": GATEWAY,
        "lab_headers": LAB,
        "liaison_headers": LIAISON,
        "adjudicator_headers": ADJ_1,
        "adjudicator_2_headers": ADJ_2,
    }


def add_sibling_vehicle(
    api,
    world: dict,
    vin: str,
    serial_number: str,
    vehicle_overrides: Optional[dict] = None,
    pack_overrides: Optional[dict] = None,
    snapshots: Optional[Sequence[Tuple[str, int, float]]] = None,
    snapshot_overrides: Optional[dict] = None,
) -> dict:
    """Register a second vehicle-and-pack pair inside the world's own program.

    Returns an independent world view that shares the program, the centre and the
    technician, so two vehicles can be compared under one identical set of
    program constants and one shared liability ledger. Any assessment or claim
    already recorded on the source world is dropped from the copy.
    """
    vehicle = setup_vehicle(api, world["program_id"], vin=vin, **(vehicle_overrides or {}))
    pack = setup_installed_pack(
        api, vehicle["id"], serial_number=serial_number, **(pack_overrides or {})
    )
    rows = (
        ingest_snapshots(api, vehicle["id"], snapshots, **(snapshot_overrides or {}))
        if snapshots
        else []
    )
    sibling = dict(world)
    for key in ("assessment", "assessment_id", "claim", "claim_id", "adjudicator_id"):
        sibling.pop(key, None)
    sibling.update(
        {
            "vehicle": vehicle,
            "vehicle_id": vehicle["id"],
            "pack": pack,
            "pack_id": pack["id"],
            "snapshots": rows,
            "owner_headers": make_owner_headers(vehicle["id"]),
        }
    )
    return sibling


def add_assessment(
    api,
    world: dict,
    variant: str = "TELEMATICS_FLEET",
    bench_measured_capacity_kwh: Optional[float] = None,
    **overrides,
) -> dict:
    """Run a diagnostic on the world's vehicle, reading the version guard first."""
    version = read_vehicle_version(api, world["vehicle_id"], world["technician_id"])
    if variant == "BENCH_CAPACITY_TEST":
        assert bench_measured_capacity_kwh is not None, (
            "a bench diagnostic needs bench_measured_capacity_kwh"
        )
        payload = f.bench_assessment_payload(
            world["vehicle_id"],
            world["pack_id"],
            world["technician_id"],
            version,
            bench_measured_capacity_kwh,
            **overrides,
        )
    else:
        payload = f.telematics_assessment_payload(
            world["vehicle_id"],
            world["pack_id"],
            world["technician_id"],
            version,
            **overrides,
        )
    assessment = get_success_data(api.create_assessment(payload, world["tech_headers"]))
    world["assessment"] = assessment
    world["assessment_id"] = assessment["id"]
    return assessment


def add_claim(api, world: dict, **overrides) -> dict:
    """File a claim against the world's newest assessment."""
    payload = f.claim_payload(
        world["vehicle_id"],
        world["center_id"],
        world["assessment_id"],
        world["technician_id"],
        **overrides,
    )
    claim = get_success_data(api.create_claim(payload, world["tech_headers"]))
    world["claim"] = claim
    world["claim_id"] = claim["id"]
    return claim


def adjudicate(
    api,
    world: dict,
    approved_remedy: str = "MODULE_REPLACEMENT",
    adjudicator_id: str = ADJUDICATOR_1_ID,
    **overrides,
) -> dict:
    """Decide the world's claim, running the settlement waterfall."""
    payload = f.adjudicate_payload(approved_remedy, **overrides)
    claim = get_success_data(
        api.adjudicate_claim(
            world["claim_id"], payload, make_adjudicator_headers(adjudicator_id)
        )
    )
    world["claim"] = claim
    world["adjudicator_id"] = adjudicator_id
    return claim


def fulfil(api, world: dict, technician_id: Optional[str] = None, **overrides) -> dict:
    """Execute the approved remedy inside a booked high-voltage bay window."""
    payload = f.fulfil_payload(technician_id or world["technician_id"], **overrides)
    claim = get_success_data(
        api.fulfil_claim(world["claim_id"], payload, world["tech_headers"])
    )
    world["claim"] = claim
    return claim


def close(api, world: dict, adjudicator_id: str = ADJUDICATOR_1_ID, **overrides) -> dict:
    """Close a fulfilled or denied claim. Terminal."""
    payload = f.close_payload(**overrides)
    claim = get_success_data(
        api.close_claim(world["claim_id"], payload, make_adjudicator_headers(adjudicator_id))
    )
    world["claim"] = claim
    return claim


def setup_submitted_claim_world(api, module_fault_positions=(3, 7), **kwargs) -> dict:
    """The canonical chain all the way to one SUBMITTED claim.

    Two faulted modules against an allowance of three recommend a module
    replacement on a MODULE_FAULT basis.
    """
    world = setup_base_world(api, **kwargs)
    add_assessment(api, world, module_fault_positions=list(module_fault_positions))
    add_claim(api, world)
    return world


def setup_adjudicated_claim_world(
    api,
    approved_remedy: str = "MODULE_REPLACEMENT",
    adjudicator_id: str = ADJUDICATOR_1_ID,
    module_fault_positions=(3, 7),
    adjudicate_overrides: Optional[dict] = None,
    **kwargs,
) -> dict:
    """The canonical chain through adjudication, so the claim carries a settlement."""
    world = setup_submitted_claim_world(
        api, module_fault_positions=module_fault_positions, **kwargs
    )
    adjudicate(
        api,
        world,
        approved_remedy,
        adjudicator_id=adjudicator_id,
        **(adjudicate_overrides or {}),
    )
    return world


def setup_fulfilled_claim_world(api, **kwargs) -> dict:
    """The canonical chain through fulfilment, so the bay window is booked."""
    world = setup_adjudicated_claim_world(api, **kwargs)
    fulfil(api, world)
    return world


# ═════════════════ thermal events, containment and filing ═════════════════


def report_thermal_event(
    api,
    world: dict,
    severity: str = "S3",
    detected_at: str = "2026-07-31T00:00:00Z",
    affected_module_positions: Optional[Iterable[int]] = (9,),
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Report a thermal event, opening both state dimensions at once."""
    payload = f.thermal_event_payload(
        world["vehicle_id"],
        world["pack_id"],
        severity,
        detected_at,
        affected_module_positions=list(affected_module_positions)
        if affected_module_positions is not None
        else None,
        **overrides,
    )
    event = get_success_data(
        api.create_thermal_event(payload, headers or GATEWAY), expected_status=201
    )
    world["event"] = event
    world["event_id"] = event["id"]
    return event


def advance_containment(api, world: dict, step_index: int, **overrides) -> dict:
    """Record the next containment step. Steps may be neither skipped nor repeated."""
    payload = f.containment_step_payload(step_index, **overrides)
    event = get_success_data(
        api.containment_step(world["event_id"], payload, world["tech_headers"])
    )
    world["event"] = event
    return event


def file_notification(
    api, world: dict, center_id: Optional[str] = None, **overrides
) -> dict:
    """File the regulatory notification for a reportable event."""
    payload = f.regulatory_notification_payload(
        center_id or world["center_id"], **overrides
    )
    event = get_success_data(
        api.file_regulatory_notification(world["event_id"], payload, LIAISON)
    )
    world["event"] = event
    return event


def quarantine_pack_with_s3_event(
    api, world: dict, detected_at: str = "2026-07-31T00:00:00Z", **overrides
) -> dict:
    """Drive the installed pack to QUARANTINED through an S3 thermal event.

    An S3 or S4 event flags the pack damaged, classifies it UN3536 and moves it
    out of service, which is the precondition a pack shipment needs.
    """
    return report_thermal_event(api, world, "S3", detected_at, **overrides)


def close_containment(api, world: dict) -> dict:
    """Walk containment through all three steps, filing first if a filing is due."""
    advance_containment(api, world, 1)
    advance_containment(api, world, 2)
    if world["event"]["notification_status"] == "PENDING":
        file_notification(api, world)
    return advance_containment(api, world, 3)


# ═════════════════════ pack shipments ═════════════════════


def create_shipment(api, world: dict, **overrides) -> dict:
    """Create a removed-pack shipment; the hazmat declaration is frozen here."""
    payload = f.shipment_payload(
        world["pack_id"], world["center_id"], world["technician_id"], **overrides
    )
    shipment = get_success_data(
        api.create_shipment(payload, world["tech_headers"]), expected_status=201
    )
    world["shipment"] = shipment
    world["shipment_id"] = shipment["id"]
    return shipment


def tender_shipment(api, world: dict, shipment_id: Optional[str] = None, **overrides) -> dict:
    """Tender the shipment to the carrier."""
    payload = f.tender_payload(**overrides)
    shipment = get_success_data(
        api.tender_shipment(
            shipment_id or world["shipment_id"], payload, world["tech_headers"]
        )
    )
    world["shipment"] = shipment
    return shipment


def receive_shipment_accepted(
    api, world: dict, disposition: str, shipment_id: Optional[str] = None, **overrides
) -> dict:
    """Record an accepted receipt and let the pack follow the disposition."""
    payload = f.receive_accepted_payload(disposition, **overrides)
    shipment = get_success_data(
        api.receive_shipment(shipment_id or world["shipment_id"], payload, ADMIN)
    )
    world["shipment"] = shipment
    return shipment


def receive_shipment_rejected(
    api, world: dict, rejection_reason: str, shipment_id: Optional[str] = None, **overrides
) -> dict:
    """Record a rejected receipt and fire the compliance cascade."""
    payload = f.receive_rejected_payload(rejection_reason, **overrides)
    shipment = get_success_data(
        api.receive_shipment(shipment_id or world["shipment_id"], payload, ADMIN)
    )
    world["shipment"] = shipment
    return shipment


def setup_quarantined_pack_shipment_world(
    api, detected_at: str = "2026-07-31T00:00:00Z", shipment_overrides: Optional[dict] = None, **kwargs
) -> dict:
    """A world whose installed pack is quarantined and carries a DRAFT UN3536 shipment."""
    world = setup_base_world(api, **kwargs)
    quarantine_pack_with_s3_event(api, world, detected_at)
    create_shipment(api, world, **(shipment_overrides or {}))
    return world


# ═════════════════════ campaigns and consents ═════════════════════


def create_campaign(api, **overrides) -> dict:
    """Create a software remediation campaign in draft."""
    payload = f.campaign_payload(**overrides)
    return get_success_data(api.create_campaign(payload, ADMIN), expected_status=201)


def release_campaign(api, campaign_id: str, release_scope: str = "FIELD", **overrides) -> dict:
    """Release a draft campaign, minting one consent row per eligible vehicle."""
    payload = f.release_payload(release_scope, **overrides)
    return get_success_data(api.release_campaign(campaign_id, payload, ADMIN))


def list_campaign_consents(api, campaign_id: str, **params) -> Tuple[List[dict], dict]:
    """List a campaign's consents in the default created_at ascending order."""
    query = {"campaign_id": campaign_id}
    query.update(params)
    response = api.list_consents(ADMIN, params=query)
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]


def solicit_consent(
    api, campaign_id: str, vehicle_id: str, expected_campaign_version: int, **overrides
) -> dict:
    """Solicit an owner's consent explicitly, under the campaign version guard."""
    payload = f.consent_payload(
        campaign_id, vehicle_id, expected_campaign_version, **overrides
    )
    return get_success_data(api.create_consent(payload, ADMIN), expected_status=201)


def decide_consent(api, consent_id: str, vehicle_id: str, decision: str, **overrides) -> dict:
    """Record the owner's grant or refusal, acting as that vehicle's owner."""
    payload = f.consent_decision_payload(decision, **overrides)
    return get_success_data(
        api.decide_consent(consent_id, payload, make_owner_headers(vehicle_id))
    )


def apply_consent_update(api, consent_id: str, technician_id: str, **overrides) -> dict:
    """Record the applied software flash against a granted consent."""
    payload = f.apply_update_payload(**overrides)
    return get_success_data(
        api.apply_update(consent_id, payload, make_technician_headers(technician_id))
    )


def setup_released_campaign_world(
    api,
    release_scope: str = "FIELD",
    campaign_overrides: Optional[dict] = None,
    **kwargs,
) -> dict:
    """A world whose vehicle carries one PENDING consent for a released campaign."""
    world = setup_base_world(api, **kwargs)
    overrides = {"applies_to_model_code": "MX-90"}
    overrides.update(campaign_overrides or {})
    campaign = create_campaign(api, **overrides)
    released = release_campaign(api, campaign["id"], release_scope)
    consents, _ = list_campaign_consents(api, campaign["id"])
    world["campaign"] = released
    world["campaign_id"] = campaign["id"]
    world["consents"] = consents
    if consents:
        world["consent"] = consents[0]
        world["consent_id"] = consents[0]["id"]
    return world


# ═════════════════════ capacity disputes ═════════════════════


def file_dispute(api, world: dict, **overrides) -> dict:
    """File a capacity dispute against the world's adjudicated claim."""
    claim = get_success_data(api.get_claim(world["claim_id"], world["tech_headers"]))
    payload = f.dispute_payload(world["claim_id"], claim["version"], **overrides)
    dispute = get_success_data(
        api.create_dispute(payload, world["owner_headers"]), expected_status=201
    )
    world["dispute"] = dispute
    world["dispute_id"] = dispute["id"]
    return dispute


def record_lab_result(api, world: dict, lab_measured_capacity_kwh: float, **overrides) -> dict:
    """Record an independent-laboratory measurement."""
    payload = f.lab_result_payload(lab_measured_capacity_kwh, **overrides)
    dispute = get_success_data(
        api.record_lab_result(world["dispute_id"], payload, LAB)
    )
    world["dispute"] = dispute
    return dispute


def resolve_dispute(api, world: dict, adjudicator_id: str = ADJUDICATOR_2_ID, **overrides) -> dict:
    """Resolve a dispute; the resolver must differ from the claim's adjudicator."""
    payload = f.resolve_payload(**overrides)
    dispute = get_success_data(
        api.resolve_dispute(
            world["dispute_id"], payload, make_adjudicator_headers(adjudicator_id)
        )
    )
    world["dispute"] = dispute
    return dispute


def setup_disputed_claim_world(
    api, lab_measured_capacity_kwh: Optional[float] = None, **kwargs
) -> dict:
    """The canonical chain through adjudication and a filed dispute.

    Supplying `lab_measured_capacity_kwh` also records the laboratory result, so
    the dispute arrives at LAB_RESULT_RECEIVED ready to be resolved.
    """
    world = setup_adjudicated_claim_world(api, **kwargs)
    file_dispute(api, world)
    if lab_measured_capacity_kwh is not None:
        record_lab_result(api, world, lab_measured_capacity_kwh)
    return world


# ═══════════ tier 4: accumulation and threshold targeting ═══════════


def stock_reman_packs(api, specs: Sequence[dict]) -> List[dict]:
    """Register remanufactured packs in STOCK, one per spec.

    Each spec is merged into the pack payload, so a caller controls
    `refurb_soh_pct`, `remanufacture_count`, `stock_region_code` and
    `module_count` — the four keys the selector ranks and filters on.
    """
    packs = []
    for index, spec in enumerate(specs, start=1):
        overrides = {
            "serial_number": spec.pop("serial_number", f"PK-R{index:03d}"),
            "pack_type": "REMANUFACTURED",
        }
        overrides.update(spec)
        packs.append(setup_pack(api, **overrides))
    return packs


def setup_stale_vehicle_version_world(api, **kwargs) -> dict:
    """A world whose captured vehicle version has been staled by a later ingest.

    Reading the version, then ingesting one more snapshot that raises
    `odometer_miles`, leaves the captured token exactly one behind.
    """
    world = setup_base_world(api, **kwargs)
    world["stale_vehicle_version"] = read_vehicle_version(
        api, world["vehicle_id"], world["technician_id"]
    )
    ingest_snapshot(api, world["vehicle_id"], "2026-07-30T00:00:00Z", 72000, 56.000)
    world["fresh_vehicle_version"] = read_vehicle_version(
        api, world["vehicle_id"], world["technician_id"]
    )
    return world


# ═══════════ tier 5: finalisation and terminal state ═══════════


def setup_closed_claim_world(api, **kwargs) -> dict:
    """A world whose claim is CLOSED, and so refuses every further action."""
    world = setup_adjudicated_claim_world(
        api,
        approved_remedy="DENIED",
        adjudicate_overrides={"override_justification": "capacity within spec on re-review"},
        **kwargs,
    )
    close(api, world)
    return world


def setup_scrapped_pack_world(api, **kwargs) -> dict:
    """A world whose pack has been scrapped at the recycler — a terminal state."""
    world = setup_quarantined_pack_shipment_world(
        api, shipment_overrides={"destination": "RECYCLER"}, **kwargs
    )
    tender_shipment(api, world)
    receive_shipment_accepted(api, world, "SCRAP")
    return world


# ═════════════════════ convenience readers ═════════════════════


def read_program(api, program_id: str) -> dict:
    """Read the program, whose two mirrors settle synchronously."""
    return get_success_data(api.get_warranty_program(program_id, ADMIN))


def read_vehicle(api, vehicle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_vehicle(vehicle_id, headers or ADMIN))


def read_pack(api, pack_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_battery_pack(pack_id, headers or ADMIN))


def read_center(api, center_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_service_center(center_id, headers or ADMIN))


def read_claim(api, claim_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_claim(claim_id, headers or ADMIN))


def read_assessment(api, assessment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_assessment(assessment_id, headers or ADMIN))


def read_event(api, event_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_thermal_event(event_id, headers or ADMIN))


def read_campaign(api, campaign_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_campaign(campaign_id, headers or ADMIN))


def read_consent(api, consent_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_consent(consent_id, headers or ADMIN))


def read_dispute(api, dispute_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_dispute(dispute_id, headers or ADMIN))


def read_shipment(api, shipment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_shipment(shipment_id, headers or ADMIN))


def list_modules(api, pack_id: str, **params) -> Tuple[List[dict], dict]:
    """List a pack's modules, ascending by position_index."""
    response = api.list_battery_modules(pack_id, ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_snapshots(api, vehicle_id: str, **params) -> Tuple[List[dict], dict]:
    """List a vehicle's snapshots, newest captured_at first."""
    response = api.list_snapshots(vehicle_id, ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_claims(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_claims(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_assessments(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_assessments(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_packs(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_battery_packs(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_shipments(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_shipments(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_centers(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_service_centers(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_vehicles(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_vehicles(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_technicians(api, center_id: str, **params) -> Tuple[List[dict], dict]:
    """List a centre's technicians, whose `status` is re-derived on every read."""
    response = api.list_technicians(center_id, ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def read_technician(api, center_id: str, technician_id: str) -> dict:
    """A technician is reachable only through the collection under their centre."""
    rows, _ = list_technicians(api, center_id, limit=100)
    for row in rows:
        if row["id"] == technician_id:
            return row
    raise AssertionError(f"no technician {technician_id} at centre {center_id}")


def list_thermal_events(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_thermal_events(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_campaigns(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_campaigns(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_consents(api, **params) -> Tuple[List[dict], dict]:
    response = api.list_consents(ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]


def list_claim_disputes(api, claim_id: str, **params) -> Tuple[List[dict], dict]:
    response = api.list_claim_disputes(claim_id, ADMIN, params=params or None)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["data"], body["meta"]
