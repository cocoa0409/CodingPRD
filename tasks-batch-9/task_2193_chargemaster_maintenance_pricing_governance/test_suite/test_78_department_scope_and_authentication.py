"""The manager's data-scoped authority: same operation, own department versus a peer's, plus 401s."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_department, create_active_item, create_change_request, create_batch,
    set_clock, make_manager_headers, MANAGER_USER_ID, MANAGER2_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-SCOPE",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)
ROLE_ONLY_HEADERS = {"X-User-Role": "DepartmentManager", "Content-Type": "application/json"}
NO_HEADERS = {"Content-Type": "application/json"}


def test_a_manager_owns_one_department_and_a_caller_without_an_identity_is_unauthenticated():
    """PRD §2.1: "Concretely: submitting a change request, resubmitting one, withdrawing one, ingesting a
    charge capture batch, appending a line to a batch, and disputing a reconciled batch all require that
    `X-User-ID` equal the `manager_user_id` of the department named by the request's `department_id`
    (directly on the body, or indirectly via the `ChangeRequest` or the `ChargeCaptureBatch` being acted
    upon)."
    PRD §2.1: "A mismatch is `ERR_DEPARTMENT_SCOPE_VIOLATION` (HTTP 403), evaluated third — after
    authentication and role admission, and before any resource is looked up."
    PRD §2.1: "The same error code covers the narrower ownership rule that a withdrawal or a resubmit may
    only be performed by the user recorded in `submitted_by_user_id`."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six declared role names,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first check performed
    on any request, before path resolution, before schema validation, before anything else."

    Design: Corner/rbac/department_manager_cannot_reach_a_peer_department_and_an_unidentified_caller_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    cath = base["department"]
    radiology = create_department(facility_id, MANAGER2_USER_ID, name="Radiology",
                                  cost_center_code="CC-200")
    cath_manager = make_manager_headers(MANAGER_USER_ID)
    radiology_manager = make_manager_headers(MANAGER2_USER_ID)

    item = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", cost_basis_cents=100000,
                              medicare_rate_cents=50000, market_p75_cents=900000,
                              effective_from="2026-09-01T00:00:00Z")
    assert item["gross_charge_cents"] == 240000

    in_scope = create_change_request(base, item["id"], "PRICE_CHANGE",
                                     justification="In-scope request for the owning department",
                                     proposed_cost_basis_cents=150000)
    assert in_scope["status"] == "SUBMITTED"
    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T23:59:59Z")
    assert batch["status"] == "INGESTED"

    validate_error(
        api_client.create_change_request(
            factories.create_change_request_payload(
                radiology["id"], item["id"], "PRICE_CHANGE",
                justification="Out-of-scope request filed against a peer department",
                proposed_cost_basis_cents=160000), cath_manager),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )
    validate_error(
        api_client.create_charge_capture_batch(
            factories.create_charge_capture_batch_payload(
                facility_id, radiology["id"], window_start_date="2026-09-08T00:00:00Z",
                window_end_date="2026-09-14T23:59:59Z"), cath_manager),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )
    validate_error(
        api_client.create_captured_charge(
            batch["id"],
            factories.create_captured_charge_payload(
                "CDM-1001", encounter_id="ENC-9", payer_code="AETNA",
                service_datetime="2026-09-02T10:00:00Z", quantity=1,
                posted_charge_cents=240000),
            radiology_manager),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )
    validate_error(
        api_client.change_request_decision(
            in_scope["id"],
            {"decision": "WITHDRAW",
             "decision_note": "A peer manager attempting someone else's withdrawal"},
            radiology_manager),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )

    validate_error(
        api_client.create_change_request(
            factories.create_change_request_payload(
                cath["id"], item["id"], "PRICE_CHANGE",
                justification="Caller supplies a role header but no user identity",
                proposed_cost_basis_cents=170000), ROLE_ONLY_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value, 401,
    )
    validate_error(api_client.reprice_charge_item(item["id"], NO_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    read_back = validate_success(
        api_client.get_charge_capture_batch(batch["id"], cath_manager), 200)
    assert read_back["status"] == "INGESTED"
    assert read_back["line_count"] == 0, "no rejected write left a partial line behind"
    rows, meta = validate_paginated(api_client.list_change_requests(
        cath_manager, {"department_id": cath["id"]}))
    assert meta["total_count"] == 1, "only the in-scope request was ever stored"
    assert rows[0]["id"] == in_scope["id"]
    assert validate_paginated(api_client.list_change_requests(
        radiology_manager, {"department_id": radiology["id"]}))[1]["total_count"] == 0
    assert validate_success(
        api_client.get_change_request(in_scope["id"], cath_manager), 200)["status"] == "SUBMITTED"
