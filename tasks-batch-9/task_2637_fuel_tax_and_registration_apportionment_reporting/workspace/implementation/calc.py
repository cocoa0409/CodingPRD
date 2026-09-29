"""Every pinned calculation from PRD.md §3 / SCAFFOLD.yaml calculations.

Rounding order matters and is pinned:
  * fleet_mpg is rounded to 2dp BEFORE dividing any jurisdiction's taxable miles
  * totals sum already-rounded per-line amounts
  * risk scores round exactly once, over the full-precision weighted sum
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from common import (
    DB,
    D,
    ZERO,
    gallons,
    miles,
    money,
    parse_date,
    parse_instant,
    percent,
    ratio,
    rnd,
    whole,
)

# --- constants (SCAFFOLD.yaml calculations.*.constants) --------------------
GAP_TOLERANCE_MILES = D("5.0")
LEG_MILEAGE_TOLERANCE_MILES = D("0.5")
RECONSTRUCTION_WINDOW_DAYS = 120
RECORD_RETENTION_DAYS = 1460
UNSUBSTANTIATED_AUDIT_FLAG_RATIO = D("0.1500")
RECONSTRUCTION_UPLIFT_FACTOR = D("1.100")
RECONSTRUCTED_MILEAGE_PENALTY_RATIO = D("0.1000")
PENALTY_RATE = D("0.10")
PENALTY_FLOOR_USD = D("100.00")
ESTIMATED_DISTANCE_FLOOR_MILES = D("20000.0")
TRANSFER_ADMIN_FEE = D("15.00")
DRIVER_HANDOVER_BUFFER_DAYS = 2
RATIO_WEIGHT = D("40")
RATIO_SATURATION_RATIO = D("0.25")
MPG_WEIGHT = D("25")
MPG_INDUSTRY_BASELINE = D("6.50")
MPG_VARIANCE_BAND = D("0.20")
LATE_FILING_WEIGHT = D("5")
RETENTION_WEIGHT = D("20")
RETENTION_SATURATION_COUNT = D("4")
RETENTION_PENALTY_WEIGHT = D("30")
AUDIT_SELECTION_THRESHOLD = 70
LICENSE_SUSPENSION_THRESHOLD = 90


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------


def carrier_trips(carrier_id):
    return [t for t in DB.trip_records.values() if t["carrier_id"] == carrier_id]


def vehicle_trips(vehicle_id):
    return [t for t in DB.trip_records.values() if t["vehicle_id"] == vehicle_id]


def trip_legs(trip_id, status=None):
    out = [l for l in DB.mileage_legs.values() if l["trip_record_id"] == trip_id]
    if status is not None:
        out = [l for l in out if l["leg_status"] == status]
    return sorted(out, key=lambda l: (l["leg_sequence"], l["created_at"], l["_seq"]))


def active_leg_total(trip_id):
    total = ZERO
    for leg in trip_legs(trip_id, "ACTIVE"):
        total += leg["leg_miles"]
    return miles(total)


def jurisdiction_by_code(code):
    for row in DB.jurisdictions.values():
        if row["jurisdiction_code"] == code:
            return row
    return None


def weight_group_fee(jurisdiction_code, weight_group_code):
    for row in DB.weight_group_fees.values():
        if (row["jurisdiction_code"] == jurisdiction_code
                and row["weight_group_code"] == weight_group_code):
            return row
    return None


def carrier_vehicles(carrier_id, registration_year=None):
    out = [v for v in DB.vehicles.values() if v["carrier_id"] == carrier_id]
    if registration_year is not None:
        out = [v for v in out if v["registration_year"] == registration_year]
    return out


def apportioned_vehicle_count(carrier_id, registration_year):
    return len([
        v for v in carrier_vehicles(carrier_id, registration_year)
        if v["vehicle_status"] in ("PENDING", "ACTIVE")
    ])


def vehicle_credentials(vehicle_id):
    return [c for c in DB.credentials.values() if c["vehicle_id"] == vehicle_id]


def derive_credential_status(vehicle_id):
    """PRD §2.9 — the credential dimension of the Vehicle parallel state pair."""
    live = [
        c for c in vehicle_credentials(vehicle_id)
        if c["credential_status"] in ("ISSUED", "DISTRIBUTED")
    ]
    if not live:
        return "NONE"
    if all(c["credential_status"] == "DISTRIBUTED" for c in live):
        return "DISTRIBUTED"
    return "ISSUED"


def schedule_lines(application_id, status=None):
    out = [
        l for l in DB.schedule_lines.values()
        if l["registration_application_id"] == application_id
    ]
    if status is not None:
        out = [l for l in out if l["line_status"] == status]
    return sorted(out, key=lambda l: (l["jurisdiction_code"], l["created_at"], l["_seq"]))


def return_lines(return_id, status=None):
    out = [l for l in DB.return_lines.values() if l["fuel_tax_return_id"] == return_id]
    if status is not None:
        out = [l for l in out if l["line_status"] == status]
    return sorted(out, key=lambda l: (l["jurisdiction_code"], l["created_at"], l["_seq"]))


# --------------------------------------------------------------------------
# mileage_gap_detection
# --------------------------------------------------------------------------


def predecessor_trip(vehicle_id, trip_start, exclude_id=None):
    candidates = []
    for trip in vehicle_trips(vehicle_id):
        if exclude_id is not None and trip["id"] == exclude_id:
            continue
        if trip["trip_status"] == "REJECTED":
            continue
        if trip["_start_dt"] >= trip_start:
            continue
        candidates.append(trip)
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t["_start_dt"], t["created_at"], t["_seq"]))
    return candidates[-1]


def gap_from_previous(vehicle_id, trip_start, start_odometer):
    prior = predecessor_trip(vehicle_id, trip_start)
    if prior is None:
        return miles(ZERO)
    return miles(D(start_odometer) - D(prior["end_odometer"]))


# --------------------------------------------------------------------------
# carrier_unsubstantiated_mileage_ratio
# --------------------------------------------------------------------------


def recompute_carrier_ratio(carrier):
    numerator = ZERO
    denominator = ZERO
    for trip in carrier_trips(carrier["id"]):
        if trip["trip_status"] == "REJECTED":
            continue
        denominator += trip["odometer_delta_miles"]
        if trip["trip_status"] in ("GAP_FLAGGED", "RECONSTRUCTED"):
            numerator += trip["odometer_delta_miles"]
    if denominator == 0:
        value = ratio(ZERO)
    else:
        value = ratio(numerator / denominator)
    carrier["unsubstantiated_mileage_ratio"] = value
    carrier["audit_flag"] = value > UNSUBSTANTIATED_AUDIT_FLAG_RATIO
    return value


# --------------------------------------------------------------------------
# quarter windows
# --------------------------------------------------------------------------


def quarter_window(filing_year, filing_quarter):
    start_month = 3 * filing_quarter - 2
    start = datetime(filing_year, start_month, 1, tzinfo=timezone.utc)
    end_month = 3 * filing_quarter + 1
    if end_month > 12:
        end = datetime(filing_year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(filing_year, end_month, 1, tzinfo=timezone.utc)
    return start, end


def quarter_date_window(filing_year, filing_quarter):
    start, end = quarter_window(filing_year, filing_quarter)
    return start.date(), end.date()


# --------------------------------------------------------------------------
# quarterly_fuel_tax_settlement (+ reconstructed_mileage_penalty)
# --------------------------------------------------------------------------


def quarter_trips(carrier_id, filing_year, filing_quarter):
    start, end = quarter_window(filing_year, filing_quarter)
    return [
        t for t in carrier_trips(carrier_id)
        if t["trip_status"] == "ACCEPTED" and start <= t["_start_dt"] < end
    ]


def quarter_purchases(carrier_id, filing_year, filing_quarter):
    start, end = quarter_date_window(filing_year, filing_quarter)
    out = []
    for purchase in DB.fuel_purchases.values():
        if purchase["carrier_id"] != carrier_id:
            continue
        if purchase["purchase_status"] != "ACCEPTED":
            continue
        day = purchase["_purchase_day"]
        if start <= day < end:
            out.append(purchase)
    return out


def settle_quarter(carrier_id, filing_year, filing_quarter, basis):
    """Returns a dict of the totals plus the ordered per-jurisdiction line dicts.
    Raises nothing — the caller enforces ERR_NO_TAX_PAID_GALLONS and
    ERR_NO_ACCEPTED_MILEAGE in the pinned order using the returned figures."""
    taxable_miles = {}
    reconstructed_by_j = {}
    for trip in quarter_trips(carrier_id, filing_year, filing_quarter):
        if basis == "AUDIT_BASIS" and trip["mileage_source"] == "MANUAL_RECONSTRUCTION":
            uplift = RECONSTRUCTION_UPLIFT_FACTOR
        else:
            uplift = D("1.000")
        is_recon = trip["mileage_source"] == "MANUAL_RECONSTRUCTION"
        for leg in trip_legs(trip["id"], "ACTIVE"):
            effective = miles(leg["leg_miles"] * uplift)
            code = leg["jurisdiction_code"]
            taxable_miles[code] = taxable_miles.get(code, ZERO) + effective
            if is_recon:
                reconstructed_by_j[code] = reconstructed_by_j.get(code, ZERO) + effective

    for code in list(taxable_miles.keys()):
        taxable_miles[code] = miles(taxable_miles[code])
    total_fleet_miles = miles(sum(taxable_miles.values(), ZERO))

    tax_paid = {}
    for purchase in quarter_purchases(carrier_id, filing_year, filing_quarter):
        code = purchase["jurisdiction_code"]
        tax_paid[code] = tax_paid.get(code, ZERO) + purchase["gallons"]
    for code in list(tax_paid.keys()):
        tax_paid[code] = gallons(tax_paid[code])
    total_tax_paid_gallons = gallons(sum(tax_paid.values(), ZERO))

    result = {
        "total_fleet_miles": total_fleet_miles,
        "total_tax_paid_gallons": total_tax_paid_gallons,
        "fleet_mpg": None,
        "lines": [],
        "total_net_tax_due": money(ZERO),
        "reconstructed_mileage_ratio": ratio(ZERO),
        "reconstruction_penalty_amount": money(ZERO),
        "total_amount_due": money(ZERO),
    }
    if total_tax_paid_gallons <= 0 or total_fleet_miles <= 0:
        return result

    fleet_mpg = money(total_fleet_miles / total_tax_paid_gallons)
    result["fleet_mpg"] = fleet_mpg

    codes = sorted(set(list(taxable_miles.keys()) + list(tax_paid.keys())))
    total_net_tax_due = ZERO
    for code in codes:
        line_miles = taxable_miles.get(code, miles(ZERO))
        line_paid = tax_paid.get(code, gallons(ZERO))
        taxable_gallons = gallons(line_miles / fleet_mpg) if fleet_mpg != 0 else gallons(ZERO)
        net_taxable_gallons = gallons(taxable_gallons - line_paid)
        jurisdiction = jurisdiction_by_code(code)
        rate = jurisdiction["fuel_tax_rate_per_gallon"] if jurisdiction else ZERO
        base_tax_amount = money(net_taxable_gallons * rate)
        if jurisdiction is not None and jurisdiction["is_surcharge_jurisdiction"]:
            surcharge_amount = money(taxable_gallons * jurisdiction["surcharge_rate_per_gallon"])
        else:
            surcharge_amount = money(ZERO)
        net_tax_amount = money(base_tax_amount + surcharge_amount)
        total_net_tax_due += net_tax_amount
        result["lines"].append({
            "jurisdiction_code": code,
            "taxable_miles": line_miles,
            "taxable_gallons": taxable_gallons,
            "tax_paid_gallons": line_paid,
            "net_taxable_gallons": net_taxable_gallons,
            "base_tax_amount": base_tax_amount,
            "surcharge_amount": surcharge_amount,
            "net_tax_amount": net_tax_amount,
        })

    total_net_tax_due = money(total_net_tax_due)
    result["total_net_tax_due"] = total_net_tax_due

    reconstructed_miles = miles(sum(reconstructed_by_j.values(), ZERO))
    if total_fleet_miles == 0:
        recon_ratio = ratio(ZERO)
    else:
        recon_ratio = ratio(reconstructed_miles / total_fleet_miles)
    result["reconstructed_mileage_ratio"] = recon_ratio

    if recon_ratio > RECONSTRUCTED_MILEAGE_PENALTY_RATIO:
        computed = money(PENALTY_RATE * max(total_net_tax_due, money(ZERO)))
        penalty = max(PENALTY_FLOOR_USD, computed)
    else:
        penalty = money(ZERO)
    result["reconstruction_penalty_amount"] = money(penalty)
    result["total_amount_due"] = money(total_net_tax_due + penalty)
    return result


# --------------------------------------------------------------------------
# apportioned_registration_fee
# --------------------------------------------------------------------------


def effective_distance(reported, distance_basis):
    if distance_basis == "ESTIMATED_DISTANCE_BASIS":
        return miles(max(D(reported), ESTIMATED_DISTANCE_FLOOR_MILES))
    return miles(reported)


def apportion_application(application):
    """Writes effective_distance_miles / apportion_percent /
    jurisdiction_fee_amount on the ACTIVE lines and returns the totals."""
    lines = schedule_lines(application["id"], "ACTIVE")
    basis = application["distance_basis"]
    for line in lines:
        line["effective_distance_miles"] = effective_distance(
            line["reported_distance_miles"], basis
        )
    fleet_total = miles(sum((l["effective_distance_miles"] for l in lines), ZERO))
    application["fleet_total_distance_miles"] = fleet_total

    count = application["apportioned_vehicle_count"]
    base_fee_total = ZERO
    for line in lines:
        if fleet_total == 0:
            line["apportion_percent"] = percent(ZERO)
        else:
            line["apportion_percent"] = percent(
                line["effective_distance_miles"] / fleet_total
            )
        fee_row = weight_group_fee(line["jurisdiction_code"], application["weight_group_code"])
        annual = fee_row["annual_fee_amount"] if fee_row else ZERO
        line["jurisdiction_fee_amount"] = money(
            line["apportion_percent"] * annual * D(count)
        )
        base_fee_total += line["jurisdiction_fee_amount"]
    base_fee_total = money(base_fee_total)
    application["base_fee_total"] = base_fee_total
    application["total_apportioned_fee"] = base_fee_total
    return base_fee_total


# --------------------------------------------------------------------------
# fleet_change_fee_delta
# --------------------------------------------------------------------------


def per_vehicle_full_year(application):
    """Priced off the application's FROZEN ACTIVE schedule lines — percentages
    are never recomputed for a supplement."""
    total = ZERO
    for line in schedule_lines(application["id"], "ACTIVE"):
        fee_row = weight_group_fee(line["jurisdiction_code"], application["weight_group_code"])
        annual = fee_row["annual_fee_amount"] if fee_row else ZERO
        total += line["apportion_percent"] * annual
    return money(total)


def fleet_change_fee_delta(application, change_type, effective_date_str):
    pv = per_vehicle_full_year(application)
    month = parse_date(effective_date_str).month
    if change_type == "ADDITION":
        prorate_months = 13 - month
        delta = money(pv * D(prorate_months) / D(12))
    elif change_type == "DELETION":
        prorate_months = 12 - month
        delta = -money(pv * D(prorate_months) / D(12))
    else:
        add_months = 13 - month
        credit_months = 12 - month
        prorate_months = add_months
        delta = money(
            money(pv * D(add_months) / D(12))
            - money(pv * D(credit_months) / D(12))
            + TRANSFER_ADMIN_FEE
        )
    return prorate_months, money(delta)


def approved_delta_sum(application_id):
    total = ZERO
    for row in DB.fleet_change_requests.values():
        if row["registration_application_id"] != application_id:
            continue
        if row["change_status"] != "APPROVED":
            continue
        total += row["fee_delta"]
    return total


def refresh_total_apportioned_fee(application):
    application["total_apportioned_fee"] = money(
        application["base_fee_total"] + approved_delta_sum(application["id"])
    )
    return application["total_apportioned_fee"]


# --------------------------------------------------------------------------
# credential_validity_window
# --------------------------------------------------------------------------


def december_31(year):
    return "%04d-12-31" % year


def credential_window_conflict(driver_id, credential_type, new_from, new_to,
                               exclude_credential_id=None):
    """Closed intervals, both sides buffered by DRIVER_HANDOVER_BUFFER_DAYS."""
    buffer_days = timedelta(days=DRIVER_HANDOVER_BUFFER_DAYS)
    for other in DB.credentials.values():
        if exclude_credential_id is not None and other["id"] == exclude_credential_id:
            continue
        if other["credential_status"] != "DISTRIBUTED":
            continue
        if other["distributed_to_driver_id"] != driver_id:
            continue
        if other["credential_type"] != credential_type:
            continue
        other_from = parse_date(other["valid_from_date"])
        other_to = parse_date(other["valid_to_date"])
        if other_from is None or other_to is None:
            continue
        if (new_from - buffer_days <= other_to + buffer_days
                and new_to + buffer_days >= other_from - buffer_days):
            return other
    return None


# --------------------------------------------------------------------------
# audit_risk_score
# --------------------------------------------------------------------------


def audit_risk_score(carrier, late_filing_count, retention_deficiency_count):
    r = D(carrier["unsubstantiated_mileage_ratio"])
    total = RATIO_WEIGHT * min(D(1), r / RATIO_SATURATION_RATIO)
    mpg = carrier["latest_prepared_fleet_mpg"]
    if mpg is not None:
        variance = abs(D(mpg) - MPG_INDUSTRY_BASELINE) / MPG_INDUSTRY_BASELINE
        total += MPG_WEIGHT * min(D(1), variance / MPG_VARIANCE_BAND)
    total += LATE_FILING_WEIGHT * min(D(3), D(late_filing_count))
    total += RETENTION_WEIGHT * min(
        D(1), D(retention_deficiency_count) / RETENTION_SATURATION_COUNT
    )
    return min(100, whole(total))


def post_review_score(risk_score, deficiency_ratio):
    return min(100, risk_score + whole(RETENTION_PENALTY_WEIGHT * deficiency_ratio))
