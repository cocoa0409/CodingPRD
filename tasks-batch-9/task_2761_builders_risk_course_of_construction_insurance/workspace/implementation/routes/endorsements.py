"""ExtensionEndorsement endpoints (PRD 3.6)."""
from flask import Blueprint

import calc
import lookup
import recompute
from db import by_policy, new_row, ordered, store, touch
from enums import DECISIONS_APPROVE_DECLINE, SLIP_REASONS
from errors import ApiError
from middleware import authenticate, body, get_dt, get_enum, get_int, get_str, present
from response import created, ok
from util import add_days

bp = Blueprint("endorsements", __name__)

OPEN_STATUSES = ("REQUESTED", "RETURNED_FOR_INFO")


def _check_revised_date(policy, requested_extension_days, revised_completion_date):
    expected = add_days(policy["adjusted_completion_date"], requested_extension_days)
    if revised_completion_date != expected:
        raise ApiError(
            "ERR_REVISED_DATE_MISMATCH",
            "revised_completion_date must equal adjusted_completion_date plus the requested days.",
        )


def _check_extension_ceiling(policy, requested_extension_days):
    if calc.extension_limit_exceeded(
        policy["cumulative_extension_days"], requested_extension_days, policy["original_term_days"]
    ):
        raise ApiError(
            "ERR_EXTENSION_LIMIT_EXCEEDED",
            "Cumulative extension may not exceed half of the original term.",
        )


@bp.post("/extension-endorsements")
def file_endorsement():
    user_id, _role = authenticate("Underwriter")
    payload = body()
    policy = lookup.fk_policy(payload)
    expected_policy_version = get_int(payload, "expected_policy_version", minimum=0)
    requested_extension_days = get_int(
        payload, "requested_extension_days", minimum=1, maximum=180
    )
    slip_reason = get_enum(payload, "slip_reason", SLIP_REASONS)
    revised_completion_date = get_dt(payload, "revised_completion_date")
    if expected_policy_version != policy["version"]:
        raise ApiError(
            "ERR_STALE_POLICY_VERSION", "expected_policy_version does not match the policy."
        )
    if policy["status"] != "IN_FORCE":
        raise ApiError(
            "ERR_INVALID_POLICY_STATE", "An endorsement may only be filed on an IN_FORCE policy."
        )
    _check_revised_date(policy, requested_extension_days, revised_completion_date)
    _check_extension_ceiling(policy, requested_extension_days)
    project = store.projects[policy["project_id"]]
    slip_factor, additional_premium_cents = calc.price_extension(
        policy, project, requested_extension_days
    )
    row = new_row()
    row.update({
        "policy_id": policy["id"],
        "requested_extension_days": requested_extension_days,
        "slip_reason": slip_reason,
        "revised_completion_date": revised_completion_date,
        "status": "REQUESTED",
        "requested_by_user_id": user_id,
        "decided_by_user_id": None,
        "info_request_note": None,
        "resubmission_count": 0,
        "slip_factor": slip_factor,
        "additional_premium_cents": additional_premium_cents,
    })
    for existing in ordered(by_policy(store.endorsements, policy["id"])):
        if existing["status"] in OPEN_STATUSES:
            existing["status"] = "SUPERSEDED"
            touch(existing)
    store.endorsements[row["id"]] = row
    touch(policy)
    return created(row)


@bp.post("/extension-endorsements/<endorsement_id>/return-for-info")
def return_for_info(endorsement_id):
    user_id, _role = authenticate("UnderwritingManager")
    endorsement = lookup.endorsement(endorsement_id)
    if endorsement["requested_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The filing underwriter may not return its own request."
        )
    payload = body()
    note = get_str(payload, "info_request_note")
    if endorsement["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_ENDORSEMENT_STATE", "Only a REQUESTED endorsement may be returned."
        )
    endorsement["status"] = "RETURNED_FOR_INFO"
    endorsement["info_request_note"] = note
    touch(endorsement)
    return ok(endorsement)


@bp.post("/extension-endorsements/<endorsement_id>/resubmit")
def resubmit_endorsement(endorsement_id):
    authenticate("Underwriter")
    endorsement = lookup.endorsement(endorsement_id)
    payload = body()
    requested_extension_days = get_int(
        payload, "requested_extension_days", minimum=1, maximum=180
    )
    revised_completion_date = get_dt(payload, "revised_completion_date")
    slip_reason = get_enum(payload, "slip_reason", SLIP_REASONS, required=False)
    if endorsement["status"] != "RETURNED_FOR_INFO":
        raise ApiError(
            "ERR_INVALID_ENDORSEMENT_STATE",
            "Only a RETURNED_FOR_INFO endorsement may be resubmitted.",
        )
    if endorsement["resubmission_count"] >= 3:
        raise ApiError(
            "ERR_RESUBMISSION_LIMIT_REACHED", "This endorsement has exhausted its resubmissions."
        )
    policy = store.policies[endorsement["policy_id"]]
    _check_revised_date(policy, requested_extension_days, revised_completion_date)
    _check_extension_ceiling(policy, requested_extension_days)
    project = store.projects[policy["project_id"]]
    slip_factor, additional_premium_cents = calc.price_extension(
        policy, project, requested_extension_days
    )
    endorsement["requested_extension_days"] = requested_extension_days
    endorsement["revised_completion_date"] = revised_completion_date
    if slip_reason is not None:
        endorsement["slip_reason"] = slip_reason
    endorsement["resubmission_count"] += 1
    endorsement["slip_factor"] = slip_factor
    endorsement["additional_premium_cents"] = additional_premium_cents
    endorsement["status"] = "REQUESTED"
    touch(endorsement)
    return ok(endorsement)


