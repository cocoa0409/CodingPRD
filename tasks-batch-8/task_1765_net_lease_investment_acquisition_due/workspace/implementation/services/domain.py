"""Business logic: calculations (PRD §2.5, scaffold §1.3), deal posture
recompute (PRD §2.7), milestone auto-satisfaction (PRD §3.5), and the
clock-driven deferred transitions (PRD §2.6).

All money math uses Decimal; fractional results round half-up to the declared
field precision, except NOI which truncates (scaffold: "multiplication then
truncation").
"""

from datetime import timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, getcontext

import db
from errors import ApiError
from middleware import bump

getcontext().prec = 60

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3 / PRD §3)
# ---------------------------------------------------------------------------
OPEX_PCT = {"CONSERVATIVE": Decimal("0.15"), "MARKET": Decimal("0.12")}
MIN_CAP_RATE_BPS = 300
MAX_CAP_RATE_BPS = 1200
MIN_DSCR = Decimal("1.25")
MAX_LTV_PCT = 65          # loan <= 65% of psa price
EARNEST_MIN_PCT = 1       # earnest money >= 1% of psa price
ESTOPPEL_TOLERANCE_BPS = 50
TITLE_CURE_THRESHOLD_CENTS = 100000
DAYS_IN_YEAR = 365
DD_PERIOD_MIN = 15
DD_PERIOD_MAX = 120
FINANCING_CONTINGENCY_SLACK = 30  # financing_contingency_days <= dd + 30

MILESTONE_TYPES = [
    "TITLE_REVIEW",
    "SURVEY_REVIEW",
    "ENVIRONMENTAL",
    "PCA",
    "ESTOPPEL_COLLECTION",
    "SNDA_COLLECTION",
    "FINANCING_COMMITMENT",
    "FINAL_WALKTHROUGH",
]
NON_WAIVABLE_MILESTONES = {"TITLE_REVIEW", "ENVIRONMENTAL"}

LEASE_INCLUDED_STATUSES = {"VERIFIED", "ESTOPPEL_PENDING", "ESTOPPELED"}


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up_int(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def truncate_int(x):
    return int(Decimal(x).to_integral_value(rounding=ROUND_DOWN))


# ---------------------------------------------------------------------------
# Lookup helpers (validation priority 3 — path existence, left to right)
# ---------------------------------------------------------------------------
def get_deal(deal_id):
    rec = db.stores["deals"].get(deal_id)
    if rec is None:
        raise ApiError("ERR_DEAL_NOT_FOUND", "Deal id does not exist", 404)
    return rec


def get_tenant(tenant_id):
    rec = db.stores["tenants"].get(tenant_id)
    if rec is None:
        raise ApiError("ERR_TENANT_NOT_FOUND", "Tenant id does not exist", 404)
    return rec


def get_property_scoped(deal, property_id):
    rec = db.stores["properties"].get(property_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_PROPERTY_NOT_FOUND",
                       "Property id does not exist within deal", 404)
    return rec


def get_property_flat(property_id):
    rec = db.stores["properties"].get(property_id)
    if rec is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "Property id does not exist", 404)
    return rec


def get_lease_scoped(prop, lease_id):
    rec = db.stores["leases"].get(lease_id)
    if rec is None or rec["property_id"] != prop["id"]:
        raise ApiError("ERR_LEASE_NOT_FOUND",
                       "Lease id does not exist within property", 404)
    return rec


def get_lease_flat(lease_id):
    rec = db.stores["leases"].get(lease_id)
    if rec is None:
        raise ApiError("ERR_LEASE_NOT_FOUND", "Lease id does not exist", 404)
    return rec


def get_model_scoped(deal, model_id):
    rec = db.stores["models"].get(model_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_MODEL_NOT_FOUND",
                       "UnderwritingModel id does not exist within deal", 404)
    return rec


def get_model_flat(model_id):
    rec = db.stores["models"].get(model_id)
    if rec is None:
        raise ApiError("ERR_MODEL_NOT_FOUND", "UnderwritingModel id does not exist", 404)
    return rec


def get_psa_scoped(deal, psa_id):
    rec = db.stores["psas"].get(psa_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_PSA_NOT_FOUND",
                       "PurchaseAgreement id does not exist within deal", 404)
    return rec


def get_milestone_scoped(deal, milestone_id):
    rec = db.stores["milestones"].get(milestone_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_MILESTONE_NOT_FOUND",
                       "Milestone id does not exist within deal", 404)
    return rec


def get_title_review_scoped(deal, review_id):
    rec = db.stores["title_reviews"].get(review_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_TITLE_REVIEW_NOT_FOUND",
                       "TitleReview id does not exist within deal", 404)
    return rec


