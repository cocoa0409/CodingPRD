"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the server before each test, so each test
starts against an empty database with the logical clock at its default instant.

All setup calls go through `get_success_data`, so a broken precondition reports
as a clear "Setup step failed" rather than as a confusing assertion later.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_AT_CUTOFF,
    CLOCK_AT_HANDOFF,
    CLOCK_AT_PRODUCTION,
    CLOCK_ORDERING_TIME,
)
from .factories import (
    create_baker_payload,
    create_cookie_payload,
    create_customer_payload,
    create_cycle_payload,
    create_delivery_route_payload,
    create_ingredient_lot_payload,
    create_label_payload,
    create_loaf_payload,
    create_offer_window_payload,
    create_order_line_payload,
    create_order_payload,
    create_payment_payload,
    create_recipe_component_payload,
    create_recipe_payload,
    create_refund_payload,
    create_review_payload,
    create_scone_payload,
    create_subscription_payload,
)
from .test_users import ADMIN, make_baker_headers, make_customer_headers


class Scenario(dict):
    """Dict with attribute access, so tests can read `s.window_id`."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ─── Primitives ──────────────────────────────────────────────────────────────

def set_clock(to_iso8601):
    """Move the logical clock; mutates no entity."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def sweep_holds(offer_window_id=None):
    payload = {"offer_window_id": offer_window_id} if offer_window_id else {}
    return get_success_data(api_client.expire_due_holds(ADMIN, payload))


def read_window(window_id, headers):
    return get_success_data(api_client.get_offer_window(window_id, headers))


def window_version(window_id, headers):
    return read_window(window_id, headers)["version"]


def read_capacity(window_id, headers):
    return get_success_data(api_client.get_offer_window_capacity(window_id, headers))


def read_order(order_id, headers):
    return get_success_data(api_client.get_order(order_id, headers))


def order_version(order_id, headers):
    return read_order(order_id, headers)["version"]


def read_recipe(recipe_id, headers):
    return get_success_data(api_client.get_recipe(recipe_id, headers))


def recipe_version(recipe_id, headers):
    return read_recipe(recipe_id, headers)["version"]


def read_subscription(subscription_id, headers):
    return get_success_data(api_client.get_subscription(subscription_id, headers))


def subscription_version(subscription_id, headers):
    return read_subscription(subscription_id, headers)["version"]


def read_line(order_line_id, headers):
    return get_success_data(api_client.get_order_line(order_line_id, headers))


def read_batch(batch_id, headers):
    return get_success_data(api_client.get_batch(batch_id, headers))


def read_label(label_id, headers):
    return get_success_data(api_client.get_label(label_id, headers))


def read_cycle(cycle_id, headers):
    return get_success_data(api_client.get_subscription_cycle(cycle_id, headers))


def read_payment(payment_id, headers):
    return get_success_data(api_client.get_payment(payment_id, headers))


def read_menu_item(menu_item_id, headers):
    return get_success_data(api_client.get_menu_item(menu_item_id, headers))


def read_compliance(baker_id, headers):
    return get_success_data(api_client.get_baker_compliance(baker_id, headers))


def read_customer(customer_id, headers):
    return get_success_data(api_client.get_customer(customer_id, headers))


def read_review(review_id, headers):
    return get_success_data(api_client.get_review(review_id, headers))


def list_data(response):
    return get_success_data(response)


def lines_of(order_id, headers):
    return get_success_data(
        api_client.list_order_lines(headers, {"order_id": order_id, "limit": 100})
    )


def movements_of(headers, **filters):
    filters.setdefault("limit", 100)
    return get_success_data(api_client.list_money_movements(headers, filters))


def batches_of(window_id, headers, menu_item_id=None):
    params = {"offer_window_id": window_id, "limit": 100}
    if menu_item_id:
        params["menu_item_id"] = menu_item_id
    return get_success_data(api_client.list_batches(headers, params))


def labels_of(order_line_id, headers):
    return get_success_data(
        api_client.list_labels(headers, {"order_line_id": order_line_id, "limit": 100})
    )


# ─── Tier 1: single-entity builders ──────────────────────────────────────────

