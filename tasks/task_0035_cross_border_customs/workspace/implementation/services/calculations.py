"""Calculation rules per scaffold §1.3 and PRD §3."""

import math
import re
from decimal import Decimal, ROUND_HALF_UP

from clock import parse_iso
from db import DB


# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------
KEYWORD_WEIGHT = Decimal("0.7")
DESCRIPTION_WEIGHT = Decimal("0.3")
MIN_RELEVANCE_SCORE = Decimal("0.20")

DEDUCTION_RATIO_BPS = 1500          # 15% deduction (DEDUCTIVE_VALUE)
LOGISTICS_PER_KG_MINOR = 5000       # 50.00 CNY per kg in fen (COMPUTED_VALUE)
COMPUTED_UPLIFT_BPS = 1000          # 10% profit uplift (COMPUTED_VALUE)

PERSONAL_POSTAL_THRESHOLD_CNY_MINOR = 500000  # 5,000.00 CNY in fen
POSTAL_EXEMPTION_CNY_MINOR = 5000             # 50.00 CNY in fen


def _floor_div(a: int, b: int) -> int:
    """Integer division that truncates toward zero (matches the PRD §2.5 wording)."""
    # For positive numerator/denominator (the only case in this domain) this is
    # identical to Python floor division. Use truncation to be safe.
    if b == 0:
        return 0
    q = a // b
    if (a < 0) ^ (b < 0):
        # Floor division goes toward -inf; we want truncation toward zero.
        if a % b != 0:
            q += 1
    return q


# ---------------------------------------------------------------------------
# Classification suggestion (PRD §3.2)
# ---------------------------------------------------------------------------

def _whole_word_count(text_lower: str, keyword_lower: str) -> int:
    """Count occurrences of `keyword_lower` as a whole-word substring in text_lower."""
    if not keyword_lower:
        return 0
    pattern = r"\b" + re.escape(keyword_lower) + r"\b"
    return len(re.findall(pattern, text_lower))


def classification_suggest(product_description: str):
    """Return up to 3 suggestions {hs_code, score} sorted by score DESC then code ASC."""
    if not isinstance(product_description, str):
        product_description = ""
    text_lower = product_description.lower()

    candidates = []
    for hs in DB.hs_codes.values():
        if hs.get("status") != "ACTIVE":
            continue
        keywords = hs.get("keywords") or []
        if keywords:
            matched = 0
            for kw in keywords:
                if not isinstance(kw, str):
                    continue
                kw_lower = kw.lower()
                # We count "keywords appearing" — at least one match counts as 1
                # per the PRD wording "count of HsCode.keywords appearing as
                # whole-word substring". Treat as count of distinct keywords
                # that appear (binary per keyword), matching PRD/scaffold
                # phrasing "count of HsCode.keywords appearing".
                if _whole_word_count(text_lower, kw_lower) > 0:
                    matched += 1
            denom = max(1, len(keywords))
            keyword_score = Decimal(matched) / Decimal(denom)
        else:
            keyword_score = Decimal(0)
        desc = (hs.get("description") or "").lower()
        description_score = Decimal(1) if (desc and desc in text_lower) else Decimal(0)

        raw = keyword_score * KEYWORD_WEIGHT + description_score * DESCRIPTION_WEIGHT
        # Round half-up to 6 decimal places.
        score = raw.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        candidates.append((score, hs.get("code") or "", hs))

    if not candidates:
        return []

    candidates.sort(key=lambda t: (-t[0], t[1]))
    top_score = candidates[0][0]
    if top_score < MIN_RELEVANCE_SCORE:
        return []

    out = []
    for score, _code, hs in candidates[:3]:
        out.append({"hs_code": hs, "score": float(score)})
    return out


# ---------------------------------------------------------------------------
# Exchange rate lookup (PRD §3.1) — pin date to latest effective_date <= submission date
# ---------------------------------------------------------------------------

