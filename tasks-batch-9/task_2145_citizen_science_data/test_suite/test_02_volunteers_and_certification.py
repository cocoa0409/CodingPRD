"""Volunteer and expert enrolment plus the certification lifecycle."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_certification,
    assert_expert,
    assert_iso8601_millis,
    assert_volunteer,
    build_world,
    certify,
    complete_training,
    create_accepted_observation,
    create_active_protocol,
    create_rejected_observation,
    create_site,
    enroll_certification,
    make_expert_headers,
    open_campaign,
    read_certification,
    read_volunteer,
    STAGE_ACTORS,
    STAGE_TRAINED,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def test_registered_volunteer_is_returned_with_its_seeded_system_fields(api):
    """PRD 3.2: "A freshly registered volunteer sits in `PENDING` with no field
    privileges at all: both `quality_score` and `lifetime_quality_score` seed to
    0.5, `recognition_tier` seeds to `BRONZE`, and `lifetime_points`,
    `accepted_observation_count`, `rejected_observation_count`,
    `consecutive_accepted`, and `consecutive_rejections` all seed to 0."
    PRD 2.4: "Most records additionally carry `updated_at`, in the same ISO 8601
    UTC format with three fractional digits, and `version`, an integer that starts
    at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/volunteer_get_returns_stored_row_with_system_fields
    """
    created = validate_success(api.create_volunteer({
        "full_name": "Rex Reader", "email": "rex@example.org",
        "home_region_code": "SW-02"}, ADMIN), 201)

    stored = validate_success(api.get_volunteer(created["id"], ADMIN))

    assert_volunteer(stored)
    assert stored["status"] == "PENDING"
    assert float(stored["quality_score"]) == 0.5
    assert float(stored["lifetime_quality_score"]) == 0.5
    assert stored["recognition_tier"] == "BRONZE"
    assert stored["lifetime_points"] == 0
    assert stored["version"] == 1


def test_volunteer_identity_and_timestamps_are_server_generated(api):
    """PRD 2.4: "Every record also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional digits, stamped from the logical clock at insert time."
    PRD 2.4: "Most records additionally carry `updated_at`, in the same ISO 8601
    UTC format with three fractional digits, and `version`, an integer that starts
    at 1 on creation and increments by exactly 1 on every mutation of that row."
    PRD 3.2: "A freshly registered volunteer sits in `PENDING` with no field
    privileges at all: both `quality_score` and `lifetime_quality_score` seed to
    0.5, `recognition_tier` seeds to `BRONZE`, and `lifetime_points`,
    `accepted_observation_count`, `rejected_observation_count`,
    `consecutive_accepted`, and `consecutive_rejections` all seed to 0."

    Design: Corner/entities/volunteer_system_fields_are_server_generated
    """
    created = validate_success(api.create_volunteer({
        "full_name": "Sys Fields", "email": "sys@example.org",
        "home_region_code": "NE-09"}, ADMIN), 201)

    assert created["version"] == 1
    assert created["status"] == "PENDING"
    assert_iso8601_millis(created["created_at"], "created_at")
    assert_iso8601_millis(created["updated_at"], "updated_at")
    assert created["accepted_observation_count"] == 0
    assert created["consecutive_rejections"] == 0


def test_expert_verification_weight_must_sit_inside_the_declared_range(api):
    """PRD 3.2: "Experts are registered the same way, with `full_name`, the
    `specialty_taxon` they adjudicate, and a `verification_weight` between 0.50 and
    4.00 inclusive at two decimal places — the base influence their vote will
    carry."
    PRD 3.2: "A new expert begins `ACTIVE`, with `vote_count` and
    `retracted_confirm_count` at 0."
    PRD 2.7: "**Priority 6 — payload shape (all creating and acting operations
    that take a body).** Every required field must be present, every value must
    match its declared type, every enum value must be a declared member of its
    enumeration, and every numeric value must fall inside its declared range;
    otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/expert_create_verification_weight_out_of_range_rejected
    """
    over = api.create_expert({
        "full_name": "Over Weighted", "specialty_taxon": "AVES",
        "verification_weight": 5.00}, ADMIN)
    validate_error(over, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    at_max = validate_success(api.create_expert({
        "full_name": "Max Weighted", "specialty_taxon": "AVES",
        "verification_weight": 4.00}, ADMIN), 201)

    assert_expert(at_max)
    assert float(at_max["verification_weight"]) == 4.00, (
        f"4.00 is inclusive, got {at_max['verification_weight']}")
    assert at_max["status"] == "ACTIVE"
    assert at_max["vote_count"] == 0


def test_enrolment_lands_the_certification_in_enrolled(api):
    """PRD 3.2: "A `ProgramAdmin` enrols a volunteer by naming the `volunteer_id`,
    the `protocol_id` being trained on, the `trainer_expert_id` who will run the
    session, and the `level` being attempted (`BASIC`, `ADVANCED`, or `EXPERT`).
    The row starts in `ENROLLED` with `exam_score`, `granted_at`, and `expires_at`
    all null and `suspended_reason` at `NONE`."

    Design: Corner/state_machines/certification_initial_state_is_enrolled
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)

    created = validate_success(api.create_certification({
        "volunteer_id": world["v1"], "protocol_id": world["p1"],
        "trainer_expert_id": world["et"], "level": "BASIC"}, ADMIN), 201)

    assert_certification(created)
    assert created["status"] == "ENROLLED"
    assert created["exam_score"] is None
    assert created["granted_at"] is None
    assert created["expires_at"] is None
    assert created["suspended_reason"] == "NONE"
    assert read_volunteer(world["v1"])["status"] == "PENDING"


