"""Declared states and declared edges: where every resource starts, which hops are
legal, which are refused because the from-state declares no such edge, and how the
three dimensions of a charge and its opt-out request move apart from one another.
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
    PublisherAgreementStatus,
    ReconciliationStatus,
    RegistrationType,
    SectionIaStatus,
    StudentStatus,
    assert_adoption_shape,
    assert_disclosure_report_shape,
    assert_money,
    assert_ratio,
    assert_section_shape,
    factories,
    fixtures,
    make_faculty_headers,
    make_program_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_SECTION = {
    "section_number": "002",
    "instructor_user_id": "fac-2",
}
LATIMER_AGREEMENT = {
    "publisher_name": "Latimer Learning",
    "agreement_code": "PUB-B",
    "max_list_price_pct": 0.80,
}
MACRO_TITLE = {
    "isbn": "978-0-11-000003-0",
    "title": "Macro Foundations",
    "list_price_cents": 18000,
}
ESSENTIALS_TITLE = {
    "isbn": "978-0-11-000005-0",
    "title": "Economics Essentials",
    "list_price_cents": 12000,
}


class TestInitialStatesAcrossTheDomain:
    """Every create lands on its declared initial state with its counters at zero."""

    def test_the_catalog_and_the_section_start_where_they_are_declared_to(self, api):
        """PRD §3.1: "A newly created term is `PLANNING`, with `ia_section_count` at
        0 and `closed_at` null."

        PRD §3.2: "A new agreement is `DRAFT` in its contractual dimension and
        `NOT_STARTED` in its settlement dimension, with `settled_amount_cents` and
        `suspend_reason_note` both null." And: "A new title is `ACTIVE`."

        PRD §3.3: "A new section is `NOT_FLAGGED` with `inclusive_access_flag`
        false, every counter (`enrolled_count`, `provisioned_access_count`,
        `revoked_access_count`, `opted_out_count`) at 0, `participation_rate` at
        0.0000, and both `billing_basis_enrollment_count` and `first_posted_at`
        null."

        Design: Corner/state_machines/state_initial_states_on_create_across_the_domain
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)
        assert term["status"] == AcademicTermStatus.PLANNING.value
        assert term["ia_section_count"] == 0
        assert term["closed_at"] is None

        agreement = fixtures.create_agreement(api)
        assert agreement["status"] == PublisherAgreementStatus.DRAFT.value
        assert agreement["reconciliation_status"] == ReconciliationStatus.NOT_STARTED.value
        assert agreement["settled_amount_cents"] is None
        assert agreement["suspend_reason_note"] is None

        title = fixtures.create_title(api, agreement["id"])
        assert title["status"] == CourseMaterialTitleStatus.ACTIVE.value

        section = fixtures.create_section(api, term["id"])
        assert_section_shape(section)
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
        assert section["inclusive_access_flag"] is False
        assert section["enrolled_count"] == 0
        assert section["provisioned_access_count"] == 0
        assert section["revoked_access_count"] == 0
        assert section["opted_out_count"] == 0
        assert_ratio(section["participation_rate"], 0.0000)
        assert section["billing_basis_enrollment_count"] is None
        assert section["first_posted_at"] is None

    def test_the_adoption_the_student_and_the_enrollment_start_at_their_zero_values(
            self, api, registrar):
        """PRD §3.3: "A new adoption is `DRAFT` with `revision_count` at 0 and
        `requires_rebill` false; `submitted_by_user_id`, `approved_by_user_id`,
        `submitted_at`, `approved_at`, `locked_list_price_cents` and `change_note`
        are all null at this point."

        PRD §3.4: "A new student is `ACTIVE` (the alternative value is `INACTIVE`)
        with `bursar_balance_cents` at 0."

        PRD §3.4: "Creating an enrollment sets `status` to `ENROLLED` with
        `dropped_on` null, then recomputes the section's `enrolled_count` and
        `participation_rate`."

        Design: Corner/state_machines/state_initial_states_on_create_across_the_domain
        """
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-01T00:00:00Z", open_term_now=False,
            bands=((1, 2, 9000),), activate_now=False,
        )
        section = fixtures.create_section(api, catalog["term_id"])

        # Authoring is legal while the term is still PLANNING.
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )
        assert_adoption_shape(adoption)
        assert adoption["status"] == AdoptionStatus.DRAFT.value
        assert adoption["revision_count"] == 0
        assert adoption["requires_rebill"] is False
        assert adoption["submitted_by_user_id"] is None
        assert adoption["approved_by_user_id"] is None
        assert adoption["submitted_at"] is None
        assert adoption["approved_at"] is None
        assert adoption["locked_list_price_cents"] is None
        assert adoption["change_note"] is None

        student = fixtures.create_student(api)
        assert student["status"] == StudentStatus.ACTIVE.value
        assert_money(student["bursar_balance_cents"], 0)

        enrollment = validate_success(
            api.create_enrollment(
                factories.enrollment_payload(section["id"], student["id"]), registrar
            ),
            expected_status=201,
        )
        assert enrollment["status"] == EnrollmentStatus.ENROLLED.value
        assert enrollment["dropped_on"] is None
        # 2026-08-24 is on or before the 2026-09-04 add/drop deadline.
        assert enrollment["registration_type"] == RegistrationType.REGULAR.value

        refreshed = fixtures.read_section(api, section["id"])
        assert refreshed["enrolled_count"] == 1
        # No charge is provisioned yet, so the rate stays at zero.
        assert_ratio(refreshed["participation_rate"], 0.0000)

    def test_a_report_on_an_empty_term_computes_its_metrics_as_not_applicable(
            self, api, compliance_officer):
        """PRD §3.9: "A new report is `DRAFT` with `amendment_count` at 0,
        `amendment_note`, `certified_by_user_id`, `certified_at` and `published_at`
        all null, and every affordability metric computed immediately at creation."

        PRD §3.9: "`compliance_status` follows from those figures in a fixed order:
        it is `NOT_APPLICABLE` when `charge_count` is zero, `COMPLIANT` when
        `savings_pct` is at or above thirty percent (0.3000), and `NON_COMPLIANT`
        otherwise."

        Design: Corner/state_machines/state_initial_states_on_create_across_the_domain
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)

        report = validate_success(
            api.create_disclosure_report(
                factories.disclosure_report_payload(term["id"], "CA"),
                compliance_officer,
            ),
            expected_status=201,
        )
        assert_disclosure_report_shape(report)
        assert report["status"] == DisclosureReportStatus.DRAFT.value
        assert report["amendment_count"] == 0
        assert report["amendment_note"] is None
        assert report["certified_by_user_id"] is None
        assert report["certified_at"] is None
        assert report["published_at"] is None

        assert report["ia_section_count"] == 0
        assert report["charge_count"] == 0
        assert report["enrolled_student_count"] == 0
        assert report["opted_out_student_count"] == 0
        assert_money(report["total_list_price_cents"], 0)
        assert_money(report["total_net_billed_cents"], 0)
        assert_money(report["average_net_cost_cents"], 0)
        assert_ratio(report["savings_pct"], 0.0000)
        assert report["compliance_status"] == ComplianceStatus.NOT_APPLICABLE.value


class TestAgreementLifecycleHops:
    """Two hops on the contractual dimension leave the settlement dimension alone."""

    def test_activation_then_suspension_moves_one_dimension_only(self, api,
                                                                program_admin):
        """PRD §3.2: "Suspension is the exit. Moving `ACTIVE` → `SUSPENDED` is
        permitted only from `ACTIVE`, requires a `suspend_reason_note`, which is
        stored on the agreement, and increments `version`. It deliberately leaves
        `reconciliation_status` untouched."

        Design: Corner/state_machines/state_agreement_activate_then_suspend_valid_transitions
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        agreement = fixtures.create_agreement(api)
        fixtures.create_priced_title(api, agreement["id"], ((1, 2, 9000),))

        fixtures.set_clock(api, "2026-07-02T10:00:00Z")
        activated = fixtures.activate_agreement(api, agreement["id"])
        assert activated["status"] == PublisherAgreementStatus.ACTIVE.value
        assert activated["version"] == 2
        assert activated["reconciliation_status"] == ReconciliationStatus.NOT_STARTED.value
        assert activated["created_at"] == "2026-07-01T00:00:00.000Z"
        assert activated["updated_at"] == "2026-07-02T10:00:00.000Z"

        note = "Publisher data feed outage; pausing new approvals."
        suspended = fixtures.suspend_agreement(api, agreement["id"], note)
        assert suspended["status"] == PublisherAgreementStatus.SUSPENDED.value
        assert suspended["version"] == 3
        assert suspended["suspend_reason_note"] == note
        assert suspended["reconciliation_status"] == ReconciliationStatus.NOT_STARTED.value
        assert suspended["settled_amount_cents"] is None
        assert suspended["updated_at"] == "2026-07-02T10:00:00.000Z"

        rows, meta = validate_paginated(
            api.list_agreements(program_admin,
                                {"status": PublisherAgreementStatus.SUSPENDED.value})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == agreement["id"]


class TestActivationReadiness:
    """Both halves of the readiness test are enforced, and separately."""

    def test_no_title_then_a_tierless_title_then_a_ready_catalog(self, api,
                                                                program_admin):
        """PRD §3.2: "Activation is the readiness gate on the catalog. Moving an
        agreement `DRAFT` → `ACTIVE` is permitted only while it is `DRAFT`, and only
        if the agreement has at least one title in `ACTIVE` status and every one of
        its `ACTIVE` titles carries at least one pricing band. A catalog that fails
        either half of that test is rejected with
        `ERR_AGREEMENT_NOT_ACTIVATABLE`; a successful activation increments the
        agreement's `version`."

        Design: Corner/state_machines/state_agreement_activation_preconditions_enforced
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        agreement = fixtures.create_agreement(api)

        response = api.activate_agreement(agreement["id"], program_admin)
        validate_error(response, ApiErrorId.AGREEMENT_NOT_ACTIVATABLE.value)
        stored = fixtures.read_agreement(api, agreement["id"])
        assert stored["status"] == PublisherAgreementStatus.DRAFT.value
        assert stored["version"] == 1

        title = fixtures.create_title(api, agreement["id"])
        response = api.activate_agreement(agreement["id"], program_admin)
        validate_error(response, ApiErrorId.AGREEMENT_NOT_ACTIVATABLE.value)

        fixtures.add_pricing_band(api, title["id"], (1, 2, 9000))
        activated = fixtures.activate_agreement(api, agreement["id"])
        assert activated["status"] == PublisherAgreementStatus.ACTIVE.value
        assert activated["version"] == 2

    def test_a_withdrawn_title_stops_counting_even_though_it_owns_a_band(
            self, api, program_admin):
        """PRD §3.2: "A title may be retired from the catalog by moving it `ACTIVE`
        → `WITHDRAWN`, which is permitted only while the title is `ACTIVE` and only
        if no approved adoption of that title sits on a section whose `ia_status` is
        `BILLED` or `AT_RISK`."

        PRD §3.2: "A catalog that fails either half of that test is rejected with
        `ERR_AGREEMENT_NOT_ACTIVATABLE`; a successful activation increments the
        agreement's `version`."

        Design: Corner/state_machines/state_agreement_activation_preconditions_enforced
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        agreement = fixtures.create_agreement(api, **LATIMER_AGREEMENT)
        title, _ = fixtures.create_priced_title(
            api, agreement["id"], ((1, None, 12000),), **MACRO_TITLE
        )

        withdrawn = fixtures.withdraw_title(api, title["id"])
        assert withdrawn["status"] == CourseMaterialTitleStatus.WITHDRAWN.value

        response = api.activate_agreement(agreement["id"], program_admin)
        validate_error(response, ApiErrorId.AGREEMENT_NOT_ACTIVATABLE.value)

        stored = fixtures.read_agreement(api, agreement["id"])
        assert stored["status"] == PublisherAgreementStatus.DRAFT.value
        _, meta = validate_paginated(
            api.list_agreements(program_admin,
                                {"status": PublisherAgreementStatus.ACTIVE.value})
        )
        assert meta["total_count"] == 0


class TestTransitionsFromAWrongFromState:
    """Priority 45 answers before any domain gate downstream of it."""

    @staticmethod
    def _planning_term_with_a_draft_adoption_and_a_draft_report(api,
                                                                compliance_officer):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-01T00:00:00Z", open_term_now=False,
            bands=((1, 2, 9000),), activate_now=False,
        )
        section = fixtures.create_section(api, catalog["term_id"])
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )
        report = validate_success(
            api.create_disclosure_report(
                factories.disclosure_report_payload(catalog["term_id"], "CA"),
                compliance_officer,
            ),
            expected_status=201,
        )
        catalog["adoption_id"] = adoption["id"]
        catalog["report_id"] = report["id"]
        return catalog

    def test_five_undeclared_hops_are_all_invalid_state_and_move_nothing(
            self, api, program_admin, compliance_officer):
        """PRD §2.11: "8. The target entity is in a state from which the requested
        transition is declared — `ERR_INVALID_STATE` (HTTP 409). Re-running a
        transition out of a terminal state, acting on a superseded reconciliation
        run, and acting on a published disclosure report all land here."

        PRD §3.1: "When billing for the term is complete, the same role locks it,
        moving `OPEN` → `BILLING_LOCKED`, permitted only from `OPEN`, and again
        incrementing `version`."

        Design: Corner/state_machines/state_transitions_from_wrong_from_state_rejected
        """
        scenario = self._planning_term_with_a_draft_adoption_and_a_draft_report(
            api, compliance_officer
        )

        response = api.lock_term_billing(scenario["term_id"], program_admin)
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        response = api.suspend_agreement(
            scenario["agreement_id"],
            factories.suspend_payload("Attempting to suspend a DRAFT agreement."),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        # Approval from DRAFT reports the state, not the segregation-of-duties or
        # agreement-active gates that this request also violates.
        response = api.approve_adoption(scenario["adoption_id"], program_admin)
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        response = api.request_adoption_change(
            scenario["adoption_id"],
            factories.change_request_payload("Please pick the cheaper edition."),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        response = api.amend_disclosure_report(
            scenario["report_id"],
            factories.amend_payload("Amending a report that was never certified."),
            compliance_officer,
        )
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        term = fixtures.read_term(api, scenario["term_id"])
        assert term["status"] == AcademicTermStatus.PLANNING.value
        assert term["version"] == 1

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["status"] == PublisherAgreementStatus.DRAFT.value
        assert agreement["suspend_reason_note"] is None
        assert agreement["version"] == 1

        adoption = fixtures.read_adoption(api, scenario["adoption_id"])
        assert adoption["status"] == AdoptionStatus.DRAFT.value
        assert adoption["locked_list_price_cents"] is None
        assert adoption["change_note"] is None
        assert adoption["version"] == 1

        report = fixtures.read_report(api, scenario["report_id"])
        assert report["status"] == DisclosureReportStatus.DRAFT.value
        assert report["amendment_count"] == 0
        assert report["version"] == 1


class TestTerminalStatesAreLocked:
    """Three declared terminal states, and no edge leaves any of them."""

    @staticmethod
    def _active_catalog_with_an_approved_unflagged_adoption(api):
        catalog = fixtures.setup_catalog(api, setup_clock="2026-07-01T00:00:00Z",
                                         bands=((1, 2, 9000),))
        essentials, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, 2, 6000),), **ESSENTIALS_TITLE
        )
        section = fixtures.create_section(api, catalog["term_id"], **SECOND_SECTION)
        adoption = fixtures.create_approved_adoption(
            api, section["id"], essentials["id"], section["version"],
            instructor_user_id="fac-2",
        )
        catalog["section_id"] = section["id"]
        catalog["adoption_id"] = adoption["id"]
        return catalog

    def test_a_withdrawn_title_and_a_withdrawn_adoption_refuse_every_further_hop(
            self, api, program_admin):
        """PRD §3.2: "`WITHDRAWN` is terminal."

        PRD §3.3: "Finally, an approved adoption may be withdrawn, moving
        `APPROVED` → `WITHDRAWN`, but only while the section's `ia_status` is
        `NOT_FLAGGED` or `FLAGGED` — that is, only while no charge has ever posted
        on the section. If withdrawing leaves the section with no approved adoption
        at all, the server clears the section's `inclusive_access_flag` to false,
        returns its `ia_status` to `NOT_FLAGGED`, and recomputes the term's
        `ia_section_count`."

        Design: Corner/state_machines/state_terminal_states_cannot_transition_further
        """
        scenario = self._active_catalog_with_an_approved_unflagged_adoption(api)

        withdrawn_title = fixtures.withdraw_title(api, scenario["title_id"])
        assert withdrawn_title["status"] == CourseMaterialTitleStatus.WITHDRAWN.value
        title_version = withdrawn_title["version"]

        response = api.withdraw_title(scenario["title_id"], program_admin)
        validate_error(response, ApiErrorId.INVALID_STATE.value)
        stored_title = validate_success(
            api.get_title(scenario["title_id"], program_admin)
        )
        assert stored_title["version"] == title_version

        withdrawn_adoption = validate_success(
            api.withdraw_adoption(scenario["adoption_id"], program_admin)
        )
        assert withdrawn_adoption["status"] == AdoptionStatus.WITHDRAWN.value
        section = fixtures.read_section(api, scenario["section_id"])
        assert section["inclusive_access_flag"] is False
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
        assert fixtures.read_term(api, scenario["term_id"])["ia_section_count"] == 0

        response = api.withdraw_adoption(scenario["adoption_id"], program_admin)
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        # Not even a second ProgramAdmin can re-approve a terminal adoption.
        response = api.approve_adoption(scenario["adoption_id"],
                                        make_program_admin_headers("pa-2"))
        validate_error(response, ApiErrorId.INVALID_STATE.value)
        assert (fixtures.read_adoption(api, scenario["adoption_id"])["status"]
                == AdoptionStatus.WITHDRAWN.value)

    def test_a_suspended_agreement_reports_its_state_not_its_readiness(self, api,
                                                                      program_admin):
        """PRD §3.2: "`SUSPENDED` is terminal in the contractual dimension; an
        agreement never returns to `ACTIVE`."

        PRD §2.11: "8. The target entity is in a state from which the requested
        transition is declared — `ERR_INVALID_STATE` (HTTP 409). Re-running a
        transition out of a terminal state, acting on a superseded reconciliation
        run, and acting on a published disclosure report all land here."

        Design: Corner/state_machines/state_terminal_states_cannot_transition_further
        """
        scenario = self._active_catalog_with_an_approved_unflagged_adoption(api)
        note = "Contract terminated for the term."

        suspended = fixtures.suspend_agreement(api, scenario["agreement_id"], note)
        assert suspended["status"] == PublisherAgreementStatus.SUSPENDED.value
        assert suspended["suspend_reason_note"] == note

        # The readiness gate at priority 62 is never consulted.
        response = api.activate_agreement(scenario["agreement_id"], program_admin)
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        response = api.suspend_agreement(
            scenario["agreement_id"],
            factories.suspend_payload("Second suspension attempt."),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        final = fixtures.read_agreement(api, scenario["agreement_id"])
        assert final["status"] == PublisherAgreementStatus.SUSPENDED.value
        assert final["suspend_reason_note"] == note
        assert final["version"] == suspended["version"]


class TestCompletedTransitionsDoNotReplay:
    """The second identical call is a 409, and it never double-counts."""

    def test_submit_open_and_flag_each_refuse_their_own_repeat(self, api,
                                                              program_admin):
        """PRD §3.1: "A `ProgramAdmin` opens it, moving `PLANNING` → `OPEN`, which
        is permitted only while the term is `PLANNING`; the transition recomputes
        `ia_section_count` from the term's sections that carry the inclusive access
        flag and increments the term's `version`."

        PRD §3.5: "Flagging sets `inclusive_access_flag` to true, recomputes the
        term's `ia_section_count`, and increments the section's `version`."

        Design: Corner/state_machines/state_repeating_a_completed_transition_rejected
        """
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", open_term_now=False,
            bands=((1, 2, 9000),),
        )
        section = fixtures.create_section(api, catalog["term_id"])
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )

        submitted = fixtures.submit_adoption(api, adoption["id"])
        assert submitted["status"] == AdoptionStatus.SUBMITTED.value
        assert submitted["submitted_by_user_id"] == "fac-1"
        assert submitted["submitted_at"] == "2026-07-05T00:00:00.000Z"
        assert submitted["revision_count"] == 0

        response = api.submit_adoption(adoption["id"], make_faculty_headers())
        validate_error(response, ApiErrorId.INVALID_STATE.value)
        assert fixtures.read_adoption(api, adoption["id"])["revision_count"] == 0

        fixtures.open_term(api, catalog["term_id"])
        response = api.open_term(catalog["term_id"], program_admin)
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        fixtures.approve_adoption(api, adoption["id"])
        flagged = fixtures.flag_section(api, section["id"])
        assert flagged["ia_status"] == SectionIaStatus.FLAGGED.value
        assert flagged["inclusive_access_flag"] is True
        assert fixtures.read_term(api, catalog["term_id"])["ia_section_count"] == 1

        response = api.flag_section_inclusive_access(section["id"], program_admin)
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        term = fixtures.read_term(api, catalog["term_id"])
        assert term["status"] == AcademicTermStatus.OPEN.value
        # No double count from the refused repeat.
        assert term["ia_section_count"] == 1

        section = fixtures.read_section(api, section["id"])
        assert section["billing_basis_enrollment_count"] is None
        assert section["first_posted_at"] is None


