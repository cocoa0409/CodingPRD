"""Domain logic: derived-field reconciliation, calculations, cascades,
and entity serializers."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import core
from core import (
    now, format_dt, add_years, touch,
    NON_EHS_THRESHOLD_LBS, EHS_TPQ_CAP_LBS,
    BASE_FEE_CENTS, PROVISIONAL_RATE_CENTS, INCLUDED_CHEMICALS,
    TIER1_MAX, TIER1_RATE_CENTS, TIER2_RATE_CENTS, EHS_SURCHARGE_CENTS,
    RMP_RESUBMIT_YEARS, RMP_DUE_WINDOW_DAYS,
)

LATE_PENALTY_PCT = Decimal("0.10")


def dround2(x):
    """Round a numeric value half-up to 2 decimal places, return float."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Inventory-level computed fields (set at creation)
# ---------------------------------------------------------------------------
def compute_inventory_derived(inv, chem):
    reportable = inv["max_daily_amount_lbs"]          # MAX variant
    inv["reportable_amount_lbs"] = reportable
    inv["average_onsite_lbs"] = inv["average_daily_amount_lbs"]  # AVERAGE variant

    if chem["is_ehs"]:
        tpq = chem["tpq_lbs"]
        inv["applicable_threshold_lbs"] = min(tpq, EHS_TPQ_CAP_LBS)
        inv["exceeds_tpq"] = reportable >= tpq
    else:
        inv["applicable_threshold_lbs"] = NON_EHS_THRESHOLD_LBS
        inv["exceeds_tpq"] = False

    inv["is_reportable"] = reportable >= inv["applicable_threshold_lbs"]
    inv["weighted_hazard_contribution"] = dround2(
        (inv["max_daily_amount_lbs"] / 1000.0) * chem["hazard_weight"]
    )


# ---------------------------------------------------------------------------
# Facility derived fields (reconciled on read)
# ---------------------------------------------------------------------------
def facility_open_cases(fid):
    return [c for c in core.cases.values()
            if c["facility_id"] == fid and c["status"] in ("OPEN", "UNDER_REVIEW")]


def facility_posture(fid):
    open_cases = facility_open_cases(fid)
    if any(c["origin"] == "RELEASE_RQ_EXCEEDED" or c["severity"] == "HIGH" for c in open_cases):
        return "ENFORCEMENT"
    if open_cases:
        return "DEFICIENT"
    return "COMPLIANT"


