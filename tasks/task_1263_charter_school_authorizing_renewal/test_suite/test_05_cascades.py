"""Cross-entity cascades: renewal-denial closure, monitoring-accept standing +
auto-notice, and activation supersede (PRD §3.2, §3.3, §3.4, §3.6)."""
import pytest

from test_helpers import (
    validate_success, get_success_data, CLOCK, assert_same_instant,
    create_open_school, setup_renewal_ready_school, create_renewal_decision,
    create_open_lottery, add_lottery_entry, add_monitoring_report,
    create_draft_contract, add_standard_targets, set_clock,
    make_staff_headers, make_board_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


def _denial_cascade_context():
    """Open school with track record, an OPEN lottery with one entry, and a
    renewal decision DECIDED DENIED whose appeal window has lapsed."""
    ctx = setup_renewal_ready_school(school_name="TC Closure Academy",
                                     applicant_id="applicant_tc1")
    lottery = create_open_lottery(ctx["school"]["id"], academic_year=2028, capacity=30)
    entry = add_lottery_entry(lottery["id"], ctx["school"]["id"],
                              student_ref="stu_tc1", preference_codes=[])
    decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
    validate_success(api_client.decide_renewal(
        decision["id"], {"outcome": "DENIED"}, make_board_headers("board_1")), 200)
    set_clock(CLOCK["AFTER_APPEAL_WINDOW"])
    return ctx, lottery, entry, decision


class TestRenewalDenialClosureCascade:
    def test_finalize_denial_moves_school_closing_and_creates_closure_plan(self, api):
        """PRD §3.6: "For `DENIED`, the closure cascade fires: the school moves
        `OPEN` → `CLOSING`, a `ClosurePlan` with reason `NON_RENEWAL` is created
        in `INITIATED` status"
        PRD §3.6: "Finalization moves the decision `DECIDED` → `FINAL` and then
        forks."

        Design: Difficulty/transitive_cascade/renewal_denial_closure_cascade
        """
        ctx, _lottery, _entry, decision = _denial_cascade_context()
        finalized = validate_success(api.finalize_renewal(decision["id"], STAFF), 200)
        assert finalized["status"] == "FINAL"

        school = validate_success(api.get_school(ctx["school"]["id"], STAFF), 200)
        assert school["status"] == "CLOSING"

        plans = validate_success(
            api.list_closure_plans(ctx["school"]["id"], STAFF), 200)
        assert len(plans) == 1
        assert plans[0]["reason"] == "NON_RENEWAL"
        assert plans[0]["status"] == "INITIATED"

    def test_finalize_denial_cancels_open_lottery_and_voids_entries(self, api):
        """PRD §3.4: "when a school moves `OPEN` → `CLOSING`, every lottery
        still in `DRAFT`, `OPEN`, or `SEALED` is cancelled to `CANCELLED`, and
        every entry in those lotteries — whether `ENTERED`, `WAITLISTED`, or
        `OFFERED` — is moved to `VOIDED`."

        Design: Difficulty/transitive_cascade/renewal_denial_closure_cascade
        """
        ctx, lottery, entry, decision = _denial_cascade_context()
        validate_success(api.finalize_renewal(decision["id"], STAFF), 200)

        current_lottery = validate_success(api.get_lottery(lottery["id"], STAFF), 200)
        assert current_lottery["status"] == "CANCELLED"

        entries = validate_success(api.list_lottery_entries(lottery["id"], STAFF), 200)
        assert len(entries) == 1
        assert entries[0]["id"] == entry["id"]
        assert entries[0]["outcome"] == "VOIDED"


class TestMonitoringAcceptStandingNoticeCascade:
    def _cascade_context(self):
        ctx = create_open_school(school_name="TC Monitoring Academy",
                                 applicant_id="applicant_tc2")
        report = add_monitoring_report(ctx["school"]["id"], fiscal_year=2028,
                                       academic_score=40, financial_score=90,
                                       operational_score=90)
        accepted = validate_success(
            api_client.accept_monitoring_report(report["id"], make_staff_headers("staff_tc2")),
            200)
        return ctx, accepted

    def test_accept_applies_standing_band(self, api):
        """PRD §3.3: "The school's `academic_standing`, `financial_standing`,
        and `operational_standing` are then set from the three bands."
        PRD §3.3: "Accepting a report — `SUBMITTED` → `ACCEPTED`, with
        `ERR_REPORT_INVALID_STATE` for any other status — is where monitoring
        bites."

        Design: Difficulty/transitive_cascade/monitoring_accept_standing_notice_cascade
        """
        ctx, accepted = self._cascade_context()
        assert accepted["status"] == "ACCEPTED"
        school = validate_success(api.get_school(ctx["school"]["id"], STAFF), 200)
        assert school["academic_standing"] == "CRITICAL"      # 40 < 50
        assert school["financial_standing"] == "GOOD"
        assert school["operational_standing"] == "GOOD"

    def test_accept_auto_creates_issued_probation_notice(self, api):
        """PRD §3.3: "for every domain the acceptance left newly in `PROBATION`
        or `CRITICAL`, if no open notice (one in `DRAFT` or `ISSUED`) already
        exists for that school and domain, the system itself creates an
        `InterventionNotice` at level `PROBATION`, already in `ISSUED` status,
        with the accepting staff member recorded as `issued_by_user_id` and a
        `corrective_due_date` thirty days out from the logical clock."

        Design: Difficulty/transitive_cascade/monitoring_accept_standing_notice_cascade
        """
        ctx, _accepted = self._cascade_context()
        notices = validate_success(
            api.list_interventions(ctx["school"]["id"], STAFF), 200)
        assert len(notices) == 1
        notice = notices[0]
        assert notice["level"] == "PROBATION"
        assert notice["status"] == "ISSUED"
        assert notice["domain"] == "ACADEMIC"
        assert notice["issued_by_user_id"] == "staff_tc2"
        # Accept ran at the default clock 2026-05-01T00:00:00Z, +30 days.
        assert_same_instant(notice["corrective_due_date"], "2026-05-31T00:00:00Z")


class TestActivationSupersedesPriorContract:
    def test_successor_activation_supersedes_and_repoints_school(self, api):
        """PRD §3.2: "Activation then cascades: any other `ACTIVE` contract for
        the same school is superseded (`ACTIVE` → `SUPERSEDED`), the school's
        `current_contract_id` is pointed at the newly active contract, and a
        `PRE_OPENING` school opens its doors (`PRE_OPENING` → `OPEN`)."

        Design: Corner/cross_cutting_complexity_layers/cc_activation_supersedes_prior_contract
        """
        ctx = create_open_school(school_name="CC Supersede Academy",
                                 applicant_id="applicant_x3")
        school = ctx["school"]
        c1 = ctx["contract"]
        assert c1["status"] == "ACTIVE"

        school_now = validate_success(api.get_school(school["id"], STAFF), 200)
        c2 = create_draft_contract(school["id"], school_now["version"],
                                   framework_version="FW-2",
                                   term_start="2032-07-01T00:00:00Z",
                                   term_end="2037-06-30T00:00:00Z",
                                   prior_contract_id=c1["id"])
        add_standard_targets(c2["id"])
        activated = validate_success(api.activate_contract(c2["id"], STAFF), 200)
        assert activated["status"] == "ACTIVE"

        prior = validate_success(api.get_contract(c1["id"], STAFF), 200)
        assert prior["status"] == "SUPERSEDED"

        school_after = validate_success(api.get_school(school["id"], STAFF), 200)
        assert school_after["current_contract_id"] == c2["id"]
