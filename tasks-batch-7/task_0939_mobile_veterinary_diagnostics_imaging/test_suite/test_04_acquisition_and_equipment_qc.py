"""On-site acquisition, its ladder of matching rungs, and equipment quality control."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accepted_referral_with_appointment,
    acquire_study,
    add_stop,
    arrive_stop,
    assert_same_instant,
    calibrate,
    dispatch_route,
    make_clinic_user_headers,
    make_field_tech_headers,
    new_calibrated_equipment,
    new_clinic,
    new_equipment,
    new_mobile_unit,
    new_route,
    new_study,
    new_technician,
    publish_route,
    qc_study,
    record_qc_check,
    set_clock,
    setup_mobile_scene,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# --------------------------------------------------------------------------
# Equipment usage cap — difficulty instance
# --------------------------------------------------------------------------
def _four_studies_at_one_arrived_stop(api):
    set_clock("2026-05-04T08:00:00Z")
    return setup_mobile_scene(
        clinic_name="Overuse Vet", address_zone="Z13", unit_name="Van U",
        equipment_serial="US-U", technician_name="Ola Berg",
        body_regions=("ABDOMEN", "THORAX", "PELVIS", "NECK"),
    )


def test_a_modality_unit_admits_exactly_three_acquisitions_between_passing_checks(api):
    """PRD §3.5: "A modality unit may perform three acquisitions between passing
    quality checks: the first three succeed, because on entry the counter reads 0,
    then 1, then 2; the fourth is refused with `ERR_EQUIPMENT_QC_DUE` because the
    counter reads exactly 3."
    PRD §3.5: "A successful acquisition increments the counter by one. A passing
    equipment QC check resets it to 0, and so does recalibration."

    Design: Difficulty/boundary_precision_check/equipment_usage_cap_admits_exactly_three_acquisitions
    """
    scene = _four_studies_at_one_arrived_stop(api)
    equipment_id = scene["equipment"]["id"]
    technician_id = scene["technician"]["id"]
    first, second, third, _fourth = scene["studies"]

    acquire_study(first["id"], equipment_id, technician_id, image_count=4)
    acquire_study(second["id"], equipment_id, technician_id, image_count=4)
    third_result = validate_success(
        api.acquire_study(
            third["id"],
            {"equipment_id": equipment_id, "technician_id": technician_id, "image_count": 4},
            make_field_tech_headers(technician_id),
        )
    )

    assert third_result["workflow_status"] == "ACQUIRED"
    assert validate_success(api.get_equipment(equipment_id, ADMIN))["usage_count_since_qc"] == 3


def test_the_fourth_acquisition_on_the_same_unit_is_refused_as_qc_due(api):
    """PRD §2.8 rung 28: "Equipment QC is not overdue.** The equipment's `usage_count_since_qc` must be
    strictly less than 3, otherwise `ERR_EQUIPMENT_QC_DUE` (409). Applies to `POST
    /studies/{study_id}/acquire`."
    PRD §3.5: "The comparison is *at or above* the cap, not *strictly above* it."
    PRD §3.4: "`acquired_studies_count` counts those in `ACQUIRED`, `ASSIGNED`,
    `READ_IN_PROGRESS`, `PRELIM_REPORTED` or `FINALIZED`."

    Design: Difficulty/boundary_precision_check/equipment_usage_cap_admits_exactly_three_acquisitions
    """
    scene = _four_studies_at_one_arrived_stop(api)
    equipment_id = scene["equipment"]["id"]
    technician_id = scene["technician"]["id"]
    first, second, third, fourth = scene["studies"]
    for study in (first, second, third):
        acquire_study(study["id"], equipment_id, technician_id, image_count=4)

    response = api.acquire_study(
        fourth["id"],
        {"equipment_id": equipment_id, "technician_id": technician_id, "image_count": 4},
        make_field_tech_headers(technician_id),
    )

    validate_error(response, ApiErrorId.ERR_EQUIPMENT_QC_DUE.value)
    assert validate_success(api.get_study(fourth["id"], SCHED))["workflow_status"] == "ORDERED"
    appointment = validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))
    assert appointment["ordered_studies_count"] == 4
    assert appointment["acquired_studies_count"] == 3
    assert appointment["pending_studies_count"] == 1


# --------------------------------------------------------------------------
# Calibration lapse blocks acquisition — difficulty instance
# --------------------------------------------------------------------------
def _stop_arrived_with_a_lapsed_modality_unit(api):
    """The window ran 2026-04-01 to 2026-04-29, so against a logical clock of
    2026-05-04 the unit computes EXPIRED."""
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Lapsed Cal Vet", "Z14")
    unit = new_mobile_unit("Van E")
    equipment = new_equipment("ULTRASOUND", "US-E", assigned_unit_id=unit["id"])
    calibrate(equipment["id"], valid_from="2026-04-01T00:00:00Z",
              valid_until="2026-04-29T00:00:00Z")
    technician = new_technician("Ivy Nolan", ["ULTRASOUND"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=45, drive_minutes_from_prev=20)
    _referral, appointment = accepted_referral_with_appointment(
        clinic["id"], route_stop_id=stop["id"], patient_name="Poppy",
        study_kind="MOBILE", requested_modality="ULTRASOUND",
        clinical_history="murmur workup",
    )
    study = new_study(appointment["id"], clinic["id"])
    publish_route(route["id"])
    dispatch_route(route["id"], technician["id"])
    arrive_stop(stop["id"], technician["id"])
    return clinic, unit, equipment, technician, study


def test_acquiring_on_a_unit_whose_calibration_window_has_lapsed_is_refused(api):
    """PRD §3.1: "Its `calibration_status` is computed on every read, in this fixed
    order of tests: it is `QUARANTINED` whenever `quarantined_at` is not null;
    otherwise it is `UNCALIBRATED` whenever `calibration_valid_from` is null;
    otherwise it is `EXPIRED` whenever the logical clock is strictly before
    `calibration_valid_from` or at or after `calibration_valid_until`; otherwise it is
    `VALID`."
    PRD §2.9: "**G4 — equipment calibration (409).** Acquiring images with a modality
    unit whose `calibration_status` is anything other than `VALID` is refused, and
    this gate applies to `POST /studies/{study_id}/acquire` alone. Its internal order
    is fixed: a `QUARANTINED` unit reports `ERR_EQUIPMENT_QUARANTINED` in preference
    to everything else; an `EXPIRED` or `UNCALIBRATED` unit reports
    `ERR_EQUIPMENT_CALIBRATION_LAPSED`."

    Design: Difficulty/cross_entity_state_dependency/study_acquire_blocked_until_equipment_recalibrated
    """
    _clinic, _unit, equipment, technician, study = _stop_arrived_with_a_lapsed_modality_unit(api)
    assert validate_success(api.get_equipment(equipment["id"], ADMIN))["calibration_status"] == "EXPIRED"

    response = api.acquire_study(
        study["id"],
        {"equipment_id": equipment["id"], "technician_id": technician["id"], "image_count": 7},
        make_field_tech_headers(technician["id"]),
    )

    validate_error(response, ApiErrorId.ERR_EQUIPMENT_CALIBRATION_LAPSED.value)
    assert validate_success(api.get_study(study["id"], SCHED))["workflow_status"] == "ORDERED"


def test_recalibrating_the_unit_lets_the_identical_acquisition_through(api):
    """PRD §3.1: "**The supplied window need not contain the logical clock.**
    Calibrating with a window that lies entirely in the past is accepted and leaves
    the unit computing `EXPIRED` immediately — only a window containing the clock
    yields `VALID`."
    PRD §3.5: "A successful acquisition moves the study `ORDERED → ACQUIRED`, stamps
    `acquired_at` with the logical clock, records the supplied `equipment_id`,
    `technician_id` and `image_count`, refreshes the appointment's disposition
    counters, and re-allocates the trip-fee share across every billable study at that
    stop — the newcomer joins the split, so its siblings' shares **fall**."

    Design: Difficulty/cross_entity_state_dependency/study_acquire_blocked_until_equipment_recalibrated
    """
    _clinic, _unit, equipment, technician, study = _stop_arrived_with_a_lapsed_modality_unit(api)
    validate_error(
        api.acquire_study(
            study["id"],
            {"equipment_id": equipment["id"], "technician_id": technician["id"], "image_count": 7},
            make_field_tech_headers(technician["id"]),
        ),
        ApiErrorId.ERR_EQUIPMENT_CALIBRATION_LAPSED.value,
    )

    refreshed = calibrate(equipment["id"], valid_from="2026-05-01T00:00:00Z",
                          valid_until="2026-05-29T00:00:00Z")
    assert refreshed["calibration_status"] == "VALID"

    acquired = validate_success(
        api.acquire_study(
            study["id"],
            {"equipment_id": equipment["id"], "technician_id": technician["id"], "image_count": 7},
            make_field_tech_headers(technician["id"]),
        )
    )

    assert acquired["workflow_status"] == "ACQUIRED"
    assert acquired["equipment_id"] == equipment["id"]
    assert acquired["image_count"] == 7
    assert_same_instant(acquired["acquired_at"], "2026-05-04T08:00:00Z")
    assert validate_success(api.get_equipment(equipment["id"], ADMIN))["usage_count_since_qc"] == 1


# --------------------------------------------------------------------------
# Gate G4 pre-empts the rung-27 modality check — difficulty instance
# --------------------------------------------------------------------------
def _quarantined_radiography_unit_and_an_ultrasound_study(api):
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Quarantine Vet", "Z11")
    unit = new_mobile_unit("Van K")
    equipment = new_calibrated_equipment(unit["id"], "RADIOGRAPHY", "XR-K")
    technician = new_technician("Sam Doyle", ["RADIOGRAPHY", "ULTRASOUND"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=45, drive_minutes_from_prev=20)
    _referral, appointment = accepted_referral_with_appointment(
        clinic["id"], route_stop_id=stop["id"], patient_name="Otis",
        study_kind="MOBILE", requested_modality="ULTRASOUND",
        clinical_history="abdominal distension",
    )
    study = new_study(appointment["id"], clinic["id"], modality="ULTRASOUND")
    publish_route(route["id"])
    dispatch_route(route["id"], technician["id"])
    arrive_stop(stop["id"], technician["id"])
    check = record_qc_check(equipment["id"], technician["id"], "FAIL",
                            note="grid line artefact")
    return equipment, technician, study, check


def test_a_failing_check_on_a_unit_that_acquired_nothing_condemns_no_study(api):
    """PRD §3.6: "The affected studies are those whose `equipment_id` is this unit,
    whose `acquired_at` is **at or after** the cutoff, and whose `workflow_status` is
    not `CANCELLED`, `NOT_PERFORMED` or `REPEAT_PENDING`; they are processed in
    `created_at` ascending order."
    PRD §3.6: "The number of studies swept in becomes the check's
    `affected_study_count`."
    PRD §3.6: "**Hop 1.** The unit's `quarantined_at` is set to the logical clock, so
    its computed `calibration_status` becomes `QUARANTINED`."

    Design: Difficulty/priority_pair_validation_conflict/equipment_quarantine_gate_preempts_modality_mismatch_rung
    """
    equipment, _technician, _study, check = _quarantined_radiography_unit_and_an_ultrasound_study(api)

    assert check["affected_study_count"] == 0
    refreshed = validate_success(api.get_equipment(equipment["id"], ADMIN))
    assert refreshed["calibration_status"] == "QUARANTINED"
    assert_same_instant(refreshed["quarantined_at"], "2026-05-04T08:00:00Z")


def test_the_quarantine_gate_wins_over_the_equipment_modality_mismatch_rung(api):
    """PRD §2.9: "Rungs 8 through 12 form an ordered block of five **write gates**.
    They sit after authentication, authorization, ownership, existence, request shape,
    enum membership and concurrency control, and **before every rung from 13
    upwards**. When any gate fires, no rung at or above 13 is evaluated at all, so
    those rungs' errors never surface for that request."
    PRD §2.8 rung 27: "Equipment modality matches.** The equipment's `modality` must equal the study's
    `modality`, otherwise `ERR_EQUIPMENT_MODALITY_MISMATCH` (422). Applies to `POST
    /studies/{study_id}/acquire`."

    The named unit is a RADIOGRAPHY unit and the study is ULTRASOUND, which rung 27
    would reject; because the same unit is QUARANTINED, gate G4 at rung 11 pre-empts
    it and the quarantine code is what surfaces.

    Design: Difficulty/priority_pair_validation_conflict/equipment_quarantine_gate_preempts_modality_mismatch_rung
    """
    equipment, technician, study, _check = _quarantined_radiography_unit_and_an_ultrasound_study(api)

    response = api.acquire_study(
        study["id"],
        {"equipment_id": equipment["id"], "technician_id": technician["id"], "image_count": 5},
        make_field_tech_headers(technician["id"]),
    )

    validate_error(response, ApiErrorId.ERR_EQUIPMENT_QUARANTINED.value)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ORDERED"
    assert after["acquired_at"] is None
    assert validate_success(api.get_equipment(equipment["id"], ADMIN))["usage_count_since_qc"] == 0


# --------------------------------------------------------------------------
# The acquisition matching rungs, isolated one at a time
# --------------------------------------------------------------------------
def _dispatched_route_staffed_by_an_uncertified_technician(api):
    """Van A carries an ULTRASOUND unit; the route on van A is staffed by a
    RADIOGRAPHY-only technician, and its single stop is left EN_ROUTE."""
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Match Sweep Vet", "S3")
    van_a = new_mobile_unit("Van M3A")
    van_b = new_mobile_unit("Van M3B")
    equipment_a = new_calibrated_equipment(van_a["id"], "ULTRASOUND", "US-A3")
    equipment_b = new_calibrated_equipment(van_b["id"], "ULTRASOUND", "US-B3")
    inactive_tech = new_technician("T Inactive", ["ULTRASOUND"], status="INACTIVE")
    xray_only_tech = new_technician("T Xray Only", ["RADIOGRAPHY"])
    certified_tech = new_technician("T Certified A", ["ULTRASOUND"])
    route = new_route(van_a["id"], xray_only_tech["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=45, drive_minutes_from_prev=20)
    _referral, appointment = accepted_referral_with_appointment(
        clinic["id"], route_stop_id=stop["id"], patient_name="Mack",
        study_kind="MOBILE", requested_modality="ULTRASOUND",
    )
    study = new_study(appointment["id"], clinic["id"])
    publish_route(route["id"])
    dispatch_route(route["id"], xray_only_tech["id"])
    return {
        "clinic": clinic, "van_a": van_a, "van_b": van_b,
        "equipment_a": equipment_a, "equipment_b": equipment_b,
        "inactive_tech": inactive_tech, "xray_only_tech": xray_only_tech,
        "certified_tech": certified_tech, "route": route, "stop": stop, "study": study,
    }


def test_naming_an_inactive_technician_on_a_new_route_is_refused(api):
    """PRD §2.8 rung 23: "The **status** limb applies on `POST /routes` (against the
    `technician_id` supplied for the route), `POST /routes/{route_id}/dispatch`, `POST
    /studies/{study_id}/acquire` and `POST /qc-checks`: a `Technician` whose `status`
    is not `ACTIVE` raises `ERR_TECHNICIAN_INACTIVE` (409)."
    PRD §3.3: "The named technician must be `ACTIVE` — rung 23's status limb applies
    here and reports `ERR_TECHNICIAN_INACTIVE` — but their certifications are **not**
    checked, because a route names no modality."

    Design: Corner/errors/acquisition_matching_sweep_isolates_each_rung_in_ladder_order
    """
    scene = _dispatched_route_staffed_by_an_uncertified_technician(api)

    response = api.create_route(
        {
            "mobile_unit_id": scene["van_b"]["id"],
            "technician_id": scene["inactive_tech"]["id"],
            "service_date": "2026-05-05",
            "shift_start_minute": 480,
            "shift_end_minute": 900,
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_TECHNICIAN_INACTIVE.value)
    rows, _meta = validate_paginated(
        api.list_routes(SCHED, params={"technician_id": scene["inactive_tech"]["id"]})
    )
    assert rows == []


def test_an_uncertified_route_technician_is_refused_before_the_stop_state_is_examined(api):
    """PRD §2.8 rung 23: "The **certification** limb applies **only** on `POST
    /studies/{study_id}/acquire`, tested against the study's `modality`, and on `POST
    /qc-checks`, tested against the equipment's `modality` — never on `POST /routes`,
    because a route names no modality: a technician whose `certified_modalities` does
    not contain the relevant modality raises `ERR_TECHNICIAN_NOT_CERTIFIED` (422)."
    PRD §2.8 rung 25: "Stop has been arrived at.** The study's `RouteStop` must be in `ARRIVED` before any
    image is acquired at it, otherwise `ERR_STOP_NOT_ARRIVED` (409). Applies to
    `POST /studies/{study_id}/acquire`."

    The stop is still EN_ROUTE, so rung 25 would also reject this request; because
    rung 23 sits lower on the ladder, the certification code is what surfaces.

    Design: Corner/errors/acquisition_matching_sweep_isolates_each_rung_in_ladder_order
    """
    scene = _dispatched_route_staffed_by_an_uncertified_technician(api)

    response = api.acquire_study(
        scene["study"]["id"],
        {
            "equipment_id": scene["equipment_a"]["id"],
            "technician_id": scene["xray_only_tech"]["id"],
            "image_count": 5,
        },
        make_field_tech_headers(scene["xray_only_tech"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED.value)
    assert validate_success(api.get_study(scene["study"]["id"], SCHED))["workflow_status"] == "ORDERED"


def test_a_certified_technician_who_does_not_staff_the_route_is_refused_at_its_own_rung(api):
    """PRD §2.8 rung 24: "Technician staffs this route.** The `technician_id` supplied in the acquire body
    must equal the stop's owning `Route`'s `technician_id`, otherwise
    `ERR_TECHNICIAN_NOT_ON_ROUTE` (409). A certified, active technician who is
    simply not staffing this route is refused here, not at rung 3."
    PRD §2.8 rung 3: "`FieldTech` acquiring images: `X-User-ID` must equal the
    `technician_id` carried in the request body — a technician may only acquire as
    himself. Whether that technician also staffs the route is a **separate** question,
    decided at rung 24."

    Design: Corner/errors/acquisition_matching_sweep_isolates_each_rung_in_ladder_order
    """
    scene = _dispatched_route_staffed_by_an_uncertified_technician(api)

    response = api.acquire_study(
        scene["study"]["id"],
        {
            "equipment_id": scene["equipment_a"]["id"],
            "technician_id": scene["certified_tech"]["id"],
            "image_count": 5,
        },
        make_field_tech_headers(scene["certified_tech"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TECHNICIAN_NOT_ON_ROUTE.value)
    assert validate_success(api.get_study(scene["study"]["id"], SCHED))["workflow_status"] == "ORDERED"


def test_equipment_belonging_to_another_van_is_refused_once_the_stop_is_arrived(api):
    """PRD §2.8 rung 26: "Equipment is on the right van.** The equipment's `assigned_unit_id` must equal the
    stop's route's `mobile_unit_id`, otherwise `ERR_EQUIPMENT_NOT_ON_UNIT` (422).
    Applies to `POST /studies/{study_id}/acquire`."

    Every lower rung is satisfied deliberately: the acting technician is ACTIVE,
    ULTRASOUND-certified, staffs this very route, and the stop has been arrived at, so
    rung 26 is the only remaining objection.

    Design: Corner/errors/acquisition_matching_sweep_isolates_each_rung_in_ladder_order
    """
    scene = _dispatched_route_staffed_by_an_uncertified_technician(api)
    other_clinic = new_clinic("Match Sweep Vet Two", "S3")
    second_route = new_route(scene["van_b"]["id"], scene["certified_tech"]["id"],
                             service_date="2026-05-05")
    second_stop = add_stop(second_route["id"], other_clinic["id"], planned_arrival_minute=540,
                           service_minutes=45, drive_minutes_from_prev=20)
    _referral, appointment = accepted_referral_with_appointment(
        other_clinic["id"], route_stop_id=second_stop["id"], patient_name="Nell",
        study_kind="MOBILE", requested_modality="ULTRASOUND",
    )
    second_study = new_study(appointment["id"], other_clinic["id"])
    publish_route(second_route["id"])
    dispatch_route(second_route["id"], scene["certified_tech"]["id"])
    arrive_stop(second_stop["id"], scene["certified_tech"]["id"])

    response = api.acquire_study(
        second_study["id"],
        {
            "equipment_id": scene["equipment_a"]["id"],
            "technician_id": scene["certified_tech"]["id"],
            "image_count": 5,
        },
        make_field_tech_headers(scene["certified_tech"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_EQUIPMENT_NOT_ON_UNIT.value)
    assert validate_success(api.get_study(second_study["id"], SCHED))["workflow_status"] == "ORDERED"


def test_an_en_route_stop_is_the_only_remaining_objection_for_a_perfect_request(api):
    """PRD §2.8 rung 25: "Stop has been arrived at.** The study's `RouteStop` must be in `ARRIVED` before any
    image is acquired at it, otherwise `ERR_STOP_NOT_ARRIVED` (409). Applies to
    `POST /studies/{study_id}/acquire`."
    PRD §3.3: "Dispatching takes it `PUBLISHED → DISPATCHED`; it is the `FieldTech`'s
    action, requires the acting technician to be the route's own `technician_id` and
    to be `ACTIVE`, requires the van to be `IN_SERVICE` (gate G3), stamps
    `dispatched_at`, and fans out to move **every** `PLANNED` stop on the route to
    `EN_ROUTE`."

    Design: Corner/errors/stop_not_arrived_is_reported_when_every_earlier_acquisition_rung_passes
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Not Arrived Vet", address_zone="S4", unit_name="Van S4",
        equipment_serial="US-S4", technician_name="T S4", arrive=False,
    )
    study = scene["studies"][0]

    response = api.acquire_study(
        study["id"],
        {
            "equipment_id": scene["equipment"]["id"],
            "technician_id": scene["technician"]["id"],
            "image_count": 5,
        },
        make_field_tech_headers(scene["technician"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_STOP_NOT_ARRIVED.value)
    assert validate_success(api.get_route_stop(scene["stop"]["id"], SCHED))["status"] == "EN_ROUTE"
    assert validate_success(api.get_equipment(scene["equipment"]["id"], ADMIN))["usage_count_since_qc"] == 0


# --------------------------------------------------------------------------
# Pipeline applicability — rung 13
# --------------------------------------------------------------------------
def test_uploading_images_against_a_mobile_study_is_refused(api):
    """PRD §3.5: "**Telerad upload.** A `ClinicUser` whose `X-User-ID` matches the
    study's clinic uploads images for a telerad study, supplying only the
    `image_count`. This verb is telerad-only: attempting it on a mobile study is
    refused at rung 13 with `ERR_STUDY_KIND_MISMATCH`."

    Design: Corner/validations/uploading_images_against_a_mobile_study_returns_kind_mismatch
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Kindcheck Vet", address_zone="VC", unit_name="Van C",
        equipment_serial="US-C", technician_name="T Eleven",
        publish=False, dispatch=False, arrive=False,
    )
    study = scene["studies"][0]

    response = api.upload_study(
        study["id"], {"image_count": 6},
        make_clinic_user_headers(scene["clinic"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_STUDY_KIND_MISMATCH.value)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ORDERED"
    assert after["acquired_at"] is None


# --------------------------------------------------------------------------
# A passing check narrows the retroactive blast radius
# --------------------------------------------------------------------------
def test_a_passing_check_narrows_a_later_failures_retroactive_blast_radius(api):
    """PRD §3.6: "A `PASS` sets the unit's `last_passing_qc_at` to the logical clock
    and resets its `usage_count_since_qc` to 0."
    PRD §3.6: "A passing check leaves `calibration_status` where it is — from `VALID`
    the unit stays `VALID` — and its real effect is forward-looking: **it narrows the
    retroactive blast radius of every future failure** to studies acquired at or after
    this instant."
    PRD §3.6: "Take the cutoff to be the unit's `last_passing_qc_at`, or, when that is
    null because the unit has never passed a check, the unit's own `created_at`."
    PRD §3.6: "**Hop 2**, caused by hop 1. Every study in the blast radius moves its
    `qc_status` to `REPEAT_REQUIRED` and its `workflow_status` to `REPEAT_PENDING`."

    Derivation: study one is acquired at 09:00, the passing check lands at 09:30 and
    study two is acquired at 10:00.  A failing check at 10:30 takes 09:30 as its
    cutoff, so only study two — acquired at or after it — is swept in.

    Design: Corner/state_machines/passing_qc_check_resets_the_usage_counter_and_narrows_the_blast_radius
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Radius Vet", address_zone="ZG", unit_name="Van G",
        equipment_serial="US-G", technician_name="Yara Sol",
        body_regions=("ABDOMEN", "THORAX"), arrive=False,
    )
    equipment_id = scene["equipment"]["id"]
    technician_id = scene["technician"]["id"]
    first, second = scene["studies"]

    set_clock("2026-05-04T09:00:00Z")
    arrive_stop(scene["stop"]["id"], technician_id)
    acquire_study(first["id"], equipment_id, technician_id, image_count=5)
    qc_study(first["id"], technician_id, "ACCEPTED")

    set_clock("2026-05-04T09:30:00Z")
    record_qc_check(equipment_id, technician_id, "PASS", note="mid-shift check clean")

    set_clock("2026-05-04T10:00:00Z")
    acquire_study(second["id"], equipment_id, technician_id, image_count=5)
    qc_study(second["id"], technician_id, "ACCEPTED")

    set_clock("2026-05-04T10:30:00Z")
    failing = record_qc_check(equipment_id, technician_id, "FAIL", note="drift detected")

    assert failing["affected_study_count"] == 1
    survivor = validate_success(api.get_study(first["id"], SCHED))
    assert survivor["qc_status"] == "ACCEPTED"
    assert survivor["workflow_status"] == "ACQUIRED"
    condemned = validate_success(api.get_study(second["id"], SCHED))
    assert condemned["qc_status"] == "REPEAT_REQUIRED"
    assert condemned["workflow_status"] == "REPEAT_PENDING"
    unit_after = validate_success(api.get_equipment(equipment_id, ADMIN))
    assert unit_after["calibration_status"] == "QUARANTINED"
    assert_same_instant(unit_after["quarantined_at"], "2026-05-04T10:30:00Z")
