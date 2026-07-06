"""Sponsor and Contribution endpoints (PRD §3.8)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db, new_record, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_STALE_SPONSOR_VERSION,
    ERR_OVERFULFILLMENT,
    ERR_VALIDATION,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_enum,
    require_int,
    parse_pagination,
    paginate,
)
from services.lookups import get_sponsor
from services.serialize import sponsor_view, contribution_view

bp = Blueprint("sponsors", __name__)

SPONSOR_KINDS = {"DONOR", "SPONSOR"}


def _fulfillment_ratio(received, pledged):
    if pledged == 0:
        return 0.0
    ratio = Decimal(received) / Decimal(pledged)
    return float(ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _recompute_received(sponsor):
    total = 0
    for c in db.contributions.values():
        if c["sponsor_id"] == sponsor["id"] and c["status"] == "RECEIVED":
            total += c["amount_cents"]
    sponsor["received_cents"] = total
    sponsor["fulfillment_ratio"] = _fulfillment_ratio(total, sponsor["pledged_cents"])
    return total


@bp.route("/sponsors", methods=["POST"])
def create_sponsor():
    _, role = authenticate()
    require_role(role, {"DevelopmentOfficer"})
    body = get_body()
    org_name = require_string(body, "org_name")
    sponsor_kind = require_enum(body, "sponsor_kind", SPONSOR_KINDS)
    pledged = require_int(body, "pledged_cents")
    if pledged < 0:
        raise err(ERR_VALIDATION, "pledged_cents must be >= 0")

    with db.lock:
        rec = new_record(with_version=True)
        rec.update({
            "org_name": org_name,
            "sponsor_kind": sponsor_kind,
            "pledged_cents": pledged,
            "received_cents": 0,
            "fulfillment_ratio": _fulfillment_ratio(0, pledged),
            "status": "PLEDGED",
        })
        db.sponsors[rec["id"]] = rec
    return success(sponsor_view(rec), status=201)


@bp.route("/sponsors", methods=["GET"])
def list_sponsors():
    _, role = authenticate()
    require_role(role, {"DevelopmentOfficer"})
    limit, offset = parse_pagination()
    sponsor_kind = request.args.get("sponsor_kind")
    status = request.args.get("status")
    with db.lock:
        records = list(db.sponsors.values())
        if sponsor_kind is not None:
            records = [s for s in records if s["sponsor_kind"] == sponsor_kind]
        if status is not None:
            records = [s for s in records if s["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [sponsor_view(s) for s in page]
    return success(data, status=200, pagination=meta)


@bp.route("/sponsors/<sid>", methods=["GET"])
def get_one_sponsor(sid):
    _, role = authenticate()
    require_role(role, {"DevelopmentOfficer"})
    with db.lock:
        s = get_sponsor(sid)
        return success(sponsor_view(s), status=200)


@bp.route("/sponsors/<sid>/contributions", methods=["POST"])
def record_contribution(sid):
    _, role = authenticate()
    require_role(role, {"DevelopmentOfficer"})
    body = get_body()
    amount = require_int(body, "amount_cents")
    expected_sponsor_version = require_int(body, "expected_sponsor_version")
    with db.lock:
        sponsor = get_sponsor(sid)
        # State (priority 5): contributions only from PLEDGED or PARTIALLY_FULFILLED.
        if sponsor["status"] not in ("PLEDGED", "PARTIALLY_FULFILLED"):
            raise err(ERR_INVALID_STATE, "Sponsor is not accepting contributions")
        # OCC stale-version (priority 6).
        if expected_sponsor_version != sponsor["version"]:
            raise err(ERR_STALE_SPONSOR_VERSION, "Sponsor version is stale")
        # Over-fulfillment (priority 17): cannot push received above pledged —
        # checked before the generic field-range (priority 20) per PRD §3.10.
        if sponsor["received_cents"] + amount > sponsor["pledged_cents"]:
            raise err(ERR_OVERFULFILLMENT, "Contribution would over-fulfill the pledge")
        # Field-range (amount_cents >= 1) — generic, lowest priority.
        if amount < 1:
            raise err(ERR_VALIDATION, "amount_cents must be >= 1")

        # Append-only contribution (no version/updated_at of its own).
        crec = new_record(with_version=False)
        crec.update({
            "sponsor_id": sid,
            "amount_cents": amount,
            "expected_sponsor_version": expected_sponsor_version,
            "status": "RECEIVED",
        })
        db.contributions[crec["id"]] = crec

        # Recompute sponsor received_cents and fulfillment_ratio.
        new_received = _recompute_received(sponsor)
        # Advance fulfillment status.
        if new_received >= sponsor["pledged_cents"]:
            sponsor["status"] = "FULFILLED"
        elif new_received > 0:
            sponsor["status"] = "PARTIALLY_FULFILLED"
        touch(sponsor)
        return success(contribution_view(crec), status=201)


@bp.route("/sponsors/<sid>/contributions", methods=["GET"])
def list_contributions(sid):
    _, role = authenticate()
    require_role(role, {"DevelopmentOfficer"})
    limit, offset = parse_pagination()
    with db.lock:
        get_sponsor(sid)
        records = [c for c in db.contributions.values() if c["sponsor_id"] == sid]
        page, meta = paginate(records, limit, offset)
        data = [contribution_view(c) for c in page]
    return success(data, status=200, pagination=meta)


@bp.route("/sponsors/<sid>/lapse", methods=["POST"])
def lapse_sponsor(sid):
    _, role = authenticate()
    require_role(role, {"DevelopmentOfficer"})
    with db.lock:
        sponsor = get_sponsor(sid)
        if sponsor["status"] not in ("PLEDGED", "PARTIALLY_FULFILLED"):
            raise err(ERR_INVALID_STATE, "Sponsor cannot be lapsed from its current state")
        sponsor["status"] = "LAPSED"
        touch(sponsor)
        return success(sponsor_view(sponsor), status=200)
