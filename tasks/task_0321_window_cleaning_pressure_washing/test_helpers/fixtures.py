"""Composite setup helpers for multi-step test prerequisites.

The dominant precondition across this domain is "an ACTIVE agreement with its
first generated visit", reached via:
  account -> property -> quote -> send -> accept -> convert -> activate -> (visit).
On top of that sit the dispatch chain (crew -> route -> commit -> dispatch ->
photos -> start -> complete) and various terminal/threshold states. These
fixtures encapsulate those chains so tests focus on assertions.

Uses get_success_data() (lenient 2xx validator) so a broken setup step produces
a clear "Setup step failed" error rather than a confusing assertion failure.

Identity threading (PRD §2.1): the Customer role is entity-backed on Account, so
every ownership-gated Customer call uses make_customer_headers(account["id"]).
Opaque roles (Dispatcher, FieldCrew, Billing) use their shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload, create_property_payload, create_quote_payload,
    create_service_agreement_payload, activate_agreement_payload,
    create_deposit_payload, create_crew_payload, create_route_payload,
    commit_visit_payload, attach_add_on_payload, upload_photo_payload,
    weather_reschedule_payload, create_weather_advisory_payload,
    create_invoice_payload, create_reclean_request_payload,
)
from .test_users import TEST_USERS, make_customer_headers


BILLING = TEST_USERS["billing_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FIELD_CREW = TEST_USERS["field_crew_headers"]


# ─── Tier 0: Atomic creates ──────────────────────────────────────────────
def create_account(region_code="NORTH", **overrides):
    """Create an ACTIVE account. Returns the account dict."""
    res = api_client.create_account(
        create_account_payload(region_code=region_code, **overrides), BILLING)
    return get_success_data(res)


def create_property(account_id, **overrides):
    """Register a property under an account. Returns the property dict."""
    res = api_client.create_property(
        create_property_payload(account_id, **overrides), BILLING)
    return get_success_data(res)


def create_crew(region_code="NORTH", skill_codes=None, daily_capacity_minutes=600, **overrides):
    """Create an AVAILABLE crew. Returns the crew dict."""
    res = api_client.create_crew(
        create_crew_payload(region_code=region_code,
                            skill_codes=skill_codes if skill_codes is not None else [],
                            daily_capacity_minutes=daily_capacity_minutes, **overrides),
        DISPATCHER)
    return get_success_data(res)


def create_route(crew_id, region_code="NORTH", service_date="2026-07-01", **overrides):
    """Create a PLANNING route. Returns the route dict (includes version)."""
    res = api_client.create_route(
        create_route_payload(crew_id, region_code=region_code,
                            service_date=service_date, **overrides), DISPATCHER)
    return get_success_data(res)


def post_deposit(account_id, agreement_id, amount_cents):
    """Post a HELD deposit. Returns the deposit dict."""
    res = api_client.create_deposit(
        create_deposit_payload(account_id, agreement_id, amount_cents), BILLING)
    return get_success_data(res)


def create_weather_suspend(region_code, advisory_date):
    """Register a SUSPEND-severity weather advisory. Returns the advisory dict."""
    res = api_client.create_weather_advisory(
        create_weather_advisory_payload(region_code=region_code,
                                        advisory_date=advisory_date, severity="SUSPEND"),
        DISPATCHER)
    return get_success_data(res)


# ─── Tier 1: Quote lifecycle ─────────────────────────────────────────────
def create_quote(account_id, property_id, **quote_overrides):
    """Create a DRAFT quote. Returns the quote dict (priced fields computed)."""
    res = api_client.create_quote(
        create_quote_payload(account_id, property_id, **quote_overrides), BILLING)
    return get_success_data(res)


def create_sent_quote(account_id, property_id, **quote_overrides):
    """Create then send a quote (DRAFT -> SENT, priced fields frozen).
    Returns the sent quote dict."""
    quote = create_quote(account_id, property_id, **quote_overrides)
    return get_success_data(api_client.send_quote(quote["id"], BILLING))


def create_accepted_quote(account_id, property_id, **quote_overrides):
    """Create -> send -> accept a quote. accept is Customer-exclusive, so it is
    called with make_customer_headers(account_id). Returns the ACCEPTED quote."""
    quote = create_sent_quote(account_id, property_id, **quote_overrides)
    cust = make_customer_headers(account_id)
    return get_success_data(api_client.accept_quote(quote["id"], cust))


# ─── Tier 2: Agreement lifecycle ─────────────────────────────────────────
def create_agreement(account_id, property_id, schedule_kind="ONE_TIME",
                     agreement_overrides=None, **quote_overrides):
    """account(given) -> property(given) -> quote -> send -> accept -> convert.
    Returns the PENDING_DEPOSIT agreement dict."""
    quote = create_accepted_quote(account_id, property_id, **quote_overrides)
    payload = create_service_agreement_payload(
        quote["id"], schedule_kind, **(agreement_overrides or {}))
    return get_success_data(api_client.create_service_agreement(payload, BILLING))


def setup_pending_agreement(schedule_kind="ONE_TIME", region_code="NORTH",
                            property_overrides=None, quote_overrides=None,
                            agreement_overrides=None):
    """Full chain to a PENDING_DEPOSIT agreement, building account + property too.
    Returns (account, property, quote, agreement)."""
    account = create_account(region_code=region_code)
    prop = create_property(account["id"], **(property_overrides or {}))
    quote = create_accepted_quote(account["id"], prop["id"], **(quote_overrides or {}))
    payload = create_service_agreement_payload(
        quote["id"], schedule_kind, **(agreement_overrides or {}))
    agreement = get_success_data(api_client.create_service_agreement(payload, BILLING))
    return account, prop, quote, agreement


def activate_agreement(agreement_id, planned_date="2026-07-01",
                       window_start_min=540, window_end_min=660):
    """Activate a PENDING_DEPOSIT agreement (deposit must already be met).
    Returns the ACTIVE agreement dict."""
    res = api_client.activate_agreement(
        agreement_id,
        activate_agreement_payload(planned_date, window_start_min, window_end_min),
        BILLING)
    return get_success_data(res)


def setup_active_agreement(schedule_kind="ONE_TIME", region_code="NORTH",
                           deposit_cents=None,
                           planned_date="2026-07-01",
                           window_start_min=540, window_end_min=660,
                           property_overrides=None, quote_overrides=None,
                           agreement_overrides=None):
    """Full chain to an ACTIVE agreement with its first UNSCHEDULED visit generated.
    If deposit_cents is given (or the agreement requires a deposit), posts a HELD
    deposit before activation. Returns (account, property, agreement, visit)."""
    account, prop, quote, agreement = setup_pending_agreement(
        schedule_kind, region_code, property_overrides, quote_overrides, agreement_overrides)

    required = agreement.get("required_deposit_cents", 0)
    to_post = deposit_cents if deposit_cents is not None else required
    if to_post and to_post > 0:
        post_deposit(account["id"], agreement["id"], to_post)

    active = activate_agreement(agreement["id"], planned_date, window_start_min, window_end_min)
    visit = _first_agreement_visit(agreement["id"])
    return account, prop, active, visit


def _first_agreement_visit(agreement_id):
    """Return the first (oldest) visit generated by an agreement."""
    res = api_client.list_agreement_visits(agreement_id, BILLING)
    data, _ = _paginated(res)
    return data[0]


def _paginated(res):
    """Lenient unpack of a paginated list response for setup use."""
    body = res.json()
    return body["data"], body["meta"]


# ─── Tier 3: Commit / dispatch chain ─────────────────────────────────────
def commit_visit(route_id, visit_id, headers=DISPATCHER):
    """Read the route's current version and commit the visit onto it
    (UNSCHEDULED -> SCHEDULED). Returns the committed visit dict."""
    route = get_success_data(api_client.get_route(route_id, DISPATCHER))
    res = api_client.commit_visit(
        route_id, commit_visit_payload(visit_id, route["version"]), headers)
    return get_success_data(res)


def setup_scheduled_visit(region_code="NORTH", schedule_kind="ONE_TIME",
                          service_date="2026-07-01", crew_skills=None,
                          daily_capacity_minutes=600, deposit_cents=None,
                          window_start_min=540, window_end_min=660,
                          property_overrides=None, quote_overrides=None):
    """ACTIVE agreement + crew + route, with the first visit committed (SCHEDULED).
    Returns (account, property, agreement, visit, crew, route)."""
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind=schedule_kind, region_code=region_code, deposit_cents=deposit_cents,
        planned_date=service_date, window_start_min=window_start_min,
        window_end_min=window_end_min,
        property_overrides=property_overrides, quote_overrides=quote_overrides)
    crew = create_crew(region_code=region_code, skill_codes=crew_skills,
                       daily_capacity_minutes=daily_capacity_minutes)
    route = create_route(crew["id"], region_code=region_code, service_date=service_date)
    committed = commit_visit(route["id"], visit["id"])
    return account, prop, agreement, committed, crew, route


def setup_dispatched_visit(**kwargs):
    """As setup_scheduled_visit, then dispatch the route (visit -> DISPATCHED).
    Returns (account, property, agreement, visit, crew, route)."""
    account, prop, agreement, visit, crew, route = setup_scheduled_visit(**kwargs)
    get_success_data(api_client.dispatch_route(route["id"], DISPATCHER))
    visit = get_success_data(api_client.get_visit(visit["id"], DISPATCHER))
    return account, prop, agreement, visit, crew, route


def upload_photo(visit_id, phase, image_uri="s3://photo.jpg"):
    """Upload a BEFORE/AFTER photo. Returns the photo dict."""
    res = api_client.upload_photo(visit_id, upload_photo_payload(phase, image_uri), FIELD_CREW)
    return get_success_data(res)


def setup_in_progress_visit(before_photo=True, **kwargs):
    """As setup_dispatched_visit, upload a BEFORE photo and start the visit
    (-> IN_PROGRESS). Returns (account, property, agreement, visit, crew, route)."""
    account, prop, agreement, visit, crew, route = setup_dispatched_visit(**kwargs)
    if before_photo:
        upload_photo(visit["id"], "BEFORE")
    get_success_data(api_client.start_visit(visit["id"], FIELD_CREW))
    visit = get_success_data(api_client.get_visit(visit["id"], FIELD_CREW))
    return account, prop, agreement, visit, crew, route


def setup_completed_visit(after_photo_count=1, add_on_codes=None, **kwargs):
    """Full chain to a COMPLETED visit (schedule_status COMPLETED, charge stamped).
    Optionally attach add-ons before completion and upload N AFTER photos.
    Returns (account, property, agreement, visit, crew, route)."""
    account, prop, agreement, visit, crew, route = setup_dispatched_visit(**kwargs)
    if add_on_codes:
        for code in add_on_codes:
            get_success_data(api_client.attach_add_on(
                visit["id"], attach_add_on_payload(code), DISPATCHER))
    upload_photo(visit["id"], "BEFORE")
    get_success_data(api_client.start_visit(visit["id"], FIELD_CREW))
    for i in range(max(after_photo_count, 1)):
        upload_photo(visit["id"], "AFTER", image_uri=f"s3://after{i}.jpg")
    get_success_data(api_client.complete_visit(visit["id"], FIELD_CREW))
    visit = get_success_data(api_client.get_visit(visit["id"], FIELD_CREW))
    return account, prop, agreement, visit, crew, route


def setup_invoiced_visit(**kwargs):
    """Full chain to a COMPLETED + INVOICED visit. Returns
    (account, property, agreement, visit, crew, route, invoice)."""
    account, prop, agreement, visit, crew, route = setup_completed_visit(**kwargs)
    invoice = get_success_data(api_client.create_invoice(
        create_invoice_payload(visit["id"]), BILLING))
    return account, prop, agreement, visit, crew, route, invoice


# ─── Tier 4: Reschedule / threshold targeting ────────────────────────────
def weather_reschedule_once(visit, route, new_planned_date):
    """Register a SUSPEND advisory covering the visit's current planned_date/region
    and weather-reschedule it (-> UNSCHEDULED, reschedule_count += 1).
    Returns the rescheduled visit dict."""
    create_weather_suspend(route["region_code"], visit["planned_date"])
    res = api_client.weather_reschedule_visit(
        visit["id"], weather_reschedule_payload(new_planned_date), DISPATCHER)
    return get_success_data(res)


def setup_visit_rescheduled_twice(region_code="NORTH", quote_overrides=None,
                                  property_overrides=None):
    """An ACTIVE ONE_TIME agreement's visit committed, weather-rescheduled twice
    (reschedule_count reaches 2), then re-committed onto a third-date route,
    dispatched, and carried through BEFORE photo + start + AFTER photo so the
    test can trigger completion. Returns (account, property, agreement, visit, crew).

    Dates: commit @ 07-01 -> reschedule to 07-08 -> reschedule to 07-15.
    A single crew runs all three single-day routes (07-01, 07-08, 07-15)."""
    account, prop, agreement, visit, crew, route1 = setup_scheduled_visit(
        region_code=region_code, schedule_kind="ONE_TIME", service_date="2026-07-01",
        quote_overrides=quote_overrides, property_overrides=property_overrides)

    # First reschedule: 07-01 -> 07-08
    visit = weather_reschedule_once(visit, route1, "2026-07-08")
    route2 = create_route(crew["id"], region_code=region_code, service_date="2026-07-08")
    visit = commit_visit(route2["id"], visit["id"])

    # Second reschedule: 07-08 -> 07-15
    visit = weather_reschedule_once(visit, route2, "2026-07-15")
    route3 = create_route(crew["id"], region_code=region_code, service_date="2026-07-15")
    visit = commit_visit(route3["id"], visit["id"])

    # Dispatch + walk to ready-for-completion.
    get_success_data(api_client.dispatch_route(route3["id"], DISPATCHER))
    upload_photo(visit["id"], "BEFORE")
    get_success_data(api_client.start_visit(visit["id"], FIELD_CREW))
    upload_photo(visit["id"], "AFTER")
    visit = get_success_data(api_client.get_visit(visit["id"], FIELD_CREW))
    return account, prop, agreement, visit, crew


def setup_requested_reclean(after_photo_count=1, **kwargs):
    """A COMPLETED visit with N AFTER photos, plus a REQUESTED ReCleanRequest on it.
    The re-clean is Customer-exclusive, opened with make_customer_headers(account.id).
    Returns (account, property, agreement, visit, reclean)."""
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        after_photo_count=after_photo_count, **kwargs)
    cust = make_customer_headers(account["id"])
    reclean = get_success_data(api_client.create_reclean_request(
        create_reclean_request_payload(visit["id"]), cust))
    return account, prop, agreement, visit, reclean
