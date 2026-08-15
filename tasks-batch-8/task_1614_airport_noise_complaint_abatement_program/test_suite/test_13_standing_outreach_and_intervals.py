"""Complainant standing and outreach: the 9-vs-10 repeat-threshold boundary,
the full outreach-case lifecycle with the repeat-baseline reset, the manual
case guard, plus the half-open outage interval semantics and the terminal
lockdown of OPERATED flights."""
from test_helpers import (
    ApiErrorId,
    assert_monitor_outage,
    assert_same_instant,
    create_complaint,
    create_complainant,
    create_flight,
    create_monitor,
    create_operator,
    log_contact,
    operate_flight,
    record_outage,
    set_clock,
    setup_repeat_complainant,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]


def test_nine_filings_keep_good_standing(api):
    """PRD 3.1: "When the recomputed count reaches ten while remaining below
    twenty-five, standing moves from `GOOD_STANDING` to `REPEAT`".
    PRD 3.6: "The system auto-creates one — `OPEN`, with the matching threshold
    trigger — whenever a complainant's standing crosses into `REPEAT` or
    `RESTRICTED`".

    Design: Difficulty/boundary_precision_check/repeat_standing_threshold_9_vs_10_complaints
    """
    ctx = setup_repeat_complainant(filings=9)

    person = validate_success(api.get_complainant(ctx["complainant"]["id"], LIAISON))
    # Nine filings stay below the inclusive ten threshold.
    assert person["complaints_90d"] == 9
    assert person["filed_total"] == 9
    assert person["standing"] == "GOOD_STANDING"
    # No threshold crossing -> no auto-created outreach case.
    assert ctx["cases"] == []


def test_tenth_filing_flips_repeat_and_autocreates_outreach_case(api):
    """PRD 3.1: "When the recomputed count reaches ten while remaining below
    twenty-five, standing moves from `GOOD_STANDING` to `REPEAT`; at twenty-five
    or more it moves from `REPEAT` to `RESTRICTED`, with both thresholds
    inclusive."
    PRD 3.4: "filing also refreshes the complainant's counters and
    trailing-window count, re-evaluating standing per §3.1 and auto-creating an
    outreach case when the standing crosses into `REPEAT` or `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/repeat_standing_threshold_9_vs_10_complaints
    """
    ctx = setup_repeat_complainant(filings=9)
    complainant = ctx["complainant"]

    create_complaint(complainant["id"], "2026-07-10T08:00:00Z")

    person = validate_success(api.get_complainant(complainant["id"], LIAISON))
    assert person["complaints_90d"] == 10
    assert person["standing"] == "REPEAT"

    cases, meta = validate_paginated(
        api.list_complainant_outreach_cases(complainant["id"], LIAISON)
    )
    assert meta["total_count"] == 1
    assert cases[0]["status"] == "OPEN"
    assert cases[0]["trigger_reason"] == "REPEAT_THRESHOLD"


