"""Lab results: recording gates, referential checks, validation gates,
holding-time boundary, segregation of duties and the reject/resubmit cycle
(PRD §2.11, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_custody_to_analyzed,
    assert_lab_result,
    collect_sample,
    create_active_permit,
    create_analyzed_sample,
    create_custody_event_payload,
    create_lab_result_payload,
    make_field_sampler_headers,
    make_lab_analyst_headers,
    make_lab_validator_headers,
    record_lab_result,
    schedule_sample,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANY_HEADERS = TEST_USERS["regulator_headers"]  # reads are open to every role (PRD §2.1)

def _transfer_payload(event_at):
    return create_custody_event_payload(
        "TRANSFER", event_at, from_party="sampler", to_party="courier"
    )

def _receive_lab_payload(event_at):
    return create_custody_event_payload(
        "RECEIVE_LAB", event_at, from_party="courier", to_party="lab"
    )

def _sample_at_lab_received(api, permit_number):
    """Sample collected, TRANSFER-red, then RECEIVE_LAB — but not ANALYZED."""
    env = create_active_permit(permit_number=permit_number)
    sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-05T08:00:00Z")
    collect_sample(sample["id"], clock_iso="2026-08-05T09:00:00Z")
    # Custody appends create a new ChainOfCustodyRecord -> 201 (PRD §4).
    validate_success(api.append_custody_event(
        sample["id"], _transfer_payload("2026-08-05T09:10:00Z"),
        make_field_sampler_headers("sampler-1"),
    ), expected_status=201)
    validate_success(api.append_custody_event(
        sample["id"], _receive_lab_payload("2026-08-05T09:20:00Z"),
        make_lab_analyst_headers("analyst-1"),
    ), expected_status=201)
    return env, sample

class TestResultRecording:
    def test_lab_result_recorded_before_lab_receipt_rejected(self, api):
        """PRD §3.3: "Recording requires the sample's custody position to be
        `LAB_RECEIVED` or `ANALYZED` (`ERR_SAMPLE_NOT_IN_LAB`)"

        Design: Corner/validations/lab_result_recorded_before_lab_receipt_rejected
        """
        env = create_active_permit(permit_number="NPDES-VAL8")
        sample = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-05T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-05T09:00:00Z")
        validate_success(api.append_custody_event(
            sample["id"], _transfer_payload("2026-08-05T09:10:00Z"),
            make_field_sampler_headers("sampler-1"),
        ), expected_status=201)  # custody now IN_TRANSIT

        resp = api.create_lab_result(
            create_lab_result_payload(
                sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z"
            ),
            make_lab_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_IN_LAB)

    def test_lab_result_parameter_mismatch_rejected(self, api):
        """PRD §3.3: "the result's `parameter_code` must equal the sampling event's
        parameter (`ERR_PARAMETER_MISMATCH`)"

        Design: Corner/validations/lab_result_parameter_mismatch_rejected
        """
        env = create_active_permit(
            permit_number="NPDES-VAL6", parameter_code="COPPER", limit_value=1.0
        )
        sample = schedule_sample(env["outfall"]["id"], "COPPER", "2026-08-05T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-05T09:00:00Z")
        validate_success(api.append_custody_event(
            sample["id"], _transfer_payload("2026-08-05T09:10:00Z"),
            make_field_sampler_headers("sampler-1"),
        ), expected_status=201)
        validate_success(api.append_custody_event(
            sample["id"], _receive_lab_payload("2026-08-05T09:20:00Z"),
            make_lab_analyst_headers("analyst-1"),
        ), expected_status=201)

        resp = api.create_lab_result(
            create_lab_result_payload(
                sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z"
            ),
            make_lab_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PARAMETER_MISMATCH)

    def test_lab_result_unit_mismatch_rejected(self, api):
        """PRD §3.3: "its `unit` must equal the unit of the governing `ACTIVE`
        limit when one exists (`ERR_UNIT_MISMATCH`)"

        Design: Corner/validations/lab_result_unit_mismatch_rejected
        """
        env = create_active_permit(
            permit_number="NPDES-VAL7", parameter_code="COPPER", limit_value=1.0
        )
        sample = schedule_sample(env["outfall"]["id"], "COPPER", "2026-08-05T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-05T09:00:00Z")
        validate_success(api.append_custody_event(
            sample["id"], _transfer_payload("2026-08-05T09:10:00Z"),
            make_field_sampler_headers("sampler-1"),
        ), expected_status=201)
        validate_success(api.append_custody_event(
            sample["id"], _receive_lab_payload("2026-08-05T09:20:00Z"),
            make_lab_analyst_headers("analyst-1"),
        ), expected_status=201)

        resp = api.create_lab_result(
            create_lab_result_payload(
                sample["id"], "COPPER", 7.0, "2026-08-05T09:45:00Z", unit="SU"
            ),
            make_lab_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_MISMATCH)

    def test_get_lab_result_not_found(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_RESULT_NOT_FOUND` ..."

        Design: Corner/entities/get_lab_result_not_found
        """
        resp = api.get_lab_result(NON_EXISTENT_UUID, ANY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_RESULT_NOT_FOUND)

