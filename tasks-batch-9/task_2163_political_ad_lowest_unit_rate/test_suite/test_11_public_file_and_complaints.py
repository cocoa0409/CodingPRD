"""The public political file, its lateness measure, and the FCC complaint cycle."""

from test_helpers import (
    TEST_USERS,
    assert_complaint,
    assert_file_entry,
    assert_station_posture,
    create_station,
    file_complaint,
    hourly_spots,
    list_file_entries,
    post_file_entry,
    read_complaint,
    read_file_entry,
    read_order,
    read_station,
    respond_to_complaint,
    run_audit_sweep,
    set_clock,
    setup_issue_order,
    setup_station_with_two_overdue_adjustments,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER_ALPHA = TEST_USERS["officer_alpha_headers"]


def test_file_entry_posted_at_exactly_the_due_instant_counts_as_on_time(api):
    """PRD §3.9: "Otherwise, if the logical clock is on or before `due_at`, the outcome
    is `POSTED`; posting at exactly the due instant is on time."
    PRD §3.9: "In every late outcome, `late_by_seconds` records the whole seconds
    elapsed from `due_at` to `posted_at`; on an on-time posting it stays at zero.
    Posting from `PENDING` decrements the station's `pending_file_entry_count` by one,
    and where the outcome was `LATE_POSTED` it also increments `late_posting_count` by
    one."
    PRD §3.9: "From that instant and the station's configured
    `political_file_posting_deadline_hours` the platform derives `due_at`, the moment by
    which the entry must be posted."

    Design: Corner/calculations/file_entry_posted_at_exactly_due_at_counts_as_on_time
    """
    built = setup_issue_order(
        call_sign="WONT-TV",
        market_code="DMA-120",
        station_overrides={
            "licensee_name": "On Time Broadcasting",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        accept=True,
    )
    station = built["station"]

    entries = list_file_entries(order_id=built["order"]["id"])
    assert len(entries) == 1
    entry = entries[0]
    assert_file_entry(entry)
    assert entry["due_at"] == "2026-08-06T09:00:00.000Z"
    assert entry["posting_status"] == "PENDING"

    set_clock("2026-08-06T09:00:00Z")
    posted = validate_success(
        api.post_file_entry(
            entry["id"],
            {"public_file_url": "https://publicfiles.example/wont/accept-1"},
            OFFICER_ALPHA,
        )
    )
    assert posted["posting_status"] == "POSTED"
    assert posted["late_by_seconds"] == 0
    assert posted["posted_at"] == "2026-08-06T09:00:00.000Z"
    assert posted["public_file_url"] == "https://publicfiles.example/wont/accept-1"

    refreshed_station = read_station(station["id"])
    assert refreshed_station["pending_file_entry_count"] == 0
    assert refreshed_station["late_posting_count"] == 0
    assert refreshed_station["compliance_posture"] == "OPEN"


def test_exactly_two_overdue_entries_freeze_the_station(api):
    """PRD §3.1: "Take the station's current count of overdue political file entries and
    its current count of open complaints, and consider **the larger of those two
    numbers** — never their sum. If that larger number is 2 or more, the posture is
    `FROZEN`."
    PRD §3.1: "Both thresholds are inclusive at their boundary: a station with exactly
    two overdue file entries and no complaints is `FROZEN`, and a station with exactly
    one open complaint and no overdue entries is `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/posture_freezes_at_exactly_two_overdue_and_relaxes_to_restricted_at_one
    """
    built = setup_station_with_two_overdue_adjustments(
        call_sign="WBND-TV", market_code="DMA-712", run_sweep=True
    )
    swept = built["swept_station"]

    assert swept["overdue_file_entry_count"] == 2
    assert swept["open_complaint_count"] == 0
    assert swept["compliance_posture"] == "FROZEN"
    assert_station_posture(swept)


def test_posting_one_of_two_overdue_entries_relaxes_the_posture_to_restricted(api):
    """PRD §3.1: "Otherwise, if it is 1 or more, the posture is `RESTRICTED`. Otherwise
    the posture is `OPEN`."
    PRD §3.9: "If the entry was sitting in `OVERDUE`, the outcome is `LATE_POSTED`
    regardless of anything else."
    PRD §3.9: "Posting from `OVERDUE` decrements `overdue_file_entry_count` by one,
    increments `late_posting_count` by one, and triggers a recomputation of the
    station's `compliance_posture` from the reduced overdue count."
    PRD §3.9: "In every late outcome, `late_by_seconds` records the whole seconds
    elapsed from `due_at` to `posted_at`; on an on-time posting it stays at zero."

    Design: Difficulty/boundary_precision_check/posture_freezes_at_exactly_two_overdue_and_relaxes_to_restricted_at_one
    """
    built = setup_station_with_two_overdue_adjustments(
        call_sign="WBN2-TV", market_code="DMA-713", run_sweep=True
    )
    station = built["station"]
    first_adjustment, second_adjustment = built["adjustment_entries"]
    assert built["swept_station"]["compliance_posture"] == "FROZEN"

    posted = validate_success(
        api.post_file_entry(
            first_adjustment["id"],
            {"public_file_url": "https://publicfiles.example/wbnd/adj-1"},
            OFFICER_ALPHA,
        )
    )
    assert posted["posting_status"] == "LATE_POSTED"
    assert posted["late_by_seconds"] == 172800, (
        "two days elapsed between the 2026-08-06T09:00:00Z deadline and the posting"
    )

    relaxed = read_station(station["id"])
    assert relaxed["overdue_file_entry_count"] == 1
    assert relaxed["compliance_posture"] == "RESTRICTED", (
        "one overdue entry is below the freeze threshold but at the restrict threshold"
    )
    assert relaxed["late_posting_count"] == 1
    assert_station_posture(relaxed)

    assert read_file_entry(second_adjustment["id"])["posting_status"] == "OVERDUE"


def test_suspended_order_resumes_once_the_posture_returns_to_open(api):
    """PRD §3.9: "Step six is the return leg. If step four left the posture at `OPEN`,
    every order on the station sitting in `SUSPENDED` moves `SUSPENDED → ACCEPTED`,
    restoring it to live status once the station has cleared its overdue file entries
    and its open complaints."
    PRD §3.9: "If the entry was sitting in `OVERDUE`, the outcome is `LATE_POSTED`
    regardless of anything else."

    Design: Corner/state_machines/suspended_order_resumes_to_accepted_when_posture_returns_to_open
    """
    built = setup_station_with_two_overdue_adjustments(
        call_sign="WRSM-TV",
        market_code="DMA-113",
        advertiser_kind="ISSUE",
        run_sweep=True,
    )
    station, order, advertiser = built["station"], built["order"], built["advertiser"]
    first_adjustment, second_adjustment = built["adjustment_entries"]

    assert built["swept_station"]["compliance_posture"] == "FROZEN"
    assert read_order(order["id"], advertiser["id"])["status"] == "SUSPENDED"

    post_file_entry(first_adjustment["id"], "https://publicfiles.example/wrsm/adj-1")
    post_file_entry(second_adjustment["id"], "https://publicfiles.example/wrsm/adj-2")

    resumed_station = run_audit_sweep(station["id"])
    assert resumed_station["overdue_file_entry_count"] == 0
    assert resumed_station["late_posting_count"] == 2
    assert resumed_station["compliance_posture"] == "OPEN"

    resumed_order = read_order(order["id"], advertiser["id"])
    assert resumed_order["status"] == "ACCEPTED"
    assert resumed_order["payment_status"] == "REFUND_DUE", (
        "the settlement dimension is untouched by the resume"
    )

    assert read_file_entry(first_adjustment["id"])["posting_status"] == "LATE_POSTED"
    assert read_file_entry(second_adjustment["id"])["posting_status"] == "LATE_POSTED"


def test_complaint_reopens_after_the_cure_period_and_closes_on_a_cured_remedy(api):
    """PRD §3.9: "Filing stamps `filed_at` with the logical clock, derives
    `response_due_at` as 240 hours — ten days — after that instant, opens the complaint
    in `OPEN` with `remedy_code`, `cure_due_at`, `responded_at`, `response_text` and
    `responded_by_user_id` all null and `late_response` false, then increments the
    station's `open_complaint_count` by one and recomputes its `compliance_posture`."
    PRD §3.9: "The response stores `response_text` and `remedy_code`, stamps
    `responded_at` with the logical clock and `responded_by_user_id` with the acting
    `X-User-ID`, and — when and only when the remedy is `PENDING_CURE` — sets
    `cure_due_at` to 720 hours, that is thirty days, after `responded_at`; for `CURED`
    and `NO_VIOLATION` the `cure_due_at` field is left null."
    PRD §3.9: "A complaint sitting in `RESPONDED` whose `remedy_code` is `PENDING_CURE`
    and whose `cure_due_at` the logical clock has reached — on it or past it — moves
    `RESPONDED → REOPENED`, which increments `open_complaint_count` by one and
    recomputes `compliance_posture`. A complaint sitting in `RESPONDED` whose
    `remedy_code` is `CURED` or `NO_VIOLATION` moves `RESPONDED → CLOSED`, which is
    terminal."
    PRD §3.9: "Responding late is permitted but recorded: the response is accepted
    whenever the complaint is open, and `late_response` is set to true when the logical
    clock is strictly later than `response_due_at`."

    Design: Corner/state_machines/complaint_reopens_after_cure_period_then_closes_on_a_cured_remedy
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WCUR-TV",
        licensee_name="Cure Period Broadcasting",
        market_code="DMA-111",
        political_file_posting_deadline_hours=24,
    )
    complaint = file_complaint(
        station["id"],
        complainant_name="Ida Brennan",
        allegation_code="FILE_TIMELINESS",
        narrative="Entries were not posted within one business day.",
    )
    assert_complaint(complaint)
    assert complaint["response_due_at"] == "2026-08-15T09:00:00.000Z"
    assert read_station(station["id"])["open_complaint_count"] == 1

    pending_cure = respond_to_complaint(
        complaint["id"], "Corrective posting workflow scheduled.", "PENDING_CURE"
    )
    assert pending_cure["status"] == "RESPONDED"
    assert pending_cure["cure_due_at"] == "2026-09-04T09:00:00.000Z"
    after_first_response = read_station(station["id"])
    assert after_first_response["open_complaint_count"] == 0
    assert after_first_response["compliance_posture"] == "OPEN"

    set_clock("2026-09-04T09:00:00Z")
    reopened_station = run_audit_sweep(station["id"])
    assert reopened_station["open_complaint_count"] == 1
    assert reopened_station["compliance_posture"] == "RESTRICTED"
    assert read_complaint(complaint["id"])["status"] == "REOPENED"

    cured = respond_to_complaint(complaint["id"], "Backlog cleared and audited.", "CURED")
    assert cured["status"] == "RESPONDED"
    assert cured["late_response"] is True, (
        "the CURED response landed after the ten-day response deadline"
    )

    run_audit_sweep(station["id"])
    closed = read_complaint(complaint["id"])
    assert closed["status"] == "CLOSED"
    assert closed["remedy_code"] == "CURED"

    final_station = read_station(station["id"])
    assert final_station["open_complaint_count"] == 0
    assert final_station["compliance_posture"] == "OPEN"
