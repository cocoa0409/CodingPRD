"""Exclusive allocation: remaining-units boundary, window overlap + buffer,
exclusivity/limit/open-window gating, and optimistic concurrency on the window
version."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_product, make_allocation_window,
    setup_open_exclusive_window, claim_allocation, get_window, set_clock,
)
from test_helpers.test_users import make_customer_headers


# ─── Difficulty/boundary_precision_check/allocation_claim_exact_remaining_boundary ───
def test_claim_exact_remaining_units_succeeds(api):
    """PRD §3.7: "the requested units must not exceed that remainder — a request
    exactly equal to the remainder is admissible."

    Design: Difficulty/boundary_precision_check/allocation_claim_exact_remaining_boundary
    """
    ctx = setup_open_exclusive_window(total_allocation=10, per_customer_cap=100, per_customer_limit=100)
    claim_allocation(ctx["win_id"], ctx["cust_id"], 10, ctx["win_version"])
    win = get_window(ctx["win_id"])
    assert win["claimed_units"] == 10


def test_claim_one_beyond_remaining_rejected(api):
    """PRD §3.7: "one unit beyond it is rejected with `ERR_ALLOCATION_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/allocation_claim_exact_remaining_boundary
    """
    ctx = setup_open_exclusive_window(total_allocation=10, per_customer_cap=100, per_customer_limit=100)
    claim_allocation(ctx["win_id"], ctx["cust_id"], 10, ctx["win_version"])
    current = get_window(ctx["win_id"])["version"]
    resp = api.create_claim(
        ctx["win_id"],
        {"customer_id": ctx["cust_id"], "units": 1, "expected_window_version": current},
        make_customer_headers(ctx["cust_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXHAUSTED, 409)


# ─── Difficulty/resource_temporal_overlap/allocation_window_closed_buffer_overlap ───
def _exclusive_product_with_window(api):
    prod = make_product(name="Excl2", brand="Maison", concentration="PARFUM",
                        is_exclusive=True, per_customer_limit=5)
    make_allocation_window(prod["id"], window_start="2026-07-01T00:00:00Z",
                           window_end="2026-07-10T00:00:00Z", total_allocation=10, per_customer_cap=5)
    return prod


def test_window_within_buffer_rejected(api):
    """PRD §3.7: "A new window must not overlap any existing window of the same
    product and must be separated from adjacent windows of that product by at
    least the allocation buffer of 24 hours (`ALLOCATION_BUFFER_HOURS` = 24
    hours); a violation is rejected with `ERR_ALLOCATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/allocation_window_closed_buffer_overlap
    """
    prod = _exclusive_product_with_window(api)
    resp = api.create_allocation_window(prod["id"], {
        "window_start": "2026-07-10T12:00:00Z", "window_end": "2026-07-20T00:00:00Z",
        "total_allocation": 10, "per_customer_cap": 5}, __merch())
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_WINDOW_OVERLAP, 409)


def test_window_beyond_buffer_allowed(api):
    """PRD §3.7: "must be separated from adjacent windows of that product by at
    least the allocation buffer of 24 hours (`ALLOCATION_BUFFER_HOURS` = 24
    hours)." — a window opening two days after the prior close clears the buffer.

    Design: Difficulty/resource_temporal_overlap/allocation_window_closed_buffer_overlap
    """
    prod = _exclusive_product_with_window(api)
    resp = api.create_allocation_window(prod["id"], {
        "window_start": "2026-07-12T00:00:00Z", "window_end": "2026-07-20T00:00:00Z",
        "total_allocation": 10, "per_customer_cap": 5}, __merch())
    win = validate_success(resp, 201)
    assert win["total_allocation"] == 10


# ─── Corner instances ─────────────────────────────────
def test_claim_non_exclusive_product_rejected(api):
    """PRD §3.7: "The target product must be exclusive, or the claim is rejected
    with `ERR_PRODUCT_NOT_EXCLUSIVE`."

    Design: Corner/validations/claim_non_exclusive_product_returns_422
    """
    ctx = setup_open_exclusive_window(total_allocation=10, per_customer_cap=5,
                                      per_customer_limit=None, is_exclusive=False)
    resp = api.create_claim(
        ctx["win_id"],
        {"customer_id": ctx["cust_id"], "units": 1, "expected_window_version": ctx["win_version"]},
        make_customer_headers(ctx["cust_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_EXCLUSIVE, 422)


def test_claim_exceeding_per_customer_limit_rejected(api):
    """PRD §3.7: "their cumulative units across all of this product's windows must
    not exceed the product's `per_customer_limit` (when that limit is set);
    reaching either limit exactly is allowed, exceeding it by one unit is rejected
    with `ERR_PER_CUSTOMER_LIMIT`."

    Design: Corner/validations/per_customer_limit_claim_returns_409
    """
    ctx = setup_open_exclusive_window(total_allocation=100, per_customer_cap=100, per_customer_limit=5)
    resp = api.create_claim(
        ctx["win_id"],
        {"customer_id": ctx["cust_id"], "units": 6, "expected_window_version": ctx["win_version"]},
        make_customer_headers(ctx["cust_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PER_CUSTOMER_LIMIT, 409)


def test_claim_closed_window_rejected(api):
    """PRD §3.7: "The window must currently be `OPEN` — a claim against a
    `SCHEDULED` or `CLOSED` window is rejected with
    `ERR_ALLOCATION_WINDOW_NOT_OPEN`."

    Design: Corner/errors/claim_closed_window_returns_409
    """
    ctx = setup_open_exclusive_window(total_allocation=10, per_customer_cap=5, per_customer_limit=5,
                                      window_start="2026-07-01T00:00:00Z",
                                      window_end="2026-07-05T00:00:00Z")
    set_clock("2026-07-10T00:00:00Z")
    resp = api.create_claim(
        ctx["win_id"],
        {"customer_id": ctx["cust_id"], "units": 1, "expected_window_version": ctx["win_version"]},
        make_customer_headers(ctx["cust_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_WINDOW_NOT_OPEN, 409)


def test_claim_stale_window_version_rejected(api):
    """PRD §2.6: "If `expected_window_version` does not equal the window's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/claim_stale_window_version_returns_412
    """
    ctx = setup_open_exclusive_window(total_allocation=100, per_customer_cap=100, per_customer_limit=100)
    claim_allocation(ctx["win_id"], ctx["cust_id"], 1, ctx["win_version"])
    resp = api.create_claim(
        ctx["win_id"],
        {"customer_id": ctx["cust_id"], "units": 1, "expected_window_version": ctx["win_version"]},
        make_customer_headers(ctx["cust_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_claim_with_current_window_version_succeeds(api):
    """PRD §3.7: "A successful claim creates an `AllocationClaim` recording its
    `window_id`, `customer_id`, and `units`, then increases the window's
    `claimed_units` by those units and increments the window's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/claim_correct_window_version_succeeds
    """
    ctx = setup_open_exclusive_window(total_allocation=100, per_customer_cap=100, per_customer_limit=100)
    claim_allocation(ctx["win_id"], ctx["cust_id"], 1, ctx["win_version"])
    reread = get_window(ctx["win_id"])
    wv1 = reread["version"]
    resp = api.create_claim(
        ctx["win_id"],
        {"customer_id": ctx["cust_id"], "units": 1, "expected_window_version": wv1},
        make_customer_headers(ctx["cust_id"]),
    )
    validate_success(resp, 201)
    final = get_window(ctx["win_id"])
    assert final["claimed_units"] == 2
    assert final["version"] == wv1 + 1


# ─── local helper ─────────────────────────────────────
def __merch():
    from test_helpers import TEST_USERS
    return TEST_USERS["merchandiser_headers"]
