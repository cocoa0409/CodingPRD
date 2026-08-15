"""Customs filings (ISF/AMS), penalties, and the bill-of-lading lifecycle."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    accept_both_filings,
    create_active_bond,
    create_confirmed_booking,
    create_draft_bl,
    create_filing,
    create_issued_freight_invoice,
    issue_bl,
    setup_documented_fcl_scenario,
    setup_fcl_lane,
    setup_lcl_lane,
    submit_and_answer_filing,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CO_1, DOC_1, DOC_2, FC, OPS
from test_helpers.test_users import make_shipper_headers


def _parse(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (Z or offset form)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestFilingDeadlineSnapshot:
    def test_filing_deadline_snapshot_constants(self, api):
        """PRD §3.5: "On creation the voyage enters `SCHEDULED`, and the
        system derives two statutory deadlines from the `etd`: the
        `isf_deadline` is exactly 24 hours before `etd` (ISF 10+2 must be
        filed 24 hours before loading), and the `ams_deadline` is exactly 48
        hours before `etd`."
        PRD §3.10: "On creation the filing enters `PENDING`, the
        `filed_by_user_id` is stamped from `X-User-ID`, and the `deadline_at`
        is **frozen** as a snapshot: for an `ISF` filing it equals the
        voyage's `isf_deadline` (24 hours before `etd`); for an `AMS` filing
        it equals the voyage's `ams_deadline` (48 hours before `etd`)."

        Design: Corner/calculations/filing_deadline_snapshot_constants
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        voyage = validate_success(api.get_voyage(ctx["voyage"]["id"], OPS), 200)
        etd = _parse(voyage["etd"])
        assert _parse(voyage["isf_deadline"]) == etd - timedelta(hours=24)
        assert _parse(voyage["ams_deadline"]) == etd - timedelta(hours=48)

        isf = create_filing(booking["id"], "ISF")
        ams = create_filing(booking["id"], "AMS")
        assert _parse(isf["deadline_at"]) == _parse(voyage["isf_deadline"])
        assert _parse(ams["deadline_at"]) == _parse(voyage["ams_deadline"])

        # Default logical clock (2026-08-01) is well before both deadlines.
        submitted = validate_success(
            api.submit_compliance_filing(isf["id"], CO_1), 200)
        assert submitted["is_late"] is False
        assert submitted["penalty_status"] == "NONE"


