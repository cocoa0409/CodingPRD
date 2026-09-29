"""Boundary behaviour of the two overlap tests the lease-buyout pipeline runs.

A warehouse lender tests a candidate collateral pledge against the closed date periods a
stream is already pledged for, so a period that merely abuts an existing one still
collides. A refusal notice, by contrast, runs a half-open instant window, so the moment
the first window ends the tower company's clock has run out and a replacement notice
whose window starts on that same instant is served without conflict.
"""

from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    ROFR_REQUIRED_COMPANY,
    TEST_DEFAULTS,
    assert_fields,
    assert_pledge,
    assert_pledge_eligible_value,
    assert_rofr_notice,
    build_facility_with_pledge,
    deal_in_diligence,
    factories,
    read_facility,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_PLEDGE_START = "2026-08-01"
FIRST_PLEDGE_END = "2026-12-31"


def _parse_instant(text: str) -> datetime:
    """Read one of the API's UTC instants, with or without fractional digits."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _format_instant(moment: datetime) -> str:
    """Render an instant in the whole-second form the clock capability accepts."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _attempt_pledge(api, facility_id, lease_stream_id, headers, start_date, end_date):
    """Pin the facility's live version and post one candidate pledge period."""
    version = read_facility(api, facility_id)["version"]
    payload = factories.pledge_payload(
        lease_stream_id,
        version,
        pledge_start_date=start_date,
        pledge_end_date=end_date,
    )
    return api.create_pledge(facility_id, payload, headers=headers)


# ===========================================================================
# Closed pledge periods on one lease stream
# ===========================================================================


def test_pledge_starting_on_the_day_the_existing_period_ends_is_refused(api, treasury_headers):
    """A stream pledged through 2026-12-31 refuses a second pledge that starts on 2026-12-31.

    PRD 2.11: A collateral pledge period is a **closed date interval**: it includes both `pledge_start_date` and `pledge_end_date`, and adjacency is additionally forbidden.
    PRD 3.9: Because these are closed intervals with adjacency forbidden, a candidate beginning on the exact day an existing pledge ends collides with it and is refused with `ERR_PLEDGE_PERIOD_OVERLAP`, while a candidate beginning the following day is accepted.

    Design: Difficulty/resource_temporal_overlap/pledge_period_closed_interval_forbids_adjacent_start_day
    """
    scenario = build_facility_with_pledge(
        api,
        pledge={"pledge_start_date": FIRST_PLEDGE_START, "pledge_end_date": FIRST_PLEDGE_END},
    )
    first = scenario["pledge"]
    assert_pledge(first)
    assert_fields(
        first,
        {
            "lease_stream_id": scenario.lease_stream_id,
            "pledge_start_date": FIRST_PLEDGE_START,
            "pledge_end_date": FIRST_PLEDGE_END,
            "status": "PLEDGED",
        },
        "first CollateralPledge",
    )

    refused = _attempt_pledge(
        api,
        scenario.facility_id,
        scenario.lease_stream_id,
        treasury_headers,
        FIRST_PLEDGE_END,
        "2027-06-30",
    )
    validate_error(refused, ApiErrorId.ERR_PLEDGE_PERIOD_OVERLAP.value)

    unchanged = validate_success(api.get_collateral_pledge(first["id"], headers=treasury_headers))
    assert_fields(
        unchanged,
        {"pledge_end_date": FIRST_PLEDGE_END, "status": "PLEDGED"},
        "existing CollateralPledge after the refused candidate",
    )
    _, meta = validate_paginated(
        api.list_collateral_pledges(params={"lease_stream_id": scenario.lease_stream_id}, headers=treasury_headers)
    )
    assert meta["total_count"] == 1, (
        f"the refused candidate must not have been written: meta.total_count is {meta['total_count']}, expected 1"
    )


def test_pledge_starting_the_day_after_the_existing_period_ends_is_accepted(api, treasury_headers):
    """The same stream accepts a second pledge that starts on 2027-01-01, one day past the first period's end.

    PRD 2.11: A candidate pledge starting on the exact day an existing pledge ends conflicts with it; a candidate starting the following day does not.
    PRD 3.9: Because these are closed intervals with adjacency forbidden, a candidate beginning on the exact day an existing pledge ends collides with it and is refused with `ERR_PLEDGE_PERIOD_OVERLAP`, while a candidate beginning the following day is accepted.

    Design: Difficulty/resource_temporal_overlap/pledge_period_closed_interval_forbids_adjacent_start_day
    """
    scenario = build_facility_with_pledge(
        api,
        pledge={"pledge_start_date": FIRST_PLEDGE_START, "pledge_end_date": FIRST_PLEDGE_END},
    )
    model_value_cents = scenario["valuation"]["value_cents"]

    accepted = validate_success(
        _attempt_pledge(
            api,
            scenario.facility_id,
            scenario.lease_stream_id,
            treasury_headers,
            "2027-01-01",
            "2027-06-30",
        ),
        201,
    )
    assert_pledge(accepted)
    assert_fields(
        accepted,
        {
            "lease_stream_id": scenario.lease_stream_id,
            "pledge_start_date": "2027-01-01",
            "pledge_end_date": "2027-06-30",
            "status": "PLEDGED",
            "valuation_basis_snapshot": "MARK_TO_MODEL",
            "basis_value_cents": model_value_cents,
            "haircut_bps": 0,
            "eligible_value_cents": model_value_cents,
        },
        "day-after CollateralPledge",
    )
    assert_pledge_eligible_value(accepted)

    pledges, meta = validate_paginated(
        api.list_collateral_pledges(params={"lease_stream_id": scenario.lease_stream_id}, headers=treasury_headers)
    )
    assert meta["total_count"] == 2, (
        f"both non-abutting periods must stand: meta.total_count is {meta['total_count']}, expected 2"
    )
    assert [row["pledge_start_date"] for row in pledges] == [FIRST_PLEDGE_START, "2027-01-01"], (
        f"expected the two periods in creation order, got {[row['pledge_start_date'] for row in pledges]}"
    )