def test_outreach_case_full_lifecycle_resets_standing(api):
    """PRD 3.6: "Logging a contact with `outcome` `NO_ANSWER` moves an `OPEN`
    case to `CONTACT_ATTEMPTED` and increments `contact_attempts` ... Logging
    `REACHED` moves an `OPEN` or `CONTACT_ATTEMPTED` case to `ENGAGED`, again
    counting the attempt."
    PRD 3.6: "an `ENGAGED` case may go `DORMANT`, and a `DORMANT` case may be
    reactivated to `OPEN`."
    PRD 3.6: "From `ENGAGED`, the liaison resolves the case with a
    `resolution_summary`: the case becomes `RESOLVED` with `resolved_at`
    stamped, and — the decisive side effect — the complainant's
    `repeat_baseline_at` is set to that instant. Because `complaints_90d` only
    counts filings at or after the baseline, resolution shrinks the trailing
    window immediately, the count is recomputed, and standing is re-evaluated".

    Design: Corner/state_machines/outreach_case_full_lifecycle_resets_standing
    """
    ctx = setup_repeat_complainant(filings=10)
    complainant = ctx["complainant"]
    assert len(ctx["cases"]) == 1
    case = ctx["cases"][0]
    assert case["status"] == "OPEN"
    assert case["trigger_reason"] == "REPEAT_THRESHOLD"

    # Advance past the filings so the baseline set at resolution is strictly
    # later than every filing's created_at.
    set_clock("2026-08-02T00:00:00Z")

    first = log_contact(case["id"], "NO_ANSWER")
    assert first["status"] == "CONTACT_ATTEMPTED"
    assert first["contact_attempts"] == 1

    second = log_contact(case["id"], "REACHED")
    assert second["status"] == "ENGAGED"
    assert second["contact_attempts"] == 2

    dormant = validate_success(api.mark_dormant(case["id"], {}, LIAISON), 200)
    assert dormant["status"] == "DORMANT"

    reopened = validate_success(api.reactivate_case(case["id"], {}, LIAISON), 200)
    assert reopened["status"] == "OPEN"

    third = log_contact(case["id"], "REACHED")
    assert third["status"] == "ENGAGED"

    resolved = validate_success(
        api.resolve_case(
            case["id"],
            {"resolution_summary": "Coordinated with airport on procedures."},
            LIAISON,
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None

    person = validate_success(api.get_complainant(complainant["id"], LIAISON))
    # The baseline reset shrank the trailing window below every filing.
    assert person["repeat_baseline_at"] is not None
    assert person["complaints_90d"] == 0
    assert person["standing"] == "GOOD_STANDING"


def test_manual_outreach_for_good_standing_rejected(api):
    """PRD 3.6: "A `CommunityLiaison` may also open one manually, but only for a
    complainant whose standing is currently `REPEAT` or `RESTRICTED` — opening a
    manual case for someone in `GOOD_STANDING` is rejected with
    `ERR_STANDING_NOT_ELEVATED`."

    Design: Corner/validations/manual_outreach_for_good_standing_rejected
    """
    complainant = create_complainant(full_name="Calm One", email="calm1@x.com")

    response = api.create_outreach_case(
        {"complainant_id": complainant["id"], "trigger_reason": "MANUAL"}, LIAISON
    )
    validate_error(response, ApiErrorId.ERR_STANDING_NOT_ELEVATED)


def test_outage_adjacent_interval_allowed(api):
    """PRD 3.3: "Two outages on the same monitor may touch but never overlap: an
    existing outage ending exactly when the new one begins is permitted, while
    any positive intersection of the half-open intervals is rejected with
    `ERR_OUTAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/outage_half_open_intervals_adjacency_allowed
    """
    monitor = create_monitor(station_code="MU-A")
    record_outage(
        monitor["id"],
        start_at="2026-07-10T10:00:00Z",
        end_at="2026-07-10T11:00:00Z",
        outage_type="CALIBRATION",
    )

    # Half-open [10:00, 11:00) meets [11:00, 12:00) without intersecting.
    adjacent = validate_success(
        api.create_outage(
            monitor["id"],
            {
                "start_at": "2026-07-10T11:00:00Z",
                "end_at": "2026-07-10T12:00:00Z",
                "outage_type": "MAINTENANCE",
            },
            ADMIN,
        ),
        201,
    )
    assert_monitor_outage(adjacent)

    outages, meta = validate_paginated(api.list_outages(monitor["id"], ANALYST))
    assert meta["total_count"] == 2


def test_outage_interior_overlap_rejected(api):
    """PRD 3.3: "a `start_at` and an `end_at` bounding the outage as a half-open
    interval — the start is inclusive, the end is exclusive, and the end must be
    strictly after the start".
    PRD 3.3: "any positive intersection of the half-open intervals is rejected
    with `ERR_OUTAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/outage_half_open_intervals_adjacency_allowed
    """
    monitor = create_monitor(station_code="MU-A")
    record_outage(
        monitor["id"],
        start_at="2026-07-10T10:00:00Z",
        end_at="2026-07-10T11:00:00Z",
        outage_type="CALIBRATION",
    )
    record_outage(
        monitor["id"],
        start_at="2026-07-10T11:00:00Z",
        end_at="2026-07-10T12:00:00Z",
        outage_type="MAINTENANCE",
    )

    # [10:30, 11:30) shares [10:30, 11:00) with the first outage and
    # [11:00, 11:30) with the second.
    response = api.create_outage(
        monitor["id"],
        {
            "start_at": "2026-07-10T10:30:00Z",
            "end_at": "2026-07-10T11:30:00Z",
            "outage_type": "FAULT",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_OUTAGE_OVERLAP)


def test_flight_patch_after_operated_rejected(api):
    """PRD 3.2: "All three outcomes are terminal, and recording any outcome
    against a flight that is no longer `SCHEDULED` is rejected with
    `ERR_INVALID_FLIGHT_STATE`."
    PRD 3.2: "Once written, both flags are immutable."

    Design: Corner/state_machines/flight_patch_after_operated_rejected
    """
    operator = create_operator()
    flight = create_flight(operator["id"], scheduled_at="2026-08-05T10:00:00Z")
    operated = operate_flight(flight["id"], "2026-08-05T10:05:00Z")
    assert operated["status"] == "OPERATED"
    assert operated["curfew_movement"] is False
    assert operated["curfew_violation"] is False

    response = api.patch_flight(flight["id"], {"status": "CANCELLED"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_FLIGHT_STATE)

    reread = validate_success(api.get_flight(flight["id"], ADMIN))
    assert reread["status"] == "OPERATED"
    assert_same_instant(reread["actual_at"], "2026-08-05T10:05:00Z", "actual_at")
    assert reread["curfew_movement"] is False
    assert reread["curfew_violation"] is False
