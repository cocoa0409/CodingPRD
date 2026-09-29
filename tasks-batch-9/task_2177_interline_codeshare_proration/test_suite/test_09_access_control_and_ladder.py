"""Authentication, role gating, carrier ownership and the absolute rejection ladder."""

from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    OPERATOR,
    UNKNOWN_UUIDS,
    create_carrier_payload,
    create_ticket_payload,
    make_accountant_headers,
    make_auditor_headers,
    make_billing_agent_headers,
    new_carrier,
    read_carrier,
    read_invoice,
    read_ticket,
    set_clock,
    setup_draft_invoice,
    setup_two_carriers,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Authentication and role gating
# --------------------------------------------------------------------------- #
def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the service — including reads — must carry two headers.
    `X-User-ID` identifies the acting principal and `X-User-Role` names the desk it is acting
    from. If either header is missing or present but empty, the request is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    payload = create_carrier_payload("AA")

    resp = api.create_carrier(payload, ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.json()["response_type"] == "error"

    _rows, meta = validate_paginated(api.list_carriers(OPERATOR))
    assert meta["total_count"] == 0, "no carrier row is created by the refused request"

    created = validate_success(api.create_carrier(payload, OPERATOR), 201)
    assert created["iata_code"] == "AA"


def test_revenue_accountant_cannot_submit_an_invoice(api):
    """PRD §2.1: "If `X-User-Role` is not one of the four role names declared below, or is a
    declared role that the requested operation does not list among its authorized roles, the
    request is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.6: "Submission is the `BillingAgent`'s act, and only for its own
    `billing_carrier_id`."

    Design: Corner/rbac/revenue_accountant_cannot_submit_an_invoice
    """
    ctx = setup_draft_invoice(ticket_number="0067000000001")

    resp = api.submit_invoice(
        ctx["invoice"]["id"], make_accountant_headers(ctx["bb"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "DRAFT"
    assert invoice["submitted_at"] is None
    assert read_carrier(ctx["bb"]["id"])["pending_receivable_minor"] == 0


def test_interline_auditor_cannot_decide_a_recovery_claim(api):
    """PRD §3.9: "Only the audited carrier's `BillingAgent`, matched on `audited_carrier_id`,
    may decide a `CLAIM_RAISED` sample, by supplying a `decision` of `ACCEPT` or `DENY`."
    PRD §2.7: "This ladder is global and absolute: a later check never masks an earlier one,
    and a request that would fail step 30 but also fails step 4 is answered as step 4."

    Design: Corner/rbac/interline_auditor_cannot_decide_a_recovery_claim
    """
    unknown_sample = UNKNOWN_UUIDS["spare"]

    resp = api.claim_decision(
        unknown_sample, "ACCEPT", make_auditor_headers(unknown_sample)
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_SAMPLE_NOT_FOUND.value, (
        "the role check at step 2 fires ahead of the path-existence check at step 4"
    )


def test_accountant_cannot_issue_a_ticket_for_another_carrier(api):
    """PRD §2.1: "For `RevenueAccountant`, `BillingAgent` and `InterlineAuditor`, `X-User-ID`
    is the `id` of the acting `Carrier`; ownership checks on any resource compare the relevant
    carrier-valued field of that resource to `X-User-ID`. Concretely: a `RevenueAccountant`
    must match the `validating_carrier_id` of the ticket it is acting on, and — when drafting
    an agreement or an invoice — the `issuing_carrier_id` or `billing_carrier_id` named in the
    request body."
    PRD §2.1: "A mismatch is refused with `ERR_CARRIER_OWNERSHIP_REQUIRED` (HTTP 403)."

    Design: Corner/rbac/accountant_cannot_issue_a_ticket_for_another_carrier
    """
    aa, bb = setup_two_carriers()
    payload = create_ticket_payload(
        aa["id"], "0068000000001", issue_date="2026-08-01T00:00:00Z"
    )

    resp = api.create_ticket(payload, make_accountant_headers(bb["id"]))
    validate_error(resp, ApiErrorId.ERR_CARRIER_OWNERSHIP_REQUIRED.value)

    _rows, meta = validate_paginated(
        api.list_tickets(OPERATOR, params={"validating_carrier_id": aa["id"]})
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_ticket(payload, make_accountant_headers(aa["id"])), 201
    )
    assert accepted["validating_carrier_id"] == aa["id"]


def test_billed_carrier_cannot_submit_the_billing_carriers_invoice(api):
    """PRD §2.1: "A `BillingAgent` must match `billing_carrier_id` when submitting or
    recalling an invoice, countering a memo or accepting a memo; must match
    `billed_carrier_id` when raising, re-rejecting or withdrawing a memo; and must match
    `audited_carrier_id` when deciding an audit claim."
    PRD §2.1: "A mismatch is refused with `ERR_CARRIER_OWNERSHIP_REQUIRED` (HTTP 403)."

    Design: Corner/rbac/billed_carrier_cannot_submit_the_billing_carriers_invoice
    """
    ctx = setup_draft_invoice(ticket_number="0069000000001")

    resp = api.submit_invoice(
        ctx["invoice"]["id"], make_billing_agent_headers(ctx["aa"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CARRIER_OWNERSHIP_REQUIRED.value)
    assert read_invoice(ctx["invoice"]["id"])["status"] == "DRAFT"

    accepted = validate_success(
        api.submit_invoice(ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        200,
    )
    assert accepted["status"] == "SUBMITTED"


# --------------------------------------------------------------------------- #
# Domain-specific 404s
# --------------------------------------------------------------------------- #
def test_unknown_path_identifiers_report_their_own_not_found_code(api):
    """PRD §2.7: "**Path identifiers.** Every `id` embedded in the request path resolves to a
    stored row, checked strictly left to right, so an outer segment's failure is reported
    before an inner segment is even looked at. The code names the missing type:
    `ERR_CARRIER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_COUPON_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_MEMO_NOT_FOUND` or `ERR_SAMPLE_NOT_FOUND`, all HTTP 404. Applies to every operation
    carrying a path identifier."

    Design: Corner/errors/unknown_path_ids_return_their_own_not_found_errors
    """
    validate_error(
        api.get_agreement(UNKNOWN_UUIDS["agreement"], OPERATOR),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
    )
    validate_error(
        api.get_period(UNKNOWN_UUIDS["period"], OPERATOR),
        ApiErrorId.ERR_PERIOD_NOT_FOUND.value,
    )
    validate_error(
        api.get_invoice(UNKNOWN_UUIDS["invoice"], OPERATOR),
        ApiErrorId.ERR_INVOICE_NOT_FOUND.value,
    )
    validate_error(
        api.get_coupon(UNKNOWN_UUIDS["coupon"], OPERATOR),
        ApiErrorId.ERR_COUPON_NOT_FOUND.value,
    )


def test_unknown_memo_sample_and_body_carrier_references_report_not_found(api):
    """PRD §2.7: "**Body references.** Every foreign-key identifier supplied in the request
    body resolves to a stored row, checked in the order the fields are declared in that
    operation's input list; for the `coupon_ids` and `sample_coupon_ids` arrays, in the order
    the elements were supplied. The code again names the missing type —
    `ERR_CARRIER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_COUPON_NOT_FOUND`,
    `ERR_PERIOD_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, HTTP 404. Applies to agreement
    drafting, ticket issue, coupon append, invoice drafting, memo raise, audit-sample draw and
    audit finding recording."
    PRD §2.7: "Existence beats permission-of-account: a request naming a carrier that does not
    exist is a 404 before it can be a 403 for acting on someone else's carrier, but ownership
    (step 6) beats every state and business check that follows it."

    Design: Corner/errors/unknown_memo_and_sample_paths_return_not_found
    """
    validate_error(
        api.get_memo(UNKNOWN_UUIDS["memo"], OPERATOR),
        ApiErrorId.ERR_MEMO_NOT_FOUND.value,
    )
    validate_error(
        api.get_audit_sample(UNKNOWN_UUIDS["sample"], OPERATOR),
        ApiErrorId.ERR_SAMPLE_NOT_FOUND.value,
    )

    ghost = UNKNOWN_UUIDS["carrier"]
    resp = api.create_ticket(
        create_ticket_payload(ghost, "0060000000001", issue_date="2026-08-01T00:00:00Z"),
        make_accountant_headers(ghost),
    )
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND.value)


# --------------------------------------------------------------------------- #
# Ladder precedence: state beats fiscal
# --------------------------------------------------------------------------- #
def _tiny_limit_draft_into_a_closed_period(api):
    ctx = setup_draft_invoice(billed_credit_limit=1000, ticket_number="0020000000001")
    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.close_period(ctx["period"]["id"], OPERATOR), 200)
    return ctx


def test_closed_period_state_beats_the_credit_limit_breach(api):
    """PRD §2.7: "**Period open.** The referenced settlement period is `OPEN` — otherwise
    `ERR_PERIOD_NOT_OPEN` (409). Applies to invoice drafting, invoice submission, invoice
    recall and settlement-period close."
    PRD §2.7: "**Credit limit.** The billed carrier's `pending_payable_minor` plus
    `settled_payable_minor` plus the invoice's `provisional_settlement_minor`, less that
    carrier's `pending_receivable_minor` and `settled_receivable_minor`, is no larger than its
    `credit_limit_minor` — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (409). Applies to invoice
    submission."
    PRD §2.7: "This ladder is global and absolute: a later check never masks an earlier one,
    and a request that would fail step 30 but also fails step 4 is answered as step 4."

    Design: Difficulty/priority_pair_validation_conflict/closed_period_state_beats_credit_limit_breach_on_submit
    """
    ctx = _tiny_limit_draft_into_a_closed_period(api)
    assert read_carrier(ctx["aa"]["id"])["credit_limit_minor"] == 1000

    resp = api.submit_invoice(
        ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, (
        "the period-state check at step 7 outranks the credit check at step 43"
    )


def test_submit_refused_by_the_earlier_ladder_step_lands_no_side_effect(api):
    """PRD §2.7: "When a request violates more than one rule, the response is decided by the
    **first** rule that fails in the ordering below, and no side effect of the request has
    been applied when it does."
    PRD §3.6: "A successful submission sets `status` to `SUBMITTED` and `submitted_at` to the
    current logical clock, adds `provisional_settlement_minor` to the billing carrier's
    `pending_receivable_minor` and to the billed carrier's `pending_payable_minor`, recomputes
    `net_position_minor` on both, and moves every ticket owning one of the attached coupons
    from `billing_status` `UNBILLED` to `BILLED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_period_state_beats_credit_limit_breach_on_submit
    """
    ctx = _tiny_limit_draft_into_a_closed_period(api)

    validate_error(
        api.submit_invoice(ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        ApiErrorId.ERR_PERIOD_NOT_OPEN.value,
    )

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "DRAFT"
    assert invoice["gross_billed_minor"] == 0
    assert read_carrier(ctx["aa"]["id"])["pending_payable_minor"] == 0
    assert read_carrier(ctx["bb"]["id"])["pending_receivable_minor"] == 0
    assert read_ticket(ctx["ticket"]["id"])["billing_status"] == "UNBILLED"


# --------------------------------------------------------------------------- #
# Ladder precedence: compliance beats uniqueness
# --------------------------------------------------------------------------- #
def _suspended_issuer_reusing_a_ticket_number(api):
    set_clock("2026-08-10T00:00:00Z")
    aa = new_carrier("AA")
    first = validate_success(
        api.create_ticket(
            create_ticket_payload(aa["id"], "0022000000001"),
            make_accountant_headers(aa["id"]),
        ),
        201,
    )
    validate_success(api.suspend_carrier(aa["id"], OPERATOR), 200)
    return aa, first


def test_suspended_acting_carrier_beats_the_duplicate_ticket_number(api):
    """PRD §2.7: "**Acting carrier in good standing.** The carrier acting for its own account
    is `ACTIVE` — the `validating_carrier_id` on ticket issue and coupon append, the
    `issuing_carrier_id` on agreement drafting, the `billing_carrier_id` on invoice drafting
    and invoice submission, and the `billed_carrier_id` on memo raise and memo re-reject.
    Otherwise `ERR_CARRIER_SUSPENDED` (409)."
    PRD §2.7: "**Ticket number uniqueness.** `ticket_number` is not already used by another
    ticket — otherwise `ERR_DUPLICATE_TICKET_NUMBER` (409). Applies to ticket issue."

    Design: Difficulty/priority_pair_validation_conflict/suspended_carrier_safety_beats_duplicate_ticket_number
    """
    aa, _first = _suspended_issuer_reusing_a_ticket_number(api)

    resp = api.create_ticket(
        create_ticket_payload(aa["id"], "0022000000001", total_fare_minor=200000),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CARRIER_SUSPENDED.value)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_DUPLICATE_TICKET_NUMBER.value, (
        "the compliance check at step 18 outranks the uniqueness check at step 29"
    )


def test_refused_reissue_leaves_the_original_ticket_alone(api):
    """PRD §3.4: "Ticket numbers are globally unique; a repeat is refused with
    `ERR_DUPLICATE_TICKET_NUMBER`."
    PRD §3.1: "A suspended carrier may not issue tickets, may not have coupons appended to its
    tickets, may not draft an agreement as the issuing side, may not draft or submit an
    invoice as the billing side, and may not raise or re-reject a rejection memo as the billed
    side; each of those is refused with `ERR_CARRIER_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_carrier_safety_beats_duplicate_ticket_number
    """
    aa, first = _suspended_issuer_reusing_a_ticket_number(api)

    validate_error(
        api.create_ticket(
            create_ticket_payload(aa["id"], "0022000000001", total_fare_minor=200000),
            make_accountant_headers(aa["id"]),
        ),
        ApiErrorId.ERR_CARRIER_SUSPENDED.value,
    )

    rows, meta = validate_paginated(
        api.list_tickets(OPERATOR, params={"validating_carrier_id": aa["id"]})
    )
    assert meta["total_count"] == 1, "exactly one ticket carries that number"
    assert rows[0]["id"] == first["id"]
    assert read_ticket(first["id"])["total_fare_minor"] == 100000
