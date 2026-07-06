"""Role-based access control (operation-level and ownership-level) and the state-vs-temporal
validation priority pairing.

Translates the priority-pair difficulty instance on the skip endpoint (queue A) plus RBAC-denial
corner instances (queue B).
"""
from test_helpers import (
    validate_error,
    ApiErrorId, make_admin_headers, make_customer_headers,
    create_box_item_payload,
    setup_open_box_no_run, setup_skipped_box,
    seed_zone, seed_plan, seed_meal, seed_customer, seed_subscription, seed_run, seed_box,
    set_clock, CUTOFF_AT,
)

ADMIN = make_admin_headers()


def test_customer_cannot_lock_box_returns_unauthorized(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to
    perform the requested operation — or a `Customer` attempts to act on a resource it does not
    own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_lock_box_returns_unauthorized
    """
    ctx = setup_open_box_no_run(api, clock_iso=CUTOFF_AT)  # box owned by the customer, at cutoff
    resp = api.lock_box(ctx["box_id"], make_customer_headers(ctx["cust_id"]))  # lock is admin-only
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_add_item_to_other_customers_box(api):
    """PRD §2.1: "A `Customer` may only read and act on resources that resolve to their own
    `X-User-ID`."
    PRD §2.1: "a `Customer` attempts to act on a resource it does not own — the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_add_item_to_other_customers_box
    """
    set_clock(api)
    zone = seed_zone(api)
    plan = seed_plan(api)
    meal = seed_meal(api, meal_code="M1", name="Meal 1")
    cust_a = seed_customer(api, zone["id"], email="a@x.com", full_name="Cust A")
    cust_b = seed_customer(api, zone["id"], email="b@x.com", full_name="Cust B")
    sub_a = seed_subscription(api, cust_a["id"], plan["id"])
    seed_run(api, meal["id"], open_run=True, par_total=100)
    box_a = seed_box(api, sub_a["id"], cust_a["id"])
    resp = api.create_box_item(
        box_a["id"], create_box_item_payload(meal["id"], 1),
        make_customer_headers(cust_b["id"]))  # B acts on A's box
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_state_beats_temporal_skip_already_skipped_past_cutoff(api):
    """PRD §2.9: "(4) state validity, that the target resource is in a state from which the
    requested transition is defined, yielding `ERR_INVALID_STATE`; (5) the selection-window
    cutoff check, yielding `ERR_CUTOFF_PASSED`". "A lower priority number wins on conflict, so a
    mid-flight state problem surfaces ahead of an allergen conflict, and both surface ahead of a
    sold-out condition."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_temporal_on_skip_rejected
    """
    ctx = setup_skipped_box(api, advance_past_cutoff=True)  # SKIPPED (state) AND past cutoff (temporal)
    resp = api.skip_box(ctx["box_id"], make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_skip_already_skipped_before_cutoff_invalid_state(api):
    """PRD §3.5: "A `Customer` may **skip** a week's box while it is still `OPEN`".
    PRD §2.9: "(4) state validity, that the target resource is in a state from which the
    requested transition is defined, yielding `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_temporal_on_skip_rejected
    """
    ctx = setup_skipped_box(api, advance_past_cutoff=False)  # SKIPPED, clock still before cutoff
    resp = api.skip_box(ctx["box_id"], make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
