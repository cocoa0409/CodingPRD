"""Validation-priority conflicts, temporal booking overlaps, fiscal floors, RBAC, segregation
of duties, authentication, and settlement optimistic-concurrency.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, MANAGER, APPRAISER, CASHIER,
    new_client, new_project, new_crew, new_truck,
    listed_fixed_lot, listed_bid_lot, crew_booked_event,
    contracted_project, new_lot, research_and_price, patch_project,
    project_in_settling_no_lots, set_clock,
    make_client_headers, make_appraiser_headers, make_sale_manager_headers,
)


# ---- Difficulty: priority_pair / state_beats_fiscal_on_resale_below_reserve -----------------
def _sold_then_day3_lot(api):
    ctx = listed_fixed_lot(api, list_price_cents=10000, reserve_price_cents=5000,
                           sale_start="2026-06-01T00:00:00Z", sale_end="2026-06-05T00:00:00Z")
    set_clock("2026-06-02T00:00:00Z", api)  # day 1 -> price 7500 >= reserve, first sale succeeds
    validate_success(
        api.create_transaction(
            {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
            CASHIER,
        ),
        201,
    )
    set_clock("2026-06-04T00:00:00Z", api)  # day 3 -> markdown 2500 < reserve 5000
    return ctx


def test_resale_of_sold_lot_returns_state_error_not_fiscal(api):
    """PRD §3.4: "The lot must be in a sellable state: a fixed-price lot must be `LISTED` and a
    bid lot must be `BID_CLOSED` with a `winning_bid_id` present, and any other case is rejected
    with `ERR_LOT_NOT_SELLABLE`."
    PRD §2.11: state checks (item 6) are evaluated before the fiscal floor (item 10) in the
    fixed order — "the response reports the failure of highest priority".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_resale_below_reserve
    """
    ctx = _sold_then_day3_lot(api)
    resp = api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_SELLABLE.value)


def test_resale_of_sold_lot_leaves_lot_sold(api):
    """PRD §3.4: "On a successful ring-up the lot's own `final_price_cents` is stamped, the lot
    transitions to `SOLD`". A subsequent sale attempt does not change that state.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_resale_below_reserve
    """
    ctx = _sold_then_day3_lot(api)
    api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    data = validate_success(api.get_lot(ctx["lot_id"], APPRAISER))
    assert data["status"] == "SOLD"


# ---- Difficulty: priority_pair / temporal_beats_constraint_on_sale_event --------------------
def test_overlong_and_overlapping_event_returns_double_booked(api):
    """PRD §2.11: "Checks are evaluated in this fixed order: ... 8. Temporal availability — crew
    and truck booking windows are free, else `ERR_CREW_DOUBLE_BOOKED` or `ERR_TRUCK_UNAVAILABLE`
    (409). 9. Booking constraints — the sale window is not too long and a bid clears its
    minimums, else `ERR_SALE_WINDOW_TOO_LONG` or `ERR_BID_TOO_LOW` (422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_sale_event
    """
    ctx = crew_booked_event(api, start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T17:00:00Z")
    resp = api.create_sale_event(
        {"project_id": ctx["project_id"], "crew_id": ctx["crew_id"],
         "start_at": "2026-06-01T10:00:00Z", "end_at": "2026-06-07T10:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)


def test_rejected_event_does_not_book_crew(api):
    """PRD §3.3: "the crew's `booked_minutes` is recomputed as the sum of `window_minutes`
    across all of that crew's sale events currently in `SCHEDULED` or `OPEN` status." A rejected
    booking creates no event, so only the original 8-hour (480-minute) window is counted.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_sale_event
    """
    ctx = crew_booked_event(api, start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T17:00:00Z")
    api.create_sale_event(
        {"project_id": ctx["project_id"], "crew_id": ctx["crew_id"],
         "start_at": "2026-06-01T10:00:00Z", "end_at": "2026-06-07T10:00:00Z"},
        MANAGER,
    )
    crew = validate_success(api.get_crew(ctx["crew_id"], MANAGER))
    assert crew["booked_minutes"] == 480


# ---- Difficulty: resource_temporal_overlap / crew_half_open_window_overlap_rejected ---------
def test_crew_overlapping_window_rejected(api):
    """PRD §3.3: "the crew's booking is treated as the **half-open** interval from `start_at` up
    to but not including `end_at`, and if this interval overlaps any other `SCHEDULED` or `OPEN`
    sale event already booked on the same crew, the request is rejected with
    `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_window_overlap_rejected
    """
    ctx = crew_booked_event(api, start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T17:00:00Z")
    resp = api.create_sale_event(
        {"project_id": ctx["project_id"], "crew_id": ctx["crew_id"],
         "start_at": "2026-06-01T16:00:00Z", "end_at": "2026-06-01T20:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)


def test_crew_touching_endpoint_window_allowed(api):
    """PRD §3.3: "the crew's booking is treated as the **half-open** interval from `start_at` up
    to but not including `end_at`, and if this interval overlaps any other `SCHEDULED` or `OPEN`
    sale event already booked on the same crew, the request is rejected with
    `ERR_CREW_DOUBLE_BOOKED`." A new window starting exactly at the prior window's exclusive end
    does not overlap.

    Design: Difficulty/resource_temporal_overlap/crew_half_open_window_overlap_rejected
    """
    ctx = crew_booked_event(api, start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T17:00:00Z")
    resp = api.create_sale_event(
        {"project_id": ctx["project_id"], "crew_id": ctx["crew_id"],
         "start_at": "2026-06-01T17:00:00Z", "end_at": "2026-06-01T21:00:00Z"},
        MANAGER,
    )
    validate_success(resp, 201)


# ---- Difficulty: resource_temporal_overlap / truck_closed_window_buffer_overlap_rejected ----
def _project_with_booked_truck(api):
    client = new_client(api)
    project = new_project(client["id"], api)
    truck = new_truck(api)
    validate_success(
        api.create_haul_job(
            {"project_id": project["id"], "truck_id": truck["id"], "disposition_type": "DONATION",
             "start_at": "2026-06-05T09:00:00Z", "end_at": "2026-06-05T11:00:00Z"},
            MANAGER,
        ),
        201,
    )
    return project["id"], truck["id"]


def test_truck_within_buffer_rejected(api):
    """PRD §3.7: "A truck's pickup window is treated as the **closed** interval from `start_at`
    through `end_at` inclusive, and it additionally reserves a 60-minute buffer on each side for
    travel and turnaround. If the new job's window, expanded by that buffer, overlaps another
    `SCHEDULED` job on the same truck, the request is rejected with `ERR_TRUCK_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/truck_closed_window_buffer_overlap_rejected
    """
    project_id, truck_id = _project_with_booked_truck(api)
    resp = api.create_haul_job(
        {"project_id": project_id, "truck_id": truck_id, "disposition_type": "HAULAWAY",
         "start_at": "2026-06-05T11:30:00Z", "end_at": "2026-06-05T13:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_TRUCK_UNAVAILABLE.value)


def test_truck_direct_overlap_rejected(api):
    """PRD §3.7: "A truck's pickup window is treated as the **closed** interval from `start_at`
    through `end_at` inclusive ... If the new job's window, expanded by that buffer, overlaps
    another `SCHEDULED` job on the same truck, the request is rejected with
    `ERR_TRUCK_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/truck_closed_window_buffer_overlap_rejected
    """
    project_id, truck_id = _project_with_booked_truck(api)
    resp = api.create_haul_job(
        {"project_id": project_id, "truck_id": truck_id, "disposition_type": "HAULAWAY",
         "start_at": "2026-06-05T10:00:00Z", "end_at": "2026-06-05T12:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_TRUCK_UNAVAILABLE.value)


# ---- Corner: validations -------------------------------------------------------------------
def test_bid_below_reserve_rejected(api):
    """PRD §3.4: "A bid must clear two floors: its `amount_cents` must be at least the lot's
    `reserve_price_cents`, and it must be at least the current high bid plus the lot's
    `min_increment_cents`. A bid that fails either floor is rejected with `ERR_BID_TOO_LOW`."

    Design: Corner/validations/bid_below_reserve_returns_bid_too_low
    """
    ctx = listed_bid_lot(api, bid_mode="FIRST_PRICE", reserve_price_cents=10000,
                         min_increment_cents=1000, list_price_cents=20000)
    resp = api.create_bid({"lot_id": ctx["lot_id"], "amount_cents": 5000, "bidder_name": "low"}, CASHIER)
    validate_error(resp, ApiErrorId.ERR_BID_TOO_LOW.value)


def test_fixed_sale_below_reserve_rejected(api):
    """PRD §3.4: "For a fixed-price lot the markdown price must not fall below the lot's
    `reserve_price_cents`; if it would, the sale is rejected with `ERR_BELOW_RESERVE`."

    Design: Corner/validations/below_reserve_blocks_fixed_sale
    """
    ctx = listed_fixed_lot(api, list_price_cents=5000, reserve_price_cents=5000,
                           sale_start="2026-06-01T00:00:00Z", sale_end="2026-06-03T00:00:00Z")
    set_clock("2026-06-02T00:00:00Z", api)  # day 1: 25% markdown -> 3750 < reserve 5000
    resp = api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    validate_error(resp, ApiErrorId.ERR_BELOW_RESERVE.value)
    data = validate_success(api.get_lot(ctx["lot_id"], APPRAISER))
    assert data["status"] == "LISTED"


def test_sale_window_too_long_rejected(api):
    """PRD §3.3: "its length, measured from `start_at` to `end_at`, must not exceed the maximum
    sale window of 4 days, and a longer window is rejected with `ERR_SALE_WINDOW_TOO_LONG`."

    Design: Corner/validations/sale_window_too_long_returns_error
    """
    client = new_client(api)
    project = new_project(client["id"], api)
    crew = new_crew(api)
    resp = api.create_sale_event(
        {"project_id": project["id"], "crew_id": crew["id"],
         "start_at": "2026-06-01T09:00:00Z", "end_at": "2026-06-08T09:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_SALE_WINDOW_TOO_LONG.value)


# ---- Corner: rbac --------------------------------------------------------------------------
def test_appraiser_cannot_ring_transaction(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." Ringing up
    a transaction (`POST /estate/transactions`) is authorized for `Cashier` only.

    Design: Corner/rbac/appraiser_cannot_ring_transaction
    """
    ctx = listed_fixed_lot(api, list_price_cents=3000, reserve_price_cents=100)
    resp = api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        APPRAISER,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_client_cannot_sign_foreign_project(api):
    """PRD §2.1: "Concretely, the two project transitions a client may drive — countering the
    proposed terms and signing the contract — are permitted only on a project whose `client_id`
    equals the caller's `X-User-ID`. A client acting on someone else's project is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/client_cannot_patch_foreign_project
    """
    owner = new_client(api, name="Owner A")
    other = new_client(api, name="Owner B")
    project = new_project(owner["id"], api, estimated_total_value_cents=1000)
    patch_project(project["id"], {"status": "ASSESSED"}, MANAGER, api)
    patch_project(project["id"], {"status": "PROPOSED"}, MANAGER, api)
    resp = api.patch_project(project["id"], {"status": "CONTRACTED"}, make_client_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    data = validate_success(api.get_project(project["id"], MANAGER))
    assert data["status"] == "PROPOSED"


def test_segregation_of_duties_blocks_self_buyout(api):
    """PRD §2.10: "When a buyout is approved, the acting `SaleManager`'s `X-User-ID` is compared
    to the lot's `researched_by_user_id` (the `Appraiser` who ran the research step). If they
    are the same person, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_blocks_self_buyout
    """
    _, project = contracted_project(api)
    lot = new_lot(project["id"], api, title="Silverware", list_price_cents=9000,
                  reserve_price_cents=100, researcher_headers=make_appraiser_headers("U1"))
    research_and_price(lot["id"], api, list_price_cents=9000,
                       researcher_headers=make_appraiser_headers("U1"))
    resp = api.approve_buyout(lot["id"], {"buyout_price_cents": 4000}, make_sale_manager_headers("U1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    data = validate_success(api.get_lot(lot["id"], APPRAISER))
    assert data["handling_type"] == "CONSIGNMENT"


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_request_missing_auth_header_rejected
    """
    resp = api.create_client(
        {"name": "No Auth", "phone": "555-0000"}, {"Content-Type": "application/json"}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---- Corner: cross_cutting / occ_stale_project_version_rejected_on_settlement ---------------
def test_settlement_with_stale_version_rejected(api):
    """PRD §2.7: "If that value does not equal the project's current `version`, the request is
    rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), and no statement is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_rejected_on_settlement
    """
    project, version = project_in_settling_no_lots(api)
    resp = api.create_settlement(
        {"project_id": project["id"], "expected_project_version": version - 1}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)
    data = validate_success(api.get_project(project["id"], MANAGER))
    assert data["status"] == "SETTLING"
