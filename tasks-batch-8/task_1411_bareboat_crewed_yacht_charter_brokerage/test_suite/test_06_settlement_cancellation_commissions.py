"""Completion settlement cascade, cancellation refund cascade, penalty tiers
and boundaries, commission rounding order, escrow conservation, and calendar
block conservation under rebook."""
from test_helpers import (
    ApiErrorId,
    accept_request,
    add_expense,
    assert_commission_statement,
    assert_escrow_closed_invariants,
    create_rebook_payload,
    create_request,
    fund_all,
    fund_tranche,
    get_agreement_escrow,
    list_movements,
    make_offer,
    review_expense,
    set_clock,
    setup_accepted_agreement,
    setup_fully_funded_agreement,
    setup_in_prep_agreement,
    setup_signed_agreement,
    setup_underway_agreement,
    submit_request,
    summarize_movements,
    TEST_USERS,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _commission_statements(api, agreement_id, headers):
    statements, _ = validate_paginated(
        api.list_commission_statements(agreement_id, headers))
    return statements


def test_cancellation_cascade_terminal_states(api):
    """PRD section 3.9: "When every movement has posted, a
    `CommissionStatement` with `basis` `CANCELLATION_PENALTY` is written if
    and only if the retained amount is greater than zero, its
    `basis_amount_cents` equal to the retained penalty; the escrow closes —
    every held bucket at zero, funded equal to released — and the funds axis
    settles into `REFUNDED`."
    PRD section 3.9: "The penalty tier keys off that notice: ninety days or
    more before start costs ten percent of the charter fee; sixty to
    eighty-nine days costs thirty percent — so a cancellation exactly sixty
    days out lands in the thirty-percent tier while fifty-nine days lands in
    the fifty-percent tier; thirty to fifty-nine days costs fifty percent; and
    twenty-nine days or fewer costs the full fee."

    Design: Difficulty/transitive_cascade/cancellation_cascade_depth_six
    """
    # 20-day charter on Yacht A: fee 2000000, apa 0.25 -> 500000, deposit 500000.
    from test_helpers import make_central_agent_headers

    ctx = setup_fully_funded_agreement(start_date="2026-10-30",
                                       end_date="2026-11-19")
    assert ctx.escrow["total_funded_cents"] == 3000000

    set_clock("2026-08-31T00:00:00Z")  # exactly 60 whole days before start
    cancelled = validate_success(
        api.cancel(ctx.agreement["id"], {"reason": "weather window"},
                   make_central_agent_headers(ctx.central_agent["id"])),
        200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["funds_status"] == "REFUNDED"
    assert cancelled["days_before_start"] == 60
    assert cancelled["cancellation_penalty_cents"] == 600000, (
        "sixty days out lands in the thirty-percent tier")

    escrow = get_agreement_escrow(ctx.agreement["id"])
    assert_escrow_closed_invariants(escrow)
    assert escrow["total_funded_cents"] == 3000000
    assert escrow["total_released_cents"] == 3000000


def test_cancellation_cascade_movements_block_and_request(api):
    """PRD section 3.9: "The cascade then unwinds the money. The funds axis —
    from whichever of `UNFUNDED`, `DEPOSIT_HELD`, or `FULLY_FUNDED` it sits in
    — moves to `REFUNDING`, and the escrow moves from `OPEN` to `SETTLING` as
    its movements post: the client is refunded the held charter fee minus the
    retained amount, the entire held APA, the entire held gratuity, and the
    held deposit less any approved damage claims; when anything is retained, a
    penalty commission of twenty percent of the retained amount, rounded
    half-up, is carved off — the operator's release from the `CHARTER_FEE`
    bucket is the retained amount minus that commission, while the retail
    broker receives the retail share of the penalty commission (the commission
    multiplied by `retail_pct_bps` over ten thousand, rounded half-up) and the
    central agent receives the residual central share, the same pinned
    rounding order as section 3.8 with `basis` `CANCELLATION_PENALTY`."
    PRD section 3.9: "Escrow closure releases the agreement's `CHARTER` block
    from `ACTIVE` to `RELEASED` — the only way such a block is ever released —
    incrementing the yacht's `version` by one, and that release in turn
    transitions the source charter request from `ACCEPTED` to `CANCELLED`,
    incrementing its `version` as well."

    Design: Difficulty/transitive_cascade/cancellation_cascade_depth_six
    """
    from test_helpers import make_central_agent_headers

    ctx = setup_fully_funded_agreement(start_date="2026-10-30",
                                       end_date="2026-11-19")
    yacht_after_accept = validate_success(
        api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)

    set_clock("2026-08-31T00:00:00Z")
    validate_success(
        api.cancel(ctx.agreement["id"], {"reason": "weather window"},
                   make_central_agent_headers(ctx.central_agent["id"])),
        200)

    movements = list_movements(ctx.escrow["id"])
    totals = summarize_movements(movements)
    # retained = min(600000 penalty, 2000000 held fee) = 600000.
    assert totals[("REFUND_TO_CLIENT", "CHARTER_FEE")] == 1400000
    assert totals[("REFUND_TO_CLIENT", "APA")] == 500000
    assert totals[("REFUND_TO_CLIENT", "DEPOSIT")] == 500000
    # Penalty commission 20% of 600000 = 120000; operator release 480000.
    assert totals[("RELEASE_TO_OPERATOR", "CHARTER_FEE")] == 480000
    # retail_pct_bps was pinned to 5000 by the fixture offer: 60000 each.
    assert totals[("RELEASE_TO_RETAIL_BROKER", "CHARTER_FEE")] == 60000
    assert totals[("RELEASE_TO_CENTRAL_AGENT", "CHARTER_FEE")] == 60000

    blocks, _ = validate_paginated(
        api.list_agreement_availability_blocks(ctx.agreement["id"], ctx.op_headers))
    assert len(blocks) == 1 and blocks[0]["status"] == "RELEASED"

    yacht = validate_success(api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert yacht["version"] == yacht_after_accept["version"] + 1, (
        "the block release increments the yacht's version by one")

    request = validate_success(
        api.get_charter_request(ctx.request["id"], ctx.cl_headers), 200)
    assert request["status"] == "CANCELLED", (
        "the block release transitions the source request ACCEPTED -> CANCELLED")

    statements = _commission_statements(api, ctx.agreement["id"], ctx.cl_headers)
    assert len(statements) == 1
    stmt = statements[0]
    assert_commission_statement(stmt)
    assert stmt["basis"] == "CANCELLATION_PENALTY"
    assert stmt["basis_amount_cents"] == 600000
    assert stmt["commission_total_cents"] == 120000
    assert stmt["retail_share_cents"] == 60000
    assert stmt["central_share_cents"] == 60000


def test_completion_locks_expenses_and_settles_escrow(api):
    """PRD section 3.8: "Completion moves the lifecycle axis from `UNDERWAY`
    to `COMPLETED` and fires a four-hop cascade."
    PRD section 3.8: "The first hop flips the funds axis from `FULLY_FUNDED`
    to `SETTLING` and locks the books: every expense still `PENDING` or
    `DISPUTED` is auto-rejected, and the APA's final position — approved spend
    only — becomes the settlement basis."
    PRD section 3.8: "The second hop posts the settlement movements and moves
    the escrow from `OPEN` to `SETTLING`: a `RELEASE_TO_OPERATOR` from the
    `APA` bucket for the final approved spend; a `REFUND_TO_CLIENT` from `APA`
    for the held APA minus that spend; a `RELEASE_TO_OPERATOR` from `GRATUITY`
    for the entire held gratuity; the deposit settlement — a
    `RELEASE_TO_OPERATOR` from `DEPOSIT` for the approved damage claims,
    capped so it never exceeds the held deposit, and a `REFUND_TO_CLIENT` from
    `DEPOSIT` for the remainder, the two always summing exactly to the held
    deposit; and the charter-fee split — a `RELEASE_TO_OPERATOR` from
    `CHARTER_FEE` for the fee minus the total commission, a
    `RELEASE_TO_RETAIL_BROKER` for the retail share, and a
    `RELEASE_TO_CENTRAL_AGENT` for the central share."

    Design: Difficulty/transitive_cascade/completion_settlement_cascade_depth_four
    """
    # 10-day Yacht A: fee 1000000, apa 300000, deposit 500000; funded 1800000.
    ctx = setup_underway_agreement(start_date="2026-11-02", end_date="2026-11-12",
                                   charter_start="2026-11-02")
    pending_expense = add_expense(ctx.agreement["id"], ctx.operator["id"],
                                  bucket="APA", description="unreviewed fuel",
                                  amount_cents=12345)

    set_clock("2026-11-12T00:00:00Z")  # reached end_date
    completed = validate_success(api.complete(ctx.agreement["id"], ctx.ca_headers),
                                 200)
    assert completed["status"] == "COMPLETED"
    assert completed["funds_status"] == "SETTLED", (
        "the fourth hop settles the funds axis from SETTLING to SETTLED")

    expenses, _ = validate_paginated(
        api.list_expenses(ctx.agreement["id"], ctx.op_headers))
    by_id = {e["id"]: e for e in expenses}
    assert by_id[pending_expense["id"]]["status"] == "REJECTED", (
        "settlement locks unresolved expenses before the APA final position")

    movements = list_movements(ctx.escrow["id"])
    totals = summarize_movements(movements)
    # Commission: 1000000 is in the eighteen-percent tier -> 180000 total;
    # retail_pct_bps 5000 (pinned by the fixture offer) -> 90000 each share.
    assert totals[("RELEASE_TO_OPERATOR", "CHARTER_FEE")] == 820000
    assert totals[("RELEASE_TO_RETAIL_BROKER", "CHARTER_FEE")] == 90000
    assert totals[("RELEASE_TO_CENTRAL_AGENT", "CHARTER_FEE")] == 90000
    assert totals[("REFUND_TO_CLIENT", "APA")] == 300000, (
        "no APA expense was approved, so the entire held APA is refunded")
    assert totals[("REFUND_TO_CLIENT", "DEPOSIT")] == 500000

    escrow = get_agreement_escrow(ctx.agreement["id"])
    assert_escrow_closed_invariants(escrow)
    assert escrow["total_funded_cents"] == 1800000
    assert escrow["total_released_cents"] == 1800000


def test_completion_writes_commission_statement_keeps_block(api):
    """PRD section 3.8: "The commission behind that split is tiered on the
    charter fee: fifteen percent when the fee is below 1,000,000 cents,
    eighteen percent when it is at least 1,000,000 and at most 4,999,999
    cents, and twenty percent when it reaches 5,000,000 cents."
    PRD section 3.8: "The third hop fires once every required movement is
    posted: it writes the `CommissionStatement` with `basis` `CHARTER_FEE`,
    the `basis_amount_cents` equal to the charter fee, and the
    `commission_total_cents`, `retail_share_cents`, and `central_share_cents`
    exactly as computed; then it closes the escrow — `SETTLING` to `CLOSED` —
    leaving every held bucket at zero and the funding and release totals
    equal."
    PRD section 3.9: "Escrow closure releases the agreement's `CHARTER` block
    from `ACTIVE` to `RELEASED` — the only way such a block is ever released —
    incrementing the yacht's `version` by one, and that release in turn
    transitions the source charter request from `ACCEPTED` to `CANCELLED`,
    incrementing its `version` as well."

    Design: Difficulty/transitive_cascade/completion_settlement_cascade_depth_four
    """
    ctx = setup_underway_agreement(start_date="2026-11-02", end_date="2026-11-12",
                                   charter_start="2026-11-02")
    set_clock("2026-11-12T00:00:00Z")
    validate_success(api.complete(ctx.agreement["id"], ctx.op_headers), 200)

    statements = _commission_statements(api, ctx.agreement["id"], ctx.cl_headers)
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt["basis"] == "CHARTER_FEE"
    assert stmt["basis_amount_cents"] == 1000000
    assert stmt["commission_total_cents"] == 180000
    assert stmt["retail_share_cents"] == 90000
    assert stmt["central_share_cents"] == 90000

    # Completion does NOT release the calendar: the CHARTER block stays ACTIVE
    # (only escrow closure *after a cancellation* releases it), and the
    # request remains ACCEPTED.
    blocks, _ = validate_paginated(
        api.list_agreement_availability_blocks(ctx.agreement["id"], ctx.op_headers))
    assert len(blocks) == 1 and blocks[0]["status"] == "ACTIVE"
    request = validate_success(
        api.get_charter_request(ctx.request["id"], ctx.cl_headers), 200)
    assert request["status"] == "ACCEPTED"


def test_cancellation_penalty_tier_and_retained_cap(api):
    """PRD section 3.9: "What the operator actually retains is capped by what
    the escrow holds: the retained amount is the smaller of the penalty and
    the held charter fee."
    PRD section 3.9: "The penalty tier keys off that notice: ninety days or
    more before start costs ten percent of the charter fee; sixty to
    eighty-nine days costs thirty percent — so a cancellation exactly sixty
    days out lands in the thirty-percent tier while fifty-nine days lands in
    the fifty-percent tier; thirty to fifty-nine days costs fifty percent; and
    twenty-nine days or fewer costs the full fee."

    Design: Difficulty/combinatorial_formula/cancellation_penalty_tier_and_retained_cap
    """
    # 20-day charter: fee 2000000; only SIGNING funded (fee bucket 1000000).
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    fund_tranche(ctx.agreement["id"], "SIGNING", 1500000, ctx.client["id"])

    set_clock("2026-09-30T00:00:00Z")  # exactly 30 days before 2026-10-30
    cancelled = validate_success(
        api.cancel(ctx.agreement["id"], {"reason": "client change of plans"},
                   ctx.cl_headers),
        200)
    assert cancelled["days_before_start"] == 30
    assert cancelled["cancellation_penalty_cents"] == 1000000, (
        "thirty days out is the fifty-percent tier on a 2,000,000-cent fee")
    # retained = min(penalty 1000000, held charter fee 1000000) = 1000000:
    # the cap engages at exact equality.
    statements = _commission_statements(api, ctx.agreement["id"], ctx.cl_headers)
    assert len(statements) == 1
    assert statements[0]["basis_amount_cents"] == 1000000, (
        "basis_amount equals the retained penalty — the capped 1,000,000")


def test_cancellation_retained_cap_settlement_movements(api):
    """PRD section 3.9: "The cascade then unwinds the money. The funds axis —
    from whichever of `UNFUNDED`, `DEPOSIT_HELD`, or `FULLY_FUNDED` it sits in
    — moves to `REFUNDING`, and the escrow moves from `OPEN` to `SETTLING` as
    its movements post: the client is refunded the held charter fee minus the
    retained amount, the entire held APA, the entire held gratuity, and the
    held deposit less any approved damage claims; when anything is retained, a
    penalty commission of twenty percent of the retained amount, rounded
    half-up, is carved off — the operator's release from the `CHARTER_FEE`
    bucket is the retained amount minus that commission, while the retail
    broker receives the retail share of the penalty commission (the commission
    multiplied by `retail_pct_bps` over ten thousand, rounded half-up) and the
    central agent receives the residual central share, the same pinned
    rounding order as section 3.8 with `basis` `CANCELLATION_PENALTY`."

    Design: Difficulty/combinatorial_formula/cancellation_penalty_tier_and_retained_cap
    """
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    escrow = fund_tranche(ctx.agreement["id"], "SIGNING", 1500000,
                          ctx.client["id"])

    set_clock("2026-09-30T00:00:00Z")
    validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers), 200)

    movements = list_movements(escrow["id"])
    totals = summarize_movements(movements)
    # retained == 1000000 == entire held fee, so no CHARTER_FEE refund posts.
    assert ("REFUND_TO_CLIENT", "CHARTER_FEE") not in totals
    assert totals[("REFUND_TO_CLIENT", "DEPOSIT")] == 500000
    # Penalty commission 20% of 1000000 = 200000; operator release 800000.
    assert totals[("RELEASE_TO_OPERATOR", "CHARTER_FEE")] == 800000
    assert totals[("RELEASE_TO_RETAIL_BROKER", "CHARTER_FEE")] == 100000
    assert totals[("RELEASE_TO_CENTRAL_AGENT", "CHARTER_FEE")] == 100000

    closed = get_agreement_escrow(ctx.agreement["id"])
    assert_escrow_closed_invariants(closed)
    assert closed["total_funded_cents"] == 1500000
    assert closed["total_released_cents"] == 1500000


def test_commission_total_and_retail_share_rounding(api):
    """PRD section 3.8: "The commission behind that split is tiered on the
    charter fee: fifteen percent when the fee is below 1,000,000 cents,
    eighteen percent when it is at least 1,000,000 and at most 4,999,999
    cents, and twenty percent when it reaches 5,000,000 cents. Rounding order
    is pinned and non-negotiable: first the total commission is computed — the
    fee multiplied by the tier rate, rounded half-up to whole cents — then the
    retail share is the total multiplied by the agreement's `retail_pct_bps`
    and divided by ten thousand, rounded half-up to whole cents; the central
    share is never rounded independently but is simply the total minus the
    retail share, so the two shares always reconcile to the cent."

    Design: Difficulty/combinatorial_formula/commission_split_rounding_residual
    """
    # Fee overridden to 666673 (< 1000000 -> 15% tier): total rounds to 100001.
    ctx = setup_underway_agreement(
        start_date="2026-10-01", end_date="2026-10-11",
        charter_start="2026-10-01",
        offer_overrides={"quoted_charter_fee_cents": 666673},
        yacht_preset={"pricing_mode": "WEEKLY_PLUS_DAILY",
                      "security_deposit_cents": 400000})
    assert ctx.agreement["charter_fee_cents"] == 666673

    set_clock("2026-10-11T00:00:00Z")
    validate_success(api.complete(ctx.agreement["id"], ctx.op_headers), 200)

    statements = _commission_statements(api, ctx.agreement["id"], ctx.cl_headers)
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt["basis"] == "CHARTER_FEE"
    assert stmt["basis_amount_cents"] == 666673
    # round_half_up(666673 x 0.15) = round_half_up(100000.95) = 100001.
    assert stmt["commission_total_cents"] == 100001
    # retail_pct_bps 5000: round_half_up(100001 x 0.5) = 50001.
    assert stmt["retail_share_cents"] == 50001


def test_central_share_is_residual_not_independently_rounded(api):
    """PRD section 3.8: "Rounding order is pinned and non-negotiable: first
    the total commission is computed — the fee multiplied by the tier rate,
    rounded half-up to whole cents — then the retail share is the total
    multiplied by the agreement's `retail_pct_bps` and divided by ten
    thousand, rounded half-up to whole cents; the central share is never
    rounded independently but is simply the total minus the retail share, so
    the two shares always reconcile to the cent."

    Design: Difficulty/combinatorial_formula/commission_split_rounding_residual
    """
    ctx = setup_underway_agreement(
        start_date="2026-10-01", end_date="2026-10-11",
        charter_start="2026-10-01",
        offer_overrides={"quoted_charter_fee_cents": 666673},
        yacht_preset={"pricing_mode": "WEEKLY_PLUS_DAILY",
                      "security_deposit_cents": 400000})
    pending = add_expense(ctx.agreement["id"], ctx.operator["id"],
                          bucket="APA", description="late fuel",
                          amount_cents=7777)

    set_clock("2026-10-11T00:00:00Z")
    validate_success(api.complete(ctx.agreement["id"], ctx.op_headers), 200)

    stmt = _commission_statements(api, ctx.agreement["id"], ctx.cl_headers)[0]
    # Residual: 100001 - 50001 = 50000 (NOT an independently rounded 50001).
    assert stmt["central_share_cents"] == 50000
    assert (stmt["retail_share_cents"] + stmt["central_share_cents"]
            == stmt["commission_total_cents"]), (
        "the two shares always reconcile to the cent")

    expenses, _ = validate_paginated(
        api.list_expenses(ctx.agreement["id"], ctx.op_headers))
    assert expenses[0]["status"] == "REJECTED", (
        "the PENDING expense is auto-rejected at settlement")

    movements = list_movements(ctx.escrow["id"])
    totals = summarize_movements(movements)
    assert totals[("RELEASE_TO_OPERATOR", "CHARTER_FEE")] == 566672
    assert totals[("REFUND_TO_CLIENT", "APA")] == 200002, (
        "no APA expense was approved, so the entire held APA returns")
    assert totals[("REFUND_TO_CLIENT", "DEPOSIT")] == 400000


def test_cancellation_exactly_60_days_lands_30pct_tier(api):
    """PRD section 3.9: "The penalty tier keys off that notice: ninety days or
    more before start costs ten percent of the charter fee; sixty to
    eighty-nine days costs thirty percent — so a cancellation exactly sixty
    days out lands in the thirty-percent tier while fifty-nine days lands in
    the fifty-percent tier; thirty to fifty-nine days costs fifty percent; and
    twenty-nine days or fewer costs the full fee."
    PRD section 3.9: "Cancellation from `PENDING_SIGNATURES` runs the
    identical cascade with one natural emptiness: nothing has been funded yet,
    every held bucket is zero, so the retained amount is zero, no refund or
    release movements post, and no commission statement is written — yet the
    penalty fields are still computed and recorded, the escrow still closes,
    and the downstream hops still fire."

    Design: Difficulty/boundary_precision_check/cancellation_day_boundary_60_vs_59
    """
    ctx = setup_accepted_agreement(start_date="2026-10-30", end_date="2026-11-19")
    set_clock("2026-08-31T00:00:00Z")  # exactly 60 whole days before start
    cancelled = validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers),
                                 200)
    assert cancelled["days_before_start"] == 60
    assert cancelled["cancellation_penalty_cents"] == 600000, (
        "0.30 x 2000000: the sixty-day boundary is inclusive from above")

    # From PENDING_SIGNATURES nothing was funded: no statement is written.
    statements = _commission_statements(api, ctx.agreement["id"], ctx.cl_headers)
    assert statements == [], "retained is zero, so no commission statement"
    escrow = get_agreement_escrow(ctx.agreement["id"])
    assert_escrow_closed_invariants(escrow)


