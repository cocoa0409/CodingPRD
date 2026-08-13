"""Discharge Monitoring Reports: creation constraints, completeness arithmetic,
averaging variants, pinned loading rounding, certification/submission gates and
the reject/revise cycle (PRD §3.5)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equals,
    create_active_permit,
    create_dmr,
    create_dmr_payload,
    create_effluent_limit,
    create_exceedance_scenario,
    create_outfall,
    create_permit,
    create_validated_result,
    create_validated_results,
    issue_permit,
    make_field_sampler_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANY_HEADERS = TEST_USERS["regulator_headers"]  # reads are open to every role (PRD §2.1)
CO1 = TEST_USERS["compliance_officer_headers"]   # operator id "co-1"
CO2 = TEST_USERS["compliance_officer_2_headers"]  # operator id "co-2"
REG = TEST_USERS["regulator_headers"]

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-08-31T23:59:59Z"

def _dmr_with_one_validated_result(api, permit_number, parameter_code="TSS",
                                   limit_value=10.0, reported_value=1.0,
                                   monitoring_frequency="MONTHLY",
                                   officer_id="co-1"):
    """ACTIVE permit, one VALIDATED non-breaching result, one DRAFT DMR for Aug."""
    env = create_active_permit(
        permit_number=permit_number, parameter_code=parameter_code,
        limit_value=limit_value, monitoring_frequency=monitoring_frequency,
    )
    create_validated_result(
        env["outfall"]["id"], parameter_code, reported_value,
        scheduled_for="2026-08-05T08:00:00Z", collect_clock="2026-08-05T09:00:00Z",
        analyzed_at="2026-08-05T09:45:00Z", validate_clock="2026-08-05T10:00:00Z",
    )
    dmr = create_dmr(env["outfall"]["id"], officer_id=officer_id)
    return env, dmr

def _dmr_in_submitted(api, permit_number):
    env, dmr = _dmr_with_one_validated_result(api, permit_number)
    validate_success(api.certify_dmr(dmr["id"], CO2))
    validate_success(api.submit_dmr(dmr["id"], CO2))
    return env, dmr

class TestDmrCreation:
    def test_dmr_create_rejects_period_end_before_start(self, api):
        """PRD §3.5: "the period is inclusive at both ends and `period_end` must
        not precede `period_start` (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/dmr_create_rejects_period_end_before_start
        """
        permit = create_permit(permit_number="NPDES-ENT6")
        outfall = create_outfall(permit["id"])
        resp = api.create_dmr(
            create_dmr_payload(
                outfall["id"], "2026-08-31T00:00:00Z", "2026-08-01T00:00:00Z"
            ),
            CO1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_dmr_not_found(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_DMR_NOT_FOUND` ..."

        Design: Corner/entities/get_dmr_not_found
        """
        resp = api.get_dmr(NON_EXISTENT_UUID, ANY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_DMR_NOT_FOUND)

    def test_monitoring_completeness_empty_required_set_yields_zero_ratio(self, api):
        """PRD §3.5: "`monitoring_completeness_ratio` is the total divided by the
        required count, rounded half-up to four decimal places, and is exactly 0
        when nothing is required."
        PRD §3.5: "For each parameter holding an `ACTIVE` effluent limit for this
        outfall whose effective range intersects the period".

        Design: Corner/calculations/monitoring_completeness_empty_required_set_yields_zero_ratio
        """
        # The only limit's range starts after the period, so nothing is required.
        env = create_active_permit(
            permit_number="NPDES-CALC7", limit_effective_from="2027-01-01T00:00:00Z"
        )
        dmr = create_dmr(env["outfall"]["id"])
        assert dmr["required_sample_count"] == 0, (
            "the future-dated limit does not intersect the period"
        )
        assert dmr["monitoring_completeness_ratio"] == pytest.approx(0.0), (
            "pinned empty-set rule: ratio 0 when nothing is required"
        )

    def test_dmr_due_date_and_late_flag(self, api):
        """PRD §3.5: "The report's `due_date` is exactly 15 days after `period_end`"
        and "`is_late` is the report's lateness flag: it is true when the report has
        not been submitted and the logical clock is past `due_date`, or when its
        `submitted_at` ended up later than `due_date`."

        Design: Corner/calculations/dmr_due_date_and_late_flag
        """
        env, dmr = _dmr_with_one_validated_result(api, "NPDES-CALC6")
        assert_instant_equals(dmr["due_date"], "2026-09-15T23:59:59Z", "due_date")
        validate_success(api.certify_dmr(dmr["id"], CO2))

        set_clock("2026-09-20T00:00:00Z")  # past the due date
        submitted = validate_success(api.submit_dmr(dmr["id"], CO2))
        assert_instant_equals(submitted["submitted_at"], "2026-09-20T00:00:00Z", "submitted_at")
        assert submitted["is_late"] is True, "submitted after the due date"

class TestDmrGauntlet:
    def test_dmr_full_lifecycle_with_reject_revise_cycle(self, api):
        """PRD §3.5: "A `decision` of `REJECTED` requires a non-empty
        `deficiency_notes` payload field (`ERR_INVALID_REQUEST` otherwise); the notes
        are recorded on the report and it moves to `REJECTED` (`DMR_REJECTED`)."
        PRD §3.5: "a `ComplianceOfficer` may return it from `REJECTED` to `DRAFT`
        (`ERR_DMR_NOT_REJECTED` from any other status), which clears
        `certified_by_user_id` to null".

        Design: Corner/state_machines/dmr_full_lifecycle_with_reject_revise_cycle
        """
        env, dmr = _dmr_with_one_validated_result(api, "NPDES-SM22")

        certified = validate_success(api.certify_dmr(dmr["id"], CO2))
        assert certified["status"] == "CERTIFIED"
        validate_success(api.submit_dmr(dmr["id"], CO2))

        rejected = validate_success(api.review_dmr(
            dmr["id"],
            {"decision": "REJECTED", "deficiency_notes": "missing lab QC narrative"},
            REG,
        ))
        assert rejected["status"] == "REJECTED"
        assert rejected["deficiency_notes"] == "missing lab QC narrative"

        revised = validate_success(api.revise_dmr(dmr["id"], CO1))
        assert revised["status"] == "DRAFT"
        assert revised["certified_by_user_id"] is None, "certifier reset on revise"

        validate_success(api.certify_dmr(dmr["id"], CO2))
        validate_success(api.submit_dmr(dmr["id"], CO2))
        accepted = validate_success(
            api.review_dmr(dmr["id"], {"decision": "ACCEPTED"}, REG)
        )
        assert accepted["status"] == "ACCEPTED", "terminal state reached on second pass"

    def test_dmr_agency_review_rejected_without_notes_rejected(self, api):
        """PRD §3.5: "A `decision` of `REJECTED` requires a non-empty
        `deficiency_notes` payload field (`ERR_INVALID_REQUEST` otherwise)".

        Design: Corner/state_machines/dmr_agency_review_rejected_without_notes_rejected
        """
        env, dmr = _dmr_in_submitted(api, "NPDES-SM23")
        resp = api.review_dmr(dmr["id"], {"decision": "REJECTED"}, REG)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = validate_success(api.get_dmr(dmr["id"], ANY_HEADERS))
        assert after["status"] == "SUBMITTED"

    def test_dmr_revise_from_draft_rejected(self, api):
        """PRD §3.5: "a `ComplianceOfficer` may return it from `REJECTED` to `DRAFT`
        (`ERR_DMR_NOT_REJECTED` from any other status)".

        Design: Corner/state_machines/dmr_revise_from_draft_rejected
        """
        permit = create_permit(permit_number="NPDES-SM24")
        outfall = create_outfall(permit["id"])
        dmr = create_dmr(outfall["id"])
        resp = api.revise_dmr(dmr["id"], CO1)
        validate_error(resp, ApiErrorId.ERR_DMR_NOT_REJECTED)

    def test_error_dmr_monitoring_incomplete_on_certify(self, api):
        """PRD §3.5: "the `monitoring_completeness_ratio` must be at least 0.5
        (`ERR_DMR_MONITORING_INCOMPLETE`, HTTP 422)" and "below 0.5 is INCOMPLETE
        and blocks certification."

        Design: Corner/errors/error_dmr_monitoring_incomplete_on_certify
        """
        env = create_active_permit(
            permit_number="NPDES-ERR10", monitoring_frequency="MONTHLY"
        )
        dmr = create_dmr(env["outfall"]["id"])  # 1 required sample, 0 validated
        assert dmr["required_sample_count"] == 1
        assert dmr["monitoring_completeness_ratio"] == pytest.approx(0.0)

        resp = api.certify_dmr(dmr["id"], CO2)
        validate_error(resp, ApiErrorId.ERR_DMR_MONITORING_INCOMPLETE)

    def test_error_dmr_exceedances_unresolved_on_certify(self, api):
        """PRD §3.5: "every exceedance of this outfall detected within the period
        must be at least orally notified — its `notification_status` one of
        `ORAL_NOTIFIED`, `WRITTEN_OVERDUE`, `WRITTEN_FILED` or `CLOSED`
        (`ERR_DMR_EXCEEDANCES_UNRESOLVED`)."

        Design: Corner/errors/error_dmr_exceedances_unresolved_on_certify
        """
        scenario = create_exceedance_scenario(
            permit_number="NPDES-ERR5", monitoring_frequency="MONTHLY"
        )  # exceedance is PENDING_ORAL, detected 2026-08-05 (inside the period)
        dmr = create_dmr(scenario["outfall"]["id"])
        assert dmr["monitoring_completeness_ratio"] >= 0.5, (
            "completeness is satisfied; only the exceedance gate blocks"
        )
        resp = api.certify_dmr(dmr["id"], CO2)
        validate_error(resp, ApiErrorId.ERR_DMR_EXCEEDANCES_UNRESOLVED)

    def test_error_dmr_exceedances_unresolved_on_submit(self, api):
        """PRD §3.5: "Submission requires `CERTIFIED` (`ERR_DMR_NOT_CERTIFIED`) and
        tightens the exceedance gate: every period exceedance must now have its
        written report filed, standing in `WRITTEN_FILED` or `CLOSED`
        (`ERR_DMR_EXCEEDANCES_UNRESOLVED`)."

        Design: Corner/errors/error_dmr_exceedances_unresolved_on_submit
        """
        scenario = create_exceedance_scenario(
            permit_number="NPDES-ERR6", monitoring_frequency="MONTHLY"
        )
        validate_success(api.notify_exceedance(scenario["exceedance"]["id"], CO1))
        dmr = create_dmr(scenario["outfall"]["id"])
        validate_success(api.certify_dmr(dmr["id"], CO2))  # ORAL_NOTIFIED passes certify

        resp = api.submit_dmr(dmr["id"], CO2)
        validate_error(resp, ApiErrorId.ERR_DMR_EXCEEDANCES_UNRESOLVED)

class TestDmrSegregationAndRoles:
    def test_sod_dmr_certifier_must_differ_from_preparer(self, api):
        """PRD §2.11: "A discharge monitoring report may not be certified by the
        officer who prepared it — the certifier's identifier must differ from
        `prepared_by_user_id`."

        Design: Corner/rbac/sod_dmr_certifier_must_differ_from_preparer
        """
        env = create_active_permit(
            permit_number="NPDES-RBAC6", monitoring_frequency="MONTHLY"
        )
        dmr = create_dmr(env["outfall"]["id"], officer_id="co-1")
        resp = api.certify_dmr(dmr["id"], CO1)  # same operator id as the preparer
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_rbac_compliance_officer_cannot_review_dmr(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target operation
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.5: "Agency review belongs to the `Regulator`".

        Design: Corner/rbac/rbac_compliance_officer_cannot_review_dmr
        """
        env, dmr = _dmr_in_submitted(api, "NPDES-RBAC4")
        resp = api.review_dmr(dmr["id"], {"decision": "ACCEPTED"}, CO1)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_priority_ordering_auth_beats_state(self, api):
        """PRD §2.8: "2. **Authorization** — the caller's role must be permitted on
        the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`)." precedes "6. **State-machine
        guards** — each transition's source-state preconditions (HTTP 409 errors
        throughout §3)."

        Design: Corner/validations/priority_ordering_auth_beats_state
        """
        env, dmr = _dmr_with_one_validated_result(api, "NPDES-VAL13")
        validate_success(api.certify_dmr(dmr["id"], CO2))  # now CERTIFIED (not DRAFT)

        resp = api.certify_dmr(dmr["id"], make_field_sampler_headers("sampler-1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

# ─── Difficulty design: dual_variant_calc ────────────────────────────────────

def _two_result_monthly_avg_dmr(api, permit_number, average_method,
                                scheduled_fors=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
                                collect_clock="2026-08-05T10:00:00Z",
                                analyzed_at="2026-08-06T09:00:00Z",
                                validate_clock="2026-08-06T09:30:00Z"):
    """One outfall with a TSS MONTHLY_AVG limit; two VALIDATED results of
    1.0 @ 4.0 MGD and 3.0 @ 1.0 MGD; one DMR for the August period.

    The clock instants are parameters because the logical clock is monotonic
    (PRD §2.5): a test running two of these scenarios on one server must give
    the second scenario later instants.
    """
    env = create_active_permit(
        permit_number=permit_number, parameter_code="TSS", limit_type="MONTHLY_AVG",
        limit_value=10.0, monitoring_frequency="MONTHLY", average_method=average_method,
    )
    create_validated_results(
        env["outfall"]["id"], "TSS",
        [
            {"scheduled_for": scheduled_fors[0], "reported_value": 1.0, "flow_mgd": 4.0},
            {"scheduled_for": scheduled_fors[1], "reported_value": 3.0, "flow_mgd": 1.0},
        ],
        collect_clock=collect_clock,
        analyzed_at=analyzed_at,
        validate_clock=validate_clock,
    )
    return env, create_dmr(env["outfall"]["id"])

def _tss_line(dmr):
    lines = [l for l in dmr["summary_lines"] if l["parameter_code"] == "TSS"]
    assert len(lines) == 1, "exactly one summary line for TSS"
    return lines[0]

class TestDmrMonthlyAverageVariants:
    def test_dmr_monthly_average_arithmetic_variant(self, api):
        """PRD §3.5: "under `ARITHMETIC` it is the plain mean of the comparison
        values (each result's `reported_value`, or its `method_detection_limit` when
        `BELOW_MDL`), rounded half-up to three decimal places" and "two results of
        1.0 at 4.0 MGD and 3.0 at 1.0 MGD give an arithmetic average of 2.000".

        Design: Difficulty/dual_variant_calc/dmr_monthly_average_arithmetic_vs_flow_weighted
        """
        env, dmr = _two_result_monthly_avg_dmr(api, "NPDES-DV1A", "ARITHMETIC")
        line = _tss_line(dmr)
        assert line["sample_count"] == 2
        assert line["avg_concentration"] == pytest.approx(2.0, abs=0.0001), (
            "ARITHMETIC: (1.0 + 3.0) / 2 = 2.000"
        )
        assert line["exceeds_limit"] is False, "2.000 does not exceed the 10.0 limit"

    def test_dmr_monthly_average_flow_weighted_variant_diverges(self, api):
        """PRD §3.5: "under `FLOW_WEIGHTED` each comparison value is multiplied by
        its result's `flow_mgd`, the products are summed and divided by the sum of
        the flows, and the quotient is rounded half-up to three decimal places —
        identical inputs produce a different average whenever flows are non-uniform
        (two results of 1.0 at 4.0 MGD and 3.0 at 1.0 MGD give an arithmetic average
        of 2.000 but a flow-weighted average of 1.400)."

        Design: Difficulty/dual_variant_calc/dmr_monthly_average_arithmetic_vs_flow_weighted
        """
        env_a, dmr_a = _two_result_monthly_avg_dmr(api, "NPDES-DV1B", "ARITHMETIC")
        # Later August instants: the logical clock is monotonic (PRD §2.5), so the
        # second scenario must advance past the first scenario's validate clock.
        env_b, dmr_b = _two_result_monthly_avg_dmr(
            api, "NPDES-DV1C", "FLOW_WEIGHTED",
            scheduled_fors=("2026-08-12T08:00:00Z", "2026-08-12T09:00:00Z"),
            collect_clock="2026-08-12T10:00:00Z",
            analyzed_at="2026-08-13T09:00:00Z",
            validate_clock="2026-08-13T09:30:00Z",
        )
        assert _tss_line(dmr_a)["avg_concentration"] == pytest.approx(2.0, abs=0.0001)
        assert _tss_line(dmr_b)["avg_concentration"] == pytest.approx(1.4, abs=0.0001), (
            "FLOW_WEIGHTED: (1.0*4.0 + 3.0*1.0) / (4.0 + 1.0) = 1.400"
        )
        assert _tss_line(dmr_b)["exceeds_limit"] is False

# ─── Difficulty design: combinatorial_formula (loading rounding) ─────────────

def _loading_rounding_dmr(api, permit_number):
    """Two VALIDATED TSS results of 1.0 MG_L at flows 0.0324 and 0.0323 MGD —
    the PRD's pinned-rounding boundary data."""
    env = create_active_permit(
        permit_number=permit_number, parameter_code="TSS", limit_type="DAILY_MAX",
        limit_value=10.0, monitoring_frequency="MONTHLY",
    )
    create_validated_results(
        env["outfall"]["id"], "TSS",
        [
            {"scheduled_for": "2026-08-05T08:00:00Z", "reported_value": 1.0, "flow_mgd": 0.0324},
            {"scheduled_for": "2026-08-05T09:00:00Z", "reported_value": 1.0, "flow_mgd": 0.0323},
        ],
        collect_clock="2026-08-05T10:00:00Z",
        analyzed_at="2026-08-06T09:00:00Z",
        validate_clock="2026-08-06T09:30:00Z",
    )
    return env, create_dmr(env["outfall"]["id"])

class TestDmrPollutantLoadingRounding:
    def test_dmr_loading_per_sample_round_then_sum(self, api):
        """PRD §3.5: "first each contributing result's per-sample load — its
        comparison value times its `flow_mgd` times 3.785 — is rounded half-up to
        three decimal places; then those rounded per-sample loads are summed and the
        total is rounded half-up to two decimal places. Rounding only once after
        summing raw loads is forbidden, because it diverges on boundary data:
        per-sample loads of 0.122634 and 0.1222555 round to 0.123 and 0.122
        respectively, summing to a pinned total of 0.25, whereas rounding the raw
        sum of 0.2448895 once would yield 0.24."

        Design: Difficulty/combinatorial_formula/dmr_loading_per_sample_round_then_sum
        """
        env, dmr = _loading_rounding_dmr(api, "NPDES-CF1A")
        line = _tss_line(dmr)
        assert line["total_loading_kg"] == pytest.approx(0.25, abs=0.0001), (
            "pinned order: round3(0.122634)+round3(0.1222555) = 0.123+0.122 -> 0.25"
        )

    def test_dmr_loading_boundary_line_companions(self, api):
        """PRD §3.5: "`sample_count` is the number of validated results contributing
        to the line" and "The average follows the parameter limit's `average_method`:
        under `ARITHMETIC` it is the plain mean of the comparison values".

        Design: Difficulty/combinatorial_formula/dmr_loading_per_sample_round_then_sum
        """
        env, dmr = _loading_rounding_dmr(api, "NPDES-CF1B")
        line = _tss_line(dmr)
        assert line["sample_count"] == 2
        assert line["avg_concentration"] == pytest.approx(1.0, abs=0.0001)
        assert line["max_concentration"] == pytest.approx(1.0, abs=0.0001)

# ─── Difficulty design: combinatorial_formula (tiered completeness) ──────────

def _tiered_ratio_scenario(api, permit_number):
    """BOD5 WEEKLY + TSS MONTHLY limits; three validated BOD5 results; August
    period -> required ceil(31/7) + 1 = 6, validated 3, ratio exactly 0.5."""
    permit = create_permit(permit_number=permit_number)
    outfall = create_outfall(permit["id"])
    create_effluent_limit(
        outfall["id"], parameter_code="BOD5", limit_type="DAILY_MAX",
        limit_value=5.0, monitoring_frequency="WEEKLY",
    )
    create_effluent_limit(
        outfall["id"], parameter_code="TSS", limit_type="DAILY_MAX",
        limit_value=10.0, monitoring_frequency="MONTHLY",
    )
    issue_permit(permit["id"])
    for day, analyzed_day in (("05", "06"), ("12", "13"), ("19", "20")):
        create_validated_result(
            outfall["id"], "BOD5", 0.5,
            scheduled_for=f"2026-08-{day}T08:00:00Z",
            collect_clock=f"2026-08-{day}T09:00:00Z",
            analyzed_at=f"2026-08-{analyzed_day}T09:00:00Z",
            validate_clock=f"2026-08-{analyzed_day}T09:30:00Z",
        )
    return permit, outfall

class TestMonitoringCompletenessTiers:
    def test_monitoring_completeness_tiered_ratio_fields(self, api):
        """PRD §3.5: "a `WEEKLY` limit requires the period's day count divided by
        seven and rounded up to a whole number of samples; a `MONTHLY` limit requires
        one sample per calendar month the period touches. `required_sample_count` is
        the sum of these per-parameter requirements." and
        "`monitoring_completeness_ratio` is the total divided by the required count,
        rounded half-up to four decimal places".

        Design: Difficulty/combinatorial_formula/monitoring_completeness_tiered_ratio
        """
        permit, outfall = _tiered_ratio_scenario(api, "NPDES-CF2A")
        dmr = create_dmr(outfall["id"])
        assert dmr["required_sample_count"] == 6, (
            "ceil(31/7) = 5 weekly BOD5 + 1 monthly TSS"
        )
        assert dmr["total_validated_results"] == 3
        assert dmr["monitoring_completeness_ratio"] == pytest.approx(0.5, abs=0.00005), (
            "3 / 6 lands exactly on the DEFICIENT tier lower bound"
        )

    def test_monitoring_completeness_tiered_ratio_certification_allowed(self, api):
        """PRD §3.5: "The ratio falls into three tiers: at least 1.0 is COMPLETE;
        at least 0.5 but below 1.0 is DEFICIENT, in which certification is still
        permitted; below 0.5 is INCOMPLETE and blocks certification."
        PRD §3.5: "Certification records `certified_by_user_id`, moves the report
        `DRAFT → CERTIFIED`".

        Design: Difficulty/combinatorial_formula/monitoring_completeness_tiered_ratio
        """
        permit, outfall = _tiered_ratio_scenario(api, "NPDES-CF2B")
        dmr = create_dmr(outfall["id"], officer_id="co-1")
        certified = validate_success(api.certify_dmr(dmr["id"], CO2))
        assert certified["status"] == "CERTIFIED", "ratio exactly 0.5 permits certification"
        assert certified["certified_by_user_id"] == "co-2"
