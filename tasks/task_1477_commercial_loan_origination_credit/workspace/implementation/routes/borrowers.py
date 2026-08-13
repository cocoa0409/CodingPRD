"""Borrowers: creation, listing, amendment. Exposure counters are derived."""
import re

from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch
from errors import raise_err, ERR_VALIDATION
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list
from services import exposure
from validation import get_body, req_str, opt_str, opt_bool, opt_enum, req_date, parse_date_str

bp = Blueprint("borrowers", __name__)

_NAICS_RE = re.compile(r'^\d{6}$')
BORROWER_STATUSES = {"ACTIVE", "SUSPENDED", "EXITED"}


def _check_naics(value):
    if not _NAICS_RE.match(value):
        raise_err(ERR_VALIDATION, "Field 'naics_code' must be a 6-digit NAICS code.")


@bp.post("/credit/borrowers")
def create_borrower():
    require_roles("RelationshipManager")
    body = get_body()
    legal_name = req_str(body, "legal_name")
    naics_code = req_str(body, "naics_code")
    _check_naics(naics_code)
    relationship_since = req_date(body, "relationship_since")
    is_reg_o_insider = opt_bool(body, "is_reg_o_insider", False)

    borrower = new_entity()
    borrower.update({
        'legal_name': legal_name,
        'naics_code': naics_code,
        'is_reg_o_insider': is_reg_o_insider,
        'relationship_since': relationship_since,
        'status': 'ACTIVE',
    })
    STORE.borrowers[borrower['id']] = borrower
    return success_object(serialize.borrower(borrower), status=201)


@bp.get("/credit/borrowers")
def list_borrowers():
    require_roles(*ALL_ROLES)
    items = list(STORE.borrowers.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b['status'] == status]
    return render_list(items, serialize.borrower)


@bp.get("/credit/borrowers/<bid>")
def get_borrower(bid):
    require_roles(*ALL_ROLES)
    borrower = get_or_404(STORE.borrowers, bid, "Borrower")
    return success_object(serialize.borrower(borrower))


@bp.get("/credit/borrowers/<bid>/loan-applications")
def borrower_applications(bid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.borrowers, bid, "Borrower")
    return render_list(exposure.applications_of_borrower(bid), serialize.loan_application)


@bp.patch("/credit/borrowers/<bid>")
def update_borrower(bid):
    require_roles("RelationshipManager")
    borrower = get_or_404(STORE.borrowers, bid, "Borrower")
    body = get_body()

    legal_name = opt_str(body, "legal_name")
    naics_code = opt_str(body, "naics_code")
    if naics_code is not None:
        _check_naics(naics_code)
    relationship_since = None
    if 'relationship_since' in body and body['relationship_since'] is not None:
        relationship_since = parse_date_str(body['relationship_since'], 'relationship_since')
    is_reg_o_insider = opt_bool(body, "is_reg_o_insider")
    status = opt_enum(body, "status", BORROWER_STATUSES)
    # SUSPENDED is system-driven (covenant breach); never settable via PATCH.
    if status == "SUSPENDED":
        raise_err(ERR_VALIDATION,
                  "Borrower status may only be set manually between ACTIVE and EXITED; SUSPENDED is system-driven.")

    if legal_name is not None:
        borrower['legal_name'] = legal_name
    if naics_code is not None:
        borrower['naics_code'] = naics_code
    if relationship_since is not None:
        borrower['relationship_since'] = relationship_since
    if is_reg_o_insider is not None:
        borrower['is_reg_o_insider'] = is_reg_o_insider
    if status is not None:
        borrower['status'] = status
    touch(borrower)
    return success_object(serialize.borrower(borrower))