def test_pledge_ending_on_the_day_the_existing_period_starts_is_refused(api, treasury_headers):
    """A candidate period whose last day is the existing period's first day collides, while ending a day earlier does not.

    PRD 3.9: The period must not collide with any existing pledge of the same stream: the candidate is tested against every pledge of that stream whose `status` is `PLEDGED` or `INELIGIBLE`, with `RELEASED` pledges excluded from the test, and a collision is declared when the candidate's `pledge_start_date` falls on or before the existing pledge's `pledge_end_date` **and** the candidate's `pledge_end_date` falls on or after the existing pledge's `pledge_start_date`.
    PRD 2.11: A collateral pledge period is a **closed date interval**: it includes both `pledge_start_date` and `pledge_end_date`, and adjacency is additionally forbidden.

    Design: Difficulty/resource_temporal_overlap/pledge_period_closed_interval_forbids_adjacent_start_day
    """
    scenario = build_facility_with_pledge(
        api,
        pledge={"pledge_start_date": FIRST_PLEDGE_START, "pledge_end_date": FIRST_PLEDGE_END},
    )

    refused = _attempt_pledge(
        api,
        scenario.facility_id,
        scenario.lease_stream_id,
        treasury_headers,
        "2026-06-01",
        FIRST_PLEDGE_START,
    )
    validate_error(refused, ApiErrorId.ERR_PLEDGE_PERIOD_OVERLAP.value)

    accepted = validate_success(
        _attempt_pledge(
            api,
            scenario.facility_id,
            scenario.lease_stream_id,
            treasury_headers,
            "2026-06-01",
            "2026-07-31",
        ),
        201,
    )
    assert_fields(
        accepted,
        {"pledge_start_date": "2026-06-01", "pledge_end_date": "2026-07-31", "status": "PLEDGED"},
        "day-before CollateralPledge",
    )
    _, meta = validate_paginated(
        api.list_collateral_pledges(params={"lease_stream_id": scenario.lease_stream_id}, headers=treasury_headers)
    )
    assert meta["total_count"] == 2, (
        f"only the abutting candidate should have been refused: meta.total_count is {meta['total_count']}, expected 2"
    )


# ===========================================================================
# The half-open refusal window on one deal
# ===========================================================================


def test_second_refusal_notice_inside_the_running_window_is_refused(api, analyst_headers):
    """While the tower company's 30-day window is still running, a second notice on the deal is refused.

    PRD 2.11: A right-of-first-refusal window is a **half-open instant interval**: it includes `window_start` and excludes `window_end`.
    PRD 3.6: A second notice may not be served while an earlier notice on the same deal is still inside its window — refused with `ERR_ROFR_WINDOW_OVERLAP` — but a notice whose `window_start` falls exactly on a prior notice's `window_end` is permitted, since adjacency is not overlap.

    Design: Difficulty/resource_temporal_overlap/rofr_window_half_open_allows_adjacent_notice_after_lapse
    """
    scenario = deal_in_diligence(api, tower_company=ROFR_REQUIRED_COMPANY)
    first = validate_success(api.serve_rofr_notice(scenario.deal_id, {}, headers=analyst_headers), 201)
    assert_rofr_notice(first)
    window_start = _parse_instant(first["window_start"])
    window_end = _parse_instant(first["window_end"])
    assert first["window_days_snapshot"] == TEST_DEFAULTS["ROFR_WINDOW_DAYS"], (
        f"window_days_snapshot is {first['window_days_snapshot']}, expected the tower company's "
        f"{TEST_DEFAULTS['ROFR_WINDOW_DAYS']} days"
    )
    assert window_end == window_start + timedelta(days=first["window_days_snapshot"]), (
        f"window_end is {first['window_end']}, expected {first['window_days_snapshot']} days after "
        f"window_start {first['window_start']}"
    )
    assert first["status"] == "SERVED", f"a fresh notice opens at SERVED, got {first['status']!r}"

    refused = api.serve_rofr_notice(scenario.deal_id, {}, headers=analyst_headers)
    validate_error(refused, ApiErrorId.ERR_ROFR_WINDOW_OVERLAP.value)

    notices, meta = validate_paginated(api.list_rofr_notices(scenario.deal_id, headers=analyst_headers))
    assert meta["total_count"] == 1, (
        f"the refused notice must not have been written: meta.total_count is {meta['total_count']}, expected 1"
    )
    assert notices[0]["status"] == "SERVED", (
        f"the running notice stays SERVED inside its window, got {notices[0]['status']!r}"
    )
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(deal, {"rofr_state": "PENDING", "stage": "DILIGENCE"}, "Deal with a running refusal window")


