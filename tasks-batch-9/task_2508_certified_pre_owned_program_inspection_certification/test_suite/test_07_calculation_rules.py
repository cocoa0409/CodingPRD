"""Arithmetic of the programme: fee ladder, coverage clamps, reimbursement, sampling.

Four families of numbers decide what the programme costs and what it promises, and
each family has its own rounding discipline. Approving a certification prices a fee out
of the vehicle's whole years of age, its excess mileage in whole ten-thousand-mile
blocks, a percentage cap on the surcharge and a volume tier keyed on the dealer's
activation count before this approval. The same approval fixes a coverage window that
two lifetime caps measured from the vehicle's in-service date may clamp, and derives
the documentation retention deadline from the clamped end. Closing repairs aggregates a
reimbursement obligation that rounds per item and caps on the sum. Drawing an audit run
turns a pool size into a whole number of selections and a ranked order into a winner.
Every figure below is re-derived from the rule text and the seeded tunables, so these
tests pin each figure to the last cent, month and mile rather than to a status code.
"""

from test_helpers import (
    AGE_SURCHARGE_CENTS_PER_YEAR,
    AGE_SURCHARGE_FREE_YEARS,
    AUDIT_SAMPLE_MIN_PER_RUN,
    AUDIT_SAMPLE_PCT,
    BASE_FEE_CENTS,
    CLOCK_EPOCH,
    MILEAGE_SURCHARGE_CENTS_PER_10K,
    MILEAGE_SURCHARGE_FREE_MILES,
    RECON_REIMBURSEMENT_CAP_CENTS,
    SURCHARGE_CAP_PCT,
    active_certification,
    approve_certification,
    assert_audit_run_summary,
    assert_audit_sample,
    assert_calendar_date,
    assert_certification,
    assert_certification_number,
    assert_dealer,
    assert_dealer_ledger_conservation,
    assert_instant_equals,
    assert_reconditioning_item,
    audit_samples_of,
    bootstrap_program,
    ceil_count,
    certification_documents,
    complete_reconditioning,
    create_vehicle,
    days_between,
    draw_audit_run,
    floor_cents,
    ids_of,
    item_b1_payload,
    item_p1_payload,
    item_s1_payload,
    item_t1_payload,
    open_inspection_for,
    read_certification,
    read_config,
    read_dealer,
    read_inspection,
    reconditioning_item_for,
    record_finding,
    record_results,
    reimbursable_for,
    result_row,
    retune_config,
    set_clock,
    submit_inspection,
    submitted_certification,
    validate_paginated,
    waive_reconditioning,
)

#: The calendar date the logical clock reads before any request moves it.
ACTIVATION_DATE = "2026-08-01"
DAY_AFTER_EPOCH = "2026-08-02T00:00:00Z"

#: A young, low-mileage car: three whole years old at activation and inside the
#: 40000-mile free allowance, so both surcharge components come out at zero.
YOUNG_IN_SERVICE_DATE = "2023-05-10"

#: The canonical car of the fixtures: in service 2022-02-01 with 62000 miles.
CANONICAL_IN_SERVICE_DATE = "2022-02-01"

#: The per-item reconditioning ceilings the three repairable checklist points declare.
S1_ITEM_CAP_CENTS = 200000
B1_ITEM_CAP_CENTS = 100000
T1_ITEM_CAP_CENTS = 200000


def _young_vehicle(api, odometer_miles: int = 30000) -> dict:
    """A car in service on 2023-05-10, three whole years old at the epoch clock."""
    return create_vehicle(
        api,
        model_year=2023,
        in_service_date=YOUNG_IN_SERVICE_DATE,
        odometer_miles=odometer_miles,
    )


def _four_point_program(api):
    """A programme whose checklist carries a fourth repairable point, `T1`."""
    return bootstrap_program(
        api,
        items=[
            item_p1_payload(),
            item_s1_payload(),
            item_b1_payload(),
            item_t1_payload(),
        ],
    )


def _repairable_point_program(api):
    """A programme whose three checklist points are all curable by repair."""
    return bootstrap_program(
        api,
        items=[item_s1_payload(), item_b1_payload(), item_t1_payload()],
    )


