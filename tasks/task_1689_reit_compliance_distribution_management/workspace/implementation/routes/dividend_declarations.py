"""DividendDeclaration endpoints — OCC-guarded create, approve, declare, pay, void."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import (
    calc_dividend_characterization_waterfall,
    capital_gain_pool,
)
from services.common import (
    get_json_body, make_entity, parse_date, req_date, req_int, touch,
)
from services.ledger import refresh_ep_balance, sync_requirement_amounts

bp = Blueprint("dividend_declarations", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")


@bp.route("/reit-compliance/dividend-declarations", methods=["POST"])
def create_declaration():
    user_id, _ = require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    reit = db.reits.get(reit_id)
    if reit is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")

    taxable_year = req_int(body, "taxable_year")
    amount_cents = req_int(body, "amount_cents", min_value=0)
    if amount_cents <= 0:
        raise errors.validation("amount_cents must be > 0")
    declaration_date = req_date(body, "declaration_date")
    record_date = req_date(body, "record_date")
    payable_date = req_date(body, "payable_date")

    expected = body.get("expected_reit_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.validation("expected_reit_version is required and must be an integer")

    # Date sanity (priority 10)
    if parse_date(record_date) < parse_date(declaration_date):
        raise errors.invalid_date_range("record_date must not precede declaration_date")
    if parse_date(payable_date) < parse_date(record_date):
        raise errors.invalid_date_range("payable_date must not precede record_date")

    # REIT posture gate (priority 12)
    if reit["status"] != "ACTIVE":
        raise errors.reit_suspended("Drafting against a suspended REIT is not permitted")

    # OCC (priority 16)
    if expected != reit["version"]:
        raise errors.stale_version()

    decl = make_entity({
        "reit_id": reit_id,
        "taxable_year": taxable_year,
        "amount_cents": amount_cents,
        "declaration_date": declaration_date,
        "record_date": record_date,
        "payable_date": payable_date,
        "status": "PENDING_APPROVAL",
        "ordinary_cents": 0,
        "capital_gain_cents": 0,
        "return_of_capital_cents": 0,
        "declared_by_officer_id": None,
        "approved_by_director_id": None,
    })
    db.dividend_declarations[decl["id"]] = decl
    # Creating a declaration increments the REIT's version
    touch(reit)
    return success_object(dict(decl), status=201)


@bp.route("/reit-compliance/dividend-declarations/<did>", methods=["GET"])
def get_declaration(did):
    require_roles(*ALL)
    decl = db.dividend_declarations.get(did)
    if decl is None:
        raise errors.not_found("Dividend declaration not found")
    return success_object(dict(decl))


@bp.route("/reit-compliance/dividend-declarations", methods=["GET"])
def list_declarations():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.dividend_declarations.values())
    reit_id = request.args.get("reit_id")
    taxable_year = request.args.get("taxable_year")
    if reit_id is not None:
        rows = [d for d in rows if d["reit_id"] == reit_id]
    if taxable_year is not None:
        try:
            year = int(taxable_year)
            rows = [d for d in rows if d["taxable_year"] == year]
        except (TypeError, ValueError):
            rows = []
    page, total = paginate(rows, limit, offset)
    return success_list([dict(d) for d in page], limit, offset, total)


@bp.route("/reit-compliance/dividend-declarations/<did>/approve", methods=["POST"])
def approve_declaration(did):
    user_id, _ = require_roles("BoardDirector")
    decl = db.dividend_declarations.get(did)
    if decl is None:
        raise errors.not_found("Dividend declaration not found")
    if decl["status"] != "PENDING_APPROVAL":
        raise errors.invalid_state("Only PENDING_APPROVAL declarations can be approved")
    reit = db.reits.get(decl["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")
    # Posture gate (priority 12) then 5/50 block (priority 13)
    if reit["status"] != "ACTIVE":
        raise errors.reit_suspended("Suspended REIT may not approve dividends")
    if reit["five_fifty_blocked"]:
        raise errors.five_fifty_blocked()

    decl["status"] = "APPROVED"
    decl["approved_by_director_id"] = user_id
    touch(decl)
    return success_object(dict(decl))


@bp.route("/reit-compliance/dividend-declarations/<did>/declare", methods=["POST"])
def declare_declaration(did):
    user_id, _ = require_roles("ComplianceOfficer")
    decl = db.dividend_declarations.get(did)
    if decl is None:
        raise errors.not_found("Dividend declaration not found")
    if decl["status"] != "APPROVED":
        raise errors.invalid_state("Only APPROVED declarations can be declared")
    reit = db.reits.get(decl["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")
    # Posture gate (12), then 5/50 block (13), then segregation (14), then requirement (15)
    if reit["status"] != "ACTIVE":
        raise errors.reit_suspended("Suspended REIT may not declare dividends")
    if reit["five_fifty_blocked"]:
        raise errors.five_fifty_blocked()
    if decl["approved_by_director_id"] is not None and user_id == decl["approved_by_director_id"]:
        raise errors.segregation(
            "The officer who declares must not be the director who approved"
        )

    requirement = next(
        (r for r in db.distribution_requirements.values()
         if r["reit_id"] == decl["reit_id"]
         and r["taxable_year"] == decl["taxable_year"]
         and r["status"] == "POSTED"),
        None,
    )
    if requirement is None:
        raise errors.requirement_not_posted(
            "A POSTED DistributionRequirement for (reit_id, taxable_year) is required"
        )

    # Characterize (waterfall): ordinary from current E&P, then capital gain pool, then ROC
    cg_pool = capital_gain_pool(decl["reit_id"], decl["taxable_year"], requirement)
    result = calc_dividend_characterization_waterfall(
        decl["amount_cents"], reit["current_ep_balance_cents"], cg_pool
    )
    decl["ordinary_cents"] = result["ordinary_cents"]
    decl["capital_gain_cents"] = result["capital_gain_cents"]
    decl["return_of_capital_cents"] = result["return_of_capital_cents"]
    decl["declared_by_officer_id"] = user_id
    decl["status"] = "DECLARED"
    touch(decl)

    # Debit E&P immediately by ordinary_cents via the chronological replay
    refresh_ep_balance(reit)
    touch(reit)

    # Ledger sync on the requirement
    deficiency = sync_requirement_amounts(requirement)
    touch(requirement)
    reit["dividend_distribution_deficit_cents"] = deficiency

    return success_object(dict(decl))


@bp.route("/reit-compliance/dividend-declarations/<did>/pay", methods=["POST"])
def pay_declaration(did):
    require_roles("ComplianceOfficer")
    decl = db.dividend_declarations.get(did)
    if decl is None:
        raise errors.not_found("Dividend declaration not found")
    if decl["status"] != "DECLARED":
        raise errors.invalid_state("Only DECLARED declarations can be paid")
    decl["status"] = "PAID"
    touch(decl)
    return success_object(dict(decl))


@bp.route("/reit-compliance/dividend-declarations/<did>/void", methods=["POST"])
def void_declaration(did):
    require_roles("ComplianceOfficer")
    decl = db.dividend_declarations.get(did)
    if decl is None:
        raise errors.not_found("Dividend declaration not found")
    if decl["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise errors.invalid_state(
            "Only PENDING_APPROVAL or APPROVED declarations can be voided"
        )
    decl["status"] = "VOID"
    touch(decl)
    return success_object(dict(decl))
