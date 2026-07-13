from flask import Blueprint

import store
from store import DB, touch, ser, now, liens_of_parcel
from web import protected, ok, ApiError
from fetch import get_payment, get_installment, get_parcel
import calc
import logic
from util import add_days

bp = Blueprint("payments", __name__)


@bp.post("/payments/<pid>/reverse")
@protected(["CountyTreasurer"])
def reverse_payment(pid):
    payment = get_payment(pid)
    inst = DB["installments"].get(payment["installment_id"])
    parcel = get_parcel(inst["parcel_id"]) if inst else None

    payment["reversed"] = True
    payment["reversed_at"] = now()

    if inst is not None:
        # installment returns from PAID to DUE (or DELINQUENT if past grace)
        if now() >= add_days(inst["due_date"], calc.GRACE_DAYS):
            inst["status"] = "DELINQUENT"
        else:
            inst["status"] = "DUE"
        touch(inst)

        if parcel is not None:
            was_paid_off = parcel["status"] == "PAID_OFF"
            parcel["remaining_principal_cents"] += inst["principal_cents"]
            if was_paid_off:
                parcel["status"] = "ACTIVE"
                # re-record the ASSESSMENT lien
                reactivated = None
                for lien in liens_of_parcel(parcel["id"]):
                    if lien["lien_type"] == "ASSESSMENT" and lien["status"] == "RELEASED":
                        reactivated = lien
                if reactivated is not None:
                    reactivated["status"] = "RECORDED"
                    reactivated["amount_cents"] = parcel["remaining_principal_cents"]
                    touch(reactivated)
                else:
                    logic.record_lien(parcel, "ASSESSMENT", parcel["remaining_principal_cents"])
            touch(parcel)

    return ok(ser(payment))
