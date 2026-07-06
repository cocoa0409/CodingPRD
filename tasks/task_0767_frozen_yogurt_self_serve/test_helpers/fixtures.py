"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints and uses get_success_data() (lenient) internally so that setup
failures surface as clear "Setup failed" errors rather than confusing
assertion failures. The API server is restarted before every test, so each
helper starts against an empty database and, where the logical clock matters,
sets it explicitly.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f
from .constants import CLOCK_DEFAULT, CLOCK_FAR_FUTURE

MANAGER = TEST_USERS["manager_headers"]
SHIFTLEAD = TEST_USERS["shiftlead_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# --- clock ------------------------------------------------------------------
def set_clock(api, iso, headers=None):
    return get_success_data(api.set_clock(iso, headers or MANAGER))


# --- single-entity creators -------------------------------------------------
def make_machine(api, **overrides):
    return get_success_data(api.create_machine(f.create_machine_payload(**overrides), MANAGER))


def make_flavor(api, machine_id, **overrides):
    return get_success_data(api.create_flavor(f.create_flavor_payload(machine_id, **overrides), SHIFTLEAD))


def make_topping(api, **overrides):
    return get_success_data(api.create_topping(f.create_topping_payload(**overrides), SHIFTLEAD))


def make_promotion(api, **overrides):
    return get_success_data(api.create_promotion(f.create_promotion_payload(**overrides), MANAGER))


def make_loyalty(api, **overrides):
    return get_success_data(api.create_loyalty(f.create_loyalty_payload(**overrides), CASHIER))


def make_ticket(api, **overrides):
    return get_success_data(api.create_ticket(f.create_ticket_payload(**overrides), CASHIER))


def add_line(api, ticket_id, flavor_id, gross_weight_oz, **overrides):
    return get_success_data(
        api.add_line(ticket_id, f.add_line_payload(flavor_id, gross_weight_oz, **overrides), CASHIER))


def do_checkout(api, ticket_id, voucher_id=None):
    payload = {} if voucher_id is None else {"voucher_id": voucher_id}
    return get_success_data(api.checkout(ticket_id, payload, CASHIER))


def make_catering_resource(api, **overrides):
    return get_success_data(api.create_catering_resource(f.create_catering_resource_payload(**overrides), MANAGER))


def make_reconciliation(api, **overrides):
    return get_success_data(api.create_reconciliation(f.create_reconciliation_payload(**overrides), MANAGER))


# --- Tier 1/2: machine + flavor setup ---------------------------------------
def setup_machine_flavor(api, mix_par_oz=1000, initial_mix_oz=1000,
                         price_per_oz_cents=55, cost_per_oz_cents=20):
    """A READY machine with one LOADED flavor. Returns (machine, flavor)."""
    machine = make_machine(api, mix_par_oz=mix_par_oz, initial_mix_oz=initial_mix_oz)
    flavor = make_flavor(api, machine["id"],
                         price_per_oz_cents=price_per_oz_cents,
                         cost_per_oz_cents=cost_per_oz_cents)
    return machine, flavor


def setup_machine_out_of_service(api, num_flavors=1,
                                 price_per_oz_cents=55, cost_per_oz_cents=20):
    """Create a machine (+ flavors) at the default clock, then advance the clock
    far past any plausible cleaning interval and run check-sanitation so the
    machine is driven READY -> OUT_OF_SERVICE and its LOADED flavors cascade to
    SUSPENDED. Returns (machine_after, [flavors_before])."""
    set_clock(api, CLOCK_DEFAULT)
    machine = make_machine(api, mix_par_oz=1000, initial_mix_oz=1000)
    flavors = [make_flavor(api, machine["id"],
                           price_per_oz_cents=price_per_oz_cents,
                           cost_per_oz_cents=cost_per_oz_cents,
                           name=f"Flavor-{i}")
               for i in range(num_flavors)]
    set_clock(api, CLOCK_FAR_FUTURE)
    machine = get_success_data(api.check_sanitation(machine["id"], SHIFTLEAD))
    return machine, flavors


# --- Tier 3: charged tickets ------------------------------------------------
def setup_charged_ticket(api, gross_weight_oz=7.3, loyalty_account_id=None,
                         topping_ids=None, with_promo=False,
                         mix_par_oz=1000, initial_mix_oz=1000,
                         price_per_oz_cents=55, cost_per_oz_cents=20):
    """Machine + flavor + (optional promo/topping/loyalty) + a single-line ticket
    charged. Returns dict with machine, flavor, ticket (post-checkout), topping.

    All timestamps use the default clock so any promo created here is active."""
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(
        api, mix_par_oz=mix_par_oz, initial_mix_oz=initial_mix_oz,
        price_per_oz_cents=price_per_oz_cents, cost_per_oz_cents=cost_per_oz_cents)
    if with_promo:
        make_promotion(api)
    ticket_overrides = {}
    if loyalty_account_id is not None:
        ticket_overrides["loyalty_account_id"] = loyalty_account_id
    ticket = make_ticket(api, **ticket_overrides)
    line_overrides = {}
    if topping_ids is not None:
        line_overrides["topping_ids"] = topping_ids
    add_line(api, ticket["id"], flavor["id"], gross_weight_oz, **line_overrides)
    ticket = do_checkout(api, ticket["id"])
    return {"machine": machine, "flavor": flavor, "ticket": ticket}


def setup_ticket_ready_to_reconcile(api, gross_weight_oz=7.3, loyalty_account_id=None,
                                    with_promo=False, price_per_oz_cents=55):
    """A charged single-line ticket plus an OPEN reconciliation for the same
    business date. Returns (bundle_dict, reconciliation)."""
    bundle = setup_charged_ticket(api, gross_weight_oz=gross_weight_oz,
                                  loyalty_account_id=loyalty_account_id,
                                  with_promo=with_promo,
                                  price_per_oz_cents=price_per_oz_cents)
    recon = make_reconciliation(api)
    return bundle, recon


# --- Tier 4: loyalty punch cascade -> voucher -------------------------------
def setup_issued_voucher(api):
    """Drive the punch cascade to issue exactly one RewardVoucher: a loyalty
    account seeded at punch_count 9, one charged 7.3oz ticket attached, then a
    reconciliation close (punch 9 -> 10 crosses the threshold). Returns dict
    with loyalty, voucher, machine, flavor, reconciliation."""
    set_clock(api, CLOCK_DEFAULT)
    loyalty = make_loyalty(api, initial_punch_count=9)
    machine, flavor = setup_machine_flavor(api, mix_par_oz=2000, initial_mix_oz=2000)
    ticket = make_ticket(api, loyalty_account_id=loyalty["id"])
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    recon = make_reconciliation(api)
    get_success_data(api.close_reconciliation(recon["id"], 402, MANAGER))
    vouchers, _ = _list(api.list_vouchers(MANAGER, params={"loyalty_account_id": loyalty["id"]}))
    voucher = vouchers[0]
    return {"loyalty": loyalty, "voucher": voucher, "machine": machine,
            "flavor": flavor, "reconciliation": recon, "ticket": ticket}


# --- Catering ---------------------------------------------------------------
def setup_quoted_catering(api, line_items=None,
                          event_start="2026-03-02T10:00:00Z",
                          event_end="2026-03-02T12:00:00Z", resource=None):
    """A resource plus a DRAFT->QUOTED catering order. If `resource` is supplied,
    books against it. Returns (resource, order)."""
    if line_items is None:
        line_items = [{"qty": 1, "unit_price_cents": 1000, "discount_pct": 0}]
    if resource is None:
        resource = make_catering_resource(api)
    order = get_success_data(api.create_catering_order(
        f.create_catering_order_payload(resource["id"], line_items,
                                        event_start=event_start, event_end=event_end),
        CASHIER))
    order = get_success_data(api.quote_catering_order(order["id"], MANAGER))
    return resource, order


def setup_confirmed_catering(api, event_start="2026-03-02T10:00:00Z",
                             event_end="2026-03-02T12:00:00Z",
                             deposit_paid_cents=250, resource=None,
                             line_items=None):
    """A resource plus a QUOTED->CONFIRMED catering order. If `resource` is
    supplied, books against it (for overlap tests). Returns (resource, order)."""
    if line_items is None:
        line_items = [{"qty": 1, "unit_price_cents": 1000, "discount_pct": 0}]
    if resource is None:
        resource = make_catering_resource(api)
    order = get_success_data(api.create_catering_order(
        f.create_catering_order_payload(resource["id"], line_items,
                                        event_start=event_start, event_end=event_end),
        CASHIER))
    order = get_success_data(api.quote_catering_order(order["id"], MANAGER))
    order = get_success_data(api.confirm_catering_order(order["id"], deposit_paid_cents, MANAGER))
    return resource, order


# --- Maintenance ------------------------------------------------------------
def make_maintenance_window(api, machine_id, window_start, window_end,
                            expected_machine_version):
    return get_success_data(api.create_maintenance_window(
        f.create_maintenance_window_payload(machine_id, window_start, window_end,
                                            expected_machine_version),
        SHIFTLEAD))


def current_machine_version(api, machine_id):
    return get_success_data(api.get_machine(machine_id, SHIFTLEAD))["version"]


# --- utilities --------------------------------------------------------------
def _list(response):
    """Return (data_list, meta) from a list response, lenient about envelope."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})
