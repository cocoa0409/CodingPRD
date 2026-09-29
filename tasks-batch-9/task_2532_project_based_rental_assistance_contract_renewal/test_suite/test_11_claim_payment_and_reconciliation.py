"""Claim payment ordering behind the covering voucher, the reversal compensation, and the
read-only reconciliation projection."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_HOUSEHOLD_ONE,
    TEST_USERS,
    api_client,
    certify_household,
    create_direct_ledger_claim,
    create_household,
    create_voucher,
    create_voucher_submission_payload,
    current_contract_version,
    reverse_voucher,
    reverse_voucher_payload,
    set_clock_date,
    setup_approved_claim,
    setup_ledger_at_balance,
    setup_paid_voucher,
    setup_portfolio,
    setup_reference_households,
    setup_submitted_voucher,
    validate_error,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]


def test_claim_payment_waits_for_the_covering_voucher_and_then_settles_the_ledger():
    """"Payment of an `APPROVED` claim is ordered behind the covering voucher: the voucher
    submission whose `contract_id` matches the claim's and whose `period_month` equals the
    claim's `claim_period_month` must exist and be in state `PAID`, otherwise the payment is
    refused with `ERR_COVERING_VOUCHER_NOT_PAID` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/special_claim_payment_requires_the_covering_monthly_voucher_to_be_paid_first
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_reference_households(ctx["property"]["id"], owner_headers, "2026-07-01")

    voucher = setup_submitted_voucher(contract_id, owner_headers, "2026-07")
    assert voucher["requested_hap_cents"] == 211500, (
        f"84500 plus 127000 is 211500, got {voucher['requested_hap_cents']}"
    )
    assert voucher["included_certification_count"] == 2
    assert voucher["state"] == "SUBMITTED"

    claim = create_direct_ledger_claim(
        contract_id,
        owner_headers,
        "UNPAID_RENT",
        "101",
        "2026-07",
        claimed_amount_cents=90000,
        security_deposit_balance_cents=20000,
    )
    assert claim["computed_amount_cents"] == 70000, (
        "the lesser of 90000 and one month of 118000, less a 20000 deposit, is 70000, got "
        f"{claim['computed_amount_cents']}"
    )
    assert claim["valuation_variant"] == "DIRECT_LEDGER"
    assert claim["vacancy_days_claimed"] == 0
    approved = setup_approved_claim(
        claim, owner_headers, "Tenant ledger and eviction record verified"
    )
    assert approved["state"] == "APPROVED"

    validate_error(
        api_client.pay_special_claim(claim["id"], CA_HEADERS),
        ApiErrorId.ERR_COVERING_VOUCHER_NOT_PAID.value,
        expected_status=409,
    )
    blocked = validate_success(api_client.get_special_claim(claim["id"], CA_HEADERS))
    assert blocked["state"] == "APPROVED", (
        "the gate reads a different entity and leaves the claim exactly where it was, got "
        f"{blocked['state']}"
    )
    assert blocked["paid_amount_cents"] is None

    paid_voucher = validate_success(
        api_client.pay_voucher_submission(voucher["id"], CA_HEADERS)
    )
    assert paid_voucher["state"] == "PAID"
    assert paid_voucher["paid_amount_cents"] == 211500

    paid_claim = validate_success(api_client.pay_special_claim(claim["id"], CA_HEADERS))
    assert paid_claim["state"] == "PAID", (
        f"the same call now succeeds unchanged, got {paid_claim['state']}"
    )
    assert paid_claim["paid_amount_cents"] == 70000

    contract = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract["paid_hap_total_cents"] == 211500
    assert contract["paid_claims_total_cents"] == 70000
    assert contract["hap_ledger_balance_cents"] == 29718500, (
        "30000000 less 211500 less 70000 is 29718500, got "
        f"{contract['hap_ledger_balance_cents']}"
    )

    rec = validate_success(api_client.get_contract_reconciliation(contract_id, CA_HEADERS))
    assert rec["requested_total_cents"] == 211500
    assert rec["paid_hap_total_cents"] == 211500
    assert rec["paid_claims_total_cents"] == 70000
    assert rec["hap_ledger_balance_cents"] == 29718500
    assert rec["variance_cents"] == 0, (
        f"everything requested has been paid, got {rec['variance_cents']}"
    )
    assert rec["paid_period_count"] == 1


