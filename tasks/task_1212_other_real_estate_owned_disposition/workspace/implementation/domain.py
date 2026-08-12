"""Domain logic: derived fields, calculations, cascades, serializers."""
from datetime import timedelta
from decimal import Decimal

import db
from util import new_id, now_iso, q2, q4, money_out, pdate, render_derived

# ---- Constants (from scaffold calculations) ----
COST_TO_SELL_PCT = Decimal("0.08")
MEASUREMENT_WINDOW_DAYS = 180
HOLDING_PERIOD_DAYS = 1825
MAX_TOTAL_EXTENSION_DAYS = 1825
APPRAISAL_INTERVAL_DAYS = 365
APPRAISAL_DUE_SOON_WINDOW_DAYS = 30
CLOSING_COST_FLAT = Decimal("2500.00")
DEEP_DISCOUNT_RATIO = Decimal("0.9")
TIER_1_LIMIT = Decimal("500000.00")
TIER_1_RATE = Decimal("0.06")
TIER_2_LIMIT = Decimal("1000000.00")
TIER_2_RATE = Decimal("0.05")
TIER_3_RATE = Decimal("0.03")
LAND_SURCHARGE = Decimal("0.01")
SF_COMMISSION_CAP_PCT = Decimal("0.06")
SPLIT_RATIO = Decimal("0.5")
W_CLOSE_RATE = Decimal("0.5")
W_MARKET_TIME = Decimal("0.3")
W_PRICE_RATIO = Decimal("0.2")
DAYS_CAP = Decimal(180)

ROLE_RANK = {"OREOSpecialist": 1, "CreditOfficer": 2, "OREOCommittee": 3}

TERMINAL_LIFECYCLE = ("DISPOSED", "CHARGED_OFF")
OPEN_ISSUE_STATES = ("OPEN", "IN_REMEDIATION")
PENDING_OFFER_STATES = ("RECEIVED", "UNDER_REVIEW", "COUNTERED")
TERMINAL_OFFER_STATES = ("CLOSED", "REJECTED", "WITHDRAWN", "RESCINDED")


# ---- Generic entity helpers ----

def base_entity():
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }


def append_only_entity():
    return {"id": new_id(), "created_at": now_iso(), "_seq": db.next_seq()}


def bump(e):
    e["version"] += 1
    e["updated_at"] = now_iso()


def ledger_append(property_id, entry_type, amount, memo, write_down_id=None, closing_statement_id=None):
    e = append_only_entity()
    e.update({
        "property_id": property_id,
        "write_down_id": write_down_id,
        "closing_statement_id": closing_statement_id,
        "entry_type": entry_type,
        "amount": q2(amount),
        "memo": memo,
    })
    db.ledger[e["id"]] = e
    return e


def new_write_down(property_id, amount, reason, status, auto_generated, proposed_by, approved_by=None):
    wd = base_entity()
    wd.update({
        "property_id": property_id,
        "amount": q2(amount),
        "reason": reason,
        "status": status,
        "auto_generated": auto_generated,
        "proposed_by_user_id": proposed_by,
        "approved_by_user_id": approved_by,
    })
    db.write_downs[wd["id"]] = wd
    return wd


# ---- Property derived fields ----

def costs_of(pid):
    return [c for c in db.costs.values() if c["property_id"] == pid]


def capitalized_total(pid):
    return sum((c["amount"] for c in costs_of(pid) if c["cost_type"] == "CAPITAL_IMPROVEMENT"), Decimal(0))


def expensed_total(pid):
    return sum((c["amount"] for c in costs_of(pid) if c["cost_type"] != "CAPITAL_IMPROVEMENT"), Decimal(0))


def write_downs_of(pid):
    return [w for w in db.write_downs.values() if w["property_id"] == pid]


def posted_wd_total(pid):
    return sum((w["amount"] for w in write_downs_of(pid) if w["status"] == "POSTED"), Decimal(0))


def pending_wd_count(pid):
    return sum(1 for w in write_downs_of(pid) if w["status"] == "PROPOSED")


def carrying_value(p):
    return q2(p["acquisition_basis"] + capitalized_total(p["id"]) - posted_wd_total(p["id"]))


def basis_from(fair_value):
    return q2(fair_value - q2(fair_value * COST_TO_SELL_PCT))


