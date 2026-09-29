"""Tier selection, cost-plus markup, deviated overrides, service fees and
substitute selection (SCAFFOLD calculations contract_line_price,
out_of_market_service_fee, deviated_price_resolution, substitute_selection)."""

import errors
from errors import fail
from db import db, values
from util import cents, closed_contains, dec, half_open_contains, pct

# --- constants (SCAFFOLD 1.3) ----------------------------------------------
FEE_WAIVER_EXTENDED_THRESHOLD_CENTS = 500000
MANUFACTURER_FUNDING_SHARE_PCT = 60
MAJOR_CHANGE_PCT = dec("10.00")
MINOR_NOTICE_DAYS = 7
AUDIT_TOLERANCE_PCT = dec("0.50")
CONTRACT_MINIMUM_COMPLIANCE_PCT = dec("80.00")
DEVIATION_BREACH_POSTURE_LIMIT = 1
MAX_REVISION_ROUNDS = 3
DC_COVERAGE_BUFFER_DAYS = 14
NOTICE_WINDOW_DAYS = 30

COST_FIELD = {
    "LAST_COST": "last_cost_cents",
    "AVG_COST": "avg_cost_cents",
    "REPLACEMENT_COST": "replacement_cost_cents",
}

PRICING_ACTIVE_STATUSES = ("DRAFT_PRICED", "INVOICED", "REPRICED")


def product_of(line):
    return db.products[line["product_id"]]


def class_of(product_id):
    return db.products[product_id]["product_class_code"]


def cost_on_basis(product, cost_basis):
    return product.get(COST_FIELD[cost_basis])


# --- tier selection ---------------------------------------------------------

def active_tiers(contract_id, product_class_code):
    return [t for t in values(db.contract_tiers)
            if t["contract_id"] == contract_id
            and t["product_class_code"] == product_class_code
            and t["status"] == "ACTIVE"]


def has_active_tier(contract_id, product_class_code):
    return len(active_tiers(contract_id, product_class_code)) > 0


def select_tier(contract_id, product_class_code, class_cases):
    for tier in active_tiers(contract_id, product_class_code):
        if tier["min_case_volume"] <= class_cases and (
                tier["max_case_volume"] is None or class_cases < tier["max_case_volume"]):
            return tier
    return None


def entry_tier(contract_id, product_class_code):
    """The ACTIVE tier covering case volume zero (min_case_volume == 0)."""
    return select_tier(contract_id, product_class_code, 0)


def _line_sort_key(line):
    return (line["order_date"], line["created_at"], line["_seq"])


def class_cases_prospective(contract, product_class_code, order_date, exclude_line_id):
    total = 0
    rows = [ol for ol in values(db.order_lines)
            if ol["contract_id"] == contract["id"]
            and ol["id"] != exclude_line_id
            and ol["pricing_status"] in PRICING_ACTIVE_STATUSES
            and class_of(ol["product_id"]) == product_class_code
            and ol["order_date"] >= contract["effective_from"]
            and ol["order_date"] < order_date]
    for line in sorted(rows, key=_line_sort_key):
        total += line["quantity_cases"]
    return total


def class_cases_retroactive(contract, product_class_code, period_end):
    total = 0
    rows = [ol for ol in values(db.order_lines)
            if ol["contract_id"] == contract["id"]
            and ol["pricing_status"] in PRICING_ACTIVE_STATUSES
            and class_of(ol["product_id"]) == product_class_code
            and ol["order_date"] >= contract["effective_from"]
            and ol["order_date"] < period_end]
    for line in sorted(rows, key=_line_sort_key):
        total += line["quantity_cases"]
    return total


# --- markup ----------------------------------------------------------------

def list_price(cost, tier):
    if tier["markup_type"] == "PERCENT_OF_COST":
        return cents(dec(cost) * (dec(100) + dec(tier["markup_value"])) / dec(100))
    return int(cost) + cents(dec(tier["markup_value"]))


# --- deviation / coverage lookups ------------------------------------------

def active_deviation(contract_id, product_id, order_date):
    for dev in values(db.deviation_agreements):
        if (dev["contract_id"] == contract_id and dev["product_id"] == product_id
                and dev["status"] == "ACTIVE"
                and half_open_contains(dev["effective_from"], dev["effective_to"], order_date)):
            return dev
    return None


def active_coverage(contract_id, distribution_center_id, order_date):
    for cov in values(db.dc_coverages):
        if (cov["contract_id"] == contract_id
                and cov["distribution_center_id"] == distribution_center_id
                and cov["status"] == "ACTIVE"
                and closed_contains(cov["coverage_from"], cov["coverage_to"], order_date)):
            return cov
    return None


def service_fee_for(coverage, distribution_center, extended_price_cents, quantity_cases):
    if (coverage["coverage_type"] == "IN_MARKET"
            or coverage["service_fee_waived"] is True
            or extended_price_cents >= FEE_WAIVER_EXTENDED_THRESHOLD_CENTS):
        return 0
    return distribution_center["out_of_market_fee_per_case_cents"] * quantity_cases


# --- full line pricing -----------------------------------------------------

def resolve_tier_for_line(line, contract):
    """Tier + frozen cost for the prospective variant; raises priority-12."""
    product = product_of(line)
    product_class = product["product_class_code"]
    class_cases = class_cases_prospective(
        contract, product_class, line["order_date"], line["id"])
    tier = select_tier(contract["id"], product_class, class_cases)
    if tier is None:
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)
    cost = cost_on_basis(product, tier["cost_basis"])
    if cost is None:
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)
    return tier, cost


