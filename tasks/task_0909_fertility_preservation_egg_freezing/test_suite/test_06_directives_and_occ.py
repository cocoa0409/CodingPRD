"""Consent/disposition directives: revocation state guard, and the optimistic-concurrency
control (ERR_STALE_VERSION) and supersede semantics on directive creation.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_directive_payload,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


def test_revoke_already_revoked_directive_invalid_state(api):
    """PRD §3.6: "A patient may also revoke one of their own active directives, moving it from
    ACTIVE to REVOKED; revocation is permitted only while the directive is ACTIVE and only when
    the acting patient owns it."

    Design: Corner/state_machines/revoke_already_revoked_directive_returns_invalid_state
    """
    patient = fx.create_patient()
    p_headers = fx.make_patient_headers(patient["id"])
    v1 = fx.get_patient_version(patient["id"])
    dir_id = fx.get_success_data(api.create_directive(
        create_directive_payload(patient["id"], v1, directive_type="CONSENT"), p_headers))["id"]
    validate_success(api.revoke_directive(dir_id, p_headers), 200)
    resp = api.revoke_directive(dir_id, p_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_directive_create_with_stale_version_rejected(api):
    """PRD §2.8: "A create-directive request must carry expected_patient_version, the version
    of the target Patient the client last observed. If that value does not match the patient's
    current version, the request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_directive_returns_stale
    """
    patient = fx.create_patient()
    p_headers = fx.make_patient_headers(patient["id"])
    v1 = patient["version"]
    # First create supersedes nothing but bumps Patient.version to 2.
    validate_success(api.create_directive(
        create_directive_payload(patient["id"], v1, directive_type="CONSENT"), p_headers), 201)
    # Second create still carrying v1 is stale.
    resp = api.create_directive(
        create_directive_payload(patient["id"], v1, directive_type="DISPOSITION",
                                 disposition_action="THAW_TO_SELF"), p_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_directive_create_with_current_version_supersedes_prior(api):
    """PRD §3.6: "Creating a new directive of a given type supersedes the patient's prior active
    directive of that same type: the prior directive's status becomes SUPERSEDED, the new one
    becomes the active directive of that type, and the patient's version is incremented by one
    as part of the create."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_directive_supersedes_prior
    """
    patient = fx.create_patient()
    p_headers = fx.make_patient_headers(patient["id"])
    v1 = patient["version"]
    dir1 = fx.get_success_data(api.create_directive(
        create_directive_payload(patient["id"], v1, directive_type="CONSENT"), p_headers))["id"]
    v2 = fx.get_patient_version(patient["id"])
    resp = api.create_directive(
        create_directive_payload(patient["id"], v2, directive_type="CONSENT"), p_headers)
    dir2 = validate_success(resp, 201)
    prior = validate_success(api.get_directive(dir1, COORD), 200)
    assert prior["status"] == "SUPERSEDED", "prior same-type directive must be SUPERSEDED"
    assert dir2["status"] == "ACTIVE", "new directive must become ACTIVE"
