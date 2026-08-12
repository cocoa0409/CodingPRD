"""Authentication presence and role authorization (PRD §2.1, §4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_producer_payload,
    get_producer,
    make_cip_cycle,
    make_permit,
    make_run,
    set_clock,
    setup_intake_env,
    setup_releasable_receipt,
    validate_error,
)

PC = TEST_USERS["plant_controller_headers"]
LAB = TEST_USERS["lab_technician_headers"]
OP = TEST_USERS["pasteurizer_operator_headers"]
SI = TEST_USERS["state_inspector_headers"]


def test_missing_auth_headers_401(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. A request missing either header, or carrying a malformed
    value, is rejected with `ERR_MISSING_AUTH`."

    Design: Corner/validations/auth_missing_headers_returns_401
    """
    res = api.list_producers(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH)


def test_lab_technician_cannot_create_producer(api):
    """PRD §2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`." The PRD §4 endpoint
    table authorizes only PlantController for POST /dairy/producers.

    Design: Corner/validations/wrong_role_returns_403
    """
    set_clock()
    res = api.create_producer(
        create_producer_payload(producer_code="PX", farm_name="FX"), LAB
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_state_inspector_cannot_release_receipt(api):
    """PRD §2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`." The PRD §4 endpoint
    table authorizes only QualityAssuranceManager for POST
    /dairy/tanker-receipts/{id}/release.

    Design: Corner/rbac/state_inspector_cannot_release_receipt
    """
    env = setup_intake_env()
    receipt = setup_releasable_receipt(env["producer"]["id"], env["hauler"]["id"])
    producer = get_producer(env["producer"]["id"])

    res = api.release_tanker_receipt(
        receipt["id"], {"expected_producer_version": producer["version"]}, SI
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_pasteurizer_operator_cannot_validate_cip(api):
    """PRD §2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`." The PRD §4 endpoint
    table authorizes only QualityAssuranceManager for POST
    /dairy/pasteurizer-runs/{runId}/cip-cycles/{id}/validate.

    Design: Corner/rbac/pasteurizer_operator_cannot_validate_cip
    """
    set_clock()
    make_permit()
    run = make_run()
    cip = make_cip_cycle(run["id"], started_at="2026-05-09T08:00:00Z")

    res = api.validate_cip_cycle(run["id"], cip["id"], {}, OP)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
