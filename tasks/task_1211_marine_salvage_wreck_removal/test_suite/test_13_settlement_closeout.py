"""Closeout: doc packs, settlement gates, casualty closure, overrun flag."""
from test_helpers import (
    ApiErrorId,
    add_doc_entry,
    assert_doc_entry,
    assert_security_conservation,
    book_charter,
    compute_award,
    disburse_security,
    get_success_data,
    lodge_security,
    log_property,
    open_doc_pack,
    register_asset,
    register_site,
    report_pollution_event,
    secure_ashore,
    set_clock,
    setup_active_contract,
    setup_completed_operation,
    setup_running_phase,
    setup_signed_contract,
    setup_verified_lot,
    survey_property,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    verify_value,
)


def test_settle_requires_docs_accepted_then_full_settlement_happy_path(
    api, contracts_officer_headers, insurer_surveyor_headers,
    operations_director_headers, salvage_master_headers,
):
    """PRD 3.9: "the `ContractsOfficer` settles a contract in `AWARD_FINAL`,
    which requires every security deposit of the contract to be `CLOSED` (an
    open deposit blocks settlement with `ERR_SECURITY_DISBURSE_NOT_ALLOWED`) and
    every documentation pack of the contract to be `ACCEPTED`
    (`ERR_DOCS_NOT_ACCEPTED`)."
    PRD 3.9: "An `ACCEPT` outcome moves the pack to its terminal `ACCEPTED`; a
    `DEFICIENT` outcome returns the pack to `COMPILING` for rework, and the
    submit–review loop may repeat"
    PRD 3.9: "the `OperationsDirector` closes a casualty in
    `OPERATIONS_COMPLETE`, which requires every contract of the casualty to be
    `SETTLED` or `TERMINATED` and no pollution event of the casualty to remain
    in `REPORTED`, `ESCALATED`, or `CONTAINED`"

    Design: Corner/validations/settle_requires_docs_accepted_then_full_settlement_happy_path
    """
    ctx = setup_running_phase(casualty_overrides={"vessel_name": "MV Pax"})
    phase = validate_success(api.complete_phase(ctx["phase"]["id"], salvage_master_headers), 200)
    set_clock("2026-05-15T00:00:00Z")
    charter = validate_success(api.off_hire_charter(ctx["charter"]["id"], salvage_master_headers), 200)
    # Verified lot, fully redelivered.
    ctx["site"] = register_site(name="Yard A", capacity_tonnes=1000)
    lot = setup_verified_lot(ctx, quantity_tonnes=50, declared_value_cents=200_000_000)
    validate_success(
        api.dispose_property(lot["id"], {"method": "REDELIVER", "tonnes": 50},
                             salvage_master_headers),
        200,
    )
    # Award: agree without arbitration, then record payment.
    award = compute_award(ctx["contract"]["id"])
    agreed = validate_success(
        api.agree_award(award["id"], {"agreed_amount_cents": 18_900_000},
                        contracts_officer_headers),
        200,
    )
    assert agreed["status"] == "AGREED"
    paid = validate_success(api.mark_paid_award(award["id"], contracts_officer_headers), 200)
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 18_900_000, "agreed path pays the agreed amount"
    contract = validate_success(api.get_contract(ctx["contract"]["id"], contracts_officer_headers), 200)
    assert contract["status"] == "AWARD_FINAL"
    # Security fully applied toward the award: deposit closes.
    deposit = ctx["security"]
    closed = disburse_security(deposit["id"], "APPLY_TO_AWARD", 30_000_000)
    assert closed["status"] == "CLOSED"
    assert closed["applied_cents"] == 30_000_000
    assert closed["held_cents"] == 0
    assert_security_conservation(closed)
    # Documentation: 3 required (phase, off-hire charter, surveyed lot).
    pack = open_doc_pack(ctx["contract"]["id"])
    add_doc_entry(pack["id"], "DAILY_LOG", phase["id"], summary="refloat log")
    add_doc_entry(pack["id"], "COST_LOG", charter["id"],
                  entry_date="2026-05-15T00:00:00Z", summary="tug costs")
    add_doc_entry(pack["id"], "SURVEY_REPORT", lot["id"],
                  entry_date="2026-05-15T00:00:00Z", summary="value survey")
    submitted = validate_success(api.submit_doc_pack(pack["id"], salvage_master_headers), 200)
    assert submitted["status"] == "SUBMITTED"

    # The docs gate is the sole blocker: security is already CLOSED.
    res = api.settle_contract(ctx["contract"]["id"], contracts_officer_headers)
    validate_error(res, ApiErrorId.ERR_DOCS_NOT_ACCEPTED, expected_status=422)

    deficient = validate_success(
        api.review_doc_pack(pack["id"], {"outcome": "DEFICIENT", "notes": "missing signatures"},
                            insurer_surveyor_headers),
        200,
    )
    assert deficient["status"] == "COMPILING", "rework loop returns to COMPILING"
    resubmitted = validate_success(api.submit_doc_pack(pack["id"], salvage_master_headers), 200)
    assert resubmitted["status"] == "SUBMITTED"
    accepted = validate_success(
        api.review_doc_pack(pack["id"], {"outcome": "ACCEPT"}, insurer_surveyor_headers), 200
    )
    assert accepted["status"] == "ACCEPTED"

    settled = validate_success(
        api.settle_contract(ctx["contract"]["id"], contracts_officer_headers), 200
    )
    assert settled["status"] == "SETTLED"
    closed_casualty = validate_success(
        api.close_casualty(ctx["casualty"]["id"], operations_director_headers), 200
    )
    assert closed_casualty["lifecycle_status"] == "CLOSED"


