"""Monthly assessment runs and the assessed-dues calculation (both variants)."""
import pytest

from test_helpers import (
    ST,
    ApiErrorId,
    add_remittance_line,
    assert_assessment,
    assert_assessment_run,
    create_assessment_run_payload,
    get_member,
    get_success_data,
    make_assessment_run,
    make_classification,
    make_employer,
    make_local,
    make_member,
    make_remittance,
    reconcile_remittance,
    run_period,
    set_clock,
    setup_flat_local_with_journeyman,
    setup_pct_local_with_journeyman,
    validate_error,
    validate_success,
)


def _only_assessment(api, member_id):
    data = get_success_data(api.list_member_assessments(member_id, ST))
    assert len(data) == 1, f"expected exactly one assessment, got {len(data)}"
    return data[0]


class TestAssessmentRuns:
    def test_assessment_run_computed_counts(self, api):
        """PRD section on assessment runs: "The immutable run record reports
        `assessments_created_count` and `assessments_finalized_count`", and "any
        `PROVISIONAL` assessment from a period earlier than the run period for
        which no wages were ever reported is finalized with a wage base of
        zero."

        Design: Corner/entities/assessment_run_computed_counts
        """
        local, cls = setup_flat_local_with_journeyman()
        make_member(local["id"], cls["id"], full_name="Batch Bill", member_number="M-001")
        make_member(local["id"], cls["id"], full_name="Batch Barb", member_number="M-002")
        run_period(local["id"], "2026-05")
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_assessment_run(
            create_assessment_run_payload(local["id"], "2026-06"), ST
        )
        run = validate_success(resp, 201)
        assert_assessment_run(run)
        assert run["assessments_created_count"] == 2, "both members assessed for 2026-06"
        assert run["assessments_finalized_count"] == 2, (
            "both members' stale 2026-05 provisionals finalized at wage base zero"
        )

    def test_duplicate_assessment_run_rejected(self, api):
        """PRD section on assessment runs: "only one run may exist per local and
        period, with repeats rejected as `ERR_ASSESSMENT_RUN_EXISTS`".

        Design: Corner/errors/duplicate_assessment_run_rejected
        """
        local = make_local("FLAT", name="Local 200")
        set_clock("2026-08-01T00:00:00Z")
        payload = create_assessment_run_payload(local["id"], "2026-08")
        validate_success(api.create_assessment_run(payload, ST), 201)
        resp = api.create_assessment_run(payload, ST)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_RUN_EXISTS)

    def test_future_period_run_rejected(self, api):
        """PRD section on assessment runs: "the period must be a well-formed
        `YYYY-MM` string no later than the current clock period, otherwise the
        run is rejected with `ERR_INVALID_PERIOD`".

        Design: Corner/errors/future_period_run_rejected
        """
        local = make_local("FLAT", name="Local 200")
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_assessment_run(
            create_assessment_run_payload(local["id"], "2026-12"), ST
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)


class TestAssessedDuesVariants:
    """The provisional and final variants of the same formula disagree on the
    same member-period when reported wages differ from the floor."""

    def _setup_provisional_then_remittance(self, api):
        local, cls = setup_pct_local_with_journeyman(
            local_name="Local 100", max_monthly_dues_cents=20000
        )
        emp = make_employer("Acme Widgets")
        member = make_member(
            local["id"], cls["id"], employer_id=emp["id"],
            full_name="Pat Journeyman", member_number="M-001",
        )
        set_clock("2026-08-01T00:00:00Z")
        make_assessment_run(local["id"], "2026-08")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 18000)
        add_remittance_line(rem["id"], member["id"], 18000, 900000)
        return local, member, rem

    def test_provisional_variant_lands_at_floor(self, api):
        """PRD section on the dues calculation: "the wage base is the gross
        wages of the member's most recent `FINAL` assessment from an earlier
        period, or zero when the member has none — which typically lands the
        provisional at the floor." With floor 3000 and no prior FINAL, the
        provisional assesses at 3000.

        Design: Difficulty/dual_variant_calc/assessed_dues_provisional_vs_final_diverge
        """
        local, member, rem = self._setup_provisional_then_remittance(api)
        assessment = _only_assessment(api, member["id"])
        assert_assessment(assessment)
        assert assessment["status"] == "PROVISIONAL"
        assert assessment["assessed_cents"] == 3000, (
            "zero wage base under PERCENTAGE_OF_GROSS lands at the 3000 floor"
        )

    def test_final_variant_uses_reported_wages_and_diverges(self, api):
        """PRD section on the dues calculation: "under `PERCENTAGE_OF_GROSS` the
        base is the gross wages in cents multiplied by the resolved basis-point
        rate divided by ten thousand, rounded half up to whole cents", and the
        final variant "takes the actual reported gross wages from the remittance
        line". 900000 x 200 / 10000 = 18000, diverging from the 3000
        provisional.

        Design: Difficulty/dual_variant_calc/assessed_dues_provisional_vs_final_diverge
        """
        local, member, rem = self._setup_provisional_then_remittance(api)
        reconcile_remittance(rem["id"])
        assessment = _only_assessment(api, member["id"])
        assert assessment["status"] == "FINAL"
        assert assessment["gross_wages_cents"] == 900000
        assert assessment["assessed_cents"] == 18000
        assert assessment["assessed_cents"] != 3000, (
            "the two variants disagree by exactly the reported-wages difference"
        )


