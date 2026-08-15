"""Payment lifecycle: creation gates, posting acceptance rules, returns (NSF),
re-presentment, and the per-payment allocation conservation invariant."""
from test_helpers import (
    ApiErrorId,
    add_charge,
    assert_charge,
    create_payment_payload,
    is_valid_uuid,
    list_allocations,
    list_charges,
    post_payment,
    record_and_post_payment,
    record_payment,
    return_payment,
    run_sweep,
    set_clock,
    setup_property_tenant_lease,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_payment_creation_gated_by_lease_state_draft(api):
    """PRD 3.3: "Payment recording is refused outright once the lease has ended
    (`ERR_LEASE_ALREADY_ENDED`); a lease still in `DRAFT` may record a payment, but
    that payment cannot be posted until the lease is active."
    PRD 2.9 rule 6: "Operations that require an `ACTIVE` lease (payment posting,
    notice creation and issuance, plan creation) fail with `ERR_LEASE_NOT_ACTIVE`
    while the lease is still in `DRAFT`; operations that are never permitted once a
    lease has ended (charge creation, payment creation, payment posting, notice
    creation and issuance, plan creation) fail with `ERR_LEASE_ALREADY_ENDED` on an
    `ENDED` lease."

    Design: Difficulty/cross_entity_state_dependency/payment_creation_gated_by_lease_state
    """
    ctx = setup_property_tenant_lease(activate=False)
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)

    # While DRAFT, a payment may be recorded but cannot be posted.
    pending = record_payment(lease_id, ctx["tenant"]["id"], amount_cents=200000)
    response = api.transition_payment(pending["id"], {"action": "POST"}, AGENT)
    validate_error(response, ApiErrorId.ERR_LEASE_NOT_ACTIVE)

    # Once ACTIVE, posting succeeds end to end.
    response = api.transition_lease(lease_id, {"action": "ACTIVATE"}, PM)
    validate_success(response)
    posted = post_payment(pending["id"])
    assert posted["status"] == "POSTED"


def test_payment_creation_gated_by_lease_state_ended(api):
    """PRD 3.3: "Payment recording is refused outright once the lease has ended
    (`ERR_LEASE_ALREADY_ENDED`); a lease still in `DRAFT` may record a payment, but
    that payment cannot be posted until the lease is active."

    Design: Difficulty/cross_entity_state_dependency/payment_creation_gated_by_lease_state
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    set_clock("2026-08-20T00:00:00Z")
    validate_success(
        api.transition_lease(lease_id, {"action": "MOVE_OUT", "move_out_date": "2026-08-20"}, PM)
    )
    response = api.create_payment(
        create_payment_payload(lease_id, ctx["tenant"]["id"], amount_cents=100000, received_date="2026-08-20"),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_LEASE_ALREADY_ENDED)


def test_payment_return_from_pending_rejected(api):
    """PRD 2.9 rule 7: "Each resource's transition is checked against its state
    machine — a payment must be `PENDING` or `RETURNED` to post and `POSTED` to return
    (`ERR_PAYMENT_INVALID_TRANSITION`); ..."

    Design: Corner/state_machines/payment_return_from_pending_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)

    response = api.transition_payment(
        payment["id"], {"action": "RETURN", "reason_code": "NSF", "nsf_fee_cents": 3000}, AGENT
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_INVALID_TRANSITION)

    reread = validate_success(api.get_payment(payment["id"], PM))
    assert reread["status"] == "PENDING"
    assert reread["return_count"] == 0


