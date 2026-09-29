"""Derived-field recomputation and cross-entity cascades (PRD sections 2.9, 3.6, 3.7, 3.8, 3.9)."""

import clock
import db
from services import calc

LIVE_AUTHORIZATION_STATES = ("PENDING_SETUP", "AUTHORIZED", "AT_RISK")
COMMITTED_SLOTTING_STATES = ("ACCEPTED", "AMORTIZING", "RECOVERY_HOLD")
OPEN_LIABILITY_STATES = ("AMORTIZING", "RECOVERY_HOLD")


# --------------------------------------------------------------- graph walks
def presentation_of_deal(deal):
    return db.find("presentations", deal.get("presentation_id"))


def review_of_presentation(presentation):
    if presentation is None:
        return None
    return db.find("reviews", presentation.get("review_id"))


def principal_of_deal(deal):
    presentation = presentation_of_deal(deal)
    if presentation is None:
        return None
    return db.find("principals", presentation.get("principal_id"))


def retailer_of_deal(deal):
    review = review_of_presentation(presentation_of_deal(deal))
    if review is None:
        return None
    return db.find("retailers", review.get("retailer_id"))


def principal_of_authorization(auth):
    item = db.find("items", auth.get("item_id"))
    if item is None:
        return None
    return db.find("principals", item.get("principal_id"))


def deals_of_principal(principal_id):
    result = []
    for deal in db.ordered("deals"):
        presentation = db.find("presentations", deal.get("presentation_id"))
        if presentation is not None and presentation.get("principal_id") == principal_id:
            result.append(deal)
    return result


def authorizations_of_deal(deal_id):
    return [a for a in db.ordered("authorizations") if a.get("slotting_deal_id") == deal_id]


def authorizations_of_principal(principal_id):
    result = []
    for auth in db.ordered("authorizations"):
        item = db.find("items", auth.get("item_id"))
        if item is not None and item.get("principal_id") == principal_id:
            result.append(auth)
    return result


def presentations_of_review(review_id):
    return [p for p in db.ordered("presentations") if p.get("review_id") == review_id]


def deals_of_presentation(presentation_id):
    return [d for d in db.ordered("deals") if d.get("presentation_id") == presentation_id]


def promotions_of_authorization(authorization_id):
    return [p for p in db.ordered("promotions") if p.get("authorization_id") == authorization_id]


def live_postings(authorization_id):
    """POSTING entries of an authorization that have not been reversed."""
    entries = [
        s for s in db.ordered("snapshots")
        if s.get("authorization_id") == authorization_id
        and s.get("entry_kind") == "POSTING"
        and not s.get("is_reversed")
    ]
    entries.sort(key=lambda s: s["period_index"])
    return entries


def latest_live_posting(authorization_id):
    entries = live_postings(authorization_id)
    return entries[-1] if entries else None


# ------------------------------------------------------- agreement resolution
def active_agreement(principal_id, retailer_id, category_code, on_date=None):
    """The ACTIVE agreement for the triple whose half-open window covers a date."""
    if on_date is None:
        on_date = clock.today()
    for agreement in db.ordered("agreements"):
        if agreement["status"] != "ACTIVE":
            continue
        if agreement["principal_id"] != principal_id:
            continue
        if agreement["retailer_id"] != retailer_id:
            continue
        if agreement["category_code"] != category_code:
            continue
        start = clock.parse_date(agreement["effective_start_date"])
        end = clock.parse_date(agreement["effective_end_date"])
        if start <= on_date < end:
            return agreement
    return None


def exclusive_blocker(principal_id, retailer_id, category_code, on_date=None):
    """Another principal's ACTIVE, date-covering, category-exclusive agreement."""
    if on_date is None:
        on_date = clock.today()
    for agreement in db.ordered("agreements"):
        if agreement["status"] != "ACTIVE" or not agreement.get("exclusive_in_category"):
            continue
        if agreement["retailer_id"] != retailer_id or agreement["category_code"] != category_code:
            continue
        if agreement["principal_id"] == principal_id:
            continue
        start = clock.parse_date(agreement["effective_start_date"])
        end = clock.parse_date(agreement["effective_end_date"])
        if start <= on_date < end:
            return agreement
    return None


