"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints only —
the database is empty at the start of each test. Setup calls use the lenient
`get_success_data` validator so that a broken precondition surfaces as a setup failure
rather than as a confusing assertion failure inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    cold_chain_event_payload,
    create_delivery_zone_payload,
    create_member_payload,
    create_pickup_hub_payload,
    create_pickup_window_payload,
    create_quota_ledger_payload,
    create_season_payload,
    create_share_plan_payload,
    create_subscription_payload,
    create_trip_payload,
    create_vessel_payload,
    record_landing_payload,
    recall_notice_payload,
    share_transfer_payload,
    substitution_payload,
)
from .test_users import (
    TEST_USERS,
    make_hub_operator_headers,
    make_member_headers,
    make_quality_officer_headers,
    make_vendor_headers,
)

ADMIN = TEST_USERS["admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]
QUALITY_OFFICER = TEST_USERS["quality_officer_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Catalogue primitives ─────────────────────────────────────────────────────

def new_season(**overrides) -> dict:
    return get_success_data(api_client.create_season(create_season_payload(**overrides), ADMIN))


def new_plan(season_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_share_plan(create_share_plan_payload(season_id, **overrides), ADMIN)
    )


def new_zone(**overrides) -> dict:
    return get_success_data(
        api_client.create_delivery_zone(create_delivery_zone_payload(**overrides), ADMIN)
    )


def new_hub(**overrides) -> dict:
    return get_success_data(
        api_client.create_pickup_hub(create_pickup_hub_payload(**overrides), ADMIN)
    )


def new_window(hub_id: str, season_id: str, week_index: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_pickup_window(
            hub_id, create_pickup_window_payload(season_id, week_index, **overrides), ADMIN
        )
    )


def new_member(**overrides) -> dict:
    return get_success_data(api_client.create_member(create_member_payload(**overrides), ADMIN))


def open_season(season_id: str) -> dict:
    return get_success_data(api_client.open_season(season_id, ADMIN))


def close_landings(season_id: str) -> dict:
    return get_success_data(api_client.close_landings(season_id, ADMIN))


def run_true_up(season_id: str) -> dict:
    return get_success_data(api_client.run_true_up(season_id, ADMIN))


# ─── Subscription primitives ──────────────────────────────────────────────────

def new_subscription(member_id: str, share_plan_id: str, season_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(member_id, share_plan_id, season_id, **overrides), ADMIN
        )
    )


def pay_subscription(subscription_id: str, amount_cents: int, headers=None) -> dict:
    return get_success_data(
        api_client.record_payment(subscription_id, {"amount_cents": amount_cents}, headers or ADMIN)
    )


def activate_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.activate_subscription(subscription_id, ADMIN))


def pause_subscription(subscription_id: str, headers=None) -> dict:
    return get_success_data(api_client.pause_subscription(subscription_id, headers or ADMIN))


def cancel_subscription(subscription_id: str, headers=None) -> dict:
    return get_success_data(api_client.cancel_subscription(subscription_id, headers or ADMIN))


# ─── Fleet primitives ─────────────────────────────────────────────────────────

def new_vessel(**overrides) -> dict:
    return get_success_data(api_client.create_vessel(create_vessel_payload(**overrides), ADMIN))


def new_ledger(vessel_id: str, season_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_quota_ledger(
            create_quota_ledger_payload(vessel_id, season_id, **overrides), ADMIN
        )
    )


def set_compliance(vessel_id: str, target_status: str) -> dict:
    return get_success_data(
        api_client.set_vessel_compliance(vessel_id, {"target_status": target_status}, ADMIN)
    )


def new_trip(vessel_id: str, season_id: str, quota_ledger_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trip(
            create_trip_payload(vessel_id, season_id, quota_ledger_id, **overrides), ADMIN
        )
    )


def land_catch(trip_id: str, vessel_id: str, species: str, landed_pounds_gross: float, **overrides) -> dict:
    return get_success_data(
        api_client.record_landing(
            trip_id,
            record_landing_payload(species, landed_pounds_gross, **overrides),
            make_vendor_headers(vessel_id),
        )
    )


