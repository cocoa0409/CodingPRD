"""Medical record review one-way door and injury-verification cross-entity gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_program, create_claimant, create_eligibility_passed_claim,
    create_medical_record_payload,
    create_injury_verified_claim,
)


class TestRecordReviewOneWayDoor:
    def test_reaccepting_accepted_record_rejected(self, api, records_analyst_headers):
        """PRD §3.3: "Either action against a record that has already left `PENDING_REVIEW` is rejected as `ERR_RECORD_ALREADY_REVIEWED` (HTTP 409), and either action while the claim is not in `RECORDS_PENDING` is `ERR_CLAIM_INVALID_STATE`."

        Design: Corner/errors/err_record_already_reviewed_triggerable
        """
        program = create_program(program_code="MT-RAR")
        claimant = create_claimant(program["id"], full_name="Quincy", ssn_last4="3434")
        claim = create_eligibility_passed_claim(program["id"], claimant["id"])
        record = validate_success(api.create_medical_record(
            program["id"], claim["id"],
            create_medical_record_payload(provider_name="X", record_type="DIAGNOSTIC",
                                          severity_score=70, confirms_qualifying_injury=True),
            records_analyst_headers,
        ), expected_status=201)
        validate_success(api.accept_medical_record(program["id"], claim["id"], record["id"], records_analyst_headers))
        resp = api.accept_medical_record(program["id"], claim["id"], record["id"], records_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_REVIEWED)

    def test_rerejecting_rejected_record_rejected(self, api, records_analyst_headers):
        """PRD §3.3: "Either action against a record that has already left `PENDING_REVIEW` is rejected as `ERR_RECORD_ALREADY_REVIEWED` (HTTP 409), and either action while the claim is not in `RECORDS_PENDING` is `ERR_CLAIM_INVALID_STATE`."

        Design: Corner/errors/err_record_already_reviewed_triggerable
        """
        program = create_program(program_code="MT-RAR2")
        claimant = create_claimant(program["id"], full_name="Quincy Two", ssn_last4="3435")
        claim = create_eligibility_passed_claim(program["id"], claimant["id"])
        record = validate_success(api.create_medical_record(
            program["id"], claim["id"],
            create_medical_record_payload(provider_name="X", record_type="TREATMENT",
                                          severity_score=40, confirms_qualifying_injury=False),
            records_analyst_headers,
        ), expected_status=201)
        validate_success(api.reject_medical_record(program["id"], claim["id"], record["id"], records_analyst_headers))
        resp = api.reject_medical_record(program["id"], claim["id"], record["id"], records_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_REVIEWED)


class TestVerifyInjuryDependsOnMedicalRecords:
    def test_verify_injury_with_one_accepted_one_pending_rejected(self, api, records_analyst_headers):
        """PRD §3.3: "the claim must have at least two medical records in `ACCEPTED` state, otherwise `ERR_INSUFFICIENT_MEDICAL_RECORDS` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/verify_injury_depends_on_medical_records
        """
        program = create_program(program_code="MT-X1")
        claimant = create_claimant(program["id"], full_name="Nina", ssn_last4="4545")
        claim = create_eligibility_passed_claim(program["id"], claimant["id"])
        pid, cid = program["id"], claim["id"]
        r1 = validate_success(api.create_medical_record(
            pid, cid, create_medical_record_payload(provider_name="X", record_type="DIAGNOSTIC",
                                                    severity_score=70, confirms_qualifying_injury=True),
            records_analyst_headers,
        ), expected_status=201)
        validate_success(api.accept_medical_record(pid, cid, r1["id"], records_analyst_headers))
        validate_success(api.create_medical_record(
            pid, cid, create_medical_record_payload(provider_name="Y", record_type="TREATMENT",
                                                    severity_score=65, confirms_qualifying_injury=False),
            records_analyst_headers,
        ), expected_status=201)
        resp = api.verify_injury(pid, cid, records_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MEDICAL_RECORDS)

    def test_verify_injury_succeeds_with_two_accepted_including_qualifying(self, api, records_analyst_headers):
        """PRD §3.3: "When the file is ready, the `RecordsAnalyst` verifies the injury, moving the claim from `RECORDS_PENDING` to `INJURY_VERIFIED` and setting `injury_verification_status` to `VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/verify_injury_depends_on_medical_records
        """
        program = create_program(program_code="MT-X1B")
        claimant = create_claimant(program["id"], full_name="Nina B", ssn_last4="4546")
        claim, _records = create_injury_verified_claim(program["id"], claimant["id"], severities=(70, 65))
        assert claim["status"] == "INJURY_VERIFIED", f"Expected INJURY_VERIFIED, got {claim['status']}"
        assert claim["injury_verification_status"] == "VERIFIED"
