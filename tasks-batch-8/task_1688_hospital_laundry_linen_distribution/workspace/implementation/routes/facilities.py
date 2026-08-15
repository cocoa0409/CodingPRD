"""Facility endpoints (PRD 3.1, 3.9)."""
from decimal import Decimal

from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_INVALID_REQUEST, raise_err
from serializers import facility_out
from util import body_json, get_or_404, list_response, new_record, req_str, \
    req_int, req_number, opt_int, rhu2, success_object

bp = Blueprint("facilities", __name__)


@bp.route("/facilities", methods=["POST"])
def create_facility():
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    body = body_json()

    name = req_str(body, "name")
    rate = req_int(body, "rate_per_lb_cents")
    if rate < 0:
        raise_err(ERR_INVALID_REQUEST, "rate_per_lb_cents must be >= 0")
    surcharge = req_number(body, "isolation_surcharge_pct")
    if surcharge < 0:
        raise_err(ERR_INVALID_REQUEST, "isolation_surcharge_pct must be >= 0")
    cap = opt_int(body, "monthly_cap_cents", None)
    if cap is not None and cap < 0:
        raise_err(ERR_INVALID_REQUEST, "monthly_cap_cents must be >= 0")

    rec = new_record()
    rec.update({
        "name": name,
        "rate_per_lb_cents": rate,
        "isolation_surcharge_pct": surcharge,
        "monthly_cap_cents": cap,
        "surge_posture": "NORMAL",
        "credit_balance_cents": 0,
    })
    store.facilities[rec["id"]] = rec
    return success_object(facility_out(rec), 201)


@bp.route("/facilities/<facility_id>", methods=["GET"])
def get_facility(facility_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.facilities, facility_id, "Facility")
    return success_object(facility_out(rec))


@bp.route("/facilities/<facility_id>/metrics", methods=["GET"])
def facility_metrics(facility_id):
    """cost_per_adjusted_patient_day, posted vs accrual bases (PRD 3.9)."""
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    fac = get_or_404(store.facilities, facility_id, "Facility")

    invs = [i for i in store.invoices.values() if i["facility_id"] == fac["id"]]
    settled = [i for i in invs if i["status"] == "SETTLED"]

    if settled:
        num = sum(i["billed_total_cents"] for i in settled)
        den = sum(i["period_adjusted_patient_days"] for i in settled)
        posted = rhu2(Decimal(num) / Decimal(den))
    else:
        posted = 0

    if invs:
        num = sum(i["billed_total_cents"] for i in invs
                  if i["status"] in ("FINALIZED", "DISPUTED", "SETTLED"))
        num += sum(i["provisional_total_cents"] for i in invs
                   if i["status"] == "PROVISIONAL")
        den = sum(i["period_adjusted_patient_days"] for i in invs)
        accrual = rhu2(Decimal(num) / Decimal(den))
    else:
        accrual = 0

    return success_object({
        "cost_per_apd_posted_cents": posted,
        "cost_per_apd_accrual_cents": accrual,
        "posted_invoice_count": len(settled),
        "accrual_invoice_count": len(invs),
    })
