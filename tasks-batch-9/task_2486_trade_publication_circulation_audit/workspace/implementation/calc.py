"""Calculations: scoring, ledgers, breakdown, posture, make-good tiering."""
from decimal import Decimal

from store import (add_months, complete_months, db, floor_div_decimal, now,
                   ratio_pct, round_half_up, touch)

# ---- pinned constants (SCAFFOLD calculations[].constants / PRD 3.4, 3.8, 3.9)
QUALIFY_SCORE_THRESHOLD = 70
SCORE_CEILING = 100
FRESH_WINDOW_MONTHS = 12
STALENESS_PENALTY_PER_MONTH = 5
MAX_STALENESS_PENALTY = 30
DIRECT_MAIL_BONUS = 10
DIGITAL_CHANNEL_BONUS = 5
INFO_REQUEST_LIMIT = 2
AUDIT_WINDOW_BUFFER_DAYS = 14
TIER_1_MAX_PCT = Decimal("5.00")
TIER_2_MAX_PCT = Decimal("10.00")
TIER_1_FACTOR = Decimal("0.50")
TIER_2_FACTOR = Decimal("1.00")
TIER_3_FACTOR = Decimal("1.50")

LIVE_FINDING_STATUSES = ("OPEN", "RESPONSE_SUBMITTED", "REJECTED_REOPENED")
LIVE_STATEMENT_STATUSES = (
    "DRAFT", "FILED", "UNDER_AUDIT", "FINDINGS_OPEN", "AUDIT_CLEARED",
    "RESTATEMENT_REQUIRED",
)


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def rules_for(publication_id):
    out = {}
    for rule in db.qualification_rules.values():
        if rule["publication_id"] == publication_id:
            out[rule["dimension"]] = rule
    return out


def subscribers_of(publication_id):
    return [s for s in db.subscribers.values() if s["publication_id"] == publication_id]


def statements_of(publication_id):
    return [s for s in db.statements.values() if s["publication_id"] == publication_id]


def contracts_of(publication_id):
    return [c for c in db.contracts.values() if c["publication_id"] == publication_id]


def findings_of(engagement_id):
    return [f for f in db.findings.values() if f["engagement_id"] == engagement_id]


def make_goods_of(contract_id):
    return [m for m in db.make_goods.values() if m["contract_id"] == contract_id]


def engagement_publication(engagement):
    stmt = db.statements.get(engagement["statement_id"])
    if stmt is None:
        return None
    return db.publications.get(stmt["publication_id"])


# --------------------------------------------------------------------------
# calculations.qualification_score  (PRD 3.4)
# --------------------------------------------------------------------------

def dimension_points(rules, req):
    attested = {
        "JOB_FUNCTION": req["attested_job_function_code"],
        "INDUSTRY": req["attested_industry_code"],
        "PURCHASING_AUTHORITY": req["attested_purchasing_authority"],
    }
    points = {}
    for dimension, value in attested.items():
        rule = rules.get(dimension)
        if rule is None:
            points[dimension] = 0
            continue
        points[dimension] = rule["points"] if value in rule["allowed_values"] else 0
    return points


def qualification_score(req, rules, at=None):
    """Returns (computed_score, per-dimension points)."""
    at = at or now()
    points = dimension_points(rules, req)
    base = sum(points.values())
    age = complete_months(req["signed_at"], at)
    channel = req["request_channel"]
    if age <= FRESH_WINDOW_MONTHS and channel == "DIRECT_MAIL":
        bonus = DIRECT_MAIL_BONUS
    elif age <= FRESH_WINDOW_MONTHS and channel in ("WEB", "EMAIL"):
        bonus = DIGITAL_CHANNEL_BONUS
    else:
        bonus = 0
    if age <= FRESH_WINDOW_MONTHS:
        penalty = 0
    else:
        penalty = min(MAX_STALENESS_PENALTY,
                      STALENESS_PENALTY_PER_MONTH * (age - FRESH_WINDOW_MONTHS))
    score = base + bonus - penalty
    score = max(0, min(SCORE_CEILING, score))
    return score, points


# --------------------------------------------------------------------------
# calculations.publication_copies_ledger  (PRD 2.10)
# --------------------------------------------------------------------------

def recompute_copies_ledger(pub):
    rows = subscribers_of(pub["id"])
    total = sum(s["copies"] for s in rows)
    pub["copies_on_file_total"] = total
    pub["paid_copies_on_file"] = sum(s["copies"] for s in rows if s["subscription_class"] == "PAID")
    pub["qualified_non_paid_copies_on_file"] = sum(
        s["copies"] for s in rows if s["subscription_class"] == "QUALIFIED_NON_PAID")
    pub["controlled_copies_on_file"] = sum(
        s["copies"] for s in rows if s["subscription_class"] == "CONTROLLED")
    pub["deliverable_copies"] = sum(s["copies"] for s in rows if s["delivery_status"] == "DELIVERABLE")
    pub["undeliverable_copies"] = sum(s["copies"] for s in rows if s["delivery_status"] == "UNDELIVERABLE")
    pub["removed_copies"] = sum(s["copies"] for s in rows if s["delivery_status"] == "REMOVED")
    pub["undeliverable_pct"] = ratio_pct(
        pub["undeliverable_copies"] + pub["removed_copies"], total)


