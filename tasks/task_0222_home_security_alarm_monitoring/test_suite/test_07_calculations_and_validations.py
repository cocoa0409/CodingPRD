"""Calculation corners (permit fee variants, dispatch fee, ETF boundary, battery
boundary) and validation corners (duplicate zone, cellular entitlement, second
active permit, open-dispatch blocks change-plan).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_admin_headers,
    make_operator_headers,
    make_subscriber_headers,
    set_clock,
    create_plan,
    create_account,
    create_system,
    create_sensor,
    issue_permit,
    ingest_route_dispatch,
    dispatch_for_event,
    setup_activated_account,
    setup_activated_armed_account,
    create_permit_payload,
    create_sensor_payload,
    create_system_payload,
    change_plan_payload,
    arm_payload,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

BASIC = dict(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
             max_sensors=8, cellular_backup_included=False)
PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
           max_sensors=32, cellular_backup_included=True)
PLUS = dict(tier="PLUS", monthly_fee_cents=3100, police_dispatch_included=True,
            max_sensors=16, cellular_backup_included=True)


# ─── calculations ────────────────────────────────────────────────────────────

def test_permit_fee_residential_ontime_base_only(api):
    """PRD §3.8: "The base is 5000 cents, plus a commercial uplift of 3000 cents
    when the account's `premises_type` is `COMMERCIAL` (and nothing extra for a
    `RESIDENTIAL` premises). The late penalty is zero when `filed_days_late` is
    zero."

    Design: Corner/calculations/permit_fee_residential_ontime_base_only
    """
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"], premises_type="RESIDENTIAL")
    permit = validate_success(
        api.create_permit(create_permit_payload(acct["id"], "P-RES-1", filed_days_late=0), ADMIN), 201)
    assert permit["fee_total_cents"] == 5000


def test_permit_fee_residential_45_days_late_uncapped(api):
    """PRD §3.8: "the penalty is the base permit fee of 5000 cents multiplied by
    20 percent per late period, where the number of late periods is
    `filed_days_late` divided by 30 and rounded up to the next whole period; that
    product is rounded half up to whole cents and then capped at 4000 cents."

    Design: Corner/calculations/permit_fee_residential_45_days_late_uncapped_penalty
    """
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"], premises_type="RESIDENTIAL")
    permit = validate_success(
        api.create_permit(create_permit_payload(acct["id"], "P-RES-45", filed_days_late=45), ADMIN), 201)
    # penalty = round(5000*0.20*ceil(45/30)) = round(5000*0.20*2) = 2000 (< cap);
    # fee = 5000 + 2000 = 7000.
    assert permit["fee_total_cents"] == 7000


def test_dispatch_fee_police_charged_on_basic_plan(api):
    """PRD §3.6: "a police dispatch costs nothing when the account's plan has
    `police_dispatch_included` true, but 2500 cents when that flag is false."

    Design: Corner/calculations/dispatch_fee_police_included_zero_vs_basic_charged
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_armed_account(plan_overrides=BASIC,
                                        system_overrides={"primary_path": "BROADBAND"},
                                        sensor_overrides={"sensor_type": "MOTION"})
    dispatched = ingest_route_dispatch(ctx["system"]["id"], ctx["sensor"]["id"], "BURGLARY")
    assert dispatched["routed_service"] == "POLICE"
    disp = dispatch_for_event(dispatched["id"])
    assert disp["fee_cents"] == 2500, "BASIC plan (police not included) charges 2500"


