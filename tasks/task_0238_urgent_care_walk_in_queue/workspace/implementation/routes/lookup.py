"""Path / FK resolution helpers (PRD §2.5)."""
from db import db
from errors import err

# Map collection name -> store dict
_STORES = {
    "clinic": "clinics",
    "exam_room": "exam_rooms",
    "provider": "providers",
    "queue_entry": "queue_entries",
    "patient": "patients",
    "coverage": "coverages",
    "visit": "visits",
    "charge": "charges",
    "occ_health_order": "occ_health_orders",
    "referral": "referrals",
    "discharge_instruction": "discharge_instructions",
}


def get_path(kind, ident):
    """Resolve a path-referenced resource or raise ERR_NOT_FOUND (404)."""
    store = getattr(db, _STORES[kind])
    rec = store.get(ident)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found" % kind)
    return rec


def get_fk(kind, ident):
    """Resolve a body FK reference or raise ERR_FK_NOT_FOUND (404)."""
    store = getattr(db, _STORES[kind])
    rec = store.get(ident)
    if rec is None:
        raise err("ERR_FK_NOT_FOUND", "%s reference not found" % kind)
    return rec
