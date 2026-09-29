"""
Optimistic concurrency and derived-field reconciliation across the ledger.

Two operations carry a version field — estimate approval and statement creation —
and both refuse a request built on a snapshot that has since moved. Alongside
them, the version counter itself is exercised: every write advances it by exactly
one and no read ever touches it, and the derived-on-read aggregates are checked
against the per-lot sources they are recomputed from.
"""

from typing import Any, Dict, Optional

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_page,
    assert_unchanged,
)
from test_helpers.constants import (
    BASIS_GROSS,
    CLOCK_EPOCH,
    COHORT_C1_OBSERVED_RATE_BP,
    DEFAULT_ISSUANCE_RATE_MILLICENTS,
    DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    DEFAULT_SSP_MILLICENTS_PER_POINT,
    ESTIMATE_APPROVED,
    ESTIMATE_SUBMITTED,
    LOT_FULLY_REDEEMED,
    LOT_OUTSTANDING,
    LOT_PARTIALLY_REDEEMED,
    PROGRAM_ACTIVE,
    PROGRAM_SUSPENDED,
    REDEMPTION_ALLOCATED,
    REDEMPTION_FULFILLED,
    STATEMENT_DRAFT,
    TIER_MULTIPLIER_BP,
    TIER_SILVER,
    apply_bp,
    points_to_cents,
    round_half_up,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)

# ─── The reference figures every test below re-derives ───────────────────────
SSP = DEFAULT_SSP_MILLICENTS_PER_POINT              # 1200 millicents per point
SEEDED_RATE_BP = DEFAULT_SEEDED_BREAKAGE_RATE_BP    # 10000 - 7500
OBSERVED_RATE_BP = COHORT_C1_OBSERVED_RATE_BP       # the single cohort's rate
APPROVED_RATE_BP = 10000 - OBSERVED_RATE_BP         # what approval installs

BASE_LOT_POINTS = 1000
PARTNER_LOT_A_POINTS = 2000
PARTNER_LOT_B_POINTS = 1000
REDEEM_FIRST = 400
REDEEM_REST = 600

# The August period's end advanced by the agreement's thirty days of lag.
STATEMENT_DUE_DATE = "2026-10-01T00:00:00Z"

# A BASE member's lot: the tier multiplier is an identity, so no uplift is expensed.
LOT_A_GROSS_CENTS = points_to_cents(BASE_LOT_POINTS, SSP)
LOT_A_DEFERRED_CENTS = LOT_A_GROSS_CENTS - apply_bp(LOT_A_GROSS_CENTS, SEEDED_RATE_BP)

# A SILVER member's lot, where both uplifts carry a fractional tail and each rounds.
LOT_B_BASE_POINTS = 250
LOT_B_PROMO_BP = 10300
LOT_B_TIER_POINTS = round_half_up(
    LOT_B_BASE_POINTS * TIER_MULTIPLIER_BP[TIER_SILVER], 10000
)
LOT_B_POINTS_ISSUED = round_half_up(LOT_B_TIER_POINTS * LOT_B_PROMO_BP, 10000)
LOT_B_GROSS_CENTS = points_to_cents(LOT_B_POINTS_ISSUED, SSP)
LOT_B_DEFERRED_CENTS = LOT_B_GROSS_CENTS - apply_bp(LOT_B_GROSS_CENTS, SEEDED_RATE_BP)


def _live_program(
    api,
    program_overrides: Optional[Dict[str, Any]] = None,
    cohort_overrides: Optional[Dict[str, Any]] = None,
    rule_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    clock: str = CLOCK_EPOCH,
) -> Dict[str, Any]:
    """
    An ACTIVE programme with one state expiry rule, one cohort, one member and one
    OPEN period — the minimum state an issuance needs.
    """
    fixtures.set_clock(api, clock)
    program = fixtures.new_program(api, **(program_overrides or {}))
    fixtures.new_state_expiry_rule(api, program["id"], **(rule_overrides or {}))
    cohort = fixtures.new_cohort(api, program["id"], **(cohort_overrides or {}))
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(
        api, program["id"], cohort["id"], **(member_overrides or {})
    )
    period = fixtures.new_period(api, program["id"], **(period_overrides or {}))
    return {
        "program": program,
        "cohort": cohort,
        "member": member,
        "period": period,
    }


