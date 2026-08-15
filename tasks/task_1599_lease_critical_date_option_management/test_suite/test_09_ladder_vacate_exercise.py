"""Expiration ladder aggregation, vacate-at-expiration supersession, the
notice-acknowledge cascade (option → lease → ledger), and immediate
consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lease,
    create_lease_payload,
    create_notice_payload,
    create_option_payload,
    get_success_data,
    set_clock,
    setup_active_lease,
    setup_notice_delivered,
    setup_option_on_active_lease,
    setup_portfolio_with_contacts,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestLadderComputation:
    def test_ladder_input_set_excludes_terminal_leases(self, api):
        """PRD §3.2: "the system sums the `rentable_square_feet` of leases in
        `ACTIVE`, `EXPIRING`, or `HOLDOVER` whose `expiration_date` falls in
        that year, then expresses each year's expiring footage as a whole
        percentage of `total_active_square_feet`"

        Design: Corner/calculations/ladder_input_set_excludes_terminal_leases
        """
        ws = setup_active_lease(
            name="C2", region="EAST", laddering_max_pct_per_year=40,
            premises_label="A", rentable_square_feet=8000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
            holdover_tier1_pct=150, holdover_tier2_pct=200)
        # A DRAFT lease with a huge RSF must not dilute the ladder.
        get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="B", rentable_square_feet=50000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            ws["am_headers"]))
        ladder = validate_success(api.get_portfolio_ladder(ws["pid"], ADMIN))
        assert ladder["posture"] == "LADDER_STRESSED", (
            "8000/8000 = 100% > 40 — DRAFT lease is excluded"
        )
        assert ladder["posture_year"] == 2027
        portfolio = validate_success(api.get_portfolio(ws["pid"], ADMIN))
        assert portfolio["total_active_square_feet"] == 8000

    def test_computed_ladder_read_matches_aggregate(self, api):
        """PRD §3.2: "For each calendar year from the current clock year through
        the latest expiration year, the system sums the `rentable_square_feet`
        of leases in `ACTIVE`, `EXPIRING`, or `HOLDOVER` whose `expiration_date`
        falls in that year, then expresses each year's expiring footage as a
        whole percentage of `total_active_square_feet`, rounded half up."

        Design: Corner/endpoints/computed_ladder_read_matches_aggregate
        """
        ws = setup_portfolio_with_contacts(
            name="E3", region="EAST", laddering_max_pct_per_year=50)
        leases_spec = [
            ("A", 6000, "2027-12-31T00:00:00Z"),
            ("B", 6000, "2028-12-31T00:00:00Z"),
            ("C", 8000, "2027-06-30T00:00:00Z"),
        ]
        for label, rsf, expiration in leases_spec:
            lease = get_success_data(api.create_lease(
                ws["pid"],
                create_lease_payload(
                    premises_label=label, rentable_square_feet=rsf,
                    base_rent_cents_per_rsf_year=4000,
                    commencement_date="2026-01-01T00:00:00Z",
                    expiration_date=expiration,
                    holdover_tier1_pct=150, holdover_tier2_pct=200),
                ws["am_headers"]))
            get_success_data(api.activate_lease(
                ws["pid"], lease["id"], {}, ws["am_headers"]))
        ladder = validate_success(api.get_portfolio_ladder(ws["pid"], ADMIN))
        assert ladder["posture"] == "LADDER_STRESSED"
        assert ladder["posture_year"] == 2027
        years = {y["year"]: y for y in ladder["years"]}
        # 2027: A + C = 14000 / 20000 = 70; 2028: B = 6000 / 20000 = 30.
        assert years[2027]["expiring_rsf"] == 14000
        assert years[2027]["exposure_pct"] == 70
        assert years[2028]["expiring_rsf"] == 6000
        assert years[2028]["exposure_pct"] == 30


class TestLadderBoundary:
    def _setup_four_active_leases(self, api, name, cap):
        """Four ACTIVE 4000-RSF leases expiring 2027-2030 (each year 25%)."""
        ws = setup_portfolio_with_contacts(
            name=name, region="WEST", laddering_max_pct_per_year=cap)
        expirations = ["2027-12-31T00:00:00Z", "2028-12-31T00:00:00Z",
                       "2029-12-31T00:00:00Z", "2030-12-31T00:00:00Z"]
        for i, exp in enumerate(expirations):
            lease = get_success_data(api.create_lease(
                ws["pid"],
                create_lease_payload(
                    premises_label=chr(ord("A") + i), rentable_square_feet=4000,
                    base_rent_cents_per_rsf_year=4000,
                    commencement_date="2026-01-01T00:00:00Z",
                    expiration_date=exp,
                    holdover_tier1_pct=150, holdover_tier2_pct=200),
                ws["am_headers"]))
            get_success_data(api.activate_lease(
                ws["pid"], lease["id"], {}, ws["am_headers"]))
        return ws

    def test_ladder_exposure_exactly_at_cap_does_not_trip(self, api):
        """PRD §3.2: "a year whose exposure equals the cap exactly does not trip
        the posture"
        PRD §3.2: "When any year's exposure strictly exceeds
        `laddering_max_pct_per_year`, the portfolio's `posture` reads
        `LADDER_STRESSED`"

        Design: Difficulty/boundary_precision_check/ladder_exposure_exactly_at_cap_does_not_trip
        """
        ws = self._setup_four_active_leases(api, "P11", cap=40)
        # Fifth lease E (4000 RSF, expiring 2027) lands 2027 exposure at 8000/20000 = 40% = cap.
        lease_e = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="E", rentable_square_feet=4000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            ws["am_headers"]))
        resp = api.activate_lease(ws["pid"], lease_e["id"],
                                  {"enforce_ladder": True}, ws["am_headers"])
        validate_success(resp, 200)  # strict > means equality does NOT trip
        ladder = validate_success(api.get_portfolio_ladder(ws["pid"], ADMIN))
        assert ladder["posture"] == "LADDER_OK"
        assert ladder["posture_year"] is None
        portfolio = validate_success(api.get_portfolio(ws["pid"], ADMIN))
        assert portfolio["total_active_square_feet"] == 20000

    def test_ladder_exposure_above_cap_with_enforce_flag_rejects(self, api):
        """PRD §3.2: "a caller who passes `enforce_ladder` as true on activation
        asks the system to reject the operation with `ERR_LADDER_BREACH` when
        the activation would push the portfolio into `LADDER_STRESSED`"

        Design: Difficulty/boundary_precision_check/ladder_exposure_exactly_at_cap_does_not_trip
        """
        ws = setup_active_lease(
            name="X1-pre", region="WEST", laddering_max_pct_per_year=40,
            premises_label="A", rentable_square_feet=12000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
            holdover_tier1_pct=150, holdover_tier2_pct=200)
        # DRAFT lease B 9000 RSF expiring 2027 — would push 2027 to 21000/21000 = 100%.
        lease_b = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="B", rentable_square_feet=9000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-06-30T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            ws["am_headers"]))
        resp = api.activate_lease(ws["pid"], lease_b["id"],
                                  {"enforce_ladder": True}, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_LADDER_BREACH)


class TestLadderEnforceFlag:
    def test_err_ladder_breach_triggered_by_enforce_flag(self, api):
        """PRD §3.2: "a caller who passes `enforce_ladder` as true on activation
        asks the system to reject the operation with `ERR_LADDER_BREACH` when
        the activation would push the portfolio into `LADDER_STRESSED`; the
        flag is off by default"

        Design: Corner/errors/err_ladder_breach_triggered_by_enforce_flag
        """
        ws = setup_active_lease(
            name="X1", region="WEST", laddering_max_pct_per_year=40,
            premises_label="A", rentable_square_feet=12000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
            holdover_tier1_pct=150, holdover_tier2_pct=200)
        lease_b = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="B", rentable_square_feet=9000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-06-30T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            ws["am_headers"]))
        resp = api.activate_lease(ws["pid"], lease_b["id"],
                                  {"enforce_ladder": True}, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_LADDER_BREACH)
        lease_b_after = validate_success(api.get_lease(
            ws["pid"], lease_b["id"], ws["am_headers"]))
        assert lease_b_after["status"] == "DRAFT", (
            "Rejected activation leaves the lease in DRAFT"
        )

    def test_ladder_breach_flag_off_by_default_allows_activation(self, api):
        """PRD §3.2: "the flag is off by default"

        Design: Corner/errors/err_ladder_breach_triggered_by_enforce_flag
        """
        ws = setup_active_lease(
            name="X1b", region="WEST", laddering_max_pct_per_year=40,
            premises_label="A", rentable_square_feet=12000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
            holdover_tier1_pct=150, holdover_tier2_pct=200)
        lease_b = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="B", rentable_square_feet=9000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-06-30T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            ws["am_headers"]))
        # Same activation WITHOUT the flag — advisory gate is off; must succeed.
        resp = api.activate_lease(ws["pid"], lease_b["id"], {}, ws["am_headers"])
        activated = validate_success(resp, 200)
        assert activated["status"] == "ACTIVE", (
            "Without enforce_ladder the advisory gate stays off and activation succeeds"
        )


class TestVacateSupersession:
    def test_vacate_then_expiration_supersedes_options(self, api):
        """PRD §3.2: "At the next clock sweep past expiration the lease then
        moves from `ACTIVE` or `EXPIRING` to `EXPIRED` instead of rolling into
        holdover: its unexercised options become `SUPERSEDED` — not `LAPSED`,
        so no missed-option penalty posts for an on-time departure — their
        `PENDING` reminders are `CANCELED`"

        Design: Corner/endpoints/vacate_then_expiration_supersedes_options
        """
        ws = setup_option_on_active_lease(
            name="E1", region="WEST",
            option_overrides={
                "option_type": "ROFR",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2027-03-31T00:00:00Z",
                "target_commencement_date": "2027-06-01T00:00:00Z",
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4000,
                "missed_option_penalty_cents": 90000,
            },
            premises_label="E1", rentable_square_feet=5000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2026-12-31T00:00:00Z",
            holdover_tier1_pct=150, holdover_tier2_pct=200,
        )
        set_clock("2026-12-15T00:00:00Z")
        get_success_data(api.vacate_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        set_clock("2027-01-01T00:00:00Z")
        lease = validate_success(api.get_lease(ws["pid"], ws["lid"], ADMIN))
        assert lease["status"] == "EXPIRED", (
            "On-time vacatur rolls the lease to EXPIRED, not HOLDOVER"
        )
        assert lease["holdover_entered_at"] is None
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "SUPERSEDED", (
            "Unexercised options are SUPERSEDED, not LAPSED"
        )
        data, meta = validate_paginated(api.list_ledger(ws["pid"], ws["lid"], ADMIN))
        assert meta["total_count"] == 0, (
            "Supersession posts no missed-option penalty"
        )


class TestNoticeAcknowledgeCascade:
    def _setup_acknowledged_exercise(self, api, name, exercise_fee_cents=100000):
        """Drive an exercise to ACKNOWLEDGED with a TERMINATION option."""
        ws = setup_notice_delivered(
            name=name, region="EAST", with_lc=True,
            option_overrides={
                "option_type": "TERMINATION",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2027-06-30T00:00:00Z",
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4800,
                "exercise_fee_cents": exercise_fee_cents,
            },
            clock="2026-09-01T00:00:00Z",
            premises_label="PL-8", rentable_square_feet=7000,
            base_rent_cents_per_rsf_year=4800,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2028-12-31T00:00:00Z",
            holdover_tier1_pct=150, holdover_tier2_pct=200,
        )
        return ws

    def test_acknowledge_moves_option_to_exercised_and_stamps_exercised_at(self, api):
        """PRD §3.5: "the first cascade hop moves the option `NOTICE_SENT` →
        `EXERCISED` ... Completion stamps `exercised_at`"

        Design: Difficulty/transitive_cascade/notice_acknowledge_cascades_option_to_lease_to_ledger
        """
        ws = self._setup_acknowledged_exercise(api, "P8", exercise_fee_cents=100000)
        get_success_data(api.acknowledge_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["lc_headers"]))
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "EXERCISED"
        assert opt["exercised_at"] == "2026-09-01T00:00:00Z", (
            "exercised_at is stamped with the logical clock at acknowledgment"
        )
        notice = validate_success(api.get_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ADMIN))
        assert notice["status"] == "ACKNOWLEDGED"

    def test_acknowledge_posts_option_fee_and_cancels_reminders(self, api):
        """PRD §3.5: "posts an `OPTION_FEE` ledger entry when
        `exercise_fee_cents` is positive; and cancels the option's remaining
        `PENDING` reminders."

        Design: Difficulty/transitive_cascade/notice_acknowledge_cascades_option_to_lease_to_ledger
        """
        ws = self._setup_acknowledged_exercise(api, "P8b", exercise_fee_cents=100000)
        get_success_data(api.acknowledge_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["lc_headers"]))
        ledger, _ = validate_paginated(api.list_ledger(ws["pid"], ws["lid"], ADMIN))
        fees = [e for e in ledger
                if e["entry_kind"] == "OPTION_FEE"
                and e.get("source_option_id") == ws["oid"]]
        assert len(fees) == 1
        assert fees[0]["amount_cents"] == 100000
        reminders, _ = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], ws["oid"], ADMIN))
        for r in reminders:
            assert r["status"] == "CANCELED", (
                "Exercise cancels every remaining PENDING reminder on the option"
            )


class TestImmediateConsistency:
    def test_exercise_effects_visible_in_same_request_chain(self, api):
        """PRD §3.5: "Completion stamps `exercised_at`; fixes
        `determined_rent_cents_per_rsf_year`, with a `FIXED` option copying its
        `fixed_rent_cents_per_rsf_year` and a `FAIR_MARKET` option copying the
        `FINAL` assessment's `determined_rent_cents`; posts an `OPTION_FEE`
        ledger entry when `exercise_fee_cents` is positive; and cancels the
        option's remaining `PENDING` reminders."

        Design: Corner/consistency_model/exercise_effects_visible_in_same_request_chain
        """
        ws = setup_notice_delivered(
            name="CM1", region="WEST", with_lc=True,
            option_overrides={
                "option_type": "TERMINATION",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2027-06-30T00:00:00Z",
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4000,
                "exercise_fee_cents": 75000,
            },
            clock="2026-09-01T00:00:00Z",
            premises_label="CM1", rentable_square_feet=5000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2028-12-31T00:00:00Z",
            holdover_tier1_pct=150, holdover_tier2_pct=200,
        )
        get_success_data(api.acknowledge_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["lc_headers"]))
        # Immediate consistency: subsequent GETs reflect the exercise.
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "EXERCISED"
        assert opt["determined_rent_cents_per_rsf_year"] == 4000, (
            "FIXED option copies its fixed_rent_cents_per_rsf_year at exercise"
        )
        ledger, _ = validate_paginated(api.list_ledger(ws["pid"], ws["lid"], ADMIN))
        fees = [e for e in ledger
                if e["entry_kind"] == "OPTION_FEE"
                and e.get("source_option_id") == ws["oid"]]
        assert len(fees) == 1
        assert fees[0]["amount_cents"] == 75000
        assert fees[0]["effective_date"].startswith("2026-09-01")
        reminders, _ = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], ws["oid"], ADMIN))
        for r in reminders:
            assert r["status"] == "CANCELED"
