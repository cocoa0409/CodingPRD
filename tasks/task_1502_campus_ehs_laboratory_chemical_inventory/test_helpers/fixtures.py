"""
Composite setup helpers for multi-step test prerequisites.

The harness restarts the server before every test, so each helper builds its
preconditions from scratch using only PRD-declared endpoints. Internally these
helpers use get_success_data() so a setup failure surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.

Ownership threading (PRD §2.1): after a worker entity is created, every
ownership-gated call is made with make_pi_headers(worker["id"]) /
make_lab_member_headers(worker["id"]) — never the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_ISO,
    DOCK_ID,
    DOCK_WINDOW_END,
    DOCK_WINDOW_START,
    FUTURE_TRAINING_DUE,
)
from .factories import (
    create_area_payload,
    create_container_payload,
    create_incident_payload,
    create_inspection_payload,
    create_lab_payload,
    create_pickup_payload,
    create_registration_payload,
    create_training_payload,
    create_worker_payload,
    schedule_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_lab_member_headers,
    make_pi_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 1/2: labs, people, training, areas, containers ───────────────

def create_lab(**overrides) -> dict:
    """Create a lab (status ACTIVE, posture NORMAL). Returns the lab."""
    res = api_client.create_lab(create_lab_payload(**overrides), ADMIN)
    return get_success_data(res)


def add_worker(lab_id: str, full_name: str = "Dr. Py", role_in_lab: str = "PI") -> dict:
    """Add a worker to a lab. role_in_lab='PI' auto-assigns lab.pi_worker_id."""
    res = api_client.create_worker(
        create_worker_payload(lab_id, full_name=full_name, role_in_lab=role_in_lab), ADMIN
    )
    return get_success_data(res)


def create_lab_with_pi(**lab_overrides):
    """Create a lab plus its PI worker. Returns (lab, pi_worker)."""
    lab = create_lab(**lab_overrides)
    pi = add_worker(lab["id"], role_in_lab="PI")
    return lab, pi


def assign_and_complete_training(
    lab_id: str, worker_id: str, hazard_class: str, due_date: str = FUTURE_TRAINING_DUE
) -> dict:
    """Assign hazard-class training to a worker and complete it (as that worker).

    Returns the COMPLETED TrainingAssignment.
    """
    assignment = get_success_data(
        api_client.create_training_assignment(
            create_training_payload(
                lab_id, worker_id, hazard_class=hazard_class, due_date=due_date
            ),
            ADMIN,
        )
    )
    res = api_client.complete_training_assignment(
        assignment["id"], make_pi_headers(worker_id)
    )
    return get_success_data(res)


def create_lab_with_trained_pi(hazard_class: str = "FLAMMABLE", **lab_overrides):
    """Lab + PI worker holding COMPLETED training for hazard_class.

    Returns (lab, pi_worker).
    """
    lab, pi = create_lab_with_pi(**lab_overrides)
    assign_and_complete_training(lab["id"], pi["id"], hazard_class)
    return lab, pi


def create_area(lab_id: str, capacity_containers: int = 10, **overrides) -> dict:
    """Create an accumulation area for a lab (EHSAdmin-only)."""
    res = api_client.create_accumulation_area(
        create_area_payload(lab_id, capacity_containers=capacity_containers, **overrides),
        ADMIN,
    )
    return get_success_data(res)


def create_container(lab_id: str, actor_headers: dict, **overrides) -> dict:
    """Register a container (IN_USE) as the given actor."""
    res = api_client.create_container(
        create_container_payload(lab_id, **overrides), actor_headers
    )
    return get_success_data(res)


def create_tagged_container(lab_id: str, pi_worker: dict, area_id: str, **overrides) -> dict:
    """Create a container and tag it as waste into the area. Returns WASTE_TAGGED container."""
    headers = make_pi_headers(pi_worker["id"])
    container = create_container(lab_id, headers, **overrides)
    res = api_client.tag_waste(container["id"], {"accumulation_area_id": area_id}, headers)
    return get_success_data(res)


# ─── Tier 3: waste pickup lifecycle shortcuts ──────────────────────────

def create_draft_pickup(lab_id: str, pi_worker: dict) -> dict:
    """Create a DRAFT pickup request as the lab's PI."""
    res = api_client.create_pickup_request(
        create_pickup_payload(lab_id), make_pi_headers(pi_worker["id"])
    )
    return get_success_data(res)


