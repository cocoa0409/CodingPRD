"""Auto-transitions: license SIGNED, EFFECTIVE, EXPIRED; contract cascades."""
from clock import format_iso, get_now, parse_iso
from common import stamp_update
from db import db
from errors import api_error
from services.audit import append_audit, append_rights_chain


def evaluate_signed_transition(contract: dict):
    """When contract reaches FULLY_SIGNED, advance license ACCEPTED → SIGNED.

    Preconditions: contract_id set; pinned_work_version still matches Work.version.
    Side effects: AuditLog{CONTRACT_AMENDED}, RightsChainEvent{LICENSE_SIGNED}.
    """
    license_obj = db.licenses.get(contract.get("license_id"))
    if not license_obj:
        return
    if license_obj.get("status") != "ACCEPTED":
        return
    work = db.works.get(license_obj.get("work_id"))
    if not work:
        raise api_error("ERR_PINNED_VERSION_STALE", "work missing for pinned version check")
    if license_obj.get("pinned_work_version") != work.get("version"):
        raise api_error("ERR_PINNED_VERSION_STALE",
                        "Work.version drifted from pinned_work_version")
    before = {"status": license_obj["status"]}
    license_obj["status"] = "SIGNED"
    stamp_update(license_obj)
    append_audit("system", "License", license_obj["id"], "CONTRACT_AMENDED",
                 before, {"status": license_obj["status"]})
    append_rights_chain(license_obj["work_id"], "LICENSE_SIGNED", "system",
                        "License", license_obj["id"], {})


def evaluate_effective_transition(contract: dict, license_obj: dict = None):
    """If contract.status==FULLY_SIGNED and now() >= max(target, term_start),
    advance license SIGNED→EFFECTIVE and contract FULLY_SIGNED→EFFECTIVE.
    Boundary inclusive (>=)."""
    if contract.get("status") != "FULLY_SIGNED":
        return
    if license_obj is None:
        license_obj = db.licenses.get(contract.get("license_id"))
    if not license_obj or license_obj.get("status") != "SIGNED":
        return
    target = parse_iso(contract.get("effective_date_target"))
    term_start = parse_iso(license_obj.get("term_start"))
    if target is None or term_start is None:
        return
    candidate = max(target, term_start)
    now = get_now()
    if now < candidate:
        return
    license_before = {"status": license_obj["status"], "effective_date": license_obj.get("effective_date")}
    license_obj["effective_date"] = format_iso(candidate)
    license_obj["status"] = "EFFECTIVE"
    stamp_update(license_obj)
    contract_before = {"status": contract["status"]}
    contract["status"] = "EFFECTIVE"
    stamp_update(contract)
    append_audit("system", "License", license_obj["id"], "LICENSE_CHANGED",
                 license_before,
                 {"status": license_obj["status"], "effective_date": license_obj["effective_date"]})
    append_audit("system", "Contract", contract["id"], "CONTRACT_AMENDED",
                 contract_before, {"status": contract["status"]})


def evaluate_expired_transition(license_obj: dict):
    """EFFECTIVE → EXPIRED when now() >= term_end."""
    if license_obj.get("status") != "EFFECTIVE":
        return
    term_end = parse_iso(license_obj.get("term_end"))
    if term_end is None:
        return
    if get_now() < term_end:
        return
    before = {"status": license_obj["status"]}
    license_obj["status"] = "EXPIRED"
    stamp_update(license_obj)
    append_audit("system", "License", license_obj["id"], "LICENSE_CHANGED",
                 before, {"status": license_obj["status"]})
    append_rights_chain(license_obj["work_id"], "LICENSE_TERMINATED", "system",
                        "License", license_obj["id"], {"reason": "EXPIRED"})


def evaluate_clock_advanced():
    """After clock has been advanced, run any pending auto-transitions."""
    # SIGNED → EFFECTIVE for contracts that are FULLY_SIGNED whose target reached.
    for contract in list(db.contracts.values()):
        if contract.get("status") == "FULLY_SIGNED":
            evaluate_effective_transition(contract)
    # EFFECTIVE → EXPIRED.
    for license_obj in list(db.licenses.values()):
        if license_obj.get("status") == "EFFECTIVE":
            evaluate_expired_transition(license_obj)


def evaluate_supersede(contract: dict):
    """When a supplementary contract reaches FULLY_SIGNED, parent EFFECTIVE→SUPERSEDED."""
    parent_id = contract.get("parent_contract_id")
    if not parent_id:
        return
    parent = db.contracts.get(parent_id)
    if not parent:
        return
    if parent.get("status") != "EFFECTIVE":
        return
    before = {"status": parent["status"]}
    parent["status"] = "SUPERSEDED"
    stamp_update(parent)
    append_audit("system", "Contract", parent["id"], "CONTRACT_AMENDED",
                 before, {"status": parent["status"]})
