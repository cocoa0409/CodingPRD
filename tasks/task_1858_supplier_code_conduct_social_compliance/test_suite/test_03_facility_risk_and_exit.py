"""Facility risk scoping (baseline vs history-adjusted variants) and exit gates."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_facility,
    assert_fee_review,
    cancel_audit,
    confirm_violation,
    create_auditor,
    create_facility,
    create_fee_review,
    decide_audit,
    fee_item,
    get_scoping,
    parse_instant,
    record_finding,
    record_interviews,
    schedule_audit,
    setup_active_supplier,
    setup_in_progress_audit,
    submit_report,
    validate_error,
    validate_success,
)


def run_risk_scenario():
    """BD / APPAREL / 1200-worker facility, audit [2026-09-01, 2026-09-03)
    completed with 2 MAJOR + 1 MINOR findings (no zero-tolerance).

    Returns (pre_scoping, post_scoping): the facility scoping read before the
    audit reaches its terminal state and after COMPLETED.
    """
    ctx = setup_in_progress_audit(
        sector="APPAREL",
        supplier_country="BD",
        facility_country="BD",
        worker_count=1200,
        zt_categories=("FORCED_LABOR", "CHILD_LABOR"),
        scheduled_end="2026-09-03T00:00:00Z",
        auditor_countries=("BD", "US"),
        supplier_name="Acme Apparel Ltd",
        facility_name="Dhaka Plant 1",
    )
    pre = get_scoping(ctx["facility"]["id"])
    record_interviews(
        ctx["audit"]["id"], ctx["auditor"]["id"], interview_count=35
    )
    for classification, category in (
        ("MAJOR", "WORKING_HOURS"),
        ("MAJOR", "WAGES"),
        ("MINOR", "HEALTH_SAFETY"),
    ):
        record_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"],
            classification=classification, category=category,
            description=f"{classification} {category} finding",
        )
    submit_report(ctx["audit"]["id"], ctx["auditor"]["id"])
    decide_audit(ctx["audit"]["id"], "COMPLETE")
    post = get_scoping(ctx["facility"]["id"])
    return pre, post


class TestFacilityComputedAtCreation:
    def test_facility_computed_fields_override_client_input(self, api):
        """PRD §3.2: "At creation the system computes the facility's baseline
        risk. The `risk_score_baseline` is the country exposure of the site's
        `country_code`, multiplied by the sector multiplier of the owning
        supplier's `sector`, plus a workforce factor derived from
        `worker_count`. Country exposures are: BD 60, IN 55, VN 50, CN 40,
        TR 35, US 10. Sector multipliers are: `APPAREL` 1.2, `ELECTRONICS` 1.1,
        `FOOD` 1.0, `HARDLINES` 0.9. The workforce factor adds 15 when the site
        employs at least 1000 workers, 8 when it employs at least 300 but fewer
        than 1000, and 3 when it employs fewer than 300."
        PRD §3.2: "Until the facility's first terminal audit,
        `risk_score_history` is null"

        Design: Corner/entities/facility_computed_fields_input_ignored
        """
        ctx = setup_active_supplier(
            sector="APPAREL", supplier_country="BD", legal_name="Tango Apparel"
        )
        payload = {
            "supplier_id": ctx["supplier"]["id"],
            "name": "Gazipur Unit",
            "country_code": "BD",
            "worker_count": 1200,
            "processes": ["sewing"],
            # Client-planted values for server-computed fields must not win.
            "risk_tier": "LOW",
            "risk_score_baseline": 0,
        }
        facility = validate_success(api.create_facility(payload, ADMIN), 201)
        assert_facility(facility)
        # BD 60 * APPAREL 1.2 + 15 (>= 1000 workers) = 87.0
        assert facility["risk_score_baseline"] == pytest.approx(87.0, abs=0.01)
        assert facility["risk_tier"] == "HIGH", "87.0 >= 70 -> HIGH"
        assert facility["risk_score_history"] is None, (
            "no terminal audit yet: the history variant has not activated"
        )
        assert facility["next_audit_interval_months"] == 6, (
            "tier base HIGH is 6 months"
        )
        assert facility["status"] == "ACTIVE"


class TestFacilityRiskDualVariant:
    def test_risk_baseline_then_history_on_first_terminal_audit(self, api):
        """PRD §3.2: "Once any audit of the facility reaches a terminal state —
        `COMPLETED` or `FAILED_ZT` — the history-adjusted variant activates. Its
        history component counts the facility's findings on terminal audits that
        have not been voided, weighted 10 per `ZERO_TOLERANCE`, 4 per `MAJOR`,
        and 1 per `MINOR`, capped at 100. The `risk_score_history` is then the
        blend of one half baseline and one half history component, rounded half
        up to one decimal place."
        PRD §3.2: "The `risk_tier` derives from the applicable score — the
        history variant once available, the baseline otherwise: `HIGH` at 70 or
        above, `MEDIUM` at 40 or above, otherwise `LOW`, with the band
        boundaries inclusive on their lower bounds."

        Design: Difficulty/dual_variant_calc/facility_risk_baseline_vs_history_adjusted
        """
        pre, post = run_risk_scenario()
        # Baseline variant before any terminal audit: 60*1.2 + 15 = 87.0.
        assert pre["risk_score_baseline"] == pytest.approx(87.0, abs=0.01)
        assert pre["risk_tier"] == "HIGH"
        assert pre["risk_score_history"] is None, (
            "the baseline variant applies before any terminal audit"
        )
        assert pre["next_audit_interval_months"] == 6

        # History component = min(100, 10*0 + 4*2 + 1*1) = 9;
        # history = round_half_up(0.5*87.0 + 0.5*9, 1) = 48.0.
        assert post["risk_score_baseline"] == pytest.approx(87.0, abs=0.01), (
            "identical facility inputs keep the baseline variant unchanged"
        )
        assert post["risk_score_history"] == pytest.approx(48.0, abs=0.01)
        assert post["risk_tier"] == "MEDIUM", (
            "48.0 >= 40 and < 70 -> MEDIUM: the tier flips purely because the "
            "applicable variant switched at the terminal transition"
        )

    def test_risk_history_variant_recomputes_interval_and_due_date(self, api):
        """PRD §3.2: "The `next_audit_interval_months` starts from the tier base
        — `HIGH` 6 months, `MEDIUM` 12, `LOW` 24"
        PRD §3.2: "The `next_audit_due_date` is the latest terminal audit's
        `scheduled_end` shifted forward by that interval in months, and stays
        null while the facility has no terminal audit."
        PRD §3.2: "The interval and due date recompute at facility creation,
        whenever an audit of the facility reaches a terminal state, and whenever
        a mutual-recognition claim is accepted"

        Design: Difficulty/dual_variant_calc/facility_risk_baseline_vs_history_adjusted
        """
        pre, post = run_risk_scenario()
        assert pre["next_audit_due_date"] is None, (
            "no terminal audit yet: no due date"
        )
        assert post["next_audit_interval_months"] == 12, (
            "MEDIUM tier base is 12 months"
        )
        # Latest terminal audit scheduled_end 2026-09-03 + 12 months.
        assert parse_instant(post["next_audit_due_date"]) == datetime(
            2027, 9, 3, tzinfo=timezone.utc
        )


class TestFacilityExit:
    def test_facility_exit_blocked_by_open_audit(self, api):
        """PRD §3.2: "Exit is blocked while any audit at the facility is
        `SCHEDULED`, `IN_PROGRESS`, or `REPORT_SUBMITTED`
        (`ERR_AUDIT_ALREADY_OPEN`)"
        PRD §3.2: "A successful exit moves the facility `ACTIVE → EXITED`, which
        is terminal"

        Design: Corner/validations/facility_exit_with_open_audit_rejected
        """
        ctx = setup_active_supplier(legal_name="Lima C", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site M2")
        auditor = create_auditor()
        audit = schedule_audit(facility["id"], auditor["id"])
        assert audit["status"] == "SCHEDULED"

        blocked = api.exit_facility(
            facility["id"], {"exit_reason": "Close site"}, ADMIN
        )
        validate_error(blocked, ApiErrorId.ERR_AUDIT_ALREADY_OPEN)

        cancel_audit(audit["id"], reason="Site closing")
        exited = validate_success(
            api.exit_facility(facility["id"], {"exit_reason": "Close site"}, ADMIN)
        )
        assert exited["status"] == "EXITED"

    def test_facility_exit_blocked_by_outstanding_reimbursement(self, api):
        """PRD §3.2: "and while any fee review on the facility's audits is
        `VIOLATION_CONFIRMED` with `outstanding_reimbursement_cents` above zero
        (`ERR_OUTSTANDING_REIMBURSEMENT`)."

        Design: Corner/validations/facility_exit_with_outstanding_reimbursement_rejected
        """
        ctx = setup_in_progress_audit(supplier_name="Mike C",
                                      facility_name="Site L2")
        record_interviews(ctx["audit"]["id"], ctx["auditor"]["id"],
                          interview_count=4)
        review = create_fee_review(
            ctx["audit"]["id"], ctx["auditor"]["id"],
            workers_assessed=1, fee_items=[fee_item()],
        )
        review = confirm_violation(review["id"])
        assert_fee_review(review)
        assert review["status"] == "VIOLATION_CONFIRMED"
        assert review["outstanding_reimbursement_cents"] == 3, (
            "one 300-BDT item rounds to 3 cents of outstanding reimbursement"
        )
        # Complete the audit so the open-audit gate no longer applies; only the
        # fiscal gate can fire.
        submit_report(ctx["audit"]["id"], ctx["auditor"]["id"])
        decide_audit(ctx["audit"]["id"], "COMPLETE")

        resp = api.exit_facility(
            ctx["facility"]["id"], {"exit_reason": "Close site"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_REIMBURSEMENT)
