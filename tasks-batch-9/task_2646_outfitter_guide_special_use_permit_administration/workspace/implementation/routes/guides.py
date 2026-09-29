"""Guides, their certification cycle and the authorized roster (PRD 3.1 / 3.6)."""
from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qstr
from security import ANY_ROLE, OFFICER, REPRESENTATIVE, SPECIALIST

bp = Blueprint("guides", __name__)

LEVELS = ("TRAINEE", "ASSISTANT", "LEAD")
CERT_TYPES = ("NONE", "BASIC_FIRST_AID", "WFR", "WEMT")
PERMIT_FILEABLE = ("ISSUED", "ACTIVE")


def check_credential(cert_type, expires_on):
    """The two safety checks, in their pinned order."""
    if cert_type == "NONE":
        raise ApiError("ERR_FIRST_AID_CERT_MISSING", "no first-aid certification on file")
    if store.as_date(expires_on) < store.today():
        raise ApiError("ERR_FIRST_AID_CERT_EXPIRED", "the first-aid certification has expired")


@bp.post("/osup/outfitters/<outfitter_id>/guides")
def hire_guide(outfitter_id):
    caller = security.authenticate((REPRESENTATIVE,))
    outfitter = store.get_or_404("outfitters", outfitter_id, "ERR_OUTFITTER_NOT_FOUND")
    security.require_owner(caller, outfitter["id"])
    data = shapes.body()
    full_name = shapes.req_str(data, "full_name")
    level = shapes.req_str(data, "qualification_level", allowed=LEVELS)
    cert_type = shapes.req_str(data, "first_aid_cert_type", allowed=CERT_TYPES)
    expires_on = shapes.req_date(data, "first_aid_expires_on")
    seasons = shapes.opt_int(data, "seasons_experience", minimum=0, default=0)
    guide = store.insert(
        "guides",
        {
            "outfitter_id": outfitter["id"],
            "full_name": full_name,
            "qualification_level": level,
            "first_aid_cert_type": cert_type,
            "first_aid_expires_on": expires_on,
            "seasons_experience": seasons,
            "base_client_capacity": 0,
            "status": "PENDING_QUALIFICATION",
            "qualified_at": None,
        },
    )
    calc.recompute_guide_capacity(guide)
    return envelope.ok(serialize.guide(guide), 201)


@bp.get("/osup/outfitters/<outfitter_id>/guides")
def list_roster(outfitter_id):
    security.authenticate(ANY_ROLE, mutating=False)
    outfitter = store.get_or_404("outfitters", outfitter_id, "ERR_OUTFITTER_NOT_FOUND")
    status = qstr("status")
    rows = [
        g
        for g in store.all_of("guides")
        if g["outfitter_id"] == outfitter["id"] and match(g, status=status)
    ]
    return envelope.paginate(store.sort_created(rows), serialize.guide)


@bp.get("/osup/guides/<guide_id>")
def read_guide(guide_id):
    security.authenticate(ANY_ROLE, mutating=False)
    guide = store.get_or_404("guides", guide_id, "ERR_GUIDE_NOT_FOUND")
    return envelope.ok(serialize.guide(guide))


@bp.post("/osup/guides/<guide_id>/certifications")
def file_certification(guide_id):
    caller = security.authenticate((REPRESENTATIVE,))
    guide = store.get_or_404("guides", guide_id, "ERR_GUIDE_NOT_FOUND")
    security.require_owner(caller, guide["outfitter_id"])
    data = shapes.body()
    cert_type = shapes.req_str(data, "first_aid_cert_type", allowed=CERT_TYPES)
    expires_on = shapes.req_date(data, "first_aid_expires_on")
    check_credential(cert_type, expires_on)
    guide["first_aid_cert_type"] = cert_type
    guide["first_aid_expires_on"] = expires_on
    guide["qualified_at"] = store.now_str()
    calc.recompute_guide_capacity(guide)
    if guide["qualification_level"] != "TRAINEE" and guide["status"] == "LAPSED":
        guide["status"] = "QUALIFIED"
    store.touch(guide)
    return envelope.ok(serialize.guide(guide))


@bp.post("/osup/guides/<guide_id>/qualify")
def qualify_guide(guide_id):
    security.authenticate((SPECIALIST, OFFICER))
    guide = store.get_or_404("guides", guide_id, "ERR_GUIDE_NOT_FOUND")
    # a TRAINEE may be qualified -- it simply keeps base_client_capacity 0
    check_credential(guide["first_aid_cert_type"], guide["first_aid_expires_on"])
    if guide["status"] not in ("PENDING_QUALIFICATION", "LAPSED"):
        raise ApiError("ERR_INVALID_REQUEST", "the guide is already QUALIFIED")
    guide["status"] = "QUALIFIED"
    guide["qualified_at"] = store.now_str()
    calc.recompute_guide_capacity(guide)
    store.touch(guide)
    return envelope.ok(serialize.guide(guide))


