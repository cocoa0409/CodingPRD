"""Constants, calculations and cascades for the food recall effectiveness API."""
from decimal import Decimal

from core import (add_days, ceil_div, db, err, iso, mark_dirty, money, new_row,
                  now, now_iso, parse_iso, pct, rhu, upd)

# ---------------------------------------------------------------- enums
AGENCIES = {"FDA", "USDA"}
INITIATION_TYPES = {"FIRM_INITIATED", "AGENCY_REQUESTED", "MANDATED"}
HAZARD_CLASSES = {"CLASS_I", "CLASS_II", "CLASS_III"}
RECALL_STATUSES = ["DRAFT", "CLASSIFIED", "NOTIFICATION_IN_PROGRESS", "RETRIEVAL_ACCOUNTING",
                   "EFFECTIVENESS_REVIEW", "TERMINATION_REQUESTED", "TERMINATED"]
PROBABILITIES = {"HIGH", "MEDIUM", "LOW", "REMOTE"}
EVIDENCE_STRENGTHS = {"CONFIRMED", "PROBABLE", "SUSPECTED"}
CONSIGNEE_TYPES = {"DISTRIBUTOR", "RETAILER", "RESTAURANT", "INSTITUTION"}
NOTIFICATION_METHODS = {"EMAIL", "PHONE", "CERTIFIED_MAIL"}
WARNING_TYPES = {"PRESS_RELEASE", "PUBLIC_WARNING", "SOCIAL_MEDIA_ONLY"}
DISPOSITION_METHODS = {"DESTROY", "REWORK", "RELABEL", "RETURN_TO_FIRM"}
REPORT_KINDS = {"PERIODIC", "INTERIM", "FINAL_EFFECTIVENESS"}
COST_CATEGORIES = {"NOTIFICATION", "LOGISTICS", "DESTRUCTION", "LEGAL", "PRODUCT_VALUE", "LAB_TESTING"}
ROOT_CAUSE_CODES = {"SUPPLIER_INGREDIENT", "SANITATION", "PROCESS_DEVIATION", "LABELING",
                    "PACKAGING", "CROSS_CONTACT", "UNKNOWN"}
RECONCILE_OUTCOMES = {"CONFIRM", "DISPUTE", "CORRECT", "VOID"}

# ---------------------------------------------------------------- constants
SEVERITY_POINTS = {1: 12, 2: 24, 3: 40, 4: 58}
PROBABILITY_MULTIPLIER = {"HIGH": "1.30", "MEDIUM": "1.00", "LOW": "0.70", "REMOTE": "0.40"}
EXPOSURE_DIVISOR = 25000
EXPOSURE_CAP = 12
VULNERABLE_BONUS = 9
EVIDENCE_SCALE = {"CONFIRMED": "1.00", "PROBABLE": "0.80", "SUSPECTED": "0.55"}
CLASS_I_THRESHOLD = Decimal("70.00")
CLASS_II_THRESHOLD = Decimal("35.00")

LEVEL_PCT = {"A": "1.00", "B": "0.50", "C": "0.10", "D": "0.02"}
SAMPLE_TIER_SCOPE = {"A": 3, "B": 2, "C": 2, "D": 1}
CONSIGNEE_MAX_TIER = 3

EFFECTIVENESS_TARGET_PCT = 95.00
TERMINATION_MIN_EFFECTIVENESS_PCT = 90.00
EFFECTIVENESS_WATCH_PCT = 60.00

OVERHEAD_RATE = {"NOTIFICATION": "0.115", "LOGISTICS": "0.085", "DESTRUCTION": "0.145",
                 "LEGAL": "0.000", "PRODUCT_VALUE": "0.055", "LAB_TESTING": "0.225"}
INSURABLE_CATEGORIES = ["NOTIFICATION", "LOGISTICS", "DESTRUCTION", "PRODUCT_VALUE"]

SUBLIMIT_CENTS = {"NOTIFICATION": 2000000, "LOGISTICS": 5000000,
                  "DESTRUCTION": 3000000, "PRODUCT_VALUE": 25000000}
COINS_TIER_HIGH_CENTS = 50000000
COINS_TIER_MID_CENTS = 10000000
HANDLING_FEE_RATE = "0.030"

CADENCE_DAYS = {"CLASS_I": 7, "CLASS_II": 14, "CLASS_III": 30}
ESCALATED_CADENCE_DAYS = 3
FINAL_REVIEW_REPORT_DAYS = 3
REPORT_REJECT_EXTENSION_DAYS = 2

DELINQUENT_OVERDUE_COUNT = 3
ESCALATED_OVERDUE_COUNT = 1

RESPONSE_WINDOW_HOURS = {"CLASS_I": 24, "CLASS_II": 72, "CLASS_III": 168}
METHOD_BUFFER_HOURS = {"EMAIL": 24, "PHONE": 12, "CERTIFIED_MAIL": 72}

