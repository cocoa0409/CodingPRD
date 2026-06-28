"""Matter intake, conflict screening, open/close, and conflict waiver."""

from flask import Blueprint, request

import db
import errors
from common import (get_json_body, stamp_create, touch, require_str,
                    optional_int, paginate)
from middleware import authenticate, require_role
from middleware import ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY
from response import object_response, array_response
import serializers
from services import (matter_wip, sync_matter_wip, latest_conflict_check)

bp = Blueprint("matters", __name__)

ALL_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY}
WRITE_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK}


def _norm(name):
    return name.strip().casefold()


# ---------------- Matter CRUD ----------------

@bp.route("/firm/matters", methods=["POST"])
def create_matter():
    _uid, role = authenticate()
    require_role(role, WRITE_ROLES)
    body = get_json_body()
    # Validate body shape first (existence checks below per ordering).
    client_id = body.get("client_id")
    responsible_tk = body.get("responsible_timekeeper_id")
    title = require_str(body, "title", 1, 200)
    matter_rate = optional_int(body, "matter_rate_cents", default=None, minimum=0)
    if client_id is None or not isinstance(client_id, str):
        raise errors.invalid_request("Missing required field 'client_id'.")
    if responsible_tk is None or not isinstance(responsible_tk, str):
        raise errors.invalid_request("Missing required field 'responsible_timekeeper_id'.")
    # Existence of FK body fields.
    if db.clients.get(client_id) is None:
        raise errors.not_found("Client not found.")
    if db.timekeepers.get(responsible_tk) is None:
        raise errors.not_found("Responsible timekeeper not found.")
    with db.LOCK:
        rec = {
            "client_id": client_id,
            "responsible_timekeeper_id": responsible_tk,
            "title": title,
            "matter_rate_cents": matter_rate,
            "status": "INTAKE",
            "wip_fees_cents": 0,
            "wip_expenses_cents": 0,
        }
        stamp_create(rec)
        db.matters[rec["id"]] = rec
    return object_response(serializers.s_matter(rec), status=201)


@bp.route("/firm/matters/<mid>", methods=["GET"])
def get_matter(mid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.matters.get(mid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_matter(rec))


@bp.route("/firm/matters", methods=["GET"])
def list_matters():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    items = list(db.matters.values())
    cid = request.args.get("client_id")
    rtk = request.args.get("responsible_timekeeper_id")
    status = request.args.get("status")
    if cid is not None:
        items = [m for m in items if m["client_id"] == cid]
    if rtk is not None:
        items = [m for m in items if m["responsible_timekeeper_id"] == rtk]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_matter(m) for m in page], limit, offset, total)