def test_fee_floors_to_the_bare_base_fee_inside_both_free_allowances(api, program):
    """A car inside both free allowances is billed the bare base fee and nothing else.

    The car entered service on 2023-05-10 and is activated on 2026-08-01, which is
    1179 whole days, so floor(1179 / 365) is 3 whole years; three free years leave
    max(0, 3 - 3) == 0 chargeable years and a zero age component. Its 30000-mile
    worksheet reading is below the 40000-mile allowance, so max(0, 30000 - 40000) is
    0 excess miles, floor(0 / 10000) is 0 blocks, and the raw surcharge is 0 — far
    under the cap floor(89900 * 0.35) == 31465. The subtotal is therefore 89900, the
    dealer's pre-approval activation count of 0 selects the min_count 0 tier at 0.00,
    floor(89900 * 0.00) is a 0 discount, and 89900 is charged.

    PRD §3.7: "The raw surcharge is the age component plus the mileage component."
    PRD §3.7: "with a negative result treated as zero"
    PRD §3.7: "`fee_surcharge_cents` is the smaller of the raw surcharge and that cap"
    PRD §3.7: "`fee_charged_cents` is the subtotal minus `fee_discount_cents`."
    PRD §2.6: "`base_fee_cents` is 89900"

    Design: Corner/calculations/certification_fee_zero_surcharge_zero_discount
    """
    walk = submitted_certification(
        api, program, vehicle=_young_vehicle(api), odometer_at_inspection=30000
    )

    certification = approve_certification(api, walk.certification_id)

    assert_certification(certification)
    assert days_between(YOUNG_IN_SERVICE_DATE, ACTIVATION_DATE) == 1179
    assert floor_cents(1179 / 365) - AGE_SURCHARGE_FREE_YEARS == 0
    assert max(0, 30000 - MILEAGE_SURCHARGE_FREE_MILES) == 0
    assert floor_cents(BASE_FEE_CENTS * SURCHARGE_CAP_PCT) == 31465
    assert certification["status"] == "ACTIVE"
    assert certification["fee_surcharge_cents"] == 0
    assert certification["fee_discount_cents"] == 0
    assert certification["fee_charged_cents"] == 89900
    assert certification["fee_credited_cents"] == 0
    assert certification["program_config_version"] == 1
    assert certification["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert certification["warranty_start_date"] == "2026-08-01"
    assert certification["warranty_end_date"] == "2027-08-01"
    assert certification["warranty_end_miles"] == 42000
    assert certification["retention_expires_at"] == "2034-08-01"

    dealer = read_dealer(api, program.dealer_id)
    assert_dealer(dealer)
    assert dealer["lifetime_activated_count"] == 1
    assert dealer["fee_billed_cents_total"] == 89900
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == 89900


def test_mileage_surcharge_charges_whole_blocks_and_forgives_the_remainder(api, program):
    """Fifteen thousand excess miles buy exactly one whole block of surcharge.

    The worksheet reads 55000 miles, which is 15000 over the 40000-mile allowance;
    floor(15000 / 10000) is one whole block at 9000 cents, so the leftover 5000 miles
    are free. Pro-rating the partial block would bill 13500 and rounding it up would
    bill 18000. The age component is still 0 for a car three whole years old against
    three free years, so the raw surcharge is 9000, well under the 31465 cap, the
    subtotal is 89900 + 9000 == 98900, and the min_count 0 tier discounts nothing.

    PRD §3.7: "that excess divided by 10000 and rounded down"
    PRD §3.7: "so a car 4000 miles into a block contributes nothing for that partial block"
    PRD §2.6: "`mileage_surcharge_cents_per_10k` is 9000"
    PRD §3.7: "`warranty_end_miles` is the smaller of that figure"

    Design: Corner/calculations/mileage_surcharge_block_constant_floors_partial_block
    """
    walk = submitted_certification(
        api,
        program,
        vehicle=_young_vehicle(api, odometer_miles=55000),
        odometer_at_inspection=55000,
    )

    certification = approve_certification(api, walk.certification_id)

    excess_miles = max(0, 55000 - MILEAGE_SURCHARGE_FREE_MILES)
    assert excess_miles == 15000
    assert floor_cents(excess_miles / 10000) == 1
    assert certification["fee_surcharge_cents"] == 9000
    assert certification["fee_surcharge_cents"] == MILEAGE_SURCHARGE_CENTS_PER_10K
    assert certification["fee_discount_cents"] == 0
    assert certification["fee_charged_cents"] == 98900
    assert certification["program_config_version"] == 1
    assert certification["warranty_end_miles"] == 67000
    assert certification["warranty_start_date"] == "2026-08-01"
    assert certification["warranty_end_date"] == "2027-08-01"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_billed_cents_total"] == 98900
    assert_dealer_ledger_conservation(dealer)


def test_volume_tier_reads_the_activation_count_before_the_current_approval(api, program):
    """A tier ladder rung at min_count 1 discounts the second activation, not the first.

    With the ladder retuned to a 0.00 rung at min_count 0 and a 0.05 rung at
    min_count 1, the dealer's first approval reads a pre-approval activation count of
    0, selects the min_count 0 rung and pays the whole 89900 subtotal. Its second
    approval reads 1, selects the min_count 1 rung, and is discounted
    floor(89900 * 0.05) == 4495 down to 85405. Reading the counter after incrementing
    it would discount the very first certification a dealer ever activates.

    PRD §3.7: "as it stands immediately *before* this approval increments it"
    PRD §3.7: "the entry of the programme's tier list with the greatest `min_count`"
    PRD §3.7: "multiplied by the selected tier's `pct`, rounded down to whole cents"
    PRD §2.6: "Retuning is never retroactive."

    Design: Corner/calculations/volume_discount_tier_boundary_at_first_activation
    """
    config = retune_config(
        api,
        volume_discount_tiers=[
            {"min_count": 0, "pct": 0.0},
            {"min_count": 1, "pct": 0.05},
        ],
    )
    assert config["version"] == 2

    first = submitted_certification(
        api, program, vehicle=_young_vehicle(api), odometer_at_inspection=30000
    )
    second = submitted_certification(
        api, program, vehicle=_young_vehicle(api), odometer_at_inspection=30000
    )

    first_certification = approve_certification(api, first.certification_id)
    second_certification = approve_certification(api, second.certification_id)

    assert first_certification["fee_surcharge_cents"] == 0
    assert first_certification["fee_discount_cents"] == 0
    assert first_certification["fee_charged_cents"] == 89900
    assert floor_cents(89900 * 0.05) == 4495
    assert second_certification["fee_surcharge_cents"] == 0
    assert second_certification["fee_discount_cents"] == 4495
    assert second_certification["fee_charged_cents"] == 85405
    assert first_certification["program_config_version"] == 2
    assert second_certification["program_config_version"] == 2

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_activated_count"] == 2
    assert dealer["fee_billed_cents_total"] == 175305
    assert dealer["fee_balance_cents"] == 175305
    assert_dealer_ledger_conservation(dealer)


def test_coverage_and_retention_clamp_to_the_lifetime_caps(api, program, auditor_headers):
    """Both lifetime caps bite, and the retention deadline follows the clamped end.

    With the caps tightened to 60 months and 70000 miles, the canonical car — in
    service 2022-02-01 with 62000 miles — anchors on the certification because its
    36-month factory term expired 2025-02-01. The raw end 2026-08-01 plus 12 months
    is 2027-08-01 but the cap 2022-02-01 plus 60 months is 2027-02-01, and the earlier
    of the two wins. The raw end mileage 62000 + 12000 == 74000 loses to the 70000
    cap, and the interval is still non-empty because 70000 exceeds 62000. Retention is
    measured from the clamped end: 2027-02-01 plus seven years is 2034-02-01, which is
    stamped onto every retained document. The fee ladder is untouched: age
    floor(1642 / 365) == 4 whole years leaves one chargeable year at 12500, the 22000
    excess miles give floor(22000 / 10000) == 2 blocks at 9000, and 89900 + 30500 is
    120400.

    PRD §3.7: "`warranty_anchor_variant` is `CERTIFICATION_ANCHORED`"
    PRD §3.7: "`warranty_end_date` is the earlier of those two dates."
    PRD §3.7: "An absolute cap date is the vehicle's `in_service_date` advanced"
    PRD §3.7: "`retention_expires_at` is `warranty_end_date` advanced by the documentation"
    PRD §3.7: "stamps `retained_until` equal to `retention_expires_at` onto **every**"

    Design: Corner/calculations/warranty_coverage_clamped_by_total_caps
    """
    config = retune_config(api, warranty_total_cap_months=60, warranty_total_cap_miles=70000)
    assert config["version"] == 2
    walk = submitted_certification(api, program)

    certification = approve_certification(api, walk.certification_id)
    documents = certification_documents(api, walk.certification_id, auditor_headers)

    assert days_between(CANONICAL_IN_SERVICE_DATE, ACTIVATION_DATE) == 1642
    assert floor_cents(1642 / 365) - AGE_SURCHARGE_FREE_YEARS == 1
    assert floor_cents(max(0, 62000 - MILEAGE_SURCHARGE_FREE_MILES) / 10000) == 2
    assert certification["program_config_version"] == 2
    assert certification["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert certification["warranty_start_date"] == "2026-08-01"
    assert certification["warranty_end_date"] == "2027-02-01"
    assert certification["warranty_end_miles"] == 70000
    assert certification["retention_expires_at"] == "2034-02-01"
    assert_calendar_date(certification["warranty_end_date"], "warranty_end_date")
    assert certification["fee_surcharge_cents"] == 30500
    assert certification["fee_surcharge_cents"] == (
        AGE_SURCHARGE_CENTS_PER_YEAR + 2 * MILEAGE_SURCHARGE_CENTS_PER_10K
    )
    assert certification["fee_discount_cents"] == 0
    assert certification["fee_charged_cents"] == 120400

    assert len(documents) == 3
    for document_row in documents:
        assert document_row["retained_until"] == "2034-02-01"
        assert document_row["retained_until"] == certification["retention_expires_at"]


def test_reimbursement_total_is_capped_on_the_sum_not_per_repair(api):
    """Three repairs reimbursed at 60000 each are clamped to 150000 on the sum.

    Each of the three completed repairs costs 100000, so each reimburses
    round_half_up(100000 * 0.60) == 60000, and each per-item ceiling — 200000 for S1,
    100000 for B1, 200000 for T1 — is above that figure and never binds. After two
    completions the running total is the uncapped 120000; only the third pushes the raw
    sum to 180000, where the per-inspection ceiling of 150000 clamps it. Applying that
    ceiling per row instead, or forgetting it, would leave 180000 standing. The plain
    cost sum is 300000, and closing repairs never moves the inspection itself.

    PRD §3.5: "round that product half up to whole cents"
    PRD §3.5: "`total_recon_cost_cents` is the plain sum of `actual_cost_cents`"
    PRD §3.5: "The summed figure is then capped by the programme's per-inspection"
    PRD §2.9: "applied to each item *individually before* the items are summed"

    Design: Corner/calculations/reconditioning_reimbursement_total_clamped_by_cap
    """
    programme = _four_point_program(api)
    walk = open_inspection_for(api, programme, vehicle=_young_vehicle(api))
    record_results(
        api,
        walk.inspection_id,
        programme.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "FAIL", measured_value=2.0),
            result_row("T1", "FAIL"),
        ],
    )
    inspection = submit_inspection(api, walk.inspection_id, programme.dealer_headers)
    assert inspection["status"] == "RECONDITIONING_REQUIRED"
    assert inspection["failed_recon_count"] == 3

    safety = reconditioning_item_for(api, walk.inspection_id, "S1")
    brakes = reconditioning_item_for(api, walk.inspection_id, "B1")
    tires = reconditioning_item_for(api, walk.inspection_id, "T1")

    closed_safety = complete_reconditioning(
        api, safety["id"], 100000, programme.other_technician_headers
    )
    closed_brakes = complete_reconditioning(
        api, brakes["id"], 100000, programme.other_technician_headers
    )
    after_two = read_inspection(api, walk.inspection_id)
    closed_tires = complete_reconditioning(
        api, tires["id"], 100000, programme.other_technician_headers
    )
    after_three = read_inspection(api, walk.inspection_id)

    for closed, item_cap in (
        (closed_safety, S1_ITEM_CAP_CENTS),
        (closed_brakes, B1_ITEM_CAP_CENTS),
        (closed_tires, T1_ITEM_CAP_CENTS),
    ):
        assert_reconditioning_item(closed)
        assert closed["status"] == "COMPLETED"
        assert closed["actual_cost_cents"] == 100000
        assert closed["reimbursable_cents"] == 60000
        assert closed["reimbursable_cents"] == reimbursable_for(100000, item_cap)

    assert after_two["total_recon_cost_cents"] == 200000
    assert after_two["total_reimbursable_cents"] == 120000
    assert after_three["total_recon_cost_cents"] == 300000
    assert after_three["total_reimbursable_cents"] == 150000
    assert after_three["total_reimbursable_cents"] == RECON_REIMBURSEMENT_CAP_CENTS
    assert 60000 * 3 == 180000
    assert after_three["status"] == "RECONDITIONING_REQUIRED"


