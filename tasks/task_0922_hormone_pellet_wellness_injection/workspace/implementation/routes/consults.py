"""Consults and the discrete pellet plan (PRD 3.3)."""
import access
import calc
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
    @app.route("/clinic/consults", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN],
        specs=[
            field("patient_id", "id", True),
            field("physician_id", "id", True),
            field("hormone_type", "enum", True, members=config.HORMONE_TYPES),
            field("prescribed_dose_mg", "number", True, gt=0),
            field("symptom_score", "integer", True, gte=0, lte=100),
            field("indication", "text", True),
        ],
    )
    def create_consult(ctx):
        resolved = access.resolve_fks(ctx, ("patient_id", "physician_id"))
        access.require_physician_class(resolved)
        access.ownership(ctx, patient_id=resolved["patient_id"]["id"])

        hormone = ctx.get("hormone_type")
        plan = calc.pellet_count_from_dose(hormone, ctx.get("prescribed_dose_mg"))
        row = store.create("Consult", {
            "patient_id": ctx.get("patient_id"),
            "physician_id": ctx.get("physician_id"),
            "hormone_type": hormone,
            "prescribed_dose_mg": ctx.get("prescribed_dose_mg"),
            "symptom_score": ctx.get("symptom_score"),
            "indication": ctx.get("indication"),
            "planned_large_count": plan["planned_large_count"],
            "planned_small_count": plan["planned_small_count"],
            "planned_total_mg": plan["planned_total_mg"],
            "planned_pellet_count": plan["planned_pellet_count"],
        })
        return envelope.ok(serializers.consult(row), 201)

    @app.route("/clinic/consults/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_consult(ctx, id):
        row = access.path_row("Consult", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.consult(row))

    @app.route("/clinic/consults", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("physician_id", "filter", False),
        ],
    )
    def list_consults(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("Consult"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "physician_id": "physician_id",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.consult(r) for r in window], 200, block)