def certified_appraisals(pid):
    return [a for a in db.appraisals.values() if a["property_id"] == pid and a["status"] == "CERTIFIED"]


def latest_certified(pid):
    cs = certified_appraisals(pid)
    if not cs:
        return None
    return max(cs, key=lambda a: (pdate(a["effective_date"]), a["_seq"]))


def current_fair_value(p):
    a = latest_certified(p["id"])
    return a["appraised_value"] if a else None


def nrv_from(cfv):
    return q2(cfv - q2(cfv * COST_TO_SELL_PCT))


def appraisal_status(p):
    a = latest_certified(p["id"])
    if a is None:
        return "UNAPPRAISED"
    eff = pdate(a["effective_date"])
    if db.clock <= eff + timedelta(days=APPRAISAL_INTERVAL_DAYS - APPRAISAL_DUE_SOON_WINDOW_DAYS):
        return "CURRENT"
    if db.clock <= eff + timedelta(days=APPRAISAL_INTERVAL_DAYS):
        return "DUE_SOON"
    return "OVERDUE"


def active_listing_count(pid):
    return sum(1 for l in db.listings.values() if l["property_id"] == pid and l["status"] == "ACTIVE")


def issue_counts(pid):
    env = sum(1 for i in db.issues.values()
              if i["property_id"] == pid and i["issue_type"] == "ENVIRONMENTAL" and i["status"] in OPEN_ISSUE_STATES)
    title = sum(1 for i in db.issues.values()
                if i["property_id"] == pid and i["issue_type"] == "TITLE" and i["status"] in OPEN_ISSUE_STATES)
    return env, title


def extension_days_approved(pid):
    return sum(e["requested_extension_days"] for e in db.extensions.values()
               if e["property_id"] == pid and e["status"] == "APPROVED")


def holding_deadline(p):
    return pdate(p["acquisition_date"]) + timedelta(days=HOLDING_PERIOD_DAYS + extension_days_approved(p["id"]))


def recognized_gain_loss_total(pid):
    return sum((e["amount"] for e in db.ledger.values()
                if e["property_id"] == pid and e["entry_type"] in ("GAIN_RECOGNIZED", "LOSS_RECOGNIZED")),
               Decimal(0))


# ---- Calculations ----

def commission_tiered(price, property_type, financing_type):
    """Tiered commission, single half-up rounding at the end of the tier pipeline;
    SELLER_FINANCED caps the rounded tiered total at round(6% * price, 2)."""
    sur = LAND_SURCHARGE if property_type == "LAND" else Decimal("0")
    r1 = TIER_1_RATE + sur
    r2 = TIER_2_RATE + sur
    r3 = TIER_3_RATE + sur
    p1 = min(price, TIER_1_LIMIT)
    p2 = min(max(price - TIER_1_LIMIT, Decimal(0)), TIER_2_LIMIT - TIER_1_LIMIT)
    p3 = max(price - TIER_2_LIMIT, Decimal(0))
    tiered = q2(r1 * p1 + r2 * p2 + r3 * p3)
    if financing_type == "SELLER_FINANCED":
        cap = q2(SF_COMMISSION_CAP_PCT * price)
        return min(tiered, cap)
    return tiered


def commission_split(commission_total):
    """Pinned order: round total first, listing share = round(half), selling = remainder."""
    listing_share = q2(commission_total * SPLIT_RATIO)
    selling_share = q2(commission_total - listing_share)
    return listing_share, selling_share


def net_proceeds_of(price, property_type, financing_type):
    commission = commission_tiered(price, property_type, financing_type)
    return q2(price - commission - CLOSING_COST_FLAT), commission


def recognition_variant(financing_type, down_payment, gain_loss, contract_price):
    """Returns (recognized_gain_at_settlement, deferred_gain)."""
    if financing_type == "CASH":
        return q2(gain_loss), Decimal("0.00")
    if gain_loss > 0:
        recognized = q2(down_payment * (gain_loss / contract_price))
        return recognized, q2(gain_loss - recognized)
    return q2(gain_loss), Decimal("0.00")


