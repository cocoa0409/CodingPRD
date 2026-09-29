"""Field, cross-entity, temporal and aggregate validation refusals.

Single-slot document classes, the asymmetric document bar for a high-risk
origin, the SAF share ceiling, a maturity that has already passed, a campaign
window off midnight, pretreatment that would create mass, a nomination outside
its contract, hydrogen that does not cover the day, a window that has not
elapsed, product that exceeds the feed, and a retirement larger than the balance.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUE_DILIGENCE_DOCS_INSUFFICIENT,
    ERR_DUPLICATE_DOCUMENT,
    ERR_HYDROGEN_COVERAGE_SHORTFALL,
    ERR_INSUFFICIENT_CREDITS,
    ERR_INVALID_RUN_WINDOW,
    ERR_MASS_BALANCE_VIOLATION,
    ERR_MATURITY_IN_PAST,
    ERR_NOMINATION_OUTSIDE_CONTRACT_WINDOW,
    ERR_PRETREATMENT_MASS_EXCEEDED,
    ERR_RUN_WINDOW_NOT_ELAPSED,
    ERR_SAF_SHARE_EXCEEDED,
)
from test_helpers.assertions import (
    assert_activity_index,
    assert_fields_null,
    assert_mass,
    assert_one_decimal,
    assert_timestamp_equals,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
)
from test_helpers.types import (
    BLOCK_RETIRED,
    BLOCK_VERIFIED,
    CHARGE_ACTIVE,
    DD_PENDING,
    DD_VERIFIED,
    DOC_MASS_BALANCE_STATEMENT,
    DOC_ORIGIN_ATTESTATION,
    DOC_THIRD_PARTY_AUDIT,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_UCO,
    LOT_ACCEPTED,
    LOT_PRETREAT_REQUIRED,
    LOT_PRETREATED,
    RUN_PLANNED,
    RUN_RUNNING,
    TIER_HEAVY,
    TIER_NONE,
    UNIT_RUNNING,
)


def test_a_second_origin_attestation_is_a_duplicate_even_with_a_new_hash(api):
    """PRD §3.1: "Two uniqueness conditions apply together and both surface as
    `ERR_DUPLICATE_DOCUMENT`: no other document already on this supplier may share the same
    `doc_type`, and no document anywhere in the system may already carry the same `doc_hash`."
    PRD §3.1: "A supplier that needs to replace an expiring origin attestation therefore cannot
    simply upload a second one — the document class is single-slot per supplier."

    Design: Corner/validations/duplicate_doc_type_on_supplier_returns_duplicate_document
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    fx.add_document(
        api, supplier["id"], doc_type=DOC_ORIGIN_ATTESTATION, valid_until="2027-12-31T00:00:00Z"
    )

    validate_error(
        api.create_traceability_document(
            supplier["id"],
            f.traceability_document_payload(
                doc_type=DOC_ORIGIN_ATTESTATION,
                issued_at="2026-07-15T00:00:00Z",
                valid_until="2028-01-31T00:00:00Z",
            ),
            TRADER_HEADERS,
        ),
        ERR_DUPLICATE_DOCUMENT,
    )

    refreshed = validate_success(api.get_supplier(supplier["id"], TRADER_HEADERS))
    assert refreshed["dd_document_type_count"] == 1, f"got {refreshed['dd_document_type_count']}"
    assert refreshed["dd_status"] == DD_PENDING, f"got {refreshed['dd_status']}"

    _, meta = validate_paginated(
        api.list_traceability_documents(supplier["id"], TRADER_HEADERS)
    )
    assert meta["total_count"] == 1, f"the refused upload stored nothing, got {meta['total_count']}"


