"""Change control: submission, prerequisite graph, approval lanes, merge and
withdrawal."""

from flask import Blueprint, request

import db
import validate as v
from db import make, now, store, upd
from errors import fail
from middleware import ANY, authenticate
from response import array_response, object_response
from services import calc, cascade

bp = Blueprint("changes", __name__)

WITHDRAWABLE = (
    "DRAFT",
    "RISK_CLASSIFIED",
    "CAB_REVIEW",
    "APPROVED",
    "BLOCKED_BY_DEPENDENCY",
    "DEFERRED",
)
COUNTER_FIELD = {
    "TECHNICAL": "approval_technical_count",
    "COMPLIANCE": "approval_compliance_count",
    "CAB": "approval_cab_count",
}
LANE_ROLE = {
    "TECHNICAL": "ChangeApprover",
    "CAB": "ChangeApprover",
    "COMPLIANCE": "ComplianceOfficer",
}


def _train_of(release):
    return store.release_trains.get(release["release_train_id"])


def _budget_would_exceed(release, added_points):
    train = _train_of(release)
    if train is None:
        return False
    return release["risk_budget_consumed_points"] + added_points > train["risk_budget_points"]


@bp.get("/change-requests/<change_id>")
def read_change(change_id):
    authenticate(ANY)
    change = db.get_change(change_id)
    return object_response(db.public(change))


@bp.post("/change-requests/<change_id>/submit")
def submit_change(change_id):
    user_id, _role = authenticate(("Engineer",))
    v.get_body()
    change = db.get_change(change_id)
    release = db.get_release(change["release_id"])

    if change["state"] != "DRAFT":
        fail("ERR_CHANGE_STATE_INVALID", "Only a DRAFT change may be submitted")
    if release["phase"] != "OPEN":
        fail("ERR_RELEASE_PHASE_INVALID", "The release is not OPEN")
    if user_id != change["author_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the author may submit this change")

    preliminary = calc.preliminary_risk_score(change)
    risk_class = calc.risk_tier(preliminary)

    final = None
    if risk_class == "LOW":
        probe = dict(change)
        probe["risk_class"] = risk_class
        probe["risk_score_preliminary"] = preliminary
        final = calc.final_risk_score(probe)
        if _budget_would_exceed(release, final):
            fail(
                "ERR_RISK_BUDGET_EXCEEDED",
                "Approving this change would exceed the train's risk budget",
            )

    upd(
        change,
        risk_score_preliminary=preliminary,
        risk_class=risk_class,
        state="RISK_CLASSIFIED",
    )
    cascade.refresh_projected(release)

    if risk_class == "LOW":
        upd(change, state="APPROVED", risk_score_final=final)
        cascade.credit_approval(release, change)
        cascade.refresh_projected(release)
    elif risk_class == "CRITICAL":
        upd(change, state="CAB_REVIEW")
        cascade.refresh_projected(release)

    return object_response(db.public(change))


# ---------------------------------------------------------------------------
# prerequisite graph
# ---------------------------------------------------------------------------
@bp.post("/change-requests/<change_id>/dependencies")
def create_dependency(change_id):
    authenticate(("Engineer",))
    body = v.get_body()
    to_change_id = v.req_str(body, "to_change_id", allow_blank=False)
    note = v.opt_str(body, "note")
    change = db.get_change(change_id)
    prerequisite = db.get_change(to_change_id)

    if change_id == to_change_id:
        fail("ERR_DEPENDENCY_CYCLE", "A change may not depend on itself")
    if prerequisite["release_id"] != change["release_id"]:
        fail("ERR_DEPENDENCY_CYCLE", "Both endpoints must belong to the same release")
    if calc.creates_cycle(change_id, to_change_id):
        fail("ERR_DEPENDENCY_CYCLE", "The edge would close a cycle in the prerequisite graph")

    edge = make(
        "change_dependencies",
        {"from_change_id": change_id, "to_change_id": to_change_id, "note": note},
        common=False,
    )
    upd(change, dependency_depth=calc.dependency_depth(change_id))
    cascade.refresh_projected(db.get_release(change["release_id"]))
    return object_response(db.public(edge), 201)


