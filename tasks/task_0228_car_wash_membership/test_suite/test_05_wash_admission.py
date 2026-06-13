"""License-plate wash admission and usage intensity (PRD §3.6, §3.7).

Translates queue-A boundary_precision_check, priority_pair_validation_conflict
(location-closed pairing), cross_entity_state_dependency (Vehicle->Membership),
resource_temporal_overlap (daily capacity), dual_variant_calc (usage intensity),
plus queue-B validation/endpoint corners.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_wash_event,
    create_plan_payload, create_single_wash_plan_payload, create_location_payload,
    create_account_payload, create_vehicle_payload, create_membership_payload,
    TEST_USERS, make_account_holder_headers,
    setup_unlimited_active, setup_single_wash_active,
    create_plan, create_single_wash_plan, create_location, create_account,
    create_vehicle, enroll_membership, pay_first_cycle_invoice, set_clock,
    submit_wash, simulate,
)

PA = TEST_USERS["platform_admin_headers"]
LO = TEST_USERS["location_operator_headers"]


# ─── Queue A: boundary_precision_check / cooldown_exactly_at_boundary_admits ───

def test_cooldown_exactly_at_boundary_admits(api):
    """PRD §3.6: "For an `UNLIMITED` plan, the cooldown must have elapsed: the number of
    hours since the membership's `last_admitted_wash_utc` must be at least the plan's
    `wash_cooldown_hours`. The boundary is inclusive — when exactly that many hours have
    passed, the cooldown is satisfied."

    Design: Difficulty/boundary_precision_check/cooldown_exactly_at_boundary_admits
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        wash_cooldown_hours=12, clock="2026-06-01T00:00:00Z", license_plate="COOL07"
    )
    loc = create_location(name="CoolSite", daily_wash_capacity=50, in_network=True)
    first = submit_wash(loc["id"], "COOL07", "CA")
    assert first["status"] == "ADMITTED", "first wash should be admitted"
    set_clock("2026-06-01T12:00:00Z")  # exactly 12h later
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "COOL07", "state_code": "CA"}, LO
    )
    we2 = validate_success(res, 201)
    assert we2["status"] == "ADMITTED", "a wash exactly at the cooldown boundary is admitted"
    assert we2["rejection_error_id"] is None


