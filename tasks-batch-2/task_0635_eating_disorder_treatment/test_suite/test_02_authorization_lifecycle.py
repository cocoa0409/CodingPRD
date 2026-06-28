"""Authorization status lifecycle: the denial/appeal negotiation cycle and the
expiry cascade that drives an admitted admission to discharge-pending.
"""
from test_helpers import (
    validate_success,
    ADMIN,
    REVIEWER,
    fixtures as fx,
)


def test_denial_appeal_cycle_returns_to_denied(api):
    """PRD §3.11: "A `UtilizationReviewer` may appeal a `DENIED` authorization,
    moving it to `APPEALED` (legal only from `DENIED`, else `ERR_INVALID_STATE`);
    from `APPEALED` the negotiation can loop back to `APPROVED` or `DENIED`
    through further reviews."

    Design: Difficulty/non_linear_state_machine/authorization_denial_appeal_cycle
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    auth = fx.create_authorization(admission["id"], facility["id"])
    # PENDING -> DENIED
    validate_success(
        api.create_review(
            {"authorization_id": auth["id"], "facility_id": facility["id"],
             "decision": "DENY"},
            REVIEWER,
        ),
        expected_status=201,
    )
    # DENIED -> APPEALED
    validate_success(api.appeal_authorization(auth["id"], REVIEWER))
    # APPEALED -> DENIED (second deny)
    validate_success(
        api.create_review(
            {"authorization_id": auth["id"], "facility_id": facility["id"],
             "decision": "DENY"},
            REVIEWER,
        ),
        expected_status=201,
    )
    data = validate_success(api.get_authorization(auth["id"], REVIEWER))
    assert data["status"] == "DENIED", f"expected DENIED, got {data['status']}"


def test_appeal_from_denied_moves_to_appealed(api):
    """PRD §3.11: "A `UtilizationReviewer` may appeal a `DENIED` authorization,
    moving it to `APPEALED` (legal only from `DENIED`, else `ERR_INVALID_STATE`)".

    Design: Difficulty/non_linear_state_machine/authorization_denial_appeal_cycle
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    auth = fx.create_authorization(admission["id"], facility["id"])
    validate_success(
        api.create_review(
            {"authorization_id": auth["id"], "facility_id": facility["id"],
             "decision": "DENY"},
            REVIEWER,
        ),
        expected_status=201,
    )
    appealed = validate_success(api.appeal_authorization(auth["id"], REVIEWER))
    assert appealed["status"] == "APPEALED", (
        f"expected APPEALED, got {appealed['status']}"
    )


def test_expiry_cascades_admitted_to_discharge_pending(api):
    """PRD §3.11: "Expiry moves the authorization to `EXPIRED`, and if its parent
    admission is `ADMITTED`, it cascades that admission from `ADMITTED` to
    `DISCHARGE_PENDING`."

    Design: Difficulty/transitive_cascade/authorization_expiry_cascade_depth2_to_admission
    """
    ctx = fx.setup_admitted_admission(window_end_iso="2026-01-08T00:00:00Z")
    auth_id = ctx["authorization"]["id"]
    aid = ctx["admission"]["id"]
    # Advance clock to covered_through (01-08) so the window has passed.
    validate_success(api.set_clock("2026-01-08T00:00:00Z", ADMIN))
    expired = validate_success(api.expire_authorization(auth_id, REVIEWER))
    assert expired["status"] == "EXPIRED", f"expected EXPIRED, got {expired['status']}"
    admission = validate_success(api.get_admission(aid, ADMIN))
    assert admission["clinical_status"] == "DISCHARGE_PENDING", (
        f"expected DISCHARGE_PENDING, got {admission['clinical_status']}"
    )


def test_expire_authorization_moves_to_expired(api):
    """PRD §3.11: "A `UtilizationReviewer` (or `Admin`) may expire an
    authorization whose coverage has elapsed. ... Expiry moves the authorization
    to `EXPIRED`".

    Design: Difficulty/transitive_cascade/authorization_expiry_cascade_depth2_to_admission
    """
    ctx = fx.setup_admitted_admission(window_end_iso="2026-01-08T00:00:00Z")
    auth_id = ctx["authorization"]["id"]
    validate_success(api.set_clock("2026-01-08T00:00:00Z", ADMIN))
    expired = validate_success(api.expire_authorization(auth_id, REVIEWER))
    assert expired["status"] == "EXPIRED"
