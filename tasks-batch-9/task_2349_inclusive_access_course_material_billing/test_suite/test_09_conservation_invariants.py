"""The two named conserved quantities under their compensating pairs: money across
a grant and its rescind, and entitlement seats across a title-change rebill that
deliberately moves money.
"""

from test_helpers import (
    AccessStatus,
    AdoptionStatus,
    BillingStatus,
    LedgerEntryType,
    LedgerReasonCode,
    OptOutRequestStatus,
    ReconciliationStatus,
    SectionIaStatus,
    assert_charge_ledger_conserved,
    assert_entitlement_seats_conserved,
    assert_ledger_append_only,
    assert_money,
    assert_ratio,
    assert_student_balance_matches_ledger,
    fixtures,
    validate_paginated,
    validate_success,
)

REPLACEMENT_TITLE = {
    "isbn": "978-0-11-000005-0",
    "title": "Economics Essentials",
    "list_price_cents": 12000,
}


class TestGrantThenRescindConservesMoney:
    """The balance may pass through 0, but it must come back to 9450 exactly."""

    @staticmethod
    def _billed_section_with_one_undecided_request(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        scenario["request_id"] = request["id"]
        return scenario

    def test_the_compensating_pair_returns_the_ledger_sum_to_its_pre_grant_value(
            self, api, bursar_officer, registrar):
        """PRD §2.7: "The compensating-pair form of the invariant matters most: if a
        charge's ledger sum was some amount before an opt-out was granted, then
        granting the opt-out and subsequently rescinding it leaves the charge's
        ledger sum at that same amount and the student's `bursar_balance_cents`
        unchanged, with exactly two additional rows — a refund of that amount
        followed by a re-charge of that amount."

        Design: Difficulty/compensating_invariant/compensating_grant_then_rescind_conserves_bursar_money
        """
        scenario = self._billed_section_with_one_undecided_request(api)
        charge_id = scenario["charge_ids"][0]
        student_id = scenario["student_ids"][0]

        before, before_meta = validate_paginated(
            api.list_charge_ledger_entries(charge_id, bursar_officer)
        )
        assert before_meta["total_count"] == 1

        fixtures.grant_opt_out(api, scenario["request_id"])

        midpoint = validate_success(api.get_charge(charge_id, bursar_officer))
        assert midpoint["billing_status"] == BillingStatus.REFUNDED.value
        assert midpoint["access_status"] == AccessStatus.REVOKED.value
        assert_money(midpoint["net_billed_cents"], 0)
        assert_money(midpoint["refunded_amount_cents"], 9450)
        student = validate_success(api.get_student(student_id, registrar))
        assert_money(student["bursar_balance_cents"], 0)

        fixtures.set_clock(api, "2026-08-27T10:00:00Z")
        rescinded = fixtures.rescind_opt_out(api, scenario["request_id"], student_id)
        assert rescinded["status"] == OptOutRequestStatus.RESCINDED.value
        assert_money(rescinded["refund_amount_cents"], 9450)
        assert_money(rescinded["recharge_amount_cents"], 9450)

        charge = validate_success(api.get_charge(charge_id, bursar_officer))
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["refunded_amount_cents"], 0)

        after, after_meta = validate_paginated(
            api.list_charge_ledger_entries(charge_id, bursar_officer)
        )
        assert after_meta["total_count"] == 3
        assert_ledger_append_only(before, after)
        assert [(entry["entry_type"], entry["reason_code"], entry["amount_cents"])
                for entry in after] == [
            (LedgerEntryType.CHARGE.value, LedgerReasonCode.INITIAL_POST.value, 9450),
            (LedgerEntryType.REFUND.value, LedgerReasonCode.OPT_OUT_REFUND.value, -9450),
            (LedgerEntryType.CHARGE.value, LedgerReasonCode.OPT_IN_RECHARGE.value, 9450),
        ]
        assert_charge_ledger_conserved(charge, after)

        student = validate_success(api.get_student(student_id, registrar))
        assert_money(student["bursar_balance_cents"], 9450)
        rows, _ = validate_paginated(
            api.list_student_ledger_entries(student_id, bursar_officer)
        )
        assert_student_balance_matches_ledger(student, rows)

    def test_the_seats_come_back_too_and_nothing_else_is_touched(self, api,
                                                                bursar_officer,
                                                                registrar):
        """PRD §2.7: "Second, granting an opt-out (which revokes a seat) and then
        rescinding it (which restores the seat) returns both
        `provisioned_access_count` and `revoked_access_count` to their pre-grant
        values."

        Design: Difficulty/compensating_invariant/compensating_grant_then_rescind_conserves_bursar_money
        """
        scenario = self._billed_section_with_one_undecided_request(api)

        fixtures.grant_opt_out(api, scenario["request_id"])
        fixtures.set_clock(api, "2026-08-27T10:00:00Z")
        fixtures.rescind_opt_out(api, scenario["request_id"], scenario["student_ids"][0])

        charge = validate_success(
            api.get_charge(scenario["charge_ids"][0], bursar_officer)
        )
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert charge["access_status"] == AccessStatus.RESTORED.value
        assert charge["access_restored_at"] == "2026-08-27T10:00:00.000Z"
        assert_money(charge["publisher_share_cents"], 8316)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["provisioned_access_count"] == 2
        assert section["revoked_access_count"] == 0
        assert_ratio(section["participation_rate"], 1.0000)
        assert section["ia_status"] == SectionIaStatus.BILLED.value
        assert_entitlement_seats_conserved(section, 2)

        # The compensation reached exactly one charge and one student.
        _, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][1], bursar_officer)
        )
        assert meta["total_count"] == 1
        peer = validate_success(
            api.get_student(scenario["student_ids"][1], registrar)
        )
        assert_money(peer["bursar_balance_cents"], 9450)