def test_granting_before_training_is_refused(api):
    """PRD 2.7: "**Priority 21 — certification state.** Guards `POST
    /citizen-science/certifications/{id}/complete-training` (requires `ENROLLED`)
    and `POST /citizen-science/certifications/{id}/grant` (requires `TRAINED`).
    Otherwise `ERR_CERTIFICATION_STATE_INVALID` (409)."

    Design: Corner/state_machines/certification_grant_before_training_rejected
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)
    certification = enroll_certification(world["v1"], world["p1"], world["et"],
                                         level="BASIC")

    response = api.grant_certification(certification["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_STATE_INVALID.value, 409)

    assert read_certification(certification["id"])["status"] == "ENROLLED"
    assert read_volunteer(world["v1"])["status"] == "PENDING"


def test_exam_pass_mark_is_seventy_inclusive(api):
    """PRD 3.2: "A score of at least 70 moves the certification `ENROLLED →
    TRAINED` and stores the score on the row; a score below 70 is refused with
    `ERR_EXAM_SCORE_TOO_LOW` and leaves the certification where it was."

    Design: Corner/state_machines/certification_complete_training_below_pass_score_rejected
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)
    certification = enroll_certification(world["v1"], world["p1"], world["et"],
                                         level="BASIC")
    trainer_headers = make_expert_headers(world["et"])

    below = api.complete_training(certification["id"], {"exam_score": 69},
                                  trainer_headers)
    validate_error(below, ApiErrorId.ERR_EXAM_SCORE_TOO_LOW.value, 422)

    after_failure = read_certification(certification["id"])
    assert after_failure["status"] == "ENROLLED"
    assert after_failure["exam_score"] is None

    at_mark = validate_success(api.complete_training(
        certification["id"], {"exam_score": 70}, trainer_headers))
    assert at_mark["status"] == "TRAINED", (
        f"A score of at least 70 moves the certification to TRAINED, got "
        f"{at_mark['status']}")
    assert read_certification(certification["id"])["exam_score"] == 70


def test_granting_a_credential_activates_a_pending_volunteer(api):
    """PRD 3.2: "On success the service stamps `granted_at` from the logical clock
    and sets `expires_at` to that instant advanced by the protocol's
    `certification_valid_days` in days — so a protocol left at its 365-day default
    yields a credential good for a year to the minute."
    PRD 3.2: "Granting carries one cross-entity effect: when the owning volunteer
    is still `PENDING`, that volunteer transitions `PENDING → ACTIVE` and their
    `version` increments alongside the certification's."

    Design: Corner/state_machines/certification_grant_bubbles_pending_volunteer_to_active
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)
    certification = enroll_certification(world["v1"], world["p1"], world["et"],
                                         level="BASIC")
    complete_training(certification["id"], world["et"])

    granted = validate_success(api.grant_certification(certification["id"], ADMIN))

    assert granted["status"] == "CERTIFIED"
    assert granted["granted_at"] == "2026-08-05T09:00:00.000Z", (
        f"granted_at is stamped from the logical clock, got {granted['granted_at']}")
    assert granted["expires_at"] == "2027-08-05T09:00:00.000Z", (
        f"expires_at is granted_at advanced by 365 days, got {granted['expires_at']}")

    volunteer = read_volunteer(world["v1"])
    assert volunteer["status"] == "ACTIVE"
    assert volunteer["version"] == 2, (
        f"the volunteer's version increments alongside the certification's, got "
        f"{volunteer['version']}")


def test_reinstating_a_probation_volunteer_restores_quality_suspended_credentials(api):
    """PRD 3.2: "Reinstatement itself is available only for a volunteer whose
    `status` is `PROBATION` or `SUSPENDED` and whose current `quality_score` stands
    at 0.50 or above; the volunteer returns `PROBATION → ACTIVE` or `SUSPENDED →
    ACTIVE`, every certification of theirs sitting in `SUSPENDED` with
    `suspended_reason` `QUALITY_PROBATION` returns to `CERTIFIED` with the reason
    cleared to `NONE`, `consecutive_rejections` resets to 0, and the volunteer's
    `version` increments."
    PRD 3.7: "The fourth link, caused by the third, suspends the volunteer's
    serious credentials — every certification of theirs whose `status` is
    `CERTIFIED` and whose `level` is `ADVANCED` or `EXPERT` transitions `CERTIFIED →
    SUSPENDED` with `suspended_reason` set to `QUALITY_PROBATION`, while `BASIC`
    credentials survive so the observer can keep contributing simple records."

    Design: Corner/state_machines/volunteer_reinstate_restores_quality_suspended_certification
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)
    expert_protocol = create_active_protocol(
        code="BBS-EXPERT", title="Expert Side Protocol",
        required_certification_level="EXPERT")

    basic_cert = certify(world["v1"], world["p1"], world["et"], level="BASIC")
    expert_cert = certify(world["v1"], expert_protocol["id"], world["et"], level="EXPERT")

    campaign = validate_success(api.create_campaign({
        "name": "Autumn Count", "protocol_id": world["p1"],
        "season_start_date": "2026-08-01", "season_end_date": "2026-10-31",
        "target_observations_per_site": 3}, ADMIN), 201)
    site = create_site(campaign["id"])
    open_campaign(campaign["id"])
    world["cam1"] = campaign["id"]
    world["s_hi"] = site["id"]

    create_rejected_observation(world, count_value=1)
    create_accepted_observation(world, count_value=2)

    before = read_volunteer(world["v1"])
    assert before["status"] == "PROBATION"
    assert read_certification(expert_cert["id"])["status"] == "SUSPENDED"
    assert read_certification(basic_cert["id"])["status"] == "CERTIFIED"

    reinstated = validate_success(api.reinstate_volunteer(world["v1"], ADMIN))

    assert float(reinstated["quality_score"]) == 0.5000
    assert reinstated["status"] == "ACTIVE"
    restored = read_certification(expert_cert["id"])
    assert restored["status"] == "CERTIFIED"
    assert restored["suspended_reason"] == "NONE"
    assert read_volunteer(world["v1"])["consecutive_rejections"] == 0


def test_only_the_named_trainer_may_record_the_exam_result(api):
    """PRD 3.2: "When the training session concludes, the named trainer — and only
    the named trainer — records the result."
    PRD 3.2: "Any expert other than the named trainer attempting this receives
    `ERR_NOT_RESOURCE_OWNER`, and an attempt against a certification in any state
    other than `ENROLLED` receives `ERR_CERTIFICATION_STATE_INVALID`."

    Design: Corner/rbac/expert_cannot_complete_training_they_are_not_trainer_for
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)
    certification = enroll_certification(world["v1"], world["p1"], world["et"],
                                         level="BASIC")

    response = api.complete_training(certification["id"], {"exam_score": 95},
                                     make_expert_headers(world["e1"]))
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    stored = read_certification(certification["id"])
    assert stored["status"] == "ENROLLED"
    assert stored["exam_score"] is None


def test_pending_volunteer_cannot_file_an_observation(api):
    """PRD 2.7: "**Priority 30 — volunteer standing.** Guards `POST
    /citizen-science/observations`, `POST /citizen-science/observations/{id}/resubmit`,
    and `POST /citizen-science/equipment-loans`. The volunteer's `status` must be
    `ACTIVE` or `PROBATION`, otherwise `ERR_VOLUNTEER_NOT_IN_GOOD_STANDING` (403)."
    PRD 3.5: "The observer must be in `ACTIVE` or `PROBATION` standing — a
    `PENDING` or `SUSPENDED` volunteer cannot file at all."

    Design: Corner/errors/pending_volunteer_cannot_submit_observation
    """
    world = build_world(stage=STAGE_TRAINED, clock=CLOCK)
    campaign = validate_success(api.create_campaign({
        "name": "Autumn Count", "protocol_id": world["p1"],
        "season_start_date": "2026-08-01", "season_end_date": "2026-10-31",
        "target_observations_per_site": 3}, ADMIN), 201)
    site = create_site(campaign["id"])
    open_campaign(campaign["id"])

    response = api.create_observation({
        "campaign_id": campaign["id"], "site_id": site["id"],
        "volunteer_id": world["v1"], "observed_at": "2026-08-05T06:00:00Z",
        "latitude": 44.0, "longitude": -70.0, "species_code": "BAEA",
        "count_value": 1}, world["vol_headers"])

    error = validate_error(response,
                           ApiErrorId.ERR_VOLUNTEER_NOT_IN_GOOD_STANDING.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_CERTIFICATION_NOT_VALID.value
    assert read_volunteer(world["v1"])["status"] == "PENDING"
