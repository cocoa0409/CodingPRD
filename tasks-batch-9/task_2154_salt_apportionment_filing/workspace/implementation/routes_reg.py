"""State registrations, activity records and filing elections."""
from flask import Blueprint

from calc import (adjust_obligations, derive_posture, elections_of_registration,
                  filings_of_registration, group_of_registration,
                  nexus_determination, IN_FLIGHT_FILING_STATUSES)
from errors import ApiError, invalid
from models import (find_election, find_group, find_legal_entity, find_registration,
                    find_activity, ser_activity, ser_election, ser_registration)
from store import db
from util import (money, opt_bool, opt_enum, opt_int, opt_num, opt_state_code,
                  req_enum, req_int, req_num, req_state_code, req_str, ZERO)
from web import (ANY_ROLE, body_json, bump, created, endpoint, mark_dirty, new_record,
                 ok, paginate, query_int, query_str, sort_created)

bp = Blueprint("registrations", __name__)

FACTOR_FORMULAS = ("EQUAL_WEIGHTED_THREE", "DOUBLE_WEIGHTED_SALES", "SINGLE_SALES_FACTOR")
THROWBACK_RULES = ("THROWBACK", "THROWOUT", "NONE")
SERVICE_SOURCING_RULES = ("MARKET_BASED", "COST_OF_PERFORMANCE")
SAFE_HARBOR_BASES = ("PRIOR_YEAR_100", "PRIOR_YEAR_110", "CURRENT_YEAR_90")
ELECTION_BASES = ("COMBINED_UNITARY", "SEPARATE_ENTITY", "CONSOLIDATED")


def guard_not_withdrawn(reg):
    """Band 14 - no write is accepted against a withdrawn registration."""
    if reg["registration_status"] == "WITHDRAWN":
        raise ApiError("ERR_REGISTRATION_WITHDRAWN",
                       "This state registration has been withdrawn and accepts no further work.")


# --------------------------------------------------------------------------
# StateRegistration
# --------------------------------------------------------------------------
@bp.route("/salt/groups/<gid>/registrations", methods=["POST"])
@endpoint(["TaxManager"])
def create_registration(gid):
    group = find_group(gid)
    body = body_json()
    state_code = req_state_code(body, "state_code")
    factor_formula = req_enum(body, "factor_formula", FACTOR_FORMULAS)
    tax_rate = req_num(body, "tax_rate", minv=0, maxv=1)
    throwback_rule = req_enum(body, "throwback_rule", THROWBACK_RULES)
    service_sourcing_rule = req_enum(body, "service_sourcing_rule", SERVICE_SOURCING_RULES)
    safe_harbor_basis = opt_enum(body, "safe_harbor_basis", SAFE_HARBOR_BASES, "PRIOR_YEAR_100")
    sales_threshold = opt_num(body, "economic_nexus_sales_threshold", None, minv=0)
    if sales_threshold is None:
        sales_threshold = money(500000)
    days_threshold = opt_int(body, "economic_nexus_employee_days_threshold", 15, minv=0)
    due_month = opt_int(body, "due_month", 4, minv=1, maxv=12)
    due_day = opt_int(body, "due_day", 15, minv=1, maxv=28)
    extension_months = opt_int(body, "extension_months", 6, minv=0, maxv=12)
    installment_count = opt_int(body, "estimated_installment_count", 4, minv=1, maxv=4)
    prior_year_tax = opt_num(body, "prior_year_tax", None, minv=0)
    if prior_year_tax is None:
        prior_year_tax = ZERO
    current_year_estimated_tax = opt_num(body, "current_year_estimated_tax", None, minv=0)
    if current_year_estimated_tax is None:
        current_year_estimated_tax = ZERO
    early_revocation = opt_bool(body, "state_permits_early_revocation", False)

    for other in db.registrations.values():
        if other["group_id"] == group["id"] and other["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_REGISTRATION",
                           "This group already holds a registration for state %s." % state_code)

    reg = new_record()
    reg.update({
        "group_id": group["id"],
        "state_code": state_code,
        "factor_formula": factor_formula,
        "tax_rate": tax_rate,
        "throwback_rule": throwback_rule,
        "service_sourcing_rule": service_sourcing_rule,
        "economic_nexus_sales_threshold": sales_threshold,
        "economic_nexus_employee_days_threshold": days_threshold,
        "nexus_status": "NONE",
        "registration_status": "NOT_REQUIRED",
        "state_account_number": None,
        "registered_on_date": None,
        "due_month": due_month,
        "due_day": due_day,
        "extension_months": extension_months,
        "estimated_installment_count": installment_count,
        "safe_harbor_basis": safe_harbor_basis,
        "prior_year_tax": prior_year_tax,
        "current_year_estimated_tax": current_year_estimated_tax,
        "state_permits_early_revocation": early_revocation,
        "calendar_rolled_through_year": 0,
        "total_payments_received": money(ZERO),
        "unapplied_payment_balance": money(ZERO),
    })
    db.registrations[reg["id"]] = reg
    return created(ser_registration(reg))