def test_etf_zero_when_term_elapsed(api):
    """PRD §3.2: "Remaining months is the committed `contract_term_months` minus
    those elapsed months, but never less than zero. When no months remain,
    `early_termination_fee_cents` is zero."

    Design: Corner/calculations/etf_zero_when_term_elapsed
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=BASIC, account_overrides={"contract_term_months": 1})
    set_clock("2026-07-11T00:00:00Z")  # 40 days later -> elapsed 1 month, remaining 0
    requested = validate_success(api.request_cancellation(ctx["account"]["id"], ADMIN), 200)
    assert requested["early_termination_fee_cents"] == 0


def test_communicator_health_battery_boundary(api):
    """PRD §3.3: "the battery is acceptable when `backup_battery_pct` is at or
    above 20 percent. When both are acceptable, health is `HEALTHY`; when the
    system is not `OFFLINE` but at least one of signal or battery falls below its
    threshold, health is `DEGRADED`."

    Design: Corner/calculations/communicator_health_battery_boundary
    """
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR",
                           cellular_signal_dbm=-50, backup_battery_pct=100, last_checkin_minutes_ago=5)
    h20 = validate_success(api.patch_system(system["id"], {"backup_battery_pct": 20}, OPERATOR), 200)
    assert h20["communicator_health"] == "HEALTHY", "20 is inclusive -> HEALTHY"
    h19 = validate_success(api.patch_system(system["id"], {"backup_battery_pct": 19}, OPERATOR), 200)
    assert h19["communicator_health"] == "DEGRADED", "19 below 20 -> DEGRADED"


# ─── validations ─────────────────────────────────────────────────────────────

def test_duplicate_zone_rejected(api):
    """PRD §3.5: "`zone_number` must be unique among the non-`REMOVED` sensors on
    the same system, and a collision is rejected with `ERR_DUPLICATE_ZONE`."

    Design: Corner/validations/duplicate_zone_rejected
    """
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    create_sensor(system["id"], zone_number=1, sensor_type="DOOR")
    res = api.create_sensor(create_sensor_payload(system["id"], zone_number=1, sensor_type="MOTION"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_ZONE")


def test_cellular_not_entitled_rejected(api):
    """PRD §3.3: "A `CELLULAR` primary path may only be set on a system whose plan
    has `cellular_backup_included` set to true; otherwise the request is rejected
    with `ERR_CELLULAR_NOT_ENTITLED`."

    Design: Corner/validations/cellular_not_entitled_rejected
    """
    plan = create_plan(**BASIC)  # cellular_backup_included false
    acct = create_account(plan["id"])
    res = api.create_system(create_system_payload(acct["id"], primary_path="CELLULAR"), ADMIN)
    validate_error(res, "ERR_CELLULAR_NOT_ENTITLED")


def test_second_active_permit_rejected(api):
    """PRD §3.8: "An account may hold at most one permit in status `ACTIVE` at a
    time; a second active permit is rejected with `ERR_PERMIT_ALREADY_ACTIVE`."

    Design: Corner/validations/second_active_permit_rejected
    """
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"])
    issue_permit(acct["id"], "P-A", filed_days_late=0)
    res = api.create_permit(create_permit_payload(acct["id"], "P-B", filed_days_late=0), ADMIN)
    validate_error(res, "ERR_PERMIT_ALREADY_ACTIVE")


def test_open_dispatch_blocks_change_plan(api):
    """PRD §3.2: "the change is blocked while any alarm event under the account is
    in status `DISPATCHED` — an open responder dispatch must resolve before the
    proration cycle can be re-anchored — and that block surfaces as
    `ERR_OPEN_DISPATCH`."

    Design: Corner/validations/open_dispatch_blocks_change_plan
    """
    set_clock("2026-06-01T00:00:00Z")
    pro = create_plan(**PRO)
    plus = create_plan(**PLUS)
    acct = create_account(pro["id"])
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="SMOKE")
    activated = validate_success(api.activate_account(acct["id"], ADMIN), 200)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)
    # FIRE event routed + dispatched, left open (DISPATCHED).
    ingest_route_dispatch(system["id"], sensor["id"], "FIRE")

    res = api.change_plan(
        acct["id"], change_plan_payload(plus["id"], activated["version"]), ADMIN)
    validate_error(res, "ERR_OPEN_DISPATCH")
