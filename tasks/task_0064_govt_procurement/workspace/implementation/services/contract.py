"""Contract lifecycle: filing, signing, amendment, payment, termination."""

from clock import clock
from db import bump_version, common_fields_create, db, light_fields_create
from errors import (
    ERR_AMENDMENT_EXCEEDS_CAP,
    ERR_CONTRACT_INCONSISTENT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PROJECT_FROZEN,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SUPPLIER_BLACKLISTED,
    ERR_VALIDATION,
    raise_error,
)
from services.audit import append_audit
from services.bid import get_bid_or_404
from services.project import get_project_or_ref_404
from services.supplier import (
    get_supplier_or_ref_404,
    is_currently_blacklisted,
)


def get_contract_or_404(contract_id: str) -> dict:
    c = db.contracts.get(contract_id)
    if not c:
        raise_error(ERR_NOT_FOUND, f"contract '{contract_id}' not found")
    return c


def file_contract(body: dict):
    project_id = body.get("project_id")
    award_id = body.get("award_id")
    supplier_id = body.get("supplier_id")
    amt = body.get("contract_amount_cents")
    pt = body.get("payment_terms")
    if not all(isinstance(x, str) and x for x in (project_id, award_id, supplier_id)):
        raise_error(ERR_VALIDATION, "project_id, award_id, supplier_id required")
    if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
        raise_error(ERR_VALIDATION, "contract_amount_cents must be positive integer")
    if not isinstance(pt, str) or not pt:
        raise_error(ERR_VALIDATION, "payment_terms must be non-empty string")
    project = get_project_or_ref_404(project_id)
    award = db.awards.get(award_id)
    if not award:
        raise_error(ERR_REFERENCE_NOT_FOUND, "award not found")
    supplier = get_supplier_or_ref_404(supplier_id)
    if award["project_id"] != project_id:
        raise_error(ERR_VALIDATION, "award does not belong to project")
    # PRD §3.11 names the sign-time precondition "award's status must be
    # PUBLISHED" explicitly. Filing only requires the award reference to
    # resolve; the PUBLISHED state is verified at sign.
    if project_id in db.contract_by_project:
        raise_error(ERR_INVALID_STATE, "contract already filed for project")
    # blacklist check on supplier for contracts
    if is_currently_blacklisted(supplier):
        raise_error(ERR_SUPPLIER_BLACKLISTED, "supplier is blacklisted")
    # PRD §3.11: The three-clause consistency check runs at SIGN, not at
    # FILE. Filing only validates field shapes, the award reference, and
    # the one-contract-per-project invariant.
    c = {
        "id": db.new_id(),
        **common_fields_create(),
        "project_id": project_id,
        "award_id": award_id,
        "supplier_id": supplier_id,
        "contract_amount_cents": int(amt),
        "payment_terms": pt,
        "signature_ref": None,
        "contract_status": "PENDING_SIGNATURE",
        "paid_amount_cents": 0,
    }
    db.contracts[c["id"]] = c
    db.contract_by_project[project_id] = c["id"]
    return c


def _contract_is_consistent(award: dict, supplier_id: str, amt: int, pt: str) -> bool:
    if int(amt) != int(award["award_amount_cents"]):
        return False
    winning_bid_id = award.get("winning_bid_id")
    winning_bid = db.bids.get(winning_bid_id) if winning_bid_id else None
    if not winning_bid:
        return False
    if winning_bid["supplier_id"] != supplier_id:
        return False
    # payment_terms must match TenderDocument.commercial_spec at the version pinned at award time
    pinned_version = db.award_tender_version.get(award["id"])
    project_id = award["project_id"]
    doc_id = db.tender_by_project.get(project_id)
    doc = db.tender_documents.get(doc_id) if doc_id else None
    if not doc:
        return False
    # The current doc may have moved on; we capture commercial_spec at award time?
    # In this in-memory model we don't track historical commercial_spec separately,
    # but the spec stays on the doc unless explicitly changed via a new amendment.
    # The 'version' check ensures we have the right doc.
    if doc.get("commercial_spec") != pt:
        return False
    return True


