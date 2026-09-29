"""Rule violations mapped to their exact rejection codes, and the boundary case on
the legal side of each rule: the two term gates, the posting posture gates, duplicate
posting, enrollment and drop date ranges, the six business keys, re-enrolment after a
drop, the faculty deadline and supersede-target tests, the approval-time title and
agreement gates, access-window validity, the opt-out window instant, settlement's term
gate and the disclosure filing deadline.
"""

from test_helpers import (
    AcademicTermStatus,
    AccessStatus,
    AdoptionStatus,
    ApiErrorId,
    BillingStatus,
    ComplianceStatus,
    CourseMaterialTitleStatus,
    DisclosureReportStatus,
    EnrollmentStatus,
    OptOutRequestStatus,
    ReconciliationRunStatus,
    ReconciliationStatus,
    RegistrationType,
    SectionIaStatus,
    assert_money,
    assert_ratio,
    factories,
    fixtures,
    make_faculty_headers,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ONE_STUDENT = fixtures.DEFAULT_STUDENTS[:1]
SINGLE_BAND = ((1, 2, 9000),)
ESSENTIALS_TITLE = {
    "isbn": "978-0-11-000005-0",
    "title": "Economics Essentials",
    "list_price_cents": 12000,
}
INTERACTIVE_TITLE = {
    "isbn": "978-0-11-000002-0",
    "title": "Economics Interactive",
    "list_price_cents": 15000,
}
STATISTICS_TITLE = {
    "isbn": "978-0-11-000004-0",
    "title": "Applied Statistics",
    "list_price_cents": 16000,
}
LATIMER_AGREEMENT = {
    "publisher_name": "Latimer Learning",
    "agreement_code": "PUB-B",
    "max_list_price_pct": 0.80,
}
COTSWOLD_AGREEMENT = {
    "publisher_name": "Cotswold Press",
    "agreement_code": "PUB-C",
    "effective_from": "2026-08-01",
    "effective_to": "2026-12-11",
}
SECOND_SECTION = {"section_number": "002", "instructor_user_id": "fac-2"}
THIRD_SECTION = {"section_number": "003", "instructor_user_id": "fac-3"}


class TestTheTwoTermGatesAreDifferentRules:
    """Flagging demands `OPEN`; submission and approval also admit `PLANNING`."""

    @staticmethod
    def _planning_term_with_a_draft_adoption(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", open_term_now=False,
            bands=SINGLE_BAND,
        )
        essentials, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, None, 6000),), **ESSENTIALS_TITLE
        )
        section = fixtures.create_section(api, catalog["term_id"])
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )
        return {
            "term_id": catalog["term_id"],
            "section_id": section["id"],
            "adoption_id": adoption["id"],
            "essentials_id": essentials["id"],
        }

    def test_flagging_is_refused_in_planning_before_and_after_the_approval(
            self, api, program_admin):
        """PRD §3.1: "Section flagging, enrollment and charge posting all require an
        `OPEN` term."

        Design: Corner/validations/validation_term_workflow_gate_blocks_flagging_and_submission
        """
        scenario = self._planning_term_with_a_draft_adoption(api)

        response = api.flag_section_inclusive_access(scenario["section_id"],
                                                    program_admin)
        validate_error(response, ApiErrorId.TERM_NOT_OPEN.value)

        # §3.3: submission and approval admit PLANNING as well as OPEN.
        fixtures.submit_adoption(api, scenario["adoption_id"])
        approved = fixtures.approve_adoption(api, scenario["adoption_id"])
        assert approved["status"] == AdoptionStatus.APPROVED.value

        # Satisfying the approval gate does not satisfy the term gate.
        response = api.flag_section_inclusive_access(scenario["section_id"],
                                                    program_admin)
        validate_error(response, ApiErrorId.TERM_NOT_OPEN.value)
        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
        assert section["inclusive_access_flag"] is False

        fixtures.open_term(api, scenario["term_id"])
        flagged = fixtures.flag_section(api, scenario["section_id"])
        assert flagged["ia_status"] == SectionIaStatus.FLAGGED.value
        assert flagged["inclusive_access_flag"] is True

        term = fixtures.read_term(api, scenario["term_id"])
        assert term["status"] == AcademicTermStatus.OPEN.value
        assert term["ia_section_count"] == 1

    def test_a_locked_term_reports_the_money_gate_for_posting_and_the_workflow_gate_for_submission(
            self, api, bursar_officer):
        """PRD §3.1: "Locking simultaneously freezes student-facing money: from that
        point on, batch charge posting, single charge posting, filing an opt-out,
        rescinding one and re-filing one are all rejected with
        `ERR_TERM_BILLING_LOCKED`, and the same rejection applies once the term is
        `CLOSED`."

        Design: Corner/validations/validation_term_workflow_gate_blocks_flagging_and_submission
        """
        scenario = self._planning_term_with_a_draft_adoption(api)
        fixtures.submit_adoption(api, scenario["adoption_id"])
        fixtures.approve_adoption(api, scenario["adoption_id"])
        fixtures.open_term(api, scenario["term_id"])
        fixtures.flag_section(api, scenario["section_id"])

        locked = fixtures.lock_term_billing(api, scenario["term_id"])
        assert locked["status"] == AcademicTermStatus.BILLING_LOCKED.value

        # The section is FLAGGED, so the money gate is what refuses the posting.
        response = api.post_section_charges(scenario["section_id"], bursar_officer)
        validate_error(response, ApiErrorId.TERM_BILLING_LOCKED.value)

        # Authoring a draft adoption is not term-gated at all.
        successor = validate_success(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["essentials_id"],
                    fixtures.section_version(api, scenario["section_id"]),
                ),
                make_faculty_headers("fac-1"),
            ),
            expected_status=201,
        )
        assert successor["status"] == AdoptionStatus.DRAFT.value

        response = api.submit_adoption(successor["id"], make_faculty_headers("fac-1"))
        validate_error(response, ApiErrorId.TERM_NOT_OPEN.value)
        assert fixtures.read_adoption(api, successor["id"])["status"] == \
            AdoptionStatus.DRAFT.value

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.FLAGGED.value
        assert section["billing_basis_enrollment_count"] is None


