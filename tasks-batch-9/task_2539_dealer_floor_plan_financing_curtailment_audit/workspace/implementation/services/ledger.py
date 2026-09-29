"""Capacity aggregates (2.11), dealer counters, the risk assessment (2.10) and
the shared suspension cascade."""

import db
from services import spec


# --------------------------------------------------------------------------
# Lookups and pinned orderings
# --------------------------------------------------------------------------


def dealer_line(dealer_id):
    """The dealership's live facility (PENDING, ACTIVE or SUSPENDED)."""
    for line in db.rows("credit_lines"):
        if line["dealer_id"] == dealer_id and line["status"] in spec.LIVE_LINE_STATUSES:
            return line
    return None


def any_dealer_line(dealer_id):
    live = dealer_line(dealer_id)
    if live is not None:
        return live
    lines = [l for l in db.rows("credit_lines") if l["dealer_id"] == dealer_id]
    return lines[-1] if lines else None


def line_units(line_id):
    return [u for u in db.rows("inventory_units") if u["credit_line_id"] == line_id]


def dealer_units(dealer_id):
    return [u for u in db.rows("inventory_units") if u["dealer_id"] == dealer_id]


def unit_line(unit):
    return db.get("credit_lines", unit["credit_line_id"])


def obligation_order(rows):
    """due_date ascending, then created_at ascending."""
    return sorted(rows, key=lambda o: (o["due_date"], o["created_at"], o["_seq"]))


def unit_obligations(unit_id, statuses=None):
    rows = [o for o in db.rows("curtailment_obligations") if o["unit_id"] == unit_id]
    if statuses is not None:
        rows = [o for o in rows if o["status"] in statuses]
    return obligation_order(rows)


def dealer_obligations(dealer_id, statuses=None):
    rows = [o for o in db.rows("curtailment_obligations") if o["dealer_id"] == dealer_id]
    if statuses is not None:
        rows = [o for o in rows if o["status"] in statuses]
    return obligation_order(rows)


def unit_incidents(unit_id, statuses=None):
    rows = [i for i in db.rows("incidents") if i["unit_id"] == unit_id]
    if statuses is not None:
        rows = [i for i in rows if i["status"] in statuses]
    return rows


def dealer_incidents(dealer_id, statuses=None):
    rows = [i for i in db.rows("incidents") if i["dealer_id"] == dealer_id]
    if statuses is not None:
        rows = [i for i in rows if i["status"] in statuses]
    return rows


def unit_tiers(line_id, inventory_class):
    rows = [
        t
        for t in db.rows("curtailment_tiers")
        if t["credit_line_id"] == line_id and t["inventory_class"] == inventory_class
    ]
    return sorted(rows, key=lambda t: (t["age_days_from"], t["_seq"]))


# --------------------------------------------------------------------------
# 2.11 -- facility capacity and the borrowing base
# --------------------------------------------------------------------------


def recompute_availability(line):
    if line is None:
        return None
    units = line_units(line["id"])
    outstanding = 0
    eligible = 0
    class_totals = {"USED": 0, "DEMONSTRATOR": 0}
    for unit in units:
        principal = int(unit["outstanding_principal_cents"])
        if unit["funding_status"] in spec.OUTSTANDING_FUNDING_STATUSES:
            outstanding += principal
            if unit["inventory_class"] in class_totals:
                class_totals[unit["inventory_class"]] += principal
        if (
            unit["eligibility_status"] == "ELIGIBLE"
            and unit["funding_status"] in spec.COLLATERAL_FUNDING_STATUSES
        ):
            eligible += principal
    line["outstanding_principal_cents"] = outstanding
    line["eligible_collateral_cents"] = eligible
    line["class_outstanding_cents_used"] = class_totals["USED"]
    line["class_outstanding_cents_demonstrator"] = class_totals["DEMONSTRATOR"]
    line["borrowing_base_deficiency_cents"] = max(0, outstanding - eligible)
    line["available_credit_cents"] = (
        int(line["credit_limit_cents"]) - outstanding - int(line["charged_off_principal_cents"])
    )
    return line


def class_outstanding(line, inventory_class):
    if inventory_class == "USED":
        return int(line["class_outstanding_cents_used"])
    if inventory_class == "DEMONSTRATOR":
        return int(line["class_outstanding_cents_demonstrator"])
    return 0


def class_sublimit(line, inventory_class):
    if inventory_class == "USED":
        return int(line["class_sublimit_cents_used"])
    if inventory_class == "DEMONSTRATOR":
        return int(line["class_sublimit_cents_demonstrator"])
    return None