def get_title_review_flat(review_id):
    rec = db.stores["title_reviews"].get(review_id)
    if rec is None:
        raise ApiError("ERR_TITLE_REVIEW_NOT_FOUND", "TitleReview id does not exist", 404)
    return rec


def get_exception_scoped(review, ex_id):
    rec = db.stores["title_exceptions"].get(ex_id)
    if rec is None or rec["title_review_id"] != review["id"]:
        raise ApiError("ERR_EXCEPTION_NOT_FOUND",
                       "TitleException id does not exist within review", 404)
    return rec


def get_exception_flat(ex_id):
    rec = db.stores["title_exceptions"].get(ex_id)
    if rec is None:
        raise ApiError("ERR_EXCEPTION_NOT_FOUND", "TitleException id does not exist", 404)
    return rec


def get_ea_scoped(deal, ea_id):
    rec = db.stores["eas"].get(ea_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_EA_NOT_FOUND",
                       "EnvironmentalAssessment id does not exist within deal", 404)
    return rec


def get_pca_scoped(deal, pca_id):
    rec = db.stores["pcas"].get(pca_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_PCA_NOT_FOUND",
                       "PropertyConditionAssessment id does not exist within deal", 404)
    return rec


def get_estoppel_scoped(deal, estoppel_id):
    rec = db.stores["estoppels"].get(estoppel_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_ESTOPPEL_NOT_FOUND",
                       "EstoppelCertificate id does not exist within deal", 404)
    return rec


def get_estoppel_flat(estoppel_id):
    rec = db.stores["estoppels"].get(estoppel_id)
    if rec is None:
        raise ApiError("ERR_ESTOPPEL_NOT_FOUND", "EstoppelCertificate id does not exist", 404)
    return rec


def get_snda_scoped(deal, snda_id):
    rec = db.stores["sndas"].get(snda_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_SNDA_NOT_FOUND",
                       "SNDA id does not exist within deal", 404)
    return rec


def get_snda_flat(snda_id):
    rec = db.stores["sndas"].get(snda_id)
    if rec is None:
        raise ApiError("ERR_SNDA_NOT_FOUND", "SNDA id does not exist", 404)
    return rec


def get_financing_scoped(deal, app_id):
    rec = db.stores["financing"].get(app_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_FINANCING_NOT_FOUND",
                       "FinancingApplication id does not exist within deal", 404)
    return rec


def get_statement_scoped(deal, stmt_id):
    rec = db.stores["statements"].get(stmt_id)
    if rec is None or rec["deal_id"] != deal["id"]:
        raise ApiError("ERR_STATEMENT_NOT_FOUND",
                       "ClosingStatement id does not exist within deal", 404)
    return rec


def get_statement_flat(stmt_id):
    rec = db.stores["statements"].get(stmt_id)
    if rec is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND", "ClosingStatement id does not exist", 404)
    return rec


def get_proration_scoped(stmt, proration_id):
    rec = db.stores["prorations"].get(proration_id)
    if rec is None or rec["closing_statement_id"] != stmt["id"]:
        raise ApiError("ERR_PRORATION_NOT_FOUND",
                       "Proration id does not exist within statement", 404)
    return rec


def get_proration_flat(proration_id):
    rec = db.stores["prorations"].get(proration_id)
    if rec is None:
        raise ApiError("ERR_PRORATION_NOT_FOUND", "Proration id does not exist", 404)
    return rec


def get_trueup_scoped(stmt, adj_id):
    rec = db.stores["true_ups"].get(adj_id)
    if rec is None or rec["closing_statement_id"] != stmt["id"]:
        raise ApiError("ERR_TRUE_UP_NOT_FOUND",
                       "TrueUpAdjustment id does not exist within statement", 404)
    return rec


def get_trueup_flat(adj_id):
    rec = db.stores["true_ups"].get(adj_id)
    if rec is None:
        raise ApiError("ERR_TRUE_UP_NOT_FOUND", "TrueUpAdjustment id does not exist", 404)
    return rec


# ---------------------------------------------------------------------------
# Collection queries
# ---------------------------------------------------------------------------
def _of(store, field, value):
    return [r for r in db.stores[store].values() if r.get(field) == value]


def properties_of(deal_id):
    return _of("properties", "deal_id", deal_id)


def leases_of_property(property_id):
    return _of("leases", "property_id", property_id)


def leases_of_deal(deal_id):
    out = []
    for p in properties_of(deal_id):
        out.extend(leases_of_property(p["id"]))
    return out


def models_of(deal_id):
    return _of("models", "deal_id", deal_id)