class TestRebillConservesSeatsWhileMoneyMoves:
    """Seats are pinned at 1 and 1 while the live charge is repriced downward."""

    @staticmethod
    def _refunded_and_live_charge_with_a_submitted_replacement(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")

        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        fixtures.grant_opt_out(api, request["id"])

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"], agreement["version"],
            publisher_reported_count=1, publisher_reported_amount_cents=8316,
        )

        replacement, _ = fixtures.create_priced_title(
            api, scenario["agreement_id"], ((1, 2, 6000),), **REPLACEMENT_TITLE
        )
        fixtures.set_clock(api, "2026-08-27T09:00:00Z")
        successor = fixtures.create_adoption(
            api, scenario["section_id"], replacement["id"],
            supersedes_adoption_id=scenario["adoption_id"],
        )
        fixtures.submit_adoption(api, successor["id"])

        scenario["run_id"] = run["id"]
        scenario["successor_id"] = successor["id"]
        return scenario

    def test_no_seat_is_created_or_destroyed_by_changing_the_book(self, api):
        """PRD §3.7: "`access_status` is deliberately not touched — the seat is
        conserved even though the money is not."

        Design: Difficulty/compensating_invariant/compensating_rebill_conserves_entitlement_seats_while_money_moves
        """
        scenario = self._refunded_and_live_charge_with_a_submitted_replacement(api)

        before = fixtures.read_section(api, scenario["section_id"])
        assert before["provisioned_access_count"] == 1
        assert before["revoked_access_count"] == 1
        assert_entitlement_seats_conserved(before, 2)

        approved = fixtures.approve_adoption(api, scenario["successor_id"])
        assert approved["status"] == AdoptionStatus.APPROVED.value
        assert approved["requires_rebill"] is True
        assert_money(approved["locked_list_price_cents"], 12000)

        superseded = fixtures.read_adoption(api, scenario["adoption_id"])
        assert superseded["status"] == AdoptionStatus.SUPERSEDED.value

        after = fixtures.read_section(api, scenario["section_id"])
        assert after["provisioned_access_count"] == 1
        assert after["revoked_access_count"] == 1
        assert_entitlement_seats_conserved(after, 2)
        # A rebill cannot move a participation figure.
        assert_ratio(after["participation_rate"], 0.5000)
        assert after["ia_status"] == SectionIaStatus.BILLED.value

        refunded = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert refunded["access_status"] == AccessStatus.REVOKED.value
        assert refunded["access_restored_at"] is None
        live = fixtures.read_charge(api, scenario["charge_ids"][1])
        assert live["access_status"] == AccessStatus.PROVISIONED.value
        assert live["access_restored_at"] is None

    def test_money_moves_only_on_the_charge_inside_the_rebill_scope(self, api,
                                                                   bursar_officer,
                                                                   registrar):
        """PRD §3.7: "Only charges whose `billing_status` is `POSTED` or `REBILLED`
        participate; `PARTIALLY_REFUNDED` and `REFUNDED` charges are excluded and
        keep pointing at the superseded adoption."

        Design: Difficulty/compensating_invariant/compensating_rebill_conserves_entitlement_seats_while_money_moves
        """
        scenario = self._refunded_and_live_charge_with_a_submitted_replacement(api)
        fixtures.approve_adoption(api, scenario["successor_id"])

        rebilled = fixtures.read_charge(api, scenario["charge_ids"][1])
        assert rebilled["billing_status"] == BillingStatus.REBILLED.value
        assert rebilled["rebill_count"] == 1
        assert rebilled["adoption_id"] == scenario["successor_id"]
        assert_money(rebilled["gross_price_cents"], 6300)
        assert_money(rebilled["billed_amount_cents"], 6300)
        assert_money(rebilled["net_billed_cents"], 6300)
        assert_money(rebilled["publisher_share_cents"], 5544)

        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][1], bursar_officer)
        )
        assert meta["total_count"] == 3
        assert [entry["amount_cents"] for entry in entries] == [9450, -9450, 6300]
        assert_charge_ledger_conserved(rebilled, entries)

        excluded = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert excluded["billing_status"] == BillingStatus.REFUNDED.value
        assert excluded["rebill_count"] == 0
        assert excluded["adoption_id"] == scenario["adoption_id"]
        excluded_entries, excluded_meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert excluded_meta["total_count"] == 2
        assert_money(sum(entry["amount_cents"] for entry in excluded_entries), 0)

        for index, expected in ((0, 0), (1, 6300)):
            student = validate_success(
                api.get_student(scenario["student_ids"][index], registrar)
            )
            assert_money(student["bursar_balance_cents"], expected)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.STALE.value
        run = fixtures.read_run(api, scenario["run_id"])
        # The run keeps the figures it was computed with.
        assert_money(run["gross_invoice_cents"], 8316)
