"""Role and identity enforcement: shared reads, exclusive writes, the two
header defects that collapse into one 401, actor binding on the operating
surgeon, and segregation of duties on a morbidity review.
"""
from test_helpers import (
    ADMIN,
    BENEFITS,
    INVENTORY,
    SCHEDULER,
    ApiErrorId,
    api_client as api,
    assert_pagination_meta,
    build_user_headers,
    headers_for_role,
    make_anesthesia_coordinator_headers,
    make_quality_reviewer_headers,
    make_surgeon_headers,
    parse_iso,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_rbac_shared_reads_are_open_to_all_seven_roles():
    """One case read succeeds under every recognised role and mutates nothing.

    PRD: "The system recognises exactly seven roles: `PracticeAdministrator`,
    `SchedulingCoordinator`, `BenefitsSpecialist`, `InventoryManager`,
    `Surgeon`, `AnesthesiaCoordinator`, and `QualityReviewer`."

    PRD: "The authorised-role column is exhaustive: a caller presenting any
    other role receives `ERR_ROLE_NOT_PERMITTED`, and a caller presenting no
    identity at all receives `ERR_UNAUTHENTICATED` before role evaluation
    begins."

    Design: Corner/rbac/shared_reads_are_open_to_all_seven_roles
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Shared Read OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Public",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-20T13:00:00Z",
                "planned_end": "2026-09-20T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    case_id = case["id"]

    readers = [
        ("PracticeAdministrator", ADMIN),
        ("SchedulingCoordinator", SCHEDULER),
        ("BenefitsSpecialist", BENEFITS),
        ("InventoryManager", INVENTORY),
        ("Surgeon", make_surgeon_headers(surgeon["id"])),
        ("AnesthesiaCoordinator", make_anesthesia_coordinator_headers(surgeon["id"])),
        ("QualityReviewer", make_quality_reviewer_headers(surgeon["id"])),
    ]
    for role, headers in readers:
        read = validate_success(api.get_surgical_case(case_id, headers))
        assert read["id"] == case_id, f"{role} must read the same case row"
        assert read["scheduling_status"] == "DRAFT", (
            f"{role} sees the same scheduling_status"
        )
        assert read["version"] == 1, f"a read by {role} must not mutate the row"


def test_rbac_exclusive_write_endpoints_refuse_foreign_roles():
    """A foreign role is refused 403 before the body is ever validated.

    PRD: "Once the role is recognised, the system checks it against the
    authorised-role list published for that endpoint in §4; a role that does not
    appear there is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD: "These two checks run before any other work: before path identifiers
    are resolved, before the body is parsed, and before any business rule is
    consulted."

    Design: Corner/rbac/exclusive_write_endpoints_refuse_foreign_roles
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Role Fence OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Fence",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    well_formed = {
        "practice_id": prac_id,
        "patient_id": patient["id"],
        "primary_surgeon_id": surgeon["id"],
        "planned_anesthesia_level": "LOCAL_ONLY",
        "procedure_category": "IMPLANT",
        "planned_start": "2026-09-20T13:00:00Z",
        "planned_end": "2026-09-20T14:00:00Z",
        "total_charge_cents": 90000,
    }
    validate_error(
        api.create_surgical_case(well_formed, BENEFITS),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    inverted = dict(
        well_formed,
        planned_start="2026-09-20T14:00:00Z",
        planned_end="2026-09-20T13:00:00Z",
    )
    validate_error(
        api.create_surgical_case(inverted, BENEFITS),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.run_compliance_sweep({}, INVENTORY),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Sneaky Hire",
                "role_type": "RECOVERY_NURSE",
            },
            make_surgeon_headers(surgeon["id"]),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    cases, cases_meta = validate_paginated(
        api.list_surgical_cases(ADMIN, params={"practice_id": prac_id})
    )
    assert_pagination_meta(cases_meta, expected_total=0)
    assert cases == [], "no case was created by the refused writes"
    staff, staff_meta = validate_paginated(
        api.list_staff_members(ADMIN, params={"practice_id": prac_id})
    )
    assert_pagination_meta(staff_meta, expected_total=1)
    assert [member["full_name"] for member in staff] == ["Dr Alma Reyes"]


def test_rbac_missing_or_unknown_identity_headers_rejected():
    """An absent role, an unknown role, and an absent staff id all answer 401.

    PRD: "A request whose `X-User-Role` is missing or is not one of those seven
    spellings is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "For all three of these entity-backed roles `X-User-ID` is mandatory;
    its absence is an `ERR_UNAUTHENTICATED` condition, and a present-but-wrong
    value on an operation bound to a specific staff member yields
    `ERR_ACTOR_NOT_ASSIGNED` (HTTP 403)."

    Design: Corner/rbac/missing_or_unknown_identity_headers_rejected
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Identity OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Anon",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-20T13:00:00Z",
                "planned_end": "2026-09-20T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )

    no_role = build_user_headers(surgeon["id"], "Surgeon")
    del no_role["X-User-Role"]
    validate_error(
        api.get_surgical_case(case["id"], no_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    validate_error(
        api.get_surgical_case(case["id"], headers_for_role("OfficeManager")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    no_user_id = build_user_headers(surgeon["id"], "Surgeon")
    del no_user_id["X-User-ID"]
    validate_error(
        api.start_recovery(case["id"], {}, no_user_id),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    still_draft = validate_success(api.get_surgical_case(case["id"], ADMIN))
    assert still_draft["scheduling_status"] == "DRAFT", (
        "the header failure answered before the state machine was consulted"
    )


def test_rbac_only_the_bound_surgeon_may_run_the_case():
    """Holding the Surgeon role is not enough — the case names its own surgeon.

    PRD: "Only the case's own primary surgeon may do so: the acting
    `X-User-Role` must be `Surgeon` and `X-User-ID` must equal the case's
    `primary_surgeon_id`, or the answer is `ERR_ACTOR_NOT_ASSIGNED`."

    PRD: "The transition stamps `recovery_started_at` with the logical clock,
    moves `scheduling_status` from `CONFIRMED` to `IN_RECOVERY`, increments the
    case's `version`, and starts the interval during which the case genuinely
    occupies a recovery bay for `recovery_minutes_required` minutes."

    PRD: "Completion moves `scheduling_status` from `IN_RECOVERY` to the
    terminal `COMPLETED`, increments the case's `version`, frees the recovery
    bay for future capacity projections, and makes the case eligible to serve as
    the `prerequisite_case_id` of a staged successor — which is exactly what
    unblocks an orthognathic case waiting on a third-molar extraction."

    Design: Corner/rbac/only_the_bound_surgeon_may_run_the_case
    """
    set_clock("2026-09-13T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Binding OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]

    def hire(full_name, role_type):
        return validate_success(
            api.create_staff_member(
                {
                    "practice_id": prac_id,
                    "full_name": full_name,
                    "role_type": role_type,
                },
                ADMIN,
            ),
            201,
        )

    surgeon_a = hire("Dr Alma Reyes", "SURGEON")
    surgeon_b = hire("Dr Ben Ortiz", "SURGEON")
    author = hire("Nia Author", "ANESTHESIA_MONITOR")
    verifier = hire("Val Verifier", "ANESTHESIA_MONITOR")
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Bound",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    block = validate_success(
        api.create_block_time(
            {
                "practice_id": prac_id,
                "surgeon_id": surgeon_a["id"],
                "room_code": "OR-1",
                "block_start": "2026-09-14T13:00:00Z",
                "block_end": "2026-09-14T17:00:00Z",
                "release_deadline_hours": 48,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon_a["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-14T13:00:00Z",
                "planned_end": "2026-09-14T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    case_id = case["id"]
    evaluation = validate_success(
        api.create_evaluation(
            case_id,
            {
                "evaluator_staff_id": author["id"],
                "asa_class_recorded": 2,
                "airway_class_recorded": 2,
                "comorbidity_count": 0,
                "expected_case_version": case["version"],
            },
            make_anesthesia_coordinator_headers(author["id"]),
        ),
        201,
    )
    validate_success(
        api.sign_evaluation(
            evaluation["id"], {}, make_anesthesia_coordinator_headers(author["id"])
        )
    )
    set_clock("2026-09-14T07:00:00Z")
    validate_success(
        api.verify_evaluation(
            evaluation["id"],
            {
                "intent": "CLEAR",
                "fasting_solids_last_at": "2026-09-13T20:00:00Z",
                "fasting_clears_last_at": "2026-09-14T06:00:00Z",
                "escort_confirmed": False,
            },
            make_anesthesia_coordinator_headers(verifier["id"]),
        )
    )
    validate_success(api.hold_block(case_id, {"block_id": block["id"]}, SCHEDULER))
    held_block = validate_success(api.get_block_time(block["id"], SCHEDULER))
    confirmed = validate_success(
        api.confirm_case(
            case_id, {"expected_block_version": held_block["version"]}, SCHEDULER
        )
    )
    assert confirmed["scheduling_status"] == "CONFIRMED"
    set_clock("2026-09-14T13:00:00Z")

    validate_error(
        api.start_recovery(case_id, {}, make_surgeon_headers(surgeon_b["id"])),
        ApiErrorId.ERR_ACTOR_NOT_ASSIGNED.value,
    )
    assert (
        validate_success(api.get_surgical_case(case_id, ADMIN))["scheduling_status"]
        == "CONFIRMED"
    )

    recovering = validate_success(
        api.start_recovery(case_id, {}, make_surgeon_headers(surgeon_a["id"]))
    )
    assert recovering["scheduling_status"] == "IN_RECOVERY"
    assert parse_iso(recovering["recovery_started_at"]) == parse_iso(
        "2026-09-14T13:00:00Z"
    )

    validate_error(
        api.complete_case(case_id, {}, make_surgeon_headers(surgeon_b["id"])),
        ApiErrorId.ERR_ACTOR_NOT_ASSIGNED.value,
    )
    assert (
        validate_success(api.get_surgical_case(case_id, ADMIN))["scheduling_status"]
        == "IN_RECOVERY"
    )

    completed = validate_success(
        api.complete_case(case_id, {}, make_surgeon_headers(surgeon_a["id"]))
    )
    assert completed["scheduling_status"] == "COMPLETED"


def test_rbac_morbidity_reviewer_may_not_be_the_operating_surgeon():
    """A surgeon correctly bound to their own id still cannot review their case.

    PRD: "The event must be in `REPORTED`, and the nominated reviewer must be
    employed by the same practice as the event's case and must not be that
    case's `primary_surgeon_id` — a surgeon may not review their own morbidity,
    and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "Opening moves `status` from `REPORTED` to `UNDER_MORBIDITY_REVIEW` and
    persists the `reviewer_staff_id` on the event."

    PRD: "`reporting_deadline_at` is `occurred_at` plus 24 hours for a
    `SENTINEL` event, plus 72 hours for a `SEVERE` one, plus 7 days for a
    `MODERATE` one, and plus 30 days for a `MINOR` one."

    Design: Corner/rbac/morbidity_reviewer_may_not_be_the_operating_surgeon
    """
    set_clock("2026-09-16T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Duties OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    reviewer = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Quinn Reviewer",
                "role_type": "RECOVERY_NURSE",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Reviewed",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-20T13:00:00Z",
                "planned_end": "2026-09-20T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    event = validate_success(
        api.create_adverse_event(
            {
                "case_id": case["id"],
                "event_type": "PROLONGED_RECOVERY",
                "severity": "MINOR",
                "occurred_at": "2026-09-16T09:00:00Z",
                "narrative": "Extended monitoring after a routine local case.",
            },
            make_surgeon_headers(surgeon["id"]),
        ),
        201,
    )
    assert event["status"] == "REPORTED"
    assert parse_iso(event["reporting_deadline_at"]) == parse_iso(
        "2026-10-16T09:00:00Z"
    ), "a MINOR event is due 30 days after it occurred"
    assert event["late_report"] is False
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["open_adverse_event_count"]
        == 1
    )

    validate_error(
        api.morbidity_review(
            event["id"],
            {"action": "OPEN", "reviewer_staff_id": surgeon["id"]},
            make_quality_reviewer_headers(surgeon["id"]),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    unchanged = validate_success(api.get_adverse_event(event["id"], ADMIN))
    assert unchanged["status"] == "REPORTED"
    assert unchanged["reviewer_staff_id"] is None

    opened = validate_success(
        api.morbidity_review(
            event["id"],
            {"action": "OPEN", "reviewer_staff_id": reviewer["id"]},
            make_quality_reviewer_headers(reviewer["id"]),
        )
    )
    assert opened["status"] == "UNDER_MORBIDITY_REVIEW"
    assert opened["reviewer_staff_id"] == reviewer["id"]
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["open_adverse_event_count"]
        == 1
    ), "an event under review is still open"
