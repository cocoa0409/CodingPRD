"""Version guards on the two displacing creates, and write-through derivation.

Both stale-version guards cover a whole row rather than the field a caller cares
about, so a governance action on an unrelated dimension is enough to invalidate a
held version. The last two cases pin the other side of the same coin: a repeated
checkpoint must not accumulate, and a single assess call must leave the parent
already correct without anything else being run.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    OFFICER_PREPARER_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    AMENDMENT_PROPOSED,
    ATTESTATION_DRAFT,
    CYCLE_MISSED,
    CYCLE_PENDING,
    DATA_RIGHTS_NOT_SECURED,
    DATA_RIGHTS_PENDING_AMENDMENT,
    DEFICIENCY_MRF_REFRESH,
    DISCLOSURE_UNREASONABLE,
    ENTRY_ACCRUAL,
    GAG_IN_REVIEW,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    VARIANT_TOTAL_WITH_INDIRECT,
    VENDOR_TYPE_BROKER,
    VENDOR_TYPE_PBM,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

ROSTER_CLOCK = "2027-12-01T09:00:00Z"
ATTESTATION_CLOCK = "2028-01-10T09:00:00Z"
CONTRACT_CLOCK = "2027-05-01T09:00:00Z"
CYCLE_OPEN_CLOCK = "2027-06-01T09:00:00Z"
RUN_CLOCK = "2027-07-08T09:00:00Z"
DISCLOSURE_CLOCK = "2027-05-01T09:00:00Z"

FREEZE_REASON = "Evidence trail re-checked after a vendor complaint."
BROKER_FIGURES = {
    "direct_comp_cents": 1_000_000,
    "indirect_comp_cents": 400_000,
    "benchmark_median_cents": 1_000_000,
    "services_scope_score": 5,
    "disclosure_completeness_score": 4,
}


def _plan_year_whose_version_moved_without_changing_posture(api: ApiClient) -> dict:
    """A gag-clear plan year, its version read, then a freeze/unfreeze pair applied."""
    fx.set_clock(api, ROSTER_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    plan_year_id = setup["plan_year"]["id"]
    fx.gag_compliant_contract(api, setup["tpa_contract"]["id"])

    fx.set_clock(api, ATTESTATION_CLOCK)
    stale_version = fx.current_plan_year_version(api, plan_year_id)
    validate_success(
        api.freeze_plan_year(
            plan_year_id, {"reason": FREEZE_REASON}, EXTERNAL_AUDITOR_HEADERS
        )
    )
    validate_success(
        api.unfreeze_plan_year(
            plan_year_id, EXTERNAL_AUDITOR_HEADERS, {"note": "Complaint unfounded."}
        )
    )
    return {"plan_year_id": plan_year_id, "stale_version": stale_version}


def _plan_year_with_an_untouched_pbm_contract(api: ApiClient) -> dict:
    """An active plan year whose PBM contract is fresh on both dimensions."""
    fx.set_clock(api, CONTRACT_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    pbm = fx.add_contract_for_vendor_type(
        api, setup["plan_year"]["id"], VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
    )
    return {
        "plan_year_id": setup["plan_year"]["id"],
        "contract_id": pbm["contract"]["id"],
    }


class TestStalePlanYearVersionGuard:
    """A freeze and an unfreeze leave the posture where it was — and the version not."""

    def test_a_version_read_before_a_governance_round_trip_is_refused(
        self, api: ApiClient
    ) -> None:
        """Posture came back to where it started; the version did not.

        PRD 2.7: "Creating an attestation requires a non-optional
        `expected_plan_year_version` field carrying the client's last observed
        `version` of the target `PlanYear`. If that value does not equal the plan
        year's current `version`, the create is refused with
        `ERR_STALE_PLAN_YEAR_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_year_version_on_attestation_create
        """
        built = _plan_year_whose_version_moved_without_changing_posture(api)
        plan_year_id = built["plan_year_id"]

        validate_error(
            api.create_attestation(
                f.attestation_payload(
                    plan_year_id, built["stale_version"], contract_terms_doc_count=3
                ),
                OFFICER_PREPARER_HEADERS,
            ),
            ApiErrorId.STALE_PLAN_YEAR_VERSION,
            expected_status=412,
        )

        rows, meta = validate_paginated(
            api.list_attestations(
                COMPLIANCE_OFFICER_HEADERS, params={"plan_year_id": plan_year_id}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        settled = fx.read_plan_year(api, plan_year_id)
        assert settled["version"] == built["stale_version"] + 2
        assert settled["compliance_posture"] == POSTURE_COMPLIANT
        assert settled["freeze_flag"] is False
        assert settled["freeze_reason"] is None

    def test_re_reading_the_version_lets_the_identical_payload_through(
        self, api: ApiClient
    ) -> None:
        """Nothing about the request body changes — only the version it carries.

        PRD 2.7: "This guard exists because a new draft attestation legitimately
        supersedes the prior draft for the same plan year — the create cannot be
        refused on state grounds, so the version check is what stops a writer
        from voiding a draft it never saw, and from attesting against a
        compliance posture snapshot that has since moved."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_year_version_on_attestation_create
        """
        built = _plan_year_whose_version_moved_without_changing_posture(api)
        plan_year_id = built["plan_year_id"]
        validate_error(
            api.create_attestation(
                f.attestation_payload(
                    plan_year_id, built["stale_version"], contract_terms_doc_count=3
                ),
                OFFICER_PREPARER_HEADERS,
            ),
            ApiErrorId.STALE_PLAN_YEAR_VERSION,
        )

        fresh_version = fx.current_plan_year_version(api, plan_year_id)
        assert fresh_version == built["stale_version"] + 2

        created = validate_success(
            api.create_attestation(
                f.attestation_payload(
                    plan_year_id, fresh_version, contract_terms_doc_count=3
                ),
                OFFICER_PREPARER_HEADERS,
            ),
            expected_status=201,
        )
        assert created["status"] == ATTESTATION_DRAFT
        assert created["plan_year_id"] == plan_year_id

        stored = validate_success(
            api.get_attestation(created["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert stored["contract_terms_doc_count"] == 3
        assert stored["submitted_by_user_id"] is None


class TestStaleContractVersionGuard:
    """The guard covers the row, not the dimension the amendment writes."""

    def test_a_gag_review_invalidates_a_version_held_for_the_data_rights_dimension(
        self, api: ApiClient
    ) -> None:
        """Data rights never moved, and the held version is stale all the same.

        PRD 2.7: "Creating a contract amendment requires a non-optional
        `expected_contract_version` field carrying the client's last observed
        `version` of the target `ServiceProviderContract`. If that value does not
        equal the contract's current `version`, the create is refused with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        PRD 2.7: "The version check stops a writer from withdrawing a negotiation
        round it never observed, and from proposing terms against a
        `data_rights_status` or `gag_review_status` that has already changed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_amendment_create
        """
        built = _plan_year_with_an_untouched_pbm_contract(api)
        contract_id = built["contract_id"]
        stale_version = fx.current_contract_version(api, contract_id)

        fx.open_gag_review(
            api,
            contract_id,
            clause_inventory_count=22,
            prohibited_clause_count=0,
            review_note="Clause inventory pulled from the executed agreement.",
        )

        validate_error(
            api.create_amendment(
                f.amendment_payload(contract_id, stale_version),
                SPONSOR_ADMIN_HEADERS,
            ),
            ApiErrorId.STALE_CONTRACT_VERSION,
            expected_status=412,
        )

        after_review = fx.read_contract(api, contract_id)
        assert after_review["data_rights_status"] == DATA_RIGHTS_NOT_SECURED
        assert after_review["gag_review_status"] == GAG_IN_REVIEW
        fresh_version = after_review["version"]
        assert fresh_version == stale_version + 1

        proposed = validate_success(
            api.create_amendment(
                f.amendment_payload(contract_id, fresh_version),
                SPONSOR_ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert proposed["status"] == AMENDMENT_PROPOSED
        assert proposed["round"] == 1

        after_proposal = fx.read_contract(api, contract_id)
        assert after_proposal["data_rights_status"] == DATA_RIGHTS_PENDING_AMENDMENT
        assert after_proposal["version"] == fresh_version + 1


class TestComplianceRunIdempotence:
    """A checkpoint, not an accumulator."""

    def test_a_second_run_at_the_same_clock_sweeps_and_posts_nothing_further(
        self, api: ApiClient
    ) -> None:
        """One overdue month costs one accrual however many times it is checked.

        PRD 3.9: "Each newly missed cycle then posts one ledger accrual with
        `entry_type` `ACCRUAL`, `deficiency_type` `MRF_REFRESH` and `onset_date`
        equal to the day after that cycle's `deadline_at` date, priced by the
        accrual formula above — unless an unreversed `MRF_REFRESH` accrual
        already exists for that cycle's `period_month`, in which case no second
        accrual is posted."

        PRD 3.9: "The run is idempotent for a fixed clock: triggering it a second
        time without advancing the clock sweeps nothing further and posts no
        further accruals, so `cycles_missed_count`, `amendments_lapsed_count` and
        `accruals_posted_count` all come back as 0 and `posture_before` equals
        `posture_after`."

        Design: Corner/cross_cutting_complexity_layers/compliance_run_repeated_at_same_clock_posts_no_second_accrual
        """
        fx.set_clock(api, CYCLE_OPEN_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        cycle = fx.open_refresh_cycle(
            api,
            plan_year_id,
            period_month="2027-06",
            period_start="2027-06-01",
            period_end="2027-06-30",
        )
        assert cycle["status"] == CYCLE_PENDING

        fx.set_clock(api, RUN_CLOCK)
        first = validate_success(
            api.run_compliance(plan_year_id, PLATFORM_OPERATOR_HEADERS)
        )
        assert first["cycles_missed_count"] == 1
        assert first["accruals_posted_count"] == 1
        assert first["posture_before"] == POSTURE_COMPLIANT
        assert first["posture_after"] == POSTURE_AT_RISK
        assert first["penalty_exposure_cents"] == 60_000

        second = validate_success(
            api.run_compliance(plan_year_id, PLATFORM_OPERATOR_HEADERS)
        )
        assert second["cycles_missed_count"] == 0
        assert second["amendments_lapsed_count"] == 0
        assert second["accruals_posted_count"] == 0
        assert second["posture_before"] == POSTURE_AT_RISK
        assert second["posture_after"] == POSTURE_AT_RISK
        assert second["penalty_exposure_cents"] == 60_000
        assert second["run_id"] != first["run_id"]

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                EXTERNAL_AUDITOR_HEADERS, params={"plan_year_id": plan_year_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["entry_type"] == ENTRY_ACCRUAL
        assert rows[0]["deficiency_type"] == DEFICIENCY_MRF_REFRESH
        assert rows[0]["onset_date"] == "2027-07-06"
        assert rows[0]["days_open"] == 3
        assert rows[0]["signed_amount_cents"] == 60_000

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["deficiency_points"] == 3
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK

        swept = validate_success(
            api.get_refresh_cycle(cycle["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert swept["status"] == CYCLE_MISSED


class TestWriteThroughDerivedFields:
    """Nothing has to be run afterwards to make the parent correct."""

    def test_the_assessment_response_and_the_parent_are_both_current_at_once(
        self, api: ApiClient
    ) -> None:
        """The score is in the response, and the plan year already carries the points.

        PRD 3.7: "Where they diverge is the plan year: the `UNREASONABLE` branch
        recomputes the plan year's `deficiency_points`, adding three points for
        this disclosure, and recomputes `compliance_posture` — while the
        `REASONABLE` branch touches no plan year field at all."

        PRD 2.8: "It is recomputed from `deficiency_points`, which is itself
        recomputed from the live state of the plan year's children after every
        mutation that opens or closes a deficiency and on every compliance run."

        Design: Corner/consistency_model/assessment_response_already_reflects_derived_posture
        """
        fx.set_clock(api, DISCLOSURE_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        broker = fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_BROKER, annual_fee_cents=2_400_000
        )
        disclosure = fx.received_compensation_disclosure(
            api, broker["contract"]["id"], **BROKER_FIGURES
        )
        assert disclosure["unreasonableness_score"] is None

        before = fx.read_plan_year(api, plan_year_id)
        assert before["deficiency_points"] == 0
        assert before["compliance_posture"] == POSTURE_COMPLIANT

        assessed = validate_success(
            api.assess_compensation_disclosure(
                disclosure["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.assess_disclosure_payload(
                    assessment_note=(
                        "Indirect commissions push the ratio above tolerance."
                    )
                ),
            )
        )
        assert assessed["unreasonableness_score"] == 67.67
        assert assessed["status"] == DISCLOSURE_UNREASONABLE
        assert assessed["variant_applied"] == VARIANT_TOTAL_WITH_INDIRECT

        stored = validate_success(
            api.get_compensation_disclosure(
                disclosure["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert stored["unreasonableness_score"] == 67.67
        assert stored["variant_applied"] == VARIANT_TOTAL_WITH_INDIRECT
        assert_instant_equals(stored["assessed_at"], DISCLOSURE_CLOCK)

        after = fx.read_plan_year(api, plan_year_id)
        assert after["deficiency_points"] == 3
        assert after["compliance_posture"] == POSTURE_AT_RISK
        assert after["penalty_exposure_cents"] == 0
