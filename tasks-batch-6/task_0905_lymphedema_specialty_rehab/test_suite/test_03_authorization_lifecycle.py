"""Authorization lifecycle: the cyclic resubmission loop, closed-interval window
overlap, and invalid-transition lockdown.

Queue A: nonlinear_authorization_resubmit_cycle, overlap_auth_window_closed_touching.
Queue B: approve_already_approved_authorization_returns_invalid_state.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    get_success_data,
    create_patient,
    create_authorization,
)

AUTHORIZER = TEST_USERS["authorizer_headers"]


def _denied_authorization(patient_id):
    auth = create_authorization(patient_id, body_region="LEFT_ARM", visit_cap=5)
    get_success_data(_submit(auth["id"]))
    get_success_data(_deny(auth["id"]))
    return auth


def _submit(auth_id):
    from test_helpers import api_client
    return api_client.submit_authorization(auth_id, AUTHORIZER)


def _deny(auth_id):
    from test_helpers import api_client
    return api_client.deny_authorization(auth_id, AUTHORIZER)


# ---- Queue A: nonlinear_authorization_resubmit_cycle (>=2 tests) ----

def test_denied_authorization_can_be_resubmitted(api):
    """PRD §3.3: "the same submit action re-submits a denied authorization, advancing it
    DENIED → SUBMITTED."

    Design: Difficulty/non_linear_state_machine/nonlinear_authorization_resubmit_cycle
    """
    patient = create_patient()
    auth = _denied_authorization(patient["id"])
    data = validate_success(api.submit_authorization(auth["id"], AUTHORIZER))
    assert data["status"] == "SUBMITTED"


def test_resubmitted_authorization_can_be_approved(api):
    """PRD §3.3: "From SUBMITTED, an approve advances it to APPROVED, while a deny
    advances it to DENIED; a denied authorization can be resubmitted, forming the
    resubmission loop."

    Design: Difficulty/non_linear_state_machine/nonlinear_authorization_resubmit_cycle
    """
    patient = create_patient()
    auth = _denied_authorization(patient["id"])
    get_success_data(api.submit_authorization(auth["id"], AUTHORIZER))
    data = validate_success(api.approve_authorization(auth["id"], AUTHORIZER))
    assert data["status"] == "APPROVED"


# ---- Queue A: overlap_auth_window_closed_touching (>=2 tests) ----

def test_authorization_windows_touching_endpoint_overlap(api):
    """PRD §3.3: "the windows are treated as closed intervals, so windows that merely
    touch at an endpoint are considered overlapping."

    Design: Difficulty/resource_temporal_overlap/overlap_auth_window_closed_touching
    """
    patient = create_patient()
    create_authorization(
        patient["id"], body_region="LEFT_ARM", auth_number="AUTH-1",
        effective_start_date="2026-05-01", effective_end_date="2026-06-30",
    )
    resp = api.create_authorization(
        {"patient_id": patient["id"], "body_region": "LEFT_ARM", "payer_name": "Acme Health",
         "auth_number": "AUTH-2", "visit_cap": 5,
         "effective_start_date": "2026-06-30", "effective_end_date": "2026-07-31"},
        AUTHORIZER,
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_OVERLAP)


def test_authorization_windows_not_touching_allowed(api):
    """PRD §3.3: "A new authorization is rejected with ERR_AUTH_WINDOW_OVERLAP if its
    window overlaps that of any existing authorization for the same patient_id and
    body_region whose status is DRAFT, SUBMITTED, APPROVED, or EXHAUSTED; the windows
    are treated as closed intervals, so windows that merely touch at an endpoint are
    considered overlapping."

    Design: Difficulty/resource_temporal_overlap/overlap_auth_window_closed_touching
    """
    patient = create_patient()
    create_authorization(
        patient["id"], body_region="LEFT_ARM", auth_number="AUTH-1",
        effective_start_date="2026-05-01", effective_end_date="2026-06-30",
    )
    # Starting the day after the first window closes does not touch it.
    resp = api.create_authorization(
        {"patient_id": patient["id"], "body_region": "LEFT_ARM", "payer_name": "Acme Health",
         "auth_number": "AUTH-2", "visit_cap": 5,
         "effective_start_date": "2026-07-01", "effective_end_date": "2026-07-31"},
        AUTHORIZER,
    )
    validate_success(resp, expected_status=201)


# ---- Queue B: approve already-approved authorization ----

def test_approve_already_approved_authorization_invalid_state(api):
    """PRD §3.3: "Each of these transitions requires the authorization to be in the
    expected source state and otherwise returns ERR_INVALID_STATE."

    Design: Corner/state_machines/approve_already_approved_authorization_returns_invalid_state
    """
    patient = create_patient()
    auth = create_authorization(patient["id"], body_region="LEFT_ARM", visit_cap=5)
    get_success_data(api.submit_authorization(auth["id"], AUTHORIZER))
    get_success_data(api.approve_authorization(auth["id"], AUTHORIZER))
    validate_error(api.approve_authorization(auth["id"], AUTHORIZER), ApiErrorId.ERR_INVALID_STATE)
    still = get_success_data(api.get_authorization(auth["id"], AUTHORIZER))
    assert still["status"] == "APPROVED"
