"""The nine pinned calculations of SCAFFOLD 1.3 / PRD 2.6."""

import hashlib
from decimal import Decimal, ROUND_HALF_UP

from errors import fail
from store import STORE

BP = 10000
VARIANCE_TOLERANCE_BP = 100
SIMILARITY_THRESHOLD = Decimal("0.8000")
MIN_TOKEN_LENGTH = 3
DEFAULT_MARKUP_TIERS = [
    {"min_cost_basis_cents": 0, "markup_bp": 32000},
    {"min_cost_basis_cents": 50000, "markup_bp": 24000},
    {"min_cost_basis_cents": 250000, "markup_bp": 18000},
]


def rhu_div(numerator, denominator):
    """Integer division rounding half away from zero."""
    if denominator == 0:
        raise ZeroDivisionError("rhu_div by zero")
    sign = 1
    if (numerator < 0) != (denominator < 0):
        sign = -1
    num = abs(numerator)
    den = abs(denominator)
    return sign * ((2 * num + den) // (2 * den))


def apply_bp(amount, basis_points):
    return rhu_div(amount * basis_points, BP)


def round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# price_rule_selector
# ---------------------------------------------------------------------------
def price_rule_candidates(facility_id, revenue_code_id):
    now = STORE.now
    out = []
    for rule in STORE.ordered(STORE.price_rules):
        if rule["facility_id"] != facility_id:
            continue
        if rule["revenue_code_id"] != revenue_code_id:
            continue
        if rule["status"] != "ACTIVE":
            continue
        if rule["_effective_from"] > now:
            continue
        eff_to = rule.get("_effective_to")
        if eff_to is not None and not (now < eff_to):
            continue
        out.append(rule)
    return out


def price_rule_selector(facility_id, revenue_code_id):
    candidates = price_rule_candidates(facility_id, revenue_code_id)
    if not candidates:
        fail(
            "ERR_NO_APPLICABLE_PRICE_RULE",
            "No ACTIVE price rule is in force for this scope.",
        )
    candidates.sort(key=lambda r: (r["_created"], r["_seq"]))
    candidates.sort(key=lambda r: r["_effective_from"], reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# gross_charge_from_price_rule
# ---------------------------------------------------------------------------
def select_tier(tiers, cost_basis_cents):
    chosen = None
    for tier in tiers or DEFAULT_MARKUP_TIERS:
        if tier["min_cost_basis_cents"] <= cost_basis_cents:
            chosen = tier
    if chosen is None:
        chosen = (tiers or DEFAULT_MARKUP_TIERS)[0]
    return chosen


def apply_rounding_mode(cents, rounding_mode):
    if rounding_mode == "NEAREST_CENT":
        return cents
    if rounding_mode == "NEAREST_DOLLAR":
        return rhu_div(cents, 100) * 100
    # PSYCHOLOGICAL_99
    return -((-cents) // 100) * 100 - 1


def gross_charge_from_price_rule(
    facility,
    revenue_code_id,
    cost_basis_cents,
    medicare_rate_cents,
    market_p75_cents,
):
    """Returns (gross_cents, price_conflict, rule)."""
    rule = price_rule_selector(facility["id"], revenue_code_id)
    method = rule["pricing_method"]
    if method == "FLAT_FEE":
        base = rule.get("flat_fee_cents") or 0
    elif method == "MEDICARE_MULTIPLE":
        base = apply_bp(medicare_rate_cents, rule["min_medicare_multiple_bp"])
    else:
        tier = select_tier(rule.get("markup_tiers"), cost_basis_cents)
        base = apply_bp(cost_basis_cents, tier["markup_bp"])

    floor_cents = apply_bp(medicare_rate_cents, rule["min_medicare_multiple_bp"])
    cap_cents = apply_bp(market_p75_cents, rule["market_cap_multiple_bp"])
    floored = max(base, floor_cents)
    constrained = min(floored, cap_cents)
    price_conflict = floor_cents > cap_cents
    gross = apply_rounding_mode(constrained, facility["rounding_mode"])
    return gross, price_conflict, rule


def reprice_item_value(facility, item, cost_basis_cents=None, revenue_code_id=None):
    return gross_charge_from_price_rule(
        facility,
        revenue_code_id if revenue_code_id is not None else item["revenue_code_id"],
        cost_basis_cents if cost_basis_cents is not None else item["cost_basis_cents"],
        item["medicare_rate_cents"],
        item["market_p75_cents"],
    )


# ---------------------------------------------------------------------------
# markup_compliance_ratio
# ---------------------------------------------------------------------------
def markup_compliance_ratio(facility, item, proposed_gross, proposed_cost):
    active = item["lifecycle_status"] == "ACTIVE"
    snap_gross = facility["aggregate_gross_charge_cents"] - (
        item["gross_charge_cents"] if active else 0
    )
    snap_cost = facility["aggregate_cost_basis_cents"] - (
        item["cost_basis_cents"] if active else 0
    )
    num = snap_gross + proposed_gross
    den = snap_cost + proposed_cost
    if den == 0:
        return 0
    return rhu_div(num * BP, den)


# ---------------------------------------------------------------------------
# code_update_crosswalk_price_carry
# ---------------------------------------------------------------------------
def code_update_crosswalk_price_carry(cycle, entry, target, facility, new_revenue_code_id):
    if entry["action"] == "DELETE":
        return target["gross_charge_cents"]
    if new_revenue_code_id is None or new_revenue_code_id == target["revenue_code_id"]:
        return target["gross_charge_cents"]
    inflated = apply_bp(target["cost_basis_cents"], cycle["cost_inflator_bp"])
    gross, _conflict, _rule = gross_charge_from_price_rule(
        facility,
        new_revenue_code_id,
        inflated,
        target["medicare_rate_cents"],
        target["market_p75_cents"],
    )
    return gross


# ---------------------------------------------------------------------------
# payer_impact_delta
# ---------------------------------------------------------------------------
def reimburse(contract, charge_cents, units):
    method = contract["reimbursement_method"]
    if method == "PERCENT_OF_CHARGE":
        per_unit = apply_bp(charge_cents, contract.get("percent_of_charge_bp") or 0)
    elif method == "LESSER_OF_FEE_SCHEDULE":
        pct = apply_bp(charge_cents, contract.get("percent_of_charge_bp") or 0)
        per_unit = min(pct, contract.get("fee_schedule_cents") or 0)
    else:
        per_unit = contract.get("case_rate_cents") or 0
    return per_unit * units


def payer_impact_delta(variant, facility, item, old_gross, new_gross):
    if variant == "FORWARD_PROJECTED":
        lines = _forward_projected(facility, item, old_gross, new_gross)
    else:
        lines = _historical_replay(facility, item, old_gross, new_gross)
    total = sum(line["delta_cents"] for line in lines)
    return lines, total


def _forward_projected(facility, item, old_gross, new_gross):
    now = STORE.now
    contracts = []
    for contract in STORE.ordered(STORE.payer_contracts):
        if contract["facility_id"] != facility["id"]:
            continue
        if contract["status"] != "ACTIVE":
            continue
        if contract["_term_start"] <= now <= contract["_term_end"]:
            contracts.append(contract)
    contracts.sort(key=lambda c: (c["payer_code"], c["product_line"]))
    lines = []
    for contract in contracts:
        units = apply_bp(contract.get("trailing_units") or 0, facility["volume_growth_bp"])
        old_r = reimburse(contract, old_gross, units)
        new_r = reimburse(contract, new_gross, units)
        lines.append(
            {
                "payer_code": contract["payer_code"],
                "product_line": contract["product_line"],
                "units": units,
                "old_reimbursement_cents": old_r,
                "new_reimbursement_cents": new_r,
                "delta_cents": new_r - old_r,
            }
        )
    return lines


def _historical_replay(facility, item, old_gross, new_gross):
    from datetime import timedelta

    now = STORE.now
    window_start = now - timedelta(days=facility["impact_lookback_days"])
    captured = []
    for line in STORE.ordered(STORE.captured_charges):
        if line.get("charge_item_id") != item["id"]:
            continue
        batch = STORE.batches.get(line["batch_id"])
        if batch is None or batch["status"] not in ("RECONCILED", "CLOSED"):
            continue
        if line["match_status"] not in ("MATCHED", "PRICE_VARIANCE"):
            continue
        service = line["_service_datetime"]
        if not (window_start <= service <= now):
            continue
        captured.append(line)
    captured.sort(key=lambda l: (l["_service_datetime"], l["_created"], l["_seq"]))

    buckets = {}
    for line in captured:
        contract = _contract_on_service_date(facility, line)
        if contract is None:
            continue
        key = (contract["payer_code"], contract["product_line"])
        bucket = buckets.setdefault(
            key,
            {
                "payer_code": contract["payer_code"],
                "product_line": contract["product_line"],
                "units": 0,
                "old_reimbursement_cents": 0,
                "new_reimbursement_cents": 0,
            },
        )
        bucket["units"] += line["quantity"]
        bucket["old_reimbursement_cents"] += reimburse(contract, old_gross, line["quantity"])
        bucket["new_reimbursement_cents"] += reimburse(contract, new_gross, line["quantity"])
    lines = []
    for key in sorted(buckets):
        bucket = buckets[key]
        bucket["delta_cents"] = (
            bucket["new_reimbursement_cents"] - bucket["old_reimbursement_cents"]
        )
        lines.append(bucket)
    return lines


def _contract_on_service_date(facility, line):
    service = line["_service_datetime"]
    matches = []
    for contract in STORE.ordered(STORE.payer_contracts):
        if contract["facility_id"] != facility["id"]:
            continue
        if contract["payer_code"] != line.get("payer_code"):
            continue
        if contract["status"] not in ("ACTIVE", "EXPIRED"):
            continue
        if contract["_term_start"] <= service <= contract["_term_end"]:
            matches.append(contract)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# duplicate_similarity_score
# ---------------------------------------------------------------------------
def tokens(text):
    if not text:
        return set()
    upper = text.upper()
    parts = []
    current = []
    for char in upper:
        if char.isalnum():
            current.append(char)
        else:
            if current:
                parts.append("".join(current))
                current = []
    if current:
        parts.append("".join(current))
    return set(part for part in parts if len(part) >= MIN_TOKEN_LENGTH)


def duplicate_similarity_score(mode, subject, candidate):
    code_match = (
        1
        if (
            subject["code_type"] == candidate["code_type"]
            and subject.get("code_value") == candidate.get("code_value")
            and subject.get("code_value") is not None
        )
        else 0
    )
    rev_match = 1 if subject["revenue_code_id"] == candidate["revenue_code_id"] else 0
    if mode == "STRICT_CODE":
        if code_match == 1 and rev_match == 1 and subject["department_id"] == candidate["department_id"]:
            return Decimal("1.0000")
        return Decimal("0.0000")
    a = tokens(subject.get("description"))
    b = tokens(candidate.get("description"))
    union = a | b
    if not union:
        jaccard = Decimal("0.0000")
    else:
        jaccard = round4(Decimal(len(a & b)) / Decimal(len(union)))
    score = (
        Decimal("0.5") * Decimal(code_match)
        + Decimal("0.3") * jaccard
        + Decimal("0.2") * Decimal(rev_match)
    )
    return round4(score)


def duplicate_candidates(facility, subject):
    """(candidate, score) pairs ranked by score DESC then created_at ASC."""
    mode = facility["duplicate_detection_mode"]
    rows = []
    for candidate in STORE.ordered(STORE.charge_items):
        if candidate["facility_id"] != facility["id"]:
            continue
        if candidate["id"] == subject["id"]:
            continue
        if candidate["lifecycle_status"] != "ACTIVE":
            continue
        if candidate.get("duplicate_of_item_id") is not None:
            continue
        rows.append((candidate, duplicate_similarity_score(mode, subject, candidate)))
    rows.sort(key=lambda pair: (pair[0]["_created"], pair[0]["_seq"]))
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# charge_capture_variance_summary
# ---------------------------------------------------------------------------
def batch_lines(batch_id):
    lines = [
        line
        for line in STORE.captured_charges.values()
        if line["batch_id"] == batch_id
    ]
    lines.sort(key=lambda l: (l["_service_datetime"], l["_created"], l["_seq"]))
    return lines


def resolve_line_item(facility_id, cdm_number):
    for item in STORE.ordered(STORE.charge_items):
        if item["facility_id"] == facility_id and item["cdm_number"] == cdm_number:
            return item
    return None


def charge_capture_variance_summary(batch):
    lines = batch_lines(batch["id"])
    facility_id = batch["facility_id"]
    seen_keys = {}
    for line in lines:
        item = resolve_line_item(facility_id, line["submitted_cdm_number"])
        line["charge_item_id"] = item["id"] if item is not None else None
        line["expected_charge_cents"] = None
        line["line_variance_bp"] = None
        if item is None:
            line["match_status"] = "UNKNOWN_CODE"
            continue
        if item["lifecycle_status"] in ("INACTIVE", "ARCHIVED"):
            line["match_status"] = "INACTIVE_ITEM"
            continue
        key = (line["encounter_id"], item["id"], line["service_datetime"])
        if key in seen_keys:
            line["match_status"] = "DUPLICATE_LINE"
            continue
        seen_keys[key] = line["id"]
        expected = item["gross_charge_cents"] * line["quantity"]
        line["expected_charge_cents"] = expected
        if expected == 0:
            line["line_variance_bp"] = None
            line["match_status"] = (
                "PRICE_VARIANCE" if line["posted_charge_cents"] > 0 else "MATCHED"
            )
            continue
        variance = rhu_div((line["posted_charge_cents"] - expected) * BP, expected)
        line["line_variance_bp"] = variance
        line["match_status"] = (
            "PRICE_VARIANCE" if abs(variance) > VARIANCE_TOLERANCE_BP else "MATCHED"
        )

    scored = [
        line
        for line in lines
        if line["match_status"] in ("MATCHED", "PRICE_VARIANCE")
        and line["line_variance_bp"] is not None
    ]
    if not scored:
        mean = 0
    else:
        mean = rhu_div(sum(l["line_variance_bp"] for l in scored), len(scored))
    total_expected = sum(
        (line["expected_charge_cents"] or 0)
        for line in lines
        if line["match_status"] != "UNKNOWN_CODE"
    )
    total_posted = sum(line["posted_charge_cents"] for line in lines)
    return lines, mean, total_expected, total_posted


# ---------------------------------------------------------------------------
# missing_charge_detection
# ---------------------------------------------------------------------------
def missing_charge_detection(batch, lines):
    """Returns (created_findings_spec, dismissed_findings)."""
    creations = []
    dismissals = []
    for trigger in lines:
        if trigger["match_status"] not in ("MATCHED", "PRICE_VARIANCE"):
            continue
        item = STORE.charge_items.get(trigger.get("charge_item_id"))
        if item is None:
            continue
        companion_id = item.get("companion_required_item_id")
        if companion_id is None:
            continue
        companion = STORE.charge_items.get(companion_id)
        if companion is None:
            continue
        if companion["lifecycle_status"] in ("INACTIVE", "ARCHIVED"):
            continue
        window_hours = item.get("companion_window_hours")
        if window_hours is None:
            window_hours = 24
        present = False
        for other in lines:
            if other.get("charge_item_id") != companion["id"]:
                continue
            if other["encounter_id"] != trigger["encounter_id"]:
                continue
            if other["match_status"] == "DUPLICATE_LINE":
                continue
            if other["quantity"] < trigger["quantity"]:
                continue
            delta = other["_service_datetime"] - trigger["_service_datetime"]
            hours = delta.total_seconds() / 3600.0
            if 0 <= hours <= window_hours:
                present = True
                break
        existing_open = None
        blocking = False
        for finding in STORE.ordered(STORE.findings):
            if finding.get("trigger_captured_charge_id") != trigger["id"]:
                continue
            if finding["status"] == "OPEN":
                existing_open = finding
            if finding["status"] in ("OPEN", "CONFIRMED", "RESOLVED"):
                blocking = True
        if present:
            if existing_open is not None:
                dismissals.append(existing_open)
            continue
        if not blocking:
            creations.append(
                {
                    "trigger": trigger,
                    "companion": companion,
                    "estimated_lost_charge_cents": companion["gross_charge_cents"]
                    * trigger["quantity"],
                }
            )
    return creations, dismissals


# ---------------------------------------------------------------------------
# transparency_file_build
# ---------------------------------------------------------------------------
def transparency_inclusion_set(facility_id):
    rows = []
    for item in STORE.ordered(STORE.charge_items):
        if item["facility_id"] != facility_id:
            continue
        if item["lifecycle_status"] != "ACTIVE":
            continue
        if item["price_status"] not in ("PRICED_CURRENT", "PRICE_FROZEN"):
            continue
        if item.get("duplicate_of_item_id") is not None:
            continue
        rows.append(item)

    def sort_key(item):
        revenue_code = STORE.revenue_codes.get(item["revenue_code_id"]) or {}
        code = revenue_code.get("code") or ""
        code_value = item.get("code_value")
        return (
            code,
            1 if code_value is None else 0,
            code_value or "",
            item["cdm_number"],
        )

    rows.sort(key=sort_key)
    return rows


def transparency_file_build(facility, as_of):
    inclusion = transparency_inclusion_set(facility["id"])
    included_item_count = len(inclusion)
    total_gross = sum(item["gross_charge_cents"] for item in inclusion)
    columns = set()
    for contract in STORE.payer_contracts.values():
        if contract["facility_id"] != facility["id"]:
            continue
        if contract["status"] != "ACTIVE":
            continue
        if contract["_term_start"] <= as_of <= contract["_term_end"]:
            columns.add((contract["payer_code"], contract["product_line"]))
    payer_column_count = len(columns)
    serialized = []
    for item in inclusion:
        revenue_code = STORE.revenue_codes.get(item["revenue_code_id"]) or {}
        serialized.append(
            "%s|%s|%s|%d"
            % (
                item["cdm_number"],
                revenue_code.get("code") or "",
                item.get("code_value") or "",
                item["gross_charge_cents"],
            )
        )
    content_hash = hashlib.sha256("\n".join(serialized).encode("utf-8")).hexdigest()
    validation_errors = []
    if included_item_count == 0:
        validation_errors.append("NO_PUBLISHABLE_ITEMS")
    if payer_column_count == 0:
        validation_errors.append("NO_ACTIVE_PAYER_COLUMNS")
    for item in STORE.charge_items.values():
        if (
            item["facility_id"] == facility["id"]
            and item["lifecycle_status"] == "ACTIVE"
            and item["price_status"] == "PRICE_STALE"
        ):
            validation_errors.append("STALE_PRICED_ITEMS")
            break
    return {
        "included_item_count": included_item_count,
        "total_gross_charge_cents": total_gross,
        "payer_column_count": payer_column_count,
        "content_hash": content_hash,
        "validation_errors": validation_errors,
    }
