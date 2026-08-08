"""Round-the-clock access: encounters, the after-hours verdict and two axes."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_encounter,
    assert_instant_equals,
    by_field,
    complete_clinical,
    create_encounter_payload,
    get_encounter,
    open_encounter,
    premier_plan_payload,
    service_lines_for_encounter,
    setup_active_membership,
    submit_billing,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def _active_membership_mid_june(**kwargs):
    kwargs.setdefault("clock", "2026-06-01T00:00:00Z")
    kwargs.setdefault("advance_clock_to", "2026-06-15T20:00:00Z")
    return setup_active_membership(**kwargs)


# ==========================================================================
# The two independent axes
# ==========================================================================


def test_billing_axis_closes_while_the_clinical_axis_is_still_scheduled(api):
    """PRD §3.6: "A newly opened encounter carries `clinical_status` `SCHEDULED` and
    `billing_status` `BILLING_PENDING`, with `clinical_note` and `cancel_reason` both
    null."
    PRD §3.6: "It fires inside the submission itself when every line created was born
    `SETTLED` — a membership-covered or patient-responsibility encounter therefore reads
    `BILLING_CLOSED` in the very response of the submission that routed it."
    PRD §3.6: "a `ROUTINE_QUESTION` maps to `TELEHEALTH_VISIT`"

    Design: Difficulty/non_linear_state_machine/encounter_billing_axis_closes_while_clinical_axis_still_scheduled
    """
    scenario = _active_membership_mid_june(household_name="Castro", child_first_name="Lena")

    encounter = open_encounter(
        scenario["membership"]["id"],
        "2026-06-15T10:00:00Z",
        encounter_type="ROUTINE_QUESTION",
        modality="TELEHEALTH",
    )
    assert_encounter(encounter)
    assert encounter["clinical_status"] == "SCHEDULED"
    assert encounter["billing_status"] == "BILLING_PENDING"
    assert encounter["clinical_note"] is None
    assert encounter["cancel_reason"] is None

    submitted = validate_success(api.submit_encounter_billing(encounter["id"], BILLING))
    assert submitted["clinical_status"] == "SCHEDULED", "the billing call never reads the chart"
    assert submitted["billing_status"] == "BILLING_CLOSED"

    lines = service_lines_for_encounter(encounter["id"])
    assert len(lines) == 1
    line = lines[0]
    assert line["service_code"] == "TELEHEALTH_VISIT"
    assert line["route"] == "COVERED_BY_MEMBERSHIP"
    assert line["billed_amount_cents"] == 12000
    assert line["membership_covered_cents"] == 12000
    assert line["status"] == "SETTLED"


def test_clinical_completion_leaves_a_closed_billing_axis_untouched(api):
    """PRD §3.6: "On the clinical axis, a `Physician` or `PracticeAdmin` completes the
    encounter by supplying a `clinical_note`, moving it `SCHEDULED → CLINICALLY_COMPLETE`.
    The `billing_status` is neither read nor changed by this call — the billing axis may
    already read `BILLING_ROUTED` or may still read `BILLING_PENDING`, and both are
    perfectly legal."

    Design: Difficulty/non_linear_state_machine/encounter_billing_axis_closes_while_clinical_axis_still_scheduled
    """
    scenario = _active_membership_mid_june(household_name="Castro", child_first_name="Lena")

    encounter = open_encounter(
        scenario["membership"]["id"],
        "2026-06-15T10:00:00Z",
        encounter_type="ROUTINE_QUESTION",
        modality="TELEHEALTH",
    )
    submit_billing(encounter["id"], "bs-021")

    completed = validate_success(
        api.complete_clinical_encounter(
            encounter["id"],
            {"clinical_note": "Reassurance given, no red flags"},
            scenario["physician_headers"],
        )
    )
    assert completed["clinical_status"] == "CLINICALLY_COMPLETE"
    assert completed["billing_status"] == "BILLING_CLOSED"
    assert completed["clinical_note"] == "Reassurance given, no red flags"


def test_completing_the_clinical_axis_twice_is_refused(api):
    """PRD §3.6: "On the clinical axis, a `Physician` or `PracticeAdmin` completes the
    encounter by supplying a `clinical_note`, moving it `SCHEDULED → CLINICALLY_COMPLETE`."
    PRD §2.7: "The target row's current state must permit the requested transition,
    including refusal of every transition attempted out of a terminal state — otherwise
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/corner_complete_clinical_twice_returns_invalid_state
    """
    scenario = _active_membership_mid_june(household_name="Haddad", child_first_name="Sami")

    encounter = open_encounter(scenario["membership"]["id"], "2026-06-15T10:00:00Z")
    complete_clinical(encounter["id"], scenario["physician"]["id"], "First note")

    resp = api.complete_clinical_encounter(
        encounter["id"], {"clinical_note": "Second note"}, scenario["physician_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    row = get_encounter(encounter["id"])
    assert row["clinical_note"] == "First note"
    assert row["clinical_status"] == "CLINICALLY_COMPLETE"
    assert row["billing_status"] == "BILLING_PENDING"


# ==========================================================================
# Safety gates and the closed-interval collision test
# ==========================================================================


def test_licensure_is_reported_before_the_encounter_overlap(api):
    """PRD §3.6: "Two safety gates apply and their relative order matters. Licensure is
    checked first: when `modality` is `TELEHEALTH`, the `patient_state_code` must appear
    in the `licensed_state_codes` of the physician the membership names, and if it does
    not the request is refused with `ERR_LICENSURE_NOT_COVERED`."
    PRD §2.7: "Rules are evaluated in a strict ascending order and the **first** rule that
    fails determines the response."

    Design: Difficulty/priority_pair_validation_conflict/telehealth_licensure_outranks_encounter_overlap
    """
    scenario = _active_membership_mid_june(household_name="Osei", child_first_name="Kofi")
    open_encounter(scenario["membership"]["id"], "2026-06-15T14:00:00Z")

    resp = api.create_encounter(
        create_encounter_payload(
            scenario["membership"]["id"],
            "2026-06-15T14:15:00Z",
            encounter_type="SICK_VISIT",
            modality="TELEHEALTH",
            patient_state_code="TX",
        ),
        COORDINATOR,
    )
    error = validate_error(resp, ApiErrorId.ERR_LICENSURE_NOT_COVERED)
    assert resp.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_ENCOUNTER_OVERLAP.value


def test_the_rejected_out_of_state_contact_writes_nothing(api):
    """PRD §2.7: "No later rule runs and no partial mutation is persisted."
    PRD §3.6: "A newly opened encounter carries `clinical_status` `SCHEDULED` and
    `billing_status` `BILLING_PENDING`, with `clinical_note` and `cancel_reason` both
    null."

    Design: Difficulty/priority_pair_validation_conflict/telehealth_licensure_outranks_encounter_overlap
    """
    scenario = _active_membership_mid_june(household_name="Osei", child_first_name="Kofi")
    first = open_encounter(scenario["membership"]["id"], "2026-06-15T14:00:00Z")

    validate_error(
        api.create_encounter(
            create_encounter_payload(
                scenario["membership"]["id"],
                "2026-06-15T14:15:00Z",
                encounter_type="SICK_VISIT",
                modality="TELEHEALTH",
                patient_state_code="TX",
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_LICENSURE_NOT_COVERED,
    )

    rows, meta = validate_paginated(
        api.list_encounters(COORDINATOR, params={"membership_id": scenario["membership"]["id"]})
    )
    assert meta["total_count"] == 1 and len(rows) == 1

    unchanged = get_encounter(first["id"])
    assert unchanged["clinical_status"] == "SCHEDULED"
    assert unchanged["billing_status"] == "BILLING_PENDING"


def test_touching_encounter_endpoints_collide_on_the_same_child(api):
    """PRD §3.6: "The service then derives `ends_at` as the `started_at` plus thirty
    minutes and applies a **closed-interval collision test** on the child."
    PRD §3.6: "Because both intervals are closed, touching endpoints **do** collide — a
    contact beginning exactly thirty minutes after another began is a collision, not a
    clean handoff. A collision is refused with `ERR_ENCOUNTER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/encounter_closed_interval_touching_endpoints_collide_on_child
    """
    scenario = _active_membership_mid_june(household_name="Vargas", child_first_name="Nico")

    first = open_encounter(scenario["membership"]["id"], "2026-06-15T14:00:00Z")
    assert_instant_equals(first["ends_at"], "2026-06-15T14:30:00.000Z", "Encounter.ends_at")

    resp = api.create_encounter(
        create_encounter_payload(scenario["membership"]["id"], "2026-06-15T14:30:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ENCOUNTER_OVERLAP)
    assert resp.status_code == 409


def test_a_contact_one_minute_past_the_closed_interval_is_accepted(api):
    """PRD §3.6: "The new encounter's interval runs from `started_at` through `ends_at`
    with **both endpoints included**, and it is compared against the same closed interval
    of every other encounter for that same child whose `clinical_status` is currently
    `SCHEDULED`; encounters in any other clinical status are invisible to the test."
    PRD §3.6: "so a contact at 2026-06-15T14:00:00Z, a Monday, is not after-hours and
    carries `surcharge_cents` 0."

    Design: Difficulty/resource_temporal_overlap/encounter_closed_interval_touching_endpoints_collide_on_child
    """
    scenario = _active_membership_mid_june(household_name="Vargas", child_first_name="Nico")

    first = open_encounter(scenario["membership"]["id"], "2026-06-15T14:00:00Z")

    second = validate_success(
        api.create_encounter(
            create_encounter_payload(scenario["membership"]["id"], "2026-06-15T14:31:00Z"),
            COORDINATOR,
        ),
        201,
    )
    assert_instant_equals(second["ends_at"], "2026-06-15T15:01:00.000Z", "Encounter.ends_at")

    rows, meta = validate_paginated(
        api.list_encounters(COORDINATOR, params={"child_id": scenario["child"]["id"]})
    )
    assert meta["total_count"] == 2 and len(rows) == 2

    assert first["after_hours"] is False
    assert first["surcharge_cents"] == 0


def test_newborn_weight_check_may_not_be_delivered_over_video(api):
    """PRD §3.6: "Modality suitability is checked second: a `NEWBORN_WEIGHT_CHECK` requires
    a physical scale and may never be delivered over video regardless of licensure, so
    pairing that `encounter_type` with `TELEHEALTH` is refused with
    `ERR_MODALITY_NOT_ALLOWED`."

    Design: Corner/validations/corner_newborn_weight_check_by_telehealth_returns_modality_not_allowed
    """
    scenario = _active_membership_mid_june(
        household_name="Imani", child_first_name="Zuri", date_of_birth="2026-05-20"
    )

    resp = api.create_encounter(
        create_encounter_payload(
            scenario["membership"]["id"],
            "2026-06-15T10:00:00Z",
            encounter_type="NEWBORN_WEIGHT_CHECK",
            modality="TELEHEALTH",
            patient_state_code="CA",
        ),
        COORDINATOR,
    )
    error = validate_error(resp, ApiErrorId.ERR_MODALITY_NOT_ALLOWED)
    assert resp.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_LICENSURE_NOT_COVERED.value

    _, meta = validate_paginated(
        api.list_encounters(COORDINATOR, params={"membership_id": scenario["membership"]["id"]})
    )
    assert meta["total_count"] == 0


# ==========================================================================
# The after-hours verdict
# ==========================================================================


def test_after_hours_weekday_window_boundaries_are_exact(api):
    """PRD §3.6: "Both evening and morning boundaries are exact: a contact starting at
    18:00:00 **is** after-hours while one starting at 17:59:00 is not, and one starting at
    07:59:00 **is** after-hours while one starting at 08:00:00 is not."
    PRD §3.6: "The `surcharge_cents` figure itself is 0 whenever `after_hours` is false or
    the membership's plan sets `after_hours_surcharge_waived` to true, and 7 500
    otherwise."

    Design: Corner/calculations/corner_after_hours_weekday_window_boundaries
    """
    scenario = _active_membership_mid_june(
        household_name="Wexler",
        child_first_name="Tovi",
        advance_clock_to="2026-06-16T23:00:00Z",
    )
    membership_id = scenario["membership"]["id"]
    doc_id = scenario["physician"]["id"]

    before_evening = open_encounter(
        membership_id, "2026-06-15T17:59:00Z", encounter_type="AFTER_HOURS_CONTACT"
    )
    assert before_evening["after_hours"] is False
    assert before_evening["after_hours_reason"] is None
    assert before_evening["surcharge_cents"] == 0
    complete_clinical(before_evening["id"], doc_id, "Pre-evening call")

    at_evening = open_encounter(
        membership_id, "2026-06-15T18:00:00Z", encounter_type="AFTER_HOURS_CONTACT"
    )
    assert at_evening["after_hours"] is True
    assert at_evening["after_hours_reason"] == "WEEKDAY_EVENING"
    assert at_evening["surcharge_cents"] == 7500
    complete_clinical(at_evening["id"], doc_id, "Evening call")

    before_morning = open_encounter(
        membership_id, "2026-06-16T07:59:00Z", encounter_type="AFTER_HOURS_CONTACT"
    )
    assert before_morning["after_hours"] is True
    assert before_morning["after_hours_reason"] == "WEEKDAY_EARLY_MORNING"
    assert before_morning["surcharge_cents"] == 7500
    complete_clinical(before_morning["id"], doc_id, "Dawn call")

    at_morning = open_encounter(
        membership_id, "2026-06-16T08:00:00Z", encounter_type="AFTER_HOURS_CONTACT"
    )
    assert at_morning["after_hours"] is False
    assert at_morning["after_hours_reason"] is None
    assert at_morning["surcharge_cents"] == 0


def test_weekend_and_declared_holiday_are_after_hours_all_day(api):
    """PRD §3.6: "If the weekday of that date is `SATURDAY` or `SUNDAY`, `after_hours` is
    true and `after_hours_reason` is `WEEKEND`. Otherwise, if the date is one of the
    practice's declared holidays — 2026-05-25, 2026-07-03, 2026-09-07, 2026-11-26,
    2026-12-25 and 2027-01-01 — `after_hours` is true and the reason is `HOLIDAY`."
    PRD §3.6: "On a Saturday, a Sunday or a declared holiday the minute of day is never
    consulted at all and the entire calendar day is after-hours"

    Design: Corner/calculations/corner_after_hours_full_day_on_weekend_and_declared_holiday
    """
    scenario = _active_membership_mid_june(
        household_name="Xavier",
        child_first_name="Kai",
        advance_clock_to="2026-07-03T20:00:00Z",
    )
    membership_id = scenario["membership"]["id"]

    saturday = open_encounter(
        membership_id, "2026-06-20T14:00:00Z", encounter_type="AFTER_HOURS_CONTACT"
    )
    assert saturday["after_hours"] is True
    assert saturday["after_hours_reason"] == "WEEKEND"
    assert saturday["surcharge_cents"] == 7500
    complete_clinical(saturday["id"], scenario["physician"]["id"], "Weekend call")

    holiday = open_encounter(
        membership_id, "2026-07-03T14:00:00Z", encounter_type="AFTER_HOURS_CONTACT"
    )
    assert holiday["after_hours"] is True
    assert holiday["after_hours_reason"] == "HOLIDAY", (
        "2026-07-03 is a Friday, so only the declared-holiday rung can explain the verdict"
    )
    assert holiday["surcharge_cents"] == 7500


def test_premier_tier_waives_the_after_hours_surcharge_to_the_membership_route(api):
    """PRD §3.6: "When the encounter's `after_hours` flag is true, a **second** line with
    `service_code` `AFTER_HOURS_SURCHARGE` is created alongside the primary one: routed
    `COVERED_BY_MEMBERSHIP` with `billed_amount_cents` 0 when the plan's
    `after_hours_surcharge_waived` is true, and routed `PATIENT_RESPONSIBILITY` with
    `billed_amount_cents` 7 500 when it is not."
    PRD §3.7: "If the set is empty — the household never had a policy, or the only one it
    had has been terminated — the line falls back to `PATIENT_RESPONSIBILITY` with
    `policy_id` null."

    Design: Corner/calculations/corner_premier_tier_waives_after_hours_surcharge_to_membership_route
    """
    scenario = setup_active_membership(
        clock="2026-06-01T00:00:00Z",
        plan=premier_plan_payload(),
        household_name="Yeung",
        child_first_name="Jun",
        family_monthly_cap_cents=200000,
        advance_clock_to="2026-06-15T23:00:00Z",
    )

    encounter = open_encounter(
        scenario["membership"]["id"],
        "2026-06-15T18:00:00Z",
        encounter_type="AFTER_HOURS_CONTACT",
    )
    assert encounter["after_hours"] is True
    assert encounter["after_hours_reason"] == "WEEKDAY_EVENING"
    assert encounter["surcharge_cents"] == 0, "the PREMIER tier waives the surcharge"

    submitted = validate_success(api.submit_encounter_billing(encounter["id"], BILLING))

    lines = service_lines_for_encounter(encounter["id"])
    assert len(lines) == 2

    primary = by_field(lines, "service_code", "SICK_VISIT")
    assert primary["route"] == "PATIENT_RESPONSIBILITY"
    assert primary["billed_amount_cents"] == 18000
    assert primary["patient_responsibility_cents"] == 18000
    assert primary["policy_id"] is None

    surcharge = by_field(lines, "service_code", "AFTER_HOURS_SURCHARGE")
    assert surcharge["route"] == "COVERED_BY_MEMBERSHIP"
    assert surcharge["billed_amount_cents"] == 0
    assert surcharge["patient_responsibility_cents"] == 0
    assert surcharge["membership_covered_cents"] == 0

    assert all(line["status"] == "SETTLED" for line in lines)
    assert submitted["billing_status"] == "BILLING_CLOSED"
    assert scenario["invoice"]["total_cents"] == 60000


def test_service_lines_filter_by_route_returns_only_that_route(api):
    """PRD §2.3: "Service lines filter on `encounter_id`, `consult_booking_id`,
    `well_visit_id`, `membership_id`, `policy_id`, `route` and `status`."
    PRD §3.6: "a `SICK_VISIT` encounter and an `AFTER_HOURS_CONTACT` encounter both map
    to service code `SICK_VISIT`"
    PRD §3.7: "This is the shape taken by an after-hours surcharge on a non-waiving tier,
    an overage consult, and a sick visit for a household with no active policy."

    Design: Corner/endpoints/corner_service_lines_filter_by_route_returns_only_that_route
    """
    scenario = _active_membership_mid_june(
        household_name="Sandoval",
        child_first_name="Nael",
        advance_clock_to="2026-06-15T23:00:00Z",
    )
    membership_id = scenario["membership"]["id"]

    encounter = open_encounter(
        membership_id, "2026-06-15T18:00:00Z", encounter_type="AFTER_HOURS_CONTACT"
    )
    submit_billing(encounter["id"], "bs-101")

    patient_rows, patient_meta = validate_paginated(
        api.list_service_lines(
            BILLING, params={"membership_id": membership_id, "route": "PATIENT_RESPONSIBILITY"}
        )
    )
    assert patient_meta["total_count"] == 2 and len(patient_rows) == 2

    membership_rows, membership_meta = validate_paginated(
        api.list_service_lines(
            BILLING, params={"membership_id": membership_id, "route": "COVERED_BY_MEMBERSHIP"}
        )
    )
    assert membership_meta["total_count"] == 0 and membership_rows == []

    sick = by_field(patient_rows, "service_code", "SICK_VISIT")
    surcharge = by_field(patient_rows, "service_code", "AFTER_HOURS_SURCHARGE")
    assert sick["billed_amount_cents"] == 18000
    assert surcharge["billed_amount_cents"] == 7500
    assert sum(row["patient_responsibility_cents"] for row in patient_rows) == 25500

    refreshed = get_encounter(encounter["id"])
    assert refreshed["surcharge_cents"] == 7500
    assert refreshed["after_hours_reason"] == "WEEKDAY_EVENING"