class TestPostingPostureAndApprovalGates:
    """Posting reports the posture; flagging reports the missing approval."""

    @staticmethod
    def _unflagged_section_with_a_draft_adoption_and_one_enrollment(api):
        # The adoption is deliberately still DRAFT when the clock reaches day one,
        # so the term's adoption deadline is set past that instant: this scenario
        # exercises the flagging gate, not PRD §3.3's submission deadline.
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", bands=SINGLE_BAND,
            term_overrides={"adoption_deadline_date": "2026-09-01"},
        )
        section = fixtures.create_section(api, catalog["term_id"])
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )
        peer = fixtures.create_section(api, catalog["term_id"], **SECOND_SECTION)

        roster = fixtures.enroll_roster(api, section["id"], ONE_STUDENT)
        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        return {
            "section_id": section["id"],
            "peer_id": peer["id"],
            "adoption_id": adoption["id"],
            "enrollment_id": roster["enrollment_ids"][0],
            "student_id": roster["student_ids"][0],
        }

    def test_both_posting_shapes_refuse_a_section_that_is_not_flagged(
            self, api, bursar_officer):
        """PRD §3.5: "Both forms require the section's `ia_status` to be `FLAGGED` or
        `BILLED` (else `ERR_SECTION_NOT_FLAGGED`), at least one approved adoption on
        the section (else `ERR_ADOPTION_NOT_APPROVED`), an `ACTIVE` pricing agreement
        (else `ERR_AGREEMENT_NOT_ACTIVE`), and an `OPEN` term (else
        `ERR_TERM_BILLING_LOCKED`)."

        Design: Corner/validations/validation_posting_requires_flagged_section_and_approved_adoption
        """
        scenario = self._unflagged_section_with_a_draft_adoption_and_one_enrollment(api)

        # The deeper cause is the missing approval, but the posture gate outranks it.
        response = api.post_section_charges(scenario["section_id"], bursar_officer)
        validate_error(response, ApiErrorId.SECTION_NOT_FLAGGED.value)

        response = api.post_enrollment_charge(scenario["enrollment_id"], bursar_officer)
        validate_error(response, ApiErrorId.SECTION_NOT_FLAGGED.value)

        _, meta = validate_paginated(
            api.list_enrollment_charges(scenario["enrollment_id"], bursar_officer)
        )
        assert meta["total_count"] == 0
        assert_money(fixtures.student_balance(api, scenario["student_id"]), 0)

    def test_flagging_reports_the_missing_approval_and_then_the_same_posting_succeeds(
            self, api, program_admin):
        """PRD §3.5: "A `ProgramAdmin` moves the section `NOT_FLAGGED` → `FLAGGED`,
        which requires that the section is currently `NOT_FLAGGED`, that at least one
        adoption on it is `APPROVED` (else `ERR_ADOPTION_NOT_APPROVED`), that for
        every such approved adoption the adopted title is `ACTIVE` (else
        `ERR_TITLE_WITHDRAWN`) and the agreement pricing that title is `ACTIVE` (else
        `ERR_AGREEMENT_NOT_ACTIVE`), and that the term is `OPEN` (else
        `ERR_TERM_NOT_OPEN`)."

        Design: Corner/validations/validation_posting_requires_flagged_section_and_approved_adoption
        """
        scenario = self._unflagged_section_with_a_draft_adoption_and_one_enrollment(api)

        # A section with no adoption row at all, and one whose adoption is DRAFT.
        response = api.flag_section_inclusive_access(scenario["peer_id"], program_admin)
        validate_error(response, ApiErrorId.ADOPTION_NOT_APPROVED.value)
        response = api.flag_section_inclusive_access(scenario["section_id"],
                                                    program_admin)
        validate_error(response, ApiErrorId.ADOPTION_NOT_APPROVED.value)

        fixtures.submit_adoption(api, scenario["adoption_id"])
        fixtures.approve_adoption(api, scenario["adoption_id"])
        flagged = fixtures.flag_section(api, scenario["section_id"])
        assert flagged["ia_status"] == SectionIaStatus.FLAGGED.value

        charges = fixtures.post_section_charges(api, scenario["section_id"])
        assert len(charges) == 1
        assert_money(charges[0]["gross_price_cents"], 9450)
        assert charges[0]["billing_status"] == BillingStatus.POSTED.value
        assert charges[0]["access_status"] == AccessStatus.PROVISIONED.value

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.BILLED.value
        assert section["billing_basis_enrollment_count"] == 1

        peer = fixtures.read_section(api, scenario["peer_id"])
        assert peer["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
        assert peer["billing_basis_enrollment_count"] is None


class TestDuplicatePostingGuards:
    """The two posting shapes refuse a re-post for two different reasons."""

    @staticmethod
    def _billed_section_with_one_uncharged_late_arrival(api):
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-05T00:00:00Z", roster=ONE_STUDENT
        )
        newcomer = fixtures.create_student(api, "S-1002", "Ben Ortiz")
        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        enrollment = fixtures.create_enrollment(
            api, scenario["section_id"], newcomer["id"], "2026-08-26"
        )
        scenario["newcomer_id"] = newcomer["id"]
        scenario["newcomer_enrollment_id"] = enrollment["id"]
        return scenario

    def test_the_single_endpoint_refuses_an_enrollment_that_is_already_charged(
            self, api, bursar_officer):
        """PRD §3.5: "The single form, available to the same two roles, posts exactly
        one charge for one named enrollment and is the normal path for a late
        registrant; it is rejected with `ERR_CHARGE_ALREADY_EXISTS` when that
        enrollment already carries a charge on the section's currently approved
        adoption whose `billing_status` is any of `POSTED`, `PARTIALLY_REFUNDED`,
        `REFUNDED` or `REBILLED`, and rejected with `ERR_ENROLLMENT_NOT_ACTIVE` when
        the enrollment has been dropped."

        Design: Corner/validations/validation_duplicate_posting_guards_batch_and_single
        """
        scenario = self._billed_section_with_one_uncharged_late_arrival(api)

        response = api.post_enrollment_charge(scenario["enrollment_ids"][0],
                                             bursar_officer)
        validate_error(response, ApiErrorId.CHARGE_ALREADY_EXISTS.value)

        # The uncharged newcomer is still postable, priced against the frozen basis.
        charge = fixtures.post_single_charge(api, scenario["newcomer_enrollment_id"])
        assert_money(charge["gross_price_cents"], 9450)
        assert_ratio(charge["proration_pct"], 1.0000)
        assert_money(charge["billed_amount_cents"], 9450)
        assert_money(charge["publisher_share_cents"], 8316)
        assert charge["billing_status"] == BillingStatus.POSTED.value

        response = api.post_enrollment_charge(scenario["newcomer_enrollment_id"],
                                              bursar_officer)
        validate_error(response, ApiErrorId.CHARGE_ALREADY_EXISTS.value)

    def test_the_batch_endpoint_has_nothing_left_to_post(self, api, bursar_officer):
        """PRD §3.5: "If no such uncharged enrolled student exists — because every
        enrolled student is already charged, or because the section has no enrolled
        student at all — the request is rejected with `ERR_NO_BILLABLE_CHARGES`."

        Design: Corner/validations/validation_duplicate_posting_guards_batch_and_single
        """
        scenario = self._billed_section_with_one_uncharged_late_arrival(api)
        fixtures.post_single_charge(api, scenario["newcomer_enrollment_id"])

        response = api.post_section_charges(scenario["section_id"], bursar_officer)
        validate_error(response, ApiErrorId.NO_BILLABLE_CHARGES.value)

        _, meta = validate_paginated(
            api.list_charges(bursar_officer, {"adoption_id": scenario["adoption_id"]})
        )
        assert meta["total_count"] == 2

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 2
        assert section["provisioned_access_count"] == 2
        assert_ratio(section["participation_rate"], 1.0000)
        assert section["billing_basis_enrollment_count"] == 1
        assert section["first_posted_at"] == "2026-08-24T09:00:00.000Z"

        assert_money(fixtures.student_balance(api, scenario["newcomer_id"]), 9450)