def add_pickup_item(pickup_id: str, container_id: str, pi_worker: dict) -> dict:
    """Link a WASTE_TAGGED container to a DRAFT/REJECTED pickup."""
    res = api_client.add_pickup_item(
        pickup_id, {"container_id": container_id}, make_pi_headers(pi_worker["id"])
    )
    return get_success_data(res)


def setup_pickup_with_tagged_items(
    quantities=(2.0,), hazard_class: str = "FLAMMABLE", **lab_overrides
) -> dict:
    """Lab + trained PI + area + tagged containers + DRAFT pickup with all items linked."""
    lab, pi = create_lab_with_trained_pi(hazard_class, **lab_overrides)
    area = create_area(lab["id"], capacity_containers=max(10, len(quantities)))
    containers = [
        create_tagged_container(
            lab["id"], pi, area["id"], hazard_class=hazard_class, quantity_value=q
        )
        for q in quantities
    ]
    pickup = create_draft_pickup(lab["id"], pi)
    for c in containers:
        pickup = add_pickup_item(pickup["id"], c["id"], pi)
    return {
        "lab": lab,
        "pi": pi,
        "area": area,
        "containers": containers,
        "pickup": pickup,
    }


def setup_submitted_pickup(**kwargs) -> dict:
    """Pickup carried to SUBMITTED with its items linked."""
    ctx = setup_pickup_with_tagged_items(**kwargs)
    ctx["pickup"] = get_success_data(
        api_client.submit_pickup_request(
            ctx["pickup"]["id"], make_pi_headers(ctx["pi"]["id"])
        )
    )
    return ctx


def setup_scheduled_pickup(
    dock_id: str = DOCK_ID,
    window_start: str = DOCK_WINDOW_START,
    window_end: str = DOCK_WINDOW_END,
    **kwargs,
) -> dict:
    """Pickup carried to SCHEDULED at the given dock window."""
    ctx = setup_submitted_pickup(**kwargs)
    ctx["pickup"] = get_success_data(
        api_client.schedule_pickup_request(
            ctx["pickup"]["id"],
            schedule_window_payload(
                dock_id=dock_id, window_start=window_start, window_end=window_end
            ),
            ADMIN,
        )
    )
    return ctx


def setup_completed_pickup(**kwargs) -> dict:
    """Pickup carried through to COMPLETED (containers cascade to PICKED_UP)."""
    ctx = setup_scheduled_pickup(**kwargs)
    ctx["pickup"] = get_success_data(
        api_client.complete_pickup_request(ctx["pickup"]["id"], ADMIN)
    )
    return ctx


def setup_multiple_submitted_pickups(count: int, hazard_class: str = "FLAMMABLE") -> dict:
    """Lab + trained PI + area + `count` tagged containers, each in its own SUBMITTED pickup."""
    lab, pi = create_lab_with_trained_pi(hazard_class)
    area = create_area(lab["id"], capacity_containers=count + 5)
    containers = []
    pickups = []
    for _ in range(count):
        c = create_tagged_container(
            lab["id"], pi, area["id"], hazard_class=hazard_class, quantity_value=1.0
        )
        p = create_draft_pickup(lab["id"], pi)
        p = add_pickup_item(p["id"], c["id"], pi)
        p = get_success_data(
            api_client.submit_pickup_request(p["id"], make_pi_headers(pi["id"]))
        )
        containers.append(c)
        pickups.append(p)
    return {
        "lab": lab,
        "pi": pi,
        "area": area,
        "containers": containers,
        "pickups": pickups,
    }


# ─── Tier 3: inspections and corrective actions ────────────────────────

