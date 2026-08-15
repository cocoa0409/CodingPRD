"""Business logic: pricing calculations, approval pipeline, clock sweep,
seasonal occurrence expansion, damage forfeiture allocation.

Money discipline (PRD §2.7, §3.6): integer cents everywhere; components are
rounded half-up individually BEFORE summation; the volume discount is keyed on
the pre-discount subtotal and rounded half-up once.
"""
from datetime import timedelta

import db
import errors
import util
from validation import (
    new_id, now_iso, touch, init_common, policy_for, insurance_sufficient,
    calendar_conflict, permit_blocked_conflict, derive_priority_class,
    request_priority_key, issue_invoice, void_invoice, post_txn,
    fee_payments_total, open_assessment_exists, recompute_standing,
    run_waitlist_sweep, cancel_permit_record,
)

RATE_CLASSES = {"INTERNAL", "NONPROFIT", "FOR_PROFIT"}
FACILITY_TIERS = {"STANDARD", "PREMIUM", "ATHLETIC"}


# ---------------------------------------------------------------------------
# Pricing calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def rental_fee_cents(policy, starts_at, ends_at):
    """Tiered rental charge: whole 30-minute blocks rounding up; block count
    halved gives billable hours; >= 6 billable hours earns 10% off, rounded
    half-up once at the rebate step."""
    minutes = (ends_at - starts_at).total_seconds() / 60.0
    block_count = util.ceil_div_30(minutes)
    billable_hours = block_count / 2.0
    base = billable_hours * policy["hourly_rate_cents"]
    if billable_hours >= 6:
        base = util.round_half_up_cents(base * 0.90)
    return int(base)


def staffing_charge_cents(policy, hours):
    """hours x custodial rate, rounded half-up; minimum-shift floor bills at
    least 2.0 hours whenever hours > 0."""
    if hours is None or hours <= 0:
        return 0
    if hours < 2.0:
        hours = 2.0
    return util.round_half_up_cents(hours * policy["custodial_hourly_cents"])


def after_hours_charge_cents(staffing, after_hours_flag, weekend_flag):
    """Uplifts compose additively on the (already rounded) staffing base."""
    uplift = (0.50 if after_hours_flag else 0.0) + (0.25 if weekend_flag else 0.0)
    if uplift == 0.0:
        return 0
    return util.round_half_up_cents(staffing * uplift)


def volume_discount_cents(subtotal):
    """Tier keyed on the pre-discount subtotal, inclusive floors; not re-keyed
    after discounting."""
    if subtotal >= 200000:
        pct = 0.15
    elif subtotal >= 100000:
        pct = 0.10
    elif subtotal >= 50000:
        pct = 0.05
    else:
        pct = 0.0
    return util.round_half_up_cents(subtotal * pct)


def deposit_required_cents(policy, rental_fee):
    """max(floor, round_half_up(rental_fee * basis_points / 10000))."""
    raw = util.round_half_up_cents(rental_fee * policy["deposit_basis_points"] / 10000)
    return max(policy["deposit_floor_cents"], raw)


def build_invoice_amounts(policy, facility, occ_start, occ_end, wo, hours):
    """Assemble the four money components in pinned order and the total."""
    rental = rental_fee_cents(policy, occ_start, occ_end)
    staffing = staffing_charge_cents(policy, hours) if wo is not None else 0
    after = after_hours_charge_cents(
        staffing, wo["after_hours_flag"], wo["weekend_flag"]) if wo is not None else 0
    subtotal = rental + staffing + after
    discount = volume_discount_cents(subtotal)
    total = max(0, subtotal - discount)
    return rental, staffing, after, discount, total


def permit_work_order(permit_id):
    for w in db.work_orders.values():
        if w["permit_id"] == permit_id and w["wo_status"] != "CANCELLED":
            return w
    return None


def provisional_invoice(permit_id):
    for inv in db.invoices.values():
        if inv["permit_id"] == permit_id and inv["invoice_kind"] == "PROVISIONAL" \
                and inv["invoice_status"] in ("DRAFT", "ISSUED"):
            return inv
    return None


