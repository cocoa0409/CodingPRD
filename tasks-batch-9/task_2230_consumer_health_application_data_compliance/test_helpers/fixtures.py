"""Composite setup helpers and pytest fixtures.

The server is relaunched with an empty database before every test, so nothing
here may assume pre-existing rows: each helper builds the state it needs from
scratch through the public API.

Every helper takes ``**overrides`` so a test can vary one input without
restating the rest, and returns the created resource so the test can chain on
its identifiers and computed fields.
"""

from __future__ import annotations

from typing import Any

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient, api_client
from .constants import CLOCK_EPOCH
from .test_users import (
    make_compliance_approver_headers,
    make_consumer_headers,
    make_data_steward_headers,
    make_platform_admin_headers,
    make_privacy_officer_headers,
    make_security_engineer_headers,
)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(instant: str, client: ApiClient = api_client) -> dict[str, Any]:
    """Move the logical clock to an explicit UTC instant."""
    response = client.set_clock(
        factories.set_clock_payload(instant), make_platform_admin_headers()
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# App products
# ---------------------------------------------------------------------------


def create_product(client: ApiClient = api_client, **overrides: Any) -> dict[str, Any]:
    """Register an app product."""
    response = client.create_app_product(
        factories.create_app_product_payload(**overrides), make_platform_admin_headers()
    )
    return get_success_data(response)


def read_product(app_product_id: str, client: ApiClient = api_client) -> dict[str, Any]:
    """Read an app product, refreshing its derived counters and version."""
    return get_success_data(
        client.get_app_product(app_product_id, make_platform_admin_headers())
    )


def product_version(app_product_id: str, client: ApiClient = api_client) -> int:
    """Current version of the product, for the policy-creation concurrency check."""
    return int(read_product(app_product_id, client)["version"])


# ---------------------------------------------------------------------------
# Data elements and processing purposes
# ---------------------------------------------------------------------------


def create_element(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Declare a data element on a product."""
    response = client.create_data_element(
        factories.create_data_element_payload(app_product_id, **overrides),
        make_data_steward_headers(),
    )
    return get_success_data(response)


def create_purpose(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Declare a processing purpose on a product."""
    response = client.create_processing_purpose(
        factories.create_processing_purpose_payload(app_product_id, **overrides),
        make_data_steward_headers(),
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


def create_vendor(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Register a vendor with its contract clauses."""
    response = client.create_vendor(
        factories.create_vendor_payload(app_product_id, **overrides),
        make_privacy_officer_headers(),
    )
    return get_success_data(response)


def create_executed_vendor(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Register a vendor and execute its agreement."""
    vendor = create_vendor(app_product_id, client, **overrides)
    return get_success_data(
        client.execute_vendor_agreement(vendor["id"], make_privacy_officer_headers())
    )


# ---------------------------------------------------------------------------
# Element-purpose mappings
# ---------------------------------------------------------------------------


def create_mapping(
    data_element_id: str,
    processing_purpose_id: str,
    client: ApiClient = api_client,
    **overrides: Any,
) -> dict[str, Any]:
    """Propose a mapping of one element onto one purpose."""
    response = client.create_element_purpose_mapping(
        factories.create_element_purpose_mapping_payload(
            data_element_id, processing_purpose_id, **overrides
        ),
        make_data_steward_headers(),
    )
    return get_success_data(response)


def activate_mapping(mapping_id: str, client: ApiClient = api_client) -> dict[str, Any]:
    """Activate a proposed or suspended mapping."""
    return get_success_data(
        client.activate_element_purpose_mapping(mapping_id, make_data_steward_headers())
    )


# ---------------------------------------------------------------------------
# Applicability assessments
# ---------------------------------------------------------------------------


def create_assessment(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Create a DRAFT applicability assessment."""
    response = client.create_applicability_assessment(
        factories.create_applicability_assessment_payload(app_product_id, **overrides),
        make_privacy_officer_headers(),
    )
    return get_success_data(response)


def create_submitted_assessment(
    app_product_id: str,
    client: ApiClient = api_client,
    submitter: str = "po-1",
    **overrides: Any,
) -> dict[str, Any]:
    """Create an assessment and submit it, running the applicability determination."""
    assessment = create_assessment(app_product_id, client, **overrides)
    return get_success_data(
        client.submit_applicability_assessment(
            assessment["id"], make_privacy_officer_headers(submitter)
        )
    )


def create_approved_assessment(
    app_product_id: str,
    client: ApiClient = api_client,
    submitter: str = "po-1",
    approver: str = "ca-1",
    **overrides: Any,
) -> dict[str, Any]:
    """Create, submit and approve an assessment, pinning the product's track.

    An assessment can only be submitted once the product has at least one
    active data element, so callers must declare an element first.
    """
    assessment = create_submitted_assessment(
        app_product_id, client, submitter=submitter, **overrides
    )
    return get_success_data(
        client.approve_applicability_assessment(
            assessment["id"], make_compliance_approver_headers(approver)
        )
    )


# ---------------------------------------------------------------------------
# Privacy policy versions
# ---------------------------------------------------------------------------


def create_policy(
    app_product_id: str,
    applicability_assessment_id: str,
    client: ApiClient = api_client,
    author: str = "po-1",
    **overrides: Any,
) -> dict[str, Any]:
    """Draft a policy version, reading the product's current version first."""
    payload = factories.create_privacy_policy_version_payload(
        app_product_id,
        applicability_assessment_id,
        product_version(app_product_id, client),
        **overrides,
    )
    response = client.create_privacy_policy_version(
        payload, make_privacy_officer_headers(author)
    )
    return get_success_data(response)


def create_reviewed_policy(
    app_product_id: str,
    applicability_assessment_id: str,
    client: ApiClient = api_client,
    author: str = "po-1",
    **overrides: Any,
) -> dict[str, Any]:
    """Draft a policy version and submit it for review, scoring its completeness."""
    policy = create_policy(
        app_product_id, applicability_assessment_id, client, author=author, **overrides
    )
    return get_success_data(
        client.submit_policy_review(policy["id"], make_privacy_officer_headers(author))
    )


def create_published_policy(
    app_product_id: str,
    applicability_assessment_id: str,
    client: ApiClient = api_client,
    author: str = "po-1",
    publisher: str = "ca-1",
    **overrides: Any,
) -> dict[str, Any]:
    """Draft, review and publish a policy version, setting the product CURRENT."""
    policy = create_reviewed_policy(
        app_product_id, applicability_assessment_id, client, author=author, **overrides
    )
    return get_success_data(
        client.publish_privacy_policy_version(
            policy["id"], make_compliance_approver_headers(publisher)
        )
    )


# ---------------------------------------------------------------------------
# Consumers and consent
# ---------------------------------------------------------------------------


def create_consumer(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Register a consumer and receive its minted verification token."""
    response = client.create_consumer(
        factories.create_consumer_payload(app_product_id, **overrides),
        make_platform_admin_headers(),
    )
    return get_success_data(response)


def read_consumer(consumer_id: str, client: ApiClient = api_client) -> dict[str, Any]:
    """Read a consumer, refreshing its version and deletion counter."""
    return get_success_data(
        client.get_consumer(consumer_id, make_platform_admin_headers())
    )


def consumer_version(consumer_id: str, client: ApiClient = api_client) -> int:
    """Current version of the consumer, for the consent-record concurrency check."""
    return int(read_consumer(consumer_id, client)["version"])


def open_consent_record(
    consumer_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Open a consent record, reading the consumer's current version first."""
    payload = factories.create_consent_record_payload(
        consumer_id, consumer_version(consumer_id, client), **overrides
    )
    response = client.create_consent_record(payload, make_privacy_officer_headers())
    return get_success_data(response)


def grant_axes(
    record_id: str, consumer_id: str, axes: list[str], client: ApiClient = api_client
) -> dict[str, Any]:
    """Grant consent on the named axes, acting as the owning consumer."""
    return get_success_data(
        client.grant_consent(record_id, {"axes": axes}, make_consumer_headers(consumer_id))
    )


def withdraw_axis(
    record_id: str, consumer_id: str, axis: str, client: ApiClient = api_client
) -> dict[str, Any]:
    """Withdraw consent on one axis, acting as the owning consumer."""
    return get_success_data(
        client.withdraw_consent(
            record_id, {"axis": axis}, make_consumer_headers(consumer_id)
        )
    )


# ---------------------------------------------------------------------------
# Consumer rights requests and deletion tasks
# ---------------------------------------------------------------------------


def file_request(
    consumer_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """File a rights request, acting as the owning consumer."""
    response = client.create_consumer_request(
        factories.create_consumer_request_payload(consumer_id, **overrides),
        make_consumer_headers(consumer_id),
    )
    return get_success_data(response)


def verify_request(
    request_id: str, verification_token: str, client: ApiClient = api_client
) -> dict[str, Any]:
    """Verify a request's identity with the consumer's minted token."""
    return get_success_data(
        client.verify_consumer_request(
            request_id,
            {"verification_token": verification_token},
            make_privacy_officer_headers(),
        )
    )


def tasks_for_request(request_id: str, client: ApiClient = api_client) -> list[dict[str, Any]]:
    """List the deletion tasks fanned out for one request, in creation order."""
    response = client.list_deletion_tasks(
        make_privacy_officer_headers(), {"consumer_request_id": request_id}
    )
    return list(get_success_data(response))


# ---------------------------------------------------------------------------
# Geofencing
# ---------------------------------------------------------------------------


def create_zone(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Register a health facility zone and derive its prohibition rule."""
    response = client.create_geofence_zone(
        factories.create_geofence_zone_payload(app_product_id, **overrides),
        make_platform_admin_headers(),
    )
    return get_success_data(response)


def create_campaign(
    geofence_zone_id: str,
    processing_purpose_id: str,
    client: ApiClient = api_client,
    **overrides: Any,
) -> dict[str, Any]:
    """Plan a campaign against a zone and compute its standoff."""
    response = client.create_geofence_campaign(
        factories.create_geofence_campaign_payload(
            geofence_zone_id, processing_purpose_id, **overrides
        ),
        make_data_steward_headers(),
    )
    return get_success_data(response)


def activate_campaign(campaign_id: str, client: ApiClient = api_client) -> dict[str, Any]:
    """Activate a planned or paused campaign."""
    return get_success_data(
        client.activate_geofence_campaign(campaign_id, make_data_steward_headers())
    )


# ---------------------------------------------------------------------------
# Breaches and the security program
# ---------------------------------------------------------------------------


def create_breach(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Record a discovered breach incident."""
    response = client.create_breach_incident(
        factories.create_breach_incident_payload(app_product_id, **overrides),
        make_security_engineer_headers(),
    )
    return get_success_data(response)


def assess_breach(incident_id: str, client: ApiClient = api_client) -> dict[str, Any]:
    """Assess a discovered breach's reportability."""
    return get_success_data(
        client.assess_breach_incident(incident_id, make_security_engineer_headers())
    )


def create_sra(
    app_product_id: str, client: ApiClient = api_client, **overrides: Any
) -> dict[str, Any]:
    """Document a security risk assessment and score its residual risk."""
    response = client.create_security_risk_assessment(
        factories.create_security_risk_assessment_payload(app_product_id, **overrides),
        make_security_engineer_headers(),
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------


def build_regulated_product(
    client: ApiClient = api_client, **product_overrides: Any
) -> dict[str, Any]:
    """A product with one CHD element and an APPROVED applicability assessment.

    Returns a dict with the ``product``, ``element`` and ``assessment`` rows.
    The product row is re-read after approval so its pinned track and bumped
    version are visible.
    """
    product = create_product(client, **product_overrides)
    element = create_element(product["id"], client)
    assessment = create_approved_assessment(product["id"], client)
    return {
        "product": read_product(product["id"], client),
        "element": element,
        "assessment": assessment,
    }


def build_share_disclosure_chain(
    client: ApiClient = api_client, **product_overrides: Any
) -> dict[str, Any]:
    """A product whose CHD element is actively shared with an executed vendor.

    Builds product, CHD element, SHARE purpose, executed vendor, and an ACTIVE
    mapping joining them, after approving the product's applicability
    assessment so that mapping activation is admitted. Returns every row plus
    the re-read product.
    """
    product = create_product(client, **product_overrides)
    element = create_element(product["id"], client)
    assessment = create_approved_assessment(product["id"], client)
    purpose = create_purpose(
        product["id"],
        client,
        purpose_kind="ADVERTISING",
        activity_kind="SHARE",
        description_text="Share sleep diagnoses with an ad network",
    )
    vendor = create_executed_vendor(product["id"], client)
    mapping = create_mapping(
        element["id"], purpose["id"], client, vendor_id=vendor["id"]
    )
    mapping = activate_mapping(mapping["id"], client)
    return {
        "product": read_product(product["id"], client),
        "element": element,
        "assessment": assessment,
        "purpose": purpose,
        "vendor": vendor,
        "mapping": mapping,
    }


def build_consented_consumer(
    app_product_id: str,
    client: ApiClient = api_client,
    axes: tuple[str, ...] = ("COLLECT", "SHARE"),
    **consumer_overrides: Any,
) -> dict[str, Any]:
    """A registered consumer with an open consent record and the named axes granted.

    Axes are granted one call at a time, in the order given, because a grant
    names exactly one axis.
    """
    consumer = create_consumer(app_product_id, client, **consumer_overrides)
    record = open_consent_record(consumer["id"], client)
    for axis in axes:
        record = grant_axes(record["id"], consumer["id"], [axis], client)
    return {"consumer": consumer, "consent_record": record}


def build_verified_delete_request(
    app_product_id: str,
    client: ApiClient = api_client,
    axes: tuple[str, ...] = ("COLLECT", "SHARE"),
) -> dict[str, Any]:
    """A verified DELETE request for a consented consumer, with its fanned-out tasks."""
    consented = build_consented_consumer(app_product_id, client, axes=axes)
    consumer = consented["consumer"]
    request = file_request(consumer["id"], client, request_kind="DELETE")
    request = verify_request(request["id"], consumer["verification_token"], client)
    return {
        "consumer": consumer,
        "consent_record": consented["consent_record"],
        "request": request,
        "tasks": tasks_for_request(request["id"], client),
    }


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clock_at_epoch(api: ApiClient) -> str:
    """Pin the logical clock to its documented starting instant."""
    set_clock(CLOCK_EPOCH, api)
    return CLOCK_EPOCH


@pytest.fixture
def product(api: ApiClient) -> dict[str, Any]:
    """A freshly registered app product."""
    return create_product(api)


@pytest.fixture
def element(api: ApiClient, product: dict[str, Any]) -> dict[str, Any]:
    """A directly collected diagnosis element on the product."""
    return create_element(product["id"], api)


@pytest.fixture
def purpose(api: ApiClient, product: dict[str, Any]) -> dict[str, Any]:
    """A primary-service collection purpose on the product."""
    return create_purpose(product["id"], api)


@pytest.fixture
def vendor(api: ApiClient, product: dict[str, Any]) -> dict[str, Any]:
    """A DRAFT vendor agreement carrying both required clauses."""
    return create_vendor(product["id"], api)


@pytest.fixture
def executed_vendor(api: ApiClient, product: dict[str, Any]) -> dict[str, Any]:
    """A vendor whose agreement has been executed."""
    return create_executed_vendor(product["id"], api)


@pytest.fixture
def consumer(api: ApiClient, product: dict[str, Any]) -> dict[str, Any]:
    """An adult consumer registered against the product."""
    return create_consumer(product["id"], api)


@pytest.fixture
def consent_record(api: ApiClient, consumer: dict[str, Any]) -> dict[str, Any]:
    """A fresh consent record with every axis still NOT_REQUESTED."""
    return open_consent_record(consumer["id"], api)


@pytest.fixture
def approved_assessment(
    api: ApiClient, product: dict[str, Any], element: dict[str, Any]
) -> dict[str, Any]:
    """An APPROVED applicability assessment pinning the product's track."""
    return create_approved_assessment(product["id"], api)


@pytest.fixture
def regulated_product(api: ApiClient) -> dict[str, Any]:
    """A product with one CHD element and an approved applicability assessment."""
    return build_regulated_product(api)


@pytest.fixture
def share_disclosure_chain(api: ApiClient) -> dict[str, Any]:
    """A product whose CHD element is actively shared with an executed vendor."""
    return build_share_disclosure_chain(api)
