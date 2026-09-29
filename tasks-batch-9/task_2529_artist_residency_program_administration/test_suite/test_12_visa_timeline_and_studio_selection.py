"""Derived sponsorship dates, and the studio the server picks when nobody names one."""

from test_helpers import (
    ERR_FACILITY_UNAVAILABLE,
    ERR_NO_STUDIO_AVAILABLE,
    FACILITIES_HEADERS,
    assert_studio_day_ledger,
    assign_studio,
    create_applicant,
    create_international_applicant,
    create_residency,
    create_studio,
    get_success_data,
    make_studio_assignment_payload,
    obligations_for,
    read_residency,
    read_visa_case,
    refresh_residency,
    refresh_studio,
    release_studio_assignment,
    schedule_residency,
    set_clock,
    setup_open_cycle,
    studio_assignments_for,
    validate_error,
    visa_case_for,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"
LATER_START = "2027-03-01"
LATER_END = "2027-05-02"


def _two_sponsored_cases(api):
    """One high-volume citizenship and one ordinary one, on identical calendars."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    cases = {}
    for country in ("IN", "FR"):
        applicant = create_international_applicant(api, citizenship_country=country)
        residency = create_residency(api, cycle, applicant)
        assert residency.residency["visa_required"] is True
        schedule_residency(api, residency, SESSION_START, 8)
        cases[country] = visa_case_for(api, residency.residency_id)
    return cycle, cases


def test_the_high_volume_post_and_the_ordinary_post_take_different_constants(api):
    """Two identical calendars produce two deadlines, 24 days apart.

    PRD: "`backlog_days` is 45 when the sponsored artist's `citizenship_country`
    is one of `IN`, `CN`, `NG` or `BR` — the high-volume posts — and 21 for every
    other citizenship."

    Design: Corner/calculations/visa_backlog_constant_switches_on_the_high_volume_country_list
    """
    _cycle, cases = _two_sponsored_cases(api)

    assert cases["IN"]["backlog_days"] == 45
    assert cases["IN"]["filing_deadline_date"] == "2026-06-20"
    assert cases["FR"]["backlog_days"] == 21
    assert cases["FR"]["filing_deadline_date"] == "2026-07-14"
    # Twenty-four days is exactly the gap between the two constants.
    assert cases["IN"]["backlog_days"] - cases["FR"]["backlog_days"] == 24


def test_the_entry_lead_time_is_a_different_constant_and_ignores_the_country(api):
    """Both residents may enter on the same date although they must file weeks apart.

    PRD: "`earliest_entry_date` is the residency's `session_start_date` minus 30
    days — the first date on which the resident may lawfully enter the host
    country."

    Design: Corner/calculations/visa_backlog_constant_switches_on_the_high_volume_country_list
    """
    _cycle, cases = _two_sponsored_cases(api)

    assert cases["IN"]["earliest_entry_date"] == "2026-10-03"
    assert cases["FR"]["earliest_entry_date"] == "2026-10-03"
    assert cases["IN"]["filing_deadline_date"] != cases["FR"]["filing_deadline_date"]


def test_the_case_type_is_decided_by_session_length_and_not_by_country(api):
    """An eight-week session is a short-term case whichever passport pays for it.

    PRD: "`case_type` is `J1_RESEARCH_SCHOLAR` when the residency's
    `session_length_weeks` is at least 9 and `B1_SHORT_TERM` otherwise, which
    means an eight-week session is a short-term case and a nine-week session is a
    research-scholar case"

    Design: Corner/calculations/visa_backlog_constant_switches_on_the_high_volume_country_list
    """
    _cycle, cases = _two_sponsored_cases(api)

    assert cases["IN"]["case_type"] == "B1_SHORT_TERM"
    assert cases["FR"]["case_type"] == "B1_SHORT_TERM"
    assert cases["IN"]["status"] == "INITIATED"
    assert cases["FR"]["status"] == "INITIATED"


def test_both_countdowns_are_measured_against_the_one_logical_clock(api):
    """The deadlines are already behind the clock, so both figures run negative.

    PRD: "`days_to_filing_deadline` is `filing_deadline_date` minus the current
    date on the logical clock, in whole days, and goes negative once the deadline
    has passed."

    Design: Corner/calculations/visa_backlog_constant_switches_on_the_high_volume_country_list
    """
    _cycle, cases = _two_sponsored_cases(api)

    assert cases["IN"]["days_to_filing_deadline"] == -42
    assert cases["FR"]["days_to_filing_deadline"] == -18


def test_membership_of_the_high_volume_list_is_exact_and_not_approximate(api):
    """A citizenship absent from the four named posts takes the ordinary constant.

    PRD: "the high-volume posts — and 21 for every other citizenship. It is
    derived even before the residency has a calendar."

    Design: Corner/calculations/visa_backlog_constant_switches_on_the_high_volume_country_list
    """
    cycle = setup_open_cycle(api, clock=CLOCK)
    applicant = create_international_applicant(api, citizenship_country="IE")
    residency = create_residency(api, cycle, applicant)

    fresh = visa_case_for(api, residency.residency_id)
    assert fresh["backlog_days"] == 21
    assert fresh["filing_deadline_date"] is None
    assert fresh["earliest_entry_date"] is None
    assert fresh["days_to_filing_deadline"] is None

    schedule_residency(api, residency, SESSION_START, 8)

    dated = read_visa_case(api, fresh["id"])
    assert dated["backlog_days"] == 21
    assert dated["filing_deadline_date"] == "2026-07-14"


def _case_before_the_reschedule(api):
    """A high-volume case whose whole timeline hangs off an eight-week November session."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    applicant = create_international_applicant(api, citizenship_country="IN")
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, SESSION_START, 8)

    case = visa_case_for(api, residency.residency_id)
    assert case["filing_deadline_date"] == "2026-06-20"
    assert case["earliest_entry_date"] == "2026-10-03"
    assert case["case_type"] == "B1_SHORT_TERM"
    assert case["days_to_filing_deadline"] == -42
    return cycle, residency, case


