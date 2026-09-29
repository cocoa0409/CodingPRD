"""
Dependencies that reach across an aggregate boundary.

Three operations in this contract cannot be judged from the target record's own
state: beginning acquisition reads the coverage window's state *and* whether the
logical clock lies inside it, advancing the medication reduction reads the
triage state of every alert reachable through the admission's studies, and
presenting a surgical conference case reads the delivery state of the export
package the conference will review. Each test below drives one of those
dependencies from refused to permitted by moving only the other entity.
"""

from test_helpers import (
    api_errors as e,
    assert_admission_dimensions,
    assert_capture_value,
    assert_ids_equal,
    assert_instant_equals,
    assert_storage_value,
    constants as c,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    TECHNOLOGIST,
    as_epileptologist,
)

# Coverage window rostered for a day the stay has already begun, so the clock has
# to be walked forward into it (PRD §3.1, §3.5).
COVERAGE_OPENS_AT = "2026-08-05T00:00:00Z"
COVERAGE_CLOSES_AT = "2026-08-06T00:00:00Z"
ONE_MINUTE_BEFORE_COVERAGE = "2026-08-04T23:59:00Z"

# The instant the first alert of the stay is raised, after its segment closed.
ALERT_DETECTED_AT = "2026-08-03T00:30:00Z"
MARKING_ONSET_AT = "2026-08-02T22:00:00Z"

PRESENTER_USER_ID = "epi-presenter"
RECIPIENT_CENTER = "Regional Surgical Center"


def _stay_awaiting_coverage(api):
    """An admitted inpatient stay whose only coverage window opens on 2026-08-05."""
    return fx.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        planned_days=5,
        target_event_count=4,
        admitted_at=c.T_ADMIT,
        shift_starts_at=COVERAGE_OPENS_AT,
        shift_ends_at=COVERAGE_CLOSES_AT,
        max_concurrent_studies=2,
        channel_count=32,
    )


def _stay_with_confirmed_clinical_alert(api):
    """An admitted stay whose taper is blocked by an adjudicated clinical event.

    One 1440-minute segment is closed by a pause, a nurse documents the bedside
    response, a CLINICAL_SEIZURE marking substantiates the alert, and the
    epileptologist adjudicates the alert CLINICAL so it stands in
    CONFIRMED_CLINICAL with the marking banked.
    """
    stay = fx.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        planned_days=5,
        target_event_count=4,
        admitted_at=c.T_ADMIT,
        max_concurrent_studies=2,
        channel_count=32,
    )
    plan = fx.create_taper_plan(api, stay.admission_id, total_steps=3)
    fx.acquire_segment(
        api,
        stay.study_id,
        from_iso=c.T_ADMIT,
        to_iso=c.T_ADMIT_PLUS_1D,
        shift_id=stay.shift_id,
    )
    alert = fx.raise_alert(
        api,
        stay.study_id,
        source=c.ALERT_SOURCE_PATIENT_PUSH_BUTTON,
        at=ALERT_DETECTED_AT,
    )
    fx.record_intervention(
        api,
        alert["id"],
        interventions=[c.INTERVENTION_POSITIONING, c.INTERVENTION_OXYGEN],
        nurse_user_id="nurse-4",
    )
    marking = fx.create_marking(
        api,
        stay.study_id,
        MARKING_ONSET_AT,
        event_class=c.EVENT_CLINICAL_SEIZURE,
        duration_seconds=80,
        alert_id=alert["id"],
    )
    alert = fx.adjudicate_alert(api, alert["id"], c.CLASSIFICATION_CLINICAL)
    return stay, plan, alert, marking


def _stay_with_built_package(api):
    """A completed 25-channel inpatient study with a final report and a built package.

    The single segment runs 2026-08-02T00:00Z to 2026-08-04T12:00Z, that is 3600
    whole minutes at 0.0004 * 25 * 2.5 = 0.025 GB per channel-minute, so the
    study stores 90.00 GB and the video-stripped package allocates
    90.00 / 2.5 = 36.00 GB against the unit's 500.00 GB quota.
    """
    stay = fx.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        planned_days=5,
        target_event_count=4,
        admitted_at=c.T_ADMIT,
        max_concurrent_studies=2,
        channel_count=25,
    )
    fx.start_study(api, stay.study_id, stay.shift_id)
    fx.complete_study(api, stay.study_id, at=c.T_COMPLETE)
    fx.finalized_report(api, stay.study_id)
    package = fx.built_export(api, stay.study_id, include_video=False)
    return stay, package


