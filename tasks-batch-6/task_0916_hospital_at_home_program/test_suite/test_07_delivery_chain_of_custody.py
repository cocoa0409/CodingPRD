"""Delivery orders: the handling fee, the capped redelivery loop and custody."""

from test_helpers import (
    ApiErrorId,
    assert_delivery_order,
    assert_money,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_delivery_order_payload
from test_helpers.test_users import (
    COMMUNITY_PARAMEDIC,
    LOGISTICS_COORDINATOR,
    PROGRAM_ADMIN,
    make_pharmacy_authorizer_headers,
)


# ─── The controlled / non-controlled fee fork ──────────────────────────────

def test_controlled_order_carries_the_base_and_witness_components(api):
    """PRD §3.6: "Two of the fee's components fork on whether the order is
    controlled: a controlled order starts from a base of 45.00 US dollars and
    carries a witness fee of 12.50 US dollars, while a non-controlled order
    starts from a base of 12.00 US dollars and carries no witness fee at all —
    the same weight and cold-chain inputs therefore produce a raw figure 45.50
    lower on a non-controlled order before any floor or cap applies."
    PRD §3.6: "To the base and witness components the system adds a cold-chain
    surcharge of 22.00 US dollars when `cold_chain_required` is true and nothing
    when it is false; a weight component equal to `weight_kg` multiplied by 1.40
    US dollars per kilogram, **rounded half up to two decimals before it enters
    the sum**; and a redelivery component equal to `redelivery_count` — read at
    the instant of the recompute — multiplied by 9.00 US dollars per
    redelivery."

    Design: Difficulty/dual_variant_calc/controlled_vs_non_controlled_handling_fee_diverge_by_45_50
    """
    parts = fx.setup_active_episode(
        home_distance_km=12.5,
        primary_diagnosis_code="CELLULITIS",
        qualifying_condition_code="CELLULITIS",
        mrn="MRN-D1",
        full_name="Dana Delivery",
    )
    episode_id = parts["episode"]["id"]

    controlled = validate_success(
        api.create_delivery_order(
            create_delivery_order_payload(
                episode_id,
                order_kind="MEDICATION",
                is_controlled=True,
                cold_chain_required=True,
                weight_kg=3.5,
                requested_by_user_id="log-1",
            ),
            LOGISTICS_COORDINATOR,
        ),
        201,
    )
    assert_delivery_order(controlled)
    assert_money(controlled["handling_fee_usd"], 84.40, "controlled handling_fee_usd")
    assert controlled["status"] == "PENDING_AUTHORIZATION"
    assert controlled["redelivery_count"] == 0


def test_non_controlled_order_costs_forty_five_fifty_less(api):
    """PRD §3.6: "Two of the fee's components fork on whether the order is
    controlled: a controlled order starts from a base of 45.00 US dollars and
    carries a witness fee of 12.50 US dollars, while a non-controlled order
    starts from a base of 12.00 US dollars and carries no witness fee at all —
    the same weight and cold-chain inputs therefore produce a raw figure 45.50
    lower on a non-controlled order before any floor or cap applies."

    Design: Difficulty/dual_variant_calc/controlled_vs_non_controlled_handling_fee_diverge_by_45_50
    """
    parts = fx.setup_active_episode(
        home_distance_km=12.5,
        primary_diagnosis_code="CELLULITIS",
        qualifying_condition_code="CELLULITIS",
        mrn="MRN-D2",
        full_name="Dana Delivery Two",
    )
    episode_id = parts["episode"]["id"]

    controlled = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=True,
        cold_chain_required=True,
        weight_kg=3.5,
        requested_by_user_id="log-1",
    )
    plain = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=False,
        cold_chain_required=True,
        weight_kg=3.5,
        requested_by_user_id="log-1",
    )

    assert_money(plain["handling_fee_usd"], 38.90, "non-controlled handling_fee_usd")
    assert plain["status"] == "PENDING_AUTHORIZATION"
    assert_money(
        controlled["handling_fee_usd"] - plain["handling_fee_usd"],
        45.50,
        "controlled minus non-controlled handling fee",
    )


# ─── Floor before cap ──────────────────────────────────────────────────────