def verify_landing(trip_id: str, accepted: bool = True) -> dict:
    return get_success_data(api_client.verify_landing(trip_id, {"accepted": accepted}, ADMIN))


def allocate(lot_id: str, week_index: int, expected_landing_lot_version: int) -> dict:
    return get_success_data(
        api_client.run_allocation(
            lot_id,
            {
                "week_index": week_index,
                "expected_landing_lot_version": expected_landing_lot_version,
            },
            ADMIN,
        )
    )


def split_lot(lot_id: str, destinations: list) -> dict:
    return get_success_data(api_client.split_lot(lot_id, {"destinations": destinations}, ADMIN))


def hub_destination(hub_id: str, pounds: float) -> dict:
    return {"destination_type": "HUB", "destination_id": hub_id, "pounds": pounds}


def route_destination(zone_id: str, pounds: float) -> dict:
    return {"destination_type": "ROUTE", "destination_id": zone_id, "pounds": pounds}


def sub_lots_of(lot_id: str) -> list:
    body = api_client.list_sub_lots(ADMIN, {"landing_lot_id": lot_id}).json()
    return body["data"]


def arrive_sub_lot(sub_lot_id: str, headers=None) -> dict:
    return get_success_data(api_client.arrive_sub_lot(sub_lot_id, headers or HUB_OP))


# ─── Delivery primitives ──────────────────────────────────────────────────────

def deliveries_of(subscription_id: str, **params) -> list:
    query = {"subscription_id": subscription_id}
    query.update(params)
    body = api_client.list_share_deliveries(ADMIN, query).json()
    return body["data"]


def delivery_of_week(subscription_id: str, week_index: int) -> dict:
    rows = deliveries_of(subscription_id, week_index=week_index)
    assert rows, f"Setup failed: no delivery for subscription {subscription_id} week {week_index}"
    return rows[0]


def pack_delivery(delivery_id: str, headers=None) -> dict:
    return get_success_data(api_client.pack_delivery(delivery_id, headers or HUB_OP))


def stage_delivery(delivery_id: str, window_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.stage_at_hub(delivery_id, {"pickup_window_id": window_id}, headers or HUB_OP)
    )


def dispatch_delivery(delivery_id: str, headers=None) -> dict:
    return get_success_data(api_client.dispatch_delivery(delivery_id, headers or HUB_OP))


def complete_delivery(delivery_id: str, headers=None) -> dict:
    return get_success_data(api_client.complete_delivery(delivery_id, headers or HUB_OP))


def pickup_delivery(delivery_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.record_pickup(delivery_id, make_member_headers(member_id))
    )


def open_window(window_id: str, headers=None) -> dict:
    return get_success_data(api_client.open_pickup_window(window_id, headers or HUB_OP))


def close_window(window_id: str, headers=None) -> dict:
    return get_success_data(api_client.close_pickup_window(window_id, headers or HUB_OP))


# ─── Cold chain, quality, settlement, recall primitives ───────────────────────

def log_leg(
    lot_id: str,
    custody_leg: str,
    minutes_above_threshold: int,
    peak_temp_c: float,
    headers=None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.log_cold_chain_event(
            cold_chain_event_payload(
                lot_id, custody_leg, minutes_above_threshold, peak_temp_c, **overrides
            ),
            headers or HUB_OP,
        )
    )


def disposition_lot(lot_id: str, disposition: str, officer_user_id: str = "qo-1") -> dict:
    return get_success_data(
        api_client.disposition_lot(
            lot_id, {"disposition": disposition}, make_quality_officer_headers(officer_user_id)
        )
    )


def new_settlement(trip_id: str, expected_trip_version: int) -> dict:
    return get_success_data(
        api_client.create_settlement(
            trip_id, {"expected_trip_version": expected_trip_version}, ADMIN
        )
    )


def finalize_settlement(statement_id: str) -> dict:
    return get_success_data(api_client.finalize_settlement(statement_id, ADMIN))


def pay_settlement(statement_id: str) -> dict:
    return get_success_data(api_client.pay_settlement(statement_id, ADMIN))


def file_skip(delivery_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.create_skip_request(
            {"share_delivery_id": delivery_id}, make_member_headers(member_id)
        )
    )


