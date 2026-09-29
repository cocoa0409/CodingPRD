"""One effective appraisal reduction, four denormalized targets, and no
reconciliation between the write and the read that follows it.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import COMMITTEE_OFFICER, MASTER_SERVICER, TRUSTEE


def _a_loan_carrying_one_provisional_reduction(api):
    """A 10,000,000.00 loan whose accepted UPDATE appraisal reports 6,000,000.00.

    Returns ``{trust_id, loan_id, reduction}``.
    """
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={
            "deal_name": "CMBS 2026-V48",
            "closing_date": "2026-01-15T00:00:00Z",
            "original_controlling_class_balance_usd": 40000000,
        },
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V48", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=fx.record_bankruptcy_event,
    )
    fx.accepted_appraisal(
        api,
        built["loan_id"],
        value_usd=6000000,
        as_of_date="2026-07-01T00:00:00Z",
        ordered_on="2026-06-20T00:00:00Z",
        appraiser_firm="Meridian Valuation",
    )
    reductions, meta = validate_paginated(
        api.list_appraisal_reductions(
            COMMITTEE_OFFICER, {"loan_id": built["loan_id"], "status": "PROVISIONAL"}
        )
    )
    assert meta["total_count"] == 1, "accepting one appraisal creates one reduction"
    built["reduction"] = reductions[0]
    return built


def test_the_first_read_after_the_cascade_already_carries_every_target(api):
    """Nothing lags: all four denormalized figures are right on the next read.

    The PRD: "First, the loan's `ara_amount_usd` is set to the reduction's
    `ara_amount_usd` and the loan's `required_monthly_pi_advance_usd` is recomputed.
    Second — caused by the first — the trust's `total_ara_usd` is recomputed, which
    in turn recomputes `controlling_class_notional_usd`."

    Design: Corner/consistency_model/every_cascade_target_is_readable_in_the_same_request_sequence
    """
    built = _a_loan_carrying_one_provisional_reduction(api)
    reduction = built["reduction"]
    a.assert_money(reduction["ara_amount_usd"], 4600000.00, "ara_amount_usd")
    a.assert_money(reduction["deficiency_base_usd"], 10000000.00, "deficiency_base_usd")
    a.assert_money(reduction["appraisal_credit_usd"], 5400000.00, "appraisal_credit_usd")
    a.assert_ara_percentage(reduction["ara_percentage"], 46.0000)
    a.assert_status(reduction, "GROSS_APPRAISED_BASIS", "calculation_basis")

    loan_before = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan_before["ara_amount_usd"], 0.00, "loan.ara_amount_usd")
    a.assert_money(
        loan_before["required_monthly_pi_advance_usd"],
        65000.00,
        "loan.required_monthly_pi_advance_usd",
    )
    trust_before = fx.read_trust(api, built["trust_id"], TRUSTEE)
    a.assert_money(trust_before["total_ara_usd"], 0.00, "trust.total_ara_usd")
    a.assert_money(
        trust_before["controlling_class_notional_usd"],
        40000000.00,
        "trust.controlling_class_notional_usd",
    )
    a.assert_status(trust_before, "CONTROLLING", "control_status")

    effective = validate_success(
        api.set_appraisal_reduction_status(
            reduction["id"], f.status_payload("EFFECTIVE"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(effective, "EFFECTIVE")
    assert effective["effective_on"].startswith("2026-08-01")
    assert effective["made_effective_by_user_id"] == "cmte-001"
    assert effective["advance_reduction_applies"] is True
    a.assert_money(effective["ara_amount_usd"], 4600000.00, "ara_amount_usd")

    loan_after = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan_after["ara_amount_usd"], 4600000.00, "loan.ara_amount_usd")
    a.assert_money(
        loan_after["required_monthly_pi_advance_usd"],
        35100.00,
        "loan.required_monthly_pi_advance_usd",
    )
    trust_after = fx.read_trust(api, built["trust_id"], TRUSTEE)
    a.assert_money(trust_after["total_ara_usd"], 4600000.00, "trust.total_ara_usd")
    a.assert_money(
        trust_after["controlling_class_notional_usd"],
        35400000.00,
        "trust.controlling_class_notional_usd",
    )
    a.assert_status(trust_after, "CONTROLLING", "control_status")

    loan_reread = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    trust_reread = fx.read_trust(api, built["trust_id"], TRUSTEE)
    assert loan_reread == loan_after, (
        "the second read of the loan returns exactly the first read: nothing converged"
    )
    assert trust_reread == trust_after, (
        "the second read of the trust returns exactly the first read"
    )


def test_the_reduced_obligation_governs_the_very_next_write(api):
    """The new ceiling was in force for a write, not only for a read.

    The PRD: "A `PI_ADVANCE` may not exceed the loan's
    `required_monthly_pi_advance_usd`; one that does is refused with
    `ERR_ADVANCE_EXCEEDS_ARA_ADJUSTED_OBLIGATION`. The comparison is inclusive, so
    an amount exactly equal to the obligation is permitted and a single cent more
    is not — and since the obligation shrinks the moment an appraisal reduction
    becomes effective, an advance that would have been fine yesterday can be
    refused today."

    Design: Corner/consistency_model/every_cascade_target_is_readable_in_the_same_request_sequence
    """
    built = _a_loan_carrying_one_provisional_reduction(api)
    fx.make_reduction_effective(api, built["reduction"]["id"])

    advance = validate_success(
        api.create_advance(
            f.advance_payload(
                built["loan_id"],
                advance_type="PI_ADVANCE",
                amount_usd=35100,
                advanced_on="2026-08-01T00:00:00Z",
            ),
            MASTER_SERVICER,
        ),
        201,
    )
    a.assert_status(advance, "OUTSTANDING")
    a.assert_money(advance["amount_usd"], 35100.00, "advance.amount_usd")

    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan["advances_outstanding_usd"], 35100.00, "loan.advances_outstanding_usd")
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        35100.00,
        "loan.required_monthly_pi_advance_usd",
    )
    a.assert_money(loan["ara_amount_usd"], 4600000.00, "loan.ara_amount_usd")

    trust = fx.read_trust(api, built["trust_id"], TRUSTEE)
    a.assert_money(
        trust["total_advances_outstanding_usd"],
        35100.00,
        "trust.total_advances_outstanding_usd",
    )
    a.assert_money(trust["total_ara_usd"], 4600000.00, "trust.total_ara_usd")