def test_cancellation_59_days_drops_to_50pct_tier(api):
    """PRD section 3.9: "The penalty tier keys off that notice: ninety days or
    more before start costs ten percent of the charter fee; sixty to
    eighty-nine days costs thirty percent — so a cancellation exactly sixty
    days out lands in the thirty-percent tier while fifty-nine days lands in
    the fifty-percent tier; thirty to fifty-nine days costs fifty percent; and
    twenty-nine days or fewer costs the full fee."

    Design: Difficulty/boundary_precision_check/cancellation_day_boundary_60_vs_59
    """
    ctx = setup_accepted_agreement(start_date="2026-10-30", end_date="2026-11-19")
    set_clock("2026-09-01T00:00:00Z")  # exactly 59 whole days before start
    cancelled = validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers),
                                 200)
    assert cancelled["days_before_start"] == 59
    assert cancelled["cancellation_penalty_cents"] == 1000000, (
        "0.50 x 2000000: one calendar day earlier flips the tier")


def test_escrow_funded_equals_released_after_cancel(api):
    """PRD section 3.5: "The escrow's own `status` — `OPEN`, `SETTLING`,
    `CLOSED` — is driven only by the settlement and cancellation cascades,
    never directly; closure carries a hard invariant, `total_funded_cents`
    equal to `total_released_cents` with every held bucket at zero."

    Design: Difficulty/compensating_invariant/escrow_cash_conservation_under_cancel
    """
    # Only the SIGNING tranche is funded: 1000000 fee + 500000 deposit.
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    escrow = fund_tranche(ctx.agreement["id"], "SIGNING", 1500000,
                          ctx.client["id"])
    assert escrow["total_funded_cents"] == 1500000

    set_clock("2026-08-31T00:00:00Z")  # 60 days -> penalty 600000
    validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers), 200)

    closed = get_agreement_escrow(ctx.agreement["id"])
    assert closed["status"] == "CLOSED"
    assert closed["total_funded_cents"] == 1500000
    assert closed["total_released_cents"] == 1500000, (
        "fund + cancel-refund conserves client cash")


