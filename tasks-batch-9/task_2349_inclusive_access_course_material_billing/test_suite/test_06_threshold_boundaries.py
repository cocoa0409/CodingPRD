"""Values landing exactly on a threshold, and their one-unit neighbours on the
other side: the state savings floor, the participation floor and the settlement
variance tolerance.
"""

from test_helpers import (
    AcademicTermStatus,
    AccessStatus,
    ApiErrorId,
    BillingStatus,
    ComplianceStatus,
    DisclosureReportStatus,
    ReconciliationRunStatus,
    ReconciliationStatus,
    SectionIaStatus,
    assert_entitlement_seats_conserved,
    assert_money,
    assert_ratio,
    fixtures,
    validate_error,
    validate_success,
)

BRIGHTLEAF_AGREEMENT = {
    "publisher_name": "Brightleaf Press",
    "agreement_code": "PUB-B",
    "effective_from": "2027-01-01",
    "effective_to": "2027-06-01",
    "max_list_price_pct": 0.80,
}
BIOLOGY_TITLE = {
    "isbn": "978-0-11-000003-0",
    "title": "Biology Now",
    "list_price_cents": 18000,
}
LAB_SAFETY_TITLE = {
    "isbn": "978-0-11-000006-0",
    "title": "Lab Safety Companion",
    "list_price_cents": 10000,
}
SPRING_WINDOW = {"access_start_date": "2027-01-11", "access_end_date": "2027-05-01"}
FOUR_STUDENTS = (
    ("S-1001", "Ada Lin"),
    ("S-1002", "Ben Ortiz"),
    ("S-1003", "Cara Wu"),
    ("S-1004", "Dana Ek"),
)


class TestStateSavingsThreshold:
    """A term-wide saving of exactly 0.3000 is compliant; 0.2643 is not."""

    @staticmethod
    def _two_flagged_sections_with_only_the_first_charged(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-11-15T00:00:00Z", spring_term=True,
            agreement_overrides=BRIGHTLEAF_AGREEMENT, title_overrides=BIOLOGY_TITLE,
            bands=((1, 2, 12000),),
        )
        lab_title, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, 1, 8000),), **LAB_SAFETY_TITLE
        )

        first = fixtures.add_section(
            api, catalog,
            section_overrides={"subject_code": "BIO", "catalog_number": "120",
                              "section_number": "001", "instructor_user_id": "fac-4"},
            instructor_user_id="fac-4", adoption_overrides=SPRING_WINDOW,
        )
        second = fixtures.add_section(
            api, catalog,
            section_overrides={"subject_code": "BIO", "catalog_number": "121",
                              "section_number": "001", "instructor_user_id": "fac-5"},
            title_id=lab_title["id"], instructor_user_id="fac-5",
            adoption_overrides=SPRING_WINDOW,
        )

        students = fixtures.create_students(api, (("S-4001", "Gia Noor"),
                                                  ("S-4002", "Hal Vega")))
        fixtures.set_clock(api, "2027-01-11T08:00:00Z")
        fixtures.create_enrollment(api, first["section_id"], students[0]["id"],
                                   "2027-01-11")
        second_enrollment = fixtures.create_enrollment(
            api, second["section_id"], students[1]["id"], "2027-01-11"
        )

        fixtures.set_clock(api, "2027-01-11T09:00:00Z")
        charges = fixtures.post_section_charges(api, first["section_id"])

        fixtures.create_reconciliation_run(
            api, catalog["agreement_id"], catalog["term_id"],
            publisher_reported_count=1, publisher_reported_amount_cents=11088,
        )
        report = fixtures.create_disclosure_report(api, catalog["term_id"], "TX")

        return {
            "term_id": catalog["term_id"],
            "first_section_id": first["section_id"],
            "second_section_id": second["section_id"],
            "second_enrollment_id": second_enrollment["id"],
            "first_charge": charges[0],
            "report_id": report["id"],
        }

    def test_savings_of_exactly_thirty_percent_certifies_as_compliant(self, api,
                                                                     compliance_officer):
        """PRD §3.9: "`compliance_status` follows from those figures in a fixed
        order: it is `NOT_APPLICABLE` when `charge_count` is zero, `COMPLIANT`
        when `savings_pct` is at or above thirty percent (0.3000), and
        `NON_COMPLIANT` otherwise."

        Design: Difficulty/boundary_precision_check/boundary_state_savings_pct_exactly_at_min_threshold_is_compliant
        """
        scenario = self._two_flagged_sections_with_only_the_first_charged(api)

        # round_half_up(12000 * 1.05) = 12600, under the 14400 cap and over the floor.
        assert_money(scenario["first_charge"]["gross_price_cents"], 12600)

        certified = validate_success(
            api.certify_disclosure_report(scenario["report_id"], compliance_officer)
        )
        assert certified["status"] == DisclosureReportStatus.CERTIFIED.value
        assert_money(certified["total_list_price_cents"], 18000)
        assert_money(certified["total_net_billed_cents"], 12600)
        assert certified["charge_count"] == 1
        assert_money(certified["average_net_cost_cents"], 12600)
        assert_ratio(certified["savings_pct"], 0.3000)
        assert certified["compliance_status"] == ComplianceStatus.COMPLIANT.value

    def test_amending_after_a_weaker_discount_recomputes_below_the_threshold(
            self, api, bursar_officer, compliance_officer):
        """PRD §3.9: "Amendment is the return path. A `ComplianceOfficer` moves a
        report `CERTIFIED` → `DRAFT` with a stored `amendment_note`, incrementing
        `amendment_count` by 1, clearing `certified_at` and
        `certified_by_user_id`, and recomputing every metric."

        Design: Difficulty/boundary_precision_check/boundary_state_savings_pct_exactly_at_min_threshold_is_compliant
        """
        scenario = self._two_flagged_sections_with_only_the_first_charged(api)
        fixtures.certify_report(api, scenario["report_id"])

        second_charges = validate_success(
            api.post_section_charges(scenario["second_section_id"], bursar_officer),
            expected_status=201,
        )
        # The 0.80 list cap binds at 8000, not the 8400 fee-loaded band price.
        assert_money(second_charges[0]["gross_price_cents"], 8000)

        amended = validate_success(
            api.amend_disclosure_report(
                scenario["report_id"],
                {"amendment_note": "Second inclusive-access section came online."},
                compliance_officer,
            )
        )
        assert amended["status"] == DisclosureReportStatus.DRAFT.value
        assert amended["amendment_count"] == 1
        assert amended["certified_at"] is None

        assert_money(amended["total_list_price_cents"], 28000)
        assert_money(amended["total_net_billed_cents"], 20600)
        assert amended["charge_count"] == 2
        assert_money(amended["average_net_cost_cents"], 10300)
        # round_half_up(0.26428571, 4) = 0.2643, one notch under 0.3000.
        assert_ratio(amended["savings_pct"], 0.2643)
        assert amended["compliance_status"] == ComplianceStatus.NON_COMPLIANT.value
        assert amended["ia_section_count"] == 2
        assert amended["enrolled_student_count"] == 2
        assert amended["opted_out_student_count"] == 0


