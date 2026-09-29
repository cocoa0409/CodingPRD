"""The two occupancy rules of §2.9: a proctor's exclusive window with its
15-minute pad, and a site's aggregate half-open seat count."""
from test_helpers import (
    add_candidate,
    add_proctor,
    assign_code,
    factories as f,
    get_success_data,
    purchase_batch,
    schedule_session,
    setup_landscape,
    validate_error,
    validate_paginated,
)

_FIRST_START = "2026-09-10T09:00:00Z"


def _one_proctor_two_candidates(api):
    env = setup_landscape()
    cand_a = add_candidate(env)
    cand_b = add_candidate(env)
    proctor = add_proctor(env, languages_certified=["EN"], remote_certified=False)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    code_a, batch = assign_code(env, batch, cand_a)
    code_b, batch = assign_code(env, batch, cand_b)
    first = schedule_session(env, cand_a, code_a, _FIRST_START, proctor=proctor)
    env.update({"cand_a": cand_a, "cand_b": cand_b, "proctor": proctor,
                "code_b": code_b, "batch": batch, "first": first})
    return env


def _second_sitting_payload(env, start_at):
    return f.create_exam_session_payload(
        env["cand_b"]["id"], env["exam_form"]["id"], env["code_b"]["id"], start_at,
        delivery_mode="IN_PERSON", testing_site_id=env["testing_site"]["id"],
        proctor_id=env["proctor"]["id"])


def test_a_fourteen_minute_gap_collides_with_the_proctors_turnaround_pad(api):
    """The raw intervals do not touch, but the padded windows do, so the 11:14
    start is a conflict.

    PRD: "A conflict exists when, for any sitting in that set, the new sitting's
    `scheduled_start_at` falls strictly before that sitting's `scheduled_end_at`
    extended forward by 15 minutes, and at the same time that sitting's
    `scheduled_start_at` falls strictly before the new sitting's
    `scheduled_end_at` extended forward by 15 minutes."

    Design: Difficulty/resource_temporal_overlap/proctor_exclusive_occupancy_rejects_14_minute_gap_allows_exactly_15
    """
    env = _one_proctor_two_candidates(api)
    admin = env["admin_headers"]
    assert env["first"]["scheduled_end_at"] == "2026-09-10T11:00:00Z"
    assert env["batch"]["total_price_cents"] == 7524
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 492476
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 120

    refused = api.create_exam_session(
        _second_sitting_payload(env, "2026-09-10T11:14:00Z"), env["provider_headers"])

    validate_error(refused, "ERR_PROCTOR_INTERVAL_CONFLICT", 409)
    _, meta = validate_paginated(api.list_exam_sessions(
        admin, params={"proctor_id": env["proctor"]["id"]}))
    assert meta["total_count"] == 1
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 120
    assert get_success_data(api.get_access_code(
        env["code_b"]["id"], env["provider_headers"]))["status"] == "ASSIGNED"


def test_a_gap_of_exactly_fifteen_minutes_is_permitted(api):
    """Both padded comparisons are strict, so the 11:15 start is admitted.

    PRD: "Because both comparisons are strict, a gap of exactly 15 minutes between
    neighbouring sittings is permitted, while a gap of 14 minutes is a conflict and
    is rejected with `ERR_PROCTOR_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/proctor_exclusive_occupancy_rejects_14_minute_gap_allows_exactly_15
    """
    env = _one_proctor_two_candidates(api)
    admin = env["admin_headers"]

    second = get_success_data(api.create_exam_session(
        _second_sitting_payload(env, "2026-09-10T11:15:00Z"),
        env["provider_headers"]), 201)

    assert second["session_status"] == "SCHEDULED"
    assert second["scheduled_end_at"] == "2026-09-10T13:15:00Z"
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 240
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 240


