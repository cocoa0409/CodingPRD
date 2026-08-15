"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch against a fresh server using
only PRD-declared endpoints, and uses get_success_data() so a broken setup
fails with a clear "Setup failed" message rather than a confusing assertion.

Identity threading: entity-backed roles (Prescriber, Pharmacist,
PharmacyTechnician, Nurse) always authenticate with the actual StaffMember id
via the make_*_headers builders; opaque roles use the TEST_USERS constants.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_SESSION_END, DEFAULT_SESSION_START
from .factories import (
    complete_batch_payload,
    count_payload,
    create_adc_pocket_payload,
    create_adc_station_payload,
    create_batch_payload,
    create_coverage_shift_payload,
    create_drug_product_payload,
    create_hood_payload,
    create_hood_session_payload,
    create_intervention_payload,
    create_order_payload,
    create_patient_payload,
    create_staff_payload,
    create_substitution_protocol_payload,
    dispense_payload,
    restock_payload,
    return_payload,
    set_clock_payload,
    waste_payload,
)
from .test_users import (
    TEST_USERS,
    make_nurse_headers,
    make_pharmacist_headers,
    make_prescriber_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["diversion_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators (all return the created resource dict)
# ---------------------------------------------------------------------------

def register_staff(staff_role: str, **overrides) -> dict:
    """Register a StaffMember row as PharmacyAdmin (PRD §3.1)."""
    payload = create_staff_payload(staff_role=staff_role, **overrides)
    return get_success_data(api_client.create_staff_member(payload, ADMIN), 201)


def make_prescriber(**overrides):
    staff = register_staff("PRESCRIBER", **overrides)
    return staff, make_prescriber_headers(staff["id"])


def make_pharmacist(**overrides):
    staff = register_staff("PHARMACIST", **overrides)
    return staff, make_pharmacist_headers(staff["id"])


def make_technician(**overrides):
    staff = register_staff("TECHNICIAN", **overrides)
    return staff, make_technician_headers(staff["id"])


def make_nurse(**overrides):
    staff = register_staff("NURSE", **overrides)
    return staff, make_nurse_headers(staff["id"])


def create_patient(**overrides) -> dict:
    """Register a patient; defaults to the healthy panel (renal factor 1.00)."""
    return get_success_data(
        api_client.create_patient(create_patient_payload(**overrides), ADMIN), 201
    )


def get_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, ADMIN), 200)


def create_drug(**overrides) -> dict:
    """Add a formulary drug; defaults: NON_CONTROLLED, 10 mg/mL, 10 mL vial."""
    return get_success_data(
        api_client.create_drug_product(create_drug_product_payload(**overrides), ADMIN),
        201,
    )


def create_hood(**overrides) -> dict:
    return get_success_data(
        api_client.create_hood(create_hood_payload(**overrides), ADMIN), 201
    )


def create_station(**overrides) -> dict:
    return get_success_data(
        api_client.create_adc_station(create_adc_station_payload(**overrides), ADMIN),
        201,
    )


def create_pocket(station_id: str, drug_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_adc_pocket(
            station_id, create_adc_pocket_payload(drug_id, **overrides), ADMIN
        ),
        201,
    )


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; runs the expiry sweeps (PRD §2.6)."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), ADMIN), 200
    )


# ---------------------------------------------------------------------------
# Tier 1: order state progression
# ---------------------------------------------------------------------------

def place_order(patient: dict, drug: dict, prescriber: dict,
                route: str = "IV", ordered_dose_mg: float = 100.0,
                frequency_per_day: int = 1, **overrides) -> dict:
    """Create an order, reading the patient's current version first (PRD §2.5)."""
    current = get_patient(patient["id"])
    payload = create_order_payload(
        patient["id"], drug["id"], current["version"],
        route=route, ordered_dose_mg=ordered_dose_mg,
        frequency_per_day=frequency_per_day, **overrides,
    )
    return get_success_data(
        api_client.create_medication_order(
            payload, make_prescriber_headers(prescriber["id"])
        ),
        201,
    )


def verify_order(order_id: str, pharmacist: dict) -> dict:
    return get_success_data(
        api_client.verify_order(order_id, {}, make_pharmacist_headers(pharmacist["id"])),
        200,
    )


