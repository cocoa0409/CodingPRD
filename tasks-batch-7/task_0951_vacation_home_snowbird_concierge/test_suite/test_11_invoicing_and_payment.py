"""Invoice lines, the pinned per-line tax rounding, the nine-step total and payment."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    ApiErrorId,
    append_line,
    assert_invoice_money,
    create_invoice_line_payload,
    lines_of,
    open_draft_invoice,
    refresh_invoice,
    refresh_invoice_line,
    refresh_work_order,
    setup_completed_work_order,
    setup_draft_invoice,
    setup_issued_invoice,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


# --------------------------------------------------------------------------
# Lines
# --------------------------------------------------------------------------

def test_line_sequence_index_follows_the_append_order(api):
    """PRD 3.11: "Each new line is born with a `status` of `ACTIVE` and receives a
    one-based `sequence_index` assigned in ascending `created_at` order, and that index is
    what pins the per-line rounding sequence."
    PRD 3.11: "Further lines are appended one at a time with a `line_type`, a human
    `description`, a signed `amount_cents`, an optional `taxable` flag defaulting to true,
    and up to four optional links naming the thing the line bills: `visit_id`,
    `work_order_id`, `security_incident_id` and `mail_hold_id`."

    Design: Corner/entities/invoice_line_sequence_index_assigned_in_append_order
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    second = append_line(ctx["invoice_id"], line_type="TRAVEL_SURCHARGE", description="Trip A",
                         amount_cents=1500)
    third = append_line(ctx["invoice_id"], line_type="MAIL_DISPOSITION",
                        description="Forwarding", amount_cents=1800)

    assert second["sequence_index"] == 2
    assert third["sequence_index"] == 3
    assert third["status"] == "ACTIVE"
    assert third["taxable"] is True
    assert third["tax_cents"] == 126, "1800 * 0.07 rounds to 126"
    _, meta = validate_paginated(
        api.list_invoice_lines(headers=AUDITOR, params={"invoice_id": ctx["invoice_id"]})
    )
    assert meta["total_count"] == 3


def test_a_positive_guarantee_credit_violates_the_sign_rule(api):
    """PRD 3.11: "Sign is constrained by type: an `ENTITLEMENT_OFFSET` or a
    `GUARANTEE_CREDIT` line carries an `amount_cents` at or below zero and every other type
    carries one at or above zero, a violation being rejected with `ERR_LINE_SIGN_INVALID`."

    Design: Corner/errors/err_line_sign_invalid_for_positive_guarantee_credit_returns_400
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    response = api.create_invoice_invoice_line(
        ctx["invoice_id"],
        create_invoice_line_payload(line_type="GUARANTEE_CREDIT",
                                    description="Wrongly positive credit",
                                    amount_cents=15000, taxable=False),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_LINE_SIGN_INVALID.value)
    _, meta = validate_paginated(
        api.list_invoice_lines(headers=AUDITOR, params={"invoice_id": ctx["invoice_id"]})
    )
    assert meta["total_count"] == 1
    assert refresh_invoice(ctx["invoice_id"])["total_cents"] == 21385


def test_lines_cannot_be_appended_once_the_invoice_is_issued(api):
    """PRD 3.11: "Lines may be appended only while the invoice is `DRAFT`; an append against
    any other status is rejected with `ERR_INVOICE_NOT_DRAFT`."
    PRD 3.11: "Issuing recomputes every step of the total, freezes the line set, stamps
    `issued_at`, and moves the invoice to `ISSUED`."

    Design: Corner/errors/err_invoice_not_draft_when_appending_to_issued_invoice_returns_409
    """
    ctx = setup_issued_invoice(plan_overrides=STANDARD)
    response = api.create_invoice_invoice_line(
        ctx["invoice_id"],
        create_invoice_line_payload(line_type="TRAVEL_SURCHARGE", description="Late add",
                                    amount_cents=1500),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_INVOICE_NOT_DRAFT.value)
    assert refresh_invoice(ctx["invoice_id"])["total_cents"] == 21385
    _, meta = validate_paginated(
        api.list_invoice_lines(headers=AUDITOR, params={"invoice_id": ctx["invoice_id"]})
    )
    assert meta["total_count"] == 1


def test_voiding_an_already_void_line_is_refused(api):
    """PRD 3.11: "Voiding a line that is already `VOID` is rejected with
    `ERR_LINE_ALREADY_VOID`."
    PRD 3.11: "A line's `status` takes only `ACTIVE` or `VOID`, and `VOID` lines are
    excluded from every invoice aggregate."

    Design: Corner/errors/err_line_already_void_on_second_void_returns_409
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    line = append_line(ctx["invoice_id"], line_type="TRAVEL_SURCHARGE", description="Trip",
                       amount_cents=1500)
    validate_success(api.void_invoice_line(line["id"], {}, ACCOUNT_MANAGER))

    response = api.void_invoice_line(line["id"], {}, ACCOUNT_MANAGER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_LINE_ALREADY_VOID.value, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
         ApiErrorId.ERR_ALREADY_TERMINAL.value],
    )
    assert refresh_invoice_line(line["id"])["status"] == "VOID"
    assert refresh_invoice(ctx["invoice_id"])["total_cents"] == 21385


