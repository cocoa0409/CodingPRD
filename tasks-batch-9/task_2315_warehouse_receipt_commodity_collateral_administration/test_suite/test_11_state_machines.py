"""
State machines: initial states, permitted edges, refused edges, terminal
lockdown, and the side effects each admitted transition is obliged to run.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal, assert_instant_equals
from test_helpers.constants import CLOCK_BASE_UTC
from test_helpers.test_users import (
    REGULATOR_HEADERS,
    REGULATOR_USER_ID,
    SECOND_REGULATOR_HEADERS,
    make_warehouse_operator_headers,
)

CLOCK_LOADOUT_DAY = "2026-09-14T09:00:00Z"
CLOCK_INSOLVENCY_DAY = "2026-09-01T08:00:00Z"


class TestWarehouseLicensingEdges:
    def test_a_fresh_application_starts_applied_solvent_and_closed(
        self, api, new_warehouse
    ):
        """
        Nothing about the application is open yet, and the financial test has
        already run: a 500000-bushel STATE facility needs 5000000 cents of net
        worth (the programme floor beats 4 cents a bushel), a 1250000-cent
        quarter of that as tolerance, and a 2500000-cent bond, all of which this
        application exactly meets.

        PRD: "The application is created in `license_state` `APPLIED` and
        `insolvency_state` `SOLVENT`, and its `operational_posture` is `CLOSED`
        for as long as the licence is merely applied for."

        Design: Corner/state_machines/warehouse_starts_applied_and_solvent_with_derived_requirements
        """
        warehouse = new_warehouse()

        assert_fields_equal(
            warehouse,
            {
                "license_state": "APPLIED",
                "insolvency_state": "SOLVENT",
                "operational_posture": "CLOSED",
                "licensed_by_user_id": None,
                "required_net_worth_cents": 5000000,
                "net_worth_shortfall_cents": 0,
                "net_worth_tolerance_cents": 1250000,
                "required_bond_cents": 2500000,
                "bond_deficiency_cents": 0,
                "obligation_bushels": 0,
                "version": 1,
            },
        )

    def test_issuing_the_licence_stamps_the_regulator_and_opens_the_posture(
        self, api, new_warehouse
    ):
        """
        The one decision moves the licence dimension, records who made it, copies
        both dates off the request and re-derives the posture, which reaches OPEN
        because the facility is solvent and square on its position.

        PRD: "Issuance records the deciding regulator's `X-User-ID` in
        `licensed_by_user_id`, sets `license_effective_date` and
        `license_expiry_date` from the request, and recomputes
        `operational_posture` — which reaches `OPEN` when the facility is
        `SOLVENT` and its position variance is inside tolerance."

        Design: Corner/state_machines/license_issue_from_applied_moves_to_licensed_and_opens_posture
        """
        warehouse = new_warehouse()

        licensed = get_success_data(
            api.license_decision(
                warehouse["id"], f.license_issue_payload(), REGULATOR_HEADERS
            ),
            200,
        )

        assert_fields_equal(
            licensed,
            {
                "license_state": "LICENSED",
                "licensed_by_user_id": REGULATOR_USER_ID,
                "license_effective_date": "2026-08-01",
                "license_expiry_date": "2027-07-31",
                "operational_posture": "OPEN",
                "version": 2,
            },
        )

    def test_suspending_a_licence_that_was_never_issued_is_refused(
        self, api, new_warehouse
    ):
        """
        SUSPEND is defined only on the LICENSED edge, so against a merely applied
        facility it is inadmissible and writes nothing at all — the version is
        still the one the application was created with.

        PRD: "Any decision issued against a licence not in the required source
        state is rejected with `ERR_INVALID_STATE` (HTTP 409), and every licensing
        decision increments the warehouse's `version` by one."

        Design: Corner/state_machines/license_suspend_from_applied_rejected
        """
        warehouse = new_warehouse()

        response = api.license_decision(
            warehouse["id"],
            f.license_decision_payload("SUSPEND", note="premature"),
            REGULATOR_HEADERS,
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        current = get_success_data(
            api.get_warehouse(warehouse["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(current, {"license_state": "APPLIED", "version": 1})

    def test_a_denied_application_cannot_be_licensed_afterwards(
        self, api, new_warehouse
    ):
        """
        Denial is the end of that application's life, so a later ISSUE does not
        resurrect it and the posture stays shut.

        PRD: "`DENIED` is terminal: a denied application cannot be revived, and a
        fresh warehouse row must be filed instead."

        Design: Corner/state_machines/license_decision_on_denied_warehouse_rejected
        """
        warehouse = new_warehouse()
        get_success_data(
            api.license_decision(
                warehouse["id"],
                f.license_decision_payload("DENY", note="insufficient facilities"),
                REGULATOR_HEADERS,
            ),
            200,
        )

        response = api.license_decision(
            warehouse["id"], f.license_issue_payload(), REGULATOR_HEADERS
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        current = get_success_data(
            api.get_warehouse(warehouse["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            current, {"license_state": "DENIED", "operational_posture": "CLOSED"}
        )

    def test_re_issuing_a_licence_already_in_force_is_an_error_not_a_no_op(
        self, api, licensed_warehouse
    ):
        """
        Replaying the identical ISSUE decision against a facility that is already
        licensed is refused rather than silently absorbed, and the second attempt
        does not bump the version.

        PRD: "`APPLIED → LICENSED` on `ISSUE`, permitted only while the licence
        is `APPLIED` and only when the net-worth and bond tests above both pass."

        Design: Corner/state_machines/second_license_issue_on_licensed_warehouse_rejected
        """
        warehouse = licensed_warehouse()

        response = api.license_decision(
            warehouse["id"], f.license_issue_payload(), REGULATOR_HEADERS
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        current = get_success_data(
            api.get_warehouse(warehouse["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(current, {"license_state": "LICENSED", "version": 2})


class TestStorageAgreementTermination:
    def test_an_agreement_with_an_outstanding_receipt_cannot_be_terminated(
        self, api, base_full
    ):
        """
        WR-0001 is still ISSUED under this agreement, so termination is
        inadmissible and the supplied reason is not recorded.

        PRD: "An agreement reaches `TERMINATED` only when nothing is outstanding
        under it: no receipt under the agreement may be in `receipt_state`
        `ISSUED`, and no deposit ticket under it may be in `ticket_state`
        `WEIGHED` or `ACCEPTED`."

        Design: Corner/state_machines/agreement_terminate_blocked_by_issued_receipt
        """
        response = api.terminate_storage_agreement(
            base_full["agreement_id"],
            f.terminate_agreement_payload(termination_reason="DEPOSITOR_REQUEST"),
            base_full["operator_headers"],
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        agreement = get_success_data(
            api.get_storage_agreement(
                base_full["agreement_id"], base_full["operator_headers"]
            ),
            200,
        )
        assert_fields_equal(
            agreement, {"agreement_state": "ACTIVE", "termination_reason": None}
        )

    def test_terminating_a_clean_agreement_frees_the_bin_dedicated_to_it(
        self, api, licensed_warehouse, new_producer, new_agreement, new_bin
    ):
        """
        With nothing outstanding the termination goes through, records its reason
        and releases the dedication on bin B3 while leaving the bin's physical
        condition alone.

        PRD: "Termination records the supplied `termination_reason` — which is
        null while the agreement is `ACTIVE` — and releases any bin whose
        `dedicated_agreement_id` points at this agreement."

        Design: Corner/state_machines/agreement_terminate_releases_dedicated_bin
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        headers = make_warehouse_operator_headers(warehouse["id"])
        dedicated_bin = new_bin(
            warehouse["id"],
            bin_code="B3",
            capacity_bushels=20000,
            commingling_allowed=False,
            dedicated_agreement_id=agreement["id"],
        )

        terminated = get_success_data(
            api.terminate_storage_agreement(
                agreement["id"],
                f.terminate_agreement_payload(termination_reason="DEPOSITOR_REQUEST"),
                headers,
            ),
            200,
        )
        assert_fields_equal(
            terminated,
            {
                "agreement_state": "TERMINATED",
                "termination_reason": "DEPOSITOR_REQUEST",
            },
        )

        storage_bin = get_success_data(api.get_bin(dedicated_bin["id"], headers), 200)
        assert_fields_equal(
            storage_bin,
            {"dedicated_agreement_id": None, "condition_state": "SOUND"},
        )


