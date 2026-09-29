"""The eight named calculations of the scaffold."""

from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

import clock
import constants as K
import db
from errors import fail
from validators import DIRECT_HEALTH_SIGNALS

REGULATED_CLASSES = ("CHD", "CHD_BY_INFERENCE")


# --------------------------------------------------------------- numeric tools

def round_half_up(frac, places):
    """Round an exact Fraction half-up to `places` decimals, returning a float."""
    scale = 10 ** places
    negative = frac < 0
    if negative:
        frac = -frac
    n = frac.numerator * scale
    d = frac.denominator
    q, r = divmod(n, d)
    if 2 * r >= d:
        q += 1
    if negative:
        q = -q
    return float(Decimal(q) / Decimal(scale))


def ceil_half(n):
    """ceil(0.5 * n) for a non-negative integer n."""
    return (n + 1) // 2


def add_days(instant, days):
    return instant + timedelta(days=days)


# ------------------------------------------------- calculations.chd_classification

def derivation_hops(parent_id, self_id=None):
    """Walk the derivation chain upward. Raises on a cycle or an over-deep chain."""
    if parent_id is None:
        return 0
    visited = set()
    if self_id:
        visited.add(self_id)
    hops = 0
    current = parent_id
    while current is not None:
        if current in visited:
            fail("ERR_INFERENCE_CYCLE")
        visited.add(current)
        hops += 1
        parent = db.get("data_elements", current)
        if parent is None:
            break
        current = parent.get("derived_from_element_id")
    if hops > K.MAX_INFERENCE_DEPTH:
        fail("ERR_INFERENCE_DEPTH_EXCEEDED")
    return hops


def _safe_depth(element):
    """Depth of a stored element, tolerant of malformed chains."""
    depth = 0
    visited = {element["id"]}
    current = element.get("derived_from_element_id")
    while current is not None and current not in visited:
        visited.add(current)
        depth += 1
        parent = db.get("data_elements", current)
        if parent is None:
            break
        current = parent.get("derived_from_element_id")
    return depth


def _classify_one(element, parent_class):
    if element.get("hipaa_flow_only") and element.get("source_kind") != "THIRD_PARTY":
        return "NON_CHD"
    if element.get("health_signal_kind") in DIRECT_HEALTH_SIGNALS:
        return "CHD"
    if element.get("health_signal_kind") == "PRECISE_LOCATION":
        return "CHD_BY_INFERENCE"
    if element.get("inference_depth", 0) == 0:
        return "NON_CHD"
    if parent_class in REGULATED_CLASSES:
        return "CHD_BY_INFERENCE"
    return "NON_CHD"


def reclassify_product(app_product_id):
    """Recompute inference_depth and chd_classification for every element of a
    product, regardless of status, in ascending depth then created_at order."""
    elements = [e for e in db.rows_of("data_elements")
                if e.get("app_product_id") == app_product_id]
    for element in elements:
        depth = _safe_depth(element)
        if element.get("inference_depth") != depth:
            element["inference_depth"] = depth
            db.touch(element)

    elements.sort(key=lambda e: (e.get("inference_depth", 0), e["created_at"], e["_seq"]))
    classes = {}
    for element in elements:
        parent_id = element.get("derived_from_element_id")
        parent_class = classes.get(parent_id)
        if parent_class is None and parent_id:
            parent = db.get("data_elements", parent_id)
            parent_class = parent.get("chd_classification") if parent else None
        result = _classify_one(element, parent_class)
        classes[element["id"]] = result
        if element.get("chd_classification") != result:
            element["chd_classification"] = result
            db.touch(element)


# ------------------------------------------ calculations.applicability_determination

def small_business_flag(product):
    return (product["consumer_count"] < K.SMALL_BUSINESS_CONSUMER_MAX
            and product["annual_revenue_cents"] < K.SMALL_BUSINESS_REVENUE_CENTS_MAX)


