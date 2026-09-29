"""Tenant register, lease execution and amendment, insurance, ledger, mortgages."""

from flask import Blueprint

import auth
import calc
import cascades
import serialize
import store
import validate as v
from errors import ApiError
from response import object_response

bp = Blueprint("setup", __name__)

CREDIT_RATINGS = {"AAA", "A", "BBB", "SPECULATIVE"}
USE_CODES = {"RETAIL_MIXED", "INDUSTRIAL_LOGISTICS", "RESIDENTIAL_RENTAL",
             "LIFE_SCIENCE_LAB"}
REVERSION_STANDARDS = {"SHELL_CONDITION", "FULLY_FITTED", "BROOM_CLEAN"}


# ===========================================================================
# Tenant register
# ===========================================================================
@bp.post("/lessees")
def register_lessee():
    auth.require({"LessorAdmin"})
    payload = v.body()
    legal_name = v.req_str(payload, "legal_name")
    notice_email = v.req_str(payload, "notice_email")
    credit = v.opt_enum(payload, "credit_rating_code", CREDIT_RATINGS, "BBB")

    for row in store.lessees.values():
        if row["legal_name"] == legal_name:
            raise ApiError("ERR_DUPLICATE_RECORD",
                           "That legal name is already on the tenant register.")

    record = {
        "legal_name": legal_name,
        "notice_email": notice_email,
        "credit_rating_code": credit,
    }
    store.stamp(record)
    store.lessees[record["id"]] = record
    return object_response(serialize.lessee(record), 201)


# ===========================================================================
# Lease execution
# ===========================================================================
def _coherence(min_bps, max_bps, rate_bps, commencement, expiration, gfa):
    """The four coherence rules applied to the terms as a set (PRD 3.1)."""
    if not min_bps < max_bps:
        raise ApiError("ERR_TERMS_INCOHERENT",
                       "reval_collar_min_uplift_bps must be strictly less than "
                       "reval_collar_max_uplift_bps.")
    if rate_bps < 100 or rate_bps > 2000:
        raise ApiError("ERR_TERMS_INCOHERENT",
                       "percentage_rent_rate_bps must fall between 100 and "
                       "2000 basis points inclusive.")
    if not expiration > commencement:
        raise ApiError("ERR_TERMS_INCOHERENT",
                       "expiration_date must be strictly after "
                       "commencement_date.")
    if gfa < 1:
        raise ApiError("ERR_TERMS_INCOHERENT",
                       "total_permitted_gfa_sqft must be at least 1.")


