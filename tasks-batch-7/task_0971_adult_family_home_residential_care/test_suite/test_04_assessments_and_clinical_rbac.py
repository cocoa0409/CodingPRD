"""Assessment lifecycle and the Nurse-exclusive clinical surface."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_assessment_payload, create_home, create_resident,
    create_and_finalize_assessment, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestAssessmentFinalization:
    def test_finalize_already_finalized_rejected(self, api):
        """PRD §3.2: "Finalization by a `Nurse` moves the assessment `DRAFT` →
        `FINALIZED` and requires the resident to be `PROSPECT`, `APPLICANT`, or
        `ADMITTED` with all assessed fields complete."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/finalize_already_finalized_assessment_rejected
        """
        home = create_home(name="Asm Twice", licensed_bed_capacity=4)
        resident = create_resident(home["id"])
        asm = create_and_finalize_assessment(resident["id"])
        assert asm["status"] == "FINALIZED"
        res = api.finalize_assessment(asm["id"], NURSE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestClinicalRoleBoundaries:
    def test_provider_cannot_finalize_assessment(self, api):
        """PRD §3.2: "Finalization by a `Nurse` moves the assessment `DRAFT` →
        `FINALIZED` and requires the resident to be `PROSPECT`, `APPLICANT`, or
        `ADMITTED` with all assessed fields complete."
        PRD §2.1: "A request that is authenticated but whose role is not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/provider_cannot_finalize_assessment
        """
        home = create_home(name="RBAC Prov", licensed_bed_capacity=4)
        resident = create_resident(home["id"])
        asm = validate_success(
            api.create_assessment(resident["id"], create_assessment_payload(), NURSE),
            201)
        res = api.finalize_assessment(asm["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        asm_after = validate_success(api.get_assessment(asm["id"], NURSE), 200)
        assert asm_after["status"] == "DRAFT", \
            "a denied finalize must leave the assessment DRAFT"

    def test_nurse_can_create_and_finalize_assessment(self, api):
        """PRD §3.2: "Finalization by a `Nurse` moves the assessment `DRAFT` →
        `FINALIZED` and requires the resident to be `PROSPECT`, `APPLICANT`, or
        `ADMITTED` with all assessed fields complete."

        Design: Corner/rbac/nurse_can_create_and_finalize_assessment
        """
        home = create_home(name="RBAC Nurse Ok", licensed_bed_capacity=4)
        resident = create_resident(home["id"])
        asm = validate_success(
            api.create_assessment(resident["id"], create_assessment_payload(), NURSE),
            201)
        finalized = validate_success(api.finalize_assessment(asm["id"], NURSE), 200)
        assert finalized["status"] == "FINALIZED"

    def test_finalization_promotes_prospect_to_applicant(self, api):
        """PRD §3.2: "If the resident was `PROSPECT`, they are promoted to
        `APPLICANT` — the first finalized assessment is what makes a prospect an
        applicant."

        Design: Corner/rbac/nurse_can_create_and_finalize_assessment
        """
        home = create_home(name="RBAC Nurse Ok", licensed_bed_capacity=4)
        resident = create_resident(home["id"])
        create_and_finalize_assessment(resident["id"])
        resident_after = validate_success(api.get_resident(resident["id"], NURSE), 200)
        assert resident_after["status"] == "APPLICANT", \
            "the first FINALIZED assessment must promote the PROSPECT"
