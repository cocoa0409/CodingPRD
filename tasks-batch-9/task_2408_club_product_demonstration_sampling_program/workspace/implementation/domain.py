"""Derived fields, calculations and the multi-hop cascades of PRD section 3."""

from datetime import timedelta
from decimal import Decimal

import calc
from errors import fail
from store import (
    by_seq,
    db,
    iso,
    new_ledger_row,
    new_row,
    now,
    today,
    touch,
)


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------
def pub(row):
    """Public projection of a stored row: every field except internal keys."""
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def cert_status(row):
    if row.get("revoked_at"):
        return "REVOKED"
    if calc.parse_date(row["expires_on"]) < today():
        return "EXPIRED"
    return "VALID"


def cert_pub(row):
    out = pub(row)
    out["cert_status"] = cert_status(row)
    return out


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def resolve(table, rid, error_id):
    row = table.get(rid) if isinstance(rid, str) else None
    if row is None:
        fail(error_id, "No such resource: %s" % (rid,))
    return row


def event_assignments(event_id):
    return by_seq([a for a in db.assignments.values() if a["demo_event_id"] == event_id])


def event_reservations(event_id):
    return by_seq([r for r in db.reservations.values() if r["demo_event_id"] == event_id])


def event_shipments(event_id):
    return by_seq([s for s in db.shipments.values() if s["demo_event_id"] == event_id])


def event_reconciliation(event_id):
    rows = by_seq([r for r in db.reconciliations.values() if r["demo_event_id"] == event_id])
    return rows[0] if rows else None


def event_measurements(event_id):
    return by_seq([m for m in db.measurements.values() if m["demo_event_id"] == event_id])


def event_invoices(event_id):
    return by_seq([i for i in db.invoices.values() if i["demo_event_id"] == event_id])


def event_credits(event_id):
    return by_seq([c for c in db.credits.values() if c["demo_event_id"] == event_id])


def live_invoice(event_id):
    """The at-most-one invoice in DRAFT, ISSUED or PAID."""
    for inv in event_invoices(event_id):
        if inv["invoice_status"] in ("DRAFT", "ISSUED", "PAID"):
            return inv
    return None


def demonstrator_assignments(demonstrator_id):
    return by_seq(
        [a for a in db.assignments.values() if a["demonstrator_id"] == demonstrator_id]
    )


def baseline_for(club_id, product_id):
    for row in by_seq(list(db.baselines.values())):
        if row["club_id"] == club_id and row["product_id"] == product_id:
            return row
    return None


def received_cases(event_id):
    total = 0
    for s in event_shipments(event_id):
        if s["shipment_status"] in calc.RECEIVED_SHIPMENT_STATUSES:
            total += s["cases_received"] or 0
    return total


# ---------------------------------------------------------------------------
# certification gate (PRD 3.4): unrevoked and expires_on >= the event_date
# ---------------------------------------------------------------------------
def holds_valid_cert(demonstrator_id, cert_type, event_date_str):
    event_date = calc.parse_date(event_date_str)
    for row in db.certifications.values():
        if row["demonstrator_id"] != demonstrator_id or row["cert_type"] != cert_type:
            continue
        if row.get("revoked_at"):
            continue
        if calc.parse_date(row["expires_on"]) >= event_date:
            return True
    return False


# ---------------------------------------------------------------------------
# staffing coverage (PRD 3.4)
# ---------------------------------------------------------------------------
def required_support_for(event):
    if (
        event["event_type"] == "FOOD_SAMPLING"
        and event["allocated_sample_cases"] >= calc.SUPPORT_REQUIRED_CASE_THRESHOLD
    ):
        return 1
    return 0


def sync_required_support(event):
    event["required_support_count"] = required_support_for(event)


