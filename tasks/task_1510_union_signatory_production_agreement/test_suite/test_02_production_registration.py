"""Production registration, tier caps, bond auto-creation, and listings (PRD §3.2)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def test_get_unknown_production_returns_not_found(api):
    """PRD §2.4: "Path `id` parameters and foreign-key references in request
    bodies ... are resolved before business rules run; a reference to a
    non-existent resource is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/production_get_not_found_returns_404
    """
    company = th.register_company("Dovetail LLC", "20-0000004")
    resp = api.get_production(th.NON_EXISTENT_UUID, th.owner_headers(company))
    th.validate_error(resp, E.ERR_RESOURCE_NOT_FOUND)


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with `response_type` "error" and a `data` object
    where "The `error_id` is a unique, machine-readable string that identifies
    the specific error" and "The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    company = th.register_company("Rosebay LLC", "20-0000045")
    resp = api.get_production(th.NON_EXISTENT_UUID, th.owner_headers(company))
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("response_type") == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert th.is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["data"]["error_id"] == "ERR_RESOURCE_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_production_create_auto_creates_pending_bond(api):
    """PRD §3.2: "Creation has one automatic side effect: exactly one bond is
    created for the production in status `PENDING`, its `amount_required_cents`
    set from the per-tier bond schedule keyed on the production's current tier."
    PRD §2.7: "2,500,000 cents for `ULTRA_LOW_BUDGET`". PRD §3.2: "The bond
    keeps a running ledger — `total_posted_cents`, `total_released_cents`, and
    `total_forfeited_cents` all start at zero."

    Design: Corner/entities/bond_auto_created_with_tier_requirement
    """
    company, _ = th.create_signatory_company("Elmwood LLC", "20-0000005")
    production = th.create_production(company, "Elm Row")

    data, meta = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    assert len(data) == 1, "exactly one bond is auto-created per production"
    bond = data[0]
    th.assert_bond(bond)
    assert bond["status"] == "PENDING"
    assert bond["amount_required_cents"] == 2_500_000
    assert bond["amount_held_cents"] == 0
    assert bond["total_posted_cents"] == 0
    assert bond["total_released_cents"] == 0
    assert bond["total_forfeited_cents"] == 0


def test_tier_cap_exceeded_at_create_but_exact_cap_passes(api):
    """PRD §3.2: "a budget above the selected tier's cap is rejected with
    `ERR_TIER_CAP_EXCEEDED` (HTTP 422), while a budget exactly equal to the cap
    passes."
    PRD §2.7: "`ULTRA_LOW_BUDGET` covers budgets up to 30,000,000 cents" and
    "The cap boundary is inclusive — a budget exactly equal to a tier's cap is
    covered by that tier."

    Design: Corner/validations/tier_cap_exceeded_at_create_rejected
    """
    company, _ = th.create_signatory_company(
        "Pepperroot LLC", "20-0000043", slate=30_000_000,
    )
    resp = api.create_production(
        th.create_production_payload(
            producer_company_id=company["id"], title="Over Cap",
            agreement_tier="ULTRA_LOW_BUDGET", budget_cents=30_000_100,
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_TIER_CAP_EXCEEDED)

    data = th.validate_success(
        api.create_production(
            th.create_production_payload(
                producer_company_id=company["id"], title="At Cap",
                agreement_tier="ULTRA_LOW_BUDGET", budget_cents=30_000_000,
            ),
            th.owner_headers(company),
        ),
        expected_status=201,
    )
    assert data["status"] == "REGISTERED", "budget == cap is allowed"


def test_create_response_carries_status_posture_version(api):
    """PRD §3.2: "A new production starts in `REGISTERED` with
    `compliance_posture` `CLEAR` and `pre_suspension_status` null."
    PRD §2.4: "`version` is an integer that starts at 1 on creation".
    PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_visibility_of_computed_fields_on_create
    """
    company, _ = th.create_signatory_company(
        "Dropwort LLC", "20-0000056", scope="NEW_MEDIA",
    )
    resp = api.create_production(
        th.create_production_payload(producer_company_id=company["id"],
                                     title="Dropwort Dell"),
        th.owner_headers(company),
    )
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    data = body["data"]
    th.assert_production(data)
    assert data["status"] == "REGISTERED"
    assert data["compliance_posture"] == "CLEAR"
    assert data["version"] == 1


def test_productions_list_pagination(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned: it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100.
    `offset` sets the number of items skipped and defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/productions_list_pagination_envelope
    """
    company, _ = th.create_signatory_company("Galewood LLC", "20-0000007", slate=60_000_000)
    for title in ("P1", "P2", "P3"):
        th.create_production(company, title, budget=10_000_000)

    page1, meta1 = th.validate_paginated(
        api.list_company_productions(
            company["id"], th.owner_headers(company),
            params={"limit": 2, "offset": 0},
        )
    )
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2

    page2, meta2 = th.validate_paginated(
        api.list_company_productions(
            company["id"], th.owner_headers(company),
            params={"limit": 2, "offset": 2},
        )
    )
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert len(page2) == 1


