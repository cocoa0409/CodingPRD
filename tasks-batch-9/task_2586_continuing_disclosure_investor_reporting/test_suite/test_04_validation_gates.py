"""Validation-ladder gates for the Continuing Disclosure & Investor Reporting API.

Every test in this module is about *which rung of the §2.10 ladder answers first*:
the exact value at which a creation gate is satisfied rather than fired, the
precedence of the issue gate over the undertaking-uniqueness rule, the ordered
pair of cycle-creation content gates, subject exclusivity on a mere DRAFT, the
conditional correction-reason requirement, global receipt-id uniqueness, the
two arms of the remediation-evidence check, and the pagination bounds.

Each test starts against an empty database whose logical clock reads its startup
value of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    FD,
    OFFICER,
    ApiErrorId,
    api_client,
    assemble,
    attest_item,
    confirm,
    create_annual_report_filing,
    create_bond_issue,
    create_content_requirement,
    create_cycle,
    create_engagement,
    create_event_filing,
    create_notice,
    create_undertaking,
    defease_issue,
    determine_notice,
    is_iso8601_timestamp,
    issue_version,
    list_content_items,
    list_failure_events,
    make_agent_headers,
    prepare_item,
    read_engagement,
    read_failure_event,
    read_filing,
    read_notice,
    read_undertaking,
    run_sweep,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Module-local composites.  fixtures.py builds no chain that pairs a sibling
# credit program against a swept-delinquent cycle, nor one that leaves two
# MATERIAL notices unfiled on a single issue, so those two are assembled here.
# --------------------------------------------------------------------------- #

ISSUE_KWARGS = {
    "issuer_program_code": "CIVICCENTER",
    "series_designation": "2026A",
    "security_type": "REVENUE",
    "dated_date": "2024-04-01",
    "final_maturity_date": "2056-04-01",
    "original_par_amount_cents": 100000000,
}


def _make_issue(**overrides):
    payload = dict(ISSUE_KWARGS)
    payload.update(overrides)
    return create_bond_issue(**payload)


def _setup_issue_with_two_material_notices():
    """One OUTSTANDING issue, one ACTIVE undertaking, two distinct MATERIAL notices."""
    issue = _make_issue()
    undertaking = create_undertaking(issue["id"])
    n1 = create_notice(
        issue["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
    )
    n2 = create_notice(
        issue["id"], event_type="MERGER_OR_SALE", occurrence_date="2026-07-28"
    )
    determine_notice(n1["id"], "MATERIAL", "Successor trustee appointed.")
    determine_notice(n2["id"], "MATERIAL", "Asset transfer is material.")
    return {
        "issue": issue,
        "undertaking": undertaking,
        "n1": read_notice(n1["id"]),
        "n2": read_notice(n2["id"]),
    }


def _setup_confirmed_notice_filing():
    """The chain above plus an ACTIVE engagement and one CONFIRMED filing on n1."""
    context = _setup_issue_with_two_material_notices()
    context["engagement"] = create_engagement(context["undertaking"]["id"])
    filing = create_event_filing(context["issue"]["id"], context["n1"]["id"])
    submit(filing["id"], context["engagement"]["id"])
    context["f1"] = confirm(filing["id"], context["engagement"]["id"], "EMMA-0001")
    return context


def _setup_delinquent_cycle_beside_sibling_program():
    """A swept-DELINQUENT FY2025 cycle on program CIVICCENTER, plus a CONFIRMED
    filing that belongs to an entirely different program's undertaking."""
    issue_a = _make_issue()
    issue_b = _make_issue(issuer_program_code="HARBORWORKS")
    und_a = create_undertaking(issue_a["id"])
    und_b = create_undertaking(issue_b["id"])
    create_content_requirement(
        und_a["id"],
        kind="OPERATING_DATA_TABLE",
        label="Operating Data Tables",
        weight_bp=10000,
    )
    cycle_a = create_cycle(
        und_a["id"],
        fiscal_year_label="FY2025",
        period_start_date="2024-07-01",
        period_end_date="2025-06-30",
    )
    eng_a = create_engagement(und_a["id"])
    eng_b = create_engagement(und_b["id"])
    nb = create_notice(
        issue_b["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
    )
    determine_notice(nb["id"], "MATERIAL", "Successor trustee appointed.")
    fb = create_event_filing(issue_b["id"], nb["id"])
    submit(fb["id"], eng_b["id"])
    fb = confirm(fb["id"], eng_b["id"], "EMMA-B-0001")
    sweep = run_sweep()
    events = [
        e
        for e in list_failure_events(cycle_id=cycle_a["id"])
        if e["kind"] == "ANNUAL_REPORT_MISSED"
    ]
    assert len(events) == 1, f"Expected one ANNUAL_REPORT_MISSED event, got {events}"
    return {
        "issue_a": issue_a,
        "issue_b": issue_b,
        "und_a": und_a,
        "und_b": und_b,
        "cycle_a": cycle_a,
        "eng_a": eng_a,
        "eng_b": eng_b,
        "fb": fb,
        "sweep": sweep,
        "fte": events[0],
    }


def _ready_and_assemble_cycle(cycle_id):
    """Drive the sole content item of a DELINQUENT cycle to READY and reassemble."""
    item = list_content_items(cycle_id)[0]
    prepare_item(
        item["id"],
        data_as_of_date="2025-06-30",
        source_document_ref="OPDATA-FY2025.xlsx",
    )
    attest_item(item["id"])
    return assemble(cycle_id)


class TestCreationGateSatisfactionBoundaries:
    """The exact values at which each creation gate is satisfied rather than fired."""

    def test_first_undertaking_two_kinds_closing_at_10000_open_a_cycle(self):
        """The first undertaking, two distinct kinds summing to exactly 10000, and a cycle all pass.

        PRD §3.2: "At most one undertaking may exist per `issue_id`, and the guard is absolute rather than merely current: a second undertaking on the same issue is refused with `ERR_UNDERTAKING_ALREADY_EXISTS` even when the incumbent is already `TERMINATED`, because that terminated row still owns the historical failure events the five-year lookback has to find."
        PRD §3.2: "Only one requirement may exist per undertaking-and-`kind` pair; a second is refused with `ERR_DUPLICATE_REQUIREMENT`."
        PRD §3.3: "Over that non-empty set, `content_weight_bp_total` must then equal exactly 10000 basis points, or the request is refused with `ERR_CONTENT_WEIGHTS_UNBALANCED`."
        Design: Corner/validations/every_creation_gate_passes_at_its_exact_satisfaction_boundary
        """
        issue = _make_issue()

        undertaking = validate_success(
            api_client.create_undertaking(
                {"issue_id": issue["id"], "fiscal_year_end_month_day": "06-30"}, FD
            ),
            201,
        )
        assert undertaking["status"] == "ACTIVE"

        validate_success(
            api_client.create_content_requirement(
                {
                    "undertaking_id": undertaking["id"],
                    "kind": "AUDITED_FINANCIALS",
                    "label": "Audited Financial Statements",
                    "weight_bp": 6000,
                },
                OFFICER,
            ),
            201,
        )
        validate_success(
            api_client.create_content_requirement(
                {
                    "undertaking_id": undertaking["id"],
                    "kind": "OPERATING_DATA_TABLE",
                    "label": "Operating Data Tables",
                    "weight_bp": 4000,
                },
                OFFICER,
            ),
            201,
        )
        assert read_undertaking(undertaking["id"])["content_weight_bp_total"] == 10000

        cycle = validate_success(
            api_client.create_annual_report_cycle(
                {
                    "undertaking_id": undertaking["id"],
                    "fiscal_year_label": "FY2026",
                    "period_start_date": "2025-07-01",
                    "period_end_date": "2026-06-30",
                },
                OFFICER,
            ),
            201,
        )
        assert cycle["status"] == "DRAFTING"

    def test_occurrence_date_equal_to_clock_and_single_day_review_window_are_accepted(self):
        """A notice dated today and a one-day review window sit on the legal side of both bounds.

        PRD §3.5: "Then `occurrence_date` must not lie after the logical clock's date, or the request is refused with `ERR_OCCURRENCE_DATE_IN_FUTURE`."
        PRD §3.6: "The window must be non-empty in the sense that `review_window_end_date` may not precede `review_window_start_date`, and a violation of that or of the principal floor is refused with `ERR_INVALID_REQUEST`."
        PRD §3.6: "`materiality_ratio_bp` is derived once, at creation, as `principal_amount_cents` multiplied by 10000, divided by the issue's `outstanding_par_amount_cents`, rounded half-up to a whole basis point."
        Design: Corner/validations/every_creation_gate_passes_at_its_exact_satisfaction_boundary
        """
        issue = _make_issue()
        create_undertaking(issue["id"])

        notice = validate_success(
            api_client.create_material_event_notice(
                {
                    "issue_id": issue["id"],
                    "event_type": "TRUSTEE_SUBSTITUTION",
                    "occurrence_date": "2026-08-01",
                },
                OFFICER,
            ),
            201,
        )
        assert notice["status"] == "DETERMINATION_PENDING"
        assert notice["occurrence_date"] == "2026-08-01"

        placement = validate_success(
            api_client.create_direct_placement(
                {
                    "issue_id": issue["id"],
                    "lender_name": "Harbor National Bank",
                    "principal_amount_cents": 2000000,
                    "execution_date": "2026-07-28",
                    "review_window_start_date": "2026-08-10",
                    "review_window_end_date": "2026-08-10",
                    "disclosure_practice": "VOLUNTARY",
                },
                OFFICER,
            ),
            201,
        )
        assert placement["status"] == "RECEIVED"
        assert placement["materiality_ratio_bp"] == 200


class TestIssueGateOutranksUndertakingUniqueness:
    """Rung 9 answers before rung 14 when both are violated by the same request."""

    def test_second_undertaking_on_an_outstanding_issue_is_a_uniqueness_violation(self):
        """While the issue is OUTSTANDING only the uniqueness rule is broken.

        PRD §2.10: "14. At most one `Undertaking` per `issue_id`, in any status → `ERR_UNDERTAKING_ALREADY_EXISTS` (409). Applies to `POST /disclosure/undertakings`."
        PRD §3.2: "At most one undertaking may exist per `issue_id`, and the guard is absolute rather than merely current: a second undertaking on the same issue is refused with `ERR_UNDERTAKING_ALREADY_EXISTS` even when the incumbent is already `TERMINATED`, because that terminated row still owns the historical failure events the five-year lookback has to find."
        Design: Corner/validations/defeased_issue_outranks_the_undertaking_uniqueness_rule
        """
        issue = _make_issue(original_par_amount_cents=50000000)
        assert issue["outstanding_par_amount_cents"] == 50000000
        create_undertaking(issue["id"])

        validate_error(
            api_client.create_undertaking(
                {"issue_id": issue["id"], "fiscal_year_end_month_day": "12-31"}, FD
            ),
            ApiErrorId.ERR_UNDERTAKING_ALREADY_EXISTS.value,
        )

    def test_defeased_issue_outranks_the_undertaking_uniqueness_rule(self):
        """Once the issue is DEFEASED the issue gate answers, not the uniqueness rule.

        PRD §2.10: "Checks are evaluated in a single strictly ordered ladder, and the **first** rule that fails is the **only** error returned."
        PRD §2.10: "9. Issue gate — the `BondIssue` that owns the target row is `OUTSTANDING` → `ERR_ISSUE_NOT_OUTSTANDING` (409). Applies to `POST /disclosure/undertakings`, `POST /disclosure/annual-report-cycles`, `POST /disclosure/material-event-notices`, `POST /disclosure/direct-placements`, `POST /disclosure/filings`, and `POST /disclosure/official-statements/{id}/compliance-review`."
        PRD §2.10: "14. At most one `Undertaking` per `issue_id`, in any status → `ERR_UNDERTAKING_ALREADY_EXISTS` (409). Applies to `POST /disclosure/undertakings`."
        Design: Corner/validations/defeased_issue_outranks_the_undertaking_uniqueness_rule
        """
        issue = _make_issue(original_par_amount_cents=50000000)
        undertaking = create_undertaking(issue["id"])

        defeased = defease_issue(
            issue["id"],
            defeasance_type="LEGAL",
            escrow_deposit_cents=50000000,
            occurrence_date="2026-08-01",
        )
        assert defeased["status"] == "DEFEASED"
        assert defeased["outstanding_par_amount_cents"] == 0

        terminated = read_undertaking(undertaking["id"])
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_cause"] == "DEFEASANCE"

        validate_error(
            api_client.create_undertaking(
                {"issue_id": issue["id"], "fiscal_year_end_month_day": "12-31"}, FD
            ),
            ApiErrorId.ERR_ISSUE_NOT_OUTSTANDING.value,
        )

        _rows, meta = validate_paginated(
            api_client.list_undertakings(FD, params={"issue_id": issue["id"], "limit": 100})
        )
        assert meta["total_count"] == 1, (
            "neither refused attempt may persist a row, and the TERMINATED incumbent is retained"
        )


class TestRequirementUniqueness:
    """Uniqueness keys on the (undertaking_id, kind) pair and nothing else."""

    def test_requirement_uniqueness_is_per_undertaking_and_kind(self):
        """A different label and weight do not make the same kind a different requirement.

        PRD §3.2: "Only one requirement may exist per undertaking-and-`kind` pair; a second is refused with `ERR_DUPLICATE_REQUIREMENT`."
        PRD §3.2: "Each accepted requirement re-derives the undertaking's `content_weight_bp_total` as the sum of `weight_bp` across all of that undertaking's requirements, which is the figure the weight-closure gate of §3.3 tests."
        Design: Corner/validations/requirement_uniqueness_is_per_undertaking_and_kind
        """
        issue_a = _make_issue()
        und_a = create_undertaking(issue_a["id"])
        create_content_requirement(
            und_a["id"],
            kind="AUDITED_FINANCIALS",
            label="Audited Financial Statements",
            weight_bp=6000,
        )

        validate_error(
            api_client.create_content_requirement(
                {
                    "undertaking_id": und_a["id"],
                    "kind": "AUDITED_FINANCIALS",
                    "label": "Audited Financials (Enterprise Funds)",
                    "weight_bp": 1500,
                },
                OFFICER,
            ),
            ApiErrorId.ERR_DUPLICATE_REQUIREMENT.value,
        )
        assert read_undertaking(und_a["id"])["content_weight_bp_total"] == 6000, (
            "the refused row added nothing; the check precedes the derived total"
        )

    def test_a_different_kind_and_a_different_undertaking_are_unrelated(self):
        """The pair is the key, so neither a new kind here nor the same kind elsewhere collides.

        PRD §3.2: "Only one requirement may exist per undertaking-and-`kind` pair; a second is refused with `ERR_DUPLICATE_REQUIREMENT`."
        PRD §3.2: "Each accepted requirement re-derives the undertaking's `content_weight_bp_total` as the sum of `weight_bp` across all of that undertaking's requirements, which is the figure the weight-closure gate of §3.3 tests."
        Design: Corner/validations/requirement_uniqueness_is_per_undertaking_and_kind
        """
        issue_a = _make_issue()
        issue_b = _make_issue(series_designation="2026B")
        und_a = create_undertaking(issue_a["id"])
        und_b = create_undertaking(issue_b["id"])
        create_content_requirement(
            und_a["id"],
            kind="AUDITED_FINANCIALS",
            label="Audited Financial Statements",
            weight_bp=6000,
        )

        validate_success(
            api_client.create_content_requirement(
                {
                    "undertaking_id": und_a["id"],
                    "kind": "OPERATING_DATA_TABLE",
                    "label": "Operating Data Tables",
                    "weight_bp": 4000,
                },
                OFFICER,
            ),
            201,
        )
        validate_success(
            api_client.create_content_requirement(
                {
                    "undertaking_id": und_b["id"],
                    "kind": "AUDITED_FINANCIALS",
                    "label": "Audited Financial Statements",
                    "weight_bp": 10000,
                },
                OFFICER,
            ),
            201,
        )

        _rows, meta = validate_paginated(
            api_client.list_content_requirements(
                OFFICER, params={"undertaking_id": und_a["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 2
        assert read_undertaking(und_a["id"])["content_weight_bp_total"] == 10000


class TestCycleContentGateOrdering:
    """Rung 17 must speak before rung 18, or absence is indistinguishable from imbalance."""

    def test_empty_requirement_set_reports_absence_not_imbalance(self):
        """A zero-sum requirement set answers ERR_NO_CONTENT_REQUIREMENTS, then imbalance.

        PRD §3.3: "The undertaking must first have at least one `ContentRequirement` row, or the request is refused with `ERR_NO_CONTENT_REQUIREMENTS`; there is nothing to snapshot otherwise."
        PRD §3.3: "The ordering is deliberate: an empty requirement set sums to zero and so fails closure too, which would make the first error unreachable if closure were tested first."
        PRD §3.3: "Over that non-empty set, `content_weight_bp_total` must then equal exactly 10000 basis points, or the request is refused with `ERR_CONTENT_WEIGHTS_UNBALANCED`."
        Design: Corner/validations/empty_requirement_set_reports_absence_not_imbalance
        """
        issue = _make_issue()
        undertaking = create_undertaking(issue["id"])
        assert undertaking["content_weight_bp_total"] == 0

        cycle_payload = {
            "undertaking_id": undertaking["id"],
            "fiscal_year_label": "FY2026",
            "period_start_date": "2025-07-01",
            "period_end_date": "2026-06-30",
        }

        validate_error(
            api_client.create_annual_report_cycle(cycle_payload, OFFICER),
            ApiErrorId.ERR_NO_CONTENT_REQUIREMENTS.value,
        )

        create_content_requirement(
            undertaking["id"],
            kind="AUDITED_FINANCIALS",
            label="Audited Financial Statements",
            weight_bp=6000,
        )

        validate_error(
            api_client.create_annual_report_cycle(cycle_payload, OFFICER),
            ApiErrorId.ERR_CONTENT_WEIGHTS_UNBALANCED.value,
        )

        _rows, meta = validate_paginated(
            api_client.list_annual_report_cycles(
                OFFICER, params={"undertaking_id": undertaking["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0, "neither refused attempt left a partial cycle behind"

    def test_the_same_request_succeeds_once_the_weights_close_at_10000(self):
        """The third attempt on the identical payload opens the cycle and snapshots both items.

        PRD §3.3: "Over that non-empty set, `content_weight_bp_total` must then equal exactly 10000 basis points, or the request is refused with `ERR_CONTENT_WEIGHTS_UNBALANCED`."
        PRD §3.3: "One **`CycleContentItem`** is minted for each `ContentRequirement` of the undertaking, each carrying the `cycle_id` of the new cycle, the `content_requirement_id` of its source requirement, `status` `NOT_STARTED`, `readiness_factor` 0.0, and a `weight_bp_snapshot` copied from the requirement's `weight_bp` at that instant."
        PRD §3.3: "The cycle itself opens in `status` `DRAFTING` with `version` 1, `completeness_score_pct` 0.00, `days_late` 0, and null `assembled_by_user_id`, `assembled_at`, `filed_filing_id`, `filed_at`, `timeliness_basis_applied`, and `withdrawal_reason`."
        Design: Corner/validations/empty_requirement_set_reports_absence_not_imbalance
        """
        issue = _make_issue()
        undertaking = create_undertaking(issue["id"])
        cycle_payload = {
            "undertaking_id": undertaking["id"],
            "fiscal_year_label": "FY2026",
            "period_start_date": "2025-07-01",
            "period_end_date": "2026-06-30",
        }
        validate_error(
            api_client.create_annual_report_cycle(cycle_payload, OFFICER),
            ApiErrorId.ERR_NO_CONTENT_REQUIREMENTS.value,
        )
        create_content_requirement(
            undertaking["id"],
            kind="AUDITED_FINANCIALS",
            label="Audited Financial Statements",
            weight_bp=6000,
        )
        validate_error(
            api_client.create_annual_report_cycle(cycle_payload, OFFICER),
            ApiErrorId.ERR_CONTENT_WEIGHTS_UNBALANCED.value,
        )
        create_content_requirement(
            undertaking["id"],
            kind="OPERATING_DATA_TABLE",
            label="Operating Data Tables",
            weight_bp=4000,
        )

        cycle = validate_success(
            api_client.create_annual_report_cycle(cycle_payload, OFFICER), 201
        )
        assert cycle["status"] == "DRAFTING"
        assert float(cycle["completeness_score_pct"]) == 0.00

        _items, item_meta = validate_paginated(
            api_client.list_content_items(
                OFFICER, params={"cycle_id": cycle["id"], "limit": 100}
            )
        )
        assert item_meta["total_count"] == 2

        _cycles, cycle_meta = validate_paginated(
            api_client.list_annual_report_cycles(
                OFFICER, params={"undertaking_id": undertaking["id"], "limit": 100}
            )
        )
        assert cycle_meta["total_count"] == 1


class TestSubjectExclusivity:
    """A DRAFT filing already occupies its four-field subject tuple."""

    def test_a_second_draft_on_the_same_subject_is_refused(self):
        """Subject exclusivity counts DRAFT filings, not only filed ones.

        PRD §3.7: "No other `Filing` may already carry the identical four-field subject tuple of `filing_type`, `cycle_id`, `material_event_id`, and `direct_placement_id` in `status` `DRAFT`, `SUBMITTED`, or `CONFIRMED`, unless this new draft supplies `supersedes_filing_id` naming that exact `CONFIRMED` filing; otherwise the draft is refused with `ERR_SUBJECT_ALREADY_FILED`."
        PRD §3.7: "The draft opens at `status` `DRAFT`, `version` 1, `submission_attempt_count` 0, with `submitted_at`, `submitted_by_user_id`, `submitting_engagement_id`, `repository_receipt_id`, `repository_confirmed_at`, `rejection_reason`, and `superseded_by_filing_id` all null."
        Design: Corner/validations/a_second_draft_on_the_same_subject_is_refused
        """
        context = _setup_issue_with_two_material_notices()
        issue_id = context["issue"]["id"]
        n1 = context["n1"]["id"]

        first = validate_success(
            api_client.create_filing(
                {
                    "issue_id": issue_id,
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": n1,
                    "expected_issue_version": issue_version(issue_id),
                },
                OFFICER,
            ),
            201,
        )
        assert first["status"] == "DRAFT"

        validate_error(
            api_client.create_filing(
                {
                    "issue_id": issue_id,
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": n1,
                    "expected_issue_version": issue_version(issue_id),
                },
                OFFICER,
            ),
            ApiErrorId.ERR_SUBJECT_ALREADY_FILED.value,
        )

        _rows, meta = validate_paginated(
            api_client.list_filings(OFFICER, params={"material_event_id": n1, "limit": 100})
        )
        assert meta["total_count"] == 1, "the refused draft was not persisted"

    def test_a_second_notice_is_a_different_subject_and_drafts_freely(self):
        """The tuple is the whole subject, so another notice on the same issue is unaffected.

        PRD §3.7: "No other `Filing` may already carry the identical four-field subject tuple of `filing_type`, `cycle_id`, `material_event_id`, and `direct_placement_id` in `status` `DRAFT`, `SUBMITTED`, or `CONFIRMED`, unless this new draft supplies `supersedes_filing_id` naming that exact `CONFIRMED` filing; otherwise the draft is refused with `ERR_SUBJECT_ALREADY_FILED`."
        Design: Corner/validations/a_second_draft_on_the_same_subject_is_refused
        """
        context = _setup_issue_with_two_material_notices()
        issue_id = context["issue"]["id"]
        n1 = context["n1"]["id"]
        n2 = context["n2"]["id"]

        create_event_filing(issue_id, n1)
        version_after_first_draft = issue_version(issue_id)

        validate_error(
            api_client.create_filing(
                {
                    "issue_id": issue_id,
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": n1,
                    "expected_issue_version": version_after_first_draft,
                },
                OFFICER,
            ),
            ApiErrorId.ERR_SUBJECT_ALREADY_FILED.value,
        )

        second = validate_success(
            api_client.create_filing(
                {
                    "issue_id": issue_id,
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": n2,
                    "expected_issue_version": version_after_first_draft,
                },
                OFFICER,
            ),
            201,
        )
        assert second["status"] == "DRAFT", (
            "reusing the pre-refusal issue version also proves the refused draft "
            "did not advance it"
        )


class TestCorrectionReasonIsConditional:
    """correction_reason is required exactly when supersedes_filing_id is present."""

    def test_a_superseding_draft_without_a_correction_reason_is_refused(self):
        """Naming a supersede target arms the correction-reason requirement.

        PRD §3.7: "A correcting draft must also carry a non-empty `correction_reason`, checked at draft creation and refused with `ERR_CORRECTION_REASON_REQUIRED`."
        PRD §2.10: "33. Repository confirmation payload and correction payload — `repository_receipt_id` unique across all filings → `ERR_RECEIPT_ID_DUPLICATE` (409) on `POST /disclosure/filings/{id}/confirm`; a correcting draft carrying `supersedes_filing_id` must also carry a non-empty `correction_reason` → `ERR_CORRECTION_REASON_REQUIRED` (422) on `POST /disclosure/filings`."
        Design: Corner/validations/correction_reason_is_required_only_for_a_superseding_draft
        """
        context = _setup_confirmed_notice_filing()
        assert context["f1"]["status"] == "CONFIRMED"

        validate_error(
            api_client.create_filing(
                {
                    "issue_id": context["issue"]["id"],
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": context["n1"]["id"],
                    "supersedes_filing_id": context["f1"]["id"],
                    "expected_issue_version": issue_version(context["issue"]["id"]),
                },
                OFFICER,
            ),
            ApiErrorId.ERR_CORRECTION_REASON_REQUIRED.value,
        )

    def test_the_identical_draft_is_accepted_once_the_reason_is_supplied(self):
        """Naming the CONFIRMED predecessor explicitly also disarms subject exclusivity.

        PRD §3.7: "A correcting draft must also carry a non-empty `correction_reason`, checked at draft creation and refused with `ERR_CORRECTION_REASON_REQUIRED`."
        PRD §3.7: "No other `Filing` may already carry the identical four-field subject tuple of `filing_type`, `cycle_id`, `material_event_id`, and `direct_placement_id` in `status` `DRAFT`, `SUBMITTED`, or `CONFIRMED`, unless this new draft supplies `supersedes_filing_id` naming that exact `CONFIRMED` filing; otherwise the draft is refused with `ERR_SUBJECT_ALREADY_FILED`."
        PRD §3.7: "Creating the draft moves no subject: the subject advances only when the draft is submitted."
        Design: Corner/validations/correction_reason_is_required_only_for_a_superseding_draft
        """
        context = _setup_confirmed_notice_filing()
        issue_id = context["issue"]["id"]
        f1_id = context["f1"]["id"]
        version_before = issue_version(issue_id)

        validate_error(
            api_client.create_filing(
                {
                    "issue_id": issue_id,
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": context["n1"]["id"],
                    "supersedes_filing_id": f1_id,
                    "expected_issue_version": version_before,
                },
                OFFICER,
            ),
            ApiErrorId.ERR_CORRECTION_REASON_REQUIRED.value,
        )

        correction = validate_success(
            api_client.create_filing(
                {
                    "issue_id": issue_id,
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": context["n1"]["id"],
                    "supersedes_filing_id": f1_id,
                    "correction_reason": "Restated the trustee's legal name.",
                    "expected_issue_version": version_before,
                },
                OFFICER,
            ),
            201,
        )
        assert correction["status"] == "DRAFT"
        assert correction["supersedes_filing_id"] == f1_id
        assert correction["correction_reason"] == "Restated the trustee's legal name."

        notice = read_notice(context["n1"]["id"])
        assert notice["status"] == "FILED_TIMELY"
        assert notice["filed_filing_id"] == f1_id, (
            "drafting a correction repoints nothing; that happens only at confirmation"
        )

    def test_a_non_superseding_draft_may_carry_a_correction_reason(self):
        """The requirement is conditional, not a prohibition on the field itself.

        PRD §3.7: "A `DisclosureOfficer` drafts one by naming the `issue_id`, the `filing_type`, and the `expected_issue_version` that arms the concurrency guard of §2.8, plus exactly one of `cycle_id`, `material_event_id`, or `direct_placement_id`, and optionally `supersedes_filing_id` and `correction_reason`."
        PRD §3.7: "A correcting draft must also carry a non-empty `correction_reason`, checked at draft creation and refused with `ERR_CORRECTION_REASON_REQUIRED`."
        Design: Corner/validations/correction_reason_is_required_only_for_a_superseding_draft
        """
        context = _setup_confirmed_notice_filing()
        issue_id = context["issue"]["id"]

        plain = validate_success(
            api_client.create_filing(
                {
                    "issue_id": issue_id,
                    "filing_type": "MATERIAL_EVENT_NOTICE",
                    "material_event_id": context["n2"]["id"],
                    "correction_reason": "Carried over from the prior submission package.",
                    "expected_issue_version": issue_version(issue_id),
                },
                OFFICER,
            ),
            201,
        )
        assert plain["status"] == "DRAFT"
        assert plain["supersedes_filing_id"] is None


def _setup_two_submitted_event_filings():
    """Two SUBMITTED MATERIAL_EVENT_NOTICE filings on two MATERIAL notices, one agent."""
    context = _setup_issue_with_two_material_notices()
    context["engagement"] = create_engagement(context["undertaking"]["id"])
    f1 = create_event_filing(context["issue"]["id"], context["n1"]["id"])
    f2 = create_event_filing(context["issue"]["id"], context["n2"]["id"])
    submit(f1["id"], context["engagement"]["id"])
    submit(f2["id"], context["engagement"]["id"])
    context["f1"] = read_filing(f1["id"])
    context["f2"] = read_filing(f2["id"])
    return context


class TestRepositoryReceiptUniqueness:
    """A receipt id is unique across every Filing row, whatever its subject."""

    def test_a_receipt_id_taken_by_another_subject_is_refused(self):
        """Uniqueness is global across filings, not scoped to a subject or an agent.

        PRD §3.7: "Recording the repository's confirmation takes a `repository_receipt_id`, requires `status` `SUBMITTED`, requires the acting `X-User-ID` to be the `submitting_engagement_id`, and requires the receipt id to be unique across every `Filing` row, failing which the call is refused with `ERR_RECEIPT_ID_DUPLICATE`."
        PRD §3.11: "In cents: take the lesser of F and 4 at 45000 cents, plus the lesser of 5 and the excess of F over 4 (floored at zero) at 32500 cents, plus the excess of F over 9 (floored at zero) at 25000 cents."
        PRD §3.11: "The cap and the floor then apply in this exact nested order: the subtotal plus surcharge is first capped at 12,000 dollars (1200000 cents), and that capped figure is then raised to the minimum annual fee of 3,000 dollars (300000 cents) if it falls below it."
        PRD §2.10: "33. Repository confirmation payload and correction payload — `repository_receipt_id` unique across all filings → `ERR_RECEIPT_ID_DUPLICATE` (409) on `POST /disclosure/filings/{id}/confirm`; a correcting draft carrying `supersedes_filing_id` must also carry a non-empty `correction_reason` → `ERR_CORRECTION_REASON_REQUIRED` (422) on `POST /disclosure/filings`."
        Design: Corner/validations/repository_receipt_ids_are_unique_across_all_filings
        """
        context = _setup_two_submitted_event_filings()
        engagement_id = context["engagement"]["id"]

        first = confirm(context["f1"]["id"], engagement_id, "EMMA-DUP-77")
        assert first["status"] == "CONFIRMED"
        assert first["repository_receipt_id"] == "EMMA-DUP-77"

        engagement = read_engagement(engagement_id)
        assert engagement["billable_filing_count"] == 1
        assert engagement["invoice_total_cents"] == 300000, (
            "one filing bills 45000 + a 250000 retainer, which the annual floor lifts to 300000"
        )

        validate_error(
            api_client.confirm_filing(
                context["f2"]["id"],
                {"repository_receipt_id": "EMMA-DUP-77"},
                make_agent_headers(engagement_id),
            ),
            ApiErrorId.ERR_RECEIPT_ID_DUPLICATE.value,
        )

    def test_the_refused_confirmation_writes_nothing_and_bills_nothing(self):
        """A confirmation that errored cannot have run its ledger cascade.

        PRD §3.7: "Recording the repository's confirmation takes a `repository_receipt_id`, requires `status` `SUBMITTED`, requires the acting `X-User-ID` to be the `submitting_engagement_id`, and requires the receipt id to be unique across every `Filing` row, failing which the call is refused with `ERR_RECEIPT_ID_DUPLICATE`."
        PRD §3.7: "It sets `repository_confirmed_at` from the logical clock and stamps the receipt."
        PRD §3.11: "The first input is the conserved filing count: let F be the number of `Filing` rows whose `submitting_engagement_id` is this engagement and whose `status` is exactly `CONFIRMED`."
        PRD §2.11: "Third, derived quantities are **recomputed from source, never adjusted in place**."
        PRD §3.11: "For any other posture the surcharge is zero."
        Design: Corner/validations/repository_receipt_ids_are_unique_across_all_filings
        """
        context = _setup_two_submitted_event_filings()
        engagement_id = context["engagement"]["id"]
        f2_id = context["f2"]["id"]
        confirm(context["f1"]["id"], engagement_id, "EMMA-DUP-77")

        validate_error(
            api_client.confirm_filing(
                f2_id,
                {"repository_receipt_id": "EMMA-DUP-77"},
                make_agent_headers(engagement_id),
            ),
            ApiErrorId.ERR_RECEIPT_ID_DUPLICATE.value,
        )

        refused = read_filing(f2_id)
        assert refused["status"] == "SUBMITTED"
        assert refused["repository_receipt_id"] is None
        assert refused["repository_confirmed_at"] is None

        engagement = read_engagement(engagement_id)
        assert engagement["billable_filing_count"] == 1
        assert engagement["invoice_total_cents"] == 300000

        second = confirm(f2_id, engagement_id, "EMMA-0002")
        assert second["status"] == "CONFIRMED"
        assert second["repository_receipt_id"] == "EMMA-0002"

        engagement = read_engagement(engagement_id)
        assert engagement["billable_filing_count"] == 2
        assert engagement["invoice_total_cents"] == 340000, (
            "two filings bill 45000 + 45000 on top of the 250000 retainer"
        )


class TestRemediationEvidenceValidity:
    """Both arms of the remediation-evidence test return one error for two reasons."""

    def test_a_confirmed_filing_of_a_sibling_program_is_not_evidence(self):
        """The evidence is CONFIRMED, yet it belongs to another undertaking entirely.

        PRD §3.8: "The named filing must be `CONFIRMED`, and its subject must belong to the same undertaking as the event; the test has two arms, keyed on the event's own subject."
        PRD §3.8: "When the event's `cycle_id` is not null, the filing's `cycle_id` must equal it — the delinquent annual report is exactly what still has to be filed."
        PRD §3.8: "A failure of either arm returns `ERR_REMEDIATION_FILING_INVALID`."
        PRD §2.10: "31. Remediation evidence → `ERR_REMEDIATION_FILING_INVALID` (409). Applies to `POST /disclosure/failure-to-file-events/{id}/remediate`."
        Design: Corner/validations/remediation_evidence_must_be_confirmed_and_belong_to_the_same_undertaking
        """
        context = _setup_delinquent_cycle_beside_sibling_program()
        assert context["cycle_a"]["due_date"] == "2026-01-26"
        assert context["fb"]["status"] == "CONFIRMED"
        assert context["sweep"]["delinquent_cycle_count"] == 1
        assert context["sweep"]["failure_event_created_count"] == 1

        fte = context["fte"]
        assert fte["status"] == "OPEN"
        assert fte["days_late"] == 187
        assert fte["severity"] == "MAJOR"

        validate_error(
            api_client.remediate_failure_event(
                fte["id"],
                {
                    "remediation_filing_id": context["fb"]["id"],
                    "remediation_note": "Filed under the harbor program.",
                },
                OFFICER,
            ),
            ApiErrorId.ERR_REMEDIATION_FILING_INVALID.value,
        )
        assert read_failure_event(fte["id"])["status"] == "OPEN", (
            "the refused remediation left the failure exactly where it stood"
        )

    def test_a_draft_filing_of_the_right_cycle_is_not_evidence_either(self):
        """The subject matches, but a filing that never reached the repository proves nothing.

        PRD §3.8: "The named filing must be `CONFIRMED`, and its subject must belong to the same undertaking as the event; the test has two arms, keyed on the event's own subject."
        PRD §3.8: "A failure of either arm returns `ERR_REMEDIATION_FILING_INVALID`."
        PRD §3.7: "Creating the draft moves no subject: the subject advances only when the draft is submitted."
        Design: Corner/validations/remediation_evidence_must_be_confirmed_and_belong_to_the_same_undertaking
        """
        context = _setup_delinquent_cycle_beside_sibling_program()
        fte = context["fte"]

        reassembled = _ready_and_assemble_cycle(context["cycle_a"]["id"])
        assert reassembled["status"] == "READY_TO_FILE"

        fa = create_annual_report_filing(
            context["issue_a"]["id"], context["cycle_a"]["id"]
        )
        assert fa["status"] == "DRAFT"

        validate_error(
            api_client.remediate_failure_event(
                fte["id"],
                {
                    "remediation_filing_id": fa["id"],
                    "remediation_note": "Annual report drafted.",
                },
                OFFICER,
            ),
            ApiErrorId.ERR_REMEDIATION_FILING_INVALID.value,
        )
        still_open = read_failure_event(fte["id"])
        assert still_open["status"] == "OPEN"
        assert still_open["remediation_filing_id"] is None
        assert still_open["remediated_at"] is None

    def test_the_confirmation_that_makes_the_evidence_valid_also_arms_the_event(self):
        """From REMEDIATION_PENDING the same filing is finally accepted as evidence.

        PRD §3.8: "A cycle reaching `FILED_LATE` mints one with `kind` `ANNUAL_REPORT_LATE`, `undertaking_id` and `cycle_id` from the cycle, `material_event_id` null, `occurred_at` set to the cycle's `due_date`, `days_late` copied from the cycle's `days_late`, and `status` `OPEN` — but only if no event with that `cycle_id` already exists; if the delinquency sweep already minted one, its `kind` is left unchanged, its `days_late` is refreshed, and its `status` moves from `OPEN` to `REMEDIATION_PENDING`."
        PRD §3.8: "A `DisclosureOfficer` supplies a `remediation_filing_id` and a `remediation_note` against an event in `status` `OPEN` or `REMEDIATION_PENDING`, and the event moves to `REMEDIATED` with `remediated_at` stamped from the logical clock."
        PRD §3.8: "The named filing must be `CONFIRMED`, and its subject must belong to the same undertaking as the event; the test has two arms, keyed on the event's own subject."
        PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`; until the clock is explicitly set, that instant is what all rules read, and the service must never fall back on real wall-clock time."
        Design: Corner/validations/remediation_evidence_must_be_confirmed_and_belong_to_the_same_undertaking
        """
        context = _setup_delinquent_cycle_beside_sibling_program()
        fte_id = context["fte"]["id"]

        _ready_and_assemble_cycle(context["cycle_a"]["id"])
        fa = create_annual_report_filing(
            context["issue_a"]["id"], context["cycle_a"]["id"]
        )
        submit(fa["id"], context["eng_a"]["id"])
        confirmed = confirm(fa["id"], context["eng_a"]["id"], "EMMA-A-0001")
        assert confirmed["status"] == "CONFIRMED"

        armed = read_failure_event(fte_id)
        assert armed["status"] == "REMEDIATION_PENDING", (
            "the confirmation cascade moved the swept failure out of OPEN by itself"
        )
        assert armed["kind"] == "ANNUAL_REPORT_MISSED", "its kind is left unchanged"

        remediated = validate_success(
            api_client.remediate_failure_event(
                fte_id,
                {
                    "remediation_filing_id": fa["id"],
                    "remediation_note": (
                        "FY2025 annual report filed and confirmed by the repository."
                    ),
                },
                OFFICER,
            )
        )
        assert remediated["status"] == "REMEDIATED"
        assert remediated["remediation_filing_id"] == fa["id"]
        assert is_iso8601_timestamp(remediated["remediated_at"])
        assert remediated["remediated_at"][:19] == "2026-08-01T00:00:00", (
            "the logical clock was never moved, so the stamp is its startup instant"
        )


def _two_issues_one_program():
    """Two OUTSTANDING issues of one program, so a limit of 1 leaves a remainder."""
    issue_a = _make_issue(series_designation="2026A")
    issue_b = _make_issue(series_designation="2026B")
    return issue_a, issue_b


class TestPaginationBounds:
    """limit is bounded at both ends, offset only below."""

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
        ],
        ids=["limit_below_one", "limit_above_one_hundred", "negative_offset"],
    )
    def test_out_of_range_pagination_is_refused(self, params):
        """Each of the three out-of-range probes is refused by the same rung.

        PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` and HTTP 422."
        PRD §2.10: "36. Pagination bounds → `ERR_INVALID_PAGINATION` (422). Applies to every list endpoint."
        Design: Corner/validations/pagination_bounds_are_rejected_at_both_ends
        """
        _two_issues_one_program()

        validate_error(
            api_client.list_bond_issues(FD, params=params),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
        )

    def test_the_legal_extremes_are_accepted_and_has_more_tracks_the_window(self):
        """limit 1 and limit 100 both sit inside the inclusive range and page correctly.

        PRD §2.3: "`limit` is an integer with a minimum of 1, a maximum of 100, and a default of 10 when omitted."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the size of the full filtered result set before the window is applied and `has_more` indicates whether any row remains beyond the returned window."
        PRD §2.3: "Rows are returned in ascending `created_at` order, with `id` ascending as the tie-breaker."
        Design: Corner/validations/pagination_bounds_are_rejected_at_both_ends
        """
        issue_a, issue_b = _two_issues_one_program()

        first_page, meta = validate_paginated(
            api_client.list_bond_issues(FD, params={"limit": 1, "offset": 0})
        )
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert [row["id"] for row in first_page] == [issue_a["id"]]

        second_page, meta = validate_paginated(
            api_client.list_bond_issues(FD, params={"limit": 1, "offset": 1})
        )
        assert meta["total_count"] == 2, (
            "total_count is the unpaginated size and does not shrink with the window"
        )
        assert meta["has_more"] is False
        assert [row["id"] for row in second_page] == [issue_b["id"]]

        whole, meta = validate_paginated(
            api_client.list_bond_issues(FD, params={"limit": 100})
        )
        assert meta["limit"] == 100, "100 is the inclusive upper bound and is accepted"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(whole) == 2

    def test_the_declared_defaults_apply_when_both_parameters_are_omitted(self):
        """An unparameterised list reads limit 10 and offset 0.

        PRD §2.3: "`limit` is an integer with a minimum of 1, a maximum of 100, and a default of 10 when omitted."
        PRD §2.3: "`offset` is an integer with a minimum of 0 and a default of 0 when omitted."
        Design: Corner/validations/pagination_bounds_are_rejected_at_both_ends
        """
        _two_issues_one_program()

        rows, meta = validate_paginated(api_client.list_bond_issues(FD))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert len(rows) == 2
