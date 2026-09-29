"""Composite state builders for the Single-Family Rental Portfolio Operations API.

The harness restarts the service before every test, so each test must build all of its
preconditions through the public API.  The builders below assemble the recurring
multi-entity states -- an approved acquisition, a stabilised home, a verified prospect, a
funded draft lease -- and return the identifiers a test needs to drive its trigger.

Setup calls use the lenient ``get_success_data`` validator: a setup step that fails should
report *which* step failed, not drown the real assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    TEST_USERS,
    make_prospect_headers,
    make_vendor_headers,
    headers_without_user_id,
)

SYSTEM = TEST_USERS["system"]
ADMIN = TEST_USERS["portfolio_admin"]
ANALYST = TEST_USERS["acquisition_analyst"]
ANALYST_2 = TEST_USERS["acquisition_analyst_2"]
COMMITTEE = TEST_USERS["investment_committee"]
COMMITTEE_2 = TEST_USERS["investment_committee_2"]
OPS = TEST_USERS["operations_manager"]
VENDOR_MANAGER = TEST_USERS["vendor_manager"]
AGENT = TEST_USERS["leasing_agent"]
COMPLIANCE = TEST_USERS["compliance_officer"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2"]
DIRECTOR = TEST_USERS["regional_director"]
ANON = TEST_USERS["anonymous"]


class Ctx(dict):
    """A dict whose keys are also readable as attributes, for terse test bodies."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)

    def __setattr__(self, key, value):
        self[key] = value


# --- primitives -----------------------------------------------------------------------
def set_clock(api, instant):
    """Move the logical clock; the setter is exempt from the ``X-User-ID`` requirement."""
    return get_success_data(api.set_clock(f.clock_payload(instant), SYSTEM))


def create_market(api, payload=None, **overrides):
    """Register a market and return its resource."""
    body = payload if payload is not None else f.market_payload(**overrides)
    return get_success_data(api.create_market(body, ADMIN))


def create_scope_template(api, payload):
    """Publish a scope template and return its resource."""
    return get_success_data(api.create_scope_template(payload, ADMIN))


def create_home(api, market_id, payload=None, **overrides):
    """Register a home and return its resource (``version`` 1, ``PIPELINE``/``VACANT``)."""
    body = payload if payload is not None else f.home_payload(market_id, **overrides)
    return get_success_data(api.create_home(body, ANALYST))


def create_prospect(api, market_id, payload=None, **overrides):
    """Register a prospect (an ``Anonymous`` self-registration) and return its resource."""
    body = payload if payload is not None else f.prospect_payload(market_id, **overrides)
    return get_success_data(api.create_prospect(body, ANON))


def create_vendor(api, market_id, **overrides):
    """Register a vendor and return its resource."""
    return get_success_data(
        api.create_vendor(f.vendor_payload(market_id, **overrides), VENDOR_MANAGER)
    )


def certify_vendor(api, vendor_id, certification_code, **overrides):
    """Grant a vendor an active certification and return the certification resource."""
    return get_success_data(
        api.create_vendor_certification(
            f.vendor_certification_payload(vendor_id, certification_code, **overrides),
            VENDOR_MANAGER,
        )
    )


# --- catalogues -----------------------------------------------------------------------
def three_trade_catalogue(api):
    """Publish the paint / HVAC / flooring templates used by the underwriting example."""
    return Ctx(
        paint=create_scope_template(api, f.scope_template_paint()),
        hvac=create_scope_template(api, f.scope_template_hvac()),
        floor=create_scope_template(api, f.scope_template_floor()),
    )


def general_catalogue(api):
    """Publish the single ``GEN``-certified repaint template."""
    return Ctx(paint=create_scope_template(api, f.scope_template_general()))


