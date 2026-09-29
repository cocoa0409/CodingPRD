"""Employer accounts, seat credits, locations, assignments, dram-shop and runs."""

from decimal import Decimal

from flask import Blueprint

import chain
import domain
import envelope
import store as st
import validate as v
from auth import authenticate, deny_ownership, EMPLOYER_ADMIN, PROGRAM_ADMIN, \
    STATE_REGULATOR
from calcs import dram_shop_credit, dram_shop_discount, seat_credit_settlement, \
    whole_months
from errors import fail, invalid
from store import apply_changes, create_row, store, touch

bp = Blueprint("employer", __name__)

READ_EMPLOYER_ROLES = (PROGRAM_ADMIN, STATE_REGULATOR, EMPLOYER_ADMIN)


def paged(items):
    limit, offset = v.pagination()
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


def own_account(caller, account_id):
    """Priority 5 for the EmployerAdmin role."""
    if caller.is_employer_admin and caller.user_id != account_id:
        deny_ownership()


# --- accounts --------------------------------------------------------------

@bp.post("/employer-accounts")
def create_account():
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    legal_name = v.req_str(body, "legal_name", 1, 160)
    billing_state_code = v.req_state_code(body, "billing_state_code")
    row = create_row("employer_accounts", {
        "legal_name": legal_name,
        "billing_state_code": billing_state_code,
        "account_status": "ACTIVE",
        "seat_credit_balance": 0,
        "seat_credits_purchased_total": 0,
        "seat_credits_consumed_total": 0,
        "seat_credits_refunded_total": 0,
        "last_purchase_discount_pct": v.quantize(0, 2),
        "last_purchase_total_charged_cents": 0,
        "lifetime_charged_cents": 0,
        "location_count": 0,
        "account_compliance_rate_pct": v.quantize(0, 2),
        "dram_shop_discount_status": "NOT_DOCUMENTED",
        "first_documented_at": None,
        "status_reason": None,
    })
    return envelope.ok_row(row, 201)


@bp.post("/employer-accounts/<account_id>/status")
def set_account_status(account_id):
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    account_status = v.req_enum(body, "account_status", v.ACCOUNT_STATUSES)
    status_reason = v.opt_str(body, "status_reason", 1, None)
    account = v.must_exist("employer_accounts", account_id)
    changes = {"account_status": account_status}
    if status_reason is not None:
        changes["status_reason"] = status_reason
    apply_changes(account, changes)
    return envelope.ok_row(account)


@bp.post("/employer-accounts/<account_id>/seat-credit-purchases")
def buy_seat_credits(account_id):
    caller = authenticate((EMPLOYER_ADMIN, PROGRAM_ADMIN))
    body = v.body()
    seat_quantity = v.req_int(body, "seat_quantity", 1, 500)
    unit_price_cents = v.req_int(body, "unit_price_cents", 1, None)
    account = v.must_exist("employer_accounts", account_id)
    own_account(caller, account["id"])                                 # priority 5
    if account["account_status"] == "SUSPENDED":                       # priority 17
        fail("ERR_ACCOUNT_INVALID_STATE",
             "A SUSPENDED account cannot buy seat credits.")
    result = seat_credit_settlement(seat_quantity, unit_price_cents)
    granted = result["seat_credits_granted"]
    apply_changes(account, {
        "seat_credits_purchased_total":
            account["seat_credits_purchased_total"] + granted,
        "seat_credit_balance": account["seat_credit_balance"] + granted,
        "last_purchase_discount_pct": result["volume_discount_pct"],
        "last_purchase_total_charged_cents": result["total_charged_cents"],
        "lifetime_charged_cents":
            account["lifetime_charged_cents"] + result["total_charged_cents"],
    })
    return envelope.ok_row(account)


