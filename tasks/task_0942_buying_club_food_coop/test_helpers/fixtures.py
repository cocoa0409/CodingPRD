"""Composite setup helpers.

Every entity a test needs is built here through the declared endpoints; the
server seeds nothing.  The chain below is the canonical scenario the whole
suite shares:

    North Route (2 reefer slots)
      Depot A  -- no coordinator
      Depot B  -- coordinated by Cora (PRO)
    Members: Cora (PRO), Mara (PLUS), Ben (BASIC), all with dues paid
    Catalog: OAT-25 (DRY, 4/case), BERRY-10 (FROZEN, 6/case, ROUND_UP),
             CHEESE-2 (CHILLED, 3/case, DROP)
    Cycle CY-MAY, opens 2026-05-05, cutoff 2026-05-25
    Mara orders OAT x5, BERRY x4, CHEESE x4;  Ben orders OAT x6, BERRY x3,
    CHEESE x3;  both submitted.

`canonical_world(api, stage)` walks that chain and stops at a named stage.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    CLOCK_AFTER_EXCEPTION_WINDOW,
    CLOCK_CUTOFF,
    CLOCK_OPEN,
    CYCLE_CUTOFF_AT,
    CYCLE_OPENS_AT,
    DEFAULT_FREIGHT_CENTS,
    DEFAULT_SUPPLIER_INVOICE_CENTS,
    PRICE_EPOCH,
    PRICE_LATE_OAT,
    TIER_BASIC_ANNUAL_DUES_CENTS,
    TIER_PLUS_ANNUAL_DUES_CENTS,
    TIER_PRO_ANNUAL_DUES_CENTS,
)
from .factories import (
    ITEM_BLUEPRINTS,
    ITEM_CASE_PRICE_CENTS,
    create_credit_grant_payload,
    create_drop_point_payload,
    create_drop_reconciliation_payload,
    create_drop_run_payload,
    create_item_payload,
    create_member_order_payload,
    create_member_payload,
    create_order_line_payload,
    create_price_version_payload,
    create_receipt_line_payload,
    create_route_payload,
    create_volunteer_shift_payload,
    dues_payment_payload,
    supplier_invoice_payload,
)
from .test_users import (
    FINANCE_PREPARER_HEADERS,
    FINANCE_POSTER_HEADERS,
    TEST_USERS,
    make_coordinator_headers,
    make_member_headers,
)

# Ordered stages of the canonical chain.
STAGES = [
    "catalog",
    "cycle_open",
    "orders_submitted",
    "at_cutoff",
    "locked",
    "authorized",
    "cycle_submitted",
    "received",
    "volunteer_verified",
    "aggregates",
    "receipts",
    "invoiced",
    "pallets_built",
    "pallets_sealed",
    "consolidated",
    "captured",
    "delivered",
    "recon_drafted",
    "recon_balanced",
    "recon_posted",
    "cycle_reconciled",
    "cycle_closed",
]

# Price plans: one list of (effective_from, case_price_cents) per catalog key.
PRICE_PLANS = {
    "oat": [(PRICE_EPOCH, ITEM_CASE_PRICE_CENTS["oat"])],
    "berry": [(PRICE_EPOCH, ITEM_CASE_PRICE_CENTS["berry"])],
    "cheese": [(PRICE_EPOCH, ITEM_CASE_PRICE_CENTS["cheese"])],
    "salt": [(PRICE_EPOCH, ITEM_CASE_PRICE_CENTS["salt"])],
    "pepper": [(PRICE_EPOCH, ITEM_CASE_PRICE_CENTS["pepper"])],
    "rice": [(PRICE_EPOCH, ITEM_CASE_PRICE_CENTS["rice"])],
    "late": [("2026-06-01T00:00:00Z", ITEM_CASE_PRICE_CENTS["late"])],
    # the substitute is only ever named on a receipt, which carries its own
    # substitute_case_price_cents, so it needs no published price version
    "cheddar_sub": [],
}

ANNUAL_DUES = {
    "BASIC": TIER_BASIC_ANNUAL_DUES_CENTS,
    "PLUS": TIER_PLUS_ANNUAL_DUES_CENTS,
    "PRO": TIER_PRO_ANNUAL_DUES_CENTS,
}


class World:
    """Attribute bag holding every id the canonical chain minted."""

    def __init__(self):
        self.admin = TEST_USERS["club_admin_headers"]
        self.warehouse = TEST_USERS["warehouse_headers"]
        self.finance = TEST_USERS["finance_headers"]
        self.items = {}
        self.prices = {}
        self.route_id = None
        self.depot_a_id = None
        self.depot_b_id = None
        self.cora_id = None
        self.mara_id = None
        self.ben_id = None
        self.cycle_id = None
        self.drop_run_id = None
        self.route_run_id = None
        self.order_mara = None
        self.order_ben = None
        self.lines = {}
        self.aggregates = {}
        self.pallets = []
        self.volunteer_shift_id = None
        self.reconciliation_id = None
        self.accrual_id = None

    # convenience header builders -----------------------------------------
    @property
    def mara(self):
        return make_member_headers(self.mara_id)

    @property
    def ben(self):
        return make_member_headers(self.ben_id)

    @property
    def cora(self):
        return make_member_headers(self.cora_id)

    @property
    def coordinator(self):
        return make_coordinator_headers(self.cora_id)


# --------------------------------------------------------------------------
# Small primitives
# --------------------------------------------------------------------------


def set_clock(api, iso: str, headers=None) -> dict:
    return get_success_data(
        api.set_clock(iso, headers or TEST_USERS["club_admin_headers"])
    )


def order_version(api, w: World, order_id: str) -> int:
    return get_success_data(api.get_member_order(order_id, w.admin))["version"]


def member_version(api, w: World, member_id: str) -> int:
    return get_success_data(api.get_member(member_id, w.admin))["version"]


def drop_run_version(api, w: World, drop_run_id: str) -> int:
    return get_success_data(api.get_drop_run(drop_run_id, w.admin))["version"]


def route_run_version(api, w: World, route_run_id: str) -> int:
    return get_success_data(api.get_route_run(route_run_id, w.admin))["version"]


def register_member(api, w: World, email: str, full_name: str, drop_point_id: str,
                    tier: str = "BASIC", pay_dues: bool = True) -> str:
    payload = create_member_payload(drop_point_id, email=email, full_name=full_name)
    if tier != "BASIC":
        payload["tier"] = tier
    member = get_success_data(api.create_member(payload, w.admin))
    if pay_dues:
        get_success_data(
            api.pay_dues(
                member["id"],
                dues_payment_payload(ANNUAL_DUES[tier], member["version"]),
                w.admin,
            )
        )
    return member["id"]


def publish_item(api, w: World, key: str, **item_overrides) -> str:
    item = get_success_data(
        api.create_item(create_item_payload(key, **item_overrides), w.admin)
    )
    w.items[key] = item["id"]
    w.prices[key] = []
    for effective_from, case_price_cents in PRICE_PLANS[key]:
        price = get_success_data(
            api.create_price_version(
                create_price_version_payload(
                    item["id"], case_price_cents, effective_from=effective_from
                ),
                w.admin,
            )
        )
        w.prices[key].append(price["id"])
    return item["id"]


# --------------------------------------------------------------------------
# Tier 1 / Tier 2 — catalog, delivery network and membership
# --------------------------------------------------------------------------


def build_catalog(
    api,
    *,
    clock: str = CLOCK_OPEN,
    route_minimum_cents: int = 1000,
    reefer_slots: int = 2,
    max_pallets: int = 12,
    drop_minimum_cents: int = 1000,
    items=("oat", "berry", "cheese"),
    oat_late_price: bool = True,
    include_ben: bool = True,
) -> World:
    """North Route, two depots, three members and the requested catalog."""
    w = World()
    set_clock(api, clock)

    route = get_success_data(
        api.create_route(
            create_route_payload(
                reefer_slots=reefer_slots,
                route_minimum_cents=route_minimum_cents,
                max_pallets=max_pallets,
            ),
            w.admin,
        )
    )
    w.route_id = route["id"]

    depot_a = get_success_data(
        api.create_drop_point(
            create_drop_point_payload(
                w.route_id, name="Depot A", drop_minimum_cents=drop_minimum_cents
            ),
            w.admin,
        )
    )
    w.depot_a_id = depot_a["id"]

    w.cora_id = register_member(
        api, w, "cora@coop.test", "Cora Ord", w.depot_a_id, tier="PRO"
    )

    depot_b = get_success_data(
        api.create_drop_point(
            create_drop_point_payload(
                w.route_id,
                name="Depot B",
                coordinator_member_id=w.cora_id,
                drop_minimum_cents=drop_minimum_cents,
            ),
            w.admin,
        )
    )
    w.depot_b_id = depot_b["id"]

    w.mara_id = register_member(
        api, w, "mara@coop.test", "Mara Plus", w.depot_b_id, tier="PLUS"
    )
    if include_ben:
        w.ben_id = register_member(
            api, w, "ben@coop.test", "Ben Basic", w.depot_b_id, tier="BASIC"
        )

    for key in items:
        publish_item(api, w, key)
        if key == "oat" and oat_late_price:
            price = get_success_data(
                api.create_price_version(
                    create_price_version_payload(
                        w.items["oat"], 13200, effective_from=PRICE_LATE_OAT
                    ),
                    w.admin,
                )
            )
            w.prices["oat"].append(price["id"])
    return w


def open_cycle(
    api,
    w: World,
    *,
    code: str = "CY-MAY",
    opens_at: str = CYCLE_OPENS_AT,
    cutoff_at: str = CYCLE_CUTOFF_AT,
) -> dict:
    cycle = get_success_data(
        api.create_cycle(
            {"code": code, "opens_at": opens_at, "cutoff_at": cutoff_at}, w.admin
        )
    )
    if w.cycle_id is None:
        w.cycle_id = cycle["id"]
    return cycle


def open_drop_run(api, w: World, *, cycle_id: str = None, drop_point_id: str = None) -> dict:
    drop_run = get_success_data(
        api.create_drop_run(
            create_drop_run_payload(
                cycle_id or w.cycle_id, drop_point_id or w.depot_b_id
            ),
            w.admin,
        )
    )
    if w.drop_run_id is None:
        w.drop_run_id = drop_run["id"]
    return drop_run


def add_line(api, w: World, order_id: str, item_key: str, qty_units: int,
             headers=None, **line_overrides) -> dict:
    """Create one order line, always with the order's current version."""
    version = order_version(api, w, order_id)
    return get_success_data(
        api.create_order_line(
            create_order_line_payload(
                order_id, w.items[item_key], qty_units, version, **line_overrides
            ),
            headers,
        )
    )


