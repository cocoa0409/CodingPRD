"""Policy applications: the license gate at approval, decline-and-forfeit,
the suspended-producer gate, and the premium floor (PRD sections 2.5, 2.9,
3.1, 3.5, 3.8).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_application,
    create_application_payload,
    create_producer,
    get_application,
    get_entry_for_application,
    get_license,
    setup_jit_scenario,
    setup_producer_with_active_appointment,
    setup_suspended_producer,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]


def _setup_expired_license_with_submitted_application(npn: str) -> dict:
    """Producer with a CA LIFE license expiring 2027-01-01 and one SUBMITTED
    application; after the sweep to 2027-02-01 the license is EXPIRED (and the
    just-in-time appointment has lapsed)."""
    bundle = setup_jit_scenario(
        npn=npn, state_code="CA", line_of_authority="LIFE",
        premium_cents=5_000_000, expiration_date="2027-01-01T00:00:00Z",
    )
    advance_clock("2027-02-01T00:00:00Z")
    return bundle


def test_approve_rejected_when_license_expired():
    """PRD section 3.5: "Approving requires the producer to hold an `ACTIVE`
    license in the application's state covering its line, else
    `ERR_LICENSE_NOT_ACTIVE`". PRD section 2.5: "Every license still `ACTIVE`
    whose `expiration_date` lies strictly before the new time transitions to
    `EXPIRED`".

    Design: Difficulty/cross_entity_state_dependency/application_approve_requires_license_active
    """
    bundle = _setup_expired_license_with_submitted_application("NPN-2014")
    assert get_license(bundle["license"]["id"])["status"] == "EXPIRED"

    resp = api_client.decide_application(
        bundle["application"]["id"], {"decision": "APPROVE"}, LC
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


def test_failed_approve_leaves_application_submitted_then_decline_forfeits():
    """PRD section 3.5: "Approving requires the producer to hold an `ACTIVE`
    license in the application's state covering its line, else
    `ERR_LICENSE_NOT_ACTIVE`" — the rejected approval leaves the application
    `SUBMITTED` — and "Declining moves it to `DECLINED` — terminal — and
    forfeits its commission entry regardless of the entry's then-current
    non-terminal status, after which the producer's held-commission total is
    recomputed."

    Design: Difficulty/cross_entity_state_dependency/application_approve_requires_license_active
    """
    bundle = _setup_expired_license_with_submitted_application("NPN-2015")
    app_id = bundle["application"]["id"]

    blocked = api_client.decide_application(app_id, {"decision": "APPROVE"}, LC)
    validate_error(blocked, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)
    assert get_application(app_id)["status"] == "SUBMITTED", (
        "the failed guard leaves the application untouched"
    )

    declined = validate_success(
        api_client.decide_application(app_id, {"decision": "DECLINE"}, LC), 200
    )
    assert declined["status"] == "DECLINED"
    assert get_entry_for_application(app_id)["status"] == "FORFEITED"


def test_suspended_producer_submission_rejected():
    """PRD section 3.5: "The producer must be `ACTIVE` at submission, else
    `ERR_PRODUCER_SUSPENDED`." PRD section 2.9: business-safety gates are
    evaluated before the fiscal floor ("Finally come the fiscal floor on
    submission premium (`ERR_PREMIUM_BELOW_MINIMUM`, HTTP 422)"), so a
    suspended producer submitting a below-minimum premium is reported as
    `ERR_PRODUCER_SUSPENDED`.

    Design: Difficulty/priority_pair_validation_conflict/suspended_producer_beats_premium_minimum
    """
    bundle = setup_suspended_producer(npn="NPN-2016", reference_number="INQ-2016")
    assert bundle["producer"]["status"] == "SUSPENDED"

    resp = api_client.create_application(
        create_application_payload(
            bundle["producer"]["id"], state_code="TX", line_of_authority="LIFE",
            applicant_name="Cheap", premium_cents=100,
        ),
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCER_SUSPENDED)


def test_suspended_producer_submission_creates_no_application():
    """PRD section 3.5: "The producer must be `ACTIVE` at submission, else
    `ERR_PRODUCER_SUSPENDED`." A rejected submission creates nothing: the
    producer's application list stays empty.

    Design: Difficulty/priority_pair_validation_conflict/suspended_producer_beats_premium_minimum
    """
    bundle = setup_suspended_producer(npn="NPN-2017", reference_number="INQ-2017")
    producer_id = bundle["producer"]["id"]

    resp = api_client.create_application(
        create_application_payload(
            producer_id, state_code="TX", line_of_authority="LIFE",
            applicant_name="Cheap", premium_cents=100,
        ),
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCER_SUSPENDED)

    data, meta = validate_paginated(
        api_client.list_applications(LC, params={"producer_id": producer_id})
    )
    assert data == [], "the rejected call must not create an application"
    assert meta["total_count"] == 0


def test_decline_forfeits_commission_entry():
    """PRD section 3.5: "Declining moves it to `DECLINED` — terminal — and
    forfeits its commission entry regardless of the entry's then-current
    non-terminal status, after which the producer's held-commission total is
    recomputed."

    Design: Corner/state_machines/decline_forfeits_commission_entry
    """
    bundle = setup_producer_with_active_appointment(
        npn="NPN-3014", lines_of_authority=("LIFE",),
    )
    application = submit_application(
        bundle["producer"]["id"], state_code="CA", line_of_authority="LIFE",
        applicant_name="D", premium_cents=1_000_000,
    )
    entry = get_entry_for_application(application["id"])
    assert entry["status"] == "PAYABLE", "ELIGIBLE business starts PAYABLE"

    declined = validate_success(
        api_client.decide_application(application["id"], {"decision": "DECLINE"}, LC),
        200,
    )
    assert declined["status"] == "DECLINED"
    assert get_entry_for_application(application["id"])["status"] == "FORFEITED"


def test_premium_below_minimum_boundary():
    """PRD section 3.5: "the written `premium_cents`, which must be at least
    500 cents (five dollars); anything less is rejected with
    `ERR_PREMIUM_BELOW_MINIMUM` (HTTP 422)."

    Design: Corner/validations/premium_below_minimum_rejected
    """
    producer = create_producer(npn="NPN-3025", full_name="Min Premium",
                               resident_state_code="TX")
    too_low = api_client.create_application(
        create_application_payload(
            producer["id"], state_code="TX", line_of_authority="LIFE",
            applicant_name="Low", premium_cents=499,
        ),
        LC,
    )
    validate_error(too_low, ApiErrorId.ERR_PREMIUM_BELOW_MINIMUM)

    at_floor = validate_success(
        api_client.create_application(
            create_application_payload(
                producer["id"], state_code="TX", line_of_authority="LIFE",
                applicant_name="Edge", premium_cents=500,
            ),
            LC,
        ),
        201,
    )
    assert_application(at_floor)
    assert at_floor["status"] == "SUBMITTED", "the boundary 500 is inclusive"
