"""Adverse action cases: hearing lifecycle, remand cycle, waiver by silence,
quorum, SoD exclusion, and NPDB reporting obligations."""
from datetime import timedelta

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_days,
    create_approved_member,
    create_member_record,
    create_npdb_report_payload,
    create_proposed_case,
    format_ts,
    get_success_data,
    make_department_chief_headers,
    make_practitioner_headers,
    parse_ts,
    refresh_case,
    refresh_grant,
    refresh_member,
    request_hearing_for_case,
    seat_panelists,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]
MEC = TEST_USERS["mec_chair_headers"]
HEARING = TEST_USERS["hearing_officer_headers"]


def _subject_with_case(case_kind="SUSPENSION", restriction_days=None,
                       name="Dr. Subject", npdb="NPDB-SUBJ"):
    """ACTIVE member + proposed case from a fresh chief record."""
    ws = create_approved_member(name, npdb)
    chief = create_member_record("Dr. Chief", f"{npdb}-CHIEF", "EMED")
    case = create_proposed_case(ws["member"]["id"], chief["id"], case_kind,
                                restriction_days)
    return ws, case, chief


class TestRemandCycle:
    def test_remand_cycle_loops_back_to_hearing(self, api):
        """PRD §3.8: "`REMANDED` extends the hearing-request deadline to the
        remand instant plus the hearing-request window, and the loop
        `HEARING_HELD` → `REMANDED` → `HEARING_REQUESTED` → `HEARING_HELD` is
        permitted — the subject may re-request the hearing under the same
        guards".

        Design: Difficulty/non_linear_state_machine/adverse_case_remand_cycle_loops
        """
        ws, case, _chief = _subject_with_case()
        case_id = case["id"]
        get_success_data(api.endorse_adverse_action_case(case_id, MEC))
        request_hearing_for_case(case_id, ws["member"]["id"])
        seat_panelists(case_id, 3)
        get_success_data(api.hold_hearing(case_id, HEARING))
        assert refresh_case(case_id)["case_status"] == "HEARING_HELD"

        remanded = validate_success(
            api.decide_adverse_action_case(case_id, "REMAND", HEARING))
        assert remanded["case_status"] == "REMANDED"

        re_requested = request_hearing_for_case(case_id, ws["member"]["id"])
        assert re_requested["case_status"] == "HEARING_REQUESTED", (
            "The loop re-enters HEARING_REQUESTED after a remand")

        get_success_data(api.hold_hearing(case_id, HEARING))
        assert refresh_case(case_id)["case_status"] == "HEARING_HELD"

        decided = validate_success(
            api.decide_adverse_action_case(case_id, "OVERTURNED", HEARING))
        assert decided["case_status"] == "FINAL_NO_ACTION"

    def test_overturned_leaves_member_untouched_no_npdb(self, api):
        """PRD §3.8: "`FINAL_NO_ACTION`, by contrast, produces no NPDB report
        and leaves the member untouched."

        Design: Difficulty/non_linear_state_machine/adverse_case_remand_cycle_loops
        """
        ws, case, _chief = _subject_with_case()
        case_id = case["id"]
        get_success_data(api.endorse_adverse_action_case(case_id, MEC))
        request_hearing_for_case(case_id, ws["member"]["id"])
        seat_panelists(case_id, 3)
        get_success_data(api.hold_hearing(case_id, HEARING))

        decided = validate_success(
            api.decide_adverse_action_case(case_id, "OVERTURNED", HEARING))
        assert decided["case_status"] == "FINAL_NO_ACTION"

        member = refresh_member(ws["member"]["id"])
        assert member["membership_status"] == "ACTIVE", (
            "An overturned case leaves the member's standing unchanged")

        reports, meta = validate_paginated(api.list_npdb_reports(COORD))
        assert meta["total_count"] == 0, (
            "No NPDB report may be spawned by a FINAL_NO_ACTION outcome")