def test_raw_fee_below_fifteen_dollars_is_lifted_to_the_floor(api):
    """PRD §3.6: "That raw total is then bounded in a pinned order: first it is
    raised to the fifteen-dollar floor if it falls below it, and only afterwards
    lowered to the one-hundred-and-twenty-dollar cap if it exceeds it. The
    bounded figure is rounded half up to two decimals and stored as
    `handling_fee_usd`."

    Design: Difficulty/combinatorial_formula/delivery_fee_nested_floor_then_cap_mode_a
    """
    parts = fx.setup_active_episode(
        home_distance_km=9.0,
        primary_diagnosis_code="COPD_EXAC",
        qualifying_condition_code="COPD_EXAC",
        origin="INPATIENT_WARD",
        eval_at="2026-06-01T07:00:00Z",
        mrn="MRN-C1",
        full_name="Cara Cap",
    )
    episode_id = parts["episode"]["id"]

    order = fx.raise_delivery_order(
        episode_id,
        order_kind="DME",
        is_controlled=False,
        cold_chain_required=False,
        weight_kg=2.0,
        requested_by_user_id="log-1",
    )
    assert_money(order["handling_fee_usd"], 15.00, "floored handling_fee_usd")
    assert order["handling_fee_usd"] != 14.80, (
        "the raw sum of 12.00 + 2.80 is lifted to the fifteen-dollar floor"
    )


def test_raw_fee_above_one_hundred_and_twenty_dollars_is_cut_to_the_cap(api):
    """PRD §3.6: "That raw total is then bounded in a pinned order: first it is
    raised to the fifteen-dollar floor if it falls below it, and only afterwards
    lowered to the one-hundred-and-twenty-dollar cap if it exceeds it. The
    bounded figure is rounded half up to two decimals and stored as
    `handling_fee_usd`."

    Design: Difficulty/combinatorial_formula/delivery_fee_nested_floor_then_cap_mode_a
    """
    parts = fx.setup_active_episode(
        home_distance_km=9.0,
        primary_diagnosis_code="COPD_EXAC",
        qualifying_condition_code="COPD_EXAC",
        origin="INPATIENT_WARD",
        eval_at="2026-06-01T07:00:00Z",
        mrn="MRN-C2",
        full_name="Cara Cap Two",
    )
    episode_id = parts["episode"]["id"]

    order = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=True,
        cold_chain_required=True,
        weight_kg=40.0,
        requested_by_user_id="log-1",
    )
    assert_money(order["handling_fee_usd"], 120.00, "capped handling_fee_usd")
    assert order["handling_fee_usd"] != 135.50, (
        "the raw sum of 45.00 + 12.50 + 22.00 + 56.00 is cut to the cap"
    )


# ─── The capped redelivery loop ────────────────────────────────────────────

def _order_driven_to_two_spent_redeliveries(mrn: str, full_name: str) -> dict:
    parts = fx.setup_active_episode(
        home_distance_km=5.0,
        primary_diagnosis_code="CELLULITIS",
        qualifying_condition_code="CELLULITIS",
        mrn=mrn,
        full_name=full_name,
    )
    episode_id = parts["episode"]["id"]
    order = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=True,
        cold_chain_required=True,
        weight_kg=3.5,
        requested_by_user_id="log-1",
    )
    fx.authorize_order(order["id"], "pharm-9")
    for _ in range(3):
        fx.dispatch_order(order["id"])
        fx.refuse_order(order["id"])
    parts["order"] = order
    return parts


def test_dispatch_beyond_two_redeliveries_is_refused_by_the_cap(api):
    """PRD §3.6: "A redelivery attempt on an order whose `redelivery_count` has
    already reached 2 is refused with `ERR_REDELIVERY_LIMIT_EXCEEDED` at HTTP 409
    and the order stays in `REFUSED` — this cap is deliberately enforced below
    the state check rather than as part of it, because `REFUSED` remains a legal
    state to dispatch from until both redeliveries are spent."
    PRD §3.6: "From `REFUSED` it is a **redelivery**: the episode must still be
    `ACTIVE`, `redelivery_count` must be strictly below 2, and success moves the
    order back to `OUT_FOR_DELIVERY`, increments `redelivery_count` by 1,
    recomputes `handling_fee_usd` with the new redelivery component, and advances
    the order's `version` by 1."

    Design: Difficulty/non_linear_state_machine/delivery_order_capped_redelivery_loop_then_abandoned_to_failed
    """
    parts = _order_driven_to_two_spent_redeliveries("MRN-R1", "Rex Redeliver")
    episode_id = parts["episode"]["id"]
    order_id = parts["order"]["id"]

    before = fx.read_delivery_order(episode_id, order_id)
    assert before["status"] == "REFUSED"
    assert before["redelivery_count"] == 2

    validate_error(
        api.dispatch_delivery_order(order_id, LOGISTICS_COORDINATOR),
        ApiErrorId.ERR_REDELIVERY_LIMIT_EXCEEDED.value,
    )

    after = fx.read_delivery_order(episode_id, order_id)
    assert after["status"] == "REFUSED", "the rejected dispatch leaves the order refused"
    assert after["redelivery_count"] == 2, (
        "a rejected dispatch must not touch redelivery_count"
    )
    assert_money(after["handling_fee_usd"], 102.40, "handling_fee_usd")