def setup_verified_order(route: str = "IV", ordered_dose_mg: float = 100.0,
                         patient_overrides: dict = None,
                         drug_overrides: dict = None) -> SimpleNamespace:
    """Prescriber + pharmacist + patient + drug + one VERIFIED order."""
    prescriber, prescriber_headers = make_prescriber()
    pharmacist, pharmacist_headers = make_pharmacist()
    patient = create_patient(**(patient_overrides or {}))
    drug = create_drug(**(drug_overrides or {}))
    order = place_order(patient, drug, prescriber, route=route,
                        ordered_dose_mg=ordered_dose_mg)
    order = verify_order(order["id"], pharmacist)
    return SimpleNamespace(
        prescriber=prescriber, prescriber_headers=prescriber_headers,
        pharmacist=pharmacist, pharmacist_headers=pharmacist_headers,
        patient=patient, drug=drug, order=order,
    )


# ---------------------------------------------------------------------------
# Tier 2: hood sessions and batches
# ---------------------------------------------------------------------------

def create_hood_session(hood: dict, technician: dict,
                        start_at: str = DEFAULT_SESSION_START,
                        end_at: str = DEFAULT_SESSION_END, start: bool = False) -> dict:
    """Reserve a hood window; optionally start it (clock must be in-window)."""
    session = get_success_data(
        api_client.create_hood_session(
            create_hood_session_payload(hood["id"], start_at=start_at, end_at=end_at),
            make_technician_headers(technician["id"]),
        ),
        201,
    )
    if start:
        session = get_success_data(
            api_client.start_hood_session(
                session["id"], make_technician_headers(technician["id"])
            ),
            200,
        )
    return session


def setup_session(start: bool = True, hood_overrides: dict = None,
                  start_at: str = DEFAULT_SESSION_START,
                  end_at: str = DEFAULT_SESSION_END) -> SimpleNamespace:
    """Technician + hood + session (IN_USE by default)."""
    technician, technician_headers = make_technician()
    hood = create_hood(**(hood_overrides or {}))
    session = create_hood_session(hood, technician, start_at, end_at, start=start)
    return SimpleNamespace(
        technician=technician, technician_headers=technician_headers,
        hood=hood, session=session,
    )


def setup_batch(order_ids: list, start_session: bool = True,
                usp_risk_level: str = "LOW",
                documents_stability_source: bool = None,
                batch_creator: dict = None,
                batch_creator_headers: dict = None,
                hood_overrides: dict = None,
                order_ns: SimpleNamespace = None) -> SimpleNamespace:
    """Hood + session + DRAFT batch over the given (verified IV) orders.

    batch_creator defaults to the session's technician; pass a different
    technician (with matching headers) to control compounder_staff_id.
    """
    if order_ns is None:
        order_ns = SimpleNamespace()
    sess_ns = setup_session(start=start_session, hood_overrides=hood_overrides)
    creator = batch_creator or sess_ns.technician
    creator_headers = batch_creator_headers or sess_ns.technician_headers
    payload = create_batch_payload(
        sess_ns.session["id"], order_ids, usp_risk_level=usp_risk_level,
        **({"documents_stability_source": documents_stability_source}
           if documents_stability_source is not None else {}),
    )
    batch = get_success_data(
        api_client.create_batch(payload, creator_headers), 201
    )
    return SimpleNamespace(
        technician=creator, technician_headers=creator_headers,
        session_technician=sess_ns.technician,
        session_technician_headers=sess_ns.technician_headers,
        hood=sess_ns.hood, session=sess_ns.session, batch=batch,
        **vars(order_ns),
    )


def start_batch(ns: SimpleNamespace) -> dict:
    return get_success_data(
        api_client.start_batch(ns.batch["id"], ns.technician_headers), 200
    )


def complete_batch(ns: SimpleNamespace, prepared_volumes_ml: list,
                   waste_ml: float = 0.0, storage_condition: str = "ROOM") -> dict:
    return get_success_data(
        api_client.complete_batch(
            ns.batch["id"],
            complete_batch_payload(prepared_volumes_ml, waste_ml=waste_ml,
                                   storage_condition=storage_condition),
            ns.technician_headers,
        ),
        200,
    )


def setup_batch_in_progress(order_ids: list, **kwargs) -> SimpleNamespace:
    """DRAFT batch moved to IN_PROGRESS (session IN_USE, no HD gates)."""
    ns = setup_batch(order_ids, start_session=True, **kwargs)
    ns.batch = start_batch(ns)
    return ns


