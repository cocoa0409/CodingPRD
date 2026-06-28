"""Inspection findings, add-on approval cascade, finish preconditions, terminal lockdown.

Translates difficulty boundary_precision_check (finish with unresolved findings),
corner validations (resolve-addons exact-cover) and corner cross-cutting add-on cascade,
plus corner state_machines terminal-lockdown.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_customer_headers, make_mechanic_headers,
    create_catalog_part, setup_in_progress_request, add_finding,
    resolve_addons, finish_visit, setup_completed_request,
    create_finish_payload, create_resolve_addons_payload,
)
from test_helpers.test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_first_finding_moves_request_to_awaiting_addon_approval(api):
    """PRD §3.6: "Recording a finding is permitted only while the request is
    `IN_PROGRESS`, and the first proposed finding drives the request `IN_PROGRESS →
    AWAITING_ADDON_APPROVAL`, incrementing the request's `version`".

    Design: Difficulty/boundary_precision_check/finish_with_unresolved_findings_empty_set_edge
    """
    ctx = setup_in_progress_request(mechanic_rate=9000, email="m12b@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    add_finding(sr["id"], mechanic["id"], jv["id"], description="worn belt",
                add_on_labor_hours=0.5)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "AWAITING_ADDON_APPROVAL"


# ── Corner: resolve-addons exact-cover rule (omitted PROPOSED finding) ──

def test_resolve_addons_omits_proposed_finding_returns_validation_pending(api):
    """PRD §3.6: "The decisions must cover exactly the findings currently in `PROPOSED`:
    no proposed finding may be omitted, and no decision may reference a finding that is
    not currently proposed or that belongs to another request. A decisions list that
    fails this exact-cover rule is rejected with `ERR_VALIDATION_PENDING` (HTTP 422)."

    PRD §3.6: "Recording a finding is permitted only while the request is `IN_PROGRESS`,
    and the first proposed finding drives the request `IN_PROGRESS →
    AWAITING_ADDON_APPROVAL`" — so a request carries at most one PROPOSED finding at a
    time. The omission case is exercised by submitting an empty decisions list, which
    omits the single proposed finding and so fails the exact-cover rule.

    Design: Corner/validations/resolve_addons_omits_proposed_finding_returns_validation_pending
    """
    ctx = setup_in_progress_request(mechanic_rate=9000, email="c16@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    add_finding(sr["id"], mechanic["id"], jv["id"], description="finding A",
                add_on_labor_hours=0.5)

    res = api.resolve_addons(
        sr["id"], create_resolve_addons_payload([]),
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_VALIDATION_PENDING", expected_status=422)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "AWAITING_ADDON_APPROVAL"


# ── Corner: add-on resolution cascade spawns add-on PartLine ──

def test_addon_resolution_cascade_spawns_part_line(api):
    """PRD §3.6: "every approved finding that names a recommended part spawns a new
    `PartLine` with `is_addon` set to true, in `SOURCED` status, priced through the parts
    markup of §3.9".
    PRD §3.6: "When no proposed findings remain, the request returns
    `AWAITING_ADDON_APPROVAL → IN_PROGRESS` and the request's `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/addon_resolution_cascade_spawns_part_line
    """
    part = create_catalog_part(wholesale_cost_cents=4000, sku="AD1", name="Pad")
    ctx = setup_in_progress_request(mechanic_rate=9000, email="c28@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    finding = add_finding(sr["id"], mechanic["id"], jv["id"], description="needs pad",
                          recommended_part_id=part["id"], recommended_quantity=1,
                          add_on_labor_hours=0.5)
    resolve_addons(sr["id"], ctx["customer"]["id"],
                   [{"finding_id": finding["id"], "decision": "APPROVED"}])

    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "IN_PROGRESS"
    finding_after = validate_success(api.get_inspection_finding(finding["id"], DISPATCHER), 200)
    assert finding_after["status"] == "APPROVED"

    data, _meta = validate_paginated(
        api.list_service_request_part_lines(sr["id"], DISPATCHER))
    addons = [pl for pl in data if pl["is_addon"]]
    assert len(addons) == 1
    addon = addons[0]
    assert addon["status"] == "SOURCED"
    assert addon["unit_price_cents"] == 5800


# ── Corner: terminal lockdown — cancel a COMPLETED request ──

def test_cancel_completed_request_invalid_state(api):
    """PRD §3.2: "Cancellation is permitted only while the request is in `INTAKE`,
    `QUOTED`, or `APPROVED`."
    PRD §3.2: "`CANCELLED` and `COMPLETED` are the two terminal states of a service
    request."

    Design: Corner/state_machines/cancel_completed_request_invalid_state
    """
    ctx = setup_completed_request(mechanic_rate=9000, logged_labor_hours=1.0,
                                  payment_method="CARD", email="c10@x.com")
    sr = ctx["service_request"]
    assert sr["status"] == "COMPLETED"
    res = api.cancel_service_request(sr["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "COMPLETED"