def test_refusing_an_exhausted_order_abandons_it_and_opens_an_escalation(api):
    """PRD §3.6: "A refusal recorded against an order **already** in `REFUSED` is
    the abandonment path: it is permitted only when `redelivery_count` is exactly
    2, meaning both permitted redeliveries have been spent, and an
    already-refused order with fewer than two redeliveries behind it is refused
    with `ERR_INVALID_STATE` because a redelivery is still available to it."
    PRD §3.6: "When abandonment does apply, the order moves `REFUSED → FAILED`, a
    brand-new escalation is opened on the same episode with a `reason` of
    `MEDICATION_FAILURE`, a `status` of `TIER1_OPEN` and an `opened_by_user_id`
    set to the refusing caller's identifier"

    Design: Difficulty/non_linear_state_machine/delivery_order_capped_redelivery_loop_then_abandoned_to_failed
    """
    parts = _order_driven_to_two_spent_redeliveries("MRN-R2", "Rex Redeliver Two")
    episode_id = parts["episode"]["id"]
    order_id = parts["order"]["id"]

    validate_error(
        api.dispatch_delivery_order(order_id, LOGISTICS_COORDINATOR),
        ApiErrorId.ERR_REDELIVERY_LIMIT_EXCEEDED.value,
    )
    abandoned = validate_success(
        api.refuse_delivery_order(order_id, LOGISTICS_COORDINATOR)
    )
    assert abandoned["status"] == "FAILED"

    events, meta = validate_paginated(
        api.list_episode_escalation_events(episode_id, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1, (
        f"abandonment opens exactly one escalation, got {meta['total_count']}"
    )
    assert events[0]["reason"] == "MEDICATION_FAILURE"
    assert events[0]["status"] == "TIER1_OPEN"
    assert events[0]["current_tier"] == 1
    assert events[0]["promotion_count"] == 0
    assert events[0]["acknowledged_by_user_id"] is None

    assert fx.read_episode(episode_id)["open_escalation_count"] == 1


# ─── Custody at the door ───────────────────────────────────────────────────

def test_cold_chain_excursion_of_thirty_minutes_delivers_and_thirty_one_is_rejected(api):
    """PRD §3.6: "A cold-chain order must report `excursion_minutes` at or below
    30 — exactly thirty minutes out of temperature passes, thirty-one minutes
    spoils the payload and is refused with `ERR_COLD_CHAIN_EXCURSION` at HTTP
    422."
    PRD §3.6: "Whichever of the two fields are supplied are recorded on the
    order, `witness_staff_id` as itself and `excursion_minutes` into
    `last_excursion_minutes`; `handling_fee_usd` is recomputed; and the order's
    `version` advances by 1."

    Design: Corner/validations/cold_chain_excursion_of_30_minutes_delivers_and_31_minutes_is_rejected
    """
    parts = fx.setup_active_episode(
        primary_diagnosis_code="CELLULITIS",
        qualifying_condition_code="CELLULITIS",
        mrn="MRN-CC",
        full_name="Cleo Chain",
    )
    episode_id = parts["episode"]["id"]

    ok_order = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=False,
        cold_chain_required=True,
        weight_kg=1.0,
        requested_by_user_id="log-1",
    )
    spoiled_order = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=False,
        cold_chain_required=True,
        weight_kg=1.0,
        requested_by_user_id="log-1",
    )
    for order in (ok_order, spoiled_order):
        fx.authorize_order(order["id"], "pharm-9")
        fx.dispatch_order(order["id"])

    delivered = validate_success(
        api.deliver_delivery_order(
            ok_order["id"], {"excursion_minutes": 30}, LOGISTICS_COORDINATOR
        )
    )
    assert delivered["status"] == "DELIVERED"
    assert delivered["last_excursion_minutes"] == 30
    assert_money(delivered["handling_fee_usd"], 35.40, "handling_fee_usd")

    validate_error(
        api.deliver_delivery_order(
            spoiled_order["id"], {"excursion_minutes": 31}, LOGISTICS_COORDINATOR
        ),
        ApiErrorId.ERR_COLD_CHAIN_EXCURSION.value,
    )
    assert (
        fx.read_delivery_order(episode_id, spoiled_order["id"])["status"]
        == "OUT_FOR_DELIVERY"
    )