def test_a_high_risk_origin_needs_the_third_party_audit_before_it_verifies(api):
    """PRD §3.1: "The document bar is asymmetric and is the check behind
    `ERR_DUE_DILIGENCE_DOCS_INSUFFICIENT`: an ordinary-origin supplier needs
    `dd_document_type_count` of at least 2, while a supplier whose `is_high_risk_origin` is
    `true` needs at least 3 **and** must additionally hold at least one `THIRD_PARTY_AUDIT`
    document whose `valid_until` is strictly after the current logical clock."
    PRD §3.1: "Verification moves `dd_status` from `PENDING` to `VERIFIED`, sets `dd_verified_at`
    to the current logical clock, sets `dd_expires_at` to the current logical clock advanced by
    `valid_months` multiplied by 30 days (months are treated as exactly 30 days each, never as
    calendar months), clears `suspension_reason`, and bumps the supplier's `version`."

    Design: Corner/validations/high_risk_supplier_requires_a_third_document_type_then_verifies
    """
    supplier = fx.documented_supplier(
        api,
        doc_types=(DOC_ORIGIN_ATTESTATION, DOC_MASS_BALANCE_STATEMENT),
        legal_name="Sunda Straits Collectors",
        country_code="ID",
        feedstock_types=[FEEDSTOCK_UCO],
        is_high_risk_origin=True,
    )

    validate_error(
        api.verify_due_diligence(
            supplier["id"], f.due_diligence_payload(valid_months=12), OFFICER_A_HEADERS
        ),
        ERR_DUE_DILIGENCE_DOCS_INSUFFICIENT,
    )

    short = validate_success(api.get_supplier(supplier["id"], TRADER_HEADERS))
    assert short["dd_status"] == DD_PENDING, f"got {short['dd_status']}"
    assert short["dd_document_type_count"] == 2, f"got {short['dd_document_type_count']}"
    assert_fields_null(short, "dd_verified_at", "dd_expires_at")

    fx.add_document(
        api,
        supplier["id"],
        doc_type=DOC_THIRD_PARTY_AUDIT,
        issued_at="2026-07-20T00:00:00Z",
        valid_until="2027-12-31T00:00:00Z",
    )

    verified = validate_success(
        api.verify_due_diligence(
            supplier["id"], f.due_diligence_payload(valid_months=12), OFFICER_A_HEADERS
        )
    )
    assert verified["dd_status"] == DD_VERIFIED, f"got {verified['dd_status']}"
    assert verified["dd_document_type_count"] == 3, f"got {verified['dd_document_type_count']}"
    assert_timestamp_equals(verified["dd_verified_at"], "2026-08-01T00:00:00Z", "dd_verified_at")
    assert_timestamp_equals(verified["dd_expires_at"], "2027-07-27T00:00:00Z", "dd_expires_at")


def test_a_saf_target_above_the_units_ceiling_is_refused_at_creation(api):
    """PRD §3.5: "Separately, `target_saf_share_pct` may not exceed the unit's
    `max_saf_share_pct`, and a violation is refused with `ERR_SAF_SHARE_EXCEEDED`."
    PRD §3.3: "a `max_saf_share_pct` giving the maximum share of product mass this unit may route
    to sustainable aviation fuel, at least 0 and at most 60 with at most 2 decimal places"

    Design: Corner/validations/saf_share_above_unit_maximum_is_rejected_at_run_creation
    """
    plant = fx.commissioned_unit(api)
    assert plant["unit"]["max_saf_share_pct"] == 40.00, f"got {plant['unit']['max_saf_share_pct']}"

    validate_error(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=50.00
            ),
            OPERATOR_HEADERS,
        ),
        ERR_SAF_SHARE_EXCEEDED,
    )

    _, meta = validate_paginated(
        api.list_processing_runs(OPERATOR_HEADERS, {"unit_id": plant["unit"]["id"]})
    )
    assert meta["total_count"] == 0, f"no campaign may survive the refusal, got {meta['total_count']}"

    at_the_ceiling = validate_success(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=40.00
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )
    assert at_the_ceiling["target_saf_share_pct"] == 40.00, (
        f"the comparison is strictly greater-than, got {at_the_ceiling['target_saf_share_pct']}"
    )
    assert at_the_ceiling["status"] == RUN_PLANNED, f"got {at_the_ceiling['status']}"


def test_a_hedge_maturing_at_or_before_the_clock_is_refused(api):
    """PRD §3.9: "and a `maturity_at` instant that must be strictly after the current logical
    clock — a maturity equal to the current clock is refused with `ERR_MATURITY_IN_PAST`"
    PRD §2.5: "On a fresh process that clock reads `2026-08-01T00:00:00.000Z`, so a scenario that
    never touches it still observes that instant."

    Design: Corner/validations/hedge_maturity_in_the_past_is_rejected
    """
    validate_error(
        api.create_hedge_position(
            f.hedge_position_payload(
                notional_units=10000, strike_price_usd=2.50, maturity_at="2026-07-01T00:00:00Z"
            ),
            TRADER_HEADERS,
        ),
        ERR_MATURITY_IN_PAST,
    )

    validate_error(
        api.create_hedge_position(
            f.hedge_position_payload(
                notional_units=10000, strike_price_usd=2.50, maturity_at="2026-08-01T00:00:00Z"
            ),
            TRADER_HEADERS,
        ),
        ERR_MATURITY_IN_PAST,
    )

    _, meta = validate_paginated(api.list_hedge_positions(TRADER_HEADERS))
    assert meta["total_count"] == 0, f"neither attempt may open a book, got {meta['total_count']}"


