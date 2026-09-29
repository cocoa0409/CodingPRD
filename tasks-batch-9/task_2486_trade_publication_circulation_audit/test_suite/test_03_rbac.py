"""Role boundaries and the two identity-based separation-of-duties gates."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import assert_pct
from test_helpers.factories import (
    accept_resolution_payload,
    engagement_payload,
    finding_payload,
    finding_response_payload,
    sample_verification_payload,
    source_document_payload,
)
from test_helpers.fixtures import (
    add_subscriber,
    move_clock,
    open_statement,
    read_publication,
    read_statement,
    register_contract,
    register_publication,
)
from test_helpers.test_users import (
    AUDITOR_2_HEADERS,
    AUDITOR_HEADERS,
    EXECUTIVE_HEADERS,
    MANAGER_2_HEADERS,
    MANAGER_HEADERS,
    MANAGER_PRIMARY,
    MANAGER_SECONDARY,
    SPECIALIST_HEADERS,
    make_advertiser_contact_headers,
)


def test_qualification_specialist_cannot_create_publication_unauthorized():
    """Registering a title is the manager's exclusive privilege.

    "Registering a publication is a `CirculationManager`'s exclusive privilege;
    all four operator roles may read it afterwards".

    Design: Corner/rbac/qualification_specialist_cannot_create_publication_unauthorized
    """
    payload = {
        "name": "Unauthorized Launch",
        "frequency": "MONTHLY",
        "industry_code": "MANUFACTURING",
    }
    response = api_client.create_publication(payload, SPECIALIST_HEADERS)
    validate_error(response, ERR_UNAUTHORIZED, 403)

    response = api_client.create_publication(payload, MANAGER_HEADERS)
    validate_success(response, 201)


def test_circulation_auditor_cannot_purge_source_document_unauthorized():
    """The auditor may read every evidence row but may not destroy one.

    "A successful purge — a `CirculationManager` operation carrying an optional
    `purge_reason` — sets `purge_status` to `PURGED` and `purged_at` to the
    current logical clock."

    Design: Corner/rbac/circulation_auditor_cannot_purge_source_document_unauthorized
    """
    publication = register_publication(
        name="Peer Boundary Monthly",
        industry_code="MANUFACTURING",
        source_doc_retention_months=1,
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Kilo Castings",
        subscription_class="CONTROLLED",
        copies=55,
    )
    document = validate_success(
        api_client.create_source_document(
            subscriber["id"],
            source_document_payload(
                doc_type="SIGNED_REQUEST_CARD",
                captured_at="2026-07-15T00:00:00Z",
                storage_ref="s3://circ/k-card",
            ),
            SPECIALIST_HEADERS,
        ),
        201,
    )
    move_clock("2026-08-20T00:00:00Z")

    listing = api_client.list_source_documents(
        subscriber["id"], AUDITOR_HEADERS, params={"limit": 10, "offset": 0}
    )
    rows = validate_success(listing, 200)
    assert rows[0]["id"] == document["id"]

    response = api_client.purge_source_document(
        document["id"], {"purge_reason": "auditor housekeeping"}, AUDITOR_HEADERS
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    listing = api_client.list_source_documents(subscriber["id"], AUDITOR_HEADERS)
    rows = validate_success(listing, 200)
    assert rows[0]["purge_status"] == "RETAINED"

    response = api_client.purge_source_document(
        document["id"], {"purge_reason": "retention elapsed"}, MANAGER_HEADERS
    )
    purged = validate_success(response, 200)
    assert purged["purge_status"] == "PURGED"
    assert purged["purged_at"].startswith("2026-08-20T00:00:00")


def test_advertiser_contact_cannot_list_advertiser_contracts_unauthorized():
    """The entity-backed advertiser role cannot enumerate the publisher's contract book.

    "The acting role appears in the target endpoint's role list — otherwise
    `ERR_UNAUTHORIZED`. Applies to every endpoint."

    Design: Corner/rbac/advertiser_contact_cannot_list_advertiser_contracts_unauthorized
    """
    publication = register_publication(
        name="Advertiser Scope Monthly", industry_code="MANUFACTURING"
    )
    contract = register_contract(
        publication["id"],
        advertiser_name="Hydraulics International",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
    )
    assert_pct(contract["shortfall_tolerance_pct"], 2.00)

    response = api_client.list_advertiser_contracts(
        make_advertiser_contact_headers(contract["id"]),
        params={"publication_id": publication["id"], "limit": 10, "offset": 0},
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    for headers in (AUDITOR_HEADERS, EXECUTIVE_HEADERS):
        rows = validate_success(
            api_client.list_advertiser_contracts(
                headers, params={"publication_id": publication["id"]}
            ),
            200,
        )
        assert [row["id"] for row in rows] == [contract["id"]]


def test_certify_own_prepared_statement_rejected():
    """The certification block reads `X-User-ID`, not the acting role.

    "separation of duties: the acting `X-User-ID` must differ from the
    statement's `prepared_by_user_id`. The operator who assembled the numbers may
    never be the one who swears to them, and an attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 409."

    Design: Corner/rbac/certify_own_prepared_statement_rejected
    """
    publication = register_publication(
        name="Duty Split Monthly", industry_code="LOGISTICS"
    )
    statement = open_statement(
        publication["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    assert statement["prepared_by_user_id"] == MANAGER_PRIMARY

    response = api_client.certify_statement(
        statement["id"], {"certification_note": "self-certifying"}, MANAGER_HEADERS
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
    assert read_statement(statement["id"])["status"] == "DRAFT"

    response = api_client.certify_statement(
        statement["id"],
        {"certification_note": "independent certification"},
        MANAGER_2_HEADERS,
    )
    filed = validate_success(response, 200)
    assert filed["status"] == "FILED"
    assert filed["certified_by_user_id"] == MANAGER_SECONDARY
    assert filed["filed_at"].startswith("2026-08-01T00:00:00")


def test_accept_finding_resolution_by_raising_auditor_rejected():
    """The auditor who raised a finding may not bless its remedy.

    "the acting `X-User-ID` must differ from the finding's `raised_by_user_id` —
    the auditor who raised an exception may not be the one who blesses its
    remedy, and a self-acceptance is rejected with `ERR_SEGREGATION_OF_DUTIES`
    and HTTP 409".

    Design: Corner/rbac/accept_finding_resolution_by_raising_auditor_rejected
    """
    publication = register_publication(
        name="Audit Duty Split Monthly", industry_code="UTILITIES"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Lima Power",
        subscription_class="CONTROLLED",
        copies=500,
    )
    statement = open_statement(
        publication["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    validate_success(
        api_client.certify_statement(
            statement["id"], {"certification_note": "filed"}, EXECUTIVE_HEADERS
        ),
        200,
    )
    engagement = validate_success(
        api_client.create_audit_engagement(
            engagement_payload(
                statement["id"],
                auditor_org="Verified Audit Bureau",
                fieldwork_start="2026-08-05T00:00:00Z",
                fieldwork_end="2026-08-09T00:00:00Z",
                sample_size=2,
            ),
            AUDITOR_HEADERS,
        ),
        201,
    )
    # A finding may only be raised once the engagement has entered FIELDWORK, so the
    # first of the two sampled records is taken here.
    in_fieldwork = validate_success(
        api_client.record_sample_verification(
            engagement["id"],
            sample_verification_payload(
                subscriber["id"], evidence_ok=True, verified_copies=380
            ),
            AUDITOR_HEADERS,
        ),
        200,
    )
    assert in_fieldwork["status"] == "FIELDWORK"

    finding = validate_success(
        api_client.create_audit_finding(
            finding_payload(
                engagement["id"],
                subscriber_id=subscriber["id"],
                finding_type="MISSING_SOURCE_DOC",
                severity="MATERIAL",
                affected_copies=120,
            ),
            AUDITOR_HEADERS,
        ),
        201,
    )
    assert finding["raised_by_user_id"] == "aud-01"

    responded = validate_success(
        api_client.respond_to_finding(
            finding["id"], finding_response_payload(), MANAGER_HEADERS
        ),
        200,
    )
    assert responded["status"] == "RESPONSE_SUBMITTED"

    response = api_client.accept_finding_resolution(
        finding["id"],
        accept_resolution_payload(resolution_note="self-accepting my own finding"),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
    still_open = validate_success(
        api_client.get_audit_finding(finding["id"], AUDITOR_HEADERS), 200
    )
    assert still_open["status"] == "RESPONSE_SUBMITTED"

    response = api_client.accept_finding_resolution(
        finding["id"],
        accept_resolution_payload(resolution_note="independent review of the response"),
        AUDITOR_2_HEADERS,
    )
    accepted = validate_success(response, 200)
    assert accepted["status"] == "ACCEPTED_RESOLVED"

    assert read_publication(publication["id"])["open_material_findings_count"] == 0
    assert read_statement(statement["id"])["status"] == "UNDER_AUDIT"
