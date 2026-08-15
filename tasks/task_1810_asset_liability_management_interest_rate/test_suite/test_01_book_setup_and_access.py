"""Book setup, position intake, listing/pagination, and baseline access
control (PRD §2.1, §2.3, §2.5, §2.7, §2.9, §3.1)."""
from test_helpers import (
    AN1,
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_book,
    add_position,
    assert_alm_book,
    assert_position,
    create_book,
    create_book_payload,
    create_position_payload,
    get_book,
    get_book_version,
    is_valid_uuid,
    setup_book1_active,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBookCreation:
    def test_create_book_missing_name_rejected(self, api):
        """PRD §3.1: "A `TreasuryAnalyst` opens a new book by supplying a
        display `name`, a flat base yield-curve level `base_curve_rate_bps` in
        basis points (for example, 400 represents a 4.00% curve), and
        optionally `min_hedged_notional_cents`, the policy floor for total
        hedged notional that defaults to 0 when omitted." PRD §2.9: "required
        fields present, enums valid, ranges valid, kind-conditional fields
        present (`ERR_INVALID_REQUEST`, `ERR_DEPOSIT_SEGMENT_REQUIRED`,
        `ERR_ASSUMPTION_PARAMS_MISMATCH`, `ERR_OBSERVED_VALUE_INVALID`)."

        Design: Corner/entities/create_book_missing_name_rejected
        """
        resp = api.create_book({"base_curve_rate_bps": 400}, AN1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_request_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/request_missing_auth_header_rejected
        """
        resp = api.create_book(create_book_payload(), NO_AUTH_HEADERS)
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_regulator_write_attempt_forbidden(self, api, regulator_headers):
        """PRD §2.1: "a caller whose role is not permitted for the endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD §2.1: "A
        `Regulator` observes everything on a read-only basis."

        Design: Corner/rbac/regulator_write_attempt_forbidden
        """
        book = create_book()
        resp = api.create_book(create_book_payload("Book X"), regulator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        data = validate_success(api.get_book(book["id"], regulator_headers))
        assert data["id"] == book["id"]

    def test_get_book_not_found_returns_404(self, api):
        """PRD §2.9: "the server validates the existence of each identifier
        strictly left-to-right and rejects the request with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not correspond to an
        existing resource."

        Design: Corner/entities/get_book_not_found_returns_404
        """
        resp = api.get_book(NON_EXISTENT_UUID, AN1)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPositionIntake:
    def test_position_deposit_without_segment_rejected(self, api):
        """PRD §3.1: "When the `category` is `DEPOSIT`, a `deposit_segment` of
        `RETAIL_NONMATURITY`, `BUSINESS_NONMATURITY`, or `TIME` must be
        present; omitting it is rejected with `ERR_DEPOSIT_SEGMENT_REQUIRED`
        (HTTP 422)."

        Design: Corner/entities/position_deposit_without_segment_rejected
        """
        book = create_book()
        resp = api.create_position(
            book["id"],
            create_position_payload("DEPOSIT", 80_000_000, 50, 0.0, 0.5),
            AN1,
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_SEGMENT_REQUIRED)
        data, meta = validate_paginated(api.list_positions(book["id"], AN1))
        assert data == [] and meta["total_count"] == 0, (
            "the rejected position must not be persisted")

    def test_position_and_scenario_defaults_applied(self, api):
        """PRD §3.1: "optionally `min_hedged_notional_cents`, the policy floor
        for total hedged notional that defaults to 0 when omitted." PRD §3.1:
        "A loan may additionally carry `is_prepayment_eligible`, defaulting to
        `false`, marking it as subject to the prepayment assumption set."
        PRD §3.1: "Each new position lands in `ACTIVE` status". PRD §3.3:
        "The projection horizon `horizon_months` must be 12 or 24 and defaults
        to 12." PRD §3.3: "new scenarios are `ACTIVE`."

        Design: Corner/entities/position_and_scenario_defaults_applied
        """
        book = create_book()  # min_hedged_notional_cents omitted
        assert book["min_hedged_notional_cents"] == 0
        p = add_position(book["id"], category="LOAN", balance_cents=1_000_000,
                         rate_bps=600, scheduled_runoff_pct=20.0,
                         duration_years=3.0)
        assert_position(p)
        assert p["is_prepayment_eligible"] is False
        assert p["status"] == "ACTIVE"
        resp = api.create_scenario(
            book["id"],
            {"name": "UP200", "kind": "PARALLEL_SHOCK", "shock_bps": 200},
            AN1)
        sc = validate_success(resp, 201)
        assert sc["horizon_months"] == 12
        assert sc["status"] == "ACTIVE"

    def test_position_create_system_field_input_ignored(self, api):
        """PRD §3.1: "Each new position lands in `ACTIVE` status, the book's
        balance totals are recomputed, and the book's `version` advances by
        one." PRD §2.5: "`id` (string): a server-minted UUID with no type
        prefix."

        Design: Corner/entities/position_create_system_field_input_ignored
        """
        book = create_book()
        payload = create_position_payload("LOAN", 1_000_000, 600, 20.0, 3.0)
        payload["status"] = "RETIRED"  # client-supplied system field
        resp = api.create_position(book["id"], payload, AN1)
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE", (
            "initial status is server-controlled: a new position is ACTIVE")
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"


class TestPositionListing:
    def test_list_positions_pagination_envelope(self, api, regulator_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items returned; it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies how many items to skip and
        defaults to 0." PRD §2.2: "The `meta` object of a list response
        carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_positions_pagination_envelope
        """
        book = create_book()
        add_position(book["id"], category="LOAN", balance_cents=1_000_000,
                     rate_bps=600, scheduled_runoff_pct=20.0,
                     duration_years=3.0)
        add_position(book["id"], category="SECURITY", balance_cents=2_000_000,
                     rate_bps=400, scheduled_runoff_pct=0.0,
                     duration_years=4.0)
        add_position(book["id"], category="DEPOSIT", deposit_segment="TIME",
                     balance_cents=3_000_000, rate_bps=150,
                     scheduled_runoff_pct=100.0, duration_years=1.0)

        page1, meta1 = validate_paginated(api.list_positions(
            book["id"], regulator_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_positions(
            book["id"], regulator_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestActivationAndRetirement:
    def test_book_activation_requires_asset_and_liability(self, api):
        """PRD §3.1: "Activation moves the book from `DRAFT` to `ACTIVE` and
        is permitted only when the book holds at least one `ACTIVE` position
        whose `category` is `LOAN` or `SECURITY` and at least one `ACTIVE`
        position whose `category` is `DEPOSIT` or `BORROWING`; otherwise the
        activation is rejected with `ERR_BOOK_ACTIVATION_INCOMPLETE`
        (HTTP 409)."

        Design: Corner/endpoints/book_activation_requires_asset_and_liability
        """
        book = create_book()
        add_position(book["id"], category="LOAN", balance_cents=1_000_000,
                     rate_bps=600, scheduled_runoff_pct=20.0,
                     duration_years=3.0)
        resp = api.activate_book(book["id"], AN1)
        validate_error(resp, ApiErrorId.ERR_BOOK_ACTIVATION_INCOMPLETE)
        add_position(book["id"], category="DEPOSIT",
                     deposit_segment="RETAIL_NONMATURITY",
                     balance_cents=80_000_000, rate_bps=50,
                     scheduled_runoff_pct=0.0, duration_years=0.5)
        data = validate_success(api.activate_book(book["id"], AN1))
        assert_alm_book(data)
        assert data["status"] == "ACTIVE"

    def test_retired_position_excluded_from_book_totals(self, api):
        """PRD §3.1: "Retirement recomputes the book totals with the position
        excluded and advances the book's `version` by one." PRD §2.8:
        "`total_liabilities_cents` is the sum of `balance_cents` over the
        book's `ACTIVE` positions with `category` either `DEPOSIT` or
        `BORROWING`." PRD §3.1: "The position list of a book can be filtered
        by `category` and `status`."

        Design: Corner/entities/retired_position_excluded_from_book_totals
        """
        book = create_book()
        add_position(book["id"], category="LOAN", balance_cents=100_000_000,
                     rate_bps=600, scheduled_runoff_pct=20.0,
                     duration_years=3.0)
        add_position(book["id"], category="DEPOSIT",
                     deposit_segment="RETAIL_NONMATURITY",
                     balance_cents=80_000_000, rate_bps=50,
                     scheduled_runoff_pct=0.0, duration_years=0.5)
        bor = add_position(book["id"], category="BORROWING",
                           balance_cents=40_000_000, rate_bps=450,
                           scheduled_runoff_pct=25.0, duration_years=2.0)
        activate_book(book["id"])
        before = get_book(book["id"])
        assert before["total_liabilities_cents"] == 120_000_000

        data = validate_success(api.retire_position(bor["id"], AN1))
        assert data["status"] == "RETIRED"
        after = get_book(book["id"])
        assert after["total_liabilities_cents"] == 80_000_000, (
            "the retired borrowing is excluded from total_liabilities_cents")
        assert after["version"] > before["version"]
        retired, meta = validate_paginated(api.list_positions(
            book["id"], AN1, params={"status": "RETIRED"}))
        assert len(retired) == 1 and retired[0]["id"] == bor["id"]
        assert meta["total_count"] == 1

    def test_retire_position_with_open_hedge_rejected(self, api):
        """PRD §3.1: "retiring moves it from `ACTIVE` to `RETIRED`, but only
        while no hedge relationship in `PROPOSED`, `DESIGNATED`, or `ACTIVE`
        status references it — a referenced position is rejected with
        `ERR_POSITION_HAS_ACTIVE_HEDGE` (HTTP 409)."

        Design: Corner/endpoints/retire_position_with_open_hedge_rejected
        """
        ctx = setup_book1_active(with_security_and_borrowing=False)
        h = validate_success(api.create_hedge(
            ctx["book"]["id"],
            {"position_id": ctx["l1"]["id"], "instrument": "PAYER_SWAP",
             "designation_type": "FAIR_VALUE", "notional_cents": 60_000_000,
             "fixed_rate_bps": 350},
            AN1), 201)
        assert h["status"] == "PROPOSED"
        resp = api.retire_position(ctx["l1"]["id"], AN1)
        validate_error(resp, ApiErrorId.ERR_POSITION_HAS_ACTIVE_HEDGE)
        pos = validate_success(api.get_position(ctx["l1"]["id"], AN1))
        assert pos["status"] == "ACTIVE"


class TestPositionPatchOcc:
    def test_occ_position_patch_stale_book_version_rejected(self, api):
        """PRD §2.7: "Two write operations are guarded by optimistic
        concurrency control against the parent book: creating a simulation run
        against a book (`POST /books/{id}/simulation-runs`) and patching a
        position's economics (`PATCH /positions/{id}`)." PRD §2.7: "the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
        client must re-read the book and resubmit with the fresh version."

        Design: Corner/cross_cutting_complexity_layers/occ_position_patch_stale_book_version_rejected
        """
        ctx = setup_book1_active(with_security_and_borrowing=False)
        bv = get_book_version(ctx["book"]["id"])
        first = validate_success(api.patch_position(
            ctx["l1"]["id"],
            {"expected_book_version": bv, "rate_bps": 610}, AN1))
        assert first["rate_bps"] == 610
        resp = api.patch_position(
            ctx["l1"]["id"],
            {"expected_book_version": bv, "rate_bps": 620}, AN1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        pos = validate_success(api.get_position(ctx["l1"]["id"], AN1))
        assert pos["rate_bps"] == 610, (
            "the stale patch must not overwrite the first patch")