@bp.post("/employer-accounts/<account_id>/locations")
def create_location(account_id):
    caller = authenticate((EMPLOYER_ADMIN, PROGRAM_ADMIN))
    body = v.body()
    location_name = v.req_str(body, "location_name", 1, 120)
    jurisdiction_id = v.req_str(body, "state_jurisdiction_id", 1, None)
    premise_type = v.req_enum(body, "premise_type", v.TRACKS)
    annual_premium_cents = v.req_int(body, "annual_premium_cents", 0, 100000000)
    account = v.must_exist("employer_accounts", account_id)
    own_account(caller, account["id"])                                 # priority 5
    jurisdiction = v.must_exist("state_jurisdictions", jurisdiction_id)  # priority 6

    requirement = ("MANDATED" if premise_type in jurisdiction["mandated_tracks"]
                   else "VOLUNTARY")
    empty_rate = v.quantize(chain.LOCATION_EMPTY_RATE_PCT, 2)
    if requirement == "VOLUNTARY":
        posture = "NOT_APPLICABLE"
    else:
        posture = "COMPLIANT"
    location = create_row("employer_locations", {
        "employer_account_id": account["id"],
        "location_name": location_name,
        "state_jurisdiction_id": jurisdiction["id"],
        "premise_type": premise_type,
        "annual_premium_cents": annual_premium_cents,
        "training_requirement": requirement,
        "assigned_server_count": 0,
        "compliant_server_count": 0,
        "grace_server_count": 0,
        "restricted_server_count": 0,
        "compliance_rate_strict_pct": empty_rate,
        "compliance_rate_grace_inclusive_pct": empty_rate,
        "compliance_posture": posture,
    })
    chain.stage_four_five({account["id"]})
    return envelope.ok_row(location, 201)


@bp.post("/employer-accounts/<account_id>/dram-shop-documents")
def issue_document(account_id):
    caller = authenticate((EMPLOYER_ADMIN, PROGRAM_ADMIN))
    body = v.body()
    insurer_name = v.req_str(body, "insurer_name", 1, 120)
    policy_number = v.req_str(body, "policy_number", 1, 64)
    coverage_start = v.req_dt(body, "coverage_period_start")
    coverage_end = v.req_dt(body, "coverage_period_end")
    expected_version = v.req_int(body, "expected_employer_account_version")
    if coverage_end <= coverage_start:
        invalid("Field 'coverage_period_end' must be after 'coverage_period_start'.")
    account = v.must_exist("employer_accounts", account_id)
    own_account(caller, account["id"])                                 # priority 5
    if expected_version != account["version"]:                         # priority 9
        fail("ERR_STALE_ACCOUNT_VERSION",
             "expected_employer_account_version %s does not match the account "
             "version %s." % (expected_version, account["version"]))
    if account["account_status"] == "SUSPENDED":                       # priority 17
        fail("ERR_ACCOUNT_INVALID_STATE",
             "A SUSPENDED account cannot be documented.")
    if account["account_compliance_rate_pct"] < chain.DOCUMENTATION_FLOOR_PCT:
        fail("ERR_COMPLIANCE_RATE_TOO_LOW",                            # priority 38
             "The account compliance rate %s is below the 80.00 documentation floor."
             % account["account_compliance_rate_pct"])

    snapshot_at = store.clock
    locations = chain.locations_of_account(account["id"])
    months_documented = whole_months(account["first_documented_at"], snapshot_at)
    tier, discount_pct = dram_shop_discount(
        account["account_compliance_rate_pct"],
        account["account_status"],
        months_documented,
        account["location_count"],
        domain.min_location_strict_rate(account["id"]),
    )
    credit = dram_shop_credit(locations, discount_pct)

    for prior in domain.documents_of_account(account["id"]):
        if prior["document_state"] == "ISSUED":
            apply_changes(prior, {"document_state": "SUPERSEDED"})

    document = create_row("dram_shop_documents", {
        "employer_account_id": account["id"],
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "coverage_period_start": coverage_start,
        "coverage_period_end": coverage_end,
        "snapshot_at": snapshot_at,
        "document_state": "ISSUED",
        "strict_compliance_rate_pct": account["account_compliance_rate_pct"],
        "months_documented": months_documented,
        "discount_tier": tier,
        "discount_pct": discount_pct,
        "discount_credit_cents": credit,
        "location_count": len(locations),
        "void_reason": None,
    })
    changes = {"dram_shop_discount_status": "DOCUMENTED"}
    if account["first_documented_at"] is None:
        changes["first_documented_at"] = snapshot_at
    if not apply_changes(account, changes):
        touch(account)
    return envelope.ok_row(document, 201)


@bp.get("/employer-accounts/<account_id>")
def read_account(account_id):
    authenticate(READ_EMPLOYER_ROLES)
    return envelope.ok_row(v.must_exist("employer_accounts", account_id))


@bp.get("/employer-accounts/<account_id>/dram-shop-documents")
def list_documents(account_id):
    authenticate(READ_EMPLOYER_ROLES)
    limit, offset = v.pagination()
    account = v.must_exist("employer_accounts", account_id)
    items = domain.documents_of_account(account["id"])
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


# --- locations -------------------------------------------------------------

@bp.get("/employer-locations/<location_id>")
def read_location(location_id):
    authenticate(READ_EMPLOYER_ROLES)
    return envelope.ok_row(v.must_exist("employer_locations", location_id))