def test_payment_return_card_channel_rejected(api):
    """PRD 3.4: "Only bank-mediated tenders can come back: a return may be recorded on
    a `POSTED` payment whose `channel` is `ACH` or `CHECK`, while a return attempted on
    any other channel is rejected with `ERR_CHANNEL_NOT_RETURNABLE`."

    Design: Corner/state_machines/payment_return_card_channel_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=200000)

    response = api.transition_payment(
        payment["id"], {"action": "RETURN", "reason_code": "NSF", "nsf_fee_cents": 3000}, AGENT
    )
    validate_error(response, ApiErrorId.ERR_CHANNEL_NOT_RETURNABLE)

    reread = validate_success(api.get_payment(payment["id"], PM))
    assert reread["status"] == "POSTED"
    rent = [c for c in list_charges(lease_id) if c["id"] == charge["id"]][0]
    assert rent["status"] == "PAID"


def test_payment_posted_returned_posted_cycle(api):
    """PRD 3.4: "A returned payment is not dead. Re-presentment — requesting the
    posting transition again on a `RETURNED` payment — is permitted once the lease is
    `ACTIVE` and the payment clears the same two acceptance rules against the current
    outstanding. The waterfall then re-runs against the live ledger rather than the
    original target set; in particular, the returned-payment fee charge created by the
    earlier return is itself a fee-class target waiting to be satisfied."
    PRD 3.4: "First, the payment itself flips from `POSTED` to `RETURNED` and its
    `return_count` increases by one."

    Design: Difficulty/non_linear_state_machine/payment_posted_returned_posted_cycle
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)

    set_clock("2026-08-03T00:00:00Z")
    returned = return_payment(payment["id"], nsf_fee_cents=3000)
    assert returned["status"] == "RETURNED"

    set_clock("2026-08-04T00:00:00Z")
    reposted = post_payment(payment["id"])
    assert reposted["status"] == "POSTED"
    assert reposted["return_count"] == 1

    charges = {c["id"]: c for c in list_charges(lease_id)}
    rent = charges[charge["id"]]
    assert rent["outstanding_cents"] == 3000, (
        f"Re-presentment under FEES_FIRST pays the 3000 NSF fee first, leaving rent at 3000; got {rent['outstanding_cents']}"
    )
    assert rent["status"] == "PARTIALLY_PAID"
    nsf_fees = [c for c in charges.values() if c["kind"] == "NSF_FEE"]
    assert len(nsf_fees) == 1 and nsf_fees[0]["status"] == "PAID" and nsf_fees[0]["amount_cents"] == 3000

    allocs = list_allocations(params={"payment_id": payment["id"]})
    triples = sorted((a["direction"], a["amount_cents"], a["allocation_order"]) for a in allocs)
    assert ("APPLY", 200000, 1) in triples
    assert ("REVERSE", 200000, 1) in triples
    assert ("APPLY", 3000, 1) in triples
    assert ("APPLY", 197000, 2) in triples


def test_payment_application_conservation_on_post(api):
    """PRD 3.3: "The waterfall walks that order, allocating to each charge the lesser
    of the remaining payment money and that charge's outstanding balance, and stops the
    moment no payment money remains."

    Design: Difficulty/compensating_invariant/payment_application_conservation_on_return
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=100000)

    allocs = list_allocations(params={"payment_id": payment["id"]})
    assert len(allocs) == 2
    assert all(a["direction"] == "APPLY" for a in allocs)
    assert sum(a["amount_cents"] for a in allocs) == 100000 == payment["amount_cents"]
    first = [a for a in allocs if a["allocation_order"] == 1][0]
    assert first["charge_id"] == damage["id"] and first["amount_cents"] == 10000


def test_payment_application_conservation_on_return(api):
    """PRD 3.4: "Second, for every `APPLY` allocation the payment ever created, the
    system writes a `REVERSE` allocation of equal amount bearing the note
    `nsf-reversal`."

    Design: Difficulty/compensating_invariant/payment_application_conservation_on_return
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=100000)

    set_clock("2026-08-03T00:00:00Z")
    returned = return_payment(payment["id"], nsf_fee_cents=3000)
    assert returned["status"] == "RETURNED"
    assert returned["return_count"] == 1

    allocs = list_allocations(params={"payment_id": payment["id"]})
    apply_sum = sum(a["amount_cents"] for a in allocs if a["direction"] == "APPLY")
    reverse_sum = sum(a["amount_cents"] for a in allocs if a["direction"] == "REVERSE")
    assert apply_sum == 100000
    assert reverse_sum == apply_sum, "sum(REVERSE) must equal sum(APPLY) exactly after a full return"
    assert apply_sum - reverse_sum == 0, "net applied must be zero after the return"
    assert all(a["note"] == "nsf-reversal" for a in allocs if a["direction"] == "REVERSE")