class TestEnrollmentAndDropDateRanges:
    """The thirty-day pre-term window and the drop ordering share one error id."""

    @staticmethod
    def _open_term_with_a_section_and_two_students(api):
        fixtures.set_clock(api, "2026-08-01T00:00:00Z")
        term = fixtures.create_term(api)
        fixtures.open_term(api, term["id"])
        section = fixtures.create_section(api, term["id"])
        students = fixtures.create_students(api, fixtures.DEFAULT_STUDENTS[:2])
        return {
            "term_id": term["id"],
            "section_id": section["id"],
            "student_ids": [student["id"] for student in students],
        }

    def test_the_earliest_legal_registration_date_is_inclusive(self, api, registrar):
        """PRD §3.4: "First, `enrolled_on` must not be earlier than thirty days
        before the term's `term_start_date`, and on a later drop the supplied
        `dropped_on` must not be earlier than the enrollment's `enrolled_on`; either
        violation is rejected with `ERR_ENROLLMENT_DATE_OUT_OF_RANGE`."

        Design: Corner/validations/validation_enrollment_and_drop_date_range_boundaries
        """
        scenario = self._open_term_with_a_section_and_two_students(api)

        # The term starts 2026-08-24, so 2026-07-25 is the earliest legal date.
        response = api.create_enrollment(
            factories.enrollment_payload(scenario["section_id"],
                                         scenario["student_ids"][0], "2026-07-24"),
            registrar,
        )
        validate_error(response, ApiErrorId.ENROLLMENT_DATE_OUT_OF_RANGE.value)

        _, meta = validate_paginated(
            api.list_section_enrollments(scenario["section_id"], registrar)
        )
        assert meta["total_count"] == 0

        first = fixtures.create_enrollment(
            api, scenario["section_id"], scenario["student_ids"][0], "2026-07-25"
        )
        assert first["enrolled_on"] == "2026-07-25"
        assert first["registration_type"] == RegistrationType.REGULAR.value
        assert first["status"] == EnrollmentStatus.ENROLLED.value

        second = fixtures.create_enrollment(
            api, scenario["section_id"], scenario["student_ids"][1], "2026-08-24"
        )
        assert second["registration_type"] == RegistrationType.REGULAR.value

    def test_a_drop_on_the_registration_date_itself_is_legal_and_one_day_earlier_is_not(
            self, api, registrar, bursar_officer):
        """PRD §3.7: "The enrollment must currently be `ENROLLED`, `dropped_on` must
        not be earlier than `enrolled_on`, and the term must be `OPEN` or
        `BILLING_LOCKED`."

        Design: Corner/validations/validation_enrollment_and_drop_date_range_boundaries
        """
        scenario = self._open_term_with_a_section_and_two_students(api)
        first = fixtures.create_enrollment(
            api, scenario["section_id"], scenario["student_ids"][0], "2026-07-25"
        )
        fixtures.create_enrollment(
            api, scenario["section_id"], scenario["student_ids"][1], "2026-08-24"
        )

        response = api.drop_enrollment(first["id"],
                                      factories.drop_payload("2026-07-24"), registrar)
        validate_error(response, ApiErrorId.ENROLLMENT_DATE_OUT_OF_RANGE.value)

        untouched = fixtures.read_enrollment(api, first["id"])
        assert untouched["status"] == EnrollmentStatus.ENROLLED.value
        assert untouched["dropped_on"] is None

        dropped = fixtures.drop_enrollment(api, first["id"], "2026-07-25")
        assert dropped["status"] == EnrollmentStatus.DROPPED.value
        assert dropped["dropped_on"] == "2026-07-25"

        # The refund path had nothing to reverse: this enrollment never carried a charge.
        _, meta = validate_paginated(
            api.list_enrollment_charges(first["id"], bursar_officer)
        )
        assert meta["total_count"] == 0

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 1
        assert_ratio(section["participation_rate"], 0.0000)


