"""Account signup, domain search pricing, registration, WHOIS projection and access control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ANONYMOUS,
    SUPPORT,
    ApiErrorId,
    assert_account,
    assert_domain,
    create_account,
    create_account_payload,
    create_domain_payload,
    is_valid_uuid,
    make_registrant_headers,
    no_auth_headers,
    register_domain,
    register_and_activate_domain,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_account_starts_active_with_zeroed_money_and_version_one(api):
    """PRD §3.1: "A fresh account starts `ACTIVE` with `credit_balance_cents` at 0,
    `net_cash_cents` at 0, `risk_score` at 0, and `payment_method_on_file` false."
    PRD §3.1: "An optional `auto_renew_default` may be supplied at signup and defaults
    to true; its only job is to seed new domains, as §3.2 explains."
    PRD §2.4: "Every resource is identified by `id`, a server-minted UUID string carrying
    no type prefix — the caller never supplies it."

    Design: Corner/entities/create_account_applies_defaults_and_system_fields
    """
    resp = api.create_account(create_account_payload(), ANONYMOUS)
    account = validate_success(resp, 201)

    assert_account(account)
    assert account["status"] == "ACTIVE"
    assert account["payment_method_on_file"] is False
    assert account["credit_balance_cents"] == 0
    assert account["net_cash_cents"] == 0
    assert account["risk_score"] == 0
    assert account["auto_renew_default"] is True, "auto_renew_default defaults to true"
    assert account["version"] == 1, "version begins at 1 on creation"
    assert is_valid_uuid(account["id"]) and not account["id"].startswith("acct")

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_get_unknown_domain_returns_domain_not_found(api):
    """PRD §2.9: "Each entity has its own not-found code: `ERR_ACCOUNT_NOT_FOUND`,
    `ERR_DOMAIN_NOT_FOUND`, `ERR_DNS_RECORD_NOT_FOUND`, `ERR_HOSTING_PLAN_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND`, `ERR_ABUSE_REPORT_NOT_FOUND`
    and `ERR_PROMO_CODE_NOT_FOUND` — all 404."

    Design: Corner/entities/get_domain_with_unknown_id_returns_not_found
    """
    resp = api.get_domain(NON_EXISTENT_UUID, SUPPORT)

    validate_error(resp, ApiErrorId.ERR_DOMAIN_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_register_domain_without_term_years_is_invalid_request(api):
    """PRD §3.2: "It takes an `account_id`, the `domain_name` and `tld`, a `term_years`
    between 1 and 10 inclusive, the WHOIS contact pair `registrant_name` and
    `registrant_email`, and two optional switches: `whois_privacy` and `auto_renew`."
    PRD §2.8: "Authentication comes first, then the endpoint's role list, then the shape
    of the request itself (required fields present, enum members legal, integers
    non-negative, `term_years` between 1 and 10 inclusive, `ttl` between 60 and 86400
    inclusive, `limit` between 1 and 100 inclusive, `offset` at least 0, `priority`
    present when and only when `record_type` is `MX`, `mailbox_address` present when and
    only when `add_on_type` is `EMAIL_MAILBOX`) — a failure here is `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/register_domain_missing_required_field_invalid_request
    """
    account = create_account(with_card=False)
    headers = make_registrant_headers(account["id"])

    payload = create_domain_payload(account["id"])
    payload.pop("term_years")
    resp = api.create_domain(payload, headers)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    domains, meta = validate_paginated(
        api.list_domains(headers, {"account_id": account["id"]})
    )
    assert meta["total_count"] == 0, "the rejected registration must create no Domain"

    invoices, inv_meta = validate_paginated(
        api.list_invoices(headers, {"account_id": account["id"]})
    )
    assert inv_meta["total_count"] == 0, "the rejected registration must raise no Invoice"


def test_register_domain_with_unknown_tld_enum_is_invalid_request(api):
    """PRD §3.2: "A search takes a `domain_name` — the second-level label without the dot,
    lowercase, 1 to 63 characters drawn from letters, digits and hyphens — together with a
    `tld` drawn from `com`, `net`, `io` and `xyz`, and answers with the `fqdn` (the label, a
    dot, the TLD), whether the name is `available`, whether it `is_premium`, and its
    `base_year_price_cents`."
    PRD §2.8: "Authentication comes first, then the endpoint's role list, then the shape of
    the request itself (required fields present, enum members legal, integers non-negative,
    `term_years` between 1 and 10 inclusive, `ttl` between 60 and 86400 inclusive, `limit`
    between 1 and 100 inclusive, `offset` at least 0, `priority` present when and only when
    `record_type` is `MX`, `mailbox_address` present when and only when `add_on_type` is
    `EMAIL_MAILBOX`) — a failure here is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/invalid_tld_enum_value_rejected
    """
    account = create_account(with_card=False)
    headers = make_registrant_headers(account["id"])

    resp = api.create_domain(create_domain_payload(account["id"], tld="org"), headers)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_registration_seeds_server_owned_lifecycle_lock_and_null_term_fields(api):
    """PRD §3.2: "It produces a `Domain` sitting in `PENDING_PAYMENT` on its lifecycle
    dimension and `LOCKED` on its lock dimension, with `registered_at`, `expires_at` and
    `epp_auth_code` all still null, and alongside it an `ISSUED` invoice."
    PRD §3.2: "When `auto_renew` is omitted, the account's `auto_renew_default` is copied
    into the new domain's `auto_renew_enabled`; when it is supplied it wins. `whois_privacy`
    seeds `whois_privacy_enabled` and defaults to false."

    Design: Corner/entities/domain_computed_fields_are_server_owned
    """
    account = create_account()
    headers = make_registrant_headers(account["id"])

    resp = api.create_domain(create_domain_payload(account["id"]), headers)
    domain = validate_success(resp, 201)

    assert_domain(domain)
    assert domain["lifecycle_status"] == "PENDING_PAYMENT"
    assert domain["lock_status"] == "LOCKED"
    assert domain["registered_at"] is None
    assert domain["expires_at"] is None
    assert domain["epp_auth_code"] is None
    assert domain["fqdn"] == "example.com"
    assert domain["whois_privacy_enabled"] is False, "whois_privacy defaults to false"
    assert domain["auto_renew_enabled"] is True, (
        "auto_renew was omitted, so the account's auto_renew_default (true) is copied in"
    )


def test_list_domains_pages_in_created_at_order_with_pagination_meta(api):
    """PRD §2.3: "Results are always ordered by `created_at` ascending; no list endpoint
    offers an alternative sort."
    PRD §2.3: "Alongside the request identifiers, the `meta` object of a list response
    carries `limit`, `offset`, `total_count` (the number of rows matching the filters
    before the window is applied) and `has_more` (true when rows remain beyond the current
    window)."

    Design: Corner/entities/list_domains_pagination_envelope_and_filter
    """
    account = create_account(with_card=False)
    headers = make_registrant_headers(account["id"])

    register_domain(account, "example", "com")
    second = register_domain(account, "shop", "net")

    resp = api.list_domains(headers, {"account_id": account["id"], "limit": 1, "offset": 1})
    data, meta = validate_paginated(resp)

    assert resp.json()["response_type"] == "array"
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 1
    assert data[0]["id"] == second["id"], (
        "offset 1 of a created_at ASC listing is the second-registered domain"
    )


def test_whois_privacy_masks_registrant_fields_for_anonymous_callers(api):
    """PRD §3.2: "And an `Anonymous` caller sees the public WHOIS projection: when
    `whois_privacy_enabled` is true, `registrant_name` reads `REDACTED FOR PRIVACY` and
    `registrant_email` reads `privacy@proxy.example`."
    PRD §3.2: "A `Registrant` who owns it, a `SupportAgent` or a `PlatformAdmin` sees
    everything, including the `epp_auth_code`. Every other role sees `epp_auth_code` as
    null."

    Design: Corner/entities/whois_privacy_masks_registrant_fields_for_anonymous
    """
    account = create_account()
    headers = make_registrant_headers(account["id"])
    domain = register_and_activate_domain(
        account, "budgetsite", "xyz", whois_privacy=True,
        registrant_name="Ada Lovelace", registrant_email="ada@corp.example",
    )

    public = validate_success(api.get_domain(domain["id"], ANONYMOUS))
    assert public["registrant_name"] == "REDACTED FOR PRIVACY"
    assert public["registrant_email"] == "privacy@proxy.example"
    assert public["epp_auth_code"] is None

    owner = validate_success(api.get_domain(domain["id"], headers))
    assert owner["registrant_name"] == "Ada Lovelace"
    assert owner["registrant_email"] == "ada@corp.example"
    assert isinstance(owner["epp_auth_code"], str)
    assert len(owner["epp_auth_code"]) == 16, (
        "activation mints a sixteen-character epp_auth_code"
    )


def test_domain_search_applies_the_premium_multiplier_to_short_labels(api):
    """PRD §3.2: "The base year price is the TLD's list price — 1199 cents for a `com`,
    1499 cents for a `net`, 3999 cents for an `io`, and 199 cents for an `xyz` — multiplied
    by five if the name is premium, and left alone otherwise."
    PRD §3.2: "A name is premium when and only when its `domain_name` label is at most three
    characters long, which is what `is_premium` records."

    Design: Corner/calculations/domain_search_prices_a_premium_short_label
    """
    premium = validate_success(
        api.domain_search(ANONYMOUS, {"domain_name": "abc", "tld": "com"})
    )
    assert premium["available"] is True
    assert premium["is_premium"] is True
    assert premium["base_year_price_cents"] == 5995, "1199 * 5 for a 3-character label"
    assert premium["fqdn"] == "abc.com"

    plain = validate_success(
        api.domain_search(ANONYMOUS, {"domain_name": "example", "tld": "com"})
    )
    assert plain["available"] is True
    assert plain["is_premium"] is False
    assert plain["base_year_price_cents"] == 1199


def test_registering_an_fqdn_already_held_by_a_live_domain_is_rejected(api):
    """PRD §3.2: "If the requested `fqdn` is already held by a live domain, the request is
    refused with `ERR_DOMAIN_UNAVAILABLE`."
    PRD §3.2: "Availability is the negative of the uniqueness rule: an `fqdn` is taken while
    some `Domain` holds it with a `lifecycle_status` other than `DELETED` and other than
    `TRANSFERRED_OUT`."

    Design: Corner/validations/registering_an_already_held_fqdn_rejected
    """
    account_a = create_account(with_card=False)
    account_b = create_account(with_card=False)
    headers_b = make_registrant_headers(account_b["id"])

    register_domain(account_a, "example", "com")  # stays PENDING_PAYMENT — still "live"

    search = validate_success(
        api.domain_search(ANONYMOUS, {"domain_name": "example", "tld": "com"})
    )
    assert search["available"] is False

    resp = api.create_domain(
        create_domain_payload(account_b["id"], registrant_name="Bob B"), headers_b
    )
    validate_error(resp, ApiErrorId.ERR_DOMAIN_UNAVAILABLE.value, 409)

    _, meta = validate_paginated(
        api.list_domains(headers_b, {"account_id": account_b["id"]})
    )
    assert meta["total_count"] == 0


def test_request_without_role_header_is_unauthenticated_before_any_lookup(api):
    """PRD §2.1: "A request whose `X-User-Role` is missing or names something outside that
    list is rejected with `ERR_UNAUTHENTICATED` (401), as is a request that omits
    `X-User-ID` while claiming any role other than `Anonymous`; `X-User-ID` is the one
    header an `Anonymous` caller is permitted to leave out."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    resp = api.get_domain(NON_EXISTENT_UUID, no_auth_headers())

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert resp.status_code == 401, (
        "authentication precedes existence: a missing role beats the unknown domain id"
    )


def test_registrant_reading_another_accounts_domain_is_not_resource_owner(api):
    """PRD §2.1: "Concretely, a `Registrant` may only act on a `Domain` whose `account_id`
    is their own, a `HostingSubscription` whose `account_id` is their own, an `Invoice`
    whose `account_id` is their own, a `TransferRequest` whose `account_id` is their own, an
    `AddOn` whose subscription belongs to their account, and a `DnsRecord` whose domain
    belongs to their account. Any other target yields `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/validations/registrant_cannot_read_another_accounts_domain
    """
    account_a = create_account(with_card=False)
    account_b = create_account(with_card=False)
    domain = register_domain(account_a, "example", "com")

    resp = api.get_domain(domain["id"], make_registrant_headers(account_b["id"]))

    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_anonymous_caller_cannot_register_a_domain(api):
    """PRD §2.1: "Once the caller is authenticated, the endpoint's own role list is
    consulted: a role that does not appear on the endpoint is turned away with
    `ERR_FORBIDDEN_ROLE` (403)."
    PRD §4 lists `POST /registrar/domains` — "Register a domain; creates it PENDING_PAYMENT
    with an ISSUED invoice." — as authorized for Registrant only.

    Design: Corner/rbac/anonymous_cannot_register_a_domain
    """
    account = create_account(with_card=False)

    resp = api.create_domain(create_domain_payload(account["id"]), ANONYMOUS)

    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    _, meta = validate_paginated(
        api.list_domains(
            make_registrant_headers(account["id"]), {"account_id": account["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_registrant_cannot_grant_store_credit_to_their_own_account(api):
    """PRD §3.1: "A `BillingAdmin` may also grant store credit outright, as a goodwill
    gesture or an upsell incentive, by supplying `amount_cents` and a `reason`; this writes
    a `CREDIT_GRANT` ledger entry with `reference_type` of `ADJUSTMENT` and refreshes the
    account's derived credit balance."
    PRD §2.1: "Once the caller is authenticated, the endpoint's own role list is consulted:
    a role that does not appear on the endpoint is turned away with `ERR_FORBIDDEN_ROLE`
    (403)."

    Design: Corner/rbac/registrant_cannot_grant_themselves_store_credit
    """
    account = create_account(with_card=False)
    headers = make_registrant_headers(account["id"])

    resp = api.grant_credit(
        account["id"], {"amount_cents": 100000, "reason": "self-serve"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    refreshed = validate_success(api.get_account(account["id"], headers))
    assert refreshed["credit_balance_cents"] == 0

    _, meta = validate_paginated(api.list_ledger_entries(account["id"], headers))
    assert meta["total_count"] == 0