class TestDepositTicketRejectionEdge:
    def test_an_accepted_load_can_no_longer_be_turned_away(self, api, base_pre):
        """
        Rejection is a WEIGHED-only edge: once the grain has joined the mass the
        refusal is inadmissible, and the bin's 949 stored bushels prove nothing
        was un-stored on the way out.

        PRD: "Only `WEIGHED` tickets are rejectable — an already-accepted ticket
        has entered the commingled mass and can no longer be turned away — so
        rejecting an accepted, receipted or already-rejected ticket is refused
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/deposit_ticket_reject_after_accept_rejected
        """
        response = api.reject_deposit_ticket(
            base_pre["ticket_id"],
            f.reject_ticket_payload(),
            base_pre["operator_headers"],
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        ticket = get_success_data(
            api.get_deposit_ticket(base_pre["ticket_id"], base_pre["operator_headers"]),
            200,
        )
        assert ticket["ticket_state"] == "ACCEPTED"

        storage_bin = get_success_data(
            api.get_bin(base_pre["bin_id"], base_pre["operator_headers"]), 200
        )
        assert storage_bin["stored_bushels"] == 949


class TestPositionReportRevisionCycle:
    def test_a_corrected_resubmission_accepts_and_counts_the_revision(
        self, api, base_full, submitted_report
    ):
        """
        The first filing understated the count by 549 bushels, was referred, and
        came back DEFICIENT. Re-filing the true figures reconciles all three
        deltas to zero, so the report accepts as revision 1 with a PASS and the
        restriction it had caused is lifted.

        PRD: "From `REJECTED`, a re-submission whose `examination_required`
        computes false goes instead to `ACCEPTED`, likewise incrementing
        `revision_count` by one, setting `examination_result` to `PASS`, and
        clearing the `RESTRICTED` posture attributable to this report."

        Design: Corner/state_machines/position_report_resubmit_after_rejection_increments_revision_count
        """
        report = submitted_report(base_full["warehouse_id"], 400, 949)
        assert report["report_state"] == "UNDER_EXAMINATION"

        rejected = get_success_data(
            api.examine_position_report(
                report["id"],
                f.examine_report_payload("DEFICIENT", findings_note="count short"),
                SECOND_REGULATOR_HEADERS,
            ),
            200,
        )
        assert rejected["report_state"] == "REJECTED"

        resubmitted = get_success_data(
            api.submit_position_report(
                report["id"],
                f.submit_report_payload(949, 949),
                base_full["operator_headers"],
            ),
            200,
        )
        assert_fields_equal(
            resubmitted,
            {
                "report_state": "ACCEPTED",
                "revision_count": 1,
                "examination_result": "PASS",
                "count_discrepancy_bushels": 0,
                "obligation_misstatement_bushels": 0,
                "position_variance_bushels": 0,
                "examination_required": False,
            },
        )

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], REGULATOR_HEADERS), 200
        )
        assert warehouse["operational_posture"] == "OPEN"


