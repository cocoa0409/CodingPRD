"""Award adjustments: segregation of duties, fiscal floors, terminal states."""
from test_helpers import (
    ApiErrorId,
    COORDINATOR_ALT_USER_ID,
    FAO_APPROVER_USER_ID,
    FAO_USER_ID,
    TEST_USERS,
    get_award,
    make_coordinator_headers,
    make_fao_headers,
    setup_accepted_award,
    setup_fully_disbursed_award,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestAdjustmentApply:
    def test_withdrawal_clawback_applies_to_over_disbursed(self, api):
        """PRD §3.8: "for `OVER_AWARD` and `WITHDRAWAL` reasons, dipping below
        the net confirmed amount is allowed and flips the award to
        `OVER_DISBURSED` with the recovery expectation of §3.7."
        PRD §3.8: "An applied adjustment records the approver as
        `approved_by_user_id`, adds `delta_cents` to the award's
        `amount_cents`, recomputes the fund's `reserved_cents` and the
        student's totals and `excess_cents`, flips the award to
        `OVER_DISBURSED` when the net confirmed amount exceeds the new
        amount".
        PRD §3.8: "the creator's `X-User-ID` is recorded as
        `created_by_user_id`".

        Design: Corner/state_machines/adjustment_applied_clawback_to_over_disbursed
        """
        ctx = setup_fully_disbursed_award(
            amount_cents=600000,
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 600000},
        )
        award_id = ctx["award"]["id"]

        created = validate_success(
            api.create_adjustment(
                {
                    "award_id": award_id,
                    "reason": "WITHDRAWAL",
                    "delta_cents": -100000,
                },
                make_coordinator_headers(COORDINATOR_ALT_USER_ID),
            ),
            expected_status=201,
        )
        assert created["created_by_user_id"] == COORDINATOR_ALT_USER_ID
        assert created["auto_generated"] is False, "manual drafts are not auto"

        submitted = validate_success(
            api.submit_adjustment(
                created["id"], make_coordinator_headers(COORDINATOR_ALT_USER_ID)
            )
        )
        assert submitted["status"] == "PENDING_APPROVAL"

        applied = validate_success(
            api.approve_adjustment(
                created["id"], make_fao_headers(FAO_APPROVER_USER_ID)
            )
        )
        assert applied["status"] == "APPLIED"
        assert applied["approved_by_user_id"] == FAO_APPROVER_USER_ID

        award = get_award(award_id)
        assert award["amount_cents"] == 500000
        assert award["funding_status"] == "OVER_DISBURSED", (
            "net confirmed 600000 exceeds the reduced amount 500000"
        )


class TestAdjustmentSegregationPriority:
    def _pending_adjustment_by(self, api, creator_id):
        """FULLY_DISBURSED 600000 award; DATA_ERROR -500000 drafted and
        submitted by the given FinancialAidOfficer id."""
        ctx = setup_fully_disbursed_award(
            amount_cents=600000,
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 600000},
        )
        adjustment = validate_success(
            api.create_adjustment(
                {
                    "award_id": ctx["award"]["id"],
                    "reason": "DATA_ERROR",
                    "delta_cents": -500000,
                },
                make_fao_headers(creator_id),
            ),
            expected_status=201,
        )
        validate_success(
            api.submit_adjustment(adjustment["id"], make_fao_headers(creator_id))
        )
        return ctx, adjustment

    def test_self_approve_rejected_with_segregation_error(self, api):
        """PRD §2.10: "An award adjustment may be drafted by a
        `ScholarshipCoordinator` or a `FinancialAidOfficer`, but only a
        `FinancialAidOfficer` may approve or reject it, and the approver's
        `X-User-ID` must differ from the recorded `created_by_user_id`; a
        same-person approval or rejection is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.8: "the server evaluates its checks in a fixed priority order,
        and a failure at any step surfaces that step's error and masks every
        later check" — segregation (step 9: "Segregation and declared
        conflicts") precedes the fiscal floors (step 12: "Fiscal limits").

        Design: Difficulty/priority_pair_validation_conflict/self_approve_oversized_adjustment_safety_beats_fiscal
        """
        _, adjustment = self._pending_adjustment_by(api, FAO_USER_ID)
        # Same officer approves own draft; the clawback would ALSO breach the
        # DUPLICATE/DATA_ERROR fiscal floor (500000 < net confirmed 600000) —
        # the safety error surfaces, masking the fiscal one.
        resp = api.approve_adjustment(
            adjustment["id"], make_fao_headers(FAO_USER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_masked_fiscal_breach_writes_nothing(self, api):
        """PRD §2.8: "a failure at any step surfaces that step's error and
        masks every later check".
        PRD §3.8: "An applied adjustment records the approver as
        `approved_by_user_id`, adds `delta_cents` to the award's
        `amount_cents`, recomputes the fund's `reserved_cents` and the
        student's totals and `excess_cents`, flips the award to
        `OVER_DISBURSED` when the net confirmed amount exceeds the new
        amount, and runs the stacking recompute of §3.6" — a refused approval
        applies none of this.

        Design: Difficulty/priority_pair_validation_conflict/self_approve_oversized_adjustment_safety_beats_fiscal
        """
        ctx, adjustment = self._pending_adjustment_by(api, FAO_USER_ID)
        validate_error(
            api.approve_adjustment(adjustment["id"], make_fao_headers(FAO_USER_ID)),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        current = validate_success(api.get_adjustment(adjustment["id"], COORD))
        assert current["status"] == "PENDING_APPROVAL"
        assert current["approved_by_user_id"] is None
        assert get_award(ctx["award"]["id"])["amount_cents"] == 600000


class TestAdjustmentTerminalStates:
    def test_reject_then_approve_rejected(self, api):
        """PRD §3.8: "Rejection, also officer-only and also segregated from
        the creator, moves `PENDING_APPROVAL` → `REJECTED`. `APPLIED` and
        `REJECTED` are terminal".
        PRD §2.8: "**Own-state** — the target resource's own state permits
        the requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/adjustment_reject_terminal_lockdown
        """
        ctx = setup_accepted_award(amount_cents=500000)
        award_id = ctx["award"]["id"]
        adjustment = validate_success(
            api.create_adjustment(
                {
                    "award_id": award_id,
                    "reason": "DUPLICATE",
                    "delta_cents": -100000,
                },
                make_coordinator_headers(COORDINATOR_ALT_USER_ID),
            ),
            expected_status=201,
        )
        validate_success(
            api.submit_adjustment(
                adjustment["id"], make_coordinator_headers(COORDINATOR_ALT_USER_ID)
            )
        )

        rejected = validate_success(
            api.reject_adjustment(
                adjustment["id"], make_fao_headers(FAO_APPROVER_USER_ID)
            )
        )
        assert rejected["status"] == "REJECTED"

        resp = api.approve_adjustment(
            adjustment["id"], make_fao_headers(FAO_APPROVER_USER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_award(award_id)["amount_cents"] == 500000, (
            "award amount untouched by the rejected adjustment"
        )
