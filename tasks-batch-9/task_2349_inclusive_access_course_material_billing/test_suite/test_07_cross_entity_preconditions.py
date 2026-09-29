"""Transitions whose gate lives on a different entity two or more hops away:
certification against an agreement, flagging against a term and an adoption,
rescinding against an enrollment.
"""

from test_helpers import (
    AcademicTermStatus,
    AccessStatus,
    AdoptionStatus,
    ApiErrorId,
    BillingStatus,
    ComplianceStatus,
    DisclosureReportStatus,
    EnrollmentStatus,
    OptOutRequestStatus,
    ReconciliationRunStatus,
    ReconciliationStatus,
    SectionIaStatus,
    assert_money,
    assert_ratio,
    fixtures,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCertificationNeedsCurrentReconciliation:
    """A report cannot be filed while any agreement of its term is STALE."""

    @staticmethod
    def _draft_report_whose_agreement_just_went_stale(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        report = fixtures.create_disclosure_report(api, scenario["term_id"], "CA")
        run_a = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            publisher_reported_count=2, publisher_reported_amount_cents=16133,
        )

        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        fixtures.grant_opt_out(api, request["id"])

        scenario["report_id"] = report["id"]
        scenario["run_a_id"] = run_a["id"]
        return scenario

    def test_stale_agreement_blocks_the_draft_report(self, api, compliance_officer):
        """PRD §3.9: "An agreement sitting at `NOT_STARTED` or `STALE` blocks
        certification with `ERR_RECONCILIATION_NOT_CURRENT`, which is what stops
        an officer from filing a savings figure that a mid-flight refund has
        already invalidated."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_certify_requires_non_stale_agreement_reconciliation
        """
        scenario = self._draft_report_whose_agreement_just_went_stale(api)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.STALE.value

        response = api.certify_disclosure_report(scenario["report_id"],
                                                compliance_officer)
        validate_error(response, ApiErrorId.RECONCILIATION_NOT_CURRENT.value)

        report = fixtures.read_report(api, scenario["report_id"])
        assert report["status"] == DisclosureReportStatus.DRAFT.value
        assert report["certified_at"] is None

    def test_fresh_run_reopens_certification_and_the_metrics_skip_the_refund(
            self, api, compliance_officer):
        """PRD §3.9: "Their scope is the term's sections that carry
        `inclusive_access_flag` true, and within those sections the charges whose
        `billing_status` is `POSTED`, `PARTIALLY_REFUNDED` or `REBILLED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_certify_requires_non_stale_agreement_reconciliation
        """
        scenario = self._draft_report_whose_agreement_just_went_stale(api)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        run_b = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"], agreement["version"],
            publisher_reported_count=1, publisher_reported_amount_cents=8316,
            supersedes_run_id=scenario["run_a_id"],
        )
        assert run_b["billable_count"] == 1
        assert run_b["opted_out_count"] == 1
        assert_money(run_b["gross_invoice_cents"], 8316)
        assert_money(run_b["rebate_cents"], 0)
        assert_money(run_b["settlement_amount_cents"], 8316)
        assert_money(run_b["variance_cents"], 0)

        superseded = fixtures.read_run(api, scenario["run_a_id"])
        assert superseded["status"] == ReconciliationRunStatus.SUPERSEDED.value
        refreshed = fixtures.read_agreement(api, scenario["agreement_id"])
        assert refreshed["reconciliation_status"] == ReconciliationStatus.COMPUTED.value

        certified = validate_success(
            api.certify_disclosure_report(scenario["report_id"], compliance_officer)
        )
        assert certified["status"] == DisclosureReportStatus.CERTIFIED.value
        assert certified["certified_by_user_id"] == "co-1"
        assert certified["certified_at"] == "2026-08-26T10:00:00.000Z"

        assert certified["charge_count"] == 1
        assert_money(certified["total_list_price_cents"], 18000)
        assert_money(certified["total_net_billed_cents"], 9450)
        assert_money(certified["average_net_cost_cents"], 9450)
        # The opt-out leaves the money scope but stays in the headcount scope.
        assert certified["opted_out_student_count"] == 1
        assert certified["enrolled_student_count"] == 2
        assert_ratio(certified["savings_pct"], 0.4750)
        assert certified["compliance_status"] == ComplianceStatus.COMPLIANT.value


