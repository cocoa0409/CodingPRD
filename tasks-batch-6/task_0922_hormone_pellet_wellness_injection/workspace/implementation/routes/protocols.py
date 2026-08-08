"""Protocol publication and the four-hop de-consent cascade (PRD 3.2)."""
import access
import cascades
import config
import envelope
import reqctx
import serializers
import store
from reqctx import endpoint, field

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_PHYSICIAN, config.ROLE_NURSE_INJECTOR,
    config.ROLE_FRONT_DESK, config.ROLE_COMPLIANCE_OFFICER, config.ROLE_PATIENT,
]


def register(app):
    @app.route("/clinic/protocols", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN, config.ROLE_CLINIC_ADMIN],
        specs=[
            field("hormone_type", "enum", True, members=config.HORMONE_TYPES),
            field("title", "string", True),
            field("published_by_provider_id", "id", True),
        ],
    )
    def publish_protocol(ctx):
        resolved = access.resolve_fks(ctx, ("published_by_provider_id",))
        access.require_physician_class(resolved)
        access.ownership(ctx)

        hormone = ctx.get("hormone_type")
        row = store.create("Protocol", {
            "hormone_type": hormone,
            "protocol_version": cascades.highest_protocol_version(hormone) + 1,
            "title": ctx.get("title"),
            "published_by_provider_id": ctx.get("published_by_provider_id"),
            "effective_at": store.now(),
        })
        cascades.protocol_publication_cascade(hormone)
        return envelope.ok(serializers.protocol(row), 201)

    @app.route("/clinic/protocols/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_protocol(ctx, id):
        row = access.path_row("Protocol", id)
        access.ownership(ctx)
        return envelope.ok(serializers.protocol(row))

    @app.route("/clinic/protocols", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("hormone_type", "filter", False),
            field("published_by_provider_id", "filter", False),
        ],
    )
    def list_protocols(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("Protocol"))
        rows = reqctx.apply_filters(ctx, rows, {
            "hormone_type": "hormone_type",
            "published_by_provider_id": "published_by_provider_id",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.protocol(r) for r in window], 200, block)
