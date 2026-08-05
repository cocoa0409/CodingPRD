"""Self-pay installment plans and the delinquency ops run (PRD 3.9)."""
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

READ_ROLES = [config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PATIENT]


def register(app):
    @app.route("/clinic/financing-plans", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK],
        specs=[
            field("patient_id", "id", True),
            field("procedure_id", "id", True),
            field("principal_cents", "integer", True, gt=0),
            field("down_payment_cents", "integer", True),
            field("installment_count", "integer", True),
            field("first_due_date", "datetime", True),
        ],
    )
    def create_plan(ctx):
        resolved = access.resolve_fks(ctx, ("patient_id", "procedure_id"))
        access.ownership(ctx, patient_id=resolved["patient_id"]["id"])

        principal = ctx.get("principal_cents")
        down = ctx.get("down_payment_cents")
        count = ctx.get("installment_count")
        minimum = util.ceil_div_frac(
            util.frac(principal) * config.FINANCING_MIN_DOWN_PAYMENT_PCT
        )
        if down < minimum or down >= principal:                              # rung 36
            raise ApiError("ERR_DOWN_PAYMENT_TOO_LOW")
        if not (config.FINANCING_MIN_INSTALLMENTS <= count <= config.FINANCING_MAX_INSTALLMENTS):
            raise ApiError("ERR_INSTALLMENT_COUNT_INVALID")                  # rung 37

        schedule = calc.financing_schedule_cents(principal, down, count, ctx.get("first_due_date"))
        row = {
            "patient_id": ctx.get("patient_id"),
            "procedure_id": ctx.get("procedure_id"),
            "principal_cents": principal,
            "down_payment_cents": down,
            "installment_count": count,
            "first_due_date": ctx.get("first_due_date"),
            "schedule": schedule,
            "paid_installment_cents": 0,
            "outstanding_cents": 0,
            "waived_cents": 0,
            "refunded_cents": 0,
            "late_fee_cents": 0,
            "missed_count": 0,
            "status": "DRAFT",
        }
        cascades.recompute_plan_money(row)
        row = store.create("FinancingPlan", row)
        return envelope.ok(serializers.financing_plan(row), 201)

    @app.route("/clinic/financing-plans/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_plan(ctx, id):
        row = access.path_row("FinancingPlan", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.financing_plan(row))

    @app.route("/clinic/financing-plans", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("procedure_id", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_plans(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("FinancingPlan"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "procedure_id": "procedure_id",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.financing_plan(r) for r in window], 200, block)

    @app.route("/clinic/financing-plans/<id>/activate", methods=["POST"])
    @endpoint(roles=[config.ROLE_FRONT_DESK])
    def activate_plan(ctx, id):
        row = access.path_row("FinancingPlan", id)
        access.ownership(ctx)
        gates.state_gate(row, "FinancingPlan.status", ("DRAFT",))
        proc = store.get("Procedure", row["procedure_id"])
        if proc is not None and proc["status"] in ("CANCELLED", "VOIDED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "The financed procedure has already reached a terminal state.",
            )
        row["status"] = "ACTIVE"
        store.touch(row)
        return envelope.ok(serializers.financing_plan(row))

    @app.route("/clinic/financing-plans/<id>/payments", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PATIENT],
        specs=[
            field("installment_index", "integer", True),
            field("amount_cents", "integer", True),
        ],
    )
    def pay_installment(ctx, id):
        row = access.path_row("FinancingPlan", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        gates.state_gate(row, "FinancingPlan.status", ("ACTIVE", "DELINQUENT"))

        index = ctx.get("installment_index")
        entry = next((e for e in row["schedule"] if e["index"] == index), None)
        if entry is None or entry["status"] not in ("PENDING", "MISSED"):    # rung 38
            raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")
        if ctx.get("amount_cents") != entry["amount_cents"]:
            raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

        entry["status"] = "PAID"
        cascades.recompute_plan_money(row)
        if row["status"] == "DELINQUENT" and row["missed_count"] == 0:
            row["status"] = "ACTIVE"
        if row["status"] == "ACTIVE" and row["outstanding_cents"] == 0:
            row["status"] = "PAID_OFF"
        store.touch(row)
        return envelope.ok(serializers.financing_plan(row))

    @app.route("/clinic/billing/delinquency-run", methods=["POST"])
    @endpoint(roles=[config.ROLE_FRONT_DESK, config.ROLE_CLINIC_ADMIN])
    def delinquency_run(ctx):
        return envelope.ok(cascades.delinquency_run())