RESPONSE_PRECEDENCE = {"ACKNOWLEDGED": 4, "REFUSED": 3, "NO_RESPONSE": 2, "AWAITING": 1}


# ---------------------------------------------------------------- collection lookups
def recall_children(collection, recall_id):
    return [r for r in collection.values() if r.get("recall_id") == recall_id]


def consignee_children(collection, consignee_id):
    return [r for r in collection.values() if r.get("consignee_id") == consignee_id]


# ---------------------------------------------------------------- hazard scoring
def hazard_score_and_class(evaluation, variant):
    base = Decimal(SEVERITY_POINTS[int(evaluation["severity_tier"])]) * \
        Decimal(PROBABILITY_MULTIPLIER[evaluation["probability_of_adverse_health"]])
    exposure_factor = min(EXPOSURE_CAP, ceil_div(int(evaluation["exposure_population"]), EXPOSURE_DIVISOR))
    vuln_bonus = VULNERABLE_BONUS if evaluation.get("vulnerable_population") else 0
    if variant == "PRELIMINARY":
        scale = Decimal("1.00")
    else:
        scale = Decimal(EVIDENCE_SCALE[evaluation["evidence_strength"]])
    raw = (base + Decimal(exposure_factor) + Decimal(vuln_bonus)) * scale
    score = rhu(raw, 2)
    if score >= CLASS_I_THRESHOLD:
        recommended = "CLASS_I"
    elif score >= CLASS_II_THRESHOLD:
        recommended = "CLASS_II"
    else:
        recommended = "CLASS_III"
    return float(score), recommended


def apply_hazard_score(evaluation, variant):
    score, recommended = hazard_score_and_class(evaluation, variant)
    upd(evaluation, variant=variant, hazard_score=score, recommended_class=recommended)


# ---------------------------------------------------------------- sampling scope
def compute_scope(recall):
    consignees = recall_children(db.consignees, recall["id"])
    hazard_class = recall.get("hazard_class")
    if hazard_class == "CLASS_I":
        level = "A"
    elif hazard_class == "CLASS_II":
        level = "B" if any(int(c.get("tier") or 1) >= 2 for c in consignees) else "C"
    elif hazard_class == "CLASS_III":
        level = "D"
    else:
        level = None
    if level is None:
        return {"effectiveness_check_level": None, "sample_tier_scope": 0,
                "eligible_consignee_count": 0, "required_sample_size": 0}
    scope = SAMPLE_TIER_SCOPE[level]
    eligible = [c for c in consignees if int(c.get("tier") or 1) <= scope]
    count = len(eligible)
    if count == 0:
        required = 0
    else:
        exact = Decimal(count) * Decimal(LEVEL_PCT[level])
        required = max(1, ceil_div(exact.as_integer_ratio()[0], exact.as_integer_ratio()[1]))
    return {"effectiveness_check_level": level, "sample_tier_scope": scope,
            "eligible_consignee_count": count, "required_sample_size": required}


# ---------------------------------------------------------------- effectiveness
def consignee_responded(consignee):
    for n in consignee_children(db.notifications, consignee["id"]):
        if n.get("delivery_state") == "DELIVERED" and n.get("response_state") in ("ACKNOWLEDGED", "REFUSED"):
            return True
    return False


def compute_metrics(recall):
    """Pure recomputation of every derived aggregate on the recall (no posture, no cadence)."""
    values = compute_scope(recall)
    scope = values["sample_tier_scope"]
    required = values["required_sample_size"]

    consignees = recall_children(db.consignees, recall["id"])
    responded = 0
    for c in consignees:
        if int(c.get("tier") or 1) <= scope and consignee_responded(c):
            responded += 1
    values["responded_count"] = responded

    if required == 0:
        contact = 100.00
    else:
        contact = pct(Decimal(min(responded, required)) * 100 / Decimal(required))
    values["contact_effectiveness_pct"] = contact

    records = recall_children(db.distribution_records, recall["id"])
    shipped = sum(int(r.get("effective_quantity") or 0) for r in records
                  if r.get("status") in ("CONFIRMED", "CORRECTED"))
    receipts = recall_children(db.retrieval_receipts, recall["id"])
    accounted = sum(int(r.get("accounted_units") or 0) for r in receipts if r.get("status") == "VERIFIED")
    values["total_shipped_units"] = sum(int(r.get("effective_quantity") or 0) for r in records)
    values["accounted_units"] = accounted
    if shipped == 0:
        quantity = 0.00
    else:
        quantity = pct(Decimal(min(accounted, shipped)) * 100 / Decimal(shipped))
    values["quantity_effectiveness_pct"] = quantity

    official = contact if recall.get("agency") == "FDA" else quantity
    values["official_effectiveness_pct"] = official
    values["_official_basis"] = "CONTACT" if recall.get("agency") == "FDA" else "QUANTITY"
    values["_shipped_units"] = shipped

    entries = recall_children(db.cost_entries, recall["id"])
    accepted = [e for e in entries if e.get("status") == "ACCEPTED"]
    values["total_loaded_cost_cents"] = sum(int(e.get("line_loaded_cost_cents") or 0) for e in accepted)
    values["insurable_loaded_cost_cents"] = sum(int(e.get("line_loaded_cost_cents") or 0)
                                                for e in accepted if e.get("insurable"))
    return values


