"""Segregation-of-duties policies: invalid toxic pair, HARD conflict blocking
approval, and SOFT conflict requiring an override justification.

Derived from PRD §3.1 (toxic pairs), §3.3/§3.4 (SoD evaluation at submit and
approve).
"""
from test_helpers import (
    validate_success, validate_error,
    create_entitlement_payload, create_role_payload, create_identity_payload,
    create_sod_policy_payload, create_grant_payload, create_access_request_payload,
    ApiErrorId,
    TEST_USERS, build_user_headers,
)  # noqa: F401

CATALOG = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["access_manager_headers"]


def test_sod_policy_with_same_entitlement_pair_rejected(api):
    """PRD §3.1: "the two must differ, and a policy whose entitlement_a_id equals
    its entitlement_b_id is rejected with ERR_SOD_PAIR_INVALID."

    POST /sod-policies with entitlement_a_id == entitlement_b_id -> 422
    ERR_SOD_PAIR_INVALID.

    Design: Corner/validations/sod_policy_same_entitlement_pair_rejected
    """
    solo = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Solo", system_code="SO", risk_weight=10), CATALOG), 201)
    resp = api.create_sod_policy(
        create_sod_policy_payload(solo["id"], solo["id"], name="BadPair"), CATALOG)
    validate_error(resp, ApiErrorId.ERR_SOD_PAIR_INVALID.value)


def test_hard_sod_conflict_blocks_approval(api):
    """PRD §3.4: "if any ACTIVE HARD policy is in conflict, approval is blocked
    outright with ERR_SOD_CONFLICT".

    Identity holds entitlement A; the request adds a role bundling B; a HARD
    policy over A/B exists. Approving the submitted request completes the toxic
    pair -> 409 ERR_SOD_CONFLICT (an override cannot push a HARD conflict).

    Design: Corner/validations/hard_sod_conflict_blocks_approval
    """
    ha = validate_success(api.create_entitlement(
        create_entitlement_payload(name="HA", system_code="HA", risk_weight=10), CATALOG), 201)
    hb = validate_success(api.create_entitlement(
        create_entitlement_payload(name="HB", system_code="HB", risk_weight=10), CATALOG), 201)
    validate_success(api.create_sod_policy(
        create_sod_policy_payload(ha["id"], hb["id"], name="HARDab", severity="HARD"), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([hb["id"]], name="RoleHB"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Hi", email="hi@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(ha["id"], identity["version"]), MANAGER), 201)
    mgr = build_user_headers("mgr-d", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)

    apr = build_user_headers("apr-d", "AccessApprover")
    resp = api.approve_access_request(req["id"], {"second_approver_confirmed": True}, apr)
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT.value)


def test_soft_sod_conflict_without_override_rejected(api):
    """PRD §3.4: "if the only conflicts present are SOFT, approval may proceed but
    only when a non-empty sod_override_justification accompanies it, and a missing
    or empty override justification in the presence of a soft conflict is rejected
    with ERR_SOD_OVERRIDE_REQUIRED."

    Identity holds A; request adds role bundling B; a SOFT policy over A/B exists;
    approve omits the override justification -> 422 ERR_SOD_OVERRIDE_REQUIRED.

    Design: Corner/validations/soft_sod_without_override_rejected
    """
    sa = validate_success(api.create_entitlement(
        create_entitlement_payload(name="SA", system_code="SA", risk_weight=10), CATALOG), 201)
    sb = validate_success(api.create_entitlement(
        create_entitlement_payload(name="SB", system_code="SB", risk_weight=10), CATALOG), 201)
    validate_success(api.create_sod_policy(
        create_sod_policy_payload(sa["id"], sb["id"], name="SOFTab", severity="SOFT"), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([sb["id"]], name="RoleSB"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Sfi", email="sfi@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(sa["id"], identity["version"]), MANAGER), 201)
    mgr = build_user_headers("mgr-e", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)

    apr = build_user_headers("apr-e", "AccessApprover")
    resp = api.approve_access_request(req["id"], {}, apr)
    validate_error(resp, ApiErrorId.ERR_SOD_OVERRIDE_REQUIRED.value)
