"""Booking capacity and safety constraints: station double-booking, machine
turnover buffer, validation-priority conflicts, and the per-validation single-
violation checks.

Difficulty queue (A): priority_pair_validation_conflict, resource_temporal_overlap.
Corner queue (B): validations section.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_bookable_scenario, setup_clinic_inventory, book_session,
    create_station_payload, create_shift_payload, create_patient_payload,
    create_order_payload, create_session_payload, create_standing_slot_payload,
    create_lab_order_payload,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]
NEPH = TEST_USERS["nephrologist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def _fresh_pv(api, patient_id):
    return get_success_data(api.get_patient(patient_id, SCHED))["version"]


# ─── resource_temporal_overlap / station_cell_exact_double_book ───────────
def test_station_cell_exact_double_book_rejected(api):
    """PRD §3.5: "No two sessions that are neither `CANCELLED` nor `MISSED` may
    occupy the same station, shift, and `service_date` combination ... and a
    collision is rejected with `ERR_STATION_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/station_cell_exact_double_book
    """
    inv = setup_clinic_inventory()
    cid = inv["clinic"]["id"]
    p1 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="OV1", full_name="Ov One", coinsurance_pct=0.0), SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    api.create_session(create_session_payload(
        p1["id"], o1["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", p1["version"]), SCHED)
    p2 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="OV2", full_name="Ov Two", coinsurance_pct=0.0), SCHED))
    o2 = get_success_data(api.create_order(create_order_payload(p2["id"]), NEPH))
    api.activate_order(o2["id"], NEPH)
    res = api.create_session(create_session_payload(
        p2["id"], o2["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", p2["version"]), SCHED)
    validate_error(res, "ERR_STATION_DOUBLE_BOOKED")


def test_same_station_distinct_shift_does_not_double_book(api):
    """PRD §3.5: "This turnover rule is a buffered, half-open adjacency check on
    the shared machine, distinct from the exact station-cell equality of the
    double-booking rule."

    Design: Difficulty/resource_temporal_overlap/station_cell_exact_double_book
    """
    # Distinct shifts on the same station/date with a wide turnover gap do not
    # collide on the station-cell equality rule.
    inv = setup_clinic_inventory(start_minute=360, end_minute=480,
                                 turnover_buffer_minutes=0)
    cid = inv["clinic"]["id"]
    shift2 = get_success_data(api.create_shift(create_shift_payload(
        cid, code="PM", day_pattern="MWF", start_minute=600, end_minute=720,
        turnover_buffer_minutes=0), ADMIN))
    p1 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="D1", full_name="D One", coinsurance_pct=0.0), SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    api.create_session(create_session_payload(
        p1["id"], o1["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", p1["version"]), SCHED)
    p2 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="D2", full_name="D Two", coinsurance_pct=0.0), SCHED))
    o2 = get_success_data(api.create_order(create_order_payload(p2["id"]), NEPH))
    api.activate_order(o2["id"], NEPH)
    res = api.create_session(create_session_payload(
        p2["id"], o2["id"], inv["station"]["id"], shift2["id"],
        "2026-06-01", p2["version"]), SCHED)
    booked = validate_success(res, 201)
    assert booked["clinical_status"] == "BOOKED"


# ─── resource_temporal_overlap / machine_turnover_buffer_adjacency ────────
def test_machine_turnover_buffer_violation_rejected(api):
    """PRD §3.5: "two non-terminal sessions whose stations share the same machine
    on the same `service_date` must respect the earlier shift's turnover gap: the
    earlier shift's `end_minute` plus that shift's `turnover_buffer_minutes` must
    be less than or equal to the later shift's `start_minute`; if that
    disinfection gap is violated the booking is rejected with
    `ERR_TURNOVER_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/machine_turnover_buffer_adjacency
    """
    clinic = get_success_data(api.create_clinic({"name": "OvClinic2",
                                                 "dialyzer_reuse_limit": 99}, ADMIN))
    api.set_clock("2026-06-01T07:00:00Z", ADMIN)
    machine = get_success_data(api.create_machine(
        {"clinic_id": clinic["id"], "asset_tag": "OV2M1", "model": "Nipro"}, ADMIN))
    stA = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OV2A", "machine_id": machine["id"]}, ADMIN))
    stB = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OV2B", "machine_id": machine["id"]}, ADMIN))
    shAM = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "AM", "day_pattern": "MWF",
         "start_minute": 360, "end_minute": 600, "turnover_buffer_minutes": 45}, ADMIN))
    shMID = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "MID", "day_pattern": "MWF",
         "start_minute": 615, "end_minute": 720, "turnover_buffer_minutes": 45}, ADMIN))
    p1 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "OV2P1", "full_name": "Ov2 One",
         "coinsurance_pct": 0.0}, SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    api.create_session(create_session_payload(
        p1["id"], o1["id"], stA["id"], shAM["id"], "2026-06-01", p1["version"]), SCHED)
    p2 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "OV2P2", "full_name": "Ov2 Two",
         "coinsurance_pct": 0.0}, SCHED))
    o2 = get_success_data(api.create_order(create_order_payload(p2["id"]), NEPH))
    api.activate_order(o2["id"], NEPH)
    # earlier.end 600 + buffer 45 = 645 > later.start 615 -> violation
    res = api.create_session(create_session_payload(
        p2["id"], o2["id"], stB["id"], shMID["id"], "2026-06-01", p2["version"]), SCHED)
    validate_error(res, "ERR_TURNOVER_BUFFER_VIOLATION")


def test_machine_turnover_buffer_respected_passes(api):
    """PRD §3.5: "the earlier shift's `end_minute` plus that shift's
    `turnover_buffer_minutes` must be less than or equal to the later shift's
    `start_minute`"

    Design: Difficulty/resource_temporal_overlap/machine_turnover_buffer_adjacency
    """
    clinic = get_success_data(api.create_clinic({"name": "OvOk",
                                                 "dialyzer_reuse_limit": 99}, ADMIN))
    api.set_clock("2026-06-01T07:00:00Z", ADMIN)
    machine = get_success_data(api.create_machine(
        {"clinic_id": clinic["id"], "asset_tag": "OKM", "model": "Nipro"}, ADMIN))
    stA = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OKA", "machine_id": machine["id"]}, ADMIN))
    stB = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OKB", "machine_id": machine["id"]}, ADMIN))
    shAM = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "AM", "day_pattern": "MWF",
         "start_minute": 360, "end_minute": 600, "turnover_buffer_minutes": 45}, ADMIN))
    # later.start 645 == earlier.end 600 + buffer 45 -> half-open <= passes
    shLATE = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "LATE", "day_pattern": "MWF",
         "start_minute": 645, "end_minute": 760, "turnover_buffer_minutes": 45}, ADMIN))
    p1 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "OKP1", "full_name": "Ok One",
         "coinsurance_pct": 0.0}, SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    api.create_session(create_session_payload(
        p1["id"], o1["id"], stA["id"], shAM["id"], "2026-06-01", p1["version"]), SCHED)
    p2 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "OKP2", "full_name": "Ok Two",
         "coinsurance_pct": 0.0}, SCHED))
    o2 = get_success_data(api.create_order(create_order_payload(p2["id"]), NEPH))
    api.activate_order(o2["id"], NEPH)
    res = api.create_session(create_session_payload(
        p2["id"], o2["id"], stB["id"], shLATE["id"], "2026-06-01", p2["version"]), SCHED)
    booked = validate_success(res, 201)
    assert booked["clinical_status"] == "BOOKED"


# ─── priority_pair / clinic_suspended_beats_station_double_booked ─────────
def test_clinic_suspended_masks_double_booking(api):
    """PRD §2.9: "(5) the clinic being `OPEN` where required, else
    `ERR_CLINIC_SUSPENDED` ... (12) station-cell double-booking, else
    `ERR_STATION_DOUBLE_BOOKED` ... A lower-numbered check that fails masks every
    higher-numbered one."

    Design: Difficulty/priority_pair_validation_conflict/clinic_suspended_beats_station_double_booked
    """
    inv = setup_clinic_inventory()
    cid = inv["clinic"]["id"]
    p1 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="PR1", full_name="Pri One", coinsurance_pct=0.0), SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    api.create_session(create_session_payload(
        p1["id"], o1["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", p1["version"]), SCHED)
    p2 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="PR2", full_name="Pri Two", coinsurance_pct=0.0), SCHED))
    o2 = get_success_data(api.create_order(create_order_payload(p2["id"]), NEPH))
    api.activate_order(o2["id"], NEPH)
    api.suspend_clinic(cid, ADMIN)
    # second create both collides (cell) and targets a SUSPENDED clinic
    res = api.create_session(create_session_payload(
        p2["id"], o2["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", p2["version"]), SCHED)
    validate_error(res, "ERR_CLINIC_SUSPENDED")


def test_double_booking_isolated_fires_its_own_error(api):
    """PRD §3.5: "No two sessions that are neither `CANCELLED` nor `MISSED` may
    occupy the same station, shift, and `service_date` combination ... and a
    collision is rejected with `ERR_STATION_DOUBLE_BOOKED`."

    Isolates the lower-priority arm of the conflict: with the clinic OPEN (so the
    priority-5 suspend check passes), the cell collision alone yields
    ERR_STATION_DOUBLE_BOOKED — confirming the two conditions are distinct and
    that precedence, not coincidence, picked the masking error above.

    Design: Difficulty/priority_pair_validation_conflict/clinic_suspended_beats_station_double_booked
    """
    inv = setup_clinic_inventory()
    cid = inv["clinic"]["id"]
    p1 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="PB1", full_name="Pb One", coinsurance_pct=0.0), SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    api.create_session(create_session_payload(
        p1["id"], o1["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", p1["version"]), SCHED)
    p2 = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="PB2", full_name="Pb Two", coinsurance_pct=0.0), SCHED))
    o2 = get_success_data(api.create_order(create_order_payload(p2["id"]), NEPH))
    api.activate_order(o2["id"], NEPH)
    # clinic stays OPEN; only the cell collision is present
    res = api.create_session(create_session_payload(
        p2["id"], o2["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", p2["version"]), SCHED)
    validate_error(res, "ERR_STATION_DOUBLE_BOOKED")


# ─── priority_pair / isolation_required_beats_turnover_buffer ─────────────
def test_isolation_required_masks_turnover_buffer(api):
    """PRD §2.9: "(9) isolation suitability of the station, else
    `ERR_ISOLATION_STATION_REQUIRED` ... (13) machine turnover-buffer overlap,
    else `ERR_TURNOVER_BUFFER_VIOLATION` ... A lower-numbered check that fails
    masks every higher-numbered one."

    Design: Difficulty/priority_pair_validation_conflict/isolation_required_beats_turnover_buffer
    """
    clinic = get_success_data(api.create_clinic({"name": "IsoClinic",
                                                 "dialyzer_reuse_limit": 99}, ADMIN))
    api.set_clock("2026-06-01T07:00:00Z", ADMIN)
    machine = get_success_data(api.create_machine(
        {"clinic_id": clinic["id"], "asset_tag": "ISM1", "model": "Nipro"}, ADMIN))
    stA = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "ISA", "machine_id": machine["id"],
         "isolation_capable": True}, ADMIN))
    stB = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "ISB", "machine_id": machine["id"],
         "isolation_capable": False}, ADMIN))
    shAM = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "AM", "day_pattern": "MWF",
         "start_minute": 360, "end_minute": 600, "turnover_buffer_minutes": 45}, ADMIN))
    shMID = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "MID", "day_pattern": "MWF",
         "start_minute": 615, "end_minute": 720, "turnover_buffer_minutes": 45}, ADMIN))
    p0 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "ISP0", "full_name": "Iso Filler",
         "coinsurance_pct": 0.0}, SCHED))
    o0 = get_success_data(api.create_order(create_order_payload(p0["id"]), NEPH))
    api.activate_order(o0["id"], NEPH)
    api.create_session(create_session_payload(
        p0["id"], o0["id"], stA["id"], shAM["id"], "2026-06-01", p0["version"]), SCHED)
    p1 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "ISP1", "full_name": "Iso Patient",
         "requires_isolation": True, "coinsurance_pct": 0.0}, SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    # station B is non-isolation AND violates the 645>615 turnover buffer
    res = api.create_session(create_session_payload(
        p1["id"], o1["id"], stB["id"], shMID["id"], "2026-06-01", p1["version"]), SCHED)
    validate_error(res, "ERR_ISOLATION_STATION_REQUIRED")


def test_turnover_buffer_isolated_fires_its_own_error(api):
    """PRD §3.5: "two non-terminal sessions whose stations share the same machine
    on the same `service_date` must respect the earlier shift's turnover gap ...
    if that disinfection gap is violated the booking is rejected with
    `ERR_TURNOVER_BUFFER_VIOLATION`."

    Isolates the lower-priority arm: with a non-isolation patient (so the
    priority-9 isolation check passes), the turnover-buffer violation alone yields
    ERR_TURNOVER_BUFFER_VIOLATION — confirming precedence, not coincidence, picked
    the masking error above.

    Design: Difficulty/priority_pair_validation_conflict/isolation_required_beats_turnover_buffer
    """
    clinic = get_success_data(api.create_clinic({"name": "TbIso",
                                                 "dialyzer_reuse_limit": 99}, ADMIN))
    api.set_clock("2026-06-01T07:00:00Z", ADMIN)
    machine = get_success_data(api.create_machine(
        {"clinic_id": clinic["id"], "asset_tag": "TBM", "model": "Nipro"}, ADMIN))
    stA = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "TBA", "machine_id": machine["id"]}, ADMIN))
    stB = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "TBB", "machine_id": machine["id"]}, ADMIN))
    shAM = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "AM", "day_pattern": "MWF",
         "start_minute": 360, "end_minute": 600, "turnover_buffer_minutes": 45}, ADMIN))
    shMID = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "MID", "day_pattern": "MWF",
         "start_minute": 615, "end_minute": 720, "turnover_buffer_minutes": 45}, ADMIN))
    p0 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "TBP0", "full_name": "Tb Filler",
         "coinsurance_pct": 0.0}, SCHED))
    o0 = get_success_data(api.create_order(create_order_payload(p0["id"]), NEPH))
    api.activate_order(o0["id"], NEPH)
    api.create_session(create_session_payload(
        p0["id"], o0["id"], stA["id"], shAM["id"], "2026-06-01", p0["version"]), SCHED)
    # non-isolation patient on a non-isolation station -> isolation check passes;
    # only the 645>615 turnover violation remains.
    p1 = get_success_data(api.create_patient(
        {"clinic_id": clinic["id"], "mrn": "TBP1", "full_name": "Tb Patient",
         "coinsurance_pct": 0.0}, SCHED))
    o1 = get_success_data(api.create_order(create_order_payload(p1["id"]), NEPH))
    api.activate_order(o1["id"], NEPH)
    res = api.create_session(create_session_payload(
        p1["id"], o1["id"], stB["id"], shMID["id"], "2026-06-01", p1["version"]), SCHED)
    validate_error(res, "ERR_TURNOVER_BUFFER_VIOLATION")


# ─── Corner: validations / book_session_date_not_on_pattern ───────────────
def test_book_session_date_off_pattern_rejected(api):
    """PRD §3.5: "The `service_date`'s weekday must fall on the chosen shift's
    `day_pattern` — Monday, Wednesday, or Friday for `MWF`; Tuesday, Thursday, or
    Saturday for `TTHS` — or the request is rejected with
    `ERR_DATE_NOT_ON_PATTERN`."

    Design: Corner/validations/book_session_date_not_on_pattern
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    patient = scenario["patient"]
    pv = _fresh_pv(api, patient["id"])
    # 2026-06-02 is a Tuesday, not on the MWF pattern
    res = api.create_session(create_session_payload(
        patient["id"], scenario["order"]["id"], scenario["station"]["id"],
        scenario["shift"]["id"], "2026-06-02", pv), SCHED)
    validate_error(res, "ERR_DATE_NOT_ON_PATTERN")