def psas_of(deal_id):
    return _of("psas", "deal_id", deal_id)


def milestones_of(deal_id):
    return _of("milestones", "deal_id", deal_id)


def title_reviews_of(deal_id):
    return _of("title_reviews", "deal_id", deal_id)


def exceptions_of(review_id):
    return _of("title_exceptions", "title_review_id", review_id)


def exceptions_of_deal(deal_id):
    out = []
    for tr in title_reviews_of(deal_id):
        out.extend(exceptions_of(tr["id"]))
    return out


def eas_of(deal_id):
    return _of("eas", "deal_id", deal_id)


def pcas_of(deal_id):
    return _of("pcas", "deal_id", deal_id)


def estoppels_of(deal_id):
    return _of("estoppels", "deal_id", deal_id)


def sndas_of(deal_id):
    return _of("sndas", "deal_id", deal_id)


def financing_of(deal_id):
    return _of("financing", "deal_id", deal_id)


def statements_of(deal_id):
    return _of("statements", "deal_id", deal_id)


def prorations_of(stmt_id):
    return _of("prorations", "closing_statement_id", stmt_id)


def trueups_of(stmt_id):
    return _of("true_ups", "closing_statement_id", stmt_id)


def latest_approved_model(deal_id):
    approved = [m for m in models_of(deal_id) if m["status"] == "APPROVED"]
    if not approved:
        return None
    return max(approved, key=lambda m: m["model_version"])


def active_psa(deal_id):
    """The governing purchase agreement: latest executed one when present,
    else the most recently drafted."""
    psas = psas_of(deal_id)
    if not psas:
        return None
    executed = [p for p in psas if p.get("executed_at")]
    pool = executed if executed else psas
    return max(pool, key=lambda p: p["_seq"])


def latest_committed_financing(deal_id):
    committed = [f for f in financing_of(deal_id) if f["status"] == "COMMITTED"]
    if not committed:
        return None
    return max(committed, key=lambda f: f["_seq"])


def latest_financing_with_ds(deal_id):
    apps = [f for f in financing_of(deal_id)
            if f.get("annual_debt_service_cents") is not None]
    if not apps:
        return None
    return max(apps, key=lambda f: f["_seq"])


# ---------------------------------------------------------------------------
# Deal posture (PRD §2.7) — derived aggregate gate
# ---------------------------------------------------------------------------
def recompute_posture(deal):
    """Recompute deal.posture from contributing artifacts. Blocking events:
    an OVERDUE milestone, a FATAL title exception in OPEN/CURE_PROPOSED, or a
    FAILED environmental assessment. Bumps the deal only when the derived
    value actually changes."""
    status = deal["status"]
    if status in ("CLOSED", "TERMINATED", "CLEAR_TO_CLOSE"):
        new = status
    elif status == "SOURCING":
        new = "SOURCING"
    elif status == "PSA_PENDING":
        new = "UNDER_REVIEW"
    else:  # PSA_EXECUTED / DUE_DILIGENCE
        blocked = False
        for m in milestones_of(deal["id"]):
            if m["status"] == "OVERDUE":
                blocked = True
                break
        if not blocked:
            for ex in exceptions_of_deal(deal["id"]):
                if ex["severity"] == "FATAL" and ex["status"] in ("OPEN", "CURE_PROPOSED"):
                    blocked = True
                    break
        if not blocked:
            for ea in eas_of(deal["id"]):
                if ea["status"] == "FAILED":
                    blocked = True
                    break
        new = "DD_BLOCKED" if blocked else "DD_OPEN"
    if new != deal.get("posture"):
        deal["posture"] = new
        bump(deal)


# ---------------------------------------------------------------------------
# Milestones (PRD §3.5)
# ---------------------------------------------------------------------------
def satisfy_milestone(deal, milestone_type):
    """Auto-satisfaction works from PENDING directly or from IN_PROGRESS;
    stamps completed_at with the logical clock and recomputes posture."""
    for m in milestones_of(deal["id"]):
        if m["milestone_type"] != milestone_type:
            continue
        if m["status"] in ("PENDING", "IN_PROGRESS"):
            m["status"] = "SATISFIED"
            m["completed_at"] = db.now_iso()
            bump(m)
        return m
    return None


def milestone_of_type(deal_id, milestone_type):
    for m in milestones_of(deal_id):
        if m["milestone_type"] == milestone_type:
            return m
    return None