class TestParticipationRateThreshold:
    """Two of four seats is exactly one half; one of four is the first breach."""

    @staticmethod
    def _four_charges_one_granted_and_two_pending(api):
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z", roster=FOUR_STUDENTS,
        )

        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        first = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        fixtures.grant_opt_out(api, first["id"])
        second = fixtures.file_opt_out(
            api, scenario["charge_ids"][1], scenario["student_ids"][1], "OWNS_COPY"
        )
        third = fixtures.file_opt_out(
            api, scenario["charge_ids"][2], scenario["student_ids"][2], "ALTERNATE_SOURCE"
        )

        scenario["second_request_id"] = second["id"]
        scenario["third_request_id"] = third["id"]
        return scenario

    def test_rate_of_exactly_one_half_keeps_the_section_billed(self, api):
        """PRD §3.5: "The section's posture then reacts, but only from the two
        billed postures: a section that is `BILLED` moves to `AT_RISK` when the
        recomputed rate is strictly below one half (0.5000), and a section that is
        `AT_RISK` returns to `BILLED` when the recomputed rate is at or above one
        half."

        Design: Difficulty/boundary_precision_check/boundary_participation_rate_exactly_at_min_stays_billed
        """
        scenario = self._four_charges_one_granted_and_two_pending(api)

        before = fixtures.read_section(api, scenario["section_id"])
        assert_ratio(before["participation_rate"], 0.7500)
        assert before["ia_status"] == SectionIaStatus.BILLED.value

        fixtures.grant_opt_out(api, scenario["second_request_id"])

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 4
        assert section["provisioned_access_count"] == 2
        assert section["revoked_access_count"] == 2
        assert_ratio(section["participation_rate"], 0.5000)
        assert section["ia_status"] == SectionIaStatus.BILLED.value

    def test_third_grant_is_the_first_to_breach_and_seats_stay_conserved(self, api):
        """PRD §2.7: "For every `CourseSection` whose `ia_status` is `BILLED` or
        `AT_RISK`, `provisioned_access_count` plus `revoked_access_count` equals
        the number of charges on that section whose `access_status` is anything
        other than `NOT_PROVISIONED`."

        Design: Difficulty/boundary_precision_check/boundary_participation_rate_exactly_at_min_stays_billed
        """
        scenario = self._four_charges_one_granted_and_two_pending(api)

        fixtures.grant_opt_out(api, scenario["second_request_id"])
        assert_entitlement_seats_conserved(
            fixtures.read_section(api, scenario["section_id"]), 4
        )

        fixtures.grant_opt_out(api, scenario["third_request_id"])

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 3
        assert_ratio(section["participation_rate"], 0.2500)
        assert section["ia_status"] == SectionIaStatus.AT_RISK.value
        assert section["opted_out_count"] == 3
        assert section["billing_basis_enrollment_count"] == 4
        assert_entitlement_seats_conserved(section, 4)

        for charge_id in scenario["charge_ids"][:3]:
            refunded = fixtures.read_charge(api, charge_id)
            assert refunded["billing_status"] == BillingStatus.REFUNDED.value
            assert_money(refunded["refunded_amount_cents"], 7875)
            assert_money(refunded["net_billed_cents"], 0)
            assert_money(refunded["publisher_share_cents"], 0)

        untouched = fixtures.read_charge(api, scenario["charge_ids"][3])
        assert untouched["billing_status"] == BillingStatus.POSTED.value
        assert untouched["access_status"] == AccessStatus.PROVISIONED.value
        assert_money(untouched["net_billed_cents"], 7875)


