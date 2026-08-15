"""Event, bid, and requirement-checklist workflow tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId, is_valid_uuid,
    create_event_payload, create_bid_payload, create_requirement_payload,
    create_venue_payload, create_volunteer_payload, create_shift_payload,
    create_event, create_bid, create_verified_bid, award_event_bid, get_event,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
CVB = TEST_USERS["cvb_headers"]
ANY = TEST_USERS["any_headers"]


# ===========================================================================
# Corner / entities
# ===========================================================================

def test_event_creation_defaults_and_system_fields(api):
    """PRD §2.5: "A new event begins in `BIDDING` with `version` 1."
    PRD §2.4: "Its startup default is exactly 2026-08-01T00:00:00Z, and it never
    falls back to real time."

    Design: Corner/entities/event_creation_defaults_and_system_fields
    """
    resp = api.create_event(create_event_payload(), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["posture"] == "BIDDING"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert data["created_at"] == "2026-08-01T00:00:00.000Z"
    assert data["registered_team_count"] == 0
    assert data["finalized_match_count"] == 0


def test_event_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "Malformed request bodies, missing required fields, invalid enum
    members, out-of-range numbers, and inverted date ranges are rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/event_missing_required_field_returns_invalid_request
    """
    payload = create_event_payload()
    del payload["host_city"]
    resp = api.create_event(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    # Nothing was created.
    data, meta = validate_paginated(api.list_events(ANY))
    assert meta["total_count"] == 0


def test_event_get_missing_returns_not_found(api):
    """PRD §2.9: "Existence checking on nested paths proceeds strictly left to
    right: the event first, then the child, then the grandchild. A request
    addressing a field under a non-existent venue, or a booking under a
    non-existent block, is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not resolve, before later path segments or body rules
    are considered."

    Design: Corner/entities/event_get_missing_returns_not_found
    """
    resp = api.get_event(NON_EXISTENT_UUID, ANY)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.json()["response_type"] == "error"


def test_venue_create_under_missing_event_not_found(api):
    """PRD §2.9: "Existence checking on nested paths proceeds strictly left to
    right: the event first, then the child, then the grandchild. A request
    addressing a field under a non-existent venue, or a booking under a
    non-existent block, is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not resolve, before later path segments or body rules
    are considered."

    Design: Corner/entities/venue_create_under_missing_event_not_found
    """
    resp = api.create_venue(NON_EXISTENT_UUID, create_venue_payload(), ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_official_defaults_applied(api):
    """PRD §3.7: "Officials are registered per event by a `CommissionAdmin` with
    a `name`, a `certification_level` of `TRAINEE`, `REGIONAL`, or `NATIONAL`,
    an optional `needs_housing` flag defaulting to false that marks the official
    as requiring an officials-housing room booking, and an optional
    `game_limit_per_day` — the maximum number of accepted-or-worked games per
    calendar day — defaulting to 4 and at least 1. An official begins
    `REGISTERED`..."

    Design: Corner/entities/official_defaults_applied
    """
    ev = create_event()
    resp = api.create_official(
        ev["id"], {"name": "Ora One", "certification_level": "REGIONAL"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["needs_housing"] is False
    assert data["game_limit_per_day"] == 4
    assert data["status"] == "REGISTERED"
    assert data["assigned_game_count"] == 0


# ===========================================================================
# Corner / state_machines (bid lifecycle)
# ===========================================================================

def test_bid_initial_state_and_cycle(api):
    """PRD §3.1: "A bid begins in `DRAFT`."
    PRD §3.1: "Each bid belongs to one event through its `event_id` and receives
    a `cycle_number`: one-based, incrementing per new bid, so a renewal bid for
    the next hosting cycle continues the sequence rather than restarting it."
    PRD §3.1: "in every case the event's `active_bid_id` is set to the new bid,
    and the event's `version` increments once for the whole operation."

    Design: Corner/state_machines/bid_initial_state_and_cycle
    """
    ev = create_event()
    assert ev["version"] == 1
    resp = api.create_bid(ev["id"], create_bid_payload(ev["version"], notes="initial"), ADMIN)
    bid = validate_success(resp, expected_status=201)
    assert bid["status"] == "DRAFT"
    assert bid["cycle_number"] == 1
    assert bid["revision_count"] == 0
    ev_after = get_event(ev["id"])
    assert ev_after["active_bid_id"] == bid["id"]
    assert ev_after["version"] == 2


def test_bid_terminal_lockdown_decide_rejected(api):
    """PRD §2.10: "Terminal states are absorbing: any further transition
    attempted on an entity already in a terminal state is rejected with
    `ERR_ALREADY_TERMINAL` (HTTP 409). The terminal states are: event
    `CANCELLED`; bid `AWARDED`, `REJECTED`, `WITHDRAWN`, `SUPERSEDED`; ..."

    Design: Corner/state_machines/bid_terminal_lockdown_decide_rejected
    """
    ev = create_event()
    bid = award_event_bid(ev["id"])
    assert bid["status"] == "AWARDED"
    resp = api.decide_bid(bid["id"], {"decision": "REJECTED"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    bid_after = get_success_data(api.get_bid(bid["id"], ANY))
    assert bid_after["status"] == "AWARDED"
    assert get_event(ev["id"])["posture"] == "AWARDED"


def test_bid_double_submit_rejected(api):
    """PRD §2.9: "Existence comes next, then the optimistic-concurrency version
    check (`ERR_STALE_VERSION`), then event-posture gating
    (`ERR_EVENT_POSTURE_FORBIDS`), then entity-state legality (`ERR_INVALID_STATE`
    or the more specific state errors such as `ERR_BID_NOT_EDITABLE`,
    `ERR_DIVISION_NOT_OPEN`, `ERR_MATCH_NOT_SCHEDULABLE`, or
    `ERR_BLOCK_NOT_CONTRACTED`)."
    PRD §3.1: "A successful submit moves the bid to `SUBMITTED` and stamps
    `submitted_at` from the logical clock."

    Design: Corner/state_machines/bid_double_submit_rejected
    """
    ev = create_event()
    bid = create_verified_bid(ev["id"])
    first = validate_success(api.submit_bid(bid["id"], ADMIN))
    assert first["status"] == "SUBMITTED"
    assert first["revision_count"] == 0
    resp = api.submit_bid(bid["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    bid_after = get_success_data(api.get_bid(bid["id"], ANY))
    assert bid_after["revision_count"] == 0


def test_bid_renewal_after_bid_lost_revives_event(api):
    """PRD §2.5: "Renewal runs the ladder backward: creating a fresh bid on a
    `BID_LOST` event revives it to `BIDDING`, and creating a renewal bid on a
    `SETTLED` event re-enters `BIDDING` for the next hosting cycle with the
    event's `active_bid_id` pointed at the new bid."
    PRD §3.1: "Each bid belongs to one event through its `event_id` and receives
    a `cycle_number`: one-based, incrementing per new bid, so a renewal bid for
    the next hosting cycle continues the sequence rather than restarting it."

    Design: Corner/state_machines/bid_renewal_after_bid_lost_revives_event
    """
    ev = create_event()
    b1 = create_verified_bid(ev["id"])
    validate_success(api.submit_bid(b1["id"], ADMIN))
    validate_success(api.review_bid(b1["id"], REVIEWER))
    validate_success(api.decide_bid(b1["id"], {"decision": "REJECTED"}, REVIEWER))
    ev_lost = get_event(ev["id"])
    assert ev_lost["posture"] == "BID_LOST"
    resp = api.create_bid(ev["id"], create_bid_payload(ev_lost["version"], notes="renewal cycle"), ADMIN)
    b2 = validate_success(resp, expected_status=201)
    assert b2["cycle_number"] == 2
    assert b2["status"] == "DRAFT"
    ev_after = get_event(ev["id"])
    assert ev_after["posture"] == "BIDDING"
    assert ev_after["active_bid_id"] == b2["id"]
    b1_after = get_success_data(api.get_bid(b1["id"], ANY))
    assert b1_after["status"] == "REJECTED"


# ===========================================================================
# Corner / errors (bid domain battery, award gate)
# ===========================================================================

def test_errors_bid_requirement_domain(api):
    """PRD §3.1: "waiving is legal only from `PENDING` (anything else draws
    `ERR_REQUIREMENT_NOT_REVIEWABLE`), only while the parent bid is `DRAFT` or
    `REVISION_REQUESTED` (`ERR_BID_NOT_EDITABLE`), and never on a mandatory
    requirement (`ERR_REQUIREMENT_NOT_WAIVABLE`, HTTP 409)."
    PRD §3.1: "a verify action with `decision` `VERIFIED` or `RETURNED` (with
    optional `review_notes` recorded on the requirement) is legal only on an
    `EVIDENCE_SUBMITTED` requirement — verifying anything else is rejected with
    `ERR_REQUIREMENT_NOT_REVIEWABLE` (HTTP 409)"
    PRD §3.1: "Creating a new bid supersedes an existing `DRAFT` bid — the old
    draft becomes `SUPERSEDED` and its `version` increments — but an active bid
    in `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUESTED` blocks creation
    outright with `ERR_BID_ALREADY_ACTIVE` (HTTP 409)."

    Design: Corner/errors/errors_bid_requirement_domain
    """
    ev = create_event()
    bid = create_bid(ev["id"])
    rq1 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="INSURANCE_CERT", is_mandatory=True,
                                              weight_points=100), ADMIN))
    rq2 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="MEDICAL_PLAN", is_mandatory=True,
                                              weight_points=20), ADMIN))
    get_success_data(api.submit_evidence(rq1["id"], {"evidence_uri": "s3://ev/ins.pdf"}, ADMIN))
    get_success_data(api.verify_requirement(rq1["id"], {"decision": "VERIFIED"}, REVIEWER))
    # e1: waive on a mandatory requirement.
    resp = api.waive_requirement(rq2["id"], {"waiver_reason": "not needed"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_WAIVABLE)
    # e2: verify on a PENDING requirement (never evidenced).
    resp = api.verify_requirement(rq2["id"], {"decision": "VERIFIED"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_REVIEWABLE)
    # Drive R2 to VERIFIED, then submit; review_score == 120.
    get_success_data(api.submit_evidence(rq2["id"], {"evidence_uri": "s3://ev/med.pdf"}, ADMIN))
    get_success_data(api.verify_requirement(rq2["id"], {"decision": "VERIFIED"}, REVIEWER))
    submitted = validate_success(api.submit_bid(bid["id"], ADMIN))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["review_score"] == 120
    # e3: PATCH on a SUBMITTED bid.
    resp = api.patch_bid(bid["id"], {"expected_bid_version": submitted["version"],
                                     "notes": "late edit"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BID_NOT_EDITABLE)
    # e4: a second bid create while SUBMITTED.
    ev_now = get_event(ev["id"])
    resp = api.create_bid(ev["id"], create_bid_payload(ev_now["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_BID_ALREADY_ACTIVE)


def test_bid_award_score_gate_rejected(api):
    """PRD §3.1: "Awarding requires a `review_score` of at least 80 points — the
    boundary is inclusive — and a score below that threshold is rejected with
    `ERR_BID_SCORE_BELOW_THRESHOLD` (HTTP 409)."
    PRD §2.5: "When a bid is rejected, the event moves `BIDDING` → `BID_LOST`."

    Design: Corner/errors/bid_award_score_gate_rejected
    """
    ev = create_event()
    bid = create_bid(ev["id"])
    rq1 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="INSURANCE_CERT", is_mandatory=True,
                                              weight_points=30), ADMIN))
    rq2 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="LEGACY_PLAN", is_mandatory=False,
                                              weight_points=20), ADMIN))
    get_success_data(api.submit_evidence(rq1["id"], {"evidence_uri": "s3://ev/ins.pdf"}, ADMIN))
    get_success_data(api.verify_requirement(rq1["id"], {"decision": "VERIFIED"}, REVIEWER))
    get_success_data(api.waive_requirement(rq2["id"], {"waiver_reason": "covered by city program"}, REVIEWER))
    submitted = validate_success(api.submit_bid(bid["id"], ADMIN))
    assert submitted["review_score"] == 40  # 30 VERIFIED + floor(20/2) WAIVED
    validate_success(api.review_bid(bid["id"], REVIEWER))
    # AWARDED is gated at 80; score 40 fails.
    resp = api.decide_bid(bid["id"], {"decision": "AWARDED"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_BID_SCORE_BELOW_THRESHOLD)
    # The bid stays UNDER_REVIEW; REJECTED then succeeds.
    assert get_success_data(api.get_bid(bid["id"], ANY))["status"] == "UNDER_REVIEW"
    rejected = validate_success(api.decide_bid(bid["id"], {"decision": "REJECTED"}, REVIEWER))
    assert rejected["status"] == "REJECTED"
    assert get_event(ev["id"])["posture"] == "BID_LOST"


# ===========================================================================
# Corner / validations (auth, priority, SoD)
# ===========================================================================

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "Authentication comes first: missing or unknown identity surfaces
    as `ERR_UNAUTHENTICATED` before anything else is examined."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api._request("POST", "/api/v1/events", create_event_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_teamrep_cannot_create_venue_even_when_event_missing(api):
    """PRD §2.9: "Authorization and entity-backed ownership follow, surfacing
    `ERR_FORBIDDEN`. Existence comes next..."
    PRD §2.1: "A request whose role is not in the endpoint's authorized set, or
    that violates an entity-backed ownership scope, is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/teamrep_cannot_create_venue_even_when_event_missing
    """
    headers = {"X-User-ID": "00000000-0000-0000-0000-000000000001", "X-User-Role": "TeamRep"}
    resp = api.create_venue(NON_EXISTENT_UUID, create_venue_payload(), headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_reviewer_cannot_verify_own_submitted_evidence(api):
    """PRD §2.11: "A `SanctioningReviewer` may not verify requirement evidence
    they submitted themselves: the reviewer's `X-User-ID` must differ from the
    requirement's `evidence_submitted_by_user_id`."

    Design: Corner/validations/reviewer_cannot_verify_own_submitted_evidence
    """
    ev = create_event()
    bid = create_bid(ev["id"])
    rq1 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="INSURANCE_CERT", is_mandatory=True,
                                              weight_points=100), ADMIN))
    # Evidence submitted under operator id "shared-1".
    submitter = {"X-User-ID": "shared-1", "X-User-Role": "CommissionAdmin"}
    get_success_data(api.submit_evidence(rq1["id"], {"evidence_uri": "s3://ev/ins.pdf"}, submitter))
    # The same operator id tries to verify as a reviewer.
    same_person = {"X-User-ID": "shared-1", "X-User-Role": "SanctioningReviewer"}
    resp = api.verify_requirement(rq1["id"], {"decision": "VERIFIED"}, same_person)
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    req_after = get_success_data(api.get_requirement(rq1["id"], ANY))
    assert req_after["status"] == "EVIDENCE_SUBMITTED"


# ===========================================================================
# Corner / rbac
# ===========================================================================

def test_reviewer_cannot_create_event(api):
    """PRD §2.1: "A request whose role is not in the endpoint's authorized set,
    or that violates an entity-backed ownership scope, is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: `POST /api/v1/events` is authorized for CommissionAdmin only.

    Design: Corner/rbac/reviewer_cannot_create_event
    """
    resp = api.create_event(create_event_payload(), REVIEWER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_cvbauditor_cannot_review_bid(api):
    """PRD §2.1: "A request whose role is not in the endpoint's authorized set,
    or that violates an entity-backed ownership scope, is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: `POST /api/v1/bids/{id}/review` is authorized for
    SanctioningReviewer only.

    Design: Corner/rbac/cvbauditor_cannot_review_bid
    """
    ev = create_event()
    bid = create_verified_bid(ev["id"])
    validate_success(api.submit_bid(bid["id"], ADMIN))
    resp = api.review_bid(bid["id"], CVB)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_success_data(api.get_bid(bid["id"], ANY))["status"] == "SUBMITTED"


def test_volunteer_cannot_confirm_signup(api):
    """PRD §3.8: "Confirmation moves `SIGNED_UP` → `CONFIRMED`, is performed by
    a `CommissionAdmin`, requires the shift to be `OPEN` or `FILLED` (otherwise
    `ERR_SHIFT_NOT_OPEN`) with `confirmed_count` still below `capacity`
    (otherwise `ERR_SHIFT_FULL`), and increments `confirmed_count` by one — which
    may bubble the shift to `FILLED`."

    Design: Corner/rbac/volunteer_cannot_confirm_signup
    """
    from test_helpers import create_active_volunteer, make_volunteer_headers
    ev = create_event()
    vol = create_active_volunteer(ev["id"])
    shift = get_success_data(api.create_shift(
        ev["id"], create_shift_payload(role_needed="PARKING",
                                       starts_at="2026-10-10T08:00:00Z",
                                       ends_at="2026-10-10T10:00:00Z", capacity=2), ADMIN))
    signup = get_success_data(api.create_signup(
        shift["id"], {"volunteer_id": vol["id"]}, make_volunteer_headers(vol["id"])))
    resp = api.confirm_signup(signup["id"], make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_success_data(api.get_signup(signup["id"], ANY))["status"] == "SIGNED_UP"


def test_hotelmanager_cannot_confirm_other_block_booking(api):
    """PRD §2.1: "When `X-User-Role` is `HotelManager`, `X-User-ID` is the `id`
    of the HotelBlock the manager operates; ownership checks compare the path's
    block or a booking's `hotel_block_id` to `X-User-ID`."

    Design: Corner/rbac/hotelmanager_cannot_confirm_other_block_booking
    """
    from test_helpers import create_hotel_block, create_booking_payload, make_hotel_manager_headers
    ev = create_event()
    block_a = create_hotel_block(ev["id"], hotel_name="Alpha Inn", contracted_rooms_per_night=10,
                                 room_rate_cents=12000)
    block_b = create_hotel_block(ev["id"], hotel_name="Beta Inn", contracted_rooms_per_night=10,
                                 room_rate_cents=12000)
    booking = get_success_data(api.create_booking(
        block_b["id"], create_booking_payload(rooms_count=1, check_in_date="2026-10-08",
                                              check_out_date="2026-10-10"), ADMIN))
    # A HotelManager operating block A cannot confirm a booking on block B.
    resp = api.transition_booking(booking["id"], {"action": "CONFIRM"},
                                  make_hotel_manager_headers(block_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_success_data(api.get_booking(booking["id"], ANY))["status"] == "RESERVED"


def test_venue_manager_manages_own_venue(api):
    """PRD §2.1: "When `X-User-Role` is `VenueManager`, `X-User-ID` is the `id`
    of the Venue the manager operates; ownership checks on a field compare the
    field's `venue_id` to `X-User-ID`."
    PRD §3.2: "A `CommissionAdmin`, or the `VenueManager` of that venue, creates
    a field on a contracted venue with a `name`, a `surface_type` of `TURF`,
    `GRASS`, `COURT`, or `INDOOR`, a `has_lights` flag, and a `slot_minutes`
    match-slot length between 30 and 180 minutes inclusive."

    Design: Corner/rbac/venue_manager_manages_own_venue
    """
    from test_helpers import create_venue_payload, make_venue_manager_headers
    ev = create_event()
    venue = get_success_data(api.create_venue(ev["id"], create_venue_payload(), ADMIN))
    validate_success(api.contract_venue(venue["id"], {"contract_uri": "s3://contracts/v1.pdf"}, ADMIN))
    mgr = make_venue_manager_headers(venue["id"])
    field_resp = api.create_field(venue["id"], {
        "name": "Field 9", "surface_type": "TURF", "has_lights": False, "slot_minutes": 60,
    }, mgr)
    field = validate_success(field_resp, expected_status=201)
    assert field["status"] == "AVAILABLE"
    blacked = validate_success(api.blackout_field(field["id"], {
        "blackout_start": "2026-10-10T00:00:00Z",
        "blackout_end": "2026-10-10T12:00:00Z",
        "reason": "turf repair",
    }, mgr))
    assert blacked["status"] == "BLACKED_OUT"
    assert blacked["blackout_start"] is not None and blacked["blackout_end"] is not None