def test_escrow_buckets_zeroed_and_movements_balance(api):
    """PRD section 3.9: "When every movement has posted, a
    `CommissionStatement` with `basis` `CANCELLATION_PENALTY` is written if
    and only if the retained amount is greater than zero, its
    `basis_amount_cents` equal to the retained penalty; the escrow closes —
    every held bucket at zero, funded equal to released — and the funds axis
    settles into `REFUNDED`."

    Design: Difficulty/compensating_invariant/escrow_cash_conservation_under_cancel
    """
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    escrow = fund_tranche(ctx.agreement["id"], "SIGNING", 1500000,
                          ctx.client["id"])

    set_clock("2026-08-31T00:00:00Z")  # 60 days; retained min(600000, 1000000)
    validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers), 200)

    closed = get_agreement_escrow(ctx.agreement["id"])
    for bucket_field in ("held_charter_fee_cents", "held_apa_cents",
                         "held_deposit_cents", "held_gratuity_cents"):
        assert closed[bucket_field] == 0

    movements = list_movements(escrow["id"])
    totals = summarize_movements(movements)
    refunds = sum(v for (t, _), v in totals.items() if t == "REFUND_TO_CLIENT")
    releases = sum(v for (t, _), v in totals.items() if t.startswith("RELEASE_"))
    # Refunds: fee 1000000 - 600000 retained = 400000, deposit 500000.
    assert refunds == 900000
    # Releases: operator 480000 + retail 60000 + central 60000.
    assert releases == 600000
    assert refunds + releases == 1500000


