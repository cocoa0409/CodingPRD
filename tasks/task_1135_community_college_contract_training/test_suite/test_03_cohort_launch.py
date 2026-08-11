"""Cohort launch gates: agreement-state dependency, assignment coverage,
minimum-enrollment boundary."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_employer,
    create_approved_assessment,
    create_quoted_agreement,
    create_signed_agreement,
    create_venue_for_mode,
    create_cohort_under,
    create_session_on,
    create_instructor,
    propose_assignment,
    propose_and_confirm,
    confirm_assignment,
    enroll_participants,
    api_client,
    TEST_USERS,
    make_employer_contact_headers,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestLaunchRequiresSignedAgreement:
    def test_launch_under_quoted_rejected_then_sign_allows(self, api):
        """PRD §3.6: "A `WorkforceCoordinator` launches a `SCHEDULED` cohort
        only when four gates pass: the agreement is `SIGNED` or `IN_DELIVERY`
        (otherwise `ERR_AGREEMENT_NOT_SIGNED`)".
        PRD §3.2: "The agreement moves from `SIGNED` to `IN_DELIVERY` the
        moment its first child cohort launches."

        Design: Difficulty/cross_entity_state_dependency/cohort_launch_requires_agreement_signed
        """
        emp = create_employer(legal_name="Rho Inc", industry_code="336111",
                              contact_email="hr@rho.example")
        na = create_approved_assessment(emp["id"])
        agr = create_quoted_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT")
        coh = create_cohort_under(agr["id"], min_enrollment=1)
        ven = create_venue_for_mode("ON_SITE", name="Rho Floor", capacity=6)
        s = create_session_on(coh["id"], ven["id"],
                              "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        ins = create_instructor(full_name="Lea Instructor")
        propose_and_confirm(s["id"], ins["id"])
        enroll_participants(coh["id"], ["R01"])

        resp = api_client.launch_cohort(coh["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)

        validate_success(
            api_client.sign_training_agreement(agr["id"], make_employer_contact_headers(emp["id"]))
        )
        launched = validate_success(api_client.launch_cohort(coh["id"], COORD))
        assert launched["delivery_status"] == "LAUNCHED"
        agr_after = get_success_data(api_client.get_training_agreement(agr["id"], COORD))
        assert agr_after["contract_status"] == "IN_DELIVERY"

    def test_launch_on_draft_agreement_rejected(self, api):
        """PRD §3.6: "the agreement is `SIGNED` or `IN_DELIVERY` (otherwise
        `ERR_AGREEMENT_NOT_SIGNED`)" — a cohort created under a later state
        cannot be launched after the agreement regresses or before signature.

        Design: Difficulty/cross_entity_state_dependency/cohort_launch_requires_agreement_signed
        """
        # Build a QUOTED (unsigned) agreement with a fully-staffed cohort and
        # confirm the launch gate (not any cohort-local gate) is what fails.
        emp = create_employer()
        na = create_approved_assessment(emp["id"])
        agr = create_quoted_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT")
        coh = create_cohort_under(agr["id"], min_enrollment=1)
        ven = create_venue_for_mode("ON_SITE")
        s = create_session_on(coh["id"], ven["id"],
                              "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        ins = create_instructor()
        propose_and_confirm(s["id"], ins["id"])
        enroll_participants(coh["id"], ["X01"])
        resp = api_client.launch_cohort(coh["id"], COORD)
        err = validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)
        assert err["error_id"] == "ERR_AGREEMENT_NOT_SIGNED"


class TestLaunchRequiresAllSessionsConfirmed:
    def test_proposed_only_session_blocks_launch(self, api):
        """PRD §3.6: "every `PLANNED` session holds at least one `CONFIRMED`
        assignment (otherwise `ERR_CREDENTIAL_MISMATCH`)".

        Design: Difficulty/cross_entity_state_dependency/cohort_launch_requires_all_sessions_confirmed
        """
        emp = create_employer(legal_name="Sigma SA", industry_code="541330",
                              contact_email="hr@sigma.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_delivery_hours=4)
        ven = create_venue_for_mode("ON_SITE", name="Sigma Lab", capacity=6)
        coh = create_cohort_under(agr["id"], min_enrollment=1,
                                  start_date="2026-06-15T00:00:00Z",
                                  end_date="2026-06-16T00:00:00Z",
                                  venue_id=ven["id"])
        s1 = create_session_on(coh["id"], ven["id"],
                               "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        s2 = create_session_on(coh["id"], ven["id"],
                               "2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z")
        ins = create_instructor(full_name="Hal Instructor")
        propose_and_confirm(s1["id"], ins["id"])
        asg2 = propose_assignment(s2["id"], ins["id"])  # left PROPOSED
        enroll_participants(coh["id"], ["S01"])

        resp = api_client.launch_cohort(coh["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_MISMATCH)

        confirm_assignment(asg2["id"])
        launched = validate_success(api_client.launch_cohort(coh["id"], COORD))
        assert launched["delivery_status"] == "LAUNCHED"

    def test_all_confirmed_launch_succeeds(self, api):
        """PRD §3.6: "A launched cohort lands in `LAUNCHED`" once all four
        gates — agreement state, enrollment floor, assignment coverage, venue
        capacity — pass.

        Design: Difficulty/cross_entity_state_dependency/cohort_launch_requires_all_sessions_confirmed
        """
        emp = create_employer()
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT")
        ven = create_venue_for_mode("ON_SITE")
        coh = create_cohort_under(agr["id"], min_enrollment=1, venue_id=ven["id"])
        s = create_session_on(coh["id"], ven["id"],
                              "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        ins = create_instructor()
        propose_and_confirm(s["id"], ins["id"])
        enroll_participants(coh["id"], ["S01"])
        launched = validate_success(api_client.launch_cohort(coh["id"], COORD))
        assert launched["delivery_status"] == "LAUNCHED"


class TestMinEnrollmentBoundary:
    def _setup_two_cohorts(self, api):
        emp = create_employer(legal_name="Omicron", industry_code="325411",
                              contact_email="hr@omicron.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_participant_count=4, max_cohorts=3)
        ven = create_venue_for_mode("ON_SITE", name="Omi Floor", capacity=10)
        ins = create_instructor(full_name="Fay Instructor")
        ca = create_cohort_under(agr["id"], min_enrollment=2,
                                 start_date="2026-06-15T00:00:00Z",
                                 end_date="2026-06-15T00:00:00Z", venue_id=ven["id"])
        cb = create_cohort_under(agr["id"], min_enrollment=2,
                                 start_date="2026-06-16T00:00:00Z",
                                 end_date="2026-06-16T00:00:00Z", venue_id=ven["id"])
        sa = create_session_on(ca["id"], ven["id"],
                               "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        sb = create_session_on(cb["id"], ven["id"],
                               "2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z")
        propose_and_confirm(sa["id"], ins["id"])
        propose_and_confirm(sb["id"], ins["id"])
        enroll_participants(ca["id"], ["O01", "O02"])  # exactly at floor
        enroll_participants(cb["id"], ["O03"])          # one below floor
        return ca, cb

    def test_enrollment_equal_to_floor_launches(self, api):
        """PRD §3.6: "`enrolled_count` is at least `min_enrollment` — the
        boundary itself passes, so an exactly-full floor launches".

        Design: Difficulty/boundary_precision_check/cohort_launch_min_enrollment_boundary
        """
        ca, _ = self._setup_two_cohorts(api)
        launched = validate_success(api_client.launch_cohort(ca["id"], COORD))
        assert launched["delivery_status"] == "LAUNCHED"

    def test_enrollment_below_floor_rejected(self, api):
        """PRD §3.6: "a shortfall is rejected with
        `ERR_BELOW_MIN_ENROLLMENT`".

        Design: Difficulty/boundary_precision_check/cohort_launch_min_enrollment_boundary
        """
        _, cb = self._setup_two_cohorts(api)
        resp = api_client.launch_cohort(cb["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_ENROLLMENT)
