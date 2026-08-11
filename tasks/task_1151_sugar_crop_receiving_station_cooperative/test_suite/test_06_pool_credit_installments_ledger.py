"""Pool accrual, ticket crediting and its fiscal cap, installment scheduling
(OCC) and the advance waterfall, and the append-only ledger's reversal flow."""
from test_helpers import (
    ApiErrorId,
    SLOT_AM_END,
    SLOT_AM_START,
    WEIGH_CLOCK_AM,
    create_campaign,
    create_confirmed_booking,
    create_installment,
    create_installment_payload,
    issue_installment,
    list_ledger_entries,
    make_sampled_ticket,
    open_pool_accrual,
    setup_accepted_world,
    setup_credited_world,
    setup_two_member_credited_world,
    setup_world,
    validate_error,
    validate_success,
)


def test_credit_rejected_while_pool_open(api, pool_accountant_headers):
    """PRD §3.7: "Crediting requires the ticket to be in `ACCEPTED` status — a
    credit attempt on a ticket in any other state is rejected with
    `ERR_TICKET_NOT_CREDITABLE` — and requires the pool of the ticket's campaign
    to be `ACCRUING`, else `ERR_POOL_NOT_ACCRUING`."

    Design: Difficulty/cross_entity_state_dependency/ticket_credit_requires_pool_accruing
    """
    world = setup_accepted_world()  # ticket ACCEPTED; pool still OPEN
    res = api.credit_ticket(world["ticket"]["id"], pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_POOL_NOT_ACCRUING.value)


def test_credit_after_open_accrual_accrues_provisional_value(api, pool_accountant_headers):
    """PRD §3.7: "A successful credit moves the ticket from `ACCEPTED` to its
    terminal `CREDITED` state, adds the ticket's `provisional_value_cents` to the
    pool's `accrued_provisional_cents`, and increments both the ticket's and the
    pool's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/ticket_credit_requires_pool_accruing
    """
    # Provisional basis here is the first-recorded sample: the LAB_VERIFY sample
    # 16.10/4.40 (no quick sample recorded first) -> factor 1.0040,
    # adjusted 23.6640 t, value round(23.6640 x 5500 x 1.0040) = 130673.
    world = setup_accepted_world(sugar_pct=16.10, trash_pct=4.40)
    pool = open_pool_accrual(world["campaign"]["id"], 700000)
    credited = validate_success(
        api.credit_ticket(world["ticket"]["id"], pool_accountant_headers), 200)
    assert credited["status"] == "CREDITED"
    pool_after = validate_success(api.get_pool(pool["id"], pool_accountant_headers), 200)
    assert pool_after["accrued_provisional_cents"] == 130673


def test_credit_state_precondition_beats_pool_cap_fiscal(api, pool_accountant_headers):
    """PRD §2.7: "Incoming requests are validated in a fixed priority order, so
    that when several problems afflict the same request, the earliest check
    determines the error surfaced." and "State-machine and request-shape checks
    run fifth (`ERR_INVALID_STATE`, `ERR_INVALID_REQUEST`,
    `ERR_TICKET_NOT_CREDITABLE`, `ERR_BOOKING_NOT_CONFIRMED`,
    `ERR_CAMPAIGN_NOT_OPEN`, `ERR_POOL_NOT_ACCRUING`, `ERR_PILE_NOT_FILLING`,
    `ERR_LAB_SAMPLE_REQUIRED`)" while "fiscal checks last
    (`ERR_POOL_ACCRUAL_CAP_EXCEEDED`, `ERR_INSTALLMENT_PCT_INVALID`,
    `ERR_POOL_NO_SUGAR`, `ERR_REVERSAL_NOT_ALLOWED`)".

    Design: Difficulty/priority_pair_validation_conflict/credit_state_precondition_beats_pool_cap_fiscal
    """
    world = setup_world()
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 30)
    # SAMPLED ticket with provisional value 132620; pool cap is 1000 x 1.10 = 1100.
    ticket, _s = make_sampled_ticket(booking["id"], 80000, 32000, WEIGH_CLOCK_AM,
                                     sugar_pct=16.50, trash_pct=4.50,
                                     sample_type="STATION_QUICK")
    assert ticket["provisional_value_cents"] == 132620
    open_pool_accrual(world["campaign"]["id"], 1000)
    res = api.credit_ticket(ticket["id"], pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_CREDITABLE.value)


