"""Workmanship claims, segregation of duties and the six-link approval cascade."""
from test_helpers import (
    ApiErrorId, CLERK,
    api_client, approve_claim, build_config, create_account, create_claim, create_invoice,
    create_plan_tier, create_subscription, deny_claim, find_draft_invoice, issue_invoice,
    list_items_of_request, list_lines_by_claim, make_account_owner_headers,
    make_technician_headers, read_account, read_claim, read_invoice, read_item, read_request,
    resubmit_claim, route_to_bench, set_clock, setup_claim_ready, setup_delivered_van_visit,
    stage_request, validate_error, validate_success, work_and_deliver,
    assert_invoice_line, assert_same_instant, assert_warranty_claim,
)


def test_warranty_decision_by_the_assessing_technician_is_refused():
    """PRD 3.9: "The technician deciding a claim may not be the technician who assessed the
    item the claim is raised against: the acting `X-User-ID` must differ from the item's
    `assessed_by_technician_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`
    at HTTP 403."
    PRD 2.6 rung 23: "The acting technician's `X-User-ID` differs from the
    `assessed_by_technician_id` recorded on the claimed item. Otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403). Applies to warranty approval and warranty denial;
    pre-empts rungs 24–57."

    Design: Corner/state_machines/warranty_decision_by_the_assessing_technician_is_refused
    """
    world, _request, item, claim, _invoice = setup_claim_ready(invoice_and_issue=False)

    response = api_client.approve_warranty_claim(
        claim["id"], make_technician_headers(world["tech"]["id"]))
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    reread = read_claim(claim["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["rework_service_request_id"] is None
    assert reread["decided_by_technician_id"] is None
    assert read_item(item["id"])["service_status"] == "DELIVERED"


def test_claim_raised_after_the_warranty_window_is_refused():
    """PRD 3.9: "And the logical clock must not be later than the item's `delivered_at` plus
    30 days, with exactly the boundary passing; beyond that it is
    `ERR_WARRANTY_WINDOW_EXPIRED`."
    PRD 2.6 rung 38: "The logical clock is not later than the item's `delivered_at` plus 30
    days; exactly on the boundary passes. Otherwise `ERR_WARRANTY_WINDOW_EXPIRED` (409).
    Applies to warranty-claim creation and to resubmission; pre-empts rungs 39–57."

    Design: Corner/validations/warranty_claim_after_the_window_is_refused
    """
    world, _request, items = setup_delivered_van_visit()
    set_clock("2026-06-01T00:00:00Z")

    response = api_client.create_warranty_claim(
        {"request_item_id": items[0]["id"], "reason": "Too late"},
        make_account_owner_headers(world["account"]["id"]))
    validate_error(response, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED.value, 409)

    reread = read_item(items[0]["id"])
    assert_same_instant(reread["delivered_at"], "2026-05-01T00:00:00Z", "delivered_at")
    assert reread["service_status"] == "DELIVERED"


def test_claim_on_another_accounts_item_is_a_referential_mismatch():
    """PRD 3.9: "The claimed item's service request must belong to the acting `AccountOwner`,
    or the claim is `ERR_CLAIM_ITEM_ACCOUNT_MISMATCH` — this is the rung that the ownership
    carve-out in §2.1 defers to, and it deliberately reports a referential mismatch rather than
    a permission failure, because the caller is a legitimate account owner who simply named
    somebody else's blade."
    PRD 2.6 rung 28: "The claimed item's service request `account_id` equals the acting
    `AccountOwner`'s id. Otherwise `ERR_CLAIM_ITEM_ACCOUNT_MISMATCH` (422)."

    Design: Corner/validations/claim_on_another_accounts_item_is_a_referential_mismatch
    """
    _world, _request, items = setup_delivered_van_visit()
    other_account = create_account(name="Copper Pan", contact_email="ops@copperpan.test")

    response = api_client.create_warranty_claim(
        {"request_item_id": items[0]["id"], "reason": "Not my knife"},
        make_account_owner_headers(other_account["id"]))
    error = validate_error(response, ApiErrorId.ERR_CLAIM_ITEM_ACCOUNT_MISMATCH.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_NOT_ACCOUNT_OWNER.value
    assert read_item(items[0]["id"])["service_status"] == "DELIVERED"


def _claim_denied_twice():
    """A claim denied, resubmitted, denied, resubmitted and denied again."""
    world, _request, item, claim, _invoice = setup_claim_ready(invoice_and_issue=False)
    decider = world["tech_b"]["id"]
    owner = world["account"]["id"]
    deny_claim(claim["id"], decider, abuse_finding=True)
    resubmit_claim(claim["id"], owner)
    deny_claim(claim["id"], decider, abuse_finding=True)
    second = resubmit_claim(claim["id"], owner)
    assert second["resubmit_count"] == 2
    deny_claim(claim["id"], decider, abuse_finding=True)
    return world, item, claim


def test_third_resubmission_is_refused_at_the_resubmit_cap():
    """PRD 3.9: "Resubmission requires `resubmit_count` to be strictly below 2 — the third
    resubmission is refused with `ERR_RESUBMIT_CAP_REACHED` — and it re-checks the 30-day
    warranty window against the item's `delivered_at`, so a claim that was denied late in the
    window can time out before the customer gets a second answer."
    PRD 2.6 rung 41: "The claim's `resubmit_count` is strictly below 2. Otherwise
    `ERR_RESUBMIT_CAP_REACHED` (409). Applies to warranty resubmission; pre-empts rungs
    42–57."

    Design: Difficulty/non_linear_state_machine/warranty_claim_denied_resubmit_loop_capped_at_two
    """
    world, _item, claim = _claim_denied_twice()

    response = api_client.resubmit_warranty_claim(
        claim["id"], make_account_owner_headers(world["account"]["id"]))
    validate_error(response, ApiErrorId.ERR_RESUBMIT_CAP_REACHED.value, 409)


def test_capped_claim_stays_denied_with_its_abuse_finding_intact():
    """PRD 3.9: "**Denial** is the short path. It requires the claim to be `SUBMITTED`,
    records `decided_by_technician_id` and the `abuse_finding` supplied in the body, and moves
    the claim `SUBMITTED → DENIED`."
    PRD 2.9: "A claim can go `SUBMITTED → DENIED → SUBMITTED`, bounded to two resubmissions."

    Design: Difficulty/non_linear_state_machine/warranty_claim_denied_resubmit_loop_capped_at_two
    """
    world, item, claim = _claim_denied_twice()
    api_client.resubmit_warranty_claim(
        claim["id"], make_account_owner_headers(world["account"]["id"]))

    reread = read_claim(claim["id"])
    assert_warranty_claim(reread)
    assert reread["status"] == "DENIED"
    assert reread["resubmit_count"] == 2
    assert reread["abuse_finding"] is True
    assert read_item(item["id"])["service_status"] == "DELIVERED"


def test_approval_queues_the_blade_for_rework_and_opens_a_pre_assessed_order():
    """PRD 3.9: "*Link two.* Because the claim was granted, the blade must come back. The
    claimed item moves `service_status` `DELIVERED → REWORK_QUEUED` and, on the very same row,
    `custody_location` `DELIVERED → CUSTOMER`."
    PRD 3.9: "A new service request is created with `channel` `REWORK`, `status` `SUBMITTED`,
    `priority` `STANDARD`, `subscription_id` null and `origin_warranty_claim_id` naming the
    claim; the claim's `rework_service_request_id` is set to point back at it."
    PRD 3.9: "One item is created on that request, whose `rework_of_request_item_id` points at
    the claimed item, whose `declared_damage_tier` is copied from the claimed item's
    `assessed_damage_tier`, whose `assessed_damage_tier` is set directly to `ROUTINE_HONE`,
    whose `assessed_by_technician_id` is the approving technician, and whose
    `service_minutes_assessed` are therefore the routine-hone minutes of its class."

    Design: Difficulty/transitive_cascade/warranty_approval_rework_and_credit_depth_six_cascade
    """
    world, _request, item, claim, _invoice = setup_claim_ready(declared_tier="CHIP_REPAIR")

    approved = approve_claim(claim["id"], world["tech_b"]["id"])
    assert approved["status"] == "APPROVED"
    assert approved["credit_basis_cents"] == 1440
    assert approved["decided_by_technician_id"] == world["tech_b"]["id"]

    claimed = read_item(item["id"])
    assert claimed["service_status"] == "REWORK_QUEUED"
    assert claimed["custody_location"] == "CUSTOMER"

    rework = read_request(approved["rework_service_request_id"])
    assert rework["channel"] == "REWORK"
    assert rework["status"] == "SUBMITTED"
    assert rework["origin_warranty_claim_id"] == claim["id"]

    rework_item = list_items_of_request(rework["id"])[0]
    assert rework_item["rework_of_request_item_id"] == item["id"]
    assert rework_item["declared_damage_tier"] == "CHIP_REPAIR"
    assert rework_item["assessed_damage_tier"] == "ROUTINE_HONE"
    assert rework_item["service_status"] == "ASSESSED"
    assert rework_item["service_minutes_declared"] == 12
    assert rework_item["service_minutes_assessed"] == 6


def test_approval_emits_the_workmanship_credit_and_moves_the_billing_axis():
    """PRD 3.9: "*Link four.* Because a rework order has been opened, the workmanship credit
    is owed. A warranty-credit line is appended to the account's draft invoice, creating that
    draft invoice when none exists, carrying an `amount_cents` equal to the negative of
    `credit_basis_cents` and a `source_warranty_claim_id` naming the claim. The line is
    taxable."
    PRD 3.9: "*Link six.* Because the credit has landed, the *original* item's service request
    moves on its billing axis to `CREDITED` — `INVOICED → CREDITED` when it had only been
    invoiced, and `SETTLED → CREDITED` when it had already been paid."
    PRD 3.10: "A negative taxable subtotal produces no tax at all rather than a negative tax,
    because of the floor at zero — while `taxable_subtotal_cents` itself is reported as the
    negative figure it is."

    Design: Difficulty/transitive_cascade/warranty_approval_rework_and_credit_depth_six_cascade
    """
    world, request, _item, claim, invoice = setup_claim_ready(declared_tier="CHIP_REPAIR")

    approve_claim(claim["id"], world["tech_b"]["id"])

    draft = find_draft_invoice(world["account"]["id"])
    assert draft["status"] == "DRAFT"
    assert draft["taxable_subtotal_cents"] == -1440
    assert draft["tax_cents"] == 0
    assert draft["total_cents"] == -1440

    assert read_request(request["id"])["billing_status"] == "CREDITED"
    assert read_invoice(invoice["id"])["total_cents"] == 1544
    assert read_account(world["account"]["id"])["outstanding_balance_cents"] == 1544


def _allowance_absorbed_claim():
    """A single subscription item whose invoice line was written at zero, with a claim open."""
    world = build_config(second_technician=True)
    tier = create_plan_tier(included_items_per_cycle=1)
    subscription = create_subscription(world["account"]["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-06-01")
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")],
                                   subscription_id=subscription["id"])
    route_to_bench(world, request["id"])
    work_and_deliver(world, request["id"], [items[0]["id"]], ["ROUTINE_HONE"])
    invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
    issue_invoice(invoice["id"])
    claim = create_claim(items[0]["id"], world["account"]["id"],
                         reason="Edge folded on first use")
    return world, items[0], invoice, claim


def test_credit_basis_is_zero_when_the_allowance_absorbed_the_item():
    """PRD 3.9: "It is the `amount_cents` of the service-kind invoice line whose
    `request_item_id` names the claimed item, looked up across all of that account's non-voided
    invoices; when no such line exists — for instance because the subscription allowance
    absorbed the item entirely and its line was written at zero, or because the item was never
    invoiced — the basis is 0."
    PRD 3.10: "Invoice creation emits exactly one service line per covered item whose
    `service_status` is neither `RETURNED_UNSERVICED` nor `ABANDONED`, with `amount_cents`
    equal to that item's `charged_service_cents` — which is 0 when the allowance absorbed the
    item, and the line is still written — and exactly one part line per such item whose
    `part_fee_cents` is greater than 0."

    Design: Difficulty/boundary_precision_check/zero_credit_basis_when_allowance_absorbed_the_item
    """
    world, item, invoice, claim = _allowance_absorbed_claim()
    reread_item = read_item(item["id"])
    assert reread_item["allowance_applied"] is True
    assert reread_item["charged_service_cents"] == 0

    reread_invoice = read_invoice(invoice["id"])
    assert reread_invoice["taxable_subtotal_cents"] == 0
    assert reread_invoice["tax_cents"] == 0
    assert reread_invoice["total_cents"] == 0

    approved = approve_claim(claim["id"], world["tech_b"]["id"])
    assert approved["status"] == "APPROVED"
    assert approved["credit_basis_cents"] == 0


def test_zero_value_warranty_credit_line_is_still_written():
    """PRD 3.9: "And within an approval, link four still fires when `credit_basis_cents` is 0
    — the line is written at zero rather than skipped — because the line is the audit record
    that the claim was honoured; the invoice-recompute of link five then simply produces no
    change in the money."
    PRD 3.10: "Taxability is fixed per kind and is not negotiable per line: `SERVICE`,
    `SUBSCRIPTION_FEE`, `PRORATION_CREDIT` and `WARRANTY_CREDIT` lines are taxable; `PART` and
    `LATE_FEE` lines are not."

    Design: Difficulty/boundary_precision_check/zero_credit_basis_when_allowance_absorbed_the_item
    """
    world, _item, _invoice, claim = _allowance_absorbed_claim()

    approve_claim(claim["id"], world["tech_b"]["id"])

    lines = list_lines_by_claim(claim["id"])
    assert len(lines) == 1, f"expected exactly one warranty-credit line, got {len(lines)}"
    line = lines[0]
    assert_invoice_line(line)
    assert line["source"] == "WARRANTY_CREDIT"
    assert line["amount_cents"] == 0
    assert line["taxable"] is True
    assert read_account(world["account"]["id"])["outstanding_balance_cents"] == 0
    assert validate_success(api_client.get_invoice_line(line["id"], CLERK))["id"] == line["id"]