def final_invoice(permit_id):
    for inv in db.invoices.values():
        if inv["permit_id"] == permit_id and inv["invoice_kind"] == "FINAL" \
                and inv["invoice_status"] in ("DRAFT", "ISSUED"):
            return inv
    return None


# ---------------------------------------------------------------------------
# Approval pipeline
# ---------------------------------------------------------------------------

def approve_request(req):
    """UNDER_REVIEW -> APPROVED. Caller has already enforced state, OCC,
    capacity, insurance, standing, policy, and conflict gates. Creates the
    Permit, PROVISIONAL invoice, work order; demotes lower-priority overlaps."""
    renter = db.renters[req["renter_org_id"]]
    fac = db.facilities[req["facility_id"]]
    site = db.sites[fac["site_id"]]
    tz = util.tz_for_site(site)
    starts_at = util.parse_iso(req["starts_at"])
    ends_at = util.parse_iso(req["ends_at"])

    policy = policy_for(renter["rate_class"], fac["facility_tier"], starts_at)
    if policy is None:
        raise errors.reference_invalid(
            "No ACTIVE RateClassPolicy covers starts_at for (rate_class, facility_tier)")

    req["request_status"] = "APPROVED"
    touch(req)  # approval increments the request version by one

    occ_start, occ_end = starts_at, ends_at
    blocked_start = occ_start - timedelta(minutes=fac["setup_buffer_minutes"])
    blocked_end = occ_end + timedelta(minutes=fac["teardown_buffer_minutes"])

    rental = rental_fee_cents(policy, occ_start, occ_end)
    dep_required = deposit_required_cents(policy, rental)

    permit = init_common()
    permit.update({
        "rental_request_id": req["id"],
        "renter_org_id": renter["id"],
        "facility_id": fac["id"],
        "occupancy_start": util.iso_z(occ_start),
        "occupancy_end": util.iso_z(occ_end),
        "blocked_start": util.iso_z(blocked_start),
        "blocked_end": util.iso_z(blocked_end),
        "lifecycle_status": "ISSUED",
        "financial_status": "DEPOSIT_PENDING",
        "deposit_required_cents": dep_required,
        "deposit_held_cents": 0,
        "seasonal_permit_id": req.get("seasonal_permit_id"),
        "superseded_by_permit_id": None,
    })
    db.permits[permit["id"]] = permit

    # Custodial work order (buffers are billable custodial time).
    wo = None
    if fac["requires_custodian"]:
        wo = init_common()
        span = blocked_end - blocked_start
        after_flag, weekend_flag = util.compute_wo_flags(blocked_start, blocked_end, tz)
        wo.update({
            "permit_id": permit["id"],
            "facility_id": fac["id"],
            "scheduled_start": util.iso_z(blocked_start),
            "scheduled_end": util.iso_z(blocked_end),
            "estimated_hours": util.hours_2dp(span),
            "actual_hours": None,
            "after_hours_flag": after_flag,
            "weekend_flag": weekend_flag,
            "wo_status": "SCHEDULED",
        })
        db.work_orders[wo["id"]] = wo

    # PROVISIONAL invoice (estimated variant).
    hours = wo["estimated_hours"] if wo is not None else 0
    rental_c, staffing_c, after_c, discount_c, total_c = build_invoice_amounts(
        policy, fac, occ_start, occ_end, wo, hours)
    issue_invoice(permit, renter, "PROVISIONAL",
                  rental_c, staffing_c, after_c, discount_c, total_c)

    # Zero-deposit permits secure automatically at issuance.
    if dep_required == 0:
        permit["financial_status"] = "SECURED"
        permit["deposit_held_cents"] = 0
        touch(permit)

    # Priority arbitration: lower-priority overlapping pending requests are
    # demoted to WAITLISTED.
    for other in list(db.requests.values()):
        if other["id"] == req["id"]:
            continue
        if other["request_status"] not in (
                "SUBMITTED", "UNDER_REVIEW", "RESUBMITTED", "WAITLISTED"):
            continue
        if other["facility_id"] != fac["id"]:
            continue
        o_start = util.parse_iso(other["starts_at"])
        o_end = util.parse_iso(other["ends_at"])
        if not util.overlaps(blocked_start, blocked_end, o_start, o_end):
            continue
        if request_priority_key(req) < request_priority_key(other):
            other["request_status"] = "WAITLISTED"
            touch(other)
    return permit


