"""Participant endpoints: enrollment, read, PATCH (custodian sync / termination
cascade), contribution election, loan eligibility."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, check_participant_ownership, paginate
from response import success_object, success_list
from services import audit
from services import calculations as calc
from services.state import (get_plan, get_participant, get_participant_in_plan,
                            plan_of_participant, election_of_participant,
                            create_tax_event, set_loan_lock_from_event,
                            active_suspension_records, has_active_suspension)
from services.util import new_id, now_iso, today, touch, iso, date_iso, parse

bp = Blueprint("participants", __name__)


def _bad(msg):
    return errors.err(errors.ERR_INVALID_REQUEST, msg, 400)


@bp.route("/plans/<plan_id>/participants", methods=["POST"])
def enroll_participant(plan_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    plan = get_plan(plan_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    full_name = body.get("full_name")
    vested = body.get("vested_balance_cents")
    external_ref = body.get("external_ref")
    if not isinstance(full_name, str) or not full_name:
        raise _bad("full_name is required")
    if not isinstance(vested, int) or isinstance(vested, bool):
        raise _bad("vested_balance_cents is required and must be an integer")
    if external_ref is not None and not isinstance(external_ref, str):
        raise _bad("external_ref must be a string")
    participant = {
        "id": new_id(),
        "plan_id": plan["id"],
        "full_name": full_name,
        "external_ref": external_ref,
        "vested_balance_cents": vested,
        "employment_status": "ACTIVE",
        "terminated_on": None,
        "contribution_status": "NONE",
        "ytd_taxable_distributions_cents": 0,
        "loan_eligibility_locked_until": None,
    }
    participant["created_at"] = now_iso()
    participant["updated_at"] = participant["created_at"]
    participant["version"] = 1
    db.participants[participant["id"]] = participant
    audit.append(plan["id"], role, user_id, "PARTICIPANT_ENROLLED",
                 "Participant", participant["id"], {"full_name": full_name})
    return success_object(participant, status=201)


@bp.route("/participants/<participant_id>", methods=["GET"])
def read_participant(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    return success_object(participant)


def _terminate_participant(participant, terminated_on_dt, actor_role, actor_id):
    """The offset cascade for participant termination (PRD section 3.2)."""
    participant["employment_status"] = "TERMINATED"
    participant["terminated_on"] = date_iso(terminated_on_dt)

    # Link 1: each DISBURSED loan with outstanding > 0 -> OFFSET, created_at ASC
    loans = [l for l in db.loans.values()
             if l["participant_id"] == participant["id"]
             and l["lifecycle_status"] == "DISBURSED"
             and (l.get("outstanding_principal_cents") or 0) > 0]
    loans.sort(key=lambda l: l["created_at"])
    for loan in loans:
        loan["lifecycle_status"] = "OFFSET"
        # Link 2 (taxable amount) is computed over the installment statuses as
        # they stand at the offset transition — PRD section 3.7 sums accrued
        # unpaid interest over installments "whose status is PENDING or
        # MISSED", and the deemed/offset divergence sentence is only coherent
        # if that evaluation sees the pre-close statuses. Compute first, then
        # close the remaining PENDING/MISSED installments per link 1.
        taxable = calc.taxable_amount_for_loan(loan, terminated_on_dt)
        # close remaining PENDING/MISSED installments
        for inst in calc.loan_installments(loan["id"]):
            if inst["status"] in ("PENDING", "MISSED"):
                inst["status"] = "CLOSED"
        # Link 2: TaxEvent LOAN_OFFSET with cutoff = terminated_on
        create_tax_event(participant, "LOAN_OFFSET", loan["id"], taxable, terminated_on_dt)
        # Link 3: bump YTD and set lock
        set_loan_lock_from_event(participant, terminated_on_dt)
        touch(loan)

    # Election cascade
    election = election_of_participant(participant["id"])
    if election and election["status"] in ("ACTIVE", "SUSPENDED"):
        election["status"] = "TERMINATED"
        touch(election)
    participant["contribution_status"] = "TERMINATED"

    # Cancel PENDING approval tasks on participant's open Loan subjects
    open_loan_ids = {l["id"] for l in db.loans.values()
                     if l["participant_id"] == participant["id"]
                     and l["lifecycle_status"] in ("REQUESTED", "APPROVED", "DISBURSED")}
    for task in db.approval_tasks.values():
        if task["subject_type"] == "LOAN" and task["subject_id"] in open_loan_ids \
                and task["status"] == "PENDING":
            task["status"] = "CANCELLED"
            touch(task)

    audit.append(participant["plan_id"], actor_role, actor_id,
                 "PARTICIPANT_TERMINATED", "Participant", participant["id"],
                 {"terminated_on": participant["terminated_on"]})


@bp.route("/participants/<participant_id>", methods=["PATCH"])
def patch_participant(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    participant = get_participant(participant_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")

    new_vested = body.get("vested_balance_cents")
    new_employment = body.get("employment_status")
    new_terminated_on = body.get("terminated_on")

    if new_vested is not None:
        if not isinstance(new_vested, int) or isinstance(new_vested, bool):
            raise _bad("vested_balance_cents must be an integer")
    if new_employment is not None and new_employment not in ("ACTIVE", "TERMINATED"):
        raise _bad("employment_status must be ACTIVE or TERMINATED")
    terminated_on_dt = None
    if new_terminated_on is not None:
        if not isinstance(new_terminated_on, str):
            raise _bad("terminated_on must be an ISO 8601 string")
        try:
            terminated_on_dt = parse(new_terminated_on)
        except Exception:
            raise _bad("terminated_on must be a valid ISO 8601 timestamp")

    # Apply vested balance sync
    if new_vested is not None:
        participant["vested_balance_cents"] = new_vested

    # Termination transition
    if new_employment == "TERMINATED":
        if participant["employment_status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE,
                             "Participant is already TERMINATED", 409)
        if terminated_on_dt is None:
            terminated_on_dt = today()
        _terminate_participant(participant, terminated_on_dt, role, user_id)
    elif new_employment == "ACTIVE":
        # No ACTIVE -> ACTIVE transition defined; treat as no-op on employment
        pass

    touch(participant)
    return success_object(participant)


@bp.route("/participants/<participant_id>/contribution-election", methods=["PUT"])
def put_election(participant_id):
    user_id, role = require_roles("Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    pct = body.get("deferral_pct")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        raise _bad("deferral_pct is required and must be a number")
    if not (pct > 0 and pct <= 60):
        raise _bad("deferral_pct must be greater than 0 and at most 60")

    existing = election_of_participant(participant["id"])
    if existing is None:
        election = {
            "id": new_id(),
            "participant_id": participant["id"],
            "deferral_pct": pct,
            "status": "ACTIVE",
            "effective_on": now_iso(),
        }
        election["created_at"] = now_iso()
        election["updated_at"] = election["created_at"]
        election["version"] = 1
        db.contribution_elections[election["id"]] = election
        db.election_by_participant[participant["id"]] = election["id"]
    else:
        election = existing
        if election["status"] == "ACTIVE":
            election["deferral_pct"] = pct
            touch(election)
        elif election["status"] == "SUSPENDED":
            raise errors.err(errors.ERR_INVALID_STATE,
                             "Election is SUSPENDED; use restart", 409)
        else:  # TERMINATED
            raise errors.err(errors.ERR_INVALID_STATE,
                             "Election is TERMINATED", 409)
    participant["contribution_status"] = "ACTIVE"
    touch(participant)
    audit.append(participant["plan_id"], role, user_id, "ELECTION_SET",
                 "ContributionElection", election["id"], {"deferral_pct": pct})
    return success_object(election)


@bp.route("/participants/<participant_id>/contribution-election", methods=["GET"])
def get_election(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    election = election_of_participant(participant["id"])
    items = [election] if election else []
    # Non-paginated list-based response still carries pagination meta per PRD 2.3
    from middleware import parse_limit_offset
    limit, offset = parse_limit_offset()
    page = items[offset:offset + limit]
    return success_list(page, len(items), limit, offset)


@bp.route("/participants/<participant_id>/contribution-election/restart", methods=["POST"])
def restart_election(participant_id):
    user_id, role = require_roles("Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    plan = plan_of_participant(participant)
    # Plan posture gate
    if plan["status"] != "ACTIVE":
        raise errors.err(errors.ERR_PLAN_NOT_ACTIVE,
                         f"Plan is {plan['status']}; restart requires ACTIVE", 409)
    # Suspension check
    today_dt = today()
    if has_active_suspension(participant["id"], today_dt):
        raise errors.err(errors.ERR_SUSPENSION_STILL_ACTIVE,
                         "A suspension record is still ACTIVE", 422)
    if participant["employment_status"] != "ACTIVE":
        raise errors.err(errors.ERR_EMPLOYMENT_NOT_ACTIVE,
                         "Employment is not ACTIVE", 422)
    election = election_of_participant(participant["id"])
    if election is None or election["status"] != "SUSPENDED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Election is not SUSPENDED", 409)
    election["status"] = "ACTIVE"
    touch(election)
    participant["contribution_status"] = "ACTIVE"
    touch(participant)
    audit.append(participant["plan_id"], role, user_id, "ELECTION_RESTARTED",
                 "ContributionElection", election["id"], {})
    return success_object(election)


@bp.route("/participants/<participant_id>/loan-eligibility", methods=["GET"])
def loan_eligibility(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    plan = plan_of_participant(participant)
    today_dt = today()
    max_amt = calc.loan_maximum_amount(participant, plan, today_dt)
    outstanding_count = calc.outstanding_loan_count(participant["id"])
    locked_until = participant.get("loan_eligibility_locked_until")
    locked = False
    if locked_until:
        locked = today_dt < parse(locked_until)
    eligible = (
        participant["employment_status"] == "ACTIVE"
        and not locked
        and outstanding_count < plan["max_loans_outstanding"]
        and not has_active_suspension(participant["id"], today_dt)
    )
    return success_object({
        "eligible": eligible,
        "max_loan_amount_cents": max_amt,
        "outstanding_loan_count": outstanding_count,
        "loan_eligibility_locked_until": locked_until,
    })
