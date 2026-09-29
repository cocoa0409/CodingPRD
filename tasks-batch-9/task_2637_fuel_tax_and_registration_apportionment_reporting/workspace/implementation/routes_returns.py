"""Quarterly fuel tax returns: opening, preparation, filing and the
return-for-correction reopening cascade."""

from flask import Blueprint, g

import calc
import serializers as S
from common import (
    ALL_ROLES,
    API_PREFIX,
    DB,
    LIGHT,
    VERSIONED,
    ZERO,
    authenticate,
    collection,
    fail,
    find_or_404,
    fmt_instant,
    gallons,
    miles,
    money,
    need_enum,
    need_int,
    need_str,
    new_row,
    ok,
    q_int,
    q_str,
    ratio,
    raw_body,
    reject_unknown,
    touch,
)
from routes_ref import get_carrier_or_404

bp = Blueprint("returns", __name__)


def get_return_or_404(return_id):
    return find_or_404(DB.fuel_tax_returns, return_id, "ERR_FUEL_TAX_RETURN_NOT_FOUND")


def _void_active_lines(return_id):
    for line in calc.return_lines(return_id, "ACTIVE"):
        line["line_status"] = "VOIDED"


def _write_lines(return_id, lines):
    for line in lines:
        row = new_row(LIGHT)
        row.update({
            "fuel_tax_return_id": return_id,
            "jurisdiction_code": line["jurisdiction_code"],
            "taxable_miles": line["taxable_miles"],
            "taxable_gallons": line["taxable_gallons"],
            "tax_paid_gallons": line["tax_paid_gallons"],
            "net_taxable_gallons": line["net_taxable_gallons"],
            "base_tax_amount": line["base_tax_amount"],
            "surcharge_amount": line["surcharge_amount"],
            "net_tax_amount": line["net_tax_amount"],
            "line_status": "ACTIVE",
        })
        DB.return_lines[row["id"]] = row


@bp.post(API_PREFIX + "/fuel-tax-returns")
def create_fuel_tax_return():
    authenticate(["TaxPreparer"])
    body = raw_body()
    reject_unknown(body, {"carrier_id", "filing_year", "filing_quarter"})

    if isinstance(body.get("carrier_id"), str):
        get_carrier_or_404(body["carrier_id"])

    need_str(body, "carrier_id")
    filing_year = need_int(body, "filing_year", minimum=1)
    filing_quarter = need_int(body, "filing_quarter", choices=(1, 2, 3, 4))
    carrier = get_carrier_or_404(body["carrier_id"])

    for existing in DB.fuel_tax_returns.values():
        if (existing["carrier_id"] == carrier["id"]
                and existing["filing_year"] == filing_year
                and existing["filing_quarter"] == filing_quarter):
            raise fail("ERR_DUPLICATE_RETURN_PERIOD",
                       "A return already exists for %s Q%s." % (filing_year, filing_quarter))

    row = new_row(VERSIONED)
    row.update({
        "carrier_id": carrier["id"],
        "filing_year": filing_year,
        "filing_quarter": filing_quarter,
        "settlement_basis": "PREPARER_BASIS",
        "return_status": "DRAFT",
        "prepared_by_user_id": None,
        "filed_by_user_id": None,
        "total_fleet_miles": miles(ZERO),
        "total_tax_paid_gallons": gallons(ZERO),
        "fleet_mpg": None,
        "reconstructed_mileage_ratio": ratio(ZERO),
        "total_net_tax_due": money(ZERO),
        "reconstruction_penalty_amount": money(ZERO),
        "total_amount_due": money(ZERO),
        "audit_assessment_delta": money(ZERO),
        "filed_at": None,
    })
    DB.fuel_tax_returns[row["id"]] = row
    return ok(S.fuel_tax_return_out(row), 201)


@bp.get(API_PREFIX + "/fuel-tax-returns/<row_id>")
def get_fuel_tax_return(row_id):
    authenticate(ALL_ROLES)
    return ok(S.fuel_tax_return_out(get_return_or_404(row_id)))