# --------------------------------------------------------------------------
# Denormalized dealer counters
# --------------------------------------------------------------------------


def recompute_dealer_counters(dealer):
    open_incidents = dealer_incidents(dealer["id"], ("OPEN",))
    dealer["open_sot_incident_count"] = len(open_incidents)
    dealer["open_sot_exposure_cents"] = sum(int(i["exposure_cents"]) for i in open_incidents)
    dealer["delinquent_unit_count"] = len(
        [u for u in dealer_units(dealer["id"]) if u["funding_status"] == "DELINQUENT_CURTAILMENT"]
    )
    return dealer


# --------------------------------------------------------------------------
# 2.10 -- the risk assessment
# --------------------------------------------------------------------------


def risk_anchor(dealer):
    reconciled = [
        a
        for a in db.rows("audits")
        if a["dealer_id"] == dealer["id"]
        and a["status"] in spec.RECONCILED_AUDIT_STATUSES
        and a.get("reconciled_at")
    ]
    if reconciled:
        newest = max(reconciled, key=lambda a: (a["reconciled_at"], a["_seq"]))
        return newest["reconciled_at"]
    line = any_dealer_line(dealer["id"])
    if line is not None and line.get("activated_at"):
        return line["activated_at"]
    return None


def recompute_risk(dealer):
    score = 100
    score -= spec.RISK_SOT_PENALTY * int(dealer["open_sot_incident_count"])
    score -= spec.RISK_DELINQUENT_PENALTY * int(dealer["delinquent_unit_count"])
    if dealer.get("last_covenant_result") == "FAIL":
        score -= spec.RISK_COVENANT_FAIL_PENALTY
    score = max(0, min(100, score))
    if score >= 90:
        rating = "A"
    elif score >= 75:
        rating = "B"
    elif score >= 55:
        rating = "C"
    else:
        rating = "D"
    dealer["risk_score"] = score
    dealer["risk_rating"] = rating
    dealer["audit_frequency_days"] = spec.AUDIT_FREQUENCY_BY_RATING[rating]
    anchor = risk_anchor(dealer)
    if anchor is None:
        dealer["next_audit_due_at"] = None
    else:
        dealer["next_audit_due_at"] = db.fmt_instant(
            db.add_days(db.parse_instant(anchor), dealer["audit_frequency_days"])
        )
    return dealer


# --------------------------------------------------------------------------
# The suspension cascade -- shared by all three routes into SUSPENDED
# --------------------------------------------------------------------------


def suspend_line(line, dealer, reason_code):
    """ACTIVE -> SUSPENDED, voiding REQUESTED advances and suspending the dealer."""
    if line is None or line["status"] != "ACTIVE":
        return False
    line["status"] = "SUSPENDED"
    line["suspension_reason_code"] = reason_code
    db.touch(line)
    advances = [
        a
        for a in db.rows("funding_advances")
        if a["credit_line_id"] == line["id"] and a["status"] == "REQUESTED"
    ]
    for advance in advances:
        advance["status"] = "VOIDED"
        advance["reason_code"] = "LINE_SUSPENDED"
        db.touch(advance)
        unit = db.get("inventory_units", advance["unit_id"])
        if unit is not None and unit["funding_status"] == "PENDING_FUNDING":
            unit["funding_status"] = "REGISTERED"
            db.touch(unit)
    if dealer is not None and dealer["status"] == "ACTIVE":
        dealer["status"] = "SUSPENDED"
        db.touch(dealer)
    return True


# --------------------------------------------------------------------------
# Closing cascade helpers shared by the remittance waterfall
# --------------------------------------------------------------------------


def settle_unit_after_payment(unit):
    """PRD 3.7: paid-off promotion and delinquency recovery for a touched unit."""
    obligations = unit_obligations(unit["id"])
    if int(unit["outstanding_principal_cents"]) == 0 and obligations and all(
        o["status"] in ("PAID", "CANCELLED") for o in obligations
    ):
        if unit["funding_status"] in ("FLOORED", "DELINQUENT_CURTAILMENT"):
            unit["funding_status"] = "PAID_OFF"
            db.touch(unit)
            return
    if unit["funding_status"] == "DELINQUENT_CURTAILMENT" and not [
        o for o in obligations if o["status"] == "DELINQUENT"
    ]:
        unit["funding_status"] = "FLOORED"
        db.touch(unit)
