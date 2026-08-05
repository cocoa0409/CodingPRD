"""Memberships: tiers, pause credit, resume, tier change and cancellation."""
import access
import calc
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
    config.ROLE_NURSE_INJECTOR, config.ROLE_PATIENT,
]


def _apply_tier(row, tier, period_start):
    row["tier"] = tier
    row["monthly_fee_cents"] = config.MEMBERSHIP_FEE_CENTS[tier]
    row["discount_pct"] = config.MEMBERSHIP_DISCOUNT_PCT_OUT[tier]
    row["included_visits_allowance"] = config.MEMBERSHIP_INCLUDED_VISITS[tier]
    row["period_start"] = period_start
    row["period_end"] = util.add_days(period_start, config.MEMBERSHIP_PERIOD_DAYS)


def register(app):
    @app.route("/clinic/memberships", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_CLINIC_ADMIN],
        specs=[
            field("patient_id", "id", True),
            field("tier", "enum", True, members=config.MEMBERSHIP_TIERS),
        ],
    )
    def enrol(ctx):
        resolved = access.resolve_fks(ctx, ("patient_id",))
        patient = resolved["patient_id"]
        access.ownership(ctx, patient_id=patient["id"])
        for row in store.where("Membership", patient_id=patient["id"]):
            if row["status"] in ("ACTIVE", "PAUSED"):
                raise ApiError("ERR_DUPLICATE_ACTIVE_MEMBERSHIP")            # rung 34

        row = {
            "patient_id": patient["id"],
            "included_visits_used": 0,
            "status": "ACTIVE",
            "paused_at": None,
            "pause_days_used": 0,
            "pause_credit_cents": 0,
        }
        _apply_tier(row, ctx.get("tier"), store.now())
        row = store.create("Membership", row)
        return envelope.ok(serializers.membership(row), 201)

    @app.route("/clinic/memberships/<id>", methods=["GET"])
    @endpoint(roles=READ_ROLES)
    def read_membership(ctx, id):
        row = access.path_row("Membership", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        return envelope.ok(serializers.membership(row))

    @app.route("/clinic/memberships", methods=["GET"])
    @endpoint(
        roles=READ_ROLES,
        paginated=True,
        specs=[
            field("patient_id", "filter", False),
            field("tier", "filter", False),
            field("status", "filter", False),
        ],
    )
    def list_memberships(ctx):
        access.ownership(ctx)
        rows = reqctx.order_rows(store.all_rows("Membership"))
        rows = reqctx.apply_filters(ctx, rows, {
            "patient_id": "patient_id",
            "tier": "tier",
            "status": "status",
        })
        window, block = reqctx.pagination_window(ctx, rows)
        return envelope.ok_array([serializers.membership(r) for r in window], 200, block)

    @app.route("/clinic/memberships/<id>/pause", methods=["POST"])
    @endpoint(roles=[config.ROLE_FRONT_DESK, config.ROLE_PATIENT])
    def pause_membership(ctx, id):
        row = access.path_row("Membership", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        gates.state_gate(row, "Membership.status", ("ACTIVE",))
        credit = calc.membership_pause_credit_cents(row, store.now())
        row["pause_credit_cents"] += credit
        row["paused_at"] = store.now()
        row["status"] = "PAUSED"
        store.touch(row)
        return envelope.ok(serializers.membership(row))

    @app.route("/clinic/memberships/<id>/resume", methods=["POST"])
    @endpoint(roles=[config.ROLE_FRONT_DESK, config.ROLE_PATIENT])
    def resume_membership(ctx, id):
        row = access.path_row("Membership", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        gates.state_gate(row, "Membership.status", ("PAUSED",))
        elapsed = util.days_between(row["paused_at"], store.now())
        if row["pause_days_used"] + elapsed > config.MAX_PAUSE_DAYS_PER_YEAR:
            raise ApiError("ERR_PAUSE_LIMIT_EXCEEDED")                       # rung 35
        row["pause_days_used"] += elapsed
        row["period_end"] = util.add_days(row["period_end"], elapsed)
        row["pause_credit_cents"] -= min(row["pause_credit_cents"], row["monthly_fee_cents"])
        row["paused_at"] = None
        row["status"] = "ACTIVE"
        store.touch(row)
        return envelope.ok(serializers.membership(row))

    @app.route("/clinic/memberships/<id>/tier-change", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_FRONT_DESK, config.ROLE_CLINIC_ADMIN],
        specs=[
            field("tier", "enum", True, members=config.MEMBERSHIP_TIERS),
            field("expected_membership_version", "integer", True),
        ],
    )
    def tier_change(ctx, id):
        row = access.path_row("Membership", id)
        access.ownership(ctx)
        gates.terminal_gate(row, "Membership.status")                        # rung 11
        if ctx.get("expected_membership_version") != row["version"]:         # rung 12
            raise ApiError("ERR_STALE_MEMBERSHIP_VERSION")
        _apply_tier(row, ctx.get("tier"), store.now())
        row["included_visits_used"] = 0
        store.touch(row)
        return envelope.ok(serializers.membership(row))

    @app.route("/clinic/memberships/<id>/cancel", methods=["POST"])
    @endpoint(roles=[config.ROLE_FRONT_DESK, config.ROLE_PATIENT])
    def cancel_membership(ctx, id):
        row = access.path_row("Membership", id)
        access.ownership(ctx, patient_id=row["patient_id"])
        gates.state_gate(row, "Membership.status", ("ACTIVE", "PAUSED"))
        if row["status"] == "PAUSED":
            # Banked credit is redeemable only by resuming.
            row["pause_credit_cents"] = 0
        row["status"] = "CANCELLED"
        store.touch(row)
        return envelope.ok(serializers.membership(row))