def place_order(api, w: World, member_id: str, drop_run_id: str, lines, submit=True) -> dict:
    """Open an order for `member_id` and add `lines` = [(item_key, qty, opts)]."""
    headers = make_member_headers(member_id)
    order = get_success_data(
        api.create_member_order(
            create_member_order_payload(member_id, drop_run_id), headers
        )
    )
    created = []
    for spec in lines:
        item_key, qty = spec[0], spec[1]
        opts = spec[2] if len(spec) > 2 else {}
        created.append(add_line(api, w, order["id"], item_key, qty, headers, **opts))
    if submit:
        order = get_success_data(api.submit_member_order(order["id"], headers))
    return {"order": order, "lines": created}


def place_canonical_orders(api, w: World) -> None:
    """Mara's three-line order and Ben's three-line order, both submitted."""
    mara = place_order(
        api,
        w,
        w.mara_id,
        w.drop_run_id,
        [
            ("oat", 5),
            ("berry", 4),
            ("cheese", 4, {"substitution_pref": "APPROVAL_REQUIRED"}),
        ],
    )
    w.order_mara = mara["order"]["id"]
    w.lines["mara_oat"] = mara["lines"][0]["id"]
    w.lines["mara_berry"] = mara["lines"][1]["id"]
    w.lines["mara_cheese"] = mara["lines"][2]["id"]

    ben = place_order(
        api,
        w,
        w.ben_id,
        w.drop_run_id,
        [("oat", 6), ("berry", 3), ("cheese", 3)],
    )
    w.order_ben = ben["order"]["id"]
    w.lines["ben_oat"] = ben["lines"][0]["id"]
    w.lines["ben_berry"] = ben["lines"][1]["id"]
    w.lines["ben_cheese"] = ben["lines"][2]["id"]


