"""DistributionRequirement endpoints."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import calc_distribution_requirement
from services.common import get_json_body, make_entity, req_int, touch
from services.ledger import sync_requirement_amounts

bp = Blueprint("distribution_requirements", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")


@bp.route("/reit-compliance/distribution-requirements", methods=["POST"])
def create_requirement():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    if db.reits.get(reit_id) is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")

    taxable_year = req_int(body, "taxable_year")
    taxable_income_cents = req_int(body, "taxable_income_cents")
    net_capital_gain_cents = req_int(body, "net_capital_gain_cents", min_value=0)

    # One requirement per (reit, taxable_year)
    for r in db.distribution_requirements.values():
        if r["reit_id"] == reit_id and r["taxable_year"] == taxable_year:
            raise errors.duplicate("One distribution requirement per taxable year per REIT")

    req = make_entity({
        "reit_id": reit_id,
        "taxable_year": taxable_year,
        "status": "DRAFT",
        "taxable_income_cents": taxable_income_cents,
        "net_capital_gain_cents": net_capital_gain_cents,
        "required_amount_cents": 0,
        "distributed_amount_cents": 0,
        "deficiency_cents": 0,
    })
    db.distribution_requirements[req["id"]] = req
    return success_object(dict(req), status=201)


@bp.route("/reit-compliance/distribution-requirements/<rid>", methods=["GET"])
def get_requirement(rid):
    require_roles(*ALL)
    req = db.distribution_requirements.get(rid)
    if req is None:
        raise errors.not_found("Distribution requirement not found")
    return success_object(dict(req))


@bp.route("/reit-compliance/distribution-requirements", methods=["GET"])
def list_requirements():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.distribution_requirements.values())
    reit_id = request.args.get("reit_id")
    if reit_id is not None:
        rows = [r for r in rows if r["reit_id"] == reit_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(r) for r in page], limit, offset, total)


@bp.route("/reit-compliance/distribution-requirements/<rid>/post", methods=["POST"])
def post_requirement(rid):
    require_roles("ComplianceOfficer")
    req = db.distribution_requirements.get(rid)
    if req is None:
        raise errors.not_found("Distribution requirement not found")
    if req["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT requirements can be posted")

    req["required_amount_cents"] = calc_distribution_requirement(
        req["taxable_income_cents"], req["net_capital_gain_cents"]
    )
    req["status"] = "POSTED"
    sync_requirement_amounts(req)
    touch(req)

    reit = db.reits.get(req["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")
    reit["dividend_distribution_deficit_cents"] = req["required_amount_cents"]
    touch(reit)

    return success_object(dict(req))


@bp.route("/reit-compliance/distribution-requirements/<rid>/close", methods=["POST"])
def close_requirement(rid):
    require_roles("TaxDirector")
    req = db.distribution_requirements.get(rid)
    if req is None:
        raise errors.not_found("Distribution requirement not found")
    # State check (priority 7) precedes open-declarations check (priority 17)
    if req["status"] != "POSTED":
        raise errors.invalid_state("Only POSTED requirements can be closed")

    open_decls = [
        d for d in db.dividend_declarations.values()
        if d["reit_id"] == req["reit_id"]
        and d["taxable_year"] == req["taxable_year"]
        and d["status"] not in ("PAID", "VOID")
    ]
    if open_decls:
        raise errors.declarations_open(
            "All sibling dividend declarations must be in a terminal state (PAID or VOID)"
        )

    # Freeze deficiency
    req["deficiency_cents"] = max(
        0, req["required_amount_cents"] - req["distributed_amount_cents"]
    )
    req["status"] = "CLOSED"
    touch(req)

    reit = db.reits.get(req["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")
    reit["dividend_distribution_deficit_cents"] = (
        req["deficiency_cents"] if req["deficiency_cents"] > 0 else 0
    )
    touch(reit)

    return success_object(dict(req))