# --------------------------------------------------------------------------
# The pinned per-line tax rounding
# --------------------------------------------------------------------------

def test_tax_rounds_per_line_and_only_then_sums(api):
    """PRD 3.11: "**The rounding order is pinned: tax rounds per line and only then is
    summed.** Worked: two `ACTIVE` taxable lines of 1250 each round 87.5 to 88 twice, for
    176 — where taxing the 2500 sum in one step and rounding once would give 175."
    PRD 3.11: "A line's `tax_cents` is its `amount_cents` multiplied by a tax rate of 0.07
    and rounded to whole cents when `taxable` is true and its `status` is `ACTIVE`, and
    zero otherwise."

    Design: Difficulty/combinatorial_formula/invoice_tax_round_per_line_then_sum_mode_b
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    first = append_line(ctx["invoice_id"], line_type="TRAVEL_SURCHARGE",
                        description="Zone Z2 trip 1", amount_cents=1250, taxable=True)
    second = append_line(ctx["invoice_id"], line_type="TRAVEL_SURCHARGE",
                         description="Zone Z2 trip 2", amount_cents=1250, taxable=True)

    assert first["tax_cents"] == 88
    assert second["tax_cents"] == 88
    invoice = refresh_invoice(ctx["invoice_id"])
    assert_invoice_money(invoice, gross=22486, subtotal=22486, tax=1575, total=24061)


def test_a_negative_line_rounds_half_away_from_zero(api):
    """PRD 3.11: "A negative line rounds half away from zero, so −1250 yields −88."
    PRD 3.11: "`entitlement_offset_cents` is the sum of `amount_cents` over the `ACTIVE`
    `ENTITLEMENT_OFFSET` lines, and is therefore zero or negative."

    Design: Difficulty/combinatorial_formula/invoice_tax_round_per_line_then_sum_mode_b
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    offset = append_line(ctx["invoice_id"], line_type="ENTITLEMENT_OFFSET",
                         description="Included visit offset", amount_cents=-1250, taxable=True)
    assert offset["tax_cents"] == -88

    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["gross_service_cents"] == 19986
    assert invoice["entitlement_offset_cents"] == -1250
    assert_invoice_money(invoice, subtotal=18736, tax=1311, total=20047)


# --------------------------------------------------------------------------
# The compensating void
# --------------------------------------------------------------------------

