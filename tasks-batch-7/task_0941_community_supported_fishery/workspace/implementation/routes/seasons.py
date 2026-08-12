"""Seasons, share plans and the logical clock (PRD 3.1, 3.9)."""
from flask import Blueprint, request

import authz
import calc
import clock
import constants as C
import guards
import lookup
import store
import validate as V
from routes.common import created, filter_eq, listing, ok, ok_raw, always

bp = Blueprint("seasons", __name__)


# --------------------------------------------------------------------------
# POST /csf/seasons
# --------------------------------------------------------------------------
@bp.post("/seasons")
def create_season():
    authz.require_roles(C.ROLE_ADMIN)                                    # rungs 1-3
    body = V.body_of(request)
    V.require(body, "season_code", "start_date", "end_date", "total_weeks",
              "offered_species")                                        # rung 4
    ambient_band = body.get("ambient_band", "MILD")
    if ambient_band is None:
        ambient_band = "MILD"
    V.enum_field(ambient_band, C.AMBIENT_BANDS, "ambient_band")          # rung 5
    season_code = V.string_field(body["season_code"], "season_code", 1, 32)  # rung 6
    start_date = V.datetime_field(body["start_date"], "start_date")
    end_date = V.datetime_field(body["end_date"], "end_date")
    total_weeks = V.int_field(body["total_weeks"], "total_weeks", 1, 40)
    offered = V.string_array_field(body["offered_species"], "offered_species",
                                   allow_empty=False)
    lead = body.get("landing_commit_lead_hours")
    lead = C.DEFAULT_LANDING_COMMIT_LEAD_HOURS if lead is None else \
        V.int_field(lead, "landing_commit_lead_hours", 0, 336)
    guards.unique("Season", lambda s: s["season_code"] == season_code)    # rung 53

    rec = store.create("Season", {
        "season_code": season_code, "start_date": start_date,
        "end_date": end_date, "total_weeks": total_weeks,
        "ambient_band": ambient_band, "offered_species": offered,
        "landing_commit_lead_hours": lead, "status": "PLANNING",
        "shortfall_flag_count": 0, "true_up_run_at": None,
    })
    return created(rec)


@bp.get("/seasons/<sid>")
def read_season(sid):
    authz.require_roles(*C.ALL_ROLES)
    return ok(lookup.season(sid))


# --------------------------------------------------------------------------
# POST /csf/seasons/{id}/open
# --------------------------------------------------------------------------
@bp.post("/seasons/<sid>/open")
def open_season(sid):
    authz.require_roles(C.ROLE_ADMIN)
    season = lookup.season(sid)                                          # rung 7
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "PLANNING")                             # rung 25
    # The transition's second precondition: "at least one share plan already
    # exist for it" (PRD 3.1).  No dedicated code exists for an unmet transition
    # precondition, so it lands on rung 28's ERR_INVALID_STATE.
    guards.state_require(
        any(p["season_id"] == season["id"] for p in store.all_of("SharePlan")),
        "A season cannot be opened before at least one share plan exists for it.")
    season["status"] = "OPEN"
    store.touch(season)
    return ok(season)


# --------------------------------------------------------------------------
# POST /csf/seasons/{id}/close-landings
# --------------------------------------------------------------------------
@bp.post("/seasons/<sid>/close-landings")
def close_landings(sid):
    authz.require_roles(C.ROLE_ADMIN)
    season = lookup.season(sid)
    guards.season_not_closed(season)
    guards.season_status(season, "OPEN")
    season["status"] = "LANDINGS_CLOSED"
    store.touch(season)
    for transfer in store.ordered("ShareTransfer",
                                  lambda t: t["season_id"] == season["id"]
                                  and t["status"] == "REQUESTED"):
        transfer["status"] = "EXPIRED"
        store.touch(transfer)
    return ok(season)