class TestDeliverySettlementForks:
    @pytest.fixture
    def loaded_order(self, api, base_full, set_clock, booked_delivery_order):
        """A loadout of a caller-chosen size, loaded at the receipt's own grade."""

        def _load(bushels: int):
            set_clock(CLOCK_LOADOUT_DAY)
            order = booked_delivery_order(
                base_full["depositor_id"],
                base_full["receipt_id"],
                bushels,
                CLOCK_LOADOUT_DAY,
                "2026-09-14T11:00:00Z",
            )
            return get_success_data(
                api.load_delivery_order(
                    order["id"],
                    f.load_payload(bushels, delivered_moisture_pct=15.0),
                    base_full["operator_headers"],
                ),
                200,
            )

        return _load

    def test_a_partial_settlement_charges_storage_on_the_whole_stored_lot(
        self, api, base_full, loaded_order
    ):
        """
        Only 400 of the 949 bushels leave, but all 949 occupied the bin, so the
        final storage accrual over 26 chargeable days is 8636 cents on the whole
        lot; the loadout charge is the delivered 400 bushels at 8 cents, and with
        no grade improvement to credit the depositor ends up 11836 cents down.

        PRD: "Storage is charged on the receipt's whole outstanding quantity,
        **not** on the delivered bushels, because the entire lot occupied the bin
        up to this moment."

        Design: Corner/state_machines/delivery_settle_partial_leaves_receipt_issued_with_reduced_quantity
        """
        order = loaded_order(400)

        settled = get_success_data(
            api.settle_delivery_order(
                order["id"], f.settle_payload(430), base_full["operator_headers"]
            ),
            200,
        )
        assert_fields_equal(
            settled,
            {
                "delivery_state": "SETTLED_PARTIAL",
                "delivered_grade": "US_NO_1",
                "grade_delta_bps": 0,
                "quality_adjustment_cents": 0,
                "storage_charge_cents": 8636,
                "loadout_charge_cents": 3200,
                "net_settlement_cents": -11836,
            },
        )

        party = get_success_data(
            api.get_party(base_full["depositor_id"], base_full["depositor_headers"]),
            200,
        )
        assert party["settlement_balance_cents"] == -11836

    def test_a_partial_settlement_leaves_the_receipt_issued_at_the_residual(
        self, api, base_full, loaded_order
    ):
        """
        The receipt survives a partial delivery: 949 less the 400 delivered
        leaves 549 bushels of obligation on both the receipt and the bin, and no
        grain stays held.

        PRD: "The quality adjustment and net settlement are computed on the
        delivered quantity only, and the receipt stays in `receipt_state`
        `ISSUED` with its `quantity_bushels` reduced by `delivered_bushels`, so a
        residual obligation and a residual collateral base both remain."

        Design: Corner/state_machines/delivery_settle_partial_leaves_receipt_issued_with_reduced_quantity
        """
        order = loaded_order(400)
        get_success_data(
            api.settle_delivery_order(
                order["id"], f.settle_payload(430), base_full["operator_headers"]
            ),
            200,
        )

        headers = base_full["operator_headers"]
        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], headers), 200
        )
        assert_fields_equal(
            receipt, {"receipt_state": "ISSUED", "quantity_bushels": 549}
        )

        storage_bin = get_success_data(api.get_bin(base_full["bin_id"], headers), 200)
        assert_fields_equal(
            storage_bin, {"stored_bushels": 549, "held_bushels": 0}
        )

    def test_a_full_delivery_cancels_the_receipt_and_empties_the_bin(
        self, api, base_full, loaded_order
    ):
        """
        Taking the whole 949 bushels out performs the receipt: it is cancelled at
        zero quantity, the bin empties and loses its blended grade, and the
        warehouse owes nothing at all. Storage is still the same 8636 cents,
        while the loadout charge grows to 7592 for the larger load.

        PRD: "The receipt's `quantity_bushels` drops to zero and its
        `receipt_state` moves from `ISSUED` to `CANCELLED`, so the receipt leaves
        the warehouse's `obligation_bushels` entirely."

        Design: Corner/state_machines/delivery_settle_full_cancels_receipt_and_empties_bin
        """
        order = loaded_order(949)

        settled = get_success_data(
            api.settle_delivery_order(
                order["id"], f.settle_payload(430), base_full["operator_headers"]
            ),
            200,
        )
        assert_fields_equal(
            settled,
            {
                "delivery_state": "SETTLED_FULL",
                "storage_charge_cents": 8636,
                "loadout_charge_cents": 7592,
                "net_settlement_cents": -16228,
            },
        )

        headers = base_full["operator_headers"]
        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], headers), 200
        )
        assert_fields_equal(
            receipt, {"receipt_state": "CANCELLED", "quantity_bushels": 0}
        )

        storage_bin = get_success_data(api.get_bin(base_full["bin_id"], headers), 200)
        assert_fields_equal(
            storage_bin, {"stored_bushels": 0, "blended_grade": None}
        )

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            warehouse,
            {"obligation_bushels": 0, "receipted_obligation_bushels": 0},
        )


