"""The logical conservation clock, the cycle checkpoint sweep, and the immediacy
of the cascades those two drive.

Every stamped deadline in the register is derived from the logical clock at the
moment a row is created, the cycle checkpoint is the only sweep that lapses
consultations and elapses notices, routine care windows are gated against that
same clock, and every cascaded movement is durable the instant the triggering
write returns.
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    assert_maintenance_visit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.factories import maintenance_visit_payload
from test_helpers.fixtures import (
    create_artwork,
    create_assessment,
    create_protocol,
    open_consultation,
    read_artwork,
    read_consultation,
    read_notice,
    send_notice,
    set_clock,
    setup_assessment_finalized,
    setup_assessment_submitted,
    setup_register,
    setup_scheduled_visit,
)
from test_helpers.test_users import CHIEF_CONSERVATOR_USER_ID, TEST_USERS

# The survey used throughout: a BRONZE work on an URBAN site scored 3/3/3/2/2.
# Weighted defect 0.30*3 + 0.25*3 + 0.20*3 + 0.15*2 + 0.10*2 = 2.75; the URBAN
# exposure penalty 3.0 is halved because no single axis has failed outright, so
# the index is 100 - 25*2.75 - 1.5 = 29.75, rounded half up to 29.8.
SURVEY_SCORES = {
    "surface_score": 3,
    "structural_score": 3,
    "coating_score": 3,
    "mount_score": 2,
    "graffiti_score": 2,
}
EXPECTED_INDEX = 29.8
# deficit 70.2 * LANDMARK 1.5 * URBAN 1.25 * deferral 1.0 = 131.625 -> 131.63
EXPECTED_SINGLE_ASSESSMENT_SCORE = 131.63
# the same product carried by the 92-day deferral factor 1.368 -> 180.0630
EXPECTED_CYCLE_COHORT_SCORE = 180.06
CHECKPOINT_CLOCK_UTC = "2026-11-01T00:00:00Z"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so a comparison ignores fractional digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_cycle_checkpoint_rescores_only_works_finalized_in_the_named_cycle_year(api):
    """PRD §3.9: "It rescores every work holding at least one finalized survey in
    that cycle year under the cycle-cohort variant, sets each such work's
    `priority_basis` to `CYCLE_COHORT` and recomputes cohort ranks."
    PRD §3.9: "Under the **cycle-cohort** variant, which runs at the cycle
    checkpoint, the source is the *earliest* finalized survey of the named cycle
    year for that work — ordered by `assessed_on` ascending and, where two surveys
    share a date, by `created_at` ascending — and the deferral day count is
    measured from that survey's `assessed_on` to the logical clock; the work's
    `priority_basis` is set to `CYCLE_COHORT`."
    PRD §3.9: "The checkpoint reports what it did, echoing the `cycle_year` it ran
    for alongside `artworks_rescored`, `consultations_lapsed`, `notices_elapsed`
    and `artworks_returned_to_monitored`."

    Design: Corner/endpoints/cycle_checkpoint_returns_a_summary_body_and_rescopes_only_the_named_cycle
    """
    register = setup_register(api)
    finalized_work = register["artwork"]
    # A second work whose only 2026 survey never leaves DRAFT, so nothing about it
    # is finalized in the cycle year the checkpoint will run for.
    draft_only_work = create_artwork(
        api,
        register["artist"]["id"],
        register["site"]["id"],
        accession_number="2024.002",
        title="Seated Figure",
        footprint_units=4,
    )
    setup_assessment_finalized(
        api, finalized_work["id"], cycle_year=2026, assessed_on="2026-08-01",
        **SURVEY_SCORES,
    )
    create_assessment(
        api,
        draft_only_work["id"],
        cycle_year=2026,
        assessed_on="2026-08-01",
        surface_score=4,
        structural_score=4,
        coating_score=4,
        mount_score=4,
        graffiti_score=4,
    )

    # Finalization alone leaves the work scored under the single-assessment variant.
    before = read_artwork(api, finalized_work["id"])
    assert before["condition_index"] == EXPECTED_INDEX
    assert before["priority_basis"] == "SINGLE_ASSESSMENT"
    assert before["treatment_priority_score"] == EXPECTED_SINGLE_ASSESSMENT_SCORE
    assert before["conservation_status"] == "TREATMENT_REQUIRED"

    set_clock(api, CHECKPOINT_CLOCK_UTC)
    summary = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )

    assert summary["cycle_year"] == 2026
    assert summary["artworks_rescored"] == 1
    assert summary["consultations_lapsed"] == 0
    assert summary["notices_elapsed"] == 0
    assert summary["artworks_returned_to_monitored"] == 0
    # The checkpoint reports what it did; it does not return a register record.
    assert "id" not in summary
    assert "version" not in summary

    rescored = read_artwork(api, finalized_work["id"])
    assert rescored["priority_basis"] == "CYCLE_COHORT"
    assert rescored["treatment_priority_score"] == EXPECTED_CYCLE_COHORT_SCORE
    assert rescored["treatment_priority_rank"] == 1

    untouched = read_artwork(api, draft_only_work["id"])
    assert untouched["treatment_priority_score"] is None
    assert untouched["priority_basis"] == "NONE"
    assert untouched["treatment_priority_rank"] is None
    assert untouched["conservation_status"] == "MONITORED"


def test_cycle_checkpoint_for_a_year_with_no_finalized_survey_changes_nothing(api):
    """PRD §3.9: "It rescores every work holding at least one finalized survey in
    that cycle year under the cycle-cohort variant, sets each such work's
    `priority_basis` to `CYCLE_COHORT` and recomputes cohort ranks."
    PRD §3.9: "The checkpoint reports what it did, echoing the `cycle_year` it ran
    for alongside `artworks_rescored`, `consultations_lapsed`, `notices_elapsed`
    and `artworks_returned_to_monitored`."
    PRD §2.5: "`version` (integer): a counter that increments by exactly one on
    every mutation of the record."

    Design: Corner/endpoints/cycle_checkpoint_returns_a_summary_body_and_rescopes_only_the_named_cycle
    """
    register = setup_register(api)
    setup_assessment_finalized(
        api, register["artwork"]["id"], cycle_year=2026, assessed_on="2026-08-01",
        **SURVEY_SCORES,
    )
    set_clock(api, CHECKPOINT_CLOCK_UTC)
    validate_success(api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"]))
    after_2026 = read_artwork(api, register["artwork"]["id"])

    summary = validate_success(
        api.run_cycle({"cycle_year": 2025}, TEST_USERS["manager_headers"])
    )

    assert summary["cycle_year"] == 2025
    assert summary["artworks_rescored"] == 0
    assert summary["consultations_lapsed"] == 0
    assert summary["notices_elapsed"] == 0
    assert summary["artworks_returned_to_monitored"] == 0

    # No cohort matched 2025, so the 2026 cohort scoring stands untouched.
    after_2025 = read_artwork(api, register["artwork"]["id"])
    assert after_2025["treatment_priority_score"] == EXPECTED_CYCLE_COHORT_SCORE
    assert after_2025["priority_basis"] == "CYCLE_COHORT"
    assert after_2025["treatment_priority_rank"] == 1
    assert after_2025["version"] == after_2026["version"]


def test_pinned_default_clock_stamps_consultation_and_notice_deadlines(api):
    """PRD §2.6: "Every stamped instant, every deadline and every year comparison
    is derived from a single logical clock, which reads exactly
    `2026-08-01T00:00:00Z` until it is moved."
    PRD §3.6: "Creation stamps `sent_on` with the logical clock's calendar date and
    derives `due_at` by advancing the logical clock by the artist's
    `consultation_response_days`."
    PRD §3.6: "Creation stamps `sent_at` from the logical clock, derives
    `earliest_action_at` by advancing that instant by the artist's
    `notice_wait_days`, sets `status` to `SENT`, leaves `acknowledged_at` and
    `consumed_by_ref` null, and raises the work's `open_notice_count` by one — that
    counter being maintained as the number of the work's notices sitting in `SENT`,
    `ACKNOWLEDGED` or `WAIT_ELAPSED`."

    Design: Corner/endpoints/the_logical_clock_starts_pinned_and_only_forward_stamps_move
    """
    register = setup_register(api)
    artist, artwork = register["artist"], register["artwork"]
    # The artist takes both procedural defaults: 30 response days, 90 notice days.
    assert artist["consultation_response_days"] == 30
    assert artist["notice_wait_days"] == 90

    consultation = open_consultation(
        api, artwork["id"], artist["id"], subject="RELOCATION"
    )
    notice = send_notice(api, artwork["id"], artist["id"], action_type="RELOCATION")

    assert consultation["status"] == "PENDING"
    assert consultation["sent_on"] == "2026-08-01"
    assert _instant(consultation["due_at"]) == _instant("2026-08-31T00:00:00Z")
    assert consultation["responded_at"] is None

    assert notice["status"] == "SENT"
    assert _instant(notice["sent_at"]) == _instant(DEFAULT_CLOCK_UTC)
    assert _instant(notice["earliest_action_at"]) == _instant("2026-10-30T00:00:00Z")
    assert notice["acknowledged_at"] is None
    assert notice["consumed_by_ref"] is None
    assert read_artwork(api, artwork["id"])["open_notice_count"] == 1


def test_moving_the_clock_forward_leaves_stamped_deadlines_and_statuses_alone(api):
    """PRD §2.6: "An administrative test-driving capability accepts a `to_iso8601`
    instant and moves the clock to it, returning the new value as `current_utc`;
    the capability is restricted to `PublicArtManager`."
    PRD §3.6: "The cycle checkpoint moves every `PENDING` consultation whose
    `due_at` is at or before the logical clock to `LAPSED`, and a lapsed
    consultation clears the approval gate exactly as a concurrence does."
    PRD §3.6: "Alternatively the cycle checkpoint moves a `SENT` notice whose
    `earliest_action_at` is at or before the logical clock to `WAIT_ELAPSED`."

    Design: Corner/endpoints/the_logical_clock_starts_pinned_and_only_forward_stamps_move
    """
    register = setup_register(api)
    artist, artwork = register["artist"], register["artwork"]
    early_consultation = open_consultation(
        api, artwork["id"], artist["id"], subject="RELOCATION"
    )
    early_notice = send_notice(
        api, artwork["id"], artist["id"], action_type="RELOCATION"
    )

    moved = set_clock(api, "2026-09-10T12:00:00Z")
    assert _instant(moved["current_utc"]) == _instant("2026-09-10T12:00:00Z")

    # A row created after the move takes the same response window from the new
    # clock, keeping its time-of-day component.
    late_consultation = open_consultation(
        api, artwork["id"], artist["id"], subject="TREATMENT"
    )
    assert late_consultation["sent_on"] == "2026-09-10"
    assert _instant(late_consultation["due_at"]) == _instant("2026-10-10T12:00:00Z")

    # The already-stamped deadlines never drift, and moving the clock on its own
    # lapses no consultation and elapses no notice: only the checkpoint does that.
    reread_consultation = read_consultation(api, early_consultation["id"])
    assert _instant(reread_consultation["due_at"]) == _instant("2026-08-31T00:00:00Z")
    assert reread_consultation["status"] == "PENDING"
    assert reread_consultation["version"] == early_consultation["version"]

    reread_notice = read_notice(api, early_notice["id"])
    assert _instant(reread_notice["earliest_action_at"]) == _instant(
        "2026-10-30T00:00:00Z"
    )
    assert reread_notice["status"] == "SENT"
    assert reread_notice["version"] == early_notice["version"]


def test_visit_scheduling_refuses_a_foreign_material_protocol_and_a_past_window(api):
    """PRD §3.3: "The protocol's `material_class` must equal the work's
    `material_class`, and a mismatch is refused with
    `ERR_PROTOCOL_MATERIAL_MISMATCH`."
    PRD §3.3: "A window may not be scheduled into the past: `window_start` must be
    at or after the logical clock, and an earlier value draws `ERR_WINDOW_IN_PAST`."
    PRD §3.3: "When `graffiti_reported_at` is omitted it stays null,
    `sla_deadline_at` stays null, and `sla_breached` stays false for the life of
    the visit."

    Design: Corner/endpoints/visit_scheduling_and_start_are_conditional_on_protocol_material_and_clock
    """
    register = setup_register(api)
    artwork = register["artwork"]
    assert artwork["material_class"] == "BRONZE"
    bronze_protocol = create_protocol(api)
    stone_protocol = create_protocol(
        api, protocol_code="WASH-ST", material_class="STONE", cycle_days=365
    )

    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(artwork["id"], stone_protocol["id"]),
            TEST_USERS["crew_headers"],
        ),
        ApiErrorId.ERR_PROTOCOL_MATERIAL_MISMATCH.value,
    )
    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(
                artwork["id"],
                bronze_protocol["id"],
                window_start="2026-07-01T09:00:00Z",
                window_end="2026-07-02T17:00:00Z",
            ),
            TEST_USERS["crew_headers"],
        ),
        ApiErrorId.ERR_WINDOW_IN_PAST.value,
    )

    visit = validate_success(
        api.create_maintenance_visit(
            maintenance_visit_payload(
                artwork["id"], bronze_protocol["id"], crew_note="quarterly wash"
            ),
            TEST_USERS["crew_headers"],
        ),
        201,
    )
    assert_maintenance_visit(visit)
    assert visit["status"] == "SCHEDULED"
    assert visit["abort_reason"] == "NONE"
    assert visit["graffiti_reported_at"] is None
    assert visit["sla_deadline_at"] is None
    assert visit["sla_breached"] is False

    # Neither rejection left a visit behind on the work.
    visits, meta = validate_paginated(
        api.list_maintenance_visits(
            TEST_USERS["crew_headers"], {"artwork_id": artwork["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in visits] == [visit["id"]]


def test_crew_may_start_a_visit_only_once_its_window_has_opened(api):
    """PRD §3.3: "The logical clock must be at or after `window_start` — an earlier
    attempt draws `ERR_VISIT_WINDOW_NOT_OPEN` — and the work's `custody_status`
    must be `ON_VIEW` or `IN_STORAGE`, since a work already `IN_TREATMENT` cannot
    receive routine care; that failure is `ERR_ARTWORK_CUSTODY_INVALID`."
    PRD §3.3: "Starting stamps `started_at` from the logical clock and moves any
    funding allocation attached to the visit from `RESERVED` to `COMMITTED`."

    Design: Corner/endpoints/visit_scheduling_and_start_are_conditional_on_protocol_material_and_clock
    """
    state = setup_scheduled_visit(api)
    visit, artwork = state["visit"], state["artwork"]

    # The clock still reads its pinned default, well before the work window opens.
    validate_error(
        api.start_maintenance_visit(visit["id"], {}, TEST_USERS["crew_headers"]),
        ApiErrorId.ERR_VISIT_WINDOW_NOT_OPEN.value,
    )
    refused = validate_success(
        api.get_maintenance_visit(visit["id"], TEST_USERS["crew_headers"])
    )
    assert refused["status"] == "SCHEDULED"
    assert refused["started_at"] is None
    assert refused["version"] == visit["version"]

    # The boundary instant itself counts as open.
    set_clock(api, visit["window_start"])
    started = validate_success(
        api.start_maintenance_visit(
            visit["id"], {"crew_note": "on site"}, TEST_USERS["crew_headers"]
        )
    )
    assert started["status"] == "IN_PROGRESS"
    assert _instant(started["started_at"]) == _instant(visit["window_start"])

    # Starting routine care moves neither dimension of the work itself.
    unmoved = read_artwork(api, artwork["id"])
    assert unmoved["custody_status"] == "ON_VIEW"
    assert unmoved["conservation_status"] == "MONITORED"
    assert unmoved["maintenance_applications_ytd"] == 0
    assert unmoved["last_maintenance_completed_on"] is None


def test_finalization_response_and_the_next_reads_already_show_cascade_a_complete(api):
    """PRD §2.9: "Cascades are applied immediately and synchronously within the
    request that triggered them; there is no deferred or eventual reconciliation
    anywhere in this system."
    PRD §3.2: "Hop 2: because this survey is now finalized, the work's
    `condition_index` is set to the survey's index, its `treatment_priority_score`
    is recomputed under the single-assessment variant described in §3.9, its
    `priority_basis` is set to `SINGLE_ASSESSMENT`, and its conservation dimension
    moves `MONITORED → TREATMENT_REQUIRED` or `STABILIZED → TREATMENT_REQUIRED`
    when the new index is below 55.0."
    PRD §3.2: "Hop 3: because the work now requires treatment, every maintenance
    visit on that work still sitting in `SCHEDULED` whose protocol does not require
    a conservator moves `SCHEDULED → ABORTED` with `abort_reason` set to
    `SUPERSEDED_BY_TREATMENT`; visits whose protocol does require a conservator are
    left alone."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_immediately_after_the_write
    """
    state = setup_scheduled_visit(api, protocol={"requires_conservator": False})
    artwork, visit = state["artwork"], state["visit"]
    assessment = setup_assessment_submitted(
        api, artwork["id"], cycle_year=2026, assessed_on="2026-08-01", **SURVEY_SCORES
    )

    finalized = validate_success(
        api.finalize_condition_assessment(
            assessment["id"],
            {"finalization_note": "urgent band confirmed"},
            TEST_USERS["chief_conservator_headers"],
        )
    )

    # The triggering response already carries the derived fields.
    assert finalized["status"] == "FINALIZED"
    assert finalized["condition_index"] == EXPECTED_INDEX
    assert finalized["recommendation"] == "URGENT"
    assert finalized["finalized_by_user_id"] == CHIEF_CONSERVATOR_USER_ID

    # The very next read of the work shows hop 2 durable.
    reread_artwork = read_artwork(api, artwork["id"])
    assert reread_artwork["condition_index"] == EXPECTED_INDEX
    assert reread_artwork["treatment_priority_score"] == EXPECTED_SINGLE_ASSESSMENT_SCORE
    assert reread_artwork["priority_basis"] == "SINGLE_ASSESSMENT"
    assert reread_artwork["conservation_status"] == "TREATMENT_REQUIRED"
    assert reread_artwork["treatment_priority_rank"] == 1
    # Immediate does not mean more than declared: the custody dimension is not touched.
    assert reread_artwork["custody_status"] == "ON_VIEW"

    # And the very next read of the visit shows the cross-entity hop 3 durable.
    reread_visit = validate_success(
        api.get_maintenance_visit(visit["id"], TEST_USERS["crew_headers"])
    )
    assert reread_visit["status"] == "ABORTED"
    assert reread_visit["abort_reason"] == "SUPERSEDED_BY_TREATMENT"
    assert reread_visit["version"] > visit["version"]
