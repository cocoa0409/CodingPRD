"""Path and reference resolution (PRD 2.7).

Path identifiers are validated left to right: the project is resolved before any
child, and a missing identifier anywhere produces ERR_NOT_FOUND for the first one
that does not resolve. Body foreign keys that do not exist produce
ERR_REFERENCE_NOT_FOUND.
"""

from db import db
from errors import err


# --------------------------------------------------------------------------
# Path resolution (ERR_NOT_FOUND, priority 4)
# --------------------------------------------------------------------------
def get_project_or_404(project_id):
    p = db.projects.get(project_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Project not found.")
    return p


def get_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    return c


def get_turf_or_404(turf_id):
    t = db.turf_products.get(turf_id)
    if t is None:
        raise err("ERR_NOT_FOUND", "Turf product not found.")
    return t


def get_infill_or_404(infill_id):
    i = db.infill_products.get(infill_id)
    if i is None:
        raise err("ERR_NOT_FOUND", "Infill product not found.")
    return i


def get_crew_or_404(crew_id):
    c = db.crews.get(crew_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Crew not found.")
    return c


def get_child_or_404(collection, child_id, project_id, label):
    """Resolve a project-scoped child by id and confirm it belongs to the
    project named in the path. A child that exists but belongs to another
    project is treated as not found under this path (ERR_NOT_FOUND)."""
    rec = collection.get(child_id)
    if rec is None or rec.get("project_id") != project_id:
        raise err("ERR_NOT_FOUND", f"{label} not found.")
    return rec


def get_payment_or_404(payment_id):
    p = db.payments.get(payment_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Payment not found.")
    return p


# --------------------------------------------------------------------------
# Reference resolution (ERR_REFERENCE_NOT_FOUND, priority 5)
# --------------------------------------------------------------------------
def ref_turf_or_404(turf_id):
    t = db.turf_products.get(turf_id)
    if t is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced turf product does not exist.")
    return t


def ref_infill_or_404(infill_id):
    i = db.infill_products.get(infill_id)
    if i is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced infill product does not exist.")
    return i


def ref_site_measure_or_404(measure_id, project_id):
    m = db.site_measures.get(measure_id)
    if m is None or m.get("project_id") != project_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced site measure does not exist.")
    return m


def ref_design_or_404(design_id, project_id):
    d = db.design_layouts.get(design_id)
    if d is None or d.get("project_id") != project_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced design layout does not exist.")
    return d


def ref_scope_or_404(scope_id, project_id):
    s = db.base_prep_scopes.get(scope_id)
    if s is None or s.get("project_id") != project_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced base prep scope does not exist.")
    return s


def ref_crew_or_404(crew_id):
    c = db.crews.get(crew_id)
    if c is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced crew does not exist.")
    return c


def ref_warranty_or_404(warranty_id, project_id):
    w = db.warranty_plans.get(warranty_id)
    if w is None or w.get("project_id") != project_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced warranty plan does not exist.")
    return w