class TestAdoptionReviewCycleSideEffects:
    """request-change stores a note, the resubmit counts the revision, approval pins."""

    def test_each_review_hop_lands_exactly_its_own_side_effects(self, api,
                                                               program_admin):
        """PRD §3.3: "The instructor then resubmits, moving `CHANGE_REQUESTED` →
        `SUBMITTED`; that transition is permitted only from `CHANGE_REQUESTED`, is
        again restricted to the owning instructor, and again enforces the adoption
        deadline for an original adoption while exempting a superseding one.
        Resubmission increments `revision_count` by 1, refreshes `submitted_at` to
        the current logical instant, and keeps `submitted_by_user_id` at the
        identifier of the operator who resubmitted."

        PRD §3.3: "A successful approval pins `locked_list_price_cents` to the
        title's current `list_price_cents`, freezing the disclosure savings baseline
        against later publisher price changes, and stamps `approved_by_user_id` from
        the approving operator and `approved_at` from the logical clock."

        Design: Corner/state_machines/state_adoption_review_cycle_side_effects_are_all_applied
        """
        catalog = fixtures.setup_catalog(api, setup_clock="2026-07-05T00:00:00Z",
                                         bands=((1, 2, 9000),))
        section = fixtures.create_section(api, catalog["term_id"])
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )
        submitted = fixtures.submit_adoption(api, adoption["id"])
        assert submitted["submitted_at"] == "2026-07-05T00:00:00.000Z"
        assert submitted["submitted_by_user_id"] == "fac-1"
        assert submitted["revision_count"] == 0

        fixtures.set_clock(api, "2026-07-06T14:00:00Z")
        note = "Confirm the digital-only ISBN before approval."
        returned = validate_success(
            api.request_adoption_change(adoption["id"],
                                        factories.change_request_payload(note),
                                        program_admin)
        )
        assert returned["status"] == AdoptionStatus.CHANGE_REQUESTED.value
        assert returned["change_note"] == note
        # request-change stores a note and nothing else.
        assert returned["revision_count"] == 0
        assert returned["submitted_at"] == "2026-07-05T00:00:00.000Z"

        fixtures.set_clock(api, "2026-07-07T09:15:00Z")
        resubmitted = fixtures.submit_adoption(api, adoption["id"])
        assert resubmitted["status"] == AdoptionStatus.SUBMITTED.value
        assert resubmitted["revision_count"] == 1
        assert resubmitted["submitted_at"] == "2026-07-07T09:15:00.000Z"
        assert resubmitted["submitted_by_user_id"] == "fac-1"

        fixtures.set_clock(api, "2026-07-08T11:45:00Z")
        approved = fixtures.approve_adoption(api, adoption["id"], "pa-2")
        assert approved["status"] == AdoptionStatus.APPROVED.value
        assert_money(approved["locked_list_price_cents"], 18000)
        assert approved["approved_by_user_id"] == "pa-2"
        assert approved["approved_at"] == "2026-07-08T11:45:00.000Z"
        assert approved["requires_rebill"] is False
        assert approved["supersedes_adoption_id"] is None

        # Approval alone never flags the section.
        assert (fixtures.read_section(api, section["id"])["ia_status"]
                == SectionIaStatus.NOT_FLAGGED.value)

        rows, meta = validate_paginated(
            api.list_section_adoptions(section["id"], program_admin,
                                       {"status": AdoptionStatus.APPROVED.value})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == adoption["id"]


class TestChargeDimensionsMoveIndependently:
    """Three dimensions on two rows, each waiting for its own trigger."""

    @staticmethod
    def _billed_section_with_one_submitted_request(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "COST"
        )
        scenario["request_id"] = request["id"]
        return scenario

    def test_a_denial_moves_the_request_row_and_nothing_else(self, api, registrar):
        """PRD §3.6: "Denial is the other `BursarOfficer` decision, moving
        `SUBMITTED` → `DENIED` with a `denial_note` stored alongside `decided_at` and
        `decided_by_user_id`. Denial is deliberately inert: no ledger movement is
        appended, no access changes, and no section counter moves."

        Design: Corner/state_machines/state_charge_dimensions_advance_independently_of_the_opt_out_dimension
        """
        scenario = self._billed_section_with_one_submitted_request(api)
        note = "Course requires the interactive homework platform."

        denied = fixtures.deny_opt_out(api, scenario["request_id"], note)
        assert denied["status"] == OptOutRequestStatus.DENIED.value
        assert denied["denial_note"] == note
        assert denied["decided_by_user_id"] == "bo-1"
        assert denied["decided_at"] == "2026-08-26T10:00:00.000Z"
        assert_money(denied["refund_amount_cents"], 0)

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert charge["access_status"] == AccessStatus.PROVISIONED.value
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["refunded_amount_cents"], 0)
        assert len(fixtures.read_charge_ledger(api, scenario["charge_ids"][0])) == 1

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["provisioned_access_count"] == 2
        assert section["revoked_access_count"] == 0
        assert section["opted_out_count"] == 0
        assert_ratio(section["participation_rate"], 1.0000)
        assert section["ia_status"] == SectionIaStatus.BILLED.value

        student = fixtures.read_student(api, scenario["student_ids"][0])
        assert_money(student["bursar_balance_cents"], 9450)
        assert validate_paginated(
            api.list_student_enrollments(scenario["student_ids"][0], registrar)
        )[1]["total_count"] == 1

    def test_a_later_drop_moves_both_charge_dimensions_and_leaves_the_denial_alone(
            self, api):
        """PRD §3.7: "The resulting `billing_status` follows the refund amount: a
        refund exactly equal to `net_billed_cents` yields `REFUNDED`, a refund
        greater than zero but smaller than `net_billed_cents` yields
        `PARTIALLY_REFUNDED`, and a refund of zero leaves the charge `POSTED`
        untouched."

        PRD §3.7: "Hop two, because a charge was refunded, appends a `REFUND` ledger
        movement with `reason_code` `DROP_PRORATION` and recomputes the charge's
        `net_billed_cents` and the student's `bursar_balance_cents`."

        Design: Corner/state_machines/state_charge_dimensions_advance_independently_of_the_opt_out_dimension
        """
        scenario = self._billed_section_with_one_submitted_request(api)
        fixtures.deny_opt_out(api, scenario["request_id"],
                             "Course requires the interactive homework platform.")

        fixtures.set_clock(api, "2026-09-21T13:00:00Z")
        dropped = fixtures.drop_enrollment(api, scenario["enrollment_ids"][0],
                                           "2026-09-21")
        assert dropped["status"] == EnrollmentStatus.DROPPED.value
        assert dropped["dropped_on"] == "2026-09-21"

        # 28 days retained of 110 gives 0.2545, so 9450 - 7045 = 2405 stays billed.
        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert_money(charge["refunded_amount_cents"], 7045)
        assert_money(charge["net_billed_cents"], 2405)
        assert charge["billing_status"] == BillingStatus.PARTIALLY_REFUNDED.value
        assert charge["access_status"] == AccessStatus.REVOKED.value
        assert charge["access_revoked_at"] == "2026-09-21T13:00:00.000Z"
        assert_money(charge["publisher_share_cents"], 2116)

        entries = fixtures.read_charge_ledger(api, scenario["charge_ids"][0])
        assert len(entries) == 2
        assert_money(sum(entry["amount_cents"] for entry in entries), 2405)
        assert_money(fixtures.student_balance(api, scenario["student_ids"][0]), 2405)

        # The opt-out row never saw the drop refund.
        request = fixtures.read_opt_out(api, scenario["request_id"])
        assert request["status"] == OptOutRequestStatus.DENIED.value
        assert_money(request["refund_amount_cents"], 0)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 1
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 1
        assert_ratio(section["participation_rate"], 1.0000)
        assert section["ia_status"] == SectionIaStatus.BILLED.value

        peer = fixtures.read_charge(api, scenario["charge_ids"][1])
        assert peer["billing_status"] == BillingStatus.POSTED.value
        assert peer["access_status"] == AccessStatus.PROVISIONED.value
        assert_money(peer["net_billed_cents"], 9450)
        assert len(fixtures.read_charge_ledger(api, scenario["charge_ids"][1])) == 1
