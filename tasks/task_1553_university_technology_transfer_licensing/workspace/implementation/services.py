"""Business logic: calculations, rollups, cascades, sweeps."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, now, touch, refresh_timestamp

# Constants from SCAFFOLD calculations table
TIER1_SALES_CAP_CENTS = 100000000
ADMIN_FEE_PCT = 25
INVENTOR_PCT_FEDERAL = 40
INVENTOR_PCT_NONFEDERAL = 35
STARTUP_LINKED_REDUCTION_PCT = 5
SHARE_TOTAL_BP = 10000
WRITE_OFF_REVIEW_THRESHOLD_CENTS = 5000000
INITIAL_REPORT_DUE_DAYS = 180
ELECTION_DUE_DAYS = 730
BAR_DATE_DAYS = 365
BAR_BUFFER_DAYS = 30
EQUITY_FIXED_BP = 500
AD_BASE_BP = 800
BASE_VALUATION_CENTS = 1000000000
EQUITY_FLOOR_BP = 200
EQUITY_CAP_BP = 1500
CURE_PERIOD_DAYS = 60
YEAR_SECONDS = 365 * 86400


def round_half_up_cents(numerator, denominator):
    """round_half_up(numerator / denominator) for non-negative ints."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------------------------------------------------------------------
# Cost rollups (unreimbursed_cost_rollup)
# ---------------------------------------------------------------------------

def _disclosure_cost_rows(disclosure_id):
    app_ids = [a["id"] for a in db.applications.values() if a["disclosure_id"] == disclosure_id]
    return [c for c in db.costs.values() if c["patent_application_id"] in app_ids]


def recompute_disclosure_costs(disc):
    unreimbursed = 0
    written_off = 0
    for app in [a for a in db.applications.values() if a["disclosure_id"] == disc["id"]]:
        rows = [c for c in db.costs.values() if c["patent_application_id"] == app["id"]]
        total = sum(c["amount_cents"] for c in rows)
        app_unreimb = sum(
            c["amount_cents"] - c["reimbursed_amount_cents"]
            for c in rows if c["reimbursement_status"] == "UNREIMBURSED"
        )
        if app["total_cost_cents"] != total or app["unreimbursed_cost_cents"] != app_unreimb:
            app["total_cost_cents"] = total
            app["unreimbursed_cost_cents"] = app_unreimb
            touch(app)
        unreimbursed += app_unreimb
        written_off += sum(c["amount_cents"] for c in rows if c["reimbursement_status"] == "WRITTEN_OFF")

    prev_written = disc["written_off_cost_cents"]
    changed = (
        disc["unreimbursed_cost_cents"] != unreimbursed
        or prev_written != written_off
    )
    disc["unreimbursed_cost_cents"] = unreimbursed
    disc["written_off_cost_cents"] = written_off

    threshold = WRITE_OFF_REVIEW_THRESHOLD_CENTS
    if prev_written < threshold <= written_off:
        # Threshold crossing (re-)arms the block even after a sticky clear.
        disc["cost_writeoff_review_required"] = True
        db.writeoff_cleared.discard(disc["id"])
    elif written_off >= threshold and disc["id"] not in db.writeoff_cleared:
        disc["cost_writeoff_review_required"] = True
    elif written_off < threshold:
        disc["cost_writeoff_review_required"] = False
    # else: written_off >= threshold but a sticky clear is in effect -> stays False

    if changed:
        touch(disc)


# ---------------------------------------------------------------------------
# License cumulative rollups
# ---------------------------------------------------------------------------

def recompute_license_rollups(lic):
    rows = [r for r in db.reports.values()
            if r["license_id"] == lic["id"] and r["status"] in ("ACCEPTED", "PAID")]
    sales = sum(r["reported_sales_cents"] for r in rows)
    royalty = sum(r["accepted_royalty_cents"] for r in rows)
    if lic["cumulative_sales_cents"] != sales or lic["cumulative_royalty_cents"] != royalty:
        lic["cumulative_sales_cents"] = sales
        lic["cumulative_royalty_cents"] = royalty
        touch(lic)
    else:
        refresh_timestamp(lic)