def test_the_reschedule_moves_every_derived_date_on_the_case(api):
    """A new session start drags the deadline and the entry date along with it.

    PRD: "Four of the case's fields are derived, never supplied, and are
    re-derived on creation, whenever the sponsored residency is rescheduled, on
    filing, and on every read of the case."

    Design: Corner/calculations/visa_timeline_is_re_derived_when_the_residency_is_rescheduled
    """
    _cycle, residency, case = _case_before_the_reschedule(api)

    moved = schedule_residency(api, residency, LATER_START, 9)

    assert moved["session_start_date"] == LATER_START
    assert moved["session_length_weeks"] == 9
    assert moved["session_end_date"] == LATER_END
    redated = read_visa_case(api, case["id"])
    assert redated["backlog_days"] == 45
    assert redated["filing_deadline_date"] == "2026-10-17"
    assert redated["earliest_entry_date"] == "2027-01-30"


def test_the_reschedule_carries_the_case_type_across_the_nine_week_boundary(api):
    """Nine weeks is a research-scholar session, and nothing else on the case moves.

    PRD: "And it re-derives the visa case's `case_type`, `filing_deadline_date`
    and `earliest_entry_date` from the new calendar. The residency's `version`
    advances by 1, the cycle's `version` advances by 1, and the visa case's
    `version` advances by 1 when one exists."

    Design: Corner/calculations/visa_timeline_is_re_derived_when_the_residency_is_rescheduled
    """
    _cycle, residency, case = _case_before_the_reschedule(api)

    schedule_residency(api, residency, LATER_START, 9)

    reclassified = read_visa_case(api, case["id"])
    assert reclassified["case_type"] == "J1_RESEARCH_SCHOLAR"
    assert reclassified["version"] == case["version"] + 1
    assert reclassified["status"] == "INITIATED"
    assert reclassified["rfe_round"] == 0
    assert reclassified["requested_doc_list"] == []
    assert reclassified["submitted_doc_list"] == []


def test_the_countdown_flips_sign_and_then_follows_the_clock_alone(api):
    """Once the deadline is in the future the figure is positive, and it tracks time.

    PRD: "It is recomputed on every read rather than stored, so advancing the
    clock changes it without touching the case."

    Design: Corner/calculations/visa_timeline_is_re_derived_when_the_residency_is_rescheduled
    """
    _cycle, residency, case = _case_before_the_reschedule(api)
    schedule_residency(api, residency, LATER_START, 9)
    ahead = read_visa_case(api, case["id"])
    assert ahead["days_to_filing_deadline"] == 77

    set_clock(api, "2026-09-17T00:00:00Z")

    later = read_visa_case(api, case["id"])
    assert later["days_to_filing_deadline"] == 30
    assert later["version"] == ahead["version"]
    assert later["filing_deadline_date"] == "2026-10-17"


