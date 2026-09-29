"""Two exclusive resources booked over time, under opposite interval semantics.

An element's outage window is a *closed* interval widened by a 24-hour quiet
buffer on both ends, so windows that merely touch the buffer edge collide; a
meeting's hearing docket is a *half-open* thirty-minute slot with no buffer at
all, so back-to-back slots that touch are admitted.  The same touching geometry
therefore gets opposite verdicts, and both resources are also probed for the
scope of their exclusivity.
"""

from __future__ import annotations

from typing import Any

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant_equals,
    read_case, read_contract, read_meeting,
)
from test_helpers.factories import work_order_payload
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    add_work_order,
    award_and_activate_contract,
    build_board,
    convene,
    create_association,
    docket_hearing,
    notice_meeting,
    notice_violation_case,
    patch_association,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS

INCUMBENT_START = "2026-10-05T08:00:00Z"
INCUMBENT_END = "2026-10-07T18:00:00Z"
# The 24-hour default buffer widens the incumbent window to this closed band.
BAND_START = "2026-10-04T08:00:00Z"
BAND_END = "2026-10-08T18:00:00Z"


# ======================================================================
# Resource 1: a common element's outage window (closed + 24h buffer)
# ======================================================================
def _cedarcrest(api: ApiClient):
    """Two roofs, each under its own active contract, one of them already booked.

    Both contracts run 2026-09-01 to 2027-06-01 with a 20000000 cap, so neither
    the contract-term gate nor the cap gate can be the reason for any refusal
    below.
    """
    ctx = create_association(api, legal_name="Cedarcrest Condominium Association")
    build_board(ctx)
    add_element(
        ctx,
        "el1",
        name="North Roof Membrane",
        element_class="ROOF",
        replacement_cost_cents=9_000_000,
        useful_life_years=30,
        effective_age_years=10,
    )
    add_element(
        ctx,
        "el2",
        name="South Roof Membrane",
        element_class="ROOF",
        replacement_cost_cents=7_000_000,
        useful_life_years=30,
        effective_age_years=8,
    )
    for label, element_label, vendor in (
        ("ct1", "el1", "Meridian Roofing LLC"),
        ("ct2", "el2", "Harbor Sheet Metal Co"),
    ):
        add_contract(
            ctx,
            label,
            element_label,
            vendor_name=vendor,
            contract_cap_cents=20_000_000,
            insurance_cert_expires_at="2027-06-01T00:00:00Z",
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
        )
    schedule_meeting(
        ctx,
        "mtg_ca",
        ["CONTRACT_AWARD"],
        "2026-09-10T18:00:00Z",
        "2026-09-10T21:00:00Z",
    )
    notice_meeting(ctx, "mtg_ca")
    set_clock(api, "2026-09-10T18:00:00Z")
    convene(ctx, "mtg_ca", ("d1", "d2", "tr"))
    award_and_activate_contract(ctx, "ct1", "mtg_ca")
    award_and_activate_contract(ctx, "ct2", "mtg_ca")
    incumbent = add_work_order(
        ctx,
        "ct1",
        "el1",
        scope="Incumbent seam repair",
        window_start=INCUMBENT_START,
        window_end=INCUMBENT_END,
        estimated_cost_cents=1_000_000,
    )
    return ctx, incumbent


def _post_order(ctx, contract_label: str, element_label: str, **overrides: Any):
    """Attempt a work order, re-reading the contract version each time.

    A refused creation consumes no version, so the same figure stays valid --
    reading it fresh keeps every attempt independent of the ones before it.
    """
    payload = work_order_payload(
        ctx.contracts[contract_label],
        ctx.elements[element_label],
        ctx.contract_version(contract_label),
        **overrides,
    )
    return ctx.api.create_work_order(payload, MANAGER_HEADERS)