def recompute_finding_counts(pub):
    material = 0
    critical = 0
    for finding in db.findings.values():
        if finding["status"] not in LIVE_FINDING_STATUSES:
            continue
        engagement = db.engagements.get(finding["engagement_id"])
        if engagement is None:
            continue
        stmt = db.statements.get(engagement["statement_id"])
        if stmt is None or stmt["publication_id"] != pub["id"]:
            continue
        if finding["severity"] == "MATERIAL":
            material += 1
        elif finding["severity"] == "CRITICAL":
            critical += 1
    pub["open_material_findings_count"] = material
    pub["open_critical_findings_count"] = critical


# --------------------------------------------------------------------------
# calculations.publication_audit_posture  (PRD 2.9)
# --------------------------------------------------------------------------

def derive_posture(pub):
    if pub["open_critical_findings_count"] > 0:
        return "FROZEN"
    for stmt in statements_of(pub["id"]):
        if stmt["status"] == "RESTATEMENT_REQUIRED":
            return "FROZEN"
    if pub["undeliverable_pct"] >= pub["undeliverable_restrict_pct"]:
        return "RESTRICTED"
    if pub["open_material_findings_count"] > 0:
        return "RESTRICTED"
    return "OPEN"


def mark_drafts_stale(publication_id):
    """Mark every DRAFT statement of the publication as having a stale
    breakdown.  Returns how many drafts actually flipped."""
    marked = 0
    for stmt in statements_of(publication_id):
        if stmt["status"] != "DRAFT":
            continue
        if not stmt["breakdown_stale"]:
            stmt["breakdown_stale"] = True
            touch(stmt)
            marked += 1
    return marked


def recompute_publication(pub):
    """Re-derive counters and posture.  Any posture CHANGE marks drafts stale
    (PRD 2.9).  Returns (posture_before, posture_after, drafts_marked)."""
    before = pub["audit_posture"]
    recompute_copies_ledger(pub)
    recompute_finding_counts(pub)
    after = derive_posture(pub)
    pub["audit_posture"] = after
    marked = 0
    if after != before:
        marked = mark_drafts_stale(pub["id"])
    return before, after, marked


# --------------------------------------------------------------------------
# calculations.contract_makegood_ledger  (PRD 2.11)
# --------------------------------------------------------------------------

def recompute_contract_ledger(contract):
    pool = contract["insertion_count"] * contract["gross_rate_cents_per_insertion"]
    committed = 0
    waived = 0
    for obligation in make_goods_of(contract["id"]):
        if obligation["status"] in ("PENDING", "OFFERED", "ACCEPTED"):
            committed += obligation["credit_cents"]
        elif obligation["status"] == "WAIVED":
            waived += obligation["credit_cents"]
    contract["makegood_credit_pool_cents"] = pool
    contract["makegood_credit_committed_cents"] = committed
    contract["makegood_credit_waived_cents"] = waived
    contract["makegood_credit_available_cents"] = pool - committed - waived


# --------------------------------------------------------------------------
# calculations.controlled_copies_cap_allowance + statement breakdown (PRD 3.7)
# --------------------------------------------------------------------------

def controlled_allowance(core, controlled_cap_pct):
    cap = Decimal(controlled_cap_pct)
    denominator = Decimal("100") - cap
    if denominator <= 0:
        return 0
    return floor_div_decimal(Decimal(core) * cap / denominator)


def _audit_verified_evidence_ok(subscriber, period_end):
    for req in db.qualification_requests.values():
        if req["subscriber_id"] != subscriber["id"] or req["status"] != "VERIFIED":
            continue
        doc = db.source_documents.get(req["source_document_id"])
        if doc is None:
            continue
        if doc["purge_status"] != "RETAINED":
            continue
        if doc["retention_expires_at"] is not None and doc["retention_expires_at"] >= period_end:
            return True
    return False


def eligible_subscribers(stmt, pub):
    period_end = stmt["period_end"]
    out = []
    for sub in subscribers_of(pub["id"]):
        if sub["delivery_status"] != "DELIVERABLE":
            continue
        if sub["qualified_at"] is None or sub["qualification_expires_at"] is None:
            continue
        if not sub["qualified_at"] < period_end:
            continue
        if not sub["qualification_expires_at"] >= period_end:
            continue
        if stmt["basis"] == "AUDIT_VERIFIED" and not _audit_verified_evidence_ok(sub, period_end):
            continue
        out.append(sub)
    return out


