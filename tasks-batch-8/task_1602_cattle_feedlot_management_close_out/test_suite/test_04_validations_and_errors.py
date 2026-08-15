"""Validation-cascade violations (request shape, auth presence, fiscal caps,
conditional and aggregate rules) and per-resource 404 existence errors."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assign_pen,
    create_death_loss_payload,
    create_insurance_claim_payload,
    create_lot,
    create_owner,
    create_pen,
    create_ration,
    create_ration_assignment_payload,
    file_claim,
    record_death_loss,
    validate_error,
)

FYM = TEST_USERS["feedyard_manager_headers"]
FM = TEST_USERS["feed_manager_headers"]
CHT = TEST_USERS["cattle_health_tech_headers"]
RM = TEST_USERS["risk_manager_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestRequestShape:
    def test_request_missing_required_field_returns_400(self, api):
        """PRD §2.8: "Request shape. Required fields must be present, enum
        members valid, integer and number ranges respected (head counts greater
        than zero, quantities greater than zero, dates well-formed `YYYY-MM-DD`),
        and date-valued inputs not future-dated where a rule pins them to the
        logical clock (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "A `FeedyardManager` registers an owner by supplying an
        `owner_name` and a `billing_email`"

        Design: Corner/validations/request_missing_required_field_returns_400
        """
        resp = api.create_owner({"owner_name": "O-NOFIELD"}, FYM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_pens({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestClaimFilingGuards:
    def test_claim_above_loss_value_rejected(self, api):
        """PRD §3.5: "the claimed amount may not exceed the loss's
        `loss_value_cents` (`ERR_CLAIM_EXCEEDS_LOSS_VALUE`, HTTP 422)."

        Design: Corner/validations/claim_above_loss_value_rejected
        """
        owner = create_owner(owner_name="O-V1", billing_email="v1@x.com")
        lot = create_lot(owner["id"], lot_number="L-V1", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-01",
                                       head_count=1, insured=True)
        assert death_loss["loss_value_cents"] == 140000, (
            "In-cost per head is 700000 / 5 = 140000 with zero accrued costs"
        )
        resp = api.create_insurance_claim(
            create_insurance_claim_payload(death_loss["id"],
                                           claimed_amount_cents=140001),
            CHT,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_LOSS_VALUE)

    def test_claim_on_uninsured_loss_rejected(self, api):
        """PRD §3.5: "the loss's `insured` flag must be true
        (`ERR_DEATH_LOSS_NOT_INSURED`, HTTP 409)"

        Design: Corner/validations/claim_on_uninsured_loss_rejected
        """
        owner = create_owner(owner_name="O-V2", billing_email="v2@x.com")
        lot = create_lot(owner["id"], lot_number="L-V2", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-01",
                                       head_count=1, insured=False)
        resp = api.create_insurance_claim(
            create_insurance_claim_payload(death_loss["id"],
                                           claimed_amount_cents=100000),
            CHT,
        )
        validate_error(resp, ApiErrorId.ERR_DEATH_LOSS_NOT_INSURED)

    def test_second_claim_on_same_loss_rejected(self, api):
        """PRD §3.5: "at most one claim may exist per death loss
        (`ERR_CLAIM_ALREADY_EXISTS`, HTTP 409)"

        Design: Corner/validations/second_claim_on_same_loss_rejected
        """
        owner = create_owner(owner_name="O-V3", billing_email="v3@x.com")
        lot = create_lot(owner["id"], lot_number="L-V3", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-01",
                                       head_count=1, insured=True)
        file_claim(death_loss["id"], 100000)
        resp = api.create_insurance_claim(
            create_insurance_claim_payload(death_loss["id"],
                                           claimed_amount_cents=50000),
            CHT,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_EXISTS)


class TestStepUpAndAssignmentAggregates:
    def test_step_up_first_assignment_must_be_step_one_rejected(self, api):
        """PRD §3.3: "The step-up rule requires the lot's first ration assignment
        to be at `step_level` 1, and every subsequent assignment to be exactly
        one step above the lot's latest assignment's step level; jumping or
        repeating a step is an `ERR_STEP_UP_VIOLATION` (HTTP 409)."

        Design: Corner/validations/step_up_first_assignment_must_be_step_one_rejected
        """
        owner = create_owner(owner_name="O-V4", billing_email="v4@x.com")
        ration = create_ration(ration_name="R-V4", step_level=2,
                               cost_per_ton_cents=22000)
        lot = create_lot(owner["id"], lot_number="L-V4", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        resp = api.create_ration_assignment(
            create_ration_assignment_payload(lot["id"], ration["id"],
                                             start_date="2026-08-01",
                                             end_date="2026-08-15"),
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_STEP_UP_VIOLATION)

    def test_over_assignment_beyond_lot_head_rejected(self, api):
        """PRD §3.2: "the lot's total actively-assigned head plus the new
        `head_count` may not exceed `head_count_current`, or the request fails
        with `ERR_OVER_ASSIGNMENT` (HTTP 409)."

        Design: Corner/validations/over_assignment_beyond_lot_head_rejected
        """
        owner = create_owner(owner_name="O-V5", billing_email="v5@x.com")
        pen1 = create_pen(pen_code="V-01")
        pen2 = create_pen(pen_code="V-02")
        lot = create_lot(owner["id"], lot_number="L-V5", head_count_in=10,
                         in_weight_total_lbs=7000, purchase_cost_cents=1400000)
        assign_pen(pen1["id"], lot["id"], 6)
        resp = api.create_assignment(
            {"pen_id": pen2["id"], "lot_id": lot["id"], "head_count": 6,
             "start_date": "2026-08-01"},
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_OVER_ASSIGNMENT)


class TestLogicalClockPinning:
    def test_future_loss_date_uses_default_clock_rejected(self, api):
        """PRD §2.5: "At server startup the current logical instant is exactly
        `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock
        time."
        PRD §2.5: "`ship_date`, `loss_date`, `treatment_date`, and `offset_date`
        may not lie in the future relative to it, and a violation is an
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/future_loss_date_uses_default_clock_rejected
        """
        owner = create_owner(owner_name="O-V6", billing_email="v6@x.com")
        lot = create_lot(owner["id"], lot_number="L-V6", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        resp = api.create_death_loss(
            create_death_loss_payload(lot["id"], loss_date="2026-08-02",
                                      head_count=1, insured=False),
            CHT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFoundCatalog:
    def test_get_unknown_owner_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error — `ERR_OWNER_NOT_FOUND`,
        `ERR_PEN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, ..."

        Design: Corner/errors/get_unknown_owner_returns_404
        """
        resp = api.get_owner(NON_EXISTENT_UUID, TEST_USERS["any_headers"])
        validate_error(resp, ApiErrorId.ERR_OWNER_NOT_FOUND)

    def test_get_unknown_ration_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/errors/get_unknown_ration_returns_404
        """
        resp = api.get_ration(NON_EXISTENT_UUID, TEST_USERS["any_headers"])
        validate_error(resp, ApiErrorId.ERR_RATION_NOT_FOUND)

    def test_end_unknown_assignment_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/errors/end_unknown_assignment_returns_404
        """
        resp = api.end_assignment(NON_EXISTENT_UUID, {"end_date": "2026-08-05"},
                                  FYM)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND)

    def test_void_unknown_death_loss_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/errors/void_unknown_death_loss_returns_404
        """
        resp = api.void_death_loss(NON_EXISTENT_UUID, CHT)
        validate_error(resp, ApiErrorId.ERR_DEATH_LOSS_NOT_FOUND)

    def test_decide_unknown_claim_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/errors/decide_unknown_claim_returns_404
        """
        resp = api.decide_claim(NON_EXISTENT_UUID, {"decision": "APPROVE"}, ADJ)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_CLAIM_NOT_FOUND)

    def test_offset_unknown_hedge_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/errors/offset_unknown_hedge_returns_404
        """
        resp = api.offset_hedge(
            NON_EXISTENT_UUID,
            {"exit_price_cents_per_cwt": 18900, "offset_date": "2026-08-01"},
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_HEDGE_NOT_FOUND)

    def test_confirm_unknown_closeout_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/errors/confirm_unknown_closeout_returns_404
        """
        resp = api.confirm_close_out(
            NON_EXISTENT_UUID,
            {"carcass_records": [
                {"hot_carcass_weight_lbs": 763, "quality_grade": "CHOICE",
                 "yield_grade": 2},
            ]},
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_CLOSE_OUT_NOT_FOUND)

    def test_pay_unknown_invoice_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/errors/pay_unknown_invoice_returns_404
        """
        resp = api.pay_invoice(
            NON_EXISTENT_UUID,
            {"amount_cents": 100, "payment_date": "2026-08-01"},
            BC,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)