def _submitted_estimate_bundle(api) -> Dict[str, Any]:
    """A programme holding one outstanding lot and one SUBMITTED estimate."""
    bundle = _live_program(api)
    bundle["lot"] = fixtures.issue_lot(
        api, bundle["member"]["id"], bundle["period"]["id"], BASE_LOT_POINTS
    )
    bundle["estimate"] = fixtures.submitted_estimate(
        api, bundle["program"]["id"], bundle["period"]["id"]
    )
    return bundle


def test_expiry_sweep_advances_the_program_version_and_staleness_blocks_approval(api):
    """
    A sweep that expires nothing still advances the programme's version once, which
    invalidates the version the Controller captured a moment earlier: the approval
    carrying that earlier capture is refused at 412 and nothing about the estimate
    or the programme's live rate moves. The refusal is a pure version comparison —
    the period is open, the programme active, the estimate submitted and the
    approver is not the preparer.

    "Candidates are the programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` and whose `expires_at` is at or before the clock reading; the comparison is inclusive, so a lot whose `expires_at` is exactly the current clock reading is eligible while one an instant later is not."
    "The programme's `version` increments **once per sweep request**, not once per expired lot, however many lots the sweep touches — including when escheatment accrues against the programme several times."
    "If it does not equal the programme's current `version`, the approval is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."
    "Neither of these two checks depends on requests overlapping in time: the rejection is a function of the version value supplied versus the version value stored, nothing more."

    Design: Corner/cross_cutting_complexity_layers/ccl_occ_stale_program_version_blocks_estimate_approval
    """
    bundle = _submitted_estimate_bundle(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]

    observed_version = fixtures.program_version(api, program_id)

    assert_ok(api.run_expiry_sweep(period_id, None, ACCOUNTANT_HEADERS))

    swept_lot = assert_ok(api.get_point_lot(bundle["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        swept_lot, lifecycle_state=LOT_OUTSTANDING, points_remaining=BASE_LOT_POINTS
    )
    swept_period = assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))
    assert_fields(swept_period, expiry_released_cents=0, escheat_accrual_cents=0)

    fresh_version = fixtures.program_version(api, program_id)
    assert fresh_version == observed_version + 1, (
        "The sweep must advance the programme's version exactly once: expected "
        f"{observed_version + 1}, got {fresh_version}"
    )

    refused = api.approve_estimate(
        bundle["estimate"]["id"],
        factories.approval_payload(observed_version),
        CONTROLLER_HEADERS,
    )
    assert_error(refused, ApiErrorId.STALE_PROGRAM_VERSION.value)

    estimate_after = assert_ok(
        api.get_estimate(bundle["estimate"]["id"], CONTROLLER_HEADERS)
    )
    assert_fields(estimate_after, state=ESTIMATE_SUBMITTED)
    assert_unchanged(bundle["estimate"], estimate_after, "state", "version")

    program_after = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assert_fields(
        program_after,
        current_breakage_rate_bp=SEEDED_RATE_BP,
        status=PROGRAM_ACTIVE,
        version=fresh_version,
    )


def test_the_refreshed_program_version_lets_the_identical_approval_succeed(api):
    """
    The refusal is about staleness alone, so re-reading the programme and resending
    the identical body succeeds: the estimate reaches APPROVED with the rate it
    froze at creation, the programme's live breakage rate is overwritten with the
    complement of that rate, and the programme's version advances once more.

    "Approving a breakage estimate requires the request to carry `expected_program_version`, holding the `version` of the parent `LoyaltyProgram` as the approving `Controller` last observed it."
    "From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/ccl_occ_stale_program_version_blocks_estimate_approval
    """
    bundle = _submitted_estimate_bundle(api)
    program_id = bundle["program"]["id"]
    estimate_id = bundle["estimate"]["id"]

    observed_version = fixtures.program_version(api, program_id)
    assert_ok(api.run_expiry_sweep(bundle["period"]["id"], None, ACCOUNTANT_HEADERS))

    assert_error(
        api.approve_estimate(
            estimate_id, factories.approval_payload(observed_version), CONTROLLER_HEADERS
        ),
        ApiErrorId.STALE_PROGRAM_VERSION.value,
    )

    fresh_version = fixtures.program_version(api, program_id)
    approved = assert_ok(
        api.approve_estimate(
            estimate_id, factories.approval_payload(fresh_version), CONTROLLER_HEADERS
        )
    )

    outstanding_gross = points_to_cents(BASE_LOT_POINTS, SSP)
    assert_fields(
        approved,
        state=ESTIMATE_APPROVED,
        estimated_redemption_rate_bp=OBSERVED_RATE_BP,
        breakage_rate_bp=APPROVED_RATE_BP,
        outstanding_points_at_estimate=BASE_LOT_POINTS,
        outstanding_gross_ssp_cents_at_estimate=outstanding_gross,
        required_liability_cents=apply_bp(outstanding_gross, OBSERVED_RATE_BP),
    )

    program_after = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assert_fields(
        program_after,
        current_breakage_rate_bp=APPROVED_RATE_BP,
        version=fresh_version + 1,
    )


