"""Inclusive edges, pinned together with the value one step on the other side.

An epoch exactly on the skew floor, an ask exactly on the cap, and a re-entry
exactly on the lockout's upper bound — each paired with its neighbour so an
off-by-one implementation cannot pass.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    EventStatus,
    FraudRiskBasis,
    IncidentCategory,
    IncidentStatus,
    LifecycleStatus,
    ListingStatus,
    SECURITY_INVESTIGATOR,
    ScanResult,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _three_holders_at_epoch_twenty(api):
    """Three bound seats, a session open at 18:10:00, and two barcodes captured."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    holders = {}
    for key, email, name, reference in (
        ("ada", "ada@example.com", "Ada Lovelace", "DL-ADA-1"),
        ("ben", "ben@example.com", "Ben Hall", "DL-BEN-1"),
        ("cyd", "cyd@example.com", "Cyd Marsh", "DL-CYD-1"),
    ):
        patron = fx.register_patron(
            api, email=email, display_name=name, document_reference=reference
        )
        ticket = fx.issue_ticket(api, event_id, venue["zone"]["id"], patron["id"])
        fx.bind_device(api, ticket["id"], patron["id"], f"DEV-{key.upper()}")
        holders[key] = {"patron": patron, "ticket": ticket}

    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    venue["session"] = fx.open_scan_session(api, venue["gate"]["id"])
    venue["holders"] = holders
    venue["epoch_20"] = {
        key: fx.get_barcode(api, holders[key]["ticket"]["id"]) for key in ("ada", "ben")
    }
    return venue


def test_an_epoch_on_the_skew_floor_and_an_epoch_on_the_ceiling_are_both_admitted(api):
    """The accepted window is closed at both ends, so 20-at-21 and 22-at-22 both pass.

    PRD: "The accepted window is exactly the closed integer range from one below the current index up to and including the current index — one epoch of skew tolerance, which is what makes a forwarded screenshot useless within a minute."
    PRD: "The barcode read endpoint returns the ticket's `ticket_id`, its `barcode_seed`, the `barcode_epoch_index` current at the logical clock, the assembled `current_barcode`, and the `accepted_epoch_floor`, which is one epoch below the current index."

    Design: Difficulty/boundary_precision_check/barcode_epoch_skew_floor_is_inclusive_and_one_epoch_older_is_refused
    """
    venue = _three_holders_at_epoch_twenty(api)
    at_twenty = venue["epoch_20"]["ada"]
    assert at_twenty["barcode_epoch_index"] == C.EPOCH_AT_18_10_00
    assert at_twenty["accepted_epoch_floor"] == C.EPOCH_AT_18_10_00 - 1

    fx.set_clock(api, C.T_18_10_30)
    at_floor = fx.live_scan(
        api, venue["session"]["id"], at_twenty["current_barcode"], "DEV-ADA", "S1-ONLINE-001"
    )
    assert at_floor["result"] == ScanResult.ADMITTED

    fx.set_clock(api, C.T_18_11_00)
    at_twenty_two = fx.get_barcode(api, venue["holders"]["cyd"]["ticket"]["id"])
    assert at_twenty_two["barcode_epoch_index"] == C.EPOCH_AT_18_11_00
    assert at_twenty_two["accepted_epoch_floor"] == C.EPOCH_AT_18_11_00 - 1

    at_ceiling = fx.live_scan(
        api,
        venue["session"]["id"],
        at_twenty_two["current_barcode"],
        "DEV-CYD",
        "S1-ONLINE-003",
    )
    assert at_ceiling["result"] == ScanResult.ADMITTED

    for key in ("ada", "cyd"):
        ticket = fx.read_ticket(api, venue["holders"][key]["ticket"]["id"])
        assert ticket["admission_status"] == AdmissionStatus.INSIDE
    assert fx.read_event(api, venue["event"]["id"])["live_occupancy"] == 2
    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 2


