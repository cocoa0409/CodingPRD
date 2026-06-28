"""Scheduling-constraint tests: mill-job half-open interval overlap, route-stop
buffered-window conflict, cross-entity preconditions (PLANNED route stop /
AVAILABLE machine), SLA strict-boundary, empty-fabrication boundary, and the two
validation-priority conflicts.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_error_is_one_of,
    TEST_USERS, make_doctor_headers, NON_EXISTENT_UUID,
    create_mill_job_payload, create_route_stop_payload, tryin_verdict_payload,
    create_case_payload, create_restoration_payload,
    setup_submitted_case, setup_case_at_tryin, setup_case_at_tryin_with_revisions,
    get_invoice_for_case, get_case, set_clock,
    create_doctor, create_material, create_machine, create_route, create_case,
    create_restoration,
)
from test_helpers.fixtures import (
    list_units, _schedule_and_mill_units, accept_case,
)

ADMIN = TEST_USERS["labadmin_headers"]
TECH = TEST_USERS["labtech_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── resource_temporal_overlap: mill-job half-open intervals ──────────
def test_milljob_overlap_rejected(api):
    """PRD §3.4: "A new job's half-open interval must also not intersect any
    non-cancelled job already booked on the same machine; an overlap is rejected
    with ERR_MACHINE_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/milljob_halfopen_interval_overlap
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "BRIDGE", "unit_count": 2}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    machine = create_machine()
    units = built["units"]
    # First job occupies [09:00, 10:30).
    get_success_data(api.create_mill_job(
        create_mill_job_payload(units[0]["id"], machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=90), SCHED))
    # Overlapping [10:00, 11:00) must be rejected.
    res = api.create_mill_job(
        create_mill_job_payload(units[1]["id"], machine["id"],
                                start_at="2026-01-01T10:00:00Z", duration_minutes=60), SCHED)
    validate_error(res, "ERR_MACHINE_DOUBLE_BOOKED")


