"""Renewal quoting vs charging, the expiry ladder, and the independent lock dimension."""
from test_helpers import (
    ANONYMOUS,
    BILLING,
    ApiErrorId,
    create_account,
    create_mailbox,
    days_after,
    domain_version,
    first_issued_invoice,
    get_add_on,
    get_domain,
    get_subscription,
    invoice_lines,
    line_of_type,
    make_registrant_headers,
    register_domain,
    renew_domain_payload,
    run_sweep,
    set_clock,
    setup_account_with_active_domain,
    setup_hosting_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def _domain_in_redemption():
    """Account (card) + example.com swept from ACTIVE through EXPIRED into REDEMPTION.

    The domain activates at the 2026-05-01 clock default with a one-year term, so
    expires_at is 2027-05-01. The clock then moves to 2027-05-20 (19 days into the 30-day
    grace) and finally to 2027-06-05 (past expires_at + 30 days). Returns (account, domain).
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    set_clock("2027-05-20T00:00:00Z")
    run_sweep()
    return account, domain


# =========================================================================
# QUOTED vs CHARGED across the redemption boundary  (Difficulty/dual_variant_calc)
# =========================================================================

def test_quote_taken_in_expired_omits_the_redemption_fee_the_renew_then_charges(api):
    """PRD §3.4: "A redemption fee of 8000 cents is added when, and only when, the domain's
    `lifecycle_status` is `REDEMPTION` at that instant; otherwise it is zero."
    PRD §3.4: "Consider a domain that is `EXPIRED` when the customer asks for a quote and
    that the sweep pushes into `REDEMPTION` before the customer acts on it: the charged
    subtotal then exceeds the quoted total by exactly 8000 cents, because the redemption fee
    that was absent at quote time is present at renewal time."

    Design: Difficulty/dual_variant_calc/domain_renewal_quoted_vs_charged_across_redemption
    """
    account, domain = _domain_in_redemption()
    headers = make_registrant_headers(account["id"])

    quote = validate_success(
        api.get_renewal_quote(domain["id"], headers, {"term_years": 1})
    )
    assert quote["variant"] == "QUOTED"
    assert quote["lifecycle_status"] == "EXPIRED"
    assert quote["redemption_fee_cents"] == 0
    assert quote["renewal_subtotal_cents"] == 1199
    assert quote["privacy_fee_cents"] == 0
    assert quote["quoted_total_cents"] == 1199

    set_clock("2027-06-05T00:00:00Z")
    run_sweep()
    assert get_domain(domain["id"], account)["lifecycle_status"] == "REDEMPTION"

    version = domain_version(domain["id"], account)
    validate_success(
        api.renew_domain(domain["id"], renew_domain_payload(1, version), headers)
    )

    invoice = first_issued_invoice(account["id"], headers)
    assert invoice["subtotal_cents"] == 9199, "1199 renewal + the 8000-cent redemption fee"
    assert invoice["subtotal_cents"] - quote["quoted_total_cents"] == 8000, (
        "the CHARGED subtotal exceeds the QUOTED total by exactly the redemption fee"
    )


def test_redemption_restore_bills_a_redemption_fee_line_and_returns_the_domain_to_active(api):
    """PRD §3.4: "The `EXPIRED → ACTIVE` grace renewal raises an `ISSUED` invoice with a
    `DOMAIN_RENEWAL` line and no redemption line; the `REDEMPTION → ACTIVE` restore raises an
    `ISSUED` invoice with a `DOMAIN_RENEWAL` line *and* a `REDEMPTION_FEE` line of 8000
    cents."
    PRD §3.8: "When it is at least 5000 cents but below 20000 cents, `service_fee_cents` is
    299."

    Design: Difficulty/dual_variant_calc/domain_renewal_quoted_vs_charged_across_redemption
    """
    account, domain = _domain_in_redemption()
    headers = make_registrant_headers(account["id"])

    set_clock("2027-06-05T00:00:00Z")
    run_sweep()
    version = domain_version(domain["id"], account)

    renewed = validate_success(
        api.renew_domain(domain["id"], renew_domain_payload(1, version), headers)
    )
    assert renewed["lifecycle_status"] == "ACTIVE", "REDEMPTION -> ACTIVE on restore"

    invoice = first_issued_invoice(account["id"], headers)
    assert invoice["subtotal_cents"] == 9199
    assert invoice["service_fee_cents"] == 299
    assert invoice["tax_cents"] == 759, "round_half_up per line: 99 on 1199 + 660 on 8000"
    assert invoice["total_cents"] == 10257

    lines = invoice_lines(invoice["id"], account)
    renewal_line = line_of_type(lines, "DOMAIN_RENEWAL")
    assert renewal_line["line_subtotal_cents"] == 1199
    redemption_line = line_of_type(lines, "REDEMPTION_FEE")
    assert redemption_line["line_subtotal_cents"] == 8000


# =========================================================================
# The two Domain state dimensions  (Difficulty/non_linear_state_machine)
# =========================================================================

def test_unlocking_leaves_the_lifecycle_dimension_untouched(api):
    """PRD §2.10: "The two `Domain` state dimensions are independent. `lifecycle_status` and
    `lock_status` live on the same row but evolve separately, gate different operations, and
    neither one constrains the other's value: a domain can be `ACTIVE` and `UNLOCKED`,
    `ACTIVE` and `LOCKED`, or `SUSPENDED` while still carrying whichever lock value it last
    held."
    PRD §3.3: "Sending `locked` as false moves `LOCKED → UNLOCKED`; sending it as true moves
    `UNLOCKED → LOCKED`."

    Design: Difficulty/non_linear_state_machine/domain_lifecycle_and_lock_dimensions_evolve_independently
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])
    set_clock("2026-07-01T00:00:00Z")

    updated = validate_success(
        api.update_domain_settings(domain["id"], {"locked": False}, headers)
    )

    assert updated["lock_status"] == "UNLOCKED"
    assert updated["lifecycle_status"] == "ACTIVE", (
        "the lock move must not disturb the lifecycle dimension"
    )


