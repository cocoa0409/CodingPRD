"""
Tests for cascading side effects and derived field reconciliation.
Claims from Table 2 side_effects, PRD sections 2.10, 3.7.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    assert_shelter_invariants,
    assert_invoice_invariants,
    assert_cost_precision,
    create_shelter,
    create_shelter_with_fee_schedules,
    create_available_animal,
    create_adopter_in_shelter,
    application_to_reviewed,
    approve_application,
    complete_adoption,
    pay_invoice_fully,
    create_boarding_reservation,
    confirm_boarding,
    check_in_boarding,
    check_out_boarding,
    setup_boarding_through_check_in,
    full_adoption_lifecycle,
    create_hold_on_animal,
    resolve_hold,
    create_payment_payload,
    ApiErrorId,
    TEST_USERS,
    DEFAULT_TAX_RATE,
)


class TestAdoptionApprovalCascade:
    """Approval cascades: animal -> ADOPTION_PENDING, invoice created."""

    def test_approval_creates_invoice_and_changes_animal(self, api, caseworker_headers, manager_headers):
        """
        Approve application -> animal ADOPTION_PENDING, fee_invoice created + linked.
        """
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        assert app["status"] == "APPROVED"
        assert app["fee_invoice_id"] is not None

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "ADOPTION_PENDING"
        assert animal_after["adoption_eligible"] is False

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        assert invoice["reference_type"] == "ADOPTION"
        assert invoice["reference_id"] == app["id"]
        assert_invoice_invariants(invoice)


class TestAdoptionCompletionCascade:
    """Completion cascades: animal ADOPTED, counters incremented."""

    def test_completion_updates_shelter_and_adopter_counts(self, api, caseworker_headers, manager_headers):
        """Complete adoption -> adoption_count++, adoption_history_count++."""
        shelter = create_shelter_with_fee_schedules()
        shelter_before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        adopter_before_count = adopter["adoption_history_count"]

        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])
        pay_invoice_fully(app["fee_invoice_id"])
        complete_adoption(app["id"])

        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["adoption_count"] == shelter_before["adoption_count"] + 1

        adopter_after = validate_success(api.get_adopter(adopter["id"], caseworker_headers), 200)
        assert adopter_after["adoption_history_count"] == adopter_before_count + 1

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "ADOPTED"


class TestBoardingConfirmationCascade:
    """Confirmation cascades: BoardingMatch created, invoice created."""

    def test_confirmation_creates_match_and_invoice(self, api, manager_headers, caseworker_headers):
        """Confirm reservation -> boarding_match_id set, fee_invoice_id set."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)
        reservation = create_boarding_reservation(shelter["id"], animal["id"])
        confirmed = confirm_boarding(reservation["id"])

        assert confirmed["boarding_match_id"] is not None
        assert confirmed["fee_invoice_id"] is not None

        invoice = validate_success(
            api.get_fee_invoice(confirmed["fee_invoice_id"], caseworker_headers), 200,
        )
        assert invoice["reference_type"] == "BOARDING"
        assert invoice["reference_id"] == confirmed["id"]


class TestBoardingCheckInCascade:
    """Check-in cascades: boarding_count++, animal -> BOARDING."""

    def test_check_in_increments_boarding_count(self, api, caseworker_headers, manager_headers):
        """Check in -> shelter.current_boarding_count incremented."""
        shelter = create_shelter_with_fee_schedules()
        shelter_before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        animal = create_available_animal(shelter["id"], include_bordetella=True)
        reservation = create_boarding_reservation(shelter["id"], animal["id"])
        confirm_boarding(reservation["id"])
        check_in_boarding(reservation["id"])

        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["current_boarding_count"] == shelter_before["current_boarding_count"] + 1
        assert_shelter_invariants(shelter_after)


class TestBoardingCheckOutCascade:
    """Check-out cascades: boarding_count--, animal -> AVAILABLE, invoice adjusted."""

    def test_check_out_decrements_boarding_count(self, api, caseworker_headers, manager_headers):
        """Check out -> shelter.current_boarding_count decremented."""
        reservation, animal, shelter = setup_boarding_through_check_in()
        shelter_before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        check_out_boarding(reservation["id"])

        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["current_boarding_count"] == shelter_before["current_boarding_count"] - 1
        assert_shelter_invariants(shelter_after)


class TestRevenueBalanceReconciliation:
    """Derived field: shelter.revenue_balance tracks payments minus refunds."""

    def test_revenue_balance_after_payment(self, api, caseworker_headers, manager_headers):
        """Payment increases revenue_balance."""
        shelter = create_shelter_with_fee_schedules()
        shelter_initial = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        api.pay_invoice(
            invoice["id"],
            create_payment_payload(invoice["total_amount"]),
            caseworker_headers,
        )

        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["revenue_balance"] == pytest.approx(
            shelter_initial["revenue_balance"] + invoice["total_amount"], abs=0.01,
        )
        assert_cost_precision(shelter_after["revenue_balance"])

    def test_revenue_balance_after_refund(self, api, caseworker_headers, manager_headers):
        """Refund decreases revenue_balance."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])
        pay_invoice_fully(app["fee_invoice_id"])

        shelter_before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        api.refund_invoice(app["fee_invoice_id"], manager_headers)
        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        assert shelter_after["revenue_balance"] < shelter_before["revenue_balance"]
        assert_cost_precision(shelter_after["revenue_balance"])


class TestComplianceHoldCascade:
    """Hold creation/resolution cascades on animal status and compliance_score."""

    def test_hold_creation_updates_compliance_score(self, api, manager_headers):
        """Creating a hold -> shelter.compliance_score decreases."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])

        before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        create_hold_on_animal(animal["id"], severity="LOW")
        after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        assert after["compliance_score"] < before["compliance_score"]

    def test_hold_resolution_restores_compliance_score(self, api, manager_headers):
        """Resolving a hold -> shelter.compliance_score increases."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold = create_hold_on_animal(animal["id"], severity="LOW")

        before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        resolve_hold(hold["id"])
        after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        assert after["compliance_score"] > before["compliance_score"]


class TestVersionIncrementOnCascade:
    """PRD 2.10: Cascading mutations increment affected resource's version."""

    def test_animal_version_incremented_on_approval(self, api, caseworker_headers, manager_headers):
        """Approving application -> animal.version incremented (status changed)."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")

        animal_before = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        approve_application(app["id"])
        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)

        assert animal_after["version"] > animal_before["version"]
        assert animal_after["status"] == "ADOPTION_PENDING"
