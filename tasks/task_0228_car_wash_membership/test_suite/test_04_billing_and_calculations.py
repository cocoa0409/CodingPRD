"""Billing math and invoice lifecycle (PRD §2.10, §3.4, §3.5, §3.10).

Translates queue-A combinatorial_formula (fleet tiered discount, proration) and
non_linear_state_machine (invoice FAILED->RETRYING->PAID), plus queue-B
calculation corners.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_invoice,
    create_plan_payload, create_single_wash_plan_payload, create_addon_payload,
    create_fleet_account_payload, create_account_payload, create_vehicle_payload,
    create_membership_payload, attach_addon_payload, change_plan_payload,
    TEST_USERS, make_account_holder_headers,
    setup_unlimited_active, create_account, create_vehicle, enroll_membership,
    set_clock, simulate,
)

PA = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["billing_admin_headers"]


def _cycle_invoice(api, membership_id, headers):
    res = api.list_invoices(headers, params={"membership_id": membership_id, "kind": "CYCLE"})
    return validate_success(res, 200)


# ─── Queue A: combinatorial_formula / invoice_cycle_total_fleet_tiered_discount ───

def _build_fleet_two_vehicle_membership_with_addon():
    """Set clock, build a FLEET account with two ACTIVE UNLIMITED memberships, attach
    one 500-cent add-on to membership #1. Returns (account_id, mem1_id, addon_id)."""
    set_clock("2026-06-01T00:00:00Z")
    plan = validate_success(
        api_client.create_plan(
            create_plan_payload(name="Fleet Unlimited", monthly_fee_cents=3000,
                                wash_cooldown_hours=6, max_addons=3),
            PA,
        ), 201,
    )
    addon = validate_success(
        api_client.create_addon(create_addon_payload(name="TIRE_SHINE", recurring_fee_cents=500), PA),
        201,
    )
    acct = validate_success(
        api_client.create_account(create_fleet_account_payload(company_name="Acme Fleet"), PA), 201
    )
    veh1 = validate_success(api_client.create_vehicle(acct["id"], create_vehicle_payload("FLT001", "TX"), PA), 201)
    veh2 = validate_success(api_client.create_vehicle(acct["id"], create_vehicle_payload("FLT002", "TX"), PA), 201)

    mem1 = validate_success(
        api_client.create_membership(create_membership_payload(acct["id"], veh1["id"], plan["id"]), PA), 201
    )
    inv1 = _cycle_invoice(api_client, mem1["id"], PA)[0]
    simulate(inv1["id"], "SUCCEEDED")

    mem2 = validate_success(
        api_client.create_membership(create_membership_payload(acct["id"], veh2["id"], plan["id"]), PA), 201
    )
    inv2 = _cycle_invoice(api_client, mem2["id"], PA)[0]
    simulate(inv2["id"], "SUCCEEDED")

    mem1_now = validate_success(api_client.get_membership(mem1["id"], PA), 200)
    validate_success(
        api_client.attach_addon(mem1["id"], attach_addon_payload(addon["id"], mem1_now["version"]), PA), 201
    )
    return acct["id"], mem1["id"], addon["id"]


def test_fleet_discount_pct_selects_five_percent_tier_for_two_vehicles(api):
    """PRD §2.10: "For a `FLEET` account the discount is selected by a volume tier keyed on
    `active_vehicle_count` ... 5 percent (0.05) when the count is at least 2".

    Design: Difficulty/combinatorial_formula/invoice_cycle_total_fleet_tiered_discount
    """
    account_id, mem1_id, _addon_id = _build_fleet_two_vehicle_membership_with_addon()
    acct = validate_success(api.get_account(account_id, PA), 200)
    assert acct["fleet_discount_pct"] == 0.05, \
        f"FLEET with 2 active vehicles selects 0.05, got {acct['fleet_discount_pct']}"


