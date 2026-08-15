"""Creation defaults, version pinning, and case generation from the pinned profile."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    create_published_profile,
    create_manager_and_buddy,
    create_new_hire,
    create_case,
    create_role_profile_payload,
    create_employee_payload,
    create_new_hire_payload,
    create_onboarding_case_payload,
    setup_basic_case,
    get_case_tasks,
    get_case_trainings,
    get_case_checkins,
    get_case_cycles,
)

HR = TEST_USERS["hr_admin_headers"]


def test_role_profile_creation_applies_defaults(api):
    """PRD §3.1: "A new profile begins in `DRAFT` status with `published_version` 0."
    PRD §2.4: "`version` (integer): a system-managed integer that increments by
    exactly 1 on every mutation of the resource"

    Design: Corner/entities/role_profile_creation_applies_defaults
    """
    payload = create_role_profile_payload()
    resp = api.create_role_profile(payload, HR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["published_version"] == 0
    assert data["version"] == 1
    assert data["id"]


def test_case_creation_generates_children_from_pinned_profile(api):
    """PRD §3.2: "The case pins `pinned_profile_version` to the profile's current
    `published_version`, and from that pinned template the server creates: one task
    per `preboarding_tasks` entry, in template order via `sort_index`; one training
    assignment per `training_modules` entry, in template order, each with `due_at`
    set to the end of the day that is `due_offset_days` after the `start_date`
    (23:59:59 UTC); the full check-in schedule described in §3.7; and the first
    probation cycle, `cycle_index` 1, in `ACTIVE` status with `evaluation_due_at`
    set to 17:00:00 UTC on the day that is `probation_days` after the `start_date`."

    Design: Corner/entities/case_creation_generates_children_from_pinned_profile
    """
    ctx = setup_basic_case()
    case = ctx["case"]
    assert case["phase"] == "PRE_BOARDING"
    assert case["health"] == "ON_TRACK"
    assert case["health_score"] == 100
    assert case["version"] == 1
    assert case["pinned_profile_version"] == 1

    tasks = get_case_tasks(case["id"])
    assert tasks[0]["status"] == "PENDING"
    assert tasks[2]["is_required"] is False  # Handbook optional

    trainings = get_case_trainings(case["id"])
    assert trainings[0]["due_at"] == "2026-05-11T23:59:59Z"
    assert trainings[1]["due_at"] == "2026-05-18T23:59:59Z"

    checkins = get_case_checkins(case["id"])
    expected = [
        "2026-05-05T09:00:00Z",  # MANAGER +1
        "2026-06-03T09:00:00Z",  # MANAGER +30
        "2026-05-05T09:00:00Z",  # BUDDY day 1
        "2026-05-12T09:00:00Z",  # BUDDY day 8
    ]
    assert [c["scheduled_at"] for c in checkins] == expected

    cycles = get_case_cycles(case["id"])
    assert cycles[0]["status"] == "ACTIVE"
    assert cycles[0]["evaluation_due_at"] == "2026-08-02T17:00:00Z"


def test_case_create_extra_field_input_ignored(api):
    """PRD §3.2: "The new case begins in phase `PRE_BOARDING`, with `health`
    `ON_TRACK`, `orientation_rsvp` `NONE`, and `manager_reassignment_required`
    false."

    Client-injected system fields must be overridden by the server.

    Design: Corner/entities/case_create_extra_field_input_ignored
    """
    profile = create_published_profile()
    mgr, bud = create_manager_and_buddy()
    nh = create_new_hire()
    payload = create_onboarding_case_payload(
        new_hire_id=nh["id"],
        role_profile_id=profile["id"],
        manager_id=mgr["id"],
        buddy_id=bud["id"],
    )
    # Inject system/computed fields; the server must ignore them.
    payload["phase"] = "COMPLETED"
    payload["health_score"] = 5
    resp = api.create_onboarding_case(payload, HR)
    data = validate_success(resp, expected_status=201)
    assert data["phase"] == "PRE_BOARDING"
    assert data["health_score"] == 100


def test_summary_computed_read_fresh_case(api):
    """PRD §3.7: "The estimated variant, `estimated_ttp_days`, is always available
    and forward-looking: it starts from the larger of two profile-derived bases —
    the greatest `due_offset_days` among the pinned profile's training modules and
    the greatest offset among its `manager_checkin_offsets_days` — then adds 3 days
    for each training assignment currently `OVERDUE` and 5 days for each check-in
    currently `MISSED`, drifting upward as the case slips. The actual variant,
    `actual_ttp_days`, stays null until every training assignment is `COMPLETED`
    and every `MANAGER` check-in is `COMPLETED`"

    Design: Corner/entities/summary_computed_read_fresh_case
    """
    ctx = setup_basic_case()
    summary = get_success_data(api.get_case_summary(ctx["case"]["id"], HR))
    assert summary["health_score"] == 100
    assert summary["health"] == "ON_TRACK"
    assert summary["phase"] == "PRE_BOARDING"
    assert summary["estimated_ttp_days"] == 30
    assert summary["actual_ttp_days"] is None
    assert summary["open_handoff_count"] == 0


def test_profile_republish_pins_new_cases_only(api):
    """PRD §3.1: "An `HRAdmin` may edit the template fields of an existing profile;
    the edit itself leaves `published_version` untouched, and re-publishing
    afterwards moves the profile from `PUBLISHED` to `PUBLISHED` again,
    incrementing `published_version` by 1 each time. The versioning matters because
    onboarding cases pin the profile version current at their own creation:
    existing cases keep their `pinned_profile_version` forever, so republishing a
    profile never rewrites content already generated for in-flight hires."

    Design: Corner/entities/profile_republish_pins_new_cases_only
    """
    profile = create_published_profile()
    mgr, bud = create_manager_and_buddy()
    nh_a = create_new_hire()
    case_a = create_case(mgr, bud, nh_a, profile)
    assert case_a["pinned_profile_version"] == 1

    # Edit + re-publish bumps the profile to version 2.
    get_success_data(api.update_role_profile(profile["id"], {"probation_days": 60}, HR))
    profile_v2 = get_success_data(api.publish_role_profile(profile["id"], HR))
    assert profile_v2["published_version"] == 2

    nh_b = create_new_hire()
    case_b = create_case(mgr, bud, nh_b, profile_v2)
    assert case_b["pinned_profile_version"] == 2

    cycles_a = get_case_cycles(case_a["id"])
    cycles_b = get_case_cycles(case_b["id"])
    # case A keeps v1 content (90-day probation); case B uses v2 content (60-day).
    assert cycles_a[0]["evaluation_due_at"] == "2026-08-02T17:00:00Z"
    assert cycles_b[0]["evaluation_due_at"] == "2026-07-03T17:00:00Z"


def test_employees_list_filter_by_manager_self_reference(api):
    """PRD §3.2: "employees can be listed filtered by `manager_id` or
    `employment_status`."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/employees_list_filter_by_manager_self_reference
    """
    top = get_success_data(api.create_employee(
        create_employee_payload(full_name="Top"), HR))
    get_success_data(api.create_employee(
        create_employee_payload(full_name="R1", manager_id=top["id"]), HR))
    get_success_data(api.create_employee(
        create_employee_payload(full_name="R2", manager_id=top["id"]), HR))
    get_success_data(api.create_employee(
        create_employee_payload(full_name="Other"), HR))

    resp = api.list_employees(HR, params={"manager_id": top["id"]})
    data, meta = __import__("test_helpers").validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2
    assert all(e["manager_id"] == top["id"] for e in data)
