"""TaxReturn endpoints (PRD §3.3, §3.4, §3.5)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from models import make_return, return_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_office, get_client, get_preparer,
                           get_return, paginate, page_slice)
from constants import (RETURN_KINDS, COMPLEXITY_BANDS, SCHEDULE_SET, RETURN_CLOSED_STATES)
from services.counters import (recompute_office_open_return_count,
                               recompute_preparer_assigned_open_returns)
from services import returns as ret_svc

bp = Blueprint("returns", __name__)


@bp.post("/returns")
def open_return():
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    body = get_json_body()

    office_id = body.get("office_id")
    client_id = body.get("client_id")
    tax_year = body.get("tax_year")
    if not isinstance(office_id, str) or not office_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "office_id is required")
    if not isinstance(client_id, str) or not client_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "client_id is required")
    # body FK existence (404) before remaining well-formedness
    get_office(office_id)
    get_client(client_id)

    amends_return_id = body.get("amends_return_id")
    if amends_return_id is not None:
        if not isinstance(amends_return_id, str) or not amends_return_id:
            raise errors.err(errors.ERR_INVALID_REQUEST, "amends_return_id must be a string id")
        get_return(amends_return_id)

    if not isinstance(tax_year, int) or isinstance(tax_year, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "tax_year must be an integer")

    return_kind = body.get("return_kind", "ORIGINAL")
    if return_kind not in RETURN_KINDS:
        raise errors.err(errors.ERR_INVALID_REQUEST, "return_kind is invalid")

    complexity_band = body.get("complexity_band", "SIMPLE")
    if complexity_band not in COMPLEXITY_BANDS:
        raise errors.err(errors.ERR_INVALID_REQUEST, "complexity_band is invalid")

    schedules = body.get("schedules", [])
    if not isinstance(schedules, list) or any(s not in SCHEDULE_SET for s in schedules):
        raise errors.err(errors.ERR_INVALID_REQUEST, "schedules must be a subset of {A,B,C,D,E,EIC}")

    state_return_count = body.get("state_return_count", 0)
    if not isinstance(state_return_count, int) or isinstance(state_return_count, bool) or state_return_count < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "state_return_count must be a non-negative integer")

    expected_refund_cents = body.get("expected_refund_cents", 0)
    if not isinstance(expected_refund_cents, int) or isinstance(expected_refund_cents, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_refund_cents must be an integer")

    # Duplicate-taxpayer guard (priority 12): no two non-amended returns in the
    # same office sharing client_id and tax_year. AMENDED_1040X is exempt.
    if return_kind != "AMENDED_1040X":
        for r in db.returns.values():
            if (r["office_id"] == office_id and r["client_id"] == client_id
                    and r["tax_year"] == tax_year
                    and r["return_kind"] != "AMENDED_1040X"):
                raise errors.err(errors.ERR_DUPLICATE_RETURN,
                                 "A non-amended return already exists for this client and tax year")

    ret = make_return(office_id, client_id, tax_year, return_kind, complexity_band,
                      schedules, state_return_count, expected_refund_cents,
                      amends_return_id)
    # Opening increments office open_return_count by one (recompute is equivalent).
    recompute_office_open_return_count(office_id)
    return object_response(return_dict(ret), 201)


@bp.get("/returns/<return_id>")
def get_return_ep(return_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer", "BankProductOfficer"})
    ret = get_return(return_id)
    return object_response(return_dict(ret), 200)


@bp.get("/returns")
def list_returns():
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer", "BankProductOfficer"})
    limit, offset = paginate()

    office_id = request.args.get("office_id")
    client_id = request.args.get("client_id")
    preparer_id = request.args.get("preparer_id")
    amends_return_id = request.args.get("amends_return_id")
    items = list(db.returns.values())
    if office_id is not None:
        items = [r for r in items if r["office_id"] == office_id]
    if client_id is not None:
        items = [r for r in items if r["client_id"] == client_id]
    if preparer_id is not None:
        items = [r for r in items if r.get("preparer_id") == preparer_id]
    if amends_return_id is not None:
        items = [r for r in items if r.get("amends_return_id") == amends_return_id]

    page, total = page_slice(items, limit, offset)
    return array_response([return_dict(r) for r in page], limit, offset, total, 200)


@bp.post("/returns/<return_id>/assign")
def assign_return(return_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager", "TaxPreparer"})
    ret = get_return(return_id)
    body = get_json_body()

    preparer_id = body.get("preparer_id")
    if not isinstance(preparer_id, str) or not preparer_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "preparer_id is required")
    prep = get_preparer(preparer_id)

    # Capacity check (priority 13): assignment must not push assigned_open_returns
    # above max_open_returns. This return is open (counts toward the new total).
    counts_now = sum(
        1 for r in db.returns.values()
        if r.get("preparer_id") == preparer_id and r["status"] not in RETURN_CLOSED_STATES
    )
    # if this return is already assigned to this preparer it's already counted
    already_this = (ret.get("preparer_id") == preparer_id
                    and ret["status"] not in RETURN_CLOSED_STATES)
    prospective = counts_now if already_this else counts_now + (
        1 if ret["status"] not in RETURN_CLOSED_STATES else 0)
    if prospective > prep["max_open_returns"]:
        raise errors.err(errors.ERR_PREPARER_AT_CAPACITY, "Preparer is at capacity")

    prev_preparer = ret.get("preparer_id")
    ret["preparer_id"] = preparer_id
    touch(ret)
    recompute_preparer_assigned_open_returns(preparer_id)
    if prev_preparer is not None and prev_preparer != preparer_id:
        recompute_preparer_assigned_open_returns(prev_preparer)
    return object_response(return_dict(ret), 200)


@bp.post("/returns/<return_id>/transition")
def transition_return_ep(return_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    ret = get_return(return_id)
    body = get_json_body()

    to = body.get("to")
    if not isinstance(to, str) or not to:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to is required")

    ret_svc.transition_return(ret, to)
    return object_response(return_dict(ret), 200)


@bp.post("/returns/<return_id>/efile")
def efile_ep(return_id):
    _, role = get_identity()
    require_role(role, {"TaxPreparer"})
    ret = get_return(return_id)
    ret_svc.efile(ret)
    return object_response(return_dict(ret), 200)


@bp.post("/returns/<return_id>/efile-ack")
def efile_ack_ep(return_id):
    _, role = get_identity()
    require_role(role, {"TaxPreparer"})
    ret = get_return(return_id)
    body = get_json_body()

    ack_status = body.get("ack_status")
    if ack_status not in ("ACCEPTED", "REJECTED"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "ack_status must be ACCEPTED or REJECTED")
    reject_code = body.get("reject_code")

    ret_svc.efile_ack(ret, ack_status, reject_code)
    return object_response(return_dict(ret), 200)
