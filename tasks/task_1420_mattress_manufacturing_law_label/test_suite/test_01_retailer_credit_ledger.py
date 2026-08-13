"""Retailer onboarding, credit ledger, and ledger-related concurrency (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_retailer,
    assert_credit_adjustment,
    create_retailer_payload,
    create_credit_adjustment_payload,
    create_retailer_account,
    list_ledger,
    setup_approved_claim,
    make_retailer_headers,
)

PM = TEST_USERS["plant_manager_headers"]


def test_retailer_created_with_zero_balance_and_flags(api):
    """PRD §3.1: "The account opens with `credit_balance_cents` at zero."

    Design: Corner/entities/retailer_creation_defaults_and_computed_balance
    """
    resp = api.create_retailer(
        create_retailer_payload(
            retailer_name="SleepCo",
            drop_ship_enabled=True,
            recycling_enrolled=False,
            credit_limit_cents=500000,
        ),
        PM,
    )
    retailer = validate_success(resp, expected_status=201)
    assert_retailer(retailer)
    assert retailer["credit_balance_cents"] == 0, (
        f"New retailer must open with balance 0, got {retailer['credit_balance_cents']}"
    )
    assert retailer["drop_ship_enabled"] is True
    assert retailer["recycling_enrolled"] is False
    assert retailer["credit_limit_cents"] == 500000


def test_credit_adjustment_ledger_entry_is_append_only(api):
    """PRD §2.4: "One entity deviates: `CreditAdjustment` is an append-only
    ledger entry and carries only `id` and `created_at`; both `updated_at` and
    `version` are absent from it, because ledger entries are never modified
    after posting."
    PRD §3.1: "Manual entries post with source `MANUAL` and a null `source_id`."

    Design: Corner/entities/credit_adjustment_immutable_ledger_entry
    """
    retailer = create_retailer_account()
    resp = api.create_credit_adjustment(
        retailer["id"],
        create_credit_adjustment_payload(
            amount_cents=5000,
            reason="promo",
            expected_retailer_version=retailer["version"],
        ),
        PM,
    )
    entry = validate_success(resp, expected_status=201)
    assert_credit_adjustment(entry)
    assert entry["source"] == "MANUAL"
    assert entry["source_id"] is None
    assert entry["amount_cents"] == 5000

    ledger = list_ledger(retailer["id"])
    assert len(ledger) == 1
    assert "version" not in ledger[0] and "updated_at" not in ledger[0]


def test_manual_credit_adjustment_rejected_on_stale_version(api):
    """PRD §2.7: "Posting a manual credit adjustment to a retailer requires
    `expected_retailer_version` matching the retailer's current `version`,
    because every adjustment recomputes `credit_balance_cents` and bumps the
    retailer's version; a client computing a top-up from a stale balance is
    rejected rather than allowed to compound on an outdated base."

    Design: Corner/complexity_layers/occ_credit_adjustment_stale_retailer_version
    """
    retailer = create_retailer_account()
    observed_version = retailer["version"]

    first = validate_success(api.create_credit_adjustment(
        retailer["id"],
        create_credit_adjustment_payload(
            amount_cents=5000, reason="promo",
            expected_retailer_version=observed_version,
        ),
        PM,
    ), expected_status=201)
    assert first["amount_cents"] == 5000

    # Replaying the same stale expected version is rejected with 412.
    stale = api.create_credit_adjustment(
        retailer["id"],
        create_credit_adjustment_payload(
            amount_cents=7000, reason="stale retry",
            expected_retailer_version=observed_version,
        ),
        PM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    reloaded = get_success_data(api.get_retailer(retailer["id"], PM))
    assert reloaded["credit_balance_cents"] == 5000, (
        "Only the first adjustment may post when the second carries a stale version"
    )


def test_retailer_balance_tracks_postings_across_payout_and_clawback(api):
    """PRD §3.1: "The retailer's `credit_balance_cents` is maintained as the
    sum of all its adjustments' `amount_cents`, recomputed on every posting,
    and each posting — manual or cascaded — increments the retailer's
    `version` by one."
    PRD §3.9: "Otherwise the payout posts a `CreditAdjustment` for
    `+credit_cents` with source `WARRANTY_PAYOUT` and `source_id` set to the
    claim, recomputes the retailer's balance, and increments the retailer's
    `version`."

    Design: Difficulty/compensating_invariant/retailer_ledger_invariant
    """
    ctx = setup_approved_claim(claim_type="WORKMANSHIP", measured_sag_inches=0.5,
                               unit_price_cents=200000)
    retailer_id = ctx["retailer"]["id"]
    version_at_creation = ctx["retailer"]["version"]

    paid = validate_success(api.pay_warranty_claim(ctx["claim"]["id"], PM))
    assert paid["status"] == "PAID"

    after_pay = get_success_data(api.get_retailer(retailer_id, PM))
    assert after_pay["credit_balance_cents"] == 200000
    assert after_pay["version"] == version_at_creation + 1

    clawback = validate_success(api.create_credit_adjustment(
        retailer_id,
        create_credit_adjustment_payload(
            amount_cents=-50000, reason="clawback",
            expected_retailer_version=after_pay["version"],
        ),
        PM,
    ), expected_status=201)
    assert clawback["amount_cents"] == -50000

    after_clawback = get_success_data(api.get_retailer(retailer_id, PM))
    assert after_clawback["credit_balance_cents"] == 150000, (
        "Payout +200000 followed by clawback -50000 must leave balance 150000"
    )


def test_retailer_ledger_sums_signed_amounts_without_drift(api):
    """PRD §3.1: "The retailer's `credit_balance_cents` is maintained as the
    sum of all its adjustments' `amount_cents`, recomputed on every posting,
    and each posting — manual or cascaded — increments the retailer's
    `version` by one."

    Design: Difficulty/compensating_invariant/retailer_ledger_invariant
    """
    ctx = setup_approved_claim(claim_type="WORKMANSHIP", measured_sag_inches=0.5,
                               unit_price_cents=200000)
    retailer_id = ctx["retailer"]["id"]

    validate_success(api.pay_warranty_claim(ctx["claim"]["id"], PM))
    after_pay = get_success_data(api.get_retailer(retailer_id, PM))
    validate_success(api.create_credit_adjustment(
        retailer_id,
        create_credit_adjustment_payload(
            amount_cents=-50000, reason="clawback",
            expected_retailer_version=after_pay["version"],
        ),
        PM,
    ), expected_status=201)

    ledger = list_ledger(retailer_id)
    assert len(ledger) == 2
    for entry in ledger:
        assert_credit_adjustment(entry)
    assert ledger[0]["amount_cents"] == 200000
    assert ledger[0]["source"] == "WARRANTY_PAYOUT"
    assert ledger[1]["amount_cents"] == -50000
    assert ledger[1]["source"] == "MANUAL"

    balance = get_success_data(api.get_retailer(retailer_id, PM))["credit_balance_cents"]
    ledger_sum = sum(e["amount_cents"] for e in ledger)
    assert balance == ledger_sum == 150000, (
        f"Balance {balance} must equal the ledger sum {ledger_sum} with no drift"
    )


def test_retailer_role_cannot_post_credit_adjustment(api):
    """PRD §2.1: "If the caller's role is well-formed but not in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /plant/retailers/{id}/credit-adjustments is authorized for
    PlantManager only.

    Design: Corner/rbac/retailer_cannot_post_credit_adjustment
    """
    retailer = create_retailer_account()
    resp = api.create_credit_adjustment(
        retailer["id"],
        create_credit_adjustment_payload(
            amount_cents=1000, reason="self serve",
            expected_retailer_version=retailer["version"],
        ),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
