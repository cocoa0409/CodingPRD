"""Booth posture as the universal gate: the suspension cascade that freezes a
booth, holds its pending order and cancels the attached crew; the freight hold
that restricts a booth and blocks dispatch; the reinstatement that unwinds the
freeze exactly one level; and the clause ordering that makes a freezing clause
outrank a restricting one."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_booth,
    assert_exhibitor,
    assert_labor_call,
    assert_posture,
    assert_service_order,
    assert_show,
    complete_labor_call,
    dispatch_labor_call,
    get_booth,
    get_exhibitor,
    get_labor_call,
    get_order,
    get_show,
    register_crate,
    receive_shipment,
    reinstate_exhibitor,
    request_labor_call,
    set_shipment_hold,
    setup_order_ground,
    setup_requested_labor_call,
    suspend_exhibitor,
    validate_error,
)

LABOR = TEST_USERS["labor_supervisor_headers"]

# The rigging craft every scenario below books its crew from.
RIGGING_JURISDICTION = {
    "trade": "RIGGING",
    "straight_time_rate_cents_per_hour": 14000,
    "overtime_multiplier": 1.5,
    "doubletime_multiplier": 2.0,
    "min_call_hours": 4,
    "crew_max_size": 6,
    "exhibitor_self_install_allowed": False,
    "turnaround_buffer_minutes": 30,
}


def _ground_with_pending_order_and_attached_call():
    """ON_SITE show, OPEN booth, one PENDING service order, and one REQUESTED
    call of four riggers carrying `service_order_id` so the suspension cascade
    reaches it through the order it fulfils."""
    ground = setup_order_ground(show_status="ON_SITE",
                                with_jurisdiction=True,
                                jurisdiction_overrides=RIGGING_JURISDICTION)
    ground["labor_call"] = request_labor_call(
        ground["booth"]["id"], ground["jurisdiction"]["id"],
        service_order_id=ground["order"]["id"], crew_size=4)
    return ground


def _ground_with_freight_hold():
    """ON_SITE show with one REQUESTED call, plus a DIRECT_TO_SHOW receipt for
    the same exhibitor and show carrying a raised hold."""
    ground = setup_requested_labor_call(
        show_status="ON_SITE",
        jurisdiction_overrides=RIGGING_JURISDICTION,
        with_warehouse=True,
        warehouse_overrides={"dock_capacity_cwt": 300},
        call_overrides={"crew_size": 4})
    crate = register_crate(ground["exhibitor"]["id"], weight_lbs=1250)
    ground["shipment"] = receive_shipment(
        ground["show"]["id"], ground["exhibitor"]["id"], [crate["id"]],
        warehouse_id=ground["warehouse"]["id"],
        channel="DIRECT_TO_SHOW",
        received_at="2026-09-20T10:00:00Z",
        dock_window_start="2026-09-20T09:00:00Z",
        dock_window_end="2026-09-20T11:00:00Z",
        declared_value_coverage=False)
    ground["shipment"] = set_shipment_hold(ground["shipment"]["id"], True,
                                           reason="Bill of lading missing")
    return ground


# --- exhibitor suspension: booth freeze and order hold

def test_suspension_freezes_booth_and_holds_pending_service_order():
    """PRD §3.2: "A `FinanceController` may move an exhibitor's `status` between
    `ACTIVE` and `SUSPENDED` by naming a `to_status`, optionally supplying a
    `reason` that is captured verbatim into `suspension_reason` when the account
    becomes `SUSPENDED`."
    PRD §3.2: "Suspension is the sharpest instrument in the system, and it fires
    a four-link chain: the exhibitor's `status` becomes `SUSPENDED`; every booth
    that exhibitor holds recomputes posture and, because the suspension clause
    outranks everything, lands on `FROZEN` with `posture_reason`
    `EXHIBITOR_SUSPENDED`; every service order on those booths whose
    `fulfillment_status` is `PENDING` moves to `HELD`; and every labor call
    attached to one of those held orders whose `status` is `REQUESTED` moves to
    `CANCELLED`, which in turn recomputes that show's `cancelled_labor_call_count`
    and its `committed_labor_hours`."
    PRD §2.10: "1. The booth's exhibitor has `status` `SUSPENDED` — posture
    `FROZEN`, reason `EXHIBITOR_SUSPENDED`."

    Design: Difficulty/transitive_cascade/exhibitor_suspension_freezes_booth_holds_order_cancels_labor
    """
    ground = _ground_with_pending_order_and_attached_call()
    assert get_order(ground["order"]["id"])["fulfillment_status"] == "PENDING", \
        "Setup failed: the order must sit in PENDING before the suspension"
    assert_posture(get_booth(ground["booth"]["id"]), "OPEN", None)

    suspend_exhibitor(ground["exhibitor"]["id"], reason="Credit review pending")

    exhibitor = get_exhibitor(ground["exhibitor"]["id"])
    assert_exhibitor(exhibitor)
    assert exhibitor["status"] == "SUSPENDED", \
        f"Link 1: the exhibitor must land on SUSPENDED, got {exhibitor['status']}"
    assert exhibitor["suspension_reason"] == "Credit review pending", \
        ("The supplied reason is captured verbatim into suspension_reason, got "
         f"{exhibitor['suspension_reason']}")

    booth = get_booth(ground["booth"]["id"])
    assert_booth(booth)
    assert_posture(booth, "FROZEN", "EXHIBITOR_SUSPENDED")

    order = get_order(ground["order"]["id"])
    assert_service_order(order)
    assert order["fulfillment_status"] == "HELD", \
        ("Link 3: a PENDING order on a booth the suspension froze moves to HELD, "
         f"got {order['fulfillment_status']}")
    assert order["billing_status"] == "UNBILLED", \
        ("The hold is operational only and leaves billing_status at UNBILLED, got "
         f"{order['billing_status']}")


def test_suspension_cascade_cancels_requested_labor_call_and_recomputes_show_counters():
    """PRD §3.2: "Suspension is the sharpest instrument in the system, and it
    fires a four-link chain: the exhibitor's `status` becomes `SUSPENDED`; every
    booth that exhibitor holds recomputes posture and, because the suspension
    clause outranks everything, lands on `FROZEN` with `posture_reason`
    `EXHIBITOR_SUSPENDED`; every service order on those booths whose
    `fulfillment_status` is `PENDING` moves to `HELD`; and every labor call
    attached to one of those held orders whose `status` is `REQUESTED` moves to
    `CANCELLED`, which in turn recomputes that show's `cancelled_labor_call_count`
    and its `committed_labor_hours`."
    PRD §3.5: "An order in `PENDING` moves to `HELD` purely as a cascade when its
    booth's posture becomes `FROZEN`, whether through exhibitor suspension or a
    credit-limit breach; that same cascade cancels every labor call on the order
    that was still `REQUESTED`, then recomputes the show's
    `cancelled_labor_call_count` and its `committed_labor_hours`."
    PRD §3.7: "Calls still `REQUESTED` are not yet committed, and calls that have
    reached `COMPLETED`, `NO_SHOW` or `CANCELLED` are no longer committed."

    Design: Difficulty/transitive_cascade/exhibitor_suspension_freezes_booth_holds_order_cancels_labor
    """
    ground = _ground_with_pending_order_and_attached_call()
    show_before = get_show(ground["show"]["id"])
    assert show_before["cancelled_labor_call_count"] == 0, \
        "Setup failed: no call has been cancelled yet"
    assert get_labor_call(ground["labor_call"]["id"])["status"] == "REQUESTED", \
        "Setup failed: the call must still be REQUESTED before the suspension"

    suspend_exhibitor(ground["exhibitor"]["id"], reason="Credit review pending")

    assert_posture(get_booth(ground["booth"]["id"]), "FROZEN", "EXHIBITOR_SUSPENDED")
    assert get_order(ground["order"]["id"])["fulfillment_status"] == "HELD", \
        "The cancellation of the call runs off the order the freeze drove to HELD"

    call = get_labor_call(ground["labor_call"]["id"])
    assert_labor_call(call)
    assert call["status"] == "CANCELLED", \
        ("Link 4: a REQUESTED call attached to the held order is cancelled, got "
         f"{call['status']}")

    show = get_show(ground["show"]["id"])
    assert_show(show)
    assert show["cancelled_labor_call_count"] == 1, \
        ("The cascade lifts cancelled_labor_call_count to 1, got "
         f"{show['cancelled_labor_call_count']}")
    assert show["committed_labor_hours"] == pytest.approx(0, abs=0.01), \
        ("A merely REQUESTED call never contributed, so committed_labor_hours "
         f"stays at 0, got {show['committed_labor_hours']}")


# --- freight hold: RESTRICTED booth gates the dispatch edge

def test_freight_hold_restricts_booth_and_blocks_labor_dispatch(api):
    """PRD §3.6: "A raised hold drives every booth of that shipment's exhibitor
    on that shipment's show to recompute posture, which lands them on
    `RESTRICTED` with `posture_reason` `FREIGHT_HOLD` unless a freezing clause
    outranks it; lifting the hold recomputes them again."
    PRD §2.10: "6. At least one drayage shipment matching this booth's exhibitor
    and this booth's show carries `hold_flag` true — posture `RESTRICTED`, reason
    `FREIGHT_HOLD`."
    PRD §3.7: "It requires the booth's posture to be exactly `OPEN` — a booth that
    a previous no-show has driven to `RESTRICTED` cannot take a new crew, and is
    refused with `ERR_BOOTH_RESTRICTED` — and requires the show to be in
    `MOVE_IN`, `ON_SITE` or `MOVE_OUT`, or the request is refused with
    `ERR_SHOW_NOT_ACCEPTING`."

    Design: Difficulty/cross_entity_state_dependency/labor_dispatch_gated_by_booth_posture_restricted
    """
    ground = _ground_with_freight_hold()
    assert ground["shipment"]["hold_flag"] is True, \
        "Setup failed: the drayage receipt must carry a raised hold"

    booth = get_booth(ground["booth"]["id"])
    assert_booth(booth)
    assert_posture(booth, "RESTRICTED", "FREIGHT_HOLD")

    resp = api.dispatch_labor_call(ground["labor_call"]["id"], LABOR)
    validate_error(resp, ApiErrorId.ERR_BOOTH_RESTRICTED, 409)


def test_restricted_dispatch_refusal_leaves_call_requested_and_hours_uncommitted(api):
    """PRD §2.9: "15. The booth reached from the target is not `RESTRICTED`, for
    the narrower set of operations that `RESTRICTED` also blocks — otherwise
    `ERR_BOOTH_RESTRICTED` (409). Applies to `POST /labor-calls/{id}/dispatch`
    and to `POST /exhibit-designs/{id}/decision` when the decision is `APPROVE`."
    PRD §3.7: "`Show.committed_labor_hours` is a full recomputation over the
    show's calls: it sums, for every labor call reachable through a booth of this
    show whose `status` is `DISPATCHED` or `ON_SITE`, that call's `crew_size`
    multiplied by its `scheduled_hours`, with the final sum rounded half up to two
    decimal places."
    PRD §3.7: "Calls still `REQUESTED` are not yet committed, and calls that have
    reached `COMPLETED`, `NO_SHOW` or `CANCELLED` are no longer committed."

    Design: Difficulty/cross_entity_state_dependency/labor_dispatch_gated_by_booth_posture_restricted
    """
    ground = _ground_with_freight_hold()
    assert_posture(get_booth(ground["booth"]["id"]), "RESTRICTED", "FREIGHT_HOLD")

    resp = api.dispatch_labor_call(ground["labor_call"]["id"], LABOR)
    validate_error(resp, ApiErrorId.ERR_BOOTH_RESTRICTED, 409)

    call = get_labor_call(ground["labor_call"]["id"])
    assert_labor_call(call)
    assert call["status"] == "REQUESTED", \
        ("A refused dispatch leaves the call on the REQUESTED side of the edge, "
         f"got {call['status']}")

    show = get_show(ground["show"]["id"])
    assert_show(show)
    assert show["committed_labor_hours"] == pytest.approx(0, abs=0.01), \
        ("Crew-hours become a commitment only on a dispatch that succeeds, got "
         f"{show['committed_labor_hours']}")

    assert_posture(get_booth(ground["booth"]["id"]), "RESTRICTED", "FREIGHT_HOLD")


# --- reinstatement unwinds the freeze exactly one level

def test_reinstatement_releases_held_order_without_resurrecting_cancelled_call():
    """PRD §3.2: "Reinstating the exhibitor to `ACTIVE` walks the chain back only
    as far as it honestly can: postures are recomputed, and orders that were
    driven to `HELD` return to `PENDING` once their booth is no longer `FROZEN` —
    but cancelled labor calls are not resurrected, because a crew that was
    released has been released."
    PRD §3.5: "The compensating move restores the fulfillment dimension only: the
    cancelled labor calls stay cancelled."
    PRD §2.10: "When no clause holds, `posture` is `OPEN` and `posture_reason` is
    null."

    Design: Corner/state_machines/reinstating_exhibitor_releases_held_orders_without_resurrecting_calls
    """
    ground = _ground_with_pending_order_and_attached_call()
    suspend_exhibitor(ground["exhibitor"]["id"], reason="Credit review")

    frozen_booth = get_booth(ground["booth"]["id"])
    assert_posture(frozen_booth, "FROZEN", "EXHIBITOR_SUSPENDED")
    assert get_order(ground["order"]["id"])["fulfillment_status"] == "HELD", \
        "Setup failed: the freeze must have driven the order to HELD"
    assert get_labor_call(ground["labor_call"]["id"])["status"] == "CANCELLED", \
        "Setup failed: the hold must have cancelled the requested call"

    reinstate_exhibitor(ground["exhibitor"]["id"])

    exhibitor = get_exhibitor(ground["exhibitor"]["id"])
    assert_exhibitor(exhibitor)
    assert exhibitor["status"] == "ACTIVE", \
        f"Reinstatement returns the account to ACTIVE, got {exhibitor['status']}"

    booth = get_booth(ground["booth"]["id"])
    assert_booth(booth)
    assert_posture(booth, "OPEN", None)

    order = get_order(ground["order"]["id"])
    assert_service_order(order)
    assert order["fulfillment_status"] == "PENDING", \
        ("An order driven to HELD returns to PENDING once its booth stops being "
         f"FROZEN, got {order['fulfillment_status']}")

    call = get_labor_call(ground["labor_call"]["id"])
    assert call["status"] == "CANCELLED", \
        ("A released crew is never resurrected: the call stays CANCELLED, got "
         f"{call['status']}")

    show = get_show(ground["show"]["id"])
    assert_show(show)
    assert show["cancelled_labor_call_count"] == 1, \
        ("The cancellation counter is not walked back by reinstatement, got "
         f"{show['cancelled_labor_call_count']}")


# --- clause ordering: a freezing clause outranks a restricting one

def test_suspension_freeze_outranks_no_show_restriction():
    """PRD §2.10: "The clauses are evaluated in a fixed order and the first one
    that holds wins, fixing both `posture` and `posture_reason`."
    PRD §2.10: "Every freezing clause outranks every restricting clause:"
    PRD §2.10: "1. The booth's exhibitor has `status` `SUSPENDED` — posture
    `FROZEN`, reason `EXHIBITOR_SUSPENDED`."
    PRD §2.10: "5. At least one labor call on this booth has `status` `NO_SHOW` —
    posture `RESTRICTED`, reason `LABOR_NO_SHOW`."
    PRD §3.7: "The show's committed crew-hours are recomputed downward, and the
    booth recomputes posture, landing on `RESTRICTED` with `posture_reason`
    `LABOR_NO_SHOW` unless a freezing clause outranks it — which is why a no-show
    blocks the next dispatch at that booth until the situation is resolved."

    Design: Corner/calculations/posture_frozen_clause_outranks_restricted_clause
    """
    ground = setup_requested_labor_call(
        show_status="ON_SITE",
        jurisdiction_overrides=RIGGING_JURISDICTION,
        call_overrides={"crew_size": 4})
    dispatch_labor_call(ground["labor_call"]["id"])
    no_show_call = complete_labor_call(ground["labor_call"]["id"], "NO_SHOW")
    assert no_show_call["status"] == "NO_SHOW", \
        f"Setup failed: the call must close as NO_SHOW, got {no_show_call['status']}"

    booth_before = get_booth(ground["booth"]["id"])
    assert_booth(booth_before)
    assert_posture(booth_before, "RESTRICTED", "LABOR_NO_SHOW")

    suspend_exhibitor(ground["exhibitor"]["id"], reason="Credit review")

    booth = get_booth(ground["booth"]["id"])
    assert_booth(booth)
    assert booth["posture"] == "FROZEN", \
        ("The suspension clause is reached before the no-show clause, so the booth "
         f"is FROZEN rather than RESTRICTED, got {booth['posture']}")
    assert booth["posture_reason"] == "EXHIBITOR_SUSPENDED", \
        ("posture_reason names the single highest-priority clause that held, so "
         f"EXHIBITOR_SUSPENDED wins over LABOR_NO_SHOW, got {booth['posture_reason']}")
    assert_posture(booth, "FROZEN", "EXHIBITOR_SUSPENDED")