def test_controlled_handoff_without_a_witness_is_rejected(api):
    """PRD §3.6: "A controlled order must be handed off with a non-empty
    `witness_staff_id`; omitting it is `ERR_WITNESS_REQUIRED` at HTTP 422."
    PRD §3.6: "Completing the handoff moves the order `OUT_FOR_DELIVERY →
    DELIVERED` and accepts two optional body fields, `witness_staff_id` and
    `excursion_minutes`, which become mandatory in the two circumstances the
    program cares about."

    Design: Corner/validations/controlled_delivery_without_witness_returns_witness_required
    """
    parts = fx.setup_active_episode(
        primary_diagnosis_code="CELLULITIS",
        qualifying_condition_code="CELLULITIS",
        mrn="MRN-WT",
        full_name="Wes Witness",
    )
    episode_id = parts["episode"]["id"]

    controlled = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=True,
        cold_chain_required=False,
        weight_kg=0.5,
        requested_by_user_id="log-1",
    )
    plain = fx.raise_delivery_order(
        episode_id,
        order_kind="DME",
        is_controlled=False,
        cold_chain_required=False,
        weight_kg=0.5,
        requested_by_user_id="log-1",
    )
    for order in (controlled, plain):
        fx.authorize_order(order["id"], "pharm-9")
        fx.dispatch_order(order["id"])

    validate_error(
        api.deliver_delivery_order(controlled["id"], {}, COMMUNITY_PARAMEDIC),
        ApiErrorId.ERR_WITNESS_REQUIRED.value,
    )
    blocked = fx.read_delivery_order(episode_id, controlled["id"])
    assert blocked["status"] == "OUT_FOR_DELIVERY"
    assert blocked["witness_staff_id"] is None

    delivered = validate_success(
        api.deliver_delivery_order(plain["id"], {}, COMMUNITY_PARAMEDIC)
    )
    assert delivered["status"] == "DELIVERED", (
        "the witness rung fires only when is_controlled is true"
    )
    assert_money(delivered["handling_fee_usd"], 15.00, "handling_fee_usd")


def test_controlled_order_cannot_be_authorized_by_its_own_requester(api):
    """PRD §3.6: "When `is_controlled` is true, the authorizer's `X-User-ID` must
    differ from the order's `requested_by_user_id`; an identical value means the
    same human requested and approved a controlled substance, and it is refused
    with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."
    PRD §3.6: "Success moves the order `PENDING_AUTHORIZATION → AUTHORIZED`,
    writes the authorizer's identifier into `authorized_by_user_id`, and advances
    the order's `version` by 1."

    Design: Corner/rbac/controlled_order_authorized_by_its_own_requester_violates_segregation_of_duties
    """
    parts = fx.setup_active_episode(
        primary_diagnosis_code="CELLULITIS",
        qualifying_condition_code="CELLULITIS",
        mrn="MRN-SD",
        full_name="Sid Segregation",
    )
    episode_id = parts["episode"]["id"]

    order = fx.raise_delivery_order(
        episode_id,
        order_kind="MEDICATION",
        is_controlled=True,
        cold_chain_required=False,
        weight_kg=0.4,
        requested_by_user_id="pharm-9",
    )

    validate_error(
        api.authorize_delivery_order(
            order["id"], make_pharmacy_authorizer_headers("pharm-9")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    blocked = fx.read_delivery_order(episode_id, order["id"])
    assert blocked["status"] == "PENDING_AUTHORIZATION"
    assert blocked["authorized_by_user_id"] is None

    authorized = validate_success(
        api.authorize_delivery_order(
            order["id"], make_pharmacy_authorizer_headers("pharm-7")
        )
    )
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["authorized_by_user_id"] == "pharm-7"
