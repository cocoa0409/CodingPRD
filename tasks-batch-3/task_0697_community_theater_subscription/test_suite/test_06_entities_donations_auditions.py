"""Entity creation/defaults, donations & seat naming, auditions & casting,
exchange deny cycle, and RBAC corner cases.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_patron_headers,
    create_season_payload, create_seat_payload, create_donation_payload,
    create_audition_payload, create_exchange_payload,
)
import test_helpers as th

ADMIN = TEST_USERS["season_admin_headers"]
AGENT = TEST_USERS["box_office_agent_headers"]
DIRECTOR = TEST_USERS["artistic_director_headers"]


# ==========================================================================
# Corner/entities/create_season_returns_201_with_defaults
# ==========================================================================
def test_create_season_defaults(api):
    """PRD §3.1: "A new season starts in `PLANNING`".
    PRD §3.1: "optionally a `loyalty_renewal_discount_pct` — the fractional
    discount granted to a renewing subscriber, which defaults to 0.10".
    PRD §2.4: "an integer `version` that begins at the resource's creation".

    Design: Corner/entities/create_season_returns_201_with_defaults
    """
    th.set_clock("2026-04-01T00:00:00Z")
    resp = api.create_season(create_season_payload(name="Default Season",
                                                   base_subscription_fee_cents=20000), ADMIN)
    data = validate_success(resp, 201)
    assert data["status"] == "PLANNING"
    assert data["loyalty_renewal_discount_pct"] == 0.10, (
        f"default discount must be 0.10, got {data['loyalty_renewal_discount_pct']}")
    assert data["version"] == 1


# ==========================================================================
# Corner/entities/create_season_missing_required_field_rejected
# ==========================================================================
def test_create_season_missing_required_field_rejected(api):
    """PRD §3.1: "supplying its `name`, the `renewal_window_opens_at` and
    `renewal_window_closes_at` instants, the `base_subscription_fee_cents`".
    PRD §2.10: "A request body that omits a required field or supplies a wrong type
    or out-of-range value is rejected with `ERR_VALIDATION`."

    Omitting base_subscription_fee_cents is rejected with ERR_VALIDATION.

    Design: Corner/entities/create_season_missing_required_field_rejected
    """
    resp = api.create_season({
        "name": "Bad Season",
        "renewal_window_opens_at": "2026-05-01T00:00:00Z",
        "renewal_window_closes_at": "2026-05-15T00:00:00Z",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ==========================================================================
# Corner/entities/get_performance_nonexistent_returns_not_found
# ==========================================================================
def test_get_nonexistent_performance_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve to an existing
    resource determines the rejection, each with its own not-found code
    (`ERR_SEASON_NOT_FOUND`, `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_PERFORMANCE_NOT_FOUND`, ...)".

    GET /performances/{id} with a non-existent UUID returns ERR_PERFORMANCE_NOT_FOUND.

    Design: Corner/entities/get_performance_nonexistent_returns_not_found
    """
    resp = api.get_performance(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_NOT_FOUND.value)


# ==========================================================================
# Corner/entities/venue_total_seat_count_computed_on_seat_create
# ==========================================================================
def test_venue_total_seat_count_computed(api):
    """PRD §3.1: "A `SeasonAdmin` creates a `Venue` with a `name`; its
    `total_seat_count` is derived and starts at zero."
    PRD §3.1: "Creating a seat increments the bound venue's `total_seat_count`."

    After two seats are created the venue reads total_seat_count == 2.

    Design: Corner/entities/venue_total_seat_count_computed_on_seat_create
    """
    venue = th.create_venue(name="Count Hall")
    th.create_seat(venue["id"], row_label="A", seat_number=1, price_tier="STANDARD")
    th.create_seat(venue["id"], row_label="A", seat_number=2, price_tier="VALUE")
    data = get_success_data(api.get_venue(venue["id"], ADMIN))
    assert data["total_seat_count"] == 2, f"expected 2, got {data['total_seat_count']}"


