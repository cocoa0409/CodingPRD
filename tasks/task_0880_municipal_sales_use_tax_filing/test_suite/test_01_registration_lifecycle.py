"""Registration, account lifecycle, jurisdictions, and RBAC gates."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId,
    create_taxpayer_payload, create_jurisdiction_payload,
    create_audit_payload,
    make_anonymous_headers, make_admin_headers, make_taxpayer_headers,
    make_auditor_headers,
    assert_taxpayer, assert_jurisdiction, assert_remittance,
    register_taxpayer, create_active_taxpayer, create_suspended_taxpayer,
    create_remittance,
)


def test_register_taxpayer_starts_pending_version_one(api):
    """PRD §3.1: "A newly registered taxpayer begins in `account_status` `PENDING`
    with `nexus_status` `NONE`, no `suspend_reason`, and no `activated_at`."
    PRD §2.4: "an integer `version` that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/create_taxpayer_returns_201_pending
    """
    resp = api.create_taxpayer(create_taxpayer_payload(), make_anonymous_headers())
    data = validate_success(resp, expected_status=201)
    assert_taxpayer(data)
    assert data["account_status"] == "PENDING"
    assert data["nexus_status"] == "NONE"
    assert data["version"] == 1


def test_register_taxpayer_missing_filing_frequency_rejected(api):
    """PRD §2.8: "then body well-formedness — required fields present, enum values
    in range, amounts strictly positive where required — reported as `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_taxpayer_missing_required_field
    """
    payload = {"legal_name": "NoFreq", "entity_type": "LLC", "email": "nf@x.com"}
    resp = api.create_taxpayer(payload, make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_get_unknown_taxpayer_not_found(api):
    """PRD §2.9: "an unresolved taxpayer yields `ERR_TAXPAYER_NOT_FOUND`".

    Design: Corner/entities/get_taxpayer_not_found
    """
    resp = api.get_taxpayer(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_TAXPAYER_NOT_FOUND, expected_status=404)


def test_jurisdiction_active_defaults_true(api):
    """PRD §3.2: "a combined rate `rate_bps` that must be at least 0, and an `active`
    flag that defaults to true and governs whether the jurisdiction may be cited on
    new return lines."

    Design: Corner/entities/jurisdiction_active_default_true
    """
    payload = create_jurisdiction_payload()
    payload.pop("active", None)
    resp = api.create_jurisdiction(payload, make_admin_headers())
    data = validate_success(resp, expected_status=201)
    assert_jurisdiction(data)
    assert data["active"] is True


def test_new_remittance_fully_unapplied(api):
    """PRD §3.4: "A new remittance is stamped with `received_at` at the current clock,
    starts with `applied_amount_cents` of 0, and therefore has `unapplied_amount_cents`
    equal to its full `amount_cents` and a null `applied_return_id`."

    Design: Corner/entities/remittance_id_created_at_system_generated
    """
    tp = register_taxpayer(api)
    resp = api.create_remittance(
        {"taxpayer_id": tp["id"], "remittance_type": "PREPAYMENT", "amount_cents": 5000},
        make_taxpayer_headers(tp["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert_remittance(data)
    assert data["applied_amount_cents"] == 0
    assert data["unapplied_amount_cents"] == 5000
    assert data["applied_return_id"] is None


def test_reinstate_suspended_account_returns_to_active(api):
    """PRD §3.1: "Activation is also the reinstatement path: a `SUSPENDED` account
    returns to `ACTIVE`, which clears its `suspend_reason` and bumps `version`
    (a reinstatement does not overwrite the original `activated_at`)."

    Design: Corner/cross_cutting_complexity_layers/reinstate_suspended_account_cycle
    """
    tp = create_suspended_taxpayer(api)
    assert tp["account_status"] == "SUSPENDED"
    resp = api.activate_taxpayer(tp["id"], make_admin_headers())
    data = validate_success(resp, expected_status=200)
    assert data["account_status"] == "ACTIVE"
    assert data["suspend_reason"] is None


def test_taxpayer_cannot_open_audit(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/taxpayer_cannot_open_audit
    """
    tp = create_active_taxpayer(api)
    resp = api.create_audit(
        create_audit_payload(tp["id"]), make_taxpayer_headers(tp["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "When either header is missing on a protected endpoint, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/appeal_decide_missing_auth_headers
    """
    resp = api.create_jurisdiction(create_jurisdiction_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
