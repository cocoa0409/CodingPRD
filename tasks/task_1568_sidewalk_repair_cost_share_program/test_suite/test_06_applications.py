"""Cost-share application lifecycle: review/payment dimensions, state gates,
and cross-entity gating on cycle and notice."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application_payload,
    make_cycle,
    make_owner_headers,
    make_parcel,
    set_clock,
    setup_application,
    setup_approved_application,
    setup_compliant_notice,
    setup_issued_notice,
    setup_obligated_application,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestReviewAndPaymentDimensions:
    def _setup(self):
        return setup_application(
            parcel_number="P-700", segment_code="S-700-1",
            owner_name="Hank Holly", street_address="8 Holly St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)

    def test_review_dimension_moves_independently(self, api):
        """PRD §3.5: "At creation the server copies `owner_id` from the parcel,
        sets `review_status` to `SUBMITTED` and `payment_status` to `UNFUNDED`"
        PRD §3.5: "Approval moves the application to `APPROVED`"

        Design: Difficulty/non_linear_state_machine/application_review_payment_dims_independent
        """
        bundle = self._setup()
        app = bundle["application"]
        assert app["review_status"] == "SUBMITTED"
        assert app["payment_status"] == "UNFUNDED"

        app = validate_success(api.decide_application(
            app["id"], {"outcome": "APPROVE"}, COORD))
        assert app["review_status"] == "APPROVED"
        assert app["payment_status"] == "UNFUNDED", \
            "the review dimension moved while payment stayed UNFUNDED"

        app = validate_success(api.obligate_application(app["id"], FINANCE))
        assert app["review_status"] == "OBLIGATED"

        app = validate_success(api.withdraw_application(
            app["id"], make_owner_headers(bundle["owner"]["id"])))
        assert app["review_status"] == "WITHDRAWN"

    def test_payment_dimension_moves_only_at_obligate(self, api):
        """PRD §3.6: "A successful obligation moves `payment_status` from
        `UNFUNDED` to `RESERVED`"
        PRD §3.5: "withdrawal from `OBLIGATED` additionally flips
        `payment_status` from `RESERVED` to `RELEASED` and subtracts the
        `provisional_award_cents` from the cycle's `committed_cents`"

        Design: Difficulty/non_linear_state_machine/application_review_payment_dims_independent
        """
        bundle = self._setup()
        app_id = bundle["application"]["id"]
        validate_success(api.decide_application(
            app_id, {"outcome": "APPROVE"}, COORD))
        app = validate_success(api.obligate_application(app_id, FINANCE))
        assert app["payment_status"] == "RESERVED"

        app = validate_success(api.withdraw_application(
            app_id, make_owner_headers(bundle["owner"]["id"])))
        assert app["payment_status"] == "RELEASED", \
            "compensation on the payment dimension only"

        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 0


class TestCrossEntityGates:
    def _setup_approved(self):
        return setup_approved_application(
            parcel_number="P-1700", segment_code="S-1700-1",
            owner_name="Ted Teak", street_address="20 Teak St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)

    def test_obligate_blocked_when_cycle_locked(self, api):
        """PRD §3.6: "the cycle must still be `OPEN` (else
        `ERR_CYCLE_NOT_OPEN`)"

        Design: Difficulty/cross_entity_state_dependency/obligate_requires_cycle_open
        """
        bundle = self._setup_approved()
        cycle = validate_success(
            api.lock_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["status"] == "LOCKED"

        resp = api.obligate_application(bundle["application"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    def test_obligate_allowed_while_cycle_open_control(self, api):
        """PRD §3.6: "Approval alone spends nothing; a `FinanceOfficer` must
        obligate the award — `APPROVED → OBLIGATED` — which reserves the
        provisional amount against the cycle."

        Design: Difficulty/cross_entity_state_dependency/obligate_requires_cycle_open
        """
        bundle = self._setup_approved()
        app = validate_success(
            api.obligate_application(bundle["application"]["id"], FINANCE))
        assert app["review_status"] == "OBLIGATED", \
            "the same call succeeds while the cycle is OPEN"
        assert app["payment_status"] == "RESERVED"

    def test_reimburse_blocked_until_notice_compliant(self, api):
        """PRD §3.6: "The application must be `OBLIGATED`, and the source
        notice must have reached `COMPLIANT` (else `ERR_NOTICE_NOT_COMPLIANT`)."

        Design: Difficulty/cross_entity_state_dependency/reimburse_requires_notice_compliant
        """
        bundle = setup_obligated_application(
            parcel_number="P-1900", segment_code="S-1900-1",
            owner_name="Vera Vine", street_address="22 Vine St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        resp = api.reimburse_application(
            bundle["application"]["id"], {"final_repair_cost_cents": 100000},
            FINANCE)
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_COMPLIANT)

    def test_reimburse_succeeds_after_compliance(self, api):
        """PRD §3.6: "the repair part is `final_repair_cost_cents` multiplied
        by `share_pct` and divided by 100, rounded half-up"
        PRD §3.6: "On success the reservation unwinds — `committed_cents` drops
        by the provisional award while `disbursed_cents` grows by the final
        award — `payment_status` moves from `RESERVED` to `DISBURSED`"

        Design: Difficulty/cross_entity_state_dependency/reimburse_requires_notice_compliant
        """
        bundle = setup_obligated_application(
            parcel_number="P-1900", segment_code="S-1900-1",
            owner_name="Vera Vine", street_address="22 Vine St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        setup_compliant_notice(bundle)

        app = validate_success(api.reimburse_application(
            bundle["application"]["id"], {"final_repair_cost_cents": 100000},
            FINANCE))
        assert app["review_status"] == "REIMBURSED"
        # share 50 (LOCAL + NONE): round_half_up(100000 * 50 / 100) = 50000
        assert app["final_award_cents"] == 50000


class TestApplicationStateGates:
    def test_resubmit_on_submitted_rejected(self, api):
        """PRD §3.5: "Withdrawal and resubmission from a state the application
        does not occupy, or by anyone but the owning owner, fail with
        `ERR_INVALID_APPLICATION_STATE` and `ERR_OWNERSHIP_MISMATCH`
        respectively."

        Design: Corner/state_machines/resubmit_on_submitted_application_rejected
        """
        bundle = setup_application(
            parcel_number="P-S3", segment_code="S-S3-1", owner_name="Ben Beech",
            street_address="53 Beech St", estimated_qty_sqft=50)
        resp = api.resubmit_application(
            bundle["application"]["id"],
            make_owner_headers(bundle["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

    def test_denied_application_terminal(self, api):
        """PRD §3.5: "any decision attempted on an application not in
        `SUBMITTED` fails with `ERR_INVALID_APPLICATION_STATE`"
        PRD §3.5: "Denial terminates the application as `DENIED`"

        Design: Corner/state_machines/denied_application_terminal_lockdown
        """
        bundle = setup_application(
            parcel_number="P-S9", segment_code="S-S9-1",
            owner_name="Hal Hawthorn", street_address="59 Haw St",
            estimated_qty_sqft=50)
        app = validate_success(api.decide_application(
            bundle["application"]["id"], {"outcome": "DENY"}, COORD))
        assert app["review_status"] == "DENIED"

        resp = api.decide_application(app["id"], {"outcome": "APPROVE"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

        resp = api.withdraw_application(
            app["id"], make_owner_headers(bundle["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

    def test_returned_resubmit_revision_cycle(self, api):
        """PRD §3.5: "return moves it to `RETURNED`, from which the owning
        owner may resubmit it to `SUBMITTED` — a revision cycle that may repeat
        without bound."
        PRD §3.5: "Approval moves the application to `APPROVED` and stamps
        `approved_at` from the logical clock, with `approval_expires_at`
        computed as the approval instant plus 60 days"

        Design: Corner/state_machines/returned_application_resubmit_cycle
        """
        bundle = setup_application(
            parcel_number="P-S11", segment_code="S-S11-1",
            owner_name="Joy Jojoba", street_address="61 Jojoba St",
            estimated_qty_sqft=50)
        app_id = bundle["application"]["id"]

        app = validate_success(api.decide_application(
            app_id, {"outcome": "RETURN", "reviewer_note": "photo missing"},
            COORD))
        assert app["review_status"] == "RETURNED"

        app = validate_success(api.resubmit_application(
            app_id, make_owner_headers(bundle["owner"]["id"])))
        assert app["review_status"] == "SUBMITTED"

        app = validate_success(api.decide_application(
            app_id, {"outcome": "APPROVE"}, COORD))
        assert app["review_status"] == "APPROVED"
        assert app["approved_at"] == "2026-08-01T00:00:00Z"
        assert app["approval_expires_at"] == "2026-09-30T00:00:00Z"


class TestApplicationComposition:
    def test_parcel_notice_mismatch_rejected(self, api):
        """PRD §3.5: "the application's `parcel_id` must equal the notice's
        parcel (else `ERR_PARCEL_NOTICE_MISMATCH`)"

        Design: Corner/errors/application_parcel_notice_mismatch
        """
        bundle = setup_issued_notice(parcel_number="P-R8A",
                                     segment_code="S-R8A-1",
                                     owner_name="Nia Neem",
                                     street_address="92 Neem St")
        parcel_b = make_parcel(bundle["owner"]["id"], "P-R8B", "93 Neem St",
                               "LOCAL")
        cycle = make_cycle()
        resp = api.create_application(
            create_application_payload(bundle["notice"]["id"], parcel_b["id"],
                                       cycle["id"], 50),
            make_owner_headers(bundle["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PARCEL_NOTICE_MISMATCH)

    def test_second_active_application_rejected(self, api):
        """PRD §3.5: "the notice may carry at most one application in a
        non-terminal review status at a time (else
        `ERR_APPLICATION_ALREADY_ACTIVE`)"

        Design: Corner/errors/second_active_application_on_notice_rejected
        """
        bundle = setup_application(
            parcel_number="P-R9", segment_code="S-R9-1", owner_name="Pia Pine",
            street_address="97 Pine St", estimated_qty_sqft=50)
        resp = api.create_application(
            create_application_payload(bundle["notice"]["id"],
                                       bundle["parcel"]["id"],
                                       bundle["cycle"]["id"], 60),
            make_owner_headers(bundle["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_ALREADY_ACTIVE)


class TestApprovalExpiry:
    def test_obligate_after_expiry_rejected(self, api):
        """PRD §3.6: "the logical clock must be no later than
        `approval_expires_at`, with an obligation exactly at expiry still timely
        (else `ERR_APPLICATION_EXPIRED`)"

        Design: Corner/errors/obligate_after_approval_expiry_rejected
        """
        bundle = setup_approved_application(
            parcel_number="P-T4", segment_code="S-T4-1", owner_name="Tara Teff",
            street_address="101 Teff St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=100, estimated_qty_sqft=100)
        assert bundle["application"]["approval_expires_at"] == \
            "2026-09-30T00:00:00Z"
        set_clock("2026-10-01T00:00:00Z")
        resp = api.obligate_application(bundle["application"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_EXPIRED)

    def test_obligate_at_exact_expiry_boundary(self, api):
        """PRD §3.6: "the logical clock must be no later than
        `approval_expires_at`, with an obligation exactly at expiry still timely
        (else `ERR_APPLICATION_EXPIRED`)"

        Design: Corner/cross_cutting_complexity_layers/obligate_at_exact_expiry_boundary
        """
        bundle = setup_approved_application(
            parcel_number="P-X5", segment_code="S-X5-1", owner_name="Mimosa Mo",
            street_address="120 Mimosa St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=100, estimated_qty_sqft=100)
        assert bundle["application"]["approval_expires_at"] == \
            "2026-09-30T00:00:00Z"
        set_clock("2026-09-30T00:00:00Z")

        app = validate_success(
            api.obligate_application(bundle["application"]["id"], FINANCE))
        assert app["review_status"] == "OBLIGATED"
        assert app["payment_status"] == "RESERVED"

        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 60000
