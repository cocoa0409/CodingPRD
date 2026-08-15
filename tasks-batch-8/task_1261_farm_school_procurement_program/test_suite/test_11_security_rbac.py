"""RBAC, entity-backed ownership, validation ordering, and segregation of
duties."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_claim_line,
    api_client,
    build_user_headers,
    create_accepted_delivery,
    create_approved_farm,
    create_approved_invoice,
    create_claim,
    create_farm,
    create_offering,
    create_product,
    create_program_year,
    make_farm_manager_headers,
    make_kitchen_manager_headers,
    schedule_delivery,
    setup_procurement_chain,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_claims_coordinator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
CLAIMS = TEST_USERS["claims_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD section 2.1: "A request missing either header, or presenting a role
    the system does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/errors/err_missing_auth_header_returns_400
    """
    resp = api.list_farms(None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_check_precedes_existence(api):
    """PRD section 2.5: "Inbound requests are validated as an ordered pipeline;
    a request that fails an earlier stage is rejected with that stage's error
    and never reaches later stages."
    PRD section 2.5: "2. **Role permission.** The caller's role must be
    admitted to the endpoint, else `ERR_FORBIDDEN`."

    Design: Corner/validations/val_role_check_precedes_existence
    """
    # FarmManager is not admitted to the approve endpoint at all; the missing
    # farm id is never even resolved.
    resp = api.approve_farm(
        NON_EXISTENT_UUID, make_farm_manager_headers(NON_EXISTENT_UUID)
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_existence_precedes_state(api):
    """PRD section 2.5: "Inbound requests are validated as an ordered pipeline;
    a request that fails an earlier stage is rejected with that stage's error
    and never reaches later stages."
    PRD section 2.5: "3. **Existence.** Path identifiers are resolved left to
    right, then body foreign keys; each resource family reports its own
    not-found error (see §2.6)."

    Design: Corner/validations/val_existence_precedes_state
    """
    resp = api.approve_invoice(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)


def test_farm_manager_cannot_approve_invoice(api):
    """PRD section 2.1: "Each endpoint admits a fixed set of roles (Section
    4); a caller whose role is not admitted to the endpoint is rejected with
    `ERR_FORBIDDEN`."
    PRD section 4: "| POST | `/f2s/invoices/{id}/approve` | Approve a submitted
    invoice; captures the approver's identity | DistrictProgramAdmin |"

    Design: Corner/rbac/rbac_farm_manager_cannot_approve_invoice
    """
    chain = setup_procurement_chain()
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    invoice = validate_success(
        api_client.create_invoice(
            {"delivery_id": delivery["id"], "invoice_number": "INV-1"},
            make_farm_manager_headers(chain.farm["id"]),
        ),
        201,
    )
    farm_headers = make_farm_manager_headers(chain.farm["id"])
    validate_success(api.submit_invoice(invoice["id"], farm_headers), 200)

    resp = api.approve_invoice(invoice["id"], farm_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = validate_success(api.get_invoice(invoice["id"], ADMIN), 200)
    assert after["status"] == "SUBMITTED"


def test_farm_manager_other_farm_ownership_denied(api):
    """PRD section 2.1: "When `X-User-Role` is `FarmManager`, `X-User-ID` is
    the `id` of the acting Farm; ownership checks on any resource that
    references a Farm — a compliance document's `farm_id`, an offering's
    `farm_id`, and the farm reached transitively through an agreement's
    offering or a delivery's agreement — compare that reference to `X-User-ID`,
    and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP`."

    Design: Corner/rbac/rbac_farm_manager_other_farm_ownership_denied
    """
    year = create_program_year()
    product = create_product()
    farm_a = create_approved_farm(legal_name="Farm A", distance_miles_to_hub=30)
    farm_b = create_farm(legal_name="Farm B", distance_miles_to_hub=40, acres=200)

    # Farm A's manager tries to file an offering naming farm B.
    resp = api.create_offering(
        {
            "farm_id": farm_b["id"],
            "program_year_id": year["id"],
            "product_id": product["id"],
            "price_cents_per_unit": 250,
            "max_weekly_quantity": 100,
            "harvest_start_week": 4,
            "harvest_end_week": 12,
        },
        make_farm_manager_headers(farm_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP)


def test_kitchen_manager_other_kitchen_denied(api):
    """PRD section 2.1: "When `X-User-Role` is `KitchenManager`, `X-User-ID` is
    the `id` of the acting Kitchen, and the same comparison applies to
    receiving windows (through `kitchen_id`) and to deliveries addressed to a
    kitchen."

    Design: Corner/rbac/rbac_kitchen_manager_other_kitchen_denied
    """
    chain = setup_procurement_chain()
    other_kitchen = api_client.create_kitchen({"name": "Washington MS"}, ADMIN)
    other_kitchen = validate_success(other_kitchen, 201)
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    # Kitchen B's manager cannot check in a delivery addressed to kitchen A.
    resp = api.check_in_delivery(
        delivery["id"], make_kitchen_manager_headers(other_kitchen["id"])
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP)
    after = validate_success(api.get_delivery(delivery["id"], ADMIN), 200)
    assert after["status"] == "SCHEDULED"


def test_sod_same_user_approve_then_submit_rejected(api):
    """PRD section 3.7: "Submitting the claim (`OPEN` → `SUBMITTED`) requires
    at least one line (`ERR_CLAIM_EMPTY`) and enforces segregation of duties:
    the submitter's `X-User-ID` must differ from the `approved_by_user_id`
    recorded on every line's invoice, failing which submission is rejected with
    `ERR_SOD_VIOLATION`; a successful submission stamps `submitted_by_user_id`
    with the caller's identity."
    PRD section 3.6: "approval moves `SUBMITTED` → `APPROVED` and captures the
    approver's identity in `approved_by_user_id`"

    Design: Corner/rbac/rbac_sod_same_user_approve_then_submit_rejected
    """
    chain = setup_procurement_chain()
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    invoice = create_approved_invoice(
        delivery["id"], chain.farm["id"], "INV-1", approver_user_id="admin-1"
    )
    assert invoice["approved_by_user_id"] == "admin-1"

    claim = create_claim(chain.year["id"], "2026-08")
    add_claim_line(claim["id"], invoice["id"])

    # The same person who approved the invoice cannot submit the claim, even
    # when acting in the ClaimsCoordinator capacity.
    resp = api.submit_claim(claim["id"], make_claims_coordinator_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    # A different coordinator submits successfully.
    submitted = validate_success(
        api.submit_claim(claim["id"], make_claims_coordinator_headers("claims-1")), 200
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "claims-1"


def test_all_roles_can_read(api):
    """PRD section 4: "| GET | `/f2s/program-years` | List program years | All
    roles |"
    PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."

    Design: Corner/rbac/rbac_all_roles_can_read
    """
    create_program_year(open_it=False)
    roles = [
        build_user_headers("admin-1", "DistrictProgramAdmin"),
        build_user_headers(NON_EXISTENT_UUID[:-1] + "1", "FarmManager"),
        build_user_headers(NON_EXISTENT_UUID[:-1] + "2", "KitchenManager"),
        build_user_headers("claims-1", "ClaimsCoordinator"),
        build_user_headers("aud-1", "StateGrantAuditor"),
    ]
    for headers in roles:
        resp = api.list_program_years(headers)
        assert resp.status_code == 200, (
            f"role {headers['X-User-Role']} must read the list, got {resp.status_code}"
        )
        body = resp.json()
        assert body["response_type"] == "array"
