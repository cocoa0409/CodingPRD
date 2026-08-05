"""Pellet insertions: booking, consent, allocation, tray, insertion, exits."""
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

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
    config.ROLE_NURSE_INJECTOR, config.ROLE_INVENTORY_MANAGER,
    config.ROLE_COMPLIANCE_OFFICER, config.ROLE_PATIENT,
]
ALLOCATION_READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
    config.ROLE_NURSE_INJECTOR, config.ROLE_INVENTORY_MANAGER,
    config.ROLE_COMPLIANCE_OFFICER,
]


def _membership_of(procedure):
    membership_id = procedure.get("membership_id")
    return store.get("Membership", membership_id) if membership_id else None


def _redose_gate(patient, consult, panel, scheduled_start):
    """Rungs 21 to 25, in the fixed order freshness, trough, interval, band, score."""
    hormone = consult["hormone_type"]
    now = store.now()
    anchor = calc.redose_anchor(patient["id"], hormone)
    factors = calc.redose_factors(hormone, anchor, panel, consult, scheduled_start, now)
    # With no anchoring insertion, rungs 21 and 22 have nothing to measure and
    # are skipped so the request lands on rung 23 (PRD 2.9).
    if anchor is not None:
        if not factors["f3_freshness_ok"]:
            raise ApiError("ERR_LAB_STALE")
        if not factors["f2_trough_ok"]:
            raise ApiError("ERR_TROUGH_WINDOW_VIOLATION")
    if not factors["f1_interval_ok"]:
        raise ApiError("ERR_REDOSE_INTERVAL_NOT_MET")
    if not factors["f5_band_ok"]:
        raise ApiError("ERR_ANALYTE_NOT_BELOW_OPTIMAL")
    if not factors["f4_symptom_ok"]:
        raise ApiError("ERR_SYMPTOM_SCORE_BELOW_THRESHOLD")


