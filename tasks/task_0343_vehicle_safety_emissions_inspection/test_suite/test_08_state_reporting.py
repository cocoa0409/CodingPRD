"""State reporting to the jurisdiction: batches, lines, totals, and OCC on submit.

Covers Difficulty queue: non_linear_state_machine (batch REJECTED -> OPEN reopen
cycle), transitive_cascade (attach line recomputes batch totals and version),
compensating_invariant (attach then detach conserves the fee total),
boundary_precision_check (submit empty batch rejected). Covers Corner queue:
state_machines (accepted-terminal reopen rejected), validations (non-terminal line
not eligible), cross_cutting (OCC stale batch on submit).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as F

SM = TEST_USERS["station_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
RECEP = TEST_USERS["receptionist_headers"]
AUDITOR = TEST_USERS["state_auditor_headers"]


# ===========================================================================
# Difficulty: transitive_cascade — attach line recomputes totals + version
# ===========================================================================
def test_attach_line_recomputes_batch_totals_and_bumps_version(api):
    """PRD §3.11: "After every attach the batch's totals are recomputed: `line_count`
    is set to the number of attached lines and `total_reported_fee_cents` to the sum
    of those lines' `fee_cents`, and the batch's `version` is incremented."

    Design: Difficulty/transitive_cascade/attach_line_recomputes_batch_totals_and_version
    """
    # PASSED PASSENGER+OBD record has fee 3700.
    station, profile, lane, appt, passed = F.setup_passed_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    batch = F.open_batch(api, station["id"])
    version_before = batch["version"]
    F.attach_line(api, batch["id"], passed["id"])
    fresh = get_success_data(api.get_state_report_batch(batch["id"], SM))
    assert fresh["line_count"] == 1, f"line_count must be 1, got {fresh['line_count']}"
    assert fresh["total_reported_fee_cents"] == 3700, \
        f"total must snapshot the 3700 fee, got {fresh['total_reported_fee_cents']}"
    assert fresh["version"] == version_before + 1, \
        "attaching a line must bump the batch version by one"


def test_attached_line_snapshots_record_fee(api):
    """PRD §3.11: "On attach, the line snapshots the record's overall outcome into
    `reported_result` (`PASS` or `FAIL`) and the record's frozen `fee_cents` into the
    line's own `fee_cents`; it carries the owning `batch_id` and the source
    `record_id`."

    Design: Difficulty/transitive_cascade/attach_line_recomputes_batch_totals_and_version
    """
    station, profile, lane, appt, passed = F.setup_passed_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    batch = F.open_batch(api, station["id"])
    line = F.attach_line(api, batch["id"], passed["id"])
    assert line["reported_result"] == "PASS"
    assert line["fee_cents"] == 3700, f"line fee must snapshot 3700, got {line['fee_cents']}"


# ===========================================================================
# Difficulty: compensating_invariant — attach then detach conserves fee total
# ===========================================================================
def test_attach_then_detach_conserves_total_fee_and_line_count(api):
    """PRD §3.11: "A `StationManager` may detach a line from an open batch by naming
    the record. Detaching removes the line, reruns the same recomputation of
    `line_count` and `total_reported_fee_cents` over the remaining lines, and
    increments the batch's `version`."

    Design: Difficulty/compensating_invariant/batch_line_attach_then_detach_conserves_total_fee
    """
    station, profile, lane, appt, passed = F.setup_passed_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    batch = F.open_batch(api, station["id"])
    F.attach_line(api, batch["id"], passed["id"])
    after_attach = get_success_data(api.get_state_report_batch(batch["id"], SM))
    assert after_attach["total_reported_fee_cents"] == 3700

    detached = validate_success(
        api.detach_state_report_line(batch["id"], passed["id"], SM), 200)
    assert detached["total_reported_fee_cents"] == 0, \
        f"detaching the only line must return the total to 0, got {detached['total_reported_fee_cents']}"
    assert detached["line_count"] == 0, \
        f"detaching the only line must return line_count to 0, got {detached['line_count']}"


def test_detach_line_removes_it_and_bumps_batch_version(api):
    """PRD §3.11: "Detaching removes the line, reruns the same recomputation of
    `line_count` and `total_reported_fee_cents` over the remaining lines, and
    increments the batch's `version`."

    Design: Difficulty/compensating_invariant/batch_line_attach_then_detach_conserves_total_fee
    """
    station, profile, lane, appt, passed = F.setup_passed_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    batch = F.open_batch(api, station["id"])
    F.attach_line(api, batch["id"], passed["id"])
    after_attach = get_success_data(api.get_state_report_batch(batch["id"], SM))
    version_after_attach = after_attach["version"]

    detached = validate_success(
        api.detach_state_report_line(batch["id"], passed["id"], SM), 200)
    assert detached["version"] == version_after_attach + 1, \
        "detaching a line must bump the batch version by one"
    # The line itself is gone.
    data, _meta = validate_paginated(
        api.list_state_report_lines(SM, params={"record_id": passed["id"]}))
    assert len(data) == 0, f"the detached line must no longer be listed, got {len(data)}"


# ===========================================================================
# Difficulty: non_linear_state_machine — batch REJECTED -> OPEN reopen cycle
# ===========================================================================
def test_rejected_batch_reopens_to_open(api):
    """PRD §3.11: "A rejected batch can be reopened by a `StationManager`, advancing
    `REJECTED → OPEN` so its lines become editable again, in a branching
    submit/reject cycle; the reopen bumps the `version`."

    Design: Difficulty/non_linear_state_machine/state_report_batch_rejected_to_open_reopen_cycle
    """
    station, record, rejected = F.setup_rejected_batch(api, clock_iso="2026-06-10T09:00:00Z")
    assert rejected["status"] == "REJECTED"
    reopened = validate_success(api.reopen_state_report_batch(rejected["id"], SM), 200)
    assert reopened["status"] == "OPEN", \
        f"reopening a REJECTED batch must return it to OPEN, got {reopened['status']}"


def test_reopened_batch_can_be_resubmitted(api):
    """PRD §3.11: "Submitting a batch is restricted to a `StationManager`, requires
    the batch to be `OPEN`, requires `line_count` of at least 1 (a batch with no
    lines is rejected with `ERR_EMPTY_BATCH`), and carries `expected_batch_version`
    for the stale-batch check of §2.8."
    PRD §3.11: "On success the batch transitions `OPEN → SUBMITTED`, its lines are
    frozen against further attach or detach, and its `version` is incremented."

    Design: Difficulty/non_linear_state_machine/state_report_batch_rejected_to_open_reopen_cycle
    """
    station, record, rejected = F.setup_rejected_batch(api, clock_iso="2026-06-10T09:00:00Z")
    reopened = get_success_data(api.reopen_state_report_batch(rejected["id"], SM))
    assert reopened["status"] == "OPEN"
    # The single line is still attached, so a resubmit on the current version succeeds.
    resubmitted = validate_success(
        api.submit_state_report_batch(
            reopened["id"], {"expected_batch_version": reopened["version"]}, SM), 200)
    assert resubmitted["status"] == "SUBMITTED"


# ===========================================================================
# Difficulty: boundary_precision_check — submit empty batch rejected
# ===========================================================================
def test_submit_empty_batch_returns_empty_batch(api):
    """PRD §3.11: "Submitting a batch is restricted to a `StationManager`, requires
    the batch to be `OPEN`, requires `line_count` of at least 1 (a batch with no
    lines is rejected with `ERR_EMPTY_BATCH`), and carries `expected_batch_version`
    for the stale-batch check of §2.8."

    Design: Difficulty/boundary_precision_check/submit_empty_batch_zero_line_count_rejected
    """
    station = F.create_station(api)
    batch = F.open_batch(api, station["id"])
    assert batch["line_count"] == 0
    validate_error(
        api.submit_state_report_batch(batch["id"], {"expected_batch_version": batch["version"]}, SM),
        ApiErrorId.ERR_EMPTY_BATCH.value)


def test_submit_batch_with_one_line_succeeds(api):
    """PRD §3.11: "On success the batch transitions `OPEN → SUBMITTED`, its lines are
    frozen against further attach or detach, and its `version` is incremented."

    Design: Difficulty/boundary_precision_check/submit_empty_batch_zero_line_count_rejected
    """
    station, record, batch, line = F.setup_open_batch_with_line(api, clock_iso="2026-06-10T09:00:00Z")
    assert batch["line_count"] == 1
    submitted = validate_success(
        api.submit_state_report_batch(batch["id"], {"expected_batch_version": batch["version"]}, SM), 200)
    assert submitted["status"] == "SUBMITTED"


# ===========================================================================
# Corner: state_machines — accepted (terminal) batch cannot be reopened
# ===========================================================================
def test_accepted_batch_reopen_returns_invalid_state(api):
    """PRD §3.11: "acceptance advances `SUBMITTED → ACCEPTED` (terminal) and
    rejection advances `SUBMITTED → REJECTED`, each bumping the `version`."
    PRD §3.11: "Any of these transitions attempted from a state in which it is
    undefined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/state_batch_accept_terminal_then_reopen_returns_invalid_state
    """
    station, record, accepted = F.setup_accepted_batch(api, clock_iso="2026-06-10T09:00:00Z")
    assert accepted["status"] == "ACCEPTED"
    validate_error(api.reopen_state_report_batch(accepted["id"], SM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: validations — attaching a non-terminal record is not eligible
# ===========================================================================
def test_attach_non_terminal_record_returns_line_not_eligible(api):
    """PRD §3.11: "A line may be attached only for a record that has reached a
    terminal pass/fail outcome — that is, a record in `PASSED` or `FAILED` — and a
    given record may appear at most once per batch; an attempt to attach a
    non-terminal record or to duplicate one already on the batch is rejected with
    `ERR_LINE_NOT_ELIGIBLE`."

    Design: Corner/validations/attach_non_terminal_record_to_batch_returns_line_not_eligible
    """
    station, profile, lane, appt, record = F.setup_in_progress_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    batch = F.open_batch(api, station["id"])
    validate_error(
        api.attach_state_report_line(batch["id"], F.attach_line_payload(record["id"]), SM),
        ApiErrorId.ERR_LINE_NOT_ELIGIBLE.value)


# ===========================================================================
# Cross-cutting: OCC — stale batch version on submit
# ===========================================================================
def test_submit_batch_with_stale_version_returns_stale_version(api):
    """PRD §2.8: "If a line was attached or detached after that read — each such
    change bumps the batch's `version` and recomputes its totals — the submitter's
    view of `line_count` and `total_reported_fee_cents` is stale, and submission is
    refused with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_batch_submit_stale_version_returns_412
    """
    station, profile, lane, appt, record = F.setup_decided_passenger_record(
        api, safety_pass=False, emissions_pass=True, clock_iso="2026-06-10T09:00:00Z")
    batch = F.open_batch(api, station["id"])
    stale_version = batch["version"]  # captured at creation
    F.attach_line(api, batch["id"], record["id"])  # advances the batch version
    validate_error(
        api.submit_state_report_batch(batch["id"], {"expected_batch_version": stale_version}, SM),
        ApiErrorId.ERR_STALE_VERSION.value)
