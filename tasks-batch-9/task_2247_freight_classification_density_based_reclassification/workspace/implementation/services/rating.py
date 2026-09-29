"""Cube, density, class resolution and rating (PRD 3.1, 3.4, 3.7)."""
from decimal import Decimal

import db
from constants import (
    CUBIC_INCHES_PER_CUBIC_FOOT,
    HANDLING_FLOOR,
    LIABILITY_FLOOR,
    STOWABILITY_FLOOR,
    VOLUME_TIER_DISCOUNTS,
    WEIGHT_BREAK_FACTORS,
)
from util import D, rhu, rhu_int

ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def lines_of(shipment_id):
    rows = db.all_rows("shipment_lines", lambda r: r["shipment_id"] == shipment_id)
    rows.sort(key=lambda r: (r["line_no"], r["_seq"]))
    return rows


def profile_of(line):
    return db.get("commodity_profiles", line.get("commodity_profile_id"))


def program_of(shipment):
    return db.get("rate_programs", shipment.get("rate_program_id"))


def tariff_of(shipment):
    return db.get("tariff_versions", shipment.get("tariff_version_id"))


def accepted_finding(line):
    rows = db.all_rows(
        "inspection_findings",
        lambda r: r["shipment_line_id"] == line["id"] and r["status"] == "ACCEPTED",
    )
    return rows[-1] if rows else None


def accepted_findings_of_shipment(shipment):
    ids = {line["id"] for line in lines_of(shipment["id"])}
    return db.all_rows(
        "inspection_findings",
        lambda r: r["shipment_line_id"] in ids and r["status"] == "ACCEPTED",
    )


def active_agreement(shipment, profile):
    if profile is None:
        return None
    pickup = shipment.get("pickup_at")
    if pickup is None:
        return None

    def covers(a):
        return (
            a["status"] == "ACTIVE"
            and a["customer_id"] == shipment.get("customer_id")
            and a["commodity_profile_id"] == profile["id"]
            and a["effective_from"] <= pickup
            and pickup < a["effective_to"]
        )

    rows = db.all_rows("exception_agreements", covers)
    rows.sort(key=lambda a: (a["effective_from"], a["created_at"], a["_seq"]), reverse=True)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# constant tables
# ---------------------------------------------------------------------------
def class_floor(handling_code, stowability_code, liability_code):
    return max(
        HANDLING_FLOOR.get(handling_code, ZERO),
        STOWABILITY_FLOOR.get(stowability_code, ZERO),
        LIABILITY_FLOOR.get(liability_code, ZERO),
    )


def weight_break(total_weight):
    total = D(total_weight)
    for threshold, factor in WEIGHT_BREAK_FACTORS:
        if threshold <= total:
            return factor
    return WEIGHT_BREAK_FACTORS[-1][1]


def volume_tier(annual_gross_cents):
    gross = D(annual_gross_cents)
    for threshold, factor in VOLUME_TIER_DISCOUNTS:
        if D(threshold) <= gross:
            return factor
    return VOLUME_TIER_DISCOUNTS[-1][1]


def density_bracket(tariff, density):
    """First element whose min_density_pcf <= density (inclusive lower bound)."""
    if tariff is None or density is None:
        return None
    value = D(density)
    for element in tariff.get("density_breaks") or []:
        if D(element["min_density_pcf"]) <= value:
            return D(element["class_code"])
    return None


# ---------------------------------------------------------------------------
# cube and density (PRD 2.7 / 3.4)
# ---------------------------------------------------------------------------
def cube_and_density(length_in, width_in, height_in, pieces, weight_lb):
    per_piece = rhu(D(length_in) * D(width_in) * D(height_in) / CUBIC_INCHES_PER_CUBIC_FOOT, 3)
    cubic_ft = rhu(per_piece * D(pieces), 2)
    if cubic_ft == 0:
        density = rhu(ZERO, 2)
    else:
        density = rhu(D(weight_lb) / cubic_ft, 2)
    return cubic_ft, density