@bp.get("/employer-locations")
def list_locations():
    authenticate(READ_EMPLOYER_ROLES)
    filters = {
        "employer_account_id": v.q_str("employer_account_id"),
        "state_jurisdiction_id": v.q_str("state_jurisdiction_id"),
        "compliance_posture": v.q_enum("compliance_posture", v.POSTURES),
    }

    def keep(row):
        for key, wanted in filters.items():
            if wanted is not None and row[key] != wanted:
                return False
        return True

    return paged([r for r in st.rows("employer_locations") if keep(r)])


@bp.get("/employer-locations/<location_id>/compliance-dashboard")
def location_dashboard(location_id):
    authenticate(READ_EMPLOYER_ROLES)
    location = v.must_exist("employer_locations", location_id)
    return envelope.ok({
        "employer_location_id": location["id"],
        "training_requirement": location["training_requirement"],
        "assigned_server_count": location["assigned_server_count"],
        "compliant_server_count": location["compliant_server_count"],
        "grace_server_count": location["grace_server_count"],
        "restricted_server_count": location["restricted_server_count"],
        "compliance_rate_strict_pct": location["compliance_rate_strict_pct"],
        "compliance_rate_grace_inclusive_pct":
            location["compliance_rate_grace_inclusive_pct"],
        "compliance_posture": location["compliance_posture"],
    })


# --- assignments -----------------------------------------------------------

@bp.post("/employer-locations/<location_id>/server-assignments")
def create_assignment(location_id):
    caller = authenticate((EMPLOYER_ADMIN, PROGRAM_ADMIN))
    body = v.body()
    server_id = v.req_str(body, "alcohol_server_id", 1, None)
    role_title = v.req_str(body, "role_title", 1, 80)
    location = v.must_exist("employer_locations", location_id)
    own_account(caller, location["employer_account_id"])               # priority 5
    server = v.must_exist("alcohol_servers", server_id)                # priority 6
    if (location["training_requirement"] == "MANDATED"
            and server["work_eligibility"] == "RESTRICTED"):           # priority 22
        fail("ERR_SERVER_WORK_RESTRICTED",
             "A RESTRICTED server cannot be assigned to a MANDATED location.")
    for other in chain.live_assignments_at_location(location["id"]):   # priority 27
        if other["alcohol_server_id"] == server["id"]:
            fail("ERR_DUPLICATE_ASSIGNMENT",
                 "The server already holds a live assignment at this location.")
    assignment = create_row("server_assignments", {
        "employer_location_id": location["id"],
        "alcohol_server_id": server["id"],
        "role_title": role_title,
        "assignment_state": "ACTIVE",
        "restriction_reason": "NONE",
        "assigned_at": store.clock,
        "restricted_at": None,
        "ended_at": None,
        "end_reason": None,
    })
    chain.recompute_location_and_account(location)
    return envelope.ok_row(assignment, 201)


@bp.post("/server-assignments/<assignment_id>/end")
def end_assignment(assignment_id):
    caller = authenticate((EMPLOYER_ADMIN, PROGRAM_ADMIN))
    body = v.body()
    end_reason = v.opt_str(body, "end_reason", 1, None)
    assignment = v.must_exist("server_assignments", assignment_id)
    location = st.get("employer_locations", assignment["employer_location_id"])
    own_account(caller, location["employer_account_id"])               # priority 5
    if assignment["assignment_state"] not in chain.LIVE_ASSIGNMENT_STATES:
        fail("ERR_ACCOUNT_INVALID_STATE", "The assignment has already ended.")
    changes = {"assignment_state": "ENDED", "ended_at": store.clock}
    if end_reason is not None:
        changes["end_reason"] = end_reason
    apply_changes(assignment, changes)
    chain.recompute_location_and_account(location)
    return envelope.ok_row(assignment)


@bp.get("/employer-locations/<location_id>/server-assignments")
def list_location_assignments(location_id):
    authenticate(READ_EMPLOYER_ROLES)
    limit, offset = v.pagination()
    assignment_state = v.q_enum("assignment_state", v.ASSIGNMENT_STATES)
    location = v.must_exist("employer_locations", location_id)
    items = [
        a for a in st.rows("server_assignments")
        if a["employer_location_id"] == location["id"]
        and (assignment_state is None or a["assignment_state"] == assignment_state)
    ]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


# --- the compliance epoch --------------------------------------------------

@bp.post("/compliance-runs")
def create_compliance_run():
    authenticate((PROGRAM_ADMIN,))
    v.body()
    run = domain.run_compliance_epoch()
    return envelope.ok_row(run, 201)
