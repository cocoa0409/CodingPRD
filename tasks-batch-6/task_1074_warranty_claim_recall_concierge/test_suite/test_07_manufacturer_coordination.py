"""Manufacturer coordination: RMA request gating, dispatch authorization gate, and
the full happy-path replacement dispatch.
"""
from test_helpers import (
    validate_success, validate_error,
    make_concierge_headers, make_manufacturer_agent_headers,
    setup_replacement_resolution_pending,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_request_rma_coordination_disabled_rejected(api):
    """PRD 3.8: "For a `REPLACEMENT` resolution, a `ConciergeAgent` first requests an
    RMA from the manufacturer; this is allowed only when the product's
    `Manufacturer.coordination_enabled` is true, and otherwise the request is rejected
    with `ERR_COORDINATION_DISABLED`."

    Design: Corner/endpoints/request_rma_coordination_disabled_rejected
    """
    ctx = setup_replacement_resolution_pending(coordination_enabled=False, rma_required=True,
                                               reviewer_id="cx-1", approver_id="cx-2")
    res = api.request_rma(ctx["res"]["id"], make_concierge_headers("cx-2"))
    validate_error(res, "ERR_COORDINATION_DISABLED")


def test_dispatch_replacement_without_rma_authorization_rejected(api):
    """PRD 3.8: "Dispatch also enforces the coordination gate: when the mode is
    `REPLACEMENT` and the product's `Manufacturer.rma_required` is true, the resolution's
    `rma_status` must be `AUTHORIZED`, and if it is not the dispatch is rejected with
    `ERR_RMA_NOT_AUTHORIZED`."

    Design: Corner/endpoints/dispatch_replacement_without_rma_authorization_rejected
    """
    ctx = setup_replacement_resolution_pending(coordination_enabled=True, rma_required=True,
                                               reviewer_id="cx-1", approver_id="cx-2")
    validate_success(api.request_rma(ctx["res"]["id"], make_concierge_headers("cx-2")), 200)
    res = api.dispatch_resolution(ctx["res"]["id"],
                                  {"replacement_product_id": ctx["replacement"]["id"]},
                                  make_concierge_headers("cx-2"))
    validate_error(res, "ERR_RMA_NOT_AUTHORIZED")


def test_manufacturer_coordination_happy_path_dispatch(api):
    """PRD 3.8: "The `ManufacturerAgent` then authorizes the RMA, setting `rma_status`
    to `AUTHORIZED` and recording an `rma_number` on the resolution."
    PRD 3.8: "Dispatching moves the resolution from `PENDING` to `DISPATCHED` and is
    performed by a `ConciergeAgent`. For a `REPLACEMENT`, the request supplies the
    `replacement_product_id` of the unit being shipped."

    Design: Corner/endpoints/manufacturer_coordination_happy_path_dispatch
    """
    ctx = setup_replacement_resolution_pending(coordination_enabled=True, rma_required=True,
                                               reviewer_id="cx-1", approver_id="cx-2")
    validate_success(api.request_rma(ctx["res"]["id"], make_concierge_headers("cx-2")), 200)
    validate_success(api.authorize_rma(ctx["res"]["id"],
                                       make_manufacturer_agent_headers(ctx["mfr"]["id"])), 200)
    dispatched = validate_success(
        api.dispatch_resolution(ctx["res"]["id"],
                                {"replacement_product_id": ctx["replacement"]["id"]},
                                make_concierge_headers("cx-2")), 200)
    assert dispatched["rma_status"] == "AUTHORIZED"
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["replacement_product_id"] == ctx["replacement"]["id"]