def test_lifecycle_cycles_through_expired_while_the_lock_dimension_holds_its_value(api):
    """PRD §2.10: "The two `Domain` state dimensions are independent. `lifecycle_status` and
    `lock_status` live on the same row but evolve separately, gate different operations, and
    neither one constrains the other's value: a domain can be `ACTIVE` and `UNLOCKED`,
    `ACTIVE` and `LOCKED`, or `SUSPENDED` while still carrying whichever lock value it last
    held."
    PRD §3.4: "From `EXPIRED` or from `REDEMPTION`, renewal **resets**: `expires_at` becomes
    the logical clock now plus the requested years times 365 days — the lapsed remainder of
    the old term is not credited back — and the domain returns to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/domain_lifecycle_and_lock_dimensions_evolve_independently
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api.update_domain_settings(domain["id"], {"locked": False}, headers))

    set_clock("2027-05-20T00:00:00Z")
    run_sweep()

    expired = get_domain(domain["id"], account)
    assert expired["lifecycle_status"] == "EXPIRED"
    assert expired["lock_status"] == "UNLOCKED", (
        "the lifecycle move must not disturb the lock dimension"
    )

    renewed = validate_success(
        api.renew_domain(
            domain["id"], renew_domain_payload(1, expired["version"]), headers
        )
    )
    assert renewed["lifecycle_status"] == "ACTIVE"
    assert renewed["lock_status"] == "UNLOCKED"
    assert renewed["expires_at"][:10] == days_after("2027-05-20T00:00:00Z", 365)[:10], (
        "the EXPIRED branch resets the term baseline to the logical clock"
    )


# =========================================================================
# Corner instances
# =========================================================================

def test_renewal_from_active_extends_the_existing_term(api):
    """PRD §3.4: "From `ACTIVE`, renewal **extends**: `expires_at` becomes the old
    `expires_at` plus the requested years times 365 days, and the domain stays `ACTIVE`."
    PRD §3.4: "The renewal subtotal is the base year price of §3.2 — same TLD list price,
    same five-times premium multiplier — multiplied by the requested number of years."

    Design: Corner/calculations/renewal_from_active_extends_the_existing_term
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])

    renewed = validate_success(
        api.renew_domain(
            domain["id"], renew_domain_payload(2, domain["version"]), headers
        )
    )

    assert renewed["lifecycle_status"] == "ACTIVE"
    assert renewed["expires_at"][:10] == days_after("2027-05-01T00:00:00Z", 730)[:10], (
        "2027-05-01 + 730 days — EXTEND, not RESET"
    )

    invoice = first_issued_invoice(account["id"], headers)
    assert invoice["subtotal_cents"] == 2398
    assert invoice["tax_cents"] == 198
    assert invoice["service_fee_cents"] == 0
    assert invoice["total_cents"] == 2596

    lines = invoice_lines(invoice["id"], account)
    assert len(lines) == 1, "an ACTIVE renewal raises no REDEMPTION_FEE line"
    assert lines[0]["item_type"] == "DOMAIN_RENEWAL"
    assert lines[0]["quantity"] == 2