class TestFinalAdverseCascade:
    def _upheld_revocation(self, api):
        ws, case, _chief = _subject_with_case("REVOCATION",
                                              name="Dr. Rev", npdb="NPDB-R1")
        case_id = case["id"]
        get_success_data(api.endorse_adverse_action_case(case_id, MEC))
        request_hearing_for_case(case_id, ws["member"]["id"])
        seat_panelists(case_id, 3)
        get_success_data(api.hold_hearing(case_id, HEARING))
        decided = validate_success(
            api.decide_adverse_action_case(case_id, "UPHELD", HEARING))
        return ws, case_id, decided

    def test_upheld_revocation_terminates_member_and_grants(self, api):
        """PRD §3.8: "it moves the member's `membership_status` to `SUSPENDED`
        for a `SUSPENSION` case or to `TERMINATED` for `REVOCATION` or
        `DENIAL_OF_REAPPOINTMENT`; for `REVOCATION` it additionally revokes every
        `ACTIVE` and `PROVISIONAL` grant of the member — each such revocation
        spawns its own `REPORT_ADVERSE_ACTION` filing with a thirty-day deadline
        — and drives `privilege_posture` to `NONE`".

        Design: Difficulty/transitive_cascade/adverse_final_two_hop_npdb_and_termination
        """
        ws, case_id, decided = self._upheld_revocation(api)
        assert decided["case_status"] == "FINAL_ADVERSE", (
            "hop 1: an UPHELD decision lands the case in FINAL_ADVERSE")

        member = refresh_member(ws["member"]["id"])
        assert member["membership_status"] == "TERMINATED", (
            "hop 2: REVOCATION terminates the member")
        assert member["privilege_posture"] == "NONE"
        assert refresh_grant(ws["grant"]["id"])["grant_status"] == "REVOKED"

    def test_upheld_revocation_spawns_npdb_report_with_30d_deadline(self, api):
        """PRD §3.8: "`FINAL_ADVERSE` spawns an NPDB report of `report_kind`
        `REPORT_ADVERSE_ACTION` when the case is `npdb_reportable`, with
        `submission_deadline` set thirty days from the final-adverse instant".
        PRD §3.8: "a case whose kind is `SUSPENSION`, `REVOCATION`, or
        `DENIAL_OF_REAPPOINTMENT` becomes reportable upon reaching
        `FINAL_ADVERSE`".

        The decision is rendered at the 2026-08-01 clock, so the deadline is
        2026-08-31 and the report is on time.

        Design: Difficulty/transitive_cascade/adverse_final_two_hop_npdb_and_termination
        """
        ws, case_id, decided = self._upheld_revocation(api)
        reports, _meta = validate_paginated(
            api.list_npdb_reports(COORD, params={"case_id": case_id}))
        adverse = [r for r in reports
                   if r["report_kind"] == "REPORT_ADVERSE_ACTION"]
        assert len(adverse) >= 1, (
            "FINAL_ADVERSE of a reportable case spawns a REPORT_ADVERSE_ACTION")
        report = adverse[0]
        assert parse_ts(report["submission_deadline"]) == parse_ts(
            "2026-08-31T00:00:00Z"), (
            "Deadline is thirty days from the 2026-08-01 final-adverse instant")
        assert report["is_late"] is False


class TestWaiverBySilence:
    def test_hearing_waiver_by_silence_auto_final_adverse(self, api):
        """PRD §3.8: "Silence is a waiver: if the clock passes
        `hearing_request_deadline` with no hearing requested, a case in
        `MEC_ENDORSED` moves automatically to `FINAL_ADVERSE`, carrying the same
        finalization side effects as an upheld hearing."
        PRD §3.8: "it moves the member's `membership_status` to `SUSPENDED` for
        a `SUSPENSION` case".

        Design: Corner/state_machines/hearing_waiver_by_silence_auto_final_adverse
        """
        ws, case, _chief = _subject_with_case("SUSPENSION",
                                              name="Dr. Silence",
                                              npdb="NPDB-SIL")
        case_id = case["id"]
        get_success_data(api.endorse_adverse_action_case(case_id, MEC))
        endorsed = refresh_case(case_id)
        assert endorsed["case_status"] == "MEC_ENDORSED"

        # The PRD gives the window's length only as "a fixed number of days
        # configured for the installation", so read the scheduled deadline back
        # and advance the clock strictly past it.
        deadline = parse_ts(endorsed["hearing_request_deadline"])
        past = deadline + timedelta(seconds=1)
        set_clock(format_ts(past))

        final = refresh_case(case_id)
        assert final["case_status"] == "FINAL_ADVERSE", (
            "No hearing requested by the deadline: the case auto-finalizes")
        assert refresh_member(
            ws["member"]["id"])["membership_status"] == "SUSPENDED"

        reports, _meta = validate_paginated(
            api.list_npdb_reports(COORD, params={"case_id": case_id}))
        adverse = [r for r in reports
                   if r["report_kind"] == "REPORT_ADVERSE_ACTION"]
        assert len(adverse) == 1
        assert parse_ts(adverse[0]["submission_deadline"]) == add_days(past, 30), (
            "The spawned report's deadline is thirty days from the "
            "final-adverse instant")


