"""
One test per refusal: which error id a violated rule produces, what HTTP status
carries it, and that the refused write left nothing behind.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.constants import BASE_RECEIPT_NUMBER
from test_helpers.test_users import (
    REGULATOR_HEADERS,
    SECOND_REGULATOR_HEADERS,
    make_lender_headers,
    make_warehouse_operator_headers,
)

CLOCK_DAY_16 = "2026-08-20T09:00:00Z"
CLOCK_INSOLVENCY_DAY = "2026-09-01T08:00:00Z"
APPOINTMENT_START = "2026-08-20T09:00:00Z"
APPOINTMENT_END = "2026-08-20T11:00:00Z"


class TestUnresolvedIdentifiers:
    def test_each_entity_family_answers_with_its_own_not_found_id(self, api, base_clock):
        """
        Nothing exists in the system at all, and each of these seven routes names a
        different entity family — so a shared generic 404 would lose information the
        caller is entitled to. Every one comes back with the id belonging to the
        family whose row could not be resolved.

        PRD: "The full set of resolution failures is `ERR_WAREHOUSE_NOT_FOUND`,
        `ERR_BIN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
        `ERR_RECEIPT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and
        `ERR_PARTY_NOT_FOUND`, each HTTP 404."

        PRD: "Existence of every identifier, resolved left to right per §2.4 — the
        404 family."

        Design: Corner/errors/unresolved_path_ids_return_entity_specific_not_found_errors
        """
        probes = [
            (api.get_party(NON_EXISTENT_UUID, REGULATOR_HEADERS), E.ERR_PARTY_NOT_FOUND),
            (
                api.get_storage_agreement(NON_EXISTENT_UUID, REGULATOR_HEADERS),
                E.ERR_AGREEMENT_NOT_FOUND,
            ),
            (
                api.get_deposit_ticket(NON_EXISTENT_UUID, REGULATOR_HEADERS),
                E.ERR_TICKET_NOT_FOUND,
            ),
            (
                api.get_collateral_lien(NON_EXISTENT_UUID, REGULATOR_HEADERS),
                E.ERR_LIEN_NOT_FOUND,
            ),
            (
                api.examine_position_report(
                    NON_EXISTENT_UUID,
                    f.examine_report_payload("PASS"),
                    SECOND_REGULATOR_HEADERS,
                ),
                E.ERR_REPORT_NOT_FOUND,
            ),
            (
                api.get_delivery_order(NON_EXISTENT_UUID, REGULATOR_HEADERS),
                E.ERR_DELIVERY_ORDER_NOT_FOUND,
            ),
            (
                api.adjudicate_indemnity_claim(
                    NON_EXISTENT_UUID, f.adjudicate_payload("ALLOW"), REGULATOR_HEADERS
                ),
                E.ERR_CLAIM_NOT_FOUND,
            ),
        ]

        for response, expected_error in probes:
            validate_error(response, expected_error, 404)


class TestTransferChannelEligibility:
    def test_an_electronic_receipt_cannot_be_endorsed_by_its_holder(
        self, api, base_full, new_producer
    ):
        """
        Endorsement is the paper channel; WR-0001 is electronic, so its holder has
        no way to move it at all — the registry administrator does that. The refusal
        is an authorization-shaped 403, and the receipt's audit trail records no
        attempt.

        PRD: "A `PAPER` receipt is transferred by its current holder — acting as
        `Depositor` or `Lender` — with `transfer_channel` `ENDORSEMENT`."

        PRD: "An `ELECTRONIC` receipt is transferred only by a
        `RegistryAdministrator` with `transfer_channel` `REGISTRY`, and only at a
        registry-participating warehouse."

        PRD: "Any other combination of channel, medium and role is refused with
        `ERR_TRANSFER_CHANNEL_INVALID` (HTTP 403); a `REGISTRY` transfer attempted at
        a warehouse whose `registry_participant` is false is refused with
        `ERR_REGISTRY_NOT_PARTICIPANT`."

        Design: Corner/errors/electronic_receipt_endorsement_transfer_rejected
        """
        transferee = new_producer(name="Bo Farms")

        response = api.transfer_receipt(
            base_full["receipt_id"],
            f.transfer_payload(transferee["id"], "ENDORSEMENT"),
            base_full["depositor_headers"],
        )

        validate_error(response, E.ERR_TRANSFER_CHANNEL_INVALID, 403)

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert receipt["holder_party_id"] == base_full["depositor_id"]
        assert receipt["transfer_log"] == []


class TestRestrictedPostureGate:
    def test_a_rejected_examination_closes_the_door_on_the_next_acceptance(
        self, api, base_full, weighed_ticket, submitted_report
    ):
        """
        The declared count is 549 bushels short of what the bins actually hold, which
        is past the 500-bushel tolerance, so the filing is referred out and the
        regulator finds it deficient. That single finding restricts the facility even
        though its physical position reconciles exactly — and a restricted facility
        may not take on more obligation.

        PRD: "When `examination_required` computes true, a `DRAFT` report goes to
        `UNDER_EXAMINATION` instead, and this branch additionally requires that no
        other report of the same warehouse already sit in `UNDER_EXAMINATION`; a
        second referral while another remains under examination is refused with
        `ERR_INVALID_STATE`."

        PRD: "`DEFICIENT` moves the report to `REJECTED` and drives the warehouse's
        `operational_posture` to `RESTRICTED`."

        PRD: "Otherwise, if the absolute value of `position_variance_bushels` is
        strictly greater than `examination_tolerance_bushels`, or the most recently
        submitted position report of this warehouse is in `report_state` `REJECTED`,
        the posture is `RESTRICTED`."

        PRD: "`RESTRICTED` blocks the three operations that would grow or newly
        encumber the obligation — deposit acceptance, receipt issuance and lien
        perfection — with `ERR_POSTURE_RESTRICTED`, while leaving delivery out of
        store available so that depositors can still get their grain."

        Design: Corner/errors/deposit_accept_under_restricted_posture_rejected
        """
        headers = base_full["operator_headers"]
        pending = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-06T09:00:00Z",
            fill_end_at="2026-08-06T11:00:00Z",
        )
        report = submitted_report(base_full["warehouse_id"], 400, 949)
        assert report["report_state"] == "UNDER_EXAMINATION"
        examined = get_success_data(
            api.examine_position_report(
                report["id"],
                f.examine_report_payload("DEFICIENT", findings_note="count short"),
                SECOND_REGULATOR_HEADERS,
            ),
            200,
        )
        assert_fields_equal(
            examined, {"report_state": "REJECTED", "examination_result": "DEFICIENT"}
        )

        storage_bin = get_success_data(api.get_bin(base_full["bin_id"], headers), 200)
        response = api.accept_deposit_ticket(
            pending["id"], f.accept_ticket_payload(storage_bin["version"]), headers
        )

        validate_error(response, E.ERR_POSTURE_RESTRICTED, 422)

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            warehouse,
            {"position_variance_bushels": 0, "operational_posture": "RESTRICTED"},
        )

        current_ticket = get_success_data(
            api.get_deposit_ticket(pending["id"], headers), 200
        )
        assert current_ticket["ticket_state"] == "WEIGHED"


class TestMinimumGradeGate:
    def test_a_lot_one_rank_below_the_contract_floor_is_turned_away_at_acceptance(
        self, api, licensed_warehouse, new_producer, new_agreement, new_bin, weighed_ticket
    ):
        """
        The load was legally weighed — a scale ticket records what came off the
        truck whatever it grades — so the grade gate sits at acceptance instead. Six
        percent damage puts the lot at US_NO_3, one rank worse than the agreement's
        US_NO_2 floor, and nothing enters the bin.

        PRD: "the ticket's `assigned_grade` must rank at or above the agreement's
        `min_grade`, or the request is rejected with `ERR_GRADE_BELOW_MINIMUM`; and
        the bin must have room."

        PRD: "Grades also carry a rank used whenever two grades are compared:
        `US_NO_1` ranks 1, `US_NO_2` ranks 2, `US_NO_3` ranks 3 and `SAMPLE_GRADE`
        ranks 4."

        PRD: "It declares a `min_grade`, the worst grade the warehouse will accept
        under this agreement, drawn from the four grades of §2.9; a
        `max_moisture_pct` contract moisture ceiling carried to one decimal place;
        and its commercial terms: `storage_rate_millicents_per_bushel_day`, a
        one-time `receiving_charge_cents_per_bushel`, a
        `loadout_charge_cents_per_bushel` applied per delivered bushel at
        settlement, a count of `free_storage_days`, and a
        `declared_value_cents_per_bushel` of at least one cent."

        Design: Corner/errors/accept_of_lot_below_agreement_minimum_grade_rejected
        """
        warehouse = licensed_warehouse()
        headers = make_warehouse_operator_headers(warehouse["id"])
        producer = new_producer()
        agreement = new_agreement(
            warehouse["id"], producer["id"], min_grade="US_NO_2"
        )
        storage_bin = new_bin(warehouse["id"])
        ticket = weighed_ticket(
            warehouse["id"], agreement["id"], storage_bin["id"], damage_pct=6.0
        )
        assert ticket["assigned_grade"] == "US_NO_3"

        response = api.accept_deposit_ticket(
            ticket["id"], f.accept_ticket_payload(storage_bin["version"]), headers
        )

        validate_error(response, E.ERR_GRADE_BELOW_MINIMUM, 422)

        current_ticket = get_success_data(
            api.get_deposit_ticket(ticket["id"], headers), 200
        )
        assert current_ticket["ticket_state"] == "WEIGHED"

        current_bin = get_success_data(api.get_bin(storage_bin["id"], headers), 200)
        assert current_bin["stored_bushels"] == 0


class TestNonNegotiableReceiptCannotBePledged:
    def test_no_lien_row_survives_a_pledge_of_a_non_negotiable_receipt(
        self, api, base_pre, issue_receipt
    ):
        """
        WR-0005 is a straight storage document, not a document of title that can
        change hands, so it cannot be used as collateral at all. The advance request
        does not merely fail to perfect — it never becomes a lien.

        PRD: "Only `NEGOTIABLE` receipts may ever be transferred or pledged, and any
        attempt to transfer or pledge a `NON_NEGOTIABLE` receipt is refused with
        `ERR_RECEIPT_NOT_NEGOTIABLE`."

        PRD: "The referenced receipt must be `ISSUED`, `NEGOTIABLE`, and not
        currently `PLEDGED`."

        Design: Corner/errors/pledge_of_non_negotiable_receipt_rejected
        """
        receipt = issue_receipt(
            base_pre["warehouse_id"],
            base_pre["ticket_id"],
            base_pre["depositor_id"],
            receipt_number="WR-0005",
            form="NON_NEGOTIABLE",
        )

        response = api.create_collateral_lien(
            f.collateral_lien_payload(receipt["id"], base_pre["lender_id"]),
            base_pre["lender_headers"],
        )

        validate_error(response, E.ERR_RECEIPT_NOT_NEGOTIABLE, 422)

        rows, meta = validate_paginated(
            api.list_collateral_liens(
                {"receipt_id": receipt["id"]}, base_pre["lender_headers"]
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        current = get_success_data(
            api.get_receipt(receipt["id"], base_pre["operator_headers"]), 200
        )
        assert current["encumbrance_state"] == "UNENCUMBERED"


class TestPerfectionMethodMustMatchTheMedium:
    def test_possession_cannot_perfect_an_electronic_receipt(self, api, base_full, request_lien):
        """
        Recording the advance costs the lender nothing and asks nothing of the
        method, so the request is taken. Perfection is where the method has to be
        real — and there is no paper to take possession of, so the lien stays a
        request and the receipt stays free.

        PRD: "A method mismatch — `POSSESSION` against an `ELECTRONIC` receipt, or
        `ELECTRONIC_CONTROL` against a `PAPER` one — is refused with
        `ERR_PERFECTION_METHOD_MISMATCH`; `ELECTRONIC_CONTROL` additionally requires
        the warehouse's `registry_participant` to be true, failing which the refusal
        is `ERR_REGISTRY_NOT_PARTICIPANT`."

        PRD: "**No credit is committed at this point** — recording a request costs
        the lender nothing against its line."

        Design: Corner/errors/possession_perfection_on_electronic_receipt_rejected
        """
        lien = request_lien(
            base_full["receipt_id"],
            base_full["lender_id"],
            perfection_method="POSSESSION",
        )

        response = api.perfect_lien(
            lien["id"], f.perfect_payload(), base_full["lender_headers"]
        )

        validate_error(response, E.ERR_PERFECTION_METHOD_MISMATCH, 422)

        current_lien = get_success_data(
            api.get_collateral_lien(lien["id"], base_full["lender_headers"]), 200
        )
        assert current_lien["lien_state"] == "REQUESTED"

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert receipt["encumbrance_state"] == "UNENCUMBERED"

        lender = get_success_data(
            api.get_party(base_full["lender_id"], base_full["lender_headers"]), 200
        )
        assert lender["committed_advance_cents"] == 0


class TestEncumbranceOutranksTheVoidWindow:
    def test_the_pledged_receipt_reports_the_encumbrance_not_the_stale_window(
        self, api, base_pre, issue_receipt, set_clock, request_lien
    ):
        """
        Two of the void preconditions fail at once on day 16: the receipt is pledged
        and the 72-hour window shut a fortnight ago. Precedence decides what the
        caller hears — the encumbrance check is the earlier rule, so the lender's
        interest is the stated reason and the expired window is never mentioned.

        PRD: "Checks are evaluated in the following fixed order, and the **first**
        rule violated determines the response; later rules are not evaluated and
        their errors are not reported."

        PRD: "Outstanding encumbrance — `ERR_RECEIPT_ENCUMBERED`."

        PRD: "The receipt void window — `ERR_VOID_WINDOW_EXPIRED`."

        PRD: "It requires that the receipt still be `ISSUED`, that its
        `encumbrance_state` not be `PLEDGED`, that no delivery order on the receipt
        be in `delivery_state` `REQUESTED` or `LOADED`, and that the current logical
        clock be within 72 hours of `issued_at` — a later attempt is refused with
        `ERR_VOID_WINDOW_EXPIRED`."

        Design: Corner/errors/void_of_pledged_receipt_rejected
        """
        receipt = issue_receipt(
            base_pre["warehouse_id"],
            base_pre["ticket_id"],
            base_pre["depositor_id"],
            receipt_number="WR-0004",
            medium="PAPER",
        )
        set_clock(CLOCK_DAY_16)
        lien = request_lien(
            receipt["id"], base_pre["lender_id"], perfection_method="POSSESSION"
        )
        get_success_data(
            api.perfect_lien(
                lien["id"], f.perfect_payload(), base_pre["lender_headers"]
            ),
            200,
        )

        response = api.void_receipt(
            receipt["id"],
            f.void_payload(void_reason="CLERICAL_ERROR"),
            base_pre["operator_headers"],
        )

        validate_error(response, E.ERR_RECEIPT_ENCUMBERED, 409)

        current = get_success_data(
            api.get_receipt(receipt["id"], base_pre["operator_headers"]), 200
        )
        assert_fields_equal(
            current, {"receipt_state": "ISSUED", "encumbrance_state": "PLEDGED"}
        )

        current_lien = get_success_data(
            api.get_collateral_lien(lien["id"], base_pre["lender_headers"]), 200
        )
        assert current_lien["lien_state"] == "PERFECTED"

        warehouse = get_success_data(
            api.get_warehouse(base_pre["warehouse_id"], base_pre["operator_headers"]),
            200,
        )
        assert warehouse["receipted_obligation_bushels"] == 949


class TestReportPeriodOverlap:
    def test_a_period_starting_inside_a_live_draft_period_is_refused(
        self, api, licensed_warehouse
    ):
        """
        The second filing runs from mid-August to mid-September, so it extends well
        past the first — but overlap is overlap: its start falls inside the closed
        period the draft already covers, and the draft counts because it has not
        been disposed of.

        PRD: "The period must not overlap the closed period of any other report of
        the same warehouse in `report_state` `DRAFT`, `UNDER_EXAMINATION` or
        `ACCEPTED`; an overlap is refused with `ERR_REPORT_PERIOD_OVERLAP` (HTTP
        409)."

        Design: Corner/errors/overlapping_position_report_period_rejected
        """
        warehouse = licensed_warehouse()
        headers = make_warehouse_operator_headers(warehouse["id"])
        first = get_success_data(
            api.create_position_report(
                f.position_report_payload(warehouse["id"], as_of_date="2026-08-31"),
                headers,
            ),
            201,
        )

        response = api.create_position_report(
            f.position_report_payload(
                warehouse["id"],
                period_start_date="2026-08-15",
                period_end_date="2026-09-15",
                as_of_date="2026-09-15",
            ),
            headers,
        )

        validate_error(response, E.ERR_REPORT_PERIOD_OVERLAP, 409)

        current = get_success_data(api.get_position_report(first["id"], headers), 200)
        assert current["report_state"] == "DRAFT"

        rows, meta = validate_paginated(
            api.list_position_reports({"warehouse_id": warehouse["id"]}, headers)
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1


class TestReceiptNumberUniquenessSpansTerminalStates:
    def test_a_voided_number_cannot_be_issued_again(self, api, base_full):
        """
        The void gave the bushels back to the unreceipted side and put the ticket
        back in play, so re-issuing looks natural — but the number WR-0001 is spent
        for good, because a voided document is still a document that existed.

        PRD: "`receipt_number` must be unique within the warehouse across **every**
        receipt state, including numbers already used by voided and cancelled
        receipts, and a collision is refused with `ERR_RECEIPT_NUMBER_DUPLICATE`
        (HTTP 409)."

        PRD: "A void moves `receipt_state` to `VOIDED`, zeroes `quantity_bushels`,
        and thereby removes the receipt from the warehouse's
        `receipted_obligation_bushels`; returns the source deposit ticket from
        `RECEIPTED` back to `ACCEPTED`, so the very same bushels re-enter
        `obligation_bushels` as unreceipted stock; and leaves the bin's
        `stored_bushels` completely unchanged, because voiding a receipt does not
        move grain."

        Design: Corner/errors/receipt_number_reuse_after_void_rejected
        """
        headers = base_full["operator_headers"]
        get_success_data(
            api.void_receipt(
                base_full["receipt_id"],
                f.void_payload(void_reason="CLERICAL_ERROR"),
                headers,
            ),
            200,
        )
        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )

        response = api.create_receipt(
            f.receipt_payload(
                base_full["ticket_id"],
                base_full["depositor_id"],
                warehouse["version"],
                receipt_number=BASE_RECEIPT_NUMBER,
            ),
            headers,
        )

        validate_error(response, E.ERR_RECEIPT_NUMBER_DUPLICATE, 409)

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], headers), 200
        )
        assert receipt["receipt_state"] == "VOIDED"

        ticket = get_success_data(
            api.get_deposit_ticket(base_full["ticket_id"], headers), 200
        )
        assert ticket["ticket_state"] == "ACCEPTED"

        current = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            current,
            {"receipted_obligation_bushels": 0, "obligation_bushels": 949},
        )


class TestDuplicateClaimOnTheSameReceipt:
    def test_a_second_filing_by_the_same_claimant_is_refused(
        self, api, base_full, set_clock, claims_open_warehouse, filed_claim
    ):
        """
        The first claim is live, so the depositor has already asserted everything it
        can against WR-0001; asserting a smaller amount a second time is a duplicate
        rather than an amendment, and the original is left exactly as filed.

        PRD: "A claimant may hold at most one live claim per receipt, counting claims
        in `claim_state` `FILED`, `ALLOWED` or `SETTLED`; a duplicate is refused with
        `ERR_CLAIM_DUPLICATE` (HTTP 409)."

        Design: Corner/errors/second_claim_by_same_claimant_on_same_receipt_rejected
        """
        set_clock(CLOCK_INSOLVENCY_DAY)
        claims_open_warehouse(base_full["warehouse_id"], 400)
        first = filed_claim(
            base_full["warehouse_id"],
            base_full["receipt_id"],
            base_full["depositor_id"],
            400_000,
        )

        response = api.create_indemnity_claim(
            f.indemnity_claim_payload(
                base_full["warehouse_id"],
                base_full["receipt_id"],
                base_full["depositor_id"],
                350_000,
            ),
            base_full["depositor_headers"],
        )

        validate_error(response, E.ERR_CLAIM_DUPLICATE, 409)

        current = get_success_data(
            api.get_indemnity_claim(first["id"], base_full["depositor_headers"]), 200
        )
        assert current["claim_state"] == "FILED"

        rows, meta = validate_paginated(
            api.list_indemnity_claims(
                {"receipt_id": base_full["receipt_id"]}, REGULATOR_HEADERS
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1


class TestLenderCreditLineGate:
    @pytest.fixture
    def thin_lenders_request(self, base_full, new_lender, set_clock, request_lien):
        """A 100000-cent lender's advance request against the 949-bushel receipt."""
        thin = new_lender(name="Thin Bank", credit_line_cents=100_000)
        set_clock(CLOCK_DAY_16)
        lien = request_lien(base_full["receipt_id"], thin["id"])
        return {"lender": thin, "lien": lien}

    def test_a_line_smaller_than_the_advance_limit_cannot_be_perfected_against(
        self, api, base_full, thin_lenders_request
    ):
        """
        The collateral is worth an advance limit of 290482 cents, but this lender's
        entire line is 100000 — and it is the limit, not the 250000 principal it
        actually wanted to carry, that the line must cover. Nothing is committed and
        the receipt is left for a lender who can fund it.

        PRD: "An insufficient line is refused with `ERR_CREDIT_LINE_EXCEEDED`."

        PRD: "`advance_limit_cents` is `net_collateral_cents` multiplied by
        `advance_rate_bps` and divided by ten thousand, rounded half up to whole
        cents."

        PRD: "A newly registered party starts with `committed_advance_cents` at zero
        and therefore `available_credit_cents` equal to its credit line."

        Design: Corner/errors/perfection_beyond_lender_credit_line_rejected
        """
        thin = thin_lenders_request["lender"]
        lien = thin_lenders_request["lien"]
        thin_headers = make_lender_headers(thin["id"])
        assert lien["advance_limit_cents"] == 290482

        response = api.perfect_lien(lien["id"], f.perfect_payload(), thin_headers)

        validate_error(response, E.ERR_CREDIT_LINE_EXCEEDED, 422)

        current_lien = get_success_data(
            api.get_collateral_lien(lien["id"], thin_headers), 200
        )
        assert_fields_equal(
            current_lien, {"lien_state": "REQUESTED", "advance_limit_cents": 290482}
        )

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert receipt["encumbrance_state"] == "UNENCUMBERED"

        lender = get_success_data(api.get_party(thin["id"], thin_headers), 200)
        assert_fields_equal(
            lender,
            {"committed_advance_cents": 0, "available_credit_cents": 100000},
        )


