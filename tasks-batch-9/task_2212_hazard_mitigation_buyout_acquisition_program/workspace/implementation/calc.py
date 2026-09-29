"""The thirteen calculations and the project's derived-total reconciliation sweeps."""
from datetime import timedelta
from decimal import Decimal

import store
from core import D, add_days, add_months, fmt_date, parse_date, parse_datetime, rhu, rhu_int


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------

def project_parcels(project_id):
    return [p for p in store.parcels.values() if p["project_id"] == project_id]


def project_parcel_ids(project_id):
    return {p["id"] for p in store.parcels.values() if p["project_id"] == project_id}


def parcel_project(parcel):
    return store.projects.get(parcel["project_id"]) if parcel else None


def parcel_offers(parcel_id):
    return [o for o in store.offers.values() if o["parcel_id"] == parcel_id]


def parcel_cases(parcel_id):
    return [c for c in store.cases.values() if c["parcel_id"] == parcel_id]


def parcel_restrictions(parcel_id):
    return [r for r in store.restrictions.values() if r["parcel_id"] == parcel_id]


def project_restrictions(project_id):
    ids = project_parcel_ids(project_id)
    return [r for r in store.restrictions.values() if r["parcel_id"] in ids]


def work_order_children(work_order_id):
    return [d for d in store.disconnections.values() if d["work_order_id"] == work_order_id]


def contractor_work_orders(contractor_id):
    return [w for w in store.work_orders.values() if w["contractor_id"] == contractor_id]


# --------------------------------------------------------------------------
# 1. benefit_cost_ratio (dual variant)
# --------------------------------------------------------------------------

def benefit_cost_ratio(analysis_method, annualized_loss_avoided_cents,
                       project_useful_life_years, discount_rate_pct, mitigation_cost_cents):
    if analysis_method == "FEMA_BCA_TOOLKIT":
        r = D(discount_rate_pct)
        n = int(project_useful_life_years)
        raw = (Decimal(1) - (Decimal(1) + r) ** Decimal(-n)) / r
        factor = rhu(raw, 6)
        npv = rhu_int(D(annualized_loss_avoided_cents) * factor)
    else:
        factor = rhu(Decimal(0), 6)
        npv = int(annualized_loss_avoided_cents) * int(project_useful_life_years)
    bcr = rhu(D(npv) / D(mitigation_cost_cents), 3)
    return factor, npv, bcr


# --------------------------------------------------------------------------
# 2 + 3. relocation benefits
# --------------------------------------------------------------------------

def replacement_housing_payment(case, acquisition_price_cents):
    if case["rhp_method"] == "COMPARABLE_DWELLING":
        replacement = int(case.get("comparable_dwelling_price_cents") or 0)
    else:
        replacement = int(case.get("actual_purchase_price_cents") or 0)
    gap = replacement - int(acquisition_price_cents)
    if gap < 0:
        gap = 0
    if case["displacee_type"] == "OWNER_OCCUPANT":
        return min(gap, store.RHP_OWNER_CAP_CENTS)
    return 0


def rental_assistance(case):
    months = store.MAX_RENTAL_ASSISTANCE_MONTHS if case["displacee_type"] == "TENANT_90_DAY" else 0
    start = parse_date(case["rental_assistance_start_date"])
    end_date = fmt_date(add_months(start, months))
    current = int(case.get("current_rent_cents") or 0) + int(case.get("current_utility_cents") or 0)
    ability = rhu_int(D(case.get("monthly_gross_income_cents") or 0) * store.INCOME_RENT_RATIO)
    base = min(current, ability)
    comparable = int(case.get("comparable_rent_cents") or 0) + int(case.get("comparable_utility_cents") or 0)
    differential = comparable - base
    if differential < 0:
        differential = 0
    uncapped = differential * months
    amount = min(uncapped, store.RENTAL_ASSISTANCE_CAP_CENTS)
    return months, end_date, amount


