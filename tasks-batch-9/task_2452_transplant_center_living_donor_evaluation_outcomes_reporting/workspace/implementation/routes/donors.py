"""Donor referral, advocate assignment, informed consent and advocacy determination."""

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, now, touch
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from response import list_response, object_response
from routes.programs import find_program, find_staff
from routes.recipients import find_recipient
from validation import get_body, opt_str, pagination, q_enum, q_str, req_enum, req_int, req_str

bp = Blueprint("donors", __name__)

DONOR_TERMINAL_STATUSES = ("EXCLUDED", "ADVOCATE_BLOCKED", "DONATED")
DISCLOSURE_BLOCKED_STATUSES = ("EXCLUDED", "ADVOCATE_BLOCKED", "CHAIN_COMMITTED", "DONATED")
REDISCLOSURE_ALLOWED_STATUSES = ("APPROVED", "CONDITIONAL_APPROVED", "EVAL_IN_PROGRESS")


def find_donor(donor_id):
    donor = db.donors.get(donor_id)
    if donor is None:
        raise ApiError("ERR_DONOR_NOT_FOUND", "no DonorCandidate with id %s" % donor_id)
    return donor


@bp.post("/donor-candidates")
def create_donor():
    authenticate(["TransplantCoordinator"])
    body = get_body()
    program_id = req_str(body, "program_id")
    intended_recipient_id = opt_str(body, "intended_recipient_id")
    mrn = req_str(body, "mrn")
    abo = req_enum(body, "abo_blood_type", calc.ABO_TYPES)
    age_years = req_int(body, "age_years", minimum=0)

    program = find_program(program_id)
    recipient = None
    if intended_recipient_id is not None:
        recipient = find_recipient(intended_recipient_id)

    # priority 13 -- posture gate
    if program["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN", "the program is FROZEN and may not refer donors")

    # priority 15 -- single-program containment
    domain.require_same_program(
        [
            program["id"],
            recipient["program_id"] if recipient is not None else None,
            g.staff["program_id"] if g.staff is not None else None,
        ]
    )

    row = new_entity(
        "DonorCandidate",
        {
            "program_id": program["id"],
            "intended_recipient_id": recipient["id"] if recipient is not None else None,
            "referred_by_staff_id": g.user_id,
            "advocate_staff_id": None,
            "mrn": mrn,
            "abo_blood_type": abo,
            "age_years": age_years,
            "advocacy_status": "UNASSIGNED",
            "disclosure_at": None,
            "disclosure_sequence": 0,
            "cooling_off_ends_at": None,
            "attestation_at": None,
            "objection_reason_code": None,
            "medical_status": "PENDING",
            "psychosocial_status": "PENDING",
            "medical_risk_points": 0,
            "psychosocial_risk_points": 0,
            "deferral_count": 0,
            "final_risk_index": None,
            "overall_status": "REFERRED",
            "donated_at": None,
        },
    )
    db.donors[row["id"]] = row
    return object_response(serialize.donor_candidate(row), 201)


@bp.get("/donor-candidates")
def list_donors():
    authenticate(ALL_ROLES)
    program_id = q_str("program_id")
    intended_recipient_id = q_str("intended_recipient_id")
    referred_by = q_str("referred_by_staff_id")
    advocate = q_str("advocate_staff_id")
    overall_status = q_enum("overall_status", calc.OVERALL_STATUSES)
    limit, offset = pagination()

    rows = list(db.donors.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if intended_recipient_id is not None:
        rows = [r for r in rows if r["intended_recipient_id"] == intended_recipient_id]
    if referred_by is not None:
        rows = [r for r in rows if r["referred_by_staff_id"] == referred_by]
    if advocate is not None:
        rows = [r for r in rows if r["advocate_staff_id"] == advocate]
    if overall_status is not None:
        rows = [r for r in rows if r["overall_status"] == overall_status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.donor_candidate(r) for r in page], limit, offset, total)


@bp.get("/donor-candidates/<donor_id>")
def get_donor(donor_id):
    authenticate(ALL_ROLES)
    donor = find_donor(donor_id)
    return object_response(serialize.donor_candidate(donor))


@bp.get("/donor-candidates/<donor_id>/donor-follow-ups")
def list_donor_follow_ups(donor_id):
    authenticate(ALL_ROLES)
    donor = find_donor(donor_id)
    interval_code = q_enum("interval_code", calc.FOLLOW_UP_INTERVALS)
    status = q_enum("status", calc.FOLLOW_UP_STATUSES)
    limit, offset = pagination()

    rows = domain.follow_ups_of_donor(donor)
    if interval_code is not None:
        rows = [r for r in rows if r["interval_code"] == interval_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.donor_follow_up(r) for r in page], limit, offset, total)


