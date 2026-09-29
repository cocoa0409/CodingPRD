"""Closing protection letters: routing, coverage caps, issuance and void (PRD 3.3)."""

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

bp = Blueprint("cpl", __name__)

CPL_SCOPES = ("FULL_SETTLEMENT", "LENDER_ONLY", "SELLER_PROCEEDS")
CPL_STATUSES = ("REQUESTED", "REFERRED", "ISSUED", "DECLINED", "VOIDED")
CPL_TRANSITIONS = {
    "REQUESTED": ("ISSUED", "DECLINED"),
    "REFERRED": ("ISSUED", "DECLINED"),
    "ISSUED": ("VOIDED",),
}
CPL_TERMINALS = ("DECLINED", "VOIDED")

DECIDING_ROLE = {
    "REQUESTED": (mw.COMPLIANCE_OFFICER,),
    "REFERRED": (mw.UNDERWRITING_COUNSEL,),
    "ISSUED": (mw.COMPLIANCE_OFFICER,),
}


def eo_coverage_live(agency):
    expires = db.parse_date(agency["eo_expires_on"])
    return expires is not None and expires >= db.clock_date()


def require_eo_coverage(agency):
    if not eo_coverage_live(agency):
        raise ApiError("ERR_EO_COVERAGE_LAPSED")


def require_active_appointment(agency_id, state_program_id):
    if derive.active_appointment(agency_id, state_program_id) is None:
        raise ApiError("ERR_NO_ACTIVE_APPOINTMENT_IN_STATE")


def require_expected_version(agency, expected):
    if agency["version"] != expected:
        raise ApiError("ERR_STALE_AGENCY_VERSION")


@bp.post("/closing-protection-letters")
def request_letter():
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    agency_id = shape.req_id(payload, "agency_id")
    program_id = shape.req_id(payload, "state_program_id")
    transaction_ref = shape.req_str(payload, "transaction_ref")
    coverage_scope = shape.req_enum(payload, "coverage_scope", CPL_SCOPES)
    requested = shape.req_positive_cents(payload, "requested_coverage_cents")
    closing_date = shape.req_date(payload, "closing_date")
    lender_name = shape.req_str(payload, "lender_name")
    complex_flag = shape.opt_bool(payload, "complex_title_flag", False)
    expected_version = shape.req_int(payload, "expected_agency_version")

    # Tier 5
    agency = lookup.agency(agency_id)
    program = lookup.state_program(program_id)
    # Tier 6
    mw.require_ownership(user_id, role, agency["id"])
    # Tier 9
    require_expected_version(agency, expected_version)
    # Tier 10
    if agency["oversight_posture"] == "FROZEN":
        raise ApiError("ERR_AGENCY_POSTURE_FROZEN")
    # Tier 11
    require_eo_coverage(agency)
    # Tier 12
    require_active_appointment(agency["id"], program["id"])
    if not program["cpl_permitted"]:
        raise ApiError("ERR_CPL_NOT_PERMITTED_IN_STATE")
    if coverage_scope not in program["cpl_scope_allowed"]:
        raise ApiError("ERR_CPL_SCOPE_NOT_ALLOWED")
    # Tier 14
    if requested > program["cpl_coverage_cap_cents"]:
        raise ApiError("ERR_CPL_COVERAGE_CAP_EXCEEDED")

    reason = calc.cpl_referral_reason(
        complex_flag,
        requested,
        program["counsel_referral_threshold_cents"],
        agency["underwriting_authority_limit_cents"],
        agency["oversight_posture"],
    )
    letter = db.new_row(
        db.CPL,
        {
            "agency_id": agency["id"],
            "state_program_id": program["id"],
            "transaction_ref": transaction_ref,
            "coverage_scope": coverage_scope,
            "requested_coverage_cents": requested,
            "closing_date": db.date_str(closing_date),
            "lender_name": lender_name,
            "complex_title_flag": complex_flag,
            "status": "REFERRED" if reason is not None else "REQUESTED",
            "referral_reason": reason,
            "approved_coverage_cents": 0,
            "decided_by_user_id": None,
            "issued_at": None,
            "void_reason": None,
        },
    )
    derive.recompute_agency(agency)
    tx.force_agency_version_bump(agency)
    return response.created(letter)


@bp.get("/closing-protection-letters/<letter_id>")
def read_letter(letter_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.letter(letter_id))


@bp.get("/closing-protection-letters")
def list_letters():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "agency_id": shape.query_value("agency_id"),
        "state_program_id": shape.query_value("state_program_id"),
        "status": shape.query_value("status"),
    }
    complex_flag = shape.query_bool("complex_title_flag")
    rows = []
    for row in store.all(db.CPL):
        if not all(v is None or row.get(k) == v for k, v in filters.items()):
            continue
        if complex_flag is not None and row["complex_title_flag"] != complex_flag:
            continue
        rows.append(row)
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/closing-protection-letters/<letter_id>/state")
def letter_state(letter_id):
    user_id, role = mw.require_roles(mw.COMPLIANCE_OFFICER, mw.UNDERWRITING_COUNSEL)
    payload = shape.body()
    to_state = shape.req_enum(payload, "to_state", CPL_STATUSES)
    shape.opt_str(payload, "rationale")
    void_reason = shape.opt_str(payload, "void_reason")

    letter = lookup.letter(letter_id)
    agency = lookup.agency(letter["agency_id"])
    program = store.get(db.STATE_PROGRAM, letter["state_program_id"])

    # Tier 7 - the branch the letter sits in decides who may decide it.
    mw.require_transition_role(role, DECIDING_ROLE.get(letter["status"]))

    # Tier 10
    lookup.guard_transition(letter["status"], to_state, CPL_TRANSITIONS, CPL_TERMINALS)

    if to_state == "ISSUED":
        if agency["oversight_posture"] == "FROZEN":
            raise ApiError("ERR_AGENCY_POSTURE_FROZEN")
        # Tier 11
        require_eo_coverage(agency)
        # Tier 12
        require_active_appointment(agency["id"], letter["state_program_id"])
        if not program["cpl_permitted"]:
            raise ApiError("ERR_CPL_NOT_PERMITTED_IN_STATE")

        letter["approved_coverage_cents"] = calc.cpl_approved_coverage(
            letter["requested_coverage_cents"],
            letter["coverage_scope"],
            program["cpl_coverage_cap_cents"],
            agency["oversight_posture"],
            agency["eo_policy_limit_cents"],
        )
        letter["status"] = "ISSUED"
        letter["issued_at"] = db.clock_instant()
        letter["decided_by_user_id"] = user_id
        derive.recompute_agency(agency)
        tx.force_agency_version_bump(agency)

    elif to_state == "DECLINED":
        letter["status"] = "DECLINED"
        letter["decided_by_user_id"] = user_id
        # approved_coverage_cents remains 0 and the exposure ledger is unchanged.
        derive.recompute_agency(agency)

    else:  # VOIDED
        for pf in store.all(db.POLICY_FILE):
            if pf["cpl_id"] == letter["id"] and pf["issuance_status"] in (
                "ISSUED",
                "LATE_ISSUED",
            ):
                raise ApiError("ERR_CPL_HAS_ISSUED_POLICY")
        letter["status"] = "VOIDED"
        if void_reason is not None:
            letter["void_reason"] = void_reason
        letter["approved_coverage_cents"] = 0
        derive.recompute_agency(agency)
        tx.force_agency_version_bump(agency)

    return response.ok(letter)
