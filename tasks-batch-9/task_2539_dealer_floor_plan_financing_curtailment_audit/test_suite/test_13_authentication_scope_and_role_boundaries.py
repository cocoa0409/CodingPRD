"""Access control: the header gate, the ownership gate, role exclusivity and duty separation."""
from test_helpers import (
    AM,
    AM2,
    CO,
    CRM,
    FA,
    ApiErrorId,
    api_client,
    assert_aging_exception_request,
    build_user_headers,
    create_dealer,
    credit_line_version,
    decide_aging_exception,
    file_aging_exception,
    fund_advance_payload,
    make_audit_manager_headers,
    make_dealer_principal_headers,
    make_field_auditor_headers,
    move_title_custody,
    observation_payload,
    read_dealer,
    read_unit,
    register_unit,
    request_advance,
    schedule_audit,
    set_clock,
    setup_active_line,
    setup_floored_unit,
    setup_unit_with_due_obligation,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}


def test_a_request_without_an_acting_principal_never_reaches_the_resource():
    """Omitting X-User-ID is a 401 in the error envelope, and the same read with both headers is a 200.

    PRD: "Every request to the service — reads included — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role it is acting in. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration."

    Design: Corner/errors/request_missing_x_user_id_header_returns_unauthenticated
    """
    set_clock("2026-08-01T00:00:00Z")
    dealer = create_dealer(legal_name="Corner Headerless Motors LLC", state_code="WV")

    response = api_client.raw_get(
        f"/floorplan/dealers/{dealer['id']}", headers={"X-User-Role": "CreditOfficer"}
    )
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"]

    authenticated = validate_success(api_client.get_dealer(dealer["id"], CO))
    assert authenticated["id"] == dealer["id"]


