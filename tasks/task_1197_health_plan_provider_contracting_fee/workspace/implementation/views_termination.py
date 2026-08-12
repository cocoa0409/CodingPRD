"""Termination notices (issue / finalize / rescind) and continuity-of-care
cases, including the finalize and rescind cascades."""

from flask import Blueprint

import store
from bodycheck import DATE, ENUM, STR, parse_date, validate_body
from envelope import ok, ok_list
from errors import ApiError
from helpers import get_case, get_notice, sorted_by_created
from pricing import coc_coverage_end
from security import (
    INTERNAL_ROLES, ROLE_CONTRACT_MANAGER, ROLE_PLAN_ADMIN,
    auth, require_roles,
)

bp = Blueprint("termination", __name__)

CONDITION_CATEGORIES = (
    "INPATIENT_CONFINEMENT", "PREGNANCY", "DIALYSIS",
    "ONCOLOGY_TREATMENT", "TRANSPLANT_WORKUP",
)


def _notice_invalid_state(action):
    return ApiError(
        "ERR_NOTICE_INVALID_STATE", 409,
        f"TerminationNotice state does not permit {action}.",
    )


def _case_invalid_state(action):
    return ApiError(
        "ERR_CASE_INVALID_STATE", 409,
        f"ContinuityOfCareCase state does not permit {action}.",
    )