class TestBusinessKeyUniqueness:
    """One error id for six keys, and the composite keys are composites."""

    @staticmethod
    def _one_row_behind_each_of_the_six_keys(api):
        fixtures.set_clock(api, "2026-07-05T00:00:00Z")
        term = fixtures.create_term(api)
        northgate = fixtures.create_agreement(api)
        latimer = fixtures.create_agreement(api, **LATIMER_AGREEMENT)
        title = fixtures.create_title(api, northgate["id"])
        section = fixtures.create_section(api, term["id"])
        student = fixtures.create_student(api)
        report = fixtures.create_disclosure_report(api, term["id"], "CA")
        return {
            "term_id": term["id"],
            "northgate_id": northgate["id"],
            "latimer_id": latimer["id"],
            "title_id": title["id"],
            "section_id": section["id"],
            "student_id": student["id"],
            "report_id": report["id"],
        }

    def test_every_exact_key_repeat_is_refused_with_the_same_code(
            self, api, program_admin, registrar, compliance_officer):
        """PRD §3.4: "Business keys are enforced across this and the preceding
        subsections with a single rejection code, `ERR_DUPLICATE_RESOURCE_KEY`: a
        term's `code`, an agreement's `agreement_code`, a student's `external_id`,
        the pairing of agreement and `isbn` on a title, the four-part pairing of
        term, subject code, catalog number and section number on a section, and the
        pairing of term and `reporting_state_code` on a disclosure report must each
        be unique."

        Design: Corner/validations/validation_business_key_uniqueness_rejected
        """
        scenario = self._one_row_behind_each_of_the_six_keys(api)

        validate_error(
            api.create_term(factories.term_payload(name="Fall 2026 duplicate"),
                            program_admin),
            ApiErrorId.DUPLICATE_RESOURCE_KEY.value,
        )
        validate_error(
            api.create_agreement(
                factories.agreement_payload(
                    publisher_name="Northgate Academic Duplicate"),
                program_admin),
            ApiErrorId.DUPLICATE_RESOURCE_KEY.value,
        )
        validate_error(
            api.create_student(
                factories.student_payload("S-1001", "Ada Lin Duplicate",
                                          email="ada-duplicate@campus.edu"),
                registrar),
            ApiErrorId.DUPLICATE_RESOURCE_KEY.value,
        )
        validate_error(
            api.create_title(
                factories.title_payload(
                    scenario["northgate_id"],
                    title="Principles of Economics Reprint",
                    list_price_cents=19000, format="DIGITAL_PLUS_PRINT"),
                program_admin),
            ApiErrorId.DUPLICATE_RESOURCE_KEY.value,
        )
        validate_error(
            api.create_section(
                factories.section_payload(scenario["term_id"],
                                         instructor_user_id="fac-9",
                                         max_concurrent_titles=3),
                registrar),
            ApiErrorId.DUPLICATE_RESOURCE_KEY.value,
        )
        validate_error(
            api.create_disclosure_report(
                factories.disclosure_report_payload(scenario["term_id"], "CA"),
                compliance_officer),
            ApiErrorId.DUPLICATE_RESOURCE_KEY.value,
        )

        _, terms_meta = validate_paginated(api.list_terms(program_admin))
        assert terms_meta["total_count"] == 1
        _, agreements_meta = validate_paginated(api.list_agreements(program_admin))
        assert agreements_meta["total_count"] == 2
        _, students_meta = validate_paginated(api.list_students(registrar))
        assert students_meta["total_count"] == 1

    def test_the_composite_keys_leave_room_for_a_second_row(
            self, api, program_admin, registrar, compliance_officer):
        """PRD §3.2: "A title has an `isbn` that must be unique within its agreement,
        a printed `title` string, a `list_price_cents` that must be greater than 0 —
        this is the savings baseline the state disclosure compares against — and a
        `format` that is either `DIGITAL` or `DIGITAL_PLUS_PRINT`."

        Design: Corner/validations/validation_business_key_uniqueness_rejected
        """
        scenario = self._one_row_behind_each_of_the_six_keys(api)

        # The same ISBN under a different agreement is a different key.
        twin = validate_success(
            api.create_title(
                factories.title_payload(
                    scenario["latimer_id"],
                    title="Principles of Economics Reprint",
                    list_price_cents=19000, format="DIGITAL_PLUS_PRINT"),
                program_admin),
            expected_status=201,
        )
        assert twin["isbn"] == "978-0-11-000001-0"
        assert twin["agreement_id"] == scenario["latimer_id"]

        # §3.3: only the full four-part section key is unique.
        peer = validate_success(
            api.create_section(
                factories.section_payload(scenario["term_id"], section_number="002",
                                          instructor_user_id="fac-9",
                                          max_concurrent_titles=3),
                registrar),
            expected_status=201,
        )
        assert peer["section_number"] == "002"

        # §3.9: only the pairing of term and state code is unique.
        oregon = validate_success(
            api.create_disclosure_report(
                factories.disclosure_report_payload(scenario["term_id"], "OR"),
                compliance_officer),
            expected_status=201,
        )
        assert oregon["reporting_state_code"] == "OR"
        assert oregon["status"] == DisclosureReportStatus.DRAFT.value
        assert oregon["compliance_status"] == ComplianceStatus.NOT_APPLICABLE.value

        titles, titles_meta = validate_paginated(
            api.list_titles(program_admin, {"agreement_id": scenario["northgate_id"]})
        )
        assert titles_meta["total_count"] == 1
        assert_money(titles[0]["list_price_cents"], 18000)
        assert titles[0]["format"] == "DIGITAL"

        _, reports_meta = validate_paginated(
            api.list_term_disclosure_reports(scenario["term_id"], compliance_officer)
        )
        assert reports_meta["total_count"] == 2
        assert fixtures.read_report(api, scenario["report_id"])["amendment_count"] == 0


class TestReEnrolmentAfterADrop:
    """The uniqueness rule is scoped to the `ENROLLED` rows only."""

    def test_the_dropped_row_no_longer_occupies_the_slot(self, api, registrar):
        """PRD §3.4: "At most one enrollment with status `ENROLLED` may exist for any
        given pair of section and student, and a duplicate is rejected with
        `ERR_DUPLICATE_ENROLLMENT` — a student who dropped and re-registers is fine,
        because the dropped row no longer occupies the slot."

        Design: Corner/validations/validation_reenrollment_allowed_after_drop
        """
        fixtures.set_clock(api, "2026-07-05T00:00:00Z")
        term = fixtures.create_term(api)
        fixtures.open_term(api, term["id"])
        section = fixtures.create_section(api, term["id"])
        student = fixtures.create_student(api)
        fixtures.set_clock(api, "2026-08-24T08:00:00Z")
        first = fixtures.create_enrollment(api, section["id"], student["id"],
                                          "2026-08-24")

        response = api.create_enrollment(
            factories.enrollment_payload(section["id"], student["id"], "2026-08-25"),
            registrar,
        )
        validate_error(response, ApiErrorId.DUPLICATE_ENROLLMENT.value)

        dropped = fixtures.drop_enrollment(api, first["id"], "2026-08-28")
        assert dropped["status"] == EnrollmentStatus.DROPPED.value
        assert dropped["dropped_on"] == "2026-08-28"

        again = fixtures.create_enrollment(api, section["id"], student["id"],
                                           "2026-08-31")
        assert again["id"] != first["id"]
        assert again["status"] == EnrollmentStatus.ENROLLED.value
        assert again["enrolled_on"] == "2026-08-31"
        assert again["registration_type"] == RegistrationType.REGULAR.value

        # The rule bites again on the new ENROLLED row.
        response = api.create_enrollment(
            factories.enrollment_payload(section["id"], student["id"], "2026-09-01"),
            registrar,
        )
        validate_error(response, ApiErrorId.DUPLICATE_ENROLLMENT.value)

        _, all_meta = validate_paginated(
            api.list_section_enrollments(section["id"], registrar)
        )
        assert all_meta["total_count"] == 2
        _, live_meta = validate_paginated(
            api.list_section_enrollments(section["id"], registrar,
                                        {"status": EnrollmentStatus.ENROLLED.value})
        )
        assert live_meta["total_count"] == 1

        refreshed = fixtures.read_section(api, section["id"])
        assert refreshed["enrolled_count"] == 1
        assert_ratio(refreshed["participation_rate"], 0.0000)