def relocation_benefits(case, acquisition_price_cents):
    rhp = replacement_housing_payment(case, acquisition_price_cents)
    months, end_date, rental = rental_assistance(case)
    total = rhp + rental + int(case.get("moving_expense_cents") or 0)
    return {
        "acquisition_price_cents": int(acquisition_price_cents),
        "rental_assistance_months": months,
        "rental_assistance_end_date": end_date,
        "replacement_housing_payment_cents": rhp,
        "rental_assistance_cents": rental,
        "total_relocation_benefit_cents": total,
    }


def case_interval(case, projected=False):
    """Half-open [start, end) of the case's rental-assistance occupation.

    ``rental_assistance_end_date`` is the exclusive upper bound of the interval, so a
    case that still carries a null end date occupies no interval at all and None is
    returned.  ``projected=True`` derives the interval the case is about to take on.
    """
    start = parse_date(case["rental_assistance_start_date"])
    end_raw = case.get("rental_assistance_end_date")
    if end_raw:
        return start, parse_date(end_raw)
    if not projected:
        return None
    months = store.MAX_RENTAL_ASSISTANCE_MONTHS if case["displacee_type"] == "TENANT_90_DAY" else 0
    return start, add_months(start, months)


# --------------------------------------------------------------------------
# 4. dob_deduction_total
# --------------------------------------------------------------------------

def dob_record_deductible(record):
    net = int(record["amount_cents"]) - int(record.get("repair_documented_cents") or 0)
    if net < 0:
        net = 0
    factor = store.DOB_SOURCE_FACTORS[record["benefit_source"]]
    return rhu_int(D(net) * factor)


def dob_sweep_order(records):
    return sorted(records, key=lambda r: (r["received_on"], r["created_at"], r["_seq"]))


def recompute_dob_total(parcel):
    active = [r for r in store.dob_records.values()
              if r["parcel_id"] == parcel["id"] and r["status"] == "ACTIVE"]
    total = 0
    for record in dob_sweep_order(active):
        record["deductible_cents"] = dob_record_deductible(record)
        total += record["deductible_cents"]
    parcel["dob_deduction_total_cents"] = total
    return total


# --------------------------------------------------------------------------
# 5. net_offer_amount
# --------------------------------------------------------------------------

def incentive_rate(pre_incentive_net_cents, occupancy_type):
    if occupancy_type != "OWNER_OCCUPIED":
        return Decimal("0")
    if pre_incentive_net_cents < 10000000:
        return Decimal("0.10")
    if pre_incentive_net_cents < 25000000:
        return Decimal("0.07")
    return Decimal("0.05")


def net_offer_amount(parcel, appraisal):
    base = int(appraisal["indicated_value_cents"])
    dob = int(parcel["dob_deduction_total_cents"])
    pre = base - dob
    if pre < 0:
        pre = 0
    rate = incentive_rate(pre, parcel["occupancy_type"])
    incentive = min(rhu_int(D(pre) * rate), store.INCENTIVE_CAP_CENTS)
    return {
        "base_value_cents": base,
        "dob_deduction_cents": dob,
        "pre_incentive_net_cents": pre,
        "incentive_cents": incentive,
        "net_offer_cents": pre + incentive,
    }


# --------------------------------------------------------------------------
# 6. neighborhood viability family
# --------------------------------------------------------------------------

def recompute_participating(project):
    counted = ("NOT_CONTACTED", "INTERESTED", "VOLUNTARY_CONFIRMED", "DECLINED")
    project["participating_parcel_count"] = sum(
        1 for p in project_parcels(project["id"]) if p["participation_status"] in counted
    )


def recompute_holdout(project):
    project["holdout_parcel_count"] = sum(
        1 for p in project_parcels(project["id"]) if p["participation_status"] == "DECLINED"
    )


