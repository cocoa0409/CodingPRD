"""Adjustment claims and warranty claims: aging variants, submission gates,
deadline boundaries, capacity, escalation, write-off, and closure bubble-up."""
import pytest

from test_helpers import (
    ApiErrorId,
    analyst,
    assign_case,
    create_account,
    create_check_item,
    create_clearing_bank,
    create_claim_payload,
    create_warranty_claim_payload,
    set_clock,
    setup_acknowledged_claim,
    setup_assigned_encoding_claim,
    setup_denied_claim,
    setup_encoding_error_claim,
    setup_image_warranty_case,
    setup_resolved_case_with_denied_claim,
    setup_returned_item,
    setup_submitted_claim,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OFFICER,
    PROCESSOR,
    get_first_case_for_item,
    get_first_claim_for_case,
    list_claims_for_case,
    list_notifications,
)


class TestClaimAgingVariants:
    def _encoding_claim_at_monday(self):
        """Encoding claim created at the default Friday clock (2026-05-01),
        read after advancing to Monday 2026-05-11."""
        ctx = setup_encoding_error_claim(
            amount_cents=100000, encoded_amount_cents=90000,
            bank_overrides={"name": "CB Two", "routing_number": "111000026"},
            item_reference="ITM-ENC",
        )
        set_clock("2026-05-11T00:00:00Z")
        claims = list_claims_for_case(ctx["case"]["id"])
        assert len(claims) == 1
        return claims[0]

    def test_claim_aging_calendar_days(self, api):
        """PRD §3.6: "`aging_calendar_days` is the whole number of calendar
        days from the claim's `created_at` date to the current date." and "a
        claim created on Friday 2026-05-01 and read on Monday 2026-05-11 has
        an `aging_calendar_days` of 10 but an `aging_business_days` of 6."
        PRD §3.3: the auto claim's `claimed_amount_cents` "is the absolute
        difference between the encoded and face amounts".

        Design: Difficulty/dual_variant_calc/claim_aging_business_vs_calendar
        """
        claim = self._encoding_claim_at_monday()
        assert claim["aging_calendar_days"] == 10
        assert claim["claimed_amount_cents"] == 10000

    def test_claim_aging_business_days(self, api):
        """PRD §3.6: "`aging_business_days` counts only the
        Monday-through-Friday dates strictly after the creation date up to
        and including the current date." and "a claim created on Friday
        2026-05-01 and read on Monday 2026-05-11 has an `aging_calendar_days`
        of 10 but an `aging_business_days` of 6."

        Design: Difficulty/dual_variant_calc/claim_aging_business_vs_calendar
        """
        claim = self._encoding_claim_at_monday()
        assert claim["aging_business_days"] == 6
        assert claim["aging_business_days"] != claim["aging_calendar_days"]