def register(app):
    # ------------------------------------------------------- book -----------
    @app.route("/clinic/procedures", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN],
        specs=[
            field("patient_id", "id", True),
            field("provider_id", "id", True),
            field("consult_id", "id", True),
            field("standing_order_id", "id", True),
            field("procedure_type", "enum", True, members=config.PROCEDURE_TYPES),
            field("room_code", "string", True),
            field("scheduled_start", "datetime", True),
            field("lab_panel_id", "id", False),
            field("membership_id", "id", False),
        ],
    )
    def book_procedure(ctx):
        resolved = access.resolve_fks(ctx, (
            "patient_id", "provider_id", "consult_id", "standing_order_id",
            "lab_panel_id", "membership_id",
        ))
        patient = resolved["patient_id"]
        consult = resolved["consult_id"]
        access.ownership(ctx, patient_id=patient["id"])

        hormone = consult["hormone_type"]
        planned_total_mg = consult["planned_total_mg"]
        scheduled_start = ctx.get("scheduled_start")
        scheduled_end = util.add_minutes(scheduled_start, config.PROCEDURE_DURATION_MINUTES)

        gates.clinical_hold_gate(patient)                                    # rung 14
        gates.safety_ceiling_gate(patient["id"])                             # rung 18
        gates.dose_cap_gate(hormone, planned_total_mg)                       # rung 19
        gates.rolling_cap_gate(                                              # rung 20
            patient["id"], hormone, "INCLUDING_SCHEDULED", planned_total_mg
        )
        if ctx.get("procedure_type") == "REDOSE":                            # rungs 21-25
            _redose_gate(patient, consult, resolved.get("lab_panel_id"), scheduled_start)
        gates.post_insertion_gate(patient, scheduled_start)                  # rung 26
        gates.provider_conflict_gate(                                        # rung 27
            ctx.get("provider_id"), scheduled_start, scheduled_end
        )
        gates.room_conflict_gate(ctx.get("room_code"), scheduled_start, scheduled_end)  # 28
        gates.financial_hold_gate(patient)                                   # rung 39

        row = store.create("Procedure", {
            "patient_id": patient["id"],
            "provider_id": ctx.get("provider_id"),
            "consult_id": consult["id"],
            "standing_order_id": ctx.get("standing_order_id"),
            "consent_record_id": None,
            "lab_panel_id": ctx.get("lab_panel_id"),
            "membership_id": ctx.get("membership_id"),
            "procedure_type": ctx.get("procedure_type"),
            "hormone_type": hormone,
            "room_code": ctx.get("room_code"),
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "planned_pellet_count": consult["planned_pellet_count"],
            "planned_total_mg": planned_total_mg,
            "pellets_allocated": 0,
            "pellets_opened": 0,
            "pellets_inserted": 0,
            "pellets_wasted": 0,
            "delivered_total_mg": 0,
            "status": "SCHEDULED",
            "recall_status": "NONE",
            "charge_cents": 0,
            "cancel_tier": None,
            "cancel_fee_cents": 0,
            "performed_at": None,
            "hold_reason": None,
        })
        return envelope.ok(serializers.procedure(row), 201)

    # ------------------------------------------------------- reads ----------
    @app.route("/clinic/procedures/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_procedure(ctx, id):
        row = access.path_row("Procedure", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.procedure(row))

    @app.route("/clinic/procedures", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("provider_id", "filter", False),
            field("consult_id", "filter", False),
            field("standing_order_id", "filter", False),
            field("consent_record_id", "filter", False),
            field("lab_panel_id", "filter", False),
            field("membership_id", "filter", False),
            field("status", "filter", False),
            field("recall_status", "filter", False),
        ],
    )
    def list_procedures(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("Procedure"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "provider_id": "provider_id",
            "consult_id": "consult_id",
            "standing_order_id": "standing_order_id",
            "consent_record_id": "consent_record_id",
            "lab_panel_id": "lab_panel_id",
            "membership_id": "membership_id",
            "status": "status",
            "recall_status": "recall_status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.procedure(r) for r in window], 200, block)

    # ---------------------------------------------- consent attachment ------
    @app.route("/clinic/procedures/<id>/consent-attach", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN, config.ROLE_PATIENT],
        specs=[field("consent_record_id", "id", True)],
    )
    def consent_attach(ctx, id):
        proc = access.path_row("Procedure", id)
        resolved = access.resolve_fks(ctx, ("consent_record_id",))
        access.ownership(ctx, patient_id=proc["patient_id"])
        gates.state_gate(proc, "Procedure.status", ("SCHEDULED",))
        consent = resolved["consent_record_id"]
        if not gates.consent_is_current(consent, proc["patient_id"], proc["hormone_type"]):
            raise ApiError("ERR_CONSENT_REQUIRED")                           # rung 16
        if util.frac(consent["consented_max_dose_mg"]) < util.frac(proc["planned_total_mg"]):
            raise ApiError("ERR_CONSENT_DOSE_EXCEEDED")                      # rung 17
        proc["consent_record_id"] = consent["id"]
        proc["status"] = "CONSENTED"
        store.touch(proc)
        return envelope.ok(serializers.procedure(proc))

    register_supply(app)
    register_exits(app)


def register_supply(app):
    # ------------------------------------------------- FEFO allocation ------
    @app.route("/clinic/procedures/<id>/allocations", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_INVENTORY_MANAGER, config.ROLE_PHYSICIAN],
        specs=[field("expected_procedure_version", "integer", True)],
    )
    def run_allocation(ctx, id):
        proc = access.path_row("Procedure", id)
        access.ownership(ctx)
        gates.terminal_gate(proc, "Procedure.status")                        # rung 11
        if ctx.get("expected_procedure_version") != proc["version"]:         # rung 12
            raise ApiError("ERR_STALE_PROCEDURE_VERSION")

        consult = store.get("Consult", proc["consult_id"])
        superseded = [
            row for row in calc.allocations_of_procedure(proc["id"])
            if row["status"] in ("RESERVED", "OPENED")
        ]
        credited = {}
        for row in superseded:
            credited[row["lot_id"]] = credited.get(row["lot_id"], 0) + row["quantity"]

        draws = calc.fefo_allocation_plan(proc, consult, released_extra=credited)
        if draws is None:                                                    # rung 30
            raise ApiError("ERR_INSUFFICIENT_PELLET_INVENTORY")

        # Nothing above this line mutated anything: the supersession and the new
        # plan commit together or not at all.
        for row in superseded:
            lot = store.get("PelletLot", row["lot_id"])
            row["status"] = "RELEASED"
            store.touch(row)
            if lot is not None:
                cascades.move_lot(lot, "qty_reserved", "qty_on_hand", row["quantity"])

        created = []
        for rank, draw in enumerate(draws, start=1):
            lot = draw["lot"]
            allocation = store.create("PelletAllocation", {
                "procedure_id": proc["id"],
                "lot_id": lot["id"],
                "strength_mg": draw["strength_mg"],
                "quantity": draw["quantity"],
                "allocation_rank": rank,
                "status": "RESERVED",
            })
            cascades.move_lot(lot, "qty_on_hand", "qty_reserved", draw["quantity"])
            created.append(allocation)

        cascades.recompute_pellets_allocated(proc)
        store.touch(proc)
        return envelope.ok_array([serializers.allocation(r) for r in created], 201)

    @app.route("/clinic/procedures/<id>/allocations", methods=["GET"])
    @endpoint(
        roles=ALLOCATION_READ_ROLES,
        paginated=True,
        specs=[field("status", "filter", False)],
    )
    def list_procedure_allocations(ctx, id):
        proc = access.path_row("Procedure", id)
        access.ownership(ctx)
        rows = reqctx.order_rows(calc.allocations_of_procedure(proc["id"]))
        rows = reqctx.apply_filters(ctx, rows, {"status": "status"})
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.allocation(r) for r in window], 200, block)

    # ------------------------------------------------- open the tray --------
    @app.route("/clinic/procedures/<id>/open-supply", methods=["POST"])
    @endpoint(roles=[config.ROLE_NURSE_INJECTOR, config.ROLE_PHYSICIAN])
    def open_supply(ctx, id):
        proc = access.path_row("Procedure", id)
        access.ownership(ctx)
        gates.standing_order_write_gate(                                     # rung 9
            ctx,
            store.get("StandingOrder", proc.get("standing_order_id")),
            hormone_type=proc["hormone_type"],
            planned_total_mg=proc["planned_total_mg"],
        )
        gates.state_gate(proc, "Procedure.status", ("CONSENTED",))           # rungs 10/11
        if proc["pellets_allocated"] != proc["planned_pellet_count"]:
            raise ApiError(
                "ERR_INVALID_STATE",
                "The allocation plan is not complete for this procedure.",
            )
        gates.consent_gate(proc)                                             # rung 16

        for row in calc.allocations_of_procedure(proc["id"]):
            if row["status"] == "RESERVED":
                row["status"] = "OPENED"
                store.touch(row)
        proc["pellets_opened"] = proc["pellets_allocated"]
        proc["status"] = "SUPPLY_OPENED"
        store.touch(proc)
        return envelope.ok(serializers.procedure(proc))

    # ----------------------------------------------------- insertion --------
    @app.route("/clinic/procedures/<id>/perform", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_NURSE_INJECTOR, config.ROLE_PHYSICIAN],
        specs=[
            field("expected_patient_version", "integer", True),
            field("pellets_wasted", "integer", True, gte=0),
        ],
    )
    def perform_procedure(ctx, id):
        proc = access.path_row("Procedure", id)
        wasted_input = ctx.get("pellets_wasted")
        if wasted_input > proc["pellets_opened"]:
            # PRD 3.5 routes an over-large wastage count to the request-shape rung.
            raise ApiError(
                "ERR_VALIDATION", "pellets_wasted may not exceed the procedure's pellets_opened."
            )
        access.ownership(ctx)
        patient = store.get("Patient", proc["patient_id"])
        gates.standing_order_write_gate(                                     # rung 9
            ctx,
            store.get("StandingOrder", proc.get("standing_order_id")),
            hormone_type=proc["hormone_type"],
            planned_total_mg=proc["planned_total_mg"],
        )
        gates.state_gate(proc, "Procedure.status", ("SUPPLY_OPENED",))       # rungs 10/11
        if ctx.get("expected_patient_version") != patient["version"]:        # rung 12
            raise ApiError("ERR_STALE_PATIENT_VERSION")
        gates.clinical_hold_gate(patient)                                    # rung 14
        gates.critical_lab_gate(patient)                                     # rung 15
        gates.consent_gate(proc)                                             # rung 16
        gates.safety_ceiling_gate(patient["id"])                             # rung 18

        plan = _plan_wastage(proc, wasted_input)
        committing_mg = sum(
            util.frac(consumed) * util.frac(row["strength_mg"])
            for row, consumed, _ in plan
        )
        gates.rolling_cap_gate(                                              # rung 20
            patient["id"], proc["hormone_type"], "COMPLETED_ONLY", committing_mg
        )
        gates.financial_hold_gate(patient)                                   # rung 39

        _commit_wastage(proc, plan)
        proc["pellets_inserted"] = sum(consumed for _, consumed, _ in plan)
        proc["pellets_wasted"] = wasted_input
        proc["delivered_total_mg"] = calc.procedure_delivered_mg(proc, "ACTUAL")
        proc["performed_at"] = store.now()
        proc["status"] = "COMPLETED"
        cascades.recompute_pellets_allocated(proc)
        proc["charge_cents"] = calc.visit_invoice_total_cents(proc, _membership_of(proc))
        store.touch(proc)

        key = (
            "cumulative_mg_testosterone"
            if proc["hormone_type"] == "TESTOSTERONE"
            else "cumulative_mg_estradiol"
        )
        patient[key] = util.numout(
            util.frac(patient[key]) + util.frac(proc["delivered_total_mg"])
        )
        patient["last_insertion_at"] = proc["performed_at"]
        patient["last_insertion_hormone_type"] = proc["hormone_type"]
        store.touch(patient)
        return envelope.ok(serializers.procedure(proc))


