"""Path/FK resolution helpers honoring the existence-ordering of PRD §2.6.

- Path patient: ERR_PATIENT_NOT_FOUND (404)
- Path leaf resource: ERR_RESOURCE_NOT_FOUND (404)
- Body FK: ERR_REFERENCE_NOT_FOUND (404)
"""
import db
from errors import err


def get_patient_or_404(patient_id):
    p = db.patients.get(patient_id)
    if p is None:
        raise err("ERR_PATIENT_NOT_FOUND", "Patient not found")
    return p


def leaf_or_404(store, resource_id, parent_id=None, parent_field=None):
    """Resolve a nested leaf in `store`; optionally enforce parent ownership.

    Missing or wrong-parent leaf -> ERR_RESOURCE_NOT_FOUND.
    """
    rec = store.get(resource_id)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Resource not found")
    if parent_id is not None and parent_field is not None:
        if rec.get(parent_field) != parent_id:
            raise err("ERR_RESOURCE_NOT_FOUND", "Resource not found")
    return rec


def ref_or_404(store, resource_id):
    """Resolve a body FK -> ERR_REFERENCE_NOT_FOUND if absent."""
    rec = store.get(resource_id)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found")
    return rec