def test_cancel_in_prep_deducts_approved_damage_claims(api):
    """PRD section 3.9: "For a cancellation from `IN_PREP`, approved damage
    claims are settled out of the deposit first — the operator receiving the
    approved total capped at the held deposit — before the client's deposit
    refund is computed, exactly as at completion."
    PRD section 3.9: "The cascade then unwinds the money. The funds axis —
    from whichever of `UNFUNDED`, `DEPOSIT_HELD`, or `FULLY_FUNDED` it sits in
    — moves to `REFUNDING`, and the escrow moves from `OPEN` to `SETTLING` as
    its movements post: the client is refunded the held charter fee minus the
    retained amount, the entire held APA, the entire held gratuity, and the
    held deposit less any approved damage claims; when anything is retained, a
    penalty commission of twenty percent of the retained amount, rounded
    half-up, is carved off — the operator's release from the `CHARTER_FEE`
    bucket is the retained amount minus that commission, while the retail
    broker receives the retail share of the penalty commission (the commission
    multiplied by `retail_pct_bps` over ten thousand, rounded half-up) and the
    central agent receives the residual central share, the same pinned
    rounding order as section 3.8 with `basis` `CANCELLATION_PENALTY`."

    Design: Corner/calculations/cancel_in_prep_deducts_approved_damage_claims
    """
    # 10-day Yacht A: fee 1000000, apa 300000, deposit 500000; funded 1800000.
    ctx = setup_in_prep_agreement(start_date="2026-11-02", end_date="2026-11-12")
    claim = add_expense(ctx.agreement["id"], ctx.operator["id"],
                        bucket="DAMAGE_CLAIM", description="scratch on hull",
                        amount_cents=200000)
    review_expense(claim["id"], "APPROVED", ctx.client["id"])

    # Default clock 2026-08-01 -> 93 days before start -> ten-percent tier.
    cancelled = validate_success(
        api.cancel(ctx.agreement["id"], {"reason": "itinerary change"},
                   ctx.ca_headers),
        200)
    assert cancelled["cancellation_penalty_cents"] == 100000

    movements = list_movements(ctx.escrow["id"])
    totals = summarize_movements(movements)
    assert totals[("REFUND_TO_CLIENT", "CHARTER_FEE")] == 900000
    assert totals[("REFUND_TO_CLIENT", "APA")] == 300000
    # Approved damage claim 200000 comes out of the deposit first.
    assert totals[("RELEASE_TO_OPERATOR", "DEPOSIT")] == 200000
    assert totals[("REFUND_TO_CLIENT", "DEPOSIT")] == 300000
    # Penalty commission 20% of 100000 = 20000; operator release 80000.
    assert totals[("RELEASE_TO_OPERATOR", "CHARTER_FEE")] == 80000
    assert totals[("RELEASE_TO_RETAIL_BROKER", "CHARTER_FEE")] == 10000
    assert totals[("RELEASE_TO_CENTRAL_AGENT", "CHARTER_FEE")] == 10000

    closed = get_agreement_escrow(ctx.agreement["id"])
    assert_escrow_closed_invariants(closed)
    assert closed["total_funded_cents"] == 1800000
    assert closed["total_released_cents"] == 1800000


