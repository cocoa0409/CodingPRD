"""Difficulty rule 5 — validation priority conflicts (PRD §3.3, §3.5).

Five-percent-owner vs rate-exceeds on enroll (PRD commits an explicit order); and
not-certified vs stale-version on run-purchase (PRD does not explicitly commit which
pre-empts, so the accepted-error set is used).
"""
from test_helpers import (
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    create_enrollment_payload,
    create_purchase_period_payload,
    create_offering_payload,
    create_plan_payload,
    create_participant_payload,
    run_purchase_payload,
    api_client,
    make_participant_headers,
    make_admin_headers,
)


def test_five_percent_owner_beats_rate_exceeds(api, admin_headers):
    """PRD §3.3: "the system first rejects an employee flagged as a five-percent owner
    with ERR_FIVE_PERCENT_OWNER (HTTP 422), because Section 423 bars such an owner
    from participating; then it rejects an employee whose status is not ACTIVE with
    ERR_PARTICIPANT_NOT_ACTIVE (HTTP 422); then it rejects a contribution_rate_pct
    that is not greater than 0 or that exceeds the plan's max_contribution_rate_pct
    with ERR_RATE_EXCEEDS_LIMIT (HTTP 422)".

    A five-percent owner enrolling at rate 99% violates both; the explicitly-earlier
    five-percent check wins.

    Design: Difficulty/priority_pair_validation_conflict/five_percent_owner_beats_rate_exceeds_on_enroll
    """
    plan = get_success_data(
        api.create_plan(create_plan_payload(max_contribution_rate_pct=15), admin_headers)
    )
    owner = get_success_data(
        api.create_participant(
            create_participant_payload(is_five_percent_owner=True), admin_headers
        )
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    resp = api.create_enrollment(
        create_enrollment_payload(owner["id"], offering["id"], contribution_rate_pct=99),
        make_participant_headers(owner["id"]),
    )
    validate_error(resp, "ERR_FIVE_PERCENT_OWNER")


def test_five_percent_owner_beats_rate_exceeds_status_422(api, admin_headers):
    """PRD §3.3: "the system first rejects an employee flagged as a five-percent owner
    with ERR_FIVE_PERCENT_OWNER (HTTP 422), because Section 423 bars such an owner
    from participating ... then it rejects a contribution_rate_pct that is not greater
    than 0 or that exceeds the plan's max_contribution_rate_pct with
    ERR_RATE_EXCEEDS_LIMIT (HTTP 422)".

    Second test of the instance: confirm the rejection carries HTTP 422 alongside the
    five-percent error id, not the rate error.

    Design: Difficulty/priority_pair_validation_conflict/five_percent_owner_beats_rate_exceeds_on_enroll
    """
    plan = get_success_data(
        api.create_plan(create_plan_payload(max_contribution_rate_pct=15), admin_headers)
    )
    owner = get_success_data(
        api.create_participant(
            create_participant_payload(is_five_percent_owner=True), admin_headers
        )
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    resp = api.create_enrollment(
        create_enrollment_payload(owner["id"], offering["id"], contribution_rate_pct=99),
        make_participant_headers(owner["id"]),
    )
    validate_error(resp, "ERR_FIVE_PERCENT_OWNER", expected_status=422)


def _open_uncertified_batch(api, admin_headers, officer_headers):
    """ENROLLMENT_CLOSED offering with a batch opened to OPEN (not certified).
    Returns (batch_id, current_version)."""
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    get_success_data(api.close_enrollment(offering["id"], admin_headers))
    batch = get_success_data(
        api.create_purchase_period(
            offering["id"], create_purchase_period_payload(), admin_headers
        )
    )
    opened = get_success_data(api.open_purchase_period(batch["id"], admin_headers))
    return batch["id"], opened["version"]


def test_not_certified_with_stale_version_on_open_batch(api, admin_headers):
    """PRD §3.5: "The batch must be CERTIFIED; a run attempted against a batch in any
    other state is rejected with ERR_NOT_CERTIFIED (HTTP 409). The supplied
    expected_purchase_period_version must equal the batch's current version, or the
    run is rejected with ERR_STALE_VERSION (HTTP 412)."

    Running an OPEN (un-certified) batch with a deliberately stale version violates
    both guards. The PRD enumerates the checks but does not explicitly commit which
    pre-empts, so either error id is accepted (error-precedence silence pattern).

    Design: Difficulty/priority_pair_validation_conflict/not_certified_beats_stale_version_on_run_purchase
    """
    batch_id, version = _open_uncertified_batch(api, admin_headers, None)
    resp = api.run_purchase(
        batch_id, run_purchase_payload(version - 1), make_admin_headers("admin2")
    )
    validate_error_is_one_of(resp, ["ERR_NOT_CERTIFIED", "ERR_STALE_VERSION"])


def test_not_certified_with_stale_version_rejected_4xx(api, admin_headers):
    """PRD §3.5: "The batch must be CERTIFIED; a run attempted against a batch in any
    other state is rejected with ERR_NOT_CERTIFIED (HTTP 409). The supplied
    expected_purchase_period_version must equal the batch's current version, or the
    run is rejected with ERR_STALE_VERSION (HTTP 412)."

    Second test of the instance from a different version skew (much larger stale
    value): the run is still rejected with one of the two guard errors.

    Design: Difficulty/priority_pair_validation_conflict/not_certified_beats_stale_version_on_run_purchase
    """
    batch_id, version = _open_uncertified_batch(api, admin_headers, None)
    resp = api.run_purchase(
        batch_id, run_purchase_payload(version + 99), make_admin_headers("admin2")
    )
    validate_error_is_one_of(resp, ["ERR_NOT_CERTIFIED", "ERR_STALE_VERSION"])
