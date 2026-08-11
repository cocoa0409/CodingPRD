"""Composite setup helpers.

Every helper builds its world through the public API only. The server is
restarted with an empty database before each test, so helpers never assume any
pre-existing row and every test re-creates whatever it needs.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    CHEF_KNIFE_SPEC, SALON_SHEAR_SPEC, MANDOLINE_SPEC, DELI_SLICER_SPEC,
    GARDEN_PRUNER_SPEC, account_payload, bench_day_payload, item_class_spec_payload,
    loaner_issue_payload, loaner_unit_payload, locker_compartment_payload,
    payment_payload, plan_tier_payload, request_item_payload, route_run_payload,
    route_stop_payload, service_request_payload, subscription_payload,
    technician_payload, van_payload, warranty_claim_payload,
)
from .test_users import ADMIN, CLERK, DISPATCHER, make_account_owner_headers, make_technician_headers


# ==========================================================================
# Tier 0 -- single-call primitives
# ==========================================================================

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_spec(base=None, **overrides) -> dict:
    payload = dict(base or CHEF_KNIFE_SPEC)
    payload.update(overrides)
    return get_success_data(api_client.create_item_class_spec(payload, ADMIN))


def create_chef_knife_spec(**overrides) -> dict:
    return create_spec(CHEF_KNIFE_SPEC, **overrides)


def create_salon_shear_spec(**overrides) -> dict:
    return create_spec(SALON_SHEAR_SPEC, **overrides)


def create_mandoline_spec(**overrides) -> dict:
    return create_spec(MANDOLINE_SPEC, **overrides)


def create_deli_slicer_spec(**overrides) -> dict:
    return create_spec(DELI_SLICER_SPEC, **overrides)


def create_garden_pruner_spec(**overrides) -> dict:
    return create_spec(GARDEN_PRUNER_SPEC, **overrides)


def create_plan_tier(**overrides) -> dict:
    return get_success_data(api_client.create_plan_tier(plan_tier_payload(**overrides), ADMIN))


def create_account(**overrides) -> dict:
    return get_success_data(api_client.create_account(account_payload(**overrides), ADMIN))


def create_technician(**overrides) -> dict:
    return get_success_data(api_client.create_technician(technician_payload(**overrides), ADMIN))


def create_van(**overrides) -> dict:
    return get_success_data(api_client.create_van(van_payload(**overrides), ADMIN))


def create_bench_day(**overrides) -> dict:
    return get_success_data(api_client.create_bench_day(bench_day_payload(**overrides), ADMIN))


def create_compartment(**overrides) -> dict:
    return get_success_data(
        api_client.create_locker_compartment(locker_compartment_payload(**overrides), ADMIN))


def create_subscription(account_id, plan_tier_id, **overrides) -> dict:
    return get_success_data(api_client.create_subscription(
        subscription_payload(account_id, plan_tier_id, **overrides),
        make_account_owner_headers(account_id)))


def create_service_request(account_id, **overrides) -> dict:
    return get_success_data(api_client.create_service_request(
        service_request_payload(account_id, **overrides),
        make_account_owner_headers(account_id)))


def add_item(request_id, account_id, spec_id, item_class="CHEF_KNIFE",
             declared_damage_tier="ROUTINE_HONE", **overrides) -> dict:
    return get_success_data(api_client.add_request_item(
        request_id,
        request_item_payload(spec_id, item_class, declared_damage_tier, **overrides),
        make_account_owner_headers(account_id)))


def submit_request(request_id, account_id) -> dict:
    return get_success_data(
        api_client.submit_service_request(request_id, make_account_owner_headers(account_id)))


def create_run(van_id, technician_id, **overrides) -> dict:
    return get_success_data(api_client.create_route_run(
        route_run_payload(van_id, technician_id, **overrides), DISPATCHER))


def read_run(run_id) -> dict:
    return get_success_data(api_client.get_route_run(run_id, DISPATCHER))


def add_stop(run_id, service_request_id, sequence=1, arrival_window_start="09:00",
             expected_route_run_version=None, **overrides) -> dict:
    if expected_route_run_version is None:
        expected_route_run_version = read_run(run_id)["version"]
    return get_success_data(api_client.add_route_stop(
        run_id,
        route_stop_payload(service_request_id, expected_route_run_version,
                           sequence, arrival_window_start, **overrides),
        DISPATCHER))


def dispatch_run(run_id) -> dict:
    return get_success_data(api_client.dispatch_route_run(run_id, DISPATCHER))


def arrive_stop(stop_id, technician_id) -> dict:
    return get_success_data(
        api_client.arrive_route_stop(stop_id, make_technician_headers(technician_id)))


def pickup(request_id, technician_id) -> dict:
    return get_success_data(
        api_client.pickup_service_request(request_id, make_technician_headers(technician_id)))


def bench_intake(request_id, bench_day_id, technician_id) -> dict:
    return get_success_data(api_client.bench_intake_service_request(
        request_id, {"bench_day_id": bench_day_id}, make_technician_headers(technician_id)))


def assess_item(item_id, assessed_damage_tier, technician_id) -> dict:
    return get_success_data(api_client.assess_request_item(
        item_id, {"assessed_damage_tier": assessed_damage_tier},
        make_technician_headers(technician_id)))


def start_work(item_id, technician_id) -> dict:
    return get_success_data(
        api_client.start_work_request_item(item_id, make_technician_headers(technician_id)))


def complete_work(item_id, technician_id) -> dict:
    return get_success_data(
        api_client.complete_work_request_item(item_id, make_technician_headers(technician_id)))


def deliver_request(request_id, technician_id) -> dict:
    return get_success_data(
        api_client.deliver_service_request(request_id, make_technician_headers(technician_id)))


def locker_assign(request_id, account_id) -> dict:
    return get_success_data(api_client.locker_assign_service_request(
        request_id, make_account_owner_headers(account_id)))


def locker_deposit(compartment_id, access_code, account_id) -> dict:
    return get_success_data(api_client.deposit_locker_compartment(
        compartment_id, {"access_code": access_code}, make_account_owner_headers(account_id)))


def locker_release(compartment_id, access_code, account_id) -> dict:
    return get_success_data(api_client.release_locker_compartment(
        compartment_id, {"access_code": access_code}, make_account_owner_headers(account_id)))


def create_loaner_unit(spec_id, grade="STANDARD", **overrides) -> dict:
    return get_success_data(
        api_client.create_loaner_unit(loaner_unit_payload(spec_id, grade, **overrides), ADMIN))


def issue_loaner(request_id, spec_id, technician_id, requested_grade="STANDARD") -> dict:
    return get_success_data(api_client.create_loaner_issue(
        loaner_issue_payload(request_id, spec_id, requested_grade),
        make_technician_headers(technician_id)))


def return_loaner(issue_id, technician_id, damage_reported=False) -> dict:
    return get_success_data(api_client.return_loaner_issue(
        issue_id, {"damage_reported": damage_reported}, make_technician_headers(technician_id)))


def create_claim(item_id, account_id, reason="Edge rolled after two days") -> dict:
    return get_success_data(api_client.create_warranty_claim(
        warranty_claim_payload(item_id, reason), make_account_owner_headers(account_id)))


def approve_claim(claim_id, technician_id) -> dict:
    return get_success_data(
        api_client.approve_warranty_claim(claim_id, make_technician_headers(technician_id)))


def deny_claim(claim_id, technician_id, abuse_finding=True) -> dict:
    return get_success_data(api_client.deny_warranty_claim(
        claim_id, {"abuse_finding": abuse_finding}, make_technician_headers(technician_id)))


def resubmit_claim(claim_id, account_id) -> dict:
    return get_success_data(
        api_client.resubmit_warranty_claim(claim_id, make_account_owner_headers(account_id)))


def create_invoice(account_id, service_request_id=None, billing_period=None) -> dict:
    payload = {"account_id": account_id}
    if service_request_id is not None:
        payload["service_request_id"] = service_request_id
    if billing_period is not None:
        payload["billing_period"] = billing_period
    return get_success_data(api_client.create_invoice(payload, CLERK))


def issue_invoice(invoice_id) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, CLERK))


def void_invoice(invoice_id) -> dict:
    return get_success_data(api_client.void_invoice(invoice_id, CLERK))


def pay_invoice(invoice_id, amount_cents, expected_invoice_version, account_id=None,
                method="CARD") -> dict:
    headers = make_account_owner_headers(account_id) if account_id else CLERK
    return get_success_data(api_client.create_payment(
        invoice_id, payment_payload(amount_cents, expected_invoice_version, method), headers))


# ==========================================================================
# Readers
# ==========================================================================

def read_account(account_id) -> dict:
    return get_success_data(api_client.get_account(account_id, ADMIN))


def read_subscription(subscription_id) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def read_request(request_id) -> dict:
    return get_success_data(api_client.get_service_request(request_id, ADMIN))


def read_item(item_id) -> dict:
    return get_success_data(api_client.get_request_item(item_id, ADMIN))


def read_stop(stop_id) -> dict:
    return get_success_data(api_client.get_route_stop(stop_id, DISPATCHER))


def read_compartment(compartment_id) -> dict:
    return get_success_data(api_client.get_locker_compartment(compartment_id, ADMIN))


def read_bench_day(bench_day_id) -> dict:
    return get_success_data(api_client.get_bench_day(bench_day_id, ADMIN))


def read_loaner_unit(unit_id) -> dict:
    return get_success_data(api_client.get_loaner_unit(unit_id, ADMIN))


def read_loaner_issue(issue_id) -> dict:
    return get_success_data(api_client.get_loaner_issue(issue_id, ADMIN))


def read_claim(claim_id) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, ADMIN))


def read_invoice(invoice_id) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, CLERK))


def read_statement(account_id) -> dict:
    return get_success_data(api_client.get_account_statement(account_id, CLERK))


def list_invoice_lines(invoice_id) -> list:
    return get_success_data(api_client.list_invoice_lines_of_invoice(invoice_id, CLERK))


def list_lines_by_claim(claim_id) -> list:
    return get_success_data(
        api_client.list_invoice_lines(CLERK, params={"source_warranty_claim_id": claim_id}))


def list_allowance_entries(subscription_id) -> list:
    return get_success_data(
        api_client.list_allowance_entries(ADMIN, params={"subscription_id": subscription_id}))


def list_items_of_request(request_id) -> list:
    return get_success_data(
        api_client.list_request_items(ADMIN, params={"service_request_id": request_id}))


def list_stops_of_run(run_id) -> list:
    return get_success_data(
        api_client.list_route_stops(DISPATCHER, params={"route_run_id": run_id}))


def find_draft_invoice(account_id) -> dict:
    rows = get_success_data(
        api_client.list_invoices(CLERK, params={"account_id": account_id, "status": "DRAFT"}))
    assert rows, f"expected a DRAFT invoice on account {account_id}, found none"
    return rows[0]


# ==========================================================================
# Tier 1 -- reference-data worlds
# ==========================================================================

_SPEC_BUILDERS = {
    "CHEF_KNIFE": create_chef_knife_spec,
    "SALON_SHEAR": create_salon_shear_spec,
    "MANDOLINE_BLADE": create_mandoline_spec,
    "DELI_SLICER_BLADE": create_deli_slicer_spec,
    "GARDEN_PRUNER": create_garden_pruner_spec,
}


def build_config(specs=("CHEF_KNIFE",), spec_overrides=None, account_kwargs=None,
                 tech_certs=None, second_technician=False, with_van=True,
                 van_kwargs=None, with_bench=True, bench_kwargs=None,
                 plan_tier_kwargs=None):
    """Lay down the reference data a customer flow needs.

    Returns a dict carrying `specs` (keyed by item_class), `account`, `tech`,
    optionally `tech_b`, `van`, `bench` and `tier`.
    """
    spec_overrides = spec_overrides or {}
    world = {"specs": {}}
    for item_class in specs:
        world["specs"][item_class] = _SPEC_BUILDERS[item_class](
            **spec_overrides.get(item_class, {}))
    if plan_tier_kwargs is not None:
        world["tier"] = create_plan_tier(**plan_tier_kwargs)
    world["account"] = create_account(**(account_kwargs or {}))
    world["tech"] = create_technician(certifications=list(tech_certs or []))
    if second_technician:
        world["tech_b"] = create_technician(full_name="Ben Steel", certifications=list(tech_certs or []))
    if with_van:
        world["van"] = create_van(**(van_kwargs or {}))
    if with_bench:
        world["bench"] = create_bench_day(**(bench_kwargs or {}))
    return world


def stage_request(world, items, submit=True, **request_kwargs):
    """Create a service request on `world["account"]`, add `items`, optionally submit.

    `items` is a list of (item_class, declared_damage_tier) pairs.
    Returns (request, [item, ...]).
    """
    account_id = world["account"]["id"]
    request = create_service_request(account_id, **request_kwargs)
    created = []
    for item_class, tier in items:
        created.append(add_item(request["id"], account_id,
                                world["specs"][item_class]["id"], item_class, tier))
    if submit:
        request = submit_request(request["id"], account_id)
    return request, created


# ==========================================================================
# Tier 2 -- van route progression
# ==========================================================================

def route_to_van(world, request_id, sequence=1, arrival_window_start="09:00", **run_kwargs):
    """Plan a fresh run, place the request on it, dispatch, arrive and pick the items up.

    Leaves every item in VAN custody and the request IN_SERVICE.
    Returns (run, stop). A run carrying several requests must be built stop by stop with
    `add_stop` and dispatched once, because a stop can only be added to a PLANNED run.
    """
    run = create_run(world["van"]["id"], world["tech"]["id"], **run_kwargs)
    stop = add_stop(run["id"], request_id, sequence=sequence,
                    arrival_window_start=arrival_window_start)
    dispatch_run(run["id"])
    arrive_stop(stop["id"], world["tech"]["id"])
    pickup(request_id, world["tech"]["id"])
    return read_run(run["id"]), read_stop(stop["id"])


def route_to_bench(world, request_id, sequence=1, arrival_window_start="09:00", **run_kwargs):
    """As `route_to_van`, then book the request onto `world["bench"]`.

    Leaves every item in BENCH custody at service_status INTAKE_PENDING.
    """
    run, stop = route_to_van(world, request_id, sequence, arrival_window_start, **run_kwargs)
    bench_intake(request_id, world["bench"]["id"], world["tech"]["id"])
    return read_run(run["id"]), read_stop(stop["id"])


def work_and_deliver(world, request_id, item_ids, assessed_tiers, technician_id=None):
    """Assess, start, complete every named item and then deliver the request."""
    technician_id = technician_id or world["tech"]["id"]
    for item_id, tier in zip(item_ids, assessed_tiers):
        assess_item(item_id, tier, technician_id)
    for item_id in item_ids:
        start_work(item_id, technician_id)
        complete_work(item_id, technician_id)
    return deliver_request(request_id, technician_id)


def setup_delivered_van_visit(items=(("CHEF_KNIFE", "ROUTINE_HONE"),), assessed_tiers=None,
                              world=None, request_kwargs=None, **config_kwargs):
    """Full van-route pipeline: config, request, route, bench, work, delivery.

    Returns (world, request, [item, ...]).
    """
    world = world or build_config(**config_kwargs)
    request, created = stage_request(world, list(items), **(request_kwargs or {}))
    route_to_bench(world, request["id"])
    tiers = list(assessed_tiers) if assessed_tiers else [t for _, t in items]
    work_and_deliver(world, request["id"], [i["id"] for i in created], tiers)
    return world, read_request(request["id"]), [read_item(i["id"]) for i in created]


# ==========================================================================
# Tier 3 -- locker progression
# ==========================================================================

def setup_locker_request(world, items, site_code="SITE-A", **request_kwargs):
    """Create and submit a LOCKER-channel request at `site_code`."""
    request_kwargs.setdefault("channel", "LOCKER")
    request_kwargs.setdefault("locker_site_code", site_code)
    return stage_request(world, list(items), **request_kwargs)


def setup_locker_deposited(world, items, site_code="SITE-A", **request_kwargs):
    """Submit a locker request, assign a compartment and deposit into it.

    Returns (request, [item, ...], compartment, access_code).
    """
    request, created = setup_locker_request(world, items, site_code, **request_kwargs)
    compartment = locker_assign(request["id"], world["account"]["id"])
    access_code = compartment["access_code"]
    locker_deposit(compartment["id"], access_code, world["account"]["id"])
    return read_request(request["id"]), created, read_compartment(compartment["id"]), access_code


def setup_locker_delivered(world, items, assessed_tiers=None, site_code="SITE-A",
                           **request_kwargs):
    """Locker request taken to the bench, worked and delivered back into the compartment."""
    request, created, compartment, access_code = setup_locker_deposited(
        world, items, site_code, **request_kwargs)
    bench_intake(request["id"], world["bench"]["id"], world["tech"]["id"])
    tiers = list(assessed_tiers) if assessed_tiers else [t for _, t in items]
    work_and_deliver(world, request["id"], [i["id"] for i in created], tiers)
    return (read_request(request["id"]), [read_item(i["id"]) for i in created],
            read_compartment(compartment["id"]), access_code)


# ==========================================================================
# Tier 4 -- money worlds
# ==========================================================================

def setup_cadence_upgrade_invoice(issue=True, account_kwargs=None, tier_kwargs=None):
    """MONTHLY subscription anchored 2026-06-01 upgraded to WEEKLY on the default clock.

    The upgrade appends a proration line to a freshly minted DRAFT invoice.
    Returns (account, subscription, invoice).
    """
    tier = create_plan_tier(**(tier_kwargs or {}))
    account = create_account(**(account_kwargs or {}))
    subscription = create_subscription(account["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-06-01")
    get_success_data(api_client.change_subscription_cadence(
        subscription["id"],
        {"cadence": "WEEKLY", "expected_subscription_version": subscription["version"]},
        make_account_owner_headers(account["id"])))
    invoice = find_draft_invoice(account["id"])
    if issue:
        invoice = issue_invoice(invoice["id"])
    return read_account(account["id"]), read_subscription(subscription["id"]), invoice


def setup_paused_credit_invoice(anchor_date="2026-05-01", account_kwargs=None, tier_kwargs=None):
    """Pause a subscription on the first day of its cycle, minting a full-fee credit memo.

    Returns (account, subscription, draft_invoice).
    """
    tier = create_plan_tier(**(tier_kwargs or {}))
    account = create_account(**(account_kwargs or {}))
    subscription = create_subscription(account["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date=anchor_date)
    get_success_data(api_client.pause_subscription(
        subscription["id"], make_account_owner_headers(account["id"])))
    return (read_account(account["id"]), read_subscription(subscription["id"]),
            find_draft_invoice(account["id"]))


def setup_claim_ready(declared_tier="ROUTINE_HONE", assessed_tier=None, invoice_and_issue=True,
                      subscription=None, **config_kwargs):
    """A delivered item assessed by technician A, optionally invoiced, with a SUBMITTED claim.

    Technician B (`world["tech_b"]`) has not touched the item and may adjudicate.
    Returns (world, request, item, claim, invoice_or_None).
    """
    config_kwargs.setdefault("second_technician", True)
    world = build_config(**config_kwargs)
    request_kwargs = {"subscription_id": subscription} if subscription else {}
    request, created = stage_request(world, [("CHEF_KNIFE", declared_tier)], **request_kwargs)
    route_to_bench(world, request["id"])
    work_and_deliver(world, request["id"], [created[0]["id"]],
                     [assessed_tier or declared_tier])
    invoice = None
    if invoice_and_issue:
        invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
        invoice = issue_invoice(invoice["id"])
    claim = create_claim(created[0]["id"], world["account"]["id"])
    return world, read_request(request["id"]), read_item(created[0]["id"]), claim, invoice
