"""Public representations.  Computed mirrors are derived at read time."""

import calc
import store
from store import public


def room_view(rec):
    return public(rec, {"occupied_slots": occupied_slots(rec)})


def occupied_slots(room):
    """FinishRuns in this booth whose closed booth hold contains the clock."""
    now = store.now_utc()
    count = 0
    for run in store.RUNS.values():
        if run["booth_id"] != room["id"]:
            continue
        if run["status"] not in ("SPRAYING", "CURING", "CURE_SUSPENDED",
                                "BUFFING"):
            continue
        if run["booth_hold_from"] <= now <= run["booth_hold_until"]:
            count += 1
    return count


def lot_view(rec):
    return public(rec, {
        "board_feet_cut": calc.board_feet_cut_mirror(rec),
        "nominal_yield_board_feet": calc.nominal_yield(rec),
        "actual_yield_board_feet": calc.actual_yield(rec),
    })


def billet_view(rec):
    return public(rec)


def spec_view(rec):
    return public(rec)


def component_view(rec):
    return public(rec)


def station_view(rec):
    return public(rec)


def reservation_view(rec):
    return public(rec)


def option_view(rec):
    return public(rec)


def order_view(rec):
    return public(rec)


def selection_view(rec):
    return public(rec)


def run_view(rec):
    return public(rec)


def inspection_view(rec):
    return public(rec)


def shop_view(rec):
    active = sum(1 for w in store.WARRANTIES.values()
                 if w["registering_shop_id"] == rec["id"]
                 and w["status"] == "ACTIVE")
    return public(rec, {"warranty_claim_count": active})


def warranty_view(rec):
    return public(rec)


def shipment_view(rec):
    return public(rec)
