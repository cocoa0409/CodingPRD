"""Guardian consent, procedure-session logging and the departmental audit."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_minor_consent,
    assert_procedure_log,
    audit_procedure_log,
    cite_violation,
    compliance_summary,
    create_active_artist,
    create_permitted_establishment,
    create_procedure_log_payload,
    create_verified_minor_consent,
    file_minor_consent,
    file_procedure_log,
    issue_establishment_enforcement,
    make_artist_headers,
    make_operator_headers,
    read_establishment,
    record_bbp_training,
    register_artist,
    register_establishment,
    set_clock,
    start_inspection_at,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
CLERK = TEST_USERS["records_clerk_headers"]


def test_minor_consent_chain_rejects_four_ways_then_accepts_the_matching_consent(api):
    """PRD §3.6: "A `client_age` strictly below 18 requires a `minor_consent_id`; its
    absence is rejected with `ERR_MINOR_CONSENT_REQUIRED` (HTTP 422)."
    PRD §3.6: "The referenced consent must already carry `verification_status`
    `VERIFIED`; one still `PENDING` or already `REJECTED` is rejected with
    `ERR_MINOR_CONSENT_NOT_VERIFIED` (HTTP 409)."
    PRD §3.6: "The consent's `authorized_procedure_type` must equal the log's
    `procedure_type` and the consent's `establishment_id` must equal the log's
    `establishment_id`; either mismatch is rejected with `ERR_MINOR_CONSENT_MISMATCH`
    (HTTP 409)."
    PRD §3.6: "And the symmetric rule closes the chain: a `client_age` of 18 or above
    must arrive with `minor_consent_id` null, and supplying a consent for an adult is
    rejected with `ERR_MINOR_CONSENT_NOT_APPLICABLE` (HTTP 422)."

    Design: Corner/validations/procedure_log_minor_consent_chain_rejections_then_success
    """
    establishment = create_permitted_establishment(
        name="Consent Chain Ink", street_address="26 Twentysixth St",
        establishment_type="COMBINED",
    )
    artist = create_active_artist(establishment["id"], "Cleo Banks")
    artist_headers = make_artist_headers(artist["id"])

    pending_consent = file_minor_consent(
        establishment["id"], minor_full_name="Pen Ding", guardian_full_name="Gua Ding",
        guardian_id_document_type="STATE_ID", guardian_id_document_number="SI-1",
    )
    pierce_consent = create_verified_minor_consent(
        establishment["id"], minor_full_name="Pier Cing", guardian_full_name="Gua Cing",
        guardian_id_document_type="PASSPORT", guardian_id_document_number="PP-3",
        authorized_procedure_type="PIERCING",
    )
    good_consent = create_verified_minor_consent(
        establishment["id"], minor_full_name="Tat Too", guardian_full_name="Gua Too",
        guardian_id_document_type="MILITARY_ID", guardian_id_document_number="MI-4",
        authorized_procedure_type="TATTOO",
    )
    assert good_consent["verification_status"] == "VERIFIED"

    def attempt(**overrides):
        payload = create_procedure_log_payload(
            establishment["id"], artist["id"], client_age=16,
            started_at="2026-05-01T08:00:00Z", ended_at="2026-05-01T09:00:00Z",
        )
        payload.update(overrides)
        return api.create_procedure_log(payload, artist_headers)

    missing = attempt()
    validate_error(missing, ApiErrorId.ERR_MINOR_CONSENT_REQUIRED.value)
    assert missing.status_code == 422

    unverified = attempt(minor_consent_id=pending_consent["id"])
    validate_error(unverified, ApiErrorId.ERR_MINOR_CONSENT_NOT_VERIFIED.value)
    assert unverified.status_code == 409

    mismatched = attempt(minor_consent_id=pierce_consent["id"])
    validate_error(mismatched, ApiErrorId.ERR_MINOR_CONSENT_MISMATCH.value)
    assert mismatched.status_code == 409

    not_applicable = attempt(minor_consent_id=good_consent["id"], client_age=30)
    validate_error(not_applicable, ApiErrorId.ERR_MINOR_CONSENT_NOT_APPLICABLE.value)
    assert not_applicable.status_code == 422

    accepted = validate_success(attempt(minor_consent_id=good_consent["id"]), 201)
    assert_procedure_log(accepted)
    assert accepted["audit_status"] == "RECORDED"

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"establishment_id": establishment["id"]})
    )
    assert meta["total_count"] == 1


def test_session_starting_after_the_consent_expiry_is_rejected(api):
    """PRD §3.6: "The record opens with `verification_status` `PENDING`,
    `verified_by_user_id` and `rejection_reason` null, and a computed `expires_at` set
    to exactly 30 days after `consent_signed_at`."
    PRD §3.6: "The session's `started_at` must be strictly before the consent's
    `expires_at`; a start at or after that instant is rejected with
    `ERR_MINOR_CONSENT_EXPIRED` (HTTP 409)."

    Design: Corner/validations/procedure_log_with_expired_minor_consent_rejected
    """
    establishment = create_permitted_establishment(
        name="Stale Consent Ink", street_address="27 Twentyseventh St"
    )
    artist = create_active_artist(establishment["id"], "Otto Vance")
    consent = create_verified_minor_consent(
        establishment["id"], minor_full_name="Eve Lapse", minor_age_at_signing=17,
        guardian_full_name="Ann Lapse", guardian_id_document_number="DL-9",
    )
    assert_minor_consent(consent)
    assert_instant_equals(consent["expires_at"], "2026-05-31T00:00:00Z", "expires_at")

    set_clock("2026-06-01T00:00:00Z")

    response = api.create_procedure_log(
        create_procedure_log_payload(
            establishment["id"], artist["id"], client_age=17,
            started_at="2026-06-01T09:00:00Z", ended_at="2026-06-01T10:00:00Z",
            minor_consent_id=consent["id"],
        ),
        make_artist_headers(artist["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MINOR_CONSENT_EXPIRED.value)
    assert response.status_code == 409

    stored = validate_success(api.get_minor_consent(consent["id"], HO))
    assert stored["verification_status"] == "VERIFIED"

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"establishment_id": establishment["id"]})
    )
    assert meta["total_count"] == 0


def test_restricted_posture_blocks_a_minor_session_but_admits_an_adult(api):
    """PRD §3.6: "Then the restricted-posture minor block: when the establishment's
    `operating_posture` is `RESTRICTED`, `client_age` must be at least 18, because a
    restricted premises may keep serving adults but not minors, and a younger client is
    rejected with `ERR_RESTRICTED_POSTURE_MINOR_BLOCK` (HTTP 409)."
    PRD §2.11: "A `RESTRICTED` establishment may keep serving adult clients but may not
    serve minors."

    Design: Corner/validations/restricted_posture_blocks_minor_procedure_but_allows_adult
    """
    establishment = create_permitted_establishment(
        name="Restricted Ink", street_address="28 Twentyeighth St"
    )
    artist = create_active_artist(establishment["id"], "Remy Sol")
    consent = create_verified_minor_consent(
        establishment["id"], minor_full_name="Kim Young", guardian_full_name="Lee Young",
        guardian_id_document_type="STATE_ID", guardian_id_document_number="SI-7",
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    cite_violation(inspection["id"], "BBP_001", "CRITICAL", "Sharps container overfull.")
    assert read_establishment(establishment["id"])["operating_posture"] == "RESTRICTED"

    artist_headers = make_artist_headers(artist["id"])
    minor_attempt = api.create_procedure_log(
        create_procedure_log_payload(
            establishment["id"], artist["id"], client_age=16,
            started_at="2026-05-05T09:00:00Z", ended_at="2026-05-05T10:00:00Z",
            minor_consent_id=consent["id"],
        ),
        artist_headers,
    )
    validate_error(minor_attempt, ApiErrorId.ERR_RESTRICTED_POSTURE_MINOR_BLOCK.value)
    assert minor_attempt.status_code == 409

    adult = validate_success(
        api.create_procedure_log(
            create_procedure_log_payload(
                establishment["id"], artist["id"], client_age=44,
                started_at="2026-05-05T09:00:00Z", ended_at="2026-05-05T10:00:00Z",
            ),
            artist_headers,
        ),
        201,
    )
    assert adult["client_age"] == 44

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"establishment_id": establishment["id"]})
    )
    assert meta["total_count"] == 1


def test_artist_from_another_premises_is_reported_as_a_mismatch(api):
    """PRD §3.6: "After the generic checks of §2.7 have passed, the artist named by
    `artist_id` must belong to the establishment named by `establishment_id`, failing
    which the filing is rejected with `ERR_ARTIST_ESTABLISHMENT_MISMATCH` (HTTP 409)."
    PRD §2.7: "And on procedure-log filing, an artist who belongs to a different
    establishment is reported as a mismatch before any posture, training or consent
    rule is consulted."

    Design: Corner/validations/procedure_log_artist_from_another_establishment_rejected
    """
    home = create_permitted_establishment(
        name="Home Studio", street_address="29 Twentyninth St"
    )
    artist = create_active_artist(home["id"], "Zia Cole")
    guest = register_establishment(
        name="Guest Studio", street_address="31 Thirtyfirst St"
    )
    assert read_establishment(guest["id"])["operating_posture"] == "CLOSED"

    response = api.create_procedure_log(
        create_procedure_log_payload(
            guest["id"], artist["id"], client_age=25,
            started_at="2026-05-01T09:00:00Z", ended_at="2026-05-01T10:00:00Z",
        ),
        make_artist_headers(artist["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ARTIST_ESTABLISHMENT_MISMATCH.value)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"establishment_id": guest["id"]})
    )
    assert meta["total_count"] == 0


def test_expired_training_then_unpermitted_artist_on_an_open_premises(api):
    """PRD §3.6: "Then the artist's own fitness, in two parts — their
    `bbp_training_expires_on` must be strictly after the session's `started_at`,
    failing which the filing is rejected with `ERR_ARTIST_BBP_EXPIRED` (HTTP 422), and
    their `permit_status` must be `ACTIVE`, failing which it is rejected with
    `ERR_ARTIST_NOT_PERMITTED` (HTTP 409)."
    PRD §3.2: "The recording sets `bbp_training_completed_on` to that date, sets
    `bbp_training_expires_on` to exactly 730 days after it — a two-year certification —
    and clears `bbp_recert_required` to false."

    Design: Corner/errors/procedure_log_expired_bbp_then_unpermitted_artist_errors
    """
    establishment = create_permitted_establishment(
        name="BBP Gate Ink", street_address="43 Fortythird St"
    )
    artist = register_artist(establishment["id"], "Stale Cert")
    stale = record_bbp_training(artist["id"], "2024-01-01T00:00:00Z")
    assert_instant_equals(
        stale["bbp_training_expires_on"], "2025-12-31T00:00:00Z", "bbp_training_expires_on"
    )

    artist_headers = make_artist_headers(artist["id"])
    payload = create_procedure_log_payload(
        establishment["id"], artist["id"], client_age=30,
        started_at="2026-05-01T09:00:00Z", ended_at="2026-05-01T10:00:00Z",
    )

    expired = api.create_procedure_log(payload, artist_headers)
    validate_error(expired, ApiErrorId.ERR_ARTIST_BBP_EXPIRED.value)
    assert expired.status_code == 422

    record_bbp_training(artist["id"], "2026-04-01T00:00:00Z")

    unpermitted = api.create_procedure_log(payload, artist_headers)
    validate_error(unpermitted, ApiErrorId.ERR_ARTIST_NOT_PERMITTED.value)
    assert unpermitted.status_code == 409

    stored = validate_success(api.get_artist(artist["id"], HO))
    assert stored["permit_status"] == "PENDING"

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"establishment_id": establishment["id"]})
    )
    assert meta["total_count"] == 0


def test_minor_consent_audit_rate_with_no_minor_sessions_is_zero(api):
    """PRD §3.9: "When the denominator is zero the rate is the literal value 0.0 —
    never null, and never an error."
    PRD §3.9: "Its denominator, reported as `minor_procedure_count_in_window`, counts
    every procedure log of this establishment whose `client_age` is strictly below 18
    and whose `started_at` falls inside the window; adult sessions are excluded from
    both the denominator and the numerator."

    Design: Corner/calculations/minor_consent_audit_rate_zero_denominator_returns_zero
    """
    establishment = create_permitted_establishment(
        name="Zero Rate Ink", street_address="21 Twentyfirst St"
    )
    summary = compliance_summary(
        establishment["id"], make_operator_headers(establishment["id"])
    )
    assert summary["minor_procedure_count_in_window"] == 0
    assert summary["flagged_minor_procedure_count"] == 0
    assert summary["minor_consent_audit_rate"] == pytest.approx(0.0, abs=1e-9)


def test_flagging_one_of_two_minor_sessions_gives_a_rate_of_one_half(api):
    """PRD §3.9: "Its numerator, reported as `flagged_minor_procedure_count`, counts
    how many of those same logs carry `audit_status` `FLAGGED`. The rate is the
    numerator divided by the denominator, rounded half up to four decimal places."
    PRD §3.6: "Flagging is admissible only from `RECORDED`, drives `RECORDED → FLAGGED`
    and writes the supplied `finding_code` into `audit_finding_code`, which is one of
    `CONSENT_EXPIRED`, `CONSENT_TYPE_MISMATCH`, `AFTERCARE_MISSING` or
    `ARTIST_NOT_PERMITTED`."
    PRD §3.7: "The minor-log term contributes 12 points for each procedure log of this
    establishment with `client_age` strictly below 18, `audit_status` `FLAGGED` and
    `started_at` inside the window."

    Design: Corner/calculations/minor_consent_audit_rate_after_flagging_one_of_two_minor_logs
    """
    establishment = create_permitted_establishment(
        name="Audit Rate Ink", street_address="22 Twentysecond St"
    )
    artist = create_active_artist(establishment["id"], "Pia Okonkwo")
    consent_one = create_verified_minor_consent(
        establishment["id"], minor_full_name="Ada Minor", minor_age_at_signing=16,
        guardian_full_name="Rex Minor", guardian_id_document_number="DL-1",
    )
    assert_instant_equals(consent_one["expires_at"], "2026-05-31T00:00:00Z", "expires_at")
    consent_two = create_verified_minor_consent(
        establishment["id"], minor_full_name="Ben Minor", minor_age_at_signing=17,
        guardian_full_name="Sam Minor", guardian_id_document_type="PASSPORT",
        guardian_id_document_number="PP-2",
    )

    log_one = file_procedure_log(
        establishment["id"], artist["id"], client_age=16,
        started_at="2026-05-01T09:00:00Z", ended_at="2026-05-01T10:00:00Z",
        minor_consent_id=consent_one["id"],
    )
    log_two = file_procedure_log(
        establishment["id"], artist["id"], client_age=17,
        started_at="2026-05-01T10:00:00Z", ended_at="2026-05-01T11:00:00Z",
        minor_consent_id=consent_two["id"], aftercare_provided=False,
    )

    # Both sessions ran at 09:00 and 10:00 on 2026-05-01; move the logical clock past
    # them so their `started_at` instants sit inside the trailing 90-day audit window
    # (PRD §3.9: the window runs from 90 days before the current logical-clock instant
    # up to and including that instant) and inside the 365-day risk lookback.
    set_clock("2026-05-01T12:00:00Z")

    flagged = audit_procedure_log(log_two["id"], "FLAG", "AFTERCARE_MISSING")
    assert flagged["audit_status"] == "FLAGGED"
    assert flagged["audit_finding_code"] == "AFTERCARE_MISSING"

    summary = compliance_summary(establishment["id"])
    assert summary["minor_procedure_count_in_window"] == 2
    assert summary["flagged_minor_procedure_count"] == 1
    assert summary["minor_consent_audit_rate"] == pytest.approx(0.5, abs=1e-9)
    assert summary["risk_score_provisional"] == 37, (
        "25 sterilization points plus 12 for the flagged minor log"
    )

    untouched = validate_success(api.get_procedure_log(log_one["id"], HO))
    assert untouched["audit_status"] == "RECORDED"
    assert read_establishment(establishment["id"])["operating_posture"] == "OPEN"


def test_back_to_back_artist_sessions_are_adjacency_not_conflict(api):
    """PRD §3.6: "A practitioner cannot be in two places at once, so the new session's
    interval — half-open, running from `started_at` up to but not including
    `ended_at`, with no buffer of any kind — must not intersect the identically
    half-open interval of any existing log for the same `artist_id`, in any
    `audit_status` whatsoever."
    PRD §3.6: "Because the intervals are half-open, back-to-back work is legitimate: an
    existing session ending at exactly the new session's `started_at`, or beginning at
    exactly the new session's `ended_at`, is adjacency rather than conflict."

    Design: Difficulty/resource_temporal_overlap/artist_half_open_sessions_allow_adjacency_reject_overlap
    """
    establishment = create_permitted_establishment(
        name="Half Open Ink", street_address="88 Sequoia Blvd"
    )
    artist = create_active_artist(establishment["id"], "Bo Tran")
    artist_headers = make_artist_headers(artist["id"])

    first = validate_success(
        api.create_procedure_log(
            create_procedure_log_payload(
                establishment["id"], artist["id"], client_age=27,
                started_at="2026-05-01T09:00:00Z", ended_at="2026-05-01T10:00:00Z",
            ),
            artist_headers,
        ),
        201,
    )
    second = validate_success(
        api.create_procedure_log(
            create_procedure_log_payload(
                establishment["id"], artist["id"], client_age=34,
                started_at="2026-05-01T10:00:00Z", ended_at="2026-05-01T11:00:00Z",
            ),
            artist_headers,
        ),
        201,
    )
    assert first["audit_status"] == "RECORDED"
    assert second["audit_status"] == "RECORDED"

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 2


def test_truly_intersecting_artist_sessions_are_rejected(api):
    """PRD §3.6: "A true intersection is rejected with `ERR_ARTIST_SESSION_OVERLAP`
    (HTTP 409)."
    PRD §3.6: "A practitioner cannot be in two places at once, so the new session's
    interval — half-open, running from `started_at` up to but not including
    `ended_at`, with no buffer of any kind — must not intersect the identically
    half-open interval of any existing log for the same `artist_id`, in any
    `audit_status` whatsoever."

    Design: Difficulty/resource_temporal_overlap/artist_half_open_sessions_allow_adjacency_reject_overlap
    """
    establishment = create_permitted_establishment(
        name="Half Open Two", street_address="89 Sequoia Blvd"
    )
    artist = create_active_artist(establishment["id"], "Bo Tran")
    artist_headers = make_artist_headers(artist["id"])

    file_procedure_log(
        establishment["id"], artist["id"], client_age=27,
        started_at="2026-05-01T09:00:00Z", ended_at="2026-05-01T10:00:00Z",
    )
    file_procedure_log(
        establishment["id"], artist["id"], client_age=34,
        started_at="2026-05-01T10:00:00Z", ended_at="2026-05-01T11:00:00Z",
    )

    overlapping = api.create_procedure_log(
        create_procedure_log_payload(
            establishment["id"], artist["id"], client_age=41,
            started_at="2026-05-01T10:30:00Z", ended_at="2026-05-01T11:30:00Z",
        ),
        artist_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_ARTIST_SESSION_OVERLAP.value)
    assert overlapping.status_code == 409

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 2


def test_closed_posture_is_reported_before_the_expired_training_failure(api):
    """PRD §3.6: "Then the posture gate: an establishment whose `operating_posture` is
    `CLOSED` accepts no sessions at all, and the filing is rejected with
    `ERR_ESTABLISHMENT_NOT_OPERATING` (HTTP 409)."
    PRD §3.6: "Then the artist's own fitness, in two parts — their
    `bbp_training_expires_on` must be strictly after the session's `started_at`,
    failing which the filing is rejected with `ERR_ARTIST_BBP_EXPIRED` (HTTP 422), and
    their `permit_status` must be `ACTIVE`, failing which it is rejected with
    `ERR_ARTIST_NOT_PERMITTED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/closed_posture_state_error_beats_expired_bbp_safety_error
    """
    establishment = create_permitted_establishment(
        name="Dual Fault Ink", street_address="21 Spruce St"
    )
    artist = register_artist(establishment["id"], "Del Frost")
    stale = record_bbp_training(artist["id"], "2024-01-01T00:00:00Z")
    assert_instant_equals(
        stale["bbp_training_expires_on"], "2025-12-31T00:00:00Z", "bbp_training_expires_on"
    )
    issue_establishment_enforcement(
        establishment["id"], "SUSPENSION", "IMMINENT_HEALTH_HAZARD"
    )
    assert read_establishment(establishment["id"])["operating_posture"] == "CLOSED"

    response = api.create_procedure_log(
        create_procedure_log_payload(
            establishment["id"], artist["id"], client_age=30,
            started_at="2026-05-01T00:00:00Z", ended_at="2026-05-01T01:00:00Z",
        ),
        make_artist_headers(artist["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ESTABLISHMENT_NOT_OPERATING.value)
    assert response.status_code == 409


def test_closed_posture_rejection_stores_no_log_and_hides_the_later_failures(api):
    """PRD §3.6: "Then the posture gate: an establishment whose `operating_posture` is
    `CLOSED` accepts no sessions at all, and the filing is rejected with
    `ERR_ESTABLISHMENT_NOT_OPERATING` (HTTP 409)."
    PRD §2.11: "A `CLOSED` establishment may not record any procedure session at all."

    Design: Difficulty/priority_pair_validation_conflict/closed_posture_state_error_beats_expired_bbp_safety_error
    """
    establishment = create_permitted_establishment(
        name="Dual Fault Two", street_address="22 Spruce St"
    )
    artist = register_artist(establishment["id"], "Del Frost")
    record_bbp_training(artist["id"], "2024-01-01T00:00:00Z")
    issue_establishment_enforcement(
        establishment["id"], "SUSPENSION", "IMMINENT_HEALTH_HAZARD"
    )

    response = api.create_procedure_log(
        create_procedure_log_payload(
            establishment["id"], artist["id"], client_age=30,
            started_at="2026-05-01T00:00:00Z", ended_at="2026-05-01T01:00:00Z",
        ),
        make_artist_headers(artist["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_ESTABLISHMENT_NOT_OPERATING.value)
    assert error["error_id"] != ApiErrorId.ERR_ARTIST_BBP_EXPIRED.value
    assert error["error_id"] != ApiErrorId.ERR_ARTIST_NOT_PERMITTED.value

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"establishment_id": establishment["id"]})
    )
    assert meta["total_count"] == 0

    parent = read_establishment(establishment["id"])
    assert parent["operating_posture"] == "CLOSED"
