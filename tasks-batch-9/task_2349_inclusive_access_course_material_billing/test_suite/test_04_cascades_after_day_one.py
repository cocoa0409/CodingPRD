"""Three different roots — a bursar grant, a registrar drop and a faculty title
change — each walking their own hop chain out to the pricing agreement.
"""

from test_helpers import (
    AccessStatus,
    AdoptionStatus,
    BillingStatus,
    EnrollmentStatus,
    LedgerEntryType,
    LedgerReasonCode,
    ReconciliationRunStatus,
    ReconciliationStatus,
    SectionIaStatus,
    assert_entitlement_seats_conserved,
    assert_money,
    assert_ratio,
    fixtures,
    validate_paginated,
    validate_success,
)

THREE_STUDENTS = (("S-1001", "Ada Lin"), ("S-1002", "Ben Ortiz"), ("S-1003", "Cara Wu"))


class TestOptOutGrantCascade:
    """The grant that carries the section across the participation threshold."""

    @staticmethod
    def _section_with_one_grant_and_a_pending_second(api):
        """Three charges at 7875, one already refunded, a computed run, one pending."""
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z", roster=THREE_STUDENTS,
        )

        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        first = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        fixtures.grant_opt_out(api, first["id"])

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"], agreement["version"],
            publisher_reported_count=2, publisher_reported_amount_cents=13860,
        )

        fixtures.set_clock(api, "2026-08-28T10:00:00Z")
        second = fixtures.file_opt_out(
            api, scenario["charge_ids"][1], scenario["student_ids"][1], "ALTERNATE_SOURCE"
        )

        scenario["first_request_id"] = first["id"]
        scenario["second_request_id"] = second["id"]
        scenario["run_id"] = run["id"]
        scenario["run"] = run
        scenario["agreement_version_before_trigger"] = fixtures.read_agreement(
            api, scenario["agreement_id"]
        )["version"]
        return scenario

    def test_grant_refunds_the_charge_and_revokes_its_access_seat(self, api,
                                                                 bursar_officer):
        """PRD §3.6: "Hop one refunds the charge and revokes its access:
        `billing_status` moves to `REFUNDED` from either `POSTED` or `REBILLED`,
        `refunded_amount_cents` takes on (or, from `REBILLED`, grows by) the
        pre-refund net, a `REFUND` ledger movement with `reason_code`
        `OPT_OUT_REFUND` is appended for the negative of that amount so the
        charge's `net_billed_cents` becomes 0, `access_status` moves from
        `PROVISIONED` or `RESTORED` to `REVOKED` with `access_revoked_at` stamped
        and the learning-management-system entitlement withdrawn, and the
        student's `bursar_balance_cents` is recomputed."

        Design: Difficulty/transitive_cascade/cascade_opt_out_grant_four_hops_to_at_risk_and_stale_reconciliation
        """
        scenario = self._section_with_one_grant_and_a_pending_second(api)

        granted = validate_success(
            api.grant_opt_out_request(scenario["second_request_id"], bursar_officer)
        )
        assert_money(granted["refund_amount_cents"], 7875)
        assert granted["decided_by_user_id"] == "bo-1"

        charge = fixtures.read_charge(api, scenario["charge_ids"][1])
        assert charge["billing_status"] == BillingStatus.REFUNDED.value
        assert_money(charge["refunded_amount_cents"], 7875)
        assert_money(charge["net_billed_cents"], 0)
        assert_money(charge["publisher_share_cents"], 0)
        assert charge["access_status"] == AccessStatus.REVOKED.value
        assert charge["access_revoked_at"] == "2026-08-28T10:00:00.000Z"

    def test_the_refund_row_zeroes_both_the_charge_and_the_student_balance(
            self, api, bursar_officer, registrar):
        """PRD §2.7: "For every `Student`, the stored `bursar_balance_cents`
        equals the sum of `amount_cents` over every `LedgerEntry` bearing that
        student's `student_id`."

        Design: Difficulty/transitive_cascade/cascade_opt_out_grant_four_hops_to_at_risk_and_stale_reconciliation
        """
        scenario = self._section_with_one_grant_and_a_pending_second(api)

        fixtures.grant_opt_out(api, scenario["second_request_id"])

        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][1], bursar_officer)
        )
        assert meta["total_count"] == 2
        refunds = [entry for entry in entries
                   if entry["entry_type"] == LedgerEntryType.REFUND.value]
        assert len(refunds) == 1
        assert refunds[0]["reason_code"] == LedgerReasonCode.OPT_OUT_REFUND.value
        assert_money(refunds[0]["amount_cents"], -7875)
        assert_money(sum(entry["amount_cents"] for entry in entries), 0)

        student = validate_success(
            api.get_student(scenario["student_ids"][1], registrar)
        )
        assert_money(student["bursar_balance_cents"], 0)

    def test_second_grant_drives_the_section_below_the_participation_threshold(
            self, api):
        """PRD §3.6: "Hop two, a consequence of that revocation, recomputes the
        section's `provisioned_access_count` (down by one), `revoked_access_count`
        (up by one), `opted_out_count` and `participation_rate`, and flips the
        section `BILLED` → `AT_RISK` if the recomputed rate fell below one half."

        Design: Difficulty/transitive_cascade/cascade_opt_out_grant_four_hops_to_at_risk_and_stale_reconciliation
        """
        scenario = self._section_with_one_grant_and_a_pending_second(api)

        before = fixtures.read_section(api, scenario["section_id"])
        assert before["ia_status"] == SectionIaStatus.BILLED.value
        assert_ratio(before["participation_rate"], 0.6667)

        fixtures.grant_opt_out(api, scenario["second_request_id"])

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 3
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 2
        assert section["opted_out_count"] == 2
        assert_ratio(section["participation_rate"], 0.3333)
        assert section["ia_status"] == SectionIaStatus.AT_RISK.value
        assert_entitlement_seats_conserved(section, 3)

    def test_cascade_tail_staleifies_the_agreement_and_leaves_the_run_frozen(
            self, api):
        """PRD §2.9: "Four cascades share a common tail: after an opt-out grant,
        an opt-out rescind, an enrollment drop, or a title-change rebill, the
        section's counters and participation rate are recomputed, the section's
        `ia_status` may flip between `BILLED` and `AT_RISK`, and finally the
        `reconciliation_status` of the `PublisherAgreement` that prices the
        affected charge moves from `COMPUTED` or `DISPUTED` to `STALE`."

        Design: Difficulty/transitive_cascade/cascade_opt_out_grant_four_hops_to_at_risk_and_stale_reconciliation
        """
        scenario = self._section_with_one_grant_and_a_pending_second(api)

        fixtures.grant_opt_out(api, scenario["second_request_id"])

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.STALE.value
        assert agreement["version"] == scenario["agreement_version_before_trigger"] + 1

        # The run keeps the figures it computed; the tail never rewrites them.
        run = fixtures.read_run(api, scenario["run_id"])
        assert run["status"] == ReconciliationRunStatus.COMPUTED.value
        assert run["billable_count"] == 2
        assert_money(run["gross_invoice_cents"], 13860)
        assert run["opted_out_count"] == 1

        untouched = fixtures.read_charge(api, scenario["charge_ids"][2])
        assert untouched["billing_status"] == BillingStatus.POSTED.value
        assert_money(untouched["net_billed_cents"], 7875)
        assert untouched["access_status"] == AccessStatus.PROVISIONED.value


