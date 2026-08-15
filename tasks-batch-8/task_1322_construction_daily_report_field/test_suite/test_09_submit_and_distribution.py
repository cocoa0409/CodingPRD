"""Submit gates, segregation of duties, distribution lifecycle, retention."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_crew_entry,
    add_distribution_record,
    add_incident,
    add_weather_observation,
    api_client,
    assert_instant_equal,
    create_daily_report_payload,
    get_distribution_record,
    get_report,
    make_active_project,
    make_approved_report,
    make_project_manager_headers,
    make_report,
    make_submitted_report,
    make_under_review_report,
    make_work_area,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_SUPT = TEST_USERS["superintendent_headers"]
_OWNER = TEST_USERS["owner_rep_headers"]


class TestSubmitGates:
    def test_duplicate_report_date_rejected_per_project(self, api):
        """PRD section 3.2: "One report exists per project per date: a second
        report for the same project and `report_date` is rejected with
        `ERR_DUPLICATE_REPORT_DATE`."

        Design: Corner/validations/duplicate_report_date_rejected
        """
        p1 = make_active_project()
        p2 = make_active_project()
        make_report(p1["id"], report_date="2026-08-05")

        dup = api_client.create_daily_report(
            create_daily_report_payload(p1["id"], report_date="2026-08-05"), _SUPT)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_REPORT_DATE)
        assert dup.status_code == 409

        other_project = validate_success(api_client.create_daily_report(
            create_daily_report_payload(p2["id"], report_date="2026-08-05"),
            _SUPT), 201)
        assert other_project["id"], "uniqueness is per (project, report_date)"

    def test_no_work_xor_gate_at_submit(self, api):
        """PRD section 3.9: "exactly one of the two labor signals must hold —
        either at least one `ACTIVE` crew entry, or `no_work_performed` set
        true — so a report with no active crew and the flag still false fails
        with `ERR_NO_WORK_RECORDED`, while a report asserting
        `no_work_performed` that still carries `ACTIVE` crew entries fails with
        `ERR_WORK_ENTRIES_CONFLICT`".

        Design: Corner/validations/no_work_recorded_xor_flag
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        r1 = make_report(project["id"], report_date="2026-08-05")
        r2 = make_report(project["id"], report_date="2026-08-06",
                         no_work_performed=True)
        add_weather_observation(r1["id"], observed_at="2026-08-05T08:00:00Z")
        add_weather_observation(r2["id"], observed_at="2026-08-06T08:00:00Z",
                                condition="RAIN", work_impact="STOPPAGE")
        add_crew_entry(r2["id"], area["id"], worker_count=1)
        set_clock("2026-08-06T17:00:00Z")

        err1 = api_client.submit_report(r1["id"], _SUPT)
        validate_error(err1, ApiErrorId.ERR_NO_WORK_RECORDED)
        assert err1.status_code == 409

        err2 = api_client.submit_report(r2["id"], _SUPT)
        validate_error(err2, ApiErrorId.ERR_WORK_ENTRIES_CONFLICT)
        assert err2.status_code == 409

    def test_future_report_date_gate_follows_logical_clock(self, api):
        """PRD section 3.9: "the `report_date` must not lie after the logical
        clock's current date (else `ERR_REPORT_DATE_FUTURE`)".

        Design: Corner/validations/report_date_future_rejected_at_submit
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"], report_date="2026-08-10")
        add_weather_observation(report["id"], observed_at="2026-08-10T08:00:00Z")
        add_crew_entry(report["id"], area["id"], worker_count=1)

        # Clock still at its startup default of 2026-08-01T00:00:00Z.
        err = api_client.submit_report(report["id"], _SUPT)
        validate_error(err, ApiErrorId.ERR_REPORT_DATE_FUTURE)
        assert err.status_code == 422

        set_clock("2026-08-10T17:00:00Z")
        submitted = validate_success(api_client.submit_report(report["id"], _SUPT))
        assert submitted["status"] == "SUBMITTED"

    def test_closed_work_area_rejects_entries_until_reopened(self, api):
        """PRD section 3.1: "A `CLOSED` area refuses new child entries of every
        kind — crew, equipment, delay, safety, media, quantity, and incident
        records alike — with `ERR_WORK_AREA_CLOSED`."

        Design: Corner/validations/work_area_closed_rejects_new_entries
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        validate_success(api_client.close_work_area(area["id"], _ADMIN))
        report = make_report(project["id"])

        err = api_client.create_crew_entry(
            {"report_id": report["id"], "work_area_id": area["id"],
             "subcontractor": "S", "trade": "T", "worker_count": 1,
             "hours_per_worker": 8, "work_performed": "w"},
            _SUPT)
        validate_error(err, ApiErrorId.ERR_WORK_AREA_CLOSED)
        assert err.status_code == 409

        validate_success(api_client.reopen_work_area(area["id"], _ADMIN))
        ok = add_crew_entry(report["id"], area["id"], worker_count=1)
        assert ok["status"] == "ACTIVE"


