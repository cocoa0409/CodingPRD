"""Controlled-material registrations: intake gate, OCC stale-version, supersede,
and the suspend/reinstate lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_worker,
    create_container_payload,
    create_lab,
    create_lab_payload,
    create_lab_with_pi,
    create_registration_for_lab,
    create_registration_payload,
    get_container,
    get_lab_version,
    list_lab_registrations,
    make_pi_headers,
    setup_lab_with_active_registration,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_pending_registration_does_not_unblock_controlled_container(api):
    """PRD §3.2: "a container whose `hazard_class` is `CONTROLLED_SUBSTANCE` or
    `SELECT_AGENT` may only be registered while the lab holds an `ACTIVE`
    registration of the matching `material_type`, and otherwise the create is
    rejected with `ERR_CONTROLLED_MATERIAL_UNREGISTERED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/controlled_container_requires_active_registration
    """
    lab, pi = create_lab_with_pi(name="Lab N", department="Pharmacy", building="Hall D",
                                 room="402")
    registration = create_registration_for_lab(
        lab["id"], material_type="CONTROLLED_SUBSTANCE", registration_number="REG-2"
    )
    assert registration["status"] == "PENDING"

    res = api.create_container(
        create_container_payload(
            lab["id"], barcode="CS-9", chemical_name="Morphine stock",
            hazard_class="CONTROLLED_SUBSTANCE", quantity_value=0.25,
        ),
        make_pi_headers(pi["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONTROLLED_MATERIAL_UNREGISTERED)

    _, meta = validate_paginated(api.list_containers(ADMIN, params={"lab_id": lab["id"]}))
    assert meta["total_count"] == 0, "rejected create must not persist a container"


def test_active_registration_unblocks_controlled_container(api):
    """PRD §3.2: "a container whose `hazard_class` is `CONTROLLED_SUBSTANCE` or
    `SELECT_AGENT` may only be registered while the lab holds an `ACTIVE`
    registration of the matching `material_type`" and "the computed `access_blocked`
    flag, which is true whenever its `hazard_class` is `CONTROLLED_SUBSTANCE` or
    `SELECT_AGENT` and the lab currently has no `ACTIVE` registration of the matching
    `material_type`."
    PRD §3.7: "Activation moves a registration from `PENDING` or `SUSPENDED` to
    `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/controlled_container_requires_active_registration
    """
    ctx = setup_lab_with_active_registration(
        material_type="CONTROLLED_SUBSTANCE", registration_number="REG-2"
    )
    lab, pi = ctx["lab"], ctx["pi"]
    assert ctx["registration"]["status"] == "ACTIVE"

    res = api.create_container(
        create_container_payload(
            lab["id"], barcode="CS-9", chemical_name="Morphine stock",
            hazard_class="CONTROLLED_SUBSTANCE", quantity_value=0.25,
        ),
        make_pi_headers(pi["id"]),
    )
    container = validate_success(res, 201)
    assert container["state"] == "IN_USE"
    assert get_container(container["id"])["access_blocked"] is False, (
        "an ACTIVE registration of the matching material_type clears access_blocked"
    )


def test_registration_suspend_reinstate_cycle(api):
    """PRD §3.7: "Activation moves a registration from `PENDING` or `SUSPENDED` to
    `ACTIVE` — a registration in any other status is rejected with
    `ERR_REGISTRATION_STATE` (HTTP 409)" and "Suspension moves an `ACTIVE`
    registration to `SUSPENDED`, either by direct admin action or by the system
    cascade when the lab's posture becomes `FROZEN`, and recomputes `access_blocked`
    to true on the matching containers."

    Design: Corner/state_machines/registration_suspend_reinstate_cycle
    """
    lab = create_lab(name="Lab K", department="Pharmacy", building="Hall D", room="403")
    registration = create_registration_for_lab(
        lab["id"], material_type="SELECT_AGENT", registration_number="SA-1"
    )
    assert registration["status"] == "PENDING"

    active = validate_success(api.activate_registration(registration["id"], ADMIN), 200)
    assert active["status"] == "ACTIVE"

    suspended = validate_success(api.suspend_registration(registration["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"

    reinstated = validate_success(api.activate_registration(registration["id"], ADMIN), 200)
    assert reinstated["status"] == "ACTIVE", "SUSPENDED -> ACTIVE via the same activate endpoint"

    regs = list_lab_registrations(lab["id"])
    assert next(r for r in regs if r["id"] == registration["id"])["status"] == "ACTIVE"


def test_registration_create_with_stale_lab_version_rejected(api):
    """PRD §3.7: "an `expected_lab_version` equal to the lab's current `version`. If
    the lab's `version` has advanced beyond what the client last observed, the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "The new registration begins in `PENDING` status, and creating it
    increments the lab's `version` by 1."
    PRD §3.1: "when a worker is created with `role_in_lab` equal to `PI`, the lab's
    `pi_worker_id` is automatically set to the new worker's `id` and the lab's
    `version` increments by 1"

    Design: Corner/complexity_layers/registration_create_stale_lab_version_rejected
    """
    lab_res = api.create_lab(
        create_lab_payload(name="Lab OC", department="Pharmacy", building="Hall D", room="405"),
        ADMIN,
    )
    lab = validate_success(lab_res, 201)
    stale_version = lab["version"]

    # a PI-worker creation advances the lab's version behind the client's back
    add_worker(lab["id"], full_name="Dr. Py", role_in_lab="PI")

    res = api.create_registration(
        create_registration_payload(
            lab["id"], stale_version,
            material_type="CONTROLLED_SUBSTANCE", registration_number="REG-S",
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_lab_version(lab["id"])
    created = validate_success(
        api.create_registration(
            create_registration_payload(
                lab["id"], fresh_version,
                material_type="CONTROLLED_SUBSTANCE", registration_number="REG-S",
            ),
            ADMIN,
        ),
        201,
    )
    assert created["status"] == "PENDING"
    assert get_lab_version(lab["id"]) == fresh_version + 1, (
        "a successful registration create increments the lab's version by 1"
    )


def test_registration_create_supersedes_pending_same_type(api):
    """PRD §3.7: "If a registration of the same `lab_id` and `material_type` already
    exists in `PENDING` status when the new one is created, the existing one
    transitions to the terminal `SUPERSEDED` status and its `version` increments by
    1."

    Design: Corner/complexity_layers/registration_create_supersedes_pending_same_type
    """
    lab = create_lab(name="Lab SP", department="Pharmacy", building="Hall D", room="406")
    r1 = create_registration_for_lab(
        lab["id"], material_type="CONTROLLED_SUBSTANCE", registration_number="REG-1"
    )
    assert r1["status"] == "PENDING"

    r2 = create_registration_for_lab(
        lab["id"], material_type="CONTROLLED_SUBSTANCE", registration_number="REG-2"
    )
    assert r2["status"] == "PENDING"

    regs = {r["id"]: r for r in list_lab_registrations(lab["id"])}
    assert regs[r1["id"]]["status"] == "SUPERSEDED", (
        "the prior PENDING same-type registration is superseded"
    )
    assert regs[r2["id"]]["status"] == "PENDING"


def test_activate_active_registration_rejected(api):
    """PRD §3.7: "Activation moves a registration from `PENDING` or `SUSPENDED` to
    `ACTIVE` — a registration in any other status is rejected with
    `ERR_REGISTRATION_STATE` (HTTP 409)"

    Design: Corner/validations/activate_active_registration_rejected
    """
    lab = create_lab(name="Lab X2", department="Pharmacy", building="Hall D", room="404")
    registration = create_registration_for_lab(
        lab["id"], material_type="CONTROLLED_SUBSTANCE", registration_number="REG-X"
    )
    active = validate_success(api.activate_registration(registration["id"], ADMIN), 200)
    assert active["status"] == "ACTIVE"

    res = api.activate_registration(registration["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_REGISTRATION_STATE)

    regs = list_lab_registrations(lab["id"])
    assert next(r for r in regs if r["id"] == registration["id"])["status"] == "ACTIVE"
