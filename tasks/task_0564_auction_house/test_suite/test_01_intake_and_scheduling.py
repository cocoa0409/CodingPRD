"""Consignor/bidder registration, consignment intake, appraisal decisions, and
sale scheduling — including the saleroom and intake-window overlap rules.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    create_consignor_payload,
    create_bidder_payload,
    create_consignment_payload,
    create_auction_payload,
    create_lot_payload,
    make_saleroom,
    make_consignor,
    make_bidder,
    make_auction,
    make_bidder_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ─── Corner: entity creation, validation, not-found ──────────────────────

def test_register_consignor_defaults_payout_and_version(api, staff_headers):
    """PRD §3.1: "`payout_method` is one of `CHECK`, `ACH`, or `STORE_CREDIT`,
    and defaults to `CHECK` when omitted."
    PRD §2.4: "`version` starts at 1 and increments by exactly one each time the
    resource is modified — including modifications the server performs on its own
    initiative during a cascade."

    Design: Corner/entities/corner_consignor_create_returns_201
    """
    res = api.create_consignor(create_consignor_payload(display_name="Estate A"), staff_headers)
    data = validate_success(res, 201)
    assert data["payout_method"] == "CHECK"
    assert data["version"] == 1
    assert data["display_name"] == "Estate A"


def test_get_unknown_lot_returns_not_found(api, staff_headers):
    """PRD §2.7: "The first identifier that does not resolve produces the
    corresponding not-found error (HTTP 404) before any later resolution or
    business rule is attempted."

    Design: Corner/entities/corner_get_lot_nonexistent_returns_404
    """
    res = api.get_lot(NON_EXISTENT_UUID, staff_headers)
    validate_error(res, "ERR_LOT_NOT_FOUND")


def test_duplicate_paddle_rejected(api, staff_headers):
    """PRD §3.1: "registering a paddle already held by another bidder is rejected
    with `ERR_DUPLICATE_PADDLE` (HTTP 409)."

    Design: Corner/entities/corner_bidder_duplicate_paddle_returns_409
    """
    api.create_bidder(create_bidder_payload(display_name="B1", email="b1@x.com",
                                             paddle_number="P1"), staff_headers)
    res = api.create_bidder(create_bidder_payload(display_name="B2", email="b2@x.com",
                                                  paddle_number="P1"), staff_headers)
    validate_error(res, "ERR_DUPLICATE_PADDLE")


def test_consignment_missing_commission_rate_rejected(api, staff_headers):
    """PRD §2.9: "required body fields are present with correct types, valid enum
    membership, and satisfied range/positivity constraints, else `ERR_VALIDATION`".
    PRD §3.2: "A consignment records its `consignor_id`, a `commission_rate` that
    is at least 0 and strictly less than 1".

    Design: Corner/entities/corner_consignment_missing_commission_rate_returns_400
    """
    consignor = make_consignor()
    payload = create_consignment_payload(consignor["id"])
    del payload["commission_rate"]
    res = api.create_consignment(payload, staff_headers)
    validate_error(res, "ERR_VALIDATION")


def test_auction_end_before_start_rejected(api, staff_headers):
    """PRD §3.3: "a `saleroom_id` naming the venue, and a `scheduled_start` and
    `scheduled_end` where the end is strictly after the start."

    Design: Corner/entities/corner_auction_end_before_start_returns_400
    """
    saleroom = make_saleroom()
    payload = create_auction_payload(
        saleroom["id"], title="Bad",
        scheduled_start="2026-06-10T12:00:00Z", scheduled_end="2026-06-10T10:00:00Z",
    )
    res = api.create_auction(payload, staff_headers)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner: state preconditions on the intake / scheduling path ─────────

def test_decision_before_appraised_rejected(api, staff_headers):
    """PRD §3.2: "A decision is permitted only while the consignment is
    `APPRAISED`; attempting it in any other state yields
    `ERR_CONSIGNMENT_NOT_APPRAISED` (HTTP 409)."

    Design: Corner/state_machines/corner_consignment_decision_before_appraised_returns_conflict
    """
    consignor = make_consignor()
    cg = validate_success(
        api.create_consignment(create_consignment_payload(consignor["id"]), staff_headers), 201
    )
    res = api.decide_consignment(cg["id"], {"outcome": "ACCEPT"}, staff_headers)
    validate_error(res, "ERR_CONSIGNMENT_NOT_APPRAISED")


def test_lot_from_unaccepted_consignment_rejected(api, staff_headers):
    """PRD §3.3: "Cataloging requires the referenced consignment to be in
    `ACCEPTED`; otherwise the request is rejected with
    `ERR_CONSIGNMENT_NOT_ACCEPTED` (HTTP 409)."

    Design: Corner/state_machines/corner_lot_create_from_unaccepted_consignment_returns_conflict
    """
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])
    consignor = make_consignor()
    cg = validate_success(
        api.create_consignment(create_consignment_payload(consignor["id"]), staff_headers), 201
    )
    res = api.create_lot(create_lot_payload(cg["id"], auction["id"]), staff_headers)
    validate_error(res, "ERR_CONSIGNMENT_NOT_ACCEPTED")


def test_open_auction_twice_rejected(api, staff_headers):
    """PRD §3.3: "Opening requires the auction to be `SCHEDULED` and closing
    requires it to be `OPEN`; a transition attempted from the wrong state yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_auction_open_twice_invalid
    """
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])
    validate_success(api.open_auction(auction["id"], staff_headers), 200)
    res = api.open_auction(auction["id"], staff_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_bidder_cannot_appraise_consignment(api, staff_headers):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_bidder_cannot_appraise_returns_403
    """
    consignor = make_consignor()
    cg = validate_success(
        api.create_consignment(create_consignment_payload(consignor["id"]), staff_headers), 201
    )
    bidder = make_bidder()
    res = api.appraise_consignment(
        cg["id"],
        {"appraised_low_cents": 100_000, "appraised_high_cents": 200_000},
        make_bidder_headers(bidder["id"]),
    )
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Difficulty: saleroom half-open overlap ──────────────────────────────

