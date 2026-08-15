"""Transport dispatches (PRD 3.7): reads and the DISPATCHED-only cancel that
reverts the case TRANSPORT_ARRANGED -> ACCEPTED."""

from flask import Blueprint

from core import domain as D
from core.envelope import object_response, paginate, filter_exact
from core.errors import fail
from core.store import db, bump

bp = Blueprint("transport", __name__)


@bp.get("/transport-dispatches")
def list_dispatches():
    rows = db.ordered("transport_dispatches")
    rows = filter_exact(rows, "transfer_case_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, D.serialize_dispatch)


@bp.get("/transport-dispatches/<id>")
def get_dispatch(id):
    row = db.transport_dispatches.get(id)
    if row is None:
        fail("ERR_DISPATCH_NOT_FOUND", "TransportDispatch id does not exist.", 404)
    return object_response(D.serialize_dispatch(row), 200)


@bp.post("/transport-dispatches/<id>/cancel")
def cancel_dispatch(id):
    dispatch = db.transport_dispatches.get(id)
    if dispatch is None:
        fail("ERR_DISPATCH_NOT_FOUND", "TransportDispatch id does not exist.", 404)
    if dispatch["status"] != "DISPATCHED":
        fail("ERR_DISPATCH_NOT_CANCELLABLE",
             "Only a DISPATCHED transport can be cancelled.", 409)
    case = D.get_case(dispatch["transfer_case_id"])
    if case is None or case["status"] != "TRANSPORT_ARRANGED":
        fail("ERR_INVALID_STATE", "The case is not TRANSPORT_ARRANGED.", 409)
    dispatch["status"] = "CANCELLED"
    bump(dispatch)
    case["status"] = "ACCEPTED"
    bump(case)
    return object_response(D.serialize_dispatch(dispatch), 200)
