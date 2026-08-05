"""Standing orders: the delegation instrument (PRD 3.8)."""
import access
import cascades
import config
import envelope
import gates
import reqctx
import serializers
import store
import util
from errors import ApiError
from reqctx import endpoint, field

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
    config.ROLE_NURSE_INJECTOR, config.ROLE_COMPLIANCE_OFFICER,
]


def register(app):
    @app.route("/clinic/standing-orders", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN],
        specs=[
            field("physician_id", "id", True),
            field("scope_hormone_types", "enum_array", True, members=config.HORMONE_TYPES),
            field("scope_injection_types", "enum_array", True, members=config.INJECTION_TYPES),
            field("max_dose_mg", "number", True, gt=0),
            field("valid_from", "datetime", True),
            field("valid_until", "datetime", True),
        ],
    )
    def create_standing_order(ctx):
        valid_from = ctx.get("valid_from")
        valid_until = ctx.get("valid_until")
        if not valid_until > valid_from:
            raise ApiError("ERR_VALIDATION", "valid_until must be strictly after valid_from.")
        if util.days_between(valid_from, valid_until) > config.STANDING_ORDER_MAX_VALIDITY_DAYS:
            raise ApiError(
                "ERR_VALIDATION",
                "valid_until may be no more than %d days after valid_from."
                % config.STANDING_ORDER_MAX_VALIDITY_DAYS,
            )
        resolved = access.resolve_fks(ctx, ("physician_id",))
        access.require_physician_class(resolved)
        access.ownership(ctx)

        row = store.create("StandingOrder", {
            "physician_id": ctx.get("physician_id"),
            "scope_hormone_types": list(ctx.get("scope_hormone_types") or []),
            "scope_injection_types": list(ctx.get("scope_injection_types") or []),
            "max_dose_mg": ctx.get("max_dose_mg"),
            "valid_from": valid_from,
            "valid_until": valid_until,
            "status": "ACTIVE",
            "suspended_reason": None,
        })
        return envelope.ok(serializers.standing_order(row), 201)

    @app.route("/clinic/standing-orders/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_standing_order(ctx, id):
        row = access.path_row("StandingOrder", id)
        access.ownership(ctx)
        return envelope.ok(serializers.standing_order(row))

    @app.route("/clinic/standing-orders", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("physician_id", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_standing_orders(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("StandingOrder"))
        rows = reqctx.apply_filters(ctx, rows, {
            "physician_id": "physician_id",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.standing_order(r) for r in window], 200, block)

    @app.route("/clinic/standing-orders/<id>/revoke", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN],
        specs=[field("reason", "text", False)],
    )
    def revoke_standing_order(ctx, id):
        row = access.path_row("StandingOrder", id)
        access.acting_provider(ctx)
        access.standing_order_author(ctx, row)
        gates.state_gate(row, "StandingOrder.status", ("ACTIVE", "SUSPENDED"))
        row["status"] = "REVOKED"
        store.touch(row)
        return envelope.ok(serializers.standing_order(row))

    @app.route("/clinic/standing-orders/<id>/reinstate", methods=["POST"])
    @endpoint(roles=[config.ROLE_PHYSICIAN])
    def reinstate_standing_order(ctx, id):
        row = access.path_row("StandingOrder", id)
        access.acting_provider(ctx)
        access.standing_order_author(ctx, row)
        gates.state_gate(row, "StandingOrder.status", ("SUSPENDED",))
        # Reinstatement requires every adverse event naming this order to be CLOSED.
        for event in store.where("AdverseEvent", standing_order_id=row["id"]):
            if event["status"] != "CLOSED":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Every adverse event referencing this order must be CLOSED first.",
                )
        row["status"] = "ACTIVE"
        row["suspended_reason"] = None
        store.touch(row)
        for proc in store.where("Procedure", standing_order_id=row["id"]):
            if (
                proc["status"] == "SUPPLY_HOLD"
                and proc.get("hold_reason") == "STANDING_ORDER_SUSPENDED"
            ):
                cascades.unfreeze_procedure(proc)
        return envelope.ok(serializers.standing_order(row))
