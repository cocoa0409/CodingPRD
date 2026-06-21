"""TitleLien routes (PRD 3.4)."""
from flask import Blueprint

import db
import lookups
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public
from validate import get_body, require_str, parse_pagination, paginate

bp = Blueprint("liens", __name__)


def _sorted_public(entities):
    rows = sorted(entities, key=lambda e: e["_seq"])
    return [public(e) for e in rows]


@bp.route("/atl/title-liens/<lien_id>", methods=["GET"])
def get_lien(lien_id):
    _, role = authenticate()
    require_role(role, {"TitleClerk", "Underwriter", "ComplianceAdmin", "LoanServicer"})
    lien = lookups.get_or_404(db.title_liens, lien_id)
    return success(public(lien), status=200)


@bp.route("/atl/loans/<loan_id>/title-liens", methods=["GET"])
def list_loan_liens(loan_id):
    _, role = authenticate()
    require_role(role, {"TitleClerk", "Underwriter", "ComplianceAdmin", "LoanServicer"})
    lookups.get_or_404(db.loans, loan_id)
    limit, offset = parse_pagination()
    rows = [l for l in db.title_liens.values() if l["loan_id"] == loan_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


@bp.route("/atl/title-liens/<lien_id>/file", methods=["POST"])
def file_lien(lien_id):
    _, role = authenticate()
    require_role(role, {"TitleClerk"})
    lien = lookups.get_or_404(db.title_liens, lien_id)
    body = get_body()

    dmv_reference = require_str(body, "dmv_reference")

    # State legality (priority 6): only a PENDING lien may be filed (PRD 3.4).
    if lien["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "lien not in PENDING")

    # Cross-entity guard (priority 9): loan must be OUTSTANDING (PRD 3.4).
    loan = db.loans.get(lien["loan_id"])
    if loan is None or loan["payoff_status"] != "OUTSTANDING":
        raise err("ERR_LIEN_LOAN_NOT_OUTSTANDING", "loan payoff_status not OUTSTANDING")

    lien["dmv_reference"] = dmv_reference
    lien["status"] = "FILED"
    db.touch(lien)
    return success(public(lien), status=200)
