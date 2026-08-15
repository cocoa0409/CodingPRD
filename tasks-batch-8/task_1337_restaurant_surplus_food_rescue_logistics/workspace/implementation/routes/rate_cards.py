"""RateCard endpoints."""
from flask import Blueprint

from db import DB, STATE, new_id
from errors import ApiError
from middleware import auth
from response import ok
from services import _intervals_conflict, ser_rate_card, stamp
from util import as_int, as_iso_dt, body, parse_dt, reject_unknown, required

bp = Blueprint("rate_cards", __name__)

RATE_FIELDS = (
    "cold_held_fmv_cents_per_lb",
    "cold_held_basis_cents_per_lb",
    "hot_held_fmv_cents_per_lb",
    "hot_held_basis_cents_per_lb",
    "produce_fmv_cents_per_lb",
    "produce_basis_cents_per_lb",
    "shelf_stable_fmv_cents_per_lb",
    "shelf_stable_basis_cents_per_lb",
)


@bp.post("/api/rate-cards")
def create_rate_card():
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"effective_start", "effective_end"} | set(RATE_FIELDS))
    effective_start = as_iso_dt(required(data, "effective_start"), "effective_start")
    effective_end = as_iso_dt(required(data, "effective_end"), "effective_end")
    rates = {f: as_int(required(data, f), f) for f in RATE_FIELDS}
    s = parse_dt(effective_start)
    e = parse_dt(effective_end)
    if e <= s:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "effective_end must be after effective_start"
        )
    for card in DB["rate_cards"].values():
        if _intervals_conflict(
            s, e, parse_dt(card["effective_start"]), parse_dt(card["effective_end"])
        ):
            raise ApiError(
                "ERR_RATE_CARD_WINDOW_OVERLAP", 409,
                "Effective window overlaps an existing rate card",
            )
    rec = {
        "id": new_id(),
        "effective_start": effective_start,
        "effective_end": effective_end,
        "card_version": STATE["next_card_version"],
    }
    rec.update(rates)
    # Monotonic version, consumed only by successful creations.
    STATE["next_card_version"] += 1
    stamp(rec)
    DB["rate_cards"][rec["id"]] = rec
    return ok(ser_rate_card(rec), status=201)