def revoke_skip(skip_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.revoke_skip_request(skip_id, make_member_headers(member_id))
    )


def new_transfer(
    from_subscription_id: str,
    to_subscription_id: str,
    season_id: str,
    effective_week_index: int,
    expected_subscription_version: int,
    headers=None,
) -> dict:
    return get_success_data(
        api_client.create_share_transfer(
            share_transfer_payload(
                from_subscription_id,
                to_subscription_id,
                season_id,
                effective_week_index,
                expected_subscription_version,
            ),
            headers or ADMIN,
        )
    )


def new_recall(lot_id: str, reason: str = "PATHOGEN") -> dict:
    return get_success_data(
        api_client.create_recall_notice(recall_notice_payload(lot_id, reason), ADMIN)
    )


def propose_substitution(delivery_id: str, substitute_lot_id: str, substitute_pounds: float) -> dict:
    return get_success_data(
        api_client.propose_substitution(
            delivery_id, substitution_payload(substitute_lot_id, substitute_pounds), ADMIN
        )
    )


# ─── Read-back helpers ────────────────────────────────────────────────────────

def read_season(season_id: str) -> dict:
    return get_success_data(api_client.get_season(season_id, ADMIN))


def read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_share_plan(plan_id, ADMIN))


def read_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def read_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def read_vessel(vessel_id: str) -> dict:
    return get_success_data(api_client.get_vessel(vessel_id, ADMIN))


def read_ledger(ledger_id: str) -> dict:
    return get_success_data(api_client.get_quota_ledger(ledger_id, ADMIN))


def read_trip(trip_id: str) -> dict:
    return get_success_data(api_client.get_trip(trip_id, ADMIN))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_landing_lot(lot_id, ADMIN))


def read_sub_lot(sub_lot_id: str) -> dict:
    return get_success_data(api_client.get_sub_lot(sub_lot_id, ADMIN))


def read_delivery(delivery_id: str) -> dict:
    return get_success_data(api_client.get_share_delivery(delivery_id, ADMIN))


def read_window(window_id: str) -> dict:
    return get_success_data(api_client.get_pickup_window(window_id, ADMIN))


def read_substitution(substitution_id: str) -> dict:
    return get_success_data(api_client.get_substitution(substitution_id, ADMIN))


def read_skip(skip_id: str) -> dict:
    return get_success_data(api_client.get_skip_request(skip_id, ADMIN))


def read_settlement(statement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(statement_id, ADMIN))


def read_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_share_transfer(transfer_id, ADMIN))


def read_recall(recall_id: str) -> dict:
    return get_success_data(api_client.get_recall_notice(recall_id, ADMIN))


# ─── Tier 1: season and catalogue ─────────────────────────────────────────────

def setup_open_season(
    offered_species=("SALMON",),
    ambient_band: str = "HOT",
    total_weeks: int = 20,
    plans=None,
    **season_overrides,
) -> dict:
    """Create a season with its plans and move it PLANNING -> OPEN.

    `plans` is a list of share-plan override dicts; the first one is the default plan.
    Opening requires at least one share plan to exist for the season.
    """
    season = new_season(
        offered_species=list(offered_species),
        ambient_band=ambient_band,
        total_weeks=total_weeks,
        **season_overrides,
    )
    plan_specs = plans if plans is not None else [{}]
    created = []
    for spec in plan_specs:
        created.append(new_plan(season["id"], **spec))
    open_season(season["id"])
    return {
        "season": season,
        "season_id": season["id"],
        "plan": created[0],
        "plans": created,
        "plans_by_code": {p["plan_code"]: p for p in created},
    }


def setup_fleet(
    season_id: str, species: str = "SALMON", management_area: str = "GOM-1", **ledger_overrides
) -> dict:
    """A COMPLIANT vessel holding one quota ledger for the given species and area."""
    vessel_overrides = ledger_overrides.pop("vessel", {})
    vessel = new_vessel(**vessel_overrides)
    ledger = new_ledger(
        vessel["id"],
        season_id,
        species=species,
        management_area=management_area,
        **ledger_overrides,
    )
    return {"vessel": vessel, "ledger": ledger, "vessel_id": vessel["id"], "ledger_id": ledger["id"]}


