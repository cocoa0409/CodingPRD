"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so every test
starts against an empty database). Setup calls use get_success_data() so a
broken precondition surfaces as a clear "Setup failed" error.

Identity threading: DealerPrincipal is entity-backed — every ownership-gated
call uses make_dealer_principal_headers(dealer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client as _api
from .constants import (
    CANONICAL_OPTION_BALLAST,
    CANONICAL_OPTION_TOWER,
    DEFAULT_CLOCK_ISO,
    REQUIRED_BALLAST,
    REQUIRED_NO_OPTIONS,
    REQUIRED_TOWER,
    REQUIRED_TOWER_BALLAST,
    SAFE_DEPOSIT_CENTS,
)
from .test_users import (
    TEST_USERS,
    make_dealer_principal_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
ALLOC = TEST_USERS["allocation_manager_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators
# ---------------------------------------------------------------------------

def create_model(api=_api, **overrides):
    """POST /boat-models as SystemAdmin; returns the created BoatModel."""
    resp = api.create_boat_model(factories.create_boat_model_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_option(api=_api, model_id=None, **overrides):
    """POST /option-packages as SystemAdmin; returns the created OptionPackage."""
    resp = api.create_option_package(
        factories.create_option_package_payload(model_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_dealer(api=_api, **overrides):
    """POST /dealers as AllocationManager; returns the created Dealer."""
    resp = api.create_dealer(factories.create_dealer_payload(**overrides), ALLOC)
    return get_success_data(resp)


def create_show(api=_api, **overrides):
    """POST /boat-show-events as AllocationManager; returns the created show."""
    resp = api.create_boat_show_event(
        factories.create_boat_show_event_payload(**overrides), ALLOC
    )
    return get_success_data(resp)


def create_run(api=_api, **overrides):
    """POST /production-runs as ProductionPlanner; returns the created run."""
    resp = api.create_production_run(
        factories.create_production_run_payload(**overrides),
        TEST_USERS["production_planner_headers"],
    )
    return get_success_data(resp)


def create_slot(api=_api, run_id=None, **overrides):
    """POST /build-slots as ProductionPlanner; returns the created BuildSlot."""
    resp = api.create_build_slot(
        factories.create_build_slot_payload(run_id, **overrides),
        TEST_USERS["production_planner_headers"],
    )
    return get_success_data(resp)


def set_clock(api, to_iso8601):
    """Advance the server logical clock (SystemAdmin-only, PRD §2.5)."""
    resp = api.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


def get_dealer(api, dealer_id):
    return get_success_data(api.get_dealer(dealer_id, ANY))


def get_order(api, order_id):
    return get_success_data(api.get_dealer_order(order_id, ANY))


def get_slot(api, slot_id):
    return get_success_data(api.get_build_slot(slot_id, ANY))


def get_run(api, run_id):
    return get_success_data(api.get_production_run(run_id, ANY))


def get_hull(api, hull_id):
    return get_success_data(api.get_hull(hull_id, ANY))


def get_campaign_by_id(api, campaign_id):
    """Fetch one campaign via the list channel filtered by nothing; PRD §4
    exposes no GET /recall-campaigns/{id}, so read through the list."""
    data, _meta = _list(api.list_recall_campaigns(ANY))
    for row in data:
        if row["id"] == campaign_id:
            return row
    raise AssertionError(f"Setup failed: campaign {campaign_id} not in list")


def _list(resp):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(resp)


def list_notices(api, **params):
    data, _meta = _list(api.list_recall_notices(ANY, params=params or None))
    return data


def list_advances(api, **params):
    data, _meta = _list(api.list_floor_plan_advances(ANY, params=params or None))
    return data


# ---------------------------------------------------------------------------
# Tier 1: bookable world (catalog + dealer + run + slot)
# ---------------------------------------------------------------------------

def setup_bookable_world(
    api=_api,
    *,
    standing="STANDARD",
    quota=5,
    floor_plan_limit_cents=10000000,
    capacity_hours=200,
    season="PEAK",
    with_options=True,
    plant_line_code=None,
):
    """Model SP190 (+ canonical WAKE-TOWER / BALLAST options), dealer, run, slot.

    Returns dict(model, tower, ballast, dealer, run, slot). tower/ballast are
    None when with_options=False.
    """
    model = create_model(api)
    tower = ballast = None
    if with_options:
        tower = create_option(api, model["id"], **CANONICAL_OPTION_TOWER)
        ballast = create_option(api, model["id"], **CANONICAL_OPTION_BALLAST)
    dealer = create_dealer(
        api,
        standing=standing,
        annual_allocation_quota=quota,
        floor_plan_limit_cents=floor_plan_limit_cents,
    )
    run_overrides = {"season": season}
    if plant_line_code:
        run_overrides["plant_line_code"] = plant_line_code
    run = create_run(api, **run_overrides)
    slot = create_slot(api, run["id"], slot_code="S1", capacity_hours=capacity_hours)
    return {
        "model": model,
        "tower": tower,
        "ballast": ballast,
        "dealer": dealer,
        "run": run,
        "slot": slot,
    }


# ---------------------------------------------------------------------------
# Tier 2: order lifecycle
# ---------------------------------------------------------------------------

def book_order(
    api,
    dealer,
    model,
    *,
    option_ids=(),
    deposit_paid_cents=None,
    source="RETAIL",
    slot_id=None,
    show_event_id=None,
):
    """POST /dealer-orders as the dealer's own principal; returns the order.

    deposit_paid_cents defaults to a value comfortably above any required
    deposit the canonical price range produces; pricing tests pass an exact
    deposit instead.
    """
    payload = factories.create_dealer_order_payload(
        dealer["id"],
        model["id"],
        source=source,
        deposit_paid_cents=(
            SAFE_DEPOSIT_CENTS if deposit_paid_cents is None else deposit_paid_cents
        ),
        option_package_ids=list(option_ids),
    )
    if slot_id is not None:
        payload["slot_id"] = slot_id
    if show_event_id is not None:
        payload["show_event_id"] = show_event_id
    resp = api.create_dealer_order(
        payload, make_dealer_principal_headers(dealer["id"])
    )
    return get_success_data(resp)


def confirm_order(api, order, dealer):
    """POST /dealer-orders/{id}/confirm; returns the COMMITTED order."""
    resp = api.confirm_dealer_order(
        order["id"], make_dealer_principal_headers(dealer["id"])
    )
    return get_success_data(resp)


def cancel_order(api, order, dealer):
    """POST /dealer-orders/{id}/cancel; returns the CANCELLED order."""
    resp = api.cancel_dealer_order(
        order["id"], make_dealer_principal_headers(dealer["id"])
    )
    return get_success_data(resp)


def amend_order(api, order, dealer, **amendments):
    """PATCH /dealer-orders/{id}; returns the amended order."""
    payload = factories.create_amend_order_payload(order["version"], **amendments)
    resp = api.amend_dealer_order(
        order["id"], payload, make_dealer_principal_headers(dealer["id"])
    )
    return get_success_data(resp)


# Canonical option-set shortcuts (deposit figures match the pinned rounding
# order of PRD §3.4 for a STANDARD dealer booking RETAIL). A caller may
# override the deposit via the deposit_paid_cents keyword.
def book_order_no_options(api, dealer, model, *, slot_id=None, source="RETAIL", **kw):
    kw.setdefault("deposit_paid_cents", REQUIRED_NO_OPTIONS)
    return book_order(
        api, dealer, model, option_ids=[], slot_id=slot_id, source=source, **kw
    )


def book_order_tower(api, dealer, model, tower, *, slot_id=None, **kw):
    kw.setdefault("deposit_paid_cents", REQUIRED_TOWER)
    return book_order(
        api, dealer, model, option_ids=[tower["id"]], slot_id=slot_id, **kw
    )


def book_order_tower_ballast(api, dealer, model, tower, ballast, *, slot_id=None, **kw):
    kw.setdefault("deposit_paid_cents", REQUIRED_TOWER_BALLAST)
    return book_order(
        api, dealer, model, option_ids=[tower["id"], ballast["id"]],
        slot_id=slot_id, **kw
    )


def book_order_ballast(api, dealer, model, ballast, *, slot_id=None, **kw):
    kw.setdefault("deposit_paid_cents", REQUIRED_BALLAST)
    return book_order(
        api, dealer, model, option_ids=[ballast["id"]], slot_id=slot_id, **kw
    )


# ---------------------------------------------------------------------------
# Tier 3: hull lifecycle
# ---------------------------------------------------------------------------

def create_hull(api, order_id, planner_user_id="planner-1"):
    """POST /hulls as ProductionPlanner; returns the UNCERTIFIED/AT_PLANT hull."""
    from .test_users import make_production_planner_headers

    resp = api.create_hull(
        factories.create_hull_payload(order_id),
        make_production_planner_headers(planner_user_id),
    )
    return get_success_data(resp)


def certify_hull(api, hull_id, certifier_user_id="officer-9"):
    """POST /hulls/{id}/certify as a ComplianceOfficer distinct from creator."""
    from .test_users import make_compliance_officer_headers

    resp = api.certify_hull(
        hull_id, make_compliance_officer_headers(certifier_user_id)
    )
    return get_success_data(resp)


def deliver_hull(api, hull_id, planner_user_id="planner-1"):
    """POST /hulls/{id}/deliver as ProductionPlanner; returns the DELIVERED hull."""
    from .test_users import make_production_planner_headers

    resp = api.deliver_hull(
        hull_id, make_production_planner_headers(planner_user_id)
    )
    return get_success_data(resp)


def setup_committed_hull(
    api=_api,
    *,
    planner_user_id="planner-1",
    option_set="none",
    **world_overrides,
):
    """Book -> confirm -> report production completion.

    Returns dict(world..., order, hull) with hull UNCERTIFIED / AT_PLANT and
    the order IN_PRODUCTION. option_set: "none" | "tower" | "tower_ballast".
    """
    world = setup_bookable_world(api, **world_overrides)
    book = {
        "none": book_order_no_options,
        "tower": book_order_tower,
        "tower_ballast": book_order_tower_ballast,
    }[option_set]
    args = [world["dealer"], world["model"]]
    if option_set == "tower":
        args.append(world["tower"])
    elif option_set == "tower_ballast":
        args += [world["tower"], world["ballast"]]
    order = book(api, *args, slot_id=world["slot"]["id"])
    order = confirm_order(api, order, world["dealer"])
    hull = create_hull(api, order["id"], planner_user_id)
    return {**world, "order": order, "hull": hull}


def setup_certified_hull(api=_api, *, certifier_user_id="officer-9", **kw):
    """Committed order + certified hull (CERTIFIED / AT_PLANT)."""
    world = setup_committed_hull(api, **kw)
    hull = certify_hull(api, world["hull"]["id"], certifier_user_id)
    return {**world, "hull": hull}


def setup_delivered_hull(
    api=_api,
    *,
    deliver_clock="2026-08-02T00:00:00Z",
    certifier_user_id="officer-9",
    **kw,
):
    """Full lifecycle through delivery: hull DELIVERED, order DELIVERED, and
    the opened floor-plan advance fetched via its hull reverse channel.

    Returns dict(world..., order, hull, advance).
    """
    world = setup_certified_hull(api, certifier_user_id=certifier_user_id, **kw)
    if deliver_clock is not None:
        set_clock(api, deliver_clock)
    hull = deliver_hull(api, world["hull"]["id"])
    order = get_order(api, world["order"]["id"])
    advances = list_advances(api, hull_id=hull["id"])
    assert len(advances) == 1, "Setup failed: expected exactly one advance per hull"
    return {**world, "order": order, "hull": hull, "advance": advances[0]}


# ---------------------------------------------------------------------------
# Tier 4: warranty & recall
# ---------------------------------------------------------------------------

def setup_registered_hull(
    api=_api,
    *,
    sale_date="2026-08-02",
    deliver_clock="2026-08-02T00:00:00Z",
    **kw,
):
    """Delivered hull plus its retail registration (order RETAILED).

    Returns dict(world..., order, hull, advance, registration).
    """
    world = setup_delivered_hull(api, deliver_clock=deliver_clock, **kw)
    resp = api.create_warranty_registration(
        factories.create_warranty_registration_payload(
            world["hull"]["id"], world["dealer"]["id"], sale_date
        ),
        make_dealer_principal_headers(world["dealer"]["id"]),
    )
    registration = get_success_data(resp)
    order = get_order(api, world["order"]["id"])
    return {**world, "order": order, "registration": registration}


def create_campaign(api=_api, **overrides):
    """POST /recall-campaigns as ComplianceOfficer; returns the DRAFT campaign."""
    resp = api.create_recall_campaign(
        factories.create_recall_campaign_payload(**overrides),
        TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(resp)


def issue_campaign(api, campaign_id):
    """POST /recall-campaigns/{id}/issue; returns the issued campaign."""
    resp = api.issue_recall_campaign(
        campaign_id, TEST_USERS["compliance_officer_headers"]
    )
    return get_success_data(resp)


def setup_issued_campaign(api, world, *, serial_start=1, serial_end=5, **overrides):
    """Draft + issue a campaign against the world's model; returns
    (campaign, notices) with notices fetched via the list channel."""
    campaign = create_campaign(
        api,
        model_code=world["model"]["model_code"],
        model_year=world["model"]["model_year"],
        hin_serial_start=serial_start,
        hin_serial_end=serial_end,
        **overrides,
    )
    campaign = issue_campaign(api, campaign["id"])
    notices = list_notices(api, campaign_id=campaign["id"])
    return campaign, notices


def remedy_notice(api, notice_id):
    """POST /recall-notices/{id}/remedy as ComplianceOfficer (plant path)."""
    resp = api.remedy_recall_notice(
        notice_id, TEST_USERS["compliance_officer_headers"]
    )
    return get_success_data(resp)


def submit_claim(api, registration_id, dealer, **overrides):
    """POST /warranty-claims as the registration's owning principal."""
    resp = api.create_warranty_claim(
        factories.create_warranty_claim_payload(registration_id, **overrides),
        make_dealer_principal_headers(dealer["id"]),
    )
    return get_success_data(resp)


def approve_claim(api, claim_id):
    resp = api.approve_warranty_claim(
        claim_id, TEST_USERS["warranty_administrator_headers"]
    )
    return get_success_data(resp)


def reject_claim(api, claim_id):
    resp = api.reject_warranty_claim(
        claim_id, TEST_USERS["warranty_administrator_headers"]
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: floor-plan settlement
# ---------------------------------------------------------------------------

def curtail(api, dealer_id, amount_cents):
    """POST /dealers/{id}/curtailments with the dealer's current version read
    fresh first; returns the updated Dealer."""
    dealer = get_dealer(api, dealer_id)
    payload = factories.create_curtailment_payload(dealer["version"], amount_cents)
    resp = api.post_curtailment(
        dealer_id, payload, make_dealer_principal_headers(dealer_id)
    )
    return get_success_data(resp)
