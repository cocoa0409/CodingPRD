"""Endpoint-shaped behaviour: the fifteen-field computed billing summary with its two
tier bases side by side, the skip-based batch posting endpoint, the suspend action's
forward-only reach, and the charge as the join point of three server-derived parents.
"""

from test_helpers import (
    AccessStatus,
    AdoptionStatus,
    ApiErrorId,
    BILLING_SUMMARY_FIELDS,
    BillingStatus,
    EnrollmentStatus,
    LedgerEntryType,
    LedgerReasonCode,
    PublisherAgreementStatus,
    ReconciliationRunStatus,
    ReconciliationStatus,
    SectionIaStatus,
    assert_billing_summary_shape,
    assert_charge_shape,
    assert_ledger_entry_shape,
    assert_money,
    assert_ratio,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

SINGLE_BAND = ((1, 2, 9000),)
BAND_BOUNDARY_AT_THREE = ((1, 3, 9000), (4, None, 7500))
SECOND_SECTION = {"section_number": "002"}
THIRD_SECTION = {"section_number": "003", "instructor_user_id": "fac-3"}
SUSPEND_NOTE = "Publisher missed the day-one delivery SLA for the term."


class TestBillingSummaryIsAPurelyComputedRead:
    """Two tier bases on one section: the frozen posting basis and the census basis."""

    @staticmethod
    def _billed_section_with_a_late_arrival_and_a_granted_opt_out(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-05T00:00:00Z")

        newcomer = fixtures.create_student(api, "S-1003", "Cara Wu")
        fixtures.set_clock(api, "2026-08-26T09:00:00Z")
        enrollment = fixtures.create_enrollment(
            api, scenario["section_id"], newcomer["id"], "2026-08-26"
        )
        late_charge = fixtures.post_single_charge(api, enrollment["id"])

        fixtures.set_clock(api, "2026-08-27T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        fixtures.grant_opt_out(api, request["id"])
        fixtures.set_clock(api, "2026-08-27T11:00:00Z")

        scenario["late_charge"] = late_charge
        return scenario

    def test_the_two_bases_diverge_on_one_section_and_the_rollups_follow_the_money(
            self, api, program_admin):
        """PRD §3.5: "It returns the `section_id`, the `ia_status`, the frozen
        `billing_basis_enrollment_count`, `tier_basis_posting_count` (the production
        basis — the frozen count actually used for pricing), `tier_basis_census_count`
        (the audit basis — the number of enrollments on the section whose
        `enrolled_on` is on or before the term's `census_date` and which are either
        still `ENROLLED` or whose `dropped_on` is later than the census date),
        `gross_per_student_posting_cents` and `gross_per_student_census_cents` (the
        per-student price the three-step pricing rule yields under each of those two
        bases), `charge_count`, `posted_charge_count`, `refunded_charge_count`,
        `total_net_billed_cents`, `total_publisher_share_cents`,
        `provisioned_access_count`, `revoked_access_count` and `participation_rate`."

        Design: Corner/endpoints/endpoint_billing_summary_computed_read_returns_all_fifteen_fields
        """
        scenario = self._billed_section_with_a_late_arrival_and_a_granted_opt_out(api)

        summary = validate_success(
            api.get_section_billing_summary(scenario["section_id"], program_admin)
        )
        assert_billing_summary_shape(summary)
        assert len(summary) == len(BILLING_SUMMARY_FIELDS)

        assert summary["section_id"] == scenario["section_id"]
        assert summary["ia_status"] == SectionIaStatus.BILLED.value
        assert summary["billing_basis_enrollment_count"] == 2
        # The frozen basis 2 selects band [1,2]; the census basis 3 selects [3,null].
        assert summary["tier_basis_posting_count"] == 2
        assert summary["tier_basis_census_count"] == 3
        assert_money(summary["gross_per_student_posting_cents"], 9450)
        assert_money(summary["gross_per_student_census_cents"], 7875)

        assert summary["charge_count"] == 3
        assert summary["posted_charge_count"] == 2
        assert summary["refunded_charge_count"] == 1
        # The refunded charge counts as a row but contributes no money.
        assert_money(summary["total_net_billed_cents"], 18900)
        assert_money(summary["total_publisher_share_cents"], 16632)

        assert summary["provisioned_access_count"] == 2
        assert summary["revoked_access_count"] == 1
        assert_ratio(summary["participation_rate"], 0.6667)

        # The late arrival was priced at the frozen basis, not at the live count 3.
        assert_money(scenario["late_charge"]["gross_price_cents"], 9450)
        assert_ratio(scenario["late_charge"]["proration_pct"], 1.0000)
        assert_money(scenario["late_charge"]["billed_amount_cents"], 9450)

    def test_the_three_permitted_roles_get_the_same_object_and_nothing_mutates(
            self, api, program_admin, bursar_officer, compliance_officer):
        """PRD §3.5: "A `ProgramAdmin`, `BursarOfficer` or `ComplianceOfficer` may
        pull a purely derived, no-mutation summary of a section that exposes both
        valid tier bases side by side."

        Design: Corner/endpoints/endpoint_billing_summary_computed_read_returns_all_fifteen_fields
        """
        scenario = self._billed_section_with_a_late_arrival_and_a_granted_opt_out(api)
        before = fixtures.section_version(api, scenario["section_id"])

        by_admin = validate_success(
            api.get_section_billing_summary(scenario["section_id"], program_admin)
        )
        by_bursar = validate_success(
            api.get_section_billing_summary(scenario["section_id"], bursar_officer)
        )
        by_compliance = validate_success(
            api.get_section_billing_summary(scenario["section_id"], compliance_officer)
        )
        assert by_admin == by_bursar
        assert by_bursar == by_compliance

        assert fixtures.section_version(api, scenario["section_id"]) == before


class TestBatchPostingSkipsRatherThanFails:
    """The batch sweeps what is billable and silently steps over what is not."""

    @staticmethod
    def _billed_section_with_a_dropped_charge_and_two_uncharged_arrivals(api):
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-05T00:00:00Z", bands=BAND_BOUNDARY_AT_THREE,
            roster=fixtures.DEFAULT_STUDENTS[:3],
        )

        fixtures.set_clock(api, "2026-08-26T08:00:00Z")
        fixtures.drop_enrollment(api, scenario["enrollment_ids"][1], "2026-08-26")

        # Created in the reverse of their external_id order.
        eli = fixtures.create_student(api, "S-1005", "Eli Park")
        dana = fixtures.create_student(api, "S-1004", "Dana Ek")
        eli_enrollment = fixtures.create_enrollment(
            api, scenario["section_id"], eli["id"], "2026-08-26"
        )
        dana_enrollment = fixtures.create_enrollment(
            api, scenario["section_id"], dana["id"], "2026-08-26"
        )
        fixtures.set_clock(api, "2026-08-28T09:00:00Z")

        scenario["eli_id"] = eli["id"]
        scenario["dana_id"] = dana["id"]
        scenario["eli_enrollment_id"] = eli_enrollment["id"]
        scenario["dana_enrollment_id"] = dana_enrollment["id"]
        scenario["dropped_enrollment_id"] = scenario["enrollment_ids"][1]
        return scenario

    def test_only_the_two_uncharged_arrivals_are_posted_in_the_stated_order(
            self, api, program_admin):
        """PRD §3.5: "The batch form, available to a `BursarOfficer` or a
        `ProgramAdmin`, sweeps the whole section on day one: it creates one charge for
        every enrolled student who does not yet carry a charge on the section's
        currently approved adoption, processing them in order of the enrollment's
        `enrolled_on` ascending with ties broken by the student's `external_id`
        ascending."

        Design: Corner/endpoints/endpoint_bulk_post_charges_skips_charged_and_dropped_enrollments
        """
        scenario = self._billed_section_with_a_dropped_charge_and_two_uncharged_arrivals(api)

        posted = fixtures.post_section_charges(api, scenario["section_id"],
                                              program_admin)
        assert len(posted) == 2
        assert posted[0]["student_id"] == scenario["dana_id"]
        assert posted[1]["student_id"] == scenario["eli_id"]

        for charge in posted:
            assert_charge_shape(charge)
            assert charge["billing_status"] == BillingStatus.POSTED.value
            assert charge["access_status"] == AccessStatus.PROVISIONED.value
            # The frozen basis 3 still selects band [1,3]; the live count 4 would
            # have selected [4,null] at 7875.
            assert_money(charge["gross_price_cents"], 9450)
            assert_ratio(charge["proration_pct"], 1.0000)
            assert_money(charge["billed_amount_cents"], 9450)
            assert_money(charge["net_billed_cents"], 9450)
            assert_money(charge["publisher_share_cents"], 8316)
            assert charge["posted_at"] == "2026-08-28T09:00:00.000Z"
            assert charge["opt_out_deadline_at"] == "2026-09-04T23:59:59.999Z"

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["billing_basis_enrollment_count"] == 3
        assert section["first_posted_at"] == "2026-08-24T09:00:00.000Z"
        assert section["ia_status"] == SectionIaStatus.BILLED.value
        assert section["enrolled_count"] == 4
        assert section["provisioned_access_count"] == 4
        assert section["revoked_access_count"] == 1
        assert_ratio(section["participation_rate"], 1.0000)

    def test_the_skipped_rows_are_untouched_and_a_second_sweep_has_nothing_left(
            self, api, bursar_officer, program_admin):
        """PRD §3.5: "If no such uncharged enrolled student exists — because every
        enrolled student is already charged, or because the section has no enrolled
        student at all — the request is rejected with `ERR_NO_BILLABLE_CHARGES`."

        Design: Corner/endpoints/endpoint_bulk_post_charges_skips_charged_and_dropped_enrollments
        """
        scenario = self._billed_section_with_a_dropped_charge_and_two_uncharged_arrivals(api)
        fixtures.post_section_charges(api, scenario["section_id"])

        response = api.post_section_charges(scenario["section_id"], program_admin)
        validate_error(response, ApiErrorId.NO_BILLABLE_CHARGES.value)

        # The already-charged row was skipped, not rewritten.
        untouched = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert untouched["billing_status"] == BillingStatus.POSTED.value
        assert untouched["posted_at"] == "2026-08-24T09:00:00.000Z"
        _, ledger_meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert ledger_meta["total_count"] == 1

        # The dropped enrollment gained no second charge.
        dropped_charges, dropped_meta = validate_paginated(
            api.list_enrollment_charges(scenario["dropped_enrollment_id"],
                                       bursar_officer)
        )
        assert dropped_meta["total_count"] == 1
        assert dropped_charges[0]["billing_status"] == BillingStatus.REFUNDED.value
        assert fixtures.read_enrollment(api, scenario["dropped_enrollment_id"])[
            "status"] == EnrollmentStatus.DROPPED.value

        summary = fixtures.read_billing_summary(api, scenario["section_id"])
        assert summary["charge_count"] == 5
        assert summary["posted_charge_count"] == 4
        assert summary["refunded_charge_count"] == 1
        assert_money(summary["total_net_billed_cents"], 37800)
        assert_money(summary["total_publisher_share_cents"], 33264)


class TestSuspensionIsForwardLookingOnly:
    """Three future operations stop; the past and the settlement path continue."""

    @staticmethod
    def _two_flagged_sections_one_submitted_adoption_and_one_posted_charge(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", bands=SINGLE_BAND
        )
        billed = fixtures.add_section(api, catalog)
        flagged = fixtures.add_section(api, catalog, section_overrides=SECOND_SECTION,
                                       instructor_user_id="fac-2")
        pending = fixtures.create_section(api, catalog["term_id"], **THIRD_SECTION)
        pending_adoption = fixtures.create_adoption(
            api, pending["id"], catalog["title_id"], pending["version"],
            instructor_user_id="fac-3",
        )
        fixtures.submit_adoption(api, pending_adoption["id"], "fac-3")

        first = fixtures.create_student(api, "S-1001", "Ada Lin")
        second = fixtures.create_student(api, "S-1002", "Ben Ortiz")
        fixtures.set_clock(api, "2026-08-24T08:00:00Z")
        fixtures.create_enrollment(api, billed["section_id"], first["id"], "2026-08-24")
        uncharged = fixtures.create_enrollment(
            api, flagged["section_id"], second["id"], "2026-08-24"
        )

        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        charges = fixtures.post_section_charges(api, billed["section_id"])
        agreement = fixtures.read_agreement(api, catalog["agreement_id"])
        fixtures.set_clock(api, "2026-08-25T09:00:00Z")

        return {
            "term_id": catalog["term_id"],
            "agreement_id": catalog["agreement_id"],
            "agreement_version": agreement["version"],
            "billed_section_id": billed["section_id"],
            "flagged_section_id": flagged["section_id"],
            "uncharged_enrollment_id": uncharged["id"],
            "pending_adoption_id": pending_adoption["id"],
            "charge_id": charges[0]["id"],
        }

    def test_the_three_named_operations_stop_the_moment_the_agreement_is_suspended(
            self, api, program_admin, bursar_officer):
        """PRD §3.2: "From the moment an agreement is suspended, three operations
        touching any of its titles are rejected with `ERR_AGREEMENT_NOT_ACTIVE`:
        approving an adoption of one of its titles, flagging a section for inclusive
        access under one of its titles, and posting charges — whether the batch form
        or the single-enrollment form — on a section priced by one of its titles."

        Design: Corner/endpoints/endpoint_action_suspend_agreement_stops_new_billing_but_not_reconciliation
        """
        scenario = self._two_flagged_sections_one_submitted_adoption_and_one_posted_charge(api)

        suspended = validate_success(
            api.suspend_agreement(scenario["agreement_id"],
                                 factories.suspend_payload(SUSPEND_NOTE),
                                 program_admin)
        )
        assert suspended["status"] == PublisherAgreementStatus.SUSPENDED.value
        assert suspended["suspend_reason_note"] == SUSPEND_NOTE
        assert suspended["version"] == scenario["agreement_version"] + 1
        # The two state dimensions are disjoint.
        assert suspended["reconciliation_status"] == \
            ReconciliationStatus.NOT_STARTED.value

        validate_error(
            api.post_section_charges(scenario["flagged_section_id"], bursar_officer),
            ApiErrorId.AGREEMENT_NOT_ACTIVE.value,
        )
        validate_error(
            api.post_enrollment_charge(scenario["uncharged_enrollment_id"],
                                      bursar_officer),
            ApiErrorId.AGREEMENT_NOT_ACTIVE.value,
        )
        validate_error(
            api.approve_adoption(scenario["pending_adoption_id"], program_admin),
            ApiErrorId.AGREEMENT_NOT_ACTIVE.value,
        )

        still_flagged = fixtures.read_section(api, scenario["flagged_section_id"])
        assert still_flagged["ia_status"] == SectionIaStatus.FLAGGED.value
        assert still_flagged["billing_basis_enrollment_count"] is None
        assert fixtures.read_adoption(api, scenario["pending_adoption_id"])["status"] \
            == AdoptionStatus.SUBMITTED.value

    def test_a_suspended_publisher_still_gets_its_final_invoice_checked(
            self, api, program_admin, bursar_officer):
        """PRD §2.8: "A suspended agreement can still be reconciled and settled,
        which is precisely what happens when a publisher relationship ends mid-term."

        Design: Corner/endpoints/endpoint_action_suspend_agreement_stops_new_billing_but_not_reconciliation
        """
        scenario = self._two_flagged_sections_one_submitted_adoption_and_one_posted_charge(api)
        suspended = validate_success(
            api.suspend_agreement(scenario["agreement_id"],
                                 factories.suspend_payload(SUSPEND_NOTE),
                                 program_admin)
        )

        run = validate_success(
            api.create_reconciliation_run(
                factories.reconciliation_run_payload(
                    scenario["agreement_id"], scenario["term_id"],
                    suspended["version"], publisher_reported_count=1,
                    publisher_reported_amount_cents=8316,
                ),
                program_admin,
            ),
            expected_status=201,
        )
        assert run["status"] == ReconciliationRunStatus.COMPUTED.value
        assert run["billable_count"] == 1
        assert_money(run["gross_invoice_cents"], 8316)
        assert_money(run["rebate_cents"], 0)
        assert_money(run["settlement_amount_cents"], 8316)
        assert run["count_variance"] == 0
        assert_money(run["variance_cents"], 0)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["status"] == PublisherAgreementStatus.SUSPENDED.value
        assert agreement["reconciliation_status"] == \
            ReconciliationStatus.COMPUTED.value

        # Backward-looking state is untouched by the suspension.
        charge = fixtures.read_charge(api, scenario["charge_id"])
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["publisher_share_cents"], 8316)
        assert charge["access_status"] == AccessStatus.PROVISIONED.value
        _, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_id"], bursar_officer)
        )
        assert meta["total_count"] == 1


