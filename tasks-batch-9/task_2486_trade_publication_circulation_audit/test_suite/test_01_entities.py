"""Entity shape, defaults, system fields and derived ledger fields."""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INVALID_ENUM_VALUE,
    ERR_PUBLICATION_NOT_FOUND,
    ERR_SUBSCRIBER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_envelope_meta,
    assert_ledger_buckets,
    assert_pct,
    assert_posture,
)
from test_helpers.factories import (
    industry_rule_payload,
    job_function_rule_payload,
    publication_payload,
    reclassify_payload,
    source_document_payload,
    subscriber_payload,
    undeliverable_event_payload,
)
from test_helpers.fixtures import (
    add_subscriber,
    read_publication,
    register_publication,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    MANAGER_HEADERS,
    SPECIALIST_HEADERS,
)

UNKNOWN_SUBSCRIBER_ID = "2f8c1a44-6d0e-4c3a-9b77-5a1e0c9d3e21"
UNKNOWN_PUBLICATION_ID = "9c1f6b02-8e4d-4a17-b0c5-77aa31e4d908"


def test_create_publication_with_explicit_thresholds_returns_all_fields():
    """Every supplied policy threshold is stored verbatim and no ledger counter is seeded.

    "Registration is a clean slate. Every copy counter — the grand total, the
    three class buckets and the three delivery buckets described in §2.10 —
    starts at 0, the hygiene ratio `undeliverable_pct` starts at exactly 0.00,
    both open-findings counters start at 0, `audit_posture` starts at `OPEN`,
    and `version` starts at 1."

    Design: Corner/entities/create_publication_with_explicit_thresholds_returns_all_fields
    """
    response = api_client.create_publication(
        {
            "name": "Precision Metals Monthly",
            "frequency": "MONTHLY",
            "industry_code": "MANUFACTURING",
            "qualification_validity_months": 24,
            "renewal_grace_days": 60,
            "source_doc_retention_months": 48,
            "undeliverable_restrict_pct": 7.50,
            "materiality_pct": 3.00,
            "controlled_cap_pct": 20.00,
        },
        MANAGER_HEADERS,
    )
    publication = validate_success(response, 201)
    assert_envelope_meta(response)
    assert response.json()["response_type"] == "object"

    assert publication["qualification_validity_months"] == 24
    assert publication["renewal_grace_days"] == 60
    assert publication["source_doc_retention_months"] == 48
    assert_pct(publication["undeliverable_restrict_pct"], 7.50)
    assert_pct(publication["materiality_pct"], 3.00)
    assert_pct(publication["controlled_cap_pct"], 20.00)

    assert_posture(publication, "OPEN")
    assert_ledger_buckets(
        publication,
        total=0,
        paid=0,
        qualified_non_paid=0,
        controlled=0,
        deliverable=0,
        undeliverable=0,
        removed=0,
    )
    assert_pct(publication["undeliverable_pct"], 0.00)
    assert publication["open_material_findings_count"] == 0
    assert publication["open_critical_findings_count"] == 0
    assert_common_fields(publication, expected_version=1)


def test_publication_defaults_applied_when_optional_thresholds_omitted():
    """All six policy knobs fall back to their declared defaults when omitted.

    "`qualification_validity_months` ... defaults to 36 ... `renewal_grace_days`
    ... defaults to 90 ... `source_doc_retention_months` ... defaults to 36 ...
    `undeliverable_restrict_pct` ... defaults to 5.00 ... `materiality_pct` ...
    defaults to 2.00 ... `controlled_cap_pct` ... defaults to 25.00".

    Design: Corner/entities/publication_defaults_applied_when_optional_thresholds_omitted
    """
    response = api_client.create_publication(
        {
            "name": "Default Config Weekly",
            "frequency": "WEEKLY",
            "industry_code": "LOGISTICS",
        },
        MANAGER_HEADERS,
    )
    publication = validate_success(response, 201)

    assert publication["qualification_validity_months"] == 36
    assert publication["renewal_grace_days"] == 90
    assert publication["source_doc_retention_months"] == 36
    assert_pct(publication["undeliverable_restrict_pct"], 5.00)
    assert_pct(publication["materiality_pct"], 2.00)
    assert_pct(publication["controlled_cap_pct"], 25.00)


def test_get_publication_returns_stored_threshold_configuration():
    """The single-publication read serves the stored row, ledger included, not the
    create-time snapshot.

    "Enrolment immediately re-derives the publication's copies ledger — the
    grand total, the class bucket matching the recipient's class, the
    deliverable bucket and the hygiene ratio".

    Design: Corner/entities/get_publication_returns_stored_threshold_configuration
    """
    publication = register_publication(
        name="Readback Review", frequency="MONTHLY", industry_code="UTILITIES"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Kilo Utilities",
        contact_email="k@kilo.test",
        job_function_code="PLANT_MGMT",
        industry_code="UTILITIES",
        purchasing_authority_level="APPROVES",
        subscription_class="PAID",
        copies=400,
        paid_amount_cents=8000,
    )

    response = api_client.get_publication(publication["id"], AUDITOR_HEADERS)
    stored = validate_success(response, 200)

    assert_ledger_buckets(stored, total=400, paid=400, deliverable=400)
    assert_pct(stored["undeliverable_pct"], 0.00)
    assert stored["version"] == 2
    assert subscriber["delivery_status"] == "DELIVERABLE"


