"""Transfer/renewal applications: branch side-effects, deemed approval, OCC, holds."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_application,
    TEST_USERS, make_operator_headers,
    create_application_payload,
)
from test_helpers import (
    create_active_franchise, file_transfer_application, file_renewal_application,
    set_clock, get_franchise, get_franchise_version,
    setup_franchise_in_violation_with_held_app,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ---- Difficulty: application_approve_transfer_branch_side_effects ----
def test_approve_transfer_sets_franchise_transferred(api):
    """PRD 3.8: "for a `TRANSFER` it moves the franchise lifecycle to
    `TRANSFERRED` and sets `operator_name` to the `transferee_name`".

    Design: Difficulty/non_linear_state_machine/application_approve_transfer_branch_side_effects
    """
    fr = create_active_franchise(api)
    app = file_transfer_application(api, fr["id"], transferee_name="NewCo")
    validate_success(api.decide_application(app["id"], {"decision": "APPROVE"}, AUTHORITY), 200)
    franchise = get_franchise(api, fr["id"])
    assert franchise["lifecycle_status"] == "TRANSFERRED"
    assert franchise["operator_name"] == "NewCo"


def test_approve_transfer_marks_application_approved(api):
    """PRD 3.8: "A successful approval sets `status` to `APPROVED` and `decision`
    to `APPROVE`".

    Design: Difficulty/non_linear_state_machine/application_approve_transfer_branch_side_effects
    """
    fr = create_active_franchise(api)
    app = file_transfer_application(api, fr["id"], transferee_name="NewCo")
    data = validate_success(api.decide_application(app["id"], {"decision": "APPROVE"}, AUTHORITY), 200)
    assert_application(data)
    assert data["status"] == "APPROVED"


# ---- Corner: deem_before_deadline_returns_invalid_state ----
def test_deem_before_deadline_returns_invalid_state(api):
    """PRD 3.8: "Deemed approval is defined only from `SUBMITTED` and only when
    the clock is strictly past `decision_deadline`; invoking it at or before that
    deadline, or from any state other than `SUBMITTED`, is rejected as an
    invalid-state condition with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/deem_before_deadline_returns_invalid_state
    """
    fr = create_active_franchise(api)
    app = file_transfer_application(api, fr["id"], transferee_name="NewCo")
    op = make_operator_headers(fr["id"])
    resp = api.deem_application(app["id"], op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---- Corner: deemed_approval_after_deadline_transfers_franchise ----
def test_deemed_approval_after_deadline_transfers(api):
    """PRD 3.8: "A valid deemed approval moves the application to
    `DEEMED_APPROVED` and applies the very same lifecycle side-effects as an
    explicit approval (a `TRANSFER` transfers the franchise and copies the
    transferee name".

    Design: Corner/state_machines/deemed_approval_after_deadline_transfers_franchise
    """
    fr = create_active_franchise(api)
    app = file_transfer_application(api, fr["id"], transferee_name="NewCo")
    set_clock(api, "2026-09-01T00:00:00Z")  # past decision_deadline (submitted 2026-05-01 + 120d)
    op = make_operator_headers(fr["id"])
    data = validate_success(api.deem_application(app["id"], op), 200)
    assert data["status"] == "DEEMED_APPROVED"
    assert get_franchise(api, fr["id"])["lifecycle_status"] == "TRANSFERRED"


# ---- Corner: renewal_deny_reverts_franchise_to_active ----
def test_renewal_deny_reverts_to_active(api):
    """PRD 3.8: "A denial sets `status` to `DENIED` and `decision` to `DENY`; for
    a `RENEWAL`, denial reverts the franchise lifecycle from `RENEWAL_PENDING`
    back to `ACTIVE`."

    Design: Corner/state_machines/renewal_deny_reverts_franchise_to_active
    """
    fr = create_active_franchise(api)
    app = file_renewal_application(api, fr["id"], proposed_term_end_date="2040-01-01")
    data = validate_success(api.decide_application(app["id"], {"decision": "DENY"}, AUTHORITY), 200)
    assert data["status"] == "DENIED"
    assert get_franchise(api, fr["id"])["lifecycle_status"] == "ACTIVE"


# ---- Corner: transfer_without_transferee_returns_error ----
def test_transfer_without_transferee_returns_error(api):
    """PRD 3.8: "A `TRANSFER` application must include the proposed
    `transferee_name`; omitting it is rejected with `ERR_TRANSFEREE_REQUIRED`."

    Design: Corner/validations/transfer_without_transferee_returns_error
    """
    fr = create_active_franchise(api)
    version = get_franchise_version(api, fr["id"])
    op = make_operator_headers(fr["id"])
    payload = create_application_payload(fr["id"], "TRANSFER", version)
    resp = api.create_application(payload, op)
    validate_error(resp, ApiErrorId.ERR_TRANSFEREE_REQUIRED.value, 400)


# ---- Corner: renewal_without_term_returns_error ----
def test_renewal_without_term_returns_error(api):
    """PRD 3.8: "A `RENEWAL` application must include a `proposed_term_end_date`;
    omitting it is rejected with `ERR_TERM_REQUIRED`."

    Design: Corner/validations/renewal_without_term_returns_error
    """
    fr = create_active_franchise(api)
    version = get_franchise_version(api, fr["id"])
    op = make_operator_headers(fr["id"])
    payload = create_application_payload(fr["id"], "RENEWAL", version)
    resp = api.create_application(payload, op)
    validate_error(resp, ApiErrorId.ERR_TERM_REQUIRED.value, 400)


# ---- Corner: franchise_application_stale_version_returns_412 ----
def test_stale_version_returns_412(api):
    """PRD 2.5: "The create request must carry `expected_franchise_version`, which
    must equal the franchise's current `version`. If another writer has advanced
    the franchise's `version` since the client last read it, the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/franchise_application_stale_version_returns_412
    """
    fr = create_active_franchise(api)
    stale_version = fr["version"]
    op = make_operator_headers(fr["id"])
    # First filing bumps the franchise version.
    first = create_application_payload(fr["id"], "TRANSFER", stale_version, transferee_name="NewCo")
    validate_success(api.create_application(first, op), 201)
    # Second filing reuses the now-stale version.
    second = create_application_payload(fr["id"], "TRANSFER", stale_version, transferee_name="OtherCo")
    resp = api.create_application(second, op)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# ---- Corner: franchise_application_supersede_withdraws_prior ----
def test_supersede_withdraws_prior(api):
    """PRD 3.8: "Filing also **supersedes** any prior application still in
    `SUBMITTED` on the same franchise, moving that prior application to
    `WITHDRAWN`."

    Design: Corner/cross_cutting_complexity_layers/franchise_application_supersede_withdraws_prior
    """
    fr = create_active_franchise(api)
    op = make_operator_headers(fr["id"])
    first = create_application_payload(fr["id"], "TRANSFER", fr["version"], transferee_name="NewCo")
    app_a = validate_success(api.create_application(first, op), 201)
    current_version = get_franchise_version(api, fr["id"])
    second = create_application_payload(fr["id"], "TRANSFER", current_version, transferee_name="OtherCo")
    app_b = validate_success(api.create_application(second, op), 201)

    a_after = validate_success(api.get_application(app_a["id"], AUTHORITY), 200)
    b_after = validate_success(api.get_application(app_b["id"], AUTHORITY), 200)
    assert a_after["status"] == "WITHDRAWN"
    assert b_after["status"] == "SUBMITTED"


# ---- Corner: cure_releases_held_applications ----
def test_cure_releases_held_applications(api):
    """PRD 2.7: "When an authority cures the franchise (`IN_VIOLATION` →
    `CURED`), `unresolved_complaint_count` is reset to 0 and every application
    currently `HELD` is released back to `SUBMITTED`."

    Design: Corner/cross_cutting_complexity_layers/cure_releases_held_applications
    """
    fr, app, complaints = setup_franchise_in_violation_with_held_app(api)
    # Precondition: the app is HELD after the franchise went IN_VIOLATION.
    held = validate_success(api.get_application(app["id"], AUTHORITY), 200)
    assert held["status"] == "HELD"

    data = validate_success(api.cure_franchise(fr["id"], AUTHORITY), 200)
    assert data["compliance_status"] == "CURED"
    assert data["unresolved_complaint_count"] == 0
    released = validate_success(api.get_application(app["id"], AUTHORITY), 200)
    assert released["status"] == "SUBMITTED"
