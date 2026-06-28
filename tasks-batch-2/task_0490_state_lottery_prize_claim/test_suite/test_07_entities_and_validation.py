"""Entity CRUD, defaults, computed/system fields, type/required-field validation,
uniqueness, pagination filters, and FK existence.

Covers the entities, calculations (self-exclusion), validations, endpoints, and
errors corner sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_game, create_retailer, create_active_retailer, create_provisioned_terminal,
    setup_game_retailer_terminal, sell_ticket, create_player, set_clock,
    ApiErrorId, TEST_USERS,
)

LIC = TEST_USERS["licensing_admin_headers"]
OFF = TEST_USERS["lottery_officer_headers"]
CLERK = TEST_USERS["claims_clerk_headers"]
OP = TEST_USERS["terminal_operator_headers"]


class TestEntityCreation:
    def test_create_game_returns_201_with_defaults(self, api):
        """PRD 3.1: "it defaults to 60000000 (six hundred thousand dollars) and must be a
        non-negative integer."
        PRD 3.1: "A game is created already in `ACTIVE` `status` (the only value the game
        lifecycle takes in this version), set by system initialization with no separate
        activation step."

        Design: Corner/entities/create_game_returns_201_with_defaults
        """
        data = validate_success(
            api.create_game({"name": "BaseGame", "game_type": "JACKPOT",
                             "claim_window_days": 30}, OFF), expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["federal_withholding_threshold_cents"] == 60000000
        assert data["federal_withholding_rate"] == 0.24
        assert data["state_withholding_rate"] == 0.05
        assert data["cash_option_factor"] == 0.60
        assert data["annuity_years"] == 30
        assert data["version"] == 1

    def test_create_game_system_id_and_version(self, api):
        """PRD 2.4: "Every entity in the system carries a server-minted `id` formatted as a
        UUID with no type prefix"
        PRD 2.4: "an integer `version` that begins at its initial value when the resource
        is created"

        Design: Corner/entities/create_game_system_id_and_timestamps_generated
        """
        from test_helpers import is_valid_uuid
        data = validate_success(
            api.create_game({"name": "SysGame", "game_type": "DAILY",
                             "claim_window_days": 7}, OFF), expected_status=201)
        assert data["version"] == 1
        assert is_valid_uuid(data["id"]), data["id"]

    def test_create_retailer_default_rates(self, api):
        """PRD 3.2: "the fraction of gross sales earned as commission, defaulting to 0.06
        and bounded at least 0 and below 1) and its `cashing_bonus_rate` (the fraction of a
        counter-paid prize the retailer earns as a cashing bonus, defaulting to 0.01 under
        the same bounds)."
        PRD 3.2: "A new retailer begins with `license_status` `PENDING`."

        Design: Corner/entities/create_retailer_default_commission_rate_applied
        """
        data = validate_success(
            api.create_retailer({"business_name": "Default Co", "tax_id": "TAX-D1"}, LIC),
            expected_status=201)
        assert data["commission_rate"] == 0.06
        assert data["cashing_bonus_rate"] == 0.01
        assert data["license_status"] == "PENDING"
        assert data["commission_balance_cents"] == 0

    def test_create_terminal_bad_retailer_fk_404(self, api):
        """PRD 2.9: "This applies to path identifiers ... and to body foreign keys alike
        (for example a `retailer_id` on a terminal ...)."

        Design: Corner/entities/create_terminal_bad_retailer_fk_returns_404
        """
        resp = api.create_terminal(
            {"retailer_id": "00000000-0000-4000-8000-000000000002",
             "serial_number": "SN-X"}, LIC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_ticket_claim_deadline_computed(self, api):
        """PRD 3.4: "The `claim_deadline` is computed as the `draw_date` plus exactly
        `claim_window_days` whole days (twenty-four hours per day)"
        PRD 3.4: "A new ticket begins with `validation_status` `UNVALIDATED` and
        `second_chance_status` `INELIGIBLE`"

        Design: Corner/entities/ticket_claim_deadline_computed_input_ignored
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z",
            game_overrides={"claim_window_days": 30})
        tk = sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                         draw_date="2026-01-10T00:00:00Z")
        assert tk["claim_deadline"] == "2026-02-09T00:00:00.000Z", tk["claim_deadline"]
        assert tk["validation_status"] == "UNVALIDATED"
        assert tk["second_chance_status"] == "INELIGIBLE"


