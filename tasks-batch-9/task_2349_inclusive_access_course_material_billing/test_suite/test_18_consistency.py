"""Nothing in this domain lags: the write response already carries every derived
figure, and a read taken immediately afterwards — with no clock advance in between —
agrees with it.
"""

from test_helpers import (
    AccessStatus,
    BillingStatus,
    LedgerEntryType,
    LedgerReasonCode,
    OptOutRequestStatus,
    SectionIaStatus,
    assert_charge_shape,
    assert_money,
    assert_ratio,
    fixtures,
    validate_success,
)

SINGLE_BAND = ((1, 2, 9000),)
DAY_ONE = "2026-08-24T09:00:00Z"
DAY_ONE_STAMP = "2026-08-24T09:00:00.000Z"


class TestThePostingResponseAlreadyCarriesEveryDerivedFigure:
    """One request prices, provisions, freezes the basis and moves the balances."""

    @staticmethod
    def _flagged_section_with_two_enrolments_on_day_one(api):
        catalog = fixtures.setup_catalog(api, bands=SINGLE_BAND)
        scenario = dict(catalog)
        scenario.update(fixtures.add_section(api, catalog))
        scenario.update(fixtures.enroll_roster(api, scenario["section_id"]))
        fixtures.set_clock(api, DAY_ONE)
        return scenario

    def test_the_batch_response_needs_no_second_read_and_the_reads_agree_with_it(
            self, api, bursar_officer, program_admin, registrar):
        """PRD §3.5: "On that transition the server appends a `CHARGE` ledger movement
        whose `amount_cents` equals `billed_amount_cents`, carrying `reason_code`
        `INITIAL_POST` for a batch posting and `LATE_REGISTRATION_POST` for a single
        posting of a late-registered enrollment (a single posting of a regular
        registration also carries `INITIAL_POST`); stamps `posted_at` from the logical
        clock; computes `opt_out_deadline_at`; advances `access_status`
        `NOT_PROVISIONED` → `PROVISIONED` and stamps `access_start_at`, which increments
        the section's `provisioned_access_count`; and recomputes the owning student's
        `bursar_balance_cents`."

        Design: Corner/consistency_model/consistency_immediate_post_charges_response_carries_all_derived_state
        """
        scenario = self._flagged_section_with_two_enrolments_on_day_one(api)

        charges = validate_success(
            api.post_section_charges(scenario["section_id"], bursar_officer),
            expected_status=201,
        )
        assert len(charges) == 2
        for charge in charges:
            assert_charge_shape(charge)
            assert_money(charge["gross_price_cents"], 9450)
            assert_ratio(charge["proration_pct"], 1.0000)
            assert_money(charge["billed_amount_cents"], 9450)
            assert_money(charge["net_billed_cents"], 9450)
            assert_money(charge["publisher_share_cents"], 8316)
            assert_money(charge["refunded_amount_cents"], 0)
            assert charge["billing_status"] == BillingStatus.POSTED.value
            assert charge["access_status"] == AccessStatus.PROVISIONED.value
            assert charge["posted_at"] == DAY_ONE_STAMP
            assert charge["access_start_at"] == DAY_ONE_STAMP
            assert charge["opt_out_deadline_at"] == "2026-09-04T23:59:59.999Z"
            assert charge["rebill_count"] == 0

        # No clock advance, no retry: the section read already shows the freeze.
        section = validate_success(
            api.get_section(scenario["section_id"], program_admin)
        )
        assert section["ia_status"] == SectionIaStatus.BILLED.value
        assert section["billing_basis_enrollment_count"] == 2
        assert section["first_posted_at"] == DAY_ONE_STAMP
        assert section["provisioned_access_count"] == 2
        assert_ratio(section["participation_rate"], 1.0000)

        summary = validate_success(
            api.get_section_billing_summary(scenario["section_id"], program_admin)
        )
        assert summary["charge_count"] == 2
        assert summary["posted_charge_count"] == 2
        assert summary["refunded_charge_count"] == 0
        assert_money(summary["total_net_billed_cents"], 18900)
        assert_money(summary["total_publisher_share_cents"], 16632)

        for student_id in scenario["student_ids"]:
            student = validate_success(api.get_student(student_id, registrar))
            assert_money(student["bursar_balance_cents"], 9450)

    def test_the_grant_response_already_shows_the_refund_and_the_revocation(
            self, api, bursar_officer):
        """PRD §2.9: "Several operations in this system are multi-hop: a single request
        mutates the entity named in the path and then, as a consequence, mutates
        entities two and three levels away."

        Design: Corner/consistency_model/consistency_immediate_post_charges_response_carries_all_derived_state
        """
        scenario = self._flagged_section_with_two_enrolments_on_day_one(api)
        charges = fixtures.post_section_charges(api, scenario["section_id"])

        # Filed and decided at the very instant of posting, with no clock advance.
        request = fixtures.file_opt_out(
            api, charges[0]["id"], scenario["student_ids"][0], reason_code="COST"
        )
        granted = validate_success(
            api.grant_opt_out_request(request["id"], bursar_officer)
        )
        assert granted["status"] == OptOutRequestStatus.GRANTED.value
        assert_money(granted["refund_amount_cents"], 9450)
        assert granted["decided_at"] == DAY_ONE_STAMP
        assert granted["decided_by_user_id"] == "bo-1"

        entries = fixtures.read_charge_ledger(api, charges[0]["id"])
        assert len(entries) == 2
        assert entries[0]["entry_type"] == LedgerEntryType.CHARGE.value
        assert entries[0]["reason_code"] == LedgerReasonCode.INITIAL_POST.value
        assert_money(entries[0]["amount_cents"], 9450)
        assert entries[1]["entry_type"] == LedgerEntryType.REFUND.value
        assert entries[1]["reason_code"] == LedgerReasonCode.OPT_OUT_REFUND.value
        assert_money(entries[1]["amount_cents"], -9450)

        refunded = fixtures.read_charge(api, charges[0]["id"])
        assert refunded["billing_status"] == BillingStatus.REFUNDED.value
        assert refunded["access_status"] == AccessStatus.REVOKED.value
        assert_money(refunded["net_billed_cents"],
                    sum(entry["amount_cents"] for entry in entries))
        assert_money(refunded["net_billed_cents"], 0)
        assert_money(fixtures.student_balance(api, scenario["student_ids"][0]), 0)
