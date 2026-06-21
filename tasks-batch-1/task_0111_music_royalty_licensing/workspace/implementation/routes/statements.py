"""Statement routes: open, read, list, ledger, finalize, reopen."""
from flask import Blueprint, request

import db
from errors import (fail, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_STATEMENT_PERIOD_OVERLAP,
                    ERR_UNALLOCATED_USAGE_IN_PERIOD, ERR_PAYOUT_EXISTS,
                    ERR_INVALID_REQUEST)
from middleware import authorize, get_auth
from response import success
from services import serialize as S
from services import calculations as C
from services.common import (stamp_create, touch, require_body, require_int,
                             require_datetime, parse_pagination, paginate,
                             sorted_by_creation, parse_dt, round_half_up)
from services.lookup import path_get, fk_get, require_owner

bp = Blueprint("statements", __name__)

ENTRY_TYPES = {"EARNING", "RECOUPMENT", "WITHHOLDING"}


@bp.route("/statements", methods=["POST"])
def create_statement():
    authorize({"RoyaltyOperator"})
    data = require_body(request.get_json(silent=True))
    rightsholder_id = data.get("rightsholder_id")
    fk_get(db.rightsholders, rightsholder_id)
    period_start_dt = require_datetime(data, "period_start")
    period_end_dt = require_datetime(data, "period_end")
    new_start = period_start_dt.timestamp()
    new_end = period_end_dt.timestamp()
    # Period overlap (priority 15): plain half-open, no buffer; touching allowed.
    for stmt in db.statements.values():
        if stmt["rightsholder_id"] != rightsholder_id:
            continue
        if stmt["status"] not in ("DRAFT", "FINALIZED"):  # non-PAID
            continue
        ex_start = parse_dt(stmt["period_start"]).timestamp()
        ex_end = parse_dt(stmt["period_end"]).timestamp()
        non_overlap = (new_start >= ex_end) or (new_end <= ex_start)
        if not non_overlap:
            fail(ERR_STATEMENT_PERIOD_OVERLAP,
                 "Statement period overlaps an existing non-PAID statement")
    rec = {
        "rightsholder_id": rightsholder_id,
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "gross_earnings_cents": 0,
        "recoupment_applied_cents": 0,
        "withholding_cents": 0,
        "net_payable_cents": 0,
        "carried_forward_cents": 0,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.statements[rec["id"]] = rec
    return success(S.statement(rec), status=201)


@bp.route("/statements/<rid>", methods=["GET"])
def get_statement(rid):
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    rec = path_get(db.statements, rid)
    require_owner(rec["rightsholder_id"], user_id, role)
    return success(S.statement(rec))


@bp.route("/statements", methods=["GET"])
def list_statements():
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    limit, offset = parse_pagination(request.args)
    items = list(db.statements.values())
    rightsholder_id = request.args.get("rightsholder_id")
    status = request.args.get("status")
    if rightsholder_id is not None:
        items = [s for s in items if s["rightsholder_id"] == rightsholder_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if role == "Rightsholder":
        items = [s for s in items if s["rightsholder_id"] == user_id]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.statement(s) for s in page], pagination=meta)


@bp.route("/statements/<rid>/ledger", methods=["GET"])
def list_ledger(rid):
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    stmt = path_get(db.statements, rid)
    require_owner(stmt["rightsholder_id"], user_id, role)
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.ledger_entries.values() if e["statement_id"] == rid]
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.ledger_entry(e) for e in page], pagination=meta)


def _has_unallocated_usage_in_period(stmt):
    """True if some INGESTED usage event whose distribution targets this
    rightsholder has occurred_at inside [period_start, period_end) (PRD §3.6)."""
    rh_id = stmt["rightsholder_id"]
    start = parse_dt(stmt["period_start"]).timestamp()
    end = parse_dt(stmt["period_end"]).timestamp()
    for event in db.usage_events.values():
        if event["status"] != "INGESTED":
            continue
        occ = parse_dt(event["occurred_at"]).timestamp()
        if not (start <= occ < end):
            continue
        recording = db.recordings.get(event["recording_id"])
        if recording is None:
            continue
        # Distribution targets: PERFORMANCE -> composition holders of the work;
        # MECHANICAL -> recording-share holders.
        if event["usage_type"] == "PERFORMANCE":
            targets = {s["rightsholder_id"] for s in db.composition_shares.values()
                       if s["work_id"] == recording["work_id"]}
        else:
            targets = {s["rightsholder_id"] for s in db.recording_shares.values()
                       if s["recording_id"] == recording["id"]}
        if rh_id in targets:
            return True
    return False