def setup_landed_lot(
    season_id: str,
    fleet: dict,
    species: str,
    landed_pounds_gross: float,
    management_area: str = None,
    gear_type: str = "HOOK_AND_LINE",
    **landing_overrides,
) -> dict:
    """Plan a trip against the fleet's ledger and record the landing on it."""
    area = management_area or fleet["ledger"]["management_area"]
    trip = new_trip(
        fleet["vessel_id"],
        season_id,
        fleet["ledger_id"],
        gear_type=gear_type,
        management_area=area,
    )
    lot = land_catch(
        trip["id"], fleet["vessel_id"], species, landed_pounds_gross, **landing_overrides
    )
    return {"trip": trip, "lot": lot, "trip_id": trip["id"], "lot_id": lot["id"]}


# ─── Tier 2: members and subscriptions ────────────────────────────────────────

def setup_member_subscription(
    season_id: str,
    plan_id: str,
    full_name: str = "Mara One",
    email: str = "m1@csf.test",
    paid_cents: int = 0,
    activate: bool = True,
    member_overrides=None,
    **subscription_overrides,
) -> dict:
    """Create a member, their subscription, optionally pay and activate it."""
    member = new_member(full_name=full_name, email=email, **(member_overrides or {}))
    subscription = new_subscription(member["id"], plan_id, season_id, **subscription_overrides)
    if paid_cents:
        pay_subscription(subscription["id"], paid_cents)
    if activate:
        subscription = activate_subscription(subscription["id"])
    return {
        "member": member,
        "member_id": member["id"],
        "subscription": subscription,
        "subscription_id": subscription["id"],
    }


# ─── Tier 3: the hub-pickup pipeline ──────────────────────────────────────────

def setup_hub_box_allocated(
    pool_pounds: float = 5.00,
    species: str = "SALMON",
    plan_overrides=None,
    paid_cents: int = 90000,
    ambient_band: str = "HOT",
    hub_overrides=None,
    week_index: int = 1,
    offered_species=("SALMON",),
) -> dict:
    """One ACTIVE hub-pickup member whose week box has been allocated a whole lot.

    Chain: season -> plan -> hub -> member -> subscription -> activate -> vessel ->
    ledger -> trip -> landing -> allocation.
    """
    ctx = setup_open_season(
        offered_species=offered_species,
        ambient_band=ambient_band,
        plans=[plan_overrides or {}],
    )
    hub = new_hub(**(hub_overrides or {}))
    ctx["hub"] = hub
    ctx["hub_id"] = hub["id"]
    ctx.update(
        setup_member_subscription(
            ctx["season_id"],
            ctx["plan"]["id"],
            paid_cents=paid_cents,
            join_week_index=1,
            fulfillment_mode="HUB_PICKUP",
            pickup_hub_id=hub["id"],
        )
    )
    fleet = setup_fleet(ctx["season_id"], species=species)
    ctx.update(fleet)
    landing = setup_landed_lot(ctx["season_id"], fleet, species, pool_pounds)
    ctx.update(landing)
    allocated_lot = allocate(landing["lot_id"], week_index, landing["lot"]["version"])
    ctx["lot"] = allocated_lot
    ctx["delivery"] = delivery_of_week(ctx["subscription_id"], week_index)
    ctx["delivery_id"] = ctx["delivery"]["id"]
    ctx["week_index"] = week_index
    return ctx


def setup_hub_box_packed(**kwargs) -> dict:
    """As `setup_hub_box_allocated`, then split the lot to the hub and pack the box."""
    ctx = setup_hub_box_allocated(**kwargs)
    split_lot(ctx["lot_id"], [hub_destination(ctx["hub_id"], ctx["lot"]["allocated_pounds_total"])])
    ctx["sub_lot"] = sub_lots_of(ctx["lot_id"])[0]
    ctx["sub_lot_id"] = ctx["sub_lot"]["id"]
    ctx["delivery"] = pack_delivery(ctx["delivery_id"])
    return ctx