class TestFacultyDeadlineAndSupersedeTargets:
    """The deadline day is inclusive, and a title change is exempt from it."""

    @staticmethod
    def _approved_adoption_submitted_on_the_deadline_day(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-15T12:00:00Z", bands=SINGLE_BAND
        )
        interactive, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, None, 7000),), **INTERACTIVE_TITLE
        )
        section = fixtures.create_section(api, catalog["term_id"])
        approved = fixtures.create_approved_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )
        peer = fixtures.create_section(api, catalog["term_id"], **SECOND_SECTION)
        return {
            "section_id": section["id"],
            "peer_id": peer["id"],
            "approved_id": approved["id"],
            "first_title_id": catalog["title_id"],
            "interactive_id": interactive["id"],
        }

    def test_an_original_submission_one_day_late_is_refused(self, api):
        """PRD §3.3: "Only the `Faculty` operator whose `X-User-ID` equals the
        section's `instructor_user_id` may submit, the term must be either `PLANNING`
        or `OPEN`, and — for an original adoption, meaning one whose
        `supersedes_adoption_id` is null — the current logical date must be on or
        before the term's `adoption_deadline_date`, with a later submission rejected
        as `ERR_ADOPTION_DEADLINE_PASSED`."

        Design: Corner/validations/validation_adoption_deadline_boundary_and_supersede_target_checks
        """
        scenario = self._approved_adoption_submitted_on_the_deadline_day(api)

        # The deadline day itself is legal: 2026-07-15 is the adoption deadline.
        approved = fixtures.read_adoption(api, scenario["approved_id"])
        assert approved["status"] == AdoptionStatus.APPROVED.value
        assert approved["submitted_at"] == "2026-07-15T12:00:00.000Z"

        fixtures.set_clock(api, "2026-07-16T00:00:00Z")
        # Authoring is never deadline-gated.
        late = fixtures.create_adoption(api, scenario["section_id"],
                                       scenario["interactive_id"])
        assert late["status"] == AdoptionStatus.DRAFT.value

        response = api.submit_adoption(late["id"], make_faculty_headers("fac-1"))
        validate_error(response, ApiErrorId.ADOPTION_DEADLINE_PASSED.value)

        refused = fixtures.read_adoption(api, late["id"])
        assert refused["status"] == AdoptionStatus.DRAFT.value
        assert refused["submitted_at"] is None
        assert refused["submitted_by_user_id"] is None

    def test_all_three_ways_of_naming_a_bad_supersede_target_share_one_code(
            self, api, program_admin):
        """PRD §3.3: "When `supersedes_adoption_id` is supplied it must reference an
        adoption on the same section that is currently `APPROVED` and whose
        `title_id` differs from the candidate's — pointing at another section, at a
        non-approved adoption, or at the same title is rejected with
        `ERR_SUPERSEDE_TARGET_INVALID`."

        Design: Corner/validations/validation_adoption_deadline_boundary_and_supersede_target_checks
        """
        scenario = self._approved_adoption_submitted_on_the_deadline_day(api)
        fixtures.set_clock(api, "2026-07-16T00:00:00Z")
        draft = fixtures.create_adoption(api, scenario["section_id"],
                                        scenario["interactive_id"])

        owner = make_faculty_headers("fac-1")
        # The target is DRAFT, not APPROVED.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["interactive_id"],
                    fixtures.section_version(api, scenario["section_id"]),
                    supersedes_adoption_id=draft["id"]),
                owner),
            ApiErrorId.SUPERSEDE_TARGET_INVALID.value,
        )
        # The target carries the candidate's own title.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["first_title_id"],
                    fixtures.section_version(api, scenario["section_id"]),
                    supersedes_adoption_id=scenario["approved_id"]),
                owner),
            ApiErrorId.SUPERSEDE_TARGET_INVALID.value,
        )
        # The target sits on another section.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["peer_id"], scenario["interactive_id"],
                    fixtures.section_version(api, scenario["peer_id"]),
                    supersedes_adoption_id=scenario["approved_id"]),
                make_faculty_headers("fac-2")),
            ApiErrorId.SUPERSEDE_TARGET_INVALID.value,
        )

        successor = fixtures.create_adoption(
            api, scenario["section_id"], scenario["interactive_id"],
            supersedes_adoption_id=scenario["approved_id"],
        )
        assert successor["supersedes_adoption_id"] == scenario["approved_id"]
        assert successor["status"] == AdoptionStatus.DRAFT.value
        assert successor["requires_rebill"] is False

        # A superseding adoption is deliberately exempt from the faculty deadline.
        submitted = fixtures.submit_adoption(api, successor["id"])
        assert submitted["status"] == AdoptionStatus.SUBMITTED.value
        assert submitted["submitted_at"] == "2026-07-16T00:00:00.000Z"

        _, meta = validate_paginated(
            api.list_section_adoptions(scenario["section_id"], program_admin)
        )
        assert meta["total_count"] == 3


class TestApprovalTimeTitleAndAgreementGates:
    """Three independent approval-time gates, plus the withdrawal gate in reverse."""

    @staticmethod
    def _one_billed_section_and_two_submitted_adoptions(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-10T09:00:00Z", bands=SINGLE_BAND
        )
        interactive, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, None, 7000),), **INTERACTIVE_TITLE
        )
        cotswold = fixtures.create_agreement(api, **COTSWOLD_AGREEMENT)
        statistics, _ = fixtures.create_priced_title(
            api, cotswold["id"], ((1, None, 8000),), **STATISTICS_TITLE
        )
        fixtures.activate_agreement(api, cotswold["id"])

        billed = fixtures.add_section(api, catalog)

        peer = fixtures.create_section(api, catalog["term_id"], **SECOND_SECTION)
        peer_adoption = fixtures.create_adoption(
            api, peer["id"], interactive["id"], peer["version"],
            instructor_user_id="fac-2",
        )
        fixtures.submit_adoption(api, peer_adoption["id"], "fac-2")

        third = fixtures.create_section(api, catalog["term_id"], **THIRD_SECTION)
        third_adoption = fixtures.create_adoption(
            api, third["id"], statistics["id"], third["version"],
            instructor_user_id="fac-3",
        )
        fixtures.submit_adoption(api, third_adoption["id"], "fac-3")

        roster = fixtures.enroll_roster(api, billed["section_id"], ONE_STUDENT)
        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        charges = fixtures.post_section_charges(api, billed["section_id"])
        fixtures.set_clock(api, "2026-08-24T10:00:00Z")

        return {
            "agreement_id": catalog["agreement_id"],
            "billed_section_id": billed["section_id"],
            "billed_title_id": catalog["title_id"],
            "interactive_id": interactive["id"],
            "peer_adoption_id": peer_adoption["id"],
            "third_section_id": third["id"],
            "third_adoption_id": third_adoption["id"],
            "charge_id": charges[0]["id"],
            "student_id": roster["student_ids"][0],
        }

    def test_a_title_withdrawn_under_a_submitted_adoption_blocks_its_approval(
            self, api, program_admin):
        """PRD §3.2: "Withdrawal increments the title's `version`, and from then on
        both adoption approval and section flagging touching that title are rejected
        with `ERR_TITLE_WITHDRAWN`."

        Design: Corner/validations/validation_approval_gates_title_state_and_agreement_window
        """
        scenario = self._one_billed_section_and_two_submitted_adoptions(api)

        # Withdrawal is allowed while the adoption is only SUBMITTED.
        withdrawn = fixtures.withdraw_title(api, scenario["interactive_id"])
        assert withdrawn["status"] == CourseMaterialTitleStatus.WITHDRAWN.value

        response = api.approve_adoption(scenario["peer_adoption_id"], program_admin)
        validate_error(response, ApiErrorId.TITLE_WITHDRAWN.value)

        refused = fixtures.read_adoption(api, scenario["peer_adoption_id"])
        assert refused["status"] == AdoptionStatus.SUBMITTED.value
        assert refused["locked_list_price_cents"] is None
        assert refused["approved_by_user_id"] is None

        titles, meta = validate_paginated(
            api.list_agreement_titles(scenario["agreement_id"], program_admin)
        )
        assert meta["total_count"] == 2
        assert sum(1 for title in titles
                   if title["status"] == CourseMaterialTitleStatus.WITHDRAWN.value) == 1

    def test_coverage_must_end_strictly_after_the_term_ends(self, api, program_admin):
        """PRD §3.3: "It is a `ProgramAdmin` action and requires all of the
        following: the adoption is `SUBMITTED`; the approving operator's `X-User-ID`
        differs from the adoption's `submitted_by_user_id`, since the operator who
        submitted an adoption may never approve it and an attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES`; the term is `PLANNING` or `OPEN`, else
        `ERR_TERM_NOT_OPEN`; the adopted title is `ACTIVE`, else
        `ERR_TITLE_WITHDRAWN`; the agreement pricing that title is `ACTIVE`, else
        `ERR_AGREEMENT_NOT_ACTIVE`; that agreement's coverage brackets the whole
        term, meaning `effective_from` is on or before the term's `term_start_date`
        and `effective_to` is strictly after the term's `term_end_date`, else
        `ERR_AGREEMENT_WINDOW_MISMATCH`; the adopted title carries at least one
        pricing band, else `ERR_NO_PRICING_TIER` — note that no enrollment count
        exists yet at approval time, so approval only checks that *some* band exists,
        not that a band covers a particular count; and concurrent-title capacity
        holds."

        Design: Corner/validations/validation_approval_gates_title_state_and_agreement_window
        """
        scenario = self._one_billed_section_and_two_submitted_adoptions(api)

        # PUB-C runs to 2026-12-11, exactly the term's own end date.
        response = api.approve_adoption(scenario["third_adoption_id"], program_admin)
        validate_error(response, ApiErrorId.AGREEMENT_WINDOW_MISMATCH.value)

        refused = fixtures.read_adoption(api, scenario["third_adoption_id"])
        assert refused["status"] == AdoptionStatus.SUBMITTED.value
        assert refused["approved_at"] is None

        section = fixtures.read_section(api, scenario["third_section_id"])
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value

    def test_a_title_students_were_already_charged_for_cannot_be_withdrawn(
            self, api, program_admin):
        """PRD §3.2: "A title students have already been charged for cannot be
        withdrawn — it must be replaced through a superseding adoption instead — and
        an attempt is rejected with `ERR_TITLE_ALREADY_BILLED`."

        Design: Corner/validations/validation_approval_gates_title_state_and_agreement_window
        """
        scenario = self._one_billed_section_and_two_submitted_adoptions(api)

        response = api.withdraw_title(scenario["billed_title_id"], program_admin)
        validate_error(response, ApiErrorId.TITLE_ALREADY_BILLED.value)

        title = validate_success(
            api.get_title(scenario["billed_title_id"], program_admin)
        )
        assert title["status"] == CourseMaterialTitleStatus.ACTIVE.value

        charge = fixtures.read_charge(api, scenario["charge_id"])
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert_money(charge["net_billed_cents"], 9450)

        section = fixtures.read_section(api, scenario["billed_section_id"])
        assert section["ia_status"] == SectionIaStatus.BILLED.value


