"""Business calculations and cascade helpers (PRD §3, scaffold §1.3).

Constants: REFUND_RATE_BPS=9900, TIER1_CAP_CENTS=1000000,
TIER2_DISCOUNT_BPS=2000, REALIZATION_BPS=8000, FILING_WINDOW_YEARS=5,
RETENTION_YEARS=3.
"""
from datetime import datetime
from fractions import Fraction

from db import STORE, next_seq
from util import add_years, new_id, rhu, wall_now_iso

REFUND_RATE_BPS = 9900
TIER1_CAP_CENTS = 1000000
TIER2_FACTOR_BPS = 10000 - 2000  # second tier bills at 80% of the agreed rate
REALIZATION_BPS = 8000
FILING_WINDOW_YEARS = 5
RETENTION_YEARS = 3

CULPABILITY_RATE_BPS = {
    "NONE": 0,
    "NEGLIGENCE": 500,
    "GROSS_NEGLIGENCE": 2000,
    "FRAUD": 10000,
}

OPEN_AUDIT_STATUSES = {"OPENED", "EVIDENCE_GATHERING", "RESPONSE_FILED"}
TERMINAL_CLAIM_STATUSES = {"PAID", "DENIED", "CANCELLED"}


# ---------------------------------------------------------------------------
# generic entity plumbing
# ---------------------------------------------------------------------------

def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = wall_now_iso()


def mint_entity():
    now = wall_now_iso()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1,
            "_seq": next_seq()}


def active_lines_on_entry(entry_id):
    return [l for l in STORE["claim_lines"].values()
            if l["import_entry_id"] == entry_id and l["status"] == "ACTIVE"]


def active_lines_on_export(export_id):
    return [l for l in STORE["claim_lines"].values()
            if l["export_shipment_id"] == export_id and l["status"] == "ACTIVE"]


def active_lines_of_claim(claim_id):
    return sorted(
        (l for l in STORE["claim_lines"].values()
         if l["claim_id"] == claim_id and l["status"] == "ACTIVE"),
        key=lambda l: l["_seq"],
    )


def derive_band(matched, total):
    if matched <= 0:
        return "UNMATCHED"
    if matched >= total:
        return "MATCHED"
    return "PARTIALLY_MATCHED"


# ---------------------------------------------------------------------------
# entry_eligible_duty (scaffold §1.3)
# ---------------------------------------------------------------------------

def entry_hts_code(entry):
    cls = STORE["classifications"].get(entry["classification_id"])
    return cls["hts_code"] if cls else ""


def measure_matches_entry(measure, entry):
    if not entry_hts_code(entry).startswith(measure["hts_code_prefix"]):
        return False
    if entry["entry_date"] < measure["effective_from"]:
        return False
    if measure["effective_to"] is not None and entry["entry_date"] >= measure["effective_to"]:
        return False
    return True  # half-open window [from, to)


def active_measures_for_entry(entry, extra=None):
    measures = [m for m in STORE["tariff_measures"].values()
                if m["status"] == "ACTIVE" and measure_matches_entry(m, entry)]
    if extra is not None and measure_matches_entry(extra, entry):
        measures.append(extra)
    return measures


def compute_non_drawbackable(entry, measures):
    """Per-measure round_half_up, then integer sum (pinned order).
    EXCLUSION contributes 0 and neutralizes every matching SECTION_301."""
    exclusion_present = any(m["measure_type"] == "EXCLUSION" for m in measures)
    total = 0
    for m in measures:
        if m["measure_type"] == "EXCLUSION":
            continue
        if m["measure_type"] == "SECTION_301" and exclusion_present:
            continue
        total += rhu(Fraction(entry["entered_value_cents"] * m["surcharge_bps"], 10000))
    return total


def recompute_entry(entry):
    """Recompute non_drawbackable / eligible / unclaimed from ACTIVE measures
    and ACTIVE claim lines. Does not bump version — callers do."""
    measures = active_measures_for_entry(entry)
    nd = compute_non_drawbackable(entry, measures)
    entry["non_drawbackable_cents"] = nd
    entry["drawback_eligible_duty_cents"] = max(0, entry["duty_paid_cents"] - nd)
    consumed = sum(l["drawback_amount_cents"] for l in active_lines_on_entry(entry["id"]))
    entry["unclaimed_duty_cents"] = entry["drawback_eligible_duty_cents"] - consumed


def recompute_entry_quantities(entry):
    lines = active_lines_on_entry(entry["id"])
    entry["matched_quantity"] = sum(l["matched_quantity"] for l in lines)
    entry["status"] = derive_band(entry["matched_quantity"], entry["line_quantity"])


def recompute_export(export):
    lines = active_lines_on_export(export["id"])
    export["matched_quantity"] = sum(l["matched_quantity"] for l in lines)
    export["value_pool_remaining_cents"] = (
        export["fob_value_cents"] - sum(l["drawback_amount_cents"] for l in lines)
    )
    export["status"] = derive_band(export["matched_quantity"], export["quantity"])


# ---------------------------------------------------------------------------
# line refunds (line_refund_direct / line_refund_substitution)
# ---------------------------------------------------------------------------

def line_raw_refund(entry, export, matched_quantity, claim_type):
    """Exact-rational raw refund (Fraction)."""
    unit_import = Fraction(entry["drawback_eligible_duty_cents"], entry["line_quantity"])
    if claim_type == "SUBSTITUTION":
        unit_substitute = Fraction(
            export["substituted_duty_rate_bps"] * export["fob_value_cents"],
            10000 * export["quantity"],
        )
        lesser = min(unit_import, unit_substitute)  # lesser-of rule, 19 USC 1313(l)
    else:
        lesser = unit_import
    return Fraction(REFUND_RATE_BPS, 10000) * lesser * matched_quantity


