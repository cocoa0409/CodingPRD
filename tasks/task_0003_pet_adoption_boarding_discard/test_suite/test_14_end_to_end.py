"""
End-to-end integration tests covering full lifecycle flows.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    assert_shelter,
    assert_animal,
    assert_adoption_application,
    assert_boarding_reservation,
    assert_fee_invoice,
    assert_shelter_invariants,
    assert_invoice_invariants,
    assert_cost_precision,
    create_shelter,
    create_shelter_with_fee_schedules,
    create_available_animal,
    create_animal_in_shelter,
    create_adopter_in_shelter,
    vaccinate_animal,
    submit_application,
    start_application_review,
    require_home_visit_on_application,
    complete_application_review,
    application_to_reviewed,
    approve_application,
    complete_adoption,
    pay_invoice_fully,
    schedule_home_visit,
    complete_home_visit_with_result,
    create_boarding_reservation,
    confirm_boarding,
    check_in_boarding,
    check_out_boarding,
    create_hold_on_animal,
    resolve_hold,
    create_repeat_adopter,
    create_payment_payload,
    ApiErrorId,
    TEST_USERS,
)


class TestFullAdoptionLifecycleDog:
    """Complete DOG adoption: intake -> vaccinate -> make available -> apply ->
    review -> home visit -> approve -> pay -> complete."""

    def test_dog_adoption_full_lifecycle(self, api, caseworker_headers, manager_headers, vet_headers):
        """Full DOG adoption lifecycle with all steps and side effects verified."""
        shelter = create_shelter_with_fee_schedules()
        mgr = manager_headers
        cw = caseworker_headers

        # Register animal
        animal = create_available_animal(shelter["id"], species="DOG")
        assert animal["status"] == "AVAILABLE"
        assert animal["vaccination_compliant"] is True
        assert animal["adoption_eligible"] is True

        # Register adopter
        adopter = create_adopter_in_shelter(shelter["id"])
        assert adopter["status"] == "ACTIVE"
        assert adopter["adoption_history_count"] == 0

        # Submit application
        app = submit_application(animal["id"], adopter["id"])
        assert app["status"] == "SUBMITTED"

        # Start review
        app = start_application_review(app["id"], cw)
        assert app["status"] == "UNDER_REVIEW"
        assert app["reviewer_id"] is not None
        assert app["animal_version"] is not None
        assert app["adopter_version"] is not None

        # Require and conduct home visit
        app = require_home_visit_on_application(app["id"], cw)
        assert app["status"] == "HOME_VISIT_REQUIRED"

        visit = schedule_home_visit(adopter["id"], app["id"])
        assert visit["status"] == "SCHEDULED"

        app_state = validate_success(api.get_adoption_application(app["id"], cw), 200)
        assert app_state["status"] == "HOME_VISIT_SCHEDULED"

        complete_home_visit_with_result(visit["id"], result="PASS", caseworker_headers=cw)

        app = validate_success(api.get_adoption_application(app["id"], cw), 200)
        assert app["status"] == "REVIEWED"

        adopter_state = validate_success(api.get_adopter(adopter["id"], cw), 200)
        assert adopter_state["home_visit_passed"] is True

        # Approve
        app = approve_application(app["id"], mgr)
        assert app["status"] == "APPROVED"
        assert app["fee_invoice_id"] is not None

        animal_state = validate_success(api.get_animal(animal["id"], cw), 200)
        assert animal_state["status"] == "ADOPTION_PENDING"

        # Pay fee
        invoice = validate_success(api.get_fee_invoice(app["fee_invoice_id"], cw), 200)
        assert_invoice_invariants(invoice)
        pay_invoice_fully(app["fee_invoice_id"])

        # Complete adoption
        app = complete_adoption(app["id"], cw)
        assert app["status"] == "COMPLETED"

        animal_final = validate_success(api.get_animal(animal["id"], cw), 200)
        assert animal_final["status"] == "ADOPTED"

        shelter_final = validate_success(api.get_shelter(shelter["id"], mgr), 200)
        assert shelter_final["adoption_count"] >= 1
        assert_shelter_invariants(shelter_final)

        adopter_final = validate_success(api.get_adopter(adopter["id"], cw), 200)
        assert adopter_final["adoption_history_count"] >= 1


class TestFullAdoptionLifecycleCat:
    """CAT adoption lifecycle: no home visit required."""

    def test_cat_adoption_skips_home_visit(self, api, caseworker_headers, manager_headers):
        """CAT adoption: SUBMITTED -> UNDER_REVIEW -> REVIEWED (no home visit) -> APPROVED -> COMPLETED."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])

        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = complete_application_review(app["id"])
        assert app["status"] == "REVIEWED"

        app = approve_application(app["id"])
        pay_invoice_fully(app["fee_invoice_id"])
        app = complete_adoption(app["id"])
        assert app["status"] == "COMPLETED"


