"""Waiving a breached covenant test (PRD 3.8)."""

from flask import Blueprint

from db import db, touch
from errors import ApiError
from middleware import CREDIT_OFFICER, require_auth
from response import ok
from routes.common import get_covenant_test
from serializers import covenant_test_out
from services import computed
from services.constants import OPEN_CALL_STATUSES
from services.states import reevaluate_restricted
from validation import body, v_string

bp = Blueprint("covenant_tests", __name__)


@bp.post("/covenant-tests/<test_id>/waive")
def waive_covenant_test(test_id):
    user_id, _role = require_auth([CREDIT_OFFICER])
    test = get_covenant_test(test_id)
    data = body()
    v_string(data, "reason", max_len=500)
    # priority 16
    if test["status"] != "BREACH":
        raise ApiError("ERR_COVENANT_TEST_NOT_BREACHED",
                       "Only a BREACH covenant test may be waived.")

    facility = db.facilities[test["facility_id"]]
    test["status"] = "WAIVED"
    test["waived_by_user_id"] = user_id
    touch(test)

    for call in computed.facility_margin_calls(facility["id"]):
        if call["trigger_reason"] != "COVENANT_BREACH":
            continue
        if call["status"] not in OPEN_CALL_STATUSES:
            continue
        call["status"] = "WAIVED"
        touch(call)

    touch(facility)
    reevaluate_restricted(facility)
    return ok(covenant_test_out(test))