def register_exits(app):
    # ---------------------------------------------------- cancellation ------
    @app.route("/clinic/procedures/<id>/cancel", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN, config.ROLE_PATIENT],
        specs=[field("reason", "text", False)],
    )
    def cancel_procedure(ctx, id):
        proc = access.path_row("Procedure", id)
        # From SUPPLY_OPENED and SUPPLY_HOLD only FrontDesk and Physician may act.
        if proc["status"] in ("SUPPLY_OPENED", "SUPPLY_HOLD") and ctx.role not in (
            config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN
        ):
            raise ApiError("ERR_FORBIDDEN_ROLE")
        access.ownership(ctx, patient_id=proc["patient_id"])
        gates.state_gate(
            proc, "Procedure.status",
            ("SCHEDULED", "CONSENTED", "SUPPLY_OPENED", "SUPPLY_HOLD"),
        )

        membership = _membership_of(proc)
        origin = proc["status"]
        now = store.now()
        if origin == "SUPPLY_HOLD":
            tier, fee = calc.late_cancel_fee_cents(
                proc, membership, now, variant="CLINIC_INITIATED"
            )
        else:
            tier, fee = calc.late_cancel_fee_cents(proc, membership, now)

        if origin in ("SCHEDULED", "CONSENTED"):
            cascades.release_allocations(proc, statuses=("RESERVED",))
        elif origin == "SUPPLY_OPENED":
            for row in calc.allocations_of_procedure(proc["id"]):
                if row["status"] != "OPENED":
                    continue
                lot = store.get("PelletLot", row["lot_id"])
                row["status"] = "WASTED"
                store.touch(row)
                if lot is not None:
                    cascades.move_lot(lot, "qty_reserved", "qty_wasted", row["quantity"])
            proc["pellets_wasted"] = proc["pellets_opened"]
            cascades.recompute_pellets_allocated(proc)

        proc["cancel_tier"] = tier
        proc["cancel_fee_cents"] = fee
        proc["status"] = "CANCELLED"
        store.touch(proc)
        cascades.cancel_plans_for_procedure(proc, membership, tier, fee)
        return envelope.ok(serializers.procedure(proc))

    # ---------------------------------------------------------- void --------
    @app.route("/clinic/procedures/<id>/void", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN],
        specs=[field("reason", "text", True)],
    )
    def void_procedure(ctx, id):
        proc = access.path_row("Procedure", id)
        access.ownership(ctx)
        gates.state_gate(proc, "Procedure.status", ("COMPLETED",))

        patient = store.get("Patient", proc["patient_id"])
        pre_void = proc["delivered_total_mg"]
        proc["delivered_total_mg"] = 0
        proc["status"] = "VOIDED"
        store.touch(proc)

        key = (
            "cumulative_mg_testosterone"
            if proc["hormone_type"] == "TESTOSTERONE"
            else "cumulative_mg_estradiol"
        )
        patient[key] = util.numout(util.frac(patient[key]) - util.frac(pre_void))
        cascades.recompute_last_insertion(patient)
        store.touch(patient)
        return envelope.ok(serializers.procedure(proc))

    # -------------------------------------------------- refund quote --------
    @app.route("/clinic/procedures/<id>/refund-quote", methods=["GET"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN, config.ROLE_PATIENT],
    )
    def refund_quote(ctx, id):
        proc = access.path_row("Procedure", id)
        access.ownership(ctx, patient_id=proc["patient_id"])
        quote = calc.refund_settlement_cents(
            proc, _membership_of(proc), store.now(), "PROVISIONAL_QUOTE"
        )
        data = {"procedure_id": proc["id"], "variant": "PROVISIONAL_QUOTE"}
        data.update(quote)
        return envelope.ok(data)


