"""The written policy lifecycle (Cascade B) and notice packets."""

from flask import Blueprint

import constants as K
import serialize
from authz import actor, require_role, require_role_for_target
from common import respond, respond_list
from errors import fail
from ops import cascade_b
from store import add_days, db, new_record, ordered, touch
from validate import (
    body,
    find_jurisdiction,
    find_notice,
    find_policy,
    find_program,
    opt_datetime,
    query_enum,
    query_str,
    req_bool,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    req_str_array,
)

bp = Blueprint("policies", __name__)

POLICY_READ_ROLES = ("SystemOperator", "PrivacyOfficer", "ComplianceApprover", "HRAdministrator")

POLICY_GRANTS = {
    "IN_REVIEW": ("PrivacyOfficer",),
    "RETIRED": ("PrivacyOfficer",),
    "DRAFT": ("ComplianceApprover",),
    "PUBLISHED": (),
    "SUPERSEDED": (),
}


# --- BiometricPolicy --------------------------------------------------------

@bp.post("/policies")
def create_policy():
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    data = body()
    program_id = req_str(data, "program_id")
    version_label = req_str(data, "version_label")
    retention_days = req_int(data, "retention_days", minimum=1)
    destruction_trigger = req_enum(data, "destruction_trigger", K.DESTRUCTION_TRIGGERS)
    release_language_included = req_bool(data, "release_language_included")
    jurisdiction_scope = req_str_array(data, "jurisdiction_scope", non_empty=True)

    for existing in db.policies.values():
        if existing["program_id"] == program_id and existing["version_label"] == version_label:
            fail(
                "ERR_INVALID_REQUEST",
                "version_label %s already exists for this program." % version_label,
            )

    find_program(program_id)
    for jurisdiction_id in jurisdiction_scope:
        juris = find_jurisdiction(jurisdiction_id)
        if juris["program_id"] != program_id:
            fail(
                "ERR_JURISDICTION_MISMATCH",
                "State profile %s belongs to another program." % jurisdiction_id,
            )

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "version_label": version_label,
            "retention_days": retention_days,
            "destruction_trigger": destruction_trigger,
            "release_language_included": release_language_included,
            "jurisdiction_scope": list(jurisdiction_scope),
            "status": "DRAFT",
            "published_at": None,
            "submitted_by_user_id": None,
            "published_by_user_id": None,
            "revision_count": 0,
        }
    )
    db.policies[rec["id"]] = rec
    return respond(serialize.policy, rec, 201)


@bp.post("/policies/<policy_id>/transitions")
def policy_transition(policy_id):
    user_id, role = actor()
    raw = body()
    require_role_for_target(
        role,
        raw.get("to_status"),
        K.POLICY_STATUSES,
        POLICY_GRANTS,
        ("PrivacyOfficer", "ComplianceApprover"),
    )
    to_status = req_enum(raw, "to_status", K.POLICY_STATUSES)

    policy = find_policy(policy_id)
    current = policy["status"]

    edges = {("DRAFT", "IN_REVIEW"), ("IN_REVIEW", "DRAFT"), ("SUPERSEDED", "RETIRED")}
    if (current, to_status) not in edges:
        fail("ERR_INVALID_TRANSITION", "A policy cannot move from %s to %s." % (current, to_status))

    if to_status == "IN_REVIEW":
        scope = [find_jurisdiction(j) for j in policy["jurisdiction_scope"]]
        for juris in scope:
            if juris["program_id"] != policy["program_id"]:
                fail(
                    "ERR_JURISDICTION_MISMATCH",
                    "State profile %s belongs to another program." % juris["id"],
                )
        for juris in scope:
            if juris["requires_written_release"] and not policy["release_language_included"]:
                fail(
                    "ERR_WRITTEN_RELEASE_REQUIRED",
                    "The policy must embed the written-release language for %s."
                    % juris["state_code"],
                )
        for juris in scope:
            if policy["retention_days"] > juris["retention_max_days"]:
                fail(
                    "ERR_RETENTION_EXCEEDS_JURISDICTION_MAX",
                    "retention_days exceeds the statutory ceiling for %s." % juris["state_code"],
                )
        policy["status"] = "IN_REVIEW"
        policy["submitted_by_user_id"] = user_id
        touch(policy)

    elif to_status == "DRAFT":
        policy["status"] = "DRAFT"
        policy["revision_count"] += 1
        policy["submitted_by_user_id"] = None
        touch(policy)

    else:  # RETIRED
        for asset in db.assets.values():
            if asset["pinned_policy_id"] == policy_id and asset["status"] in ("ACTIVE", "GATED"):
                fail(
                    "ERR_ASSET_STILL_ACTIVE",
                    "A collection point still pins this policy version.",
                )
        policy["status"] = "RETIRED"
        touch(policy)

    return respond(serialize.policy, policy)


@bp.post("/policies/<policy_id>/publish")
def publish_policy(policy_id):
    user_id, role = actor()
    require_role(role, ("ComplianceApprover",))
    data = body()
    expected_program_version = req_int(data, "expected_program_version")

    policy = find_policy(policy_id)
    program = db.programs.get(policy["program_id"])

    # step 6: stale-read rejection
    if program is None or program["version"] != expected_program_version:
        fail(
            "ERR_STALE_PROGRAM_VERSION",
            "expected_program_version does not match the program's current version.",
        )

    # step 7: separation of duties
    if policy["submitted_by_user_id"] is not None and user_id == policy["submitted_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The publisher must differ from the user who submitted the policy.",
        )

    # step 8: transition legality
    if policy["status"] != "IN_REVIEW":
        fail(
            "ERR_INVALID_TRANSITION",
            "Only an IN_REVIEW policy may be published; this one is %s." % policy["status"],
        )

    # step 9: posture gate
    if program["posture"] == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_BLOCKED", "The program is FROZEN; publication is blocked.")

    policy["status"] = "PUBLISHED"
    policy["published_at"] = db.clock
    policy["published_by_user_id"] = user_id

    cascade_b(policy)

    touch(program)
    touch(policy)
    return respond(serialize.policy, policy)