def test_the_covering_voucher_is_matched_by_period_value_not_by_a_foreign_key():
    """"Payment of an `APPROVED` claim is ordered behind the covering voucher: the voucher
    submission whose `contract_id` matches the claim's and whose `period_month` equals the
    claim's `claim_period_month` must exist and be in state `PAID`, otherwise the payment is
    refused with `ERR_COVERING_VOUCHER_NOT_PAID` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/special_claim_payment_requires_the_covering_monthly_voucher_to_be_paid_first
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_reference_households(ctx["property"]["id"], owner_headers, "2026-07-01")

    claim = create_direct_ledger_claim(
        contract_id,
        owner_headers,
        "UNPAID_RENT",
        "101",
        "2026-07",
        claimed_amount_cents=90000,
        security_deposit_balance_cents=20000,
    )
    setup_approved_claim(claim, owner_headers, "Arrears documented")

    august = setup_paid_voucher(
        contract_id, owner_headers, "2026-08", submit_clock_date="2026-09-01"
    )
    assert august["state"] == "PAID"
    assert august["paid_amount_cents"] == 211500

    validate_error(
        api_client.pay_special_claim(claim["id"], CA_HEADERS),
        ApiErrorId.ERR_COVERING_VOUCHER_NOT_PAID.value,
        expected_status=409,
    )
    still_blocked = validate_success(api_client.get_special_claim(claim["id"], CA_HEADERS))
    assert still_blocked["state"] == "APPROVED", (
        "a PAID voucher for 2026-08 does not cover a 2026-07 claim, got "
        f"{still_blocked['state']}"
    )
    mid_ledger = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert mid_ledger["hap_ledger_balance_cents"] == 29788500, (
        "only the August voucher has moved money, got "
        f"{mid_ledger['hap_ledger_balance_cents']}"
    )

    july = setup_paid_voucher(contract_id, owner_headers, "2026-07")
    assert july["period_month"] == "2026-07"
    assert july["paid_amount_cents"] == 211500

    settled = validate_success(api_client.pay_special_claim(claim["id"], CA_HEADERS))
    assert settled["state"] == "PAID", (
        "the covering month is now paid, so the claim clears, got " f"{settled['state']}"
    )
    assert settled["paid_amount_cents"] == 70000

    rec = validate_success(api_client.get_contract_reconciliation(contract_id, CA_HEADERS))
    assert rec["requested_total_cents"] == 423000
    assert rec["paid_hap_total_cents"] == 423000
    assert rec["paid_claims_total_cents"] == 70000
    assert rec["paid_period_count"] == 2
    assert rec["hap_ledger_balance_cents"] == 29507000, (
        "30000000 less two 211500 vouchers less the 70000 claim is 29507000, got "
        f"{rec['hap_ledger_balance_cents']}"
    )


def test_reversing_a_paid_voucher_restores_the_ledger_to_its_pre_payment_value():
    """"A permitted reversal moves the voucher `PAID` → the terminal `REVERSED`, records
    `reversal_reason`, retains `paid_amount_cents` for audit while stopping it counting toward
    the ledger, subtracts that retained amount from the contract's `paid_hap_total_cents`, adds
    it back to `hap_ledger_balance_cents`, and increments the contract's `version` by 1 —
    restoring both figures to exactly their pre-payment values."

    Design: Difficulty/compensating_invariant/reversing_a_paid_voucher_restores_the_hap_ledger_exactly_and_frees_the_period_again
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_reference_households(ctx["property"]["id"], owner_headers, "2026-07-01")

    voucher = setup_submitted_voucher(contract_id, owner_headers, "2026-07")
    assert voucher["requested_hap_cents"] == 211500
    assert voucher["included_certification_count"] == 2
    opening = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert opening["hap_ledger_balance_cents"] == 30000000
    version_before = opening["version"]

    paid = validate_success(api_client.pay_voucher_submission(voucher["id"], CA_HEADERS))
    assert paid["paid_amount_cents"] == 211500

    rec1 = validate_success(api_client.get_contract_reconciliation(contract_id, CA_HEADERS))
    assert rec1["requested_total_cents"] == 211500
    assert rec1["paid_hap_total_cents"] == 211500
    assert rec1["reversed_total_cents"] == 0
    assert rec1["hap_ledger_balance_cents"] == 29788500, (
        f"30000000 less 211500 is 29788500, got {rec1['hap_ledger_balance_cents']}"
    )
    assert rec1["variance_cents"] == 0
    assert rec1["paid_period_count"] == 1

    reversed_voucher = reverse_voucher(
        voucher["id"], "Duplicate disbursement discovered in the July close"
    )
    assert reversed_voucher["state"] == "REVERSED"
    assert reversed_voucher["reversal_reason"] == (
        "Duplicate disbursement discovered in the July close"
    )
    assert reversed_voucher["paid_amount_cents"] == 211500, (
        "the paid amount is retained for audit rather than cleared, got "
        f"{reversed_voucher['paid_amount_cents']}"
    )

    rec2 = validate_success(api_client.get_contract_reconciliation(contract_id, CA_HEADERS))
    assert rec2["requested_total_cents"] == 0, (
        "a REVERSED voucher leaves the requested total as well as the paid total, got "
        f"{rec2['requested_total_cents']}"
    )
    assert rec2["paid_hap_total_cents"] == 0
    assert rec2["reversed_total_cents"] == 211500
    assert rec2["hap_ledger_balance_cents"] == 30000000
    assert rec2["variance_cents"] == 0
    assert rec2["paid_period_count"] == 0

    after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert after["hap_ledger_balance_cents"] == 30000000, (
        "the compensation restores the ledger to the cent, got "
        f"{after['hap_ledger_balance_cents']}"
    )
    assert after["paid_hap_total_cents"] == 0
    assert after["version"] > version_before, (
        "compensation restores the money, never the version, got "
        f"{after['version']} against {version_before}"
    )


