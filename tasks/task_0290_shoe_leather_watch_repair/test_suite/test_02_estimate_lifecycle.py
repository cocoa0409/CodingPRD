"""Estimate lifecycle: the revision cycle, present preconditions, OCC on present,
owner-only approval, and the parts-cancel compensating invariant.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    create_service_type_payload, create_estimate_payload, present_estimate_payload,
    create_parts_order_payload,
    TEST_USERS, make_technician_headers, make_customer_headers,
    set_clock, create_customer, create_service_type, create_technician,
    create_ticket, add_item, add_service_line, create_draft_estimate,
    present_estimate, reject_estimate, get_ticket_version,
    setup_presented, setup_ticket_with_line,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ── Difficulty: estimate revision cycle (≥2 tests) ───────────────────────
def test_revision_present_returns_ticket_to_awaiting_approval(api):
    """PRD §3.3: "Rejection moves the estimate from `PRESENTED` to `REJECTED` and sends the ticket from `AWAITING_APPROVAL` back to `REVISION_REQUESTED`."
    PRD §3.3: "From `REVISION_REQUESTED` the technician drafts and presents a fresh estimate that supersedes the rejected one, closing the cycle `REVISION_REQUESTED → AWAITING_APPROVAL → REVISION_REQUESTED` until the customer finally approves."

    Design: Difficulty/non_linear_state_machine/repair_ticket_estimate_revision_cycle
    """
    s = setup_presented()
    ticket_id = s["ticket"]["id"]
    tech_id = s["technician"]["id"]
    cust_id = s["customer"]["id"]
    est1 = s["estimate"]

    reject_estimate(est1["id"], cust_id)
    ticket = validate_success(api.get_repair_ticket(ticket_id, FRONT_DESK), 200)
    assert ticket["repair_status"] == "REVISION_REQUESTED"

    est2 = create_draft_estimate(ticket_id, tech_id, supersedes_estimate_id=est1["id"])
    v = get_ticket_version(ticket_id)
    presented = validate_success(
        api.present_estimate(est2["id"], present_estimate_payload(v), make_technician_headers(tech_id)),
        200,
    )
    assert presented["status"] == "PRESENTED"
    ticket = validate_success(api.get_repair_ticket(ticket_id, FRONT_DESK), 200)
    assert ticket["repair_status"] == "AWAITING_APPROVAL"


def test_revision_number_increments_and_prior_superseded(api):
    """PRD §3.3: "A valid revision present also transitions that most recent rejected estimate from `REJECTED` to `SUPERSEDED`, and the new estimate's `revision_number` is the prior estimate's plus one."
    PRD §3.3: "A first estimate leaves `supersedes_estimate_id` null and is assigned `revision_number` 1; a revision takes the prior estimate's `revision_number` plus one."

    Design: Difficulty/non_linear_state_machine/repair_ticket_estimate_revision_cycle
    """
    s = setup_presented()
    ticket_id = s["ticket"]["id"]
    tech_id = s["technician"]["id"]
    cust_id = s["customer"]["id"]
    est1 = s["estimate"]
    assert est1["revision_number"] == 1

    reject_estimate(est1["id"], cust_id)
    est2 = create_draft_estimate(ticket_id, tech_id, supersedes_estimate_id=est1["id"])
    est2 = present_estimate(est2["id"], ticket_id, tech_id)
    assert est2["revision_number"] == 2

    est1_after = validate_success(api.get_estimate(est1["id"], FRONT_DESK), 200)
    assert est1_after["status"] == "SUPERSEDED"


# ── Corner: present without service lines ────────────────────────────────
def test_present_without_service_lines_rejected(api):
    """PRD §3.3: "Presenting additionally requires that at least one non-`VOIDED` service line exist on the ticket, failing with `ERR_NO_SERVICE_LINES` otherwise."

    Design: Corner/state_machines/present_without_service_lines_rejected
    """
    set_clock()
    customer = create_customer()
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    v = get_ticket_version(ticket["id"])
    res = api.present_estimate(est["id"], present_estimate_payload(v), make_technician_headers(tech["id"]))
    validate_error(res, "ERR_NO_SERVICE_LINES", 409)


# ── Corner: approve a never-presented (DRAFT) estimate ───────────────────
def test_approve_draft_estimate_invalid_state(api):
    """PRD §3.3: "Approval is permitted only while the ticket is in `AWAITING_APPROVAL` and the estimate is `PRESENTED`".

    A DRAFT estimate on an INTAKE ticket violates both the estimate-state and the
    ticket-state preconditions; PRD names both without committing a precedence,
    so either invalid-state error is faithful.

    Design: Corner/state_machines/approve_estimate_from_intake_invalid_state
    """
    set_clock()
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE")
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])

    res = api.approve_estimate(est["id"], make_customer_headers(customer["id"]))
    validate_error_is_one_of(res, ["ERR_INVALID_ESTIMATE_STATE", "ERR_INVALID_TICKET_STATE"])
    ticket_after = validate_success(api.get_repair_ticket(ticket["id"], FRONT_DESK), 200)
    assert ticket_after["repair_status"] == "INTAKE"


# ── Corner / difficulty: OCC stale version on present ────────────────────
def test_present_with_stale_ticket_version_rejected(api):
    """PRD §2.5: "Presenting an estimate requires `expected_ticket_version` to match the target ticket's current `version`; if another writer has already advanced the ticket's version since the technician last read it ... the present is rejected with `ERR_STALE_TICKET_VERSION`".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_ticket_version_on_present
    """
    set_clock()
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE")
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    # Bump the ticket version so the previously-read value is stale.
    patched = validate_success(
        api.patch_repair_ticket(ticket["id"], {"assigned_technician_id": tech["id"]}, FRONT_DESK),
        200,
    )
    stale = patched["version"] - 1
    res = api.present_estimate(est["id"], present_estimate_payload(stale), make_technician_headers(tech["id"]))
    validate_error(res, "ERR_STALE_TICKET_VERSION", 412)
    ticket_after = validate_success(api.get_repair_ticket(ticket["id"], FRONT_DESK), 200)
    assert ticket_after["repair_status"] == "INTAKE"


# ── Corner: non-owner customer cannot approve ────────────────────────────
def test_non_owner_customer_cannot_approve_estimate(api):
    """PRD §2.1: "approving or rejecting an estimate requires that the acting customer's `id` equal the owning ticket's `customer_id`, and a mismatch is rejected with `ERR_NOT_TICKET_OWNER`."

    Design: Corner/rbac/non_owner_customer_cannot_approve_estimate
    """
    s = setup_presented()
    stranger = create_customer(email="stranger_b@x.com")
    res = api.approve_estimate(s["estimate"]["id"], make_customer_headers(stranger["id"]))
    validate_error(res, "ERR_NOT_TICKET_OWNER", 403)
    ticket_after = validate_success(api.get_repair_ticket(s["ticket"]["id"], FRONT_DESK), 200)
    assert ticket_after["repair_status"] == "AWAITING_APPROVAL"


# ── Difficulty: parts order then cancel conserves parts_subtotal (≥2) ─────
def _setup_two_line_ticket():
    set_clock()
    customer = create_customer()
    st_shoe = create_service_type(base_price_cents=4000, item_category="SHOE")
    st_leather = create_service_type(base_price_cents=2500, item_category="LEATHER",
                                     standard_turnaround_days=2, warranty_days=30)
    tech = create_technician(skills=["SHOE", "LEATHER"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    item_shoe = add_item(ticket["id"], item_category="SHOE")
    item_leather = add_item(ticket["id"], item_category="LEATHER")
    line_a = add_service_line(ticket["id"], item_shoe["id"], st_shoe["id"], tech["id"])
    line_b = add_service_line(ticket["id"], item_leather["id"], st_leather["id"], tech["id"])
    return customer, tech, ticket, line_a, line_b


def test_first_estimate_parts_subtotal_zero_without_parts(api):
    """PRD §3.5: "Step two, the parts subtotal is the sum, over the parts orders in scope, of their `marked_up_cost_cents`."
    PRD §3.5: "the parts in scope are those with status `REQUESTED`, `ORDERED`, or `RECEIVED`."

    Design: Difficulty/compensating_invariant/parts_order_then_cancel_conserves_estimate_parts_subtotal
    """
    customer, tech, ticket, line_a, line_b = _setup_two_line_ticket()
    est1 = create_draft_estimate(ticket["id"], tech["id"])
    est1 = present_estimate(est1["id"], ticket["id"], tech["id"])
    assert est1["parts_subtotal_cents"] == 0
    reject_estimate(est1["id"], customer["id"])


def test_cancelled_part_excluded_from_revision_parts_subtotal(api):
    """PRD §3.4: "a cancelled order's `marked_up_cost_cents` is excluded from any subsequently presented estimate."
    PRD §3.5: "Step one, the labor subtotal is the sum, over the service lines in scope, of each line's price."

    Design: Difficulty/compensating_invariant/parts_order_then_cancel_conserves_estimate_parts_subtotal
    """
    customer, tech, ticket, line_a, line_b = _setup_two_line_ticket()
    est1 = create_draft_estimate(ticket["id"], tech["id"])
    est1 = present_estimate(est1["id"], ticket["id"], tech["id"])
    reject_estimate(est1["id"], customer["id"])

    # Request then cancel a part: it must not survive into the revision estimate.
    part = validate_success(
        api.create_parts_order(
            create_parts_order_payload(ticket["id"], line_a["id"], 800, 2),
            make_technician_headers(tech["id"]),
        ),
        201,
    )
    validate_success(api.cancel_part(part["id"], make_technician_headers(tech["id"])), 200)

    est2 = create_draft_estimate(ticket["id"], tech["id"], supersedes_estimate_id=est1["id"])
    est2 = present_estimate(est2["id"], ticket["id"], tech["id"])
    assert est2["parts_subtotal_cents"] == 0
    assert est2["estimate_total_cents"] == 6500
