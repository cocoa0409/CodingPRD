"""Derived reads, calculation rules and cascade helpers (SCAFFOLD 1.3)."""

import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

import store

# --- constants -------------------------------------------------------------
ANALYSIS_MAX_RETURNS = 2

FEDERAL_INDIRECT_CAP_PCT = Decimal("26.0")
INDUSTRY_INDIRECT_CAP_PCT = Decimal("32.0")
INDUSTRY_SMALL_STUDY_SURCHARGE_PCT = Decimal("3.0")
INDUSTRY_TIER_THRESHOLD_CENTS = 500000

INVOICE_MAX_LINES = 25
INVOICE_MAX_GROSS_CENTS = 2000000
INVOICE_VOLUME_CREDIT_THRESHOLD_CENTS = 1000000
INVOICE_VOLUME_CREDIT_PCT = Decimal("2.0")

AGING_CURRENT_MAX_DAYS = 30
AGING_31_60_MAX_DAYS = 60
AGING_61_90_MAX_DAYS = 90

RESEARCH_VISIT_DAILY_CAPACITY = 2

BILLABLE_BY_CLASSIFICATION = {
    "ROUTINE_CARE": "PAYER",
    "RESEARCH_PAID": "SPONSOR",
    "PROMOTIONAL": "NONE",
}

DECISION_TARGET = {
    "CLEAR_TO_PAYER": "PAYER",
    "HOLD_FOR_SPONSOR": "SPONSOR",
    "NO_CHARGE_PROMOTIONAL": "NONE",
}


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def indirect_of(amount_cents, rate_pct):
    rate = rate_pct if rate_pct is not None else Decimal(0)
    return round_half_up(Decimal(amount_cents) * Decimal(rate) / Decimal(100))


# --- collection scans ------------------------------------------------------
def analyses_of(study_id):
    return store.by_created([a for a in store.analyses.values() if a["study_id"] == study_id])


def items_of(analysis_id):
    return store.by_created(
        [i for i in store.coverage_items.values() if i["coverage_analysis_id"] == analysis_id]
    )


def calendars_of(study_id):
    return store.by_created([c for c in store.calendars.values() if c["study_id"] == study_id])


def visits_of_calendar(calendar_id):
    return sorted(
        [v for v in store.calendar_visits.values() if v["study_calendar_id"] == calendar_id],
        key=lambda v: (v["sequence_index"], v["_seq"]),
    )


def routes_of_visit(calendar_visit_id):
    return store.by_created(
        [r for r in store.routes.values() if r["calendar_visit_id"] == calendar_visit_id]
    )


def routes_of_calendar(calendar_id):
    visit_ids = {v["id"] for v in store.calendar_visits.values()
                 if v["study_calendar_id"] == calendar_id}
    return store.by_created(
        [r for r in store.routes.values() if r["calendar_visit_id"] in visit_ids]
    )


def subjects_of(study_id):
    return store.by_created([s for s in store.subjects.values() if s["study_id"] == study_id])


def subject_visits_of_subject(subject_id):
    return store.by_created(
        [v for v in store.subject_visits.values() if v["study_subject_id"] == subject_id]
    )


def subject_visits_of_study(study_id):
    subject_ids = {s["id"] for s in store.subjects.values() if s["study_id"] == study_id}
    return store.by_created(
        [v for v in store.subject_visits.values() if v["study_subject_id"] in subject_ids]
    )


def charges_of(study_id):
    return store.by_created([c for c in store.charges.values() if c["study_id"] == study_id])


def invoices_of(study_id):
    return sorted(
        [i for i in store.invoices.values() if i["study_id"] == study_id],
        key=lambda i: i["sequence_number"],
    )


def findings_of(study_id):
    return store.by_created([f for f in store.findings.values() if f["study_id"] == study_id])


def amendments_of(study_id):
    return sorted(
        [a for a in store.amendments.values() if a["study_id"] == study_id],
        key=lambda a: a["amendment_number"],
    )