class TestFullBoardingLifecycle:
    """Complete boarding lifecycle: reserve -> confirm -> check-in -> check-out."""

    def test_boarding_full_lifecycle(self, api, caseworker_headers, manager_headers):
        """Full boarding cycle with all side effects verified."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)

        shelter_before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        # Create reservation
        reservation = create_boarding_reservation(shelter["id"], animal["id"])
        assert reservation["status"] == "REQUESTED"

        # Confirm
        reservation = confirm_boarding(reservation["id"])
        assert reservation["status"] == "CONFIRMED"
        assert reservation["boarding_match_id"] is not None
        assert reservation["fee_invoice_id"] is not None

        # Check in
        reservation = check_in_boarding(reservation["id"])
        assert reservation["status"] == "CHECKED_IN"
        assert reservation["actual_check_in"] is not None

        animal_during = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_during["status"] == "BOARDING"

        shelter_during = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_during["current_boarding_count"] == shelter_before["current_boarding_count"] + 1

        # Check out
        reservation = check_out_boarding(reservation["id"])
        assert reservation["status"] == "CHECKED_OUT"
        assert reservation["actual_check_out"] is not None

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "AVAILABLE"

        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["current_boarding_count"] == shelter_before["current_boarding_count"]
        assert_shelter_invariants(shelter_after)


class TestComplianceHoldAndRecovery:
    """Integration: compliance hold blocks operations, resolution restores them."""

    def test_hold_blocks_make_available_then_recovery(self, api, caseworker_headers, manager_headers, vet_headers):
        """HIGH hold blocks make-available; resolving it allows the transition."""
        shelter = create_shelter()
        animal = create_animal_in_shelter(shelter["id"])
        vaccinate_animal(animal["id"], species="DOG")

        # Create HIGH hold
        hold = create_hold_on_animal(animal["id"], severity="HIGH")

        # Cannot make available
        res = api.make_animal_available(animal["id"], caseworker_headers)
        validate_error(res, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE)

        # Resolve hold
        resolve_hold(hold["id"])

        # Now can make available
        available = validate_success(
            api.make_animal_available(animal["id"], caseworker_headers), 200,
        )
        assert available["status"] == "AVAILABLE"


class TestRepeatAdopterLoyaltyDiscount:
    """Integration: repeat adopter (>= 2 adoptions) gets loyalty discount on third."""

    def test_loyalty_discount_applied_on_third_adoption(self, api, caseworker_headers, manager_headers):
        """Adopter with 2 completed adoptions gets loyalty discount on 3rd."""
        shelter = create_shelter_with_fee_schedules()
        adopter = create_repeat_adopter(shelter["id"], completed_adoptions=2, species="CAT")

        assert adopter["adoption_history_count"] >= 2

        # Third adoption should have loyalty discount
        animal = create_available_animal(shelter["id"], species="CAT")
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        assert invoice["discount_amount"] > 0, \
            "Loyalty discount should be applied for repeat adopter"
