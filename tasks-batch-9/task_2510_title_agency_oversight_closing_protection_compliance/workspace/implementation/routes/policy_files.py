"""Policy files: referral routing, authority limits, issuance timeliness and
the transfer dimension (PRD 3.4, 3.9)."""

from flask import Blueprint

import calc
import db
import derive
import lookup
import middleware as mw
import response
import shape
import tx
from db import store
from errors import ApiError
from routes.cpl import require_active_appointment, require_eo_coverage, require_expected_version

bp = Blueprint("policy_files", __name__)

ISSUANCE_STATUSES = (
    "PENDING_REFERRAL",
    "PENDING",
    "ISSUED",
    "LATE_ISSUED",
    "ISSUANCE_DECLINED",
    "VOIDED",
)
ISSUANCE_TRANSITIONS = {
    "PENDING_REFERRAL": ("PENDING", "ISSUANCE_DECLINED"),
    "PENDING": ("ISSUED",),
}
ISSUANCE_TERMINALS = ("ISSUANCE_DECLINED", "VOIDED")
ISSUANCE_ROLE = {
    "PENDING_REFERRAL": (mw.UNDERWRITING_COUNSEL,),
    "PENDING": (mw.AGENCY_PRINCIPAL,),
}

TRANSFER_STATUSES = (
    "NOT_REQUIRED",
    "PENDING_TRANSFER",
    "TRANSFERRED",
    "TRANSFER_EXCEPTION",
)
TRANSFER_TRANSITIONS = {
    "PENDING_TRANSFER": ("TRANSFERRED", "TRANSFER_EXCEPTION"),
    "TRANSFER_EXCEPTION": ("TRANSFERRED",),
}
TRANSFER_TERMINALS = ("TRANSFERRED",)

ISSUED_STATUSES = ("ISSUED", "LATE_ISSUED")


@bp.post("/policy-files")
def create_policy_file():
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    agency_id = shape.req_id(payload, "agency_id")
    program_id = shape.req_id(payload, "state_program_id")
    cpl_id = shape.opt_id(payload, "cpl_id")
    order_number = shape.req_str(payload, "order_number")
    closing_date = shape.req_date(payload, "closing_date")
    liability = shape.req_positive_cents(payload, "liability_amount_cents")
    gross_premium = shape.req_positive_cents(payload, "gross_premium_cents")
    complex_flag = shape.opt_bool(payload, "complex_title_flag", False)
    expected_version = shape.req_int(payload, "expected_agency_version")

    # Tier 5 - agency_id, state_program_id, cpl_id
    agency = lookup.agency(agency_id)
    program = lookup.state_program(program_id)
    if cpl_id is not None:
        lookup.letter(cpl_id)
    # Tier 6
    mw.require_ownership(user_id, role, agency["id"])
    # Tier 9
    require_expected_version(agency, expected_version)
    # Tier 12
    require_active_appointment(agency["id"], program["id"])

    referral = calc.policy_referral_required(
        complex_flag,
        liability,
        agency["underwriting_authority_limit_cents"],
        program["counsel_referral_threshold_cents"],
    )
    policy_file = db.new_row(
        db.POLICY_FILE,
        {
            "agency_id": agency["id"],
            "state_program_id": program["id"],
            "cpl_id": cpl_id,
            "order_number": order_number,
            "closing_date": db.date_str(closing_date),
            "liability_amount_cents": liability,
            "gross_premium_cents": gross_premium,
            "complex_title_flag": complex_flag,
            "issuance_status": "PENDING_REFERRAL" if referral else "PENDING",
            "remittance_status": "UNREPORTED",
            "transfer_status": "NOT_REQUIRED",
            "approved_liability_cents": 0 if referral else liability,
            "policy_number": None,
            "issued_at": None,
            "issuance_elapsed_days": None,
            "referral_decided_by_user_id": None,
            "transferee_agency_id": None,
        },
    )
    derive.recompute_agency(agency)
    tx.force_agency_version_bump(agency)
    return response.created(policy_file)


@bp.get("/policy-files/<policy_file_id>")
def read_policy_file(policy_file_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.policy_file(policy_file_id))


