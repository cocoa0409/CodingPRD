"""Composite setup helpers — multi-step preconditions built only from
PRD-declared endpoints (§4). Every fixture starts from an empty database;
each test's server is freshly launched by the runner.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_chargeback_payload,
    create_claim_packet_payload,
    create_contract_payload,
    create_inspection_payload,
    create_lease_payload,
    create_property_payload,
    create_resident_payload,
    create_technician_payload,
    create_treatment_payload,
    create_unit_payload,
    complete_inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_billing_clerk_headers,
    make_resident_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# --------------------------------------------------------------------------
# Tier 1/2: community structure
# --------------------------------------------------------------------------

def create_property(name="Test Community", address="100 Test Way"):
    return get_success_data(api_client.create_property(create_property_payload(name=name, address=address), ADMIN))


def create_active_contract(property_id, activate=True, **contract_overrides):
    """Create a contract on the property; activate it by default."""
    contract = get_success_data(
        api_client.create_contract(property_id, create_contract_payload(**contract_overrides), ADMIN)
    )
    if activate:
        contract = get_success_data(api_client.activate_contract(contract["id"], ADMIN))
    return contract


def create_unit(property_id, **overrides):
    return get_success_data(api_client.create_unit(property_id, create_unit_payload(**overrides), ADMIN))


def create_lease(unit_id, **overrides):
    return get_success_data(api_client.create_lease(unit_id, create_lease_payload(**overrides), MANAGER))


def create_resident(unit_id, lease_id, **overrides):
    payload = create_resident_payload(**overrides)
    payload["lease_id"] = lease_id
    return get_success_data(api_client.create_resident(unit_id, payload, MANAGER))


def create_technician(**overrides):
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), ADMIN))


def setup_community(num_units=1, contract_overrides=None, with_lease=True, with_resident=True,
                    unit_overrides=None):
    """Property + ACTIVE contract + N units + (per first unit) lease/resident +
    technician. Returns a dict of all handles.

    With the default logical clock (2026-08-01T00:00:00Z) every default date
    range is in force.
    """
    prop = create_property()
    contract = create_active_contract(prop["id"], **(contract_overrides or {}))
    units = []
    for i in range(num_units):
        overrides = dict(unit_overrides or {})
        overrides.setdefault("unit_number", f"10{i + 1}")
        overrides.setdefault("stack_index", i + 1)
        units.append(create_unit(prop["id"], **overrides))
    lease = create_lease(units[0]["id"]) if with_lease else None
    resident = create_resident(units[0]["id"], lease["id"]) if (with_lease and with_resident) else None
    tech = create_technician()
    return {
        "property": prop,
        "contract": contract,
        "units": units,
        "unit": units[0],
        "lease": lease,
        "resident": resident,
        "technician": tech,
    }


def resident_headers_for(resident):
    """Ownership-correct headers for the entity-backed Resident role."""
    return make_resident_headers(resident["id"])


def technician_headers_for(technician):
    """Assignment-correct headers for the entity-backed Technician role."""
    return make_technician_headers(technician["id"])


# --------------------------------------------------------------------------
# Tier 2/3: inspections and the bed bug exposure cascade
# --------------------------------------------------------------------------

def schedule_inspection(unit_id, technician_id, **overrides):
    payload = create_inspection_payload(**overrides)
    payload["technician_id"] = technician_id
    return get_success_data(api_client.create_inspection(unit_id, payload, MANAGER))


def complete_inspection(inspection_id, technician, **findings):
    """Complete an inspection as its assigned technician (entity-backed role)."""
    return get_success_data(
        api_client.complete_inspection(
            inspection_id, complete_inspection_payload(**findings), technician_headers_for(technician)
        )
    )


def complete_positive_inspection(unit_id, technician, kind="ROUTINE", **overrides):
    """Schedule + complete a bed-bug-positive inspection on a unit.
    Fires the exposure cascade: case OPEN on the unit, auto INITIAL inspections
    on exposed neighbors, posture recompute. Returns (inspection, case)."""
    insp = schedule_inspection(unit_id, technician["id"], kind=kind, pest_type="BED_BUGS", **overrides)
    completed = complete_inspection(
        insp["id"], technician, live_sightings=10, evidence_count=0, bed_bug_positive=True
    )
    cases = get_success_data(api_client.list_unit_bed_bug_cases(unit_id, MANAGER))
    case = next(c for c in cases if c["status"] in ("OPEN", "TREATING", "MONITORING", "REOPENED"))
    return completed, case


# --------------------------------------------------------------------------
# Tier 3: treatment lifecycle
# --------------------------------------------------------------------------

def schedule_treatment(unit_id, technician_id, **overrides):
    payload = create_treatment_payload(**overrides)
    payload["technician_id"] = technician_id
    return get_success_data(api_client.create_treatment(unit_id, payload, MANAGER))


def setup_prep_notified_treatment(unit_id, technician_id, **overrides):
    """SCHEDULED treatment driven to PREP_NOTIFIED (window defaults far enough
    out for the 48-hour notice at the default clock)."""
    treatment = schedule_treatment(unit_id, technician_id, **overrides)
    return get_success_data(api_client.notify_prep(treatment["id"], MANAGER))


def setup_prep_acknowledged_treatment(unit_id, resident, technician_id, **overrides):
    """PREP_NOTIFIED treatment whose resident has acknowledged prep."""
    treatment = setup_prep_notified_treatment(unit_id, technician_id, **overrides)
    return get_success_data(api_client.acknowledge_prep(treatment["id"], resident_headers_for(resident)))


def setup_prep_verified_treatment(unit_id, resident, technician_id, **overrides):
    """Full preparation handshake: notify -> acknowledge -> verify(true)."""
    treatment = setup_prep_acknowledged_treatment(unit_id, resident, technician_id, **overrides)
    return get_success_data(api_client.verify_prep(treatment["id"], {"compliant": True}, MANAGER))


def complete_treatment(treatment_id, technician, actual_minutes=60):
    """Complete a PREP_VERIFIED treatment as its assigned technician."""
    return get_success_data(
        api_client.complete_treatment(treatment_id, {"actual_minutes": actual_minutes},
                                      technician_headers_for(technician))
    )


def setup_completed_treatment(unit_id, resident, technician, **overrides):
    """Schedule + full handshake + complete. Returns the COMPLETED treatment."""
    treatment = setup_prep_verified_treatment(unit_id, resident, technician["id"], **overrides)
    return complete_treatment(treatment["id"], technician)


def run_prep_failure_cycle(unit_id, resident, technician_id, treatment_id, new_window_start,
                           new_window_end):
    """One NON_COMPLIANT loop: verify(false) then reschedule back to SCHEDULED.
    The treatment must be PREP_NOTIFIED and acknowledged on entry.
    Returns the rescheduled (SCHEDULED) treatment."""
    non_compliant = get_success_data(
        api_client.verify_prep(treatment_id, {"compliant": False}, MANAGER)
    )
    assert non_compliant["status"] == "NON_COMPLIANT", "Setup failed: verify(false) must yield NON_COMPLIANT"
    rescheduled = get_success_data(
        api_client.reschedule_treatment(
            treatment_id,
            {
                "window_start": new_window_start,
                "window_end": new_window_end,
                "expected_treatment_version": non_compliant["version"],
            },
            MANAGER,
        )
    )
    assert rescheduled["status"] == "SCHEDULED", "Setup failed: reschedule must yield SCHEDULED"
    return rescheduled


# --------------------------------------------------------------------------
# Tier 3: bed bug case to MONITORING / clearance-ready
# --------------------------------------------------------------------------

def setup_case_monitoring(resident, technician, unit_id, case_id, **treatment_overrides):
    """Drive a case OPEN -> TREATING -> MONITORING via one linked treatment
    completed (no disposals logged). Returns the COMPLETED treatment."""
    overrides = {"bed_bug_case_id": case_id, "pest_type": "BED_BUGS"}
    overrides.update(treatment_overrides)
    treatment = setup_prep_verified_treatment(unit_id, resident, technician["id"], **overrides)
    return complete_treatment(treatment["id"], technician)


def complete_follow_up(unit_id, case_id, technician, scheduled_for, positive=False,
                       live_sightings=0, evidence_count=0):
    """Schedule + complete a FOLLOW_UP inspection linked to a case."""
    insp = schedule_inspection(
        unit_id, technician["id"], kind="FOLLOW_UP", pest_type="BED_BUGS",
        scheduled_for=scheduled_for, bed_bug_case_id=case_id,
    )
    return complete_inspection(
        insp["id"], technician, live_sightings=live_sightings,
        evidence_count=evidence_count, bed_bug_positive=positive,
    )


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --------------------------------------------------------------------------
# Tier 2: chargebacks
# --------------------------------------------------------------------------

def assess_chargeback(lease_id, clerk_user_id="clerk-1", **overrides):
    return get_success_data(
        api_client.create_chargeback(
            lease_id, create_chargeback_payload(**overrides), make_billing_clerk_headers(clerk_user_id)
        )
    )


def dispute_chargeback(chargeback_id, resident, reason="contest"):
    """ASSESSED -> DISPUTED as the lease's own resident (ownership-gated)."""
    return get_success_data(
        api_client.dispute_chargeback(chargeback_id, {"reason": reason}, resident_headers_for(resident))
    )