@bp.get(API_PREFIX + "/fuel-tax-returns")
def list_fuel_tax_returns():
    authenticate(ALL_ROLES)
    filters = {
        "carrier_id": q_str("carrier_id"),
        "filing_year": q_int("filing_year"),
        "filing_quarter": q_int("filing_quarter"),
        "return_status": q_str("return_status"),
        "settlement_basis": q_str("settlement_basis"),
    }
    return collection(DB.fuel_tax_returns.values(), filters,
                      ["filing_year", "filing_quarter"], S.fuel_tax_return_out)


@bp.get(API_PREFIX + "/fuel-tax-returns/<row_id>/jurisdiction-lines")
def list_return_lines(row_id):
    authenticate(ALL_ROLES)
    ret = get_return_or_404(row_id)
    rows = [
        l for l in DB.return_lines.values()
        if l["fuel_tax_return_id"] == ret["id"]
    ]
    filters = {
        "jurisdiction_code": q_str("jurisdiction_code"),
        "line_status": q_str("line_status"),
    }
    return collection(rows, filters, ["jurisdiction_code"], S.return_line_out)


# --------------------------------------------------------------------------
# Preparation
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/fuel-tax-returns/<row_id>/prepare")
def prepare_return(row_id):
    authenticate(["TaxPreparer"])
    ret = get_return_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"expected_carrier_version"})
    expected = need_int(body, "expected_carrier_version")

    carrier = DB.carriers.get(ret["carrier_id"])

    # Step 8 — optimistic concurrency on the carrier baseline.
    if carrier is None or carrier["version"] != expected:
        raise fail("ERR_STALE_CARRIER_VERSION",
                   "The carrier record has moved on since it was read.")

    # Step 9 — state.
    if ret["return_status"] not in ("DRAFT", "PREPARED", "RETURNED_FOR_CORRECTION"):
        raise fail("ERR_INVALID_RETURN_STATE",
                   "A return in %s cannot be prepared." % ret["return_status"])

    # Step 10 — IFTA licence liveness.
    if carrier["ifta_license_status"] != "ACTIVE":
        raise fail("ERR_CARRIER_LICENSE_INACTIVE",
                   "The carrier's IFTA licence is %s." % carrier["ifta_license_status"])

    # Step 14 — no review work still in flight inside the quarter window.
    start, end = calc.quarter_window(ret["filing_year"], ret["filing_quarter"])
    for trip in calc.carrier_trips(carrier["id"]):
        if not (start <= trip["_start_dt"] < end):
            continue
        if trip["trip_status"] in ("CAPTURED", "RECONSTRUCTED"):
            raise fail("ERR_TRIP_GAP_UNRESOLVED",
                       "A trip in the quarter is still awaiting review.")

    settlement = calc.settle_quarter(
        carrier["id"], ret["filing_year"], ret["filing_quarter"], "PREPARER_BASIS"
    )

    # Steps 30 then 31 — gallons before mileage, as pinned.
    if settlement["total_tax_paid_gallons"] <= 0:
        raise fail("ERR_NO_TAX_PAID_GALLONS",
                   "The quarter has no accepted tax-paid gallons.")
    if settlement["total_fleet_miles"] <= 0:
        raise fail("ERR_NO_ACCEPTED_MILEAGE",
                   "The quarter has no accepted mileage.")

    _void_active_lines(ret["id"])
    _write_lines(ret["id"], settlement["lines"])

    ret["settlement_basis"] = "PREPARER_BASIS"
    ret["total_fleet_miles"] = settlement["total_fleet_miles"]
    ret["total_tax_paid_gallons"] = settlement["total_tax_paid_gallons"]
    ret["fleet_mpg"] = settlement["fleet_mpg"]
    ret["reconstructed_mileage_ratio"] = settlement["reconstructed_mileage_ratio"]
    ret["total_net_tax_due"] = settlement["total_net_tax_due"]
    ret["reconstruction_penalty_amount"] = settlement["reconstruction_penalty_amount"]
    ret["total_amount_due"] = settlement["total_amount_due"]
    ret["prepared_by_user_id"] = g.user_id
    ret["return_status"] = "PREPARED"
    touch(ret)

    calc.recompute_carrier_ratio(carrier)
    carrier["latest_prepared_fleet_mpg"] = settlement["fleet_mpg"]
    touch(carrier)
    return ok(S.fuel_tax_return_out(ret))


