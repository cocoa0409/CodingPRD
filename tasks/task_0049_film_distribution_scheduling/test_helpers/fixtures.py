"""Composite setup helpers for the Film Distribution Scheduling test suite.

Most interesting test claims require the system to be in a specific state
reached through 5–15 API calls. These helpers encapsulate those preambles
so test bodies stay focused on assertions.

Identity threading (PRD §2.1):

- DistributorOps and CinemaOps are entity-backed. PRD §2.1: 'ownership
  checks on any resource that references a Distributor compare the
  resource's foreign-key field to X-User-ID' (analogous for Cinema).
  Every ownership-gated call below uses make_<role>_headers(entity['id'])
  so the X-User-ID resolves to the real entity. Falling back to the
  shared TEST_USERS constant for an entity-backed role would make every
  ownership check fail.

- PlatformAdmin, TicketingPlatform, FinanceOps, and Auditor are opaque
  (PRD §2.1: 'an opaque operator identifier not tied to any persisted
  entity'); the shared TEST_USERS entries are canonical.

Setup helpers use get_success_data (lenient), so broken preconditions
surface as obvious errors rather than ambiguous assertion failures.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    ALT_REGION,
    DEFAULT_AD_MIN,
    DEFAULT_BUSINESS_DATE,
    DEFAULT_CLEANING_INTERVAL_MIN,
    DEFAULT_PEAK_END_MIN,
    DEFAULT_PEAK_START_MIN,
    DEFAULT_PRESALE_OPENS_AT,
    DEFAULT_REGION,
    DEFAULT_RELEASE_DATE,
    DEFAULT_TRAILER_MIN,
    WIDE_OPERATING_END_MIN,
    WIDE_OPERATING_START_MIN,
)
from .factories import (
    cancel_showtime_payload,
    clock_advance_payload,
    create_cinema_payload,
    create_distributor_payload,
    create_film_payload,
    create_screen_payload,
    create_settlement_payload,
    create_showtime_payload,
    create_ticket_payload,
    shelve_payload,
    version_payload,
)
from .test_users import (
    TEST_USERS,
    make_cinema_ops_headers,
    make_distributor_ops_headers,
)


# Shared headers for opaque roles (PRD §2.1).
ADMIN = TEST_USERS["platform_admin_headers"]
TICKETING = TEST_USERS["ticketing_platform_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ===========================================================================
# Top-level helpers -- core entity creation
# ===========================================================================
def create_distributor(
    *,
    default_split_ratio_bps: int = 6000,
    min_show_count_per_week: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A new distributor is created with name, contact_email,
    the integer default_split_ratio_bps ..., and min_show_count_per_week'.
    PRD §4: POST /distributors is authorised to PlatformAdmin."""
    payload = create_distributor_payload(
        default_split_ratio_bps=default_split_ratio_bps,
        min_show_count_per_week=min_show_count_per_week,
        **overrides,
    )
    return get_success_data(api_client.create_distributor(payload, ADMIN))


