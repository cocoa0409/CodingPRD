"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. They use get_success_data() so setup failures
surface as clear "Setup step failed" errors rather than assertion noise.

Identity threading (PRD §2.1): InterventionalCardiologist calls that are
ownership-gated (case start/complete, AUC attestation) are always issued with
make_interventional_cardiologist_headers(<the actual StaffMember id>).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import T_0900
from .factories import (
    auc_attestation_payload,
    contrast_record_payload,
    create_case_payload,
    create_device_lot_payload,
    create_recovery_bed_payload,
    create_room_payload,
    create_staff_payload,
    device_usage_payload,
    radiation_record_payload,
    schedule_case_payload,
    staff_assignment_payload,
)
from .test_users import TEST_USERS, make_interventional_cardiologist_headers

SCHEDULER = TEST_USERS["scheduler_headers"]
TECHNOLOGIST = TEST_USERS["technologist_headers"]
NURSE_MANAGER = TEST_USERS["nurse_manager_headers"]
REGISTRY = TEST_USERS["registry_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Drive the server's logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, SCHEDULER))


def create_cardiologist(full_name="Dr Perform"):
    """Register an INTERVENTIONAL_CARDIOLOGIST. Returns the StaffMember."""
    return get_success_data(api_client.create_staff(
        create_staff_payload(full_name=full_name,
                             staff_role="INTERVENTIONAL_CARDIOLOGIST"),
        SCHEDULER))


def create_scrub_technologist(full_name="Tech One"):
    """Register a SCRUB_TECHNOLOGIST. Returns the StaffMember."""
    return get_success_data(api_client.create_staff(
        create_staff_payload(full_name=full_name, staff_role="SCRUB_TECHNOLOGIST"),
        SCHEDULER))


def create_circulating_nurse(full_name="Nurse One"):
    """Register a CIRCULATING_NURSE. Returns the StaffMember."""
    return get_success_data(api_client.create_staff(
        create_staff_payload(full_name=full_name, staff_role="CIRCULATING_NURSE"),
        SCHEDULER))


def create_room(room_name="Lab 1", equipment_profile=None):
    """Register a cath lab room (born ACTIVE). Returns the room."""
    return get_success_data(api_client.create_room(
        create_room_payload(room_name=room_name, equipment_profile=equipment_profile),
        SCHEDULER))


def create_recovery_bed(bed_label="Bed 1"):
    """Register a recovery bed (born AVAILABLE). Returns the bed."""
    return get_success_data(api_client.create_recovery_bed(
        create_recovery_bed_payload(bed_label=bed_label), NURSE_MANAGER))


def create_device_lot(**overrides):
    """Register a device lot. Returns the lot."""
    return get_success_data(api_client.create_device_lot(
        create_device_lot_payload(**overrides), TECHNOLOGIST))


def post_case(performing_physician_id, patient_mrn="MRN-1", procedure_type="PCI",
              priority="URGENT", weight_kg=70, serum_creatinine=1.0,
              equipment_needs=None, scheduled_start=None, as_role=None):
    """Post a case. ELECTIVE/URGENT are born POSTED; STEMI activates at once."""
    headers = as_role if as_role is not None else SCHEDULER
    return get_success_data(api_client.create_case(
        create_case_payload(
            patient_mrn=patient_mrn, procedure_type=procedure_type,
            priority=priority, performing_physician_id=performing_physician_id,
            weight_kg=weight_kg, serum_creatinine=serum_creatinine,
            equipment_needs=equipment_needs, scheduled_start=scheduled_start),
        headers))


# ---------------------------------------------------------------------------
# Tier 2: case workflow verbs
# ---------------------------------------------------------------------------

def document_auc(case, ordering_physician, auc_score="APPROPRIATE",
                 criterion_code="AUC-45.1"):
    """Record an AUC attestation, threading the case's current version (OCC).

    The acting cardiologist must be the ordering physician (segregation of
    duties, PRD §3.8), so the call is signed with the ordering physician's id.
    Returns the updated case.
    """
    return get_success_data(api_client.attest_auc(
        case["id"],
        auc_attestation_payload(ordering_physician["id"], case["version"],
                                auc_score=auc_score, criterion_code=criterion_code),
        make_interventional_cardiologist_headers(ordering_physician["id"])))


def schedule_case(case_id, room_id, scheduled_start=T_0900, bed_id=None):
    """Schedule (or reschedule) a case onto a room. Returns the updated case."""
    return get_success_data(api_client.schedule_case(
        case_id, schedule_case_payload(room_id, scheduled_start, bed_id=bed_id),
        SCHEDULER))


def cancel_case(case_id):
    """Cancel a case. Returns the updated case."""
    return get_success_data(api_client.cancel_case(case_id, SCHEDULER))


def assign_staff(case_id, staff_id, role_in_case):
    """Assign a staff member to a SCHEDULED case. Returns the assignment."""
    return get_success_data(api_client.create_staff_assignment(
        case_id, staff_assignment_payload(staff_id, role_in_case), SCHEDULER))


def staff_case(case_id, scrub_tech_id, nurse_id):
    """Assign the SCRUB + CIRCULATOR pair required for case start (PRD §3.7)."""
    scrub = assign_staff(case_id, scrub_tech_id, "SCRUB")
    circulator = assign_staff(case_id, nurse_id, "CIRCULATOR")
    return scrub, circulator


def start_case(case_id, performing_physician_id):
    """Start a case as its performing cardiologist. Returns the updated case."""
    return get_success_data(api_client.start_case(
        case_id, make_interventional_cardiologist_headers(performing_physician_id)))


def complete_case(case_id, performing_physician_id):
    """Complete a case as its performing cardiologist. Returns the case."""
    return get_success_data(api_client.complete_case(
        case_id, make_interventional_cardiologist_headers(performing_physician_id)))


def reserve_device_usage(case_id, lot_id, quantity):
    """Reserve device units from a lot for a case. Returns the usage."""
    return get_success_data(api_client.create_device_usage(
        case_id, device_usage_payload(lot_id, quantity), TECHNOLOGIST))


def add_contrast_record(case_id, contrast_ml):
    """Record a contrast entry against an IN_PROGRESS case. Returns the entry."""
    return get_success_data(api_client.create_dose_record(
        case_id, contrast_record_payload(contrast_ml), TECHNOLOGIST))


def add_radiation_record(case_id, fluoroscopy_mgy, cine_mgy):
    """Record a radiation entry against an IN_PROGRESS case. Returns the entry."""
    return get_success_data(api_client.create_dose_record(
        case_id, radiation_record_payload(fluoroscopy_mgy, cine_mgy), TECHNOLOGIST))


def get_case(case_id):
    return get_success_data(api_client.get_case(case_id, SCHEDULER))


def get_bed(bed_id):
    return get_success_data(api_client.get_recovery_bed(bed_id, NURSE_MANAGER))


def get_lot(lot_id):
    return get_success_data(api_client.get_device_lot(lot_id, TECHNOLOGIST))


# ---------------------------------------------------------------------------
# Tier 3: workspace composites (full precondition chains)
# ---------------------------------------------------------------------------

def setup_case_workspace(priority="URGENT", procedure_type="PCI",
                         equipment_needs=None, weight_kg=70, serum_creatinine=1.0,
                         patient_mrn="MRN-1", scheduled_start=T_0900,
                         room_name="Lab 1", room_equipment=None,
                         bed_label="Bed 1", with_bed=True):
    """Physician + room (+ bed) + case, scheduled onto the room.

    ELECTIVE cases are AUC-documented by a second cardiologist first (the
    elective scheduling gate, PRD §3.3). Returns a workspace dict with keys:
    physician, ordering_physician (ELECTIVE only), room, bed, case.
    """
    physician = create_cardiologist()
    room = create_room(room_name=room_name, equipment_profile=room_equipment)
    bed = create_recovery_bed(bed_label) if with_bed else None
    case = post_case(physician["id"], patient_mrn=patient_mrn,
                     procedure_type=procedure_type, priority=priority,
                     weight_kg=weight_kg, serum_creatinine=serum_creatinine,
                     equipment_needs=equipment_needs)
    workspace = {"physician": physician, "room": room, "bed": bed, "case": case}
    if priority == "ELECTIVE":
        ordering = create_cardiologist(full_name="Dr Order")
        case = document_auc(case, ordering)
        workspace["ordering_physician"] = ordering
        workspace["case"] = case
    case = schedule_case(case["id"], room["id"], scheduled_start,
                         bed_id=bed["id"] if bed else None)
    workspace["case"] = case
    return workspace


def setup_in_progress_workspace(scrub_name="Tech One", nurse_name="Nurse One",
                                **kwargs):
    """A scheduled case, fully staffed and started. Adds keys: scrub_tech,
    nurse, scrub_assignment, circulator_assignment; case is IN_PROGRESS."""
    workspace = setup_case_workspace(**kwargs)
    case = workspace["case"]
    scrub_tech = create_scrub_technologist(full_name=scrub_name)
    nurse = create_circulating_nurse(full_name=nurse_name)
    scrub_asg, circ_asg = staff_case(case["id"], scrub_tech["id"], nurse["id"])
    case = start_case(case["id"], workspace["physician"]["id"])
    workspace.update({
        "scrub_tech": scrub_tech,
        "nurse": nurse,
        "scrub_assignment": scrub_asg,
        "circulator_assignment": circ_asg,
        "case": case,
    })
    return workspace


def setup_completed_workspace(with_radiation=True, radiation=(100, 50), **kwargs):
    """An IN_PROGRESS workspace carried through completion. Adds dose_record
    when with_radiation is true; the case ends COMPLETED."""
    workspace = setup_in_progress_workspace(**kwargs)
    case = workspace["case"]
    dose_record = None
    if with_radiation:
        fluoro, cine = radiation
        dose_record = add_radiation_record(case["id"], fluoro, cine)
    case = complete_case(case["id"], workspace["physician"]["id"])
    workspace["case"] = case
    workspace["dose_record"] = dose_record
    return workspace


def setup_submission_workspace(**kwargs):
    """A completed workspace plus its DRAFT registry submission."""
    workspace = setup_completed_workspace(**kwargs)
    submission = get_success_data(api_client.create_registry_submission(
        workspace["case"]["id"], REGISTRY))
    workspace["submission"] = submission
    return workspace