def test_a_reversed_month_frees_the_billing_period_to_be_re_billed():
    """"Only one live voucher per billing month is permitted per contract: if a voucher for the
    same `contract_id` and `period_month` exists in any state other than `REVERSED`, the request
    is refused with `ERR_DUPLICATE_VOUCHER_PERIOD` (HTTP 409) — a reversed month may be
    re-billed."

    Design: Difficulty/compensating_invariant/reversing_a_paid_voucher_restores_the_hap_ledger_exactly_and_frees_the_period_again
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_reference_households(ctx["property"]["id"], owner_headers, "2026-07-01")

    first = setup_paid_voucher(contract_id, owner_headers, "2026-07")
    assert first["state"] == "PAID"

    validate_error(
        api_client.create_voucher_submission(
            create_voucher_submission_payload(
                contract_id, current_contract_version(contract_id), period_month="2026-07"
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_VOUCHER_PERIOD.value,
        expected_status=409,
    )

    assert reverse_voucher(first["id"], "July billed against the wrong contract")["state"] == (
        "REVERSED"
    )

    second = create_voucher(contract_id, owner_headers, "2026-07")
    assert second["state"] == "DRAFT", (
        "the REVERSED row no longer occupies the 2026-07 slot, got " f"{second['state']}"
    )
    assert second["requested_hap_cents"] == 211500, (
        "the month is recomputed from the same two certifications, got "
        f"{second['requested_hap_cents']}"
    )
    assert second["paid_amount_cents"] is None
    assert second["id"] != first["id"]

    ledger = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert ledger["hap_ledger_balance_cents"] == 30000000, (
        "a DRAFT voucher moves no money, got " f"{ledger['hap_ledger_balance_cents']}"
    )

    validate_error(
        api_client.create_voucher_submission(
            create_voucher_submission_payload(
                contract_id, current_contract_version(contract_id), period_month="2026-07"
            ),
            owner_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_VOUCHER_PERIOD.value,
        expected_status=409,
    )
    assert validate_success(
        api_client.get_voucher_submission(first["id"], CA_HEADERS)
    )["paid_amount_cents"] == 211500, "the audit trail on the reversed row is untouched"


def test_a_paid_claim_blocks_the_reversal_of_the_voucher_that_covers_its_period():
    """"It is blocked while any special claim whose `claim_period_month` equals this voucher's
    `period_month` is already in state `PAID`: reversing the covering voucher out from under a
    paid claim would break the ordering the claim relied on, so the attempt is refused with
    `ERR_CLAIM_PAID_BLOCKS_REVERSAL` (HTTP 409)."

    Design: Corner/validations/a_paid_claim_blocks_the_reversal_of_the_voucher_that_covers_its_period
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    household = create_household(
        ctx["property"]["id"], owner_headers, **REFERENCE_HOUSEHOLD_ONE
    )
    certification = certify_household(household["id"], owner_headers, "2026-07-01")
    assert certification["hap_cents"] == 84500
    set_clock_date("2026-09-01")

    july = setup_paid_voucher(contract_id, owner_headers, "2026-07")
    assert july["paid_amount_cents"] == 84500

    claim = create_direct_ledger_claim(
        contract_id,
        owner_headers,
        "UNPAID_RENT",
        "101",
        "2026-07",
        claimed_amount_cents=90000,
        security_deposit_balance_cents=20000,
    )
    assert claim["computed_amount_cents"] == 70000
    setup_approved_claim(claim, owner_headers, "Tenant ledger verified")
    paid_claim = validate_success(api_client.pay_special_claim(claim["id"], CA_HEADERS))
    assert paid_claim["state"] == "PAID"
    assert paid_claim["paid_amount_cents"] == 70000
    ledger_before = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert ledger_before["hap_ledger_balance_cents"] == 29845500, (
        "30000000 less 84500 less 70000 is 29845500, got "
        f"{ledger_before['hap_ledger_balance_cents']}"
    )

    august = setup_paid_voucher(contract_id, owner_headers, "2026-08")
    assert august["paid_amount_cents"] == 84500

    validate_error(
        api_client.reverse_voucher_submission(
            july["id"],
            reverse_voucher_payload("Duplicate July disbursement discovered in audit"),
            CA_HEADERS,
        ),
        ApiErrorId.ERR_CLAIM_PAID_BLOCKS_REVERSAL.value,
        expected_status=409,
    )
    assert validate_success(
        api_client.get_voucher_submission(july["id"], CA_HEADERS)
    )["state"] == "PAID", "the blocker lives on another entity and the voucher does not move"

    reversed_august = reverse_voucher(
        august["id"], "August voucher billed against the wrong contract"
    )
    assert reversed_august["state"] == "REVERSED", (
        "no paid claim names 2026-08, so the same call succeeds there, got "
        f"{reversed_august['state']}"
    )
    assert reversed_august["reversal_reason"] == (
        "August voucher billed against the wrong contract"
    )

    rec = validate_success(api_client.get_contract_reconciliation(contract_id, CA_HEADERS))
    assert rec["requested_total_cents"] == 84500
    assert rec["paid_hap_total_cents"] == 84500
    assert rec["reversed_total_cents"] == 84500
    assert rec["paid_claims_total_cents"] == 70000
    assert rec["paid_period_count"] == 1
    assert rec["hap_ledger_balance_cents"] == 29845500, (
        "the August round trip left no drift, got " f"{rec['hap_ledger_balance_cents']}"
    )


