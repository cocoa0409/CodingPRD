"""KDM Key endpoints."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_request, err_invalid_state, err_print_not_ready,
    err_kdm_conflict,
)
from services.core import (
    serialize_kdm_key, get_kdm_key, get_booking, new_entity_common, touch,
)
from util import parse_dt, iso_from_dt
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("kdm", __name__)


def _check_kdm_window_conflict(booking, valid_from_dt, valid_until_dt, fingerprint,
                               exclude_kid=None):
    """Half-open overlap: a.from < b.until AND b.from < a.until.

    PRD §3.5: the proposed window must not overlap another issued or live key
    "on the same screen". A KDM's only screen reference is its
    screen_cert_fingerprint (the target screen's certificate), so keys sharing
    the fingerprint are keys on the same screen — including keys issued under
    other booking agreements of this distributor.
    """
    film = db.films.get(booking["film_id"])
    did = film["distributor_id"] if film else None
    for k in db.kdm_keys.values():
        if k["id"] == exclude_kid:
            continue
        if k["status"] not in ("ISSUED", "LIVE"):
            continue
        if k["screen_cert_fingerprint"] != fingerprint:
            continue
        # Scope to the same distributor tree (a screen lives under one distributor)
        kb = db.booking_agreements.get(k["booking_agreement_id"])
        kfilm = db.films.get(kb["film_id"]) if kb else None
        if not kfilm or kfilm["distributor_id"] != did:
            continue
        kf = parse_dt(k["valid_from_utc"])
        ku = parse_dt(k["valid_until_utc"])
        if kf is None or ku is None:
            continue
        if valid_from_dt < ku and kf < valid_until_dt:
            raise err_kdm_conflict()


@bp.route("/distributors/<did>/booking-agreements/<baid>/kdm-keys", methods=["POST"])
@require_roles("Booker")
def issue_kdm(did, baid, _user_id, _role):
    b = get_booking(did, baid)
    body = get_json_body()
    require_fields(body, ["valid_from_utc", "valid_until_utc", "screen_cert_fingerprint"])
    vf = parse_dt(body["valid_from_utc"])
    vu = parse_dt(body["valid_until_utc"])
    if vf is None or vu is None:
        raise err_invalid_request("valid_from_utc/valid_until_utc must be ISO 8601")
    # 7 KDM conflict (priority 7 before print readiness 8)
    _check_kdm_window_conflict(b, vf, vu, body["screen_cert_fingerprint"])
    # 8 PRINT_NOT_READY
    if b["print_status"] != "DCP_DELIVERED":
        raise err_print_not_ready()
    common = new_entity_common()
    k = {
        **common,
        "booking_agreement_id": baid,
        "valid_from_utc": iso_from_dt(vf),
        "valid_until_utc": iso_from_dt(vu),
        "screen_cert_fingerprint": body["screen_cert_fingerprint"],
        "status": "ISSUED",
    }
    db.kdm_keys[k["id"]] = k
    b["print_status"] = "KDM_ISSUED"
    touch(b)
    return success_object(serialize_kdm_key(k), 201)


@bp.route("/distributors/<did>/booking-agreements/<baid>/kdm-keys/<kid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def read_kdm(did, baid, kid, _user_id, _role):
    return success_object(serialize_kdm_key(get_kdm_key(did, baid, kid)))


@bp.route("/distributors/<did>/booking-agreements/<baid>/kdm-keys", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_kdm(did, baid, _user_id, _role):
    get_booking(did, baid)
    items = [k for k in db.kdm_keys.values() if k["booking_agreement_id"] == baid]
    filters = {}
    for k in ("status", "booking_agreement_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_kdm_key, filters)


@bp.route("/distributors/<did>/booking-agreements/<baid>/kdm-keys/<kid>/extend", methods=["POST"])
@require_roles("Booker")
def extend_kdm(did, baid, kid, _user_id, _role):
    b = get_booking(did, baid)
    k = get_kdm_key(did, baid, kid)
    body = get_json_body()
    require_fields(body, ["valid_until_utc"])
    new_until = parse_dt(body["valid_until_utc"])
    if new_until is None:
        raise err_invalid_request("valid_until_utc must be ISO 8601")
    if k["status"] not in ("ISSUED", "LIVE"):
        raise err_invalid_state("KDM must be ISSUED or LIVE to extend")
    cur_until = parse_dt(k["valid_until_utc"])
    if cur_until is None:
        raise err_invalid_state("current valid_until_utc invalid")
    if k["status"] == "ISSUED" and new_until <= cur_until:
        raise err_invalid_request("new valid_until_utc must be > current valid_until_utc")
    # For LIVE: requires only that key still be live — but also enforce new > current for sanity
    if k["status"] == "LIVE" and new_until <= cur_until:
        raise err_invalid_request("new valid_until_utc must be > current valid_until_utc")
    # Conflict check for new window [valid_from, new_until)
    vf = parse_dt(k["valid_from_utc"])
    _check_kdm_window_conflict(b, vf, new_until, k["screen_cert_fingerprint"],
                               exclude_kid=k["id"])
    # Move original to EXTENDED
    k["status"] = "EXTENDED"
    touch(k)
    # Create superseding key
    common = new_entity_common()
    new_k = {
        **common,
        "booking_agreement_id": baid,
        "valid_from_utc": k["valid_from_utc"],
        "valid_until_utc": iso_from_dt(new_until),
        "screen_cert_fingerprint": k["screen_cert_fingerprint"],
        "status": "ISSUED",
    }
    db.kdm_keys[new_k["id"]] = new_k
    return success_object(serialize_kdm_key(new_k))


@bp.route("/distributors/<did>/booking-agreements/<baid>/kdm-keys/<kid>/revoke", methods=["POST"])
@require_roles("Booker")
def revoke_kdm(did, baid, kid, _user_id, _role):
    b = get_booking(did, baid)
    k = get_kdm_key(did, baid, kid)
    if k["status"] not in ("ISSUED", "LIVE"):
        raise err_invalid_state("KDM must be ISSUED or LIVE to revoke")
    k["status"] = "REVOKED"
    touch(k)
    if b["print_status"] == "KEY_LIVE":
        b["print_status"] = "DCP_DELIVERED"
        touch(b)
    return success_object(serialize_kdm_key(k))