def create_inspection(
    lab_id: str,
    inspector_id: str = "insp-1",
    scheduled_start: str = "2026-08-05T09:00:00Z",
    scheduled_end: str = "2026-08-05T10:00:00Z",
) -> dict:
    """Schedule an inspection (SCHEDULED) for the given opaque inspector id."""
    res = api_client.create_inspection(
        create_inspection_payload(
            lab_id,
            inspector_id=inspector_id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        ADMIN,
    )
    return get_success_data(res)


def complete_inspection(inspection_id: str, findings: list, inspector_id: str = "insp-1") -> dict:
    """Complete a SCHEDULED inspection as its assigned inspector."""
    res = api_client.complete_inspection(
        inspection_id, {"findings": findings}, make_inspector_headers(inspector_id)
    )
    return get_success_data(res)


def list_inspection_cas(inspection_id: str) -> list:
    """List corrective actions spawned by one inspection."""
    return get_success_data(api_client.list_inspection_corrective_actions(inspection_id, ADMIN))


def setup_lab_with_completed_inspection(
    findings: list, inspector_id: str = "insp-1", with_pi: bool = True, **lab_overrides
) -> dict:
    """Lab (+ PI) with an inspection COMPLETED carrying the given findings.

    Returns {"lab", "pi", "inspection", "corrective_actions"}.
    """
    if with_pi:
        lab, pi = create_lab_with_pi(**lab_overrides)
    else:
        lab, pi = create_lab(**lab_overrides), None
    inspection = create_inspection(lab["id"], inspector_id=inspector_id)
    inspection = complete_inspection(inspection["id"], findings, inspector_id=inspector_id)
    cas = list_inspection_cas(inspection["id"])
    return {"lab": lab, "pi": pi, "inspection": inspection, "corrective_actions": cas}


# ─── Tier 4: frozen-posture scenarios ──────────────────────────────────

def freeze_lab_via_overdue_ca(lab_id: str, inspector_id: str = "insp-1",
                              advance_to: str = "2026-09-01T00:00:00Z") -> dict:
    """Complete an inspection with one MINOR finding, then advance the logical
    clock past the corrective action's 30-day due date so posture becomes FROZEN.

    Returns {"inspection", "corrective_action"}.
    """
    inspection = create_inspection(lab_id, inspector_id=inspector_id)
    inspection = complete_inspection(
        inspection["id"], [{"severity": "MINOR", "description": "missing signage"}],
        inspector_id=inspector_id,
    )
    ca = list_inspection_cas(inspection["id"])[0]
    get_success_data(api_client.set_clock({"to_iso8601": advance_to}, ADMIN))
    return {"inspection": inspection, "corrective_action": ca}


def setup_frozen_lab_with_pickup(pickup_stage: str = "DRAFT") -> dict:
    """Lab with a tagged item inside a pickup at `pickup_stage` (DRAFT or
    SCHEDULED), afterwards frozen via an overdue corrective action.

    Returns the pickup setup context plus "inspection"/"corrective_action".
    """
    if pickup_stage == "SCHEDULED":
        ctx = setup_scheduled_pickup(quantities=(1.0,))
    else:
        ctx = setup_pickup_with_tagged_items(quantities=(1.0,))
    frozen = freeze_lab_via_overdue_ca(ctx["lab"]["id"])
    ctx.update(frozen)
    return ctx


# ─── Tier 3: registrations (OCC-aware) ─────────────────────────────────

def get_lab(lab_id: str) -> dict:
    return get_success_data(api_client.get_lab(lab_id, ADMIN))


def get_lab_version(lab_id: str) -> int:
    return get_lab(lab_id)["version"]


def create_registration_for_lab(
    lab_id: str,
    material_type: str = "CONTROLLED_SUBSTANCE",
    registration_number: str = "REG-1",
    headers: dict = None,
) -> dict:
    """Create a registration with a fresh expected_lab_version (OCC)."""
    payload = create_registration_payload(
        lab_id,
        get_lab_version(lab_id),
        material_type=material_type,
        registration_number=registration_number,
    )
    res = api_client.create_registration(payload, headers or ADMIN)
    return get_success_data(res)


def setup_lab_with_active_registration(
    material_type: str = "CONTROLLED_SUBSTANCE", registration_number: str = "REG-1"
) -> dict:
    """Lab + PI + one registration of material_type carried to ACTIVE."""
    lab, pi = create_lab_with_pi()
    registration = create_registration_for_lab(
        lab["id"], material_type=material_type, registration_number=registration_number
    )
    registration = get_success_data(
        api_client.activate_registration(registration["id"], ADMIN)
    )
    return {"lab": lab, "pi": pi, "registration": registration}


# ─── Tier 3: incidents ─────────────────────────────────────────────────

def create_incident(lab_id: str, actor_headers: dict, **overrides) -> dict:
    """Report an incident (REPORTED) as the given actor."""
    res = api_client.create_incident(
        create_incident_payload(lab_id, **overrides), actor_headers
    )
    return get_success_data(res)


# ─── misc readers ──────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (EHSAdmin-only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def get_container(container_id: str) -> dict:
    return get_success_data(api_client.get_container(container_id, ADMIN))


def get_pickup(pickup_id: str) -> dict:
    return get_success_data(api_client.get_pickup_request(pickup_id, ADMIN))


def get_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, ADMIN))


def list_lab_areas(lab_id: str) -> list:
    return get_success_data(api_client.list_accumulation_areas(lab_id, ADMIN))


def list_lab_registrations(lab_id: str) -> list:
    return get_success_data(api_client.list_lab_registrations(lab_id, ADMIN))
