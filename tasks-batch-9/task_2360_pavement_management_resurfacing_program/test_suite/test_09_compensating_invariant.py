"""Undo actions that must restore every conserved quantity with no residue."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_money,
    assert_project_estimate,
    assert_project_scope,
    assert_scenario_funding,
)
from test_helpers.constants import (
    AREA_MAPLE,
    FUNDING_STANDARD,
    MAPLE_BUNDLE_BASE,
    MAPLE_CONTINGENCY,
    MAPLE_OAK_AREA,
    MAPLE_OAK_BASE,
    MAPLE_OAK_CONTINGENCY,
    MAPLE_OAK_TOTAL,
    MAPLE_TOTAL,
    OAK_LINE_COST,
    UNCOMMITTED_AFTER_MAPLE_AWARD,
)
from test_helpers.factories import award_payload, cancel_award_payload, close_payload
from test_helpers.test_users import ENGINEER, OFFICER_AWARDER

OAK_WINDOW_START = "2026-09-01T00:00:00Z"
OAK_WINDOW_END = "2026-09-30T00:00:00Z"
SLA_DUE_HIGH = "2026-08-04T00:00:00"


def _awarded_then_ready_to_cancel(api):
    """A BID_READY Maple St bundle awarded at exactly its own estimate."""
    ctx = fixtures.maple_bid_ready(api)
    before = fixtures.read_scenario(api, ctx["scenario"]["id"])
    assert_scenario_funding(before, FUNDING_STANDARD, 0, FUNDING_STANDARD)
    assert_money(ctx["project"]["project_total_estimate_cents"], MAPLE_TOTAL)

    awarded = validate_success(
        api.award_project(
            ctx["project"]["id"],
            award_payload(ctx["contractor"]["id"], MAPLE_TOTAL),
            OFFICER_AWARDER,
        )
    )
    after_award = fixtures.read_scenario(api, ctx["scenario"]["id"])
    assert_scenario_funding(
        after_award, FUNDING_STANDARD, MAPLE_TOTAL, UNCOMMITTED_AFTER_MAPLE_AWARD
    )
    return ctx, before, awarded, after_award


def test_cancelling_an_award_restores_the_funding_ledger_exactly(api):
    """The stored amount is subtracted back, so both totals return to the cent.

    PRD: "Cancellation subtracts the project's **stored** `award_amount_cents` from
    the scenario's `committed_cents` — never a recomputed estimate — recomputes
    `uncommitted_cents`, clears both `contractor_id` and `award_amount_cents` back to
    null, and increments the scenario's `version` by 1, restoring the funding
    conservation invariant of §2.11 exactly."

    PRD: "Awarding an amount and then cancelling that award on the same project
    restores both totals to their exact pre-award values for any amount, because
    cancellation subtracts the stored `award_amount_cents` rather than any
    recomputed estimate."

    Design: Difficulty/compensating_invariant/cancel_award_restores_scenario_committed_and_uncommitted_exactly
    """
    ctx, before, _awarded, _after_award = _awarded_then_ready_to_cancel(api)

    cancelled = validate_success(
        api.cancel_award(
            ctx["project"]["id"],
            cancel_award_payload("bid protest sustained"),
            OFFICER_AWARDER,
        )
    )
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])

    assert cancelled["delivery_status"] == "BID_READY"
    assert cancelled["contractor_id"] is None
    assert cancelled["award_amount_cents"] is None
    assert_scenario_funding(scenario, FUNDING_STANDARD, 0, FUNDING_STANDARD)
    assert scenario["committed_cents"] == before["committed_cents"]
    assert scenario["uncommitted_cents"] == before["uncommitted_cents"]


def test_the_restored_ledger_still_leaves_the_version_counter_advanced(api):
    """Money is conserved, but the optimistic-concurrency counter never rewinds.

    PRD: "Every scenario run, adoption, award, award cancellation and prior manual
    add advances that `version`; if the value supplied no longer equals the
    scenario's current `version`, the create is rejected with
    `ERR_STALE_SCENARIO_VERSION` and HTTP 412, preventing a client from adding to a
    funding picture it has not observed."

    A cancelled award also leaves no performance trace on the firm that briefly held
    it.

    Design: Difficulty/compensating_invariant/cancel_award_restores_scenario_committed_and_uncommitted_exactly
    """
    ctx, before, _awarded, after_award = _awarded_then_ready_to_cancel(api)

    validate_success(
        api.cancel_award(
            ctx["project"]["id"],
            cancel_award_payload("bid protest sustained"),
            OFFICER_AWARDER,
        )
    )
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])
    contractor = fixtures.read_contractor(api, ctx["contractor"]["id"])

    assert after_award["version"] == before["version"] + 1
    assert scenario["version"] == before["version"] + 2
    assert contractor["standing"] == "GOOD_STANDING"
    assert contractor["accepted_project_count"] == 0
    assert contractor["passed_test_count"] == 0
    assert contractor["failed_test_count"] == 0


def _maple_bundle_with_a_spare_oak_candidate(api):
    """A DRAFT one-line bundle plus an untouched Oak St crack-seal candidate."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, fixtures.MAPLE_LINE)
    assert_project_scope(ctx["project"], 1, AREA_MAPLE)
    assert_project_estimate(
        ctx["project"], MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL
    )
    oak_candidate = fixtures.read_candidate(api, fixtures.candidate_for(ctx, "Oak St")["id"])
    assert oak_candidate["candidate_status"] == "RECOMMENDED"
    assert oak_candidate["override_reason"] is None
    assert fixtures.read_segment(api, fixtures.segment_for(ctx, "Oak St")["id"])[
        "active_project_count"
    ] == 0
    return ctx


