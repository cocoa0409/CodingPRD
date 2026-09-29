"""The gate conditions the submission call enforces: one live file per profession, the
pathway-keyed residency floor, the military-spouse status demand, and the qualifying
credential set that an unverified letter leaves empty."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    APP_DRAFT,
    APP_SUBMITTED,
    CREDENTIAL_ACTIVE,
    MILITARY_VETERAN,
    PATHWAY_ENDORSEMENT,
    PATHWAY_MILITARY_SPOUSE_EXPEDITED,
    PATHWAY_UNIVERSAL_RECOGNITION,
    ApiErrorId,
    application_payload,
    assert_application_fields,
    make_applicant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PHYSICAL_THERAPIST = {
    "profession_code": "PT",
    "title": "Physical Therapist",
    "required_scope_elements": ["ASSESS", "TREAT"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 60.0,
    "exam_waiver_min_score": 99.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 90,
    "base_fee_cents": 18000,
    "endorsement_fee_cents": 5000,
    "exam_fee_cents": 4000,
    "jurisprudence_fee_cents": 0,
    "permit_fee_cents": 3000,
    "expedite_surcharge_pct": 0.10,
}


@pytest.fixture
def one_live_nursing_file(setup):
    """A nursing endorsement already submitted, so the applicant and profession pair sits
    in the blocking set."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Dov Harel")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14001",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    return {
        "ap_id": applicant["id"],
        "prof_id": profession["id"],
        "cred_id": credential["id"],
        "app_id": application["id"],
    }


@pytest.fixture
def six_months_of_residency_two_drafts(setup):
    """One applicant six months into residency holding two draft files: a
    universal-recognition nursing file and an endorsement physical-therapy file, both
    resting on the same verified credential."""
    nursing = setup.profession()
    therapy = setup.profession(**PHYSICAL_THERAPIST)
    applicant = setup.applicant(full_name="Enid Mbeki", residency_months=6)
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14002",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    recognition = setup.application(
        applicant["id"],
        nursing["id"],
        credential["id"],
        pathway=PATHWAY_UNIVERSAL_RECOGNITION,
    )
    endorsement = setup.application(
        applicant["id"], therapy["id"], credential["id"], pathway=PATHWAY_ENDORSEMENT
    )
    return {
        "ap_id": applicant["id"],
        "recognition_id": recognition["id"],
        "endorsement_id": endorsement["id"],
    }


@pytest.fixture
def veteran_on_the_spouse_pathway(setup):
    """A veteran — not a military spouse — holding a draft file on the expedited
    military-spouse pathway."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Faye Okonkwo", military_status=MILITARY_VETERAN)
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14003",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(
        applicant["id"],
        profession["id"],
        credential["id"],
        pathway=PATHWAY_MILITARY_SPOUSE_EXPEDITED,
    )
    return {"ap_id": applicant["id"], "app_id": application["id"]}


@pytest.fixture
def draft_resting_on_an_unverified_credential(setup):
    """A draft endorsement whose only credential is active but still awaiting the issuing
    state's verification letter."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Gus Halvorsen")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14004",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
        verified_good_standing=False,
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    return {
        "ap_id": applicant["id"],
        "cred_id": credential["id"],
        "app_id": application["id"],
    }


class TestOneLiveFilePerProfession:
    def test_a_second_file_for_the_same_profession_is_refused_while_the_first_lives(
        self, api, one_live_nursing_file, setup
    ):
        """PRD §3.4: "An applicant may not hold two live applications for the same
        profession: if another application for the same applicant and profession is
        already in `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT`, `SUSPENDED_REVIEW` or
        `APPROVED`, the new one is refused with `ERR_DUPLICATE_ACTIVE_APPLICATION`."  PRD
        §2.8: "One live application per profession — no other application for the same
        applicant and profession pair is in `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT`,
        `SUSPENDED_REVIEW` or `APPROVED`. `ERR_DUPLICATE_ACTIVE_APPLICATION`, 409. Applies
        to opening an application."

        Design: Corner/validations/duplicate_active_application_for_same_profession_rejected
        """
        env = one_live_nursing_file
        response = api.create_application(
            application_payload(env["ap_id"], env["prof_id"], env["cred_id"]),
            make_applicant_headers(env["ap_id"]),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION.value, 409)

        _rows, meta = validate_paginated(
            api.list_applications(ANALYST_HEADERS, {"applicant_id": env["ap_id"]})
        )
        assert meta["total_count"] == 1
        assert_application_fields(setup.read_application(env["app_id"]), status=APP_SUBMITTED)