def create_baker(activate=True, **overrides):
    """Register an operator and, by default, move its permit to ACTIVE."""
    baker = get_success_data(
        api_client.create_baker(create_baker_payload(**overrides), ADMIN)
    )
    if activate:
        baker = get_success_data(
            api_client.set_permit_status(baker["id"], {"to_status": "ACTIVE"}, ADMIN)
        )
    return baker


def create_customer(baker_id, **overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(baker_id, **overrides), ADMIN)
    )


def create_lot(baker_id, release=True, **overrides):
    headers = make_baker_headers(baker_id)
    lot = get_success_data(
        api_client.create_ingredient_lot(
            create_ingredient_lot_payload(baker_id, **overrides), headers
        )
    )
    if release:
        lot = get_success_data(api_client.release_ingredient_lot(lot["id"], headers))
    return lot


def create_recipe(baker_id, name="Brown Butter Cookie", components=None, publish=True):
    """Create a recipe, attach components, and publish it by default.

    `components` is a list of payload dicts; when omitted a single
    flour-and-butter component declaring wheat and milk is attached.
    """
    headers = make_baker_headers(baker_id)
    recipe = get_success_data(
        api_client.create_recipe(create_recipe_payload(baker_id, name=name), headers)
    )
    if components is None:
        components = [create_recipe_component_payload()]
    for component in components:
        get_success_data(
            api_client.add_recipe_component(recipe["id"], component, headers)
        )
    if publish:
        recipe = get_success_data(api_client.publish_recipe(recipe["id"], headers))
    return recipe


def create_menu_item(baker_id, recipe_id, kind="cookie", list_it=True, **overrides):
    """Create one of the three canonical menu items and list it by default."""
    headers = make_baker_headers(baker_id)
    builder = {
        "cookie": create_cookie_payload,
        "loaf": create_loaf_payload,
        "scone": create_scone_payload,
    }[kind]
    item = get_success_data(
        api_client.create_menu_item(builder(baker_id, recipe_id, **overrides), headers)
    )
    if list_it:
        item = get_success_data(
            api_client.set_listing_status(item["id"], {"to_status": "LISTED"}, headers)
        )
    return item


def create_window(baker_id, open_it=True, **overrides):
    headers = make_baker_headers(baker_id)
    window = get_success_data(
        api_client.create_offer_window(
            create_offer_window_payload(baker_id, **overrides), headers
        )
    )
    if open_it:
        window = get_success_data(
            api_client.advance_offer_window(window["id"], {"to_status": "OPEN"}, headers)
        )
    return window