def test_voiding_a_line_restores_every_invoice_money_field(api):
    """PRD 2.11: "Appending a line and then voiding it restores `subtotal_cents`,
    `tax_cents` and `total_cents` to their pre-add values exactly."
    PRD 3.11: "Voiding a single line is the compensating action behind the line-sum
    identity: the line's `status` becomes `VOID`, its `tax_cents` is set to zero, and the
    full total pipeline is re-run, restoring the pre-append `subtotal_cents`, `tax_cents`
    and `total_cents` exactly."

    Design: Difficulty/compensating_invariant/invoice_line_void_restores_every_invoice_money_field
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    before = refresh_invoice(ctx["invoice_id"])
    assert (before["gross_service_cents"], before["tax_cents"], before["total_cents"]) == (
        19986, 1399, 21385
    )
    line = append_line(ctx["invoice_id"], line_type="FALSE_ALARM_FEE",
                       description="Municipal false alarm 2", amount_cents=5000, taxable=True)
    added = refresh_invoice(ctx["invoice_id"])
    assert (added["gross_service_cents"], added["tax_cents"], added["total_cents"]) == (
        24986, 1749, 26735
    )

    validate_success(api.void_invoice_line(line["id"], {}, ACCOUNT_MANAGER))
    voided_line = refresh_invoice_line(line["id"])
    assert voided_line["status"] == "VOID"
    assert voided_line["tax_cents"] == 0
    after = refresh_invoice(ctx["invoice_id"])
    assert_invoice_money(after, gross=19986, tax=1399, total=21385)
    assert after["balance_due_cents"] == 21385


def test_voiding_one_of_two_lines_removes_only_that_line(api):
    """PRD 2.11: "An invoice's `subtotal_cents` equals the sum of `amount_cents` over its
    `ACTIVE` lines whose `line_type` is not `GUARANTEE_CREDIT`, plus the invoice's
    `storm_surcharge_cents`, plus the sum of `amount_cents` over its `ACTIVE`
    `GUARANTEE_CREDIT` lines."
    PRD 3.11: "`VOID` lines are excluded from every invoice aggregate."

    Design: Difficulty/compensating_invariant/invoice_line_void_restores_every_invoice_money_field
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    travel = append_line(ctx["invoice_id"], line_type="TRAVEL_SURCHARGE", description="Trip",
                         amount_cents=1500)
    append_line(ctx["invoice_id"], line_type="MAIL_DISPOSITION", description="Forwarding",
                amount_cents=3300)
    both = refresh_invoice(ctx["invoice_id"])
    assert_invoice_money(both, gross=24786, tax=1735, total=26521)

    validate_success(api.void_invoice_line(travel["id"], {}, ACCOUNT_MANAGER))
    after = refresh_invoice(ctx["invoice_id"])
    assert_invoice_money(after, gross=23286, tax=1630, total=24916)
    active = [ln for ln in lines_of(ctx["invoice_id"]) if ln["status"] == "ACTIVE"]
    assert len(active) == 2


def test_the_void_response_already_reflects_the_reconciled_invoice(api):
    """PRD 2.4: "**The response body carries post-mutation values.** Whatever a mutation
    writes — including the version bump, the refreshed `updated_at`, and every derived
    field re-computed as a consequence — is reflected in the resource object returned in
    `data`."
    PRD 3.11: "Voiding a single line is the compensating action behind the line-sum
    identity: the line's `status` becomes `VOID`, its `tax_cents` is set to zero, and the
    full total pipeline is re-run, restoring the pre-append `subtotal_cents`, `tax_cents`
    and `total_cents` exactly."

    Design: Corner/consistency_model/immediate_consistency_compensating_void_settles_inside_one_request
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    line = append_line(ctx["invoice_id"], line_type="MAIL_DISPOSITION",
                       description="Forwarding", amount_cents=3300)
    before = refresh_invoice(ctx["invoice_id"])
    assert_invoice_money(before, gross=23286, tax=1630, total=24916)

    voided = validate_success(api.void_invoice_line(line["id"], {}, ACCOUNT_MANAGER))
    assert voided["status"] == "VOID"
    assert voided["tax_cents"] == 0
    immediately_after = refresh_invoice(ctx["invoice_id"])
    assert immediately_after["gross_service_cents"] == 19986
    assert immediately_after["tax_cents"] == 1399
    assert immediately_after["total_cents"] == 21385


def test_voiding_a_draft_invoice_voids_every_active_line(api):
    """PRD 3.11: "voiding a draft invoice has no such precondition and likewise voids every
    `ACTIVE` line, with the totals recomputed to zero."

    Design: Corner/endpoints/void_invoice_cascades_to_every_active_line
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    second = append_line(ctx["invoice_id"], line_type="TRAVEL_SURCHARGE", description="Trip",
                         amount_cents=1500)
    third = append_line(ctx["invoice_id"], line_type="MAIL_DISPOSITION", description="Forward",
                        amount_cents=3300)

    voided = validate_success(api.void_invoice(ctx["invoice_id"], {}, ACCOUNT_MANAGER))
    assert voided["status"] == "VOID"
    assert refresh_invoice_line(second["id"])["status"] == "VOID"
    assert refresh_invoice_line(third["id"])["status"] == "VOID"
    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["gross_service_cents"] == 0
    assert invoice["subtotal_cents"] == 0
    assert invoice["tax_cents"] == 0
    assert invoice["total_cents"] == 0
    rows, meta = validate_paginated(
        api.list_invoice_lines(headers=AUDITOR, params={"invoice_id": ctx["invoice_id"]})
    )
    assert meta["total_count"] == 3
    assert all(row["status"] == "VOID" for row in rows)


