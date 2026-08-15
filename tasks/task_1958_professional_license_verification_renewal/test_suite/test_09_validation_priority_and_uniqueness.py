"""Validation-cascade priority pairs, uniqueness rules, and policy endpoints."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_active_license,
    create_disciplinary_event,
    create_employee,
    create_license_type,
    create_license_type_payload,
    create_role_requirement,
    create_submitted_request,
    confirm_disciplinary_event,
    make_officer_headers,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER1 = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")


class TestValidationPriorityPairs:
    def _suspended_license_with_submitted_request(self, api, email,
                                                  license_number):
        from test_helpers import create_employee, create_license_type
        lt = create_license_type()
        emp = create_employee(work_email=email)
        lic = create_active_license(emp["id"], lt["id"],
                                    license_number=license_number)
        rr = create_submitted_request(lic["id"], 50_000, submitter_headers=OFFICER1)
        event = create_disciplinary_event(
            lic["id"], headers=OFFICER1, board_case_number="B-9",
            event_type="SUSPENSION", effective_on="2026-08-01",
            received_via="MANUAL")
        confirm_disciplinary_event(event["id"], headers=OFFICER2)
        return lt, emp, lic, rr

    def test_submit_invalid_state_beats_suspension_safety(self, api):
        """PRD §2.8: "the first failing check determines the error returned —
        earlier failures mask later ones", with "**State-machine from-state**"
        at step 6 ahead of "**Safety gates** — renewal submission while the
        license is `SUSPENDED` (`ERR_LICENSE_SUSPENDED`)" at step 7.

        Design: Difficulty/priority_pair_validation_conflict/submit_invalid_state_beats_suspension_safety
        """
        lt, emp, lic, rr = self._suspended_license_with_submitted_request(
            api, "nora.prio@example.com", "RN-8101")
        # The request is already SUBMITTED: the state gate fails first even
        # though the license is SUSPENDED.
        resp = api.submit_renewal_request(rr["id"], OFFICER1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_resubmit_from_more_info_hits_suspension_gate(self, api):
        """PRD §2.8: "**State-machine from-state** — the target resource sits in
        a from-state of the requested transition: a request not in `DRAFT` or
        `MORE_INFO` cannot be submitted" (step 6); "**Safety gates** — renewal
        submission while the license is `SUSPENDED` (`ERR_LICENSE_SUSPENDED`)"
        (step 7).

        Design: Difficulty/priority_pair_validation_conflict/submit_invalid_state_beats_suspension_safety
        """
        lt, emp, lic, rr = self._suspended_license_with_submitted_request(
            api, "nora.prio2@example.com", "RN-8102")
        # MORE_INFO is a valid from-state, so the state gate passes and the
        # suspension gate fires.
        validate_success(api.request_info_renewal_request(
            rr["id"], "Need updated receipt", OFFICER2), 200)
        resp = api.submit_renewal_request(rr["id"], OFFICER1)
        validate_error(resp, ApiErrorId.ERR_LICENSE_SUSPENDED, 403)

    def test_body_fk_not_found_beats_field_domain_validation(self, api):
        """PRD §2.6: "Referenced-resource existence is always checked before
        field-domain validation, so a request with both a dangling foreign key
        and a malformed field surfaces the not-found error."

        Design: Difficulty/priority_pair_validation_conflict/body_fk_not_found_beats_field_domain_validation
        """
        lt = create_license_type()
        payload = {
            "employee_id": NON_EXISTENT_UUID,
            "license_type_id": lt["id"],
            "state_code": "CA",
            # license_number deliberately omitted: a p5 field-domain defect.
            "issued_on": "2026-01-01",
            "expires_on": "2027-01-01",
        }
        resp = api.create_license(payload, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_body_fk_license_type_not_found_beats_field_domain(self, api):
        """PRD §2.6: "The same error covers body foreign keys on creation
        payloads: an `employee_id`, `license_type_id`, or `license_id` that
        references a non-existent resource fails with `ERR_NOT_FOUND`.
        Referenced-resource existence is always checked before field-domain
        validation".

        Design: Difficulty/priority_pair_validation_conflict/body_fk_not_found_beats_field_domain_validation
        """
        emp = create_employee(work_email="nora.fkprio@example.com")
        payload = {
            "employee_id": emp["id"],
            "license_type_id": NON_EXISTENT_UUID,
            "state_code": "CA",
            # license_number deliberately omitted.
            "issued_on": "2026-01-01",
            "expires_on": "2027-01-01",
        }
        resp = api.create_license(payload, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestPolicyUniqueness:
    def test_duplicate_role_requirement_rejected(self, api):
        """PRD §3.1: "The triple of role, type, and state is unique per matrix;
        a conflicting insert fails with `ERR_DUPLICATE_ROLE_REQUIREMENT`."

        Design: Corner/validations/duplicate_role_requirement_rejected
        """
        lt = create_license_type()
        create_role_requirement(lt["id"], role_code="STAFF_NURSE",
                                state_code="CA", is_required=True)
        resp = api.create_role_requirement(
            {"role_code": "STAFF_NURSE", "license_type_id": lt["id"],
             "state_code": "CA", "is_required": False}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROLE_REQUIREMENT, 409)

    def test_duplicate_license_type_code_rejected(self, api):
        """PRD §3.1: "A `ComplianceAdmin` registers each credential family the
        company tracks — an RN, a PE, a CPA — under a unique program `code` and
        a human-readable `name`; a second type reusing an existing code is
        rejected with `ERR_DUPLICATE_LICENSE_TYPE_CODE`."

        Design: Corner/validations/duplicate_license_type_code_rejected
        """
        create_license_type()
        resp = api.create_license_type(create_license_type_payload(
            code="RN", name="Registered Nurse Again",
            ce_hours_required_per_cycle=0, cycle_length_months=12,
            verification_frequency_days=90, grace_period_days=0,
            requires_exclusion_screening=False,
            reimbursement_mode="FLAT_SCHEDULE", reimburse_full_up_to_cents=0,
            reimburse_half_up_to_cents=0, flat_schedule_amount_cents=0,
            hard_claim_cap_cents=100_000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LICENSE_TYPE_CODE, 409)
