"""Family-portal seats and delegated authority records."""

from flask import Blueprint

import constants as K
import derive
import gates
import store
from errors import ApiError
from routes.helpers import one, listing, filtered
from util import parse_dt

bp = Blueprint("portal", __name__)

PARTY_READ = ["MOVE_MANAGER", "BILLING_ADMIN", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]
AUTH_READ = ["MOVE_MANAGER", "BILLING_ADMIN", "CLIENT", "POWER_OF_ATTORNEY"]

AUTH_TERMINAL = ["REVOKED", "EXPIRED"]


# ---------------------------------------------------------------------------
# portal parties
# ---------------------------------------------------------------------------

@bp.route("/portal-parties", methods=["POST"])
def create_party():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"), ("party_type", "string"),
                                    ("display_name", "string"), ("email", "string")],
                          optional=[("client_id", "string")])
    fks = gates.resolve_body_fks(req.body)
    engagement = fks["engagement_id"]
    gates.gate3(engagement)

    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "client_id": req.body.get("client_id"),
        "party_type": req.body["party_type"],
        "display_name": req.body["display_name"],
        "email": req.body["email"],
    })
    store.insert("portal_parties", record)
    return one("portal_parties", record, 201)


@bp.route("/portal-parties", methods=["GET"])
def list_parties():
    req = gates.preflight(PARTY_READ, is_list=True)
    rows = filtered(store.all_of("portal_parties"), req.args,
                    ["engagement_id", "client_id", "party_type"])
    return listing("portal_parties", req, rows)


@bp.route("/portal-parties/<pid>", methods=["GET"])
def read_party(pid):
    req = gates.preflight(PARTY_READ)
    record = gates.path_record("portal_parties", pid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("portal_parties", record)


# ---------------------------------------------------------------------------
# authority records
# ---------------------------------------------------------------------------

@bp.route("/authority-records", methods=["POST"])
def create_authority():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"),
                                    ("holder_party_id", "string"),
                                    ("authority_scope", "string"),
                                    ("effective_from_utc", "datetime"),
                                    ("effective_to_utc", "datetime")],
                          optional=[("approval_ceiling_cents", "int")])
    fks = gates.resolve_body_fks(req.body)
    engagement = fks["engagement_id"]
    gates.gate3(engagement)
    gates.gate4_party_membership(engagement, [req.body["holder_party_id"]])

    if parse_dt(req.body["effective_to_utc"]) <= parse_dt(req.body["effective_from_utc"]):
        raise ApiError("ERR_AUTHORITY_WINDOW_INVALID")

    ceiling = req.body.get("approval_ceiling_cents")
    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "holder_party_id": req.body["holder_party_id"],
        "authority_scope": req.body["authority_scope"],
        "approval_ceiling_cents": K.AUTHORITY_DEFAULT_CEILING_CENTS if ceiling is None else ceiling,
        "status": "PENDING",
        "effective_from_utc": req.body["effective_from_utc"],
        "effective_to_utc": req.body["effective_to_utc"],
        "suspend_count": 0,
        "revoked_reason": None,
    })
    store.insert("authority_records", record)
    return one("authority_records", record, 201)


@bp.route("/authority-records", methods=["GET"])
def list_authorities():
    req = gates.preflight(AUTH_READ, is_list=True)
    rows = filtered(store.all_of("authority_records"), req.args,
                    ["engagement_id", "holder_party_id", "status"])
    return listing("authority_records", req, rows)


@bp.route("/authority-records/<aid>", methods=["GET"])
def read_authority(aid):
    req = gates.preflight(AUTH_READ)
    record = gates.path_record("authority_records", aid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("authority_records", record)


@bp.route("/authority-records/<aid>/activate", methods=["POST"])
def activate_authority(aid):
    gates.preflight(["MOVE_MANAGER"])
    record = gates.path_record("authority_records", aid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["PENDING"], AUTH_TERMINAL)
    now = parse_dt(store.now_iso())
    if now < parse_dt(record["effective_from_utc"]) or now >= parse_dt(record["effective_to_utc"]):
        raise ApiError("ERR_AUTHORITY_WINDOW_INVALID")
    record["status"] = "ACTIVE"
    store.touch(record)
    return one("authority_records", record)


@bp.route("/authority-records/<aid>/suspend", methods=["POST"])
def suspend_authority(aid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record = gates.path_record("authority_records", aid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["ACTIVE"], AUTH_TERMINAL)
    if record["suspend_count"] >= K.MAX_AUTHORITY_SUSPENSIONS:
        raise ApiError("ERR_HOLD_ESCALATION_LIMIT")
    record["status"] = "SUSPENDED"
    record["suspend_count"] = record["suspend_count"] + 1
    record["revoked_reason"] = req.body["reason"]
    store.touch(record)
    return one("authority_records", record)


@bp.route("/authority-records/<aid>/reinstate", methods=["POST"])
def reinstate_authority(aid):
    gates.preflight(["MOVE_MANAGER"])
    record = gates.path_record("authority_records", aid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["SUSPENDED"], AUTH_TERMINAL)
    if parse_dt(store.now_iso()) >= parse_dt(record["effective_to_utc"]):
        raise ApiError("ERR_AUTHORITY_WINDOW_INVALID")
    record["status"] = "ACTIVE"
    store.touch(record)
    return one("authority_records", record)


@bp.route("/authority-records/<aid>/revoke", methods=["POST"])
def revoke_authority(aid):
    req = gates.preflight(["MOVE_MANAGER", "CLIENT"], required=[("reason", "nes")])
    record = gates.path_record("authority_records", aid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["PENDING", "ACTIVE", "SUSPENDED"], AUTH_TERMINAL)
    record["status"] = "REVOKED"
    record["revoked_reason"] = req.body["reason"]
    store.touch(record)
    return one("authority_records", record)