def setup_hub_box_staged(
    window_overrides=None,
    open_the_window: bool = False,
    clock_at_open: str = "2026-05-04T13:00:00Z",
    **kwargs,
) -> dict:
    """As `setup_hub_box_packed`, then create the week's window and stage the box into it."""
    ctx = setup_hub_box_packed(**kwargs)
    window = new_window(
        ctx["hub_id"], ctx["season_id"], ctx["week_index"], **(window_overrides or {})
    )
    ctx["window"] = window
    ctx["window_id"] = window["id"]
    ctx["delivery"] = stage_delivery(ctx["delivery_id"], window["id"])
    if open_the_window:
        set_clock(clock_at_open)
        ctx["window"] = open_window(window["id"])
    return ctx


# ─── Tier 3: the home-delivery pipeline ───────────────────────────────────────

def setup_home_delivery_box_allocated(
    pool_pounds: float,
    plan_overrides=None,
    zone_overrides=None,
    ambient_band: str = "HOT",
    paid_cents: int = 104000,
    species: str = "COD",
    offered_species=("COD",),
) -> dict:
    """One ACTIVE home-delivery member whose week-1 box has been allocated a whole lot."""
    ctx = setup_open_season(
        offered_species=offered_species,
        ambient_band=ambient_band,
        plans=[plan_overrides or {}],
    )
    zone = new_zone(**(zone_overrides or {}))
    ctx["zone"] = zone
    ctx["zone_id"] = zone["id"]
    ctx.update(
        setup_member_subscription(
            ctx["season_id"],
            ctx["plan"]["id"],
            paid_cents=paid_cents,
            join_week_index=1,
            fulfillment_mode="HOME_DELIVERY",
            delivery_zone_id=zone["id"],
        )
    )
    fleet = setup_fleet(ctx["season_id"], species=species, management_area="GOM-2")
    ctx.update(fleet)
    landing = setup_landed_lot(ctx["season_id"], fleet, species, pool_pounds)
    ctx.update(landing)
    ctx["lot"] = allocate(landing["lot_id"], 1, landing["lot"]["version"])
    ctx["delivery"] = delivery_of_week(ctx["subscription_id"], 1)
    ctx["delivery_id"] = ctx["delivery"]["id"]
    return ctx


def setup_home_delivery_box_split(**kwargs) -> dict:
    """As `setup_home_delivery_box_allocated`, then split the lot onto the route."""
    ctx = setup_home_delivery_box_allocated(**kwargs)
    split_lot(
        ctx["lot_id"], [route_destination(ctx["zone_id"], ctx["lot"]["allocated_pounds_total"])]
    )
    ctx["sub_lot"] = sub_lots_of(ctx["lot_id"])[0]
    ctx["sub_lot_id"] = ctx["sub_lot"]["id"]
    return ctx


# ─── Tier 4: allocation arithmetic ────────────────────────────────────────────

def setup_three_share_week1(pool_pounds: float, species: str = "SALMON") -> dict:
    """Three eligible week-1 boxes on MEDIUM, LARGE and SMALL plans, activated in that order.

    The activation order fixes the deliveries' `created_at` order as MEDIUM, LARGE, SMALL,
    which is the tie-break the allocation's fixed order falls back on.
    """
    ctx = setup_open_season(
        offered_species=(species,),
        plans=[
            {"plan_code": "MED-PREM-W", "share_size": "MEDIUM"},
            {"plan_code": "LRG-PREM-W", "share_size": "LARGE"},
            {"plan_code": "SML-PREM-W", "share_size": "SMALL"},
        ],
    )
    hub = new_hub(cooler_slots_default=6)
    ctx["hub"] = hub
    ctx["hub_id"] = hub["id"]

    plans = ctx["plans_by_code"]
    for label, code, name, email in (
        ("med", "MED-PREM-W", "Mara One", "m1@csf.test"),
        ("lrg", "LRG-PREM-W", "Nils Two", "m2@csf.test"),
        ("sml", "SML-PREM-W", "Oona Three", "m3@csf.test"),
    ):
        part = setup_member_subscription(
            ctx["season_id"],
            plans[code]["id"],
            full_name=name,
            email=email,
            join_week_index=1,
            fulfillment_mode="HUB_PICKUP",
            pickup_hub_id=hub["id"],
        )
        ctx[f"member_{label}"] = part["member"]
        ctx[f"subscription_{label}"] = part["subscription"]

    fleet = setup_fleet(ctx["season_id"], species=species)
    ctx.update(fleet)
    landing = setup_landed_lot(ctx["season_id"], fleet, species, pool_pounds)
    ctx.update(landing)
    for label in ("med", "lrg", "sml"):
        ctx[f"delivery_{label}"] = delivery_of_week(ctx[f"subscription_{label}"]["id"], 1)
    return ctx