# ─── Corner: validations / book_session_order_not_active ──────────────────
def test_book_session_against_draft_order_rejected(api):
    """PRD §3.5: "the authorizing order must be `ACTIVE` with an
    `effective_from_date` on or before the `service_date`, else
    `ERR_ORDER_NOT_ACTIVE`."

    Design: Corner/validations/book_session_order_not_active
    """
    inv = setup_clinic_inventory()
    cid = inv["clinic"]["id"]
    patient = get_success_data(api.create_patient(
        create_patient_payload(cid, mrn="NA1", full_name="Na One", coinsurance_pct=0.0), SCHED))
    order = get_success_data(api.create_order(create_order_payload(patient["id"]), NEPH))
    # order left in DRAFT (never activated)
    res = api.create_session(create_session_payload(
        patient["id"], order["id"], inv["station"]["id"], inv["shift"]["id"],
        "2026-06-01", patient["version"]), SCHED)
    validate_error(res, "ERR_ORDER_NOT_ACTIVE")


# ─── Corner: validations / hdf_modality_not_supported_by_machine ──────────
def test_hdf_order_on_non_hdf_machine_rejected(api):
    """PRD §3.5: "If the order's `modality` is `HEMODIAFILTRATION`, the station's
    bound machine must have `supports_hdf` true, else `ERR_MODALITY_NOT_SUPPORTED`."

    Design: Corner/validations/hdf_modality_not_supported_by_machine
    """
    scenario = setup_bookable_scenario(modality="HEMODIAFILTRATION", dialyzer_reuse_limit=99,
                                       supports_hdf=False, coinsurance_pct=0.0)
    patient = scenario["patient"]
    pv = _fresh_pv(api, patient["id"])
    res = api.create_session(create_session_payload(
        patient["id"], scenario["order"]["id"], scenario["station"]["id"],
        scenario["shift"]["id"], "2026-06-01", pv), SCHED)
    validate_error(res, "ERR_MODALITY_NOT_SUPPORTED")


