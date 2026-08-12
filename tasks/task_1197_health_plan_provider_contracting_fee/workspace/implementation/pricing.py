"""Calculation rules (scaffold section 1.3): benchmark resolution, entry rate
computation, escalator projection, claim line pricing, retro repricing sweep,
simulation scoring, parity band evaluation, and the date-window rules.

All money is integer cents; every fractional multiplication/division resolves
immediately with round-half-up on non-negative integers.
"""

from datetime import timedelta

import store
from bodycheck import parse_date
from errors import ApiError

BPS_DENOMINATOR = 10000
SAFETY_FLOOR_BPS = 8000
OUTLIER_THRESHOLD_BPS = 30000
OUTLIER_SHARE_BPS = 8000
PASS_THRESHOLD_BPS = 7500
NOTICE_MIN_DAYS = 90
COC_MAX_DAYS = 90
ADJACENCY_GAP_DAYS = 1


def rhu(numerator, denominator=BPS_DENOMINATOR):
    """Round half up for non-negative integer numerator / denominator."""
    return (2 * numerator + denominator) // (2 * denominator)


# ---------------------------------------------------------------------------
# benchmark_resolution
# ---------------------------------------------------------------------------
def resolve_benchmark(entry, version, provider):
    year = parse_date(version["effective_date"], "effective_date").year
    candidates = [
        b for b in store.benchmarks.values()
        if b["hcpcs_code"] == entry["hcpcs_code"]
        and b["locality_code"] == provider["locality_code"]
        and b["benchmark_status"] == "PUBLISHED"
    ]
    if entry["benchmark_lookup_mode"] == "STRICT":
        candidates = [b for b in candidates if b["benchmark_year"] == year]
    else:  # PROVISIONAL: latest published year <= effective year
        candidates = [b for b in candidates if b["benchmark_year"] <= year]
    if not candidates:
        raise ApiError(
            "ERR_BENCHMARK_UNPUBLISHED", 422,
            "No PUBLISHED Medicare benchmark satisfies the entry's lookup mode.",
        )
    # Composite uniqueness of (year, locality, hcpcs) makes ties impossible.
    return max(candidates, key=lambda b: b["benchmark_year"])


# ---------------------------------------------------------------------------
# entry_rate_computation
# ---------------------------------------------------------------------------
def compute_entry_rate(entry, resolved_benchmark_cents):
    if entry["rate_type"] == "PERCENT_OF_MEDICARE":
        return rhu(resolved_benchmark_cents * entry["pct_of_medicare_bps"])
    # FLAT_RATE / PER_DIEM / CASE_RATE: the flat amount stands as the base;
    # LOS multiplication and case outlier adjustments apply per claim.
    return entry["flat_rate_cents"]


# ---------------------------------------------------------------------------
# escalator_projection
# ---------------------------------------------------------------------------
def _anniversary_steps(effective, service):
    if service < effective:
        return 0
    steps = service.year - effective.year
    if (service.month, service.day) < (effective.month, effective.day):
        steps -= 1
    return max(0, steps)


def escalator_steps(contract, version, service_date):
    effective = parse_date(version["effective_date"], "effective_date")
    if contract["escalator_mode"] == "ANNIVERSARY":
        return _anniversary_steps(effective, service_date)
    # CALENDAR: steps increment every Jan 1
    return max(0, service_date.year - effective.year)


def projected_rate(contract, version, entry, service_date):
    """Escalator-projected whole-cent rate; each completed step compounds on
    the rounded whole-cent result of the previous step."""
    rate = entry["computed_rate_cents"]
    factor = BPS_DENOMINATOR + contract["escalator_bps"]
    for _ in range(escalator_steps(contract, version, service_date)):
        rate = rhu(rate * factor)
    return rate


# ---------------------------------------------------------------------------
# Carve-out selection (shared by claim_line_pricing and retro_repricing_sweep)
# ---------------------------------------------------------------------------
def select_carve_out(version_id, service_category, service_date):
    candidates = [
        c for c in store.carve_outs.values()
        if c["contract_version_id"] == version_id
        and (c["service_category"] == service_category or c["service_category"] == "*")
        and parse_date(c["start_date"], "start_date") <= service_date
        <= parse_date(c["end_date"], "end_date")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["priority_rank"], c["created_at"]))
    return candidates[0]


def find_entry(version_id, hcpcs_code):
    for e in store.entries.values():
        if e["contract_version_id"] == version_id and e["hcpcs_code"] == hcpcs_code:
            return e
    return None


