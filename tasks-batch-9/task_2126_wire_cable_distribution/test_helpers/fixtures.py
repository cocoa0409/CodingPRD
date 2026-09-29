"""Composite setup helpers.

Most interesting claims about this API require the system to be in a state
that takes between five and twenty-five calls to reach — a branch, a
customer, a catalog part, a published copper settlement, reels in stock, a
quote that has been lined, issued and converted, an allocation run, a commit
fork, a delivery run and finally a reel return. These helpers encapsulate
those sequences so the test bodies contain assertions only.

Every helper builds its preconditions from scratch through the public API;
nothing is carried over between tests.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    PRODUCT_P1,
    allocate_payload,
    create_branch_payload,
    create_copper_index_entry_payload,
    create_customer_payload,
    create_delivery_run_payload,
    create_product_payload,
    create_quote_line_payload,
    create_quote_payload,
    create_reel_payload,
    create_truck_payload,
    credit_adjustment_payload,
    cut_payload,
    return_reel_payload,
    set_clock_payload,
)
from .test_users import (
    make_branch_ops_headers,
    make_credit_manager_headers,
    make_driver_headers,
    make_platform_admin_headers,
    make_sales_rep_headers,
)

ADMIN = make_platform_admin_headers()
REP_1 = make_sales_rep_headers("rep-1")
REP_2 = make_sales_rep_headers("rep-2")
CREDIT_DESK = make_credit_manager_headers("cm-1")


# ══════════════════════════════════════════════════════════════════════════
# Tier 0 — single-resource creation
# ══════════════════════════════════════════════════════════════════════════

def create_branch(**overrides) -> dict:
    return get_success_data(
        api_client.create_branch(create_branch_payload(**overrides), ADMIN)
    )


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_product(base=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(base, **overrides), ADMIN)
    )


def publish_index(effective_date="2026-07-30", price_cents_per_lb=450,
                  headers=None) -> dict:
    return get_success_data(
        api_client.create_copper_index_entry(
            create_copper_index_entry_payload(
                effective_date=effective_date,
                price_cents_per_lb=price_cents_per_lb,
            ),
            headers or ADMIN,
        )
    )


def create_truck(branch_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_truck(create_truck_payload(branch_id, **overrides), ADMIN)
    )


def receive_reel(product_id, branch_id, nominal_length_ft=1000,
                 lot_code=TEST_DEFAULTS["LOT_CODE"], headers=None) -> dict:
    return get_success_data(
        api_client.create_reel(
            create_reel_payload(
                product_id,
                branch_id,
                lot_code=lot_code,
                nominal_length_ft=nominal_length_ft,
            ),
            headers or ADMIN,
        )
    )


def set_clock(to_iso8601) -> dict:
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    )


def post_credit_adjustment(customer_id, delta_open_balance_cents=None,
                           delta_credit_limit_cents=None,
                           reason="manual invoice posted") -> dict:
    payload = credit_adjustment_payload(reason=reason)
    if delta_open_balance_cents is not None:
        payload["delta_open_balance_cents"] = delta_open_balance_cents
    if delta_credit_limit_cents is not None:
        payload["delta_credit_limit_cents"] = delta_credit_limit_cents
    return get_success_data(
        api_client.create_credit_adjustment(customer_id, payload, CREDIT_DESK)
    )


# ══════════════════════════════════════════════════════════════════════════
# Reads — every one of these is a plain GET returning the data payload
# ══════════════════════════════════════════════════════════════════════════

def read_branch(branch_id, headers=None) -> dict:
    return get_success_data(api_client.get_branch(branch_id, headers or ADMIN))


def read_customer(customer_id, headers=None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or ADMIN))


def read_product(product_id, headers=None) -> dict:
    return get_success_data(api_client.get_product(product_id, headers or ADMIN))


def read_index_entry(entry_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_copper_index_entry(entry_id, headers or ADMIN)
    )


def read_reel(reel_id, headers=None) -> dict:
    return get_success_data(api_client.get_reel(reel_id, headers or ADMIN))


def read_quote(quote_id, headers=None) -> dict:
    return get_success_data(api_client.get_quote(quote_id, headers or ADMIN))


def read_quote_line(quote_line_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_quote_line(quote_line_id, headers or ADMIN)
    )


def read_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.get_sales_order(order_id, headers or ADMIN))


def read_order_line(order_line_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_order_line(order_line_id, headers or ADMIN)
    )


def read_allocation(allocation_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_allocation(allocation_id, headers or ADMIN)
    )


def read_run(run_id, headers=None) -> dict:
    return get_success_data(api_client.get_delivery_run(run_id, headers or ADMIN))


def list_reels(headers=None, **params) -> list:
    return get_success_data(api_client.list_reels(headers or ADMIN, params))


def list_allocations(headers=None, **params) -> list:
    return get_success_data(api_client.list_allocations(headers or ADMIN, params))


def list_order_lines(headers=None, **params) -> list:
    return get_success_data(api_client.list_order_lines(headers or ADMIN, params))


def list_quote_lines(headers=None, **params) -> list:
    return get_success_data(api_client.list_quote_lines(headers or ADMIN, params))


def list_quotes(headers=None, **params) -> list:
    return get_success_data(api_client.list_quotes(headers or ADMIN, params))


def list_orders(headers=None, **params) -> list:
    return get_success_data(api_client.list_sales_orders(headers or ADMIN, params))


def list_runs(headers=None, **params) -> list:
    return get_success_data(api_client.list_delivery_runs(headers or ADMIN, params))


# ══════════════════════════════════════════════════════════════════════════
# Tier 1 — the quoting desk
# ══════════════════════════════════════════════════════════════════════════

def open_quote(customer_id, branch_id, creator="rep-1") -> dict:
    return get_success_data(
        api_client.create_quote(
            create_quote_payload(customer_id, branch_id),
            make_sales_rep_headers(creator),
        )
    )


def add_line(quote_id, product_id, put_up="CUT", requested_length_ft=300,
             parallel_set_size=1, expected_quote_version=None,
             creator="rep-1") -> dict:
    """Add one line to a DRAFT quote. When no expected_quote_version is
    supplied the quote's current version is read first, so callers that are
    not exercising the stale-version guard need not track it."""
    if expected_quote_version is None:
        expected_quote_version = read_quote(quote_id)["version"]
    payload = create_quote_line_payload(
        product_id,
        expected_quote_version,
        put_up=put_up,
        requested_length_ft=requested_length_ft,
        parallel_set_size=parallel_set_size,
    )
    return get_success_data(
        api_client.create_quote_line(
            quote_id, payload, make_sales_rep_headers(creator)
        )
    )


def issue_quote(quote_id, issuer="rep-2") -> dict:
    return get_success_data(
        api_client.issue_quote(quote_id, make_sales_rep_headers(issuer))
    )


def reprice_quote(quote_id, actor="rep-1") -> dict:
    return get_success_data(
        api_client.reprice_quote(quote_id, make_sales_rep_headers(actor))
    )


def convert_quote(quote_id, issuer="rep-2") -> dict:
    return get_success_data(
        api_client.convert_quote(quote_id, make_sales_rep_headers(issuer))
    )


def build_quote(customer_id, branch_id, product_id, lines, creator="rep-1") -> tuple:
    """Open a DRAFT quote and add every line in `lines`, in order.

    Each entry of `lines` is a dict accepting put_up, requested_length_ft,
    parallel_set_size and an optional product_id override.
    Returns (quote, [quote_line, ...]).
    """
    quote = open_quote(customer_id, branch_id, creator=creator)
    quote_lines = []
    for spec in lines:
        spec = dict(spec)
        quote_lines.append(
            add_line(
                quote["id"],
                spec.pop("product_id", product_id),
                creator=creator,
                **spec,
            )
        )
    return quote, quote_lines


# ══════════════════════════════════════════════════════════════════════════
# Tier 2 — the full bootstrap: catalog, stock and a converted order
# ══════════════════════════════════════════════════════════════════════════

def setup_catalog(product=None, branch_overrides=None, customer_overrides=None,
                  index=("2026-07-30", 450), truck_overrides=None,
                  reels=()) -> dict:
    """Branch, customer, catalog part and published copper settlement, plus an
    optional truck and any number of received master reels.

    `reels` is a sequence of dicts accepting nominal_length_ft and lot_code.
    Returns a scenario dict carrying every created resource and the role
    headers bound to the branch and the truck.
    """
    branch = create_branch(**(branch_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    part = create_product(product if product is not None else PRODUCT_P1)
    index_entry = None
    if index is not None:
        index_entry = publish_index(index[0], index[1])
    truck = None
    if truck_overrides is not None:
        truck = create_truck(branch["id"], **truck_overrides)
    received = [
        receive_reel(
            part["id"],
            branch["id"],
            nominal_length_ft=spec.get("nominal_length_ft", 1000),
            lot_code=spec.get("lot_code", TEST_DEFAULTS["LOT_CODE"]),
        )
        for spec in reels
    ]
    return {
        "branch": branch,
        "customer": customer,
        "product": part,
        "index": index_entry,
        "truck": truck,
        "reels": received,
        "branch_ops": make_branch_ops_headers(branch["id"]),
        "driver": make_driver_headers(truck["id"]) if truck else None,
    }


def setup_converted_order(lines, reels=(), product=None, branch_overrides=None,
                          customer_overrides=None, truck_overrides=None,
                          index=("2026-07-30", 450), creator="rep-1",
                          issuer="rep-2") -> dict:
    """Everything setup_catalog builds, plus a quote carrying `lines` that has
    been issued and converted into a SalesOrder.

    Returns the scenario dict extended with quote, quote_lines, order and
    order_lines (ordered by line_number ascending).
    """
    scn = setup_catalog(
        product=product,
        branch_overrides=branch_overrides,
        customer_overrides=customer_overrides,
        index=index,
        truck_overrides=truck_overrides,
        reels=reels,
    )
    quote, quote_lines = build_quote(
        scn["customer"]["id"], scn["branch"]["id"], scn["product"]["id"],
        lines, creator=creator,
    )
    issue_quote(quote["id"], issuer=issuer)
    order = convert_quote(quote["id"], issuer=issuer)
    scn["quote"] = read_quote(quote["id"])
    scn["quote_lines"] = [read_quote_line(ql["id"]) for ql in quote_lines]
    scn["order"] = order
    scn["order_lines"] = list_order_lines(sales_order_id=order["id"])
    return scn


# ══════════════════════════════════════════════════════════════════════════
# Tier 3 — allocation, the commit fork and staging
# ══════════════════════════════════════════════════════════════════════════

def run_allocator(order_id, branch_id, policy="MINIMIZE_REMNANT",
                  expected_version=None) -> dict:
    """Run the allocator over one order. When no expected version is supplied
    the order's current version is read first."""
    if expected_version is None:
        expected_version = read_order(order_id)["version"]
    payload = allocate_payload(expected_version, allocation_policy=policy)
    return get_success_data(
        api_client.allocate_sales_order(
            order_id, payload, make_branch_ops_headers(branch_id)
        )
    )


