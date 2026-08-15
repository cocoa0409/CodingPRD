"""Findings: the zero-tolerance fast lane, tallies, voiding, due dates."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    OFFICER,
    TEST_USERS,
    ApiErrorId,
    assert_audit_tally_conservation,
    assert_finding,
    get_finding,
    get_scorecard,
    get_supplier,
    make_auditor_headers,
    parse_instant,
    record_finding,
    setup_in_progress_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["audit_coordinator_headers"]


def zt_scenario():
    """BD / APPAREL / 1200-worker program with an IN_PROGRESS SEMI_ANNOUNCED
    audit; MINOR then MAJOR findings already recorded."""
    ctx = setup_in_progress_audit(
        sector="APPAREL", supplier_country="BD", facility_country="BD",
        worker_count=1200, zt_categories=("FORCED_LABOR", "CHILD_LABOR"),
        announcement="SEMI_ANNOUNCED", scheduled_start="2026-09-01T00:00:00Z",
        scheduled_end="2026-09-20T00:00:00Z", auditor_countries=("BD",),
        supplier_name="Golf Apparel", facility_name="Narayanganj Unit",
    )
    minor = record_finding(
        ctx["audit"]["id"], ctx["auditor"]["id"], classification="MINOR",
        category="ENVIRONMENT", description="Waste log incomplete",
    )
    major = record_finding(
        ctx["audit"]["id"], ctx["auditor"]["id"], classification="MAJOR",
        category="WAGES", description="Piece-rate records missing",
    )
    return ctx, minor, major


class TestZeroToleranceCascade:
    def test_zt_finding_auto_fails_audit_and_tallies(self, api):
        """PRD §3.4: "When a zero-tolerance finding is recorded on an
        `IN_PROGRESS` audit, a four-hop cascade fires synchronously: first the
        audit's `zt_count` tally recomputes upward by one; second the audit
        itself moves `IN_PROGRESS → FAILED_ZT`, because any zero-tolerance
        finding fails the audit outright"
        PRD §3.4: "Each audit keeps three tallies: `zt_count` for its non-voided
        `ZERO_TOLERANCE` findings, `major_count` for non-voided `MAJOR`, and
        `minor_count` for non-voided `MINOR`."

        Design: Difficulty/transitive_cascade/zt_finding_four_hop_cascade
        """
        ctx, minor, major = zt_scenario()
        zt = record_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"],
            classification="ZERO_TOLERANCE", category="CHILD_LABOR",
            description="Underage worker on line",
        )
        assert_finding(zt)
        assert zt["status"] == "OPEN"

        audit = validate_success(api.get_audit(ctx["audit"]["id"], OFFICER))
        assert audit["zt_count"] == 1, "hop 1: zt tally recomputes upward"
        assert audit["major_count"] == 1 and audit["minor_count"] == 1, (
            "prior tallies are preserved by the cascade"
        )
        assert audit["status"] == "FAILED_ZT", (
            "hop 2: any zero-tolerance finding fails the audit outright"
        )
        assert_audit_tally_conservation(audit, 3)

    def test_zt_finding_cascades_to_scorecard_and_status(self, api):
        """PRD §3.4: "third the supplier scorecard recomputes, both variants
        dropping 40 points for the newly open zero-tolerance finding; fourth the
        supplier moves `ACTIVE → PROBATION` under the open-zero-tolerance rule
        of §3.6."
        PRD §3.6: "The `consequence_tier` maps the verified score onto business
        consequences: `PREFERRED` at 80 or above; `QUALIFIED` from 60 up to 79;
        `PROBATION_WATCH` from 40 up to 59; and `SOURCING_EXIT` below 40, with
        each band inclusive on its lower bound."

        Design: Difficulty/transitive_cascade/zt_finding_four_hop_cascade
        """
        ctx, minor, major = zt_scenario()
        assert ctx["supplier"]["status"] == "ACTIVE"
        record_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"],
            classification="ZERO_TOLERANCE", category="CHILD_LABOR",
            description="Underage worker on line",
        )
        scorecard = get_scorecard(ctx["supplier"]["id"])
        # 100 - 40 (open ZT) - 10 (open MAJOR) - 3 (open MINOR) = 47.
        assert scorecard["verified_score"] == 47
        assert scorecard["provisional_score"] == 47, (
            "all findings are OPEN, so the two variants coincide"
        )
        assert scorecard["consequence_tier"] == "PROBATION_WATCH", (
            "47 lies in the [40, 59] band"
        )
        supplier = get_supplier(ctx["supplier"]["id"])
        assert supplier["status"] == "PROBATION", (
            "hop 4: an OPEN zero-tolerance finding drops ACTIVE -> PROBATION"
        )


class TestTallyConservationOnVoid:
    def test_audit_tally_conservation_across_record_and_void(self, api):
        """PRD §3.4: "The three always sum to the audit's total number of
        non-voided findings; recording a finding and voiding it are the
        compensating pair that keeps this quantity conserved."
        PRD §3.4: "Voiding moves the finding `OPEN → VOIDED`, which is terminal;
        the audit tallies recompute with the finding excluded"

        Design: Difficulty/compensating_invariant/audit_finding_tally_conservation_on_void
        """
        ctx, minor, major = zt_scenario()
        record_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"],
            classification="ZERO_TOLERANCE", category="CHILD_LABOR",
            description="Underage worker on line",
        )
        before = validate_success(api.get_audit(ctx["audit"]["id"], OFFICER))
        assert before["status"] == "FAILED_ZT"
        assert (before["zt_count"], before["major_count"],
                before["minor_count"]) == (1, 1, 1)
        assert_audit_tally_conservation(before, 3)

        voided = validate_success(
            api.void_finding(
                minor["id"],
                {"void_justification": "Evidence mis-attributed to this site"},
                make_auditor_headers(ctx["auditor"]["id"]),
            )
        )
        assert voided["status"] == "VOIDED"
        after = validate_success(api.get_audit(ctx["audit"]["id"], OFFICER))
        assert (after["zt_count"], after["major_count"],
                after["minor_count"]) == (1, 1, 0), (
            "the voided MINOR drops out of the tally"
        )
        assert_audit_tally_conservation(after, 2)

    def test_void_restores_scorecard_and_keeps_record(self, api):
        """PRD §3.4: "the supplier scorecard recomputes with both variants
        restoring the finding's deduction"
        PRD §3.4: "The findings of an audit can be listed with filters on
        `classification` and `status`."

        Design: Difficulty/compensating_invariant/audit_finding_tally_conservation_on_void
        """
        ctx, minor, major = zt_scenario()
        record_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"],
            classification="ZERO_TOLERANCE", category="CHILD_LABOR",
            description="Underage worker on line",
        )
        validate_success(
            api.void_finding(
                minor["id"],
                {"void_justification": "Evidence mis-attributed to this site"},
                make_auditor_headers(ctx["auditor"]["id"]),
            )
        )
        scorecard = get_scorecard(ctx["supplier"]["id"])
        # 100 - 40 (open ZT) - 10 (open MAJOR); the voided MINOR's 3 points are
        # restored in both variants.
        assert scorecard["verified_score"] == 50
        assert scorecard["provisional_score"] == 50

        voided_list, _ = validate_paginated(
            api.list_audit_findings(
                ctx["audit"]["id"], OFFICER, params={"status": "VOIDED"}
            )
        )
        assert [f["id"] for f in voided_list] == [minor["id"]], (
            "the voided record remains listed, not deleted"
        )
        assert get_finding(minor["id"])["status"] == "VOIDED"


class TestFindingGuards:
    def test_zt_category_not_recognized_rejected(self, api):
        """PRD §3.4: "A finding may only be classified `ZERO_TOLERANCE` when its
        `category` appears in the `zero_tolerance_categories` of the supplier's
        current code version; anything else is rejected with
        `ERR_ZT_CATEGORY_NOT_RECOGNIZED` (422)."

        Design: Corner/validations/zt_category_not_recognized_rejected
        """
        ctx = setup_in_progress_audit(supplier_name="Zulu B", sector="FOOD",
                                      facility_name="Site Y2",
                                      zt_categories=("FORCED_LABOR",))
        audit_id = ctx["audit"]["id"]
        lead = make_auditor_headers(ctx["auditor"]["id"])
        resp = api.create_finding(
            audit_id,
            {"classification": "ZERO_TOLERANCE", "category": "WAGES",
             "description": "Misclassified ZT"},
            lead,
        )
        validate_error(resp, ApiErrorId.ERR_ZT_CATEGORY_NOT_RECOGNIZED, 422)
        reread = validate_success(api.get_audit(audit_id, OFFICER))
        assert reread["status"] == "IN_PROGRESS", (
            "a rejected zero-tolerance record does not auto-fail the audit"
        )
        assert reread["zt_count"] == 0

        ok = validate_success(
            api.create_finding(
                audit_id,
                {"classification": "MAJOR", "category": "WAGES",
                 "description": "Properly classified"},
                lead,
            ),
            201,
        )
        assert ok["classification"] == "MAJOR", "MAJOR + WAGES is valid"

    def test_finding_create_forbidden_for_compliance_officer(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; an attempt
        to perform an action outside the caller's designated role is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.4: "During an `IN_PROGRESS` audit, the assigned auditor records
        findings."

        Design: Corner/rbac/finding_create_forbidden_for_compliance_officer
        """
        ctx = setup_in_progress_audit(supplier_name="Romeo D", sector="FOOD",
                                      facility_name="Site H2",
                                      with_verifier=False)
        resp = api.create_finding(
            ctx["audit"]["id"],
            {"classification": "MAJOR", "category": "WAGES",
             "description": "Officer-recorded finding"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestRemediationDueDates:
    def test_remediation_due_date_by_classification(self, api):
        """PRD §3.4: "The finding's `remediation_due_date` is its `created_at`
        plus 30 days for `ZERO_TOLERANCE`, plus 90 days for `MAJOR`, and plus
        180 days for `MINOR`."
        PRD §2.8: "Remediation due dates are computed by day-granularity
        datetime addition onto the finding's `created_at`."

        Design: Corner/calculations/remediation_due_date_by_classification
        """
        ctx = setup_in_progress_audit(supplier_name="Kilo Goods", sector="FOOD",
                                      facility_name="Site L",
                                      zt_categories=("FORCED_LABOR",
                                                     "CHILD_LABOR"))
        audit_id = ctx["audit"]["id"]
        auditor_id = ctx["auditor"]["id"]
        # created_at is stamped from the logical clock, now 2026-09-01.
        base = datetime(2026, 9, 1, tzinfo=timezone.utc)

        minor = record_finding(audit_id, auditor_id, classification="MINOR",
                               category="ENVIRONMENT", description="Minor gap")
        major = record_finding(audit_id, auditor_id, classification="MAJOR",
                               category="WAGES", description="Major gap")
        zt = record_finding(audit_id, auditor_id,
                            classification="ZERO_TOLERANCE",
                            category="FORCED_LABOR", description="ZT gap")

        assert parse_instant(minor["remediation_due_date"]) == (
            base + timedelta(days=180)
        ), "MINOR: +180 days -> 2027-02-28"
        assert parse_instant(major["remediation_due_date"]) == (
            base + timedelta(days=90)
        ), "MAJOR: +90 days -> 2026-11-30"
        assert parse_instant(zt["remediation_due_date"]) == (
            base + timedelta(days=30)
        ), "ZERO_TOLERANCE: +30 days -> 2026-10-01"
