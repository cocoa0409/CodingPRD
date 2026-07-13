from core import (store, authorize, get_body, require_string, respond_object,
                  base_common, touch, serialize)
from lookups import get_establishment
from services import refresh_est_values, void_active_seals, ApiError, compute_balance


def register(app):

    @app.route("/establishments", methods=["POST"])
    def create_establishment():
        authorize(["ProgramAdmin"])
        body = get_body(optional=False)
        name = require_string(body, "name")
        jurisdiction = require_string(body, "jurisdiction")
        est = base_common("Establishment")
        est.update({
            "name": name,
            "jurisdiction": jurisdiction,
            "status": "ACTIVE",
            "balance_due_cents": 0,
            "sealed_device_count": 0,
        })
        store.establishments[est["id"]] = est
        return respond_object(serialize(est), 201)

    @app.route("/establishments/<eid>", methods=["GET"])
    def get_establishment_route(eid):
        authorize(["ProgramAdmin", "Establishment", "Inspector"])
        est = get_establishment(eid)
        refresh_est_values(est)  # read-time consistency (no version bump)
        return respond_object(serialize(est), 200)

    @app.route("/establishments/<eid>/suspend", methods=["POST"])
    def suspend_establishment(eid):
        authorize(["ProgramAdmin"])
        get_body(optional=True)  # reason? ignored
        est = get_establishment(eid)
        if compute_balance(est["id"]) <= 0:
            raise ApiError("ERR_SUSPEND_REQUIRES_BALANCE",
                           "Suspension requires an outstanding balance")
        est["status"] = "SUSPENDED"
        # cascade: SEALED devices -> OUT_OF_SERVICE; their ACTIVE seals -> VOIDED
        for dev in store.devices.values():
            if dev["establishment_id"] == est["id"] and dev["status"] == "SEALED":
                dev["status"] = "OUT_OF_SERVICE"
                void_active_seals(dev["id"])
                touch(dev)
        refresh_est_values(est)
        touch(est)
        return respond_object(serialize(est), 200)

    @app.route("/establishments/<eid>/reinstate", methods=["POST"])
    def reinstate_establishment(eid):
        authorize(["ProgramAdmin"])
        get_body(optional=True)
        est = get_establishment(eid)
        if compute_balance(est["id"]) != 0:
            raise ApiError("ERR_OUTSTANDING_BALANCE",
                           "Reinstatement requires a zero balance")
        est["status"] = "ACTIVE"
        refresh_est_values(est)
        touch(est)
        return respond_object(serialize(est), 200)
