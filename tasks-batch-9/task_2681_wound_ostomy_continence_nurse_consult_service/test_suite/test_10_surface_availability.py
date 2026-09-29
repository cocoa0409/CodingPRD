"""One physical bed, one occupation interval and twelve hours of reclean: the
asymmetric contention rule, the retirement guard and the buffer-gated release."""
from test_helpers import (
    approve_order,
    as_instant,
    create_order,
    create_patient,
    create_surface,
    create_unit,
    deliver_order,
    get_success_data,
    read_unit_version,
    return_order,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_materials_headers


DIRECTOR = make_director_headers()
MATERIALS = make_materials_headers()


def _ward_with_one_asset(api, mrn_list, asset_tag="BED-040", cap=500000):
    """A funded ward, one asset and however many admitted patients are asked for."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=cap,
    )
    patients = [
        create_patient(unit, api=api, mrn=mrn, admitted_at="2026-07-30T00:00:00Z")
        for mrn in mrn_list
    ]
    surface = create_surface(
        api,
        asset_tag=asset_tag,
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="AirBeds Inc",
    )
    return unit, patients, surface


def _asset(api, surface_id):
    return get_success_data(api.get_support_surface(surface_id, MATERIALS))


def test_the_next_rental_may_not_start_until_the_reclean_buffer_has_run(api):
    """Twelve hours of rental_start is the only difference between 409 and 200.

    PRD §3.8: "The blocked span of an existing order on the same
    `support_surface_id` runs from that order's `rental_start` up to but not
    including its `rental_end` plus 12 hours of reclean time. Approval is refused
    with `ERR_SURFACE_UNAVAILABLE` when the candidate span intersects the blocked
    span of any other order on that asset whose `fulfillment_status` is `APPROVED`
    or `DELIVERED`."
    PRD §3.8: "Approving an order on the asset moves it `AVAILABLE → IN_USE` (or
    `CLEANING → IN_USE`, since a freshly recleaned bed may be booked straight out
    again) and writes the occupation high-water mark: `occupied_until` becomes the
    approved order's `rental_end` and `available_from` becomes that same instant
    plus 12 hours of reclean time."

    Design: Difficulty/resource_temporal_overlap/surface_adjacent_rental_rejected_by_clean_buffer
    """
    unit, (first_patient, second_patient), surface = _ward_with_one_asset(
        api, ["MRN-N1", "MRN-N2"]
    )
    held = create_order(
        unit,
        first_patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-04T00:00:00Z",
        authorized_days=3,
    )
    touching = create_order(
        unit,
        second_patient,
        surface,
        api=api,
        rental_start="2026-08-04T00:00:00Z",
        rental_end="2026-08-07T00:00:00Z",
        authorized_days=3,
    )
    clear_of_the_buffer = create_order(
        unit,
        second_patient,
        surface,
        api=api,
        rental_start="2026-08-04T12:00:00Z",
        rental_end="2026-08-07T12:00:00Z",
        authorized_days=3,
    )
    for order in (held, touching, clear_of_the_buffer):
        assert order["authorized_cost_cents"] == 32400, (
            "identical duration, identical asset, identical price"
        )

    approve_order(held, unit, api=api)
    occupied = _asset(api, surface["id"])
    assert occupied["status"] == "IN_USE"
    assert as_instant(occupied["occupied_until"]) == as_instant("2026-08-04T00:00:00Z")
    assert as_instant(occupied["available_from"]) == as_instant("2026-08-04T12:00:00Z")

    unit_version = read_unit_version(unit["id"], api=api)
    validate_error(
        api.approve_support_surface_order(
            touching["id"], {"expected_unit_version": unit_version}, MATERIALS
        ),
        "ERR_SURFACE_UNAVAILABLE",
        expected_status=409,
    )
    refused = get_success_data(
        api.get_support_surface_order(touching["id"], MATERIALS)
    )
    assert refused["fulfillment_status"] == "REQUESTED", (
        "a start at the exact instant the first rental ends is still inside the buffer"
    )
    assert refused["billing_status"] == "UNBILLED"

    accepted = validate_success(
        api.approve_support_surface_order(
            clear_of_the_buffer["id"],
            {"expected_unit_version": unit_version},
            MATERIALS,
        )
    )
    assert accepted["fulfillment_status"] == "APPROVED", (
        "the candidate meets the blocked span only at its exclusive upper bound"
    )
    ledger = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ledger["rental_encumbered_cents"] == 64800, "the refused order paid nothing"
    assert ledger["rental_available_cents"] == 435200
    rebooked = _asset(api, surface["id"])
    assert as_instant(rebooked["occupied_until"]) == as_instant("2026-08-07T12:00:00Z")
    assert as_instant(rebooked["available_from"]) == as_instant("2026-08-08T00:00:00Z")


def test_the_buffer_hangs_off_the_end_of_a_rental_and_never_off_its_start(api):
    """A rental ending where another begins is fine; the same gap after it is not.

    PRD §3.8: "Occupation contention uses half-open arithmetic with a trailing
    buffer, and it is asymmetric on purpose. The candidate span is the order's own
    `[rental_start, rental_end)`."
    PRD §3.8: "This check is computed from the live order rows rather than from the
    asset's `occupied_until` marker, so it remains correct when several orders have
    been written against the same asset."
    PRD §3.8: "Where several orders have driven the same asset, the marks reflect
    the driving order chosen by the latest `created_at`."

    Design: Difficulty/resource_temporal_overlap/surface_adjacent_rental_rejected_by_clean_buffer
    """
    unit, (first_patient, second_patient), surface = _ward_with_one_asset(
        api, ["MRN-N1", "MRN-N2"]
    )
    later_stay = create_order(
        unit,
        first_patient,
        surface,
        api=api,
        rental_start="2026-08-04T00:00:00Z",
        rental_end="2026-08-07T00:00:00Z",
        authorized_days=3,
    )
    earlier_stay = create_order(
        unit,
        second_patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-04T00:00:00Z",
        authorized_days=3,
    )
    after_the_marker = create_order(
        unit,
        second_patient,
        surface,
        api=api,
        rental_start="2026-08-04T12:00:00Z",
        rental_end="2026-08-07T12:00:00Z",
        authorized_days=3,
    )

    approve_order(later_stay, unit, api=api)
    assert as_instant(_asset(api, surface["id"])["available_from"]) == as_instant("2026-08-07T12:00:00Z")

    accepted = approve_order(earlier_stay, unit, api=api)
    assert accepted["fulfillment_status"] == "APPROVED", (
        "a candidate ending exactly where a booked rental starts intersects nothing, "
        "because the buffer is trailing only"
    )
    regressed = _asset(api, surface["id"])
    assert as_instant(regressed["occupied_until"]) == as_instant("2026-08-04T00:00:00Z"), (
        "the marks follow the most recently created driving order, so they moved "
        "backwards"
    )
    assert as_instant(regressed["available_from"]) == as_instant("2026-08-04T12:00:00Z")

    unit_version = read_unit_version(unit["id"], api=api)
    validate_error(
        api.approve_support_surface_order(
            after_the_marker["id"], {"expected_unit_version": unit_version}, MATERIALS
        ),
        "ERR_SURFACE_UNAVAILABLE",
        expected_status=409,
    )
    assert get_success_data(
        api.get_support_surface_order(after_the_marker["id"], MATERIALS)
    )["fulfillment_status"] == "REQUESTED", (
        "the marker said the bed was free from 2026-08-04T12:00:00Z, but the live "
        "order rows say otherwise"
    )
    ledger = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ledger["rental_encumbered_cents"] == 64800
    assert ledger["rental_available_cents"] == 435200


def test_an_asset_nobody_has_booked_yet_still_cannot_be_retired(api):
    """The retirement guard reads the order rows, not the asset's own status.

    PRD §3.8: "A coordinator retires an asset from either `AVAILABLE` or
    `CLEANING` with a `reason`, and only when no order on that asset has a
    `fulfillment_status` of `REQUESTED`, `APPROVED` or `DELIVERED`; an attempt
    while any such order is live, like an attempt to order a `RETIRED` asset, is
    refused with `ERR_RESOURCE_NOT_ACTIVE`."
    PRD §3.8: "A new asset starts with `status` `AVAILABLE` and with
    `occupied_until` and `available_from` both null."

    Design: Corner/state_machines/retire_surface_with_live_order_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=500000,
    )
    patient = create_patient(
        unit, api=api, mrn="MRN-G9", admitted_at="2026-07-31T00:00:00Z"
    )
    surface = create_surface(
        api,
        asset_tag="BED-080",
        surface_class="ALTERNATING_PRESSURE",
        daily_rate_cents=10000,
        vendor_name="AirBeds Inc",
    )
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-04T00:00:00Z",
        authorized_days=3,
    )
    assert order["fulfillment_status"] == "REQUESTED"
    assert _asset(api, surface["id"])["status"] == "AVAILABLE"

    validate_error(
        api.retire_support_surface(surface["id"], {"reason": "Vendor recall."}, MATERIALS),
        "ERR_RESOURCE_NOT_ACTIVE",
        expected_status=409,
    )
    assert _asset(api, surface["id"])["status"] == "AVAILABLE", (
        "the asset's own status would have permitted retirement; the live order did not"
    )

    denied = validate_success(
        api.deny_support_surface_order(
            order["id"], {"denial_reason": "Asset being recalled."}, MATERIALS
        )
    )
    assert denied["fulfillment_status"] == "DENIED"
    assert denied["billing_status"] == "UNBILLED"
    assert denied["denial_reason"] == "Asset being recalled."
    ledger = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ledger["rental_encumbered_cents"] == 0
    assert ledger["rental_released_cents"] == 0, (
        "denying a never-approved order moves no money in either direction"
    )

    retired = validate_success(
        api.retire_support_surface(surface["id"], {"reason": "Vendor recall."}, MATERIALS)
    )
    assert retired["status"] == "RETIRED"
    assert retired["occupied_until"] is None
    assert retired["available_from"] is None, (
        "both marks stay null until the asset's first approval"
    )