# ─── Tier 4: substitution ─────────────────────────────────────────────────────

def setup_under_filled_box_with_substitute_lot(
    member_overrides=None,
    offered_species=("SALMON", "COD"),
    with_haddock_lot: bool = False,
    pack_the_box: bool = False,
    paid_cents: int = 0,
) -> dict:
    """A week-1 MEDIUM box allocated 3.00 lb of SALMON against a 5.00 lb target.

    The box is therefore UNDER_FILLED with a 2.00 lb shortfall, and a separate 6.00 lb
    COD lot stands RECORDED and CLEAR with every pound uncommitted. When `pack_the_box`
    is set the lot is split to the hub and the box is packed first, so the delivery
    carries its own priced invoice before any substitution is proposed.
    """
    ctx = setup_open_season(offered_species=offered_species)
    hub = new_hub()
    ctx["hub"] = hub
    ctx["hub_id"] = hub["id"]
    ctx.update(
        setup_member_subscription(
            ctx["season_id"],
            ctx["plan"]["id"],
            paid_cents=paid_cents,
            join_week_index=1,
            fulfillment_mode="HUB_PICKUP",
            pickup_hub_id=hub["id"],
            member_overrides=member_overrides,
        )
    )
    fleet = setup_fleet(ctx["season_id"], species="SALMON", management_area="GOM-1")
    ctx.update(fleet)
    salmon = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 3.00)
    ctx["salmon_trip"] = salmon["trip"]
    ctx["lot"] = allocate(salmon["lot_id"], 1, salmon["lot"]["version"])
    ctx["lot_id"] = salmon["lot_id"]

    cod_ledger = new_ledger(
        ctx["vessel_id"], ctx["season_id"], species="COD", management_area="GOM-2"
    )
    cod_fleet = {"vessel": ctx["vessel"], "ledger": cod_ledger,
                 "vessel_id": ctx["vessel_id"], "ledger_id": cod_ledger["id"]}
    cod = setup_landed_lot(
        ctx["season_id"], cod_fleet, "COD", 6.00, ex_vessel_price_cents_per_lb=700
    )
    ctx["cod_lot"] = cod["lot"]
    ctx["cod_lot_id"] = cod["lot_id"]

    if with_haddock_lot:
        haddock_ledger = new_ledger(
            ctx["vessel_id"], ctx["season_id"], species="HADDOCK", management_area="GOM-5"
        )
        haddock_fleet = {"vessel": ctx["vessel"], "ledger": haddock_ledger,
                         "vessel_id": ctx["vessel_id"], "ledger_id": haddock_ledger["id"]}
        haddock = setup_landed_lot(
            ctx["season_id"], haddock_fleet, "HADDOCK", 6.00, ex_vessel_price_cents_per_lb=700
        )
        ctx["haddock_lot"] = haddock["lot"]
        ctx["haddock_lot_id"] = haddock["lot_id"]

    ctx["delivery"] = delivery_of_week(ctx["subscription_id"], 1)
    ctx["delivery_id"] = ctx["delivery"]["id"]

    if pack_the_box:
        split_lot(ctx["lot_id"], [hub_destination(ctx["hub_id"], 3.00)])
        ctx["sub_lot"] = sub_lots_of(ctx["lot_id"])[0]
        ctx["sub_lot_id"] = ctx["sub_lot"]["id"]
        ctx["delivery"] = pack_delivery(ctx["delivery_id"])
    return ctx


# ─── Tier 5: settlement, no-show sweep and season close ───────────────────────

