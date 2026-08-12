from flask import Blueprint, request

from db import stamp_new, store, touch
from envelope import ok, ok_list
from errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RATE_CARD_WINDOW_OVERLAP,
    ERR_STALE_RATE_CARD_VERSION,
    raise_err,
)
from security import ALL_READ, require_roles
from services import parse_d
from validators import (
    apply_filters,
    get_body,
    opt_date,
    opt_int,
    opt_num,
    paginate,
    req_date,
    req_int,
    req_num,
    req_str,
)
import serializers

bp = Blueprint("rate_cards", __name__)


def _get_card(card_id):
    card = store.rate_cards.get(card_id)
    if card is None:
        raise_err(ERR_NOT_FOUND, f"Rate card {card_id} not found.")
    return card


@bp.post("/v1/rate-cards")
def create_rate_card():
    require_roles("ProgramAdmin")
    body = get_body()
    rec = {
        "role_code": req_str(body, "role_code"),
        "skill_code": req_str(body, "skill_code"),
        "geo_code": req_str(body, "geo_code"),
        "currency": req_str(body, "currency"),
        "pay_rate_floor_cents": req_int(body, "pay_rate_floor_cents"),
        "bill_rate_ceiling_cents": req_int(body, "bill_rate_ceiling_cents"),
        "max_markup_pct": req_num(body, "max_markup_pct"),
        "effective_from": req_date(body, "effective_from"),
        "effective_to": req_date(body, "effective_to"),
        "status": "DRAFT",
        "supersedes_id": None,
    }
    stamp_new(rec)
    store.rate_cards[rec["id"]] = rec
    return ok(serializers.rate_card(rec), 201)


@bp.get("/v1/rate-cards")
def list_rate_cards():
    require_roles(*ALL_READ)
    filters = {
        "role_code": request.args.get("role_code"),
        "skill_code": request.args.get("skill_code"),
        "geo_code": request.args.get("geo_code"),
        "status": request.args.get("status"),
        "supersedes_id": request.args.get("supersedes_id"),
    }
    records = apply_filters(list(store.rate_cards.values()), filters)
    page, total, limit, offset = paginate(records, serializers.rate_card)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/rate-cards/<card_id>")
def get_rate_card(card_id):
    require_roles(*ALL_READ)
    return ok(serializers.rate_card(_get_card(card_id)))


@bp.post("/v1/rate-cards/<card_id>/activate")
def activate_rate_card(card_id):
    require_roles("ProgramAdmin")
    card = _get_card(card_id)
    if card["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT rate card can be activated.")
    new_from, new_to = parse_d(card["effective_from"]), parse_d(card["effective_to"])
    for other in store.rate_cards.values():
        if other["id"] == card["id"] or other["status"] != "ACTIVE":
            continue
        if (
            other["role_code"] == card["role_code"]
            and other["skill_code"] == card["skill_code"]
            and other["geo_code"] == card["geo_code"]
        ):
            o_from, o_to = parse_d(other["effective_from"]), parse_d(other["effective_to"])
            # half-open windows: touching at exactly one endpoint does not overlap
            if new_from < o_to and o_from < new_to:
                raise_err(
                    ERR_RATE_CARD_WINDOW_OVERLAP,
                    "Another ACTIVE rate card with the same key has an overlapping window.",
                )
    card["status"] = "ACTIVE"
    touch(card)
    return ok(serializers.rate_card(card))


@bp.post("/v1/rate-cards/<card_id>/retire")
def retire_rate_card(card_id):
    require_roles("ProgramAdmin")
    card = _get_card(card_id)
    if card["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE rate card can be retired.")
    card["status"] = "RETIRED"
    touch(card)
    return ok(serializers.rate_card(card))


@bp.post("/v1/rate-cards/<card_id>/revisions")
def revise_rate_card(card_id):
    require_roles("ProgramAdmin")
    body = get_body()
    expected = req_int(body, "expected_rate_card_version")
    floor = opt_int(body, "pay_rate_floor_cents")
    ceiling = opt_int(body, "bill_rate_ceiling_cents")
    markup = opt_num(body, "max_markup_pct")
    eff_from = opt_date(body, "effective_from")
    eff_to = opt_date(body, "effective_to")
    src = _get_card(card_id)
    if src["status"] not in ("ACTIVE", "DRAFT"):
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE or DRAFT rate card can be revised.")
    if expected != src["version"]:
        raise_err(
            ERR_STALE_RATE_CARD_VERSION,
            "expected_rate_card_version does not match the rate card's current version.",
        )
    rec = {
        "role_code": src["role_code"],
        "skill_code": src["skill_code"],
        "geo_code": src["geo_code"],
        "currency": src["currency"],
        "pay_rate_floor_cents": floor if floor is not None else src["pay_rate_floor_cents"],
        "bill_rate_ceiling_cents": ceiling if ceiling is not None else src["bill_rate_ceiling_cents"],
        "max_markup_pct": markup if markup is not None else src["max_markup_pct"],
        "effective_from": eff_from if eff_from is not None else src["effective_from"],
        "effective_to": eff_to if eff_to is not None else src["effective_to"],
        "status": "DRAFT",
        "supersedes_id": src["id"],
    }
    stamp_new(rec)
    store.rate_cards[rec["id"]] = rec
    touch(src)  # revising increments the source card's version by one
    return ok(serializers.rate_card(rec), 201)