def test_cooldown_just_before_boundary_rejects(api):
    """PRD §3.6: "A wash inside the cooldown window is rejected with
    `ERR_COOLDOWN_ACTIVE`." (Cooldown boundary inclusive; 11h59m has not elapsed 12h.)

    Design: Difficulty/boundary_precision_check/cooldown_exactly_at_boundary_admits
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        wash_cooldown_hours=12, clock="2026-06-01T00:00:00Z", license_plate="COOL08"
    )
    loc = create_location(name="CoolSite2", daily_wash_capacity=50, in_network=True)
    first = submit_wash(loc["id"], "COOL08", "CA")
    assert first["status"] == "ADMITTED"
    set_clock("2026-06-01T11:59:00Z")  # one minute short of 12h
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "COOL08", "state_code": "CA"}, LO
    )
    we2 = validate_success(res, 201)
    assert we2["status"] == "REJECTED", "a wash inside the cooldown window is rejected"
    assert we2["rejection_error_id"] == "ERR_COOLDOWN_ACTIVE"


# ─── Queue A: boundary_precision_check / single_wash_zero_credit_empty_pool_rejects ───

def test_single_wash_zero_credit_rejects_with_no_credits(api):
    """PRD §3.6: "For a `SINGLE_WASH` plan, the membership's `credit_balance` must be at
    least 1. A membership with no remaining credit is rejected with `ERR_NO_CREDITS`."

    Design: Difficulty/boundary_precision_check/single_wash_zero_credit_empty_pool_rejects
    """
    plan, account, vehicle, membership = setup_single_wash_active(
        included_credits=1, clock="2026-06-01T00:00:00Z", license_plate="POOL08"
    )
    loc = create_location(name="PoolSite", daily_wash_capacity=50, in_network=True)
    first = submit_wash(loc["id"], "POOL08", "CA")
    assert first["status"] == "ADMITTED", "the one granted credit admits the first wash"
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "POOL08", "state_code": "CA"}, LO
    )
    we2 = validate_success(res, 201)
    assert we2["status"] == "REJECTED"
    assert we2["rejection_error_id"] == "ERR_NO_CREDITS"


def test_single_wash_credit_balance_zero_after_consuming_one(api):
    """PRD §3.3: "The membership exposes `credit_balance`, which for a `SINGLE_WASH` plan
    is `credits_granted` minus `credits_consumed`".
    PRD §3.6: "for a `SINGLE_WASH` plan only — raises the membership's `credits_consumed`
    by 1".

    Design: Difficulty/boundary_precision_check/single_wash_zero_credit_empty_pool_rejects
    """
    plan, account, vehicle, membership = setup_single_wash_active(
        included_credits=1, clock="2026-06-01T00:00:00Z", license_plate="POOL09"
    )
    loc = create_location(name="PoolSite2", daily_wash_capacity=50, in_network=True)
    submit_wash(loc["id"], "POOL09", "CA")
    hdr = make_account_holder_headers(account["id"])
    mem = validate_success(api.get_membership(membership["id"], hdr), 200)
    assert mem["credit_balance"] == 0, "credit_balance must be 0 after the single credit is consumed"


# ─── Queue A: priority_pair_validation_conflict / location_closed_beats_no_credits ───

def test_location_closed_beats_no_credits(api):
    """PRD §3.6: "The location's `status` must be `OPEN`; a closed site rejects with
    `ERR_LOCATION_CLOSED`."
    PRD §3.6: "The admission conditions are evaluated in this exact priority order, and
    the first one to fail is the recorded rejection reason".

    Design: Difficulty/priority_pair_validation_conflict/location_closed_beats_no_credits
    """
    plan, account, vehicle, membership = setup_single_wash_active(
        included_credits=1, clock="2026-06-01T00:00:00Z", license_plate="CLZ005"
    )
    loc = create_location(name="CloseSite", daily_wash_capacity=50, in_network=True)
    submit_wash(loc["id"], "CLZ005", "CA")  # consumes the one credit -> balance 0
    validate_success(api.close_location(loc["id"], PA), 200)
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "CLZ005", "state_code": "CA"}, LO
    )
    we = validate_success(res, 201)
    assert we["status"] == "REJECTED"
    assert we["rejection_error_id"] == "ERR_LOCATION_CLOSED", \
        "the OPEN check (priority 1) wins over the credit check (priority 6)"


def test_location_closed_rejection_does_not_consume_credit(api):
    """PRD §3.6: "a rejected event records in `rejection_error_id` the identifier of the
    single highest-priority condition that failed, and consumes no entitlement."

    Design: Difficulty/priority_pair_validation_conflict/location_closed_beats_no_credits
    """
    plan, account, vehicle, membership = setup_single_wash_active(
        included_credits=2, clock="2026-06-01T00:00:00Z", license_plate="CLZ006"
    )
    loc = create_location(name="CloseSite2", daily_wash_capacity=50, in_network=True)
    validate_success(api.close_location(loc["id"], PA), 200)
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "CLZ006", "state_code": "CA"}, LO
    )
    we = validate_success(res, 201)
    assert we["status"] == "REJECTED"
    assert we["rejection_error_id"] == "ERR_LOCATION_CLOSED"
    hdr = make_account_holder_headers(account["id"])
    mem = validate_success(api.get_membership(membership["id"], hdr), 200)
    assert mem["credit_balance"] == 2, "a rejected wash consumes no credit"


# ─── Queue A: cross_entity_state_dependency / wash_admit_requires_membership_active ───

def test_wash_rejected_when_membership_frozen(api):
    """PRD §3.6: "The recognized plate ... must map to a vehicle whose `status` is
    `ACTIVE` that carries a membership whose `status` is `ACTIVE` — not `FROZEN`,
    `PAST_DUE`, `CANCELLED`, or any other state. If no such active membership exists,
    the entry is rejected with `ERR_NO_MEMBERSHIP`."

    Design: Difficulty/cross_entity_state_dependency/wash_admit_requires_membership_active_vehicle_membership
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="VMF009"
    )
    loc = create_location(name="VMFSite", daily_wash_capacity=50, in_network=True)
    hdr = make_account_holder_headers(account["id"])
    validate_success(api.freeze_membership(membership["id"], hdr), 200)
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "VMF009", "state_code": "CA"}, LO
    )
    we = validate_success(res, 201)
    assert we["status"] == "REJECTED"
    assert we["rejection_error_id"] == "ERR_NO_MEMBERSHIP", \
        "a FROZEN membership is not ACTIVE, so admission is rejected with ERR_NO_MEMBERSHIP"


