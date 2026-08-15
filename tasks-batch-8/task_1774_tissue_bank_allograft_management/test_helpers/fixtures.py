"""Composite setup helpers for multi-step PRD workflows.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. Setup calls go through get_success_data so
failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adverse_reaction_payload,
    create_document_payload,
    create_freezer_payload,
    create_implant_case_payload,
    create_par_policy_payload,
    create_recall_payload,
    create_shipment_payload,
    create_supplier_payload,
    make_manifest_item,
)
from .test_users import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]
COORD2 = TEST_USERS["coordinator2_headers"]
QM = TEST_USERS["quality_headers"]
QM2 = TEST_USERS["quality2_headers"]
CO = TEST_USERS["compliance_headers"]
CO2 = TEST_USERS["compliance2_headers"]
SURG = TEST_USERS["surgeon_headers"]
SURG2 = TEST_USERS["surgeon2_headers"]
ADMIN = TEST_USERS["admin_headers"]

CASE_START = "2026-08-10T10:00:00Z"
CASE_END = "2026-08-10T12:00:00Z"
IMPLANT_CLOCK = "2026-08-10T11:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------
def advance_clock(to_iso8601: str) -> dict:
    """Move the logical clock forward; runs the document, unit, and
    reservation sweeps synchronously (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: supplier qualification
# ---------------------------------------------------------------------------
def setup_qualified_supplier(
    legal_name="Acme Tissue Source",
    license_number="LIC-001",
    verifier=None,
    approver=None,
) -> dict:
    """Register a supplier, submit + verify AATB_ACCREDITATION and
    FDA_REGISTRATION documents, then approve it.

    The default verifier (qm-1) is a different operator than the default
    approver (co-1) so the segregation-of-duties gate of PRD §2.10 passes.
    Returns the QUALIFIED supplier.
    """
    verifier = verifier or QM
    approver = approver or CO
    supplier = get_success_data(
        api_client.create_supplier(
            create_supplier_payload(legal_name=legal_name, license_number=license_number),
            QM,
        )
    )
    doc_a = get_success_data(
        api_client.create_supplier_document(
            supplier["id"],
            create_document_payload(doc_type="AATB_ACCREDITATION", document_ref="AATB-1"),
            QM,
        )
    )
    get_success_data(api_client.verify_document(supplier["id"], doc_a["id"], verifier))
    doc_f = get_success_data(
        api_client.create_supplier_document(
            supplier["id"],
            create_document_payload(doc_type="FDA_REGISTRATION", document_ref="FDA-1"),
            QM,
        )
    )
    get_success_data(api_client.verify_document(supplier["id"], doc_f["id"], verifier))
    return get_success_data(api_client.approve_supplier(supplier["id"], approver))


# ---------------------------------------------------------------------------
# Tier 1: freezer
# ---------------------------------------------------------------------------
def setup_freezer(name="FZ-ULT-1", min_celsius=-80.0, max_celsius=-60.0,
                  nominal_capacity=50) -> dict:
    """Register a freezer; returns the OPERATIONAL freezer."""
    return get_success_data(
        api_client.create_freezer(
            create_freezer_payload(
                name=name,
                min_celsius=min_celsius,
                max_celsius=max_celsius,
                nominal_capacity=nominal_capacity,
            ),
            ADMIN,
        )
    )


def setup_supplier_and_freezer(freezer_name="FZ-ULT-1", nominal_capacity=50,
                               license_number="LIC-001"):
    """Qualified supplier + operational freezer. Returns (supplier, freezer)."""
    supplier = setup_qualified_supplier(license_number=license_number)
    freezer = setup_freezer(name=freezer_name, nominal_capacity=nominal_capacity)
    return supplier, freezer


# ---------------------------------------------------------------------------
# Tier 2: shipments and units
# ---------------------------------------------------------------------------
def create_shipment(supplier_id, freezer_id, items, headers=COORD) -> dict:
    """Receive a shipment; one QUARANTINED TissueUnit is minted per line."""
    return get_success_data(
        api_client.create_shipment(
            create_shipment_payload(supplier_id, freezer_id, items), headers
        )
    )


def units_of_shipment(shipment_id) -> list:
    """Units minted by a shipment, sorted serial_number ascending (PRD §3.4)."""
    return get_success_data(
        api_client.list_tissue_units(QM, params={"shipment_id": shipment_id})
    )


def setup_received_shipment(items=None, **kw):
    """Qualified supplier + freezer + a RECEIVED shipment.
    Returns (supplier, freezer, shipment, units)."""
    supplier, freezer = setup_supplier_and_freezer(**kw)
    shipment = create_shipment(
        supplier["id"], freezer["id"], items or [make_manifest_item()]
    )
    return supplier, freezer, shipment, units_of_shipment(shipment["id"])


def setup_accepted_units(items=None, **kw):
    """Qualified supplier + freezer + shipment inspected to ACCEPTED.
    Returns (supplier, freezer, shipment, units sorted serial_number ASC)."""
    supplier, freezer, shipment, units = setup_received_shipment(items=items, **kw)
    get_success_data(api_client.accept_shipment(shipment["id"], COORD))
    return supplier, freezer, shipment, units_of_shipment(shipment["id"])


def release_units(units, headers=QM) -> list:
    """QC-release each QUARANTINED unit to AVAILABLE; returns updated units."""
    return [get_success_data(api_client.release_unit(u["id"], headers)) for u in units]


def setup_available_units(items=None, **kw):
    """Accepted shipment with every unit released to AVAILABLE.
    Returns (supplier, freezer, shipment, released_units)."""
    supplier, freezer, shipment, units = setup_accepted_units(items=items, **kw)
    released = release_units(units)
    return supplier, freezer, shipment, released


# ---------------------------------------------------------------------------
# Tier 3: cases, reservations, issue, implantation
# ---------------------------------------------------------------------------
def setup_case(patient_ref="P-1", or_room_id="OR-1", scheduled_start=CASE_START,
               scheduled_end=CASE_END, headers=SURG) -> dict:
    """Schedule an implant case; returns the SCHEDULED case."""
    return get_success_data(
        api_client.create_implant_case(
            create_implant_case_payload(
                patient_ref=patient_ref,
                or_room_id=or_room_id,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
            ),
            headers,
        )
    )


def setup_reservation(case_id, unit_id, headers=COORD) -> dict:
    """Reserve an AVAILABLE unit for a case; returns the ACTIVE reservation."""
    return get_success_data(
        api_client.create_reservation(case_id, {"tissue_unit_id": unit_id}, headers)
    )


def issue_unit(unit_id, reservation_id=None, headers=COORD) -> dict:
    """Issue a unit directly, or against an ACTIVE reservation."""
    payload = {"reservation_id": reservation_id} if reservation_id else {}
    return get_success_data(api_client.issue_unit(unit_id, payload, headers))


def setup_reserved_unit(items=None, **kw) -> dict:
    """Available unit + case + ACTIVE reservation on the first unit."""
    supplier, freezer, shipment, units = setup_available_units(items=items, **kw)
    case = setup_case()
    reservation = setup_reservation(case["id"], units[0]["id"])
    return {
        "supplier": supplier,
        "freezer": freezer,
        "shipment": shipment,
        "units": units,
        "unit": units[0],
        "case": case,
        "reservation": reservation,
    }


def setup_issued_unit(via_reservation=True, items=None, **kw) -> dict:
    """Unit in ISSUED — via an ACTIVE reservation (default) or direct issue."""
    supplier, freezer, shipment, units = setup_available_units(items=items, **kw)
    case = setup_case()
    reservation = None
    if via_reservation:
        reservation = setup_reservation(case["id"], units[0]["id"])
        issued = issue_unit(units[0]["id"], reservation_id=reservation["id"])
    else:
        issued = issue_unit(units[0]["id"])
    return {
        "supplier": supplier,
        "freezer": freezer,
        "shipment": shipment,
        "units": units,
        "unit": issued,
        "case": case,
        "reservation": reservation,
    }


def setup_implanted_unit(via_reservation=True, items=None, implant_clock=IMPLANT_CLOCK,
                         **kw) -> dict:
    """Full chain: unit ISSUED then recorded IMPLANTED into the case at
    implant_clock (inside the implant window of PRD §3.5)."""
    bundle = setup_issued_unit(via_reservation=via_reservation, items=items, **kw)
    advance_clock(implant_clock)
    implanted = get_success_data(
        api_client.record_implantation(
            bundle["case"]["id"], {"tissue_unit_id": bundle["unit"]["id"]}, SURG
        )
    )
    bundle["unit"] = implanted
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: excursions
# ---------------------------------------------------------------------------
def open_excursion_via_reading(freezer_id, temp_celsius=-50.0, headers=COORD) -> str:
    """Post an out-of-range reading; returns the opened excursion id."""
    reading = get_success_data(
        api_client.create_reading(freezer_id, {"temp_celsius": temp_celsius}, headers)
    )
    assert reading.get("excursion_id"), "out-of-range reading must open an excursion"
    return reading["excursion_id"]


def report_manual_excursion(freezer_id, reason="Door left ajar observed on rounds",
                            headers=COORD) -> dict:
    """Manually report an excursion (origin MANUAL_REPORT)."""
    return get_success_data(api_client.report_excursion(freezer_id, {"reason": reason}, headers))


def investigate_excursion(excursion_id, headers=QM) -> dict:
    """Move an OPEN excursion to UNDER_INVESTIGATION."""
    return get_success_data(api_client.investigate_excursion(excursion_id, headers))


def resolve_excursion_ok(excursion_id, disposition, resolution_notes, headers=QM) -> dict:
    """Resolve an UNDER_INVESTIGATION excursion (expected to succeed)."""
    return get_success_data(
        api_client.resolve_excursion(
            excursion_id,
            {"disposition": disposition, "resolution_notes": resolution_notes},
            headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: recalls and adverse reactions
# ---------------------------------------------------------------------------
def create_recall(supplier_id, lot_numbers=None, reason="Supplier sterility assurance failure",
                  headers=QM, **overrides) -> dict:
    """Draft a recall scoped by supplier + lots + received window."""
    return get_success_data(
        api_client.create_recall(
            create_recall_payload(
                supplier_id,
                lot_numbers=lot_numbers or ["L1"],
                reason=reason,
                **overrides,
            ),
            headers,
        )
    )


def report_adverse_reaction(case_id, unit_id, headers=SURG, **overrides) -> dict:
    """Report an adverse reaction on a case; returns the REPORTED case."""
    return get_success_data(
        api_client.report_adverse_reaction(
            case_id, create_adverse_reaction_payload(unit_id, **overrides), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: par-level policies
# ---------------------------------------------------------------------------
def create_par_policy(tissue_type="BONE", par_quantity=2,
                      max_inventory_value_cents=100000000,
                      expected_current_policy_version=None, headers=ADMIN) -> dict:
    """Create an ACTIVE par policy; expected_current_policy_version is omitted
    when no ACTIVE policy exists for the tissue type (PRD §2.7)."""
    payload = create_par_policy_payload(
        tissue_type=tissue_type,
        par_quantity=par_quantity,
        max_inventory_value_cents=max_inventory_value_cents,
    )
    if expected_current_policy_version is not None:
        payload["expected_current_policy_version"] = expected_current_policy_version
    return get_success_data(api_client.create_par_policy(payload, headers))


# ---------------------------------------------------------------------------
# Tier 4: valuation fixture (accepted population with a consumed unit)
# ---------------------------------------------------------------------------
def setup_valuation_population() -> dict:
    """BONE accepted population {U-001 @10001 (L1), U-002 @10001 (L1),
    U-101 @10002 (L2)} across two shipments received on 2026-08-01 and
    2026-08-02; U-001 then IMPLANTED on 2026-08-10 so the on-hand set is
    {U-002 (L1), U-101 (L2)}. Returns the full bundle for assertions."""
    supplier = setup_qualified_supplier()
    freezer = setup_freezer()
    shipment1 = create_shipment(
        supplier["id"],
        freezer["id"],
        [
            make_manifest_item(lot_number="L1", serial_number="U-001", unit_cost_cents=10001),
            make_manifest_item(lot_number="L1", serial_number="U-002", unit_cost_cents=10001),
        ],
    )
    get_success_data(api_client.accept_shipment(shipment1["id"], COORD))
    advance_clock("2026-08-02T00:00:00Z")
    shipment2 = create_shipment(
        supplier["id"],
        freezer["id"],
        [make_manifest_item(lot_number="L2", serial_number="U-101", unit_cost_cents=10002)],
    )
    get_success_data(api_client.accept_shipment(shipment2["id"], COORD))
    units1 = units_of_shipment(shipment1["id"])
    units2 = units_of_shipment(shipment2["id"])
    release_units(units1 + units2)
    case = setup_case()
    reservation = setup_reservation(case["id"], units1[0]["id"])
    issue_unit(units1[0]["id"], reservation_id=reservation["id"])
    advance_clock(IMPLANT_CLOCK)
    get_success_data(
        api_client.record_implantation(case["id"], {"tissue_unit_id": units1[0]["id"]}, SURG)
    )
    return {
        "supplier": supplier,
        "freezer": freezer,
        "shipment1": shipment1,
        "shipment2": shipment2,
        "u1": units1[0],
        "u2": units1[1],
        "u3": units2[0],
        "case": case,
    }


# ---------------------------------------------------------------------------
# Tier 4: excursion over live stock
# ---------------------------------------------------------------------------
def setup_excursion_over_units(items, reading_temp=-50.0, opened_at="2026-08-05T09:00:00Z",
                               **kw) -> dict:
    """Accepted + released units, then an out-of-range reading opens an
    excursion over the freezer at `opened_at`. Returns bundle with the
    excursion id; units are QUARANTINED with hold_reason EXCURSION."""
    supplier, freezer, shipment, units = setup_available_units(items=items, **kw)
    advance_clock(opened_at)
    excursion_id = open_excursion_via_reading(freezer["id"], reading_temp)
    return {
        "supplier": supplier,
        "freezer": freezer,
        "shipment": shipment,
        "units": units,
        "excursion_id": excursion_id,
    }
