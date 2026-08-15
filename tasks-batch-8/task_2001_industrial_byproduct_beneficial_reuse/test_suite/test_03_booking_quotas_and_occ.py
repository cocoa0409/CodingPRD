"""Booking gates: state, FK, ownership, temporal, quota, OCC, rollover, listing."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    book_shipment,
    create_active_agreement,
    create_active_commitment,
    create_characterization,
    create_characterized_stream,
    create_draft_agreement,
    create_draft_commitment,
    create_generator,
    create_offtaker,
    create_shipment_payload,
    create_stream,
    get_agreement,
    get_agreement_version,
    make_generator_headers,
    make_offtaker_headers,
    publish_price_index,
    set_logical_clock,
    setup_booking_ready_chain,
    validate_error,
    validate_paginated,
    validate_success,
    verify_characterization,
)

BROKER = TEST_USERS["broker_ops_headers"]


def test_booking_against_draft_agreement_rejected(api):
    """PRD §3.4: "The agreement must be `ACTIVE` (else
    `ERR_AGREEMENT_NOT_ACTIVE`) and the commitment must be `ACTIVE` (else
    `ERR_COMMITMENT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_draft_agreement
    """
    base = create_characterized_stream()
    generator, stream = base["generator"], base["stream"]
    offtaker = create_offtaker()
    agreement = create_draft_agreement(generator["id"], stream["id"],
                                       committed_monthly_tons=100)
    commitment = create_active_commitment(offtaker["id"], stream["id"],
                                          committed_monthly_tons=500)
    publish_price_index()

    resp = api.create_shipment(
        create_shipment_payload(
            agreement["id"], commitment["id"], agreement["version"], gross_tons=10
        ),
        make_generator_headers(generator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_rejected_booking_persists_no_shipment(api):
    """PRD §3.4: "The agreement must be `ACTIVE` (else
    `ERR_AGREEMENT_NOT_ACTIVE`) and the commitment must be `ACTIVE` (else
    `ERR_COMMITMENT_NOT_ACTIVE`)."
    PRD §3.4: "The shipment ledger can be listed with optional
    `supply_agreement_id`, `offtake_commitment_id`, and `status` filters."

    Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_draft_agreement
    """
    base = create_characterized_stream()
    generator, stream = base["generator"], base["stream"]
    offtaker = create_offtaker()
    agreement = create_draft_agreement(generator["id"], stream["id"],
                                       committed_monthly_tons=100)
    commitment = create_active_commitment(offtaker["id"], stream["id"],
                                          committed_monthly_tons=500)
    publish_price_index()

    resp = api.create_shipment(
        create_shipment_payload(
            agreement["id"], commitment["id"], agreement["version"], gross_tons=10
        ),
        make_generator_headers(generator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    data, meta = validate_paginated(
        api.list_shipments(BROKER, params={"supply_agreement_id": agreement["id"]})
    )
    assert meta["total_count"] == 0, "a rejected booking must not persist a shipment"
    assert data == []


def test_generator_cannot_book_other_generators_agreement(api):
    """PRD §2.1: "a Generator may register streams, submit characterizations,
    create supply agreements, and book or act on shipments only for its own
    organization, and an Offtaker may create offtake commitments and act on
    deliveries only for commitments it owns."
    PRD §2.1: "ownership checks on any resource that references a Generator
    compare the resource's `generator_id` field to `X-User-ID`, and a mismatch
    is rejected with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/validations/generator_cannot_book_other_generators_agreement_returns_ownership_error
    """
    gen_a = create_generator(legal_name="GenA", contact_email="a@x.com")
    gen_b = create_generator(legal_name="GenB", hq_state_code="MI", contact_email="b@x.com")
    offtaker = create_offtaker(receiving_state_codes=["PA"])
    stream = create_stream(gen_a["id"])
    agreement = create_draft_agreement(gen_a["id"], stream["id"],
                                       committed_monthly_tons=100)
    commitment = create_draft_commitment(offtaker["id"], stream["id"],
                                         committed_monthly_tons=100)

    resp = api.create_shipment(
        create_shipment_payload(
            agreement["id"], commitment["id"], agreement["version"], gross_tons=10
        ),
        make_generator_headers(gen_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_booking_with_stream_mismatch_returns_error(api):
    """PRD §3.4: "The agreement and the commitment must cover the same stream —
    if the agreement's `stream_id` differs from the commitment's, the booking
    is rejected with `ERR_STREAM_MISMATCH`."

    Design: Corner/validations/booking_with_stream_mismatch_returns_error
    """
    generator = create_generator()
    offtaker = create_offtaker(receiving_state_codes=["PA"])
    stream1 = create_stream(generator["id"])
    char1 = create_characterization(stream1["id"], generator["id"])
    verify_characterization(char1["id"])
    stream2 = create_stream(
        generator["id"], material_type="SLAG", declared_moisture_pct=5.0,
        expected_tons_per_month=300,
    )
    char2 = create_characterization(
        stream2["id"], generator["id"], ph=7.5, arsenic_ppm=2.0, lead_ppm=1.0,
        moisture_pct_measured=5.5,
    )
    verify_characterization(char2["id"])

    agreement = create_active_agreement(generator["id"], stream1["id"],
                                        committed_monthly_tons=100)
    commitment = create_active_commitment(offtaker["id"], stream2["id"],
                                          committed_monthly_tons=100)

    resp = api.create_shipment(
        create_shipment_payload(
            agreement["id"], commitment["id"],
            get_agreement_version(agreement["id"]), gross_tons=10,
        ),
        make_generator_headers(generator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STREAM_MISMATCH)


def test_booking_with_price_index_gap_returns_error(api):
    """PRD §3.4: "Finally, a market price index entry must be effective for the
    stream's material in the destination state on `pickup_date`; if none
    exists, the booking is rejected with `ERR_PRICE_INDEX_GAP`."

    Design: Corner/validations/booking_with_price_index_gap_returns_error
    """
    chain = setup_booking_ready_chain(
        material_type="SLAG", committed_agreement_tons=100,
        committed_commitment_tons=100, publish_index=False,
    )
    resp = api.create_shipment(
        create_shipment_payload(
            chain["agreement"]["id"], chain["commitment"]["id"],
            get_agreement_version(chain["agreement"]["id"]),
            gross_tons=10, loading_moisture_pct=5.0,
        ),
        chain["generator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PRICE_INDEX_GAP)


def test_booking_pickup_outside_term_returns_error(api):
    """PRD §3.4: "The scheduled `pickup_date` must fall within the agreement's
    inclusive term, from `term_start` through `term_end` (else
    `ERR_OUTSIDE_AGREEMENT_TERM`)."

    Design: Corner/validations/booking_pickup_outside_term_returns_error
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=100)
    resp = api.create_shipment(
        create_shipment_payload(
            chain["agreement"]["id"], chain["commitment"]["id"],
            get_agreement_version(chain["agreement"]["id"]),
            gross_tons=10, pickup_date="2027-01-15",
        ),
        chain["generator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_AGREEMENT_TERM)


def test_booking_blocked_by_draft_commitment(api):
    """PRD §3.4: "The agreement must be `ACTIVE` (else
    `ERR_AGREEMENT_NOT_ACTIVE`) and the commitment must be `ACTIVE` (else
    `ERR_COMMITMENT_NOT_ACTIVE`)."

    Design: Corner/validations/booking_blocked_by_draft_commitment_returns_error
    """
    base = create_characterized_stream()
    generator, stream = base["generator"], base["stream"]
    offtaker = create_offtaker()
    agreement = create_active_agreement(generator["id"], stream["id"],
                                        committed_monthly_tons=100)
    commitment = create_draft_commitment(offtaker["id"], stream["id"],
                                         committed_monthly_tons=100)
    publish_price_index()

    resp = api.create_shipment(
        create_shipment_payload(
            agreement["id"], commitment["id"],
            get_agreement_version(agreement["id"]), gross_tons=10,
        ),
        make_generator_headers(generator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_ACTIVE)


def test_booking_with_unknown_commitment_fk_not_found(api):
    """PRD §2.10: "Sixth, every foreign key referenced in the request body —
    such as `generator_id`, `stream_id`, `supply_agreement_id`,
    `offtake_commitment_id`, or `facility_id` — must resolve to an existing
    entity, else `ERR_FK_NOT_FOUND`."

    Design: Corner/validations/booking_with_unknown_commitment_fk_not_found
    """
    base = create_characterized_stream()
    generator, stream = base["generator"], base["stream"]
    agreement = create_active_agreement(generator["id"], stream["id"],
                                        committed_monthly_tons=100)

    resp = api.create_shipment(
        create_shipment_payload(
            agreement["id"], NON_EXISTENT_UUID,
            get_agreement_version(agreement["id"]), gross_tons=10,
        ),
        make_generator_headers(generator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


def test_commitment_destination_not_served_returns_error(api):
    """PRD §3.3: "The commitment names the covered `stream_id` and the
    `destination_state_code` of the receiving site — which must appear in the
    offtaker's own `receiving_state_codes`, else the creation is rejected with
    `ERR_DESTINATION_NOT_SERVED`."

    Design: Corner/validations/commitment_destination_not_served_returns_error
    """
    generator = create_generator()
    stream = create_stream(generator["id"])
    offtaker = create_offtaker(hq_state_code="WV", receiving_state_codes=["WV"])

    resp = api.create_offtake_commitment(
        {
            "offtaker_id": offtaker["id"],
            "stream_id": stream["id"],
            "destination_state_code": "PA",
            "committed_monthly_tons": 100,
            "max_moisture_pct": 10.0,
            "max_arsenic_ppm": 5.0,
        },
        make_offtaker_headers(offtaker["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DESTINATION_NOT_SERVED)


def test_suspended_agreement_booking_reports_state_error(api):
    """PRD §2.10: "Every request passes through a fixed validation pipeline, and
    an earlier failure masks all later checks." State eligibility runs eighth —
    "for booking and dispatch specifically, the agreement and commitment must
    be `ACTIVE`, yielding `ERR_AGREEMENT_NOT_ACTIVE` or
    `ERR_COMMITMENT_NOT_ACTIVE` respectively" — while "Finally, thirteenth, the
    fiscal gates of booking (`ERR_COMMITMENT_EXCEEDED`, `ERR_PRICE_INDEX_GAP`)."

    Design: Difficulty/priority_pair_validation_conflict/booking_suspended_agreement_and_over_quota_reports_state_error
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=500)
    book_shipment(chain, gross_tons=60)
    book_shipment(chain, gross_tons=40)  # booked quota now exactly 100/100
    validate_success(
        api.suspend_supply_agreement(chain["agreement"]["id"], BROKER), 200
    )

    resp = api.create_shipment(
        create_shipment_payload(
            chain["agreement"]["id"], chain["commitment"]["id"],
            get_agreement_version(chain["agreement"]["id"]), gross_tons=1,
        ),
        chain["generator_headers"],
    )
    # Both ERR_AGREEMENT_NOT_ACTIVE (state) and ERR_COMMITMENT_EXCEEDED
    # (fiscal) are violated; the earlier pipeline stage wins.
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_suspended_agreement_booking_leaves_quota_untouched(api):
    """PRD §2.10: "Every request passes through a fixed validation pipeline, and
    an earlier failure masks all later checks."
    PRD §3.4: "As its quota side effect, booking adds `gross_tons` to the
    agreement's `booked_month_to_date_tons` (after rollover) and advances the
    agreement's `version` by one." — a rejected booking has no side effect.

    Design: Difficulty/priority_pair_validation_conflict/booking_suspended_agreement_and_over_quota_reports_state_error
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=500)
    book_shipment(chain, gross_tons=60)
    book_shipment(chain, gross_tons=40)
    validate_success(
        api.suspend_supply_agreement(chain["agreement"]["id"], BROKER), 200
    )

    resp = api.create_shipment(
        create_shipment_payload(
            chain["agreement"]["id"], chain["commitment"]["id"],
            get_agreement_version(chain["agreement"]["id"]), gross_tons=1,
        ),
        chain["generator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["booked_month_to_date_tons"] == pytest.approx(
        100
    ), "rejected booking must not change booked_month_to_date_tons"


def test_booking_at_exact_quota_allowed(api):
    """PRD §3.4: "Monthly quotas then bind on both sides, evaluated after any
    monthly rollover: the agreement's `booked_month_to_date_tons` plus the new
    `gross_tons` must not exceed the agreement's `committed_monthly_tons`, and
    the commitment's `accepted_month_to_date_tons` plus the new `gross_tons`
    must not exceed the commitment's `committed_monthly_tons`; either breach is
    rejected with `ERR_COMMITMENT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/booking_exactly_at_committed_tonnage_allowed_one_more_rejected
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=500)
    book_shipment(chain, gross_tons=60)
    second = book_shipment(chain, gross_tons=40)  # lands exactly on 100

    assert second["status"] == "BOOKED"
    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["booked_month_to_date_tons"] == pytest.approx(100)
    assert (
        agreement_after["booked_month_to_date_tons"]
        == agreement_after["committed_monthly_tons"]
    ), "equality with committed_monthly_tons is allowed (must not exceed)"


