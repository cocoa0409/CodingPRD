from flask import Blueprint, request

from db import STORE, CLOCK, next_seq, new_id, bump, parse_ts
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_FORBIDDEN, ERR_SERIAL_EXISTS,
                    ERR_CROSS_BUILDING_REFERENCE,
                    ERR_CREDENTIAL_NOT_ISSUABLE, ERR_CREDENTIAL_NOT_ISSUED,
                    ERR_PERSON_INVALID_STATE, ERR_PERSON_KIND_MISMATCH,
                    ERR_PERSON_INACTIVE, ERR_MASTER_KEY_STAFF_ONLY,
                    ERR_CREDENTIAL_LIMIT_EXCEEDED,
                    ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP,
                    ERR_VENDOR_BADGE_POOL_EXHAUSTED,
                    ERR_EXPIRY_REQUIRED_FOR_VENDOR,
                    ERR_VALIDITY_WINDOW_INVALID)
from middleware import authenticate, require_roles, body
from response import ok_object, paginate
from serializers import ser_person, ser_credential
from validators import get_or_404, req_str, opt_str, req_enum, opt_int
from services import (line_sort_key, forfeiture_line, deactivate_credential,
                      report_lost_cascade, create_charge)

bp = Blueprint("people", __name__)

STAFF_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk"]
PERSON_KINDS = ["RESIDENT", "STAFF", "VENDOR"]
CRED_TYPES = ["METAL_KEY", "FOB", "CARD"]
CRED_LIMIT = 5


# ----------------------------------------------------------------- persons
@bp.route("/persons", methods=["POST"])
def create_person():
    ctx = authenticate()
    require_roles(ctx, ["FrontDesk", "SecurityAdmin"])
    b = body()
    building_id = req_str(b, "building_id")
    full_name = req_str(b, "full_name")
    kind = req_enum(b, "kind", PERSON_KINDS)
    unit_label = opt_str(b, "unit_label")
    employer_name = opt_str(b, "employer_name")
    deposit = opt_int(b, "key_deposit_cents", 0)
    if kind == "RESIDENT" and unit_label is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "unit_label is required when kind is RESIDENT")
    get_or_404("buildings", building_id, "Building")
    now = CLOCK.now()
    p = {
        "id": new_id(),
        "building_id": building_id,
        "full_name": full_name,
        "kind": kind,
        "unit_label": unit_label,
        "employer_name": employer_name,
        "key_deposit_cents": deposit,
        "status": "ACTIVE",
        "moved_out_at": None,
        "seq": next_seq(building_id, "persons"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["persons"][p["id"]] = p
    return ok_object(ser_person(p), 201)


@bp.route("/persons", methods=["GET"])
def list_persons():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["persons"].values())
    for f in ("building_id", "kind", "status"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_person)


@bp.route("/persons/<personId>", methods=["GET"])
def get_person(personId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin", "SecurityOfficer", "FrontDesk",
                        "Resident", "Vendor"])
    if ctx.role in ("Resident", "Vendor"):
        # Ownership: path id must equal X-User-ID (which auth resolved).
        if personId != ctx.user_id:
            raise ApiError(ERR_FORBIDDEN, 403,
                           "May only read own person record")
        p = ctx.person
    else:
        p = get_or_404("persons", personId, "Person")
    return ok_object(ser_person(p))


def _strip_group_memberships(person):
    for g in STORE["access_groups"].values():
        if (g["building_id"] == person["building_id"]
                and person["id"] in g["person_ids"]):
            g["person_ids"] = [x for x in g["person_ids"]
                               if x != person["id"]]
            bump(g)