def coverage_of(event):
    held = [
        a
        for a in event_assignments(event["id"])
        if a["assignment_status"] in calc.HELD_ASSIGNMENT_STATUSES
    ]
    filled_lead = sum(1 for a in held if a["role"] == "LEAD")
    filled_support = sum(1 for a in held if a["role"] == "SUPPORT")
    if filled_lead == 0 and filled_support == 0:
        return "UNSTAFFED"
    if filled_lead >= 1 and filled_support >= event["required_support_count"]:
        return "FULLY_STAFFED"
    return "PARTIALLY_STAFFED"


RECOMPUTABLE_COVERAGE = ("UNSTAFFED", "PARTIALLY_STAFFED", "FULLY_STAFFED")


def recompute_coverage(event):
    """Move staffing_status to the recomputed value. Returns True when it moved."""
    if event["staffing_status"] not in RECOMPUTABLE_COVERAGE:
        return False
    fresh = coverage_of(event)
    if fresh != event["staffing_status"]:
        event["staffing_status"] = fresh
        return True
    return False


def coverage_after_insert(event):
    """The three upgrade transitions fired by an assignment insert."""
    if event["staffing_status"] in ("UNSTAFFED", "PARTIALLY_STAFFED"):
        fresh = coverage_of(event)
        if fresh == "FULLY_STAFFED":
            event["staffing_status"] = "FULLY_STAFFED"
            event["no_show_recovery_open"] = False
        elif fresh == "PARTIALLY_STAFFED":
            event["staffing_status"] = "PARTIALLY_STAFFED"
    touch(event)


def downgrade_coverage(event, from_no_show):
    """An assignment left the held set. Returns True when the event row changed."""
    changed = False
    if from_no_show and not event["no_show_recovery_open"]:
        event["no_show_recovery_open"] = True
        changed = True
    if recompute_coverage(event):
        changed = True
    return changed


# ---------------------------------------------------------------------------
# demonstrator metrics (PRD 3.4)
# ---------------------------------------------------------------------------
def _score(scoped):
    completed = [a for a in scoped if a["assignment_status"] == "COMPLETED"]
    no_shows = [a for a in scoped if a["assignment_status"] == "NO_SHOW"]
    late = [a for a in completed if a.get("late_check_in")]
    raw = (
        Decimal(100)
        - (len(no_shows) * calc.NO_SHOW_PENALTY)
        - (len(late) * calc.LATE_PENALTY)
        + (len(completed) * calc.COMPLETION_BONUS)
    )
    if raw < 0:
        raw = Decimal(0)
    if raw > 100:
        raw = Decimal(100)
    return calc.num2(raw)


def recompute_demonstrator_metrics(dem):
    rows = demonstrator_assignments(dem["id"])
    instant = now()
    past = []
    for a in rows:
        start = calc.parse_instant(a["scheduled_start_utc"])
        if start is not None and start < instant:
            past.append((a, start))
    rolling_cutoff = instant - timedelta(days=calc.ROLLING_WINDOW_DAYS)
    strike_cutoff = instant - timedelta(days=calc.STRIKE_LOOKBACK_DAYS)

    dem["reliability_score_program_to_date"] = _score([a for a, _ in past])
    dem["reliability_score_rolling_90"] = _score(
        [a for a, start in past if start >= rolling_cutoff]
    )
    dem["no_show_strike_count"] = sum(
        1
        for a, start in past
        if a["assignment_status"] == "NO_SHOW" and start >= strike_cutoff
    )
    dem["completed_event_count"] = sum(
        1 for a in rows if a["assignment_status"] == "COMPLETED"
    )


# ---------------------------------------------------------------------------
# denormalised mirrors
# ---------------------------------------------------------------------------
def recompute_settlement(event):
    invoices = event_invoices(event["id"])
    if any(i["invoice_status"] == "PAID" for i in invoices):
        event["settlement_status"] = "PAID"
        return
    if any(i["invoice_status"] == "ISSUED" for i in invoices):
        event["settlement_status"] = "INVOICED"
        return
    if any(c["credit_status"] == "APPLIED" for c in event_credits(event["id"])):
        event["settlement_status"] = "CREDITED"
        return
    event["settlement_status"] = "UNBILLED"