def test_milljob_adjacent_interval_accepted(api):
    """PRD §3.4: "Two intervals that merely touch end-to-end - one ending exactly
    as the next begins - do not intersect, because the interval excludes its own
    end_at."

    Design: Difficulty/resource_temporal_overlap/milljob_halfopen_interval_overlap
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "BRIDGE", "unit_count": 2}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    machine = create_machine()
    units = built["units"]
    get_success_data(api.create_mill_job(
        create_mill_job_payload(units[0]["id"], machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=90), SCHED))
    # Adjacent [10:30, 11:30) touches the first job's end_at and must succeed.
    res = api.create_mill_job(
        create_mill_job_payload(units[1]["id"], machine["id"],
                                start_at="2026-01-01T10:30:00Z", duration_minutes=60), SCHED)
    validate_success(res, 201)


# ─── resource_temporal_overlap: route-stop buffered windows ───────────
def test_routestop_buffered_window_conflict_rejected(api):
    """PRD §3.7: "the new stop's window, expanded on both the leading and
    trailing sides by the route's buffer_minutes, must not overlap the
    (unexpanded) window of any non-cancelled stop already on the same route; a
    conflict is rejected with ERR_ROUTE_WINDOW_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/routestop_buffered_window_conflict
    """
    set_clock()
    doctor = create_doctor()
    route = create_route(service_date="2026-01-01T00:00:00Z", max_stops=5, buffer_minutes=30)
    case_a = create_case(doctor["id"], intake_method="RX_PAPER")
    case_b = create_case(doctor["id"], intake_method="RX_PAPER")
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], case_a["id"],
                                  window_start_at="2026-01-01T13:00:00Z",
                                  window_minutes=20), SCHED))
    # New stop at [13:40,14:00): 20-min gap < 30-min buffer -> conflict.
    res = api.create_route_stop(
        create_route_stop_payload(route["id"], case_b["id"],
                                  window_start_at="2026-01-01T13:40:00Z",
                                  window_minutes=20), SCHED)
    validate_error(res, "ERR_ROUTE_WINDOW_CONFLICT")


def test_routestop_buffer_satisfied_accepted(api):
    """PRD §3.7: "the new stop's window, expanded on both the leading and
    trailing sides by the route's buffer_minutes, must not overlap the
    (unexpanded) window of any non-cancelled stop already on the same route".

    Design: Difficulty/resource_temporal_overlap/routestop_buffered_window_conflict
    """
    set_clock()
    doctor = create_doctor()
    route = create_route(service_date="2026-01-01T00:00:00Z", max_stops=5, buffer_minutes=30)
    case_a = create_case(doctor["id"], intake_method="RX_PAPER")
    case_b = create_case(doctor["id"], intake_method="RX_PAPER")
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], case_a["id"],
                                  window_start_at="2026-01-01T13:00:00Z",
                                  window_minutes=20), SCHED))
    # New stop at [13:55,14:15): 35-min gap >= 30-min buffer -> accepted.
    res = api.create_route_stop(
        create_route_stop_payload(route["id"], case_b["id"],
                                  window_start_at="2026-01-01T13:55:00Z",
                                  window_minutes=20), SCHED)
    validate_success(res, 201)


# ─── cross_entity_state_dependency ───────────────────────────────────
def test_accept_requires_planned_routestop(api):
    """PRD §3.5: "A verdict of ACCEPT ships the case from TRY_IN to SHIPPED.
    Acceptance requires three things: every billable unit on the case is in
    PASSED or MILLED, the expected_case_version matches per §2.7, and the case
    already has a route stop in PLANNED."

    Design: Difficulty/cross_entity_state_dependency/case_accept_requires_planned_routestop
    """
    built = setup_case_at_tryin(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    # No route stop attached -> ACCEPT blocked.
    res = api.tryin_verdict(
        case["id"], tryin_verdict_payload("ACCEPT", case["version"]),
        make_doctor_headers(built["doctor"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    assert get_case(case["id"])["status"] == "TRY_IN"


def test_accept_succeeds_with_planned_routestop(api):
    """PRD §3.5: "Acceptance requires three things: every billable unit on the
    case is in PASSED or MILLED, the expected_case_version matches per §2.7, and
    the case already has a route stop in PLANNED." PRD §3.5: "A verdict of ACCEPT
    ships the case from TRY_IN to SHIPPED."

    Design: Difficulty/cross_entity_state_dependency/case_accept_requires_planned_routestop
    """
    built = setup_case_at_tryin(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    route = create_route()
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], case["id"]), SCHED))
    res = api.tryin_verdict(
        case["id"], tryin_verdict_payload("ACCEPT", case["version"]),
        make_doctor_headers(built["doctor"]["id"]))
    shipped = validate_success(res, 200)
    assert shipped["status"] == "SHIPPED"


def test_milljob_start_requires_available_machine(api):
    """PRD §3.4: "Starting requires the machine's status to be AVAILABLE and
    requires the request's expected_machine_version to match the machine's
    current version per §2.7". PRD §3.4: "While a machine is in MAINTENANCE it
    fails the start precondition, since starts require an AVAILABLE machine."

    Design: Difficulty/cross_entity_state_dependency/milljob_start_requires_available_machine
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "CROWN", "unit_count": 1}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    machine = create_machine()
    unit = built["units"][0]
    job = get_success_data(api.create_mill_job(
        create_mill_job_payload(unit["id"], machine["id"]), SCHED))
    get_success_data(api.start_fabrication(built["case"]["id"], TECH))
    get_success_data(api.machine_maintenance(machine["id"], SCHED))
    # Taking the machine into MAINTENANCE bumps its version (PRD §3.4), so read
    # the CURRENT version after maintenance: this makes the OCC check pass so the
    # AVAILABLE-machine precondition is the only failing check and surfaces
    # cleanly as ERR_INVALID_STATE (PRD §3.4: "While a machine is in MAINTENANCE
    # it fails the start precondition, since starts require an AVAILABLE machine").
    machine_now = get_success_data(api.get_mill_machine(machine["id"], SCHED))

    res = api.start_mill_job(
        job["id"], {"expected_machine_version": machine_now["version"]}, SCHED)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_success_data(api.get_mill_job(job["id"], SCHED))["status"] == "SCHEDULED"


