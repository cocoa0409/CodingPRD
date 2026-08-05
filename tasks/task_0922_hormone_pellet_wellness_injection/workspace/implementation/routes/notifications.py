"""Patient notifications: the reverse-reachability channel for cascades."""
import access
import config
import envelope
import gates
import reqctx
import serializers
import store
from reqctx import endpoint, field

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_PATIENT,
]


def register(app):
    @app.route("/clinic/patient-notifications/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_notification(ctx, id):
        row = access.path_row("PatientNotification", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.notification(row))

    @app.route("/clinic/patient-notifications", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("procedure_id", "filter", False),
            field("lot_id", "filter", False),
            field("notification_type", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_notifications(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("PatientNotification"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "procedure_id": "procedure_id",
            "lot_id": "lot_id",
            "notification_type": "notification_type",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.notification(r) for r in window], 200, block)

    @app.route("/clinic/patient-notifications/<id>/acknowledge", methods=["POST"])
    @endpoint(roles=[config.ROLE_FRONT_DESK, config.ROLE_PATIENT])
    def acknowledge(ctx, id):
        row = access.path_row("PatientNotification", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        gates.state_gate(row, "PatientNotification.status", ("PENDING", "OVERDUE"))
        row["status"] = "ACKNOWLEDGED"
        row["acknowledged_at"] = store.now()
        store.touch(row)
        patient = store.get("Patient", row["patient_id"])
        if patient is not None:
            patient["open_notification_count"] = max(
                0, patient.get("open_notification_count", 0) - 1
            )
            store.touch(patient)
        return envelope.ok(serializers.notification(row))