def test_nsf_fee_clamped_at_property_cap(api):
    """PRD 3.4: "Fourth, every `DRAFT` notice covering an affected charge recomputes
    its demanded amount, and the returned-payment fee is assessed as a new `NSF_FEE`
    charge on the lease: its amount is the lesser of the requested `nsf_fee_cents` and
    the property's `nsf_fee_cap_cents`, it is due on the current date, its source is
    `RETURN`, and its coverage period is the current date itself."

    Design: Corner/calculations/nsf_fee_clamped_at_property_cap
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)
    set_clock("2026-08-03T00:00:00Z")

    return_payment(payment["id"], nsf_fee_cents=9000)
    nsf_charges = list_charges(lease_id, params={"kind": "NSF_FEE"})
    assert len(nsf_charges) == 1
    fee = nsf_charges[0]
    assert_charge(fee)
    assert fee["amount_cents"] == 3500, f"min(9000, cap 3500) must be 3500, got {fee['amount_cents']}"
    assert fee["source"] == "RETURN"


def test_payment_overpayment_rejected(api):
    """PRD 3.3: "First, the tendered amount must not exceed that total; an overpayment
    is rejected with `ERR_OVERPAYMENT_REJECTED`."

    Design: Corner/validations/payment_overpayment_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=200001)

    response = api.transition_payment(payment["id"], {"action": "POST"}, AGENT)
    validate_error(response, ApiErrorId.ERR_OVERPAYMENT_REJECTED)

    reread = validate_success(api.get_payment(payment["id"], PM))
    assert reread["status"] == "PENDING"
    allocs = list_allocations(params={"payment_id": payment["id"]})
    assert allocs == []


def test_partial_payment_floor_exact_cent_below_rejected(api):
    """PRD 3.3: "Second, a payment that does not exactly equal the total outstanding
    must be at least the total outstanding multiplied by the property's
    `min_partial_payment_percent`, divided by one hundred, and rounded up to a whole
    cent; anything smaller is rejected with `ERR_PARTIAL_BELOW_MINIMUM`."

    Design: Difficulty/boundary_precision_check/partial_payment_floor_exact_cent
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=49999)

    response = api.transition_payment(payment["id"], {"action": "POST"}, AGENT)
    validate_error(response, ApiErrorId.ERR_PARTIAL_BELOW_MINIMUM)


def test_partial_payment_floor_exact_cent_at_floor_posts(api):
    """PRD 3.3: "Second, a payment that does not exactly equal the total outstanding
    must be at least the total outstanding multiplied by the property's
    `min_partial_payment_percent`, divided by one hundred, and rounded up to a whole
    cent; anything smaller is rejected with `ERR_PARTIAL_BELOW_MINIMUM`."
    PRD 3.2: "From `OPEN`, a charge moves to `PARTIALLY_PAID` when an allocation
    covers less than the outstanding balance; from either `OPEN` or `PARTIALLY_PAID`,
    it moves to `PAID` when net applied cents exactly cover the face amount net of
    waivers."

    Design: Difficulty/boundary_precision_check/partial_payment_floor_exact_cent
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=50000)

    posted = post_payment(payment["id"])
    assert posted["status"] == "POSTED"
    rent = [c for c in list_charges(lease_id) if c["id"] == charge["id"]][0]
    assert rent["outstanding_cents"] == 150000
    assert rent["status"] == "PARTIALLY_PAID"


def test_clock_default_applies_to_received_date(api):
    """PRD 2.4: "The logical clock starts at exactly 2026-08-01T00:00:00Z before any
    clock-setting call is made, and it never falls back to wall-clock time thereafter."
    PRD 3.3: "The `received_date` is optional and defaults to the server's current
    date; when supplied it must not lie in the future."

    Design: Corner/cross_cutting_layers/clock_default_applies_to_received_date
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)

    payload = create_payment_payload(lease_id, ctx["tenant"]["id"], amount_cents=200000)
    del payload["received_date"]
    payment = validate_success(api.create_payment(payload, AGENT), 201)
    assert payment["received_date"] == "2026-08-01", (
        f"received_date must default to the logical clock date 2026-08-01, got {payment['received_date']!r}"
    )