def required_rank_for(net_proceeds, carrying):
    rank = 3
    for t in db.tiers.values():
        lo = t["min_net_proceeds"]
        hi = t["max_net_proceeds"]
        if net_proceeds >= lo and (hi is None or net_proceeds < hi):
            rank = t["required_rank"]
            break
    if net_proceeds < DEEP_DISCOUNT_RATIO * carrying:
        rank = 3
    return rank


def broker_performance_score(broker):
    """Weighted score over the broker's SETTLED closings; None while zero settled."""
    listing_by_id = {l["id"]: l for l in db.listings.values() if l["broker_id"] == broker["id"]}
    lids = set(listing_by_id.keys())
    settled = []
    for c in db.closings.values():
        if c["status"] != "SETTLED":
            continue
        o = db.offers.get(c["offer_id"])
        if o and o.get("listing_agreement_id") in lids:
            settled.append((c, listing_by_id[o["listing_agreement_id"]]))
    if not settled:
        return None
    broker_offers = [o for o in db.offers.values() if o.get("listing_agreement_id") in lids]
    terminal = [o for o in broker_offers if o["status"] in TERMINAL_OFFER_STATES]
    closed_n = sum(1 for o in terminal if o["status"] == "CLOSED")
    close_rate = Decimal(closed_n) / Decimal(len(terminal)) if terminal else Decimal(0)
    days = [(pdate(c["closing_date"]) - pdate(l["start_date"])).days for (c, l) in settled]
    avg_days = Decimal(sum(days)) / Decimal(len(days))
    market_ratio = Decimal(1) - min(avg_days, DAYS_CAP) / DAYS_CAP
    price_ratio = sum((c["contract_price"] / l["listing_price"]) for (c, l) in settled) / Decimal(len(settled))
    return q4(W_CLOSE_RATE * close_rate + W_MARKET_TIME * market_ratio + W_PRICE_RATIO * price_ratio)


# ---- Cascades ----

def charge_off(p):
    """Full regulatory charge-off cascade (clock sweep path and manual path)."""
    pid = p["id"]
    carrying = carrying_value(p)
    new_write_down(pid, carrying, "REGULATORY_CHARGE_OFF", "POSTED", True, "system", "system")
    ledger_append(pid, "CHARGE_OFF", -carrying, "Regulatory charge-off")
    for l in db.listings.values():
        if l["property_id"] == pid and l["status"] == "ACTIVE":
            l["status"] = "TERMINATED"
            l["termination_reason"] = "CHARGE_OFF"
            bump(l)
    for o in db.offers.values():
        if o["property_id"] != pid:
            continue
        if o["status"] in PENDING_OFFER_STATES:
            o["status"] = "REJECTED"
            o["rejection_reason"] = "PROPERTY_CHARGED_OFF"
            bump(o)
        elif o["status"] == "ACCEPTED":
            o["status"] = "RESCINDED"
            bump(o)
    p["lifecycle_status"] = "CHARGED_OFF"
    bump(p)


def run_certification_cascade(appraisal, user_id):
    """Appraisal SUBMITTED -> CERTIFIED with the three-link property cascade."""
    appraisal["status"] = "CERTIFIED"
    appraisal["certified_by_user_id"] = user_id
    bump(appraisal)
    p = db.properties[appraisal["property_id"]]
    pid = p["id"]
    eff = pdate(appraisal["effective_date"])
    window_end = pdate(p["acquisition_date"]) + timedelta(days=MEASUREMENT_WINDOW_DAYS)
    in_window = eff <= window_end
    prior_in_window = any(
        o["id"] != appraisal["id"] and pdate(o["effective_date"]) <= window_end
        for o in certified_appraisals(pid)
    )
    if in_window and not prior_in_window:
        # FINAL acquisition variant: re-measure basis, post delta write-down if nonzero.
        old_carrying = carrying_value(p)
        new_basis = basis_from(appraisal["appraised_value"])
        delta = q2(old_carrying - new_basis)
        p["fair_value_at_acquisition"] = appraisal["appraised_value"]
        p["acquisition_basis"] = new_basis
        if delta != 0:
            wd = new_write_down(pid, delta, "MEASUREMENT_PERIOD_ADJUSTMENT", "POSTED",
                                True, "system", "system")
            ledger_append(pid, "WRITE_DOWN", -delta, "Measurement period adjustment",
                          write_down_id=wd["id"])
    elif not in_window:
        # Write-down evaluation against the newly certified value.
        cfv = current_fair_value(p)
        nrv = nrv_from(cfv)
        required = q2(carrying_value(p) - nrv)
        if required > 0:
            new_write_down(pid, required, "MARKET_DECLINE", "PROPOSED", True, "system")
    bump(p)