def test_a_campaign_window_off_midnight_is_refused_before_anything_else(api):
    """PRD §3.5: "The campaign interval must be well shaped: both `window_start` and `window_end`
    must fall exactly on midnight UTC, `window_end` must be strictly later than `window_start`,
    and the gap between them must be a whole number of days."
    PRD §3.5: "A `window_start` at 06:00:00Z, or a `window_end` equal to `window_start`, is
    refused with `ERR_INVALID_RUN_WINDOW`."

    Design: Corner/validations/run_window_not_midnight_aligned_is_rejected
    """
    plant = fx.commissioned_unit(api)

    validate_error(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"],
                plant["charge"]["id"],
                window_start="2026-09-01T06:00:00Z",
                window_end="2026-09-06T00:00:00Z",
                target_saf_share_pct=0.00,
            ),
            OPERATOR_HEADERS,
        ),
        ERR_INVALID_RUN_WINDOW,
    )

    validate_error(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"],
                plant["charge"]["id"],
                window_start="2026-09-01T00:00:00Z",
                window_end="2026-09-01T00:00:00Z",
                target_saf_share_pct=0.00,
            ),
            OPERATOR_HEADERS,
        ),
        ERR_INVALID_RUN_WINDOW,
    )

    _, meta = validate_paginated(
        api.list_processing_runs(OPERATOR_HEADERS, {"unit_id": plant["unit"]["id"]})
    )
    assert meta["total_count"] == 0, f"got {meta['total_count']}"


