"""Who may act: the segregation-of-duties boundaries between the six roles, the
per-student and per-instructor ownership scoping, and the operations that several
roles genuinely share.
"""

from test_helpers import (
    AcademicTermStatus,
    AdoptionStatus,
    AccessStatus,
    ApiErrorId,
    BillingStatus,
    LedgerEntryType,
    LedgerReasonCode,
    OptOutRequestStatus,
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
PEER_SECTION = {"section_number": "002", "instructor_user_id": "fac-2"}


class TestOperationsOneRoleMayNeverBorrowFromAnother:
    """Four plausible-looking cross-role writes, and the office boundaries."""

    @staticmethod
    def _billed_section_a_peer_section_and_one_open_opt_out(api):
        scenario = fixtures.setup_billed_section(
            api, bands=SINGLE_BAND, roster=ONE_STUDENT
        )
        peer_section = fixtures.create_section(
            api, scenario["term_id"], **PEER_SECTION
        )
        fixtures.set_clock(api, "2026-08-24T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0],
            reason_code="COST",
        )
        scenario["peer_section_id"] = peer_section["id"]
        scenario["request_id"] = request["id"]
        return scenario

    def test_authoring_flagging_filing_and_deciding_each_belong_to_one_role_only(
            self, api, program_admin, faculty, bursar_officer):
        """PRD §2.1: "The role model is one of segregation of duties: the operator who
        authors an adoption may never be the operator who approves it, the office that
        posts a charge is not the office that files an opt-out, and the officer who
        certifies a state disclosure has no authority over billing at all."

        Design: Corner/rbac/rbac_cross_role_exclusive_operations_rejected
        """
        scenario = self._billed_section_a_peer_section_and_one_open_opt_out(api)
        student_headers = make_student_headers(scenario["student_ids"][0])

        # A ProgramAdmin approves adoptions but may not author one.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["peer_section_id"], scenario["title_id"], 1),
                program_admin),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )
        # Flagging a section for inclusive access is not a Faculty power.
        validate_error(
            api.flag_section_inclusive_access(scenario["peer_section_id"], faculty),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )
        # The office that posted the charge may never file the opt-out.
        validate_error(
            api.create_opt_out_request(
                factories.opt_out_request_payload(scenario["charge_ids"][0]),
                bursar_officer),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )
        # And the student who filed it may never decide it.
        validate_error(
            api.grant_opt_out_request(scenario["request_id"], student_headers),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )

        request = fixtures.read_opt_out(api, scenario["request_id"])
        assert request["status"] == OptOutRequestStatus.SUBMITTED.value
        assert request["decided_by_user_id"] is None

        _, meta = validate_paginated(
            api.list_charge_opt_out_requests(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 1

        _, meta = validate_paginated(
            api.list_section_adoptions(scenario["peer_section_id"], program_admin)
        )
        assert meta["total_count"] == 0

        peer_section = fixtures.read_section(api, scenario["peer_section_id"])
        assert peer_section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
        assert peer_section["inclusive_access_flag"] is False

    def test_registration_reconciliation_disclosure_and_billing_are_separate_offices(
            self, api, program_admin, faculty, registrar, bursar_officer,
            compliance_officer):
        """PRD §2.1: "If the headers are well formed but the named role is not
        authorized for the endpoint being called, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/rbac_cross_role_exclusive_operations_rejected
        """
        scenario = self._billed_section_a_peer_section_and_one_open_opt_out(api)
        newcomer = fixtures.create_student(api, "S-1009", "Fay Kim")

        # Registration belongs to the Registrar alone.
        validate_error(
            api.create_enrollment(
                factories.enrollment_payload(
                    scenario["section_id"], newcomer["id"], "2026-08-24"),
                bursar_officer),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )
        # Reconciliation belongs to the ProgramAdmin alone.
        validate_error(
            api.create_reconciliation_run(
                factories.reconciliation_run_payload(
                    scenario["agreement_id"], scenario["term_id"],
                    scenario["agreement_version"]),
                registrar),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )
        # State disclosure belongs to the ComplianceOfficer alone.
        validate_error(
            api.create_disclosure_report(
                factories.disclosure_report_payload(scenario["term_id"]), faculty),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )
        # And the certifying officer has no authority over billing at all.
        validate_error(
            api.post_section_charges(scenario["section_id"], compliance_officer),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )
        validate_error(
            api.lock_term_billing(scenario["term_id"], compliance_officer),
            ApiErrorId.ROLE_NOT_PERMITTED.value, expected_status=403,
        )

        assert fixtures.read_term(api, scenario["term_id"])["status"] == \
            AcademicTermStatus.OPEN.value

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert_money(charge["net_billed_cents"], 9450)

        _, meta = validate_paginated(
            api.list_section_enrollments(scenario["section_id"], registrar)
        )
        assert meta["total_count"] == 1

        _, meta = validate_paginated(
            api.list_agreement_reconciliation_runs(
                scenario["agreement_id"], program_admin)
        )
        assert meta["total_count"] == 0

        assert fixtures.read_agreement(api, scenario["agreement_id"])["version"] == \
            scenario["agreement_version"]


class TestOwnershipScopingAcrossPeersOfTheSameRole:
    """A student sees only its own money; an instructor authors only its own sections."""

    @staticmethod
    def _two_charged_students_a_granted_peer_opt_out_and_a_peer_section(api):
        # The instructor-ownership test authors and submits an adoption on the peer
        # section after day one, so the term's adoption deadline is set past that
        # instant: the subject here is ownership, not PRD §3.3's submission deadline.
        catalog = fixtures.setup_catalog(
            api, bands=SINGLE_BAND,
            term_overrides={"adoption_deadline_date": "2026-09-01"},
        )
        scenario = dict(catalog)
        scenario.update(fixtures.add_section(api, catalog))
        peer_section = fixtures.create_section(
            api, catalog["term_id"], **PEER_SECTION
        )
        scenario.update(fixtures.enroll_roster(api, scenario["section_id"]))

        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        charges = fixtures.post_section_charges(api, scenario["section_id"])
        fixtures.set_clock(api, "2026-08-24T10:00:00Z")
        peer_request = fixtures.file_opt_out(
            api, charges[1]["id"], scenario["student_ids"][1], reason_code="COST"
        )
        fixtures.set_clock(api, "2026-08-24T11:00:00Z")
        fixtures.grant_opt_out(api, peer_request["id"])

        scenario["peer_section_id"] = peer_section["id"]
        scenario["charges"] = charges
        scenario["charge_ids"] = [charge["id"] for charge in charges]
        scenario["peer_request_id"] = peer_request["id"]
        return scenario

    def test_a_student_may_neither_touch_nor_read_a_peers_charge(self, api):
        """PRD §2.1: "Ownership is enforced, with `ERR_NOT_RESOURCE_OWNER` (HTTP 403),
        on exactly these operations: `POST /adoptions` and
        `POST /adoptions/{adoption_id}/submit` (the acting `Faculty` operator's
        `X-User-ID` must equal the section's `instructor_user_id`);
        `POST /opt-out-requests`, `POST /opt-out-requests/{request_id}/rescind` and
        `POST /opt-out-requests/{request_id}/resubmit` (the acting `Student`'s
        `X-User-ID` must equal the `student_id` of the charge behind the request); and
        the three scoped reads `GET /students/{student_id}/ledger-entries`,
        `GET /charges/{charge_id}` and `GET /charges/{charge_id}/ledger-entries` (a
        `Student` may only read its own records)."

        Design: Corner/rbac/rbac_ownership_scoping_across_peer_students_and_instructors
        """
        scenario = self._two_charged_students_a_granted_peer_opt_out_and_a_peer_section(
            api)
        owner_id, peer_id = scenario["student_ids"]
        owner_charge, peer_charge = scenario["charge_ids"]
        owner_headers = make_student_headers(owner_id)

        # Filing against someone else's charge is a 403, not a 404.
        validate_error(
            api.create_opt_out_request(
                factories.opt_out_request_payload(peer_charge), owner_headers),
            ApiErrorId.NOT_RESOURCE_OWNER.value, expected_status=403,
        )
        # Opting the peer back in is likewise forbidden.
        validate_error(
            api.rescind_opt_out_request(scenario["peer_request_id"], owner_headers),
            ApiErrorId.NOT_RESOURCE_OWNER.value, expected_status=403,
        )
        # The two scoped reads leak nothing either.
        validate_error(
            api.get_charge(peer_charge, owner_headers),
            ApiErrorId.NOT_RESOURCE_OWNER.value, expected_status=403,
        )
        validate_error(
            api.list_student_ledger_entries(peer_id, owner_headers),
            ApiErrorId.NOT_RESOURCE_OWNER.value, expected_status=403,
        )

        # The peer's granted opt-out and refunded charge are untouched.
        assert fixtures.read_opt_out(api, scenario["peer_request_id"])["status"] == \
            OptOutRequestStatus.GRANTED.value
        refunded = fixtures.read_charge(api, peer_charge)
        assert refunded["billing_status"] == BillingStatus.REFUNDED.value
        assert refunded["access_status"] == AccessStatus.REVOKED.value
        assert_money(refunded["refunded_amount_cents"], 9450)
        assert_money(refunded["net_billed_cents"], 0)

        # The same student succeeds the moment it acts on its own records.
        own_request = validate_success(
            api.create_opt_out_request(
                factories.opt_out_request_payload(owner_charge), owner_headers),
            expected_status=201,
        )
        assert own_request["status"] == OptOutRequestStatus.SUBMITTED.value
        assert own_request["charge_id"] == owner_charge

        own_charge = validate_success(api.get_charge(owner_charge, owner_headers))
        assert own_charge["student_id"] == owner_id
        assert own_charge["billing_status"] == BillingStatus.POSTED.value

        entries = fixtures.read_student_ledger(api, owner_id, owner_headers)
        assert len(entries) == 1
        assert entries[0]["entry_type"] == LedgerEntryType.CHARGE.value
        assert entries[0]["reason_code"] == LedgerReasonCode.INITIAL_POST.value
        assert_money(entries[0]["amount_cents"], 9450)

        assert_money(fixtures.student_balance(api, owner_id), 9450)
        assert_money(fixtures.student_balance(api, peer_id), 0)

    def test_an_instructor_owns_authoring_only_on_its_own_sections(self, api,
                                                                 program_admin):
        """PRD §2.1: "It is recorded as `submitted_by_user_id` on an `Adoption`, and it
        is compared for ownership against the `instructor_user_id` recorded on the
        `CourseSection` — that string is itself an opaque Faculty operator identifier
        supplied when the section was created, not a foreign key to any entity."

        Design: Corner/rbac/rbac_ownership_scoping_across_peer_students_and_instructors
        """
        scenario = self._two_charged_students_a_granted_peer_opt_out_and_a_peer_section(
            api)
        peer_section_id = scenario["peer_section_id"]
        owner = make_faculty_headers("fac-2")
        outsider = make_faculty_headers("fac-1")

        # fac-1 owns section 001, so authoring on section 002 is refused.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(peer_section_id, scenario["title_id"], 1),
                outsider),
            ApiErrorId.NOT_RESOURCE_OWNER.value, expected_status=403,
        )
        _, meta = validate_paginated(
            api.list_section_adoptions(peer_section_id, program_admin)
        )
        assert meta["total_count"] == 0
        assert fixtures.section_version(api, peer_section_id) == 1

        # The instructor named on the section may author it.
        draft = validate_success(
            api.create_adoption(
                factories.adoption_payload(peer_section_id, scenario["title_id"], 1),
                owner),
            expected_status=201,
        )
        assert draft["status"] == AdoptionStatus.DRAFT.value
        assert draft["submitted_by_user_id"] is None

        # Submitting that draft is owned by the same instructor, not by a colleague.
        validate_error(
            api.submit_adoption(draft["id"], outsider),
            ApiErrorId.NOT_RESOURCE_OWNER.value, expected_status=403,
        )
        assert fixtures.read_adoption(api, draft["id"])["status"] == \
            AdoptionStatus.DRAFT.value

        submitted = fixtures.submit_adoption(api, draft["id"],
                                            instructor_user_id="fac-2")
        assert submitted["status"] == AdoptionStatus.SUBMITTED.value
        assert submitted["submitted_by_user_id"] == "fac-2"


