from flask import Blueprint

from auth import parse_auth, require_role
from db import store
from envelope import ok, paginate
from errors import (not_found, conflict, invalid_request, ERR_INVALID_STATE,
                    ERR_OPERATING_DAY_EXISTS, ERR_PRICE_DECK_INCOMPLETE,
                    ERR_UNRESOLVED_DISPUTES)
from util import (get_body, check_unknown, req_string, req_datetime, new_record,
                  serialize, sort_key, touch)
from services import settlement
from services.credit import refresh_credit

bp = Blueprint("operating_days", __name__)

ISO = ["IsoOperator"]


def get_day(day_id):
    d = store.operating_days.get(day_id)
    if d is None:
        raise not_found("operating day not found")
    return d


def _validate_price_entries(body, deck_field, component_fields):
    if deck_field not in body:
        raise invalid_request("field %s is required" % deck_field)
    deck = body[deck_field]
    if not isinstance(deck, list):
        raise invalid_request("field %s must be a list" % deck_field)
    entries = []
    seen = set()
    for entry in deck:
        if not isinstance(entry, dict):
            raise invalid_request("price deck entries must be objects")
        check_unknown(entry, {"node_name"} | set(component_fields))
        name = entry.get("node_name")
        if not isinstance(name, str) or not name.strip():
            raise invalid_request("price deck entries require node_name")
        if name in seen:
            raise invalid_request("duplicate node_name in price deck")
        seen.add(name)
        comps = {}
        for cf in component_fields:
            v = entry.get(cf)
            if isinstance(v, bool) or not isinstance(v, int):
                raise invalid_request("field %s must be an integer" % cf)
            comps[cf] = v
        entries.append((name, comps))
    return entries