def test_incumbent_outage_window_holds_the_element_with_its_cap_untouched(
    api: ApiClient,
) -> None:
    """The booked order encumbers its estimate against a cap with ample headroom.

    PRD 3.6: "On success `encumbered_cents` is set to `estimated_cost_cents`,
    the contract's `committed_cents` rises by the same amount, and
    `VendorContract.version` advances by 1."

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, incumbent = _cedarcrest(api)

    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["encumbered_cents"] == 1_000_000
    assert_instant_equals(incumbent["window_start"], INCUMBENT_START)
    assert_instant_equals(incumbent["window_end"], INCUMBENT_END)
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["committed_cents"] == 1_000_000
    assert contract["invoiced_cents"] == 0
    assert contract["contract_cap_cents"] == 20_000_000
    assert ctx.association()["element_window_buffer_hours"] == 24


def test_window_starting_exactly_on_the_upper_buffer_edge_collides(
    api: ApiClient,
) -> None:
    """window_start at existing window_end plus 24 hours is *at or before*, so it collides.

    PRD 3.6: "Concretely, the new order is rejected when its `window_start` is at
    or before an existing order's `window_end` advanced forward by the buffer
    **and** its `window_end` is at or after that existing order's `window_start`
    pushed back by the buffer."

    The incumbent runs 2026-10-05T08:00:00Z to 2026-10-07T18:00:00Z, so the
    buffered band closes at 2026-10-08T18:00:00Z -- exactly the requested start.

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, _ = _cedarcrest(api)

    validate_error(
        _post_order(
            ctx,
            "ct1",
            "el1",
            scope="Touches the upper buffer edge exactly",
            window_start=BAND_END,
            window_end="2026-10-09T12:00:00Z",
            estimated_cost_cents=400_000,
        ),
        "ERR_ELEMENT_WINDOW_CONFLICT",
        expected_status=409,
    )


def test_buffer_edge_refusal_is_neither_the_contract_term_nor_the_cap_gate(
    api: ApiClient,
) -> None:
    """The refused window sits inside the term and inside the cap, and changes nothing.

    PRD 3.6: "**The contract cap rule.** A new order is admitted only when
    `estimated_cost_cents` plus the contract's current `committed_cents` plus its
    `invoiced_cents` is less than or equal to `contract_cap_cents`."

    400000 + 1000000 + 0 is far below 20000000 and 2026-10-08 lies inside
    [2026-09-01, 2027-06-01), so only the buffer rule can be speaking.

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, _ = _cedarcrest(api)
    before = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)

    validate_error(
        _post_order(
            ctx,
            "ct1",
            "el1",
            scope="Touches the upper buffer edge exactly",
            window_start=BAND_END,
            window_end="2026-10-09T12:00:00Z",
            estimated_cost_cents=400_000,
        ),
        "ERR_ELEMENT_WINDOW_CONFLICT",
    )

    after = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert after["committed_cents"] == before["committed_cents"] == 1_000_000
    assert after["version"] == before["version"]


def test_one_second_past_the_upper_buffer_edge_is_admitted(api: ApiClient) -> None:
    """A single second clears the closed band and the encumbrance stacks.

    PRD 3.6: "The comparison is over existing work orders on the same element
    whose `status` is `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`, the intervals are
    closed, and **touching endpoints collide**."

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, _ = _cedarcrest(api)

    order = validate_success(
        _post_order(
            ctx,
            "ct1",
            "el1",
            scope="One second past the upper buffer edge",
            window_start="2026-10-08T18:00:01Z",
            window_end="2026-10-09T12:00:00Z",
            estimated_cost_cents=400_000,
        ),
        expected_status=201,
    )

    assert order["status"] == "SCHEDULED"
    assert order["encumbered_cents"] == 400_000
    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)["committed_cents"]
        == 1_400_000
    )


def test_window_ending_exactly_on_the_lower_buffer_edge_collides(
    api: ApiClient,
) -> None:
    """window_end at existing window_start less 24 hours is *at or after*, so it collides.

    PRD 3.6: "**The outage-window buffer rule.** Two orders on the same element
    must be separated by a mandatory quiet buffer of
    `element_window_buffer_hours` -- one full day at the default of 24 hours --
    applied to both ends."

    The band opens at 2026-10-04T08:00:00Z, which is exactly where this window
    ends.

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, _ = _cedarcrest(api)

    validate_error(
        _post_order(
            ctx,
            "ct1",
            "el1",
            scope="Touches the lower buffer edge exactly",
            window_start="2026-10-03T08:00:00Z",
            window_end=BAND_START,
            estimated_cost_cents=400_000,
        ),
        "ERR_ELEMENT_WINDOW_CONFLICT",
        expected_status=409,
    )


def test_one_second_before_the_lower_buffer_edge_is_admitted(api: ApiClient) -> None:
    """The band is [2026-10-04T08:00:00Z, 2026-10-08T18:00:00Z] and this falls outside it.

    PRD 3.6: "A rejection carries `ERR_ELEMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, _ = _cedarcrest(api)

    order = validate_success(
        _post_order(
            ctx,
            "ct1",
            "el1",
            scope="One second before the lower buffer edge",
            window_start="2026-10-03T08:00:00Z",
            window_end="2026-10-04T07:59:59Z",
            estimated_cost_cents=400_000,
        ),
        expected_status=201,
    )

    assert order["status"] == "SCHEDULED"
    assert_instant_equals(order["window_end"], "2026-10-04T07:59:59Z")
    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)["committed_cents"]
        == 1_400_000
    )


