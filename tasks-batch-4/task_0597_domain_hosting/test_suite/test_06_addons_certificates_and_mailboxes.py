"""SSL certificates (DNS-01 validation, interval buffer) and mailboxes (conserved storage)."""
from test_helpers import (
    ApiErrorId,
    create_mailbox,
    create_mailbox_payload,
    create_ssl_cert,
    create_ssl_payload,
    get_add_on,
    get_subscription,
    make_registrant_headers,
    publish_acme_challenge,
    setup_hosting_stack,
    create_and_validate_ssl_cert,
    create_dns_record,
    validate_error,
    validate_paginated,
    validate_success,
)


# =========================================================================
# DNS-01 validation depends on the zone's TXT record  (Difficulty/cross_entity)
# =========================================================================

def test_ssl_validation_without_the_acme_txt_record_fails(api):
    """PRD §3.5: "The owner publishes a `TXT` record on the certificate's domain, named
    `_acme-challenge`, whose `value` equals the certificate's `validation_token`, and then
    asks the system to validate."
    PRD §3.5: "If no such `TXT` record is found, validation fails with
    `ERR_DNS_VALIDATION_FAILED`."

    Design: Difficulty/cross_entity_state_dependency/ssl_validation_depends_on_txt_dns_record_of_the_domain
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    cert = create_ssl_cert(account, subscription, domain, term_days=90)

    assert cert["status"] == "PENDING_VALIDATION"
    assert isinstance(cert["validation_token"], str) and cert["validation_token"]

    resp = api.validate_add_on(cert["id"], headers)
    validate_error(resp, ApiErrorId.ERR_DNS_VALIDATION_FAILED.value, 409)

    assert get_add_on(cert["id"], account)["status"] == "PENDING_VALIDATION", (
        "the failed validation leaves the certificate where it was"
    )


def test_publishing_the_acme_txt_record_makes_the_same_validate_call_succeed(api):
    """PRD §3.5: "When it is found, the certificate moves `PENDING_VALIDATION → ACTIVE`."
    PRD §3.5: "Validation requires the add-on to be an `SSL_CERT` in `PENDING_VALIDATION` —
    otherwise `ERR_ADDON_NOT_PENDING_VALIDATION` — and the domain to be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/ssl_validation_depends_on_txt_dns_record_of_the_domain
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    cert = create_ssl_cert(account, subscription, domain, term_days=90)

    failed = api.validate_add_on(cert["id"], headers)
    assert failed.status_code == 409

    txt = publish_acme_challenge(domain, account, cert["validation_token"])

    validated = validate_success(api.validate_add_on(cert["id"], headers))
    assert validated["status"] == "ACTIVE"
    assert txt["value"] == cert["validation_token"]
    assert txt["record_type"] == "TXT"
    assert txt["name"] == "_acme-challenge"


# =========================================================================
# Buffered closed certificate intervals  (Difficulty/resource_temporal_overlap)
# =========================================================================

def _domain_with_first_certificate():
    """ACTIVE subscription on an ACTIVE example.com plus certificate #1 running
    2026-05-01 → 2026-07-30 (term_days 90). Returns (account, domain, subscription, cert)."""
    account, domain, _plan, subscription = setup_hosting_stack()
    cert = create_ssl_cert(
        account, subscription, domain, term_days=90, starts_at="2026-05-01T00:00:00Z"
    )
    return account, domain, subscription, cert


