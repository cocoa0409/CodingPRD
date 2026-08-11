"""Entity-level claims (PRD §2.2, §2.3, §2.5, §3.1, §3.2): creation defaults,
computed fields, type constraints, not-found, pagination, immutability.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, is_valid_uuid, NON_EXISTENT_UUID,
    make_security, make_account, make_event_source,
    create_security_payload, create_account_payload,
    create_position_lot_payload, create_source_notification_payload,
    split_terms,
)
from test_helpers.fixtures import ADMIN, VENDOR
from test_helpers import api_client


class TestSecurityCreationDefaults:
    def test_security_created_active_at_version_one(self, api):
        """PRD §3.1: "A security begins life `ACTIVE`". PRD §2.5: "**`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix." and "**`version` (integer):** a system-managed integer that increments by one on every mutation of the resource and underpins optimistic concurrency control."

        Design: Corner/entities/security_creation_defaults_status_active
        """
        sec = validate_success(api.create_security(
            create_security_payload(ticker="ACME", cusip="CUSPA00001",
                                    name="Acme Corp"), ADMIN), 201)
        assert sec["status"] == "ACTIVE"
        assert sec["version"] == 1
        assert is_valid_uuid(sec["id"])
        assert sec["created_at"] and sec["updated_at"]


class TestAccountDefaults:
    def test_opening_cash_defaults_to_zero(self, api):
        """PRD §3.1: "Client accounts are opened by the same role with an `account_number` (unique across accounts), a `holder_name`, and an optional `opening_cash_cents` that defaults to zero. At creation the account's `cash_balance_cents` is initialized to the opening amount, `total_cost_basis_cents` starts at zero, `pending_entitlement_count` starts at zero, and the account is `ACTIVE`."

        Design: Corner/entities/account_opening_cash_defaults_to_zero
        """
        acct = validate_success(api.create_account(
            create_account_payload(account_number="A-9", holder_name="Nine"),
            ADMIN), 201)
        assert acct["cash_balance_cents"] == 0
        assert acct["total_cost_basis_cents"] == 0
        assert acct["pending_entitlement_count"] == 0
        assert acct["status"] == "ACTIVE"

    def test_computed_cash_balance_input_ignored(self, api):
        """PRD §2.9: "Every account carries three derived figures that the server recomputes eagerly on each contributing mutation" and "An account's `cash_balance_cents` is its `opening_cash_cents` plus the sum of every cash delta ever applied to it". PRD §3.1: "an optional `opening_cash_cents` that defaults to zero. At creation the account's `cash_balance_cents` is initialized to the opening amount".

        Design: Corner/entities/account_computed_cash_input_ignored
        """
        acct = validate_success(api.create_account(
            create_account_payload(account_number="A-10", holder_name="Ten",
                                   cash_balance_cents=999999), ADMIN), 201)
        assert acct["cash_balance_cents"] == 0


class TestPositionLotConstraints:
    def test_zero_quantity_rejected(self, api):
        """PRD §3.1: "The quantity must be greater than zero and expressed in no more than four decimal places; a non-positive quantity or one with finer precision is rejected with `ERR_LOT_QUANTITY_INVALID`."

        Design: Corner/entities/position_lot_zero_quantity_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPA00002")
        acct = make_account(account_number="A-1", holder_name="One")
        resp = api.create_position_lot(
            create_position_lot_payload(
                account_id=acct["id"], security_id=sec["id"], quantity=0,
                acquisition_date="2026-04-01", cost_basis_total_cents=100),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_LOT_QUANTITY_INVALID)


class TestEventNotFound:
    def test_get_nonexistent_event_returns_404_envelope(self, api):
        """PRD §2.10: "Each resource type has its own not-found error: `ERR_SECURITY_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_POSITION_LOT_NOT_FOUND`, `ERR_EVENT_SOURCE_NOT_FOUND`, `ERR_SOURCE_NOTIFICATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`" and the catalog ends "`ERR_RECON_BREAK_NOT_FOUND` — all HTTP 404". PRD §2.2: the error envelope carries "response_type": "error" and meta with api_request_id.

        Design: Corner/entities/event_get_nonexistent_returns_404
        """
        resp = api.get_event("11111111-2222-3333-4444-555555555555", ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"]


class TestSecuritiesListPagination:
    def test_limit_offset_windowing(self, api):
        """PRD §2.3: "The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`." and "The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100".

        Design: Corner/entities/securities_list_pagination_envelope
        """
        make_security(ticker="ACME", cusip="CUSPA00003")
        make_security(ticker="BRAVO", cusip="CUSPA00004", name="Bravo Inc")
        data1, meta1 = validate_paginated(
            api.list_securities(ADMIN, params={"limit": 1, "offset": 0}))
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        data2, meta2 = validate_paginated(
            api.list_securities(ADMIN, params={"limit": 1, "offset": 1}))
        assert len(data2) == 1
        assert meta2["has_more"] is False
        assert data1[0]["ticker"] != data2[0]["ticker"]


class TestSourceNotificationImmutability:
    def test_no_version_or_updated_at_on_ingest_record(self, api):
        """PRD §2.5: "Three resource types are deliberately immutable audit or ledger records and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from them: a `SourceNotification` (an ingest record)".
        PRD §3.2: "A notification is born `RECEIVED`".

        Design: Corner/entities/source_notification_immutable_no_version
        """
        sec = make_security(ticker="ACME", cusip="CUSPA00005")
        src = make_event_source(name="Vendor Alpha")
        notif = validate_success(api.create_source_notification(
            create_source_notification_payload(
                source_id=src["id"], security_id=sec["id"], event_type="SPLIT",
                record_date="2026-05-15", announced_terms=split_terms()),
            VENDOR), 201)
        assert is_valid_uuid(notif["id"])
        assert notif["created_at"]
        assert notif["status"] == "RECEIVED"
        assert "version" not in notif
        assert "updated_at" not in notif