def test_wash_rejected_when_membership_still_pending(api):
    """PRD §3.6: "The recognized plate ... must map to a vehicle whose `status` is
    `ACTIVE` that carries a membership whose `status` is `ACTIVE` — not `FROZEN`,
    `PAST_DUE`, `CANCELLED`, or any other state. If no such active membership exists, the
    entry is rejected with `ERR_NO_MEMBERSHIP`."
    PRD §3.3: "A newly enrolled membership begins in `PENDING` status ... The membership
    does not become usable until that first invoice is paid."

    Design: Difficulty/cross_entity_state_dependency/wash_admit_requires_membership_active_vehicle_membership
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="U6b", monthly_fee_cents=3000, max_addons=3)
    loc = create_location(name="VMFSite2", daily_wash_capacity=50, in_network=True)
    acct = create_account(contact_email="l2@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh = create_vehicle(acct["id"], "VMF010", "CA", hdr)
    # Enroll but do NOT pay the first invoice: the membership stays PENDING (not ACTIVE).
    enroll_membership(acct["id"], veh["id"], plan["id"], hdr)
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "VMF010", "state_code": "CA"}, LO
    )
    we = validate_success(res, 201)
    assert we["status"] == "REJECTED"
    assert we["rejection_error_id"] == "ERR_NO_MEMBERSHIP", \
        "a PENDING (not ACTIVE) membership yields ERR_NO_MEMBERSHIP at admission"


def test_billing_run_does_not_bill_suspended_account_membership(api):
    """PRD §3.10: "Suspension cascades: every membership of that account that is `ACTIVE`
    or `PAST_DUE` is driven to `FROZEN`".
    PRD §3.4: "For each membership whose current cycle has elapsed, the run issues a
    `CYCLE` invoice."

    Design: Difficulty/cross_entity_state_dependency/billing_run_blocked_by_suspended_account_account_membership
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="ACT010"
    )
    validate_success(api.suspend_account(account["id"], PA), 200)
    set_clock("2026-07-01T00:00:00Z")
    api.billing_run({"membership_id": membership["id"]}, TEST_USERS["billing_admin_headers"])

    mem_after = validate_success(api.get_membership(membership["id"], PA), 200)
    assert mem_after["status"] == "FROZEN", \
        "a suspended account's frozen membership is unchanged by the billing run"
    invoices = validate_success(
        api.list_invoices(PA, params={"membership_id": membership["id"], "kind": "CYCLE"}), 200
    )
    assert len(invoices) == 1, \
        "no new CYCLE invoice is issued for a membership whose account is suspended"


