"""Staffing-plan compliance reporting: creation, locked-shift gating, both
fill-rate variants, and the submit/return/resubmit revision loop."""
import pytest

from test_helpers import (
    ADMIN,
    REGULATOR,
    ApiErrorId,
    api_client,
    create_full_matrix,
    create_nurse,
    create_report,
    create_shift,
    create_unit,
    make_charge_nurse_headers,
    setup_locked_day,
    setup_staffed_shift,
    submit_snapshot,
    validate_error,
    validate_success,
    walk_to_accepted,
)


class TestReportCreation:

    def test_report_duplicate_date_rejected(self):
        """PRD section 3.9: "A `NurseAdmin` creates a `ComplianceReport` for a
        `report_date`; one report per date is the rule, and a duplicate date is
        rejected with `ERR_REPORT_ALREADY_EXISTS`."

        Design: Corner/entities/report_duplicate_date_rejected
        """
        create_report("2026-08-10")
        resp = api_client.create_compliance_report(
            {"report_date": "2026-08-10"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPORT_ALREADY_EXISTS)


class TestSubmitGates:

    def test_report_submit_on_empty_date_rejected(self):
        """PRD section 3.9: "At least one shift must exist with a `shift_date`
        equal to the `report_date` (else `ERR_NO_SHIFTS_FOR_REPORT_DATE`,
        HTTP 422)".

        Design: Corner/state_machines/report_submit_on_empty_date_rejected
        """
        report = create_report("2026-08-15")
        resp = api_client.submit_compliance_report(report["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_SHIFTS_FOR_REPORT_DATE)

    def test_report_accept_from_draft_rejected(self):
        """PRD section 3.9: "The `Regulator` then adjudicates a `SUBMITTED`
        report — acting on a report in any other state fails with
        `ERR_REPORT_INVALID_STATE`."

        Design: Corner/state_machines/report_accept_from_draft_rejected
        """
        report = create_report("2026-08-16")
        resp = api_client.accept_compliance_report(report["id"], REGULATOR)
        validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE)


class TestSubmitRequiresAllShiftsLocked:
    """Difficulty instance: report_submit_requires_all_shifts_locked."""

    def test_unlocked_shift_blocks_submission(self):
        """PRD section 3.9: "every shift for that date must be `LOCKED` (else
        `ERR_SHIFTS_NOT_LOCKED`)."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_all_shifts_locked
        """
        sc = setup_staffed_shift(num_accepted=0, name="ICU L",
                                 census=(4, 0, 0, 0))
        report = create_report("2026-08-10")
        resp = api_client.submit_compliance_report(report["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFTS_NOT_LOCKED)

        after = validate_success(
            api_client.get_compliance_report(report["id"], ADMIN),
            expected_status=200)
        assert after["status"] == "DRAFT", \
            f"failed submit must leave the report DRAFT, got {after['status']}"

    def test_submission_succeeds_once_all_shifts_locked(self):
        """PRD section 3.9: "Submission — from `DRAFT`, or again from
        `RETURNED` in the revision loop; any other state fails with
        `ERR_REPORT_INVALID_STATE` — is gated on finality."
        PRD section 3.9: "`shifts_included_count` counts the `LOCKED` shifts
        whose `shift_date` equals the report date."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_all_shifts_locked
        """
        sc = setup_staffed_shift(num_accepted=0, name="ICU L2",
                                 census=(4, 0, 0, 0))
        report = create_report("2026-08-10")
        validate_error(api_client.submit_compliance_report(report["id"], ADMIN),
                       ApiErrorId.ERR_SHIFTS_NOT_LOCKED)

        validate_success(
            api_client.lock_shift(sc["shift"]["id"], sc["charge_headers"]),
            expected_status=200)
        submitted = validate_success(
            api_client.submit_compliance_report(report["id"], ADMIN),
            expected_status=200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["shifts_included_count"] == 1


class TestFillRateVariants:
    """Difficulty instance: census_vs_shift_weighted_fill_rate."""

    def _setup_two_unit_scenario(self):
        """Unit A (ICU): required 4, census 8, 3 ACCEPTED then LOCKED (0.75).
        Unit B (MED_SURG): required 4, census 16, 4 ACCEPTED then LOCKED (1.0).
        """
        # --- Unit A ---
        sc_a = setup_staffed_shift(num_accepted=3, charge_first=False,
                                   name="ICU A", census=(2, 3, 2, 1))
        assert sc_a["shift"]["required_nurses"] == 4
        validate_success(
            api_client.lock_shift(sc_a["shift"]["id"], sc_a["charge_headers"]),
            expected_status=200)

        # --- Unit B (MED_SURG matrix 5/4/2/1; census 10/4/2/0 -> 4) ---
        ub = create_unit(name="MS B", unit_type="MED_SURG", bed_count=30,
                         incentive_budget_cents=500000)
        create_full_matrix("MED_SURG")
        cn_b = create_nurse(full_name="B Charge", employment_type="CORE",
                            competencies=["MED_SURG"],
                            base_hourly_rate_cents=7000,
                            home_unit_id=ub["id"], charge_qualified=True)
        ch_b = make_charge_nurse_headers(cn_b["id"])
        submit_snapshot(ub["id"], "2026-08-10", "DAY", (10, 4, 2, 0),
                        as_headers=ch_b)
        shb = create_shift(ub["id"], "2026-08-10", "DAY")
        assert shb["required_nurses"] == 4
        for i in (1, 2, 3, 4):
            nurse = create_nurse(full_name=f"B Nurse {i}",
                                 employment_type="CORE",
                                 competencies=["MED_SURG"],
                                 base_hourly_rate_cents=4500,
                                 home_unit_id=ub["id"])
            walk_to_accepted(shb["id"], nurse, ch_b)
        validate_success(api_client.lock_shift(shb["id"], ch_b),
                         expected_status=200)
        return sc_a, shb

    def test_fill_rate_variants_diverge_on_identical_inputs(self):
        """PRD section 3.9: "`fill_rate_shift_weighted_pct` is one hundred
        times the plain average of those ratios across included shifts — every
        shift weighing equally — rounded half-up to one decimal place.
        `fill_rate_census_weighted_pct` weights each shift's ratio by the
        `total_census` of the shift's governing snapshot: one hundred times the
        sum of each ratio multiplied by its census, divided by the sum of all
        censuses, again rounded half-up to one decimal place; high-census
        shifts dominate this variant".

        Design: Difficulty/dual_variant_calc/census_vs_shift_weighted_fill_rate
        """
        self._setup_two_unit_scenario()
        report = create_report("2026-08-10")
        data = validate_success(
            api_client.submit_compliance_report(report["id"], ADMIN),
            expected_status=200)
        # shift-weighted: 100 * (0.75 + 1.0) / 2 = 87.5
        assert data["fill_rate_shift_weighted_pct"] == pytest.approx(87.5, abs=0.05)
        # census-weighted: 100 * (0.75*8 + 1.0*16) / 24 = 91.66.. -> 91.7
        assert data["fill_rate_census_weighted_pct"] == pytest.approx(91.7, abs=0.05)
        assert data["fill_rate_shift_weighted_pct"] != \
            data["fill_rate_census_weighted_pct"]

    def test_fill_rate_counts_included_and_understaffed(self):
        """PRD section 3.9: "`shifts_included_count` counts the `LOCKED` shifts
        whose `shift_date` equals the report date."
        PRD section 3.9: "`understaffed_shift_count` counts the included
        shifts whose frozen `counted_at_lock` is strictly less than
        `required_nurses`."

        Design: Difficulty/dual_variant_calc/census_vs_shift_weighted_fill_rate
        """
        self._setup_two_unit_scenario()
        report = create_report("2026-08-10")
        data = validate_success(
            api_client.submit_compliance_report(report["id"], ADMIN),
            expected_status=200)
        assert data["shifts_included_count"] == 2
        # unit A locked at 3 of 4 (understaffed); unit B locked at 4 of 4
        assert data["understaffed_shift_count"] == 1


class TestReportRevisionLoop:
    """Difficulty instance: report_return_resubmit_cycle."""

    def _setup_locked_full_house(self):
        """ICU DAY shift required 2 with two ACCEPTED (one charge), LOCKED at
        full fill; a DRAFT report for the date."""
        sc = setup_locked_day(name="ICU D", census=(4, 0, 0, 0), nurses=2,
                              charge_first=True)
        report = create_report("2026-08-10")
        return sc, report

    def test_submit_return_resubmit_accept_cycle(self):
        """PRD section 3.9: "Submission — from `DRAFT`, or again from
        `RETURNED` in the revision loop; any other state fails with
        `ERR_REPORT_INVALID_STATE`".
        PRD section 3.9: "Returning the report moves it to `RETURNED` and
        records the regulator's optional `return_reason`; accepting it moves it
        to `ACCEPTED`, which is terminal."

        Design: Difficulty/non_linear_state_machine/report_return_resubmit_cycle
        """
        _sc, report = self._setup_locked_full_house()
        rid = report["id"]

        sub1 = validate_success(
            api_client.submit_compliance_report(rid, ADMIN),
            expected_status=200)
        assert sub1["status"] == "SUBMITTED"

        ret = validate_success(
            api_client.return_compliance_report(
                rid, {"return_reason": "missing attestation"}, REGULATOR),
            expected_status=200)
        assert ret["status"] == "RETURNED"

        sub2 = validate_success(
            api_client.submit_compliance_report(rid, ADMIN),
            expected_status=200)
        assert sub2["status"] == "SUBMITTED", \
            "the RETURNED -> SUBMITTED resubmission edge must close the cycle"

        acc = validate_success(
            api_client.accept_compliance_report(rid, REGULATOR),
            expected_status=200)
        assert acc["status"] == "ACCEPTED"

    def test_resubmission_recomputes_identical_figures(self):
        """PRD section 3.9: "On submission the report's four figures are
        computed, and recomputed identically on every resubmission."
        PRD section 3.9: "Returning the report moves it to `RETURNED` and
        records the regulator's optional `return_reason`".

        Design: Difficulty/non_linear_state_machine/report_return_resubmit_cycle
        """
        _sc, report = self._setup_locked_full_house()
        rid = report["id"]

        sub1 = validate_success(
            api_client.submit_compliance_report(rid, ADMIN),
            expected_status=200)
        # 2 of 2 counted at lock with full census fill: both variants 100.0
        assert sub1["fill_rate_shift_weighted_pct"] == pytest.approx(100.0, abs=0.05)
        assert sub1["fill_rate_census_weighted_pct"] == pytest.approx(100.0, abs=0.05)
        assert sub1["understaffed_shift_count"] == 0

        validate_success(
            api_client.return_compliance_report(
                rid, {"return_reason": "missing attestation"}, REGULATOR),
            expected_status=200)
        sub2 = validate_success(
            api_client.submit_compliance_report(rid, ADMIN),
            expected_status=200)
        assert sub2["fill_rate_shift_weighted_pct"] == pytest.approx(100.0, abs=0.05)
        assert sub2["fill_rate_census_weighted_pct"] == pytest.approx(100.0, abs=0.05)

        after = validate_success(
            api_client.get_compliance_report(rid, ADMIN), expected_status=200)
        assert after["return_reason"] == "missing attestation"