def test_cancel_releases_charter_block(api):
    """PRD section 3.9: "Escrow closure releases the agreement's `CHARTER`
    block from `ACTIVE` to `RELEASED` — the only way such a block is ever
    released — incrementing the yacht's `version` by one, and that release in
    turn transitions the source charter request from `ACCEPTED` to
    `CANCELLED`, incrementing its `version` as well."

    Design: Difficulty/compensating_invariant/calendar_block_day_conservation_under_rebook
    """
    ctx = setup_accepted_agreement(start_date="2026-10-30", end_date="2026-11-19")

    active_before, _ = validate_paginated(
        api.list_yacht_availability_blocks(ctx.yacht["id"], ctx.op_headers,
                                           params={"status": "ACTIVE"}))
    assert len(active_before) == 1
    assert active_before[0]["block_type"] == "CHARTER"
    assert active_before[0]["start_date"] == "2026-10-30"
    assert active_before[0]["end_date"] == "2026-11-19"  # 20 block-days

    validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers), 200)

    active_after, meta = validate_paginated(
        api.list_yacht_availability_blocks(ctx.yacht["id"], ctx.op_headers,
                                           params={"status": "ACTIVE"}))
    assert meta["total_count"] == 0 and active_after == [], (
        "the cancellation cascade released the CHARTER block")

    request = validate_success(
        api.get_charter_request(ctx.request["id"], ctx.cl_headers), 200)
    assert request["status"] == "CANCELLED"


