"""Cycle endpoints + lock-reviews / close transitions (PRD §3.2)."""

from flask import Blueprint, request

import config
from db import parse_iso, store
from errors import raise_err
from middleware import require_role
from response import ok, paginate
from services.audit import log_event
from services.cascades import close_cycle, lock_reviews
from services.serializers import cycle_view

from . import _helpers as H

bp = Blueprint("cycles", __name__)


def _validate_windows(start: str, end: str):
    try:
        s = parse_iso(start)
        e = parse_iso(end)
    except Exception:
        raise_err("ERR_VALIDATION", "review_window_* must be ISO 8601 UTC.")
    if not (e > s):
        raise_err("ERR_TIME_WINDOW_INVALID", "review_window_end must be strictly after review_window_start.")


@bp.route("/cycles", methods=["POST"])
@require_role("HRBP", "Admin")
def create_cycle():
    with store.lock:
        body = H.get_body()
        name = H.require_str(H.require_field(body, "name"), "name", 1, 200)
        cadence = H.require_enum(
            H.require_field(body, "cadence"), "cadence", config.CADENCES,
        )
        review_window_start = H.require_iso(
            H.require_field(body, "review_window_start"), "review_window_start",
        )
        review_window_end = H.require_iso(
            H.require_field(body, "review_window_end"), "review_window_end",
        )
        merit_budget_cents = H.require_int(
            H.require_field(body, "merit_budget_cents"), "merit_budget_cents", 0,
        )
        equity_pool = H.require_int(
            H.require_field(body, "equity_refresh_pool_units"),
            "equity_refresh_pool_units", 0,
        )
        bell_curve_raw = H.require_field(body, "bell_curve_target")

        # Temporal-window validity (priority 100) before shape (110)? PRD says
        # temporal (100) runs before shape (110); both can fire — we run window
        # first.
        _validate_windows(review_window_start, review_window_end)
        bell_curve = H.validate_bell_curve_target(bell_curve_raw)

        cycle = H.new_entity({
            "name": name,
            "cadence": cadence,
            "status": "OPEN",
            "review_window_start": review_window_start,
            "review_window_end": review_window_end,
            "bell_curve_target": bell_curve,
            "merit_budget_cents": merit_budget_cents,
            "equity_refresh_pool_units": equity_pool,
            "merit_budget_consumed_cents": 0,
            "equity_pool_consumed_units": 0,
        })
        store.cycles[cycle["id"]] = cycle
        log_event("Cycle", cycle["id"], "cycle.create", payload=body)
        return ok(cycle_view(cycle), status=201)


@bp.route("/cycles", methods=["GET"])
@require_role("HRBP", "Admin", "Manager", "Approver")
def list_cycles():
    with store.lock:
        status = request.args.get("status")
        limit, offset = H.pagination_params()
        items = list(store.cycles.values())
        if status is not None:
            if status not in config.CYCLE_STATUSES:
                raise_err("ERR_VALIDATION", "Invalid status filter.")
            items = [c for c in items if c["status"] == status]
        items.sort(key=lambda c: c["created_at"])
        sliced, page_meta = paginate(items, limit, offset)
        return ok([cycle_view(c) for c in sliced], pagination=page_meta)


@bp.route("/cycles/<cycle_id>", methods=["GET"])
@require_role("HRBP", "Admin", "Manager", "Approver", "Reviewer")
def read_cycle(cycle_id):
    with store.lock:
        c = H.get_cycle_or_404(cycle_id)
        return ok(cycle_view(c))


