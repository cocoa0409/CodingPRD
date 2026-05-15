"""Concurrency / serialisation guarantees (PRD §3.11, §2.4)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    create_booking_payload,
    create_client,
    create_sample,
    create_task,
    create_tester,
    qualification,
    run_race,
    setup_assigned_task,
    setup_completed_task,
    setup_workload_cap_environment,
    update_client_payload,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    anchor_plus,
    book_instrument_for_task,
)


class TestBookingOverlapRace:
    def test_two_overlapping_bookings_serialise_first_writer_wins(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.4: 'When two callers submit simultaneous bookings
        whose intervals would overlap, the system serialises
        first-writer-wins on the (instrument, overlapping-interval)
        pair: exactly one booking succeeds, and the loser receives
        ERR_INSTRUMENT_SLOT_CONFLICT.'

        Claim: exactly one of two concurrent overlapping booking
        attempts succeeds; the loser is ERR_INSTRUMENT_SLOT_CONFLICT.
        """
        env = setup_assigned_task()
        # Two simultaneous booking calls for the same task, same
        # instrument, overlapping slots.
        slot_start = anchor_plus(hours=10)
        slot_end = anchor_plus(hours=11)
        # Need two distinct task contexts so both calls are syntactically
        # valid creation requests; we pre-create two tasks for the same
        # tester (capacity allows).
        from test_helpers import create_sample as _cs, create_task as _ct
        s1 = _cs(client_id=env["client"]["id"], material_category="CONCRETE")
        s2 = _cs(client_id=env["client"]["id"], material_category="CONCRETE")
        task1 = _ct(sample_id=s1["id"],
                    test_method="COMPRESSION_STRENGTH")
        task2 = _ct(sample_id=s2["id"],
                    test_method="COMPRESSION_STRENGTH")
        instrument_id = env["instrument"]["id"]

        payload_a = create_booking_payload(
            task_id=task1["id"], slot_start=slot_start, slot_end=slot_end,
        )
        payload_b = create_booking_payload(
            task_id=task2["id"], slot_start=slot_start, slot_end=slot_end,
        )
        result_a, result_b = run_race(
            lambda: api.create_instrument_booking(
                instrument_id, payload_a, lab_clerk_headers,
            ),
            lambda: api.create_instrument_booking(
                instrument_id, payload_b, lab_clerk_headers,
            ),
        )
        outcomes = assert_exactly_one_succeeds(result_a, result_b)
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INSTRUMENT_SLOT_CONFLICT.value)


class TestClientPatchVersionConflictRace:
    def test_concurrent_patches_with_same_version(
        self, api, lab_manager_headers,
    ):
        """PRD §3.11: 'When two concurrent client-update requests by a
        LabManager carry the same version value and both attempt to
        modify contact_email on the same Client, exactly one update
        succeeds and the second observes a stale version, returning
        ERR_VERSION_CONFLICT.'

        Claim: exactly one PATCH wins, the other is
        ERR_VERSION_CONFLICT.
        """
        client = create_client()
        payload_a = update_client_payload(
            version=client["version"], contact_email="a@example.test",
        )
        payload_b = update_client_payload(
            version=client["version"], contact_email="b@example.test",
        )
        res_a, res_b = run_race(
            lambda: api.update_client(
                client["id"], payload_a, lab_manager_headers,
            ),
            lambda: api.update_client(
                client["id"], payload_b, lab_manager_headers,
            ),
        )
        outcomes = assert_exactly_one_succeeds(res_a, res_b)
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestReportSignVsSendBackRace:
    def test_concurrent_sign_and_send_back_one_wins(self, api):
        """PRD §3.9: 'Two reviewers acting concurrently — one sending
        back, one (via signatory) signing — serialise first-writer-wins
        on the report's status; the loser sees ERR_INVALID_STATE
        because the report's status no longer matches the expected
        from-state.'

        Claim: exactly one of concurrent send-back vs sign succeeds;
        the loser is ERR_INVALID_STATE.
        """
        from test_helpers import (
            approve_review, make_reviewer_headers, make_signatory_headers,
            mint_report, submit_for_review,
        )
        env = setup_completed_task()
        report = mint_report(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
        )
        submit_for_review(
            report_id=report["id"], tester_id=env["tester"]["id"],
        )
        approve_review(
            report_id=report["id"], reviewer_id=env["reviewer"]["id"],
        )
        res_a, res_b = run_race(
            lambda: api.send_back_review(
                report["id"], make_reviewer_headers(env["reviewer"]["id"]),
            ),
            lambda: api.sign_report(
                report["id"], make_signatory_headers(env["signatory"]["id"]),
            ),
        )
        outcomes = assert_exactly_one_succeeds(res_a, res_b)
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