def test_reimbursement_counts_only_completed_repairs(api):
    """A waived repair and an outstanding repair both contribute nothing to the totals.

    One inspection holds all three repair statuses at once: a completed brake repair
    costing 1001 cents, a waived tyre repair whose cost stays null, and a still
    required safety repair. Only the completed row enters either aggregate, so the
    plain cost sum is exactly 1001 and the obligation is exactly
    round_half_up(1001 * 0.60) == round_half_up(600.6) == 601 — rounding the half cent
    down would publish 600 — which is far below the 100000 ceiling of the brake point,
    so the per-item minimum never binds. Summing every row, or treating the waived
    row's null cost as a zero-cost reimbursable row, cannot produce those two numbers.

    PRD §3.5: "A waived item keeps `actual_cost_cents` null and `reimbursable_cents` 0."
    PRD §3.5: "Waived repairs contribute nothing and never enter the sum"
    PRD §3.5: "outstanding repairs contribute nothing either"

    Design: Corner/calculations/reconditioning_reimbursement_excludes_waived_rows
    """
    programme = _repairable_point_program(api)
    walk = open_inspection_for(api, programme, vehicle=_young_vehicle(api))
    record_results(
        api,
        walk.inspection_id,
        programme.technician_headers,
        [
            result_row("S1", "FAIL"),
            result_row("B1", "FAIL", measured_value=2.0),
            result_row("T1", "FAIL"),
        ],
    )
    submit_inspection(api, walk.inspection_id, programme.dealer_headers)
    brakes = reconditioning_item_for(api, walk.inspection_id, "B1")
    tires = reconditioning_item_for(api, walk.inspection_id, "T1")
    completed = complete_reconditioning(
        api, brakes["id"], 1001, programme.other_technician_headers
    )

    waived = waive_reconditioning(api, tires["id"], "tire wear within regional tolerance")

    inspection = read_inspection(api, walk.inspection_id)
    response = api.list_reconditioning_items(
        walk.inspection_id, walk.dealer_headers, params={"status": "COMPLETED"}
    )
    completed_rows, meta = validate_paginated(response)

    assert_reconditioning_item(waived)
    assert waived["status"] == "WAIVED"
    assert waived["actual_cost_cents"] is None
    assert waived["reimbursable_cents"] == 0
    assert waived["waiver_reason"] == "tire wear within regional tolerance"

    assert completed["reimbursable_cents"] == 601
    assert completed["reimbursable_cents"] == reimbursable_for(1001, B1_ITEM_CAP_CENTS)
    assert inspection["total_recon_cost_cents"] == 1001
    assert inspection["total_reimbursable_cents"] == 601

    assert meta["total_count"] == 1
    assert ids_of(completed_rows) == [completed["id"]]

    still_required = reconditioning_item_for(api, walk.inspection_id, "S1")
    assert still_required["status"] == "REQUIRED"
    assert inspection["status"] == "RECONDITIONING_REQUIRED"