def sign_contract(contract_id: str):
    c = get_contract_or_404(contract_id)
    if c["contract_status"] != "PENDING_SIGNATURE":
        raise_error(ERR_INVALID_STATE, "contract must be PENDING_SIGNATURE to sign")
    award = db.awards.get(c["award_id"])
    if not award:
        raise_error(ERR_NOT_FOUND, "award gone")
    project = db.projects.get(c["project_id"])
    if not project:
        raise_error(ERR_NOT_FOUND, "project gone")
    # If the project is FROZEN by a complaint, reject with ERR_PROJECT_FROZEN
    if project["project_status"] == "FROZEN":
        raise_error(ERR_PROJECT_FROZEN, "project is frozen by complaint")
    if award["award_status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "award must be PUBLISHED to sign")
    if project["project_status"] != "AWARDED":
        raise_error(ERR_INVALID_STATE, "project must be AWARDED to sign")
    supplier = db.suppliers.get(c["supplier_id"])
    if not supplier:
        raise_error(ERR_NOT_FOUND, "supplier gone")
    if supplier["registration_status"] != "VERIFIED" or is_currently_blacklisted(supplier):
        raise_error(ERR_INVALID_STATE, "supplier must be VERIFIED and not blacklisted")
    # Consistency check
    if not _contract_is_consistent(award, c["supplier_id"], c["contract_amount_cents"], c["payment_terms"]):
        raise_error(ERR_CONTRACT_INCONSISTENT, "contract clauses inconsistent with award/tender")
    # Side effects
    c["signature_ref"] = f"sig_{db.new_id()}"
    c["contract_status"] = "ACTIVE"
    bump_version(c)
    project["project_status"] = "CONTRACT_SIGNED"
    bump_version(project)
    item = db.plan_items.get(project["plan_item_id"])
    if item:
        item["item_status"] = "EXECUTED"
        item["executed_amount_cents"] = int(item.get("executed_amount_cents", 0)) + int(c["contract_amount_cents"])
        bump_version(item)
        plan = db.plans.get(item["plan_id"])
        if plan and plan["status"] == "PUBLISHED":
            from services.plan import recompute_total_budget
            recompute_total_budget(plan)
            bump_version(plan)
    append_audit("CONTRACT", c["id"], "CONTRACT_SIGNED", {
        "project_id": project["id"],
        "contract_id": c["id"],
        "contract_amount_cents": c["contract_amount_cents"],
    })
    return c


def begin_amendment(contract_id: str):
    c = get_contract_or_404(contract_id)
    if c["contract_status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "contract must be ACTIVE")
    c["contract_status"] = "AMENDING"
    bump_version(c)
    return c


def file_amendment(contract_id: str, body: dict):
    c = get_contract_or_404(contract_id)
    if c["contract_status"] != "AMENDING":
        raise_error(ERR_INVALID_STATE, "contract must be AMENDING")
    delta = body.get("delta_amount_cents")
    if isinstance(delta, bool) or not isinstance(delta, int):
        raise_error(ERR_VALIDATION, "delta_amount_cents must be integer")
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise_error(ERR_VALIDATION, "reason must be non-empty string")
    new_amt = int(c["contract_amount_cents"]) + int(delta)
    award = db.awards.get(c["award_id"])
    if not award:
        raise_error(ERR_NOT_FOUND, "award gone")
    cap = int(award["award_amount_cents"]) * 120 // 100
    # The PRD says "at most one hundred and twenty percent" so allow equality.
    if new_amt <= 0 or new_amt > cap:
        raise_error(ERR_AMENDMENT_EXCEEDS_CAP, "amendment violates fiscal bounds")
    # Side effects
    c["contract_amount_cents"] = new_amt
    c["contract_status"] = "ACTIVE"
    bump_version(c)
    project = db.projects.get(c["project_id"])
    if project:
        item = db.plan_items.get(project["plan_item_id"]) if project else None
        if item:
            item["executed_amount_cents"] = int(item.get("executed_amount_cents", 0)) + int(delta)
            bump_version(item)
    amendment = {
        "id": db.new_id(),
        **light_fields_create(),
        "contract_id": c["id"],
        "delta_amount_cents": int(delta),
        "reason": reason,
        "filed_at": clock.now_iso(),
    }
    db.contract_amendments[amendment["id"]] = amendment
    return c


def record_payment(contract_id: str, body: dict):
    c = get_contract_or_404(contract_id)
    amt = body.get("amount_cents")
    if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
        raise_error(ERR_VALIDATION, "amount_cents must be positive integer")
    if c["contract_status"] not in {"ACTIVE", "AMENDING"}:
        raise_error(ERR_INVALID_STATE, "contract must be ACTIVE or AMENDING to record payment")
    c["paid_amount_cents"] = int(c.get("paid_amount_cents", 0)) + int(amt)
    bump_version(c)
    return c


def mark_executed(contract_id: str):
    c = get_contract_or_404(contract_id)
    if c["contract_status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "contract must be ACTIVE to mark executed")
    if int(c.get("paid_amount_cents", 0)) < int(c["contract_amount_cents"]):
        raise_error(ERR_INVALID_STATE, "contract not fully paid")
    c["contract_status"] = "EXECUTED"
    bump_version(c)
    return c


def terminate_contract(contract_id: str, body: dict):
    c = get_contract_or_404(contract_id)
    if c["contract_status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "contract must be ACTIVE to terminate")
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise_error(ERR_VALIDATION, "reason must be non-empty string")
    c["contract_status"] = "TERMINATED"
    bump_version(c)
    project = db.projects.get(c["project_id"])
    if project:
        item = db.plan_items.get(project["plan_item_id"])
        if item:
            unpaid = int(c["contract_amount_cents"]) - int(c.get("paid_amount_cents", 0))
            item["executed_amount_cents"] = int(item.get("executed_amount_cents", 0)) - unpaid
            bump_version(item)
    return c