def _two_full_seats(api):
    """A 2-seat site with both seats taken for [09:00, 11:00), each by its own
    proctor so the exclusive rule can never be the cause of a rejection."""
    env = setup_landscape()
    candidates = [add_candidate(env) for _ in range(4)]
    proctors = [add_proctor(env, languages_certified=["EN"], remote_certified=False)
                for _ in range(3)]
    proctors.append(add_proctor(env, languages_certified=["EN"], remote_certified=True))
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 4}])
    codes = []
    for candidate in candidates:
        code, batch = assign_code(env, batch, candidate)
        codes.append(code)
    schedule_session(env, candidates[0], codes[0], _FIRST_START, proctor=proctors[0])
    schedule_session(env, candidates[1], codes[1], _FIRST_START, proctor=proctors[1])
    env.update({"candidates": candidates, "proctors": proctors, "codes": codes,
                "batch": batch})
    return env


def test_the_third_overlapping_sitting_exhausts_a_two_seat_site(api):
    """Two seats are already committed for the interval, so an overlapping third
    in-person sitting is refused on capacity, not on the proctor rule.

    PRD: "The new sitting is rejected with `ERR_SITE_SEAT_CAPACITY_EXCEEDED`
    (HTTP 409) when the count of overlapping sittings is already greater than or
    equal to the site's `seat_count` — so with a `seat_count` of three, the third
    concurrent sitting is admitted and the fourth is refused."

    Design: Difficulty/resource_temporal_overlap/site_seat_capacity_is_aggregate_half_open_and_ignores_remote_sittings
    """
    env = _two_full_seats(api)
    admin = env["admin_headers"]
    assert env["batch"]["total_price_cents"] == 15048
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 484952
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 240

    refused = api.create_exam_session(
        f.create_exam_session_payload(
            env["candidates"][2]["id"], env["exam_form"]["id"], env["codes"][2]["id"],
            "2026-09-10T10:30:00Z", delivery_mode="IN_PERSON",
            testing_site_id=env["testing_site"]["id"],
            proctor_id=env["proctors"][2]["id"]),
        env["provider_headers"])

    validate_error(refused, "ERR_SITE_SEAT_CAPACITY_EXCEEDED", 409)
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 240


def test_an_adjacent_sitting_is_free_and_a_remote_sitting_never_takes_a_seat(api):
    """A sitting starting exactly when another ends is admitted with no pad, and a
    fully overlapping REMOTE sitting is outside the seat rule altogether.

    PRD: "Adjacency is free: a sitting that starts at exactly the instant another
    ends does not overlap it."

    PRD: "Remote sittings carry no `testing_site_id` and never consume a seat or
    contribute to `reserved_seat_minutes`."

    Design: Difficulty/resource_temporal_overlap/site_seat_capacity_is_aggregate_half_open_and_ignores_remote_sittings
    """
    env = _two_full_seats(api)
    admin = env["admin_headers"]

    adjacent = get_success_data(api.create_exam_session(
        f.create_exam_session_payload(
            env["candidates"][2]["id"], env["exam_form"]["id"], env["codes"][2]["id"],
            "2026-09-10T11:00:00Z", delivery_mode="IN_PERSON",
            testing_site_id=env["testing_site"]["id"],
            proctor_id=env["proctors"][2]["id"]),
        env["provider_headers"]), 201)
    assert adjacent["scheduled_end_at"] == "2026-09-10T13:00:00Z"
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 360

    remote = get_success_data(api.create_exam_session(
        f.create_exam_session_payload(
            env["candidates"][3]["id"], env["exam_form"]["id"], env["codes"][3]["id"],
            _FIRST_START, delivery_mode="REMOTE",
            proctor_id=env["proctors"][3]["id"]),
        env["provider_headers"]), 201)
    assert remote["delivery_mode"] == "REMOTE"
    assert remote["testing_site_id"] is None
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 360
    # A proctor's reserved_minutes is the sum of `allowed_minutes`, and PRD 3.5
    # adds "10 minutes of remote setup time for a REMOTE sitting", so the remote
    # sitting holds 120 + 10 = 130 proctor minutes even though it holds no seat.
    assert remote["allowed_minutes"] == 130
    assert get_success_data(api.get_proctor(
        env["proctors"][3]["id"], admin))["reserved_minutes"] == 130
