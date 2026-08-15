"""Cross-entity cascades: snapshot recertification depth-3 cascade and the
CAP-acceptance bubble-up (PRD §3.2, §3.9)."""

from test_helpers import (
    accept_cap,
    api_client,
    build_user_headers,
    certify_snapshot,
    charge_expenditure,
    create_snapshot,
    finalize_allocations,
    get_grant,
    issue_report,
    list_allocations_for,
    lock_rankings,
    open_grant,
    record_finding,
    register_school,
    setup_accepted_sns,
    setup_visit_in_progress,
    snapshot_entry,
    submit_cap,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")
MONITOR = build_user_headers("monitor-1", "SEAMonitor")


class TestSnapshotRecertificationCascade:

    def test_snapshot_recertification_cascade(self):
        """PRD §3.2: "A successful certification stamps `certified_at` and
        then cascades through three depths, atomically. At depth one, any
        other snapshot of the same grant currently in `CERTIFIED` flips to
        `SUPERSEDED` — the certified-cardinality invariant guarantees at most
        one certified snapshot per grant. At depth two, if the grant is
        `RANKING_LOCKED` or `ALLOCATED`, every school allocation of the grant
        is recomputed in place from the new snapshot: the ranking figures of
        §3.3 are re-derived, and when the grant is `ALLOCATED` the set-aside
        minimums, the equitable share, and the allocation waterfall of §3.4
        are re-run as well; any allocation that had been `CERTIFIED` flips
        back to `PENDING`, and newly active schools receive fresh `PENDING`
        rows (schools absent from the new entries cannot exist among the old
        rows, because coverage is total over active schools). At depth three,
        every SNS document in `ACCEPTED` whose allocation just flipped from
        `CERTIFIED` to `PENDING` flips to `STALE`, and every expenditure still
        in `PENDING_REVIEW` with `supplant_screen` set on such an allocation
        flips to `DISALLOWED` with `disallow_reason` stamped
        `SNS_STALE_CASCADE`."

        Design: Difficulty/transitive_cascade/snapshot_recertification_cascade
        """
        # Fully ALLOCATED grant with two schools: S1 400/500, S4 195/500.
        s1 = register_school("Alpha Elementary", "000001", grade_span_high=5)
        s4 = register_school("Delta Elementary", "000004", grade_span_high=5)
        grant = open_grant(2027, 100_000_000, admin_reserve_cents=5_000_000,
                           equitable_count_method="VERIFIED_COUNT")
        snap1 = create_snapshot(grant["id"], [snapshot_entry(s1["id"], 400, 500),
                                              snapshot_entry(s4["id"], 195, 500)])
        certify_snapshot(snap1["id"], grant["id"])
        lock_rankings(grant["id"])
        finalize_allocations(grant["id"])
        a1 = validate_success(api_client.list_allocations(
            DIRECTOR, params={"grant_id": grant["id"],
                              "school_id": s1["id"]}))[0]
        validate_success(api_client.certify_allocation(a1["id"], DIRECTOR))
        # ACCEPTED SNS documentation covering A1, and a supplant-screened
        # charge still in PENDING_REVIEW behind it.
        doc = setup_accepted_sns(a1["id"], methodology="PER_PUPIL_FORMULA")
        assert doc["status"] == "ACCEPTED"
        exp = charge_expenditure(
            get_grant(grant["id"]), 500_000, school_allocation_id=a1["id"],
            incurred_date="2026-11-01", description="interventionist stipend",
            supplant_screen=True)
        assert exp["status"] == "PENDING_REVIEW"

        # The recertification moves S4 to 205/500 = 4100 bp.
        snap2 = create_snapshot(grant["id"], [snapshot_entry(s1["id"], 400, 500),
                                              snapshot_entry(s4["id"], 205, 500)])
        certify_snapshot(snap2["id"], grant["id"])

        snap1_after = validate_success(api_client.get_snapshot(snap1["id"],
                                                               DIRECTOR))
        assert snap1_after["status"] == "SUPERSEDED"
        snap2_after = validate_success(api_client.get_snapshot(snap2["id"],
                                                               DIRECTOR))
        assert snap2_after["status"] == "CERTIFIED"

        a1_after = validate_success(api_client.get_allocation(a1["id"],
                                                              DIRECTOR))
        assert a1_after["status"] == "PENDING", \
            "CERTIFIED -> PENDING under the depth-two recompute"
        assert a1_after["poverty_pct_bp"] == 8000
        assert a1_after["supplement_ok"] is False, \
            "supplement_ok is recomputed to false alongside the STALE flip"
        a4_after = validate_success(api_client.list_allocations(
            DIRECTOR, params={"grant_id": grant["id"],
                              "school_id": s4["id"]}))[0]
        assert a4_after["poverty_pct_bp"] == 4100
        assert a4_after["program_model"] == "SCHOOLWIDE", \
            "S4 crossed the 4000 bp line"

        doc_after = validate_success(api_client.get_sns_document(doc["id"],
                                                                 DIRECTOR))
        assert doc_after["status"] == "STALE", \
            "depth three: the ACCEPTED document goes stale with its allocation"
        exp_after = validate_success(api_client.get_expenditure(exp["id"],
                                                                DIRECTOR))
        assert exp_after["status"] == "DISALLOWED"
        assert exp_after["disallow_reason"] == "SNS_STALE_CASCADE"

    def test_recertification_in_setup_has_no_cascade_targets(self):
        """PRD §3.2: "When the grant is still in `SETUP`, no allocations exist
        and the depth-two and depth-three cascades have nothing to touch."
        PRD §3.2: "Finally, the grant's `ranking_version` increments by one
        and its `version` increments by one, which is exactly what makes a
        concurrently drafted amendment fail its own `expected_grant_version`
        check."
        PRD §2.6: "the system stamps a generation counter, `ranking_version`,
        that starts at zero and increments on every successful ranking lock
        and every snapshot certification — two events that re-baseline the
        school figures."

        Design: Difficulty/transitive_cascade/snapshot_recertification_cascade
        """
        school = register_school("Setup School", "000702")
        grant = open_grant(2026, 5_000_000)
        snap1 = create_snapshot(grant["id"],
                                [snapshot_entry(school["id"], 50, 100)])
        certify_snapshot(snap1["id"], grant["id"])
        mid = get_grant(grant["id"])
        assert mid["ranking_version"] == 1, "one certification so far"
        snap2 = create_snapshot(grant["id"],
                                [snapshot_entry(school["id"], 55, 100)])
        certify_snapshot(snap2["id"], grant["id"])
        after = get_grant(grant["id"])
        assert after["ranking_version"] == 2
        assert after["version"] == mid["version"] + 1, \
            "certification advances the grant version by exactly one"
        rows = list_allocations_for(grant["id"])
        assert rows == [], "no allocations exist while the grant is in SETUP"
        snap1_after = validate_success(api_client.get_snapshot(snap1["id"],
                                                               DIRECTOR))
        assert snap1_after["status"] == "SUPERSEDED"


class TestCapAcceptanceBubbleUp:

    def test_cap_acceptance_bubble_up_cascade(self):
        """PRD §3.9: "Resolution bubbles upward through three depths. The
        moment a finding reaches `VERIFIED` — or an observation is closed with
        no action — the system checks its visit: when that was the visit's
        last finding outside the terminal set (`VERIFIED`, `CLOSED_NO_ACTION`),
        the visit auto-transitions from `REPORT_ISSUED` to `CLOSED`. One level
        deeper, the grant's `monitoring_clearance` is recomputed and the
        grant's `version` advances by one."
        PRD §3.9: "`FINDINGS_OPEN` when any finding of any visit of the grant
        sits in `OPEN`, `ESCALATED`, `CAP_SUBMITTED`, or `CAP_RETURNED`;
        `CLEARED` when the grant has at least one `CLOSED` visit and no such
        finding; and `NOT_MONITORED` otherwise."

        Design: Difficulty/transitive_cascade/cap_acceptance_bubble_up_cascade
        """
        grant = open_grant(2042, 5_000_000)
        visit = setup_visit_in_progress(grant["id"], scope="COMPREHENSIVE")
        f1 = record_finding(visit["id"],
                            description="ranking documentation incomplete",
                            cap_due_date="2026-09-01")
        f2 = record_finding(visit["id"], citation="2 CFR 200.403",
                            severity="SYSTEMIC",
                            description="allowability documentation missing "
                                        "for two cost items",
                            cap_due_date="2026-09-01")
        issue_report(visit["id"])
        submit_cap(f1["id"],
                   cap_narrative="District will publish the full ranking "
                                 "worksheet with school board sign-off and "
                                 "training records.")
        accept_cap(f1["id"])
        visit_mid = validate_success(api_client.get_visit(visit["id"],
                                                          MONITOR))
        assert visit_mid["status"] == "REPORT_ISSUED", \
            "F2 still OPEN — no premature closure"
        submit_cap(f2["id"],
                   cap_narrative="District will retrain business office staff "
                                 "on 2 CFR 200.403 and attach corrected "
                                 "ledgers.")
        f2_after = accept_cap(f2["id"])
        assert f2_after["status"] == "VERIFIED"
        visit_end = validate_success(api_client.get_visit(visit["id"],
                                                          MONITOR))
        assert visit_end["status"] == "CLOSED", \
            "the last terminal finding auto-closes the visit"
        grant_after = get_grant(grant["id"])
        assert grant_after["monitoring_clearance"] == "CLEARED"

    def test_finding_creation_opens_clearance_and_bumps_grant(self):
        """PRD §3.9: "A recorded finding starts in `OPEN` with
        `cap_attempt_count` at zero, and its creation immediately recomputes
        the grant's `monitoring_clearance` and advances the grant's `version`
        by one."
        PRD §3.9: "Issuing the report moves an `IN_PROGRESS` visit to
        `REPORT_ISSUED` and stamps `report_issued_at`. When the visit has no
        findings at all, it does not linger: it immediately auto-transitions
        to `CLOSED` and the grant's `monitoring_clearance` is recomputed —
        the empty-set closure."

        Design: Difficulty/transitive_cascade/cap_acceptance_bubble_up_cascade
        """
        grant = open_grant(2043, 5_000_000)
        assert grant["monitoring_clearance"] == "NOT_MONITORED"
        visit = setup_visit_in_progress(grant["id"])
        before = get_grant(grant["id"])
        finding = record_finding(visit["id"], cap_due_date="2026-09-01")
        assert finding["status"] == "OPEN"
        assert finding["cap_attempt_count"] == 0
        after = get_grant(grant["id"])
        assert after["monitoring_clearance"] == "FINDINGS_OPEN", \
            "an OPEN finding flips the clearance"
        assert after["version"] == before["version"] + 1, \
            "finding creation advances the grant version by one"
        # With findings present, issuing the report does NOT auto-close.
        issued = issue_report(visit["id"])
        assert issued["status"] == "REPORT_ISSUED"
        assert issued["report_issued_at"] is not None
