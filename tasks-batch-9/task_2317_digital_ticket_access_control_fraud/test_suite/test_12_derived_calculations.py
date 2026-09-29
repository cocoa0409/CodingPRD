"""Figures the server computes rather than stores, read at their exact turning points.

A token that is a pure function of a seed and a clock epoch, a regime with no
ceiling at all, a posture band entered on an exact ratio, a percentage guarded
against a zero denominator, and a projection that declines to divide.
"""

from test_helpers import (
    AdmissionStatus,
    CredentialRequestStatus,
    DistributionType,
    EventStatus,
    GateStatus,
    LifecycleStatus,
    ListingStatus,
    PriceCapRegime,
    ReportStatus,
    VENUE_ADMIN,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_success,
)


def test_the_barcode_is_identical_inside_one_epoch_and_different_in_the_next(api):
    """Two reads at 18:10:00 agree; the read at 18:10:30 does not.

    PRD: "The **epoch index** for an instant is the difference between that instant and the anchor, divided by 30 seconds and rounded down toward negative infinity, so instants before the anchor yield negative indices."
    PRD: "A ticket's barcode at any instant is its server-minted `barcode_seed`, then a single hyphen, then the decimal epoch index for that instant."
    PRD: "The barcode read endpoint returns the ticket's `ticket_id`, its `barcode_seed`, the `barcode_epoch_index` current at the logical clock, the assembled `current_barcode`, and the `accepted_epoch_floor`, which is one epoch below the current index."

    Design: Corner/calculations/rotating_barcode_is_stable_within_an_epoch_and_changes_across_epochs
    """
    venue = fx.on_sale_venue(api)
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(api, venue["event"]["id"], venue["zone"]["id"], ada["id"])

    fx.set_clock(api, C.T_18_10_00)
    first = fx.get_barcode(api, ticket["id"])
    # Six hundred seconds after the anchor, divided by the thirty-second rotation.
    assert first["barcode_epoch_index"] == C.EPOCH_AT_18_10_00
    assert first["accepted_epoch_floor"] == C.EPOCH_AT_18_10_00 - C.SKEW_TOLERANCE_EPOCHS
    assert first["ticket_id"] == ticket["id"]
    assert first["current_barcode"] == f"{first['barcode_seed']}-{C.EPOCH_AT_18_10_00}"

    second = fx.get_barcode(api, ticket["id"])
    # The token is a pure function of the seed and the epoch, so nothing rotated.
    assert second["barcode_epoch_index"] == C.EPOCH_AT_18_10_00
    assert second["current_barcode"] == first["current_barcode"]

    fx.set_clock(api, C.T_18_10_30)
    third = fx.get_barcode(api, ticket["id"])
    assert third["barcode_epoch_index"] == C.EPOCH_AT_18_10_30
    assert third["accepted_epoch_floor"] == C.EPOCH_AT_18_10_00
    assert third["current_barcode"] != first["current_barcode"]

    # Three computed reads are still reads.
    assert fx.read_ticket(api, ticket["id"])["version"] == 1


def test_a_regime_of_none_stores_no_cap_and_accepts_a_wildly_high_ask(api):
    """An ask of 9,999,900 cents on a 12,000-cent seat is listed with a null cap.

    PRD: "The **price cap** for a listing is computed before the asking price is compared against it, and it is written to the listing as `cap_price_cents`."
    PRD: "When the event's `price_cap_regime` is `NONE`, there is no cap at all and any `ask_price_cents` of at least 0 is accepted."
    PRD: "The server records the acting patron as `seller_patron_id`, leaves `buyer_patron_id` null, and sets `superseded_listing_id` to the most recent `DELISTED` or `SUSPENDED` listing on the same ticket ordered by `created_at` descending, or null when this is the ticket's first listing."

    Design: Corner/calculations/price_cap_regime_none_permits_any_ask_price_with_a_null_cap
    """
    venue = fx.on_sale_venue(api, price_cap_regime=PriceCapRegime.NONE)
    assert venue["event"]["price_cap_regime"] == PriceCapRegime.NONE
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(
        api, venue["event"]["id"], venue["zone"]["id"], ada["id"], face_value_cents=12000
    )
    assert ticket["version"] == 1

    listing = validate_success(
        api.create_resale_listing(
            f.resale_listing_payload(ticket["id"], 9999900, ticket["version"]),
            make_patron_headers(ada["id"]),
        ),
        201,
    )

    # No cap at all is not the same figure as a cap of zero, nor as the face value.
    assert listing["cap_price_cents"] is None
    assert listing["status"] == ListingStatus.LISTED
    assert listing["seller_patron_id"] == ada["id"]
    assert listing["buyer_patron_id"] is None
    assert listing["superseded_listing_id"] is None
    # The ask was stored as submitted rather than clamped to anything.
    assert listing["ask_price_cents"] == 9999900

    assert fx.read_ticket(api, ticket["id"])["lifecycle_status"] == LifecycleStatus.LISTED