# ---------------------------------------------------------------------------
# Royalty acceptance pricing (tiered_earned_royalty + annual_minimum_true_up)
# ---------------------------------------------------------------------------

def _license_year_index(lic, dt):
    secs = int((dt - lic["effective_date"]).total_seconds())
    return secs // YEAR_SECONDS  # floor division


def compute_acceptance(lic, report):
    others = [r for r in db.reports.values()
              if r["license_id"] == lic["id"]
              and r["id"] != report["id"]
              and r["status"] in ("ACCEPTED", "PAID")]
    cumulative_before = sum(r["reported_sales_cents"] for r in others)

    rate1_bp = lic["royalty_rate_bp"]
    rate2_bp = rate1_bp // 2
    headroom = max(0, TIER1_SALES_CAP_CENTS - cumulative_before)
    below = min(report["reported_sales_cents"], headroom)
    above = report["reported_sales_cents"] - below
    tier1 = round_half_up_cents(below * rate1_bp, 10000)
    tier2 = round_half_up_cents(above * rate2_bp, 10000)
    earned = tier1 + tier2

    true_up = 0
    start_idx = _license_year_index(lic, report["period_start"])
    end_idx = _license_year_index(lic, report["period_end"])
    if end_idx > start_idx:
        # Year-closing report; closing year is the year of period_start (1-indexed).
        year_number = start_idx + 1
        year_start = lic["effective_date"] + timedelta(days=365 * (year_number - 1))
        year_end = lic["effective_date"] + timedelta(days=365 * year_number)
        earned_in_year = 0
        if year_start <= report["period_start"] and report["period_end"] <= year_end:
            earned_in_year += earned
        for r in others:
            if year_start <= r["period_start"] and r["period_end"] <= year_end:
                earned_in_year += r["earned_royalty_cents"]
        true_up = max(0, lic["minimum_annual_royalty_cents"] - earned_in_year)

    return earned, true_up, earned + true_up


# ---------------------------------------------------------------------------
# Distribution waterfall and share splits
# ---------------------------------------------------------------------------

