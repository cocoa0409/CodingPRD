"""Shared business-logic helpers: billing, accumulators, cascades."""
import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
import db


def round_half_up(value):
    """Round to integer using ROUND_HALF_UP."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_2dp(value):
    """Round to 2 decimal places using ROUND_HALF_UP."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --- Contract accumulator recomputation ---

def recompute_contract_accumulators(contract_id):
    """Recompute all derived accumulator fields on a contract."""
    contract = db.contracts.get(contract_id)
    if not contract:
        return
    all_visits = [v for v in db.visits.list_all() if v.get("contract_id") == contract_id]
    billable_statuses = {"BILLABLE_CONFIRMED", "INVOICED", "DISPUTED", "SETTLED"}

    # season_billable_push_count
    push_count = sum(1 for v in all_visits if v.get("billing_status") in billable_statuses)

    # season_billable_minutes
    billable_minutes = sum(v.get("billable_minutes") or 0 for v in all_visits if v.get("billing_status") in billable_statuses)

    # unbilled_billable_cents
    unbilled = sum(
        (v.get("billable_amount_cents") or 0) + (v.get("material_cost_cents") or 0)
        for v in all_visits
        if v.get("billing_status") == "BILLABLE_CONFIRMED"
    )

    # season_billed_cents
    billed_statuses = {"ISSUED", "PARTIALLY_CREDITED", "PARTIALLY_PAID", "PAID"}
    season_billed = sum(
        inv.get("total_cents") or 0
        for inv in db.invoices.list_all()
        if inv.get("contract_id") == contract_id and inv.get("status") in billed_statuses
    )

    # season_sla_miss_count
    sla_miss_count = sum(1 for v in all_visits if v.get("sla_miss") is True)

    # overage_active
    overage = False
    if contract.get("contract_type") == "SEASONAL":
        cap = contract.get("seasonal_push_cap") or 0
        overage = push_count > cap

    contract["season_billable_push_count"] = push_count
    contract["season_billable_minutes"] = billable_minutes
    contract["unbilled_billable_cents"] = unbilled
    contract["season_billed_cents"] = season_billed
    contract["season_sla_miss_count"] = sla_miss_count
    contract["overage_active"] = overage
    _touch(contract)
    db.contracts.update(contract_id, contract)


def _touch(obj):
    """Update updated_at and increment version."""
    obj["updated_at"] = db.now_iso()
    obj["version"] = (obj.get("version") or 0) + 1


def _touch_client(client_id):
    """Recompute client credit_exposure_cents."""
    client = db.clients.get(client_id)
    if not client:
        return
    exposure_statuses = {"ISSUED", "PARTIALLY_CREDITED", "PARTIALLY_PAID"}
    exposure = sum(
        (inv.get("total_cents") or 0) - (inv.get("paid_cents") or 0)
        for inv in db.invoices.list_all()
        if inv.get("contract_id") in [
            c["id"] for c in db.contracts.list_all() if c.get("client_id") == client_id
        ]
        and inv.get("status") in exposure_statuses
    )
    client["credit_exposure_cents"] = exposure
    _touch(client)
    db.clients.update(client_id, client)


# --- Visit billing evaluation ---

def get_effective_trigger_depth(visit):
    """Get the effective trigger depth for a visit."""
    if visit.get("applied_trigger_depth_inches") is not None:
        return visit["applied_trigger_depth_inches"]
    cs = db.contract_sites.get(visit.get("contract_site_id"))
    if cs:
        return cs.get("effective_trigger_depth_inches")
    return None


def get_effective_per_push_rate(visit):
    """Get the effective per-push rate for a visit."""
    if visit.get("applied_per_push_rate_cents") is not None:
        return visit["applied_per_push_rate_cents"]
    cs = db.contract_sites.get(visit.get("contract_site_id"))
    if cs:
        return cs.get("effective_per_push_rate_cents")
    return None


def compute_billable_minutes(visit):
    """Compute billable_minutes for hourly contracts."""
    actual = db._parse_iso(visit.get("actual_start_at"))
    completed = db._parse_iso(visit.get("completed_at"))
    if not actual or not completed:
        return 0
    delta_seconds = (completed - actual).total_seconds()
    delta_minutes = delta_seconds / 60.0
    increments = math.ceil(delta_minutes / 6.0)
    return increments * 6


def is_night_hour(dt_str):
    """Check if the UTC hour of a datetime string falls in the night window."""
    dt = db._parse_iso(dt_str)
    if not dt:
        return False
    hour = dt.hour
    return hour >= 22 or hour < 6


