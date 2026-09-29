"""Composite state builders.

Every builder drives the public API only — there is no back door into the
database — and returns the created rows so tests can assert against them.
All builders use `get_success_data`, so a broken setup step fails loudly with
the server's own error_id rather than surfacing as a mysterious KeyError.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
    VERIFIER_HEADERS,
)
from .types import (
    CERT_DECISION_CERTIFY,
    DOC_CHAIN_OF_CUSTODY,
    DOC_MASS_BALANCE_STATEMENT,
    DOC_ORIGIN_ATTESTATION,
    FEEDSTOCK_SOYBEAN_OIL,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_UCO,
    PRODUCT_RENEWABLE_DIESEL,
    PRODUCT_SAF,
    REVIEW_REGISTER,
    REVIEW_RETURN,
    SCOPE_INSPECTION,
    VERIFICATION_VERIFY,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def move_clock(api, instant, headers=OPERATOR_HEADERS) -> dict:
    """Advance (or rewind) the logical clock and return the clock payload."""
    return get_success_data(api.set_clock(instant, headers))


# ---------------------------------------------------------------------------
# Tier 2 — hydrotreating unit hierarchy
# ---------------------------------------------------------------------------
def make_unit(api, headers=OPERATOR_HEADERS, **overrides) -> dict:
    return get_success_data(api.create_unit(f.unit_payload(**overrides), headers))


def make_window(api, unit_id, headers=OPERATOR_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_turnaround_window(unit_id, f.turnaround_window_payload(**overrides), headers)
    )


def make_approved_window(api, unit_id, headers=OPERATOR_HEADERS, **overrides) -> dict:
    window = make_window(api, unit_id, headers=headers, **overrides)
    return get_success_data(api.approve_window(window["id"], headers))


def make_charge(api, unit_id, headers=OPERATOR_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_catalyst_charge(unit_id, f.catalyst_charge_payload(**overrides), headers)
    )


def commissioned_unit(api, headers=OPERATOR_HEADERS, unit=None, charge=None) -> dict:
    """A unit with an approved CATALYST_CHANGE window and one ACTIVE charge.

    The window covers [2026-08-01T00:00:00Z, 2026-08-03T00:00:00Z) and the
    charge is installed at 2026-08-02T00:00:00Z, inside that half-open window.
    Returns {"unit", "window", "charge"}.
    """
    unit_row = make_unit(api, headers=headers, **(unit or {}))
    window_row = make_approved_window(api, unit_row["id"], headers=headers)
    charge_row = make_charge(api, unit_row["id"], headers=headers, **(charge or {}))
    return {"unit": unit_row, "window": window_row, "charge": charge_row}


# ---------------------------------------------------------------------------
# Tier 1 — supplier due-diligence progression
# ---------------------------------------------------------------------------
def make_supplier(api, headers=TRADER_HEADERS, **overrides) -> dict:
    return get_success_data(api.create_supplier(f.supplier_payload(**overrides), headers))


def add_document(api, supplier_id, headers=TRADER_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_traceability_document(
            supplier_id, f.traceability_document_payload(**overrides), headers
        )
    )


def documented_supplier(
    api,
    doc_types=(DOC_ORIGIN_ATTESTATION, DOC_CHAIN_OF_CUSTODY),
    headers=TRADER_HEADERS,
    **overrides,
) -> dict:
    """A PENDING supplier carrying one valid document of each named type."""
    supplier = make_supplier(api, headers=headers, **overrides)
    for doc_type in doc_types:
        add_document(api, supplier["id"], headers=headers, doc_type=doc_type)
    return supplier


def verified_supplier(
    api,
    doc_types=(DOC_ORIGIN_ATTESTATION, DOC_CHAIN_OF_CUSTODY),
    valid_months=12,
    officer_headers=OFFICER_A_HEADERS,
    **overrides,
) -> dict:
    """A supplier whose due diligence has been verified for `valid_months`."""
    supplier = documented_supplier(api, doc_types=doc_types, **overrides)
    return get_success_data(
        api.verify_due_diligence(
            supplier["id"], f.due_diligence_payload(valid_months=valid_months), officer_headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — feedstock lot progression
# ---------------------------------------------------------------------------
def make_lot(api, supplier_id, headers=TRADER_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_feedstock_lot(f.feedstock_lot_payload(supplier_id, **overrides), headers)
    )


def add_quality_test(api, lot_id, lot_version, headers=ANALYST_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_quality_test(lot_id, f.quality_test_payload(lot_version, **overrides), headers)
    )


def tested_lot(api, supplier_id, test=None, **lot_overrides) -> dict:
    """A lot with one quality test appended; returns the refreshed lot row."""
    lot = make_lot(api, supplier_id, **lot_overrides)
    add_quality_test(api, lot["id"], lot["version"], **(test or {}))
    return get_success_data(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))


def accepted_lot(api, supplier_id, test=None, **lot_overrides) -> dict:
    """A lot that passed its quality test and was accepted for charging."""
    lot = make_lot(api, supplier_id, **lot_overrides)
    add_quality_test(api, lot["id"], lot["version"], **(test or {}))
    return get_success_data(api.accept_lot(lot["id"], ANALYST_HEADERS))


# ---------------------------------------------------------------------------
# Tier 2 — hydrogen supply
# ---------------------------------------------------------------------------
def make_contract(api, headers=TRADER_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_hydrogen_contract(f.hydrogen_contract_payload(**overrides), headers)
    )


def make_nomination(api, contract_id, run_id, headers=OPERATOR_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_nomination(contract_id, f.nomination_payload(run_id, **overrides), headers)
    )


# ---------------------------------------------------------------------------
# Tier 2/3 — campaigns and allocations
# ---------------------------------------------------------------------------
def make_run(api, unit_id, charge_id, headers=OPERATOR_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_processing_run(
            f.processing_run_payload(unit_id, charge_id, **overrides), headers
        )
    )


def run_version(api, run_id, headers=OPERATOR_HEADERS) -> int:
    """Read the campaign's current version for an optimistic-concurrency field."""
    return get_success_data(api.get_processing_run(run_id, headers))["version"]


