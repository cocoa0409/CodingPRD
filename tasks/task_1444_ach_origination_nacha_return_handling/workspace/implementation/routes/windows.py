"""CutoffWindow creation (rate card definition)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import stamp_new
from errors import raise_err, ERR_INVALID_REQUEST, ERR_WINDOW_OVERLAP
from middleware import require_roles
from response import success_object
from services.domain import WINDOW_KINDS, SAME_DAY_KINDS, window_by_kind
from util import get_json_body, require_enum, require_hhmm, require_int, hhmm_to_minutes

bp = Blueprint("windows", __name__)


@bp.route("/ach/cutoff-windows", methods=["POST"])
@require_roles("OdfiOperations")
def create_cutoff_window(_user_id: str, _role: str):
    body = get_json_body()
    # Schema (p5): enums, HH:MM formats, fee integers >= 0.
    window_kind = require_enum(body, "window_kind", WINDOW_KINDS)
    opens_at = require_hhmm(body, "opens_at_utc")
    closes_at = require_hhmm(body, "closes_at_utc")
    per_entry_fee = require_int(body, "per_entry_fee_cents", minimum=0)
    file_fee = require_int(body, "file_fee_cents", minimum=0)
    surcharge = require_int(body, "large_entry_surcharge_cents", minimum=0)

    # Structural (p10): unique kind; close strictly later than open; half-open
    # [opens, closes) intervals non-overlapping among same-day kinds (adjacency
    # allowed; NEXT_DAY is not part of the overlap rule).
    if window_by_kind(window_kind) is not None:
        raise_err(ERR_WINDOW_OVERLAP, f"CutoffWindow kind {window_kind} already exists")
    opens_min = hhmm_to_minutes(opens_at)
    closes_min = hhmm_to_minutes(closes_at)
    if closes_min <= opens_min:
        raise_err(ERR_WINDOW_OVERLAP, "closes_at_utc must be strictly later than opens_at_utc")
    if window_kind in SAME_DAY_KINDS:
        for existing in db.cutoff_windows.values():
            if existing["window_kind"] not in SAME_DAY_KINDS:
                continue
            ex_open = hhmm_to_minutes(existing["opens_at_utc"])
            ex_close = hhmm_to_minutes(existing["closes_at_utc"])
            if opens_min < ex_close and ex_open < closes_min:
                raise_err(
                    ERR_WINDOW_OVERLAP,
                    f"Same-day window interval overlaps {existing['window_kind']}",
                )

    window = {
        "window_kind": window_kind,
        "opens_at_utc": opens_at,
        "closes_at_utc": closes_at,
        "per_entry_fee_cents": per_entry_fee,
        "file_fee_cents": file_fee,
        "large_entry_surcharge_cents": surcharge,
    }
    stamp_new(window)
    db.cutoff_windows[window["id"]] = window
    return success_object(window, 201)
