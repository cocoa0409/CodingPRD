"""The four preconditions on preparation and the live amendment slot.

Drafting is cheap and preparation is expensive, so everything that can refuse a
preparation is exercised here: the registration coverage of a different entity,
the accrual window, the triage requirement, and the one-live-draft-per-form rule
that governs how many amendments a case may carry at once.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AGENCY_ACCOUNT_NOT_ACTIVE,
    ERR_AMENDMENT_SLOT_OCCUPIED,
    ERR_INVALID_ACCRUAL_DATE,
    ERR_UNCATEGORIZED_DISCREPANCIES,
)
from test_helpers.assertions import (
    assert_amendment_money,
    assert_case_dimensions,
    assert_case_rollups,
    assert_pagination,
    assert_period_ordinals,
)
from test_helpers.constants import CANON_CLOCK, period_ordinal
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, OFFICER_HEADERS, PREPARER_HEADERS


NY_AGENCY = {
    "agency_code": "NY-WH",
    "level": "STATE",
    "jurisdiction_code": "NY",
    "interest_rate_bps_annual": 800,
    "interest_method": "STATUTORY_DAILY",
    "penalty_multiplier_bps": 10000,
    "min_days_between_amendments": 30,
    "amendment_window_days": 1095,
    "requires_registration": True,
}


def _coverage_scenario(api):
    """A 2025 Q1 state case whose only live registration covers 2025 Q2 through Q4."""
    fx.set_clock(api, CANON_CLOCK)
    employer = fx.make_employer(api, deposit_schedule="MONTHLY")
    agency = validate_success(
        api.create_tax_agency(f.federal_agency_payload(**NY_AGENCY), ADMIN_HEADERS), 201
    )
    later = validate_success(
        api.create_agency_account(
            f.agency_account_payload(
                employer["id"],
                agency["id"],
                effective_from_tax_year=2025,
                effective_from_quarter=2,
                effective_to_tax_year=2025,
                effective_to_quarter=4,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(
        api.activate_agency_account(later["id"], {"account_number": "NY-0001"}, ADMIN_HEADERS)
    )
    employee = fx.make_employee(api, employer["id"])
    fx.make_register_line(
        api,
        employer["id"],
        employee["id"],
        agency["id"],
        taxable_wage_cents=1000000,
        withheld_cents=150000,
        work_jurisdiction_code="NY",
    )
    fx.make_filed_return(
        api,
        employer["id"],
        agency["id"],
        form_code="NY-45X",
        reported_taxable_wage_cents=1000000,
        reported_withheld_cents=100000,
    )
    case = fx.make_correction_case(api, employer["id"], agency["id"])
    validate_success(api.reconcile_case(case["id"], {}, ANALYST_HEADERS))
    rows = fx.discrepancies_by_detected_category(api, case["id"])
    assert set(rows) == {"WITHHOLDING"}, rows
    validate_success(
        api.categorize_discrepancy(
            rows["WITHHOLDING"]["id"],
            f.categorize_payload("WITHHOLDING", "RATE_TABLE_STALE"),
            ANALYST_HEADERS,
        )
    )
    amendment = fx.open_amendment(api, case["id"], form_code="NY-45X")
    return {
        "employer_id": employer["id"],
        "agency_id": agency["id"],
        "case_id": case["id"],
        "later_account_id": later["id"],
        "amended_return_id": amendment["id"],
    }


class TestRegistrationCoverageGate:
    def test_prepare_is_refused_while_no_live_registration_brackets_the_case_quarter(self, api):
        """An `ACTIVE` registration starting one quarter after the case does not bracket
        it, so the amendment stays in `DRAFT` and the case contributes no exposure.

        PRD: "When the case's agency has `requires_registration` set to true, a registration for the case's employer and agency must exist whose `registration_status` is `ACTIVE` or `RETRO_ACTIVE` and whose coverage brackets the case's period: the registration's `from_period_ordinal` must be no greater than the case's period ordinal and its `to_period_ordinal` no smaller."
        PRD: "Absent such coverage the preparation is refused with `ERR_AGENCY_ACCOUNT_NOT_ACTIVE` — and note that this is precisely the gap a retroactive registration fills, since activating one back-dates coverage over its whole ordinal range."

        Design: Difficulty/cross_entity_state_dependency/amended_return_prepare_depends_on_agency_account_coverage
        """
        ctx = _coverage_scenario(api)
        live = validate_success(api.get_agency_account(ctx["later_account_id"], ADMIN_HEADERS))
        assert live["registration_status"] == "ACTIVE"
        assert_period_ordinals(
            live,
            from_period_ordinal=period_ordinal(2025, 2),
            to_period_ordinal=period_ordinal(2025, 4),
        )

        validate_error(
            api.prepare_amended_return(ctx["amended_return_id"], {}, PREPARER_HEADERS),
            ERR_AGENCY_ACCOUNT_NOT_ACTIVE,
            422,
        )

        unchanged = validate_success(
            api.get_amended_return(ctx["amended_return_id"], PREPARER_HEADERS)
        )
        assert unchanged["status"] == "DRAFT"
        assert unchanged["prepared_by_user_id"] is None
        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(case, filing_status="FILING_PENDING")
        assert_case_rollups(case, total_exposure_cents=0)

    def test_activating_a_retroactive_registration_back_dates_coverage_and_unblocks_prepare(
        self, api
    ):
        """Nothing about the amendment changes; a second registration activated into
        `RETRO_ACTIVE` over the case's own quarter is enough to let preparation run.

        PRD: "When `retroactive` is true — meaning the registration is being opened for quarters that have already closed — the row is written directly in `RETRO_PENDING`, and the overlap check above applies identically on that branch."
        PRD: "On the retroactive branch, `RETRO_PENDING → RETRO_ACTIVE` does all of that and one thing more: it back-dates coverage, so that every correction case for the same employer and agency whose quarter ordinal falls within the registration's closed-closed ordinal range becomes eligible for amendment preparation immediately, with no further action required."
        PRD: "`ACTIVE` and `RETRO_ACTIVE` satisfy the registration gate equally; the back-dating side effect is the only difference between them."

        Design: Difficulty/cross_entity_state_dependency/amended_return_prepare_depends_on_agency_account_coverage
        """
        ctx = _coverage_scenario(api)
        validate_error(
            api.prepare_amended_return(ctx["amended_return_id"], {}, PREPARER_HEADERS),
            ERR_AGENCY_ACCOUNT_NOT_ACTIVE,
            422,
        )

        retro = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    ctx["employer_id"],
                    ctx["agency_id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=1,
                    effective_to_tax_year=2025,
                    effective_to_quarter=1,
                    retroactive=True,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert retro["registration_status"] == "RETRO_PENDING"
        assert_period_ordinals(
            retro,
            from_period_ordinal=period_ordinal(2025, 1),
            to_period_ordinal=period_ordinal(2025, 1),
        )

        activated = validate_success(
            api.activate_agency_account(retro["id"], {"account_number": "NY-0000"}, ADMIN_HEADERS)
        )
        assert activated["registration_status"] == "RETRO_ACTIVE"
        assert activated["account_number"] == "NY-0000"
        assert activated["activated_at"] == "2026-04-30T00:00:00.000Z"

        prepared = validate_success(
            api.prepare_amended_return(ctx["amended_return_id"], {}, PREPARER_HEADERS)
        )

        assert prepared["status"] == "PREPARED"
        assert_amendment_money(
            prepared, days_late=365, interest_cents=4000, penalty_cents=9375
        )
        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(case, filing_status="FILING_IN_PROGRESS")
        assert_case_rollups(case, total_exposure_cents=63375)

    def test_the_registration_gate_is_silent_when_the_agency_does_not_require_one(self, api):
        """Against a federal agency that requires no registration, preparation succeeds
        with not a single registration row in the system.

        PRD: "Finally, `requires_registration` — false unless supplied — declares whether this agency insists on a live account registration before an amendment for a period may be prepared."
        PRD: "When the case's agency has `requires_registration` set to true, a registration for the case's employer and agency must exist whose `registration_status` is `ACTIVE` or `RETRO_ACTIVE` and whose coverage brackets the case's period: the registration's `from_period_ordinal` must be no greater than the case's period ordinal and its `to_period_ordinal` no smaller."

        Design: Corner/validations/registration_gate_applies_only_when_the_agency_requires_registration
        """
        ctx = fx.federal_categorized(api)
        agency = validate_success(api.get_tax_agency(ctx["agency_id"], ADMIN_HEADERS))
        assert agency["requires_registration"] is False

        _, meta = validate_paginated(
            api.list_agency_accounts({"employer_id": ctx["employer_id"]}, ADMIN_HEADERS)
        )
        assert_pagination(meta, total_count=0, has_more=False)

        amendment = fx.open_amendment(api, ctx["case_id"])
        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert prepared["status"] == "PREPARED"
        assert_case_dimensions(
            fx.read_case(api, ctx["case_id"]), filing_status="FILING_IN_PROGRESS"
        )


class TestAccrualWindowAndTriageGates:
    def test_accrual_date_outside_the_window_is_refused_on_both_sides(self, api):
        """A date before the original due date and a date after the logical now are both
        rejected, and the same draft then accepts a date inside the window.

        PRD: "Finally, `accrual_through_date` must be no earlier than the case's filed return's `original_due_date` and no later than the current logical instant; either violation is refused with `ERR_INVALID_ACCRUAL_DATE`."
        PRD: "It may optionally re-supply `accrual_through_date`, overriding the value carried on the draft."

        Design: Corner/errors/prepare_with_an_out_of_range_accrual_date_is_rejected
        """
        ctx = fx.federal_categorized(api)
        amendment = fx.open_amendment(api, ctx["case_id"])

        for out_of_range in ("2025-03-31", "2027-01-01"):
            validate_error(
                api.prepare_amended_return(
                    amendment["id"], {"accrual_through_date": out_of_range}, PREPARER_HEADERS
                ),
                ERR_INVALID_ACCRUAL_DATE,
                422,
            )

        still_draft = validate_success(api.get_amended_return(amendment["id"], PREPARER_HEADERS))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["interest_cents"] == 0
        assert still_draft["penalty_cents"] == 0
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=0)

        prepared = validate_success(
            api.prepare_amended_return(
                amendment["id"], {"accrual_through_date": "2026-04-30"}, PREPARER_HEADERS
            )
        )
        assert prepared["status"] == "PREPARED"
        assert_amendment_money(prepared, interest_cents=20000, penalty_cents=65625)
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=335625)

    def test_prepare_is_refused_while_any_discrepancy_is_still_open(self, api):
        """Two of three categorised is not enough: the gate is zero rows left in `OPEN`,
        so a partial amendment is never prepared.

        PRD: "Every discrepancy on the case must have been triaged: the count of discrepancies on the case whose status is `OPEN` must be zero, and the count whose status is `CATEGORIZED` must be greater than zero — a case with nothing categorised has nothing to amend."
        PRD: "Failing either half of that condition is refused with `ERR_UNCATEGORIZED_DISCREPANCIES`."

        Design: Corner/errors/prepare_with_an_open_discrepancy_returns_uncategorized_discrepancies
        """
        ctx = fx.federal_reconciled(api)
        fx.categorize_all(api, ctx["discrepancies"], skip=("DEPOSIT_SHORTFALL",))
        amendment = fx.open_amendment(api, ctx["case_id"])

        validate_error(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS),
            ERR_UNCATEGORIZED_DISCREPANCIES,
            409,
        )

        statuses = {row["detected_category"]: row["status"] for row in fx.case_discrepancies(api, ctx["case_id"])}
        assert statuses["DEPOSIT_SHORTFALL"] == "OPEN"
        assert statuses["TAXABLE_WAGE"] == "CATEGORIZED"
        assert statuses["WITHHOLDING"] == "CATEGORIZED"

        unchanged = validate_success(api.get_amended_return(amendment["id"], PREPARER_HEADERS))
        assert unchanged["status"] == "DRAFT"
        case = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(case, filing_status="FILING_PENDING")
        assert_case_rollups(case, total_exposure_cents=0)
        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["open_exposure_cents"] == 0


class TestAmendmentSlot:
    def test_a_new_draft_starts_in_draft_with_every_computed_figure_at_zero(self, api):
        """None of the arithmetic has run yet, so the whole money block is zero and
        both user stamps are null while the case's own version advances.

        PRD: "The new row is written in `status` `DRAFT`, with `wage_delta_cents`, `tax_delta_cents`, `deposit_shortfall_cents`, `days_late`, `interest_cents` and `penalty_cents` all at 0, `interest_variant` at null, `voluntary_reduction_applied` at false, and `prepared_by_user_id`, `signed_by_user_id`, `submitted_at`, `accepted_at`, `rejection_reason` and `void_reason` all at null."
        PRD: "Creating the draft increments the *case's* `version` by 1, which is why two drafts cannot be created against one observed case version in succession."

        Design: Corner/state_machines/amended_return_initial_state_is_draft
        """
        ctx = fx.federal_reconciled(api)
        before = fx.case_version(api, ctx["case_id"])

        draft = validate_success(
            api.create_amended_return(
                f.amended_return_payload(ctx["case_id"], before), PREPARER_HEADERS
            ),
            201,
        )

        assert draft["status"] == "DRAFT"
        for field in (
            "wage_delta_cents",
            "tax_delta_cents",
            "deposit_shortfall_cents",
            "days_late",
            "interest_cents",
            "penalty_cents",
        ):
            assert draft[field] == 0, field
        assert draft["interest_variant"] is None
        assert draft["voluntary_reduction_applied"] is False
        for field in (
            "prepared_by_user_id",
            "signed_by_user_id",
            "submitted_at",
            "accepted_at",
            "rejection_reason",
            "void_reason",
        ):
            assert draft[field] is None, field
        assert draft["version"] == 1
        assert fx.case_version(api, ctx["case_id"]) == before + 1

    def test_one_live_draft_per_form_code_and_a_second_form_never_contends(self, api):
        """The slot is keyed on case and form: a second 941X draft is refused while the
        first is live, but a 941X-SCHB draft is a different slot entirely.

        PRD: "Second, at most one amendment per case and `form_code` combination may occupy a live slot, where "live" means a `status` of `DRAFT`, `PREPARED`, `SIGNED` or `SUBMITTED`; a second draft for the same case and form while one of those is outstanding is refused with `ERR_AMENDMENT_SLOT_OCCUPIED`."

        Design: Difficulty/resource_temporal_overlap/amendment_slot_capacity_one_per_case_and_form_code
        """
        ctx = fx.federal_categorized(api)
        first = fx.open_amendment(api, ctx["case_id"], form_code="941X")
        assert first["status"] == "DRAFT"

        observed = fx.case_version(api, ctx["case_id"])
        validate_error(
            api.create_amended_return(
                f.amended_return_payload(ctx["case_id"], observed, form_code="941X"),
                PREPARER_HEADERS,
            ),
            ERR_AMENDMENT_SLOT_OCCUPIED,
            409,
        )

        sibling = validate_success(
            api.create_amended_return(
                f.amended_return_payload(ctx["case_id"], observed, form_code="941X-SCHB"),
                PREPARER_HEADERS,
            ),
            201,
        )
        assert sibling["status"] == "DRAFT"
        assert sibling["form_code"] == "941X-SCHB"
        assert sibling["id"] != first["id"]

    def test_voiding_the_occupant_releases_the_slot_for_a_superseding_draft(self, api):
        """A terminal return holds nothing, so once the 941X draft is voided a fresh
        941X draft naming it as predecessor is accepted.

        PRD: "Returns in `ACCEPTED`, `AGENCY_REJECTED` or `VOID` do not occupy the slot, which is what lets a rejected attempt be replaced."
        PRD: "Voiding a `DRAFT` amendment transitions `DRAFT → VOID`, records the `void_reason`, and increments the amendment's `version` by 1 — nothing else changes, because a draft never contributed to any rollup."

        Design: Difficulty/resource_temporal_overlap/amendment_slot_capacity_one_per_case_and_form_code
        """
        ctx = fx.federal_categorized(api)
        first = fx.open_amendment(api, ctx["case_id"], form_code="941X")
        fx.open_amendment(api, ctx["case_id"], form_code="941X-SCHB")

        voided = validate_success(
            api.void_amended_return(
                first["id"],
                f.void_payload(void_reason="Superseded by a re-scoped draft."),
                OFFICER_HEADERS,
            )
        )
        assert voided["status"] == "VOID"
        assert voided["void_reason"] == "Superseded by a re-scoped draft."

        replacement = validate_success(
            api.create_amended_return(
                f.amended_return_payload(
                    ctx["case_id"],
                    fx.case_version(api, ctx["case_id"]),
                    form_code="941X",
                    supersedes_amended_return_id=first["id"],
                ),
                PREPARER_HEADERS,
            ),
            201,
        )
        assert replacement["status"] == "DRAFT"
        assert replacement["supersedes_amended_return_id"] == first["id"]

        _, all_meta = validate_paginated(
            api.list_amended_returns({"correction_case_id": ctx["case_id"]}, PREPARER_HEADERS)
        )
        assert_pagination(all_meta, total_count=3)
        live_rows, live_meta = validate_paginated(
            api.list_amended_returns(
                {"correction_case_id": ctx["case_id"], "form_code": "941X", "status": "DRAFT"},
                PREPARER_HEADERS,
            )
        )
        assert_pagination(live_meta, total_count=1)
        assert live_rows[0]["id"] == replacement["id"]
        assert_case_dimensions(fx.read_case(api, ctx["case_id"]), filing_status="FILING_PENDING")