def evaluate_credit_standing(man):
    if (
        man["outstanding_balance_cents"] > man["credit_limit_cents"]
        and man["account_status"] == "ACTIVE"
    ):
        man["account_status"] = "HOLD"
    elif (
        man["outstanding_balance_cents"] <= man["credit_limit_cents"]
        and man["account_status"] == "HOLD"
    ):
        man["account_status"] = "ACTIVE"


def recompute_manufacturer_rollup(man):
    man["outstanding_balance_cents"] = sum(
        i["total_due_cents"]
        for i in db.invoices.values()
        if i["manufacturer_id"] == man["id"] and i["invoice_status"] == "ISSUED"
    )
    man["credit_note_balance_cents"] = sum(
        c["credit_amount_cents"]
        for c in db.credits.values()
        if c["manufacturer_id"] == man["id"]
        and c["credit_status"] == "APPLIED"
        and c.get("applied_to_invoice_id") is None
    )
    evaluate_credit_standing(man)


# ---------------------------------------------------------------------------
# sample allocation waterfall (PRD 3.3)
# ---------------------------------------------------------------------------
def club_week_usage(club_id, product_id, event_date, exclude_event_id=None):
    week_start = calc.week_monday(event_date)
    week_end = week_start + timedelta(days=7)
    pool_used = 0
    reserve_used = 0
    for e in db.demo_events.values():
        if exclude_event_id is not None and e["id"] == exclude_event_id:
            continue
        if e["club_id"] != club_id or e["product_id"] != product_id:
            continue
        if e["booking_status"] not in calc.LIVE_BOOKING_STATUSES:
            continue
        day = calc.parse_date(e["event_date"])
        if week_start <= day < week_end:
            pool_used += e["pool_cases_used"]
            reserve_used += e["reserve_cases_used"]
    return week_start, pool_used, reserve_used


def allocation_waterfall(event, product, manufacturer):
    _, pool_used, reserve_used = club_week_usage(
        event["club_id"],
        event["product_id"],
        calc.parse_date(event["event_date"]),
        exclude_event_id=event["id"],
    )
    bucket1 = max(0, product["weekly_sample_case_pool"] - pool_used)
    from_pool = min(event["requested_sample_cases"], bucket1)
    need = event["requested_sample_cases"] - from_pool
    if manufacturer["program_tier"] == "PLATINUM":
        bucket2 = max(0, product["emergency_reserve_cases"] - reserve_used)
    else:
        bucket2 = 0
    from_reserve = min(need, bucket2)
    return from_pool, from_reserve


