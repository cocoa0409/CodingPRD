"""Promise-to-pay: half-open coverage windows, overlap guard, the kept
transition, the domain-specific already-resolved guard, and OCC on creation.

Queue A (Difficulty): half-open window overlap rejection (and adjacency allowed).
Queue B (Corner): promise KEPT, cancel-on-non-active domain error, stale-version
on create, version increments on each customer mutation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_customer,
    create_invoice,
    create_payment,
    apply_payment,
    create_promise,
    current_customer_version,
    create_promise_payload,
)


# --------------------------------------------------------------------------- #
# Queue A — half-open promise window overlap
# --------------------------------------------------------------------------- #
def test_promise_window_overlap_rejected(api, collections_agent_headers):
    """PRD §3.5: "a new `ACTIVE` promise's window must not overlap any other
    `ACTIVE` promise window for the same customer; abutting windows where one
    ends exactly as the next begins are allowed, but any true overlap is rejected
    with `ERR_PROMISE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/promise_coverage_window_half_open_overlap_rejected
    """
    customer = create_customer(name="PW")
    create_promise(
        customer["id"], 30_000,
        "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z",
    )
    version = current_customer_version(customer["id"])
    res = api.create_promise(
        create_promise_payload(
            customer["id"], version,
            promised_amount_cents=30_000,
            coverage_start="2026-06-10T00:00:00Z",
            coverage_end="2026-06-20T00:00:00Z",
        ),
        collections_agent_headers,
    )
    validate_error(res, "ERR_PROMISE_WINDOW_OVERLAP")


def test_promise_window_adjacent_abutting_allowed(api, collections_agent_headers):
    """PRD §3.5: "abutting windows where one ends exactly as the next begins are
    allowed, but any true overlap is rejected with `ERR_PROMISE_WINDOW_OVERLAP`".

    A window starting exactly at the prior window's exclusive end does not
    overlap (half-open semantics), so the create succeeds.

    Design: Difficulty/resource_temporal_overlap/promise_coverage_window_half_open_overlap_rejected
    """
    customer = create_customer(name="PWadj")
    create_promise(
        customer["id"], 30_000,
        "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z",
    )
    version = current_customer_version(customer["id"])
    res = api.create_promise(
        create_promise_payload(
            customer["id"], version,
            promised_amount_cents=30_000,
            coverage_start="2026-06-15T00:00:00Z",  # == prior coverage_end
            coverage_end="2026-06-30T00:00:00Z",
        ),
        collections_agent_headers,
    )
    promise = validate_success(res, 201)
    assert promise["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Queue B — corner cases
# --------------------------------------------------------------------------- #
def test_promise_kept_when_payment_covers_within_window(api, ar_manager_headers, ar_clerk_headers, collections_agent_headers):
    """PRD §3.5: "Evaluation only acts on an `ACTIVE` promise once the clock is
    at or past `coverage_end`: if `applied_payment_cents` is at or above
    `promised_amount_cents`, the promise is `KEPT`".

    Design: Corner/state_machines/promise_kept_when_payment_covers_within_window
    """
    set_clock("2026-06-05T00:00:00Z")
    customer = create_customer(name="PK")
    invoice = create_invoice(
        customer["id"], face_amount_cents=5000,
        invoice_date="2026-04-01T00:00:00Z", due_date="2026-05-01T00:00:00Z",
    )
    promise = create_promise(
        customer["id"], 5000,
        "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z",
    )
    payment = create_payment(customer["id"], amount_cents=5000, received_at="2026-06-05T00:00:00Z")
    apply_payment(payment["id"], invoice["id"], 5000)
    set_clock("2026-06-20T00:00:00Z")  # past coverage_end
    evaluated = validate_success(api.evaluate_promise(promise["id"], collections_agent_headers), 200)
    assert evaluated["status"] == "KEPT"


def test_cancel_non_active_promise_returns_domain_error(api, collections_agent_headers):
    """PRD §3.5: "calling either on a promise that is not `ACTIVE` is rejected
    with `ERR_PROMISE_ALREADY_RESOLVED` (HTTP 409), not `ERR_INVALID_STATE`."

    Design: Corner/state_machines/promise_cancel_on_non_active_returns_domain_error
    """
    customer = create_customer(name="PC")
    promise = create_promise(
        customer["id"], 5000,
        "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z",
    )
    validate_success(api.cancel_promise(promise["id"], collections_agent_headers), 200)
    res = api.cancel_promise(promise["id"], collections_agent_headers)  # already CANCELLED
    validate_error(res, "ERR_PROMISE_ALREADY_RESOLVED")


def test_stale_version_on_promise_create(api, collections_agent_headers):
    """PRD §2.9: "If they do not match — because another writer has already added
    a promise to that customer and thereby advanced the customer's `version`
    since the client read it — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".
    PRD §2.9: "On a successful create, the customer's `version` is incremented by
    one."

    Design: Corner/errors/error_stale_version_on_promise_create
    """
    customer = create_customer(name="SV")
    v0 = customer["version"]
    # First create advances customer.version, so v0 is now stale.
    create_promise(
        customer["id"], 5000,
        "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z",
        expected_version=v0,
    )
    res = api.create_promise(
        create_promise_payload(
            customer["id"], v0,  # stale token
            promised_amount_cents=5000,
            coverage_start="2026-07-01T00:00:00Z",
            coverage_end="2026-07-15T00:00:00Z",
        ),
        collections_agent_headers,
    )
    validate_error(res, "ERR_STALE_VERSION")


def test_customer_version_increments_on_each_mutation(api, ar_manager_headers):
    """PRD §2.4: "`version` — an integer that starts at its initial value and
    increments by one on every mutation of the resource."
    PRD §2.6: "Each such recomputation that alters the customer is a mutation of
    the customer: it refreshes the customer's `updated_at` and increments the
    customer's `version`."

    A hold then a release-hold are two direct customer mutations: version goes
    1 -> 2 -> 3.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_customer_mutation
    """
    customer = create_customer(name="VC")
    assert customer["version"] == 1
    held = validate_success(api.hold_customer(customer["id"], ar_manager_headers), 200)
    assert held["version"] == 2
    released = validate_success(api.release_hold_customer(customer["id"], ar_manager_headers), 200)
    assert released["version"] == 3