# ---------------------------------------------------------------------------
# Notice read / issue / finalize / rescind
# ---------------------------------------------------------------------------
@bp.get("/termination-notices/<nid>")
def get_one_notice(nid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    return ok(dict(get_notice(nid)))


@bp.post("/termination-notices/<nid>/issue")
def issue_notice(nid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    notice = get_notice(nid)
    if notice["notice_status"] != "DRAFT":
        raise _notice_invalid_state("issue (requires DRAFT)")
    contract = store.contracts.get(notice["contract_id"])
    if contract["contract_status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_INVALID_STATE", 409,
            "Notice issue requires the parent contract to be ACTIVE.",
        )
    notice["notice_status"] = "ISSUED"
    store.touch(notice)
    store.add_audit(contract["id"], "NOTICE_ISSUED", role, user_id,
                    "Termination notice issued.")
    # Cascade: the parent contract moves ACTIVE -> TERMINATION_NOTICE.
    contract["contract_status"] = "TERMINATION_NOTICE"
    store.touch(contract)
    store.add_audit(contract["id"], "TERMINATION_NOTICE_ISSUED", role, "system",
                    "Contract moved to TERMINATION_NOTICE on notice issue.")
    return ok(dict(notice))


@bp.post("/termination-notices/<nid>/finalize")
def finalize_notice(nid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    notice = get_notice(nid)
    if notice["notice_status"] != "ISSUED":
        raise _notice_invalid_state("finalize (requires ISSUED)")
    if store.clock.today() < parse_date(notice["termination_date"], "termination_date"):
        raise _notice_invalid_state("finalize before termination_date")
    contract = store.contracts.get(notice["contract_id"])
    # Cascade link 1: the parent contract is terminated.
    contract["contract_status"] = "TERMINATED"
    store.touch(contract)
    store.add_audit(contract["id"], "CONTRACT_TERMINATED", role, "system",
                    "Contract terminated on notice finalization.")
    # Cascade link 2a: NOTIFIED continuity cases enter active coverage;
    # cases still IDENTIFIED are unaffected.
    for case in store.cases.values():
        if (case["termination_notice_id"] == nid
                and case["case_status"] == "NOTIFIED"):
            case["case_status"] = "ACTIVE_COVERAGE"
            store.touch(case)
    # Cascade link 2b: non-terminal simulation batches under every version of
    # the contract close; PASSED batches are preserved.
    for version in store.versions.values():
        if version["contract_id"] != contract["id"]:
            continue
        for batch in store.batches.values():
            if (batch["contract_version_id"] == version["id"]
                    and batch["batch_status"] in ("OPEN", "PRICED", "FAILED")):
                batch["batch_status"] = "CLOSED"
                store.touch(batch)
    notice["notice_status"] = "EFFECTIVE"
    store.touch(notice)
    store.add_audit(contract["id"], "NOTICE_EFFECTIVE", role, user_id,
                    "Termination notice finalized and effective.")
    return ok(dict(notice))


@bp.post("/termination-notices/<nid>/rescind")
def rescind_notice(nid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    notice = get_notice(nid)
    if notice["notice_status"] != "ISSUED":
        raise _notice_invalid_state("rescind (requires ISSUED)")
    contract = store.contracts.get(notice["contract_id"])
    notice["notice_status"] = "RESCINDED"
    store.touch(notice)
    store.add_audit(contract["id"], "NOTICE_RESCINDED", role, user_id,
                    "Termination notice rescinded.")
    # Compensation: contract returns to ACTIVE; pre-coverage cases close.
    contract["contract_status"] = "ACTIVE"
    store.touch(contract)
    store.add_audit(contract["id"], "TERMINATION_NOTICE_RESCINDED", role, "system",
                    "Contract restored to ACTIVE on notice rescission.")
    for case in store.cases.values():
        if (case["termination_notice_id"] == nid
                and case["case_status"] in ("IDENTIFIED", "NOTIFIED")):
            case["case_status"] = "CLOSED_RESCINDED"
            store.touch(case)
    return ok(dict(notice))


# ---------------------------------------------------------------------------
# Continuity-of-care cases
# ---------------------------------------------------------------------------
@bp.post("/termination-notices/<nid>/continuity-cases")
def create_case(nid):
    data = validate_body({
        "member_ref": (STR, True),
        "condition_category": (ENUM(*CONDITION_CATEGORIES), True),
        "treatment_end_date": (DATE, True),
    })
    _, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    notice = get_notice(nid)
    if notice["notice_status"] != "ISSUED":
        raise _notice_invalid_state("continuity-case creation (requires ISSUED)")
    if parse_date(data["treatment_end_date"], "treatment_end_date") <= parse_date(
            notice["termination_date"], "termination_date"):
        raise ApiError(
            "ERR_COC_WINDOW_EXCEEDED", 422,
            "treatment_end_date must fall after the notice termination_date.",
        )
    case = store.stamp_new({
        "termination_notice_id": nid,
        "member_ref": data["member_ref"],
        "condition_category": data["condition_category"],
        "treatment_end_date": data["treatment_end_date"],
        "coverage_end_date": coc_coverage_end(
            notice["termination_date"], data["treatment_end_date"]),
        "case_status": "IDENTIFIED",
    })
    store.cases[case["id"]] = case
    return ok(dict(case), 201)


@bp.get("/termination-notices/<nid>/continuity-cases")
def list_cases(nid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    get_notice(nid)
    items = [c for c in store.cases.values() if c["termination_notice_id"] == nid]
    return ok_list([dict(c) for c in sorted_by_created(items)])


@bp.get("/continuity-cases/<cid>")
def get_one_case(cid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    return ok(dict(get_case(cid)))


@bp.post("/continuity-cases/<cid>/notify")
def notify_case(cid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    case = get_case(cid)
    if case["case_status"] != "IDENTIFIED":
        raise _case_invalid_state("notify (requires IDENTIFIED)")
    notice = store.notices.get(case["termination_notice_id"])
    if notice["notice_status"] != "ISSUED":
        raise _case_invalid_state("notify (parent notice must be ISSUED)")
    case["case_status"] = "NOTIFIED"
    store.touch(case)
    return ok(dict(case))


@bp.post("/continuity-cases/<cid>/activate-coverage")
def activate_coverage(cid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    case = get_case(cid)
    if case["case_status"] != "NOTIFIED":
        raise _case_invalid_state("activate-coverage (requires NOTIFIED)")
    notice = store.notices.get(case["termination_notice_id"])
    if notice["notice_status"] != "EFFECTIVE":
        raise _case_invalid_state("activate-coverage (parent notice must be EFFECTIVE)")
    case["case_status"] = "ACTIVE_COVERAGE"
    store.touch(case)
    return ok(dict(case))


@bp.post("/continuity-cases/<cid>/complete")
def complete_case(cid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    case = get_case(cid)
    if case["case_status"] != "ACTIVE_COVERAGE":
        raise _case_invalid_state("complete (requires ACTIVE_COVERAGE)")
    case["case_status"] = "COMPLETED"
    store.touch(case)
    return ok(dict(case))


@bp.post("/continuity-cases/<cid>/expire")
def expire_case(cid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    case = get_case(cid)
    if case["case_status"] != "ACTIVE_COVERAGE":
        raise _case_invalid_state("expire (requires ACTIVE_COVERAGE)")
    if store.clock.today() <= parse_date(case["coverage_end_date"], "coverage_end_date"):
        raise _case_invalid_state("expire before coverage_end_date has passed")
    case["case_status"] = "EXPIRED"
    store.touch(case)
    return ok(dict(case))