class TestLatenessBoundary:
    def test_filing_submit_exactly_at_deadline_is_on_time(self, api):
        """PRD §3.10: "The lateness rule is strict: a submission is late only
        when `submitted_at` is strictly greater than `deadline_at`; a
        submission exactly at the deadline is on time."

        Design: Corner/validations/filing_submit_exactly_at_deadline_is_on_time
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        isf = create_filing(booking["id"], "ISF")

        validate_success(api.set_clock("2026-08-31T00:00:00Z", OPS), 200)
        submitted = validate_success(
            api.submit_compliance_filing(isf["id"], CO_1), 200)
        assert submitted["is_late"] is False, "submission AT the deadline is on time"
        assert submitted["penalty_amount_cents"] == 0
        assert submitted["penalty_status"] == "NONE"

    def test_filing_reject_resubmit_cycle_re_evaluates_lateness(self, api):
        """PRD §3.10: "Submission — a `ComplianceOfficer` action — transitions
        a `PENDING` or `REJECTED` filing to `SUBMITTED`."
        PRD §3.10: "The `submitted_at` is stamped with the logical clock (and
        refreshed on any resubmission from `REJECTED`), and `is_late` is
        recomputed against the frozen `deadline_at`."
        PRD §3.10: "When a submission is late and the filing's
        `penalty_status` is still `NONE`, the penalty accrues:
        `penalty_amount_cents` is set to 500000 cents for an `ISF` filing and
        300000 cents for an `AMS` filing, and `penalty_status` transitions
        from `NONE` to `ACCRUED`."

        Design: Corner/state_machines/filing_reject_resubmit_cycle_re_evaluates_lateness
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        isf = create_filing(booking["id"], "ISF")
        assert _parse(isf["deadline_at"]) == datetime.fromisoformat(
            "2026-08-31T00:00:00+00:00"), "deadline snapshot frozen at creation"

        submit_and_answer_filing(isf["id"], "REJECTED")

        validate_success(api.set_clock("2026-08-31T00:00:01Z", OPS), 200)
        resubmitted = validate_success(
            api.submit_compliance_filing(isf["id"], CO_1), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["is_late"] is True, "1s past the frozen deadline"
        assert resubmitted["penalty_status"] == "ACCRUED"
        assert resubmitted["penalty_amount_cents"] == 500000


class TestFilingStateAndUniqueness:
    def test_double_filing_submit_rejected_idempotency(self, api):
        """PRD §3.10: "Submission — a `ComplianceOfficer` action — transitions
        a `PENDING` or `REJECTED` filing to `SUBMITTED`."
        PRD §3.10: "Either transition requires the filing to currently be
        `SUBMITTED` (otherwise `ERR_FILING_INVALID_STATE`)."

        Design: Corner/state_machines/double_filing_submit_rejected_idempotency
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        isf = create_filing(booking["id"], "ISF")
        validate_success(api.submit_compliance_filing(isf["id"], CO_1), 200)

        res = api.submit_compliance_filing(isf["id"], CO_1)
        validate_error(res, ApiErrorId.ERR_FILING_INVALID_STATE,
                       expected_status=409)

        after = validate_success(api.get_compliance_filing(isf["id"], CO_1), 200)
        assert after["status"] == "SUBMITTED"
        assert after["penalty_status"] == "NONE"
        assert after["is_late"] is False

    def test_duplicate_filing_type_per_booking_rejected(self, api):
        """PRD §3.10: "At most one filing may exist per (`booking_id`,
        `filing_type`); a duplicate is rejected with `ERR_FILING_EXISTS`."

        Design: Corner/validations/duplicate_filing_type_per_booking_rejected
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        create_filing(booking["id"], "ISF")

        res = api.create_compliance_filing(
            {"booking_id": booking["id"], "filing_type": "ISF"}, CO_1)
        validate_error(res, ApiErrorId.ERR_FILING_EXISTS, expected_status=409)

        ams = validate_success(
            api.create_compliance_filing(
                {"booking_id": booking["id"], "filing_type": "AMS"}, CO_1),
            201)
        assert ams["status"] == "PENDING", "the other filing type is unaffected"


class TestBondCoverageConservation:
    def test_late_isf_accrues_penalty_and_debits_bond(self, api):
        """PRD §3.10: "When a submission is late and the filing's
        `penalty_status` is still `NONE`, the penalty accrues:
        `penalty_amount_cents` is set to 500000 cents for an `ISF` filing and
        300000 cents for an `AMS` filing, and `penalty_status` transitions
        from `NONE` to `ACCRUED`."
        PRD §3.4: "The bond's `available_coverage_cents` is the
        `coverage_amount_cents` minus the sum of `penalty_amount_cents` over
        every compliance filing whose `penalty_status` is `ACCRUED`."

        Design: Difficulty/compensating_invariant/bond_coverage_accrue_resolve_conservation
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        bond = create_active_bond()
        isf = create_filing(booking["id"], "ISF")

        validate_success(api.set_clock("2026-08-31T00:00:01Z", OPS), 200)
        submitted = validate_success(
            api.submit_compliance_filing(isf["id"], CO_1), 200)
        assert submitted["is_late"] is True
        assert submitted["penalty_status"] == "ACCRUED"
        assert submitted["penalty_amount_cents"] == 500000, (
            "ISF schedule, not the 300000 AMS figure"
        )

        bond_after = validate_success(api.get_surety_bond(bond["id"], CO_1), 200)
        assert bond_after["available_coverage_cents"] == 7000000

    def test_resolve_penalty_waived_restores_bond_coverage(self, api):
        """PRD §3.10: "An accrued penalty may later be resolved by a
        `ComplianceOfficer` with a `resolution` of `PAID` or `WAIVED`; the
        resolution transitions `penalty_status` from `ACCRUED` to `PAID` or
        `WAIVED`, removing the accrual from the bond's
        `available_coverage_cents` recomputation."

        Design: Difficulty/compensating_invariant/bond_coverage_accrue_resolve_conservation
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        bond = create_active_bond()
        isf = create_filing(booking["id"], "ISF")

        validate_success(api.set_clock("2026-08-31T00:00:01Z", OPS), 200)
        validate_success(api.submit_compliance_filing(isf["id"], CO_1), 200)
        debited = validate_success(api.get_surety_bond(bond["id"], CO_1), 200)
        assert debited["available_coverage_cents"] == 7000000

        resolved = validate_success(
            api.resolve_filing_penalty(isf["id"], "WAIVED", CO_1), 200)
        assert resolved["penalty_status"] == "WAIVED"
        restored = validate_success(api.get_surety_bond(bond["id"], CO_1), 200)
        assert restored["available_coverage_cents"] == 7500000, (
            "resolving the accrual restores coverage exactly"
        )


