"""Requests that break two rules at once, where only the higher-precedence rule
is ever reported — and the same request changes its answer when the winner is
satisfied.
"""

from test_helpers import (
    AccessStatus,
    AdoptionStatus,
    AcademicTermStatus,
    ApiErrorId,
    BillingStatus,
    PublisherAgreementStatus,
    SectionIaStatus,
    assert_money,
    fixtures,
    make_program_admin_headers,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CEDAR_AGREEMENT = {"publisher_name": "Cedar House", "agreement_code": "PUB-C"}
HISTORY_TITLE = {
    "isbn": "978-0-11-000002-0",
    "title": "World History Reader",
    "list_price_cents": 18000,
}
HISTORY_SECTION = {
    "subject_code": "HIST",
    "catalog_number": "210",
    "section_number": "001",
    "instructor_user_id": "fac-2",
}
MATH_SECTION = {
    "subject_code": "MATH",
    "catalog_number": "140",
    "section_number": "001",
    "instructor_user_id": "fac-3",
    "max_concurrent_titles": 1,
}
SECOND_TITLE = {
    "isbn": "978-0-11-000005-0",
    "title": "Economics Essentials",
    "list_price_cents": 12000,
}


class TestMoneyGateBeatsOptOutWindow:
    """State (rank 9) outranks business_temporal (rank 24) on the same request."""

    @staticmethod
    def _billed_section_two_days_past_the_window(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        fixtures.set_clock(api, "2026-09-06T10:00:00Z")
        return scenario

    def test_shut_window_is_what_an_open_term_reports(self, api, bursar_officer):
        """PRD §3.6: "Filing also requires the enrollment behind the charge to
        still be `ENROLLED` (else `ERR_ENROLLMENT_NOT_ACTIVE`), the current
        logical instant to be at or before the charge's `opt_out_deadline_at`
        (else `ERR_OPT_OUT_WINDOW_CLOSED`), and the term to be `OPEN` (else
        `ERR_TERM_BILLING_LOCKED`)."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_term_billing_locked_beats_opt_out_window_closed
        """
        scenario = self._billed_section_two_days_past_the_window(api)
        charge_id = scenario["charge_ids"][1]

        charge = validate_success(api.get_charge(charge_id, bursar_officer))
        # The add/drop cap bound the window at end of day on 2026-09-04.
        assert charge["opt_out_deadline_at"] == "2026-09-04T23:59:59.999Z"

        term = fixtures.read_term(api, scenario["term_id"])
        assert term["status"] == AcademicTermStatus.OPEN.value

        response = api.create_opt_out_request(
            {"charge_id": charge_id, "reason_code": "OWNS_COPY"},
            make_student_headers(scenario["student_ids"][1]),
        )
        validate_error(response, ApiErrorId.OPT_OUT_WINDOW_CLOSED.value)

    def test_locking_billing_masks_the_closed_window(self, api, bursar_officer):
        """PRD §2.11: "When several checks could fire on one request, they are
        evaluated in a single global order and the first failure is returned."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_term_billing_locked_beats_opt_out_window_closed
        """
        scenario = self._billed_section_two_days_past_the_window(api)
        charge_id = scenario["charge_ids"][1]

        locked = fixtures.lock_term_billing(api, scenario["term_id"])
        assert locked["status"] == AcademicTermStatus.BILLING_LOCKED.value

        # Identical request, now breaking both rules: the money gate answers.
        response = api.create_opt_out_request(
            {"charge_id": charge_id, "reason_code": "OWNS_COPY"},
            make_student_headers(scenario["student_ids"][1]),
        )
        validate_error(response, ApiErrorId.TERM_BILLING_LOCKED.value)

        _, meta = validate_paginated(
            api.list_charge_opt_out_requests(charge_id, bursar_officer)
        )
        assert meta["total_count"] == 0

        charge = validate_success(api.get_charge(charge_id, bursar_officer))
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert charge["access_status"] == AccessStatus.PROVISIONED.value
        assert_money(charge["net_billed_cents"], 9450)


class TestAgreementGateBeatsTierLookup:
    """A 409 referential gate pre-empts a 422 fiscal computation."""

    @staticmethod
    def _flagged_section_whose_only_band_covers_one_student(api):
        scenario = fixtures.setup_billed_section(
            api,
            setup_clock="2026-07-01T00:00:00Z",
            agreement_overrides=CEDAR_AGREEMENT,
            title_overrides=HISTORY_TITLE,
            bands=((1, 1, 9000),),
            section_overrides=HISTORY_SECTION,
            roster=(("S-3001", "Eli Fox"), ("S-3002", "Fay Idris")),
            post_charges_now=False,
        )
        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        return scenario

    def test_uncovered_tier_basis_is_what_an_active_agreement_reports(self, api,
                                                                     bursar_officer):
        """PRD §3.5: "Because bands never overlap, at most one band can match; if
        none matches, the posting is rejected with `ERR_NO_PRICING_TIER` (HTTP
        422)."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_agreement_not_active_beats_no_pricing_tier
        """
        scenario = self._flagged_section_whose_only_band_covers_one_student(api)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["status"] == PublisherAgreementStatus.ACTIVE.value

        # Two enrolled students, and the sole band [1,1] cannot cover n = 2.
        response = api.post_section_charges(scenario["section_id"], bursar_officer)
        validate_error(response, ApiErrorId.NO_PRICING_TIER.value)

    def test_suspension_pre_empts_the_tier_lookup_entirely(self, api, bursar_officer,
                                                           registrar):
        """PRD §3.2: "From the moment an agreement is suspended, three operations
        touching any of its titles are rejected with `ERR_AGREEMENT_NOT_ACTIVE`:
        approving an adoption of one of its titles, flagging a section for
        inclusive access under one of its titles, and posting charges — whether
        the batch form or the single-enrollment form — on a section priced by one
        of its titles."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_agreement_not_active_beats_no_pricing_tier
        """
        scenario = self._flagged_section_whose_only_band_covers_one_student(api)

        suspended = fixtures.suspend_agreement(api, scenario["agreement_id"])
        assert suspended["status"] == PublisherAgreementStatus.SUSPENDED.value

        response = api.post_section_charges(scenario["section_id"], bursar_officer)
        validate_error(response, ApiErrorId.AGREEMENT_NOT_ACTIVE.value)

        for enrollment_id in scenario["enrollment_ids"]:
            _, meta = validate_paginated(
                api.list_enrollment_charges(enrollment_id, bursar_officer)
            )
            assert meta["total_count"] == 0

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.FLAGGED.value
        assert section["billing_basis_enrollment_count"] is None

        for student_id in scenario["student_ids"]:
            student = validate_success(api.get_student(student_id, registrar))
            assert_money(student["bursar_balance_cents"], 0)


class TestSegregationBeatsConcurrentCapacity:
    """The safety rule answers first; a clean approver then hits the capacity rule."""

    @staticmethod
    def _section_at_capacity_with_a_second_submitted_adoption(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-01T00:00:00Z", bands=((1, 2, 9000),)
        )
        section = fixtures.create_section(api, catalog["term_id"], **MATH_SECTION)
        first = fixtures.create_approved_adoption(
            api, section["id"], catalog["title_id"], section["version"],
            instructor_user_id="fac-3", approver_user_id="pa-1",
        )

        second_title, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, 2, 6000),), **SECOND_TITLE
        )
        fixtures.set_clock(api, "2026-07-10T09:00:00Z")
        candidate = fixtures.create_adoption(
            api, section["id"], second_title["id"], instructor_user_id="fac-3",
            access_start_date="2026-09-01", access_end_date="2026-11-01",
        )
        fixtures.submit_adoption(api, candidate["id"], "fac-3")

        return {
            "section_id": section["id"],
            "approved_id": first["id"],
            "candidate_id": candidate["id"],
        }

    def test_self_approval_is_refused_before_capacity_is_computed(self, api):
        """PRD §3.3: "It is a `ProgramAdmin` action and requires all of the
        following: the adoption is `SUBMITTED`; the approving operator's
        `X-User-ID` differs from the adoption's `submitted_by_user_id`, since the
        operator who submitted an adoption may never approve it and an attempt is
        rejected with `ERR_SEGREGATION_OF_DUTIES`; the term is `PLANNING` or
        `OPEN`, else `ERR_TERM_NOT_OPEN`; the adopted title is `ACTIVE`, else
        `ERR_TITLE_WITHDRAWN`; the agreement pricing that title is `ACTIVE`, else
        `ERR_AGREEMENT_NOT_ACTIVE`; that agreement's coverage brackets the whole
        term, meaning `effective_from` is on or before the term's
        `term_start_date` and `effective_to` is strictly after the term's
        `term_end_date`, else `ERR_AGREEMENT_WINDOW_MISMATCH`; the adopted title
        carries at least one pricing band, else `ERR_NO_PRICING_TIER` — note that
        no enrollment count exists yet at approval time, so approval only checks
        that *some* band exists, not that a band covers a particular count; and
        concurrent-title capacity holds."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_segregation_of_duties_beats_concurrent_title_limit
        """
        scenario = self._section_at_capacity_with_a_second_submitted_adoption(api)

        # fac-3 both submitted this adoption and would breach the capacity of 1.
        response = api.approve_adoption(
            scenario["candidate_id"], make_program_admin_headers("fac-3")
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)

        candidate = fixtures.read_adoption(api, scenario["candidate_id"])
        assert candidate["status"] == AdoptionStatus.SUBMITTED.value
        assert candidate["locked_list_price_cents"] is None
        assert candidate["approved_by_user_id"] is None

    def test_clean_approver_then_meets_the_concurrent_title_limit(self, api,
                                                                 program_admin):
        """PRD §3.3: "If that count exceeds the section's `max_concurrent_titles`
        on any single date, the approval is rejected with
        `ERR_CONCURRENT_TITLE_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_segregation_of_duties_beats_concurrent_title_limit
        """
        scenario = self._section_at_capacity_with_a_second_submitted_adoption(api)

        api.approve_adoption(scenario["candidate_id"],
                             make_program_admin_headers("fac-3"))

        # Every date in [2026-09-01, 2026-11-01) already carries one approved
        # window, so including the candidate the count would be 2 against a cap of 1.
        response = api.approve_adoption(scenario["candidate_id"], program_admin)
        validate_error(response, ApiErrorId.CONCURRENT_TITLE_LIMIT.value)

        candidate = fixtures.read_adoption(api, scenario["candidate_id"])
        assert candidate["status"] == AdoptionStatus.SUBMITTED.value

        approved = fixtures.read_adoption(api, scenario["approved_id"])
        assert approved["status"] == AdoptionStatus.APPROVED.value

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
        assert section["max_concurrent_titles"] == 1
