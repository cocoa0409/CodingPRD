"""Piggyback authority opinions by state law (PRD 3.5)."""

from flask import Blueprint

import calc
import services
from calc import num
from db import (create_row, db, get_dt, logical_now, ordered, serialize, set_dt)
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, actor_id, actor_role, commit,
                        require_roles, touch)
from response import created_response, object_response
from routes.common import (ANALYSIS_STATUS, DETERMINATION, VOID_REASON, fetch,
                           list_endpoint)
from validation import json_body, read_id, read_int, read_str

bp = Blueprint("piggyback_analyses", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_MEMBER, ROLE_AUDITOR)
DETERMINATION_ACTIONS = ("DETERMINE", "VOID")


@bp.route("/coop/piggyback-analyses", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN, ROLE_MEMBER)
def create_analysis():
    body = json_body(
        allowed=("member_agency_id", "contract_id", "expected_member_agency_version",
                 "waiver_reference"),
        required=("member_agency_id", "contract_id",
                  "expected_member_agency_version"),
    )
    member_id = read_id(body, "member_agency_id", required=True)
    contract_id = read_id(body, "contract_id", required=True)
    expected = read_int(body, "expected_member_agency_version", required=True,
                        minimum=1)
    waiver = read_str(body, "waiver_reference", max_len=120)

    # 5. body foreign keys in entity field order
    member = fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")

    # 7. a member representative may only act for itself
    if actor_role() == ROLE_MEMBER and actor_id() != member_id:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the member_agency_id named in the body")

    # 9. optimistic concurrency on the pinned member version
    if int(expected) != int(member["version"]):
        fail("ERR_STALE_MEMBER_AGENCY_VERSION",
             "expected_member_agency_version %s does not match the member's "
             "current version %s" % (expected, member["version"]))

    # Opening an analysis supersedes any live opinion on the same pair.
    superseded = [
        a for a in services.analyses_of_member(member_id)
        if a["contract_id"] == contract_id and a["status"] in ("PENDING", "DETERMINED")
    ]
    services.void_analyses(superseded, "SUPERSEDED_BY_NEWER_ANALYSIS")

    row = create_row(
        db.analyses,
        member_agency_id=member_id,
        contract_id=contract_id,
        status="PENDING",
        determination=None,
        doctrine_applied=None,
        authority_score=None,
        deduction_detail=[],
        local_waiver_required=False,
        waiver_reference=waiver,
        determined_at=None,
        expires_on=None,
        voided_reason=None,
    )
    set_dt(row, "determined_at", None)
    set_dt(row, "expires_on", None)

    # The pinned parent's version increments on every successful open.
    touch(member)
    commit()
    return created_response(serialize(row))


@bp.route("/coop/piggyback-analyses", methods=["GET"])
@require_roles(*READ_ROLES)
def list_analyses():
    return list_endpoint(
        lambda: ordered(db.analyses),
        {"member_agency_id": ("member_agency_id", None),
         "contract_id": ("contract_id", None),
         "status": ("status", ANALYSIS_STATUS),
         "determination": ("determination", DETERMINATION)},
    )


@bp.route("/coop/piggyback-analyses/<analysis_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_analysis(analysis_id):
    row = fetch(db.analyses, analysis_id, "ERR_ANALYSIS_NOT_FOUND")
    return object_response(serialize(row))


@bp.route("/coop/piggyback-analyses/<analysis_id>/determination", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def determination(analysis_id):
    body = json_body(allowed=("action", "waiver_reference", "void_reason", "note"),
                     required=("action",))
    action = read_str(body, "action", required=True, enum=DETERMINATION_ACTIONS)
    waiver = read_str(body, "waiver_reference", max_len=120)
    void_reason = read_str(body, "void_reason", enum=VOID_REASON)
    read_str(body, "note")

    analysis = fetch(db.analyses, analysis_id, "ERR_ANALYSIS_NOT_FOUND")
    member = db.members[analysis["member_agency_id"]]
    contract = db.contracts[analysis["contract_id"]]

    # 6. determination reads exactly one configuration row
    rule = None
    if action == "DETERMINE":
        rule = services.rule_for_state(member["state_code"])
        if rule is None:
            fail("ERR_STATE_LAW_RULE_NOT_FOUND",
                 "no configuration row for state_code %s" % member["state_code"])

    # 10. the contract must be ACTIVE
    if action == "DETERMINE" and contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "the master contract is not ACTIVE")

    # 18. the member must be ACTIVE
    if action == "DETERMINE" and member["registration_status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "the member agency is not ACTIVE")

    # 19. from-state on the opinion's dimension
    status = analysis["status"]
    expected = {"DETERMINE": ("PENDING",), "VOID": ("PENDING", "DETERMINED")}[action]
    if status not in expected:
        fail("ERR_ANALYSIS_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    if action == "DETERMINE":
        if waiver is not None:
            analysis["waiver_reference"] = waiver
        # 29. a local solicitation waiver where the state requires one
        if rule["requires_local_solicitation_waiver"] and analysis[
                "waiver_reference"] is None:
            fail("ERR_LOCAL_WAIVER_REQUIRED",
                 "state %s requires a local solicitation waiver reference"
                 % member["state_code"])

        solicitation = db.solicitations[contract["solicitation_id"]]
        base_start = get_dt(contract, "base_term_start")
        term_end = get_dt(contract, "current_term_end")
        verdict = calc.piggyback_authority(rule, solicitation, contract, member,
                                           base_start, term_end)
        now = logical_now()
        expiry, _ = calc.analysis_expiry(now, term_end)

        analysis["status"] = "DETERMINED"
        analysis["determination"] = verdict["determination"]
        analysis["doctrine_applied"] = verdict["doctrine_applied"]
        analysis["authority_score"] = num(verdict["authority_score"])
        analysis["deduction_detail"] = verdict["deduction_detail"]
        analysis["local_waiver_required"] = bool(
            rule["requires_local_solicitation_waiver"])
        set_dt(analysis, "determined_at", now)
        set_dt(analysis, "expires_on", expiry)
    else:
        analysis["status"] = "VOIDED"
        analysis["voided_reason"] = void_reason or "ADMIN_VOID"

    touch(analysis)
    commit()
    return object_response(serialize(analysis))
