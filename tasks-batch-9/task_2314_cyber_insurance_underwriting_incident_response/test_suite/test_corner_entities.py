"""Corner coverage of the entity surface.

Creation echoes, declared defaults, computed fields, server-owned system
fields, declared type constraints, catalog immutability, body-FK resolution,
list filtering and pagination, and sub-resource retrieval.

Every test builds its own state from scratch through the public API; the
harness restarts the server with an empty database before each test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_2_HEADERS,
    UNDERWRITER_HEADERS,
    ErrorId,
)
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X

# A syntactically valid UUID that is never minted by the server.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

# The scan evidence used whenever a bound policy is only scenery: one HIGH
# finding that lowers EMAIL_FILTERING but opens no mandatory gap.
EMAIL_FILTERING_HIGH = [
    {"control_key": "EMAIL_FILTERING", "severity": "HIGH", "observed_level": "PARTIAL"}
]


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_same_instant(actual, expected, field="timestamp"):
    assert is_iso8601_timestamp(actual), f"{field} is not ISO 8601 UTC: {actual!r}"
    assert _instant(actual) == _instant(expected), (
        f"{field}: expected the instant {expected}, got {actual}"
    )


# ==========================================================================
# Creation
# ==========================================================================
def test_control_requirement_created_with_every_declared_field(api):
    """PRD §3.1: "`min_level_required` is the lowest maturity the carrier will
    accept and is one of `NONE`, `PARTIAL`, or `FULL`."
    PRD §3.1: "`weight` is an integer of at least 1 and at most 100 expressing
    how much the control contributes to the posture score."
    PRD §3.1: "A fourth field, `remediation_grace_days`, records how many days
    the insured is granted to fix this control at renewal; it defaults to 30 and
    must be at least 0 and at most 365."
    PRD §4: "A request that successfully creates a new resource returns HTTP
    201; every other successful request — reads, state transitions, amendments,
    and cascade-bearing operations that modify existing resources — returns HTTP
    200."
    PRD §2.4: "Each persisted row is addressed by an `id`, which is a
    server-minted UUID with no type prefix of any kind."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/control_requirement_created_with_every_declared_field
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    resp = api.create_control_requirement(
        {
            "control_key": "MFA_PRIVILEGED",
            "min_level_required": "FULL",
            "weight": 30,
            "is_mandatory": True,
            "remediation_grace_days": 45,
        },
        UNDERWRITER_HEADERS,
    )
    row = validate_success(resp, 201)

    assert is_valid_uuid(row["id"]), f"id must be a bare server-minted UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at: {row['created_at']!r}"

    assert row["control_key"] == "MFA_PRIVILEGED"
    assert row["min_level_required"] == "FULL"
    assert row["weight"] == 30
    assert row["is_mandatory"] is True
    assert row["remediation_grace_days"] == 45, (
        f"remediation_grace_days must echo the supplied 45, got {row['remediation_grace_days']}"
    )

    body = resp.json()
    assert body["response_type"] == "object", (
        f"a single resource is response_type object, got {body['response_type']}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {body['meta']['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    A.assert_total_count(api.list_control_requirements(UNDERWRITER_HEADERS), 1)


# ==========================================================================
# Retrieval
# ==========================================================================
def test_insured_account_get_returns_the_stored_row(api):
    """PRD §3.2: "The applicant record carries a `legal_name` of between 1 and
    200 characters, an `industry_code` from `HEALTHCARE`, `FINANCIAL`, `RETAIL`,
    `MANUFACTURING`, `PUBLIC_SECTOR`, or `TECHNOLOGY`, an `annual_revenue_usd`
    strictly greater than zero, and a `record_count` of held personal records of
    at least zero."
    PRD §3.2: "The account also exposes a computed `open_remediation_count`,
    which starts at 0 and tracks how many of this applicant's applications
    currently sit in remediation."
    PRD §4: "Read one insured account including open_remediation_count."

    Design: Corner/entities/insured_account_get_returns_the_stored_row
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    account = X.create_account(api, C.ACCOUNT_AURORA)

    fetched = validate_success(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))

    assert fetched["id"] == account["id"]
    assert fetched["legal_name"] == "Aurora Health"
    assert fetched["industry_code"] == "HEALTHCARE"
    A.assert_money(fetched["annual_revenue_usd"], 43800000, "annual_revenue_usd")
    assert fetched["record_count"] == 12345
    assert fetched["primary_dependency_key"] == "CSP_ALPHA"
    assert fetched["open_remediation_count"] == 0, (
        f"open_remediation_count starts at 0, got {fetched['open_remediation_count']}"
    )


def test_coverage_sections_subresource_returns_tower_ordered_by_erosion_priority(api):
    """PRD §3.5: "A policy's tower is readable under the policy in
    `erosion_priority` ascending order — exactly the order allocation walks —
    with a `section_key` filter, individual sections are readable by
    `section_id`, and underwriting and actuarial roles can search sections flat
    across policies with `policy_id` and `section_key` filters."
    PRD §3.5: "Each tower section is created with `sublimit_remaining_usd` equal
    to its `sublimit_usd`."
    PRD §3.5: "`waiting_period_hours` is the time deductible: it is required and
    strictly greater than zero, and at most 168, for `BUSINESS_INTERRUPTION` and
    `DEPENDENT_BI`, and must be null for every other section key — supplying it
    on a non-interruption section, or omitting it on an interruption section, is
    an `ERR_INVALID_REQUEST`."

    Design: Corner/entities/coverage_sections_subresource_returns_tower_ordered_by_erosion_priority
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.bound_policy(api, findings=EMAIL_FILTERING_HIGH)
    policy = chain["policy"]

    resp = api.list_policy_coverage_sections(
        policy["id"], UNDERWRITER_HEADERS, params={"limit": 10, "offset": 0}
    )
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 5, f"the bound tower has five sections, got {meta['total_count']}"
    assert len(rows) == 5

    assert rows[0]["section_key"] == "FIRST_PARTY_RESPONSE"
    assert rows[0]["erosion_priority"] == 10
    A.assert_money(rows[0]["sublimit_remaining_usd"], 1000000.00, "sublimit_remaining_usd")

    assert rows[1]["section_key"] == "BUSINESS_INTERRUPTION"
    assert rows[1]["waiting_period_hours"] == 12
    assert float(rows[1]["coinsurance_pct"]) == pytest.approx(0.10, abs=1e-6)

    assert rows[2]["section_key"] == "DEPENDENT_BI"
    assert rows[2]["waiting_period_hours"] == 24
    assert float(rows[2]["coinsurance_pct"]) == pytest.approx(0.20, abs=1e-6)

    assert rows[4]["section_key"] == "CYBER_EXTORTION"
    assert rows[4]["erosion_priority"] == 50
    assert rows[4]["waiting_period_hours"] is None, (
        "waiting_period_hours must be null on a non-interruption section, got "
        f"{rows[4]['waiting_period_hours']!r}"
    )

    for row in rows:
        A.assert_money(
            row["sublimit_remaining_usd"], row["sublimit_usd"], f"{row['section_key']} remaining"
        )


# ==========================================================================
# Listing
# ==========================================================================
def test_applications_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10,
    accepts a minimum of 1 and a maximum of 100."
    PRD §2.3: "`offset` skips a number of rows from the front of the result set
    and defaults to 0."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/applications_list_paginates_with_total_count_and_has_more
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    account = X.create_account(api, C.ACCOUNT_AURORA)
    for aggregate in (250000, 500000, 750000):
        X.create_application(
            api,
            account["id"],
            requested_aggregate_limit_usd=aggregate,
            requested_retention_usd=0,
            dependent_bi_definition="NAMED_ONLY",
        )

    first = api.list_applications(
        UNDERWRITER_HEADERS,
        params={"insured_account_id": account["id"], "limit": 2, "offset": 0},
    )
    page_one, meta_one = validate_paginated(first)
    assert meta_one["total_count"] == 3, f"total_count: expected 3, got {meta_one['total_count']}"
    assert meta_one["has_more"] is True, "two of three rows returned, so has_more must be true"
    assert len(page_one) == 2, f"limit 2 must cap the page at 2 rows, got {len(page_one)}"
    assert first.json()["response_type"] == "array"

    second = api.list_applications(
        UNDERWRITER_HEADERS,
        params={"insured_account_id": account["id"], "limit": 2, "offset": 2},
    )
    page_two, meta_two = validate_paginated(second)
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False, "the final page must report has_more false"
    assert len(page_two) == 1, f"one row remains after offset 2, got {len(page_two)}"
    assert second.json()["response_type"] == "array"

    for row in page_one + page_two:
        assert row["insured_account_id"] == account["id"]


def test_panel_vendors_list_filtered_by_vendor_type_and_status(api):
    """PRD §3.7: "The panel register is readable by all five roles, ordered
    `tier` ascending, then `pre_approved_hourly_rate_usd` ascending, then
    `created_at` ascending — the very order the selector applies — and
    filterable by `vendor_type` and `status`; individual firms are readable by
    `vendor_id` including the live `active_engagement_count`."
    PRD §3.7: "`status` records panel standing as `ACTIVE`, `SUSPENDED`, or
    `RETIRED`, defaulting to `ACTIVE`."

    Design: Corner/entities/panel_vendors_list_filtered_by_vendor_type_and_status
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    active_forensics = X.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Ironclad Forensics",
            vendor_type="FORENSICS",
            pre_approved_hourly_rate_usd=500,
            per_record_notification_rate_usd=0.0,
            specialty_sectors=["HEALTHCARE", "FINANCIAL"],
            tier=1,
            capacity_concurrent_engagements=1,
        ),
    )
    suspended_forensics = X.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Dormant DFIR",
            vendor_type="FORENSICS",
            pre_approved_hourly_rate_usd=400,
            per_record_notification_rate_usd=0.0,
            specialty_sectors=["HEALTHCARE"],
            tier=2,
            capacity_concurrent_engagements=2,
            status="SUSPENDED",
        ),
    )
    notification_firm = X.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Postmark Notify",
            vendor_type="NOTIFICATION",
            pre_approved_hourly_rate_usd=200,
            per_record_notification_rate_usd=3.5,
            specialty_sectors=["HEALTHCARE", "TECHNOLOGY"],
            tier=1,
            capacity_concurrent_engagements=5,
        ),
    )

    resp = api.list_panel_vendors(
        ADJUSTER_HEADERS,
        params={"vendor_type": "FORENSICS", "status": "ACTIVE", "limit": 10, "offset": 0},
    )
    rows, meta = validate_paginated(resp)

    assert meta["total_count"] == 1, (
        f"only the active forensics firm matches both filters, got total_count {meta['total_count']}"
    )
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == active_forensics["id"]
    assert rows[0]["vendor_name"] == "Ironclad Forensics"

    returned_ids = {row["id"] for row in rows}
    assert suspended_forensics["id"] not in returned_ids, "a SUSPENDED firm must not match status ACTIVE"
    assert notification_firm["id"] not in returned_ids, "a NOTIFICATION firm must not match vendor_type FORENSICS"


# ==========================================================================
# Not found
# ==========================================================================
def test_policy_get_with_unknown_id_returns_not_found(api):
    """PRD §2.9: "The request fails on the *first* identifier that does not
    resolve, with the 404 error belonging to that identifier's type:
    `insured_account_id` yields `ERR_INSURED_ACCOUNT_NOT_FOUND`,
    `application_id` yields `ERR_APPLICATION_NOT_FOUND`, `scan_id` yields
    `ERR_EXTERNAL_SCAN_NOT_FOUND`, `policy_id` yields `ERR_POLICY_NOT_FOUND`"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/policy_get_with_unknown_id_returns_not_found
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    resp = api.get_policy(UNKNOWN_UUID, UNDERWRITER_HEADERS)
    error_data = validate_error(resp, ErrorId.POLICY_NOT_FOUND)

    assert resp.json()["response_type"] == "error"
    assert error_data["message"].strip(), "the error envelope must carry a non-empty message"


def test_application_create_with_unknown_insured_account_returns_not_found(api):
    """PRD §2.9: "An `insured_account_id` naming no account, an `application_id`
    naming no application, a `policy_id` naming no policy, a
    `systemic_event_scenario_id` naming no scenario, and a directed
    `panel_vendor_id` naming no panel firm each yield the corresponding 404."
    PRD §2.10: "**Body existence** — identifiers and keys supplied in the
    request body resolve, as described in §2.9; otherwise the matching 404."

    Design: Corner/entities/application_create_with_unknown_insured_account_returns_not_found
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    resp = api.create_application(
        {
            "insured_account_id": UNKNOWN_UUID,
            "requested_aggregate_limit_usd": 5000000,
            "requested_retention_usd": 250000,
            "dependent_bi_definition": "NAMED_ONLY",
        },
        UNDERWRITER_HEADERS,
    )
    validate_error(resp, ErrorId.INSURED_ACCOUNT_NOT_FOUND)


def test_attestation_under_unknown_application_returns_application_not_found(api):
    """PRD §2.9: "When a URL contains an identifier, that identifier must
    resolve to an existing row, and when it contains more than one, resolution
    proceeds strictly left to right — the outer segment first."
    PRD §2.9: "The request fails on the *first* identifier that does not
    resolve, with the 404 error belonging to that identifier's type:
    `insured_account_id` yields `ERR_INSURED_ACCOUNT_NOT_FOUND`,
    `application_id` yields `ERR_APPLICATION_NOT_FOUND`"
    PRD §2.10: "**Path existence** — every identifier in the URL resolves, left
    to right, as described in §2.9; otherwise the matching 404."

    Design: Corner/entities/attestation_under_unknown_application_returns_application_not_found
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    X.seed_catalog(api)

    resp = api.create_control_attestation(
        UNKNOWN_UUID,
        F.control_attestation_payload("MFA_PRIVILEGED", "FULL"),
        UNDERWRITER_HEADERS,
    )
    validate_error(resp, ErrorId.APPLICATION_NOT_FOUND)


def test_claim_create_with_unknown_systemic_scenario_returns_not_found(api):
    """PRD §3.6: "An optional `systemic_event_scenario_id` tags the claim to a
    modelled systemic event and, when supplied, must name an existing scenario."
    PRD §2.9: "An `insured_account_id` naming no account, an `application_id`
    naming no application, a `policy_id` naming no policy, a
    `systemic_event_scenario_id` naming no scenario, and a directed
    `panel_vendor_id` naming no panel firm each yield the corresponding 404."

    Design: Corner/entities/claim_create_with_unknown_systemic_scenario_returns_not_found
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.bound_policy(api, findings=EMAIL_FILTERING_HIGH)
    policy = chain["policy"]
    X.set_clock(api, "2026-09-10T00:00:00Z")

    resp = api.create_incident_claim(
        {
            "policy_id": policy["id"],
            "incident_type": "RANSOMWARE",
            "incident_discovered_at": "2026-09-05T00:00:00Z",
            "outage_start_at": "2026-09-05T00:00:00Z",
            "outage_end_at": "2026-09-08T00:00:00Z",
            "systemic_event_scenario_id": UNKNOWN_UUID,
        },
        ADJUSTER_HEADERS,
    )
    validate_error(resp, ErrorId.SYSTEMIC_SCENARIO_NOT_FOUND)

    A.assert_total_count(
        api.list_incident_claims(ADJUSTER_HEADERS, params={"policy_id": policy["id"]}), 0
    )


# ==========================================================================
# Required fields
# ==========================================================================
def test_application_create_missing_dependent_bi_definition_returns_invalid_request(api):
    """PRD §3.2: "`dependent_bi_definition` fixes the breadth of dependent
    business interruption wording sought and is one of `NAMED_ONLY`,
    `NAMED_PLUS_SUPPLY_CHAIN`, or `BROAD_SYSTEM_FAILURE`."
    PRD §2.10: "**Schema** — required fields present, enum values inside their
    declared domains, non-negative numerics, monetary fields at most 2 decimals,
    ratio fields inside range (`coinsurance_pct` at most 0.50,
    `gross_profit_margin_pct` at most 1.00, `footprint_pct` at most 1.00),
    timestamps in ISO 8601 UTC, interval fields correctly ordered
    (`period_start` before `period_end`, `outage_start_at` before
    `outage_end_at`, `deployment_start_at` before `deployment_end_at`),
    `waiting_period_hours` greater than 0 and required for a
    `BUSINESS_INTERRUPTION` or `DEPENDENT_BI` section and absent — null — for
    every other section key, and `requested_aggregate_limit_usd` at least the
    250,000 minimum; otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/application_create_missing_dependent_bi_definition_returns_invalid_request
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    account = X.create_account(api, C.ACCOUNT_AURORA)

    resp = api.create_application(
        {
            "insured_account_id": account["id"],
            "requested_aggregate_limit_usd": 5000000,
            "requested_retention_usd": 250000,
        },
        UNDERWRITER_HEADERS,
    )
    validate_error(resp, ErrorId.INVALID_REQUEST)

    A.assert_total_count(
        api.list_applications(
            UNDERWRITER_HEADERS, params={"insured_account_id": account["id"]}
        ),
        0,
    )


# ==========================================================================
# Declared defaults
# ==========================================================================
def test_control_requirement_defaults_non_mandatory_and_thirty_grace_days(api):
    """PRD §3.1: "`is_mandatory` is a boolean that defaults to false; when it is
    true, a verified maturity below `min_level_required` blocks both quoting and
    binding outright rather than merely depressing the score."
    PRD §3.1: "A fourth field, `remediation_grace_days`, records how many days
    the insured is granted to fix this control at renewal; it defaults to 30 and
    must be at least 0 and at most 365."
    PRD §3.1: "The catalog is readable by all five roles, returned in `weight`
    descending then `control_key` ascending order, and can be narrowed to
    mandatory entries alone with an `is_mandatory` filter."

    Design: Corner/entities/control_requirement_defaults_non_mandatory_and_thirty_grace_days
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    resp = api.create_control_requirement(
        {
            "control_key": "EMAIL_FILTERING",
            "min_level_required": "PARTIAL",
            "weight": 15,
        },
        UNDERWRITER_HEADERS,
    )
    row = validate_success(resp, 201)

    assert row["is_mandatory"] is False, (
        f"is_mandatory defaults to false, got {row['is_mandatory']!r}"
    )
    assert row["remediation_grace_days"] == 30, (
        f"remediation_grace_days defaults to 30, got {row['remediation_grace_days']!r}"
    )

    A.assert_total_count(
        api.list_control_requirements(UNDERWRITER_HEADERS, params={"is_mandatory": "true"}),
        0,
    )


def test_panel_vendor_defaults_active_zero_record_rate_and_no_engagements(api):
    """PRD §3.7: "Commercially it records a `pre_approved_hourly_rate_usd`
    strictly greater than zero — the ceiling rate negotiated with the firm — and
    a `per_record_notification_rate_usd`, the ceiling per-record price for
    notification mailings, which defaults to 0.00 and must be at least zero."
    PRD §3.7: "`status` records panel standing as `ACTIVE`, `SUSPENDED`, or
    `RETIRED`, defaulting to `ACTIVE`."
    PRD §3.7: "A computed `active_engagement_count`, starting at 0, is the
    conserved slot quantity: it is the number of engagements on that firm whose
    `status` is `AUTHORIZED` or `ACTIVE`."

    Design: Corner/entities/panel_vendor_defaults_active_zero_record_rate_and_no_engagements
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    resp = api.create_panel_vendor(
        {
            "vendor_name": "Harbor PR",
            "vendor_type": "PR_CRISIS",
            "pre_approved_hourly_rate_usd": 300,
            "specialty_sectors": ["HEALTHCARE"],
            "tier": 2,
            "capacity_concurrent_engagements": 3,
        },
        PANEL_ADMIN_HEADERS,
    )
    row = validate_success(resp, 201)

    assert row["status"] == "ACTIVE", f"status defaults to ACTIVE, got {row['status']!r}"
    A.assert_money(
        row["per_record_notification_rate_usd"], 0.00, "per_record_notification_rate_usd"
    )
    assert row["active_engagement_count"] == 0, (
        f"active_engagement_count starts at 0, got {row['active_engagement_count']!r}"
    )


def test_incident_claim_defaults_dependency_none_records_zero_and_no_reservation(api):
    """PRD §3.6: "`dependency_key` names the third-party dependency that failed,
    defaults to `NONE`, is drawn from `CSP_ALPHA`, `CSP_BETA`, `MSSP_DELTA`, and
    `NONE`, and is required when `incident_type` is `DEPENDENT_OUTAGE`."
    PRD §3.6: "`affected_record_count` sizes the notification workload, defaults
    to 0, and must be at least zero."
    PRD §3.6: "The claim opens in `NOTIFIED` with `reserved_amount_usd`,
    `retention_absorbed_usd`, `paid_total_usd`, and `unallocated_loss_usd` all at
    0.00 and `proof_review_round` at 0."

    Design: Corner/entities/incident_claim_defaults_dependency_none_records_zero_and_no_reservation
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.bound_policy(api, findings=EMAIL_FILTERING_HIGH)
    policy = chain["policy"]
    X.set_clock(api, "2026-09-10T00:00:00Z")

    resp = api.create_incident_claim(
        {
            "policy_id": policy["id"],
            "incident_type": "BEC",
            "incident_discovered_at": "2026-09-05T00:00:00Z",
        },
        ADJUSTER_HEADERS,
    )
    claim = validate_success(resp, 201)

    assert claim["dependency_key"] == "NONE", (
        f"dependency_key defaults to NONE, got {claim['dependency_key']!r}"
    )
    assert claim["affected_record_count"] == 0, (
        f"affected_record_count defaults to 0, got {claim['affected_record_count']!r}"
    )
    A.assert_money(claim["reserved_amount_usd"], 0.00, "reserved_amount_usd")
    A.assert_money(claim["retention_absorbed_usd"], 0.00, "retention_absorbed_usd")
    A.assert_money(claim["paid_total_usd"], 0.00, "paid_total_usd")
    A.assert_money(claim["unallocated_loss_usd"], 0.00, "unallocated_loss_usd")
    assert claim["proof_review_round"] == 0, (
        f"proof_review_round opens at 0, got {claim['proof_review_round']!r}"
    )


# ==========================================================================
# Computed fields
# ==========================================================================
def test_application_attested_score_and_indicative_premium_computed_at_submit(api):
    """PRD §3.2: "On success the server recomputes `attested_control_score` on
    the attested basis, writes `indicative_premium_usd` from the attested-basis
    pricing run, and increments the application's `version` by 1."
    PRD §3.4: "The numerator is the sum, taken across every control requirement
    row in the catalog, of that requirement's `weight` multiplied by the factor
    of the level established for its `control_key`."
    PRD §3.4: "The score is 100 multiplied by the numerator divided by the
    denominator, rounded half up to 2 decimal places."
    PRD §3.4: "The gross premium is the base rate multiplied by the revenue tier
    factor multiplied by the layer units, rounded half up to 2 decimal places."
    PRD §3.4: "The **indicative run** fires at submission, consumes
    `attested_control_score`, and writes `indicative_premium_usd` — a figure
    issued before any scan can contradict the applicant."
    PRD §3.4: "On the **verified basis**, a completed scan is required."

    Design: Corner/entities/application_attested_score_and_indicative_premium_computed_at_submit
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    X.seed_catalog(api)
    account = X.create_account(api, C.ACCOUNT_AURORA)
    application = X.create_application(
        api,
        account["id"],
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
    )
    X.attest_controls(api, application["id"], C.ATTEST_95)

    submitted = validate_success(api.submit_application(application["id"], UNDERWRITER_HEADERS))

    assert submitted["status"] == "SUBMITTED"
    A.assert_score_2dp(submitted["attested_control_score"], 95.00, "attested_control_score")
    A.assert_money(submitted["indicative_premium_usd"], 25398.00, "indicative_premium_usd")
    assert submitted["verified_control_score"] is None, (
        "the verified basis requires a completed scan, so verified_control_score is still null: "
        f"{submitted['verified_control_score']!r}"
    )
    assert submitted["premium_usd"] is None, (
        f"premium_usd is written only by the bindable run, got {submitted['premium_usd']!r}"
    )
    assert submitted["mandatory_gap_count"] == 0
    assert submitted["mandatory_gap_control_keys"] == []


def test_external_scan_critical_finding_count_computed_from_findings(api):
    """PRD §3.3: "The completion also computes `critical_finding_count`, the
    number of `findings` entries whose `severity` is `CRITICAL`, which starts at
    0 when nothing critical was seen."
    PRD §3.3: "Both outcomes stamp `completed_at` from the logical clock and
    increment the scan's `version` by 1, and both are terminal for the scan."
    PRD §3.3: "A control absent from the array altogether is treated as observed
    at `FULL`: silence from the scanner is not evidence against the applicant."
    PRD §3.3: "Because the attestation rows changed, the application's
    `verified_control_score`, `mandatory_gap_count`, and
    `mandatory_gap_control_keys` are recomputed on the verified basis, and the
    application moves from `SUBMITTED` to `UNDERWRITING`."

    Design: Corner/entities/external_scan_critical_finding_count_computed_from_findings
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    X.seed_catalog(api)
    account = X.create_account(api, C.ACCOUNT_AURORA)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])

    X.set_clock(api, "2026-08-05T00:00:00Z")
    scan = X.order_scan(api, application["id"], scan_score=55)

    completed = validate_success(
        api.complete_external_scan(
            scan["id"],
            {
                "outcome": "COMPLETED",
                "findings": [
                    {
                        "control_key": "EMAIL_FILTERING",
                        "severity": "CRITICAL",
                        "observed_level": "PARTIAL",
                    },
                    {
                        "control_key": "INCIDENT_RESPONSE_PLAN",
                        "severity": "CRITICAL",
                        "observed_level": "NONE",
                    },
                    {
                        "control_key": "EDR_COVERAGE",
                        "severity": "LOW",
                        "observed_level": "FULL",
                    },
                ],
            },
            UNDERWRITER_HEADERS,
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["critical_finding_count"] == 2, (
        "two of the three findings carry severity CRITICAL, got "
        f"{completed['critical_finding_count']!r}"
    )
    _assert_same_instant(completed["completed_at"], "2026-08-05T00:00:00Z", "completed_at")

    after = X.read_application(api, application["id"])
    A.assert_score_2dp(after["verified_control_score"], 82.50, "verified_control_score")
    assert after["mandatory_gap_count"] == 0
    assert after["status"] == "UNDERWRITING"


# ==========================================================================
# System-owned fields
# ==========================================================================
def test_insured_account_system_fields_generated_and_client_id_input_ignored(api):
    """PRD §2.4: "Each persisted row is addressed by an `id`, which is a
    server-minted UUID with no type prefix of any kind."
    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp refreshed on every
    change to the row, and `version` is an integer that starts at 1 and
    increments by exactly 1 on every mutation."
    PRD §2.5: "Before any call is made the clock reads exactly
    `2026-08-01T00:00:00Z`, and it changes only when a caller sets it explicitly
    by supplying `current_utc`; the clock endpoint echoes back the instant it now
    holds."
    PRD §3.2: "The account also exposes a computed `open_remediation_count`,
    which starts at 0 and tracks how many of this applicant's applications
    currently sit in remediation."

    Design: Corner/entities/insured_account_system_fields_generated_and_client_id_input_ignored
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    resp = api.create_insured_account(
        {
            "legal_name": "Aurora Health",
            "industry_code": "HEALTHCARE",
            "annual_revenue_usd": 43800000,
            "record_count": 12345,
            "primary_dependency_key": "CSP_ALPHA",
            "id": UNKNOWN_UUID,
            "version": 99,
        },
        UNDERWRITER_HEADERS,
    )
    row = validate_success(resp, 201)

    assert is_valid_uuid(row["id"]), f"id must be a bare server-minted UUID: {row['id']!r}"
    assert row["id"] != UNKNOWN_UUID, "the client-supplied id must not become the row's id"
    assert row["version"] == 1, f"version starts at 1, not the submitted 99: {row['version']!r}"
    _assert_same_instant(row["created_at"], C.DEFAULT_CLOCK, "created_at")
    _assert_same_instant(row["updated_at"], C.DEFAULT_CLOCK, "updated_at")
    assert row["open_remediation_count"] == 0


def test_incident_claim_notified_at_stamped_from_logical_clock(api):
    """PRD §3.6: "And the notification must be timely: `notified_at` is stamped
    from the logical clock at acceptance, and the elapsed time from
    `incident_discovered_at` to `notified_at` must be no more than 30 days, a
    longer delay yielding `ERR_LATE_NOTIFICATION`."
    PRD §2.5: "The server does not read wall-clock time."
    PRD §3.6: "The claim opens in `NOTIFIED` with `reserved_amount_usd`,
    `retention_absorbed_usd`, `paid_total_usd`, and `unallocated_loss_usd` all at
    0.00 and `proof_review_round` at 0."
    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp refreshed on every
    change to the row, and `version` is an integer that starts at 1 and
    increments by exactly 1 on every mutation."

    Design: Corner/entities/incident_claim_notified_at_stamped_from_logical_clock
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.bound_policy(api, findings=EMAIL_FILTERING_HIGH)
    policy = chain["policy"]
    X.set_clock(api, "2026-09-10T00:00:00Z")

    claim = validate_success(
        api.create_incident_claim(
            {
                "policy_id": policy["id"],
                "incident_type": "DATA_THEFT",
                "incident_discovered_at": "2026-09-05T00:00:00Z",
                "affected_record_count": 400,
            },
            ADJUSTER_HEADERS,
        ),
        201,
    )

    _assert_same_instant(claim["notified_at"], "2026-09-10T00:00:00Z", "notified_at")
    _assert_same_instant(
        claim["incident_discovered_at"], "2026-09-05T00:00:00Z", "incident_discovered_at"
    )
    assert claim["status"] == "NOTIFIED"
    assert claim["version"] == 1, f"a freshly written row is at version 1, got {claim['version']!r}"


# ==========================================================================
# Declared type constraints
# ==========================================================================
def test_panel_vendor_tier_above_three_returns_invalid_request(api):
    """PRD §3.7: "`tier` is an integer of at least 1 and at most 3 expressing
    panel preference, where 1 is most preferred."
    PRD §2.10: "**Schema** — required fields present, enum values inside their
    declared domains, non-negative numerics, monetary fields at most 2 decimals,
    ratio fields inside range (`coinsurance_pct` at most 0.50,
    `gross_profit_margin_pct` at most 1.00, `footprint_pct` at most 1.00),
    timestamps in ISO 8601 UTC, interval fields correctly ordered
    (`period_start` before `period_end`, `outage_start_at` before
    `outage_end_at`, `deployment_start_at` before `deployment_end_at`),
    `waiting_period_hours` greater than 0 and required for a
    `BUSINESS_INTERRUPTION` or `DEPENDENT_BI` section and absent — null — for
    every other section key, and `requested_aggregate_limit_usd` at least the
    250,000 minimum; otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/panel_vendor_tier_above_three_returns_invalid_request
    """
    X.set_clock(api, C.DEFAULT_CLOCK)

    resp = api.create_panel_vendor(
        {
            "vendor_name": "Fourth Tier Forensics",
            "vendor_type": "FORENSICS",
            "pre_approved_hourly_rate_usd": 400,
            "per_record_notification_rate_usd": 0.0,
            "specialty_sectors": ["HEALTHCARE"],
            "tier": 4,
            "capacity_concurrent_engagements": 2,
        },
        PANEL_ADMIN_HEADERS,
    )
    validate_error(resp, ErrorId.INVALID_REQUEST)

    A.assert_total_count(
        api.list_panel_vendors(PANEL_ADMIN_HEADERS, params={"vendor_type": "FORENSICS"}), 0
    )


def test_coverage_section_coinsurance_above_cap_returns_invalid_request(api):
    """PRD §3.5: "`coinsurance_pct` is the insured's share of each allocated loss
    dollar on that section; it defaults to 0.00 and must be at least 0 and at
    most 0.50."
    PRD §2.10: "**Schema** — required fields present, enum values inside their
    declared domains, non-negative numerics, monetary fields at most 2 decimals,
    ratio fields inside range (`coinsurance_pct` at most 0.50,
    `gross_profit_margin_pct` at most 1.00, `footprint_pct` at most 1.00),
    timestamps in ISO 8601 UTC, interval fields correctly ordered
    (`period_start` before `period_end`, `outage_start_at` before
    `outage_end_at`, `deployment_start_at` before `deployment_end_at`),
    `waiting_period_hours` greater than 0 and required for a
    `BUSINESS_INTERRUPTION` or `DEPENDENT_BI` section and absent — null — for
    every other section key, and `requested_aggregate_limit_usd` at least the
    250,000 minimum; otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/coverage_section_coinsurance_above_cap_returns_invalid_request
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.quoted_application(api, findings=EMAIL_FILTERING_HIGH)
    application = chain["application"]

    current = X.read_application(api, application["id"])
    resp = api.bind_application(
        application["id"],
        {
            "expected_application_version": current["version"],
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2027-08-01T00:00:00Z",
            "bi_baseline_method": "TRAILING_12M",
            "coverage_sections": [
                {
                    "section_key": "FIRST_PARTY_RESPONSE",
                    "sublimit_usd": 1000000,
                    "waiting_period_hours": None,
                    "coinsurance_pct": 0.0,
                    "erosion_priority": 10,
                },
                {
                    "section_key": "BUSINESS_INTERRUPTION",
                    "sublimit_usd": 2000000,
                    "waiting_period_hours": 12,
                    "coinsurance_pct": 0.6,
                    "erosion_priority": 20,
                },
            ],
        },
        UNDERWRITER_2_HEADERS,
    )
    validate_error(resp, ErrorId.INVALID_REQUEST)

    after = X.read_application(api, application["id"])
    assert after["status"] == "QUOTED", (
        f"a refused bind leaves the application QUOTED, got {after['status']!r}"
    )
    A.assert_total_count(
        api.list_policies(UNDERWRITER_HEADERS, params={"application_id": application["id"]}), 0
    )


def test_waiting_period_on_non_bi_section_must_be_null_returns_invalid_request(api):
    """PRD §3.5: "`waiting_period_hours` is the time deductible: it is required
    and strictly greater than zero, and at most 168, for `BUSINESS_INTERRUPTION`
    and `DEPENDENT_BI`, and must be null for every other section key — supplying
    it on a non-interruption section, or omitting it on an interruption section,
    is an `ERR_INVALID_REQUEST`."

    Design: Corner/entities/waiting_period_on_non_bi_section_must_be_null_returns_invalid_request
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.quoted_application(api, findings=EMAIL_FILTERING_HIGH)
    application = chain["application"]

    current = X.read_application(api, application["id"])
    resp = api.bind_application(
        application["id"],
        {
            "expected_application_version": current["version"],
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2027-08-01T00:00:00Z",
            "bi_baseline_method": "TRAILING_12M",
            "coverage_sections": [
                {
                    "section_key": "FIRST_PARTY_RESPONSE",
                    "sublimit_usd": 1000000,
                    "waiting_period_hours": 6,
                    "coinsurance_pct": 0.0,
                    "erosion_priority": 10,
                },
                {
                    "section_key": "BUSINESS_INTERRUPTION",
                    "sublimit_usd": 2000000,
                    "waiting_period_hours": 12,
                    "coinsurance_pct": 0.1,
                    "erosion_priority": 20,
                },
            ],
        },
        UNDERWRITER_2_HEADERS,
    )
    validate_error(resp, ErrorId.INVALID_REQUEST)

    A.assert_total_count(
        api.list_policies(UNDERWRITER_HEADERS, params={"application_id": application["id"]}), 0
    )


def test_policy_period_end_before_start_returns_invalid_request(api):
    """PRD §3.5: "`period_start` and `period_end` bound the policy period, with
    `period_end` strictly after `period_start`; the period is half-open, covering
    `period_start` and every instant up to but not including `period_end`."
    PRD §2.10: "**Schema** — required fields present, enum values inside their
    declared domains, non-negative numerics, monetary fields at most 2 decimals,
    ratio fields inside range (`coinsurance_pct` at most 0.50,
    `gross_profit_margin_pct` at most 1.00, `footprint_pct` at most 1.00),
    timestamps in ISO 8601 UTC, interval fields correctly ordered
    (`period_start` before `period_end`, `outage_start_at` before
    `outage_end_at`, `deployment_start_at` before `deployment_end_at`),
    `waiting_period_hours` greater than 0 and required for a
    `BUSINESS_INTERRUPTION` or `DEPENDENT_BI` section and absent — null — for
    every other section key, and `requested_aggregate_limit_usd` at least the
    250,000 minimum; otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §2.10: "Later checks never mask earlier ones."

    Design: Corner/entities/policy_period_end_before_start_returns_invalid_request
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = X.quoted_application(api, findings=EMAIL_FILTERING_HIGH)
    application = chain["application"]

    current = X.read_application(api, application["id"])
    resp = api.bind_application(
        application["id"],
        F.bind_payload(
            current["version"],
            period_start="2027-08-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
            bi_baseline_method="TRAILING_12M",
            coverage_sections=list(C.STANDARD_TOWER),
            named_dependency_keys=["CSP_ALPHA"],
        ),
        UNDERWRITER_2_HEADERS,
    )
    # The schema rule on interval ordering outranks the period-overlap
    # constraint, so the client sees the 400, never ERR_POLICY_PERIOD_OVERLAP.
    validate_error(resp, ErrorId.INVALID_REQUEST)

    after = X.read_application(api, application["id"])
    assert after["status"] == "QUOTED", (
        f"a refused bind leaves the application QUOTED, got {after['status']!r}"
    )


# ==========================================================================
# Immutability of the control catalog
# ==========================================================================
def test_control_requirement_is_immutable_with_no_update_endpoint_and_no_version(api):
    """PRD §2.4: "A catalog entry is immutable once created — there is no
    endpoint that amends it — and it therefore carries only `id` and
    `created_at`."
    PRD §2.4: "Both `updated_at` and `version` are absent from a control
    requirement row entirely."
    PRD §3.1: "Catalog entries are permanent."
    PRD §3.1: "The catalog is readable by all five roles, returned in `weight`
    descending then `control_key` ascending order, and can be narrowed to
    mandatory entries alone with an `is_mandatory` filter."

    Design: Corner/entities/control_requirement_is_immutable_with_no_update_endpoint_and_no_version
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    mfa = validate_success(
        api.create_control_requirement(
            {
                "control_key": "MFA_PRIVILEGED",
                "min_level_required": "FULL",
                "weight": 30,
                "is_mandatory": True,
            },
            UNDERWRITER_HEADERS,
        ),
        201,
    )
    validate_success(
        api.create_control_requirement(
            {
                "control_key": "OFFLINE_BACKUPS",
                "min_level_required": "FULL",
                "weight": 25,
                "is_mandatory": True,
            },
            UNDERWRITER_HEADERS,
        ),
        201,
    )

    assert "version" not in mfa, "a control requirement row must expose no version field"
    assert "updated_at" not in mfa, "a control requirement row must expose no updated_at field"

    rows, meta = validate_paginated(
        api.list_control_requirements(UNDERWRITER_HEADERS, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2, f"total_count: expected 2, got {meta['total_count']}"
    for row in rows:
        assert "version" not in row, f"version must be absent from {row['control_key']}"
        assert "updated_at" not in row, f"updated_at must be absent from {row['control_key']}"

    assert [row["control_key"] for row in rows] == ["MFA_PRIVILEGED", "OFFLINE_BACKUPS"], (
        "weight descending puts MFA_PRIVILEGED (30) before OFFLINE_BACKUPS (25), got "
        f"{[row['control_key'] for row in rows]}"
    )
