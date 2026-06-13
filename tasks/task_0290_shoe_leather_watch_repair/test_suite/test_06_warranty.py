"""Warranty adjudication: the approve/deny branch, the approval redo cascade
(spawn redo ticket + copy the failed line), at-cost parts markup on the redo,
and the not-picked-up filing guard.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    create_parts_order_payload, create_warranty_claim_payload,
    rule_warranty_claim_payload,
    TEST_USERS, make_technician_headers, make_customer_headers,
    set_clock, create_customer, create_service_type, create_technician,
    create_ticket, add_item, add_service_line, add_part, create_draft_estimate,
    present_estimate, approve_estimate, complete_line, capture_full_payment,
    setup_filed_warranty_claim, setup_ready_for_pickup,
    approve_claim, deny_claim,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ── Difficulty: warranty branch approve vs deny (≥2 tests) ───────────────
def test_warranty_approve_spawns_redo_ticket(api):
    """PRD §3.6: "Approving a filed claim moves it from `FILED` to `APPROVED` and drives a two-hop cascade: first, the system spawns a new no-charge redo `RepairTicket` ... and records that new ticket's `id` as the claim's `redo_ticket_id`".
    PRD §3.6: "Both rulings enforce segregation of duties: the `ruled_by_technician_id` must differ from the `authored_by_technician_id` of the original ticket's approved estimate".

    Design: Difficulty/non_linear_state_machine/warranty_claim_branch_approve_vs_deny
    """
    s = setup_filed_warranty_claim()
    res = api.approve_warranty_claim(
        s["claim"]["id"], rule_warranty_claim_payload(s["ruling_technician"]["id"]), SHOP_MANAGER
    )
    claim = validate_success(res, 200)
    assert claim["status"] == "APPROVED"
    assert claim["redo_ticket_id"] is not None


def test_warranty_deny_leaves_no_redo(api):
    """PRD §3.6: "Denying a filed claim moves it from `FILED` to `DENIED` and has no further effect — no redo ticket and no line copy."

    Design: Difficulty/non_linear_state_machine/warranty_claim_branch_approve_vs_deny
    """
    s = setup_filed_warranty_claim()
    res = api.deny_warranty_claim(
        s["claim"]["id"], rule_warranty_claim_payload(s["ruling_technician"]["id"]), SHOP_MANAGER
    )
    claim = validate_success(res, 200)
    assert claim["status"] == "DENIED"
    assert claim["redo_ticket_id"] is None


# ── Difficulty: redo spawn + line copy cascade depth-2 (≥2 tests) ────────
def test_redo_ticket_is_approved_rush_no_charge(api):
    """PRD §3.6: "the system spawns a new no-charge redo `RepairTicket` whose `repair_status` is `APPROVED`, whose `priority` is `RUSH`, whose `final_charge_cents` is 0, and whose `customer_id` is copied from the original ticket".

    Design: Difficulty/transitive_cascade/warranty_approve_spawn_redo_and_copy_line_depth2
    """
    s = setup_filed_warranty_claim()
    claim = validate_success(
        api.approve_warranty_claim(
            s["claim"]["id"], rule_warranty_claim_payload(s["ruling_technician"]["id"]), SHOP_MANAGER
        ),
        200,
    )
    redo = validate_success(api.get_repair_ticket(claim["redo_ticket_id"], FRONT_DESK), 200)
    assert redo["repair_status"] == "APPROVED"
    assert redo["priority"] == "RUSH"
    assert redo["final_charge_cents"] == 0
    assert redo["customer_id"] == s["customer"]["id"]


def test_redo_ticket_copies_failed_line_as_no_charge(api):
    """PRD §3.6: "second, caused by that spawn rather than by the claim directly, the failed service line is copied onto the redo ticket as a no-charge `QUOTED` line with `quoted_price_cents` of 0."

    Design: Difficulty/transitive_cascade/warranty_approve_spawn_redo_and_copy_line_depth2
    """
    s = setup_filed_warranty_claim()
    claim = validate_success(
        api.approve_warranty_claim(
            s["claim"]["id"], rule_warranty_claim_payload(s["ruling_technician"]["id"]), SHOP_MANAGER
        ),
        200,
    )
    data, _ = validate_paginated(
        api.list_service_lines(FRONT_DESK, params={"ticket_id": claim["redo_ticket_id"]})
    )
    assert len(data) >= 1
    redo_line = data[0]
    assert redo_line["status"] == "QUOTED"
    assert redo_line["quoted_price_cents"] == 0


# ── Difficulty: parts markup RETAIL vs WARRANTY_REDO diverge (≥2 tests) ──
def _setup_redo_with_retail_and_redo_part():
    """Original WATCH ticket carrying a RETAIL part (1000x2=2700), picked up within
    warranty, claim filed then approved -> redo ticket. Returns context incl. the
    retail part and the redo ticket's copied line id."""
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(item_category="WATCH", base_price_cents=1500,
                             standard_turnaround_days=1, warranty_days=90)
    tech_author = create_technician(display_name="Author", skills=["WATCH"])
    tech_ruler = create_technician(display_name="Ruler", skills=["WATCH"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech_author["id"])
    item = add_item(ticket["id"], item_category="WATCH")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech_author["id"])
    retail_part = add_part(ticket["id"], line["id"], 1000, 0, tech_author["id"], quantity=2)
    est = create_draft_estimate(ticket["id"], tech_author["id"])
    est = present_estimate(est["id"], ticket["id"], tech_author["id"])
    approve_estimate(est["id"], customer["id"])
    validate_success(api_client.order_part(retail_part["id"], make_technician_headers(tech_author["id"])), 200)
    validate_success(api_client.receive_part(retail_part["id"], make_technician_headers(tech_author["id"])), 200)
    validate_success(api_client.start_repair(ticket["id"], make_technician_headers(tech_author["id"])), 200)
    complete_line(line["id"], tech_author["id"])
    ready = validate_success(api_client.mark_ready(ticket["id"], make_technician_headers(tech_author["id"])), 200)
    capture_full_payment(ticket["id"], ready["final_charge_cents"])
    validate_success(api_client.pickup(ticket["id"], FRONT_DESK), 200)
    claim = validate_success(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(ticket["id"], line["id"], customer["id"]),
            make_customer_headers(customer["id"]),
        ),
        201,
    )
    approved = validate_success(
        api_client.approve_warranty_claim(
            claim["id"], rule_warranty_claim_payload(tech_ruler["id"]), SHOP_MANAGER
        ),
        200,
    )
    redo_tkt = approved["redo_ticket_id"]
    from test_helpers import validate_paginated
    lines, _ = validate_paginated(api_client.list_service_lines(FRONT_DESK, params={"ticket_id": redo_tkt}))
    return customer, tech_ruler, ticket, retail_part, redo_tkt, lines[0]


