"""Reachability of the declared error codes, one refusal at a time.

Fabricated identifiers on every aggregate, terminal states that refuse a second
attempt, a retired catalyst charge, the three aviation-fuel refusals, and the
steps taken out of order on the certification and credit ledgers.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ALLOCATION_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_CATALYST_CHARGE_NOT_FOUND,
    ERR_CATALYST_NOT_ACTIVE,
    ERR_CREDIT_BLOCK_NOT_FOUND,
    ERR_HEDGE_POSITION_NOT_FOUND,
    ERR_INVALID_ALLOCATION_STATE,
    ERR_INVALID_BATCH_CERT_STATE,
    ERR_INVALID_BATCH_DISTRIBUTION_STATE,
    ERR_INVALID_CREDIT_BLOCK_STATE,
    ERR_INVALID_HEDGE_STATE,
    ERR_INVALID_SUPPLIER_STATE,
    ERR_LOT_NOT_ACCEPTED,
    ERR_NO_VERIFIED_SUPPLIER,
    ERR_NOMINATION_NOT_FOUND,
    ERR_PATHWAY_NOT_FOUND,
    ERR_SAF_CERTIFICATION_REQUIRED,
    ERR_SAF_SPEC_OUT_OF_RANGE,
    ERR_TURNAROUND_WINDOW_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_activity_index,
    assert_fields_null,
    assert_mass,
    assert_money,
    assert_one_decimal,
    assert_timestamp_equals,
)
from test_helpers.test_users import (
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
    VERIFIER_HEADERS,
)
from test_helpers.types import (
    ALLOC_RELEASED,
    ALLOC_RESERVED,
    BLOCK_DRAFT,
    BLOCK_SUBMITTED_FOR_VERIFICATION,
    CERT_DECISION_CERTIFY,
    CERT_PENDING,
    CERT_UNCERTIFIED,
    CHARGE_ACTIVE,
    CHARGE_REMOVED,
    DD_PENDING,
    DD_SUSPENDED,
    DD_VERIFIED,
    DIST_IN_TANK,
    DIST_RESERVED,
    DIST_SHIPPED,
    DOC_MASS_BALANCE_STATEMENT,
    DOC_ORIGIN_ATTESTATION,
    FEEDSTOCK_UCO,
    HEDGE_UNWOUND,
    INSTRUMENT_RIN_FORWARD,
    LOT_RECEIVED,
    OUTCOME_NONE,
    PATHWAY_DRAFT,
    PRODUCT_SAF,
    RELEASE_MANUAL,
)

# Identifiers that resolve to nothing in any aggregate.
FAKE_UNIT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
FAKE_WINDOW_ID = "aaaaaaaa-0000-0000-0000-000000000002"
FAKE_NOMINATION_ID = "aaaaaaaa-0000-0000-0000-000000000003"
FAKE_ALLOCATION_ID = "aaaaaaaa-0000-0000-0000-000000000004"
FAKE_BATCH_ID = "aaaaaaaa-0000-0000-0000-000000000005"
FAKE_PATHWAY_ID = "aaaaaaaa-0000-0000-0000-000000000006"
FAKE_BLOCK_ID = "aaaaaaaa-0000-0000-0000-000000000007"
FAKE_CHARGE_ID = "aaaaaaaa-0000-0000-0000-000000000008"


def test_a_fabricated_hedge_position_id_reads_back_as_a_not_found(api):
    """PRD §2.7: "one of `ERR_SUPPLIER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_TURNAROUND_WINDOW_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`,
    `ERR_RUN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_PATHWAY_NOT_FOUND`, `ERR_CREDIT_BLOCK_NOT_FOUND` or `ERR_HEDGE_POSITION_NOT_FOUND`,
    all 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."

    Design: Corner/errors/unknown_hedge_position_id_returns_not_found
    """
    response = api.get_hedge_position(NON_EXISTENT_UUID, TRADER_HEADERS)

    validate_error(response, ERR_HEDGE_POSITION_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error", f"got {body['response_type']}"
    assert body["data"]["error_id"] == ERR_HEDGE_POSITION_NOT_FOUND
    assert body["data"]["message"], "the envelope carries a human-readable message"

    _, meta = validate_paginated(api.list_hedge_positions(TRADER_HEADERS))
    assert meta["total_count"] == 0, f"the read minted nothing, got {meta['total_count']}"


def test_the_second_unwind_cannot_overwrite_the_first_settlement(api):
    """PRD §3.9: "A `FeedstockTrader` unwinds an `OPEN` position by supplying
    `settlement_price_usd`, the settlement price per unit; unwinding an already-`UNWOUND`
    position is refused with `ERR_INVALID_HEDGE_STATE`."
    PRD §3.9: "stamps `realized_pnl_usd` as the settlement price less the `strike_price_usd`,
    multiplied by `notional_units`, rounded half up to 2 decimal places"

    Design: Corner/errors/second_unwind_returns_invalid_hedge_state
    """
    position = fx.make_hedge(
        api,
        instrument=INSTRUMENT_RIN_FORWARD,
        notional_units=10000,
        strike_price_usd=2.50,
        maturity_at="2026-12-31T00:00:00Z",
    )

    unwound = validate_success(
        api.unwind_hedge_position(position["id"], f.unwind_payload(3.00), TRADER_HEADERS)
    )
    assert unwound["status"] == HEDGE_UNWOUND, f"got {unwound['status']}"
    assert_money(unwound["realized_pnl_usd"], 5000.00, "realized_pnl_usd")

    validate_error(
        api.unwind_hedge_position(position["id"], f.unwind_payload(1.00), TRADER_HEADERS),
        ERR_INVALID_HEDGE_STATE,
    )

    frozen = validate_success(api.get_hedge_position(position["id"], OFFICER_A_HEADERS))
    assert frozen["status"] == HEDGE_UNWOUND, f"got {frozen['status']}"
    assert_money(frozen["settlement_price_usd"], 3.00, "settlement_price_usd")
    assert_money(frozen["realized_pnl_usd"], 5000.00, "realized_pnl_usd")
    assert frozen["version"] == unwound["version"], (
        f"the refused unwind bumped nothing, got {frozen['version']}"
    )


def test_a_pathway_with_only_a_pending_supplier_cannot_be_submitted(api):
    """PRD §3.8: "A `ComplianceOfficer` may submit from `DRAFT` or from `RETURNED_FOR_INFO`, and
    both paths require that at least one supplier exists whose `dd_status` is `VERIFIED`, whose
    `dd_expires_at` is strictly after the current logical clock, and whose `feedstock_types`
    contains the pathway's `feedstock_type`."
    PRD §3.8: "A pathway whose only candidate suppliers are `PENDING`, `SUSPENDED` or expired is
    refused with `ERR_NO_VERIFIED_SUPPLIER` — the plant may not claim a pathway it has no lawful
    way to feed."

    Design: Corner/errors/pathway_submission_without_a_verified_supplier_returns_error
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    unit = fx.make_unit(api)
    pathway = fx.make_pathway(api, unit["id"], feedstock_type=FEEDSTOCK_UCO)
    assert pathway["status"] == PATHWAY_DRAFT, f"got {pathway['status']}"

    validate_error(api.submit_pathway(pathway["id"], OFFICER_A_HEADERS), ERR_NO_VERIFIED_SUPPLIER)

    still_draft = validate_success(api.get_pathway(pathway["id"], OFFICER_A_HEADERS))
    assert still_draft["status"] == PATHWAY_DRAFT, f"got {still_draft['status']}"
    assert still_draft["version"] == 1, f"the refusal wrote nothing, got {still_draft['version']}"
    assert_fields_null(still_draft, "info_request", "certified_ci_gco2e_per_mj")

    unverified = validate_success(api.get_supplier(supplier["id"], OFFICER_A_HEADERS))
    assert unverified["dd_status"] == DD_PENDING, f"got {unverified['dd_status']}"
    assert unverified["dd_document_type_count"] == 0, (
        f"got {unverified['dd_document_type_count']}"
    )


