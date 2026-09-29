"""Calculations, aggregates and the shared cascade helpers (scaffold Table 1.3)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from events import append_event


def round_half_up(numerator, denominator=store.MILLICENTS_PER_CENT):
    """Integral cents, rounded half away from zero, evaluated on one line alone."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ lookups
def facility_of(req):
    return store.facilities.get(req["facility_id"])


def rule_of_facility(fac):
    return store.state_fee_rules.get(fac["state_fee_rule_id"]) if fac else None


def rule_of_request(req):
    return rule_of_facility(facility_of(req))


def authorization_of(req):
    if not req.get("authorization_id"):
        return None
    return store.authorizations.get(req["authorization_id"])


def segments_of(request_id):
    rows = [s for s in store.segments.values() if s["request_id"] == request_id]
    return store.ordered(rows)


def invoices_of(request_id):
    rows = [i for i in store.invoices.values() if i["request_id"] == request_id]
    return store.ordered(rows)


def deliveries_of(request_id):
    rows = [d for d in store.deliveries.values() if d["request_id"] == request_id]
    return store.ordered(rows)


def denials_of(request_id):
    rows = [d for d in store.denials.values() if d["request_id"] == request_id]
    return store.ordered(rows)


def requests_of_facility(facility_id):
    rows = [r for r in store.requests.values() if r["facility_id"] == facility_id]
    return store.ordered(rows)


# ------------------------------------------------------------------ page ledger
def refresh_page_ledger(req):
    """request_page_ledger: both variants over the RETRIEVED segments."""
    retrieved = [s for s in segments_of(req["id"]) if s["retrieval_status"] == "RETRIEVED"]
    releasable = [
        s for s in retrieved
        if s["sensitivity_status"] in ("NOT_SENSITIVE", "AUTHORIZED_INCLUDE")
    ]
    req["page_count_total"] = sum(s["page_count"] for s in retrieved)
    req["billable_page_count"] = sum(
        s["page_count"] - (s["redacted_page_count"] if s["redaction_status"] == "APPROVED" else 0)
        for s in releasable
    )
    req["withheld_page_count"] = sum(
        s["page_count"] for s in retrieved if s["sensitivity_status"] == "WITHHELD"
    )
    req["redacted_page_count_total"] = sum(
        s["redacted_page_count"] for s in releasable if s["redaction_status"] == "APPROVED"
    )


# ------------------------------------------------------------------ deadline
def compute_statutory_due_at(req):
    """statutory_due_at: four terms composed in a pinned order."""
    rule = rule_of_request(req)
    if rule is None:
        return req.get("statutory_due_at")
    received_at = store.parse_dt(req["received_at"])

    # term 1 — which statutory window applies
    if req["access_basis"] == "PATIENT_RIGHT_OF_ACCESS":
        deadline_days = rule["patient_access_deadline_days"]
    else:
        deadline_days = rule["third_party_deadline_days"]

    # term 2 — the anchor, selected BEFORE any days are added
    anchor = received_at
    if req["access_basis"] == "THIRD_PARTY_AUTHORIZATION":
        auth = authorization_of(req)
        if auth is not None:
            signed_at = store.parse_dt(auth["signed_at"])
            if signed_at is not None and signed_at > anchor:
                anchor = signed_at

    # term 3 — the statutory window in whole days
    base_due_at = anchor + timedelta(seconds=deadline_days * store.SECONDS_PER_DAY)

    # term 4 — the toll, capped BEFORE it is added
    toll_seconds = min(req.get("tolled_seconds", 0), store.MAX_TOLL_SECONDS)

    # term 5 — the single extension, added last
    extension_seconds = (
        rule["extension_days"] * store.SECONDS_PER_DAY if req.get("extension_applied") else 0
    )

    return store.fmt(base_due_at + timedelta(seconds=toll_seconds + extension_seconds))


def refresh_statutory_due_at(req):
    req["statutory_due_at"] = compute_statutory_due_at(req)


