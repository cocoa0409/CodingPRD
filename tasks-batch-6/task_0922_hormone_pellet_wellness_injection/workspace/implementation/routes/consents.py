"""Versioned consent signing and reads (PRD 3.2)."""
import access
import cascades
import config
import envelope
import reqctx
import serializers
import store
from reqctx import endpoint, field

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
    config.ROLE_NURSE_INJECTOR, config.ROLE_COMPLIANCE_OFFICER, config.ROLE_PATIENT,
]


def register(app):
    @app.route("/clinic/consents", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN, config.ROLE_PATIENT],
        specs=[
            field("patient_id", "id", True),
            field("hormone_type", "enum", True, members=config.HORMONE_TYPES),
            field("protocol_version", "integer", True),
            field("consented_max_dose_mg", "number", True),
        ],
    )
    def sign_consent(ctx):
        resolved = access.resolve_fks(ctx, ("patient_id",))
        patient = resolved["patient_id"]
        access.ownership(ctx, patient_id=patient["id"])

        hormone = ctx.get("hormone_type")
        prior = [
            row for row in store.where("ConsentRecord", patient_id=patient["id"])
            if row["hormone_type"] == hormone
        ]
        cascades.supersede_consents(prior)
        row = store.create("ConsentRecord", {
            "patient_id": patient["id"],
            "hormone_type": hormone,
            "protocol_version": ctx.get("protocol_version"),
            "consented_max_dose_mg": ctx.get("consented_max_dose_mg"),
            "signed_at": store.now(),
            "status": "ACTIVE",
        })
        return envelope.ok(serializers.consent(row), 201)

    @app.route("/clinic/consents/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_consent(ctx, id):
        row = access.path_row("ConsentRecord", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.consent(row))

    @app.route("/clinic/consents", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("hormone_type", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_consents(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("ConsentRecord"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "hormone_type": "hormone_type",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.consent(r) for r in window], 200, block)