def test_an_epoch_one_step_below_the_floor_is_treated_as_a_replayed_screenshot(api):
    """Epoch 20 presented at epoch 22 is refused and read as counterfeit.

    PRD: "Otherwise the server computes the epoch index of the logical clock; if the presented epoch part is greater than that index, or is smaller than that index minus one, the scan is adjudicated `DENIED_STALE_BARCODE` and reported as `ERR_BARCODE_EPOCH_INVALID`."
    PRD: "`DENIED_STALE_BARCODE` also maps to `COUNTERFEIT`, because an out-of-window epoch is a replayed screenshot"

    Design: Difficulty/boundary_precision_check/barcode_epoch_skew_floor_is_inclusive_and_one_epoch_older_is_refused
    """
    venue = _three_holders_at_epoch_twenty(api)
    ben = venue["holders"]["ben"]

    fx.set_clock(api, C.T_18_11_00)
    validate_error(
        fx.denied_scan_response(
            api,
            venue["session"]["id"],
            venue["epoch_20"]["ben"]["current_barcode"],
            "DEV-BEN",
            "S1-ONLINE-002",
        ),
        ApiErrorId.BARCODE_EPOCH_INVALID,
        422,
    )

    ticket = fx.read_ticket(api, ben["ticket"]["id"])
    assert ticket["admission_status"] == AdmissionStatus.DENIED_FLAGGED
    assert ticket["admitted_scan_count"] == 0

    events = fx.list_scan_events(api, ticket_id=ben["ticket"]["id"])
    assert len(events) == 1
    assert events[0]["result"] == ScanResult.DENIED_STALE_BARCODE
    assert events[0]["denied_reason_code"] == ApiErrorId.BARCODE_EPOCH_INVALID

    incidents = fx.list_incidents(api, ticket_id=ben["ticket"]["id"])
    assert len(incidents) == 1
    assert incidents[0]["category"] == IncidentCategory.COUNTERFEIT
    assert incidents[0]["status"] == IncidentStatus.OPEN

    patron = fx.read_patron(api, ben["patron"]["id"])
    assert patron["fraud_risk_score"] == 50
    assert patron["fraud_risk_basis"] == FraudRiskBasis.PROVISIONAL


def _ada_with_a_paid_seat(api):
    """One verified holder and one unbound 12000-cent seat, ready to be listed."""
    venue = fx.ticketed_venue(api)
    venue["seller"] = make_patron_headers(venue["holder"]["id"])
    return venue


def _list_at(api, venue, ask):
    ticket = fx.read_ticket(api, venue["ticket"]["id"])
    return api.create_resale_listing(
        f.resale_listing_payload(ticket["id"], ask, ticket["version"]), venue["seller"]
    )


def test_an_ask_equal_to_the_cap_is_accepted_and_one_cent_over_is_refused(api):
    """14500 lists; 14501, exactly one cent further, does not.

    PRD: "A listing is accepted when there is no cap or when `ask_price_cents` is less than or equal to the cap; equality is accepted, and only a strictly greater ask is refused with `ERR_PRICE_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/resale_ask_price_equal_to_cap_accepted_and_one_cent_over_refused
    """
    venue = _ada_with_a_paid_seat(api)

    at_cap = validate_success(_list_at(api, venue, 14500), 201)
    assert at_cap["cap_price_cents"] == 14500
    assert at_cap["ask_price_cents"] == 14500
    assert at_cap["status"] == ListingStatus.LISTED
    assert at_cap["superseded_listing_id"] is None

    validate_success(api.delist_resale_listing(at_cap["id"], {}, venue["seller"]))
    version_after_delist = fx.read_ticket(api, venue["ticket"]["id"])["version"]

    validate_error(_list_at(api, venue, 14501), ApiErrorId.PRICE_CAP_EXCEEDED, 422)

    # A refused create is not a mutation, so the version the client read is still current.
    assert fx.read_ticket(api, venue["ticket"]["id"])["version"] == version_after_delist
    assert fx.read_ticket(api, venue["ticket"]["id"])["lifecycle_status"] == (
        LifecycleStatus.ISSUED
    )