class TestNpdbDeadlineBoundary:
    def test_npdb_report_submitted_exactly_at_deadline_is_not_late(self, api):
        """PRD §3.8: "Timeliness is strict at the boundary: `is_late` is true
        when `submitted_at` is strictly later than `submission_deadline`, while
        a filing exactly at its deadline is on time — and a report created late
        lands directly in `LATE` with `is_late` set, rather than passing through
        `SUBMITTED` cleanly."
        PRD §3.8: "a `REPORT_CORRECTION` or `REPORT_VOID` inherits the deadline
        of the report it corrects or voids".
        PRD §3.8: "a `RESTRICTION` case is reportable only when its
        `restriction_days` exceeds thirty days."

        Design: Corner/state_machines/npdb_report_submitted_exactly_at_deadline_is_not_late
        """
        ws, case, _chief = _subject_with_case("RESTRICTION", restriction_days=31,
                                              name="Dr. NotLate",
                                              npdb="NPDB-NL")
        case_id = case["id"]
        get_success_data(api.endorse_adverse_action_case(case_id, MEC))
        request_hearing_for_case(case_id, ws["member"]["id"])
        seat_panelists(case_id, 3)
        get_success_data(api.hold_hearing(case_id, HEARING))
        validate_success(api.decide_adverse_action_case(case_id, "UPHELD",
                                                        HEARING))

        reports, _meta = validate_paginated(
            api.list_npdb_reports(COORD, params={"case_id": case_id}))
        auto = [r for r in reports if r["report_kind"] == "REPORT_ADVERSE_ACTION"]
        assert len(auto) == 1
        assert auto[0]["is_late"] is False, (
            "The report spawned at the decision instant is on time")

        # File a correction at exactly the inherited deadline (decision at
        # 2026-08-01 + thirty days).
        set_clock("2026-08-31T00:00:00Z")
        correction = validate_success(
            api.create_npdb_report(
                create_npdb_report_payload(ws["member"]["id"],
                                           "REPORT_CORRECTION", case_id),
                COORD), 201)
        assert correction["report_status"] == "SUBMITTED"
        assert correction["is_late"] is False, (
            "submitted_at exactly equal to the deadline is on time")


class TestHearingQuorum:
    def test_hearing_quorum_recusal_shrinks_eligible_pool(self, api):
        """PRD §3.8: "`quorum_required` is the larger of three and the result of
        halving that total, rounded up to a whole number. The eligible panel is
        the set of rows still `SEATED` whose panelist is not excluded for the
        case, and quorum is met when the eligible count reaches
        `quorum_required`. Convening the hearing — the `HearingOfficer`'s act —
        requires the case in `HEARING_REQUESTED` (`ERR_CASE_NOT_IN_HEARING`) and
        a satisfied quorum (`ERR_HEARING_QUORUM_UNMET`), moving the case to
        `HEARING_HELD`."

        Three panelists seated (quorum_required 3); after one recusal only two
        eligible panelists remain and the hearing cannot convene.

        Design: Corner/calculations/hearing_quorum_recusal_shrinks_eligible_pool
        """
        ws, case, _chief = _subject_with_case("SUSPENSION", name="Dr. HQ",
                                              npdb="NPDB-HQ1")
        case_id = case["id"]
        get_success_data(api.endorse_adverse_action_case(case_id, MEC))
        request_hearing_for_case(case_id, ws["member"]["id"])
        panels = seat_panelists(case_id, 3)

        get_success_data(api.recuse_hearing_panel(panels[0]["id"], HEARING))

        rows, _meta = validate_paginated(
            api.list_hearing_panels(COORD, params={"case_id": case_id}))
        assert len(rows) == 3, (
            "The seated-history denominator keeps the RECUSED row")
        seated = [r for r in rows if r["panel_status"] == "SEATED"]
        assert len(seated) == 2

        resp = api.hold_hearing(case_id, HEARING)
        validate_error(resp, ApiErrorId.ERR_HEARING_QUORUM_UNMET, 409)
        assert refresh_case(case_id)["case_status"] == "HEARING_REQUESTED"