class TestSettlementVarianceTolerance:
    """501 cents is one cent too far to settle; 500 settles and cannot be disputed."""

    @staticmethod
    def _locked_term_with_a_501_cent_variance(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        fixtures.set_clock(api, "2026-12-15T09:00:00Z")
        fixtures.lock_term_billing(api, scenario["term_id"])
        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"], agreement["version"],
            publisher_reported_count=2, publisher_reported_amount_cents=16634,
        )
        scenario["run_a_id"] = run["id"]
        scenario["run_a"] = run
        return scenario

    def test_variance_of_501_is_refused_by_the_direct_branch(self, api, program_admin):
        """PRD §3.8: "It requires the run to be `COMPUTED`, the agreement's
        `reconciliation_status` to be `COMPUTED`, and the absolute value of
        `variance_cents` to be at most five dollars — 500 cents — with a larger
        variance rejected as `ERR_VARIANCE_TOLERANCE_EXCEEDED` and required to be
        disputed first."

        Design: Difficulty/boundary_precision_check/boundary_variance_501_rejects_settlement_and_500_permits_it
        """
        scenario = self._locked_term_with_a_501_cent_variance(api)

        assert_money(scenario["run_a"]["variance_cents"], 501)
        assert scenario["run_a"]["count_variance"] == 0

        response = api.settle_reconciliation_run(scenario["run_a_id"], program_admin)
        validate_error(response, ApiErrorId.VARIANCE_TOLERANCE_EXCEEDED.value)

        run = fixtures.read_run(api, scenario["run_a_id"])
        assert run["status"] == ReconciliationRunStatus.COMPUTED.value

    def test_variance_of_exactly_500_is_too_small_to_dispute(self, api, program_admin):
        """PRD §3.8: "A dispute filed on a variance whose absolute value is within
        that tolerance is rejected with `ERR_VARIANCE_WITHIN_TOLERANCE`."

        Design: Difficulty/boundary_precision_check/boundary_variance_501_rejects_settlement_and_500_permits_it
        """
        scenario = self._locked_term_with_a_501_cent_variance(api)
        api.settle_reconciliation_run(scenario["run_a_id"], program_admin)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        corrected = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"], agreement["version"],
            publisher_reported_count=2, publisher_reported_amount_cents=16633,
            supersedes_run_id=scenario["run_a_id"],
        )
        assert_money(corrected["gross_invoice_cents"], 16632)
        assert_money(corrected["rebate_cents"], 499)
        assert_money(corrected["settlement_amount_cents"], 16133)
        assert_money(corrected["variance_cents"], 500)

        superseded = fixtures.read_run(api, scenario["run_a_id"])
        assert superseded["status"] == ReconciliationRunStatus.SUPERSEDED.value
        refreshed = fixtures.read_agreement(api, scenario["agreement_id"])
        assert refreshed["reconciliation_status"] == ReconciliationStatus.COMPUTED.value

        response = api.dispute_reconciliation_run(
            corrected["id"], {"dispute_note": "Disputing a within-tolerance gap."},
            program_admin,
        )
        validate_error(response, ApiErrorId.VARIANCE_WITHIN_TOLERANCE.value)

    def test_variance_of_exactly_500_settles_on_the_campus_figure(self, api,
                                                                 program_admin):
        """PRD §3.8: "Its first hop moves the agreement's `reconciliation_status`
        to `SETTLED` and writes the agreement's `settled_amount_cents` as the
        run's own `settlement_amount_cents` — the campus computation stands."

        Design: Difficulty/boundary_precision_check/boundary_variance_501_rejects_settlement_and_500_permits_it
        """
        scenario = self._locked_term_with_a_501_cent_variance(api)
        api.settle_reconciliation_run(scenario["run_a_id"], program_admin)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        corrected = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"], agreement["version"],
            publisher_reported_count=2, publisher_reported_amount_cents=16633,
            supersedes_run_id=scenario["run_a_id"],
        )

        settled = validate_success(
            api.settle_reconciliation_run(corrected["id"], program_admin)
        )
        assert settled["status"] == ReconciliationRunStatus.SETTLED.value

        final = fixtures.read_agreement(api, scenario["agreement_id"])
        assert final["reconciliation_status"] == ReconciliationStatus.SETTLED.value
        # The campus 16133, not the publisher's 16633.
        assert_money(final["settled_amount_cents"], 16133)

        term = fixtures.read_term(api, scenario["term_id"])
        assert term["status"] == AcademicTermStatus.CLOSED.value