class TestResultValidationGates:
    def test_error_custody_not_analyzed_on_validate(self, api):
        """PRD §3.3: "the sample's custody must have reached `ANALYZED`
        (`ERR_CUSTODY_NOT_ANALYZED`)"

        Design: Corner/errors/error_custody_not_analyzed_on_validate
        """
        env, sample = _sample_at_lab_received(api, permit_number="NPDES-ERR1")
        result = record_lab_result(
            sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z"
        )
        resp = api.validate_lab_result(result["id"], make_lab_validator_headers("validator-1"))
        validate_error(resp, ApiErrorId.ERR_CUSTODY_NOT_ANALYZED)

    def test_error_result_not_submitted_on_double_validate(self, api):
        """PRD §3.3: "the result must be `SUBMITTED` (`ERR_RESULT_NOT_SUBMITTED`)"

        Design: Corner/errors/error_result_not_submitted_on_double_validate
        """
        env = create_active_permit(permit_number="NPDES-ERR2")
        sample = create_analyzed_sample(env["outfall"]["id"], "TSS")
        result = record_lab_result(sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z")
        set_clock("2026-08-05T10:00:00Z")
        validate_success(
            api.validate_lab_result(result["id"], make_lab_validator_headers("validator-1"))
        )

        resp = api.validate_lab_result(result["id"], make_lab_validator_headers("validator-2"))
        validate_error(resp, ApiErrorId.ERR_RESULT_NOT_SUBMITTED)

    def test_error_result_not_rejected_on_resubmit_of_submitted(self, api):
        """PRD §3.3: "A `LabAnalyst` may resubmit a `REJECTED` result
        (`ERR_RESULT_NOT_REJECTED`)"

        Design: Corner/errors/error_result_not_rejected_on_resubmit_of_submitted
        """
        env = create_active_permit(permit_number="NPDES-ERR3")
        sample = create_analyzed_sample(env["outfall"]["id"], "TSS")
        result = record_lab_result(sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z")

        resp = api.resubmit_lab_result(
            result["id"], {"reported_value": 1.1}, make_lab_analyst_headers("analyst-1")
        )
        validate_error(resp, ApiErrorId.ERR_RESULT_NOT_REJECTED)

    def test_custody_holding_time_inclusive_boundary(self, api):
        """PRD §3.3: "it must not exceed the parameter's allowance: 2 hours for `PH`,
        8 hours for `FECAL_COLIFORM`, 48 hours for `BOD5`, 168 hours (seven days) for
        `TSS`, 672 hours (twenty-eight days) for `AMMONIA_N`, and 4320 hours (one
        hundred eighty days) for `COPPER`. An analysis landing exactly at its allowance
        is valid; anything beyond it is rejected with `ERR_HOLDING_TIME_EXCEEDED`
        (HTTP 422)."

        Design: Corner/calculations/custody_holding_time_inclusive_boundary
        """
        env = create_active_permit(
            permit_number="NPDES-CALC8", parameter_code="BOD5", limit_value=5.0
        )
        # Both samples collected at the same instant; result A analyzed exactly
        # 48h later (valid), result B one hour beyond (rejected).
        sample_a = schedule_sample(env["outfall"]["id"], "BOD5", "2026-08-05T08:00:00Z")
        sample_b = schedule_sample(env["outfall"]["id"], "BOD5", "2026-08-05T08:30:00Z")
        set_clock("2026-08-05T09:00:00Z")
        collect_sample(sample_a["id"])
        collect_sample(sample_b["id"])
        advance_custody_to_analyzed(sample_a["id"], "2026-08-05T09:00:00Z")
        advance_custody_to_analyzed(sample_b["id"], "2026-08-05T09:00:00Z")
        result_a = record_lab_result(
            sample_a["id"], "BOD5", 1.0, "2026-08-07T09:00:00Z"  # exactly 48h
        )
        result_b = record_lab_result(
            sample_b["id"], "BOD5", 1.0, "2026-08-07T10:00:00Z"  # 49h
        )
        set_clock("2026-08-07T10:00:01Z")

        validated = validate_success(
            api.validate_lab_result(result_a["id"], make_lab_validator_headers("validator-1"))
        )
        assert_lab_result(validated)
        assert validated["validation_status"] == "VALIDATED", (
            "elapsed == 48h allowance is valid (inclusive boundary)"
        )
        resp = api.validate_lab_result(result_b["id"], make_lab_validator_headers("validator-1"))
        validate_error(resp, ApiErrorId.ERR_HOLDING_TIME_EXCEEDED)

class TestSegregationAndRejectResubmit:
    def test_sod_lab_result_validator_must_differ_from_analyst(self, api):
        """PRD §2.11: "A lab result may not be validated or rejected by the analyst
        who recorded (or last resubmitted) it — the validator's identifier must
        differ from `analyzed_by_user_id`."

        Design: Corner/rbac/sod_lab_result_validator_must_differ_from_analyst
        """
        env = create_active_permit(permit_number="NPDES-RBAC5")
        sample = create_analyzed_sample(env["outfall"]["id"], "TSS")
        result = record_lab_result(
            sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z", analyst_id="analyst-1"
        )
        set_clock("2026-08-05T10:00:00Z")

        resp = api.validate_lab_result(
            result["id"], make_lab_validator_headers("analyst-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_rbac_lab_analyst_cannot_validate_result(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target operation
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST `/npdes/lab-results/{id}/validate` ... | LabValidator |".

        Design: Corner/rbac/rbac_lab_analyst_cannot_validate_result
        """
        env = create_active_permit(permit_number="NPDES-RBAC3")
        sample = create_analyzed_sample(env["outfall"]["id"], "TSS")
        result = record_lab_result(
            sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z", analyst_id="analyst-1"
        )
        # A different operator id but the wrong role for this endpoint.
        resp = api.validate_lab_result(result["id"], make_lab_analyst_headers("analyst-2"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_lab_result_reject_and_resubmit_cycle(self, api):
        """PRD §3.3: "the validator supplies a `reason` which is recorded as
        `rejection_reason`, and the result moves `SUBMITTED → REJECTED` with a
        `RESULT_REJECTED` audit entry."
        PRD §3.3: "Resubmission returns the result to `SUBMITTED`, replaces
        `analyzed_by_user_id` with the resubmitting caller — so the segregation rule
        is evaluated against the new analyst on the next validation — clears
        `rejection_reason` to null, increments the `version` and appends
        `RESULT_RESUBMITTED`."

        Design: Corner/state_machines/lab_result_reject_and_resubmit_cycle
        """
        env = create_active_permit(permit_number="NPDES-SM18")
        sample = create_analyzed_sample(env["outfall"]["id"], "TSS")
        result = record_lab_result(
            sample["id"], "TSS", 1.0, "2026-08-05T09:45:00Z", analyst_id="analyst-1"
        )

        rejected = validate_success(api.reject_lab_result(
            result["id"], {"reason": "matrix spike failure"},
            make_lab_validator_headers("validator-1"),
        ))
        assert rejected["validation_status"] == "REJECTED"
        assert rejected["rejection_reason"] == "matrix spike failure"

        resubmitted = validate_success(api.resubmit_lab_result(
            result["id"], {"reported_value": 1.1}, make_lab_analyst_headers("analyst-2")
        ))
        assert resubmitted["validation_status"] == "SUBMITTED"
        assert resubmitted["rejection_reason"] is None
        assert resubmitted["analyzed_by_user_id"] == "analyst-2", (
            "the resubmitting caller becomes the analyst of record"
        )
        assert resubmitted["reported_value"] == 1.1