# ---------------------------------------------------------------------------
# claim_line_pricing
# ---------------------------------------------------------------------------
def price_claim_line(claim, version, contract):
    """Returns (priced_allowed_cents or None, claim_outcome)."""
    service_date = parse_date(claim["service_date"], "service_date")
    carve_out = select_carve_out(version["id"], claim["service_category"], service_date)
    if carve_out is not None:
        if carve_out["override_type"] == "EXCLUDE":
            return None, "EXCLUDED"
        if carve_out["override_type"] == "FLAT_RATE":
            line_allowed = carve_out["override_flat_cents"]
        else:  # PCT_OF_MEDICARE
            entry = find_entry(version["id"], claim["hcpcs_code"])
            if entry is None or entry["resolved_benchmark_cents"] is None:
                return None, "MISMATCH"
            line_allowed = rhu(
                entry["resolved_benchmark_cents"] * carve_out["override_pct_bps"]
            )
    else:
        entry = find_entry(version["id"], claim["hcpcs_code"])
        if entry is None:
            return None, "MISMATCH"
        base = projected_rate(contract, version, entry, service_date)
        rate_type = entry["rate_type"]
        if rate_type in ("PERCENT_OF_MEDICARE", "FLAT_RATE"):
            line_allowed = base
        elif rate_type == "PER_DIEM":
            line_allowed = base * claim["los_days"]
        else:  # CASE_RATE with capped outlier branch
            billed = claim["billed_cents"]
            if billed * BPS_DENOMINATOR > OUTLIER_THRESHOLD_BPS * base:
                threshold = rhu(OUTLIER_THRESHOLD_BPS * base)
                excess = billed - threshold
                line_allowed = base + rhu(excess * OUTLIER_SHARE_BPS)
            else:
                line_allowed = base
            line_allowed = min(line_allowed, billed)
    outcome = "MATCH" if line_allowed == claim["expected_allowed_cents"] else "MISMATCH"
    return line_allowed, outcome


def recompute_batch_counters(batch):
    rows = [c for c in store.claims.values() if c["simulation_batch_id"] == batch["id"]]
    batch["total_claims"] = len(rows)
    batch["matched_claims"] = sum(1 for c in rows if c["claim_outcome"] == "MATCH")
    batch["mismatched_claims"] = sum(1 for c in rows if c["claim_outcome"] == "MISMATCH")
    batch["excluded_claims"] = sum(1 for c in rows if c["claim_outcome"] == "EXCLUDED")
    batch["pending_claims"] = sum(1 for c in rows if c["claim_outcome"] == "PENDING")
    # Per-line rounded values are summed; sum-then-round is never used.
    batch["total_priced_cents"] = sum(
        c["priced_allowed_cents"]
        for c in rows
        if c["claim_outcome"] in ("MATCH", "MISMATCH")
        and c["priced_allowed_cents"] is not None
    )


# ---------------------------------------------------------------------------
# retro_repricing_sweep
# ---------------------------------------------------------------------------
def retro_sweep(run, version, contract):
    window_start = parse_date(run["window_start_date"], "window_start_date")
    window_end = parse_date(run["window_end_date"], "window_end_date")
    candidates = [
        s for s in store.paid_claims.values()
        if s["contract_id"] == contract["id"]
        and s["snapshot_status"] == "OPEN"
        and window_start <= parse_date(s["service_date"], "service_date") < window_end
    ]
    candidates.sort(key=lambda s: (s["service_date"], s["created_at"]))
    for snapshot in candidates:
        entry = find_entry(version["id"], snapshot["hcpcs_code"])
        if entry is None or entry["entry_status"] != "LOCKED":
            continue
        service_date = parse_date(snapshot["service_date"], "service_date")
        carve_out = select_carve_out(version["id"], snapshot["service_category"], service_date)
        if carve_out is not None and carve_out["override_type"] == "FLAT_RATE":
            repriced = carve_out["override_flat_cents"]
        elif carve_out is not None and carve_out["override_type"] == "PCT_OF_MEDICARE":
            repriced = rhu(entry["resolved_benchmark_cents"] * carve_out["override_pct_bps"])
        else:
            # No carve-out, or an EXCLUDE carve-out: the snapshot stays at its
            # escalator-projected entry rate (EXCLUDE never excludes here).
            repriced = projected_rate(contract, version, entry, service_date)
        delta = repriced - snapshot["paid_cents"]
        if delta == 0:
            continue
        adjustment = store.stamp_new({
            "retro_run_id": run["id"],
            "paid_claim_id": snapshot["id"],
            "service_date": snapshot["service_date"],
            "original_paid_cents": snapshot["paid_cents"],
            "repriced_allowed_cents": repriced,
            "delta_cents": delta,
            "direction": "UNDERPAID" if delta > 0 else "OVERPAID",
            "adjustment_status": "PROPOSED",
        })
        store.adjustments[adjustment["id"]] = adjustment