def test_doc_completeness_exact_100_boundary(api, salvage_master_headers):
    """PRD 3.9: "Submission by a `SalvageMaster` is a fiscal documentation gate:
    the completeness must read exactly 100 — three of four requirements reads 75
    and fails — otherwise `ERR_DOC_INCOMPLETE`; at submission the three counters
    freeze at their evaluated values and the pack moves from `COMPILING` to
    `SUBMITTED`."

    Design: Corner/calculations/doc_completeness_exact_100_boundary
    """
    ctx = setup_running_phase(casualty_overrides={"vessel_name": "MV Pax"})
    phase = validate_success(api.complete_phase(ctx["phase"]["id"], salvage_master_headers), 200)
    set_clock("2026-05-15T00:00:00Z")
    charter = validate_success(api.off_hire_charter(ctx["charter"]["id"], salvage_master_headers), 200)
    event = report_pollution_event(
        ctx["casualty"]["id"], pollutant_class="DEBRIS", tier="TIER_1", est_volume_m3=3
    )
    lot = log_property(
        ctx["casualty"]["id"], property_type="CARGO",
        quantity_tonnes=10, declared_value_cents=9_000_000,
    )
    survey_property(lot["id"], 9_000_000)

    pack = open_doc_pack(ctx["contract"]["id"])
    add_doc_entry(pack["id"], "DAILY_LOG", phase["id"], summary="refloat day log")
    add_doc_entry(pack["id"], "COST_LOG", charter["id"],
                  entry_date="2026-05-15T00:00:00Z", summary="tug hire costs")
    add_doc_entry(pack["id"], "POLLUTION_REPORT", event["id"],
                  entry_date="2026-05-15T00:00:00Z", summary="debris sweep")

    # 3 of 4 required entries: the SURVEY_REPORT for the lot is missing.
    res = api.submit_doc_pack(pack["id"], salvage_master_headers)
    validate_error(res, ApiErrorId.ERR_DOC_INCOMPLETE, expected_status=422)

    add_doc_entry(pack["id"], "SURVEY_REPORT", lot["id"],
                  entry_date="2026-05-15T00:00:00Z", summary="value survey")
    submitted = validate_success(api.submit_doc_pack(pack["id"], salvage_master_headers), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["required_count"] == 4
    assert submitted["satisfied_count"] == 4
    assert submitted["completeness_pct"] == 100


def test_doc_entry_ref_type_mismatch_rejected(api, salvage_master_headers):
    """PRD 3.9: "a `DAILY_LOG` must reference an operation phase, a `COST_LOG`
    an equipment charter, a `POLLUTION_REPORT` a pollution event, and a
    `SURVEY_REPORT` a recovered property lot — all of the same casualty ... A
    missing reference, a wrong entity type, a wrong casualty, or an unqualified
    record state is rejected with `ERR_DOC_ENTRY_INVALID`."

    Design: Corner/validations/doc_entry_ref_type_mismatch_rejected
    """
    ctx = setup_completed_operation(casualty_overrides={"vessel_name": "MV Pax"})
    pack = open_doc_pack(ctx["contract"]["id"])
    # A COST_LOG naming an OperationPhase id: wrong entity type.
    res = api.create_doc_entry(
        pack["id"],
        {"entry_type": "COST_LOG", "ref_id": ctx["phase"]["id"],
         "entry_date": "2026-05-11T00:00:00Z", "summary": "wrong ref type"},
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_DOC_ENTRY_INVALID, expected_status=422)


def test_doc_entry_immutable_record_shape(api, salvage_master_headers):
    """PRD 2.5: "Documentation entries are the sole exception to this
    convention: a DocEntry carries only `id` and `created_at`, and both
    `updated_at` and `version` are absent from it, because entries are immutable
    once appended."
    PRD 4: "Operations that create a new resource return a `201 Created` status
    code"

    Design: Corner/entities/doc_entry_immutable_record_shape
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    event = report_pollution_event(
        ctx["casualty"]["id"], pollutant_class="DEBRIS", tier="TIER_1", est_volume_m3=2
    )
    pack = open_doc_pack(ctx["contract"]["id"])
    res = api.create_doc_entry(
        pack["id"],
        {"entry_type": "POLLUTION_REPORT", "ref_id": event["id"],
         "entry_date": "2026-05-10T00:00:00Z", "summary": "debris sweep logged"},
        salvage_master_headers,
    )
    entry = validate_success(res, 201)
    assert_doc_entry(entry)
    assert entry["ref_id"] == event["id"]

    entries, _ = validate_paginated(
        api.list_doc_entries(pack["id"], salvage_master_headers)
    )
    assert len(entries) == 1
    assert entries[0]["id"] == entry["id"]
    assert entries[0]["ref_id"] == event["id"]


def test_duplicate_open_doc_pack_rejected(api, salvage_master_headers):
    """PRD 3.9: "at most one pack per contract may be open, meaning not yet
    `ACCEPTED`, and a duplicate attempt meets `ERR_DUPLICATE_OPEN_DOC_PACK`."

    Design: Corner/validations/duplicate_open_doc_pack_rejected
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    open_doc_pack(ctx["contract"]["id"])
    res = api.create_doc_pack({"contract_id": ctx["contract"]["id"]}, salvage_master_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_OPEN_DOC_PACK, expected_status=409)


def test_casualty_close_blocked_rejected(api, operations_director_headers):
    """PRD 3.9: "the `OperationsDirector` closes a casualty in
    `OPERATIONS_COMPLETE`, which requires every contract of the casualty to be
    `SETTLED` or `TERMINATED` and no pollution event of the casualty to remain
    in `REPORTED`, `ESCALATED`, or `CONTAINED` — either failure blocks closure
    with `ERR_CASUALTY_NOT_CLOSABLE`." The PRD names the aggregate gate for this
    failure while its §2.7 pipeline also permits the from-state rejection for an
    action taken outside `OPERATIONS_COMPLETE`; either named rejection conforms.

    Design: Corner/validations/casualty_close_blocked_rejected
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    assert ctx["contract"]["status"] == "ACTIVE"
    res = api.close_casualty(ctx["casualty"]["id"], operations_director_headers)
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_CASUALTY_NOT_CLOSABLE, ApiErrorId.ERR_INVALID_STATE_TRANSITION]
    )
    after = validate_success(api.get_casualty(ctx["casualty"]["id"], operations_director_headers), 200)
    assert after["lifecycle_status"] != "CLOSED"


def test_fixed_price_security_requirement_rounding(api, contracts_officer_headers):
    """PRD 3.3: "for a `FIXED_PRICE` contract it is simply the
    `fixed_price_cents`" (the provisional) and "for a `FIXED_PRICE` contract it
    is thirty percent of the `fixed_price_cents`, rounded half up to integer
    cents" (the security requirement).
    PRD 2.6: "all computed monetary values are rounded half up to zero decimal
    places — integer cents"

    Design: Corner/calculations/fixed_price_security_requirement_rounding
    """
    ctx = setup_signed_contract(
        form="FIXED_PRICE", fixed_price_cents=33_333_333,
        casualty_overrides={"vessel_name": "MV Pax"},
    )
    contract = ctx["contract"]
    assert contract["provisional_award_cents"] == 33_333_333, "fixed-price provisional is identity"
    # round_half_up(0.30 x 33,333,333) = round_half_up(9,999,999.9)
    assert contract["security_required_cents"] == 10_000_000


def test_fixed_price_overrun_flag_strict_threshold(api, contracts_officer_headers, salvage_master_headers):
    """PRD 3.6: "The `overrun_flag` is a fixed-price early-warning device: on a
    `FIXED_PRICE` contract it becomes true exactly when `cost_to_date_cents`
    exceeds the `fixed_price_cents` grown by ten percent — the threshold itself
    rounded half up to integer cents — with the comparison strict, so costs
    exactly at the threshold do not set the flag; on a `NO_CURE_NO_PAY` contract
    the flag is always false."

    Design: Corner/cross_cutting_layers/fixed_price_overrun_flag_strict_threshold
    """
    ctx = setup_signed_contract(
        form="FIXED_PRICE", fixed_price_cents=10_000_000,
        casualty_overrides={"vessel_name": "MV Pax"},
    )
    lodge_security(ctx["contract"]["id"], 3_000_000)
    validate_success(api.activate_contract(ctx["contract"]["id"], contracts_officer_headers), 200)
    asset = register_asset(day_rate_cents=1_000_000, max_hs_meters=3.00)
    set_clock("2026-05-10T00:00:00Z")
    ch_a = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start="2026-05-10T00:00:00Z", window_end="2026-05-22T00:00:00Z",
    )
    validate_success(api.on_hire_charter(ch_a["id"], salvage_master_headers), 200)
    set_clock("2026-05-21T00:00:00Z")
    validate_success(api.off_hire_charter(ch_a["id"], salvage_master_headers), 200)
    mid = validate_success(api.get_contract(ctx["contract"]["id"], contracts_officer_headers), 200)
    assert mid["cost_to_date_cents"] == 11_000_000, "11 active days x 1,000,000"
    assert mid["overrun_flag"] is False, "11,000,000 is not > 11,000,000 (strict)"

    ch_b = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start="2026-05-22T00:00:00Z", window_end="2026-05-24T00:00:00Z",
    )
    set_clock("2026-05-22T00:00:00Z")
    validate_success(api.on_hire_charter(ch_b["id"], salvage_master_headers), 200)
    set_clock("2026-05-23T00:00:00Z")
    validate_success(api.off_hire_charter(ch_b["id"], salvage_master_headers), 200)
    final = validate_success(api.get_contract(ctx["contract"]["id"], contracts_officer_headers), 200)
    assert final["cost_to_date_cents"] == 12_000_000
    assert final["overrun_flag"] is True, "12,000,000 > 11,000,000"