# ---------------------------------------------------------------------------
# class resolution (PRD 3.4, three ordered steps)
# ---------------------------------------------------------------------------
def resolve(shipment, line, mode):
    profile = profile_of(line)
    program = program_of(shipment)
    tariff = tariff_of(shipment)

    base = None
    source = "BOL_DECLARED"

    if mode == "INSPECTED":
        finding = accepted_finding(line)
        if finding is not None:
            if finding.get("finding_basis") == "COMMODITY_MISMATCH" and finding.get(
                "found_commodity_profile_id"
            ):
                profile = db.get("commodity_profiles", finding["found_commodity_profile_id"]) or profile
            base = D(finding["found_class_code"])
            source = "INSPECTION"
        else:
            mode = "MEASURED" if line.get("measured_density_pcf") is not None else "DECLARED"

    if base is None:
        if profile is not None and profile.get("classification_basis") == "FIXED_CLASS" and profile.get(
            "fixed_class_code"
        ) is not None:
            base = D(profile["fixed_class_code"])
            source = "FIXED_CLASS"
        elif mode == "MEASURED" and line.get("measured_density_pcf") is not None:
            bracket = density_bracket(tariff, line["measured_density_pcf"])
            if bracket is not None:
                base = bracket
                source = "DIMENSIONER"
            else:
                base = D(line["declared_class_code"])
                source = "BOL_DECLARED"
        else:
            base = D(line["declared_class_code"])
            source = "BOL_DECLARED"

    agreement = active_agreement(shipment, profile)
    if agreement is not None:
        candidate = D(agreement["agreed_class_code"])
        source = "FAK" if agreement.get("agreement_type") == "FAK" else "EXCEPTION_AGREEMENT"
    elif (
        program is not None
        and program.get("program_type") == "FAK"
        and program.get("fak_class_code") is not None
    ):
        candidate = D(program["fak_class_code"])
        source = "FAK"
    else:
        candidate = base

    floor = D(profile["min_class_floor"]) if profile is not None else ZERO
    effective = candidate if candidate >= floor else floor
    return {
        "base": base,
        "candidate": candidate,
        "effective": effective,
        "source": source,
        "floor_applied": floor > candidate,
    }


def declared_class(shipment, line):
    return resolve(shipment, line, "DECLARED")["effective"]


def line_mode(line):
    """MEASURED needs a measured density: a weight-only capture has no dimensioner basis."""
    if accepted_finding(line) is not None:
        return "INSPECTED"
    if line.get("measured_density_pcf") is not None:
        return "MEASURED"
    return "DECLARED"


def recompute_line_class(shipment, line):
    """Runs the three resolution steps and writes the line's class fields."""
    mode = line_mode(line)
    result = resolve(shipment, line, mode)
    line["effective_class_code"] = result["effective"]
    line["classification_source"] = result["source"]
    line["class_floor_applied"] = bool(result["floor_applied"])
    line["found_class_code"] = result["effective"] if mode != "DECLARED" else None
    return result


def revert_line_to_declared(shipment, line):
    """Full-overturn revert: found class dropped, provenance forced back to the BOL."""
    result = resolve(shipment, line, "DECLARED")
    line["found_class_code"] = None
    line["effective_class_code"] = result["effective"]
    line["classification_source"] = "BOL_DECLARED"
    line["class_floor_applied"] = bool(result["floor_applied"])
    return result


def is_reclassed(line):
    found = line.get("found_class_code")
    return found is not None and D(found) != D(line["declared_class_code"])


def refresh_delta_count(shipment, lines=None):
    rows = lines if lines is not None else lines_of(shipment["id"])
    count = sum(1 for line in rows if is_reclassed(line))
    if shipment.get("declared_vs_found_class_delta_count") != count:
        shipment["declared_vs_found_class_delta_count"] = count
        db.touch(shipment)
    return count


# ---------------------------------------------------------------------------
# shipment charge (PRD 3.4)
# ---------------------------------------------------------------------------
def rating_weight(line, mode):
    if mode == "DECLARED":
        return D(line["declared_weight_lb"])
    measured = line.get("measured_weight_lb")
    return D(measured if measured is not None else line["declared_weight_lb"])


def modeled_class(line, program, tariff_id=None):
    kind = program.get("program_type")
    if kind == "FAK":
        code = program.get("fak_class_code")
        return D(code) if code is not None else D(line["effective_class_code"])
    if kind == "DENSITY_BASED":
        pinned = db.get("tariff_versions", tariff_id or program.get("pinned_tariff_version_id"))
        density = line.get("measured_density_pcf")
        if density is None:
            density = line.get("declared_density_pcf")
        bracket = density_bracket(pinned, density)
        if bracket is not None:
            return bracket
        return D(line["effective_class_code"])
    return D(line["effective_class_code"])