def test_reusing_a_live_orders_own_window_is_the_degenerate_collision(
    api: ApiClient,
) -> None:
    """Identical intervals are the simplest closed-interval overlap of all.

    PRD 3.6: "the buffered window must not collide with another open order on the
    same element; and the new encumbrance must fit inside the cap."

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, _ = _cedarcrest(api)

    validate_error(
        _post_order(
            ctx,
            "ct1",
            "el1",
            scope="Exactly the incumbent window",
            window_start=INCUMBENT_START,
            window_end=INCUMBENT_END,
            estimated_cost_cents=400_000,
        ),
        "ERR_ELEMENT_WINDOW_CONFLICT",
        expected_status=409,
    )


def test_cancelling_the_incumbent_releases_the_element_window(
    api: ApiClient,
) -> None:
    """Only SCHEDULED, IN_PROGRESS and ON_HOLD orders occupy an element.

    PRD 3.6: "Cancelling an order is available from `SCHEDULED → CANCELLED` and
    from `ON_HOLD → CANCELLED`, and may carry an optional `reason`. Both legs set
    `encumbered_cents` to 0 and reduce the contract's `committed_cents` by
    exactly the released encumbrance, advancing `VendorContract.version` by 1,
    and both advance the order's own `version` by 1."

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, incumbent = _cedarcrest(api)

    cancelled = validate_success(
        ctx.api.cancel_work_order(incumbent["id"], MANAGER_HEADERS)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["encumbered_cents"] == 0
    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)["committed_cents"] == 0
    )

    replacement = validate_success(
        _post_order(
            ctx,
            "ct1",
            "el1",
            scope="Re-booking the released window",
            window_start=INCUMBENT_START,
            window_end=INCUMBENT_END,
            estimated_cost_cents=400_000,
        ),
        expected_status=201,
    )
    assert replacement["status"] == "SCHEDULED"
    assert_instant_equals(replacement["window_start"], INCUMBENT_START)


def test_the_outage_window_is_exclusive_per_element_not_per_association(
    api: ApiClient,
) -> None:
    """The identical window on a second element and a second vendor is admitted.

    PRD 3.6: "The comparison is over existing work orders on the same element
    whose `status` is `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`, the intervals are
    closed, and **touching endpoints collide**."

    Design: Difficulty/resource_temporal_overlap/element_outage_closed_interval_with_24h_buffer_touching_the_buffer_edge_collides
    """
    ctx, incumbent = _cedarcrest(api)

    twin = validate_success(
        _post_order(
            ctx,
            "ct2",
            "el2",
            scope="Same window, other roof",
            window_start=INCUMBENT_START,
            window_end=INCUMBENT_END,
            estimated_cost_cents=400_000,
        ),
        expected_status=201,
    )

    assert twin["status"] == "SCHEDULED"
    assert twin["window_start"] == incumbent["window_start"]
    assert twin["element_id"] == ctx.elements["el2"]
    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)["committed_cents"]
        == 1_000_000
    )
    assert (
        read_contract(api, ctx.contracts["ct2"], MANAGER_HEADERS)["committed_cents"]
        == 400_000
    )


# ======================================================================
# Resource 2: a meeting's hearing docket (half-open 30-minute slots)
# ======================================================================
def _marisol(api: ApiClient, *, docket_capacity: int | None = None):
    """Four noticed cases on four distinct units, one already docketed at 18:00.

    Every notice is mailed at the epoch, so every ``cure_deadline_at`` lands on
    2026-08-15 and the clock is then pushed strictly past it.
    """
    ctx = create_association(api, legal_name="Marisol Gardens Condominium Association")
    if docket_capacity is not None:
        patch_association(ctx, hearing_docket_capacity=docket_capacity)
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    cases = {}
    for owner_label, unit_label, rule_code in (
        ("ow", "W1", "PARKING"),
        ("ox", "X1", "PARKING"),
        ("oy", "Y1", "NOISE"),
        ("oz", "Z1", "NOISE"),
    ):
        add_owner(ctx, owner_label, full_name=f"Owner {unit_label}")
        add_unit(ctx, unit_label, owner_label, 2500, 1100)
        cases[unit_label] = notice_violation_case(
            ctx, unit_label, rule_code=rule_code, reporter_label="d1"
        )
    schedule_meeting(
        ctx,
        "mtg_a",
        ["HEARING"],
        "2026-10-20T18:00:00Z",
        "2026-10-20T21:00:00Z",
    )
    set_clock(api, "2026-08-16T00:00:00Z")
    docket_hearing(ctx, cases["W1"]["id"], "mtg_a", "2026-10-20T18:00:00Z")
    return ctx, cases


