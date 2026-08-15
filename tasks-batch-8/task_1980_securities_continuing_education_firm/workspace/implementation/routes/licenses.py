"""State CE licenses: create / list / get / renew."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, base_record, touch
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_WINDOW_INVALID,
                    ERR_DUPLICATE_LICENSE_STATE, ERR_REP_NOT_INSURANCE_LICENSED)
from middleware import require_roles, json_body, require_fields
from response import success, paginate
from services import (get_or_404, by_seq, recompute_license,
                      CARRYOVER_CAP_HOURS)
from util import to_decimal, require_str, parse_dt, view

bp = Blueprint("licenses", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


@bp.post("/state-ce-licenses")
@require_roles("TrainingAdmin")
def create_license():
    body = json_body()
    rep = None
    if body.get("rep_id") is not None:
        rep = get_or_404(store.representatives, body["rep_id"], "Representative")
    require_fields(body, "rep_id", "state_code", "required_hours",
                   "period_start", "period_end")
    state_code = require_str(body["state_code"], "state_code")
    required_hours = to_decimal(body["required_hours"], "required_hours")
    if required_hours <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'required_hours' must be greater than 0")
    period_start = parse_dt(body["period_start"], "period_start")
    period_end = parse_dt(body["period_end"], "period_end")
    if not period_end > period_start:
        raise ApiError(ERR_WINDOW_INVALID, 400,
                       "period_end must be strictly later than period_start")
    # Uniqueness: one license per (rep, state).
    for lic in store.licenses.values():
        if lic["rep_id"] == rep["id"] and lic["state_code"] == state_code:
            raise ApiError(ERR_DUPLICATE_LICENSE_STATE, 409,
                           "Representative already holds a license for state "
                           "'%s'" % state_code)
    # Referential: state CE licenses require an insurance-licensed rep.
    if not rep["insurance_licensed"]:
        raise ApiError(ERR_REP_NOT_INSURANCE_LICENSED, 409,
                       "Representative is not insurance-licensed")
    rec = base_record()
    rec.update({
        "rep_id": rep["id"],
        "state_code": state_code,
        "required_hours": required_hours,
        "period_start": period_start,
        "period_end": period_end,
        "license_status": "ACTIVE",
        "earned_hours_strict": Decimal("0"),
        "earned_hours_effective": Decimal("0"),
        "reported_hours": Decimal("0"),
        "carried_excess_hours": Decimal("0"),
    })
    store.licenses[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/state-ce-licenses")
@require_roles(*ANY)
def list_licenses():
    items = by_seq(store.licenses.values())
    for param in ("rep_id", "state_code", "license_status"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l[param] == value]
    items = sorted(items, key=lambda l: (l["created_at"], l["_seq"]))
    page, pagination = paginate(items)
    return success([view(l) for l in page], is_list=True, pagination=pagination)


@bp.get("/state-ce-licenses/<licenseId>")
@require_roles(*ANY)
def get_license(licenseId):
    rec = get_or_404(store.licenses, licenseId, "StateCELicense")
    return success(view(rec))


@bp.post("/state-ce-licenses/<licenseId>/renew")
@require_roles("TrainingAdmin")
def renew_license(licenseId):
    rec = get_or_404(store.licenses, licenseId, "StateCELicense")
    body = json_body()
    require_fields(body, "new_period_start", "new_period_end")
    new_start = parse_dt(body["new_period_start"], "new_period_start")
    new_end = parse_dt(body["new_period_end"], "new_period_end")
    if not new_end > new_start:
        raise ApiError(ERR_WINDOW_INVALID, 400,
                       "new_period_end must be strictly later than "
                       "new_period_start")
    # Carryover is computed from the CLOSING window before it is replaced.
    recompute_license(rec)
    excess = rec["earned_hours_strict"] - rec["required_hours"]
    if excess < 0:
        excess = Decimal("0")
    if excess > CARRYOVER_CAP_HOURS:
        excess = CARRYOVER_CAP_HOURS
    rec["carried_excess_hours"] = excess
    rec["period_start"] = new_start
    rec["period_end"] = new_end
    rec["license_status"] = "ACTIVE"
    touch(rec)
    recompute_license(rec)
    return success(view(rec))
