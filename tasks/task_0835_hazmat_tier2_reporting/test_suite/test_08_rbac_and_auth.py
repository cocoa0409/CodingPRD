"""Authentication headers and role/ownership authorization."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_facility_payload,
    create_chemical_inventory_payload,
    make_regulator_headers,
    make_facility_operator_headers,
    register_facility,
    create_chemical,
    setup_release_with_lepc_notice,
)


# ---------------------------------------------------------------------------
# Corner: validations / facility_create_missing_auth_header_returns_400
# ---------------------------------------------------------------------------
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or its role is not recognized, the
    request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 400)."

    Design: Corner/validations/facility_create_missing_auth_header_returns_400
    """
    resp = api.create_facility(create_facility_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER.value)


# ---------------------------------------------------------------------------
# Corner: rbac / facility_operator_cannot_register_facility_returns_unauthorized
# ---------------------------------------------------------------------------
def test_operator_cannot_register_facility(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or a facility operator attempts to act on a
    facility it does not own — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/facility_operator_cannot_register_facility_returns_unauthorized
    """
    resp = api.create_facility(create_facility_payload(), TEST_USERS["facility_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner: rbac / regulator_cannot_create_inventory_returns_unauthorized
# ---------------------------------------------------------------------------
def test_regulator_cannot_declare_inventory(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or a facility operator attempts to act on a
    facility it does not own — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/regulator_cannot_create_inventory_returns_unauthorized
    """
    facility = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1, physical_state="GAS")
    payload = create_chemical_inventory_payload(
        facility["id"], chemical["id"], max_daily_amount_lbs=100,
        average_daily_amount_lbs=50, days_on_site=10, storage_type="DRUM",
    )
    resp = api.create_chemical_inventory(payload, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner: rbac / operator_cannot_act_on_other_facility_returns_unauthorized
# ---------------------------------------------------------------------------
def test_operator_cannot_declare_inventory_for_other_facility(api):
    """PRD §2.1: "When `X-User-Role` is `FacilityOperator`, `X-User-ID` is the `id`
    of the acting `Facility`; ownership checks on any resource that references a
    facility compare that resource's `facility_id` to `X-User-ID`."

    Design: Corner/rbac/operator_cannot_act_on_other_facility_returns_unauthorized
    """
    facility_a = register_facility()
    facility_b = register_facility()
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1, physical_state="GAS")
    payload = create_chemical_inventory_payload(
        facility_b["id"], chemical["id"], max_daily_amount_lbs=100,
        average_daily_amount_lbs=50, days_on_site=10, storage_type="DRUM",
    )
    # Acting as operator of facility A, but declaring inventory for facility B.
    resp = api.create_chemical_inventory(payload, make_facility_operator_headers(facility_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner: rbac / operator_cannot_acknowledge_notice_returns_unauthorized
# ---------------------------------------------------------------------------
def test_operator_cannot_acknowledge_lepc_notice(api):
    """PRD §3.5: "A `LEPCCoordinator` — and only a `LEPCCoordinator` — acknowledges
    a notice, which sets its `acknowledged` flag to `true`."

    Design: Corner/rbac/operator_cannot_acknowledge_notice_returns_unauthorized
    """
    ctx = setup_release_with_lepc_notice(recipient="SERC", notice_type="VERBAL")
    fac_id = ctx["facility"]["id"]
    resp = api.acknowledge_lepc_notice(ctx["notice"]["id"], make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