# --------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# --------------------------------------------------------------------------


def capture_route_run(api, w: World, cycle_id: str = None) -> str:
    rows, _ = _list(api, api.list_route_runs, w.admin, {"cycle_id": cycle_id or w.cycle_id})
    assert rows, "Setup failed: the cycle has no route run"
    if w.route_run_id is None:
        w.route_run_id = rows[0]["id"]
    return rows[0]["id"]


def _list(api, method, headers, params=None):
    response = method(headers, params=params)
    body = response.json()
    assert response.status_code == 200, (
        f"Setup failed: list call returned {response.status_code}: {body}"
    )
    return body["data"], body.get("meta", {})


def capture_aggregates(api, w: World) -> dict:
    """Look up one case aggregate per catalog key present on the run."""
    for key, item_id in w.items.items():
        rows, _ = _list(
            api,
            api.list_case_aggregates,
            w.admin,
            {"route_run_id": w.route_run_id, "item_id": item_id},
        )
        if rows:
            w.aggregates[key] = rows[0]["id"]
    return w.aggregates


def record_receipt(api, w: World, item_key: str, cases_received: int, **overrides) -> dict:
    version = route_run_version(api, w, w.route_run_id)
    payload = create_receipt_line_payload(
        w.route_run_id, w.aggregates[item_key], cases_received, version, **overrides
    )
    return get_success_data(api.create_receipt_line(payload, w.warehouse))


