"""Supplier registration, FSVP evaluation lifecycle, risk scoring, and the
re-evaluation clock sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_supplier,
    assert_supplier_evaluation,
    create_approved_supplier,
    create_supplier,
    create_supplier_evaluation_payload,
    create_supplier_payload,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_success,
)

CM = TEST_USERS["compliance_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

EVAL_START = "2024-01-01T00:00:00Z"
EVAL_END = "2024-12-31T00:00:00Z"


class TestSupplierCreation:
    def test_supplier_creation_defaults_and_envelope(self, api):
        """PRD: "Upon creation, the supplier enters `PENDING_EVALUATION` status,
        its `risk_score` and `risk_tier` are null, `open_corrective_action_count`
        and lifetime counters (`total_species_mismatches`,
        `total_haccp_deviations`) are zeroed, and `last_evaluation_period_end`
        and `next_evaluation_due` are null. The `version` starts at 1."
        PRD: "Optionally, the registration indicates whether the supplier
        `handles_histamine_susceptible_species` — a boolean defaulting to
        `false`."

        Design: Corner/entities/supplier_creation_defaults_and_envelope
        """
        resp = api.create_supplier(
            create_supplier_payload(
                legal_name="Pacific Harvest Ltd", country_code="JP",
                facility_registration_number="FRN-C01"),
            CM,
        )
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"].get("api_request_id"), str)
        supplier = validate_success(resp, 201)
        assert_supplier(supplier)
        assert supplier["fsvp_status"] == "PENDING_EVALUATION"
        assert supplier["risk_score"] is None
        assert supplier["risk_tier"] is None
        assert supplier["open_corrective_action_count"] == 0
        assert supplier["total_species_mismatches"] == 0
        assert supplier["total_haccp_deviations"] == 0
        assert supplier["next_evaluation_due"] is None
        assert supplier["version"] == 1
        assert is_valid_uuid(supplier["id"])
        # Omitted optional boolean defaults to false.
        assert supplier["handles_histamine_susceptible_species"] is False

    def test_supplier_missing_required_field_rejected(self, api):
        """PRD: "A `ComplianceManager` registers a new foreign supplier by
        providing `legal_name`, `country_code` (ISO 3166-1 alpha-2), and
        `facility_registration_number`." A missing required field is a
        field-level validation failure: ERR_VALIDATION_FAILED (HTTP 400).

        Design: Corner/entities/supplier_missing_required_field_rejected
        """
        resp = api.create_supplier(
            {"country_code": "JP", "facility_registration_number": "FRN-C02"},
            CM,
        )
        err = validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)
        assert isinstance(err["message"], str) and err["message"].strip()


class TestEvaluationOutcomeBoundaries:
    def test_evaluation_outcome_tier_boundary(self, api):
        """PRD: "The `outcome` is derived from the overall score: 70 or above
        yields `APPROVED`, 50 or above (but below 70) yields `CONDITIONAL`, and
        below 50 yields `REJECTED`."
        PRD: "A `CONDITIONAL` outcome (score 50 to below 70) leaves the supplier
        in `PENDING_EVALUATION` — conditional does not approve a never-approved
        supplier."

        Design: Corner/calculations/evaluation_outcome_tier_boundary
        """
        supplier = create_supplier(name="Boundary Foods", country="PE",
                                   frn="FRN-CAL1")
        # 69.99 across the board -> overall 69.99 -> CONDITIONAL, no approval.
        ev1 = validate_success(api.create_supplier_evaluation(
            create_supplier_evaluation_payload(
                supplier_id=supplier["id"],
                expected_supplier_version=supplier["version"],
                period_start=EVAL_START, period_end=EVAL_END,
                hazard_analysis_score=69.99, record_review_score=69.99,
                performance_score=69.99),
            CM), 201)
        assert_supplier_evaluation(ev1)
        assert ev1["overall_score"] == pytest.approx(69.99, abs=0.005)
        assert ev1["outcome"] == "CONDITIONAL"
        after1 = validate_success(api.get_supplier(supplier["id"], CM))
        assert after1["fsvp_status"] == "PENDING_EVALUATION"

        # Exactly 70.00 -> APPROVED (boundary inclusive).
        ev2 = validate_success(api.create_supplier_evaluation(
            create_supplier_evaluation_payload(
                supplier_id=supplier["id"],
                expected_supplier_version=after1["version"],
                period_start="2025-01-01T00:00:00Z",
                period_end="2025-12-31T00:00:00Z",
                hazard_analysis_score=70, record_review_score=70,
                performance_score=70),
            CM), 201)
        assert ev2["overall_score"] == pytest.approx(70.00, abs=0.005)
        assert ev2["outcome"] == "APPROVED"
        after2 = validate_success(api.get_supplier(supplier["id"], CM))
        assert after2["fsvp_status"] == "APPROVED"


class TestSupplierReevaluationCycle:
    def test_clock_sweep_demotes_overdue_supplier(self, api):
        """PRD: "Any `APPROVED` supplier whose `next_evaluation_due` is not null
        and is less than or equal to the current logical time transitions to
        `REEVALUATION_DUE`, incrementing the supplier version."
        PRD: "The `next_evaluation_due` is set to the evaluation's `period_end`
        plus this interval." (LOW tier: 36 months)

        Design: Difficulty/non_linear_state_machine/supplier_reevaluation_cycle
        """
        supplier = create_approved_supplier(
            name="Andes Seafood", country="CL", frn="FRN-4001")
        # overall 90 -> eval component 10 -> risk 4.00 -> LOW; due 2027-12-31.
        assert supplier["risk_score"] == pytest.approx(4.00, abs=0.005)
        assert supplier["risk_tier"] == "LOW"
        assert supplier["next_evaluation_due"] == "2027-12-31T00:00:00Z"

        # Sweep past the due date.
        validate_success(api.set_clock("2028-01-01T00:00:00Z", ADMIN))
        demoted = validate_success(api.get_supplier(supplier["id"], CM))
        assert demoted["fsvp_status"] == "REEVALUATION_DUE"

    def test_passing_evaluation_restores_approved_supplier(self, api):
        """PRD: "From `REEVALUATION_DUE`, an `APPROVED` or `CONDITIONAL` outcome
        restores the supplier to `APPROVED` with updated evaluation dates and
        risk fields."
        PRD: "The `risk_score` is 40% of the evaluation component plus 30% of
        the open penalty plus 30% of the history penalty, rounded half-up to 2
        decimal places."

        Design: Difficulty/non_linear_state_machine/supplier_reevaluation_cycle
        """
        supplier = create_approved_supplier(
            name="Andes Seafood", country="CL", frn="FRN-4001")
        validate_success(api.set_clock("2028-01-01T00:00:00Z", ADMIN))
        demoted = validate_success(api.get_supplier(supplier["id"], CM))
        assert demoted["fsvp_status"] == "REEVALUATION_DUE"

        # Fresh passing evaluation (non-overlapping period) re-approves.
        ev = validate_success(api.create_supplier_evaluation(
            create_supplier_evaluation_payload(
                supplier_id=supplier["id"],
                expected_supplier_version=demoted["version"],
                period_start="2027-01-01T00:00:00Z",
                period_end="2027-12-31T00:00:00Z",
                hazard_analysis_score=80, record_review_score=80,
                performance_score=80),
            CM), 201)
        assert ev["outcome"] == "APPROVED"
        restored = validate_success(api.get_supplier(supplier["id"], CM))
        assert restored["fsvp_status"] == "APPROVED"
        # risk = 0.4*(100-80) + 0.3*0 + 0.3*0 = 8.00 -> LOW (36 months).
        assert restored["risk_score"] == pytest.approx(8.00, abs=0.005)
        assert restored["risk_tier"] == "LOW"
        assert restored["next_evaluation_due"] == "2030-12-31T00:00:00Z"


class TestEvaluationPeriodOverlap:
    def test_shared_boundary_day_is_overlap(self, api):
        """PRD: "Evaluation periods for the same supplier must not overlap.
        Because coverage windows are closed intervals, a new evaluation whose
        period intersects any existing evaluation's period — including sharing
        a boundary day — is rejected with `ERR_EVALUATION_PERIOD_OVERLAP`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/evaluation_period_shared_day_overlap
        """
        supplier = create_approved_supplier(
            name="Andes Seafood", country="CL", frn="FRN-9002")
        current = validate_success(api.get_supplier(supplier["id"], CM))

        # New period starting on the existing period's final day overlaps.
        resp = api.create_supplier_evaluation(
            create_supplier_evaluation_payload(
                supplier_id=supplier["id"],
                expected_supplier_version=current["version"],
                period_start="2024-12-31T00:00:00Z",
                period_end="2025-12-31T00:00:00Z",
                hazard_analysis_score=80, record_review_score=80,
                performance_score=80),
            CM)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_PERIOD_OVERLAP)

    def test_next_day_start_is_accepted_and_failed_attempt_keeps_version(self, api):
        """PRD: "Evaluation periods for the same supplier must not overlap."
        Starting the day after the existing period ends is not an intersection
        and is accepted.
        PRD: "**`version`** (integer): A system-managed integer that increments
        with every modification to the resource." A rejected request is not a
        modification, so the supplier version is unchanged and the same OCC
        value remains valid for the retry.

        Design: Difficulty/resource_temporal_overlap/evaluation_period_shared_day_overlap
        """
        supplier = create_approved_supplier(
            name="Andes Seafood", country="CL", frn="FRN-9002")
        current = validate_success(api.get_supplier(supplier["id"], CM))
        observed_version = current["version"]

        # Rejected overlap attempt.
        validate_error(
            api.create_supplier_evaluation(
                create_supplier_evaluation_payload(
                    supplier_id=supplier["id"],
                    expected_supplier_version=observed_version,
                    period_start="2024-12-31T00:00:00Z",
                    period_end="2025-12-31T00:00:00Z",
                    hazard_analysis_score=80, record_review_score=80,
                    performance_score=80),
                CM),
            ApiErrorId.ERR_EVALUATION_PERIOD_OVERLAP)

        # The same OCC version still works for the non-overlapping retry.
        ev = validate_success(api.create_supplier_evaluation(
            create_supplier_evaluation_payload(
                supplier_id=supplier["id"],
                expected_supplier_version=observed_version,
                period_start="2025-01-01T00:00:00Z",
                period_end="2025-12-31T00:00:00Z",
                hazard_analysis_score=80, record_review_score=80,
                performance_score=80),
            CM), 201)
        assert ev["outcome"] == "APPROVED"
        assert ev["overall_score"] == pytest.approx(80.00, abs=0.005)

        after = validate_success(api.get_supplier(supplier["id"], CM))
        assert after["fsvp_status"] == "APPROVED"
        assert after["next_evaluation_due"] == "2028-12-31T00:00:00Z"