class TestOperationsGenuinelySharedBySeveralRoles:
    """Two creator roles, two posting roles, and a clock every role may set."""

    @staticmethod
    def _open_term_with_a_priced_title(api):
        return fixtures.setup_catalog(api, bands=SINGLE_BAND)

    def test_a_section_created_by_a_registrar_matches_one_created_by_a_program_admin(
            self, api, registrar, program_admin):
        """PRD §3.3: "A **CourseSection** is created by a `Registrar` or a
        `ProgramAdmin` against a term, with a payload naming the `term_id`, the
        `subject_code` (for example `ECON`), the `catalog_number` (for example `101`)
        and the `section_number`, which must be unique for the combination of term,
        subject code and catalog number."

        Design: Corner/rbac/rbac_shared_operations_available_to_every_permitted_role
        """
        catalog = self._open_term_with_a_priced_title(api)

        by_registrar = validate_success(
            api.create_section(
                factories.section_payload(catalog["term_id"]), registrar),
            expected_status=201,
        )
        by_program_admin = validate_success(
            api.create_section(
                factories.section_payload(catalog["term_id"], **PEER_SECTION),
                program_admin),
            expected_status=201,
        )

        for section in (by_registrar, by_program_admin):
            assert section["term_id"] == catalog["term_id"]
            assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
            assert section["inclusive_access_flag"] is False
            assert section["enrolled_count"] == 0
            assert section["provisioned_access_count"] == 0
            assert section["revoked_access_count"] == 0
            assert section["opted_out_count"] == 0
            assert_ratio(section["participation_rate"], 0.0000)
            assert section["billing_basis_enrollment_count"] is None
            assert section["first_posted_at"] is None
            assert section["version"] == 1
            assert section["max_concurrent_titles"] == 2

        assert by_registrar["instructor_user_id"] == "fac-1"
        assert by_program_admin["instructor_user_id"] == "fac-2"

        # Neither section is second class: both reach FLAGGED the same way.
        fixtures.create_approved_adoption(
            api, by_registrar["id"], catalog["title_id"])
        fixtures.create_approved_adoption(
            api, by_program_admin["id"], catalog["title_id"],
            instructor_user_id="fac-2", approver_user_id="pa-2")
        for section_id in (by_registrar["id"], by_program_admin["id"]):
            assert fixtures.flag_section(api, section_id)["ia_status"] == \
                SectionIaStatus.FLAGGED.value

    def test_either_posting_role_produces_the_same_day_one_charge(self, api,
                                                                bursar_officer,
                                                                program_admin):
        """PRD §3.5: "The batch form, available to a `BursarOfficer` or a
        `ProgramAdmin`, sweeps the whole section on day one: it creates one charge for
        every enrolled student who does not yet carry a charge on the section's
        currently approved adoption, processing them in order of the enrollment's
        `enrolled_on` ascending with ties broken by the student's `external_id`
        ascending."

        Design: Corner/rbac/rbac_shared_operations_available_to_every_permitted_role
        """
        catalog = self._open_term_with_a_priced_title(api)
        first = fixtures.add_section(api, catalog)
        second = fixtures.add_section(
            api, catalog, section_overrides=PEER_SECTION,
            instructor_user_id="fac-2", approver_user_id="pa-2",
        )
        fixtures.enroll_roster(api, first["section_id"],
                              fixtures.DEFAULT_STUDENTS[:1])
        fixtures.enroll_roster(api, second["section_id"],
                              fixtures.DEFAULT_STUDENTS[1:2])

        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        by_bursar = validate_success(
            api.post_section_charges(first["section_id"], bursar_officer),
            expected_status=201,
        )
        by_program_admin = validate_success(
            api.post_section_charges(second["section_id"], program_admin),
            expected_status=201,
        )

        assert len(by_bursar) == 1 and len(by_program_admin) == 1
        for charge in (by_bursar[0], by_program_admin[0]):
            assert_money(charge["gross_price_cents"], 9450)
            assert_ratio(charge["proration_pct"], 1.0000)
            assert_money(charge["billed_amount_cents"], 9450)
            assert_money(charge["net_billed_cents"], 9450)
            assert_money(charge["publisher_share_cents"], 8316)
            assert charge["billing_status"] == BillingStatus.POSTED.value
            assert charge["access_status"] == AccessStatus.PROVISIONED.value
            assert charge["posted_at"] == "2026-08-24T09:00:00.000Z"
            assert charge["opt_out_deadline_at"] == "2026-09-04T23:59:59.999Z"

        for section_id in (first["section_id"], second["section_id"]):
            section = fixtures.read_section(api, section_id)
            assert section["ia_status"] == SectionIaStatus.BILLED.value
            assert section["billing_basis_enrollment_count"] == 1
            assert_ratio(section["participation_rate"], 1.0000)

    def test_every_role_may_set_the_clock_and_none_of_them_mutates_anything(
            self, api, program_admin, faculty, registrar, bursar_officer,
            compliance_officer):
        """PRD §2.4: "Every deadline comparison, every timestamp stamped onto a
        resource, and every proration date arithmetic reads a logical clock that any of
        the six roles may set by supplying a `current_utc` instant. Before the clock has
        ever been set, its value is `2026-08-01T00:00:00Z`. Setting the clock replaces
        the logical present for all later requests and mutates no business entity
        whatsoever; the response echoes the new `current_utc`."

        Design: Corner/rbac/rbac_shared_operations_available_to_every_permitted_role
        """
        catalog = self._open_term_with_a_priced_title(api)
        section = fixtures.create_section(api, catalog["term_id"])
        student = fixtures.create_student(api)

        before_term = fixtures.read_term(api, catalog["term_id"])
        before_agreement = fixtures.read_agreement(api, catalog["agreement_id"])
        before_section = fixtures.read_section(api, section["id"])
        before_student = fixtures.read_student(api, student["id"])

        for headers, instant in (
            (make_student_headers(student["id"]), "2026-08-20T08:10:00.000Z"),
            (faculty, "2026-08-20T08:20:00.000Z"),
            (registrar, "2026-08-20T08:30:00.000Z"),
            (bursar_officer, "2026-08-20T08:40:00.000Z"),
            (compliance_officer, "2026-08-20T08:50:00.000Z"),
            (program_admin, "2026-08-20T09:00:00.000Z"),
        ):
            echoed = validate_success(api.set_clock(instant, headers))
            assert echoed["current_utc"] == instant

        assert fixtures.read_term(api, catalog["term_id"]) == before_term
        assert fixtures.read_agreement(api, catalog["agreement_id"]) == \
            before_agreement
        assert fixtures.read_section(api, section["id"]) == before_section
        assert fixtures.read_student(api, student["id"]) == before_student
