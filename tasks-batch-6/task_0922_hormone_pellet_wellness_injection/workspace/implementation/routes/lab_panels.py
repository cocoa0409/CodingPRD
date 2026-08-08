"""Laboratory panels: two rulers on one number, plus the critical divert."""
import access
import calc
import config
import envelope
import gates
import reqctx
import serializers
import store
from reqctx import endpoint, field

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
    config.ROLE_NURSE_INJECTOR, config.ROLE_COMPLIANCE_OFFICER, config.ROLE_PATIENT,
]


def register(app):
    @app.route("/clinic/lab-panels", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN, config.ROLE_NURSE_INJECTOR],
        specs=[
            field("patient_id", "id", True),
            field("ordered_by_provider_id", "id", True),
            field("analyte", "enum", True, members=config.ANALYTES),
            field("value", "number", True),
            field("drawn_at", "datetime", True),
            field("is_trough_draw", "boolean", False, default=False),
        ],
    )
    def create_lab_panel(ctx):
        resolved = access.resolve_fks(ctx, ("patient_id", "ordered_by_provider_id"))
        patient = resolved["patient_id"]
        access.ownership(ctx, patient_id=patient["id"])

        analyte = ctx.get("analyte")
        value = ctx.get("value")
        bands = calc.lab_band_classification(analyte, value)

        # A newer panel supersedes prior RECORDED or ACKNOWLEDGED panels of the
        # same patient and analyte.  CRITICAL_FLAGGED panels are never displaced.
        for prior in store.where("LabPanel", patient_id=patient["id"], analyte=analyte):
            if prior["status"] in ("RECORDED", "ACKNOWLEDGED"):
                prior["status"] = "SUPERSEDED"
                store.touch(prior)

        row = store.create("LabPanel", {
            "patient_id": patient["id"],
            "ordered_by_provider_id": ctx.get("ordered_by_provider_id"),
            "acknowledged_by_provider_id": None,
            "analyte": analyte,
            "value": value,
            "unit": bands["unit"],
            "drawn_at": ctx.get("drawn_at"),
            "resulted_at": store.now(),
            "is_trough_draw": ctx.get("is_trough_draw", False),
            "lab_reference_band": bands["lab_reference_band"],
            "clinic_optimal_band": bands["clinic_optimal_band"],
            "critical_flag": bands["critical_flag"],
            "status": "CRITICAL_FLAGGED" if bands["critical_flag"] else "RECORDED",
        })
        return envelope.ok(serializers.lab_panel(row), 201)

    @app.route("/clinic/lab-panels/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_lab_panel(ctx, id):
        row = access.path_row("LabPanel", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.lab_panel(row))

    @app.route("/clinic/lab-panels", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("ordered_by_provider_id", "filter", False),
            field("acknowledged_by_provider_id", "filter", False),
            field("analyte", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_lab_panels(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("LabPanel"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "ordered_by_provider_id": "ordered_by_provider_id",
            "acknowledged_by_provider_id": "acknowledged_by_provider_id",
            "analyte": "analyte",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.lab_panel(r) for r in window], 200, block)

    @app.route("/clinic/lab-panels/<id>/acknowledge-critical", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN],
        specs=[field("note", "text", False)],
    )
    def acknowledge_critical(ctx, id):
        row = access.path_row("LabPanel", id)
        access.ownership(ctx)
        gates.state_gate(row, "LabPanel.status", ("CRITICAL_FLAGGED",))
        row["status"] = "ACKNOWLEDGED"
        row["acknowledged_by_provider_id"] = ctx.user_id
        store.touch(row)
        return envelope.ok(serializers.lab_panel(row))
