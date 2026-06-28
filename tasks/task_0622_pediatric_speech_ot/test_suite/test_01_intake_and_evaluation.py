"""Intake, evaluation, and the recommendation tier — children, evaluations,
goals, and listing.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, assert_child, assert_evaluation, assert_goal_progress_entry,
    create_child_payload, create_evaluation_payload, create_goal_payload,
    TEST_USERS, make_evaluator_headers, make_therapist_headers, NON_EXISTENT_UUID,
    set_clock, create_child, create_therapist, create_finalized_evaluation,
    create_active_plan, create_authorization, add_goal, setup_active_care,
    book_appointment_ok, complete_appointment,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_register_child_computes_age_and_defaults(api):
    """PRD §3.1: "On registration the system computes `age_months_at_intake` as
    the whole number of months between `date_of_birth` and the moment of creation
    under the logical clock". PRD §3.1: "A newly registered child begins with
    `status` set to `ACTIVE`, `coordination_program` set to `NONE`, and
    `active_appointment_count` of 0".

    Design: Corner/entities/create_child_returns_201_with_computed_age_and_defaults
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_child(create_child_payload(full_name="New Kid",
                                                date_of_birth="2024-06-01"), ADMIN)
    child = validate_success(res, 201)
    assert_child(child)
    assert child["age_months_at_intake"] == 24, child["age_months_at_intake"]
    assert child["coordination_program"] == "NONE"
    assert child["status"] == "ACTIVE"
    assert child["version"] == 1


def test_get_child_not_found(api):
    """PRD §2.5: "the system validates each identifier in left-to-right order and
    rejects the request with `ERR_NOT_FOUND` at the first identifier in the path
    that does not name an existing resource."

    Design: Corner/entities/get_child_not_found_returns_404
    """
    res = api.get_child(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_evaluation_missing_severity_rejected(api):
    """PRD §3.2: "An `Evaluator` authors an evaluation against a child, supplying
    the `child_id`, the `discipline` being evaluated (`SLP` or `OT`), and a
    `severity_score` — a standardized deficit score from 0 to 100 inclusive".

    Design: Corner/entities/create_evaluation_missing_required_field_returns_400
    """
    th = create_therapist()
    child = create_child()
    payload = {"child_id": child["id"], "discipline": "SLP"}  # severity_score omitted
    res = api.create_evaluation(payload, make_evaluator_headers(th["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_evaluation_severity_out_of_range_rejected(api):
    """PRD §3.2: "a `severity_score` — a standardized deficit score from 0 to 100
    inclusive where a higher number signals greater need."

    Design: Corner/entities/create_evaluation_severity_out_of_range_returns_400
    """
    th = create_therapist()
    child = create_child()
    res = api.create_evaluation(
        create_evaluation_payload(child["id"], discipline="SLP", severity_score=101),
        make_evaluator_headers(th["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_goal_target_not_above_baseline_rejected(api):
    """PRD §3.3: "a `target_pct` (the target attainment, 0 to 100, which must be
    strictly greater than `baseline_pct`; a target at or below baseline is
    `ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_goal_target_not_above_baseline_returns_400
    """
    ctx = setup_active_care()
    res = api.create_goal(
        ctx["plan"]["id"],
        create_goal_payload(description="Bad goal", weight=1, baseline_pct=40, target_pct=40),
        make_therapist_headers(ctx["therapist"]["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_finalize_computes_recommended_weekly_minutes(api):
    """PRD §3.2: "On finalization the evaluation moves to `FINALIZED` and the
    system computes `recommended_weekly_minutes` from the `severity_score`". PRD
    §3.2: "from 60 through 79 recommends 90 minutes".

    Design: Corner/entities/recommended_weekly_minutes_computed_on_finalize
    """
    th = create_therapist()
    child = create_child()
    ev = get_success_data(api.create_evaluation(
        create_evaluation_payload(child["id"], discipline="SLP", severity_score=72),
        make_evaluator_headers(th["id"])))
    res = api.finalize_evaluation(ev["id"], make_evaluator_headers(th["id"]))
    finalized = validate_success(res, 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["recommended_weekly_minutes"] == 90, finalized["recommended_weekly_minutes"]


def test_recommended_weekly_minutes_tier_boundary_low(api):
    """PRD §3.2: "A score from 0 through 29 recommends 30 minutes; from 30 through
    59 recommends 60 minutes". A severity of exactly 30 falls in the second band
    and yields 60, not 30.

    Design: Corner/calculations/recommended_weekly_minutes_tier_boundary_low
    """
    th = create_therapist()
    child = create_child()
    ev = get_success_data(api.create_evaluation(
        create_evaluation_payload(child["id"], discipline="SLP", severity_score=30),
        make_evaluator_headers(th["id"])))
    finalized = validate_success(api.finalize_evaluation(
        ev["id"], make_evaluator_headers(th["id"])), 200)
    assert finalized["recommended_weekly_minutes"] == 60, finalized["recommended_weekly_minutes"]


def test_goal_progress_entry_is_append_only_no_version(api):
    """PRD §2.4: "A goal progress entry is an append-only event-log record: it
    carries only `id` and `created_at`. It has no `updated_at` and no `version`".
    PRD §3.6: "its `recorded_session_time` copied from the appointment's
    `start_time`".

    Design: Corner/entities/goal_progress_entry_immutable_no_version_field
    """
    set_clock("2026-06-20T12:00:00Z")
    th = create_therapist()
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    goal = add_goal(plan["id"], th["id"], description="G", weight=1, baseline_pct=0, target_pct=100)
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=3)
    ctx = {"child": child, "therapist": th, "auth": auth, "plan": plan}
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    get_success_data(complete_appointment(
        appt["id"], th["id"],
        goal_progress_entries=[{"goal_id": goal["id"], "recorded_pct": 30}]))

    res = api.list_goal_progress_entries(goal["id"], make_therapist_headers(th["id"]))
    entries, _ = validate_paginated(res)
    assert len(entries) == 1, entries
    entry = entries[0]
    assert_goal_progress_entry(entry)
    assert entry["recorded_pct"] == 30
    # PRD §3.6: recorded_session_time is copied from the appointment's start_time.
    # The PRD fixes the instant, not a specific serialization of start_time
    # (§2.4 mandates three fractional digits only for created_at/updated_at), so
    # compare against the appointment's own stored start_time.
    assert entry["recorded_session_time"] == appt["start_time"], entry["recorded_session_time"]


def test_list_children_pagination_envelope(api):
    """PRD §2.3: "List responses include the following fields in the `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`." PRD §2.2: "The
    `response_type` is either "object" for a single resource or "array" for a list
    of resources."

    Design: Corner/entities/list_children_pagination_envelope
    """
    create_child(full_name="C1")
    create_child(full_name="C2")
    res = api.list_children(ADMIN)
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False
