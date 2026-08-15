"""Logical clock test-driving endpoint (PRD §2.5)."""
import services as svc
from db import store, touch
from middleware import require_roles
from response import ok_obj

PC = "ProgramCoordinator"


def register(app):

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        require_roles(PC)
        fs = svc.FieldSet()
        to_iso8601 = fs.req_dt("to_iso8601")
        fs.raise_if_bad("to_iso8601 must be a valid ISO 8601 timestamp")
        store.clock = to_iso8601
        # Setting the clock re-evaluates offer expiry: any offer still OFFERED
        # whose window_end has been reached transitions to EXPIRED, provided no
        # glean event exists for that offer.
        for offer in store.offers.values():
            if offer["status"] != "OFFERED":
                continue
            if store.clock < offer["window_end"]:
                continue
            if svc.events_of_offer(offer["id"]):
                continue
            offer["status"] = "EXPIRED"
            touch(offer)
        return ok_obj({}, 200)