def test_refusal_notice_at_the_last_instant_before_the_window_end_is_still_refused(api, analyst_headers):
    """One second before window_end the first notice is still inside its window, so a replacement is refused.

    PRD 2.11: A right-of-first-refusal window is a **half-open instant interval**: it includes `window_start` and excludes `window_end`.
    PRD 3.6: Only the `TowerCompanyAgent` of the notice's own tower site may respond, submitting a `decision` of either `WAIVE` or `EXERCISE`, and only while the current instant is at or after `window_start` and strictly before `window_end`.

    Design: Difficulty/resource_temporal_overlap/rofr_window_half_open_allows_adjacent_notice_after_lapse
    """
    scenario = deal_in_diligence(api, tower_company=ROFR_REQUIRED_COMPANY)
    first = validate_success(api.serve_rofr_notice(scenario.deal_id, {}, headers=analyst_headers), 201)
    window_end = _parse_instant(first["window_end"])

    set_clock(api, _format_instant(window_end - timedelta(seconds=1)))

    refused = api.serve_rofr_notice(scenario.deal_id, {}, headers=analyst_headers)
    validate_error(refused, ApiErrorId.ERR_ROFR_WINDOW_OVERLAP.value)

    still_running, meta = validate_paginated(api.list_rofr_notices(scenario.deal_id, headers=analyst_headers))
    assert meta["total_count"] == 1, (
        f"the refused notice must not have been written: meta.total_count is {meta['total_count']}, expected 1"
    )
    assert still_running[0]["status"] == "SERVED", (
        f"a notice one second short of window_end is still SERVED, got {still_running[0]['status']!r}"
    )
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(deal, {"rofr_state": "PENDING", "stage": "DILIGENCE"}, "Deal one second before window_end")


def test_replacement_refusal_notice_starting_at_the_lapsed_window_end_is_accepted(api, analyst_headers):
    """At exactly window_end the first notice has lapsed, and a replacement notice starting on that instant is served.

    PRD 2.11: Two adjacent windows are therefore permitted — a fresh notice whose `window_start` equals a prior notice's `window_end` does not overlap that prior notice.
    PRD 3.6: Silence works in our favour: once the current instant reaches `window_end` the notice goes `SERVED → EXPIRED` lazily on the next read or transition attempt, the deal's `rofr_state` becomes `WAIVED_BY_LAPSE`, and the clearance join is re-evaluated.

    Design: Difficulty/resource_temporal_overlap/rofr_window_half_open_allows_adjacent_notice_after_lapse
    """
    scenario = deal_in_diligence(api, tower_company=ROFR_REQUIRED_COMPANY)
    first = validate_success(api.serve_rofr_notice(scenario.deal_id, {}, headers=analyst_headers), 201)
    first_window_end = _parse_instant(first["window_end"])

    set_clock(api, _format_instant(first_window_end))

    second = validate_success(api.serve_rofr_notice(scenario.deal_id, {}, headers=analyst_headers), 201)
    assert_rofr_notice(second)
    assert second["window_days_snapshot"] == TEST_DEFAULTS["ROFR_WINDOW_DAYS"], (
        f"window_days_snapshot is {second['window_days_snapshot']}, expected the tower company's "
        f"{TEST_DEFAULTS['ROFR_WINDOW_DAYS']} days"
    )
    assert _parse_instant(second["window_start"]) == first_window_end, (
        f"the replacement window_start is {second['window_start']}, expected the prior window_end "
        f"{first['window_end']}"
    )
    assert _parse_instant(second["window_end"]) == first_window_end + timedelta(
        days=second["window_days_snapshot"]
    ), (
        f"the replacement window_end is {second['window_end']}, expected "
        f"{second['window_days_snapshot']} days after its window_start"
    )
    assert second["status"] == "SERVED", f"the replacement notice opens at SERVED, got {second['status']!r}"

    lapsed, meta = validate_paginated(api.list_rofr_notices(scenario.deal_id, headers=analyst_headers))
    assert meta["total_count"] == 2, (
        f"the adjacent notice must have been written: meta.total_count is {meta['total_count']}, expected 2"
    )
    by_id = {row["id"]: row for row in lapsed}
    assert by_id[first["id"]]["status"] == "EXPIRED", (
        f"the prior notice lapses at window_end, got {by_id[first['id']]['status']!r}"
    )
    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert_fields(deal, {"rofr_state": "PENDING", "stage": "DILIGENCE"}, "Deal after the adjacent notice is served")