# --- coverage analysis counters -------------------------------------------
def analysis_counters(analysis_id):
    items = items_of(analysis_id)
    return {
        "item_count": len(items),
        "routine_care_item_count": sum(1 for i in items if i["classification"] == "ROUTINE_CARE"),
        "research_paid_item_count": sum(1 for i in items if i["classification"] == "RESEARCH_PAID"),
        "promotional_item_count": sum(1 for i in items if i["classification"] == "PROMOTIONAL"),
        "qct_conditional_item_count": sum(
            1 for i in items
            if i["classification"] == "ROUTINE_CARE"
            and i["medicare_coverage_basis"] == "QCT_CONDITIONAL"
        ),
    }


# --- calendar counters ----------------------------------------------------
def visit_expected_total(calendar_visit_id):
    return sum(r["expected_amount_cents"] for r in routes_of_visit(calendar_visit_id))


def calendar_counters(calendar):
    visits = visits_of_calendar(calendar["id"])
    cal_routes = routes_of_calendar(calendar["id"])
    routed_item_ids = {r["coverage_item_id"] for r in cal_routes}
    unrouted = 0
    # PRD 3.4: a generation "opens at `status` `DRAFT` with `visit_count`,
    # `routed_item_count`, and `unrouted_per_patient_item_count` all at zero";
    # the unrouted counter is only refreshed once the generation has content.
    # A route cannot exist without a visit, so "has at least one visit" is
    # exactly the condition under which the counter has ever been refreshed.
    if visits:
        for item in items_of(calendar["source_analysis_id"]):
            if item["budget_category"] != "PER_PATIENT":
                continue
            if item["billable_to"] not in ("PAYER", "SPONSOR"):
                continue
            if item["id"] not in routed_item_ids:
                unrouted += 1
    return {
        "visit_count": len(visits),
        "routed_item_count": len(routed_item_ids),
        "unrouted_per_patient_item_count": unrouted,
    }


# --- study posture and ledger ---------------------------------------------
def open_finding_count(study_id):
    return sum(1 for f in store.findings.values()
               if f["study_id"] == study_id and f["status"] in ("OPEN", "RESPONDED"))


def rebuild_required_calendar_count(study_id):
    return sum(1 for c in store.calendars.values()
               if c["study_id"] == study_id and c["status"] == "REBUILD_REQUIRED")


def billing_hold_posture(study):
    """calculations.study_billing_hold_posture - clause order is normative."""
    if open_finding_count(study["id"]) >= 1:
        return "ALL_BLOCKED"
    if rebuild_required_calendar_count(study["id"]) >= 1:
        return "ALL_BLOCKED"
    if study["qct_determination"] in ("UNDETERMINED", "NON_QUALIFYING"):
        return "PAYER_BLOCKED"
    return "OPEN"


def study_ledger(study):
    """calculations.study_ledger_rollup - pure aggregates over the study's own
    charges and invoices."""
    cs = charges_of(study["id"])
    invs = invoices_of(study["id"])
    return {
        "payer_billed_cents": sum(c["amount_cents"] for c in cs
                                  if c["billing_state"] == "BILLED_PAYER"),
        "payer_refunded_cents": sum(c["refunded_amount_cents"] for c in cs
                                    if c["billing_state"] == "REFUNDED"),
        "sponsor_unbilled_cents": sum(c["amount_cents"] for c in cs
                                      if c["routing_state"] == "ROUTED_SPONSOR"
                                      and c["billing_state"] == "UNBILLED"),
        "sponsor_receivable_cents": sum(c["amount_cents"] for c in cs
                                        if c["billing_state"] == "INVOICED_SPONSOR"),
        "sponsor_collected_cents": sum(i["amount_paid_cents"] for i in invs
                                       if i["status"] == "PAID"),
        "sponsor_written_off_cents": sum(i["net_total_cents"] - i["amount_paid_cents"]
                                         for i in invs
                                         if i["status"] == "PAID" and i["short_paid"]),
        "improper_payer_exposure_cents": sum(c["amount_cents"] for c in cs
                                             if improper_flag(c)),
        "delinquent_sponsor_cents": sum(c["amount_cents"] for c in cs
                                        if c["billing_state"] == "UNBILLED"
                                        and c["aging_bucket"] == "DELINQUENT_90_PLUS"),
    }