def test_the_same_call_re_derives_the_obligations_without_duplicating_them(api):
    """One reschedule updates four rows in place rather than provisioning four more.

    PRD: "Rescheduling does not duplicate rows: an existing `PENDING` row of the
    same `obligation_type` has its `required_count` and `due_date` re-derived in
    place, while rows already in `SATISFIED`, `WAIVED` or `BREACHED` are never
    re-derived."

    Design: Corner/calculations/visa_timeline_is_re_derived_when_the_residency_is_rescheduled
    """
    _cycle, residency, _case = _case_before_the_reschedule(api)
    assert len(obligations_for(api, residency.residency_id)) == 4

    schedule_residency(api, residency, LATER_START, 9)

    rows = obligations_for(api, residency.residency_id)
    assert len(rows) == 4
    assert all(row["due_date"] == LATER_END for row in rows)
    workshop = [row for row in rows if row["obligation_type"] == "COMMUNITY_WORKSHOP"]
    assert [row["required_count"] for row in workshop] == [2]


# Six studios that all differ on exactly one ranking key at a time, so the
# ordering can be read off the winner alone.
STUDIO_YARD = [
    {"code": "S-A", "capability_tags": ["WELDING", "KILN", "DARKROOM"]},
    {"code": "S-B", "capability_tags": ["WELDING", "KILN"], "ventilation_class": "FUME_HOOD"},
    {"code": "S-C", "capability_tags": ["WELDING", "KILN"]},
    {"code": "S-D", "capability_tags": ["WELDING", "KILN"]},
    {"code": "S-E", "capability_tags": ["PRINT_PRESS"]},
    {"code": "S-F", "capability_tags": ["WELDING"], "ventilation_class": "NONE"},
]


def _yard(api, specs):
    """Register the named studios and index them by their business code."""
    return {spec["code"]: create_studio(api, **spec) for spec in specs}