# ------------------------------------------------------------------ turnaround
def turnaround(req, completion_at=None):
    """Both lateness measures over one interval; writes nothing."""
    rule = rule_of_request(req)
    per_day = rule["penalty_per_day_cents"] if rule else 0
    cap = rule["penalty_cap_cents"] if rule else 0

    due_at = store.parse_dt(req.get("statutory_due_at"))
    if completion_at is not None:
        effective = completion_at
    elif req.get("released_at"):
        effective = store.parse_dt(req["released_at"])
    elif req.get("closed_at"):
        effective = store.parse_dt(req["closed_at"])
    else:
        effective = store.now()

    result = {
        "statutory_due_at": req.get("statutory_due_at"),
        "effective_completion_at": store.fmt(effective),
        "tolled_seconds": req.get("tolled_seconds", 0),
        "extension_applied": bool(req.get("extension_applied")),
        "breached": False,
        "days_late_strict": 0,
        "days_late_business": 0,
        "chargeable_days": 0,
        "penalty_exposure_cents": 0,
        "safe_harbor_penalty_cents": 0,
    }
    if due_at is None or effective <= due_at:
        return result

    result["breached"] = True

    overrun_micros = (effective - due_at) // timedelta(microseconds=1)
    micros_per_day = store.SECONDS_PER_DAY * 1000000
    days_strict = -(-overrun_micros // micros_per_day)   # ceiling division
    result["days_late_strict"] = days_strict
    result["penalty_exposure_cents"] = min(days_strict * per_day, cap)

    business = 0
    day = due_at.date() + timedelta(days=1)
    last = effective.date()
    while day <= last:
        if day.weekday() < 5:
            business += 1
        day += timedelta(days=1)
    chargeable = max(0, business - store.GRACE_BUSINESS_DAYS)
    result["days_late_business"] = business
    result["chargeable_days"] = chargeable
    result["safe_harbor_penalty_cents"] = min(chargeable * per_day, cap)
    return result


def refresh_penalties(req, actor_user_id, completion_at=None, emit=True):
    """Re-derive both measures, append the compliance events, refresh the facility."""
    measured = turnaround(req, completion_at)
    previous = req.get("penalty_exposure_cents", 0)
    req["penalty_exposure_cents"] = measured["penalty_exposure_cents"]
    req["safe_harbor_penalty_cents"] = measured["safe_harbor_penalty_cents"]
    delta = measured["penalty_exposure_cents"] - previous

    if emit:
        if measured["breached"] and not req.get("_breached_event"):
            req["_breached_event"] = True
            append_event(
                req["id"], "STATUTORY_DEADLINE_BREACHED", actor_user_id,
                days_late=measured["days_late_strict"], penalty_delta_cents=delta,
                detail="statutory_due_at=%s" % req.get("statutory_due_at"),
            )
        if delta > 0:
            append_event(
                req["id"], "PENALTY_ACCRUED", actor_user_id,
                days_late=measured["days_late_strict"], penalty_delta_cents=delta,
                detail="penalty_exposure_cents=%d" % req["penalty_exposure_cents"],
            )
    refresh_facility_penalty(req["facility_id"])
    return delta


# ------------------------------------------------------------------ facility ledgers
def refresh_facility_penalty(facility_id):
    fac = store.facilities.get(facility_id)
    if fac is None:
        return
    fac["penalty_exposure_cents"] = sum(
        r.get("penalty_exposure_cents", 0) for r in store.requests.values()
        if r["facility_id"] == facility_id
    )


def refresh_facility_money(facility_id):
    """facility_money_ledger: three mutually exclusive buckets, re-derived."""
    fac = store.facilities.get(facility_id)
    if fac is None:
        return
    receivable = 0
    collected = 0
    written_off = 0
    for inv in store.invoices.values():
        req = store.requests.get(inv["request_id"])
        if req is None or req["facility_id"] != facility_id:
            continue
        if inv["status"] == "ISSUED":
            receivable += inv["amount_due_cents"] - inv["paid_cents"]
        elif inv["status"] == "PAID":
            collected += inv["paid_cents"]
        elif inv["status"] == "WAIVED":
            written_off += inv["amount_due_cents"]
    fac["receivable_cents"] = receivable
    fac["collected_cents"] = collected
    fac["written_off_cents"] = written_off


# ------------------------------------------------------------------ pricing
def invoice_variant(req):
    if req["access_basis"] == "PATIENT_RIGHT_OF_ACCESS":
        return "PATIENT_ACCESS_COST_BASED"
    return "THIRD_PARTY_RETAIL"


def build_priced_lines(req, priced_pages):
    """invoice_line_build: the pinned line order for the request's variant.

    Returns a list of (line_type, quantity, unit_millicents) for the priced
    lines only; CAP_ADJUSTMENT and LATE_FEE_FORFEITURE are appended later.
    """
    fac = facility_of(req)
    rule = rule_of_facility(fac)
    fmt_ = req["delivery_format"]
    lines = []
    if invoice_variant(req) == "THIRD_PARTY_RETAIL":
        lines.append(("BASE_RETRIEVAL", 1, rule["base_retrieval_fee_cents"] * store.MILLICENTS_PER_CENT))
        tier1_qty = min(priced_pages, rule["tier1_page_limit"])
        if tier1_qty != 0:
            lines.append(("PER_PAGE_TIER1", tier1_qty, rule["tier1_per_page_millicents"]))
        tier2_qty = max(0, priced_pages - rule["tier1_page_limit"])
        if tier2_qty != 0:
            lines.append(("PER_PAGE_TIER2", tier2_qty, rule["tier2_per_page_millicents"]))
        surcharge = fac["legacy_retrieval_surcharge_cents"]
        has_legacy = any(
            s["source_system"] == "LEGACY_ARCHIVE" and s["retrieval_status"] == "RETRIEVED"
            for s in segments_of(req["id"])
        )
        if has_legacy and surcharge > 0:
            lines.append(("LEGACY_RETRIEVAL", 1, surcharge * store.MILLICENTS_PER_CENT))
        if req["certification_requested"]:
            lines.append(("CERTIFICATION", 1, rule["certification_fee_cents"] * store.MILLICENTS_PER_CENT))
        if fmt_ == "CD_ROM":
            lines.append(("MEDIA", 1, rule["media_fee_cents"] * store.MILLICENTS_PER_CENT))
        if fmt_ in ("PAPER_MAIL", "CD_ROM"):
            lines.append(("POSTAGE", 1, rule["postage_per_delivery_cents"] * store.MILLICENTS_PER_CENT))
    else:
        if priced_pages != 0:
            lines.append(("PER_PAGE_FLAT", priced_pages, rule["patient_access_per_page_millicents"]))
        if fmt_ == "CD_ROM":
            lines.append(("MEDIA", 1, rule["media_fee_cents"] * store.MILLICENTS_PER_CENT))
        if fmt_ in ("PAPER_MAIL", "CD_ROM"):
            lines.append(("POSTAGE", 1, rule["postage_per_delivery_cents"] * store.MILLICENTS_PER_CENT))
    return lines


def line_amount(quantity, unit_millicents):
    return round_half_up(quantity * unit_millicents)


def subtotal_of(lines):
    return sum(line_amount(q, u) for _, q, u in lines)


def prospective_subtotal(req):
    """The subtotal an invoice for this request's variant would produce today."""
    if facility_of(req) is None or rule_of_request(req) is None:
        return 0
    return subtotal_of(build_priced_lines(req, req.get("billable_page_count", 0)))


def applicable_cap(req):
    """invoice_cap_application: the tighter of the two statutory ceilings."""
    rule = rule_of_request(req)
    if req["delivery_format"] in store.ELECTRONIC_FORMATS:
        return min(rule["electronic_delivery_total_cap_cents"], rule["total_fee_cap_cents"])
    return rule["total_fee_cap_cents"]


# ------------------------------------------------------------------ request routing
def enter_release_ready(req):
    """The billing entry rule on any entry into RELEASE_READY."""
    req["fulfillment_status"] = "RELEASE_READY"
    if req["billing_status"] == "PENDING_INVOICE" and prospective_subtotal(req) == 0:
        req["billing_status"] = "NOT_BILLABLE"


def redactions_open(request_id):
    return any(
        s["redaction_status"] in ("OPEN", "APPLIED", "REWORK")
        for s in segments_of(request_id)
    )


def bubble_up_from_redaction(req):
    """REDACTION -> RELEASE_READY once nothing remains open."""
    if req["fulfillment_status"] != "REDACTION":
        return False
    if redactions_open(req["id"]):
        return False
    enter_release_ready(req)
    refresh_statutory_due_at(req)
    return True


# ------------------------------------------------------------------ invoice cascade
def void_invoice(inv, reason):
    inv["status"] = "VOIDED"
    inv["void_reason"] = reason
    inv["settled_at"] = store.fmt(store.now())
    store.touch(inv)