def open_order(customer_id, window_id, **overrides):
    return get_success_data(
        api_client.create_order(
            create_order_payload(customer_id, window_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def add_line(order_id, menu_item_id, quantity, customer_id, window_id, **overrides):
    """Add a line, re-reading the window version so the OCC echo is always fresh."""
    headers = make_customer_headers(customer_id)
    version = window_version(window_id, headers)
    return get_success_data(
        api_client.add_order_line(
            order_id,
            create_order_line_payload(menu_item_id, quantity, version, **overrides),
            headers,
        )
    )


def confirm_order(order_id, customer_id, **overrides):
    payload = dict(overrides)
    return get_success_data(
        api_client.confirm_order(order_id, make_customer_headers(customer_id), payload)
    )


def authorize_payment(order_id, customer_id, **overrides):
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(order_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def capture_payment(payment_id, baker_id):
    return get_success_data(
        api_client.capture_payment(payment_id, make_baker_headers(baker_id))
    )


def create_refund(payment_id, order_id, baker_id, amount_cents, **overrides):
    """Refund, re-reading the order version so the OCC echo is always fresh."""
    headers = make_baker_headers(baker_id)
    version = order_version(order_id, headers)
    return get_success_data(
        api_client.create_refund(
            payment_id, create_refund_payload(amount_cents, version, **overrides), headers
        )
    )


def issue_label(order_line_id, recipe_id, baker_id, **overrides):
    """Issue a label, re-reading the recipe version immediately beforehand.

    Re-reading here keeps the OCC echo correct under either reading of what a
    label issuance does to the recipe's own version.
    """
    headers = make_baker_headers(baker_id)
    version = recipe_version(recipe_id, headers)
    return get_success_data(
        api_client.create_label(
            create_label_payload(order_line_id, recipe_id, version, **overrides), headers
        )
    )


# ─── Tier 2: the storefront scenario every test builds on ────────────────────

def setup_storefront(
    *,
    activate_permit=True,
    baker_overrides=None,
    customer_overrides=None,
    recipe_components=None,
    with_lot=False,
    lot_overrides=None,
    lot_release=True,
    cookie_overrides=None,
    list_cookie=True,
    window_overrides=None,
    open_window=True,
    clock=CLOCK_ORDERING_TIME,
):
    """ACTIVE operator + customer + PUBLISHED recipe + LISTED cookie + OPEN window.

    The cookie is the PER_DOZEN_BAKERS item at unit 450 / dozen 4600 that every
    worked example in the specification prices against. The window carries the
    default 240 units / 12 slots / 18.0 oven hours unless overridden, and the
    logical clock is left at `clock` (2026-05-04T09:00:00Z by default), inside
    the window's ordering interval.
    """
    baker = create_baker(activate=activate_permit, **(baker_overrides or {}))
    baker_id = baker["id"]
    baker_headers = make_baker_headers(baker_id)
    customer = create_customer(baker_id, **(customer_overrides or {}))
    scenario = Scenario(
        baker=baker,
        baker_id=baker_id,
        bh=baker_headers,
        customer=customer,
        customer_id=customer["id"],
        ch=make_customer_headers(customer["id"]),
    )
    if with_lot:
        lot = create_lot(baker_id, release=lot_release, **(lot_overrides or {}))
        scenario["lot"] = lot
        scenario["lot_id"] = lot["id"]
        if recipe_components is None:
            recipe_components = [
                create_recipe_component_payload(ingredient_lot_id=lot["id"])
            ]
    recipe = create_recipe(baker_id, components=recipe_components)
    scenario["recipe"] = recipe
    scenario["recipe_id"] = recipe["id"]
    cookie = create_menu_item(
        baker_id, recipe["id"], kind="cookie", list_it=list_cookie,
        **(cookie_overrides or {})
    )
    scenario["cookie"] = cookie
    scenario["cookie_id"] = cookie["id"]
    window = create_window(baker_id, open_it=False, **(window_overrides or {}))
    if clock:
        set_clock(clock)
    if open_window:
        window = get_success_data(
            api_client.advance_offer_window(
                window["id"], {"to_status": "OPEN"}, baker_headers
            )
        )
    scenario["window"] = window
    scenario["window_id"] = window["id"]
    scenario["window_version"] = window["version"]
    return scenario


def add_menu_item(s, kind="loaf", list_it=True, key=None, **overrides):
    """Attach a second menu item to an existing storefront scenario."""
    item = create_menu_item(
        s.baker_id, s.recipe_id, kind=kind, list_it=list_it, **overrides
    )
    s[key or kind] = item
    s[(key or kind) + "_id"] = item["id"]
    return item


def add_customer(s, key, **overrides):
    customer = create_customer(s.baker_id, **overrides)
    s[key] = customer
    s[key + "_id"] = customer["id"]
    return customer


# ─── Tier 3: order lifecycle shortcuts ───────────────────────────────────────

def setup_held_order(
    *, quantity=13, disposition=None, handoff_mode="PICKUP_COUNTER",
    order_overrides=None, scenario=None, **storefront_kwargs
):
    """A PENDING_HOLD order whose single line holds `quantity` cookies."""
    s = scenario or setup_storefront(**storefront_kwargs)
    overrides = dict(order_overrides or {})
    overrides["handoff_mode"] = handoff_mode
    order = open_order(s.customer_id, s.window_id, **overrides)
    line_kwargs = {"disposition": disposition} if disposition else {}
    line = add_line(
        order["id"], s.cookie_id, quantity, s.customer_id, s.window_id, **line_kwargs
    )
    s["order"] = read_order(order["id"], s.ch)
    s["order_id"] = order["id"]
    s["line"] = line
    s["line_id"] = line["id"]
    return s


def setup_confirmed_order(**kwargs):
    """A CONFIRMED order — the hold converted into confirmed capacity."""
    allergen_ack = kwargs.pop("allergen_ack", None)
    s = setup_held_order(**kwargs)
    confirm_kwargs = {"allergen_ack": allergen_ack} if allergen_ack is not None else {}
    s["order"] = confirm_order(s.order_id, s.customer_id, **confirm_kwargs)
    return s


def setup_authorized_order(*, tip_mode="FIXED", tip_fixed_cents=0, payment_overrides=None,
                           **kwargs):
    """A CONFIRMED order with an AUTHORIZED payment."""
    s = setup_confirmed_order(**kwargs)
    overrides = {"tip_mode": tip_mode}
    if tip_mode == "FIXED":
        overrides["tip_fixed_cents"] = tip_fixed_cents
    overrides.update(payment_overrides or {})
    payment = authorize_payment(s.order_id, s.customer_id, **overrides)
    s["payment"] = payment
    s["payment_id"] = payment["id"]
    return s


def setup_captured_order(**kwargs):
    """A CONFIRMED order with a CAPTURED payment."""
    s = setup_authorized_order(**kwargs)
    s["payment"] = capture_payment(s.payment_id, s.baker_id)
    s["order"] = read_order(s.order_id, s.bh)
    return s


# ─── Tier 4: window lifecycle and production ─────────────────────────────────

def lock_window(s, window_id=None, clock=CLOCK_AT_CUTOFF):
    """Move the clock to the cutoff and lock the window."""
    if clock:
        set_clock(clock)
    window = get_success_data(api_client.lock_offer_window(window_id or s.window_id, s.bh))
    if (window_id or s.window_id) == s.window_id:
        s["window"] = window
    return window


def plan_window(s, window_id=None):
    window = get_success_data(
        api_client.plan_offer_window(window_id or s.window_id, {"mode": "PLAN"}, s.bh)
    )
    if (window_id or s.window_id) == s.window_id:
        s["window"] = window
    return window


def advance_window(s, to_status, window_id=None):
    window = get_success_data(
        api_client.advance_offer_window(
            window_id or s.window_id, {"to_status": to_status}, s.bh
        )
    )
    if (window_id or s.window_id) == s.window_id:
        s["window"] = window
    return window


def drive_to_in_production(s):
    """Lock at cutoff, build the plan, then advance the window to IN_PRODUCTION."""
    lock_window(s)
    plan_window(s)
    set_clock(CLOCK_AT_PRODUCTION)
    advance_window(s, "IN_PRODUCTION")
    s["batches"] = batches_of(s.window_id, s.bh)
    if s["batches"]:
        s["batch"] = s["batches"][0]
        s["batch_id"] = s["batches"][0]["id"]
    return s


def bake_batch(s, batch_id):
    get_success_data(api_client.advance_batch(batch_id, {"to_status": "MIXED"}, s.bh))
    return get_success_data(
        api_client.advance_batch(batch_id, {"to_status": "BAKED"}, s.bh)
    )


def confirm_yield(s, batch_id, actual_yield_units):
    return get_success_data(
        api_client.confirm_yield(
            batch_id, {"actual_yield_units": actual_yield_units}, s.bh
        )
    )


def open_handoff(s, clock=CLOCK_AT_HANDOFF):
    if clock:
        set_clock(clock)
    return advance_window(s, "HANDOFF_OPEN")


def setup_ready_pickup_order(*, quantity=13, actual_yield_units=24, with_label=True,
                             **kwargs):
    """A READY order sitting at PICKUP_READY in a HANDOFF_OPEN window.

    The order is scheduled while the window is still OPEN (rung 16 gates
    scheduling on a LOCKED window), the batch is baked and yield-confirmed so
    every batch has reached ALLOCATED, one label is issued on the line, and the
    window then advances to HANDOFF_OPEN.
    """
    s = setup_confirmed_order(quantity=quantity, **kwargs)
    get_success_data(api_client.schedule_handoff(s.order_id, s.ch))
    drive_to_in_production(s)
    bake_batch(s, s.batch_id)
    confirm_yield(s, s.batch_id, actual_yield_units)
    if with_label:
        label = issue_label(s.line_id, s.recipe_id, s.baker_id)
        s["label"] = label
        s["label_id"] = label["id"]
    open_handoff(s)
    s["order"] = read_order(s.order_id, s.bh)
    return s


def setup_fulfilled_order(**kwargs):
    """A FULFILLED order: handed off at 2026-05-07T15:00:00Z with its label CONSUMED."""
    s = setup_ready_pickup_order(**kwargs)
    s["order"] = get_success_data(
        api_client.record_handoff_outcome(s.order_id, {"outcome": "HANDED_OFF"}, s.bh)
    )
    return s


# ─── Tier 5: the bread-and-cookie club ───────────────────────────────────────

def create_subscription(s, *, activate=True, menu_item_id=None, **overrides):
    """Create a club membership and, by default, activate it."""
    sub = get_success_data(
        api_client.create_subscription(
            create_subscription_payload(
                s.customer_id, menu_item_id or s.cookie_id, **overrides
            ),
            s.ch,
        )
    )
    if activate:
        sub = get_success_data(
            api_client.set_subscription_status(sub["id"], {"to_status": "ACTIVE"}, s.ch)
        )
    s["subscription"] = sub
    s["subscription_id"] = sub["id"]
    return sub


def generate_cycle(s, sequence_number=1, subscription_id=None, window_id=None):
    return get_success_data(
        api_client.generate_cycle(
            subscription_id or s.subscription_id,
            create_cycle_payload(window_id or s.window_id, sequence_number),
            s.bh,
        )
    )


def confirm_cycle(s, cycle_id, subscription_id=None):
    """Confirm a reserved cycle, re-reading the subscription version first."""
    sub_id = subscription_id or s.subscription_id
    version = subscription_version(sub_id, s.ch)
    return get_success_data(
        api_client.confirm_cycle(
            cycle_id, {"expected_subscription_version": version}, s.ch
        )
    )


def setup_active_club(*, billing_mode="PAY_PER_CYCLE", units_per_cycle=24,
                      handoff_mode="PICKUP_COUNTER", scenario=None, **storefront_kwargs):
    """An ACTIVE club membership on the cookie of an open storefront."""
    s = scenario or setup_storefront(**storefront_kwargs)
    create_subscription(
        s,
        billing_mode=billing_mode,
        units_per_cycle=units_per_cycle,
        handoff_mode=handoff_mode,
    )
    return s


def setup_reserved_cycle(*, sequence_number=1, **kwargs):
    """An ACTIVE club whose cycle `sequence_number` is RESERVED on the window."""
    s = setup_active_club(**kwargs)
    cycle = generate_cycle(s, sequence_number)
    s["cycle"] = cycle
    s["cycle_id"] = cycle["id"]
    return s


def setup_club_order(**kwargs):
    """A club membership whose first cycle has been confirmed into a club order."""
    s = setup_reserved_cycle(**kwargs)
    s["cycle"] = confirm_cycle(s, s.cycle_id)
    orders = get_success_data(
        api_client.list_orders(s.ch, {"subscription_cycle_id": s.cycle_id, "limit": 100})
    )
    assert orders, "Setup step failed: cycle confirmation created no club order"
    s["club_order"] = orders[0]
    s["club_order_id"] = orders[0]["id"]
    club_lines = lines_of(orders[0]["id"], s.ch)
    assert club_lines, "Setup step failed: club order carries no line"
    s["club_line"] = club_lines[0]
    s["club_line_id"] = club_lines[0]["id"]
    return s


# ─── Tier 5: delivery routes ─────────────────────────────────────────────────

def create_route(s, window_id=None):
    route = get_success_data(
        api_client.create_delivery_route(
            create_delivery_route_payload(s.baker_id, window_id or s.window_id), s.bh
        )
    )
    s["route"] = route
    s["route_id"] = route["id"]
    return route


def set_route_status(s, to_status, route_id=None):
    return get_success_data(
        api_client.set_route_status(
            route_id or s.route_id, {"to_status": to_status}, s.bh
        )
    )


def setup_delivery_order(s, customer_id, *, quantity=13, route_id=None,
                         schedule=True):
    """A CONFIRMED DELIVERY order for `customer_id`, optionally joined to a route."""
    order = open_order(customer_id, s.window_id, handoff_mode="DELIVERY")
    add_line(order["id"], s.cookie_id, quantity, customer_id, s.window_id)
    order = confirm_order(order["id"], customer_id)
    if schedule:
        payload = {"delivery_route_id": route_id or s.get("route_id")}
        order = get_success_data(
            api_client.schedule_handoff(
                order["id"], make_customer_headers(customer_id), payload
            )
        )
    return order


# ─── Tier 5: reviews ─────────────────────────────────────────────────────────

def submit_review(s, order_id=None, menu_item_id=None, rating=5, **overrides):
    review = get_success_data(
        api_client.create_review(
            create_review_payload(
                order_id or s.order_id, menu_item_id or s.cookie_id, rating, **overrides
            ),
            s.ch,
        )
    )
    s["review"] = review
    s["review_id"] = review["id"]
    return review


def setup_reviewed_order(*, rating=5, **kwargs):
    """A FULFILLED order carrying one SUBMITTED review."""
    s = setup_fulfilled_order(**kwargs)
    submit_review(s, rating=rating)
    return s


# ─── Tier 4: production scenarios targeting the yield fork ───────────────────

def setup_two_item_confirmed_order(*, cookie_quantity=13, loaf_quantity=13,
                                   cookie_disposition=None, loaf_disposition=None,
                                   **storefront_kwargs):
    """One CONFIRMED order carrying a STANDARD cookie line and a LONG_BAKE loaf line.

    The loaf is the PER_UNIT item at 900 with `oven_hours_per_batch` 3.0 and
    `yield_units_per_slot` 12, so the two batches share a slot count but not an
    oven-hour figure.
    """
    s = setup_storefront(**storefront_kwargs)
    add_menu_item(s, kind="loaf")
    order = open_order(s.customer_id, s.window_id)
    cookie_kwargs = {"disposition": cookie_disposition} if cookie_disposition else {}
    loaf_kwargs = {"disposition": loaf_disposition} if loaf_disposition else {}
    cookie_line = add_line(
        order["id"], s.cookie_id, cookie_quantity, s.customer_id, s.window_id,
        **cookie_kwargs
    )
    loaf_line = add_line(
        order["id"], s.loaf_id, loaf_quantity, s.customer_id, s.window_id, **loaf_kwargs
    )
    s["order_id"] = order["id"]
    s["cookie_line"] = cookie_line
    s["cookie_line_id"] = cookie_line["id"]
    s["loaf_line"] = loaf_line
    s["loaf_line_id"] = loaf_line["id"]
    s["order"] = confirm_order(order["id"], s.customer_id)
    return s


def setup_two_item_planned_window(**kwargs):
    """The two-item order driven through lock, plan and IN_PRODUCTION.

    Adds `cookie_batch` and `loaf_batch` to the scenario.
    """
    s = setup_two_item_confirmed_order(**kwargs)
    drive_to_in_production(s)
    cookie_batches = batches_of(s.window_id, s.bh, s.cookie_id)
    loaf_batches = batches_of(s.window_id, s.bh, s.loaf_id)
    assert cookie_batches, "Setup step failed: no batch was planned for the cookie"
    assert loaf_batches, "Setup step failed: no batch was planned for the loaf"
    s["cookie_batch"] = cookie_batches[0]
    s["cookie_batch_id"] = cookie_batches[0]["id"]
    s["loaf_batch"] = loaf_batches[0]
    s["loaf_batch_id"] = loaf_batches[0]["id"]
    return s


def setup_under_yield_scenario(*, cookie_units=13):
    """A single cookie batch whose demand comes from three orders in priority order.

    Built in exactly the order the shortfall priority reads: a PREPAID club order
    of 24 units first, then an earlier walk-up of `cookie_units` with a CAPTURED
    payment, then a later walk-up of `cookie_units` with no payment at all. The
    window is then locked, planned and advanced to IN_PRODUCTION and the single
    cookie batch is baked, ready for yield confirmation.
    """
    s = setup_storefront()
    create_subscription(s, billing_mode="PREPAID", units_per_cycle=24)
    cycle = generate_cycle(s, 1)
    s["cycle"] = cycle
    s["cycle_id"] = cycle["id"]
    s["cycle_price_cents"] = cycle["cycle_price_cents"]
    confirm_cycle(s, cycle["id"])
    club_orders = get_success_data(
        api_client.list_orders(s.ch, {"subscription_cycle_id": cycle["id"], "limit": 10})
    )
    assert club_orders, "Setup step failed: the club cycle produced no order"
    s["club_order_id"] = club_orders[0]["id"]
    club_lines = lines_of(club_orders[0]["id"], s.ch)
    s["club_line_id"] = club_lines[0]["id"]

    early = open_order(s.customer_id, s.window_id)
    early_line = add_line(
        early["id"], s.cookie_id, cookie_units, s.customer_id, s.window_id
    )
    confirm_order(early["id"], s.customer_id)
    early_payment = authorize_payment(
        early["id"], s.customer_id, tip_mode="FIXED", tip_fixed_cents=0
    )
    capture_payment(early_payment["id"], s.baker_id)
    s["early_order_id"] = early["id"]
    s["early_line_id"] = early_line["id"]
    s["early_payment_id"] = early_payment["id"]

    # The two walk-up lines are separated on the declared third and fourth
    # shortfall keys only if their owning orders' created_at instants differ, so
    # the logical clock is advanced before the later order is opened.
    set_clock("2026-05-04T09:10:00Z")
    late = open_order(s.customer_id, s.window_id)
    late_line = add_line(
        late["id"], s.cookie_id, cookie_units, s.customer_id, s.window_id
    )
    confirm_order(late["id"], s.customer_id)
    s["late_order_id"] = late["id"]
    s["late_line_id"] = late_line["id"]

    drive_to_in_production(s)
    cookie_batches = batches_of(s.window_id, s.bh, s.cookie_id)
    assert cookie_batches, "Setup step failed: no cookie batch was planned"
    s["cookie_batch"] = cookie_batches[0]
    s["cookie_batch_id"] = cookie_batches[0]["id"]
    bake_batch(s, s.cookie_batch_id)
    return s


def setup_recall_cascade_scenario():
    """One released flour lot backing one PUBLISHED recipe used by two LISTED items.

    Order A holds 13 cookies with a CAPTURED payment of 5100 (4600 subtotal plus a
    500-cent fixed tip) and an ISSUED label on its line; order B holds 4 loaves. The
    window is LOCKED, PLANNED and IN_PRODUCTION; the loaf batch has been baked and
    yield-confirmed so it has reached ALLOCATED, while the cookie batch is only
    MIXED. Baking the loaf batch moved the lot from RELEASED to CONSUMED, which is
    the state the deep cascade is recalled from.
    """
    s = setup_storefront(
        with_lot=True,
        lot_overrides={"lot_code": "FLR-2026-11", "allergens": ["wheat", "milk"]},
    )
    components = get_success_data(
        api_client.list_recipe_components(s.bh, {"recipe_id": s.recipe_id, "limit": 50})
    )
    assert components, "Setup step failed: the recipe carries no component"
    s["component_id"] = components[0]["id"]
    add_menu_item(s, kind="loaf")

    order_a = open_order(s.customer_id, s.window_id)
    line_cookie = add_line(
        order_a["id"], s.cookie_id, 13, s.customer_id, s.window_id,
        disposition="WHOLE_UNHEATED",
    )
    confirm_order(order_a["id"], s.customer_id)
    payment_a = authorize_payment(
        order_a["id"], s.customer_id, tip_mode="FIXED", tip_fixed_cents=500
    )
    captured = capture_payment(payment_a["id"], s.baker_id)
    s["order_a_id"] = order_a["id"]
    s["line_cookie_id"] = line_cookie["id"]
    s["payment_a_id"] = payment_a["id"]
    s["captured_a_cents"] = captured["captured_cents"]

    order_b = open_order(s.customer_id, s.window_id)
    line_bread = add_line(
        order_b["id"], s.loaf_id, 4, s.customer_id, s.window_id,
        disposition="WHOLE_UNHEATED",
    )
    confirm_order(order_b["id"], s.customer_id)
    s["order_b_id"] = order_b["id"]
    s["line_bread_id"] = line_bread["id"]

    drive_to_in_production(s)
    bread_batches = batches_of(s.window_id, s.bh, s.loaf_id)
    cookie_batches = batches_of(s.window_id, s.bh, s.cookie_id)
    assert bread_batches and cookie_batches, "Setup step failed: the plan is incomplete"
    s["bread_batch_id"] = bread_batches[0]["id"]
    s["cookie_batch_id"] = cookie_batches[0]["id"]

    bake_batch(s, s.bread_batch_id)
    confirm_yield(s, s.bread_batch_id, 12)
    get_success_data(
        api_client.advance_batch(s.cookie_batch_id, {"to_status": "MIXED"}, s.bh)
    )
    label = issue_label(s.line_cookie_id, s.recipe_id, s.baker_id)
    s["label_cookie_id"] = label["id"]
    return s
