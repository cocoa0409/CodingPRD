"""Quote lifecycle claims (PRD §2.10, §3.3): the revise/reissue negotiation
loop, one-live-quote uniqueness, optimistic concurrency on quote issue and
delivery, quote expiry vs. customer standing, and immediate consistency."""
from test_helpers import (
    TEST_USERS,
    accept_quote,
    create_deliver_payload,
    create_diagnosis_payload,
    create_motor,
    create_quote_issue_payload,
    create_shop,
    create_customer,
    diagnose_work_order,
    get_customer,
    get_work_order,
    get_work_order_version,
    intake_work_order,
    issue_quote,
    make_customer_headers,
    record_incoming_test,
    send_quote,
    set_clock,
    setup_awaiting_approval,
    setup_diagnosed_work_order,
    setup_quoted_work_order,
    setup_released_work_order,
    setup_work_order_intake,
    start_rewind,
    record_coil_data,
    record_final_test,
    release_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["service_manager_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
TECH = TEST_USERS["technician_headers"]


def _quoted_pair(priority="STANDARD"):
    """Work order in QUOTED with a live ISSUED quote."""
    return setup_quoted_work_order(priority=priority)


# ─── Revise cycle (Difficulty/non_linear_state_machine) ───

def test_revise_supersedes_quote_and_returns_work_order_to_quoted(api):
    """PRD §3.3: "Or the estimator revises: the quote moves to `SUPERSEDED`,
    the work order's `active_quote_id` is cleared, and the work order drops
    back from `AWAITING_APPROVAL` to `QUOTED`, ready for a fresh issuance —
    the revise loop can cycle as many times as negotiation requires."

    Design: Difficulty/non_linear_state_machine/quote_revise_cycle_supersedes_and_reissues
    """
    bundle = setup_awaiting_approval()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    quote_id = bundle["quote"]["id"]

    revised = validate_success(api.revise_quote(shop_id, wo_id, quote_id, ESTIMATOR), 200)
    assert revised["status"] == "SUPERSEDED"

    wo = validate_success(api.get_work_order(shop_id, wo_id, MANAGER), 200)
    assert wo["status"] == "QUOTED"
    assert wo["active_quote_id"] is None


def test_rediagnose_from_quoted_is_rejected(api):
    """PRD §3.2: "These four fields stay null on the work order until the
    moment diagnosis lands, at which point the status moves from
    `INCOMING_TEST` to `DIAGNOSED`."
    PRD §2.11: "then whether the target entity sits in a valid from-state for
    the requested transition, rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/non_linear_state_machine/quote_revise_cycle_supersedes_and_reissues
    """
    bundle = setup_awaiting_approval()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    validate_success(api.revise_quote(shop_id, wo_id, bundle["quote"]["id"], ESTIMATOR), 200)

    res = api.diagnose_work_order(shop_id, wo_id, create_diagnosis_payload(rewind_hours=6), TECH)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Expired accept beats HOLD (Difficulty/priority_pair) ───

def _hold_and_expired_quote_setup(api):
    """Customer in HOLD via a 32-day-overdue invoice; second work order with
    a sent quote now past its 30-day validity."""
    bundle = setup_released_work_order(
        rewind_hours=1, materials_cents=0, replacement_cost_cents=999999,
        motor_overrides={"rated_kw": 10, "frame_mm": 200, "manufacture_year": 2020},
    )
    shop = bundle["shop"]
    customer = bundle["customer"]
    # First order's invoice: issued 2026-08-01, due 2026-08-31, never paid.

    motor2 = create_motor(shop["id"], customer["id"], serial_number="M-8B", rated_kw=30)
    wo2 = intake_work_order(shop["id"], customer["id"], motor2["id"], "STANDARD")
    record_incoming_test(shop["id"], wo2["id"])
    diagnose_work_order(shop["id"], wo2["id"])
    quote2 = issue_quote(shop["id"], wo2["id"])  # issued 2026-08-01, expires 2026-08-31
    send_quote(shop["id"], wo2["id"], quote2["id"])

    set_clock("2026-10-02T00:00:00Z")
    customer_read = get_customer(shop["id"], customer["id"])
    assert customer_read["standing"] == "HOLD"  # invoice 32 days past due
    return shop, customer, wo2, quote2


def test_expired_quote_accept_returns_quote_expired_even_on_hold(api):
    """PRD §3.3: "The customer accepts: the quote must still be `ISSUED` and
    unexpired — acceptance at or after `expires_at` first auto-transitions the
    quote to `EXPIRED` and is then rejected with `ERR_QUOTE_EXPIRED`
    (HTTP 409) — and the customer's `standing` must not be `HOLD`, checked
    after the expiry check, with a `HOLD` rejected as `ERR_CUSTOMER_ON_HOLD`
    (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/quote_accept_expired_temporal_beats_hold_fiscal
    """
    shop, customer, wo2, quote2 = _hold_and_expired_quote_setup(api)
    res = api.accept_quote(shop["id"], wo2["id"], quote2["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_QUOTE_EXPIRED", expected_status=409)


def test_expired_quote_lazily_transitions_and_frees_work_order(api):
    """PRD §3.3: "Quote expiry itself is lazy, per §2.4: any access or
    acceptance attempt at or after `expires_at` moves an `ISSUED` quote to
    `EXPIRED`, clears `active_quote_id`, and returns a waiting work order from
    `AWAITING_APPROVAL` to `QUOTED`."

    Design: Difficulty/priority_pair_validation_conflict/quote_accept_expired_temporal_beats_hold_fiscal
    """
    shop, customer, wo2, quote2 = _hold_and_expired_quote_setup(api)
    res = api.accept_quote(shop["id"], wo2["id"], quote2["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_QUOTE_EXPIRED", expected_status=409)

    quote = validate_success(api.get_quote(shop["id"], wo2["id"], quote2["id"], ESTIMATOR), 200)
    assert quote["status"] == "EXPIRED"

    wo = validate_success(api.get_work_order(shop["id"], wo2["id"], MANAGER), 200)
    assert wo["status"] == "QUOTED"
    assert wo["active_quote_id"] is None


# ─── One live quote per work order (Difficulty/resource_temporal_overlap) ───

def test_second_quote_issue_rejected_while_first_is_issued(api):
    """PRD §3.3: "Only one live quote may exist per work order — attempting to
    issue while another quote for the same order is still `ISSUED` is rejected
    with `ERR_DUPLICATE_ACTIVE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/quote_single_live_interval_per_work_order
    """
    bundle = _quoted_pair()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]

    fresh_version = get_work_order_version(shop_id, wo_id)
    res = api.issue_quote(
        shop_id, wo_id, create_quote_issue_payload(fresh_version), ESTIMATOR
    )
    validate_error(res, "ERR_DUPLICATE_ACTIVE", expected_status=409)


def test_reissue_succeeds_after_revise_supersedes_live_quote(api):
    """PRD §3.3: "the revise loop can cycle as many times as negotiation
    requires."
    PRD §3.3: "On success the work order moves from `DIAGNOSED` to `QUOTED` —
    or simply stays `QUOTED` on a re-issue after a revise — its `version`
    increments by one, and its `active_quote_id` is set to the new quote".

    Design: Difficulty/resource_temporal_overlap/quote_single_live_interval_per_work_order
    """
    bundle = setup_awaiting_approval()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    validate_success(api.revise_quote(shop_id, wo_id, bundle["quote"]["id"], ESTIMATOR), 200)

    reissued = issue_quote(shop_id, wo_id)
    assert reissued["status"] == "ISSUED"
    assert reissued["id"] != bundle["quote"]["id"]


# ─── Single-active-quote conservation (Difficulty/compensating_invariant) ───

def test_revise_leaves_zero_live_quotes_and_nulls_active_quote(api):
    """PRD §3.3: "Or the estimator revises: the quote moves to `SUPERSEDED`,
    the work order's `active_quote_id` is cleared, and the work order drops
    back from `AWAITING_APPROVAL` to `QUOTED`, ready for a fresh issuance".

    Design: Difficulty/compensating_invariant/quote_revise_and_reissue_conserves_single_active_quote
    """
    bundle = setup_awaiting_approval()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    validate_success(api.revise_quote(shop_id, wo_id, bundle["quote"]["id"], ESTIMATOR), 200)

    data, _meta = validate_paginated(
        api.list_quotes(shop_id, wo_id, ESTIMATOR, params={"status": "ISSUED"})
    )
    assert data == [], "no ISSUED quote may survive a revise"
    wo = validate_success(api.get_work_order(shop_id, wo_id, MANAGER), 200)
    assert wo["active_quote_id"] is None


def test_reissue_restores_exactly_one_live_quote(api):
    """PRD §3.3: "its `active_quote_id` is set to the new quote, which is
    computed and moved from `DRAFT` to `ISSUED` in a single step with
    `issued_at` stamped at the current instant and `expires_at` set thirty
    days later."

    Design: Difficulty/compensating_invariant/quote_revise_and_reissue_conserves_single_active_quote
    """
    bundle = setup_awaiting_approval()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    validate_success(api.revise_quote(shop_id, wo_id, bundle["quote"]["id"], ESTIMATOR), 200)
    reissued = issue_quote(shop_id, wo_id)

    data, _meta = validate_paginated(
        api.list_quotes(shop_id, wo_id, ESTIMATOR, params={"status": "ISSUED"})
    )
    assert [q["id"] for q in data] == [reissued["id"]]
    old = validate_success(
        api.get_quote(shop_id, wo_id, bundle["quote"]["id"], ESTIMATOR), 200
    )
    assert old["status"] == "SUPERSEDED"
    wo = validate_success(api.get_work_order(shop_id, wo_id, MANAGER), 200)
    assert wo["active_quote_id"] == reissued["id"]


# ─── OCC on quote issue (Corner/errors) ───

def test_stale_version_on_quote_issue_rejected(api):
    """PRD §2.10: "Issuing a quote against a work order requires the request
    to carry `expected_work_order_version`, the client's last observed
    `version` of that work order; if the work order's version has advanced
    since — for instance because another estimator has just issued a quote,
    which legitimately sets `active_quote_id` and bumps the version — the
    issuance is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/err_stale_version_on_quote_issue
    """
    bundle = setup_work_order_intake()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    record_incoming_test(shop_id, wo_id)
    stale_version = get_work_order_version(shop_id, wo_id)
    # The diagnose transition mutates the work order and advances its version.
    diagnose_work_order(shop_id, wo_id)

    res = api.issue_quote(
        shop_id, wo_id, create_quote_issue_payload(stale_version), ESTIMATOR
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── HOLD customer accept (Corner/validations) ───

def test_quote_accept_when_customer_on_hold_returns_402(api):
    """PRD §3.3: "and the customer's `standing` must not be `HOLD`, checked
    after the expiry check, with a `HOLD` rejected as `ERR_CUSTOMER_ON_HOLD`
    (HTTP 402)."
    PRD §3.5: "It is `HOLD` when any of their invoices is more than thirty
    days past its `due_at` — exactly thirty days past due is not enough."

    Design: Corner/validations/quote_accept_when_customer_on_hold_returns_402
    """
    bundle = setup_released_work_order(
        rewind_hours=5, materials_cents=10000, replacement_cost_cents=999999,
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020},
    )
    shop, customer = bundle["shop"], bundle["customer"]
    set_clock("2026-10-02T00:00:00Z")  # invoice due 2026-08-31: 32 days overdue

    standing = validate_success(api.get_customer(shop["id"], customer["id"], MANAGER), 200)
    assert standing["standing"] == "HOLD"

    motor2 = create_motor(shop["id"], customer["id"], serial_number="M-H2", rated_kw=30)
    wo2 = intake_work_order(shop["id"], customer["id"], motor2["id"], "STANDARD")
    record_incoming_test(shop["id"], wo2["id"])
    diagnose_work_order(shop["id"], wo2["id"])
    quote2 = issue_quote(shop["id"], wo2["id"])  # fresh quote, 30-day validity
    send_quote(shop["id"], wo2["id"], quote2["id"])

    res = api.accept_quote(
        shop["id"], wo2["id"], quote2["id"], make_customer_headers(customer["id"])
    )
    validate_error(res, "ERR_CUSTOMER_ON_HOLD", expected_status=402)


# ─── OCC on delivery (Corner/cross_cutting_layers) ───

def test_deliver_stale_version_rejected_then_fresh_succeeds(api):
    """PRD §2.10: "Delivering a work order likewise requires
    `expected_work_order_version` matching the work order's current `version`;
    if the version has advanced since the delivering manager last read it —
    for instance because a warranty-driven resolution order or an invoice void
    bumped it — the delivery is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "On success the work order's `version` increments by one,
    `delivered_at` is stamped, the motor's custody returns to `WITH_CUSTOMER`,
    the status becomes `DELIVERED`".

    Design: Corner/cross_cutting_layers/occ_deliver_stale_version_rejected
    """
    bundle = setup_diagnosed_work_order()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    stale_version = bundle["work_order"]["version"]

    # Drive the order to READY_FOR_PICKUP; every step advances the version.
    quote = issue_quote(shop_id, wo_id)
    send_quote(shop_id, wo_id, quote["id"])
    accept_quote(shop_id, wo_id, quote["id"], bundle["customer"]["id"])
    start_rewind(shop_id, wo_id)
    record_coil_data(shop_id, wo_id)
    record_final_test(shop_id, wo_id, 2.0)
    release_work_order(shop_id, wo_id)

    res = api.deliver_work_order(
        shop_id, wo_id, create_deliver_payload(stale_version), MANAGER
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    fresh_version = get_work_order_version(shop_id, wo_id)
    delivered = validate_success(
        api.deliver_work_order(shop_id, wo_id, create_deliver_payload(fresh_version), MANAGER),
        200,
    )
    assert delivered["status"] == "DELIVERED"
    assert delivered["version"] == fresh_version + 1


# ─── Version increments on mutation (Corner/cross_cutting_layers) ───

def test_work_order_version_increments_on_every_mutation(api):
    """PRD §2.5: "Any mutation of a work order, including automatic cascades
    such as the rework loop or a quote issuance side effect, refreshes the
    work order's `updated_at` and increments its `version`."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    bundle = setup_work_order_intake()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    v_create = bundle["work_order"]["version"]

    record_incoming_test(shop_id, wo_id)   # INTAKE -> INCOMING_TEST
    diagnose_work_order(shop_id, wo_id)    # INCOMING_TEST -> DIAGNOSED

    wo = validate_success(api.get_work_order(shop_id, wo_id, MANAGER), 200)
    assert wo["version"] == v_create + 2


# ─── Immediate consistency (Corner/consistency_model) ───

def test_quote_accept_effects_visible_immediately(api):
    """PRD §3.3: "Acceptance moves the quote to `ACCEPTED` and the work order
    to `APPROVED`."

    Design: Corner/consistency_model/quote_accept_effects_visible_immediately
    """
    bundle = setup_awaiting_approval()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    quote_id = bundle["quote"]["id"]

    accepted = validate_success(
        api.accept_quote(shop_id, wo_id, quote_id, make_customer_headers(bundle["customer"]["id"])),
        200,
    )
    assert accepted["status"] == "ACCEPTED"

    wo = validate_success(api.get_work_order(shop_id, wo_id, MANAGER), 200)
    assert wo["status"] == "APPROVED"
    assert wo["active_quote_id"] == quote_id