@bp.post("/extension-endorsements/<endorsement_id>/decision")
def decide_endorsement(endorsement_id):
    user_id, role = authenticate("Underwriter", "UnderwritingManager")
    endorsement = lookup.endorsement(endorsement_id)
    payload = body()
    # PRD 2.10 / 2.11 step 3: the authority limit precedes every existence and state check
    # on this endpoint, and reads the premium frozen onto the endorsement.
    raw_decision = payload.get("decision")
    stored_ap = endorsement["additional_premium_cents"]
    if role == "Underwriter" and raw_decision == "APPROVE" \
            and stored_ap is not None and stored_ap > calc.SOD_AP_THRESHOLD_CENTS:
        raise ApiError(
            "ERR_MANAGER_APPROVAL_REQUIRED",
            "An Underwriter may not approve an extension above 500000 cents of premium.",
        )
    if endorsement["requested_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The filing underwriter may not decide its own request."
        )
    decision = get_enum(payload, "decision", DECISIONS_APPROVE_DECLINE)
    if endorsement["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_ENDORSEMENT_STATE", "Only a REQUESTED endorsement may be decided."
        )
    policy = store.policies[endorsement["policy_id"]]
    if decision == "DECLINE":
        endorsement["status"] = "DECLINED"
        endorsement["decided_by_user_id"] = user_id
        touch(endorsement)
        return ok(endorsement)
    if policy["status"] != "IN_FORCE":
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "An expired or cancelled policy can neither take on nor give back endorsed days.",
        )
    _check_extension_ceiling(policy, endorsement["requested_extension_days"])
    days = endorsement["requested_extension_days"]
    # Hop one -- the endorsement itself.
    endorsement["status"] = "APPROVED"
    endorsement["decided_by_user_id"] = user_id
    touch(endorsement)
    # Hop two -- the policy's term and completion baseline.
    pre_extension_term_end = policy["term_end_date"]
    policy["cumulative_extension_days"] += days
    policy["term_end_date"] = add_days(policy["term_end_date"], days)
    policy["adjusted_completion_date"] = endorsement["revised_completion_date"]
    # Hop four -- the ledger entry, then written premium.
    txn = recompute.append_txn(
        policy,
        "EXTENSION_AP",
        endorsement["additional_premium_cents"],
        pre_extension_term_end,
        "extension approval",
    )
    txn["_endorsement_id"] = endorsement["id"]
    touch(policy)
    # Hop three -- the project's audit risk score.
    project = store.projects[policy["project_id"]]
    recompute.recompute_audit_risk_score(project)
    touch(project)
    return ok(endorsement)


@bp.post("/extension-endorsements/<endorsement_id>/rescind")
def rescind_endorsement(endorsement_id):
    authenticate("UnderwritingManager")
    endorsement = lookup.endorsement(endorsement_id)
    if endorsement["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_ENDORSEMENT_STATE", "Only an APPROVED endorsement may be rescinded."
        )
    policy = store.policies[endorsement["policy_id"]]
    if policy["status"] != "IN_FORCE" or store.now() >= policy["term_end_date"]:
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "Rescission requires an IN_FORCE policy still inside its term.",
        )
    days = endorsement["requested_extension_days"]
    endorsement["status"] = "RESCINDED"
    touch(endorsement)
    recompute.append_txn(
        policy,
        "EXTENSION_AP_REVERSAL",
        -endorsement["additional_premium_cents"],
        store.now(),
        "extension rescission",
        reverses_sequence_no=recompute.extension_ap_sequence_no(
            policy["id"], endorsement["id"]
        ),
    )
    policy["cumulative_extension_days"] -= days
    policy["term_end_date"] = add_days(policy["term_end_date"], -days)
    policy["adjusted_completion_date"] = add_days(policy["adjusted_completion_date"], -days)
    touch(policy)
    project = store.projects[policy["project_id"]]
    recompute.recompute_audit_risk_score(project)
    touch(project)
    return ok(endorsement)


@bp.get("/extension-endorsements/<endorsement_id>")
def read_endorsement(endorsement_id):
    authenticate("Underwriter", "UnderwritingManager")
    return ok(lookup.endorsement(endorsement_id))
