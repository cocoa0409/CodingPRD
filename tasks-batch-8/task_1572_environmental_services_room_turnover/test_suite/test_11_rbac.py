"""RBAC claims: role denials, capability checks, identity, segregation of duties."""
from test_helpers import (
    ApiErrorId,
    BOGUS_UUID,
    CLOCK_T0800,
    api_client,
    build_user_headers,
    create_bed_payload,
    create_clean_request_payload,
    create_placement_demand_payload,
    create_supply_item_payload,
    create_unit_payload,
    get_success_data,
    make_auditor_headers,
    make_technician_headers,
    set_clock,
    setup_basic_scenario,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_bed,
    create_request,
    create_standard,
    create_staff,
    create_technician,
    create_unit,
    seed_supplies,
    start_request,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
IP = TEST_USERS["ip_headers"]
ANY = TEST_USERS["any_headers"]


def test_cross_role_write_denials(api):
    """PRD §2.1: "Access to each operation is restricted to the roles listed
    for it in §4; a call made with a role outside that list is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/cross_role_write_denials
    """
    set_clock(CLOCK_T0800)
    t1 = create_technician("T1")
    a1 = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")

    denials = [
        # units are EVSAdministrator-only
        api.create_unit(create_unit_payload(unit_code="UX", display_name="Nope"), DISPATCHER),
        # clean-request creation is EVSDispatcher-only (admin is NOT a superset)
        api.create_clean_request(
            create_clean_request_payload(bed_id=BOGUS_UUID), ADMIN
        ),
        # discharge is BedPlacementCoordinator-only
        api.discharge_bed(BOGUS_UUID, {}, ADMIN),
        # audit submission is QualityAuditor-only
        api.create_quality_audit(
            {"clean_request_id": BOGUS_UUID, "audit_method": "ATP_SWAB", "rlu_reading": 100},
            make_technician_headers(t1["id"]),
        ),
        # demand creation is BedPlacementCoordinator-only
        api.create_placement_demand(
            create_placement_demand_payload(unit_id=BOGUS_UUID),
            make_auditor_headers(a1["id"]),
        ),
        # outbreak declaration is InfectionPreventionist-only
        api.create_outbreak_event(
            {"unit_id": BOGUS_UUID, "pathogen_class": "MRSA"}, COORDINATOR
        ),
        # audit void is InfectionPreventionist-only
        api.void_quality_audit(BOGUS_UUID, ADMIN),
        # restock is EVSAdministrator-only
        api.restock_supply_item(BOGUS_UUID, {"quantity": 5}, DISPATCHER),
        # pull is EVSTechnician-only
        api.pull_clean_request(DISPATCHER),
        # maintenance windows are EVSAdministrator-only
        api.create_maintenance_window(
            {
                "bed_id": BOGUS_UUID,
                "start_at": "2026-08-01T10:00:00Z",
                "end_at": "2026-08-01T11:00:00Z",
            },
            COORDINATOR,
        ),
    ]
    for resp in denials:
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_segregation_of_duties_auditor_cannot_audit_own_clean(api):
    """PRD §3.6: "Segregation of duties is enforced at the gate: the audit's
    `auditor_id` is taken from the acting auditor's `X-User-ID`, and if it
    equals the request's `last_completed_by_staff_id` the submission is
    rejected with `ERR_AUDITOR_IS_CLEANER` — no one may verify their own work."

    Design: Corner/rbac/segregation_of_duties_auditor_cannot_audit_own_clean
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    seed_supplies("DISINFECTANT", "CLOTH")
    # T1 holds BOTH capabilities.
    t1 = create_staff("T1", capabilities=("CLEAN", "AUDIT"))
    a1 = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")
    get_success_data(api.clock_in_staff(t1["id"], make_technician_headers(t1["id"])))
    bed = create_bed(unit["id"])

    req = create_request(bed["id"], "ROUTINE")
    assign_request(req["id"], t1["id"])
    start_request(req["id"], t1["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(req["id"], t1["id"])

    # T1 auditing their own clean -> rejected.
    r = api.create_quality_audit(
        {"clean_request_id": req["id"], "audit_method": "ATP_SWAB", "rlu_reading": 100},
        make_auditor_headers(t1["id"]),
    )
    validate_error(r, ApiErrorId.ERR_AUDITOR_IS_CLEANER)

    after_reject = get_success_data(api.get_clean_request(req["id"], ANY))
    assert after_reject["status"] == "PENDING_QA"

    # Independent auditor's identical reading succeeds.
    ok = validate_success(
        api.create_quality_audit(
            {"clean_request_id": req["id"], "audit_method": "ATP_SWAB", "rlu_reading": 100},
            make_auditor_headers(a1["id"]),
        ),
        201,
    )
    assert ok["result"] == "PASS"
    verified = get_success_data(api.get_clean_request(req["id"], ANY))
    assert verified["status"] == "VERIFIED"


def test_entity_backed_role_capability_enforced(api):
    """PRD §2.1: "When `X-User-Role` is `EVSTechnician`, `X-User-ID` is the
    `id` of the acting `StaffMember`, and ownership checks on any resource that
    references a `StaffMember` compare the resource's foreign-key field to
    `X-User-ID`; the identified staff member's `capabilities` must include
    `CLEAN`, otherwise the call is rejected with
    `ERR_ROLE_CAPABILITY_MISMATCH`. When `X-User-Role` is `QualityAuditor`,
    `X-User-ID` is likewise the `id` of the acting `StaffMember`, whose
    `capabilities` must include `AUDIT`, again enforced with
    `ERR_ROLE_CAPABILITY_MISMATCH`."

    Design: Corner/rbac/entity_backed_role_capability_enforced
    """
    set_clock(CLOCK_T0800)
    a1 = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")
    t1 = create_technician("T1")

    # AUDIT-only member acting as EVSTechnician.
    r1 = api.clock_in_staff(a1["id"], make_technician_headers(a1["id"]))
    validate_error(r1, ApiErrorId.ERR_ROLE_CAPABILITY_MISMATCH)

    # CLEAN-only member acting as QualityAuditor.
    r2 = api.create_quality_audit(
        {"clean_request_id": BOGUS_UUID, "audit_method": "ATP_SWAB", "rlu_reading": 100},
        make_auditor_headers(t1["id"]),
    )
    validate_error(r2, ApiErrorId.ERR_ROLE_CAPABILITY_MISMATCH)


def test_staff_self_service_identity_enforced(api):
    """PRD §3.4: "Shift management is strictly self-service: clocking in,
    clocking out, and starting or ending a break all require the caller's
    `X-User-ID` to equal the path `staff_id`, with any mismatch rejected as
    `ERR_STAFF_IDENTITY_MISMATCH`."

    Design: Corner/rbac/staff_self_service_identity_enforced
    """
    set_clock(CLOCK_T0800)
    t1 = create_technician("T1")
    t2 = create_technician("T2")

    r_in = api.clock_in_staff(t2["id"], make_technician_headers(t1["id"]))
    validate_error(r_in, ApiErrorId.ERR_STAFF_IDENTITY_MISMATCH)
    r_break = api.break_start_staff(t2["id"], make_technician_headers(t1["id"]))
    validate_error(r_break, ApiErrorId.ERR_STAFF_IDENTITY_MISMATCH)
    r_out = api.clock_out_staff(t2["id"], make_technician_headers(t1["id"]))
    validate_error(r_out, ApiErrorId.ERR_STAFF_IDENTITY_MISMATCH)

    t2_after = get_success_data(api.get_staff(t2["id"], ANY))
    assert t2_after["shift_status"] == "OFF_SHIFT"


def test_start_complete_require_assigned_technician(api):
    """PRD §3.5: "The assigned technician — and only that technician — drives
    execution; a start or complete attempted by anyone else is rejected with
    `ERR_NOT_ASSIGNED_TECHNICIAN`."

    Design: Corner/rbac/start_complete_require_assigned_technician
    """
    ctx = setup_basic_scenario()
    t2 = create_technician("T2")
    get_success_data(api.clock_in_staff(t2["id"], make_technician_headers(t2["id"])))

    req = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(req["id"], ctx["tech"]["id"])

    r_start = api.start_clean_request(req["id"], make_technician_headers(t2["id"]))
    validate_error(r_start, ApiErrorId.ERR_NOT_ASSIGNED_TECHNICIAN)
    r_complete = api.complete_clean_request(req["id"], make_technician_headers(t2["id"]))
    validate_error(r_complete, ApiErrorId.ERR_NOT_ASSIGNED_TECHNICIAN)

    # The assignee's identical start succeeds.
    started = validate_success(
        api.start_clean_request(req["id"], make_technician_headers(ctx["tech"]["id"]))
    )
    assert started["status"] == "IN_PROGRESS"
    bed = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
    assert bed["bed_status"] == "CLEAN_IN_PROGRESS"