def test_billing_run_leaves_suspended_account_unchanged(api):
    """PRD §3.10: "**Reactivating** a suspended account returns its `status` to `ACTIVE` ...
    but it deliberately does not auto-thaw the memberships the suspension froze".
    PRD §3.4: "For each membership whose current cycle has elapsed, the run issues a
    `CYCLE` invoice."

    Design: Difficulty/cross_entity_state_dependency/billing_run_blocked_by_suspended_account_account_membership
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="ACT011"
    )
    validate_success(api.suspend_account(account["id"], PA), 200)
    set_clock("2026-07-01T00:00:00Z")
    api.billing_run({"membership_id": membership["id"]}, TEST_USERS["billing_admin_headers"])

    acct_after = validate_success(api.get_account(account["id"], PA), 200)
    assert acct_after["status"] == "SUSPENDED", \
        "the billing run does not reactivate a suspended account"
    # The original PAID cycle invoice is the only one; no FAILED/ISSUED invoice was raised.
    invoices = validate_success(
        api.list_invoices(PA, params={"membership_id": membership["id"]}), 200
    )
    statuses = sorted(i["status"] for i in invoices)
    assert statuses == ["PAID"], \
        f"no new invoice should be raised for the suspended account; got statuses {statuses}"


# ─── Queue A: resource_temporal_overlap / location_daily_capacity_aggregate_full ───

def _build_two_unlimited_vehicles_one_capacity():
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="U9", monthly_fee_cents=3000, max_addons=3)
    loc = create_location(name="CapSite", daily_wash_capacity=1, in_network=True)
    acct = create_account(contact_email="o@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh1 = create_vehicle(acct["id"], "CAP012", "CA", hdr)
    veh2 = create_vehicle(acct["id"], "CAP013", "CA", hdr)
    mem1 = enroll_membership(acct["id"], veh1["id"], plan["id"], hdr)
    pay_first_cycle_invoice(mem1["id"], acct["id"], hdr)
    mem2 = enroll_membership(acct["id"], veh2["id"], plan["id"], hdr)
    pay_first_cycle_invoice(mem2["id"], acct["id"], hdr)
    return loc["id"]


def test_daily_capacity_full_rejects_second_wash(api):
    """PRD §3.6: "The site must have capacity: the count of admitted wash events at this
    location for the current UTC calendar day must be strictly less than the location's
    `daily_wash_capacity`. A site already at capacity rejects with `ERR_CAPACITY_FULL`."

    Design: Difficulty/resource_temporal_overlap/location_daily_capacity_aggregate_full_rejects
    """
    loc_id = _build_two_unlimited_vehicles_one_capacity()
    first = submit_wash(loc_id, "CAP012", "CA")
    assert first["status"] == "ADMITTED", "first wash of the day fills capacity=1"
    res = api.create_wash_event(
        {"location_id": loc_id, "license_plate": "CAP013", "state_code": "CA"}, LO
    )
    we2 = validate_success(res, 201)
    assert we2["status"] == "REJECTED"
    assert we2["rejection_error_id"] == "ERR_CAPACITY_FULL"


def test_daily_capacity_admits_first_wash(api):
    """PRD §3.6: "the count of admitted wash events at this location for the current UTC
    calendar day must be strictly less than the location's `daily_wash_capacity`." (With
    capacity 1 and zero prior washes, the first wash is admitted.)

    Design: Difficulty/resource_temporal_overlap/location_daily_capacity_aggregate_full_rejects
    """
    loc_id = _build_two_unlimited_vehicles_one_capacity()
    res = api.create_wash_event(
        {"location_id": loc_id, "license_plate": "CAP012", "state_code": "CA"}, LO
    )
    we = validate_success(res, 201)
    assert we["status"] == "ADMITTED", "first wash is admitted while count(0) < capacity(1)"
    assert_wash_event(we)


# ─── Queue A: dual_variant_calc / usage_intensity_chronic_vs_acute_on_vehicle ───

def _setup_two_washes_across_time():
    """SINGLE_WASH membership with ample credits; vehicle created 2026-02-01; one wash on
    2026-04-15 (outside 7-day window) and one on 2026-05-29 (inside). Returns vehicle_id."""
    set_clock("2026-02-01T00:00:00Z")
    plan = create_single_wash_plan(name="PayGo", included_credits=50, per_credit_price_cents=1200)
    loc = create_location(name="Site1", daily_wash_capacity=100, in_network=True)
    acct = create_account(contact_email="b@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh = create_vehicle(acct["id"], "USE040", "CA", hdr)
    mem = enroll_membership(acct["id"], veh["id"], plan["id"], hdr)
    pay_first_cycle_invoice(mem["id"], acct["id"], hdr)
    set_clock("2026-04-15T00:00:00Z")
    submit_wash(loc["id"], "USE040", "CA")
    set_clock("2026-05-29T00:00:00Z")
    submit_wash(loc["id"], "USE040", "CA")
    return veh["id"]


def test_acute_intensity_counts_only_recent_window(api):
    """PRD §3.7: "The **acute** intensity is a plain integer count of the vehicle's
    admitted washes whose admission instant falls within the rolling 7-day window ending
    at the current clock (the lower bound of that window is inclusive)."

    Design: Difficulty/dual_variant_calc/usage_intensity_chronic_vs_acute_on_vehicle
    """
    veh_id = _setup_two_washes_across_time()
    res = api.get_vehicle_usage_intensity(veh_id, PA)
    data = validate_success(res, 200)
    # current clock 2026-05-29: only the 2026-05-29 wash is within the trailing 7 days.
    assert data["acute_intensity"] == 1, \
        f"only the 2026-05-29 wash falls in the 7-day window; got {data['acute_intensity']}"


# ─── Queue B: validation + endpoint corners ───────────────────────────────

def test_out_of_network_location_admission_rejected(api):
    """PRD §3.6: "The location's `in_network` flag must be true; an out-of-network site
    does not honor the membership and rejects with `ERR_OUT_OF_NETWORK`."

    Design: Corner/validations/out_of_network_location_admission_rejected
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="OON001"
    )
    loc = create_location(name="OonSite", daily_wash_capacity=50, in_network=False)
    res = api.create_wash_event(
        {"location_id": loc["id"], "license_plate": "OON001", "state_code": "CA"}, LO
    )
    we = validate_success(res, 201)
    assert we["status"] == "REJECTED"
    assert we["rejection_error_id"] == "ERR_OUT_OF_NETWORK"


def test_complete_admitted_wash_moves_to_completed(api):
    """PRD §3.6: "An admitted wash is later marked finished, moving its `status` from
    `ADMITTED` to `COMPLETED`."

    Design: Corner/endpoints/wash_event_complete_admitted_to_completed
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="CMP001"
    )
    loc = create_location(name="CmpSite", daily_wash_capacity=50, in_network=True)
    we = submit_wash(loc["id"], "CMP001", "CA")
    assert we["status"] == "ADMITTED"
    completed = validate_success(api.complete_wash_event(we["id"], LO), 200)
    assert completed["status"] == "COMPLETED"