@bp.post("/leases")
def execute_lease():
    payload = v.body()
    lessee = None
    if v.fk_present(payload, "lessee_id"):
        lessee = cascades.fetch("lessee", v.fk_value(payload, "lessee_id"))

    auth.require({"LessorAdmin"})

    lessee_id = v.req_str(payload, "lessee_id")
    premises_code = v.req_str(payload, "premises_code")
    commencement = v.req_dt(payload, "commencement_date")
    expiration = v.req_dt(payload, "expiration_date")
    initial_rent = v.req_int(payload, "initial_annual_base_rent_cents",
                             minimum=1)
    interval_years = v.req_int(payload, "revaluation_interval_years", minimum=1)
    collar_min = v.req_bps(payload, "reval_collar_min_uplift_bps")
    collar_max = v.req_bps(payload, "reval_collar_max_uplift_bps")
    rate_bps = v.req_bps(payload, "percentage_rent_rate_bps")
    breakpoint_cents = v.req_money(payload, "percentage_rent_breakpoint_cents")
    permitted_use = v.req_enum(payload, "permitted_use_code", USE_CODES)
    total_gfa = v.req_area(payload, "total_permitted_gfa_sqft")
    improvements = v.req_money(payload, "improvements_value_cents")
    land_value = v.req_money(payload, "reversion_land_value_cents")
    standard = v.req_enum(payload, "reversion_standard_code",
                          REVERSION_STANDARDS)
    deposit = v.req_money(payload, "security_deposit_cents")

    for row in store.leases.values():
        if (row["premises_code"] == premises_code
                and row["lease_status"] not in ("TERMINATED", "REVERTED")):
            raise ApiError(
                "ERR_DUPLICATE_RECORD",
                "That premises_code is already let under a live lease.",
            )

    _coherence(collar_min, collar_max, rate_bps, commencement, expiration,
               total_gfa)

    record = {
        "lessee_id": lessee_id,
        "predecessor_lease_id": None,
        "origin_mortgage_id": None,
        "premises_code": premises_code,
        "commencement_date": commencement,
        "expiration_date": expiration,
        "lease_status": "ACTIVE",
        "rent_status": "BASE_ONLY",
        "initial_annual_base_rent_cents": initial_rent,
        "current_annual_base_rent_cents": initial_rent,
        "revaluation_interval_years": interval_years,
        "next_revaluation_date": store.add_years(commencement, interval_years),
        "reval_collar_min_uplift_bps": collar_min,
        "reval_collar_max_uplift_bps": collar_max,
        "percentage_rent_rate_bps": rate_bps,
        "percentage_rent_breakpoint_cents": breakpoint_cents,
        "percentage_rent_sublease_base_cents": 0,
        "arrears_balance_cents": 0,
        "permitted_use_code": permitted_use,
        "total_permitted_gfa_sqft": total_gfa,
        "gfa_allocated_sqft": 0,
        "gfa_unallocated_sqft": total_gfa,
        "improvements_value_cents": improvements,
        "reversion_land_value_cents": land_value,
        "reversion_standard_code": standard,
        "security_deposit_cents": deposit,
        "deposit_held_cents": deposit,
        "deposit_applied_cents": 0,
        "deposit_refunded_cents": 0,
        "insurance_status": "LAPSED",
        "property_all_risk_limit_cents": 0,
        "builders_risk_limit_cents": 0,
        "lessor_additional_insured": False,
        "insurance_expires_at": None,
    }
    store.stamp(record)
    store.leases[record["id"]] = record
    return object_response(serialize.lease(record), 201)


AMENDABLE = {
    "permitted_use_code", "reval_collar_min_uplift_bps",
    "reval_collar_max_uplift_bps", "percentage_rent_rate_bps",
    "percentage_rent_breakpoint_cents", "revaluation_interval_years",
    "expiration_date", "total_permitted_gfa_sqft", "improvements_value_cents",
    "reversion_land_value_cents", "reversion_standard_code",
}


@bp.post("/leases/<lease_id>/terms")
def amend_terms(lease_id):
    lease = cascades.fetch("lease", lease_id)
    auth.require({"LessorAdmin"})
    payload = v.body()

    updates = {}
    if "permitted_use_code" in payload:
        updates["permitted_use_code"] = v.req_enum(
            payload, "permitted_use_code", USE_CODES)
    if "reval_collar_min_uplift_bps" in payload:
        updates["reval_collar_min_uplift_bps"] = v.req_bps(
            payload, "reval_collar_min_uplift_bps")
    if "reval_collar_max_uplift_bps" in payload:
        updates["reval_collar_max_uplift_bps"] = v.req_bps(
            payload, "reval_collar_max_uplift_bps")
    if "percentage_rent_rate_bps" in payload:
        updates["percentage_rent_rate_bps"] = v.req_bps(
            payload, "percentage_rent_rate_bps")
    if "percentage_rent_breakpoint_cents" in payload:
        updates["percentage_rent_breakpoint_cents"] = v.req_money(
            payload, "percentage_rent_breakpoint_cents")
    if "revaluation_interval_years" in payload:
        updates["revaluation_interval_years"] = v.req_int(
            payload, "revaluation_interval_years", minimum=1)
    if "expiration_date" in payload:
        updates["expiration_date"] = v.req_dt(payload, "expiration_date")
    if "total_permitted_gfa_sqft" in payload:
        updates["total_permitted_gfa_sqft"] = v.req_area(
            payload, "total_permitted_gfa_sqft")
    if "improvements_value_cents" in payload:
        updates["improvements_value_cents"] = v.req_money(
            payload, "improvements_value_cents")
    if "reversion_land_value_cents" in payload:
        updates["reversion_land_value_cents"] = v.req_money(
            payload, "reversion_land_value_cents")
    if "reversion_standard_code" in payload:
        updates["reversion_standard_code"] = v.req_enum(
            payload, "reversion_standard_code", REVERSION_STANDARDS)

    merged = dict(lease)
    merged.update(updates)
    _coherence(
        merged["reval_collar_min_uplift_bps"],
        merged["reval_collar_max_uplift_bps"],
        merged["percentage_rent_rate_bps"],
        merged["commencement_date"],
        merged["expiration_date"],
        merged["total_permitted_gfa_sqft"],
    )

    lease.update(updates)
    cascades.rederive_envelope(lease)
    store.touch(lease)
    return object_response(serialize.lease(lease), 200)


