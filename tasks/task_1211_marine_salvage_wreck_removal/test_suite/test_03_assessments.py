"""Assessments: supersession, terminal lockdown, segregation of duties, OCC."""
from test_helpers import (
    ApiErrorId,
    assert_assessment,
    create_assessment_payload,
    get_success_data,
    make_operations_director_headers,
    report_casualty,
    submit_assessment,
    validate_error,
    validate_success,
)


def test_assessment_superseded_by_newer_submission(
    api, marine_surveyor_headers, operations_director_headers
):
    """PRD 3.1: "Creating an assessment automatically transitions every sibling
    assessment of the same casualty still in `SUBMITTED` to `SUPERSEDED`
    (bumping each such sibling's `version`), and the creation itself increments
    the casualty's `version` by 1 — which is precisely the drift the next
    surveyor's `expected_casualty_version` must reflect."
    PRD 3.1: "The new assessment opens in `SUBMITTED`, records the creator's
    header identity as `assessor_id`, and receives a `casualty_seq`: a monotone
    sequence number assigned within the casualty at creation, which provides
    deterministic recency ordering and is never derived from resource
    identifiers."

    Design: Corner/state_machines/assessment_superseded_by_newer_submission
    """
    casualty = report_casualty(vessel_name="MV Pax")
    a1 = submit_assessment(casualty["id"], headers=marine_surveyor_headers)
    casualty_mid = get_success_data(
        api.get_casualty(casualty["id"], marine_surveyor_headers)
    )
    assert casualty_mid["version"] == casualty["version"] + 1, (
        "assessment creation increments the casualty version by 1"
    )
    a2 = submit_assessment(
        casualty["id"],
        headers=marine_surveyor_headers,
        pollution_risk_tier="TIER_2",
        wreck_removal_required=True,
        estimated_cost_cents=2_000_000,
    )
    assert_assessment(a2)
    assert a2["status"] == "SUBMITTED"
    assert a2["casualty_seq"] > a1["casualty_seq"], (
        "casualty_seq is monotone within the casualty"
    )
    a1_after = validate_success(
        api.get_assessment(a1["id"], operations_director_headers), 200
    )
    assert a1_after["status"] == "SUPERSEDED"
    casualty_after = get_success_data(
        api.get_casualty(casualty["id"], marine_surveyor_headers)
    )
    assert casualty_after["version"] == casualty_mid["version"] + 1


def test_terminal_assessment_approve_rejected(
    api, marine_surveyor_headers, operations_director_headers
):
    """PRD 3.1: "Once an assessment reaches `APPROVED`, `REJECTED`, or
    `SUPERSEDED` it is terminal, and any further action on it meets
    `ERR_ALREADY_TERMINAL`."
    PRD 2.5: "System-managed fields that capture a specific later event — such
    as `reviewer_id`, ... — remain null until the workflow event that populates
    them occurs"

    Design: Corner/state_machines/terminal_assessment_approve_rejected
    """
    casualty = report_casualty(vessel_name="MV Pax")
    a1 = submit_assessment(casualty["id"], headers=marine_surveyor_headers)
    # A2 supersedes A1.
    submit_assessment(
        casualty["id"],
        headers=marine_surveyor_headers,
        pollution_risk_tier="TIER_2",
        wreck_removal_required=True,
        estimated_cost_cents=2_000_000,
    )
    res = api.approve_assessment(a1["id"], operations_director_headers)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
    a1_after = validate_success(
        api.get_assessment(a1["id"], operations_director_headers), 200
    )
    assert a1_after["status"] == "SUPERSEDED"
    assert a1_after["reviewer_id"] is None, "no reviewer is stamped on a rejected action"


def test_sod_assessment_self_approve_rejected(api, marine_surveyor_headers):
    """PRD 3.1: "Review sits with the `OperationsDirector`, and segregation of
    duties forbids the reviewer from being the author: if `X-User-ID` equals the
    assessment's `assessor_id`, both approval and rejection are rejected with
    `ERR_SOD_VIOLATION`."

    Design: Corner/validations/sod_assessment_self_approve_rejected
    """
    casualty = report_casualty(vessel_name="MV Pax")
    assessment = submit_assessment(casualty["id"], headers=marine_surveyor_headers)
    assert assessment["assessor_id"] == "surveyor-01"
    # Same operator id, acting in the director capacity, attempts the review.
    res = api.approve_assessment(
        assessment["id"], make_operations_director_headers("surveyor-01")
    )
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    after = validate_success(api.get_assessment(assessment["id"], marine_surveyor_headers), 200)
    assert after["status"] == "SUBMITTED"


def test_assessment_create_stale_casualty_version_rejected(api, marine_surveyor_headers):
    """PRD 2.9: "Submitting an incident assessment requires
    `expected_casualty_version` to equal the casualty's current `version`; a
    mismatch is rejected with `ERR_STALE_CASUALTY_VERSION` and HTTP status 412,
    because creating an assessment legitimately supersedes any sibling still
    under review, so a stale writer must re-read before adding another survey."

    Design: Corner/cross_cutting_layers/assessment_create_stale_casualty_version_rejected
    """
    casualty = report_casualty(vessel_name="MV Pax")
    stale_version = casualty["version"]
    a1 = submit_assessment(casualty["id"], headers=marine_surveyor_headers)
    # The first creation advanced the casualty version; reusing the pre-creation
    # reading is stale.
    payload = create_assessment_payload(
        casualty["id"], stale_version,
        pollution_risk_tier="TIER_2", wreck_removal_required=True,
        estimated_cost_cents=2_000_000,
    )
    res = api.create_assessment(payload, marine_surveyor_headers)
    validate_error(res, ApiErrorId.ERR_STALE_CASUALTY_VERSION, expected_status=412)
    a1_after = validate_success(api.get_assessment(a1["id"], marine_surveyor_headers), 200)
    assert a1_after["status"] == "SUBMITTED", "the rejected write supersedes nothing"
    casualty_after = get_success_data(
        api.get_casualty(casualty["id"], marine_surveyor_headers)
    )
    assert casualty_after["version"] == stale_version + 1, (
        "exactly one successful creation advanced the version"
    )
