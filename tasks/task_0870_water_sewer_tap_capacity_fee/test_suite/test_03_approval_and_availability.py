"""Approval preconditions, availability determination, and the service-availability guard."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_application, ensure_meter_schedule, submit_application, start_review,
    application_under_review, application_with_availability, setup_executed_agreement,
    create_availability_payload,
    make_applicant_headers, make_reviewer_headers,
)


def test_submit_unknown_meter_size_rejected(api):
    """PRD §3.2: "Submission requires that `parcel_id`, `service_type`, `meter_size`, and
    `use_type` all be present and that the `meter_size` match an existing meter-size schedule
    row (otherwise `ERR_METER_SIZE_UNKNOWN`)."

    Design: Corner/validations/submit_unknown_meter_size_rejected
    """
    # A schedule exists for ONE, but the application requests TWO (no row).
    ensure_meter_schedule(meter_size="ONE")
    app = create_application(parcel_id="APN-U", service_type="WATER",
                             meter_size="TWO", use_type="RESIDENTIAL")
    res = api.submit_application(app["id"], make_applicant_headers("appl-1"))
    validate_error(res, ApiErrorId.ERR_METER_SIZE_UNKNOWN.value, expected_status=422)


def test_approve_without_determination_rejected(api):
    """PRD §3.4: "Next, an availability determination must exist for the application, or
    approval fails with `ERR_DETERMINATION_MISSING` (HTTP 422)."

    Design: Corner/validations/approve_without_determination_rejected
    """
    app = application_under_review(parcel_id="APN-ND", meter_size="ONE", with_fee=True)
    res = api.approve_application(app["id"], make_reviewer_headers("rev-2"))
    validate_error(res, ApiErrorId.ERR_DETERMINATION_MISSING.value, expected_status=422)


class TestApproveRequiresServiceAvailable:
    """Approval depends on AvailabilityDetermination / DeveloperAgreement state."""

    def test_unavailable_without_agreement_rejected(self, api):
        """PRD §3.4: "Finally, service must actually be available: for every requested utility
        the corresponding availability boolean must be true, unless a developer agreement in
        `EXECUTED`, `COMPLETION_PENDING`, or `CLOSED` state covers a main-extension project for
        this application. If neither condition holds, approval is rejected with
        `ERR_SERVICE_UNAVAILABLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_available_or_executed_agreement
        """
        app, _ = application_with_availability(distance_to_main_ft=300,
                                               availability_reviewer_id="rev-1",
                                               parcel_id="APN-L", service_type="WATER",
                                               meter_size="ONE")
        res = api.approve_application(app["id"], make_reviewer_headers("rev-2"))
        validate_error(res, ApiErrorId.ERR_SERVICE_UNAVAILABLE.value, expected_status=422)

    def test_executed_agreement_unblocks_approval(self, api):
        """PRD §3.4: "Finally, service must actually be available: for every requested utility
        the corresponding availability boolean must be true, unless a developer agreement in
        `EXECUTED`, `COMPLETION_PENDING`, or `CLOSED` state covers a main-extension project for
        this application."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_available_or_executed_agreement
        """
        app, _ = application_with_availability(distance_to_main_ft=300,
                                               availability_reviewer_id="rev-1",
                                               parcel_id="APN-L2", service_type="WATER",
                                               meter_size="ONE")
        # An EXECUTED developer agreement now covers a project for this application.
        setup_executed_agreement(application_id=app["id"], estimated_cost_cents=3000000,
                                 reimbursement_cap_cents=4000000,
                                 total_assessable_front_ft=300, total_assessable_area_sqft=60000,
                                 length_ft=300)
        approved = validate_success(
            api.approve_application(app["id"], make_reviewer_headers("rev-2")), 200)
        assert approved["status"] == "APPROVED"


class TestAvailabilityDistanceBoundary:
    """MAX_CONNECTION_DISTANCE_FT is 200; exactly 200 is available (<=, not <)."""

    def test_distance_at_boundary_is_available(self, api):
        """PRD §3.3: "`water_main_available` is true when water is needed and
        `distance_to_main_ft` is at most the maximum connection distance of 200 feet ... A
        distance of exactly 200 feet counts as available. `extension_required` is true when a
        needed water main is unavailable or a needed sewer main is unavailable."

        Design: Difficulty/boundary_precision_check/availability_distance_exact_boundary
        """
        app = create_application(parcel_id="APN-J1", service_type="WATER",
                                 meter_size="ONE", use_type="RESIDENTIAL")
        det = validate_success(api.create_availability_determination(
            create_availability_payload(app["id"], 200), make_reviewer_headers("rev-1")), 201)
        assert det["water_main_available"] is True
        assert det["extension_required"] is False

    def test_distance_over_boundary_is_unavailable(self, api):
        """PRD §3.3: "`water_main_available` is true when water is needed and
        `distance_to_main_ft` is at most the maximum connection distance of 200 feet ... A
        distance of exactly 200 feet counts as available. `extension_required` is true when a
        needed water main is unavailable or a needed sewer main is unavailable."

        Design: Difficulty/boundary_precision_check/availability_distance_exact_boundary
        """
        app = create_application(parcel_id="APN-J2", service_type="WATER",
                                 meter_size="ONE", use_type="RESIDENTIAL")
        det = validate_success(api.create_availability_determination(
            create_availability_payload(app["id"], 201), make_reviewer_headers("rev-1")), 201)
        assert det["water_main_available"] is False
        assert det["extension_required"] is True
