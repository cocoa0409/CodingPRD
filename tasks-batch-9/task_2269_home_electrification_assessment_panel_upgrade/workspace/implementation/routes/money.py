"""Reservation, extension, installation, stacking, remediation and payment."""
from flask import Blueprint, request

import calc
import clock
import domain
import envelope
import errors
import fields
import guards
import store
from errors import ApiError
from guards import (APPLICANT, CONTRACTOR, PROGRAM_ADMIN, PROGRAM_REVIEWER,
                    authorize)
from routes.projects import project_ownership

bp = Blueprint("money", __name__)

TERMINAL_PROJECT_STATES = ("REJECTED", "EXPIRED", "FAILED_FINAL", "CLAWED_BACK", "PAID")


# -------------------------------------------------------------- reservations --
@bp.post("/rebate-projects/<project_id>/reservations")
@authorize(PROGRAM_REVIEWER)
def create_reservation(project_id):
    payload = guards.body()
    expected_version = fields.req_int(payload, "expected_program_version")
    notes = fields.opt_str(payload, "reservation_notes")
    project = domain.get_project(project_id)
    program = domain.program_of_project(project)
    household = domain.household_of_project(project)

    if project["status"] != "APPROVED":
        raise ApiError(errors.ERR_PROJECT_NOT_APPROVED_FOR_RESERVATION)
    if program["status"] != "OPEN":
        raise ApiError(errors.ERR_PROGRAM_NOT_OPEN)
    if expected_version != program["version"]:
        raise ApiError(errors.ERR_STALE_PROGRAM_VERSION)
    if guards.actor_id() == project["reviewed_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES)

    contractor = domain.contractor_of_project(project)
    if contractor is None or contractor["status"] != "ENROLLED_ACTIVE":
        raise ApiError(errors.ERR_CONTRACTOR_NOT_ACTIVE)
    if household["income_tier"] is None or domain.verified_income_verification(
            household["id"]) is None:
        raise ApiError(errors.ERR_INCOME_TIER_NOT_VERIFIED)

    amount = project["provisional_total_incentive_cents"]
    if household["lifetime_cap_remaining_cents"] < 1:
        raise ApiError(errors.ERR_HOUSEHOLD_CAP_EXHAUSTED)
    if household["lifetime_cap_remaining_cents"] < amount:
        raise ApiError(errors.ERR_HOUSEHOLD_CAP_EXHAUSTED)
    if program["budget_available_cents"] < amount:
        raise ApiError(errors.ERR_PROGRAM_BUDGET_EXHAUSTED)

    now = clock.now()
    reservation = store.new_record({
        "project_id": project["id"],
        "program_id": program["id"],
        "reserved_amount_cents": amount,
        "initial_reserved_amount_cents": amount,
        "status": "RESERVED",
        "reserved_at": clock.iso(now),
        "expires_at": clock.iso(clock.add_days(now, program["reservation_ttl_days"])),
        "extension_count": 0,
        "extension_days_granted": 0,
        "committed_at": None,
        "release_reason": None,
        "reservation_notes": notes,
    })
    store.reservations[reservation["id"]] = reservation

    program["budget_available_cents"] -= amount
    program["budget_reserved_cents"] += amount
    store.touch(program)

    household["lifetime_cap_remaining_cents"] -= amount
    household["encumbered_cents"] += amount
    store.touch(household)

    project["status"] = "RESERVED"
    store.touch(project)

    return envelope.object_response(store.public(reservation), 201)


@bp.get("/reservations/<reservation_id>")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_reservation(reservation_id):
    reservation = domain.get_reservation(reservation_id)
    return envelope.object_response(store.public(reservation))


@bp.get("/reservations")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_reservations():
    limit, offset = guards.pagination()
    project_id = request.args.get("project_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    records = store.ordered(
        store.reservations,
        lambda r: (project_id is None or r["project_id"] == project_id)
        and (program_id is None or r["program_id"] == program_id)
        and (status is None or r["status"] == status),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/reservations/<reservation_id>/extensions")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_ADMIN)
def extend_reservation(reservation_id):
    payload = guards.body()
    additional_days = fields.req_int(payload, "additional_days")
    fields.opt_str(payload, "extension_reason")
    reservation = domain.get_reservation(reservation_id)
    program = domain.get_program(reservation["program_id"])
    project = store.projects.get(reservation["project_id"])
    now = clock.now()
    expires_at = clock.parse_datetime(reservation["expires_at"])

    if reservation["status"] != "RESERVED":
        raise ApiError(errors.ERR_RESERVATION_NOT_ACTIVE)
    if project is None or project["status"] not in ("RESERVED", "CONTRACTOR_HOLD"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    if now >= expires_at:
        raise ApiError(errors.ERR_RESERVATION_EXPIRED)

    window_opens = clock.add_days(expires_at, -program["extension_window_days"])
    if now < window_opens:
        raise ApiError(errors.ERR_EXTENSION_WINDOW_NOT_OPEN)
    if reservation["extension_count"] >= program["max_extensions_per_reservation"]:
        raise ApiError(errors.ERR_EXTENSION_LIMIT_REACHED)
    if additional_days < 1 or additional_days > program["max_extension_days"]:
        raise ApiError(errors.ERR_EXTENSION_DAYS_EXCEEDED)

    reservation["expires_at"] = clock.iso(clock.add_days(expires_at, additional_days))
    reservation["extension_count"] += 1
    reservation["extension_days_granted"] += additional_days
    store.touch(reservation)
    return envelope.object_response(store.public(reservation))


# --------------------------------------------------------------- installation -
@bp.post("/rebate-projects/<project_id>/installation")
@authorize(CONTRACTOR)
def report_installation(project_id):
    payload = guards.body()
    start_date = fields.req_date(payload, "install_start_date")
    end_date = fields.req_date(payload, "install_end_date")
    if end_date < start_date:
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            message="install_end_date must not be earlier than install_start_date.",
        )
    installed_amps = fields.req_int(payload, "installed_panel_amps", minimum=0)
    actual_cost = fields.req_int(payload, "actual_project_cost_cents", minimum=0)
    raw_results = fields.req_list(payload, "measure_results")
    results = []
    for item in raw_results:
        entry = fields.entry_object(item, "measure_results")
        results.append({
            "measure_code": fields.req_str(entry, "measure_code", allow_empty=False),
            "verified_quantity": fields.req_int(entry, "verified_quantity", minimum=0),
            "actual_cost_cents": fields.req_int(entry, "actual_cost_cents", minimum=0),
        })

    project = domain.get_project(project_id)
    project_ownership(project)

    if project["status"] != "RESERVED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    reservation = domain.reservation_of_project(project["id"])
    if reservation is None or reservation["status"] != "RESERVED":
        raise ApiError(errors.ERR_RESERVATION_NOT_ACTIVE)
    if clock.now() >= clock.parse_datetime(reservation["expires_at"]):
        raise ApiError(errors.ERR_RESERVATION_EXPIRED)

    contractor = domain.contractor_of_project(project)
    domain.require_contractor_fitness(contractor)

    lines = {line["measure_code"]: line for line in domain.project_measures(project["id"])}
    for result in results:
        if result["measure_code"] not in lines:
            raise ApiError(errors.ERR_MEASURE_NOT_ON_PROJECT)

    program = domain.program_of_project(project)
    for result in results:
        item = domain.catalog_item(program["id"], result["measure_code"])
        if item is None:
            continue
        if item["required_panel_capacity_amps"] > installed_amps:
            raise ApiError(errors.ERR_PANEL_CAPACITY_INSUFFICIENT)

    overlaps = domain.install_window_overlaps(
        project, contractor["id"], start_date, end_date)
    if overlaps >= contractor["crew_capacity"]:
        raise ApiError(errors.ERR_CONTRACTOR_CREW_CAPACITY_EXCEEDED)

    for result in results:
        line = lines[result["measure_code"]]
        line["install_status"] = "INSTALLED"
        line["verified_quantity"] = result["verified_quantity"]
        line["actual_cost_cents"] = result["actual_cost_cents"]
        store.touch(line)

    project["install_start_date"] = start_date
    project["install_end_date"] = end_date
    project["installed_panel_amps"] = installed_amps
    project["actual_project_cost_cents"] = actual_cost
    project["status"] = "INSTALLED"
    store.touch(project)
    return envelope.object_response(store.public(project))


# ------------------------------------------------------ stacking declarations -
@bp.post("/rebate-projects/<project_id>/stacking-declarations")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_ADMIN)
def create_stacking_declaration(project_id):
    payload = guards.body()
    utility_name = fields.req_str(payload, "utility_program_name", allow_empty=False)
    utility_rebate = fields.req_int(payload, "utility_rebate_cents", minimum=0)
    federal_claimed = fields.opt_int(
        payload, "federal_credit_claimed_cents", default=0, minimum=0)
    project = domain.get_project(project_id)
    project_ownership(project)

    if project["status"] in TERMINAL_PROJECT_STATES:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)

    program = domain.program_of_project(project)
    outcome = calc.benefit_stacking_limit(program, project, utility_rebate)
    if outcome["allowed_state_incentive_cents"] <= 0:
        raise ApiError(errors.ERR_STACKING_LIMIT_EXCEEDED)

    prior = domain.active_declaration(project["id"])
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        store.touch(prior)

    record = {
        "project_id": project["id"],
        "utility_program_name": utility_name,
        "utility_rebate_cents": utility_rebate,
        "federal_credit_claimed_cents": federal_claimed,
        "status": "ACTIVE",
    }
    record.update(outcome)
    declaration = store.new_record(record)
    store.stacking_declarations[declaration["id"]] = declaration

    project["stacking_adjusted_state_incentive_cents"] = outcome["allowed_state_incentive_cents"]
    store.touch(project)
    return envelope.object_response(store.public(declaration), 201)


