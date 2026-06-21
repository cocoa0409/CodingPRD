"""RBAC peer-role enforcement, authentication, body-FK existence, and the
released-WO cancel-after-disposition guard.

Translates queue B section `rbac`, the remaining `errors` and `state_machines`
instances not covered elsewhere.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_approved_quote, create_submitted_rfq_with_part_line,
    create_draft_quote, add_routing_op,
    create_rfq_payload, create_quote_payload, create_inspection_station_payload,
    create_work_order_payload,
    TEST_USERS, ZERO_UUID,
)

ADMIN = TEST_USERS["shop_admin_headers"]
EST = TEST_USERS["estimator_headers"]
SCHED = TEST_USERS["scheduler_headers"]
INSP = TEST_USERS["inspector_headers"]


def test_estimator_cannot_create_workorder(api):
    """PRD §2.1: "ShopAdmin is the operational owner of the RFQ lifecycle, the
    work-order lifecycle, routing-operation completion, shipping, and invoicing".
    PRD §2.9: "Authorization — the acting role must be permitted for the
    operation; otherwise ERR_UNAUTHORIZED (403)."

    Design: Corner/rbac/estimator_cannot_create_workorder
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-30",
    )
    res = api.create_work_order(
        create_work_order_payload(quote["id"], pl["id"], 3, 3), EST)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_shopadmin_cannot_price_quote(api):
    """PRD §2.1: "ShopAdmin ... does not price or approve quotes, book machine
    slots, allocate material, or disposition inspections; those capabilities
    belong exclusively to their respective owner roles."
    PRD §2.1: "Estimator owns the entire quoting flow."

    Design: Corner/rbac/shopadmin_cannot_price_quote
    """
    rfq, pl, quote = create_draft_quote(
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-31",
    )
    add_routing_op(quote["id"], seq=1, machine_class="MILL_3AX",
                   estimated_cycle_min=4.0, setup_fee_cents=1000)
    res = api.price_quote(quote["id"], ADMIN)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_scheduler_cannot_allocate_material(api):
    """PRD §2.1: "MaterialController owns material receipt and allocation."
    PRD §2.9: "the acting role must be permitted for the operation; otherwise
    ERR_UNAUTHORIZED (403)."

    Design: Corner/rbac/scheduler_cannot_allocate_material
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-32",
    )
    # MaterialController receives a lot so material is available; WO is PLANNED.
    api.create_material_lot(
        {"material_spec": "AL_6061", "heat_number": "H-Rbac3", "qty_received": 3,
         "unit_cost_cents": 800, "received_at": "2026-06-01T00:00:00Z"},
        TEST_USERS["material_controller_headers"])
    wo = validate_success(api.create_work_order(
        create_work_order_payload(quote["id"], pl["id"], 3, 3), ADMIN), 201)
    res = api.allocate_material(wo["id"], SCHED)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or empty on an operation that
    requires authentication, the request is rejected with ERR_UNAUTHENTICATED."
    PRD §2.9: "Authentication — X-User-Role and X-User-ID must both be present;
    otherwise ERR_UNAUTHENTICATED (401)."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    res = api.create_rfq(create_rfq_payload(customer_id="C-33"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_inspector_and_shopadmin_share_station_create(api):
    """PRD §2.1: "inspection-station creation is shared between ShopAdmin and
    Inspector."
    PRD §3.5: "A station is created — by a ShopAdmin or an Inspector".

    Both roles' creates return 201.

    Design: Corner/rbac/inspector_and_shopadmin_share_station_create
    """
    res_insp = api.create_inspection_station(
        create_inspection_station_payload(name="S-Insp", supports_mode="ALL", buffer_min=15), INSP)
    validate_success(res_insp, 201)
    res_admin = api.create_inspection_station(
        create_inspection_station_payload(name="S-Admin", supports_mode="ALL", buffer_min=15), ADMIN)
    station = validate_success(res_admin, 201)
    assert station["name"] == "S-Admin"


def test_create_quote_with_nonexistent_part_line_not_found(api):
    """PRD §2.4: "The same existence discipline extends to foreign keys supplied
    in a request body: every referenced resource named in the path is checked
    first, then every referenced resource named in the body, and any missing
    reference yields ERR_NOT_FOUND."

    Design: Corner/errors/create_quote_with_nonexistent_part_line_not_found
    """
    rfq, pl = create_submitted_rfq_with_part_line(
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3}, customer_id="C-36")
    res = api.create_quote(
        create_quote_payload(rfq["id"], ZERO_UUID,
                             material_unit_cost_cents=800, scrap_allowance_pct=0), EST)
    validate_error(res, "ERR_NOT_FOUND")


# NOTE: test_cancel_released_wo_after_disposition_rejected was DELETED.
# Per Step 7 STEP 1b (non-unique derivability — PRD internal contradiction):
# PRD §3.3 says a work order "may be cancelled ... while it is still PLANNED or
# RELEASED" and a RELEASED WO with "any inspection ... already DISPOSITIONED" is
# refused with ERR_WO_ALREADY_INSPECTED. But PRD §3.5 gates disposition on "the
# work order must be IN_PROCESS, failing with ERR_WO_NOT_IN_PROCESS" — so an
# inspection can only become DISPOSITIONED after the WO has left RELEASED for
# IN_PROCESS. A RELEASED WO therefore can never carry a DISPOSITIONED inspection,
# and a faithful PRD-only implementer who reads "PLANNED or RELEASED" literally
# correctly rejects the cancel of the IN_PROCESS WO this test builds with the
# state-legality error ERR_INVALID_STATE (PRD §2.9 rule 5), never reaching the
# ERR_WO_ALREADY_INSPECTED branch. The asserted outcome is not uniquely
# determined by the PRD prose.