class TestLienWithdrawalEdge:
    def test_withdrawing_a_never_perfected_advance_touches_no_credit(
        self, api, base_full, set_clock, request_lien
    ):
        """
        The valuation ran and produced a 290482-cent limit, but nothing was ever
        committed, so releasing straight from REQUESTED compensates nothing: the
        receipt was never pledged and the line is untouched at its full
        50000000 cents.

        PRD: "That path sets `released_at` with `payoff_received_cents` of zero,
        and has **no** credit-line effect and **no** effect on the receipt's
        encumbrance dimension, because nothing was ever committed and no
        possession was ever taken."

        Design: Corner/state_machines/lien_release_from_requested_has_no_credit_effect
        """
        set_clock("2026-08-20T09:00:00Z")
        lien = request_lien(base_full["receipt_id"], base_full["lender_id"])

        released = get_success_data(
            api.release_lien(
                lien["id"], f.release_payload(0), base_full["lender_headers"]
            ),
            200,
        )
        assert_fields_equal(
            released,
            {
                "lien_state": "RELEASED",
                "payoff_received_cents": 0,
                "perfected_at": None,
                "advance_limit_cents": 290482,
            },
        )

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert receipt["encumbrance_state"] == "UNENCUMBERED"

        lender = get_success_data(
            api.get_party(base_full["lender_id"], base_full["lender_headers"]), 200
        )
        assert_fields_equal(
            lender,
            {"committed_advance_cents": 0, "available_credit_cents": 50000000},
        )