@bp.get("/rebate-projects/<project_id>/stacking-declarations")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_stacking_declarations(project_id):
    limit, offset = guards.pagination()
    status = request.args.get("status")
    project = domain.get_project(project_id)
    records = store.ordered(
        store.stacking_declarations,
        lambda d: d["project_id"] == project["id"] and (status is None or d["status"] == status),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


# ---------------------------------------------------------------- remediation -
@bp.post("/rebate-projects/<project_id>/remediation")
@authorize(CONTRACTOR)
def open_remediation(project_id):
    payload = guards.body()
    fields.opt_str(payload, "remediation_notes")
    raw_results = fields.opt_list(payload, "measure_results")
    results = []
    if raw_results is not None:
        for item in raw_results:
            entry = fields.entry_object(item, "measure_results")
            results.append({
                "measure_code": fields.req_str(entry, "measure_code", allow_empty=False),
                "verified_quantity": fields.opt_int(entry, "verified_quantity", minimum=0),
                "actual_cost_cents": fields.opt_int(entry, "actual_cost_cents", minimum=0),
            })

    project = domain.get_project(project_id)
    project_ownership(project)

    program = domain.program_of_project(project)
    if project["status"] != "INSPECTION_FAILED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    if project["remediation_count"] >= program["max_remediations_per_project"]:
        raise ApiError(
            errors.ERR_INVALID_STATE_TRANSITION,
            message="The project has consumed every remediation cycle.",
        )
    reservation = domain.reservation_of_project(project["id"])
    if reservation is None or reservation["status"] != "RESERVED":
        raise ApiError(errors.ERR_RESERVATION_NOT_ACTIVE)
    if clock.now() >= clock.parse_datetime(reservation["expires_at"]):
        raise ApiError(errors.ERR_RESERVATION_EXPIRED)

    contractor = domain.contractor_of_project(project)
    domain.require_contractor_fitness(contractor)

    lines = {line["measure_code"]: line for line in domain.project_measures(project["id"])}
    for result in results:
        if result["measure_code"] not in lines:
            raise ApiError(errors.ERR_MEASURE_NOT_ON_PROJECT)

    reported = {}
    for result in results:
        reported[result["measure_code"]] = result

    for line in domain.project_measures(project["id"]):
        changed = False
        result = reported.get(line["measure_code"])
        if result is not None:
            if result["verified_quantity"] is not None:
                line["verified_quantity"] = result["verified_quantity"]
            if result["actual_cost_cents"] is not None:
                line["actual_cost_cents"] = result["actual_cost_cents"]
            changed = True
        if line["verification_status"] == "REJECTED":
            line["verification_status"] = "PENDING"
            line["rejection_reason"] = None
            changed = True
        if changed:
            store.touch(line)

    project["remediation_count"] += 1
    project["status"] = "REMEDIATION"
    store.touch(project)
    return envelope.object_response(store.public(project))


# -------------------------------------------------------------------- payment -
@bp.post("/rebate-projects/<project_id>/payment")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def pay_project(project_id):
    payload = guards.body()
    fields.opt_str(payload, "payment_reference")
    project = domain.get_project(project_id)
    program = domain.program_of_project(project)
    household = domain.household_of_project(project)

    if project["status"] != "VERIFIED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    if program["status"] != "OPEN":
        raise ApiError(errors.ERR_PROGRAM_NOT_OPEN)
    reservation = domain.reservation_of_project(project["id"])
    if reservation is None or reservation["status"] != "RESERVED":
        raise ApiError(errors.ERR_RESERVATION_NOT_ACTIVE)
    if domain.project_has_scheduled_inspection(project["id"]):
        raise ApiError(errors.ERR_OPEN_INSPECTION_PENDING)
    if guards.actor_id() == project["reviewed_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES)

    declaration = domain.active_declaration(project["id"])
    if declaration is not None:
        basis = project["stacking_adjusted_state_incentive_cents"]
    else:
        basis = project["final_total_incentive_cents"]
    if basis is None:
        basis = 0
    initial = reservation["initial_reserved_amount_cents"]
    disbursed = min(basis, initial)
    release_delta = initial - disbursed

    reservation["reserved_amount_cents"] = disbursed
    reservation["status"] = "COMMITTED"
    reservation["committed_at"] = clock.now_iso()
    store.touch(reservation)

    program["budget_reserved_cents"] -= initial
    program["budget_committed_cents"] += disbursed
    program["budget_available_cents"] += release_delta
    store.touch(program)

    household["encumbered_cents"] -= release_delta
    household["lifetime_cap_remaining_cents"] += release_delta
    store.touch(household)

    project["disbursed_amount_cents"] = disbursed
    project["status"] = "PAID"
    store.touch(project)
    return envelope.object_response(store.public(project))