def test_one_ton_over_quota_rejected(api):
    """PRD §3.4: "Monthly quotas then bind on both sides, evaluated after any
    monthly rollover: the agreement's `booked_month_to_date_tons` plus the new
    `gross_tons` must not exceed the agreement's `committed_monthly_tons`, and
    the commitment's `accepted_month_to_date_tons` plus the new `gross_tons`
    must not exceed the commitment's `committed_monthly_tons`; either breach is
    rejected with `ERR_COMMITMENT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/booking_exactly_at_committed_tonnage_allowed_one_more_rejected
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=500)
    book_shipment(chain, gross_tons=60)
    book_shipment(chain, gross_tons=40)

    resp = api.create_shipment(
        create_shipment_payload(
            chain["agreement"]["id"], chain["commitment"]["id"],
            get_agreement_version(chain["agreement"]["id"]), gross_tons=1,
        ),
        chain["generator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXCEEDED)

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["booked_month_to_date_tons"] == pytest.approx(
        100
    ), "rejected booking must leave booked_month_to_date_tons at 100"


def test_occ_stale_version_rejected_correct_version_succeeds(api):
    """PRD §2.9: "A booking request must carry
    `expected_supply_agreement_version`, a non-optional field holding the
    `version` of the target supply agreement as the client last observed it. If
    that value does not match the agreement's current `version`, the booking is
    rejected with `ERR_STALE_AGREEMENT_VERSION` and HTTP status 412."
    PRD §3.4: "As its quota side effect, booking adds `gross_tons` to the
    agreement's `booked_month_to_date_tons` (after rollover) and advances the
    agreement's `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_version_rejected_correct_version_succeeds
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=100)
    observed_version = get_agreement_version(chain["agreement"]["id"])

    # Correct version: booking succeeds and advances the agreement version.
    first = validate_success(
        api.create_shipment(
            create_shipment_payload(
                chain["agreement"]["id"], chain["commitment"]["id"],
                observed_version, gross_tons=10,
            ),
            chain["generator_headers"],
        ),
        201,
    )
    assert first["status"] == "BOOKED"
    version_after = get_agreement_version(chain["agreement"]["id"])
    assert (
        version_after == observed_version + 1
    ), "booking must advance the agreement version by exactly one"

    # Replaying the stale observed version is rejected.
    resp = api.create_shipment(
        create_shipment_payload(
            chain["agreement"]["id"], chain["commitment"]["id"],
            observed_version, gross_tons=10, pickup_date="2026-08-06",
        ),
        chain["generator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["booked_month_to_date_tons"] == pytest.approx(
        10
    ), "only the first booking may apply its quota side effect"


def test_monthly_counter_rollover_resets_quota(api):
    """PRD §2.4: "At the start of any read or mutation that touches one of these
    counters, if the record's `counter_month` differs from the current logical
    month, the counters are reset to zero and `counter_month` is re-stamped to
    the current month. This rollover is a derived-field refresh, not a business
    mutation: it does not increment `version` and does not refresh
    `updated_at`."

    Design: Corner/cross_cutting_layers/monthly_counter_rollover_resets_quota
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=1000)
    version_after_activation = get_agreement_version(chain["agreement"]["id"])
    book_shipment(chain, gross_tons=100)  # August quota fully booked
    version_after_booking = get_agreement_version(chain["agreement"]["id"])
    assert version_after_booking == version_after_activation + 1

    set_logical_clock("2026-09-01T00:00:00Z")

    september_read = get_agreement(chain["agreement"]["id"])
    assert september_read["booked_month_to_date_tons"] == pytest.approx(
        0
    ), "September read must reconcile booked_month_to_date_tons to 0"
    assert (
        september_read["counter_month"] == "2026-09"
    ), f"counter_month must be re-stamped to 2026-09, got {september_read['counter_month']}"
    assert (
        september_read["version"] == version_after_booking
    ), "rollover is a derived-field refresh and must not increment version"

    september_booking = book_shipment(chain, gross_tons=50, pickup_date="2026-09-10")
    assert september_booking["status"] == "BOOKED", (
        "booking must succeed in the new month despite August's 100/100"
    )
    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["booked_month_to_date_tons"] == pytest.approx(50)


def test_list_shipments_pagination_limit_offset(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The
    `offset` parameter skips that many items from the start of the result set
    and defaults to 0. Unless otherwise specified, every list endpoint returns
    resources sorted by creation timestamp in ascending order. The `meta`
    object of a list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_shipments_pagination_limit_offset
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=1000,
                                      committed_commitment_tons=1000)
    s1 = book_shipment(chain, gross_tons=10)
    s2 = book_shipment(chain, gross_tons=10, pickup_date="2026-08-06")
    s3 = book_shipment(chain, gross_tons=10, pickup_date="2026-08-07")

    page1, meta1 = validate_paginated(
        api.list_shipments(BROKER, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
    assert [s["id"] for s in page1] == [s1["id"], s2["id"]], (
        "page 1 must hold the first two shipments in ascending creation order"
    )

    page2, meta2 = validate_paginated(
        api.list_shipments(BROKER, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False
    assert page2[0]["id"] == s3["id"]
