"""Foundational records, system fields, defaults, RBAC, and listing basics.

Covers corner-design instances under sections `entities`, `state_machines`
(initial state), and `rbac`.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_client_payload, create_project_payload,
    create_client, create_rate_card, make_client_headers,
    build_user_headers,
)

PM = TEST_USERS["pm_headers"]
AR = TEST_USERS["ar_headers"]


def test_create_client_returns_201_with_system_fields(api):
    """PRD §3.1: "Either a `ProjectManager` or an `AccountsReceivable` operator may
    create one by supplying its `name` and `billing_email`; on creation its `status`
    is `ACTIVE` and its derived `ar_balance_cents` starts at zero."
    PRD §2.4: "version`, an integer that begins at the resource's initial value and
    increments by one on every mutation."

    Design: Corner/entities/create_client_returns_201_with_system_fields
    """
    resp = api.create_client(create_client_payload(name="Acme",
                                                   billing_email="ar@acme.test"), PM)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["ar_balance_cents"] == 0, f"expected 0, got {data['ar_balance_cents']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_get_client_not_found_returns_404(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing resource
    causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_client_not_found_returns_404
    """
    resp = api.get_client(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_project_missing_rate_card_id_returns_invalid_request(api):
    """PRD §2.6: "(4) request-body well-formedness — required fields present, enum
    values legal, the work window's end strictly later than its start, and all integer
    counts at least zero — which fails with `ERR_INVALID_REQUEST`".
    PRD §3.2: "A `ProjectManager` opens a **project** against an existing client and an
    existing rate card, supplying the `client_id`, the `rate_card_id`, and a `name`."

    Design: Corner/entities/create_project_missing_rate_card_id_returns_invalid_request
    """
    client = create_client()
    resp = api.create_project({"client_id": client["id"], "name": "NoRate"}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_project_defaults_rush_and_cert(api):
    """PRD §3.2: "The `rush_tier` selects a delivery-speed surcharge multiplier and is
    one of `STANDARD`, `EXPRESS`, or `SAME_DAY`, defaulting to `STANDARD`. The
    `certification_mode` selects the attestation add-on and is one of `NONE`,
    `CERTIFIED`, or `NOTARIZED`, defaulting to `NONE`."

    Design: Corner/entities/create_project_defaults_rush_and_cert
    """
    client = create_client()
    rate_card = create_rate_card()
    resp = api.create_project(
        create_project_payload(client["id"], rate_card["id"], name="Def"), PM)
    data = validate_success(resp, 201)
    assert data["rush_tier"] == "STANDARD", f"got {data['rush_tier']}"
    assert data["certification_mode"] == "NONE", f"got {data['certification_mode']}"


def test_project_pins_rates_from_rate_card_system_fields(api):
    """PRD §3.2: "At creation the project pins the rate card's two rates into
    `pinned_base_rate_cents_per_word` and `pinned_linguist_rate_cents_per_word`, so
    later edits to the rate card never disturb a project already in flight".

    Design: Corner/entities/project_pins_rates_from_rate_card_system_fields
    """
    client = create_client()
    rate_card = create_rate_card(base_rate_cents_per_word=15,
                                 linguist_rate_cents_per_word=9)
    resp = api.create_project(
        create_project_payload(client["id"], rate_card["id"], name="Pin"), PM)
    data = validate_success(resp, 201)
    assert data["pinned_base_rate_cents_per_word"] == 15, \
        f"got {data['pinned_base_rate_cents_per_word']}"
    assert data["pinned_linguist_rate_cents_per_word"] == 9, \
        f"got {data['pinned_linguist_rate_cents_per_word']}"


def test_create_project_invalid_rush_tier_enum_returns_invalid_request(api):
    """PRD §2.6: "(4) request-body well-formedness — required fields present, enum
    values legal, ... — which fails with `ERR_INVALID_REQUEST`".
    PRD §3.2: "The `rush_tier` selects a delivery-speed surcharge multiplier and is
    one of `STANDARD`, `EXPRESS`, or `SAME_DAY`, defaulting to `STANDARD`."

    Design: Corner/entities/create_project_invalid_rush_tier_enum_returns_invalid_request
    """
    client = create_client()
    rate_card = create_rate_card()
    resp = api.create_project(
        create_project_payload(client["id"], rate_card["id"], name="Bad",
                               rush_tier="OVERNIGHT"), PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_ratecard_immutable_no_version_field(api):
    """PRD §2.4: "A `RateCard` is immutable configuration and a `PayoutLedgerEntry` is
    an append-only event record; both carry only `id` and `created_at`. Neither carries
    `updated_at` and neither carries `version`, because neither is ever mutated after
    creation."

    Design: Corner/entities/ratecard_immutable_no_version_field
    """
    resp = api.create_rate_card({
        "source_locale": "en-US", "target_locale": "de-DE",
        "base_rate_cents_per_word": 15, "linguist_rate_cents_per_word": 9,
    }, PM)
    data = validate_success(resp, 201)
    assert "created_at" in data, "RateCard must carry created_at"
    assert "version" not in data, "RateCard must NOT carry version (immutable)"
    assert "updated_at" not in data, "RateCard must NOT carry updated_at (immutable)"


def test_new_project_starts_in_draft(api):
    """PRD §3.2: "A new project's `status` is `DRAFT` and its `quoted_total_cents` is
    null until it is quoted."

    Design: Corner/state_machines/new_project_starts_in_draft
    """
    client = create_client()
    rate_card = create_rate_card()
    resp = api.create_project(
        create_project_payload(client["id"], rate_card["id"], name="P1"), PM)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", f"got {data['status']}"
    assert data["quoted_total_cents"] is None, f"got {data['quoted_total_cents']}"


def test_list_projects_paginated_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list responses include the following
    fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_projects_paginated_envelope
    """
    client = create_client()
    rate_card = create_rate_card()
    api.create_project(create_project_payload(client["id"], rate_card["id"], name="P1"), PM)
    api.create_project(create_project_payload(client["id"], rate_card["id"], name="P2"), PM)
    resp = api.list_projects(PM, params={"client_id": client["id"]})
    data, meta = validate_paginated(resp)
    assert "total_count" in meta and "has_more" in meta
    assert len(data) == 2, f"expected 2 projects for this client, got {len(data)}"


def test_rbac_translator_cannot_create_assignment(api):
    """PRD §2.1: "When a syntactically valid request is made by a role that is not
    permitted to perform the operation ... the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §3.5: "A `ProjectManager` staffs a job by creating **assignments**."

    Design: Corner/rbac/rbac_translator_cannot_create_assignment
    """
    client = create_client()
    rate_card = create_rate_card()
    linguist = api.create_linguist({
        "full_name": "T", "native_locale": "de-DE",
        "qualified_pairs": [{"source_locale": "en-US", "target_locale": "de-DE"}],
    }, PM).json()["data"]
    project = api.create_project(
        create_project_payload(client["id"], rate_card["id"], name="P1"), PM).json()["data"]
    job = api.create_job(project["id"], {"filename": "a.docx",
                                         "quoted_no_match_words": 1000}, PM).json()["data"]
    api.quote_project(project["id"], PM)
    api.approve_project(project["id"], make_client_headers(client["id"]))
    jv = api.get_job(job["id"], PM).json()["data"]["version"]
    resp = api.create_assignment({
        "job_id": job["id"], "linguist_id": linguist["id"], "role": "TRANSLATOR",
        "window_start": "2026-06-01T00:00:00.000Z",
        "window_end": "2026-06-02T00:00:00.000Z", "expected_job_version": jv,
    }, build_user_headers(linguist["id"], "Translator"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)


def test_rbac_client_cannot_approve_other_clients_project(api):
    """PRD §3.4: "Only the owning `Client` may do this: the acting principal's
    `X-User-ID` must equal the project's `client_id`, and a mismatch is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/rbac_client_cannot_approve_other_clients_project
    """
    client_a = create_client(name="A", billing_email="a@x.test")
    client_b = create_client(name="B", billing_email="b@x.test")
    rate_card = create_rate_card()
    project = api.create_project(
        create_project_payload(client_a["id"], rate_card["id"], name="P1"), PM).json()["data"]
    api.create_job(project["id"], {"filename": "a.docx",
                                   "quoted_no_match_words": 1000}, PM)
    api.quote_project(project["id"], PM)
    resp = api.approve_project(project["id"], make_client_headers(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)


def test_rbac_missing_user_context_header(api):
    """PRD §2.1: "Every request must include `X-User-ID` to identify the acting
    principal and `X-User-Role` to declare its operational capacity. If either header
    is missing or malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/rbac_missing_user_context_header
    """
    resp = api.create_client(create_client_payload(name="NoAuth",
                                                   billing_email="n@x.test"),
                             {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)