class TestApproveSegregation:
    def test_submitter_cannot_approve_own_report(self, api):
        """PRD section 3.9: "Approval moves `UNDER_REVIEW` to `APPROVED`, but
        never by the report's own submitter — an approver whose `X-User-ID`
        equals `submitted_by_user_id` is refused with
        `ERR_SEGREGATION_OF_DUTIES`".

        Design: Corner/validations/segregation_approve_by_submitter_forbidden
        """
        ctx = make_under_review_report()  # submitted by supt-1
        rid = ctx["report"]["id"]
        assert ctx["report"]["submitted_by_user_id"] == "supt-1"

        same_person = api_client.approve_report(
            rid, make_project_manager_headers("supt-1"))
        validate_error(same_person, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert same_person.status_code == 403

        other_pm = validate_success(api_client.approve_report(
            rid, make_project_manager_headers("pm-2")))
        assert other_pm["status"] == "APPROVED"


class TestDistributionGates:
    def test_create_blocked_before_approval_then_allowed(self, api):
        """PRD section 3.9: "A `ProjectManager` adds recipients to a report that
        has reached `APPROVED` or `LOCKED` — any earlier state fails with
        `ERR_REPORT_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/distribution_create_blocked_by_report_state
        """
        ctx = make_under_review_report()
        rid = ctx["report"]["id"]

        err = api_client.create_distribution_record(
            {"report_id": rid, "recipient_email": "arch@x.com",
             "recipient_role": "ARCHITECT"}, _PM)
        validate_error(err, ApiErrorId.ERR_REPORT_NOT_APPROVED)
        assert err.status_code == 409

        validate_success(api_client.approve_report(rid, _PM))
        record = add_distribution_record(rid, recipient_email="arch@x.com",
                                         recipient_role="ARCHITECT")
        assert record["status"] == "PENDING"

    def test_create_blocked_on_submitted_allowed_on_locked(self, api):
        """PRD section 3.9: "A `ProjectManager` adds recipients to a report that
        has reached `APPROVED` or `LOCKED` — any earlier state fails with
        `ERR_REPORT_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/distribution_create_blocked_by_report_state
        """
        ctx = make_submitted_report()
        rid = ctx["report"]["id"]

        err = api_client.create_distribution_record(
            {"report_id": rid, "recipient_email": "insp@x.com",
             "recipient_role": "INSPECTOR"}, _PM)
        validate_error(err, ApiErrorId.ERR_REPORT_NOT_APPROVED)

        validate_success(api_client.start_review_report(rid, _PM))
        validate_success(api_client.approve_report(rid, _PM))
        validate_success(api_client.lock_report(rid, _ADMIN))
        record = add_distribution_record(rid, recipient_email="insp@x.com",
                                         recipient_role="INSPECTOR")
        assert record["status"] == "PENDING", \
            "LOCKED reports still accept distribution recipients"

    def test_full_lifecycle_send_acknowledge_and_delete_guard(self, api):
        """PRD section 3.9: "Sending is a `SystemAdmin` act that moves `PENDING`
        to `SENT`, re-checking the hold at send time, stamping `sent_at` from
        the logical clock" and "Acknowledgement by an `OwnerRep` moves `SENT` to
        the terminal `ACKNOWLEDGED` and stamps `acknowledged_at`" and "deleting
        a record is permitted from `PENDING` or `BLOCKED`, while a `SENT` or
        `ACKNOWLEDGED` record is retained for claims and its deletion fails with
        `ERR_DISTRIBUTION_ALREADY_SENT`."

        Design: Corner/endpoints/distribution_full_lifecycle
        """
        ctx = make_approved_report()
        record = add_distribution_record(ctx["report"]["id"],
                                         recipient_email="insp@x.com",
                                         recipient_role="INSPECTOR")

        sent = validate_success(api_client.send_distribution_record(
            record["id"], _ADMIN))
        assert sent["status"] == "SENT"
        assert_instant_equal(sent["sent_at"], "2026-08-05T17:00:00Z",
                             "sent_at stamps from the logical clock")

        delete_sent = api_client.delete_distribution_record(record["id"], _PM)
        validate_error(delete_sent, ApiErrorId.ERR_DISTRIBUTION_ALREADY_SENT)
        assert delete_sent.status_code == 409

        acked = validate_success(api_client.acknowledge_distribution_record(
            record["id"], _OWNER))
        assert acked["status"] == "ACKNOWLEDGED"
        assert_instant_equal(acked["acknowledged_at"], "2026-08-05T17:00:00Z")

    def test_duplicate_recipient_rejected(self, api):
        """PRD section 3.9: "supplying `recipient_email`, which must be unique
        among the report's existing records (else `ERR_DUPLICATE_RECIPIENT`)".

        Design: Corner/errors/distribution_duplicate_recipient_rejected
        """
        ctx = make_approved_report()
        add_distribution_record(ctx["report"]["id"], recipient_email="owner@x.com",
                                recipient_role="OWNER")

        dup = api_client.create_distribution_record(
            {"report_id": ctx["report"]["id"], "recipient_email": "owner@x.com",
             "recipient_role": "INTERNAL"}, _PM)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_RECIPIENT)
        assert dup.status_code == 409


