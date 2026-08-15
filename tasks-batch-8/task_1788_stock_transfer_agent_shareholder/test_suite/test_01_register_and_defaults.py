"""Register fundamentals: issuer onboarding, account registration defaults,
position seeding constraints, computed share totals, and the audit chain's
genesis anchor."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_account,
    assert_position,
    create_account,
    create_account_payload,
    create_issuer,
    create_issuer_payload,
    get_position,
    seed_position,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_certificate,
)


class TestAccountRegistrationDefaults:
    def test_create_account_applies_defaults_and_clock_default(self, api):
        """PRD §3.1: "Three tax attributes ride on the account: `residency`, which is `US` or `FOREIGN` and defaults to `US` when omitted; `tin_status`, the W-9 certification status, which is one of `MISSING`, `CERTIFIED`, or `UNCERTIFIED` and defaults to `MISSING`; and `treaty_tier`, which is `STANDARD` or `TREATY`, defaults to `STANDARD`, and only bears on withholding when the `residency` is `FOREIGN`."
        PRD §3.1: "A new account's `account_status` begins at `ACTIVE` — the lifecycle later spans `RESTRICTED`, `DORMANT`, and the terminal `ESCHEATED` — its `address_verified` flag starts out true, its `pending_transfer_count` and `stale_dividend_cents` counters start at zero, and its `last_qualifying_contact_date` is initialized to the account's `created_at`."
        PRD §2.4: "Before the clock has ever been set, its value is exactly `2026-08-01T00:00:00Z`; the clock never falls back to wall-clock time."
        PRD §3.7: "three years for `CA`, five years for `NY`, three years for `TX`, and five years for every other state."

        Design: Corner/entities/create_account_applies_defaults_and_clock_default
        """
        create_issuer(name="Upsilon Corp", cusip="000000020", ticker="UPSI")
        resp = api.create_account(
            create_account_payload(holder_name="Default Dana",
                                   address_line1="28 Date St", state_code="OK",
                                   postal_code="74101", tax_id="181-81-8181"),
            ADMIN,
        )
        acct = validate_success(resp, 201)
        assert_account(acct)
        assert acct["tin_status"] == "MISSING", "omitted tin_status defaults to MISSING"
        assert acct["residency"] == "US", "omitted residency defaults to US"
        assert acct["treaty_tier"] == "STANDARD", "omitted treaty_tier defaults to STANDARD"
        assert acct["account_status"] == "ACTIVE"
        assert acct["address_verified"] is True
        assert acct["version"] == 1, "a new account is born with version 1"
        assert acct["pending_transfer_count"] == 0
        assert acct["stale_dividend_cents"] == 0
        assert acct["created_at"] == "2026-08-01T00:00:00.000Z", (
            "created_at is stamped from the logical clock, whose startup "
            "default is exactly 2026-08-01T00:00:00Z"
        )
        assert acct["last_qualifying_contact_date"] == acct["created_at"]
        assert acct["dormancy_years"] == 5, (
            "OK is not in the dormancy table; every other state is five years"
        )

    def test_create_account_missing_tax_id_rejected(self, api):
        """PRD §3.1: "Registering a shareholder account captures the registered
        holder's legal `holder_name` and full mailing address —
        `address_line1`, `city`, the two-letter `state_code` of residence,
        `postal_code`, and the ISO `country_code` — together with the holder's
        `tax_id` as provided."
        PRD §2.8: "A duplicate `cusip` fails with `ERR_DUPLICATE_CUSIP`; a second position for the same account and issuer fails with `ERR_DUPLICATE_POSITION`; a lost report on a certificate that already has an open claim fails with `ERR_DUPLICATE_OPEN_CLAIM`; an overlapping freeze window fails with `ERR_FREEZE_WINDOW_OVERLAP`; a share quantity below one fails with `ERR_ZERO_SHARE_QUANTITY`; and missing required fields, malformed values, or enum values outside their declared sets fail with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_account_missing_required_field_returns_invalid_request
        """
        payload = create_account_payload(holder_name="No Tin", state_code="OK",
                                         postal_code="74101")
        del payload["tax_id"]
        resp = api.create_account(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_account_not_found_returns_404(self, api):
        """PRD §2.8: "Path identifiers are resolved strictly from left to right, and the request is rejected with the specific 404 for the leftmost segment that does not resolve — `ERR_ISSUER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_LEGEND_REQUEST_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, or `ERR_INQUIRY_NOT_FOUND` — before any later segment is even considered."

        Design: Corner/entities/get_account_not_found_returns_404
        """
        resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)


class TestIssuerAndPositionConstraints:
    def test_create_issuer_duplicate_cusip_rejected(self, api):
        """PRD §3.1: "A `cusip` is unique across all issuers: registering a
        security whose `cusip` is already on the platform is refused with
        `ERR_DUPLICATE_CUSIP`."

        Design: Corner/entities/create_issuer_duplicate_cusip_rejected
        """
        create_issuer(name="Phi One", cusip="000000021", ticker="PHI1")
        resp = api.create_issuer(
            create_issuer_payload(name="Phi Two", cusip="000000021",
                                  ticker="PHI2", shares_outstanding=200,
                                  par_value_cents=2,
                                  current_market_price_cents=6000),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CUSIP)

    def test_duplicate_position_same_account_issuer_rejected(self, api):
        """PRD §3.1: "There is exactly one position per account-and-issuer
        pair: seeding a second position for the same pair is refused with
        `ERR_DUPLICATE_POSITION`."

        Design: Corner/entities/duplicate_position_same_account_issuer_rejected
        """
        issuer = create_issuer(name="Chi Corp", cusip="000000022", ticker="CHIC")
        account = create_account(holder_name="Dup Dan", postal_code="74102",
                                 tax_id="191-91-9191")
        seed_position(account["id"], issuer["id"], 100)

        resp = api.create_position(
            account["id"],
            {"issuer_id": issuer["id"], "book_entry_shares": 50},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POSITION)

    def test_position_total_shares_computed_after_withdrawal(self, api):
        """PRD §2.10: "Each position divides its holding between two forms —
        `book_entry_shares` held in uncertificated DRS form and
        `certificated_shares` held in physical certificate form — and exposes
        `total_shares` as the sum of the two."
        PRD §3.2: "On success the position's `book_entry_shares` decreases by
        the withdrawn quantity, its `certificated_shares` increases by the same
        amount, the position's `version` increments by one, and the issuer's
        totals are recomputed."

        Design: Corner/entities/position_total_shares_computed_after_withdrawal
        """
        issuer = create_issuer(name="Psi Inc", cusip="000000023", ticker="PSII",
                               shares_outstanding=120)
        account = create_account(holder_name="Comp Carla", postal_code="74103",
                                 tax_id="202-12-1212")
        position = seed_position(account["id"], issuer["id"], 120)

        withdraw_certificate(position["id"], 20)

        pos = get_position(account["id"], issuer["id"])
        assert_position(pos)
        assert pos["book_entry_shares"] == 100
        assert pos["certificated_shares"] == 20
        assert pos["total_shares"] == 120, (
            "total_shares is a computed sum — a form conversion does not "
            "change the share count"
        )
        assert pos["version"] == 2, "the withdrawal bumped the position version"


class TestAuditGenesis:
    def test_audit_event_immutable_genesis_chain(self, api):
        """PRD §2.9: "Every mutation in the system appends an `AuditEvent` to a
        hash-chained, append-only log."
        PRD §2.9: "`prev_entry_hash` is the SHA-256 of the previous event in
        the chain, or the literal value `GENESIS` for the first entry"
        PRD §2.9: "The `actor_role` and `actor_id` fields are copied from the
        request's `X-User-Role` and `X-User-ID` headers."
        PRD §3.1: "the creation is recorded in the audit chain under the action
        `issuer.create`."
        PRD §2.5: "an `AuditEvent` carries only `id` and `created_at` from the
        standard set, and both `updated_at` and `version` are absent from it."

        Design: Corner/entities/audit_event_immutable_genesis_chain
        """
        issuer = create_issuer(name="Omega Chain", cusip="000000024",
                               ticker="OMGA")

        data, meta = validate_paginated(api.list_audit_events(
            COMPLIANCE, {"entity_type": "Issuer", "entity_id": issuer["id"]}))
        assert meta["total_count"] == 1, "exactly one audit event for the create"
        event = data[0]
        assert event["action"] == "issuer.create"
        assert event["entity_type"] == "Issuer"
        assert event["entity_id"] == issuer["id"]
        assert event["prev_entry_hash"] == "GENESIS", (
            "the first entry of an empty chain anchors on the literal GENESIS"
        )
        assert isinstance(event["entry_hash"], str) and len(event["entry_hash"]) == 64
        assert event["actor_role"] == "AgentAdmin"
        assert event["actor_id"] == "admin_1"
        assert "updated_at" not in event, "append-only log carries no updated_at"
        assert "version" not in event, "append-only log carries no version"