def allocate(api, run_id, lot_id, mass_mt, headers=TRADER_HEADERS, expected_version=None) -> dict:
    """Reserve mass from a lot onto a campaign, reading the fresh run version."""
    version = expected_version if expected_version is not None else run_version(api, run_id)
    return get_success_data(
        api.create_allocation(run_id, f.allocation_payload(lot_id, mass_mt, version), headers)
    )


# ---------------------------------------------------------------------------
# Tier 3 — full campaign lifecycle shortcuts
# ---------------------------------------------------------------------------
def baseline_campaign(
    api,
    target_saf_share_pct=10.00,
    alloc_mass_mt=400.000,
    lot_mass_mt=500.000,
    feedstock_type=FEEDSTOCK_UCO,
    attested_ci=32.50,
    price_usd_per_mt=900.00,
    window_start="2026-09-01T00:00:00Z",
    window_end="2026-09-06T00:00:00Z",
    nomination_kg_per_day=2600.0,
    nomination_start="2026-09-01T00:00:00Z",
    nomination_end="2026-09-05T00:00:00Z",
    secure=True,
) -> dict:
    """The canonical five-day UCO campaign, reserved and (by default) secured.

    Builds: unit HTU (400.0 MT/day, max SAF 40.00%) + approved catalyst-change
    window + ACTIVE charge; a VERIFIED supplier of `feedstock_type` holding one
    ACCEPTED lot; a hydrogen contract of 5000.0 kg/day over
    [2026-08-25, 2026-09-30]; the campaign with one RESERVED allocation and one
    CONFIRMED nomination. Returns every row plus the refreshed campaign.
    """
    plant = commissioned_unit(api)
    supplier = verified_supplier(api, feedstock_types=[feedstock_type])
    lot = accepted_lot(
        api,
        supplier["id"],
        feedstock_type=feedstock_type,
        mass_mt=lot_mass_mt,
        attested_ci_gco2e_per_mj=attested_ci,
        purchase_price_usd_per_mt=price_usd_per_mt,
    )
    contract = make_contract(api)
    run = make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start=window_start,
        window_end=window_end,
        target_saf_share_pct=target_saf_share_pct,
    )
    allocation = allocate(api, run["id"], lot["id"], alloc_mass_mt, expected_version=run["version"])
    nomination = make_nomination(
        api,
        contract["id"],
        run["id"],
        start_at=nomination_start,
        end_at=nomination_end,
        kg_per_day=nomination_kg_per_day,
    )
    if secure:
        run = get_success_data(api.secure_hydrogen(run["id"], OPERATOR_HEADERS))
    else:
        run = get_success_data(api.get_processing_run(run["id"], OPERATOR_HEADERS))
    return {
        "unit": plant["unit"],
        "window": plant["window"],
        "charge": plant["charge"],
        "supplier": supplier,
        "lot": lot,
        "contract": contract,
        "run": run,
        "allocation": allocation,
        "nomination": nomination,
    }


