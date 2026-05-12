"""Resource lookup helpers with hierarchical validation."""
import db
from errors import (
    raise_error,
    ERR_PROJECT_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_MILESTONE_NOT_FOUND,
    ERR_GUEST_NOT_FOUND,
    ERR_TIMELINE_SLOT_NOT_FOUND,
    ERR_CHANGE_ORDER_NOT_FOUND,
    ERR_SETTLEMENT_NOT_FOUND,
    ERR_TEMPLATE_NOT_FOUND,
    ERR_PROJECT_TERMINAL,
)


def get_project(project_id: str) -> dict:
    p = db.projects.get(project_id)
    if not p:
        raise_error(ERR_PROJECT_NOT_FOUND, "WeddingProject not found")
    return p


def get_template(template_id: str) -> dict:
    t = db.templates.get(template_id)
    if not t:
        raise_error(ERR_TEMPLATE_NOT_FOUND, "ProjectTemplate not found")
    return t


def get_vendor(vendor_id: str) -> dict:
    v = db.vendors.get(vendor_id)
    if not v:
        raise_error(ERR_VENDOR_NOT_FOUND, "Vendor not found")
    return v


def get_quote(vendor_id: str, quote_id: str) -> dict:
    q = db.quotes.get(quote_id)
    if not q or q["vendor_id"] != vendor_id:
        raise_error(ERR_QUOTE_NOT_FOUND, "Quote not found for this vendor")
    return q


def get_contract(project_id: str, contract_id: str) -> dict:
    c = db.contracts.get(contract_id)
    if not c or c["project_id"] != project_id:
        raise_error(ERR_CONTRACT_NOT_FOUND, "Contract not found in this project")
    return c


def get_milestone(project_id: str, milestone_id: str) -> dict:
    m = db.milestones.get(milestone_id)
    if not m or m["project_id"] != project_id:
        raise_error(ERR_MILESTONE_NOT_FOUND, "Milestone not found in this project")
    return m


def get_guest(project_id: str, guest_id: str) -> dict:
    g = db.guests.get(guest_id)
    if not g or g["project_id"] != project_id:
        raise_error(ERR_GUEST_NOT_FOUND, "Guest not found in this project")
    return g


def get_timeline_slot(project_id: str, slot_id: str) -> dict:
    s = db.timeline_slots.get(slot_id)
    if not s or s["project_id"] != project_id:
        raise_error(ERR_TIMELINE_SLOT_NOT_FOUND, "TimelineSlot not found in this project")
    return s


def get_change_order(contract_id: str, change_order_id: str) -> dict:
    co = db.change_orders.get(change_order_id)
    if not co or co["contract_id"] != contract_id:
        raise_error(ERR_CHANGE_ORDER_NOT_FOUND, "ChangeOrder not found for this contract")
    return co


def get_settlement_for_contract(contract_id: str) -> dict:
    for s in db.settlements.values():
        if s["contract_id"] == contract_id:
            return s
    raise_error(ERR_SETTLEMENT_NOT_FOUND, "Settlement not found for this contract")


def assert_project_not_terminal(project: dict) -> None:
    if project["status"] in ("CLOSED", "CANCELLED"):
        raise_error(ERR_PROJECT_TERMINAL, "Project is in a terminal state")
