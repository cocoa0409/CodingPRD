"""Production routes (PRD 3.2) — cyclic lifecycle state machine."""

from flask import Blueprint

from db import store
from errors import (ERR_INVALID_STATE, ERR_ITEMS_NOT_DELIVERED,
                    ERR_NO_PERFORMANCES, ERR_OPEN_COMMITMENTS, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from util import json_body, new_record, req_enum, req_int, req_str, to_public, touch

bp = Blueprint("productions", __name__)

WORK_TYPES = ("OPERA", "BALLET")
TARGET_STATES = ("BUILD", "REHEARSAL", "IN_REPERTORY", "ARCHIVED")
OPEN_OFFER_STATES = ("DRAFT", "SENT", "COUNTERED", "ACCEPTED")


@bp.post("/opera/productions")
def create_production():
    require_roles("ProductionManager")
    body = json_body()
    title = req_str(body, "title")
    work_type = req_enum(body, "work_type", WORK_TYPES)
    budget = req_int(body, "build_budget_cents", min_value=1)
    lang = req_str(body, "default_surtitle_language")
    rec = new_record(
        title=title,
        work_type=work_type,
        build_budget_cents=budget,
        default_surtitle_language=lang,
        build_cost_balance_cents=budget,
        season_revenue_cents=0,
        status="DESIGN",
    )
    store.productions[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/productions")
def list_productions():
    require_roles("Any")
    return list_response(store.productions.values(), [("status", "status")])


@bp.get("/opera/productions/<pid>")
def get_production(pid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.productions, pid, "Production")))


@bp.post("/opera/productions/<pid>/transition")
def transition_production(pid):
    require_roles("ProductionManager")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    prod = get_or_404(store.productions, pid, "Production")
    cur = prod["status"]

    if cur == "DESIGN" and to_state == "BUILD":
        pass
    elif cur == "BUILD" and to_state == "REHEARSAL":
        # Every non-cancelled build item must be DELIVERED or IN_USE
        # (vacuously true when no build items exist).
        for it in store.build_items.values():
            if it["production_id"] != prod["id"]:
                continue
            if it["status"] != "CANCELLED" and it["status"] not in ("DELIVERED", "IN_USE"):
                raise conflict(
                    ERR_ITEMS_NOT_DELIVERED,
                    "All non-cancelled build items must be DELIVERED or IN_USE")
    elif cur == "REHEARSAL" and to_state == "BUILD":
        pass  # rework loop
    elif cur == "REHEARSAL" and to_state == "IN_REPERTORY":
        if not any(p["production_id"] == prod["id"] for p in store.performances.values()):
            raise conflict(ERR_NO_PERFORMANCES,
                           "At least one performance must exist")
    elif cur == "IN_REPERTORY" and to_state == "ARCHIVED":
        open_offer = any(
            o["production_id"] == prod["id"] and o["status"] in OPEN_OFFER_STATES
            for o in store.rental_offers.values())
        scheduled_perf = any(
            p["production_id"] == prod["id"] and p["lifecycle_status"] == "SCHEDULED"
            for p in store.performances.values())
        if open_offer or scheduled_perf:
            raise conflict(ERR_OPEN_COMMITMENTS,
                           "Production has open rental offers or scheduled performances")
    else:
        raise conflict(ERR_INVALID_STATE,
                       f"Production cannot transition {cur} -> {to_state}")

    prod["status"] = to_state
    touch(prod)
    return ok_object(to_public(prod))
