"""Reporting cadence, checkpoints, the logical clock and reporting windows."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_status_report,
    classified_case,
    create_status_report_payload,
    make_coordinator_headers,
    make_firm_officer_headers,
    register_firm,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = make_coordinator_headers("coord-1")


def test_rejecting_a_report_extends_the_due_date_and_clears_the_narrative(api):
    """PRD §3.8: "Submission stamps `submitted_at` from the clock, stores the supplied `narrative`, and snapshots `reported_effectiveness_pct` from the recall's `official_effectiveness_pct` at that exact instant, so the report preserves what was true when it was filed rather than what is true when it is read."
    PRD §3.8: "`REJECT` sends the report back along `SUBMITTED → PENDING`, increments `reject_count`, clears `submitted_at` and `narrative` back to null, and grants a two-day extension by adding 2 days to `due_at` and setting `period_end` equal to the new `due_at`."

    Design: Corner/state_machines/status_report_reject_extends_due_at_by_two_days_and_clears_narrative
    """
    case = classified_case(clock="2026-09-01T00:00:00Z")
    reports = case.status_reports()
    assert len(reports) == 1
    first = reports[0]
    assert first["report_kind"] == "PERIODIC"
    assert first["due_at"] == "2026-09-08T00:00:00.000Z"

    submitted = case.submit_report(
        first["id"], narrative="First periodic report: notifications in progress."
    )
    assert submitted["reported_effectiveness_pct"] == 100.00

    rejected = case.adjudicate_report(
        first["id"], "REJECT", adjudication_note="Consignee counts missing."
    )
    assert_status_report(rejected)
    assert rejected["status"] == "PENDING"
    assert rejected["due_at"] == "2026-09-10T00:00:00.000Z"
    assert rejected["period_end"] == "2026-09-10T00:00:00.000Z"
    assert rejected["reject_count"] == 1
    assert rejected["narrative"] is None
    assert rejected["submitted_at"] is None


def test_adjudicating_a_pending_report_is_an_invalid_report_state(api):
    """PRD §3.8: "Submitting a report that is neither `PENDING` nor `OVERDUE`, or adjudicating one that is not `SUBMITTED`, is refused with `ERR_INVALID_REPORT_STATE`."

    Design: Corner/errors/adjudicate_a_pending_status_report_returns_invalid_report_state
    """
    case = classified_case()
    first = case.status_reports()[0]

    response = api.adjudicate_status_report(
        first["id"], {"decision": "ACCEPT"}, COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REPORT_STATE.value)
    assert response.status_code == 409

    after = case.status_reports()[0]
    assert after["status"] == "PENDING"
    assert after["reject_count"] == 0


def test_the_logical_clock_starts_at_the_declared_default(api):
    """PRD §2.4: "The server keeps a single logical clock whose startup value is exactly `2026-08-01T00:00:00Z`; before any client sets it, the server must read that default and must never fall back to real wall-clock time."
    PRD §2.4: "A clock-setting capability accepts a `to_iso8601` instant and jumps the clock to it, returning the new `current_utc`; no entity is mutated by the jump and no aging, cadence or overdue rule fires until the next checkpoint or write touches the case."
    PRD §3.3: "On a first classification the server mints the recall's first status report — `report_kind` `PERIODIC`, `period_index` 1, `period_start` at the current logical instant, and both `period_end` and `due_at` at that instant plus `report_cadence_days` days — in `status` `PENDING`."

    Design: Corner/endpoints/logical_clock_startup_default_is_2026_08_01
    """
    case = classified_case()
    reports = case.status_reports()
    assert reports[0]["period_start"] == "2026-08-01T00:00:00.000Z"
    assert reports[0]["due_at"] == "2026-08-08T00:00:00.000Z"

    version_before = case.read_recall()["version"]
    clock = set_clock("2026-08-15T00:00:00Z")
    assert clock["current_utc"] == "2026-08-15T00:00:00.000Z"
    assert case.read_recall()["version"] == version_before


def test_checkpoint_mints_the_next_periodic_report_only_when_none_is_pending(api):
    """PRD §3.8: "Fifth and last, if the recall's `status` is neither `DRAFT` nor `TERMINATED`, and no status report of the recall is left in `PENDING`, and at least one status report of the recall exists, the server mints the next one: `report_kind` `PERIODIC`, `period_index` one above the current maximum, `period_start` at the current logical instant, `period_end` and `due_at` at that instant plus `report_cadence_days` days, `status` `PENDING`."
    PRD §3.8: "First, every status report of the recall whose `due_at` is at or before the current logical instant flips `PENDING → OVERDUE`, and each flip increments the recall's `overdue_report_count` by one and recomputes `compliance_flag`."
    PRD §3.8: "`ACCEPT` advances `SUBMITTED → ACCEPTED`, which is terminal."

    Design: Corner/endpoints/checkpoint_mints_the_next_periodic_report_only_when_none_is_pending
    """
    case = classified_case(clock="2026-09-01T00:00:00Z")
    first = case.status_reports()[0]

    case.checkpoint()
    assert len(case.status_reports()) == 1, (
        "No new report may be minted while one is still PENDING"
    )

    case.submit_report(first["id"], narrative="Notifications dispatched; retrieval starting.")
    case.adjudicate_report(first["id"], "ACCEPT")

    set_clock("2026-09-10T00:00:00Z")
    after = case.checkpoint()
    assert after["overdue_report_count"] == 0
    assert after["compliance_flag"] == "COMPLIANT"

    reports = case.status_reports()
    assert len(reports) == 2
    minted = [r for r in reports if r["period_index"] == 2][0]
    assert minted["report_kind"] == "PERIODIC"
    assert minted["status"] == "PENDING"
    assert minted["period_start"] == "2026-09-10T00:00:00.000Z"
    assert minted["due_at"] == "2026-09-17T00:00:00.000Z"

    accepted = [r for r in reports if r["id"] == first["id"]][0]
    assert accepted["status"] == "ACCEPTED"


def test_an_unknown_recall_is_reported_before_a_malformed_body(api):
    """PRD §2.6: "Checks are evaluated strictly in the ascending order listed below; the first violated rung wins and short-circuits every later rung."
    PRD §2.6: "The `Recall` addressed by the leading `/recalls/{id}` path segment, or reached through a sub-resource's `recall_id`, exists — otherwise `ERR_RECALL_NOT_FOUND` (404)."
    PRD §2.9: "Paths are resolved strictly left to right, and each segment is validated before the next is considered."

    Design: Corner/validations/unknown_recall_with_invalid_body_returns_not_found_before_invalid_request
    """
    firm = register_firm()
    officer = make_firm_officer_headers(firm["id"])

    response = api.create_cost_entry(
        NON_EXISTENT_UUID,
        {"category": "NOT_A_CATEGORY", "amount_cents": -5, "description": ""},
        officer,
    )
    error = validate_error(response, ApiErrorId.ERR_RECALL_NOT_FOUND.value)
    assert response.status_code == 404
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


class TestReportingWindowOverlap:
    """Reporting windows are half-open, so adjacency is fine but overlap is not."""

    def test_a_window_overlapping_the_open_period_is_refused(self, api):
        """PRD §3.8: "A new window must not overlap any existing window on the same recall: overlap means the new start falls before an existing end *and* that existing start falls before the new end, and any such collision is refused with `ERR_REPORT_PERIOD_OVERLAP`."
        PRD §3.8: "Reporting windows are half-open, covering `period_start` inclusive up to `period_end` exclusive, and `period_start` must be strictly earlier than `period_end`."

        Design: Difficulty/resource_temporal_overlap/interim_report_window_rejects_overlap_but_accepts_exact_adjacency
        """
        case = classified_case(clock="2026-09-01T00:00:00Z")
        existing = case.status_reports()[0]
        assert existing["period_start"] == "2026-09-01T00:00:00.000Z"
        assert existing["period_end"] == "2026-09-08T00:00:00.000Z"

        response = api.create_status_report(
            case.recall_id,
            create_status_report_payload(
                "2026-09-05T00:00:00Z", "2026-09-10T00:00:00Z", report_kind="INTERIM"
            ),
            case.officer,
        )
        validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value)
        assert response.status_code == 409

        _, meta = validate_paginated(
            api.list_status_reports(case.recall_id, COORDINATOR)
        )
        assert meta["total_count"] == 1

    def test_a_window_starting_exactly_at_the_existing_end_is_accepted(self, api):
        """PRD §3.8: "Exact adjacency, where a new window starts precisely at an existing window's end, is explicitly allowed."
        PRD §3.8: "Every report — minted or filed — takes a `period_index` one greater than the largest index currently on the recall, so indices are strictly increasing within a recall and never repeat even after rejections; `due_at` is always equal to `period_end` for every report kind; and the report starts in `status` `PENDING` with `submitted_at`, `narrative` and `adjudication_note` null, `reported_effectiveness_pct` 0 and `reject_count` 0."

        Design: Difficulty/resource_temporal_overlap/interim_report_window_rejects_overlap_but_accepts_exact_adjacency
        """
        case = classified_case(clock="2026-09-01T00:00:00Z")

        response = api.create_status_report(
            case.recall_id,
            create_status_report_payload(
                "2026-09-08T00:00:00Z", "2026-09-12T00:00:00Z", report_kind="INTERIM"
            ),
            case.officer,
        )
        adjacent = validate_success(response, 201)
        assert_status_report(adjacent)
        assert adjacent["period_index"] == 2
        assert adjacent["period_end"] == adjacent["due_at"]
        assert adjacent["status"] == "PENDING"
        assert adjacent["report_kind"] == "INTERIM"

        _, meta = validate_paginated(
            api.list_status_reports(case.recall_id, COORDINATOR)
        )
        assert meta["total_count"] == 2