def log_and_verify_volunteer_hours(api, w: World, hours: float = 4.0,
                                   member_id: str = None) -> dict:
    shift = get_success_data(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(
                w.drop_run_id, member_id or w.cora_id, hours
            ),
            w.coordinator,
        )
    )
    w.volunteer_shift_id = shift["id"]
    return get_success_data(api.verify_volunteer_shift(shift["id"], w.coordinator))


def seal_all_pallets(api, w: World) -> list:
    rows, _ = _list(api, api.list_pallets, w.admin, {"route_run_id": w.route_run_id})
    w.pallets = [row["id"] for row in rows]
    for pallet_id in w.pallets:
        get_success_data(api.seal_pallet(pallet_id, w.warehouse))
    return w.pallets


def draft_reconciliation(api, w: World, drop_run_id: str = None, preparer=None) -> dict:
    """Draft a ledger for a drop run using its current version."""
    drop_run_id = drop_run_id or w.drop_run_id
    preparer = preparer or FINANCE_PREPARER_HEADERS
    version = drop_run_version(api, w, drop_run_id)
    rec = get_success_data(
        api.create_drop_reconciliation(
            create_drop_reconciliation_payload(drop_run_id, version), preparer
        )
    )
    w.reconciliation_id = rec["id"]
    return rec


def balance_reconciliation(api, w: World, reconciliation: dict, preparer=None) -> dict:
    """Bring a freshly drafted ledger to BALANCED.

    A draft auto-branches on its own computed variance inside the creating
    request, so this helper reads the variance the server reported and, when
    the draft landed on VARIANCE_HELD, resolves exactly that figure.
    """
    preparer = preparer or FINANCE_PREPARER_HEADERS
    if reconciliation["status"] == "VARIANCE_HELD":
        reconciliation = get_success_data(
            api.resolve_reconciliation_variance(
                reconciliation["id"],
                {"adjustment_cents": reconciliation["variance_cents"]},
                preparer,
            )
        )
    return reconciliation


def draft_and_balance_reconciliation(api, w: World, drop_run_id: str = None,
                                     preparer=None) -> dict:
    return balance_reconciliation(
        api, w, draft_reconciliation(api, w, drop_run_id, preparer), preparer
    )


def find_accrual(api, w: World, drop_run_id: str = None) -> dict:
    rows, _ = _list(
        api,
        api.list_commission_accruals,
        w.finance,
        {"drop_run_id": drop_run_id or w.drop_run_id},
    )
    assert rows, "Setup failed: the settled drop run has no commission accrual"
    w.accrual_id = rows[0]["id"]
    return rows[0]


def find_offer_for_line(api, w: World, order_line_id: str, headers=None) -> dict:
    rows, _ = _list(
        api,
        api.list_substitution_offers,
        headers or w.admin,
        {"order_line_id": order_line_id},
    )
    assert rows, f"Setup failed: no substitution offer for line {order_line_id}"
    return rows[0]