def started_campaign(api, start_instant="2026-09-01T00:00:00Z", **kwargs) -> dict:
    """A secured campaign moved to RUNNING with the clock at its window start."""
    ctx = baseline_campaign(api, **kwargs)
    move_clock(api, start_instant)
    ctx["run"] = get_success_data(api.start_run(ctx["run"]["id"], OPERATOR_HEADERS))
    return ctx


def completed_campaign(
    api,
    measured_rd_mt=290.000,
    measured_saf_mt=30.000,
    start_instant="2026-09-01T00:00:00Z",
    complete_instant="2026-09-06T00:00:00Z",
    **kwargs,
) -> dict:
    """A campaign carried through to COMPLETED with the measured product given."""
    ctx = started_campaign(api, start_instant=start_instant, **kwargs)
    move_clock(api, complete_instant)
    ctx["run"] = get_success_data(
        api.complete_run(
            ctx["run"]["id"], f.completion_payload(measured_rd_mt, measured_saf_mt), OPERATOR_HEADERS
        )
    )
    return ctx


def reconciled_campaign(api, **kwargs) -> dict:
    """A completed campaign settled by the compliance desk."""
    ctx = completed_campaign(api, **kwargs)
    ctx["run"] = get_success_data(api.reconcile_run(ctx["run"]["id"], OFFICER_A_HEADERS))
    return ctx


def find_batch(api, run_id, product_type=PRODUCT_RENEWABLE_DIESEL, headers=OFFICER_A_HEADERS) -> dict:
    """The single batch of `product_type` emitted by the campaign."""
    body = api.list_product_batches(headers, {"run_id": run_id, "product_type": product_type})
    rows = get_success_data(body)
    assert rows, f"no {product_type} batch was emitted by run {run_id}"
    return rows[0]


def certify_batch(api, batch_id, freeze_point_c=-47.0, headers=OFFICER_A_HEADERS) -> dict:
    """Drive a batch UNCERTIFIED -> CERT_PENDING -> CERTIFIED."""
    get_success_data(
        api.request_certification(
            batch_id, f.certification_request_payload(freeze_point_c=freeze_point_c), headers
        )
    )
    return get_success_data(
        api.decide_certification(
            batch_id, f.certification_decision_payload(CERT_DECISION_CERTIFY), VERIFIER_HEADERS
        )
    )


def ship_batch(api, batch_id, offtaker_name="Chevron Products", headers=OFFICER_A_HEADERS) -> dict:
    """Reserve a batch to an offtaker and then ship it."""
    get_success_data(
        api.reserve_batch(batch_id, f.reservation_payload(offtaker_name=offtaker_name), headers)
    )
    return get_success_data(api.ship_batch(batch_id, headers))


# ---------------------------------------------------------------------------
# Tier 3 — pathway registration progression
# ---------------------------------------------------------------------------
def make_pathway(api, unit_id, headers=OFFICER_A_HEADERS, **overrides) -> dict:
    return get_success_data(api.create_pathway(f.pathway_payload(unit_id, **overrides), headers))