def _resident_needing_a_studio(api):
    """A scheduled eight-week resident whose discipline wants welding and local air."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    return residency


def _book(api, residency, studio=None, window=(SESSION_START, SESSION_END)):
    """The raw booking call, so a refusal can be inspected rather than raised."""
    current = refresh_residency(api, residency)
    payload = make_studio_assignment_payload(
        residency.residency_id,
        window[0],
        window[1],
        current["version"],
        studio.studio_id if studio else None,
    )
    return api.create_studio_assignment(payload, FACILITIES_HEADERS)


def test_the_selector_takes_the_least_over_provisioned_studio_that_will_do(api):
    """Four eligible studios, and the winner is the plainest one with the first code.

    PRD: "The ranking is ascending on every key in turn, which means the selector
    deliberately prefers the **least** over-provisioned studio that will do the
    job: first by ventilation rank ascending, so a `LOCAL` studio is preferred
    over a `FUME_HOOD` studio when `LOCAL` suffices; then by the number of entries
    in `capability_tags` ascending, so a narrowly equipped studio is preferred
    over a general-purpose one; then by `max_concurrent_residents` ascending, so a
    private studio is preferred over a shared one; and finally by `code`
    ascending as the deterministic tie-break."

    Design: Corner/calculations/studio_auto_selection_prefers_the_least_over_provisioned_then_breaks_ties_on_code
    """
    residency = _resident_needing_a_studio(api)
    yard = _yard(api, STUDIO_YARD)

    booking = assign_studio(api, residency, SESSION_START, SESSION_END)

    assert booking["selection_mode"] == "AUTO_SELECTED"
    assert booking["studio_id"] == yard["S-C"].studio_id
    assert booking["status"] == "ACTIVE"
    assert booking["occupied_days"] == 56
    assert read_residency(api, residency.residency_id)["assigned_studio_code"] == "S-C"


def test_only_the_chosen_studio_carries_the_day_ledger(api):
    """The three runners-up are untouched by a booking they did not win.

    PRD: "The studio also carries two server-maintained figures:
    `reserved_resident_days`, the sum of `occupied_days` across the studio's
    studio assignments in status `ACTIVE`, and `active_assignment_count`, the
    number of such assignments. Both start at 0."

    Design: Corner/calculations/studio_auto_selection_prefers_the_least_over_provisioned_then_breaks_ties_on_code
    """
    residency = _resident_needing_a_studio(api)
    yard = _yard(api, STUDIO_YARD)

    assign_studio(api, residency, SESSION_START, SESSION_END)

    assert_studio_day_ledger(refresh_studio(api, yard["S-C"]), 56, 1)
    for code in ("S-A", "S-B", "S-D"):
        assert_studio_day_ledger(refresh_studio(api, yard[code]), 0, 0)


def test_the_eligibility_filter_runs_before_the_ranking(api):
    """The narrowest studio of all is filtered out rather than ranked first.

    PRD: "First an eligibility filter retains every studio that satisfies all of
    the following: its `status` is `AVAILABLE`, so studios in `MAINTENANCE` or
    `DECOMMISSIONED` are never candidates; its `capability_tags` are a superset of
    the discipline's `required_capability_tags`; its ventilation rank is at least
    the discipline's required rank"

    Design: Corner/calculations/studio_auto_selection_prefers_the_least_over_provisioned_then_breaks_ties_on_code
    """
    residency = _resident_needing_a_studio(api)
    # S-E lacks welding altogether and S-F has the fewest tags of any studio but
    # ranks below LOCAL on air handling, so neither reaches the ranking stage.
    _yard(api, [STUDIO_YARD[4], STUDIO_YARD[5]])

    validate_error(_book(api, residency), ERR_NO_STUDIO_AVAILABLE)

    assert studio_assignments_for(api, residency.residency_id) == []
    assert read_residency(api, residency.residency_id)["assigned_studio_code"] is None


def test_the_code_tie_break_survives_a_reversed_registration_order(api):
    """Registering the later code first does not make it win.

    PRD: "That last key is an operator-assigned business key: the studio's `id`
    is never consulted, so when two studios tie on every other key the winner is
    fully predictable from their codes alone."

    Design: Corner/calculations/studio_auto_selection_prefers_the_least_over_provisioned_then_breaks_ties_on_code
    """
    residency = _resident_needing_a_studio(api)
    yard = _yard(api, [STUDIO_YARD[3], STUDIO_YARD[2]])
    assert yard["S-D"].studio["created_at"] <= yard["S-C"].studio["created_at"]

    booking = assign_studio(api, residency, SESSION_START, SESSION_END)

    assert booking["studio_id"] == yard["S-C"].studio_id
    assert booking["selection_mode"] == "AUTO_SELECTED"


def test_naming_a_studio_bypasses_the_ranking_altogether(api):
    """An eligible studio that would have lost the ranking may still be chosen.

    PRD: "When `studio_id` is omitted the server chooses the studio itself, and
    `selection_mode` on the created assignment is recorded as `AUTO_SELECTED`
    rather than `EXPLICIT`."

    Design: Corner/calculations/studio_auto_selection_prefers_the_least_over_provisioned_then_breaks_ties_on_code
    """
    residency = _resident_needing_a_studio(api)
    yard = _yard(api, STUDIO_YARD)

    booking = assign_studio(api, residency, SESSION_START, SESSION_END, yard["S-A"])

    assert booking["selection_mode"] == "EXPLICIT"
    assert booking["studio_id"] == yard["S-A"].studio_id
    assert read_residency(api, residency.residency_id)["assigned_studio_code"] == "S-A"
    assert_studio_day_ledger(refresh_studio(api, yard["S-C"]), 0, 0)


TWIN_STUDIOS = [STUDIO_YARD[2], STUDIO_YARD[3]]


def _patch_studio(api, studio, **changes):
    """Revise a studio in place, the way a facilities manager would."""
    return get_success_data(api.update_studio(studio.studio_id, changes, FACILITIES_HEADERS))


def _twins_with_the_first_withdrawn(api):
    """Two interchangeable studios, the alphabetically earlier one out of service."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    yard = _yard(api, TWIN_STUDIOS)
    withdrawn = _patch_studio(api, yard["S-C"], status="MAINTENANCE")
    assert withdrawn["status"] == "MAINTENANCE"
    return cycle, residency, yard


def test_a_studio_out_of_service_never_enters_the_candidate_set(api):
    """The tie-break winner loses on status before the codes are ever compared.

    PRD: "its `status` is `AVAILABLE`, so studios in `MAINTENANCE` or
    `DECOMMISSIONED` are never candidates"

    Design: Corner/calculations/studio_selector_ignores_unavailable_studios_and_released_assignments
    """
    _cycle, residency, yard = _twins_with_the_first_withdrawn(api)

    booking = assign_studio(api, residency, SESSION_START, SESSION_END)

    assert booking["selection_mode"] == "AUTO_SELECTED"
    assert booking["studio_id"] == yard["S-D"].studio_id
    assert read_residency(api, residency.residency_id)["assigned_studio_code"] == "S-D"
    assert_studio_day_ledger(refresh_studio(api, yard["S-C"]), 0, 0)


