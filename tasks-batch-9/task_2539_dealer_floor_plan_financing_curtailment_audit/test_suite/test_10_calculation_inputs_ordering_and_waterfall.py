"""Arithmetic: which rows a sweep sees, how the ladder orders itself, and bucket order."""
from test_helpers import (
    AM,
    CO,
    api_client,
    assert_audit_scope_identity,
    assert_curtailment_obligation,
    assert_payment_remittance,
    assert_remittance_money_conservation,
    dealer_version,
    floor_unit,
    list_unit_obligations,
    make_dealer_principal_headers,
    read_credit_line,
    read_dealer,
    read_unit,
    record_observation,
    remittance_payload,
    run_curtailment,
    schedule_audit,
    setup_active_line,
    setup_floored_unit,
    setup_unit_with_delinquent_obligation,
    start_audit,
    unit_schedule,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}
NEW_TIER_MIDDLE = {
    "inventory_class": "NEW",
    "age_days_from": 180,
    "age_days_to": 270,
    "cumulative_paydown_bps": 2500,
}
NEW_TIER_EARLIEST = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": 180,
    "cumulative_paydown_bps": 1000,
}
NEW_TIER_LATEST = {
    "inventory_class": "NEW",
    "age_days_from": 270,
    "age_days_to": None,
    "cumulative_paydown_bps": 5000,
}


def test_a_sweep_dated_before_the_first_rung_matures_nothing():
    """The run date is 2026-09-01 and the only obligation falls due on 2026-10-30, so the sweep is inert.

    PRD: "An obligation in `SCHEDULED` whose `due_date` is at or before the run date matures to `DUE`: `became_due_at` is stamped from the logical clock, and `required_principal_cents` is written from the **assessed** variant of the curtailment requirement — the variant that reads what the dealership has actually paid."

    PRD: "Each count is exactly the number of rows that made the corresponding transition during this sweep."

    Design: Corner/calculations/curtailment_run_skips_a_unit_that_has_not_reached_its_first_tier_age
    """
    ctx = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNPRETIERUNIT01",
        unit_overrides={"invoice_amount_cents": 3000000},
        dealer_overrides={"legal_name": "Corner Pre Tier Motors LLC", "state_code": "AZ"},
    )
    dealer_id = ctx["dealer"]["id"]
    unit_id = ctx["unit"]["id"]

    summary = run_curtailment(dealer_id=dealer_id, as_of_date="2026-09-01")
    assert summary["dealer_ids_processed"] == [dealer_id]
    assert summary["obligations_marked_due_count"] == 0
    assert summary["obligations_marked_delinquent_count"] == 0
    assert summary["total_required_paydown_cents"] == 0
    assert summary["units_flagged_delinquent_count"] == 0
    assert summary["exceptions_expired_count"] == 0

    obligations = list_unit_obligations(unit_id)
    assert len(obligations) == 1
    obligation = obligations[0]
    assert_curtailment_obligation(obligation)
    assert obligation["status"] == "SCHEDULED"
    assert obligation["required_principal_cents"] == 0
    assert obligation["late_fee_cents"] == 0
    assert obligation["total_amount_due_cents"] == 0
    assert obligation["became_due_at"] is None
    assert obligation["version"] == 1
    assert obligation["projected_principal_cents"] == 300000
    assert str(obligation["due_date"])[:10] == "2026-10-30"

    assert read_unit(unit_id)["funding_status"] == "FLOORED"
    assert read_dealer(dealer_id)["delinquent_unit_count"] == 0