def test_a_role_outside_the_six_declared_ones_fails_the_header_gate_not_the_role_gate():
    """FloorManager is not a declared role, so the refusal is 401 and never a 403.

    PRD: "Every request to the service — reads included — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role it is acting in. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration."

    PRD: "The six roles are `DealerPrincipal`, `CreditOfficer`, `CreditRiskManager`, `FieldAuditor`, `AuditManager` and `SystemOperator`. Each endpoint declares the roles permitted to invoke it (see §4); a syntactically valid role that is not on that list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/unrecognized_role_header_is_rejected_before_authorization
    """
    set_clock("2026-08-01T00:00:00Z")
    dealer = create_dealer(legal_name="Corner Unknown Role Motors LLC", state_code="VT")

    validate_error(
        api_client.raw_get(
            f"/floorplan/dealers/{dealer['id']}",
            headers=build_user_headers("u-floor-1", "FloorManager"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    unchanged = read_dealer(dealer["id"])
    assert unchanged["version"] == 1
    assert unchanged["status"] == "PROSPECT"

    _, meta = validate_paginated(api_client.list_credit_lines(CO, params={"dealer_id": dealer["id"]}))
    assert meta["total_count"] == 0


def test_a_dealership_may_not_read_a_sibling_dealerships_record():
    """The ownership rule blocks a plain GET across dealerships while each self-read succeeds.

    PRD: "A `DealerPrincipal` acting on another dealership's resource is refused with `ERR_DEALER_SCOPE_VIOLATION` (HTTP 403), and this applies to read traffic exactly as it applies to writes."

    Design: Corner/errors/dealer_principal_reading_another_dealers_record_is_forbidden
    """
    set_clock("2026-08-01T00:00:00Z")
    first = create_dealer(legal_name="Corner Scope One Motors LLC", state_code="NH")
    second = create_dealer(legal_name="Corner Scope Two Motors LLC", state_code="NH")

    validate_error(
        api_client.get_dealer(second["id"], make_dealer_principal_headers(first["id"])),
        ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
        403,
    )

    own_second = validate_success(
        api_client.get_dealer(second["id"], make_dealer_principal_headers(second["id"]))
    )
    assert own_second["id"] == second["id"]
    own_first = validate_success(
        api_client.get_dealer(first["id"], make_dealer_principal_headers(first["id"]))
    )
    assert own_first["id"] == first["id"]


def test_the_risk_manager_grants_thirty_days_and_the_ladder_is_rewritten():
    """Approval supersedes the matured rung and issues a replacement 30 days later with nothing yet required.

    PRD: "Deciding a request is a `CreditRiskManager` act. The decision payload carries `decision`, either `APPROVE` or `DENY`; `decided_extension_days`, which is required on an approval; and `reason_code`, one of `RELIEF_GRANTED`, `INSUFFICIENT_JUSTIFICATION`, `EXPOSURE_TOO_HIGH` or `DOCUMENTATION_MISSING`."

    PRD: "The request moves `PENDING → APPROVED` with `decided_by_user_id` from `X-User-ID`, `decided_at` from the logical clock and `reason_code` recorded."

    PRD: "The targeted obligation moves to `SUPERSEDED` and a **replacement** obligation is created in `SCHEDULED` whose `supersedes_obligation_id` points at the superseded row, whose `extension_days_applied` is the granted `decided_extension_days`, whose `due_date` is the superseded row's `due_date` plus the granted days, and whose `projected_principal_cents` is copied across unchanged."

    PRD: "The unit's `aging_exception_count` increases by 1 and its `curtailment_extension_days_total` increases by the granted days."

    Design: Corner/rbac/credit_risk_manager_approves_an_aging_exception_and_supersedes_the_obligation
    """
    ctx = setup_unit_with_due_obligation(vin_seed="CRNEXCEPTUNIT001")
    unit_id = ctx["unit"]["id"]
    assert str(ctx["due_date"]).startswith("2026-10-30")
    due_obligation = ctx["obligations"][0]
    assert due_obligation["status"] == "DUE"
    assert str(due_obligation["due_date"])[:10] == "2026-10-30"
    assert due_obligation["required_principal_cents"] == 300000

    request = file_aging_exception(
        due_obligation["id"], ctx["dealer_headers"], 30, "RETAIL_DEAL_PENDING"
    )
    assert_aging_exception_request(request)
    assert request["status"] == "PENDING"
    assert request["requested_by_user_id"] == ctx["dealer"]["id"]

    decided = decide_aging_exception(request["id"], "APPROVE", "RELIEF_GRANTED", 30, CRM)
    assert decided["status"] == "APPROVED"
    assert decided["decided_extension_days"] == 30
    assert decided["decided_by_user_id"] == CRM["X-User-ID"]
    assert str(decided["decided_at"]).startswith("2026-10-30T00:00:00")
    assert decided["reason_code"] == "RELIEF_GRANTED"

    superseded = validate_success(
        api_client.get_curtailment_obligation(due_obligation["id"], CRM)
    )
    assert superseded["status"] == "SUPERSEDED"

    replacement = validate_success(
        api_client.get_curtailment_obligation(decided["replacement_obligation_id"], CRM)
    )
    assert replacement["status"] == "SCHEDULED"
    assert replacement["supersedes_obligation_id"] == due_obligation["id"]
    assert replacement["extension_days_applied"] == 30
    assert str(replacement["due_date"])[:10] == "2026-11-29"
    assert replacement["required_principal_cents"] == 0
    assert replacement["late_fee_cents"] == 0
    assert replacement["projected_principal_cents"] == 300000

    unit_after = read_unit(unit_id)
    assert unit_after["aging_exception_count"] == 1
    assert unit_after["curtailment_extension_days_total"] == 30

    rows, meta = validate_paginated(
        api_client.list_curtailment_obligations(
            CRM, params={"supersedes_obligation_id": due_obligation["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == replacement["id"]


def test_an_auditor_holding_a_perfect_payload_still_cannot_wire_the_money():
    """Funding is exclusive to the credit officer, so the auditor is stopped before any arithmetic.

    PRD: "No role is a superset of another. There is no administrative override and no escalation path: a `CreditOfficer` cannot reconcile an audit, an `AuditManager` cannot fund an advance, and a `CreditRiskManager` cannot record a physical observation. All three attempts produce `ERR_UNAUTHORIZED`."

    PRD: "Disbursement is a `CreditOfficer` act on an advance still in `REQUESTED` — any other advance status is refused with `ERR_ADVANCE_NOT_PENDING`."

    Design: Corner/rbac/field_auditor_cannot_fund_an_advance_and_is_denied
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={
            "legal_name": "Corner Role Denied Motors LLC",
            "state_code": "WA",
        },
    )
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "CRNROLEDENYUNT01",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-C32")
    advance = request_advance(unit["id"], ctx["dealer_headers"], 3000000, "INV-C32")
    version = credit_line_version(line_id)

    payload = fund_advance_payload(version, "WIRE-C32")
    validate_error(
        api_client.fund_advance(advance["id"], payload, FA),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    still_requested = validate_success(api_client.get_funding_advance(advance["id"], CO))
    assert still_requested["status"] == "REQUESTED"
    assert still_requested["funded_by_user_id"] is None
    blocked_unit = read_unit(unit["id"])
    assert blocked_unit["funding_status"] == "PENDING_FUNDING"
    assert blocked_unit["advance_amount_cents"] == 0
    assert credit_line_version(line_id) == version

    funded = validate_success(api_client.fund_advance(advance["id"], payload, CO))
    assert funded["status"] == "FUNDED"
    assert funded["funded_by_user_id"] == CO["X-User-ID"]


def test_the_operator_who_walked_the_lot_cannot_countersign_his_own_count():
    """One identifier wearing both hats is caught by the counting-versus-signing-off separation.

    PRD: "Recording also sets `observed_by_user_id` from `X-User-ID` and appends that identifier to the audit's `observer_user_ids` if it is not already there, preserving first-observation order."

    PRD: "The counting-versus-signing-off separation of §2.9 requires that the reconciling `X-User-ID` not appear in the audit's `observer_user_ids`, or the request is refused with `ERR_SOD_AUDIT_RECONCILER`."

    PRD: "An operator identifier that appears in an audit's `observer_user_ids` may never reconcile that audit. Violation yields `ERR_SOD_AUDIT_RECONCILER`. Because counting is a `FieldAuditor` capability and reconciliation an `AuditManager` capability, this check only bites when the same `X-User-ID` is presented under both roles — which is precisely the abuse it exists to stop."

    Design: Corner/rbac/the_operator_who_counted_the_lot_cannot_sign_off_the_reconcile
    """
    ctx = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNSODUNITAA0001",
        unit_overrides={"invoice_amount_cents": 3000000},
        dealer_overrides={"legal_name": "Corner SoD Motors LLC", "state_code": "ID"},
    )
    dealer_id = ctx["dealer"]["id"]
    audit = schedule_audit(dealer_id, "2026-08-01", "2026-08-03", audit_type="UNANNOUNCED")
    dual_hat_headers = make_field_auditor_headers(AM["X-User-ID"])
    start_audit(audit["id"], headers=dual_hat_headers)

    observation = validate_success(
        api_client.record_observation(
            audit["id"],
            observation_payload(ctx["unit"]["id"], "PRESENT", True),
            dual_hat_headers,
        ),
        201,
    )
    assert observation["classification"] == "VERIFIED"
    assert observation["observed_by_user_id"] == AM["X-User-ID"]
    counted = validate_success(api_client.get_audit(audit["id"], AM))
    assert counted["observer_user_ids"] == [AM["X-User-ID"]]

    validate_error(
        api_client.reconcile_audit(
            audit["id"],
            {"notes": "self sign-off attempt"},
            make_audit_manager_headers(AM["X-User-ID"]),
        ),
        ApiErrorId.ERR_SOD_AUDIT_RECONCILER,
        403,
    )

    unsigned = validate_success(api_client.get_audit(audit["id"], AM))
    assert unsigned["status"] == "IN_PROGRESS"
    assert unsigned["reconciled_at"] is None
    assert unsigned["reconciled_by_user_id"] is None
    assert unsigned["sot_exposure_cents"] == 0
    assert read_dealer(dealer_id)["audit_in_progress"] is True

    signed = validate_success(
        api_client.reconcile_audit(
            audit["id"], {"notes": "self sign-off attempt"}, AM2
        )
    )
    assert signed["status"] == "RECONCILED_CLEAN"
    assert signed["reconciled_by_user_id"] == AM2["X-User-ID"]
