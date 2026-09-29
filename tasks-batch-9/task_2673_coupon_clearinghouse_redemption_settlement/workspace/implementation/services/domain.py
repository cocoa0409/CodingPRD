"""Shared lookups, derived-field recomputation and cascades (PRD 2.8, 2.9)."""

from decimal import Decimal

import db
from db import touch, sort_rows
from services import calc


# ------------------------------------------------------------------ lookups
def lots_of_submission(submission_id):
    return sort_rows(
        [l for l in db.db.lots.values() if l["submission_id"] == submission_id]
    )


def lots_of_offer(offer_id):
    return sort_rows([l for l in db.db.lots.values() if l["offer_id"] == offer_id])


def items_of_lot(lot_id):
    return sort_rows([i for i in db.db.items.values() if i["lot_id"] == lot_id])


def items_of_submission(submission_id):
    out = []
    for lot in lots_of_submission(submission_id):
        out.extend(items_of_lot(lot["id"]))
    return out


def statements_of_submission(submission_id):
    return sort_rows(
        [s for s in db.db.statements.values() if s["submission_id"] == submission_id]
    )


def statements_of_invoice(invoice_id):
    return sort_rows(
        [
            s
            for s in db.db.statements.values()
            if s["manufacturer_invoice_id"] == invoice_id
        ]
    )


def disputes_of_lot(lot_id):
    return sort_rows([d for d in db.db.disputes.values() if d["lot_id"] == lot_id])


def offer_of_lot(lot):
    return db.db.offers[lot["offer_id"]]


def submission_of_lot(lot):
    return db.db.submissions[lot["submission_id"]]


def retailer_of_submission(submission):
    return db.db.retailers[submission["retailer_id"]]


def lot_of_item(item):
    return db.db.lots[item["lot_id"]]


# ------------------------------------------------- submission derived fields
def recompute_declared_face_value(submission):
    total = 0
    for lot in lots_of_submission(submission["id"]):
        total += lot["counted_qty"] * offer_of_lot(lot)["face_value_cents"]
    submission["declared_face_value_cents"] = total


def recompute_sorted_lot_count(submission):
    submission["sorted_lot_count"] = len(lots_of_submission(submission["id"]))


def recompute_rejected_lot_count(submission):
    submission["rejected_lot_count"] = len(
        [
            l
            for l in lots_of_submission(submission["id"])
            if l["status"] == "LOT_REJECTED"
        ]
    )


def recompute_item_face_values(submission):
    adjudicated = 0
    accepted = 0
    rejected = 0
    for lot in lots_of_submission(submission["id"]):
        face = offer_of_lot(lot)["face_value_cents"]
        for item in items_of_lot(lot["id"]):
            value = face * item["claimed_units"]
            if item["status"] == "CAPTURED":
                continue
            adjudicated += value
            if item["status"] in calc.CLEARED_STATUSES:
                accepted += value
            elif item["status"] in calc.REJECTED_STATUSES:
                rejected += value
    submission["adjudicated_face_value_cents"] = adjudicated
    submission["accepted_item_face_value_cents"] = accepted
    submission["rejected_item_face_value_cents"] = rejected


def recompute_settled_money(submission):
    gross = 0
    fee = 0
    for lot in lots_of_submission(submission["id"]):
        if lot["status"] in calc.SETTLEABLE_LOT_STATUSES:
            gross += lot["gross_face_value_cents"]
            fee += lot["handling_fee_cents"]
    submission["settled_gross_face_value_cents"] = gross
    submission["settled_handling_fee_cents"] = fee


def recompute_valuation_method(submission):
    for lot in lots_of_submission(submission["id"]):
        if lot["valuation_variant"] == "SAMPLED_EXTRAPOLATION":
            submission["valuation_method"] = "SAMPLED_EXTRAPOLATION"
            return
    submission["valuation_method"] = "FULL_COUNT"


# --------------------------------------------------------- ledger identities
def recompute_retailer_unpaid(retailer):
    total = 0
    for st in db.db.statements.values():
        if st["retailer_id"] == retailer["id"] and st["status"] == "SCHEDULED":
            total += st["net_payable_cents"]
    retailer["unpaid_balance_cents"] = total
    touch(retailer)


def recompute_manufacturer_ledger(manufacturer):
    funded = 0
    disbursed = 0
    invoice_ids = set()
    for inv in db.db.invoices.values():
        if inv["manufacturer_id"] != manufacturer["id"]:
            continue
        invoice_ids.add(inv["id"])
        if inv["status"] in ("FUNDED", "SHORT_FUNDED", "RECONCILED"):
            funded += inv["funded_amount_cents"]
    for st in db.db.statements.values():
        if st["manufacturer_invoice_id"] in invoice_ids and st["status"] == "PAID":
            disbursed += st["net_payable_cents"]
    manufacturer["funded_total_cents"] = funded
    manufacturer["disbursed_total_cents"] = disbursed
    manufacturer["funding_balance_cents"] = funded - disbursed
    touch(manufacturer)


