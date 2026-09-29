"""The shipment's two independent status axes and the full-overturn cascade.

Billing walks the money axis, capture walks the classification axis, and a full
overturn is the one trigger that walks the classification axis backward while
pushing the money axis forward.
"""

from test_helpers import (
    assert_credit_memo,
    assert_dispute,
    assert_status_dimensions_independent,
    assert_strike_count_conserved,
    factories,
)
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"


def _unbilled_single_line_shipment():
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.setup_shipment_with_lines(env, "PRO5001", line_specs=[{}])
    scenario = dict(env)
    scenario.update(tendered)
    return scenario


def _two_line_disputed_scenario():
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_two_line_billed_shipment(
        env=env,
        pro_number="PRO8002",
        shipment_overrides={"bol_declared_total_weight_lb": 1100},
    )
    assert scenario["shipment"]["original_charge_cents"] == 26754
    fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        1300,
        [
            factories.line_measurement(1, 520, 48.0, 40.0, 48.0),
            factories.line_measurement(2, 780, 40.0, 40.0, 40.0),
        ],
    )
    draft = fx.find_draft_notice(scenario["shipment_id"])
    issued = fx.issue_notice(draft["id"])
    assert fx.get_shipment(scenario["shipment_id"])["assessed_total_cents"] == 61284
    dispute = fx.file_dispute(
        issued["id"],
        scenario["customer_id"],
        claim_basis="DEVICE_CALIBRATION",
        evidence_doc_count=2,
        claimed_class_code=70,
    )
    scenario["notice_id"] = issued["id"]
    scenario["dispute_id"] = dispute["id"]
    return scenario


# ==========================================================================
# The two axes advance on unrelated triggers
# ==========================================================================


def test_billing_moves_only_the_money_axis():
    """Billing takes `billing_status` to `BILLED` and leaves `class_status` `DECLARED`.

    PRD: "Billing a shipment leaves `class_status` untouched; capturing a shipment
    leaves `billing_status` untouched."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_dimensions_with_reclass_revert_on_overturn
    """
    scenario = _unbilled_single_line_shipment()
    assert_status_dimensions_independent(scenario["shipment"], "DECLARED", "UNBILLED")

    billed = fx.bill_shipment(scenario["shipment_id"])

    assert_status_dimensions_independent(billed, "DECLARED", "BILLED")
    assert billed["original_charge_cents"] == 12500, (
        f"the 12500 minimum charge binds on this shipment, "
        f"got {billed['original_charge_cents']}"
    )


def test_capture_moves_only_the_classification_axis():
    """A capture that fires the cascade takes `class_status` to `RECLASS_PENDING`
    while `billing_status` stays `BILLED`.

    PRD: "When either a reweigh condition or a class delta does result, the
    shipment advances `DECLARED → RECLASS_PENDING` on a first capture, or
    `CAPTURED → RECLASS_PENDING` on a later one, and the full cascade fires."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_dimensions_with_reclass_revert_on_overturn
    """
    scenario = _unbilled_single_line_shipment()
    fx.bill_shipment(scenario["shipment_id"])

    fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        520,
        fx.single_line_measurement(520),
    )
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert_status_dimensions_independent(shipment, "RECLASS_PENDING", "BILLED")


def test_full_overturn_walks_classification_backward_and_billing_forward():
    """Issuance advances both axes; the overturn then reverses only the
    classification axis and reverts the line to its declared class.

    PRD: "the shipment's `class_status` moves backward `RECLASSED → CAPTURED` —
    the reclassification is undone and the shipment returns to the
    measured-but-unreclassed state"

    Design: Difficulty/non_linear_state_machine/shipment_parallel_dimensions_with_reclass_revert_on_overturn
    """
    scenario = _unbilled_single_line_shipment()
    fx.bill_shipment(scenario["shipment_id"])
    fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        520,
        fx.single_line_measurement(520),
    )
    notice = fx.find_draft_notice(scenario["shipment_id"])
    fx.issue_notice(notice["id"])
    assert_status_dimensions_independent(
        fx.get_shipment(scenario["shipment_id"]), "RECLASSED", "REBILLED"
    )
    dispute = fx.file_dispute(
        notice["id"],
        scenario["customer_id"],
        claim_basis="DEVICE_CALIBRATION",
        evidence_doc_count=3,
    )

    fx.resolve_dispute(
        dispute["id"], "OVERTURNED", resolution_note="Scale ticket disproves the reweigh."
    )

    shipment = fx.get_shipment(scenario["shipment_id"])
    line = fx.get_shipment_line(scenario["line_ids"][0])
    assert_status_dimensions_independent(shipment, "CAPTURED", "CREDITED")
    assert line["found_class_code"] is None
    assert line["effective_class_code"] == 70
    assert line["classification_source"] == "BOL_DECLARED"
    assert line["measured_weight_lb"] == 520, (
        "the measurement itself survives the overturn; only the classification reverts"
    )
    assert fx.get_notice(notice["id"])["status"] == "OVERTURNED"
    assert shipment["assessed_total_cents"] == 12500
    assert shipment["open_notice_count"] == 0


