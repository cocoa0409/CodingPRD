"""Deep cascades: inspection FAIL with MAJOR finding freezes the lab and suspends
registrations; closeout cascades to scheduled inspections."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_container,
    create_inspection,
    create_lab_with_pi,
    get_container,
    get_inspection,
    get_lab,
    list_lab_registrations,
    make_pi_headers,
    setup_lab_with_active_registration,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

_FAIL_FINDINGS = [
    {"severity": "MAJOR", "description": "open CSA safe"},
    {"severity": "MAJOR", "description": "missing log"},
]


def _setup_lab_with_active_cs_container(api):
    """Lab + PI + ACTIVE CONTROLLED_SUBSTANCE registration + one CS container."""
    ctx = setup_lab_with_active_registration(
        material_type="CONTROLLED_SUBSTANCE", registration_number="REG-1"
    )
    container = create_container(
        ctx["lab"]["id"], make_pi_headers(ctx["pi"]["id"]), barcode="CS-1",
        chemical_name="Fentanyl stock", hazard_class="CONTROLLED_SUBSTANCE",
        quantity_value=0.5,
    )
    ctx["container"] = container
    return ctx


def test_fail_with_major_cascades_to_frozen_and_suspends_registration(api):
    """PRD §3.5: "a `FAIL` with at least one `MAJOR` finding forces the posture to
    `FROZEN` via derivation rule 3, and a transition into `FROZEN` suspends every
    `ACTIVE` registration of the lab and recomputes `access_blocked` to true on the
    lab's containers of each suspended `material_type`."
    PRD §2.6: "Otherwise, if the lab's most recently completed inspection — the
    `COMPLETED` inspection with the latest `completed_at`, ties broken in favor of
    the earliest `created_at` — has `outcome` equal to `FAIL` with at least one
    `MAJOR` finding, posture is `FROZEN`."

    Design: Difficulty/transitive_cascade/inspection_fail_cascade_freezes_registrations
    """
    ctx = _setup_lab_with_active_cs_container(api)
    lab, container, registration = ctx["lab"], ctx["container"], ctx["registration"]
    assert registration["status"] == "ACTIVE"
    assert get_container(container["id"])["access_blocked"] is False

    inspection = create_inspection(lab["id"], inspector_id="insp-1",
                                   scheduled_start="2026-08-06T09:00:00Z",
                                   scheduled_end="2026-08-06T10:00:00Z")
    completed = validate_success(
        api.complete_inspection(
            inspection["id"], {"findings": _FAIL_FINDINGS},
            TEST_USERS["inspector_headers"],
        ),
        200,
    )
    assert completed["outcome"] == "FAIL"
    assert completed["score_weighted"] == 60, "100 - 2*20 = 60 < 70 -> FAIL"

    assert get_lab(lab["id"])["posture"] == "FROZEN"

    regs = list_lab_registrations(lab["id"])
    reg_after = next(r for r in regs if r["id"] == registration["id"])
    assert reg_after["status"] == "SUSPENDED", (
        "transition into FROZEN suspends every ACTIVE registration"
    )

    assert get_container(container["id"])["access_blocked"] is True, (
        "suspension recomputes access_blocked=true on matching containers"
    )


def test_frozen_cascade_gates_new_container_registration(api):
    """PRD §3.5: "a `FAIL` with at least one `MAJOR` finding forces the posture to
    `FROZEN` via derivation rule 3"
    PRD §2.6: "While a lab is `FROZEN`, four mutations are gated and fail with
    `ERR_LAB_FROZEN` (HTTP 409): registering a new container in the lab, tagging a
    container as waste, creating a waste pickup request for the lab, and submitting
    a waste pickup request for the lab."

    Design: Difficulty/transitive_cascade/inspection_fail_cascade_freezes_registrations
    """
    ctx = _setup_lab_with_active_cs_container(api)
    lab, pi = ctx["lab"], ctx["pi"]

    inspection = create_inspection(lab["id"], inspector_id="insp-1",
                                   scheduled_start="2026-08-06T09:00:00Z",
                                   scheduled_end="2026-08-06T10:00:00Z")
    validate_success(
        api.complete_inspection(
            inspection["id"], {"findings": _FAIL_FINDINGS},
            TEST_USERS["inspector_headers"],
        ),
        200,
    )
    assert get_lab(lab["id"])["posture"] == "FROZEN"

    res = api.create_container(
        {
            "lab_id": lab["id"],
            "barcode": "CS-2",
            "chemical_name": "Morphine stock",
            "hazard_class": "CONTROLLED_SUBSTANCE",
            "quantity_value": 0.25,
            "quantity_unit": "GAL",
        },
        make_pi_headers(pi["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LAB_FROZEN)


def test_closeout_cancels_scheduled_inspection(api):
    """PRD §3.8: "Closeout cancels every inspection of the lab still in `SCHEDULED`
    status — each cancelled inspection's `version` increments by 1 — recomputes the
    lab's posture, and increments the lab's `version` by 1."
    PRD §3.8: "closeout begins with the transition from `ACTIVE` to `CLOSING`"

    Design: Corner/state_machines/closeout_cancels_scheduled_inspection
    """
    lab, pi = create_lab_with_pi(name="Lab I", department="Biology", building="Hall B",
                                 room="204")
    inspection = create_inspection(lab["id"], inspector_id="insp-1",
                                   scheduled_start="2026-08-12T09:00:00Z",
                                   scheduled_end="2026-08-12T10:00:00Z")
    insp_version_before = inspection["version"]

    closed = validate_success(api.closeout_lab(lab["id"], make_pi_headers(pi["id"])), 200)
    assert closed["status"] == "CLOSING"

    insp_after = get_inspection(inspection["id"])
    assert insp_after["status"] == "CANCELLED", (
        "closeout flips the lab's SCHEDULED inspections to CANCELLED"
    )
    assert insp_after["version"] == insp_version_before + 1