def test_credit_fiscal_cap_fires_once_state_valid(api, pool_accountant_headers):
    """PRD §3.7: "A fiscal ceiling applies on top: the pool's
    `accrued_provisional_cents` plus the ticket's `provisional_value_cents` must
    not exceed 110 percent of the pool's `estimated_pool_value_cents` — that is,
    the estimated value multiplied by 1.10. A credit that would breach the cap is
    rejected with `ERR_POOL_ACCRUAL_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/credit_state_precondition_beats_pool_cap_fiscal
    """
    # Same world as the priority-pair sibling, but with the ticket ACCEPTED so
    # only the fiscal check (cap 1000 x 1.10 = 1100 < 132620) can fire.
    world = setup_accepted_world(quick_first=(16.50, 4.50))
    assert world["ticket"]["provisional_value_cents"] == 132620
    open_pool_accrual(world["campaign"]["id"], 1000)
    res = api.credit_ticket(world["ticket"]["id"], pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_POOL_ACCRUAL_CAP_EXCEEDED.value)
    after = validate_success(api.get_ticket(world["ticket"]["id"],
                                            pool_accountant_headers), 200)
    assert after["status"] == "ACCEPTED"


def test_credit_fiscal_cap_fires_when_state_valid(api, pool_accountant_headers):
    """PRD §3.7: "A fiscal ceiling applies on top: the pool's
    `accrued_provisional_cents` plus the ticket's `provisional_value_cents` must
    not exceed 110 percent of the pool's `estimated_pool_value_cents` — that is,
    the estimated value multiplied by 1.10. A credit that would breach the cap is
    rejected with `ERR_POOL_ACCRUAL_CAP_EXCEEDED`."

    Design: Corner/validations/credit_fiscal_cap_fires_when_state_valid
    """
    world = setup_accepted_world(quick_first=(16.50, 4.50))
    assert world["ticket"]["status"] == "ACCEPTED"
    assert world["ticket"]["provisional_value_cents"] == 132620
    open_pool_accrual(world["campaign"]["id"], 100000)  # cap = 110000
    res = api.credit_ticket(world["ticket"]["id"], pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_POOL_ACCRUAL_CAP_EXCEEDED.value)
    after = validate_success(api.get_ticket(world["ticket"]["id"],
                                            pool_accountant_headers), 200)
    assert after["status"] == "ACCEPTED"


def test_pool_close_with_zero_sugar_returns_error(api, pool_accountant_headers,
                                                  admin_headers):
    """PRD §3.10: "Closing the pool is the pivot from accrual to settlement, and
    a `POOL_ACCOUNTANT` may close it only when four conditions hold: the campaign
    is `CLOSED` (`ERR_INVALID_STATE`); no load ticket of the campaign remains in
    `CREATED`, `WEIGHED`, `REWEIGHING`, `SAMPLED`, or `ACCEPTED`
    (`ERR_INVALID_STATE`); every storage pile holding allocations from the
    campaign's tickets is `EMPTY` (`ERR_INVALID_STATE`); and the total post-loss
    sugar pounds over the campaign's `CREDITED` tickets is greater than zero
    (`ERR_POOL_NO_SUGAR`)."

    Design: Corner/calculations/pool_close_with_zero_sugar_returns_error
    """
    campaign = create_campaign()
    pool = open_pool_accrual(campaign["id"], 700000)
    validate_success(api.close_campaign(campaign["id"], admin_headers), 200)
    res = api.close_pool(pool["id"], {"gross_pool_value_cents": 1000000},
                         pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_POOL_NO_SUGAR.value)


def test_installment_pct_out_of_bounds_returns_error(api, pool_accountant_headers):
    """PRD §3.9: "Creating an installment takes `pct_of_estimated` — the
    percentage of the estimated pool value to distribute as advances, which must
    be greater than 0 and at most 100, else `ERR_INSTALLMENT_PCT_INVALID`".

    Design: Corner/validations/installment_pct_out_of_bounds_returns_error
    """
    campaign = create_campaign()
    pool = open_pool_accrual(campaign["id"], 700000)
    version = pool["version"]
    res1 = api.create_pool_installment(
        pool["id"], create_installment_payload(0, version), pool_accountant_headers)
    validate_error(res1, ApiErrorId.ERR_INSTALLMENT_PCT_INVALID.value)
    res2 = api.create_pool_installment(
        pool["id"], create_installment_payload(100.01, version), pool_accountant_headers)
    validate_error(res2, ApiErrorId.ERR_INSTALLMENT_PCT_INVALID.value)