def setup_verified_cod_landing(landed_pounds_gross: float = 10.04) -> dict:
    """A verified COD landing ready for settlement creation.

    10.04 lb at 850 cents ex-vessel with 12 offload minutes on HOOK_AND_LINE gear gives
    a GREEN band, which is the figure set the PRD works through in its settlement example.
    """
    ctx = setup_open_season(
        offered_species=("COD",),
        plans=[{"plan_code": "LRG-WHITE-W", "share_size": "LARGE", "species_tier": "WHITEFISH"}],
    )
    fleet = setup_fleet(ctx["season_id"], species="COD", management_area="GOM-2")
    ctx.update(fleet)
    landing = setup_landed_lot(ctx["season_id"], fleet, "COD", landed_pounds_gross)
    ctx.update(landing)
    verified = verify_landing(landing["trip_id"], accepted=True)
    ctx["trip"] = verified
    ctx["trip_version"] = verified["version"]
    return ctx


def setup_no_show_sequence(close_second_window: bool = True) -> dict:
    """Two staged hub boxes in consecutive weeks, both left uncollected.

    After the week-1 window closes past its grace tail the member stands at one no-show
    and WARNED. When `close_second_window` is set the week-2 window is closed too, which
    is what drives the second no-show.
    """
    ctx = setup_hub_box_staged(
        pool_pounds=5.00,
        paid_cents=90000,
        window_overrides={"cooler_slots_total": 2},
    )
    ctx["window_1"] = ctx["window"]
    ctx["window_1_id"] = ctx["window_id"]
    ctx["delivery_1"] = ctx["delivery"]
    ctx["delivery_1_id"] = ctx["delivery_id"]
    ctx["lot_1_id"] = ctx["lot_id"]

    fleet = {"vessel": ctx["vessel"], "ledger": ctx["ledger"],
             "vessel_id": ctx["vessel_id"], "ledger_id": ctx["ledger_id"]}
    landing2 = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)
    lot2 = allocate(landing2["lot_id"], 2, landing2["lot"]["version"])
    split_lot(landing2["lot_id"], [hub_destination(ctx["hub_id"], 5.00)])
    delivery2 = delivery_of_week(ctx["subscription_id"], 2)
    pack_delivery(delivery2["id"])
    window2 = new_window(
        ctx["hub_id"],
        ctx["season_id"],
        2,
        opens_at="2026-05-11T12:00:00Z",
        closes_at="2026-05-11T18:00:00Z",
        cooler_slots_total=2,
    )
    stage_delivery(delivery2["id"], window2["id"])
    ctx["lot_2"] = lot2
    ctx["lot_2_id"] = landing2["lot_id"]
    ctx["delivery_2"] = delivery2
    ctx["delivery_2_id"] = delivery2["id"]
    ctx["window_2"] = window2
    ctx["window_2_id"] = window2["id"]

    set_clock("2026-05-04T12:00:00Z")
    open_window(ctx["window_1_id"])
    set_clock("2026-05-04T19:31:00Z")
    close_window(ctx["window_1_id"])
    set_clock("2026-05-11T12:00:00Z")
    open_window(window2["id"])
    set_clock("2026-05-11T19:31:00Z")
    if close_second_window:
        close_window(window2["id"])
    return ctx


def setup_transfer_pair(payment_basis: str = "PREPAID_FULL_SEASON", paid_cents: int = 82800) -> dict:
    """An ACTIVE transferring subscription and a WAITLISTED receiving one in the same season."""
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    ctx["hub"] = hub
    ctx["hub_id"] = hub["id"]
    transferor = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Mara One",
        email="m1@csf.test",
        paid_cents=paid_cents,
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
        payment_basis=payment_basis,
    )
    transferee_member = new_member(full_name="Nils Two", email="m2@csf.test")
    transferee = new_subscription(
        transferee_member["id"],
        ctx["plan"]["id"],
        ctx["season_id"],
        join_week_index=11,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
        waitlist_requested=True,
    )
    ctx["transferor_member"] = transferor["member"]
    ctx["transferor"] = transferor["subscription"]
    ctx["transferor_id"] = transferor["subscription_id"]
    ctx["transferor_version"] = transferor["subscription"]["version"]
    ctx["transferee_member"] = transferee_member
    ctx["transferee"] = transferee
    ctx["transferee_id"] = transferee["id"]
    return ctx
