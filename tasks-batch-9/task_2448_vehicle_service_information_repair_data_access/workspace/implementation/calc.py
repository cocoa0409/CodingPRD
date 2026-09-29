"""Calculations -- PRD 2.8 rounding discipline, 3.1, 3.3, 3.4, 3.7 and 3.9.

Every intermediate quotient is held as an exact rational (fractions.Fraction);
rounding happens only at the points the PRD identifies, always round half up.
"""

from fractions import Fraction

from store import store, whole_days

# -- constants ------------------------------------------------------------
TIER_MULT = {"BASIC": Fraction(100, 100), "PRO": Fraction(85, 100), "ENTERPRISE": Fraction(70, 100)}
SEAT_STEP = Fraction(5, 100)
INCLUDED_SEATS = 3

PARITY_MAX_INDEX = Fraction(115, 100)
DAYS_PER_MONTH = 30

SESSION_BASE_CENTS = 2500
VIN_CREDENTIAL_CENTS = 300
JOB_CENTS = {"IMMOBILIZER_KEY": 4000, "MODULE_FLASH": 3000, "ADAS_CALIBRATION": 6000}
DISCOUNT_TIER_1_CENTS = 5000
DISCOUNT_TIER_2_CENTS = 10000
IMMOBILIZER_SURCHARGE_PCT = Fraction(12, 100)
STANDARD_SURCHARGE_PCT = Fraction(4, 100)

BILLABLE_JOB_STATUSES = ("IN_PROGRESS", "COMPLETED", "REVALIDATION_REQUIRED")


