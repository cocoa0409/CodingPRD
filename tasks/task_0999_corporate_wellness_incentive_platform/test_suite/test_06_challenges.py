"""Challenges: publish guards, join, backfill, ingest cascade, sweeps, OCC
(PRD §2.2–2.3, §2.7, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_challenge,
    create_challenge_payload,
    create_employee,
    create_enrollment,
    accept_enrollment,
    create_participation_payload,
    create_program,
    create_active_program,
    create_employer,
    join_challenge,
    make_employee_headers,
    post_activity,
    set_clock,
    setup_active_enrollment,
    setup_employer_with_program,
    validate_error,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


def _employee(ctx):
    return make_employee_headers(ctx["employee"]["id"])


class TestChallengePublish:
    def test_challenge_publish_from_published_rejected(self, api):
        """PRD §3.5: "Publishing moves `DRAFT → PUBLISHED` under two guards..."
        PRD §2.6: "The target resource is in a valid from-state for the requested
        transition; otherwise the state-family error applies — `ERR_INVALID_STATE`
        generically..."

        Design: Corner/state_machines/challenge_publish_from_published_rejected
        """
        ctx = setup_active_enrollment()
        challenge = create_challenge(ctx["program"]["id"], publish=True)
        assert challenge["status"] == "PUBLISHED"

        res = api.publish_challenge(challenge["id"], BA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestJoinPreconditions:
    """Difficulty instance: ChallengeParticipation -> Enrollment cross-entity state
    dependency — joining requires an ACTIVE enrollment."""

    def test_join_with_invited_enrollment_rejected(self, api):
        """PRD §3.5: "Joining requires the enrollment to be `ACTIVE` (otherwise
        `ERR_ENROLLMENT_NOT_ACTIVE`)..."

        Design: Difficulty/cross_entity_state_dependency/join_requires_active_enrollment
        """
        employer, program = setup_employer_with_program()
        employee = create_employee(employer["id"])
        enrollment = create_enrollment(program["id"], employee["id"])  # stays INVITED
        challenge = create_challenge(program["id"], publish=True)

        res = api.create_challenge_participation(
            create_participation_payload(challenge["id"], enrollment["id"]),
            make_employee_headers(employee["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)

    def test_join_with_suspended_enrollment_rejected(self, api):
        """PRD §3.5: "Joining requires the enrollment to be `ACTIVE` (otherwise
        `ERR_ENROLLMENT_NOT_ACTIVE`)..."
        PRD §3.3: "A `BenefitsAdmin` may suspend an `ACTIVE` enrollment
        (`ACTIVE → SUSPENDED`) with no further precondition..."

        Design: Difficulty/cross_entity_state_dependency/join_requires_active_enrollment
        """
        ctx = setup_active_enrollment()
        validate_success(api.suspend_enrollment(ctx["enrollment"]["id"], BA), 200)
        challenge = create_challenge(ctx["program"]["id"], publish=True)

        res = api.create_challenge_participation(
            create_participation_payload(challenge["id"], ctx["enrollment"]["id"]),
            _employee(ctx),
        )
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)


class TestJoinBackfill:
    def test_participation_backfill_completes_on_join(self, api):
        """PRD §3.5: "Upon joining, `progress_quantity` is backfilled by summing the
        `quantity` of the enrollment's already-accepted activity events whose
        `activity_type` matches the challenge and whose `occurred_at` falls inside
        the half-open challenge window; if the backfilled figure already meets the
        goal, the participation completes immediately with the full completion
        cascade described below."

        Design: Corner/endpoints/participation_backfill_completes_on_join
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        challenge = create_challenge(
            ctx["program"]["id"], publish=True, name="Quick Steps", goal_quantity=40000,
        )
        post_activity(enr_id, ctx["employee"]["id"], "evt-1", quantity=50000)

        participation = validate_success(
            api.create_challenge_participation(
                create_participation_payload(challenge["id"], enr_id), _employee(ctx)
            ),
            201,
        )
        assert participation["status"] == "COMPLETED", (
            "backfilled progress 50000 meets goal 40000 at creation"
        )
        assert participation["progress_quantity"] == 50000

        challenge_after = validate_success(api.get_challenge(challenge["id"], BA), 200)
        assert challenge_after["completed_count"] == 1

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 300, "50 EARNED + 250 BONUS"


