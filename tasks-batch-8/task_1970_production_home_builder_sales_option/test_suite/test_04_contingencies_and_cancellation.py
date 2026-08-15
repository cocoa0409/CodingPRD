"""Contingency clearance (OCC + bubble-up), the deadline sweep, and the
cancellation cascade with its earnest-money refund branches (PRD §2.9, §3.4,
§3.8)."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_RE_RELEASE_PRICE_CENTS,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_refund_invariant,
    cancel_agreement,
    clear_contingency,
    create_incentive,
    get_community,
    get_incentive,
    get_lot,
    make_buyer_headers,
    setup_cleared_agreement,
    setup_signed_agreement,
    sign_agreement,
    validate_error,
    validate_success,
)

AGENT = TEST_USERS["sales_agent_headers"]


def test_occ_stale_agreement_version_on_clearance():
    """PRD §2.9: "Each clearance itself mutates the agreement and may promote it
    to `CONTINGENCIES_CLEARED`, so a clearance submitted against a version the
    agreement has already advanced beyond is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), forcing the client to re-read the
    current contingency state."

    Design: Corner/complexity_layers/occ_stale_agreement_version_on_clearance
    """
    from test_helpers import setup_draft_agreement

    bundle = setup_draft_agreement()
    agreement = bundle["agreement"]
    v_create = agreement["version"]
    signed = sign_agreement(agreement["id"], bundle["buyer"]["id"])
    assert signed["version"] > v_create, "signing advanced the version"

    stale = api_client.clear_contingency(
        agreement["id"],
        {"contingency_type": "financing", "action": "CLEARED",
         "expected_agreement_version": v_create},
        AGENT,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION, 412)

    current = validate_success(api_client.get_agreement(agreement["id"], AGENT), 200)
    assert current["financing_contingency_status"] == "PENDING", (
        "the stale clearance changed nothing"
    )

    cleared = clear_contingency(agreement["id"], signed["version"], "financing")
    assert cleared["financing_contingency_status"] == "CLEARED"


def test_contingency_double_clear_rejected():
    """PRD §3.4: "Only a tracker still in `PENDING` may be cleared or waived;
    acting on one that has already resolved is rejected with
    `ERR_CONTINGENCY_NOT_PENDING`."

    Design: Corner/state_machines/contingency_double_clear_rejected
    """
    bundle = setup_signed_agreement()
    agreement = bundle["agreement"]

    cleared = clear_contingency(agreement["id"], agreement["version"], "financing")
    assert cleared["financing_contingency_status"] == "CLEARED"

    resp = api_client.clear_contingency(
        agreement["id"],
        {"contingency_type": "financing", "action": "CLEARED",
         "expected_agreement_version": cleared["version"]},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_CONTINGENCY_NOT_PENDING)

    after = validate_success(api_client.get_agreement(agreement["id"], AGENT), 200)
    assert after["financing_contingency_status"] == "CLEARED"


def test_contingency_deadline_sweep_auto_cancels_full_refund():
    """PRD §3.4: "The agreement's `contingency_deadline` is supplied at drafting
    time; whenever the logical clock is set strictly later than that deadline
    while any of the three trackers is still `PENDING`, the sweep cancels the
    agreement outright."
    PRD §3.4: "The cancellation carries `cancel_reason` `CONTINGENCY_EXPIRED`
    and always refunds the earnest money in full: `refund_amount_cents` equals
    `earnest_money_deposited_cents` and `forfeited_amount_cents` is 0."
    PRD §3.4: "The full cascade — selections cancelled, incentives revoked, the
    lot re-released and repriced — is the same one described in §3.8."

    Design: Corner/state_machines/contingency_deadline_sweep_auto_cancels_full_refund
    """
    bundle = setup_signed_agreement(
        agreement_overrides={"has_sale_of_home_contingency": True}
    )
    agreement = bundle["agreement"]
    for tracker in ("financing_contingency_status",
                    "appraisal_contingency_status",
                    "sale_of_home_contingency_status"):
        assert agreement[tracker] == "PENDING", tracker
    incentive = create_incentive(agreement["id"], 200_000)
    assert incentive["status"] == "APPROVED"
    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 800_000

    advance_clock("2026-08-22T00:00:00Z")  # strictly past the 2026-08-21 deadline

    after = validate_success(api_client.get_agreement(agreement["id"], AGENT), 200)
    assert after["status"] == "CANCELLED"
    assert after["cancel_reason"] == "CONTINGENCY_EXPIRED"
    assert after["refund_amount_cents"] == 500_000
    assert after["forfeited_amount_cents"] == 0
    assert_refund_invariant(after)

    lot = get_lot(bundle["lot"]["id"])
    assert lot["status"] == "RELEASED"
    assert lot["release_count"] == 1
    assert lot["release_price_cents"] == CANONICAL_RE_RELEASE_PRICE_CENTS

    revoked = get_incentive(incentive["id"])
    assert revoked["status"] == "REVOKED"
    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 1_000_000


def test_earnest_forfeit_math_after_contingencies_cleared():
    """PRD §3.8: "The single forfeiture branch is `CONTINGENCIES_CLEARED` with
    `BUYER_DEFAULT`: the forfeited share is 25 percent of the deposited earnest
    money, rounded half up to whole cents, and the remainder is refunded."
    PRD §3.8: "The trust invariant always holds: `refund_amount_cents` plus
    `forfeited_amount_cents` equals `earnest_money_deposited_cents`."

    Design: Corner/calculations/earnest_forfeit_math_after_contingencies_cleared
    """
    bundle = setup_cleared_agreement()
    assert bundle["agreement"]["status"] == "CONTINGENCIES_CLEARED"

    cancelled = cancel_agreement(
        bundle["agreement"]["id"], "BUYER_DEFAULT",
        make_buyer_headers(bundle["buyer"]["id"]),
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "BUYER_DEFAULT"
    # round_half_up(500,000 * 0.25) = 125,000 forfeited; 375,000 refunded
    assert cancelled["forfeited_amount_cents"] == 125_000
    assert cancelled["refund_amount_cents"] == 375_000
    assert_refund_invariant(cancelled)

    lot = get_lot(bundle["lot"]["id"])
    assert lot["status"] == "RELEASED"
    assert lot["release_count"] == 1
    assert lot["release_price_cents"] == CANONICAL_RE_RELEASE_PRICE_CENTS


def test_earnest_full_refund_during_contingency_period():
    """PRD §3.8: "A cancellation from `PENDING_CONTINGENCIES` also refunds in
    full regardless of reason."

    Design: Corner/calculations/earnest_full_refund_during_contingency_period
    """
    bundle = setup_signed_agreement()
    assert bundle["agreement"]["status"] == "PENDING_CONTINGENCIES"

    cancelled = cancel_agreement(
        bundle["agreement"]["id"], "BUYER_DEFAULT",
        make_buyer_headers(bundle["buyer"]["id"]),
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "BUYER_DEFAULT"
    assert cancelled["refund_amount_cents"] == 500_000
    assert cancelled["forfeited_amount_cents"] == 0
    assert_refund_invariant(cancelled)

    lot = get_lot(bundle["lot"]["id"])
    assert lot["status"] == "RELEASED"
    assert lot["release_count"] == 1
    assert lot["release_price_cents"] == CANONICAL_RE_RELEASE_PRICE_CENTS


def test_cancel_signed_agreement_releases_and_reprices_lot():
    """PRD §3.8: "And if the agreement had been signed, its lot returns from
    `SOLD` to `RELEASED`: the reservation fields are cleared, `release_count`
    increments by 1, and the lot is repriced upward — the new
    `release_price_cents` is the previous release price inflated by 2 percent,
    rounded half up to whole cents, with no re-evaluation of the phase window
    or the lot-type premium."
    PRD §3.8: "A cancellation from `CONTINGENCIES_CLEARED` with reason
    `BUILDER_DEFAULT` refunds in full as well."

    Design: Difficulty/transitive_cascade/agreement_cancel_lot_release_reprice_cascade
    """
    bundle = setup_signed_agreement()
    lot_before = get_lot(bundle["lot"]["id"])
    assert lot_before["status"] == "SOLD"
    assert lot_before["release_count"] == 0

    cancelled = cancel_agreement(
        bundle["agreement"]["id"], "BUILDER_DEFAULT", AGENT
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "BUILDER_DEFAULT"
    assert cancelled["refund_amount_cents"] == 500_000
    assert cancelled["forfeited_amount_cents"] == 0

    lot = get_lot(bundle["lot"]["id"])
    assert lot["status"] == "RELEASED", "cascade hop: lot returned to inventory"
    assert lot["reserved_buyer_id"] is None
    assert lot["hold_expires_at"] is None
    assert lot["release_count"] == 1
    # round_half_up(9,991,000 * 1.02) = 10,190,820
    assert lot["release_price_cents"] == CANONICAL_RE_RELEASE_PRICE_CENTS


def test_rerelease_pricing_compounds_on_each_post_contract_fallout():
    """PRD §3.8: "And if the agreement had been signed, its lot returns from
    `SOLD` to `RELEASED`: the reservation fields are cleared, `release_count`
    increments by 1, and the lot is repriced upward — the new
    `release_price_cents` is the previous release price inflated by 2 percent,
    rounded half up to whole cents, with no re-evaluation of the phase window
    or the lot-type premium."

    Design: Difficulty/transitive_cascade/agreement_cancel_lot_release_reprice_cascade
    """
    from test_helpers import (
        create_agreement_payload,
        setup_reserved_scenario,
    )

    bundle = setup_reserved_scenario()
    buyer = bundle["buyer"]
    lot_id = bundle["lot"]["id"]
    plan_id = bundle["plan"]["id"]

    # First fallout: RELEASED(9,991,000) -> SOLD -> RELEASED(10,190,820), count 1.
    payload = create_agreement_payload(
        buyer_id=buyer["id"], lot_id=lot_id, plan_id=plan_id,
        expected_lot_version=bundle["lot_version"],
    )
    agreement1 = validate_success(api_client.create_agreement(payload, AGENT), 201)
    sign_agreement(agreement1["id"], buyer["id"])
    cancel_agreement(agreement1["id"], "BUILDER_DEFAULT", AGENT)

    lot = get_lot(lot_id)
    assert lot["release_count"] == 1
    assert lot["release_price_cents"] == 10_190_820

    # Second fallout reprices from the *previous release price*, compounding.
    reserved = validate_success(
        api_client.reserve_lot(
            lot_id, {"buyer_id": buyer["id"]}, make_buyer_headers(buyer["id"])
        ),
        200,
    )
    payload2 = create_agreement_payload(
        buyer_id=buyer["id"], lot_id=lot_id, plan_id=plan_id,
        expected_lot_version=reserved["version"],
    )
    agreement2 = validate_success(api_client.create_agreement(payload2, AGENT), 201)
    sign_agreement(agreement2["id"], buyer["id"])
    cancel_agreement(agreement2["id"], "BUILDER_DEFAULT", AGENT)

    lot = get_lot(lot_id)
    assert lot["status"] == "RELEASED"
    assert lot["release_count"] == 2
    # round_half_up(10,190,820 * 1.02) = round_half_up(10,394,636.4) = 10,394,636
    assert lot["release_price_cents"] == 10_394_636
