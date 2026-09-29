"""Non-solicitation enforcement, the penalty and reinstatement (PRD 3.9)."""

from flask import Blueprint, request

import db
from db import (
    CASE_DISPOSITIONS,
    CASE_STATUSES,
    PENALTY_FLOOR_CENTS,
    TERMINAL_CASE,
    serialize,
    store,
    touch,
)
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    BILLING_ADMINISTRATOR,
    CLIENT,
    COMPLIANCE_OFFICER,
    authenticate,
)
from response import created_response, list_response, object_response
from services import calc, domain
from timeutil import parse_date
from validation import (
    apply_filters,
    body_of,
    check_date,
    check_enum,
    check_int,
    list_params,
    require_present,
    require_string,
)

bp = Blueprint("cases", __name__)

READ_ROLES = {AGENCY_PRINCIPAL, BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT}


@bp.post("/non-solicitation-cases")
def create_case():
    user_id, _role = authenticate({COMPLIANCE_OFFICER})
    body = body_of(request)

    require_present(body, "respondent_client_id", "candidate_id", "allegation_note", "discovered_on")
    allegation_note = require_string(body, "allegation_note", 1, 2000)
    check_date(body, "discovered_on")

    client = domain.resolve("clients", body["respondent_client_id"])
    candidate = domain.resolve("candidates", body["candidate_id"])
    source_placement = domain.resolve_optional("placements", body.get("source_placement_id"))

    if source_placement is not None and source_placement["candidate_id"] != candidate["id"]:
        fail("ERR_ENTITY_RELATIONSHIP_MISMATCH")

    row = {
        "respondent_client_id": client["id"],
        "candidate_id": candidate["id"],
        "source_placement_id": source_placement["id"] if source_placement is not None else None,
        "allegation_note": allegation_note,
        "discovered_on": body["discovered_on"],
        "status": "ALLEGED",
        "prior_substantiated_count": 0,
        "penalty_cents": None,
        "settlement_amount_cents": None,
        "investigation_opened_at": None,
        "substantiated_at": None,
        "opened_by_user_id": user_id,
        "resolved_by_user_id": None,
        "findings_note": None,
    }
    db.stamp_new(row)
    store.non_solicitation_cases[row["id"]] = row
    return created_response(serialize(row))


@bp.get("/non-solicitation-cases/<case_id>")
def get_case(case_id):
    authenticate(READ_ROLES)
    row = domain.resolve("non_solicitation_cases", case_id)
    return object_response(serialize(row))


