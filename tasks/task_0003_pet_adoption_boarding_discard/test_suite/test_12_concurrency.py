"""
Tests for concurrency safeguards: optimistic concurrency control, version pinning,
and race conditions explicitly defined in the PRD (Table 2.1).
Claims from Table 2.1 (concurrency rules), PRD section 2.9, 3.8.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    assert_version_incremented,
    assert_exactly_one_succeeds,
    run_race,
    create_shelter,
    create_shelter_with_fee_schedules,
    create_available_animal,
    create_adopter_in_shelter,
    create_animal_in_shelter,
    vaccinate_animal,
    submit_application,
    start_application_review,
    complete_application_review,
    application_to_reviewed,
    approve_application,
    pay_invoice_fully,
    create_boarding_reservation,
    confirm_boarding,
    check_in_boarding,
    create_hold_on_animal,
    create_payment_payload,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
)
from test_helpers.factories import _future_iso


class TestOptimisticConcurrency:
    """PRD 2.9: Stale version on PATCH -> ERR_STALE_DATA."""

    def test_animal_stale_version_rejected(self, api, caseworker_headers):
        """Update animal with stale version -> ERR_STALE_DATA."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        stale_version = animal["version"]

        # Modify animal to advance version
        api.update_animal(animal["id"], {"name": "First Update"}, caseworker_headers)

        # Attempt update with stale version
        res = api.update_animal(
            animal["id"],
            {"name": "Stale Update", "version": stale_version},
            caseworker_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_DATA)

    def test_animal_correct_version_succeeds(self, api, caseworker_headers):
        """Update animal with correct version -> success."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])

        # Update with current version
        res = api.update_animal(
            animal["id"],
            {"name": "Correct Update", "version": animal["version"]},
            caseworker_headers,
        )
        updated = validate_success(res, 200)
        assert updated["name"] == "Correct Update"
        assert_version_incremented(updated["version"], animal["version"])

    def test_animal_no_version_skips_check(self, api, caseworker_headers):
        """Update without version field -> unconditional success."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        # Advance version
        api.update_animal(animal["id"], {"name": "First"}, caseworker_headers)

        # Update without version -> should succeed
        res = api.update_animal(
            animal["id"], {"name": "No Version"}, caseworker_headers,
        )
        updated = validate_success(res, 200)
        assert updated["name"] == "No Version"

    def test_adopter_stale_version_rejected(self, api, caseworker_headers):
        """Update adopter with stale version -> ERR_STALE_DATA."""
        shelter = create_shelter()
        adopter = create_adopter_in_shelter(shelter["id"])
        stale_version = adopter["version"]

        api.update_adopter(adopter["id"], {"full_name": "First"}, caseworker_headers)

        res = api.update_adopter(
            adopter["id"],
            {"full_name": "Stale", "version": stale_version},
            caseworker_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_DATA)


class TestConcurrentAdoptionApprovals:
    """
    PRD 3.8 / Table 2.1: At most one APPROVED/COMPLETED application per animal.
    Two approvals for the same animal -> second fails with ERR_ANIMAL_NOT_AVAILABLE.
    """

    def test_two_approvals_same_animal_second_fails(self, api, manager_headers, caseworker_headers):
        """
        Submit two applications for the same animal.
        Approve the first -> animal becomes ADOPTION_PENDING.
        Attempt to approve second -> ERR_ANIMAL_NOT_AVAILABLE.
        """
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter1 = create_adopter_in_shelter(shelter["id"], full_name="Adopter One")
        adopter2 = create_adopter_in_shelter(shelter["id"], full_name="Adopter Two")

        app1 = application_to_reviewed(animal["id"], adopter1["id"], species="CAT")
        app2 = submit_application(animal["id"], adopter2["id"])

        # Approve first
        approve_application(app1["id"])

        # Second should fail at start-review or approval due to animal not available
        res = api.start_review(app2["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE)

    def test_concurrent_approval_race(self, api, manager_headers):
        """
        Table 2.1: Two simultaneous approvals -> at most one succeeds.
        Uses run_race to test concurrent approval attempts.
        """
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")

        # Create two adopters and get their apps to REVIEWED
        adopter1 = create_adopter_in_shelter(shelter["id"], full_name="Race Adopter 1")
        adopter2 = create_adopter_in_shelter(shelter["id"], full_name="Race Adopter 2")

        # We need two different reviewers and two different managers
        cw1 = TEST_USERS["caseworker_headers"]
        cw2 = TEST_USERS["caseworker2_headers"]
        mgr1 = TEST_USERS["manager_headers"]
        mgr2 = TEST_USERS["manager2_headers"]

        app1 = submit_application(animal["id"], adopter1["id"])
        app1 = start_application_review(app1["id"], cw1)
        app1 = complete_application_review(app1["id"], cw1)

        app2 = submit_application(animal["id"], adopter2["id"])
        app2 = start_application_review(app2["id"], cw2)
        app2 = complete_application_review(app2["id"], cw2)

        results = run_race(
            lambda: api.approve_application(app1["id"], mgr1),
            lambda: api.approve_application(app2["id"], mgr2),
        )

        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The failure should be ERR_ANIMAL_NOT_AVAILABLE
        for resp in outcome["failures"]:
            validate_error_is_one_of(resp, [
                ApiErrorId.ERR_ANIMAL_NOT_AVAILABLE,
            ])


class TestConcurrentBoardingConfirmations:
    """
    Table 2.1: Two boarding confirmations for same animal with overlapping dates.
    At most one confirmed.
    """

    def test_concurrent_boarding_confirmation_race(self, api, manager_headers):
        """
        Two overlapping reservations for same animal confirmed concurrently.
        At most one succeeds; loser gets ERR_BOARDING_DATE_OVERLAP.
        """
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)

        r1 = create_boarding_reservation(
            shelter["id"], animal["id"],
            check_in_date=_future_iso(days=5),
            check_out_date=_future_iso(days=15),
        )
        r2 = create_boarding_reservation(
            shelter["id"], animal["id"],
            check_in_date=_future_iso(days=10),
            check_out_date=_future_iso(days=20),
        )

        mgr1 = TEST_USERS["manager_headers"]
        mgr2 = TEST_USERS["manager2_headers"]

        results = run_race(
            lambda: api.confirm_boarding_reservation(r1["id"], mgr1),
            lambda: api.confirm_boarding_reservation(r2["id"], mgr2),
        )

        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for resp in outcome["failures"]:
            validate_error_is_one_of(resp, [
                ApiErrorId.ERR_BOARDING_DATE_OVERLAP,
            ])


class TestConcurrentPaymentAndVoid:
    """
    Table 2.1: Fee invoice payment while invoice is being voided simultaneously.
    Exactly one wins; loser gets ERR_INVALID_STATE.
    """

    def test_concurrent_pay_and_void(self, api, caseworker_headers, manager_headers):
        """Payment vs void race on same invoice -> exactly one succeeds."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )

        results = run_race(
            lambda: api.pay_invoice(
                invoice["id"],
                create_payment_payload(invoice["total_amount"]),
                caseworker_headers,
            ),
            lambda: api.void_invoice(invoice["id"], manager_headers),
        )

        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for resp in outcome["failures"]:
            validate_error_is_one_of(resp, [
                ApiErrorId.ERR_INVALID_STATE,
                ApiErrorId.ERR_INVOICE_HAS_PAYMENTS,
            ])