def test_list_subscribers_filtered_by_publication_returns_pagination_envelope():
    """A publication filter narrows the set before `total_count` is computed.

    "Filters supplied as query parameters narrow the result set before
    pagination and before `total_count` is computed."

    Design: Corner/entities/list_subscribers_filtered_by_publication_returns_pagination_envelope
    """
    pa = register_publication(name="Filter Target Journal", industry_code="MANUFACTURING")
    pb = register_publication(name="Other Journal", industry_code="LOGISTICS")
    sub_l = add_subscriber(
        pa["id"],
        company_name="Lima Fabrication",
        subscription_class="PAID",
        copies=100,
        paid_amount_cents=2000,
    )
    sub_m = add_subscriber(
        pa["id"],
        company_name="Mike Tooling",
        subscription_class="CONTROLLED",
        copies=50,
    )
    sub_n = add_subscriber(
        pb["id"],
        company_name="November Freight",
        subscription_class="CONTROLLED",
        copies=25,
    )

    response = api_client.list_subscribers(
        MANAGER_HEADERS, params={"publication_id": pa["id"], "limit": 1, "offset": 0}
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert rows[0]["id"] in {sub_l["id"], sub_m["id"]}
    assert rows[0]["id"] != sub_n["id"]

    response = api_client.list_subscribers(
        MANAGER_HEADERS,
        params={
            "publication_id": pa["id"],
            "subscription_class": "CONTROLLED",
            "limit": 10,
            "offset": 0,
        },
    )
    rows, meta = validate_paginated(response)
    assert len(rows) == 1
    assert rows[0]["id"] == sub_m["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    response = api_client.list_subscribers(
        MANAGER_HEADERS, params={"publication_id": pa["id"]}
    )
    rows, meta = validate_paginated(response)
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_get_subscriber_with_unknown_id_not_found():
    """An unresolved recipient identifier yields the entity-scoped not-found error.

    "a `subscriber_id` that resolves to nothing yields `ERR_SUBSCRIBER_NOT_FOUND`".

    Design: Corner/entities/get_subscriber_with_unknown_id_not_found
    """
    response = api_client.get_subscriber(UNKNOWN_SUBSCRIBER_ID, MANAGER_HEADERS)
    validate_error(response, ERR_SUBSCRIBER_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ERR_SUBSCRIBER_NOT_FOUND
    assert isinstance(body["data"]["message"], str)


def test_create_subscriber_with_unknown_subscription_class_rejected():
    """An out-of-set enum is refused at the enum-membership rung, not the request-shape one.

    "Enum membership. Every supplied enum value is a member of its declared set
    — otherwise `ERR_INVALID_ENUM_VALUE` with HTTP 422."

    Design: Corner/entities/create_subscriber_with_unknown_subscription_class_rejected
    """
    publication = register_publication(
        name="Enum Guard Journal", industry_code="MANUFACTURING"
    )
    base = subscriber_payload(
        publication["id"],
        company_name="Papa Castings",
        contact_email="p@papa.test",
        job_function_code="ENGINEERING_MGMT",
        industry_code="MANUFACTURING",
        purchasing_authority_level="APPROVES",
        copies=60,
    )

    response = api_client.create_subscriber(
        dict(base, subscription_class="COMPLIMENTARY"), MANAGER_HEADERS
    )
    validate_error(response, ERR_INVALID_ENUM_VALUE, 422)

    response = api_client.create_subscriber(
        dict(base, purchasing_authority_level="SOMETIMES"), MANAGER_HEADERS
    )
    validate_error(response, ERR_INVALID_ENUM_VALUE, 422)

    response = api_client.create_subscriber(
        dict(base, subscription_class="paid"), MANAGER_HEADERS
    )
    validate_error(response, ERR_INVALID_ENUM_VALUE, 422)

    listing = api_client.list_subscribers(
        MANAGER_HEADERS, params={"publication_id": publication["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assert rows == []


def test_subscriber_system_fields_minted_on_create():
    """`id`, `created_at`, `updated_at` and `version` are server-minted and advance on mutation.

    "`version` begins at 1 when the resource is created and increases by exactly
    1 on every mutation of that resource; `updated_at` is refreshed on the same
    occasions."

    Design: Corner/entities/subscriber_system_fields_minted_on_create
    """
    publication = register_publication(
        name="System Field Journal", industry_code="UTILITIES"
    )
    created = add_subscriber(
        publication["id"],
        company_name="Quebec Power",
        contact_email="q@quebec.test",
        job_function_code="PLANT_MGMT",
        industry_code="UTILITIES",
        purchasing_authority_level="SPECIFIES",
        subscription_class="CONTROLLED",
        copies=80,
    )
    assert_common_fields(created, expected_version=1)
    assert is_valid_uuid(created["id"])
    assert len(created["id"]) == 36
    assert not created["id"].startswith("sub_")

    response = api_client.record_undeliverable_event(
        created["id"], undeliverable_event_payload(reason_code="ADDRESS_UNKNOWN"), MANAGER_HEADERS
    )
    mutated = validate_success(response, 200)
    assert_common_fields(mutated, expected_version=2)
    assert mutated["created_at"] == created["created_at"]
    assert mutated["updated_at"] >= created["created_at"]


def test_source_document_immutability_has_no_update_endpoint_or_version():
    """Evidence rows are write-once apart from the purge action, and retention is derived.

    "A source document likewise has no general update operation — the only
    mutation defined for it is the purge action described in §3.2 — but it does
    carry the full complement of common properties, and the purge refreshes
    `updated_at` and increments `version` like any other mutation."

    Design: Corner/entities/source_document_immutability_has_no_update_endpoint_or_version
    """
    publication = register_publication(
        name="Evidence Retention Journal", industry_code="MANUFACTURING"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Romeo Welding",
        subscription_class="CONTROLLED",
        copies=40,
    )
    response = api_client.create_source_document(
        subscriber["id"],
        source_document_payload(
            doc_type="WEB_FORM_CAPTURE",
            captured_at="2026-07-15T00:00:00Z",
            storage_ref="s3://circ/r-web",
        ),
        SPECIALIST_HEADERS,
    )
    document = validate_success(response, 201)

    # `retention_expires_at` is `captured_at` advanced by the publication's
    # `source_doc_retention_months`, which defaults to 36.
    assert document["retention_expires_at"].startswith("2029-07-15T00:00:00")
    assert document["purge_status"] == "RETAINED"
    assert document["purged_at"] is None
    assert_common_fields(document, expected_version=1)

    listing = api_client.list_source_documents(
        subscriber["id"],
        AUDITOR_HEADERS,
        params={"purge_status": "RETAINED", "limit": 10, "offset": 0},
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == document["id"]
    assert rows[0]["purge_status"] == "RETAINED"


def test_create_qualification_rule_under_unknown_publication_not_found():
    """A rule's parent is resolved from the path before the body is considered.

    "A publication identifier that resolves to nothing yields
    `ERR_PUBLICATION_NOT_FOUND`".

    Design: Corner/entities/create_qualification_rule_under_unknown_publication_not_found
    """
    response = api_client.create_qualification_rule(
        UNKNOWN_PUBLICATION_ID,
        job_function_rule_payload(allowed_values=["ENGINEERING_MGMT"], points=45),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_PUBLICATION_NOT_FOUND, 404)


def test_publication_ledger_computed_fields_after_reclassify_and_undeliverable_event():
    """The two ledger axes are server-derived, and a bounce report moves neither of them.

    "Recording a returned or bounced copy against a recipient increments its
    `undeliverable_count` by 1 and does nothing else ... Neither
    `delivery_status` nor `qualification_status` moves, and the publication's
    delivery buckets do not move either."

    Design: Corner/entities/publication_ledger_computed_fields_after_reclassify_and_undeliverable_event
    """
    publication = register_publication(
        name="Derived Field Journal", industry_code="UTILITIES"
    )
    sub_s = add_subscriber(
        publication["id"],
        company_name="Sierra Turbines",
        subscription_class="QUALIFIED_NON_PAID",
        copies=300,
    )
    sub_t = add_subscriber(
        publication["id"],
        company_name="Tango Boilers",
        purchasing_authority_level="RECOMMENDS",
        subscription_class="CONTROLLED",
        copies=100,
    )
    # `qualification_score` is only ever written by verification.
    assert sub_s["qualification_score"] == 0
    assert sub_t["qualification_score"] == 0

    response = api_client.record_undeliverable_event(
        sub_t["id"], undeliverable_event_payload(reason_code="RETURNED_MAIL"), MANAGER_HEADERS
    )
    bounced = validate_success(response, 200)
    assert bounced["undeliverable_count"] == 1
    assert bounced["delivery_status"] == "DELIVERABLE"

    stored = read_publication(publication["id"])
    assert_ledger_buckets(
        stored,
        total=400,
        qualified_non_paid=300,
        controlled=100,
        deliverable=400,
        undeliverable=0,
        removed=0,
    )
    assert_pct(stored["undeliverable_pct"], 0.00)
    assert_posture(stored, "OPEN")

    # Reclassification moves copies between class buckets and conserves the total.
    response = api_client.reclassify_subscriber(
        sub_t["id"],
        reclassify_payload("PAID", paid_amount_cents=4500),
        MANAGER_HEADERS,
    )
    reclassified = validate_success(response, 200)
    assert reclassified["subscription_class"] == "PAID"
    assert reclassified["version"] == 3

    stored = read_publication(publication["id"])
    assert_ledger_buckets(
        stored,
        total=400,
        paid=100,
        qualified_non_paid=300,
        controlled=0,
        deliverable=400,
    )
