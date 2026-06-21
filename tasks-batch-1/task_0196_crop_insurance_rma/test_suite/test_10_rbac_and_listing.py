"""Role-based access control and FK-filtered listing.

Covers authentication (missing headers), authorization (role attempting another role's
exclusive operation), and the assigned-adjuster filtered loss-claim listing
(PRD §2.1, §2.8, §4).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_reported_unit,
    register_selling_agent, register_producer, register_adjuster, create_program,
    file_loss_claim, make_agent_headers, make_lossadjuster_headers, TEST_USERS,
)

RMA = TEST_USERS["rma_admin_headers"]


def test_agent_cannot_open_program(api):
    """PRD §2.1: "When a well-authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with ERR_FORBIDDEN."
    PRD §4: "POST /commodity-programs/{id}/open | Open a program for sales | RmaAdmin"

    Design: Corner/rbac/rbac_agent_cannot_open_program
    """
    prog = get_success_data(api.create_commodity_program(
        {"crop_code": "CORN", "county_code": "19153", "crop_year": 2026,
         "projected_price": 4.00, "base_premium_rate": 0.085, "pp_coverage_factor": 0.60,
         "final_planting_date": "2026-05-31T00:00:00Z",
         "acreage_reporting_deadline": "2026-07-15T00:00:00Z"},
        RMA))
    sa = register_selling_agent(license_number="SA-RBAC1")
    res = api.open_commodity_program(prog["id"], make_agent_headers(sa["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    after = get_success_data(api.get_commodity_program(prog["id"], RMA))
    assert after["status"] == "DRAFT", after["status"]


def test_lossadjuster_cannot_create_policy(api):
    """PRD §2.1: "When a well-authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with ERR_FORBIDDEN."
    PRD §4: "POST /policies | Create a policy for a producer | Agent"

    Design: Corner/rbac/rbac_lossadjuster_cannot_create_policy
    """
    adj = register_adjuster(license_number="ADJ-RBAC2")
    producer = register_producer(tax_id="TX-RBAC2")
    res = api.create_policy(
        {"producer_id": producer["id"], "agent_id": adj["id"], "crop_year": 2026},
        make_lossadjuster_headers(adj["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must be authenticated with two mandatory HTTP headers:
    X-User-ID, which identifies the acting user, and X-User-Role, which declares the
    capacity in which they act. If either header is absent ... the request is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/rbac/rbac_missing_headers_returns_unauthenticated
    """
    res = api.get_policy("00000000-0000-4000-8000-000000000000", {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_list_loss_claims_filtered_by_assigned_adjuster(api):
    """PRD §4: "GET /loss-claims | List loss claims | RmaAdmin, Agent, LossAdjuster"
    PRD §3.6: "the assigned_adjuster_id naming the Agent record of the loss adjuster
    assigned at intake."

    Design: Corner/endpoints/list_loss_claims_filtered_by_assigned_adjuster
    """
    ctx = setup_reported_unit(plan_type="YP", acres=100, share=1,
                              clock="2026-06-01T00:00:00Z")
    claim = file_loss_claim(ctx["unit"]["id"], ctx["adj"]["id"], ctx["sa_headers"],
                            production_to_count_bu=9000)
    data, meta = validate_paginated(api.list_loss_claims(
        ctx["adj_headers"], params={"assigned_adjuster_id": ctx["adj"]["id"]}))
    ids = [c["id"] for c in data]
    assert claim["id"] in ids, ids