def test_the_ninth_of_ten_places_restricts_the_zone_and_the_tenth_freezes_it(api):
    """0.80 is `OPEN`, exactly 0.90 is `RESTRICTED`, exactly 1.00 is `FROZEN`.

    PRD: "The posture is derived from the exact ratio of `issued_entitlement_count` to the zone's `fire_code_capacity`, compared without rounding: the posture is `FROZEN` when that ratio is at least 1.00, `RESTRICTED` when it is at least 0.90 but below 1.00, and `OPEN` otherwise."
    PRD: "Both boundaries are inclusive."
    PRD: "`RESTRICTED` is advisory and still permits credential submission and approval; `FROZEN` blocks both, with `ERR_ZONE_FROZEN`."
    PRD: "Issuance moves three counters. The target zone's `issued_entitlement_count` rises by one and its `posture` is recomputed; the event's `entitlements_outstanding` rises by one; and only when the `ticket_type` is `PAID` does the event's `settlement_pool_cents` rise by the ticket's `face_value_cents`."

    Design: Corner/calculations/zone_posture_restricted_band_at_exactly_the_zero_point_nine_ratio
    """
    event = fx.create_event(api)
    zone = fx.create_zone(
        api, event["id"], zone_code="SMALL", fire_code_capacity=10, credential_capacity=4
    )
    fx.create_gate(api, event["id"], zone["id"])
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)
    ada = fx.register_patron(api)

    def sell_one_seat():
        return fx.issue_ticket(
            api, event["id"], zone["id"], ada["id"], face_value_cents=12000
        )

    for _ in range(8):
        sell_one_seat()
    eight = fx.read_zone(api, zone["id"])
    assert eight["issued_entitlement_count"] == 8
    # Eight of ten is 0.80, short of the advisory band.
    assert eight["posture"] == ZonePosture.OPEN

    sell_one_seat()
    nine = fx.read_zone(api, zone["id"])
    assert nine["issued_entitlement_count"] == 9
    # Exactly 0.90, and the comparison includes its boundary.
    assert nine["posture"] == ZonePosture.RESTRICTED

    draft = fx.create_credential_draft(
        api,
        event["id"],
        zone["id"],
        ada["id"],
        distribution_type=DistributionType.COMP,
        quantity=1,
        valid_from="2026-09-12T18:00:00Z",
        valid_until="2026-09-12T22:00:00Z",
        justification="Submitted while the zone is RESTRICTED",
    )
    submitted = fx.submit_credential_request(api, draft["id"])
    # The advisory band advises; it does not refuse.
    assert submitted["status"] == CredentialRequestStatus.SUBMITTED

    sell_one_seat()
    ten = fx.read_zone(api, zone["id"])
    assert ten["issued_entitlement_count"] == 10
    assert ten["posture"] == ZonePosture.FROZEN

    final = fx.read_event(api, event["id"])
    # The submission minted nothing, so only the ten paid seats count.
    assert final["entitlements_outstanding"] == 10
    assert final["settlement_pool_cents"] == 120000


