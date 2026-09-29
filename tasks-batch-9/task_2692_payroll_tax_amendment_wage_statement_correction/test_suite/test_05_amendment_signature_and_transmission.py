"""Signature, transmission and the precedence ladder that guards them.

Signing and transmitting are the two acts that can each fail for several reasons
at once, so this file pins which refusal wins: the duty split before the fiscal
limit on signing, the workflow state before the statutory calendar on
transmission, and the exact-equality edge of the cooling-off buffer.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AMENDED_RETURN_NOT_SIGNED,
    ERR_AMENDMENT_COOLING_OFF_ACTIVE,
    ERR_AMENDMENT_WINDOW_CLOSED,
    ERR_AUTHORIZATION_LIMIT_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
)
from test_helpers.assertions import (
    assert_amendment_money,
    assert_case_dimensions,
    assert_case_rollups,
)
from test_helpers.constants import CANON_CLOCK
from test_helpers.test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    OFFICER_HEADERS,
    PREPARER_HEADERS,
    USER_ADMIN,
    USER_ADMIN_ALT,
    USER_PREPARER,
    make_officer_headers,
)


SINGLE_VARIANCE = {
    "with_deposit": False,
    "register_totals": ((1000000, 150000),),
    "filed_return_overrides": {
        "reported_taxable_wage_cents": 1000000,
        "reported_withheld_cents": 100000,
    },
}


def _prepared_single_variance(api, clock=CANON_CLOCK, accrual="2026-04-30", **overrides):
    """A 2025 Q1 case with one categorised withholding variance of 50000 cents,
    prepared by the preparer and awaiting a signature."""
    ctx = fx.federal_scenario(api, clock=clock, **dict(SINGLE_VARIANCE, **overrides))
    validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))
    rows = fx.discrepancies_by_detected_category(api, ctx["case_id"])
    assert set(rows) == {"WITHHOLDING"}, rows
    validate_success(
        api.categorize_discrepancy(
            rows["WITHHOLDING"]["id"],
            f.categorize_payload("WITHHOLDING", "RATE_TABLE_STALE"),
            ANALYST_HEADERS,
        )
    )
    amendment = fx.open_amendment(api, ctx["case_id"], accrual_through_date=accrual)
    prepared = validate_success(
        api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
    )
    assert prepared["prepared_by_user_id"] == USER_PREPARER
    ctx["amended_return_id"] = amendment["id"]
    ctx["prepared"] = prepared
    return ctx


class TestSigningLadder:
    def test_the_duty_split_is_refused_before_the_authorization_limit_is_consulted(self, api):
        """The preparer signing their own amendment is a duty violation, and that 403
        wins even though the exposure also blows through a 1000-cent limit.

        PRD: "The acting `X-User-ID` must differ from the `prepared_by_user_id` recorded on the amendment; if they are equal the request is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."
        PRD: "Segregation of duties is evaluated immediately after those, first for signing and then for remediation verification, both as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."
        PRD: "Fiscal checks are evaluated last, in this order: the signing authorization limit (`ERR_AUTHORIZATION_LIMIT_EXCEEDED`), the exact-collection rule (`ERR_OVERCOLLECTION`), and the requested-waiver ceiling (`ERR_WAIVER_EXCEEDS_ASSESSMENT`)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_authorization_limit_on_sign
        """
        ctx = _prepared_single_variance(
            api,
            employer_overrides={"deposit_schedule": "MONTHLY", "authorization_limit_cents": 1000},
        )
        case = fx.read_case(api, ctx["case_id"])
        assert_case_rollups(case, total_exposure_cents=63375)
        employer = validate_success(api.get_employer(ctx["employer_id"], ADMIN_HEADERS))
        assert employer["authorization_limit_cents"] == 1000

        validate_error(
            api.sign_amended_return(
                ctx["amended_return_id"], {}, make_officer_headers(USER_PREPARER)
            ),
            ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            403,
        )

        unchanged = validate_success(
            api.get_amended_return(ctx["amended_return_id"], PREPARER_HEADERS)
        )
        assert unchanged["status"] == "PREPARED"
        assert unchanged["signed_by_user_id"] is None

    def test_the_authorization_limit_only_becomes_visible_once_the_signer_differs(self, api):
        """With the duty violation removed the next rung of the ladder fires: a 63375-cent
        exposure against a 1000-cent limit is a 422, and the amendment still never signs.

        PRD: "And the case's `total_exposure_cents`, as it stands with this amendment counted, must be no greater than the employer's `authorization_limit_cents`; if the exposure would exceed the limit the signature is refused with `ERR_AUTHORIZATION_LIMIT_EXCEEDED`, on the principle that no officer may bind the employer beyond the authority the employer granted."
        PRD: "On success the amendment transitions `PREPARED → SIGNED`, `signed_by_user_id` is set to the acting `X-User-ID`, and the amendment's `version` is incremented by 1."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_authorization_limit_on_sign
        """
        ctx = _prepared_single_variance(
            api,
            employer_overrides={"deposit_schedule": "MONTHLY", "authorization_limit_cents": 1000},
        )
        validate_error(
            api.sign_amended_return(
                ctx["amended_return_id"], {}, make_officer_headers(USER_PREPARER)
            ),
            ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            403,
        )

        validate_error(
            api.sign_amended_return(ctx["amended_return_id"], {}, OFFICER_HEADERS),
            ERR_AUTHORIZATION_LIMIT_EXCEEDED,
            422,
        )

        unchanged = validate_success(
            api.get_amended_return(ctx["amended_return_id"], PREPARER_HEADERS)
        )
        assert unchanged["status"] == "PREPARED"
        assert unchanged["signed_by_user_id"] is None
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=63375)

    def test_signing_a_draft_amendment_is_refused_and_records_no_signature(self, api):
        """`DRAFT` has only two outgoing triggers, and signing is not one of them, so a
        correctly-roled officer still cannot sign an unprepared amendment.

        PRD: "Signing is available only from `PREPARED` and takes no request body."
        PRD: "State checks come next, in three steps: whether the addressed entity's relevant state field permits the requested transition at all (`ERR_INVALID_STATE`, or `ERR_AMENDED_RETURN_NOT_SIGNED` when the attempted act is submitting an amendment that is not in `SIGNED`), then whether the entity is already in a terminal state (`ERR_ALREADY_TERMINAL`), then the amendment-specific discrepancy readiness check (`ERR_UNCATEGORIZED_DISCREPANCIES`)."

        Design: Corner/state_machines/signing_a_draft_amended_return_returns_invalid_state
        """
        ctx = fx.federal_reconciled(api)
        draft = fx.open_amendment(api, ctx["case_id"])
        assert draft["status"] == "DRAFT"

        validate_error_is_one_of(
            api.sign_amended_return(draft["id"], {}, OFFICER_HEADERS),
            (ERR_INVALID_STATE, ERR_AMENDED_RETURN_NOT_SIGNED),
        )

        unchanged = validate_success(api.get_amended_return(draft["id"], PREPARER_HEADERS))
        assert unchanged["status"] == "DRAFT"
        assert unchanged["signed_by_user_id"] is None
        assert unchanged["version"] == 1


class TestTransmissionLadder:
    def test_the_unsigned_state_check_wins_over_a_window_that_has_already_lapsed(self, api):
        """Both conditions hold on the same call — never signed and past the 730-day
        window — and the workflow-state refusal is the one returned.

        PRD: "The amendment must be in `SIGNED`; attempting transmission on an amendment in any other state is refused with `ERR_AMENDED_RETURN_NOT_SIGNED`."
        PRD: "Temporal checks come next in this order: the amendment window (`ERR_AMENDMENT_WINDOW_CLOSED`), the cooling-off buffer between amendments (`ERR_AMENDMENT_COOLING_OFF_ACTIVE`), the accrual date bounds (`ERR_INVALID_ACCRUAL_DATE`), the notice response deadline (`ERR_NOTICE_RESPONSE_OVERDUE`), and the prior-year statement window (`ERR_PRIOR_YEAR_WINDOW_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_check_precedes_temporal_window_on_unsigned_late_submit
        """
        ctx = _prepared_single_variance(
            api,
            clock="2027-05-01T00:00:00Z",
            accrual="2027-05-01",
            employer_overrides={"deposit_schedule": "MONTHLY"},
            agency_overrides={"amendment_window_days": 730},
        )

        validate_error(
            api.submit_amended_return(ctx["amended_return_id"], {}, OFFICER_HEADERS),
            ERR_AMENDED_RETURN_NOT_SIGNED,
            409,
        )

        unchanged = validate_success(
            api.get_amended_return(ctx["amended_return_id"], PREPARER_HEADERS)
        )
        assert unchanged["status"] == "PREPARED"
        assert unchanged["submitted_at"] is None
        assert_case_dimensions(
            fx.read_case(api, ctx["case_id"]), filing_status="FILING_IN_PROGRESS"
        )

    def test_the_lapsed_window_surfaces_only_after_the_amendment_has_been_signed(self, api):
        """Signing the very same amendment removes the state violation, and the calendar
        refusal that was hidden behind it becomes the answer.

        PRD: "The **amendment window** requires the current logical instant to fall on or before the filed return's `original_due_date` advanced by the agency's `amendment_window_days` whole days — the boundary instant itself is inside the window — and a later attempt is refused with `ERR_AMENDMENT_WINDOW_CLOSED`."
        PRD: "On success the amendment transitions `PREPARED → SIGNED`, `signed_by_user_id` is set to the acting `X-User-ID`, and the amendment's `version` is incremented by 1."

        Design: Difficulty/priority_pair_validation_conflict/state_check_precedes_temporal_window_on_unsigned_late_submit
        """
        ctx = _prepared_single_variance(
            api,
            clock="2027-05-01T00:00:00Z",
            accrual="2027-05-01",
            employer_overrides={"deposit_schedule": "MONTHLY"},
            agency_overrides={"amendment_window_days": 730},
        )
        signed = validate_success(
            api.sign_amended_return(ctx["amended_return_id"], {}, OFFICER_HEADERS)
        )
        assert signed["status"] == "SIGNED"

        validate_error(
            api.submit_amended_return(ctx["amended_return_id"], {}, OFFICER_HEADERS),
            ERR_AMENDMENT_WINDOW_CLOSED,
            422,
        )

        unchanged = validate_success(
            api.get_amended_return(ctx["amended_return_id"], PREPARER_HEADERS)
        )
        assert unchanged["status"] == "SIGNED"
        assert unchanged["submitted_at"] is None


def _rejected_then_resigned(api):
    """A first amendment submitted on 1 May 2026 and rejected, and a replacement
    sitting in `SIGNED` waiting on the 45-day buffer."""
    ctx = _prepared_single_variance(
        api,
        clock="2026-05-01T00:00:00Z",
        employer_overrides={"deposit_schedule": "MONTHLY"},
        agency_overrides={"min_days_between_amendments": 45},
    )
    first = ctx["amended_return_id"]
    validate_success(api.sign_amended_return(first, {}, OFFICER_HEADERS))
    submitted = validate_success(api.submit_amended_return(first, {}, OFFICER_HEADERS))
    assert submitted["submitted_at"] == "2026-05-01T00:00:00.000Z"
    rejected = validate_success(
        api.record_agency_outcome(
            first,
            f.agency_outcome_payload(
                "REJECTED", rejection_reason="Agency could not match the deposit schedule."
            ),
            OFFICER_HEADERS,
        )
    )
    assert rejected["status"] == "AGENCY_REJECTED"

    second = fx.open_amendment(
        api,
        ctx["case_id"],
        accrual_through_date="2026-04-30",
        supersedes_amended_return_id=first,
    )
    validate_success(api.prepare_amended_return(second["id"], {}, PREPARER_HEADERS))
    resigned = validate_success(api.sign_amended_return(second["id"], {}, OFFICER_HEADERS))
    assert resigned["status"] == "SIGNED"
    ctx["first_id"] = first
    ctx["second_id"] = second["id"]
    return ctx


class TestCoolingOffBuffer:
    def test_forty_four_whole_days_after_the_previous_transmission_is_refused(self, api):
        """One day short of the configured 45 is short, so the replacement stays in
        `SIGNED` and nothing is transmitted.

        PRD: "If one or more exist, take the most recent of them and count the whole days from its `submitted_at` to the current logical instant; that count must be at least the agency's `min_days_between_amendments`."
        PRD: "A shorter interval is refused with `ERR_AMENDMENT_COOLING_OFF_ACTIVE`."

        Design: Difficulty/boundary_precision_check/cooling_off_buffer_admits_exactly_min_days_between_amendments
        """
        ctx = _rejected_then_resigned(api)
        fx.set_clock(api, "2026-06-14T00:00:00Z")

        validate_error(
            api.submit_amended_return(ctx["second_id"], {}, OFFICER_HEADERS),
            ERR_AMENDMENT_COOLING_OFF_ACTIVE,
            409,
        )

        unchanged = validate_success(api.get_amended_return(ctx["second_id"], PREPARER_HEADERS))
        assert unchanged["status"] == "SIGNED"
        assert unchanged["submitted_at"] is None

    def test_exactly_the_configured_minimum_number_of_days_is_admitted(self, api):
        """The buffer is half-open, so a count of exactly 45 whole days passes and the
        accrual date rather than the transmission date still drives the money.

        PRD: "The buffer is half-open, so a count exactly equal to the configured minimum passes."
        PRD: "On success the amendment transitions `SIGNED → SUBMITTED`, `submitted_at` is stamped from the logical clock, and `version` is incremented by 1."

        Design: Difficulty/boundary_precision_check/cooling_off_buffer_admits_exactly_min_days_between_amendments
        """
        ctx = _rejected_then_resigned(api)
        fx.set_clock(api, "2026-06-14T00:00:00Z")
        validate_error(
            api.submit_amended_return(ctx["second_id"], {}, OFFICER_HEADERS),
            ERR_AMENDMENT_COOLING_OFF_ACTIVE,
            409,
        )

        fx.set_clock(api, "2026-06-15T00:00:00Z")
        submitted = validate_success(
            api.submit_amended_return(ctx["second_id"], {}, OFFICER_HEADERS)
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == "2026-06-15T00:00:00.000Z"
        assert_amendment_money(
            submitted, days_late=365, interest_cents=4000, penalty_cents=9375
        )
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=63375)


class TestPlatformAdminReach:
    def test_platform_admin_runs_the_whole_chain_yet_still_obeys_the_duty_split(self, api):
        """One admin identity posts the register line, reconciles, categorises, drafts,
        prepares and opens a remediation; a second admin identity is needed to sign.

        PRD: "`PlatformAdmin` is the operations superuser and may perform every declared operation, but it earns no exemption from the segregation-of-duties rules described in §2.8 — an admin who prepared an amendment still cannot sign it."
        PRD: "When `X-User-Role` is `PlatformAdmin`, `PayrollAnalyst`, `TaxPreparer`, `TaxOfficer` or `ControlsAuditor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any row's `id`."

        Design: Corner/rbac/platform_admin_performs_every_other_roles_exclusive_operation
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = validate_success(api.create_employer(f.employer_payload(), ADMIN_HEADERS), 201)
        agency = validate_success(
            api.create_tax_agency(f.federal_agency_payload(), ADMIN_HEADERS), 201
        )
        first = validate_success(
            api.create_employee(f.employee_payload(employer["id"]), ADMIN_HEADERS), 201
        )
        second = validate_success(
            api.create_employee(
                f.employee_payload(employer["id"], full_name="Lee Park", national_id_last4="7130"),
                ADMIN_HEADERS,
            ),
            201,
        )
        for employee, (wage, withheld) in zip(
            (first, second), ((3000000, 450000), (2000000, 300000))
        ):
            validate_success(
                api.create_register_line(
                    f.register_line_payload(
                        employer["id"],
                        employee["id"],
                        agency["id"],
                        taxable_wage_cents=wage,
                        withheld_cents=withheld,
                    ),
                    ADMIN_HEADERS,
                ),
                201,
            )
        validate_success(
            api.create_filed_return(
                f.filed_return_payload(employer["id"], agency["id"]), ADMIN_HEADERS
            ),
            201,
        )
        case = validate_success(
            api.create_correction_case(
                f.correction_case_payload(employer["id"], agency["id"]), ADMIN_HEADERS
            ),
            201,
        )
        validate_success(api.reconcile_case(case["id"], {}, ADMIN_HEADERS))
        rows = fx.discrepancies_by_detected_category(api, case["id"])
        assert set(rows) == {"TAXABLE_WAGE", "WITHHOLDING"}, rows
        for category, root_cause in (
            ("TAXABLE_WAGE", "RATE_TABLE_STALE"),
            ("WITHHOLDING", "RATE_TABLE_STALE"),
        ):
            validate_success(
                api.categorize_discrepancy(
                    rows[category]["id"],
                    f.categorize_payload(category, root_cause),
                    ADMIN_HEADERS,
                )
            )
        amendment = validate_success(
            api.create_amended_return(
                f.amended_return_payload(case["id"], fx.case_version(api, case["id"])),
                ADMIN_HEADERS,
            ),
            201,
        )
        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, ADMIN_HEADERS)
        )
        assert prepared["prepared_by_user_id"] == USER_ADMIN

        validate_error(
            api.sign_amended_return(amendment["id"], {}, ADMIN_HEADERS),
            ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            403,
        )
        signed = validate_success(
            api.sign_amended_return(amendment["id"], {}, ADMIN_ALT_HEADERS)
        )

        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == USER_ADMIN_ALT
        assert_amendment_money(
            signed,
            tax_delta_cents=250000,
            deposit_shortfall_cents=0,
            interest_cents=20000,
            penalty_cents=46875,
            voluntary_reduction_applied=True,
        )

        remediation = validate_success(
            api.create_control_remediation(
                f.control_remediation_payload(case["id"]), ADMIN_HEADERS
            ),
            201,
        )
        assert remediation["correction_case_id"] == case["id"]
