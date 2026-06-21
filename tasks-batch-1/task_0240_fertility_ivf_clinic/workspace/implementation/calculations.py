"""Calculation rules (PRD §3, SCAFFOLD §1.3). All money in integer cents.

Coverage multiplication uses Decimal with ROUND_HALF_UP, applied ONCE to the
summed covered total (SUM-then-round, never per-line). Cap is applied AFTER
rounding.
"""

from decimal import Decimal, ROUND_HALF_UP

CANCELLATION_FEES = {
    "DRAFT": 0,
    "STIM": 50000,
    "RETRIEVAL": 150000,
    "FERTILIZATION": 250000,
    # FRESH_TRANSFER / FREEZE_ALL are not reachable cancel-from-states that
    # carry a defined fee tier; the only non-terminal stages with fees are the
    # four above. The PRD enumerates fees only up to FERTILIZATION.
}


def round_half_up_cents(value):
    """Round a numeric/Decimal value half-up to a whole integer of cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def medication_line_total(start_day_offset, end_day_offset, daily_dose_units,
                          unit_price_cents):
    """days (inclusive) * daily_dose_units * unit_price_cents. Exact integer."""
    days = (end_day_offset - start_day_offset) + 1
    return days * daily_dose_units * unit_price_cents


def cancellation_fee(reached_status):
    return CANCELLATION_FEES.get(reached_status, 0)


def embryo_utilization_rate(embryos_fertilized, oocytes_retrieved):
    """embryos/oocytes rounded half-up to 4 dp; 0.0 when denominator is 0."""
    if oocytes_retrieved == 0:
        return 0.0
    raw = Decimal(embryos_fertilized) / Decimal(oocytes_retrieved)
    rounded = raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(rounded)


def cycle_cost_estimate(package, stim_med_gross, cryo_count):
    """Forward-looking estimate. insurer NOT capped. Returns estimated_patient_owed."""
    base = package["base_price_cents"]
    cryo_gross = cryo_count * package["annual_cryo_storage_cents"]
    gross = base + stim_med_gross + cryo_gross

    covered_gross = base
    if package["stim_med_covered"]:
        covered_gross += stim_med_gross
    if package["cryo_storage_covered"]:
        covered_gross += cryo_gross

    coverage_pct = Decimal(str(package["coverage_pct"]))
    insurer_est = round_half_up_cents(Decimal(covered_gross) * coverage_pct)
    return gross - insurer_est


def cycle_cost_settlement(package, stim_med_gross, cryo_gross, cancellation,
                          prior_insurer_paid):
    """Chronological settlement with lifetime cap. Returns a dict of figures
    plus the frozen line_items snapshot."""
    base = package["base_price_cents"]
    gross_charge = base + stim_med_gross + cryo_gross + cancellation

    covered_gross = base
    if package["stim_med_covered"]:
        covered_gross += stim_med_gross
    if package["cryo_storage_covered"]:
        covered_gross += cryo_gross
    # cancellation fee is NEVER covered (excluded from covered_gross).

    coverage_pct = Decimal(str(package["coverage_pct"]))
    insurer_raw = round_half_up_cents(Decimal(covered_gross) * coverage_pct)

    headroom = max(0, package["lifetime_coverage_cap_cents"] - prior_insurer_paid)
    insurer_paid = min(insurer_raw, headroom)
    final_patient_owed = gross_charge - insurer_paid

    # Build per-line snapshot. insurer_cents/patient_cents per line are derived
    # so that the lines reconcile to the (possibly capped) totals. The cap is a
    # cycle-level reduction of the covered insurer amount, so we apportion the
    # post-cap insurer total back across covered lines, with any rounding
    # remainder absorbed by the last covered line.
    lines = []
    covered_lines = []  # indices into `lines` that are covered

    def add_line(category, gross_cents, covered):
        idx = len(lines)
        lines.append({
            "category": category,
            "gross_cents": gross_cents,
            "covered": covered,
            "insurer_cents": 0,
            "patient_cents": gross_cents,
        })
        if covered:
            covered_lines.append(idx)

    add_line("BASE", base, True)
    if stim_med_gross > 0 or package["stim_med_covered"]:
        add_line("STIM_MED", stim_med_gross, package["stim_med_covered"])
    elif stim_med_gross > 0:
        add_line("STIM_MED", stim_med_gross, False)
    if cryo_gross > 0:
        add_line("CRYO_STORAGE", cryo_gross, package["cryo_storage_covered"])
    if cancellation > 0:
        add_line("CANCELLATION", cancellation, False)

    # Distribute insurer_paid across covered lines proportional to gross,
    # remainder on the last covered line.
    if covered_lines and insurer_paid > 0:
        covered_total_gross = sum(lines[i]["gross_cents"] for i in covered_lines)
        allocated = 0
        for k, i in enumerate(covered_lines):
            if k == len(covered_lines) - 1:
                share = insurer_paid - allocated
            else:
                if covered_total_gross == 0:
                    share = 0
                else:
                    share = (lines[i]["gross_cents"] * insurer_paid) // covered_total_gross
                allocated += share
            lines[i]["insurer_cents"] = share
            lines[i]["patient_cents"] = lines[i]["gross_cents"] - share

    gross_total = sum(l["gross_cents"] for l in lines)
    insurer_total = sum(l["insurer_cents"] for l in lines)
    patient_total = gross_total - insurer_total

    return {
        "gross_charge_cents": gross_charge,
        "insurer_paid_cents": insurer_paid,
        "final_patient_owed_cents": final_patient_owed,
        "line_items": lines,
        "gross_total_cents": gross_total,
        "insurer_total_cents": insurer_total,
        "patient_total_cents": patient_total,
    }