def applicability_determination(assessment, product):
    """Runs the four pinned steps and returns the computed field values."""
    # STEP 1 -- entity status from product inputs and the claim only.
    sbf = small_business_flag(product)
    ratio = product["hipaa_covered_transaction_ratio"]
    if not isinstance(ratio, Decimal):
        ratio = Decimal(str(ratio))
    claim = assessment["entity_status_claim"]
    covered = claim in ("COVERED_ENTITY", "BUSINESS_ASSOCIATE")
    if covered and ratio >= Decimal(K.HIPAA_ONLY_RATIO):
        determination = "HIPAA_ONLY"
    elif covered and ratio >= Decimal(K.DUAL_TRACK_RATIO):
        determination = "DUAL_TRACK"
    else:
        determination = "CHD_REGULATED"

    # STEP 2 -- classification, blind to the determination.
    reclassify_product(product["id"])

    # STEP 3 -- snapshots over ACTIVE elements only.
    active = [e for e in db.rows_of("data_elements")
              if e.get("app_product_id") == product["id"] and e.get("status") == "ACTIVE"]
    active_snapshot = len(active)
    regulated_snapshot = len(
        [e for e in active if e.get("chd_classification") in REGULATED_CLASSES])

    # STEP 4 -- scope and deadline from steps 1 and 3 only.
    deadline = None
    if determination == "HIPAA_ONLY":
        scope = "NONE"
    else:
        if regulated_snapshot == 0:
            scope = "NONE"
        elif regulated_snapshot >= ceil_half(active_snapshot):
            scope = "FULL"
        else:
            scope = "PARTIAL"
        deadline = K.SMALL_BUSINESS_DEADLINE if sbf else K.STANDARD_DEADLINE

    return {
        "small_business_flag": sbf,
        "determination": determination,
        "active_element_count_snapshot": active_snapshot,
        "regulated_element_count_snapshot": regulated_snapshot,
        "regulated_scope": scope,
        "compliance_deadline_date": deadline,
    }


# ------------------------------------------ calculations.policy_completeness_score

def policy_completeness_score(policy, product):
    if policy["specificity_mode"] == "ELEMENT_LEVEL":
        category_denominator = product.get("regulated_element_count", 0)
    else:
        category_denominator = K.REQUIRED_CATEGORY_COUNT
    purpose_denominator = len([p for p in db.db.processing_purposes.values()
                               if p.get("app_product_id") == policy["app_product_id"]])

    one = Fraction(1)
    if category_denominator == 0:
        category = one
    else:
        category = min(Fraction(policy["disclosed_category_count"], category_denominator), one)
    if purpose_denominator == 0:
        purpose = one
    else:
        purpose = min(Fraction(policy["disclosed_purpose_count"], purpose_denominator), one)
    if policy["disclosed_third_party_count"] == 0:
        third = one
    else:
        third = min(Fraction(policy["named_third_party_count"],
                             policy["disclosed_third_party_count"]), one)

    gap_count = len([c for c in (category, purpose, third) if c < one])
    total = 100 * (Fraction(40, 100) * category
                   + Fraction(35, 100) * purpose
                   + Fraction(25, 100) * third)
    return round_half_up(total, 1), gap_count


# ------------------------------------------------ calculations.residual_risk_score

_RISK_WEIGHTS = (
    ("admin_control_score", Fraction(30, 100)),
    ("technical_control_score", Fraction(35, 100)),
    ("physical_control_score", Fraction(10, 100)),
    ("vendor_oversight_score", Fraction(25, 100)),
)


def residual_risk_score(row):
    penalty = 1 + Fraction(*K.GAP_PENALTY_PER_GAP) * row["documented_gap_count"]
    if penalty > K.MAX_PENALTY_MULTIPLIER:
        penalty = Fraction(K.MAX_PENALTY_MULTIPLIER)
    total = Fraction(0)
    for field, weight in _RISK_WEIGHTS:
        total += (100 - row[field]) * penalty * weight
    score = round_half_up(total, 2)
    if score < K.TIER_MODERATE_MIN:
        tier = "LOW"
    elif score < K.TIER_HIGH_MIN:
        tier = "MODERATE"
    elif score < K.TIER_CRITICAL_MIN:
        tier = "HIGH"
    else:
        tier = "CRITICAL"
    return score, tier


# ------------------------------------------ calculations.breach_notification_deadline

def breach_deadlines(incident):
    """Returns the reportable-branch deadline values."""
    scope = incident["breach_scope"]
    discovered = incident["discovered_at"]
    health = add_days(discovered, K.HEALTH_RULE_DAYS) if scope in ("CHD_ONLY", "MIXED") else None
    general = (add_days(discovered, K.GENERAL_RULE_DAYS)
               if scope in ("GENERAL_PII_ONLY", "MIXED") else None)
    candidates = [d for d in (health, general) if d is not None]
    governing = min(candidates) if candidates else None
    return {
        "health_rule_deadline_at": health,
        "general_rule_deadline_at": general,
        "governing_deadline_at": governing,
        "media_notice_required": incident["affected_state_max_count"] >= K.MEDIA_NOTICE_THRESHOLD,
        "exposure_contribution_cents": (incident["affected_consumer_count"]
                                        * K.PER_CONSUMER_EXPOSURE_CENTS),
    }