@bp.get("/non-solicitation-cases")
def list_cases():
    authenticate(READ_ROLES)
    limit, offset, filters = list_params(
        request,
        enum_filters={"status": CASE_STATUSES},
        plain_filters=("respondent_client_id", "candidate_id", "source_placement_id"),
    )
    rows = apply_filters(list(store.non_solicitation_cases.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.post("/non-solicitation-cases/<case_id>/investigate")
def investigate_case(case_id):
    authenticate({COMPLIANCE_OFFICER})
    body = body_of(request)
    require_string(body, "note", 0, 100000, required=False)

    case = domain.resolve("non_solicitation_cases", case_id)
    domain.guard_terminal(case["status"], TERMINAL_CASE)
    if case["status"] != "ALLEGED":
        fail("ERR_INVALID_STATE_TRANSITION")

    client = domain.resolve("clients", case["respondent_client_id"])
    expires_on = client["non_solicitation_expires_on"]
    if expires_on is None:
        fail("ERR_NON_SOLICITATION_TERM_EXPIRED")
    # Conduct discovered on the very last covered day is still actionable.
    if parse_date(case["discovered_on"]) > parse_date(expires_on):
        fail("ERR_NON_SOLICITATION_TERM_EXPIRED")

    case["status"] = "INVESTIGATING"
    case["investigation_opened_at"] = store.now_str()
    touch(case)
    return object_response(serialize(case))


def _prior_substantiated_count(case):
    """Other cases against the same household already substantiated strictly
    before this case's investigation was opened.  Frozen at resolution."""
    opened_at = case["investigation_opened_at"]
    count = 0
    for other in store.non_solicitation_cases.values():
        if other["id"] == case["id"]:
            continue
        if other["respondent_client_id"] != case["respondent_client_id"]:
            continue
        if other["status"] not in ("SUBSTANTIATED", "SETTLED"):
            continue
        if other["substantiated_at"] is None or opened_at is None:
            continue
        if other["substantiated_at"] < opened_at:
            count += 1
    return count


@bp.post("/non-solicitation-cases/<case_id>/resolve")
def resolve_case(case_id):
    user_id, _role = authenticate({COMPLIANCE_OFFICER})
    body = body_of(request)

    require_present(body, "disposition")
    findings_note = require_string(body, "findings_note", 0, 100000, required=False)
    disposition = check_enum(body, "disposition", CASE_DISPOSITIONS)

    case = domain.resolve("non_solicitation_cases", case_id)
    domain.guard_terminal(case["status"], TERMINAL_CASE)
    if case["status"] != "INVESTIGATING":
        fail("ERR_CASE_NOT_INVESTIGATING")

    # Same role, different human: the opener may not be the resolver.
    if user_id == case["opened_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    case["resolved_by_user_id"] = user_id
    if findings_note is not None:
        case["findings_note"] = findings_note

    if disposition == "UNSUBSTANTIATE":
        # The quiet branch: no penalty, no ledger row, no household change.
        case["status"] = "UNSUBSTANTIATED"
        touch(case)
        return object_response(serialize(case))

    client = domain.resolve("clients", case["respondent_client_id"])

    prior_count = _prior_substantiated_count(case)
    if case["source_placement_id"]:
        source = store.placements.get(case["source_placement_id"])
        base_cents = source["fee_cents"] if source is not None else PENALTY_FLOOR_CENTS
    else:
        base_cents = PENALTY_FLOOR_CENTS

    case["status"] = "SUBSTANTIATED"
    case["prior_substantiated_count"] = prior_count
    case["penalty_cents"] = calc.non_solicitation_penalty(base_cents, prior_count)
    case["substantiated_at"] = store.now_str()
    touch(case)

    domain.append_ledger_entry(
        client,
        "PENALTY_ASSESSED",
        case["penalty_cents"],
        "Non-solicitation penalty on case %s" % case["id"],
        related_ref_type="NON_SOLICITATION_CASE",
        related_ref_id=case["id"],
    )
    domain.recompute_client_balance(client)
    domain.suspend_client_cascade(client)

    return object_response(serialize(case))


@bp.post("/non-solicitation-cases/<case_id>/settle")
def settle_case(case_id):
    authenticate({BILLING_ADMINISTRATOR})
    body = body_of(request)

    require_present(body, "settlement_amount_cents")
    memo = require_string(body, "memo", 1, 200, required=False)
    settlement_amount_cents = check_int(body, "settlement_amount_cents", minimum=0)

    case = domain.resolve("non_solicitation_cases", case_id)
    domain.guard_terminal(case["status"], TERMINAL_CASE)
    if case["status"] != "SUBSTANTIATED":
        fail("ERR_INVALID_STATE_TRANSITION")

    penalty_cents = case["penalty_cents"]
    if penalty_cents is not None and settlement_amount_cents > penalty_cents:
        fail("ERR_SETTLEMENT_EXCEEDS_PENALTY")

    client = domain.resolve("clients", case["respondent_client_id"])

    case["status"] = "SETTLED"
    case["settlement_amount_cents"] = settlement_amount_cents
    touch(case)

    domain.append_ledger_entry(
        client,
        "PENALTY_SETTLED",
        -settlement_amount_cents,
        memo,
        related_ref_type="NON_SOLICITATION_CASE",
        related_ref_id=case["id"],
    )
    domain.recompute_client_balance(client)

    # Readmission waits until no other case against the household is still
    # SUBSTANTIATED: two substantiated cases must both be settled.
    outstanding = [
        c for c in store.non_solicitation_cases.values()
        if c["respondent_client_id"] == client["id"]
        and c["id"] != case["id"]
        and c["status"] == "SUBSTANTIATED"
    ]
    if not outstanding and client["status"] == "SUSPENDED":
        client["status"] = "ONBOARDED"
        touch(client)

    return object_response(serialize(case))