def test_first_docketed_case_takes_the_opening_slot_of_the_meeting(
    api: ApiClient,
) -> None:
    """Round one writes the slot, sets the round to 1 and bumps the docket count.

    PRD 3.8: "The side effects are that `hearing_meeting_id` and
    `hearing_slot_start` are written, `hearing_round` is set to 1, the meeting's
    `hearing_slot_count` rises by 1 with `BoardMeeting.version` advancing by 1,
    and `ViolationCase.version` advances by 1."

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api)

    case1 = read_case(api, cases["W1"]["id"], MANAGER_HEADERS)
    assert case1["status"] == "HEARING_SCHEDULED"
    assert case1["hearing_round"] == 1
    assert_instant_equals(case1["hearing_slot_start"], "2026-10-20T18:00:00Z")
    assert_instant_equals(case1["cure_deadline_at"], "2026-08-15T00:00:00Z")
    meeting = read_meeting(api, ctx.meetings["mtg_a"], MANAGER_HEADERS)
    assert meeting["status"] == "SCHEDULED"
    assert meeting["hearing_slot_count"] == 1


def test_a_slot_that_merely_touches_the_incumbent_slot_is_admitted(
    api: ApiClient,
) -> None:
    """[18:30, 19:00) touches [18:00, 18:30) and half-open slots that touch do not collide.

    PRD 3.8: "Because the slot interval is half-open, a case starting exactly
    when another case's thirty-minute slot ends does **not** collide."

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api)

    docketed = validate_success(
        api.schedule_hearing(
            cases["X1"]["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg_a"],
                "hearing_slot_start": "2026-10-20T18:30:00Z",
            },
            ctx.director("d1"),
        )
    )

    assert docketed["status"] == "HEARING_SCHEDULED"
    assert_instant_equals(docketed["hearing_slot_start"], "2026-10-20T18:30:00Z")
    assert (
        read_meeting(api, ctx.meetings["mtg_a"], MANAGER_HEADERS)["hearing_slot_count"]
        == 2
    )


def test_requesting_an_occupied_slot_is_refused_and_changes_nothing(
    api: ApiClient,
) -> None:
    """The identical start instant is the one geometry the half-open rule rejects.

    PRD 3.8: "no other case docketed to that meeting occupies the half-open
    thirty-minute slot beginning at `hearing_slot_start`, failing which the
    response is `ERR_HEARING_SLOT_TAKEN`"

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api)
    docket_hearing(ctx, cases["X1"]["id"], "mtg_a", "2026-10-20T18:30:00Z")

    validate_error(
        api.schedule_hearing(
            cases["Y1"]["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg_a"],
                "hearing_slot_start": "2026-10-20T18:00:00Z",
            },
            ctx.director("d1"),
        ),
        "ERR_HEARING_SLOT_TAKEN",
        expected_status=409,
    )

    assert read_case(api, cases["Y1"]["id"], MANAGER_HEADERS)["status"] == "NOTICE_SENT"
    assert (
        read_meeting(api, ctx.meetings["mtg_a"], MANAGER_HEADERS)["hearing_slot_count"]
        == 2
    )


def test_an_off_boundary_start_fails_alignment_not_occupancy(
    api: ApiClient,
) -> None:
    """19:15 intersects nothing, so the thirty-minute boundary rule is what refuses it.

    PRD 3.8: "`hearing_slot_start` sits on a thirty-minute boundary and the whole
    thirty-minute slot lies inside the meeting's window, which is inclusive of
    `scheduled_start` and exclusive of `scheduled_end`, failing which the
    response is `ERR_SLOT_OUTSIDE_MEETING`"

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api)

    validate_error(
        api.schedule_hearing(
            cases["Y1"]["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg_a"],
                "hearing_slot_start": "2026-10-20T19:15:00Z",
            },
            ctx.director("d1"),
        ),
        "ERR_SLOT_OUTSIDE_MEETING",
        expected_status=422,
    )

    assert read_case(api, cases["Y1"]["id"], MANAGER_HEADERS)["status"] == "NOTICE_SENT"


