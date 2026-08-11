"""Weigh tickets, the governing ticket and the two settle-weight variants."""

from test_helpers import (
    ApiErrorId,
    YARD_OPERATOR,
    capture_weigh_ticket,
    check_in_consignment,
    create_consignment,
    create_lot,
    create_weigh_ticket_payload,
    open_weigh_ticket,
    read_lot,
    read_sale_day,
    read_scale,
    read_weigh_ticket,
    set_clock,
    setup_checked_in_consignment,
    setup_ready_lot,
    setup_yard,
    validate_error,
    validate_paginated,
    weigh_lot,
)


def _two_bases_scenario():
    """Two consignments with byte-identical scale readings on different bases.

    Consignment A weighs on PENCIL_SHRINK with one captured 7200/200 draft.
    Consignment B weighs on STAND_ACTUAL with a first captured 7200/200 draft and,
    240 minutes later, a second captured 7100/200 draft.
    """
    scn = setup_yard(with_pen=False)

    scn.consignment_a = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=10,
        weigh_basis="PENCIL_SHRINK",
        pencil_shrink_pct=0.03,
    )
    check_in_consignment(scn.consignment_a["id"])
    scn.lot_a = create_lot(scn.consignment_a["id"], head_count=10)
    scn.ticket_a = weigh_lot(
        scn.lot_a["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200
    )

    scn.consignment_b = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=10,
        weigh_basis="STAND_ACTUAL",
    )
    check_in_consignment(scn.consignment_b["id"])
    scn.lot_b = create_lot(scn.consignment_b["id"], head_count=10)
    scn.ticket_b1 = weigh_lot(
        scn.lot_b["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200
    )
    set_clock("2026-06-01T12:00:00Z")
    scn.ticket_b2 = weigh_lot(
        scn.lot_b["id"], scn.scale["id"], gross_weight_lb=7100, tare_weight_lb=200
    )
    return scn


def test_pencil_shrink_settle_weight_deducts_the_contractual_fraction(api):
    """PRD §3.4: "When the consignment weighs on a pencil-shrink basis, the settle
    weight is the governing ticket's net weight multiplied by one minus the
    consignment's `pencil_shrink_pct`, rounded half up to whole pounds."
    PRD §3.4: "From settle weight follow two derived fields: `avg_weight_lb` is the
    settle weight divided by `head_count`, rounded half up to one decimal place; and
    `weight_class` is `NONE` while there is no settle weight, `LIGHT` when the average
    weight is below 500.0 pounds, `MEDIUM` when it is at least 500.0 and below 800.0
    pounds, and `HEAVY` at 800.0 pounds and above."

    Design: Difficulty/dual_variant_calc/settle_weight_pencil_shrink_versus_stand_actual_on_lot_weight
    """
    scn = _two_bases_scenario()

    lot_a = read_lot(scn.lot_a["id"])
    assert lot_a["net_weight_lb"] == 7000
    assert lot_a["settle_weight_lb"] == 6790
    assert lot_a["avg_weight_lb"] == 679.0
    assert lot_a["weight_class"] == "MEDIUM"


def test_stand_actual_settle_weight_takes_the_governing_raw_net_weight(api):
    """PRD §3.4: "When it weighs on a stand-actual basis, no percentage is deducted at
    all and the governing ticket's raw net weight is the settle weight."
    PRD §3.4: "Any earlier ticket on the same lot that was `CAPTURED` transitions
    `CAPTURED → SUPERSEDED`, and the lot's weight fields are recomputed from the
    governing ticket — `gross_weight_lb`, `tare_weight_lb` and `net_weight_lb` are
    copied from it, and `settle_weight_lb`, `avg_weight_lb` and `weight_class` are
    derived."

    Design: Difficulty/dual_variant_calc/settle_weight_pencil_shrink_versus_stand_actual_on_lot_weight
    """
    scn = _two_bases_scenario()

    assert read_weigh_ticket(scn.ticket_b1["id"])["status"] == "SUPERSEDED"
    assert read_weigh_ticket(scn.ticket_b2["id"])["status"] == "CAPTURED"

    lot_b = read_lot(scn.lot_b["id"])
    assert lot_b["settle_weight_lb"] == 6900
    assert lot_b["avg_weight_lb"] == 690.0

    lot_a = read_lot(scn.lot_a["id"])
    assert lot_a["settle_weight_lb"] != lot_b["settle_weight_lb"], (
        "identical scale readings must settle differently under the two bases"
    )


def _expiring_scale_scenario():
    """A scale whose certification lapses between opening and capturing a draft."""
    scn = setup_yard(
        clock="2026-05-31T08:00:00Z",
        sale_date="2026-05-31",
        with_pen=False,
        scale_overrides={"certification_expires_on": "2026-05-31"},
    )
    scn.consignment = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=10, pencil_shrink_pct=0.03
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot = create_lot(scn.consignment["id"], head_count=10)
    scn.ticket_one = weigh_lot(
        scn.lot["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200
    )
    scn.ticket_two = open_weigh_ticket(
        scn.lot["id"], scn.scale["id"], gross_weight_lb=7100, tare_weight_lb=200
    )
    set_clock("2026-06-01T08:00:00Z")
    return scn


def test_capture_is_refused_once_the_scale_certification_has_lapsed(api):
    """PRD §3.4: "The scale is re-checked at capture time, so a scale whose
    certification lapsed between opening and capture stops the capture with
    `ERR_SCALE_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/weigh_ticket_capture_depends_on_scale_certification_state
    """
    scn = _expiring_scale_scenario()

    response = api.capture_weigh_ticket(scn.ticket_two["id"], YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_SCALE_NOT_CERTIFIED.value)

    ticket = read_weigh_ticket(scn.ticket_two["id"])
    assert ticket["status"] == "OPEN"
    assert ticket["captured_at"] is None


def test_scale_status_is_rederived_from_the_clock_and_the_expiry_day_is_inclusive(api):
    """PRD §3.1: "A scale's `status` is not stored but derived on every read against
    the logical clock: it is `CERTIFIED` when the clock's date falls on or after
    `certified_from` and on or before `certification_expires_on` — both bounds
    inclusive, so a scale is still good on the exact day printed as its expiry — and
    `EXPIRED` otherwise."
    PRD §2.4: "Moving the clock immediately re-derives every scale's certification
    standing and every inspection-validity comparison; nothing is cached against the
    old instant."

    Design: Difficulty/cross_entity_state_dependency/weigh_ticket_capture_depends_on_scale_certification_state
    """
    scn = _expiring_scale_scenario()

    assert read_scale(scn.scale["id"])["status"] == "EXPIRED"
    assert read_weigh_ticket(scn.ticket_one["id"])["status"] == "CAPTURED", (
        "the first draft was captured on the expiry date itself, which is inclusive"
    )
    assert read_lot(scn.lot["id"])["settle_weight_lb"] == 6790


def test_second_open_draft_on_the_same_lot_is_refused(api):
    """PRD §3.4: "the lot must not already have another ticket sitting in `OPEN` or
    the answer is `ERR_WEIGH_TICKET_OPEN`; and the lot's re-weigh count — its ticket
    count less one — must be below 2, so that the third re-weigh is refused with
    `ERR_REWEIGH_LIMIT_EXCEEDED`."

    Design: Corner/validations/corner_second_open_weigh_ticket_on_same_lot_is_rejected
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False)
    lot = create_lot(scn.consignment["id"], head_count=10)
    first = open_weigh_ticket(
        lot["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200
    )

    response = api.create_weigh_ticket(
        create_weigh_ticket_payload(
            lot["id"], scn.scale["id"], gross_weight_lb=7100, tare_weight_lb=200
        ),
        YARD_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_WEIGH_TICKET_OPEN.value)

    assert read_weigh_ticket(first["id"])["status"] == "OPEN"
    _, meta = validate_paginated(
        api.list_weigh_tickets(YARD_OPERATOR, params={"lot_id": lot["id"]})
    )
    assert meta["total_count"] == 1


def test_stand_actual_reweigh_captured_before_the_stand_time_is_refused(api):
    """PRD §3.4: "For a consignment weighing on a stand-actual basis, a re-weigh —
    any ticket whose `ticket_seq` is greater than 1 — may only be captured once at
    least 240 minutes have elapsed since the governing prior captured ticket's
    `captured_at`; an elapsed time of exactly 240 minutes passes, and anything shorter
    is refused with `ERR_STAND_TIME_NOT_MET`."

    Design: Corner/validations/corner_stand_actual_reweigh_captured_before_stand_time_is_rejected
    """
    scn = setup_checked_in_consignment(
        head_received=10,
        with_pen=False,
        consignment_overrides={"weigh_basis": "STAND_ACTUAL"},
    )
    lot = create_lot(scn.consignment["id"], head_count=10)
    first = weigh_lot(lot["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    second = open_weigh_ticket(
        lot["id"], scn.scale["id"], gross_weight_lb=7100, tare_weight_lb=200
    )
    set_clock("2026-06-01T11:59:00Z")

    response = api.capture_weigh_ticket(second["id"], YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_STAND_TIME_NOT_MET.value)

    assert read_weigh_ticket(second["id"])["status"] == "OPEN"
    assert read_weigh_ticket(first["id"])["status"] == "CAPTURED"
    assert read_lot(lot["id"])["settle_weight_lb"] == 7000, (
        "no pencil shrink is applied on the stand-actual basis"
    )


def test_mark_ready_without_a_settle_weight_is_refused(api):
    """PRD §3.8: "Marking it ready is the `PENNED → READY` transition, and it demands
    a non-null `settle_weight_lb` — a lot with no weight behind it is refused with
    `ERR_SETTLE_WEIGHT_MISSING` — plus the class-specific health test of §3.6."
    PRD §3.8: "On success the lot takes its `ring_order` from the sale day's
    `next_ring_order`, which then advances by 10, so the first lot marked ready on a
    fresh sale day is ring order 10, the second 20, and so on."

    Design: Corner/state_machines/corner_mark_ready_without_settle_weight_is_rejected
    """
    scn = setup_ready_lot(head_received=10, head_count=10, weigh=False, ready=False)

    response = api.mark_lot_ready(scn.lot["id"], YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_SETTLE_WEIGHT_MISSING.value)

    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "PENNED"
    assert lot["ring_order"] is None

    assert read_sale_day(scn.sale_day["id"])["next_ring_order"] == 10
