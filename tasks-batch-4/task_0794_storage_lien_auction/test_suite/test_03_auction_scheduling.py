"""Scheduling and opening auctions: maturity gate, window/spacing rules, precedence."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_platform_admin_headers, make_facility_operator_headers,
    create_facility, create_tenant, create_unit, create_lien_notice, set_clock,
    setup_matured_unit, setup_scheduled_auction, setup_live_auction,
    create_auction_payload,
    CLOCK_MATURE,
)

ADMIN = make_platform_admin_headers()


def _mature_two_units_same_facility(api):
    """Two LIEN_MATURED units under one facility; clock left at 2026-03-20."""
    facility = create_facility(api)
    fac = facility["id"]
    fac_hdr = make_facility_operator_headers(fac)
    tenant = create_tenant(api, fac)
    u1 = create_unit(api, fac, tenant["id"], unit_number="U1")["id"]
    u2 = create_unit(api, fac, tenant["id"], unit_number="U2")["id"]
    n1 = create_lien_notice(api, u1, fac)["id"]
    n2 = create_lien_notice(api, u2, fac)["id"]
    set_clock(api, CLOCK_MATURE)
    validate_success(api.mature_lien_notice(n1, fac_hdr))
    validate_success(api.mature_lien_notice(n2, fac_hdr))
    return fac, fac_hdr, u1, u2


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / schedule_requires_unit_matured
# ---------------------------------------------------------------------------
def test_schedule_matured_unit_creates_scheduled_auction(api):
    """PRD §3.3: "Scheduling requires the unit's `status` to be `LIEN_MATURED`;
    scheduling against any other status is rejected with `ERR_UNIT_NOT_MATURED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_unit_matured
    """
    ctx = setup_matured_unit(api)
    resp = api.create_auction(create_auction_payload(ctx["unit_id"]), ctx["fac_hdr"])
    auction = validate_success(resp, expected_status=201)
    assert auction["status"] == "SCHEDULED"


def test_scheduling_does_not_flip_unit_until_open(api):
    """PRD §3.3: "Scheduling deliberately does not move the unit: the unit stays
    `LIEN_MATURED` so that overlapping-window scheduling can still be detected and
    rejected. The unit flips only when an auction is opened."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_unit_matured
    """
    ctx = setup_scheduled_auction(api)
    unit = validate_success(api.get_unit(ctx["unit_id"], ADMIN))
    assert unit["status"] == "LIEN_MATURED"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / schedule_referential_beats_temporal
# ---------------------------------------------------------------------------
def test_schedule_rented_unit_bad_window_reports_unit_not_matured(api):
    """PRD §2.10: "For scheduling an auction, after the shared checks the order is:
    the unit must be matured (`ERR_UNIT_NOT_MATURED`), then the window itself must be
    valid (`ERR_INVALID_AUCTION_WINDOW`), then the window must not overlap another
    auction on the same unit (`ERR_AUCTION_WINDOW_CONFLICT`), then any onsite spacing
    rule must hold (`ERR_ONSITE_SLOT_CONFLICT`)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_referential_beats_temporal
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    unit = create_unit(api, facility["id"], tenant["id"])  # RENTED, never noticed
    resp = api.create_auction(
        create_auction_payload(unit["id"], start_at="2026-04-02T00:00:00Z",
                               end_at="2026-04-01T00:00:00Z"),
        make_facility_operator_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_MATURED.value)


def test_schedule_rented_unit_valid_window_reports_unit_not_matured(api):
    """PRD §3.3: "Scheduling requires the unit's `status` to be `LIEN_MATURED`;
    scheduling against any other status is rejected with `ERR_UNIT_NOT_MATURED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_referential_beats_temporal
    """
    facility = create_facility(api)
    tenant = create_tenant(api, facility["id"])
    unit = create_unit(api, facility["id"], tenant["id"])  # RENTED
    resp = api.create_auction(create_auction_payload(unit["id"]),
                              make_facility_operator_headers(facility["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_MATURED.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / onsite_facility_buffer_conflict
# ---------------------------------------------------------------------------
def test_onsite_auctions_thirty_minutes_apart_rejected(api):
    """PRD §3.3: "any two `ONSITE` auctions held at the same facility — that is, on
    units sharing the same `facility_id` — must be separated by at least 120 minutes
    measured edge to edge as a closed interval with that buffer; onsite auctions
    closer than two hours apart are rejected with `ERR_ONSITE_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/onsite_facility_buffer_conflict
    """
    fac, fac_hdr, u1, u2 = _mature_two_units_same_facility(api)
    validate_success(api.create_auction(
        create_auction_payload(u1, mode="ONSITE", start_at="2026-03-21T10:00:00Z",
                               end_at="2026-03-21T11:00:00Z"), fac_hdr), 201)
    resp = api.create_auction(
        create_auction_payload(u2, mode="ONSITE", start_at="2026-03-21T11:30:00Z",
                               end_at="2026-03-21T12:30:00Z"), fac_hdr)
    validate_error(resp, ApiErrorId.ERR_ONSITE_SLOT_CONFLICT.value)


def test_onsite_auctions_ninety_minutes_apart_rejected(api):
    """PRD §3.3: "any two `ONSITE` auctions held at the same facility — that is, on
    units sharing the same `facility_id` — must be separated by at least 120 minutes
    measured edge to edge as a closed interval with that buffer; onsite auctions
    closer than two hours apart are rejected with `ERR_ONSITE_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/onsite_facility_buffer_conflict
    """
    fac, fac_hdr, u1, u2 = _mature_two_units_same_facility(api)
    validate_success(api.create_auction(
        create_auction_payload(u1, mode="ONSITE", start_at="2026-03-21T10:00:00Z",
                               end_at="2026-03-21T11:00:00Z"), fac_hdr), 201)
    resp = api.create_auction(
        create_auction_payload(u2, mode="ONSITE", start_at="2026-03-21T12:30:00Z",
                               end_at="2026-03-21T13:30:00Z"), fac_hdr)  # 90-min gap
    validate_error(resp, ApiErrorId.ERR_ONSITE_SLOT_CONFLICT.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / unit_window_half_open_overlap
# ---------------------------------------------------------------------------
def test_overlapping_windows_same_unit_rejected(api):
    """PRD §3.3: "Because a single unit may hold several scheduled auctions at once,
    the platform forbids two auctions on the same unit whose half-open windows
    overlap, rejecting the conflict with `ERR_AUCTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/unit_window_half_open_overlap
    """
    ctx = setup_scheduled_auction(api)  # a1 spans [2026-03-21, 2026-03-22)
    resp = api.create_auction(
        create_auction_payload(ctx["unit_id"], start_at="2026-03-21T12:00:00Z",
                               end_at="2026-03-23T00:00:00Z"), ctx["fac_hdr"])
    validate_error(resp, ApiErrorId.ERR_AUCTION_WINDOW_CONFLICT.value)


def test_adjacent_half_open_windows_same_unit_allowed(api):
    """PRD §3.3: "The bidding window is half-open, covering `start_at` inclusive up
    to but not including `end_at`."
    PRD §3.3: "the platform forbids two auctions on the same unit whose half-open
    windows overlap, rejecting the conflict with `ERR_AUCTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/unit_window_half_open_overlap
    """
    ctx = setup_scheduled_auction(api)  # a1 spans [2026-03-21, 2026-03-22)
    resp = api.create_auction(
        create_auction_payload(ctx["unit_id"], start_at="2026-03-22T00:00:00Z",
                               end_at="2026-03-23T00:00:00Z"), ctx["fac_hdr"])
    auction = validate_success(resp, expected_status=201)
    assert auction["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: window validity, open timing, open idempotency
# ---------------------------------------------------------------------------
def test_invalid_auction_window_rejected(api):
    """PRD §3.3: "The window must satisfy `end_at` strictly after `start_at` and
    `start_at` at or after the logical clock now; a window that ends at or before it
    starts, or that starts in the past, is rejected with `ERR_INVALID_AUCTION_WINDOW`."

    Design: Corner/validations/invalid_auction_window_returns_422
    """
    ctx = setup_matured_unit(api)
    resp = api.create_auction(
        create_auction_payload(ctx["unit_id"], start_at="2026-04-02T00:00:00Z",
                               end_at="2026-04-01T00:00:00Z"), ctx["fac_hdr"])
    validate_error(resp, ApiErrorId.ERR_INVALID_AUCTION_WINDOW.value)


def test_open_before_start_returns_too_early(api):
    """PRD §3.3: "Opening requires the auction to be `SCHEDULED`, the unit to be
    `LIEN_MATURED`, and the logical clock now to be at or after `start_at`; opening
    before `start_at` is rejected with `ERR_OPEN_TOO_EARLY`."

    Design: Corner/validations/open_before_start_returns_too_early
    """
    ctx = setup_scheduled_auction(api)  # clock at 2026-03-20, start_at 2026-03-21
    resp = api.open_auction(ctx["auc"], ctx["fac_hdr"])
    validate_error(resp, ApiErrorId.ERR_OPEN_TOO_EARLY.value)


def test_open_already_live_auction_returns_invalid_state(api):
    """PRD §3.3: "Opening requires the auction to be `SCHEDULED`, the unit to be
    `LIEN_MATURED`, and the logical clock now to be at or after `start_at`; opening
    before `start_at` is rejected with `ERR_OPEN_TOO_EARLY`."
    PRD §2.10: "then the general state check that the target resource is in a state
    permitting the requested transition (else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/open_already_live_auction_returns_invalid_state
    """
    ctx = setup_live_auction(api)  # already LIVE
    resp = api.open_auction(ctx["auc"], ctx["fac_hdr"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