def _taper_plan_state(plan):
    """The declared lifecycle value of a taper plan, whichever field carries it.

    The contract names the taper states themselves (`ACTIVE`, `HELD`,
    `COMPLETED`, `ABORTED`) but not the field they are written to, so the value
    is located rather than the field name pinned.
    """
    for name in ("status", "state"):
        if plan.get(name) is not None:
            return plan[name]
    raise AssertionError(f"taper plan exposes no lifecycle value: {plan!r}")


# ---------------------------------------------------------------------------
# A study start depends on the coverage window containing the clock
# ---------------------------------------------------------------------------


def test_study_start_refused_until_clock_enters_the_coverage_window(api):
    """An ACTIVE coverage window is not enough; the clock must lie inside its window.

    PRD §2.6: "The named coverage window is in state `ACTIVE` and the logical clock lies inside its half-open window, otherwise `ERR_NO_TECH_COVERAGE` (409)."

    Design: Difficulty/cross_entity_state_dependency/study_start_requires_shift_window_to_contain_clock
    """
    stay = _stay_awaiting_coverage(api)

    fx.set_clock(api, ONE_MINUTE_BEFORE_COVERAGE)
    refused = api.start_study(
        stay.study_id, f.start_payload(stay.shift_id), TECHNOLOGIST
    )
    validate_error(refused, e.ERR_NO_TECH_COVERAGE, 409)

    still_preparing = validate_success(api.get_study(stay.study_id, TECHNOLOGIST))
    assert still_preparing["acquisition_state"] == c.ACQ_PREPARING, (
        "a refused start must leave the study in PREPARING, got "
        f"{still_preparing['acquisition_state']!r}"
    )

    # The lower bound of the window is inclusive, so the same call now stands.
    fx.set_clock(api, COVERAGE_OPENS_AT)
    started = validate_success(
        api.start_study(stay.study_id, f.start_payload(stay.shift_id), TECHNOLOGIST)
    )
    assert started["acquisition_state"] == c.ACQ_ACQUIRING, (
        f"start at the inclusive lower bound should acquire, got {started!r}"
    )
    assert_ids_equal(started["shift_id"], stay.shift_id, "study shift_id")
    assert_instant_equals(
        started["current_segment_started_at"],
        COVERAGE_OPENS_AT,
        "current_segment_started_at",
    )


def test_study_start_inside_the_window_registers_on_shift_and_unit(api):
    """Beginning acquisition inside the window charges the window and the unit.

    PRD §3.5: "On success the study pins the named window on its own `shift_id` and keeps it for the rest of its life, opens its first segment by stamping `current_segment_started_at` from the clock, increments the window's `assigned_study_count`, increments the unit's `active_study_count` and re-derives the unit's `posture` — which may now read `COVERAGE_CONSTRAINED` — and increments the study's `version` by 1."
    PRD §2.11: "Here `active_study_count` is the number of studies of the unit whose `acquisition_state` is `ACQUIRING`, and `coverage_capacity` is the sum of `max_concurrent_studies` over the unit's coverage windows whose `state` is `ACTIVE` and whose half-open window — inclusive of `starts_at`, exclusive of `ends_at` — contains the current logical clock."

    Design: Difficulty/cross_entity_state_dependency/study_start_requires_shift_window_to_contain_clock
    """
    stay = _stay_awaiting_coverage(api)

    fx.set_clock(api, ONE_MINUTE_BEFORE_COVERAGE)
    validate_error(
        api.start_study(stay.study_id, f.start_payload(stay.shift_id), TECHNOLOGIST),
        e.ERR_NO_TECH_COVERAGE,
        409,
    )
    fx.set_clock(api, COVERAGE_OPENS_AT)
    validate_success(
        api.start_study(stay.study_id, f.start_payload(stay.shift_id), TECHNOLOGIST)
    )

    shift = validate_success(api.get_shift(stay.shift_id, COORDINATOR))
    assert shift["assigned_study_count"] == 1, (
        f"the covering window should carry one study, got {shift['assigned_study_count']!r}"
    )

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert unit["active_study_count"] == 1, (
        f"one study is ACQUIRING, got active_study_count {unit['active_study_count']!r}"
    )
    assert unit["coverage_capacity"] == 2, (
        "the single window containing the clock declares max_concurrent_studies 2, "
        f"got coverage_capacity {unit['coverage_capacity']!r}"
    )


# ---------------------------------------------------------------------------
# A taper advance depends on the triage state of the admission's alerts
# ---------------------------------------------------------------------------