def _split_pool(pool_cents, items):
    """items: [(key, weight_bp, created_at, seq)]. Floor then distribute the
    remainder one cent at a time ordered by weight DESC, created_at ASC
    (seq as deterministic tie-break), wrapping. Returns [(key, amount)] in
    that pinned order."""
    if not items:
        return []
    floors = {key: (pool_cents * weight) // SHARE_TOTAL_BP for key, weight, _, _ in items}
    remainder = pool_cents - sum(floors.values())
    order = sorted(items, key=lambda x: (-x[1], x[2], x[3]))
    amounts = dict(floors)
    i = 0
    while remainder > 0:
        amounts[order[i % len(order)][0]] += 1
        remainder -= 1
        i += 1
    return [(key, amounts[key]) for key, _, _, _ in order]


def compute_distribution_figures(report, lic, disc):
    gross = report["accepted_royalty_cents"]
    cost_offset = min(gross, disc["unreimbursed_cost_cents"])
    net = gross - cost_offset
    admin_fee = round_half_up_cents(net * ADMIN_FEE_PCT, 100)

    if disc["funding_source"] in ("FEDERAL", "MIXED"):
        inventor_pct = INVENTOR_PCT_FEDERAL
    else:
        inventor_pct = INVENTOR_PCT_NONFEDERAL
    if lic["startup_id"] is not None:
        inventor_pct -= STARTUP_LINKED_REDUCTION_PCT

    inventor_pool = round_half_up_cents(net * inventor_pct, 100)
    department_pool = net - admin_fee - inventor_pool
    university_pool = cost_offset + admin_fee

    confirmed = [e for e in db.entries.values()
                 if e["disclosure_id"] == disc["id"] and e["confirmation_status"] == "CONFIRMED"]

    inv_items = [(e["inventor_id"], e["share_bp"], e["created_at"], e["seq"]) for e in confirmed]
    inventor_shares = [
        {"inventor_id": key, "amount_cents": amount}
        for key, amount in _split_pool(inventor_pool, inv_items)
    ]

    dept_weights = {}
    for e in confirmed:
        inventor = db.inventors.get(e["inventor_id"])
        if inventor is None:
            continue
        dept = db.departments.get(inventor["department_id"])
        if dept is None:
            continue
        key = dept["id"]
        if key not in dept_weights:
            dept_weights[key] = [0, dept["created_at"], dept["seq"]]
        dept_weights[key][0] += e["share_bp"]
    dept_items = [(key, w, ca, sq) for key, (w, ca, sq) in dept_weights.items()]
    department_shares = [
        {"department_id": key, "amount_cents": amount}
        for key, amount in _split_pool(department_pool, dept_items)
    ]

    return {
        "gross_cents": gross,
        "cost_offset_cents": cost_offset,
        "net_cents": net,
        "admin_fee_cents": admin_fee,
        "inventor_pool_cents": inventor_pool,
        "department_pool_cents": department_pool,
        "university_pool_cents": university_pool,
        "inventor_shares": inventor_shares,
        "department_shares": department_shares,
    }


# ---------------------------------------------------------------------------
# Cost offset application / reversal (distribution approve & cancel)
# ---------------------------------------------------------------------------

def _disclosure_for_distribution(dist):
    report = db.reports[dist["royalty_report_id"]]
    lic = db.licenses[report["license_id"]]
    return db.disclosures[lic["disclosure_id"]]


def apply_cost_offsets(dist):
    disc = _disclosure_for_distribution(dist)
    remaining = dist["cost_offset_cents"]
    rows = [c for c in _disclosure_cost_rows(disc["id"])
            if c["reimbursement_status"] == "UNREIMBURSED"]
    rows.sort(key=lambda c: (c["incurred_date"], c["created_at"], c["seq"]))
    applications = []
    for c in rows:
        if remaining <= 0:
            break
        room = c["amount_cents"] - c["reimbursed_amount_cents"]
        applied = min(room, remaining)
        if applied <= 0:
            continue
        c["reimbursed_amount_cents"] += applied
        remaining -= applied
        if c["reimbursed_amount_cents"] == c["amount_cents"]:
            c["reimbursement_status"] = "REIMBURSED"
        touch(c)
        applications.append({"cost_id": c["id"], "applied_cents": applied})
    dist["cost_applications"] = applications
    recompute_disclosure_costs(disc)


def reverse_cost_offsets(dist):
    disc = _disclosure_for_distribution(dist)
    for application in dist["cost_applications"]:
        c = db.costs.get(application["cost_id"])
        if c is None:
            continue
        c["reimbursed_amount_cents"] -= application["applied_cents"]
        if c["reimbursement_status"] != "WRITTEN_OFF":
            if c["reimbursed_amount_cents"] == c["amount_cents"]:
                c["reimbursement_status"] = "REIMBURSED"
            else:
                c["reimbursement_status"] = "UNREIMBURSED"
        touch(c)
    recompute_disclosure_costs(disc)


# ---------------------------------------------------------------------------
# Startup equity (startup_equity_bp)
# ---------------------------------------------------------------------------

def compute_equity_bp(startup, post_money_valuation_cents):
    if startup["equity_model"] == "FIXED":
        return EQUITY_FIXED_BP
    raw = (AD_BASE_BP * BASE_VALUATION_CENTS) // post_money_valuation_cents
    return max(EQUITY_FLOOR_BP, min(EQUITY_CAP_BP, raw))


# ---------------------------------------------------------------------------
# COI coverage / overlap helpers
# ---------------------------------------------------------------------------

def coi_coverage_active(startup_id):
    clock = now()
    for p in db.coi_plans.values():
        if (p["startup_id"] == startup_id and p["status"] == "APPROVED"
                and p["coverage_start"] <= clock < p["coverage_end"]):
            return True
    return False


def _half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def coi_window_overlap(startup_id, inventor_id, start, end, statuses, exclude_id=None):
    for p in db.coi_plans.values():
        if exclude_id is not None and p["id"] == exclude_id:
            continue
        if (p["startup_id"] == startup_id and p["inventor_id"] == inventor_id
                and p["status"] in statuses
                and _half_open_overlap(start, end, p["coverage_start"], p["coverage_end"])):
            return True
    return False


# ---------------------------------------------------------------------------
# License clock sweep (EXECUTED->ACTIVE, EXECUTED/ACTIVE->EXPIRED)
# ---------------------------------------------------------------------------

def license_sweep():
    clock = now()
    activated = []
    expired = []
    for lic in sorted(db.licenses.values(), key=lambda l: (l["created_at"], l["seq"])):
        if lic["status"] in ("EXECUTED", "ACTIVE") and clock >= lic["expiration_date"]:
            lic["status"] = "EXPIRED"
            touch(lic)
            expired.append(lic["id"])
        elif lic["status"] == "EXECUTED" and clock >= lic["effective_date"]:
            lic["status"] = "ACTIVE"
            touch(lic)
            activated.append(lic["id"])
    return activated, expired


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def abandon_cascade(app, disc):
    for c in db.costs.values():
        if (c["patent_application_id"] == app["id"]
                and c["reimbursement_status"] == "UNREIMBURSED"
                and c["reimbursed_amount_cents"] == 0):
            c["reimbursement_status"] = "WRITTEN_OFF"
            touch(c)
    recompute_disclosure_costs(disc)


def startup_dissolve_cascade(startup):
    for p in db.coi_plans.values():
        if p["startup_id"] == startup["id"] and p["status"] in ("SUBMITTED", "APPROVED"):
            p["status"] = "TERMINATED"
            touch(p)


def license_termination_cascade(lic):
    disc = db.disclosures[lic["disclosure_id"]]
    for m in db.milestones.values():
        if m["license_id"] == lic["id"] and m["status"] == "PENDING":
            m["status"] = "CANCELLED"
            touch(m)
    for r in db.reports.values():
        if r["license_id"] == lic["id"] and r["status"] in ("SUBMITTED", "ACCEPTED"):
            r["status"] = "VOIDED"
            touch(r)
            for dist in db.distributions.values():
                if (dist["royalty_report_id"] == r["id"]
                        and dist["status"] in ("CALCULATED", "APPROVED")):
                    if dist["status"] == "APPROVED":
                        reverse_cost_offsets(dist)
                    dist["status"] = "CANCELLED"
                    touch(dist)
    recompute_license_rollups(lic)
    recompute_disclosure_costs(disc)


def distribution_pay_cascade(dist):
    report = db.reports[dist["royalty_report_id"]]
    if report["status"] == "ACCEPTED":
        report["status"] = "PAID"
        touch(report)
    lic = db.licenses[report["license_id"]]
    recompute_license_rollups(lic)
    for share in dist["department_shares"]:
        dept = db.departments.get(share["department_id"])
        if dept is not None:
            dept["distribution_pool_cents"] += share["amount_cents"]
            touch(dept)


# ---------------------------------------------------------------------------
# Compliance due dates (compliance_due_date)
# ---------------------------------------------------------------------------

def compute_compliance_due_date(disc, report_type, client_due_date):
    if report_type == "INITIAL_DISCLOSURE":
        return disc["created_at"] + timedelta(days=INITIAL_REPORT_DUE_DAYS)
    if report_type == "ELECTION_OF_TITLE":
        statutory = disc["created_at"] + timedelta(days=ELECTION_DUE_DAYS)
        if disc["public_disclosure_date"] is not None:
            bar = (disc["public_disclosure_date"]
                   + timedelta(days=BAR_DATE_DAYS)
                   - timedelta(days=BAR_BUFFER_DAYS))
            return min(statutory, bar)
        return statutory
    return client_due_date
