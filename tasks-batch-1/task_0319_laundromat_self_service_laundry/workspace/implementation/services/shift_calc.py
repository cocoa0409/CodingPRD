"""Shift drawer aggregate recomputation (SCAFFOLD calc 5 / PRD §3.6).

coin_collected_cents = sum charged_amount_cents over the shift's COIN vends
                       that remain CAPTURED.
cash_reload_cents     = sum principal_cents over the shift's CASH reloads POSTED.
cash_refund_paid_cents = sum approved_cents over APPROVED CASH-destination
                         refunds whose underlying vend belongs to this shift.
expected_drawer_cents = opening_float + coin_collected + cash_reload
                        - cash_refund_paid.
"""
from db import db, touch


def recompute_shift(shift):
    sid = shift["id"]

    coin = 0
    for v in db.vends.values():
        if (
            v.get("shift_id") == sid
            and v["payment_method"] == "COIN"
            and v["payment_status"] == "CAPTURED"
        ):
            coin += v["charged_amount_cents"]

    cash_reload = 0
    for r in db.reloads.values():
        if (
            r.get("shift_id") == sid
            and r["tender"] == "CASH"
            and r["status"] == "POSTED"
        ):
            cash_reload += r["principal_cents"]

    cash_refund = 0
    for c in db.refund_claims.values():
        if c["status"] != "APPROVED" or c["refund_destination"] != "CASH":
            continue
        vend = db.vends.get(c["vend_id"])
        if vend is not None and vend.get("shift_id") == sid:
            cash_refund += c["approved_cents"]

    shift["coin_collected_cents"] = coin
    shift["cash_reload_cents"] = cash_reload
    shift["cash_refund_paid_cents"] = cash_refund
    shift["expected_drawer_cents"] = (
        shift["opening_float_cents"] + coin + cash_reload - cash_refund
    )


def recompute_and_touch(shift):
    recompute_shift(shift)
    touch(shift)
