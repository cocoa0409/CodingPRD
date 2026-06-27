"""State-machine behavior: water-test, system, contract, route, cartridge, visit,
warranty-claim, and invoice transitions — valid moves, terminal lockdown, guarded
transitions, and the cyclic / fork-join shapes.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_active_rental_contract,
    setup_active_system,
    setup_account_with_accepted_test,
    setup_triaged_claim,
    setup_due_soon_cartridge,
    setup_dispatched_route_with_stop,
    set_clock,
    create_system_payload,
    create_water_test_payload,
)

BILLING = TEST_USERS["billing_clerk_headers"]
SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Non-linear: RentalContract cyclic ACTIVE<->SUSPENDED, version bumps each toggle
# ===========================================================================
def test_rental_contract_cyclic_suspend_resume_suspend(api):
    """PRD §3.8: "This active-suspended cycle may repeat any number of times. Each
    suspend and each resume bumps the contract's `version`."

    Design: Difficulty/non_linear_state_machine/rental_contract_cyclic_active_suspended
    """
    ctx = setup_active_rental_contract()
    rc_id = ctx["contract"]["id"]
    assert ctx["contract"]["version"] == 1

    get_success_data(api.suspend_rental_contract(rc_id, BILLING))
    get_success_data(api.resume_rental_contract(rc_id, BILLING))
    final = validate_success(api.suspend_rental_contract(rc_id, BILLING), 200)

    assert final["status"] == "SUSPENDED"
    assert final["version"] == 4, f"v1 + three toggles -> v4, got {final['version']}"


# ===========================================================================
# Non-linear: WarrantyClaim branching fork-join (TRIAGED -> REPLACE -> CLOSED)
# ===========================================================================
def test_warranty_claim_replace_branch_reaches_closed(api):
    """PRD §3.9: "resolving to `REPLACE` moves it to `REPLACE` but is permitted only
    when `covered` is true, because an uncovered claim cannot elect a free
    replacement."
    PRD §3.9: "Closing a claim moves it from either `REPAIR` or `REPLACE` to
    `CLOSED`."
    PRD §3.9: "when the claim is covered the settlement is 0 regardless of defect
    class."

    Design: Difficulty/non_linear_state_machine/warranty_claim_branching_fork_join
    """
    ctx = setup_triaged_claim(defect_class="RESIN_FOULING", install_at="2026-01-01T00:00:00Z",
                              reported_at="2026-06-01T00:00:00Z", triage_at="2026-06-01T00:00:00Z")
    assert ctx["claim"]["covered"] is True

    resolved = validate_success(
        api.resolve_warranty_claim(ctx["claim"]["id"], {"resolution": "REPLACE"}, SM), 200)
    assert resolved["status"] == "REPLACE"

    closed = validate_success(api.close_warranty_claim(ctx["claim"]["id"], SM), 200)
    assert closed["status"] == "CLOSED"
    assert closed["covered"] is True
    assert closed["settlement_cents"] == 0


# ===========================================================================
# Cross-entity state dependency: install requires source test ACCEPTED
# ===========================================================================
def test_install_rejected_when_source_test_only_recommended(api):
    """PRD §3.3: "Three preconditions guard the install: the system must currently
    be `ORDERED`, the source water test must be in `ACCEPTED` status, and the
    system's `grain_capacity` must exactly equal the source test's
    `recommended_grain_capacity`."

    Design: Difficulty/cross_entity_state_dependency/system_install_requires_accepted_water_test
    """
    # Build a system ORDERED from a RECOMMENDED (not yet ACCEPTED) test.
    base = _account_and_recommended_test(api)
    sys = get_success_data(api.create_system(
        create_system_payload(base["account"]["id"], base["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=32000), SM))

    resp = api.install_system(sys["id"], base["tech_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_system(sys["id"], SM), 200)
    assert after["lifecycle_status"] == "ORDERED"


# ===========================================================================
# Cross-entity state dependency: resume requires account GOOD standing
# ===========================================================================
def test_resume_rejected_when_account_delinquent(api):
    """PRD §3.8: "A `BillingClerk` may resume a `SUSPENDED` contract back to
    `ACTIVE`, but only when the account's `standing` is `GOOD`."
    PRD §3.10: "Re-evaluating an `OPEN` invoice against the clock checks whether it
    has aged past its due date ... if so the invoice becomes `PAST_DUE` and the
    owning account's `standing` is driven to `DELINQUENT` as a cascade."

    Design: Difficulty/cross_entity_state_dependency/contract_resume_requires_account_good_standing
    """
    ctx = setup_active_rental_contract(start_date="2026-01-01T00:00:00Z")
    rc_id = ctx["contract"]["id"]
    acct_id = ctx["account"]["id"]

    get_success_data(api.suspend_rental_contract(rc_id, BILLING))
    inv = get_success_data(api.create_invoice({
        "account_id": acct_id, "contract_id": rc_id, "invoice_kind": "RENTAL_CYCLE",
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-02-01T00:00:00Z",
        "due_offset_days": 30}, BILLING))
    set_clock("2026-03-05T00:00:00Z", BILLING)
    get_success_data(api.evaluate_invoice(inv["id"], BILLING))

    acct = validate_success(api.get_account(acct_id, SM), 200)
    assert acct["standing"] == "DELINQUENT"

    resp = api.resume_rental_contract(rc_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_rental_contract(rc_id, BILLING), 200)
    assert after["status"] == "SUSPENDED"


# ===========================================================================
# Corner: water test initial state DRAFT
# ===========================================================================
def test_water_test_starts_in_draft(api):
    """PRD §3.2: "A new test is created in `DRAFT` status."

    Design: Corner/state_machines/water_test_initial_state_is_draft
    """
    base = setup_account_with_accepted_test()  # gives us a fresh account chain
    wt = validate_success(api.create_water_test(
        create_water_test_payload(base["account"]["id"], hardness_gpg=12), base["tech_headers"]), 201)
    assert wt["status"] == "DRAFT"
    assert wt.get("recommended_grain_capacity") is None


# ===========================================================================
# Corner: accept supersedes prior accepted test and updates account hardness
# ===========================================================================
def test_accept_supersedes_prior_accepted_test(api):
    """PRD §3.2: "It copies the test's `hardness_gpg` onto the owning account's
    `hardness_gpg`, establishing the account's working hardness basis. And it
    supersedes any prior accepted test for the same account: any other `WaterTest`
    for that account currently in `ACCEPTED` transitions to `SUPERSEDED` as a
    cascade."

    Design: Corner/state_machines/accept_supersedes_prior_accepted_test_cascade
    """
    base = setup_account_with_accepted_test(hardness_gpg=15)  # wt1 is ACCEPTED at hardness 15
    wt1 = base["water_test"]
    assert wt1["status"] == "ACCEPTED"

    wt2 = get_success_data(api.create_water_test(
        create_water_test_payload(base["account"]["id"], hardness_gpg=18), base["tech_headers"]))
    get_success_data(api.recommend_water_test(wt2["id"], base["tech_headers"]))
    wt2 = validate_success(api.accept_water_test(wt2["id"], base["cust_headers"]), 200)

    assert wt2["status"] == "ACCEPTED"
    wt1_after = validate_success(api.get_water_test(wt1["id"], SM), 200)
    assert wt1_after["status"] == "SUPERSEDED"
    acct = validate_success(api.get_account(base["account"]["id"], SM), 200)
    assert acct["hardness_gpg"] == 18


# ===========================================================================
# Corner: activating an ORDERED system is an invalid transition
# ===========================================================================
def test_activate_from_ordered_is_invalid_state(api):
    """PRD §3.3: "Activation advances `lifecycle_status` from `INSTALLED` to
    `ACTIVE` and is permitted only from `INSTALLED`."

    Design: Corner/state_machines/activate_from_ordered_invalid_state
    """
    base = setup_account_with_accepted_test()
    sys = get_success_data(api.create_system(
        create_system_payload(base["account"]["id"], base["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=32000), SM))
    resp = api.activate_system(sys["id"], base["tech_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: SUPERSEDED water test cannot be re-accepted (terminal lockdown)
# ===========================================================================
def test_superseded_water_test_cannot_be_reaccepted(api):
    """PRD §3.2: "`SUPERSEDED` is terminal."
    PRD §3.2: "A `Customer` accepts the recommendation, which advances the test from
    `RECOMMENDED` to `ACCEPTED` and is permitted only from `RECOMMENDED`."

    Design: Corner/state_machines/water_test_terminal_superseded_lockdown
    """
    base = setup_account_with_accepted_test(hardness_gpg=15)
    wt1 = base["water_test"]

    wt2 = get_success_data(api.create_water_test(
        create_water_test_payload(base["account"]["id"], hardness_gpg=18), base["tech_headers"]))
    get_success_data(api.recommend_water_test(wt2["id"], base["tech_headers"]))
    get_success_data(api.accept_water_test(wt2["id"], base["cust_headers"]))

    wt1_after = validate_success(api.get_water_test(wt1["id"], SM), 200)
    assert wt1_after["status"] == "SUPERSEDED"

    resp = api.accept_water_test(wt1["id"], base["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: decommission blocked by an ACTIVE rental contract
# ===========================================================================
def test_decommission_blocked_by_active_contract(api):
    """PRD §3.3: "Decommissioning is a `ServiceManager`-only override that advances
    an `ACTIVE` system to `DECOMMISSIONED`; it is permitted only from `ACTIVE` and
    only when the system has no rental contract still in `ACTIVE` or `SUSPENDED`
    status — any such contract must be terminated first."

    Design: Corner/state_machines/decommission_blocked_by_active_contract
    """
    ctx = setup_active_rental_contract()  # system ACTIVE, contract ACTIVE
    resp = api.decommission_system(ctx["system"]["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_system(ctx["system"]["id"], SM), 200)
    assert after["lifecycle_status"] == "ACTIVE"


# ===========================================================================
# Corner: cartridge evaluate enters DUE_SOON within lead window
# ===========================================================================
def test_cartridge_evaluate_enters_due_soon(api):
    """PRD §3.5: "The schedule enters `DUE_SOON` from `ON_TRACK` once the clock
    reaches the lead window — that is, once now is at or after the due date minus 14
    days and still strictly before the due date."

    Design: Corner/state_machines/cartridge_evaluate_due_soon_within_lead_window
    """
    # interval 180 from 2026-01-01 -> due 2026-06-30; clock 2026-06-20 within 14-day lead.
    ctx = setup_due_soon_cartridge(evaluate_at="2026-06-20T00:00:00Z", interval_days=180,
                                   last_replaced_at="2026-01-01T00:00:00Z")
    assert ctx["schedule"]["status"] == "DUE_SOON"


# ===========================================================================
# Corner: replacing a cartridge resets and logs the replacement
# ===========================================================================
def test_cartridge_replace_resets_and_logs(api):
    """PRD §3.5: "On replacement the schedule's `last_replaced_at` is set to now, its
    `status` returns to `ON_TRACK`, and `replacements_logged` is incremented; a
    cartridge-replacement service visit is created as well."

    Design: Corner/state_machines/cartridge_replace_resets_and_logs_replacement
    """
    ctx = setup_due_soon_cartridge(evaluate_at="2026-06-20T00:00:00Z")
    replaced = validate_success(api.replace_cartridge_schedule(ctx["schedule"]["id"], ctx["tech_headers"]), 200)
    assert replaced["status"] == "ON_TRACK"
    assert replaced["replacements_logged"] == 1


# ===========================================================================
# Corner: completing a SALT_DELIVERY stop raises salt level (capped at 100)
# ===========================================================================
def test_salt_delivery_stop_keeps_salt_capped_at_100(api):
    """PRD §3.4: "A `SALT_DELIVERY` stop raises the system's `salt_level_pct` by 25
    percentage points for each bag recorded in `salt_bags_delivered`, capped at
    100."

    Design: Corner/state_machines/route_stop_complete_salt_delivery_raises_salt_level
    """
    ctx = setup_dispatched_route_with_stop(stop_type="SALT_DELIVERY", salt_bags_delivered=2)
    completed = validate_success(api.complete_route_stop(ctx["stop"]["id"], ctx["tech_headers"]), 200)
    assert completed["status"] == "COMPLETED"
    sys = validate_success(api.get_system(ctx["system"]["id"], SM), 200)
    assert sys["salt_level_pct"] == 100, "fresh system already at 100; +50 still caps at 100"


# ===========================================================================
# Corner: regenerate below salt floor rejected with ERR_INSUFFICIENT_SALT
# ===========================================================================
def test_regenerate_blocked_below_salt_floor(api):
    """PRD §3.7: "Regeneration — whether triggered directly on the system or through
    a `REGEN_SERVICE` route stop — requires `salt_level_pct` to be at least 20
    percent; an attempt to regenerate below that floor is rejected with
    `ERR_INSUFFICIENT_SALT`."
    PRD §3.7: "A successful regeneration consumes salt: it decrements
    `salt_level_pct` by 30 percentage points, floored at 0."

    Design: Corner/state_machines/regenerate_blocked_when_salt_below_minimum
    """
    ctx = setup_active_system(grain_capacity=32000, hardness_gpg=15)  # capacity_gallons=2133
    sys_id = ctx["system"]["id"]
    th = ctx["tech_headers"]
    # Three DUE->regenerate cycles: salt 100->70->40->10.
    for _ in range(3):
        get_success_data(api.meter_reading(sys_id, {"gallons_since_regen": 2133}, th))
        get_success_data(api.regenerate_system(sys_id, th))
    after3 = validate_success(api.get_system(sys_id, SM), 200)
    assert after3["salt_level_pct"] == 10

    # Drive DUE again, then the 4th regenerate must fail at salt 10 < 20.
    get_success_data(api.meter_reading(sys_id, {"gallons_since_regen": 2133}, th))
    resp = api.regenerate_system(sys_id, th)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SALT.value)
    final = validate_success(api.get_system(sys_id, SM), 200)
    assert final["regen_health"] == "DUE"


# ===========================================================================
# Corner: paying a PAID invoice again is ERR_INVOICE_CLOSED (idempotency)
# ===========================================================================
def test_pay_already_paid_invoice_is_closed(api):
    """PRD §3.10: "Attempting to pay or void an invoice that is already `PAID` or
    `VOID` is rejected with `ERR_INVOICE_CLOSED`."

    Design: Corner/state_machines/invoice_pay_then_pay_again_invoice_closed
    """
    base = setup_account_with_accepted_test()
    inv = get_success_data(api.create_invoice({
        "account_id": base["account"]["id"], "invoice_kind": "SERVICE_REPAIR",
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-01-02T00:00:00Z"}, BILLING))
    get_success_data(api.pay_invoice(inv["id"], BILLING))
    resp = api.pay_invoice(inv["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_CLOSED.value)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _account_and_recommended_test(api):
    """Account chain with a RECOMMENDED (not accepted) water test."""
    from test_helpers import (create_customer, create_field_tech, create_account,
                              make_field_tech_headers, make_customer_headers,
                              create_water_test_payload)
    customer = create_customer()
    tech = create_field_tech(home_zone="Z-NORTH")
    account = create_account(customer["id"], service_zone="Z-NORTH")
    th = make_field_tech_headers(tech["id"])
    wt = get_success_data(api.create_water_test(create_water_test_payload(account["id"]), th))
    get_success_data(api.recommend_water_test(wt["id"], th))
    wt = get_success_data(api.get_water_test(wt["id"], SM))
    return {"account": account, "tech": tech, "water_test": wt, "tech_headers": th,
            "cust_headers": make_customer_headers(customer["id"])}
