"""Family, ChildAccount, and Jar endpoints (PRD §3.1, §3.2)."""
from flask import Blueprint, request

import db
import domain
import serialize
import validate
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import object_response, list_response

bp = Blueprint("families", __name__)


# ----------------------------- Family --------------------------------------
@bp.route("/families", methods=["POST"])
def create_family():
    # Registration is the only call that does not require auth in the usual way,
    # but it is exclusive to Parent and still needs the X-User-ID to mint
    # primary_parent_id. (PRD §3.1)
    identity = authenticate()
    require_role(identity, {"Parent"})
    body = get_json_body()
    family_name = validate.require_str(body, "family_name")

    rec = db.base_fields()
    rec.update({
        "family_name": family_name,
        "primary_parent_id": identity.user_id,
        "funding_balance_cents": 0,
        "status": "ACTIVE",
        "large_spend_threshold_cents": None,
        "low_balance_threshold_cents": None,
    })
    db.families[rec["id"]] = rec
    return object_response(serialize.family(rec), status=201)


@bp.route("/families/<fid>", methods=["GET"])
def read_family(fid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    fam = domain.get_family(fid)
    domain.check_family_owner(identity, fam)
    return object_response(serialize.family(fam))


@bp.route("/families/<fid>/deposit", methods=["POST"])
def deposit(fid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    fam = domain.get_family(fid)
    domain.check_family_owner(identity, fam)
    body = get_json_body()
    amount = validate.require_int(body, "amount_cents")
    validate.bound_positive(amount, "amount_cents")
    fam["funding_balance_cents"] += amount
    db.touch(fam)
    return object_response(serialize.family(fam))


@bp.route("/families/<fid>/alert-thresholds", methods=["POST"])
def alert_thresholds(fid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    fam = domain.get_family(fid)
    domain.check_family_owner(identity, fam)
    body = get_json_body()
    large = validate.require_int(body, "large_spend_threshold_cents")
    low = validate.require_int(body, "low_balance_threshold_cents")
    validate.bound_min(large, 0, "large_spend_threshold_cents")
    validate.bound_min(low, 0, "low_balance_threshold_cents")
    fam["large_spend_threshold_cents"] = large
    fam["low_balance_threshold_cents"] = low
    db.touch(fam)
    return object_response(serialize.family(fam))


@bp.route("/families/<fid>/suspend", methods=["POST"])
def suspend(fid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    fam = domain.get_family(fid)
    domain.check_family_owner(identity, fam)
    fam["status"] = "SUSPENDED"
    db.touch(fam)
    return object_response(serialize.family(fam))


@bp.route("/families/<fid>/reactivate", methods=["POST"])
def reactivate(fid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    fam = domain.get_family(fid)
    domain.check_family_owner(identity, fam)
    fam["status"] = "ACTIVE"
    db.touch(fam)
    return object_response(serialize.family(fam))


# --------------------------- ChildAccount ----------------------------------
def _create_jar(child_id, jar_type):
    rec = db.base_fields()
    rec.update({
        "child_account_id": child_id,
        "jar_type": jar_type,
        "balance_cents": 0,
        "lifetime_credited_cents": 0,
    })
    db.jars[rec["id"]] = rec
    return rec


@bp.route("/families/<fid>/child-accounts", methods=["POST"])
def create_child(fid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    fam = domain.get_family(fid)
    domain.check_family_owner(identity, fam)
    body = get_json_body()
    display_name = validate.require_str(body, "display_name")
    birthdate = validate.require_str(body, "birthdate")

    child = db.base_fields()
    child.update({
        "family_id": fid,
        "display_name": display_name,
        "birthdate": birthdate,
        "status": "ACTIVE",
    })
    db.child_accounts[child["id"]] = child

    # Generative act: 3 jars, 1 debit card, 1 interest-match config.
    for jt in ("SPEND", "SAVE", "GIVE"):
        _create_jar(child["id"], jt)

    card = db.base_fields()
    card.update({
        "child_account_id": child["id"],
        "lock_state": "UNLOCKED",
        "funding_state": "DRAINED",
        "held_cents": 0,
        "available_cents": 0,
    })
    db.debit_cards[card["id"]] = card

    cfg = db.base_fields()
    cfg.update({
        "child_account_id": child["id"],
        "annual_rate_bps": None,
        "monthly_cap_cents": None,
        "accrual_method": None,
        "status": "DISABLED",
    })
    db.interest_match_configs[cfg["id"]] = cfg

    return object_response(serialize.child_account(child), status=201)


@bp.route("/families/<fid>/child-accounts", methods=["GET"])
def list_children(fid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    fam = domain.get_family(fid)
    domain.check_family_owner(identity, fam)
    items = [c for c in db.child_accounts.values() if c["family_id"] == fid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response([serialize.child_account(c) for c in items], request.args)


@bp.route("/child-accounts/<cid>", methods=["GET"])
def read_child(cid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    return object_response(serialize.child_account(child))


@bp.route("/child-accounts/<cid>/archive", methods=["POST"])
def archive_child(cid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    child["status"] = "ARCHIVED"
    db.touch(child)
    return object_response(serialize.child_account(child))


@bp.route("/child-accounts/<cid>/fund-jar", methods=["POST"])
def fund_jar(cid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    body = get_json_body()
    jar_type = validate.require_enum(body, "jar_type", {"SPEND", "SAVE", "GIVE"})
    amount = validate.require_int(body, "amount_cents")
    validate.bound_positive(amount, "amount_cents")

    # Money-movement gates (family then child).
    domain.gate_money_movement(child)

    fam = db.families[child["family_id"]]
    if fam["funding_balance_cents"] < amount:
        raise err("ERR_INSUFFICIENT_FUNDING", "Funding wallet has insufficient balance")

    fam["funding_balance_cents"] -= amount
    db.touch(fam)
    jar = domain.jar_of_type(cid, jar_type)
    domain.credit_jar(jar, amount)
    return object_response(serialize.jar(jar))


# ------------------------------- Jar ---------------------------------------
@bp.route("/child-accounts/<cid>/jars", methods=["GET"])
def list_jars(cid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    items = domain.child_jars(cid)
    jar_type = request.args.get("jar_type")
    if jar_type is not None:
        items = [j for j in items if j["jar_type"] == jar_type]
    return list_response([serialize.jar(j) for j in items], request.args)


@bp.route("/jars/<jid>", methods=["GET"])
def read_jar(jid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    jar = domain.get_jar(jid)
    child = domain.get_child(jar["child_account_id"])
    domain.check_child_owner(identity, child)
    return object_response(serialize.jar(jar))