@bp.route("/salt/registrations/<rid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_registration(rid):
    return ok(ser_registration(find_registration(rid)))


@bp.route("/salt/groups/<gid>/registrations", methods=["GET"])
@endpoint(ANY_ROLE)
def list_group_registrations(gid):
    group = find_group(gid)
    rows = [r for r in db.registrations.values() if r["group_id"] == group["id"]]
    return paginate(sort_created(rows), ser_registration)


@bp.route("/salt/registrations/<rid>", methods=["PATCH"])
@endpoint(["TaxManager"])
def patch_registration(rid):
    reg = find_registration(rid)
    body = body_json()
    updates = {}
    value = opt_enum(body, "safe_harbor_basis", SAFE_HARBOR_BASES, None)
    if value is not None:
        updates["safe_harbor_basis"] = value
    value = opt_num(body, "prior_year_tax", None, minv=0)
    if value is not None:
        updates["prior_year_tax"] = value
    value = opt_num(body, "current_year_estimated_tax", None, minv=0)
    if value is not None:
        updates["current_year_estimated_tax"] = value
    value = opt_num(body, "tax_rate", None, minv=0, maxv=1)
    if value is not None:
        updates["tax_rate"] = value
    value = opt_int(body, "due_month", None, minv=1, maxv=12)
    if value is not None:
        updates["due_month"] = value
    value = opt_int(body, "due_day", None, minv=1, maxv=28)
    if value is not None:
        updates["due_day"] = value
    value = opt_int(body, "extension_months", None, minv=0, maxv=12)
    if value is not None:
        updates["extension_months"] = value
    value = opt_num(body, "economic_nexus_sales_threshold", None, minv=0)
    if value is not None:
        updates["economic_nexus_sales_threshold"] = value
    value = opt_int(body, "economic_nexus_employee_days_threshold", None, minv=0)
    if value is not None:
        updates["economic_nexus_employee_days_threshold"] = value
    value = opt_bool(body, "state_permits_early_revocation", None)
    if value is not None:
        updates["state_permits_early_revocation"] = value
    value = opt_enum(body, "factor_formula", FACTOR_FORMULAS, None)
    if value is not None:
        updates["factor_formula"] = value
    value = opt_enum(body, "throwback_rule", THROWBACK_RULES, None)
    if value is not None:
        updates["throwback_rule"] = value
    value = opt_enum(body, "service_sourcing_rule", SERVICE_SOURCING_RULES, None)
    if value is not None:
        updates["service_sourcing_rule"] = value

    guard_not_withdrawn(reg)
    reg.update(updates)
    bump(reg)
    return ok(ser_registration(reg))


@bp.route("/salt/registrations/<rid>/evaluate-nexus", methods=["POST"])
@endpoint(["TaxManager"])
def evaluate_nexus(rid):
    reg = find_registration(rid)
    body = body_json()
    as_of_tax_year = req_int(body, "as_of_tax_year")
    guard_not_withdrawn(reg)

    result = nexus_determination(reg, as_of_tax_year)
    reg["nexus_status"] = result
    if result in ("ECONOMIC", "PHYSICAL") and reg["registration_status"] == "NOT_REQUIRED":
        reg["registration_status"] = "REGISTRATION_REQUIRED"
        adjust_obligations(group_of_registration(reg), 1)
    bump(reg)
    return ok(ser_registration(reg))


@bp.route("/salt/registrations/<rid>/complete-registration", methods=["POST"])
@endpoint(["TaxManager"])
def complete_registration(rid):
    reg = find_registration(rid)
    body = body_json()
    account_number = req_str(body, "state_account_number")
    guard_not_withdrawn(reg)

    was_required = reg["registration_status"] == "REGISTRATION_REQUIRED"
    reg["registration_status"] = "REGISTERED"
    reg["state_account_number"] = account_number
    reg["registered_on_date"] = db.clock
    if was_required:
        adjust_obligations(group_of_registration(reg), -1)
    bump(reg)
    return ok(ser_registration(reg))


@bp.route("/salt/registrations/<rid>/withdraw", methods=["POST"])
@endpoint(["TaxManager"])
def withdraw_registration(rid):
    reg = find_registration(rid)
    body = body_json()
    req_str(body, "reason")
    guard_not_withdrawn(reg)

    for filing in filings_of_registration(reg):
        if filing["preparation_status"] in IN_FLIGHT_FILING_STATUSES:
            raise ApiError("ERR_INVALID_FILING_STATE",
                           "A return on this registration is still in flight.")

    was_required = reg["registration_status"] == "REGISTRATION_REQUIRED"
    reg["registration_status"] = "WITHDRAWN"
    if was_required:
        adjust_obligations(group_of_registration(reg), -1)
    bump(reg)
    return ok(ser_registration(reg))


@bp.route("/salt/registrations/<rid>/roll-filing-calendar", methods=["POST"])
@endpoint(["TaxManager"])
def roll_filing_calendar(rid):
    reg = find_registration(rid)
    body = body_json()
    through_tax_year = req_int(body, "through_tax_year")
    guard_not_withdrawn(reg)

    reg["calendar_rolled_through_year"] = through_tax_year
    for election in elections_of_registration(reg):
        if election["status"] == "ELECTED" and election["expires_after_tax_year"] < through_tax_year:
            election["status"] = "EXPIRED"
            mark_dirty(election)
    bump(reg)
    return ok(ser_registration(reg))


# --------------------------------------------------------------------------
# ActivityRecord
# --------------------------------------------------------------------------
@bp.route("/salt/registrations/<rid>/activity-records", methods=["POST"])
@endpoint(["TaxManager", "StateAnalyst"])
def create_activity_record(rid):
    reg = find_registration(rid)
    body = body_json()

    # Band 4 - body foreign keys resolve before payload shape is judged.
    raw_entity = body.get("legal_entity_id")
    entity = find_legal_entity(raw_entity) if raw_entity is not None else None

    if entity is None:
        raise invalid("'legal_entity_id' is required")
    tax_year = req_int(body, "tax_year")
    destination_sales = opt_num(body, "destination_sales", ZERO)
    origin_sales = opt_num(body, "origin_sales", ZERO)
    purchaser_taxable_in_state = opt_bool(body, "purchaser_taxable_in_state", True)
    service_receipts = opt_num(body, "service_receipts", ZERO)
    cost_state = opt_state_code(body, "cost_of_performance_state_code", None)
    property_average_value = opt_num(body, "property_average_value", ZERO)
    rented_property_annual_rent = opt_num(body, "rented_property_annual_rent", ZERO)
    payroll_compensation = opt_num(body, "payroll_compensation", ZERO)
    employee_days_in_state = opt_int(body, "employee_days_in_state", 0)
    protected_solicitation_only = opt_bool(body, "protected_solicitation_only", False)

    guard_not_withdrawn(reg)

    if entity["group_id"] != reg["group_id"]:
        raise ApiError("ERR_ENTITY_NOT_IN_GROUP",
                       "The named member entity does not belong to this registration's group.")
    if tax_year < 2000:
        raise ApiError("ERR_ACTIVITY_YEAR_MISMATCH", "tax_year must be 2000 or later.")

    record = new_record(versioned=False)
    record.update({
        "registration_id": reg["id"],
        "legal_entity_id": entity["id"],
        "tax_year": tax_year,
        "destination_sales": destination_sales,
        "origin_sales": origin_sales,
        "purchaser_taxable_in_state": purchaser_taxable_in_state,
        "service_receipts": service_receipts,
        "cost_of_performance_state_code": cost_state,
        "property_average_value": property_average_value,
        "rented_property_annual_rent": rented_property_annual_rent,
        "payroll_compensation": payroll_compensation,
        "employee_days_in_state": employee_days_in_state,
        "protected_solicitation_only": protected_solicitation_only,
    })
    db.activity_records[record["id"]] = record
    return created(ser_activity(record))


@bp.route("/salt/activity-records/<aid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_activity_record(aid):
    return ok(ser_activity(find_activity(aid)))


@bp.route("/salt/activity-records", methods=["GET"])
@endpoint(ANY_ROLE)
def list_activity_records():
    registration_id = query_str("registration_id")
    legal_entity_id = query_str("legal_entity_id")
    tax_year = query_int("tax_year")
    rows = list(db.activity_records.values())
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    if legal_entity_id is not None:
        rows = [r for r in rows if r["legal_entity_id"] == legal_entity_id]
    if tax_year is not None:
        rows = [r for r in rows if r["tax_year"] == tax_year]
    return paginate(sort_created(rows), ser_activity)


# --------------------------------------------------------------------------
# FilingElection
# --------------------------------------------------------------------------
def occupied_interval(election):
    if election["status"] == "REVOKED" and election["revocation_tax_year"] is not None:
        return (election["effective_tax_year"], election["revocation_tax_year"] - 1)
    return (election["effective_tax_year"], election["expires_after_tax_year"])


def guard_no_overlap(reg, start, end, exclude_id=None):
    for other in elections_of_registration(reg):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        low, high = occupied_interval(other)
        if low > high:
            continue
        if start <= high and low <= end:
            raise ApiError("ERR_ELECTION_PERIOD_OVERLAP",
                           "The proposed election period overlaps an existing election.")


@bp.route("/salt/registrations/<rid>/elections", methods=["POST"])
@endpoint(["TaxManager"])
def create_election(rid):
    reg = find_registration(rid)
    body = body_json()
    election_basis = req_enum(body, "election_basis", ELECTION_BASES)
    effective_tax_year = req_int(body, "effective_tax_year")
    binding_years = req_int(body, "binding_years", minv=1)
    guard_not_withdrawn(reg)

    expires_after = effective_tax_year + binding_years - 1
    guard_no_overlap(reg, effective_tax_year, expires_after)

    election = new_record()
    election.update({
        "registration_id": reg["id"],
        "election_basis": election_basis,
        "effective_tax_year": effective_tax_year,
        "binding_years": binding_years,
        "expires_after_tax_year": expires_after,
        "status": "ELECTED",
        "revocation_tax_year": None,
        "reinstatement_count": 0,
        "reason": None,
    })
    db.elections[election["id"]] = election
    return created(ser_election(election))


@bp.route("/salt/elections/<eid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_election(eid):
    return ok(ser_election(find_election(eid)))


@bp.route("/salt/registrations/<rid>/elections", methods=["GET"])
@endpoint(ANY_ROLE)
def list_registration_elections(rid):
    reg = find_registration(rid)
    return paginate(elections_of_registration(reg), ser_election)


@bp.route("/salt/elections/<eid>/revoke", methods=["POST"])
@endpoint(["TaxManager"])
def revoke_election(eid):
    election = find_election(eid)
    reg = db.registrations[election["registration_id"]]
    body = body_json()
    revocation_tax_year = req_int(body, "revocation_tax_year")
    reason = req_str(body, "reason") if body.get("reason") is not None else None
    if revocation_tax_year <= election["effective_tax_year"]:
        raise invalid("'revocation_tax_year' must be later than the election's effective_tax_year")

    if election["status"] != "ELECTED":
        raise ApiError("ERR_INVALID_ELECTION_STATE",
                       "Only an ELECTED election may be revoked.")
    if (revocation_tax_year <= election["expires_after_tax_year"]
            and not reg["state_permits_early_revocation"]):
        raise ApiError("ERR_BINDING_PERIOD_ACTIVE",
                       "This state does not permit revocation inside the binding period.")

    election["status"] = "REVOKED"
    election["revocation_tax_year"] = revocation_tax_year
    election["reason"] = reason
    bump(election)
    return ok(ser_election(election))


@bp.route("/salt/elections/<eid>/reinstate", methods=["POST"])
@endpoint(["TaxManager"])
def reinstate_election(eid):
    election = find_election(eid)
    reg = db.registrations[election["registration_id"]]
    body = body_json()
    effective_tax_year = req_int(body, "effective_tax_year")
    binding_years = req_int(body, "binding_years", minv=1)

    if election["status"] != "REVOKED":
        raise ApiError("ERR_INVALID_ELECTION_STATE",
                       "Only a REVOKED election may be reinstated.")

    expires_after = effective_tax_year + binding_years - 1
    guard_no_overlap(reg, effective_tax_year, expires_after, exclude_id=election["id"])

    election["status"] = "ELECTED"
    election["effective_tax_year"] = effective_tax_year
    election["binding_years"] = binding_years
    election["expires_after_tax_year"] = expires_after
    election["revocation_tax_year"] = None
    election["reinstatement_count"] = election["reinstatement_count"] + 1
    bump(election)
    return ok(ser_election(election))
