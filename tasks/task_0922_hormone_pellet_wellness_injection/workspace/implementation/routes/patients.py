"""Patients, the therapy-status projection and the two eligibility holds."""
import access
import calc
import cascades
import config
import envelope
import serializers
import store
import util
from errors import ApiError
from reqctx import endpoint, field


def _financial_role_hook(ctx):
    """Only a ClinicAdmin may drive the financial hold (PRD 3.1)."""
    if ctx.role == config.ROLE_PHYSICIAN and ctx.raw_get("hold_kind") == "FINANCIAL":
        raise ApiError("ERR_FORBIDDEN_ROLE")


def register(app):
    @app.route("/clinic/patients", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK],
        specs=[
            field("full_name", "string", True),
            field("date_of_birth", "string", True),
            field("email", "string", True),
            field("sex_at_birth", "enum", True, members=config.SEX_AT_BIRTH),
        ],
    )
    def create_patient(ctx):
        email = ctx.get("email")
        for row in store.all_rows("Patient"):
            if row["email"] == email:
                raise ApiError("ERR_VALIDATION", "email must be unique across patients.")
        row = store.create("Patient", {
            "full_name": ctx.get("full_name"),
            "date_of_birth": ctx.get("date_of_birth"),
            "email": email,
            "sex_at_birth": ctx.get("sex_at_birth"),
            "clinical_hold": False,
            "financial_hold": False,
            "eligibility_status": "CLEAR",
            "cumulative_mg_testosterone": 0,
            "cumulative_mg_estradiol": 0,
            "last_insertion_at": None,
            "last_insertion_hormone_type": None,
            "open_notification_count": 0,
        })
        return envelope.ok(serializers.patient(row), 201)

    @app.route("/clinic/patients/<id>", methods=["GET"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
               config.ROLE_NURSE_INJECTOR, config.ROLE_COMPLIANCE_OFFICER,
               config.ROLE_PATIENT],
    )
    def read_patient(ctx, id):
        row = access.path_row("Patient", id)
        access.ownership(ctx, patient_id=row["id"])
        return envelope.ok(serializers.patient(row))

    @app.route("/clinic/patients/<id>/therapy-status", methods=["GET"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN, config.ROLE_PHYSICIAN, config.ROLE_NURSE_INJECTOR,
               config.ROLE_FRONT_DESK, config.ROLE_PATIENT],
        specs=[
            # hormone_type is not one of the fields rung 5 routes to
            # ERR_INVALID_ENUM, so an undeclared member is ERR_VALIDATION.
            field("hormone_type", "enum", True, members=config.HORMONE_TYPES, rung5=False),
            field("consult_id", "id", False),
            field("lab_panel_id", "id", False),
            field("scheduled_start", "datetime", False),
        ],
    )
    def therapy_status(ctx, id):
        patient = access.path_row("Patient", id)
        resolved = access.resolve_fks(ctx, ("consult_id", "lab_panel_id"))
        access.ownership(ctx, patient_id=patient["id"])

        hormone = ctx.get("hormone_type")
        now = store.now()
        consult = resolved.get("consult_id")
        panel = resolved.get("lab_panel_id")
        anchor = calc.redose_anchor(patient["id"], hormone)
        factors = calc.redose_factors(
            hormone, anchor, panel, consult, ctx.get("scheduled_start"), now
        )
        data = {
            "patient_id": patient["id"],
            "hormone_type": hormone,
            "rolling_mg_completed_only": calc.rolling_mg_exposure(
                patient["id"], hormone, "COMPLETED_ONLY", now
            ),
            "rolling_mg_including_scheduled": calc.rolling_mg_exposure(
                patient["id"], hormone, "INCLUDING_SCHEDULED", now
            ),
            "rolling_mg_cap": config.ROLLING_MG_CAP[hormone],
            "anchor_performed_at": util.fmt_dt(anchor),
        }
        data.update(factors)
        data["redose_eligible"] = all(factors.values())
        data["clinical_hold"] = bool(patient["clinical_hold"])
        data["financial_hold"] = bool(patient["financial_hold"])
        data["eligibility_status"] = patient["eligibility_status"]
        return envelope.ok(data)

    @app.route("/clinic/patients/<id>/eligibility-hold", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN, config.ROLE_PHYSICIAN],
        role_hook=_financial_role_hook,
        specs=[
            field("hold_kind", "enum", True, members=config.HOLD_KINDS),
            field("hold_action", "enum", True, members=config.HOLD_ACTIONS),
            field("reason", "text", False),
        ],
    )
    def eligibility_hold(ctx, id):
        patient = access.path_row("Patient", id)
        access.ownership(ctx)

        kind = ctx.get("hold_kind")
        action = ctx.get("hold_action")
        value = action == "SET"
        if kind == "CLINICAL":
            cascades.set_clinical_hold(patient, value)
        else:
            cascades.set_financial_hold(patient, value)
            if not value:
                # Clearing a financial hold releases the procedures it froze.
                for proc in store.where("Procedure", patient_id=patient["id"]):
                    if (
                        proc["status"] == "SUPPLY_HOLD"
                        and proc.get("hold_reason") == "PATIENT_FINANCIAL_HOLD"
                    ):
                        cascades.unfreeze_procedure(proc)
        return envelope.ok(serializers.patient(patient))