def _collection_complete(records):
    """Latest record per lease must be CERTIFIED; requires at least one
    record. Loop-aware: a superseded/deficient earlier certificate for the
    same lease no longer blocks once a newer one is certified."""
    if not records:
        return False
    latest_by_lease = {}
    for r in records:
        cur = latest_by_lease.get(r["lease_id"])
        if cur is None or r["_seq"] > cur["_seq"]:
            latest_by_lease[r["lease_id"]] = r
    return all(r["status"] == "CERTIFIED" for r in latest_by_lease.values())


def recheck_estoppel_collection(deal):
    if _collection_complete(estoppels_of(deal["id"])):
        satisfy_milestone(deal, "ESTOPPEL_COLLECTION")


def recheck_snda_collection(deal):
    if _collection_complete(sndas_of(deal["id"])):
        satisfy_milestone(deal, "SNDA_COLLECTION")


# ---------------------------------------------------------------------------
# Title exceptions (PRD §3.6)
# ---------------------------------------------------------------------------
def recompute_exception_count(review):
    """exception_count = linked exceptions in any non-resolved state
    (OPEN or CURE_PROPOSED)."""
    count = sum(1 for ex in exceptions_of(review["id"])
                if ex["status"] in ("OPEN", "CURE_PROPOSED"))
    if count != review.get("exception_count"):
        review["exception_count"] = count
        bump(review)


# ---------------------------------------------------------------------------
# Calculations (scaffold §1.3)
# ---------------------------------------------------------------------------
def included_leases(deal_id):
    return [l for l in leases_of_deal(deal_id) if l["status"] in LEASE_INCLUDED_STATUSES]


def compute_noi_cents(deal_id, variant):
    """NOI = gross rent minus opex allowance; exact decimal math then
    truncation to whole cents (scaffold: 'multiplication then truncation')."""
    gross = sum(l["annual_base_rent_cents"] for l in included_leases(deal_id))
    pct = OPEX_PCT[variant]
    noi = Decimal(gross) - Decimal(gross) * pct
    return truncate_int(noi)


def compute_cap_rate_bps(noi_cents, purchase_price_cents):
    if not purchase_price_cents:
        return None
    return round_half_up_int(
        Decimal(noi_cents) * Decimal(10000) / Decimal(purchase_price_cents))


def compute_cash_on_cash_bps(deal, noi_cents):
    """Dual-variant counterpart to cap rate; only when a financing
    application with computed debt service exists on the deal."""
    app = latest_financing_with_ds(deal["id"])
    if app is None:
        return None
    equity = (deal["purchase_price_cents"] - app["loan_amount_cents"]
              + (app.get("assumption_fee_cents") or 0))
    if equity <= 0:
        return None
    return round_half_up_int(
        (Decimal(noi_cents) - Decimal(app["annual_debt_service_cents"]))
        * Decimal(10000) / Decimal(equity))


def compute_walt_months(deal_id):
    leases = included_leases(deal_id)
    total_weight = sum(l["annual_base_rent_cents"] for l in leases)
    if not leases or total_weight == 0:
        return 0
    weighted = sum(Decimal(l["annual_base_rent_cents"]) * Decimal(l["remaining_term_months"] or 0)
                   for l in leases)
    return round_half_up_int(weighted / Decimal(total_weight))


def recompute_model(model):
    deal = db.stores["deals"].get(model["deal_id"])
    noi = compute_noi_cents(model["deal_id"], model["opex_allowance_variant"])
    model["noi_cents"] = noi
    model["cap_rate_bps"] = compute_cap_rate_bps(noi, deal["purchase_price_cents"])
    model["walt_months"] = compute_walt_months(model["deal_id"])
    model["cash_on_cash_bps"] = compute_cash_on_cash_bps(deal, noi)


def compute_annual_debt_service(loan_amount_cents, interest_rate_bps, amortization_months):
    """Dual-variant: interest-only when amortization_months == 0, otherwise
    standard constant-payment amortization. The monthly payment is rounded
    half-up to cents first, then multiplied by twelve (pinned order)."""
    loan = Decimal(loan_amount_cents)
    rate = Decimal(interest_rate_bps)
    if amortization_months == 0:
        return round_half_up_int(loan * rate / Decimal(10000))
    r = rate / Decimal(10000) / Decimal(12)
    n = int(amortization_months)
    pow_n = (Decimal(1) + r) ** n
    payment = round_half_up_int(loan * r * pow_n / (pow_n - Decimal(1)))
    return payment * 12


def compute_assumption_fee(loan_type, loan_amount_cents):
    if loan_type == "ASSUMPTION":
        return round_half_up_int(Decimal(loan_amount_cents) * Decimal("0.01"))
    return 0


