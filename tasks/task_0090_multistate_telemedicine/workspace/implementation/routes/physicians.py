"""Physician registry + state-license junction routes."""
from flask import Blueprint

import db
from errors import (err, ERR_DUPLICATE_RESOURCE, ERR_COMPACT_INELIGIBLE,
                    ERR_LICENSE_PERIOD_OVERLAP, ERR_INVALID_STATE, ERR_INVALID_REQUEST)
from middleware import require_auth, require_role
from response import success_object
from services import store, serializers, lookup, validate, cascade
from .common import list_response

bp = Blueprint("physicians", __name__)


# ---------------- Physician registry ----------------

@bp.route("/physicians", methods=["POST"])
def create_physician():
    # Public (Anonymous) — no auth required.
    body = validate.get_body()
    full_name = validate.require_str(body, "full_name")
    npi = validate.require_str(body, "npi")
    if not validate.NPI_RE.match(npi):
        raise err(ERR_INVALID_REQUEST, "npi must be exactly 10 numeric digits.")
    dea_number = validate.optional_str(body, "dea_number", None)
    imlc_eligible = validate.optional_bool(body, "imlc_eligible", False)
    home_state_code = validate.require_state(body, "home_state_code")

    with db.lock:
        # Uniqueness: npi unique across physicians (priority 5).
        for p in db.physicians.values():
            if p["npi"] == npi:
                raise err(ERR_DUPLICATE_RESOURCE, "npi already registered.")
        record = store.create_full({
            "full_name": full_name,
            "npi": npi,
            "dea_number": dea_number,
            "imlc_eligible": imlc_eligible,
            "home_state_code": home_state_code,
            "active_license_count": 0,
            "status": "ACTIVE",
        })
        db.physicians[record["id"]] = record
        return success_object(serializers.physician(record), status=201)


@bp.route("/physicians/<pid>", methods=["GET"])
def get_physician(pid):
    with db.lock:
        p = lookup.physician(pid)
        return success_object(serializers.physician(p))


@bp.route("/physicians", methods=["GET"])
def list_physicians():
    with db.lock:
        return list_response(list(db.physicians.values()), serializers.physician)


@bp.route("/physicians/<pid>/deactivate", methods=["POST"])
def deactivate_physician(pid):
    _, role = require_auth()
    require_role(role, {"LicensingBoard"})
    with db.lock:
        p = lookup.physician(pid)
        p["status"] = "DEACTIVATED"
        store.touch(p)
        return success_object(serializers.physician(p))


def recompute_active_license_count(physician_id):
    count = sum(
        1 for s in db.state_licenses.values()
        if s["physician_id"] == physician_id and s["status"] == "ACTIVE"
    )
    phys = db.physicians.get(physician_id)
    if phys is not None:
        phys["active_license_count"] = count
        store.touch(phys)


# ---------------- State licenses (junction) ----------------

@bp.route("/physicians/<pid>/state-licenses", methods=["POST"])
def create_state_license(pid):
    from errors import ERR_INVALID_REQUEST
    _, role = require_auth()
    require_role(role, {"LicensingBoard"})
    with db.lock:
        phys = lookup.physician(pid)
        body = validate.get_body()
        state_code = validate.require_state(body, "state_code")
        issuance_type = validate.require_enum(body, "issuance_type", {"FULL", "COMPACT_EXPEDITED"})
        controlled = validate.optional_bool(body, "controlled_substance_authority", False)
        effective_date = validate.require_datetime(body, "effective_date")
        expiration_date = validate.require_datetime(body, "expiration_date")

        # Priority 6: COMPACT_EXPEDITED eligibility.
        if issuance_type == "COMPACT_EXPEDITED":
            if not phys["imlc_eligible"] or state_code == phys["home_state_code"]:
                raise err(ERR_COMPACT_INELIGIBLE,
                          "COMPACT_EXPEDITED requires an imlc-eligible physician and a "
                          "state other than the home state.")

        # Priority 7: half-open period overlap with non-REVOKED same physician+state.
        new_eff = db.parse_iso(effective_date)
        new_exp = db.parse_iso(expiration_date)
        for s in db.state_licenses.values():
            if s["physician_id"] != pid or s["state_code"] != state_code:
                continue
            if s["status"] == "REVOKED":
                continue
            ex_eff = db.parse_iso(s["effective_date"])
            ex_exp = db.parse_iso(s["expiration_date"])
            if new_eff < ex_exp and ex_eff < new_exp:
                raise err(ERR_LICENSE_PERIOD_OVERLAP,
                          "New license period overlaps an existing non-revoked license.")

        record = store.create_full({
            "physician_id": pid,
            "state_code": state_code,
            "issuance_type": issuance_type,
            "controlled_substance_authority": controlled,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "status": "ACTIVE",
            "suspension_reason": None,
        })
        db.state_licenses[record["id"]] = record
        recompute_active_license_count(pid)
        return success_object(serializers.state_license(record), status=201)


@bp.route("/physicians/<pid>/state-licenses", methods=["GET"])
def list_state_licenses(pid):
    with db.lock:
        lookup.physician(pid)
        records = [s for s in db.state_licenses.values() if s["physician_id"] == pid]
        return list_response(records, serializers.state_license)


@bp.route("/state-licenses/<sid>", methods=["GET"])
def get_state_license(sid):
    with db.lock:
        s = lookup.state_license(sid)
        return success_object(serializers.state_license(s))


@bp.route("/state-licenses/<sid>/suspend", methods=["POST"])
def suspend_license(sid):
    _, role = require_auth()
    require_role(role, {"LicensingBoard"})
    with db.lock:
        s = lookup.state_license(sid)
        body = validate.get_body()
        reason = validate.require_str(body, "suspension_reason")
        if s["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "License must be ACTIVE to suspend.")
        s["suspension_reason"] = reason
        s["status"] = "SUSPENDED"
        store.touch(s)
        recompute_active_license_count(s["physician_id"])
        cascade.suspend_cascade(sid)
        return success_object(serializers.state_license(s))


@bp.route("/state-licenses/<sid>/reinstate", methods=["POST"])
def reinstate_license(sid):
    _, role = require_auth()
    require_role(role, {"LicensingBoard"})
    with db.lock:
        s = lookup.state_license(sid)
        if s["status"] != "SUSPENDED":
            raise err(ERR_INVALID_STATE, "License must be SUSPENDED to reinstate.")
        # Precondition: clock < expiration_date (license has not expired during suspension).
        now = db.clock_now()
        exp = db.parse_iso(s["expiration_date"])
        if not (now < exp):
            raise err(ERR_INVALID_STATE, "License expired during suspension; cannot reinstate.")
        s["suspension_reason"] = None
        s["status"] = "ACTIVE"
        store.touch(s)
        recompute_active_license_count(s["physician_id"])
        return success_object(serializers.state_license(s))


@bp.route("/state-licenses/<sid>/revoke", methods=["POST"])
def revoke_license(sid):
    _, role = require_auth()
    require_role(role, {"LicensingBoard"})
    with db.lock:
        s = lookup.state_license(sid)
        if s["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err(ERR_INVALID_STATE, "License must be ACTIVE or SUSPENDED to revoke.")
        s["status"] = "REVOKED"
        store.touch(s)
        # active_license_count: only an ACTIVE->REVOKED changes the count;
        # SUSPENDED was already excluded. recompute is idempotent either way.
        recompute_active_license_count(s["physician_id"])
        return success_object(serializers.state_license(s))