# ---------------------------------------------------------------------------
# Damage finalization — deposit forfeiture allocation
# ---------------------------------------------------------------------------

def finalize_assessment(assessment):
    """Runs when an assessment reaches FINAL (accept, resolve_appeal, or the
    14-day window elapsing). Exact integer-cents waterfall, no rounding."""
    permit = db.permits.get(assessment["permit_id"])
    if permit is None:
        return
    renter = db.renters.get(permit["renter_org_id"])
    adjudicated = assessment["adjudicated_amount_cents"] or 0
    held = permit["deposit_held_cents"]
    applied = min(held, adjudicated)
    refunded = held - applied
    shortfall = adjudicated - applied

    if applied > 0:
        post_txn(permit["id"], None, "DEPOSIT_FORFEIT", applied)
    if refunded > 0:
        post_txn(permit["id"], None, "DEPOSIT_REFUND", refunded)
    if shortfall > 0:
        # DAMAGE invoice accrues onto the renter's outstanding balance.
        issue_invoice(permit, renter, "DAMAGE", 0, 0, 0, 0, shortfall)

    permit["deposit_held_cents"] = 0 if (applied + refunded) > 0 else held
    if adjudicated > 0:
        permit["financial_status"] = "FORFEITED"
        if renter is not None:
            renter["forfeiture_count"] += 1
            touch(renter)
            recompute_standing(renter)
    else:
        permit["financial_status"] = "SETTLED"
    touch(permit)


# ---------------------------------------------------------------------------
# Logical clock sweep — fires every time-based system transition
# ---------------------------------------------------------------------------

def sweep_clock():
    now = util.clock_now()

    # Insurance certificates lapse.
    for c in db.certificates.values():
        if c["cert_status"] == "VALID" and now >= util.parse_iso(c["effective_to"]):
            c["cert_status"] = "EXPIRED"
            touch(c)
            _insurance_loss_cascade(c)

    # Unapproved requests lapse once their start passes.
    for r in db.requests.values():
        if r["request_status"] in ("SUBMITTED", "WAITLISTED") and \
                now >= util.parse_iso(r["starts_at"]):
            r["request_status"] = "EXPIRED"
            touch(r)

    # Permits activate or lapse at occupancy start.
    for p in db.permits.values():
        if p["lifecycle_status"] != "ISSUED":
            continue
        occ_start = util.parse_iso(p["occupancy_start"])
        if now < occ_start:
            continue
        if p["financial_status"] == "SECURED":
            p["lifecycle_status"] = "ACTIVE"
            touch(p)
            for w in db.work_orders.values():
                if w["permit_id"] == p["id"] and w["wo_status"] == "SCHEDULED":
                    w["wo_status"] = "IN_PROGRESS"
                    touch(w)
        elif p["financial_status"] == "DEPOSIT_PENDING":
            p["lifecycle_status"] = "EXPIRED"
            cancel_permit_record(p, "ADMINISTRATIVE_LAPSE_NO_REFUND")
            p["financial_status"] = "SETTLED"
            touch(p)

    # Renter standing: 30+ continuous days with an unpaid balance -> SUSPENDED.
    for renter in db.renters.values():
        if renter["org_standing"] != "GOOD_STANDING":
            continue
        if renter["outstanding_balance_cents"] > 0:
            since = renter.get("_balance_since")
            if since is None:
                renter["_balance_since"] = now_iso()
            elif now - util.parse_iso(since) >= timedelta(days=30):
                renter["org_standing"] = "SUSPENDED"
                touch(renter)
        else:
            renter.pop("_balance_since", None)

    # Damage appeal windows close 14 days after adjudication.
    for a in db.damage_assessments.values():
        if a["assessment_status"] == "ADJUDICATED":
            at = a.get("_adjudicated_at")
            if at and now >= util.parse_iso(at) + timedelta(days=14):
                a["assessment_status"] = "FINAL"
                touch(a)
                finalize_assessment(a)

    # Seasonal series complete at season's end.
    for s in db.seasonal_permits.values():
        if s["series_status"] in ("ACTIVE", "PARTIALLY_BLOCKED") and \
                now > util.parse_iso(s["season_end"]):
            s["series_status"] = "COMPLETED"
            touch(s)


