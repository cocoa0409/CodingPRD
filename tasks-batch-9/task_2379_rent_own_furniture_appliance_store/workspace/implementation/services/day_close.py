"""The arrears checkpoint (PRD 3.6). Nothing else assesses fees or defaults."""

import clock
from db import base_row, db, sort_rows, touch
from services import calc, domain


def _open_window(agreement, rule, now):
    window = base_row()
    window["agreement_id"] = agreement["id"]
    window["missed_period_index"] = agreement["periods_paid"] + 1
    window["opened_at"] = clock.fmt(now)
    window["window_days"] = calc.reinstatement_window_days(rule, agreement)
    window["expires_at"] = clock.fmt(clock.plus_days(now, window["window_days"]))
    window["reinstatement_fee_cents"] = rule["reinstatement_fee_cents"]
    window["status"] = "OPEN"
    db.windows[window["id"]] = window
    return window


def run(store):
    now = clock.now()
    result = {
        "store_id": store["id"],
        "closed_at": clock.fmt(now),
        "agreements_scanned": 0,
        "late_fees_assessed": 0,
        "late_fee_total_cents": 0,
        "windows_opened": 0,
        "windows_expired": 0,
        "agreements_defaulted": 0,
        "agreements_marked_adverse": 0,
    }

    store_agreements = [
        ag for ag in db.agreements.values() if ag["store_id"] == store["id"]
    ]

    scannable = [
        ag
        for ag in store_agreements
        if ag["payment_status"] in ("CURRENT", "DELINQUENT")
        and ag["possession_status"] in ("DELIVERED", "SERVICE_SWAP_PENDING")
        and ag["cycle_anchor_at"] is not None
    ]

    for agreement in sort_rows(scannable):
        result["agreements_scanned"] += 1
        rule = domain.pinned_rule(agreement)
        customer = db.customers.get(agreement["customer_id"])
        due_at = clock.parse(agreement["current_period_due_at"])
        if due_at is None:
            continue
        dirty = False

        days_late = clock.whole_days_between(now, due_at)
        if days_late > rule["late_fee_grace_days"]:
            # (1) assess an unpaid overdue period's late fee
            if agreement["late_fee_period_index_last"] < agreement["periods_paid"] + 1:
                fee = calc.late_fee_cents(rule, agreement["renewal_rate_cents"])
                agreement["late_fee_assessed_cents"] += fee
                agreement["late_fee_period_index_last"] = agreement["periods_paid"] + 1
                result["late_fees_assessed"] += 1
                result["late_fee_total_cents"] += fee
                dirty = True
            # (2) open a reinstatement window and flip CURRENT -> DELINQUENT
            if agreement["payment_status"] == "CURRENT":
                _open_window(agreement, rule, now)
                agreement["reinstatement_fee_assessed_cents"] += rule[
                    "reinstatement_fee_cents"
                ]
                agreement["payment_status"] = "DELINQUENT"
                result["windows_opened"] += 1
                if agreement["collections_stage"] == "NONE":
                    agreement["collections_stage"] = "ADVERSE"
                    result["agreements_marked_adverse"] += 1
                if customer is not None:
                    customer["lifetime_delinquency_count"] += 1
                    touch(customer)
                dirty = True

        # (3) expire an OPEN window whose expires_at is strictly before the clock
        window = domain.open_window(agreement["id"])
        if window is not None:
            expires_at = clock.parse(window["expires_at"])
            if expires_at is not None and now > expires_at:
                window["status"] = "EXPIRED"
                touch(window)
                result["windows_expired"] += 1
                # (4) on that expiry, DELINQUENT -> DEFAULTED
                if agreement["payment_status"] == "DELINQUENT":
                    agreement["payment_status"] = "DEFAULTED"
                    if agreement["collections_stage"] != "ADVERSE":
                        agreement["collections_stage"] = "ADVERSE"
                        result["agreements_marked_adverse"] += 1
                    result["agreements_defaulted"] += 1
                    dirty = True

        if dirty:
            domain.sync_agreement_money(agreement)
            touch(agreement)
        if customer is not None:
            domain.sync_customer(customer)

    # the sweep also expires every OPEN quote the clock has passed
    for agreement in sort_rows(store_agreements):
        for quote in sort_rows(domain.agreement_quotes(agreement["id"]), "issued_at"):
            if quote["status"] != "OPEN":
                continue
            expires_at = clock.parse(quote["expires_at"])
            if expires_at is not None and now > expires_at:
                quote["status"] = "EXPIRED"
                touch(quote)

    return result