# ==========================================================================
# The five-level overturn cascade
# ==========================================================================


def test_overturn_resolves_the_dispute_and_the_notice():
    """The dispute and the notice both move to their overturned terminal states.

    PRD: "A dispute may be resolved out of any of its three non-terminal states —
    `OPEN → RESOLVED` when the reviewer never asked for more,
    `SUPPLEMENT_REQUESTED → RESOLVED` when the reviewer decides without waiting
    for the shipper's answer, and `SUPPLEMENTED → RESOLVED` after the shipper
    answered — and in every case `outcome`, `outcome_class_code`,
    `reviewer_user_id` and `resolved_at` are recorded."

    Design: Difficulty/transitive_cascade/overturn_cascade_dispute_notice_memo_shipment_customer
    """
    scenario = _two_line_disputed_scenario()

    resolved = fx.resolve_dispute(
        scenario["dispute_id"],
        "OVERTURNED",
        resolution_note="Certified scale ticket disproves both the reweigh and the reclass.",
    )
    notice = fx.get_notice(scenario["notice_id"])

    assert_dispute(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["outcome"] == "OVERTURNED"
    assert resolved["reviewer_user_id"] == "rev-1"
    assert resolved["resolved_at"] is not None
    assert resolved["resolved_at"].startswith("2026-01-10T08:00:00")
    assert notice["status"] == "OVERTURNED"
    assert notice["applied_delta_cents"] == 30030, (
        "the frozen delta is never recomputed, not even by an overturn"
    )


def test_overturn_memo_is_priced_from_the_frozen_delta_across_three_buckets():
    """The freight bucket is the frozen delta, the fee bucket is the frozen fee and
    the interest bucket is derived from the freight bucket.

    PRD: "On a full overturn, `freight_credit_cents` is the notice's frozen
    `applied_delta_cents` in full."

    Design: Difficulty/transitive_cascade/overturn_cascade_dispute_notice_memo_shipment_customer
    """
    scenario = _two_line_disputed_scenario()

    fx.resolve_dispute(
        scenario["dispute_id"],
        "OVERTURNED",
        resolution_note="Certified scale ticket disproves both the reweigh and the reclass.",
    )
    memos = [
        memo
        for memo in fx.list_credit_memos_for(scenario["customer_id"])
        if memo["correction_notice_id"] == scenario["notice_id"]
    ]
    notice = fx.get_notice(scenario["notice_id"])

    assert len(memos) == 1, f"one memo per resolved overturn, found {len(memos)}"
    memo = memos[0]
    assert_credit_memo(memo)
    assert memo["reason"] == "FULL_OVERTURN"
    assert memo["freight_credit_cents"] == 30030
    assert memo["fee_credit_cents"] == 4500
    assert memo["interest_credit_cents"] == 150
    assert memo["amount_cents"] == 34680
    assert memo["customer_id"] == scenario["customer_id"]
    assert notice["credited_total_cents"] == 34680, (
        f"credited_total_cents sums amount_cents across the notice's memos, "
        f"got {notice['credited_total_cents']}"
    )


def test_overturn_returns_the_shipment_to_its_billed_total_and_clears_the_strike():
    """Both lines revert, the ledger returns to the original charge and the shipper's
    record goes back to a clean sheet.

    PRD: "the shipper's `offender_strike_count` is decremented before the indices,
    tier and window are recomputed. A fully overturned notice contributes to
    neither index thereafter."

    Design: Difficulty/transitive_cascade/overturn_cascade_dispute_notice_memo_shipment_customer
    """
    scenario = _two_line_disputed_scenario()

    fx.resolve_dispute(
        scenario["dispute_id"],
        "OVERTURNED",
        resolution_note="Certified scale ticket disproves both the reweigh and the reclass.",
    )
    shipment = fx.get_shipment(scenario["shipment_id"])
    line_one = fx.get_shipment_line(scenario["line_ids"][0])
    line_two = fx.get_shipment_line(scenario["line_ids"][1])
    customer = fx.get_customer(scenario["customer_id"])

    assert shipment["assessed_total_cents"] == 26754, (
        f"a full overturn returns the assessed total to the original charge, "
        f"got {shipment['assessed_total_cents']}"
    )
    assert shipment["billing_status"] == "CREDITED"
    assert shipment["class_status"] == "CAPTURED"
    assert shipment["open_notice_count"] == 0
    assert line_one["found_class_code"] is None
    assert line_one["effective_class_code"] == 70
    assert line_two["found_class_code"] is None
    assert line_two["effective_class_code"] == 100
    assert customer["offender_strike_count"] == 0
    assert customer["liability_index_rolling"] == 0.00
    assert customer["liability_index_lifetime"] == 0.00
    assert customer["dispute_window_days"] == 30
    assert_strike_count_conserved(customer, fx.list_notices_for(scenario["shipment_id"]))