class TestNpdbFilingRules:
    def test_error_npdb_case_required_for_report_kinds(self, api):
        """PRD §3.8: "for every `REPORT_*` kind, the source `case_id`
        (`ERR_NPDB_CASE_REQUIRED`, 400); query kinds carry no case reference."

        Design: Corner/errors/error_npdb_case_required_for_report_kinds
        """
        member = create_member_record("Dr. NoCase", "NPDB-NC", "CARD")
        resp = api.create_npdb_report(
            {"member_id": member["id"], "report_kind": "REPORT_ADVERSE_ACTION"},
            COORD)
        validate_error(resp, ApiErrorId.ERR_NPDB_CASE_REQUIRED, 400)


class TestCaseOwnershipRules:
    def test_rbac_case_withdraw_only_by_proposer(self, api):
        """PRD §2.10: "A case may be withdrawn only by the department chief
        whose member record matches the case's `proposed_by_member_id`
        (`ERR_NOT_CASE_PROPOSER`, 403)".

        Design: Corner/roles/rbac_case_withdraw_only_by_proposer
        """
        subject = create_member_record("Dr. SubjW", "NPDB-SW", "EMED")
        chief1 = create_member_record("Dr. Chief1", "NPDB-C1", "EMED")
        chief2 = create_member_record("Dr. Chief2", "NPDB-C2", "EMED")
        case = create_proposed_case(subject["id"], chief1["id"], "SUSPENSION")

        resp = api.withdraw_adverse_action_case(
            case["id"], make_department_chief_headers(chief2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_CASE_PROPOSER, 403)

        withdrawn = validate_success(api.withdraw_adverse_action_case(
            case["id"], make_department_chief_headers(chief1["id"])))
        assert withdrawn["case_status"] == "WITHDRAWN"

    def test_rbac_hearing_request_only_by_subject(self, api):
        """PRD §3.8: "The subject — and only the subject, a `Practitioner` whose
        identity matches `subject_member_id` (`ERR_NOT_CASE_SUBJECT`, 403) — may
        request a hearing while the case is in `MEC_ENDORSED`".

        Design: Corner/roles/rbac_hearing_request_only_by_subject
        """
        ws = create_approved_member("Dr. SubjH", "NPDB-SH")
        chief = create_member_record("Dr. ChiefH", "NPDB-CH", "EMED")
        other = create_member_record("Dr. Other", "NPDB-OTH", "EMED")
        case = create_proposed_case(ws["member"]["id"], chief["id"],
                                    "SUSPENSION")
        get_success_data(api.endorse_adverse_action_case(case["id"], MEC))

        resp = api.request_hearing(
            case["id"], make_practitioner_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_CASE_SUBJECT, 403)
        assert refresh_case(case["id"])["case_status"] == "MEC_ENDORSED"

    def test_rbac_seating_sod_excluded_panelist_rejected(self, api):
        """PRD §2.10: "When a practitioner requests a fair hearing on an adverse
        action case, the case's `id` is appended to the `sod_exclusion_tags` of
        both the subject and the proposer. Any member whose `sod_exclusion_tags`
        contain a case's `id` is barred from being seated on that case's hearing
        panel — the seating attempt is rejected with
        `ERR_PANELIST_SOD_EXCLUDED` (403)".

        Design: Corner/roles/rbac_seating_sod_excluded_panelist_rejected
        """
        ws = create_approved_member("Dr. SubjP", "NPDB-SP")
        chief = create_member_record("Dr. ChiefP", "NPDB-CP", "EMED")
        case = create_proposed_case(ws["member"]["id"], chief["id"],
                                    "SUSPENSION")
        get_success_data(api.endorse_adverse_action_case(case["id"], MEC))
        request_hearing_for_case(case["id"], ws["member"]["id"])

        resp_proposer = api.create_hearing_panel(
            {"case_id": case["id"], "panel_member_id": chief["id"],
             "panel_role": "MEMBER"}, HEARING)
        validate_error(resp_proposer, ApiErrorId.ERR_PANELIST_SOD_EXCLUDED, 403)

        resp_subject = api.create_hearing_panel(
            {"case_id": case["id"], "panel_member_id": ws["member"]["id"],
             "panel_role": "MEMBER"}, HEARING)
        validate_error(resp_subject, ApiErrorId.ERR_PANELIST_SOD_EXCLUDED, 403)