def invoiced_price_for(line, contract, tier, list_unit_price_cents):
    """Step 4 of contract_line_price: deviation, then substitution protection."""
    dev = active_deviation(contract["id"], line["product_id"], line["order_date"])
    if dev is not None:
        return dev["deviated_price_cents"], dev["id"]
    rule_id = line.get("substitution_rule_id")
    if rule_id is not None:
        rule = db.substitution_rules.get(rule_id)
        if rule is not None and rule["price_protection_mode"] == "HOLD_CONTRACT_PRICE":
            original = db.products.get(line.get("substituted_from_product_id"))
            if original is not None:
                original_cost = cost_on_basis(original, tier["cost_basis"])
                if original_cost is not None:
                    return list_price(original_cost, tier), None
    return list_unit_price_cents, None


def apply_fee(line, contract):
    coverage = active_coverage(
        contract["id"], line["distribution_center_id"], line["order_date"])
    if coverage is None:
        fail(errors.ERR_DC_NOT_COVERED)
    dc = db.distribution_centers[line["distribution_center_id"]]
    line["service_fee_cents"] = service_fee_for(
        coverage, dc, line["extended_price_cents"], line["quantity_cases"])
    line["invoice_total_cents"] = line["extended_price_cents"] + line["service_fee_cents"]


def price_line_full(line, contract):
    """Full derivation used by order-line create and substitute."""
    tier, cost = resolve_tier_for_line(line, contract)
    line["applied_tier_id"] = tier["id"]
    line["cost_basis_snapshot_cents"] = cost
    line["list_unit_price_cents"] = list_price(cost, tier)
    invoiced, deviation_id = invoiced_price_for(
        line, contract, tier, line["list_unit_price_cents"])
    line["invoiced_unit_price_cents"] = invoiced
    line["deviation_agreement_id"] = deviation_id
    line["extended_price_cents"] = invoiced * line["quantity_cases"]
    if line.get("substitution_rule_id") is None:
        line["is_contracted_item"] = bool(tier["counts_as_contracted"])
    else:
        rule = db.substitution_rules[line["substitution_rule_id"]]
        line["is_contracted_item"] = rule["price_protection_mode"] == "HOLD_CONTRACT_PRICE"
    apply_fee(line, contract)
    return line


def reprice_line(line, contract):
    """Reprice recomputes the five money fields from the current cost basis and
    the currently ACTIVE tier (PRD 3.5)."""
    tier, cost = resolve_tier_for_line(line, contract)
    line["list_unit_price_cents"] = list_price(cost, tier)
    invoiced, _ = invoiced_price_for(line, contract, tier, line["list_unit_price_cents"])
    line["invoiced_unit_price_cents"] = invoiced
    line["extended_price_cents"] = invoiced * line["quantity_cases"]
    apply_fee(line, contract)
    return line


# --- deviated price resolution ---------------------------------------------

def resolve_deviated_price(contract_id, product, bill_back_basis,
                           requested_net_price_cents, protected_discount_cents):
    if bill_back_basis == "FIXED_NET_PRICE":
        return requested_net_price_cents
    tier = entry_tier(contract_id, product["product_class_code"])
    if tier is None:
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)
    basis_cost = cost_on_basis(product, tier["cost_basis"])
    if basis_cost is None:
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)
    return basis_cost - protected_discount_cents


def rederive_deviated_price(deviation, fallback_cost_basis):
    """HOP 2 of the notice cascade: re-derive from the entry-band tier's basis."""
    product = db.products[deviation["product_id"]]
    tier = entry_tier(deviation["contract_id"], product["product_class_code"])
    basis = tier["cost_basis"] if tier is not None else fallback_cost_basis
    basis_cost = cost_on_basis(product, basis)
    if basis_cost is None:
        return deviation["deviated_price_cents"]
    return basis_cost - deviation["protected_discount_cents"]


# --- substitute selection --------------------------------------------------

def select_substitute(line, contract):
    primary = product_of(line)
    product_class = primary["product_class_code"]
    class_cases = class_cases_prospective(
        contract, product_class, line["order_date"], line["id"])
    tier = select_tier(contract["id"], product_class, class_cases)
    if tier is None:
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)
    primary_cost = cost_on_basis(primary, tier["cost_basis"])
    if primary_cost is None:
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)
    primary_list = list_price(primary_cost, tier)

    candidates = []
    for rule in values(db.substitution_rules):
        if rule["contract_id"] != contract["id"]:
            continue
        if rule["primary_product_id"] != line["product_id"]:
            continue
        if rule["status"] != "ACTIVE":
            continue
        substitute = db.products.get(rule["substitute_product_id"])
        if substitute is None:
            continue
        if substitute["status"] != "ACTIVE" or substitute["stock_status"] != "IN_STOCK":
            continue
        if substitute.get("substitution_group_code") is None:
            continue
        if substitute["substitution_group_code"] != primary.get("substitution_group_code"):
            continue
        substitute_cost = cost_on_basis(substitute, tier["cost_basis"])
        if substitute_cost is None:
            continue
        substitute_list = list_price(substitute_cost, tier)
        if primary_list == 0:
            if substitute_list != 0:
                continue
            delta = dec(0)
        else:
            delta = pct(abs(substitute_list - primary_list) * dec(100) / dec(primary_list))
        if delta > dec(rule["max_price_delta_pct"]):
            continue
        candidates.append(rule)

    if not candidates:
        fail(errors.ERR_NO_ELIGIBLE_SUBSTITUTE)
    candidates.sort(key=lambda r: (r["rank"], r["created_at"], r["_seq"]))
    return candidates[0]