def _partner_bundle(api) -> Dict[str, Any]:
    """
    A programme with one ACTIVE third-party agreement that has already caused one
    partner lot of 2000 points to be issued, with a minimum invoice low enough that
    the first statement bills rather than defers.
    """
    bundle = _live_program(api)
    bundle["agreement"] = fixtures.new_agreement(
        api, bundle["program"]["id"], min_invoice_cents=1000
    )
    bundle["lot_a"] = fixtures.issue_lot(
        api,
        bundle["member"]["id"],
        bundle["period"]["id"],
        PARTNER_LOT_A_POINTS,
        partner_agreement_id=bundle["agreement"]["id"],
    )
    return bundle


def test_a_further_partner_lot_makes_a_pending_statement_create_stale(api):
    """
    Issuing a second partner-caused lot advances the agreement's version by one,
    because that lot changes what the next statement will measure. The create
    carrying the accountant's earlier capture is therefore refused at 412 and no
    statement row is written — which is exactly what stops the statement billing
    only the first lot's 2000 points.

    "When the request carried a `partner_agreement_id`, the named agreement's `version` increments by 1, because a partner-issued lot changes what the next settlement statement will measure."
    "Creating a settlement statement requires the request to carry `expected_partner_agreement_version`, holding the `version` of the parent `PartnerAgreement` as the accountant last observed it."
    "If it does not equal the agreement's current `version`, the create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/ccl_occ_stale_agreement_version_blocks_statement_creation
    """
    bundle = _partner_bundle(api)
    agreement_id = bundle["agreement"]["id"]
    period_id = bundle["period"]["id"]

    observed_version = fixtures.agreement_version(api, agreement_id)

    fixtures.issue_lot(
        api,
        bundle["member"]["id"],
        period_id,
        PARTNER_LOT_B_POINTS,
        partner_agreement_id=agreement_id,
    )

    fresh_version = fixtures.agreement_version(api, agreement_id)
    assert fresh_version == observed_version + 1, (
        "A partner-issued lot must advance the agreement's version exactly once: "
        f"expected {observed_version + 1}, got {fresh_version}"
    )

    refused = api.create_statement(
        factories.statement_payload(agreement_id, period_id, observed_version),
        ACCOUNTANT_HEADERS,
    )
    assert_error(refused, ApiErrorId.STALE_AGREEMENT_VERSION.value)

    assert_page(
        api.list_statements(ACCOUNTANT_HEADERS, partner_agreement_id=agreement_id),
        expected_ids=[],
        total_count=0,
    )