def release_allocations(order_id, branch_id) -> dict:
    return get_success_data(
        api_client.release_allocations(order_id, make_branch_ops_headers(branch_id))
    )


def allocations_of_line(order_line_id, headers=None) -> list:
    """Allocations of one order line, ordered by sequence_no ascending."""
    return list_allocations(headers=headers, order_line_id=order_line_id)


def allocations_of_order(order_id, headers=None) -> list:
    return list_allocations(headers=headers, sales_order_id=order_id)


def commit_cut(allocation_id, branch_id, window_start, window_end) -> dict:
    return get_success_data(
        api_client.cut_allocation(
            allocation_id,
            cut_payload(window_start, window_end),
            make_branch_ops_headers(branch_id),
        )
    )


def commit_pick(allocation_id, branch_id) -> dict:
    return get_success_data(
        api_client.pick_allocation(allocation_id, make_branch_ops_headers(branch_id))
    )


def setup_allocated_order(lines, reels=(), policy="MINIMIZE_REMNANT",
                          **kwargs) -> dict:
    """A converted order that has been through one allocation run.

    Adds `allocations_by_line` — a list, one entry per order line, of that
    line's allocations ordered by sequence_no.
    """
    scn = setup_converted_order(lines, reels=reels, **kwargs)
    run_allocator(scn["order"]["id"], scn["branch"]["id"], policy=policy)
    scn["order"] = read_order(scn["order"]["id"])
    scn["order_lines"] = list_order_lines(sales_order_id=scn["order"]["id"])
    scn["allocations_by_line"] = [
        allocations_of_line(ol["id"]) for ol in scn["order_lines"]
    ]
    scn["allocations"] = [
        alloc for line in scn["allocations_by_line"] for alloc in line
    ]
    return scn


