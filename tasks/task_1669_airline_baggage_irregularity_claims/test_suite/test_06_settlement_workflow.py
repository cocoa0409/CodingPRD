"""Settlement negotiation, OCC-guarded payment creation, void/mark-paid
compensation, and terminal lockdown (PRD §2.9, §3.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    setup_bag_and_report, setup_declared_lost_report, setup_settlement_accepted,
    setup_closed_report, setup_damage_report_claim_review, create_expense_claim,
    make_receipt,
    TEST_USERS, make_passenger_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestClaimReviewDoors:

    def test_open_claim_review_requires_delivered(self, api):
        """PRD §3.8: "For a bag recovered late, the adjuster opens claim review on a
        report in `DELIVERED` — on any other status the request is rejected with
        `ERR_REPORT_NOT_DELIVERED`."

        Design: Corner/state_machines/open_claim_review_requires_delivered
        """
        ctx = setup_bag_and_report(report_type="DELAYED")  # still TRACING
        resp = api.open_claim_review(ctx["report"]["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DELIVERED, 409)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["status"] == "TRACING"

    def test_assess_loss_requires_declared_lost(self, api):
        """PRD §3.8: "For a lost bag, the adjuster records the assessed
        `contents_loss_cents` on a report in `DECLARED_LOST` — assessing loss on a
        report in any other status is rejected with `ERR_REPORT_NOT_DECLARED_LOST`"

        Design: Corner/state_machines/assess_loss_requires_declared_lost
        """
        ctx = setup_bag_and_report(report_type="DELAYED")  # TRACING, before sweep
        resp = api.assess_loss(ctx["report"]["id"], {"contents_loss_cents": 100000},
                               ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DECLARED_LOST, 409)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["status"] == "TRACING"
        assert report_now["contents_loss_cents"] is None


class TestOfferSettlement:

    def test_accept_from_claim_review_rejected(self, api):
        """PRD §3.8: "Only the owning passenger — `X-User-ID` equal to the report's
        `passenger_id`, otherwise `ERR_NOT_RESOURCE_OWNER` — and only while the
        report is `SETTLEMENT_OFFERED` (otherwise `ERR_SETTLEMENT_NOT_OFFERED`) may
        respond."

        Design: Corner/state_machines/accept_settlement_from_claim_review_invalid
        """
        ctx = setup_damage_report_claim_review(contents_damage_cents=5000)
        assert ctx["report"]["status"] == "CLAIM_REVIEW"
        resp = api.accept_settlement(ctx["report"]["id"],
                                     make_passenger_headers(ctx["passenger"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_OFFERED, 409)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["status"] == "CLAIM_REVIEW"


class TestRejectReofferCycle:

    def test_reject_returns_to_claim_review_and_clears_offer(self, api):
        """PRD §3.8: "Rejection sends the report back from `SETTLEMENT_OFFERED` to
        `CLAIM_REVIEW` for a revised offer, clearing `settlement_offer_cents`,
        `root_cause`, and `root_cause_station_id`, and resetting
        `amount_payable_cents` to zero."

        Design: Difficulty/non_linear_state_machine/report_settlement_reject_reoffer_cycle
        """
        ctx = setup_damage_report_claim_review(contents_damage_cents=5000)
        get_success_data(api.offer_settlement(
            ctx["report"]["id"],
            {"root_cause": "LOADING_ERROR",
             "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER))
        resp = api.reject_settlement(ctx["report"]["id"],
                                     make_passenger_headers(ctx["passenger"]["id"]))
        rejected = validate_success(resp, 200)
        assert rejected["status"] == "CLAIM_REVIEW"
        assert rejected["amount_payable_cents"] == 0
        assert rejected["settlement_offer_cents"] is None
        assert rejected["root_cause"] is None
        assert rejected["root_cause_station_id"] is None

    def test_reoffer_after_reject_produces_fresh_offer(self, api):
        """PRD §3.8: "Rejection sends the report back from `SETTLEMENT_OFFERED` to
        `CLAIM_REVIEW` for a revised offer"
        PRD §3.8: "a `DAMAGED` report uses its `repair_payout_cents` plus its
        `contents_damage_cents` (treated as zero while null) ... The offer is then
        the lesser of the report's `effective_cap_cents` and that loss basis."

        Design: Difficulty/non_linear_state_machine/report_settlement_reject_reoffer_cycle
        """
        ctx = setup_damage_report_claim_review(contents_damage_cents=5000)
        rpt_id = ctx["report"]["id"]
        offer_payload = {"root_cause": "LOADING_ERROR",
                         "root_cause_station_id": ctx["station"]["id"]}
        get_success_data(api.offer_settlement(rpt_id, offer_payload, ADJUSTER))
        get_success_data(api.reject_settlement(
            rpt_id, make_passenger_headers(ctx["passenger"]["id"])))
        resp = api.offer_settlement(rpt_id, offer_payload, ADJUSTER)
        reoffered = validate_success(resp, 200)
        assert reoffered["status"] == "SETTLEMENT_OFFERED"
        # loss_basis = repair_payout 0 + contents_damage 5000; cap 50000 doesn't bind.
        assert reoffered["settlement_offer_cents"] == 5000
        assert reoffered["amount_payable_cents"] == 5000


class TestPaymentCreation:

    def test_payment_blocked_by_unadjudicated_claim(self, api):
        """PRD §3.8: "Two further guards apply: the report must have no expense
        claims still in `SUBMITTED` (otherwise `ERR_UNADJUDICATED_EXPENSE_CLAIMS`),
        and it must not already have a payment in `ISSUED` status (otherwise
        `ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS`)."

        Design: Difficulty/cross_entity_state_dependency/settlement_payment_blocked_by_unadjudicated_claim
        """
        ctx = setup_declared_lost_report(is_international=True)
        rpt_id = ctx["report"]["id"]
        # A SUBMITTED claim that is never adjudicated (DECLARED_LOST accepts claims).
        claim = create_expense_claim(rpt_id, ctx["passenger"]["id"],
                                     [make_receipt("2026-08-02", 10000, "USD",
                                                   "hotel")])
        get_success_data(api.assess_loss(rpt_id, {"contents_loss_cents": 100000},
                                         ADJUSTER))
        get_success_data(api.offer_settlement(
            rpt_id, {"root_cause": "MISCONNECT",
                     "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER))
        accepted = get_success_data(api.accept_settlement(
            rpt_id, make_passenger_headers(ctx["passenger"]["id"])))

        resp = api.create_settlement_payment(
            rpt_id, {"expected_report_version": accepted["version"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_UNADJUDICATED_EXPENSE_CLAIMS, 409)
        claim_now = get_success_data(api.get_expense_claim(claim["id"], ADJUSTER))
        assert claim_now["status"] == "SUBMITTED"
        report_now = get_success_data(api.get_report(rpt_id, ADJUSTER))
        assert report_now["status"] == "SETTLEMENT_ACCEPTED"

    def test_payment_succeeds_after_claims_adjudicated(self, api):
        """PRD §3.8: "The created payment is `ISSUED` and snapshots the money as it
        stands: `settlement_component_cents` takes the report's current
        `amount_payable_cents` in full, `expense_component_cents` sums the
        `reimbursable_total_cents` of every `APPROVED` expense claim on the report —
        and those claims move to `SETTLEMENT_EARMARKED` — and `amount_cents` is the
        sum of the two components."

        Design: Difficulty/cross_entity_state_dependency/settlement_payment_blocked_by_unadjudicated_claim
        """
        ctx = setup_declared_lost_report(is_international=True)
        rpt_id = ctx["report"]["id"]
        claim = create_expense_claim(rpt_id, ctx["passenger"]["id"],
                                     [make_receipt("2026-08-02", 10000, "USD",
                                                   "hotel")])
        get_success_data(api.adjudicate_expense_claim(claim["id"],
                                                      {"decision": "APPROVE"},
                                                      ADJUSTER))
        get_success_data(api.assess_loss(rpt_id, {"contents_loss_cents": 100000},
                                         ADJUSTER))
        get_success_data(api.offer_settlement(
            rpt_id, {"root_cause": "MISCONNECT",
                     "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER))
        accepted = get_success_data(api.accept_settlement(
            rpt_id, make_passenger_headers(ctx["passenger"]["id"])))

        payment = validate_success(api.create_settlement_payment(
            rpt_id, {"expected_report_version": accepted["version"]}, ADJUSTER), 201)
        assert payment["status"] == "ISSUED"
        assert payment["settlement_component_cents"] == 100000
        assert payment["expense_component_cents"] == 10000
        assert payment["amount_cents"] == 110000
        claim_now = get_success_data(api.get_expense_claim(claim["id"], ADJUSTER))
        assert claim_now["status"] == "SETTLEMENT_EARMARKED"

    def test_payment_before_acceptance_rejected(self, api):
        """PRD §3.8: "Creating the **Settlement Payment** requires the report to be
        `SETTLEMENT_ACCEPTED` — otherwise the request is rejected with
        `ERR_SETTLEMENT_NOT_PAYABLE`"

        Design: Corner/errors/payment_before_acceptance_rejected
        """
        ctx = setup_declared_lost_report(is_international=True)
        rpt_id = ctx["report"]["id"]
        get_success_data(api.assess_loss(rpt_id, {"contents_loss_cents": 100000},
                                         ADJUSTER))
        offered = get_success_data(api.offer_settlement(
            rpt_id, {"root_cause": "MISCONNECT",
                     "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER))
        assert offered["status"] == "SETTLEMENT_OFFERED"
        resp = api.create_settlement_payment(
            rpt_id, {"expected_report_version": offered["version"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_PAYABLE, 409)
        report_now = get_success_data(api.get_report(rpt_id, ADJUSTER))
        assert report_now["status"] == "SETTLEMENT_OFFERED"


class TestOcc:

    def test_stale_report_version_rejected(self, api):
        """PRD §2.9: "If another writer has advanced the report's version since the
        client last read it — by creating or voiding a payment, or by re-offering a
        settlement after a rejection — the client's view of the report totals is
        stale, and the create is rejected with `ERR_STALE_REPORT_VERSION`
        (HTTP 412)"

        Design: Corner/complexity_layers/occ_stale_report_version_rejected
        """
        ctx = setup_settlement_accepted(contents_loss_cents=100000,
                                        is_international=True)
        rpt_id = ctx["report"]["id"]
        stale_version = ctx["report_version"]
        # First creation with the fresh version succeeds and bumps report.version.
        payment = validate_success(api.create_settlement_payment(
            rpt_id, {"expected_report_version": stale_version}, ADJUSTER), 201)
        assert payment["status"] == "ISSUED"
        # Replaying the same (now stale) version is rejected deterministically.
        resp = api.create_settlement_payment(
            rpt_id, {"expected_report_version": stale_version}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_STALE_REPORT_VERSION, 412)

    def test_fresh_version_after_write_accepted_for_state_check(self, api):
        """PRD §2.9: "the request must carry `expected_report_version` matching the
        report's current `version`; a stale expectation is rejected with
        `ERR_STALE_REPORT_VERSION` (HTTP 412)."
        PRD §3.8: "it must not already have a payment in `ISSUED` status (otherwise
        `ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS`)."

        Design: Corner/complexity_layers/occ_stale_report_version_rejected
        """
        ctx = setup_settlement_accepted(contents_loss_cents=100000,
                                        is_international=True)
        rpt_id = ctx["report"]["id"]
        get_success_data(api.create_settlement_payment(
            rpt_id, {"expected_report_version": ctx["report_version"]}, ADJUSTER))
        # A version one behind the live one is stale even though state still matches.
        report_now = get_success_data(api.get_report(rpt_id, ADJUSTER))
        resp = api.create_settlement_payment(
            rpt_id, {"expected_report_version": report_now["version"] - 1}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_STALE_REPORT_VERSION, 412)

    def test_second_payment_with_fresh_version_blocked(self, api):
        """PRD §3.8: "it must not already have a payment in `ISSUED` status
        (otherwise `ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS`)."
        PRD §2.10 item 6 then item 9: the machine-state and OCC checks run before
        uniqueness constraints.

        Design: Corner/validations/second_settlement_payment_blocked
        """
        ctx = setup_settlement_accepted(contents_loss_cents=100000,
                                        is_international=True)
        rpt_id = ctx["report"]["id"]
        payment = validate_success(api.create_settlement_payment(
            rpt_id, {"expected_report_version": ctx["report_version"]}, ADJUSTER), 201)
        report_now = get_success_data(api.get_report(rpt_id, ADJUSTER))
        resp = api.create_settlement_payment(
            rpt_id, {"expected_report_version": report_now["version"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_SETTLEMENT_PAYMENT_EXISTS, 409)
        payment_now = get_success_data(api.get_settlement_payment(payment["id"],
                                                                  ADJUSTER))
        assert payment_now["status"] == "ISSUED"


class TestMoneyConservation:

    def test_money_conserved_across_issue_and_void(self, api):
        """PRD §3.8: "From the moment of the offer onward, a conservation invariant
        holds: the report's `settlement_offer_cents` always equals its
        `amount_payable_cents` plus the sum of `settlement_component_cents` over its
        payments in `ISSUED` or `PAID` status; `VOIDED` payments contribute nothing,
        because voiding restores the payable."

        Design: Difficulty/compensating_invariant/settlement_money_conserved_across_issue_and_void
        """
        ctx = setup_settlement_accepted(contents_loss_cents=100000,
                                        is_international=True)
        rpt_id = ctx["report"]["id"]
        payment = validate_success(api.create_settlement_payment(
            rpt_id, {"expected_report_version": ctx["report_version"]}, ADJUSTER), 201)
        assert payment["settlement_component_cents"] == 100000
        assert payment["expense_component_cents"] == 0
        assert payment["amount_cents"] == 100000

        report_after_issue = get_success_data(api.get_report(rpt_id, ADJUSTER))
        # 100000 offer == 0 payable + 100000 issued.
        assert report_after_issue["amount_payable_cents"] == 0
        assert report_after_issue["settlement_offer_cents"] == \
            report_after_issue["amount_payable_cents"] + payment["settlement_component_cents"]

        voided = validate_success(api.void_payment(payment["id"], ADJUSTER), 200)
        assert voided["status"] == "VOIDED"
        report_after_void = get_success_data(api.get_report(rpt_id, ADJUSTER))
        # Void restores the payable: 100000 offer == 100000 payable + 0 (voided).
        assert report_after_void["amount_payable_cents"] == 100000
        assert report_after_void["status"] == "SETTLEMENT_ACCEPTED"
        assert report_after_void["settlement_offer_cents"] == \
            report_after_void["amount_payable_cents"]

    def test_void_bumps_version_and_allows_superseding_payment(self, api):
        """PRD §3.8: "Voiding instead — likewise only from `ISSUED` — moves the
        payment to `VOIDED` as compensation: the report's `amount_payable_cents` is
        restored by adding back the payment's `settlement_component_cents`, every
        earmarked claim returns to `APPROVED`, and the report's `version` is
        incremented by one. The report remains `SETTLEMENT_ACCEPTED`, and a
        superseding payment may be created against the fresh report version."

        Design: Difficulty/compensating_invariant/settlement_money_conserved_across_issue_and_void
        """
        ctx = setup_settlement_accepted(contents_loss_cents=100000,
                                        is_international=True)
        rpt_id = ctx["report"]["id"]
        payment = validate_success(api.create_settlement_payment(
            rpt_id, {"expected_report_version": ctx["report_version"]}, ADJUSTER), 201)
        version_after_issue = get_success_data(api.get_report(rpt_id, ADJUSTER))["version"]
        get_success_data(api.void_payment(payment["id"], ADJUSTER))
        report_after_void = get_success_data(api.get_report(rpt_id, ADJUSTER))
        assert report_after_void["version"] == version_after_issue + 1

        # A superseding payment may be created against the fresh report version.
        superseding = validate_success(api.create_settlement_payment(
            rpt_id, {"expected_report_version": report_after_void["version"]},
            ADJUSTER), 201)
        assert superseding["status"] == "ISSUED"
        assert superseding["settlement_component_cents"] == 100000


class TestTerminalLockdown:

    def test_closed_report_rejects_offer_settlement(self, api):
        """PRD §3.8: "Offering on a report not in `CLAIM_REVIEW` is rejected with
        `ERR_REPORT_NOT_IN_CLAIM_REVIEW`."
        PRD §2.10: "Any state-machine transition attempted from a state that does
        not permit it — including transitions out of terminal states and repeated
        triggers — is rejected with `ERR_INVALID_STATE_TRANSITION` wherever §3 does
        not assign a more specific state error."

        Design: Corner/state_machines/closed_report_terminal_lockdown
        """
        ctx = setup_closed_report(contents_loss_cents=100000, is_international=True)
        assert ctx["report"]["status"] == "CLOSED"
        resp = api.offer_settlement(
            ctx["report"]["id"],
            {"root_cause": "MISCONNECT",
             "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_IN_CLAIM_REVIEW, 409)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["status"] == "CLOSED"