def test_taper_advance_blocked_while_an_alert_stands_confirmed_clinical(api):
    """The taper interlock keys on alerts of the admission, not on the plan alone.

    PRD §2.6: "No seizure alert on any study of the admission stands in `CONFIRMED_CLINICAL`, otherwise `ERR_TAPER_BLOCKED_BY_OPEN_EVENT` (409)."
    PRD §3.6: "The close from `CONFIRMED_CLINICAL` has one further consequence worth stating plainly: because the taper interlock keys on alerts standing in `CONFIRMED_CLINICAL`, closing such an alert is what unblocks taper advancement for that admission."

    Design: Difficulty/cross_entity_state_dependency/taper_advance_depends_on_alert_triage_state
    """
    stay, plan, alert, _marking = _stay_with_confirmed_clinical_alert(api)
    assert alert["triage_state"] == c.TRIAGE_CONFIRMED_CLINICAL, (
        f"setup should leave the alert CONFIRMED_CLINICAL, got {alert['triage_state']!r}"
    )

    blocked = api.advance_taper_step(plan["id"], EPILEPTOLOGIST)
    validate_error(blocked, e.ERR_TAPER_BLOCKED_BY_OPEN_EVENT, 409)

    held_plan = validate_success(api.get_taper_plan(plan["id"], EPILEPTOLOGIST))
    assert held_plan["current_step"] == 0, (
        f"a refused advance must not move current_step, got {held_plan['current_step']!r}"
    )

    closed = validate_success(api.close_alert(alert["id"], EPILEPTOLOGIST))
    assert closed["triage_state"] == c.TRIAGE_CLOSED, (
        f"the alert should join at CLOSED, got {closed['triage_state']!r}"
    )

    advanced = validate_success(api.advance_taper_step(plan["id"], EPILEPTOLOGIST))
    assert advanced["current_step"] == 1, (
        f"the advance should now take the first step, got {advanced['current_step']!r}"
    )
    assert _taper_plan_state(advanced) == c.TAPER_ACTIVE, (
        "one step of three leaves the plan ACTIVE, got "
        f"{_taper_plan_state(advanced)!r}"
    )
    assert stay.admission_id == advanced["admission_id"]


def test_clinical_adjudication_banks_the_marking_without_meeting_the_target(api):
    """The blocking adjudication is also what banks capture weight on the admission.

    PRD §3.7: "And `weight` is computed as the class weight of the `event_class` — 1.0 for `CLINICAL_SEIZURE`, 0.5 for `SUBCLINICAL_SEIZURE`, and 0 for both `SPIKE_BURST` and `ARTIFACT` — multiplied by a provoked-event discount of 0.75 when `taper_step_at_onset` is 2 or greater, or by 1.0 when it is below 2, with the product rounded half up to 3 decimal places."
    PRD §3.7: "The retrospective figure stored on `capture_adequacy_index` is the lesser of 1.000 and `weighted_event_count` divided by `target_event_count`, rounded half up to 3 decimal places; it counts only weight already banked by adjudicated markings, it is clamped at 1.000, and it is **the only figure the `ADMITTED` to `CAPTURE_TARGET_MET` transition reads** — the transition fires when it reaches 1.000 or more, and the reverse transition fires when it falls below 1.000."

    Design: Difficulty/cross_entity_state_dependency/taper_advance_depends_on_alert_triage_state
    """
    stay, plan, alert, marking = _stay_with_confirmed_clinical_alert(api)

    validate_error(
        api.advance_taper_step(plan["id"], EPILEPTOLOGIST),
        e.ERR_TAPER_BLOCKED_BY_OPEN_EVENT,
        409,
    )
    validate_success(api.close_alert(alert["id"], EPILEPTOLOGIST))
    validate_success(api.advance_taper_step(plan["id"], EPILEPTOLOGIST))

    banked = validate_success(api.get_marking(marking["id"], EPILEPTOLOGIST))
    assert banked["status"] == c.MARKING_ADJUDICATED, (
        "the CLINICAL adjudication moves the substantiating marking to ADJUDICATED, "
        f"got {banked['status']!r}"
    )
    # taper_step_at_onset is 0, so the class weight of CLINICAL_SEIZURE stands undiscounted.
    assert_capture_value(banked["weight"], 1.000, "marking weight")

    admission = validate_success(api.get_admission(stay.admission_id, EPILEPTOLOGIST))
    # 1.000 banked weight against a target of 4 weighted events.
    assert_capture_value(
        admission["capture_adequacy_index"], 0.250, "capture_adequacy_index"
    )
    assert_admission_dimensions(admission, c.CLINICAL_ADMITTED, c.AUTH_STATE_ACTIVE)


# ---------------------------------------------------------------------------
# A conference presentation depends on the export package being delivered
# ---------------------------------------------------------------------------


