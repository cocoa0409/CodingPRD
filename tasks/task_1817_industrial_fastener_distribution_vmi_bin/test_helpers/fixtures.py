"""Composite setup helpers.

Every helper builds preconditions from scratch via PRD-declared endpoints
(the server is re-launched before each test, so no state is ever carried
over). Setup calls use the lenient get_success_data() validator so failures
surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .constants import (
    CLOCK_INSIDE_WINDOW, ROUTE_DATE, WINDOW_END, WINDOW_START,
)
from .factories import (
    _OMIT,
    create_bin_agreement_payload,
    create_kit_job_payload,
    create_lot_certificate_payload,
    create_part_cross_reference_payload,
    create_part_payload,
    create_route_payload,
    create_route_stop_payload,
    create_site_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
DRIVER = TEST_USERS["driver_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators
# ---------------------------------------------------------------------------

def create_site(api, **overrides) -> dict:
    return get_success_data(api.create_site(create_site_payload(**overrides), ADMIN))


def create_part(api, **overrides) -> dict:
    return get_success_data(api.create_part(create_part_payload(**overrides), ADMIN))


def create_agreement(api, site_id, part_id, **overrides) -> dict:
    return get_success_data(api.create_bin_agreement(
        create_bin_agreement_payload(site_id, part_id, **overrides), ADMIN))


def create_cert(api, part_id, **overrides) -> dict:
    return get_success_data(api.create_lot_certificate(
        create_lot_certificate_payload(part_id, **overrides), ADMIN))


def create_cross_reference(api, from_part_id, to_part_id, **overrides) -> dict:
    return get_success_data(api.create_part_cross_reference(
        create_part_cross_reference_payload(
            from_part_id=from_part_id, to_part_id=to_part_id, **overrides),
        ADMIN))


def create_kit_job(api, site_id, component_part_ids, **overrides) -> dict:
    return get_success_data(api.create_kit_job(
        create_kit_job_payload(site_id, component_part_ids, **overrides),
        OPERATOR))


def get_site_version(api, site_id) -> int:
    return get_success_data(api.get_site(site_id, ADMIN))["version"]


def create_route(api, site_id, route_date=ROUTE_DATE,
                 window_start=WINDOW_START, window_end=WINDOW_END) -> dict:
    """Schedule a route, fetching the site's current version for the OCC guard."""
    site_v = get_site_version(api, site_id)
    return get_success_data(api.create_route(
        create_route_payload(
            site_id, site_v,
            route_date=route_date, window_start=window_start,
            window_end=window_end),
        ADMIN))


def set_clock(api, to_iso8601) -> dict:
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def start_route(api, route_id, clock_at=CLOCK_INSIDE_WINDOW) -> dict:
    """Advance the logical clock inside the window, then start the route."""
    set_clock(api, clock_at)
    return get_success_data(api.start_route(route_id, DRIVER))


def create_stop(api, route_id, bin_agreement_id) -> dict:
    return get_success_data(api.create_route_stop(
        route_id, create_route_stop_payload(bin_agreement_id), DRIVER))


def submit_stop(api, stop_id, counted_qty) -> dict:
    return get_success_data(api.submit_route_stop(
        stop_id, {"counted_qty": counted_qty}, DRIVER))


# ---------------------------------------------------------------------------
# Tier 1/2: site + part + agreement, route with stop, order chains
# ---------------------------------------------------------------------------

def setup_site_part_agreement(api, *, credit_limit_cents=100_000_000,
                              delivery_mode="DOCK_TO_STOCK",
                              is_critical=False, unit_price_cents=1000,
                              total_stock_qty=100_000,
                              pricing_mode="UNIT_PRICE",
                              flat_bin_price_cents=_OMIT,
                              min_qty=10, max_qty=100,
                              bin_location=None,
                              with_cert=False,
                              cert_expires_at="2027-01-01T00:00:00Z") -> dict:
    """Site + part (+ optional lot certificate) + bin agreement."""
    site = create_site(api, credit_limit_cents=credit_limit_cents,
                       delivery_mode=delivery_mode)
    part = create_part(api, is_critical=is_critical,
                       unit_price_cents=unit_price_cents,
                       total_stock_qty=total_stock_qty)
    cert = None
    if with_cert:
        cert = create_cert(api, part["id"], cert_expires_at=cert_expires_at)
    kwargs = {"pricing_mode": pricing_mode, "min_qty": min_qty,
              "max_qty": max_qty}
    if bin_location is not None:
        kwargs["bin_location"] = bin_location
    if flat_bin_price_cents is not _OMIT:
        kwargs["flat_bin_price_cents"] = flat_bin_price_cents
    agreement = create_agreement(api, site["id"], part["id"], **kwargs)
    return {"site": site, "part": part, "cert": cert, "agreement": agreement}