# ------------------------------------------------------- derived recomputation
def recompute_prep_completeness(presentation):
    item_ids = presentation.get("item_ids") or []
    if not item_ids:
        db.assign(presentation, prep_completeness_bps=0)
        return
    validated = 0
    for item_id in item_ids:
        item = db.find("items", item_id)
        if item is not None and item.get("catalog_state") == "VALIDATED":
            validated += 1
    db.assign(presentation, prep_completeness_bps=calc.floor_div(validated * 10000, len(item_ids)))


def recompute_prep_for_item(item_id):
    """Every DRAFT presentation listing the item re-derives its completeness."""
    for presentation in db.ordered("presentations"):
        if presentation["status"] != "DRAFT":
            continue
        if item_id in (presentation.get("item_ids") or []):
            recompute_prep_completeness(presentation)


def recompute_distribution(auth):
    """Counters and void rate from the latest live POSTING under the pinned basis."""
    latest = latest_live_posting(auth["id"])
    metrics = calc.void_metrics(auth["void_rate_basis"], auth["authorized_store_count"], latest)
    db.assign(auth, **metrics)


def recompute_trade_spend(auth):
    settled = 0
    for event in promotions_of_authorization(auth["id"]):
        if event["state"] == "SETTLED":
            settled += event.get("actual_funding_cents") or 0
    db.assign(
        auth,
        promo_settled_funding_cents=settled,
        trade_spend_total_cents=auth.get("slotting_share_cents", 0) + settled,
    )


def recompute_principal(principal):
    """The five derived aggregates plus the ratio and posture (PRD section 2.9)."""
    if principal is None:
        return
    committed = 0
    open_liability = 0
    for deal in deals_of_principal(principal["id"]):
        if deal["state"] in COMMITTED_SLOTTING_STATES:
            committed += deal["accepted_fee_cents"]
        if deal["state"] in OPEN_LIABILITY_STATES:
            open_liability += deal["unamortized_balance_cents"]

    open_deduction = 0
    for deduction in db.ordered("deductions"):
        if deduction["principal_id"] == principal["id"] and deduction["settlement_state"] == "OPEN":
            open_deduction += deduction["open_cents"]

    at_risk = 0
    for auth in authorizations_of_principal(principal["id"]):
        if auth["authorization_state"] == "AT_RISK":
            at_risk += 1

    ratio = calc.liability_ratio_bps(open_liability, open_deduction, principal["slotting_budget_cents"])
    db.assign(
        principal,
        slotting_committed_cents=committed,
        open_slotting_liability_cents=open_liability,
        open_deduction_cents=open_deduction,
        at_risk_authorization_count=at_risk,
        liability_ratio_bps=ratio,
        credit_posture=calc.credit_posture(at_risk, ratio),
    )


# ------------------------------------------------------------ risk transitions
def evaluate_at_risk(auth):
    """The AUTHORIZED <-> AT_RISK decision; returns 'ENTERED', 'LEFT' or None."""
    retailer = db.find("retailers", auth["retailer_id"])
    threshold = retailer["at_risk_void_rate_bps"] if retailer else 0
    rate = auth["void_rate_bps"]
    if auth["authorization_state"] == "AUTHORIZED" and rate >= threshold:
        db.assign(auth, authorization_state="AT_RISK")
        return "ENTERED"
    if auth["authorization_state"] == "AT_RISK" and rate < threshold:
        db.assign(auth, authorization_state="AUTHORIZED")
        return "LEFT"
    return None


def release_recovery_hold(deal):
    """RECOVERY_HOLD -> AMORTIZING once no linked authorization is still at risk."""
    if deal is None or deal["state"] != "RECOVERY_HOLD":
        return
    for auth in authorizations_of_deal(deal["id"]):
        if auth["authorization_state"] == "AT_RISK":
            return
    db.assign(deal, state="AMORTIZING")


# ----------------------------------------------------------------- amortization
def apply_amortization(deal, snapshot):
    """Step 3 of a posting: amortize against the linked deal when it is live."""
    if deal is None or deal["state"] not in OPEN_LIABILITY_STATES:
        snapshot["amortized_amount_cents"] = 0
        snapshot["_amortized_to_deal"] = None
        return
    amount = calc.amortization_amount(deal, snapshot["reported_case_volume"])
    snapshot["amortized_amount_cents"] = amount
    snapshot["_amortized_to_deal"] = deal["id"]
    db.assign(
        deal,
        recovered_cents=deal["recovered_cents"] + amount,
        unamortized_balance_cents=deal["unamortized_balance_cents"] - amount,
        periods_posted=deal["periods_posted"] + 1,
    )
    if deal["unamortized_balance_cents"] == 0:
        db.assign(deal, state="RECOVERED")
        for auth in authorizations_of_deal(deal["id"]):
            if auth["settlement_state"] == "SLOTTING_AMORTIZING":
                db.assign(auth, settlement_state="SLOTTING_RECOVERED")


