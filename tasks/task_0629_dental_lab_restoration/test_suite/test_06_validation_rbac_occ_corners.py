"""Breadth (corner) tests: business validations (material inactive, capability
mismatch, route capacity, unit not warrantable), endpoint actions (confirm-
delivery precondition, remake deny), max-revisions error, RBAC denials, and the
mill-machine OCC stale-version rule.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    build_user_headers,
    TEST_USERS, make_doctor_headers,
    create_restoration_payload, create_mill_job_payload, create_route_stop_payload,
    create_remake_request_payload, tryin_verdict_payload, create_case_payload,
    create_doctor, create_material, create_machine, create_route, create_case,
    create_restoration, set_clock,
    setup_submitted_case, setup_case_at_tryin, setup_shipped_case, setup_delivered_case,
    get_case,
)
from test_helpers.fixtures import list_units

ADMIN = TEST_USERS["labadmin_headers"]
TECH = TEST_USERS["labtech_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── validations ─────────────────────────────────────────────────────
def test_material_inactive_on_restoration_create(api):
    """PRD §3.2: "The selected material must have is_active true at the moment the
    restoration is created; choosing an inactive material is rejected with
    ERR_MATERIAL_INACTIVE (HTTP 422)."

    Design: Corner/validations/material_inactive_on_restoration_create
    """
    set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=8000, fabrication_process="MILLED",
                              is_active=False)
    case = create_case(doctor["id"])
    res = api.create_restoration(
        case["id"], create_restoration_payload(material["id"], restoration_type="CROWN",
                                               unit_count=1), TECH)
    validate_error(res, "ERR_MATERIAL_INACTIVE")


def test_machine_capability_mismatch_on_milljob(api):
    """PRD §3.4: "The machine's capability must equal the unit's material
    fabrication_process; a printer cannot take a milled unit and vice versa, and a
    mismatch is rejected with ERR_MACHINE_CAPABILITY_MISMATCH (HTTP 422)."

    Design: Corner/validations/machine_capability_mismatch_on_milljob
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "ALIGNER", "unit_count": 2,
                            "requested_shade": "NA"}],
        material_overrides={"base_unit_price_cents": 5000, "fabrication_process": "PRINTED"},
    )
    milled_machine = create_machine(capability="MILLED")
    unit = built["units"][0]
    res = api.create_mill_job(
        create_mill_job_payload(unit["id"], milled_machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=60), SCHED)
    validate_error(res, "ERR_MACHINE_CAPABILITY_MISMATCH")


def test_route_at_capacity_boundary(api):
    """PRD §3.7: "a route may not exceed its max_stops: attaching a stop when the
    route's stop_count already equals max_stops is rejected with
    ERR_ROUTE_AT_CAPACITY (HTTP 422)."

    Design: Corner/validations/route_at_capacity_boundary
    """
    set_clock()
    doctor = create_doctor()
    route = create_route(service_date="2026-01-01T00:00:00Z", max_stops=2, buffer_minutes=30)
    c1 = create_case(doctor["id"], intake_method="RX_PAPER")
    c2 = create_case(doctor["id"], intake_method="RX_PAPER")
    c3 = create_case(doctor["id"], intake_method="RX_PAPER")
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], c1["id"],
                                  window_start_at="2026-01-01T09:00:00Z"), SCHED))
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], c2["id"],
                                  window_start_at="2026-01-01T11:00:00Z"), SCHED))
    res = api.create_route_stop(
        create_route_stop_payload(route["id"], c3["id"],
                                  window_start_at="2026-01-01T13:00:00Z"), SCHED)
    validate_error(res, "ERR_ROUTE_AT_CAPACITY")
    assert get_success_data(api.get_courier_route(route["id"], SCHED))["stop_count"] == 2