class TestDocumentationClearedGate:
    def test_doc_clearance_compound_gate_requires_both_filings_and_bl(self, api):
        """PRD §3.11: "On success `issued_by_user_id` is stamped from
        `X-User-ID`, and the booking's DOCUMENTATION_CLEARED gate is
        re-evaluated: a booking in `CONFIRMED` transitions automatically to
        `DOCUMENTATION_CLEARED` once it holds one `ACCEPTED` ISF filing, one
        `ACCEPTED` AMS filing, and a bill of lading in `ISSUED` or
        `SURRENDERED`."

        Design: Corner/state_machines/doc_clearance_compound_gate_requires_both_filings_and_bl
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        create_active_bond()
        accept_both_filings(booking["id"])

        mid = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert mid["status"] == "CONFIRMED", (
            "both filings ACCEPTED but no ISSUED B/L yet — gate not satisfied"
        )

        bl = issue_bl(create_draft_bl(booking["id"])["id"])
        assert bl["status"] == "ISSUED"
        end = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert end["status"] == "DOCUMENTATION_CLEARED", (
            "the B/L issue event itself completes the compound gate"
        )


class TestBillOfLadingStateRules:
    def test_bl_issue_from_issued_returns_invalid_state(self, api):
        """PRD §3.11: "Issuance — a `DocumentationOfficer` action —
        transitions a `DRAFT` bill to `ISSUED`."

        Design: Corner/state_machines/bl_issue_from_issued_returns_invalid_state
        """
        ctx = setup_documented_fcl_scenario()
        bl = ctx["bl"]
        assert bl["status"] == "ISSUED"

        res = api.issue_bill_of_lading(bl["id"], DOC_1)
        validate_error(res, ApiErrorId.ERR_BL_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_bill_of_lading(bl["id"], DOC_1), 200)
        assert after["status"] == "ISSUED"

    def test_released_bl_terminal_lockdown_void_rejected(self, api):
        """PRD §3.11: "Voiding is permitted manually only from `DRAFT` or
        `AMENDMENT_PENDING`; a manual void of an `ISSUED` or `SURRENDERED`
        bill is rejected with `ERR_BL_INVALID_STATE`. The system cascades void
        bills in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED` to
        `VOIDED` when the parent booking is cancelled or rolled or when the
        voyage blanks or departs with the booking rolled. `RELEASED` and
        `VOIDED` are terminal."

        Design: Corner/state_machines/released_bl_terminal_lockdown_void_rejected
        """
        ctx = setup_documented_fcl_scenario()
        bl = ctx["bl"]
        released = validate_success(api.release_bill_of_lading(bl["id"], DOC_2), 200)
        assert released["status"] == "RELEASED"

        res = api.void_bill_of_lading(bl["id"], DOC_1)
        validate_error(res, ApiErrorId.ERR_BL_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_bill_of_lading(bl["id"], DOC_1), 200)
        assert after["status"] == "RELEASED"

    def test_second_active_bl_per_booking_rejected(self, api):
        """PRD §3.11: "The booking must be in `CONFIRMED`,
        `DOCUMENTATION_CLEARED`, `LOADED`, `DEPARTED`, or `ARRIVED`
        (otherwise `ERR_BOOKING_INVALID_STATE`), and there may be at most one
        non-terminal bill of lading per booking — a booking already holding a
        bill in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED`
        rejects a new draft with `ERR_ACTIVE_BL_EXISTS`."

        Design: Corner/validations/second_active_bl_per_booking_rejected
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx, terms="COLLECT")
        bl1 = create_draft_bl(booking["id"])

        res = api.create_bill_of_lading(
            {"booking_id": booking["id"], "bl_type": "MASTER",
             "release_mode": "ORIGINAL"}, DOC_1)
        validate_error(res, ApiErrorId.ERR_ACTIVE_BL_EXISTS, expected_status=409)

        validate_success(api.void_bill_of_lading(bl1["id"], DOC_1), 200)
        bl2 = validate_success(
            api.create_bill_of_lading(
                {"booking_id": booking["id"], "bl_type": "MASTER",
                 "release_mode": "ORIGINAL"}, DOC_1),
            201)
        assert bl2["status"] == "DRAFT"