class TestFlaggingNeedsTermThenAdoption:
    """One unchanged request, three answers, as two foreign gates clear in turn."""

    @staticmethod
    def _planning_term_with_a_submitted_adoption(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-01T00:00:00Z", open_term_now=False,
            bands=((1, 2, 9000),),
        )
        section = fixtures.create_section(api, catalog["term_id"])
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], section["version"]
        )
        fixtures.submit_adoption(api, adoption["id"])
        catalog["section_id"] = section["id"]
        catalog["adoption_id"] = adoption["id"]
        return catalog

    def test_planning_term_answers_before_the_adoption_is_examined(self, api,
                                                                  program_admin):
        """PRD §3.5: "A `ProgramAdmin` moves the section `NOT_FLAGGED` →
        `FLAGGED`, which requires that the section is currently `NOT_FLAGGED`,
        that at least one adoption on it is `APPROVED` (else
        `ERR_ADOPTION_NOT_APPROVED`), that for every such approved adoption the
        adopted title is `ACTIVE` (else `ERR_TITLE_WITHDRAWN`) and the agreement
        pricing that title is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`), and that
        the term is `OPEN` (else `ERR_TERM_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_flag_section_requires_open_term_then_approved_adoption
        """
        scenario = self._planning_term_with_a_submitted_adoption(api)

        # Both gates are shut, and the term gate is the one that reports.
        response = api.flag_section_inclusive_access(scenario["section_id"],
                                                    program_admin)
        validate_error(response, ApiErrorId.TERM_NOT_OPEN.value)

        opened = fixtures.open_term(api, scenario["term_id"])
        assert opened["status"] == AcademicTermStatus.OPEN.value
        assert opened["ia_section_count"] == 0

        # Identical request, and now the adoption gate is what answers.
        response = api.flag_section_inclusive_access(scenario["section_id"],
                                                    program_admin)
        validate_error(response, ApiErrorId.ADOPTION_NOT_APPROVED.value)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
        assert section["inclusive_access_flag"] is False

    def test_approval_unlocks_the_flag_and_bubbles_a_counter_to_the_term(self, api):
        """PRD §3.5: "Flagging sets `inclusive_access_flag` to true, recomputes
        the term's `ia_section_count`, and increments the section's `version`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_flag_section_requires_open_term_then_approved_adoption
        """
        scenario = self._planning_term_with_a_submitted_adoption(api)
        fixtures.open_term(api, scenario["term_id"])

        approved = fixtures.approve_adoption(api, scenario["adoption_id"])
        assert approved["status"] == AdoptionStatus.APPROVED.value
        assert_money(approved["locked_list_price_cents"], 18000)
        assert approved["approved_by_user_id"] == "pa-1"

        flagged = fixtures.flag_section(api, scenario["section_id"])
        assert flagged["ia_status"] == SectionIaStatus.FLAGGED.value
        assert flagged["inclusive_access_flag"] is True
        # Freezing waits for the first posting.
        assert flagged["billing_basis_enrollment_count"] is None

        term = fixtures.read_term(api, scenario["term_id"])
        assert term["ia_section_count"] == 1


class TestRescindNeedsAnActiveEnrollment:
    """The same rescind succeeds for the enrolled peer and fails for the dropped one."""

    @staticmethod
    def _two_grants_with_the_first_student_dropped(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")

        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        first = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        fixtures.grant_opt_out(api, first["id"])

        fixtures.set_clock(api, "2026-08-27T10:00:00Z")
        second = fixtures.file_opt_out(
            api, scenario["charge_ids"][1], scenario["student_ids"][1], "ALTERNATE_SOURCE"
        )
        fixtures.grant_opt_out(api, second["id"])

        fixtures.set_clock(api, "2026-08-28T10:00:00Z")
        fixtures.drop_enrollment(api, scenario["enrollment_ids"][0], "2026-08-28")

        scenario["first_request_id"] = first["id"]
        scenario["second_request_id"] = second["id"]
        return scenario

    def test_dropped_enrollment_freezes_its_charge_forever(self, api, bursar_officer,
                                                          registrar):
        """PRD §3.6: "Across the whole opt-out lifecycle, a request whose
        enrollment has been dropped is frozen: filing, granting, rescinding and
        re-filing on such a charge are all rejected with
        `ERR_ENROLLMENT_NOT_ACTIVE`, and all four operations are equally subject
        to `ERR_OPT_OUT_WINDOW_CLOSED` once the charge's deadline instant has
        passed."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_rescind_blocked_by_dropped_enrollment
        """
        scenario = self._two_grants_with_the_first_student_dropped(api)

        enrollment = validate_success(
            api.get_enrollment(scenario["enrollment_ids"][0], registrar)
        )
        assert enrollment["status"] == EnrollmentStatus.DROPPED.value

        # The charge was already REFUNDED, so the drop moved no money at all.
        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 2
        assert_money(sum(entry["amount_cents"] for entry in entries), 0)

        response = api.rescind_opt_out_request(
            scenario["first_request_id"],
            make_student_headers(scenario["student_ids"][0]),
        )
        validate_error(response, ApiErrorId.ENROLLMENT_NOT_ACTIVE.value)

        request = fixtures.read_opt_out(api, scenario["first_request_id"])
        assert request["status"] == OptOutRequestStatus.GRANTED.value

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert charge["billing_status"] == BillingStatus.REFUNDED.value
        assert charge["access_status"] == AccessStatus.REVOKED.value

    def test_enrolled_peer_rescinds_and_carries_the_section_back_to_billed(
            self, api, registrar):
        """PRD §3.6: "It records `recharge_amount_cents` as the absolute value of
        the most recent `OPT_OUT_REFUND` movement on that charge, and stamps
        `rescinded_at`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_rescind_blocked_by_dropped_enrollment
        """
        scenario = self._two_grants_with_the_first_student_dropped(api)

        rescinded = fixtures.rescind_opt_out(
            api, scenario["second_request_id"], scenario["student_ids"][1]
        )
        assert rescinded["status"] == OptOutRequestStatus.RESCINDED.value
        assert_money(rescinded["recharge_amount_cents"], 9450)

        charge = fixtures.read_charge(api, scenario["charge_ids"][1])
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert charge["access_status"] == AccessStatus.RESTORED.value
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["refunded_amount_cents"], 0)

        for index, expected in ((0, 0), (1, 9450)):
            student = validate_success(
                api.get_student(scenario["student_ids"][index], registrar)
            )
            assert_money(student["bursar_balance_cents"], expected)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 1
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 1
        assert_ratio(section["participation_rate"], 1.0000)
        assert section["ia_status"] == SectionIaStatus.BILLED.value

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        # No run ever existed, so the cascade's STALE hop has nothing to move.
        assert agreement["reconciliation_status"] == ReconciliationStatus.NOT_STARTED.value