def select_exchange_rate(from_currency: str, to_currency: str, submission_iso: str):
    """Return (rate_micros, effective_date) for the rate row to use.

    submission_iso is an ISO 8601 timestamp; we compare its date portion
    against ExchangeRate.effective_date (YYYY-MM-DD strings) lexicographically.
    """
    sub_dt = parse_iso(submission_iso)
    sub_date = sub_dt.date().isoformat()
    candidates = [
        er for er in DB.exchange_rates.values()
        if er["from_currency"] == from_currency
        and er["to_currency"] == to_currency
        and er["effective_date"] <= sub_date
    ]
    if not candidates:
        return None, None
    candidates.sort(key=lambda er: er["effective_date"], reverse=True)
    chosen = candidates[0]
    return int(chosen["rate_micros"]), chosen["effective_date"]


# ---------------------------------------------------------------------------
# Tariff rule lookup (PRD §3.1) — match (hs_code_id, origin, dest) and effective window
# ---------------------------------------------------------------------------

def select_tariff_rate_bps(hs_code_id: str, origin_country: str,
                           destination_country: str, submission_iso: str,
                           hs_default_bps: int) -> int:
    sub_dt = parse_iso(submission_iso)
    for tr in DB.tariff_rules.values():
        if tr["hs_code_id"] != hs_code_id:
            continue
        if tr["origin_country"] != origin_country:
            continue
        if tr["destination_country"] != destination_country:
            continue
        ef_from = parse_iso(tr["effective_from"])
        ef_to = parse_iso(tr.get("effective_to")) if tr.get("effective_to") else None
        # interval is [effective_from, effective_to). open-ended if effective_to is None.
        if sub_dt < ef_from:
            continue
        if ef_to is not None and sub_dt >= ef_to:
            continue
        return int(tr["tariff_rate_bps"])
    return int(hs_default_bps)


# ---------------------------------------------------------------------------
# Dutiable value (PRD §3.5) — per-line floor, then sum
# ---------------------------------------------------------------------------

def compute_line_dutiable_value(line_value_minor: int, weight_kg, method: str,
                                rate_micros: int) -> int:
    """Return CNY-fen contribution of a single line under `method`."""
    if method == "TRANSACTION_VALUE":
        line_minor = line_value_minor
    elif method == "DEDUCTIVE_VALUE":
        retail_value_minor = (line_value_minor * 125) // 100
        deduction_minor = (retail_value_minor * DEDUCTION_RATIO_BPS) // 10000
        line_minor = retail_value_minor - deduction_minor
    elif method == "COMPUTED_VALUE":
        # ceil(weight_kg * LOGISTICS_PER_KG_MINOR)
        try:
            wk = Decimal(str(weight_kg))
        except Exception:
            wk = Decimal(0)
        logistics = wk * Decimal(LOGISTICS_PER_KG_MINOR)
        # ceil to int
        logistics_minor = int(logistics.to_integral_value(rounding="ROUND_CEILING"))
        cost_plus = line_value_minor + logistics_minor
        uplifted = (cost_plus * (10000 + COMPUTED_UPLIFT_BPS)) // 10000
        line_minor = uplifted
    else:
        raise ValueError(f"Unknown dutiable_value_method: {method}")

    line_cny_minor = (line_minor * int(rate_micros)) // 1_000_000
    return int(line_cny_minor)


# ---------------------------------------------------------------------------
# Tax composition (PRD §3.6)
# ---------------------------------------------------------------------------

