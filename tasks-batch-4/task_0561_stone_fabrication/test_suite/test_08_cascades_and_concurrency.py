"""The change-order reopen cascade (depth 4), the CLOSED-project state guard outranking the
fiscal amount check, and optimistic-concurrency version control on the project."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_quote_payload, create_change_order_payload, create_payment_payload,
    setup_scheduled_fab, setup_closed_project, new_project, add_active_quote,
)


# --------------------------------------------------------------------------
# Difficulty/transitive_cascade — change-order approve reopen cascade (depth 4)
# --------------------------------------------------------------------------
def test_reopen_cascade_applies_order_and_reopens_template(api, salesrep_headers):
    """PRD §3.7: "On approval the order moves to `APPLIED`, the project's `final_invoice_cents`
    is recomputed to include the new delta line (taxed per line as in §3.3) and
    `balance_due_cents` is refreshed."
    PRD §3.7: "When the applied order's `reopens_template` is true, the full reopen cascade
    fires: the project's `APPROVED` template returns to `MEASURED`, the project's linked
    fabrication order is cancelled if it is still in `SCHEDULED`, `CUTTING`, `RECUTTING`, or
    `QC_PASSED` (which releases its reserved slab back to `IN_STOCK` per §3.5), and the
    project's `status` becomes `ON_HOLD`."

    Design: Difficulty/transitive_cascade/change_order_approve_reopen_cascade_depth4
    """
    from test_helpers import add_change_order
    ctx = setup_scheduled_fab(nominal_sqft=50)
    co = add_change_order(ctx["p_id"], delta_cents=50000, reopens_template=True, description="add island")
    applied = validate_success(api.approve_change_order(co["id"], TEST_USERS["shopmanager_headers"]))
    assert applied["status"] == "APPLIED"
    template = validate_success(api.get_template(ctx["t_id"], salesrep_headers))
    assert template["status"] == "MEASURED"
    fab = validate_success(api.get_fabrication_order(ctx["f_id"], salesrep_headers))
    assert fab["status"] == "CANCELLED"


def test_reopen_cascade_releases_slab_and_holds_project(api, salesrep_headers, fabricator_headers):
    """PRD §3.7: "When the applied order's `reopens_template` is true, the full reopen cascade
    fires: the project's `APPROVED` template returns to `MEASURED`, the project's linked
    fabrication order is cancelled if it is still in `SCHEDULED`, `CUTTING`, `RECUTTING`, or
    `QC_PASSED` (which releases its reserved slab back to `IN_STOCK` per §3.5), and the
    project's `status` becomes `ON_HOLD`."
    PRD §2.7: "If the allocating order is cancelled, the slab returns to `IN_STOCK` with
    `reserved_sqft` reset to 0 and `remaining_sqft` restored to the full `nominal_sqft`."

    Design: Difficulty/transitive_cascade/change_order_approve_reopen_cascade_depth4
    """
    from test_helpers import add_change_order
    ctx = setup_scheduled_fab(nominal_sqft=50)
    co = add_change_order(ctx["p_id"], delta_cents=50000, reopens_template=True, description="add island")
    api.approve_change_order(co["id"], TEST_USERS["shopmanager_headers"])
    slab = validate_success(api.get_slab(ctx["sl_id"], fabricator_headers))
    assert slab["status"] == "IN_STOCK"
    assert slab["reserved_sqft"] == pytest.approx(0, abs=0.005)
    assert slab["remaining_sqft"] == pytest.approx(50.00, abs=0.005)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["status"] == "ON_HOLD"


# --------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict — CLOSED state beats fiscal amount
# --------------------------------------------------------------------------
def test_closed_project_payment_zero_amount_returns_project_closed(api, salesrep_headers):
    """PRD §3.2: "Before a payment is accepted, several checks run in order. The project must not
    be `CLOSED`. There must be an `ACTIVE` quote to price against, or the payment is rejected
    with `ERR_QUOTE_REQUIRED` (409). The `amount_cents` must be strictly greater than zero, or
    the payment is rejected with `ERR_INVALID_AMOUNT` (422)."
    PRD §2.9: "any mutating operation directed at a `CLOSED` project is rejected with
    `ERR_PROJECT_CLOSED` (HTTP 409); this guard applies to recording a payment."

    The CLOSED check runs before the amount check, so amount_cents=0 still yields
    ERR_PROJECT_CLOSED, not ERR_INVALID_AMOUNT.

    Design: Difficulty/priority_pair_validation_conflict/state_closed_beats_fiscal_invalid_amount_on_payment
    """
    ctx = setup_closed_project()
    resp = api.create_payment(
        ctx["p_id"], create_payment_payload(amount_cents=0, kind="BALANCE"), salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_PROJECT_CLOSED)


def test_closed_project_rejects_wellformed_payment(api, salesrep_headers):
    """PRD §2.9: "any mutating operation directed at a `CLOSED` project is rejected with
    `ERR_PROJECT_CLOSED` (HTTP 409); this guard applies to recording a payment, creating a
    quote, creating a change order, and recording a template on that project."

    The setup drives the project to CLOSED; even a well-formed payment is rejected by the
    CLOSED guard.

    Design: Difficulty/priority_pair_validation_conflict/state_closed_beats_fiscal_invalid_amount_on_payment
    """
    ctx = setup_closed_project()
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["status"] == "CLOSED"
    resp = api.create_payment(
        ctx["p_id"], create_payment_payload(amount_cents=100, kind="BALANCE"), salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_PROJECT_CLOSED)


# --------------------------------------------------------------------------
# Corner/cross_cutting — optimistic concurrency (OCC)
# --------------------------------------------------------------------------
def test_quote_create_stale_project_version_returns_412(api, salesrep_headers):
    """PRD §2.8: "a request to add a quote to a project must present `expected_project_version`
    equal to the project's current `version`. If another writer has advanced the project's
    `version` since the client last read it — for instance by creating a newer quote that
    already superseded the prior active one — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412), because the stale caller has not observed the supersede that already occurred."

    Design: Corner/cross_cutting/quote_create_stale_project_version_returns_412
    """
    p = new_project(material_grade="PREMIUM")
    stale_version = p["version"]  # version 1
    add_active_quote(p["id"], stale_version)  # advances project version to 2
    resp = api.create_quote(
        p["id"],
        create_quote_payload(
            expected_project_version=stale_version, est_sqft=45, material_grade="PREMIUM",
            edge_profile="OGEE", edge_linear_ft=25, sink_count=1, faucet_count=0, cooktop_count=0),
        salesrep_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_change_order_create_stale_project_version_returns_412(api, salesrep_headers):
    """PRD §2.8: "The second is change-order creation: a request to add a change order must
    likewise present `expected_project_version` matching the project's current `version`, and a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a change order is priced
    against the project's current invoice basis and a stale version means the client's view of
    that basis is out of date."

    Design: Corner/cross_cutting/change_order_create_stale_project_version_returns_412
    """
    p = new_project(material_grade="PREMIUM")
    add_active_quote(p["id"], p["version"])
    proj = validate_success(api.get_project(p["id"], salesrep_headers))
    captured_version = proj["version"]
    # First change order consumes captured_version and advances the project version.
    validate_success(api.create_change_order(
        p["id"],
        create_change_order_payload(expected_project_version=captured_version, description="first", delta_cents=1000),
        salesrep_headers), expected_status=201)
    # Second change order still carries the now-stale captured_version.
    resp = api.create_change_order(
        p["id"],
        create_change_order_payload(expected_project_version=captured_version, description="second stale", delta_cents=2000),
        salesrep_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_project_version_increments_on_quote_create(api, salesrep_headers):
    """PRD §2.4: "an integer `version` that begins at 1 and increments by one on each mutation."
    PRD §2.4: "Whenever the server recomputes a derived field on an entity — for example
    refreshing a project's `payment_status`, `balance_due_cents`, or `final_invoice_cents` ...
    that recomputation counts as a mutation of the owning entity: its `updated_at` is refreshed
    and its `version` increments."

    Creating a quote recomputes the project's balance and advances version 1 -> 2.

    Design: Corner/cross_cutting/project_version_increments_on_quote_create
    """
    p = new_project(material_grade="PREMIUM")
    assert p["version"] == 1
    add_active_quote(p["id"], p["version"])
    proj = validate_success(api.get_project(p["id"], salesrep_headers))
    assert proj["version"] == 2
