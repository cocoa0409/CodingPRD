"""Holding an appointment: deposit computation, pricing integrity, interval and
resource-overlap checks, and chair-version optimistic concurrency.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_client_headers, make_artist_headers,
    create_artist, create_chair, create_client,
    create_flash_design, hold_appointment,
    set_clock,
)
from test_helpers import factories

MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Required-deposit calculation (PRD §3.6)
# ---------------------------------------------------------------------------
def test_required_deposit_hourly_rounds_up_to_dollar(api):
    """PRD §3.6: "in `HOURLY` mode the estimate is the `estimated_minutes`
    divided by 60 and rounded up to a whole number of hours, then multiplied by
    the `hourly_rate_cents`. The raw deposit is that estimate multiplied by the
    deposit rate of 0.20 (twenty percent). The required deposit is then this
    single raw figure rounded up to the next whole dollar".

    ceil(180/60)=3h; 3*18000=54000; ceil(54000*0.20/100)*100 = 10800.

    Design: Corner/calculations/required_deposit_hourly_round_up_to_dollar
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=180,
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T13:00:00Z",
    )
    assert appt["required_deposit_cents"] == 10800, \
        f"expected required_deposit 10800, got {appt['required_deposit_cents']}"


def test_required_deposit_piece_rounds_up_to_dollar(api):
    """PRD §3.6: "in `PIECE` mode the estimate is simply the `piece_price_cents`
    ... The raw deposit is that estimate multiplied by the deposit rate of 0.20
    (twenty percent). The required deposit is then this single raw figure rounded
    up to the next whole dollar".

    55000 * 0.20 = 11000; ceil(11000/100)*100 = 11000.

    Design: Corner/calculations/required_deposit_piece_round_up_to_dollar
    """
    artist = create_artist(hourly_rate_cents=18000)
    flash = create_flash_design(artist["id"], title="Skull", piece_price_cents=55000, estimated_minutes=120)
    chair = create_chair()
    client = create_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="PIECE", flash_design_id=flash["id"], piece_price_cents=55000,
        estimated_minutes=120, start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T12:00:00Z",
    )
    assert appt["required_deposit_cents"] == 11000, \
        f"expected required_deposit 11000, got {appt['required_deposit_cents']}"


# ---------------------------------------------------------------------------
# Pricing integrity (PRD §3.5, priority 8 -> ERR_INVALID_PRICING)
# ---------------------------------------------------------------------------
def test_book_two_sources_rejected(api):
    """PRD §3.5: "the appointment must specify exactly one of `flash_design_id`
    or `custom_request_id` ... Any of these pricing faults — wrong number of
    sources, missing required price field, or an hourly rate not divisible by 4
    — is rejected with `ERR_INVALID_PRICING`."

    Design: Corner/validations/book_appointment_two_sources_rejected
    """
    artist = create_artist(hourly_rate_cents=18000)
    flash = create_flash_design(artist["id"], title="Lion", piece_price_cents=50000, estimated_minutes=120)
    chair = create_chair()
    client = create_client()
    cid = client["id"]
    # An APPROVED custom request to the same artist (both sources will be supplied).
    request = get_success_data(
        api.create_custom_request(
            factories.create_custom_request_payload(artist["id"], cid, brief="Eagle"),
            make_client_headers(cid),
        )
    )
    get_success_data(
        api.quote_custom_request(
            request["id"], factories.quote_payload(quoted_price_cents=60000, estimated_minutes=180),
            make_artist_headers(artist["id"]),
        )
    )
    get_success_data(api.approve_custom_request(request["id"], make_client_headers(cid)))
    resp = api.create_appointment(
        {
            "artist_id": artist["id"], "client_id": cid, "chair_id": chair["id"],
            "expected_chair_version": chair["version"], "pricing_mode": "PIECE",
            "flash_design_id": flash["id"], "custom_request_id": request["id"],
            "piece_price_cents": 50000, "estimated_minutes": 120,
            "start_at": "2026-07-01T10:00:00Z", "end_at": "2026-07-01T12:00:00Z",
        },
        make_client_headers(cid),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PRICING.value, expected_status=422)


