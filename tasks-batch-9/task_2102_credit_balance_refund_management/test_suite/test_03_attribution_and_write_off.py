"""Attribution of a credit between the patient and the payer, and de-minimis write-off."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_attribution_portions_sum,
    attribute,
    post_txn,
    read_account,
    read_credit_balance,
    reverse_txn,
    run_identify_sweep,
    seed_account,
    seed_payer,
    set_clock,
    setup_attributed_credit,
    setup_identified_credit,
    setup_split_ledger_credits,
    start_review,
    validate_error,
    validate_success,
    write_off,
)

ANALYST = TEST_USERS["credit_analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_proportional_attribution_splits_the_credit_by_paid_share(api):
    """PRD §3.4: "Under `PROPORTIONAL`, sum the magnitudes of the qualifying payments whose `source` is `PATIENT`. The patient slice is the credit multiplied by that patient-paid sum, divided by the total paid, rounded half up to a whole cent. The payer slice is then the credit minus the patient slice, so the payer bucket absorbs the residual cent and the two portions always sum exactly to `credit_amount_cents`."
    PRD §3.4: "Once the two portions are known, the classification is the same under both methods: `attribution` is `SPLIT` when both portions are strictly positive, `PATIENT` when only the patient portion is strictly positive, and `PAYER` otherwise."

    Design: Difficulty/dual_variant_calc/attribution_proportional_vs_reverse_chronological_on_credit_balance
    """
    scenario = setup_split_ledger_credits(account_numbers=["ACCT-SP1", "ACCT-SP2"])
    credit_balance_id = scenario["credit_balances"][0]["id"]
    start_review(credit_balance_id)

    attributed = validate_success(
        api.attribute_credit_balance(
            credit_balance_id, {"attribution_method": "PROPORTIONAL"}, ANALYST
        )
    )

    assert attributed["credit_amount_cents"] == 20_000
    assert attributed["patient_portion_cents"] == 8_000
    assert attributed["payer_portion_cents"] == 12_000
    assert attributed["attribution"] == "SPLIT"
    assert attributed["attribution_method"] == "PROPORTIONAL"
    assert attributed["status"] == "ATTRIBUTED"
    assert_attribution_portions_sum(attributed)


def test_reverse_chronological_attribution_diverges_on_an_identical_ledger(api):
    """PRD §3.4: "Under `REVERSE_CHRONOLOGICAL`, sort the qualifying payments by `posted_at` descending, breaking ties by `created_at` descending, and unwind the credit against them newest first."
    PRD §3.4: "A single recent payment large enough to cover the whole credit therefore takes the entire attribution and leaves the other bucket at 0 — which is exactly how this method differs from the proportional one on an identical ledger."

    Design: Difficulty/dual_variant_calc/attribution_proportional_vs_reverse_chronological_on_credit_balance
    """
    scenario = setup_split_ledger_credits(account_numbers=["ACCT-SP1", "ACCT-SP2"])
    proportional_id = scenario["credit_balances"][0]["id"]
    reverse_id = scenario["credit_balances"][1]["id"]

    start_review(proportional_id)
    proportional = attribute(proportional_id, "PROPORTIONAL")
    start_review(reverse_id)
    reverse = validate_success(
        api.attribute_credit_balance(
            reverse_id, {"attribution_method": "REVERSE_CHRONOLOGICAL"}, ANALYST
        )
    )

    assert reverse["credit_amount_cents"] == 20_000
    assert reverse["patient_portion_cents"] == 20_000
    assert reverse["payer_portion_cents"] == 0
    assert reverse["attribution"] == "PATIENT"
    assert_attribution_portions_sum(reverse)

    assert proportional["attribution"] == "SPLIT"
    assert reverse["attribution"] != proportional["attribution"], (
        "the two methods must diverge on byte-identical ledgers"
    )
    assert reverse["patient_portion_cents"] != proportional["patient_portion_cents"]


def test_attribution_is_undetermined_when_no_qualifying_payment_exists(api):
    """PRD §3.4: "If the total paid is zero — no qualifying payment exists at all — then `patient_portion_cents` is 0, `payer_portion_cents` is 0, and `attribution` is `UNDETERMINED`."

    Design: Corner/calculations/attribution_is_undetermined_when_no_qualifying_payment_rows_exist
    """
    scenario = setup_identified_credit(
        account_number="ACCT-UD1", charge_cents=10_000,
        payment_cents=-12_000, payment_source="SYSTEM",
        payment_txn_type="CONTRACTUAL_ADJUSTMENT",
    )
    credit_balance_id = scenario["credit_balance"]["id"]
    start_review(credit_balance_id)

    attributed = validate_success(
        api.attribute_credit_balance(
            credit_balance_id, {"attribution_method": "PROPORTIONAL"}, ANALYST
        )
    )
    assert attributed["credit_amount_cents"] == 2_000
    assert attributed["attribution"] == "UNDETERMINED"
    assert attributed["patient_portion_cents"] == 0
    assert attributed["payer_portion_cents"] == 0
    assert attributed["status"] == "ATTRIBUTED"


def test_attribution_input_set_drops_a_reversed_payment_row(api):
    """PRD §3.4: "Take every ledger transaction on the credit balance's account whose `txn_type` is `PAYMENT`, whose `is_reversed` is false, whose `reversal_of_transaction_id` is null — a reversal row is never itself treated as a payment — and whose `posted_at` is at or before the credit balance's `identified_at`, that upper bound being inclusive."

    Design: Corner/calculations/attribution_input_set_excludes_a_reversed_payment_row
    """
    set_clock("2026-08-01T00:00:00Z")
    payer = seed_payer(payer_code="MCR", payer_type="MEDICARE")
    account = seed_account(payer["id"], account_number="ACCT-RX1",
                           financial_class="INPATIENT", patient_name="Rex Nolan")
    post_txn(account["id"], "CHARGE", 50_000, "SYSTEM")
    set_clock("2026-08-05T00:00:00Z")
    post_txn(account["id"], "PAYMENT", -62_000, "PAYER", payer_id=payer["id"])
    set_clock("2026-08-06T00:00:00Z")
    patient_payment = post_txn(account["id"], "PAYMENT", -20_000, "PATIENT")
    set_clock("2026-08-07T00:00:00Z")
    reverse_txn(patient_payment["id"], remark="Patient payment applied to the wrong account")
    set_clock("2026-08-15T00:00:00Z")
    sweep = run_identify_sweep([account["id"]])
    credit_balance_id = sweep["credit_balance_ids"][0]
    start_review(credit_balance_id)

    attributed = validate_success(
        api.attribute_credit_balance(
            credit_balance_id, {"attribution_method": "PROPORTIONAL"}, ANALYST
        )
    )

    assert read_account(account["id"])["balance_cents"] == -12_000
    assert attributed["credit_amount_cents"] == 12_000
    assert attributed["attribution"] == "PAYER"
    assert attributed["payer_portion_cents"] == 12_000
    assert attributed["patient_portion_cents"] == 0


def test_start_review_on_an_attributed_credit_balance_is_rejected(api):
    """PRD §3.4: "Taking it into review moves the credit balance `IDENTIFIED → UNDER_REVIEW` and bumps its `version` by 1; a credit balance in any other status is refused with `ERR_CREDIT_BALANCE_INVALID_STATE`."

    Design: Corner/state_machines/start_review_from_attributed_state_is_rejected
    """
    scenario = setup_attributed_credit(account_number="ACCT-IV2",
                                       financial_class="INPATIENT")
    credit_balance = scenario["credit_balance"]

    response = api.start_credit_balance_review(credit_balance["id"], {}, ANALYST)
    validate_error(response, ApiErrorId.ERR_CREDIT_BALANCE_INVALID_STATE.value)

    unchanged = read_credit_balance(credit_balance["id"])
    assert unchanged["status"] == "ATTRIBUTED"
    assert unchanged["version"] == credit_balance["version"], (
        "a rejected transition must not bump the version"
    )


def test_written_off_credit_balance_is_terminal_and_drops_out_of_open_liability(api):
    """PRD §3.4: "A `ComplianceOfficer` may write off a de-minimis credit, moving it `ATTRIBUTED → WRITTEN_OFF` with a supplied `reason_code` and bumping its `version` by 1."
    PRD §3.4: "The outstanding credit must be small: `outstanding_cents` must be at most 1,000 cents — ten dollars — or the attempt fails with `ERR_WRITE_OFF_LIMIT_EXCEEDED`."
    PRD §2.9: "An account's `credit_balance_cents` is the sum of `credit_amount_cents` over the credit balance rows on that account whose `status` is `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED` or `REFUND_PENDING`; those four statuses constitute open credit liability, and a credit balance in any other status contributes nothing."

    Design: Corner/state_machines/written_off_credit_balance_is_terminal_and_rejects_further_transitions
    """
    scenario = setup_attributed_credit(
        account_number="ACCT-WO1", charge_cents=10_000, payment_cents=-10_600,
    )
    credit_balance_id = scenario["credit_balance"]["id"]
    assert scenario["credit_balance"]["outstanding_cents"] == 600

    written_off = validate_success(
        api.write_off_credit_balance(
            credit_balance_id, {"reason_code": "DE_MINIMIS"}, COMPLIANCE
        )
    )
    assert written_off["status"] == "WRITTEN_OFF"

    blocked = api.start_credit_balance_review(credit_balance_id, {}, ANALYST)
    validate_error(blocked, ApiErrorId.ERR_CREDIT_BALANCE_INVALID_STATE.value)

    account = read_account(scenario["account"]["id"])
    assert account["credit_balance_cents"] == 0
    assert account["balance_cents"] == -600
