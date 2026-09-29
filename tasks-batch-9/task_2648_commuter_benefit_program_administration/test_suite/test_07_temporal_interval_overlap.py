"""Interval occupation on the two calendars that reject double-booking.

The commuter benefit service refuses two different kinds of double-booking, and
it refuses them under deliberately *opposite* endpoint conventions:

* an employer's **election window** occupies a HALF-OPEN interval
  ``[opens_at, cutoff_at)``, so a window that begins exactly where another one
  ends is legal and back-to-back monthly windows are the normal case; only a
  genuine straddle of the seam is refused with ``ERR_ELECTION_WINDOW_OVERLAP``;
* a commuter's **media coverage** on one ``transit_media_id`` occupies a CLOSED
  interval ``[coverage_start_at, coverage_end_at]``, so two lines whose
  endpoints merely touch DO collide and are refused with
  ``ERR_MEDIA_COVERAGE_OVERLAP``; only moving the start one second later clears.

Every test therefore pins both verdicts on the convention that actually governs
its entity: the adjacency that must be accepted, and the touching or straddling
interval that must be rejected.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import PROGRAM_ADMIN, factories as f, fixtures as fx
from test_helpers import make_order_desk_headers
from test_helpers.api_errors import (
    ERR_ELECTION_WINDOW_OVERLAP,
    ERR_MEDIA_COVERAGE_OVERLAP,
)
from test_helpers.constants import REGION_AUS, REGION_SEA

# --- Instants used by the election-calendar scenarios -------------------------
JULY_OPENS = "2026-07-01T00:00:00Z"
JULY_CUTOFF = "2026-08-01T00:00:00Z"
AUGUST_OPENS = "2026-08-01T00:00:00Z"
AUGUST_CUTOFF = "2026-09-01T00:00:00Z"
SEPTEMBER_OPENS = "2026-09-01T00:00:00Z"
SEPTEMBER_CUTOFF = "2026-10-01T00:00:00Z"
JUNE_OPENS = "2026-06-01T00:00:00Z"
JUNE_CUTOFF = "2026-07-01T00:00:00Z"

# --- Instants used by the media-coverage scenarios ----------------------------
COVER_A_START = "2026-08-01T00:00:00Z"
COVER_A_END = "2026-08-15T00:00:00Z"
COVER_TOUCHING_START = "2026-08-15T00:00:00Z"
COVER_CLEAR_START = "2026-08-15T00:00:01Z"
COVER_LATE_END = "2026-08-31T00:00:00Z"

TRANSIT_CATEGORY = {
    "category_type": "TRANSIT_PASS",
    "monthly_exclusion_limit_cents": 30000,
}

LIVE_MEDIA_STATUSES = (
    "PENDING",
    "SUBMITTED",
    "SHIPPED",
    "DELIVERED",
    "UNDELIVERED",
)


def _instant(value: str) -> datetime:
    """Parse a UTC instant so two spellings of the same moment compare equal."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _all_windows(api):
    """Every election window in the store; the database starts empty."""
    rows, meta = validate_paginated(
        api.list_election_windows(PROGRAM_ADMIN, {"limit": 100})
    )
    return rows, meta


def _orders_for_election(api, election_id):
    rows, _meta = validate_paginated(
        api.list_media_orders(
            make_order_desk_headers("desk-audit"),
            {"election_id": election_id, "limit": 100},
        )
    )
    return rows


