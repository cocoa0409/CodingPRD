"""EmployerAccount endpoints plus employer-scoped reverse-reachability lists
and the computed rating summary."""
import re

from flask import Blueprint

from db import STORE
from errors import err, ERR_DUPLICATE_ACTIVE_RECORD, ERR_INVALID_REQUEST
from middleware import require_roles
from response import paginate, success
from services.core import find_or_404, new_record, serialize, sorted_created
from util import as_int, as_str, body_json, check_enum, opt, req

bp = Blueprint("employers", __name__)

MERIT_METHODS = ("RESERVE_RATIO", "BENEFIT_RATIO")


@bp.post("/ui/employers")
def create_employer():
    require_roles("PlatformAdmin")
    body = body_json()
    legal_name = as_str(req(body, "legal_name"), "legal_name")
    fein = as_str(req(body, "fein"), "fein")
    if not re.fullmatch(r"\d{9}", fein):
        raise err(ERR_INVALID_REQUEST, 400, "fein must be a 9-digit string")
    merit_rating_method = check_enum(
        as_str(req(body, "merit_rating_method"), "merit_rating_method"),
        MERIT_METHODS, "merit_rating_method",
    )
    taxable_payroll_cents = as_int(req(body, "taxable_payroll_cents"), "taxable_payroll_cents")
    reserve_balance_cents = opt(body, "reserve_balance_cents", 0)
    reserve_balance_cents = as_int(reserve_balance_cents, "reserve_balance_cents")
    for e in STORE.employers.values():
        if e["fein"] == fein:
            raise err(ERR_DUPLICATE_ACTIVE_RECORD, 409, "fein is globally unique across accounts")
    rec = new_record({
        "legal_name": legal_name,
        "fein": fein,
        "merit_rating_method": merit_rating_method,
        "reserve_balance_cents": reserve_balance_cents,
        "taxable_payroll_cents": taxable_payroll_cents,
        "current_tax_rate_bps": 270,
        "protest_credits_cents": 0,
        "compliance_posture": "CLEAR",
        "late_response_strikes": 0,
    })
    STORE.employers[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/ui/employers")
def list_employers():
    require_roles("PlatformAdmin", "ClaimsAnalyst", "ChargeAuditor", "RatingAnalyst", "TpaManager")
    items = [serialize(r) for r in sorted_created(STORE.employers.values())]
    return paginate(items)


@bp.get("/ui/employers/<rid>")
def get_employer(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "ChargeAuditor", "RatingAnalyst", "TpaManager")
    rec = find_or_404(STORE.employers, rid, "employer")
    return success(serialize(rec))


@bp.get("/ui/employers/<rid>/claims")
def employer_claims(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "ChargeAuditor", "AgencyLiaison")
    find_or_404(STORE.employers, rid, "employer")
    items = [serialize(c) for c in sorted_created(STORE.claims.values()) if c["employer_id"] == rid]
    return paginate(items)


@bp.get("/ui/employers/<rid>/separations")
def employer_separations(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    find_or_404(STORE.employers, rid, "employer")
    items = [serialize(s) for s in sorted_created(STORE.separations.values()) if s["employer_id"] == rid]
    return paginate(items)


@bp.get("/ui/employers/<rid>/charge-statements")
def employer_charge_statements(rid):
    require_roles("PlatformAdmin", "ChargeAuditor")
    find_or_404(STORE.employers, rid, "employer")
    items = [serialize(s) for s in sorted_created(STORE.charge_statements.values()) if s["employer_id"] == rid]
    return paginate(items)


@bp.get("/ui/employers/<rid>/experience-rating-models")
def employer_models(rid):
    require_roles("PlatformAdmin", "RatingAnalyst")
    find_or_404(STORE.employers, rid, "employer")
    items = [serialize(m) for m in sorted_created(STORE.rating_models.values()) if m["employer_id"] == rid]
    return paginate(items)


@bp.get("/ui/employers/<rid>/tpa-engagements")
def employer_tpas(rid):
    require_roles("PlatformAdmin", "TpaManager", "ClaimsAnalyst")
    find_or_404(STORE.employers, rid, "employer")
    items = [serialize(t) for t in sorted_created(STORE.tpa_engagements.values()) if t["employer_id"] == rid]
    return paginate(items)


@bp.get("/ui/employers/<rid>/rating-summary")
def employer_rating_summary(rid):
    require_roles("PlatformAdmin", "RatingAnalyst", "ChargeAuditor")
    emp = find_or_404(STORE.employers, rid, "employer")
    return success({
        "current_tax_rate_bps": emp["current_tax_rate_bps"],
        "compliance_posture": emp["compliance_posture"],
        "late_response_strikes": emp["late_response_strikes"],
        "protest_credits_cents": emp["protest_credits_cents"],
    })
