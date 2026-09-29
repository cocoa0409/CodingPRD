"""Allocating defense bills, and unwinding them again.

The frozen allocation method decides how much of a mixed bill is covered at all,
the grandparent policy's billing dimension decides whether the money may leave,
and a late denial has to put the limit ledger back exactly where it was.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADJUSTER,
    ApiErrorId,
    FIRST_ADJUSTER_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    advance_epoch,
    allocate_invoice_payload,
    assert_defense_invoice,
    assert_limit_conservation,
    coverage_decision_payload,
    make_claims_adjuster_headers,
    make_risk_manager_headers,
    notice_claim,
    premium_payment_payload,
    read_claim,
    read_coverage_parts,
    read_defense_invoices,
    read_layer,
    read_layers,
    read_policy,
    record_coverage_decision,
    set_clock,
    setup_bound_policy,
    setup_claim_with_coverage_accepted,
    setup_claim_with_submitted_invoice,
    setup_policy_with_claim,
    side_a_part,
    side_b_part,
    side_c_part,
    submit_defense_invoice,
    subscribe_layer,
)

# 400,000 billed = 150,000 covered + 200,000 mixed + 50,000 uncovered, defended
# for 3 insured persons and 1 entity, so the relative-exposure share is 3/4.
MIXED_BILL = {
    "billed_amount_usd": 400_000,
    "covered_matter_amount_usd": 150_000,
    "uncovered_matter_amount_usd": 50_000,
    "mixed_matter_amount_usd": 200_000,
    "insured_person_defendant_count": 3,
    "entity_defendant_count": 1,
}

FULLY_COVERED_BILL = {
    "law_firm_name": "Harrow & Blake LLP",
    "uncovered_matter_amount_usd": 0,
    "mixed_matter_amount_usd": 0,
    "insured_person_defendant_count": 3,
    "entity_defendant_count": 1,
}


def test_relative_exposure_pro_rates_the_mixed_bill_by_the_defendant_headcount(api):
    """PRD 3.8: "The relative-exposure share is `insured_person_defendant_count`
    divided by the sum of `insured_person_defendant_count` and
    `entity_defendant_count` ... Under `RELATIVE_EXPOSURE`, `covered_allocated_usd`
    is `covered_matter_amount_usd` plus `mixed_matter_amount_usd` multiplied by that
    share, rounded half-up to 2 decimal places: mixed work is pro-rated by the
    defendant headcount ratio, so only the insured-person fraction of the mixed
    amount becomes covered." "Under both methods, `uncovered_matter_amount_usd` is
    never advanced."

    Design: Difficulty/dual_variant_calc/defense_allocation_relative_exposure_vs_larger_settlement
    """
    scenario = setup_claim_with_submitted_invoice(
        allocation_method="RELATIVE_EXPOSURE",
        invoice_overrides=dict(MIXED_BILL, invoice_reference="HR-2026-0001"),
    )

    invoice = validate_success(
        api.allocate_defense_invoice(
            scenario["invoice"]["id"],
            allocate_invoice_payload(scenario["claim"]["version"]),
            ADJUSTER,
        ),
        200,
    )

    assert_defense_invoice(invoice)
    assert invoice["allocation_method_applied"] == "RELATIVE_EXPOSURE"
    # 150,000 + 200,000 x 3/4.
    assert invoice["covered_allocated_usd"] == pytest.approx(300_000.00, abs=0.01)
    assert invoice["retention_applied_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert invoice["advanced_usd"] == pytest.approx(50_000.00, abs=0.01)
    assert invoice["unfunded_excess_usd"] == pytest.approx(0.00, abs=0.01)
    assert invoice["status"] == "ADVANCED"
    assert invoice["covered_allocated_usd"] < 400_000, (
        "the uncovered 50,000 falls outside the covered amount under either method"
    )

    claim = read_claim(scenario["claim"]["id"])
    assert claim["status"] == "DEFENSE_ADVANCING"
    assert claim["retention_applied_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert claim["retention_remaining_usd"] == pytest.approx(0.00, abs=0.01)
    assert claim["advanced_defense_usd"] == pytest.approx(50_000.00, abs=0.01)

    parts = read_coverage_parts(scenario["policy"]["id"])
    assert side_b_part(parts)["eroded_usd"] == pytest.approx(50_000.00, abs=0.01)
    assert side_a_part(parts)["eroded_usd"] == pytest.approx(0.00, abs=0.01)
    assert side_c_part(parts)["eroded_usd"] == pytest.approx(0.00, abs=0.01), (
        "SIDE_C never funds defense cost under any claim type"
    )


def test_larger_settlement_takes_the_whole_mixed_bill_on_a_byte_identical_invoice(api):
    """PRD 3.8: "Under `LARGER_SETTLEMENT`, `covered_allocated_usd` is
    `covered_matter_amount_usd` plus the whole `mixed_matter_amount_usd` — a factor
    of 1.00 — rounded half-up to 2 decimal places, on the theory that the work would
    have been incurred to defend the covered insured persons regardless; for any
    invoice with a positive `mixed_matter_amount_usd` and a positive
    `entity_defendant_count` this method yields strictly more covered cost than the
    other."

    Design: Difficulty/dual_variant_calc/defense_allocation_relative_exposure_vs_larger_settlement
    """
    scenario = setup_policy_with_claim()
    policy_id = scenario["policy"]["id"]
    insured_id = scenario["insured"]["id"]

    relative = record_coverage_decision(
        scenario["claim"]["id"], "ACCEPT_WITH_ROR",
        allocation_method="RELATIVE_EXPOSURE",
    )
    relative_invoice = submit_defense_invoice(
        relative["id"], insured_id, **dict(MIXED_BILL, invoice_reference="HR-2026-0001")
    )
    validate_success(
        api.allocate_defense_invoice(
            relative_invoice["id"], allocate_invoice_payload(relative["version"]),
            ADJUSTER,
        ),
        200,
    )

    second_claim = notice_claim(
        policy_id, insured_id, claimant_name="Calder Retirement Trust",
        wrongful_act_date="2026-06-20T00:00:00Z", alleged_damages_usd=7_500_000,
    )
    larger = record_coverage_decision(
        second_claim["id"], "ACCEPT_WITH_ROR", allocation_method="LARGER_SETTLEMENT"
    )
    larger_invoice = submit_defense_invoice(
        larger["id"], insured_id, **dict(MIXED_BILL, invoice_reference="HR-2026-0002")
    )

    allocated = validate_success(
        api.allocate_defense_invoice(
            larger_invoice["id"], allocate_invoice_payload(larger["version"]),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        200,
    )

    assert allocated["allocation_method_applied"] == "LARGER_SETTLEMENT"
    assert allocated["covered_allocated_usd"] == pytest.approx(350_000.00, abs=0.01)
    assert allocated["retention_applied_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert allocated["advanced_usd"] == pytest.approx(100_000.00, abs=0.01)
    assert allocated["unfunded_excess_usd"] == pytest.approx(0.00, abs=0.01)
    assert allocated["status"] == "ADVANCED"
    # The only structural difference: the mixed bucket at (1 - 3/4).
    assert allocated["covered_allocated_usd"] - 300_000.00 == pytest.approx(
        50_000.00, abs=0.01
    )
    assert allocated["covered_allocated_usd"] < 400_000

    settled_wider = read_claim(second_claim["id"])
    assert settled_wider["status"] == "DEFENSE_ADVANCING"
    assert settled_wider["retention_remaining_usd"] == pytest.approx(0.00, abs=0.01)
    assert settled_wider["advanced_defense_usd"] == pytest.approx(100_000.00, abs=0.01)

    parts = read_coverage_parts(policy_id)
    assert side_b_part(parts)["eroded_usd"] == pytest.approx(150_000.00, abs=0.01)
    assert side_b_part(parts)["remaining_limit_usd"] == pytest.approx(
        9_850_000.00, abs=0.01
    )
    policy = read_policy(policy_id)
    assert policy["total_eroded_usd"] == pytest.approx(150_000.00, abs=0.01)
    assert policy["aggregate_remaining_usd"] == pytest.approx(9_850_000.00, abs=0.01)
    assert_limit_conservation(policy)


def _delinquent_policy_with_a_submitted_invoice():
    """A live policy the epoch advance has flagged DELINQUENT, carrying one claim in
    COVERAGE_ACCEPTED and one invoice still SUBMITTED."""
    scenario = setup_bound_policy()
    set_clock("2026-09-01T00:00:00Z")
    advance_epoch()
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    return setup_claim_with_submitted_invoice(
        policy_scenario=scenario, notice_clock=None,
        allocation_method="RELATIVE_EXPOSURE",
        invoice_overrides=dict(MIXED_BILL, law_firm_name="Harrow & Blake LLP",
                               invoice_reference="HB-2026-0001"),
    )


def test_a_delinquent_premium_blocks_advancement_on_the_grandparent_policy(api):
    """PRD 3.8: on allocation "the policy's `premium_status` must not be
    `DELINQUENT`, or it is refused with `ERR_PREMIUM_DELINQUENT`." PRD 3.6:
    "delinquency has teeth: while a policy is `DELINQUENT` no insurer money may
    leave it, so defense advancement on every claim of that policy is refused with
    `ERR_PREMIUM_DELINQUENT` at HTTP 402."

    Design: Difficulty/cross_entity_state_dependency/advance_blocked_by_delinquent_policy_premium
    """
    scenario = _delinquent_policy_with_a_submitted_invoice()
    policy_id = scenario["policy"]["id"]
    claim_id = scenario["claim"]["id"]
    claim_version = scenario["claim"]["version"]

    assert scenario["policy"]["premium_status"] == "DELINQUENT"
    assert scenario["policy"]["coverage_status"] == "ACTIVE"
    assert claim_version == 2, "created at 1, the coverage decision takes it to 2"

    # The invoice is SUBMITTED and the claim COVERAGE_ACCEPTED, so the only failing
    # precondition lives on the grandparent policy.
    validate_error(
        api.allocate_defense_invoice(
            scenario["invoice"]["id"], allocate_invoice_payload(claim_version), ADJUSTER
        ),
        ApiErrorId.ERR_PREMIUM_DELINQUENT,
        402,
    )

    blocked_invoice = read_defense_invoices(claim_id)[0]
    assert blocked_invoice["status"] == "SUBMITTED"
    assert (blocked_invoice.get("advanced_usd") or 0) == pytest.approx(0, abs=0.01)
    assert (blocked_invoice.get("covered_allocated_usd") or 0) == pytest.approx(
        0, abs=0.01
    )
    blocked_claim = read_claim(claim_id)
    assert blocked_claim["status"] == "COVERAGE_ACCEPTED"
    assert blocked_claim["retention_remaining_usd"] == pytest.approx(250_000, abs=0.01)
    assert blocked_claim["version"] == claim_version
    blocked_policy = read_policy(policy_id)
    assert blocked_policy["total_eroded_usd"] == pytest.approx(0, abs=0.01)
    assert blocked_policy["aggregate_remaining_usd"] == pytest.approx(
        10_000_000, abs=0.01
    )


def test_curing_the_premium_lets_the_identical_allocation_request_through(api):
    """PRD 3.6: "Payment is accepted while `premium_status` is `INVOICED` or
    `DELINQUENT`, so a late payer can still cure ... A successful payment sets
    `premium_status` to `PAID`, leaves `coverage_status` untouched, and increments
    the policy's `version` by 1." PRD 2.6: allocation "requires
    `expected_claim_version` ... If the submitted value does not equal the claim's
    current `version`, the allocation is rejected with `ERR_STALE_VERSION` and HTTP
    412", so a replay of the same value only succeeds because the refused attempt
    consumed nothing.

    Design: Difficulty/cross_entity_state_dependency/advance_blocked_by_delinquent_policy_premium
    """
    scenario = _delinquent_policy_with_a_submitted_invoice()
    policy_id = scenario["policy"]["id"]
    claim_version = scenario["claim"]["version"]

    validate_error(
        api.allocate_defense_invoice(
            scenario["invoice"]["id"], allocate_invoice_payload(claim_version), ADJUSTER
        ),
        ApiErrorId.ERR_PREMIUM_DELINQUENT,
        402,
    )

    cured = validate_success(
        api.create_premium_payment(
            policy_id,
            premium_payment_payload(scenario["policy"]["gross_premium_usd"]),
            make_risk_manager_headers(scenario["insured"]["id"]),
        ),
        200,
    )
    assert cured["premium_status"] == "PAID"
    assert cured["coverage_status"] == "ACTIVE"

    # The identical body, including the replayed expected_claim_version.
    retried = validate_success(
        api.allocate_defense_invoice(
            scenario["invoice"]["id"], allocate_invoice_payload(claim_version), ADJUSTER
        ),
        200,
    )
    assert retried["status"] == "ADVANCED"
    assert retried["allocation_method_applied"] == "RELATIVE_EXPOSURE"
    assert retried["covered_allocated_usd"] == pytest.approx(300_000.00, abs=0.01)
    assert retried["retention_applied_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert retried["advanced_usd"] == pytest.approx(50_000.00, abs=0.01)
    assert retried["unfunded_excess_usd"] == pytest.approx(0.00, abs=0.01)

    claim = read_claim(scenario["claim"]["id"])
    assert claim["status"] == "DEFENSE_ADVANCING"
    assert claim["retention_remaining_usd"] == pytest.approx(0.00, abs=0.01)
    assert claim["retention_applied_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert claim["advanced_defense_usd"] == pytest.approx(50_000.00, abs=0.01)
    assert claim["version"] == 3

    parts = read_coverage_parts(policy_id)
    assert side_b_part(parts)["eroded_usd"] == pytest.approx(50_000.00, abs=0.01)
    assert side_b_part(parts)["remaining_limit_usd"] == pytest.approx(
        9_950_000.00, abs=0.01
    )
    assert side_a_part(parts)["eroded_usd"] == pytest.approx(0.00, abs=0.01)
    assert side_c_part(parts)["eroded_usd"] == pytest.approx(0.00, abs=0.01)
    policy = read_policy(policy_id)
    assert policy["total_eroded_usd"] == pytest.approx(50_000.00, abs=0.01)
    assert policy["aggregate_remaining_usd"] == pytest.approx(9_950_000.00, abs=0.01)
    assert policy["tower_posture"] == "ERODED"


def _claim_that_has_exhausted_side_b(api):
    """A 5,000,000 policy under a contiguous two-band tower whose whole Side B limit
    has been advanced on one 5,250,000 fully covered bill, plus a second bill left
    SUBMITTED."""
    scenario = setup_bound_policy(
        submission_overrides={
            "requested_limit_usd": 5_000_000,
            "requested_side_c_sublimit_usd": 0,
            "requested_program_target_limit_usd": 10_000_000,
        },
        quote_overrides={
            "offered_limit_usd": 5_000_000,
            "offered_side_c_sublimit_usd": 0,
        },
    )
    policy_id = scenario["policy"]["id"]
    scenario["primary_layer"] = subscribe_layer(
        policy_id, carrier_name="Meridian Primary", attachment_point_usd=0,
        limit_usd=5_000_000, participation_pct=1.00,
    )
    scenario["excess_layer"] = subscribe_layer(
        policy_id, carrier_name="Northgate Excess", attachment_point_usd=5_000_000,
        limit_usd=5_000_000, participation_pct=1.00,
        underlying_layer_id=scenario["primary_layer"]["id"],
    )
    scenario = setup_claim_with_coverage_accepted(
        policy_scenario=scenario, allocation_method="RELATIVE_EXPOSURE"
    )
    insured_id = scenario["insured"]["id"]
    invoice_a = submit_defense_invoice(
        scenario["claim"]["id"], insured_id, invoice_reference="HB-2026-0007",
        billed_amount_usd=5_250_000, covered_matter_amount_usd=5_250_000,
        **FULLY_COVERED_BILL,
    )
    scenario["invoice_a"] = validate_success(
        api.allocate_defense_invoice(
            invoice_a["id"], allocate_invoice_payload(scenario["claim"]["version"]),
            ADJUSTER,
        ),
        200,
    )
    scenario["invoice_b"] = submit_defense_invoice(
        scenario["claim"]["id"], insured_id, invoice_reference="HB-2026-0008",
        billed_amount_usd=100_000, covered_matter_amount_usd=100_000,
        **FULLY_COVERED_BILL,
    )
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    scenario["policy"] = read_policy(policy_id)
    return scenario


def test_the_advancement_exhausts_side_b_and_the_primary_layer_beneath_it(api):
    """PRD 3.8: "the invoice's `retention_applied_usd` is the lesser of the claim's
    `retention_remaining_usd` and the covered amount ... Second the policy's `SIDE_B`
    part, when `SIDE_B` is eligible and that part exists and is `ACTIVE`: it absorbs
    the lesser of its `remaining_limit_usd` and what remains, raising its
    `eroded_usd` and lowering its `remaining_limit_usd` accordingly." PRD 2.9 fixes
    the conservation identity that a policy's `shared_aggregate_limit_usd` equals its
    `aggregate_remaining_usd` plus its `total_eroded_usd`.

    Design: Difficulty/compensating_invariant/denial_clawback_restores_limit_conservation
    """
    scenario = _claim_that_has_exhausted_side_b(api)
    policy = scenario["policy"]

    assert policy["total_eroded_usd"] == pytest.approx(5_000_000.00, abs=0.01)
    assert policy["aggregate_remaining_usd"] == pytest.approx(0.00, abs=0.01)
    assert policy["tower_posture"] == "ERODED"
    assert policy["open_claim_count"] == 1
    assert_limit_conservation(policy)

    parts = read_coverage_parts(policy["id"])
    assert side_b_part(parts)["eroded_usd"] == pytest.approx(5_000_000.00, abs=0.01)
    assert side_b_part(parts)["remaining_limit_usd"] == pytest.approx(0.00, abs=0.01)
    assert side_b_part(parts)["status"] == "EXHAUSTED"
    assert side_a_part(parts)["eroded_usd"] == pytest.approx(0.00, abs=0.01)
    assert side_a_part(parts)["status"] == "ACTIVE"

    assert read_layer(scenario["primary_layer"]["id"])["status"] == "EXHAUSTED"
    assert read_layer(scenario["excess_layer"]["id"])["status"] == "ATTACHED", (
        "the excess band attaches at 5,000,000, which the erosion has only reached"
    )

    invoice = scenario["invoice_a"]
    assert invoice["covered_allocated_usd"] == pytest.approx(5_250_000.00, abs=0.01)
    assert invoice["retention_applied_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert invoice["advanced_usd"] == pytest.approx(5_000_000.00, abs=0.01)
    assert invoice["unfunded_excess_usd"] == pytest.approx(0.00, abs=0.01)
    assert invoice["status"] == "ADVANCED"

    claim = scenario["claim"]
    assert claim["status"] == "DEFENSE_ADVANCING"
    assert claim["advanced_defense_usd"] == pytest.approx(5_000_000.00, abs=0.01)
    assert claim["retention_applied_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert claim["retention_remaining_usd"] == pytest.approx(0.00, abs=0.01)


def test_a_late_denial_restores_the_limit_ledger_to_its_exact_prior_value(api):
    """PRD 3.8: "Every defense invoice of the claim in `ADVANCED` moves `ADVANCED →
    CLAWED_BACK` and every invoice still in `SUBMITTED` moves `SUBMITTED → VOIDED`,
    and a voided invoice can never be allocated. Each clawed-back invoice reverses
    its `advanced_usd` from the coverage part it eroded, restoring that part's
    `eroded_usd` and `remaining_limit_usd` and returning an `EXHAUSTED` part to
    `ACTIVE` when its `eroded_usd` falls back below its `limit_usd` ... and returns
    every layer whose `attachment_point_usd` is greater than or equal to the restored
    `total_eroded_usd` from `EXHAUSTED` back to `ATTACHED`. Finally the claim's own
    ledger resets: `advanced_defense_usd` to 0, `retention_applied_usd` to 0, and
    `retention_remaining_usd` back to the policy's `retention_usd`."

    Design: Difficulty/compensating_invariant/denial_clawback_restores_limit_conservation
    """
    scenario = _claim_that_has_exhausted_side_b(api)
    policy_id = scenario["policy"]["id"]
    claim_id = scenario["claim"]["id"]

    denied = validate_success(
        api.create_coverage_decision(
            claim_id,
            coverage_decision_payload("DENY", denial_reason="CONDUCT_EXCLUSION"),
            make_claims_adjuster_headers(FIRST_ADJUSTER_USER_ID),
        ),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "CONDUCT_EXCLUSION"

    invoices = {i["invoice_reference"]: i for i in read_defense_invoices(claim_id)}
    assert invoices["HB-2026-0007"]["status"] == "CLAWED_BACK"
    assert invoices["HB-2026-0008"]["status"] == "VOIDED", (
        "the never-allocated invoice is closed off rather than left available"
    )

    claim = read_claim(claim_id)
    assert claim["advanced_defense_usd"] == pytest.approx(0.00, abs=0.01)
    assert claim["retention_applied_usd"] == pytest.approx(0.00, abs=0.01)
    assert claim["retention_remaining_usd"] == pytest.approx(250_000.00, abs=0.01)
    assert claim["unfunded_excess_usd"] == pytest.approx(0.00, abs=0.01)

    parts = read_coverage_parts(policy_id)
    assert side_b_part(parts)["eroded_usd"] == pytest.approx(0.00, abs=0.01)
    assert side_b_part(parts)["remaining_limit_usd"] == pytest.approx(
        5_000_000.00, abs=0.01
    )
    assert side_b_part(parts)["status"] == "ACTIVE", (
        "an EXHAUSTED part is restored, not merely credited"
    )

    policy = read_policy(policy_id)
    assert policy["total_eroded_usd"] == pytest.approx(0.00, abs=0.01), (
        "back on its exact pre-advancement value, with no rounding drift"
    )
    assert policy["aggregate_remaining_usd"] == pytest.approx(5_000_000.00, abs=0.01)
    assert_limit_conservation(policy)
    assert policy["tower_posture"] == "CONTIGUOUS", (
        "re-derived, not left at ERODED and not collapsed to INCOMPLETE"
    )
    assert policy["open_claim_count"] == 0
    assert {layer["status"] for layer in read_layers(policy_id)} == {"ATTACHED"}

    # No second reversal can double-credit the ledger.
    validate_error(
        api.allocate_defense_invoice(
            scenario["invoice_b"]["id"], allocate_invoice_payload(claim["version"]),
            ADJUSTER,
        ),
        ApiErrorId.ERR_INVALID_CLAIM_STATE,
        409,
    )
