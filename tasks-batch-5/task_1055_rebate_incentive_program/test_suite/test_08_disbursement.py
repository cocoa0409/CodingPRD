"""Disbursement: scheduling a payout, its amounts, release, void and reissue."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    read_claim,
    read_claimant,
    read_payout,
    read_program,
    setup_approved_claim,
    setup_pending_payout,
    setup_released_payout,
    substantiate_claimant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
CONSUMER_GOODS = [{"sku": "APPLIANCE-X", "quantity": 4, "unit_price_cents": 5000}]


# --------------------------------------------------------------------------- #
# Method is chosen from the gross, then the fee is subtracted
# --------------------------------------------------------------------------- #

def _consumer_payout_without_explicit_method():
    return setup_pending_payout(
        method=None,
        channel="CONSUMER",
        claimant_type="CONSUMER",
        program_overrides={"name": "Consumer Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Consumer Offer"},
        claimant_overrides={"legal_name": "Dana Consumer", "email": "dana@home.example"},
        serial_number="SN-CON-1",
        lines=CONSUMER_GOODS,
    )


def test_payout_method_is_selected_from_the_gross_amount(api):
    """PRD §3.8: "Second, the `method` is selected *from the gross*, never from the
    net: if the request supplied a `method`, that value is used as given;
    otherwise, if the claimant's `type` is `CONSUMER` and `gross_cents` is 2500
    cents or more, the method is `VIRTUAL_CARD`; otherwise the method is `CHECK`."

    Design: Difficulty/combinatorial_formula/payout_method_selected_from_gross_then_fee_applied
    """
    ctx = _consumer_payout_without_explicit_method()
    assert ctx["claim"]["final_rebate_cents"] == 2500
    assert ctx["payout"]["method"] == "VIRTUAL_CARD"
    assert ctx["payout"]["gross_cents"] == 2500


def test_card_fee_drops_net_below_the_threshold_without_reselecting_the_method(api):
    """PRD §3.8: "Third, `fee_cents` follows the method — 150 cents for a `CHECK`,
    50 cents for a `VIRTUAL_CARD`. Fourth, `net_cents` is `gross_cents` less
    `fee_cents`; the method is deliberately *not* re-selected even when subtracting
    the fee drops the net back below the 2500-cent card threshold."
    PRD §3.8: "A successful scheduling creates the payout in `PENDING` with
    `check_number`, `released_at`, `released_by_user_id` and `void_reason` all null
    and `reissue_count` at zero, moves the claim's payment state
    `NONE → SCHEDULED`, and increments the claim's `version` by one."

    Design: Difficulty/combinatorial_formula/payout_method_selected_from_gross_then_fee_applied
    """
    ctx = _consumer_payout_without_explicit_method()
    payout = ctx["payout"]
    assert payout["method"] == "VIRTUAL_CARD"
    assert payout["fee_cents"] == 50
    assert payout["net_cents"] == 2450
    assert payout["status"] == "PENDING"
    assert payout["reissue_count"] == 0
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "SCHEDULED"


def test_payout_whose_net_falls_below_the_floor_is_refused(api):
    """PRD §3.8: "Fifth, if `net_cents` is below 100 cents the payout is refused
    with `ERR_BELOW_MIN_PAYOUT` (HTTP 422); the same floor is checked again at
    release."

    Design: Corner/validations/payout_below_minimum_net_is_rejected
    """
    ctx = setup_approved_claim(
        program_overrides={"name": "Small Payout Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Small Payout Offer"},
        claimant_overrides={"legal_name": "Small Dealer", "email": "sm@sm.example"},
        serial_number="SN-SM-1",
        lines=[{"sku": "TOOLS-A", "quantity": 1, "unit_price_cents": 2000}],
    )
    assert ctx["claim"]["final_rebate_cents"] == 100

    resp = api.create_payout(
        ctx["claim"]["id"],
        {"expected_claim_version": ctx["claim_version"], "method": "CHECK"},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_BELOW_MIN_PAYOUT.value)

    assert read_claim(ctx["claim"]["id"])["payment_status"] == "NONE"
    _, meta = validate_paginated(
        api.list_payouts(ADMIN, params={"claim_id": ctx["claim"]["id"]})
    )
    assert meta["total_count"] == 0


def test_second_live_payout_on_one_claim_is_refused(api):
    """PRD §3.8: "A claim that already has a payout in `PENDING`, `RELEASED` or
    `REISSUE_PENDING` cannot be given a second one, and the attempt is refused with
    `ERR_PAYOUT_ALREADY_EXISTS` (HTTP 409) — but a claim whose payout has been
    voided may be given a fresh one, which is precisely why the version guard
    exists."

    Design: Corner/endpoints/second_payout_while_one_is_live_is_rejected
    """
    ctx = setup_pending_payout(
        method="CHECK",
        program_overrides={"name": "Dup Payout Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Dup Payout Offer"},
        claimant_overrides={"legal_name": "Dup Dealer", "email": "dp@dp.example"},
    )
    current_version = read_claim(ctx["claim"]["id"])["version"]

    resp = api.create_payout(
        ctx["claim"]["id"],
        {"expected_claim_version": current_version, "method": "CHECK"},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_PAYOUT_ALREADY_EXISTS.value)

    _, meta = validate_paginated(
        api.list_payouts(ADMIN, params={"claim_id": ctx["claim"]["id"]})
    )
    assert meta["total_count"] == 1
    assert read_payout(ctx["payout"]["id"])["status"] == "PENDING"


def test_stale_expected_claim_version_blocks_a_replacement_payout(api):
    """PRD §2.7: "Scheduling a disbursement for an approved claim requires the
    request to carry `expected_claim_version`, a non-optional field holding the
    client's last observed `version` of the target claim. If that value does not
    equal the claim's current `version`, the request is rejected with
    `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_claim_version_on_payout_create_returns_412
    """
    ctx = setup_pending_payout(
        method="CHECK",
        program_overrides={"name": "OCC Claim Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "OCC Claim Offer"},
        claimant_overrides={"legal_name": "OCC Dealer", "email": "oc@oc.example"},
    )
    validate_success(
        api.void_payout(ctx["payout"]["id"], {"void_reason": "WRONG_PAYEE"}, FINANCE)
    )

    resp = api.create_payout(
        ctx["claim"]["id"],
        {"expected_claim_version": ctx["claim_version"], "method": "CHECK"},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION.value)

    _, meta = validate_paginated(
        api.list_payouts(ADMIN, params={"claim_id": ctx["claim"]["id"]})
    )
    assert meta["total_count"] == 1
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "NONE"


def test_releasing_a_voided_payout_is_refused(api):
    """PRD §3.8: "A release attempted from a payout state that does not declare it
    reports `ERR_PAYOUT_NOT_RELEASABLE` (HTTP 409)."
    PRD §3.8: "In neither case is a `RELEASE` row appended: voiding a payout does
    not release the underlying commitment, because the claim is still owed its
    rebate."

    Design: Corner/endpoints/releasing_a_voided_payout_is_rejected
    """
    ctx = setup_pending_payout(
        method="CHECK",
        program_overrides={"name": "Void Release Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Void Release Offer"},
        claimant_overrides={"legal_name": "Void Dealer", "email": "vd@vd.example"},
    )
    validate_success(
        api.void_payout(ctx["payout"]["id"], {"void_reason": "WRONG_ADDRESS"}, FINANCE)
    )

    resp = api.release_payout(ctx["payout"]["id"], FINANCE, {"check_number": "CHK-4444"})
    validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_RELEASABLE.value)

    assert read_payout(ctx["payout"]["id"])["status"] == "VOIDED"
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "NONE"
    assert read_program(ctx["program"]["id"])["committed_cents"] == 1600


# --------------------------------------------------------------------------- #
# The two state dimensions of a claim advance independently
# --------------------------------------------------------------------------- #

def test_payment_status_cycles_while_adjudication_stays_approved(api):
    """PRD §3.8: "On release the payout moves to `RELEASED`, `released_at` is
    stamped from the logical clock and `released_by_user_id` from the acting
    `X-User-ID`; the claim's payment state moves `SCHEDULED → PAID`; and a ledger
    row of type `PAYMENT` with `amount_cents` equal to the payout's `net_cents` is
    appended, raising the program's `paid_cents`."
    PRD §3.8: "Voiding one that was already released moves the claim's payment
    state `PAID → NONE`, which — because `paid_cents` is derived from the ledger by
    looking at each payment entry's claim — lowers the program's `paid_cents` by
    that payout's `net_cents` without any new ledger row being written."

    Design: Difficulty/non_linear_state_machine/claim_adjudication_and_payment_dimensions_evolve_independently
    """
    ctx = setup_released_payout(
        method="CHECK",
        program_overrides={"name": "Parallel Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Parallel Offer"},
        claimant_overrides={"legal_name": "Parallel Dealer", "email": "p@par.example"},
    )
    assert ctx["claim"]["payment_status"] == "PAID"
    assert ctx["claim"]["adjudication_status"] == "APPROVED"

    validate_success(
        api.void_payout(ctx["payout"]["id"], {"void_reason": "ADDRESS_RETURNED"}, FINANCE)
    )
    claim = read_claim(ctx["claim"]["id"])
    assert claim["payment_status"] == "NONE"
    assert claim["adjudication_status"] == "APPROVED"


def test_voiding_a_released_check_lowers_paid_cents_but_not_committed_cents(api):
    """PRD §3.8: "In neither case is a `RELEASE` row appended: voiding a payout does
    not release the underlying commitment, because the claim is still owed its
    rebate."
    PRD §3.1: "`paid_cents` is the sum of the amounts of `PAYMENT` entries whose
    associated claim currently has a payment state of `PAID` or `ESCHEATED` — which
    is why voiding a released payout lowers `paid_cents` without any compensating
    ledger row being written."

    Design: Difficulty/non_linear_state_machine/claim_adjudication_and_payment_dimensions_evolve_independently
    """
    ctx = setup_released_payout(
        method="CHECK",
        program_overrides={"name": "Parallel Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Parallel Offer"},
        claimant_overrides={"legal_name": "Parallel Dealer", "email": "p@par.example"},
    )
    assert ctx["claim"]["final_rebate_cents"] == 1600
    assert ctx["payout"]["net_cents"] == 1450
    assert read_program(ctx["program"]["id"])["paid_cents"] == 1450

    voided = validate_success(
        api.void_payout(ctx["payout"]["id"], {"void_reason": "ADDRESS_RETURNED"}, FINANCE)
    )
    assert voided["status"] == "VOIDED"

    program = read_program(ctx["program"]["id"])
    assert program["committed_cents"] == 1600
    assert program["paid_cents"] == 0


# --------------------------------------------------------------------------- #
# A releasable payout still depends on its claimant's standing
# --------------------------------------------------------------------------- #

def _reissue_pending_payout_for_blocked_claimant():
    ctx = setup_released_payout(
        method="CHECK",
        check_number="CHK-7001",
        program_overrides={"name": "Blocked Release Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Blocked Release Offer"},
        claimant_overrides={"legal_name": "Blocked Dealer", "email": "bl@bl.example"},
    )
    ctx["payout"] = validate_success(api_client.reissue_payout(ctx["payout"]["id"], FINANCE))
    substantiate_claimant(ctx["claimant"]["id"], opened_reason="STAFF_REFERRAL")
    return ctx


def test_release_from_reissue_pending_is_blocked_by_a_blocked_claimant(api):
    """PRD §3.8: "Three further conditions apply: the claimant must be `ACTIVE`,
    else `ERR_CLAIMANT_BLOCKED`; the payout's `net_cents` must be at least 100
    cents, else `ERR_BELOW_MIN_PAYOUT`; and — the segregation-of-duties rule — the
    requesting `X-User-ID` must differ from the `approved_by_user_id` recorded on
    the claim when it was approved."
    PRD §3.8: "Reissue is the recovery path for a lost check or a botched card, and
    it is available from `RELEASED` and from `VOIDED`, moving the payout to
    `REISSUE_PENDING` and incrementing `reissue_count` by one."

    Design: Difficulty/cross_entity_state_dependency/payout_release_depends_on_claimant_blocked_state
    """
    ctx = _reissue_pending_payout_for_blocked_claimant()

    resp = api.release_payout(ctx["payout"]["id"], FINANCE, {"check_number": "CHK-7002"})
    validate_error(resp, ApiErrorId.ERR_CLAIMANT_BLOCKED.value)

    payout = read_payout(ctx["payout"]["id"])
    assert payout["status"] == "REISSUE_PENDING"
    assert payout["reissue_count"] == 1
    assert read_claimant(ctx["claimant"]["id"])["status"] == "BLOCKED"


def test_a_paid_claim_survives_substantiation_unrevoked(api):
    """PRD §3.7: "An approved claim whose money has already been paid out is *not*
    revoked — the revocation branch reaches only the unpaid ones."
    PRD §3.8: "Reissuing from `RELEASED` requires the claim's payment state to be
    `PAID` or `NONE`, clears `check_number`, and deliberately leaves the claim
    `PAID` — the claim does not fall back to unpaid merely because a replacement
    instrument is being cut; it stays `PAID` until the reissued payout is released
    again."

    Design: Difficulty/cross_entity_state_dependency/payout_release_depends_on_claimant_blocked_state
    """
    ctx = _reissue_pending_payout_for_blocked_claimant()

    claim = read_claim(ctx["claim"]["id"])
    assert claim["adjudication_status"] == "APPROVED"
    assert claim["payment_status"] == "PAID"
    assert read_payout(ctx["payout"]["id"])["status"] == "REISSUE_PENDING"