# ------------------------------------------------------------ lot arithmetic
def recompute_lot_quantities(lot):
    accepted = 0
    rejected = 0
    for item in items_of_lot(lot["id"]):
        if item["status"] in calc.CLEARED_STATUSES:
            accepted += item["claimed_units"]
        elif item["status"] in calc.REJECTED_STATUSES:
            rejected += item["claimed_units"]
    lot["accepted_qty"] = accepted
    lot["rejected_qty"] = rejected


def value_lot(lot):
    """Runs the lot valuation + handling fee; returns projected units."""
    offer = offer_of_lot(lot)
    submission = submission_of_lot(lot)
    retailer = retailer_of_submission(submission)
    manufacturer = db.db.manufacturers[offer["manufacturer_id"]]
    projected, gross = calc.lot_valuation(
        lot["valuation_variant"],
        lot["accepted_qty"],
        lot["counted_qty"],
        lot["sample_size"],
        offer["face_value_cents"],
    )
    lot["projected_accepted_units"] = projected
    lot["gross_face_value_cents"] = gross
    lot["handling_fee_cents"] = calc.handling_fee_cents(
        projected, offer, manufacturer, retailer
    )
    return projected


# ------------------------------------------------------ adjudication (3.4)
def adjudicate_item(item, lot, offer, submission):
    """Runs the four ordered checks; writes status, reject_code and links."""
    item["reject_code"] = None
    item["duplicate_of_item_id"] = None
    item["matched_purchase_record_id"] = None

    if item["scanned_barcode"] != offer["barcode_payload"]:
        item["status"] = "REJECTED_COUNTERFEIT"
        item["reject_code"] = "BARCODE_MISMATCH"
    elif db.parse_date(item["redeemed_at"]) > db.parse_date(offer["expiration_date"]):
        item["status"] = "REJECTED_EXPIRED"
        item["reject_code"] = "EXPIRED_AT_POS"
    else:
        winner = _duplicate_winner(item)
        if winner is not None:
            item["status"] = "REJECTED_DUPLICATE"
            item["reject_code"] = "DUPLICATE_SERIAL"
            item["duplicate_of_item_id"] = winner["id"]
        else:
            _misredemption_check(item, lot, offer, submission)
    item["adjudicated_at"] = db.now_iso()
    touch(item)
    return item


def _duplicate_winner(item):
    if item.get("serial_number") is None:
        return None
    pool = [
        other
        for other in db.db.items.values()
        if other["id"] != item["id"]
        and other["scanned_barcode"] == item["scanned_barcode"]
        and other.get("serial_number") == item["serial_number"]
        and other["status"] in calc.CLEARED_STATUSES
    ]
    if not pool:
        return None
    pool.sort(
        key=lambda o: (
            o.get("adjudicated_at") or "",
            o.get("created_at") or "",
            o.get("_seq") or 0,
        )
    )
    return pool[0]


def _misredemption_check(item, lot, offer, submission):
    required_units = item["claimed_units"] * offer["purchase_requirement_units"]
    ref = item.get("pos_transaction_ref")
    pool = []
    if ref is not None:
        pool = [
            r
            for r in db.db.purchase_records.values()
            if r["retailer_id"] == submission["retailer_id"]
            and r["offer_id"] == lot["offer_id"]
            and r["pos_transaction_ref"] == ref
        ]
    if not pool:
        item["status"] = "REJECTED_MISREDEEMED"
        item["reject_code"] = "NO_PURCHASE_MATCH"
        item["matched_purchase_record_id"] = None
        return
    pool.sort(
        key=lambda r: (
            r.get("transaction_date") or "",
            r.get("created_at") or "",
            r.get("_seq") or 0,
        )
    )
    qualifying = [r for r in pool if r["qualifying_units"] >= required_units]
    if not qualifying:
        item["status"] = "REJECTED_MISREDEEMED"
        item["reject_code"] = "INSUFFICIENT_QUALIFYING_UNITS"
        item["matched_purchase_record_id"] = pool[0]["id"]
        return
    item["status"] = "ACCEPTED"
    item["reject_code"] = None
    item["matched_purchase_record_id"] = qualifying[0]["id"]


# --------------------------------------------------------- fraud scoring 3.6
def _fraud_pool(retailer_id):
    pool = []
    for submission in db.db.submissions.values():
        if submission["retailer_id"] != retailer_id:
            continue
        for item in items_of_submission(submission["id"]):
            if item["status"] != "CAPTURED":
                pool.append(item)
    return pool


