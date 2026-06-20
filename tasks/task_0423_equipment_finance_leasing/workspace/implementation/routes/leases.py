"""Lease endpoints — PRD §3.4, §3.6, §3.7, §3.11, §4.

A lease carries two independent dimensions: lifecycle_status
(ORIGINATION -> BOOKED -> ACTIVE -> END_OF_TERM -> TERMINATED) and
funding_status (PENDING_FUNDING -> FUNDED). ACTIVE is reached only when BOTH
lifecycle == BOOKED and funding == FUNDED.
"""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_enum, require_positive_int, require_int,
    require_string, optional_nonneg_int, optional_positive_int, serialize,
    paginate, sort_by_created, parse_iso8601, to_iso, add_months,
)
from services import domain
from services import calculations as calc

bp = Blueprint("leases", __name__)

LEASE_TYPES = {"FMV", "DOLLAR_OUT", "TRAC"}


@bp.post("/lessors/<lessor_id>/lessees/<lessee_id>/leases")
def create_lease(lessor_id, lessee_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        lessee = domain.get_lessee(lessor_id, lessee_id)
        body = get_json_body()
        vendor_id = require_string(body, "vendor_id")
        lease_type = require_enum(body, "lease_type", LEASE_TYPES)
        equipment_cost_cents = require_positive_int(body, "equipment_cost_cents")
        term_months = require_positive_int(body, "term_months")
        monthly_rate_factor_bps = require_positive_int(body, "monthly_rate_factor_bps")
        trac_residual_pct_bps = optional_positive_int(body, "trac_residual_pct_bps")
        advance_payment_count = optional_nonneg_int(body, "advance_payment_count", 0)
        security_deposit_cents = optional_nonneg_int(body, "security_deposit_cents", 0)

        rec = db.init_record({
            "lessor_id": lessor_id,
            "lessee_id": lessee_id,
            "vendor_id": vendor_id,
            "lease_type": lease_type,
            "equipment_cost_cents": equipment_cost_cents,
            "term_months": term_months,
            "monthly_rate_factor_bps": monthly_rate_factor_bps,
            "trac_residual_pct_bps": trac_residual_pct_bps,
            "advance_payment_count": advance_payment_count,
            "security_deposit_cents": security_deposit_cents,
            "financed_amount_cents": 0,
            "monthly_payment_cents": 0,
            "residual_value_cents": 0,
            "booked_clock_utc": None,
            "lifecycle_status": "ORIGINATION",
            "funding_status": "PENDING_FUNDING",
            "paid_installment_count": 0,
            "deposit_refundable": False,
        })
        db.leases[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>")
def get_lease(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_lease(lessor_id, lease_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/leases")
def list_leases(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        items = [l for l in db.leases.values() if l["lessor_id"] == lessor_id]
        for key in ("lessee_id", "vendor_id", "lifecycle_status", "funding_status"):
            val = request.args.get(key)
            if val is not None and val != "":
                items = [l for l in items if l[key] == val]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/book")
def book_lease(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        body = get_json_body()
        # Priority 4: request body well-formedness — expected_lease_version required.
        expected_version = require_int(body, "expected_lease_version")
        # OCC version check is pinned FIRST among booking preconditions
        # (PRD §3.4: "the version check first (ERR_STALE_VERSION, 412)"). A
        # re-book attempt carrying a stale version must surface ERR_STALE_VERSION
        # even though the lease has already left ORIGINATION, so the version
        # check precedes the from-state check here.
        if expected_version != lease["version"]:
            raise errors.stale_version()
        # State: the book transition is only defined from ORIGINATION.
        if lease["lifecycle_status"] != "ORIGINATION":
            raise errors.invalid_state("Lease is not in ORIGINATION")
        # Business preconditions (PRD §3.4 ordering):
        # credit, equipment, TRAC consistency.
        lessee = db.lessees.get(lease["lessee_id"])

        # Pre-compute pricing to know financed_amount for the credit check.
        mp = calc.monthly_payment(lease["equipment_cost_cents"], lease["monthly_rate_factor_bps"])
        financed = calc.financed_amount(
            lease["equipment_cost_cents"], lease["advance_payment_count"], mp,
            lease["security_deposit_cents"],
        )

        # Credit check (ERR_CREDIT_LIMIT_EXCEEDED).
        if lessee["available_credit_cents"] < financed:
            raise errors.conflict(errors.ERR_CREDIT_LIMIT_EXCEEDED,
                                  "available credit insufficient for financed amount")
        # At least one EquipmentUnit attached (ERR_NO_EQUIPMENT).
        units = domain.units_for_lease(lease["id"])
        if len(units) == 0:
            raise errors.conflict(errors.ERR_NO_EQUIPMENT, "no equipment attached")
        # TRAC consistency (ERR_TRAC_RESIDUAL_REQUIRED): TRAC iff trac set;
        # and when TRAC, >= TRAC_FLOOR_BPS.
        is_trac = lease["lease_type"] == "TRAC"
        has_trac = lease["trac_residual_pct_bps"] is not None
        if is_trac != has_trac:
            raise errors.conflict(errors.ERR_TRAC_RESIDUAL_REQUIRED,
                                  "trac_residual_pct_bps must be present iff lease_type is TRAC")
        if is_trac and lease["trac_residual_pct_bps"] < calc.TRAC_FLOOR_BPS:
            raise errors.conflict(errors.ERR_TRAC_RESIDUAL_REQUIRED,
                                  "trac_residual_pct_bps below TRAC floor")

        # Commit side effects.
        lease["lifecycle_status"] = "BOOKED"
        lease["booked_clock_utc"] = lessor["clock_utc"]
        lease["monthly_payment_cents"] = mp
        lease["financed_amount_cents"] = financed
        lease["residual_value_cents"] = calc.residual_value(
            lease["lease_type"], lease["term_months"], lease["equipment_cost_cents"],
            lease["trac_residual_pct_bps"],
        )
        # Generate schedule lines.
        booked_dt = parse_iso8601(lease["booked_clock_utc"])
        for n in range(1, lease["term_months"] + 1):
            is_advance = n <= lease["advance_payment_count"]
            sl = db.init_record({
                "lessor_id": lessor_id,
                "lease_id": lease["id"],
                "installment_number": n,
                "due_clock_utc": to_iso(add_months(booked_dt, n)),
                "base_rent_cents": mp,
                "is_advance": is_advance,
                "status": "WAIVED" if is_advance else "SCHEDULED",
            })
            db.schedule_lines[sl["id"]] = sl
        # increments Lease.version by 1 (the book transition's own mutation).
        db.touch(lease)
        # Cascades.
        domain.recompute_lessee_credit(lessee)
        domain.recompute_lessor_portfolio(lessor)
        return object_response(serialize(lease), 200)


# (vendor_id required as a non-empty string at lease creation.)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/fund")
def fund_lease(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        # State: funding dimension must be PENDING_FUNDING.
        if lease["funding_status"] != "PENDING_FUNDING":
            raise errors.invalid_state("Lease is not PENDING_FUNDING")
        # Business: must be BOOKED then vendor APPROVED.
        if lease["lifecycle_status"] != "BOOKED":
            raise errors.conflict(errors.ERR_NOT_BOOKED, "lease is not BOOKED")
        vendor = db.vendors.get(lease["vendor_id"])
        if vendor is None or vendor["status"] != "APPROVED":
            raise errors.conflict(errors.ERR_VENDOR_NOT_APPROVED, "vendor is not APPROVED")

        # Commit: funding_status -> FUNDED.
        lease["funding_status"] = "FUNDED"
        db.touch(lease)

        # Cascade depth-3: create UCC filing PENDING -> auto-file FILED.
        filed_dt = parse_iso8601(lessor["clock_utc"])
        ucc = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease["id"],
            "jurisdiction_state_code": lessor["home_state_code"],
            "filing_number": None,
            "filed_clock_utc": None,
            "coverage_end_clock_utc": None,
            "status": "PENDING",
        })
        db.ucc_filings[ucc["id"]] = ucc
        ucc["status"] = "FILED"
        ucc["filed_clock_utc"] = to_iso(filed_dt)
        ucc["coverage_end_clock_utc"] = to_iso(add_months(filed_dt, calc.UCC_LAPSE_MONTHS))
        ucc["filing_number"] = "UCC-" + ucc["id"][:12].upper()
        db.touch(ucc)

        # Generate SALES_USE TaxAssessment.
        base = lease["equipment_cost_cents"]
        tax_amount = calc.assessment_tax_amount(base, lessor["sales_tax_rate_bps"])
        ta = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease["id"],
            "tax_type": "SALES_USE",
            "assessment_clock_utc": lessor["clock_utc"],
            "taxable_base_cents": base,
            "tax_amount_cents": tax_amount,
            "status": "ASSESSED",
        })
        db.tax_assessments[ta["id"]] = ta

        # Automatic lifecycle BOOKED -> ACTIVE now that both dimensions align.
        if lease["lifecycle_status"] == "BOOKED" and lease["funding_status"] == "FUNDED":
            lease["lifecycle_status"] = "ACTIVE"
            db.touch(lease)
        return object_response(serialize(lease), 200)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/begin-end-of-term")
def begin_end_of_term(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        if lease["lifecycle_status"] != "ACTIVE":
            raise errors.invalid_state("Lease is not ACTIVE")
        required = lease["term_months"] - lease["advance_payment_count"]
        if lease["paid_installment_count"] < required:
            raise errors.conflict(errors.ERR_TERM_NOT_COMPLETE,
                                  "scheduled term not fully paid")
        lease["lifecycle_status"] = "END_OF_TERM"
        db.touch(lease)
        return object_response(serialize(lease), 200)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/terminate")
def terminate_lease(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        if lease["lifecycle_status"] != "END_OF_TERM":
            raise errors.invalid_state("Lease is not END_OF_TERM")
        # An EndOfTermElection in EXERCISED status must exist.
        exercised = [e for e in domain.elections_for_lease(lease["id"])
                     if e["status"] == "EXERCISED"]
        if not exercised:
            raise errors.conflict(errors.ERR_ELECTION_NOT_EXERCISED,
                                  "no EXERCISED end-of-term election")
        # No OPEN invoice with outstanding balance.
        for inv in domain.invoices_for_lease(lease["id"]):
            if inv["status"] == "OPEN" and inv["total_due_cents"] > inv["amount_paid_cents"]:
                raise errors.conflict(errors.ERR_OUTSTANDING_BALANCE,
                                      "open invoice with outstanding balance")
        lease["lifecycle_status"] = "TERMINATED"
        lease["deposit_refundable"] = True
        db.touch(lease)
        # Cascades: lease drops out of committed-credit and active portfolio.
        lessee = db.lessees.get(lease["lessee_id"])
        domain.recompute_lessee_credit(lessee)
        domain.recompute_lessor_portfolio(lessor)
        return object_response(serialize(lease), 200)