# ==========================================================================
# Corner/entities/seat_naming_status_defaults_unnamed
# ==========================================================================
def test_seat_naming_status_defaults_unnamed(api):
    """PRD §3.1: "A seat begins with `naming_status` of `UNNAMED` and a null
    `named_plaque_text`; both change only when a seat-naming donation is fulfilled".

    Design: Corner/entities/seat_naming_status_defaults_unnamed
    """
    venue = th.create_venue(name="Naming Hall")
    resp = api.create_seat(create_seat_payload(venue["id"], section="ORCH", row_label="B",
                                               seat_number=1, price_tier="PREMIUM"), ADMIN)
    data = validate_success(resp, 201)
    assert data["naming_status"] == "UNNAMED"


# ==========================================================================
# Corner/validations/seat_already_named_rejected
# ==========================================================================
def test_seat_already_named_rejected(api):
    """PRD §3.6: "when the donation names a seat, fulfillment requires that seat to
    be `UNNAMED` (otherwise `ERR_SEAT_ALREADY_NAMED`), and on success it sets the
    seat's `naming_status` to `NAMED` and copies the donation's `plaque_text` into
    the seat's `named_plaque_text`."

    A second seat-naming donation against an already-NAMED seat is rejected with
    ERR_SEAT_ALREADY_NAMED; the original plaque text is preserved.

    Design: Corner/validations/seat_already_named_rejected
    """
    th.set_clock("2026-06-10T00:00:00Z")
    venue = th.create_venue(name="NameHall")
    seat = th.create_seat(venue["id"], row_label="X", seat_number=1, price_tier="PREMIUM")
    patron = th.create_patron(email="namer@example.com")
    don1 = get_success_data(api.create_donation(
        create_donation_payload(patron["id"], 50000, seat_id=seat["id"], plaque_text="In memory of A"), AGENT))
    get_success_data(api.fulfill_donation(don1["id"], AGENT))
    don2 = get_success_data(api.create_donation(
        create_donation_payload(patron["id"], 60000, seat_id=seat["id"], plaque_text="In memory of B"), AGENT))
    validate_error(api.fulfill_donation(don2["id"], AGENT), ApiErrorId.ERR_SEAT_ALREADY_NAMED.value)
    seat_after = get_success_data(api.get_seat(seat["id"], ADMIN))
    assert seat_after["naming_status"] == "NAMED"
    assert seat_after["named_plaque_text"] == "In memory of A"