class TestAccessWindowBoundariesOnAuthoring:
    """A half-open window inside the term, with the exclusive end one day past it."""

    @staticmethod
    def _planning_term_with_an_unpriced_title(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", open_term_now=False,
            bands=(), activate_now=False,
        )
        section = fixtures.create_section(api, catalog["term_id"])
        return {
            "section_id": section["id"],
            "section_version": section["version"],
            "title_id": catalog["title_id"],
        }

    def test_a_zero_length_window_and_a_start_before_the_term_are_both_refused(
            self, api):
        """PRD §3.3: "The access window is validated as a half-open interval inside
        the term: `access_end_date` must be strictly later than `access_start_date`,
        `access_start_date` must not be earlier than the term's `term_start_date`,
        and `access_end_date` must not be later than the day after the term's
        `term_end_date`."

        Design: Corner/validations/validation_access_window_boundaries_on_adoption_create
        """
        scenario = self._planning_term_with_an_unpriced_title(api)
        owner = make_faculty_headers("fac-1")

        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["title_id"],
                    scenario["section_version"],
                    access_start_date="2026-08-24", access_end_date="2026-08-24"),
                owner),
            ApiErrorId.ACCESS_WINDOW_INVALID.value,
        )
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["title_id"],
                    scenario["section_version"],
                    access_start_date="2026-08-23", access_end_date="2026-12-12"),
                owner),
            ApiErrorId.ACCESS_WINDOW_INVALID.value,
        )

        # A rejected create mutates nothing, so the same version is still current.
        assert fixtures.section_version(api, scenario["section_id"]) == \
            scenario["section_version"]

    def test_the_exclusive_end_one_day_past_the_term_is_the_last_legal_one(
            self, api, program_admin):
        """PRD §3.3: "A window failing any of those three tests is rejected with
        `ERR_ACCESS_WINDOW_INVALID`."

        Design: Corner/validations/validation_access_window_boundaries_on_adoption_create
        """
        scenario = self._planning_term_with_an_unpriced_title(api)
        owner = make_faculty_headers("fac-1")

        # The term ends 2026-12-11, so 2026-12-13 reaches two days past it.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["title_id"],
                    scenario["section_version"],
                    access_start_date="2026-08-24", access_end_date="2026-12-13"),
                owner),
            ApiErrorId.ACCESS_WINDOW_INVALID.value,
        )

        accepted = validate_success(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["title_id"],
                    scenario["section_version"],
                    access_start_date="2026-08-24", access_end_date="2026-12-12"),
                owner),
            expected_status=201,
        )
        assert accepted["access_start_date"] == "2026-08-24"
        assert accepted["access_end_date"] == "2026-12-12"
        assert accepted["status"] == AdoptionStatus.DRAFT.value

        _, meta = validate_paginated(
            api.list_section_adoptions(scenario["section_id"], program_admin)
        )
        assert meta["total_count"] == 1


