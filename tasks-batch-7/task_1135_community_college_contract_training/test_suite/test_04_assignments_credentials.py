"""Instructor assignments: duty segregation, credential scoring/expiry,
double-booking semantics, committed-hours conservation."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_employer,
    create_approved_assessment,
    create_signed_agreement,
    create_venue_for_mode,
    create_cohort_under,
    create_session_on,
    create_instructor,
    propose_assignment,
    propose_and_confirm,
    enroll_participants,
    api_client,
    TEST_USERS,
    make_credential_officer_headers,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]
CRED = TEST_USERS["credential_officer_headers"]


def _basic_signed_cohort(api, curriculum_modules=None, **cohort_overrides):
    emp = create_employer()
    na = create_approved_assessment(emp["id"], curriculum_modules=curriculum_modules)
    agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT")
    ven = create_venue_for_mode("ON_SITE", capacity=cohort_overrides.pop("capacity", 8))
    coh = create_cohort_under(agr["id"], venue_id=ven["id"], **cohort_overrides)
    return emp, agr, ven, coh


class TestSegregationOfDuties:
    def test_proposer_cannot_confirm_own_proposal(self, api):
        """PRD §3.5: "the confirmer's `X-User-ID` must differ from
        `proposed_by_user_id` — the proposer may never confirm their own
        proposal, and a self-confirmation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`".

        Design: Corner/rbac/segregation_of_duties_confirm_own_proposal_rejected
        """
        _, _, ven, coh = _basic_signed_cohort(api, min_enrollment=1)
        s = create_session_on(coh["id"], ven["id"],
                              "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        ins = create_instructor(full_name="Val Instructor")
        # proposed by wc-01 (the shared coordinator identity)
        asg = propose_assignment(s["id"], ins["id"])

        # Same X-User-ID wearing the CredentialOfficer role
        resp = api_client.confirm_instructor_assignment(
            asg["id"], make_credential_officer_headers("wc-01")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # A different CredentialOfficer confirms successfully
        confirmed = validate_success(api_client.confirm_instructor_assignment(asg["id"], CRED))
        assert confirmed["status"] == "CONFIRMED"


class TestCredentialMatchScore:
    def test_recency_half_weight_pulls_score_below_threshold(self, api):
        """PRD §3.5: "Each required code contributes a weight read from the
        instructor's `credentials`: zero when the instructor holds no
        credential with that code; zero when the credential's `expires_on`
        falls before the session's `start_at` — the expiry case that
        independently blocks confirmation with `ERR_CREDENTIAL_EXPIRED`; one
        half when the credential expires on or after `start_at` but within
        thirty days of it; and one when `expires_on` lies at least thirty days
        beyond `start_at`. The score is one hundred times the sum of the
        weights divided by the number of required codes, rounded half up to an
        integer percent". PRD §3.5: "the computed `match_score` must be at
        least 80 (otherwise `ERR_CREDENTIAL_MISMATCH`)".

        Design: Corner/calculations/credential_match_score_recency_weighting
        """
        modules = [{"code": "T-1", "hours": 2,
                    "required_credential_codes": ["CNC", "OSHA30"]}]
        _, _, ven, coh = _basic_signed_cohort(api, curriculum_modules=modules,
                                              min_enrollment=1)
        s = create_session_on(coh["id"], ven["id"],
                              "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        ins = create_instructor(
            full_name="Ned Instructor",
            credentials=[{"code": "CNC", "expires_on": "2027-06-01"},
                         {"code": "OSHA30", "expires_on": "2026-06-20"}],
        )
        asg = propose_assignment(s["id"], ins["id"])
        resp = api_client.confirm_instructor_assignment(asg["id"], CRED)
        # weights 1.0 and 0.5 -> score round(100*1.5/2) = 75 < 80
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_MISMATCH)


class TestSafetyVsTemporalPriority:
    def test_expired_credential_reported_over_double_booking(self, api):
        """PRD §2.8: "Incoming requests are validated in a fixed priority
        order, and the first failing check produces the error response", with
        item 7 "Credential compliance and duty segregation at assignment
        confirmation: `ERR_CREDENTIAL_EXPIRED`, `ERR_CREDENTIAL_MISMATCH`,
        `ERR_SEGREGATION_OF_DUTIES`" ordered before item 8 "Temporal windows
        and overlaps: `ERR_QUOTE_EXPIRED`, `ERR_GRANT_WINDOW_CLOSED`,
        `ERR_INSTRUCTOR_DOUBLE_BOOKED`, `ERR_VENUE_OVERLAP`".

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_assignment_confirm
        """
        # Agreement/cohort 0: curriculum with NO required credentials, so the
        # expired credential does not gate the confirm that builds the overlap.
        emp = create_employer(legal_name="Nu Co", industry_code="621511",
                              contact_email="hr@nu.example")
        na0 = create_approved_assessment(emp["id"], curriculum_modules=[
            {"code": "SOFT-1", "hours": 3, "required_credential_codes": []}])
        agr0 = create_signed_agreement(emp["id"], na0["id"], pricing_model="FLAT_COHORT",
                                       est_delivery_hours=3)
        ven0 = create_venue_for_mode("ON_SITE", name="Nu Room", capacity=8)
        coh0 = create_cohort_under(agr0["id"], min_enrollment=1, venue_id=ven0["id"])
        sc = create_session_on(coh0["id"], ven0["id"],
                               "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        inx = create_instructor(full_name="Xena Instructor",
                                credentials=[{"code": "CNC", "expires_on": "2026-06-01"}])
        asgc = propose_and_confirm(sc["id"], inx["id"])
        assert asgc["status"] == "CONFIRMED"

        # Agreement/cohort 1: curriculum REQUIRES CNC; session overlaps sc.
        na1 = create_approved_assessment(emp["id"], curriculum_modules=[
            {"code": "CNC-9", "hours": 2, "required_credential_codes": ["CNC"]}])
        agr1 = create_signed_agreement(emp["id"], na1["id"], pricing_model="FLAT_COHORT")
        ven1 = create_venue_for_mode("ON_SITE", name="Nu Room 2", capacity=8)
        coh1 = create_cohort_under(agr1["id"], min_enrollment=1, venue_id=ven1["id"])
        sb = create_session_on(coh1["id"], ven1["id"],
                               "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z")
        asgb = propose_assignment(sb["id"], inx["id"])

        resp = api_client.confirm_instructor_assignment(asgb["id"], CRED)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_EXPIRED)

    def test_expired_credential_alone_blocks_confirm(self, api):
        """PRD §3.5: "no credential required by the cohort's curriculum may be
        expired at the session's start (otherwise `ERR_CREDENTIAL_EXPIRED`)" —
        the safety gate fires on its own, without any overlap present.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_assignment_confirm
        """
        modules = [{"code": "CNC-9", "hours": 2, "required_credential_codes": ["CNC"]}]
        _, _, ven, coh = _basic_signed_cohort(api, curriculum_modules=modules,
                                              min_enrollment=1)
        s = create_session_on(coh["id"], ven["id"],
                              "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        ins = create_instructor(full_name="Xena Solo",
                                credentials=[{"code": "CNC", "expires_on": "2026-06-01"}])
        asg = propose_assignment(s["id"], ins["id"])
        resp = api_client.confirm_instructor_assignment(asg["id"], CRED)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_EXPIRED)


class TestInstructorDoubleBooking:
    def _three_session_setup(self, api):
        emp = create_employer(legal_name="Upsilon", industry_code="484121",
                              contact_email="hr@upsilon.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_delivery_hours=5)
        v1 = create_venue_for_mode("ON_SITE", name="U1", capacity=5)
        v2 = create_venue_for_mode("ON_SITE", name="U2", capacity=5)
        v3 = create_venue_for_mode("ON_SITE", name="U3", capacity=5)
        coh = create_cohort_under(agr["id"], min_enrollment=1, venue_id=v1["id"])
        sa = create_session_on(coh["id"], v1["id"],
                               "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        sb = create_session_on(coh["id"], v2["id"],
                               "2026-06-15T11:00:00Z", "2026-06-15T13:00:00Z")
        sc = create_session_on(coh["id"], v3["id"],
                               "2026-06-15T12:30:00Z", "2026-06-15T14:00:00Z")
        ins = create_instructor(full_name="Jay Instructor")
        propose_and_confirm(sa["id"], ins["id"])
        return ins, sb, sc

    def test_adjacent_half_open_sessions_allowed(self, api):
        """PRD §3.5: "the session's window must not overlap, under half-open
        semantics, any other session on which the same instructor holds a
        `CONFIRMED` assignment — windows that merely touch, the previous
        `end_at` equalling the next `start_at`, are allowed".

        Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_allowed
        """
        ins, sb, _ = self._three_session_setup(api)
        asgb = propose_assignment(sb["id"], ins["id"])
        confirmed = validate_success(api_client.confirm_instructor_assignment(asgb["id"], CRED))
        assert confirmed["status"] == "CONFIRMED"

    def test_strict_overlap_rejected_and_hours_unchanged(self, api):
        """PRD §3.5: "a true overlap is rejected with
        `ERR_INSTRUCTOR_DOUBLE_BOOKED`". PRD §3.5: "increases the instructor's
        `committed_hours` by the session's `hours`" on a successful confirm.

        Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_allowed
        """
        ins, sb, sc = self._three_session_setup(api)
        asgb = propose_assignment(sb["id"], ins["id"])
        validate_success(api_client.confirm_instructor_assignment(asgb["id"], CRED))
        asgc = propose_assignment(sc["id"], ins["id"])
        resp = api_client.confirm_instructor_assignment(asgc["id"], CRED)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED)
        ins_after = get_success_data(api_client.get_instructor(ins["id"], COORD))
        # 2h (SA) + 2h (SB); the rejected confirm added nothing
        assert ins_after["committed_hours"] == 4, (
            f"expected committed_hours 4, got {ins_after['committed_hours']}"
        )


class TestCommittedHoursConservation:
    def _two_confirm_setup(self, api):
        emp = create_employer(legal_name="Psi Co", industry_code="713110",
                              contact_email="hr@psi.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_delivery_hours=3.5)
        ven = create_venue_for_mode("ON_SITE", name="Psi Gym", capacity=10)
        coh = create_cohort_under(agr["id"], min_enrollment=1, venue_id=ven["id"])
        s1 = create_session_on(coh["id"], ven["id"],
                               "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        s2 = create_session_on(coh["id"], ven["id"],
                               "2026-06-15T12:00:00Z", "2026-06-15T13:30:00Z")
        ins = create_instructor(full_name="Kay Instructor")
        asg1 = propose_and_confirm(s1["id"], ins["id"])
        propose_and_confirm(s2["id"], ins["id"])
        return ins, s1, asg1

    def test_confirm_then_compensating_release_restores_hours(self, api):
        """PRD §3.5: "`committed_hours` is not a free-running counter but a
        defined quantity — the sum of `hours` over the instructor's
        `CONFIRMED` assignments on `PLANNED` sessions — so a confirm followed
        by its compensating release leaves it unchanged."

        Design: Difficulty/compensating_invariant/instructor_hours_conservation_on_confirm_release
        """
        ins, s1, asg1 = self._two_confirm_setup(api)
        h1 = get_success_data(api_client.get_instructor(ins["id"], COORD))["committed_hours"]
        assert h1 == 3.5, f"expected 3.5 after two confirms, got {h1}"

        validate_success(api_client.release_instructor_assignment(asg1["id"], CRED))
        h2 = get_success_data(api_client.get_instructor(ins["id"], COORD))["committed_hours"]
        assert h2 == 1.5, f"expected 1.5 after release, got {h2}"

    def test_reconfirm_round_trip_returns_to_conserved_sum(self, api):
        """PRD §3.5: "the sum of `hours` over the instructor's `CONFIRMED`
        assignments on `PLANNED` sessions" — a release followed by a fresh
        confirm of equal hours returns the field to the same defined value.

        Design: Difficulty/compensating_invariant/instructor_hours_conservation_on_confirm_release
        """
        ins, s1, asg1 = self._two_confirm_setup(api)
        validate_success(api_client.release_instructor_assignment(asg1["id"], CRED))
        asg1b = propose_and_confirm(s1["id"], ins["id"])
        assert asg1b["status"] == "CONFIRMED"
        h3 = get_success_data(api_client.get_instructor(ins["id"], COORD))["committed_hours"]
        assert h3 == 3.5, f"expected 3.5 after re-confirm, got {h3}"
