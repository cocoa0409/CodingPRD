"""The layers that cut across every flow: the two stale-read tokens that guard the
section and the agreement, and the derived fields that must be recomputed after a
create, after an update and after a source row is removed.
"""

from test_helpers import (
    AccessStatus,
    AdoptionStatus,
    ApiErrorId,
    BillingStatus,
    EnrollmentStatus,
    LedgerEntryType,
    LedgerReasonCode,
    OptOutRequestStatus,
    PublisherAgreementStatus,
    ReconciliationRunStatus,
    ReconciliationStatus,
    SectionIaStatus,
    assert_money,
    assert_ratio,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

SINGLE_BAND = ((1, 2, 9000),)
FLAT_BAND = ((1, None, 7000),)
INTERACTIVE_TITLE = {
    "isbn": "978-0-11-000002-0",
    "title": "Economics Interactive",
    "list_price_cents": 15000,
}
SECOND_SECTION = {"section_number": "002", "instructor_user_id": "fac-2"}


class TestTheSectionVersionIsTheTokenOnAdoptionCreate:
    """A second adoption is legitimate, so only the stale token can stop it."""

    @staticmethod
    def _flagged_section_whose_version_has_moved_on(api):
        catalog = fixtures.setup_catalog(api, bands=SINGLE_BAND, activate_now=False)
        second_title, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], bands=FLAT_BAND, **INTERACTIVE_TITLE
        )
        fixtures.activate_agreement(api, catalog["agreement_id"])

        section = fixtures.create_section(api, catalog["term_id"])
        stale_version = section["version"]
        adoption = fixtures.create_adoption(
            api, section["id"], catalog["title_id"], stale_version
        )
        fixtures.submit_adoption(api, adoption["id"])
        fixtures.approve_adoption(api, adoption["id"])
        # Flagging is a mutation of the section, so the client's token goes stale.
        flagged = fixtures.flag_section(api, section["id"])

        return {
            "section_id": section["id"],
            "stale_version": stale_version,
            "current_version": flagged["version"],
            "first_title_id": catalog["title_id"],
            "second_title_id": second_title["id"],
            "adoption_id": adoption["id"],
        }

    def test_a_stale_token_is_refused_and_the_refreshed_one_admits_the_same_payload(
            self, api, program_admin):
        """PRD §2.10: "`POST /adoptions` requires a non-optional
        `expected_section_version` field carrying the client's last observed `version`
        of the target `CourseSection`. If that value does not equal the section's
        current `version`, the create is rejected with `ERR_STALE_SECTION_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_section_version_rejects_adoption_create
        """
        scenario = self._flagged_section_whose_version_has_moved_on(api)
        assert scenario["current_version"] > scenario["stale_version"]
        author = fixtures.make_faculty_headers("fac-1")

        stale_payload = factories.adoption_payload(
            scenario["section_id"], scenario["second_title_id"],
            scenario["stale_version"],
        )
        validate_error(
            api.create_adoption(stale_payload, author),
            ApiErrorId.STALE_SECTION_VERSION.value, expected_status=412,
        )

        # The rejected write is inert.
        assert fixtures.section_version(api, scenario["section_id"]) == \
            scenario["current_version"]
        _, meta = validate_paginated(
            api.list_section_adoptions(scenario["section_id"], program_admin)
        )
        assert meta["total_count"] == 1

        # The same body with a refreshed token is accepted: a second adoption on the
        # section is legitimate under the product semantics.
        refreshed = dict(stale_payload)
        refreshed["expected_section_version"] = fixtures.section_version(
            api, scenario["section_id"]
        )
        created = validate_success(
            api.create_adoption(refreshed, author), expected_status=201
        )
        assert created["status"] == AdoptionStatus.DRAFT.value
        assert created["title_id"] == scenario["second_title_id"]
        assert created["section_id"] == scenario["section_id"]

        _, meta = validate_paginated(
            api.list_section_adoptions(scenario["section_id"], program_admin)
        )
        assert meta["total_count"] == 2

    def test_the_stale_token_is_reported_ahead_of_the_access_window_rule(
            self, api, program_admin):
        """PRD §2.11: "Stale-read protection, per §2.10 — `ERR_STALE_SECTION_VERSION`
        or `ERR_STALE_AGREEMENT_VERSION`."

        Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_section_version_rejects_adoption_create
        """
        scenario = self._flagged_section_whose_version_has_moved_on(api)
        author = fixtures.make_faculty_headers("fac-1")

        # An end date earlier than the start date is an invalid access window, but the
        # request also carries an outdated section version.
        doomed = factories.adoption_payload(
            scenario["section_id"], scenario["second_title_id"],
            scenario["stale_version"],
            access_start_date="2026-08-24", access_end_date="2026-08-23",
        )
        validate_error(
            api.create_adoption(doomed, author),
            ApiErrorId.STALE_SECTION_VERSION.value, expected_status=412,
        )

        # With the token refreshed, the window rule is the one that fires.
        doomed["expected_section_version"] = fixtures.section_version(
            api, scenario["section_id"]
        )
        validate_error(
            api.create_adoption(doomed, author),
            ApiErrorId.ACCESS_WINDOW_INVALID.value, expected_status=422,
        )

        _, meta = validate_paginated(
            api.list_section_adoptions(scenario["section_id"], program_admin)
        )
        assert meta["total_count"] == 1