class TestOptOutWindowInstantAndDuplicateOpenRequest:
    """The window closes to the millisecond, and only one request may be open."""

    DEADLINE = "2026-09-04T23:59:59.999Z"
    ONE_MS_LATE = "2026-09-05T00:00:00.000Z"

    @staticmethod
    def _two_day_one_charges_whose_window_ends_at_the_add_drop_deadline(api):
        return fixtures.setup_billed_section(api, setup_clock="2026-07-05T00:00:00Z")

    def test_only_one_submitted_or_granted_request_may_exist_per_charge(
            self, api, bursar_officer):
        """PRD §3.6: "At most one request whose `status` is `SUBMITTED` or `GRANTED`
        may exist per charge at any time, and a second one is rejected with
        `ERR_DUPLICATE_OPT_OUT_OPEN`."

        Design: Corner/validations/validation_opt_out_window_boundary_and_duplicate_open_request
        """
        scenario = self._two_day_one_charges_whose_window_ends_at_the_add_drop_deadline(api)
        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert charge["opt_out_deadline_at"] == self.DEADLINE

        fixtures.set_clock(api, self.DEADLINE)
        filed = fixtures.file_opt_out(api, scenario["charge_ids"][0],
                                     scenario["student_ids"][0], "COST")
        assert filed["status"] == OptOutRequestStatus.SUBMITTED.value
        assert filed["cycle_count"] == 0
        assert_money(filed["refund_amount_cents"], 0)

        response = api.create_opt_out_request(
            factories.opt_out_request_payload(scenario["charge_ids"][0], "OWNS_COPY"),
            make_student_headers(scenario["student_ids"][0]),
        )
        validate_error(response, ApiErrorId.DUPLICATE_OPT_OUT_OPEN.value)

        _, meta = validate_paginated(
            api.list_charge_opt_out_requests(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 1

    def test_one_millisecond_past_the_deadline_closes_both_filing_and_granting(
            self, api, bursar_officer):
        """PRD §3.6: "Filing also requires the enrollment behind the charge to still
        be `ENROLLED` (else `ERR_ENROLLMENT_NOT_ACTIVE`), the current logical instant
        to be at or before the charge's `opt_out_deadline_at` (else
        `ERR_OPT_OUT_WINDOW_CLOSED`), and the term to be `OPEN` (else
        `ERR_TERM_BILLING_LOCKED`)."

        Design: Corner/validations/validation_opt_out_window_boundary_and_duplicate_open_request
        """
        scenario = self._two_day_one_charges_whose_window_ends_at_the_add_drop_deadline(api)
        fixtures.set_clock(api, self.DEADLINE)
        filed = fixtures.file_opt_out(api, scenario["charge_ids"][0],
                                     scenario["student_ids"][0], "COST")

        fixtures.set_clock(api, self.ONE_MS_LATE)
        response = api.create_opt_out_request(
            factories.opt_out_request_payload(scenario["charge_ids"][1], "COST"),
            make_student_headers(scenario["student_ids"][1]),
        )
        validate_error(response, ApiErrorId.OPT_OUT_WINDOW_CLOSED.value)

        _, meta = validate_paginated(
            api.list_charge_opt_out_requests(scenario["charge_ids"][1], bursar_officer)
        )
        assert meta["total_count"] == 0

        # A request filed in time cannot be granted after the window closes.
        response = api.grant_opt_out_request(filed["id"], bursar_officer)
        validate_error(response, ApiErrorId.OPT_OUT_WINDOW_CLOSED.value)
        assert fixtures.read_opt_out(api, filed["id"])["status"] == \
            OptOutRequestStatus.SUBMITTED.value

    def test_a_grant_at_exactly_the_deadline_instant_refunds_the_whole_net(
            self, api, bursar_officer, registrar):
        """PRD §3.6: "The grant records `refund_amount_cents` as the charge's
        `net_billed_cents` observed *before* any refund is applied, together with
        `decided_at` and `decided_by_user_id`."

        Design: Corner/validations/validation_opt_out_window_boundary_and_duplicate_open_request
        """
        scenario = self._two_day_one_charges_whose_window_ends_at_the_add_drop_deadline(api)
        fixtures.set_clock(api, self.DEADLINE)
        filed = fixtures.file_opt_out(api, scenario["charge_ids"][0],
                                     scenario["student_ids"][0], "COST")

        granted = fixtures.grant_opt_out(api, filed["id"])
        assert granted["status"] == OptOutRequestStatus.GRANTED.value
        assert_money(granted["refund_amount_cents"], 9450)
        assert granted["decided_by_user_id"] == "bo-1"
        assert granted["decided_at"] == self.DEADLINE

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert charge["billing_status"] == BillingStatus.REFUNDED.value
        assert charge["access_status"] == AccessStatus.REVOKED.value
        assert_money(charge["refunded_amount_cents"], 9450)
        assert_money(charge["net_billed_cents"], 0)
        assert_money(charge["publisher_share_cents"], 0)

        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 2
        assert_money(sum(entry["amount_cents"] for entry in entries), 0)
        assert_money(fixtures.student_balance(api, scenario["student_ids"][0]), 0)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 2
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 1
        assert_ratio(section["participation_rate"], 0.5000)
        # Exactly one half is still at or above the participation floor.
        assert section["ia_status"] == SectionIaStatus.BILLED.value


class TestSettlementRequiresALockedTerm:
    """The lock is the gate into settlement, and settlement closes the term."""

    @staticmethod
    def _computed_run_and_certified_report_on_an_open_term(api):
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-05T00:00:00Z", bands=SINGLE_BAND,
            roster=ONE_STUDENT,
        )
        fixtures.set_clock(api, "2026-09-10T09:00:00Z")
        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            publisher_reported_count=1, publisher_reported_amount_cents=8316,
        )
        report = fixtures.create_disclosure_report(api, scenario["term_id"], "CA")
        fixtures.set_clock(api, "2026-09-10T10:00:00Z")
        certified = fixtures.certify_report(api, report["id"])

        scenario["run_id"] = run["id"]
        scenario["run"] = run
        scenario["report_id"] = report["id"]
        scenario["certified"] = certified
        return scenario

    def test_an_open_term_refuses_the_settle_even_with_a_zero_variance(
            self, api, program_admin):
        """PRD §3.1: "Locking is the gate into publisher settlement: no
        reconciliation run may be settled until the term is locked, and a settle
        attempt against an unlocked term is rejected with `ERR_TERM_NOT_LOCKED`."

        Design: Corner/validations/validation_settlement_requires_locked_term
        """
        scenario = self._computed_run_and_certified_report_on_an_open_term(api)
        run = scenario["run"]
        assert run["billable_count"] == 1
        assert_money(run["gross_invoice_cents"], 8316)
        assert_money(run["rebate_cents"], 0)
        assert_money(run["settlement_amount_cents"], 8316)
        assert run["count_variance"] == 0
        assert_money(run["variance_cents"], 0)
        assert run["status"] == ReconciliationRunStatus.COMPUTED.value

        # The tolerance gate is satisfied, so the term gate is the reported failure.
        response = api.settle_reconciliation_run(scenario["run_id"], program_admin)
        validate_error(response, ApiErrorId.TERM_NOT_LOCKED.value)

        unchanged = fixtures.read_run(api, scenario["run_id"])
        assert unchanged["status"] == ReconciliationRunStatus.COMPUTED.value
        assert unchanged["settled_at"] is None
        assert unchanged["settled_by_user_id"] is None

    def test_the_computed_branch_writes_the_campus_figure_onto_the_agreement(self, api):
        """PRD §3.8: "Its first hop moves the agreement's `reconciliation_status` to
        `SETTLED` and writes the agreement's `settled_amount_cents` as the run's own
        `settlement_amount_cents` — the campus computation stands."

        Design: Corner/validations/validation_settlement_requires_locked_term
        """
        scenario = self._computed_run_and_certified_report_on_an_open_term(api)
        fixtures.set_clock(api, "2026-09-10T11:00:00Z")
        locked = fixtures.lock_term_billing(api, scenario["term_id"])
        assert locked["status"] == AcademicTermStatus.BILLING_LOCKED.value

        settled = fixtures.settle_run(api, scenario["run_id"])
        assert settled["status"] == ReconciliationRunStatus.SETTLED.value
        assert settled["settled_at"] == "2026-09-10T11:00:00.000Z"
        assert settled["settled_by_user_id"] == "pa-1"

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.SETTLED.value
        assert_money(agreement["settled_amount_cents"], 8316)

        # Settlement moves publisher money, never student money.
        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["publisher_share_cents"], 8316)

    def test_the_same_request_closes_the_term_and_publishes_the_certified_report(
            self, api):
        """PRD §3.8: "From either branch, the second hop moves the term
        `BILLING_LOCKED` → `CLOSED` once every agreement pricing at least one charge
        of that term is `SETTLED`, and the third hop moves every `CERTIFIED`
        disclosure report of that term to `PUBLISHED`."

        Design: Corner/validations/validation_settlement_requires_locked_term
        """
        scenario = self._computed_run_and_certified_report_on_an_open_term(api)
        certified = scenario["certified"]
        assert certified["status"] == DisclosureReportStatus.CERTIFIED.value
        assert certified["charge_count"] == 1
        assert_money(certified["total_list_price_cents"], 18000)
        assert_money(certified["total_net_billed_cents"], 9450)
        assert_money(certified["average_net_cost_cents"], 9450)
        assert_ratio(certified["savings_pct"], 0.4750)
        assert certified["compliance_status"] == ComplianceStatus.COMPLIANT.value

        fixtures.set_clock(api, "2026-09-10T11:00:00Z")
        fixtures.lock_term_billing(api, scenario["term_id"])
        fixtures.settle_run(api, scenario["run_id"])

        term = fixtures.read_term(api, scenario["term_id"])
        assert term["status"] == AcademicTermStatus.CLOSED.value
        assert term["closed_at"] == "2026-09-10T11:00:00.000Z"

        report = fixtures.read_report(api, scenario["report_id"])
        assert report["status"] == DisclosureReportStatus.PUBLISHED.value
        assert report["published_at"] == "2026-09-10T11:00:00.000Z"

    def test_a_published_report_can_never_be_amended(self, api, compliance_officer):
        """PRD §3.9: "`PUBLISHED` is terminal: a published report can never be
        amended, and an attempt is rejected with `ERR_INVALID_STATE`."

        Design: Corner/validations/validation_settlement_requires_locked_term
        """
        scenario = self._computed_run_and_certified_report_on_an_open_term(api)
        fixtures.set_clock(api, "2026-09-10T11:00:00Z")
        fixtures.lock_term_billing(api, scenario["term_id"])
        fixtures.settle_run(api, scenario["run_id"])

        response = api.amend_disclosure_report(
            scenario["report_id"],
            factories.amend_payload(
                amendment_note="Attempting to amend after publication."),
            compliance_officer,
        )
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        frozen = fixtures.read_report(api, scenario["report_id"])
        assert frozen["status"] == DisclosureReportStatus.PUBLISHED.value
        assert frozen["amendment_count"] == 0
        assert frozen["amendment_note"] is None