def setup_staged_order_by_pick(lines, reels=(), **kwargs) -> dict:
    """An allocated MASTER_REEL order whose every allocation has been picked,
    so the order has bubbled ALLOCATED -> STAGED."""
    scn = setup_allocated_order(lines, reels=reels, **kwargs)
    for alloc in scn["allocations"]:
        commit_pick(alloc["id"], scn["branch"]["id"])
    scn["order"] = read_order(scn["order"]["id"])
    scn["allocations"] = [read_allocation(a["id"]) for a in scn["allocations"]]
    return scn


def setup_staged_order_by_cut(lines, reels=(), cut_windows=None, **kwargs) -> dict:
    """An allocated CUT order whose every allocation has been cut in a
    non-colliding buffered window, so the order has bubbled to STAGED.

    `cut_windows` is a sequence of (start, end) pairs, one per allocation.
    """
    scn = setup_allocated_order(lines, reels=reels, **kwargs)
    windows = cut_windows or _default_cut_windows(len(scn["allocations"]))
    for alloc, (start, end) in zip(scn["allocations"], windows):
        commit_cut(alloc["id"], scn["branch"]["id"], start, end)
    scn["order"] = read_order(scn["order"]["id"])
    scn["allocations"] = [read_allocation(a["id"]) for a in scn["allocations"]]
    return scn


