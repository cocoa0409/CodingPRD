"""The reading queue, the reporting chain and peer review."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_read,
    decline_read,
    hand_back_read,
    new_specialist,
    offer_read,
    set_clock,
    setup_telerad_scene,
    study_version,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# --------------------------------------------------------------------------
# The cyclic study workflow axis — difficulty instance
# --------------------------------------------------------------------------
def _read_ready_telerad_study(clinic_name="Telerad Partner Vet", zone="Z6",
                              specialist_name="Dr Vale", stat_eligible=False,
                              species="CANINE", referral_priority="ROUTINE",
                              image_count=14):
    scene = setup_telerad_scene(
        clinic_name=clinic_name, address_zone=zone,
        technician_name="Hub QC Tech", species=species,
        referral_priority=referral_priority, image_count=image_count,
    )
    specialist = new_specialist(specialist_name, ("ULTRASOUND",), (species,),
                                stat_eligible=stat_eligible)
    return scene, specialist


def test_a_decline_returns_the_study_to_acquired_and_keeps_the_attempt_spent(api):
    """PRD §3.7: "**Declining** moves it `OFFERED → DECLINED`, stamps `responded_at`
    and the supplied `decline_reason`, and returns the study `ASSIGNED → ACQUIRED` —
    still read-ready, still eligible for another offer, one attempt poorer."
    PRD §3.7: "A successful offer creates a `ReadAssignment` in `OFFERED`, stamps its
    `offered_at` with the logical clock, leaves `responded_at` and `decline_reason`
    null, increments the study's `read_attempt_count` by 1, records that new value as
    the assignment's `attempt_number` — a 1-based index — and moves the study
    `ACQUIRED → ASSIGNED`."

    Design: Difficulty/non_linear_state_machine/study_workflow_cycles_back_through_decline_and_hand_back
    """
    set_clock("2026-05-04T09:00:00Z")
    scene, specialist = _read_ready_telerad_study()
    study = scene["studies"][0]

    first_offer = offer_read(study["id"], specialist["id"])
    assert first_offer["attempt_number"] == 1
    assert validate_success(api.get_study(study["id"], SCHED))["workflow_status"] == "ASSIGNED"

    declined = decline_read(first_offer["id"], specialist["id"], "outside subspecialty")

    assert declined["status"] == "DECLINED"
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ACQUIRED"
    assert after["qc_status"] == "ACCEPTED"
    assert after["read_attempt_count"] == 1


def test_a_hand_back_returns_the_study_to_acquired_a_second_time(api):
    """PRD §3.7: "**Handing back** an accepted read moves it `ACCEPTED → HANDED_BACK`,
    stamps `responded_at` and `decline_reason`, and returns the study
    `READ_IN_PROGRESS → ACQUIRED`; it is refused if the handing-back specialist
    already has a `PUBLISHED` report on that study."
    PRD §3.7: "Three attempts per study is a hard ceiling and **no exit gives an
    attempt back**. Attempts 1, 2 and 3 are created because the counter reads 0, 1 and
    2 on entry; the fourth offer is refused because the counter reads exactly 3.
    Declining consumes the attempt. So does handing back."
    PRD §3.7: "`open_read_count` is simply the number of that specialist's assignments
    whose `status` is `OFFERED` or `ACCEPTED`; `DECLINED`, `HANDED_BACK`, `COMPLETED`
    and `REVOKED` never count."

    Design: Difficulty/non_linear_state_machine/study_workflow_cycles_back_through_decline_and_hand_back
    """
    set_clock("2026-05-04T09:00:00Z")
    scene, specialist = _read_ready_telerad_study()
    study = scene["studies"][0]

    first_offer = offer_read(study["id"], specialist["id"])
    decline_read(first_offer["id"], specialist["id"], "outside subspecialty")
    second_offer = offer_read(study["id"], specialist["id"])
    accept_read(second_offer["id"], specialist["id"])
    assert validate_success(api.get_study(study["id"], SCHED))["workflow_status"] == "READ_IN_PROGRESS"

    handed_back = hand_back_read(second_offer["id"], specialist["id"], "conflict of interest")

    assert handed_back["status"] == "HANDED_BACK"
    assert handed_back["attempt_number"] == 2
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ACQUIRED"
    assert after["read_attempt_count"] == 2
    reader = validate_success(api.get_specialist(specialist["id"], SCHED))
    assert reader["open_read_count"] == 0
    assert reader["workload_score"] == 0


def test_the_fourth_offer_after_three_declines_is_refused_by_the_attempt_cap(api):
    """PRD §2.8 rung 33: "**Read-attempt cap.** The study's `read_attempt_count` must be strictly less than 3,
    otherwise `ERR_READ_ATTEMPT_CAP_EXCEEDED` (409). Applies to `POST
    /read-assignments`."
    PRD §3.7: "Declining consumes the attempt. So does handing back. So does a
    revocation driven by the equipment cascade."

    Design: Corner/validations/fourth_read_offer_after_three_declines_returns_attempt_cap_exceeded
    """
    set_clock("2026-05-04T09:00:00Z")
    scene, specialist = _read_ready_telerad_study(clinic_name="Decline Vet", zone="V6",
                                                  specialist_name="Dr Busy", image_count=5)
    study = scene["studies"][0]
    for reason in ("no capacity", "still no capacity", "handing to another reader"):
        offer = offer_read(study["id"], specialist["id"])
        decline_read(offer["id"], specialist["id"], reason)
    assert validate_success(api.get_study(study["id"], SCHED))["read_attempt_count"] == 3

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": specialist["id"],
            "expected_study_version": study_version(study["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_READ_ATTEMPT_CAP_EXCEEDED.value)
    rows, _meta = validate_paginated(api.list_read_assignments(SCHED, params={"study_id": study["id"]}))
    assert len(rows) == 3
    assert all(row["status"] == "DECLINED" for row in rows)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ACQUIRED"
    assert after["read_attempt_count"] == 3


# --------------------------------------------------------------------------
# Matching rungs on the reading side
# --------------------------------------------------------------------------
def test_offering_a_canine_read_to_a_feline_only_specialist_is_refused(api):
    """PRD §2.8 rung 31: "Species privilege.** The study's `species` must be a member of the specialist's
    `species_privileges`, otherwise `ERR_SPECIALIST_SPECIES_NOT_PRIVILEGED` (422).
    Applies to `POST /read-assignments`."

    Design: Corner/validations/offering_a_read_to_a_species_unprivileged_specialist_returns_error
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Species Vet", address_zone="V4",
                                technician_name="T Four", image_count=5)
    specialist = new_specialist("Dr Feline Only", ("ULTRASOUND",), ("FELINE",), stat_eligible=True)
    study = scene["studies"][0]

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": specialist["id"],
            "expected_study_version": study_version(study["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_SPECIALIST_SPECIES_NOT_PRIVILEGED.value)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ACQUIRED"
    assert after["read_attempt_count"] == 0
    assert validate_success(api.get_specialist(specialist["id"], SCHED))["open_read_count"] == 0


def test_offering_a_stat_read_to_a_specialist_who_is_not_stat_eligible_is_refused(api):
    """PRD §2.8 rung 32: "STAT eligibility.** A study whose `priority` is `STAT` may only be offered to a
    specialist whose `stat_eligible` flag is true, otherwise
    `ERR_SPECIALIST_NOT_STAT_ELIGIBLE` (422). Applies to `POST /read-assignments`."

    Design: Corner/validations/offering_a_stat_read_to_a_non_stat_eligible_specialist_returns_error
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Stat Vet", address_zone="V5",
                                technician_name="T Five", referral_priority="STAT",
                                image_count=5)
    specialist = new_specialist("Dr Routine Only", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": specialist["id"],
            "expected_study_version": study_version(study["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_SPECIALIST_NOT_STAT_ELIGIBLE.value)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["priority"] == "STAT"
    assert after["read_attempt_count"] == 0


def test_a_study_whose_image_qc_is_still_pending_is_not_read_ready(api):
    """PRD §2.8 rung 35: "**Study is read-ready** — its `workflow_status` is `ACQUIRED` and its `qc_status` is
    `ACCEPTED`; otherwise `ERR_STUDY_NOT_READ_READY` (409). Applies to `POST
    /read-assignments`."

    Design: Corner/validations/assigning_a_study_whose_image_qc_is_still_pending_returns_not_read_ready
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Unqc Vet", address_zone="V7",
                                qc_result=None, image_count=5)
    specialist = new_specialist("Dr Ready", ("ULTRASOUND",), ("CANINE",), stat_eligible=True)
    study = scene["studies"][0]
    assert validate_success(api.get_study(study["id"], SCHED))["qc_status"] == "PENDING_QC"

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": specialist["id"],
            "expected_study_version": study_version(study["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_STUDY_NOT_READ_READY.value)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ACQUIRED"
    assert after["read_attempt_count"] == 0


def _three_read_ready_studies_and_three_specialists(api):
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Reader Sweep Vet", address_zone="S5", technician_name="T S5",
        body_regions=("ABDOMEN", "THORAX", "PELVIS"), image_count=5,
    )
    suspended = new_specialist("Dr Suspended", ("ULTRASOUND",), ("CANINE",),
                               stat_eligible=False, status="SUSPENDED")
    xray_only = new_specialist("Dr Xray Reader", ("RADIOGRAPHY",), ("CANINE",), stat_eligible=False)
    fully_privileged = new_specialist("Dr Full", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    first, second, third = scene["studies"]
    offer_read(first["id"], fully_privileged["id"])
    offer_read(second["id"], fully_privileged["id"])
    return third, suspended, xray_only, fully_privileged


def test_offering_a_read_to_a_suspended_specialist_is_refused(api):
    """PRD §2.8 rung 29: "Specialist is active.** The named `Specialist`'s `status` must be `ACTIVE` — a
    specialist who is `SUSPENDED` or `INACTIVE` raises `ERR_SPECIALIST_INACTIVE`
    (409). Applies to `POST /read-assignments` and `POST /peer-reviews`."

    Design: Corner/errors/reading_side_matching_sweep_for_inactive_modality_and_capacity
    """
    study, suspended, _xray_only, _full = _three_read_ready_studies_and_three_specialists(api)

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": suspended["id"],
            "expected_study_version": study_version(study["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_SPECIALIST_INACTIVE.value)
    assert validate_success(api.get_study(study["id"], SCHED))["read_attempt_count"] == 0


def test_offering_an_ultrasound_read_to_a_radiography_only_specialist_is_refused(api):
    """PRD §2.8 rung 30: "Modality privilege.** The study's `modality` must be a member of the specialist's
    `modality_privileges`, otherwise `ERR_SPECIALIST_MODALITY_NOT_PRIVILEGED` (422).
    Applies to `POST /read-assignments`."

    Design: Corner/errors/reading_side_matching_sweep_for_inactive_modality_and_capacity
    """
    study, _suspended, xray_only, _full = _three_read_ready_studies_and_three_specialists(api)

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": xray_only["id"],
            "expected_study_version": study_version(study["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_SPECIALIST_MODALITY_NOT_PRIVILEGED.value)
    assert validate_success(api.get_study(study["id"], SCHED))["read_attempt_count"] == 0


def test_a_specialist_already_holding_two_open_reads_is_at_capacity(api):
    """PRD §2.8 rung 34: "**Specialist read capacity.** The specialist's `open_read_count` must be strictly
    less than 2, otherwise `ERR_SPECIALIST_READ_CAPACITY` (409). Applies to `POST
    /read-assignments`."
    PRD §3.7: "a specialist whose `stat_eligible` is false is scored on a
    **committed** basis, counting only assignments in `ACCEPTED`."

    Derivation: the reader holds two OFFERED, not-yet-accepted assignments, so
    open_read_count is 2 while the committed workload score is still 0.

    Design: Corner/errors/reading_side_matching_sweep_for_inactive_modality_and_capacity
    """
    study, _suspended, _xray_only, fully_privileged = _three_read_ready_studies_and_three_specialists(api)

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": fully_privileged["id"],
            "expected_study_version": study_version(study["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_SPECIALIST_READ_CAPACITY.value)
    reader = validate_success(api.get_specialist(fully_privileged["id"], SCHED))
    assert reader["open_read_count"] == 2
    assert reader["workload_score"] == 0
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["read_attempt_count"] == 0
    assert after["workflow_status"] == "ACQUIRED"


def test_the_pipeline_and_committed_workload_bases_diverge_on_identical_data(api):
    """PRD §3.7: "`workload_score` is weighted and its counting basis depends on the
    specialist: a specialist whose `stat_eligible` is true is scored on a **pipeline**
    basis, counting assignments in `OFFERED` or `ACCEPTED`, on the theory that an
    emergency reader must answer offers fast and the offer counts against them the
    moment it lands; a specialist whose `stat_eligible` is false is scored on a
    **committed** basis, counting only assignments in `ACCEPTED`."
    PRD §3.7: "On identical data — one outstanding offer for a routine study and
    nothing else — the pipeline basis scores 1 and the committed basis scores 0, while
    `open_read_count` reads 1 in both cases."

    Design: Corner/calculations/specialist_workload_pipeline_basis_versus_committed_basis
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Workload Vet", address_zone="ZK", technician_name="Hub QC Seven",
        body_regions=("ABDOMEN", "THORAX"), image_count=6,
    )
    pipeline_reader = new_specialist("Dr Pipeline", ("ULTRASOUND",), ("CANINE",), stat_eligible=True)
    committed_reader = new_specialist("Dr Committed", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    first, second = scene["studies"]
    offer_read(first["id"], pipeline_reader["id"])
    offer_read(second["id"], committed_reader["id"])

    pipeline = validate_success(api.get_specialist(pipeline_reader["id"], SCHED))
    committed = validate_success(api.get_specialist(committed_reader["id"], SCHED))

    assert pipeline["open_read_count"] == 1
    assert pipeline["workload_score"] == 1
    assert committed["open_read_count"] == 1
    assert committed["workload_score"] == 0


def test_a_second_offer_replaying_the_pre_assignment_study_version_is_refused(api):
    """PRD §2.7: "Offering a read on a study (`POST /read-assignments`) requires
    `expected_study_version`, matched against the target `Study`'s current `version`."
    PRD §2.8 rung 7: "Optimistic concurrency.** The supplied `expected_route_version`,
    `expected_study_version`, `expected_invoice_version` or
    `expected_contract_version` equals the parent record's current `version`, per
    §2.7 — otherwise `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_study_version_on_second_read_offer_returns_412
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="OCC Vet 3", address_zone="O2",
                                technician_name="T O2", image_count=5)
    reader_a = new_specialist("Dr O2 A", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    reader_b = new_specialist("Dr O2 B", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    stale_version = study_version(study["id"])
    first_assignment = offer_read(study["id"], reader_a["id"], expected_study_version=stale_version)

    response = api.create_read_assignment(
        {
            "study_id": study["id"],
            "specialist_id": reader_b["id"],
            "expected_study_version": stale_version,
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert validate_success(api.get_study(study["id"], SCHED))["read_attempt_count"] == 1
    rows, _meta = validate_paginated(api.list_read_assignments(SCHED, params={"study_id": study["id"]}))
    assert len(rows) == 1
    assert rows[0]["id"] == first_assignment["id"]
    assert validate_success(api.get_specialist(reader_b["id"], SCHED))["open_read_count"] == 0
