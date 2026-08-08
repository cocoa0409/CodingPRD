"""Enforcement instruments, segregation of duties and the reinstatement penalty."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_enforcement_action,
    assert_instant_equals,
    assert_reinstatement_breakdown,
    create_active_artist,
    create_enforcement_action_payload,
    create_paid_renewal,
    create_permitted_establishment,
    create_permitted_establishment_with_artist,
    file_sterilization_record,
    issue_establishment_enforcement,
    read_artist,
    read_establishment,
    record_bbp_training,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
HO2 = TEST_USERS["health_officer_2_headers"]


def test_reinstatement_tier_is_keyed_on_the_base_figure_not_the_total(api):
    """PRD §3.8: "First, the calling `X-User-ID` must differ from the action's
    `issued_by_user_id`; an officer attempting to lift their own instrument is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "**Step one** measures the length of the suspension: `suspension_days` is the
    number of whole 24-hour days between `issued_at` and the lift instant, with any
    partial day discarded — a lift 19 days and 23 hours after issuance yields 19, not
    20."
    PRD §3.8: "**Step two** builds the base figure into `reinstatement_base_cents`: a flat
    500 dollars, expressed as 50000 cents, plus 2600 cents for every whole suspension
    day."
    PRD §3.8: "**Step three** selects the administrative percentage, and the tier is keyed
    on the base figure and never on the total: a base strictly below 100000 cents draws
    5 percent, a base at or above 100000 cents but strictly below 200000 cents draws 8
    percent, and a base of 200000 cents or more draws 12 percent."
    PRD §3.8: "Second, the action must still be `ACTIVE`; a lift aimed at one already
    `LIFTED` is rejected with `ERR_ENFORCEMENT_STATE_INVALID` (HTTP 409)."

    Design: Corner/calculations/reinstatement_penalty_tier_is_keyed_on_base_not_on_total
    """
    establishment, artist = create_permitted_establishment_with_artist(
        legal_name="Tao Meier", name="Reinstate Ink", street_address="20 Twentieth St"
    )
    action = issue_establishment_enforcement(
        establishment["id"], "SUSPENSION", "IMMINENT_HEALTH_HAZARD", HO
    )
    assert_enforcement_action(action)
    assert_instant_equals(action["issued_at"], "2026-05-01T00:00:00Z", "issued_at")

    self_lift = api.lift_enforcement_action(action["id"], HO)
    validate_error(self_lift, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert self_lift.status_code == 403

    set_clock("2026-05-20T00:00:00Z")
    lifted = validate_success(api.lift_enforcement_action(action["id"], HO2))
    assert lifted["status"] == "LIFTED"
    assert lifted["lifted_by_user_id"] == "officer-ho-2"
    assert_reinstatement_breakdown(lifted, 19, 99400, 4970, 104370)

    relift = api.lift_enforcement_action(action["id"], HO2)
    validate_error(relift, ApiErrorId.ERR_ENFORCEMENT_STATE_INVALID.value)
    assert relift.status_code == 409

    parent = read_establishment(establishment["id"])
    assert parent["permit_status"] == "ACTIVE"
    assert parent["operating_posture"] == "OPEN"
    assert parent["active_artist_count"] == 1
    assert read_artist(artist["id"])["permit_status"] == "ACTIVE"


def test_second_live_instrument_and_lifting_a_revocation_are_rejected(api):
    """PRD §3.8: "A subject may be under at most one live instrument: if any
    enforcement action against the same establishment, or against the same artist, is
    already `ACTIVE`, a second issuance is rejected with
    `ERR_ACTIVE_ENFORCEMENT_EXISTS` (HTTP 409)."
    PRD §3.8: "Third, the action's `action_type` must be `SUSPENSION`; revocations are
    permanent instruments with no exit path at all, and a lift aimed at one is rejected
    with `ERR_ENFORCEMENT_NOT_LIFTABLE` (HTTP 409)."
    PRD §3.2: "A revocation moves an `ACTIVE` artist `ACTIVE → REVOKED`, decrementing
    `active_artist_count` and bumping both versions."

    Design: Corner/validations/second_active_enforcement_and_revocation_lift_rejected
    """
    establishment, artist = create_permitted_establishment_with_artist(
        legal_name="Vic Stone", name="Revoke Ink", street_address="38 Thirtyeighth St"
    )
    first_version = read_artist(artist["id"])["version"]

    payload = create_enforcement_action_payload("REVOCATION", "UNLICENSED_PRACTICE")
    payload["expected_artist_version"] = first_version
    action = validate_success(
        api.create_artist_enforcement_action(artist["id"], payload, HO), 201
    )
    assert action["subject_type"] == "ARTIST"

    revoked = read_artist(artist["id"])
    assert revoked["permit_status"] == "REVOKED"

    second = create_enforcement_action_payload("SUSPENSION", "CONFIRMED_INFECTION")
    second["expected_artist_version"] = revoked["version"]
    duplicate = api.create_artist_enforcement_action(artist["id"], second, HO2)
    validate_error_is_one_of(
        duplicate,
        [
            ApiErrorId.ERR_ACTIVE_ENFORCEMENT_EXISTS.value,
            ApiErrorId.ERR_ARTIST_STATE_INVALID.value,
        ],
    )
    assert duplicate.status_code == 409

    not_liftable = api.lift_enforcement_action(action["id"], HO2)
    validate_error(not_liftable, ApiErrorId.ERR_ENFORCEMENT_NOT_LIFTABLE.value)
    assert not_liftable.status_code == 409

    stored = validate_success(api.get_enforcement_action(action["id"], HO))
    assert stored["status"] == "ACTIVE"

    _, meta = validate_paginated(
        api.list_enforcement_actions(HO, params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 1


def test_stale_artist_version_blocks_the_enforcement_create(api):
    """PRD §2.8: "Issuing an enforcement action against an individual artist requires
    `expected_artist_version` carrying the client's last observed `version` of that
    artist. A mismatch against the artist's current `version` is rejected with
    `ERR_STALE_ARTIST_VERSION` (HTTP 412)."
    PRD §3.8: "An action aimed at a premises records `subject_type` `ESTABLISHMENT`
    with `establishment_id` populated and `artist_id` null; an action aimed at a
    practitioner records `subject_type` `ARTIST` with `artist_id` populated and
    `establishment_id` null."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_artist_version_rejects_artist_enforcement
    """
    establishment = create_permitted_establishment(
        name="OCC Artist Ink", street_address="54 Fiftyfourth St"
    )
    artist = create_active_artist(establishment["id"], "Ver Sion")
    old_version = artist["version"]

    refreshed = record_bbp_training(artist["id"], "2026-04-15T00:00:00Z")
    new_version = refreshed["version"]
    assert new_version == old_version + 1

    stale = create_enforcement_action_payload("SUSPENSION", "UNLICENSED_PRACTICE")
    stale["expected_artist_version"] = old_version
    rejected = api.create_artist_enforcement_action(artist["id"], stale, HO)
    validate_error(rejected, ApiErrorId.ERR_STALE_ARTIST_VERSION.value)
    assert rejected.status_code == 412

    fresh = create_enforcement_action_payload("SUSPENSION", "UNLICENSED_PRACTICE")
    fresh["expected_artist_version"] = new_version
    action = validate_success(
        api.create_artist_enforcement_action(artist["id"], fresh, HO), 201
    )
    assert action["subject_type"] == "ARTIST"
    assert action["establishment_id"] is None

    assert read_artist(artist["id"])["permit_status"] == "SUSPENDED"
    assert read_establishment(establishment["id"])["active_artist_count"] == 0


def _renewal_blocked_by_enforcement():
    establishment = create_permitted_establishment(
        name="Held Renewal Studio", street_address="61 Hazel Rd"
    )
    file_sterilization_record(
        establishment["id"], "2026-04-28T00:00:00Z", "PASS", device_serial="AC-3"
    )
    application = create_paid_renewal(establishment["id"])
    action = issue_establishment_enforcement(
        establishment["id"], "SUSPENSION", "IMMINENT_HEALTH_HAZARD", HO2
    )
    return establishment, application, action


def test_renewal_approval_is_blocked_by_a_live_enforcement_action(api):
    """PRD §3.9: "Approval is guarded by five conditions evaluated in this order: the
    establishment's `open_critical_violation_count` must be zero, failing which the
    approval is rejected with `ERR_OPEN_CRITICAL_VIOLATION_BLOCKS_RENEWAL` (HTTP 409);
    the establishment's `sterilization_compliance_status` must be `COMPLIANT` or
    `DEFICIENT`, with `NONCOMPLIANT` rejected as `ERR_STERILIZATION_NONCOMPLIANT` (HTTP
    409); no enforcement action against that establishment may still be `ACTIVE`,
    failing which the rejection is `ERR_ACTIVE_ENFORCEMENT_BLOCKS_RENEWAL` (HTTP 409);
    both `attested_bbp_current` and `attested_sterilization_logs_complete` must be
    true, failing which the rejection is `ERR_RENEWAL_ATTESTATION_MISSING` (HTTP 422);
    and `payment_status` must be `PAID`, failing which the rejection is
    `ERR_RENEWAL_FEE_UNPAID` (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/renewal_approval_blocked_by_active_enforcement_on_establishment
    """
    _establishment, application, _action = _renewal_blocked_by_enforcement()
    assert application["fee_estimate_cents"] == 26875

    response = api.review_renewal_application(
        application["id"], {"decision": "APPROVE"}, HO
    )
    validate_error(response, ApiErrorId.ERR_ACTIVE_ENFORCEMENT_BLOCKS_RENEWAL.value)
    assert response.status_code == 409


def test_blocked_renewal_leaves_the_application_and_the_premises_untouched(api):
    """PRD §3.9: "no enforcement action against that establishment may still be
    `ACTIVE`, failing which the rejection is `ERR_ACTIVE_ENFORCEMENT_BLOCKS_RENEWAL`
    (HTTP 409)"
    PRD §3.8: "Issuing against a premises drives it out of `ACTIVE`: a suspension moves
    it `ACTIVE → SUSPENDED` and a revocation moves it `ACTIVE → REVOKED`."

    Design: Difficulty/cross_entity_state_dependency/renewal_approval_blocked_by_active_enforcement_on_establishment
    """
    establishment, application, action = _renewal_blocked_by_enforcement()

    blocked = api.review_renewal_application(
        application["id"], {"decision": "APPROVE"}, HO
    )
    validate_error(blocked, ApiErrorId.ERR_ACTIVE_ENFORCEMENT_BLOCKS_RENEWAL.value)

    stored = validate_success(api.get_renewal_application(application["id"], HO))
    assert stored["status"] == "SUBMITTED"
    assert stored["payment_status"] == "PAID"
    assert stored["fee_final_cents"] is None

    stored_action = validate_success(api.get_enforcement_action(action["id"], HO))
    assert stored_action["status"] == "ACTIVE"

    parent = read_establishment(establishment["id"])
    assert parent["permit_status"] == "SUSPENDED"