@bp.route("/persons/<personId>/move-out", methods=["POST"])
def move_out(personId):
    ctx = authenticate()
    require_roles(ctx, ["FrontDesk", "SecurityAdmin"])
    p = get_or_404("persons", personId, "Person")
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_PERSON_INVALID_STATE, 409,
                       "Person is not ACTIVE")
    if p["kind"] != "RESIDENT":
        raise ApiError(ERR_PERSON_KIND_MISMATCH, 409,
                       "Move-out applies only to RESIDENT persons")
    now = CLOCK.now()
    issued = [c for c in STORE["credentials"].values()
              if c["holder_person_id"] == p["id"] and c["status"] == "ISSUED"]
    issued.sort(key=line_sort_key)
    lines = [forfeiture_line(c) for c in issued]
    p["status"] = "MOVED_OUT"
    p["moved_out_at"] = now
    bump(p)
    for c in issued:
        deactivate_credential(c, "MOVE_OUT")
    _strip_group_memberships(p)
    deposit = p["key_deposit_cents"]
    provisional = max(0, deposit - sum(l["fee_cents"] for l in lines))
    create_charge(p["building_id"], p["id"], None, "MOVE_OUT_SETTLEMENT", 0,
                  deposit_cents=deposit,
                  provisional_refund_cents=provisional,
                  line_items=lines, moved_out_at=now)
    return ok_object(ser_person(p))


@bp.route("/persons/<personId>/terminate", methods=["POST"])
def terminate(personId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    p = get_or_404("persons", personId, "Person")
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_PERSON_INVALID_STATE, 409,
                       "Person is not ACTIVE")
    if p["kind"] not in ("STAFF", "VENDOR"):
        raise ApiError(ERR_PERSON_KIND_MISMATCH, 409,
                       "Terminate applies only to STAFF or VENDOR persons")
    for c in list(STORE["credentials"].values()):
        if c["holder_person_id"] == p["id"] and c["status"] == "ISSUED":
            deactivate_credential(c, "TERMINATION")
    _strip_group_memberships(p)
    p["status"] = "TERMINATED"
    bump(p)
    return ok_object(ser_person(p))


# ------------------------------------------------------------- credentials
@bp.route("/credentials", methods=["POST"])
def create_credential():
    ctx = authenticate()
    require_roles(ctx, ["FrontDesk", "SecurityAdmin"])
    b = body()
    building_id = req_str(b, "building_id")
    key_node_id = req_str(b, "key_node_id")
    serial_no = req_str(b, "serial_no")
    type_ = req_enum(b, "type", CRED_TYPES)
    get_or_404("buildings", building_id, "Building")
    node = get_or_404("key_nodes", key_node_id, "KeyNode")
    if node["building_id"] != building_id:
        raise ApiError(ERR_CROSS_BUILDING_REFERENCE, 422,
                       "key_node_id belongs to a different building")
    if any(c["building_id"] == building_id and c["serial_no"] == serial_no
           for c in STORE["credentials"].values()):
        raise ApiError(ERR_SERIAL_EXISTS, 422,
                       "serial_no already used in this building")
    now = CLOCK.now()
    c = {
        "id": new_id(),
        "building_id": building_id,
        "key_node_id": key_node_id,
        "serial_no": serial_no,
        "type": type_,
        "status": "IN_STOCK",
        "holder_person_id": None,
        "issued_at": None,
        "expires_at": None,
        "lost_at": None,
        "deactivated_reason": None,
        "seq": next_seq(building_id, "credentials"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["credentials"][c["id"]] = c
    return ok_object(ser_credential(c), 201)


@bp.route("/credentials", methods=["GET"])
def list_credentials():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin", "SecurityOfficer", "FrontDesk",
                        "Resident", "Vendor"])
    args = request.args
    if ctx.role in ("Resident", "Vendor"):
        if args.get("holder_person_id") != ctx.user_id:
            raise ApiError(ERR_FORBIDDEN, 403,
                           "Must filter holder_person_id to own id")
    rows = list(STORE["credentials"].values())
    for f in ("building_id", "key_node_id", "holder_person_id", "status",
              "type"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_credential)