def test_claim_payment_checks_the_covering_voucher_before_the_budget_ceiling():
    """"Payment is a `ContractAdministrator` act on a `SUBMITTED` voucher and is the point where
    the money invariant bites: `requested_hap_cents` must not exceed the contract's
    `hap_ledger_balance_cents`, and an over-draw is refused with `ERR_HAP_BUDGET_EXCEEDED`
    (HTTP 402)."

    Design: Corner/validations/claim_payment_checks_the_covering_voucher_before_the_budget_ceiling
    """
    ctx = setup_ledger_at_balance(80000)
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    assert ctx["contract"]["hap_ledger_balance_cents"] == 80000
    household = create_household(
        ctx["property"]["id"], owner_headers, **REFERENCE_HOUSEHOLD_ONE
    )
    certify_household(household["id"], owner_headers, "2026-07-01")

    voucher = setup_submitted_voucher(contract_id, owner_headers, "2026-07")
    assert voucher["requested_hap_cents"] == 84500
    assert voucher["state"] == "SUBMITTED"

    claim = create_direct_ledger_claim(
        contract_id,
        owner_headers,
        "UNPAID_RENT",
        "101",
        "2026-07",
        claimed_amount_cents=90000,
        security_deposit_balance_cents=0,
    )
    assert claim["computed_amount_cents"] == 90000, (
        "90000 is under one month of 118000 and no deposit offsets it, got "
        f"{claim['computed_amount_cents']}"
    )
    setup_approved_claim(claim, owner_headers, "Arrears documented")

    validate_error(
        api_client.pay_special_claim(claim["id"], CA_HEADERS),
        ApiErrorId.ERR_COVERING_VOUCHER_NOT_PAID.value,
        expected_status=409,
    )
    validate_error(
        api_client.pay_voucher_submission(voucher["id"], CA_HEADERS),
        ApiErrorId.ERR_HAP_BUDGET_EXCEEDED.value,
        expected_status=402,
    )

    assert validate_success(
        api_client.get_special_claim(claim["id"], CA_HEADERS)
    )["state"] == "APPROVED", "the cross-entity check answered before the fiscal one"
    assert validate_success(
        api_client.get_voucher_submission(voucher["id"], CA_HEADERS)
    )["state"] == "SUBMITTED", "neither refusal moved a state"

    rec = validate_success(api_client.get_contract_reconciliation(contract_id, CA_HEADERS))
    assert rec["requested_total_cents"] == 84500
    assert rec["paid_hap_total_cents"] == 0
    assert rec["paid_claims_total_cents"] == 0
    assert rec["variance_cents"] == 84500, (
        "the whole request is still unpaid, got " f"{rec['variance_cents']}"
    )
    assert rec["paid_period_count"] == 0
    assert rec["hap_ledger_balance_cents"] == 80000
    assert rec["authorized_hap_budget_cents"] == 80000