def test_a_charge_retired_by_a_swap_can_no_longer_carry_a_campaign(api):
    """PRD §3.3: "When the unit already carries a charge in `ACTIVE`, `DERATED` or `SPENT`,
    installing a successor is a swap and the unit must be `DOWN_TURNAROUND` at that moment; the
    outgoing charge — which must be the unit's current `active_catalyst_charge_id` — moves to
    `REMOVED` and has its `version` bumped."
    PRD §3.5: "And the cited catalyst charge must be `ACTIVE`; citing a `REMOVED`, `SPENT` or
    `DERATED` charge is refused with `ERR_CATALYST_NOT_ACTIVE`."

    Design: Corner/errors/removed_catalyst_charge_returns_catalyst_not_active
    """
    unit = fx.make_unit(api)
    window = fx.make_approved_window(api, unit["id"])
    charge_a = fx.make_charge(api, unit["id"])
    fx.move_clock(api, "2026-08-01T12:00:00Z")
    validate_success(api.start_window(window["id"], OPERATOR_HEADERS))
    charge_b = fx.make_charge(api, unit["id"], installed_at="2026-08-02T12:00:00Z")

    validate_error(
        api.create_processing_run(
            f.processing_run_payload(unit["id"], charge_a["id"], target_saf_share_pct=0.00),
            OPERATOR_HEADERS,
        ),
        ERR_CATALYST_NOT_ACTIVE,
    )

    charges = {
        row["id"]: row
        for row in get_success_data(api.list_catalyst_charges(unit["id"], OPERATOR_HEADERS))
    }
    assert charges[charge_a["id"]]["status"] == CHARGE_REMOVED, (
        f"the incumbent was swapped out, got {charges[charge_a['id']]['status']}"
    )
    assert charges[charge_b["id"]]["status"] == CHARGE_ACTIVE, (
        f"got {charges[charge_b['id']]['status']}"
    )
    assert_activity_index(charges[charge_b["id"]]["activity_index"], 1.0000)

    loaded = validate_success(api.get_unit(unit["id"], OPERATOR_HEADERS))
    assert loaded["active_catalyst_charge_id"] == charge_b["id"], (
        f"got {loaded['active_catalyst_charge_id']}"
    )
    assert loaded["requires_turnaround"] is False

    run = validate_success(
        api.create_processing_run(
            f.processing_run_payload(unit["id"], charge_b["id"], target_saf_share_pct=0.00),
            OPERATOR_HEADERS,
        ),
        201,
    )
    assert run["catalyst_charge_id"] == charge_b["id"], f"got {run['catalyst_charge_id']}"


