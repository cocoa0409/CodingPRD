"""Revenue reports: the recoupment waterfall, OCC on report submission,
reversal replay, and report validation rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_slot,
    assert_recoupment_ledger_invariant,
    assert_revenue_report,
    book_report,
    create_direct_license,
    create_revenue_report_payload,
    get_license,
    list_reports_for_license,
    reverse_report,
    setup_catalog,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]


def _mg_license(workspace, minimum_guarantee_cents, revenue_share_pct=50):
    """EXECUTED MINIMUM_GUARANTEE license covering [2026-08-01, 2027-08-01)."""
    slot = add_slot(workspace)
    return create_direct_license(
        slot["id"], workspace["platform"]["id"],
        license_start="2026-08-01T00:00:00Z",
        license_end="2027-08-01T00:00:00Z",
        fee_model="MINIMUM_GUARANTEE",
        minimum_guarantee_cents=minimum_guarantee_cents,
        revenue_share_pct=revenue_share_pct,
    )


def _revenue_share_license(workspace, revenue_share_pct=50):
    """EXECUTED REVENUE_SHARE license covering [2026-08-01, 2027-08-01)."""
    slot = add_slot(workspace)
    return create_direct_license(
        slot["id"], workspace["platform"]["id"],
        license_start="2026-08-01T00:00:00Z",
        license_end="2027-08-01T00:00:00Z",
        fee_model="REVENUE_SHARE",
        revenue_share_pct=revenue_share_pct,
    )


class TestRecoupmentWaterfall:
    def test_waterfall_min_binds_differently_per_report(self, api):
        """PRD §3.8: "For a `MINIMUM_GUARANTEE` license, the recoupment applied — `recoupment_applied_cents` — is the smaller of the accrued amount and the outstanding recoupment balance immediately before this report; for a `REVENUE_SHARE` license the applied amount is 0. The payable portion, `payable_cents`, is the accrued amount minus the applied amount."
        PRD §3.8: "The accrued royalty is the gross multiplied by `revenue_share_pct` and divided by 100, rounded half up to integer cents, and stored as `royalty_accrued_cents`."

        Design: Difficulty/combinatorial_formula/recoupment_waterfall_min_interaction
        """
        workspace = setup_catalog()
        license_agreement = _mg_license(workspace, 100000)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        r1 = book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z",
                         120000)
        assert_revenue_report(r1)
        assert r1["royalty_accrued_cents"] == 60000
        assert r1["recoupment_applied_cents"] == 60000, (
            "min(60000 accrued, 100000 outstanding) withholds the full accrual"
        )
        assert r1["payable_cents"] == 0

        r2 = book_report(lid, buyer, "2026-07-16T00:00:00Z", "2026-07-31T00:00:00Z",
                         80000)
        assert r2["royalty_accrued_cents"] == 40000
        assert r2["recoupment_applied_cents"] == 40000, (
            "min(40000 accrued, 40000 outstanding) binds at exact exhaustion"
        )
        assert r2["payable_cents"] == 0

        r3 = book_report(lid, buyer, "2026-07-20T00:00:00Z", "2026-07-31T00:00:00Z",
                         10000)
        assert r3["royalty_accrued_cents"] == 5000
        assert r3["recoupment_applied_cents"] == 0, (
            "with the guarantee exhausted the min() binds at zero"
        )
        assert r3["payable_cents"] == 5000

    def test_waterfall_final_ledger_state(self, api):
        """PRD §3.8: "In the same request the license's ledger updates: `recouped_cents` increases by the applied amount, `royalty_payable_cents` increases by the payable amount, `outstanding_recoupment_cents` becomes the greater of zero and `minimum_guarantee_cents` minus `recouped_cents`, and the license's `version` advances by one."

        Design: Difficulty/combinatorial_formula/recoupment_waterfall_min_interaction
        """
        workspace = setup_catalog()
        license_agreement = _mg_license(workspace, 100000)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        r1 = book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z",
                         120000)
        r2 = book_report(lid, buyer, "2026-07-16T00:00:00Z", "2026-07-31T00:00:00Z",
                         80000)
        r3 = book_report(lid, buyer, "2026-07-20T00:00:00Z", "2026-07-31T00:00:00Z",
                         10000)

        ledger = get_license(lid)
        assert ledger["recouped_cents"] == 100000
        assert ledger["royalty_payable_cents"] == 5000
        assert ledger["outstanding_recoupment_cents"] == 0
        assert_recoupment_ledger_invariant(ledger, [r1, r2, r3])

    def test_recoupment_exact_equality_withholds_full_amount(self, api):
        """PRD §3.8: "For a `MINIMUM_GUARANTEE` license, the recoupment applied — `recoupment_applied_cents` — is the smaller of the accrued amount and the outstanding recoupment balance immediately before this report; for a `REVENUE_SHARE` license the applied amount is 0."

        Design: Difficulty/boundary_precision_check/recoupment_exact_equality_boundary
        """
        workspace = setup_catalog()
        license_agreement = _mg_license(workspace, 50000)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        r1 = book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z",
                         100000)
        assert r1["royalty_accrued_cents"] == 50000
        assert r1["recoupment_applied_cents"] == 50000, (
            "accrued 50000 exactly equals outstanding 50000: the min() must take "
            "the full amount, leaving no one-cent residue"
        )
        assert r1["payable_cents"] == 0
        assert get_license(lid)["outstanding_recoupment_cents"] == 0, (
            "the boundary lands exactly on zero"
        )

    def test_post_exhaustion_report_pays_in_full(self, api):
        """PRD §3.8: "The payable portion, `payable_cents`, is the accrued amount minus the applied amount."
        PRD §3.8: "In the same request the license's ledger updates: `recouped_cents` increases by the applied amount, `royalty_payable_cents` increases by the payable amount, `outstanding_recoupment_cents` becomes the greater of zero and `minimum_guarantee_cents` minus `recouped_cents`, and the license's `version` advances by one."

        Design: Difficulty/boundary_precision_check/recoupment_exact_equality_boundary
        """
        workspace = setup_catalog()
        license_agreement = _mg_license(workspace, 50000)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", 100000)
        r2 = book_report(lid, buyer, "2026-07-15T00:00:00Z", "2026-07-31T00:00:00Z",
                         4000)
        assert r2["recoupment_applied_cents"] == 0
        assert r2["payable_cents"] == 2000, (
            "once the guarantee is exhausted, further reports pay out in full"
        )

        ledger = get_license(lid)
        assert ledger["recouped_cents"] == 50000
        assert ledger["royalty_payable_cents"] == 2000


class TestReportReversal:
    def test_reverse_replays_waterfall_over_remaining_reports(self, api):
        """PRD §3.8: "Reversal recomputes the license's `recouped_cents`, `royalty_payable_cents`, and `outstanding_recoupment_cents` from scratch: both cumulative fields are reset to zero, then the waterfall is replayed over the license's remaining `SUBMITTED` reports in chronological order — `submitted_at` ascending, ties broken by `created_at` ascending — and the license's `version` increments with `updated_at` refreshed."
        PRD §3.8: "Only a `SUBMITTED` report can be reversed — `REVERSED` is terminal and a second reversal is impossible."

        Design: Difficulty/compensating_invariant/report_reverse_restores_recoupment_invariant
        """
        workspace = setup_catalog()
        license_agreement = _mg_license(workspace, 100000)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        r1 = book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z",
                         120000)
        book_report(lid, buyer, "2026-07-16T00:00:00Z", "2026-07-31T00:00:00Z", 80000)

        reversed_report = reverse_report(r1["id"])
        assert reversed_report["report_status"] == "REVERSED"

        ledger = get_license(lid)
        assert ledger["recouped_cents"] == 40000, (
            "replay over the remaining report recomputes min(40000, 100000); "
            "it does not merely subtract the reversed amount"
        )
        assert ledger["royalty_payable_cents"] == 0
        assert ledger["outstanding_recoupment_cents"] == 60000

    def test_recoupment_invariant_holds_after_reversal(self, api):
        """PRD §3.8: "Reversal recomputes the license's `recouped_cents`, `royalty_payable_cents`, and `outstanding_recoupment_cents` from scratch: both cumulative fields are reset to zero, then the waterfall is replayed over the license's remaining `SUBMITTED` reports in chronological order — `submitted_at` ascending, ties broken by `created_at` ascending — and the license's `version` increments with `updated_at` refreshed."

        Design: Difficulty/compensating_invariant/report_reverse_restores_recoupment_invariant
        """
        workspace = setup_catalog()
        license_agreement = _mg_license(workspace, 100000)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        r1 = book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z",
                         120000)
        r2 = book_report(lid, buyer, "2026-07-16T00:00:00Z", "2026-07-31T00:00:00Z",
                         80000)
        reverse_report(r1["id"])

        remaining = [
            r for r in list_reports_for_license(lid)
            if r["report_status"] == "SUBMITTED"
        ]
        assert [r["id"] for r in remaining] == [r2["id"]]
        ledger = get_license(lid)
        assert_recoupment_ledger_invariant(ledger, remaining)


class TestReportOcc:
    def test_report_submit_with_stale_license_version_returns_412(self, api):
        """PRD §2.7: "Both requests must carry `expected_license_version`, a non-optional field equal to the license's current `version` as last observed by the client. If the value does not match the license's current `version` — because another booked report or a prior extension has advanced the version since the client last read the license — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "Each legitimately successful revenue-report booking mutates `recouped_cents`, `royalty_payable_cents`, and `outstanding_recoupment_cents` and advances the license's `version` by one, so a client holding a stale view would otherwise compute recoupment from superseded state."

        Design: Corner/cross_cutting_layers/report_submit_with_stale_license_version_returns_412
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]
        stale_version = license_agreement["version"]

        first = validate_success(api.submit_revenue_report(
            lid,
            create_revenue_report_payload(
                "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", 1000, stale_version,
            ),
            buyer,
        ), 201)
        assert_revenue_report(first)

        resp = api.submit_revenue_report(
            lid,
            create_revenue_report_payload(
                "2026-07-15T00:00:00Z", "2026-07-31T00:00:00Z", 2000, stale_version,
            ),
            buyer,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh_version = get_license(lid)["version"]
        assert fresh_version == stale_version + 1, (
            "the booked report advanced the license version by exactly one"
        )
        second = validate_success(api.submit_revenue_report(
            lid,
            create_revenue_report_payload(
                "2026-07-15T00:00:00Z", "2026-07-31T00:00:00Z", 2000, fresh_version,
            ),
            buyer,
        ), 201)
        assert_revenue_report(second)

        reports = list_reports_for_license(lid)
        assert len(reports) == 2
        assert all(r["report_status"] == "SUBMITTED" for r in reports)


class TestReportValidation:
    def test_report_with_future_period_returns_422(self, api):
        """PRD §3.8: "The period end must be strictly after the period start and must not lie in the future relative to the logical clock — future-dated revenue is rejected with `ERR_REPORT_PERIOD_FUTURE` (422)."

        Design: Corner/validations/report_with_future_period_returns_422
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)

        resp = api.submit_revenue_report(
            license_agreement["id"],
            create_revenue_report_payload(
                "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z", 1000,
                license_agreement["version"],
            ),
            workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_FUTURE, 422)

    def test_report_with_zero_gross_returns_422(self, api):
        """PRD §3.8: "Gross revenue must be greater than 0, otherwise `ERR_NONPOSITIVE_REVENUE` (422)."

        Design: Corner/validations/report_with_zero_gross_returns_422
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)

        resp = api.submit_revenue_report(
            license_agreement["id"],
            create_revenue_report_payload(
                "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", 0,
                license_agreement["version"],
            ),
            workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NONPOSITIVE_REVENUE, 422)