class TestTheAgreementVersionIsTheTokenOnReconciliationCreate:
    """A recompute that supersedes the current run is legal — until the token ages."""

    @staticmethod
    def _billed_section_with_one_computed_run(api):
        scenario = fixtures.setup_billed_section(
            api, bands=SINGLE_BAND, roster=fixtures.DEFAULT_STUDENTS[:1]
        )
        fixtures.set_clock(api, "2026-09-10T09:00:00Z")
        scenario["stale_agreement_version"] = fixtures.read_agreement(
            api, scenario["agreement_id"]
        )["version"]
        scenario["first_run"] = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            scenario["stale_agreement_version"],
            publisher_reported_count=1, publisher_reported_amount_cents=8316,
        )
        return scenario

    def test_the_first_run_bumps_the_token_so_the_recompute_behind_it_is_refused(
            self, api, program_admin):
        """PRD §2.10: "`POST /reconciliation-runs` requires a non-optional
        `expected_agreement_version` field carrying the client's last observed
        `version` of the target `PublisherAgreement`. If that value does not equal the
        agreement's current `version`, the create is rejected with
        `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_agreement_version_rejects_reconciliation_run
        """
        scenario = self._billed_section_with_one_computed_run(api)
        first_run = scenario["first_run"]

        assert first_run["status"] == ReconciliationRunStatus.COMPUTED.value
        assert first_run["billable_count"] == 1
        assert_money(first_run["gross_invoice_cents"], 8316)
        assert_money(first_run["rebate_cents"], 0)
        assert_money(first_run["settlement_amount_cents"], 8316)
        assert_money(first_run["variance_cents"], 0)
        assert first_run["count_variance"] == 0

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.COMPUTED.value
        assert agreement["version"] == scenario["stale_agreement_version"] + 1

        # The recompute is otherwise valid: it supersedes the current computed run.
        stale_recompute = factories.reconciliation_run_payload(
            scenario["agreement_id"], scenario["term_id"],
            scenario["stale_agreement_version"],
            publisher_reported_count=1, publisher_reported_amount_cents=8400,
            supersedes_run_id=first_run["id"],
        )
        validate_error(
            api.create_reconciliation_run(stale_recompute, program_admin),
            ApiErrorId.STALE_AGREEMENT_VERSION.value, expected_status=412,
        )

        # Nothing moved.
        assert fixtures.read_run(api, first_run["id"])["status"] == \
            ReconciliationRunStatus.COMPUTED.value
        assert fixtures.read_agreement(api, scenario["agreement_id"])["version"] == \
            scenario["stale_agreement_version"] + 1
        _, meta = validate_paginated(
            api.list_agreement_reconciliation_runs(
                scenario["agreement_id"], program_admin)
        )
        assert meta["total_count"] == 1

    def test_the_refreshed_token_lets_the_recompute_supersede_without_leaving_computed(
            self, api, program_admin):
        """PRD §3.8: "From `NOT_STARTED` or from `STALE`, the agreement's
        `reconciliation_status` moves to `COMPUTED`; from `COMPUTED` it stays
        `COMPUTED`, but only when the new run's `supersedes_run_id` names the
        agreement-and-term pairing's current computed run — a recompute under a
        different `method`, or against a corrected publisher invoice, replaces the
        current run without leaving `COMPUTED`. In every superseding case the named
        prior run moves `COMPUTED` → `SUPERSEDED`, which appends no ledger movement and
        freezes that run's stored figures for audit. Each of these paths increments the
        agreement's `version`."

        Design: Corner/cross_cutting_complexity_layers/layer_occ_stale_agreement_version_rejects_reconciliation_run
        """
        scenario = self._billed_section_with_one_computed_run(api)
        first_run = scenario["first_run"]

        second_run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            fixtures.read_agreement(api, scenario["agreement_id"])["version"],
            publisher_reported_count=1, publisher_reported_amount_cents=8400,
            supersedes_run_id=first_run["id"],
        )
        assert second_run["status"] == ReconciliationRunStatus.COMPUTED.value
        assert second_run["supersedes_run_id"] == first_run["id"]
        assert_money(second_run["settlement_amount_cents"], 8316)
        # The publisher reported 8400 against a computed settlement of 8316.
        assert_money(second_run["variance_cents"], 84)

        assert fixtures.read_run(api, first_run["id"])["status"] == \
            ReconciliationRunStatus.SUPERSEDED.value
        assert_money(fixtures.read_run(api, first_run["id"])["variance_cents"], 0)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["status"] == PublisherAgreementStatus.ACTIVE.value
        assert agreement["reconciliation_status"] == ReconciliationStatus.COMPUTED.value
        assert agreement["version"] == scenario["stale_agreement_version"] + 2

        runs, meta = validate_paginated(
            api.list_agreement_reconciliation_runs(
                scenario["agreement_id"], program_admin)
        )
        assert meta["total_count"] == 2
        assert len([run for run in runs
                    if run["status"] == ReconciliationRunStatus.COMPUTED.value]) == 1

        # Reconciliation reads charges; it never writes to them.
        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["publisher_share_cents"], 8316)
        assert len(fixtures.read_charge_ledger(api, charge["id"])) == 1