def test_a_warm_freeze_point_blocks_certification_and_then_shipment(api):
    """PRD §3.7: "but for a batch whose `product_type` is `SAF` two additional conditions apply:
    the recorded `freeze_point_c` must be at or below -40.0 degrees Celsius, and the recorded
    `astm_annex` must be present."
    PRD §3.7: "A SAF batch recorded at -39.9 degrees is warmer than the limit and is refused with
    `ERR_SAF_SPEC_OUT_OF_RANGE`; the same code covers a missing annex."
    PRD §3.7: "Reserving a `SHIPPED` batch, or shipping one still `IN_TANK`, is refused with
    `ERR_INVALID_BATCH_DISTRIBUTION_STATE`."
    PRD §3.7: "a batch whose `product_type` is `SAF` may not ship unless its `cert_status` is
    `CERTIFIED`"

    Design: Corner/errors/saf_freeze_point_above_limit_returns_spec_out_of_range
    """
    ctx = fx.completed_campaign(
        api, measured_rd_mt=295.000, measured_saf_mt=32.000, target_saf_share_pct=10.00
    )
    batch = fx.find_batch(api, ctx["run"]["id"], PRODUCT_SAF)
    assert_mass(batch["mass_mt"], 32.000, "mass_mt")
    assert_one_decimal(batch["volume_gal"], 10304.0, "volume_gal")

    filed = validate_success(
        api.request_certification(
            batch["id"], f.certification_request_payload(freeze_point_c=-38.0), OFFICER_A_HEADERS
        )
    )
    assert filed["cert_status"] == CERT_PENDING, f"got {filed['cert_status']}"

    validate_error(
        api.decide_certification(
            batch["id"], f.certification_decision_payload(CERT_DECISION_CERTIFY), VERIFIER_HEADERS
        ),
        ERR_SAF_SPEC_OUT_OF_RANGE,
        422,
    )

    held = validate_success(api.get_product_batch(batch["id"], OFFICER_A_HEADERS))
    assert held["cert_status"] == CERT_PENDING, f"got {held['cert_status']}"
    assert held["distribution_status"] == DIST_IN_TANK, f"got {held['distribution_status']}"

    validate_error(
        api.ship_batch(batch["id"], OFFICER_A_HEADERS), ERR_INVALID_BATCH_DISTRIBUTION_STATE
    )

    reserved = validate_success(
        api.reserve_batch(batch["id"], f.reservation_payload(), OFFICER_A_HEADERS)
    )
    assert reserved["distribution_status"] == DIST_RESERVED, (
        f"reserving uncertified aviation fuel is legal, got {reserved['distribution_status']}"
    )

    validate_error(api.ship_batch(batch["id"], OFFICER_A_HEADERS), ERR_SAF_CERTIFICATION_REQUIRED)

    grounded = validate_success(api.get_product_batch(batch["id"], OFFICER_A_HEADERS))
    assert grounded["distribution_status"] == DIST_RESERVED, (
        f"got {grounded['distribution_status']}"
    )
    assert grounded["cert_status"] == CERT_PENDING, f"got {grounded['cert_status']}"