def test_naming_the_unavailable_studio_is_a_different_refusal(api):
    """Asking for the closed studio by name is answered on the studio, not the set.

    PRD: "When a `studio_id` was named explicitly, that studio's `status` must be
    `AVAILABLE`; a studio in `MAINTENANCE` or `DECOMMISSIONED` is
    `ERR_FACILITY_UNAVAILABLE` (HTTP 409)."

    Design: Corner/calculations/studio_selector_ignores_unavailable_studios_and_released_assignments
    """
    _cycle, residency, yard = _twins_with_the_first_withdrawn(api)

    validate_error(_book(api, residency, yard["S-C"]), ERR_FACILITY_UNAVAILABLE)

    assert studio_assignments_for(api, residency.residency_id) == []


def test_decommissioned_and_maintenance_are_filtered_identically(api):
    """With both studios out of service the candidate set is empty and nothing is written.

    PRD: "If the eligibility filter retains nothing, the request is rejected with
    `ERR_NO_STUDIO_AVAILABLE` (HTTP 409)."

    Design: Corner/calculations/studio_selector_ignores_unavailable_studios_and_released_assignments
    """
    _cycle, residency, yard = _twins_with_the_first_withdrawn(api)
    _patch_studio(api, yard["S-C"], status="DECOMMISSIONED")
    _patch_studio(api, yard["S-D"], status="MAINTENANCE")

    validate_error(_book(api, residency), ERR_NO_STUDIO_AVAILABLE)

    assert studio_assignments_for(api, residency.residency_id) == []
    assert read_residency(api, residency.residency_id)["assigned_studio_code"] is None


def test_a_studio_already_booked_for_the_window_drops_out_too(api):
    """Restoring the first studio and occupying the second reverses the winner.

    PRD: "and it has room for the requested window under whichever of the two
    occupancy rules its own `max_concurrent_residents` selects — the buffered
    closed-interval rule for a single-occupancy studio, the aggregate headcount
    rule for a shared one."

    Design: Corner/calculations/studio_selector_ignores_unavailable_studios_and_released_assignments
    """
    cycle, residency, yard = _twins_with_the_first_withdrawn(api)
    first = assign_studio(api, residency, SESSION_START, SESSION_END)
    assert first["studio_id"] == yard["S-D"].studio_id
    _patch_studio(api, yard["S-C"], status="AVAILABLE")

    latecomer = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, latecomer, SESSION_START, 8)
    second = assign_studio(api, latecomer, SESSION_START, SESSION_END)

    assert second["studio_id"] == yard["S-C"].studio_id
    assert second["selection_mode"] == "AUTO_SELECTED"
    assert_studio_day_ledger(refresh_studio(api, yard["S-C"]), 56, 1)
    assert_studio_day_ledger(refresh_studio(api, yard["S-D"]), 56, 1)


def test_a_released_row_frees_its_window_for_the_selector_at_once(api):
    """The identical window is auto-selectable again on the studio that just let it go.

    PRD: "Only assignments in `ACTIVE` occupy a studio; a `RELEASED` assignment
    frees its window immediately, buffer included."

    Design: Corner/calculations/studio_selector_ignores_unavailable_studios_and_released_assignments
    """
    _cycle, residency, yard = _twins_with_the_first_withdrawn(api)
    first = assign_studio(api, residency, SESSION_START, SESSION_END)
    assert_studio_day_ledger(refresh_studio(api, yard["S-D"]), 56, 1)

    release_studio_assignment(api, first["id"], "resident deferred a fortnight")
    assert_studio_day_ledger(refresh_studio(api, yard["S-D"]), 0, 0)
    rebooked = assign_studio(api, residency, SESSION_START, SESSION_END)

    assert rebooked["studio_id"] == yard["S-D"].studio_id
    assert rebooked["selection_mode"] == "AUTO_SELECTED"
    assert rebooked["occupied_days"] == 56
    assert_studio_day_ledger(refresh_studio(api, yard["S-D"]), 56, 1)
