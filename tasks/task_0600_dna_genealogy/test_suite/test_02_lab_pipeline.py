"""Kits, barcode activation, the extraction/requeue cycle, instruments, batches and the run."""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    validate_success,
    validate_error,
    validate_paginated,
    assert_kit,
    assert_sample,
    assert_lab_instrument,
    assert_lab_batch,
    assert_instant_equals,
    make_customer_headers,
    make_lab_technician_headers,
    make_platform_admin_headers,
    factories as f,
    fixtures as fx,
)

ADMIN = make_platform_admin_headers()
LAB = make_lab_technician_headers()


# ═══════════════════════════════════════════════════════════════════════════
# Ordering a kit
# ═══════════════════════════════════════════════════════════════════════════

def test_kit_barcode_and_price_are_server_minted(api):
    """PRD §3.3: "The server mints a unique activation `barcode` and returns it on the
    created kit, whose `status` begins at `ORDERED` and whose `price_cents` is fixed at
    9900."
    PRD §3.3: "A kit's `activated_at` is null until activation."

    Design: Corner/entities/kit_barcode_and_price_are_system_minted
    """
    customer = fx.create_customer(email="kb@dna.test", display_name="KB")
    headers = make_customer_headers(customer["id"])

    first = validate_success(
        api.create_kit(f.create_kit_payload(customer["id"], chip_version="V5"), headers), 201
    )
    second = validate_success(
        api.create_kit(f.create_kit_payload(customer["id"], chip_version="V4"), headers), 201
    )
    assert_kit(first)
    assert_kit(second)

    assert first["price_cents"] == 9900, f"Expected price_cents 9900, got {first['price_cents']}"
    assert first["barcode"] != second["barcode"], "Each kit must receive a unique barcode"
    assert first["status"] == "ORDERED"
    assert second["status"] == "ORDERED"
    assert first["activated_at"] is None