# --- charge_routing_expectation -------------------------------------------
def _candidates(study_id, statuses):
    return [a for a in store.analyses.values()
            if a["study_id"] == study_id and a["status"] in statuses]


def _latest_approved(candidates):
    if not candidates:
        return None
    return sorted(candidates,
                  key=lambda a: (a["approved_at"], a["created_at"], a["_seq"]),
                  reverse=True)[0]


def effective_current(study_id):
    """The audit view: the study's single APPROVED analysis."""
    cands = [a for a in _candidates(study_id, ("APPROVED",)) if a["approved_at"] is not None]
    return _latest_approved(cands)


def effective_as_of(study_id, service_date):
    """The operational view: latest analysis approved at or before the very end
    of service_date."""
    cutoff = _dt.datetime.fromisoformat(service_date).replace(
        hour=23, minute=59, second=59, microsecond=999000, tzinfo=_dt.timezone.utc)
    cands = [a for a in _candidates(study_id, ("APPROVED", "SUPERSEDED"))
             if a["approved_at"] is not None and a["approved_at"] <= cutoff]
    return _latest_approved(cands)


def match_item(analysis, charge_code):
    if analysis is None:
        return None
    matches = [i for i in items_of(analysis["id"]) if i["item_code"] == charge_code]
    if not matches:
        return None
    return matches[0]


def expected_routing_target(charge):
    """Persisted-as-derived: the current_effective variant."""
    analysis = effective_current(charge["study_id"])
    item = match_item(analysis, charge["charge_code"])
    if item is None:
        return "UNDETERMINED"
    return item["billable_to"]


def improper_flag(charge):
    return (charge["billing_state"] == "BILLED_PAYER"
            and expected_routing_target(charge) != "PAYER")


def new_charge(study_id, charge_code, service_date, amount_cents, source, **overrides):
    """Create and register a Charge row with the declared field defaults."""
    rec = store.base_record()
    rec.update({
        "study_id": study_id,
        "subject_visit_id": None,
        "coverage_item_id": None,
        "sponsor_invoice_id": None,
        "replaces_charge_id": None,
        "charge_code": charge_code,
        "service_date": service_date,
        "amount_cents": amount_cents,
        "source": source,
        "routing_state": "UNROUTED",
        "billing_state": "UNBILLED",
        "suggested_routing_target": None,
        "hold_reason": "NONE",
        "hold_applied_at": None,
        "unbilled_since": store.now(),
        "aging_days": 0,
        "aging_bucket": "CURRENT",
        "posted_by_user_id": None,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "override_justification": None,
        "refunded_amount_cents": 0,
    })
    rec.update(overrides)
    store.charges[rec["id"]] = rec
    return rec


# --- visit_route_expected_amount -----------------------------------------
def route_expected_amount(item, routing_target, occurrences):
    if routing_target == "PAYER":
        unit = item["charge_master_unit_cents"]
    elif routing_target == "SPONSOR":
        unit = item["negotiated_unit_cents"]
    else:
        unit = 0
    return occurrences * item["units_per_occurrence"] * unit


# --- budget calculations -------------------------------------------------
def budget_subtotals(study, source_analysis_id, basis):
    items = items_of(source_analysis_id)
    by_id = {i["id"]: i for i in items}

    if basis == "COVERAGE_DRIVEN":
        per_patient = sum(
            i["units_per_occurrence"] * i["expected_occurrences"] * i["negotiated_unit_cents"]
            for i in items
            if i["billable_to"] == "SPONSOR" and i["budget_category"] == "PER_PATIENT"
        )
    else:
        per_patient = 0
        calendar = published_calendar_for_analysis(study["id"], source_analysis_id)
        if calendar is not None:
            for route in routes_of_calendar(calendar["id"]):
                item = by_id.get(route["coverage_item_id"])
                if item is None:
                    continue
                if route["routing_target"] != "SPONSOR":
                    continue
                if item["budget_category"] != "PER_PATIENT":
                    continue
                per_patient += (route["occurrences"] * item["units_per_occurrence"]
                                * item["negotiated_unit_cents"])

    invoiceable = sum(
        i["units_per_occurrence"] * i["expected_occurrences"] * i["negotiated_unit_cents"]
        for i in items
        if i["billable_to"] == "SPONSOR" and i["budget_category"] == "INVOICEABLE"
    )
    return per_patient, invoiceable


