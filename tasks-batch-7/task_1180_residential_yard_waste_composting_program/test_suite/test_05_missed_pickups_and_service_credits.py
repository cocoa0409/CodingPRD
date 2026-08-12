"""Missed pickups and the service credit ledger: report/validate cycle,
prorated vs flat credit amounts, segregation of duties, and balance invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_credit,
    complete_ticket,
    create_published_route,
    create_ticket,
    get_household,
    get_subscription,
    get_ticket,
    make_clerk_headers,
    make_resident_headers,
    report_missed,
    set_clock,
    setup_active_household_with_route,
    setup_pending_credit,
    validate_error,
    validate_missed,
    validate_success,
    void_credit,
    create_household,
    create_zone,
)


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / missed_credit_prorated_vs_flat
# ---------------------------------------------------------------------------

def _setup_both_credit_variants():
    """Opt-in household A (base 12000 -> prorated credit floor(12000/27) = 444)
    and universal household B (flat 500), each with a validated missed pickup."""
    ctx_o = setup_pending_credit(service_model="OPT_IN", validator_id="sup_1")
    ctx_u = setup_pending_credit(service_model="UNIVERSAL", validator_id="sup_1")
    return ctx_o, ctx_u


def test_missed_credit_prorated_for_opt_in(api, admin_headers):
    """PRD section 3.6: "for an `OPT_IN` subscription it is the subscription's
    `base_fee_cents` divided by the season length in weeks (computed as in
    §3.2: season window days divided by seven, rounded up), floored to whole
    cents — so the credit reflects the fee actually charged, prorated season
    included". floor(12000 / 27) = 444.

    Design: Difficulty/dual_variant_calc/missed_credit_prorated_vs_flat
    """
    ctx_o, _ctx_u = _setup_both_credit_variants()
    credit = ctx_o["credit"]
    assert credit["amount_cents"] == 444
    assert credit["status"] == "PENDING_APPROVAL"

    approve_credit(credit["id"], clerk_id="clerk_1")
    household = get_household(ctx_o["household"]["id"])
    assert household["credit_balance_cents"] == 444


def test_missed_credit_flat_for_universal(api, admin_headers):
    """PRD section 3.6: "for a `UNIVERSAL` subscription it is simply the zone's
    `universal_flat_credit_cents`, independent of any fee." The same validated
    missed pickup yields 500 flat where the opt-in variant yields 444.

    Design: Difficulty/dual_variant_calc/missed_credit_prorated_vs_flat
    """
    ctx_o, ctx_u = _setup_both_credit_variants()
    credit_u = ctx_u["credit"]
    assert credit_u["amount_cents"] == 500
    assert ctx_o["credit"]["amount_cents"] != credit_u["amount_cents"]

    approve_credit(credit_u["id"], clerk_id="clerk_1")
    household = get_household(ctx_u["household"]["id"])
    assert household["credit_balance_cents"] == 500


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / ticket_missed_report_invalidate_cycle
# ---------------------------------------------------------------------------

def _setup_reported_ticket():
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")
    set_clock("2026-05-05T00:00:00Z")
    report_missed(ticket["id"], ctx["household"])
    ctx["ticket"] = ticket
    return ctx


def test_invalidate_loops_ticket_back_to_scheduled(api, admin_headers):
    """PRD section 3.6: "When `validated` is false, the report is invalidated:
    `missed_reported_by` is cleared to null and the ticket loops back to
    `SCHEDULED` — this cycle may repeat."

    Design: Difficulty/non_linear_state_machine/ticket_missed_report_invalidate_cycle
    """
    ctx = _setup_reported_ticket()
    reported = get_ticket(ctx["ticket"]["id"])
    assert reported["status"] == "MISSED_REPORTED"
    assert reported["missed_reported_by"] == ctx["household"]["id"]

    invalidated = validate_missed(ctx["ticket"]["id"], False, supervisor_id="sup_1")
    assert invalidated["status"] == "SCHEDULED"
    assert invalidated["missed_reported_by"] is None


def test_invalidated_ticket_completes_normally(api, admin_headers):
    """PRD section 3.6: "When `validated` is false, the report is invalidated:
    `missed_reported_by` is cleared to null and the ticket loops back to
    `SCHEDULED` — this cycle may repeat." PRD section 3.8: "convert that
    ticket's `weight_lbs` to gallons at half yield and twenty pounds per gallon
    (0.025 gallons per pound)" — a completed 100-lb ticket earns 2.50 gallons.

    Design: Difficulty/non_linear_state_machine/ticket_missed_report_invalidate_cycle
    """
    ctx = _setup_reported_ticket()
    validate_missed(ctx["ticket"]["id"], False, supervisor_id="sup_1")

    completed = complete_ticket(ctx["ticket"]["id"], 100)
    assert completed["status"] == "COMPLETED"
    assert completed["weight_lbs"] == 100
    assert completed["missed_reported_by"] is None

    household = get_household(ctx["household"]["id"])
    assert household["compost_entitlement_gallons"] == pytest.approx(2.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / credit_approve_then_void_balance_unchanged
# ---------------------------------------------------------------------------

def test_credit_approve_raises_balance(api, admin_headers):
    """PRD section 3.6: "Approval records the clerk in `approved_by`, moves the
    credit to `GRANTED`, adds `amount_cents` to the household's
    `credit_balance_cents`, and increments the household's `version` by one."
    and "A household's `credit_balance_cents` is always exactly the sum of
    `amount_cents` over its `GRANTED` credits".

    Design: Difficulty/compensating_invariant/credit_approve_then_void_balance_unchanged
    """
    ctx = setup_pending_credit(service_model="OPT_IN")
    assert get_household(ctx["household"]["id"])["credit_balance_cents"] == 0

    approve_credit(ctx["credit"]["id"], clerk_id="clerk_1")
    household = get_household(ctx["household"]["id"])
    assert household["credit_balance_cents"] == 444


def test_credit_approve_then_void_balance_unchanged(api, admin_headers):
    """PRD section 3.6: "Or a `BillingClerk` may void a `GRANTED` credit (any
    other status is `ERR_INVALID_STATE`), which moves it to `VOIDED`, subtracts
    `amount_cents` from the household's balance, and increments the household's
    `version` — so approving and then voiding the same credit leaves the balance
    unchanged."

    Design: Difficulty/compensating_invariant/credit_approve_then_void_balance_unchanged
    """
    ctx = setup_pending_credit(service_model="OPT_IN")
    balance_before = get_household(ctx["household"]["id"])["credit_balance_cents"]
    assert balance_before == 0

    approve_credit(ctx["credit"]["id"], clerk_id="clerk_1")
    assert get_household(ctx["household"]["id"])["credit_balance_cents"] == 444

    voided = void_credit(ctx["credit"]["id"], clerk_id="clerk_1")
    assert voided["status"] == "VOIDED"
    balance_after = get_household(ctx["household"]["id"])["credit_balance_cents"]
    assert balance_after == 0
    assert balance_after == balance_before


# ---------------------------------------------------------------------------
# Queue B: validations / cross-cutting credit rules
# ---------------------------------------------------------------------------

def test_credit_segregation_same_user_rejected(api, admin_headers):
    """PRD section 3.6: "segregation of duties is enforced: the approving
    clerk's `X-User-ID` must differ from the credit's `validated_by`, or the
    approval is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/credit_segregation_same_user_rejected
    """
    ctx = setup_pending_credit(service_model="UNIVERSAL", validator_id="ops_9")
    assert ctx["credit"]["validated_by"] == "ops_9"

    # The same operator id wearing the BillingClerk role may not approve.
    res = api.approve_service_credit(ctx["credit"]["id"], make_clerk_headers("ops_9"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    granted = approve_credit(ctx["credit"]["id"], clerk_id="clerk_1")
    assert granted["status"] == "GRANTED"
    assert granted["approved_by"] == "clerk_1"
    assert get_household(ctx["household"]["id"])["credit_balance_cents"] == 500


def test_approve_granted_credit_again_rejected(api, admin_headers):
    """PRD section 3.6: "A `BillingClerk` approves a credit that is
    `PENDING_APPROVAL` (otherwise `ERR_INVALID_STATE`)" and "`APPLIED` and
    `VOIDED` are terminal."

    Design: Corner/validations/approve_granted_credit_again_rejected
    """
    ctx = setup_pending_credit(service_model="UNIVERSAL")
    approve_credit(ctx["credit"]["id"], clerk_id="clerk_1")

    res = api.approve_service_credit(ctx["credit"]["id"], make_clerk_headers("clerk_1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    # Balance is not double-counted by the failed re-approval.
    assert get_household(ctx["household"]["id"])["credit_balance_cents"] == 500


def test_credit_applied_via_payment_reconciles_ledger(api, admin_headers):
    """PRD section 3.2: "When the flag is true, the household's `GRANTED`
    service credits are consumed oldest first by `created_at`, each moving to
    `APPLIED` and its amount added to the subscription's `paid_cents` and
    subtracted from the household's `credit_balance_cents`, until the amount due
    is covered; the cash portion of the payment covers whatever remains."
    Outstanding 1500 (13500 due - 12000 paid): the 444 credit applies and cash
    covers the remaining 1056.

    Design: Corner/cross_cutting_layers/credit_applied_via_payment_reconciles_ledger
    """
    # Opt-in household pays base 12000 cash, then a 64-gal cart raises the bill.
    ctx = setup_active_household_with_route(service_model="OPT_IN",
                                            base_seasonal_fee_cents=12000)
    household, sub = ctx["household"], ctx["subscription"]
    assert sub["paid_cents"] == 12000

    res = api.create_cart(
        {"household_id": household["id"], "subscription_id": sub["id"], "size_gallons": 64},
        make_resident_headers(household["id"]),
    )
    assert res.status_code == 201, f"setup failed: create cart -> {res.status_code} {res.text}"
    sub = get_subscription(sub["id"])
    assert sub["total_due_cents"] == 13500

    # Validated missed pickup -> prorated credit 444, approved -> GRANTED.
    ticket = create_ticket(sub["id"], ctx["route"]["id"], "2026-05-04")
    set_clock("2026-05-05T00:00:00Z")
    report_missed(ticket["id"], household)
    validate_missed(ticket["id"], True, supervisor_id="sup_1")
    credits = api.list_service_credits(
        admin_headers, params={"subscription_id": sub["id"], "status": "PENDING_APPROVAL"}
    ).json()["data"]
    assert len(credits) == 1, f"setup failed: expected 1 credit, got {len(credits)}"
    credit = credits[0]
    approve_credit(credit["id"], clerk_id="clerk_1")

    # Pay the outstanding 1500 with the credit balance: 444 credit + 1056 cash.
    paid = validate_success(api.pay_subscription(
        sub["id"], {"use_credit_balance": True}, make_resident_headers(household["id"])), 200)
    assert paid["paid_cents"] == 13500
    assert paid["status"] == "ACTIVE"

    credit_after = validate_success(
        api.get_service_credit(credit["id"], make_clerk_headers("clerk_1")), 200)
    assert credit_after["status"] == "APPLIED"
    assert get_household(household["id"])["credit_balance_cents"] == 0