def test_conference_present_refused_until_the_package_is_delivered(api):
    """A merely built package cannot carry a case into the conference.

    PRD §2.6: "The referenced export package stands in `DELIVERED` before a conference case may be presented, otherwise `ERR_EXPORT_NOT_DELIVERED` (409)."
    PRD §3.9: "Presenting the case moves `status` from `DRAFT` to `PRESENTED` and stamps `presenter_user_id` from the acting `X-User-ID`; the referenced package must stand in `DELIVERED`, otherwise `ERR_EXPORT_NOT_DELIVERED`, and a case that is neither `DRAFT` nor `DEFERRED` is refused with `ERR_INVALID_CASE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/conference_present_depends_on_export_delivery
    """
    stay, package = _stay_with_built_package(api)
    assert package["status"] == c.EXPORT_BUILT, (
        f"setup should leave the package BUILT, got {package['status']!r}"
    )
    case = validate_success(
        api.create_conference_case(
            f.conference_case_payload(stay.admission_id, package["id"]), EPILEPTOLOGIST
        ),
        expected_status=201,
    )
    assert case["status"] == c.CASE_DRAFT, (
        f"a new conference case opens in DRAFT, got {case['status']!r}"
    )

    refused = api.present_case(case["id"], as_epileptologist(PRESENTER_USER_ID))
    validate_error(refused, e.ERR_EXPORT_NOT_DELIVERED, 409)

    still_draft = validate_success(api.get_conference_case(case["id"], EPILEPTOLOGIST))
    assert still_draft["status"] == c.CASE_DRAFT, (
        f"a refused presentation must leave the case in DRAFT, got {still_draft['status']!r}"
    )
    assert still_draft["presenter_user_id"] is None, (
        "a refused presentation must not stamp presenter_user_id, got "
        f"{still_draft['presenter_user_id']!r}"
    )

    validate_success(
        api.deliver_export(package["id"], f.deliver_payload(RECIPIENT_CENTER), COORDINATOR)
    )

    presented = validate_success(
        api.present_case(case["id"], as_epileptologist(PRESENTER_USER_ID))
    )
    assert presented["status"] == c.CASE_PRESENTED, (
        f"delivery unblocks the presentation, got {presented['status']!r}"
    )
    assert_ids_equal(
        presented["presenter_user_id"], PRESENTER_USER_ID, "presenter_user_id"
    )
    assert presented["defer_round"] == 0, (
        f"the first presentation opens round 0, got {presented['defer_round']!r}"
    )


def test_delivery_records_recipient_and_leaves_the_allocated_volume_in_place(api):
    """Delivering the package the conference reviews moves no storage.

    PRD §3.9: "Delivery moves a package from `BUILT` to `DELIVERED`, stamping `delivered_at` from the clock and storing the supplied `recipient_center` naming the surgical centre; a package that is not `BUILT` is refused with `ERR_INVALID_EXPORT_STATE`."
    PRD §2.11: "Its `storage_used_gb` is recomputed, as a figure rounded half up to 2 decimal places, as the sum of `stored_gb` over every study of the unit whose `data_state` is `ONLINE` or `EXPORT_HELD`, plus the sum of `package_gb` over every export package on those same studies whose `status` is `BUILT` or `DELIVERED`."

    Design: Difficulty/cross_entity_state_dependency/conference_present_depends_on_export_delivery
    """
    stay, package = _stay_with_built_package(api)
    case = validate_success(
        api.create_conference_case(
            f.conference_case_payload(stay.admission_id, package["id"]), EPILEPTOLOGIST
        ),
        expected_status=201,
    )
    validate_error(
        api.present_case(case["id"], as_epileptologist(PRESENTER_USER_ID)),
        e.ERR_EXPORT_NOT_DELIVERED,
        409,
    )
    delivered = validate_success(
        api.deliver_export(package["id"], f.deliver_payload(RECIPIENT_CENTER), COORDINATOR)
    )
    validate_success(api.present_case(case["id"], as_epileptologist(PRESENTER_USER_ID)))

    assert delivered["status"] == c.EXPORT_DELIVERED, (
        f"the package should read DELIVERED, got {delivered['status']!r}"
    )
    assert delivered["recipient_center"] == RECIPIENT_CENTER, (
        f"recipient_center should be {RECIPIENT_CENTER!r}, got {delivered['recipient_center']!r}"
    )
    # 90.00 GB of study volume divided by the inpatient modality factor of 2.5.
    assert_storage_value(delivered["package_gb"], 36.00, "package_gb")

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    # 90.00 GB of ONLINE study volume plus the 36.00 GB the delivered package holds.
    assert_storage_value(unit["storage_used_gb"], 126.00, "storage_used_gb")