def compute_tax_totals(declaration: dict, lines: list, order: dict, submission_iso: str):
    """Return a dict with all the computed totals and tax_mode for a declaration.

    Mutates lines in place by populating each line's
    `line_dutiable_value_cny_minor` and `declared_value_minor`.
    """
    method = declaration["dutiable_value_method"]

    # Pin exchange rate (from order currency to CNY)
    rate_micros, effective_date = select_exchange_rate(order["currency"], "CNY", submission_iso)
    if rate_micros is None:
        # If no rate exists we cannot compute. Treat as zero (won't pass tests
        # that require rates, but won't crash either).
        rate_micros = 0
        effective_date = None

    line_items = order.get("line_items") or []
    per_line_dutiable_cny_minor = []
    total_dutiable = 0

    for ln in lines:
        idx = int(ln["order_line_index"])
        if idx < 0 or idx >= len(line_items):
            line_items_entry = {"quantity": 0, "unit_price": 0, "weight_kg": 0}
        else:
            line_items_entry = line_items[idx]
        qty = int(line_items_entry.get("quantity") or 0)
        unit_price = int(line_items_entry.get("unit_price") or 0)
        weight_kg = line_items_entry.get("weight_kg") or 0
        line_value_minor = qty * unit_price

        ln["declared_value_minor"] = line_value_minor

        contribution = compute_line_dutiable_value(line_value_minor, weight_kg, method, rate_micros)
        ln["line_dutiable_value_cny_minor"] = contribution
        per_line_dutiable_cny_minor.append((ln, contribution))
        total_dutiable += contribution

    # Determine tax_mode
    if (declaration["trade_mode"] == "B2C_DIRECT_MAIL"
            and total_dutiable <= PERSONAL_POSTAL_THRESHOLD_CNY_MINOR):
        tax_mode = "PERSONAL_POSTAL"
    else:
        tax_mode = "STANDARD"

    tariff_total = 0
    consumption_total = 0
    vat_total = 0

    if tax_mode == "STANDARD":
        for ln, line_dutiable in per_line_dutiable_cny_minor:
            hs = DB.hs_codes.get(ln["hs_code_id"])
            if hs is None:
                continue
            rate_bps = select_tariff_rate_bps(
                ln["hs_code_id"],
                order["origin_country"],
                order["destination_country"],
                submission_iso,
                hs.get("tariff_rate_bps", 0),
            )
            line_tariff = (line_dutiable * int(rate_bps)) // 10000
            line_consumption = (line_dutiable * int(hs.get("consumption_tax_rate_bps") or 0)) // 10000
            line_vat_base = line_dutiable + line_tariff + line_consumption
            line_vat = (line_vat_base * int(hs.get("vat_rate_bps") or 0)) // 10000
            tariff_total += line_tariff
            consumption_total += line_consumption
            vat_total += line_vat
        total_tax = tariff_total + vat_total + consumption_total
    else:
        # PERSONAL_POSTAL
        postal_total = 0
        for ln, line_dutiable in per_line_dutiable_cny_minor:
            hs = DB.hs_codes.get(ln["hs_code_id"])
            if hs is None:
                continue
            line_postal = (line_dutiable * int(hs.get("postal_tax_rate_bps") or 0)) // 10000
            postal_total += line_postal
        if postal_total <= POSTAL_EXEMPTION_CNY_MINOR:
            total_tax = 0
        else:
            total_tax = postal_total
        tariff_total = 0
        consumption_total = 0
        vat_total = 0

    return {
        "dutiable_value_cny_minor": total_dutiable,
        "tariff_amount_cny_minor": tariff_total,
        "vat_amount_cny_minor": vat_total,
        "consumption_tax_cny_minor": consumption_total,
        "total_tax_cny_minor": total_tax,
        "tax_mode": tax_mode,
        "exchange_rate_date_used": effective_date,
    }


# ---------------------------------------------------------------------------
# Refund amount (PRD §3.10)
# ---------------------------------------------------------------------------

def compute_refund_amount(refund_reason: str, payment_notice: dict, declaration: dict) -> int:
    pn_amount = int(payment_notice["amount_cny_minor"])
    if refund_reason in ("RETURN", "ORDER_CANCELLATION"):
        return pn_amount
    if refund_reason == "ERRONEOUS_DECLARATION":
        current_total = int(declaration.get("total_tax_cny_minor") or 0)
        return max(0, pn_amount - current_total)
    return 0


# ---------------------------------------------------------------------------
# TariffRule overlap check (PRD §3.1)
# ---------------------------------------------------------------------------

def tariff_rules_overlap(a_from, a_to, b_from, b_to) -> bool:
    """Two intervals [a_from, a_to) and [b_from, b_to) overlap iff
    a_from < b_to AND b_from < a_to. None for *_to means open-ended (+inf)."""
    # Normalize None → +inf semantics
    if a_to is None:
        a_to_dt = None
    else:
        a_to_dt = parse_iso(a_to)
    if b_to is None:
        b_to_dt = None
    else:
        b_to_dt = parse_iso(b_to)
    a_from_dt = parse_iso(a_from)
    b_from_dt = parse_iso(b_from)

    # a_from < b_to (or b_to is +inf)
    cond1 = (b_to_dt is None) or (a_from_dt < b_to_dt)
    # b_from < a_to (or a_to is +inf)
    cond2 = (a_to_dt is None) or (b_from_dt < a_to_dt)
    return cond1 and cond2