def test_a_report_with_no_scans_behind_it_pins_the_variance_percentage_at_zero(api):
    """Five reported against nought derived is a variance of five and a percentage of 0.00.

    PRD: "The **reconciled** reading, persisted as a report's `scan_derived_attendance` and surfaced as `reconciled_attendance` on the occupancy read, counts distinct `ticket_id` values across scan events whose `result` is `ADMITTED` regardless of `source`, so offline-replayed scans are included, processed in ascending `scanned_at` order with ascending `recorded_at` as the tie-break."
    PRD: "At creation the report's derived figures are computed: `scan_derived_attendance` from the reconciled reading of §2.9, `variance_count` as the `reported_attendance` minus `scan_derived_attendance`, `variance_pct` as that variance divided by `scan_derived_attendance`, multiplied by 100 and rounded half up to two decimal places — defined as exactly 0.00 when `scan_derived_attendance` is zero, rather than an error — and `fire_code_breach` set true when `scan_derived_attendance` exceeds the event's `fire_code_capacity`."
    PRD: "**Finalization** requires the report to be `DRAFT` or `REOPENED`, and requires the absolute value of `variance_pct` to be no greater than 2.00 percent — or, failing that, a non-empty `override_reason` supplied with the request."

    Design: Corner/calculations/reconciliation_variance_pct_is_zero_when_no_scan_was_derived
    """
    venue = fx.closed_venue_with_report(api, 5)
    report = venue["report"]

    assert report["scan_derived_attendance"] == 0
    assert report["variance_count"] == 5
    # The guard fires ahead of the division rather than after it.
    assert report["variance_pct"] == 0.00
    # Nobody was counted through the doors, so no ceiling was passed.
    assert report["fire_code_breach"] is False
    assert report["status"] == ReportStatus.DRAFT
    assert report["override_reason"] is None

    finalized = validate_success(
        api.finalize_reconciliation_report(report["id"], f.finalize_payload(), VENUE_ADMIN)
    )
    # A pinned 0.00 sits inside the tolerance, so no correction had to be justified.
    assert finalized["status"] == ReportStatus.FINAL
    assert finalized["variance_pct"] == 0.00
    assert finalized["variance_count"] == 5

    assert fx.read_event(api, venue["event"]["id"])["status"] == EventStatus.RECONCILED


def test_an_idle_turnstile_yields_no_projection_while_the_rest_of_the_read_stands(api):
    """One person waiting and nought places a minute gives null, not zero.

    PRD: "Only gates whose `status` is `SCANNING` contribute throughput; an `IDLE` gate contributes nothing."
    PRD: "`projected_clearance_minutes` is the waiting population divided by the capacity per minute, rounded *up* to a whole minute; when no gate is scanning, and therefore capacity per minute is zero, `projected_clearance_minutes` is null rather than an error."
    PRD: "Alongside it the read reports the event's `event_id`, `live_occupancy`, `peak_live_occupancy`, `reconciled_attendance`, `fire_code_capacity`, the `headroom` remaining (the event's fire-code capacity less its live occupancy), and a `zone_occupancy` array carrying, for each access zone of the event, that zone's `id`, `zone_code`, `occupancy_count` and `fire_code_capacity`."

    Design: Corner/calculations/clearance_projection_is_null_while_every_gate_is_idle
    """
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"], fire_code_capacity=150)
    gate = fx.create_gate(api, event["id"], zone["id"], throughput_per_minute=20, lanes_open=2)
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(api, event["id"], zone["id"], ada["id"])
    fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)

    read = fx.read_occupancy(api, event["id"])

    # Forty rated places a minute count for nothing while the gate sits idle.
    assert read["projected_clearance_minutes"] is None
    assert read["event_id"] == event["id"]
    assert read["live_occupancy"] == 0
    assert read["peak_live_occupancy"] == 0
    assert read["reconciled_attendance"] == 0
    assert read["fire_code_capacity"] == 200
    assert read["headroom"] == 200

    assert len(read["zone_occupancy"]) == 1
    row = read["zone_occupancy"][0]
    assert row["id"] == zone["id"]
    assert row["zone_code"] == "GA1"
    assert row["occupancy_count"] == 0
    assert row["fire_code_capacity"] == 150

    assert fx.read_gate(api, gate["id"])["status"] == GateStatus.IDLE
    assert fx.read_zone(api, zone["id"])["posture"] == ZonePosture.OPEN
    assert fx.read_ticket(api, ticket["id"])["admission_status"] == AdmissionStatus.NOT_ADMITTED
