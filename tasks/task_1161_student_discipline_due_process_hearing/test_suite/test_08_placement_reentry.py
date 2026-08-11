"""Alternative-education placement: capacity arithmetic, activation windows,
re-entry plan gating, and the IDEA safety gate's precedence."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_alt_ed_site, assert_alt_ed_placement, assert_re_entry_plan,
    create_placement_payload, create_re_entry_plan_payload,
    set_clock, create_alt_ed_site, setup_expulsion_active_case,
    create_placement, activate_placement, complete_placement,
    create_re_entry_plan, get_case,
    make_student_services_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
CLS = TEST_USERS["school_classifier_headers"]
SSD = TEST_USERS["student_services_headers"]

# Forward-only clock plan for two consecutive expulsion chains:
# chain 1 decides at 2026-05-05T11:00Z; chain 2 decides at 2026-05-10T11:00Z.
CHAIN1 = dict(officer_id="ho_1", referral_clock="2026-05-01T00:00:00Z",
              scheduled_start="2026-05-05T10:00:00Z",
              scheduled_end="2026-05-05T11:00:00Z")
CHAIN2 = dict(officer_id="ho_2", referral_clock="2026-05-06T00:00:00Z",
              incident_date="2026-05-02T00:00:00Z",
              scheduled_start="2026-05-10T10:00:00Z",
              scheduled_end="2026-05-10T11:00:00Z")


def _two_expelled_students(api, site_capacity=1, site_name="Site Cap",
                           y_disability=None):
    """Student A and student B each carried through EXPULSION_ACTIVE (PRD §3.5
    cascade), plus one alternative-education site. Returns (a, b, site)."""
    site = create_alt_ed_site(site_name, site_capacity)
    a = setup_expulsion_active_case(
        guardian_id="ga", full_name="Stu A", grade_level=12,
        date_of_birth="2008-06-01T00:00:00Z", **CHAIN1)
    b = setup_expulsion_active_case(
        guardian_id="gb", full_name="Stu B", grade_level=12,
        date_of_birth="2008-07-01T00:00:00Z", demographic_group="BLACK",
        disability_status=y_disability, offense_code="WEAP-02", **CHAIN2)
    return a, b, site


# ─── Difficulty: aggregate site capacity ──────────────

def test_site_capacity_rejects_overlapping_placement(api):
    """PRD §3.7: "Capacity is enforced in aggregate over closed intervals:
    counting the new placement, the site's overlapping placements in `PLACED`
    or `ACTIVE` status may not exceed its `capacity`, on pain of
    `ERR_SITE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/site_capacity_aggregate_overlap_counts_concurrent
    """
    a, b, site = _two_expelled_students(api, site_capacity=1)
    pa = create_placement(a["case"]["id"], site["id"],
                          "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    assert pa["status"] == "PLACED"

    # [2026-05-15, 2026-05-22] overlaps [2026-05-11, 2026-05-29]; the
    # concurrent count reaches capacity 1.
    res = api.create_placement(
        create_placement_payload(b["case"]["id"], site["id"],
                                 "2026-05-15T00:00:00Z", "2026-05-22T00:00:00Z"),
        SSD)
    validate_error(res, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED, expected_status=409)


def test_site_capacity_rejection_leaves_only_first_placement(api):
    """PRD §3.7: "Capacity is enforced in aggregate over closed intervals:
    counting the new placement, the site's overlapping placements in `PLACED`
    or `ACTIVE` status may not exceed its `capacity`, on pain of
    `ERR_SITE_CAPACITY_EXCEEDED`."
    PRD §3.7: "the placement register supports filters on `case_id`,
    `site_id`, and `status`."

    Design: Difficulty/resource_temporal_overlap/site_capacity_aggregate_overlap_counts_concurrent
    """
    a, b, site = _two_expelled_students(api, site_capacity=1)
    pa = create_placement(a["case"]["id"], site["id"],
                          "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    res = api.create_placement(
        create_placement_payload(b["case"]["id"], site["id"],
                                 "2026-05-15T00:00:00Z", "2026-05-22T00:00:00Z"),
        SSD)
    validate_error(res, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED, expected_status=409)

    data, meta = validate_paginated(
        api.list_placements(SSD, params={"site_id": site["id"]}))
    assert len(data) == 1 and meta["total_count"] == 1
    assert data[0]["id"] == pa["id"]
    assert data[0]["status"] == "PLACED"


def test_site_closed_interval_end_adjacency_counts_overlap(api):
    """PRD §3.7: "A site's live `seats_occupied` is computed on every read as
    the number of its placements in `PLACED` or `ACTIVE` status whose closed
    date interval — `start_date` through `planned_end_date`, both ends
    inclusive — covers the current clock day".
    PRD §3.7: "Capacity is enforced in aggregate over closed intervals ...
    on pain of `ERR_SITE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/site_closed_interval_end_adjacency_counts_overlap
    """
    a, b, site = _two_expelled_students(api, site_capacity=1, site_name="Site Z")
    create_placement(a["case"]["id"], site["id"],
                     "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    # Closed intervals include the shared boundary day 2026-05-29.
    res = api.create_placement(
        create_placement_payload(b["case"]["id"], site["id"],
                                 "2026-05-29T00:00:00Z", "2026-06-05T00:00:00Z"),
        SSD)
    validate_error(res, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED, expected_status=409)


def test_placement_second_active_per_case_returns_409(api):
    """PRD §3.7: "One open placement per case is the rule, so a second
    placement while one stands `PLACED` or `ACTIVE` draws
    `ERR_PLACEMENT_ALREADY_ACTIVE`."

    Design: Corner/validations/placement_second_active_per_case_returns_409
    """
    site = create_alt_ed_site("Site W", 5)
    a = setup_expulsion_active_case(guardian_id="gpa", full_name="Stu PA",
                                    grade_level=12, **CHAIN1)
    create_placement(a["case"]["id"], site["id"],
                     "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    # Capacity is free (5 seats); the binding constraint is the open placement.
    res = api.create_placement(
        create_placement_payload(a["case"]["id"], site["id"],
                                 "2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z"),
        SSD)
    validate_error(res, ApiErrorId.ERR_PLACEMENT_ALREADY_ACTIVE, expected_status=409)


def test_placement_activate_before_start_returns_409(api):
    """PRD §3.7: "Activation waits for the placement's first day: the clock
    must have reached `start_date`, and an earlier attempt fails with
    `ERR_PLACEMENT_NOT_STARTED`."

    Design: Corner/validations/placement_activate_before_start_returns_409
    """
    site = create_alt_ed_site("Site V", 5)
    a = setup_expulsion_active_case(guardian_id="gns", full_name="Stu NS",
                                    grade_level=12, **CHAIN1)
    placement = create_placement(a["case"]["id"], site["id"],
                                 "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    set_clock("2026-05-10T00:00:00Z")  # one day before start_date
    res = api.activate_placement(placement["id"], {}, SSD)
    validate_error(res, ApiErrorId.ERR_PLACEMENT_NOT_STARTED, expected_status=409)

    settled = validate_success(api.get_placement(placement["id"], SSD), 200)
    assert settled["status"] == "PLACED"
    student = validate_success(api.get_student(a["student"]["id"], SSD), 200)
    assert student["enrollment_status"] == "ALT_ED_PENDING"


# ─── Difficulty: IDEA safety gate beats capacity ──────

def _setup_mdr_vs_capacity(api):
    """Site capacity 1 occupied by expelled student X's placement
    [2026-05-11, 2026-05-29]; expelled student Y (IEP) has no manifestation
    determination at all."""
    site = create_alt_ed_site("Site S", 1)
    x = setup_expulsion_active_case(
        guardian_id="gx", full_name="Stu X", grade_level=12,
        date_of_birth="2008-01-01T00:00:00Z", **CHAIN1)
    px = create_placement(x["case"]["id"], site["id"],
                          "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    y = setup_expulsion_active_case(
        guardian_id="gy", full_name="Stu Y", grade_level=12,
        date_of_birth="2008-02-01T00:00:00Z", demographic_group="BLACK",
        disability_status="IEP", offense_code="WEAP-02", **CHAIN2)
    return x, y, site, px


def test_placement_mdr_safety_beats_capacity_constraint(api):
    """PRD §2.9: "Every request traverses a fixed ladder of checks, and a
    failure at any rung stops the evaluation with that rung's error."
    PRD §2.9 (rung 9): "Notice issuance and placement creation require that no
    manifestation determination for the case is `PENDING` or `SCHEDULED`, and
    placement for a student with disability status additionally requires a
    `COMPLETED` determination for the case — otherwise `ERR_MDR_INCOMPLETE`."
    — the safety rung precedes the uniqueness/capacity rung carrying
    `ERR_SITE_CAPACITY_EXCEEDED`.

    Design: Difficulty/priority_pair_validation_conflict/placement_mdr_safety_beats_capacity_constraint
    """
    x, y, site, px = _setup_mdr_vs_capacity(api)
    # Y's window overlaps X's placement, so capacity also fails; the IDEA
    # safety gate is evaluated first.
    res = api.create_placement(
        create_placement_payload(y["case"]["id"], site["id"],
                                 "2026-05-12T00:00:00Z", "2026-05-20T00:00:00Z"),
        SSD)
    validate_error(res, ApiErrorId.ERR_MDR_INCOMPLETE, expected_status=409)


def test_placement_mdr_safety_rejection_creates_no_row(api):
    """PRD §3.7: "The IDEA gate applies in full: placement is refused with
    `ERR_MDR_INCOMPLETE` while any determination for the case stands `PENDING`
    or `SCHEDULED`, and for a student with disability status the case must
    show a `COMPLETED` determination."
    PRD §3.7: "the placement register supports filters on `case_id`,
    `site_id`, and `status`."

    Design: Difficulty/priority_pair_validation_conflict/placement_mdr_safety_beats_capacity_constraint
    """
    x, y, site, px = _setup_mdr_vs_capacity(api)
    res = api.create_placement(
        create_placement_payload(y["case"]["id"], site["id"],
                                 "2026-05-12T00:00:00Z", "2026-05-20T00:00:00Z"),
        SSD)
    validate_error(res, ApiErrorId.ERR_MDR_INCOMPLETE, expected_status=409)

    data, meta = validate_paginated(
        api.list_placements(SSD, params={"case_id": y["case"]["id"]}))
    assert data == [] and meta["total_count"] == 0, (
        "no placement row may persist for the rejected request")


# ─── Difficulty: re-entry activation gated on placement ─

def _setup_placed_with_draft_plan(api):
    """Expelled student (NONE); placement PLACED over [2026-05-11,
    2026-05-29]; one re-entry plan DRAFT; clock parked at 2026-05-12 so only
    the missing ACTIVE status can block activation."""
    site = create_alt_ed_site("Site R", 5)
    a = setup_expulsion_active_case(guardian_id="g9", full_name="Stu Re",
                                    **CHAIN1)
    placement = create_placement(a["case"]["id"], site["id"],
                                 "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    plan = create_re_entry_plan(placement["id"],
                                ["attend orientation", "weekly check-in"],
                                "2026-05-26T00:00:00Z")
    set_clock("2026-05-12T00:00:00Z")
    return a, site, placement, plan


def test_reentry_activation_blocked_until_placement_active(api):
    """PRD §3.7: "Activation is guarded across entities: the plan can leave
    `DRAFT` for `ACTIVE` only while its placement is `ACTIVE`, failing
    otherwise with `ERR_PLACEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reentry_activation_blocked_until_placement_active
    """
    a, site, placement, plan = _setup_placed_with_draft_plan(api)
    assert placement["status"] == "PLACED"

    res = api.activate_re_entry_plan(plan["id"], {}, SSD)
    validate_error(res, ApiErrorId.ERR_PLACEMENT_NOT_ACTIVE, expected_status=409)


def test_reentry_activation_rejection_keeps_plan_draft(api):
    """PRD §3.7: "the plan can leave `DRAFT` for `ACTIVE` only while its
    placement is `ACTIVE`, failing otherwise with `ERR_PLACEMENT_NOT_ACTIVE`."
    PRD §3.7: "a placement's plans can be listed by district staff and the
    director."

    Design: Difficulty/cross_entity_state_dependency/reentry_activation_blocked_until_placement_active
    """
    a, site, placement, plan = _setup_placed_with_draft_plan(api)
    res = api.activate_re_entry_plan(plan["id"], {}, SSD)
    validate_error(res, ApiErrorId.ERR_PLACEMENT_NOT_ACTIVE, expected_status=409)

    plans = validate_success(
        api.list_re_entry_plans(placement["id"], SSD), 200)
    assert len(plans) == 1
    assert plans[0]["status"] == "DRAFT", (
        f"the rejected activation leaves the plan DRAFT, got "
        f"{plans[0]['status']!r}")


def test_reentry_second_open_plan_returns_409(api):
    """PRD §3.7: "the plan begins `DRAFT`, attached to its placement through
    `placement_id`, and only one open plan may exist per placement — a second
    draws `ERR_REENTRY_OPEN`."

    Design: Corner/validations/reentry_second_open_plan_returns_409
    """
    site = create_alt_ed_site("Site U", 5)
    a = setup_expulsion_active_case(guardian_id="gre", full_name="Stu RE",
                                    grade_level=12, **CHAIN1)
    placement = create_placement(a["case"]["id"], site["id"],
                                 "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    plan1 = create_re_entry_plan(placement["id"], ["orientation"],
                                 "2026-05-26T00:00:00Z")
    assert plan1["status"] == "DRAFT"

    res = api.create_re_entry_plan(
        placement["id"],
        create_re_entry_plan_payload(["duplicate plan"], "2026-05-27T00:00:00Z"),
        SSD)
    validate_error(res, ApiErrorId.ERR_REENTRY_OPEN, expected_status=409)


# ─── Difficulty: seat ledger compensation ─────────────

def test_seat_occupied_while_placement_covers_clock_day(api):
    """PRD §3.7: "A site's live `seats_occupied` is computed on every read as
    the number of its placements in `PLACED` or `ACTIVE` status whose closed
    date interval — `start_date` through `planned_end_date`, both ends
    inclusive — covers the current clock day; a freshly created site reads
    zero."
    PRD §3.7: "Activation moves the placement `PLACED` → `ACTIVE` and the
    student's `enrollment_status` `ALT_ED_PENDING` → `IN_ALT_ED`, with the
    site's `seats_occupied` reflecting the activation on subsequent reads."

    Design: Difficulty/compensating_invariant/site_seat_ledger_placement_then_complete_restores_available
    """
    site = create_alt_ed_site("Site Seat", 2)
    a = setup_expulsion_active_case(guardian_id="gs", full_name="Stu Seat",
                                    **CHAIN1)
    placement = create_placement(a["case"]["id"], site["id"],
                                 "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")

    set_clock("2026-05-11T00:00:00Z")  # covered by the closed interval
    site_mid = validate_success(api.get_alt_ed_site(site["id"], SSD), 200)
    assert site_mid["seats_occupied"] == 1, (
        f"one PLACED placement covering the clock day: got "
        f"{site_mid['seats_occupied']}")

    activated = activate_placement(placement["id"])
    assert activated["status"] == "ACTIVE"
    student = validate_success(api.get_student(a["student"]["id"], SSD), 200)
    assert student["enrollment_status"] == "IN_ALT_ED"


def test_seat_released_after_completion_and_student_reenrolls(api):
    """PRD §3.7: "Completion, from `ACTIVE`, records an `outcome` of
    `COMPLETED` or `EXITED_EARLY`, stamps `actual_end_date` at the clock, and
    returns the student from `IN_ALT_ED` to `ENROLLED`."
    PRD §3.7: "A site's live `seats_occupied` is computed on every read as the
    number of its placements in `PLACED` or `ACTIVE` status".

    Design: Difficulty/compensating_invariant/site_seat_ledger_placement_then_complete_restores_available
    """
    site = create_alt_ed_site("Site Seat", 2)
    a = setup_expulsion_active_case(guardian_id="gs", full_name="Stu Seat",
                                    **CHAIN1)
    placement = create_placement(a["case"]["id"], site["id"],
                                 "2026-05-11T00:00:00Z", "2026-05-29T00:00:00Z")
    set_clock("2026-05-11T00:00:00Z")
    activate_placement(placement["id"])

    completed = complete_placement(placement["id"], "COMPLETED")
    assert completed["status"] == "COMPLETED"
    assert completed.get("actual_end_date") is not None

    site_after = validate_success(api.get_alt_ed_site(site["id"], SSD), 200)
    assert site_after["seats_occupied"] == 0, (
        "create/activate (+1) paired with complete (-1) conserves the seat "
        f"count; got {site_after['seats_occupied']}")
    student = validate_success(api.get_student(a["student"]["id"], SSD), 200)
    assert student["enrollment_status"] == "ENROLLED"
