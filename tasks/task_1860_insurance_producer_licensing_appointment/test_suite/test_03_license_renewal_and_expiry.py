"""License renewal, expiration, and reinstatement: the cyclic renewal loop,
window/grace boundaries, state-check precedence, OCC on renew, and the strict
sweep comparison (PRD sections 2.5, 2.8, 2.9, 3.3).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_instant_equals,
    assert_license,
    create_license,
    create_producer,
    get_license,
    setup_confirmed_license_action,
    setup_producer_with_license,
    validate_error,
    validate_success,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]
OFFICER_B = TEST_USERS["compliance_officer_b_headers"]


def test_license_active_renewal_self_loop():
    """PRD section 3.3: "from `ACTIVE`, the window runs from ninety days before
    the `expiration_date` through the `expiration_date` itself, both ends
    inclusive" and "A successful renewal extends the `expiration_date` by 24
    months, measured from the prior expiration. The compliance period rolls
    forward with it: `ce_period_start` becomes the prior `ce_period_end`, and
    `ce_period_end` becomes the new `expiration_date`. Both progress counters,
    `ce_completed_hours` and `ce_ethics_completed_hours`, reset to zero, and
    `renewed_count` increases by one".

    Design: Difficulty/non_linear_state_machine/license_expiry_renewal_cycle
    """
    bundle = setup_producer_with_license(
        npn="NPN-2005", expiration_date="2026-09-01T00:00:00Z",
        ce_required_hours=0, ce_ethics_required_hours=0,
    )
    license_ = bundle["license"]
    # Default clock 2026-08-01 is inside the window [2026-06-03, 2026-09-01].
    renewed = validate_success(
        api_client.renew_license(
            license_["id"], {"expected_license_version": license_["version"]}, LC
        ),
        200,
    )
    assert_license(renewed)
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewed_count"] == 1
    assert_instant_equals(
        renewed["expiration_date"], "2028-09-01T00:00:00Z",
        "expiration_date extended by 24 months",
    )
    assert_instant_equals(
        renewed["ce_period_start"], "2026-09-01T00:00:00Z",
        "ce_period_start becomes the prior ce_period_end",
    )
    assert_instant_equals(
        renewed["ce_period_end"], "2028-09-01T00:00:00Z",
        "ce_period_end becomes the new expiration_date",
    )
    assert renewed["ce_completed_hours"] == 0
    assert renewed["ce_ethics_completed_hours"] == 0


def test_license_expired_grace_renewal_closes_cycle():
    """PRD section 2.5: "Every license still `ACTIVE` whose `expiration_date`
    lies strictly before the new time transitions to `EXPIRED`".
    PRD section 3.3: "from `EXPIRED`, a grace leg runs from strictly after the
    `expiration_date` through thirty days past it, the far end inclusive" and
    "A renewal from `EXPIRED` additionally restores the status to `ACTIVE`;
    its period and counter resets are identical to an in-window renewal."

    Design: Difficulty/non_linear_state_machine/license_expiry_renewal_cycle
    """
    bundle = setup_producer_with_license(
        npn="NPN-2006", expiration_date="2026-09-01T00:00:00Z",
        ce_required_hours=0, ce_ethics_required_hours=0,
    )
    license_id = bundle["license"]["id"]
    first = validate_success(
        api_client.renew_license(
            license_id,
            {"expected_license_version": bundle["license"]["version"]},
            LC,
        ),
        200,
    )
    assert_instant_equals(first["expiration_date"], "2028-09-01T00:00:00Z")

    # One second past the new expiration: the sweep expires the license.
    advance_clock("2028-09-02T00:00:00Z")
    expired = get_license(license_id)
    assert expired["status"] == "EXPIRED"

    # 2028-09-02 is inside the grace leg (2028-09-01, 2028-10-01].
    renewed = validate_success(
        api_client.renew_license(
            license_id, {"expected_license_version": expired["version"]}, LC
        ),
        200,
    )
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewed_count"] == 2
    assert_instant_equals(
        renewed["expiration_date"], "2030-09-01T00:00:00Z",
        "second renewal extends the prior expiration by another 24 months",
    )


def test_renew_revoked_license_rejected_invalid_state():
    """PRD section 3.3: "Attempting to renew a license in any other status —
    `SUSPENDED` or `REVOKED` — is a plain state error, `ERR_INVALID_STATE`."
    PRD section 2.9: state checks are evaluated before the business-safety
    gates ("Business-safety gates follow"), so the renewal on a REVOKED license
    reports `ERR_INVALID_STATE` even though the CE determination would also
    fail (zero hours against the default 24/3 requirement).

    Design: Difficulty/priority_pair_validation_conflict/renew_revoked_beats_ce_incomplete
    """
    bundle = setup_confirmed_license_action(
        npn="NPN-2009", action_type="REVOCATION", lines_of_authority=("LIFE",),
        ce_required_hours=24, ce_ethics_required_hours=3,
    )
    license_now = get_license(bundle["license"]["id"])
    assert license_now["status"] == "REVOKED"

    resp = api_client.renew_license(
        bundle["license"]["id"],
        {"expected_license_version": license_now["version"]},
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_license(bundle["license"]["id"])
    assert after["renewed_count"] == 0
    assert after["status"] == "REVOKED"


def test_renew_suspended_license_rejected_invalid_state():
    """PRD section 2.9: "the target record simply is not in a state from which
    the requested transition exists — renewing a `REVOKED` or `SUSPENDED`
    license, closing an `OPEN` inquiry, reviewing an already-terminal CE credit
    — the generic rejection is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/renew_revoked_beats_ce_incomplete
    """
    bundle = setup_confirmed_license_action(
        npn="NPN-2010", action_type="SUSPENSION", lines_of_authority=("LIFE",),
        ce_required_hours=24, ce_ethics_required_hours=3,
    )
    license_now = get_license(bundle["license"]["id"])
    assert license_now["status"] == "SUSPENDED"

    resp = api_client.renew_license(
        bundle["license"]["id"],
        {"expected_license_version": license_now["version"]},
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_license(bundle["license"]["id"])
    assert after["renewed_count"] == 0
    assert after["status"] == "SUSPENDED"


def test_renewal_window_closed_before_window_and_after_grace():
    """PRD section 3.3: "the renewal window must be open: from `ACTIVE`, the
    window runs from ninety days before the `expiration_date` through the
    `expiration_date` itself, both ends inclusive; from `EXPIRED`, a grace leg
    runs from strictly after the `expiration_date` through thirty days past it,
    the far end inclusive. Outside both legs the renewal is rejected with
    `ERR_RENEWAL_WINDOW_CLOSED`."

    Design: Corner/validations/renewal_window_closed_on_both_legs_rejected
    """
    producer = create_producer(npn="NPN-3026", full_name="Window Check")
    ca_license = create_license(
        producer_id=producer["id"], state_code="CA",
        expiration_date="2028-01-01T00:00:00Z",
        ce_required_hours=0, ce_ethics_required_hours=0,
    )
    nv_license = create_license(
        producer_id=producer["id"], state_code="NV", license_class="NON_RESIDENT",
        issue_date="2025-01-01T00:00:00Z", expiration_date="2026-07-01T00:00:00Z",
        ce_required_hours=0, ce_ethics_required_hours=0,
    )

    # Sweep: the NV license (expired 2026-07-01) goes EXPIRED; CA stays ACTIVE.
    advance_clock("2026-08-02T00:00:00Z")
    nv_now = get_license(nv_license["id"])
    assert nv_now["status"] == "EXPIRED"

    # ACTIVE leg: clock 2026-08-02 is before the window open 2027-10-03.
    early = api_client.renew_license(
        ca_license["id"], {"expected_license_version": ca_license["version"]}, LC
    )
    validate_error(early, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)

    # EXPIRED leg: grace closed at 2026-07-31; clock 2026-08-02 is past it.
    late = api_client.renew_license(
        nv_license["id"], {"expected_license_version": nv_now["version"]}, LC
    )
    validate_error(late, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)


def test_license_reinstate_from_revoked_rejected():
    """PRD section 3.3: "`REVOKED` is terminal" and "Reinstatement is the
    regulatory cure, reserved for a `ComplianceOfficer`: a `SUSPENDED` license
    returns to `ACTIVE` with a version increment."
    PRD section 2.9: "Where no domain-specific error applies and the target
    record simply is not in a state from which the requested transition exists
    — renewing a `REVOKED` or `SUSPENDED` license, closing an `OPEN` inquiry,
    reviewing an already-terminal CE credit — the generic rejection is
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/license_reinstate_from_revoked_rejected
    """
    bundle = setup_confirmed_license_action(
        npn="NPN-3009", action_type="REVOCATION", lines_of_authority=("LIFE",),
    )
    resp = api_client.reinstate_license(bundle["license"]["id"], OFFICER_B)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_license(bundle["license"]["id"])["status"] == "REVOKED"


def test_stale_version_occ_license_renew_rejected():
    """PRD section 2.8: "Renewing a license requires the non-optional field
    `expected_license_version`, carrying the `version` of the license the
    client last observed."
    PRD section 2.8: "In both cases, if the value does not match the record's
    current `version` — because another write, such as a CE-credit acceptance
    recomputing the license's counters or a clock sweep moving the inquiry to
    `OVERDUE`, has legitimately advanced it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite state it has
    not observed."

    Design: Corner/cross_cutting_layers/stale_version_occ_license_renew_rejected
    """
    bundle = setup_producer_with_license(
        npn="NPN-3035", expiration_date="2026-09-01T00:00:00Z",
        ce_required_hours=0, ce_ethics_required_hours=0,
    )
    license_ = bundle["license"]
    observed_version = license_["version"]

    stale = api_client.renew_license(
        license_["id"], {"expected_license_version": observed_version - 1}, LC
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    renewed = validate_success(
        api_client.renew_license(
            license_["id"], {"expected_license_version": observed_version}, LC
        ),
        200,
    )
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewed_count"] == 1
    assert renewed["version"] == observed_version + 1


def test_license_at_exact_expiration_instant_not_swept():
    """PRD section 2.5: "The platform never consults wall-clock time. All
    deadlines, windows, and time-stamped transitions are evaluated against a
    logical clock whose startup value is exactly 2026-08-01T00:00:00Z"
    PRD section 2.5: "Every license still `ACTIVE` whose `expiration_date`
    lies strictly before the new time transitions to `EXPIRED` — a license
    remains `ACTIVE` through the expiration instant itself."
    PRD section 2.5: "The sweep uses strict comparison throughout: an entity
    whose deadline equals the new clock value exactly is not swept."

    Design: Corner/cross_cutting_layers/license_at_exact_expiration_instant_not_swept
    """
    bundle = setup_producer_with_license(
        npn="NPN-3037", expiration_date="2026-08-01T00:00:00Z",
    )
    license_id = bundle["license"]["id"]

    # No clock call has been made: the startup clock equals the expiration
    # instant exactly, and equality is not expiry.
    at_default = get_license(license_id)
    assert at_default["status"] == "ACTIVE", (
        "startup clock equals the expiration instant; the license is not swept"
    )

    advance_clock("2026-08-01T00:00:00Z")
    at_equal = get_license(license_id)
    assert at_equal["status"] == "ACTIVE", "strict comparison: equality is not swept"

    advance_clock("2026-08-01T00:00:01Z")
    after = get_license(license_id)
    assert after["status"] == "EXPIRED", "one second past expiration is swept"
