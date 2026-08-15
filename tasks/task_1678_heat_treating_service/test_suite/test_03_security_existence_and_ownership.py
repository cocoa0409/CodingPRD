"""User-context headers, role exclusivity, resource-existence errors, and
customer ownership scoping (PRD §2.1, §2.8, §2.10, §4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_pyrometry_payload,
    make_customer_headers,
    setup_scrapped_order,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
QE = TEST_USERS["quality_engineer"]
AUDITOR = TEST_USERS["nadcap_auditor"]
OPERATOR = TEST_USERS["furnace_operator"]
CALTECH = TEST_USERS["calibration_tech"]


# ---------------------------------------------------------------------------
# Corner: validations / missing_auth_header_returns_400
# ---------------------------------------------------------------------------

def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request carries two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their
    operational capacity."
    PRD §2.1: "A request missing either header, or carrying an empty value for
    one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    res = api.create_customer_account({"name": "NoAuth Co"}, headers={})
    validate_error(
        res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value
    )
    empty = api.create_customer_account(
        {"name": "NoAuth Co"}, headers={"X-User-ID": "", "X-User-Role": ""}
    )
    validate_error(
        empty, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value
    )


# ---------------------------------------------------------------------------
# Corner: rbac / role_denied_for_exclusive_operations
# ---------------------------------------------------------------------------

ROLE_DENIAL_CASES = [
    # (headers, callable) — each invokes an operation reserved for another role
    (
        "customer_create_work_order",
        lambda: api_client.create_work_order(
            {
                "customer_id": NON_EXISTENT_UUID,
                "recipe_id": NON_EXISTENT_UUID,
                "part_quantity": 5,
                "received_weight_lb": 100,
                "declared_value_cents": 500000,
                "processing_charge_cents": 100000,
            },
            make_customer_headers(NON_EXISTENT_UUID),
        ),
    ),
    (
        "auditor_create_furnace",
        lambda: api_client.create_furnace(
            {
                "furnace_code": "F-X",
                "furnace_class": "CLASS_3",
                "max_load_weight_lb": 1000,
                "quench_media_supported": ["OIL"],
            },
            AUDITOR,
        ),
    ),
    (
        "operator_record_pyrometry",
        lambda: api_client.create_pyrometry_record(
            create_pyrometry_payload(NON_EXISTENT_UUID), OPERATOR
        ),
    ),
    (
        "calibration_tech_record_inspection",
        lambda: api_client.create_inspection_test(
            {
                "work_order_id": NON_EXISTENT_UUID,
                "hardness_readings": [40],
                "measured_distortion_in": 0.004,
            },
            CALTECH,
        ),
    ),
    (
        "quality_engineer_create_customer",
        lambda: api_client.create_customer_account({"name": "Nope Co"}, QE),
    ),
]


@pytest.mark.parametrize(
    "case", [c[1] for c in ROLE_DENIAL_CASES], ids=[c[0] for c in ROLE_DENIAL_CASES]
)
def test_role_denied_for_exclusive_operations(api, case):
    """PRD §2.1: "A role attempting an operation reserved for another role is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.8: "The order is: (1) user-context headers present and non-empty
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permitted for the
    endpoint (`ERR_INSUFFICIENT_PERMISSIONS`); (3) customer-ownership scoping
    (`ERR_OWNERSHIP_MISMATCH`); (4) resource existence — path identifiers
    validated left to right, then request-body foreign keys (the
    `ERR_*_NOT_FOUND` family); (5) state-machine preconditions and
    optimistic-concurrency checks (the state errors such as
    `ERR_LOAD_NOT_BUILDING`, plus `ERR_STALE_VERSION`); (6) business safety
    gates — furnace qualification, furnace-class rank, quench-media
    compatibility, segregation of duties; (7) recipe referential consistency —
    approval state, recipe match between order and load, alloy/spec
    uniqueness; (8) temporal rules — rush guarantee window, pyrometry validity
    containment, schedule overlap and purge gap; (9) constraint checks — load
    weight capacity, non-empty load, re-treat ceiling, required fields and
    enum validity; (10) fiscal standing (`ERR_CUSTOMER_CREDIT_HOLD`)."

    Design: Corner/rbac/role_denied_for_exclusive_operations
    """
    res = case()
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# Corner: endpoints / not_found_returns_404_per_resource
# ---------------------------------------------------------------------------

NOT_FOUND_PROBES = [
    ("customer_account", ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
     lambda: api_client.get_customer_account(NON_EXISTENT_UUID, CSR)),
    ("furnace_recipe", ApiErrorId.ERR_RECIPE_NOT_FOUND,
     lambda: api_client.get_furnace_recipe(NON_EXISTENT_UUID, CSR)),
    ("furnace", ApiErrorId.ERR_FURNACE_NOT_FOUND,
     lambda: api_client.get_furnace(NON_EXISTENT_UUID, CSR)),
    ("work_order", ApiErrorId.ERR_WORK_ORDER_NOT_FOUND,
     lambda: api_client.get_work_order(NON_EXISTENT_UUID, CSR)),
    ("load_batch", ApiErrorId.ERR_LOAD_BATCH_NOT_FOUND,
     lambda: api_client.get_load_batch(NON_EXISTENT_UUID, CSR)),
    ("load_assignment", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
     lambda: api_client.get_load_assignment(NON_EXISTENT_UUID, CSR)),
    ("disposition_case", ApiErrorId.ERR_DISPOSITION_CASE_NOT_FOUND,
     lambda: api_client.get_disposition_case(NON_EXISTENT_UUID, CSR)),
    ("liability_claim", ApiErrorId.ERR_CLAIM_NOT_FOUND,
     lambda: api_client.get_liability_claim(NON_EXISTENT_UUID, CSR)),
    ("audit_package", ApiErrorId.ERR_AUDIT_PACKAGE_NOT_FOUND,
     lambda: api_client.get_audit_package(NON_EXISTENT_UUID, CSR)),
    ("pyrometry_record", ApiErrorId.ERR_PYROMETRY_RECORD_NOT_FOUND,
     lambda: api_client.get_pyrometry_record(NON_EXISTENT_UUID, CSR)),
    ("thermocouple_reading", ApiErrorId.ERR_THERMOCOUPLE_READING_NOT_FOUND,
     lambda: api_client.get_thermocouple_reading(NON_EXISTENT_UUID, CSR)),
    ("inspection_test", ApiErrorId.ERR_INSPECTION_TEST_NOT_FOUND,
     lambda: api_client.get_inspection_test(NON_EXISTENT_UUID, CSR)),
]


@pytest.mark.parametrize(
    "resource,expected,probe",
    NOT_FOUND_PROBES,
    ids=[p[0] for p in NOT_FOUND_PROBES],
)
def test_not_found_returns_404_per_resource(api, resource, expected, probe):
    """PRD §2.10: "Reads of a single nonexistent resource fail with that
    resource's specific identifier — `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_RECIPE_NOT_FOUND`, `ERR_FURNACE_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PYROMETRY_RECORD_NOT_FOUND`,
    `ERR_THERMOCOUPLE_READING_NOT_FOUND`, `ERR_INSPECTION_TEST_NOT_FOUND`,
    `ERR_DISPOSITION_CASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or
    `ERR_AUDIT_PACKAGE_NOT_FOUND` as applicable."
    PRD §2.10: "Foreign keys supplied in request bodies must reference
    existing resources, each with its own identifier: `customer_id` surfaces
    `ERR_CUSTOMER_NOT_FOUND`, `recipe_id` surfaces `ERR_RECIPE_NOT_FOUND`,
    `furnace_id` surfaces `ERR_FURNACE_NOT_FOUND`, `work_order_id` surfaces
    `ERR_WORK_ORDER_NOT_FOUND`, and `load_batch_id` surfaces
    `ERR_LOAD_BATCH_NOT_FOUND`."

    Design: Corner/endpoints/not_found_returns_404_per_resource
    """
    res = probe()
    err = validate_error(res, expected.value)
    assert res.status_code == 404
    assert isinstance(err.get("message"), str) and err["message"].strip()


# ---------------------------------------------------------------------------
# Corner: rbac / customer_ownership_scope_enforced
# ---------------------------------------------------------------------------

def test_customer_ownership_scope_enforced(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting CustomerAccount; ownership checks on any resource that
    references a CustomerAccount compare the resource's `customer_id` field to
    `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`
    (HTTP 403)."
    PRD §2.1: "This scoping applies when a `Customer` retrieves a single work
    order, retrieves a single liability claim, or accepts a liability claim."
    PRD §3.8: "From `PENDING`, a claim can be accepted by the customer it
    belongs to — ownership is enforced by comparing `X-User-ID` to the
    claim's `customer_id` (`ERR_OWNERSHIP_MISMATCH`), and a claim no longer
    `PENDING` rejects acceptance with `ERR_CLAIM_NOT_PENDING` (HTTP 409) —
    moving it to `ACCEPTED`."

    Design: Corner/rbac/customer_ownership_scope_enforced
    """
    bundle = setup_scrapped_order(
        customer_overrides={"name": "Owner Co", "liability_tier": "STANDARD"}
    )
    owner = bundle["customer"]
    other = api_client.create_customer_account({"name": "Other Co"}, CSR)
    other_id = validate_success(other, 201)["id"]
    order = bundle["order"]
    claim = bundle["claim"]

    # Owner reads its own work order.
    own = validate_success(
        api.get_work_order(order["id"], make_customer_headers(owner["id"])), 200
    )
    assert own["id"] == order["id"]

    # Non-owner reads are rejected on both resource types.
    res = api.get_work_order(order["id"], make_customer_headers(other_id))
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)
    res = api.get_liability_claim(claim["id"], make_customer_headers(other_id))
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)

    # Non-owner cannot accept the owner's claim; it stays PENDING.
    res = api.accept_liability_claim(
        claim["id"], make_customer_headers(other_id)
    )
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)
    claim_after = validate_success(api.get_liability_claim(claim["id"], CSR), 200)
    assert claim_after["status"] == "PENDING"