def compute_hourly_charge(visit, contract):
    """Compute billable_amount_cents for an HOURLY visit."""
    billable_mins = visit.get("billable_minutes") or compute_billable_minutes(visit)
    threshold = contract.get("hourly_tier_threshold_minutes") or 2400
    rate1 = contract.get("hourly_rate_cents") or 0
    rate2 = contract.get("hourly_tier2_rate_cents") or 0
    night_pct = contract.get("night_premium_pct") or 0.25

    # Chronological ordering: (actual_start_at ASC, created_at ASC)
    all_visits = [
        v for v in db.visits.list_all()
        if v.get("contract_id") == contract["id"]
        and v.get("billing_status") in ("BILLABLE_CONFIRMED", "INVOICED", "DISPUTED", "SETTLED")
        and v.get("billable_minutes") is not None
        and v["id"] != visit["id"]
    ]
    visit_start = db._parse_iso(visit.get("actual_start_at"))
    visit_created = db._parse_iso(visit.get("created_at"))

    prior_minutes = 0
    for v in all_visits:
        v_start = db._parse_iso(v.get("actual_start_at"))
        v_created = db._parse_iso(v.get("created_at"))
        if v_start and visit_start:
            if v_start < visit_start or (v_start == visit_start and v_created and visit_created and v_created < visit_created):
                prior_minutes += v.get("billable_minutes") or 0

    tier1_minutes = max(0, min(threshold - prior_minutes, billable_mins))
    tier2_minutes = billable_mins - tier1_minutes

    base_cents = round_half_up(tier1_minutes * rate1 / 60) + round_half_up(tier2_minutes * rate2 / 60)

    night = is_night_hour(visit.get("actual_start_at"))
    if night:
        result = round_half_up(base_cents * (1 + float(night_pct)))
    else:
        result = base_cents

    return result, night, billable_mins


def evaluate_visit_billing(visit, storm_event):
    """Evaluate billing_status for a visit after verification or completion."""
    if visit.get("execution_status") != "COMPLETED":
        if visit.get("billing_status") == "PENDING":
            visit["billing_status"] = "NON_BILLABLE"
            _touch(visit)
            db.visits.update(visit["id"], visit)
        return

    contract = db.contracts.get(visit.get("contract_id"))
    if not contract:
        return

    verified_acc = storm_event.get("verified_accumulation_inches")
    if verified_acc is None:
        return

    trigger = get_effective_trigger_depth(visit)
    if trigger is None:
        return

    if float(verified_acc) >= float(trigger):
        visit["billing_status"] = "BILLABLE_CONFIRMED"
        # Compute billable amount
        if contract.get("contract_type") == "PER_PUSH":
            rate = get_effective_per_push_rate(visit)
            visit["billable_amount_cents"] = rate or 0
        elif contract.get("contract_type") == "HOURLY":
            mins = compute_billable_minutes(visit)
            visit["billable_minutes"] = mins
            amount, night, _ = compute_hourly_charge(visit, contract)
            visit["billable_amount_cents"] = amount
            visit["night_premium_applied"] = night
        elif contract.get("contract_type") == "SEASONAL":
            visit["billable_amount_cents"] = 0
    else:
        visit["billing_status"] = "NON_BILLABLE"
        visit["billable_amount_cents"] = 0

    _touch(visit)
    db.visits.update(visit["id"], visit)


# --- Material cost recomputation ---

def recompute_visit_material_cost(visit_id):
    """Recompute material_cost_cents from RECORDED material rows."""
    visit = db.visits.get(visit_id)
    if not visit:
        return
    recorded = [m for m in db.materials.list_all() if m.get("visit_id") == visit_id and m.get("status") == "RECORDED"]
    visit["material_cost_cents"] = sum(m.get("line_cost_cents") or 0 for m in recorded)
    _touch(visit)
    db.visits.update(visit_id, visit)


# --- DRAFT invoice recomputation ---

def recompute_draft_invoices(contract_id=None, storm_event_id=None):
    """Recompute lines for DRAFT invoices matching criteria."""
    for inv in db.invoices.list_all():
        if inv.get("status") != "DRAFT":
            continue
        if contract_id and inv.get("contract_id") != contract_id:
            continue
        if storm_event_id and inv.get("storm_event_id") != storm_event_id:
            continue
        recompute_invoice_lines(inv)


def recompute_invoice_lines(invoice):
    """Recompute the lines of a DRAFT invoice."""
    contract_id = invoice.get("contract_id")
    kind = invoice.get("kind")

    eligible = []
    for v in db.visits.list_all():
        if v.get("contract_id") != contract_id:
            continue
        if v.get("billing_status") != "BILLABLE_CONFIRMED":
            continue
        if kind == "EVENT":
            if v.get("storm_event_id") != invoice.get("storm_event_id"):
                continue
        elif kind == "PERIOD":
            completed = db._parse_iso(v.get("completed_at"))
            p_start = db._parse_iso(invoice.get("period_start"))
            p_end = db._parse_iso(invoice.get("period_end"))
            if not completed or not p_start or not p_end:
                continue
            if not (p_start <= completed < p_end):
                continue
        eligible.append(v)

    lines = []
    for v in eligible:
        service_line = {
            "visit_id": v["id"],
            "line_type": "SERVICE",
            "line_cents": v.get("billable_amount_cents") or 0,
        }
        lines.append(service_line)
        mat_cost = v.get("material_cost_cents") or 0
        if mat_cost > 0:
            material_line = {
                "visit_id": v["id"],
                "line_type": "MATERIAL",
                "line_cents": mat_cost,
            }
            lines.append(material_line)

    invoice["lines"] = lines
    invoice["subtotal_cents"] = sum(l["line_cents"] for l in lines)
    invoice["total_cents"] = invoice["subtotal_cents"] - (invoice.get("credit_cents") or 0)
    _touch(invoice)
    db.invoices.update(invoice["id"], invoice)


