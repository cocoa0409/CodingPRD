"""Coach screening, credential lapse and renewal, and the revocation cascade."""
from test_helpers import (
    ApiErrorId,
    assert_staff_credential,
    create_staff_credential_payload,
    make_director_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _only_credential(api, school_id, admin_headers):
    rows, _meta = validate_paginated(
        api.list_school_staff_credentials(school_id, admin_headers, {"limit": 100})
    )
    assert len(rows) == 1, f"expected exactly one credential on file, found {len(rows)}"
    return rows[0]


def test_clock_checkpoint_expires_a_cleared_credential_and_renewal_closes_the_gap(
    api, admin_headers
):
    """PRD §3.2: "Whenever an administrator moves the logical clock, the service
    runs a checkpoint over every credential standing at `CLEARED`: any whose
    `certification_expires_on` is on or before the new clock's UTC date moves
    `CLEARED → EXPIRED`, and where such a credential was a `HEAD_COACH` credential
    and the school is left holding zero `CLEARED` head-coach credentials for that
    sport, the sport is appended to `credential_gap_sports` and the school's
    `version` increments by 1."
    PRD §3.2: "The count of credentials moved this way is what the clock response
    reports as `expired_credential_count`."
    PRD §3.2: "On success the credential's `certification_expires_on` is overwritten
    with the renewed date, the credential moves `EXPIRED → CLEARED`, and — for a
    `HEAD_COACH` credential — the sport leaves `credential_gap_sports` and the
    school's `version` increments by 1."

    Design: Corner/state_machines/clock_checkpoint_expires_a_cleared_credential_and_renewal_closes_the_gap_again
    """
    set_clock("2026-09-10T09:00:00Z")
    school = fx.create_school(name="North High")
    credential = fx.create_credential(
        school["id"], sport="FOOTBALL", role_title="HEAD_COACH",
        certification_expires_on="2026-09-20",
    )
    fx.clear_credential(credential["id"], background_check_reference="BGC-1")

    clock = fx.set_clock("2026-09-20T00:00:00Z")

    assert clock["expired_credential_count"] == 1
    lapsed = _only_credential(api, school["id"], admin_headers)
    assert lapsed["status"] == "EXPIRED"
    assert "FOOTBALL" in fx.read_school(school["id"])["credential_gap_sports"]

    renewed = validate_success(
        api.background_check_credential(
            credential["id"],
            {"result": "CLEARED", "background_check_reference": "BGC-2",
             "renewed_certification_expires_on": "2027-06-30"},
            admin_headers,
        ),
        200,
    )

    assert_staff_credential(renewed)
    assert renewed["status"] == "CLEARED"
    assert renewed["certification_expires_on"] == "2027-06-30"
    assert fx.read_school(school["id"])["credential_gap_sports"] == []
    rows, _meta = validate_paginated(
        api.list_school_staff_credentials(school["id"], admin_headers, {"limit": 100})
    )
    assert len(rows) == 1, "re-credentialing reuses the row rather than minting a new one"


def test_background_check_cannot_clear_an_already_lapsed_certification(api, admin_headers):
    """PRD §3.2: "Clearance is refused outright if the certification has already
    lapsed: when the clock's UTC date is at or after `certification_expires_on`, the
    answer is `ERR_CREDENTIAL_ALREADY_LAPSED`."
    PRD §3.2: "`credential_gap_sports` lists exactly those sports for which the
    school currently holds zero credentials with `role_title` `HEAD_COACH` and
    status `CLEARED`, so filing a pending head-coach credential for a sport the
    school cannot yet staff leaves that sport sitting in the gap list."

    Design: Corner/errors/clearing_a_credential_whose_certification_already_lapsed_is_rejected
    """
    set_clock("2026-09-10T09:00:00Z")
    school = fx.create_school(name="North High")
    credential = validate_success(
        api.create_staff_credential(
            create_staff_credential_payload(
                school["id"], sport="FOOTBALL", role_title="HEAD_COACH",
                certification_expires_on="2026-09-05",
            ),
            make_director_headers(school["id"]),
        ),
        201,
    )

    response = api.background_check_credential(
        credential["id"],
        {"result": "CLEARED", "background_check_reference": "BGC-LATE"},
        admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_CREDENTIAL_ALREADY_LAPSED.value, 409)
    stored = _only_credential(api, school["id"], admin_headers)
    assert stored["status"] == "BACKGROUND_PENDING"
    assert "FOOTBALL" in fx.read_school(school["id"])["credential_gap_sports"]


def test_credential_revocation_reopens_the_gap_and_holds_the_staffed_contest(
    api, admin_headers
):
    """PRD §3.2: "the credential moves `CLEARED → REVOKED`, and where the
    `role_title` was `HEAD_COACH` and the school is left with zero `CLEARED`
    head-coach credentials for that sport, the sport is appended to
    `credential_gap_sports` and the school's `version` increments by 1."
    PRD §3.2: "every contest whose season contests that sport, whose
    `home_school_id` is this school, whose status is `OFFICIALS_ASSIGNED` or
    `CONFIRMED`, and whose `starts_at` is still in the future relative to the
    logical clock, reverts to `SCHEDULED` with `hold_reason` set to
    `COACH_CREDENTIAL_REVOKED` and `accepted_official_count` reset to 0; every
    officiating assignment on those contests standing at `OFFERED` or `ACCEPTED`
    moves to `WITHDRAWN`, and for each formerly `ACCEPTED` one, that official's
    `accepted_assignment_count` is decremented by 1."

    Design: Difficulty/transitive_cascade/credential_revocation_cascades_four_hops_to_release_minute_restitution
    """
    ctx = fx.setup_approved_trip(confirm=True)
    credential = fx.create_cleared_head_coach(ctx["home"]["id"], sport="FOOTBALL")
    assert ctx["contest"]["status"] == "CONFIRMED"

    revoked = validate_success(
        api.revoke_credential(
            credential["id"], {"revocation_note": "certification falsified"},
            admin_headers,
        ),
        200,
    )

    assert revoked["status"] == "REVOKED"
    assert "FOOTBALL" in fx.read_school(ctx["home"]["id"])["credential_gap_sports"]
    contest = fx.read_contest(ctx["contest"]["id"])
    assert contest["status"] == "SCHEDULED"
    assert contest["hold_reason"] == "COACH_CREDENTIAL_REVOKED"
    assert contest["accepted_official_count"] == 0
    assignment = fx.read_assignment(ctx["assignments"][0]["id"])
    assert assignment["status"] == "WITHDRAWN"


def test_credential_revocation_cancels_the_approved_trip_and_restores_release_minutes(
    api, admin_headers
):
    """PRD §3.2: "every transport request whose `contest_id` names one of them and
    whose status is `APPROVED` moves to `CANCELLED` with `cancelled_reason`
    `CONTEST_HOLD_CASCADE`."
    PRD §3.2: "each trip's `requesting_school_id` has its `release_minutes_used`
    decremented by exactly that trip's `release_minutes`, restoring the conservation
    rule of §2.9."

    Design: Difficulty/transitive_cascade/credential_revocation_cascades_four_hops_to_release_minute_restitution
    """
    ctx = fx.setup_approved_trip(confirm=True)
    credential = fx.create_cleared_head_coach(ctx["home"]["id"], sport="FOOTBALL")
    assert ctx["trip"]["release_minutes"] == 60
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 60

    validate_success(
        api.revoke_credential(credential["id"], {}, admin_headers), 200
    )

    trip = fx.read_transport(ctx["trip"]["id"])
    assert trip["status"] == "CANCELLED"
    assert trip["cancelled_reason"] == "CONTEST_HOLD_CASCADE"
    assert trip["release_minutes"] == 60, "the cancelled trip still reports its own minutes"
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 0