@bp.get("/policies/<policy_id>")
def read_policy(policy_id):
    _, role = actor()
    require_role(role, POLICY_READ_ROLES)
    policy = find_policy(policy_id)
    return respond(serialize.policy, policy)


@bp.get("/policies")
def list_policies():
    _, role = actor()
    require_role(role, POLICY_READ_ROLES)
    program_id = query_str("program_id")
    status = query_enum("status", K.POLICY_STATUSES)
    rows = list(db.policies.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond_list(rows, serialize.policy)


# --- NoticePacket -----------------------------------------------------------

@bp.post("/notice-packets")
def create_notice():
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    data = body()
    program_id = req_str(data, "program_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    policy_id = req_str(data, "policy_id")
    audience = req_enum(data, "audience", K.AUDIENCES)
    locales = req_str_array(data, "locales", non_empty=True)
    accommodation_channel = req_str(data, "accommodation_channel")
    effective_from = req_datetime(data, "effective_from")
    effective_to = opt_datetime(data, "effective_to")

    find_program(program_id)
    find_jurisdiction(jurisdiction_id)
    find_policy(policy_id)

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "policy_id": policy_id,
            "audience": audience,
            "locales": list(locales),
            "accommodation_channel": accommodation_channel,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "DRAFT",
            "published_at": None,
            "consent_eligible_from": None,
        }
    )
    db.notices[rec["id"]] = rec
    return respond(serialize.notice, rec, 201)


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) intersection; None `to` means +infinity."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


@bp.post("/notice-packets/<notice_id>/transitions")
def notice_transition(notice_id):
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    raw = body()
    to_status = req_enum(raw, "to_status", K.NOTICE_STATUSES)

    notice = find_notice(notice_id)
    current = notice["status"]

    edges = {("DRAFT", "PUBLISHED"), ("PUBLISHED", "WITHDRAWN")}
    if (current, to_status) not in edges:
        fail(
            "ERR_INVALID_TRANSITION",
            "A notice packet cannot move from %s to %s." % (current, to_status),
        )

    program = db.programs.get(notice["program_id"])
    juris = db.jurisdictions.get(notice["jurisdiction_id"])

    if to_status == "PUBLISHED":
        # step 9
        if program is not None and program["posture"] == "FROZEN":
            fail(
                "ERR_PROGRAM_POSTURE_BLOCKED",
                "The program is FROZEN; notice publication is blocked.",
            )
        # step 10
        policy = db.policies.get(notice["policy_id"])
        if policy is None or policy["status"] != "PUBLISHED":
            fail(
                "ERR_POLICY_NOT_PUBLISHED",
                "A notice packet may only reproduce a published policy.",
            )
        if juris is not None and juris["translation_required"]:
            if not set(juris["required_locales"]).issubset(set(notice["locales"])):
                fail(
                    "ERR_TRANSLATION_LOCALE_MISSING",
                    "The packet's locales do not cover every required locale.",
                )
        # step 11
        for other in ordered(list(db.notices.values())):
            if other["id"] == notice_id or other["status"] != "PUBLISHED":
                continue
            if (
                other["jurisdiction_id"] != notice["jurisdiction_id"]
                or other["audience"] != notice["audience"]
            ):
                continue
            if _windows_overlap(
                notice["effective_from"],
                notice["effective_to"],
                other["effective_from"],
                other["effective_to"],
            ):
                fail(
                    "ERR_NOTICE_WINDOW_OVERLAP",
                    "Another published packet already covers an overlapping window.",
                )

        notice["status"] = "PUBLISHED"
        notice["published_at"] = db.clock
        lead_days = juris["notice_lead_days"] if juris is not None else 0
        notice["consent_eligible_from"] = add_days(notice["published_at"], lead_days)
        touch(notice)

    else:  # WITHDRAWN
        for asset in db.assets.values():
            if (
                asset["jurisdiction_id"] == notice["jurisdiction_id"]
                and asset["subject_class"] == notice["audience"]
                and asset["status"] == "ACTIVE"
            ):
                fail(
                    "ERR_ASSET_STILL_ACTIVE",
                    "A collection point in this state is still actively collecting.",
                )
        notice["status"] = "WITHDRAWN"
        touch(notice)

    return respond(serialize.notice, notice)


@bp.get("/notice-packets/<notice_id>")
def read_notice(notice_id):
    _, role = actor()
    require_role(role, POLICY_READ_ROLES)
    notice = find_notice(notice_id)
    return respond(serialize.notice, notice)


@bp.get("/notice-packets")
def list_notices():
    _, role = actor()
    require_role(role, POLICY_READ_ROLES)
    program_id = query_str("program_id")
    jurisdiction_id = query_str("jurisdiction_id")
    policy_id = query_str("policy_id")
    audience = query_enum("audience", K.AUDIENCES)
    status = query_enum("status", K.NOTICE_STATUSES)
    rows = list(db.notices.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if audience is not None:
        rows = [r for r in rows if r["audience"] == audience]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond_list(rows, serialize.notice)
