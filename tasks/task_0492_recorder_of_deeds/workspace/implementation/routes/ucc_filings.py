"""LienUccFiling routes (PRD §3.7, §4). Lapse, continuation window, tax-lien
exclusivity with grace buffer, and lazy LAPSED evaluation on read."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import calculations as calc
from auth import require_auth, SUBMITTER, ALL_READERS
from clock import clock, parse_iso, add_years
from db import db, new_id, common_fields, touch
from helpers import (body, require_fields, as_str, as_enum, get_or_404, out,
                     out_list, paginate, sort_created)
from response import ok, created, listed

bp = Blueprint("ucc_filings", __name__)

LIEN_TYPES = {"UCC1", "TAX_LIEN", "JUDGMENT_LIEN", "MECHANICS_LIEN"}


def _maybe_lapse(filing):
    """Lazy LAPSED evaluation (PRD §3.7): a filing's status becomes LAPSED when
    the office's recording_date reaches or passes its lapse_date (inclusive).
    Returns the filing (mutated in place when it lapses)."""
    if filing["status"] == "ACTIVE":
        office = db.offices.get(filing["office_id"])
        recording_date = office["recording_date"] if office else clock.now()
        if recording_date >= filing["lapse_date"]:
            filing["status"] = "LAPSED"
            touch(filing)
    return filing


def _tax_lien_overlap(office_id, parcel_id, effective_date):
    """Tax-lien exclusivity (PRD §3.7): reject a new TAX_LIEN if an ACTIVE
    TAX_LIEN on the same parcel has a buffered period containing the new lien's
    effective_date — i.e. new.effective_date < existing.lapse_date + grace AND
    new.effective_date >= existing.effective_date."""
    grace = timedelta(days=calc.TAX_LIEN_GRACE_DAYS)
    for f in db.ucc_filings.values():
        if f["lien_type"] != "TAX_LIEN" or f["parcel_id"] != parcel_id:
            continue
        # evaluate lapse lazily so a stale ACTIVE that should be LAPSED is excluded
        _maybe_lapse(f)
        if f["status"] != "ACTIVE":
            continue
        if (effective_date < f["lapse_date"] + grace
                and effective_date >= f["effective_date"]):
            return True
    return False


@bp.route("/ucc-filings", methods=["POST"])
def create_filing():
    require_auth([SUBMITTER])
    data = body()
    require_fields(data, ["submitter_id", "office_id", "lien_type", "parcel_id",
                          "debtor_name", "effective_date"])
    submitter_id = as_str(data, "submitter_id")
    office_id = as_str(data, "office_id")
    lien_type = as_enum(data, "lien_type", LIEN_TYPES)
    parcel_id = as_str(data, "parcel_id")
    debtor_name = as_str(data, "debtor_name")
    raw_effective = data.get("effective_date")
    if not isinstance(raw_effective, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "effective_date must be an ISO 8601 string")
    try:
        effective_date = parse_iso(raw_effective)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid effective_date")

    # Existence (priority 3), left-to-right
    get_or_404(db.submitters, submitter_id)
    get_or_404(db.offices, office_id)

    lapse_date = add_years(effective_date, calc.LIEN_LAPSE_YEARS)

    # Tax-lien exclusivity (priority 9), TAX_LIEN only
    if lien_type == "TAX_LIEN" and _tax_lien_overlap(office_id, parcel_id, effective_date):
        raise errors.err(errors.ERR_TAX_LIEN_OVERLAP, "Tax lien overlaps an active tax lien on this parcel")

    fid = new_id()
    filing = {
        "id": fid,
        "submitter_id": submitter_id,
        "office_id": office_id,
        "lien_type": lien_type,
        "parcel_id": parcel_id,
        "debtor_name": debtor_name,
        "effective_date": effective_date,
        "lapse_date": lapse_date,
        "continuation_count": 0,
        "status": "ACTIVE",
    }
    filing.update(common_fields())
    db.ucc_filings[fid] = filing
    return created(out(filing))


@bp.route("/ucc-filings/<fid>", methods=["GET"])
def get_filing(fid):
    require_auth(ALL_READERS)
    filing = get_or_404(db.ucc_filings, fid)
    _maybe_lapse(filing)
    return ok(out(filing))


@bp.route("/ucc-filings", methods=["GET"])
def list_filings():
    require_auth(ALL_READERS)
    items = list(db.ucc_filings.values())
    # lazy lapse evaluation applies on read for each filing
    for f in items:
        _maybe_lapse(f)
    submitter_id = request.args.get("submitter_id")
    office_id = request.args.get("office_id")
    parcel_id = request.args.get("parcel_id")
    lien_type = request.args.get("lien_type")
    status = request.args.get("status")
    if submitter_id is not None:
        items = [f for f in items if f["submitter_id"] == submitter_id]
    if office_id is not None:
        items = [f for f in items if f["office_id"] == office_id]
    if parcel_id is not None:
        items = [f for f in items if f["parcel_id"] == parcel_id]
    if lien_type is not None:
        items = [f for f in items if f["lien_type"] == lien_type]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/ucc-filings/<fid>/continue", methods=["POST"])
def continue_filing(fid):
    caller = require_auth([SUBMITTER])
    filing = get_or_404(db.ucc_filings, fid)

    # State (priority 5): a TERMINATED filing is not a valid source state for
    # continuation. A by-time lapse is handled by the dedicated temporal check
    # below (ERR_FILING_ALREADY_LAPSED), per PRD §3.7, not by the state band.
    if filing["status"] == "TERMINATED":
        raise errors.err(errors.ERR_INVALID_STATE, "Filing is TERMINATED")
    # Ownership (priority 6)
    if caller.user_id != filing["submitter_id"]:
        raise errors.err(errors.ERR_NOT_OWNER, "Acting submitter does not own this filing")

    office = db.offices[filing["office_id"]]
    recording_date = office["recording_date"]
    # Temporal (priority 9): not already lapsed (strictly before lapse_date),
    # and within the continuation window (PRD §3.7).
    if recording_date >= filing["lapse_date"]:
        # reflect the observed LAPSED state on the persisted record
        _maybe_lapse(filing)
        raise errors.err(errors.ERR_FILING_ALREADY_LAPSED, "Filing has already lapsed")
    window_open = filing["lapse_date"] - timedelta(days=calc.CONTINUATION_WINDOW_DAYS)
    if recording_date < window_open:
        raise errors.err(errors.ERR_CONTINUATION_TOO_EARLY, "Continuation window not yet open")

    filing["lapse_date"] = add_years(filing["lapse_date"], calc.LIEN_LAPSE_YEARS)
    filing["continuation_count"] += 1
    touch(filing)
    return ok(out(filing))


@bp.route("/ucc-filings/<fid>/terminate", methods=["POST"])
def terminate_filing(fid):
    caller = require_auth([SUBMITTER])
    filing = get_or_404(db.ucc_filings, fid)
    _maybe_lapse(filing)
    # State (priority 5)
    if filing["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Filing is not ACTIVE")
    # Ownership (priority 6)
    if caller.user_id != filing["submitter_id"]:
        raise errors.err(errors.ERR_NOT_OWNER, "Acting submitter does not own this filing")
    filing["status"] = "TERMINATED"
    touch(filing)
    return ok(out(filing))
