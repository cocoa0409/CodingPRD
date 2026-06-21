"""Administrative clock control (PRD §2.10). POST /_clock/set"""

from flask import Blueprint

import errors
from db import LOCK
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body
from services import lookup
from services.common import parse_date, date_of, compute_outstanding_balance, touch
from services.serialize import public

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    body = get_json_body()

    with LOCK:
        employer_id = body.get("employer_id")
        if employer_id is None:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: employer_id")
        employer = lookup.get_employer(employer_id)

        to_raw = body.get("to_iso8601")
        if to_raw is None:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
        new_date = parse_date(to_raw)
        if new_date is None:
            raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid date")

        employer["current_date"] = to_raw

        # Overdue re-evaluation: ISSUED / PARTIALLY_PAID invoices whose due_date is
        # now before current_date flip to OVERDUE (paid_cents retained).
        from db import db
        for inv in db.invoices.values():
            if inv["employer_id"] != employer["id"]:
                continue
            if inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
                due = date_of(inv.get("due_date"))
                if due is not None and new_date > due:
                    inv["status"] = "OVERDUE"
                    touch(inv)

        # Recompute balance (OVERDUE still counts) and bump employer.version
        # exactly once — §2.10 requires the clock-set to increment the version
        # regardless of whether any invoice aged.
        employer["outstanding_balance_cents"] = compute_outstanding_balance(employer)
        touch(employer)

        return object_response(public(employer), 200)
