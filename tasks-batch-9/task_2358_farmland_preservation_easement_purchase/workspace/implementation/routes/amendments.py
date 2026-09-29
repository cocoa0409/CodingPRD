"""Amendment endpoints (PRD 3.9)."""

from flask import Blueprint

from db import db, touch
from errors import ApiError
from middleware import authenticate
from response import ok
from services import cascade, lookup, serialize
from validation import Payload, raw_body

bp = Blueprint("amendments", __name__)


def _compliance_gate(easement, program):
    """PRD 2.11 rung 11 -- the stewardship-hold and compliance-posture gate."""
    if easement["stewardship_hold"]:
        raise ApiError(
            "ERR_EASEMENT_NOT_COMPLIANT",
            "an easement under a stewardship hold accepts no amendment work",
        )
    admissible = ("COMPLIANT",)
    if program["amendment_policy"] == "CONDITIONAL":
        admissible = ("COMPLIANT", "VIOLATION_CURED")
    if easement["compliance_status"] not in admissible:
        raise ApiError(
            "ERR_EASEMENT_NOT_COMPLIANT",
            "the easement's compliance posture is not admissible under the "
            "program's amendment policy",
        )


@bp.get("/amendments/<amendment_id>")
def read_amendment(amendment_id):
    authenticate(("ProgramAdmin", "StewardshipMonitor", "Landowner"))
    return ok(serialize.amendment(lookup.get_amendment(amendment_id)))


@bp.post("/amendments/<amendment_id>/submission")
def submit_amendment(amendment_id):
    authenticate(("ProgramAdmin",))
    amendment = lookup.get_amendment(amendment_id)
    Payload(raw_body(), ())

    if amendment["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE", "only a DRAFT amendment can be submitted"
        )

    easement = db.easements[amendment["easement_id"]]
    _compliance_gate(easement, lookup.program_of_easement(easement))

    amendment["status"] = "UNDER_REVIEW"
    touch(amendment)
    touch(easement)
    return ok(serialize.amendment(amendment))


@bp.post("/amendments/<amendment_id>/decision")
def decide_amendment(amendment_id):
    authenticate(("ProgramAdmin",))
    amendment = lookup.get_amendment(amendment_id)
    payload = Payload(raw_body(), ("decision", "reason"))
    decision = payload.enum("decision", ("APPROVE", "REJECT"))
    reason = payload.string("reason", required=False, default=None, min_len=1, max_len=500)
    if decision == "REJECT" and reason is None:
        raise ApiError("ERR_INVALID_REQUEST", "reason is mandatory on rejection")

    if amendment["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE",
            "only an amendment UNDER_REVIEW can be decided",
        )

    easement = db.easements[amendment["easement_id"]]
    if easement["stewardship_hold"]:
        raise ApiError(
            "ERR_EASEMENT_NOT_COMPLIANT",
            "an easement under a stewardship hold accepts no amendment decision",
        )

    if decision == "APPROVE":
        if int(amendment["net_conservation_benefit_cents"]) <= 0:
            raise ApiError(
                "ERR_NO_NET_CONSERVATION_BENEFIT",
                "an amendment with no net conservation benefit cannot be approved",
            )
        amendment["status"] = "APPROVED"
        easement["status"] = "AMENDED"
        if amendment["amendment_type"] == "IMPERVIOUS_INCREASE":
            easement["impervious_allowance_sqft"] = int(
                amendment["requested_impervious_sqft"]
            )
            amendment["applied_impervious_sqft"] = int(
                amendment["requested_impervious_sqft"]
            )
        elif amendment["amendment_type"] == "RESIDENTIAL_RIGHT_RELOCATION":
            delta = int(amendment["residential_rights_delta"])
            easement["residential_rights_retained"] = (
                int(easement["residential_rights_retained"]) + delta
            )
            amendment["applied_rights_delta"] = delta
    else:
        amendment["status"] = "REJECTED"
        amendment["decision_reason"] = reason

    touch(amendment)
    touch(easement)
    return ok(serialize.amendment(amendment))


@bp.post("/amendments/<amendment_id>/reinstatement")
def reinstate_amendment(amendment_id):
    authenticate(("ProgramAdmin",))
    amendment = lookup.get_amendment(amendment_id)
    Payload(raw_body(), ())

    if amendment["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE",
            "only a SUSPENDED amendment can be reinstated",
        )

    easement = db.easements[amendment["easement_id"]]
    _compliance_gate(easement, lookup.program_of_easement(easement))

    amendment["status"] = "UNDER_REVIEW"
    amendment["suspended_reason"] = None
    touch(amendment)
    touch(easement)
    return ok(serialize.amendment(amendment))


@bp.post("/amendments/<amendment_id>/rescission")
def rescind_amendment(amendment_id):
    authenticate(("ProgramAdmin",))
    amendment = lookup.get_amendment(amendment_id)
    payload = Payload(raw_body(), ("reason",))
    reason = payload.string("reason", min_len=1, max_len=500)

    if amendment["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE",
            "only an APPROVED amendment can be rescinded",
        )

    easement = db.easements[amendment["easement_id"]]
    program = lookup.program_of_easement(easement)

    amendment["status"] = "RESCINDED"
    amendment["rescission_reason"] = reason
    if amendment["applied_impervious_sqft"] is not None:
        cascade.restore_impervious_allowance(easement, program)
    delta = int(amendment["applied_rights_delta"] or 0)
    if delta != 0:
        easement["residential_rights_retained"] = (
            int(easement["residential_rights_retained"]) - delta
        )
    amendment["applied_rights_delta"] = 0
    amendment["applied_impervious_sqft"] = None
    touch(amendment)

    if lookup.easement_amendment_count(easement["id"]) == 0 and easement["status"] == "AMENDED":
        easement["status"] = "RECORDED"
    touch(easement)
    return ok(serialize.amendment(amendment))