def test_renewal_quote_persists_nothing(api):
    """PRD §3.4: "The quote takes a `term_years` and returns a read-only projection — nothing
    is persisted, no invoice is raised — reporting back the `domain_id`, the `term_years`
    asked for, the `variant` that was evaluated, the `lifecycle_status` the domain was in at
    quote time, the `renewal_subtotal_cents`, the `redemption_fee_cents`, the
    `privacy_fee_cents`, the `quoted_total_cents`, and the `quoted_at` instant the quote was
    taken from the logical clock."

    Design: Corner/endpoints/renewal_quote_is_a_pure_read
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])

    for caller in (headers, BILLING):
        quote = validate_success(
            api.get_renewal_quote(domain["id"], caller, {"term_years": 3})
        )
        assert quote["domain_id"] == domain["id"]
        assert quote["term_years"] == 3
        assert quote["variant"] == "QUOTED"
        assert quote["lifecycle_status"] == "ACTIVE"
        assert quote["renewal_subtotal_cents"] == 3597, "3 * 1199"
        assert quote["redemption_fee_cents"] == 0
        assert quote["privacy_fee_cents"] == 0
        assert quote["quoted_total_cents"] == 3597
        assert isinstance(quote["quoted_at"], str)

    after = get_domain(domain["id"], account)
    assert after["version"] == domain["version"], "a quote must not bump the version"
    assert after["expires_at"] == domain["expires_at"]

    _, meta = validate_paginated(
        api.list_invoices(headers, {"account_id": account["id"], "status": "ISSUED"})
    )
    assert meta["total_count"] == 0, "a quote raises no invoice"


def test_renewal_pushing_the_term_beyond_ten_years_is_rejected(api):
    """PRD §3.4: "Renewal is also bounded: the term may not be pushed more than ten years
    past the logical clock. If the prospective new `expires_at` minus the clock now would
    exceed 10 times 365 days, the request is refused with `ERR_MAX_TERM_EXCEEDED`."

    Design: Corner/validations/renewal_beyond_ten_years_rejected
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])

    resp = api.renew_domain(
        domain["id"], renew_domain_payload(10, domain["version"]), headers
    )
    validate_error(resp, ApiErrorId.ERR_MAX_TERM_EXCEEDED.value, 422)

    after = get_domain(domain["id"], account)
    assert after["expires_at"] == domain["expires_at"], "expires_at is unchanged"
    assert after["version"] == domain["version"]

    _, meta = validate_paginated(
        api.list_invoices(headers, {"account_id": account["id"], "status": "ISSUED"})
    )
    assert meta["total_count"] == 0, "the rejected renewal raises no invoice"