def test_audit_run_draws_the_ceiling_share_and_breaks_ties_on_activation(
    api, program, auditor_headers
):
    """A two-certification pool at equal risk selects exactly one, the earlier activation.

    Both certifications belong to one dealer whose risk score is 0, so the ranking
    falls through to the activation instant: the car activated on 2026-08-01 ranks
    ahead of the one activated on 2026-08-02. The count drawn is
    min(2, max(1, ceil(0.2 * 2))) == min(2, max(1, 1)) == 1 — flooring the 0.4 share
    would draw nothing at all — so the first-ranked certification is sampled and the
    second is ranked but left alone, still ACTIVE and still unsampled. Being selected
    is not a failure: the dealer's failure count and failure rate stay at zero.

    PRD §3.10: "the greater of the programme's per-run minimum (1 by default)"
    PRD §3.10: "the dealer's `risk_score` descending, then the certification's"
    PRD §3.10: "a `selection_rank` giving its 1-based position in the ranked order"
    PRD §2.9: "the audit sample count uses **ceiling**"

    Design: Corner/calculations/audit_run_ranks_pool_and_selects_one
    """
    first = active_certification(api, program)
    set_clock(api, DAY_AFTER_EPOCH)
    second = active_certification(api, program)

    run = draw_audit_run(api, auditor_headers)

    assert_audit_run_summary(run)
    assert run["pool_size"] == 2
    assert run["selected_count"] == 1
    assert run["selected_count"] == min(
        run["pool_size"],
        max(AUDIT_SAMPLE_MIN_PER_RUN, ceil_count(AUDIT_SAMPLE_PCT * run["pool_size"])),
    )
    assert run["selected_certification_ids"] == [first.certification_id]

    samples = audit_samples_of(api, first.certification_id, auditor_headers)
    assert len(samples) == 1
    assert_audit_sample(samples[0])
    assert samples[0]["selection_rank"] == 1
    assert samples[0]["status"] == "SELECTED"
    assert samples[0]["audit_run_id"] == run["audit_run_id"]
    assert samples[0]["finding_code"] is None
    assert samples[0]["reviewed_at"] is None
    assert samples[0]["reviewer_user_id"] is None

    sampled = read_certification(api, first.certification_id)
    assert sampled["status"] == "UNDER_AUDIT"
    assert sampled["audit_sampled"] is True
    assert sampled["audit_sample_count"] == 1
    assert_instant_equals(sampled["activated_at"], CLOCK_EPOCH, "activated_at")

    ranked_but_not_drawn = read_certification(api, second.certification_id)
    assert ranked_but_not_drawn["status"] == "ACTIVE"
    assert ranked_but_not_drawn["audit_sampled"] is False
    assert ranked_but_not_drawn["audit_sample_count"] == 0
    assert audit_samples_of(api, second.certification_id, auditor_headers) == []

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["audit_sample_count"] == 1
    assert dealer["audit_fail_count"] == 0
    assert dealer["audit_fail_rate"] == 0.0
    assert dealer["risk_score"] == 0