def test_removing_a_line_restores_the_bundle_price_and_area_exactly(api):
    """Every counter the add moved comes back to its pre-add value, to the cent.

    PRD: "Removal decrements the project's `segment_count`, subtracts the line's
    `line_area_sy` from `planned_area_sy`, decrements the segment's
    `active_project_count`, recomputes `bundle_base_cents`, `contingency_cents`,
    `utility_share_cents` and `project_total_estimate_cents`, and increments the
    project's `version` — restoring the conserved quantities of §2.11 exactly."

    Adding Oak St lifts the bundle from 11817655 to 16602628 and the area from
    3333.33 to 15058.33; removing it puts both back precisely.

    Design: Difficulty/compensating_invariant/line_removal_restores_project_area_counters_and_candidate_status
    """
    ctx = _maple_bundle_with_a_spare_oak_candidate(api)
    oak_line = fixtures.add_line(
        api,
        ctx["project"]["id"],
        fixtures.segment_for(ctx, "Oak St")["id"],
        fixtures.candidate_for(ctx, "Oak St")["id"],
        OAK_WINDOW_START,
        OAK_WINDOW_END,
    )
    assert_money(oak_line["line_cost_cents"], OAK_LINE_COST)
    grown = fixtures.read_project(api, ctx["project"]["id"])
    assert_project_scope(grown, 2, MAPLE_OAK_AREA)
    assert_project_estimate(
        grown, MAPLE_OAK_BASE, MAPLE_OAK_CONTINGENCY, 0, MAPLE_OAK_TOTAL
    )

    removed = validate_success(api.delete_project_segment(oak_line["id"], ENGINEER))
    shrunk = fixtures.read_project(api, ctx["project"]["id"])

    assert removed["work_state"] == "REMOVED"
    assert_project_scope(shrunk, 1, AREA_MAPLE)
    assert_project_estimate(shrunk, MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL)


def test_removing_a_line_returns_the_candidate_to_the_pool(api):
    """The freed candidate is reusable and the segment's occupancy count drops back.

    PRD: "The freed candidate returns to the pool, and which state it returns to
    depends on its history: a candidate with a null `override_reason` returns to
    `RECOMMENDED`, while a candidate carrying an `override_reason` returns to
    `OVERRIDDEN` with its override intact."

    Design: Difficulty/compensating_invariant/line_removal_restores_project_area_counters_and_candidate_status
    """
    ctx = _maple_bundle_with_a_spare_oak_candidate(api)
    oak_segment_id = fixtures.segment_for(ctx, "Oak St")["id"]
    oak_candidate_id = fixtures.candidate_for(ctx, "Oak St")["id"]
    oak_line = fixtures.add_line(
        api,
        ctx["project"]["id"],
        oak_segment_id,
        oak_candidate_id,
        OAK_WINDOW_START,
        OAK_WINDOW_END,
    )
    assert fixtures.read_candidate(api, oak_candidate_id)["candidate_status"] == "CONSUMED"
    assert fixtures.read_segment(api, oak_segment_id)["active_project_count"] == 1

    validate_success(api.delete_project_segment(oak_line["id"], ENGINEER))

    still_there = fixtures.read_line(api, oak_line["id"])
    candidate = fixtures.read_candidate(api, oak_candidate_id)
    assert still_there["work_state"] == "REMOVED"
    assert candidate["candidate_status"] == "RECOMMENDED"
    assert candidate["override_reason"] is None
    assert fixtures.read_segment(api, oak_segment_id)["active_project_count"] == 0