def test_renewing_a_pending_payment_domain_is_not_renewable(api):
    """PRD §3.4: "Renewal is refused outright when the domain's `lifecycle_status` is
    anything other than `ACTIVE`, `EXPIRED` or `REDEMPTION` — a `PENDING_PAYMENT`,
    `SUSPENDED`, `PENDING_DELETE`, `DELETED` or `TRANSFERRED_OUT` name yields
    `ERR_DOMAIN_NOT_RENEWABLE`, and the same rule guards the quote."

    Design: Corner/errors/error_domain_not_renewable_trigger
    """
    account = create_account(with_card=False)
    headers = make_registrant_headers(account["id"])
    domain = register_domain(account, "example", "com", auto_renew=False)

    resp = api.renew_domain(
        domain["id"], renew_domain_payload(1, domain["version"]), headers
    )
    validate_error(resp, ApiErrorId.ERR_DOMAIN_NOT_RENEWABLE.value, 409)

    after = get_domain(domain["id"], account)
    assert after["lifecycle_status"] == "PENDING_PAYMENT"
    assert after["expires_at"] is None


def test_sweep_auto_renews_a_domain_whose_account_has_a_card_on_file(api):
    """PRD §3.4: "If its `auto_renew_enabled` is true *and* its account is `ACTIVE` *and*
    that account has a payment method on file, the domain auto-renews for exactly one year:
    `expires_at` advances by 365 days from its previous value (the extend branch), the domain
    stays `ACTIVE`, its `version` increments, and an `ISSUED` invoice with a one-year
    `DOMAIN_RENEWAL` line is raised and immediately settled exactly as if the customer had
    paid it — credit first, then the card."
    PRD §3.4: "The sweep reports what it did: `auto_renewed_count`, `expired_count`,
    `redemption_count`, `pending_delete_count`, `deleted_count` and `addon_expired_count`."

    Design: Corner/state_machines/sweep_auto_renews_a_domain_with_auto_renew_and_a_card
    """
    account, domain = setup_account_with_active_domain(auto_renew=True)
    headers = make_registrant_headers(account["id"])

    set_clock("2027-05-02T00:00:00Z")
    report = run_sweep()

    assert report["auto_renewed_count"] == 1
    assert report["expired_count"] == 0

    after = get_domain(domain["id"], account)
    assert after["lifecycle_status"] == "ACTIVE"
    assert after["expires_at"][:10] == days_after("2027-05-01T00:00:00Z", 365)[:10]

    _, meta = validate_paginated(
        api.list_invoices(headers, {"account_id": account["id"], "status": "PAID"})
    )
    assert meta["total_count"] == 2, (
        "the registration invoice plus the immediately settled renewal invoice"
    )


def test_a_single_sweep_can_walk_the_whole_ladder_to_deleted(api):
    """PRD §3.4: "A `PlatformAdmin` runs the expiry sweep, which walks every domain whose
    `lifecycle_status` is `ACTIVE`, `EXPIRED`, `REDEMPTION` or `PENDING_DELETE` in
    `created_at` ascending order — never by `id` — and applies the following ladder
    repeatedly to each domain, so a clock parked far in the future can carry one name from
    `ACTIVE` all the way to `DELETED` inside a single call."
    PRD §3.4: "Once the clock reaches `expires_at` plus 65 days — those 60 plus a final
    5-day pending-delete window — the domain reaches `DELETED`, which is terminal and fires
    the heaviest cascade of all: every `AddOn` whose `domain_id` is this domain and whose
    `status` is `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED` transitions to `CANCELLED`;
    because those mailbox add-ons have left the committed set, every affected subscription's
    `storage_committed_mb` is recomputed; every `HostingSubscription` whose
    `primary_domain_id` is this domain transitions to `CANCELLED`; and the `fqdn` is released
    back into the pool for anyone to register."

    Design: Corner/state_machines/sweep_ladder_carries_an_expired_domain_all_the_way_to_deleted
    """
    account, domain, _plan, subscription = setup_hosting_stack()
    mailbox = create_mailbox(
        account, subscription, domain, "info", 2048, term_days=730
    )

    set_clock("2027-07-06T00:00:00Z")
    report = run_sweep()

    assert report["deleted_count"] == 1

    assert get_domain(domain["id"], account)["lifecycle_status"] == "DELETED"
    assert get_add_on(mailbox["id"], account)["status"] == "CANCELLED"

    sub = get_subscription(subscription["id"], account)
    assert sub["status"] == "CANCELLED"
    assert sub["storage_committed_mb"] == 0

    search = validate_success(
        api.domain_search(ANONYMOUS, {"domain_name": "example", "tld": "com"})
    )
    assert search["available"] is True, "a DELETED name releases its fqdn back into the pool"


