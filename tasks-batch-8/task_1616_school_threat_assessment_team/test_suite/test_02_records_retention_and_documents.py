"""Case listing, append-only records, records retention, and purge."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    append_document,
    assert_audit_event,
    assert_case_document,
    create_case,
    create_school,
    get_case,
    list_case_audit_events,
    list_case_documents,
    screen_case,
    set_clock,
    triage_case,
    validate_error,
    validate_paginated,
    validate_success,
)

IC = TEST_USERS["intake_coordinator_headers"]
TA = TEST_USERS["threat_assessor_headers"]
TL = TEST_USERS["team_lead_headers"]
DA = TEST_USERS["district_admin_headers"]


def _setup_closed_no_threat_case(school_id, alias, summary):
    """Case closed via a NON_SUBSTANTIVE screening (score 1)."""
    case = create_case(school_id, subject_alias=alias, summary=summary)
    triage_case(case["id"])
    return screen_case(case["id"], true_count=1)


class TestCaseListing:
    def test_list_cases_paginates_with_envelope_fields(self, api):
        """PRD: "The `limit` parameter specifies the maximum number of items to
        return; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100."
        PRD: "Unless otherwise specified, all list endpoints return resources
        sorted by their creation timestamp in ascending order, and paginated
        list responses carry `limit`, `offset`, `total_count`, and `has_more`
        in the `meta` object of the envelope."

        Design: Corner/entities/list_cases_paginates_with_envelope_fields
        """
        school = create_school(name="Page HS", school_code="PAG")
        aliases = []
        for i in (1, 2, 3):
            alias = f"STU-P{i}"
            create_case(school["id"], subject_alias=alias, summary=f"p{i}")
            aliases.append(alias)

        page1, meta1 = validate_paginated(
            api.list_cases(TL, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_cases(TL, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        ordered = page1 + page2
        # Ascending creation-timestamp order; identical logical-clock
        # timestamps satisfy this trivially regardless of tie-breaking.
        created = [item["created_at"] for item in ordered]
        assert created == sorted(created), (
            f"list must be ordered by created_at ascending, got {created}"
        )
        assert sorted(item["subject_alias"] for item in ordered) == sorted(aliases)


class TestAppendOnlyRecords:
    def test_document_and_audit_event_are_append_only_shape(self, api):
        """PRD: "Two resources are deliberately narrower. A `CaseDocument` is
        an append-only log entry and an `AuditEvent` is an immutable,
        tamper-evident record; both carry only `id` and `created_at`."
        PRD: "Neither `updated_at` nor `version` exists on these two types,
        and the API exposes no update or delete operations for either."
        PRD: "The new case opens in `INTAKE` status, and the system writes a
        `CASE_CREATED` audit event."

        Design: Corner/entities/document_and_audit_event_are_append_only_shape
        """
        school = create_school(name="Append HS", school_code="APP")
        case = create_case(school["id"], subject_alias="STU-APP",
                           summary="append-only")
        append_document(case["id"], doc_type="INTAKE_NOTE", body="first note",
                        author=IC)

        documents, doc_meta = validate_paginated(
            api.list_case_documents(case["id"], TL))
        assert doc_meta["total_count"] == 1
        assert_case_document(documents[0])
        assert documents[0]["body"] == "first note"
        assert documents[0]["author_user_id"] == "ic_1"

        events, ev_meta = validate_paginated(
            api.list_case_audit_events(case["id"], TL))
        assert ev_meta["total_count"] == 1
        assert_audit_event(events[0])
        assert events[0]["action"] == "CASE_CREATED"
        assert events[0]["actor_role"] == "IntakeCoordinator"


class TestRecordsRetentionPurge:
    def test_purge_on_exact_retention_date_purges_case(self, api):
        """PRD: "A `DistrictAdministrator` invokes the district-wide purge,
        which selects every case in `CLOSED_NO_THREAT` or `CLOSED_MANAGED`
        whose `purged_at` is still null and whose `retention_purge_after`
        falls on or before the current logical date — a case whose retention
        date equals the current date is purged."
        PRD: "Each selected case moves to `PURGED` (the case's only terminal
        state), its `purged_at` is stamped, its `subject_alias` is overwritten
        with the literal string `PURGED`, every one of its case documents has
        its `body` scrubbed to null and its `purged` flag set to true, and
        `CASE_PURGED` is audited."
        PRD: "The purge responds with `purged_count` and the list
        `purged_case_ids`."

        Design: Difficulty/boundary_precision_check/retention_purge_on_exact_date
        """
        school_a = create_school(name="Retention A", school_code="RA",
                                 enrollment_count=300, retention_days=365)
        case_a = create_case(school_a["id"], subject_alias="STU-R1",
                             summary="purge me on boundary")
        triage_case(case_a["id"])
        append_document(case_a["id"], doc_type="INTAKE_NOTE",
                        body="intake narrative A", author=IC)
        closed_a = screen_case(case_a["id"], true_count=1)
        assert closed_a["retention_purge_after"] == "2027-08-01"

        set_clock("2027-08-01T00:00:00Z")
        result = validate_success(api.purge_records(DA), 200)
        assert result["purged_count"] == 1
        assert result["purged_case_ids"] == [case_a["id"]]

        purged = get_case(case_a["id"])
        assert purged["status"] == "PURGED", (
            "a case whose retention date equals the current date is purged"
        )
        assert purged["subject_alias"] == "PURGED"
        assert purged["purged_at"] is not None

        documents, doc_meta = validate_paginated(
            api.list_case_documents(case_a["id"], TL))
        assert doc_meta["total_count"] == 1
        assert documents[0]["purged"] is True
        assert documents[0]["body"] is None, (
            "retention purge scrubs every case document body to null"
        )

    def test_case_one_day_short_of_retention_date_is_not_purged(self, api):
        """PRD: "A `DistrictAdministrator` invokes the district-wide purge,
        which selects every case in `CLOSED_NO_THREAT` or `CLOSED_MANAGED`
        whose `purged_at` is still null and whose `retention_purge_after`
        falls on or before the current logical date — a case whose retention
        date equals the current date is purged."
        PRD: "A `NON_SUBSTANTIVE` screening moves the case from `TRIAGED` to
        `CLOSED_NO_THREAT`, stamps `closed_at` with the current logical time,
        and computes `retention_purge_after` as the closure calendar date plus
        the school's `retention_days`."

        Design: Difficulty/boundary_precision_check/retention_purge_on_exact_date
        """
        school_b = create_school(name="Retention B", school_code="RB",
                                 enrollment_count=300, retention_days=366)
        case_b = create_case(school_b["id"], subject_alias="STU-R2",
                             summary="not yet purgeable")
        triage_case(case_b["id"])
        closed_b = screen_case(case_b["id"], true_count=1)
        assert closed_b["retention_purge_after"] == "2027-08-02", (
            "closure on 2026-08-01 plus 366 retention days"
        )

        set_clock("2027-08-01T00:00:00Z")
        result = validate_success(api.purge_records(DA), 200)
        assert result["purged_count"] == 0
        assert result["purged_case_ids"] == []

        after = get_case(case_b["id"])
        assert after["status"] == "CLOSED_NO_THREAT", (
            "a purge date after the current date is not yet eligible"
        )
        assert after["purged_at"] is None
        assert after["subject_alias"] == "STU-R2"

    def test_purge_with_no_eligible_cases_returns_zero(self, api):
        """PRD: "A `DistrictAdministrator` invokes the district-wide purge,
        which selects every case in `CLOSED_NO_THREAT` or `CLOSED_MANAGED`
        whose `purged_at` is still null and whose `retention_purge_after`
        falls on or before the current logical date — a case whose retention
        date equals the current date is purged."
        PRD: "The purge responds with `purged_count` and the list
        `purged_case_ids`."

        Design: Corner/endpoints/purge_with_no_eligible_cases_returns_zero
        """
        school = create_school(name="NoPurge HS", school_code="NPG",
                               enrollment_count=300)
        case = create_case(school["id"], subject_alias="STU-NP",
                           summary="open case")

        result = validate_success(api.purge_records(DA), 200)
        assert result["purged_count"] == 0
        assert result["purged_case_ids"] == []
        assert get_case(case["id"])["status"] == "INTAKE"

    def test_purged_case_is_terminal_for_reopen_and_documents(self, api):
        """PRD: "When a new report arrives concerning a previously closed
        subject, an `IntakeCoordinator` reopens the case: from either
        `CLOSED_NO_THREAT` or `CLOSED_MANAGED` (`ERR_CASE_NOT_REOPENABLE`
        otherwise) the case returns to `TRIAGED`, `closed_at` and
        `retention_purge_after` are cleared to null, `consecutive_missed_count`
        resets to zero, `escalation_flag` resets to false, the prior
        `triage_priority` is preserved, and `CASE_REOPENED` is written."
        PRD: "An `IntakeCoordinator`, `ThreatAssessor`, or `TeamLead` may
        append a document to any case that has not been purged — writing to a
        `PURGED` case is rejected with `ERR_CASE_PURGED` — supplying a
        `doc_type` of `INTAKE_NOTE`, `INTERVIEW_SUMMARY`, `PLAN_DOCUMENT`,
        `LEGAL_HOLD`, or `OTHER`, the document `body`, and optionally `sealed`
        (defaulting to false)."
        PRD: "The audit trail is confidential: only `TeamLead` and
        `DistrictAdministrator` may read it, and the audit list accepts an
        optional `action` filter."

        Design: Corner/state_machines/purged_case_is_terminal_for_reopen_and_documents
        """
        school = create_school(name="Purge HS", school_code="PRG",
                               enrollment_count=300)
        case = _setup_closed_no_threat_case(school["id"], "STU-P", "purge me")
        set_clock("2027-08-01T00:00:00Z")
        result = validate_success(api.purge_records(DA), 200)
        assert result["purged_count"] == 1

        reopen_resp = api.reopen_case(case["id"], IC)
        validate_error(reopen_resp, ApiErrorId.ERR_CASE_NOT_REOPENABLE)

        doc_resp = api.create_case_document(
            case["id"], {"doc_type": "OTHER", "body": "late note"}, TA)
        validate_error(doc_resp, ApiErrorId.ERR_CASE_PURGED)

        events, ev_meta = validate_paginated(api.list_case_audit_events(
            case["id"], DA, params={"action": "CASE_PURGED"}))
        assert ev_meta["total_count"] == 1, (
            "the audit trail remains readable after purge"
        )
        assert events[0]["action"] == "CASE_PURGED"
