from flask import Blueprint

import store
from store import touch, ser, now, parcels_of_district, rolls_of_district, bonds_of_district, installments_of_parcel
from web import protected, ok, ApiError
from fetch import get_roll, get_district
import calc
import logic

bp = Blueprint("rolls", __name__)


@bp.post("/rolls/<rid>/confirm")
@protected(["DistrictAdministrator"])
def confirm_roll(rid):
    roll = get_roll(rid)
    if roll["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ROLL_STATE")
    district = get_district(roll["district_id"])
    if district["status"] != "FORMED":
        raise ApiError("ERR_DISTRICT_NOT_FORMED")

    active = [p for p in parcels_of_district(district["id"]) if p["status"] == "ACTIVE"]
    assessable = roll["total_apportioned_cents"]
    entries = [{"id": p["id"], "weight": calc.weight_of(p, roll["method"]), "seq": p["_seq"]}
               for p in active]
    shares = calc.waterfall(assessable, entries)

    for p in active:
        assessed = shares.get(p["id"], 0)
        paid_principal = sum(i["principal_cents"] for i in installments_of_parcel(p["id"])
                             if i["status"] == "PAID")
        p["assessed_principal_cents"] = assessed
        remaining = assessed - paid_principal
        if remaining < 0:
            remaining = 0
        p["remaining_principal_cents"] = remaining
        touch(p)

    district["total_apportioned_principal_cents"] = assessable
    touch(district)

    # supersede any previously CONFIRMED roll of this district
    for other in rolls_of_district(district["id"]):
        if other["id"] != roll["id"] and other["status"] == "CONFIRMED":
            other["status"] = "SUPERSEDED"
            touch(other)

    roll["status"] = "CONFIRMED"
    roll["confirmed_at"] = now()
    touch(roll)

    # record ASSESSMENT liens
    for p in active:
        if logic.unreleased_assessment_lien(p["id"]) is None:
            logic.record_lien(p, "ASSESSMENT", p["remaining_principal_cents"])

    # reassessment: re-amortize SCHEDULED installments if a bond is ISSUED
    for bond in bonds_of_district(district["id"]):
        if bond["status"] != "ISSUED":
            continue
        for p in active:
            sched = calc.amortize(p["remaining_principal_cents"], bond["coupon_rate_bps"],
                                  bond["term_years"], bond["admin_fee_bps"], bond["issuance_date"])
            by_year = {row["installment_year"]: row for row in sched}
            for inst in installments_of_parcel(p["id"]):
                if inst["bond_id"] != bond["id"] or inst["status"] != "SCHEDULED":
                    continue
                row = by_year.get(inst["installment_year"])
                if row is None:
                    continue
                inst["principal_cents"] = row["principal_cents"]
                inst["interest_cents"] = row["interest_cents"]
                inst["admin_fee_cents"] = row["admin_fee_cents"]
                inst["amount_due_cents"] = row["amount_due_cents"]
                touch(inst)

    return ok(ser(roll))