def grant_credit(api, w: World, member_id: str, amount_cents: int, expires_at: str) -> dict:
    version = member_version(api, w, member_id)
    return get_success_data(
        api.create_credit_grant(
            create_credit_grant_payload(member_id, amount_cents, expires_at, version),
            w.admin,
        )
    )


# --------------------------------------------------------------------------
# Tier 5 — the canonical chain, stopped at a named stage
# --------------------------------------------------------------------------


def canonical_world(
    api,
    stage: str = "delivered",
    *,
    route_minimum_cents: int = 1000,
    reefer_slots: int = 2,
    max_pallets: int = 12,
    drop_minimum_cents: int = 1000,
    with_volunteer_shift: bool = True,
    volunteer_hours: float = 4.0,
    supplier_invoice_cents: int = DEFAULT_SUPPLIER_INVOICE_CENTS,
    freight_cents: int = DEFAULT_FREIGHT_CENTS,
    extra_items=(),
) -> World:
    """Walk the shared scenario and stop once `stage` is reached."""
    assert stage in STAGES, f"unknown stage {stage!r}"
    target = STAGES.index(stage)

    items = ("oat", "berry", "cheese") + tuple(extra_items)
    w = build_catalog(
        api,
        route_minimum_cents=route_minimum_cents,
        reefer_slots=reefer_slots,
        max_pallets=max_pallets,
        drop_minimum_cents=drop_minimum_cents,
        items=items,
    )
    if target == STAGES.index("catalog"):
        return w

    open_cycle(api, w)
    open_drop_run(api, w)
    if target == STAGES.index("cycle_open"):
        return w

    place_canonical_orders(api, w)
    if target == STAGES.index("orders_submitted"):
        return w

    set_clock(api, CLOCK_CUTOFF)
    if target == STAGES.index("at_cutoff"):
        return w

    get_success_data(api.lock_cycle(w.cycle_id, w.admin))
    capture_route_run(api, w)
    if target == STAGES.index("locked"):
        return w

    get_success_data(
        api.authorize_member_order(
            w.order_mara, {"simulated_outcome": "SUCCEEDED"}, w.finance
        )
    )
    get_success_data(
        api.authorize_member_order(
            w.order_ben, {"simulated_outcome": "SUCCEEDED"}, w.finance
        )
    )
    if target == STAGES.index("authorized"):
        return w

    get_success_data(api.submit_cycle(w.cycle_id, w.admin))
    if target == STAGES.index("cycle_submitted"):
        return w

    get_success_data(api.receive_cycle(w.cycle_id, w.warehouse))
    if target == STAGES.index("received"):
        return w

    if with_volunteer_shift:
        log_and_verify_volunteer_hours(api, w, volunteer_hours)
    if target == STAGES.index("volunteer_verified"):
        return w

    capture_aggregates(api, w)
    if target == STAGES.index("aggregates"):
        return w

    record_receipt(api, w, "oat", 2)
    record_receipt(api, w, "berry", 2)
    record_receipt(api, w, "cheese", 2)
    if target == STAGES.index("receipts"):
        return w

    get_success_data(
        api.record_supplier_invoice(
            w.route_run_id,
            supplier_invoice_payload(supplier_invoice_cents, freight_cents),
            w.warehouse,
        )
    )
    if target == STAGES.index("invoiced"):
        return w

    get_success_data(api.build_pallets(w.route_run_id, w.warehouse))
    if target == STAGES.index("pallets_built"):
        return w

    seal_all_pallets(api, w)
    if target == STAGES.index("pallets_sealed"):
        return w

    set_clock(api, CLOCK_AFTER_EXCEPTION_WINDOW)
    get_success_data(api.consolidate_cycle(w.cycle_id, w.warehouse))
    if target == STAGES.index("consolidated"):
        return w

    get_success_data(api.capture_member_order(w.order_mara, {}, w.finance))
    get_success_data(api.capture_member_order(w.order_ben, {}, w.finance))
    if target == STAGES.index("captured"):
        return w

    get_success_data(api.deliver_cycle(w.cycle_id, w.warehouse))
    if target == STAGES.index("delivered"):
        return w

    rec = draft_reconciliation(api, w)
    if target == STAGES.index("recon_drafted"):
        return w

    balance_reconciliation(api, w, rec)
    if target == STAGES.index("recon_balanced"):
        return w

    get_success_data(
        api.post_drop_reconciliation(w.reconciliation_id, FINANCE_POSTER_HEADERS)
    )
    if target == STAGES.index("recon_posted"):
        return w

    get_success_data(api.reconcile_cycle(w.cycle_id, w.finance))
    if target == STAGES.index("cycle_reconciled"):
        return w

    get_success_data(api.close_cycle(w.cycle_id, w.admin))
    return w


