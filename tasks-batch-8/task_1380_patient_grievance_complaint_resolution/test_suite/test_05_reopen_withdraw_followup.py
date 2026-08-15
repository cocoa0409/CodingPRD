"""Reopen cycles (manual and score-triggered), the parallel regulatory clock
dimension, withdrawal cascades, and satisfaction follow-up rules."""
from test_helpers import (
    ApiErrorId,
    create_case,
    create_clock_suspension_payload,
    create_staff,
    create_unit,
    get_case,
    get_success_data,
    make_advocate_headers,
    make_director_headers,
    make_investigator_headers,
    set_clock,
    setup_closed_case,
    setup_open_investigation,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def _closed_grievance(api, patient_ref, **overrides):
    """STANDARD grievance closed via letter issued 2026-08-10T09:00:00Z.

    The grievance is acknowledged at intake (PRD §3.2) so the parallel clock
    dimension is readable as ON_TRACK after reopen.
    """
    kwargs = dict(unit_name="ED Main", unit_category="EMERGENCY",
                  clock="2026-08-03T10:00:00.000Z", received_at="2026-08-03T09:00:00.000Z",
                  channel="PHONE", description="ED wait time concern",
                  grievance_category="ACCESS_DELAY", acknowledge=True,
                  issue_at="2026-08-10T09:00:00.000Z")
    kwargs.update(overrides)
    return setup_closed_case(patient_ref=patient_ref, **kwargs)


class TestManualReopenCycle:
    def test_reopen_unwinds_closure_and_supersedes_children(self, api):
        """PRD §3.9: "First, the case moves `CLOSED` → `REOPENED`:
        `reopen_count` rises by one, `closed_at` is cleared,
        `resolution_timeliness` returns to `NA`, and the unit's
        `open_case_count` rises by one. Second, the case's `FINDINGS_ACCEPTED`
        investigation moves to `REOPENED` and its `ISSUED` letter moves to
        `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/patient_case_reopen_cycle_with_parallel_clock
        """
        base = _closed_grievance(api, "P-5001")
        assert base.case["lifecycle_status"] == "CLOSED"
        set_clock("2026-08-20T12:00:00.000Z")
        reopened = validate_success(api.reopen_case(
            base.case["id"], {"reopen_reason": "Patient rejected resolution"},
            make_director_headers(base.director["id"])))
        assert reopened["lifecycle_status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        assert reopened["resolution_timeliness"] == "NA"
        assert reopened["closed_at"] is None

        investigation = get_success_data(api.get_investigation(
            base.investigation["id"], make_director_headers(base.director["id"])))
        assert investigation["status"] == "REOPENED"
        letter = get_success_data(api.get_letter(
            base.letter["id"], make_director_headers(base.director["id"])))
        assert letter["status"] == "SUPERSEDED"
        unit = get_success_data(api.get_unit(
            base.unit["id"], make_director_headers(base.director["id"])))
        assert unit["open_case_count"] == 1, "unit counter restored by the reopen"

    def test_reopen_reanchors_dues_and_clock_reads_on_track(self, api):
        """PRD §3.9: "Third, the regulatory dues are re-anchored:
        `response_due_calendar_at` becomes fifteen calendar days after the
        reopen instant and `response_due_business_at` fifteen business days
        after it, with `requires_qro_cosign` recomputed." PRD §3.3: "Resuming
        work is again the investigator's act: resume requires the investigation
        in `REOPENED` and the case in `REOPENED` (the respective violations are
        `ERR_INVESTIGATION_INVALID_STATE` and `ERR_CASE_INVALID_STATE`), and it
        returns the investigation to `OPEN` while the case bubbles `REOPENED`
        → `UNDER_INVESTIGATION`."

        Design: Difficulty/non_linear_state_machine/patient_case_reopen_cycle_with_parallel_clock
        """
        base = _closed_grievance(api, "P-5001")
        set_clock("2026-08-20T12:00:00.000Z")
        validate_success(api.reopen_case(
            base.case["id"], {"reopen_reason": "Patient rejected resolution"},
            make_director_headers(base.director["id"])))

        timeline = get_success_data(api.get_case_timeline(
            base.case["id"], make_director_headers(base.director["id"])))
        assert timeline["response_due_calendar_at"] == "2026-09-04T12:00:00.000Z", (
            "reopen at 2026-08-20T12:00:00Z + 15 calendar days")
        assert timeline["response_due_business_at"] == "2026-09-10T12:00:00.000Z", (
            "15 business days: Aug 21,24-28,31, Sep 1-4,7-10")
        assert timeline["regulatory_clock_status"] == "ON_TRACK", (
            "the parallel clock dimension re-derives independently of the "
            "lifecycle: acknowledged grievance with re-anchored dues ahead")

        resumed = validate_success(api.resume_investigation(
            base.investigation["id"], make_investigator_headers(base.inv["id"])))
        assert resumed["status"] == "OPEN"
        assert get_case(base.case["id"])["lifecycle_status"] == "UNDER_INVESTIGATION"


class TestSatisfactionScoreReopenCascade:
    def test_followup_schedule_and_respond(self, api):
        """PRD §3.9: "Every closure — by issued letter or by complaint
        fast-track — spawns a **satisfaction follow-up** in `PENDING`, with
        `due_at` set five business days after `closed_at` and `expires_at` ten
        business days after `due_at`, both on the business-day arithmetic of
        §2.8 at the same time of day as their base." and "A recorded response
        stamps `responded_at` and moves the follow-up to `RESPONDED`."

        Design: Difficulty/transitive_cascade/poor_satisfaction_score_reopen_cascade
        """
        base = _closed_grievance(api, "P-6001")
        follow_up = base.follow_up
        assert follow_up["status"] == "PENDING"
        assert follow_up["due_at"] == "2026-08-17T09:00:00.000Z", (
            "closed 2026-08-10T09:00:00Z (Monday) + 5 business days")
        assert follow_up["expires_at"] == "2026-08-31T09:00:00.000Z", (
            "due_at + 10 business days")

        advocate = create_staff("Ally Advocate", ["ADVOCATE"])
        set_clock("2026-08-12T09:00:00.000Z")
        responded = validate_success(api.respond_follow_up(
            follow_up["id"], {"score": 1}, make_advocate_headers(advocate["id"])))
        assert responded["status"] == "RESPONDED"

    def test_low_score_fires_full_reopen_cascade(self, api):
        """PRD §3.9: "A score of two or lower is treated as a failed resolution
        and fires the full reopen cascade on the case." and "First, the case
        moves `CLOSED` → `REOPENED`: `reopen_count` rises by one, `closed_at`
        is cleared, `resolution_timeliness` returns to `NA`, and the unit's
        `open_case_count` rises by one. Second, the case's `FINDINGS_ACCEPTED`
        investigation moves to `REOPENED` and its `ISSUED` letter moves to
        `SUPERSEDED`. Third, the regulatory dues are re-anchored:
        `response_due_calendar_at` becomes fifteen calendar days after the
        reopen instant and `response_due_business_at` fifteen business days
        after it, with `requires_qro_cosign` recomputed."

        Design: Difficulty/transitive_cascade/poor_satisfaction_score_reopen_cascade
        """
        base = _closed_grievance(api, "P-6001")
        advocate = create_staff("Ally Advocate", ["ADVOCATE"])
        set_clock("2026-08-12T09:00:00.000Z")
        validate_success(api.respond_follow_up(
            base.follow_up["id"], {"score": 1},
            make_advocate_headers(advocate["id"])))

        case = get_case(base.case["id"])
        assert case["lifecycle_status"] == "REOPENED"
        assert case["reopen_count"] == 1
        investigation = get_success_data(api.get_investigation(
            base.investigation["id"], make_advocate_headers(advocate["id"])))
        assert investigation["status"] == "REOPENED"
        letter = get_success_data(api.get_letter(
            base.letter["id"], make_advocate_headers(advocate["id"])))
        assert letter["status"] == "SUPERSEDED"
        timeline = get_success_data(api.get_case_timeline(
            base.case["id"], make_advocate_headers(advocate["id"])))
        assert timeline["response_due_calendar_at"] == "2026-08-27T09:00:00.000Z", (
            "reopen fired at 2026-08-12T09:00:00Z + 15 calendar days")
        unit = get_success_data(api.get_unit(
            base.unit["id"], make_advocate_headers(advocate["id"])))
        assert unit["open_case_count"] == 1

    def test_followup_respond_after_expiry_rejected(self, api):
        """PRD §3.9: "Responding requires the follow-up still `PENDING` and the
        clock not past `expires_at` — a late response is rejected with
        `ERR_FOLLOWUP_INVALID_STATE`, and a follow-up still pending past its
        expiry reads `EXPIRED`."

        Design: Corner/state_machines/followup_respond_after_expiry_rejected
        """
        base = _closed_grievance(api, "P-0105")
        advocate = create_staff("Ally Advocate", ["ADVOCATE"])
        # expires_at is 2026-08-31T09:00:00Z for a 2026-08-10T09:00:00Z closure.
        set_clock("2026-09-01T00:00:00.000Z")
        resp = api.respond_follow_up(base.follow_up["id"], {"score": 4},
                                     make_advocate_headers(advocate["id"]))
        validate_error(resp, ApiErrorId.ERR_FOLLOWUP_INVALID_STATE)
        fetched = get_success_data(api.get_follow_up(
            base.follow_up["id"], make_advocate_headers(advocate["id"])))
        assert fetched["status"] == "EXPIRED"


class TestWithdrawal:
    def test_withdraw_from_terminal_withdrawn_rejected(self, api):
        """PRD §3.9: "and from anywhere else, including the terminal
        `WITHDRAWN` itself, the request meets `ERR_CASE_INVALID_STATE`." and
        "The case `version` advances by one, and `WITHDRAWN` is terminal —
        nothing leaves it."

        Design: Corner/state_machines/withdraw_from_terminal_withdrawn_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED Main", "EMERGENCY")
        case = create_case(unit["id"], patient_ref="P-0101",
                           received_at="2026-08-03T09:00:00.000Z",
                           description="Concern withdrawn", grievance_category="OTHER")
        validate_success(api.withdraw_case(
            case["id"], {"withdraw_reason": "Patient request"}, INTAKE))

        resp = api.withdraw_case(case["id"], {"withdraw_reason": "Duplicate attempt"},
                                 INTAKE)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
        unit_after = get_success_data(api.get_unit(unit["id"], INTAKE))
        assert unit_after["open_case_count"] == 0, (
            "the unit counter is decremented exactly once — the cascade did "
            "not re-fire")

    def test_withdraw_cascade_releases_children_and_freezes_tolling(self, api):
        """PRD §3.9: "The withdraw cascade releases every `ACTIVE` assignment
        to `RELEASED` with each investigator's count falling by one, cancels an
        investigation standing in `OPEN`, `FINDINGS_SUBMITTED`, or `REOPENED`
        to `CANCELLED`, cancels letters standing in `DRAFT`, `IN_REVIEW`, or
        `RETURNED` while conspicuously leaving an `APPROVED` letter approved,
        closes every `OPEN` suspension at the withdrawal instant, rejects every
        `PENDING_APPROVAL` recovery action, and lowers the unit's
        `open_case_count` by one." PRD §3.5: "Closure stamps `closed_at` and
        fixes `credited_seconds` as the number of seconds between start and
        close."

        Design: Corner/state_machines/withdraw_cascade_releases_children_and_freezes_tolling
        """
        base = setup_open_investigation(
            unit_name="Neuro", unit_category="INPATIENT", patient_ref="P-0107",
            description="Concern", grievance_category="COMMUNICATION")
        set_clock("2026-08-05T09:00:00.000Z")
        suspension = get_success_data(api.create_clock_suspension(
            base.case["id"], create_clock_suspension_payload(reason="AWAITING_PATIENT"),
            INTAKE))
        set_clock("2026-08-08T09:00:00.000Z")

        withdrawn = validate_success(api.withdraw_case(
            base.case["id"], {"withdraw_reason": "Patient moved away"}, INTAKE))
        assert withdrawn["lifecycle_status"] == "WITHDRAWN"

        assignment = get_success_data(api.get_assignment(base.assignment["id"], INTAKE))
        assert assignment["status"] == "RELEASED"
        investigation = get_success_data(api.get_investigation(
            base.investigation["id"], INTAKE))
        assert investigation["status"] == "CANCELLED"
        suspension_after = get_success_data(api.get_clock_suspension(
            suspension["id"], INTAKE))
        assert suspension_after["status"] == "CLOSED"
        assert suspension_after["credited_seconds"] == 259200, (
            "three days frozen at the withdrawal instant, not growing")
