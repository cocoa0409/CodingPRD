"""Two scarce resources whose interval rules land on opposite boundary verdicts.

A branch window is half-open and carries no buffer, so a new window starting at the
exact instant an old one ends is fine.  A data-room reservation is closed and carries
a mandatory hour, so a gap of exactly sixty minutes is refused and it takes
sixty-one to book.  The same implementation cannot serve both.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BRANCH_WINDOW_OVERLAP,
    ERR_DATA_ROOM_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_instant,
    created,
    total_count,
)
from test_helpers.test_users import (
    CLOSING_MANAGER,
    RESOLUTION_ANALYST,
    make_bidder_headers,
)

FIRST_WINDOW_START = "2026-08-10T09:00:00Z"
FIRST_WINDOW_END = "2026-08-10T17:00:00Z"
ADJACENT_WINDOW_START = "2026-08-10T17:00:00Z"
ADJACENT_WINDOW_END = "2026-08-11T01:00:00Z"
STRADDLING_WINDOW_START = "2026-08-10T16:00:00Z"
STRADDLING_WINDOW_END = "2026-08-10T18:00:00Z"


def _branch_network_estate(client):
    """A closed, deposit-free institution with no branch plans filed yet."""
    X.open_at_setup_clock(client)
    return X.deposit_free_closed_institution(
        client, cert_number="34580", legal_name="Yakima Branch Network Bank"
    )


def _plan_branch(client, institution_id, branch_code, start, end, headcount):
    return client.create_branch_reopening(
        institution_id,
        F.branch_reopening_payload(
            branch_code=branch_code,
            reopen_window_start=start,
            reopen_window_end=end,
            staffing_headcount=headcount,
        ),
        CLOSING_MANAGER,
    )


def _branch_count(client, institution_id, branch_code=None):
    params = {"branch_code": branch_code} if branch_code else None
    return total_count(
        client.list_branch_reopenings(institution_id, CLOSING_MANAGER, params=params)
    )


def test_a_branch_window_starting_when_another_ends_is_accepted(client):
    """Because branch windows are half-open and carry no buffer, a second window on the
    same branch may begin at the exact instant the first one ends.

    PRD: "Windows are **half-open** — the start instant belongs to the window and the end instant does not — and unlike data-room reservations they carry **no** buffer. ... A new window beginning at exactly the instant an existing one ends is therefore allowed."

    Design: Difficulty/resource_temporal_overlap/branch_window_half_open_adjacency_allowed_overlap_conflict
    """
    institution = _branch_network_estate(client)
    institution_id = institution["id"]

    first = created(
        _plan_branch(client, institution_id, "BR-01", FIRST_WINDOW_START, FIRST_WINDOW_END, 10)
    )
    assert_fields_equal(
        first, {"status": "PLANNED", "branch_code": "BR-01", "reschedule_count": 0}
    )
    assert first["reopened_at"] is None

    adjacent = created(
        _plan_branch(
            client, institution_id, "BR-01", ADJACENT_WINDOW_START, ADJACENT_WINDOW_END, 6
        )
    )
    assert_fields_equal(adjacent, {"status": "PLANNED", "branch_code": "BR-01"})
    assert_instant(adjacent["reopen_window_start"], FIRST_WINDOW_END)

    assert _branch_count(client, institution_id, "BR-01") == 2


def test_a_straddling_branch_window_is_refused_but_another_branch_may_reuse_it(client):
    """A window that starts before one plan ends and ends after another starts is
    refused, while the very same interval on a different branch code is accepted,
    because the resource is the branch and not the institution.

    PRD: "A new or rescheduled window on the same institution and the same `branch_code` is rejected with `ERR_BRANCH_WINDOW_OVERLAP` when the new start falls strictly before an existing window's end **and** that existing window's start falls strictly before the new end, considering only existing reopenings at `PLANNED` or `READY`."

    Design: Difficulty/resource_temporal_overlap/branch_window_half_open_adjacency_allowed_overlap_conflict
    """
    institution = _branch_network_estate(client)
    institution_id = institution["id"]
    created(
        _plan_branch(client, institution_id, "BR-01", FIRST_WINDOW_START, FIRST_WINDOW_END, 10)
    )
    created(
        _plan_branch(
            client, institution_id, "BR-01", ADJACENT_WINDOW_START, ADJACENT_WINDOW_END, 6
        )
    )

    validate_error(
        _plan_branch(
            client,
            institution_id,
            "BR-01",
            STRADDLING_WINDOW_START,
            STRADDLING_WINDOW_END,
            4,
        ),
        ERR_BRANCH_WINDOW_OVERLAP,
        409,
    )
    assert _branch_count(client, institution_id, "BR-01") == 2

    other_branch = created(
        _plan_branch(client, institution_id, "BR-02", FIRST_WINDOW_START, FIRST_WINDOW_END, 10)
    )
    assert_fields_equal(other_branch, {"status": "PLANNED", "branch_code": "BR-02"})
    assert _branch_count(client, institution_id) == 3


# ---------------------------------------------------------------------------
# The data room: closed intervals with a mandatory sixty-minute separation
# ---------------------------------------------------------------------------
RESERVED_WINDOW_START = "2026-09-01T09:00:00Z"
RESERVED_WINDOW_END = "2026-09-01T12:00:00Z"
SIXTY_MINUTES_LATER = "2026-09-01T13:00:00Z"
SIXTY_ONE_MINUTES_LATER = "2026-09-01T13:01:00Z"
SECOND_WINDOW_END = "2026-09-01T15:00:00Z"


def _data_room_estate(client):
    """A marketed estate with two qualified bidders and a completely free data room."""
    X.open_at_setup_clock(client)
    institution = X.marketed_institution(
        client, cert_number="34581", legal_name="Wenatchee Data Room Bank"
    )
    first_bidder = X.new_qualified_bidder(
        client,
        legal_name="Wenatchee Federal Savings",
        cert_number="55001",
        tier1_capital_ratio_bps=1500,
        camels_composite=2,
    )
    second_bidder = X.new_qualified_bidder(
        client,
        legal_name="Kitsap Commerce Bank",
        cert_number="55002",
        tier1_capital_ratio_bps=1450,
        camels_composite=2,
    )
    return {
        "institution": institution,
        "first_bidder": first_bidder,
        "second_bidder": second_bidder,
    }


def _submit_bid(client, institution_id, bidder_id, premium_bps, start, end):
    return client.create_bid(
        F.bid_payload(
            institution_id,
            bidder_id,
            structure="WHOLE_BANK_PA",
            deposit_premium_bps=premium_bps,
            asset_discount_bps=1000,
            data_room_window_start=start,
            data_room_window_end=end,
        ),
        make_bidder_headers(bidder_id),
    )


def _bid_count(client, institution_id):
    return total_count(
        client.list_bids(RESOLUTION_ANALYST, params={"institution_id": institution_id})
    )


def test_a_sixty_minute_gap_in_the_data_room_is_refused_across_bidders(client):
    """A second bidder claiming the data room exactly sixty minutes after the first
    reservation ends is refused, because the buffer must separate the reservations and
    the room is shared by every bidder on the estate.

    PRD: "a new bid is rejected when its start instant is at or before an existing reservation's end plus 60 minutes **and** that existing reservation's start is at or before the new bid's end plus 60 minutes"

    Design: Difficulty/resource_temporal_overlap/data_room_closed_interval_requires_more_than_sixty_minute_buffer
    """
    world = _data_room_estate(client)
    institution_id = world["institution"]["id"]

    first = created(
        _submit_bid(
            client,
            institution_id,
            world["first_bidder"]["id"],
            300,
            RESERVED_WINDOW_START,
            RESERVED_WINDOW_END,
        )
    )
    assert first["status"] == "SUBMITTED"
    assert_instant(first["data_room_window_start"], RESERVED_WINDOW_START)
    assert_instant(first["data_room_window_end"], RESERVED_WINDOW_END)

    validate_error(
        _submit_bid(
            client,
            institution_id,
            world["second_bidder"]["id"],
            320,
            SIXTY_MINUTES_LATER,
            SECOND_WINDOW_END,
        ),
        ERR_DATA_ROOM_WINDOW_CONFLICT,
        409,
    )
    assert _bid_count(client, institution_id) == 1


def test_a_sixty_one_minute_gap_clears_the_data_room_buffer(client):
    """One minute more than the mandatory hour separates the reservations, so the second
    bidder's submission is accepted and both reservations stand.

    PRD: "A reservation is a **closed** interval — both endpoints belong to it — and a mandatory buffer of 60 minutes must separate a new reservation from every live reservation across **all** bidders on the same institution."

    Design: Difficulty/resource_temporal_overlap/data_room_closed_interval_requires_more_than_sixty_minute_buffer
    """
    world = _data_room_estate(client)
    institution_id = world["institution"]["id"]
    created(
        _submit_bid(
            client,
            institution_id,
            world["first_bidder"]["id"],
            300,
            RESERVED_WINDOW_START,
            RESERVED_WINDOW_END,
        )
    )

    second = created(
        _submit_bid(
            client,
            institution_id,
            world["second_bidder"]["id"],
            320,
            SIXTY_ONE_MINUTES_LATER,
            SECOND_WINDOW_END,
        )
    )
    assert second["status"] == "SUBMITTED"
    assert_instant(second["data_room_window_start"], SIXTY_ONE_MINUTES_LATER)
    assert _bid_count(client, institution_id) == 2