# --------------------------------------------------------------------------
# Focused single-line scenarios (SALT-1: 5250 cents per 5-unit case)
# --------------------------------------------------------------------------


def salt_world(
    api,
    *,
    route_minimum_cents: int = 1000,
    drop_minimum_cents: int = 1000,
    extra_items=(),
    qty_units: int = 5,
    submit: bool = True,
    rollover_opt_in: bool = False,
) -> World:
    """Mara alone on Depot B with one SALT-1 line worth 5250 cents."""
    items = ("salt",) + tuple(extra_items)
    w = build_catalog(
        api,
        items=items,
        include_ben=False,
        route_minimum_cents=route_minimum_cents,
        drop_minimum_cents=drop_minimum_cents,
    )
    open_cycle(api, w)
    open_drop_run(api, w)
    line_opts = {"rollover_opt_in": True} if rollover_opt_in else {}
    placed = place_order(
        api,
        w,
        w.mara_id,
        w.drop_run_id,
        [("salt", qty_units, line_opts)],
        submit=submit,
    )
    w.order_mara = placed["order"]["id"]
    w.lines["mara_salt"] = placed["lines"][0]["id"]
    return w


def rice_world(
    api,
    *,
    qty_units: int,
    cases_received: int,
    supplier_invoice_cents: int,
    max_pallets: int = 12,
    stage: str = "pallets_built",
) -> World:
    """Mara alone with one bulk RICE-50 line, carried to the pallet build.

    RICE-50 packs 2 units per case at 40000 cents, forbids split units and
    weighs 22700 g per unit, which is what makes the 900000 g pallet cap
    reachable.
    """
    w = build_catalog(api, items=("rice",), include_ben=False, max_pallets=max_pallets)
    open_cycle(api, w)
    open_drop_run(api, w)
    placed = place_order(api, w, w.mara_id, w.drop_run_id, [("rice", qty_units)])
    w.order_mara = placed["order"]["id"]
    w.lines["mara_rice"] = placed["lines"][0]["id"]

    set_clock(api, CLOCK_CUTOFF)
    get_success_data(api.lock_cycle(w.cycle_id, w.admin))
    capture_route_run(api, w)
    get_success_data(api.submit_cycle(w.cycle_id, w.admin))
    get_success_data(api.receive_cycle(w.cycle_id, w.warehouse))
    capture_aggregates(api, w)
    record_receipt(api, w, "rice", cases_received)
    get_success_data(
        api.record_supplier_invoice(
            w.route_run_id, supplier_invoice_payload(supplier_invoice_cents, 0), w.warehouse
        )
    )
    if stage == "invoiced":
        return w
    get_success_data(api.build_pallets(w.route_run_id, w.warehouse))
    if stage == "pallets_built":
        return w

    seal_all_pallets(api, w)
    set_clock(api, CLOCK_AFTER_EXCEPTION_WINDOW)
    get_success_data(api.consolidate_cycle(w.cycle_id, w.warehouse))
    get_success_data(
        api.authorize_member_order(
            w.order_mara, {"simulated_outcome": "SUCCEEDED"}, w.finance
        )
    )
    get_success_data(api.capture_member_order(w.order_mara, {}, w.finance))
    get_success_data(api.deliver_cycle(w.cycle_id, w.warehouse))
    return w


def substitution_world(api, *, substitute_case_price_cents: int) -> World:
    """The canonical world at RECEIVED, with the cheese aggregate satisfied by
    CHEDDAR-SUB at the supplied case price."""
    w = canonical_world(api, "volunteer_verified", extra_items=("cheddar_sub",))
    capture_aggregates(api, w)
    record_receipt(
        api,
        w,
        "cheese",
        2,
        substitute_item_id=w.items["cheddar_sub"],
        substitute_case_price_cents=substitute_case_price_cents,
    )
    return w