# --------------------------------------------------------------------------
# Work-order invoicing
# --------------------------------------------------------------------------

def test_invoicing_a_work_order_appends_exactly_one_line_of_its_total(api):
    """PRD 3.5: "Invoicing a completed work order supplies an `invoice_id` whose invoice
    must be in `DRAFT`, creates one `ACTIVE` invoice line with `line_type` `WORK_ORDER` and
    an `amount_cents` equal to the work order's `total_cents`, and re-derives the invoice's
    `storm_surcharge_pct`, `gross_service_cents`, `storm_surcharge_cents`,
    `subtotal_cents`, `tax_cents` and `total_cents`."
    PRD 2.11: "Invoicing it creates exactly one `ACTIVE` line whose `line_type` is
    `WORK_ORDER` and whose `amount_cents` equals that total"

    Design: Corner/endpoints/work_order_invoice_action_creates_exactly_one_line_of_the_total
    """
    ctx = setup_completed_work_order(
        plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
        description="Leaky joint", item_codes=("PLUMBING_CHECK",), item_code="PLUMBING_CHECK",
        vendor_overrides={"legal_name": "Charge Plumbing", "trade": "PLUMBING", "rating": 4.3},
        key_asset_overrides={"key_type": "LOCKBOX", "label": "Bill lockbox",
                             "copies_total": 2, "current_code": "6666"},
        window_start_at="2026-06-02T14:00:00Z", window_end_at="2026-06-02T20:00:00Z",
        actual_labour_hours=2.0, actual_parts_cents=5000,
    )
    assert ctx["work_order"]["total_cents"] == 25960
    invoice = open_draft_invoice(ctx["cycle_id"])

    validate_success(api.invoice_work_order(ctx["work_order_id"], {"invoice_id": invoice["id"]},
                                            ACCOUNT_MANAGER))
    assert refresh_work_order(ctx["work_order_id"])["status"] == "INVOICED"
    rows, meta = validate_paginated(
        api.list_invoice_lines(headers=AUDITOR,
                               params={"work_order_id": ctx["work_order_id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["line_type"] == "WORK_ORDER"
    assert rows[0]["amount_cents"] == 25960

    final = refresh_invoice(invoice["id"])
    assert final["storm_surcharge_pct"] == 0.0
    assert final["storm_surcharge_cents"] == 0
    assert_invoice_money(final, gross=45946, tax=3216, total=49162)


def test_invoicing_against_an_unknown_invoice_id_is_a_404(api):
    """PRD 2.8: "A body field `invoice_id`, or the invoice targeted by a work-order
    invoicing call, resolves to an existing invoice. This applies to work-order invoicing
    and to invoice-line appending. Otherwise `ERR_INVOICE_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/err_invoice_not_found_when_invoicing_a_work_order_returns_404
    """
    ctx = setup_completed_work_order(
        plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
        description="Slow drain", item_codes=("PLUMBING_CHECK",), item_code="PLUMBING_CHECK",
        vendor_overrides={"legal_name": "Ghost Plumbing", "trade": "PLUMBING", "rating": 4.2},
        key_asset_overrides={"key_type": "LOCKBOX", "label": "Ghost lockbox",
                             "copies_total": 2, "current_code": "6100"},
        window_start_at="2026-06-02T14:00:00Z", window_end_at="2026-06-02T20:00:00Z",
        actual_labour_hours=2.0, actual_parts_cents=5000,
    )
    assert ctx["work_order"]["status"] == "COMPLETED"
    assert ctx["work_order"]["total_cents"] == 25960

    response = api.invoice_work_order(
        ctx["work_order_id"], {"invoice_id": "00000000-0000-4000-8000-0000000000c1"},
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_INVOICE_NOT_FOUND.value)
    assert refresh_work_order(ctx["work_order_id"])["status"] == "COMPLETED"
    _, meta = validate_paginated(
        api.list_invoice_lines(headers=AUDITOR,
                               params={"work_order_id": ctx["work_order_id"]})
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Issuing, paying, disputing and voiding
# --------------------------------------------------------------------------

def test_an_invoice_with_no_active_lines_cannot_be_issued(api):
    """PRD 3.11: "Issuing a draft invoice requires the parent billing cycle to be in
    `OPEN`, `CLOSING` or `CLOSED`, requires the subscription's status to be anything other
    than `CANCELLED`, and requires at least one `ACTIVE` line; an empty line set is
    rejected with `ERR_INVOICE_HAS_NO_LINES`."

    Design: Corner/errors/err_invoice_has_no_lines_after_voiding_the_only_line_returns_409
    """
    ctx = setup_draft_invoice(plan_overrides=STANDARD)
    seeded = lines_of(ctx["invoice_id"])[0]
    validate_success(api.void_invoice_line(seeded["id"], {}, ACCOUNT_MANAGER))

    response = api.issue_invoice(ctx["invoice_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVOICE_HAS_NO_LINES.value)
    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["status"] == "DRAFT"
    assert invoice["total_cents"] == 0
    assert invoice["issued_at"] is None


def test_a_zero_payment_is_refused(api):
    """PRD 3.11: "A payment supplies an `amount_cents` that must be strictly greater than
    zero against an invoice that is not already `PAID`, a violation being rejected with
    `ERR_PAYMENT_AMOUNT_INVALID`."

    Design: Corner/errors/err_payment_amount_invalid_for_zero_payment_returns_409
    """
    ctx = setup_issued_invoice(plan_overrides=STANDARD)
    response = api.pay_invoice(ctx["invoice_id"], {"amount_cents": 0}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value)
    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["status"] == "ISSUED"
    assert invoice["amount_paid_cents"] == 0
    assert invoice["balance_due_cents"] == 21385


def test_a_paid_invoice_cannot_be_voided(api):
    """PRD 3.11: "Voiding an issued invoice requires `amount_paid_cents` to be exactly zero
    — a part-paid invoice is rejected with `ERR_INVOICE_ALREADY_PAID` — and moves every
    `ACTIVE` line to `VOID`"
    PRD 3.11: "A payment at or above `balance_due_cents` moves an `ISSUED` invoice straight
    to `PAID`, setting `amount_paid_cents` to `total_cents`, `balance_due_cents` to zero and
    `paid_at` to the logical clock"

    Design: Corner/errors/err_invoice_already_paid_on_void_returns_409
    """
    ctx = setup_issued_invoice(plan_overrides=STANDARD)
    paid = validate_success(
        api.pay_invoice(ctx["invoice_id"], {"amount_cents": 21385}, ctx["owner_headers"])
    )
    assert paid["status"] == "PAID"
    assert paid["amount_paid_cents"] == 21385
    assert paid["balance_due_cents"] == 0
    assert paid["paid_at"] is not None

    response = api.void_invoice(ctx["invoice_id"], {}, ACCOUNT_MANAGER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_INVOICE_ALREADY_PAID.value,
         ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
         ApiErrorId.ERR_ALREADY_TERMINAL.value],
    )
    assert refresh_invoice(ctx["invoice_id"])["status"] == "PAID"


def test_the_dispute_loop_counts_once_and_recomputes_on_resolution(api):
    """PRD 3.11: "Only the owner named by the invoice's `owner_id` may dispute an issued
    invoice, optionally attaching a `resolution_note`; the dispute advances `dispute_count`
    by one and moves the invoice from `ISSUED` to `DISPUTED`."
    PRD 3.11: "Resolving a dispute returns the invoice from `DISPUTED` to `ISSUED` with no
    precondition and recomputes every step of the total over the current `ACTIVE` line
    set."

    Design: Corner/state_machines/invoice_dispute_loop_returns_to_issued_and_counts
    """
    ctx = setup_issued_invoice(plan_overrides=STANDARD)
    disputed = validate_success(api.dispute_invoice(
        ctx["invoice_id"], {"resolution_note": "Fee looks wrong"}, ctx["owner_headers"]
    ))
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 1

    resolved = validate_success(
        api.resolve_dispute_invoice(ctx["invoice_id"], {}, ACCOUNT_MANAGER)
    )
    assert resolved["status"] == "ISSUED"
    assert resolved["dispute_count"] == 1
    assert resolved["total_cents"] == 21385
    assert resolved["balance_due_cents"] == 21385
