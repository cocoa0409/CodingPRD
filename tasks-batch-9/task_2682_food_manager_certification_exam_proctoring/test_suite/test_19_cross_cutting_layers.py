"""The layers that cut across every write: the two optimistic-concurrency guards
and the four-phase ordering of the compliance run."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_proctor,
    assign_code,
    factories as f,
    get_success_data,
    purchase_batch,
    read_batch,
    run_compliance,
    schedule_session,
    set_clock,
    setup_landscape,
    setup_sitting,
    validate_error,
    validate_paginated,
)

_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]


def _three_unit_batch(api):
    """Two candidates under one provider and one ACTIVE batch of 3 EXAM_ONLY units."""
    env = setup_landscape(testing_site={"seat_count": 2})
    env["first_candidate"] = add_candidate(env)
    env["second_candidate"] = add_candidate(env)
    env["proctor"] = add_proctor(env)
    env["batch"] = purchase_batch(
        env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 3}])
    return env


def test_a_replayed_batch_version_is_refused_and_bumps_nothing(api):
    """A second assignment out of a still-ACTIVE batch is ordinary product behaviour,
    so only the stale version can explain the 412 — and the refusal moves no counter.

    PRD: "If that value does not equal the batch's current `version`, the assignment is
    rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412)."

    PRD: "`version` is an integer that starts at 1 when the resource is created and
    increments by exactly 1 on every mutation of that resource; `updated_at` is refreshed
    to the current logical clock on the same mutation."

    PRD: "The winning code moves `AVAILABLE → ASSIGNED` with its `candidate_id` set and
    `assigned_at` set to the logical clock; the batch's `available_count` falls by one,
    its `assigned_count` rises by one, and its `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_superseded_parent_version_and_bump_it_only_on_success
    """
    env = _three_unit_batch(api)
    provider_headers, batch_id = env["provider_headers"], env["batch"]["id"]
    opened = read_batch(env, batch_id)
    assert opened["total_price_cents"] == 11286
    assert (opened["version"], opened["available_count"]) == (1, 3)

    first = get_success_data(api.assign_access_code(
        batch_id,
        f.create_assignment_payload(env["first_candidate"]["id"], opened["version"]),
        provider_headers), 201)
    assert first["status"] == "ASSIGNED"
    after_first = read_batch(env, batch_id)
    assert (after_first["version"], after_first["available_count"],
            after_first["assigned_count"]) == (2, 2, 1)

    replayed = api.assign_access_code(
        batch_id,
        f.create_assignment_payload(env["second_candidate"]["id"], opened["version"]),
        provider_headers)
    validate_error(replayed, "ERR_STALE_BATCH_VERSION", 412)

    after_stale = read_batch(env, batch_id)
    assert (after_stale["version"], after_stale["available_count"],
            after_stale["assigned_count"]) == (2, 2, 1)

    retried = get_success_data(api.assign_access_code(
        batch_id,
        f.create_assignment_payload(env["second_candidate"]["id"],
                                    after_stale["version"]),
        provider_headers), 201)
    assert retried["candidate_id"] == env["second_candidate"]["id"]
    final = read_batch(env, batch_id)
    assert (final["version"], final["available_count"],
            final["assigned_count"]) == (3, 1, 2)


def test_a_replayed_session_version_is_refused_and_bumps_nothing(api):
    """A sitting may be re-timed repeatedly while it stays SCHEDULED, so the second
    reschedule fails on the superseded version alone and the interval never moves.

    PRD: "A mismatch with the session's current `version` is rejected with
    `ERR_STALE_SESSION_VERSION` (HTTP 412)."

    PRD: "On success `scheduled_start_at` is replaced, `allowed_minutes` and
    `scheduled_end_at` are recomputed by the rule above, `reschedule_count` grows by one,
    the released interval is deducted from the site's `reserved_seat_minutes` and the
    proctor's `reserved_minutes` before the new interval is reserved, a supplied
    `proctor_id` moves `proctoring_status` `PENDING_REPROCTOR → ASSIGNED`, and the
    sitting's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_superseded_parent_version_and_bump_it_only_on_success
    """
    env = _three_unit_batch(api)
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    code, batch = assign_code(env, env["batch"], env["first_candidate"])
    session = schedule_session(env, env["first_candidate"], code,
                              "2026-09-12T09:00:00Z", proctor=env["proctor"])
    assert (session["version"], session["reschedule_count"]) == (1, 0)
    assert session["scheduled_start_at"] == "2026-09-12T09:00:00Z"

    moved = get_success_data(api.reschedule_exam_session(
        session["id"],
        f.create_reschedule_payload("2026-09-13T09:00:00Z", session["version"]),
        provider_headers))
    assert (moved["version"], moved["reschedule_count"]) == (2, 1)
    assert moved["scheduled_start_at"] == "2026-09-13T09:00:00Z"

    replayed = api.reschedule_exam_session(
        session["id"],
        f.create_reschedule_payload("2026-09-14T09:00:00Z", session["version"]),
        provider_headers)
    validate_error(replayed, "ERR_STALE_SESSION_VERSION", 412)

    after_stale = get_success_data(api.get_exam_session(session["id"], admin))
    assert (after_stale["version"], after_stale["reschedule_count"]) == (2, 1)
    assert after_stale["scheduled_start_at"] == "2026-09-13T09:00:00Z"
    assert after_stale["session_status"] == "SCHEDULED"

    retried = get_success_data(api.reschedule_exam_session(
        session["id"],
        f.create_reschedule_payload("2026-09-14T09:00:00Z", after_stale["version"]),
        provider_headers))
    assert (retried["version"], retried["reschedule_count"]) == (3, 2)
    assert retried["scheduled_start_at"] == "2026-09-14T09:00:00Z"
    assert retried["scheduled_end_at"] == "2026-09-14T11:00:00Z"


def test_the_run_phases_are_ordered_and_a_replay_at_the_same_epoch_is_inert(api):
    """One registration is caught by phase two's predicate and phase three's at once,
    so its WITHDRAWN status and the zero delinquent count prove the pinned order, and
    phase four then reads the status phase two produced.

    PRD: "The run executes four phases in a pinned order, and each phase sees the world
    the earlier phases produced."

    PRD: "An `ASSIGNED` code held by a sitting that is already `CHECKED_IN` or
    `IN_PROGRESS` is left alone — a candidate mid-exam is not disconnected by a sweep —
    whereas a `SCHEDULED` sitting holding an expired code is moved to `CANCELLED` without
    the code being returned to the batch."

    PRD: "Every certificate whose `status` is `ISSUED` and whose `expires_at` is at or
    before `run_epoch` — the comparison is inclusive — moves `ISSUED → EXPIRED`; its
    holder's `compliance_status` drops to `LAPSED`, and its local registrations in
    `FILED`, `POSTED`, `VERIFIED` or `DELINQUENT` move to `WITHDRAWN`."

    PRD: "Every local registration whose `status` is `FILED`, whose `posted_at` is still
    null, and whose `posting_deadline_at` falls strictly before `run_epoch` moves `FILED →
    DELINQUENT`."

    PRD: "Dispatching appends the chosen tier to that certificate's `reminder_tiers_sent`,
    in dispatch order, and a tier already present is never appended twice, so a
    certificate whose `T_90` was sent by an earlier run is skipped rather than re-notified
    until it becomes due for a different tier."

    Design: Corner/cross_cutting_complexity_layers/the_four_run_phases_are_ordered_and_a_replay_at_the_same_epoch_changes_nothing
    """
    env = setup_sitting(stage="FILED", start_at="2026-09-12T10:30:00Z",
                        scored_correct_count=60, expires_at="2032-12-31T00:00:00Z",
                        scoring_admin_headers=_SCORING_ADMIN)
    admin = env["admin_headers"]
    certificate, registration = env["certificate"], env["local_registration"]
    assert env["score_report"]["pass_flag"] is True
    assert certificate["expires_at"] == "2031-09-12T10:30:00Z"
    assert certificate["recert_window_opens_at"] == "2031-03-16T10:30:00Z"
    assert certificate["reminder_tiers_sent"] == []
    assert registration["posting_deadline_at"] == "2026-10-12T10:30:00Z"

    other_candidate = add_candidate(env)
    doomed_batch = purchase_batch(env, expires_at="2031-06-30T00:00:00Z",
                                  line_items=[{"bundle_type": "EXAM_ONLY",
                                               "quantity": 1}])
    doomed_code, doomed_batch = assign_code(env, doomed_batch, other_candidate)
    future_sitting = schedule_session(env, other_candidate, doomed_code,
                                      "2031-10-01T09:00:00Z", proctor=env["proctor"])
    assert future_sitting["session_status"] == "SCHEDULED"

    set_clock("2031-09-12T10:30:00Z", admin)
    first_run = run_compliance(env)

    assert first_run["run_epoch"] == "2031-09-12T10:30:00Z"
    assert first_run["certificates_expired_count"] == 1
    assert first_run["batches_expired_count"] == 1
    assert first_run["reminder_notices_sent_count"] == 1
    assert first_run["notified_certificate_ids"] == [certificate["id"]]
    assert first_run["registrations_delinquent_count"] == 0

    withdrawn = get_success_data(api.get_local_registration(registration["id"], admin))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["posted_at"] is None
    expired = get_success_data(api.get_certificate(certificate["id"], admin))
    assert expired["status"] == "EXPIRED"
    assert expired["reminder_tiers_sent"] == ["T_LAPSED"]
    assert get_success_data(api.get_candidate(
        env["candidate"]["id"], admin))["compliance_status"] == "LAPSED"

    swept = read_batch(env, doomed_batch["id"])
    assert swept["status"] == "EXPIRED"
    assert (swept["available_count"], swept["assigned_count"],
            swept["voided_count"]) == (0, 0, 1)
    assert get_success_data(api.get_access_code(
        doomed_code["id"], env["provider_headers"]))["status"] == "EXPIRED"
    assert get_success_data(api.get_exam_session(
        future_sitting["id"], admin))["session_status"] == "CANCELLED"
    assert read_batch(env, env["batch"]["id"])["status"] == "DEPLETED"

    second_run = run_compliance(env)

    assert second_run["run_epoch"] == "2031-09-12T10:30:00Z"
    assert second_run["certificates_expired_count"] == 0
    assert second_run["registrations_delinquent_count"] == 0
    assert second_run["batches_expired_count"] == 0
    assert second_run["reminder_notices_sent_count"] == 0
    assert second_run["notified_certificate_ids"] == []
    replayed = get_success_data(api.get_certificate(certificate["id"], admin))
    assert replayed["status"] == "EXPIRED"
    assert replayed["reminder_tiers_sent"] == ["T_LAPSED"]
    data, meta = validate_paginated(api.list_local_registrations(
        admin, params={"certificate_id": certificate["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["status"] == "WITHDRAWN"