@bp.get("/change-requests/<change_id>/dependencies")
def list_dependencies(change_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_change(change_id)
    direction = request.args.get("direction") or "OUTGOING"
    if direction == "INCOMING":
        records = db.deps_to(change_id)
    else:
        records = db.deps_from(change_id)
    records = db.by_creation(records)
    items = [db.public(e) for e in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


# ---------------------------------------------------------------------------
# flag guards
# ---------------------------------------------------------------------------
@bp.post("/change-requests/<change_id>/flag-links")
def create_flag_link(change_id):
    authenticate(("Engineer",))
    body = v.get_body()
    feature_flag_id = v.req_str(body, "feature_flag_id", allow_blank=False)
    guard_kind = v.req_enum(body, "guard_kind", ("GATES_ENTIRE_CHANGE", "PARTIAL"))
    change = db.get_change(change_id)
    db.get_flag(feature_flag_id)

    link = make(
        "change_flag_links",
        {
            "change_request_id": change_id,
            "feature_flag_id": feature_flag_id,
            "guard_kind": guard_kind,
        },
        common=False,
    )
    cascade.refresh_projected(db.get_release(change["release_id"]))
    return object_response(db.public(link), 201)


@bp.get("/change-requests/<change_id>/flag-links")
def list_flag_links(change_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_change(change_id)
    records = db.by_creation(db.links_of_change(change_id))
    items = [db.public(l) for l in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


# ---------------------------------------------------------------------------
# approval lanes
# ---------------------------------------------------------------------------
def _join_reached(change, counters):
    if change["state"] == "RISK_CLASSIFIED":
        if change["risk_class"] == "MEDIUM":
            return counters["approval_technical_count"] >= 1
        if change["risk_class"] == "HIGH":
            return (
                counters["approval_technical_count"] >= 1
                and counters["approval_compliance_count"] >= 1
            )
        return False
    if change["state"] == "CAB_REVIEW":
        return (
            counters["approval_technical_count"] >= 1
            and counters["approval_compliance_count"] >= 1
            and counters["approval_cab_count"] >= 1
        )
    return False


@bp.post("/change-requests/<change_id>/approvals")
def create_approval(change_id):
    user_id, role = authenticate(("ChangeApprover", "ComplianceOfficer"))
    body = v.get_body()
    kind = v.req_enum(body, "kind", ("TECHNICAL", "COMPLIANCE", "CAB"))
    decision = v.req_enum(body, "decision", ("APPROVE", "REJECT"))
    comment = v.opt_str(body, "comment")
    change = db.get_change(change_id)
    release = db.get_release(change["release_id"])

    if change["state"] not in ("RISK_CLASSIFIED", "CAB_REVIEW"):
        fail(
            "ERR_CHANGE_STATE_INVALID",
            "Approvals may only be recorded while the change awaits a decision",
        )

    existing = db.by_creation(db.approvals_of_change(change_id))
    if user_id == change["author_user_id"]:
        fail("ERR_SELF_APPROVAL_FORBIDDEN", "An author may not approve their own change")
    if kind == "CAB":
        for row in existing:
            if row["kind"] == "TECHNICAL" and row["approver_user_id"] == user_id:
                fail(
                    "ERR_SELF_APPROVAL_FORBIDDEN",
                    "The CAB lane may not be recorded by the technical reviewer",
                )

    if LANE_ROLE[kind] != role:
        fail("ERR_APPROVAL_ROLE_MISMATCH", "Role %s may not record a %s decision" % (role, kind))

    if kind not in calc.APPROVALS_REQUIRED.get(change["risk_class"] or "LOW", ()):
        fail(
            "ERR_APPROVAL_KIND_NOT_REQUIRED",
            "A %s change does not require the %s lane" % (change["risk_class"], kind),
        )

    if decision == "APPROVE":
        for row in existing:
            if row["kind"] == kind and row["decision"] == "APPROVE":
                fail("ERR_DUPLICATE_APPROVAL_KIND", "The %s lane is already approved" % kind)

    field = COUNTER_FIELD[kind]
    counters = {
        "approval_technical_count": change["approval_technical_count"],
        "approval_compliance_count": change["approval_compliance_count"],
        "approval_cab_count": change["approval_cab_count"],
    }
    join = False
    final = None
    if decision == "APPROVE":
        counters[field] += 1
        join = _join_reached(change, counters)
        if join:
            final = calc.final_risk_score(change)
            if _budget_would_exceed(release, final):
                fail(
                    "ERR_RISK_BUDGET_EXCEEDED",
                    "Approving this change would exceed the train's risk budget",
                )

    approval = make(
        "approvals",
        {
            "change_request_id": change_id,
            "kind": kind,
            "decision": decision,
            "comment": comment,
            "approver_user_id": user_id,
            "pinned_risk_score": change["risk_score_preliminary"],
            "pinned_change_version": change["version"],
        },
        common=False,
    )

    if decision == "REJECT":
        upd(change, state="REJECTED")
        cascade.refresh_projected(release)
    elif join:
        upd(change, state="APPROVED", risk_score_final=final, **{field: counters[field]})
        cascade.credit_approval(release, change)
        cascade.refresh_projected(release)
    else:
        upd(change, **{field: counters[field]})

    return object_response(db.public(approval), 201)


@bp.get("/change-requests/<change_id>/approvals")
def list_approvals(change_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_change(change_id)
    records = db.by_creation(db.approvals_of_change(change_id))
    kind = request.args.get("kind")
    if kind is not None:
        records = [a for a in records if a["kind"] == kind]
    items = [db.public(a) for a in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


# ---------------------------------------------------------------------------
# merge / withdraw
# ---------------------------------------------------------------------------
@bp.post("/change-requests/<change_id>/merge")
def merge_change(change_id):
    user_id, _role = authenticate(("Engineer",))
    v.get_body()
    change = db.get_change(change_id)
    release = db.get_release(change["release_id"])
    train = _train_of(release)

    if change["state"] != "APPROVED":
        fail("ERR_CHANGE_STATE_INVALID", "Only an APPROVED change may merge")
    if user_id != change["author_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the author may merge this change")

    if change["risk_class"] in ("HIGH", "CRITICAL"):
        if change["rollback_plan"] is None or not change["rollback_tested"]:
            fail(
                "ERR_ROLLBACK_PLAN_REQUIRED",
                "A tested rollback plan is required for a %s change" % change["risk_class"],
            )

    for edge in db.by_creation(db.deps_from(change_id)):
        prerequisite = store.change_requests.get(edge["to_change_id"])
        if prerequisite is None or prerequisite["state"] not in ("MERGED", "DEPLOYED"):
            fail("ERR_PREREQUISITE_NOT_MERGED", "A prerequisite has not landed yet")

    exception = release["freeze_exception_approved"]
    if release["phase"] == "OPEN":
        pass
    elif release["phase"] in ("FROZEN", "CUT") and exception:
        pass
    else:
        fail("ERR_CODE_FREEZE_ACTIVE", "The release phase does not permit a merge")
    if now() >= release["freeze_at"] and not exception:
        fail("ERR_CODE_FREEZE_ACTIVE", "The code freeze deadline has passed")

    if train is not None and release["risk_budget_consumed_points"] > train["risk_budget_points"]:
        fail("ERR_RISK_BUDGET_EXCEEDED", "The release has exhausted its risk budget")

    upd(change, state="MERGED", merged_at=now())
    cascade.unblock_dependents_after_merge(release)
    upd(
        release,
        rollback_plan_confirmed=calc.rollback_plan_confirmed(release),
        readiness_score_projected=calc.readiness_projected(release),
    )
    return object_response(db.public(change))


@bp.post("/change-requests/<change_id>/withdraw")
def withdraw_change(change_id):
    user_id, _role = authenticate(("Engineer",))
    body = v.get_body()
    v.opt_str(body, "reason")
    change = db.get_change(change_id)
    release = db.get_release(change["release_id"])

    if change["state"] not in WITHDRAWABLE:
        fail("ERR_CHANGE_STATE_INVALID", "State %s may not be withdrawn" % change["state"])
    if user_id != change["author_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the author may withdraw this change")

    was_approved = change["state"] == "APPROVED"
    upd(change, state="WITHDRAWN")

    touched = set()
    if was_approved:
        cascade.debit_approval(release, change)
        cascade.block_approved_dependents(change, touched)

    touched.add(release["id"])
    for release_id in touched:
        affected = store.releases.get(release_id)
        if affected is not None:
            cascade.refresh_projected(affected)
    return object_response(db.public(change))