def test_milljob_start_succeeds_on_available_machine(api):
    """PRD §3.4: "Starting a scheduled job moves the job from SCHEDULED to
    RUNNING and, as a paired effect, advances its unit from QUEUED to MILLING.
    Starting requires the machine's status to be AVAILABLE and requires the
    request's expected_machine_version to match the machine's current version per
    §2.7; on a successful start the machine's version increments by one."

    Design: Difficulty/cross_entity_state_dependency/milljob_start_requires_available_machine
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "CROWN", "unit_count": 1}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    machine = create_machine()
    unit = built["units"][0]
    job = get_success_data(api.create_mill_job(
        create_mill_job_payload(unit["id"], machine["id"]), SCHED))
    get_success_data(api.start_fabrication(built["case"]["id"], TECH))
    machine_now = get_success_data(api.get_mill_machine(machine["id"], SCHED))
    res = api.start_mill_job(
        job["id"], {"expected_machine_version": machine_now["version"]}, SCHED)
    started = validate_success(res, 200)
    assert started["status"] == "RUNNING"


# ─── boundary_precision_check: SLA strict greater-than ───────────────
def test_sla_not_breached_at_exact_deadline(api):
    """PRD §3.6: "The case's sla_breached flag is set to true exactly when
    shipped_at is strictly later than promised_ready_at; shipping at precisely
    the promised instant is not a breach."

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than_boundary
    """
    # crown promised 2026-01-06T00:00:00Z; ship exactly at that instant -> no breach.
    built = setup_case_at_tryin(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    route = create_route(service_date="2026-01-06T00:00:00Z")
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], case["id"],
                                  window_start_at="2026-01-06T09:00:00Z"), SCHED))
    set_clock("2026-01-06T00:00:00Z")
    shipped = accept_case(case, built["doctor"]["id"])
    assert shipped["sla_breached"] is False, (
        "shipping exactly at promised_ready_at is not a breach (strict >)"
    )
    invoice = get_invoice_for_case(case["id"])
    assert invoice["sla_credit_cents"] == 0
    assert invoice["total_cents"] == 12990


def test_sla_breached_one_hour_late(api):
    """PRD §3.6: "The case's sla_breached flag is set to true exactly when
    shipped_at is strictly later than promised_ready_at; shipping at precisely
    the promised instant is not a breach."

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than_boundary
    """
    built = setup_case_at_tryin(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    route = create_route(service_date="2026-01-06T00:00:00Z")
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], case["id"],
                                  window_start_at="2026-01-06T09:00:00Z"), SCHED))
    set_clock("2026-01-06T01:00:00Z")
    shipped = accept_case(case, built["doctor"]["id"])
    assert shipped["sla_breached"] is True
    invoice = get_invoice_for_case(case["id"])
    assert invoice["sla_credit_cents"] == 2400


# ─── boundary_precision_check: empty fabrication ─────────────────────
def test_submit_empty_case_rejected(api):
    """PRD §3.3: "The submission is rejected before anything else if the case has
    no restoration carrying at least one unit - a case with zero billable units
    cannot be submitted, and the attempt returns ERR_EMPTY_FABRICATION (HTTP
    422)."

    Design: Difficulty/boundary_precision_check/empty_fabrication_zero_units_boundary
    """
    set_clock()
    doctor = create_doctor()
    case = create_case(doctor["id"], intake_method="RX_PAPER")
    res = api.submit_case(case["id"], TECH)
    validate_error(res, "ERR_EMPTY_FABRICATION")
    assert get_case(case["id"])["status"] == "INTAKE"


def test_submit_with_one_restoration_succeeds(api):
    """PRD §3.3: "Submitting a case advances it from INTAKE to DESIGN". PRD §3.3:
    "Given at least one restoration, the transition additionally requires that
    every restoration on the case references a material that is currently
    active."

    Design: Difficulty/boundary_precision_check/empty_fabrication_zero_units_boundary
    """
    set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    case = create_case(doctor["id"])
    create_restoration(case["id"], material["id"], restoration_type="CROWN", unit_count=1)
    res = api.submit_case(case["id"], TECH)
    submitted = validate_success(res, 200)
    assert submitted["status"] == "DESIGN"


# ─── priority_pair_validation_conflict ───────────────────────────────
def test_existence_or_state_precedes_capability_check(api):
    """PRD §2.9: "then existence of every path id and body foreign key, resolved
    left to right (ERR_NOT_FOUND); then that the target resource is in a state
    from which the requested transition is defined (ERR_INVALID_STATE, HTTP 409);
    ... then the domain business-safety, temporal, capacity, and referential
    checks described throughout §3".

    Design: Difficulty/priority_pair_validation_conflict/state_before_machine_capability_on_milljob
    """
    set_clock()
    doctor = create_doctor()
    printed_mat = create_material(base_unit_price_cents=5000, fabrication_process="PRINTED")
    milled_machine = create_machine(capability="MILLED")
    case = create_case(doctor["id"])
    create_restoration(case["id"], printed_mat["id"], restoration_type="ALIGNER",
                       unit_count=4, requested_shade="NA")
    # fabrication_unit_id is a Case id (never a unit) AND the machine capability
    # mismatches. Existence (404) / state checks must pre-empt the capability
    # (422) business-safety check.
    res = api.create_mill_job(
        create_mill_job_payload(case["id"], milled_machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=60), SCHED)
    validate_error_is_one_of(res, ["ERR_NOT_FOUND", "ERR_INVALID_STATE"])


def test_ownership_precedes_max_revisions_check(api):
    """PRD §2.9: "then, for the Doctor-owned case-cancel and try-in-verdict
    operations, case ownership (ERR_NOT_CASE_OWNER); then existence of every path
    id and body foreign key ... ; then that the target resource is in a state
    from which the requested transition is defined ... ; then the domain
    business-safety, temporal, capacity, and referential checks described
    throughout §3". PRD §2.1: "the acting X-User-ID must equal the target case's
    doctor_id; if it does not, the request is rejected with ERR_NOT_CASE_OWNER".

    Design: Difficulty/priority_pair_validation_conflict/ownership_before_max_revisions_on_verdict
    """
    # Owner's case at TRY_IN with revision_count == MAX_REVISIONS (3).
    built = setup_case_at_tryin_with_revisions(
        3, material_overrides={"base_unit_price_cents": 12000,
                               "fabrication_process": "MILLED"})
    case = built["case"]
    assert case["revision_count"] == 3
    other = create_doctor()
    # Non-owner doctor attempts a REVISE -> ownership (403) pre-empts max-revisions (422).
    res = api.tryin_verdict(
        case["id"],
        tryin_verdict_payload("REVISE", case["version"],
                              revise_restoration_ids=[built["restoration"]["id"]]),
        make_doctor_headers(other["id"]))
    validate_error(res, "ERR_NOT_CASE_OWNER")


def test_capability_check_fires_when_existence_and_state_pass(api):
    """PRD §2.9: "then the domain business-safety, temporal, capacity, and
    referential checks described throughout §3". PRD §3.4: "The machine's
    capability must equal the unit's material fabrication_process; a printer
    cannot take a milled unit and vice versa, and a mismatch is rejected with
    ERR_MACHINE_CAPABILITY_MISMATCH (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_machine_capability_on_milljob
    """
    # Valid QUEUED PRINTED unit (existence + state OK) on a MILLED machine: only
    # the business-safety capability check can fail, so it surfaces.
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


def test_max_revisions_fires_for_owner_when_ownership_passes(api):
    """PRD §3.5: "This is permitted only while revision_count is strictly below
    the maximum of three revisions; a REVISE recorded when revision_count already
    equals that maximum is rejected with ERR_MAX_REVISIONS_EXCEEDED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/ownership_before_max_revisions_on_verdict
    """
    # When the OWNER (ownership check passes) sends REVISE at the cap, the
    # lower-priority business_constraint check is what surfaces.
    built = setup_case_at_tryin_with_revisions(
        3, material_overrides={"base_unit_price_cents": 12000,
                               "fabrication_process": "MILLED"})
    case = built["case"]
    res = api.tryin_verdict(
        case["id"],
        tryin_verdict_payload("REVISE", case["version"],
                              revise_restoration_ids=[built["restoration"]["id"]]),
        make_doctor_headers(built["doctor"]["id"]))
    validate_error(res, "ERR_MAX_REVISIONS_EXCEEDED")