class TestValidationErrors:
    def test_create_retailer_missing_tax_id_invalid_request(self, api):
        """PRD 2.11: "every create and update validates that required fields are present
        and that each value has the correct type and falls within its allowed enum or
        numeric range; a malformed body is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_retailer_missing_tax_id_returns_invalid_request
        """
        resp = api.create_retailer({"business_name": "No Tax"}, LIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_game_invalid_game_type_rejected(self, api):
        """PRD 3.1: "its `game_type` — one of `JACKPOT`, `INSTANT`, or `DAILY` — and the
        `claim_window_days`, an integer of at least 1 giving how many days after a ticket's
        draw a winning ticket remains claimable before it may escheat."
        PRD 2.11: "a malformed body is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_game_invalid_game_type_enum_rejected
        """
        resp = api.create_game({"name": "BadType", "game_type": "LOTTO",
                                "claim_window_days": 30}, OFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_retailer_not_found_404(self, api):
        """PRD 2.9: "Every resource referenced by a request — whether by a path identifier
        or by a foreign-key field in the request body — must exist."

        Design: Corner/entities/get_retailer_not_found_returns_404
        """
        resp = api.get_retailer("00000000-0000-4000-8000-000000000001", OFF)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_duplicate_tax_id_rejected(self, api):
        """PRD 2.10: "A retailer's `tax_id` is unique across retailers ... An attempt to
        create a record that would duplicate any of these is rejected with
        `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/duplicate_tax_id_rejected
        """
        validate_success(
            api.create_retailer({"business_name": "Dup1", "tax_id": "TAX-DUP"}, LIC),
            expected_status=201)
        resp = api.create_retailer({"business_name": "Dup2", "tax_id": "TAX-DUP"}, LIC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    def test_list_limit_over_max_rejected(self, api):
        """PRD 2.3: "A `limit` or `offset` outside its permitted range — for example a
        `limit` above 100 or below 1 — is rejected with `ERR_VALIDATION_FILTER_INVALID`."

        Design: Corner/validations/list_limit_over_max_rejected
        """
        resp = api.list_games(OFF, params={"limit": 500})
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FILTER_INVALID.value)

    def test_claim_after_deadline_window_expired(self, api):
        """PRD 3.5: "The claim also fails with `ERR_CLAIM_WINDOW_EXPIRED` if the logical
        clock has strictly passed the ticket's `claim_deadline`."

        Design: Corner/validations/claim_after_deadline_window_expired
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        tk = sell_ticket(game["id"], term["id"], declared_tier=1, gross_prize_cents=1000000,
                         draw_date="2026-01-10T00:00:00Z")  # deadline 2026-02-09
        set_clock("2026-02-09T00:00:00Z")
        validate_success(api.validate_ticket(tk["id"], OP))  # winner at deadline
        player = create_player()
        set_clock("2026-02-10T00:00:00Z")  # strictly past deadline
        resp = api.create_prize_claim(
            {"ticket_id": tk["id"], "player_id": player["id"], "payout_option": "CASH"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED.value)


class TestListing:
    def test_list_games_pagination_envelope(self, api):
        """PRD 2.3: "List responses carry the pagination bookkeeping in the `meta` object
        of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_games_pagination_envelope
        """
        validate_success(api.create_game({"name": "L1", "game_type": "DAILY",
                                          "claim_window_days": 7}, OFF), expected_status=201)
        validate_success(api.create_game({"name": "L2", "game_type": "DAILY",
                                          "claim_window_days": 7}, OFF), expected_status=201)
        data, meta = validate_paginated(api.list_games(OFF))
        assert meta["total_count"] == 2, meta["total_count"]
        assert meta["has_more"] is False, meta["has_more"]

    def test_list_terminals_filtered_by_retailer(self, api):
        """PRD 3.3: "Terminals may be listed and filtered by `retailer_id` and by
        `status`."

        Design: Corner/endpoints/list_terminals_filtered_by_retailer
        """
        ret = create_retailer()
        create_provisioned_terminal(ret["id"])
        create_provisioned_terminal(ret["id"])
        data, meta = validate_paginated(api.list_terminals(LIC, params={"retailer_id": ret["id"]}))
        assert meta["total_count"] == 2, meta["total_count"]