def _variant_rates(pool, weighted):
    """Returns (duplicate_rate, misredemption_rate, counterfeit_rate)."""
    now = db.now()
    total = Decimal(0)
    dup = Decimal(0)
    mis = Decimal(0)
    cft = Decimal(0)
    for item in pool:
        adjudicated = db.parse_instant(item.get("adjudicated_at"))
        if adjudicated is None:
            continue
        if weighted:
            age_days = (now - adjudicated).days
            if age_days < 0:
                age_days = 0
            bucket = age_days // calc.FRAUD_DECAY_HALFLIFE_DAYS
            weight = Decimal("0.5") ** int(bucket)
        else:
            cutoff = now - db.timedelta(days=calc.FRAUD_WINDOW_DAYS)
            if adjudicated < cutoff:
                continue
            weight = Decimal(1)
        total += weight
        if item["status"] == "REJECTED_DUPLICATE":
            dup += weight
        elif item["status"] == "REJECTED_MISREDEEMED":
            mis += weight
        elif item["status"] == "REJECTED_COUNTERFEIT":
            cft += weight
    if total == 0:
        return calc.ZERO_2, calc.ZERO_2, calc.ZERO_2
    return (
        calc.rhu(dup * Decimal(100) / total, 2),
        calc.rhu(mis * Decimal(100) / total, 2),
        calc.rhu(cft * Decimal(100) / total, 2),
    )


def _score_from_rates(rates):
    raw = (
        rates[0] * calc.DUP_WEIGHT
        + rates[1] * calc.MIS_WEIGHT
        + rates[2] * calc.CFT_WEIGHT
    )
    return min(calc.FRAUD_SCORE_CAP, calc.rhu(raw, 2))


def fraud_rescore(retailer):
    """Recomputes both variants, stores the selected one, applies the gate."""
    pool = _fraud_pool(retailer["id"])
    rolling = _variant_rates(pool, weighted=False)
    lifetime = _variant_rates(pool, weighted=True)
    rolling_score = _score_from_rates(rolling)
    lifetime_score = _score_from_rates(lifetime)
    retailer["fraud_score_rolling_window"] = rolling_score
    retailer["fraud_score_lifetime_weighted"] = lifetime_score
    if retailer["fraud_scoring_mode"] == "LIFETIME_WEIGHTED":
        selected, score = lifetime, lifetime_score
    else:
        selected, score = rolling, rolling_score
    retailer["duplicate_rate"] = selected[0]
    retailer["misredemption_rate"] = selected[1]
    retailer["counterfeit_rate"] = selected[2]
    retailer["fraud_score"] = score
    retailer["last_rescored_at"] = db.now_iso()
    _apply_fraud_gate(retailer, score)
    touch(retailer)
    return retailer


def _apply_fraud_gate(retailer, score):
    if score >= calc.FRAUD_SUSPEND_THRESHOLD:
        target = "SUSPENDED"
    elif score >= calc.FRAUD_WATCHLIST_THRESHOLD:
        target = "WATCHLIST"
    else:
        target = "ACTIVE"
    current = retailer["status"]
    allowed = {
        "ACTIVE": ("WATCHLIST", "SUSPENDED"),
        "WATCHLIST": ("SUSPENDED", "ACTIVE"),
        "SUSPENDED": (),
    }
    if target != current and target in allowed.get(current, ()):
        retailer["status"] = target
    if score >= calc.FRAUD_WATCHLIST_THRESHOLD:
        retailer["handling_fee_tier"] = "PROBATION"
    else:
        retailer["handling_fee_tier"] = retailer["base_fee_tier"]


# -------------------------------------------------------- statement recompute
def recompute_statement_money(statement):
    """Re-runs the settlement waterfall from the submission's current figures."""
    submission = db.db.submissions[statement["submission_id"]]
    retailer = db.db.retailers[statement["retailer_id"]]
    gross = submission["settled_gross_face_value_cents"]
    fee = submission["settled_handling_fee_cents"]
    offset = statement["prior_chargeback_offset_cents"]
    provisional = gross + fee - offset
    base = provisional if provisional > 0 else 0
    pct = calc.holdback_pct(base, retailer)
    holdback = calc.rhu_int(Decimal(base) * pct)
    statement["gross_face_value_cents"] = gross
    statement["handling_fee_total_cents"] = fee
    statement["provisional_net_cents"] = provisional
    statement["holdback_pct"] = pct
    statement["misredemption_holdback_cents"] = holdback
    statement["net_payable_cents"] = provisional - holdback
    return statement