class TestIngestCascade:
    """Difficulty instance: depth-4 cascade from one activity-event POST."""

    def test_event_acceptance_cascades_to_challenge_completion(self, api):
        """PRD §3.5: "every `JOINED` participation of the enrollment whose challenge
        matches the event's `activity_type` has its `progress_quantity` recomputed
        over the half-open window, and any participation whose progress has reached
        its challenge's `goal_quantity` completes — progress meeting the goal
        exactly counts — moving `JOINED → COMPLETED`..."

        Design: Difficulty/transitive_cascade/activity_ingest_transitive_cascade
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        challenge = create_challenge(ctx["program"]["id"], publish=True)
        participation = join_challenge(challenge["id"], enr_id, ctx["employee"]["id"])

        event = post_activity(enr_id, ctx["employee"]["id"], "evt-1", quantity=100000)
        assert event["points_granted"] == 100

        parts, _meta = validate_paginated(
            api.list_enrollment_challenge_participations(enr_id, BA)
        )
        by_id = {p["id"]: p for p in parts}
        updated = by_id[participation["id"]]
        assert updated["status"] == "COMPLETED"
        assert updated["progress_quantity"] == 100000, (
            "progress meeting the goal exactly counts"
        )

        challenge_after = validate_success(api.get_challenge(challenge["id"], BA), 200)
        assert challenge_after["completed_count"] == 1

    def test_completion_grants_provisional_bonus_entry(self, api):
        """PRD §3.5: "moving `JOINED → COMPLETED`, creating a `BONUS` ledger entry in
        `PROVISIONAL` status for the challenge's `points_reward`, recomputing the
        balances again, and incrementing the challenge's `completed_count` by one."
        PRD §2.8: "The `points_balance_provisional` sums entries in either
        `PROVISIONAL` or `POSTED` status..."

        Design: Difficulty/transitive_cascade/activity_ingest_transitive_cascade
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        challenge = create_challenge(ctx["program"]["id"], publish=True)
        join_challenge(challenge["id"], enr_id, ctx["employee"]["id"])
        event = post_activity(enr_id, ctx["employee"]["id"], "evt-1", quantity=100000)

        entries, meta = validate_paginated(
            api.list_enrollment_points_ledger_entries(enr_id, BA)
        )
        assert meta["total_count"] == 2
        by_kind = {e["kind"]: e for e in entries}
        assert by_kind["EARNED"]["points_delta"] == 100
        assert by_kind["EARNED"]["source_activity_event_id"] == event["id"]
        assert by_kind["BONUS"]["points_delta"] == 250
        assert entries[0]["status"] == "PROVISIONAL"
        assert entries[1]["status"] == "PROVISIONAL"

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 350, "100 EARNED + 250 BONUS"
        assert after["points_balance_settled"] == 0, "nothing is POSTED yet"