def test_occ_installment_create_stale_pool_version(api, pool_accountant_headers):
    """PRD §2.6: "Creating a pool installment against a payment pool requires the
    request body to carry `expected_pool_version`, a non-optional field holding
    the `version` of the target `PaymentPool` as the client last observed it. If
    the value presented does not match the pool's current `version` — because
    another writer has advanced the pool's version since the client read it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/complexity_layers/occ_installment_create_stale_pool_version
    """
    campaign = create_campaign()
    pool = open_pool_accrual(campaign["id"], 700000)
    captured_version = pool["version"]
    first = validate_success(api.create_pool_installment(
        pool["id"], create_installment_payload(25, captured_version),
        pool_accountant_headers), 201)
    assert first["target_amount_cents"] == 175000  # 25% of 700000
    res = api.create_pool_installment(
        pool["id"], create_installment_payload(25, captured_version),
        pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_installment_waterfall_two_member_remainder(api, pool_accountant_headers):
    """PRD §3.9: "Each member's raw advance is the installment's
    `target_amount_cents` multiplied by their E_m and divided by the sum of E_m
    over all eligible members, then floored to integer cents. The remainder —
    the target minus the sum of floored advances — is distributed one cent at a
    time to members ordered by E_m descending, ties broken by `member_code`
    ascending."
    PRD §3.9: "One `ADVANCE_CREDIT` ledger entry is created per member whose
    final advance is greater than zero, with `member_id`, `pool_id`, and
    `installment_id` set; each paid member's `net_ledger_cents` is recomputed;
    the installment's `distributed_amount_cents` records the sum of created
    advances".

    Design: Corner/calculations/installment_waterfall_two_member_remainder
    """
    world = setup_two_member_credited_world()
    # E1 = 132620 (provisional via quick 16.50/4.50), E2 = 92224 (16.0 t x 5500
    # x 1.0480). Target = 30% of 700000 = 210000.
    installment = create_installment(world["pool"], 30)
    assert installment["target_amount_cents"] == 210000
    issued = validate_success(
        api.issue_installment(installment["id"], pool_accountant_headers), 200)
    assert issued["status"] == "ISSUED"
    assert issued["distributed_amount_cents"] == 210000

    adv1 = list_ledger_entries(member_id=world["m1"]["id"], kind="ADVANCE_CREDIT")
    adv2 = list_ledger_entries(member_id=world["m2"]["id"], kind="ADVANCE_CREDIT")
    assert len(adv1) == 1 and len(adv2) == 1
    # floors: 123864 and 86135; the 1-cent remainder goes to the largest E (M1).
    assert adv1[0]["amount_cents"] == 123865
    assert adv2[0]["amount_cents"] == 86135

    m1 = validate_success(api.get_member(world["m1"]["id"], pool_accountant_headers), 200)
    m2 = validate_success(api.get_member(world["m2"]["id"], pool_accountant_headers), 200)
    assert m1["net_ledger_cents"] == 123865
    assert m2["net_ledger_cents"] == 86135


def test_ledger_advance_post_raises_net_ledger(api, pool_accountant_headers):
    """PRD §3.9: "Each member's advance is then capped: it may not exceed the
    member's E_m minus the member's already-advanced amount for this pool, where
    already-advanced is the member's net `ADVANCE_CREDIT` (advances plus any
    reversals)."
    PRD §2.8: "A member's `net_ledger_cents` is the sum of `amount_cents` over
    all of that member's `PaymentLedgerEntry` rows of every kind".

    Design: Difficulty/compensating_invariant/ledger_advance_post_then_reverse_conserves_net
    """
    world = setup_credited_world(quick_first=(16.50, 4.50))
    # E1 = 132620; target 30% of 700000 = 210000; advance = min(210000, 132620).
    installment = create_installment(world["pool"], 30)
    assert installment["target_amount_cents"] == 210000
    issued = validate_success(
        api.issue_installment(installment["id"], pool_accountant_headers), 200)
    assert issued["distributed_amount_cents"] == 132620
    entries = list_ledger_entries(installment_id=installment["id"])
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 132620
    member = validate_success(
        api.get_member(world["member"]["id"], pool_accountant_headers), 200)
    assert member["net_ledger_cents"] == 132620


def test_ledger_reverse_restores_net_and_cannot_repeat(api, pool_accountant_headers):
    """PRD §2.8: "An error in a posted advance is never edited or deleted; it is
    compensated by posting a new entry of kind `REVERSAL` whose `amount_cents` is
    the negation of the original entry's amount and whose `reversal_of_id`
    references the original entry's `id`. A reversal is only permitted on an
    entry of kind `ADVANCE_CREDIT` that has not already been reversed, and only
    while the entry's pool is still in `ACCRUING` status; any other reversal
    attempt is rejected with `ERR_REVERSAL_NOT_ALLOWED` (409)."

    Design: Difficulty/compensating_invariant/ledger_advance_post_then_reverse_conserves_net
    """
    world = setup_credited_world(quick_first=(16.50, 4.50))
    installment = create_installment(world["pool"], 30)
    issue_installment(installment["id"])
    advance = list_ledger_entries(installment_id=installment["id"])[0]

    reversal = validate_success(
        api.reverse_ledger_entry(advance["id"], pool_accountant_headers), 201)
    assert reversal["kind"] == "REVERSAL"
    assert reversal["amount_cents"] == -132620
    assert reversal["reversal_of_id"] == advance["id"]
    member = validate_success(
        api.get_member(world["member"]["id"], pool_accountant_headers), 200)
    assert member["net_ledger_cents"] == 0  # forward post + compensating reversal

    res = api.reverse_ledger_entry(advance["id"], pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_REVERSAL_NOT_ALLOWED.value)