class TestWorkloadAssignmentRace:
    def test_two_simultaneous_assigns_to_last_capacity_one_wins(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.11: 'When two assignment attempts target the last
        available qualified Tester whose active_task_count equals
        max_concurrent_tasks minus one, exactly one assignment
        succeeds; the loser receives ERR_TESTER_WORKLOAD_EXCEEDED and
        the loser's task remains PENDING_ASSIGNMENT.'

        Claim: exactly one of two concurrent explicit /assign calls
        succeeds; the loser is ERR_TESTER_WORKLOAD_EXCEEDED.
        """
        # Single tester qualified for CONCRETE with cap=1, active=0. This
        # ensures the race targets ONLY this tester so the PRD §3.11
        # workload-race split is observable.
        client2 = create_client()
        tester2 = create_tester(
            qualifications=[
                qualification("CONCRETE", "2024-01-01", "2200-12-31"),
            ],
            max_concurrent_tasks=1,
        )
        s_x = create_sample(
            client_id=client2["id"], material_category="CONCRETE",
        )
        s_y = create_sample(
            client_id=client2["id"], material_category="CONCRETE",
        )
        # Race two POST /samples/{id}/tasks — both will try to auto-
        # assign to tester2 (the only qualified one). With cap=1 only
        # one can take the slot.
        from test_helpers import create_test_task_payload as _payload
        res_a, res_b = run_race(
            lambda: api.create_test_task(
                s_x["id"], _payload(test_method="COMPRESSION_STRENGTH"),
                lab_clerk_headers,
            ),
            lambda: api.create_test_task(
                s_y["id"], _payload(test_method="COMPRESSION_STRENGTH"),
                lab_clerk_headers,
            ),
        )
        # Both create calls return 201 because the task itself is
        # created; one auto-assigns, the other remains
        # PENDING_ASSIGNMENT. PRD §3.3 quotes: 'if no tester satisfies
        # this combined filter, no assignment is made and the task
        # remains PENDING_ASSIGNMENT.' That makes BOTH 201 responses
        # legitimate even when the workload race is lost. We therefore
        # assert via the resulting task statuses instead.
        from test_helpers import get_success_data
        ta = get_success_data(res_a)
        tb = get_success_data(res_b)
        statuses = {ta["status"], tb["status"]}
        # Exactly one must be ASSIGNED, exactly one PENDING_ASSIGNMENT.
        assert ("ASSIGNED" in statuses
                and "PENDING_ASSIGNMENT" in statuses), (
            f"expected race split, got statuses {statuses}"
        )
        assigned = ta if ta["status"] == "ASSIGNED" else tb
        pending = ta if ta["status"] == "PENDING_ASSIGNMENT" else tb
        assert assigned["assigned_tester_id"] == tester2["id"]
        assert pending["assigned_tester_id"] is None
        # And an explicit /assign on the pending task surfaces the
        # workload-exceeded error.
        assign_resp = api.assign_task(
            pending["id"], TEST_USERS["lab_manager_headers"],
        )
        validate_error(
            assign_resp, ApiErrorId.ERR_TESTER_WORKLOAD_EXCEEDED.value,
        )