def registered_pathway(
    api,
    unit_id,
    certified_ci=41.25,
    officer_headers=OFFICER_A_HEADERS,
    verifier_headers=VERIFIER_HEADERS,
    **overrides,
) -> dict:
    """A pathway driven DRAFT -> SUBMITTED -> UNDER_REVIEW -> REGISTERED."""
    pathway = make_pathway(api, unit_id, headers=officer_headers, **overrides)
    get_success_data(api.submit_pathway(pathway["id"], officer_headers))
    get_success_data(api.start_pathway_review(pathway["id"], verifier_headers))
    return get_success_data(
        api.decide_pathway_review(
            pathway["id"],
            f.review_decision_payload(REVIEW_REGISTER, certified_ci=certified_ci),
            verifier_headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 4/5 — credit blocks
# ---------------------------------------------------------------------------
def make_credit_block(api, batch_id, pathway_id, headers=OFFICER_A_HEADERS) -> dict:
    return get_success_data(
        api.create_credit_block(f.credit_block_payload(batch_id, pathway_id), headers)
    )


def submitted_credit_block(
    api,
    batch_id,
    pathway_id,
    minting_headers=OFFICER_A_HEADERS,
    signoff_headers=OFFICER_B_HEADERS,
) -> dict:
    """A block minted by one officer, signed off and submitted by another.

    The two officers must differ: sign-off compares the acting user id against
    the pathway's registering user id.
    """
    block = make_credit_block(api, batch_id, pathway_id, headers=minting_headers)
    get_success_data(api.internal_signoff(block["id"], signoff_headers))
    return get_success_data(api.submit_for_verification(block["id"], signoff_headers))


def verified_credit_block(api, batch_id, pathway_id, verified_ci=41.25, **kwargs) -> dict:
    """A submitted block carried through a VERIFY decision at `verified_ci`."""
    block = submitted_credit_block(api, batch_id, pathway_id, **kwargs)
    return get_success_data(
        api.decide_verification(
            block["id"],
            f.verification_decision_payload(VERIFICATION_VERIFY, verified_ci=verified_ci),
            VERIFIER_HEADERS,
        )
    )


def credit_ready_campaign(api, product_type=PRODUCT_RENEWABLE_DIESEL, **kwargs) -> dict:
    """A RECONCILED campaign whose batch is SHIPPED behind a REGISTERED pathway.

    Adds "batch" and "pathway" to the `reconciled_campaign` context. SAF batches
    are certified before shipping, since SAF may not ship uncertified.
    """
    ctx = reconciled_campaign(api, **kwargs)
    batch = find_batch(api, ctx["run"]["id"], product_type)
    if product_type != PRODUCT_RENEWABLE_DIESEL:
        certify_batch(api, batch["id"])
    ship_batch(api, batch["id"])
    ctx["batch"] = get_success_data(api.get_product_batch(batch["id"], OFFICER_A_HEADERS))
    ctx["pathway"] = registered_pathway(api, ctx["unit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Hedges
# ---------------------------------------------------------------------------
def make_hedge(api, headers=TRADER_HEADERS, **overrides) -> dict:
    return get_success_data(api.create_hedge_position(f.hedge_position_payload(**overrides), headers))


# ---------------------------------------------------------------------------
# Multi-line campaigns (settlement arithmetic)
# ---------------------------------------------------------------------------
def campaign_with_lot_lines(
    api,
    lines,
    feedstock_type=FEEDSTOCK_UCO,
    attested_ci=32.50,
    target_saf_share_pct=0.00,
    window_start="2026-09-01T00:00:00Z",
    window_end="2026-09-06T00:00:00Z",
    nomination_kg_per_day=900.0,
    nomination_start="2026-09-01T00:00:00Z",
    nomination_end="2026-09-05T00:00:00Z",
    doc_types=(DOC_ORIGIN_ATTESTATION, DOC_MASS_BALANCE_STATEMENT),
    secure=True,
) -> dict:
    """A campaign carrying one fully allocated lot per entry in `lines`.

    `lines` is a sequence of ``(mass_mt, purchase_price_usd_per_mt)`` pairs; each
    becomes its own ACCEPTED lot allocated in full, in the order given, so the
    allocations' `created_at` order matches the sequence. Returns
    {"unit", "charge", "supplier", "contract", "run", "lots", "allocations"}.
    """
    plant = commissioned_unit(api)
    supplier = verified_supplier(api, doc_types=doc_types, feedstock_types=[feedstock_type])
    contract = make_contract(api)
    run = make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start=window_start,
        window_end=window_end,
        target_saf_share_pct=target_saf_share_pct,
    )
    lots = []
    allocations = []
    for mass_mt, price in lines:
        lot = accepted_lot(
            api,
            supplier["id"],
            feedstock_type=feedstock_type,
            mass_mt=mass_mt,
            attested_ci_gco2e_per_mj=attested_ci,
            purchase_price_usd_per_mt=price,
        )
        lots.append(lot)
        allocations.append(allocate(api, run["id"], lot["id"], mass_mt))
    make_nomination(
        api,
        contract["id"],
        run["id"],
        start_at=nomination_start,
        end_at=nomination_end,
        kg_per_day=nomination_kg_per_day,
    )
    if secure:
        run = get_success_data(api.secure_hydrogen(run["id"], OPERATOR_HEADERS))
    else:
        run = get_success_data(api.get_processing_run(run["id"], OPERATOR_HEADERS))
    return {
        "unit": plant["unit"],
        "charge": plant["charge"],
        "supplier": supplier,
        "contract": contract,
        "run": run,
        "lots": lots,
        "allocations": allocations,
    }


def reconciled_campaign_with_lot_lines(
    api,
    lines,
    measured_rd_mt,
    measured_saf_mt=0.000,
    start_instant="2026-09-01T00:00:00Z",
    complete_instant="2026-09-06T00:00:00Z",
    **kwargs,
) -> dict:
    """`campaign_with_lot_lines` carried through start, completion and settlement."""
    ctx = campaign_with_lot_lines(api, lines, **kwargs)
    move_clock(api, start_instant)
    get_success_data(api.start_run(ctx["run"]["id"], OPERATOR_HEADERS))
    move_clock(api, complete_instant)
    get_success_data(
        api.complete_run(
            ctx["run"]["id"],
            f.completion_payload(measured_rd_mt, measured_saf_mt),
            OPERATOR_HEADERS,
        )
    )
    ctx["run"] = get_success_data(api.reconcile_run(ctx["run"]["id"], OFFICER_A_HEADERS))
    ctx["allocations"] = get_success_data(
        api.list_run_allocations(ctx["run"]["id"], OFFICER_A_HEADERS, {"limit": 100})
    )
    return ctx


def registrable_unit(api, feedstock_type=FEEDSTOCK_UCO) -> dict:
    """A unit plus a VERIFIED supplier of `feedstock_type`.

    A pathway submission requires at least one verified, unexpired supplier
    declaring the pathway's feedstock class, so both halves are needed before a
    registration can leave DRAFT. Returns {"unit", "supplier"}.
    """
    return {
        "unit": make_unit(api),
        "supplier": verified_supplier(api, feedstock_types=[feedstock_type]),
    }


def returned_pathway(
    api,
    unit_id,
    laps=1,
    officer_headers=OFFICER_A_HEADERS,
    verifier_headers=VERIFIER_HEADERS,
    **overrides,
) -> dict:
    """A pathway walked around the return/resubmit loop `laps` times.

    Each lap is submit -> review-start -> RETURN, so the registration ends at
    RETURNED_FOR_INFO carrying the info request of the final lap.
    """
    pathway = make_pathway(api, unit_id, headers=officer_headers, **overrides)
    for lap in range(1, laps + 1):
        get_success_data(api.submit_pathway(pathway["id"], officer_headers))
        get_success_data(api.start_pathway_review(pathway["id"], verifier_headers))
        get_success_data(
            api.decide_pathway_review(
                pathway["id"],
                f.review_decision_payload(
                    REVIEW_RETURN,
                    info_request=f"Provide the mass-balance ledger for round {lap}.",
                ),
                verifier_headers,
            )
        )
    return get_success_data(api.get_pathway(pathway["id"], officer_headers))


def reserved_saf_batch(api, offtaker_name="Delta Air Lines", **kwargs) -> dict:
    """A campaign whose SAF batch is RESERVED to an offtaker but still UNCERTIFIED.

    Adds "batch" to the `completed_campaign` context.
    """
    ctx = completed_campaign(api, **kwargs)
    batch = find_batch(api, ctx["run"]["id"], PRODUCT_SAF)
    ctx["batch"] = get_success_data(
        api.reserve_batch(
            batch["id"], f.reservation_payload(offtaker_name=offtaker_name), OFFICER_A_HEADERS
        )
    )
    return ctx


def two_run_credit_portfolio(api) -> dict:
    """Two campaigns drawn from one lot, three shipped batches, three credit blocks.

    Campaign 1 over [2026-09-01, 2026-09-06) consumes 400.000 MT at a 10.00 percent
    aviation target and completes at 290.000 RD / 30.000 SAF; campaign 2 over
    [2026-09-10, 2026-09-13) consumes the remaining 100.000 MT at a 0.00 percent
    target and completes at 80.000 RD. Both are RECONCILED and all three batches are
    shipped, the aviation one certified first. One REGISTERED LCFS pathway for UCO
    covers the unit. Blocks A (campaign 1 RD) and B (campaign 1 SAF) are submitted
    for verification; block C (campaign 2 RD) is left in DRAFT.

    Adds "run2", "batch_rd1", "batch_saf1", "batch_rd2", "pathway", "block_a",
    "block_b" and "block_c" to the `reconciled_campaign` context.
    """
    ctx = reconciled_campaign(api, target_saf_share_pct=10.00)

    run2 = make_run(
        api,
        ctx["unit"]["id"],
        ctx["charge"]["id"],
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-13T00:00:00Z",
        target_saf_share_pct=0.00,
    )
    allocate(api, run2["id"], ctx["lot"]["id"], 100.000, expected_version=run2["version"])
    make_nomination(
        api,
        ctx["contract"]["id"],
        run2["id"],
        start_at="2026-09-10T00:00:00Z",
        end_at="2026-09-12T00:00:00Z",
        kg_per_day=1100.0,
    )
    get_success_data(api.secure_hydrogen(run2["id"], OPERATOR_HEADERS))
    move_clock(api, "2026-09-10T00:00:00Z")
    get_success_data(api.start_run(run2["id"], OPERATOR_HEADERS))
    move_clock(api, "2026-09-13T00:00:00Z")
    get_success_data(
        api.complete_run(run2["id"], f.completion_payload(80.000, 0.000), OPERATOR_HEADERS)
    )
    ctx["run2"] = get_success_data(api.reconcile_run(run2["id"], OFFICER_A_HEADERS))

    rd1 = find_batch(api, ctx["run"]["id"], PRODUCT_RENEWABLE_DIESEL)
    saf1 = find_batch(api, ctx["run"]["id"], PRODUCT_SAF)
    rd2 = find_batch(api, ctx["run2"]["id"], PRODUCT_RENEWABLE_DIESEL)
    ship_batch(api, rd1["id"])
    certify_batch(api, saf1["id"])
    ctx["batch_saf1"] = ship_batch(api, saf1["id"], offtaker_name="Delta Air Lines")
    ctx["batch_rd2"] = ship_batch(api, rd2["id"])
    ctx["batch_rd1"] = get_success_data(api.get_product_batch(rd1["id"], OFFICER_A_HEADERS))

    ctx["pathway"] = registered_pathway(api, ctx["unit"]["id"])
    ctx["block_a"] = submitted_credit_block(api, rd1["id"], ctx["pathway"]["id"])
    ctx["block_b"] = submitted_credit_block(api, saf1["id"], ctx["pathway"]["id"])
    ctx["block_c"] = make_credit_block(api, rd2["id"], ctx["pathway"]["id"])
    return ctx


def running_and_planned_runs(api) -> dict:
    """A RUNNING campaign, a still-PLANNED one, and a thin 50.000 MT spare lot.

    The campaign in "run" was secured and then started at 2026-09-01T00:00:00Z, so
    its 400.000 MT line is CONSUMED. "lot2" holds 50.000 MT ACCEPTED and is
    deliberately too thin for a 200.000 MT commitment. Adds "lot2" and "run2" to
    the `baseline_campaign` context; the clock is left at 2026-09-01T00:00:00Z.
    """
    ctx = baseline_campaign(api, target_saf_share_pct=0.00)
    ctx["lot2"] = accepted_lot(
        api,
        ctx["supplier"]["id"],
        feedstock_type=FEEDSTOCK_UCO,
        mass_mt=50.000,
        attested_ci_gco2e_per_mj=32.50,
        purchase_price_usd_per_mt=900.00,
    )
    ctx["run2"] = make_run(
        api,
        ctx["unit"]["id"],
        ctx["charge"]["id"],
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-13T00:00:00Z",
        target_saf_share_pct=0.00,
    )
    move_clock(api, "2026-09-01T00:00:00Z")
    ctx["run"] = get_success_data(api.start_run(ctx["run"]["id"], OPERATOR_HEADERS))
    return ctx


def pretreatment_owed_lot_and_run(api, valid_months=1) -> dict:
    """A heavy TALLOW lot owing pretreatment behind a short-dated verification.

    The supplier is verified for `valid_months` at the default clock, the 300.000 MT
    lot sits at PRETREAT_REQUIRED on tier HEAVY, and the campaign over
    [2026-09-10, 2026-09-13) is still PLANNED. Returns {"supplier", "lot", "run"}.
    """
    plant = commissioned_unit(api)
    supplier = verified_supplier(
        api, feedstock_types=[FEEDSTOCK_TALLOW], valid_months=valid_months
    )
    lot = tested_lot(
        api,
        supplier["id"],
        test={
            "ffa_pct": 6.00,
            "moisture_pct": 0.20,
            "insolubles_ppm": 100,
            "phosphorus_ppm": 5,
            "sampled_at": "2026-08-01T00:00:00Z",
        },
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=300.000,
        attested_ci_gco2e_per_mj=41.00,
        purchase_price_usd_per_mt=780.00,
    )
    run = make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-13T00:00:00Z",
        target_saf_share_pct=0.00,
    )
    return {"unit": plant["unit"], "charge": plant["charge"], "supplier": supplier, "lot": lot, "run": run}


def soybean_lot_with_test(api, ffa_pct) -> dict:
    """A 100.000 MT SOYBEAN_OIL lot carrying one quality test at `ffa_pct`.

    Every other laboratory metric sits in its lowest band, so the governing tier is
    whatever the free-fatty-acid reading alone decides. Returns {"supplier", "test",
    "lot"} where "lot" is the refreshed lot row.
    """
    supplier = verified_supplier(api, feedstock_types=[FEEDSTOCK_SOYBEAN_OIL])
    lot = make_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_SOYBEAN_OIL,
        mass_mt=100.000,
        attested_ci_gco2e_per_mj=58.90,
        purchase_price_usd_per_mt=1020.00,
    )
    test_row = get_success_data(
        api.create_quality_test(
            lot["id"],
            f.quality_test_payload(
                lot["version"],
                ffa_pct=ffa_pct,
                moisture_pct=0.20,
                insolubles_ppm=100,
                phosphorus_ppm=5,
                sampled_at="2026-08-01T00:00:00Z",
            ),
            ANALYST_HEADERS,
        )
    )
    return {
        "supplier": supplier,
        "test": test_row,
        "lot": get_success_data(api.get_feedstock_lot(lot["id"], TRADER_HEADERS)),
    }


def unallocated_run_ready_for_hydrogen(api) -> dict:
    """A PLANNED three-day campaign with a booked nomination but no allocations yet.

    The campaign runs over [2026-09-10, 2026-09-13), the 500.000 MT UCO lot is
    ACCEPTED, and the nomination books 1200.0 kg/day over [2026-09-10, 2026-09-12] —
    enough to cover a 100.000 MT charge. Returns {"unit", "charge", "supplier",
    "lot", "contract", "run", "nomination"}.
    """
    plant = commissioned_unit(api)
    supplier = verified_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = accepted_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_UCO,
        mass_mt=500.000,
        attested_ci_gco2e_per_mj=32.50,
        purchase_price_usd_per_mt=900.00,
    )
    contract = make_contract(api)
    run = make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-13T00:00:00Z",
        target_saf_share_pct=0.00,
    )
    nomination = make_nomination(
        api,
        contract["id"],
        run["id"],
        start_at="2026-09-10T00:00:00Z",
        end_at="2026-09-12T00:00:00Z",
        kg_per_day=1200.0,
    )
    return {
        "unit": plant["unit"],
        "charge": plant["charge"],
        "supplier": supplier,
        "lot": lot,
        "contract": contract,
        "run": run,
        "nomination": nomination,
    }


