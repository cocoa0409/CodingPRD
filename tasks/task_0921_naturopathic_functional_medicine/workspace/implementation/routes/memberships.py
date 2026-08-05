"""Membership cycles, entitlement pools, pause/resume, tier change and roll."""

import math
from datetime import timedelta

from flask import Blueprint

import config
import ladder
from clock import clock, parse_date, parse_instant, render_date
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers
from services.money import ceil_units, dec, round_half_up

bp = Blueprint("memberships", __name__)


def _cycle_end(start_date):
    return start_date + timedelta(days=config.MEMBERSHIP_CYCLE_DAYS - 1)


@bp.route("/memberships", methods=["POST"])
def create_membership():
    def overlap_check(ctx):
        patient = ctx.fk["patient_id"]
        start = parse_date(ctx.body["cycle_start_date"])
        end = _cycle_end(start)
        for row in db.memberships.values():
            if row["patient_id"] != patient["id"]:
                continue
            if row["status"] not in ("ACTIVE", "PAUSED"):
                continue
            other_start = parse_date(row["cycle_start_date"])
            other_end = parse_date(row["cycle_end_date"])
            # CLOSED on both ends: touching cycles DO collide.
            if start <= other_end and other_start <= end:
                raise ApiError("ERR_MEMBERSHIP_CYCLE_OVERLAP")

    def handler(ctx):
        patient = ctx.fk["patient_id"]
        tier_name = ctx.body["tier"]
        tier = config.MEMBERSHIP_TIERS[tier_name]
        start = parse_date(ctx.body["cycle_start_date"])
        row = make_row(
            patient_id=patient["id"],
            tier=tier_name,
            status="ACTIVE",
            cycle_start_date=render_date(start),
            cycle_end_date=render_date(_cycle_end(start)),
            cycle_index=1,
            paused_at=None,
            paused_days_total=0,
            monthly_fee_cents=tier["monthly_fee_cents"],
            dispensary_discount_pct=tier["dispensary_discount_pct"],
            includes_messaging=tier["includes_messaging"],
            visits_granted=tier["included_visits"],
            visits_consumed=0,
            visits_remaining=tier["included_visits"],
            visits_forfeited=0,
            lab_credits_granted=tier["included_lab_credits"],
            lab_credits_consumed=0,
            lab_credits_remaining=tier["included_lab_credits"],
            lab_credits_forfeited=0,
            last_proration_net_charge_cents=0,
        )
        db.memberships[row["id"]] = row
        if patient["clinical_status"] == "INACTIVE":
            patient["clinical_status"] = "ESTABLISHED"
            bump(patient)
        return serializers.membership(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "body_fks": ["patient_id"],
            "shape": [
                ("patient_id", "string", True),
                ("tier", "string", True),
                ("cycle_start_date", "date", True),
            ],
            "enums": {"tier": config.TIERS},
            "business": [overlap_check],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/patients/<pid>/memberships", methods=["GET"])
def list_patient_memberships(pid):
    def handler(ctx):
        rows = ordered(
            [
                m
                for m in db.memberships.values()
                if m["patient_id"] == ctx.path["patient"]["id"]
            ]
        )
        status = ctx.args_get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return ladder.list_result(ctx, rows, serializers.membership)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_BILLING,
                config.ROLE_PATIENT,
            ],
            "path": [("patient", pid)],
            "owner": lambda ctx: ctx.path["patient"]["id"],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/memberships/<mid>/pause", methods=["POST"])
def pause_membership(mid):
    def own_state(ctx):
        if ctx.path["membership"]["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        row = ctx.path["membership"]
        row["status"] = "PAUSED"
        row["paused_at"] = clock.stamp()
        bump(row)
        return serializers.membership(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "path": [("membership", mid)],
            "own_state": own_state,
            "shape": [],
            "handler": handler,
        }
    )


@bp.route("/memberships/<mid>/resume", methods=["POST"])
def resume_membership(mid):
    def own_state(ctx):
        if ctx.path["membership"]["status"] != "PAUSED":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        row = ctx.path["membership"]
        paused_at = parse_instant(row["paused_at"])
        paused_days = 0
        if paused_at is not None:
            elapsed = clock.now() - paused_at
            paused_days = max(0, int(math.ceil(elapsed.total_seconds() / 86400.0)))
        row["paused_days_total"] += paused_days
        row["cycle_end_date"] = render_date(
            parse_date(row["cycle_end_date"]) + timedelta(days=paused_days)
        )
        row["paused_at"] = None
        row["status"] = "ACTIVE"
        bump(row)
        return serializers.membership(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "path": [("membership", mid)],
            "own_state": own_state,
            "shape": [],
            "handler": handler,
        }
    )