class TestDistributionHoldCascade:
    def test_incident_close_releases_hold_and_unblocks_records(self, api):
        """PRD section 3.5: "Closing the last open incident unwinds the freeze.
        The report's `has_open_incident` recomputes — true while any linked
        incident sits outside the two closed states `CLOSED_RECORDABLE` and
        `CLOSED_NOT_RECORDABLE` — and when this was the final open incident it
        flips to false, `distribution_hold` follows it to false, and every
        `BLOCKED` distribution record on the report flips back to `PENDING`."

        Design: Difficulty/transitive_cascade/incident_close_releases_distribution_hold
        """
        ctx = make_approved_report()
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        record = add_distribution_record(rid, recipient_email="owner@x.com",
                                         recipient_role="OWNER")
        assert record["status"] == "PENDING"

        incident = add_incident(rid, aid, occurred_at="2026-08-05T15:00:00Z",
                                severity="FIRST_AID",
                                narrative="Minor cut treated onsite.")
        mid = get_distribution_record(record["id"])
        assert mid["status"] == "BLOCKED", \
            "incident create flips PENDING records to BLOCKED via the hold"

        closer = {"X-User-ID": "so-2", "X-User-Role": "SafetyOfficer",
                  "Content-Type": "application/json"}
        closed = validate_success(api_client.close_incident(
            incident["id"], {"outcome": "NOT_RECORDABLE"}, closer))
        assert closed["status"] == "CLOSED_NOT_RECORDABLE"

        report = get_report(rid)
        assert report["has_open_incident"] is False
        assert report["distribution_hold"] is False
        assert report["retention_class"] == "STANDARD", \
            "a non-recordable incident never sets CLAIMS_HOLD"
        after = get_distribution_record(record["id"])
        assert after["status"] == "PENDING", "hold release auto-unblocks records"

    def test_hold_releases_only_when_last_open_incident_closes(self, api):
        """PRD section 3.5: "The report's `has_open_incident` recomputes — true
        while any linked incident sits outside the two closed states
        `CLOSED_RECORDABLE` and `CLOSED_NOT_RECORDABLE` — and when this was the
        final open incident it flips to false, `distribution_hold` follows it to
        false, and every `BLOCKED` distribution record on the report flips back
        to `PENDING`."

        Design: Difficulty/transitive_cascade/incident_close_releases_distribution_hold
        """
        ctx = make_approved_report()
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        record = add_distribution_record(rid, recipient_email="owner@x.com")

        i1 = add_incident(rid, aid, occurred_at="2026-08-05T14:00:00Z",
                          severity="FIRST_AID", narrative="First minor injury.")
        i2 = add_incident(rid, aid, occurred_at="2026-08-05T15:00:00Z",
                          severity="NEAR_MISS", narrative="Second near miss.")
        assert get_distribution_record(record["id"])["status"] == "BLOCKED"

        closer = {"X-User-ID": "so-2", "X-User-Role": "SafetyOfficer",
                  "Content-Type": "application/json"}
        validate_success(api_client.close_incident(
            i1["id"], {"outcome": "NOT_RECORDABLE"}, closer))
        mid = get_report(rid)
        assert mid["has_open_incident"] is True, "one incident still open"
        assert mid["distribution_hold"] is True
        assert get_distribution_record(record["id"])["status"] == "BLOCKED"

        validate_success(api_client.close_incident(
            i2["id"], {"outcome": "NOT_RECORDABLE"}, closer))
        end = get_report(rid)
        assert end["has_open_incident"] is False
        assert end["distribution_hold"] is False
        assert get_distribution_record(record["id"])["status"] == "PENDING"

    def test_incident_on_approved_report_holds_and_blocks_send(self, api):
        """PRD section 2.6: "incident creation, and the escalation of a safety
        observation into an incident, are allowed on any report that is not yet
        `LOCKED`, even when the report is `SEALED`." PRD section 3.9: "While the
        report's `distribution_hold` is true, both creating and sending
        distribution records are refused with `ERR_DISTRIBUTION_HOLD`, and every
        `PENDING` record on the report stands flipped to `BLOCKED`".

        Design: Corner/cross_cutting_layers/incident_create_on_approved_report_sets_hold_and_blocks_pending
        """
        ctx = make_approved_report()
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        record = add_distribution_record(rid, recipient_email="owner@x.com",
                                         recipient_role="OWNER")

        incident = add_incident(rid, aid, occurred_at="2026-08-05T15:30:00Z",
                                severity="PROPERTY_DAMAGE",
                                narrative="Forklift struck stored material pallet.")
        assert incident["id"], "carve-out: incident creation allowed on SEALED"

        blocked = get_distribution_record(record["id"])
        assert blocked["status"] == "BLOCKED"

        send = api_client.send_distribution_record(record["id"], _ADMIN)
        # PRD 3.9 refuses sends "while the report's distribution_hold is true"
        # with ERR_DISTRIBUTION_HOLD, but the incident cascade has flipped the
        # record to BLOCKED, and PRD 2.9 orders the layer-6 state precondition
        # (ERR_DISTRIBUTION_INVALID_TRANSITION) ahead of the layer-10
        # distribution gates — either error is a PRD-faithful resolution.
        validate_error_is_one_of(send, [
            ApiErrorId.ERR_DISTRIBUTION_HOLD,
            ApiErrorId.ERR_DISTRIBUTION_INVALID_TRANSITION,
        ])
        assert send.status_code == 409

        report = get_report(rid)
        assert report["distribution_hold"] is True
        assert report["has_open_incident"] is True