def apply_metrics(recall):
    values = {k: v for k, v in compute_metrics(recall).items() if not k.startswith("_")}
    upd(recall, **values)


def refresh_sample_flags(recall):
    scope = int(recall.get("sample_tier_scope") or 0)
    for c in recall_children(db.consignees, recall["id"]):
        upd(c, in_effectiveness_sample=(int(c.get("tier") or 1) <= scope))


def refresh_consignee_response_state(consignee):
    best = "AWAITING"
    for n in consignee_children(db.notifications, consignee["id"]):
        state = n.get("response_state") or "AWAITING"
        if RESPONSE_PRECEDENCE.get(state, 0) > RESPONSE_PRECEDENCE[best]:
            best = state
    upd(consignee, response_state=best)


def refresh_notification_counts(notification):
    upd(notification, counts_toward_effectiveness=(
        notification.get("delivery_state") == "DELIVERED"
        and notification.get("response_state") in ("ACKNOWLEDGED", "REFUSED")))


# ---------------------------------------------------------------- posture / cadence
def compliance_posture(recall):
    overdue = int(recall.get("overdue_report_count") or 0)
    if overdue >= DELINQUENT_OVERDUE_COUNT:
        return "DELINQUENT"
    if overdue >= ESCALATED_OVERDUE_COUNT:
        return "ESCALATED"
    if float(recall.get("official_effectiveness_pct") or 0) < EFFECTIVENESS_WATCH_PCT and \
            recall.get("status") in ("RETRIEVAL_ACCOUNTING", "EFFECTIVENESS_REVIEW", "TERMINATION_REQUESTED"):
        return "WATCH"
    return "COMPLIANT"


def apply_compliance_posture(recall):
    upd(recall, compliance_flag=compliance_posture(recall))


def cadence_days(recall):
    if recall.get("compliance_flag") in ("ESCALATED", "DELINQUENT"):
        return ESCALATED_CADENCE_DAYS
    hazard_class = recall.get("hazard_class")
    if hazard_class in CADENCE_DAYS:
        return CADENCE_DAYS[hazard_class]
    return int(recall.get("report_cadence_days") or 0)


def apply_cadence(recall):
    upd(recall, report_cadence_days=cadence_days(recall))


# ---------------------------------------------------------------- status reports
def next_period_index(recall_id):
    reports = recall_children(db.status_reports, recall_id)
    if not reports:
        return 1
    return max(int(r.get("period_index") or 0) for r in reports) + 1


def mint_report(recall, report_kind, days):
    start = now()
    end = add_days(start, days)
    start_s, end_s = iso(start), iso(end)
    return new_row(db.status_reports,
                   recall_id=recall["id"],
                   period_index=next_period_index(recall["id"]),
                   report_kind=report_kind,
                   period_start=start_s,
                   period_end=end_s,
                   due_at=end_s,
                   status="PENDING",
                   submitted_at=None,
                   narrative=None,
                   reported_effectiveness_pct=0,
                   reject_count=0,
                   adjudication_note=None)


def flip_overdue_reports(recall):
    """Every PENDING report whose due_at <= clock_now flips to OVERDUE."""
    flipped = 0
    for report in sorted(recall_children(db.status_reports, recall["id"]),
                         key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0)):
        if report.get("status") != "PENDING":
            continue
        due = parse_iso(report.get("due_at"))
        if due is not None and due <= now():
            upd(report, status="OVERDUE")
            flipped += 1
            upd(recall, overdue_report_count=int(recall.get("overdue_report_count") or 0) + 1)
            apply_compliance_posture(recall)
    return flipped


# ---------------------------------------------------------------- auto transitions
def maybe_enter_retrieval(recall):
    if recall.get("status") != "NOTIFICATION_IN_PROGRESS":
        return False
    required = int(recall.get("required_sample_size") or 0)
    if required > 0 and int(recall.get("responded_count") or 0) >= required:
        upd(recall, status="RETRIEVAL_ACCOUNTING")
        return True
    return False


