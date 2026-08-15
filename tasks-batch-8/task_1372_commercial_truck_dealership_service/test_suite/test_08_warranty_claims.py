"""Warranty claims: submission, adjudication, segregation of duties, appeal
cycle, payments, write-offs, and the AR cascade (PRD §3.8, §2.9)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    create_account, create_fleet_account, create_repair_order, add_labor_line,
    create_bay, create_bay_booking, check_in_booking, drive_ro_to_invoiced,
    create_claim, create_submitted_claim, create_part, create_parts_sale,
    set_clock, make_fleet_customer_headers, make_warranty_admin_headers,
    make_oem_adjudicator_headers,
)

ADVISOR = TEST_USERS["service_advisor_headers"]
SERVICE_MGR = TEST_USERS["service_manager_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]

OEM_9 = make_oem_adjudicator_headers("oem-9")
WADMIN_1 = make_warranty_admin_headers("wadmin-1")


def _get_claim(claim_id):
    return get_success_data(api_client.get_warranty_claim(claim_id, WARRANTY_ADMIN))


def _get_ro(ro_id):
    return get_success_data(api_client.get_repair_order(ro_id, ADVISOR))


def _account(account_id):
    return get_success_data(api_client.get_customer_account(account_id, CONTROLLER))


def _invoiced_ro_with_eligible_labor(account_id, hours=1.0, labor_rate_cents=None):
    return drive_ro_to_invoiced(account_id, labor_hours=hours,
                                labor_rate_cents=labor_rate_cents,
                                warranty_eligible=True)


# ---------------------------------------------------------------- Queue A ---

class TestClaimDenyAppealApproveCycle:
    def _setup(self):
        acct = create_account(name="RetailOne")
        ctx = _invoiced_ro_with_eligible_labor(acct["id"])  # due 17325
        claim = create_submitted_claim(ctx["ro"]["id"], 16500, 0)
        return acct, ctx["ro"], claim

    def test_deny_then_appeal_reopens_claim(self, api):
        """PRD §3.8: "`DENY` zeroes both approved amounts and requires a
        `denial_reason` (`ERR_INVALID_REQUEST`)."
        PRD §3.8: "A denied or short-paid claim can be appealed by the warranty
        administrator with mandatory `appeal_notes` (`ERR_INVALID_REQUEST` if
        absent), moving to `APPEALED` and incrementing `appeal_count` by one."

        Design: Difficulty/non_linear_state_machine/warranty_claim_deny_appeal_approve_cycle
        """
        _, _, claim = self._setup()
        denied = validate_success(api_client.adjudicate_warranty_claim(
            claim["id"], {"outcome": "DENY", "denial_reason": "wear item not covered"},
            OEM_9), 200)
        assert denied["status"] == "DENIED"
        assert denied["approved_labor_cents"] == 0
        assert denied["approved_parts_cents"] == 0
        appealed = validate_success(api_client.appeal_warranty_claim(
            claim["id"], {"appeal_notes": "TSB 23-91 covers actuator"}, WADMIN_1), 200)
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_count"] == 1

    def test_appealed_claim_approval_fires_ro_and_ar_cascade(self, api):
        """PRD §3.8: "`APPROVE` sets `approved_labor_cents` and
        `approved_parts_cents` equal to the claimed amounts."
        PRD §3.8: "the repair order's `warranty_covered_cents` is recomputed as
        the approved-total sum over its claims in `APPROVED`, `SHORT_PAID`, or
        `PAID`; the order's `customer_due_cents` is recomputed from the §3.7
        formula; if the order is `INVOICED`, the account's `open_ar_cents` is
        adjusted by the change in customer-due".

        Design: Difficulty/non_linear_state_machine/warranty_claim_deny_appeal_approve_cycle
        """
        acct, ro, claim = self._setup()
        api_client.adjudicate_warranty_claim(
            claim["id"], {"outcome": "DENY", "denial_reason": "wear item"}, OEM_9)
        api_client.appeal_warranty_claim(
            claim["id"], {"appeal_notes": "TSB 23-91 covers actuator"}, WADMIN_1)
        approved = validate_success(api_client.adjudicate_warranty_claim(
            claim["id"], {"outcome": "APPROVE"}, OEM_9), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_labor_cents"] == 16500
        assert approved["approved_parts_cents"] == 0
        ro_after = _get_ro(ro["id"])
        assert ro_after["warranty_covered_cents"] == 16500
        assert ro_after["customer_due_cents"] == 825  # 17325 - 16500
        assert _account(acct["id"])["open_ar_cents"] == 825


class TestClaimSubmitRequiresInvoicedRo:
    def _setup_completed_ro(self):
        acct = create_account(name="XDep3")
        ro = create_repair_order(acct["id"])
        add_labor_line(ro["id"], hours=1.0, warranty_eligible=True)
        get_success_data(api_client.submit_estimate(ro["id"], ADVISOR))
        get_success_data(api_client.approve_estimate(
            ro["id"], make_fleet_customer_headers(acct["id"])))
        bay = create_bay()
        booking = create_bay_booking(ro["id"], bay["id"])
        check_in_booking(booking["id"])
        get_success_data(api_client.start_work(ro["id"], ADVISOR))
        get_success_data(api_client.complete_work(ro["id"], ADVISOR))
        return acct, ro

    def test_submit_rejected_while_ro_not_invoiced(self, api):
        """PRD §3.8: "Submission requires the claim be `DRAFT`
        (`ERR_CLAIM_STATE`) and the repair order be `INVOICED`
        (`ERR_RO_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_invoiced_ro
        """
        _, ro = self._setup_completed_ro()
        assert _get_ro(ro["id"])["work_status"] == "COMPLETED"
        claim = create_claim(ro["id"], 16500, 0)
        validate_error(api_client.submit_warranty_claim(claim["id"], WADMIN_1),
                       ApiErrorId.ERR_RO_STATE)
        assert _get_claim(claim["id"])["status"] == "DRAFT"

    def test_submit_succeeds_after_invoice_and_captures_submitter(self, api):
        """PRD §3.8: "it stamps `submitted_at` and captures the caller's header
        into `submitted_by_user_id`, the segregation-of-duties anchor."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_invoiced_ro
        """
        acct, ro = self._setup_completed_ro()
        claim = create_claim(ro["id"], 16500, 0)
        validate_success(api_client.invoice_repair_order(ro["id"], SERVICE_MGR), 200)
        data = validate_success(api_client.submit_warranty_claim(claim["id"], WADMIN_1), 200)
        assert data["status"] == "SUBMITTED"
        assert data["submitted_by_user_id"] == "wadmin-1"
        assert data["submitted_at"]


class TestAdjudicationCascade:
    def _setup(self):
        acct = create_fleet_account(tier="STANDARD", credit_limit_cents=100000,
                                    name="CascadeCo")
        # labor 8.0h @ 10000 -> 80000; fee capped 3500; due 83500
        ctx = _invoiced_ro_with_eligible_labor(acct["id"], hours=8.0,
                                               labor_rate_cents=10000)
        part = create_part(list_price_cents=20000, cost_cents=12000, on_hand=5,
                           sku="TURBO-1")
        create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 1}])
        claim = create_submitted_claim(ctx["ro"]["id"], 80000, 0)
        return acct, ctx["ro"], claim

    def test_approval_recomputes_due_and_adjusts_receivable(self, api):
        """PRD §3.8: "Approval and short-pay fire a four-level cascade: the
        repair order's `warranty_covered_cents` is recomputed as the
        approved-total sum over its claims in `APPROVED`, `SHORT_PAID`, or
        `PAID`; the order's `customer_due_cents` is recomputed from the §3.7
        formula; if the order is `INVOICED`, the account's `open_ar_cents` is
        adjusted by the change in customer-due".

        Design: Difficulty/transitive_cascade/adjudication_cascades_to_ro_account_and_credit_posture
        """
        acct, ro, claim = self._setup()
        assert _get_ro(ro["id"])["customer_due_cents"] == 83500
        assert _account(acct["id"])["open_ar_cents"] == 103500
        validate_success(api_client.adjudicate_warranty_claim(
            claim["id"], {"outcome": "APPROVE"}, OEM_9), 200)
        ro_after = _get_ro(ro["id"])
        assert ro_after["warranty_covered_cents"] == 80000
        assert ro_after["customer_due_cents"] == 3500  # 83500 - 80000
        assert _account(acct["id"])["open_ar_cents"] == 23500  # 103500 - 80000

    def test_cascade_clears_credit_hold(self, api):
        """PRD §3.8: "and that receivable movement re-evaluates the account's
        credit posture, clearing a `CREDIT_HOLD` back to `ACTIVE` when the
        receivable returns to at or below the ceiling."
        PRD §2.9: "a `FLEET` account whose `open_ar_cents` exceeds its
        `credit_limit_cents` is placed on `CREDIT_HOLD`".

        Design: Difficulty/transitive_cascade/adjudication_cascades_to_ro_account_and_credit_posture
        """
        acct, _, claim = self._setup()
        assert _account(acct["id"])["status"] == "CREDIT_HOLD"  # 103500 > 100000
        validate_success(api_client.adjudicate_warranty_claim(
            claim["id"], {"outcome": "APPROVE"}, OEM_9), 200)
        assert _account(acct["id"])["status"] == "ACTIVE"  # 23500 <= 100000


# ---------------------------------------------------------------- Queue B ---

def test_claim_submit_and_close_terminal_states(api):
    """PRD §3.8: "when cumulative payments reach the approved total the claim
    becomes `PAID`."
    PRD §3.8: "A denied or short-paid claim can be appealed by the warranty
    administrator".
    PRD §3.8: "posting a claim payment of `amount_cents` requires the claim be
    `APPROVED` or `SHORT_PAID` (`ERR_CLAIM_STATE`)".

    Design: Corner/state_machines/claim_submit_and_close_terminal_states
    """
    acct = create_account(name="TermCl")
    ctx = _invoiced_ro_with_eligible_labor(acct["id"])
    claim = create_submitted_claim(ctx["ro"]["id"], 16500, 0)
    validate_success(api_client.adjudicate_warranty_claim(
        claim["id"], {"outcome": "APPROVE"}, OEM_9), 200)
    paid = validate_success(api_client.post_claim_payment(
        claim["id"], {"amount_cents": 16500}, CONTROLLER), 200)
    assert paid["status"] == "PAID"
    validate_error(api_client.appeal_warranty_claim(
        claim["id"], {"appeal_notes": "too late"}, WADMIN_1), ApiErrorId.ERR_CLAIM_STATE)
    validate_error(api_client.post_claim_payment(
        claim["id"], {"amount_cents": 100}, CONTROLLER), ApiErrorId.ERR_CLAIM_STATE)


def test_segregation_of_duties_on_adjudication(api):
    """PRD §3.8: "the hard segregation rule that the adjudicator's identity
    must differ from `submitted_by_user_id` — a self-adjudication is refused
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_on_adjudication
    """
    acct = create_account(name="SoDCo")
    ctx = _invoiced_ro_with_eligible_labor(acct["id"])
    claim = create_submitted_claim(ctx["ro"]["id"], 16500, 0)
    resp = api_client.adjudicate_warranty_claim(
        claim["id"], {"outcome": "APPROVE"}, make_oem_adjudicator_headers("wadmin-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    assert _get_claim(claim["id"])["status"] == "SUBMITTED"


def test_claim_amounts_capped_by_eligible_line_sums(api):
    """PRD §3.8: "A claim is drafted against a repair order with
    `claimed_labor_cents` and `claimed_parts_cents`, each at least zero and
    each capped by the sum of `line_total_cents` over the order's
    warranty-eligible lines of the matching type — an over-claim is
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/claim_amounts_capped_by_eligible_line_sums
    """
    acct = create_account(name="CapCo")
    ro = create_repair_order(acct["id"])
    add_labor_line(ro["id"], hours=1.0, warranty_eligible=True)  # eligible 16500
    resp = api_client.create_warranty_claim(
        {"repair_order_id": ro["id"], "claimed_labor_cents": 20000,
         "claimed_parts_cents": 0}, WARRANTY_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_short_pay_cannot_exceed_claimed(api):
    """PRD §3.8: "`SHORT_PAY` stores the supplied approved amounts, which must
    not exceed their claimed counterparts (`ERR_APPROVAL_EXCEEDS_CLAIM`) and
    must sum to something positive (`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/short_pay_cannot_exceed_claimed
    """
    acct = create_account(name="ShortCo")
    ctx = _invoiced_ro_with_eligible_labor(acct["id"])
    claim = create_submitted_claim(ctx["ro"]["id"], 16500, 0)
    resp = api_client.adjudicate_warranty_claim(
        claim["id"], {"outcome": "SHORT_PAY", "approved_labor_cents": 17000,
                      "approved_parts_cents": 0}, OEM_9)
    validate_error(resp, ApiErrorId.ERR_APPROVAL_EXCEEDS_CLAIM)
    assert _get_claim(claim["id"])["status"] == "SUBMITTED"


def test_warranty_writeoff_window_and_small_balance_rules(api):
    """PRD §3.8: "the controller may write off the residual receivable: the
    residual (approved total minus `paid_cents`) must be positive, and the
    write-off is permitted only when the residual is at most 2,500 cents or the
    logical clock has passed `adjudicated_at` by more than 45 days — violations
    are `ERR_WRITEOFF_RULE_VIOLATION`."

    Design: Corner/calculations/warranty_writeoff_window_and_small_balance_rules
    """
    acct = create_account(name="WOffCo")
    # Claim A: approved 78000; post a partial payment of 75500 so the residual
    # (approved_total - paid_cents) is 2500 (<= 2500) -> writable immediately.
    ctx_a = _invoiced_ro_with_eligible_labor(acct["id"], hours=8.0,
                                             labor_rate_cents=10000)
    claim_a = create_submitted_claim(ctx_a["ro"]["id"], 80000, 0)
    validate_success(api_client.adjudicate_warranty_claim(
        claim_a["id"], {"outcome": "SHORT_PAY", "approved_labor_cents": 78000,
                        "approved_parts_cents": 0}, OEM_9), 200)
    validate_success(api_client.post_claim_payment(
        claim_a["id"], {"amount_cents": 75500}, CONTROLLER), 200)
    data = validate_success(api_client.write_off_claim(claim_a["id"], CONTROLLER), 200)
    assert data["status"] == "WRITTEN_OFF"

    # Claim B: approved 74000, residual 74000 (> 2500) -> needs age > 45 days.
    ctx_b = _invoiced_ro_with_eligible_labor(acct["id"], hours=8.0,
                                             labor_rate_cents=10000)
    claim_b = create_submitted_claim(ctx_b["ro"]["id"], 80000, 0)
    set_clock("2026-08-10T00:00:00Z")
    validate_success(api_client.adjudicate_warranty_claim(
        claim_b["id"], {"outcome": "SHORT_PAY", "approved_labor_cents": 74000,
                        "approved_parts_cents": 0}, OEM_9), 200)
    set_clock("2026-09-24T00:00:00Z")  # exactly adjudicated_at + 45 days
    validate_error(api_client.write_off_claim(claim_b["id"], CONTROLLER),
                   ApiErrorId.ERR_WRITEOFF_RULE_VIOLATION)
    set_clock("2026-09-25T00:00:00Z")  # 46 days
    data = validate_success(api_client.write_off_claim(claim_b["id"], CONTROLLER), 200)
    assert data["status"] == "WRITTEN_OFF"