@bp.route("/cycles/<cycle_id>", methods=["PATCH"])
@require_role("HRBP", "Admin")
def patch_cycle(cycle_id):
    with store.lock:
        c = H.get_cycle_or_404(cycle_id)
        body = H.get_body()
        supplied_version = body.get("version")

        # If both windows are being changed, check the new pair; if only one,
        # check it against the current other.
        new_start = body.get("review_window_start", c["review_window_start"])
        new_end = body.get("review_window_end", c["review_window_end"])
        if "review_window_start" in body or "review_window_end" in body:
            _validate_windows(new_start, new_end)

        if "bell_curve_target" in body and body["bell_curve_target"] is not None:
            new_bell = H.validate_bell_curve_target(body["bell_curve_target"])
        else:
            new_bell = None

        if "name" in body and body["name"] is not None:
            new_name = H.require_str(body["name"], "name", 1, 200)
        else:
            new_name = None

        if "merit_budget_cents" in body and body["merit_budget_cents"] is not None:
            new_merit = H.require_int(body["merit_budget_cents"], "merit_budget_cents", 0)
        else:
            new_merit = None

        if "equity_refresh_pool_units" in body and body["equity_refresh_pool_units"] is not None:
            new_equity = H.require_int(body["equity_refresh_pool_units"], "equity_refresh_pool_units", 0)
        else:
            new_equity = None

        H.check_version(c, supplied_version)

        changed = False
        if new_name is not None:
            c["name"] = new_name; changed = True
        if new_bell is not None:
            c["bell_curve_target"] = new_bell; changed = True
        if new_merit is not None:
            c["merit_budget_cents"] = new_merit; changed = True
        if new_equity is not None:
            c["equity_refresh_pool_units"] = new_equity; changed = True
        if "review_window_start" in body:
            c["review_window_start"] = body["review_window_start"]; changed = True
        if "review_window_end" in body:
            c["review_window_end"] = body["review_window_end"]; changed = True

        if changed:
            H.bump(c)
        log_event("Cycle", c["id"], "cycle.patch", payload=body)
        return ok(cycle_view(c))


@bp.route("/cycles/<cycle_id>/lock-reviews", methods=["POST"])
@require_role("HRBP")
def lock_reviews_route(cycle_id):
    with store.lock:
        c = H.get_cycle_or_404(cycle_id)
        if c["status"] != "OPEN":
            raise_err("ERR_INVALID_STATE", f"Cycle is in {c['status']}, not OPEN.")

        # Every ReviewCase belonging to this cycle must be SUBMITTED or RETURNED
        rcs = [rc for rc in store.review_cases.values() if rc["cycle_id"] == cycle_id]
        for rc in rcs:
            if rc["status"] not in ("SUBMITTED", "RETURNED"):
                raise_err(
                    "ERR_INVALID_STATE",
                    f"ReviewCase '{rc['id']}' is in {rc['status']}, not SUBMITTED/RETURNED.",
                )

        lock_reviews(c)
        log_event("Cycle", c["id"], "cycle.lock_reviews", payload={})
        return ok(cycle_view(c))


@bp.route("/cycles/<cycle_id>/close", methods=["POST"])
@require_role("HRBP")
def close_cycle_route(cycle_id):
    with store.lock:
        c = H.get_cycle_or_404(cycle_id)
        if c["status"] != "COMP_PLANNING":
            raise_err("ERR_INVALID_STATE", f"Cycle is in {c['status']}, not COMP_PLANNING.")

        for cp in store.comp_plans.values():
            if cp["cycle_id"] == cycle_id and cp["status"] not in ("APPROVED", "REJECTED"):
                raise_err(
                    "ERR_INVALID_STATE",
                    f"CompPlan '{cp['id']}' must be APPROVED or REJECTED before close.",
                )

        if c.get("merit_budget_consumed_cents", 0) > c["merit_budget_cents"]:
            raise_err("ERR_MERIT_BUDGET_EXCEEDED", "Merit budget consumption exceeds authorisation.")
        if c.get("equity_pool_consumed_units", 0) > c["equity_refresh_pool_units"]:
            raise_err("ERR_EQUITY_POOL_EXHAUSTED", "Equity pool consumption exceeds authorisation.")

        close_cycle(c)
        log_event("Cycle", c["id"], "cycle.close", payload={})
        return ok(cycle_view(c))
