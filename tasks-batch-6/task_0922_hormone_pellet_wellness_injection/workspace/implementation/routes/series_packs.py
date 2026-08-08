"""Prepaid injection series packs (PRD 3.7)."""
import access
import calc
import config
import envelope
import gates
import reqctx
import serializers
import store
import util
from reqctx import endpoint, field

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
    config.ROLE_NURSE_INJECTOR, config.ROLE_PATIENT,
]


def register(app):
    @app.route("/clinic/series-packs", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PATIENT],
        specs=[
            field("patient_id", "id", True),
            field("series_type", "enum", True, members=config.INJECTION_TYPES),
        ],
    )
    def sell_pack(ctx):
        resolved = access.resolve_fks(ctx, ("patient_id",))
        patient = resolved["patient_id"]
        access.ownership(ctx, patient_id=patient["id"])

        series_type = ctx.get("series_type")
        price, per_visit = calc.series_pack_price_cents(series_type)
        purchased_at = store.now()
        row = store.create("SeriesPack", {
            "patient_id": patient["id"],
            "series_type": series_type,
            "purchased_visits": config.SERIES_PACK_VISITS,
            "remaining_visits": config.SERIES_PACK_VISITS,
            "redeemed_visits": 0,
            "refunded_visits": 0,
            "forfeited_visits": 0,
            "price_cents": price,
            "per_visit_value_cents": per_visit,
            "purchased_at": purchased_at,
            "expires_at": util.add_days(purchased_at, config.SERIES_VALIDITY_DAYS),
            "refunded_cents": 0,
            "status": "ACTIVE",
        })
        return envelope.ok(serializers.series_pack(row), 201)

    @app.route("/clinic/series-packs/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_pack(ctx, id):
        row = access.path_row("SeriesPack", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.series_pack(row))

    @app.route("/clinic/series-packs", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("series_type", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_packs(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("SeriesPack"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "series_type": "series_type",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.series_pack(r) for r in window], 200, block)

    @app.route("/clinic/series-packs/<id>/refund", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK],
        specs=[field("reason", "text", False)],
    )
    def refund_pack(ctx, id):
        row = access.path_row("SeriesPack", id)
        gates.state_gate(row, "SeriesPack.status", ("ACTIVE",))
        row["refunded_cents"] = calc.series_refund_cents(row)
        row["refunded_visits"] += row["remaining_visits"]
        row["remaining_visits"] = 0
        row["status"] = "REFUNDED"
        store.touch(row)
        return envelope.ok(serializers.series_pack(row))