class TestDisclosureDeadlineOnATermThatPricedNothing:
    """With no agreement in scope, the currency gate is vacuous and only the date bites."""

    @staticmethod
    def _open_term_with_one_draft_report(api):
        fixtures.set_clock(api, "2026-07-05T00:00:00Z")
        term = fixtures.create_term(api)
        fixtures.open_term(api, term["id"])
        report = fixtures.create_disclosure_report(api, term["id"], "CA")
        return {"term_id": term["id"], "report_id": report["id"]}

    def test_the_filing_deadline_day_is_inclusive_to_the_millisecond(
            self, api, compliance_officer):
        """PRD §3.9: "It requires the report to be `DRAFT`, the current logical date
        to be on or before the term's `disclosure_deadline_date` — a later attempt is
        rejected with `ERR_DISCLOSURE_DEADLINE_PASSED` — and every
        `PublisherAgreement` pricing at least one charge of the term to have a
        `reconciliation_status` of `COMPUTED`, `DISPUTED` or `SETTLED`."

        Design: Corner/validations/validation_disclosure_deadline_blocks_late_certification
        """
        scenario = self._open_term_with_one_draft_report(api)

        fixtures.set_clock(api, "2027-01-16T00:00:00Z")
        response = api.certify_disclosure_report(scenario["report_id"],
                                                compliance_officer)
        validate_error(response, ApiErrorId.DISCLOSURE_DEADLINE_PASSED.value)

        still_draft = fixtures.read_report(api, scenario["report_id"])
        assert still_draft["status"] == DisclosureReportStatus.DRAFT.value
        assert still_draft["certified_at"] is None

        fixtures.set_clock(api, "2027-01-15T23:59:59.999Z")
        certified = fixtures.certify_report(api, scenario["report_id"])
        assert certified["status"] == DisclosureReportStatus.CERTIFIED.value
        assert certified["certified_at"] == "2027-01-15T23:59:59.999Z"
        assert certified["certified_by_user_id"] == "co-1"

        assert certified["ia_section_count"] == 0
        assert certified["charge_count"] == 0
        assert certified["enrolled_student_count"] == 0
        assert certified["opted_out_student_count"] == 0
        assert_money(certified["total_list_price_cents"], 0)
        assert_money(certified["total_net_billed_cents"], 0)
        assert_money(certified["average_net_cost_cents"], 0)
        assert_ratio(certified["savings_pct"], 0.0000)
        # A zero charge count is NOT_APPLICABLE, not NON_COMPLIANT.
        assert certified["compliance_status"] == ComplianceStatus.NOT_APPLICABLE.value

    def test_the_amendment_clears_the_stamps_and_the_report_may_certify_again(
            self, api, compliance_officer):
        """PRD §3.9: "A `ComplianceOfficer` moves a report `CERTIFIED` → `DRAFT` with
        a stored `amendment_note`, incrementing `amendment_count` by 1, clearing
        `certified_at` and `certified_by_user_id`, and recomputing every metric."

        Design: Corner/validations/validation_disclosure_deadline_blocks_late_certification
        """
        scenario = self._open_term_with_one_draft_report(api)
        fixtures.set_clock(api, "2027-01-15T23:59:59.999Z")
        fixtures.certify_report(api, scenario["report_id"])

        amended = fixtures.amend_report(
            api, scenario["report_id"],
            "Adding the late-reported ECON section figures.",
        )
        assert amended["status"] == DisclosureReportStatus.DRAFT.value
        assert amended["amendment_count"] == 1
        assert amended["amendment_note"] == \
            "Adding the late-reported ECON section figures."
        assert amended["certified_at"] is None
        assert amended["certified_by_user_id"] is None
        assert amended["published_at"] is None

        recertified = fixtures.certify_report(api, scenario["report_id"])
        assert recertified["status"] == DisclosureReportStatus.CERTIFIED.value
        assert recertified["amendment_count"] == 1
        assert recertified["certified_at"] == "2027-01-15T23:59:59.999Z"

        _, meta = validate_paginated(
            api.list_term_disclosure_reports(
                scenario["term_id"], compliance_officer,
                {"status": DisclosureReportStatus.CERTIFIED.value},
            )
        )
        assert meta["total_count"] == 1