@bp.post("/leases/<lease_id>/insurance-endorsements")
def file_endorsement(lease_id):
    lease = cascades.fetch("lease", lease_id)
    user_id, role = auth.require({"LessorAdmin", "GroundTenant"})
    auth.owns_lease(user_id, role, lease)
    payload = v.body()

    property_limit = v.req_money(payload, "property_all_risk_limit_cents")
    builders_limit = v.req_money(payload, "builders_risk_limit_cents")
    additional_insured = v.req_bool(payload, "lessor_additional_insured")
    expires_at = v.req_dt(payload, "expires_at")

    lease["property_all_risk_limit_cents"] = property_limit
    lease["builders_risk_limit_cents"] = builders_limit
    lease["lessor_additional_insured"] = additional_insured
    lease["insurance_expires_at"] = expires_at
    # ACTIVE only where the endorsement is still live at the logical clock.
    lease["insurance_status"] = (
        "ACTIVE" if expires_at > store.now() else "LAPSED"
    )
    store.touch(lease)
    return object_response(serialize.lease(lease), 200)


@bp.post("/leases/<lease_id>/rent-charges")
def post_rent_charge(lease_id):
    lease = cascades.fetch("lease", lease_id)
    auth.require({"LeaseAccountant"})
    payload = v.body()
    amount = v.req_money(payload, "amount_cents")
    v.opt_str(payload, "memo", default=None, max_len=2000)

    lease["arrears_balance_cents"] = lease["arrears_balance_cents"] + amount
    store.touch(lease)
    return object_response(serialize.lease(lease), 200)


# ===========================================================================
# Leasehold mortgages
# ===========================================================================
@bp.post("/leases/<lease_id>/leasehold-mortgages")
def record_mortgage(lease_id):
    lease = cascades.fetch("lease", lease_id)
    auth.require({"LessorAdmin"})
    payload = v.body()

    legal_name = v.req_str(payload, "mortgagee_legal_name")
    notice_email = v.req_str(payload, "notice_email")
    principal = v.req_int(payload, "original_principal_cents", minimum=1)
    priority_rank = v.req_int(payload, "priority_rank", minimum=1)
    extension_days = v.req_int(payload, "cure_extension_days", minimum=1)

    for row in cascades.lease_mortgages(lease_id):
        if row["priority_rank"] == priority_rank:
            raise ApiError(
                "ERR_DUPLICATE_RECORD",
                "That priority_rank is already recorded against this lease.",
            )

    cascades.require_operative(lease)

    record = {
        "lease_id": lease_id,
        "mortgagee_legal_name": legal_name,
        "notice_email": notice_email,
        "original_principal_cents": principal,
        "outstanding_principal_cents": principal,
        "priority_rank": priority_rank,
        "cure_extension_days": extension_days,
        "status": "RECORDED",
        "mortgagee_notified_at": None,
        "new_lease_election_deadline": None,
    }
    store.stamp(record)
    store.mortgages[record["id"]] = record
    return object_response(serialize.mortgage(record), 201)


