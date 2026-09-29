"""Run computation: the two variants, the participant set and the reopen round trip."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ApiErrorId,
    assert_allocation_line,
    assert_cents,
    assert_invoice_dimensions,
    assert_invoice_ledger,
    assert_shares_sum_to_pool,
    find_by,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import AUGUST_FIFTH_UTC


def _discounted_july_model(api):
    """Two units, three commitment-discounted records and one pooled storage record.

    A resource-less 5001-cent storage record is absorbed into a sealed headcount
    pool on a `DRAFT` `CHARGEBACK` run covering the same July period, so the run
    carries both direct and shared cost when it is computed.
    """
    built = fixtures.discounted_compute_model(api, untagged_cents=5001)
    built.update(
        fixtures.headcount_pool_chargeback_run(
            api,
            [built["platform"]["id"], built["data"]["id"]],
            [built["untagged"]["id"]],
            variant=None,
        )
    )
    return built


def _lines_of(api, run_id):
    lines, meta = validate_paginated(
        api.list_allocation_lines(ANALYST_HEADERS, {"allocation_run_id": run_id})
    )
    return lines, meta


def test_the_provisional_total_overshoots_the_effective_cost_by_the_whole_discount(api):
    """Direct lines are struck at list cost while the pooled cents stay net.

    PRD §3.5: "Under `PROVISIONAL`, a direct record's basis amount is its
    `list_cost_cents`, so direct lines are struck at undiscounted list cost and
    carry `method_applied` of `LIST_BASIS`; commitment discounts are
    deliberately not recognised, and `total_allocated_cents` therefore exceeds
    `scoped_effective_cost_cents` by exactly the commitment discount resting on
    the run's records."

    Design: Difficulty/dual_variant_calc/allocation_run_provisional_vs_final_total_divergence
    """
    built = _discounted_july_model(api)
    run_id = built["run"]["id"]

    provisional = validate_success(api.compute_allocation_run(run_id, "PROVISIONAL", ANALYST_HEADERS))
    assert provisional["status"] == "COMPUTED_PROVISIONAL"
    assert provisional["variant_applied"] == "PROVISIONAL"
    assert_cents(provisional["total_allocated_cents"], 35301, "total_allocated_cents")
    assert_cents(provisional["scoped_effective_cost_cents"], 26967, "scoped_effective_cost_cents")
    assert provisional["line_count"] == 4

    lines, meta = _lines_of(api, run_id)
    assert meta["total_count"] == 4

    platform_direct = find_by(lines, line_kind="DIRECT", business_unit_id=built["platform"]["id"])
    assert_allocation_line(platform_direct, "DIRECT", "LIST_BASIS", 20200, basis_value=0.00)
    data_direct = find_by(lines, line_kind="DIRECT", business_unit_id=built["data"]["id"])
    assert_allocation_line(data_direct, "DIRECT", "LIST_BASIS", 10100, basis_value=0.00)

    platform_shared = find_by(lines, line_kind="SHARED", business_unit_id=built["platform"]["id"])
    assert_allocation_line(
        platform_shared, "SHARED", "PROPORTIONAL", 4001, basis_value=40.00,
        rounding_remainder_cents=1,
    )
    data_shared = find_by(lines, line_kind="SHARED", business_unit_id=built["data"]["id"])
    assert_allocation_line(
        data_shared, "SHARED", "PROPORTIONAL", 1000, basis_value=10.00,
        rounding_remainder_cents=0,
    )
    assert_shares_sum_to_pool([platform_shared, data_shared], 5001)

    commitment = validate_success(
        api.get_commitment(built["commitment"]["id"], CONTROLLER_HEADERS)
    )
    overshoot = provisional["total_allocated_cents"] - provisional["scoped_effective_cost_cents"]
    assert_cents(overshoot, commitment["total_discount_cents"], "provisional overshoot")
    assert_cents(overshoot, 8334, "provisional overshoot")


def test_recomputing_the_same_run_on_the_final_basis_reconciles_it_exactly(api):
    """The second compute rebuilds the direct lines net of the same discount.

    PRD §3.5: "Under `FINAL`, a direct record's basis amount is its
    `effective_cost_cents`, so direct lines are struck net of commitment
    discount and carry `method_applied` of `EFFECTIVE_BASIS`;
    `total_allocated_cents` then satisfies the compensating invariant and equals
    `scoped_effective_cost_cents` exactly."

    Design: Difficulty/dual_variant_calc/allocation_run_provisional_vs_final_total_divergence
    """
    built = _discounted_july_model(api)
    run_id = built["run"]["id"]

    provisional = validate_success(api.compute_allocation_run(run_id, "PROVISIONAL", ANALYST_HEADERS))
    assert_cents(provisional["total_allocated_cents"], 35301, "total_allocated_cents")

    final = validate_success(api.compute_allocation_run(run_id, "FINAL", ANALYST_HEADERS))
    assert final["status"] == "COMPUTED_FINAL"
    assert final["variant_applied"] == "FINAL"
    assert_cents(final["total_allocated_cents"], 26967, "total_allocated_cents")
    assert_cents(final["scoped_effective_cost_cents"], 26967, "scoped_effective_cost_cents")
    assert final["line_count"] == 4
    assert_cents(
        provisional["total_allocated_cents"] - final["total_allocated_cents"], 8334, "divergence"
    )

    lines, meta = _lines_of(api, run_id)
    assert meta["total_count"] == 4

    platform_direct = find_by(lines, line_kind="DIRECT", business_unit_id=built["platform"]["id"])
    assert_allocation_line(platform_direct, "DIRECT", "EFFECTIVE_BASIS", 14644)
    data_direct = find_by(lines, line_kind="DIRECT", business_unit_id=built["data"]["id"])
    assert_allocation_line(data_direct, "DIRECT", "EFFECTIVE_BASIS", 7322)

    platform_shared = find_by(lines, line_kind="SHARED", business_unit_id=built["platform"]["id"])
    assert_allocation_line(platform_shared, "SHARED", "PROPORTIONAL", 4001)
    data_shared = find_by(lines, line_kind="SHARED", business_unit_id=built["data"]["id"])
    assert_allocation_line(data_shared, "SHARED", "PROPORTIONAL", 1000)

    for record in built["records"]:
        stored = validate_success(api.get_cost_record(record["id"], ANALYST_HEADERS))
        assert_cents(stored["effective_cost_cents"], 7322, "effective_cost_cents")


def test_suspending_the_only_pool_participant_makes_the_next_compute_refuse(api):
    """One eligible participant allocates the whole pool; zero refuses the run.

    PRD §3.5: "Every compute requires that every shared cost pool attached to
    the run have at least one eligible participant, and a pool whose participant
    set contains no `ACTIVE` business unit at compute time fails the run with
    `ERR_NO_ELIGIBLE_PARTICIPANTS` at HTTP 422."

    Design: Difficulty/boundary_precision_check/shared_pool_eligible_participant_set_drops_from_one_to_zero
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    owning = fixtures.direct_cost_unit(api)
    shared_unit = fixtures.create_chargeback_unit(api, "Shared BU", "CC-600", headcount=4)
    untagged = fixtures.create_untagged_record(api, 5000)

    run = fixtures.create_run(api, mode="CHARGEBACK")
    pool = fixtures.create_pool(
        api, run["id"], [shared_unit["id"]], name="storage-untagged", methodology="EVEN_SPLIT"
    )
    fixtures.absorb(api, pool["id"], [untagged["id"]])
    fixtures.seal(api, pool["id"])

    provisional = validate_success(api.compute_allocation_run(run["id"], "PROVISIONAL", ANALYST_HEADERS))
    assert_cents(provisional["total_allocated_cents"], 15000, "total_allocated_cents")
    assert provisional["line_count"] == 2

    lines, _ = _lines_of(api, run["id"])
    shared_line = find_by(lines, line_kind="SHARED")
    assert_allocation_line(
        shared_line, "SHARED", "EVEN_SPLIT", 5000, rounding_remainder_cents=0
    )
    assert shared_line["business_unit_id"] == shared_unit["id"]
    direct_line = find_by(lines, line_kind="DIRECT")
    assert direct_line["business_unit_id"] == owning["unit"]["id"]

    suspended = validate_success(
        api.patch_business_unit(shared_unit["id"], {"status": "SUSPENDED"}, ADMIN_HEADERS)
    )
    assert suspended["status"] == "SUSPENDED"

    refused = api.compute_allocation_run(run["id"], "FINAL", ANALYST_HEADERS)
    validate_error(refused, ApiErrorId.NO_ELIGIBLE_PARTICIPANTS.value, 422)

    untouched = validate_success(api.get_allocation_run(run["id"], ANALYST_HEADERS))
    assert untouched["status"] == "COMPUTED_PROVISIONAL"
    assert untouched["variant_applied"] == "PROVISIONAL"
    assert_cents(untouched["total_allocated_cents"], 15000, "total_allocated_cents")

    _, after_refusal = _lines_of(api, run["id"])
    assert after_refusal["total_count"] == 2


