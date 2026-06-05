"""DisclosureAcceptance endpoints (Reg Z, PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, require_borrower_owns
from response import success
from services import engine
from services.engine import serialize_disclosure
from routes.common import (
    get_json_body, parse_pagination, paginate, sort_by_created,
    require_application, require_disclosure,
)

bp = Blueprint("disclosures", __name__)


@bp.route("/disclosure-acceptances", methods=["POST"])
def create_disclosure():
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    body = get_json_body()

    application_id = body.get("application_id")
    if not application_id or not isinstance(application_id, str):
        raise err("ERR_INVALID_REQUEST", "Missing required field 'application_id'.")
    app = require_application(application_id)
    require_borrower_owns(role, uid, app["borrower_id"])

    accepted = body.get("accepted")
    if not isinstance(accepted, bool):
        raise err("ERR_INVALID_REQUEST", "Field 'accepted' must be a boolean.")

    # Disclosure is recorded against an APPROVED application.
    if app["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE",
                  "Disclosure may only be accepted on an APPROVED application.")

    installment_count = 4 if app["plan_type"] == "PAY_IN_4" else app["term_months"]
    d = {
        "id": db.new_id(),
        "application_id": application_id,
        "disclosed_apr_bps": app["apr_bps"],
        "disclosed_finance_charge_cents": app["finance_charge_cents"],
        "disclosed_total_of_payments_cents": app["total_of_payments_cents"],
        "disclosed_installment_count": installment_count,
        "accepted": accepted,
    }
    # Immutable audit record: only id + created_at (PRD §2.4).
    from services.engine import stamp_new
    stamp_new(d, with_version=False)
    db.disclosure_acceptances[d["id"]] = d
    return success(serialize_disclosure(d), status=201)


@bp.route("/disclosure-acceptances/<disclosure_id>", methods=["GET"])
def get_disclosure(disclosure_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower"})
    d = require_disclosure(disclosure_id)
    app = db.applications.get(d["application_id"])
    if app is not None:
        require_borrower_owns(role, uid, app["borrower_id"])
    return success(serialize_disclosure(d), status=200)


@bp.route("/disclosure-acceptances", methods=["GET"])
def list_disclosures():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower"})
    limit, offset = parse_pagination()
    application_filter = request.args.get("application_id")

    rows = list(db.disclosure_acceptances.values())
    if application_filter is not None:
        rows = [d for d in rows if d["application_id"] == application_filter]
    if role == "Borrower":
        rows = [d for d in rows
                if (db.applications.get(d["application_id"]) or {}).get("borrower_id") == uid]

    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([serialize_disclosure(d) for d in page],
                   status=200, pagination=meta)