def test_the_refreshed_agreement_version_measures_both_partner_lots(api):
    """
    Re-reading the agreement and resending the identical body succeeds, and the
    statement then bills every point the partner caused to be issued in the period
    — 3000, not 2000 — at the agreement's issuance rate. Netting is disabled, so the
    basis is gross, the candidate clears the minimum invoice and the due date is the
    period's end plus the agreement's settlement lag.

    "`partner_issued_points` is the sum of `points_issued` over the matching lots, with every `lifecycle_state` included — issuance is billable the moment it happens, and a later redemption, expiry or escheatment does not un-bill it."
    "From those two counts, `issuance_receivable_cents` is `partner_issued_points` multiplied by the agreement's `issuance_rate_millicents_per_point`, divided by 1000, rounded half up, and `redemption_payable_cents` is `partner_redeemed_points` multiplied by the agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up."
    "What happens next depends on `settlement_basis`, which is computed at creation from the agreement: `NET` when `net_settlement_enabled` is true, `GROSS` when it is false."
    "`due_date` is the period's `end_at` advanced by the agreement's `settlement_lag_days` whole days."

    Design: Corner/cross_cutting_complexity_layers/ccl_occ_stale_agreement_version_blocks_statement_creation
    """
    bundle = _partner_bundle(api)
    agreement_id = bundle["agreement"]["id"]
    period_id = bundle["period"]["id"]

    observed_version = fixtures.agreement_version(api, agreement_id)
    fixtures.issue_lot(
        api,
        bundle["member"]["id"],
        period_id,
        PARTNER_LOT_B_POINTS,
        partner_agreement_id=agreement_id,
    )

    assert_error(
        api.create_statement(
            factories.statement_payload(agreement_id, period_id, observed_version),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.STALE_AGREEMENT_VERSION.value,
    )

    fresh_version = fixtures.agreement_version(api, agreement_id)
    statement = assert_created(
        api.create_statement(
            factories.statement_payload(agreement_id, period_id, fresh_version),
            ACCOUNTANT_HEADERS,
        )
    )

    total_points = PARTNER_LOT_A_POINTS + PARTNER_LOT_B_POINTS
    receivable = points_to_cents(total_points, DEFAULT_ISSUANCE_RATE_MILLICENTS)
    assert_fields(
        statement,
        state=STATEMENT_DRAFT,
        settlement_basis=BASIS_GROSS,
        partner_issued_points=total_points,
        partner_redeemed_points=0,
        issuance_receivable_cents=receivable,
        redemption_payable_cents=0,
        carried_forward_cents=0,
        net_due_cents=receivable,
        deferred_below_minimum_cents=0,
        due_date=STATEMENT_DUE_DATE,
    )


def test_program_version_advances_once_per_transition_and_never_on_a_read(api):
    """
    The programme's version starts at 1 on creation and moves by exactly one for each
    transition — a suspension and then a reactivation — while any number of reads
    leaves it exactly where the last write left it, even though every read recomputes
    the programme's two derived aggregates. Reactivation is also confirmed not to
    reseed the live breakage rate that the first activation installed.

    "Programmes, state expiry rules, cohorts, members, accounting periods, partner agreements, point lots, redemption events, breakage estimates, settlement statements and programme change orders additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on each mutation of that resource."
    "Suspension, `ACTIVE → SUSPENDED`, likewise increments `version` by 1; it blocks issuance and redemption while leaving period close and partner settlement fully available."
    "The second form is reactivation, `SUSPENDED → ACTIVE`, which explicitly does **not** reseed the rate — `current_breakage_rate_bp` is left exactly as the most recent estimate approval left it — and increments `version` by 1."
    "Both are recomputed on each read and reading them never bumps the programme's `version`."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_advances_on_every_write_and_never_on_a_read
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    assert program["version"] == 1, (
        f"A freshly created programme must be at version 1, got {program['version']}"
    )
    fixtures.new_state_expiry_rule(api, program["id"])
    fixtures.new_cohort(api, program["id"])
    activated = fixtures.activate(api, program["id"])
    assert activated["version"] == program["version"] + 1, (
        "First activation must advance the programme's version by exactly one"
    )

    before = assert_ok(api.get_program(program["id"], CONTROLLER_HEADERS))
    assert before["version"] == activated["version"]

    suspended = assert_ok(
        api.suspend_program(program["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        suspended, status=PROGRAM_SUSPENDED, version=before["version"] + 1
    )

    reactivated = assert_ok(
        api.activate_program(program["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        reactivated,
        status=PROGRAM_ACTIVE,
        version=suspended["version"] + 1,
        current_breakage_rate_bp=SEEDED_RATE_BP,
    )

    for reader in (CONTROLLER_HEADERS, ACCOUNTANT_HEADERS, PROGRAM_ADMIN_HEADERS):
        read = assert_ok(api.get_program(program["id"], reader))
        assert_fields(
            read,
            version=reactivated["version"],
            current_breakage_rate_bp=SEEDED_RATE_BP,
        )
        assert_unchanged(reactivated, read, "version", "updated_at")


def test_allocation_advances_both_the_event_and_the_consumed_lot(api):
    """
    One allocation is two mutations on two resources, so both counters move
    independently by exactly one: the event's, because it changed state and booked a
    provisional release, and the consumed lot's, because its balance fell. The
    provisional release is measured at the lot's own frozen breakage rate, and the
    lot's derived remainders are recomputed on each read without moving its version.

    "A lot that was `OUTSTANDING` and gives up a positive count strictly fewer than its `points_remaining` moves `OUTSTANDING → PARTIALLY_REDEEMED`, with `points_remaining` decremented by the amount drawn, one `ALLOCATION` row appended, and the lot's `version` incremented by 1."
    "The event's own `provisional_release_cents` is the sum of the per-line provisional releases — each line rounded first, then the rounded amounts added."
    "The event's own `version` increments by 1."
    "A derived-on-read figure is recomputed from current data every time the resource is read and is never stored; reading it does not refresh `updated_at` and does not increment `version`."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_advances_on_every_write_and_never_on_a_read
    """
    bundle = _live_program(api)
    member_id = bundle["member"]["id"]
    period_id = bundle["period"]["id"]

    lot = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)
    event = fixtures.request_redemption(api, member_id, period_id, REDEEM_FIRST)
    assert lot["version"] == 1 and event["version"] == 1, (
        "A freshly issued lot and a freshly requested redemption both start at version 1"
    )

    for _ in range(2):
        assert_ok(api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS))
        assert_ok(api.get_redemption(event["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        assert_ok(api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS)), version=1
    )
    assert_fields(
        assert_ok(api.get_redemption(event["id"], ACCOUNTANT_HEADERS)), version=1
    )

    line_gross = points_to_cents(REDEEM_FIRST, SSP)
    provisional = line_gross - apply_bp(line_gross, SEEDED_RATE_BP)

    allocated = assert_ok(api.allocate_redemption(event["id"], None, ACCOUNTANT_HEADERS))
    assert_fields(
        allocated,
        state=REDEMPTION_ALLOCATED,
        version=event["version"] + 1,
        provisional_release_cents=provisional,
    )

    lot_after = assert_ok(api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_after,
        version=lot["version"] + 1,
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
        points_remaining=BASE_LOT_POINTS - REDEEM_FIRST,
    )


def test_fulfilment_advances_only_the_event_version(api):
    """
    Fulfilment re-measures the same lines at the programme's current rate and books
    the divergence as a re-measurement delta, so the event's counter advances a third
    time; no lot balance moves, so the consumed lot's counter stands exactly where
    the allocation left it. Here the lot was issued under the seeded rate and the
    approved estimate then installed a lower one, so the delta is strictly positive.

    "The event's `final_release_cents` is the sum of those per-line finals, each rounded before being added, and the event's `remeasurement_delta_cents` is `final_release_cents` less `provisional_release_cents`."
    "No lot balance moves at fulfilment."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/ccl_version_advances_on_every_write_and_never_on_a_read
    """
    bundle = _live_program(api)
    member_id = bundle["member"]["id"]
    period_id = bundle["period"]["id"]

    lot = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)
    fixtures.approved_estimate(api, bundle["program"]["id"], period_id)

    event = fixtures.request_redemption(api, member_id, period_id, REDEEM_FIRST)
    allocated = assert_ok(api.allocate_redemption(event["id"], None, ACCOUNTANT_HEADERS))
    lot_after_allocation = assert_ok(api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS))

    line_gross = points_to_cents(REDEEM_FIRST, SSP)
    provisional = line_gross - apply_bp(line_gross, SEEDED_RATE_BP)
    final = line_gross - apply_bp(line_gross, APPROVED_RATE_BP)

    fulfilled = assert_ok(api.fulfill_redemption(event["id"], None, ACCOUNTANT_HEADERS))
    assert_fields(
        fulfilled,
        state=REDEMPTION_FULFILLED,
        version=allocated["version"] + 1,
        provisional_release_cents=provisional,
        final_release_cents=final,
        remeasurement_delta_cents=final - provisional,
    )

    lot_after_fulfilment = assert_ok(api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS))
    assert_unchanged(
        lot_after_allocation,
        lot_after_fulfilment,
        "version",
        "points_remaining",
        "lifecycle_state",
    )


def _two_lot_bundle(api) -> Dict[str, Any]:
    """
    One programme, one period and two members holding one lot each: a BASE member's
    round 1000-point lot and a SILVER member's lot whose tier and promotional uplifts
    both round.
    """
    bundle = _live_program(api)
    period_id = bundle["period"]["id"]
    bundle["member_b"] = fixtures.new_member(
        api, bundle["program"]["id"], bundle["cohort"]["id"], tier=TIER_SILVER
    )
    bundle["lot_a"] = fixtures.issue_lot(
        api, bundle["member"]["id"], period_id, BASE_LOT_POINTS
    )
    bundle["lot_b"] = fixtures.issue_lot(
        api,
        bundle["member_b"]["id"],
        period_id,
        LOT_B_BASE_POINTS,
        promo_multiplier_bp=LOT_B_PROMO_BP,
    )
    return bundle


def test_derived_aggregates_sum_the_lots_before_any_redemption(api):
    """
    Every derived-on-read aggregate ties to its per-lot sources the moment the lots
    exist: the programme's deferred revenue is the sum of the two lots' remaining
    deferral, and each member's balance and outstanding gross are that member's own
    lot rounded first and only then added. Nothing has closed, so the programme's
    recognised breakage for the year is still zero.

    "`total_deferred_revenue_cents` is the sum, over this programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, of each lot's `remaining_deferred_cents`."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."
    "Three member figures are derived on read: `dormancy_days` is the whole number of days between `last_activity_at` and the current clock reading, computed by dividing the elapsed seconds by 86400 and discarding the fraction, and floored at 0; `point_balance` is the sum of `points_remaining` over the member's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`; and `outstanding_gross_ssp_cents` is the sum, over that same set of lots, of each lot's `remaining_gross_ssp_cents`, with each lot rounded first and the rounded amounts then added."
    "`points_issued` is the **already-rounded** `tier_points` multiplied by `promo_multiplier_bp`, divided by 10000, and rounded half up again."

    Design: Corner/cross_cutting_complexity_layers/ccl_derived_field_reconciliation_deferred_revenue_tracks_lots
    """
    bundle = _two_lot_bundle(api)

    lot_a = assert_ok(api.get_point_lot(bundle["lot_a"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_a,
        points_issued=BASE_LOT_POINTS,
        gross_ssp_cents=LOT_A_GROSS_CENTS,
        deferred_revenue_cents=LOT_A_DEFERRED_CENTS,
        remaining_gross_ssp_cents=LOT_A_GROSS_CENTS,
        remaining_deferred_cents=LOT_A_DEFERRED_CENTS,
        lifecycle_state=LOT_OUTSTANDING,
    )

    lot_b = assert_ok(api.get_point_lot(bundle["lot_b"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_b,
        tier_points=LOT_B_TIER_POINTS,
        points_issued=LOT_B_POINTS_ISSUED,
        gross_ssp_cents=LOT_B_GROSS_CENTS,
        deferred_revenue_cents=LOT_B_DEFERRED_CENTS,
        remaining_gross_ssp_cents=LOT_B_GROSS_CENTS,
        remaining_deferred_cents=LOT_B_DEFERRED_CENTS,
    )

    program = assert_ok(api.get_program(bundle["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        program,
        total_deferred_revenue_cents=LOT_A_DEFERRED_CENTS + LOT_B_DEFERRED_CENTS,
        recognized_breakage_ytd_cents=0,
    )

    assert_fields(
        assert_ok(api.get_member(bundle["member"]["id"], ACCOUNTANT_HEADERS)),
        point_balance=BASE_LOT_POINTS,
        outstanding_gross_ssp_cents=LOT_A_GROSS_CENTS,
    )
    assert_fields(
        assert_ok(api.get_member(bundle["member_b"]["id"], ACCOUNTANT_HEADERS)),
        point_balance=LOT_B_POINTS_ISSUED,
        outstanding_gross_ssp_cents=LOT_B_GROSS_CENTS,
    )

    assert_fields(
        assert_ok(api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS)),
        issuance_deferred_cents=LOT_A_DEFERRED_CENTS + LOT_B_DEFERRED_CENTS,
    )


def test_a_partial_redemption_reprices_every_derived_aggregate(api):
    """
    Drawing 400 of a 1000-point lot leaves the lot PARTIALLY_REDEEMED, so it still
    counts everywhere, but every derived figure is recomputed from the surviving
    balance: the lot's remaining gross and deferral, the holder's balance and
    outstanding gross, and the programme's total deferred revenue all fall together.
    The period's issuance accumulator does not fall — it is the persisted total of
    what was deferred at issuance, and the redemption side is booked separately.

    "`remaining_gross_ssp_cents` is `points_remaining` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`remaining_deferred_cents` is that remaining gross less the reserve on the remaining gross — that is, less `remaining_gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "`issuance_deferred_cents` grows by each issued lot's `deferred_revenue_cents`."
    "`redemption_recognized_cents` grows by a redemption event's `provisional_release_cents` when that event is allocated and shrinks by the same amount when the event is reversed."

    Design: Corner/cross_cutting_complexity_layers/ccl_derived_field_reconciliation_deferred_revenue_tracks_lots
    """
    bundle = _two_lot_bundle(api)
    period_id = bundle["period"]["id"]

    fixtures.allocated_redemption(
        api, bundle["member"]["id"], period_id, REDEEM_FIRST
    )

    survivors = BASE_LOT_POINTS - REDEEM_FIRST
    remaining_gross = points_to_cents(survivors, SSP)
    remaining_deferred = remaining_gross - apply_bp(remaining_gross, SEEDED_RATE_BP)

    lot_a = assert_ok(api.get_point_lot(bundle["lot_a"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot_a,
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
        points_remaining=survivors,
        remaining_gross_ssp_cents=remaining_gross,
        remaining_deferred_cents=remaining_deferred,
        gross_ssp_cents=LOT_A_GROSS_CENTS,
        deferred_revenue_cents=LOT_A_DEFERRED_CENTS,
    )

    assert_fields(
        assert_ok(api.get_program(bundle["program"]["id"], CONTROLLER_HEADERS)),
        total_deferred_revenue_cents=remaining_deferred + LOT_B_DEFERRED_CENTS,
        recognized_breakage_ytd_cents=0,
    )

    assert_fields(
        assert_ok(api.get_member(bundle["member"]["id"], ACCOUNTANT_HEADERS)),
        point_balance=survivors,
        outstanding_gross_ssp_cents=remaining_gross,
    )

    line_gross = points_to_cents(REDEEM_FIRST, SSP)
    assert_fields(
        assert_ok(api.get_period(period_id, CONTROLLER_HEADERS)),
        issuance_deferred_cents=LOT_A_DEFERRED_CENTS + LOT_B_DEFERRED_CENTS,
        redemption_recognized_cents=line_gross - apply_bp(line_gross, SEEDED_RATE_BP),
    )


def test_an_exhausted_lot_drops_out_of_every_derived_aggregate(api):
    """
    A second draw takes the lot to FULLY_REDEEMED, and a fully redeemed lot is
    outside the scope of every aggregate: the holder's balance and outstanding gross
    fall to zero and the programme's deferred revenue is exactly the other member's
    lot. That other member's own figures are untouched throughout, which is what
    shows the aggregates are recomputed per lot rather than carried as a running
    programme-level total.

    "A lot that was already `PARTIALLY_REDEEMED` and gives up exactly its `points_remaining` moves `PARTIALLY_REDEEMED → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1; if it gives up less than that, it remains `PARTIALLY_REDEEMED` with its balance reduced."
    "`total_deferred_revenue_cents` is the sum, over this programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, of each lot's `remaining_deferred_cents`."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."

    Design: Corner/cross_cutting_complexity_layers/ccl_derived_field_reconciliation_deferred_revenue_tracks_lots
    """
    bundle = _two_lot_bundle(api)
    period_id = bundle["period"]["id"]
    member_b_before = assert_ok(
        api.get_member(bundle["member_b"]["id"], ACCOUNTANT_HEADERS)
    )

    fixtures.allocated_redemption(api, bundle["member"]["id"], period_id, REDEEM_FIRST)
    fixtures.allocated_redemption(api, bundle["member"]["id"], period_id, REDEEM_REST)

    assert_fields(
        assert_ok(api.get_point_lot(bundle["lot_a"]["id"], ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_FULLY_REDEEMED,
        points_remaining=0,
        remaining_gross_ssp_cents=0,
        remaining_deferred_cents=0,
    )

    assert_fields(
        assert_ok(api.get_program(bundle["program"]["id"], CONTROLLER_HEADERS)),
        total_deferred_revenue_cents=LOT_B_DEFERRED_CENTS,
        recognized_breakage_ytd_cents=0,
    )

    assert_fields(
        assert_ok(api.get_member(bundle["member"]["id"], ACCOUNTANT_HEADERS)),
        point_balance=0,
        outstanding_gross_ssp_cents=0,
    )

    member_b_after = assert_ok(
        api.get_member(bundle["member_b"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(
        member_b_after,
        point_balance=LOT_B_POINTS_ISSUED,
        outstanding_gross_ssp_cents=LOT_B_GROSS_CENTS,
    )
    assert_unchanged(
        member_b_before,
        member_b_after,
        "point_balance",
        "outstanding_gross_ssp_cents",
        "version",
    )