# ─── Corner: validations / standing_slot_for_transient_rejected ───────────
def test_standing_slot_for_transient_patient_rejected(api):
    """PRD §3.5: "the patient must be a `RESIDENT`, or the request is rejected
    with `ERR_TRANSIENT_NO_STANDING_SLOT`"

    Design: Corner/validations/standing_slot_for_transient_rejected
    """
    # Isolate the RESIDENT guard: every other standing-slot precondition is
    # satisfied (OPEN clinic, ACTIVE order, non-isolation, no cell collision) so
    # the only violation is patient_kind == TRANSIENT.
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0,
                                       patient_kind="TRANSIENT")
    patient = scenario["patient"]
    pv = _fresh_pv(api, patient["id"])
    res = api.create_standing_slot(create_standing_slot_payload(
        patient["id"], scenario["shift"]["id"], scenario["station"]["id"], pv), SCHED)
    validate_error(res, "ERR_TRANSIENT_NO_STANDING_SLOT")


# ─── Corner: validations / cross_clinic_station_reference_rejected ────────
def test_cross_clinic_station_reference_rejected(api):
    """PRD §2.5: "A body foreign key that points at a missing entity, or at an
    entity belonging to a different clinic, is rejected with
    `ERR_CROSS_CLINIC_REFERENCE` (HTTP 422)."

    Design: Corner/validations/cross_clinic_station_reference_rejected
    """
    clinicA = get_success_data(api.create_clinic({"name": "ClinicA"}, ADMIN))
    clinicB = get_success_data(api.create_clinic({"name": "ClinicB"}, ADMIN))
    api.set_clock("2026-06-01T07:00:00Z", ADMIN)
    mB = get_success_data(api.create_machine(
        {"clinic_id": clinicB["id"], "asset_tag": "XB1", "model": "T"}, ADMIN))
    sB = get_success_data(api.create_station(
        {"clinic_id": clinicB["id"], "chair_label": "XB1", "machine_id": mB["id"]}, ADMIN))
    shB = get_success_data(api.create_shift(create_shift_payload(
        clinicB["id"], code="AM", day_pattern="MWF", start_minute=360, end_minute=600), ADMIN))
    pA = get_success_data(api.create_patient(
        create_patient_payload(clinicA["id"], mrn="XA1", full_name="Xa One",
                               coinsurance_pct=0.0), SCHED))
    oA = get_success_data(api.create_order(create_order_payload(pA["id"]), NEPH))
    api.activate_order(oA["id"], NEPH)
    res = api.create_session(create_session_payload(
        pA["id"], oA["id"], sB["id"], shB["id"], "2026-06-01", pA["version"]), SCHED)
    validate_error(res, "ERR_CROSS_CLINIC_REFERENCE")


# ─── Corner: validations / clinic_suspended_blocks_lab_order ──────────────
def test_suspended_clinic_blocks_lab_order(api):
    """PRD §3.1: "While a clinic sits in `SUSPENDED`, the system refuses to create
    new standing slots, treatment sessions, or lab orders for it, rejecting each
    attempt with `ERR_CLINIC_SUSPENDED`."

    Design: Corner/validations/clinic_suspended_blocks_lab_order
    """
    clinic = get_success_data(api.create_clinic({"name": "SuspClinic"}, ADMIN))
    patient = get_success_data(api.create_patient(
        create_patient_payload(clinic["id"], mrn="SU1", full_name="Su One"), SCHED))
    api.suspend_clinic(clinic["id"], ADMIN)
    res = api.create_lab_order(create_lab_order_payload(
        patient["id"], panel="MONTHLY_CHEM", scheduled_date="2026-06-15"), SCHED)
    validate_error(res, "ERR_CLINIC_SUSPENDED")