def test_retail_part_marked_up_at_1_35(api):
    """PRD §3.5: "The multiplier is the retail markup of 1.35 for a part on a normal (non-redo) ticket, whose marked-up cost flows into the customer-billed estimate and final charge."

    Design: Difficulty/dual_variant_calc/parts_markup_retail_vs_warranty_redo_diverge
    """
    customer, tech_ruler, ticket, retail_part, redo_tkt, redo_line = _setup_redo_with_retail_and_redo_part()
    retail_now = validate_success(api.get_parts_order(retail_part["id"], FRONT_DESK), 200)
    assert retail_now["marked_up_cost_cents"] == 2700


def test_redo_part_at_cost_diverges_from_retail(api):
    """PRD §3.6: "Because the redo ticket is a redo, any parts ordered against it are marked up at the at-cost factor of 1.0 per §3.5."
    PRD §3.5: "For a part on a warranty-redo ticket ... the multiplier is the at-cost factor of 1.0, so the same `supplier_cost_cents` and `quantity` produce a smaller `marked_up_cost_cents`, because a redo is no-charge and parts are passed at wholesale."

    Design: Difficulty/dual_variant_calc/parts_markup_retail_vs_warranty_redo_diverge
    """
    customer, tech_ruler, ticket, retail_part, redo_tkt, redo_line = _setup_redo_with_retail_and_redo_part()
    res = api.create_parts_order(
        create_parts_order_payload(redo_tkt, redo_line["id"], 1000, 0, quantity=2),
        make_technician_headers(tech_ruler["id"]),
    )
    redo_part = validate_success(res, 201)
    assert redo_part["marked_up_cost_cents"] == 2000
    retail_now = validate_success(api.get_parts_order(retail_part["id"], FRONT_DESK), 200)
    assert redo_part["marked_up_cost_cents"] != retail_now["marked_up_cost_cents"]


# ── Difficulty: warranty claim blocked when ticket not picked up (≥2) ────
def _setup_ready_not_picked_up():
    """WATCH ticket carried to READY_FOR_PICKUP (line completed, mark-ready) but
    NOT picked up. Returns context."""
    s = setup_ready_for_pickup(
        item_category="WATCH",
        service_overrides={"item_category": "WATCH", "base_price_cents": 1500,
                           "standard_turnaround_days": 1, "warranty_days": 90},
    )
    return s


def test_file_claim_against_ready_not_picked_up_rejected(api):
    """PRD §3.6: "A claim may be filed only while the original ticket is `PICKED_UP` and the current clock is at or before that ticket's `warranty_expires_at`; a claim filed after expiry or against a ticket not picked up is rejected with `ERR_WARRANTY_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_blocked_when_ticket_not_picked_up
    """
    s = _setup_ready_not_picked_up()
    res = api.create_warranty_claim(
        create_warranty_claim_payload(s["ticket"]["id"], s["line"]["id"], s["customer"]["id"]),
        make_customer_headers(s["customer"]["id"]),
    )
    validate_error(res, "ERR_WARRANTY_EXPIRED", 422)


def test_claim_filing_requires_pickup_state(api):
    """PRD §3.6: "After pickup, the owning customer may file a **warranty claim** against a service alleged to have failed".
    PRD §3.6: "a claim filed after expiry or against a ticket not picked up is rejected with `ERR_WARRANTY_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_blocked_when_ticket_not_picked_up
    """
    s = _setup_ready_not_picked_up()
    ticket = validate_success(api.get_repair_ticket(s["ticket"]["id"], FRONT_DESK), 200)
    assert ticket["repair_status"] == "READY_FOR_PICKUP"
    res = api.create_warranty_claim(
        create_warranty_claim_payload(s["ticket"]["id"], s["line"]["id"], s["customer"]["id"]),
        make_customer_headers(s["customer"]["id"]),
    )
    validate_error(res, "ERR_WARRANTY_EXPIRED", 422)