@bp.route("/statements/<rid>/finalize", methods=["POST"])
def finalize_statement(rid):
    authorize({"RoyaltyOperator"})
    stmt = path_get(db.statements, rid)
    data = require_body(request.get_json(silent=True))
    # expected_statement_version is required (PRD §2.7).
    expected_version = require_int(data, "expected_statement_version")
    # PRD §3.6 prose order: DRAFT status, then version match, then unallocated.
    if stmt["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "Finalize requires DRAFT status")
    if expected_version != stmt["version"]:
        fail(ERR_STALE_VERSION, "expected_statement_version does not match")
    if _has_unallocated_usage_in_period(stmt):
        fail(ERR_UNALLOCATED_USAGE_IN_PERIOD,
             "An unallocated usage event targets this rightsholder within the period")

    rh = db.rightsholders[stmt["rightsholder_id"]]

    # 1. Recoupment over rightsholder's ACTIVE advances, oldest first.
    active_advances = [a for a in db.advances.values()
                       if a["rightsholder_id"] == rh["id"] and a["status"] == "ACTIVE"]
    active_advances.sort(key=lambda a: (a["created_at"], a["_seq"]))
    recoupment_applied, takes = C.advance_recoupment(
        stmt["gross_earnings_cents"], active_advances)
    for adv, take in takes:
        adv["recouped_cents"] += take
        if adv["recouped_cents"] == adv["principal_cents"]:
            adv["status"] = "RECOUPED"
        touch(adv)
        # RECOUPMENT ledger entry (negative), source_type ADVANCE.
        entry = {
            "id": db.new_id(),
            "created_at": db.now_iso(),
            "statement_id": stmt["id"],
            "rightsholder_id": stmt["rightsholder_id"],
            "entry_type": "RECOUPMENT",
            "source_type": "ADVANCE",
            "source_id": adv["id"],
            "amount_cents": -take,
            "_seq": db.next_seq(),
        }
        db.ledger_entries[entry["id"]] = entry
    stmt["recoupment_applied_cents"] = recoupment_applied

    # 2. Withholding = round_half_up((gross - recoupment) * withholding_pct).
    base = stmt["gross_earnings_cents"] - recoupment_applied
    withholding = round_half_up(base * float(rh["withholding_pct"])) if rh["withholding_pct"] else 0
    if withholding:
        entry = {
            "id": db.new_id(),
            "created_at": db.now_iso(),
            "statement_id": stmt["id"],
            "rightsholder_id": stmt["rightsholder_id"],
            "entry_type": "WITHHOLDING",
            "source_type": "STATEMENT",
            "source_id": stmt["id"],
            "amount_cents": -withholding,
            "_seq": db.next_seq(),
        }
        db.ledger_entries[entry["id"]] = entry
    stmt["withholding_cents"] = withholding

    # 3. net_payable = max(0, gross - recoupment - withholding).
    net = max(0, stmt["gross_earnings_cents"] - recoupment_applied - withholding)
    # 4. minimum-payout carry-forward.
    if net < rh["minimum_payout_cents"]:
        stmt["carried_forward_cents"] = net
        net = 0
    else:
        stmt["carried_forward_cents"] = 0
    stmt["net_payable_cents"] = net

    stmt["status"] = "FINALIZED"
    touch(stmt)
    # Rightsholder derived totals recomputed read-time; touch to reflect cascade.
    touch(rh)
    return success(S.statement(stmt))


@bp.route("/statements/<rid>/reopen", methods=["POST"])
def reopen_statement(rid):
    authorize({"RoyaltyOperator"})
    stmt = path_get(db.statements, rid)
    data = require_body(request.get_json(silent=True))
    expected_version = require_int(data, "expected_statement_version")
    # PRD §3.6 prose order: FINALIZED status, then no SETTLED payout, then version.
    if stmt["status"] != "FINALIZED":
        fail(ERR_INVALID_STATE, "Reopen requires FINALIZED status")
    for p in db.payouts.values():
        if p["statement_id"] == stmt["id"] and p["status"] == "SETTLED":
            fail(ERR_PAYOUT_EXISTS, "A SETTLED payout references this statement")
    if expected_version != stmt["version"]:
        fail(ERR_STALE_VERSION, "expected_statement_version does not match")

    rh = db.rightsholders[stmt["rightsholder_id"]]

    # Reverse each RECOUPMENT entry: restore advance.recouped_cents; RECOUPED ->
    # ACTIVE if drops below principal. Then remove the recoupment + withholding
    # ledger entries for this statement.
    to_remove = []
    for entry in list(db.ledger_entries.values()):
        if entry["statement_id"] != stmt["id"]:
            continue
        if entry["entry_type"] == "RECOUPMENT":
            adv = db.advances.get(entry["source_id"])
            if adv is not None:
                adv["recouped_cents"] += entry["amount_cents"]  # amount is negative
                if adv["status"] == "RECOUPED" and adv["recouped_cents"] < adv["principal_cents"]:
                    adv["status"] = "ACTIVE"
                touch(adv)
            to_remove.append(entry["id"])
        elif entry["entry_type"] == "WITHHOLDING":
            to_remove.append(entry["id"])
    for eid in to_remove:
        del db.ledger_entries[eid]

    stmt["recoupment_applied_cents"] = 0
    stmt["withholding_cents"] = 0
    stmt["net_payable_cents"] = 0
    stmt["carried_forward_cents"] = 0
    stmt["status"] = "DRAFT"
    touch(stmt)
    touch(rh)
    return success(S.statement(stmt))
