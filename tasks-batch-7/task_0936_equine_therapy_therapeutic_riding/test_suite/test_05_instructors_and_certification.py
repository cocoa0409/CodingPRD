"""Instructor registration, the certification clock, renewal and supervision."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    book_session,
    make_instructor_headers,
    read_instructor,
    session_payload,
    set_clock,
    setup_active_rider,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def test_supervisor_filter_finds_every_trainee(api):
    """PRD 3.5: "Instructors are listed and filtered by `certification_status`,
    `certification_level` and `supervisor_instructor_id`, the last of which is
    how a caller finds every trainee reporting to a given supervisor, and read
    individually."
    PRD 3.5: "New instructors start with `ce_hours_accrued` at 0 and
    `suspended_until` null."

    Design: Corner/entities/instructor_self_reference_discoverable_by_supervisor_filter
    """
    set_clock("2026-05-01T00:00:00Z")
    supervisor = validate_success(
        api.create_instructor(
            {
                "full_name": "Ada Reins",
                "certification_level": "MASTER",
                "certification_expires_at": "2028-04-30T00:00:00Z",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    first_trainee = validate_success(
        api.create_instructor(
            {
                "full_name": "Trainee One",
                "certification_level": "IN_TRAINING",
                "certification_expires_at": "2028-04-30T00:00:00Z",
                "supervisor_instructor_id": supervisor["id"],
            },
            ADMIN,
        ),
        expected_status=201,
    )
    second_trainee = validate_success(
        api.create_instructor(
            {
                "full_name": "Trainee Two",
                "certification_level": "IN_TRAINING",
                "certification_expires_at": "2028-04-30T00:00:00Z",
                "supervisor_instructor_id": supervisor["id"],
            },
            ADMIN,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_instructor(
            {
                "full_name": "Cy Cinch",
                "certification_level": "ADVANCED",
                "certification_expires_at": "2028-04-30T00:00:00Z",
            },
            ADMIN,
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_instructors(ADMIN, params={"supervisor_instructor_id": supervisor["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first_trainee["id"], second_trainee["id"]}

    trainee = read_instructor(first_trainee["id"])
    assert trainee["certification_status"] == "CURRENT"
    assert trainee["ce_hours_accrued"] == 0

    _, master_meta = validate_paginated(
        api.list_instructors(ADMIN, params={"certification_level": "MASTER"})
    )
    assert master_meta["total_count"] == 1


def test_grace_instructor_may_complete_but_not_book(api):
    """PRD 2.11: "An instructor's `certification_status` is `SUSPENDED` if
    `suspended_until` is set and the logical clock is before it; otherwise
    `CURRENT` if the logical clock is before `certification_expires_at`;
    otherwise `GRACE` if the logical clock is before 60 days after
    `certification_expires_at`; otherwise `LAPSED`."
    PRD 3.5: "An instructor in `GRACE` may still **complete** a session that is
    already confirmed — the ride happened and the record must be closed — but may
    not **book** a new session and may not **confirm** one, and both refusals are
    `ERR_INSTRUCTOR_CERT_LAPSED`."

    Design: Corner/state_machines/instructor_in_grace_may_complete_an_assigned_session_but_not_book_a_new_one
    """
    scenario = setup_active_rider(
        instructors=[
            {
                "full_name": "Ada Reins",
                "certification_level": "ADVANCED",
                "certification_expires_at": "2026-06-01T00:00:00Z",
            }
        ]
    )
    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-06-15T10:00:00Z",
        duration_minutes=60,
    )
    validate_success(api.confirm_session(session["id"], scenario["instructor_headers"]))

    set_clock("2026-06-15T11:30:00Z")
    assert read_instructor(scenario["instructor_id"])["certification_status"] == "GRACE"

    completed = validate_success(
        api.complete_session(
            session["id"], {"mounted_minutes": 60}, scenario["instructor_headers"]
        )
    )
    assert completed["schedule_status"] == "COMPLETED"

    refused = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-06-20T10:00:00Z",
        ),
        scenario["instructor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_INSTRUCTOR_CERT_LAPSED.value)

    rows, _ = validate_paginated(
        api.list_sessions(ADMIN, params={"instructor_id": scenario["instructor_id"]})
    )
    assert all(row["scheduled_start"][:10] != "2026-06-20" for row in rows)


def test_lapsed_renewal_requires_twenty_ce_hours(api):
    """PRD 3.5: "Renewing with fewer than 20 accrued hours is
    `ERR_CE_HOURS_INSUFFICIENT`, and attempting to renew a certification that is
    already `CURRENT` is `ERR_INVALID_STATE`."
    PRD 3.5: "Then, once at least 20 hours have accrued, the same role may renew
    a certification that is in `GRACE` or `LAPSED` by supplying a `renewed_on`
    date: `certification_expires_at` is recomputed as 730 days — two years —
    after `renewed_on`, `ce_hours_accrued` is reset to 0, and `version`
    increments, returning the instructor to `CURRENT`."

    Design: Corner/state_machines/lapsed_instructor_renewal_requires_ce_hours_then_restores_current
    """
    set_clock("2026-08-01T00:00:00Z")
    instructor = validate_success(
        api.create_instructor(
            {
                "full_name": "Ada Reins",
                "certification_level": "ADVANCED",
                "certification_expires_at": "2026-06-01T00:00:00Z",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert instructor["certification_status"] == "LAPSED"

    accrued = validate_success(
        api.accrue_ce_hours(
            instructor["id"], {"hours": 15, "completed_on": "2026-07-20"}, ADMIN
        )
    )
    assert accrued["ce_hours_accrued"] == pytest.approx(15, abs=0.001)

    refused = api.renew_certification(
        instructor["id"], {"renewed_on": "2026-08-01"}, ADMIN
    )
    validate_error(refused, ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value)

    validate_success(
        api.accrue_ce_hours(
            instructor["id"], {"hours": 5, "completed_on": "2026-07-30"}, ADMIN
        )
    )
    renewed = validate_success(
        api.renew_certification(instructor["id"], {"renewed_on": "2026-08-01"}, ADMIN)
    )
    assert renewed["certification_status"] == "CURRENT"
    assert_same_instant(renewed["certification_expires_at"], "2028-07-31T00:00:00.000Z")
    assert read_instructor(instructor["id"])["ce_hours_accrued"] == pytest.approx(
        0, abs=0.001
    )


def test_trainee_without_a_session_supervisor_is_refused(api):
    """PRD 2.7 rung 25: "Supervision pairing is correct: an instructor of record
    whose `certification_level` is `IN_TRAINING` must be accompanied by a
    `supervising_instructor_id` whose tier ordinal is strictly greater than the
    trainee's, and a `supervising_instructor_id` must be omitted or null when the
    instructor of record is not `IN_TRAINING` — otherwise
    `ERR_SUPERVISOR_REQUIRED` (422). Applies to session creation."

    Design: Corner/validations/in_training_instructor_without_a_supervisor_on_the_session_returns_supervisor_required
    """
    scenario = setup_active_rider(
        instructors=[
            {
                "full_name": "Ada Reins",
                "certification_level": "MASTER",
                "certification_expires_at": "2028-04-30T00:00:00Z",
            }
        ],
    )
    supervisor_id = scenario["instructor_id"]
    trainee = validate_success(
        api.create_instructor(
            {
                "full_name": "Tim Trainee",
                "certification_level": "IN_TRAINING",
                "certification_expires_at": "2028-04-30T00:00:00Z",
                "supervisor_instructor_id": supervisor_id,
            },
            ADMIN,
        ),
        expected_status=201,
    )

    unsupervised = api.create_session(
        session_payload(scenario["rider_id"], scenario["horse_id"], trainee["id"]),
        make_instructor_headers(trainee["id"]),
    )
    validate_error(unsupervised, ApiErrorId.ERR_SUPERVISOR_REQUIRED.value)

    supervised = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"],
                scenario["horse_id"],
                trainee["id"],
                supervising_instructor_id=supervisor_id,
            ),
            make_instructor_headers(trainee["id"]),
        ),
        expected_status=201,
    )
    assert supervised["supervising_instructor_id"] == supervisor_id

    _, meta = validate_paginated(
        api.list_sessions(ADMIN, params={"supervising_instructor_id": supervisor_id})
    )
    assert meta["total_count"] == 1


def test_instructor_intervals_conflict_across_different_horses(api):
    """PRD 2.7 rung 32: "The new session's half-open interval does not intersect
    the half-open interval of another live session naming the same instructor in
    either the `instructor_id` or the `supervising_instructor_id` slot —
    otherwise `ERR_INSTRUCTOR_SCHEDULE_CONFLICT` (409). Applies to session
    creation."

    Design: Corner/validations/overlapping_sessions_on_different_horses_return_instructor_schedule_conflict
    """
    scenario = setup_active_rider(
        horses=[
            {"name": "Comet", "body_weight_lb": 1100, "tack_weight_lb": 30},
            {"name": "Blaze", "body_weight_lb": 1100, "tack_weight_lb": 30},
        ]
    )
    book_session(
        scenario["rider_id"],
        scenario["horse_ids"][0],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:00:00Z",
        duration_minutes=60,
    )

    overlapping = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_ids"][1],
            scenario["instructor_id"],
            scheduled_start="2026-05-11T10:30:00Z",
            duration_minutes=60,
        ),
        scenario["instructor_headers"],
    )
    validate_error(overlapping, ApiErrorId.ERR_INSTRUCTOR_SCHEDULE_CONFLICT.value)

    touching = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"],
                scenario["horse_ids"][1],
                scenario["instructor_id"],
                scheduled_start="2026-05-11T11:00:00Z",
                duration_minutes=60,
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert touching["schedule_status"] == "CREW_PENDING"

    _, meta = validate_paginated(
        api.list_sessions(ADMIN, params={"instructor_id": scenario["instructor_id"]})
    )
    assert meta["total_count"] == 2