def maybe_enter_effectiveness_review(recall):
    if recall.get("status") != "RETRIEVAL_ACCOUNTING":
        return False
    if float(recall.get("official_effectiveness_pct") or 0) < EFFECTIVENESS_TARGET_PCT:
        return False
    upd(recall, status="EFFECTIVENESS_REVIEW")
    # Cascade B hop 3
    for consignee in recall_children(db.consignees, recall["id"]):
        if consignee.get("response_state") in ("AWAITING", "NO_RESPONSE"):
            upd(consignee, closed_without_response=True)
    mint_report(recall, "FINAL_EFFECTIVENESS", FINAL_REVIEW_REPORT_DAYS)
    return True


# ---------------------------------------------------------------- cost + insurance
def cost_line_values(category, amount_cents):
    rate = OVERHEAD_RATE[category]
    loaded = money(Decimal(amount_cents) * (Decimal("1") + Decimal(rate)))
    return {
        "insurable": category in INSURABLE_CATEGORIES,
        "overhead_rate": float(Decimal(rate)),
        "line_loaded_cost_cents": loaded,
    }


def insurance_settlement(recall, firm):
    # STEP 1
    claimed = int(recall.get("insurable_loaded_cost_cents") or 0)
    # STEP 2
    entries = [e for e in recall_children(db.cost_entries, recall["id"]) if e.get("status") == "ACCEPTED"]
    capped_total = 0
    for category in INSURABLE_CATEGORIES:
        subtotal = sum(int(e.get("line_loaded_cost_cents") or 0)
                       for e in entries if e.get("category") == category)
        capped_total += min(subtotal, SUBLIMIT_CENTS[category])
    # STEP 3
    if capped_total >= COINS_TIER_HIGH_CENTS:
        rate = Decimal("0.90")
    elif capped_total >= COINS_TIER_MID_CENTS:
        rate = Decimal("0.85")
    else:
        rate = Decimal("0.80")
    # STEP 4
    deductible = int(firm.get("policy_deductible_cents") or 0)
    payable = money(Decimal(max(0, capped_total - deductible)) * rate)
    # STEP 5
    remaining = int(firm.get("policy_aggregate_cents") or 0) - int(firm.get("policy_paid_to_date_cents") or 0)
    payable = min(payable, remaining)
    # STEP 6 / 7
    fee = money(Decimal(payable) * Decimal(HANDLING_FEE_RATE))
    return {
        "claimed_cents": claimed,
        "capped_total_cents": capped_total,
        "coinsurance_rate": float(rate),
        "settlement_payable_cents": payable,
        "handling_fee_cents": fee,
        "total_claim_value_cents": payable + fee,
    }


def refresh_firm_paid_to_date(firm):
    total = 0
    for claim in db.insurance_claims.values():
        recall = db.recalls.get(claim.get("recall_id"))
        if recall is None or recall.get("firm_id") != firm["id"]:
            continue
        if claim.get("status") in ("PARTIALLY_PAID", "PAID"):
            total += int(claim.get("paid_cents") or 0)
    upd(firm, policy_paid_to_date_cents=total)


def refresh_firm_open_recalls(firm):
    count = sum(1 for r in db.recalls.values()
                if r.get("firm_id") == firm["id"] and r.get("status") != "TERMINATED")
    upd(firm, open_recall_count=count)


# ---------------------------------------------------------------- checkpoint
def run_checkpoint(recall):
    # 1. overdue flips
    flip_overdue_reports(recall)

    # 2. notification aging
    hazard_class = recall.get("hazard_class")
    window = RESPONSE_WINDOW_HOURS.get(hazard_class)
    if window is not None:
        notes = sorted(recall_children(db.notifications, recall["id"]),
                       key=lambda n: (n.get("sent_at") or "", n.get("created_at") or "", n.get("_seq") or 0))
        for note in notes:
            if note.get("delivery_state") != "DELIVERED" or note.get("response_state") != "AWAITING":
                continue
            recorded = parse_iso(note.get("delivery_recorded_at"))
            if recorded is None:
                continue
            elapsed = (now() - recorded).total_seconds() / 3600.0
            if elapsed >= window:
                upd(note, response_state="NO_RESPONSE", response_recorded_at=now_iso())
                refresh_notification_counts(note)
                consignee = db.consignees.get(note.get("consignee_id"))
                if consignee is not None:
                    upd(consignee, escalation_level=int(consignee.get("escalation_level") or 0) + 1)
                    refresh_consignee_response_state(consignee)

    # 3. posture, cadence, effectiveness
    apply_metrics(recall)
    apply_compliance_posture(recall)
    apply_cadence(recall)

    # 4. auto transitions
    maybe_enter_retrieval(recall)
    maybe_enter_effectiveness_review(recall)

    # 5. mint next periodic report
    reports = recall_children(db.status_reports, recall["id"])
    if recall.get("status") not in ("DRAFT", "TERMINATED") and reports and \
            not any(r.get("status") == "PENDING" for r in reports):
        mint_report(recall, "PERIODIC", int(recall.get("report_cadence_days") or 0))
