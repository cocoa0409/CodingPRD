"""Carrier endpoints (PRD §3.1) and its state machine (SCAFFOLD §1.2)."""
from flask import Blueprint

import serialize
from db import store, new_common, touch
from errors import (
    err,
    ERR_DUPLICATE,
    ERR_INVALID_STATE,
)
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from util import require_str, require_fraction, require_bool, validate_naic

bp = Blueprint("carriers", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}


@bp.post("/carriers")
def create_carrier():
    auth({"AgencyAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    naic = validate_naic(body.get("naic_code"))
    download_supported = require_bool(body, "download_supported", default=False)
    nb = require_fraction(body, "default_new_business_commission_pct")
    rn = require_fraction(body, "default_renewal_commission_pct")

    with store.lock:
        # uniqueness: naic_code (§2.8)
        for c in store.carriers.values():
            if c["naic_code"] == naic:
                raise err(ERR_DUPLICATE, "naic_code already exists")
        rec = new_common()
        rec.update(
            name=name,
            naic_code=naic,
            status="PROSPECTIVE",
            download_supported=download_supported,
            default_new_business_commission_pct=nb,
            default_renewal_commission_pct=rn,
        )
        store.carriers[rec["id"]] = rec
        return object_response(serialize.carrier(rec), 201)


@bp.get("/carriers/<cid>")
def get_carrier(cid):
    auth(ALL_ROLES)
    rec = lookup(store.carriers, cid)
    return object_response(serialize.carrier(rec))


@bp.get("/carriers")
def list_carriers():
    from flask import request
    auth(ALL_ROLES)
    status = request.args.get("status")
    recs = [c for c in store.carriers.values() if status is None or c["status"] == status]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.carrier(c) for c in page], limit, offset, total)


@bp.post("/carriers/<cid>/activate")
def activate_carrier(cid):
    auth({"AgencyAdmin"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.carriers, cid)
        if rec["status"] not in ("PROSPECTIVE", "SUSPENDED"):
            raise err(ERR_INVALID_STATE, "carrier cannot be activated from its current state")
        check_version(rec, body.get("expected_carrier_version"), "expected_carrier_version")
        # naic present and 5 digits (already enforced at create, re-affirm)
        validate_naic(rec["naic_code"])
        rec["status"] = "ACTIVE"
        touch(rec)
        return object_response(serialize.carrier(rec))


@bp.post("/carriers/<cid>/suspend")
def suspend_carrier(cid):
    auth({"AgencyAdmin"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.carriers, cid)
        if rec["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "only an ACTIVE carrier may be suspended")
        check_version(rec, body.get("expected_carrier_version"), "expected_carrier_version")
        rec["status"] = "SUSPENDED"
        touch(rec)
        return object_response(serialize.carrier(rec))


@bp.post("/carriers/<cid>/terminate")
def terminate_carrier(cid):
    auth({"AgencyAdmin"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.carriers, cid)
        if rec["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err(ERR_INVALID_STATE, "carrier cannot be terminated from its current state")
        check_version(rec, body.get("expected_carrier_version"), "expected_carrier_version")

        # Precondition: no policy under this carrier's products is ACTIVE,
        # PENDING_RENEWAL, or REINSTATED.
        product_ids = {p["id"] for p in store.products.values() if p["carrier_id"] == cid}
        for pol in store.policies.values():
            if pol["product_id"] in product_ids and pol["status"] in (
                "ACTIVE",
                "PENDING_RENEWAL",
                "REINSTATED",
            ):
                raise err(
                    ERR_INVALID_STATE,
                    "carrier has policies in ACTIVE/PENDING_RENEWAL/REINSTATED",
                )

        rec["status"] = "TERMINATED"
        touch(rec)
        # Cascade: all non-terminal appointments for this carrier -> TERMINATED.
        for appt in store.appointments.values():
            if appt["carrier_id"] == cid and appt["status"] in (
                "REQUESTED",
                "APPROVED",
                "ACTIVE",
            ):
                appt["status"] = "TERMINATED"
                touch(appt)
        return object_response(serialize.carrier(rec))
