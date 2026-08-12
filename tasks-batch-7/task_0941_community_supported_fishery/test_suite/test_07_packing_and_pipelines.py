"""Packing a box, the invoice chain, cooler-slot accounting and the two fulfilment pipelines."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate,
    close_window,
    delivery_of_week,
    hub_destination,
    log_leg,
    make_member_headers,
    new_hub,
    new_window,
    open_window,
    pack_delivery,
    read_delivery,
    read_lot,
    read_member,
    read_subscription,
    read_window,
    set_clock,
    setup_fleet,
    setup_home_delivery_box_split,
    setup_hub_box_packed,
    setup_hub_box_staged,
    setup_landed_lot,
    setup_member_subscription,
    setup_no_show_sequence,
    setup_open_season,
    split_lot,
    stage_delivery,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]

LARGE_WHITEFISH_WEEKLY = {
    "plan_code": "LRG-WHITE-W",
    "share_size": "LARGE",
    "delivery_frequency": "WEEKLY",
    "species_tier": "WHITEFISH",
}
TIER_1_SIX_HOUR_ZONE = {"zone_code": "ZONE-1", "fee_tier": "TIER_1", "transit_hours": 6.0}


def _home_delivery_box(pool_pounds):
    return setup_home_delivery_box_split(
        pool_pounds=pool_pounds,
        plan_overrides=LARGE_WHITEFISH_WEEKLY,
        zone_overrides=TIER_1_SIX_HOUR_ZONE,
        ambient_band="HOT",
        paid_cents=104000,
        species="COD",
        offered_species=("COD",),
    )


def test_the_surcharge_waiver_reads_the_subtotal_and_not_the_running_total(api):
    """PRD 3.7: "It is also 0 whenever `subtotal_cents` has reached or passed
    `FREE_SURCHARGE_THRESHOLD_CENTS`, which is 6000 cents — a large enough share earns free
    carriage. Otherwise it is `REMOTE_SURCHARGE_CENTS`, which is 250 cents. **The waiver test
    reads `subtotal_cents` and nothing else.**"
    PRD 3.7: "The `delivery_fee_cents` is the zone base plus the pack cost plus the surcharge."
    PRD 3.7: "The `invoice_total_cents` is `subtotal_cents` plus `delivery_fee_cents`."
    PRD 3.7: "The `charged_cents` is set equal to `invoice_total_cents`."

    The subtotal is 5200, below the 6000 threshold, so the surcharge stands at 250 even though
    the pre-surcharge running total of 5200 + 500 + 1000 already clears it.

    Design: Difficulty/combinatorial_formula/surcharge_waiver_reads_subtotal_before_fees
    """
    ctx = _home_delivery_box(6.00)
    delivery = pack_delivery(ctx["delivery_id"])

    assert delivery["subtotal_cents"] == 5200
    assert delivery["surcharge_cents"] == 250
    assert delivery["delivery_fee_cents"] == 1750
    assert delivery["invoice_total_cents"] == 6950
    assert delivery["charged_cents"] == 6950


def test_a_six_pound_home_box_takes_a_small_pack_and_four_gel_packs(api):
    """PRD 3.7: "`box_pounds` is the delivery's `allocated_pounds` plus its `substituted_pounds`
    — the actual weight going into the container."
    PRD 3.7: "`PACK_SMALL_MAX_LB` is 6.00 pounds, so a box at or below 6.00 pounds takes a
    `SMALL` pack"
    PRD 3.7: "The `gel_pack_count` is the zone's `transit_hours` divided by the applicable
    figure and rounded *up* to a whole number, with a floor of one pack — a home-delivery box
    always carries at least one."
    PRD 3.7: "so in the `HOT` band over a 6.0 hour transit a `SMALL` pack needs four gel packs
    while a `MEDIUM` pack needs only two, and a `LARGE` also two."

    Design: Difficulty/combinatorial_formula/surcharge_waiver_reads_subtotal_before_fees
    """
    ctx = _home_delivery_box(6.00)
    delivery = pack_delivery(ctx["delivery_id"])

    assert float(delivery["allocated_pounds"]) == pytest.approx(6.00)
    assert float(delivery["box_pounds"]) == pytest.approx(6.00)
    assert delivery["pack_size"] == "SMALL"
    assert delivery["gel_pack_count"] == 4
    assert delivery["fulfillment_status"] == "PACKED"


def test_one_extra_hundredth_of_a_pound_tips_the_box_into_a_cheaper_medium_pack(api):
    """PRD 3.7: "`PACK_MEDIUM_MAX_LB` is 14.00 pounds, so a box above 6.00 and at or below
    14.00 takes a `MEDIUM`; and anything above 14.00 takes a `LARGE`. Exactly 6.00 pounds is
    `SMALL`, 6.01 is `MEDIUM`, 14.00 is `MEDIUM` and 14.01 is `LARGE`."
    PRD 3.7: "A 6.01 pound box takes a `MEDIUM` pack and only two gel packs, costing 450 plus
    350, producing a `delivery_fee_cents` of 1550 and an `invoice_total_cents` of 6750."

    Design: Difficulty/boundary_precision_check/pack_tier_boundary_six_point_zero_one_costs_less_than_six
    """
    ctx = _home_delivery_box(6.01)
    delivery = pack_delivery(ctx["delivery_id"])

    assert float(delivery["box_pounds"]) == pytest.approx(6.01)
    assert delivery["pack_size"] == "MEDIUM"
    assert delivery["gel_pack_count"] == 2
    assert delivery["surcharge_cents"] == 250
    assert delivery["delivery_fee_cents"] == 1550
    assert delivery["invoice_total_cents"] == 6750


def test_the_six_pound_counterpart_of_the_pack_boundary_costs_two_hundred_cents_more(api):
    """PRD 3.7: "A 6.00 pound box takes a `SMALL` pack and four gel packs, costing 300 plus
    700, and with the 500 zone base and the 250 surcharge produces a `delivery_fee_cents` of
    1750 and an `invoice_total_cents` of 6950."
    PRD 3.7: "One extra hundredth of a pound of fish makes the box 200 cents cheaper, both in
    absolute fee and per pound."

    Design: Difficulty/boundary_precision_check/pack_tier_boundary_six_point_zero_one_costs_less_than_six
    """
    ctx = _home_delivery_box(6.00)
    delivery = pack_delivery(ctx["delivery_id"])

    assert delivery["pack_size"] == "SMALL"
    assert delivery["gel_pack_count"] == 4
    assert delivery["delivery_fee_cents"] == 1750
    assert delivery["invoice_total_cents"] == 6950
    assert delivery["invoice_total_cents"] - 6750 == 200


def test_a_hub_pickup_box_carries_no_pack_and_no_delivery_fee(api):
    """PRD 3.7: "On the hub-pickup pipeline there is no insulated pack at all: `pack_size` is
    `NONE` and `gel_pack_count` is 0."
    PRD 3.7: "On the hub-pickup pipeline, both the pack cost and the zone base are 0."
    PRD 3.7: "It is 0 whenever the subscription's `fulfillment_mode` is `HUB_PICKUP`."

    Design: Corner/calculations/hub_pickup_invoice_carries_no_delivery_fee
    """
    ctx = setup_hub_box_packed(pool_pounds=5.00, paid_cents=90000)
    delivery = read_delivery(ctx["delivery_id"])

    assert delivery["pack_size"] == "NONE"
    assert delivery["gel_pack_count"] == 0
    assert delivery["surcharge_cents"] == 0
    assert delivery["delivery_fee_cents"] == 0
    assert delivery["subtotal_cents"] == 4500
    assert delivery["invoice_total_cents"] == 4500
    assert delivery["fill_status"] == "FULL_FILL"


def _two_boxes_one_cooler_slot():
    """Two packed hub boxes for two distinct members and a week-1 window holding one slot."""
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub(cooler_slots_default=1)
    first = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Mara One",
        email="m1@csf.test",
        paid_cents=90000,
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    second = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Nils Two",
        email="m2@csf.test",
        paid_cents=90000,
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 10.00)
    allocate(landing["lot_id"], 1, landing["lot"]["version"])
    split_lot(landing["lot_id"], [hub_destination(hub["id"], 10.00)])

    delivery_one = delivery_of_week(first["subscription_id"], 1)
    delivery_two = delivery_of_week(second["subscription_id"], 1)
    pack_delivery(delivery_one["id"])
    pack_delivery(delivery_two["id"])

    window = new_window(hub["id"], ctx["season_id"], 1, cooler_slots_total=1)
    stage_delivery(delivery_one["id"], window["id"])

    ctx.update(landing)
    ctx.update(
        {
            "hub": hub,
            "window": window,
            "delivery_one": delivery_one,
            "delivery_two": delivery_two,
        }
    )
    return ctx


def test_staging_a_second_box_into_a_one_slot_window_is_refused(api):
    """PRD 3.7: "`slots_free` is at all times `cooler_slots_total` less the reserved, occupied
    and forfeited counts, and staging is refused with `ERR_HUB_CAPACITY_EXCEEDED` when
    `slots_free` is below 1 before the increment."
    PRD 2.5: "The window's `slots_free` is at least 1 before the reservation is taken —
    otherwise `ERR_HUB_CAPACITY_EXCEEDED` (HTTP 409), on hub staging."

    Design: Difficulty/resource_temporal_overlap/cooler_slot_capacity_partition_rejects_the_extra_box
    """
    ctx = _two_boxes_one_cooler_slot()

    response = api.stage_at_hub(
        ctx["delivery_two"]["id"], {"pickup_window_id": ctx["window"]["id"]}, HUB_OP
    )
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_HUB_CAPACITY_EXCEEDED.value)

    rejected_box = read_delivery(ctx["delivery_two"]["id"])
    assert rejected_box["fulfillment_status"] == "PACKED"
    assert rejected_box.get("pickup_window_id") != ctx["window"]["id"]


def test_the_refused_staging_consumes_no_cooler_slot(api):
    """PRD 3.7: "Cooler slots are strictly accounted. Staging raises `slots_reserved` by 1."
    PRD 2.9: "`INV_HUB_SLOT_PARTITION` — for every pickup window, `cooler_slots_total` equals
    `slots_free` plus `slots_reserved` plus `slots_occupied` plus `slots_forfeited`."

    Design: Difficulty/resource_temporal_overlap/cooler_slot_capacity_partition_rejects_the_extra_box
    """
    ctx = _two_boxes_one_cooler_slot()
    api.stage_at_hub(ctx["delivery_two"]["id"], {"pickup_window_id": ctx["window"]["id"]}, HUB_OP)

    window = read_window(ctx["window"]["id"])
    assert window["cooler_slots_total"] == 1
    assert window["slots_reserved"] == 1
    assert window["slots_occupied"] == 0
    assert window["slots_forfeited"] == 0
    assert window["slots_free"] == 0


def test_pickup_before_the_window_opens_is_refused(api):
    """PRD 2.5: "The pickup window is in a status that admits the operation — otherwise
    `ERR_WINDOW_NOT_OPEN` (HTTP 409). Staging requires the window to be `SCHEDULED` or `OPEN`;
    recording a pickup requires it to be `OPEN` or `GRACE`; closing it requires it to be `OPEN`
    or `GRACE`."
    PRD 3.7: "Collection moves the delivery `AT_HUB → PICKED_UP`. It requires the window to be
    `OPEN` or `GRACE`, the logical clock to be at or before the window's `closes_at` plus its
    frozen `grace_minutes` — one second past that and the collection is refused with
    `ERR_WINDOW_GRACE_EXPIRED` — the lot's `quality_status` to be `CLEAR`, `RELEASED` or
    `DISCOUNTED`, and at least one cold-chain leg with `custody_leg` `HUB_HOLD` to have been
    logged against the lot."

    Design: Corner/errors/error_window_not_open_on_pickup_before_the_window_opens
    """
    ctx = setup_hub_box_staged(pool_pounds=5.00, paid_cents=90000)
    log_leg(ctx["lot_id"], "HUB_HOLD", 0, 2.0)

    response = api.record_pickup(ctx["delivery_id"], make_member_headers(ctx["member_id"]))
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_WINDOW_NOT_OPEN.value)

    window = read_window(ctx["window_id"])
    assert window["status"] == "SCHEDULED"
    assert window["slots_reserved"] == 1
    assert read_delivery(ctx["delivery_id"])["fulfillment_status"] == "AT_HUB"


def test_pickup_one_second_past_the_grace_instant_is_refused(api):
    """PRD 2.5: "The pickup instant is at or before the window's `closes_at` plus its
    `grace_minutes`; one second later is refused with `ERR_WINDOW_GRACE_EXPIRED` (HTTP 409), on
    pickup."
    PRD 3.1: "and `grace_minutes`, which is copied from the hub's `grace_minutes` at the moment
    the window is created and frozen there, so that later edits to the hub do not retroactively
    move a window's grace tail."

    The window closes at 2026-05-04T18:00:00Z with 90 grace minutes, so the last admissible
    instant is 19:30:00Z and the pickup is attempted at 19:30:01Z.

    Design: Corner/errors/error_window_grace_expired_on_a_clear_lot
    """
    ctx = setup_hub_box_staged(pool_pounds=5.00, paid_cents=90000, open_the_window=True)
    log_leg(ctx["lot_id"], "HUB_HOLD", 0, 2.0)
    set_clock("2026-05-04T19:30:01Z")

    response = api.record_pickup(ctx["delivery_id"], make_member_headers(ctx["member_id"]))
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_WINDOW_GRACE_EXPIRED.value)

    assert read_delivery(ctx["delivery_id"])["fulfillment_status"] == "AT_HUB"
    assert read_window(ctx["window_id"])["slots_occupied"] == 0
    assert read_subscription(ctx["subscription_id"])["delivered_count"] == 0


def test_pickup_without_the_hub_hold_leg_is_refused_for_missing_evidence(api):
    """PRD 2.5: "The custody evidence the pipeline requires exists — otherwise
    `ERR_COLD_CHAIN_EVIDENCE_MISSING` (HTTP 422). Delivering a home box requires a
    `HUB_TO_DOOR` leg logged on the lot; recording a hub pickup requires a `HUB_HOLD` leg
    logged on the lot."

    Design: Corner/validations/pickup_without_the_hub_hold_leg_returns_evidence_missing
    """
    ctx = setup_hub_box_staged(pool_pounds=5.00, paid_cents=90000, open_the_window=True)
    log_leg(ctx["lot_id"], "DOCK_TO_HUB", 0, 2.0)

    response = api.record_pickup(ctx["delivery_id"], make_member_headers(ctx["member_id"]))
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_COLD_CHAIN_EVIDENCE_MISSING.value)

    assert read_delivery(ctx["delivery_id"])["fulfillment_status"] == "AT_HUB"
    assert read_lot(ctx["lot_id"])["quality_status"] == "CLEAR"
    assert read_window(ctx["window_id"])["slots_occupied"] == 0


def _held_lot_past_grace():
    """A staged box past its grace instant whose lot is also standing on quality HOLD."""
    ctx = setup_hub_box_staged(pool_pounds=5.00, paid_cents=90000, open_the_window=True,
                               clock_at_open="2026-05-04T12:00:00Z")
    log_leg(ctx["lot_id"], "HUB_HOLD", 25, 9.0)
    set_clock("2026-05-04T19:31:00Z")
    return ctx


def test_the_quality_hold_answers_the_pickup_before_the_expired_grace_does(api):
    """PRD 2.5: "The lot behind the box has `quality_status` of `CLEAR`, `RELEASED` or
    `DISCOUNTED` — otherwise `ERR_LOT_ON_QUALITY_HOLD` (HTTP 409). This guards home delivery
    completion and hub pickup."
    PRD 2.5: "when a request would fail more than one rung, the response carries the error of
    the **lowest-numbered** rung it fails, and no later rung is evaluated."
    PRD 3.6: "On the member side, handing over a box from a held lot — completing a home
    delivery or recording a hub pickup — is refused with `ERR_LOT_ON_QUALITY_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/quality_hold_safety_outranks_grace_temporal_on_pickup
    """
    ctx = _held_lot_past_grace()

    response = api.record_pickup(ctx["delivery_id"], make_member_headers(ctx["member_id"]))
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_LOT_ON_QUALITY_HOLD.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_WINDOW_GRACE_EXPIRED.value


def test_the_refused_pickup_leaves_the_box_staged_and_the_lot_on_hold(api):
    """PRD 3.6: "Any `breach_type` other than `NONE` moves the lot's quality axis `CLEAR →
    HOLD`, and a hold has immediate consequences on both sides of the business."
    PRD 3.7: "Staging stamps `pickup_window_id` onto the delivery and moves it `PACKED →
    AT_HUB`."

    Design: Difficulty/priority_pair_validation_conflict/quality_hold_safety_outranks_grace_temporal_on_pickup
    """
    ctx = _held_lot_past_grace()
    api.record_pickup(ctx["delivery_id"], make_member_headers(ctx["member_id"]))

    assert read_delivery(ctx["delivery_id"])["fulfillment_status"] == "AT_HUB"
    assert read_window(ctx["window_id"])["slots_reserved"] == 1
    assert read_lot(ctx["lot_id"])["quality_status"] == "HOLD"


def test_closing_the_second_window_donates_and_forfeits_the_uncollected_box(api):
    """PRD 3.7: "Hop one: every delivery in that window still standing in `AT_HUB` moves to
    `NO_SHOW`. Hop two, caused by hop one: each such delivery moves `NO_SHOW → DONATED`, its
    money axis moves `CHARGED → FORFEITED` with `credit_cents` left at 0 — a no-show is not
    refunded — its cooler slot moves from reserved to forfeited, the owning member's
    `season_no_show_count` rises by 1 and the owning subscription's `member_fault_count` rises
    by 1."
    PRD 3.7: "The window itself moves `OPEN → CLOSED` or `GRACE → CLOSED`, and then, once no
    delivery in it remains `AT_HUB`, moves `CLOSED → RECONCILED` inside the same request, with
    `slots_reserved` down to 0 and `slots_free` recomputed."

    Design: Difficulty/transitive_cascade/hub_no_show_four_hop_cascade
    """
    ctx = setup_no_show_sequence(close_second_window=True)

    delivery = read_delivery(ctx["delivery_2_id"])
    assert delivery["fulfillment_status"] == "DONATED"
    assert delivery["billing_status"] == "FORFEITED"
    assert delivery["credit_cents"] == 0

    window = read_window(ctx["window_2_id"])
    assert window["status"] == "RECONCILED"
    assert window["slots_reserved"] == 0
    assert window["slots_forfeited"] == 1
    assert window["slots_free"] == 1


def test_the_second_no_show_restricts_the_member_and_pauses_their_subscription(api):
    """PRD 3.7: "Hop three, caused by the member counter written in hop two: the member's
    `standing` escalates. `NO_SHOW_WARN_THRESHOLD` is 1 and `NO_SHOW_RESTRICT_THRESHOLD` is 2,
    and both fire on reaching the threshold rather than exceeding it, so a `season_no_show_count`
    of 1 moves `GOOD → WARNED` while a count of 2 or more moves `WARNED → RESTRICTED`; a count
    of 0 leaves the standing alone."
    PRD 3.7: "Hop four, caused by hop three: when a member has become `RESTRICTED`, every
    subscription of theirs standing in `ACTIVE` moves to `PAUSED`, and it stays paused —
    clearing the restriction later does not auto-resume it."

    Design: Difficulty/transitive_cascade/hub_no_show_four_hop_cascade
    """
    ctx = setup_no_show_sequence(close_second_window=True)

    member = read_member(ctx["member_id"])
    assert member["season_no_show_count"] == 2
    assert member["standing"] == "RESTRICTED"

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["lifecycle_status"] == "PAUSED"
    assert subscription["member_fault_count"] == 2