def test_rebook_accept_recreates_identical_charter_block(api):
    """PRD section 3.3: "Three states end a request: `DECLINED`, `EXPIRED`,
    and `CANCELLED`. From any of them the client side may rebook — a fresh
    request in `DRAFT` for the same client, built from a payload of
    `yacht_id`, `start_date`, `end_date`, `guests_count`, and optionally
    `retail_broker_id`, with the new request's `rebooked_from_request_id`
    pointing back at the terminal request it descends from (null on any
    request not born of a rebook)."
    PRD section 3.4: "The third hop creates the charter's `AvailabilityBlock`
    — `block_type` `CHARTER`, status `ACTIVE`, covering the charter's
    half-open window, linked back to the new agreement through its
    `charter_agreement_id` — and increments the yacht's `version` by one."

    Design: Difficulty/compensating_invariant/calendar_block_day_conservation_under_rebook
    """
    ctx = setup_accepted_agreement(start_date="2026-10-30", end_date="2026-11-19")
    validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers), 200)

    rebooked = validate_success(
        api.rebook_charter_request(
            ctx.request["id"],
            create_rebook_payload(ctx.yacht["id"],
                                  start_date="2026-10-30",
                                  end_date="2026-11-19"),
            ctx.cl_headers),
        201)
    assert rebooked["rebooked_from_request_id"] == ctx.request["id"]
    assert rebooked["status"] == "DRAFT"

    submitted = submit_request(rebooked["id"], ctx.client["id"])
    offered = make_offer(rebooked["id"], ctx.central_agent["id"])
    agreement = accept_request(rebooked["id"], ctx.client["id"],
                               offered["version"])

    active, _ = validate_paginated(
        api.list_yacht_availability_blocks(ctx.yacht["id"], ctx.op_headers,
                                           params={"status": "ACTIVE"}))
    assert len(active) == 1, (
        "cancel + rebook compensate exactly: exactly one ACTIVE CHARTER block "
        "before and after")
    assert active[0]["block_type"] == "CHARTER"
    assert active[0]["start_date"] == "2026-10-30"
    assert active[0]["end_date"] == "2026-11-19", (
        "identical 20-day coverage is recreated by the rebooked acceptance")
    assert active[0]["charter_agreement_id"] == agreement["id"]


