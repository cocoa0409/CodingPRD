"""Program endpoints and the launch gate (PRD 3.1, 3.6)."""

from decimal import Decimal

from flask import Blueprint

import db
import guards
import middleware
import response
import serialize
import util
import validate
from constants import (
    ACCREDITATION_LIAISON, ADEQUACY_BASES, ADEQUACY_STATUSES, LAUNCH_STATUSES,
    PROGRAM_DEAN, PROGRAM_DEGREE_LEVELS, QUALIFICATION_POLICIES, READ_ROLES,
    SYSTEM_ADMIN,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import calc, domain, lookup

bp = Blueprint("programs", __name__)

DEFAULT_MIN_TERMINAL_RATIO = Decimal("0.75")


@bp.route("/programs", methods=["POST"])
def create_program():
    middleware.require_role(SYSTEM_ADMIN)
    payload = validate.body()

    name = validate.req_str(payload, "name")
    discipline_id = validate.req_str(payload, "discipline_id")
    degree_level = validate.req_enum(payload, "degree_level", PROGRAM_DEGREE_LEVELS)
    policy = validate.req_enum(payload, "qualification_policy", QUALIFICATION_POLICIES)
    basis = validate.req_enum(payload, "adequacy_basis", ADEQUACY_BASES)
    min_ratio = validate.opt_num(payload, "min_terminal_ratio",
                                default=DEFAULT_MIN_TERMINAL_RATIO,
                                minimum=0, maximum=1)
    substantive = validate.opt_bool(payload, "is_substantive_change", default=False)
    budget = validate.req_int(payload, "credential_budget_cents", minimum=0)

    lookup.discipline(discipline_id)

    row = db.new_row(
        name=name,
        discipline_id=discipline_id,
        degree_level=degree_level,
        qualification_policy=policy,
        adequacy_basis=basis,
        min_terminal_ratio=min_ratio,
        is_substantive_change=substantive,
        credential_budget_cents=budget,
        budget_reserved_cents=0,
        budget_spent_cents=0,
        launch_status="PLANNING",
        adequacy_ratio=Decimal("0.0000"),
        adequacy_status="INSUFFICIENT",
        unqualified_assignment_count=0,
        adequacy_term_id=None,
    )
    store.programs[row["id"]] = row
    return response.created(serialize.program(row))


@bp.route("/programs/<program_id>", methods=["GET"])
def read_program(program_id):
    middleware.require_role(*READ_ROLES)
    row = lookup.program(program_id)
    return response.ok(serialize.program(row))


@bp.route("/programs", methods=["GET"])
def list_programs():
    middleware.require_role(*READ_ROLES)
    discipline_id = validate.q_str("discipline_id")
    adequacy_term_id = validate.q_str("adequacy_term_id")
    launch_status = validate.q_enum("launch_status", LAUNCH_STATUSES)
    adequacy_status = validate.q_enum("adequacy_status", ADEQUACY_STATUSES)
    policy = validate.q_enum("qualification_policy", QUALIFICATION_POLICIES)
    basis = validate.q_enum("adequacy_basis", ADEQUACY_BASES)
    rows = [r for r in db.ordered(store.programs)
            if match(r, "discipline_id", discipline_id)
            and match(r, "adequacy_term_id", adequacy_term_id)
            and match(r, "launch_status", launch_status)
            and match(r, "adequacy_status", adequacy_status)
            and match(r, "qualification_policy", policy)
            and match(r, "adequacy_basis", basis)]
    return list_response(rows, serialize.program)


@bp.route("/programs/<program_id>/adequacy", methods=["GET"])
def read_adequacy(program_id):
    middleware.require_role(*READ_ROLES)
    term_id = validate.q_str("term_id")
    if term_id is None:
        validate.bad("Query parameter 'term_id' is required.")
    basis_override = validate.q_enum("basis_override", ADEQUACY_BASES)

    program = lookup.program(program_id)
    lookup.term(term_id)

    result = calc.program_adequacy(program, term_id, basis=basis_override)
    anchor = lookup.anchor_roster_for_term(program_id, term_id)
    return response.ok({
        "program_id": program_id,
        "term_id": term_id,
        "basis_applied": result["basis_applied"],
        "numerator": util.num(result["numerator"]),
        "denominator": util.num(result["denominator"]),
        "adequacy_ratio": util.fnum(result["adequacy_ratio"]),
        "adequacy_status": result["adequacy_status"],
        "unqualified_assignment_count": result["unqualified_assignment_count"],
        "roster_id": anchor["id"] if anchor else None,
    })


@bp.route("/programs/<program_id>/launch-review", methods=["POST"])
def launch_review(program_id):
    middleware.require_role(PROGRAM_DEAN)
    # Ownership on this endpoint compares X-User-ID to the path parameter.
    middleware.require_dean_owns(program_id)

    payload = validate.body()
    term_id = validate.req_str(payload, "term_id")

    program = lookup.program(program_id)
    lookup.term(term_id)

    roster = lookup.anchor_roster_for_term(program_id, term_id)
    if roster is None:
        raise ApiError("ERR_ROSTER_NOT_FOUND")

    if program["launch_status"] not in ("PLANNING", "ADEQUACY_DENIED"):
        guards.invalid_state("A program in %s may not be submitted for adequacy review."
                             % program["launch_status"])

    program["launch_status"] = "ADEQUACY_REVIEW"
    domain.write_program_adequacy(program, term_id)
    return response.ok(serialize.program(program))


@bp.route("/programs/<program_id>/launch-decision", methods=["POST"])
def launch_decision(program_id):
    middleware.require_role(ACCREDITATION_LIAISON)
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", ("APPROVE", "DENY"))
    validate.opt_str(payload, "rationale")

    program = lookup.program(program_id)

    if program["launch_status"] != "ADEQUACY_REVIEW":
        guards.invalid_state("A program in %s has no launch decision pending."
                             % program["launch_status"])

    if decision == "APPROVE":
        if program.get("is_substantive_change"):
            accepted = False
            for review in lookup.reviews_of_program(program_id):
                if (review["review_type"] == "SUBSTANTIVE_CHANGE"
                        and review["status"] == "CLOSED_ACCEPTED"):
                    accepted = True
                    break
            if not accepted:
                guards.invalid_state(
                    "A substantive-change program needs an accepted "
                    "SUBSTANTIVE_CHANGE review before launch.")
        guards.require_program_clean(program)
        program["launch_status"] = "APPROVED_TO_LAUNCH"
    else:
        program["launch_status"] = "ADEQUACY_DENIED"

    touch(program)
    return response.ok(serialize.program(program))
