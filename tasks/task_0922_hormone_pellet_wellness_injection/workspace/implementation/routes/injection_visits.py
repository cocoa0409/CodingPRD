"""Wellness injection visits and the payment-source waterfall (PRD 3.7)."""
import access
import calc
import config
import envelope
import gates
import reqctx
import serializers
import store
import util
from reqctx import endpoint, field

READ_ROLES = [
    config.ROLE_CLINIC_ADMIN, config.ROLE_FRONT_DESK, config.ROLE_PHYSICIAN,
    config.ROLE_NURSE_INJECTOR, config.ROLE_COMPLIANCE_OFFICER, config.ROLE_PATIENT,
]


def register(app):
    @app.route("/clinic/injection-visits", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_NURSE_INJECTOR, config.ROLE_PHYSICIAN],
        specs=[
            field("patient_id", "id", True),
            field("provider_id", "id", True),
            field("standing_order_id", "id", True),
            field("injection_type", "enum", True, members=config.INJECTION_TYPES),
            field("room_code", "string", True),
            field("scheduled_start", "datetime", True),
            field("series_pack_id", "id", False),
            field("membership_id", "id", False),
        ],
    )
    def book_visit(ctx):
        resolved = access.resolve_fks(ctx, (
            "patient_id", "provider_id", "standing_order_id", "series_pack_id",
            "membership_id",
        ))
        patient = resolved["patient_id"]
        access.ownership(ctx, patient_id=patient["id"])

        scheduled_start = ctx.get("scheduled_start")
        scheduled_end = util.add_minutes(scheduled_start, config.INJECTION_DURATION_MINUTES)
        gates.provider_conflict_gate(                                        # rung 27
            ctx.get("provider_id"), scheduled_start, scheduled_end
        )
        gates.room_conflict_gate(ctx.get("room_code"), scheduled_start, scheduled_end)  # 28
        gates.series_ownership_gate(resolved.get("series_pack_id"), patient["id"])      # 31

        row = store.create("InjectionVisit", {
            "patient_id": patient["id"],
            "provider_id": ctx.get("provider_id"),
            "standing_order_id": ctx.get("standing_order_id"),
            "series_pack_id": ctx.get("series_pack_id"),
            "membership_id": ctx.get("membership_id"),
            "injection_type": ctx.get("injection_type"),
            "room_code": ctx.get("room_code"),
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "payment_source": None,
            "charge_cents": 0,
            "series_debit_cents": 0,
            "administered_at": None,
            "status": "SCHEDULED",
        })
        return envelope.ok(serializers.injection_visit(row), 201)

    @app.route("/clinic/injection-visits/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_visit(ctx, id):
        row = access.path_row("InjectionVisit", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.injection_visit(row))

    @app.route("/clinic/injection-visits", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("provider_id", "filter", False),
            field("standing_order_id", "filter", False),
            field("series_pack_id", "filter", False),
            field("membership_id", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_visits(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("InjectionVisit"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "provider_id": "provider_id",
            "standing_order_id": "standing_order_id",
            "series_pack_id": "series_pack_id",
            "membership_id": "membership_id",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.injection_visit(r) for r in window], 200, block)

    @app.route("/clinic/injection-visits/<id>/administer", methods=["POST"])
    @endpoint(roles=[config.ROLE_NURSE_INJECTOR, config.ROLE_PHYSICIAN])
    def administer_visit(ctx, id):
        visit = access.path_row("InjectionVisit", id)
        access.ownership(ctx)
        patient = store.get("Patient", visit["patient_id"])
        pack = store.get("SeriesPack", visit.get("series_pack_id")) if visit.get(
            "series_pack_id"
        ) else None
        membership = store.get("Membership", visit.get("membership_id")) if visit.get(
            "membership_id"
        ) else None

        gates.standing_order_write_gate(                                     # rung 9
            ctx,
            store.get("StandingOrder", visit.get("standing_order_id")),
            injection_type=visit["injection_type"],
        )
        gates.state_gate(visit, "InjectionVisit.status", ("SCHEDULED",))     # rungs 10/11
        gates.clinical_hold_gate(patient)                                    # rung 14
        gates.critical_lab_gate(patient)                                     # rung 15
        gates.series_ownership_gate(pack, visit["patient_id"])               # rung 31
        gates.series_expiry_gate(pack)                                       # rung 32
        gates.series_exhaustion_gate(pack)                                   # rung 33

        source = calc.injection_payment_source(visit, pack, membership)
        visit["payment_source"] = source
        if source == "SERIES":
            visit["series_debit_cents"] = calc.series_redemption_debit_cents(pack)
            visit["charge_cents"] = 0
            pack["remaining_visits"] -= 1
            pack["redeemed_visits"] += 1
            if pack["remaining_visits"] == 0:
                pack["status"] = "EXHAUSTED"
            store.touch(pack)
        elif source == "MEMBERSHIP_INCLUDED":
            visit["charge_cents"] = 0
            visit["series_debit_cents"] = 0
            membership["included_visits_used"] += 1
            store.touch(membership)
        else:
            visit["series_debit_cents"] = 0
            visit["charge_cents"] = calc.injection_charge_cents(visit, membership)
        visit["administered_at"] = store.now()
        visit["status"] = "ADMINISTERED"
        store.touch(visit)
        return envelope.ok(serializers.injection_visit(visit))

    @app.route("/clinic/injection-visits/<id>/cancel", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_PATIENT],
        specs=[field("reason", "text", False)],
    )
    def cancel_visit(ctx, id):
        visit = access.path_row("InjectionVisit", id)
        access.ownership(ctx, patient_id=visit["patient_id"])
        gates.state_gate(visit, "InjectionVisit.status", ("SCHEDULED",))
        visit["status"] = "CANCELLED"
        store.touch(visit)
        return envelope.ok(serializers.injection_visit(visit))

    @app.route("/clinic/injection-visits/<id>/void", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_PHYSICIAN],
        specs=[field("reason", "text", True)],
    )
    def void_visit(ctx, id):
        visit = access.path_row("InjectionVisit", id)
        access.ownership(ctx)
        gates.state_gate(visit, "InjectionVisit.status", ("ADMINISTERED",))

        source = visit.get("payment_source")
        if source == "SERIES":
            pack = store.get("SeriesPack", visit.get("series_pack_id"))
            if pack is not None:
                pack["redeemed_visits"] -= 1
                pack["remaining_visits"] += 1
                if pack["status"] == "EXHAUSTED":
                    pack["status"] = "ACTIVE"
                store.touch(pack)
        elif source == "MEMBERSHIP_INCLUDED":
            membership = store.get("Membership", visit.get("membership_id"))
            if membership is not None:
                membership["included_visits_used"] -= 1
                store.touch(membership)
        else:
            visit["charge_cents"] = 0
        visit["status"] = "VOIDED"
        store.touch(visit)
        return envelope.ok(serializers.injection_visit(visit))
