"""The consistency model: every derived field is already final in the response
of the write that caused it, and the very next read agrees with it.

Every test in this module translates exactly one instance of
SCAFFOLD_CORNER_DESIGN.yaml section `consistency_model`.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    STUDIO_EXECUTIVE_HEADERS,
    make_writer_headers,
)

# --- Module landmarks --------------------------------------------------------

# The STAFFING room before any acceptance: no confirmed seat, so the burn is the
# TIER_1 facility fee at the IN_PERSON surcharge of 1.0 and nothing else.
COMMITMENT_BEFORE_ACCEPTANCE = K.ROOM_BURN_EMPTY_IN_PERSON
# ... and after the 600,000 seat confirms.
COMMITMENT_AFTER_ACCEPTANCE = K.ROOM_BURN_ONE_SEAT_600000
SEAT_WEEKLY_CENTS = 600000

# STORY_EDITOR carries a 0.5 guarantee offset fraction on a one-hour episode.
TELEPLAY_OFFSET_ONE_HOUR = 1750000
TELEPLAY_PAYABLE_ONE_HOUR = 1750000
# The accrual and its offset, and their signed sum.
LEDGER_ROWS_AFTER_CREATE = 2
COMMITTED_SCRIPT_FEE = 1750000

# ready_script_target 1 with no READY episode yet.
COVERAGE_GAP_AT_RISK = 1

ENVELOPE_META_KEYS = {"api_request_id", "api_request_timestamp"}
PAGINATION_META_KEYS = {"limit", "offset", "total_count", "has_more"}
DEFAULT_PAGE_LIMIT = 10


# --- Local helpers -----------------------------------------------------------

def _object_body(response, expected_status=200):
    """Validate one single-resource response and its envelope, and return data."""
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource is an object envelope, got {body['response_type']!r}"
    )
    assert set(body["meta"]) == ENVELOPE_META_KEYS, (
        f"pagination keys belong to list endpoints only: {sorted(body['meta'])}"
    )
    return data


def _array_body(response):
    """Validate one list response and its envelope, and return (rows, meta)."""
    rows, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == "array", (
        f"a list is an array envelope, got {body['response_type']!r}"
    )
    assert PAGINATION_META_KEYS <= set(body["meta"]), (
        f"a list endpoint echoes every pagination key: {sorted(body['meta'])}"
    )
    return rows, meta


def test_the_write_that_causes_a_derived_field_already_returns_its_final_value(api):
    """The acceptance response itself carries the seat's final compensation and
    prorated commitment, and the room, season, writer and window reads taken
    immediately afterwards return exactly the figures that response implied -
    there is no window in which the seat is CONFIRMED while the season
    commitment still reads its pre-acceptance value. The same holds for the
    assignment create and the ledger it writes.

    PRD: "**derived state is always recomputed, never patched**: seat compensation, room weekly burn, season staffing commitment, script coverage posture, clearance risk and credit shares are all functions of their inputs, re-evaluated whenever an input moves"

    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    PRD: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

    PRD: "Acceptance moves the seat `OFFERED → CONFIRMED` and stamps `confirmed_at` from the logical clock."

    PRD: "The winning window moves to `CONSUMED` and records the seat in its `consumed_by_seat_id`, while the seat records the window in its `consumed_window_id`"

    PRD: "The room's `confirmed_seat_count` increases by one, and when the seat is `diversity_program_funded` its `confirmed_diversity_seat_count` also increases by one. Because a confirmed seat now contributes to the subtotal, the room's `seat_subtotal_weekly_cents`, `facility_tier`, `facility_surcharge_weekly_cents` and `weekly_burn_cents` are recomputed, and the season's `staffing_commitment_weekly_cents` follows."

    PRD: "Round the weekly compensation divided by 7 to whole cents **first** to obtain a daily rate, then multiply that rounded daily rate by the residual days, and add the product of the full weeks and the full weekly compensation."

    PRD: "**Season staffing commitment** is the sum of `weekly_burn_cents` over the season's rooms whose status is `STAFFING` or `ACTIVE`"

    PRD: "Creating an assignment therefore appends a `SCRIPT_FEE_ACCRUAL` entry for the full gross and, when a slot applied at creation, a `GUARANTEE_OFFSET` entry for the negative offset. The season's `script_fee_committed_cents` is then recomputed as the signed sum of every ledger entry of that season — it is never incremented in place."

    PRD: "From that count, `coverage_gap` is the season's `ready_script_target` minus `ready_script_count`, floored at 0, so the gap never goes negative when a season over-delivers."

    Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_response_that_caused_it
    """
    world = X.build_staffing_room_world(api)
    room_id = world["room_id"]
    season_id = world["season_id"]
    writer_id = world["w1_id"]

    seat = X.seed_seat(
        api,
        room_id,
        writer_id,
        world["sr_headers"],
        expected_room_version=world["room_version"],
        episodic_guarantee_count=1,
    )
    A.assert_field_values(seat, status="OFFERED", consumed_window_id=None)

    # A merely OFFERED seat contributes nothing, so the commitment is still the
    # empty room's facility surcharge.
    A.assert_field_values(
        X.read_season(api, season_id),
        staffing_commitment_weekly_cents=COMMITMENT_BEFORE_ACCEPTANCE,
    )

    # THE CAUSING WRITE. Its own body is the whole answer.
    accepted = _object_body(
        api.accept_seat(seat["id"], make_writer_headers(writer_id))
    )
    A.assert_common_fields(accepted)
    A.assert_field_values(
        accepted,
        id=seat["id"],
        status="CONFIRMED",
        consumed_window_id=world["aw1_id"],
        guarantee_slots_consumed=0,
        guarantee_slots_remaining=1,
    )
    A.assert_instant(accepted["confirmed_at"], K.CLOCK_EPOCH, "confirmed_at")
    A.assert_seat_pricing(
        accepted,
        SEAT_WEEKLY_CENTS,
        SEAT_WEEKLY_CENTS,
        0,
        SEAT_WEEKLY_CENTS,
        K.SEAT_PRORATED_181_DAYS_AT_600000,
    )

    # THE VERY NEXT READS. Each is a single-resource envelope, and each already
    # agrees with the write above.
    room = _object_body(api.get_room(room_id, STUDIO_EXECUTIVE_HEADERS))
    A.assert_field_values(room, status="STAFFING", confirmed_seat_count=1)
    A.assert_room_burn(
        room,
        SEAT_WEEKLY_CENTS,
        K.FACILITY_TIER_1,
        K.ROOM_BURN_EMPTY_IN_PERSON,
        COMMITMENT_AFTER_ACCEPTANCE,
    )
    A.assert_seat_capacity_conserved(room)

    season = _object_body(api.get_season(season_id, STUDIO_EXECUTIVE_HEADERS))
    A.assert_field_values(
        season, staffing_commitment_weekly_cents=COMMITMENT_AFTER_ACCEPTANCE
    )

    writer = _object_body(api.get_writer(writer_id, STUDIO_EXECUTIVE_HEADERS))
    A.assert_field_values(writer, active_seat_count=1)

    window = _object_body(
        api.get_availability_window(world["aw1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(
        window, status="CONSUMED", consumed_by_seat_id=seat["id"]
    )

    # The same immediacy on the money side of the system.
    X.activate_room(api, room_id)
    episode = X.seed_episode(api, season_id, 1)
    created = _object_body(
        api.create_script_assignment(
            episode["id"],
            F.build_script_assignment(
                writer_id, episode["version"], assignment_type="TELEPLAY"
            ),
            world["sr_headers"],
        ),
        201,
    )
    A.assert_field_values(created, status="DRAFTING", room_seat_id=seat["id"])
    A.assert_assignment_settlement(
        created,
        K.SCRIPT_FEE_ONE_HOUR["TELEPLAY"],
        True,
        TELEPLAY_OFFSET_ONE_HOUR,
        TELEPLAY_PAYABLE_ONE_HOUR,
    )

    # The list read is the array envelope, and both rows are already there.
    rows, meta = _array_body(
        api.list_fee_ledger_entries(
            STUDIO_EXECUTIVE_HEADERS, {"season_id": season_id}
        )
    )
    A.assert_pagination_meta(
        meta, LEDGER_ROWS_AFTER_CREATE, False, DEFAULT_PAGE_LIMIT, 0
    )
    assert A.entry_types(rows) == ["SCRIPT_FEE_ACCRUAL", "GUARANTEE_OFFSET"], (
        f"the create appends the accrual then its offset, got {A.entry_types(rows)}"
    )
    A.assert_ledger_sum(rows, COMMITTED_SCRIPT_FEE)
    for entry in rows:
        A.assert_ledger_common_fields(entry)
        A.assert_field_values(
            entry,
            season_id=season_id,
            assignment_id=created["id"],
            writer_id=writer_id,
        )

    # The season's own committed total is the signed sum of those rows, and its
    # coverage figures are equally current.
    settled_season = _object_body(api.get_season(season_id, STUDIO_EXECUTIVE_HEADERS))
    A.assert_field_values(
        settled_season,
        script_fee_committed_cents=COMMITTED_SCRIPT_FEE,
        ready_script_count=0,
        coverage_gap=COVERAGE_GAP_AT_RISK,
        coverage_posture="AT_RISK",
    )