def pending_supplier_lot_and_run(api) -> dict:
    """An ACCEPTED lot whose supplier has filed documents but is still PENDING.

    The campaign over [2026-09-10, 2026-09-13) is PLANNED and the clock stays at the
    2026-08-01T00:00:00Z default. Returns {"unit", "charge", "supplier", "lot",
    "run"}.
    """
    plant = commissioned_unit(api)
    supplier = documented_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = accepted_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_UCO,
        mass_mt=500.000,
        attested_ci_gco2e_per_mj=32.50,
        purchase_price_usd_per_mt=900.00,
    )
    run = make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-13T00:00:00Z",
        target_saf_share_pct=0.00,
    )
    return {
        "unit": plant["unit"],
        "charge": plant["charge"],
        "supplier": supplier,
        "lot": lot,
        "run": run,
    }


def unit_down_for_turnaround(api) -> dict:
    """A secured campaign whose unit was taken down by a second turnaround window.

    An APPROVED INSPECTION window over [2026-08-20, 2026-08-25) is started at
    2026-08-20 and left IN_PROGRESS, so the unit is DOWN_TURNAROUND; the clock is
    then moved to the campaign's window start at 2026-09-01T00:00:00Z. Adds
    "inspection" to the `baseline_campaign` context.
    """
    ctx = baseline_campaign(api, target_saf_share_pct=0.00)
    inspection = make_approved_window(
        api,
        ctx["unit"]["id"],
        scope=SCOPE_INSPECTION,
        start_at="2026-08-20T00:00:00Z",
        end_at="2026-08-25T00:00:00Z",
    )
    move_clock(api, "2026-08-20T00:00:00Z")
    ctx["inspection"] = get_success_data(api.start_window(inspection["id"], OPERATOR_HEADERS))
    move_clock(api, "2026-09-01T00:00:00Z")
    return ctx


def reserved_rd_batch_with_pathway(api, **kwargs) -> dict:
    """A RECONCILED campaign whose diesel batch is RESERVED but not yet shipped.

    A REGISTERED LCFS pathway for the same unit and feedstock is in place, so the
    only thing standing between the batch and a credit block is its distribution
    state. Adds "batch" and "pathway" to the `reconciled_campaign` context.
    """
    ctx = reconciled_campaign(api, **kwargs)
    batch = find_batch(api, ctx["run"]["id"], PRODUCT_RENEWABLE_DIESEL)
    ctx["batch"] = get_success_data(
        api.reserve_batch(batch["id"], f.reservation_payload(), OFFICER_A_HEADERS)
    )
    ctx["pathway"] = registered_pathway(api, ctx["unit"]["id"])
    return ctx