# --- acquisition ----------------------------------------------------------------------
def underwrite_and_approve(api, home_id, home_version, scope_lines, **case_overrides):
    """Create, submit and approve one underwriting case, leaving the home ``ACQUIRED``.

    ``analyst-1`` submits and ``ic-1`` decides, so the segregation-of-duties control is
    satisfied by construction.
    """
    case = get_success_data(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home_id, home_version, scope_lines, **case_overrides
            ),
            ANALYST,
        )
    )
    get_success_data(api.submit_underwriting_case(case["id"], {}, ANALYST))
    get_success_data(
        api.decide_underwriting_case(case["id"], f.decision_payload("APPROVE"), COMMITTEE)
    )
    return case


def acquired_home(api, general_template=True, market_overrides=None, home_overrides=None):
    """Market + catalogue + an ``ACQUIRED`` home behind an ``APPROVED`` case.

    Returns a :class:`Ctx` carrying ``market``, ``templates``, ``home``, ``case`` and the
    identifier shortcuts ``market_id``, ``home_id``, ``case_id`` and ``paint_id``.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    market = create_market(api, **(market_overrides or {}))
    templates = general_catalogue(api) if general_template else three_trade_catalogue(api)
    home = create_home(api, market["id"], **(home_overrides or {}))
    if general_template:
        lines = [f.scope_line(templates.paint["id"], 1)]
    else:
        lines = [
            f.scope_line(templates.paint["id"], 1),
            f.scope_line(templates.hvac["id"], 1),
            f.scope_line(templates.floor["id"], 1150),
        ]
    case = underwrite_and_approve(api, home["id"], home["version"], lines)
    return Ctx(
        market=market,
        market_id=market["id"],
        templates=templates,
        paint_id=templates.paint["id"],
        home=home,
        home_id=home["id"],
        case=case,
        case_id=case["id"],
        scope_lines=lines,
    )


# --- renovation -----------------------------------------------------------------------
def renovated_home(api, general_template=True, approved_budget_cents=400000):
    """Chain S: the canonical stabilised home.

    Extends :func:`acquired_home` with a 400000-cent acquisition-renovation project, one
    300000-cent in-house paint work order, a scope lock on 2026-08-05 and completion on
    2026-09-06.  The home ends ``STABILIZED``/``VACANT`` with ``leasing_posture`` ``OPEN``,
    a ``realized_all_in_basis_cents`` of 26050000 and a realized yield of 584 bps, and the
    logical clock is left at 2026-09-06.
    """
    ctx = acquired_home(api, general_template=general_template)
    project = get_success_data(
        api.create_renovation_project(
            f.renovation_project_payload(ctx.home_id, approved_budget_cents), OPS
        )
    )
    work_order = get_success_data(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]),
            OPS,
        )
    )
    set_clock(api, "2026-08-05T00:00:00Z")
    get_success_data(api.lock_project_scope(project["id"], f.lock_scope_payload(), OPS))
    get_success_data(api.dispatch_work_order(work_order["id"], {}, OPS))
    set_clock(api, "2026-09-06T00:00:00Z")
    get_success_data(
        api.complete_work_order(
            work_order["id"],
            f.complete_work_order_payload(300000, "2026-09-06"),
            OPS,
        )
    )
    ctx.project = project
    ctx.project_id = project["id"]
    ctx.work_order = work_order
    ctx.work_order_id = work_order["id"]
    return ctx


def three_order_scope(api, approved_budget_cents=1600000):
    """An ``ACQUIRED`` home carrying a 1600000-cent project and three in-house orders.

    The order set is the one the money-ledger rules are built around: interior paint
    quoted 300000, 1300 square feet of flooring quoted 640000 and 1150 square feet quoted
    570000, so ``committed_cost_cents`` is 1510000 and ``budget_remaining_cents`` 90000
    while the project is still ``SCOPING``.  Actual costs of 310000 + 640000 + 570000 then
    give the 1520000 gross turn cost of the PRD's three worked holdback settlements.
    """
    ctx = acquired_home(api, general_template=False)
    project = get_success_data(
        api.create_renovation_project(
            f.renovation_project_payload(ctx.home_id, approved_budget_cents), OPS
        )
    )
    paint = get_success_data(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]),
            OPS,
        )
    )
    floor_a = get_success_data(
        api.create_work_order(
            f.work_order_payload(
                ctx.home_id,
                ctx.templates.floor["id"],
                quantity=1300,
                crew_size=2,
                quoted_cost_cents=640000,
                project_id=project["id"],
            ),
            OPS,
        )
    )
    floor_b = get_success_data(
        api.create_work_order(
            f.work_order_payload(
                ctx.home_id,
                ctx.templates.floor["id"],
                quantity=1150,
                crew_size=2,
                quoted_cost_cents=570000,
                project_id=project["id"],
            ),
            OPS,
        )
    )
    ctx.project = project
    ctx.project_id = project["id"]
    ctx.paint_order_id = paint["id"]
    ctx.floor_a_order_id = floor_a["id"]
    ctx.floor_b_order_id = floor_b["id"]
    return ctx


# --- leasing --------------------------------------------------------------------------
def verified_prospect(api, market_id, prospect_overrides=None, verification_overrides=None):
    """Register a prospect and carry it through one clean identity verification.

    Returns a :class:`Ctx` with ``prospect`` (as created), ``verified`` (the verification
    response body), ``prospect_id`` and ``headers`` for acting as that prospect.
    """
    prospect = create_prospect(api, market_id, **(prospect_overrides or {}))
    verified = get_success_data(
        api.verify_identity(
            prospect["id"],
            f.identity_verification_payload(
                prospect["version"], **(verification_overrides or {})
            ),
            make_prospect_headers(prospect["id"]),
        )
    )
    return Ctx(
        prospect=prospect,
        prospect_id=prospect["id"],
        verified=verified,
        headers=make_prospect_headers(prospect["id"]),
    )


def submitted_application(api, home_id, prospect_id, **overrides):
    """A prospect applies for a home; the application lands in ``SUBMITTED``."""
    return get_success_data(
        api.create_rental_application(
            f.rental_application_payload(home_id, prospect_id, **overrides),
            make_prospect_headers(prospect_id),
        )
    )


def screened_application(api, home_id, prospect_id, **overrides):
    """A submitted application that a ``LeasingAgent`` has screened.

    Screening a passing application reserves the home, so the home's
    ``occupancy_status`` becomes ``RESERVED`` on return.
    """
    application = submitted_application(api, home_id, prospect_id, **overrides)
    screened = get_success_data(
        api.screen_rental_application(application["id"], {}, AGENT)
    )
    return Ctx(
        application=application,
        application_id=application["id"],
        screened=screened,
    )


def draft_lease(api, application_id, **overrides):
    """A ``DRAFT`` lease drafted by a ``LeasingAgent`` at 208000 cents for 12 months."""
    return get_success_data(
        api.create_lease(f.lease_payload(application_id, **overrides), AGENT)
    )


def funded_draft_lease(api, application_id, deposit_cents=352500, **overrides):
    """A ``DRAFT`` lease whose ``deposit_paid_cents`` already meets the requirement."""
    lease = draft_lease(api, application_id, **overrides)
    get_success_data(
        api.pay_deposit(lease["id"], f.deposit_payment_payload(deposit_cents), AGENT)
    )
    return lease


def reserved_home(api, general_template=True):
    """Chain S extended with a verified prospect whose screened application reserved it.

    Returns the :func:`renovated_home` context plus ``prospect_id``, ``prospect_headers``,
    ``application_id`` and ``screened`` (the screening response body).
    """
    ctx = renovated_home(api, general_template=general_template)
    prospect = verified_prospect(api, ctx.market_id)
    app = screened_application(api, ctx.home_id, prospect.prospect_id)
    ctx.prospect = prospect.prospect
    ctx.prospect_id = prospect.prospect_id
    ctx.prospect_headers = prospect.headers
    ctx.application = app.application
    ctx.application_id = app.application_id
    ctx.screened = app.screened
    return ctx


def leased_home(api, general_template=True, monthly_rent_cents=208000):
    """A :func:`reserved_home` carried through a funded, executed lease.

    The home ends ``STABILIZED``/``OCCUPIED`` with ``leasing_posture`` ``OPEN``.
    """
    ctx = reserved_home(api, general_template=general_template)
    lease = funded_draft_lease(api, ctx.application_id, monthly_rent_cents=monthly_rent_cents)
    executed = get_success_data(
        api.execute_lease(lease["id"], f.execute_lease_payload(), AGENT)
    )
    ctx.lease = lease
    ctx.lease_id = lease["id"]
    ctx.executed = executed
    return ctx


# --- vendors --------------------------------------------------------------------------
def certified_vendor(api, market_id, certification_code="GEN", **vendor_overrides):
    """An ``ACTIVE`` vendor holding one active certification, with acting headers."""
    vendor = create_vendor(api, market_id, **vendor_overrides)
    certification = certify_vendor(
        api, vendor["id"], certification_code, expires_on="2027-01-01"
    )
    return Ctx(
        vendor=vendor,
        vendor_id=vendor["id"],
        certification=certification,
        headers=make_vendor_headers(vendor["id"]),
    )


def two_certified_vendors(api, market_id, certification_code="GEN"):
    """The cheap/high-quality vendor pair the ranking rule is built to separate.

    ``cheap`` carries ``cost_index_bps`` 9800 with ``quality_score_bps`` 8600, ``pricey``
    carries 10100 with 9400, so the cheaper bid wins despite the lower quality score.
    """
    cheap = certified_vendor(
        api,
        market_id,
        certification_code,
        legal_name="Peachtree Painters",
        daily_crew_capacity=10,
        cost_index_bps=9800,
        quality_score_bps=8600,
        insurance_expires_on="2027-06-30",
    )
    pricey = certified_vendor(
        api,
        market_id,
        certification_code,
        legal_name="Buckhead Finishes",
        daily_crew_capacity=10,
        cost_index_bps=10100,
        quality_score_bps=9400,
        insurance_expires_on="2027-06-30",
    )
    return Ctx(cheap=cheap, pricey=pricey)


# --- compliance -----------------------------------------------------------------------
def open_obligation(api, home_id, obligation_type="HOA_VIOLATION", severity="MINOR", **overrides):
    """Record an ``OPEN`` compliance obligation against a home."""
    return get_success_data(
        api.create_compliance_obligation(
            f.obligation_payload(home_id, obligation_type, severity, **overrides),
            COMPLIANCE,
        )
    )


def planned_obligation(api, home_id, obligation_type="HOA_VIOLATION", severity="MINOR",
                       planned_resolution_on="2026-09-30", **overrides):
    """An obligation moved ``OPEN -> PLANNED`` with a planned resolution date."""
    obligation = open_obligation(api, home_id, obligation_type, severity, **overrides)
    get_success_data(
        api.plan_obligation(
            obligation["id"], f.plan_obligation_payload(planned_resolution_on), COMPLIANCE
        )
    )
    return obligation


# --- showing calendars ----------------------------------------------------------------
def available_slot(api, home_id, **overrides):
    """Publish one ``AVAILABLE`` showing window on a home."""
    return get_success_data(
        api.create_showing_slot(f.showing_slot_payload(home_id, **overrides), AGENT)
    )


def two_available_slots(api, home_id):
    """Two non-overlapping windows, 15:00 and 17:00 on 2026-08-20."""
    first = available_slot(api, home_id)
    second = available_slot(
        api,
        home_id,
        starts_at="2026-08-20T17:00:00Z",
        ends_at="2026-08-20T17:30:00Z",
    )
    return Ctx(first=first, second=second)