def _two_open_complaints_on_a_quiet_block(api):
    """A segment with no project activity carrying two HIGH pothole complaints."""
    fixtures.set_clock(api)
    segment = fixtures.create_segment(api)
    assert segment["open_service_request_count"] == 0

    first = fixtures.file_service_request(
        api, segment["id"], location_note="deep pothole at the 1200 block driveway"
    )
    second = fixtures.file_service_request(
        api, segment["id"], location_note="second pothole near the 1300 block crosswalk"
    )
    assert first["request_status"] == "NEW"
    assert first["sla_due_at"].startswith(SLA_DUE_HIGH)
    assert first["sla_breached"] is False
    assert fixtures.read_segment(api, segment["id"])["open_service_request_count"] == 2
    return segment["id"], first, second


def test_triage_leaves_the_open_complaint_count_alone(api):
    """The complaint changes hands without changing how many are open.

    PRD: "Triage requires the request to still be `NEW`, else
    `ERR_SERVICE_REQUEST_NOT_NEW`, and — per §2.11 — never changes the segment's
    `open_service_request_count`."

    PRD: "A segment's `active_project_count` counts the project lines referencing it
    whose `work_state` is `PLANNED`, `IN_PROGRESS`, `WORK_COMPLETE` or
    `REMEDIATION_REQUIRED`, and its `open_service_request_count` counts the
    complaints on it whose `request_status` is `NEW`, `TRIAGED_PATCH` or
    `DEFERRED_TO_CAPITAL`."

    Design: Difficulty/compensating_invariant/duplicate_close_decrements_open_service_request_count_exactly_once
    """
    segment_id, first, _second = _two_open_complaints_on_a_quiet_block(api)

    triaged = fixtures.triage_service_request(api, first["id"], "PATCH")

    assert triaged["request_status"] == "TRIAGED_PATCH"
    assert triaged["capital_project_id"] is None
    assert triaged["triaged_at"] is not None
    assert fixtures.read_segment(api, segment_id)["open_service_request_count"] == 2


def test_a_second_close_on_the_same_complaint_decrements_nothing(api):
    """The counter falls once per complaint and never goes negative.

    PRD: "Either closure stamps `closed_at` from the logical clock, recomputes
    `sla_breached` against `closed_at`, and decrements the segment's
    `open_service_request_count`. Closing an already-closed request reports
    `ERR_SERVICE_REQUEST_ALREADY_CLOSED`."

    The clock never leaves 2026-08-01, so neither 72-hour deadline is passed and
    both closures record `sla_breached` false.

    Design: Difficulty/compensating_invariant/duplicate_close_decrements_open_service_request_count_exactly_once
    """
    segment_id, first, second = _two_open_complaints_on_a_quiet_block(api)
    fixtures.triage_service_request(api, first["id"], "PATCH")

    closed_first = fixtures.close_service_request(api, first["id"], "PATCHED")
    assert closed_first["request_status"] == "CLOSED_PATCHED"
    assert closed_first["closure_code"] == "PATCHED"
    assert closed_first["sla_breached"] is False
    assert fixtures.read_segment(api, segment_id)["open_service_request_count"] == 1

    validate_error(
        api.close_service_request(first["id"], close_payload("DUPLICATE"), ENGINEER),
        ApiErrorId.SERVICE_REQUEST_ALREADY_CLOSED,
        409,
    )
    assert fixtures.read_segment(api, segment_id)["open_service_request_count"] == 1

    closed_second = fixtures.close_service_request(api, second["id"], "DUPLICATE")
    assert closed_second["request_status"] == "CLOSED_DUPLICATE"
    assert fixtures.read_segment(api, segment_id)["open_service_request_count"] == 0

    validate_error(
        api.close_service_request(second["id"], close_payload("DUPLICATE"), ENGINEER),
        ApiErrorId.SERVICE_REQUEST_ALREADY_CLOSED,
        409,
    )
    assert fixtures.read_segment(api, segment_id)["open_service_request_count"] == 0
