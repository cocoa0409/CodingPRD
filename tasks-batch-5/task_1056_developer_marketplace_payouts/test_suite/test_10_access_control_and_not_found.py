"""Authentication, role authorisation, resource ownership and the 404 catalogue."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    calculate_batch,
    configure_jurisdiction,
    create_developer,
    create_draft_app,
    create_policy_case_payload,
    create_verified_developer,
    make_developer_headers,
    open_batch,
    set_clock,
    setup_approved_app,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_request_without_identity_headers_is_unauthenticated(api, anonymous_headers):
    """PRD 2.1: "Every request to this API — without exception, including reads — must
    carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the
    capacity in which the caller is acting. If either header is absent, or if
    `X-User-Role` carries a value that is not one of the six declared roles, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_request_without_role_header_returns_unauthenticated
    """
    create_developer(api, legal_name="Anon Probe Co", email="an2@x.test",
                     country_code="US")
    response = api.list_developers(anonymous_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401


def test_review_agent_may_not_open_a_policy_case(api, agent_headers, opener_headers):
    """PRD 2.1: "When both headers are well-formed but the named role does not appear in
    the authorised-role list published for that endpoint in §4, the request is rejected
    with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 3.8: "A `PolicyOfficer` opens a case against a listing by naming the `app_id`, a
    `category` drawn from `FRAUD`, `IP_INFRINGEMENT`, `MALWARE`, `CONTENT` and
    `PAYMENT_ABUSE`, and a `severity` of `LOW`, `MEDIUM` or `HIGH`."

    Design: Corner/rbac/corner_review_agent_cannot_open_policy_case
    """
    developer = create_verified_developer(
        api, legal_name="RBAC Co", email="rb@x.test", country_code="US"
    )
    app = create_draft_app(api, developer["id"], name="RBAC App", category="GAMES",
                           listed_countries=["US"])

    payload = create_policy_case_payload(app["id"], category="MALWARE", severity="HIGH")
    response = api.create_policy_case(payload, agent_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403

    _rows, meta = validate_paginated(
        api.list_policy_cases(opener_headers, {"app_id": app["id"]})
    )
    assert meta["total_count"] == 0


def test_finance_ops_may_not_approve_a_payout_batch(api, finance_headers):
    """PRD 2.1: "Separately, payout-batch approval is reserved to `PlatformAdmin` and is
    unavailable to the `FinanceOps` operator who calculated and submitted the batch; that
    separation is expressed through the role lists in §4 rather than through a dedicated
    error."
    PRD 3.9: "Submission moves the batch `CALCULATED → PENDING_APPROVAL` and records
    `submitted_by_user_id`. Approval is reserved to `PlatformAdmin`, moves the batch
    `PENDING_APPROVAL → APPROVED`, and records `approved_by_user_id`."

    Design: Corner/rbac/corner_finance_ops_cannot_approve_payout_batch
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    calculate_batch(api, batch["id"])
    submitted = submit_batch(api, batch["id"])
    assert submitted["submitted_by_user_id"] == "fin-1"

    response = api.approve_payout_batch(batch["id"], finance_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403

    assert validate_success(
        api.get_payout_batch(batch["id"], finance_headers)
    )["status"] == "PENDING_APPROVAL"


def test_developer_may_not_publish_another_developers_listing(api):
    """PRD 2.1: "Concretely, a `Developer` caller may act on an `App` only when the app's
    `developer_id` equals `X-User-ID`; on a `PricingPlan` only when the plan's owning
    app's `developer_id` equals `X-User-ID`; on a `PolicyCase` only when the case's
    `developer_id` equals `X-User-ID`; and on a `Developer` record only when its `id`
    equals `X-User-ID`. A violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/corner_developer_cannot_publish_another_developers_app
    """
    configure_jurisdiction(api, "US", 0, True)
    intruder = create_verified_developer(
        api, legal_name="Intruder B", email="ib2@x.test", country_code="US"
    )
    ctx = setup_approved_app(
        api,
        plan_overrides={"price_cents": 1000},
        app_overrides={"name": "Owned By A", "category": "GAMES"},
        developer_overrides={"legal_name": "Owner A", "email": "oa@x.test"},
    )

    response = api.publish_app(ctx["app_id"], make_developer_headers(intruder["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert response.status_code == 403

    assert validate_success(
        api.get_app(ctx["app_id"], make_developer_headers(ctx["developer_id"]))
    )["status"] == "APPROVED"


def test_unknown_payout_line_returns_its_own_not_found(api, finance_headers):
    """PRD 2.8: "The error identifier names the missing resource type:
    `ERR_DEVELOPER_NOT_FOUND`, `ERR_APP_NOT_FOUND`, `ERR_REVIEW_SUBMISSION_NOT_FOUND`,
    `ERR_PRICING_PLAN_NOT_FOUND`, `ERR_TAX_JURISDICTION_NOT_FOUND`,
    `ERR_REVENUE_SHARE_TIER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_POLICY_CASE_NOT_FOUND`,
    `ERR_PAYOUT_BATCH_NOT_FOUND`, `ERR_PAYOUT_LINE_NOT_FOUND`,
    `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_TAX_FORM_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/errors/corner_payout_line_unknown_id_not_found
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    response = api.get_payout_line(NON_EXISTENT_UUID, finance_headers)
    validate_error(response, ApiErrorId.ERR_PAYOUT_LINE_NOT_FOUND)
    assert response.status_code == 404


def test_unknown_ledger_entry_returns_its_own_not_found(api, finance_headers):
    """PRD 2.8: "Existence. Every resource named in the URL path exists, validated left to
    right, so that the outermost missing segment is the one reported."
    PRD 2.8: "`ERR_PAYOUT_BATCH_NOT_FOUND`, `ERR_PAYOUT_LINE_NOT_FOUND`,
    `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_TAX_FORM_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/errors/corner_ledger_entry_unknown_id_not_found
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    response = api.get_ledger_entry(NON_EXISTENT_UUID, finance_headers)
    validate_error(response, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND)
    assert response.status_code == 404


def test_every_resource_family_reports_its_own_not_found_error(api, admin_headers):
    """PRD 2.8: "Existence. Every resource named in the URL path exists, validated left to
    right, so that the outermost missing segment is the one reported. The error identifier
    names the missing resource type: `ERR_DEVELOPER_NOT_FOUND`, `ERR_APP_NOT_FOUND`,
    `ERR_REVIEW_SUBMISSION_NOT_FOUND`, `ERR_PRICING_PLAN_NOT_FOUND`,
    `ERR_TAX_JURISDICTION_NOT_FOUND`, `ERR_REVENUE_SHARE_TIER_NOT_FOUND`,
    `ERR_PURCHASE_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND`,
    `ERR_POLICY_CASE_NOT_FOUND`, `ERR_PAYOUT_BATCH_NOT_FOUND`,
    `ERR_PAYOUT_LINE_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or
    `ERR_TAX_FORM_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/errors/corner_remaining_resource_families_return_their_own_not_found_error
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    cases = [
        (api.get_app, ApiErrorId.ERR_APP_NOT_FOUND),
        (api.get_pricing_plan, ApiErrorId.ERR_PRICING_PLAN_NOT_FOUND),
        (api.get_purchase, ApiErrorId.ERR_PURCHASE_NOT_FOUND),
        (api.get_refund, ApiErrorId.ERR_REFUND_NOT_FOUND),
        (api.get_chargeback, ApiErrorId.ERR_CHARGEBACK_NOT_FOUND),
        (api.get_policy_case, ApiErrorId.ERR_POLICY_CASE_NOT_FOUND),
        (api.get_review_submission, ApiErrorId.ERR_REVIEW_SUBMISSION_NOT_FOUND),
        (api.get_payout_batch, ApiErrorId.ERR_PAYOUT_BATCH_NOT_FOUND),
        (api.get_tax_jurisdiction, ApiErrorId.ERR_TAX_JURISDICTION_NOT_FOUND),
        (api.get_tax_form, ApiErrorId.ERR_TAX_FORM_NOT_FOUND),
    ]
    for reader, expected in cases:
        response = reader(NON_EXISTENT_UUID, admin_headers)
        validate_error(response, expected)
        assert response.status_code == 404, f"{expected} must carry HTTP 404"