class TestReportValidationPriority:
    def test_state_error_beats_fiscal_error_on_terminated_license(self, api):
        """PRD §2.9: "When multiple validations could reject the same request, the server evaluates them in a fixed priority order. Authentication (headers present, role known) runs first, then authorization and platform ownership, then request-body schema validation (required fields present, types correct, enum values known — including the rule that any window or period end is strictly after its start), then existence of every referenced resource, then state checks, then business-safety rules (embargo, segregation of duties), then business-referential rules (line membership, duplicate line slots), then business-temporal rules (window containment, clock monotonicity), then business-constraint rules (duplicate slot tuples, exclusivity and holdback conflicts, blocked lines, empty acceptance, statement period overlap, delivery completeness), and finally business-fiscal rules (positive revenue, fee-structure consistency)."
        PRD §3.8: "Only the `PlatformBuyer` who owns the license may submit, and the license must be `EXECUTED` or `ACTIVE` with a `fee_model` other than `FLAT_FEE` — flat-fee deals have no revenue share to report — otherwise the submission is rejected with `ERR_LICENSE_NOT_REPORTABLE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_terminal_license_report
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)
        lid = license_agreement["id"]
        terminated = validate_success(api.terminate_license(lid, RM), 200)

        resp = api.submit_revenue_report(
            lid,
            create_revenue_report_payload(
                "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", -500,
                terminated["version"],
            ),
            workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_REPORTABLE, 409)

    def test_rejected_report_books_nothing(self, api):
        """PRD §3.8: "Only the `PlatformBuyer` who owns the license may submit, and the license must be `EXECUTED` or `ACTIVE` with a `fee_model` other than `FLAT_FEE` — flat-fee deals have no revenue share to report — otherwise the submission is rejected with `ERR_LICENSE_NOT_REPORTABLE` (409)."
        PRD §3.8: "Reports can be listed with optional `license_id` and `report_status` filters."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_terminal_license_report
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)
        lid = license_agreement["id"]
        terminated = validate_success(api.terminate_license(lid, RM), 200)

        resp = api.submit_revenue_report(
            lid,
            create_revenue_report_payload(
                "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", -500,
                terminated["version"],
            ),
            workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_REPORTABLE, 409)

        assert list_reports_for_license(lid) == [], (
            "a rejected submission must not persist a revenue report"
        )
        ledger = get_license(lid)
        assert ledger["recouped_cents"] == 0
        assert ledger["royalty_payable_cents"] == 0