# ------------------------------------------------------- submission closing
def close_submission_if_ready(submission, rescore_on_total_loss=False):
    lots = lots_of_submission(submission["id"])
    if not lots:
        return False
    if submission["intake_status"] != "SORTED":
        return False
    for lot in lots:
        if lot["status"] not in ("VALIDATED", "LOT_REJECTED"):
            return False
    submission["intake_status"] = "CLOSED"
    recompute_item_face_values(submission)
    recompute_settled_money(submission)
    recompute_rejected_lot_count(submission)
    recompute_valuation_method(submission)
    touch(submission)
    if submission["rejected_lot_count"] == submission["sorted_lot_count"]:
        submission["settlement_status"] = "HELD"
        submission["hold_reason"] = "FRAUD_REVIEW"
        retailer = retailer_of_submission(submission)
        retailer["rejected_submission_count"] = (
            retailer["rejected_submission_count"] + 1
        )
        touch(retailer)
        if rescore_on_total_loss:
            fraud_rescore(retailer)
    return True


# ------------------------------------------------------ offer withdrawal 3.2
def withdraw_offer(offer, reason):
    offer["status"] = "WITHDRAWN"
    offer["withdrawn_reason"] = reason
    touch(offer)

    affected = []
    seen = set()
    for lot in lots_of_offer(offer["id"]):
        if lot["status"] != "SORTED":
            continue
        lot["status"] = "LOT_REJECTED"
        lot["reject_reason"] = "OFFER_WITHDRAWN"
        touch(lot)
        submission = submission_of_lot(lot)
        if submission["id"] not in seen:
            seen.add(submission["id"])
            affected.append(submission)

    retailers = {}
    for submission in sort_rows(affected):
        recompute_rejected_lot_count(submission)
        recompute_declared_face_value(submission)
        recompute_settled_money(submission)
        touch(submission)
        close_submission_if_ready(submission, rescore_on_total_loss=False)
        for statement in statements_of_submission(submission["id"]):
            if statement["status"] in ("DRAFT", "SCHEDULED"):
                recompute_statement_money(statement)
                touch(statement)
        retailer = retailer_of_submission(submission)
        retailers[retailer["id"]] = retailer
    for retailer in sort_rows(list(retailers.values())):
        recompute_retailer_unpaid(retailer)
    return offer


# ------------------------------------------------------------ dispute holds
def hold_statements_for_dispute(submission):
    retailers = {}
    for statement in statements_of_submission(submission["id"]):
        if statement["status"] not in ("DRAFT", "SCHEDULED"):
            continue
        statement["status"] = "HELD"
        statement["hold_reason"] = "DISPUTE_OPEN"
        touch(statement)
        retailer = db.db.retailers[statement["retailer_id"]]
        retailers[retailer["id"]] = retailer
    for retailer in sort_rows(list(retailers.values())):
        recompute_retailer_unpaid(retailer)


# ------------------------------------------------------- funding-hold cascade
def apply_funding_shortfall(invoice):
    retailers = {}
    for statement in statements_of_invoice(invoice["id"]):
        if statement["status"] != "SCHEDULED":
            continue
        statement["status"] = "HELD"
        statement["hold_reason"] = "FUNDING_SHORTFALL"
        touch(statement)
        submission = db.db.submissions[statement["submission_id"]]
        if submission["settlement_status"] == "STATEMENT_ISSUED":
            submission["settlement_status"] = "HELD"
            submission["hold_reason"] = "FUNDING_SHORTFALL"
            touch(submission)
        retailer = db.db.retailers[statement["retailer_id"]]
        retailers[retailer["id"]] = retailer
    for retailer in sort_rows(list(retailers.values())):
        recompute_retailer_unpaid(retailer)


def release_funding_holds(invoice):
    retailers = {}
    for statement in statements_of_invoice(invoice["id"]):
        if not (
            statement["status"] == "HELD"
            and statement["hold_reason"] == "FUNDING_SHORTFALL"
        ):
            continue
        statement["status"] = "SCHEDULED"
        statement["hold_reason"] = None
        touch(statement)
        submission = db.db.submissions[statement["submission_id"]]
        if (
            submission["settlement_status"] == "HELD"
            and submission["hold_reason"] == "FUNDING_SHORTFALL"
        ):
            submission["settlement_status"] = "STATEMENT_ISSUED"
            submission["hold_reason"] = None
            touch(submission)
        retailer = db.db.retailers[statement["retailer_id"]]
        retailers[retailer["id"]] = retailer
    for retailer in sort_rows(list(retailers.values())):
        recompute_retailer_unpaid(retailer)


def has_open_dispute(submission_id):
    for lot in lots_of_submission(submission_id):
        for dispute in disputes_of_lot(lot["id"]):
            if dispute["status"] in ("UNDER_REVIEW", "INFO_REQUESTED"):
                return True
    return False