class TestClaimSubmitCaseDependency:
    def test_claim_submit_rejected_while_case_open(self, api):
        """PRD §3.6: "Six preconditions guard the transition, evaluated in
        this order: the claim must be `DRAFT` (else `ERR_INVALID_STATE`); the
        linked case must be `ASSIGNED` (else `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_case_assigned
        """
        ctx = setup_encoding_error_claim(
            amount_cents=100000, encoded_amount_cents=80000,
            bank_overrides={"name": "CB CS", "routing_number": "111000038"},
            item_reference="ITM-CS",
        )
        assert ctx["case"]["status"] == "OPEN"
        res = api.submit_adjustment_claim(ctx["claim"]["id"], analyst("analyst-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_claim_submit_succeeds_once_case_assigned(self, api):
        """PRD §3.6: "the linked case must be `ASSIGNED` (else
        `ERR_INVALID_STATE`)" and "Submitting a `DRAFT` adjustment claim
        moves it to `SUBMITTED` and records `submitted_at`."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_case_assigned
        """
        ctx = setup_encoding_error_claim(
            amount_cents=100000, encoded_amount_cents=80000,
            bank_overrides={"name": "CB CS", "routing_number": "111000038"},
            item_reference="ITM-CS",
        )
        assign_case(ctx["case"]["id"], "analyst-1")
        submitted = validate_success(
            api.submit_adjustment_claim(ctx["claim"]["id"], analyst("analyst-1")), 200
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] is not None


class TestClaimSubmitValidationOrder:
    def test_settled_claim_resubmit_reports_state_not_window(self, api):
        """PRD §3.6: "Six preconditions guard the transition, evaluated in
        this order: the claim must be `DRAFT` (else `ERR_INVALID_STATE`); the
        linked case must be `ASSIGNED` (else `ERR_INVALID_STATE`); the
        submission must fall within the clearing bank's
        `claim_window_business_days` business days of the claim's
        `created_at` (else `ERR_CLAIM_WINDOW_EXPIRED`)" — the state check
        precedes the temporal check, so a SETTLED claim past its window
        surfaces ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_vs_temporal
        """
        ctx = setup_acknowledged_claim(
            analyst_id="analyst-1",
            bank_overrides={"name": "CB PC", "routing_number": "111000033"},
            item_reference="ITM-PC",
        )
        settled = validate_success(
            api.settle_adjustment_claim(
                ctx["claim"]["id"],
                {"outcome": "SETTLED", "recovered_amount_cents": 10000},
                analyst("analyst-2"),
            ),
            200,
        )
        assert settled["status"] == "SETTLED"
        # Past the 3-business-day claim window (Friday + 3 business days was
        # Wednesday 2026-05-06).
        set_clock("2026-05-11T00:00:00Z")
        res = api.submit_adjustment_claim(ctx["claim"]["id"], analyst("analyst-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_acknowledged_claim_resubmit_reports_state_not_window(self, api):
        """PRD §3.6: "Six preconditions guard the transition, evaluated in
        this order: the claim must be `DRAFT` (else `ERR_INVALID_STATE`); the
        linked case must be `ASSIGNED` (else `ERR_INVALID_STATE`); the
        submission must fall within the clearing bank's
        `claim_window_business_days` business days of the claim's
        `created_at` (else `ERR_CLAIM_WINDOW_EXPIRED`)" — an ACKNOWLEDGED
        claim past its window likewise surfaces the state error.

        Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_vs_temporal
        """
        ctx = setup_acknowledged_claim(
            analyst_id="analyst-1",
            bank_overrides={"name": "CB PC2", "routing_number": "111000043"},
            item_reference="ITM-PC2",
        )
        assert ctx["claim"]["status"] == "ACKNOWLEDGED"
        set_clock("2026-05-11T00:00:00Z")
        res = api.submit_adjustment_claim(ctx["claim"]["id"], analyst("analyst-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestClaimWindowBoundary:
    def test_claim_submit_window_boundary(self, api):
        """PRD §3.6: "the submission must fall within the clearing bank's
        `claim_window_business_days` business days of the claim's
        `created_at` (else `ERR_CLAIM_WINDOW_EXPIRED`)". With the default
        3-business-day window and a Friday 2026-05-01 creation, Wednesday
        2026-05-06 is the last in-window business day and Thursday
        2026-05-07 is expired (PRD §2.4 business-day counting).

        Design: Corner/calculations/claim_submit_window_boundary
        """
        ctx = setup_assigned_encoding_claim(
            analyst_id="analyst-1",
            amount_cents=100000, encoded_amount_cents=95000,
            bank_overrides={
                "name": "CB CW",
                "routing_number": "222000018",
                "claim_window_business_days": 3,
            },
            item_reference="ITM-CW",
        )
        claim1 = ctx["claim"]
        claim2 = validate_success(
            api.create_adjustment_claim(
                ctx["case"]["id"], create_claim_payload(claimed_amount_cents=500),
                analyst("analyst-1"),
            ),
            201,
        )

        set_clock("2026-05-06T00:00:00Z")
        submitted = validate_success(
            api.submit_adjustment_claim(claim1["id"], analyst("analyst-1")), 200
        )
        assert submitted["status"] == "SUBMITTED"

        set_clock("2026-05-07T00:00:00Z")
        late = api.submit_adjustment_claim(claim2["id"], analyst("analyst-1"))
        validate_error(late, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


class TestDailyCapacity:
    def test_clearing_bank_daily_capacity_exceeded(self, api):
        """PRD §3.6: "the clearing bank must have fewer than
        `daily_claim_capacity` claims already submitted on the current
        business day (else `ERR_CLEARING_BANK_CAPACITY_EXCEEDED`)"

        Design: Corner/validations/clearing_bank_daily_capacity_exceeded
        """
        bank = create_clearing_bank(
            name="CB Cap", routing_number="222000025", daily_claim_capacity=1
        )
        account = create_account(customer_name="Kurt", account_number="A-2017")
        claims = []
        for ref, amount, encoded in (("ITM-C1", 100000, 90000), ("ITM-C2", 50000, 40000)):
            item = create_check_item(
                account["id"], bank["id"], item_reference=ref,
                amount_cents=amount, encoded_amount_cents=encoded,
            )
            validate_success(api.present_check_item(item["id"], PROCESSOR), 200)
            case = get_first_case_for_item(item["id"], case_type="ENCODING_ERROR")
            assign_case(case["id"], "analyst-1")
            claims.append(get_first_claim_for_case(case["id"]))

        first = validate_success(
            api.submit_adjustment_claim(claims[0]["id"], analyst("analyst-1")), 200
        )
        assert first["status"] == "SUBMITTED"
        second = api.submit_adjustment_claim(claims[1]["id"], analyst("analyst-1"))
        validate_error(second, ApiErrorId.ERR_CLEARING_BANK_CAPACITY_EXCEEDED)


class TestEscalationSweep:
    def test_claim_escalation_sweep_at_boundary(self, api):
        """PRD §3.9: "it escalates every `SUBMITTED` or `ACKNOWLEDGED`
        adjustment claim and every `SUBMITTED` warranty claim whose
        `aging_business_days` has reached at least 10, moving them to
        `ESCALATED`." A claim created Friday 2026-05-01 reaches exactly 10
        business days on Friday 2026-05-15 (PRD §2.4 counting).

        Design: Corner/calculations/claim_escalation_sweep_at_boundary
        """
        ctx = setup_submitted_claim(
            analyst_id="analyst-1",
            bank_overrides={"name": "CB Esc", "routing_number": "222000021"},
            item_reference="ITM-ESC",
        )
        set_clock("2026-05-15T00:00:00Z")
        report = validate_success(api.run_daily_ops(ADMIN), 200)
        assert report["claims_escalated"] == 1

        claims = list_claims_for_case(ctx["case"]["id"])
        assert claims[0]["status"] == "ESCALATED"
        assert claims[0]["aging_business_days"] == 10


class TestWriteOff:
    def test_write_off_aging_gate(self, api):
        """PRD §3.6: "A `ComplianceOfficer` may write off a `DENIED` or
        `ESCALATED` claim — again never its creator, else
        `ERR_SEGREGATION_OF_DUTIES` — but only once `aging_business_days` has
        reached at least 30; earlier attempts are rejected with
        `ERR_CLAIM_NOT_AGED_ENOUGH`." A claim created Friday 2026-05-01 is at
        29 business days on 2026-06-11 and 30 on 2026-06-12.

        Design: Corner/calculations/write_off_aging_gate
        """
        ctx = setup_denied_claim(
            analyst_id="analyst-1",
            bank_overrides={"name": "CB AG", "routing_number": "222000022"},
            item_reference="ITM-AG",
        )
        set_clock("2026-06-11T00:00:00Z")
        early = api.write_off_adjustment_claim(
            ctx["claim"]["id"], {"write_off_reason": "too early"}, OFFICER
        )
        validate_error(early, ApiErrorId.ERR_CLAIM_NOT_AGED_ENOUGH)

        set_clock("2026-06-12T00:00:00Z")
        written = validate_success(
            api.write_off_adjustment_claim(
                ctx["claim"]["id"], {"write_off_reason": "aged out"}, OFFICER
            ),
            200,
        )
        assert written["status"] == "WRITTEN_OFF"

    def test_claim_writeoff_closes_resolved_case(self, api):
        """PRD §3.6: "Write-off records the supplied `write_off_reason` and
        `written_off_at`, lands the claim in the terminal `WRITTEN_OFF`
        state, and fires the same case-closure bubble-up."
        PRD §3.5: "The same close also happens automatically, without a
        client request, the moment a linked claim or warranty reaches a
        terminal state and no non-terminal claims or warranties remain on a
        `RESOLVED` case".

        Design: Difficulty/transitive_cascade/claim_writeoff_closes_case_cascade
        """
        ctx = setup_resolved_case_with_denied_claim(
            bank_overrides={"name": "CB WO", "routing_number": "111000032"},
            item_reference="ITM-WO",
        )
        assert ctx["case"]["status"] == "RESOLVED"
        set_clock("2026-06-12T00:00:00Z")
        written = validate_success(
            api.write_off_adjustment_claim(
                ctx["claim"]["id"],
                {"write_off_reason": "uncollectible after 30 business days"},
                OFFICER,
            ),
            200,
        )
        assert written["status"] == "WRITTEN_OFF"

        case = validate_success(api.get_adjustment_case(ctx["case"]["id"], ADMIN), 200)
        assert case["status"] == "CLOSED"

    def test_claim_writeoff_raises_case_closed_notification(self, api):
        """PRD §3.5: "Closing records `closed_at` and raises a `CASE_CLOSED`
        customer notification in `PENDING` status."
        PRD §3.6: "Write-off records the supplied `write_off_reason` and
        `written_off_at`, lands the claim in the terminal `WRITTEN_OFF`
        state, and fires the same case-closure bubble-up."

        Design: Difficulty/transitive_cascade/claim_writeoff_closes_case_cascade
        """
        ctx = setup_resolved_case_with_denied_claim(
            bank_overrides={"name": "CB WO2", "routing_number": "111000044"},
            item_reference="ITM-WO2",
        )
        set_clock("2026-06-12T00:00:00Z")
        validate_success(
            api.write_off_adjustment_claim(
                ctx["claim"]["id"],
                {"write_off_reason": "uncollectible after 30 business days"},
                OFFICER,
            ),
            200,
        )
        notices = list_notifications(adjustment_case_id=ctx["case"]["id"])
        assert any(
            n["notification_type"] == "CASE_CLOSED" and n["status"] == "PENDING"
            for n in notices
        ), f"expected a PENDING CASE_CLOSED notification, got {notices}"


class TestSegregationOfDuties:
    def test_segregation_of_duties_on_settle(self, api):
        """PRD §3.6: "An `AdjustmentAnalyst` settles an `ACKNOWLEDGED` or
        `ESCALATED` claim by supplying an `outcome` of `SETTLED` or `DENIED`;
        the acting analyst must not be the claim's `created_by_user_id`, on
        pain of `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/cross_cutting_layers/segregation_of_duties_on_settle
        """
        ctx = setup_returned_item(
            amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB SD", "routing_number": "222000043"},
            item_reference="ITM-SD",
        )
        assign_case(ctx["return_case"]["id"], "analyst-1")
        claim = validate_success(
            api.create_adjustment_claim(
                ctx["return_case"]["id"], create_claim_payload(claimed_amount_cents=1200),
                analyst("analyst-1"),
            ),
            201,
        )
        validate_success(
            api.submit_adjustment_claim(claim["id"], analyst("analyst-1")), 200
        )
        validate_success(api.acknowledge_adjustment_claim(claim["id"], {}, ADMIN), 200)

        own = api.settle_adjustment_claim(
            claim["id"],
            {"outcome": "SETTLED", "recovered_amount_cents": 1200},
            analyst("analyst-1"),
        )
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        settled = validate_success(
            api.settle_adjustment_claim(
                claim["id"],
                {"outcome": "SETTLED", "recovered_amount_cents": 1200},
                analyst("analyst-2"),
            ),
            200,
        )
        assert settled["status"] == "SETTLED"

    def test_analyst_cannot_write_off_claim(self, api):
        """PRD §4 endpoint table: "POST `/bank/adjustment-claims/{id}/write-off`
        | Write off a `DENIED` or `ESCALATED` claim aged at least 30 business
        days | ComplianceOfficer".
        PRD §2.1: "A request whose role is authenticated but not in the
        endpoint's authorized role list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/analyst_cannot_write_off_claim
        """
        ctx = setup_denied_claim(
            analyst_id="analyst-1",
            bank_overrides={"name": "CB RB", "routing_number": "222000040"},
            item_reference="ITM-RB",
        )
        res = api.write_off_adjustment_claim(
            ctx["claim"]["id"], {"write_off_reason": "role test"}, analyst("analyst-2")
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestWarrantyClaims:
    def _warranty_case_with_two_drafts(self, api):
        ctx = setup_image_warranty_case(
            score=50, amount_cents=80000,
            bank_overrides={
                "name": "CB WD",
                "routing_number": "222000017",
                "warranty_window_days": 7,
            },
            item_reference="ITM-WD",
        )
        wc1 = validate_success(
            api.create_warranty_claim(
                ctx["case"]["id"], create_warranty_claim_payload(claimed_amount_cents=80000),
                analyst("analyst-1"),
            ),
            201,
        )
        wc2 = validate_success(
            api.create_warranty_claim(
                ctx["case"]["id"], create_warranty_claim_payload(claimed_amount_cents=1000),
                analyst("analyst-1"),
            ),
            201,
        )
        return ctx, wc1, wc2

    def test_warranty_submit_deadline_boundary(self, api):
        """PRD §3.6: "A warranty claim's `deadline_at` is computed at
        creation as the item's `presented_at` plus the clearing bank's
        `warranty_window_days` calendar days, and submission is allowed only
        while the current logical time is on or before `deadline_at`; a late
        submit is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`."
        (Presented Friday 2026-05-01T00:00:00Z + 7 calendar days ->
        deadline 2026-05-08T00:00:00Z; submit at the deadline succeeds, the
        next day fails.)

        Design: Corner/calculations/warranty_submit_deadline_boundary
        """
        _ctx, wc1, wc2 = self._warranty_case_with_two_drafts(api)
        assert wc1["deadline_at"].startswith("2026-05-08T00:00:00")

        set_clock("2026-05-08T00:00:00Z")
        submitted = validate_success(
            api.submit_warranty_claim(wc1["id"], analyst("analyst-1")), 200
        )
        assert submitted["status"] == "SUBMITTED"

        set_clock("2026-05-09T00:00:00Z")
        late = api.submit_warranty_claim(wc2["id"], analyst("analyst-1"))
        validate_error(late, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED)

    def test_warranty_on_non_image_case_rejected(self, api):
        """PRD §3.6: "One may be created only on a case whose `case_type` is
        `IMAGE_WARRANTY` — any other case type is rejected with
        `ERR_CASE_TYPE_MISMATCH`"

        Design: Corner/validations/warranty_on_non_image_case_rejected
        """
        ctx = setup_returned_item(
            amount_cents=5000, opening_balance_cents=100000,
            bank_overrides={"name": "CB TM", "routing_number": "222000027"},
            item_reference="ITM-TM",
        )
        assert ctx["return_case"]["case_type"] == "RETURN_ITEM"
        res = api.create_warranty_claim(
            ctx["return_case"]["id"], create_warranty_claim_payload(claimed_amount_cents=5000),
            analyst("analyst-1"),
        )
        validate_error(res, ApiErrorId.ERR_CASE_TYPE_MISMATCH)