class TestDeliveryQuantityGate:
    def test_asking_for_more_than_the_receipt_holds_places_no_hold(
        self, api, base_full
    ):
        """
        The receipt is good for 949 bushels and the order asks for 1000, so there is
        nothing to book — and because the booking never happened, the bin's grain is
        still free rather than sitting under a phantom hold.

        PRD: "The requested quantity must not exceed the receipt's outstanding
        `quantity_bushels`, or the request is refused with
        `ERR_DELIVERY_EXCEEDS_RECEIPT`."

        PRD: "Booking raises the bin's `held_bushels` by `requested_bushels`, which
        is what keeps the same grain from being promised twice, and the order starts
        in `REQUESTED` with `delivered_bushels`, `delivered_grade`,
        `settlement_price_cents_per_bushel`, `loaded_at`, `settled_at`,
        `cancelled_at` and `cancellation_reason` all null."

        Design: Corner/errors/delivery_request_above_receipt_quantity_rejected
        """
        response = api.create_delivery_order(
            f.delivery_order_payload(
                base_full["receipt_id"], 1000, APPOINTMENT_START, APPOINTMENT_END
            ),
            base_full["depositor_headers"],
        )

        validate_error(response, E.ERR_DELIVERY_EXCEEDS_RECEIPT, 422)

        storage_bin = get_success_data(
            api.get_bin(base_full["bin_id"], base_full["operator_headers"]), 200
        )
        assert storage_bin["held_bushels"] == 0

        rows, meta = validate_paginated(
            api.list_delivery_orders(
                {"receipt_id": base_full["receipt_id"]},
                base_full["depositor_headers"],
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