class TestRetention:
    def test_retention_release_date_is_latest_sent_plus_retention_days(self, api):
        """PRD section 3.9: "The `retention_release_date` is null while the
        class is `CLAIMS_HOLD`, and likewise null while no distribution record
        on the report has reached `SENT` or `ACKNOWLEDGED`; otherwise it is the
        latest `sent_at` among the report's sent or acknowledged records, plus
        the project's `retention_days`."

        Design: Corner/calculations/retention_release_date_standard_vs_claims_hold
        """
        ctx = make_approved_report(project_overrides={"retention_days": 30})
        rid = ctx["report"]["id"]
        record = add_distribution_record(rid, recipient_email="owner@x.com",
                                         recipient_role="OWNER")

        before = get_report(rid)
        assert before["retention_release_date"] is None, \
            "null while no record has reached SENT or ACKNOWLEDGED"

        sent = validate_success(api_client.send_distribution_record(
            record["id"], _ADMIN))
        assert_instant_equal(sent["sent_at"], "2026-08-05T17:00:00Z")

        report = get_report(rid)
        assert report["retention_class"] == "STANDARD"
        assert_instant_equal(report["retention_release_date"],
                             "2026-09-04T17:00:00Z",
                             "sent_at 2026-08-05T17:00:00Z + 30 retention days")
