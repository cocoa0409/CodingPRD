"""Per-diem rate endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_validation
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_per_diem_rate
from core.store import store
from core.utils import is_int, lock, new_id, now_iso, parse_iso


bp = Blueprint("per_diem_rates", __name__)


@bp.post("/per-diem-rates")
@require_roles("ADMIN")
def create_per_diem_rate():
    body = get_json_body()
    required = ["city", "state", "effective_from", "effective_to", "lodging_cap_cents", "mie_cap_cents", "is_high_cost_locality"]
    for f in required:
        if body.get(f) is None:
            raise err_validation(f"{f} is required.")

    try:
        eff_from = parse_iso(body["effective_from"])
        eff_to = parse_iso(body["effective_to"])
    except ValueError as exc:
        raise err_validation(str(exc))
    if eff_from is None or eff_to is None or eff_to <= eff_from:
        raise err_validation("effective_to must be > effective_from.")

    if not is_int(body["lodging_cap_cents"]) or body["lodging_cap_cents"] < 0:
        raise err_validation("lodging_cap_cents must be a non-negative integer.")
    if not is_int(body["mie_cap_cents"]) or body["mie_cap_cents"] < 0:
        raise err_validation("mie_cap_cents must be a non-negative integer.")
    if not isinstance(body["is_high_cost_locality"], bool):
        raise err_validation("is_high_cost_locality must be boolean.")

    with lock():
        rec = {
            "id": new_id(),
            "city": body["city"],
            "state": body["state"],
            "effective_from": body["effective_from"],
            "effective_to": body["effective_to"],
            "lodging_cap_cents": int(body["lodging_cap_cents"]),
            "mie_cap_cents": int(body["mie_cap_cents"]),
            "is_high_cost_locality": bool(body["is_high_cost_locality"]),
            "created_at": now_iso(),
        }
        store.per_diem_rates[rec["id"]] = rec

    return success_response(serialize_per_diem_rate(rec), status=201)


@bp.get("/per-diem-rates")
@require_roles("TRAVELER", "MANAGER", "FINANCE_REVIEWER", "OOP_APPROVER", "ADMIN")
def list_per_diem_rates():
    city = request.args.get("city")
    state = request.args.get("state")
    effective_on = request.args.get("effective_on")
    when = None
    if effective_on is not None:
        try:
            when = parse_iso(effective_on)
        except ValueError as exc:
            raise err_validation(str(exc))

    items = list(store.per_diem_rates.values())
    if city:
        items = [r for r in items if (r["city"] or "").strip().lower() == city.strip().lower()]
    if state:
        items = [r for r in items if (r["state"] or "").strip().upper() == state.strip().upper()]
    if when is not None:
        filtered = []
        for r in items:
            eff_from = parse_iso(r["effective_from"])
            eff_to = parse_iso(r["effective_to"])
            if eff_from is not None and eff_to is not None and eff_from <= when < eff_to:
                filtered.append(r)
        items = filtered

    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    page, meta = paginate(items, limit, offset)
    return success_response(
        [serialize_per_diem_rate(r) for r in page],
        response_type="array",
        pagination=meta,
    )
