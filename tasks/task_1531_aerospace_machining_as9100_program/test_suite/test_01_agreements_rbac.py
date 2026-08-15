"""Agreement creation, activation, and role-based access control (PRD §2.1, §2.5, §3.1)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_lta,
    create_lta,
    create_lta_payload,
    create_released_po,
    setup_fai_submitted,
    validate_error,
    validate_success,
)


def test_lta_creation_defaults(api):
    """PRD §3.1: "A new agreement starts in `DRAFT` with
    `remaining_ceiling_cents` initialized to the full `ceiling_cents`,
    `consecutive_not_ready_count` at zero, and `last_audit_month` and
    `last_audit_result` unset until the first audit runs."
    PRD §2.4: "`version` (integer): a system-managed integer that increments
    by one with every modification of the resource, serving optimistic
    concurrency control where applicable."

    Design: Corner/entities/lta_creation_defaults
    """
    payload = create_lta_payload()
    resp = api_client.create_lta(payload, TEST_USERS["contracts_manager"])
    lta = validate_success(resp, expected_status=201)
    assert_lta(lta)
    assert lta["status"] == "DRAFT", f"new LTA must start DRAFT, got {lta['status']}"
    assert lta["remaining_ceiling_cents"] == payload["ceiling_cents"], (
        f"remaining_ceiling_cents {lta['remaining_ceiling_cents']} must equal "
        f"ceiling_cents {payload['ceiling_cents']} at creation"
    )
    assert lta["consecutive_not_ready_count"] == 0
    assert lta.get("last_audit_month") is None
    assert lta.get("last_audit_result") is None


def test_lta_activate_happy(api):
    """PRD §3.1: "Activation moves the agreement `DRAFT → ACTIVE`."

    Design: Corner/state_machines/lta_activate_happy
    """
    lta = create_lta()
    resp = api_client.activate_lta(lta["id"], TEST_USERS["contracts_manager"])
    activated = validate_success(resp, expected_status=200)
    assert_lta(activated)
    assert (
        activated["status"] == "ACTIVE"
    ), f"activation must move DRAFT -> ACTIVE, got {activated['status']}"


def test_lta_create_missing_required_field(api):
    """PRD §3.1: "A `ContractsManager` opens one by supplying the
    `customer_name`, a `ceiling_cents` total value ceiling (a positive integer
    number of cents), a `pricing_tiers` table, an `escalation_pct_per_year`
    annual escalation rate, an `award_year` base calendar year, a
    `rebate_tiers` table, and a `committed_monthly_rate_units` committed
    production rate in units per calendar month (also positive)."
    PRD §2.11: "Malformed request payloads — a missing or invalid required
    field, an invalid enum value, an unknown field, or a non-positive quantity
    — fail with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/lta_create_missing_required_field
    """
    payload = create_lta_payload()
    del payload["ceiling_cents"]
    resp = api_client.create_lta(payload, TEST_USERS["contracts_manager"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_lta_create_forbidden_for_mrb_member(api):
    """PRD §2.1: "An attempt to perform an operation outside the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."
    PRD §4: POST /api/ltas is authorized for ContractsManager only.

    Design: Corner/rbac/lta_create_forbidden_for_mrb_member
    """
    resp = api_client.create_lta(
        create_lta_payload(), TEST_USERS["mrb_member"]
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_clock_set_forbidden_for_quality_manager(api):
    """PRD §2.5: "A `SystemAdmin`-only test-driving capability sets the clock
    by supplying a `to_iso8601` instant; the response reports the resulting
    `current_utc` value."
    PRD §2.1: "An attempt to perform an operation outside the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/clock_set_forbidden_for_quality_manager
    """
    resp = api_client.set_clock(
        {"to_iso8601": "2026-08-02T00:00:00Z"}, TEST_USERS["quality_manager"]
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_delegation_grant_forbidden_for_supply_chain(api):
    """PRD §2.1: "A `CustomerQualityRep` represents the customer's quality
    organization: FAI approval and rejection, delegation grants and
    revocations, escape acknowledgement, customer concessions, and source
    inspection."
    PRD §2.1: "An attempt to perform an operation outside the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/delegation_grant_forbidden_for_supply_chain
    """
    bundle = create_released_po()
    po = bundle["po"]
    resp = api_client.create_delegation(
        {
            "po_id": po["id"],
            "inspector_user_id": "insp-9",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        },
        TEST_USERS["supply_chain_manager"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_fai_approve_forbidden_for_inspector(api):
    """PRD §3.4: "A `CustomerQualityRep` approves a `SUBMITTED` inspection to
    `APPROVED` — from any other state, `ERR_FAI_NOT_SUBMITTED` — which pins
    `approved_revision` equal to the inspection's `part_revision`, freezing
    the approved revision at the moment of approval, and supersedes every
    other `APPROVED` inspection of the same `part_number` and `part_revision`,
    moving each to the terminal `SUPERSEDED` state."
    PRD §2.1: "An attempt to perform an operation outside the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/fai_approve_forbidden_for_inspector
    """
    fai = setup_fai_submitted()
    assert fai["status"] == "SUBMITTED"
    resp = api_client.approve_fai(fai["id"], TEST_USERS["quality_inspector_3"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