def test_each_aggregate_reports_its_own_flavour_of_not_found(api):
    """PRD §2.7: "Every resource named by a path segment exists, validated left to right"
    PRD §2.7: "Every identifier supplied in the request body resolves to an existing row —
    `supplier_id`, `lot_id`, `unit_id`, `catalyst_charge_id`, `run_id`, `batch_id` and
    `pathway_id` are screened here, reporting `ERR_SUPPLIER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_CATALYST_CHARGE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
    `ERR_BATCH_NOT_FOUND` or `ERR_PATHWAY_NOT_FOUND` as appropriate, all 404."

    Design: Corner/errors/unknown_ids_across_every_aggregate_return_not_found
    """
    unit = fx.make_unit(api)

    validate_error(api.get_unit(FAKE_UNIT_ID, OPERATOR_HEADERS), ERR_UNIT_NOT_FOUND, 404)
    validate_error(
        api.approve_window(FAKE_WINDOW_ID, OPERATOR_HEADERS),
        ERR_TURNAROUND_WINDOW_NOT_FOUND,
        404,
    )
    validate_error(
        api.cancel_nomination(FAKE_NOMINATION_ID, OPERATOR_HEADERS), ERR_NOMINATION_NOT_FOUND, 404
    )
    validate_error(
        api.release_allocation(FAKE_ALLOCATION_ID, TRADER_HEADERS), ERR_ALLOCATION_NOT_FOUND, 404
    )
    validate_error(
        api.get_product_batch(FAKE_BATCH_ID, OFFICER_A_HEADERS), ERR_BATCH_NOT_FOUND, 404
    )
    validate_error(api.get_pathway(FAKE_PATHWAY_ID, OFFICER_A_HEADERS), ERR_PATHWAY_NOT_FOUND, 404)
    validate_error(
        api.retire_credits(FAKE_BLOCK_ID, f.retirement_payload(1.000), OFFICER_A_HEADERS),
        ERR_CREDIT_BLOCK_NOT_FOUND,
        404,
    )

    body_fk = api.create_processing_run(
        f.processing_run_payload(unit["id"], FAKE_CHARGE_ID), OPERATOR_HEADERS
    )
    validate_error(body_fk, ERR_CATALYST_CHARGE_NOT_FOUND, 404)
    assert body_fk.json()["data"]["error_id"] != ERR_UNIT_NOT_FOUND, (
        "the unit resolves, so the body-FK rung must report the charge"
    )

    _, meta = validate_paginated(api.list_processing_runs(OFFICER_A_HEADERS))
    assert meta["total_count"] == 0, f"no row survived any refusal, got {meta['total_count']}"


