"""Privacy requests, the deferred purge run, and role / ownership / authentication gates."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    CLOCK_START,
    EXPORT_URL_PREFIX,
    validate_success,
    validate_error,
    validate_paginated,
    assert_data_request,
    assert_instant_equals,
    make_customer_headers,
    make_lab_technician_headers,
    make_privacy_officer_headers,
    make_platform_admin_headers,
    NO_AUTH_HEADERS,
    factories as f,
    fixtures as fx,
)

ADMIN = make_platform_admin_headers()
LAB = make_lab_technician_headers()


# ═══════════════════════════════════════════════════════════════════════════
# Privacy requests
# ═══════════════════════════════════════════════════════════════════════════

def test_approving_an_export_request_completes_it_and_mints_the_url(api):
    """PRD §3.10: "For an `EXPORT` request, the approval completes immediately: the request
    moves `PENDING → COMPLETED`, and `export_url` is minted as the literal prefix
    `https://export.dna.example/` followed by the request's own identifier. Its
    `scheduled_purge_at` stays null."
    PRD §3.10: "In all three outcomes the officer's `X-User-ID` is recorded in
    `reviewed_by`."

    Design: Corner/state_machines/data_request_export_approval_completes_with_export_url
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="e@dna.test", display_name="Eve")
    request = fx.file_data_request(customer["id"], "EXPORT")

    data = validate_success(
        api.decide_data_request(
            request["id"], f.decide_payload("APPROVE"), make_privacy_officer_headers("po-1")
        )
    )
    assert_data_request(data)

    assert data["status"] == "COMPLETED"
    assert data["export_url"] == f"{EXPORT_URL_PREFIX}{request['id']}", (
        f"Expected the export_url to be the literal prefix plus the request id, "
        f"got {data['export_url']}"
    )
    assert data["scheduled_purge_at"] is None
    assert data["reviewed_by"] == "po-1"
    assert fx.read_customer(customer["id"])["account_status"] == "ACTIVE"


def test_filing_a_second_open_request_is_rejected(api):
    """PRD §3.10: "A customer may only ever have one request open at a time: if any of their
    existing requests is in `PENDING` or `SCHEDULED` status, the new filing is refused with
    `ERR_PENDING_DATA_REQUEST` (HTTP 409)."

    Design: Corner/validations/second_open_data_request_returns_pending_data_request
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="dup@dna.test", display_name="Dup")
    headers = make_customer_headers(customer["id"])
    first = fx.file_data_request(customer["id"], "EXPORT")

    resp = api.create_data_request(
        f.create_data_request_payload(customer["id"], request_type="DELETE"), headers
    )
    validate_error(resp, ApiErrorId.ERR_PENDING_DATA_REQUEST.value, 409)

    requests, meta = validate_paginated(
        api.list_data_requests(headers, params={"customer_id": customer["id"]})
    )
    assert meta["total_count"] == 1, f"Expected exactly 1 request, got {meta['total_count']}"
    assert requests[0]["id"] == first["id"]
    assert requests[0]["status"] == "PENDING"


def test_purge_run_executes_a_due_delete_request_and_purges_the_customer(api):
    """PRD §3.10: "For a `DELETE` request, the approval schedules rather than executes: the
    request moves `PENDING → SCHEDULED`, and `scheduled_purge_at` is set to the current
    logical-clock instant plus seven days."
    PRD §3.10: "An operator runs a purge checkpoint, which sweeps every request whose
    `status` is `SCHEDULED` and whose `scheduled_purge_at` is at or before the current
    logical-clock instant — the boundary is inclusive, so a request whose purge instant
    equals the clock exactly is executed."
    PRD §3.10: "Their `account_status` and `dna_status` both become `PURGED`. Every one of
    their consent grants still in `ACTIVE` status transitions to `WITHDRAWN`. Every one of
    their reports in `DRAFT` or `PUBLISHED` status transitions to `REVOKED`."

    Design: Corner/state_machines/purge_run_executes_due_delete_request_and_purges_customer
    """
    fx.set_clock(CLOCK_START)
    p = fx.setup_dna_ready_customer(email="d@dna.test", display_name="Dee", tier="PLUS")
    customer_id = p["customer"]["id"]
    grant = fx.grant_consent(customer_id, "RESEARCH")
    report = fx.publish_report(customer_id, "ETHNICITY", "PROVISIONAL")

    scheduled = fx.setup_scheduled_delete(customer_id)
    assert scheduled["status"] == "SCHEDULED"
    assert_instant_equals(
        scheduled["scheduled_purge_at"], "2026-05-08T00:00:00Z", "scheduled_purge_at"
    )

    # One day early: nothing is due.
    fx.set_clock("2026-05-07T00:00:00Z")
    early = validate_success(api.purge_run(ADMIN))
    assert early["purged_count"] == 0, "A request that is not yet due must not be executed"

    # Exactly at the purge instant: the boundary is inclusive.
    fx.set_clock("2026-05-08T00:00:00Z")
    due = validate_success(api.purge_run(ADMIN))
    assert due["purged_count"] == 1
    assert scheduled["id"] in due["completed_request_ids"]

    assert fx.read_data_request(scheduled["id"], customer_id)["status"] == "COMPLETED"
    purged = fx.read_customer(customer_id)
    assert purged["account_status"] == "PURGED"
    assert purged["dna_status"] == "PURGED"
    assert fx.read_report(report["id"], customer_id)["status"] == "REVOKED"
    assert fx.read_consent_grant(grant["id"], customer_id)["status"] == "WITHDRAWN"


def test_cancelling_a_scheduled_delete_before_its_purge_instant_succeeds(api):
    """PRD §3.10: "A customer may cancel their own request from `PENDING` status, and from
    `SCHEDULED` status provided the current logical-clock instant is strictly before
    `scheduled_purge_at`."
    PRD §3.10: "Requests in `PENDING`, `CANCELLED`, `REJECTED`, or `COMPLETED` status are
    ignored entirely."

    Design: Corner/state_machines/cancel_scheduled_delete_before_purge_instant_succeeds
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="g@dna.test", display_name="Gus")
    scheduled = fx.setup_scheduled_delete(customer["id"])

    fx.set_clock("2026-05-05T00:00:00Z")
    cancelled = validate_success(
        api.cancel_data_request(scheduled["id"], make_customer_headers(customer["id"]))
    )
    assert cancelled["status"] == "CANCELLED"

    fx.set_clock("2026-05-08T00:00:00Z")
    result = validate_success(api.purge_run(ADMIN))
    assert result["purged_count"] == 0, "A cancelled request must be ignored by the purge run"

    assert fx.read_customer(customer["id"])["account_status"] == "ACTIVE"


