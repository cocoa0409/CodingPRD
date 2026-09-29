"""Compliance sweep, authority-wide summary and the logical clock."""
import services as svc
from clock import iso
from db import db
from middleware import STAFF_ROLES, authenticate
from response import object_response
from validation import field_datetime, get_body, query_int


def register(app):
    @app.route("/land-bank/compliance-sweeps", methods=["POST"])
    def compliance_sweep():
        authenticate("InventoryManager")
        result = svc.run_compliance_sweep()
        result["swept_at"] = iso(result["swept_at"])
        return object_response(result)

    @app.route("/land-bank/inventory-summary", methods=["GET"])
    def inventory_summary():
        authenticate(*STAFF_ROLES)
        ward = query_int("situs_ward", 1, 9)
        return object_response(svc.inventory_summary(ward))

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        authenticate(*STAFF_ROLES)
        body = get_body()
        target = field_datetime(body, "to_iso8601")
        db.clock = target
        return object_response({"current_utc": iso(target)})