def test_a_relisting_one_cent_under_the_cap_supersedes_only_the_withdrawn_listing(api):
    """The refused attempt leaves no row, so the 14499 listing points at the delisted one.

    PRD: "The server records the acting patron as `seller_patron_id`, leaves `buyer_patron_id` null, and sets `superseded_listing_id` to the most recent `DELISTED` or `SUSPENDED` listing on the same ticket ordered by `created_at` descending, or null when this is the ticket's first listing."

    Design: Difficulty/boundary_precision_check/resale_ask_price_equal_to_cap_accepted_and_one_cent_over_refused
    """
    venue = _ada_with_a_paid_seat(api)

    first = validate_success(_list_at(api, venue, 14500), 201)
    validate_success(api.delist_resale_listing(first["id"], {}, venue["seller"]))
    validate_error(_list_at(api, venue, 14501), ApiErrorId.PRICE_CAP_EXCEEDED, 422)

    under_cap = validate_success(_list_at(api, venue, 14499), 201)
    assert under_cap["cap_price_cents"] == 14500
    assert under_cap["status"] == ListingStatus.LISTED
    assert under_cap["superseded_listing_id"] == first["id"]

    assert validate_success(
        api.get_resale_listing(first["id"], SECURITY_INVESTIGATOR)
    )["status"] == ListingStatus.DELISTED

    _, meta = validate_paginated(
        api.list_resale_listings(
            SECURITY_INVESTIGATOR, params={"ticket_id": venue["ticket"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert fx.read_ticket(api, venue["ticket"]["id"])["lifecycle_status"] == (
        LifecycleStatus.LISTED
    )


def _exited_at_eighteen_ten_thirty(api):
    """Ada walked in at 18:10:00 and out again thirty seconds later."""
    venue = fx.scan_ready_venue(api, device_fingerprint="DEV-ADA")
    ticket_id = venue["ticket"]["id"]
    fx.admit_ticket(api, venue["session"]["id"], ticket_id, "DEV-ADA", "S1-ONLINE-001")
    fx.set_clock(api, C.T_18_10_30)
    exit_event = fx.exit_ticket(
        api, venue["session"]["id"], ticket_id, "DEV-ADA", "S1-ONLINE-002"
    )
    assert exit_event["result"] == ScanResult.EXIT_RECORDED
    assert fx.read_ticket(api, ticket_id)["last_exited_at"] == C.T_18_10_30
    return venue


def test_a_re_entry_at_exactly_the_lockout_upper_bound_is_refused(api):
    """Two minutes to the second is still inside the closed lockout interval.

    PRD: "The lockout is a **closed** interval anchored on the ticket's own `last_exited_at` and running 120 seconds — two minutes — beyond it, with both ends inclusive; an entry scan is permitted only when the logical clock is strictly later than `last_exited_at` plus 120 seconds."

    Design: Difficulty/boundary_precision_check/reentry_lockout_upper_bound_is_inclusive_and_next_second_admits
    """
    venue = _exited_at_eighteen_ten_thirty(api)
    ticket_id = venue["ticket"]["id"]

    fx.set_clock(api, C.T_18_12_30)
    barcode = fx.get_barcode(api, ticket_id)
    assert barcode["barcode_epoch_index"] == C.EPOCH_AT_18_12_30

    validate_error(
        fx.denied_scan_response(
            api, venue["session"]["id"], barcode["current_barcode"], "DEV-ADA", "S1-ONLINE-003"
        ),
        ApiErrorId.REENTRY_LOCKOUT,
        409,
    )

    # A lockout refusal is not an accusation: the ticket keeps the status it had.
    assert fx.read_ticket(api, ticket_id)["admission_status"] == AdmissionStatus.EXITED
    assert fx.list_incidents(api, ticket_id=ticket_id) == []
    patron = fx.read_patron(api, venue["holder"]["id"])
    assert patron["strike_count"] == 0
    assert patron["fraud_risk_score"] == 0


def test_the_very_next_second_admits_the_same_barcode_again(api):
    """One second past the bound the identical epoch-25 barcode is admitted.

    PRD: "An attempt at exactly the upper bound is rejected with `ERR_REENTRY_LOCKOUT`, and the first accepted instant is one second later."
    PRD: "A re-entry that clears the lockout moves the ticket `EXITED → INSIDE` and produces exactly the same counter movements as a first admission."

    Design: Difficulty/boundary_precision_check/reentry_lockout_upper_bound_is_inclusive_and_next_second_admits
    """
    venue = _exited_at_eighteen_ten_thirty(api)
    ticket_id = venue["ticket"]["id"]
    session_id = venue["session"]["id"]

    fx.set_clock(api, C.T_18_12_30)
    barcode = fx.get_barcode(api, ticket_id)["current_barcode"]
    validate_error(
        fx.denied_scan_response(api, session_id, barcode, "DEV-ADA", "S1-ONLINE-003"),
        ApiErrorId.REENTRY_LOCKOUT,
        409,
    )

    fx.set_clock(api, C.T_18_12_31)
    readmitted = fx.live_scan(api, session_id, barcode, "DEV-ADA", "S1-ONLINE-004")
    assert readmitted["result"] == ScanResult.ADMITTED

    ticket = fx.read_ticket(api, ticket_id)
    assert ticket["admission_status"] == AdmissionStatus.INSIDE
    assert ticket["last_admitted_at"] == C.T_18_12_31
    assert ticket["admitted_scan_count"] == 2

    event = fx.read_event(api, venue["event"]["id"])
    assert event["live_occupancy"] == 1
    assert event["peak_live_occupancy"] == 1

    results = [row["result"] for row in fx.list_scan_events(api, scan_session_id=session_id)]
    assert len(results) == 4
    assert set(results) == {
        ScanResult.ADMITTED,
        ScanResult.EXIT_RECORDED,
        ScanResult.DENIED_REENTRY_LOCKOUT,
    }
