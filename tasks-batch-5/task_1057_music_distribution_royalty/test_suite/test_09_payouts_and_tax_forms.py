"""Settling up: payout approval, payment, reversal, the withholding ladder and 1099 forms."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_payout, assert_tax_form, assert_settled_total,
    setup_world, lock_sheets_for_world, setup_closed_statement, setup_single_payee_payout,
    royalty_line_payload, read_statement, read_collaborator, read_payout, read_tax_form,
    list_payouts_for, approve_payout, pay_payout, draft_tax_form, set_clock,
    PERIOD_MAY, make_finance_headers, make_artist_headers,
    FIN_RECONCILER, FIN_CLOSER, FIN_APPROVER, FIN_PAYER,
)


def _payout_by_payee(payouts, collaborator_id):
    matches = [p for p in payouts if p["collaborator_id"] == collaborator_id]
    assert len(matches) == 1, f"expected exactly 1 payout for {collaborator_id}, got {len(matches)}"
    return matches[0]


def test_verified_treaty_payee_is_withheld_less_than_a_submitted_one(api):
    """PRD §3.8: "Its `withholding_bps` is pinned at this moment by re-evaluating the four-case
    withholding ladder for that collaborator — backup at 2400 basis points when the paperwork is
    `MISSING` or `EXPIRED`, zero for a `US` payee, 1000 basis points for a `VERIFIED` payee
    resident in `GB`, `DE`, `NL`, `AU` or `JP`, and 3000 basis points otherwise — and stored on
    the payout, so that later paperwork changes cannot retroactively alter a settled payout."
    PRD §3.4: "The consequence worth stressing is that a payee in a treaty country whose paperwork
    has only reached `SUBMITTED` is withheld at 3000 basis points, not 1000: identical country and
    identical gross yield a materially different net purely because verification has not landed."
    PRD §3.8: "Its `withholding_cents` is the payout's `gross_cents` multiplied by that pinned
    rate, divided by 10000 and rounded half up to whole cents, and its `net_cents` is
    `gross_cents` less `withholding_cents`."

    Design: Difficulty/dual_variant_calc/collaborator_treaty_vs_statutory_withholding_divergence
    """
    world = setup_world(
        plan_overrides={"code": "LITE", "name": "Lite", "commission_bps": 1000,
                        "allows_content_id": False, "included_release_slots": 3},
        artist_overrides={"email": "vega@example.com"},
        payees=[{"name": "Mia", "email": "mia@example.com", "country_code": "GB",
                 "tax_form_status": "VERIFIED"},
                {"name": "Neo", "email": "neo@example.com", "country_code": "GB",
                 "tax_form_status": "SUBMITTED"}],
    )
    c_treaty, c_statutory = world["payees"]
    lock_sheets_for_world(world, [[(c_treaty["id"], 5000), (c_statutory["id"], 5000)]])

    setup_closed_statement(world, [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 100000,
                             "2026-05-12T00:00:00Z", units=500000),
    ])

    statement = read_statement(world["statement_id"])
    assert statement["commission_cents"] == 10000
    assert statement["net_cents"] == 90000

    payouts = list_payouts_for(statement_id=world["statement_id"])
    treaty = _payout_by_payee(payouts, c_treaty["id"])
    statutory = _payout_by_payee(payouts, c_statutory["id"])
    assert_payout(treaty)
    assert_payout(statutory)

    assert treaty["gross_cents"] == 45000 and statutory["gross_cents"] == 45000
    assert treaty["withholding_bps"] == 1000
    assert treaty["withholding_cents"] == 4500
    assert treaty["net_cents"] == 40500
    assert statutory["withholding_bps"] == 3000
    assert statutory["withholding_cents"] == 13500
    assert statutory["net_cents"] == 31500


def test_divergent_withholding_flows_through_to_each_payees_pending_balance(api):
    """PRD §3.8: "Each created payout starts in `PENDING` with `auto_approved` false,
    `approved_by_user_id`, `paid_by_user_id`, `paid_at` and `reversal_reason_code` all null, and
    each raises its collaborator's `pending_payout_cents` by that payout's `net_cents`."
    PRD §3.9: "`pending_payout_cents` is the sum of `net_cents` across the payee's payouts in
    `PENDING` or `APPROVED`; `lifetime_paid_cents` is the sum across those in `PAID`;
    `reversed_payout_cents` is the sum across those in `REVERSED`."

    Design: Difficulty/dual_variant_calc/collaborator_treaty_vs_statutory_withholding_divergence
    """
    world = setup_world(
        plan_overrides={"code": "LITE", "name": "Lite", "commission_bps": 1000,
                        "allows_content_id": False, "included_release_slots": 3},
        artist_overrides={"email": "vega2@example.com"},
        payees=[{"name": "Mia", "email": "mia@example.com", "country_code": "GB",
                 "tax_form_status": "VERIFIED"},
                {"name": "Neo", "email": "neo@example.com", "country_code": "GB",
                 "tax_form_status": "SUBMITTED"}],
    )
    c_treaty, c_statutory = world["payees"]
    lock_sheets_for_world(world, [[(c_treaty["id"], 5000), (c_statutory["id"], 5000)]])

    setup_closed_statement(world, [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 100000,
                             "2026-05-12T00:00:00Z", units=500000),
    ])

    assert read_collaborator(c_treaty["id"])["pending_payout_cents"] == 40500
    assert read_collaborator(c_statutory["id"])["pending_payout_cents"] == 31500


def test_withholding_rounds_half_up_on_an_exact_half_cent(api):
    """PRD §2.6: "a computed value whose fractional part is exactly one half rounds away from
    zero, to the next larger whole cent."
    PRD §3.8: "Its `withholding_cents` is the payout's `gross_cents` multiplied by that pinned
    rate, divided by 10000 and rounded half up to whole cents, and its `net_cents` is
    `gross_cents` less `withholding_cents`."

    Design: Corner/calculations/withholding_rounds_half_up_on_exact_half_cent
    """
    world = setup_single_payee_payout(
        2055,
        payee_overrides={"name": "Geo", "email": "geo@example.com", "country_code": "GB",
                         "tax_form_status": "VERIFIED"},
    )

    statement = read_statement(world["statement_id"])
    assert statement["commission_cents"] == 50
    assert statement["net_cents"] == 2005

    payout = world["payout"]
    assert payout["gross_cents"] == 2005
    assert payout["withholding_bps"] == 1000
    assert payout["withholding_cents"] == 201, "200.5 rounds away from zero to 201"
    assert payout["net_cents"] == 1804


def test_payout_of_exactly_two_thousand_net_cents_can_be_paid(api):
    """PRD §3.9: "And the payout's `net_cents` must be at least 2000 cents; anything smaller is
    refused with `ERR_PAYOUT_BELOW_THRESHOLD` (HTTP 422), since the platform does not move
    sub-threshold sums."
    PRD §3.9: "A successful payment moves the payout `APPROVED → PAID`, stamps `paid_at` with the
    current instant, records the acting `X-User-ID` into `paid_by_user_id`, lowers the payee's
    `pending_payout_cents` by the payout's `net_cents` while raising their `lifetime_paid_cents`
    by the same amount, and advances the payout's `version` by 1."

    Design: Difficulty/boundary_precision_check/payout_pay_at_exactly_2000_cents_versus_1999
    """
    world = setup_single_payee_payout(2050)
    payout = world["payout"]
    assert payout["net_cents"] == 2000
    assert payout["status"] == "APPROVED" and payout["auto_approved"] is True

    paid = validate_success(
        api.pay_payout(payout["id"], make_finance_headers(FIN_APPROVER))
    )

    assert paid["status"] == "PAID"
    assert paid["paid_by_user_id"] == FIN_APPROVER
    assert paid["paid_at"].startswith("2026-07-01T00:00:00")
    payee = read_collaborator(world["payee"]["id"])
    assert payee["lifetime_paid_cents"] == 2000
    assert payee["pending_payout_cents"] == 0


def test_payout_of_one_thousand_nine_hundred_ninety_nine_cents_is_refused(api):
    """PRD §3.9: "And the payout's `net_cents` must be at least 2000 cents; anything smaller is
    refused with `ERR_PAYOUT_BELOW_THRESHOLD` (HTTP 422), since the platform does not move
    sub-threshold sums."
    PRD §3.8: "As the last hop of the cascade, every payout the close just created whose
    `net_cents` is at least 2000 cents moves straight from `PENDING` to `APPROVED` with
    `auto_approved` set true, `approved_by_user_id` deliberately left null, and its `version`
    advanced by 1. Payouts below that threshold remain in `PENDING` awaiting a human."

    Design: Difficulty/boundary_precision_check/payout_pay_at_exactly_2000_cents_versus_1999
    """
    world = setup_single_payee_payout(2049)
    payout = world["payout"]
    assert payout["net_cents"] == 1999
    assert payout["status"] == "PENDING", "one cent short of the auto-approval threshold"

    approve_payout(payout["id"], FIN_APPROVER)

    resp = api.pay_payout(payout["id"], make_finance_headers(FIN_PAYER))
    validate_error(resp, ApiErrorId.ERR_PAYOUT_BELOW_THRESHOLD.value)

    assert read_payout(payout["id"])["status"] == "APPROVED"
    payee = read_collaborator(world["payee"]["id"])
    assert payee["lifetime_paid_cents"] == 0
    assert payee["pending_payout_cents"] == 1999


def test_the_approving_operator_may_not_also_pay_the_payout(api):
    """PRD §2.10: "Paying a payout requires, whenever the payout carries a non-null
    `approved_by_user_id`, that the acting `X-User-ID` differ from it; a payout that was
    auto-approved by the close cascade has no recorded approver and therefore imposes no such
    restriction."
    PRD §3.9: "Manual approval is available to any `FinanceOps` operator for a payout still in
    `PENDING`; it records the acting `X-User-ID` into `approved_by_user_id`, sets `auto_approved`
    to false, and advances the payout's `version` by 1."
    PRD §3.9: "When the payout carries a non-null `approved_by_user_id`, the paying operator's
    `X-User-ID` must differ from it, otherwise `ERR_SEGREGATION_OF_DUTIES`; an auto-approved
    payout has no recorded approver and so imposes no such constraint."

    Design: Corner/rbac/same_finance_user_cannot_approve_and_pay_a_payout
    """
    world = setup_single_payee_payout(2049)
    payout = world["payout"]
    assert payout["net_cents"] == 1999

    approved = validate_success(
        api.approve_payout(payout["id"], make_finance_headers(FIN_APPROVER))
    )
    assert approved["auto_approved"] is False
    assert approved["approved_by_user_id"] == FIN_APPROVER

    same_operator = api.pay_payout(payout["id"], make_finance_headers(FIN_APPROVER))
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    other_operator = api.pay_payout(payout["id"], make_finance_headers(FIN_PAYER))
    validate_error(other_operator, ApiErrorId.ERR_PAYOUT_BELOW_THRESHOLD.value)

    assert read_payout(payout["id"])["status"] == "APPROVED"
    assert read_collaborator(world["payee"]["id"])["lifetime_paid_cents"] == 0


def test_paying_a_payout_whose_payee_is_unverified_is_refused(api):
    """PRD §3.9: "The payee's `tax_form_status` must be exactly `VERIFIED` at the moment of
    payment — `MISSING`, `SUBMITTED` and `EXPIRED` all fail with `ERR_TAX_FORM_NOT_VERIFIED`
    (HTTP 422)."
    PRD §3.4: "Either the owning artist or a `FinanceOps` operator may later revise
    `tax_form_status`, `payout_method`, `country_code` or `status`; such a revision advances the
    collaborator's `version` by 1."

    Design: Corner/validations/paying_a_payout_whose_payee_tax_form_is_not_verified_rejected
    """
    world = setup_single_payee_payout(
        4050,
        payee_overrides={"name": "Sag", "email": "sag@example.com", "country_code": "US",
                         "tax_form_status": "SUBMITTED"},
    )
    payout = world["payout"]
    assert payout["status"] == "APPROVED", "the payout clears the auto-approval threshold"

    blocked = api.pay_payout(payout["id"], make_finance_headers(FIN_APPROVER))
    validate_error(blocked, ApiErrorId.ERR_TAX_FORM_NOT_VERIFIED.value)
    assert read_payout(payout["id"])["status"] == "APPROVED"

    validate_success(
        api.update_collaborator(world["payee"]["id"], {"tax_form_status": "VERIFIED"},
                                make_finance_headers(FIN_APPROVER))
    )

    paid = validate_success(api.pay_payout(payout["id"], make_finance_headers(FIN_APPROVER)))
    assert paid["status"] == "PAID"
    assert read_collaborator(world["payee"]["id"])["lifetime_paid_cents"] == paid["net_cents"]


def test_pay_moves_the_amount_from_the_pending_bucket_to_the_paid_bucket(api):
    """PRD §3.9: "`pending_payout_cents` is the sum of `net_cents` across the payee's payouts in
    `PENDING` or `APPROVED`; `lifetime_paid_cents` is the sum across those in `PAID`;
    `reversed_payout_cents` is the sum across those in `REVERSED`."
    PRD §3.9: "Payment moves an amount from the first bucket to the second and reversal moves the
    same amount from the second to the third, so the sum of all three buckets is identical before
    payment, after payment and after reversal — the payee's settled total never drifts."

    Design: Difficulty/compensating_invariant/pay_then_reverse_conserves_collaborator_settled_total_cents
    """
    world = setup_single_payee_payout(
        2050,
        payee_overrides={"name": "Gold", "email": "gold@example.com",
                         "payout_method": "BANK_TRANSFER"},
    )
    payee_id = world["payee"]["id"]

    before = read_collaborator(payee_id)
    assert before["pending_payout_cents"] == 2000
    assert before["lifetime_paid_cents"] == 0
    assert before["reversed_payout_cents"] == 0
    assert_settled_total(before, 2000)

    validate_success(api.pay_payout(world["payout"]["id"], make_finance_headers(FIN_APPROVER)))

    after_pay = read_collaborator(payee_id)
    assert after_pay["pending_payout_cents"] == 0
    assert after_pay["lifetime_paid_cents"] == 2000
    assert after_pay["reversed_payout_cents"] == 0
    assert_settled_total(after_pay, 2000)


def test_reverse_moves_the_amount_on_to_the_reversed_bucket_without_drift(api):
    """PRD §3.9: "Reversal moves the payout `PAID → REVERSED`, lowers the payee's
    `lifetime_paid_cents` by the payout's `net_cents`, raises their `reversed_payout_cents` by the
    same amount, and advances `version` by 1."
    PRD §3.9: "Payment moves an amount from the first bucket to the second and reversal moves the
    same amount from the second to the third, so the sum of all three buckets is identical before
    payment, after payment and after reversal — the payee's settled total never drifts."

    Design: Difficulty/compensating_invariant/pay_then_reverse_conserves_collaborator_settled_total_cents
    """
    world = setup_single_payee_payout(
        2050,
        payee_overrides={"name": "Gold", "email": "gold@example.com",
                         "payout_method": "BANK_TRANSFER"},
    )
    payee_id, payout_id = world["payee"]["id"], world["payout"]["id"]
    pay_payout(payout_id, FIN_APPROVER)

    reversed_payout = validate_success(
        api.reverse_payout(payout_id, "BANK_RETURNED", make_finance_headers(FIN_PAYER))
    )

    assert reversed_payout["status"] == "REVERSED"
    assert reversed_payout["reversal_reason_code"] == "BANK_RETURNED"

    after_reverse = read_collaborator(payee_id)
    assert after_reverse["pending_payout_cents"] == 0
    assert after_reverse["lifetime_paid_cents"] == 0
    assert after_reverse["reversed_payout_cents"] == 2000
    assert_settled_total(after_reverse, 2000)

    assert read_statement(world["statement_id"])["net_cents"] == 2000, (
        "the statement's own net is untouched by the pay and reverse pair"
    )


def test_reversal_ninety_days_after_payment_is_refused(api):
    """PRD §3.9: "A `PAID` payout may be reversed, with a `reason_code` recorded into
    `reversal_reason_code`, provided the current instant is strictly earlier than ninety days
    after the payout's `paid_at`; a reversal attempted ninety days or more after payment is
    refused with `ERR_REVERSAL_WINDOW_EXPIRED` (HTTP 422), and reversing anything not in `PAID` is
    refused with `ERR_INVALID_STATE`."

    Design: Corner/validations/payout_reverse_after_ninety_days_rejected
    """
    world = setup_single_payee_payout(
        2050, payee_overrides={"name": "Ind", "email": "ind@example.com"}
    )
    payout_id = world["payout"]["id"]
    paid = pay_payout(payout_id, FIN_APPROVER)
    assert paid["paid_at"].startswith("2026-07-01T00:00:00")

    set_clock("2026-09-29T00:00:00Z")
    resp = api.reverse_payout(payout_id, "TOO_LATE", make_finance_headers(FIN_PAYER))
    validate_error(resp, ApiErrorId.ERR_REVERSAL_WINDOW_EXPIRED.value)

    assert read_payout(payout_id)["status"] == "PAID"
    payee = read_collaborator(world["payee"]["id"])
    assert payee["lifetime_paid_cents"] == 2000
    assert payee["reversed_payout_cents"] == 0


def test_tax_form_walks_draft_issued_voided(api):
    """PRD §3.9: "The form is created in `DRAFT` with `issued_at` null and `total_paid_cents`
    computed immediately as the sum of `net_cents` across that collaborator's payouts whose status
    is `PAID` and whose `paid_at` falls within the calendar year named by `tax_year`, read in UTC."
    PRD §3.9: "Issuing recomputes `total_paid_cents` afresh before deciding, moves the form
    `DRAFT → ISSUED`, stamps `issued_at` with the current instant, and advances its `version` by 1
    — but only when that recomputed total is at least 60000 cents; a form below the reporting
    threshold is refused with `ERR_1099_THRESHOLD_NOT_MET` (HTTP 422), and issuing a form not in
    `DRAFT` is refused with `ERR_INVALID_STATE`."
    PRD §3.9: "An issued form may later be voided with a `reason_code`, moving it
    `ISSUED → VOIDED` and advancing its `version` by 1; `VOIDED` is terminal, and voiding anything
    not in `ISSUED` is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/tax_form_issue_and_void_walk_the_declared_lifecycle
    """
    world = setup_single_payee_payout(
        60050, payee_overrides={"name": "Payee", "email": "payee@example.com"}
    )
    payout = world["payout"]
    assert payout["net_cents"] == 60000
    pay_payout(payout["id"], FIN_APPROVER)

    form = validate_success(
        api.create_tax_form({"collaborator_id": world["payee"]["id"], "tax_year": 2026},
                            make_finance_headers(FIN_APPROVER)),
        201,
    )
    assert_tax_form(form)
    assert form["status"] == "DRAFT"
    assert form["issued_at"] is None
    assert form["total_paid_cents"] == 60000

    issued = validate_success(
        api.issue_tax_form(form["id"], make_finance_headers(FIN_APPROVER))
    )
    assert issued["status"] == "ISSUED"
    assert issued["issued_at"].startswith("2026-07-01T00:00:00")

    voided = validate_success(
        api.void_tax_form(form["id"], "CORRECTION", make_finance_headers(FIN_APPROVER))
    )
    assert voided["status"] == "VOIDED"


def test_issuing_a_1099_below_the_reporting_threshold_is_refused(api):
    """PRD §3.9: "Issuing recomputes `total_paid_cents` afresh before deciding, moves the form
    `DRAFT → ISSUED`, stamps `issued_at` with the current instant, and advances its `version` by 1
    — but only when that recomputed total is at least 60000 cents; a form below the reporting
    threshold is refused with `ERR_1099_THRESHOLD_NOT_MET` (HTTP 422), and issuing a form not in
    `DRAFT` is refused with `ERR_INVALID_STATE`."

    Design: Corner/validations/issuing_a_1099_below_the_reporting_threshold_rejected
    """
    world = setup_single_payee_payout(
        2050, payee_overrides={"name": "Tiny", "email": "tiny@example.com"}
    )
    pay_payout(world["payout"]["id"], FIN_APPROVER)
    form = draft_tax_form(world["payee"]["id"], 2026, FIN_APPROVER)
    assert form["total_paid_cents"] == 2000

    resp = api.issue_tax_form(form["id"], make_finance_headers(FIN_APPROVER))
    validate_error(resp, ApiErrorId.ERR_1099_THRESHOLD_NOT_MET.value)

    stored = read_tax_form(form["id"])
    assert stored["status"] == "DRAFT"
    assert stored["issued_at"] is None
    assert stored["total_paid_cents"] == 2000