@bp.get("/policy-files")
def list_policy_files():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "agency_id": shape.query_value("agency_id"),
        "state_program_id": shape.query_value("state_program_id"),
        "cpl_id": shape.query_value("cpl_id"),
        "transferee_agency_id": shape.query_value("transferee_agency_id"),
        "issuance_status": shape.query_value("issuance_status"),
        "remittance_status": shape.query_value("remittance_status"),
        "transfer_status": shape.query_value("transfer_status"),
    }
    date_from = shape.query_date("closing_date_from")
    date_to = shape.query_date("closing_date_to")

    rows = []
    for row in store.all(db.POLICY_FILE):
        if not all(v is None or row.get(k) == v for k, v in filters.items()):
            continue
        closing = db.parse_date(row["closing_date"])
        if date_from is not None and (closing is None or closing < date_from):
            continue
        if date_to is not None and (closing is None or closing > date_to):
            continue
        rows.append(row)
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/policy-files/<policy_file_id>/issuance-state")
def issuance_state(policy_file_id):
    user_id, role = mw.require_roles(mw.UNDERWRITING_COUNSEL, mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    to_state = shape.req_enum(payload, "to_state", ISSUANCE_STATUSES)
    shape.opt_str(payload, "rationale")

    approved_liability = None
    if to_state == "PENDING":
        approved_liability = shape.req_positive_cents(payload, "approved_liability_cents")
    policy_number = None
    if to_state == "ISSUED":
        policy_number = shape.req_str(payload, "policy_number")

    policy_file = lookup.policy_file(policy_file_id)
    agency = lookup.agency(policy_file["agency_id"])
    program = store.get(db.STATE_PROGRAM, policy_file["state_program_id"])

    # Tier 6
    mw.require_ownership(user_id, role, agency["id"])
    # Tier 7
    mw.require_transition_role(role, ISSUANCE_ROLE.get(policy_file["issuance_status"]))
    # Tier 10
    lookup.guard_transition(
        policy_file["issuance_status"], to_state, ISSUANCE_TRANSITIONS, ISSUANCE_TERMINALS
    )

    if to_state == "PENDING":
        # Tier 14 - the referral approval ceiling
        if approved_liability > policy_file["liability_amount_cents"]:
            raise ApiError("ERR_APPROVED_LIABILITY_ABOVE_REQUEST")
        policy_file["issuance_status"] = "PENDING"
        policy_file["approved_liability_cents"] = approved_liability
        policy_file["referral_decided_by_user_id"] = user_id
        return response.ok(policy_file)

    if to_state == "ISSUANCE_DECLINED":
        policy_file["issuance_status"] = "ISSUANCE_DECLINED"
        policy_file["referral_decided_by_user_id"] = user_id
        return response.ok(policy_file)

    # to_state == ISSUED
    # Tier 10
    if agency["oversight_posture"] == "FROZEN":
        raise ApiError("ERR_AGENCY_POSTURE_FROZEN")
    # Tier 11 - P2: the coverage error outranks the appointment error.
    require_eo_coverage(agency)
    # Tier 12
    require_active_appointment(agency["id"], policy_file["state_program_id"])
    if policy_file["cpl_id"] is not None:
        letter = store.get(db.CPL, policy_file["cpl_id"])
        if letter is None or letter["status"] != "ISSUED":
            raise ApiError("ERR_CPL_NOT_ISSUED")
    # Tier 13 - the number is only reserved by an in-force file of this agency
    for other in store.where(db.POLICY_FILE, agency_id=agency["id"]):
        if other["id"] == policy_file["id"]:
            continue
        if (
            other["issuance_status"] in ISSUED_STATUSES
            and other["policy_number"] == policy_number
        ):
            raise ApiError("ERR_DUPLICATE_POLICY_NUMBER")
    # Tier 14 - a counsel referral decision lifts the authority limit
    if (
        policy_file["approved_liability_cents"]
        > agency["underwriting_authority_limit_cents"]
        and policy_file["referral_decided_by_user_id"] is None
    ):
        raise ApiError("ERR_UNDERWRITING_AUTHORITY_EXCEEDED")

    elapsed = db.days_between(db.parse_date(policy_file["closing_date"]), db.clock_date())
    policy_file["issuance_elapsed_days"] = elapsed
    policy_file["issuance_status"] = calc.issuance_landing(
        elapsed, program["policy_issuance_deadline_days"]
    )
    policy_file["policy_number"] = policy_number
    policy_file["issued_at"] = db.clock_instant()
    previous = derive.recompute_agency(agency)
    derive.apply_freeze_to_accounts(agency, previous)
    tx.force_agency_version_bump(agency)
    return response.ok(policy_file)


@bp.post("/policy-files/<policy_file_id>/transfer-state")
def transfer_state(policy_file_id):
    mw.require_roles(mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    to_state = shape.req_enum(payload, "to_state", TRANSFER_STATUSES)
    shape.opt_str(payload, "note")

    policy_file = lookup.policy_file(policy_file_id)
    agency = lookup.agency(policy_file["agency_id"])

    # Tier 10
    lookup.guard_transition(
        policy_file["transfer_status"], to_state, TRANSFER_TRANSITIONS, TRANSFER_TERMINALS
    )

    if to_state == "TRANSFERRED":
        # Tier 12 - eligibility is re-tested at the moment of transfer
        transferee_id = policy_file["transferee_agency_id"]
        transferee = store.get(db.AGENCY, transferee_id) if transferee_id else None
        if (
            transferee is None
            or transferee["appointment_status"] != "APPOINTED"
            or transferee["oversight_posture"] == "FROZEN"
        ):
            raise ApiError("ERR_TRANSFEREE_NOT_ELIGIBLE")
        policy_file["transfer_status"] = "TRANSFERRED"
    else:
        policy_file["transfer_status"] = "TRANSFER_EXCEPTION"

    derive.recompute_agency(agency)
    return response.ok(policy_file)


@bp.get("/policy-files/<policy_file_id>/remittance-lines")
def list_policy_lines(policy_file_id):
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    policy_file = lookup.policy_file(policy_file_id)
    rows = store.where(db.LINE, policy_file_id=policy_file["id"])
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))
