"""Quantities that must return to an exact earlier value, and one that must not.

Money and strikes are conserved: reversing a correction puts them back where they
were. The education dimension is deliberately not conserved — completing education
is a fact about the shipper that survives the reversal of the notice that caused it.
"""

from test_helpers import (
    assert_credit_memo,
    assert_shipment_ledger_identity,
    assert_strike_count_conserved,
)
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"


def _stacked_notice_scenario():
    """One shipment carrying an UPHELD notice and a second, freshly disputed notice
    raised by hand against the same capture five months later."""
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_issued_notice_scenario(
        env=env, pro_number="PROD001", measured_total_weight_lb=520
    )
    assert scenario["shipment"]["original_charge_cents"] == 12500

    first_dispute = fx.file_dispute(
        scenario["notice_id"], scenario["customer_id"], evidence_doc_count=1
    )
    fx.set_clock("2026-02-05T00:00:00Z")
    fx.resolve_dispute(
        first_dispute["id"],
        "UPHELD_CARRIER",
        resolution_note="Dimensioner evidence stands.",
    )

    fx.set_clock("2026-06-01T00:00:00Z")
    second_notice = fx.draft_manual_notice(
        scenario["shipment_id"],
        notice_type="RECLASS",
        basis_capture_event_id=scenario["capture_event"]["id"],
    )
    fx.issue_notice(second_notice["id"])
    second_dispute = fx.file_dispute(
        second_notice["id"],
        scenario["customer_id"],
        claim_basis="EVIDENCE_INSUFFICIENT",
        evidence_doc_count=2,
    )

    scenario["first_notice_id"] = scenario["notice_id"]
    scenario["second_notice_id"] = second_notice["id"]
    scenario["second_dispute_id"] = second_dispute["id"]
    return scenario


def _overturn_the_second_notice(scenario):
    return fx.resolve_dispute(
        scenario["second_dispute_id"],
        "OVERTURNED",
        reviewer_user_id="rev-2",
        resolution_note="Second notice duplicates the first correction.",
    )


def _educated_shipper_scenario():
    """A one-strike-interval shipper whose only notice is issued, whose education is
    then completed, and who has a dispute pending against that notice."""
    env = fx.setup_pricing_environment(
        clock=CLOCK,
        customer_overrides={
            "account_code": "REPEAT",
            "name": "Repeat Offender Co",
            "education_strike_interval": 1,
        },
    )
    scenario = fx.setup_issued_notice_scenario(
        env=env, pro_number="PROD101", measured_total_weight_lb=520
    )
    fx.complete_education(scenario["customer_id"])
    dispute = fx.file_dispute(
        scenario["notice_id"],
        scenario["customer_id"],
        claim_basis="DEVICE_CALIBRATION",
        evidence_doc_count=2,
    )
    scenario["dispute_id"] = dispute["id"]
    return scenario


# ==========================================================================
# Money: the ledger identity holds through a stacked overturn
# ==========================================================================


def test_two_issued_notices_stack_their_frozen_amounts_into_the_ledger():
    """Each contributing notice adds its own frozen delta and fee, so the ledger
    reads 78128 before anything is reversed.

    PRD: "At every instant it equals the shipment's `original_charge_cents`, plus
    the sum over every correction notice of that shipment whose `status` is
    `ISSUED`, `DISPUTED`, `EVIDENCE_REQUESTED`, `UPHELD`, `PARTIALLY_OVERTURNED`
    or `OVERTURNED` of that notice's `applied_delta_cents` added to its
    `inspection_fee_cents`, minus the sum over the credit memos of those notices
    of each memo's `freight_credit_cents` added to its `fee_credit_cents`."

    Design: Difficulty/compensating_invariant/money_invariant_assessed_total_returns_to_pre_notice_value
    """
    scenario = _stacked_notice_scenario()

    shipment = fx.get_shipment(scenario["shipment_id"])
    first_notice = fx.get_notice(scenario["first_notice_id"])
    second_notice = fx.get_notice(scenario["second_notice_id"])

    assert first_notice["status"] == "UPHELD"
    assert first_notice["applied_delta_cents"] == 28314
    assert first_notice["inspection_fee_cents"] == 4500
    assert second_notice["applied_delta_cents"] == 28314, (
        "the manual notice freezes the same delta because it cites the same capture"
    )
    assert second_notice["inspection_fee_cents"] == 4500
    assert shipment["assessed_total_cents"] == 78128, (
        f"12500 plus two contributions of 32814 is 78128, "
        f"got {shipment['assessed_total_cents']}"
    )
    assert_shipment_ledger_identity(
        shipment,
        fx.list_notices_for(scenario["shipment_id"]),
        fx.list_credit_memos_for(scenario["customer_id"]),
    )


def test_a_full_overturn_returns_the_ledger_to_its_pre_notice_value():
    """Reversing the second notice puts the ledger back at 45314 — exactly what it
    read while only the upheld notice stood.

    PRD: "A shipment's `assessed_total_cents` is a conserved quantity, not an
    accumulator that drifts."

    Design: Difficulty/compensating_invariant/money_invariant_assessed_total_returns_to_pre_notice_value
    """
    scenario = _stacked_notice_scenario()

    _overturn_the_second_notice(scenario)

    shipment = fx.get_shipment(scenario["shipment_id"])
    first_notice = fx.get_notice(scenario["first_notice_id"])
    second_notice = fx.get_notice(scenario["second_notice_id"])

    assert shipment["assessed_total_cents"] == 45314, (
        f"the ledger returns to the value it held with one upheld notice, "
        f"got {shipment['assessed_total_cents']}"
    )
    assert first_notice["status"] == "UPHELD"
    assert first_notice["credited_total_cents"] == 0, (
        "an upheld notice never produces a credit"
    )
    assert second_notice["status"] == "OVERTURNED"
    assert second_notice["credited_total_cents"] == 32956
    assert second_notice["applied_delta_cents"] == 28314, (
        "the frozen delta survives the overturn untouched"
    )
    assert shipment["billing_status"] == "CREDITED"
    assert shipment["class_status"] == "CAPTURED"
    assert shipment["open_notice_count"] == 0
    assert_shipment_ledger_identity(
        shipment,
        fx.list_notices_for(scenario["shipment_id"]),
        fx.list_credit_memos_for(scenario["customer_id"]),
    )


