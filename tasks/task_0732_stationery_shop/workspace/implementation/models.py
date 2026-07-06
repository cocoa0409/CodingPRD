"""Entity constructors and lookup helpers."""

import db
import errors


def make_common(entity: dict) -> dict:
    """Attach id, created_at, updated_at, version to a fresh entity dict."""
    now = db.iso_now()
    entity["id"] = db.new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def bump(entity: dict):
    entity["updated_at"] = db.iso_now()
    entity["version"] = entity.get("version", 0) + 1


# ---- Lookup helpers with existence errors ---------------------------------

def get_customer(cid: str):
    o = db.customers.get(cid)
    if not o:
        errors.raise_error(errors.ERR_CUSTOMER_NOT_FOUND, f"Customer {cid} not found")
    return o


def get_designer(did: str):
    o = db.designers.get(did)
    if not o:
        errors.raise_error(errors.ERR_DESIGNER_NOT_FOUND, f"Designer {did} not found")
    return o


def get_paper_stock(pid: str):
    o = db.paper_stocks.get(pid)
    if not o:
        errors.raise_error(errors.ERR_PAPER_STOCK_NOT_FOUND, f"PaperStock {pid} not found")
    return o


def get_finish_option(fid: str):
    o = db.finish_options.get(fid)
    if not o:
        errors.raise_error(errors.ERR_FINISH_OPTION_NOT_FOUND, f"FinishOption {fid} not found")
    return o


def get_event_package(eid: str):
    o = db.event_packages.get(eid)
    if not o:
        errors.raise_error(errors.ERR_EVENT_PACKAGE_NOT_FOUND, f"EventPackage {eid} not found")
    return o


def get_design(did: str):
    o = db.designs.get(did)
    if not o:
        errors.raise_error(errors.ERR_DESIGN_NOT_FOUND, f"Design {did} not found")
    return o


def get_proof(pid: str):
    o = db.proofs.get(pid)
    if not o:
        errors.raise_error(errors.ERR_PROOF_NOT_FOUND, f"Proof {pid} not found")
    return o


def get_order(oid: str):
    o = db.orders.get(oid)
    if not o:
        errors.raise_error(errors.ERR_ORDER_NOT_FOUND, f"Order {oid} not found")
    return o


def get_line_item(lid: str):
    o = db.line_items.get(lid)
    if not o:
        errors.raise_error(errors.ERR_LINE_ITEM_NOT_FOUND, f"LineItem {lid} not found")
    return o


def get_addressing_job(aid: str):
    o = db.addressing_jobs.get(aid)
    if not o:
        errors.raise_error(errors.ERR_ADDRESSING_JOB_NOT_FOUND, f"AddressingJob {aid} not found")
    return o


def get_work_order(wid: str):
    o = db.work_orders.get(wid)
    if not o:
        errors.raise_error(errors.ERR_WORK_ORDER_NOT_FOUND, f"WorkOrder {wid} not found")
    return o


def get_shipment(sid: str):
    o = db.shipments.get(sid)
    if not o:
        errors.raise_error(errors.ERR_SHIPMENT_NOT_FOUND, f"Shipment {sid} not found")
    return o


# ---- Order helpers --------------------------------------------------------

def order_line_items(order_id: str):
    """Return LineItems for a given order in creation order."""
    return sorted(
        (li for li in db.line_items.values() if li["order_id"] == order_id),
        key=lambda x: (x["created_at"], x["id"]),
    )


def order_addressing_jobs(order_id: str):
    return sorted(
        (a for a in db.addressing_jobs.values() if a["order_id"] == order_id),
        key=lambda x: (x["created_at"], x["id"]),
    )


def order_work_orders(order_id: str):
    return sorted(
        (w for w in db.work_orders.values() if w["order_id"] == order_id),
        key=lambda x: (x["created_at"], x["id"]),
    )


def order_shipments(order_id: str):
    return sorted(
        (s for s in db.shipments.values() if s["order_id"] == order_id),
        key=lambda x: (x["created_at"], x["id"]),
    )


def order_active_proof(order_id: str):
    """Return the (single) active Proof for the given order, or None.

    An order gets exactly one Proof created at confirm time and it stays linked
    until terminal. We look it up via Order.proof_id.
    """
    o = db.orders.get(order_id)
    if not o:
        return None
    pid = o.get("proof_id")
    if pid is None:
        return None
    return db.proofs.get(pid)
