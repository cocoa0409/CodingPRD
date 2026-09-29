"""Error coverage on two refusals that leave their target untouched: an execution
blocked by a lapsed workers compensation policy, and a revocation whose mandatory
reason is missing from the body.
"""

from test_helpers import (
    COORDINATOR,
    OFFICER,
    SIGNER,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    enrol_student_with_issued_permit,
    make_employer_supervisor_headers,
    read_agreement,
    read_permit,
    recruit_employer_partner,
    register_reviewed_worksite,
    register_supervisor,
    set_clock,
    validate_error,
    validate_success,
)

LARKSPUR_LANDSCAPING = {
    "legal_name": "Larkspur Landscaping",
    "naics_code": "561730",
    "industry_sector": "CONSTRUCTION",
    "workers_comp_policy_no": "WC-10211",
    "workers_comp_expires_on": "2026-08-31",
}

NOOR_HABIB = {
    "full_name": "Noor Habib",
    "birth_date": "2009-09-09",
    "grade_level": 11,
    "gpa": 3.30,
    "attendance_rate": 0.95,
    "student_learner_certificate": True,
}


class TestExecutionUnderALapsedPolicy:
    def test_a_policy_that_expired_last_week_blocks_execution(self):
        """The employer partner's `workers_comp_expires_on` must be on or after the clock
        date, and a lapsed policy is refused with `ERR_WORKERS_COMP_LAPSED`. On success the
        acting `X-User-ID` is written to `executed_by_user_id` and `executed_on` is set to the
        clock date.

        Design: Corner/errors/agreement_execute_with_lapsed_workers_comp_rejected
        """
        set_clock("2026-09-07T08:00:00Z")
        partner = recruit_employer_partner(**LARKSPUR_LANDSCAPING)
        worksite, _review = register_reviewed_worksite(
            partner["id"],
            site_name="Larkspur Yard",
            address_line="18 Larkspur Way",
            max_concurrent_students=2,
        )
        supervisor = register_supervisor(
            worksite["id"],
            full_name="Mira Osei",
            email="mira@larkspur.example",
            training_completed_on="2026-07-06",
            max_student_load=2,
        )
        agreement = validate_success(
            api_client.create_agreement(
                create_agreement_payload(
                    partner["id"], worksite["id"], supervisor["id"], insurance_rider=True
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.employer_sign_agreement(
                agreement["id"], {}, make_employer_supervisor_headers(supervisor["id"])
            )
        )

        response = api_client.execute_agreement(agreement["id"], {}, SIGNER)

        validate_error(response, ApiErrorId.ERR_WORKERS_COMP_LAPSED.value)
        assert response.status_code == 422

        stored = read_agreement(agreement["id"])
        assert stored["status"] == "PENDING_DISTRICT"
        assert stored["executed_on"] is None
        assert stored["executed_by_user_id"] is None


class TestRevocationWithoutAReason:
    def test_revoking_without_the_reason_field_leaves_the_permit_issued(self):
        """Revocation moves the permit `ISSUED → REVOKED` and stores the supplied
        `revoked_reason`. 8. Request body shape is valid — `ERR_INVALID_REQUEST` (400).

        Design: Corner/errors/work_permit_revoke_reason_missing_required_field_rejected
        """
        set_clock("2026-09-07T08:00:00Z")
        student, permit = enrol_student_with_issued_permit(
            permit_class="MINOR_16_17", hazardous_endorsement=True, **NOOR_HABIB
        )

        response = api_client.revoke_work_permit(permit["id"], {}, OFFICER)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400

        stored = read_permit(student["id"], permit["id"])
        assert stored["status"] == "ISSUED"
        assert stored["revoked_reason"] is None