def test_the_ladder_reads_back_in_age_order_whatever_order_its_rungs_were_added():
    """Rungs added middle, earliest, latest still project 300,000 then 450,000 then 750,000.

    PRD: "For each ladder rung of the unit's line and `inventory_class` whose `cumulative_paydown_bps` is strictly greater than zero, taken in `age_days_from` ascending order, one obligation is created in `SCHEDULED`."

    PRD: "As a worked illustration: a unit floored at an advance of 3,000,000 cents against rungs of 1,000, 2,500 and 5,000 basis points at 90, 180 and 270 days yields cumulative figures of 300,000, 750,000 and 1,500,000 cents, and therefore projected requirements of 300,000, 450,000 and 750,000 cents on the three obligations."

    Design: Corner/calculations/curtailment_schedule_is_tier_ordered_regardless_of_tier_creation_order
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_MIDDLE, NEW_TIER_EARLIEST, NEW_TIER_LATEST],
        dealer_overrides={"legal_name": "Corner Ladder Motors LLC", "state_code": "CO"},
    )
    line_id = ctx["credit_line"]["id"]
    floored = floor_unit(
        ctx["dealer"]["id"],
        line_id,
        "CRNLADDERUNIT001",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=3000000,
        document_reference="MSO-C19",
        invoice_amount_cents=3000000,
    )
    unit_id = floored["unit"]["id"]

    schedule = unit_schedule(unit_id)
    assert schedule["advance_amount_cents"] == 3000000
    assert schedule["basis"] == "FORWARD_PROJECTED"
    assert schedule["projected_total_required_cents"] == 1500000
    rungs = schedule["projected_obligations"]
    assert len(rungs) == 3
    assert [rung["tier_age_days_from"] for rung in rungs] == [90, 180, 270]
    assert [rung["projected_principal_cents"] for rung in rungs] == [300000, 450000, 750000]
    assert [rung["tier_cumulative_paydown_bps"] for rung in rungs] == [1000, 2500, 5000]
    assert [str(rung["due_date"])[:10] for rung in rungs] == [
        "2026-10-30",
        "2027-01-28",
        "2027-04-28",
    ]

    rows, meta = validate_paginated(
        api_client.list_curtailment_obligations(CO, params={"unit_id": unit_id})
    )
    assert meta["total_count"] == 3
    assert [row["tier_age_days_from"] for row in rows] == [90, 180, 270]
    assert [row["projected_principal_cents"] for row in rows] == [300000, 450000, 750000]

    tiers, tier_meta = validate_paginated(
        api_client.list_curtailment_tiers(line_id, CO)
    )
    assert tier_meta["total_count"] == 3
    assert [tier["age_days_from"] for tier in tiers] == [90, 180, 270]
    assert [tier["cumulative_paydown_bps"] for tier in tiers] == [1000, 2500, 5000]


def test_a_late_payment_fills_the_fee_bucket_before_it_touches_principal():
    """300,000 cents against a 306,000 cent total pays the 6,000 fee first and 294,000 of principal.

    PRD: "The raw fee is `required_principal_cents` multiplied by 200 basis points (two percent) divided by 10,000; that raw figure is rounded half up to whole cents **before** the ceiling is applied, and the recorded `late_fee_cents` is the smaller of the rounded fee and the ceiling of 50,000 cents (five hundred dollars)."

    PRD: "A required principal of 300,000 cents therefore carries a fee of 6,000 and a total of 306,000; a required principal of 3,000,000 cents would carry an uncapped fee of 60,000, so the ceiling binds at 50,000 and the total is 3,050,000."

    PRD: "For each obligation in turn, the engine takes the smaller of the remaining balance and the fee gap (`late_fee_cents` minus `fee_paid_cents`), adding it to `fee_paid_cents` and to the remittance's `applied_fee_cents`; then the smaller of what is still remaining and the principal gap (`required_principal_cents` minus `principal_paid_cents`), adding it to `principal_paid_cents` and to `applied_principal_cents`, and simultaneously increasing the unit's `principal_paid_cents` and decreasing its `outstanding_principal_cents` by the same figure."

    Design: Corner/calculations/curtailment_remittance_consumes_the_late_fee_before_principal
    """
    ctx = setup_unit_with_delinquent_obligation(
        paydown_bps=1000,
        age_days_from=90,
        invoice_amount_cents=3000000,
        grace_days=5,
        vin_seed="CRNWATERFALLUNT1",
    )
    dealer_id = ctx["dealer"]["id"]
    unit_id = ctx["unit"]["id"]
    line_id = ctx["credit_line"]["id"]
    assert ctx["run"]["obligations_marked_due_count"] == 1
    assert ctx["delinquency_run"]["obligations_marked_delinquent_count"] == 1

    obligation = ctx["obligations"][0]
    assert obligation["status"] == "DELINQUENT"
    assert obligation["required_principal_cents"] == 300000
    assert obligation["late_fee_cents"] == 6000
    assert obligation["total_amount_due_cents"] == 306000

    remittance = validate_success(
        api_client.create_remittance(
            remittance_payload(
                dealer_id,
                "CURTAILMENT",
                300000,
                dealer_version(dealer_id),
                "PAY-C20",
                target_obligation_id=obligation["id"],
            ),
            make_dealer_principal_headers(dealer_id),
        ),
        201,
    )
    assert_payment_remittance(remittance)
    assert_remittance_money_conservation(remittance)
    assert remittance["status"] == "APPLIED"
    assert remittance["applied_fee_cents"] == 6000
    assert remittance["applied_principal_cents"] == 294000
    assert remittance["applied_sot_cure_cents"] == 0
    assert remittance["unapplied_cents"] == 0

    settled = validate_success(
        api_client.get_curtailment_obligation(obligation["id"], CO)
    )
    assert settled["fee_paid_cents"] == 6000
    assert settled["principal_paid_cents"] == 294000
    assert settled["status"] == "DELINQUENT"

    unit_after = read_unit(unit_id)
    assert unit_after["principal_paid_cents"] == 294000
    assert unit_after["outstanding_principal_cents"] == 2706000
    assert unit_after["funding_status"] == "DELINQUENT_CURTAILMENT"

    line = read_credit_line(line_id)
    assert line["outstanding_principal_cents"] == 2706000
    assert line["available_credit_cents"] == 497294000
    assert read_dealer(dealer_id)["unapplied_credit_cents"] == 0


def test_every_observed_condition_branch_lands_on_its_own_classification():
    """Four readings in one count produce four classifications and exactly one out-of-trust flag.

    PRD: "`classification` is `VERIFIED` when the unit was `PRESENT` and the title was verified; `TITLE_EXCEPTION` when the unit was `PRESENT` but the title was not verified; `DAMAGE_EXCEPTION` when the condition was `PRESENT_DAMAGED`; `WHOLESALE_EXCEPTION` when the condition was `WHOLESALED`; and `SOLD_OUT_OF_TRUST` when the condition was either `SOLD_NO_PAYOFF` or `MISSING`."

    PRD: "The audit's `units_verified_count` increments when the classification is `VERIFIED` and its `units_exception_count` increments otherwise, and `units_unobserved_count` decrements by 1 in either case, so the count-conservation identity of §2.12 holds after every single reading."

    PRD: "The observation row itself is immutable and carries no `version`; the unit is not mutated at all at this stage — nothing about a unit's eligibility or funding changes until the count is signed off."

    Design: Corner/calculations/observation_classification_maps_every_observed_condition_branch
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Branch Motors LLC", "state_code": "OR"},
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    units = [
        floor_unit(
            dealer_id,
            line_id,
            f"CRNBRANCHUNIT{index}",
            dealer_headers=ctx["dealer_headers"],
            requested_amount_cents=3000000,
            document_reference=f"MSO-C21-{index}",
            invoice_amount_cents=3000000,
        )["unit"]
        for index in range(1, 5)
    ]

    audit = schedule_audit(dealer_id, "2026-08-01", "2026-08-03", audit_type="UNANNOUNCED")
    opened = start_audit(audit["id"])
    assert opened["units_in_scope_count"] == 4
    assert opened["units_unobserved_count"] == 4

    verified = record_observation(audit["id"], units[0]["id"], "PRESENT", True)
    title_gap = record_observation(audit["id"], units[1]["id"], "PRESENT", False)
    damaged = record_observation(audit["id"], units[2]["id"], "PRESENT_DAMAGED", True)
    missing = record_observation(audit["id"], units[3]["id"], "MISSING", False)

    assert verified["classification"] == "VERIFIED"
    assert title_gap["classification"] == "TITLE_EXCEPTION"
    assert damaged["classification"] == "DAMAGE_EXCEPTION"
    assert missing["classification"] == "SOLD_OUT_OF_TRUST"
    assert verified["is_out_of_trust"] is False
    assert title_gap["is_out_of_trust"] is False
    assert damaged["is_out_of_trust"] is False
    assert missing["is_out_of_trust"] is True
    assert missing["unit_outstanding_principal_cents_at_observation"] == 3000000

    counted = validate_success(api_client.get_audit(audit["id"], AM))
    assert counted["units_verified_count"] == 1
    assert counted["units_exception_count"] == 3
    assert counted["units_unobserved_count"] == 0
    assert_audit_scope_identity(counted)

    _, incident_meta = validate_paginated(
        api_client.list_out_of_trust_incidents(CO, params={"audit_id": audit["id"]})
    )
    assert incident_meta["total_count"] == 0

    for unit in units:
        current = read_unit(unit["id"])
        assert current["funding_status"] == "FLOORED"
        assert current["eligibility_status"] == "ELIGIBLE"