def test_the_reclean_release_waits_for_the_clock_and_fires_on_the_bound(api):
    """Two identical reconciles on two identical beds, separated only by the clock.

    PRD §3.8: "Reconciling the order's invoice moves the asset `CLEANING →
    AVAILABLE`, but only when the logical clock has reached or passed
    `available_from`; if the reclean buffer has not yet elapsed the asset stays
    `CLEANING`."
    PRD §3.8: "Returning the asset moves it `IN_USE → CLEANING` and rewrites the
    marks from reality: `occupied_until` becomes the order's `actual_return_at` and
    `available_from` becomes that instant plus the same 12 hours."

    Design: Corner/state_machines/reconcile_returns_surface_to_available_only_at_buffer_end
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=500000,
    )
    patient = create_patient(
        unit, api=api, mrn="MRN-H6", admitted_at="2026-07-31T00:00:00Z"
    )
    early_bed, late_bed = (
        create_surface(
            api,
            asset_tag=asset_tag,
            surface_class="LOW_AIR_LOSS",
            daily_rate_cents=10000,
            vendor_name="AirBeds Inc",
        )
        for asset_tag in ("BED-090", "BED-091")
    )
    early_order, late_order = (
        create_order(
            unit,
            patient,
            bed,
            api=api,
            rental_start="2026-08-01T00:00:00Z",
            rental_end="2026-08-04T00:00:00Z",
            authorized_days=3,
        )
        for bed in (early_bed, late_bed)
    )
    approve_order(early_order, unit, api=api)
    approve_order(late_order, unit, api=api)
    set_clock("2026-08-04T00:00:00Z", api=api)
    deliver_order(early_order, "2026-08-01T00:00:00Z", api=api)
    deliver_order(late_order, "2026-08-01T00:00:00Z", api=api)
    early_returned = return_order(early_order, "2026-08-04T00:00:00Z", api=api)
    late_returned = return_order(late_order, "2026-08-04T00:00:00Z", api=api)
    assert early_returned["actual_cost_cents"] == 32400
    assert late_returned["actual_cost_cents"] == 32400
    for bed in (early_bed, late_bed):
        cleaning = _asset(api, bed["id"])
        assert cleaning["status"] == "CLEANING"
        assert as_instant(cleaning["occupied_until"]) == as_instant("2026-08-04T00:00:00Z")
        assert as_instant(cleaning["available_from"]) == as_instant("2026-08-04T12:00:00Z")

    too_early = validate_success(
        api.reconcile_support_surface_order(early_order["id"], {}, MATERIALS)
    )
    assert too_early["billing_status"] == "RECONCILED"
    assert _asset(api, early_bed["id"])["status"] == "CLEANING", (
        "the billing move happened while the buffer held the asset back"
    )

    set_clock("2026-08-04T12:00:00Z", api=api)
    on_the_bound = validate_success(
        api.reconcile_support_surface_order(late_order["id"], {}, MATERIALS)
    )
    assert on_the_bound["billing_status"] == "RECONCILED"
    assert _asset(api, late_bed["id"])["status"] == "AVAILABLE", (
        "the bound is inclusive, so a clock equal to available_from releases the bed"
    )
    assert _asset(api, early_bed["id"])["status"] == "CLEANING", (
        "the first bed is not swept along; only a reconcile of its own order frees it"
    )

    ledger = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ledger["rental_encumbered_cents"] == 0
    assert ledger["rental_committed_cents"] == 64800
    assert ledger["rental_released_cents"] == 0
    assert ledger["rental_available_cents"] == 435200