def digital_reach_for(stmt):
    total = 0
    for snap in db.snapshots.values():
        if snap["publication_id"] != stmt["publication_id"]:
            continue
        if snap["status"] != "VALIDATED":
            continue
        if snap["window_start"] < stmt["period_start"]:
            continue
        if snap["window_end"] > stmt["period_end"]:
            continue
        total += snap["combined_reach_deduplicated"]
    return total


def compute_statement_breakdown(stmt, pub):
    rows = eligible_subscribers(stmt, pub)
    paid = sum(s["copies"] for s in rows if s["subscription_class"] == "PAID")
    qnp = sum(s["copies"] for s in rows if s["subscription_class"] == "QUALIFIED_NON_PAID")
    controlled_raw = sum(s["copies"] for s in rows if s["subscription_class"] == "CONTROLLED")
    core = paid + qnp
    allowance = controlled_allowance(core, pub["controlled_cap_pct"])
    included = min(controlled_raw, allowance)
    stmt["paid_copies"] = paid
    stmt["qualified_non_paid_copies"] = qnp
    stmt["controlled_copies_included"] = included
    stmt["controlled_copies_excess"] = controlled_raw - included
    stmt["total_qualified_copies"] = paid + qnp + included
    stmt["digital_reach_verified"] = digital_reach_for(stmt)
    stmt["undeliverable_pct_at_close"] = pub["undeliverable_pct"]
    stmt["statement_type"] = "AUDITED" if stmt["basis"] == "AUDIT_VERIFIED" else "PUBLISHER_STATEMENT"
    stmt["breakdown_stale"] = False


# --------------------------------------------------------------------------
# calculations.digital_combined_reach  (PRD 3.6)
# --------------------------------------------------------------------------

def combined_reach(website_unique_visitors, newsletter_unique_opens, overlap_pct):
    gross = website_unique_visitors + newsletter_unique_opens
    discounted = round_half_up(
        Decimal(newsletter_unique_opens) * (Decimal("100") - Decimal(overlap_pct)) / Decimal("100"), 0)
    deduplicated = website_unique_visitors + int(discounted)
    return gross, deduplicated


# --------------------------------------------------------------------------
# calculations.rate_base_shortfall_makegood  (PRD 3.9)
# --------------------------------------------------------------------------

def tier_factor_for(shortfall_pct):
    if shortfall_pct <= TIER_1_MAX_PCT:
        return TIER_1_FACTOR
    if shortfall_pct <= TIER_2_MAX_PCT:
        return TIER_2_FACTOR
    return TIER_3_FACTOR


def shortfall_makegood(contract, total_qualified_copies):
    """Returns None when the contract is inside its tolerance, else the
    computed obligation figures."""
    guaranteed = contract["guaranteed_rate_base"]
    shortfall_copies = max(0, guaranteed - total_qualified_copies)
    shortfall_pct = ratio_pct(shortfall_copies, guaranteed)
    if shortfall_pct <= Decimal(contract["shortfall_tolerance_pct"]):
        return None
    factor = tier_factor_for(shortfall_pct)
    per_insertion = int(round_half_up(
        Decimal(contract["gross_rate_cents_per_insertion"]) * (shortfall_pct / Decimal("100")) * factor,
        0))
    credit = per_insertion * contract["insertion_count"]
    bonus = credit // contract["gross_rate_cents_per_insertion"]
    return {
        "shortfall_copies": shortfall_copies,
        "shortfall_pct": shortfall_pct,
        "tier_factor": factor,
        "per_insertion_credit_cents": per_insertion,
        "credit_cents": credit,
        "bonus_insertions": bonus,
    }


# --------------------------------------------------------------------------
# calculations.statement_reconciliation_discrepancy  (PRD 3.9)
# --------------------------------------------------------------------------

def reconciliation(stmt, engagement):
    declared = stmt["declared_total_copies"]
    discrepancy_copies = declared - engagement["verified_qualified_copies"]
    discrepancy_pct = ratio_pct(abs(discrepancy_copies), declared)
    return discrepancy_copies, discrepancy_pct


# --------------------------------------------------------------------------
# qualification windows (PRD 3.4)
# --------------------------------------------------------------------------

def window_collides(sub, pub, at):
    """Closed-interval collision test between the window a verification would
    open and the window already running on the recipient."""
    if sub["qualified_at"] is None or sub["qualification_expires_at"] is None:
        return False
    new_start = at
    new_end = add_months(at, pub["qualification_validity_months"])
    running_start = sub["qualified_at"]
    running_end = sub["qualification_expires_at"]
    return max(new_start, running_start) <= min(new_end, running_end)


def grace_window_open(sub, pub, at):
    if sub["qualification_expires_at"] is None:
        return False
    from store import add_days
    return at >= add_days(sub["qualification_expires_at"], -pub["renewal_grace_days"])