def test_saleroom_overlapping_window_double_booked(api, staff_headers):
    """PRD §3.3: "If another auction in the same `saleroom_id` overlaps that
    half-open interval, the creation is rejected with `ERR_SALEROOM_DOUBLE_BOOKED`
    (HTTP 409); because the interval is half-open, a sale that begins exactly when
    another ends is allowed."

    Design: Difficulty/resource_temporal_overlap/ov_auction_saleroom_halfopen
    """
    saleroom = make_saleroom()
    make_auction(saleroom["id"], title="A1",
                 scheduled_start="2026-06-10T10:00:00Z",
                 scheduled_end="2026-06-10T12:00:00Z")
    res = api.create_auction(
        create_auction_payload(saleroom["id"], title="A2",
                               scheduled_start="2026-06-10T11:00:00Z",
                               scheduled_end="2026-06-10T13:00:00Z"),
        staff_headers,
    )
    validate_error(res, "ERR_SALEROOM_DOUBLE_BOOKED")


def test_saleroom_back_to_back_window_allowed(api, staff_headers):
    """PRD §3.3: "because the interval is half-open, a sale that begins exactly
    when another ends is allowed."

    Design: Difficulty/resource_temporal_overlap/ov_auction_saleroom_halfopen
    """
    saleroom = make_saleroom()
    make_auction(saleroom["id"], title="A1",
                 scheduled_start="2026-06-10T10:00:00Z",
                 scheduled_end="2026-06-10T12:00:00Z")
    res = api.create_auction(
        create_auction_payload(saleroom["id"], title="A3",
                               scheduled_start="2026-06-10T12:00:00Z",
                               scheduled_end="2026-06-10T14:00:00Z"),
        staff_headers,
    )
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED"


# ─── Difficulty: consignor intake-window buffer (closed + 60 min) ────────

def test_intake_window_within_buffer_conflict(api, staff_headers):
    """PRD §3.2: "if any other consignment for the same `consignor_id` has an
    intake window nearer than the mandatory buffer of 60 minutes
    (`INTAKE_BUFFER_MINUTES`) — measured against the closed intervals plus that
    buffer — the submission is rejected with `ERR_INTAKE_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ov_consignor_intake_buffer
    """
    consignor = make_consignor()
    validate_success(
        api.create_consignment(
            create_consignment_payload(
                consignor["id"],
                intake_window_start="2026-05-02T09:00:00Z",
                intake_window_end="2026-05-02T10:00:00Z"),
            staff_headers), 201
    )
    res = api.create_consignment(
        create_consignment_payload(
            consignor["id"],
            intake_window_start="2026-05-02T10:30:00Z",
            intake_window_end="2026-05-02T11:00:00Z"),
        staff_headers,
    )
    validate_error(res, "ERR_INTAKE_WINDOW_CONFLICT")


def test_intake_window_exactly_buffer_allowed(api, staff_headers):
    """PRD §3.2: "if any other consignment for the same `consignor_id` has an
    intake window nearer than the mandatory buffer of 60 minutes
    (`INTAKE_BUFFER_MINUTES`) — measured against the closed intervals plus that
    buffer — the submission is rejected with `ERR_INTAKE_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ov_consignor_intake_buffer
    """
    consignor = make_consignor()
    validate_success(
        api.create_consignment(
            create_consignment_payload(
                consignor["id"],
                intake_window_start="2026-05-02T09:00:00Z",
                intake_window_end="2026-05-02T10:00:00Z"),
            staff_headers), 201
    )
    res = api.create_consignment(
        create_consignment_payload(
            consignor["id"],
            intake_window_start="2026-05-02T11:00:00Z",
            intake_window_end="2026-05-02T12:00:00Z"),
        staff_headers,
    )
    data = validate_success(res, 201)
    assert data["status"] == "SUBMITTED"