class TestDropProrationCascade:
    """A drop 28 days into a 110-day term retains 0.2545 and refunds the rest."""

    @staticmethod
    def _reconciled_section_on_the_day_of_a_late_drop(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            scenario["agreement_version"],
            publisher_reported_count=2, publisher_reported_amount_cents=16133,
        )
        fixtures.set_clock(api, "2026-09-21T11:00:00Z")
        scenario["run_id"] = run["id"]
        scenario["run"] = run
        return scenario

    def test_late_drop_lands_on_partially_refunded_with_a_live_balance(self, api,
                                                                      registrar):
        """PRD §3.7: "Otherwise the system computes a retained share by counting
        the days from the term's `term_start_date` to `dropped_on`, dividing by
        `total_term_days` and rounding half up to 4 decimal places; multiplies the
        charge's `net_billed_cents` by one minus that rounded retained share;
        rounds half up to whole cents; and caps the result at `net_billed_cents`
        so the institution never over-refunds."

        Design: Difficulty/transitive_cascade/cascade_drop_partial_refund_three_hops_and_stale_reconciliation
        """
        scenario = self._reconciled_section_on_the_day_of_a_late_drop(api)

        dropped = validate_success(
            api.drop_enrollment(scenario["enrollment_ids"][0],
                                {"dropped_on": "2026-09-21"}, registrar)
        )
        assert dropped["status"] == EnrollmentStatus.DROPPED.value
        assert dropped["dropped_on"] == "2026-09-21"

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        # Retained 28/110 = 0.2545, so the refund is neither 0 nor the whole 9450.
        assert charge["billing_status"] == BillingStatus.PARTIALLY_REFUNDED.value
        assert_money(charge["refunded_amount_cents"], 7045)
        assert_money(charge["net_billed_cents"], 2405)
        assert charge["access_status"] == AccessStatus.REVOKED.value
        assert charge["access_revoked_at"] == "2026-09-21T11:00:00.000Z"

    def test_drop_proration_row_moves_the_balance_and_the_publisher_share(
            self, api, bursar_officer, registrar):
        """PRD §3.7: "Hop two, because a charge was refunded, appends a `REFUND`
        ledger movement with `reason_code` `DROP_PRORATION` and recomputes the
        charge's `net_billed_cents` and the student's `bursar_balance_cents`."

        Design: Difficulty/transitive_cascade/cascade_drop_partial_refund_three_hops_and_stale_reconciliation
        """
        scenario = self._reconciled_section_on_the_day_of_a_late_drop(api)

        fixtures.drop_enrollment(api, scenario["enrollment_ids"][0], "2026-09-21")

        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 2
        refunds = [entry for entry in entries
                   if entry["reason_code"] == LedgerReasonCode.DROP_PRORATION.value]
        assert len(refunds) == 1
        assert refunds[0]["entry_type"] == LedgerEntryType.REFUND.value
        assert_money(refunds[0]["amount_cents"], -7045)
        assert_money(sum(entry["amount_cents"] for entry in entries), 2405)

        student = validate_success(
            api.get_student(scenario["student_ids"][0], registrar)
        )
        assert_money(student["bursar_balance_cents"], 2405)

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        # round_half_up(2405 * 0.88) = 2116, down from 8316 on the full charge.
        assert_money(charge["publisher_share_cents"], 2116)

    def test_dropped_student_leaves_the_denominator_so_the_section_stays_billed(
            self, api):
        """PRD §3.5: "After any event that moves a section's
        `provisioned_access_count` or `enrolled_count` — posting, opt-out grant,
        opt-out rescind, enrollment drop, title-change rebill — the section's
        `participation_rate` is recomputed as `provisioned_access_count` divided
        by `enrolled_count`, rounded half up to 4 decimal places, or as 0.0000
        when `enrolled_count` is zero."

        Design: Difficulty/transitive_cascade/cascade_drop_partial_refund_three_hops_and_stale_reconciliation
        """
        scenario = self._reconciled_section_on_the_day_of_a_late_drop(api)

        fixtures.drop_enrollment(api, scenario["enrollment_ids"][0], "2026-09-21")

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 1
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 1
        assert_ratio(section["participation_rate"], 1.0000)
        assert section["ia_status"] == SectionIaStatus.BILLED.value

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.STALE.value

        run = fixtures.read_run(api, scenario["run_id"])
        assert run["status"] == ReconciliationRunStatus.COMPUTED.value
        assert_money(run["gross_invoice_cents"], 16632)

        sibling = fixtures.read_charge(api, scenario["charge_ids"][1])
        assert sibling["billing_status"] == BillingStatus.POSTED.value
        assert_money(sibling["net_billed_cents"], 9450)
        assert_money(sibling["publisher_share_cents"], 8316)