@bp.post("/leasehold-mortgages/<mortgage_id>/new-lease-election")
def elect_new_lease(mortgage_id):
    mortgage = cascades.fetch("mortgage", mortgage_id)
    payload = v.body()
    new_lessee = None
    if v.fk_present(payload, "new_lessee_id"):
        new_lessee = cascades.fetch("lessee", v.fk_value(payload, "new_lessee_id"))

    auth.require({"MortgageeAgent"})

    new_lessee_id = v.req_str(payload, "new_lessee_id")
    premises_code = v.opt_str(payload, "premises_code", default=None)

    old_lease = store.leases.get(mortgage["lease_id"])

    if mortgage["status"] != "NEW_LEASE_ELIGIBLE":
        raise cascades.invalid_state(
            "The mortgage is in %s and cannot elect a new lease."
            % mortgage["status"]
        )
    deadline = mortgage.get("new_lease_election_deadline")
    if deadline is not None and store.now() > deadline:
        raise ApiError("ERR_CURE_WINDOW_CLOSED",
                       "The new-lease election window has closed.")
    if old_lease is None or old_lease["arrears_balance_cents"] != 0:
        raise cascades.invalid_state(
            "The terminated lease still carries arrears; clear the ledger "
            "before electing a replacement lease."
        )

    commencement = store.now()
    interval_years = old_lease["revaluation_interval_years"]
    total_gfa = old_lease["total_permitted_gfa_sqft"]
    new_lease = {
        "lessee_id": new_lessee_id,
        "predecessor_lease_id": old_lease["id"],
        "origin_mortgage_id": mortgage["id"],
        "premises_code": premises_code or old_lease["premises_code"],
        "commencement_date": commencement,
        "expiration_date": old_lease["expiration_date"],
        "lease_status": "ACTIVE",
        "rent_status": "BASE_ONLY",
        "initial_annual_base_rent_cents":
            old_lease["current_annual_base_rent_cents"],
        "current_annual_base_rent_cents":
            old_lease["current_annual_base_rent_cents"],
        "revaluation_interval_years": interval_years,
        "next_revaluation_date": store.add_years(commencement, interval_years),
        "reval_collar_min_uplift_bps": old_lease["reval_collar_min_uplift_bps"],
        "reval_collar_max_uplift_bps": old_lease["reval_collar_max_uplift_bps"],
        "percentage_rent_rate_bps": old_lease["percentage_rent_rate_bps"],
        "percentage_rent_breakpoint_cents":
            old_lease["percentage_rent_breakpoint_cents"],
        "percentage_rent_sublease_base_cents": 0,
        "arrears_balance_cents": 0,
        "permitted_use_code": old_lease["permitted_use_code"],
        "total_permitted_gfa_sqft": total_gfa,
        "gfa_allocated_sqft": 0,
        "gfa_unallocated_sqft": total_gfa,
        "improvements_value_cents": old_lease["improvements_value_cents"],
        "reversion_land_value_cents": old_lease["reversion_land_value_cents"],
        "reversion_standard_code": old_lease["reversion_standard_code"],
        "security_deposit_cents": 0,
        "deposit_held_cents": 0,
        "deposit_applied_cents": 0,
        "deposit_refunded_cents": 0,
        "insurance_status": "LAPSED",
        "property_all_risk_limit_cents": 0,
        "builders_risk_limit_cents": 0,
        "lessor_additional_insured": False,
        "insurance_expires_at": None,
    }
    store.stamp(new_lease)
    store.leases[new_lease["id"]] = new_lease

    mortgage["status"] = "NEW_LEASE_ELECTED"
    store.touch(mortgage)

    return object_response(serialize.lease(new_lease), 201)