def test_book_hourly_rate_not_divisible_by_four_rejected(api):
    """PRD §3.5: "an `HOURLY`-mode session requires `hourly_rate_cents` (at least
    1000 cents when set), and that hourly rate must be divisible by 4, since the
    studio bills in quarter-hour increments. Any of these pricing faults ... is
    rejected with `ERR_INVALID_PRICING`."

    Design: Corner/validations/book_appointment_hourly_rate_not_divisible_by_four_rejected
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    resp = api.create_appointment(
        factories.create_appointment_payload(
            artist["id"], client["id"], chair["id"], chair["version"],
            pricing_mode="HOURLY", hourly_rate_cents=18002, estimated_minutes=60,
            start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T11:00:00Z",
        ),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PRICING.value, expected_status=422)


def test_book_custom_request_not_approved_rejected(api):
    """PRD §3.5: "if a `custom_request_id` is supplied, the referenced custom
    request must be in `APPROVED`; if it is in any other state the hold is
    rejected with `ERR_REQUEST_NOT_APPROVED`."

    Design: Corner/validations/book_appointment_custom_request_not_approved_rejected
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    request = get_success_data(
        api.create_custom_request(
            factories.create_custom_request_payload(artist["id"], client["id"], brief="Wolf"),
            make_client_headers(client["id"]),
        )
    )
    # Quote it but do NOT approve — leaves it QUOTED.
    get_success_data(
        api.quote_custom_request(
            request["id"], factories.quote_payload(quoted_price_cents=60000, estimated_minutes=180),
            make_artist_headers(artist["id"]),
        )
    )
    resp = api.create_appointment(
        {
            "artist_id": artist["id"], "client_id": client["id"], "chair_id": chair["id"],
            "expected_chair_version": chair["version"], "pricing_mode": "PIECE",
            "custom_request_id": request["id"], "piece_price_cents": 60000,
            "estimated_minutes": 180, "start_at": "2026-07-01T10:00:00Z",
            "end_at": "2026-07-01T13:00:00Z",
        },
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_APPROVED.value, expected_status=422)