def _default_cut_windows(count):
    """Two-hour windows separated by two hours, so no buffered window can
    touch its neighbour on a branch of cut capacity one."""
    windows = []
    for i in range(count):
        hour = 8 + i * 4
        windows.append(
            (
                f"2026-08-02T{hour:02d}:00:00Z",
                f"2026-08-02T{hour + 1:02d}:00:00Z",
            )
        )
    return windows


# ══════════════════════════════════════════════════════════════════════════
# Tier 4 — delivery and the delivery cascade
# ══════════════════════════════════════════════════════════════════════════

def schedule_run(order_id, truck_id, branch_id, window_start, window_end,
                 jobsite_has_forklift=False,
                 jobsite_address=TEST_DEFAULTS["JOBSITE_ADDRESS"]) -> dict:
    payload = create_delivery_run_payload(
        order_id, truck_id, window_start, window_end,
        jobsite_address=jobsite_address,
        jobsite_has_forklift=jobsite_has_forklift,
    )
    return get_success_data(
        api_client.create_delivery_run(payload, make_branch_ops_headers(branch_id))
    )


def dispatch_run(run_id, truck_id) -> dict:
    return get_success_data(
        api_client.dispatch_delivery_run(run_id, make_driver_headers(truck_id))
    )


def deliver_run(run_id, truck_id) -> dict:
    return get_success_data(
        api_client.deliver_delivery_run(run_id, make_driver_headers(truck_id))
    )


def deliver_order(scn, window_start="2026-08-02T08:00:00Z",
                  window_end="2026-08-02T10:00:00Z",
                  jobsite_has_forklift=False) -> dict:
    """Schedule, dispatch and complete a run for a staged order, firing the
    whole delivery cascade. Returns the delivered run and refreshes the
    scenario's order."""
    run = schedule_run(
        scn["order"]["id"], scn["truck"]["id"], scn["branch"]["id"],
        window_start, window_end, jobsite_has_forklift=jobsite_has_forklift,
    )
    dispatch_run(run["id"], scn["truck"]["id"])
    deliver_run(run["id"], scn["truck"]["id"])
    scn["run"] = read_run(run["id"])
    scn["order"] = read_order(scn["order"]["id"])
    return scn["run"]


def setup_delivered_master_reel_order(lines=None, reels=None,
                                      truck_overrides=None, **kwargs) -> dict:
    """The canonical returnable shipment: a MASTER_REEL order picked whole,
    delivered on a boom-lift truck, leaving the reel ON_JOBSITE and the order
    DELIVERED / INVOICED with its deposit charged."""
    lines = lines or [{"put_up": "MASTER_REEL", "requested_length_ft": 2500}]
    reels = reels if reels is not None else [{"nominal_length_ft": 2500}]
    truck_overrides = truck_overrides if truck_overrides is not None else {
        "truck_code": "T-BOOM", "has_boom_lift": True, "max_reel_slots": 4,
    }
    scn = setup_staged_order_by_pick(
        lines, reels=reels, truck_overrides=truck_overrides, **kwargs
    )
    deliver_order(scn)
    scn["order_lines"] = list_order_lines(sales_order_id=scn["order"]["id"])
    scn["reels"] = [read_reel(r["id"]) for r in scn["reels"]]
    return scn


def return_reel(order_line_id, reel_id, branch_id, condition="GOOD") -> dict:
    return get_success_data(
        api_client.return_order_line_reel(
            order_line_id,
            return_reel_payload(reel_id, condition),
            make_branch_ops_headers(branch_id),
        )
    )