def _austin_program_with_july_window(api):
    """An ACTIVE Austin employer whose calendar already holds July 2026.

    July occupies the half-open interval [2026-07-01, 2026-08-01).
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[dict(TRANSIT_CATEGORY)],
        legal_name="Austin Calendar Co",
        region_code=REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    july = fx.make_scheduled_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-07",
        opens_at=JULY_OPENS,
        cutoff_at=JULY_CUTOFF,
    )
    return employer, july


def _create_window(api, employer_id, benefit_month, opens_at, cutoff_at):
    return api.create_election_window(
        f.election_window_payload(
            employer_id,
            benefit_month=benefit_month,
            opens_at=opens_at,
            cutoff_at=cutoff_at,
        ),
        PROGRAM_ADMIN,
    )


def _seattle_two_windows_one_pass(api):
    """One Seattle commuter holding a live pass line in July and a fresh
    election in the adjacent August window against the SAME media product.

    Media order A already covers the closed interval
    [2026-08-01, 2026-08-15] against the July election, so any further line for
    the same commuter and the same product is judged against that closed span.
    The August election is a different (employee, window, category) triple, so
    nothing about it supersedes the July line.
    """
    fx.set_clock(api, "2026-07-15T00:00:00Z")
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[dict(TRANSIT_CATEGORY)],
        legal_name="Seattle Pass Coverage Co",
        region_code=REGION_SEA,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    media = fx.make_transit_media(
        api,
        "desk-catalog",
        sku="SEA-COVER",
        media_type="SMART_CARD_LOAD",
        region_code=REGION_SEA,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=4000,
        replacement_fee_cents=500,
        requires_physical_fulfillment=True,
    )
    enrolled = fx.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        external_ref="SEA-COV-1",
        work_region_code=REGION_SEA,
        hire_date="2026-02-01T00:00:00Z",
    )
    employee = enrolled["employee"]
    account = enrolled["account"]

    july = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-07",
        opens_at=JULY_OPENS,
        cutoff_at=JULY_CUTOFF,
    )
    july_election = fx.make_election(
        api,
        employee["id"],
        july["id"],
        category["id"],
        account["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=4000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=1,
    )
    july_batch = fx.make_open_batch(api, july["id"], REGION_SEA, "desk-sealer")
    order_a = fx.make_media_order(
        api,
        july_election["id"],
        media["id"],
        july_batch["id"],
        "desk-sealer",
        quantity=1,
        coverage_start_at=COVER_A_START,
        coverage_end_at=COVER_A_END,
    )

    fx.set_clock(api, "2026-08-05T00:00:00Z")
    august = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at=AUGUST_OPENS,
        cutoff_at=AUGUST_CUTOFF,
    )
    august_election = fx.make_election(
        api,
        employee["id"],
        august["id"],
        category["id"],
        account["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=4000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=1,
    )
    august_batch = fx.make_open_batch(api, august["id"], REGION_SEA, "desk-sealer")
    return {
        "employer": employer,
        "category": category,
        "employee": employee,
        "account": account,
        "media": media,
        "july_window": july,
        "july_election": july_election,
        "july_batch": july_batch,
        "order_a": order_a,
        "august_window": august,
        "august_election": august_election,
        "august_batch": august_batch,
    }


def _add_coverage_line(api, setup, coverage_start_at, coverage_end_at):
    """Attempt one further media line for the August election and product."""
    election_id = setup["august_election"]["id"]
    version = fx.current_election_version(api, election_id)
    return api.create_media_order(
        f.media_order_payload(
            election_id,
            setup["media"]["id"],
            setup["august_batch"]["id"],
            version,
            quantity=1,
            coverage_start_at=coverage_start_at,
            coverage_end_at=coverage_end_at,
        ),
        make_order_desk_headers("desk-sealer"),
    )


# =============================================================================
# The election calendar: half-open occupation, adjacency legal
# =============================================================================
def test_01_back_to_back_election_windows_abutting_the_prior_cutoff_are_accepted(api):
    """PRD §3.2: "A window's occupation interval runs from `opens_at` inclusive up to `cutoff_at` exclusive, and a new window is refused if that half-open interval intersects the half-open interval of any existing window of the same employer whose `status` is `SCHEDULED`, `OPEN` or `LOCKED`."
    PRD §3.2: "Because both endpoints are treated half-open, adjacency is entirely legal: a window whose `opens_at` is exactly equal to another window's `cutoff_at` does not conflict, and back-to-back monthly windows are the normal case."

    Design: Difficulty/resource_temporal_overlap/election_window_half_open_intervals_allow_adjacency_reject_straddle
    """
    employer, july = _austin_program_with_july_window(api)
    assert july["status"] == "SCHEDULED", (
        f"a freshly created window opens SCHEDULED, got {july['status']}"
    )

    august = validate_success(
        _create_window(api, employer["id"], "2026-08", AUGUST_OPENS, AUGUST_CUTOFF),
        expected_status=201,
    )
    assert _instant(august["opens_at"]) == _instant(july["cutoff_at"]), (
        "the August window must open at exactly the July cutoff instant"
    )
    assert august["status"] == "SCHEDULED"

    september = validate_success(
        _create_window(
            api, employer["id"], "2026-09", SEPTEMBER_OPENS, SEPTEMBER_CUTOFF
        ),
        expected_status=201,
    )
    assert _instant(september["opens_at"]) == _instant(august["cutoff_at"]), (
        "the September window must open at exactly the August cutoff instant"
    )

    rows, meta = _all_windows(api)
    assert meta["total_count"] == 3, (
        "three back-to-back monthly windows must all survive on the calendar, "
        f"found {meta['total_count']}"
    )
    assert {row["benefit_month"] for row in rows} == {"2026-07", "2026-08", "2026-09"}


def test_02_election_window_straddling_the_prior_cutoff_seam_is_rejected(api):
    """PRD §3.2: "Concretely, the two intervals conflict when the new window's `opens_at` falls strictly before the existing window's `cutoff_at` **and** the new window's `cutoff_at` falls strictly after the existing window's `opens_at`."
    PRD §3.2: "A conflict is rejected with `ERR_ELECTION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/election_window_half_open_intervals_allow_adjacency_reject_straddle
    """
    employer, july = _austin_program_with_july_window(api)

    # 2026-07-15 is strictly before July's cutoff 2026-08-01, and 2026-08-15 is
    # strictly after July's opens_at 2026-07-01: both legs of the conflict test
    # are satisfied, so the calendar slot is genuinely double-booked.
    validate_error(
        _create_window(
            api,
            employer["id"],
            "2026-09",
            "2026-07-15T00:00:00Z",
            "2026-08-15T00:00:00Z",
        ),
        ERR_ELECTION_WINDOW_OVERLAP,
    )

    rows, meta = _all_windows(api)
    assert meta["total_count"] == 1, (
        "the straddling window must not have been persisted, "
        f"found {meta['total_count']} windows"
    )
    assert rows[0]["id"] == july["id"]


def test_03_election_window_ending_exactly_at_the_prior_opens_at_is_accepted(api):
    """PRD §3.2: "Concretely, the two intervals conflict when the new window's `opens_at` falls strictly before the existing window's `cutoff_at` **and** the new window's `cutoff_at` falls strictly after the existing window's `opens_at`."
    PRD §3.2: "Because both endpoints are treated half-open, adjacency is entirely legal: a window whose `opens_at` is exactly equal to another window's `cutoff_at` does not conflict, and back-to-back monthly windows are the normal case."

    Design: Difficulty/resource_temporal_overlap/election_window_half_open_intervals_allow_adjacency_reject_straddle
    """
    employer, july = _austin_program_with_july_window(api)

    # The June window's cutoff_at equals July's opens_at exactly, so it is not
    # "strictly after" it and the second leg of the conflict test fails.
    june = validate_success(
        _create_window(api, employer["id"], "2026-06", JUNE_OPENS, JUNE_CUTOFF),
        expected_status=201,
    )
    assert _instant(june["cutoff_at"]) == _instant(july["opens_at"]), (
        "the June window must close at exactly the July opening instant"
    )
    assert june["status"] == "SCHEDULED"

    # One second of genuine intersection with July is enough to be refused.
    validate_error(
        _create_window(
            api,
            employer["id"],
            "2026-06",
            "2026-06-15T00:00:00Z",
            "2026-07-15T00:00:00Z",
        ),
        ERR_ELECTION_WINDOW_OVERLAP,
    )

    _rows, meta = _all_windows(api)
    assert meta["total_count"] == 2, (
        "only the adjacent June window may join July on the calendar, "
        f"found {meta['total_count']}"
    )


# =============================================================================
# The commuter's pass coverage: closed occupation, touching endpoints collide
# =============================================================================
def test_04_media_coverage_line_touching_the_prior_end_instant_is_rejected(api):
    """PRD §3.5: "Coverage intervals are treated as **closed** on both ends, and unlike the election calendar, adjacency is a conflict here rather than a courtesy."
    PRD §3.5: "Concretely, the two intervals conflict when the new line's `coverage_start_at` falls at or before the existing line's `coverage_end_at` **and** the new line's `coverage_end_at` falls at or after the existing line's `coverage_start_at`, so two intervals whose endpoints merely touch do collide."
    PRD §3.5: "The rejection is `ERR_MEDIA_COVERAGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/media_coverage_closed_intervals_reject_touching_endpoints
    """
    setup = _seattle_two_windows_one_pass(api)
    assert _instant(setup["order_a"]["coverage_end_at"]) == _instant(COVER_A_END)

    # 2026-08-15T00:00:00Z is exactly order A's coverage_end_at, so the new
    # line's start falls "at or before" it and the closed intervals collide.
    validate_error(
        _add_coverage_line(api, setup, COVER_TOUCHING_START, COVER_LATE_END),
        ERR_MEDIA_COVERAGE_OVERLAP,
    )

    august_lines = _orders_for_election(api, setup["august_election"]["id"])
    assert august_lines == [], (
        "the touching line must not have been persisted, "
        f"found {len(august_lines)} rows on the August election"
    )
    order_a = fx.read_media_order(api, setup["order_a"]["id"])
    assert order_a["status"] == "PENDING", (
        f"the refused create must not touch order A, status {order_a['status']}"
    )
    assert order_a["superseded_media_order_id"] is None


def test_05_media_coverage_line_starting_one_second_after_the_prior_end_is_accepted(api):
    """PRD §3.5: "Concretely, the two intervals conflict when the new line's `coverage_start_at` falls at or before the existing line's `coverage_end_at` **and** the new line's `coverage_end_at` falls at or after the existing line's `coverage_start_at`, so two intervals whose endpoints merely touch do collide."
    PRD §3.5: "A new media line is refused if its interval from `coverage_start_at` through `coverage_end_at` inclusive intersects the closed coverage interval of any existing media order for the same combination of electing employee and `transit_media_id` whose `status` is anything other than `CANCELLED`."

    Design: Difficulty/resource_temporal_overlap/media_coverage_closed_intervals_reject_touching_endpoints
    """
    setup = _seattle_two_windows_one_pass(api)

    validate_error(
        _add_coverage_line(api, setup, COVER_TOUCHING_START, COVER_LATE_END),
        ERR_MEDIA_COVERAGE_OVERLAP,
    )

    # Moving the start a single second past order A's closed end clears it.
    order_b = validate_success(
        _add_coverage_line(api, setup, COVER_CLEAR_START, COVER_LATE_END),
        expected_status=201,
    )
    assert _instant(order_b["coverage_start_at"]) == _instant(COVER_CLEAR_START)
    assert order_b["status"] == "PENDING", (
        f"a fresh media line opens PENDING, got {order_b['status']}"
    )
    assert order_b["superseded_media_order_id"] is None, (
        "the August line belongs to a different election, so it supersedes nothing"
    )

    order_a = fx.read_media_order(api, setup["order_a"]["id"])
    assert order_a["status"] == "PENDING", (
        f"the July line keeps its coverage, status {order_a['status']}"
    )
    assert order_a["superseded_media_order_id"] is None

    july_batch = fx.read_batch(api, setup["july_batch"]["id"])
    august_batch = fx.read_batch(api, setup["august_batch"]["id"])
    assert july_batch["line_count"] == 1, (
        f"the July batch holds exactly its one line, got {july_batch['line_count']}"
    )
    assert august_batch["line_count"] == 1, (
        "the August batch holds only the accepted line, "
        f"got {august_batch['line_count']}"
    )
    assert sum(
        row["quantity"]
        for row in _orders_for_election(api, setup["august_election"]["id"])
        if row["status"] in LIVE_MEDIA_STATUSES
    ) == 1


def test_06_media_coverage_line_ending_exactly_at_the_prior_start_instant_is_rejected(api):
    """PRD §3.5: "Concretely, the two intervals conflict when the new line's `coverage_start_at` falls at or before the existing line's `coverage_end_at` **and** the new line's `coverage_end_at` falls at or after the existing line's `coverage_start_at`, so two intervals whose endpoints merely touch do collide."
    PRD §3.5: "The rejection is `ERR_MEDIA_COVERAGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/media_coverage_closed_intervals_reject_touching_endpoints
    """
    setup = _seattle_two_windows_one_pass(api)

    # The new line ends exactly on order A's coverage_start_at, which is still
    # "at or after" it, so the closed intervals touch and therefore collide.
    validate_error(
        _add_coverage_line(
            api, setup, "2026-07-20T00:00:00Z", "2026-08-01T00:00:00Z"
        ),
        ERR_MEDIA_COVERAGE_OVERLAP,
    )
    assert _orders_for_election(api, setup["august_election"]["id"]) == []

    # One second earlier the new end falls strictly before order A's start, so
    # the two closed intervals no longer share an instant.
    order_b = validate_success(
        _add_coverage_line(
            api, setup, "2026-07-20T00:00:00Z", "2026-07-31T23:59:59Z"
        ),
        expected_status=201,
    )
    assert order_b["status"] == "PENDING"
    assert _instant(order_b["coverage_end_at"]) < _instant(COVER_A_START)
    assert order_b["superseded_media_order_id"] is None
