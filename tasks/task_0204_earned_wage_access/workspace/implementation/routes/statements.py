"""ReconciliationStatement endpoints: create/recompute, fetch, list, sign.

Create is idempotent on an unsigned statement (PRD §3.11): it returns 200 and
recomputes in place rather than minting a second statement for the period.
"""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import object_response, array_response
from services import domain, serialize, validate

bp = Blueprint("statements", __name__)


@bp.route("/reconciliation-statements", methods=["POST"])
def create_or_recompute_statement():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    body = validate.get_body()
    pay_period_id = validate.require_str(body, "pay_period_id")
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise errors.cross_employer("pay_period_id does not resolve")

    existing = domain.get_period_statement(pay_period_id)
    if existing is not None:
        # Idempotent recompute in place (do not recompute a SIGNED statement's
        # aggregates beyond returning it; PRD §3.11 says DRAFT recomputes in place).
        if existing["status"] == "DRAFT":
            domain.recompute_period_statement(pay_period_id, create_if_absent=False)
        return object_response(serialize.reconciliation_statement(existing), status=200)

    stmt = domain.recompute_period_statement(pay_period_id, create_if_absent=True)
    # Endpoint returns 200 OK (create-or-recompute in place), per PRD §4.
    return object_response(serialize.reconciliation_statement(stmt), status=200)


@bp.route("/reconciliation-statements/<statement_id>", methods=["GET"])
def get_statement(statement_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    stmt = db.reconciliation_statements.get(statement_id)
    if stmt is None:
        raise errors.not_found()
    return object_response(serialize.reconciliation_statement(stmt))


@bp.route("/reconciliation-statements", methods=["GET"])
def list_statements():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    limit, offset = validate.pagination()
    pp_filter = request.args.get("pay_period_id")
    emp_filter = request.args.get("employer_id")
    items = []
    for s in db.reconciliation_statements.values():
        if pp_filter is not None and s["pay_period_id"] != pp_filter:
            continue
        if emp_filter is not None and s["employer_id"] != emp_filter:
            continue
        items.append(s)
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.reconciliation_statement(s) for s in page], limit, offset, total)


@bp.route("/reconciliation-statements/<statement_id>/sign", methods=["POST"])
def sign_statement(statement_id):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    stmt = db.reconciliation_statements.get(statement_id)
    if stmt is None:
        raise errors.not_found()

    # State legality (priority 6): only a DRAFT statement can be signed.
    if stmt["status"] != "DRAFT":
        raise errors.invalid_state()

    period = db.pay_periods.get(stmt["pay_period_id"])

    # Segregation of duties (priority 8): signer must not be the period's batch
    # poster and must not be the approver of any advance in the period.
    for b in db.repayment_batches.values():
        if (b["pay_period_id"] == stmt["pay_period_id"]
                and b["status"] in ("POSTED", "RECONCILED")
                and b.get("posted_by_user_id") == user_id):
            raise errors.segregation_of_duties("Signer posted this period's batch")
    for a in domain.period_advances(stmt["pay_period_id"]):
        if a.get("approved_by_user_id") == user_id:
            raise errors.segregation_of_duties("Signer approved an advance in this period")

    # Period must be DISBURSED (PRD §3.11).
    if period is None or period["status"] != "DISBURSED":
        raise errors.ApiError(errors.ERR_PERIOD_NOT_DISBURSED, 409, "Period not disbursed")

    # Recompute then require CLEAN (drift == 0).
    domain.recompute_period_statement(stmt["pay_period_id"], create_if_absent=False)
    if stmt["drift_cents"] != 0:
        raise errors.ApiError(errors.ERR_STATEMENT_NOT_CLEAN, 409, "Statement is not CLEAN")

    stmt["status"] = "SIGNED"
    stmt["signed_by_user_id"] = user_id
    db.touch(stmt)

    # Recompute employer posture (a CLEAN signed statement can lift FROZEN).
    employer = db.employers.get(stmt["employer_id"])
    if employer is not None:
        domain.refresh_employer(employer)

    return object_response(serialize.reconciliation_statement(stmt))