def facility_hazard_index(fid):
    total = Decimal("0.00")
    for inv in core.inventories.values():
        if inv["facility_id"] == fid and inv["status"] == "ACTIVE":
            total += Decimal(str(inv["weighted_hazard_contribution"]))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def facility_outstanding_fee(fid):
    total = 0
    for f in core.filings.values():
        if f["facility_id"] == fid and f["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            contribution = f["assessed_fee_cents"] - f["fee_paid_cents"]
            if contribution < 0:
                contribution = 0
            total += contribution
    return total


def facility_is_rmp_required(fid):
    for inv in core.inventories.values():
        if inv["facility_id"] != fid or inv["status"] != "ACTIVE":
            continue
        chem = core.chemicals.get(inv["chemical_id"])
        if chem and chem["is_ehs"] and inv["exceeds_tpq"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Tier II fee calculations
# ---------------------------------------------------------------------------
def active_inventories_for_year(fid, year):
    return [inv for inv in core.inventories.values()
            if inv["facility_id"] == fid and inv["reporting_year"] == year
            and inv["status"] == "ACTIVE"]


def reportable_inventories_for_year(fid, year):
    return [inv for inv in active_inventories_for_year(fid, year) if inv["is_reportable"]]


def provisional_fee(fid, year):
    declared = len(active_inventories_for_year(fid, year))
    return BASE_FEE_CENTS + declared * PROVISIONAL_RATE_CENTS


def assessed_fee(n_reportable, e_ehs, is_late):
    if n_reportable <= INCLUDED_CHEMICALS:
        per = 0
    elif n_reportable <= TIER1_MAX:
        per = (n_reportable - INCLUDED_CHEMICALS) * TIER1_RATE_CENTS
    else:
        per = ((TIER1_MAX - INCLUDED_CHEMICALS) * TIER1_RATE_CENTS
               + (n_reportable - TIER1_MAX) * TIER2_RATE_CENTS)
    ehs_surcharge = e_ehs * EHS_SURCHARGE_CENTS
    subtotal = BASE_FEE_CENTS + per + ehs_surcharge
    if is_late:
        penalty = int((Decimal(subtotal) * LATE_PENALTY_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        penalty = 0
    return subtotal + penalty


def filing_deadline(year):
    return core.parse_dt(f"{year + 1}-03-01T00:00:00Z")


def filing_counts(filing):
    fid = filing["facility_id"]
    year = filing["reporting_year"]
    reportable = reportable_inventories_for_year(fid, year)
    n = len(reportable)
    e = 0
    for inv in reportable:
        chem = core.chemicals.get(inv["chemical_id"])
        if chem and chem["is_ehs"]:
            e += 1
    return n, e


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def open_case(fid, origin, severity, origin_ref):
    rec = core.base_record()
    rec.update({
        "facility_id": fid,
        "origin": origin,
        "origin_ref": origin_ref,
        "severity": severity,
        "status": "OPEN",
        "penalty_cents": 0,
    })
    core.cases[rec["id"]] = rec
    return rec


def suspend_active_permits(fid):
    for p in core.permits.values():
        if p["facility_id"] == fid and p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            touch(p)


def reinstate_suspended_permits(fid):
    for p in core.permits.values():
        if p["facility_id"] == fid and p["status"] == "SUSPENDED":
            p["status"] = "ACTIVE"
            touch(p)


# ---------------------------------------------------------------------------
# Read-time reconciliation for permit expiry / RMP status
# ---------------------------------------------------------------------------
def reconcile_permit(p):
    if p["status"] == "ACTIVE" and now() > p["expiry_date"]:
        p["status"] = "EXPIRED"
    return p


def rmp_status(r):
    due = r["next_due_date"]
    clock = now()
    if clock > due:
        return "OVERDUE"
    if clock >= due - timedelta(days=RMP_DUE_WINDOW_DAYS):
        return "DUE"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": format_dt(rec["created_at"]),
        "updated_at": format_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_facility(f):
    fid = f["id"]
    out = _common(f)
    out.update({
        "name": f["name"],
        "epa_facility_id": f["epa_facility_id"],
        "state_code": f["state_code"],
        "county": f["county"],
        "operator_name": f["operator_name"],
        "erp_contact_name": f["erp_contact_name"],
        "erp_contact_phone": f["erp_contact_phone"],
        "erp_plan_ref": f["erp_plan_ref"],
        "erp_linked_lepc_district": f["erp_linked_lepc_district"],
        "erp_status": f["erp_status"],
        "compliance_posture": facility_posture(fid),
        "open_case_count": len(facility_open_cases(fid)),
        "hazard_index": facility_hazard_index(fid),
        "total_outstanding_fee_cents": facility_outstanding_fee(fid),
        "is_rmp_required": facility_is_rmp_required(fid),
    })
    return out


def ser_chemical(c):
    out = _common(c)
    out.update({
        "cas_number": c["cas_number"],
        "name": c["name"],
        "is_ehs": c["is_ehs"],
        "tpq_lbs": c["tpq_lbs"],
        "rq_lbs": c["rq_lbs"],
        "hazard_weight": c["hazard_weight"],
        "physical_state": c["physical_state"],
    })
    return out


def ser_inventory(inv):
    out = _common(inv)
    out.update({
        "facility_id": inv["facility_id"],
        "chemical_id": inv["chemical_id"],
        "reporting_year": inv["reporting_year"],
        "max_daily_amount_lbs": inv["max_daily_amount_lbs"],
        "average_daily_amount_lbs": inv["average_daily_amount_lbs"],
        "days_on_site": inv["days_on_site"],
        "storage_type": inv["storage_type"],
        "reportable_amount_lbs": inv["reportable_amount_lbs"],
        "average_onsite_lbs": inv["average_onsite_lbs"],
        "applicable_threshold_lbs": inv["applicable_threshold_lbs"],
        "is_reportable": inv["is_reportable"],
        "exceeds_tpq": inv["exceeds_tpq"],
        "weighted_hazard_contribution": inv["weighted_hazard_contribution"],
        "status": inv["status"],
    })
    return out


def ser_filing(f):
    n, e = filing_counts(f)
    out = _common(f)
    out.update({
        "facility_id": f["facility_id"],
        "reporting_year": f["reporting_year"],
        "status": f["status"],
        "provisional_fee_cents": f["provisional_fee_cents"],
        "assessed_fee_cents": f["assessed_fee_cents"],
        "fee_paid_cents": f["fee_paid_cents"],
        "reportable_chemical_count": n,
        "ehs_reportable_count": e,
        "is_late": f["is_late"],
        "submitted_at": format_dt(f["submitted_at"]),
        "deadline": format_dt(f["deadline"]),
        "revision_count": f["revision_count"],
    })
    return out


def ser_sds(s):
    out = _common(s)
    out.update({
        "facility_id": s["facility_id"],
        "chemical_id": s["chemical_id"],
        "document_ref": s["document_ref"],
        "revision_date": format_dt(s["revision_date"]),
        "status": s["status"],
    })
    return out


def ser_release(r):
    out = _common(r)
    out.update({
        "facility_id": r["facility_id"],
        "chemical_id": r["chemical_id"],
        "release_datetime": format_dt(r["release_datetime"]),
        "quantity_released_lbs": r["quantity_released_lbs"],
        "medium": r["medium"],
        "reporting_status": r["reporting_status"],
        "remediation_status": r["remediation_status"],
        "exceeds_rq": r["exceeds_rq"],
        "requires_lepc": r["requires_lepc"],
        "origin_case_opened": r["origin_case_opened"],
    })
    return out


def ser_notice(n):
    out = _common(n)
    out.update({
        "release_id": n["release_id"],
        "notice_type": n["notice_type"],
        "recipient": n["recipient"],
        "sent_at": format_dt(n["sent_at"]),
        "acknowledged": n["acknowledged"],
    })
    return out


def ser_permit(p):
    reconcile_permit(p)
    out = _common(p)
    out.update({
        "facility_id": p["facility_id"],
        "permit_type": p["permit_type"],
        "issued_date": format_dt(p["issued_date"]),
        "expiry_date": format_dt(p["expiry_date"]),
        "fee_cents": p["fee_cents"],
        "status": p["status"],
    })
    return out


def ser_inspection(i):
    out = _common(i)
    out.update({
        "facility_id": i["facility_id"],
        "inspector_id": i["inspector_id"],
        "scheduled_date": format_dt(i["scheduled_date"]),
        "status": i["status"],
        "result": i["result"],
        "findings_count": i["findings_count"],
    })
    return out


def ser_case(c):
    out = _common(c)
    out.update({
        "facility_id": c["facility_id"],
        "origin": c["origin"],
        "origin_ref": c["origin_ref"],
        "severity": c["severity"],
        "status": c["status"],
        "penalty_cents": c["penalty_cents"],
    })
    return out


def ser_rmp(r):
    out = _common(r)
    out.update({
        "facility_id": r["facility_id"],
        "program_level": r["program_level"],
        "submitted_date": format_dt(r["submitted_date"]),
        "next_due_date": format_dt(r["next_due_date"]),
        "status": rmp_status(r),
    })
    return out
