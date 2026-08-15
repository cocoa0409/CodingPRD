"""Market price index, sustainability credit reporting, logical clock."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from common import (actor, as_date, as_enum, as_int, as_str, bad_request,
                    body_dict, created, not_found, ok, ok_list, paginate, ser)
from logic import (ATTESTED_FACTOR, D0, MATERIALS, current_month,
                   new_ledger_record, rhu, sorted_items)
from store import db

bp = Blueprint("misc", __name__)


# ---------------------------------------------------------------------------
# Market price index (append-only ledger)
# ---------------------------------------------------------------------------

@bp.post("/api/price-index-entries")
def create_price_entry():
    uid, _ = actor({"BrokerOps"})
    body = body_dict()
    material = as_enum(body, "material_type", MATERIALS)
    region = as_str(body, "region_code")
    effective_from = as_date(body, "effective_from")
    price = as_int(body, "price_cents_per_ton")
    if price <= 0:
        bad_request("price_cents_per_ton must be positive")
    rec = new_ledger_record()
    rec.update(material_type=material, region_code=region,
               effective_from=effective_from, price_cents_per_ton=price,
               published_by_user_id=uid)
    db.price_entries[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/price-index-entries")
def list_price_entries():
    actor()
    items = sorted_items(db.price_entries.values())
    mt = request.args.get("material_type")
    rc = request.args.get("region_code")
    if mt is not None:
        items = [r for r in items if r["material_type"] == mt]
    if rc is not None:
        items = [r for r in items if r["region_code"] == rc]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


# ---------------------------------------------------------------------------
# Sustainability credit reporting
# ---------------------------------------------------------------------------

@bp.get("/api/generators/<gid>/credit-entries")
def generator_credit_entries(gid):
    actor()
    if gid not in db.generators:
        not_found("Generator not found")
    items = [e for e in sorted_items(db.credit_entries.values())
             if e["generator_id"] == gid]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.get("/api/generators/<gid>/credit-summary")
def generator_credit_summary(gid):
    actor()
    gen = db.generators.get(gid)
    if gen is None:
        not_found("Generator not found")
    period = request.args.get("period") or current_month()
    # standard (ledger) variant: signed sum of the period's entries
    standard = D0
    for e in db.credit_entries.values():
        if e["generator_id"] != gid or e["period"] != period:
            continue
        if e["entry_type"] == "ACCRUAL":
            standard += e["credits"]
        else:
            standard -= e["credits"]
    standard = rhu(standard, 2)
    # attested (regulatory) variant: shipments still ACCEPTED, accepted in period
    total_net = D0
    for sh in db.shipments.values():
        if sh["status"] != "ACCEPTED":
            continue
        if db.accepted_periods.get(sh["id"]) != period:
            continue
        ag = db.agreements.get(sh["supply_agreement_id"])
        if ag is None or ag["generator_id"] != gid:
            continue
        total_net += sh["net_billable_tons"]
    attested = rhu(total_net * ATTESTED_FACTOR, 2)
    return ok({
        "standard_credits": float(standard),
        "attested_credits": float(attested),
        "total_net_tons": float(total_net),
        "credit_tier": gen["credit_tier"],
    })


# ---------------------------------------------------------------------------
# Logical clock (test-driving endpoint)
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_clock():
    actor({"PlatformAdmin"})
    body = body_dict()
    raw = as_str(body, "to_iso8601")
    parsed = None
    try:
        candidate = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=timezone.utc)
        parsed = candidate.astimezone(timezone.utc)
    except ValueError:
        pass
    if parsed is None:
        try:
            from datetime import date as _date
            d = _date.fromisoformat(raw)
            parsed = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            pass
    if parsed is None:
        bad_request("to_iso8601 must be an ISO 8601 instant")
    db.clock = parsed
    return ok({"current_utc": raw})