class TestDerivedFieldsAreRecomputedAfterEveryKindOfChange:
    """Four derived fields on four entities, checked after a create, an update and a
    removal."""

    @staticmethod
    def _two_flagged_sections_with_one_billed_pair(api):
        catalog = fixtures.setup_catalog(api)
        scenario = dict(catalog)
        scenario.update(fixtures.add_section(api, catalog))
        second = fixtures.add_section(
            api, catalog, section_overrides=SECOND_SECTION,
            instructor_user_id="fac-2",
        )
        scenario["second_section_id"] = second["section_id"]
        scenario.update(fixtures.enroll_roster(api, scenario["section_id"]))

        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        charges = fixtures.post_section_charges(api, scenario["section_id"])
        scenario["charges"] = charges
        scenario["charge_ids"] = [charge["id"] for charge in charges]
        return scenario

    @staticmethod
    def _grant_the_first_students_opt_out(api, scenario):
        fixtures.set_clock(api, "2026-08-27T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0]
        )
        return fixtures.grant_opt_out(api, request["id"])

    def test_after_the_create_every_counter_balance_and_rollup_agrees(self, api):
        """PRD §2.9: "Derived fields are recomputed, not incrementally patched,
        whenever anything they depend on changes. `Student.bursar_balance_cents` and
        `StudentCharge.net_billed_cents` are recomputed from the ledger;
        `CourseSection.enrolled_count`, `provisioned_access_count`,
        `revoked_access_count`, `opted_out_count` and `participation_rate` are
        recomputed from their underlying rows; `AcademicTerm.ia_section_count` is
        recomputed from the term's sections."

        Design: Corner/cross_cutting_complexity_layers/layer_derived_fields_reconciled_after_post_grant_and_drop
        """
        scenario = self._two_flagged_sections_with_one_billed_pair(api)

        # Both flagged sections count, billed or not.
        assert fixtures.read_term(api, scenario["term_id"])["ia_section_count"] == 2

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.BILLED.value
        assert section["enrolled_count"] == 2
        assert section["billing_basis_enrollment_count"] == 2
        assert section["provisioned_access_count"] == 2
        assert section["revoked_access_count"] == 0
        assert section["opted_out_count"] == 0
        assert_ratio(section["participation_rate"], 1.0000)

        for student_id, charge_id in zip(scenario["student_ids"],
                                        scenario["charge_ids"]):
            assert_money(fixtures.student_balance(api, student_id), 9450)
            charge = fixtures.read_charge(api, charge_id)
            entries = fixtures.read_charge_ledger(api, charge_id)
            assert len(entries) == 1
            assert_money(charge["net_billed_cents"],
                        sum(entry["amount_cents"] for entry in entries))
            assert_money(charge["net_billed_cents"], 9450)

    def test_after_the_grant_the_same_fields_are_recomputed_from_the_new_rows(self,
                                                                            api):
        """PRD §3.6: "Hop two, a consequence of that revocation, recomputes the
        section's `provisioned_access_count` (down by one), `revoked_access_count` (up
        by one), `opted_out_count` and `participation_rate`, and flips the section
        `BILLED` → `AT_RISK` if the recomputed rate fell below one half."

        Design: Corner/cross_cutting_complexity_layers/layer_derived_fields_reconciled_after_post_grant_and_drop
        """
        scenario = self._two_flagged_sections_with_one_billed_pair(api)
        granted = self._grant_the_first_students_opt_out(api, scenario)
        assert granted["status"] == OptOutRequestStatus.GRANTED.value

        refunded = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert refunded["billing_status"] == BillingStatus.REFUNDED.value
        assert refunded["access_status"] == AccessStatus.REVOKED.value
        assert_money(refunded["refunded_amount_cents"], 9450)
        assert_money(refunded["publisher_share_cents"], 0)

        entries = fixtures.read_charge_ledger(api, scenario["charge_ids"][0])
        assert len(entries) == 2
        assert_money(entries[1]["amount_cents"], -9450)
        assert entries[1]["entry_type"] == LedgerEntryType.REFUND.value
        assert entries[1]["reason_code"] == LedgerReasonCode.OPT_OUT_REFUND.value
        assert_money(refunded["net_billed_cents"],
                    sum(entry["amount_cents"] for entry in entries))
        assert_money(refunded["net_billed_cents"], 0)
        assert_money(fixtures.student_balance(api, scenario["student_ids"][0]), 0)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 2
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 1
        assert section["opted_out_count"] == 1
        assert_ratio(section["participation_rate"], 0.5000)
        # Exactly one half is not below one half.
        assert section["ia_status"] == SectionIaStatus.BILLED.value

    def test_after_the_source_row_is_dropped_the_denominator_shrinks(self, api):
        """PRD §3.7: "Otherwise the system computes a retained share by counting the
        days from the term's `term_start_date` to `dropped_on`, dividing by
        `total_term_days` and rounding half up to 4 decimal places; multiplies the
        charge's `net_billed_cents` by one minus that rounded retained share; rounds
        half up to whole cents; and caps the result at `net_billed_cents` so the
        institution never over-refunds."

        Design: Corner/cross_cutting_complexity_layers/layer_derived_fields_reconciled_after_post_grant_and_drop
        """
        scenario = self._two_flagged_sections_with_one_billed_pair(api)
        self._grant_the_first_students_opt_out(api, scenario)

        # 2026-08-24 through 2026-09-21 is 28 days of a 110-day term: retained 0.2545,
        # so 9450 * 0.7455 refunds 7045 and leaves 2405.
        fixtures.set_clock(api, "2026-09-21T13:00:00Z")
        fixtures.drop_enrollment(api, scenario["enrollment_ids"][1], "2026-09-21")

        dropped_charge = fixtures.read_charge(api, scenario["charge_ids"][1])
        assert dropped_charge["billing_status"] == \
            BillingStatus.PARTIALLY_REFUNDED.value
        assert_money(dropped_charge["refunded_amount_cents"], 7045)
        assert_money(dropped_charge["net_billed_cents"], 2405)
        assert_money(dropped_charge["publisher_share_cents"], 2116)
        assert dropped_charge["access_status"] == AccessStatus.REVOKED.value
        assert dropped_charge["access_revoked_at"] == "2026-09-21T13:00:00.000Z"

        entries = fixtures.read_charge_ledger(api, scenario["charge_ids"][1])
        assert len(entries) == 2
        assert entries[1]["reason_code"] == LedgerReasonCode.DROP_PRORATION.value
        assert_money(entries[1]["amount_cents"], -7045)
        assert_money(dropped_charge["net_billed_cents"],
                    sum(entry["amount_cents"] for entry in entries))
        assert_money(fixtures.student_balance(api, scenario["student_ids"][1]), 2405)

        assert fixtures.read_enrollment(api, scenario["enrollment_ids"][1])["status"] \
            == EnrollmentStatus.DROPPED.value

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 1
        assert section["provisioned_access_count"] == 0
        assert section["revoked_access_count"] == 2
        assert_ratio(section["participation_rate"], 0.0000)
        assert section["ia_status"] == SectionIaStatus.AT_RISK.value
        # The pricing basis is frozen at what day one saw.
        assert section["billing_basis_enrollment_count"] == 2

        # The term counts flagged sections, not billed students.
        assert fixtures.read_term(api, scenario["term_id"])["ia_section_count"] == 2
        # Hop four only fires from COMPUTED or DISPUTED.
        assert fixtures.read_agreement(api, scenario["agreement_id"])[
            "reconciliation_status"] == ReconciliationStatus.NOT_STARTED.value
