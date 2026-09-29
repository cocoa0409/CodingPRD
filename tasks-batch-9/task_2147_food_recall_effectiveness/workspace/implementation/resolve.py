"""Rejection-ladder resolution helpers (§2.6 rungs 3-7 and 11)."""
from core import ROLE_FIRM, db, err
from domain import apply_metrics


def get_firm(firm_id):
    firm = db.firms.get(firm_id) if isinstance(firm_id, str) else None
    if firm is None:
        err("ERR_FIRM_NOT_FOUND", "Firm %s does not exist" % firm_id)
    return firm


def get_recall(recall_id):
    recall = db.recalls.get(recall_id) if isinstance(recall_id, str) else None
    if recall is None:
        err("ERR_RECALL_NOT_FOUND", "Recall %s does not exist" % recall_id)
    return recall


def get_consignee(consignee_id):
    consignee = db.consignees.get(consignee_id) if isinstance(consignee_id, str) else None
    if consignee is None:
        err("ERR_CONSIGNEE_NOT_FOUND", "Consignee %s does not exist" % consignee_id)
    return consignee


def get_consignee_in_recall(consignee_id, recall):
    consignee = db.consignees.get(consignee_id) if isinstance(consignee_id, str) else None
    if consignee is None or consignee.get("recall_id") != recall["id"]:
        err("ERR_CONSIGNEE_NOT_FOUND",
            "Consignee %s does not exist on this recall" % consignee_id)
    return consignee


def get_sub(collection, sub_id):
    row = collection.get(sub_id) if isinstance(sub_id, str) else None
    if row is None:
        err("ERR_SUBRESOURCE_NOT_FOUND", "Resource %s does not exist" % sub_id)
    return row


def sub_recall(row):
    return db.recalls.get(row.get("recall_id"))


def firm_scope(role, user_id, recall):
    """Rung 7 — FirmRecallOfficer tenant scoping."""
    if recall is None:
        return
    if role == ROLE_FIRM and recall.get("firm_id") != user_id:
        err("ERR_FIRM_SCOPE_VIOLATION",
            "This recall belongs to another firm")


def recall_state(recall, allowed):
    """Rung 11."""
    if recall.get("status") not in allowed:
        err("ERR_INVALID_RECALL_STATE",
            "Recall status %s does not permit this operation" % recall.get("status"))


def not_terminated(recall):
    if recall.get("status") == "TERMINATED":
        err("ERR_INVALID_RECALL_STATE", "The recall has terminated")


def sync(recall):
    """Recompute every derived aggregate on the recall hub."""
    apply_metrics(recall)
    return recall
