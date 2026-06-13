"""Mortgage routes: convert (EscrowAgent), fetch, list."""

from flask import Blueprint, request

import db
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from routes.helpers import lookup, paginate
from services import domain
from services import calc
import validation as V

bp = Blueprint("mortgages", __name__)


# ---------------------------------------------------------------------------
# Convert (EscrowAgent): Agreement EXERCISED -> CONVERTED, Property -> SOLD
# ---------------------------------------------------------------------------
@bp.post("/agreements/<aid>/mortgage")
def convert_to_mortgage(aid):
    _, role = get_auth()
    require_role(role, {"EscrowAgent"})  # opaque identity; no ownership check
    agreement = lookup(db.agreements, aid)

    body = V.get_body()
    option_exercise_id = V.require_str(body, "option_exercise_id")
    annual_rate_bps = V.require_int(body, "annual_rate_bps", minimum=0)
    term_months = V.require_int(body, "term_months", minimum=1)

    # Existence (priority 3): referenced exercise must exist.
    exercise = lookup(db.option_exercises, option_exercise_id)

    # State (priority 7, per PRD §3.7 prose order): agreement must be EXERCISED.
    if agreement["status"] != "EXERCISED":
        raise err("ERR_AGREEMENT_NOT_EXERCISED", "Agreement is not EXERCISED")

    # Referential consistency (PRD §3.7): a SETTLED exercise must exist for this
    # agreement and the supplied id must belong to the path agreement.
    if exercise["agreement_id"] != aid or exercise["status"] != "SETTLED":
        raise err("ERR_REFERENCE_MISMATCH",
                  "Option exercise does not belong to this agreement or is not SETTLED")

    # Credit-score gate (PRD §3.7): tenant.credit_score >= MIN_CONVERSION_SCORE.
    tenant = db.tenants.get(agreement["tenant_id"])
    if tenant is None or tenant["credit_score"] < calc.MIN_CONVERSION_SCORE:
        raise err("ERR_CREDIT_SCORE_TOO_LOW", "Tenant credit score below minimum")

    principal = exercise["net_due_at_closing_cents"]
    installment = calc.amortized_installment(principal, annual_rate_bps, term_months)

    rec = {
        "id": db.new_id(),
        "agreement_id": aid,
        "option_exercise_id": option_exercise_id,
        "principal_cents": principal,
        "annual_rate_bps": annual_rate_bps,
        "term_months": term_months,
        "monthly_installment_cents": installment,
        "status": "ACTIVE",
    }
    domain._stamp_new(rec)
    db.mortgages[rec["id"]] = rec

    # Agreement EXERCISED -> CONVERTED.
    agreement["status"] = "CONVERTED"
    domain.touch(agreement)

    # Cascade property UNDER_AGREEMENT -> SOLD.
    prop = db.properties.get(agreement["property_id"])
    if prop is not None and prop["status"] == "UNDER_AGREEMENT":
        prop["status"] = "SOLD"
        domain.touch(prop)

    return object_response(domain.serialize_mortgage(rec), 201)


# ---------------------------------------------------------------------------
# Fetch / list
# ---------------------------------------------------------------------------
@bp.get("/mortgages/<rid>")
def get_mortgage(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.mortgages, rid)
    return object_response(domain.serialize_mortgage(rec), 200)


@bp.get("/mortgages")
def list_mortgages():
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    items = list(db.mortgages.values())
    for field in ("agreement_id", "option_exercise_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [m for m in items if m.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([domain.serialize_mortgage(m) for m in page],
                          limit, offset, total)