# ---------------------------------------------------------------------------
# cancellation credit valuation (PRD 3.9)
# ---------------------------------------------------------------------------
def create_cancellation_credit(event, reason):
    prior_applied = sum(
        c["credit_amount_cents"]
        for c in event_credits(event["id"])
        if c["credit_status"] == "APPLIED"
    )
    invoice = live_invoice(event["id"])
    if invoice is not None:
        gross_base = invoice["subtotal_cents"]
    else:
        club = db.clubs[event["club_id"]]
        gross_base = calc.base_fee_projection(
            event["event_type"], club["club_tier"], event["day_part"]
        )
    billable_base = max(0, gross_base - prior_applied)

    window_start = calc.parse_instant(event["event_window_start_utc"])
    seconds = (window_start - now()).total_seconds()
    notice_hours = 0 if seconds <= 0 else int(seconds // 3600)

    bracket = "HIGH" if billable_base >= calc.NOTICE_BRACKET_SPLIT_CENTS else "LOW"
    notice_tier_pct = calc.NOTICE_TIER[bracket][calc.notice_bracket(notice_hours)]
    reason_multiplier = calc.REASON_MULTIPLIER[reason]
    amount = calc.cents(Decimal(billable_base) * notice_tier_pct * reason_multiplier)
    credit_amount = min(billable_base, amount)

    row = new_row(
        demo_event_id=event["id"],
        manufacturer_id=event["manufacturer_id"],
        credit_reason=reason,
        gross_base_cents=gross_base,
        prior_applied_cents=prior_applied,
        billable_base_cents=billable_base,
        notice_hours=notice_hours,
        notice_tier_pct=float(notice_tier_pct),
        reason_multiplier=float(reason_multiplier),
        credit_amount_cents=credit_amount,
        credit_status="PENDING_APPROVAL",
        approved_by_user_id=None,
        applied_to_invoice_id=None,
    )
    db.credits[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# release cascades
# ---------------------------------------------------------------------------
def release_event_reservations(event):
    for res in event_reservations(event["id"]):
        if res["reservation_status"] not in ("HELD", "ACTIVE"):
            continue
        was_active = res["reservation_status"] == "ACTIVE"
        res["reservation_status"] = "RELEASED"
        touch(res)
        if was_active:
            unit = db.equipment_units.get(res["equipment_unit_id"])
            if unit is not None:
                unit["sanitation_status"] = "SOILED"
                touch(unit)


def release_event_assignments(event):
    """Hop 1: release live assignments. Hop 2: rescore each demonstrator."""
    for a in event_assignments(event["id"]):
        if a["assignment_status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        a["assignment_status"] = "RELEASED"
        touch(a)
        dem = db.demonstrators.get(a["demonstrator_id"])
        if dem is not None:
            recompute_demonstrator_metrics(dem)
            touch(dem)


def freeze_coverage_on_cancel(event):
    """PRD 3.3: coverage freezes when the booking reaches CANCELLED."""
    prior = event["staffing_status"]
    if prior == "FULLY_STAFFED":
        event["staffing_status"] = "CLOSED_OUT"
        touch(event)
    elif prior in ("UNSTAFFED", "PARTIALLY_STAFFED"):
        event["staffing_status"] = "UNSTAFFED"


def cancel_confirmed_event(event, reason):
    """The full CONFIRMED -> CANCELLED cascade, shared with the club-CLOSED sweep."""
    event["cancellation_reason"] = reason
    event["pool_cases_used"] = 0
    event["reserve_cases_used"] = 0
    event["allocated_sample_cases"] = 0
    sync_required_support(event)
    release_event_assignments(event)
    release_event_reservations(event)
    create_cancellation_credit(event, reason)
    event["booking_status"] = "CANCELLED"
    freeze_coverage_on_cancel(event)
    recompute_settlement(event)
    touch(event)


# ---------------------------------------------------------------------------
# invoice construction (PRD 3.9)
# ---------------------------------------------------------------------------
def build_invoice_figures(event):
    club = db.clubs[event["club_id"]]
    base_amount = calc.base_fee_projection(
        event["event_type"], club["club_tier"], event["day_part"]
    )
    lines = [
        {
            "line_type": "BASE",
            "label": "Base demonstration fee (%s)" % event["event_type"],
            "amount_cents": base_amount,
        }
    ]

    addon_total = 0
    for service in event["addon_services"]:
        if service in calc.ADDON_FLAT_CENTS:
            amount = calc.cents(calc.ADDON_FLAT_CENTS[service])
        else:
            amount = calc.cents(Decimal(base_amount) * calc.ADDON_PCT_OF_BASE[service])
        addon_total += amount
        lines.append(
            {"line_type": "ADDON", "label": service, "amount_cents": amount}
        )

    staffing_total = 0
    for a in event_assignments(event["id"]):
        if a["assignment_status"] != "COMPLETED":
            continue
        dem = db.demonstrators.get(a["demonstrator_id"])
        rate = dem["hourly_rate_cents"] if dem is not None else 0
        amount = calc.cents(
            Decimal(str(a["billable_hours"]))
            * Decimal(rate)
            * calc.ROLE_MULTIPLIER[a["role"]]
        )
        staffing_total += amount
        lines.append(
            {
                "line_type": "STAFFING",
                "label": "%s staffing" % a["role"],
                "amount_cents": amount,
            }
        )

    recon = event_reconciliation(event["id"])
    cases = recon["cases_delivered"] if recon is not None else 0
    handling_total = 0
    amount = calc.cents(Decimal(cases) * calc.HANDLING_FEE_PER_CASE_CENTS)
    handling_total += amount
    lines.append(
        {
            "line_type": "HANDLING",
            "label": "Sample handling (%d cases)" % cases,
            "amount_cents": amount,
        }
    )
    if event["event_type"] == "FOOD_SAMPLING":
        amount = calc.cents(Decimal(cases) * calc.COLD_CHAIN_SURCHARGE_PER_CASE_CENTS)
        handling_total += amount
        lines.append(
            {
                "line_type": "HANDLING",
                "label": "Cold chain surcharge (%d cases)" % cases,
                "amount_cents": amount,
            }
        )

    return {
        "line_items": lines,
        "base_fee_cents": base_amount,
        "addon_fee_cents": addon_total,
        "staffing_fee_cents": staffing_total,
        "sample_handling_fee_cents": handling_total,
        "subtotal_cents": sum(line["amount_cents"] for line in lines),
    }


def monthly_completed_count(manufacturer_id, event_date_str):
    day = calc.parse_date(event_date_str)
    count = 0
    for e in db.demo_events.values():
        if e["manufacturer_id"] != manufacturer_id:
            continue
        if e["booking_status"] != "COMPLETED":
            continue
        other = calc.parse_date(e["event_date"])
        if other.year == day.year and other.month == day.month:
            count += 1
    return count


def apply_invoice_figures(invoice, event):
    """Writes every recomputed money field. credit_applied_cents is preserved."""
    figures = build_invoice_figures(event)
    invoice.update(figures)
    man = db.manufacturers[event["manufacturer_id"]]
    count = monthly_completed_count(event["manufacturer_id"], event["event_date"])
    pct = calc.TIER_BASE_DISCOUNT[man["program_tier"]] + calc.volume_step(count)
    if pct > calc.MAX_VOLUME_DISCOUNT_PCT:
        pct = calc.MAX_VOLUME_DISCOUNT_PCT
    invoice["monthly_completed_event_count"] = count
    invoice["volume_discount_pct"] = float(pct)
    invoice["discount_cents"] = calc.cents(Decimal(invoice["subtotal_cents"]) * pct)
    recompute_total_due(invoice)


def recompute_total_due(invoice):
    invoice["total_due_cents"] = max(
        0,
        invoice["subtotal_cents"]
        - invoice["discount_cents"]
        - invoice["credit_applied_cents"],
    )


# ---------------------------------------------------------------------------
# reconciliation arithmetic (PRD 3.7)
# ---------------------------------------------------------------------------
def reconciliation_figures(event, product, units_sampled, units_wasted, units_returned):
    cases_delivered = received_cases(event["id"])
    units_per_case = product["samples_per_case"]
    units_delivered = cases_delivered * units_per_case
    variance_units = units_delivered - (units_sampled + units_wasted + units_returned)
    if units_delivered == 0:
        variance_pct = Decimal("0.00")
    else:
        variance_pct = calc.dec2(
            Decimal(abs(variance_units)) / Decimal(units_delivered) * Decimal(100)
        )
    if variance_units == 0 or variance_pct <= calc.VARIANCE_TOLERANCE_PCT:
        recon_status = "BALANCED"
    else:
        recon_status = "VARIANCE_FLAGGED"
    return {
        "cases_delivered": cases_delivered,
        "units_per_case": units_per_case,
        "units_delivered": units_delivered,
        "units_sampled": units_sampled,
        "units_wasted": units_wasted,
        "units_returned": units_returned,
        "variance_units": variance_units,
        "variance_pct": float(variance_pct),
        "write_off_cost_cents": 0,
        "recon_status": recon_status,
    }


# ---------------------------------------------------------------------------
# sales lift measurement (PRD 3.8)
# ---------------------------------------------------------------------------
def build_measurement(event, variant, units_sold, baseline, recon):
    event_date = calc.parse_date(event["event_date"])
    if variant == "PROVISIONAL":
        attribution_days = calc.PROVISIONAL_WINDOW_DAYS
        window_boundary = "CLOSED"
        window_end = event_date + timedelta(days=attribution_days - 1)
        cannibalization = Decimal("0.00")
    else:
        attribution_days = event["attribution_window_days"]
        window_boundary = "HALF_OPEN"
        window_end = event_date + timedelta(days=attribution_days)
        cannibalization = calc.dec2(
            Decimal(recon["units_sampled"]) * calc.SAMPLE_CANNIBALIZATION_RATE
        )

    baseline_units_expected = calc.dec2(
        Decimal(baseline["baseline_weekly_units"])
        * Decimal(attribution_days)
        / Decimal(7)
    )
    lift_units = calc.dec2(
        Decimal(units_sold) - baseline_units_expected - cannibalization
    )
    if baseline_units_expected == 0:
        lift_pct = Decimal("0.00")
    else:
        lift_pct = calc.dec2(lift_units / baseline_units_expected * Decimal(100))
    incremental = calc.cents(
        lift_units * Decimal(baseline["baseline_unit_price_cents"])
    )

    row = new_ledger_row(
        demo_event_id=event["id"],
        measurement_variant=variant,
        units_sold_in_window=units_sold,
        attribution_days=attribution_days,
        window_start_date=event["event_date"],
        window_end_date=window_end.isoformat(),
        window_boundary=window_boundary,
        baseline_weekly_units=baseline["baseline_weekly_units"],
        baseline_unit_price_cents=baseline["baseline_unit_price_cents"],
        baseline_units_expected=float(baseline_units_expected),
        cannibalization_units=float(cannibalization),
        lift_units=float(lift_units),
        lift_pct=float(lift_pct),
        incremental_revenue_cents=incremental,
        measurement_status="POSTED",
    )
    db.measurements[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# assignment attendance arithmetic (PRD 3.6)
# ---------------------------------------------------------------------------
def hours_between(check_in, check_out):
    if check_in is None or check_out is None:
        return Decimal("0.00")
    seconds = (check_out - check_in).total_seconds()
    return calc.dec2(Decimal(seconds) / Decimal(3600))


def apply_attendance_figures(assignment):
    check_in = calc.parse_instant(assignment.get("check_in_at"))
    check_out = calc.parse_instant(assignment.get("check_out_at"))
    worked = hours_between(check_in, check_out)
    assignment["hours_worked"] = float(worked)
    if assignment["assignment_status"] == "COMPLETED":
        billable = worked if worked > calc.MIN_BILLABLE_HOURS else calc.MIN_BILLABLE_HOURS
        assignment["billable_hours"] = float(calc.dec2(billable))
    else:
        assignment["billable_hours"] = 0.00


def compute_late_check_in(assignment):
    check_in = calc.parse_instant(assignment.get("check_in_at"))
    if check_in is None:
        return False
    start = calc.parse_instant(assignment["scheduled_start_utc"])
    return check_in > start + timedelta(minutes=calc.LATE_GRACE_MINUTES)


# ---------------------------------------------------------------------------
# event construction helpers
# ---------------------------------------------------------------------------
def write_event_window(event):
    start, end = calc.event_window(event["event_date"], event["day_part"])
    event["event_window_start_utc"] = iso(start)
    event["event_window_end_utc"] = iso(end)