def run_clock_sweep():
    """Three-phase sweep after a clock set: (1) appraisal currency is derived on read,
    (2) expire ACTIVE listings past end_date, (3) charge off properties past deadline."""
    # Phase 2: listing expiry.
    for p in list(db.properties.values()):
        pid = p["id"]
        expired = [l for l in db.listings.values()
                   if l["property_id"] == pid and l["status"] == "ACTIVE"
                   and pdate(l["end_date"]) < db.clock]
        if not expired:
            continue
        for l in expired:
            l["status"] = "EXPIRED"
            bump(l)
        if p["lifecycle_status"] == "MARKETED" and active_listing_count(pid) == 0:
            p["lifecycle_status"] = "HELD"
        bump(p)
    # Phase 3: holding-period charge-off sweep.
    for p in list(db.properties.values()):
        if p["lifecycle_status"] in ("HELD", "MARKETED", "UNDER_CONTRACT") and db.clock > holding_deadline(p):
            charge_off(p)


# ---- Serializers ----

def property_json(p):
    pid = p["id"]
    cfv = current_fair_value(p)
    env, title = issue_counts(pid)
    return {
        "id": pid,
        "address": p["address"],
        "state_code": p["state_code"],
        "county": p["county"],
        "property_type": p["property_type"],
        "acquisition_date": p["acquisition_date"],
        "bpo_value": money_out(p["bpo_value"]),
        "foreclosure_debt": money_out(p["foreclosure_debt"]),
        "fair_value_at_acquisition": money_out(p["fair_value_at_acquisition"]),
        "acquisition_basis": money_out(p["acquisition_basis"]),
        "carrying_value": money_out(carrying_value(p)),
        "capitalized_cost_total": money_out(capitalized_total(pid)),
        "expensed_cost_total": money_out(expensed_total(pid)),
        "current_fair_value": money_out(cfv),
        "net_realizable_value": money_out(nrv_from(cfv)) if cfv is not None else None,
        "holding_deadline": render_derived(holding_deadline(p), p["_acq_date_only"]),
        "extension_days_approved": extension_days_approved(pid),
        "lifecycle_status": p["lifecycle_status"],
        "appraisal_status": appraisal_status(p),
        "active_listing_count": active_listing_count(pid),
        "open_environmental_issue_count": env,
        "open_title_issue_count": title,
        "recognized_gain_loss_total": money_out(recognized_gain_loss_total(pid)),
        "pending_write_down_count": pending_wd_count(pid),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def summary_json(p):
    pid = p["id"]
    j = property_json(p)
    return {
        "property_id": pid,
        "lifecycle_status": j["lifecycle_status"],
        "appraisal_status": j["appraisal_status"],
        "acquisition_basis": j["acquisition_basis"],
        "capitalized_cost_total": j["capitalized_cost_total"],
        "expensed_cost_total": j["expensed_cost_total"],
        "posted_write_down_total": money_out(posted_wd_total(pid)),
        "carrying_value": j["carrying_value"],
        "current_fair_value": j["current_fair_value"],
        "net_realizable_value": j["net_realizable_value"],
        "holding_deadline": j["holding_deadline"],
        "extension_days_approved": j["extension_days_approved"],
        "active_listing_count": j["active_listing_count"],
        "open_environmental_issue_count": j["open_environmental_issue_count"],
        "open_title_issue_count": j["open_title_issue_count"],
        "pending_write_down_count": j["pending_write_down_count"],
        "recognized_gain_loss_total": j["recognized_gain_loss_total"],
    }


def appraiser_json(a):
    return {
        "id": a["id"], "name": a["name"], "license_number": a["license_number"],
        "coverage_states": list(a["coverage_states"]), "fee_flat": money_out(a["fee_flat"]),
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def broker_json(b):
    score = broker_performance_score(b)
    return {
        "id": b["id"], "name": b["name"], "license_number": b["license_number"],
        "coverage_states": list(b["coverage_states"]), "status": b["status"],
        "performance_score": float(score) if score is not None else None,
        "created_at": b["created_at"], "updated_at": b["updated_at"], "version": b["version"],
    }


def cost_json(c):
    return {
        "id": c["id"], "property_id": c["property_id"], "cost_type": c["cost_type"],
        "amount": money_out(c["amount"]), "incurred_date": c["incurred_date"],
        "description": c.get("description"), "created_at": c["created_at"],
    }


def appraisal_json(a):
    return {
        "id": a["id"], "property_id": a["property_id"], "appraiser_id": a["appraiser_id"],
        "effective_date": a["effective_date"], "appraised_value": money_out(a["appraised_value"]),
        "status": a["status"], "submitted_by_user_id": a["submitted_by_user_id"],
        "certified_by_user_id": a["certified_by_user_id"],
        "rejection_reason": a["rejection_reason"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def write_down_json(w):
    return {
        "id": w["id"], "property_id": w["property_id"], "amount": money_out(w["amount"]),
        "reason": w["reason"], "status": w["status"], "auto_generated": w["auto_generated"],
        "proposed_by_user_id": w["proposed_by_user_id"],
        "approved_by_user_id": w["approved_by_user_id"],
        "created_at": w["created_at"], "updated_at": w["updated_at"], "version": w["version"],
    }


def listing_json(l):
    return {
        "id": l["id"], "property_id": l["property_id"], "broker_id": l["broker_id"],
        "start_date": l["start_date"], "end_date": l["end_date"],
        "listing_price": money_out(l["listing_price"]), "status": l["status"],
        "termination_reason": l["termination_reason"],
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def offer_json(o):
    return {
        "id": o["id"], "property_id": o["property_id"],
        "listing_agreement_id": o["listing_agreement_id"],
        "buyer_name": o["buyer_name"], "offer_price": money_out(o["offer_price"]),
        "financing_type": o["financing_type"],
        "down_payment": money_out(o["down_payment"]),
        "earnest_money": money_out(o["earnest_money"]),
        "status": o["status"], "current_price": money_out(o["current_price"]),
        "counter_round": o["counter_round"], "rejection_reason": o["rejection_reason"],
        "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
    }


def issue_json(i):
    return {
        "id": i["id"], "property_id": i["property_id"], "issue_type": i["issue_type"],
        "severity": i["severity"], "description": i["description"], "status": i["status"],
        "resolution_notes": i["resolution_notes"],
        "created_at": i["created_at"], "updated_at": i["updated_at"], "version": i["version"],
    }


def closing_json(c):
    return {
        "id": c["id"], "offer_id": c["offer_id"], "property_id": c["property_id"],
        "closing_date": c["closing_date"], "contract_price": money_out(c["contract_price"]),
        "commission_total": money_out(c["commission_total"]),
        "listing_broker_share": money_out(c["listing_broker_share"]),
        "selling_broker_share": money_out(c["selling_broker_share"]),
        "closing_cost_flat": money_out(c["closing_cost_flat"]),
        "net_proceeds": money_out(c["net_proceeds"]),
        "carrying_value_at_closing": money_out(c["carrying_value_at_closing"]),
        "gain_loss": money_out(c["gain_loss"]),
        "recognized_gain_at_settlement": money_out(c["recognized_gain_at_settlement"]),
        "deferred_gain": money_out(c["deferred_gain"]),
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def extension_json(e):
    return {
        "id": e["id"], "property_id": e["property_id"],
        "requested_extension_days": e["requested_extension_days"],
        "justification": e["justification"], "status": e["status"],
        "submitted_by_user_id": e["submitted_by_user_id"],
        "decided_by_user_id": e["decided_by_user_id"],
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def ledger_json(e):
    return {
        "id": e["id"], "property_id": e["property_id"],
        "write_down_id": e["write_down_id"], "closing_statement_id": e["closing_statement_id"],
        "entry_type": e["entry_type"], "amount": money_out(e["amount"]), "memo": e["memo"],
        "created_at": e["created_at"],
    }


def tier_json(t):
    return {
        "id": t["id"], "name": t["name"],
        "min_net_proceeds": money_out(t["min_net_proceeds"]),
        "max_net_proceeds": money_out(t["max_net_proceeds"]),
        "required_role": t["required_role"], "required_rank": t["required_rank"],
        "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
    }


def sort_entities(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