def _insurance_loss_cascade(cert):
    """UNDER_REVIEW requests of the cert's renter that no longer have any
    sufficient certificate are sent back to REVISION_REQUESTED (INSURANCE)."""
    for r in db.requests.values():
        if r["request_status"] != "UNDER_REVIEW":
            continue
        if r["renter_org_id"] != cert["renter_org_id"]:
            continue
        renter = db.renters.get(r["renter_org_id"])
        if renter is None or renter["rate_class"] == "INTERNAL":
            continue
        ends_at = util.parse_iso(r["ends_at"])
        if not insurance_sufficient(renter, r["headcount_estimate"], ends_at):
            r["request_status"] = "REVISION_REQUESTED"
            touch(r)


# ---------------------------------------------------------------------------
# Seasonal occurrence expansion
# ---------------------------------------------------------------------------

def expand_series(series):
    """Expand the recurrence rule across the season window; each occurrence is
    run through the approval pipeline in date order. Failures are collected,
    not fatal. Returns (approved_count, failed_count)."""
    renter = db.renters.get(series["renter_org_id"])
    fac = db.facilities.get(series["facility_id"])
    site = db.sites.get(fac["site_id"]) if fac else None
    tz = util.tz_for_site(site)
    season_start = util.parse_iso(series["season_start"])
    season_end = util.parse_iso(series["season_end"])
    occurrences = util.expand_occurrences(
        series["recurrence_rule"], season_start, season_end, tz) or []

    approved = 0
    failed = 0
    for occ_start, occ_end in occurrences:
        req = init_common()
        req.update({
            "renter_org_id": renter["id"],
            "facility_id": fac["id"],
            "event_title": series["series_name"],
            "headcount_estimate": series.get("headcount_estimate") or 1,
            "starts_at": util.iso_z(occ_start),
            "ends_at": util.iso_z(occ_end),
            "request_priority_class": derive_priority_class(renter, False),
            "district_sponsored": False,
            "request_status": "SUBMITTED",
            "revision_round": 0,
            "denial_reason_code": None,
            "submitted_at": now_iso(),
            "seasonal_permit_id": series["id"],
        })
        db.requests[req["id"]] = req

        # Per-occurrence gates: standing, capacity, insurance, calendar,
        # blocked-interval conflict, and a covering policy.
        blocked_start = occ_start - timedelta(minutes=fac["setup_buffer_minutes"])
        blocked_end = occ_end + timedelta(minutes=fac["teardown_buffer_minutes"])
        ok = (
            renter["org_standing"] == "GOOD_STANDING"
            and fac["facility_status"] == "AVAILABLE"
            and site is not None and site["site_status"] == "ACTIVE"
            and req["headcount_estimate"] <= fac["capacity"]
            and insurance_sufficient(renter, req["headcount_estimate"], occ_end)
            and not calendar_conflict(fac, occ_start, occ_end)
            and not permit_blocked_conflict(fac["id"], blocked_start, blocked_end)
            and policy_for(renter["rate_class"], fac["facility_tier"], occ_start) is not None
        )
        if not ok:
            failed += 1
            req["request_status"] = "DENIED"
            req["denial_reason_code"] = "CALENDAR_CONFLICT"
            touch(req)
            continue
        req["request_status"] = "UNDER_REVIEW"
        touch(req)
        approve_request(req)
        approved += 1
    return approved, failed