def test_writes_against_a_purged_customer_are_rejected(api):
    """PRD §3.6: "A customer whose `account_status` is `PURGED` cannot grant consent at all
    (`ERR_CUSTOMER_PURGED`)."
    PRD §2.6: "8. Purged-account rejection (`ERR_CUSTOMER_PURGED`)."

    Design: Corner/cross_cutting/writes_against_purged_customer_return_customer_purged
    """
    setup = fx.setup_purged_customer(email="pg@dna.test")
    customer_id = setup["customer"]["id"]
    headers = make_customer_headers(customer_id)
    assert setup["customer"]["account_status"] == "PURGED"

    resp = api.create_consent_grant(
        f.create_consent_payload(
            customer_id,
            "RESEARCH",
            effective_from="2026-05-08T00:00:00Z",
            effective_until="2026-12-31T00:00:00Z",
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_PURGED.value, 409)

    _grants, meta = validate_paginated(
        api.list_consent_grants(ADMIN, params={"customer_id": customer_id})
    )
    assert meta["total_count"] == 0, "The rejected grant must not be persisted"


# ═══════════════════════════════════════════════════════════════════════════
# Authentication, role authorization and ownership
# ═══════════════════════════════════════════════════════════════════════════

def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, declaring the capacity in which that principal
    is acting. If either header is absent, or if `X-User-Role` is not one of the four
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.get_customer(UNKNOWN_UUID, NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_lab_technician_cannot_generate_a_report(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not among the roles
    authorized for the requested endpoint (see the table in Section 4), the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/dna/customers/{id}/reports` | Generate and publish a report from the
    customer's genotyped sample. Consent-gated and concurrency-guarded. | `Customer` |"

    Design: Corner/rbac/lab_technician_cannot_generate_report_returns_forbidden_role
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="rb1@dna.test", display_name="Rb1")
    fx.create_subscription(customer["id"], "PLUS")
    version = fx.read_customer_version(customer["id"])

    resp = api.generate_report(
        customer["id"],
        f.generate_report_payload(version, report_type="ETHNICITY", variant="PROVISIONAL"),
        LAB,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    _reports, meta = validate_paginated(
        api.list_reports(
            make_customer_headers(customer["id"]), params={"customer_id": customer["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_customer_cannot_decide_their_own_data_request(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not among the roles
    authorized for the requested endpoint (see the table in Section 4), the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/dna/data-requests/{id}/decide` | Privacy officer decision on a
    pending request. | `PrivacyOfficer` |"

    Design: Corner/rbac/customer_cannot_decide_own_data_request
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="rb2@dna.test", display_name="Rb2")
    headers = make_customer_headers(customer["id"])
    request = fx.file_data_request(customer["id"], "DELETE")

    resp = api.decide_data_request(request["id"], f.decide_payload("APPROVE"), headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    after = fx.read_data_request(request["id"], customer["id"])
    assert after["status"] == "PENDING"
    assert after["scheduled_purge_at"] is None


def test_customer_cannot_activate_another_customers_kit(api):
    """PRD §2.1: "A `Customer` may only act on their own subscriptions, kits, consent grants,
    reports, relative matches, family trees, tree people, record hints, and data requests.
    Reaching for a resource that belongs to a different Customer yields
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    Customer record; ownership checks on any resource that references a Customer compare the
    resource's owning-customer field to `X-User-ID`."

    Design: Corner/rbac/customer_cannot_activate_another_customers_kit
    """
    fx.set_clock(CLOCK_START)
    owner = fx.create_customer(email="own1@dna.test", display_name="Own1")
    fx.create_subscription(owner["id"], "PLUS")
    kit = fx.create_kit(owner["id"], "V5")

    intruder = fx.create_customer(email="own2@dna.test", display_name="Own2")
    fx.create_subscription(intruder["id"], "PLUS")

    # The barcode is correct — only the caller's identity is wrong.
    resp = api.activate_kit(
        kit["id"], f.activate_kit_payload(kit["barcode"]), make_customer_headers(intruder["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert fx.read_kit(kit["id"])["status"] == "ORDERED"
