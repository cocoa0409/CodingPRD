"""Shared route helpers: existence lookups, ownership, list rendering."""
import db
from errors import err
from pagination import get_pagination, paginate
from response import success
from serialize import out_list


def find_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def ref_or_404(coll, rid):
    """FK body reference resolution -> ERR_REFERENCE_NOT_FOUND."""
    rec = coll.get(rid)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found")
    return rec


# ---- Ownership (PRD §2.1) --------------------------------------------------
def customer_owns(principal, owner_customer_id):
    """Customer actor must own the resource. ServiceManager/ComplianceOfficer bypass."""
    if principal.role == "Customer" and principal.user_id != owner_customer_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting customer does not own this resource")


def tech_is_assigned(principal, assigned_tech_id):
    """Technician actor must be the assigned/install tech -> ERR_NOT_ASSIGNED_TECH."""
    if principal.role == "Technician" and principal.user_id != assigned_tech_id:
        raise err("ERR_NOT_ASSIGNED_TECH", "Acting technician is not assigned to this resource")


# ---- List rendering --------------------------------------------------------
def render_list(records, sort=True):
    if sort:
        records = db.sort_by_creation(records)
    limit, offset = get_pagination()
    page, meta = paginate(records, limit, offset)
    return success(out_list(page), status=200, pagination=meta)