def test_unit_not_warrantable_on_remake_request(api):
    """PRD §3.9: "The targeted unit must be one that is in PASSED on a DELIVERED
    case - a remake aimed at any unit that is not PASSED, or whose case is not
    DELIVERED, is rejected with ERR_UNIT_NOT_WARRANTABLE (HTTP 422)."

    Design: Corner/validations/unit_not_warrantable_on_remake_request
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "CROWN", "unit_count": 1}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    case = built["case"]                     # still in DESIGN, unit QUEUED
    unit = built["units"][0]
    res = api.create_remake_request(
        case["id"], create_remake_request_payload(unit["id"], reason="FRACTURE"),
        make_doctor_headers(built["doctor"]["id"]))
    validate_error(res, "ERR_UNIT_NOT_WARRANTABLE")


# ─── endpoints ───────────────────────────────────────────────────────
def test_confirm_delivery_requires_completed_stop(api):
    """PRD §3.7: "Confirming delivery of a case advances it from SHIPPED to
    DELIVERED, and it requires the case to have a route stop in COMPLETED."

    Design: Corner/endpoints/confirm_delivery_requires_completed_stop
    """
    built = setup_shipped_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]                     # SHIPPED; route stop still PLANNED
    res = api.confirm_delivery(case["id"], SCHED)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_case(case["id"])["status"] == "SHIPPED"


def test_remake_deny_terminalizes_request(api):
    """PRD §3.9: "Alternatively the administrator may deny a remake request,
    moving it from OPEN to DENIED."

    Design: Corner/endpoints/remake_deny_terminalizes_request
    """
    built = setup_delivered_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    unit = built["units"][0]
    rr = get_success_data(api.create_remake_request(
        case["id"], create_remake_request_payload(unit["id"], reason="SHADE_MISMATCH"),
        make_doctor_headers(built["doctor"]["id"])))
    res = api.deny_remake_request(rr["id"], ADMIN)
    denied = validate_success(res, 200)
    assert denied["status"] == "DENIED"
    # No replacement spawned; original unit stays PASSED.
    assert get_success_data(api.get_fabrication_unit(unit["id"], ADMIN))["status"] == "PASSED"


# ─── errors ──────────────────────────────────────────────────────────
def test_max_revisions_exceeded_owner(api):
    """PRD §3.5: "This is permitted only while revision_count is strictly below
    the maximum of three revisions; a REVISE recorded when revision_count already
    equals that maximum is rejected with ERR_MAX_REVISIONS_EXCEEDED (HTTP 422)."

    Design: Corner/errors/max_revisions_exceeded_triggerable
    """
    from test_helpers import setup_case_at_tryin_with_revisions
    built = setup_case_at_tryin_with_revisions(
        3, material_overrides={"base_unit_price_cents": 12000,
                               "fabrication_process": "MILLED"})
    case = built["case"]
    assert case["revision_count"] == 3
    res = api.tryin_verdict(
        case["id"],
        tryin_verdict_payload("REVISE", case["version"],
                              revise_restoration_ids=[built["restoration"]["id"]]),
        make_doctor_headers(built["doctor"]["id"]))
    validate_error(res, "ERR_MAX_REVISIONS_EXCEEDED")


# ─── rbac ────────────────────────────────────────────────────────────
def test_labtech_cannot_record_tryin_verdict(api):
    """PRD §2.1: "When a known, authenticated role attempts an operation it is not
    permitted to invoke, the request is rejected with ERR_FORBIDDEN_ROLE." PRD §4
    routing summary lists POST /cases/{id}/tryin-verdict as authorized for Doctor
    only.

    Design: Corner/rbac/labtech_cannot_record_tryin_verdict
    """
    built = setup_case_at_tryin(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    res = api.tryin_verdict(
        case["id"], tryin_verdict_payload("ACCEPT", case["version"]), TECH)
    validate_error(res, "ERR_FORBIDDEN_ROLE")
    assert get_case(case["id"])["status"] == "TRY_IN"


def test_scheduler_cannot_create_doctor(api):
    """PRD §2.1: "When a known, authenticated role attempts an operation it is not
    permitted to invoke, the request is rejected with ERR_FORBIDDEN_ROLE." PRD §4
    routing summary lists POST /doctors as authorized for LabAdmin only.

    Design: Corner/rbac/scheduler_cannot_create_doctor
    """
    from test_helpers import create_doctor_payload
    res = api.create_doctor(create_doctor_payload(), SCHED)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of
    these five known roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    res = api.list_doctors(build_user_headers("nobody", "NobodyUnknownRole"))
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── cross_cutting_complexity_layers: OCC on machine version ─────────
def test_occ_stale_machine_version_on_milljob_start(api):
    """PRD §2.7: "starting a mill job requires the request to carry
    expected_machine_version, a non-optional field whose value must equal the
    target MillMachine's current version. When another job has already started on
    (and thereby advanced the version of) that machine, a start request carrying
    the now-outdated expected_machine_version is rejected with
    ERR_STALE_MACHINE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_machine_version_on_milljob_start
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "BRIDGE", "unit_count": 2}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    machine = create_machine()
    mach_v0 = machine["version"]
    units = built["units"]
    job1 = get_success_data(api.create_mill_job(
        create_mill_job_payload(units[0]["id"], machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=60), SCHED))
    job2 = get_success_data(api.create_mill_job(
        create_mill_job_payload(units[1]["id"], machine["id"],
                                start_at="2026-01-01T10:00:00Z", duration_minutes=60), SCHED))
    get_success_data(api.start_fabrication(built["case"]["id"], TECH))
    # First start advances the machine version.
    get_success_data(api.start_mill_job(
        job1["id"], {"expected_machine_version": mach_v0}, SCHED))
    # Second start carries the now-stale pre-start version.
    res = api.start_mill_job(job2["id"], {"expected_machine_version": mach_v0}, SCHED)
    validate_error(res, "ERR_STALE_MACHINE_VERSION")