def test_suspension_closes_the_door_on_verification_and_on_itself(api):
    """PRD §3.1: "Attempting to verify a supplier that is not `PENDING` — one already `VERIFIED`,
    or one `SUSPENDED` — is a state failure reported as `ERR_INVALID_SUPPLIER_STATE`."
    PRD §3.1: "`SUSPENDED` is terminal: there is no path back, and a second suspension attempt on
    an already-suspended supplier is refused with `ERR_INVALID_SUPPLIER_STATE`."
    PRD §3.1: "sets `dd_expires_at` to the current logical clock advanced by `valid_months`
    multiplied by 30 days (months are treated as exactly 30 days each, never as calendar months)"

    Design: Corner/errors/suspended_supplier_transitions_are_rejected
    """
    supplier = fx.documented_supplier(
        api, doc_types=(DOC_ORIGIN_ATTESTATION, DOC_MASS_BALANCE_STATEMENT)
    )

    verified = validate_success(
        api.verify_due_diligence(
            supplier["id"], f.due_diligence_payload(valid_months=12), OFFICER_A_HEADERS
        )
    )
    assert verified["dd_status"] == DD_VERIFIED, f"got {verified['dd_status']}"
    assert_timestamp_equals(verified["dd_verified_at"], "2026-08-01T00:00:00Z", "dd_verified_at")
    assert_timestamp_equals(verified["dd_expires_at"], "2027-07-27T00:00:00Z", "dd_expires_at")

    suspended = validate_success(
        api.suspend_supplier(supplier["id"], f.suspension_payload(), OFFICER_A_HEADERS)
    )
    assert suspended["dd_status"] == DD_SUSPENDED, f"got {suspended['dd_status']}"

    validate_error(
        api.verify_due_diligence(
            supplier["id"], f.due_diligence_payload(valid_months=12), OFFICER_A_HEADERS
        ),
        ERR_INVALID_SUPPLIER_STATE,
    )
    validate_error(
        api.suspend_supplier(
            supplier["id"],
            f.suspension_payload(reason="Duplicate suspension attempt"),
            OFFICER_A_HEADERS,
        ),
        ERR_INVALID_SUPPLIER_STATE,
    )

    final = validate_success(api.get_supplier(supplier["id"], OFFICER_A_HEADERS))
    assert final["dd_status"] == DD_SUSPENDED, f"got {final['dd_status']}"
    assert final["dd_document_type_count"] == 2, f"got {final['dd_document_type_count']}"
    assert final["suspension_reason"] == suspended["suspension_reason"], (
        f"the refused second suspension overwrote the reason: {final['suspension_reason']}"
    )
    assert final["version"] == suspended["version"], (
        f"two refusals bumped nothing, got {final['version']}"
    )


def test_an_untested_lot_and_a_twice_released_line_are_both_refused(api):
    """PRD §3.5: "A `RECEIVED`, `TESTED`, `PRETREATED`, `REJECTED`, `CHARGED` or `QUARANTINED` lot
    yields `ERR_LOT_NOT_ACCEPTED`."
    PRD §3.5: "Release sets `release_reason` to `MANUAL`, restores the mass to the lot (lowering
    `allocated_mass_mt`, raising `remaining_mass_mt`), lowers the campaign's `reserved_mass_mt`,
    recomputes the campaign's `blend_ci_gco2e_per_mj` and `required_h2_kg_per_day` over the
    allocations that still count — both returning to null when none remain — and bumps the
    allocation's, the lot's and the campaign's `version`."
    PRD §3.5: "Releasing an allocation that is already `CONSUMED` because the campaign started, or
    one that is already `RELEASED`, is refused with `ERR_INVALID_ALLOCATION_STATE`."

    Design: Corner/errors/unaccepted_lot_and_double_release_are_rejected
    """
    supplier = fx.verified_supplier(
        api, doc_types=(DOC_ORIGIN_ATTESTATION, DOC_MASS_BALANCE_STATEMENT)
    )
    lot_a = fx.make_lot(api, supplier["id"], mass_mt=200.000)
    lot_b = fx.accepted_lot(api, supplier["id"], mass_mt=200.000)
    plant = fx.commissioned_unit(api)
    run = fx.make_run(api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=0.00)

    validate_error(
        api.create_allocation(
            run["id"], f.allocation_payload(lot_a["id"], 100.000, run["version"]), TRADER_HEADERS
        ),
        ERR_LOT_NOT_ACCEPTED,
    )
    untouched = validate_success(api.get_feedstock_lot(lot_a["id"], TRADER_HEADERS))
    assert untouched["status"] == LOT_RECEIVED, f"got {untouched['status']}"
    assert_mass(untouched["allocated_mass_mt"], 0.000, "allocated_mass_mt")

    allocation = validate_success(
        api.create_allocation(
            run["id"], f.allocation_payload(lot_b["id"], 200.000, run["version"]), TRADER_HEADERS
        ),
        201,
    )
    assert allocation["status"] == ALLOC_RESERVED, f"got {allocation['status']}"
    charged = validate_success(api.get_processing_run(run["id"], TRADER_HEADERS))
    assert_mass(charged["reserved_mass_mt"], 200.000, "reserved_mass_mt")
    assert charged["blend_ci_gco2e_per_mj"] == 32.50, f"got {charged['blend_ci_gco2e_per_mj']}"

    released = validate_success(api.release_allocation(allocation["id"], TRADER_HEADERS))
    assert released["status"] == ALLOC_RELEASED, f"got {released['status']}"
    assert released["release_reason"] == RELEASE_MANUAL, f"got {released['release_reason']}"
    emptied = validate_success(api.get_processing_run(run["id"], TRADER_HEADERS))
    assert_mass(emptied["reserved_mass_mt"], 0.000, "reserved_mass_mt")
    assert_fields_null(emptied, "blend_ci_gco2e_per_mj", "required_h2_kg_per_day")

    validate_error(
        api.release_allocation(allocation["id"], TRADER_HEADERS), ERR_INVALID_ALLOCATION_STATE
    )

    restored = validate_success(api.get_feedstock_lot(lot_b["id"], TRADER_HEADERS))
    assert_mass(restored["remaining_mass_mt"], 200.000, "remaining_mass_mt")
    assert_mass(restored["allocated_mass_mt"], 0.000, "allocated_mass_mt")