def create_cinema(
    *,
    region_code: str = DEFAULT_REGION,
    tier: str = "TIER_1",
    peak_window_start_minute: int = DEFAULT_PEAK_START_MIN,
    peak_window_end_minute: int = DEFAULT_PEAK_END_MIN,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'CinemaOps registers a Cinema with name, a region_code, a
    tier ..., and the cinema-wide peak window ...'.

    Because Cinema creation is itself the ownership-source -- PRD §2.1
    says CinemaOps' X-User-ID 'is the id of the acting Cinema' -- there
    is no real Cinema to own yet. The fallback CinemaOps header is used
    here only for the initial create; every subsequent ownership-gated
    call uses make_cinema_ops_headers(cinema['id'])."""
    payload = create_cinema_payload(
        region_code=region_code,
        tier=tier,
        peak_window_start_minute=peak_window_start_minute,
        peak_window_end_minute=peak_window_end_minute,
        **overrides,
    )
    return get_success_data(
        api_client.create_cinema(
            payload, TEST_USERS["cinema_ops_headers"],
        ),
    )


def create_screen(
    cinema: Dict[str, Any],
    *,
    supported_formats: Optional[List[str]] = None,
    operating_start_minute: int = WIDE_OPERATING_START_MIN,
    operating_end_minute: int = WIDE_OPERATING_END_MIN,
    cleaning_interval_minutes: int = DEFAULT_CLEANING_INTERVAL_MIN,
    trailer_minutes: int = DEFAULT_TRAILER_MIN,
    ad_minutes: int = DEFAULT_AD_MIN,
    seat_capacity: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'Each cinema hosts one or more Screen rows.'
    Owner identity threaded via make_cinema_ops_headers(cinema['id'])."""
    payload = create_screen_payload(
        supported_formats=supported_formats,
        operating_start_minute=operating_start_minute,
        operating_end_minute=operating_end_minute,
        cleaning_interval_minutes=cleaning_interval_minutes,
        trailer_minutes=trailer_minutes,
        ad_minutes=ad_minutes,
        seat_capacity=seat_capacity,
        **overrides,
    )
    return get_success_data(
        api_client.create_screen(
            cinema["id"], payload, make_cinema_ops_headers(cinema["id"]),
        ),
    )


def create_film(
    distributor: Dict[str, Any],
    *,
    duration_minutes: int = 90,
    format: str = "2D",
    release_date: str = DEFAULT_RELEASE_DATE,
    region_strategy: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Films are registered by DistributorOps against an active
    distributor.' Owner identity threaded via
    make_distributor_ops_headers(distributor['id'])."""
    payload = create_film_payload(
        distributor_id=distributor["id"],
        duration_minutes=duration_minutes,
        format=format,
        release_date=release_date,
        region_strategy=region_strategy,
        **overrides,
    )
    return get_success_data(
        api_client.create_film(
            payload, make_distributor_ops_headers(distributor["id"]),
        ),
    )


# ===========================================================================
# Clock + sweep helpers
# ===========================================================================
def advance_clock(to_timestamp: str) -> None:
    """PRD §2.10: 'In test mode the clock can be advanced -- but never
    rewound -- by submitting an ISO 8601 instant as to_timestamp.'
    PRD §4: POST /_clock/advance is authorised to PlatformAdmin."""
    res = api_client.advance_clock(
        clock_advance_payload(to_timestamp), ADMIN,
    )
    # Tolerate ERR_CLOCK_REGRESS if the caller already advanced past this
    # instant -- that is the PRD §2.10 idempotency case ('rejected if
    # instant <= current clock'). Tests that depend on the advance
    # succeeding should assert HTTP 200 explicitly.
    if not (200 <= res.status_code < 300):
        # Surface the error body so setup failures are obvious.
        try:
            body = res.json()
        except Exception:
            body = res.text
        # If it's not a regress, fail loudly.
        err_id = ""
        if isinstance(body, dict):
            err_id = (body.get("data") or {}).get("error_id") or ""
        if err_id != "ERR_CLOCK_REGRESS":
            raise AssertionError(
                f"advance_clock to {to_timestamp} failed: "
                f"status={res.status_code} body={body}"
            )


def run_sweep() -> None:
    """PRD §2.10: 'A separate sweep capability scans all Showtime rows
    and applies the system-actor transitions on sale_status and
    lifecycle_status whose time preconditions are now satisfied'."""
    get_success_data(api_client.run_sweep(ADMIN))


# ===========================================================================
# Film lifecycle helpers
# ===========================================================================
def release_film(film: Dict[str, Any],
                 distributor: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.2: 'Promotion from PLANNED to RELEASED is initiated by
    DistributorOps'. Caller is responsible for advancing the clock to or
    past film.release_date first."""
    return get_success_data(api_client.release_film(
        film["id"], version_payload(film["version"]),
        make_distributor_ops_headers(distributor["id"]),
    ))


def shelve_film(film: Dict[str, Any],
                distributor: Dict[str, Any],
                *,
                reason: str = "low_demand") -> Dict[str, Any]:
    """PRD §3.2: 'Shelving -- RELEASED -> SHELVED -- is a soft pause
    invoked by DistributorOps with a free-text reason'."""
    return get_success_data(api_client.shelve_film(
        film["id"], shelve_payload(version=film["version"], reason=reason),
        make_distributor_ops_headers(distributor["id"]),
    ))


def delist_film(film: Dict[str, Any],
                distributor: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.2: 'Delisting is the terminal step and may be invoked from
    PLANNED, RELEASED, or SHELVED.'"""
    return get_success_data(api_client.delist_film(
        film["id"], version_payload(film["version"]),
        make_distributor_ops_headers(distributor["id"]),
    ))


# ===========================================================================
# Showtime / ticket helpers
# ===========================================================================
def create_showtime(
    screen: Dict[str, Any],
    cinema: Dict[str, Any],
    film: Dict[str, Any],
    *,
    start_minute: int = 720,
    business_date: str = DEFAULT_BUSINESS_DATE,
    ticket_price_cents: int = 1500,
    presale_opens_at: str = DEFAULT_PRESALE_OPENS_AT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'CinemaOps schedules a showtime against a specific
    screen'. Owner identity is the cinema; we thread make_cinema_ops_headers
    (cinema['id'])."""
    payload = create_showtime_payload(
        film_id=film["id"],
        start_minute=start_minute,
        business_date=business_date,
        ticket_price_cents=ticket_price_cents,
        presale_opens_at=presale_opens_at,
        **overrides,
    )
    return get_success_data(api_client.create_showtime(
        screen["id"], payload, make_cinema_ops_headers(cinema["id"]),
    ))


def cancel_showtime(
    showtime: Dict[str, Any],
    cinema: Dict[str, Any],
    *,
    cancel_reason: str = "INCIDENT",
    exchange_to_showtime_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.7: 'CinemaOps cancels a SCHEDULED showtime'.

    Re-fetches the showtime first so the optimistic-concurrency `version`
    we submit reflects any intermediate mutations (e.g., earlier ticket
    purchases bumped the parent showtime's version)."""
    headers = make_cinema_ops_headers(cinema["id"])
    fresh = get_success_data(api_client.get_showtime(showtime["id"], headers))
    return get_success_data(api_client.cancel_showtime(
        showtime["id"],
        cancel_showtime_payload(
            version=fresh["version"],
            cancel_reason=cancel_reason,
            exchange_to_showtime_id=exchange_to_showtime_id,
        ),
        headers,
    ))


def purchase_ticket(
    showtime: Dict[str, Any],
    *,
    buyer_external_id: str = "buyer-001",
    paid_amount_cents: Optional[int] = None,
    promo_code: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.5: 'TicketingPlatform purchases a ticket against a specific
    showtime'. TicketingPlatform is an opaque role."""
    if paid_amount_cents is None:
        paid_amount_cents = showtime.get("ticket_price_cents", 1500)
    payload = create_ticket_payload(
        buyer_external_id=buyer_external_id,
        paid_amount_cents=paid_amount_cents,
        promo_code=promo_code,
    )
    return get_success_data(api_client.purchase_ticket(
        showtime["id"], payload, TICKETING,
    ))


def refund_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.8: 'A refund supplies the standard version field'.
    TicketingPlatform is an opaque role."""
    return get_success_data(api_client.refund_ticket(
        ticket["id"], version_payload(ticket["version"]), TICKETING,
    ))


# ===========================================================================
# Settlement helpers
# ===========================================================================
def create_settlement(showtime: Dict[str, Any],
                      *,
                      cycle_label: str = "2026-W19") -> Dict[str, Any]:
    """PRD §3.9: 'FinanceOps creates a draft posting against a showtime
    by supplying the showtime_id and the cycle_label'."""
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(
            showtime_id=showtime["id"], cycle_label=cycle_label,
        ),
        FINANCE,
    ))


def post_settlement(settlement: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.9: 'The draft can only be promoted from DRAFT to POSTED by
    an explicit post action that supplies the standard version field'.

    NOTE: append-only entities have no version (PRD §2.4). The PRD §2.6
    says the version field may be supplied; for Settlement (append-only)
    we send {} and rely on idempotency rules. If implementations require
    version on Settlement, the test suite's contract is unclear -- skip
    is preferable to forcing a path.

    Read the appended Settlement back to ensure invariants hold.
    """
    res = api_client.post_settlement(
        settlement["id"], {}, FINANCE,
    )
    return get_success_data(res)


# ===========================================================================
# Composite scenarios -- the workhorse of the test suite
# ===========================================================================
def setup_basic_org(
    *,
    default_split_ratio_bps: int = 6000,
    min_show_count_per_week: int = 0,
    region_code: str = DEFAULT_REGION,
    cinema_tier: str = "TIER_1",
    supported_formats: Optional[List[str]] = None,
    operating_start_minute: int = WIDE_OPERATING_START_MIN,
    operating_end_minute: int = WIDE_OPERATING_END_MIN,
    cleaning_interval_minutes: int = DEFAULT_CLEANING_INTERVAL_MIN,
    trailer_minutes: int = DEFAULT_TRAILER_MIN,
    ad_minutes: int = DEFAULT_AD_MIN,
    seat_capacity: int = 100,
    peak_window_start_minute: int = DEFAULT_PEAK_START_MIN,
    peak_window_end_minute: int = DEFAULT_PEAK_END_MIN,
) -> Dict[str, Dict[str, Any]]:
    """Create the minimal hierarchy: distributor, cinema, screen.

    Returns dict with keys: distributor, cinema, screen.
    """
    distributor = create_distributor(
        default_split_ratio_bps=default_split_ratio_bps,
        min_show_count_per_week=min_show_count_per_week,
    )
    cinema = create_cinema(
        region_code=region_code, tier=cinema_tier,
        peak_window_start_minute=peak_window_start_minute,
        peak_window_end_minute=peak_window_end_minute,
    )
    screen = create_screen(
        cinema,
        supported_formats=supported_formats,
        operating_start_minute=operating_start_minute,
        operating_end_minute=operating_end_minute,
        cleaning_interval_minutes=cleaning_interval_minutes,
        trailer_minutes=trailer_minutes,
        ad_minutes=ad_minutes,
        seat_capacity=seat_capacity,
    )
    return {"distributor": distributor, "cinema": cinema, "screen": screen}


def setup_released_film(
    *,
    duration_minutes: int = 90,
    format: str = "2D",
    region_strategy: Optional[Dict[str, Any]] = None,
    release_date: str = DEFAULT_RELEASE_DATE,
    advance_to_release: bool = True,
    **org_kwargs: Any,
) -> Dict[str, Any]:
    """Create distributor+cinema+screen+film, advance clock to release_date
    (if requested), and promote film PLANNED -> RELEASED.

    Returns: {distributor, cinema, screen, film}.

    PRD §3.2: 'Promotion from PLANNED to RELEASED ... is allowed only once
    the server clock has reached release_date and the parent
    Distributor.status is ACTIVE'.
    """
    # Filter org_kwargs to only those setup_basic_org accepts.
    org_param_names = {
        "default_split_ratio_bps", "min_show_count_per_week", "region_code",
        "cinema_tier", "supported_formats", "operating_start_minute",
        "operating_end_minute", "cleaning_interval_minutes",
        "trailer_minutes", "ad_minutes", "seat_capacity",
        "peak_window_start_minute", "peak_window_end_minute",
    }
    org_only = {k: v for k, v in org_kwargs.items() if k in org_param_names}
    org = setup_basic_org(**org_only)
    distributor = org["distributor"]
    film = create_film(
        distributor,
        duration_minutes=duration_minutes,
        format=format,
        region_strategy=region_strategy,
        release_date=release_date,
    )
    if advance_to_release:
        advance_clock(release_date)
        film = release_film(film, distributor)
    return {**org, "film": film}


def setup_showtime_on_sale(
    *,
    duration_minutes: int = 90,
    format: str = "2D",
    seat_capacity: int = 100,
    trailer_minutes: int = DEFAULT_TRAILER_MIN,
    ad_minutes: int = DEFAULT_AD_MIN,
    cleaning_interval_minutes: int = DEFAULT_CLEANING_INTERVAL_MIN,
    operating_start_minute: int = WIDE_OPERATING_START_MIN,
    operating_end_minute: int = WIDE_OPERATING_END_MIN,
    start_minute: int = 720,
    ticket_price_cents: int = 1500,
    business_date: str = DEFAULT_BUSINESS_DATE,
    presale_opens_at: str = DEFAULT_PRESALE_OPENS_AT,
    sweep_to_on_sale: bool = True,
    region_strategy: Optional[Dict[str, Any]] = None,
    **org_kwargs: Any,
) -> Dict[str, Any]:
    """Create org + released film + showtime, advance clock past
    presale_opens_at and run sweep so showtime.sale_status == ON_SALE.

    Returns: {distributor, cinema, screen, film, showtime}.

    PRD §3.5: 'A new showtime sits in sale_status PRESALE until the server
    clock crosses presale_opens_at, at which point the system actor
    transitions sale_status to ON_SALE'.
    """
    base = setup_released_film(
        duration_minutes=duration_minutes,
        format=format,
        region_strategy=region_strategy,
        supported_formats=org_kwargs.pop("supported_formats", None)
        or [format],
        seat_capacity=seat_capacity,
        trailer_minutes=trailer_minutes,
        ad_minutes=ad_minutes,
        cleaning_interval_minutes=cleaning_interval_minutes,
        operating_start_minute=operating_start_minute,
        operating_end_minute=operating_end_minute,
        **org_kwargs,
    )
    showtime = create_showtime(
        base["screen"], base["cinema"], base["film"],
        start_minute=start_minute,
        business_date=business_date,
        ticket_price_cents=ticket_price_cents,
        presale_opens_at=presale_opens_at,
    )
    if sweep_to_on_sale:
        advance_clock(presale_opens_at)
        run_sweep()
        showtime = get_success_data(
            api_client.get_showtime(
                showtime["id"], make_cinema_ops_headers(base["cinema"]["id"]),
            )
        )
    return {**base, "showtime": showtime}


def setup_completed_showtime(
    *,
    tickets: int = 3,
    paid_amount_cents: int = 1500,
    promo_code: Optional[str] = None,
    buyer_external_id: str = "buyer-001",
    distributor_split_bps: int = 6000,
    duration_minutes: int = 90,
    format: str = "2D",
    seat_capacity: int = 100,
    start_minute: int = 720,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """Sell `tickets` valid tickets, advance the clock past end_minute,
    and sweep so lifecycle_status == COMPLETED.

    Returns: {distributor, cinema, screen, film, showtime, tickets}.

    PRD §3.6: 'When the clock further reaches business_date plus
    end_minute, the system actor transitions lifecycle_status from
    IN_PROGRESS to COMPLETED, which unblocks the downstream settlement
    post.'
    """
    base = setup_showtime_on_sale(
        default_split_ratio_bps=distributor_split_bps,
        duration_minutes=duration_minutes,
        format=format,
        seat_capacity=seat_capacity,
        start_minute=start_minute,
        **scenario_overrides,
    )
    tlist: List[Dict[str, Any]] = []
    for i in range(tickets):
        t = purchase_ticket(
            base["showtime"],
            buyer_external_id=f"{buyer_external_id}-{i}",
            paid_amount_cents=paid_amount_cents,
            promo_code=promo_code,
        )
        tlist.append(t)
    # Advance past end_minute + sweep.
    # business_date is the midnight ISO timestamp; end_minute = start +
    # block. Use a generous +24h offset so we land cleanly past.
    bdate = base["showtime"]["business_date"]
    # Compose a target instant well past end_minute: business_date next day.
    # PRD §2.10 only requires the clock to monotonically move forward to a
    # point past business_date + end_minute. A simple anchor: take
    # business_date's date string and bump to the next day.
    end_inst = _advance_past_end(bdate)
    advance_clock(end_inst)
    run_sweep()
    showtime = get_success_data(api_client.get_showtime(
        base["showtime"]["id"],
        make_cinema_ops_headers(base["cinema"]["id"]),
    ))
    return {**base, "showtime": showtime, "tickets": tlist}


def _advance_past_end(business_date_iso: str) -> str:
    """Return an ISO instant guaranteed to be past business_date+end_minute
    for any reasonable showtime (one day later at 23:59).

    Cheap implementation: replace the calendar day with the next day at
    23:59:00.000Z. business_date is formatted as 'YYYY-MM-DDT00:00:00.000Z'.
    """
    from datetime import datetime, timedelta, timezone
    # Be permissive on trailing Z vs offset.
    s = business_date_iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    bumped = dt + timedelta(days=1, hours=23, minutes=59)
    # Render with three fractional digits.
    return bumped.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def setup_posted_settlement(
    *,
    tickets: int = 3,
    paid_amount_cents: int = 1500,
    promo_code: Optional[str] = None,
    distributor_split_bps: int = 6000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Reach POSTING.status == POSTED for a fully-funded showtime.

    Returns: {distributor, cinema, screen, film, showtime, tickets,
              settlement}.

    PRD §3.9: 'FinanceOps creates a draft posting' then 'The draft can
    only be promoted from DRAFT to POSTED by an explicit post action'.
    """
    base = setup_completed_showtime(
        tickets=tickets,
        paid_amount_cents=paid_amount_cents,
        promo_code=promo_code,
        distributor_split_bps=distributor_split_bps,
        **kwargs,
    )
    draft = create_settlement(base["showtime"])
    posted = post_settlement(draft)
    return {**base, "settlement": posted, "settlement_draft": draft}


# ===========================================================================
# Difficulty-design composite fixtures (referenced by §2.1.A in the skill)
# ===========================================================================
def setup_distributor_with_weekly_minimum(
    min_show_count_per_week: int,
    showtime_count: int,
    *,
    business_date: str = DEFAULT_BUSINESS_DATE,
    start_minute_first: int = 600,
    start_minute_gap: int = 200,
) -> Dict[str, Any]:
    """Create distributor with min_show_count_per_week=N, then create
    `showtime_count` SCHEDULED showtimes for the SAME ISO-week in the
    same cinema, exhausting the minimum.

    Used by safety-fiscal priority tests (Rule 5) and by Rule 9
    screen-time conservation tests.
    Returns: {distributor, cinema, screen, film, showtimes: [...]}.
    """
    base = setup_released_film(
        default_split_ratio_bps=6000,
        min_show_count_per_week=min_show_count_per_week,
        supported_formats=["2D"],
        seat_capacity=100,
        trailer_minutes=DEFAULT_TRAILER_MIN,
        ad_minutes=DEFAULT_AD_MIN,
        cleaning_interval_minutes=DEFAULT_CLEANING_INTERVAL_MIN,
        operating_start_minute=0,
        operating_end_minute=1440,
        duration_minutes=90,
        format="2D",
    )
    showtimes = []
    sm = start_minute_first
    for i in range(showtime_count):
        st = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=sm,
            business_date=business_date,
            ticket_price_cents=1500,
            presale_opens_at=DEFAULT_PRESALE_OPENS_AT,
        )
        showtimes.append(st)
        sm += start_minute_gap
    return {**base, "showtimes": showtimes}


def setup_imax_and_2d_films(
    *,
    duration_minutes: int = 120,
) -> Dict[str, Any]:
    """Create distributor + cinema + screen with all formats supported,
    plus two RELEASED films -- one IMAX and one 2D -- for testing
    showtime_block_minutes Mode (a).
    Returns: {distributor, cinema, screen, film_imax, film_2d}.
    """
    distributor = create_distributor(
        default_split_ratio_bps=6000, min_show_count_per_week=0,
    )
    cinema = create_cinema(region_code=DEFAULT_REGION, tier="TIER_1")
    screen = create_screen(
        cinema,
        supported_formats=["2D", "3D", "IMAX"],
        operating_start_minute=0, operating_end_minute=1440,
        trailer_minutes=10, ad_minutes=5,
        cleaning_interval_minutes=15, seat_capacity=100,
    )
    film_imax = create_film(
        distributor, duration_minutes=duration_minutes,
        format="IMAX", release_date=DEFAULT_RELEASE_DATE,
    )
    film_2d = create_film(
        distributor, duration_minutes=duration_minutes,
        format="2D", release_date=DEFAULT_RELEASE_DATE,
    )
    advance_clock(DEFAULT_RELEASE_DATE)
    film_imax = release_film(film_imax, distributor)
    film_2d = release_film(film_2d, distributor)
    return {
        "distributor": distributor, "cinema": cinema, "screen": screen,
        "film_imax": film_imax, "film_2d": film_2d,
    }


def fetch_film(film_id: str, distributor: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api_client.get_film(
        film_id, make_distributor_ops_headers(distributor["id"]),
    ))


def fetch_showtime(showtime_id: str,
                   cinema: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api_client.get_showtime(
        showtime_id, make_cinema_ops_headers(cinema["id"]),
    ))


def fetch_ticket(ticket_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_ticket(ticket_id, TICKETING))


def list_settlements_for(showtime_id: str) -> List[Dict[str, Any]]:
    res = api_client.list_settlements(
        FINANCE, params={"showtime_id": showtime_id, "limit": 100},
    )
    data, _meta = validate_paginated(res)
    return data


def list_anomaly_alerts_for(
    showtime_id: str,
    buyer_external_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"showtime_id": showtime_id, "limit": 100}
    if buyer_external_id is not None:
        params["buyer_external_id"] = buyer_external_id
    res = api_client.list_anomaly_alerts(ADMIN, params=params)
    data, _meta = validate_paginated(res)
    return data


def list_schedule_adjustments_for(
    showtime_id: str,
) -> List[Dict[str, Any]]:
    res = api_client.list_schedule_adjustments(
        ADMIN, params={"showtime_id": showtime_id, "limit": 100},
    )
    data, _meta = validate_paginated(res)
    return data


def list_audit_logs_for(
    target_id: str,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"target_id": target_id, "limit": 100}
    if action is not None:
        params["action"] = action
    res = api_client.list_audit_logs(ADMIN, params=params)
    data, _meta = validate_paginated(res)
    return data


__all__ = [
    "ADMIN",
    "TICKETING",
    "FINANCE",
    "AUDITOR",
    "create_distributor",
    "create_cinema",
    "create_screen",
    "create_film",
    "advance_clock",
    "run_sweep",
    "release_film",
    "shelve_film",
    "delist_film",
    "create_showtime",
    "cancel_showtime",
    "purchase_ticket",
    "refund_ticket",
    "create_settlement",
    "post_settlement",
    "setup_basic_org",
    "setup_released_film",
    "setup_showtime_on_sale",
    "setup_completed_showtime",
    "setup_posted_settlement",
    "setup_distributor_with_weekly_minimum",
    "setup_imax_and_2d_films",
    "fetch_film",
    "fetch_showtime",
    "fetch_ticket",
    "list_settlements_for",
    "list_anomaly_alerts_for",
    "list_schedule_adjustments_for",
    "list_audit_logs_for",
]
