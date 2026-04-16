"""Concurrency guarantees — PRD §2.8."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    run_race, assert_exactly_one_succeeds, assert_race_outcome,
    validate_error_is_one_of,
    setup_approved_application,
    setup_ready_for_approval, submit_application,
    walk_application_to_under_review,
    create_shelter, create_boardable_animal, create_adopter,
    create_reservation_payload,
    make_approver_headers, make_reviewer_headers,
    create_pending_settlement, create_and_capture_settlement,
    fill_shelter_to_capacity,
)
from datetime import datetime, timezone, timedelta


class TestConcurrentApprove:
    def test_two_applications_same_animal_only_one_approves(self):
        """PRD §2.8: "When two approvers simultaneously call approve for different
        applications targeting the same animal, the first-writer-wins on the
        AVAILABLE -> HELD transition; the loser receives ERR_ANIMAL_ALREADY_RESERVED
        with HTTP 409"."""
        ctx = setup_ready_for_approval()
        from test_helpers import create_adopter_with_passed_home_visit
        adopter2 = create_adopter_with_passed_home_visit(inspector_user_id="insp-conc-2")
        app1 = submit_application(ctx["adopter"]["id"], ctx["animal"]["id"])
        app2 = submit_application(adopter2["id"], ctx["animal"]["id"])
        walk_application_to_under_review(app1["id"], reviewer_user_id="rev-conc-1")
        walk_application_to_under_review(app2["id"], reviewer_user_id="rev-conc-2")

        def approve_app1():
            return api_client.approve_application(app1["id"], make_approver_headers("app-conc-a"))

        def approve_app2():
            return api_client.approve_application(app2["id"], make_approver_headers("app-conc-b"))

        results = run_race(approve_app1, approve_app2)
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        # Loser gets ERR_ANIMAL_ALREADY_RESERVED per PRD §2.8
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [ApiErrorId.ERR_ANIMAL_ALREADY_RESERVED.value])


class TestConcurrentReservation:
    def test_race_for_last_slot_exactly_one_wins(self):
        """PRD §2.8: "When two boarding reservations race for the final slot of a
        shelter (i.e., available_slots == 1) ... exactly one caller succeeds;
        the loser receives ERR_SHELTER_AT_CAPACITY"."""
        shelter = create_shelter(boarding_capacity=2)
        # Fill so only 1 slot remains
        fill_shelter_to_capacity(shelter["id"], leaving_free=1)
        # Two candidate reservations
        animal1 = create_boardable_animal(shelter["id"])
        animal2 = create_boardable_animal(shelter["id"])
        adopter = create_adopter()

        def res1():
            payload = create_reservation_payload(
                animal_id=animal1["id"], owner_id=adopter["id"], nights=2)
            return api_client.create_reservation(
                shelter["id"], payload, TEST_USERS["boarding_coordinator_headers"])

        def res2():
            payload = create_reservation_payload(
                animal_id=animal2["id"], owner_id=adopter["id"], nights=2)
            return api_client.create_reservation(
                shelter["id"], payload, TEST_USERS["boarding_coordinator_headers"])

        results = run_race(res1, res2)
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [ApiErrorId.ERR_SHELTER_AT_CAPACITY.value])


class TestConcurrentCaptureRefund:
    def test_capture_and_refund_race_exactly_one_wins(self):
        """PRD §2.8: "When capture and refund are invoked simultaneously on the same
        FeeSettlement, exactly one succeeds; the loser receives ERR_INVALID_STATE"."""
        ctx = setup_approved_application()
        # Create a PENDING settlement; capture and then refund are separate states.
        # Race: capture vs refund on PENDING — refund requires COMPLETED, so refund
        # would fail on state alone. Per PRD §2.8, the race is on the same settlement
        # id: one wins, the other loses with ERR_INVALID_STATE.
        settlement = create_pending_settlement(
            "ADOPTION", ctx["application"]["id"],
            ctx["application"]["pinned_fee"])

        def capture():
            return api_client.capture_settlement(settlement["id"],
                                                 TEST_USERS["finance_officer_headers"])

        def refund():
            return api_client.refund_settlement(settlement["id"],
                                                TEST_USERS["finance_officer_headers"])

        results = run_race(capture, refund)
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [ApiErrorId.ERR_INVALID_STATE.value])
