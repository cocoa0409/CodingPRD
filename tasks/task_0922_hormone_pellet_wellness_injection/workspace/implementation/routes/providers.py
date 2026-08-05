"""Clinician registration and reads."""
import access
import config
import envelope
import serializers
import store
from errors import ApiError
from reqctx import endpoint, field


def register(app):
    @app.route("/clinic/providers", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN],
        specs=[
            field("full_name", "string", True),
            field("provider_type", "enum", True, members=config.PROVIDER_TYPES),
            field("npi", "string", True),
            field("active", "boolean", False, default=True),
        ],
    )
    def create_provider(ctx):
        npi = ctx.get("npi")
        for row in store.all_rows("Provider"):
            if row["npi"] == npi:
                raise ApiError("ERR_VALIDATION", "npi must be unique across providers.")
        row = store.create("Provider", {
            "full_name": ctx.get("full_name"),
            "provider_type": ctx.get("provider_type"),
            "npi": npi,
            "active": ctx.get("active", True),
        })
        return envelope.ok(serializers.provider(row), 201)

    @app.route("/clinic/providers/<id>", methods=["GET"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
               config.ROLE_NURSE_INJECTOR, config.ROLE_COMPLIANCE_OFFICER],
    )
    def read_provider(ctx, id):
        row = access.path_row("Provider", id)
        access.ownership(ctx)
        return envelope.ok(serializers.provider(row))