def test_a_batch_never_filed_and_a_block_never_signed_off_are_out_of_order(api):
    """PRD §3.7: "Deciding on a batch that is not `CERT_PENDING` — an `UNCERTIFIED` batch, for
    instance — is refused with `ERR_INVALID_BATCH_CERT_STATE`."
    PRD §3.8: "Submitting a block still in `DRAFT` is refused with
    `ERR_INVALID_CREDIT_BLOCK_STATE`."
    PRD §3.8: "A `ComplianceOfficer` signs off a `DRAFT` block, which moves `DRAFT →
    INTERNAL_SIGNED_OFF` and records the acting `X-User-ID` as the block's
    `signed_off_by_user_id`, bumping the `version`."

    Design: Corner/errors/certification_decision_on_an_uncertified_batch_and_submission_of_a_draft_block_are_rejected
    """
    ctx = fx.credit_ready_campaign(
        api, measured_rd_mt=320.123, measured_saf_mt=0.000, target_saf_share_pct=0.00
    )
    block = fx.make_credit_block(api, ctx["batch"]["id"], ctx["pathway"]["id"])
    assert block["status"] == BLOCK_DRAFT, f"got {block['status']}"
    assert block["verification_outcome"] == OUTCOME_NONE, f"got {block['verification_outcome']}"

    validate_error(
        api.decide_certification(
            ctx["batch"]["id"],
            f.certification_decision_payload(CERT_DECISION_CERTIFY),
            VERIFIER_HEADERS,
        ),
        ERR_INVALID_BATCH_CERT_STATE,
    )
    unfiled = validate_success(api.get_product_batch(ctx["batch"]["id"], OFFICER_A_HEADERS))
    assert unfiled["cert_status"] == CERT_UNCERTIFIED, f"got {unfiled['cert_status']}"
    assert unfiled["distribution_status"] == DIST_SHIPPED, (
        f"the two dimensions stay independent, got {unfiled['distribution_status']}"
    )

    validate_error(
        api.submit_for_verification(block["id"], OFFICER_A_HEADERS),
        ERR_INVALID_CREDIT_BLOCK_STATE,
    )
    still_draft = validate_success(api.get_credit_block(block["id"], OFFICER_A_HEADERS))
    assert still_draft["status"] == BLOCK_DRAFT, f"got {still_draft['status']}"
    assert still_draft["verification_outcome"] == OUTCOME_NONE
    assert_fields_null(still_draft, "signed_off_by_user_id", "verified_ci_gco2e_per_mj")

    validate_success(api.internal_signoff(block["id"], OFFICER_B_HEADERS))
    submitted = validate_success(api.submit_for_verification(block["id"], OFFICER_A_HEADERS))
    assert submitted["status"] == BLOCK_SUBMITTED_FOR_VERIFICATION, f"got {submitted['status']}"