class TestTheChargeIsAJoinPointOfThreeDerivedParents:
    """Every reverse filter finds the charge exactly once; the sibling is excluded."""

    @staticmethod
    def _two_flagged_sections_each_with_one_charged_student(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", bands=SINGLE_BAND
        )
        first_section = fixtures.add_section(api, catalog)
        second_section = fixtures.add_section(
            api, catalog, section_overrides=SECOND_SECTION, instructor_user_id="fac-2"
        )

        first = fixtures.create_student(api, "S-1001", "Ada Lin")
        second = fixtures.create_student(api, "S-1002", "Ben Ortiz")
        fixtures.set_clock(api, "2026-08-24T08:00:00Z")
        first_enrollment = fixtures.create_enrollment(
            api, first_section["section_id"], first["id"], "2026-08-24"
        )
        second_enrollment = fixtures.create_enrollment(
            api, second_section["section_id"], second["id"], "2026-08-24"
        )

        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        first_charges = fixtures.post_section_charges(api, first_section["section_id"])
        second_charges = fixtures.post_section_charges(api, second_section["section_id"])

        return {
            "first_student_id": first["id"],
            "second_student_id": second["id"],
            "first_enrollment_id": first_enrollment["id"],
            "second_enrollment_id": second_enrollment["id"],
            "first_adoption_id": first_section["adoption_id"],
            "second_adoption_id": second_section["adoption_id"],
            "first_charge_id": first_charges[0]["id"],
            "second_charge_id": second_charges[0]["id"],
        }

    def test_the_three_parents_were_derived_by_the_server_and_every_filter_agrees(
            self, api, program_admin, bursar_officer, registrar):
        """PRD §3.5: "Each **StudentCharge** row records the `enrollment_id` it bills,
        the `adoption_id` whose title is being billed, and the `student_id` that owns
        the bursar charge as a denormalized convenience for the bursar's own
        reporting."

        Design: Corner/endpoints/endpoint_charge_cross_reference_links_enrollment_adoption_and_student
        """
        scenario = self._two_flagged_sections_each_with_one_charged_student(api)

        # The batch posting endpoint takes no body: all three links are derived.
        charge = validate_success(
            api.get_charge(scenario["first_charge_id"], bursar_officer)
        )
        assert charge["enrollment_id"] == scenario["first_enrollment_id"]
        assert charge["adoption_id"] == scenario["first_adoption_id"]
        assert charge["student_id"] == scenario["first_student_id"]

        for params, expected in (
            ({"enrollment_id": scenario["first_enrollment_id"]},
             scenario["first_charge_id"]),
            ({"student_id": scenario["first_student_id"]},
             scenario["first_charge_id"]),
            ({"adoption_id": scenario["second_adoption_id"]},
             scenario["second_charge_id"]),
        ):
            rows, meta = validate_paginated(api.list_charges(program_admin, params))
            assert meta["total_count"] == 1
            assert rows[0]["id"] == expected

        by_enrollment, enrollment_meta = validate_paginated(
            api.list_enrollment_charges(scenario["first_enrollment_id"], registrar)
        )
        assert enrollment_meta["total_count"] == 1
        by_student, student_meta = validate_paginated(
            api.list_student_charges(scenario["first_student_id"], registrar)
        )
        assert student_meta["total_count"] == 1
        assert by_enrollment[0]["id"] == scenario["first_charge_id"]
        assert by_student[0]["id"] == scenario["first_charge_id"]

        # Each section froze its own basis of 1: they do not pool for tier selection.
        for charge_id in (scenario["first_charge_id"], scenario["second_charge_id"]):
            row = fixtures.read_charge(api, charge_id)
            assert_money(row["gross_price_cents"], 9450)
            assert_money(row["publisher_share_cents"], 8316)

    def test_the_ledger_names_its_operation_and_partitions_by_student_as_well(
            self, api, bursar_officer):
        """PRD §2.5: "Each `LedgerEntry` also records `posted_at`, the logical-clock
        instant at which the movement was appended, and `source_event`, a string
        naming the API operation that appended it, written as the operation's HTTP
        method, a space, and the operation's path template — for example `POST
        /opt-out-requests/{request_id}/grant` for a movement appended by granting an
        opt-out."

        Design: Corner/endpoints/endpoint_charge_cross_reference_links_enrollment_adoption_and_student
        """
        scenario = self._two_flagged_sections_each_with_one_charged_student(api)

        rows, meta = validate_paginated(
            api.list_ledger_entries(bursar_officer,
                                   {"charge_id": scenario["first_charge_id"]})
        )
        assert meta["total_count"] == 1
        entry = rows[0]
        assert_ledger_entry_shape(entry)
        assert entry["charge_id"] == scenario["first_charge_id"]
        assert entry["student_id"] == scenario["first_student_id"]
        assert entry["entry_type"] == LedgerEntryType.CHARGE.value
        assert entry["reason_code"] == LedgerReasonCode.INITIAL_POST.value
        assert_money(entry["amount_cents"], 9450)
        assert entry["posted_at"] == "2026-08-24T09:00:00.000Z"
        assert entry["source_event"] == "POST /sections/{section_id}/post-charges"

        # The same ledger partitions by student, and the two never see each other.
        sibling, sibling_meta = validate_paginated(
            api.list_ledger_entries(bursar_officer,
                                   {"student_id": scenario["second_student_id"]})
        )
        assert sibling_meta["total_count"] == 1
        assert sibling[0]["charge_id"] == scenario["second_charge_id"]