def test_audit_pool_excludes_sampled_and_never_activated_certifications(
    api, program, auditor_headers
):
    """The second run's pool holds one row: neither a cleared sample nor a submission.

    Three certifications sit under one dealer. The first is approved, drawn by a run
    of pool size 1 and cleared with a PASS finding, which returns it to ACTIVE while
    leaving its sampled flag true, so it is barred from every later pool. The second is
    deliberately left SUBMITTED and has never been activated at all. The third is
    approved only after the first run, so it has never been sampled — and it is the
    whole of the second run's pool of 1. Filtering on status alone would readmit the
    cleared certification and filtering on the flag alone would admit the submission.

    PRD §3.10: "whose `audit_sampled` flag is still false"
    PRD §3.10: "Certifications that are `SUBMITTED`, `UNDER_AUDIT`, `REJECTED`,"
    PRD §3.10: "a certification is sampled at most once in its life"
    PRD §3.10: "The certification returns `UNDER_AUDIT → ACTIVE`"
    PRD §3.2: "`audit_fail_rate` is the failure count divided by the sample count"

    Design: Corner/calculations/audit_run_pool_excludes_submitted_and_already_sampled
    """
    cleared = submitted_certification(api, program)
    never_activated = submitted_certification(api, program)
    late = submitted_certification(api, program)
    approve_certification(api, cleared.certification_id)

    first_run = draw_audit_run(api, auditor_headers)
    assert first_run["pool_size"] == 1
    assert first_run["selected_certification_ids"] == [cleared.certification_id]
    sample = audit_samples_of(api, cleared.certification_id, auditor_headers)[0]
    record_finding(api, sample["id"], "PASS", headers=auditor_headers)
    approve_certification(api, late.certification_id)

    second_run = draw_audit_run(api, auditor_headers)

    assert_audit_run_summary(second_run)
    assert second_run["pool_size"] == 1
    assert second_run["selected_count"] == 1
    assert second_run["selected_certification_ids"] == [late.certification_id]
    assert second_run["audit_run_id"] != first_run["audit_run_id"]

    cleared_row = read_certification(api, cleared.certification_id)
    assert cleared_row["status"] == "ACTIVE"
    assert cleared_row["audit_sampled"] is True
    submitted_row = read_certification(api, never_activated.certification_id)
    assert submitted_row["status"] == "SUBMITTED"
    assert submitted_row["activated_at"] is None
    assert submitted_row["audit_sampled"] is False
    late_row = read_certification(api, late.certification_id)
    assert late_row["status"] == "UNDER_AUDIT"
    assert late_row["audit_sampled"] is True

    cleared_samples = audit_samples_of(api, cleared.certification_id, auditor_headers)
    assert len(cleared_samples) == 1
    assert cleared_samples[0]["status"] == "PASSED"
    assert cleared_samples[0]["finding_code"] == "NONE"
    assert cleared_samples[0]["audit_run_id"] == first_run["audit_run_id"]
    assert_instant_equals(cleared_samples[0]["reviewed_at"], CLOCK_EPOCH, "reviewed_at")

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["audit_sample_count"] == 2
    assert dealer["audit_fail_count"] == 0
    assert dealer["audit_fail_rate"] == 0.0