def recompute_run_totals(run):
    rows = [
        a for a in store.adjustments.values()
        if a["retro_run_id"] == run["id"] and a["adjustment_status"] != "VOIDED"
    ]
    run["adjustment_count"] = len(rows)
    run["total_underpaid_cents"] = sum(a["delta_cents"] for a in rows if a["delta_cents"] > 0)
    run["total_overpaid_cents"] = sum(-a["delta_cents"] for a in rows if a["delta_cents"] < 0)
    run["net_delta_cents"] = run["total_underpaid_cents"] - run["total_overpaid_cents"]


# ---------------------------------------------------------------------------
# parity_band_evaluation
# ---------------------------------------------------------------------------
def parity_check(contract, activating_version):
    """Raises ERR_RATE_PARITY_VIOLATION when any overlapping hcpcs_code ratio
    strictly exceeds an ACTIVE rule's band for the paired line of business."""
    network = store.networks.get(contract["network_id"])
    if network is None:
        return
    lob = network["line_of_business"]
    activating_date = parse_date(activating_version["effective_date"], "effective_date")
    activating_entries = {
        e["hcpcs_code"]: e
        for e in store.entries.values()
        if e["contract_version_id"] == activating_version["id"]
        and e["entry_status"] == "LOCKED"
    }
    if not activating_entries:
        return
    for rule in store.parity_rules.values():
        if rule["rule_status"] != "ACTIVE":
            continue
        pair = {rule["line_of_business_a"], rule["line_of_business_b"]}
        if lob not in pair:
            continue
        other_lob = (pair - {lob}).pop()
        for other in store.contracts.values():
            if other["id"] == contract["id"]:
                continue
            if other["provider_id"] != contract["provider_id"]:
                continue
            if other["contract_status"] != "ACTIVE":
                continue
            other_network = store.networks.get(other["network_id"])
            if other_network is None or other_network["line_of_business"] != other_lob:
                continue
            other_versions = [
                v for v in store.versions.values()
                if v["contract_id"] == other["id"] and v["version_status"] == "EFFECTIVE"
            ]
            for other_version in other_versions:
                other_entries = {
                    e["hcpcs_code"]: e
                    for e in store.entries.values()
                    if e["contract_version_id"] == other_version["id"]
                    and e["entry_status"] == "LOCKED"
                }
                for hcpcs, entry_c in activating_entries.items():
                    entry_o = other_entries.get(hcpcs)
                    if entry_o is None:
                        continue
                    rate_c = projected_rate(contract, activating_version, entry_c, activating_date)
                    rate_o = projected_rate(other, other_version, entry_o, activating_date)
                    hi, lo = max(rate_c, rate_o), min(rate_c, rate_o)
                    if lo <= 0:
                        if hi > 0:
                            raise ApiError(
                                "ERR_RATE_PARITY_VIOLATION", 422,
                                "Rate parity violation: ratio exceeds the permitted band.",
                            )
                        continue
                    # Integer floor division discards the fractional remainder.
                    ratio = (hi * BPS_DENOMINATOR) // lo
                    if ratio > rule["band_bps"]:
                        raise ApiError(
                            "ERR_RATE_PARITY_VIOLATION", 422,
                            "Rate parity violation: ratio exceeds the permitted band.",
                        )


# ---------------------------------------------------------------------------
# Date-window rules
# ---------------------------------------------------------------------------
def notice_period_valid(notice_date_str, termination_date_str):
    days = (parse_date(termination_date_str, "termination_date")
            - parse_date(notice_date_str, "notice_date")).days
    return days >= NOTICE_MIN_DAYS


def coc_coverage_end(termination_date_str, treatment_end_str):
    limit = parse_date(termination_date_str, "termination_date") + timedelta(days=COC_MAX_DAYS)
    treatment_end = parse_date(treatment_end_str, "treatment_end_date")
    return min(limit, treatment_end).isoformat()


def carve_out_window_conflicts(version_id, service_category, start_str, end_str):
    """Closed-interval conflict including one-day adjacency, comparing the
    literal service_category only (a '*' carve-out never conflicts with a
    concrete-category carve-out on category grounds)."""
    new_start = parse_date(start_str, "start_date")
    new_end = parse_date(end_str, "end_date")
    gap = timedelta(days=ADJACENCY_GAP_DAYS)
    for existing in store.carve_outs.values():
        if existing["contract_version_id"] != version_id:
            continue
        if existing["service_category"] != service_category:
            continue
        ex_start = parse_date(existing["start_date"], "start_date")
        ex_end = parse_date(existing["end_date"], "end_date")
        if new_start <= ex_end + gap and ex_start <= new_end + gap:
            return True
    return False