def test_replaying_a_stale_expected_domain_version_on_renew_is_rejected(api):
    """PRD §2.6: "A domain renewal request must carry `expected_domain_version`, a
    non-optional field holding the client's last observed `version` of the target `Domain`.
    If it does not equal the domain's current `version`, the renewal is rejected with
    `ERR_STALE_DOMAIN_VERSION` (HTTP 412)."
    PRD §2.6: "This guard is load-bearing because renewal is legitimately repeatable — a
    domain may be renewed twice, each renewal extending the term — so a second renewal
    replaying the version observed before the first one would pass every state precondition;
    only the version check catches it."

    Design: Corner/validations/stale_expected_domain_version_on_renew_returns_412
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])
    stale_version = domain["version"]

    validate_success(
        api.renew_domain(domain["id"], renew_domain_payload(1, stale_version), headers)
    )

    resp = api.renew_domain(
        domain["id"], renew_domain_payload(1, stale_version), headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_DOMAIN_VERSION.value, 412)

    after = get_domain(domain["id"], account)
    assert after["version"] == stale_version + 1, "bumped once by the accepted renew only"

    _, meta = validate_paginated(
        api.list_invoices(headers, {"account_id": account["id"], "status": "ISSUED"})
    )
    assert meta["total_count"] == 1, "the rejected renew raised no second renewal invoice"


def test_unlocking_inside_the_sixty_day_window_is_rejected_and_allowed_on_day_sixty(api):
    """PRD §3.3: "Unlocking is not: a name may not leave the lock before sixty days have
    elapsed since its `registered_at` — the logical clock must have reached at least
    `registered_at` plus 60 days — and an attempt to unlock inside that window is refused
    with `ERR_TRANSFER_LOCK_PERIOD`."

    Design: Corner/validations/unlocking_within_sixty_days_of_registration_rejected
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])

    set_clock("2026-06-29T00:00:00Z")  # day 59
    early = api.update_domain_settings(domain["id"], {"locked": False}, headers)
    validate_error(early, ApiErrorId.ERR_TRANSFER_LOCK_PERIOD.value, 409)
    assert get_domain(domain["id"], account)["lock_status"] == "LOCKED"

    set_clock("2026-06-30T00:00:00Z")  # day 60 — the boundary is inclusive
    on_time = validate_success(
        api.update_domain_settings(domain["id"], {"locked": False}, headers)
    )
    assert on_time["lock_status"] == "UNLOCKED"


def test_a_settings_patch_bumps_the_version_and_strands_a_pre_patch_renew(api):
    """PRD §3.3: "Whatever else the request does, it increments the domain's `version`."
    PRD §2.4: "Most resources also carry the standard audit triple: `created_at` and
    `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and
    `version`, an integer that begins at 1 on creation and increments by one on every
    mutation of that resource."
    PRD §2.6: "If it does not equal the domain's current `version`, the renewal is rejected
    with `ERR_STALE_DOMAIN_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/version_increments_on_every_mutation_including_cascades
    """
    account, domain = setup_account_with_active_domain(auto_renew=False)
    headers = make_registrant_headers(account["id"])
    set_clock("2026-07-15T00:00:00Z")

    pre_patch_version = domain_version(domain["id"], account)

    patched = validate_success(
        api.update_domain_settings(domain["id"], {"locked": False}, headers)
    )
    assert patched["version"] == pre_patch_version + 1
    assert patched["lock_status"] == "UNLOCKED"

    resp = api.renew_domain(
        domain["id"], renew_domain_payload(1, pre_patch_version), headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_DOMAIN_VERSION.value, 412)

    after = get_domain(domain["id"], account)
    assert after["expires_at"] == domain["expires_at"], "the stale renew changed nothing"