def test_the_goodwill_interest_bucket_is_paid_outside_the_ledger():
    """The memo pays 32956 while the ledger only gives back 32814, and the 142-cent
    difference is exactly the interest bucket.

    PRD: "The third credit bucket, `interest_credit_cents`, is deliberately
    excluded from this identity. It is a goodwill payment made outside the freight
    ledger, which is why a full overturn returns `assessed_total_cents` to exactly
    `original_charge_cents` rather than below it."

    Design: Difficulty/compensating_invariant/money_invariant_assessed_total_returns_to_pre_notice_value
    """
    scenario = _stacked_notice_scenario()

    _overturn_the_second_notice(scenario)

    memos = [
        memo
        for memo in fx.list_credit_memos_for(scenario["customer_id"])
        if memo["correction_notice_id"] == scenario["second_notice_id"]
    ]
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert len(memos) == 1, f"one memo per overturned notice, found {len(memos)}"
    memo = memos[0]
    assert_credit_memo(memo)
    assert memo["freight_credit_cents"] == 28314
    assert memo["fee_credit_cents"] == 4500
    assert memo["interest_credit_cents"] == 142, (
        f"28314 at half a percent for one round is 142 cents, "
        f"got {memo['interest_credit_cents']}"
    )
    assert memo["amount_cents"] == 32956
    assert (
        memo["amount_cents"] - memo["interest_credit_cents"] == 32814
    ), "only the freight and fee buckets are subtracted from the shipment ledger"
    assert shipment["assessed_total_cents"] == 45314


# ==========================================================================
# Counts: the strike reverts, the education record does not
# ==========================================================================


def test_overturning_the_only_notice_reverts_the_strike_and_both_indices():
    """The strike is removed from the counted set and neither index retains it.

    PRD: "the shipper's `offender_strike_count` is decremented before the indices,
    tier and window are recomputed. A fully overturned notice contributes to
    neither index thereafter."

    Design: Difficulty/compensating_invariant/count_invariant_strike_reverts_but_education_flag_does_not
    """
    scenario = _educated_shipper_scenario()

    fx.resolve_dispute(
        scenario["dispute_id"],
        "OVERTURNED",
        resolution_note="Terminal scale was uncertified on the capture date.",
    )
    customer = fx.get_customer(scenario["customer_id"])

    assert customer["offender_strike_count"] == 0
    assert customer["liability_index_rolling"] == 0.00
    assert customer["liability_index_lifetime"] == 0.00
    assert customer["offender_tier"] == "TIER_0"
    assert customer["dispute_window_days"] == 30
    assert_strike_count_conserved(customer, fx.list_notices_for(scenario["shipment_id"]))


def test_the_education_record_survives_the_overturn_that_removed_the_strike():
    """The resolution cascade does not write the education dimension at all.

    PRD: "Resolving a dispute writes the dispute, the notice, possibly every line
    of the shipment, the shipment's billing dimension and money, a newly created
    credit memo, and the shipper account's strike and index record."

    Design: Difficulty/compensating_invariant/count_invariant_strike_reverts_but_education_flag_does_not
    """
    scenario = _educated_shipper_scenario()

    fx.resolve_dispute(
        scenario["dispute_id"],
        "OVERTURNED",
        resolution_note="Terminal scale was uncertified on the capture date.",
    )
    customer = fx.get_customer(scenario["customer_id"])

    assert customer["education_status"] == "COMPLETED", (
        "completing education is not undone by reversing the notice that required it"
    )
    assert customer["education_required_at"] is not None
    assert customer["education_required_at"].startswith("2026-01-10T08:00:00"), (
        f"the original requirement instant is kept, "
        f"got {customer['education_required_at']}"
    )
    assert customer["education_threshold_strikes"] == 2, (
        f"the threshold raised at completion stays raised even though the strike "
        f"count fell back to 0, got {customer['education_threshold_strikes']}"
    )


def test_the_shipment_and_its_line_return_to_the_declared_basis():
    """The money and the classification both unwind to the pre-notice state.

    PRD: "Every line of the shipment reverts to its declared classification:
    `found_class_code` returns to null and `classification_source` returns to
    `BOL_DECLARED`."

    Design: Difficulty/compensating_invariant/count_invariant_strike_reverts_but_education_flag_does_not
    """
    scenario = _educated_shipper_scenario()

    fx.resolve_dispute(
        scenario["dispute_id"],
        "OVERTURNED",
        resolution_note="Terminal scale was uncertified on the capture date.",
    )
    shipment = fx.get_shipment(scenario["shipment_id"])
    line = fx.get_shipment_line(scenario["line_ids"][0])
    notice = fx.get_notice(scenario["notice_id"])

    assert shipment["assessed_total_cents"] == 12500, (
        f"the ledger returns to original_charge_cents exactly, "
        f"got {shipment['assessed_total_cents']}"
    )
    assert shipment["class_status"] == "CAPTURED"
    assert shipment["billing_status"] == "CREDITED"
    assert line["found_class_code"] is None
    assert line["classification_source"] == "BOL_DECLARED"
    assert line["effective_class_code"] == 70
    assert notice["status"] == "OVERTURNED"
    assert notice["credited_total_cents"] == 32956