def test_reverse_fk_lists_and_empty_commission(api):
    """PRD section 3.3: "The request collection supports optional `client_id`,
    `yacht_id`, `retail_broker_id`, `rebooked_from_request_id`, and `status`
    filters, covering every reverse lookup a deal party needs."
    PRD section 3.4: "Agreements are readable individually — both state axes,
    the computed funding schedule, and the penalty fields included — and the
    collection supports optional filters on `charter_request_id`,
    `client_id`, `yacht_id`, `operator_id`, `retail_broker_id`,
    `central_agent_id`, `status`, and `funds_status`."
    PRD section 3.5: "The account is readable through its agreement (an array
    of length zero or one, since the escrow exists only from acceptance
    onward) or directly by `id`, and its movements are listed in posted,
    chronological order with optional `movement_type` and `bucket` filters."
    PRD section 3.8: "An agreement's commission statements — zero or one of
    them, created here or by the cancellation of section 3.9 — are listable
    under the agreement."

    Design: Corner/endpoints/reverse_fk_lists_and_empty_commission
    """
    from test_helpers import decline_request, setup_offered_request

    ctx = setup_offered_request(start_date="2026-10-01", end_date="2026-10-11")
    decline_request(ctx.request["id"], ctx.client["id"])  # terminal DECLINED

    rebooked = validate_success(
        api.rebook_charter_request(
            ctx.request["id"], create_rebook_payload(ctx.yacht["id"]),
            ctx.cl_headers),
        201)
    submitted = submit_request(rebooked["id"], ctx.client["id"])
    offered = make_offer(rebooked["id"], ctx.central_agent["id"])
    agreement = accept_request(rebooked["id"], ctx.client["id"],
                               offered["version"])

    children, meta = validate_paginated(
        api.list_charter_requests(
            ctx.cl_headers,
            params={"rebooked_from_request_id": ctx.request["id"]}))
    assert meta["total_count"] == 1 and children[0]["id"] == rebooked["id"]

    agreements, meta = validate_paginated(
        api.list_charter_agreements(ctx.cl_headers,
                                    params={"charter_request_id": rebooked["id"]}))
    assert meta["total_count"] == 1 and agreements[0]["id"] == agreement["id"]

    escrow, meta = validate_paginated(
        api.get_agreement_escrow(agreement["id"], ctx.cl_headers))
    assert len(escrow) == 1, "the escrow sub-resource is an array of length 0-1"
    assert escrow[0]["status"] == "OPEN"
    assert escrow[0]["total_funded_cents"] == 0

    statements, meta = validate_paginated(
        api.list_commission_statements(agreement["id"], ctx.cl_headers))
    assert meta["total_count"] == 0 and statements == [], (
        "no settlement has run, so no commission statement exists")