def round_half_up(value, places=0):
    """Round an exact rational half up to `places` decimals; returns a Fraction."""
    fraction = Fraction(value)
    scale = Fraction(10) ** places
    scaled = fraction * scale
    numerator, denominator = scaled.numerator, scaled.denominator
    if numerator >= 0:
        quotient = (2 * numerator + denominator) // (2 * denominator)
    else:
        # magnitude increased on an exact half
        quotient = -((2 * -numerator + denominator) // (2 * denominator))
    return Fraction(quotient) / scale


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def as_number(fraction, places):
    """Render a rounded rational as a JSON number carrying `places` decimals."""
    return float(round_half_up(fraction, places))


# -- parity index (PRD 3.1) ----------------------------------------------


def effective_cents_per_system_day(monthly_cents, covered_system_count):
    return Fraction(monthly_cents, covered_system_count * DAYS_PER_MONTH)


def parity_index(manufacturer, basis):
    """Returns (index_fraction, parity_status) for LIST_BASIS or EFFECTIVE_BASIS."""
    if basis == "LIST_BASIS":
        index = round_half_up(
            Fraction(
                manufacturer["independent_list_monthly_cents"],
                manufacturer["oem_dealer_monthly_cents"],
            ),
            4,
        )
    else:
        independent = effective_cents_per_system_day(
            manufacturer["independent_list_monthly_cents"],
            manufacturer["independent_covered_system_count"],
        )
        dealer = effective_cents_per_system_day(
            manufacturer["oem_dealer_monthly_cents"],
            manufacturer["oem_dealer_covered_system_count"],
        )
        index = round_half_up(independent / dealer, 4)
    status = "COMPLIANT" if index <= PARITY_MAX_INDEX else "NON_COMPLIANT"
    return index, status


def stamp_list_basis_parity(manufacturer):
    """Only the list-basis verdict is ever persisted (PRD 3.1)."""
    index, status = parity_index(manufacturer, "LIST_BASIS")
    manufacturer["parity_index"] = float(index)
    manufacturer["parity_status"] = status


# -- entitlement charge (PRD 3.3 / 3.4) ----------------------------------


def _seat_factor(seats_total):
    return 1 + SEAT_STEP * max(0, seats_total - INCLUDED_SEATS)


def charge_lines(license_row):
    """The charge lines are exactly License.covered_system_area_ids, ordered by code."""
    lines = []
    for area_id in license_row["covered_system_area_ids"]:
        area = store.system_areas.get(area_id)
        lines.append((area["code"] if area else "", area_id))
    lines.sort(key=lambda pair: pair[0])
    return lines


def provisional_charge(shop, license_row, entitlement_model, seats_total, vin_quota):
    tier_mult = TIER_MULT[shop["tier"]]
    seat_factor = _seat_factor(seats_total)
    if entitlement_model == "SUBSCRIPTION":
        n_lines = len(charge_lines(license_row))
        per_line_base = Fraction(license_row["monthly_fee_cents"], n_lines)
        # PINNED ROUNDING ORDER: round EACH LINE to whole cents, THEN sum.
        line_charge = round_half_up_int(per_line_base * tier_mult * seat_factor)
        return line_charge * n_lines
    return round_half_up_int(Fraction(license_row["per_vehicle_fee_cents"]) * vin_quota * tier_mult)


def distinct_consumed_vins(entitlement):
    """Distinct VINs over the entitlement's sessions in ACTIVE/COMPLETED/EXPIRED/TERMINATED."""
    seat_ids = set(
        seat["id"]
        for seat in store.seat_assignments.values()
        if seat["entitlement_id"] == entitlement["id"]
    )
    vins = set()
    for session in store.gateway_sessions.values():
        if session["seat_assignment_id"] not in seat_ids:
            continue
        if session["status"] in ("ACTIVE", "COMPLETED", "EXPIRED", "TERMINATED"):
            vins.add(session["vin"])
    return vins


def final_charge(entitlement, shop, license_row):
    if entitlement["entitlement_model"] == "SUBSCRIPTION":
        window_start = entitlement["_window_start"]
        window_end = entitlement["_window_end"]
        window_days = whole_days(window_end, window_start)
        reference = min(store.now(), window_end)
        elapsed_days = max(0, whole_days(reference, window_start))
        if window_days <= 0:
            return 0
        return round_half_up_int(
            Fraction(entitlement["charged_cents"] * elapsed_days, window_days)
        )
    vins_consumed = len(distinct_consumed_vins(entitlement))
    return round_half_up_int(
        Fraction(license_row["per_vehicle_fee_cents"]) * vins_consumed * TIER_MULT[shop["tier"]]
    )


# -- gateway access fee (PRD 3.7) ----------------------------------------


def gateway_access_fee(session):
    """Five pinned steps.  Job statuses are read BEFORE the exit's own cascade."""
    jobs = [
        job
        for job in store.jobs.values()
        if job["session_id"] == session["id"] and job["status"] in BILLABLE_JOB_STATUSES
    ]
    base_subtotal = SESSION_BASE_CENTS + VIN_CREDENTIAL_CENTS
    for job in jobs:
        base_subtotal += JOB_CENTS[job["job_type"]]

    if base_subtotal < DISCOUNT_TIER_1_CENTS:
        discount_pct = Fraction(0)
    elif base_subtotal < DISCOUNT_TIER_2_CENTS:
        discount_pct = Fraction(5, 100)
    else:
        discount_pct = Fraction(10, 100)
    discount = round_half_up_int(Fraction(base_subtotal) * discount_pct)

    if any(job["job_type"] == "IMMOBILIZER_KEY" for job in jobs):
        surcharge_pct = IMMOBILIZER_SURCHARGE_PCT
    else:
        surcharge_pct = STANDARD_SURCHARGE_PCT
    surcharge = round_half_up_int(Fraction(base_subtotal) * surcharge_pct)

    total = base_subtotal - discount + surcharge
    return base_subtotal, discount, surcharge, total


# -- coverage completeness (PRD 3.9) -------------------------------------


def _cell_universe(shop_id):
    """De-duplicated (vehicle model, system area) cells of a shop's ACTIVE entitlements."""
    license_ids = set()
    for entitlement in store.entitlements.values():
        if entitlement["shop_id"] == shop_id and entitlement["status"] == "ACTIVE":
            license_ids.add(entitlement["license_id"])
    cells = {}
    for license_id in license_ids:
        license_row = store.licenses.get(license_id)
        if license_row is None:
            continue
        models = [
            model
            for model in store.vehicle_models.values()
            if model["manufacturer_id"] == license_row["manufacturer_id"]
        ]
        for model in models:
            for area_id in license_row["covered_system_area_ids"]:
                area = store.system_areas.get(area_id)
                if area is None:
                    continue
                cells[(model["id"], area_id)] = (model, area)
    return cells


def _versions_for(model_id, area_id, publication_type):
    publication_ids = set(
        publication["id"]
        for publication in store.publications.values()
        if publication["vehicle_model_id"] == model_id
        and publication["system_area_id"] == area_id
        and publication["publication_type"] == publication_type
    )
    return [
        version
        for version in store.publication_versions.values()
        if version["publication_id"] in publication_ids
    ]


def _strict(versions):
    return any(
        version["review_status"] == "VALIDATED" and version["distribution_status"] == "PUBLISHED"
        for version in versions
    )


def _loose(versions):
    return any(version["distribution_status"] == "PUBLISHED" for version in versions)


def classify_cell(model, area):
    procedures = _versions_for(model["id"], area["id"], "REPAIR_PROCEDURE")
    calibrations = _versions_for(model["id"], area["id"], "CALIBRATION_DOC")
    needs_calibration = bool(area["requires_calibration_doc"])

    if _strict(procedures) and (not needs_calibration or _strict(calibrations)):
        return "COVERED"
    if _loose(procedures) and (not needs_calibration or _loose(calibrations)):
        return "DEGRADED"
    return "GAP"


def coverage_report(shop_id, basis):
    cells = _cell_universe(shop_id)
    total_cells = len(cells)
    covered_cells = 0
    degraded_cells = 0
    gap_cells = 0
    gaps = []
    for (model_id, area_id), (model, area) in cells.items():
        state = classify_cell(model, area)
        if state == "COVERED":
            covered_cells += 1
        elif state == "DEGRADED":
            degraded_cells += 1
        else:
            gap_cells += 1
        if state != "COVERED":
            gaps.append(
                {
                    "vehicle_model_id": model_id,
                    "model_code": model["model_code"],
                    "system_area_id": area_id,
                    "system_area_code": area["code"],
                    "cell_state": state,
                }
            )
    # ordered by (model_code ASC, system area code ASC); no id enters the ordering
    gaps.sort(key=lambda entry: (entry["model_code"], entry["system_area_code"]))

    numerator = covered_cells if basis == "EFFECTIVE" else covered_cells + degraded_cells
    if total_cells == 0:
        completeness = Fraction(0)
    else:
        completeness = round_half_up(Fraction(100 * numerator, total_cells), 2)
    return {
        "shop_id": shop_id,
        "basis": basis,
        "total_cells": total_cells,
        "covered_cells": covered_cells,
        "degraded_cells": degraded_cells,
        "gap_cells": gap_cells,
        "completeness_pct": float(completeness),
        "gaps": gaps,
    }


def stamp_shop_coverage(shop):
    """The stored figure is always the EFFECTIVE-basis number (PRD 3.9)."""
    report = coverage_report(shop["id"], "EFFECTIVE")
    shop["coverage_completeness_pct"] = report["completeness_pct"]


def stamp_coverage_for_cell(model_id, area_id):
    """Recompute the stored figure for every shop whose ACTIVE entitlement covers a cell."""
    model = store.vehicle_models.get(model_id)
    if model is None:
        return
    shop_ids = set()
    for entitlement in store.entitlements.values():
        if entitlement["status"] != "ACTIVE":
            continue
        license_row = store.licenses.get(entitlement["license_id"])
        if license_row is None:
            continue
        if license_row["manufacturer_id"] != model["manufacturer_id"]:
            continue
        if area_id not in license_row["covered_system_area_ids"]:
            continue
        shop_ids.add(entitlement["shop_id"])
    for shop_id in shop_ids:
        shop = store.shops.get(shop_id)
        if shop is not None:
            stamp_shop_coverage(shop)


# -- seat ledger (PRD 3.5) -----------------------------------------------


def recompute_seat_ledger(entitlement):
    seats_assigned = sum(
        1
        for seat in store.seat_assignments.values()
        if seat["entitlement_id"] == entitlement["id"] and seat["status"] == "ACTIVE"
    )
    entitlement["seats_assigned"] = seats_assigned
    entitlement["seats_available"] = entitlement["seats_total"] - seats_assigned