# --------------------------------------------------------------------------
# POST /csf/seasons/{id}/true-up
# --------------------------------------------------------------------------
@bp.post("/seasons/<sid>/true-up")
def true_up(sid):
    authz.require_roles(C.ROLE_ADMIN)
    season = lookup.season(sid)
    # rung 24 carve-out: "the season true-up call itself".
    guards.season_status(season, "LANDINGS_CLOSED")                      # rung 25
    guards.state_require(season["true_up_run_at"] is None,
                         "The true-up has already run for this season.")

    subs = store.ordered("Subscription",
                         lambda s: s["season_id"] == season["id"]
                         and s["lifecycle_status"] in ("ACTIVE", "PAUSED", "PAST_DUE"))
    for sub in subs:
        # banked skip credit is spent first
        applied, expired = calc.skip_credit_expiry(
            sub["commitment_cents"], sub["paid_cents"],
            sub["skip_credit_balance_cents"])
        sub["paid_cents"] = sub["paid_cents"] + applied
        sub["expired_credit_cents"] = expired
        sub["skip_credit_balance_cents"] = 0

        undelivered = (sub["promised_delivery_count"] - sub["delivered_count"]
                       - sub["credited_count"] - sub["member_fault_count"]
                       - sub["skip_credited_count"])
        sub["undelivered_count"] = undelivered
        base_owed = (sub["credited_count"] + undelivered) * sub["price_per_delivery_cents"]
        sub["true_up_amount_cents"] = base_owed

        if sub["payment_basis"] == "PREPAID_FULL_SEASON" and \
                base_owed >= C.TRUE_UP_MIN_REFUND_CENTS:
            sub["true_up_status"] = "REFUNDED"
            sub["rollover_credit_cents"] = 0
            sub["billing_status"] = "REFUND_PENDING"
        else:
            sub["true_up_status"] = "CREDITED"
            sub["rollover_credit_cents"] = base_owed

        sub["lifecycle_status"] = "COMPLETED"
        sub["billing_status"] = "SETTLED"
        store.touch(sub)

    season["true_up_run_at"] = clock.now()
    season["status"] = "CLOSED"
    store.touch(season)
    return ok(season)


# --------------------------------------------------------------------------
# Share plans
# --------------------------------------------------------------------------
@bp.post("/share-plans")
def create_share_plan():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "season_id", "plan_code", "share_size", "delivery_frequency",
              "species_tier")                                            # rung 4
    share_size = V.enum_field(body["share_size"], C.SHARE_SIZES, "share_size")
    frequency = V.enum_field(body["delivery_frequency"], C.DELIVERY_FREQUENCIES,
                             "delivery_frequency")
    tier = V.enum_field(body["species_tier"], C.SPECIES_TIERS, "species_tier")  # rung 5
    plan_code = V.string_field(body["plan_code"], "plan_code", 1, 32)    # rung 6
    V.id_field(body["season_id"], "season_id")
    season = lookup.season(body["season_id"])                            # rung 7
    guards.season_not_closed(season)                                     # rung 24
    guards.unique("SharePlan", lambda p: p["season_id"] == season["id"]
                  and p["plan_code"] == plan_code)                       # rung 53

    price = calc.share_price_per_delivery(share_size, tier, frequency)
    units, target, floor = calc.plan_physicals(share_size)
    rec = store.create("SharePlan", {
        "season_id": season["id"], "plan_code": plan_code,
        "share_size": share_size, "delivery_frequency": frequency,
        "species_tier": tier, "price_per_delivery_cents": price,
        "weight_units": units, "target_pounds_per_delivery": target,
        "min_floor_pounds": floor,
        "scheduled_delivery_count": calc.scheduled_delivery_count(
            season["total_weeks"], frequency),
    })
    return created(rec)


@bp.get("/share-plans/<pid>")
def read_share_plan(pid):
    authz.require_roles(*C.ALL_ROLES)
    return ok(lookup.share_plan(pid))


@bp.get("/share-plans")
def list_share_plans():
    authz.require_roles(*C.ALL_ROLES)
    pred = filter_eq(request.args, "season_id", lambda r: r["season_id"], always)
    return listing("SharePlan", request.args, pred)


# --------------------------------------------------------------------------
# POST /csf/_clock/set_current_utc
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "to_iso8601")                                        # rung 4
    instant = V.datetime_field(body["to_iso8601"], "to_iso8601")         # rung 6
    # rung 24 carve-out: "the logical-clock setter".
    clock.CLOCK.set(instant)
    return ok_raw({"current_utc": clock.render_instant(instant)})
