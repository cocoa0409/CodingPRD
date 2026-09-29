"""Candidacy endpoints — filing, the petition review loop, slates, withdrawal
and the officer-transition axis (PRD 3.2, 3.9)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("candidacies", __name__)


def candidate_eligible(student, office):
    """PRD 3.2 — every bar the office sets, reported as ERR_CANDIDATE_INELIGIBLE."""
    if student["enrollment_status"] != "ENROLLED":
        return False
    if student["disciplinary_hold"]:
        return False
    if student["class_year"] not in (office["eligible_class_years"] or []):
        return False
    if student["gpa"] < office["min_gpa"]:
        return False
    if student["credits_completed"] < office["min_credits"]:
        return False
    return True


def check_slate(leader, election_id, self_id):
    """PRD 3.2 — same election, not itself, exactly one level deep."""
    if leader is None:
        return
    if leader["election_id"] != election_id:
        errors.fail(errors.ERR_INVALID_SLATE,
                    "The slate leader belongs to another election.")
    if self_id is not None and leader["id"] == self_id:
        errors.fail(errors.ERR_INVALID_SLATE,
                    "A candidacy may not lead its own slate.")
    if leader["slate_leader_candidacy_id"] is not None:
        errors.fail(errors.ERR_INVALID_SLATE,
                    "Slates are exactly one level deep.")


@bp.post("/candidacies")
def create_candidacy():
    auth.require(constants.CANDIDATE)
    body = validation.get_body()

    # rule 4 — body foreign keys, in input-list order
    election = lookup.fk_election(body)
    office = lookup.fk_office(body)
    student = lookup.fk_student(body)
    leader = lookup.fk_candidacy(body, "slate_leader_candidacy_id")

    # rule 5 — schema
    validation.req_str(body, "election_id")
    validation.req_str(body, "office_id")
    student_id = validation.req_str(body, "student_id")
    if validation.present(body, "slate_leader_candidacy_id"):
        validation.req_str(body, "slate_leader_candidacy_id")
    statement = validation.opt_text(body, "statement")

    # rule 7 — ownership
    auth.require_owner(student_id)

    # rule 10 — election phase
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Candidacies may only be filed while the election is PETITIONING.")

    # rule 18 — candidate eligibility
    if not candidate_eligible(student, office):
        errors.fail(errors.ERR_CANDIDATE_INELIGIBLE,
                    "The student does not clear every eligibility bar of this office.")

    # rule 21 — one live candidacy per student per election
    for existing in lookup.candidacies_of(election["id"]):
        if existing["student_id"] != student["id"]:
            continue
        if existing["status"] not in constants.CANDIDACY_DEAD_FOR_DUPLICATE:
            errors.fail(errors.ERR_DUPLICATE_CANDIDACY,
                        "The student already holds a live candidacy in this election.")

    # rule 28 — slate shape
    check_slate(leader, election["id"], None)

    row = db.new_row(db.store.candidacies, {
        "election_id": election["id"],
        "office_id": office["id"],
        "student_id": student["id"],
        "slate_leader_candidacy_id": leader["id"] if leader else None,
        "statement": statement,
        "status": "DRAFT",
        "transition_status": "NOT_APPLICABLE",
        "training_modules_completed": 0,
        "ballot_position": None,
        "petition_signature_total_count": 0,
        "petition_signature_valid_count": 0,
        "petition_signature_ineligible_count": 0,
        "petition_signature_pending_count": 0,
        "petition_signature_rejected_count": 0,
        "petition_signature_voided_count": 0,
        "spending_reported_cents": 0,
        "spending_committed_cents": 0,
        "spending_reversed_cents": 0,
        "spending_final_cents": None,
        "poster_count": 0,
        "penalty_points_total": 0,
        "slate_snapshot_member_ids": [],
        "raw_votes_count": 0,
        "certified_votes_count": 0,
        "provisional_share_pct": Decimal("0.00"),
        "certified_share_pct": Decimal("0.00"),
        "disqualified_reason": None,
        "term_start_date": None,
        "term_end_date": None,
        "activated_at": None,
    })
    if leader is not None:
        calc.recompute_spend_group(row)
    return response.object_response(serialize.candidacy(row), 201)


@bp.get("/candidacies")
def list_candidacies():
    auth.require_any()
    rows = listing.filtered(db.store.candidacies, {
        "election_id": ("election_id", None),
        "office_id": ("office_id", None),
        "student_id": ("student_id", None),
        "slate_leader_candidacy_id": ("slate_leader_candidacy_id", None),
        "status": ("status", None),
        "transition_status": ("transition_status", None),
    })
    return listing.list_response(rows, serialize.candidacy)


@bp.get("/candidacies/<candidacy_id>")
def read_candidacy(candidacy_id):
    auth.require_any()
    row = lookup.candidacy(candidacy_id)
    return response.object_response(serialize.candidacy(row))


@bp.post("/candidacies/<candidacy_id>/submit-petition")
def submit_petition(candidacy_id):
    auth.require(constants.CANDIDATE)
    candidacy = lookup.candidacy(candidacy_id)
    election = db.store.elections[candidacy["election_id"]]

    auth.require_owner(candidacy["student_id"])

    if candidacy["status"] not in ("DRAFT", "RETURNED", "PETITION_DEFICIENT"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "A petition may only be submitted from DRAFT, RETURNED or PETITION_DEFICIENT.")
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Petitions may only be submitted while the election is PETITIONING.")
    if not db.now() < election["petition_deadline"]:
        errors.fail(errors.ERR_PETITION_DEADLINE_PASSED,
                    "The petition deadline has passed.")

    if candidacy["status"] == "DRAFT":
        student = db.store.students.get(candidacy["student_id"])
        office = db.store.offices.get(candidacy["office_id"])
        if student is None or office is None or not candidate_eligible(student, office):
            errors.fail(errors.ERR_CANDIDATE_INELIGIBLE,
                        "The student does not clear every eligibility bar of this office.")

    db.set_fields(candidacy, status="UNDER_REVIEW")
    db.touch(candidacy)
    return response.object_response(serialize.candidacy(candidacy))


@bp.post("/candidacies/<candidacy_id>/return")
def return_petition(candidacy_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    candidacy = lookup.candidacy(candidacy_id)
    election = db.store.elections[candidacy["election_id"]]

    body = validation.get_body()
    validation.req_text(body, "reason")

    if candidacy["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_INVALID_STATE,
                    "A petition may only be returned from UNDER_REVIEW.")
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Petitions may only be returned while the election is PETITIONING.")

    db.set_fields(candidacy, status="RETURNED")
    db.touch(candidacy)
    return response.object_response(serialize.candidacy(candidacy))


@bp.post("/candidacies/<candidacy_id>/approve")
def approve_petition(candidacy_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    candidacy = lookup.candidacy(candidacy_id)
    election = db.store.elections[candidacy["election_id"]]
    office = db.store.offices.get(candidacy["office_id"])

    if candidacy["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_INVALID_STATE,
                    "A petition may only be approved from UNDER_REVIEW.")
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Petitions may only be approved while the election is PETITIONING.")
    # approval tolerates the deadline instant itself; submission does not
    if not db.now() <= election["petition_deadline"]:
        errors.fail(errors.ERR_PETITION_DEADLINE_PASSED,
                    "The petition deadline has passed.")
    if candidacy["petition_signature_valid_count"] < office["required_signature_count"]:
        errors.fail(errors.ERR_INSUFFICIENT_SIGNATURES,
                    "The petition has not reached the required valid signature count.")

    db.set_fields(candidacy, status="ELIGIBLE")
    db.touch(candidacy)

    # approval repairs the slate
    for member in db.by_seq(list(db.store.candidacies.values())):
        if member["slate_leader_candidacy_id"] == candidacy["id"] and member["status"] == "SLATE_SUSPENDED":
            db.set_fields(member, status="ELIGIBLE")

    return response.object_response(serialize.candidacy(candidacy))


@bp.post("/candidacies/<candidacy_id>/withdraw")
def withdraw(candidacy_id):
    auth.require(constants.CANDIDATE)
    candidacy = lookup.candidacy(candidacy_id)
    election = db.store.elections[candidacy["election_id"]]

    body = validation.get_body()
    validation.opt_text(body, "reason")

    auth.require_owner(candidacy["student_id"])

    if candidacy["status"] not in constants.CANDIDACY_WITHDRAWABLE:
        errors.fail(errors.ERR_INVALID_STATE,
                    "This candidacy may no longer be withdrawn.")
    if election["status"] not in ("PETITIONING", "BALLOT_BUILDING"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Withdrawal is only permitted while the election is PETITIONING or BALLOT_BUILDING.")

    was_eligible = candidacy["status"] == "ELIGIBLE"
    db.set_fields(candidacy, status="WITHDRAWN")
    db.touch(candidacy)
    if was_eligible:
        cascades.void_active_lines(candidacy)
    return response.object_response(serialize.candidacy(candidacy))


@bp.post("/candidacies/<candidacy_id>/slate-membership")
def slate_membership(candidacy_id):
    auth.require(constants.CANDIDATE)
    candidacy = lookup.candidacy(candidacy_id)
    body = validation.get_body()

    # rule 4 — body foreign key
    leader = lookup.fk_candidacy(body, "slate_leader_candidacy_id")

    # rule 5 — schema
    if not validation.has_key(body, "slate_leader_candidacy_id"):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Missing required field: slate_leader_candidacy_id.")
    if validation.present(body, "slate_leader_candidacy_id"):
        validation.req_str(body, "slate_leader_candidacy_id")
    expected_version = validation.req_int(body, "expected_candidacy_version")

    # rule 7 — ownership
    auth.require_owner(candidacy["student_id"])

    # rule 12 — optimistic concurrency on the candidacy version
    if expected_version != candidacy["version"]:
        errors.fail(errors.ERR_STALE_CANDIDACY_VERSION,
                    "expected_candidacy_version does not match the candidacy version.")

    # rule 28 — slate shape
    check_slate(leader, candidacy["election_id"], candidacy["id"])

    old_members = calc.live_members(candidacy)
    db.set_fields(candidacy, slate_leader_candidacy_id=leader["id"] if leader else None)
    db.touch(candidacy)
    new_members = calc.live_members(candidacy)

    seen = set()
    for member in old_members + new_members:
        if member["id"] in seen:
            continue
        seen.add(member["id"])
        calc.recompute_spend_for(member)

    return response.object_response(serialize.candidacy(candidacy))


@bp.post("/candidacies/<candidacy_id>/record-training")
def record_training(candidacy_id):
    auth.require(constants.CANDIDATE)
    candidacy = lookup.candidacy(candidacy_id)
    office = db.store.offices.get(candidacy["office_id"])

    body = validation.get_body()
    modules = validation.req_int(body, "modules_completed", minimum=0)

    auth.require_owner(candidacy["student_id"])

    if candidacy["transition_status"] != "PENDING":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Training may only be recorded against a PENDING officer transition.")

    total = candidacy["training_modules_completed"] + modules
    db.set_fields(candidacy, training_modules_completed=total)
    if office is not None and total >= office["required_training_modules"]:
        db.set_fields(candidacy, transition_status="TRAINING_COMPLETE")
    db.touch(candidacy)
    return response.object_response(serialize.candidacy(candidacy))


@bp.post("/candidacies/<candidacy_id>/activate-officer")
def activate_officer(candidacy_id):
    auth.require(constants.FACULTY_ADVISOR)
    candidacy = lookup.candidacy(candidacy_id)
    election = db.store.elections[candidacy["election_id"]]
    office = db.store.offices.get(candidacy["office_id"])

    # rule 9 — PENDING passes the state gate deliberately; it is refused at
    # rule 30 with ERR_TRAINING_INCOMPLETE so the officer learns the real reason.
    if candidacy["transition_status"] not in ("PENDING", "TRAINING_COMPLETE"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "The officer transition is not open for activation.")
    if election["status"] != "CERTIFIED":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Officers may only be seated once the election is CERTIFIED.")
    # rule 30 — a PENDING officer is told the actual reason, not a generic
    # state error (PRD 3.9), so the training test runs before the term test.
    if office is not None and candidacy["training_modules_completed"] < office["required_training_modules"]:
        errors.fail(errors.ERR_TRAINING_INCOMPLETE,
                    "The officer has not recorded the required training modules.")
    if candidacy["term_start_date"] is None or not db.now() >= candidacy["term_start_date"]:
        errors.fail(errors.ERR_INVALID_STATE,
                    "The logical clock has not reached the candidacy's term_start_date.")

    db.set_fields(candidacy, transition_status="ACTIVE", activated_at=db.now())
    db.touch(candidacy)
    return response.object_response(serialize.candidacy(candidacy))