@bp.route("/credentials/<credentialId>", methods=["GET"])
def get_credential(credentialId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    c = get_or_404("credentials", credentialId, "Credential")
    return ok_object(ser_credential(c))


@bp.route("/credentials/<credentialId>/issue", methods=["POST"])
def issue_credential(credentialId):
    ctx = authenticate()
    require_roles(ctx, ["FrontDesk", "SecurityAdmin"])
    cred = get_or_404("credentials", credentialId, "Credential")
    b = body()
    person_id = b.get("person_id")
    if not isinstance(person_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid person_id")
    person = STORE["persons"].get(person_id)
    if person is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Person not found")
    # State guard
    if cred["status"] != "IN_STOCK":
        raise ApiError(ERR_CREDENTIAL_NOT_ISSUABLE, 409,
                       "Credential is not IN_STOCK")
    # Security-critical rules
    if person["status"] != "ACTIVE":
        raise ApiError(ERR_PERSON_INACTIVE, 422, "Person is not ACTIVE")
    node = STORE["key_nodes"].get(cred["key_node_id"])
    if node is not None and node["level"] != "CHANGE" \
            and person["kind"] != "STAFF":
        raise ApiError(ERR_MASTER_KEY_STAFF_ONLY, 422,
                       "Credentials above CHANGE level issue to STAFF only")
    # Capacity constraints
    held = sum(1 for c in STORE["credentials"].values()
               if c["holder_person_id"] == person["id"]
               and c["status"] == "ISSUED")
    if held >= CRED_LIMIT:
        raise ApiError(ERR_CREDENTIAL_LIMIT_EXCEEDED, 422,
                       "Person already holds 5 issued credentials")
    now = CLOCK.now()
    expires_at = None
    if person["kind"] == "VENDOR":
        for c2 in STORE["credentials"].values():
            if (c2["holder_person_id"] == person["id"]
                    and c2["status"] == "ISSUED"
                    and c2["expires_at"] is not None
                    and c2["expires_at"] > now):
                raise ApiError(ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP, 422,
                               "Vendor already holds a live credential")
        bld = STORE["buildings"][cred["building_id"]]
        live = sum(1 for c in STORE["credentials"].values()
                   if c["building_id"] == cred["building_id"]
                   and c["status"] == "ISSUED"
                   and c["expires_at"] is not None
                   and c["expires_at"] > now)
        if live >= bld["vendor_badge_pool_max"]:
            raise ApiError(ERR_VENDOR_BADGE_POOL_EXHAUSTED, 422,
                           "Building vendor badge pool exhausted")
        # Temporal rules
        raw = b.get("expires_at")
        if raw is None:
            raise ApiError(ERR_EXPIRY_REQUIRED_FOR_VENDOR, 422,
                           "expires_at is required for vendor issue")
        expires_at = parse_ts(raw)
        if expires_at is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Invalid expires_at timestamp")
        if expires_at <= now:
            raise ApiError(ERR_VALIDITY_WINDOW_INVALID, 422,
                           "expires_at must lie strictly in the future")
    else:
        if b.get("expires_at") is not None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "expires_at is forbidden for non-vendor issue")
    cred["status"] = "ISSUED"
    cred["holder_person_id"] = person["id"]
    cred["issued_at"] = now
    cred["expires_at"] = expires_at
    bump(cred)
    return ok_object(ser_credential(cred))


@bp.route("/credentials/<credentialId>/return", methods=["POST"])
def return_credential(credentialId):
    ctx = authenticate()
    require_roles(ctx, ["FrontDesk", "SecurityAdmin"])
    cred = get_or_404("credentials", credentialId, "Credential")
    if cred["status"] != "ISSUED":
        raise ApiError(ERR_CREDENTIAL_NOT_ISSUED, 409,
                       "Credential is not ISSUED")
    cred["status"] = "IN_STOCK"
    cred["holder_person_id"] = None
    cred["issued_at"] = None
    cred["expires_at"] = None
    bump(cred)
    return ok_object(ser_credential(cred))


@bp.route("/credentials/<credentialId>/report-lost", methods=["POST"])
def report_lost(credentialId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin", "FrontDesk", "Resident", "Vendor"])
    cred = get_or_404("credentials", credentialId, "Credential")
    if ctx.role in ("Resident", "Vendor"):
        if cred["holder_person_id"] != ctx.user_id:
            raise ApiError(ERR_FORBIDDEN, 403,
                           "May only report own credentials lost")
    if cred["status"] != "ISSUED":
        raise ApiError(ERR_CREDENTIAL_NOT_ISSUED, 409,
                       "Credential is not ISSUED")
    report_lost_cascade(cred)
    return ok_object(ser_credential(cred))
