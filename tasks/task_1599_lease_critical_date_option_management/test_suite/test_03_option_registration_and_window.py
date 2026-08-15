"""Option registration, temporal-order and rate-term coherence, and the
closed-closed notice-window membership rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_option,
    create_lease_payload,
    create_notice_payload,
    create_option_payload,
    get_success_data,
    set_clock,
    setup_active_lease,
    setup_option_on_active_lease,
    setup_portfolio_with_contacts,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestOptionRegistrationValidation:
    def test_temporal_order_close_before_open_rejected(self, api):
        """PRD §3.3: "Registration enforces temporal order first — the close date
        must fall on or after the open date, and an inversion is rejected with
        `ERR_TEMPORAL_ORDER`."

        Design: Corner/validations/temporal_order_close_before_open_rejected
        """
        ws = setup_active_lease(name="V1", region="WEST")
        payload = create_option_payload(
            option_type="RENEWAL",
            notice_window_open_date="2026-12-31T00:00:00Z",
            notice_window_close_date="2026-08-01T00:00:00Z",  # before open
            target_commencement_date="2028-01-01T00:00:00Z",
            extension_years=5,
            rate_determination="FIXED",
            fixed_rent_cents_per_rsf_year=4200,
        )
        resp = api.create_option(ws["pid"], ws["lid"], payload, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_ORDER)

    def test_rate_terms_fair_market_with_fixed_rent_rejected(self, api):
        """PRD §3.3: "a `FIXED` option must carry a positive
        `fixed_rent_cents_per_rsf_year`, a `FAIR_MARKET` option must not carry one
        at all ... any incoherence is rejected with `ERR_RATE_TERMS_INCOHERENT`."

        Design: Corner/validations/rate_terms_fair_market_with_fixed_rent_rejected
        """
        ws = setup_active_lease(name="V2", region="WEST")
        payload = create_option_payload(
            option_type="RENEWAL",
            notice_window_open_date="2026-08-01T00:00:00Z",
            notice_window_close_date="2026-12-31T00:00:00Z",
            target_commencement_date="2028-01-01T00:00:00Z",
            extension_years=5,
            rate_determination="FAIR_MARKET",
            fixed_rent_cents_per_rsf_year=4200,  # forbidden under FAIR_MARKET
        )
        resp = api.create_option(ws["pid"], ws["lid"], payload, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_RATE_TERMS_INCOHERENT)


class TestNoticeWindowBoundaries:
    def test_exercise_window_close_date_is_inclusive(self, api):
        """PRD §3.3: "Both window bounds are inclusive: a notice dated exactly on
        the close date is timely, while one dated the day after lapses the
        option."

        Design: Difficulty/resource_temporal_overlap/exercise_window_closed_closed_membership
        """
        ws = setup_active_lease(name="P15", region="WEST")
        option = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="EXPANSION",
                notice_window_open_date="2026-08-01T00:00:00Z",
                notice_window_close_date="2026-09-30T00:00:00Z",
                target_commencement_date="2027-01-01T00:00:00Z",
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4200,
            ),
            ws["am_headers"],
        ))
        ws["oid"] = option["id"]
        # Pin the clock at the very end of the closing day.
        set_clock("2026-09-30T23:59:59Z")

        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        payload = create_notice_payload(
            lease["version"], delivery_method="EMAIL_IF_PERMITTED")
        resp = api.create_notice(ws["pid"], ws["lid"], ws["oid"], payload,
                                 ws["am_headers"])
        notice = validate_success(resp, 201)
        assert notice["status"] == "SENT", (
            "Notice created on the closing day succeeds — the close bound is inclusive"
        )
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "NOTICE_SENT"

    def test_exercise_window_open_date_is_inclusive(self, api):
        """PRD §3.3: "Both window bounds are inclusive"
        PRD §3.5: "the current clock date must fall within the notice window,
        both bounds inclusive (else `ERR_NOTICE_WINDOW_CLOSED`)"

        Design: Difficulty/resource_temporal_overlap/exercise_window_closed_closed_membership
        """
        ws = setup_active_lease(name="P15-open", region="WEST")
        option = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="EXPANSION",
                notice_window_open_date="2026-08-01T00:00:00Z",
                notice_window_close_date="2026-09-30T00:00:00Z",
                target_commencement_date="2027-01-01T00:00:00Z",
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4200,
            ),
            ws["am_headers"],
        ))
        ws["oid"] = option["id"]
        # Pin the clock at the very start of the open day.
        set_clock("2026-08-01T00:00:00Z")
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        payload = create_notice_payload(lease["version"],
                                        delivery_method="CERTIFIED_MAIL")
        resp = api.create_notice(ws["pid"], ws["lid"], ws["oid"], payload,
                                 ws["am_headers"])
        notice = validate_success(resp, 201)
        assert notice["status"] == "SENT", (
            "Notice created on the opening day succeeds — the open bound is inclusive"
        )
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "NOTICE_SENT"

    def test_notice_before_window_open_rejected(self, api):
        """PRD §3.5: "the current clock date must fall within the notice window,
        both bounds inclusive (else `ERR_NOTICE_WINDOW_CLOSED`)"

        Design: Corner/errors/err_notice_window_closed_before_open_date
        """
        ws = setup_active_lease(name="X3", region="WEST")
        option = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="RENEWAL",
                notice_window_open_date="2026-09-01T00:00:00Z",
                notice_window_close_date="2026-12-31T00:00:00Z",
                target_commencement_date="2028-01-01T00:00:00Z",
                extension_years=5,
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4200,
            ),
            ws["am_headers"],
        ))
        ws["oid"] = option["id"]
        # Clock lands before the window opens.
        set_clock("2026-08-15T00:00:00Z")

        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        payload = create_notice_payload(lease["version"], delivery_method="COURIER")
        resp = api.create_notice(ws["pid"], ws["lid"], ws["oid"], payload,
                                 ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_CLOSED)
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "AVAILABLE", (
            "A rejected notice attempt must not move the option"
        )


class TestNoticeCreationGatedByLeaseState:
    def test_notice_create_succeeds_on_active_lease(self, api):
        """PRD §3.5: "Four gates guard the first notice, evaluated in order: the
        parent lease must be `ACTIVE` or `EXPIRING` (else `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/notice_creation_gated_by_lease_state
        """
        # Happy path: lease is ACTIVE, notice create succeeds.
        ws = setup_option_on_active_lease(
            name="P13-OK", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",  # fixed syntax
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4200,
            })
        set_clock("2026-09-01T00:00:00Z")
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        payload = create_notice_payload(lease["version"], delivery_method="COURIER")
        resp = api.create_notice(ws["pid"], ws["lid"], ws["oid"], payload,
                                 ws["am_headers"])
        notice = validate_success(resp, 201)
        assert notice["status"] == "SENT"

    def test_notice_create_blocked_on_draft_lease(self, api):
        """PRD §3.5: "the parent lease must be `ACTIVE` or `EXPIRING` (else
        `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/notice_creation_gated_by_lease_state
        """
        # Build a DRAFT lease (no activate) with an option, clock inside the window.
        ws = setup_portfolio_with_contacts(name="P13", region="WEST")
        lease = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="OF-13",
                rentable_square_feet=5000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150,
                holdover_tier2_pct=200,
            ),
            ws["am_headers"],
        ))
        ws["lease"] = lease
        ws["lid"] = lease["id"]
        option = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="RENEWAL",
                notice_window_open_date="2026-08-01T00:00:00Z",
                notice_window_close_date="2026-12-31T00:00:00Z",
                target_commencement_date="2028-01-01T00:00:00Z",
                extension_years=5,
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4200,
            ),
            ws["am_headers"],
        ))
        ws["oid"] = option["id"]
        set_clock("2026-09-01T00:00:00Z")
        payload = create_notice_payload(lease["version"], delivery_method="COURIER")
        resp = api.create_notice(ws["pid"], ws["lid"], ws["oid"], payload,
                                 ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "AVAILABLE", (
            "A DRAFT parent lease blocks the notice path"
        )