def setup_batch_qa_review(order_ids: list, prepared_volumes_ml: list,
                          waste_ml: float = 0.0,
                          storage_condition: str = "ROOM", **kwargs) -> SimpleNamespace:
    """Batch driven to QA_REVIEW; preparations COMPOUNDED with BUD computed."""
    ns = setup_batch_in_progress(order_ids, **kwargs)
    ns.batch = complete_batch(ns, prepared_volumes_ml, waste_ml=waste_ml,
                              storage_condition=storage_condition)
    return ns


# ---------------------------------------------------------------------------
# Tier 3: ADC pocket + ledger
# ---------------------------------------------------------------------------

def setup_station_with_pocket(drug: dict = None, max_units: int = 100,
                              restock_units: int = 0,
                              schedule: str = None,
                              drug_overrides: dict = None) -> SimpleNamespace:
    """Technician + station + pocket; optionally restocked to restock_units."""
    technician, technician_headers = make_technician()
    if drug is None:
        ov = dict(drug_overrides or {})
        if schedule is not None:
            ov["schedule"] = schedule
        drug = create_drug(**ov)
    station = create_station()
    pocket = create_pocket(station["id"], drug["id"], max_units=max_units)
    if restock_units:
        pocket = get_success_data(
            api_client.restock_pocket(
                pocket["id"],
                restock_payload(restock_units, pocket["version"]),
                technician_headers,
            ),
            200,
        )
    return SimpleNamespace(
        technician=technician, technician_headers=technician_headers,
        drug=drug, station=station, pocket=pocket,
    )


def restock_pocket(pocket: dict, units: int, technician: dict) -> dict:
    current = get_success_data(api_client.get_adc_pocket(pocket["id"], ADMIN), 200)
    return get_success_data(
        api_client.restock_pocket(
            pocket["id"], restock_payload(units, current["version"]),
            make_technician_headers(technician["id"]),
        ),
        200,
    )


def dispense_pocket(pocket_id: str, order_id: str, units: int, nurse: dict) -> dict:
    return get_success_data(
        api_client.dispense_pocket(
            pocket_id, dispense_payload(order_id, units),
            make_nurse_headers(nurse["id"]),
        ),
        200,
    )


def return_pocket(pocket_id: str, units: int, nurse: dict, order_id: str = None) -> dict:
    payload = return_payload(units, **({"order_id": order_id} if order_id else {}))
    return get_success_data(
        api_client.return_pocket(pocket_id, payload, make_nurse_headers(nurse["id"])),
        200,
    )


def waste_pocket(pocket_id: str, units: int, recorder: dict, recorder_headers: dict,
                 witness: dict = None) -> dict:
    payload = waste_payload(
        units, **({"witness_staff_id": witness["id"]} if witness else {})
    )
    return get_success_data(
        api_client.waste_pocket(pocket_id, payload, recorder_headers), 200
    )