def recompute_components(project):
    nodes = store.by_created([
        p for p in project_parcels(project["id"])
        if p["acquisition_status"] in store.ACQUIRED_ACQUISITION
    ])
    node_ids = {p["id"] for p in nodes}
    if not nodes:
        project["contiguous_open_space_parcel_count"] = 0
        project["largest_component_parcel_ids"] = []
        return
    adjacency = {p["id"]: set() for p in nodes}
    for edge in store.adjacencies.values():
        if edge["project_id"] != project["id"]:
            continue
        a, b = edge["parcel_a_id"], edge["parcel_b_id"]
        if a in node_ids and b in node_ids:
            adjacency[a].add(b)
            adjacency[b].add(a)

    order = {p["id"]: idx for idx, p in enumerate(nodes)}
    seen = set()
    components = []
    for parcel in nodes:
        if parcel["id"] in seen:
            continue
        stack = [parcel["id"]]
        members = []
        seen.add(parcel["id"])
        while stack:
            current = stack.pop()
            members.append(current)
            for nb in adjacency[current]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        members.sort(key=lambda pid: order[pid])
        components.append(members)

    best = None
    for members in components:
        key = (-len(members), order[members[0]])
        if best is None or key < best[0]:
            best = (key, members)
    winner = best[1]
    project["contiguous_open_space_parcel_count"] = len(winner)
    project["largest_component_parcel_ids"] = list(winner)


def recompute_ratio_only(project):
    denominator = int(project["participating_parcel_count"])
    count = int(project["contiguous_open_space_parcel_count"])
    if denominator == 0:
        ratio = rhu(Decimal(0), 4)
    else:
        ratio = rhu(D(count) / D(denominator), 4)
    project["neighborhood_viability_ratio"] = ratio


def recompute_status_only(project):
    ratio = project["neighborhood_viability_ratio"]
    if ratio >= store.VIABILITY_VIABLE_MIN:
        project["viability_status"] = "VIABLE"
    elif ratio >= store.VIABILITY_AT_RISK_MIN:
        project["viability_status"] = "AT_RISK"
    else:
        project["viability_status"] = "NONVIABLE"


def recompute_ratio(project):
    recompute_ratio_only(project)
    recompute_status_only(project)


def recompute_viability_full(project):
    recompute_participating(project)
    recompute_holdout(project)
    recompute_components(project)
    recompute_ratio(project)


# --------------------------------------------------------------------------
# 7. program income federal share + balance
# --------------------------------------------------------------------------

def program_income_federal_share(entry_type, amount_cents, cost_share_federal_pct):
    sign = -1 if entry_type == "EXPENDITURE" else 1
    magnitude = rhu_int(D(amount_cents) * D(cost_share_federal_pct))
    return sign * magnitude


def ledger_order(entries):
    return sorted(entries, key=lambda e: (e["posted_on"], e["created_at"], e["_seq"]))


def recompute_program_income_balance(project):
    active = [e for e in store.ledger.values()
              if e["project_id"] == project["id"] and e["status"] == "ACTIVE"]
    balance = 0
    for entry in ledger_order(active):
        balance += int(entry["federal_share_cents"])
    project["program_income_balance_cents"] = balance
    return balance


# --------------------------------------------------------------------------
# 8. federal obligation ledger
# --------------------------------------------------------------------------

def federal_item(amount_cents, cost_share_federal_pct):
    return rhu_int(D(amount_cents) * D(cost_share_federal_pct))


def compute_federal_obligated(project):
    pct = project["cost_share_federal_pct"]
    parcel_ids = project_parcel_ids(project["id"])
    total = 0
    group1 = [o for o in store.offers.values()
              if o["parcel_id"] in parcel_ids and o["status"] in ("PRESENTED", "ACCEPTED")]
    for offer in store.by_created(group1):
        total += federal_item(offer["net_offer_cents"], pct)
    group2 = [c for c in store.closings.values()
              if c["parcel_id"] in parcel_ids and c["status"] in ("FUNDED", "RECORDED")]
    for closing in store.by_created(group2):
        total += federal_item(closing["settlement_cost_cents"], pct)
    group3 = [c for c in store.cases.values()
              if c["parcel_id"] in parcel_ids and c["status"] == "CLAIM_PAID"]
    for case in store.by_created(group3):
        total += federal_item(case["total_relocation_benefit_cents"], pct)
    return total


def recompute_federal_obligated(project):
    project["federal_obligated_cents"] = compute_federal_obligated(project)
    return project["federal_obligated_cents"]


# --------------------------------------------------------------------------
# 9. protected open space acreage
# --------------------------------------------------------------------------