@bp.route("/firm/matters/<mid>/wip-summary", methods=["GET"])
def matter_wip_summary(mid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    matter = db.matters.get(mid)
    if matter is None:
        raise errors.not_found()
    with db.LOCK:
        fees, expenses, te_count, ee_count = matter_wip(mid)
        matter["wip_fees_cents"] = fees
        matter["wip_expenses_cents"] = expenses
    return object_response({
        "wip_fees_cents": fees,
        "wip_expenses_cents": expenses,
        "time_entry_count": te_count,
        "expense_entry_count": ee_count,
    })


# ---------------- Conflict screening ----------------

@bp.route("/firm/matters/<mid>/conflict-checks", methods=["POST"])
def run_conflict_check(mid):
    _uid, role = authenticate()
    require_role(role, WRITE_ROLES)
    matter = db.matters.get(mid)
    if matter is None:
        raise errors.not_found()
    body = get_json_body()
    adverse_name = require_str(body, "adverse_party_name", 1, 200)
    adverse_client_id = body.get("adverse_party_client_id")
    if adverse_client_id is not None and not isinstance(adverse_client_id, str):
        raise errors.invalid_request("adverse_party_client_id must be a string.")

    # Existence of FK body field (priority 3) before kind check (priority 4).
    if adverse_client_id is not None:
        if db.clients.get(adverse_client_id) is None:
            # adverse_party_client_id must reference an existing Client; the kind
            # check (§2.7) surfaces a not-an-existing-Client as ERR_CODE_KIND_MISMATCH.
            raise errors.code_kind_mismatch("adverse_party_client_id is not an existing Client.")

    # State: matter must be INTAKE to run the screen (§3.2).
    if matter["status"] != "INTAKE":
        raise errors.invalid_state("Conflict check may only run on an INTAKE matter.")

    # Owning client must exist (precondition).
    if db.clients.get(matter["client_id"]) is None:
        raise errors.not_found("Matter's owning client not found.")

    with db.LOCK:
        # Build candidate set.
        norm_adverse = _norm(adverse_name)
        client_candidates = []
        seen_client_ids = set()
        if adverse_client_id is not None:
            linked = db.clients.get(adverse_client_id)
            if linked is not None:
                client_candidates.append(linked)
                seen_client_ids.add(linked["id"])
        for c in db.clients.values():
            if _norm(c["display_name"]) == norm_adverse and c["id"] not in seen_client_ids:
                client_candidates.append(c)
                seen_client_ids.add(c["id"])
        timekeeper_matches = [t for t in db.timekeepers.values()
                              if _norm(t["full_name"]) == norm_adverse]

        any_candidate = bool(client_candidates) or bool(timekeeper_matches)
        if not any_candidate:
            result = "CLEAR"
            matched_client_id = None
        else:
            result = "FLAGGED"
            if client_candidates:
                client_candidates.sort(key=lambda c: c["_seq"])
                matched_client_id = client_candidates[0]["id"]
            else:
                matched_client_id = None

        rec = {
            "matter_id": mid,
            "adverse_party_client_id": adverse_client_id,
            "adverse_party_name": adverse_name,
            "result": result,
            "matched_client_id": matched_client_id,
            "approved_by_user_id": None,
        }
        stamp_create(rec)
        db.conflict_checks[rec["id"]] = rec

        # Drive the matter: INTAKE -> CONFLICT_PENDING -> CLEARED/BLOCKED.
        matter["status"] = "CONFLICT_PENDING"
        if result == "CLEAR":
            matter["status"] = "CONFLICT_CLEARED"
        else:
            matter["status"] = "CONFLICT_BLOCKED"
        touch(matter)

    return object_response(serializers.s_conflict_check(rec), status=201)


@bp.route("/firm/matters/<mid>/conflict-checks", methods=["GET"])
def list_matter_conflict_checks(mid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.matters.get(mid) is None:
        raise errors.not_found()
    items = [c for c in db.conflict_checks.values() if c["matter_id"] == mid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_conflict_check(c) for c in page], limit, offset, total)


@bp.route("/firm/conflict-checks/<cid>", methods=["GET"])
def get_conflict_check(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.conflict_checks.get(cid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_conflict_check(rec))


@bp.route("/firm/conflict-checks/<cid>/waive", methods=["POST"])
def waive_conflict_check(cid):
    uid, role = authenticate()
    require_role(role, {ROLE_ATTORNEY})
    check = db.conflict_checks.get(cid)
    if check is None:
        raise errors.not_found()
    matter = db.matters.get(check["matter_id"])
    if matter is None:
        raise errors.not_found("Matter not found.")
    # State preconditions: check FLAGGED and matter CONFLICT_BLOCKED.
    if check["result"] != "FLAGGED" or matter["status"] != "CONFLICT_BLOCKED":
        raise errors.invalid_state("Only a FLAGGED check on a CONFLICT_BLOCKED matter may be waived.")
    with db.LOCK:
        check["result"] = "WAIVED"
        check["approved_by_user_id"] = uid
        touch(check)
        matter["status"] = "CONFLICT_CLEARED"
        touch(matter)
    return object_response(serializers.s_conflict_check(check))


# ---------------- Open / Close ----------------

@bp.route("/firm/matters/<mid>/open", methods=["POST"])
def open_matter(mid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ATTORNEY, ROLE_PLATFORM_ADMIN})
    matter = db.matters.get(mid)
    if matter is None:
        raise errors.not_found()
    # State precondition first (priority 5), then conflict gate (priority 8).
    if matter["status"] != "CONFLICT_CLEARED":
        raise errors.invalid_state("Matter must be CONFLICT_CLEARED to open.")
    latest = latest_conflict_check(mid)
    if latest is None or latest["result"] not in ("CLEAR", "WAIVED"):
        raise errors.conflict_not_cleared()
    with db.LOCK:
        matter["status"] = "OPEN"
        touch(matter)
        # Cascade up to client: PROSPECT -> ACTIVE.
        client = db.clients.get(matter["client_id"])
        if client is not None and client["status"] == "PROSPECT":
            client["status"] = "ACTIVE"
            touch(client)
        # Create a ClientTrustLedger in the default trust account if absent.
        _ensure_default_ledger(matter["client_id"])
    return object_response(serializers.s_matter(matter))


def _ensure_default_ledger(client_id):
    """Create a ClientTrustLedger for the client in the default (earliest)
    trust account if none yet exists for that client. Idempotent.
    """
    # Default trust account = earliest-created account, if any exists.
    accounts = sorted(db.trust_accounts.values(), key=lambda a: a["_seq"])
    if not accounts:
        return  # No trust account configured yet; nothing to create.
    default_account = accounts[0]
    for l in db.client_trust_ledgers.values():
        if l["client_id"] == client_id and l["trust_account_id"] == default_account["id"]:
            return
    rec = {
        "trust_account_id": default_account["id"],
        "client_id": client_id,
        "balance_cents": 0,
        "retainer_floor_cents": 0,
    }
    stamp_create(rec)
    db.client_trust_ledgers[rec["id"]] = rec


@bp.route("/firm/matters/<mid>/close", methods=["POST"])
def close_matter(mid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ATTORNEY, ROLE_PLATFORM_ADMIN})
    matter = db.matters.get(mid)
    if matter is None:
        raise errors.not_found()
    if matter["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN matter may be closed.")
    with db.LOCK:
        sync_matter_wip(matter)
        if matter["wip_fees_cents"] != 0 or matter["wip_expenses_cents"] != 0:
            raise errors.matter_has_open_balance("Matter has un-invoiced WIP.")
        for inv in db.invoices.values():
            if inv["matter_id"] == mid and inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID"):
                raise errors.matter_has_open_balance("Matter has an outstanding invoice.")
        matter["status"] = "CLOSED"
        touch(matter)
        # Cascade up: if every sibling matter of the client is CLOSED -> INACTIVE.
        client = db.clients.get(matter["client_id"])
        if client is not None:
            siblings = [m for m in db.matters.values() if m["client_id"] == client["id"]]
            if siblings and all(m["status"] == "CLOSED" for m in siblings):
                client["status"] = "INACTIVE"
                touch(client)
    return object_response(serializers.s_matter(matter))