@bp.post("/osup/permits/<permit_id>/guide-authorizations")
def authorize_guide(permit_id):
    caller = security.authenticate((REPRESENTATIVE,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    data = shapes.body()
    guide = None
    raw_guide = data.get("guide_id")
    if isinstance(raw_guide, str) and raw_guide.strip():
        guide = store.get_or_404("guides", raw_guide, "ERR_GUIDE_NOT_FOUND")
    security.require_owner(caller, permit["outfitter_id"])
    guide_id = shapes.req_id(data, "guide_id")
    if guide is None:
        guide = store.get_or_404("guides", guide_id, "ERR_GUIDE_NOT_FOUND")
    # priority 7
    if permit["administrative_status"] not in PERMIT_FILEABLE:
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "the permit is not ISSUED or ACTIVE")
    # priority 8: the fixed safety order
    check_credential(guide["first_aid_cert_type"], guide["first_aid_expires_on"])
    if guide["qualification_level"] == "TRAINEE":
        raise ApiError("ERR_GUIDE_LEVEL_INELIGIBLE", "a TRAINEE may not be authorized")
    if guide["status"] != "QUALIFIED":
        raise ApiError("ERR_GUIDE_NOT_QUALIFIED", "the guide is not QUALIFIED")
    # priority 9
    if guide["outfitter_id"] != permit["outfitter_id"]:
        raise ApiError(
            "ERR_GUIDE_OUTFITTER_MISMATCH", "the guide belongs to another outfitter"
        )
    # priority 10: the credential must outlast the work
    area = store.get("use_areas", permit["use_area_id"])
    expires = store.as_date(guide["first_aid_expires_on"])
    covers_term = expires >= store.as_date(permit["term_end_date"])
    covers_season = area is not None and expires >= store.as_date(area["season_close_date"])
    if not covers_term and not covers_season:
        raise ApiError(
            "ERR_GUIDE_TERM_CONFLICT", "the credential expires before the season closes"
        )
    # priority 11: the roster cap
    standing = [
        a
        for a in store.all_of("authorizations")
        if a["permit_id"] == permit["id"] and a["status"] == "AUTHORIZED"
    ]
    if len(standing) >= calc.MAX_AUTHORIZED_GUIDES_PER_PERMIT:
        raise ApiError("ERR_GUIDE_ROSTER_FULL", "the permit already carries 8 guides")

    frozen = min(area["max_clients_per_guide"], guide["base_client_capacity"]) if area else 0
    row = store.insert(
        "authorizations",
        {
            "guide_id": guide["id"],
            "permit_id": permit["id"],
            "authorized_client_capacity": frozen,
            "status": "AUTHORIZED",
            "authorized_at": store.now_str(),
            "revoked_at": None,
            "revocation_reason_code": None,
        },
    )
    calc.recompute_permit_capacity_total(permit)
    store.touch(permit)
    return envelope.ok(serialize.authorization(row), 201)


@bp.get("/osup/permits/<permit_id>/guide-authorizations")
def list_permit_roster(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    status = qstr("status")
    rows = [
        a
        for a in store.all_of("authorizations")
        if a["permit_id"] == permit["id"] and match(a, status=status)
    ]
    return envelope.paginate(store.sort_created(rows), serialize.authorization)


@bp.get("/osup/guides/<guide_id>/guide-authorizations")
def list_guide_authorizations(guide_id):
    security.authenticate(ANY_ROLE, mutating=False)
    guide = store.get_or_404("guides", guide_id, "ERR_GUIDE_NOT_FOUND")
    status = qstr("status")
    rows = [
        a
        for a in store.all_of("authorizations")
        if a["guide_id"] == guide["id"] and match(a, status=status)
    ]
    return envelope.paginate(store.sort_created(rows), serialize.authorization)


@bp.post("/osup/guide-authorizations/<authorization_id>/revoke")
def revoke_authorization(authorization_id):
    caller = security.authenticate((REPRESENTATIVE, OFFICER))
    row = store.get_or_404("authorizations", authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    permit = store.get("permits", row["permit_id"])
    if permit is not None:
        security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    reason = shapes.req_str(data, "revocation_reason_code")
    if row["status"] != "AUTHORIZED":
        raise ApiError("ERR_AUTHORIZATION_NOT_ACTIVE", "the authorization is already revoked")
    row["status"] = "REVOKED"
    row["revoked_at"] = store.now_str()
    row["revocation_reason_code"] = reason
    store.touch(row)
    if permit is not None:
        calc.recompute_permit_capacity_total(permit)
        store.touch(permit)
    return envelope.ok(serialize.authorization(row))