class TestChallengeSweep:
    def test_challenge_clock_sweep_fails_incomplete_participation(self, api):
        """PRD §3.5: "When a challenge completes — by clock sweep or by program
        close — every participation still `JOINED` with `progress_quantity` short
        of the goal moves from `JOINED` to `FAILED` with no further effect, while
        those at or beyond the goal complete with the bonus cascade above."
        PRD §2.5: "Every Challenge in `ACTIVE` status whose `ends_at` is strictly
        earlier than the new current instant transitions to `COMPLETED`, resolving
        each still-`JOINED` participation exactly as the challenge-completion rules
        in §3.5 describe."

        Design: Corner/state_machines/challenge_clock_sweep_fails_incomplete_participation
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        challenge = create_challenge(
            ctx["program"]["id"], publish=True, name="April Steps",
            starts_at="2026-04-01T00:00:00Z", ends_at="2026-04-30T00:00:00Z",
        )
        participation = join_challenge(challenge["id"], enr_id, ctx["employee"]["id"])
        post_activity(enr_id, ctx["employee"]["id"], "evt-1", quantity=50000)

        set_clock("2026-05-02T00:00:00Z")

        challenge_after = validate_success(api.get_challenge(challenge["id"], BA), 200)
        assert challenge_after["status"] == "COMPLETED"
        assert challenge_after["completed_count"] == 0

        parts, _meta = validate_paginated(
            api.list_enrollment_challenge_participations(enr_id, BA)
        )
        by_id = {p["id"]: p for p in parts}
        assert by_id[participation["id"]]["status"] == "FAILED"
        assert by_id[participation["id"]]["progress_quantity"] == 50000

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 50, "EARNED only; no BONUS granted"


class TestJoinProgramMismatch:
    def test_challenge_join_program_mismatch_rejected(self, api):
        """PRD §3.5: "Joining requires the enrollment to be `ACTIVE` (otherwise
        `ERR_ENROLLMENT_NOT_ACTIVE`), the challenge to be `PUBLISHED` or `ACTIVE`
        (otherwise `ERR_INVALID_STATE`), both to belong to the same program
        (otherwise `ERR_CHALLENGE_PROGRAM_MISMATCH`)..."
        PRD §3.2: "Because both windows are half-open, pure adjacency — one
        program's `plan_year_end` landing exactly on the other's `plan_year_start` —
        does not count as overlap and is allowed."

        Design: Corner/validations/challenge_join_program_mismatch_rejected
        """
        employer = create_employer()
        program_1 = create_active_program(employer["id"])  # [2026-01-01, 2027-01-01)
        program_2 = create_program(
            employer["id"], name="PY2027",
            plan_year_start="2027-01-01", plan_year_end="2028-01-01",
        )
        activated = validate_success(api.activate_program(program_2["id"], BA), 200)
        assert activated["status"] == "ACTIVE", "adjacent windows do not overlap"

        employee = create_employee(employer["id"])
        enrollment = accept_enrollment(
            create_enrollment(program_1["id"], employee["id"])["id"], employee["id"]
        )
        challenge_2 = create_challenge(
            program_2["id"], publish=True, name="Winter Steps", goal_quantity=50000,
            points_reward=100,
            starts_at="2027-02-01T00:00:00Z", ends_at="2027-03-01T00:00:00Z",
        )

        res = api.create_challenge_participation(
            create_participation_payload(challenge_2["id"], enrollment["id"]),
            make_employee_headers(employee["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CHALLENGE_PROGRAM_MISMATCH, expected_status=422)


class TestChallengeListing:
    def test_challenge_list_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and
        maximum of 100. The `offset` parameter specifies the number of items to
        skip and defaults to 0."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/endpoints/challenge_list_pagination_defaults_and_envelope
        """
        ctx = setup_active_enrollment()
        challenge = create_challenge(ctx["program"]["id"])

        response = api.list_program_challenges(ctx["program"]["id"], BA)
        body = response.json()
        data, meta = validate_paginated(response)
        assert body["response_type"] == "array"
        assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
        assert len(data) == 1 and data[0]["id"] == challenge["id"]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"


class TestChallengeOcc:
    def test_occ_stale_challenge_patch_rejected(self, api):
        """PRD §2.7: "Editing a `DRAFT` Challenge requires `expected_challenge_version`
        matching that challenge's current `version`. If another writer has advanced
        the challenge's version since the client last observed it, the edit is
        rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_stale_challenge_patch_rejected
        """
        ctx = setup_active_enrollment()
        challenge = create_challenge(ctx["program"]["id"])
        stale_version = challenge["version"]

        first = validate_success(
            api.patch_challenge(
                challenge["id"],
                {"goal_quantity": 90000, "expected_challenge_version": stale_version},
                BA,
            ),
            200,
        )
        assert first["goal_quantity"] == 90000

        res = api.patch_challenge(
            challenge["id"],
            {"points_reward": 300, "expected_challenge_version": stale_version},
            BA,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = validate_success(api.get_challenge(challenge["id"], BA), 200)
        assert after["points_reward"] == 250, "the rejected PATCH must leave no trace"