@bp.route("/memberships/<mid>/tier", methods=["PATCH"])
def change_tier(mid):
    def handler(ctx):
        row = ctx.path["membership"]
        old_tier = config.MEMBERSHIP_TIERS[row["tier"]]
        new_tier_name = ctx.body["new_tier"]
        new_tier = config.MEMBERSHIP_TIERS[new_tier_name]
        cycle_days = config.MEMBERSHIP_CYCLE_DAYS

        # STEP 1-2: elapsed days are counted HALF-OPEN from the cycle start.
        elapsed_days = (clock.today() - parse_date(row["cycle_start_date"])).days
        remaining_days = max(cycle_days - elapsed_days, 0)

        # STEP 3-5: money legs read remaining_days before the entitlement legs run.
        old_unused = round_half_up(
            dec(old_tier["monthly_fee_cents"]) * dec(remaining_days) / dec(cycle_days)
        )
        new_prorated = round_half_up(
            dec(new_tier["monthly_fee_cents"]) * dec(remaining_days) / dec(cycle_days)
        )
        net = new_prorated - old_unused
        row["last_proration_net_charge_cents"] = net

        # STEP 6-7: entitlement grants round UP to whole units.
        visit_grant = ceil_units(
            dec(new_tier["included_visits"]) * dec(remaining_days) / dec(cycle_days)
        )
        credit_grant = ceil_units(
            dec(new_tier["included_lab_credits"])
            * dec(remaining_days)
            / dec(cycle_days)
        )

        # STEP 8-9: remove the old remaining before adding the new grant so that
        # consumed and forfeited are untouched and the identity survives.
        row["visits_granted"] = row["visits_granted"] - row["visits_remaining"] + visit_grant
        row["visits_remaining"] = visit_grant
        row["lab_credits_granted"] = (
            row["lab_credits_granted"] - row["lab_credits_remaining"] + credit_grant
        )
        row["lab_credits_remaining"] = credit_grant

        # STEP 10
        row["tier"] = new_tier_name
        row["monthly_fee_cents"] = new_tier["monthly_fee_cents"]
        row["dispensary_discount_pct"] = new_tier["dispensary_discount_pct"]
        row["includes_messaging"] = new_tier["includes_messaging"]

        patient = db.patients.get(row["patient_id"])
        if patient is not None and net != 0:
            if net > 0:
                patient["cash_charged_total_cents"] += net
            else:
                patient["cash_refunded_total_cents"] += abs(net)
            touch(patient)
        bump(row)
        return serializers.membership(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "path": [("membership", mid)],
            "occ": ("expected_membership_version", lambda ctx: ctx.path["membership"]),
            "shape": [
                ("new_tier", "string", True),
                ("expected_membership_version", "int", True),
            ],
            "enums": {"new_tier": config.TIERS},
            "handler": handler,
        }
    )


@bp.route("/memberships/<mid>/roll-cycle", methods=["POST"])
def roll_cycle(mid):
    def own_state(ctx):
        if ctx.path["membership"]["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        row = ctx.path["membership"]
        renew = ctx.body["renew"]
        tier = config.MEMBERSHIP_TIERS[row["tier"]]

        row["visits_forfeited"] += row["visits_remaining"]
        row["lab_credits_forfeited"] += row["lab_credits_remaining"]

        if renew:
            row["visits_granted"] += tier["included_visits"]
            row["lab_credits_granted"] += tier["included_lab_credits"]
            row["visits_remaining"] = tier["included_visits"]
            row["lab_credits_remaining"] = tier["included_lab_credits"]
            row["cycle_index"] += 1
            new_start = parse_date(row["cycle_end_date"]) + timedelta(days=1)
            row["cycle_start_date"] = render_date(new_start)
            row["cycle_end_date"] = render_date(_cycle_end(new_start))
        else:
            row["visits_remaining"] = 0
            row["lab_credits_remaining"] = 0
            row["status"] = "EXPIRED"
            patient = db.patients.get(row["patient_id"])
            if patient is not None and patient["clinical_status"] == "ESTABLISHED":
                patient["clinical_status"] = "INACTIVE"
                bump(patient)
        bump(row)
        return serializers.membership(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "path": [("membership", mid)],
            "own_state": own_state,
            "shape": [("renew", "bool", True)],
            "handler": handler,
        }
    )
