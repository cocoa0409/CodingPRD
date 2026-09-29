"""Endpoint surface and role-based access control.

Every test in this module translates exactly one instance of the `endpoints` or
`rbac` section of SCAFFOLD_CORNER_DESIGN.yaml.  Each test starts against an empty
database whose logical clock reads its startup value 2026-08-01T00:00:00Z.
"""

import datetime

import pytest

from test_helpers import (
    AUDIT_AND_DATA_REQUIREMENT_SPECS,
    NON_EXISTENT_UUID,
    OFFICER_ASSEMBLER_ID,
    OFFICER_PREPARER_ID,
    REVIEWER_ONE_ID,
    REVIEWER_TWO_ID,
    SIMPLE_REQUIREMENT_SPECS,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_annual_report_cycle,
    assert_cycle_content_item,
    assert_dissemination_engagement,
    assert_filing,
    assert_material_event_notice,
    assert_official_statement,
    assert_score,
    assert_undertaking,
    attest_item,
    create_bond_issue,
    create_content_requirement,
    create_cycle,
    create_engagement,
    create_event_filing,
    create_notice,
    create_official_statement,
    determine_notice,
    item_for_requirement,
    make_agent_headers,
    make_officer_headers,
    prepare_item,
    setup_cycle,
    setup_issue_with_undertaking,
    validate_error,
    validate_paginated,
    validate_success,
)

