"""Pellet lots, release, the five-hop recall and the impact report."""
import access
import calc
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

LOT_READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_INVENTORY_MANAGER,
    config.ROLE_COMPLIANCE_OFFICER, config.ROLE_PHYSICIAN, config.ROLE_NURSE_INJECTOR,
]


def register(app):
    @app.route("/clinic/pellet-lots", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_INVENTORY_MANAGER],
        specs=[
            field("lot_code", "string", True),
            field("hormone_type", "enum", True, members=config.HORMONE_TYPES),
            field("strength_mg", "number", True),
            field("expiry_date", "datetime", True),
            field("qty_received", "integer", True, gt=0),
        ],
    )
    def create_lot(ctx):
        lot_code = ctx.get("lot_code")
        for row in store.all_rows("PelletLot"):
            if row["lot_code"] == lot_code:
                raise ApiError("ERR_VALIDATION", "lot_code must be unique across lots.")
        hormone = ctx.get("hormone_type")
        strength = ctx.get("strength_mg")
        # rung 29 -- the strength must be a rung of this hormone's ladder.
        ladder = [util.frac(v) for v in config.PELLET_LADDER[hormone]]
        if util.frac(strength) not in ladder:
            raise ApiError("ERR_LOT_NOT_ELIGIBLE")
        qty = ctx.get("qty_received")
        row = store.create("PelletLot", {
            "lot_code": lot_code,
            "hormone_type": hormone,
            "strength_mg": strength,
            "expiry_date": ctx.get("expiry_date"),
            "qty_received": qty,
            "qty_on_hand": qty,
            "qty_reserved": 0,
            "qty_consumed": 0,
            "qty_wasted": 0,
            "qty_returned": 0,
            "sterility_status": "QUARANTINED",
            "recall_severity": None,
            "recalled_at": None,
            "recall_reason": None,
        })
        return envelope.ok(serializers.pellet_lot(row), 201)

    @app.route("/clinic/pellet-lots/<id>", methods=["GET"])
    @endpoint(roles=LOT_READ_ROLES)
    def read_lot(ctx, id):
        row = access.path_row("PelletLot", id)
        access.ownership(ctx)
        return envelope.ok(serializers.pellet_lot(row))

    @app.route("/clinic/pellet-lots/<id>/release", methods=["POST"])
    @endpoint(roles=[config.ROLE_INVENTORY_MANAGER])
    def release_lot(ctx, id):
        row = access.path_row("PelletLot", id)
        gates.state_gate(row, "PelletLot.sterility_status", ("QUARANTINED",),
                         state_field="sterility_status")
        row["sterility_status"] = "RELEASED"
        store.touch(row)
        return envelope.ok(serializers.pellet_lot(row))

    @app.route("/clinic/pellet-lots/<id>/recall", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_INVENTORY_MANAGER, config.ROLE_COMPLIANCE_OFFICER],
        specs=[
            field("severity_class", "enum", True, members=config.RECALL_SEVERITY_CLASSES),
            field("recall_reason", "text", True),
        ],
    )
    def recall_lot(ctx, id):
        row = access.path_row("PelletLot", id)
        gates.state_gate(row, "PelletLot.sterility_status", ("RELEASED", "QUARANTINED"),
                         state_field="sterility_status")
        cascades.recall_lot_cascade(row, ctx.get("severity_class"), ctx.get("recall_reason"))
        return envelope.ok(serializers.pellet_lot(row))

    @app.route("/clinic/pellet-lots/<id>/recall-impact", methods=["GET"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN, config.ROLE_INVENTORY_MANAGER,
               config.ROLE_COMPLIANCE_OFFICER],
        specs=[
            field("variant", "enum", True, members=config.RECALL_IMPACT_VARIANTS),
            field("assume_severity", "enum", False, members=config.RECALL_SEVERITY_CLASSES),
        ],
    )
    def recall_impact(ctx, id):
        row = access.path_row("PelletLot", id)
        variant = ctx.get("variant")
        counts = calc.recall_impact_counts(row, variant, ctx.get("assume_severity"))
        data = {"lot_id": row["id"], "variant": variant}
        data.update(counts)
        return envelope.ok(data)

    @app.route("/clinic/pellet-lots/<id>/allocations", methods=["GET"])
    @endpoint(
        roles=LOT_READ_ROLES,
        paginated=True,
        specs=[field("status", "filter", False)],
    )
    def lot_allocations(ctx, id):
        row = access.path_row("PelletLot", id)
        access.ownership(ctx)
        rows = reqctx.order_rows(calc.allocations_of_lot(row["id"]))
        rows = reqctx.apply_filters(ctx, rows, {"status": "status"})
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.allocation(r) for r in window], 200, block)