def recompute_protected_acres(project):
    total = Decimal(0)
    for parcel in store.by_created(project_parcels(project["id"])):
        if parcel["acquisition_status"] != "OPEN_SPACE_RECORDED":
            continue
        rows = parcel_restrictions(parcel["id"])
        if not rows:
            continue
        if all(r["status"] == "TERMINATED" for r in rows):
            continue
        total += D(parcel["acreage"])
    project["protected_open_space_acres"] = rhu(total, 2)
    return project["protected_open_space_acres"]


# --------------------------------------------------------------------------
# 10. debris diversion
# --------------------------------------------------------------------------

def debris_diversion_pct(total_debris_tons, recycled_tons):
    total = D(total_debris_tons)
    if total == 0:
        return rhu(Decimal(0), 2)
    return rhu(D(recycled_tons) / total * Decimal(100), 2)


# --------------------------------------------------------------------------
# 11. monitoring schedule
# --------------------------------------------------------------------------

def next_monitoring_due(anchor_date):
    return fmt_date(add_months(anchor_date, store.MONITORING_INTERVAL_MONTHS))


def corrective_deadline(inspection_date):
    return fmt_date(add_days(inspection_date, store.CURE_WINDOW_DAYS))


def restriction_overdue(restriction, today):
    if restriction["status"] not in ("RECORDED", "IN_COMPLIANCE", "CURED"):
        return False
    due = parse_date(restriction.get("next_monitoring_due_date") or "")
    if due is None:
        return False
    return due < today


# --------------------------------------------------------------------------
# 12. appraisal validity window
# --------------------------------------------------------------------------

def validity_end(effective_date):
    return fmt_date(add_months(effective_date, store.APPRAISAL_VALIDITY_MONTHS))


def appraisal_window_overlap(appraisal, effective_date, end_date):
    """True when another INITIAL peer on the same parcel overlaps (half-open, strict)."""
    for peer in store.appraisals.values():
        if peer["id"] == appraisal["id"]:
            continue
        if peer["parcel_id"] != appraisal["parcel_id"]:
            continue
        if peer["appraisal_type"] != "INITIAL":
            continue
        if peer["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        peer_start = parse_date(peer["effective_date"])
        peer_end = parse_date(peer.get("validity_end_date") or "")
        if peer_start is None or peer_end is None:
            continue
        if effective_date < peer_end and peer_start < end_date:
            return True
    return False


# --------------------------------------------------------------------------
# 13. demolition buffered window
# --------------------------------------------------------------------------

def buffered_window(scheduled_start, scheduled_end):
    return (scheduled_start - timedelta(hours=store.DEMOLITION_BUFFER_HOURS),
            scheduled_end + timedelta(hours=store.DEMOLITION_BUFFER_HOURS))


def buffered_conflicts(contractor_id, buffered_start, buffered_end, exclude_id=None):
    count = 0
    for order in contractor_work_orders(contractor_id):
        if order["id"] == exclude_id:
            continue
        if order["status"] not in store.ACTIVE_WORK_ORDER_STATUSES:
            continue
        other_start = parse_datetime(order["buffered_start"])
        other_end = parse_datetime(order["buffered_end"])
        if buffered_start <= other_end and other_start <= buffered_end:
            count += 1
    return count


def recompute_active_work_orders(contractor):
    contractor["active_work_order_count"] = sum(
        1 for w in contractor_work_orders(contractor["id"])
        if w["status"] in store.ACTIVE_WORK_ORDER_STATUSES
    )


# --------------------------------------------------------------------------
# Work order utility readiness
# --------------------------------------------------------------------------

def recompute_confirmed_utilities(work_order):
    children = store.by_created([
        d for d in work_order_children(work_order["id"]) if d["status"] == "CONFIRMED"
    ])
    work_order["confirmed_utility_types"] = [d["utility_type"] for d in children]
    return work_order["confirmed_utility_types"]


def utilities_complete(work_order):
    confirmed = set(work_order.get("confirmed_utility_types") or [])
    return all(t in confirmed for t in work_order.get("required_utility_types") or [])