def test_pinned_configuration_generation_survives_a_later_retune(api, program):
    """Two identical cars priced across a retune keep the generation each was approved under.

    The first certification is approved under the seeded generation and must keep
    89900 + 30500 == 120400, coverage to 2027-08-01, 74000 covered miles and retention
    to 2034-08-01 for good. The retune then lifts the base fee to 200000 and the
    extension to 24 months, publishing generation 2. The second certification pins that
    generation: its surcharge is the same 30500 — one chargeable year at 12500 plus two
    mileage blocks at 9000 — now under the wider cap floor(200000 * 0.35) == 70000, so
    it is charged 230500, and its coverage runs to 2026-08-01 plus 24 months ==
    2028-08-01, inside the untouched 84-month cap end of 2029-02-01, with retention at
    2035-08-01 and 74000 covered miles because the extension mileage was not retuned.
    The two rows differ by 110100 on identical cars.

    PRD §2.6: "it records the configuration `version` in force at that moment"
    PRD §2.6: "Each successful retune publishes a **new generation**"
    PRD §3.7: "the base fee (89900 cents by default) plus the *capped* `fee_surcharge_cents`"
    PRD §3.2: "`fee_billed_cents_total` sums the fee charged over every certification"

    Design: Corner/calculations/program_config_pinned_at_approval_survives_later_change
    """
    seeded = read_config(api)
    assert seeded["version"] == 1
    first = submitted_certification(api, program)
    second = submitted_certification(api, program)
    approve_certification(api, first.certification_id)

    retuned = retune_config(api, base_fee_cents=200000, warranty_extension_months=24)
    pinned = read_certification(api, first.certification_id)
    second_certification = approve_certification(api, second.certification_id)

    assert retuned["version"] == 2
    assert retuned["base_fee_cents"] == 200000
    assert retuned["warranty_extension_months"] == 24

    assert pinned["program_config_version"] == 1
    assert pinned["fee_surcharge_cents"] == 30500
    assert pinned["fee_charged_cents"] == 120400
    assert pinned["warranty_end_date"] == "2027-08-01"
    assert pinned["warranty_end_miles"] == 74000
    assert pinned["retention_expires_at"] == "2034-08-01"
    assert_certification_number(
        pinned["certification_number"], program.dealer["franchise_code"], 1
    )

    assert second_certification["program_config_version"] == 2
    assert second_certification["fee_surcharge_cents"] == 30500
    assert floor_cents(200000 * SURCHARGE_CAP_PCT) == 70000
    assert second_certification["fee_discount_cents"] == 0
    assert second_certification["fee_charged_cents"] == 230500
    assert second_certification["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED"
    assert second_certification["warranty_start_date"] == "2026-08-01"
    assert second_certification["warranty_end_date"] == "2028-08-01"
    assert second_certification["warranty_end_miles"] == 74000
    assert second_certification["retention_expires_at"] == "2035-08-01"
    assert second_certification["fee_charged_cents"] - pinned["fee_charged_cents"] == 110100
    assert_certification_number(
        second_certification["certification_number"], program.dealer["franchise_code"], 2
    )

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_billed_cents_total"] == 350900
    assert dealer["fee_balance_cents"] == 350900
    assert_dealer_ledger_conservation(dealer)
