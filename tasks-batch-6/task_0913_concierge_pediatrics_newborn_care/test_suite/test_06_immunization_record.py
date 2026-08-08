"""The immunization record: the validity ladder and retrospective invalidation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_immunization_dose,
    assert_instant_equals,
    complete_well_visit,
    create_child,
    create_family,
    create_immunization_dose_payload,
    get_child,
    get_dose,
    get_form_request,
    record_dose,
    request_form,
    set_clock,
    setup_active_membership,
    validate_error,
    validate_paginated,
    validate_success,
    well_visit_for,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _child_with_two_hepb_doses(clock, household_name, child_name):
    set_clock(clock)
    family = create_family(household_name=household_name)
    child = create_child(family["id"], first_name=child_name, date_of_birth="2026-04-01")
    d1 = record_dose(child["id"], "HEPB", "2026-04-02")
    d2 = record_dose(child["id"], "HEPB", "2026-04-29")
    return family, child, d1, d2


# ==========================================================================
# The two rungs of the validity ladder
# ==========================================================================


def test_third_hepb_dose_fails_only_the_age_rung(api):
    """PRD §3.5: "Otherwise the **age rung** is tested first: the practice allows a
    four-day grace, so the dose passes when its `age_days_at_administration` plus four is
    greater than or equal to the position's minimum age."
    PRD §3.5: "An age failure means the child is simply too young and the fix is to wait —
    for a child born 2026-04-01, a third `HEPB` dose administered 2026-09-11 sits at 163
    days of age, and 163 plus the four-day grace is 167, short of the 168-day minimum, so
    the dose is invalid for age even though the interval since the second dose is
    enormous."

    Design: Difficulty/dual_variant_calc/immunization_validity_age_rung_vs_interval_rung
    """
    _, child, d1, d2 = _child_with_two_hepb_doses("2026-09-12T00:00:00Z", "Okafor", "Noah")

    first, second = get_dose(d1["id"]), get_dose(d2["id"])
    assert first["validity"] == "VALID" and first["effective_series_index"] == 1
    assert second["validity"] == "VALID" and second["effective_series_index"] == 2
    assert second["interval_days_since_prior"] == 27

    third = record_dose(child["id"], "HEPB", "2026-09-11")
    assert_immunization_dose(third)

    assert third["validity"] == "INVALID"
    assert third["invalid_reason"] == "MIN_AGE_NOT_MET"
    assert third["age_days_at_administration"] == 163
    assert third["effective_series_index"] == 3
    assert third["interval_days_since_prior"] == 135
    assert third["prior_valid_dose_id"] == d2["id"]


def test_second_dtap_dose_clears_the_age_rung_but_fails_the_interval_rung(api):
    """PRD §3.5: "Only if the age rung passes is the **interval rung** tested, and it is
    skipped entirely at effective position 1. The same four-day grace applies: the dose
    passes when its `interval_days_since_prior` plus four is greater than or equal to the
    position's minimum interval. A failure here is `INVALID` with `invalid_reason`
    `MIN_INTERVAL_NOT_MET`."
    PRD §3.5: "for the same birth date, a first `DTAP` dose on 2026-05-26 sits at 55 days
    and is valid, while a second on 2026-06-18 gives an interval of 23 days, and 23 plus
    the grace is 27, short of the 28-day minimum, so it is invalid for interval even
    though its age of 78 days clears the 70-day age floor comfortably."

    Design: Difficulty/dual_variant_calc/immunization_validity_age_rung_vs_interval_rung
    """
    _, child, _, _ = _child_with_two_hepb_doses("2026-09-12T00:00:00Z", "Okafor", "Noah")

    dtap1 = record_dose(child["id"], "DTAP", "2026-05-26")
    assert dtap1["validity"] == "VALID"
    assert dtap1["age_days_at_administration"] == 55

    dtap2 = record_dose(child["id"], "DTAP", "2026-06-18")
    assert_immunization_dose(dtap2)

    assert dtap2["validity"] == "INVALID"
    assert dtap2["invalid_reason"] == "MIN_INTERVAL_NOT_MET"
    assert dtap2["age_days_at_administration"] == 78
    assert dtap2["effective_series_index"] == 2
    assert dtap2["interval_days_since_prior"] == 23


def test_four_day_grace_is_inclusive_at_its_edge(api):
    """PRD §3.5: "A dose given exactly four days early therefore passes and one given five
    days early fails."
    PRD §3.5: "A dose's `effective_series_index` is one plus the number of that child's
    doses of the same `vaccine_code` currently carrying `validity` `VALID` whose
    `administered_date` is strictly earlier than this dose's, or equal to it with a
    strictly earlier `created_at`."

    Design: Corner/calculations/corner_immunization_grace_window_exactly_four_days_is_valid
    """
    _, child, _, d2 = _child_with_two_hepb_doses("2026-09-13T00:00:00Z", "Aarons", "Rex")

    too_early = record_dose(child["id"], "HEPB", "2026-09-11")
    assert too_early["age_days_at_administration"] == 163
    assert too_early["validity"] == "INVALID"
    assert too_early["invalid_reason"] == "MIN_AGE_NOT_MET"

    just_in_time = record_dose(child["id"], "HEPB", "2026-09-12")
    assert just_in_time["age_days_at_administration"] == 164
    assert just_in_time["validity"] == "VALID"
    assert just_in_time["invalid_reason"] is None
    assert just_in_time["effective_series_index"] == 3, (
        "the invalid dose does not sit in the valid series and so does not advance it"
    )
    assert just_in_time["prior_valid_dose_id"] == d2["id"]
    assert just_in_time["interval_days_since_prior"] == 136

    valid_rows, meta = validate_paginated(
        api.list_immunization_doses(
            ADMIN, params={"child_id": child["id"], "validity": "VALID"}
        )
    )
    assert meta["total_count"] == 3 and len(valid_rows) == 3


def test_a_dose_failing_both_rungs_reports_the_age_reason(api):
    """PRD §3.5: "**The rung order is pinned**: when a dose fails both rungs, the reported
    reason is always `MIN_AGE_NOT_MET` and never `MIN_INTERVAL_NOT_MET`."
    PRD §3.5: "`DTAP` runs to five doses: position 1 at minimum age 42 days with no
    interval requirement; position 2 at minimum age 70 days with a 28-day interval"

    Design: Corner/calculations/corner_immunization_both_rungs_failing_reports_min_age_not_met
    """
    set_clock("2026-05-20T00:00:00Z")
    family = create_family(household_name="Bergen")
    child = create_child(family["id"], first_name="Isa", date_of_birth="2026-04-01")

    first = record_dose(child["id"], "DTAP", "2026-05-13")
    assert first["validity"] == "VALID"
    assert first["age_days_at_administration"] == 42
    assert first["effective_series_index"] == 1

    second = record_dose(child["id"], "DTAP", "2026-05-17")
    assert second["validity"] == "INVALID"
    assert second["invalid_reason"] == "MIN_AGE_NOT_MET"
    assert second["invalid_reason"] != "MIN_INTERVAL_NOT_MET"
    assert second["age_days_at_administration"] == 46
    assert second["interval_days_since_prior"] == 4
    assert second["effective_series_index"] == 2


def test_recording_a_dose_dated_after_today_is_refused(api):
    """PRD §3.5: "A `Physician` or `PracticeAdmin` records an administered dose by naming
    the `child_id`, a `vaccine_code` of either `HEPB` or `DTAP`, and the
    `administered_date`, which may not be after today."
    PRD §2.7: "Clinically dated fields may not lie in the future: `date_of_birth` on child
    creation, `administered_date` on dose creation and `completed_date` on well-visit
    completion may not be after today, and `started_at` on encounter creation may not be
    after the current instant — otherwise `ERR_FUTURE_DATED` (422)."

    Design: Corner/validations/corner_record_dose_dated_in_the_future_returns_future_dated
    """
    set_clock("2026-06-01T00:00:00Z")
    family = create_family(household_name="Halloran")
    child = create_child(family["id"], first_name="Fia", date_of_birth="2026-01-01")

    resp = api.create_immunization_dose(
        create_immunization_dose_payload(child["id"], "HEPB", "2026-06-02"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_FUTURE_DATED)
    assert resp.status_code == 422

    rows, meta = validate_paginated(
        api.list_immunization_doses(ADMIN, params={"child_id": child["id"]})
    )
    assert meta["total_count"] == 0 and rows == []

    on_the_bound = record_dose(child["id"], "HEPB", "2026-06-01")
    assert on_the_bound["age_days_at_administration"] == 151, (
        "a dose dated exactly today is accepted; the bound is inclusive"
    )


def test_doses_are_reverse_reachable_through_prior_valid_dose_id(api):
    """PRD §2.3: "Immunization doses filter on `child_id`, `vaccine_code`, `validity` and
    `prior_valid_dose_id`."
    PRD §3.5: "Its `prior_valid_dose_id` names the valid dose of the same child and
    vaccine whose `administered_date` is the greatest value strictly less than this
    dose's, with ties on the date broken by taking the later `created_at`; that field is
    null when the dose sits at effective position 1."

    Design: Corner/endpoints/corner_immunization_doses_filter_by_prior_valid_dose_id
    """
    _, child, d1, d2 = _child_with_two_hepb_doses("2026-05-05T00:00:00Z", "Tudor", "Cass")

    rows, meta = validate_paginated(
        api.list_immunization_doses(ADMIN, params={"prior_valid_dose_id": d1["id"]})
    )
    assert meta["total_count"] == 1 and len(rows) == 1
    assert rows[0]["id"] == d2["id"]

    tail_rows, tail_meta = validate_paginated(
        api.list_immunization_doses(ADMIN, params={"prior_valid_dose_id": d2["id"]})
    )
    assert tail_meta["total_count"] == 0 and tail_rows == []

    first, second = get_dose(d1["id"]), get_dose(d2["id"])
    assert first["prior_valid_dose_id"] is None
    assert first["effective_series_index"] == 1
    assert second["prior_valid_dose_id"] == d1["id"]
    assert second["effective_series_index"] == 2
    assert second["interval_days_since_prior"] == 27


# ==========================================================================
# Retrospective invalidation and its cascade
# ==========================================================================


def _blocked_form_cascade_scenario():
    """Two valid HEPB doses, a completed M2 visit, and a PENDING form request."""
    scenario = setup_active_membership(
        clock="2026-05-24T09:00:00Z",
        household_name="Lindqvist",
        child_first_name="Eli",
        date_of_birth="2026-04-01",
        start_date="2026-05-24",
    )
    child = scenario["child"]
    scenario["d1"] = record_dose(child["id"], "HEPB", "2026-04-02")
    scenario["d2"] = record_dose(child["id"], "HEPB", "2026-04-29")

    m2 = well_visit_for(scenario["membership"]["id"], "M2")
    completed = complete_well_visit(m2["id"], scenario["physician"]["id"], "2026-05-24")
    assert completed["punctuality"] == "ON_SCHEDULE"

    set_clock("2026-05-29T09:00:00Z")
    scenario["form"] = request_form(
        scenario["membership"]["id"], form_type="SCHOOL", needed_by_date="2026-08-15"
    )
    return scenario


def test_invalidating_a_dose_reshuffles_the_rest_of_the_series(api):
    """PRD §3.5: "The dose's `validity` becomes `INVALID`, its `invalid_reason` becomes
    `MANUALLY_INVALIDATED`, and its `manually_invalidated` flag is set to true — a flag
    that is permanent, because a manually invalidated dose can never return to `VALID` no
    matter what happens to the series around it."
    PRD §3.5: "First, because the dose has left the valid set, every dose of the same
    child and the same `vaccine_code` with a strictly later `administered_date` is
    re-evaluated in `administered_date` ascending then `created_at` ascending order,
    recomputing each one's `effective_series_index`, `prior_valid_dose_id`,
    `interval_days_since_prior`, `validity` and `invalid_reason` from scratch."

    Design: Difficulty/transitive_cascade/dose_invalidation_shifts_series_and_blocks_pending_form_request
    """
    scenario = _blocked_form_cascade_scenario()

    invalidated = validate_success(
        api.invalidate_immunization_dose(
            scenario["d1"]["id"], {"reason": "Cold-chain excursion at the depot"}, ADMIN
        )
    )
    assert invalidated["validity"] == "INVALID"
    assert invalidated["invalid_reason"] == "MANUALLY_INVALIDATED"
    assert invalidated["manually_invalidated"] is True

    shifted = get_dose(scenario["d2"]["id"])
    assert shifted["validity"] == "VALID"
    assert shifted["effective_series_index"] == 1, "removing dose 1 moved dose 2 down a rung"
    assert shifted["prior_valid_dose_id"] is None
    assert shifted["interval_days_since_prior"] is None


def test_invalidating_a_dose_blocks_the_pending_form_request(api):
    """PRD §3.5: "Third, because that flag may have gone false, every form request of that
    child still in `PENDING` transitions `PENDING → BLOCKED` with `blocked_reason` set to
    `IMMUNIZATION_INCOMPLETE`; form requests already `ISSUED` are not touched, and no
    already-issued form is ever revoked."
    PRD §3.9: "The service stamps `requested_at` with the current instant and computes
    `due_at` once, as `requested_at` plus the plan's `form_sla_hours` — five days on
    `ESSENTIAL`, three on `PLUS`, one on `PREMIER` — and never recomputes it afterwards,
    so a mid-flight plan change does not move a promise already made."

    Design: Difficulty/transitive_cascade/dose_invalidation_shifts_series_and_blocks_pending_form_request
    """
    scenario = _blocked_form_cascade_scenario()
    form, child = scenario["form"], scenario["child"]

    assert form["status"] == "PENDING"
    assert form["blocked_reason"] is None
    assert_instant_equals(form["due_at"], "2026-06-01T09:00:00.000Z", "FormRequest.due_at")

    validate_success(
        api.invalidate_immunization_dose(
            scenario["d1"]["id"], {"reason": "Cold-chain excursion at the depot"}, ADMIN
        )
    )

    assert get_child(child["id"])["immunization_complete_for_age"] is False

    blocked = get_form_request(form["id"])
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "IMMUNIZATION_INCOMPLETE"
    assert blocked["issued_at"] is None
    assert blocked["sla_met"] is None