def test_kit_create_with_out_of_range_chip_version_is_rejected(api):
    """PRD §3.3: "A customer orders a DNA kit for themselves by naming their `customer_id`
    and the `chip_version` the kit should be manufactured for — either `V4` or `V5`."
    PRD §2.6: "Request well-formedness — required fields present, enumerated values in
    range, numeric ranges respected, and uniqueness honored (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/kit_create_with_invalid_chip_version_enum_returns_invalid_request
    """
    customer = fx.create_customer(email="enum@dna.test", display_name="Enum")
    headers = make_customer_headers(customer["id"])

    resp = api.create_kit(f.create_kit_payload(customer["id"], chip_version="V6"), headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    kits, _meta = validate_paginated(api.list_kits(headers, params={"customer_id": customer["id"]}))
    assert kits == [], "A rejected kit order must not create a Kit row"


# ═══════════════════════════════════════════════════════════════════════════
# Barcode activation
# ═══════════════════════════════════════════════════════════════════════════

def test_activating_an_already_activated_kit_is_rejected(api):
    """PRD §3.3: "The kit's `status` must be `ORDERED`; a kit that has already moved on
    rejects the attempt with `ERR_BARCODE_ALREADY_ACTIVATED`."
    PRD §3.3: "On success the kit moves `ORDERED → ACTIVATED`, `activated_at` is stamped
    with the logical clock, and the kit's `version` advances by one."

    Design: Corner/state_machines/kit_activate_twice_returns_barcode_already_activated
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="dbl@dna.test", display_name="Dbl")
    fx.create_subscription(customer["id"], "PLUS")
    headers = make_customer_headers(customer["id"])

    kit = fx.create_kit(customer["id"], "V5")
    fx.activate_kit(kit, customer["id"])

    resp = api.activate_kit(kit["id"], f.activate_kit_payload(kit["barcode"]), headers)
    validate_error(resp, ApiErrorId.ERR_BARCODE_ALREADY_ACTIVATED.value, 409)

    after = fx.read_kit(kit["id"])
    assert after["status"] == "ACTIVATED"
    assert_instant_equals(after["activated_at"], CLOCK_START, "activated_at")


def test_activating_a_kit_with_the_wrong_barcode_is_rejected(api):
    """PRD §3.3: "The submitted `barcode` must equal the kit's own barcode exactly, or the
    attempt fails with `ERR_BARCODE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/barcode_mismatch_on_activation_returns_422
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="bm@dna.test", display_name="Bm")
    fx.create_subscription(customer["id"], "PLUS")
    kit = fx.create_kit(customer["id"], "V5")

    resp = api.activate_kit(
        kit["id"],
        f.activate_kit_payload("NOT-THE-RIGHT-BARCODE"),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BARCODE_MISMATCH.value, 422)

    assert fx.read_kit(kit["id"])["status"] == "ORDERED"


def _setup_locked_owner_with_ordered_kit(email):
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email=email, display_name="Kai")
    sub = fx.create_subscription(customer["id"], "PLUS")
    kit = fx.create_kit(customer["id"], "V5")
    fx.lock_subscription(sub["id"])
    return customer, sub, kit


def test_kit_activation_is_refused_when_the_owners_subscription_is_locked(api):
    """PRD §3.3: "And — this is a cross-entity dependency that surprises people — the kit
    owner's subscription must have an `access_status` of `ACTIVE` or `GRACE`, or activation
    is refused with `ERR_SUBSCRIPTION_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/kit_activation_blocked_by_locked_subscription
    """
    customer, _sub, kit = _setup_locked_owner_with_ordered_kit("k@dna.test")

    # The kit's own state is ORDERED and the barcode is correct — only the *other* entity fails.
    resp = api.activate_kit(
        kit["id"], f.activate_kit_payload(kit["barcode"]), make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_LOCKED.value, 402)


def test_kit_refused_by_a_locked_subscription_stays_ordered_and_unstamped(api):
    """PRD §3.3: "On success the kit moves `ORDERED → ACTIVATED`, `activated_at` is stamped
    with the logical clock, and the kit's `version` advances by one."
    PRD §3.3: "And — this is a cross-entity dependency that surprises people — the kit
    owner's subscription must have an `access_status` of `ACTIVE` or `GRACE`, or activation
    is refused with `ERR_SUBSCRIPTION_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/kit_activation_blocked_by_locked_subscription
    """
    customer, sub, kit = _setup_locked_owner_with_ordered_kit("k2@dna.test")

    resp = api.activate_kit(
        kit["id"], f.activate_kit_payload(kit["barcode"]), make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_LOCKED.value, 402)

    after = fx.read_kit(kit["id"])
    assert after["status"] == "ORDERED", "The refused activation must leave the kit ORDERED"
    assert after["activated_at"] is None, "activated_at must not be stamped by a refused activation"
    assert fx.read_subscription(sub["id"], customer["id"])["access_status"] == "LOCKED"


# ═══════════════════════════════════════════════════════════════════════════
# Extraction, QC failure and the requeue cycle
# ═══════════════════════════════════════════════════════════════════════════

def test_requeue_from_extracted_is_not_a_declared_transition(api):
    """PRD §3.4: "This requires the sample to be in `QC_FAILED` status (`ERR_INVALID_STATE`
    otherwise) and requires `extraction_attempts` to be strictly below three — a sample that
    has burned all three attempts is refused with `ERR_EXTRACTION_ATTEMPTS_EXHAUSTED`."

    Design: Corner/state_machines/sample_requeue_from_extracted_is_invalid_transition
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="rq@dna.test", display_name="Rq")
    fx.create_subscription(customer["id"], "PLUS")
    _kit, sample = fx.create_extracted_sample(customer["id"], "V5")
    assert sample["status"] == "EXTRACTED"

    resp = api.requeue_sample(sample["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = fx.read_sample(sample["id"])
    assert after["status"] == "EXTRACTED"
    assert after["extraction_attempts"] == 1


def _setup_received_sample(email):
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email=email, display_name="Quinn")
    fx.create_subscription(customer["id"], "PLUS")
    kit, sample = fx.create_received_sample(customer["id"], "V5")
    return customer, kit, sample


def test_qc_failure_then_requeue_returns_the_sample_to_received(api):
    """PRD §3.4: "A yield below 200.0 nanograms fails quality control. If, after the
    increment, `extraction_attempts` is still below three, the sample moves
    `RECEIVED → QC_FAILED` and can be salvaged."
    PRD §3.4: "A technician may return a `QC_FAILED` sample to the head of the pipeline,
    moving it `QC_FAILED → RECEIVED` so it can be extracted again."

    Design: Difficulty/non_linear_state_machine/sample_qc_failure_requeue_cycle_returns_to_received
    """
    _customer, _kit, sample = _setup_received_sample("q@dna.test")

    failed = validate_success(
        api.extract_sample(sample["id"], f.extract_payload(dna_yield_ng=100.0), LAB)
    )
    assert_sample(failed)
    assert failed["status"] == "QC_FAILED"
    assert failed["extraction_attempts"] == 1

    requeued = validate_success(api.requeue_sample(sample["id"], LAB))
    assert requeued["status"] == "RECEIVED", (
        "The requeue edge must return the sample to a state it already left"
    )
    assert requeued["batch_id"] is None
    assert requeued["call_rate"] is None


def test_extraction_attempts_survive_the_requeue_cycle(api):
    """PRD §3.4: "In every case, the submitted yield is written onto the sample's
    `dna_yield_ng` and `extraction_attempts` is incremented by one."
    PRD §3.4: "Requeuing clears the sample's `batch_id` back to null and clears its
    `call_rate` back to null, because whatever batch and whatever call rate the sample
    previously carried are no longer meaningful."

    Design: Difficulty/non_linear_state_machine/sample_qc_failure_requeue_cycle_returns_to_received
    """
    _customer, _kit, sample = _setup_received_sample("q2@dna.test")

    validate_success(api.extract_sample(sample["id"], f.extract_payload(dna_yield_ng=100.0), LAB))
    validate_success(api.requeue_sample(sample["id"], LAB))
    second = validate_success(
        api.extract_sample(sample["id"], f.extract_payload(dna_yield_ng=500.0), LAB)
    )

    assert second["status"] == "EXTRACTED"
    assert second["extraction_attempts"] == 2, (
        "The requeue edge does not reset the attempt counter; two extractions means two attempts, "
        f"got {second['extraction_attempts']}"
    )
    assert second["dna_yield_ng"] == pytest.approx(500.0)
    assert second["batch_id"] is None


def test_third_failed_extraction_terminates_the_sample_voids_the_kit_and_refunds(api):
    """PRD §3.4: "A yield below 200.0 nanograms where, after the increment,
    `extraction_attempts` has reached three or more, is terminal: the sample moves
    `RECEIVED → FAILED_TERMINAL`, and the terminal-failure cascade fires (below)."
    PRD §3.4: "When a sample reaches `FAILED_TERMINAL` — whether from a failed extraction
    here or from a failed genotype call in Section 3.5 — its kit, sitting in `RECEIVED`,
    transitions to `VOID`. That kit transition in turn credits the customer's
    `wallet_credit_cents` by the kit's `price_cents` of 9900 and resets the customer's
    `dna_status` to `NO_SAMPLE`."

    Design: Corner/state_machines/third_failed_extraction_terminates_sample_and_voids_kit_with_refund
    """
    customer, kit, sample = _setup_received_sample("fail@dna.test")

    validate_success(api.extract_sample(sample["id"], f.extract_payload(dna_yield_ng=10.0), LAB))
    validate_success(api.requeue_sample(sample["id"], LAB))
    validate_success(api.extract_sample(sample["id"], f.extract_payload(dna_yield_ng=20.0), LAB))
    validate_success(api.requeue_sample(sample["id"], LAB))
    final = validate_success(
        api.extract_sample(sample["id"], f.extract_payload(dna_yield_ng=30.0), LAB)
    )

    assert final["status"] == "FAILED_TERMINAL"
    assert final["extraction_attempts"] == 3

    assert fx.read_kit(kit["id"])["status"] == "VOID"
    after = fx.read_customer(customer["id"])
    assert after["wallet_credit_cents"] == 9900, (
        f"Expected a 9900-cent kit refund, got {after['wallet_credit_cents']}"
    )
    assert after["dna_status"] == "NO_SAMPLE"


# ═══════════════════════════════════════════════════════════════════════════
# Instruments and batch windows
# ═══════════════════════════════════════════════════════════════════════════

def test_instrument_status_defaults_to_online_when_omitted(api):
    """PRD §3.5: "An operator registers a genotyping instrument with a `name`, the
    `chip_version` it reads (`V4` or `V5`), and an optional `status` of `ONLINE` or
    `MAINTENANCE`, defaulting to `ONLINE`."

    Design: Corner/entities/lab_instrument_status_defaults_to_online_when_omitted
    """
    resp = api.create_lab_instrument({"name": "SEQ-DEF", "chip_version": "V4"}, ADMIN)
    data = validate_success(resp, 201)
    assert_lab_instrument(data)

    assert data["status"] == "ONLINE", f"Expected the ONLINE default, got {data['status']}"
    assert data["chip_version"] == "V4"


def _setup_extracted_sample_and_offline_instrument(email):
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email=email, display_name="Mo")
    fx.create_subscription(customer["id"], "PLUS")
    _kit, sample = fx.create_extracted_sample(customer["id"], "V5")
    instrument = fx.create_instrument(chip_version="V5", status="MAINTENANCE", name="SEQ-OFFLINE")
    return customer, sample, instrument


def test_batch_creation_is_refused_on_an_instrument_in_maintenance(api):
    """PRD §3.5: "The instrument must be `ONLINE`; an instrument in `MAINTENANCE` yields
    `ERR_INSTRUMENT_OFFLINE`."

    Design: Difficulty/cross_entity_state_dependency/batch_creation_blocked_by_offline_instrument
    """
    _customer, sample, instrument = _setup_extracted_sample_and_offline_instrument("m@dna.test")

    # The sample is EXTRACTED and chip-compatible, so the sample-readiness rule cannot fire.
    resp = api.create_lab_batch(
        f.create_batch_payload(instrument["id"], [sample["id"]]), LAB
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_OFFLINE.value, 409)


def test_batch_refused_by_an_offline_instrument_leaves_the_sample_unbatched(api):
    """PRD §3.5: "Each accepted sample moves `EXTRACTED → QUEUED`, has its `batch_id` set to
    the new batch, and pushes the batch's `member_count` up by one."
    PRD §3.5: "The instrument must be `ONLINE`; an instrument in `MAINTENANCE` yields
    `ERR_INSTRUMENT_OFFLINE`."

    Design: Difficulty/cross_entity_state_dependency/batch_creation_blocked_by_offline_instrument
    """
    _customer, sample, instrument = _setup_extracted_sample_and_offline_instrument("m2@dna.test")

    resp = api.create_lab_batch(f.create_batch_payload(instrument["id"], [sample["id"]]), LAB)
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_OFFLINE.value, 409)

    after = fx.read_sample(sample["id"])
    assert after["status"] == "EXTRACTED", "The refused batch must not move the sample"
    assert after["batch_id"] is None

    batches, _meta = validate_paginated(
        api.list_lab_batches(LAB, params={"instrument_id": instrument["id"]})
    )
    assert batches == [], "No batch may exist on the offline instrument"


def test_batch_creation_is_refused_when_the_sample_chip_does_not_match_the_instrument(api):
    """PRD §3.5: "Every enumerated sample must be in `EXTRACTED` status, and — the chip
    constraint — the `chip_version` of the sample's kit must equal the `chip_version` of the
    batch's instrument. A sample that fails either test is refused with
    `ERR_SAMPLE_NOT_READY`."

    Design: Corner/validations/batch_create_with_chip_mismatched_sample_returns_sample_not_ready
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="chip@dna.test", display_name="Chip")
    fx.create_subscription(customer["id"], "PLUS")
    _kit, sample = fx.create_extracted_sample(customer["id"], "V4")
    instrument = fx.create_instrument(chip_version="V5", status="ONLINE", name="SEQ-V5-ONLY")

    resp = api.create_lab_batch(f.create_batch_payload(instrument["id"], [sample["id"]]), LAB)
    validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_READY.value, 409)

    after = fx.read_sample(sample["id"])
    assert after["status"] == "EXTRACTED"
    assert after["batch_id"] is None


def test_back_to_back_batch_windows_on_one_instrument_are_legal(api):
    """PRD §3.5: "The window is **half-open**: it includes its start instant and excludes
    its end instant, which means back-to-back batches on the same instrument — where one
    batch's `run_start_at` equals the previous batch's `run_end_at` — do not conflict and
    are perfectly legal."

    Design: Difficulty/resource_temporal_overlap/lab_instrument_half_open_window_adjacency_allowed_overlap_rejected
    """
    fx.set_clock(CLOCK_START)
    instrument = fx.create_instrument(chip_version="V5", status="ONLINE", name="SEQ-8")

    first = validate_success(
        api.create_lab_batch(
            f.create_batch_payload(
                instrument["id"],
                [],
                run_start_at="2026-05-01T02:00:00Z",
                run_end_at="2026-05-01T06:00:00Z",
            ),
            LAB,
        ),
        201,
    )
    assert_lab_batch(first)
    assert first["status"] == "OPEN"

    adjacent = validate_success(
        api.create_lab_batch(
            f.create_batch_payload(
                instrument["id"],
                [],
                run_start_at="2026-05-01T06:00:00Z",
                run_end_at="2026-05-01T08:00:00Z",
            ),
            LAB,
        ),
        201,
    )
    assert adjacent["status"] == "OPEN", (
        "A batch starting exactly at another's run_end_at must be accepted under half-open semantics"
    )


def test_a_genuinely_overlapping_batch_window_is_rejected(api):
    """PRD §3.5: "Any genuine overlap with an existing batch on the same instrument whose
    `status` is `OPEN`, `RUNNING`, or `FINALIZED` is refused with `ERR_BATCH_WINDOW_OVERLAP`,
    as is a window whose end is not strictly after its start."

    Design: Difficulty/resource_temporal_overlap/lab_instrument_half_open_window_adjacency_allowed_overlap_rejected
    """
    fx.set_clock(CLOCK_START)
    instrument = fx.create_instrument(chip_version="V5", status="ONLINE", name="SEQ-8b")

    fx.create_batch(
        instrument["id"], [], run_start_at="2026-05-01T02:00:00Z", run_end_at="2026-05-01T06:00:00Z"
    )
    fx.create_batch(
        instrument["id"], [], run_start_at="2026-05-01T06:00:00Z", run_end_at="2026-05-01T08:00:00Z"
    )

    # 05:00-07:00 straddles the boundary and genuinely intersects both windows.
    resp = api.create_lab_batch(
        f.create_batch_payload(
            instrument["id"],
            [],
            run_start_at="2026-05-01T05:00:00Z",
            run_end_at="2026-05-01T07:00:00Z",
        ),
        LAB,
    )
    validate_error(resp, ApiErrorId.ERR_BATCH_WINDOW_OVERLAP.value, 409)

    batches, meta = validate_paginated(
        api.list_lab_batches(LAB, params={"instrument_id": instrument["id"]})
    )
    assert meta["total_count"] == 2, f"Expected exactly 2 batches, got {meta['total_count']}"
    assert len(batches) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Starting, finalizing and aborting a run
# ═══════════════════════════════════════════════════════════════════════════

def _setup_empty_open_batch():
    fx.set_clock(CLOCK_START)
    instrument = fx.create_instrument(chip_version="V5", status="ONLINE", name="SEQ-7")
    batch = fx.create_batch(instrument["id"], [])
    return instrument, batch


def test_starting_a_batch_with_no_members_is_rejected(api):
    """PRD §3.5: "Starting the run requires the batch to be `OPEN` (`ERR_INVALID_STATE`
    otherwise) and to have at least one member — a batch with `member_count` of zero is
    refused with `ERR_EMPTY_BATCH` (HTTP 422) — and requires the instrument to still be
    `ONLINE`, or `ERR_INSTRUMENT_OFFLINE`."

    Design: Difficulty/boundary_precision_check/empty_batch_start_rejected_on_zero_members
    """
    _instrument, batch = _setup_empty_open_batch()
    assert batch["member_count"] == 0

    resp = api.start_lab_batch(batch["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH.value, 422)


def test_a_batch_refused_by_the_empty_guard_stays_open_with_null_pass_rate(api):
    """PRD §3.5: "The batch itself is created in `OPEN` status with `pass_rate` null."
    PRD §3.5: "Starting the run requires the batch to be `OPEN` (`ERR_INVALID_STATE`
    otherwise) and to have at least one member — a batch with `member_count` of zero is
    refused with `ERR_EMPTY_BATCH` (HTTP 422) — and requires the instrument to still be
    `ONLINE`, or `ERR_INSTRUMENT_OFFLINE`."

    Design: Difficulty/boundary_precision_check/empty_batch_start_rejected_on_zero_members
    """
    _instrument, batch = _setup_empty_open_batch()

    resp = api.start_lab_batch(batch["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH.value, 422)

    after = fx.read_batch(batch["id"])
    assert after["status"] == "OPEN", "The refused start must leave the batch OPEN"
    assert after["member_count"] == 0
    assert after["pass_rate"] is None


def _setup_running_batch_for_one_customer(email, chip="V5", dna_yield_ng=500.0):
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email=email, display_name="Fay")
    fx.create_subscription(customer["id"], "PLUS")
    kit, sample = fx.create_received_sample(customer["id"], chip)
    sample = fx.extract_sample(sample["id"], dna_yield_ng)
    _instrument, batch = fx.create_running_batch([sample["id"]], chip)
    return customer, kit, sample, batch


def test_finalize_cascades_sample_to_kit_to_customer_dna_status(api):
    """PRD §3.5: "A `call_rate` of at least 0.98: the sample moves `GENOTYPING → GENOTYPED`,
    and its `call_rate`, `population_scores`, and `genotype_markers` are all written from the
    result entry. The **finalize cascade** then fires: the sample's kit, sitting in
    `RECEIVED`, moves to `PROCESSED`, and that kit transition in turn sets the owning
    customer's `dna_status` to `DNA_READY`."

    Design: Difficulty/transitive_cascade/lab_finalize_sample_kit_customer_three_hop_cascade
    """
    customer, kit, sample, batch = _setup_running_batch_for_one_customer(
        "f@dna.test", dna_yield_ng=240.0
    )
    assert fx.read_customer(customer["id"])["dna_status"] == "PROCESSING"

    validate_success(
        api.finalize_lab_batch(
            batch["id"],
            f.finalize_batch_payload(
                [
                    f.sample_result(
                        sample["id"],
                        call_rate=0.98,
                        population_scores=[
                            {"population": "EUR", "raw_score": 50},
                            {"population": "EAS", "raw_score": 50},
                        ],
                        genotype_markers=[3, 4, 5],
                    )
                ]
            ),
            LAB,
        )
    )

    # hop 1: the sample; hop 2: the kit the client never named; hop 3: the customer.
    assert fx.read_sample(sample["id"])["status"] == "GENOTYPED"
    assert fx.read_kit(kit["id"])["status"] == "PROCESSED"
    assert fx.read_customer(customer["id"])["dna_status"] == "DNA_READY"


def test_finalize_records_the_batch_pass_rate_and_the_genotype_payload(api):
    """PRD §3.5: "The batch itself moves `RUNNING → FINALIZED` and records its `pass_rate`:
    the number of member samples whose reported call rate is at least 0.98, divided by the
    total number of member samples, rounded half up to 4 decimal places."

    Design: Difficulty/transitive_cascade/lab_finalize_sample_kit_customer_three_hop_cascade
    """
    _customer, _kit, sample, batch = _setup_running_batch_for_one_customer(
        "f2@dna.test", dna_yield_ng=240.0
    )

    finalized = validate_success(
        api.finalize_lab_batch(
            batch["id"],
            f.finalize_batch_payload(
                [
                    f.sample_result(
                        sample["id"],
                        call_rate=0.98,
                        population_scores=[
                            {"population": "EUR", "raw_score": 50},
                            {"population": "EAS", "raw_score": 50},
                        ],
                        genotype_markers=[3, 4, 5],
                    )
                ]
            ),
            LAB,
        )
    )
    assert_lab_batch(finalized)
    assert finalized["status"] == "FINALIZED"
    assert finalized["pass_rate"] == pytest.approx(1.0, abs=0.0001)

    after = fx.read_sample(sample["id"])
    assert after["call_rate"] == pytest.approx(0.98)
    assert after["genotype_markers"] == [3, 4, 5]


def test_batch_pass_rate_is_one_half_when_one_of_two_members_fails(api):
    """PRD §3.5: "The batch itself moves `RUNNING → FINALIZED` and records its `pass_rate`:
    the number of member samples whose reported call rate is at least 0.98, divided by the
    total number of member samples, rounded half up to 4 decimal places."
    PRD §3.5: "A `call_rate` below 0.98 where the resulting `extraction_attempts` (after
    being incremented by one) is still below three: the sample moves
    `GENOTYPING → QC_FAILED`, with its `call_rate` written from the result entry. It can be
    requeued."

    Design: Corner/calculations/lab_batch_pass_rate_is_half_when_one_of_two_members_fails
    """
    fx.set_clock(CLOCK_START)
    c1 = fx.create_customer(email="pr1@dna.test", display_name="Pr1")
    fx.create_subscription(c1["id"], "PLUS")
    k1, s1 = fx.create_extracted_sample(c1["id"], "V5")

    c2 = fx.create_customer(email="pr2@dna.test", display_name="Pr2")
    fx.create_subscription(c2["id"], "PLUS")
    k2, s2 = fx.create_extracted_sample(c2["id"], "V5")

    _instrument, batch = fx.create_running_batch([s1["id"], s2["id"]], "V5")

    finalized = validate_success(
        api.finalize_lab_batch(
            batch["id"],
            f.finalize_batch_payload(
                [
                    f.sample_result(s1["id"], call_rate=0.99),
                    f.sample_result(s2["id"], call_rate=0.97),
                ]
            ),
            LAB,
        )
    )
    assert finalized["pass_rate"] == pytest.approx(0.5, abs=0.0001)

    passed = fx.read_sample(s1["id"])
    assert passed["status"] == "GENOTYPED"
    assert passed["extraction_attempts"] == 1

    failed = fx.read_sample(s2["id"])
    assert failed["status"] == "QC_FAILED"
    assert failed["extraction_attempts"] == 2, (
        "A failing genotype call increments extraction_attempts, "
        f"got {failed['extraction_attempts']}"
    )

    assert fx.read_kit(k1["id"])["status"] == "PROCESSED"
    assert fx.read_customer(c1["id"])["dna_status"] == "DNA_READY"
    assert fx.read_kit(k2["id"])["status"] == "RECEIVED"
    assert fx.read_customer(c2["id"])["dna_status"] == "PROCESSING"


def test_aborting_a_running_batch_releases_its_members_back_to_extracted(api):
    """PRD §3.5: "Every member sample is released back to `EXTRACTED` — from `QUEUED` if the
    batch was open, from `GENOTYPING` if it was running — each member's `batch_id` is cleared
    to null, and the batch's `member_count` is set to zero."

    Design: Corner/state_machines/batch_abort_releases_members_back_to_extracted
    """
    _customer, _kit, sample, batch = _setup_running_batch_for_one_customer("ab@dna.test")

    aborted = validate_success(api.abort_lab_batch(batch["id"], LAB))
    assert aborted["status"] == "ABORTED"
    assert aborted["member_count"] == 0
    assert aborted["pass_rate"] is None

    released = fx.read_sample(sample["id"])
    assert released["status"] == "EXTRACTED"
    assert released["batch_id"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Reads: filtering and pagination
# ═══════════════════════════════════════════════════════════════════════════

def test_samples_filtered_by_batch_id_returns_only_that_batchs_members(api):
    """PRD §4: "samples accept `kit_id`, `batch_id`, and `status`"
    PRD §3.5: "Each accepted sample moves `EXTRACTED → QUEUED`, has its `batch_id` set to the
    new batch, and pushes the batch's `member_count` up by one."

    Design: Corner/endpoints/samples_filtered_by_batch_id_returns_only_batch_members
    """
    fx.set_clock(CLOCK_START)
    c1 = fx.create_customer(email="fl1@dna.test", display_name="Fl1")
    fx.create_subscription(c1["id"], "PLUS")
    _k1, s1 = fx.create_extracted_sample(c1["id"], "V5")

    c2 = fx.create_customer(email="fl2@dna.test", display_name="Fl2")
    fx.create_subscription(c2["id"], "PLUS")
    _k2, s2 = fx.create_extracted_sample(c2["id"], "V5")

    instrument = fx.create_instrument(chip_version="V5", status="ONLINE", name="SEQ-FL")
    batch = fx.create_batch(instrument["id"], [s1["id"]])

    samples, meta = validate_paginated(api.list_samples(LAB, params={"batch_id": batch["id"]}))
    assert meta["total_count"] == 1, f"Expected 1 batch member, got {meta['total_count']}"
    assert samples[0]["id"] == s1["id"]
    assert samples[0]["status"] == "QUEUED"

    unbatched = fx.read_sample(s2["id"])
    assert unbatched["batch_id"] is None
    assert unbatched["status"] == "EXTRACTED"
    assert fx.read_batch(batch["id"])["member_count"] == 1


def test_kit_list_paginates_with_limit_offset_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, may not be
    lower than 1, and may not exceed 100. `offset` is the number of items to skip and
    defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` object of the envelope. `total_count` reflects the size of the filtered result
    set before pagination is applied, and `has_more` is true exactly when items remain beyond
    the current page."

    Design: Corner/endpoints/kit_list_paginates_with_limit_offset_total_count_has_more
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="pag@dna.test", display_name="Pag")
    headers = make_customer_headers(customer["id"])
    fx.create_kit(customer["id"], "V5")
    fx.create_kit(customer["id"], "V5")
    fx.create_kit(customer["id"], "V4")

    first_page, meta = validate_paginated(
        api.list_kits(headers, params={"customer_id": customer["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second_page, meta2 = validate_paginated(
        api.list_kits(headers, params={"customer_id": customer["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