def test_crew_create_with_unknown_production_returns_not_found(api):
    """PRD §2.4: "Path `id` parameters and foreign-key references in request
    bodies — `producer_company_id`, `production_id`, `crew_assignment_id`, and
    each element of `work_day_log_ids` — are resolved before business rules
    run; a reference to a non-existent resource is rejected with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/fk_integrity_crew_assignment_unknown_production_rejected
    """
    company = th.register_company("Fernhill LLC", "20-0000006")
    resp = api.create_crew_assignment(
        th.create_crew_assignment_payload(production_id=th.NON_EXISTENT_UUID),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_RESOURCE_NOT_FOUND)


def test_pending_company_production_create_rejected(api):
    """PRD §3.2: "Only a `SIGNATORY` company may register a production: the
    `ProducerRep` supplies `producer_company_id`, `title`, `agreement_tier`,
    and `budget_cents`, and if the named company is not `SIGNATORY` the request
    fails with `ERR_COMPANY_NOT_SIGNATORY` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/production_create_requires_signatory_company
    """
    company = th.register_company("Pine Vale LLC", "13-0000002")
    th.create_application(company)  # DRAFT, never submitted — company stays PENDING

    resp = api.create_production(
        th.create_production_payload(producer_company_id=company["id"],
                                     title="Pine Vale One"),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_COMPANY_NOT_SIGNATORY)


def test_signatory_company_production_create_succeeds(api):
    """PRD §3.2: "Only a `SIGNATORY` company may register a production" — the
    identical request that failed while `PENDING` succeeds once approval moves
    the company to `SIGNATORY` (PRD §3.1: "Approval moves the application to
    `APPROVED`; if the company is still `PENDING`, the company transitions to
    `SIGNATORY`"). A new production starts `REGISTERED` (PRD §3.2).

    Design: Difficulty/cross_entity_state_dependency/production_create_requires_signatory_company
    """
    company = th.register_company("Pine Vale LLC", "13-0000002")
    application = th.create_application(company)
    th.submit_application(application, company)
    th.approve_application(application)

    data = th.validate_success(
        api.create_production(
            th.create_production_payload(producer_company_id=company["id"],
                                         title="Pine Vale One"),
            th.owner_headers(company),
        ),
        expected_status=201,
    )
    th.assert_production(data)
    assert data["status"] == "REGISTERED"


def test_fundtrustee_cannot_create_production(api, fund_trustee_headers):
    """PRD §2.1: "A request whose role is authenticated but not on the target
    endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." PRD §4: POST `/union-compliance/productions` is authorized
    for `ProducerRep` only.

    Design: Corner/rbac/fundtrustee_cannot_create_production
    """
    company, _ = th.create_signatory_company("Sanicle LLC", "20-0000046")
    resp = api.create_production(
        th.create_production_payload(producer_company_id=company["id"],
                                     title="Sanicle One"),
        fund_trustee_headers,
    )
    th.validate_error(resp, E.ERR_UNAUTHORIZED_ROLE)