def test_book_end_before_start_rejected(api):
    """PRD §3.5: "**Interval validity** is next: `end_at` must be strictly after
    `start_at`, failing otherwise with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/book_appointment_end_before_start_rejected
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    resp = api.create_appointment(
        factories.create_appointment_payload(
            artist["id"], client["id"], chair["id"], chair["version"],
            pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
            start_at="2026-07-01T11:00:00Z", end_at="2026-07-01T11:00:00Z",
        ),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value, expected_status=422)


# ---------------------------------------------------------------------------
# Resource temporal overlap (PRD §3.5 priorities 11 & 12)
# ---------------------------------------------------------------------------
def test_artist_overlapping_window_rejected(api):
    """PRD §3.5: "**Artist availability** is then checked: the proposed half-open
    window from `start_at` to `end_at` must not overlap the window of any other
    non-terminal appointment for the same `artist_id`; an overlap is rejected
    with `ERR_ARTIST_DOUBLE_BOOKED`."

    Same artist, two distinct chairs (so the conflict is purely the artist):
    10:30-12:30 overlaps an existing 10:00-12:00.

    Design: Difficulty/resource_temporal_overlap/artist_half_open_adjacent_allowed_overlap_rejected
    """
    set_clock("2026-06-01T12:00:00Z")
    artist = create_artist(hourly_rate_cents=18000)
    chair1 = create_chair(label="Ovl C1")
    chair2 = create_chair(label="Ovl C2")
    client = create_client()
    hold_appointment(
        artist["id"], client["id"], chair1["id"], chair1["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=120,
        start_at="2026-06-10T10:00:00Z", end_at="2026-06-10T12:00:00Z",
    )
    resp = api.create_appointment(
        factories.create_appointment_payload(
            artist["id"], client["id"], chair2["id"], chair2["version"],
            pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=120,
            start_at="2026-06-10T10:30:00Z", end_at="2026-06-10T12:30:00Z",
        ),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ARTIST_DOUBLE_BOOKED.value, expected_status=409)


def test_artist_adjacent_window_allowed(api):
    """PRD §3.5: "the proposed half-open window from `start_at` to `end_at` must
    not overlap the window of any other non-terminal appointment for the same
    `artist_id`".

    The half-open interval makes an exactly-adjacent window (12:00-13:00 after
    10:00-12:00) non-overlapping, so a second hold for the same artist on a
    second chair succeeds.

    Design: Difficulty/resource_temporal_overlap/artist_half_open_adjacent_allowed_overlap_rejected
    """
    set_clock("2026-06-01T12:00:00Z")
    artist = create_artist(hourly_rate_cents=18000)
    chair1 = create_chair(label="Adj C1")
    chair2 = create_chair(label="Adj C2")
    client = create_client()
    hold_appointment(
        artist["id"], client["id"], chair1["id"], chair1["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=120,
        start_at="2026-06-10T10:00:00Z", end_at="2026-06-10T12:00:00Z",
    )
    appt2 = hold_appointment(
        artist["id"], client["id"], chair2["id"], chair2["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
        start_at="2026-06-10T12:00:00Z", end_at="2026-06-10T13:00:00Z",
    )
    assert appt2["status"] == "HELD", f"adjacent half-open window must be allowed, got {appt2['status']}"


def test_chair_buffered_adjacent_rejected(api):
    """PRD §3.5: "**Chair availability** is checked next: the chair must be
    active, and the proposed window — expanded on each side by the chair's
    `cleanup_buffer_minutes` — must not overlap any other non-terminal
    appointment on the same `chair_id`; a buffered overlap or an inactive chair
    is rejected with `ERR_CHAIR_UNAVAILABLE`."

    Two DIFFERENT artists (so the artist check passes); one chair with a 30-min
    buffer; exactly-adjacent 12:00-13:00 after 10:00-12:00 falls inside the
    buffer.

    Design: Difficulty/resource_temporal_overlap/chair_buffered_adjacent_rejected
    """
    set_clock("2026-06-01T12:00:00Z")
    artist1 = create_artist(hourly_rate_cents=18000)
    artist2 = create_artist(hourly_rate_cents=18000)
    chair = create_chair(cleanup_buffer_minutes=30)
    client = create_client()
    hold_appointment(
        artist1["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=120,
        start_at="2026-06-10T10:00:00Z", end_at="2026-06-10T12:00:00Z",
    )
    chair_v2 = get_success_data(api.get_chair(chair["id"], MANAGER))["version"]
    resp = api.create_appointment(
        factories.create_appointment_payload(
            artist2["id"], client["id"], chair["id"], chair_v2,
            pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
            start_at="2026-06-10T12:00:00Z", end_at="2026-06-10T13:00:00Z",
        ),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHAIR_UNAVAILABLE.value, expected_status=409)


def test_chair_gap_beyond_buffer_allowed(api):
    """PRD §3.5: "the proposed window — expanded on each side by the chair's
    `cleanup_buffer_minutes` — must not overlap any other non-terminal
    appointment on the same `chair_id`".

    Complement of the buffered-adjacent rejection: with a 30-min buffer, a second
    appointment that leaves a full 60-min gap (13:00-14:00 after 10:00-12:00)
    clears the buffer on both sides and is allowed.

    Design: Difficulty/resource_temporal_overlap/chair_buffered_adjacent_rejected
    """
    set_clock("2026-06-01T12:00:00Z")
    artist1 = create_artist(hourly_rate_cents=18000)
    artist2 = create_artist(hourly_rate_cents=18000)
    chair = create_chair(cleanup_buffer_minutes=30)
    client = create_client()
    hold_appointment(
        artist1["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=120,
        start_at="2026-06-10T10:00:00Z", end_at="2026-06-10T12:00:00Z",
    )
    chair_v2 = get_success_data(api.get_chair(chair["id"], MANAGER))["version"]
    appt2 = hold_appointment(
        artist2["id"], client["id"], chair["id"], chair_v2,
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
        start_at="2026-06-10T13:00:00Z", end_at="2026-06-10T14:00:00Z",
    )
    assert appt2["status"] == "HELD", \
        f"a gap beyond the buffer must be allowed, got {appt2['status']}"


# ---------------------------------------------------------------------------
# Chair-version OCC (PRD §2.7)
# ---------------------------------------------------------------------------
def test_hold_with_stale_chair_version_rejected(api):
    """PRD §2.7: "When holding a new appointment, the request must carry
    `expected_chair_version`, which must equal the current `version` of the
    target `Chair`. If a prior hold has legitimately reserved an overlapping
    slot on that chair and advanced the chair's `version` since the client last
    read it, the client's view of chair availability is stale; the hold is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_chair_version_increments_on_hold
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair = create_chair()
    client = create_client()
    # First hold succeeds and bumps the chair version.
    hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T11:00:00Z",
    )
    # Second hold reuses the now-stale pre-bump chair version.
    resp = api.create_appointment(
        factories.create_appointment_payload(
            artist["id"], client["id"], chair["id"], chair["version"],
            pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
            start_at="2026-07-01T14:00:00Z", end_at="2026-07-01T15:00:00Z",
        ),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