def test_reactivating_the_participant_lets_the_final_compute_through(api):
    """The refusal is a live read of the participant's status, not a stored verdict.

    PRD §3.5: "The participant list is first filtered to business units whose
    `status` is `ACTIVE`; an empty result is the `ERR_NO_ELIGIBLE_PARTICIPANTS`
    case above."

    Design: Difficulty/boundary_precision_check/shared_pool_eligible_participant_set_drops_from_one_to_zero
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    fixtures.direct_cost_unit(api)
    shared_unit = fixtures.create_chargeback_unit(api, "Shared BU", "CC-600", headcount=4)
    untagged = fixtures.create_untagged_record(api, 5000)

    run = fixtures.create_run(api, mode="CHARGEBACK")
    pool = fixtures.create_pool(
        api, run["id"], [shared_unit["id"]], name="storage-untagged", methodology="EVEN_SPLIT"
    )
    fixtures.absorb(api, pool["id"], [untagged["id"]])
    fixtures.seal(api, pool["id"])
    validate_success(api.compute_allocation_run(run["id"], "PROVISIONAL", ANALYST_HEADERS))

    validate_success(
        api.patch_business_unit(shared_unit["id"], {"status": "SUSPENDED"}, ADMIN_HEADERS)
    )
    validate_error(
        api.compute_allocation_run(run["id"], "FINAL", ANALYST_HEADERS),
        ApiErrorId.NO_ELIGIBLE_PARTICIPANTS.value,
        422,
    )

    revived = validate_success(
        api.patch_business_unit(shared_unit["id"], {"status": "ACTIVE"}, ADMIN_HEADERS)
    )
    assert revived["status"] == "ACTIVE"

    final = validate_success(api.compute_allocation_run(run["id"], "FINAL", ANALYST_HEADERS))
    assert final["status"] == "COMPUTED_FINAL"
    assert final["variant_applied"] == "FINAL"
    assert_cents(final["total_allocated_cents"], 15000, "total_allocated_cents")
    assert final["line_count"] == 2

    lines, meta = _lines_of(api, run["id"])
    assert meta["total_count"] == 2
    assert_allocation_line(find_by(lines, line_kind="SHARED"), "SHARED", "EVEN_SPLIT", 5000)


def test_reopening_a_published_run_zeroes_its_lines_invoices_and_balances(api):
    """The intermediate state is a clean zero on every figure the publication moved.

    PRD §3.6: "A permitted reopen increments `reopen_count` by 1, returns every
    cost record carrying this run's `allocated_by_run_id` to `allocation_state`
    `UNALLOCATED` and clears that reference, drives every invoice of the run
    `ISSUED → VOIDED` as a system cascade (permitted only while the invoice is
    not `SETTLED`, and recomputing `net_due_cents` to 0 as it goes), deletes
    every allocation line of the run and resets both `total_allocated_cents` and
    `line_count` to 0, and recomputes both `chargeback_balance_cents` and
    `showback_total_cents` on the affected business units."

    Design: Difficulty/compensating_invariant/reopen_then_recompute_preserves_allocated_equals_effective_identity
    """
    built = _discounted_july_model(api)
    run_id = built["run"]["id"]
    platform_id = built["platform"]["id"]
    data_id = built["data"]["id"]

    computed = fixtures.compute(api, run_id, "FINAL")
    assert_cents(computed["total_allocated_cents"], 26967, "total_allocated_cents")
    published = fixtures.publish(api, run_id)
    assert published["status"] == "PUBLISHED"

    invoices = fixtures.invoices_of_run(api, run_id)
    platform_invoice = fixtures.issue_invoice(
        api, find_by(invoices, business_unit_id=platform_id)["id"]
    )
    data_invoice = fixtures.issue_invoice(api, find_by(invoices, business_unit_id=data_id)["id"])
    assert_invoice_ledger(platform_invoice, 18645, 0, 0, 18645)
    assert_invoice_ledger(data_invoice, 8322, 0, 0, 8322)
    before = validate_success(api.get_business_unit(platform_id, ADMIN_HEADERS))
    assert_cents(before["chargeback_balance_cents"], 18645, "chargeback_balance_cents")

    reopened = validate_success(
        api.reopen_allocation_run(
            run_id, "Late July storage bill arrived after publication.", CONTROLLER_HEADERS
        )
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert_cents(reopened["total_allocated_cents"], 0, "total_allocated_cents")
    assert reopened["line_count"] == 0

    _, no_lines = _lines_of(api, run_id)
    assert no_lines["total_count"] == 0

    for invoice in (platform_invoice, data_invoice):
        voided = validate_success(api.get_chargeback_invoice(invoice["id"], CONTROLLER_HEADERS))
        assert_invoice_dimensions(voided, settlement_status="VOIDED", dispute_status="NONE")
        assert_cents(voided["net_due_cents"], 0, "net_due_cents")

    for unit_id in (platform_id, data_id):
        cleared = validate_success(api.get_business_unit(unit_id, ADMIN_HEADERS))
        assert_cents(cleared["chargeback_balance_cents"], 0, "chargeback_balance_cents")

    for record in built["records"]:
        released = validate_success(api.get_cost_record(record["id"], ANALYST_HEADERS))
        assert released["allocation_state"] == "UNALLOCATED"
        assert released["allocated_by_run_id"] is None
        assert_cents(released["effective_cost_cents"], 7322, "effective_cost_cents")


def test_the_recompute_after_a_reopen_restores_the_totals_without_double_counting(api):
    """The rebuilt run lands on the same four lines and the same 26967 cents.

    PRD §3.6: "A `REOPENED` run re-enters compute on the `FINAL` variant and can
    be published again, and the compensating invariant must hold after every
    recompute."

    Design: Difficulty/compensating_invariant/reopen_then_recompute_preserves_allocated_equals_effective_identity
    """
    built = _discounted_july_model(api)
    run_id = built["run"]["id"]
    platform_id = built["platform"]["id"]

    fixtures.compute(api, run_id, "FINAL")
    fixtures.publish(api, run_id)
    for invoice in fixtures.invoices_of_run(api, run_id):
        fixtures.issue_invoice(api, invoice["id"])
    validate_success(
        api.reopen_allocation_run(
            run_id, "Late July storage bill arrived after publication.", CONTROLLER_HEADERS
        )
    )

    rebuilt = validate_success(api.compute_allocation_run(run_id, "FINAL", ANALYST_HEADERS))
    assert rebuilt["status"] == "COMPUTED_FINAL"
    assert rebuilt["variant_applied"] == "FINAL"
    assert_cents(rebuilt["total_allocated_cents"], 26967, "total_allocated_cents")
    assert_cents(rebuilt["scoped_effective_cost_cents"], 26967, "scoped_effective_cost_cents")
    assert rebuilt["line_count"] == 4

    pool = validate_success(api.get_shared_cost_pool(built["pool"]["id"], ANALYST_HEADERS))
    assert pool["absorbed_record_count"] == 1
    assert_cents(pool["pooled_cost_cents"], 5001, "pooled_cost_cents")

    lines, meta = _lines_of(api, run_id)
    assert meta["total_count"] == 4
    assert_allocation_line(
        find_by(lines, line_kind="DIRECT", business_unit_id=platform_id),
        "DIRECT",
        "EFFECTIVE_BASIS",
        14644,
    )
    assert_shares_sum_to_pool([line for line in lines if line["line_kind"] == "SHARED"], 5001)

    republished = fixtures.publish(api, run_id)
    assert republished["status"] == "PUBLISHED"

    invoices, invoice_meta = validate_paginated(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert invoice_meta["total_count"] == 4
    assert len([row for row in invoices if row["settlement_status"] == "VOIDED"]) == 2
    fresh = [row for row in invoices if row["settlement_status"] == "UNBILLED"]
    assert len(fresh) == 2
    assert_cents(
        find_by(fresh, business_unit_id=platform_id)["gross_amount_cents"],
        18645,
        "gross_amount_cents",
    )