def test_the_reconciliation_projection_partitions_vouchers_by_state():
    """"`requested_total_cents` sums `requested_hap_cents` over vouchers in state `SUBMITTED` or
    `PAID`, so drafts are excluded." "`reversed_total_cents` sums `paid_amount_cents` over
    vouchers in state `REVERSED`, reported separately precisely because those amounts are
    retained but no longer count." "`hap_ledger_balance_cents` is the authorization less the paid
    voucher total less the paid claim total, and it must always equal the contract's own stored
    `hap_ledger_balance_cents` — a divergence between the projection and the stored field is a
    defect."

    Design: Corner/endpoints/the_reconciliation_projection_partitions_vouchers_by_state_and_matches_the_stored_ledger
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    households = setup_reference_households(
        ctx["property"]["id"], owner_headers, "2026-07-01"
    )
    assert households["certification_one"]["hap_cents"] == 84500
    assert households["certification_two"]["hap_cents"] == 127000
    set_clock_date("2026-11-01")

    first = setup_paid_voucher(contract_id, owner_headers, "2026-07")
    assert first["requested_hap_cents"] == 211500
    assert first["included_certification_count"] == 2
    assert first["paid_amount_cents"] == 211500

    claim = create_direct_ledger_claim(
        contract_id,
        owner_headers,
        "UNPAID_RENT",
        "101",
        "2026-07",
        claimed_amount_cents=90000,
        security_deposit_balance_cents=20000,
    )
    setup_approved_claim(
        claim, owner_headers, "Tenant ledger reconciled against the eviction record"
    )
    assert validate_success(api_client.pay_special_claim(claim["id"], CA_HEADERS))[
        "paid_amount_cents"
    ] == 70000

    second = setup_paid_voucher(contract_id, owner_headers, "2026-08")
    reversed_second = reverse_voucher(
        second["id"], "August disbursement issued against the wrong contract"
    )
    assert reversed_second["state"] == "REVERSED"
    assert reversed_second["paid_amount_cents"] == 211500

    third = setup_submitted_voucher(contract_id, owner_headers, "2026-09")
    assert third["state"] == "SUBMITTED"
    fourth = create_voucher(contract_id, owner_headers, "2026-10")
    assert fourth["state"] == "DRAFT"
    assert fourth["requested_hap_cents"] == 211500

    stored = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    rec = validate_success(
        api_client.get_contract_reconciliation(contract_id, owner_headers)
    )
    assert rec["requested_total_cents"] == 423000, (
        "only the PAID July and the SUBMITTED September count; the REVERSED August and the "
        f"DRAFT October are both excluded, got {rec['requested_total_cents']}"
    )
    assert rec["paid_hap_total_cents"] == 211500, (
        "a reversed voucher retains paid_amount_cents but leaves the paid total, got "
        f"{rec['paid_hap_total_cents']}"
    )
    assert rec["reversed_total_cents"] == 211500
    assert rec["paid_claims_total_cents"] == 70000
    assert rec["authorized_hap_budget_cents"] == 30000000
    assert rec["paid_period_count"] == 1
    assert rec["variance_cents"] == 211500, (
        "423000 less 211500 — the unpaid SUBMITTED voucher is the whole variance, got "
        f"{rec['variance_cents']}"
    )
    assert rec["hap_ledger_balance_cents"] == 29718500, (
        "30000000 less 211500 less 70000 is 29718500, got "
        f"{rec['hap_ledger_balance_cents']}"
    )
    assert rec["hap_ledger_balance_cents"] == stored["hap_ledger_balance_cents"], (
        "the projection reproduces the stored ledger exactly, got "
        f"{rec['hap_ledger_balance_cents']} against {stored['hap_ledger_balance_cents']}"
    )