# --------------------------------------------------------------------------
# Filing and the reopening cascade
# --------------------------------------------------------------------------


def rescore_not_selected(carrier, selection_year):
    """Fourth hop of the correction cascade / re-selection."""
    for selection in DB.audit_selections.values():
        if selection["carrier_id"] != carrier["id"]:
            continue
        if selection["selection_year"] != selection_year:
            continue
        if selection["selection_status"] != "NOT_SELECTED":
            continue
        score = calc.audit_risk_score(
            carrier, selection["late_filing_count"],
            selection["retention_deficiency_count"],
        )
        promoted = score >= calc.AUDIT_SELECTION_THRESHOLD
        changed = score != selection["risk_score"] or promoted
        selection["risk_score"] = score
        if promoted:
            selection["selection_status"] = "SELECTED"
            carrier["audit_flag"] = True
        if changed:
            touch(selection)


@bp.post(API_PREFIX + "/fuel-tax-returns/<row_id>/review")
def review_return(row_id):
    authenticate(["ComplianceOfficer"])
    ret = get_return_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"decision", "review_note"})
    decision = need_enum(body, "decision", ("FILE", "RETURN_FOR_CORRECTION"))
    need_str(body, "review_note", required=False)

    carrier = DB.carriers.get(ret["carrier_id"])

    # Step 9 — state.
    if ret["return_status"] != "PREPARED":
        raise fail("ERR_INVALID_RETURN_STATE",
                   "A return in %s cannot be reviewed." % ret["return_status"])

    # Step 10 — IFTA licence liveness.
    if carrier is None or carrier["ifta_license_status"] != "ACTIVE":
        raise fail("ERR_CARRIER_LICENSE_INACTIVE",
                   "The carrier's IFTA licence is not active.")

    # Step 18 — segregation of duties.
    if ret["prepared_by_user_id"] is not None and ret["prepared_by_user_id"] == g.user_id:
        raise fail("ERR_SEGREGATION_OF_DUTIES",
                   "The preparer of this return may not review it.")

    if decision == "FILE":
        # Step 29 — bond coverage.
        if ret["total_amount_due"] > carrier["bond_ceiling_amount"]:
            raise fail("ERR_BOND_CEILING_EXCEEDED",
                       "The amount due exceeds the carrier's bond ceiling.")
        ret["return_status"] = "FILED"
        ret["filed_by_user_id"] = g.user_id
        ret["filed_at"] = fmt_instant(DB.clock.now())
        touch(ret)
        return ok(S.fuel_tax_return_out(ret))

    # First hop — the return itself.
    _void_active_lines(ret["id"])
    ret["return_status"] = "RETURNED_FOR_CORRECTION"
    ret["total_net_tax_due"] = money(ZERO)
    ret["reconstruction_penalty_amount"] = money(ZERO)
    ret["total_amount_due"] = money(ZERO)
    ret["total_fleet_miles"] = miles(ZERO)
    ret["fleet_mpg"] = None
    ret["reconstructed_mileage_ratio"] = ratio(ZERO)
    touch(ret)

    # Second hop — reopen the quarter's accepted manual reconstructions.
    start, end = calc.quarter_window(ret["filing_year"], ret["filing_quarter"])
    for trip in calc.carrier_trips(carrier["id"]):
        if trip["trip_status"] != "ACCEPTED":
            continue
        if trip["mileage_source"] != "MANUAL_RECONSTRUCTION":
            continue
        if not (start <= trip["_start_dt"] < end):
            continue
        for leg in calc.trip_legs(trip["id"], "ACTIVE"):
            leg["leg_status"] = "VOIDED"
        trip["trip_status"] = "GAP_FLAGGED"
        trip["accepted_leg_miles_total"] = miles(ZERO)
        trip["supporting_document_reference"] = None
        touch(trip)

    # Third hop — the carrier's compliance posture.
    calc.recompute_carrier_ratio(carrier)

    # Fourth hop — audit re-selection for the filing year.
    rescore_not_selected(carrier, ret["filing_year"])
    touch(carrier)
    return ok(S.fuel_tax_return_out(ret))