@bp.get("/donor-candidates/<donor_id>/donor-cost-claims")
def list_donor_claims(donor_id):
    authenticate(ALL_ROLES)
    donor = find_donor(donor_id)
    claim_type = q_enum("claim_type", calc.CLAIM_TYPES)
    status = q_enum("status", calc.CLAIM_STATUSES)
    limit, offset = pagination()

    rows = domain.claims_of_donor(donor)
    if claim_type is not None:
        rows = [r for r in rows if r["claim_type"] == claim_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.donor_cost_claim(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# advocate assignment
# --------------------------------------------------------------------------- #


@bp.post("/donor-candidates/<donor_id>/advocate-assignment")
def assign_advocate(donor_id):
    authenticate(["ProgramAdmin"])
    donor = find_donor(donor_id)

    body = get_body()
    advocate_staff_id = req_str(body, "advocate_staff_id")
    advocate = find_staff(advocate_staff_id)

    # priority 8 -- the advocacy dimension only offers UNASSIGNED -> ASSIGNED
    if donor["overall_status"] in DONOR_TERMINAL_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a donor in %s accepts no advocate assignment" % donor["overall_status"],
        )
    if donor["advocacy_status"] != "UNASSIGNED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "advocacy_status %s may not move to ASSIGNED" % donor["advocacy_status"],
        )

    # priority 10 -- role-type fitness
    if advocate["staff_role"] != "LIVING_DONOR_ADVOCATE" or not advocate["is_active"]:
        raise ApiError(
            "ERR_STAFF_ROLE_INVALID",
            "the advocate must be an active LIVING_DONOR_ADVOCATE",
        )

    # priority 11 -- segregation of duties
    if donor["intended_recipient_id"] is not None:
        for other in db.donors.values():
            if other["id"] == donor["id"]:
                continue
            if (
                other["intended_recipient_id"] == donor["intended_recipient_id"]
                and other["advocate_staff_id"] == advocate["id"]
            ):
                raise ApiError(
                    "ERR_ADVOCATE_CONFLICT_OF_INTEREST",
                    "this advocate already represents another donor for the same recipient",
                )

    # priority 15 -- single-program containment
    domain.require_same_program([donor["program_id"], advocate["program_id"]])

    donor["advocate_staff_id"] = advocate["id"]
    donor["advocacy_status"] = "ASSIGNED"
    touch(donor)
    domain.refresh_donor_status(donor)
    return object_response(serialize.donor_candidate(donor))


# --------------------------------------------------------------------------- #
# informed consent disclosure
# --------------------------------------------------------------------------- #


@bp.post("/donor-candidates/<donor_id>/consent-disclosure")
def consent_disclosure(donor_id):
    authenticate(["DonorAdvocate"])
    donor = find_donor(donor_id)
    get_body()

    # priority 7 -- resource-scoped actor binding
    if donor["advocate_staff_id"] != g.user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_ADVOCATE", "the caller is not this donor's assigned advocate"
        )

    # priority 8 -- ASSIGNED -> DISCLOSED and ATTESTED -> DISCLOSED only
    advocacy = donor["advocacy_status"]
    if advocacy == "ASSIGNED":
        if donor["overall_status"] in DISCLOSURE_BLOCKED_STATUSES:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "a donor in %s may not be disclosed to" % donor["overall_status"],
            )
    elif advocacy == "ATTESTED":
        if donor["overall_status"] not in REDISCLOSURE_ALLOWED_STATUSES:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "a donor in %s may not be re-disclosed to" % donor["overall_status"],
            )
    else:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "advocacy_status %s may not move to DISCLOSED" % advocacy,
        )

    program = domain.program_of_donor(donor)
    donor["disclosure_sequence"] = donor["disclosure_sequence"] + 1
    donor["disclosure_at"] = now()
    donor["cooling_off_ends_at"] = calc.cooling_off_ends_at(program, donor, donor["disclosure_at"])
    donor["advocacy_status"] = "DISCLOSED"
    if advocacy == "ATTESTED":
        donor["attestation_at"] = None
        donor["final_risk_index"] = None
    touch(donor)
    domain.refresh_donor_status(donor)
    return object_response(serialize.donor_candidate(donor))


# --------------------------------------------------------------------------- #
# advocacy determination
# --------------------------------------------------------------------------- #


@bp.post("/donor-candidates/<donor_id>/advocacy-determination")
def advocacy_determination(donor_id):
    authenticate(["DonorAdvocate"])
    donor = find_donor(donor_id)

    body = get_body()
    outcome = req_enum(body, "outcome", calc.ADVOCACY_OUTCOMES)
    objection_reason_code = opt_str(body, "objection_reason_code")
    if outcome == "OBJECTED" and objection_reason_code is None:
        raise ApiError("ERR_VALIDATION", "objection_reason_code is required for an objection")

    # priority 7
    if donor["advocate_staff_id"] != g.user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_ADVOCATE", "the caller is not this donor's assigned advocate"
        )

    # priority 8
    advocacy = donor["advocacy_status"]
    if outcome == "ATTESTED" and advocacy != "DISCLOSED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "advocacy_status %s may not move to ATTESTED" % advocacy,
        )
    if outcome == "OBJECTED" and advocacy not in ("DISCLOSED", "ATTESTED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "advocacy_status %s may not move to OBJECTED" % advocacy,
        )

    if outcome == "ATTESTED":
        # priority 12 -- informed-consent safety, cooling-off first
        if donor["cooling_off_ends_at"] is None or now() < donor["cooling_off_ends_at"]:
            raise ApiError(
                "ERR_COOLING_OFF_NOT_ELAPSED", "the cooling-off window has not elapsed"
            )
        if donor["medical_status"] != "CLEARED" or donor["psychosocial_status"] != "CLEARED":
            raise ApiError(
                "ERR_CLEARANCE_INCOMPLETE",
                "both clinical dimensions must be CLEARED before attestation",
            )

        donor["advocacy_status"] = "ATTESTED"
        donor["attestation_at"] = now()
        donor["final_risk_index"] = calc.final_risk_index(
            donor["medical_risk_points"],
            donor["psychosocial_risk_points"],
            donor["deferral_count"],
            donor["intended_recipient_id"] is None,
        )
        touch(donor)
        domain.refresh_donor_status(donor)
        return object_response(serialize.donor_candidate(donor))

    donor["advocacy_status"] = "OBJECTED"
    donor["objection_reason_code"] = objection_reason_code
    touch(donor)
    domain.refresh_donor_status(donor)
    domain.cascade_participant_withdrawal(
        domain.segments_of_donor(donor), "ADVOCATE_OBJECTION"
    )
    return object_response(serialize.donor_candidate(donor))