FD = TEST_USERS["finance_director_headers"]
OFFICER = TEST_USERS["disclosure_officer_headers"]
ASSEMBLER = TEST_USERS["assembler_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]
SECOND_REVIEWER = TEST_USERS["second_reviewer_headers"]
STRANGER_AGENT = TEST_USERS["dissemination_agent_headers"]

CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# A third officer who has attested nothing at all, so segregation of duties
# leaves the assembly open to it.
OFFICER_THIRD_ID = "off-third"


def _instant(value) -> datetime.datetime:
    """Parse an ISO 8601 UTC instant, tolerating the optional fractional digits."""
    return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_same_instant(actual, expected: str = CLOCK_STARTUP_INSTANT):
    """The logical clock's instant, compared independently of fractional-digit style."""
    assert _instant(actual) == _instant(expected), (
        f"Expected the logical-clock instant {expected}, got {actual}"
    )


# --------------------------------------------------------------------------- #
# Composite preconditions this module needs and fixtures.py does not build
# --------------------------------------------------------------------------- #

WAIVABLE_ONLY_REQUIREMENT_SPECS = [
    {
        "kind": "ENTERPRISE_STATISTICS",
        "label": "Enterprise Statistics",
        "weight_bp": 10000,
        "waivable": True,
    },
]

AUDIT_HEAVY_REQUIREMENT_SPECS = [
    {"kind": "AUDITED_FINANCIALS", "label": "Audited Financial Statements", "weight_bp": 7000},
    {"kind": "OPERATING_DATA_TABLE", "label": "Operating Data Tables", "weight_bp": 3000},
]

DESIGN_ISSUE = {
    "issuer_program_code": "CIVICCENTER",
    "series_designation": "2026A",
    "security_type": "REVENUE",
    "dated_date": "2024-04-01",
    "final_maturity_date": "2056-04-01",
    "original_par_amount_cents": 100000000,
}


def _setup_waivable_cycle_with_pending_notice() -> dict:
    """A DRAFTING cycle whose single item is waivable, plus one pending notice."""
    context = setup_cycle(specs=WAIVABLE_ONLY_REQUIREMENT_SPECS, issue=dict(DESIGN_ISSUE))
    context["item"] = context["items"][0]
    context["notice"] = create_notice(
        context["issue"]["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
    )
    return context


def _setup_cycle_attested_by_two_officers() -> dict:
    """Two READY items on one cycle, attested by two different officers."""
    context = setup_cycle(specs=AUDIT_HEAVY_REQUIREMENT_SPECS, issue=dict(DESIGN_ISSUE))
    requirements = {r["kind"]: r for r in context["requirements"]}
    item_fin = item_for_requirement(context["items"], requirements["AUDITED_FINANCIALS"]["id"])
    item_ops = item_for_requirement(context["items"], requirements["OPERATING_DATA_TABLE"]["id"])
    prepare_item(
        item_fin["id"],
        user_id=OFFICER_PREPARER_ID,
        audit_opinion_type="UNMODIFIED",
        data_as_of_date="2026-06-30",
        source_document_ref="CAFR-FY2026.pdf",
    )
    prepare_item(
        item_ops["id"],
        user_id=OFFICER_PREPARER_ID,
        data_as_of_date="2026-06-30",
        source_document_ref="OPDATA-FY2026.xlsx",
    )
    context["item_fin"] = attest_item(item_fin["id"], user_id=OFFICER_PREPARER_ID)
    context["item_ops"] = attest_item(item_ops["id"], user_id=OFFICER_ASSEMBLER_ID)
    return context


def _setup_two_engagements_and_a_draft_event_filing() -> dict:
    """Two undertakings, each with its own ACTIVE agent, and a DRAFT filing on A."""
    side_a = setup_issue_with_undertaking(issue=dict(DESIGN_ISSUE))
    engagement_a = create_engagement(
        side_a["undertaking"]["id"],
        agent_name="Meridian Disclosure Services",
        effective_date="2026-07-20",
        expiration_date="2027-06-30",
        retainer_cents=250000,
    )
    side_b = setup_issue_with_undertaking(
        issue={
            "issuer_program_code": "WATERWORKS",
            "series_designation": "2026A",
            "security_type": "REVENUE",
            "dated_date": "2024-05-01",
            "final_maturity_date": "2054-05-01",
            "original_par_amount_cents": 60000000,
        }
    )
    engagement_b = create_engagement(
        side_b["undertaking"]["id"],
        agent_name="Keystone Filing Agents",
        effective_date="2026-07-20",
        expiration_date="2027-06-30",
        retainer_cents=250000,
    )
    notice = create_notice(
        side_a["issue"]["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
    )
    notice = determine_notice(notice["id"], "MATERIAL", user_id=REVIEWER_ONE_ID)
    filing = create_event_filing(side_a["issue"]["id"], notice["id"])
    return {
        "issue_a": side_a["issue"],
        "undertaking_a": side_a["undertaking"],
        "engagement_a": engagement_a,
        "issue_b": side_b["issue"],
        "undertaking_b": side_b["undertaking"],
        "engagement_b": engagement_b,
        "notice": notice,
        "filing": filing,
    }


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #

class TestContentItemSurface:
    """The read / list / partial-update surface of the cascade-created content item."""

    def test_content_item_read_list_and_partial_update_round_trip(self):
        """Reading, listing and repeatedly PATCHing one content item agree field for field.

        PRD §3.3: "Supplied fields overwrite their stored values and omitted fields are left untouched, so partial preparation is a legitimate repeat operation rather than an error: the first such update advances the item from `NOT_STARTED` to `DRAFT`, and every subsequent one is a `DRAFT` to `DRAFT` self-loop."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including cascaded mutations."
        PRD §2.12: "Content items are filterable by `cycle_id`, `content_requirement_id`, and `status`."
        PRD §3.3: "Where the requirement does demand an opinion, the multiplier is 1.0 for an `UNMODIFIED` opinion, 0.8 for a `QUALIFIED` one, 0.5 for `UNAUDITED_INTERIM`, and 0.0 when `audit_opinion_type` is still null."
        Design: Corner/endpoints/content_item_read_list_and_partial_update_round_trip
        """
        context = setup_cycle(specs=AUDIT_AND_DATA_REQUIREMENT_SPECS, issue=dict(DESIGN_ISSUE))
        cycle_id = context["cycle"]["id"]
        requirements = {r["kind"]: r for r in context["requirements"]}
        req_fin = requirements["AUDITED_FINANCIALS"]["id"]

        # The cascade minted exactly one item per requirement.
        rows, meta = validate_paginated(
            api_client.list_content_items(REVIEWER, params={"cycle_id": cycle_id})
        )
        assert meta["total_count"] == 2, "one content item per ContentRequirement"
        assert meta["has_more"] is False
        assert len(rows) == 2

        # The list row narrowed to one requirement, and the single read of the same row.
        narrowed, _ = validate_paginated(
            api_client.list_content_items(
                OFFICER, params={"cycle_id": cycle_id, "content_requirement_id": req_fin}
            )
        )
        assert len(narrowed) == 1
        list_row = narrowed[0]
        item_fin = list_row["id"]
        assert list_row["status"] == "NOT_STARTED"
        assert list_row["weight_bp_snapshot"] == 6000
        assert list_row["version"] == 1

        single = validate_success(api_client.get_content_item(item_fin, OFFICER))
        assert_cycle_content_item(single)
        assert single["id"] == item_fin
        assert single["cycle_id"] == cycle_id
        assert single["content_requirement_id"] == req_fin
        assert float(single["readiness_factor"]) == 0.0
        assert single == list_row, "the single read and the list row agree field for field"

        # First PATCH: NOT_STARTED -> DRAFT, version 1 -> 2.
        first = validate_success(
            api_client.update_content_item(
                item_fin,
                {"data_as_of_date": "2026-06-30", "source_document_ref": "CAFR-FY2026.pdf"},
                OFFICER,
            )
        )
        assert_cycle_content_item(first)
        assert first["status"] == "DRAFT"
        assert first["data_as_of_date"] == "2026-06-30"
        assert first["source_document_ref"] == "CAFR-FY2026.pdf"
        assert first["audit_opinion_type"] is None
        assert first["version"] == 2
        assert float(first["readiness_factor"]) == 0.5

        # A DRAFT audited-financials item with no opinion recorded is worth nothing.
        mid_cycle = validate_success(api_client.get_annual_report_cycle(cycle_id, OFFICER))
        assert_annual_report_cycle(mid_cycle)
        assert_score(mid_cycle["completeness_score_pct"], 0.00, "completeness_score_pct")

        # Second PATCH: merge, not replace.
        second = validate_success(
            api_client.update_content_item(
                item_fin, {"audit_opinion_type": "UNMODIFIED"}, OFFICER
            )
        )
        assert_cycle_content_item(second)
        assert second["data_as_of_date"] == "2026-06-30"
        assert second["source_document_ref"] == "CAFR-FY2026.pdf"
        assert second["audit_opinion_type"] == "UNMODIFIED"
        assert second["version"] == 3, "one increment per PATCH, no skipped versions"
        assert second["status"] == "DRAFT"
        assert float(second["readiness_factor"]) == 0.5

        drafts, draft_meta = validate_paginated(
            api_client.list_content_items(
                OFFICER, params={"cycle_id": cycle_id, "status": "DRAFT"}
            )
        )
        assert draft_meta["total_count"] == 1, "the status filter sees only the patched item"
        assert [row["id"] for row in drafts] == [item_fin]

        after_cycle = validate_success(api_client.get_annual_report_cycle(cycle_id, OFFICER))
        assert_score(after_cycle["completeness_score_pct"], 30.00, "completeness_score_pct")


class TestSuspendAndReinstate:
    """The suspend / reinstate pair and the preparation endpoints it gates."""

    def test_suspend_and_reinstate_gate_every_preparation_endpoint(self):
        """Suspension blocks content preparation and new cycles; reinstatement clears the reason.

        PRD §3.2: "A `FinanceDirector` may suspend an `ACTIVE` undertaking — pending a legal opinion, for instance — by supplying a `suspended_reason`, which is stamped on the row; suspension blocks new reporting cycles, all content preparation, assembly, and all new engagements, while filings already in flight continue undisturbed."
        PRD §3.2: "Reinstating a `SUSPENDED` undertaking takes no payload at all, returns it to `ACTIVE`, and clears `suspended_reason` back to null."
        PRD §3.2: "Neither suspension nor reinstatement touches the second dimension: `compliance_posture`, `disclosure_risk_score`, `remediation_tier`, and every counter are left exactly as they were."
        PRD §2.10: "Undertaking gate — the `Undertaking` that owns the target row is `ACTIVE` → `ERR_UNDERTAKING_NOT_ACTIVE` (409)."
        PRD §2.10: "Own-status transition legality — the target row's own `status` admits the requested transition → `ERR_INVALID_STATE_TRANSITION` (409)."
        Design: Corner/endpoints/suspend_and_reinstate_gate_every_preparation_endpoint
        """
        context = setup_cycle(specs=SIMPLE_REQUIREMENT_SPECS, issue=dict(DESIGN_ISSUE))
        undertaking_id = context["undertaking"]["id"]
        item_id = context["items"][0]["id"]
        assert context["undertaking"]["suspended_reason"] is None, (
            "a new undertaking carries a null suspended_reason"
        )

        reason = "Audit not complete; preparation paused by the finance director."
        suspended = validate_success(
            api_client.suspend_undertaking(undertaking_id, {"suspended_reason": reason}, FD)
        )
        assert_undertaking(suspended)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspended_reason"] == reason
        assert suspended["compliance_posture"] == "COMPLIANT", (
            "suspension is a lifecycle dimension and must not touch the compliance posture"
        )

        # Priority 10 reaches down to the grandchild item through its cycle.
        validate_error(
            api_client.update_content_item(
                item_id,
                {"data_as_of_date": "2026-06-30", "source_document_ref": "OPDATA-FY2026.xlsx"},
                OFFICER,
            ),
            ApiErrorId.ERR_UNDERTAKING_NOT_ACTIVE.value,
        )

        # The FY2027 period is otherwise perfectly legal.
        validate_error(
            api_client.create_annual_report_cycle(
                {
                    "undertaking_id": undertaking_id,
                    "fiscal_year_label": "FY2027",
                    "period_start_date": "2026-07-01",
                    "period_end_date": "2027-06-30",
                },
                OFFICER,
            ),
            ApiErrorId.ERR_UNDERTAKING_NOT_ACTIVE.value,
        )

        # Suspend is not idempotent.
        validate_error(
            api_client.suspend_undertaking(
                undertaking_id, {"suspended_reason": "Still paused."}, FD
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )

        reinstated = validate_success(api_client.reinstate_undertaking(undertaking_id, FD))
        assert_undertaking(reinstated)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspended_reason"] is None, (
            "reinstatement clears the reason rather than leaving stale text"
        )

        validate_error(
            api_client.reinstate_undertaking(undertaking_id, FD),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )

        # The identical PATCH that was refused during suspension now succeeds.
        prepared = validate_success(
            api_client.update_content_item(
                item_id,
                {"data_as_of_date": "2026-06-30", "source_document_ref": "OPDATA-FY2026.xlsx"},
                OFFICER,
            )
        )
        assert_cycle_content_item(prepared)
        assert prepared["status"] == "DRAFT"


class TestUndertakingReadPaths:
    """The derived undertaking fields as seen from the single read and from the list."""

    def test_derived_undertaking_fields_agree_across_write_single_read_and_list(self):
        """The single GET and the list row report the same recomputed counters.

        PRD §2.11: "`open_obligation_count`, `open_material_event_count`, `late_filing_count`, `missed_event_count`, `delinquent_cycle_count`, `content_weight_bp_total`, `completeness_score_pct`, `billable_filing_count`, and `monitoring_lapse_days` are each defined as a full aggregation over their source rows and are re-derived whenever a trigger fires."
        PRD §3.2: "All four counters — `late_filing_count`, `missed_event_count`, `delinquent_cycle_count`, and `open_obligation_count` — start at 0, and so does `content_weight_bp_total`."
        PRD §3.3: "The undertaking's `open_obligation_count` is re-derived, and the new cycle raises it."
        PRD §3.5: "Creation also re-derives the issue's `open_material_event_count` and the undertaking's `open_obligation_count`, because a `DETERMINATION_PENDING` notice is an open obligation."
        PRD §3.5: "A `NOT_MATERIAL` determination is terminal and releases the obligation: the notice leaves the open set, both counters fall, no `filing_deadline_date` enforcement ever applies to it again, the calendar sweep skips it permanently, and any later filing that names it is refused with `ERR_FILING_SUBJECT_MISMATCH`."
        PRD §3.2: "Each accepted requirement re-derives the undertaking's `content_weight_bp_total` as the sum of `weight_bp` across all of that undertaking's requirements, which is the figure the weight-closure gate of §3.3 tests."
        PRD §2.12: "The remaining lists follow the same pattern: bond issues by `issuer_program_code` and `status`; undertakings by `issue_id`, `status`, and `compliance_posture`; content requirements by `undertaking_id` and `kind`; reporting cycles by `undertaking_id`, `filed_filing_id`, `status`, and `fiscal_year_label`; listed-event notices by `issue_id`, `financial_obligation_ref`, `filed_filing_id`, `status`, and `event_type`; filings by `issue_id`, `cycle_id`, `material_event_id`, `direct_placement_id`, `supersedes_filing_id`, `superseded_by_filing_id`, `submitting_engagement_id`, `filing_type`, and `status`; direct placements by `issue_id`, `linked_notice_id`, `status`, and `disclosure_practice`; official statements by `issue_id`, `status`, and `lookback_policy`; and dissemination engagements by `undertaking_id`, `superseded_by_engagement_id`, and `status`."
        Design: Corner/endpoints/derived_undertaking_fields_agree_across_write_single_read_and_list
        """
        context = setup_cycle(specs=SIMPLE_REQUIREMENT_SPECS, issue=dict(DESIGN_ISSUE))
        issue_id = context["issue"]["id"]
        undertaking_id = context["undertaking"]["id"]
        keep = create_notice(
            issue_id, event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
        )
        drop = create_notice(issue_id, event_type="MERGER_OR_SALE", occurrence_date="2026-07-28")
        assert keep["status"] == "DETERMINATION_PENDING"
        assert drop["status"] == "DETERMINATION_PENDING"

        # One DRAFTING cycle plus two pending notices are three open obligations.
        before = validate_success(api_client.get_undertaking(undertaking_id, REVIEWER))
        assert before["open_obligation_count"] == 3
        issue_before = validate_success(api_client.get_bond_issue(issue_id, FD))
        assert issue_before["open_material_event_count"] == 2

        determined = validate_success(
            api_client.determine_material_event_notice(
                drop["id"],
                {"determination": "NOT_MATERIAL", "determination_note": "No change of control."},
                REVIEWER,
            )
        )
        assert_material_event_notice(determined)
        assert determined["status"] == "NOT_MATERIAL"

        single = validate_success(api_client.get_undertaking(undertaking_id, REVIEWER))
        assert_undertaking(single)
        assert single["open_obligation_count"] == 2, (
            "one DRAFTING cycle plus one still-pending notice; the NOT_MATERIAL notice has left"
        )
        assert single["content_weight_bp_total"] == 10000
        assert_score(single["disclosure_risk_score"], 0.00, "disclosure_risk_score")
        assert single["remediation_tier"] == "TIER_0"
        assert single["compliance_posture"] == "COMPLIANT"
        assert single["late_filing_count"] == 0
        assert single["missed_event_count"] == 0
        assert single["delinquent_cycle_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_undertakings(FD, params={"issue_id": issue_id})
        )
        assert meta["total_count"] == 1
        list_row = rows[0]
        assert_undertaking(list_row)
        assert list_row["open_obligation_count"] == single["open_obligation_count"]
        assert list_row["content_weight_bp_total"] == single["content_weight_bp_total"]
        assert list_row["disclosure_risk_score"] == single["disclosure_risk_score"]
        assert list_row["remediation_tier"] == single["remediation_tier"]
        assert list_row["compliance_posture"] == single["compliance_posture"]
        assert list_row == single, "the list row is the same serialization as the single read"

        # The issue-level counter agrees on the notice half of the obligation count.
        issue_after = validate_success(api_client.get_bond_issue(issue_id, FD))
        assert issue_after["open_material_event_count"] == 1


SWEEP_ISSUE = {
    "issuer_program_code": "CIVICCENTER",
    "series_designation": "2026A",
    "security_type": "REVENUE",
    "dated_date": "2023-04-01",
    "final_maturity_date": "2056-04-01",
    "original_par_amount_cents": 100000000,
}


class TestCalendarSweepSurface:
    """The bulk sweep endpoint: skip-not-fail semantics and idempotence at a fixed clock."""

    def test_calendar_sweep_processes_every_due_row_once_and_is_idempotent(self):
        """The sweep moves only the past-due rows, scores once, and is a no-op when repeated.

        PRD §3.11: "Its five steps execute in the pinned order 1 through 5, and within each step candidate rows are iterated `created_at` ascending with `id` ascending as the tie-break."
        PRD §3.11: "**Step 2 — delinquency.** Every `AnnualReportCycle` in `status` `DRAFTING` or `READY_TO_FILE` whose `due_date` is strictly before the logical clock's date moves to `DELINQUENT`, with `assembled_by_user_id` and `assembled_at` cleared."
        PRD §3.11: "**Step 3 — missed listed events.** Every `MaterialEventNotice` in `status` `MATERIAL` whose `filing_deadline_date` is strictly before the logical clock's date moves to `MISSED`, with `days_late` set to the calendar days from `filing_deadline_date` to the clock date."
        PRD §3.11: "**Step 4 — monitoring lapse.** Every `DisseminationEngagement` in `status` `ACTIVE` whose refreshed `monitoring_lapse_days` exceeds 45 moves to `SUSPENDED`."
        PRD §3.11: "It reports `swept_at`, the logical-clock instant of the sweep, alongside five counts: `matured_issue_count` for step 1, `delinquent_cycle_count` for step 2, `missed_event_count` for step 3, `suspended_engagement_count` for step 4, and `failure_event_created_count` for every `FailureToFileEvent` minted across steps 2 and 3 together."
        PRD §3.11: "The sweep is idempotent for a fixed clock: a second sweep at the same clock instant finds no candidates and returns all five counts as 0."
        PRD §3.3: "Take the cycle's own `period_end_date`, advance it by the owning undertaking's `filing_window_days` in **calendar** days, then roll the result forward — never backward — to the first business day at or after it, using the calendar of §2.6."
        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §3.10: "`monitoring_lapse_days` is the whole calendar days from the later-of-nothing baseline — `last_calendar_ack_date` when it is set, and `effective_date` when it is null — to the logical clock's date, floored at 0."
        PRD §3.8: "`late_filing_count` is the number of that undertaking's failure events whose `kind` is `ANNUAL_REPORT_LATE` or `ANNUAL_REPORT_MISSED`."
        PRD §3.8: "Step 1 forms an additive base of 12 times L, plus 20 times M, plus 15 times D."
        PRD §3.8: "The pass runs **exactly once** per trigger and is never iterated to a fixed point, so `disclosure_risk_score` and `remediation_tier` may legitimately disagree by one escalation step until the next trigger fires."
        PRD §3.8: "the posture is `DELINQUENT` whenever D is 1 or more, regardless of score"
        Design: Corner/endpoints/calendar_sweep_processes_every_due_row_once_and_is_idempotent
        """
        base = setup_issue_with_undertaking(issue=dict(SWEEP_ISSUE))
        issue_id = base["issue"]["id"]
        undertaking_id = base["undertaking"]["id"]
        create_content_requirement(
            undertaking_id,
            kind="OPERATING_DATA_TABLE",
            label="Operating Data Tables",
            weight_bp=10000,
        )
        cycle_24 = create_cycle(
            undertaking_id,
            fiscal_year_label="FY2024",
            period_start_date="2023-07-01",
            period_end_date="2024-06-30",
        )
        cycle_25 = create_cycle(
            undertaking_id,
            fiscal_year_label="FY2025",
            period_start_date="2024-07-01",
            period_end_date="2025-06-30",
        )
        cycle_26 = create_cycle(
            undertaking_id,
            fiscal_year_label="FY2026",
            period_start_date="2025-07-01",
            period_end_date="2026-06-30",
        )
        # 2024-06-30 + 210 calendar days is Sunday 2025-01-26, rolled forward.
        assert cycle_24["due_date"] == "2025-01-27"
        assert cycle_25["due_date"] == "2026-01-26"
        assert cycle_26["due_date"] == "2027-01-26"

        notice = create_notice(
            issue_id, event_type="UNSCHEDULED_DRAW_ON_RESERVE", occurrence_date="2026-07-13"
        )
        assert notice["filing_deadline_date"] == "2026-07-27"
        notice = determine_notice(
            notice["id"], "MATERIAL", determination_note="Reserve draw exceeded the policy floor."
        )
        assert notice["status"] == "MATERIAL"

        engagement = create_engagement(
            undertaking_id,
            agent_name="Meridian Disclosure Services",
            effective_date="2026-07-01",
            expiration_date="2027-06-30",
            retainer_cents=250000,
        )
        assert engagement["monitoring_lapse_days"] == 31, "2026-07-01 to 2026-08-01 is 31 days"

        first = validate_success(api_client.run_calendar_sweep(FD))
        assert first["matured_issue_count"] == 0, "final maturity 2056 is far in the future"
        assert first["delinquent_cycle_count"] == 2
        assert first["missed_event_count"] == 1
        assert first["suspended_engagement_count"] == 0
        assert first["failure_event_created_count"] == 3, "two cycle events plus one notice event"
        assert_same_instant(first["swept_at"])

        # The not-yet-due FY2026 cycle is skipped, not failed.
        untouched = validate_success(api_client.get_annual_report_cycle(cycle_26["id"], OFFICER))
        assert untouched["status"] == "DRAFTING"
        delinquent, delinquent_meta = validate_paginated(
            api_client.list_annual_report_cycles(
                OFFICER, params={"undertaking_id": undertaking_id, "status": "DELINQUENT"}
            )
        )
        assert delinquent_meta["total_count"] == 2
        assert {row["id"] for row in delinquent} == {cycle_24["id"], cycle_25["id"]}

        swept_notice = validate_success(
            api_client.get_material_event_notice(notice["id"], OFFICER)
        )
        assert_material_event_notice(swept_notice)
        assert swept_notice["status"] == "MISSED"

        # 31 <= 45, so step 4 leaves the engagement alone.
        swept_engagement = validate_success(api_client.get_engagement(engagement["id"], FD))
        assert_dissemination_engagement(swept_engagement)
        assert swept_engagement["status"] == "ACTIVE"
        assert swept_engagement["monitoring_lapse_days"] == 31

        after_first = validate_success(api_client.get_undertaking(undertaking_id, FD))
        assert_undertaking(after_first)
        assert after_first["late_filing_count"] == 2
        assert after_first["missed_event_count"] == 1
        assert after_first["delinquent_cycle_count"] == 2
        # Base 12*2 + 20*1 + 15*2 = 74, times the prior TIER_0 multiplier 1.00, applied once
        # for the whole sweep rather than once per row.
        assert_score(after_first["disclosure_risk_score"], 74.00, "disclosure_risk_score")
        assert after_first["remediation_tier"] == "TIER_2"
        assert after_first["compliance_posture"] == "DELINQUENT"

        events, events_meta = validate_paginated(
            api_client.list_failure_events(OFFICER, params={"undertaking_id": undertaking_id})
        )
        assert events_meta["total_count"] == 3
        assert len(events) == 3

        second = validate_success(api_client.run_calendar_sweep(FD))
        assert second["matured_issue_count"] == 0
        assert second["delinquent_cycle_count"] == 0
        assert second["missed_event_count"] == 0
        assert second["suspended_engagement_count"] == 0
        assert second["failure_event_created_count"] == 0

        after_second = validate_success(api_client.get_undertaking(undertaking_id, FD))
        assert_score(
            after_second["disclosure_risk_score"],
            74.00,
            "disclosure_risk_score after a no-op sweep",
        )
        assert after_second["remediation_tier"] == "TIER_2", (
            "a no-op sweep must not re-multiply 74.00 by the now-persisted TIER_2 factor"
        )
        assert after_second["late_filing_count"] == 2
        _, events_meta_2 = validate_paginated(
            api_client.list_failure_events(OFFICER, params={"undertaking_id": undertaking_id})
        )
        assert events_meta_2["total_count"] == 3, "no duplicate failure events were minted"


# --------------------------------------------------------------------------- #
# rbac
# --------------------------------------------------------------------------- #

SECOND_ISSUE_PAYLOAD = {
    "issuer_program_code": "CIVICCENTER",
    "series_designation": "2026B",
    "security_type": "REVENUE",
    "dated_date": "2024-04-01",
    "final_maturity_date": "2056-04-01",
    "original_par_amount_cents": 5000000,
}


class TestFinanceDirectorAuthority:
    """The debt-registry and calendar endpoints belong to the FinanceDirector alone."""

    @pytest.mark.parametrize(
        "headers",
        [OFFICER, REVIEWER, STRANGER_AGENT],
        ids=["disclosure_officer", "compliance_reviewer", "dissemination_agent"],
    )
    def test_registry_and_calendar_authority_belongs_to_the_finance_director_alone(self, headers):
        """Registering an issue is refused for every non-director role with ERR_UNAUTHORIZED.

        PRD §2.1: "When the headers are well-formed but the named role is not among those authorized for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` with HTTP 403."
        PRD §2.10: "2. Authorization — the acting role appears in the called endpoint's role list → `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        PRD §2.10: "6. Agent identity — the three arms described in §2.1 → `ERR_AGENT_NOT_ENGAGED` (403). Applies to `POST /disclosure/filings/{id}/submit`, `/confirm`, `/reject`, `/resubmit`, and to `POST /disclosure/dissemination-engagements/{id}/acknowledge-calendar`. This is distinct from rule 2: the role is permitted, the identity is wrong."
        Design: Corner/rbac/registry_and_calendar_authority_belongs_to_the_finance_director_alone
        """
        # The agent's X-User-ID resolves to no engagement row at all, and the role
        # gate at rung 2 must still be the rung that answers.
        validate_error(
            api_client.create_bond_issue(dict(SECOND_ISSUE_PAYLOAD), headers),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

    def test_role_gate_outranks_body_foreign_key_resolution(self):
        """A wrong-role create carrying an unknown foreign key is 403, not 404.

        PRD §2.10: "Checks are evaluated in a single strictly ordered ladder, and the **first** rule that fails is the **only** error returned."
        PRD §2.10: "2. Authorization — the acting role appears in the called endpoint's role list → `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        PRD §2.10: "4. Body foreign-key existence — every foreign-key field in the body resolves, in declared input order → the entity-specific not-found error (404). Applies to every create and update endpoint carrying a foreign key."
        Design: Corner/rbac/registry_and_calendar_authority_belongs_to_the_finance_director_alone
        """
        validate_error(
            api_client.create_undertaking(
                {"issue_id": NON_EXISTENT_UUID, "fiscal_year_end_month_day": "06-30"}, REVIEWER
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

    @pytest.mark.parametrize(
        "action",
        ["suspend_undertaking", "calendar_sweep", "defease_issue"],
    )
    def test_director_only_actions_are_refused_to_the_other_roles(self, action):
        """Suspension, the calendar sweep and defeasance are all director-only.

        PRD §2.1: "This role owns the debt inventory and the undertaking register, signs off on defeasance and rating actions, engages and terminates dissemination agents, drives the server's logical clock, and runs the dated calendar sweep."
        PRD §2.1: "When the headers are well-formed but the named role is not among those authorized for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` with HTTP 403."
        Design: Corner/rbac/registry_and_calendar_authority_belongs_to_the_finance_director_alone
        """
        base = setup_issue_with_undertaking(issue=dict(DESIGN_ISSUE))
        if action == "suspend_undertaking":
            response = api_client.suspend_undertaking(
                base["undertaking"]["id"], {"suspended_reason": "Attempted by the preparer."}, OFFICER
            )
        elif action == "calendar_sweep":
            response = api_client.run_calendar_sweep(OFFICER)
        else:
            response = api_client.defease_bond_issue(
                base["issue"]["id"],
                {
                    "defeasance_type": "LEGAL",
                    "escrow_deposit_cents": 100000000,
                    "occurrence_date": "2026-07-30",
                },
                REVIEWER,
            )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_reads_stay_shared_across_the_roles(self):
        """The refusals are endpoint-specific: every GET remains open to all four roles.

        PRD §2.1: "Read access is uniform. Every single-resource read and every list endpoint under `/disclosure` is available to all four roles; the write surface is partitioned exactly as described above and enumerated in §4."
        Design: Corner/rbac/registry_and_calendar_authority_belongs_to_the_finance_director_alone
        """
        issue = create_bond_issue(**DESIGN_ISSUE)
        shared = validate_success(api_client.get_bond_issue(issue["id"], REVIEWER))
        assert shared["status"] == "OUTSTANDING"


class TestPreparationVersusReview:
    """The preparer's surface and the reviewer's surface do not overlap."""

    @pytest.mark.parametrize("act", ["determine", "waive"])
    def test_the_preparing_officer_may_neither_judge_nor_excuse(self, act):
        """Materiality determination and content waiver are closed to the DisclosureOfficer.

        PRD §2.1: "A `DisclosureOfficer` cannot determine materiality, cannot waive content, cannot review or publish an official statement, and cannot submit to the repository."
        PRD §2.10: "2. Authorization — the acting role appears in the called endpoint's role list → `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        Design: Corner/rbac/preparation_and_review_duties_do_not_overlap_between_officer_and_reviewer
        """
        context = _setup_waivable_cycle_with_pending_notice()
        if act == "determine":
            response = api_client.determine_material_event_notice(
                context["notice"]["id"],
                {
                    "determination": "MATERIAL",
                    "determination_note": "Preparer attempting to judge his own filing.",
                },
                OFFICER,
            )
        else:
            response = api_client.waive_content_item(
                context["item"]["id"],
                {"waiver_reason": "Preparer attempting to excuse his own content."},
                OFFICER,
            )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    @pytest.mark.parametrize("act", ["requirement", "cycle", "patch", "attest"])
    def test_the_compliance_reviewer_may_not_prepare(self, act):
        """Declaring requirements, opening cycles, patching and attesting are officer-only.

        PRD §2.1: "A `ComplianceReviewer` cannot open or prepare anything, and cannot submit to the repository."
        PRD §2.10: "2. Authorization — the acting role appears in the called endpoint's role list → `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        Design: Corner/rbac/preparation_and_review_duties_do_not_overlap_between_officer_and_reviewer
        """
        context = _setup_waivable_cycle_with_pending_notice()
        if act == "requirement":
            response = api_client.create_content_requirement(
                {
                    "undertaking_id": context["undertaking"]["id"],
                    "kind": "BUDGET_SUMMARY",
                    "label": "Adopted Budget Summary",
                    "weight_bp": 1000,
                },
                REVIEWER,
            )
        elif act == "cycle":
            response = api_client.create_annual_report_cycle(
                {
                    "undertaking_id": context["undertaking"]["id"],
                    "fiscal_year_label": "FY2027",
                    "period_start_date": "2026-07-01",
                    "period_end_date": "2027-06-30",
                },
                REVIEWER,
            )
        elif act == "patch":
            response = api_client.update_content_item(
                context["item"]["id"], {"data_as_of_date": "2026-06-30"}, REVIEWER
            )
        else:
            response = api_client.attest_content_item(context["item"]["id"], REVIEWER)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_the_same_payloads_succeed_once_the_correct_role_sends_them(self):
        """The identical waive and determine bodies are accepted from the ComplianceReviewer.

        PRD §2.1: "A **`ComplianceReviewer`** is the independent compliance function. This role judges the materiality of listed events, waives content the undertaking is not obliged to provide, classifies direct placements against the materiality boundary, and runs and publishes the official-statement failure-to-file review."
        PRD §3.3: "An item in `NOT_STARTED` or `DRAFT` moves to `WAIVED` on supply of a `waiver_reason`, but only when its underlying `ContentRequirement` has `waivable` true; otherwise the attempt is refused with `ERR_REQUIREMENT_NOT_WAIVABLE`."
        PRD §3.5: "Determination is the `ComplianceReviewer`'s act, and it takes a `determination` of `MATERIAL` or `NOT_MATERIAL` plus an optional `determination_note`."
        Design: Corner/rbac/preparation_and_review_duties_do_not_overlap_between_officer_and_reviewer
        """
        context = _setup_waivable_cycle_with_pending_notice()
        reason = "Enterprise statistics are not part of this undertaking."
        waived = validate_success(
            api_client.waive_content_item(
                context["item"]["id"], {"waiver_reason": reason}, REVIEWER
            )
        )
        assert_cycle_content_item(waived)
        assert waived["status"] == "WAIVED"
        assert waived["waiver_reason"] == reason

        determined = validate_success(
            api_client.determine_material_event_notice(
                context["notice"]["id"],
                {
                    "determination": "MATERIAL",
                    "determination_note": "Trustee substitution affects bondholder security.",
                },
                REVIEWER,
            )
        )
        assert_material_event_notice(determined)
        assert determined["status"] == "MATERIAL"


class TestRepositoryTraffic:
    """Submit, confirm, reject and calendar acknowledgement belong to one engagement."""

    @pytest.mark.parametrize("act", ["submit_as_officer", "confirm_as_director"])
    def test_repository_traffic_is_closed_to_every_human_role(self, act):
        """Only the DisseminationAgent may touch the repository surface.

        PRD §2.1: "A **`DisseminationAgent`** is the engaged outside agent and the only role permitted to touch the central-repository submission surface: it submits and resubmits filings and carries the repository's confirmation or rejection back into the record."
        PRD §2.1: "A `FinanceDirector` cannot prepare or attest filing content, cannot determine materiality, and cannot submit anything to the central repository."
        PRD §2.10: "2. Authorization — the acting role appears in the called endpoint's role list → `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        Design: Corner/rbac/repository_traffic_is_restricted_to_the_engagement_that_owns_it
        """
        context = _setup_two_engagements_and_a_draft_event_filing()
        filing_id = context["filing"]["id"]
        if act == "submit_as_officer":
            response = api_client.submit_filing(filing_id, OFFICER)
        else:
            response = api_client.confirm_filing(
                filing_id, {"repository_receipt_id": "EMMA-RCPT-90001"}, FD
            )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_an_engagement_of_another_undertaking_cannot_submit(self):
        """Arm (a): the submitting engagement must own the undertaking behind the subject.

        PRD §2.1: "On a submit, the engagement's `undertaking_id` must equal the undertaking that owns the filing's subject — the undertaking of the subject cycle, or the undertaking of the issue named by the subject notice or placement."
        PRD §2.1: "All three arms fail with `ERR_AGENT_NOT_ENGAGED` and HTTP 403, and this check runs regardless of the engagement's own status, so a terminated agent is told it is not engaged rather than being allowed to read another engagement's record."
        Design: Corner/rbac/repository_traffic_is_restricted_to_the_engagement_that_owns_it
        """
        context = _setup_two_engagements_and_a_draft_event_filing()
        filing_id = context["filing"]["id"]
        engagement_a = context["engagement_a"]["id"]
        engagement_b = context["engagement_b"]["id"]

        # Engagement B is ACTIVE and real, but it is engaged on the other undertaking.
        validate_error(
            api_client.submit_filing(filing_id, make_agent_headers(engagement_b)),
            ApiErrorId.ERR_AGENT_NOT_ENGAGED.value,
        )

        submitted = validate_success(
            api_client.submit_filing(filing_id, make_agent_headers(engagement_a))
        )
        assert_filing(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitting_engagement_id"] == engagement_a
        assert submitted["submission_attempt_count"] == 1

    def test_only_the_submitting_engagement_may_carry_the_repository_answer(self):
        """Arm (b): confirm and reject demand an exact submitting_engagement_id match.

        PRD §2.1: "On a confirm, a reject, or a resubmit, `X-User-ID` must equal the filing's `submitting_engagement_id` exactly, so that only the agent that handed the document over may carry the repository's answer back."
        PRD §2.1: "All three arms fail with `ERR_AGENT_NOT_ENGAGED` and HTTP 403, and this check runs regardless of the engagement's own status, so a terminated agent is told it is not engaged rather than being allowed to read another engagement's record."
        Design: Corner/rbac/repository_traffic_is_restricted_to_the_engagement_that_owns_it
        """
        context = _setup_two_engagements_and_a_draft_event_filing()
        filing_id = context["filing"]["id"]
        engagement_a = context["engagement_a"]["id"]
        engagement_b = context["engagement_b"]["id"]
        validate_success(api_client.submit_filing(filing_id, make_agent_headers(engagement_a)))

        validate_error(
            api_client.confirm_filing(
                filing_id,
                {"repository_receipt_id": "EMMA-RCPT-90002"},
                make_agent_headers(engagement_b),
            ),
            ApiErrorId.ERR_AGENT_NOT_ENGAGED.value,
        )
        validate_error(
            api_client.reject_filing(
                filing_id,
                {"rejection_reason": "Foreign agent attempting to reject."},
                make_agent_headers(engagement_b),
            ),
            ApiErrorId.ERR_AGENT_NOT_ENGAGED.value,
        )

        confirmed = validate_success(
            api_client.confirm_filing(
                filing_id,
                {"repository_receipt_id": "EMMA-RCPT-90003"},
                make_agent_headers(engagement_a),
            )
        )
        assert_filing(confirmed)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["repository_receipt_id"] == "EMMA-RCPT-90003"

    def test_an_agent_may_acknowledge_only_its_own_calendar(self):
        """Arm (c): the acknowledgement path segment must be the acting engagement.

        PRD §2.1: "On a calendar acknowledgement, `X-User-ID` must equal the engagement named by the `{id}` path segment."
        PRD §3.10: "Acknowledgement is the agent's own act: it takes a `last_calendar_ack_date`, requires the acting `X-User-ID` to equal the engagement's own id (else `ERR_AGENT_NOT_ENGAGED`), and requires that date to be at or after `effective_date` and at or before the logical clock's date (else `ERR_ACK_DATE_OUT_OF_RANGE`)."
        PRD §3.10: "`monitoring_lapse_days` is the whole calendar days from the later-of-nothing baseline — `last_calendar_ack_date` when it is set, and `effective_date` when it is null — to the logical clock's date, floored at 0."
        Design: Corner/rbac/repository_traffic_is_restricted_to_the_engagement_that_owns_it
        """
        context = _setup_two_engagements_and_a_draft_event_filing()
        engagement_a = context["engagement_a"]["id"]
        engagement_b = context["engagement_b"]["id"]

        validate_error(
            api_client.acknowledge_calendar(
                engagement_a,
                {"last_calendar_ack_date": "2026-08-01"},
                make_agent_headers(engagement_b),
            ),
            ApiErrorId.ERR_AGENT_NOT_ENGAGED.value,
        )

        acknowledged = validate_success(
            api_client.acknowledge_calendar(
                engagement_b,
                {"last_calendar_ack_date": "2026-08-01"},
                make_agent_headers(engagement_b),
            )
        )
        assert_dissemination_engagement(acknowledged)
        assert acknowledged["last_calendar_ack_date"] == "2026-08-01"
        assert acknowledged["monitoring_lapse_days"] == 0


# Deliberately malformed identity headers, built by hand because every helper in
# test_helpers necessarily builds a well-formed pair.
NO_ROLE_HEADERS = {"X-User-ID": FD["X-User-ID"], "Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": FD["X-User-ID"],
    "X-User-Role": "TrusteeBank",
    "Content-Type": "application/json",
}
EMPTY_USER_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": "FinanceDirector",
    "Content-Type": "application/json",
}
NO_USER_HEADERS = {"X-User-Role": "FinanceDirector", "Content-Type": "application/json"}


class TestIdentityHeaders:
    """Authentication is the outermost rung of the ladder."""

    @pytest.mark.parametrize(
        "probe",
        [
            "missing_role",
            "unknown_role",
            "missing_role_and_unknown_path_id",
            "empty_user_id",
            "missing_user_id_and_malformed_body",
        ],
    )
    def test_missing_or_unknown_identity_headers_are_refused_before_anything_else(self, probe):
        """Every ill-formed identity pair is ERR_UNAUTHENTICATED, whatever else is wrong.

        PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which that user acts. If either header is absent, if `X-User-ID` is empty, or if `X-User-Role` holds a value outside the four roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD §2.10: "Checks are evaluated in a single strictly ordered ladder, and the **first** rule that fails is the **only** error returned. Where two rules could both fire on the same request, the lower-numbered rule wins."
        PRD §2.10: "1. Authentication — `X-User-Role` present and one of the four declared roles, `X-User-ID` present and non-empty → `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."
        PRD §2.10: "3. Path existence — every `{id}` path segment resolves, left to right → the entity-specific not-found error (404). Applies to every endpoint with an `{id}` path parameter."
        PRD §2.10: "5. Request shape — every required input present; every enum value inside its declared set; integers non-negative where declared; dates in ISO 8601 form; `period_start_date` strictly before `period_end_date`; `weight_bp` between 1 and 10000 inclusive; `retainer_cents` at least 0; `disclosed_event_ids` a possibly empty array of distinct ids → `ERR_INVALID_REQUEST` (422). Applies to every create and update endpoint."
        Design: Corner/rbac/missing_or_unknown_identity_headers_are_refused_before_anything_else
        """
        issue = create_bond_issue(**DESIGN_ISSUE)
        if probe == "missing_role":
            response = api_client.get_bond_issue(issue["id"], NO_ROLE_HEADERS)
        elif probe == "unknown_role":
            # An unrecognised role value is an authentication failure, not a 403.
            response = api_client.get_bond_issue(issue["id"], UNKNOWN_ROLE_HEADERS)
        elif probe == "missing_role_and_unknown_path_id":
            # Rung 1 precedes rung 3: this must not become ERR_ISSUE_NOT_FOUND.
            response = api_client.get_bond_issue(NON_EXISTENT_UUID, NO_ROLE_HEADERS)
        elif probe == "empty_user_id":
            response = api_client.create_undertaking(
                {"issue_id": issue["id"], "fiscal_year_end_month_day": "06-30"},
                EMPTY_USER_HEADERS,
            )
        else:
            # Rung 1 precedes rung 5: a plainly impossible month-day is not the answer.
            response = api_client.create_undertaking(
                {"issue_id": issue["id"], "fiscal_year_end_month_day": "13-45"},
                NO_USER_HEADERS,
            )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_the_same_read_succeeds_once_both_headers_are_present(self):
        """The control call proves the refusals above were about the headers alone.

        PRD §2.1: "Read access is uniform. Every single-resource read and every list endpoint under `/disclosure` is available to all four roles; the write surface is partitioned exactly as described above and enumerated in §4."
        PRD §3.1: "A freshly registered issue opens in `status` `OUTSTANDING` with `version` 1."
        Design: Corner/rbac/missing_or_unknown_identity_headers_are_refused_before_anything_else
        """
        issue = create_bond_issue(**DESIGN_ISSUE)
        control = validate_success(api_client.get_bond_issue(issue["id"], FD))
        assert control["status"] == "OUTSTANDING"
        assert control["version"] == 1


class TestSegregationOfPreparationFromAssembly:
    """The attester of any non-VOID item is barred from assembling the cycle."""

    @pytest.mark.parametrize(
        "attester_id",
        [OFFICER_PREPARER_ID, OFFICER_ASSEMBLER_ID],
        ids=["attester_of_the_first_item", "attester_of_the_second_item"],
    )
    def test_the_officer_who_attested_content_may_not_assemble_the_cycle(self, attester_id):
        """Both attesters are refused, because the scan covers every non-VOID item.

        PRD §2.1: "First, preparation is segregated from assembly: the user declaring an annual report assembled must not equal the `attested_by_user_id` of any non-`VOID` content item of that cycle."
        PRD §3.4: "Segregation of duties is checked next and therefore **before** either content check: the `X-User-ID` performing the assembly must differ from the `attested_by_user_id` of every non-`VOID` content item of the cycle, and a match is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.10: "12. Segregation of duties, preparation versus assembly → `ERR_SEGREGATION_OF_DUTIES` (403). Applies to `POST /disclosure/annual-report-cycles/{id}/assemble`."
        Design: Corner/rbac/the_officer_who_attested_content_may_not_assemble_the_cycle
        """
        context = _setup_cycle_attested_by_two_officers()
        assert context["item_fin"]["attested_by_user_id"] == OFFICER_PREPARER_ID
        assert context["item_fin"]["status"] == "READY"
        assert context["item_ops"]["attested_by_user_id"] == OFFICER_ASSEMBLER_ID
        assert context["item_ops"]["status"] == "READY"

        validate_error(
            api_client.assemble_cycle(
                context["cycle"]["id"], make_officer_headers(attester_id)
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

    def test_a_third_officer_who_attested_nothing_may_assemble(self):
        """The cycle is fully READY, so a disinterested officer completes the assembly.

        PRD §3.4: "A successful assembly stamps `assembled_by_user_id` from `X-User-ID` and `assembled_at` from the logical clock, and re-derives `completeness_score_pct`."
        PRD §3.4: "Either way the cycle lands in `READY_TO_FILE`."
        PRD §3.3: "First, each item's contribution is its `weight_bp_snapshot` divided by 10000, multiplied by its readiness factor, multiplied by its opinion multiplier, and that product is rounded half-up to **4 decimal places**. Second, those already-rounded contributions are summed exactly, with no further rounding of the sum. Third, the sum is multiplied by 100 and rounded half-up to **2 decimal places** to give `completeness_score_pct`."
        PRD §3.3: "Each item in the set has a readiness factor — 1.0 when its `status` is `READY` or `WAIVED`, 0.5 when `DRAFT`, and 0.0 when `NOT_STARTED` — and an opinion multiplier that reflects the quality of the audit opinion behind it."
        Design: Corner/rbac/the_officer_who_attested_content_may_not_assemble_the_cycle
        """
        context = _setup_cycle_attested_by_two_officers()
        assembled = validate_success(
            api_client.assemble_cycle(
                context["cycle"]["id"], make_officer_headers(OFFICER_THIRD_ID)
            )
        )
        assert_annual_report_cycle(assembled)
        assert assembled["status"] == "READY_TO_FILE"
        assert assembled["assembled_by_user_id"] == OFFICER_THIRD_ID
        assert_same_instant(assembled["assembled_at"])
        # Weights 7000 and 3000, both READY with an opinion multiplier of 1.0.
        assert_score(assembled["completeness_score_pct"], 100.00, "completeness_score_pct")


class TestSegregationOfReviewFromPublication:
    """The bar on posting follows the current reviewer of record, not a history of them."""

    def test_the_reviewer_who_ran_the_lookback_may_not_post_the_statement(self):
        """Each re-review overwrites the reviewer, so the barred party moves with it.

        PRD §2.1: "Second, review is segregated from publication: the user publishing an official statement must not equal that statement's `reviewed_by_user_id`."
        PRD §2.10: "13. Segregation of duties, review versus publication → `ERR_SEGREGATION_OF_DUTIES` (403). Applies to `POST /disclosure/official-statements/{id}/post`."
        PRD §3.9: "A `DisclosureOfficer` drafts one against the new `issue_id`, naming its `dated_date` and optionally a `lookback_policy` (default `STRICT_FIVE_YEAR`) and an initial `disclosed_event_ids` array (default empty). The draft opens at `status` `DRAFT`, `version` 1, `disclosure_adequacy` `UNKNOWN`, `required_disclosure_event_ids` empty, and `required_disclosure_event_count` 0, with `reviewed_by_user_id`, `reviewed_at`, `posted_by_user_id`, and `posted_at` all null."
        PRD §3.9: "The call then runs the lookback under the now-current policy, writes all three computed fields, and stamps `reviewed_by_user_id` from `X-User-ID` and `reviewed_at` from the logical clock — overwriting them on every self-loop, so the reviewer of record is the most recent one."
        PRD §3.9: "`disclosure_adequacy` is `ADEQUATE` when every id in `required_disclosure_event_ids` appears in `disclosed_event_ids`, and `INCOMPLETE` otherwise; ids in `disclosed_event_ids` that are not required are ignored rather than treated as errors, so an over-inclusive document is adequate."
        PRD §3.9: "And the acting `X-User-ID` must differ from `reviewed_by_user_id`, or the post is refused with `ERR_SEGREGATION_OF_DUTIES`; a `ComplianceReviewer` may not both review and publish the same document, and no role hierarchy can satisfy the prohibition because both acts belong to the same role."
        PRD §3.9: "A successful post stamps `posted_by_user_id` and `posted_at`, and appends this statement's id to `disclosed_in_official_statement_ids` on every failure event listed in `required_disclosure_event_ids`, in `required_disclosure_event_ids` order."
        Design: Corner/rbac/the_reviewer_who_ran_the_lookback_may_not_post_the_statement
        """
        base = setup_issue_with_undertaking(issue=dict(DESIGN_ISSUE))
        statement = create_official_statement(base["issue"]["id"], dated_date="2026-09-15")
        assert_official_statement(statement)
        assert statement["status"] == "DRAFT"
        assert statement["lookback_policy"] == "STRICT_FIVE_YEAR", "the declared default"

        statement_id = statement["id"]
        first_review = validate_success(
            api_client.review_official_statement(
                statement_id, REVIEWER, {"disclosed_event_ids": []}
            )
        )
        assert_official_statement(first_review)
        assert first_review["status"] == "COMPLIANCE_REVIEW"
        assert first_review["reviewed_by_user_id"] == REVIEWER_ONE_ID
        # No FailureToFileEvent exists at all, so the required set is empty.
        assert first_review["required_disclosure_event_count"] == 0
        assert first_review["required_disclosure_event_ids"] == []
        assert first_review["disclosure_adequacy"] == "ADEQUATE"

        # Adequacy already holds, so rung 13 is the only rung that can answer.
        validate_error(
            api_client.post_official_statement(statement_id, REVIEWER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        second_review = validate_success(
            api_client.review_official_statement(
                statement_id, SECOND_REVIEWER, {"disclosed_event_ids": []}
            )
        )
        assert second_review["status"] == "COMPLIANCE_REVIEW"
        assert second_review["reviewed_by_user_id"] == REVIEWER_TWO_ID, (
            "the self-loop overwrites the reviewer of record"
        )

        # The permission has flipped: rev-2 is now the barred party.
        validate_error(
            api_client.post_official_statement(statement_id, SECOND_REVIEWER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        posted = validate_success(api_client.post_official_statement(statement_id, REVIEWER))
        assert_official_statement(posted)
        assert posted["status"] == "POSTED"
        assert posted["posted_by_user_id"] == REVIEWER_ONE_ID
        assert_same_instant(posted["posted_at"])
        assert posted["reviewed_by_user_id"] == REVIEWER_TWO_ID, (
            "the check reads the current reviewer, not a history of reviewers"
        )