# ==========================================================================
# Corner/state_machines/audition_decline_then_cast_terminal_lockdown
# ==========================================================================
def test_cast_after_decline_rejected(api):
    """PRD §3.9: "From `SCHEDULED`, `AUDITIONED`, or `CALLBACK`, the director may
    instead decline the applicant, moving the audition to the terminal `DECLINED`
    state."
    PRD §3.9: "Casting may be performed from either `AUDITIONED` or `CALLBACK`,
    advancing the audition to the terminal `CAST` state".

    Once DECLINED (terminal), a cast attempt is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/audition_decline_then_cast_terminal_lockdown
    """
    season = th.create_season()
    production = get_success_data(api.create_production(
        th.create_production_payload(season["id"], title="Cast Show"), DIRECTOR))
    aud = get_success_data(api.create_audition(
        create_audition_payload(production["id"], "Alex", "Lead"), DIRECTOR))
    get_success_data(api.decline_audition(aud["id"], DIRECTOR))
    validate_error(api.cast_audition(aud["id"], {"cast_role": "Lead"}, DIRECTOR),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Corner/validations/audition_cast_duplicate_role_rejected
# ==========================================================================
def test_cast_duplicate_role_rejected(api):
    """PRD §3.9: "it is rejected with `ERR_ROLE_ALREADY_CAST` if any existing
    `CAST` audition on the same production already holds that same `cast_role`."

    Casting a second performer into a cast_role already held by a CAST audition on
    the same production is rejected with ERR_ROLE_ALREADY_CAST.

    Design: Corner/validations/audition_cast_duplicate_role_rejected
    """
    season = th.create_season()
    production = get_success_data(api.create_production(
        th.create_production_payload(season["id"], title="Dup Cast"), DIRECTOR))
    aud1 = get_success_data(api.create_audition(
        create_audition_payload(production["id"], "A1", "Lead"), DIRECTOR))
    get_success_data(api.record_audition(aud1["id"], DIRECTOR))
    get_success_data(api.cast_audition(aud1["id"], {"cast_role": "Lead"}, DIRECTOR))
    aud2 = get_success_data(api.create_audition(
        create_audition_payload(production["id"], "A2", "Lead"), DIRECTOR))
    get_success_data(api.record_audition(aud2["id"], DIRECTOR))
    validate_error(api.cast_audition(aud2["id"], {"cast_role": "Lead"}, DIRECTOR),
                   ApiErrorId.ERR_ROLE_ALREADY_CAST.value)


# ==========================================================================
# Corner/state_machines/exchange_deny_then_request_again_cycle
# ==========================================================================
def test_exchange_deny_then_new_request_cycle(api):
    """PRD §3.7: "A `BoxOfficeAgent` may deny an exchange, moving it from
    `REQUESTED` to the terminal `DENIED` state and leaving the original ticket
    untouched, after which the holder may submit a fresh exchange — request and deny
    form a deliberate cycle across attempts."

    A denied exchange is terminal, but a second exchange against the same ticket is
    a fresh REQUESTED.

    Design: Corner/state_machines/exchange_deny_then_request_again_cycle
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "R", "seat_number": 1},
               {"price_tier": "STANDARD", "row_label": "R", "seat_number": 2}])
    patron = th.create_patron(email="exchcycle@example.com")
    ph = make_patron_headers(patron["id"])
    seat1, seat2 = ctx["seats"]
    ticket = th.hold_single_ticket(ctx["performance"]["id"], seat1["id"], patron["id"],
                                   ctx["performance_version"], headers=ph)
    get_success_data(api.pay_ticket(ticket["id"], ph))
    exch1 = get_success_data(api.create_exchange(
        create_exchange_payload(ticket["id"], ctx["performance"]["id"], seat2["id"], "PAID_EXCHANGE"), ph))
    get_success_data(api.deny_exchange(exch1["id"], AGENT))
    exch2 = get_success_data(api.create_exchange(
        create_exchange_payload(ticket["id"], ctx["performance"]["id"], seat2["id"], "PAID_EXCHANGE"), ph))
    exch1_after = get_success_data(api.get_exchange(exch1["id"], ADMIN))
    assert exch1_after["status"] == "DENIED"
    assert exch2["status"] == "REQUESTED"


# ==========================================================================
# Corner/rbac/patron_cannot_settle_performance
# ==========================================================================
def test_patron_cannot_settle_performance(api):
    """PRD §2.1: "A `BoxOfficeAgent` handles day-to-day commerce: opening,
    suspending, and settling performance sales".
    PRD §2.1: "When a syntactically valid role is not permitted to perform the
    requested operation ... the request is rejected with `ERR_UNAUTHORIZED`."

    A Patron calling settle (a BoxOfficeAgent-exclusive op) is denied with
    ERR_UNAUTHORIZED.

    Design: Corner/rbac/patron_cannot_settle_performance
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "AC"}])
    patron = th.create_patron(email="rbac@example.com")
    validate_error(api.settle_performance(ctx["performance"]["id"], make_patron_headers(patron["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


# ==========================================================================
# Corner/rbac/missing_user_context_header_rejected
# ==========================================================================
def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which declares the capacity in which they are acting. If either header is
    missing or malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api.list_seasons({})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