class TestInsolvencyEdges:
    def test_allocation_is_refused_while_any_claim_is_still_unadjudicated(
        self, api, base_full, set_clock, claims_open_warehouse, filed_claim
    ):
        """
        One claim is still FILED, so the waterfall cannot run; the proceeding
        stays open for claims and no share or roll-up figure is written.

        PRD: "It requires the warehouse to be `CLAIMS_OPEN` and requires that
        **no** claim of this warehouse remain in `claim_state` `FILED` — every
        claim must have been adjudicated one way or the other first, or the run is
        refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/insolvency_allocate_blocked_while_a_claim_is_still_filed
        """
        set_clock(CLOCK_INSOLVENCY_DAY)
        claims_open_warehouse(base_full["warehouse_id"])
        claim = filed_claim(
            base_full["warehouse_id"],
            base_full["receipt_id"],
            base_full["depositor_id"],
            400000,
        )

        response = api.insolvency_action(
            base_full["warehouse_id"],
            f.insolvency_payload("ALLOCATE"),
            REGULATOR_HEADERS,
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            warehouse,
            {"insolvency_state": "CLAIMS_OPEN", "allocated_total_cents": 0},
        )

        current_claim = get_success_data(
            api.get_indemnity_claim(claim["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            current_claim, {"claim_state": "FILED", "bond_share_cents": 0}
        )

    def test_declaring_insolvency_cancels_bookings_and_turns_away_weighed_grain(
        self, api, base_full, weighed_ticket, booked_delivery_order
    ):
        """
        One regulator action reaches three other rows: the requested loadout is
        cancelled and its 400-bushel hold released, the load still on the scale is
        turned away, and the posture closes even though the licence itself is
        untouched.

        PRD: "Declaration drives `operational_posture` to `CLOSED` regardless of
        `license_state`, cancels every delivery order in `delivery_state`
        `REQUESTED` with `cancellation_reason` `INSOLVENCY_DECLARED` and releases
        their held bushels, and moves every deposit ticket in `ticket_state`
        `WEIGHED` to `REJECTED` with `rejection_reason` `INSOLVENCY_DECLARED`."

        Design: Corner/state_machines/insolvency_declare_cancels_requested_orders_and_rejects_weighed_tickets
        """
        weighed = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-06T09:00:00Z",
            fill_end_at="2026-08-06T11:00:00Z",
        )
        order = booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            400,
            "2026-08-20T09:00:00Z",
            "2026-08-20T11:00:00Z",
        )

        warehouse = get_success_data(
            api.insolvency_action(
                base_full["warehouse_id"],
                f.insolvency_payload(
                    "DECLARE",
                    insolvency_price_cents_per_bushel=400,
                    note="receivership",
                ),
                REGULATOR_HEADERS,
            ),
            200,
        )
        assert_fields_equal(
            warehouse,
            {
                "insolvency_state": "DECLARED",
                "license_state": "LICENSED",
                "operational_posture": "CLOSED",
                "insolvency_price_cents_per_bushel": 400,
            },
        )
        assert_instant_equals(
            warehouse["insolvency_declared_at"], CLOCK_BASE_UTC, "insolvency_declared_at"
        )

        headers = base_full["operator_headers"]
        cancelled = get_success_data(api.get_delivery_order(order["id"], headers), 200)
        assert_fields_equal(
            cancelled,
            {
                "delivery_state": "CANCELLED",
                "cancellation_reason": "INSOLVENCY_DECLARED",
            },
        )

        rejected = get_success_data(
            api.get_deposit_ticket(weighed["id"], headers), 200
        )
        assert_fields_equal(
            rejected,
            {"ticket_state": "REJECTED", "rejection_reason": "INSOLVENCY_DECLARED"},
        )

        storage_bin = get_success_data(api.get_bin(base_full["bin_id"], headers), 200)
        assert_fields_equal(
            storage_bin,
            {
                "held_bushels": 0,
                "available_bushels": 949,
                "scheduled_inbound_bushels": 0,
            },
        )

    def test_adjudicating_an_already_allowed_claim_a_second_time_is_refused(
        self, api, base_full, set_clock, claims_open_warehouse, filed_claim
    ):
        """
        The first ALLOW fixed the economics — 949 bushels at the posted 400 cents
        is 379600, less 9300 of provisional storage over the 28 days to the
        declaration and the 5694 receiving charge, gives an entitlement of 364606
        and an allowed amount capped by it — and the second ALLOW is inadmissible,
        so none of those figures and not even the note is overwritten.

        PRD: "It is admissible only while the claim is `FILED` and the warehouse
        is `CLAIMS_OPEN`, and it records `adjudicated_by_user_id`."

        PRD: "State admissibility of the requested transition — `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_adjudicate_twice_rejected
        """
        set_clock(CLOCK_INSOLVENCY_DAY)
        claims_open_warehouse(base_full["warehouse_id"])
        claim = filed_claim(
            base_full["warehouse_id"],
            base_full["receipt_id"],
            base_full["depositor_id"],
            400000,
        )
        get_success_data(
            api.adjudicate_indemnity_claim(
                claim["id"],
                f.adjudicate_payload("ALLOW", adjudication_note="receipt verified"),
                REGULATOR_HEADERS,
            ),
            200,
        )

        response = api.adjudicate_indemnity_claim(
            claim["id"],
            f.adjudicate_payload("ALLOW", adjudication_note="duplicate"),
            REGULATOR_HEADERS,
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        current = get_success_data(
            api.get_indemnity_claim(claim["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            current,
            {
                "claim_state": "ALLOWED",
                "entitlement_cents": 364606,
                "allowed_cents": 364606,
                "fund_eligible": True,
                "adjudication_note": "receipt verified",
            },
        )


class TestBinBlendOutTreatment:
    def test_blending_a_bin_back_to_watch_loses_the_blend_bushels(
        self, api, base_full, assess_bin
    ):
        """
        A BLEND_OUT treatment that lifts the bin off OUT_OF_CONDITION mixes away
        150 basis points of the 949 stored bushels — 14 of them — leaving 935
        stored and 25 on the shrink accumulator, and the receipt's quality flag
        comes back with the bin. The 14-bushel gap against a 949-bushel
        obligation is well inside the 500-bushel tolerance, so the posture stays
        open.

        PRD: "When the recorded `treatment_action` is `BLEND_OUT`, the bin is
        physically mixed and loses volume: the blend loss is 150 basis points —
        one and a half percent — of the bin's `stored_bushels`, rounded half up to
        a whole bushel; `stored_bushels` falls by that amount and
        `cumulative_shrink_bushels` rises by exactly the same amount."

        PRD: "If the treating assessment carried `BLEND_OUT`, the blend loss
        described above is applied as well, so the bushels regained are the
        post-blend figure."

        Design: Corner/state_machines/blend_treatment_out_of_condition_to_watch_shrinks_stored_bushels
        """
        assess_bin(base_full["warehouse_id"], base_full["bin_id"], 16.0, 70)

        blended = assess_bin(
            base_full["warehouse_id"],
            base_full["bin_id"],
            14.2,
            70,
            treatment_action="BLEND_OUT",
        )
        assert_fields_equal(
            blended,
            {
                "condition_state": "WATCH",
                "stored_bushels": 935,
                "cumulative_shrink_bushels": 25,
                "last_treatment_action": "BLEND_OUT",
                "last_moisture_pct": 14.2,
            },
        )
        assert_instant_equals(
            blended["last_assessed_at"], CLOCK_BASE_UTC, "last_assessed_at"
        )

        headers = base_full["operator_headers"]
        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], headers), 200
        )
        assert receipt["quality_flag"] == "SOUND"

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            warehouse,
            {
                "system_physical_bushels": 935,
                "sound_physical_bushels": 935,
                "position_variance_bushels": -14,
                "examination_tolerance_bushels": 500,
                "operational_posture": "OPEN",
            },
        )
