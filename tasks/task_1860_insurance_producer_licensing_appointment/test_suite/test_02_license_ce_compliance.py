"""Licenses and continuing-education compliance: subject exclusivity,
duplicate licenses, CE credit lifecycle, CE input-set filtering, and the
spillover/strict compliance variants (PRD sections 2.6, 2.7, 2.9, 3.1, 3.2, 3.3).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_ce_credit,
    assert_license,
    confirm_regulatory_action,
    create_agency,
    create_license,
    create_license_payload,
    create_producer,
    create_regulatory_action,
    get_license,
    get_success_data,
    report_and_accept_ce_credit,
    report_ce_credit,
    review_ce_credit,
    setup_producer_with_license,
    validate_error,
    validate_success,
    advance_clock,
    LICENSING_COORDINATOR_USER_ID,
    RENEWAL_WINDOW_CLOCK,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]


def test_license_invalid_loa_enum_rejected():
    """PRD section 3.1: a license takes "a non-empty `lines_of_authority`
    subset drawn from `LIFE`, `ACCIDENT_HEALTH`, `PROPERTY`, `CASUALTY`, and
    `PERSONAL_LINES`". PRD section 2.9: "any request that is malformed in
    itself — a missing required field, an invalid enum value, a malformed
    datetime, a non-positive `credit_hours`, an `expiration_date` not strictly
    after `issue_date`, or a uniqueness collision on a producer's `npn` or an
    inquiry's `reference_number` — is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/license_invalid_enum_rejected
    """
    producer = create_producer(npn="NPN-3002", full_name="Enum Check")
    resp = api_client.create_license(
        create_license_payload(producer_id=producer["id"],
                               lines_of_authority=["VOID_MAGIC"]),
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_license_subject_conflict_rejected():
    """PRD section 2.6: "On each of them, precisely one of `producer_id` or
    `agency_id` must be set: a record naming both, or neither, is rejected with
    `ERR_LICENSE_SUBJECT_CONFLICT` (HTTP 422)."

    Design: Corner/validations/license_subject_conflict_rejected
    """
    agency = create_agency(name="Subj Agency")
    producer = create_producer(npn="NPN-3019", full_name="Subj Producer")
    resp = api_client.create_license(
        create_license_payload(producer_id=producer["id"], agency_id=agency["id"]),
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_SUBJECT_CONFLICT)


def test_duplicate_license_rejected_until_revoked():
    """PRD section 3.1: "At most one non-terminal license may exist per subject
    and state — any license whose status is not `REVOKED` counts as
    non-terminal — and creating a second is rejected with
    `ERR_DUPLICATE_LICENSE` (HTTP 409)."
    PRD section 3.7: "The matching license — same subject, same `state_code` —
    moves from `ACTIVE` to `SUSPENDED`, or from `ACTIVE` (or already
    `SUSPENDED`) to `REVOKED`."

    Design: Corner/validations/duplicate_license_rejected
    """
    producer = create_producer(npn="NPN-3020", full_name="Dup License")
    first = create_license(producer_id=producer["id"])

    dup = api_client.create_license(
        create_license_payload(producer_id=producer["id"],
                               issue_date="2026-02-01T00:00:00Z",
                               expiration_date="2028-02-01T00:00:00Z"),
        LC,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_LICENSE)

    action = create_regulatory_action(
        producer_id=producer["id"], state_code="CA", action_type="REVOCATION",
        effective_date="2026-08-01T00:00:00Z",
    )
    confirm_regulatory_action(action["id"])
    assert get_license(first["id"])["status"] == "REVOKED"

    second = validate_success(
        api_client.create_license(
            create_license_payload(producer_id=producer["id"],
                                   issue_date="2026-02-01T00:00:00Z",
                                   expiration_date="2028-02-01T00:00:00Z"),
            LC,
        ),
        201,
    )
    assert_license(second)
    assert second["status"] == "ACTIVE"


def test_ce_credit_on_agency_license_rejected():
    """PRD section 2.6: "reporting a CE credit against an agency-held license
    is rejected with `ERR_CE_NOT_APPLICABLE`."

    Design: Corner/validations/ce_credit_on_agency_license_rejected
    """
    agency = create_agency(name="CE Agency")
    agency_license = create_license(
        agency_id=agency["id"], ce_required_hours=0, ce_ethics_required_hours=0
    )
    resp = api_client.create_ce_credit(
        {
            "license_id": agency_license["id"],
            "provider_name": "CEU",
            "course_title": "X",
            "category": "GENERAL",
            "credit_hours": 5,
            "completed_on": "2026-06-01T00:00:00Z",
        },
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_CE_NOT_APPLICABLE)


def test_ce_credit_accept_recomputes_license_counters():
    """PRD section 3.2: "A newly reported credit starts in `REPORTED` status"
    and "A `LicensingCoordinator` reviews each `REPORTED` credit by submitting
    a `decision` of `ACCEPT` or `REJECT`, moving it to `ACCEPTED` or `REJECTED`
    — both terminal. The review records the coordinator's identity in
    `reviewed_by_user_id`. On either outcome the license's CE counters are
    recomputed; an acceptance can change them (and therefore increments the
    license's `version`)".
    PRD section 3.2: "its `ce_completed_hours` displays the combined
    ethics-plus-general total capped at `ce_required_hours`."

    Design: Corner/state_machines/ce_credit_accept_recomputes_license_counters
    """
    bundle = setup_producer_with_license(npn="NPN-3006")
    license_id = bundle["license"]["id"]
    version_before = bundle["license"]["version"]

    credit = report_ce_credit(
        license_id, course_title="Gen 10", category="GENERAL", credit_hours=10
    )
    assert_ce_credit(credit)
    assert credit["status"] == "REPORTED"

    reviewed = review_ce_credit(credit["id"], "ACCEPT")
    assert reviewed["status"] == "ACCEPTED"
    assert reviewed["reviewed_by_user_id"] == LICENSING_COORDINATOR_USER_ID

    license_after = get_license(license_id)
    assert license_after["ce_completed_hours"] == 10
    assert license_after["ce_ethics_completed_hours"] == 0
    assert license_after["version"] == version_before + 1, (
        "acceptance recomputes the counters and increments the license version"
    )


def test_ce_credit_double_review_rejected():
    """PRD section 3.2: "Reviewing a credit that is already terminal is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/ce_credit_double_review_rejected
    """
    bundle = setup_producer_with_license(npn="NPN-3007")
    credit = report_and_accept_ce_credit(
        bundle["license"]["id"], course_title="Gen 10", credit_hours=10
    )

    resp = api_client.review_ce_credit(credit["id"], {"decision": "REJECT"}, LC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = get_success_data(api_client.get_ce_credit(credit["id"], LC))
    assert reread["status"] == "ACCEPTED", "terminal state must be unchanged"


def test_ce_input_set_excludes_reported_and_out_of_period():
    """PRD section 3.2: "The input set is the license's `ACCEPTED` credits
    whose `completed_on` falls within the current compliance period — from
    `ce_period_start` through `ce_period_end`, both ends inclusive; `REPORTED`
    and `REJECTED` credits are excluded."
    PRD section 3.3: "Third, the CE determination of §3.2 must come out
    `COMPLIANT`, else `ERR_CE_INCOMPLETE`."

    Design: Corner/calculations/ce_input_set_excludes_reported_and_out_of_period
    """
    bundle = setup_producer_with_license(npn="NPN-3015")
    license_id = bundle["license"]["id"]

    # 20 GENERAL hours inside the period: counted.
    report_and_accept_ce_credit(
        license_id, course_title="In", category="GENERAL", credit_hours=20,
        completed_on="2026-06-01T00:00:00Z",
    )
    # 4 GENERAL hours completed before the period start: excluded.
    report_and_accept_ce_credit(
        license_id, course_title="Early", category="GENERAL", credit_hours=4,
        completed_on="2025-12-15T00:00:00Z",
    )
    # 5 ETHICS hours left REPORTED (never reviewed): excluded.
    report_ce_credit(
        license_id, course_title="Pending", category="ETHICS", credit_hours=5,
        completed_on="2026-06-01T00:00:00Z",
    )

    advance_clock(RENEWAL_WINDOW_CLOCK)
    license_now = get_license(license_id)
    assert license_now["ce_completed_hours"] == 20
    assert license_now["ce_ethics_completed_hours"] == 0

    resp = api_client.renew_license(
        license_id, {"expected_license_version": license_now["version"]}, LC
    )
    validate_error(resp, ApiErrorId.ERR_CE_INCOMPLETE)


def test_ce_spillover_variant_resident_renewal_succeeds():
    """PRD section 3.2: "For a `RESIDENT` license, the spillover variant
    applies: all accepted hours count toward the total."
    PRD section 3.2: "The license is `COMPLIANT` exactly when the combined
    ethics-plus-general total is at least `ce_required_hours` and the ethics
    total is at least `ce_ethics_required_hours`." With 20 GENERAL + 5 ETHICS
    against 24/3, the combined total is 25 >= 24 and 5 >= 3, so the renewal
    succeeds.
    PRD section 3.3: "Both progress counters, `ce_completed_hours` and
    `ce_ethics_completed_hours`, reset to zero, and `renewed_count` increases
    by one".

    Design: Difficulty/dual_variant_calc/ce_spillover_vs_strict_variant_divergence
    """
    bundle = setup_producer_with_license(
        npn="NPN-2001", state_code="CA", license_class="RESIDENT",
        lines_of_authority=("LIFE",),
    )
    license_id = bundle["license"]["id"]
    report_and_accept_ce_credit(
        license_id, course_title="Gen 20", category="GENERAL", credit_hours=20
    )
    report_and_accept_ce_credit(
        license_id, course_title="Eth 5", category="ETHICS", credit_hours=5,
        completed_on="2026-06-02T00:00:00Z",
    )

    advance_clock(RENEWAL_WINDOW_CLOCK)
    license_now = get_license(license_id)
    # Spillover display: combined 25 capped at 24; ethics 5 capped at 3.
    assert license_now["ce_completed_hours"] == 24
    assert license_now["ce_ethics_completed_hours"] == 3

    renewed = validate_success(
        api_client.renew_license(
            license_id, {"expected_license_version": license_now["version"]}, LC
        ),
        200,
    )
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewed_count"] == 1


def test_ce_strict_variant_non_resident_renewal_rejected():
    """PRD section 3.2: "For a `NON_RESIDENT` license, the strict variant
    applies: ethics hours count only toward the ethics sub-requirement."
    PRD section 3.2: "The license is `COMPLIANT` exactly when the general total
    alone is at least the total requirement minus the ethics requirement, and
    the ethics total is at least `ce_ethics_required_hours`." With 20 GENERAL +
    5 ETHICS against 24/3, the general total 20 falls short of 24 - 3 = 21, so
    the determination is not COMPLIANT.
    PRD section 3.3: "Third, the CE determination of §3.2 must come out
    `COMPLIANT`, else `ERR_CE_INCOMPLETE`."

    Design: Difficulty/dual_variant_calc/ce_spillover_vs_strict_variant_divergence
    """
    bundle = setup_producer_with_license(
        npn="NPN-2002", state_code="AZ", license_class="NON_RESIDENT",
        lines_of_authority=("LIFE",),
    )
    license_id = bundle["license"]["id"]
    report_and_accept_ce_credit(
        license_id, course_title="Gen 20", category="GENERAL", credit_hours=20
    )
    report_and_accept_ce_credit(
        license_id, course_title="Eth 5", category="ETHICS", credit_hours=5,
        completed_on="2026-06-02T00:00:00Z",
    )

    advance_clock(RENEWAL_WINDOW_CLOCK)
    license_now = get_license(license_id)
    # Strict display: min(ethics, 3) + general = 3 + 20 = 23; ethics capped at 3.
    assert license_now["ce_completed_hours"] == 23
    assert license_now["ce_ethics_completed_hours"] == 3

    resp = api_client.renew_license(
        license_id, {"expected_license_version": license_now["version"]}, LC
    )
    validate_error(resp, ApiErrorId.ERR_CE_INCOMPLETE)

    license_after = get_license(license_id)
    assert license_after["renewed_count"] == 0
    assert license_after["status"] == "ACTIVE"


def test_ce_exact_threshold_counters():
    """PRD section 2.7: "Hour comparisons in the compliance determination are
    exact, and every threshold in that determination is inclusive — a producer
    whose hours equal a requirement exactly has met it." At exactly 21 GENERAL
    + 3 ETHICS against a 24/3 requirement, the spillover display shows the
    combined total (24) and the ethics total (3) with nothing capped away.

    Design: Difficulty/boundary_precision_check/ce_hours_exact_threshold_passes
    """
    bundle = setup_producer_with_license(npn="NPN-2011")
    license_id = bundle["license"]["id"]
    report_and_accept_ce_credit(
        license_id, course_title="Gen 21", category="GENERAL", credit_hours=21
    )
    report_and_accept_ce_credit(
        license_id, course_title="Eth 3", category="ETHICS", credit_hours=3,
        completed_on="2026-06-02T00:00:00Z",
    )

    license_now = get_license(license_id)
    assert license_now["ce_completed_hours"] == 24, (
        "exact threshold: combined 21 + 3 = 24 with no margin"
    )
    assert license_now["ce_ethics_completed_hours"] == 3


def test_ce_exact_threshold_renewal_succeeds():
    """PRD section 2.7: "every threshold in that determination is inclusive —
    a producer whose hours equal a requirement exactly has met it."
    PRD section 3.3: "Third, the CE determination of §3.2 must come out
    `COMPLIANT`, else `ERR_CE_INCOMPLETE`." Exactly 24.0 total hours and 3.0
    ethics hours against a 24/3 requirement is COMPLIANT, so the in-window
    renewal succeeds.

    Design: Difficulty/boundary_precision_check/ce_hours_exact_threshold_passes
    """
    bundle = setup_producer_with_license(npn="NPN-2012")
    license_id = bundle["license"]["id"]
    report_and_accept_ce_credit(
        license_id, course_title="Gen 21", category="GENERAL", credit_hours=21
    )
    report_and_accept_ce_credit(
        license_id, course_title="Eth 3", category="ETHICS", credit_hours=3,
        completed_on="2026-06-02T00:00:00Z",
    )

    advance_clock(RENEWAL_WINDOW_CLOCK)
    license_now = get_license(license_id)
    renewed = validate_success(
        api_client.renew_license(
            license_id, {"expected_license_version": license_now["version"]}, LC
        ),
        200,
    )
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewed_count"] == 1