# --- Season overlap check ---

def check_season_overlap(contract_id, site_id, exclude_contract_id=None):
    """Check if adding site to contract would create a season overlap with ACTIVE/SUSPENDED contracts."""
    contract = db.contracts.get(contract_id)
    if not contract:
        return False
    c_start = db._parse_iso(contract.get("season_start"))
    c_end = db._parse_iso(contract.get("season_end"))
    if not c_start or not c_end:
        return False

    for cs in db.contract_sites.list_all():
        if cs.get("site_id") != site_id:
            continue
        other_contract = db.contracts.get(cs.get("contract_id"))
        if not other_contract:
            continue
        if exclude_contract_id and other_contract["id"] == exclude_contract_id:
            continue
        if other_contract.get("status") not in ("ACTIVE", "SUSPENDED"):
            continue
        o_start = db._parse_iso(other_contract.get("season_start"))
        o_end = db._parse_iso(other_contract.get("season_end"))
        if not o_start or not o_end:
            continue
        # Closed interval overlap: they intersect if start1 <= end2 AND start2 <= end1
        if c_start <= o_end and o_start <= c_end:
            return True
    return False


# --- Coverage overlap check ---

def check_coverage_overlap(subcontractor_id, coverage_start, coverage_end, exclude_id=None):
    """Check half-open interval overlap for the same subcontractor."""
    cs_dt = db._parse_iso(coverage_start)
    ce_dt = db._parse_iso(coverage_end)
    if not cs_dt or not ce_dt:
        return False

    for ca in db.coverage_assignments.list_all():
        if ca.get("subcontractor_id") != subcontractor_id:
            continue
        if ca.get("status") not in ("CREATED", "ACTIVE"):
            continue
        if exclude_id and ca["id"] == exclude_id:
            continue
        o_start = db._parse_iso(ca.get("coverage_start"))
        o_end = db._parse_iso(ca.get("coverage_end"))
        if not o_start or not o_end:
            continue
        # Half-open [start, end) overlap: start1 < end2 AND start2 < end1
        if cs_dt < o_end and o_start < ce_dt:
            return True
    return False


# --- Reliability score ---

def compute_reliability_score(sub):
    released = sub.get("assignments_released_count") or 0
    failed = sub.get("assignments_failed_count") or 0
    denominator = max(1, released + failed)
    return int(100 * released / denominator)


def update_subcontractor_reliability(sub_id):
    sub = db.subcontractors.get(sub_id)
    if not sub:
        return
    sub["reliability_score"] = compute_reliability_score(sub)
    _touch(sub)
    db.subcontractors.update(sub_id, sub)


# --- Claim scoring ---

def compute_claim_scores(claim):
    """Compute score_standard and score_strict for a slip-fall claim."""
    site_id = claim.get("site_id")
    incident_at = db._parse_iso(claim.get("incident_at"))
    storm_event_id = claim.get("storm_event_id")

    # Find visits at this site under the linked storm event
    matching_visits = []
    if storm_event_id:
        for v in db.visits.list_all():
            if v.get("site_id") == site_id and v.get("storm_event_id") == storm_event_id:
                matching_visits.append(v)

    # Indicators
    has_before = False
    has_after = False
    material_logged = False
    response_within_target = True
    weather_verified = False

    for v in matching_visits:
        # Photos
        visit_photos = [p for p in db.photos.list_all() if p.get("visit_id") == v["id"]]
        for p in visit_photos:
            if p.get("phase") == "BEFORE" and p.get("review_status") == "ACCEPTED":
                has_before = True
            if p.get("phase") == "AFTER" and p.get("review_status") == "ACCEPTED":
                has_after = True
        # Materials
        visit_materials = [m for m in db.materials.list_all() if m.get("visit_id") == v["id"] and m.get("status") == "RECORDED"]
        if visit_materials:
            material_logged = True
        # SLA
        if v.get("sla_miss") is True:
            response_within_target = False

    if storm_event_id:
        event = db.storm_events.get(storm_event_id)
        if event and event.get("status") in ("VERIFIED", "CLOSED"):
            weather_verified = True

    # Weights
    W_STANDARD = {"before": 15, "after": 25, "material": 20, "timeliness": 20, "weather": 20}
    W_STRICT = {"before": 30, "after": 40, "material": 10, "timeliness": 10, "weather": 10}

    indicators = {
        "before": has_before,
        "after": has_after,
        "material": material_logged,
        "timeliness": response_within_target,
        "weather": weather_verified,
    }

    score_standard = sum(w for k, w in W_STANDARD.items() if indicators[k])
    score_strict = sum(w for k, w in W_STRICT.items() if indicators[k])

    return score_standard, score_strict, matching_visits