def published_calendar_for_analysis(study_id, source_analysis_id):
    for cal in calendars_of(study_id):
        if cal["source_analysis_id"] == source_analysis_id and cal["status"] == "PUBLISHED":
            return cal
    return None


def effective_indirect_rate(study, requested_rate, per_patient_subtotal_cents):
    """calculations.study_effective_indirect_rate."""
    funding = study["funding_source"]
    if funding == "FEDERALLY_FUNDED":
        return min(requested_rate, FEDERAL_INDIRECT_CAP_PCT)
    if funding == "INDUSTRY_SPONSORED":
        if per_patient_subtotal_cents >= INDUSTRY_TIER_THRESHOLD_CENTS:
            return min(requested_rate, INDUSTRY_INDIRECT_CAP_PCT)
        return min(requested_rate + INDUSTRY_SMALL_STUDY_SURCHARGE_PCT,
                   INDUSTRY_INDIRECT_CAP_PCT)
    return Decimal("0.0")


def sum_then_round_total(subtotal_cents, rate_pct):
    """Budget order: sum then round (one rounding for the whole subtotal)."""
    return subtotal_cents + round_half_up(
        Decimal(subtotal_cents) * Decimal(rate_pct) / Decimal(100))


# --- invoice calculations ------------------------------------------------
def select_invoice_lines(study, period_end_date, invoice_id=None):
    """calculations.sponsor_invoice_line_selection - strict waterfall."""
    rate = study["effective_indirect_rate_pct"]
    candidates = [
        c for c in store.charges.values()
        if c["study_id"] == study["id"]
        and c["routing_state"] == "ROUTED_SPONSOR"
        and c["billing_state"] == "UNBILLED"
        and c["sponsor_invoice_id"] is None
        and c["hold_reason"] == "NONE"
        and c["service_date"] <= period_end_date
    ]
    candidates.sort(key=lambda c: (c["service_date"], c["created_at"], c["_seq"]))

    selected = []
    running_subtotal = 0
    running_indirect = 0
    for c in candidates:
        line_indirect = indirect_of(c["amount_cents"], rate)
        if len(selected) + 1 > INVOICE_MAX_LINES:
            break
        if (running_subtotal + c["amount_cents"] + running_indirect + line_indirect
                > INVOICE_MAX_GROSS_CENTS):
            break
        selected.append(c)
        running_subtotal += c["amount_cents"]
        running_indirect += line_indirect
    return selected, running_subtotal, running_indirect


def invoice_money(subtotal_cents, indirect_cents):
    """sponsor_invoice_indirect + sponsor_invoice_net_total (pinned steps)."""
    gross = subtotal_cents + indirect_cents
    credit_pct = (INVOICE_VOLUME_CREDIT_PCT
                  if gross >= INVOICE_VOLUME_CREDIT_THRESHOLD_CENTS
                  else Decimal("0.0"))
    credit = round_half_up(Decimal(gross) * credit_pct / Decimal(100))
    return {
        "subtotal_cents": subtotal_cents,
        "indirect_cents": indirect_cents,
        "gross_total_cents": gross,
        "volume_credit_cents": credit,
        "net_total_cents": gross - credit,
    }


# --- aging ---------------------------------------------------------------
def aging_bucket_for(days):
    if days <= AGING_CURRENT_MAX_DAYS:
        return "CURRENT"
    if days <= AGING_31_60_MAX_DAYS:
        return "AGING_31_60"
    if days <= AGING_61_90_MAX_DAYS:
        return "AGING_61_90"
    return "DELINQUENT_90_PLUS"