def compute_line_amount(entry, export, matched_quantity, claim_type):
    return rhu(line_raw_refund(entry, export, matched_quantity, claim_type))


# ---------------------------------------------------------------------------
# claim aggregation (claim_total) — per-line rounding then integer sum
# ---------------------------------------------------------------------------

def recompute_claim_estimate(claim):
    """PROVISIONAL variant: only recomputed while the claim is DRAFT."""
    claim["estimate_cents"] = sum(
        l["drawback_amount_cents"] for l in active_lines_of_claim(claim["id"])
    )


def recompute_filing_deadline(claim):
    """min(entry_date over ACTIVE lines' entries) + 5 years; null when lineless."""
    lines = active_lines_of_claim(claim["id"])
    if not lines:
        claim["filing_deadline"] = None
        return
    earliest = min(
        STORE["import_entries"][l["import_entry_id"]]["entry_date"] for l in lines
    )
    claim["filing_deadline"] = add_years(earliest, FILING_WINDOW_YEARS)


# ---------------------------------------------------------------------------
# invoice_fee_tiered (settled + accrued variants)
# ---------------------------------------------------------------------------

def tiered_fee_cents(recovered_cents, fee_bps):
    """Per-tier round_half_up, then integer sum (pinned order)."""
    tier1_base = min(recovered_cents, TIER1_CAP_CENTS)
    tier2_base = max(0, recovered_cents - TIER1_CAP_CENTS)
    tier1 = rhu(Fraction(tier1_base * fee_bps, 10000))
    tier2 = rhu(Fraction(tier2_base * fee_bps * TIER2_FACTOR_BPS, 100000000))
    return tier1 + tier2


# ---------------------------------------------------------------------------
# client_summary_aggregates
# ---------------------------------------------------------------------------

def recompute_client_aggregates(client, bump_on_change=True):
    old = (
        client["lifetime_recovered_cents"],
        client["projected_fee_accrual_cents"],
        client["open_audit_count"],
    )
    claims = [c for c in STORE["claims"].values() if c["client_id"] == client["id"]]
    client["lifetime_recovered_cents"] = sum(
        c["paid_duty_cents"] or 0 for c in claims if c["status"] == "PAID"
    )
    accrual = 0
    for c in claims:
        if c["status"] == "APPROVED":
            realized = rhu(Fraction(c["approved_duty_cents"] * REALIZATION_BPS, 10000))
            accrual += tiered_fee_cents(realized, client["contingency_fee_bps"])
    client["projected_fee_accrual_cents"] = accrual
    client["open_audit_count"] = sum(
        1 for a in STORE["audit_cases"].values()
        if a["client_id"] == client["id"] and a["status"] in OPEN_AUDIT_STATUSES
    )
    new = (
        client["lifetime_recovered_cents"],
        client["projected_fee_accrual_cents"],
        client["open_audit_count"],
    )
    if bump_on_change and new != old:
        touch(client)


# ---------------------------------------------------------------------------
# claim-line compensation cascade (PRD §2.9)
# ---------------------------------------------------------------------------

def void_line_with_cascade(line, recompute_claim=True):
    """Void one ACTIVE line; restore entry/export pools and quantities; every
    touched resource gets version += 1 and updated_at refreshed."""
    line["status"] = "VOID"
    touch(line)

    entry = STORE["import_entries"][line["import_entry_id"]]
    recompute_entry(entry)
    recompute_entry_quantities(entry)
    touch(entry)

    export = STORE["export_shipments"][line["export_shipment_id"]]
    recompute_export(export)
    touch(export)

    if recompute_claim:
        claim = STORE["claims"][line["claim_id"]]
        if claim["status"] == "DRAFT":
            recompute_claim_estimate(claim)
            recompute_filing_deadline(claim)
        touch(claim)


def void_all_active_lines(claim):
    for line in active_lines_of_claim(claim["id"]):
        void_line_with_cascade(line, recompute_claim=False)


# ---------------------------------------------------------------------------
# claim period overlap (CLOSED intervals; sharing one date IS an overlap)
# ---------------------------------------------------------------------------

def claim_period_overlaps(client_id, claim_type, start, end, exclude_id=None):
    for c in STORE["claims"].values():
        if c["id"] == exclude_id:
            continue
        if c["client_id"] != client_id or c["claim_type"] != claim_type:
            continue
        if c["status"] in TERMINAL_CLAIM_STATUSES:
            continue
        if start <= c["period_end"] and c["period_start"] <= end:
            return True
    return False


# ---------------------------------------------------------------------------
# tariff-measure window overlap (HALF-OPEN; adjacency allowed)
# ---------------------------------------------------------------------------

def measure_window_overlaps(measure_type, prefix, eff_from, eff_to, exclude_id=None):
    for m in STORE["tariff_measures"].values():
        if m["id"] == exclude_id:
            continue
        if m["status"] != "ACTIVE":
            continue
        if m["measure_type"] != measure_type or m["hts_code_prefix"] != prefix:
            continue
        left = True if m["effective_to"] is None else eff_from < m["effective_to"]
        right = True if eff_to is None else m["effective_from"] < eff_to
        if left and right:
            return True
    return False