def test_fleet_cycle_invoice_components_and_total(api):
    """PRD §3.4: "the subtotal is the plan's `monthly_fee_cents` plus the sum of the
    `locked_fee_cents` of every membership add-on that is currently `ACTIVE` ... The
    discount is the subtotal multiplied by the account's `fleet_discount_pct`, rounded
    half-up to a whole number of cents ... The invoice `total_cents` is the subtotal
    minus that discount."

    Design: Difficulty/combinatorial_formula/invoice_cycle_total_fleet_tiered_discount
    """
    account_id, mem1_id, _addon_id = _build_fleet_two_vehicle_membership_with_addon()
    set_clock("2026-07-01T00:00:00Z")
    issued = validate_success(api.billing_run({"membership_id": mem1_id}, BA), 200)
    assert issued, "billing run after a full cycle must issue a fresh CYCLE invoice"
    new_inv = validate_success(api.get_invoice(issued[0]["id"], PA), 200)
    assert_invoice(new_inv)
    # subtotal = 3000 + 500 = 3500; discount = round_half_up(3500 * 0.05) = 175; total = 3325.
    assert new_inv["base_fee_cents"] == 3000, f"base_fee_cents expected 3000, got {new_inv['base_fee_cents']}"
    assert new_inv["addon_fee_cents"] == 500, f"addon_fee_cents expected 500, got {new_inv['addon_fee_cents']}"
    assert new_inv["discount_cents"] == 175, f"discount_cents expected 175, got {new_inv['discount_cents']}"
    assert new_inv["total_cents"] == 3325, f"total_cents expected 3325, got {new_inv['total_cents']}"


# ─── Queue A: combinatorial_formula / proration_round_per_line_then_sum ────