class TestAssessedDuesClampBranches:
    """One reconcile exercises the cap, the unclamped middle, the floor, and a
    classification rate override."""

    def _setup_four_member_reconcile(self, api):
        local = make_local("PCT", name="Local 100")
        clsj = make_classification(
            local["id"], "JOURNEYMAN", 3000, max_monthly_dues_cents=20000
        )
        clsa = make_classification(
            local["id"], "APPRENTICE", 2000, dues_percent_bp=150
        )
        emp = make_employer("Acme Widgets")
        members = {}
        for key, cls_id, name, number in (
            ("cap", clsj["id"], "Cap Casey", "M-001"),
            ("mid", clsj["id"], "Mid Mike", "M-002"),
            ("floor", clsj["id"], "Floor Flo", "M-003"),
            ("app", clsa["id"], "App Andy", "M-004"),
        ):
            members[key] = make_member(
                local["id"], cls_id, employer_id=emp["id"],
                full_name=name, member_number=number,
            )
        set_clock("2026-08-01T00:00:00Z")
        make_assessment_run(local["id"], "2026-08")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 48500)
        add_remittance_line(rem["id"], members["cap"]["id"], 20000, 1500000)
        add_remittance_line(rem["id"], members["mid"]["id"], 18000, 900000)
        add_remittance_line(rem["id"], members["floor"]["id"], 3000, 100000)
        add_remittance_line(rem["id"], members["app"]["id"], 7500, 500000)
        resp = api.reconcile_remittance(rem["id"], ST)
        reconciled = validate_success(resp, 200)
        return members, reconciled

    def test_cap_and_unclamped_branches(self, api):
        """PRD section on the dues calculation: "The result is then clamped:
        raised to the floor when it falls below `min_monthly_dues_cents`, and,
        when a cap exists, lowered to the cap when it exceeds
        `max_monthly_dues_cents`." Raw 30000 clamps to the 20000 cap; raw 18000
        stands unclamped.

        Design: Difficulty/combinatorial_formula/assessed_dues_clamp_branches
        """
        members, reconciled = self._setup_four_member_reconcile(api)
        assert reconciled["status"] == "RECONCILED", "every line matched its FINAL assessment"
        a_cap = _only_assessment(api, members["cap"]["id"])
        a_mid = _only_assessment(api, members["mid"]["id"])
        assert a_cap["assessed_cents"] == 20000, "raw 30000 lowered to the 20000 cap"
        assert a_cap["max_applied_cents"] == 20000
        assert a_mid["assessed_cents"] == 18000, "raw 18000 inside [floor, cap] stands"

    def test_floor_and_override_rate_branches(self, api):
        """PRD section on the dues calculation: "the percentage rate is the
        classification's `dues_percent_bp` when set, otherwise the local's
        `default_dues_percent_bp`". Raw 2000 raises to the 3000 floor; the
        apprentice override of 150bp yields 500000 x 150 / 10000 = 7500 with no
        cap.

        Design: Difficulty/combinatorial_formula/assessed_dues_clamp_branches
        """
        members, _ = self._setup_four_member_reconcile(api)
        a_floor = _only_assessment(api, members["floor"]["id"])
        a_app = _only_assessment(api, members["app"]["id"])
        assert a_floor["assessed_cents"] == 3000, "raw 2000 raised to the 3000 floor"
        assert a_floor["min_applied_cents"] == 3000
        assert a_app["assessed_cents"] == 7500, "override 150bp applied to gross 500000"
        assert a_app["rate_bp_applied"] == 150
        assert a_app["max_applied_cents"] is None, "uncapped classification pins null cap"


class TestRateResolution:
    def test_assessment_rate_resolution_inherits_local_defaults(self, api):
        """PRD section on the dues calculation: "the percentage rate is the
        classification's `dues_percent_bp` when set, otherwise the local's
        `default_dues_percent_bp`", and "`rate_bp_applied` records the resolved
        percentage rate and is null when the `FLAT_RATE` branch was used".
        400000 x 200 / 10000 = 8000.

        Design: Corner/calculations/assessment_rate_resolution_inherits_local_defaults
        """
        local = make_local("PCT", name="Local 100")
        cls = make_classification(local["id"], "JOURNEYMAN", 0)
        emp = make_employer("Acme Widgets")
        member = make_member(
            local["id"], cls["id"], employer_id=emp["id"],
            full_name="Inherit Irene", member_number="M-001",
        )
        set_clock("2026-08-01T00:00:00Z")
        make_assessment_run(local["id"], "2026-08")
        rem = make_remittance(emp["id"], local["id"], "2026-08", 8000)
        add_remittance_line(rem["id"], member["id"], 8000, 400000)
        reconcile_remittance(rem["id"])
        assessment = _only_assessment(api, member["id"])
        assert assessment["rate_bp_applied"] == 200, "inherited the local default rate"
        assert assessment["assessed_cents"] == 8000
        assert assessment["status"] == "FINAL"