class TestPathwayEligibilityAtTheGate:
    def test_six_months_of_residency_cannot_carry_a_universal_recognition_file(
        self, api, six_months_of_residency_two_drafts, setup
    ):
        """PRD §3.4: "Choosing `UNIVERSAL_RECOGNITION` requires the applicant's
        `residency_months` to be at least the profession's
        `universal_recognition_min_residency_months`, failing as
        `ERR_RESIDENCY_REQUIREMENT_NOT_MET`."  PRD §2.8: "Residency — the
        `UNIVERSAL_RECOGNITION` pathway requires the applicant's `residency_months` to be
        at least the profession's `universal_recognition_min_residency_months`.
        `ERR_RESIDENCY_REQUIREMENT_NOT_MET`, 422. Applies to submitting an application."

        Design: Corner/validations/universal_recognition_residency_requirement_not_met_rejected
        """
        env = six_months_of_residency_two_drafts
        response = api.submit_application(
            env["recognition_id"], {}, make_applicant_headers(env["ap_id"])
        )

        validate_error(response, ApiErrorId.ERR_RESIDENCY_REQUIREMENT_NOT_MET.value, 422)

        assert_application_fields(
            setup.read_application(env["recognition_id"]),
            status=APP_DRAFT,
            submitted_at=None,
            gross_total_cents=0,
        )
        assert setup.ledger_meta(env["recognition_id"])["total_count"] == 0

    def test_the_residency_floor_leaves_the_endorsement_file_free_to_submit(
        self, api, six_months_of_residency_two_drafts, setup
    ):
        """PRD §3.4: "Choosing `UNIVERSAL_RECOGNITION` requires the applicant's
        `residency_months` to be at least the profession's
        `universal_recognition_min_residency_months`, failing as
        `ERR_RESIDENCY_REQUIREMENT_NOT_MET`."  PRD §3.4: "The endorsement component is the
        profession's `endorsement_fee_cents` when the pathway is `ENDORSEMENT` or
        `UNIVERSAL_RECOGNITION`, and zero on the `MILITARY_SPOUSE_EXPEDITED` pathway."

        Design: Corner/validations/universal_recognition_residency_requirement_not_met_rejected
        """
        env = six_months_of_residency_two_drafts
        submitted = validate_success(
            api.submit_application(
                env["endorsement_id"], {}, make_applicant_headers(env["ap_id"])
            ),
            200,
        )

        assert_application_fields(
            submitted,
            status=APP_SUBMITTED,
            gross_total_cents=27000,
            fee_balance_cents=27000,
        )

    def test_a_veteran_may_not_ride_the_military_spouse_pathway(
        self, api, veteran_on_the_spouse_pathway, setup
    ):
        """PRD §3.4: "Choosing `MILITARY_SPOUSE_EXPEDITED` requires the applicant's
        `military_status` to be exactly `MILITARY_SPOUSE`, failing as
        `ERR_MILITARY_STATUS_REQUIRED`."  PRD §2.8: "Military-spouse eligibility — the
        `MILITARY_SPOUSE_EXPEDITED` pathway requires the applicant's `military_status` to
        be `MILITARY_SPOUSE`. `ERR_MILITARY_STATUS_REQUIRED`, 422. Applies to submitting an
        application."

        Design: Corner/validations/military_status_required_for_expedited_pathway_rejected
        """
        env = veteran_on_the_spouse_pathway
        response = api.submit_application(
            env["app_id"], {}, make_applicant_headers(env["ap_id"])
        )

        validate_error(response, ApiErrorId.ERR_MILITARY_STATUS_REQUIRED.value, 422)

        assert_application_fields(
            setup.read_application(env["app_id"]), status=APP_DRAFT, submitted_at=None
        )
        assert setup.read_applicant(env["ap_id"])["military_status"] == MILITARY_VETERAN
        assert setup.ledger_meta(env["app_id"])["total_count"] == 0


class TestQualifyingCredentialSet:
    def test_an_active_but_unverified_credential_leaves_the_qualifying_set_empty(
        self, api, draft_resting_on_an_unverified_credential, setup
    ):
        """PRD §3.4: "And finally the qualifying credential test: the applicant must hold
        at least one out-of-state credential whose `status` is `ACTIVE` **and** whose
        `verified_good_standing` is true, and the row named by `primary_credential_id` must
        itself be a member of that qualifying set."  PRD §3.4: "Either failure — an empty
        qualifying set, or a primary credential that is outside it — is
        `ERR_NO_QUALIFYING_CREDENTIAL`."  PRD §3.2: "Only credentials that are both
        `ACTIVE` and `verified_good_standing` can carry an application; that filter is
        applied once, at submission, and is examined in §3.4."

        Design: Corner/validations/no_qualifying_credential_on_submit_rejected
        """
        env = draft_resting_on_an_unverified_credential
        response = api.submit_application(
            env["app_id"], {}, make_applicant_headers(env["ap_id"])
        )

        validate_error(response, ApiErrorId.ERR_NO_QUALIFYING_CREDENTIAL.value, 422)

        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_DRAFT,
            submitted_at=None,
            review_deadline_at=None,
        )
        credentials, _meta = validate_paginated(
            api.list_credentials(env["ap_id"], make_applicant_headers(env["ap_id"]), None)
        )
        offered = next(row for row in credentials if row["id"] == env["cred_id"])
        assert offered["status"] == CREDENTIAL_ACTIVE
        assert offered["verified_good_standing"] is False