def _setup_proration_change():
    """INDIVIDUAL account on a cheap UNLIMITED plan (1000); a 2500 add-on; clock advanced
    to 23 days elapsed (remaining 7). change-plan to a 3500 plan + add the 2500 add-on."""
    set_clock("2026-06-01T00:00:00Z")
    plan_lo = validate_success(api_client.create_plan(create_plan_payload(name="Basic", monthly_fee_cents=1000), PA), 201)
    plan_hi = validate_success(api_client.create_plan(create_plan_payload(name="Premium", monthly_fee_cents=3500), PA), 201)
    addon_w = validate_success(api_client.create_addon(create_addon_payload(name="WAX", recurring_fee_cents=2500), PA), 201)
    acct = create_account(contact_email="c@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh = create_vehicle(acct["id"], "PRO777", "CA", hdr)
    mem = enroll_membership(acct["id"], veh["id"], plan_lo["id"], hdr)
    inv0 = _cycle_invoice(api_client, mem["id"], hdr)[0]
    simulate(inv0["id"], "SUCCEEDED")
    set_clock("2026-06-24T00:00:00Z")
    validate_success(
        api_client.change_plan(mem["id"], change_plan_payload(plan_hi["id"], [addon_w["id"]]), hdr), 200
    )
    return acct["id"], mem["id"], hdr


def test_proration_invoice_is_proration_kind(api):
    """PRD §3.5: "The system raises a `PRORATION` invoice for the difference."

    Design: Difficulty/combinatorial_formula/proration_round_per_line_then_sum
    """
    account_id, mem_id, hdr = _setup_proration_change()
    res = api.list_invoices(hdr, params={"membership_id": mem_id, "kind": "PRORATION"})
    prorations = validate_success(res, 200)
    assert prorations, "change-plan must create a PRORATION invoice"
    assert prorations[0]["kind"] == "PRORATION"


def test_proration_total_rounds_each_line_then_sums(api):
    """PRD §3.5: "each line is rounded on its own before the lines are summed — the order
    is pinned, round each line first, then add the rounded cents together; the system
    never sums the raw amounts and rounds once at the end ... The invoice `total_cents` is
    the plan-change line plus the sum of those already-rounded add-on lines."

    Design: Difficulty/combinatorial_formula/proration_round_per_line_then_sum
    """
    account_id, mem_id, hdr = _setup_proration_change()
    res = api.list_invoices(hdr, params={"membership_id": mem_id, "kind": "PRORATION"})
    proration = validate_success(res, 200)[0]
    inv = validate_success(api.get_invoice(proration["id"], hdr), 200)
    # remaining=7: plan line round(2500*7/30)=583; addon line round(2500*7/30)=583; total=1166
    # (sum-then-round would give 1167 — this asserts the per-line rule).
    assert inv["total_cents"] == 1166, \
        f"per-line rounding yields 1166 (not 1167); got {inv['total_cents']}"


# ─── Queue A: non_linear_state_machine / invoice_failed_retrying_paid_cycle ───

def _setup_failed_first_invoice():
    """INDIVIDUAL account, PENDING membership whose first CYCLE invoice is DECLINED
    (-> FAILED, attempt_count 1). Returns (membership_id, invoice_id, hdr)."""
    set_clock("2026-06-01T00:00:00Z")
    plan = validate_success(api_client.create_plan(create_plan_payload(name="U2"), PA), 201)
    acct = create_account(contact_email="e@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh = create_vehicle(acct["id"], "RTY001", "CA", hdr)
    mem = enroll_membership(acct["id"], veh["id"], plan["id"], hdr)
    inv0 = _cycle_invoice(api_client, mem["id"], hdr)[0]
    simulate(inv0["id"], "DECLINED")
    return mem["id"], inv0["id"], hdr


def test_invoice_failed_retry_then_paid_reaches_paid(api):
    """PRD §3.4: "retrying moves the invoice from `FAILED` to `RETRYING` ... A retry that
    is then resolved successfully moves the invoice from `RETRYING` to `PAID`".

    Design: Difficulty/non_linear_state_machine/invoice_failed_retrying_paid_cycle
    """
    mem_id, inv_id, hdr = _setup_failed_first_invoice()
    validate_success(api.retry_invoice(inv_id, BA), 200)
    simulate(inv_id, "SUCCEEDED")
    inv = validate_success(api.get_invoice(inv_id, hdr), 200)
    assert inv["status"] == "PAID", "FAILED->RETRYING->PAID loop must end at PAID"
    assert_invoice(inv)


def test_invoice_attempt_count_progresses_across_retry(api):
    """PRD §3.4: "An invoice moves from draft to issued, and on issue its `attempt_count`
    is set to 1."
    PRD §3.4: "retrying moves the invoice from `FAILED` to `RETRYING` and increases
    `attempt_count` by 1."

    Design: Difficulty/non_linear_state_machine/invoice_failed_retrying_paid_cycle
    """
    mem_id, inv_id, hdr = _setup_failed_first_invoice()
    validate_success(api.retry_invoice(inv_id, BA), 200)
    simulate(inv_id, "SUCCEEDED")
    inv = validate_success(api.get_invoice(inv_id, hdr), 200)
    assert inv["attempt_count"] == 2, \
        f"attempt_count must be 2 after issue(1)+retry(+1); got {inv['attempt_count']}"
    mem = validate_success(api.get_membership(mem_id, hdr), 200)
    assert mem["status"] == "ACTIVE", "paid first CYCLE invoice activates the membership"


# ─── Queue B: calculation corners ─────────────────────────────────────────

def test_individual_account_cycle_invoice_has_no_discount(api):
    """PRD §2.10: "For an `INDIVIDUAL` account the discount is always 0, regardless of how
    many vehicles it carries."
    PRD §3.4: "The invoice `total_cents` is the subtotal minus that discount."

    Design: Corner/calculations/invoice_total_individual_no_discount
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        monthly_fee_cents=3000, clock="2026-06-01T00:00:00Z", license_plate="IND001"
    )
    set_clock("2026-07-01T00:00:00Z")
    issued = validate_success(api.billing_run({"membership_id": membership["id"]}, BA), 200)
    assert issued, "a full cycle must produce a new CYCLE invoice"
    inv = validate_success(api.get_invoice(issued[0]["id"], PA), 200)
    assert inv["discount_cents"] == 0, "INDIVIDUAL accounts receive no fleet discount"
    assert inv["total_cents"] == 3000, f"total_cents expected 3000, got {inv['total_cents']}"