def rollback_amortization(deal, snapshot):
    """Undo one posting's amortization, reopening the deal when it had closed."""
    if deal is None or snapshot.get("_amortized_to_deal") != deal["id"]:
        return
    amount = snapshot["amortized_amount_cents"]
    reopened = deal["state"] == "RECOVERED"
    db.assign(
        deal,
        recovered_cents=deal["recovered_cents"] - amount,
        unamortized_balance_cents=deal["unamortized_balance_cents"] + amount,
        periods_posted=deal["periods_posted"] - 1,
    )
    if reopened:
        db.assign(deal, state="AMORTIZING")
        for auth in authorizations_of_deal(deal["id"]):
            if auth["settlement_state"] == "SLOTTING_RECOVERED":
                db.assign(auth, settlement_state="SLOTTING_AMORTIZING")


def maybe_write_off(deal):
    """Charge off a deal whose last live authorization has just been discontinued."""
    if deal is None or deal["state"] not in OPEN_LIABILITY_STATES:
        return
    auths = authorizations_of_deal(deal["id"])
    if not auths:
        return
    for auth in auths:
        if auth["authorization_state"] != "DISCONTINUED":
            return
    balance = deal["unamortized_balance_cents"]
    if balance <= 0:
        return
    db.assign(
        deal,
        state="WRITTEN_OFF",
        written_off_cents=deal["written_off_cents"] + balance,
        unamortized_balance_cents=0,
    )
    for auth in auths:
        if auth["settlement_state"] == "SLOTTING_AMORTIZING":
            db.assign(auth, settlement_state="SLOTTING_WRITTEN_OFF")


# ------------------------------------------------------------ acceptance cascade
def acceptance_cascade(deal):
    """The three hops of PRD section 3.6 fired inside the acceptance request."""
    auths = authorizations_of_deal(deal["id"])

    # hop 1 — both state dimensions move at once
    for auth in auths:
        if auth["authorization_state"] == "PENDING_SETUP":
            db.assign(auth, authorization_state="AUTHORIZED")
        if auth["settlement_state"] == "UNBILLED":
            db.assign(auth, settlement_state="SLOTTING_AMORTIZING")

    # hop 2 — allocate the accepted fee across the linked authorizations
    ordered = sorted(auths, key=lambda a: (a["created_at"], _item_upc(a), a["_seq"]))
    shares = calc.slotting_share_allocation(deal["accepted_fee_cents"], len(ordered))
    for auth, share in zip(ordered, shares):
        db.assign(auth, slotting_share_cents=share)
        recompute_trade_spend(auth)

    # hop 3 — re-derive the principal
    recompute_principal(principal_of_deal(deal))


def _item_upc(auth):
    item = db.find("items", auth.get("item_id"))
    return item["upc"] if item else ""


# ------------------------------------------------------- promotion settlement
def promo_settlement_cascade(deduction):
    """A PROMO_BILLBACK leaving OPEN feeds the event's settled funding."""
    if deduction["reason_code"] != "PROMO_BILLBACK":
        return
    event = db.find("promotions", deduction.get("promotion_event_id"))
    if event is None:
        return
    db.assign(event, settled_funding_cents=event["settled_funding_cents"] + deduction["conceded_cents"])
    if event["state"] == "EXECUTED" and event["settled_funding_cents"] >= (event.get("actual_funding_cents") or 0):
        db.assign(event, state="SETTLED")
        auth = db.find("authorizations", event.get("authorization_id"))
        if auth is not None:
            recompute_trade_spend(auth)


# ---------------------------------------------------------------- deal rejection
def reject_deal(deal, reason):
    """A rejected deal discontinues every authorization still awaiting setup."""
    db.assign(deal, state="REJECTED", reject_reason=reason)
    for auth in authorizations_of_deal(deal["id"]):
        if auth["authorization_state"] == "PENDING_SETUP":
            db.assign(auth, authorization_state="DISCONTINUED", discontinue_reason="DEAL_REJECTED")