class TestBillOfLadingAmendmentCycle:
    def test_request_amendment_enters_amendment_pending(self, api):
        """PRD §3.11: "Requesting an amendment — a `DocumentationOfficer`
        action — requires the bill to be `ISSUED` (otherwise
        `ERR_BL_INVALID_STATE`) and `amendment_count` to be below the cap of 3
        (otherwise `ERR_AMENDMENT_LIMIT_EXCEEDED`); the transition is `ISSUED`
        to `AMENDMENT_PENDING` with `amendment_count` incremented by one."

        Design: Difficulty/non_linear_state_machine/bill_of_lading_amendment_cycle_with_booking_revert
        """
        ctx = setup_documented_fcl_scenario()
        bl = ctx["bl"]

        amended = validate_success(
            api.request_bl_amendment(bl["id"], DOC_1), 200)
        assert amended["status"] == "AMENDMENT_PENDING"
        assert amended["amendment_count"] == 1

    def test_reissue_reverts_booking_and_second_issue_restores(self, api):
        """PRD §3.11: "Reissue returns an `AMENDMENT_PENDING` bill to `DRAFT`;
        as a side effect, a booking in `DOCUMENTATION_CLEARED` reverts to
        `CONFIRMED` because the documentation gate is no longer satisfied
        while no bill is in `ISSUED`."
        PRD §3.11: "a booking in `CONFIRMED` transitions automatically to
        `DOCUMENTATION_CLEARED` once it holds one `ACCEPTED` ISF filing, one
        `ACCEPTED` AMS filing, and a bill of lading in `ISSUED` or
        `SURRENDERED`."

        Design: Difficulty/non_linear_state_machine/bill_of_lading_amendment_cycle_with_booking_revert
        """
        ctx = setup_documented_fcl_scenario()
        bl = ctx["bl"]
        booking_id = ctx["booking"]["id"]
        assert validate_success(api.get_booking(booking_id, OPS), 200)[
            "status"] == "DOCUMENTATION_CLEARED"

        validate_success(api.request_bl_amendment(bl["id"], DOC_1), 200)
        reissued = validate_success(api.reissue_bill_of_lading(bl["id"], DOC_1), 200)
        assert reissued["status"] == "DRAFT"
        mid = validate_success(api.get_booking(booking_id, OPS), 200)
        assert mid["status"] == "CONFIRMED", "doc clearance reverted on reissue"

        reissued_again = validate_success(
            api.issue_bill_of_lading(bl["id"], DOC_1), 200)
        assert reissued_again["status"] == "ISSUED"
        end = validate_success(api.get_booking(booking_id, OPS), 200)
        assert end["status"] == "DOCUMENTATION_CLEARED", "gate re-satisfied"

    def test_bl_amendment_cap_fourth_request_rejected(self, api):
        """PRD §3.11: "Requesting an amendment — a `DocumentationOfficer`
        action — requires the bill to be `ISSUED` (otherwise
        `ERR_BL_INVALID_STATE`) and `amendment_count` to be below the cap of 3
        (otherwise `ERR_AMENDMENT_LIMIT_EXCEEDED`); the transition is `ISSUED`
        to `AMENDMENT_PENDING` with `amendment_count` incremented by one."

        Design: Corner/validations/bl_amendment_cap_fourth_request_rejected
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        create_active_bond()
        bl = issue_bl(create_draft_bl(booking["id"])["id"])

        for expected_count in (1, 2, 3):
            amended = validate_success(
                api.request_bl_amendment(bl["id"], DOC_1), 200)
            assert amended["amendment_count"] == expected_count
            validate_success(api.reissue_bill_of_lading(bl["id"], DOC_1), 200)
            validate_success(api.issue_bill_of_lading(bl["id"], DOC_1), 200)

        res = api.request_bl_amendment(bl["id"], DOC_1)
        validate_error(res, ApiErrorId.ERR_AMENDMENT_LIMIT_EXCEEDED,
                       expected_status=422)
        after = validate_success(api.get_bill_of_lading(bl["id"], DOC_1), 200)
        assert after["status"] == "ISSUED"
        assert after["amendment_count"] == 3


class TestBillOfLadingReleaseGates:
    def test_sod_bl_issuer_cannot_release(self, api):
        """PRD §3.11: "Either path enforces three preconditions: the
        releaser's `X-User-ID` must differ from `issued_by_user_id` (otherwise
        `ERR_SEGREGATION_OF_DUTIES`); the booking's ISF and AMS filings must
        both be `ACCEPTED` (otherwise `ERR_FILINGS_NOT_CLEARED`); and, when
        the booking's `terms` is `PREPAID`, every FREIGHT invoice of the
        booking must be `PAID` (otherwise `ERR_OUTSTANDING_BALANCE`)."
        PRD §2.8: "(4) segregation-of-duties checks" runs before "(7)
        regulatory gates — bill of lading release requires both filings
        `ACCEPTED`, bill of lading issue requires a qualifying bond".

        Design: Corner/validations/sod_bl_issuer_cannot_release
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        create_active_bond()
        bl = issue_bl(create_draft_bl(booking["id"])["id"])
        # No filings exist, yet the SoD band fires first for the issuer.
        res = api.release_bill_of_lading(bl["id"], DOC_1)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

    def test_release_blocked_by_unaccepted_ams_filing(self, api):
        """PRD §3.11: "Either path enforces three preconditions: the
        releaser's `X-User-ID` must differ from `issued_by_user_id` (otherwise
        `ERR_SEGREGATION_OF_DUTIES`); the booking's ISF and AMS filings must
        both be `ACCEPTED` (otherwise `ERR_FILINGS_NOT_CLEARED`); and, when
        the booking's `terms` is `PREPAID`, every FREIGHT invoice of the
        booking must be `PAID` (otherwise `ERR_OUTSTANDING_BALANCE`)."

        Design: Difficulty/cross_entity_state_dependency/bl_release_blocked_by_unaccepted_ams_filing
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        create_active_bond()
        bl = issue_bl(create_draft_bl(booking["id"])["id"])
        submit_and_answer_filing(create_filing(booking["id"], "ISF")["id"],
                                 "ACCEPTED")
        ams = create_filing(booking["id"], "AMS")
        validate_success(api.submit_compliance_filing(ams["id"], CO_1), 200)

        res = api.release_bill_of_lading(bl["id"], DOC_2)
        validate_error(res, ApiErrorId.ERR_FILINGS_NOT_CLEARED,
                       expected_status=409)
        after = validate_success(api.get_bill_of_lading(bl["id"], DOC_1), 200)
        assert after["status"] == "ISSUED", (
            "AMS merely SUBMITTED (not ACCEPTED) blocks release"
        )

    def test_release_succeeds_once_both_filings_accepted(self, api):
        """PRD §3.11: "Either path enforces three preconditions: the
        releaser's `X-User-ID` must differ from `issued_by_user_id` (otherwise
        `ERR_SEGREGATION_OF_DUTIES`); the booking's ISF and AMS filings must
        both be `ACCEPTED` (otherwise `ERR_FILINGS_NOT_CLEARED`); and, when
        the booking's `terms` is `PREPAID`, every FREIGHT invoice of the
        booking must be `PAID` (otherwise `ERR_OUTSTANDING_BALANCE`)."
        PRD §3.11: "On success `released_by_user_id` is stamped from
        `X-User-ID`."

        Design: Difficulty/cross_entity_state_dependency/bl_release_blocked_by_unaccepted_ams_filing
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        create_active_bond()
        bl = issue_bl(create_draft_bl(booking["id"])["id"])
        submit_and_answer_filing(create_filing(booking["id"], "ISF")["id"],
                                 "ACCEPTED")
        ams = create_filing(booking["id"], "AMS")
        validate_success(api.submit_compliance_filing(ams["id"], CO_1), 200)

        validate_error(api.release_bill_of_lading(bl["id"], DOC_2),
                       ApiErrorId.ERR_FILINGS_NOT_CLEARED)

        validate_success(
            api.record_filing_response(ams["id"], "ACCEPTED", CO_1), 200)
        released = validate_success(
            api.release_bill_of_lading(bl["id"], DOC_2), 200)
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "doc_2"

    def test_seaway_bl_surrender_rejected_conditional_action(self, api):
        """PRD §3.11: "A shipper surrenders its original bill — only valid
        when `release_mode` is `ORIGINAL` or `TELEX` (otherwise
        `ERR_BL_INVALID_STATE`) — transitioning `ISSUED` to `SURRENDERED`."

        Design: Corner/endpoints/seaway_bl_surrender_rejected_conditional_action
        """
        ctx = setup_documented_fcl_scenario(release_mode="SEAWAY")
        bl = ctx["bl"]

        res = api.surrender_bill_of_lading(
            bl["id"], make_shipper_headers(ctx["shipper"]["id"]))
        validate_error(res, ApiErrorId.ERR_BL_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_bill_of_lading(bl["id"], DOC_1), 200)
        assert after["status"] == "ISSUED"

    def test_original_bl_release_requires_surrender_first(self, api):
        """PRD §3.11: "For a `SEAWAY` bill, the direct path transitions
        `ISSUED` to `RELEASED`. For an `ORIGINAL` or `TELEX` bill, the release
        path runs from `SURRENDERED` to `RELEASED`; attempting the direct
        `ISSUED`-to-`RELEASED` transition on a non-SEAWAY bill is rejected
        with `ERR_BL_INVALID_STATE`."
        PRD §3.11: "The surrendering `Shipper` must own the booking: the
        acting `X-User-ID` must equal the booking's `shipper_id`, otherwise
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/endpoints/original_bl_release_requires_surrender_first
        """
        ctx = setup_documented_fcl_scenario(release_mode="ORIGINAL")
        bl = ctx["bl"]

        res = api.release_bill_of_lading(bl["id"], DOC_2)
        validate_error(res, ApiErrorId.ERR_BL_INVALID_STATE, expected_status=409)

        surrendered = validate_success(
            api.surrender_bill_of_lading(
                bl["id"], make_shipper_headers(ctx["shipper"]["id"])),
            200)
        assert surrendered["status"] == "SURRENDERED"

        released = validate_success(api.release_bill_of_lading(bl["id"], DOC_2), 200)
        assert released["status"] == "RELEASED"

    def test_prepaid_release_blocked_until_freight_paid(self, api):
        """PRD §3.11: "Either path enforces three preconditions: the
        releaser's `X-User-ID` must differ from `issued_by_user_id` (otherwise
        `ERR_SEGREGATION_OF_DUTIES`); the booking's ISF and AMS filings must
        both be `ACCEPTED` (otherwise `ERR_FILINGS_NOT_CLEARED`); and, when
        the booking's `terms` is `PREPAID`, every FREIGHT invoice of the
        booking must be `PAID` (otherwise `ERR_OUTSTANDING_BALANCE`)."

        Design: Corner/validations/prepaid_release_blocked_until_freight_paid
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)  # PREPAID by default
        create_active_bond()
        bl = issue_bl(create_draft_bl(booking["id"])["id"])
        accept_both_filings(booking["id"])
        invoice = create_issued_freight_invoice(booking["id"])
        assert invoice["total_cents"] == 77400

        res = api.release_bill_of_lading(bl["id"], DOC_2)
        validate_error(res, ApiErrorId.ERR_OUTSTANDING_BALANCE,
                       expected_status=402)

        paid = validate_success(
            api.record_invoice_payment(invoice["id"], 77400, FC), 200)
        assert paid["status"] == "PAID"
        released = validate_success(
            api.release_bill_of_lading(bl["id"], DOC_2), 200)
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "doc_2"


class TestBondCoverageGateAfterAccrual:
    def test_late_ams_accrual_drains_bond_available_coverage(self, api):
        """PRD §3.10: "When a submission is late and the filing's
        `penalty_status` is still `NONE`, the penalty accrues:
        `penalty_amount_cents` is set to 500000 cents for an `ISF` filing and
        300000 cents for an `AMS` filing, and `penalty_status` transitions
        from `NONE` to `ACCRUED`. The accrual debits the available coverage of
        the bond selected as: `ACTIVE`, with a window covering the logical
        clock, and with the earliest `created_at` among qualifying bonds; if
        no bond qualifies, the accrual is recorded on the filing only and
        debits nothing."

        Design: Difficulty/cross_entity_state_dependency/bl_issue_blocked_by_bond_coverage_after_penalty_accrual
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        bond = create_active_bond(coverage_amount_cents=80000)
        create_draft_bl(booking["id"])
        ams = create_filing(booking["id"], "AMS")

        # AMS deadline is etd - 48h == 2026-08-30T00:00:00Z; 1s past is late.
        validate_success(api.set_clock("2026-08-30T00:00:01Z", OPS), 200)
        submitted = validate_success(
            api.submit_compliance_filing(ams["id"], CO_1), 200)
        assert submitted["is_late"] is True
        assert submitted["penalty_status"] == "ACCRUED"
        assert submitted["penalty_amount_cents"] == 300000

        bond_after = validate_success(api.get_surety_bond(bond["id"], CO_1), 200)
        assert bond_after["available_coverage_cents"] == 80000 - 300000

    def test_bl_issue_rejected_when_bond_coverage_drained(self, api):
        """PRD §3.11: "Second, the **bond gate** requires the existence of a
        `SuretyBond` whose `status` is `ACTIVE`, whose window satisfies
        `effective_from` less than or equal to the logical clock and the
        logical clock strictly less than `effective_to`, and whose
        `available_coverage_cents` is at least 75000 cents — a failure is
        rejected with `ERR_BOND_COVERAGE_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/bl_issue_blocked_by_bond_coverage_after_penalty_accrual
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        bond = create_active_bond(coverage_amount_cents=80000)
        bl = create_draft_bl(booking["id"])
        ams = create_filing(booking["id"], "AMS")

        validate_success(api.set_clock("2026-08-30T00:00:01Z", OPS), 200)
        validate_success(api.submit_compliance_filing(ams["id"], CO_1), 200)
        drained = validate_success(api.get_surety_bond(bond["id"], CO_1), 200)
        assert drained["available_coverage_cents"] < 75000, (
            "accrual pushed available coverage below the 75000-cent gate"
        )

        res = api.issue_bill_of_lading(bl["id"], DOC_1)
        validate_error(res, ApiErrorId.ERR_BOND_COVERAGE_INSUFFICIENT,
                       expected_status=409)
        after = validate_success(api.get_bill_of_lading(bl["id"], DOC_1), 200)
        assert after["status"] == "DRAFT"