@bp.post("/market/operating-days")
def create_day():
    auth = parse_auth()
    require_role(auth, ISO)
    body = get_body()
    check_unknown(body, {"market_date", "da_gate_close_at"})
    market_date = req_string(body, "market_date")
    from util import parse_date
    if parse_date(market_date) is None:
        raise invalid_request("market_date must be a YYYY-MM-DD date")
    raw_gate, gate_dt = req_datetime(body, "da_gate_close_at")
    if any(d["market_date"] == market_date for d in store.operating_days.values()):
        raise conflict(ERR_OPERATING_DAY_EXISTS,
                       "an operating day with this market_date already exists")
    rec = new_record()
    rec.update({
        "market_date": market_date,
        "da_gate_close_at": raw_gate,
        "_gate_dt": gate_dt,
        "status": "DA_OPEN",
    })
    store.operating_days[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.get("/market/operating-days/<operatingDayId>")
def get_one(operatingDayId):
    parse_auth()
    return ok(serialize(get_day(operatingDayId)))


@bp.get("/market/operating-days/<operatingDayId>/price-nodes")
def list_price_nodes(operatingDayId):
    parse_auth()
    day = get_day(operatingDayId)
    rows = sorted((n for n in store.price_nodes.values()
                   if n["operating_day_id"] == day["id"]), key=sort_key)
    return paginate([serialize(r) for r in rows])


@bp.post("/market/operating-days/<operatingDayId>/run-day-ahead-market")
def run_day_ahead(operatingDayId):
    auth = parse_auth()
    require_role(auth, ISO)
    body = get_body()
    check_unknown(body, {"node_prices"})
    entries = _validate_price_entries(
        body, "node_prices",
        ["da_energy_cents_per_mwh", "da_congestion_cents_per_mwh",
         "da_loss_cents_per_mwh"])
    day = get_day(operatingDayId)
    if day["status"] != "DA_OPEN":
        raise conflict(ERR_INVALID_STATE,
                       "day-ahead market can only run while DA_OPEN")
    # deck must cover the pricing_node of every SUBMITTED offer on this day
    deck_names = {name for name, _ in entries}
    for offer in settlement.day_offers(day["id"]):
        if offer["status"] == "SUBMITTED":
            gen = store.generators[offer["generator_asset_id"]]
            if gen["pricing_node"] not in deck_names:
                raise conflict(ERR_PRICE_DECK_INCOMPLETE,
                               "price deck lacks node %s" % gen["pricing_node"])
    for name, comps in entries:
        node = new_record()
        node.update({
            "operating_day_id": day["id"],
            "node_name": name,
            "da_energy_cents_per_mwh": comps["da_energy_cents_per_mwh"],
            "da_congestion_cents_per_mwh": comps["da_congestion_cents_per_mwh"],
            "da_loss_cents_per_mwh": comps["da_loss_cents_per_mwh"],
            "rt_prelim_energy_cents_per_mwh": None,
            "rt_prelim_congestion_cents_per_mwh": None,
            "rt_prelim_loss_cents_per_mwh": None,
            "rt_final_energy_cents_per_mwh": None,
            "rt_final_congestion_cents_per_mwh": None,
            "rt_final_loss_cents_per_mwh": None,
        })
        store.price_nodes[node["id"]] = node
    settlement.run_da_clearing(day)
    day["status"] = "DA_GATED"
    touch(day)
    return ok(serialize(day))


@bp.post("/market/operating-days/<operatingDayId>/close-real-time")
def close_real_time(operatingDayId):
    auth = parse_auth()
    require_role(auth, ISO)
    body = get_body()
    check_unknown(body, {"rt_node_prices_prelim"})
    entries = _validate_price_entries(
        body, "rt_node_prices_prelim",
        ["rt_prelim_energy_cents_per_mwh", "rt_prelim_congestion_cents_per_mwh",
         "rt_prelim_loss_cents_per_mwh"])
    day = get_day(operatingDayId)
    if day["status"] != "DA_GATED":
        raise conflict(ERR_INVALID_STATE,
                       "real time can only close while DA_GATED")
    for name, comps in entries:
        node = settlement.node_for(day["id"], name)
        if node is None:
            continue
        node.update(comps)
        touch(node)
    day["status"] = "RT_COMPLETE"
    touch(day)
    return ok(serialize(day))


@bp.post("/market/operating-days/<operatingDayId>/run-preliminary-settlement")
def run_preliminary(operatingDayId):
    auth = parse_auth()
    require_role(auth, ISO)
    get_body()
    day = get_day(operatingDayId)
    if day["status"] != "RT_COMPLETE":
        raise conflict(ERR_INVALID_STATE,
                       "preliminary settlement requires RT_COMPLETE")
    # settle awards first so statement ancillary revenue is available
    for award in sorted((a for a in store.awards.values()
                         if a["operating_day_id"] == day["id"] and a["status"] == "AWARDED"),
                        key=sort_key):
        settlement.score_and_settle_award(award, day["id"])
    settlement.generate_statements(day, "PRELIMINARY", "preliminary")
    day["status"] = "PRELIM_SETTLED"
    touch(day)
    return ok(serialize(day))


@bp.post("/market/operating-days/<operatingDayId>/run-final-settlement")
def run_final(operatingDayId):
    auth = parse_auth()
    require_role(auth, ISO)
    body = get_body()
    check_unknown(body, {"rt_node_prices_final"})
    entries = _validate_price_entries(
        body, "rt_node_prices_final",
        ["rt_final_energy_cents_per_mwh", "rt_final_congestion_cents_per_mwh",
         "rt_final_loss_cents_per_mwh"])
    day = get_day(operatingDayId)
    if day["status"] != "PRELIM_SETTLED":
        raise conflict(ERR_INVALID_STATE,
                       "final settlement requires PRELIM_SETTLED")
    for name, comps in entries:
        node = settlement.node_for(day["id"], name)
        if node is None:
            continue
        node.update(comps)
        touch(node)
    for stmt in sorted((s for s in store.statements.values()
                        if s["operating_day_id"] == day["id"]
                        and s["run_type"] == "PRELIMINARY" and s["status"] == "ISSUED"),
                       key=sort_key):
        stmt["status"] = "SUPERSEDED"
        touch(stmt)
    settlement.generate_statements(day, "FINAL", "final")
    for participant in list(store.participants.values()):
        refresh_credit(participant)
    day["status"] = "FINAL_SETTLED"
    touch(day)
    return ok(serialize(day))


@bp.post("/market/operating-days/<operatingDayId>/close")
def close_day(operatingDayId):
    auth = parse_auth()
    require_role(auth, ISO)
    get_body()
    day = get_day(operatingDayId)
    if day["status"] != "FINAL_SETTLED":
        raise conflict(ERR_INVALID_STATE,
                       "operating day close requires FINAL_SETTLED")
    for stmt in store.statements.values():
        if stmt["operating_day_id"] == day["id"] and stmt["status"] == "UNDER_DISPUTE":
            raise conflict(ERR_UNRESOLVED_DISPUTES,
                           "day has statements under dispute")
    for stmt in sorted((s for s in store.statements.values()
                        if s["operating_day_id"] == day["id"] and s["status"] == "ISSUED"),
                       key=sort_key):
        stmt["status"] = "CLOSED"
        touch(stmt)
    day["status"] = "CLOSED"
    touch(day)
    return ok(serialize(day))