def count_pocket(pocket_id: str, physical_count_units: int, pharmacist: dict) -> dict:
    return get_success_data(
        api_client.count_pocket(
            pocket_id, count_payload(physical_count_units),
            make_pharmacist_headers(pharmacist["id"]),
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Tier 4: shortage substitution
# ---------------------------------------------------------------------------

def create_protocol(shortage_drug: dict, substitute_drug: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_substitution_protocol(
            create_substitution_protocol_payload(
                shortage_drug["id"], substitute_drug["id"], **overrides
            ),
            ADMIN,
        ),
        201,
    )


def setup_active_protocol(num_flagged_orders: int = 1, route: str = "IV",
                          ordered_dose_mg: float = 80.0,
                          with_pocket: bool = False,
                          conversion_factor: float = 0.5,
                          min_dose_mg: float = None,
                          max_dose_mg: float = 200.0,
                          expires_at: str = "2026-09-01T00:00:00Z",
                          patient_overrides: dict = None) -> SimpleNamespace:
    """Shortage drug + substitute + verified orders + ACTIVE protocol.

    The orders are created and verified BEFORE activation so the activation
    cascade flags them (substitution_pending := true).
    """
    prescriber, prescriber_headers = make_prescriber()
    pharmacist, pharmacist_headers = make_pharmacist()
    shortage_drug = create_drug(in_shortage=True)
    substitute_drug = create_drug()
    orders = []
    patients = []
    for _ in range(num_flagged_orders):
        patient = create_patient(**(patient_overrides or {}))
        order = place_order(patient, shortage_drug, prescriber, route=route,
                            ordered_dose_mg=ordered_dose_mg)
        order = verify_order(order["id"], pharmacist)
        orders.append(order)
        patients.append(patient)
    pocket_ns = None
    if with_pocket:
        pocket_ns = setup_station_with_pocket(drug=shortage_drug)
    proto_payload = {}
    if min_dose_mg is not None:
        proto_payload["min_dose_mg"] = min_dose_mg
    protocol = create_protocol(
        shortage_drug, substitute_drug, conversion_factor=conversion_factor,
        max_dose_mg=max_dose_mg, expires_at=expires_at, **proto_payload,
    )
    protocol = get_success_data(
        api_client.activate_substitution_protocol(protocol["id"], ADMIN), 200
    )
    return SimpleNamespace(
        prescriber=prescriber, prescriber_headers=prescriber_headers,
        pharmacist=pharmacist, pharmacist_headers=pharmacist_headers,
        shortage_drug=shortage_drug, substitute_drug=substitute_drug,
        orders=orders, patients=patients, protocol=protocol,
        pocket_ns=pocket_ns,
    )


# ---------------------------------------------------------------------------
# Tier 5: discrepancy / diversion
# ---------------------------------------------------------------------------

def setup_discrepancy_case(schedule: str = "C_II", restock_units: int = 50,
                           waste_units: int = 4,
                           physical_count_units: int = 44) -> SimpleNamespace:
    """C_II pocket restocked then wasted down; count opens a DiscrepancyCase.

    Default: restock 50, witnessed waste 4 -> expected 46; count 44 ->
    variance -2, breaching the C_II threshold of 2 (PRD §3.6).
    """
    technician, technician_headers = make_technician()
    nurse, nurse_headers = make_nurse()
    pharmacist, pharmacist_headers = make_pharmacist()
    drug = create_drug(schedule=schedule)
    station = create_station()
    pocket = create_pocket(station["id"], drug["id"])
    pocket = get_success_data(
        api_client.restock_pocket(
            pocket["id"], restock_payload(restock_units, pocket["version"]),
            technician_headers,
        ),
        200,
    )
    if waste_units:
        waste_pocket(
            pocket["id"], waste_units, technician, technician_headers,
            witness=nurse,
        )
    count_result = count_pocket(pocket["id"], physical_count_units, pharmacist)
    return SimpleNamespace(
        technician=technician, technician_headers=technician_headers,
        nurse=nurse, nurse_headers=nurse_headers,
        pharmacist=pharmacist, pharmacist_headers=pharmacist_headers,
        drug=drug, station=station, pocket=pocket,
        count_result=count_result,
        discrepancy_case_id=count_result.get("discrepancy_case_id"),
    )


def setup_diversion_case() -> SimpleNamespace:
    """Manual DiversionCase in OPEN (PRD §3.7)."""
    technician, technician_headers = make_technician()
    station = create_station()
    case = get_success_data(
        api_client.create_diversion_case(
            {
                "station_id": station["id"],
                "subject_staff_id": technician["id"],
                "reason": "manual review",
            },
            OFFICER,
        ),
        201,
    )
    return SimpleNamespace(
        technician=technician, technician_headers=technician_headers,
        station=station, case=case,
    )


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def create_intervention(order_id: str, pharmacist: dict,
                        intervention_type: str = "OTHER", note: str = "note",
                        placed_on_hold: bool = False) -> dict:
    return get_success_data(
        api_client.create_intervention(
            order_id,
            create_intervention_payload(
                intervention_type=intervention_type, note=note,
                placed_on_hold=placed_on_hold,
            ),
            make_pharmacist_headers(pharmacist["id"]),
        ),
        201,
    )


def create_coverage_shift(staff: dict, zone: str, start_at: str, end_at: str) -> dict:
    return get_success_data(
        api_client.create_coverage_shift(
            create_coverage_shift_payload(
                staff["id"], zone=zone, start_at=start_at, end_at=end_at
            ),
            ADMIN,
        ),
        201,
    )