def test_the_last_slot_ending_exactly_at_scheduled_end_is_admitted(
    api: ApiClient,
) -> None:
    """[20:30, 21:00) is contained because containment is half-open too.

    PRD 3.8: "`hearing_slot_start` sits on a thirty-minute boundary and the whole
    thirty-minute slot lies inside the meeting's window, which is inclusive of
    `scheduled_start` and exclusive of `scheduled_end`, failing which the
    response is `ERR_SLOT_OUTSIDE_MEETING`"

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api)
    docket_hearing(ctx, cases["X1"]["id"], "mtg_a", "2026-10-20T18:30:00Z")

    docketed = validate_success(
        api.schedule_hearing(
            cases["Y1"]["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg_a"],
                "hearing_slot_start": "2026-10-20T20:30:00Z",
            },
            ctx.director("d1"),
        )
    )

    assert docketed["status"] == "HEARING_SCHEDULED"
    assert_instant_equals(docketed["hearing_slot_start"], "2026-10-20T20:30:00Z")
    assert (
        read_meeting(api, ctx.meetings["mtg_a"], MANAGER_HEADERS)["hearing_slot_count"]
        == 3
    )


def test_a_slot_starting_at_scheduled_end_is_out_of_range(api: ApiClient) -> None:
    """One slot further on, and the exclusive end of the meeting window bites.

    PRD 3.8: "`hearing_slot_start` sits on a thirty-minute boundary and the whole
    thirty-minute slot lies inside the meeting's window, which is inclusive of
    `scheduled_start` and exclusive of `scheduled_end`, failing which the
    response is `ERR_SLOT_OUTSIDE_MEETING`"

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api)

    validate_error(
        api.schedule_hearing(
            cases["Z1"]["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg_a"],
                "hearing_slot_start": "2026-10-20T21:00:00Z",
            },
            ctx.director("d1"),
        ),
        "ERR_SLOT_OUTSIDE_MEETING",
        expected_status=422,
    )

    assert read_case(api, cases["Z1"]["id"], MANAGER_HEADERS)["status"] == "NOTICE_SENT"


def test_a_full_docket_refuses_even_an_unoccupied_slot(api: ApiClient) -> None:
    """Capacity is counted, not searched: 19:00 is free but the docket is closed.

    PRD 3.8: "the meeting's `hearing_slot_count` is strictly below
    `hearing_docket_capacity`, failing which the response is
    `ERR_HEARING_DOCKET_FULL`"

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api, docket_capacity=2)
    docket_hearing(ctx, cases["X1"]["id"], "mtg_a", "2026-10-20T18:30:00Z")
    assert (
        read_meeting(api, ctx.meetings["mtg_a"], MANAGER_HEADERS)["hearing_slot_count"]
        == 2
    )

    validate_error(
        api.schedule_hearing(
            cases["Y1"]["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg_a"],
                "hearing_slot_start": "2026-10-20T19:00:00Z",
            },
            ctx.director("d1"),
        ),
        "ERR_HEARING_DOCKET_FULL",
        expected_status=409,
    )

    assert read_case(api, cases["Y1"]["id"], MANAGER_HEADERS)["status"] == "NOTICE_SENT"


def test_slot_occupancy_is_scoped_to_a_single_meeting(api: ApiClient) -> None:
    """A second HEARING meeting accepts the same wall-clock slot on its own docket.

    PRD 3.8: "no other case docketed to that meeting occupies the half-open
    thirty-minute slot beginning at `hearing_slot_start`, failing which the
    response is `ERR_HEARING_SLOT_TAKEN`"

    Design: Difficulty/resource_temporal_overlap/hearing_docket_half_open_30min_slots_touch_allowed_and_last_legal_slot_is_2030
    """
    ctx, cases = _marisol(api)
    schedule_meeting(
        ctx,
        "mtg_b",
        ["HEARING"],
        "2026-10-27T18:00:00Z",
        "2026-10-27T21:00:00Z",
    )

    docketed = get_success_data(
        api.schedule_hearing(
            cases["Y1"]["id"],
            {
                "hearing_meeting_id": ctx.meetings["mtg_b"],
                "hearing_slot_start": "2026-10-27T18:00:00Z",
            },
            ctx.director("d1"),
        )
    )

    assert docketed["status"] == "HEARING_SCHEDULED"
    assert docketed["hearing_meeting_id"] == ctx.meetings["mtg_b"]
    assert (
        read_meeting(api, ctx.meetings["mtg_b"], MANAGER_HEADERS)["hearing_slot_count"]
        == 1
    )
    assert (
        read_meeting(api, ctx.meetings["mtg_a"], MANAGER_HEADERS)["hearing_slot_count"]
        == 1
    )