# ------------------------------------------- calculations.request_response_deadline

def request_response_deadline(row):
    base = add_days(row["received_at"], K.RESPONSE_BASE_DAYS)
    extended = add_days(base, K.RESPONSE_EXTENSION_DAYS) if row.get("extension_granted") else base
    kind = row["request_kind"]
    if kind == "DELETE" and row.get("verified_at") is not None:
        return min(extended, add_days(row["verified_at"], K.DELETE_FULFILLMENT_DAYS))
    if kind == "CONFIRM":
        return min(extended, add_days(row["received_at"], K.CONFIRM_MAX_DAYS))
    return extended


# ------------------------------------------------ calculations.deletion_task_fanout

def deletion_task_fanout(consumer):
    """Returns [(vendor_row, hop_distance)] in creation order."""
    product_id = consumer["app_product_id"]
    direct = {}
    for mapping in db.rows_of("element_purpose_mappings"):
        if mapping.get("status") != "ACTIVE":
            continue
        if not mapping.get("regulated_flag"):
            continue
        vendor_id = mapping.get("vendor_id")
        if not vendor_id:
            continue
        purpose = db.get("processing_purposes", mapping.get("processing_purpose_id"))
        if purpose is None or purpose.get("activity_kind") not in ("SHARE", "SELL"):
            continue
        element = db.get("data_elements", mapping.get("data_element_id"))
        if element is None or element.get("app_product_id") != product_id:
            continue
        vendor = db.get("vendors", vendor_id)
        if vendor is None or vendor.get("agreement_state") != "EXECUTED":
            continue
        if vendor_id not in direct:
            direct[vendor_id] = 0

    hops = dict(direct)
    frontier = list(direct.keys())
    while frontier:
        nxt = []
        for vendor_id in frontier:
            depth = hops[vendor_id]
            if depth >= K.MAX_FLOW_DOWN_HOPS:
                continue
            vendor = db.get("vendors", vendor_id)
            if vendor is None or not vendor.get("flow_down_clause"):
                continue
            children = [v for v in db.rows_of("vendors")
                        if v.get("subprocessor_of_id") == vendor_id
                        and v.get("agreement_state") == "EXECUTED"]
            for child in children:
                candidate = depth + 1
                if child["id"] not in hops or candidate < hops[child["id"]]:
                    hops[child["id"]] = candidate
                    nxt.append(child["id"])
        frontier = nxt

    selected = []
    for vendor_id, depth in hops.items():
        vendor = db.get("vendors", vendor_id)
        if vendor is not None:
            selected.append((vendor, depth))
    selected.sort(key=lambda pair: (pair[1], pair[0]["created_at"], pair[0]["_seq"]))
    return selected


# ---------------------------------------------------- calculations.geofence_standoff

def zone_prohibition_rule(state_code, facility_kind):
    law = K.GEOFENCE_LAW_BY_STATE.get(state_code, "PERMITTED")
    if law == "PROHIBITED_ALL":
        if facility_kind in ("SENSITIVE_HEALTH", "GENERAL_HEALTH"):
            return "PROHIBITED_ALL"
        return "PERMITTED"
    if law == "PROHIBITED_SENSITIVE_ONLY":
        if facility_kind == "SENSITIVE_HEALTH":
            return "PROHIBITED_ALL"
        if facility_kind == "GENERAL_HEALTH":
            return "PROHIBITED_SENSITIVE_ONLY"
        return "PERMITTED"
    return "PERMITTED"


def zone_min_standoff(prohibition_rule):
    if prohibition_rule == "PROHIBITED_SENSITIVE_ONLY":
        return K.SENSITIVE_STANDOFF_METERS
    return 0


def campaign_standoff(distance_to_zone_center_meters, target_radius_meters, zone_radius_meters):
    return distance_to_zone_center_meters - target_radius_meters - zone_radius_meters


def intervals_touch(start_a, end_a, start_b, end_b):
    """Closed-interval overlap: touching endpoints collide."""
    return start_a <= end_b and start_b <= end_a


def within_cooldown(last_activated_at):
    if last_activated_at is None:
        return False
    elapsed = clock.now() - last_activated_at
    return elapsed < timedelta(hours=K.ZONE_COOLDOWN_HOURS)
