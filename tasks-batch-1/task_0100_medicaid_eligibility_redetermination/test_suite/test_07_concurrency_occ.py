"""Optimistic concurrency control on the enrollment-superseding creates
(opening a redetermination, filing an appeal).
"""
from test_helpers import (
    api_client as api,
    TEST_USERS,
    get_success_data, validate_success, validate_error, ApiErrorId,
    setup_active_enrollment,
    create_redetermination_payload,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]


def _eligible_renewal_det(app_id):
    return get_success_data(api.run_determination(app_id, CW))


# ===========================================================================
# Queue B — cross_cutting_complexity_layers corner
# ===========================================================================
def test_occ_stale_enrollment_version_on_redetermination_create():
    """PRD §2.8: "If another writer has advanced the enrollment's `version` since
    then — for example, a prior request already opened a redetermination and moved
    the enrollment from `ACTIVE` to `IN_REDETERMINATION`, bumping its `version` —
    then the supplied `expected_enrollment_version` no longer matches the
    enrollment's current `version`, the client is acting on a stale view, and the
    create is rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_enrollment_version_on_redetermination_create
    """
    hh, app, enr, _member = setup_active_enrollment(state="CA")
    enr_v = enr["version"]
    det = _eligible_renewal_det(app["id"])
    # First redetermination succeeds and bumps the enrollment version.
    get_success_data(api.create_redetermination(
        create_redetermination_payload(enr["id"], det["id"], enr_v), CW))
    # Second create still carries the stale enr_v.
    resp = api.create_redetermination(
        create_redetermination_payload(
            enr["id"], det["id"], enr_v,
            window_open="2026-11-02T00:00:00Z", window_close="2026-12-16T00:00:00Z"),
        CW)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_version_increments_on_redetermination_create():
    """PRD §3.8: "When all checks pass, the create succeeds, the parent enrollment
    cascades from `ACTIVE` to `IN_REDETERMINATION`, and the enrollment's `version`
    increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_redetermination_create
    """
    hh, app, enr, _member = setup_active_enrollment(state="CA")
    enr_v = enr["version"]
    det = _eligible_renewal_det(app["id"])
    redet = validate_success(api.create_redetermination(
        create_redetermination_payload(enr["id"], det["id"], enr_v), CW), 201)
    assert redet["redet_status"] == "INITIATED"
    enr_after = validate_success(api.get_enrollment(enr["id"], CW))
    assert enr_after["coverage_status"] == "IN_REDETERMINATION"
    assert enr_after["version"] == enr_v + 1
