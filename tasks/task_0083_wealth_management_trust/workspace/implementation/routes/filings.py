"""Tax filings (Form 1041): create/file/amend/refile (PRD §3.7, §3.9)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize, calc
from services.helpers import get_json_body, must_exist
from services.ledger import recompute_trust_balances, recompute_inclusion_ratio

bp = Blueprint("filings", __name__)


@bp.route("/accounts/<aid>/filings", methods=["POST"])
def create_filing(aid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    a = must_exist(db.accounts, aid)
    body = get_json_body()
    supersedes = body.get("supersedes_filing_id")
    if supersedes is not None:
        if not isinstance(supersedes, str):
            raise err("ERR_VALIDATION", "supersedes_filing_id must be a string")
        must_exist(db.filings, supersedes)
    with db.LOCK:
        if a["status"] != "CLOSED":
            raise err("ERR_INVALID_STATE", "A filing may only be created on a CLOSED period.")
        f = db.base_fields()
        f.update({
            "account_id": aid,
            "taxable_income_snapshot_cents": 0,
            "tax_due_cents": 0,
            "status": "DRAFT",
            "supersedes_filing_id": supersedes,
        })
        db.filings[f["id"]] = f
    return success(serialize.filing(f), status=201)


@bp.route("/filings/<fid>", methods=["GET"])
def get_filing(fid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    f = must_exist(db.filings, fid)
    return success(serialize.filing(f))


@bp.route("/accounts/<aid>/filings", methods=["GET"])
def list_account_filings(aid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    must_exist(db.accounts, aid)
    limit, offset = parse_pagination()
    items = [f for f in db.filings.values() if f["account_id"] == aid]
    page, meta = paginate(items, limit, offset)
    return success([serialize.filing(f) for f in page], pagination=meta)


@bp.route("/filings", methods=["GET"])
def list_filings():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    supersedes = request.args.get("supersedes_filing_id")
    items = list(db.filings.values())
    if account_id is not None:
        items = [f for f in items if f["account_id"] == account_id]
    if supersedes is not None:
        items = [f for f in items if f["supersedes_filing_id"] == supersedes]
    page, meta = paginate(items, limit, offset)
    return success([serialize.filing(f) for f in page], pagination=meta)


@bp.route("/filings/<fid>/file", methods=["POST"])
def file_filing(fid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    f = must_exist(db.filings, fid)
    a = db.accounts[f["account_id"]]
    t = db.trusts[a["trust_id"]]
    with db.LOCK:
        if f["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE")
        if a["status"] != "CLOSED":
            raise err("ERR_INVALID_STATE", "Cannot file an OPEN period.")
        # No existing FILED (not-yet-superseded) filing for this account.
        for other in db.filings.values():
            if other["account_id"] == a["id"] and other["status"] == "FILED":
                raise err("ERR_INVALID_STATE", "An active filing already exists for this period.")

        f["taxable_income_snapshot_cents"] = a["taxable_income_cents"]
        f["tax_due_cents"] = calc.trust_income_tax(
            f["taxable_income_snapshot_cents"], t["is_grantor_trust"]
        )
        f["status"] = "FILED"
        # CASCADE step 1: account CLOSED -> FILED.
        a["status"] = "FILED"
        db.touch(a)
        # CASCADE step 2: spawn TAX_PAYMENT system disbursement when tax > 0.
        if f["tax_due_cents"] > 0:
            disb = db.base_fields()
            disb.update({
                "account_id": a["id"],
                "amount_cents": f["tax_due_cents"],
                "expense_kind": "TAX_PAYMENT",
                "ledger_side": "PRINCIPAL",
                "is_system_generated": True,
            })
            db.disbursements[disb["id"]] = disb
            recompute_trust_balances(t)
            recompute_inclusion_ratio(t)
            db.touch(t)
        db.touch(f)
    return success(serialize.filing(f))


@bp.route("/filings/<fid>/amend", methods=["POST"])
def amend_filing(fid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    f = must_exist(db.filings, fid)
    with db.LOCK:
        if f["status"] != "FILED":
            raise err("ERR_INVALID_STATE")
        f["status"] = "AMENDED"
        db.touch(f)
    return success(serialize.filing(f))


@bp.route("/filings/<fid>/refile", methods=["POST"])
def refile_filing(fid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    f = must_exist(db.filings, fid)
    a = db.accounts[f["account_id"]]
    t = db.trusts[a["trust_id"]]
    with db.LOCK:
        if f["status"] != "AMENDED":
            raise err("ERR_INVALID_STATE")
        # Mark prior original filing as SUPERSEDED.
        if f["supersedes_filing_id"] is not None:
            prior = db.filings.get(f["supersedes_filing_id"])
            if prior is not None:
                prior["status"] = "SUPERSEDED"
                db.touch(prior)
        # Recompute tax from current snapshot.
        f["tax_due_cents"] = calc.trust_income_tax(
            f["taxable_income_snapshot_cents"], t["is_grantor_trust"]
        )
        f["status"] = "FILED"
        db.touch(f)
    return success(serialize.filing(f))