def setup_started_route_with_stop(api, site_id, bin_agreement_id, *,
                                  route_date=ROUTE_DATE,
                                  window_start=WINDOW_START,
                                  window_end=WINDOW_END,
                                  clock_at=CLOCK_INSIDE_WINDOW) -> dict:
    """Route scheduled, clock advanced into the window, route started, one
    stop registered for the agreement. Returns route and stop."""
    route = create_route(api, site_id, route_date=route_date,
                         window_start=window_start, window_end=window_end)
    start_route(api, route["id"], clock_at=clock_at)
    stop = create_stop(api, route["id"], bin_agreement_id)
    return {"route": route, "stop": stop}


def setup_draft_order(api, *, counted_qty=5, route_date=ROUTE_DATE,
                      window_start=WINDOW_START, window_end=WINDOW_END,
                      clock_at=CLOCK_INSIDE_WINDOW,
                      **agreement_kwargs) -> dict:
    """Site/part/agreement + started route + submitted stop whose count is
    below the reorder point, producing a DRAFT replenishment order."""
    ctx = setup_site_part_agreement(api, **agreement_kwargs)
    rs = setup_started_route_with_stop(
        api, ctx["site"]["id"], ctx["agreement"]["id"],
        route_date=route_date, window_start=window_start,
        window_end=window_end, clock_at=clock_at)
    submitted = submit_stop(api, rs["stop"]["id"], counted_qty)
    order_id = submitted["generated_order_id"]
    ctx.update(rs)
    ctx["submitted_stop"] = submitted
    ctx["order_id"] = order_id
    return ctx


def setup_confirmed_order(api, *, counted_qty=5, **kwargs) -> dict:
    ctx = setup_draft_order(api, counted_qty=counted_qty, **kwargs)
    assert ctx["order_id"] is not None, (
        f"expected an order: counted {counted_qty} must be below min_qty "
        f"{ctx['agreement']['min_qty']}"
    )
    get_success_data(api.confirm_order(ctx["order_id"], ADMIN))
    return ctx


def setup_delivered_order(api, *, counted_qty=5, **kwargs) -> dict:
    ctx = setup_confirmed_order(api, counted_qty=counted_qty, **kwargs)
    get_success_data(api.ship_order(ctx["order_id"], ADMIN))
    get_success_data(api.deliver_order(ctx["order_id"], DRIVER))
    return ctx


def run_weekly_scan(api, site_id, bin_agreement_id, day, counted_qty,
                    close=True) -> dict:
    """One weekly route cycle on its own day: schedule, clock, start, stop,
    submit, close. Returns the submitted stop."""
    route = create_route(
        api, site_id,
        route_date=f"2026-08-{day:02d}T00:00:00Z",
        window_start=f"2026-08-{day:02d}T08:00:00Z",
        window_end=f"2026-08-{day:02d}T12:00:00Z")
    start_route(api, route["id"], clock_at=f"2026-08-{day:02d}T09:00:00Z")
    stop = create_stop(api, route["id"], bin_agreement_id)
    submitted = submit_stop(api, stop["id"], counted_qty)
    if close:
        get_success_data(api.close_route(route["id"], DRIVER))
    return submitted


def setup_sizing_history(api, *, min_qty=25, max_qty=200,
                         counts=(100, 90, 80, 70, 20)) -> dict:
    """Agreement plus one weekly submitted scan per entry in `counts`, each on
    its own day (Aug 3..7). The final scan (below min_qty) is left on an
    in-progress route without closing it."""
    ctx = setup_site_part_agreement(api, min_qty=min_qty, max_qty=max_qty)
    days = (3, 4, 5, 6, 7)
    for i, count in enumerate(counts):
        run_weekly_scan(api, ctx["site"]["id"], ctx["agreement"]["id"],
                        days[i], count, close=(i < len(counts) - 1))
    return ctx