def test_certificate_starting_one_day_after_the_incumbent_ends_still_collides(api):
    """PRD §3.5: "Concretely, a conflict exists when such a certificate's `starts_at` is at
    or before the new certificate's `ends_at` plus one day *and* its `ends_at` is at or after
    the new certificate's `starts_at` minus one day; an intersection on either end, including
    bare adjacency where the new window begins exactly where an old one ended, draws
    `ERR_SSL_INTERVAL_CONFLICT`."
    PRD §3.5: "The validity window ends at `ends_at`, which is `starts_at` plus `term_days`
    days."

    Design: Difficulty/resource_temporal_overlap/ssl_certificate_closed_interval_with_buffer_on_a_domain
    """
    account, domain, subscription, cert = _domain_with_first_certificate()
    headers = make_registrant_headers(account["id"])

    assert cert["ends_at"][:10] == "2026-07-30", "2026-05-01 + 90 days"

    resp = api.create_add_on(
        create_ssl_payload(
            subscription["id"], domain["id"], term_days=90,
            starts_at="2026-07-31T00:00:00Z",
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_SSL_INTERVAL_CONFLICT.value, 409)


def test_certificate_clearing_the_one_day_buffer_is_accepted(api):
    """PRD §3.5: "Certificates on the same domain may not crowd each other: the new
    certificate's closed interval from `starts_at` to `ends_at`, widened by one buffer day on
    each side, must not intersect the interval of any other `SSL_CERT` add-on on that domain
    whose `status` is `PENDING_VALIDATION` or `ACTIVE`."
    PRD §3.5: "A **certificate** (`add_on_type` of `SSL_CERT`) is created in
    `PENDING_VALIDATION` with a server-minted `validation_token`; `mailbox_address` must be
    absent and `storage_mb_quota` is forced to 0, so a certificate never consumes storage."

    Design: Difficulty/resource_temporal_overlap/ssl_certificate_closed_interval_with_buffer_on_a_domain
    """
    account, domain, subscription, _cert = _domain_with_first_certificate()
    headers = make_registrant_headers(account["id"])

    resp = api.create_add_on(
        create_ssl_payload(
            subscription["id"], domain["id"], term_days=90,
            starts_at="2026-08-01T00:00:00Z",
        ),
        headers,
    )
    accepted = validate_success(resp, 201)
    assert accepted["status"] == "PENDING_VALIDATION"
    assert accepted["storage_mb_quota"] == 0, "a certificate never consumes storage"

    _, meta = validate_paginated(
        api.list_add_ons(
            headers, {"domain_id": domain["id"], "add_on_type": "SSL_CERT"}
        )
    )
    assert meta["total_count"] == 2


# =========================================================================
# Storage is a conserved quantity  (Difficulty/compensating_invariant)
# =========================================================================

def test_creating_a_mailbox_commits_its_storage_quota(api):
    """PRD §3.5: "A subscription's `storage_committed_mb` is at all times the sum of
    `storage_mb_quota` over that subscription's mailbox add-ons whose `status` is
    `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED`."
    PRD §3.5: "A **mailbox** (`add_on_type` of `EMAIL_MAILBOX`) skips validation entirely: it
    is born straight into `ACTIVE`."

    Design: Difficulty/compensating_invariant/mailbox_create_then_delete_restores_storage_committed_mb
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    create_mailbox(account, subscription, domain, "info", 2048)

    assert get_subscription(subscription["id"], account)["storage_committed_mb"] == 2048

    second = create_mailbox(account, subscription, domain, "sales", 2048)

    assert second["status"] == "ACTIVE"
    assert get_subscription(subscription["id"], account)["storage_committed_mb"] == 4096


def test_cancelling_a_mailbox_returns_storage_committed_mb_to_its_pre_create_value(api):
    """PRD §3.5: "Creation adds the quota to the committed total; cancelling the mailbox
    subtracts exactly the same figure back out, so a create-then-cancel pair leaves the
    number precisely where it started."
    PRD §3.5: "Cancelling an add-on is a `Registrant` action, permitted from
    `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED`, and it lands the add-on in `CANCELLED` —
    releasing the storage reservation when it is a mailbox."

    Design: Difficulty/compensating_invariant/mailbox_create_then_delete_restores_storage_committed_mb
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    keeper = create_mailbox(account, subscription, domain, "info", 2048)
    doomed = create_mailbox(account, subscription, domain, "sales", 2048)

    assert get_subscription(subscription["id"], account)["storage_committed_mb"] == 4096

    resp = api.delete_add_on(doomed["id"], headers)
    assert resp.status_code == 204, f"a successful delete returns 204, got {resp.status_code}"

    assert get_add_on(doomed["id"], account)["status"] == "CANCELLED"
    assert get_subscription(subscription["id"], account)["storage_committed_mb"] == 2048, (
        "exactly the pre-create value, with no drift"
    )
    assert get_add_on(keeper["id"], account)["status"] == "ACTIVE"


# =========================================================================
# Corner instances
# =========================================================================

def test_mailbox_landing_exactly_on_the_storage_quota_is_allowed(api):
    """PRD §3.5: "Admission is checked before the mailbox is created: if the subscription's
    current `storage_committed_mb` plus the requested `storage_mb_quota` would come out
    strictly greater than the plan's `storage_quota_mb`, the mailbox is refused with
    `ERR_STORAGE_QUOTA_EXCEEDED` — landing exactly on the quota is allowed."

    Design: Corner/calculations/mailbox_landing_exactly_on_the_storage_quota_is_allowed
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    create_mailbox(account, subscription, domain, "a", 2048)
    create_mailbox(account, subscription, domain, "b", 2048)

    exact = create_mailbox(account, subscription, domain, "c", 1024)
    assert exact["status"] == "ACTIVE"
    assert get_subscription(subscription["id"], account)["storage_committed_mb"] == 5120, (
        "2048 + 2048 + 1024 lands exactly on the plan's 5120 MB quota"
    )

    resp = api.create_add_on(
        create_mailbox_payload(subscription["id"], domain["id"], "d", 1024), headers
    )
    validate_error(resp, ApiErrorId.ERR_STORAGE_QUOTA_EXCEEDED.value, 422)

    assert get_subscription(subscription["id"], account)["storage_committed_mb"] == 5120


def test_duplicate_mailbox_address_on_the_same_domain_is_rejected(api):
    """PRD §3.5: "The pair of `domain_id` and `mailbox_address` must be unique among mailbox
    add-ons whose `status` is anything other than `CANCELLED`; a collision is
    `ERR_MAILBOX_ADDRESS_TAKEN`."

    Design: Corner/validations/duplicate_mailbox_address_on_a_domain_rejected
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    create_mailbox(account, subscription, domain, "info", 1024)

    resp = api.create_add_on(
        create_mailbox_payload(subscription["id"], domain["id"], "info", 1024), headers
    )
    validate_error(resp, ApiErrorId.ERR_MAILBOX_ADDRESS_TAKEN.value, 409)

    assert get_subscription(subscription["id"], account)["storage_committed_mb"] == 1024

    _, meta = validate_paginated(
        api.list_add_ons(
            headers,
            {"subscription_id": subscription["id"], "add_on_type": "EMAIL_MAILBOX"},
        )
    )
    assert meta["total_count"] == 1


def test_deleting_the_txt_record_a_live_certificate_depends_on_is_rejected(api):
    """PRD §3.5: "A `TXT` record may not be removed while some `AddOn` on the same domain, of
    `add_on_type` `SSL_CERT` and with `status` `PENDING_VALIDATION` or `ACTIVE`, has a
    `validation_token` equal to that record's `value` — pulling that record would strand a
    certificate that still depends on it, so the delete is refused with
    `ERR_DNS_RECORD_IN_USE`."

    Design: Corner/validations/deleting_a_txt_record_an_ssl_addon_depends_on_rejected
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    cert, txt = create_and_validate_ssl_cert(account, subscription, domain, term_days=90)
    a_record = create_dns_record(domain, account, record_type="A", name="@",
                                 value="203.0.113.10")

    blocked = api.delete_dns_record(txt["id"], headers)
    validate_error(blocked, ApiErrorId.ERR_DNS_RECORD_IN_USE.value, 409)

    unrelated = api.delete_dns_record(a_record["id"], headers)
    assert unrelated.status_code == 204

    records, meta = validate_paginated(api.list_dns_records(domain["id"], headers))
    assert meta["total_count"] == 1, "only the TXT record survives"
    assert records[0]["id"] == txt["id"]

    assert get_add_on(cert["id"], account)["status"] == "ACTIVE"


def test_validating_a_mailbox_add_on_is_rejected(api):
    """PRD §3.5: "Validation requires the add-on to be an `SSL_CERT` in `PENDING_VALIDATION`
    — otherwise `ERR_ADDON_NOT_PENDING_VALIDATION` — and the domain to be `ACTIVE`."
    PRD §3.5: "A **mailbox** (`add_on_type` of `EMAIL_MAILBOX`) skips validation entirely: it
    is born straight into `ACTIVE`."

    Design: Corner/errors/error_addon_not_pending_validation_trigger
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    headers = make_registrant_headers(account["id"])
    mailbox = create_mailbox(account, subscription, domain, "info", 1024)

    resp = api.validate_add_on(mailbox["id"], headers)
    validate_error(resp, ApiErrorId.ERR_ADDON_NOT_PENDING_VALIDATION.value, 409)

    assert get_add_on(mailbox["id"], account)["status"] == "ACTIVE"