class TestTitleChangeRebillCascade:
    """Swapping to a cheaper title rewrites the money and conserves every seat."""

    CHEAPER_TITLE = {
        "isbn": "978-0-11-000005-0",
        "title": "Economics Essentials",
        "list_price_cents": 12000,
    }

    @classmethod
    def _billed_section_with_a_submitted_replacement(cls, api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        replacement, _ = fixtures.create_priced_title(
            api, scenario["agreement_id"], ((1, 2, 6000),), **cls.CHEAPER_TITLE
        )
        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            scenario["agreement_version"],
            publisher_reported_count=2, publisher_reported_amount_cents=16133,
        )

        # 2026-08-26 is past adoption_deadline_date 2026-07-15, which a
        # superseding adoption is expressly exempt from.
        fixtures.set_clock(api, "2026-08-26T09:00:00Z")
        superseding = fixtures.create_adoption(
            api, scenario["section_id"], replacement["id"],
            supersedes_adoption_id=scenario["adoption_id"],
        )
        fixtures.submit_adoption(api, superseding["id"])

        scenario["replacement_title"] = replacement
        scenario["superseding_id"] = superseding["id"]
        scenario["run_id"] = run["id"]
        return scenario

    def test_approving_the_replacement_supersedes_and_rebills_every_live_charge(
            self, api, program_admin, bursar_officer):
        """PRD §3.7: "It appends a `REBILL_CHARGE` movement with `reason_code`
        `TITLE_CHANGE_REBILL` for the positive of that new amount, repoints the
        charge's `adoption_id` to the superseding adoption, overwrites
        `gross_price_cents` and `billed_amount_cents`, sets `billing_status` to
        `REBILLED`, and increments `rebill_count` by 1."

        Design: Difficulty/transitive_cascade/cascade_title_change_rebill_four_hops_after_billing
        """
        scenario = self._billed_section_with_a_submitted_replacement(api)

        approved = validate_success(
            api.approve_adoption(scenario["superseding_id"], program_admin)
        )
        assert approved["status"] == AdoptionStatus.APPROVED.value
        assert_money(approved["locked_list_price_cents"], 12000)
        assert approved["requires_rebill"] is True

        superseded = fixtures.read_adoption(api, scenario["adoption_id"])
        assert superseded["status"] == AdoptionStatus.SUPERSEDED.value

        for charge_id in scenario["charge_ids"]:
            charge = fixtures.read_charge(api, charge_id)
            assert charge["adoption_id"] == scenario["superseding_id"]
            # round(6000 * 1.05) = 6300, under both the 7200 cap and the floor.
            assert_money(charge["gross_price_cents"], 6300)
            assert_money(charge["billed_amount_cents"], 6300)
            assert_money(charge["net_billed_cents"], 6300)
            assert charge["billing_status"] == BillingStatus.REBILLED.value
            assert charge["rebill_count"] == 1

        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 3
        assert_money(sum(entry["amount_cents"] for entry in entries), 6300)
        by_type = {entry["entry_type"]: entry for entry in entries}
        assert_money(by_type[LedgerEntryType.CHARGE.value]["amount_cents"], 9450)
        credit = by_type[LedgerEntryType.REBILL_CREDIT.value]
        assert_money(credit["amount_cents"], -9450)
        assert credit["reason_code"] == LedgerReasonCode.TITLE_CHANGE_REBILL.value
        recharge = by_type[LedgerEntryType.REBILL_CHARGE.value]
        assert_money(recharge["amount_cents"], 6300)
        assert recharge["reason_code"] == LedgerReasonCode.TITLE_CHANGE_REBILL.value

    def test_rebill_prices_against_the_frozen_basis_and_preserves_proration(
            self, api, registrar):
        """PRD §3.7: "For each participating charge the system captures the
        current `net_billed_cents`, appends a `REBILL_CREDIT` ledger movement
        with `reason_code` `TITLE_CHANGE_REBILL` for the negative of that amount,
        then prices the new title using the three-step rule of §3.5 against the
        section's frozen `billing_basis_enrollment_count` — never the live
        `enrolled_count` — and multiplies the resulting new gross by the charge's
        existing `proration_pct`, which is preserved untouched, rounding half up
        to whole cents."

        Design: Difficulty/transitive_cascade/cascade_title_change_rebill_four_hops_after_billing
        """
        scenario = self._billed_section_with_a_submitted_replacement(api)

        fixtures.approve_adoption(api, scenario["superseding_id"])

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["billing_basis_enrollment_count"] == 2

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert_ratio(charge["proration_pct"], 1.0000)
        # round_half_up(6300 * 0.88) = 5544.
        assert_money(charge["publisher_share_cents"], 5544)

        for student_id in scenario["student_ids"]:
            student = validate_success(api.get_student(student_id, registrar))
            assert_money(student["bursar_balance_cents"], 6300)

    def test_rebill_conserves_every_seat_while_the_money_moves(self, api):
        """PRD §2.7: "First, a title-change rebill repoints charges and rewrites
        money but must leave `provisioned_access_count` and the section's charge
        count unchanged — no seat is created or destroyed by changing which book
        the seat entitles the student to."

        Design: Difficulty/transitive_cascade/cascade_title_change_rebill_four_hops_after_billing
        """
        scenario = self._billed_section_with_a_submitted_replacement(api)

        before = fixtures.read_section(api, scenario["section_id"])
        assert before["provisioned_access_count"] == 2
        assert before["revoked_access_count"] == 0
        assert_entitlement_seats_conserved(before, 2)

        fixtures.approve_adoption(api, scenario["superseding_id"])

        after = fixtures.read_section(api, scenario["section_id"])
        assert after["provisioned_access_count"] == 2
        assert after["revoked_access_count"] == 0
        assert_ratio(after["participation_rate"], 1.0000)
        assert after["ia_status"] == SectionIaStatus.BILLED.value
        assert_entitlement_seats_conserved(after, 2)

        for charge_id in scenario["charge_ids"]:
            charge = fixtures.read_charge(api, charge_id)
            assert charge["access_status"] == AccessStatus.PROVISIONED.value

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.STALE.value
