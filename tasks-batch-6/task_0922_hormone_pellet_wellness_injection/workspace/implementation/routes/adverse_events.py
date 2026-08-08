"""Adverse events: severity routing, the severe cascade and reviews."""
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
    config.ROLE_CLINIC_ADMIN, config.ROLE_PHYSICIAN, config.ROLE_NURSE_INJECTOR,
    config.ROLE_COMPLIANCE_OFFICER, config.ROLE_PATIENT,
]


def register(app):
    @app.route("/clinic/adverse-events", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN, config.ROLE_NURSE_INJECTOR],
        specs=[
            field("patient_id", "id", True),
            field("reported_by_provider_id", "id", True),
            # SURVEILLANCE is system-generated only and is rejected at rung 5.
            field("severity", "enum", True, members=config.AE_INPUT_SEVERITIES),
            field("narrative", "text", True),
            field("onset_at", "datetime", True),
            field("procedure_id", "id", False),
            field("injection_visit_id", "id", False),
            field("lot_id", "id", False),
            field("standing_order_id", "id", False),
        ],
    )
    def file_event(ctx):
        resolved = access.resolve_fks(ctx, (
            "patient_id", "reported_by_provider_id", "standing_order_id", "lot_id",
            "procedure_id", "injection_visit_id",
        ))
        patient = resolved["patient_id"]
        access.ownership(ctx)

        severity = ctx.get("severity")
        now = store.now()
        if severity == "MODERATE":
            review_due_at = util.add_days(now, config.MODERATE_REVIEW_DUE_DAYS)
        elif severity == "SEVERE":
            review_due_at = util.add_hours(now, config.SEVERE_REVIEW_DUE_HOURS)
        else:
            review_due_at = None

        row = store.create("AdverseEvent", {
            "patient_id": patient["id"],
            "procedure_id": ctx.get("procedure_id"),
            "injection_visit_id": ctx.get("injection_visit_id"),
            "lot_id": ctx.get("lot_id"),
            "standing_order_id": ctx.get("standing_order_id"),
            "reported_by_provider_id": ctx.get("reported_by_provider_id"),
            "reviewed_by_provider_id": None,
            "severity": severity,
            "source": "CLINICAL_REPORT",
            "narrative": ctx.get("narrative"),
            "onset_at": ctx.get("onset_at"),
            "review_due_at": review_due_at,
            "disposition_note": None,
            "status": "OPEN",
        })

        if severity == "SEVERE":
            cascades.severe_adverse_event_cascade(
                patient, resolved.get("lot_id"), resolved.get("standing_order_id")
            )
        elif severity == "MODERATE":
            store.touch(patient)
        return envelope.ok(serializers.adverse_event(row), 201)

    @app.route("/clinic/adverse-events/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_event(ctx, id):
        row = access.path_row("AdverseEvent", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.adverse_event(row))

    @app.route("/clinic/adverse-events", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("procedure_id", "filter", False),
            field("injection_visit_id", "filter", False),
            field("lot_id", "filter", False),
            field("standing_order_id", "filter", False),
            field("reported_by_provider_id", "filter", False),
            field("reviewed_by_provider_id", "filter", False),
            field("severity", "filter", False),
            field("status", "filter", False),
            field("source", "filter", False),
        ],
    )
    def list_events(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("AdverseEvent"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "procedure_id": "procedure_id",
            "injection_visit_id": "injection_visit_id",
            "lot_id": "lot_id",
            "standing_order_id": "standing_order_id",
            "reported_by_provider_id": "reported_by_provider_id",
            "reviewed_by_provider_id": "reviewed_by_provider_id",
            "severity": "severity",
            "status": "status",
            "source": "source",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.adverse_event(r) for r in window], 200, block)

    @app.route("/clinic/adverse-events/<id>/review", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN],
        specs=[
            field("disposition", "enum", True, members=config.AE_DISPOSITIONS),
            field("disposition_note", "text", True),
        ],
    )
    def review_event(ctx, id):
        row = access.path_row("AdverseEvent", id)
        access.acting_provider(ctx)
        disposition = ctx.get("disposition")
        allowed = ("OPEN", "ESCALATED") if disposition == "CLOSED" else ("OPEN",)
        gates.state_gate(row, "AdverseEvent.status", allowed)                # rungs 10/11

        # rung 13 -- segregation of duties
        if ctx.user_id == row["reported_by_provider_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if row["status"] == "ESCALATED" and ctx.user_id == row.get("reviewed_by_provider_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

        row["reviewed_by_provider_id"] = ctx.user_id
        row["disposition_note"] = ctx.get("disposition_note")
        row["status"] = disposition
        store.touch(row)
        if disposition == "CLOSED":
            patient = store.get("Patient", row["patient_id"])
            if patient is not None:
                cascades.clear_clinical_hold_if_resolved(patient)
        return envelope.ok(serializers.adverse_event(row))