def compute_dscr(noi_cents, annual_debt_service_cents):
    """4 decimal places, round half-up."""
    if not annual_debt_service_cents:
        return None
    d = (Decimal(noi_cents) / Decimal(annual_debt_service_cents)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return d


def compute_remaining_term_months(now, expiry):
    """Whole months between the logical clock now and lease expiration;
    partial month in progress not counted; floored at zero."""
    months = (expiry.year - now.year) * 12 + (expiry.month - now.month)
    if expiry.day < now.day:
        months -= 1
    return max(0, months)


def rollover_risk_tier(remaining_term_months):
    """Strict thresholds; boundaries land in the upper tier."""
    m = remaining_term_months
    if m < 24:
        return "CRITICAL"
    if m < 60:
        return "HIGH"
    if m < 120:
        return "MEDIUM"
    return "LOW"


def compute_proration_line(line_type, annual_amount_cents, period_start, period_end, closing_date):
    """ACT/365 over the half-open interval [period_start, period_end).
    Seller covers days before closing_date, buyer the rest; the line amount
    is annual * buyer_days / 365 rounded half-up per line."""
    start = db.parse_dt(period_start)
    end = db.parse_dt(period_end)
    closing = db.parse_dt(closing_date)
    days_in_period = (end - start).days
    seller_days = max(0, (min(end, closing) - start).days)
    buyer_days = days_in_period - seller_days
    prorated = round_half_up_int(
        Decimal(annual_amount_cents) * Decimal(buyer_days) / Decimal(DAYS_IN_YEAR))
    direction = "BUYER_CREDIT" if line_type in ("BASE_RENT", "CAM") else "SELLER_CREDIT"
    return prorated, direction


def compute_total_prorations(lines):
    """Pinned rounding order: each line already rounded; buyer credits minus
    seller credits."""
    credits = sum(l["prorated_cents"] for l in lines if l["direction"] == "BUYER_CREDIT")
    debits = sum(l["prorated_cents"] for l in lines if l["direction"] == "SELLER_CREDIT")
    return credits - debits


def compute_cash_to_close(deal, psa, total_prorations_cents):
    """Layered compounding order (pinned): price -> less loan -> plus net
    prorations -> plus assumption fee -> less earnest money."""
    fin = latest_committed_financing(deal["id"])
    loan = fin["loan_amount_cents"] if fin else 0
    fee = (fin.get("assumption_fee_cents") or 0) if fin else 0
    layer1 = psa["psa_price_cents"] - loan
    layer2 = layer1 + total_prorations_cents
    layer3 = layer2 + fee
    return layer3 - deal["earnest_money_cents"]


# ---------------------------------------------------------------------------
# Clock-driven deferred transitions (PRD §2.6)
# ---------------------------------------------------------------------------
def fire_time_transitions():
    """Advancing the logical clock fires, atomically within the clock-set
    request: milestone OVERDUE (PENDING past due_date), estoppel EXPIRED
    (REQUESTED past dd_period_end), financing LAPSED (SUBMITTED past
    financing_contingency_end)."""
    now = db.clock_now()
    for deal in list(db.stores["deals"].values()):
        deal_id = deal["id"]
        # 1. Pending milestones whose due_date has passed -> OVERDUE
        for m in milestones_of(deal_id):
            if m["status"] == "PENDING" and m.get("due_date"):
                if now > db.parse_dt(m["due_date"]):
                    m["status"] = "OVERDUE"
                    bump(m)
        # 2. Requested-but-never-received estoppels -> EXPIRED past dd end
        dd_end = deal.get("dd_period_end")
        if dd_end and now > db.parse_dt(dd_end):
            expired_any = False
            for e in estoppels_of(deal_id):
                if e["status"] == "REQUESTED":
                    e["status"] = "EXPIRED"
                    bump(e)
                    expired_any = True
            if expired_any:
                m = milestone_of_type(deal_id, "ESTOPPEL_COLLECTION")
                if m is not None and m["status"] in ("PENDING", "IN_PROGRESS"):
                    m["status"] = "OVERDUE"
                    bump(m)
        # 3. SUBMITTED financing applications lapse past contingency end
        fc_end = deal.get("financing_contingency_end")
        if fc_end and now > db.parse_dt(fc_end):
            lapsed_any = False
            for f in financing_of(deal_id):
                if f["status"] == "SUBMITTED":
                    f["status"] = "LAPSED"
                    bump(f)
                    lapsed_any = True
            if lapsed_any:
                m = milestone_of_type(deal_id, "FINANCING_COMMITMENT")
                if m is not None and m["status"] in ("PENDING", "IN_PROGRESS"):
                    m["status"] = "OVERDUE"
                    bump(m)
        recompute_posture(deal)