def test_pretreatment_cannot_hand_back_more_mass_than_it_was_given(api):
    """PRD §3.2: "That figure must be greater than 0 and no greater than the source lot's
    `mass_mt`; a zero or over-large value is refused with `ERR_PRETREATMENT_MASS_EXCEEDED`."
    PRD §3.2: "And a **child lot** is created and returned, carrying `source_lot_id` pointing at
    the source lot, the same `supplier_id`, the same `feedstock_type`, the same `received_at`, a
    `mass_mt` and `remaining_mass_mt` equal to `output_mass_mt`, a status of `ACCEPTED` (a
    pretreated lot is already fit to charge and needs no separate acceptance), a
    `pretreatment_tier` of `NONE` and a `pretreatment_fee_usd` of 0.00."

    Design: Corner/validations/pretreatment_output_above_source_mass_is_rejected
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_TALLOW])
    lot = fx.tested_lot(
        api,
        supplier["id"],
        test={"ffa_pct": 6.00},
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=300.000,
        attested_ci_gco2e_per_mj=21.40,
        purchase_price_usd_per_mt=880.00,
    )
    assert lot["status"] == LOT_PRETREAT_REQUIRED, f"got {lot['status']}"
    assert lot["pretreatment_tier"] == TIER_HEAVY, f"got {lot['pretreatment_tier']}"

    validate_error(
        api.create_pretreatment(lot["id"], f.pretreatment_payload(320.000), ANALYST_HEADERS),
        ERR_PRETREATMENT_MASS_EXCEEDED,
    )

    intact = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert intact["status"] == LOT_PRETREAT_REQUIRED, f"got {intact['status']}"
    assert_mass(intact["remaining_mass_mt"], 300.000, "remaining_mass_mt")

    _, meta = validate_paginated(
        api.list_feedstock_lots(TRADER_HEADERS, {"source_lot_id": lot["id"]})
    )
    assert meta["total_count"] == 0, f"no child lot may be minted, got {meta['total_count']}"

    child = validate_success(
        api.create_pretreatment(lot["id"], f.pretreatment_payload(300.000), ANALYST_HEADERS), 201
    )
    assert child["source_lot_id"] == lot["id"]
    assert_mass(child["mass_mt"], 300.000, "mass_mt")
    assert child["status"] == LOT_ACCEPTED, f"got {child['status']}"
    assert child["pretreatment_tier"] == TIER_NONE, f"got {child['pretreatment_tier']}"

    spent = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert spent["status"] == LOT_PRETREATED, f"got {spent['status']}"
    assert_mass(spent["pretreatment_loss_mt"], 0.000, "pretreatment_loss_mt")


def test_a_nomination_after_the_contract_closes_is_outside_its_window(api):
    """PRD §3.4: "The nomination's closed interval must lie entirely inside the contract's closed
    window; a `start_at` one day before the contract's `window_start`, or an `end_at` earlier than
    `start_at`, is refused with `ERR_NOMINATION_OUTSIDE_CONTRACT_WINDOW`."
    PRD §3.4: "The `peak_committed_kg_per_day` is the maximum of that daily figure taken over
    every calendar date from the contract's `window_start` through its `window_end` inclusive,
    rounded half up to 1 decimal place, and it is 0.0 when the contract holds no `CONFIRMED`
    nomination at all."

    Design: Corner/validations/nomination_outside_the_contract_window_is_rejected
    """
    plant = fx.commissioned_unit(api)
    contract = fx.make_contract(api)
    assert_timestamp_equals(contract["window_end"], "2026-09-30T00:00:00Z", "window_end")
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=0.00
    )

    validate_error(
        api.create_nomination(
            contract["id"],
            f.nomination_payload(
                run["id"],
                start_at="2026-10-01T00:00:00Z",
                end_at="2026-10-02T00:00:00Z",
                kg_per_day=2600.0,
            ),
            OPERATOR_HEADERS,
        ),
        ERR_NOMINATION_OUTSIDE_CONTRACT_WINDOW,
    )

    untouched = validate_success(api.get_hydrogen_contract(contract["id"], TRADER_HEADERS))
    assert_one_decimal(untouched["peak_committed_kg_per_day"], 0.0, "peak_committed_kg_per_day")

    _, meta = validate_paginated(
        api.list_contract_nominations(contract["id"], OPERATOR_HEADERS)
    )
    assert meta["total_count"] == 0, f"nothing may be booked, got {meta['total_count']}"


def test_hydrogen_booked_below_the_daily_requirement_blocks_securement(api):
    """PRD §3.5: "and for **every** calendar day in the campaign's half-open window, the sum of
    `kg_per_day` over the `CONFIRMED` nominations booked against that campaign whose closed
    interval covers that day must be at least the campaign's `required_h2_kg_per_day`."
    PRD §3.5: "A nomination covering only part of the window, or covering every day at too low a
    rate, is refused with `ERR_HYDROGEN_COVERAGE_SHORTFALL`."

    Design: Corner/validations/hydrogen_coverage_shortfall_blocks_securement
    """
    ctx = fx.baseline_campaign(
        api, target_saf_share_pct=0.00, nomination_kg_per_day=2000.0, secure=False
    )
    assert_one_decimal(ctx["run"]["required_h2_kg_per_day"], 2560.0, "required_h2_kg_per_day")

    validate_error(
        api.secure_hydrogen(ctx["run"]["id"], OPERATOR_HEADERS), ERR_HYDROGEN_COVERAGE_SHORTFALL
    )

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert run["status"] == RUN_PLANNED, f"got {run['status']}"
    assert_fields_null(run, "provisional_yield_pct", "planned_total_product_mt")
    assert_mass(run["reserved_mass_mt"], 400.000, "reserved_mass_mt")


def test_completing_a_day_early_is_refused_and_succeeds_on_the_boundary(api):
    """PRD §3.6: "Three conditions are evaluated in this order after the campaign's state has been
    confirmed: the current logical clock must be at or after the campaign's `window_end`,
    otherwise `ERR_RUN_WINDOW_NOT_ELAPSED`"
    PRD §3.6: "When all three hold, the campaign moves `RUNNING → COMPLETED`, storing the two
    measured masses."

    Design: Corner/validations/run_completion_before_window_end_returns_not_elapsed
    """
    ctx = fx.started_campaign(api)
    fx.move_clock(api, "2026-09-05T00:00:00Z")

    validate_error(
        api.complete_run(
            ctx["run"]["id"], f.completion_payload(290.000, 30.000), OPERATOR_HEADERS
        ),
        ERR_RUN_WINDOW_NOT_ELAPSED,
    )

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert run["status"] == RUN_RUNNING, f"got {run['status']}"
    assert_fields_null(run, "final_yield_pct", "yield_variance_pct")

    unit = validate_success(api.get_unit(ctx["unit"]["id"], OPERATOR_HEADERS))
    assert unit["status"] == UNIT_RUNNING, f"got {unit['status']}"

    _, meta = validate_paginated(
        api.list_product_batches(OFFICER_A_HEADERS, {"run_id": ctx["run"]["id"]})
    )
    assert meta["total_count"] == 0, f"no product may exist yet, got {meta['total_count']}"

    fx.move_clock(api, "2026-09-06T00:00:00Z")
    completed = validate_success(
        api.complete_run(
            ctx["run"]["id"], f.completion_payload(290.000, 30.000), OPERATOR_HEADERS
        )
    )
    assert_mass(completed["measured_rd_mt"], 290.000, "measured_rd_mt")
    assert_mass(completed["measured_saf_mt"], 30.000, "measured_saf_mt")


def test_measured_product_above_the_consumed_feed_breaks_the_mass_balance(api):
    """PRD §3.6: "and the sum of the two measured masses, rounded to 3 decimal places, must be no
    greater than the campaign's `consumed_mass_mt`, otherwise `ERR_MASS_BALANCE_VIOLATION`. You
    cannot make more product than you fed."
    PRD §3.6: "The completion then reaches into the catalyst charge. Its
    `cumulative_throughput_mt` is recomputed and its `activity_index` re-derived as described in
    §3.3."

    Design: Corner/validations/mass_balance_violation_when_measured_product_exceeds_consumed_feedstock
    """
    ctx = fx.started_campaign(api)
    fx.move_clock(api, "2026-09-06T00:00:00Z")

    validate_error(
        api.complete_run(
            ctx["run"]["id"], f.completion_payload(300.000, 120.000), OPERATOR_HEADERS
        ),
        ERR_MASS_BALANCE_VIOLATION,
    )

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert run["status"] == RUN_RUNNING, f"got {run['status']}"
    assert_mass(run["consumed_mass_mt"], 400.000, "consumed_mass_mt")
    assert_fields_null(run, "final_yield_pct")
    assert_mass(run["measured_rd_mt"], 0.000, "measured_rd_mt")
    assert_mass(run["measured_saf_mt"], 0.000, "measured_saf_mt")

    _, meta = validate_paginated(
        api.list_product_batches(OFFICER_A_HEADERS, {"run_id": ctx["run"]["id"]})
    )
    assert meta["total_count"] == 0, f"got {meta['total_count']}"

    charges, _ = validate_paginated(
        api.list_catalyst_charges(
            ctx["unit"]["id"], OPERATOR_HEADERS, {"status": CHARGE_ACTIVE}
        )
    )
    assert len(charges) == 1, f"got {len(charges)}"
    assert_mass(charges[0]["cumulative_throughput_mt"], 0.000, "cumulative_throughput_mt")
    assert_activity_index(charges[0]["activity_index"], 1.0000)


def test_retiring_more_than_the_verified_balance_is_refused(api):
    """PRD §3.8: "That figure must be greater than 0 and no greater than the block's
    `verified_credits_mtco2e` less its `retired_credits_mtco2e`; a request for zero, or for more
    than the remaining balance, is refused with `ERR_INSUFFICIENT_CREDITS`."
    PRD §3.8: "The block moves to `RETIRED` only when `retired_credits_mtco2e` has become equal to
    `verified_credits_mtco2e`; a partial retirement leaves the block where it was so that the
    remainder can be retired later."

    Design: Corner/validations/over_retirement_is_rejected_with_insufficient_credits
    """
    ctx = fx.credit_ready_campaign(
        api, measured_rd_mt=320.123, measured_saf_mt=0.000, target_saf_share_pct=0.00
    )
    assert_one_decimal(ctx["batch"]["volume_gal"], 98597.9, "volume_gal")

    block = fx.verified_credit_block(api, ctx["batch"]["id"], ctx["pathway"]["id"])
    assert block["status"] == BLOCK_VERIFIED, f"got {block['status']}"
    assert_mass(block["provisional_credits_mtco2e"], 604.007, "provisional_credits_mtco2e")
    assert_mass(block["verified_credits_mtco2e"], 591.927, "verified_credits_mtco2e")

    validate_error(
        api.retire_credits(block["id"], f.retirement_payload(600.000), OFFICER_A_HEADERS),
        ERR_INSUFFICIENT_CREDITS,
    )

    intact = validate_success(api.get_credit_block(block["id"], OFFICER_A_HEADERS))
    assert intact["status"] == BLOCK_VERIFIED, f"got {intact['status']}"
    assert_mass(intact["retired_credits_mtco2e"], 0.000, "retired_credits_mtco2e")

    retired = validate_success(
        api.retire_credits(block["id"], f.retirement_payload(591.927), OFFICER_A_HEADERS)
    )
    assert retired["status"] == BLOCK_RETIRED, f"got {retired['status']}"
    assert_mass(retired["retired_credits_mtco2e"], 591.927, "retired_credits_mtco2e")

    pathway = validate_success(api.get_pathway(ctx["pathway"]["id"], OFFICER_A_HEADERS))
    assert_mass(pathway["credits_outstanding_mtco2e"], 0.000, "credits_outstanding_mtco2e")
