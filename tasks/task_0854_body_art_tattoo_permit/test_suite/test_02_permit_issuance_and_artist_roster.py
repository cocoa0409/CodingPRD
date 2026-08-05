"""Permit issuance, the artist roster and permit expiry on the logical clock."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_plan_review,
    assert_artist,
    assert_instant_equals,
    create_active_artist,
    create_establishment_pending_inspection,
    create_permitted_establishment,
    pass_preopening_inspection,
    read_establishment,
    record_bbp_training,
    register_artist,
    register_establishment,
    schedule_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
INSP = TEST_USERS["inspector_headers"]
CLERK = TEST_USERS["records_clerk_headers"]
PUBLIC = TEST_USERS["public_user_headers"]


def test_activation_requires_a_passed_preopening_and_is_admissible_once(api):
    """PRD §3.2: "It advances the establishment `PENDING_INSPECTION → ACTIVE` and is
    admissible only from `PENDING_INSPECTION`; the premises must additionally have at
    least one inspection of `inspection_type` `PREOPENING` sitting in status `PASSED`,
    and without one the attempt is rejected with `ERR_PREOPENING_INSPECTION_REQUIRED`
    (HTTP 409)."
    PRD §3.2: "Upon issuance the server stamps `permit_issued_on` with the current
    logical-clock instant and sets `permit_expires_on` to exactly 365 days later — a
    one-year permit term."

    Design: Corner/errors/activate_without_passed_preopening_then_double_activate_rejected
    """
    establishment = register_establishment(
        name="Premature Ink", street_address="44 Fortyfourth St"
    )
    approve_plan_review(establishment["id"], floor_plan_reference="FP-PM")
    inspection = schedule_inspection(
        establishment["id"],
        inspection_type="PREOPENING",
        scheduled_start_at="2026-05-01T00:00:00Z",
        scheduled_end_at="2026-05-01T02:00:00Z",
    )

    too_early = api.activate_establishment(establishment["id"], HO)
    validate_error(too_early, ApiErrorId.ERR_PREOPENING_INSPECTION_REQUIRED.value)
    assert too_early.status_code == 409

    validate_success(api.start_inspection(inspection["id"], INSP))
    finalized = validate_success(api.finalize_inspection(inspection["id"], INSP))
    assert finalized["status"] == "PASSED"

    activated = validate_success(api.activate_establishment(establishment["id"], HO))
    assert activated["permit_status"] == "ACTIVE"
    assert_instant_equals(
        activated["permit_issued_on"], "2026-05-01T00:00:00Z", "permit_issued_on"
    )
    assert_instant_equals(
        activated["permit_expires_on"], "2027-05-01T00:00:00Z", "permit_expires_on"
    )

    again = api.activate_establishment(establishment["id"], HO)
    validate_error(again, ApiErrorId.ERR_ESTABLISHMENT_STATE_INVALID.value)
    assert again.status_code == 409


def test_activation_response_already_carries_every_derived_field(api):
    """PRD §3.2: "It then recomputes `sterilization_compliance_status`, the provisional
    `risk_score` and `operating_posture`, and increments the establishment's `version`
    by one."
    PRD §1: "never on a schedule and never lazily at read time; a client that reads an
    establishment immediately after citing a violation sees the new counters, the new
    score and the new posture."

    Design: Corner/consistency_model/activation_response_already_carries_every_derived_field
    """
    establishment = create_establishment_pending_inspection(
        name="Immediate Ink", street_address="56 Fiftysixth St"
    )
    pass_preopening_inspection(establishment["id"])

    activated = validate_success(api.activate_establishment(establishment["id"], HO))
    assert activated["permit_status"] == "ACTIVE"
    assert_instant_equals(
        activated["permit_issued_on"], "2026-05-01T00:00:00Z", "permit_issued_on"
    )
    assert_instant_equals(
        activated["permit_expires_on"], "2027-05-01T00:00:00Z", "permit_expires_on"
    )
    assert activated["operating_posture"] == "OPEN"
    assert activated["risk_score"] == 25
    assert activated["sterilization_compliance_status"] == "NONCOMPLIANT"

    reread = validate_success(api.get_establishment(establishment["id"], CLERK))
    assert reread["permit_status"] == activated["permit_status"]
    assert reread["permit_expires_on"] == activated["permit_expires_on"]
    assert reread["operating_posture"] == activated["operating_posture"]
    assert reread["risk_score"] == activated["risk_score"]


def test_artist_activation_without_training_on_file_is_rejected(api):
    """PRD §3.2: "A newly registered artist sits in `permit_status` `PENDING` with no
    training on file: `bbp_training_completed_on` and `bbp_training_expires_on` are
    null, `bbp_recert_required` is false, `permit_expires_on` is null, and
    `confirmed_infection_count` and `suspension_count` are both zero."
    PRD §3.2: "Second, the artist must hold live training: `bbp_training_expires_on`
    must be non-null and strictly after the current logical-clock instant, failing
    which the attempt is rejected with `ERR_ARTIST_BBP_MISSING` (HTTP 422)."

    Design: Corner/validations/artist_activation_without_bbp_training_rejected
    """
    establishment = create_permitted_establishment(
        name="No Training Ink", street_address="37 Thirtyseventh St"
    )
    artist = register_artist(establishment["id"], "Nia Blank")
    assert_artist(artist)
    assert artist["bbp_training_expires_on"] is None

    response = api.activate_artist(artist["id"], HO)
    validate_error(response, ApiErrorId.ERR_ARTIST_BBP_MISSING.value)
    assert response.status_code == 422

    stored = validate_success(api.get_artist(artist["id"], HO))
    assert stored["permit_status"] == "PENDING"
    assert read_establishment(establishment["id"])["active_artist_count"] == 0


def test_artist_list_filters_to_a_single_establishment_roster(api):
    """PRD §3.2: "The artist roster can be read one record at a time or browsed with
    filters on `establishment_id` and `permit_status`."
    PRD §3.2: "Only `ACTIVE` artists count toward `active_artist_count`."

    Design: Corner/endpoints/artists_filtered_list_by_establishment_returns_only_that_roster
    """
    est_a = register_establishment(name="Roster A", street_address="41 Fortyfirst St")
    est_b = register_establishment(name="Roster B", street_address="42 Fortysecond St")
    a1 = register_artist(est_a["id"], "A One")
    a2 = register_artist(est_a["id"], "A Two")
    b1 = register_artist(est_b["id"], "B One")

    rows_a, meta_a = validate_paginated(
        api.list_artists(HO, params={"establishment_id": est_a["id"]})
    )
    assert meta_a["total_count"] == 2
    assert {row["id"] for row in rows_a} == {a1["id"], a2["id"]}

    rows_b, meta_b = validate_paginated(
        api.list_artists(
            HO, params={"establishment_id": est_b["id"], "permit_status": "PENDING"}
        )
    )
    assert meta_b["total_count"] == 1
    assert rows_b[0]["id"] == b1["id"]

    assert read_establishment(est_a["id"])["active_artist_count"] == 0, (
        "PENDING practitioners are excluded from active_artist_count"
    )


def test_recording_fresh_training_rehabilitates_a_probation_artist(api):
    """PRD §3.2: "The recording sets `bbp_training_completed_on` to that date, sets
    `bbp_training_expires_on` to exactly 730 days after it — a two-year certification —
    and clears `bbp_recert_required` to false."
    PRD §3.2: "An artist in `PROBATION`, by contrast, is rehabilitated: they advance
    `PROBATION → ACTIVE`, which requires that the submitted `completed_on` be at or
    before the current logical-clock instant, and the transition increments the parent
    establishment's `active_artist_count` by one, recomputes that establishment's
    `operating_posture`, and increments both the artist's `version` and the
    establishment's `version` by one."
    PRD §3.7: "**Hop two:** because the report was confirmed, the practitioner named by
    `artist_id`, when one was named, moves `ACTIVE → PROBATION` and has
    `bbp_recert_required` set to true, with `confirmed_infection_count` recomputed on
    that artist."

    Design: Corner/state_machines/artist_recertification_returns_probation_to_active
    """
    establishment = create_permitted_establishment(
        name="Recert Ink", street_address="19 Nineteenth St"
    )
    artist = create_active_artist(establishment["id"], "Mira Osei")

    report = validate_success(
        api.create_infection_report(
            {
                "establishment_id": establishment["id"],
                "artist_id": artist["id"],
                "reporter_contact": "case@example.com",
                "infection_type": "BACTERIAL",
                "procedure_date": "2026-04-15T00:00:00Z",
                "symptom_onset_at": "2026-04-20T00:00:00Z",
            },
            PUBLIC,
        ),
        201,
    )
    validate_success(
        api.advance_infection_investigation(report["id"], {"action": "SCREEN"}, HO)
    )
    confirmed = validate_success(
        api.advance_infection_investigation(report["id"], {"action": "CONFIRM"}, HO)
    )
    assert confirmed["investigation_status"] == "CONFIRMED"

    rehabilitated = record_bbp_training(artist["id"], "2026-05-01T00:00:00Z")
    assert rehabilitated["permit_status"] == "ACTIVE"
    assert rehabilitated["bbp_recert_required"] is False
    assert_instant_equals(
        rehabilitated["bbp_training_expires_on"],
        "2028-04-30T00:00:00Z",
        "bbp_training_expires_on",
    )
    assert rehabilitated["confirmed_infection_count"] == 1

    parent = read_establishment(establishment["id"])
    assert parent["active_artist_count"] == 1
    assert parent["risk_score"] == 45, (
        f"25 sterilization points plus 20 for the confirmed infection, got {parent['risk_score']}"
    )


def test_logical_clock_only_moves_strictly_forward(api):
    """PRD §2.5: "The server does not read wall-clock time for any domain decision.
    Instead it maintains a single logical clock which, before any client moves it,
    reads exactly `2026-05-01T00:00:00Z`."
    PRD §2.5: "The clock is strictly monotonic: a target instant that is at or before
    the current logical-clock instant is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP
    409)."

    Design: Corner/validations/logical_clock_must_move_strictly_forward
    """
    backwards = api.set_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, HO)
    validate_error(backwards, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)
    assert backwards.status_code == 409

    identical = api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, HO)
    validate_error(identical, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)
    assert identical.status_code == 409

    forward = validate_success(api.set_clock({"to_iso8601": "2026-05-02T00:00:00Z"}, HO))
    assert_instant_equals(forward["current_utc"], "2026-05-02T00:00:00Z", "current_utc")


def test_clock_sweep_expires_the_permit_and_deactivates_the_roster(api):
    """PRD §3.4: "The first step of the same sweep handles permits: every
    establishment sitting in `ACTIVE` whose `permit_expires_on` is at or before the new
    instant moves `ACTIVE → EXPIRED`, processed in ascending `created_at` order of the
    establishment rows; each such expiry drops every `ACTIVE` or `PROBATION` artist at
    that premises to `INACTIVE`, forces `operating_posture` to `CLOSED`, recomputes
    `active_artist_count`, increments the establishment's `version` by one, and appends
    the establishment identifier to the `expired_establishment_ids` array."

    Design: Corner/state_machines/clock_sweep_expires_permit_and_deactivates_roster
    """
    establishment = create_permitted_establishment(
        name="Lapse Ink", street_address="15 Fifteenth St"
    )
    assert_instant_equals(
        establishment["permit_expires_on"], "2027-05-01T00:00:00Z", "permit_expires_on"
    )
    artist = create_active_artist(establishment["id"], "Lark Vance")

    sweep = validate_success(api.set_clock({"to_iso8601": "2027-05-01T00:00:00Z"}, HO))
    assert_instant_equals(sweep["current_utc"], "2027-05-01T00:00:00Z", "current_utc")
    assert establishment["id"] in sweep["expired_establishment_ids"]

    expired = read_establishment(establishment["id"])
    assert expired["permit_status"] == "EXPIRED"
    assert expired["operating_posture"] == "CLOSED"
    assert expired["active_artist_count"] == 0

    stored_artist = validate_success(api.get_artist(artist["id"], HO))
    assert stored_artist["permit_status"] == "INACTIVE"


def test_artist_activation_rejected_while_parent_permit_is_not_active(api):
    """PRD §3.2: "First, the parent establishment must itself hold `permit_status`
    `ACTIVE`; a premises still awaiting plan review, awaiting inspection, suspended,
    expired or revoked cannot host a newly permitted practitioner, and the attempt is
    rejected with `ERR_ESTABLISHMENT_PERMIT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/artist_activation_requires_establishment_permit_active
    """
    establishment = register_establishment(
        name="Gate Check Ink", street_address="14 Poplar St"
    )
    artist = register_artist(establishment["id"], "Juno Park")
    record_bbp_training(artist["id"], "2026-04-01T00:00:00Z")

    response = api.activate_artist(artist["id"], HO)
    validate_error(response, ApiErrorId.ERR_ESTABLISHMENT_PERMIT_NOT_ACTIVE.value)
    assert response.status_code == 409

    stored = validate_success(api.get_artist(artist["id"], HO))
    assert stored["permit_status"] == "PENDING"
    assert stored["permit_expires_on"] is None

    parent = read_establishment(establishment["id"])
    assert parent["permit_status"] == "PENDING_PLAN_REVIEW"
    assert parent["active_artist_count"] == 0


def test_same_artist_activates_once_the_parent_permit_reaches_active(api):
    """PRD §3.2: "First, the parent establishment must itself hold `permit_status`
    `ACTIVE`; a premises still awaiting plan review, awaiting inspection, suspended,
    expired or revoked cannot host a newly permitted practitioner, and the attempt is
    rejected with `ERR_ESTABLISHMENT_PERMIT_NOT_ACTIVE` (HTTP 409)."
    PRD §3.2: "On success the artist's `permit_expires_on` is copied from the parent
    establishment's `permit_expires_on`, the establishment's `active_artist_count`
    rises by one and the establishment's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/artist_activation_requires_establishment_permit_active
    """
    establishment = register_establishment(
        name="Gate Check Two", street_address="15 Poplar St"
    )
    artist = register_artist(establishment["id"], "Juno Park")
    record_bbp_training(artist["id"], "2026-04-01T00:00:00Z")

    blocked = api.activate_artist(artist["id"], HO)
    validate_error(blocked, ApiErrorId.ERR_ESTABLISHMENT_PERMIT_NOT_ACTIVE.value)

    approve_plan_review(establishment["id"])
    pass_preopening_inspection(establishment["id"])
    permitted = validate_success(api.activate_establishment(establishment["id"], HO))
    assert permitted["permit_status"] == "ACTIVE"

    activated = validate_success(api.activate_artist(artist["id"], HO))
    assert activated["permit_status"] == "ACTIVE"
    assert activated["permit_expires_on"] == permitted["permit_expires_on"]

    parent = read_establishment(establishment["id"])
    assert parent["active_artist_count"] == 1
