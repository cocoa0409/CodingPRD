"""The eighteen calculations of PRD section 3.

Money is integer cents throughout. Every rounding step uses half-up on an exact
Decimal, never binary floating point and never banker's rounding.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

COVERAGE_BUFFER_DAYS = 7
MAX_RETEST_ROUNDS = 3
SAMPLE_UNIT_CEILING = 40
INITIAL_VOLUME_DIVISOR = 2500
PERIODIC_VOLUME_DIVISOR = 5000

INDEPENDENCE_MULTIPLIER = {
    "INDEPENDENT": Decimal("1.00"),
    "FIREWALLED_GOVERNMENT": Decimal("1.05"),
    "MANUFACTURER_OWNED": Decimal("1.20"),
}

OPEN_CASE_STATES_FOR_SCORE = (
    "OPEN",
    "STOP_DISTRIBUTION_ISSUED",
    "RETEST_ORDERED",
    "RETEST_FAILED",
)

POSTURE_SUSPENDING_CASE_STATES = (
    "OPEN",
    "STOP_DISTRIBUTION_ISSUED",
    "RETEST_FAILED",
    "ESCALATED_RECALL",
)

COMMITTING_ORDER_STATES = (
    "SCHEDULED",
    "IN_TESTING",
    "REPORTED_PASS",
    "REPORTED_FAIL",
)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------
# 1. applicable_rule_set_derivation
# --------------------------------------------------------------------------

def _condition_holds(condition, parts):
    if condition == "ALWAYS":
        return True
    if condition == "IF_PAINTED_SURFACE":
        return any(p["material_class"] == "PAINTED_COATING" for p in parts)
    if condition == "IF_PLASTICIZED_PART":
        return any(p["material_class"] == "PLASTICIZED_PLASTIC" for p in parts)
    if condition == "IF_SMALL_PART_PRESENT":
        return any(p["small_part_when_detached"] for p in parts)
    if condition == "IF_ACCESSIBLE_METAL":
        return any(
            p["material_class"] == "ACCESSIBLE_METAL" and p["accessible_to_child"]
            for p in parts
        )
    return False


def derive_required_rule_ids(product):
    """Ordered rule id list: severity_weight DESC then rule_code ASC."""
    now = clock.now()
    candidates = []
    for mapping in db.all_rows("category_rule_mappings"):
        if mapping["category_id"] != product["category_id"]:
            continue
        if mapping["mapping_state"] != "ACTIVE":
            continue
        if mapping["effective_from"] > now:
            continue
        rule = db.get("applicable_rules", mapping["rule_id"])
        if rule is None:
            continue
        candidates.append((mapping, rule))
    candidates.sort(key=lambda pair: (-pair[1]["severity_weight"], pair[1]["rule_code"]))
    parts = db.find("component_parts", product_id=product["id"])
    out = []
    for mapping, rule in candidates:
        if not _condition_holds(mapping["applicability_condition"], parts):
            continue
        if rule["id"] not in out:
            out.append(rule["id"])
    return out


# --------------------------------------------------------------------------
# 2. sampling_plan_required_sample_size
# --------------------------------------------------------------------------

def sampling_plan_units_authorized(product, category, plan):
    rule_count = len(product["required_rule_ids"])
    if plan["plan_type"] == "INITIAL":
        volume = math.ceil(product["projected_annual_units"] / INITIAL_VOLUME_DIVISOR)
        raw = (3 + volume) * rule_count
    else:
        volume = plan["baseline_units_produced"] // PERIODIC_VOLUME_DIVISOR
        raw = (1 + volume) * rule_count
    if category["durable_infant_product"]:
        raw *= 2
    return min(SAMPLE_UNIT_CEILING, max(category["sampling_floor_units"], raw))


# --------------------------------------------------------------------------
# 3. lab_test_line_fee_cents
# --------------------------------------------------------------------------

def line_fee_cents(rule, laboratory, accreditation, sample_count):
    surcharge_bp = accreditation["fee_surcharge_basis_points"] if accreditation else 0
    multiplier = INDEPENDENCE_MULTIPLIER[laboratory["independence_class"]]
    per_sample = _dec(rule["base_method_fee_cents"]) * (
        Decimal(1) + _dec(surcharge_bp) / Decimal(10000)
    ) * multiplier
    per_sample_cents = round_half_up(per_sample)
    return per_sample_cents * sample_count


# --------------------------------------------------------------------------
# 4. test_order_invoice_total_cents
# --------------------------------------------------------------------------

def _expedite_basis_points(subtotal):
    if subtotal <= 50000:
        return 1500
    if subtotal <= 150000:
        return 1000
    return 600


def _reliance_discount_basis_points(total_before_discount):
    if total_before_discount >= 120000:
        return 1200
    if total_before_discount >= 60000:
        return 800
    return 0


def invoice_total_cents(line_fee, expedite_requested, evidence_path):
    subtotal = line_fee
    expedite_fee = 0
    if expedite_requested:
        bp = _expedite_basis_points(subtotal)
        expedite_fee = round_half_up(_dec(subtotal) * _dec(bp) / Decimal(10000))
    total_before_discount = subtotal + expedite_fee
    discount = 0
    if evidence_path == "COMPONENT_RELIANCE":
        bp = _reliance_discount_basis_points(total_before_discount)
        if bp:
            discount = round_half_up(
                _dec(total_before_discount) * _dec(bp) / Decimal(10000)
            )
    return total_before_discount - discount


# --------------------------------------------------------------------------
# 5. product_risk_weighted_gap_score
# --------------------------------------------------------------------------

def _rule_covered(product, rule_id):
    if product["evidence_path"] == "FULL_PRODUCT_TEST":
        for order in db.all_rows("test_orders"):
            if (
                order["product_id"] == product["id"]
                and order["rule_id"] == rule_id
                and order["order_state"] == "REPORTED_PASS"
            ):
                return True
        return False
    if product["evidence_path"] == "COMPONENT_RELIANCE":
        part_ids = {p["id"] for p in db.find("component_parts", product_id=product["id"])}
        for cert in db.all_rows("component_part_certificates"):
            if (
                cert["rule_id"] == rule_id
                and cert["reliance_state"] == "RELIED_UPON"
                and cert["component_part_id"] in part_ids
            ):
                return True
        return False
    return False


def risk_weighted_gap_score(product):
    total_weight = 0
    uncovered_weight = 0
    for rule_id in product["required_rule_ids"]:
        rule = db.get("applicable_rules", rule_id)
        if rule is None:
            continue
        weight = rule["severity_weight"]
        total_weight += weight
        if not _rule_covered(product, rule_id):
            uncovered_weight += weight
    if total_weight == 0:
        score = 100
    else:
        score = round_half_up(
            Decimal(100) * _dec(uncovered_weight) / _dec(total_weight)
        )
    open_cases = [
        c
        for c in db.find("noncompliance_cases", product_id=product["id"])
        if c["case_state"] in OPEN_CASE_STATES_FOR_SCORE
    ]
    resample_plans = [
        p
        for p in db.find("sampling_plans", product_id=product["id"])
        if p["plan_state"] == "RESAMPLE_DUE"
    ]
    score += 15 * len(open_cases)
    score += 10 * len(resample_plans)
    return max(0, min(100, score))


# --------------------------------------------------------------------------
# 6. product_compliance_posture
# --------------------------------------------------------------------------

def compliance_posture(product):
    if product["certification_state"] in ("DRAFT", "ARCHIVED"):
        return "UNSCOPED"
    cases = db.find("noncompliance_cases", product_id=product["id"])
    if any(c["case_state"] in POSTURE_SUSPENDING_CASE_STATES for c in cases):
        return "SUSPENDED"
    plans = db.find("sampling_plans", product_id=product["id"])
    if any(p["plan_state"] == "LAPSED" for p in plans):
        return "SUSPENDED"
    if product["risk_weighted_gap_score"] == 0:
        return "CLEARED"
    return "RESTRICTED"


# --------------------------------------------------------------------------
# 7. noncompliance_corrective_scope_units
# --------------------------------------------------------------------------

def corrective_scope_units(product, case, failing_order, scope_variant):
    if scope_variant == "BATCH_SCOPED":
        cutoff = failing_order["window_start"]
    else:
        cutoff = None
        for order in db.all_rows("test_orders"):
            if (
                order["product_id"] == product["id"]
                and order["rule_id"] == case["failed_rule_id"]
                and order["order_state"] == "REPORTED_PASS"
                and order["reported_at"] is not None
                and failing_order["reported_at"] is not None
                and order["reported_at"] < failing_order["reported_at"]
            ):
                if cutoff is None or order["reported_at"] > cutoff:
                    cutoff = order["reported_at"]
        if cutoff is None:
            cutoff = product["created_at"]
    total = 0
    for batch in db.find("production_batches", product_id=product["id"]):
        if batch["distribution_state"] == "DESTROYED":
            continue
        if batch["produced_on"] >= cutoff:
            total += batch["quantity"]
    return total


# --------------------------------------------------------------------------
# 8. periodic_retest_due_date
# --------------------------------------------------------------------------

def periodic_due_at(product, last_verified_at):
    if not product["required_rule_ids"] or last_verified_at is None:
        return None
    intervals = []
    for rule_id in product["required_rule_ids"]:
        rule = db.get("applicable_rules", rule_id)
        if rule is not None:
            intervals.append(rule["periodic_interval_months"])
    if not intervals:
        return None
    return clock.add_calendar_months(last_verified_at, min(intervals))


# --------------------------------------------------------------------------
# 9. laboratory_slot_overlap_check
# --------------------------------------------------------------------------

def peak_concurrency(laboratory_id, window_start, window_end, exclude_order_id=None):
    existing = []
    for order in db.all_rows("test_orders"):
        if order["laboratory_id"] != laboratory_id:
            continue
        if order["order_state"] not in ("SCHEDULED", "IN_TESTING"):
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        existing.append(order)
    breakpoints = [window_start]
    for order in existing:
        if window_start <= order["window_start"] < window_end:
            breakpoints.append(order["window_start"])
    peak = 0
    for point in breakpoints:
        count = 1
        for order in existing:
            if order["window_start"] <= point < order["window_end"]:
                count += 1
        peak = max(peak, count)
    return peak


def slot_capacity_exceeded(laboratory, window_start, window_end):
    peak = peak_concurrency(laboratory["id"], window_start, window_end)
    return peak > laboratory["concurrent_slot_capacity"]


# --------------------------------------------------------------------------
# 10. component_certificate_coverage_overlap_check
# --------------------------------------------------------------------------

def coverage_collides(component_part_id, rule_id, coverage_from, coverage_through):
    for cert in db.all_rows("component_part_certificates"):
        if cert["component_part_id"] != component_part_id:
            continue
        if cert["rule_id"] != rule_id:
            continue
        if cert["reliance_state"] not in ("SUBMITTED", "RELIED_UPON"):
            continue
        buffered_through = clock.add_days(cert["coverage_through"], COVERAGE_BUFFER_DAYS)
        buffered_from = clock.add_days(cert["coverage_from"], -COVERAGE_BUFFER_DAYS)
        if coverage_from <= buffered_through and buffered_from <= coverage_through:
            return True
    return False


# --------------------------------------------------------------------------
# 11. test_result_decision
# --------------------------------------------------------------------------

def test_result(rule, measured_value):
    limit = _dec(rule["limit_value"])
    measured = _dec(measured_value)
    if rule["limit_comparator"] == "AT_OR_BELOW":
        return "PASS" if measured <= limit else "FAIL"
    return "PASS" if measured >= limit else "FAIL"


# --------------------------------------------------------------------------
# 12. certificate_content_completeness
# --------------------------------------------------------------------------

def content_completeness_pct(certificate, product):
    from validation import RE_MONTH

    satisfied = 0
    if (certificate["certifier_legal_name"] or "").strip():
        satisfied += 1
    if "@" in (certificate["certifier_contact_email"] or ""):
        satisfied += 1
    if (certificate["manufacture_place"] or "").strip():
        satisfied += 1
    if RE_MONTH.match(certificate["manufacture_date_month"] or ""):
        satisfied += 1
    if (certificate["testing_place"] or "").strip():
        satisfied += 1
    cited = certificate["cited_rule_ids"]
    if cited and set(cited) == set(product["required_rule_ids"]):
        satisfied += 1
    if certificate["cited_evidence_count"] >= len(cited):
        satisfied += 1
    return int(math.floor(100 * satisfied / 7))


# --------------------------------------------------------------------------
# 13. tracking_label_compliance_flag
# --------------------------------------------------------------------------

def tracking_label_compliant(batch, product):
    from validation import RE_BATCH_CODE

    return bool(
        batch["label_on_product"]
        and batch["label_on_packaging"]
        and batch["label_batch_code_printed"]
        and RE_BATCH_CODE.match(batch["batch_code"] or "")
        and (product["manufacture_site_code"] or "").strip()
    )


# --------------------------------------------------------------------------
# 14. material_change_resample_decision
# --------------------------------------------------------------------------

def triggers_resample(change_kind):
    return change_kind != "PACKAGING_ONLY"


# --------------------------------------------------------------------------
# 15. retest_round_threshold_decision
# --------------------------------------------------------------------------

def retest_threshold_reached(case):
    return case["retest_round_count"] >= MAX_RETEST_ROUNDS


# --------------------------------------------------------------------------
# 16. sample_unit_ledger
# --------------------------------------------------------------------------

def plan_units_committed(plan):
    total = 0
    for order in db.all_rows("test_orders"):
        if order["sampling_plan_id"] != plan["id"]:
            continue
        if order["order_state"] in COMMITTING_ORDER_STATES:
            total += order["sample_count"]
    return total


def recompute_plan_ledger(plan):
    plan["units_committed"] = plan_units_committed(plan)
    plan["units_available"] = plan["units_authorized"] - plan["units_committed"]
    return plan


# --------------------------------------------------------------------------
# 17. distribution_unit_ledger
# --------------------------------------------------------------------------

DISTRIBUTION_BUCKET = {
    "HELD": "units_held",
    "RELEASED": "units_released",
    "STOP_DISTRIBUTION": "units_stopped",
    "DESTROYED": "units_destroyed",
}


def recompute_distribution_ledger(product):
    buckets = {"units_held": 0, "units_released": 0, "units_stopped": 0,
               "units_destroyed": 0}
    for batch in db.find("production_batches", product_id=product["id"]):
        buckets[DISTRIBUTION_BUCKET[batch["distribution_state"]]] += batch["quantity"]
    product.update(buckets)
    return product


# --------------------------------------------------------------------------
# 18. laboratory_fee_ledger
# --------------------------------------------------------------------------

def laboratory_outstanding_fees(laboratory):
    total = 0
    for order in db.all_rows("test_orders"):
        if order["laboratory_id"] != laboratory["id"]:
            continue
        if order["order_state"] in COMMITTING_ORDER_STATES:
            total += order["invoice_total_cents"]
    return total