def _plan_wastage(procedure, pellets_wasted):
    """Wastage is taken from the highest allocation_rank downward (PRD 3.5)."""
    rows = [
        row for row in calc.allocations_of_procedure(procedure["id"])
        if row["status"] == "OPENED"
    ]
    rows.sort(key=lambda r: (r["allocation_rank"], r["_seq"]), reverse=True)
    remaining = pellets_wasted
    plan = []
    for row in rows:
        take = min(remaining, row["quantity"])
        plan.append((row, row["quantity"] - take, take))
        remaining -= take
    return plan


def _commit_wastage(procedure, plan):
    for row, consumed, wasted in plan:
        lot = store.get("PelletLot", row["lot_id"])
        opened_quantity = consumed + wasted
        if consumed > 0 and wasted > 0:
            # The boundary falls inside this row: keep the id and rank on the
            # consumed remainder and mint a sibling row for the waste.
            row["quantity"] = consumed
            row["status"] = "CONSUMED"
            store.touch(row)
            store.create("PelletAllocation", {
                "procedure_id": procedure["id"],
                "lot_id": row["lot_id"],
                "strength_mg": row["strength_mg"],
                "quantity": wasted,
                "allocation_rank": row["allocation_rank"],
                "status": "WASTED",
            })
        elif wasted > 0:
            row["status"] = "WASTED"
            store.touch(row)
        else:
            row["status"] = "CONSUMED"
            store.touch(row)
        if lot is not None:
            lot["qty_reserved"] -= opened_quantity
            lot["qty_consumed"] += consumed
            lot["qty_wasted"] += wasted
            store.touch(lot)
