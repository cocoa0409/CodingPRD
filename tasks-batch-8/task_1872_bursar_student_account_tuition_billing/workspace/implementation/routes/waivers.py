from flask import Blueprint

from db import store, base_fields, touch
from errors import (err, ERR_ACCOUNT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
                    ERR_ACCOUNT_STATE_INVALID, ERR_AMOUNT_INVALID,
                    ERR_WAIVER_STATE_INVALID, ERR_WAIVER_NOTHING_ELIGIBLE,
                    ERR_STALE_VERSION)
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_str, req_int, req_enum, list_response
from serialize import ser_waiver
from services.core import (post_entry, account_entries, open_amount,
                           recompute_account)

bp = Blueprint("waivers", __name__)


def _eligible_targets(waiver, account):
    """Waiver waterfall targets: CHARGE entries only. A WAIVER considers
    TUITION-kind entries only; a SCHOLARSHIP considers tuition first, then
    fees; within each group oldest due_date first, created_at ASC tie-break."""
    rows = [e for e in account_entries(account["id"])
            if e["entry_type"] == "CHARGE" and open_amount(e) > 0]
    tuition = sorted((e for e in rows if e["charge_kind"] == "TUITION"),
                     key=lambda e: (e["due_date"], e["_seq"]))
    if waiver["kind"] == "WAIVER":
        return tuition
    fees = sorted((e for e in rows if e["charge_kind"] == "FEE"),
                  key=lambda e: (e["due_date"], e["_seq"]))
    return tuition + fees


@bp.post("/bursar/waivers")
def create_waiver():
    uid, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    body = json_body()
    account_id = req_str(body, "account_id")
    kind = req_enum(body, "kind", ("WAIVER", "SCHOLARSHIP"))
    awarded = req_int(body, "awarded_cents")
    account = store.accounts.get(account_id)
    if account is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if account["status"] not in ("OPEN", "PAST_DUE"):
        raise err(ERR_ACCOUNT_STATE_INVALID,
                  "Waiver award requires the account to be OPEN or PAST_DUE")
    if awarded <= 0:
        raise err(ERR_AMOUNT_INVALID, "awarded_cents must be positive")
    w = base_fields()
    w.update({
        "account_id": account["id"], "kind": kind, "awarded_cents": awarded,
        "posted_cents": 0, "allocations": [], "status": "AWARDED",
    })
    store.waivers[w["id"]] = w
    return success(ser_waiver(w), status=201)


@bp.post("/bursar/waivers/<wid>/post")
def post_waiver(wid):
    uid, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    w = store.waivers.get(wid)
    if w is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Waiver not found")
    account = store.accounts[w["account_id"]]
    body = json_body()
    expected = req_int(body, "expected_account_version")
    if w["status"] != "AWARDED":
        raise err(ERR_WAIVER_STATE_INVALID, "Only an AWARDED waiver can be posted")
    targets = _eligible_targets(w, account)
    eligible_open = sum(open_amount(e) for e in targets)
    if eligible_open <= 0:
        raise err(ERR_WAIVER_NOTHING_ELIGIBLE, "No eligible open charge amount")
    # OCC is evaluated last, after every business rule has passed.
    if expected != account["version"]:
        raise err(ERR_STALE_VERSION, "expected_account_version does not match the account version")

    remaining = min(w["awarded_cents"], eligible_open)
    allocations = []
    for e in targets:
        if remaining <= 0:
            break
        alloc = min(open_amount(e), remaining)
        if alloc > 0:
            allocations.append({"ledger_entry_id": e["id"], "amount_cents": alloc})
            remaining -= alloc
    posted = sum(a["amount_cents"] for a in allocations)
    post_entry(account["id"], "WAIVER", posted, source_ref=w["id"],
               memo="Waiver/scholarship posting")
    w["posted_cents"] = posted
    w["allocations"] = allocations
    w["status"] = "POSTED"
    touch(w)
    recompute_account(account, force_bump=True)
    return success(ser_waiver(w))


@bp.post("/bursar/waivers/<wid>/revoke")
def revoke_waiver(wid):
    uid, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    w = store.waivers.get(wid)
    if w is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Waiver not found")
    if w["status"] == "AWARDED":
        # Nothing was ever posted: no ledger entry.
        w["status"] = "REVOKED"
        touch(w)
        return success(ser_waiver(w))
    if w["status"] == "POSTED":
        account = store.accounts[w["account_id"]]
        post_entry(account["id"], "WAIVER_REVERSAL", w["posted_cents"],
                   source_ref=w["id"], memo="Waiver reversal")
        # Allocations unwind: open amounts count POSTED waivers only.
        w["status"] = "REVOKED"
        touch(w)
        recompute_account(account, force_bump=True)
        return success(ser_waiver(w))
    raise err(ERR_WAIVER_STATE_INVALID, "Waiver is already REVOKED")


@bp.get("/bursar/accounts/<aid>/waivers")
def list_waivers(aid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    a = store.accounts.get(aid)
    if a is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if role == "Student" and a["student_id"] != uid:
        forbid()
    rows = [w for w in store.waivers.values() if w["account_id"] == aid]
    rows.sort(key=lambda w: w["_seq"])
    return list_response(rows, ser_waiver)