def _rating_class(shipment, line, mode, program, class_fn, tariff_id):
    if class_fn is not None:
        override = class_fn(line)
        if override is not None:
            return D(override)
    if mode == "DECLARED":
        return declared_class(shipment, line)
    if mode == "MODELED":
        return modeled_class(line, program, tariff_id)
    return D(line["effective_class_code"])


def charge_raw(shipment, mode, program=None, class_fn=None, discount=None, tariff_id=None, lines=None):
    """The unrounded summed per-line amount; no rounding, no minimum charge."""
    program = program if program is not None else program_of(shipment)
    if program is None:
        return ZERO, ZERO
    rows = lines if lines is not None else lines_of(shipment["id"])
    total_weight = sum((rating_weight(line, mode) for line in rows), ZERO)
    wbf = weight_break(total_weight)
    disc = D(discount) if discount is not None else D(program.get("discount_pct") or 0)
    base_rate = D(program["base_rate_per_cwt_cents"])
    raw = ZERO
    for line in rows:
        weight = rating_weight(line, mode)
        cls = _rating_class(shipment, line, mode, program, class_fn, tariff_id)
        raw += (weight / 100) * base_rate * (cls / 100) * wbf * (1 - disc)
    return raw, wbf


def shipment_charge(shipment, mode, program=None, class_fn=None, tariff_id=None, lines=None):
    program = program if program is not None else program_of(shipment)
    if program is None:
        return 0
    rows = lines if lines is not None else lines_of(shipment["id"])
    if not rows:
        return 0
    raw, _ = charge_raw(shipment, mode, program, class_fn, tariff_id=tariff_id, lines=rows)
    return max(int(program.get("min_charge_cents") or 0), rhu_int(raw))


def line_charge(shipment, line, program=None, wbf=None, lines=None):
    """Informational per-line amount (PRD 3.4 final paragraph)."""
    program = program if program is not None else program_of(shipment)
    if program is None:
        return 0
    rows = lines if lines is not None else lines_of(shipment["id"])
    if wbf is None:
        total_weight = sum((rating_weight(row, "RECLASSED") for row in rows), ZERO)
        wbf = weight_break(total_weight)
    weight = rating_weight(line, "RECLASSED")
    cls = D(line.get("effective_class_code") or 0)
    disc = D(program.get("discount_pct") or 0)
    raw = (weight / 100) * D(program["base_rate_per_cwt_cents"]) * (cls / 100) * wbf * (1 - disc)
    return rhu_int(raw)


def recompute_line_charges(shipment, targets=None):
    """Refreshes line_charge_cents; the weight break always comes from the shipment total."""
    rows = lines_of(shipment["id"])
    program = program_of(shipment)
    if program is None:
        return
    total_weight = sum((rating_weight(row, "RECLASSED") for row in rows), ZERO)
    wbf = weight_break(total_weight)
    wanted = None if targets is None else {row["id"] for row in targets}
    for row in rows:
        if wanted is not None and row["id"] not in wanted:
            continue
        amount = line_charge(shipment, row, program=program, wbf=wbf, lines=rows)
        if row.get("line_charge_cents") != amount:
            row["line_charge_cents"] = amount
            db.touch(row)


# ---------------------------------------------------------------------------
# correction notice deltas (PRD 3.7)
# ---------------------------------------------------------------------------
def _line_amount(weight, cls, program):
    """Per-line weight break, per-line rounding, no minimum charge."""
    weight = D(weight)
    disc = D(program.get("discount_pct") or 0)
    raw = (
        (weight / 100)
        * D(program["base_rate_per_cwt_cents"])
        * (D(cls) / 100)
        * weight_break(weight)
        * (1 - disc)
    )
    return rhu_int(raw)


def provisional_delta(shipment, program=None, lines=None):
    program = program if program is not None else program_of(shipment)
    if program is None:
        return 0
    rows = lines if lines is not None else lines_of(shipment["id"])
    total = 0
    for line in rows:
        after = _line_amount(
            rating_weight(line, "RECLASSED"), D(line.get("effective_class_code") or 0), program
        )
        before = _line_amount(
            D(line["declared_weight_lb"]), declared_class(shipment, line), program
        )
        total += after - before
    return total


def final_delta(shipment, program=None, lines=None):
    program = program if program is not None else program_of(shipment)
    if program is None:
        return 0
    rows = lines if lines is not None else lines_of(shipment["id"])
    if not rows:
        return 0
    reclassed = shipment_charge(shipment, "RECLASSED", program=program, lines=rows)
    declared = shipment_charge(shipment, "DECLARED", program=program, lines=rows)
    return reclassed - declared
