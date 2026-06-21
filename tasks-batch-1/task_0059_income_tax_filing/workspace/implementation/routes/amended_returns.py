from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, parse_iso,
                  paginate, sorted_by_created)
from serialize import public, public_list
from services.common import (get_taxpayer_or_fk, get_return_or_fk, get_amended_or_404,
                             owner_check_amended)

bp = Blueprint("amended_returns", __name__)


def _windows_overlap_closed(a_start, a_end, b_start, b_end):
    """Closed [start, end] intervals; touching endpoints count as overlap."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/amended-returns")
def create_amended():
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer"})
    body = get_body()

    original_return_id = require_str(body, "original_return_id")
    taxpayer_id = require_str(body, "taxpayer_id")

    # FK existence: original return + taxpayer
    original = get_return_or_fk(original_return_id)
    get_taxpayer_or_fk(taxpayer_id)

    # ownership: caller must own the amendment (taxpayer_id == X-User-ID)
    if taxpayer_id != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER,
                  "Caller may only create amendments for themselves")

    corrected_balance = require_int(body, "corrected_balance_due_cents")
    cps = require_str(body, "correction_period_start")
    cpe = require_str(body, "correction_period_end")
    expected_version = require_int(body, "expected_return_version")

    start_dt = parse_iso(cps, "correction_period_start")
    end_dt = parse_iso(cpe, "correction_period_end")

    # state legality / business: original must be FILED
    if original["status"] != "FILED":
        raise err(errors.ERR_ORIGINAL_NOT_FILED,
                  "1040X may only target a FILED return")

    # OCC
    if expected_version != original["version"]:
        raise err(errors.ERR_STALE_RETURN_VERSION,
                  "expected_return_version does not match original return version")

    # correction window overlap (closed interval) on same original_return_id
    for am in db.amended_returns.values():
        if am["original_return_id"] != original_return_id:
            continue
        e_start = parse_iso(am["correction_period_start"])
        e_end = parse_iso(am["correction_period_end"])
        if _windows_overlap_closed(start_dt, end_dt, e_start, e_end):
            raise err(errors.ERR_CORRECTION_WINDOW_OVERLAP,
                      "Correction window overlaps an existing amendment on this return")

    amended = {
        "original_return_id": original_return_id,
        "taxpayer_id": taxpayer_id,
        "status": "DRAFT",
        "corrected_balance_due_cents": corrected_balance,
        "correction_period_start": cps,
        "correction_period_end": cpe,
        "delta_cents": 0,
    }
    init_common(amended)
    db.amended_returns[amended["id"]] = amended
    touch(original)
    return success(public(amended), status=201)


@bp.get("/amended-returns/<amended_id>")
def get_amended(amended_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    am = get_amended_or_404(amended_id)
    owner_check_amended(role, user_id, am)
    return success(public(am))


@bp.get("/amended-returns")
def list_amended():
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer", "Preparer"})
    items = list(db.amended_returns.values())
    items = [a for a in items if a["taxpayer_id"] == user_id]
    orig_filter = request.args.get("original_return_id")
    if orig_filter is not None:
        items = [a for a in items if a["original_return_id"] == orig_filter]
    tp_filter = request.args.get("taxpayer_id")
    if tp_filter is not None:
        items = [a for a in items if a["taxpayer_id"] == tp_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


@bp.post("/amended-returns/<amended_id>/file")
def file_amended(amended_id):
    user_id, role = get_auth()
    require_roles(role, {"Taxpayer"})
    am = get_amended_or_404(amended_id)
    owner_check_amended(role, user_id, am)

    # state: amendment must be DRAFT
    if am["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Amendment is not in DRAFT")

    original = db.tax_returns.get(am["original_return_id"])
    # cross-entity guard: original must still be FILED
    if original is None or original["status"] != "FILED":
        raise err(errors.ERR_ORIGINAL_NOT_FILED,
                  "Original return is not in FILED status")

    # hop 1: compute delta + mark amendment FILED
    am["delta_cents"] = am["corrected_balance_due_cents"] - original["balance_due_cents"]
    am["status"] = "FILED"
    touch(am)

    # hop 2: original FILED -> AMENDED
    original["status"] = "AMENDED"
    touch(original)

    # hop 3: cascade to ACCEPTED EFilingSubmission(s) of the original
    for sub in db.efilings.values():
        if sub["return_id"] == original["id"] and sub["status"] == "ACCEPTED":
            sub["superseded_by_amendment"] = True
            touch(sub)

    return success(public(am))
