"""Amendment negotiation loop, one-open-negotiation exclusivity, SoD on
execute, holdover-settlement gating, and amendment/lease version bumps."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_contact,
    create_amendment,
    create_lease_payload,
    create_option,
    create_option_payload,
    execute_amendment,
    get_success_data,
    make_am_headers,
    make_lc_headers,
    propose_amendment,
    setup_active_lease,
    setup_lease_in_holdover,
    setup_option_on_active_lease,
    setup_portfolio_with_contacts,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCyclicNegotiation:
    def test_amendment_counter_then_repropose_returns_to_proposed(self, api):
        """PRD §3.7: "`LandlordCounsel` counters a `PROPOSED` amendment, moving
        it `PROPOSED` → `COUNTERED` with a revised
        `new_base_rent_cents_per_rsf_year`. The `AssetManager` re-proposes,
        moving it `COUNTERED` → `PROPOSED` and optionally revising
        `new_base_rent_cents_per_rsf_year` or `new_expiration_date`."

        Design: Difficulty/non_linear_state_machine/amendment_cyclic_negotiation_loop
        """
        ws = setup_active_lease(name="P5", region="WEST", with_lc=True,
                                rentable_square_feet=9000,
                                base_rent_cents_per_rsf_year=5000)
        amendment = create_amendment(ws, kind="RENEWAL_TERM",
                                     new_expiration_date="2032-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=5500)
        propose_amendment(ws, amendment["id"])
        # Landlord counters at 5800.
        countered = validate_success(api.counter_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"new_base_rent_cents_per_rsf_year": 5800}, ws["lc_headers"]))
        assert countered["status"] == "COUNTERED"
        assert countered["new_base_rent_cents_per_rsf_year"] == 5800
        # Tenant re-proposes at 5650 (cyclic loop returns to PROPOSED).
        reprop = validate_success(api.repropose_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"new_base_rent_cents_per_rsf_year": 5650}, ws["am_headers"]))
        assert reprop["status"] == "PROPOSED", "Repropose closes the cyclic loop"
        assert reprop["new_base_rent_cents_per_rsf_year"] == 5650, (
            "The reproposed value survives the loop"
        )

    def test_amendment_loop_ends_in_agreed(self, api):
        """PRD §3.7: "Agreement is `LandlordCounsel`'s act from either
        `PROPOSED` or `COUNTERED`, moving the amendment to `AGREED`."

        Design: Difficulty/non_linear_state_machine/amendment_cyclic_negotiation_loop
        """
        ws = setup_active_lease(name="P5b", region="WEST", with_lc=True,
                                rentable_square_feet=9000,
                                base_rent_cents_per_rsf_year=5000)
        amendment = create_amendment(ws, kind="RENEWAL_TERM",
                                     new_expiration_date="2032-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=5500)
        propose_amendment(ws, amendment["id"])
        # Cycle: PROPOSED → COUNTERED → PROPOSED → AGREED.
        get_success_data(api.counter_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"new_base_rent_cents_per_rsf_year": 5800}, ws["lc_headers"]))
        get_success_data(api.repropose_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"new_base_rent_cents_per_rsf_year": 5650}, ws["am_headers"]))
        agreed = validate_success(api.agree_amendment(
            ws["pid"], ws["lid"], amendment["id"], ws["lc_headers"]))
        assert agreed["status"] == "AGREED"
        assert agreed["new_base_rent_cents_per_rsf_year"] == 5650


class TestOneOpenNegotiation:
    def test_single_open_negotiation_per_lease_capacity(self, api):
        """PRD §3.7: "only one negotiation may be open per lease, so a sibling
        amendment sitting in `PROPOSED`, `COUNTERED`, or `AGREED` forces
        `ERR_NEGOTIATION_ALREADY_OPEN`"

        Design: Difficulty/resource_temporal_overlap/single_open_negotiation_per_lease_aggregate_capacity
        """
        ws = setup_active_lease(name="P16", region="EAST", with_lc=True)
        a1 = create_amendment(ws, kind="RENEWAL_TERM",
                              new_expiration_date="2032-12-31T00:00:00Z",
                              new_base_rent_cents_per_rsf_year=5500)
        propose_amendment(ws, a1["id"])
        a2 = create_amendment(ws, kind="EXPANSION_TERM",
                              new_expiration_date="2033-12-31T00:00:00Z",
                              new_base_rent_cents_per_rsf_year=5800)
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        resp = api.propose_amendment(
            ws["pid"], ws["lid"], a2["id"],
            {"expected_lease_version": lease["version"]}, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ALREADY_OPEN)
        a2_after = validate_success(api.get_amendment(
            ws["pid"], ws["lid"], a2["id"], ws["am_headers"]))
        assert a2_after["status"] == "DRAFT", "Rejected propose must not move the draft"
        a1_after = validate_success(api.get_amendment(
            ws["pid"], ws["lid"], a1["id"], ws["am_headers"]))
        assert a1_after["status"] == "PROPOSED", "The open negotiation is undisturbed"

    def test_negotiation_exclusivity_releases_after_abandon(self, api):
        """PRD §3.7: "An amendment not yet executed — from `DRAFT`, `PROPOSED`,
        `COUNTERED`, or `AGREED` — may be abandoned by the `AssetManager`,
        moving it to `ABANDONED`"

        Design: Difficulty/resource_temporal_overlap/single_open_negotiation_per_lease_aggregate_capacity
        """
        ws = setup_active_lease(name="P16b", region="EAST", with_lc=True)
        a1 = create_amendment(ws, kind="RENEWAL_TERM")
        propose_amendment(ws, a1["id"])
        # Abandon A1; then a sibling may open.
        get_success_data(api.abandon_amendment(
            ws["pid"], ws["lid"], a1["id"], ws["am_headers"]))
        a2 = create_amendment(ws, kind="RENEWAL_TERM",
                              new_expiration_date="2033-12-31T00:00:00Z")
        proposed = propose_amendment(ws, a2["id"])
        assert proposed["status"] == "PROPOSED", (
            "After A1 abandons, the exclusivity slot is released"
        )
        a1_after = validate_success(api.get_amendment(
            ws["pid"], ws["lid"], a1["id"], ws["am_headers"]))
        assert a1_after["status"] == "ABANDONED"


class TestFkScope:
    def test_fk_scope_violation_superseding_amendment_from_other_lease(self, api):
        """PRD §3.7: "`supersedes_amendment_id` names the prior amendment on
        the same lease that this one replaces ... a value pointing at an
        amendment of a different lease is rejected with
        `ERR_FK_SCOPE_VIOLATION`."

        Design: Corner/validations/fk_scope_violation_superseding_amendment_from_other_lease
        """
        ws = setup_portfolio_with_contacts(name="V4", region="EAST")
        lease1 = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="V4-1", rentable_square_feet=5000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            ws["am_headers"]))
        lease2 = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="V4-2", rentable_square_feet=6000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2028-12-31T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            ws["am_headers"]))
        a1 = get_success_data(api.create_amendment(
            ws["pid"], lease1["id"],
            {"kind": "RENEWAL_TERM",
             "new_expiration_date": "2032-12-31T00:00:00Z",
             "new_base_rent_cents_per_rsf_year": 5500},
            ws["am_headers"]))
        # A2 on lease2 attempts to supersede an amendment of lease1 — out of scope.
        resp = api.create_amendment(
            ws["pid"], lease2["id"],
            {"supersedes_amendment_id": a1["id"],
             "kind": "RENEWAL_TERM",
             "new_expiration_date": "2033-12-31T00:00:00Z",
             "new_base_rent_cents_per_rsf_year": 5600},
            ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_FK_SCOPE_VIOLATION)


class TestSodOnExecute:
    def test_sod_beats_occ_stale_version_on_amendment_execute(self, api):
        """PRD §3.7: "Its checks run in order: state admissibility; segregation
        of duties — the executor's `X-User-ID` must differ from the agreeing
        counsel's, else `ERR_SOD_VIOLATION`; the stale-version check; ..."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_occ_stale_version_on_amendment_execute
        """
        ws = setup_portfolio_with_contacts(name="P10", region="WEST")
        # Two contacts: AM2 (the proposer / eventual executor-attempt is by DUAL)
        # and DUAL (agreer as LandlordCounsel).
        dual = ws["am"]  # reuse as dual-hat: proposer AM2, agreer DUAL
        am2 = add_contact(ws["pid"], "AM Two Ten", "am2-10@x.com", "ASSET_MANAGER")
        am2_headers = make_am_headers(am2["id"])
        dual_am_headers = make_am_headers(dual["id"])
        dual_lc_headers = make_lc_headers(dual["id"])

        lease = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="OF-10", rentable_square_feet=5000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            am2_headers))
        lease = get_success_data(api.activate_lease(
            ws["pid"], lease["id"], {}, am2_headers))
        ws["lease"] = lease
        ws["lid"] = lease["id"]
        ws["am_headers"] = am2_headers

        amendment = create_amendment(ws, kind="RENEWAL_TERM",
                                     new_expiration_date="2032-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=5500)
        # AM2 proposes; DUAL (as LandlordCounsel) agrees.
        propose_amendment(ws, amendment["id"])
        get_success_data(api.agree_amendment(
            ws["pid"], ws["lid"], amendment["id"], dual_lc_headers))

        # Capture a stale lease version by bumping the lease (create + withdraw
        # a dummy option).
        lease_now = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], am2_headers))
        stale_version = lease_now["version"]
        dummy_opt = create_option(
            ws["pid"], ws["lid"], am2_headers,
            option_type="ROFR",
            notice_window_open_date="2026-09-01T00:00:00Z",
            notice_window_close_date="2026-12-01T00:00:00Z",
            target_commencement_date="2027-06-01T00:00:00Z",
            rate_determination="FIXED",
            fixed_rent_cents_per_rsf_year=4000)
        lease_now2 = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], am2_headers))
        get_success_data(api.withdraw_option(
            ws["pid"], ws["lid"], dummy_opt["id"],
            {"expected_lease_version": lease_now2["version"]}, am2_headers))

        # DUAL (the agreer) attempts to execute with a stale version. Both SoD
        # and OCC fail; SoD must surface.
        resp = api.execute_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"expected_lease_version": stale_version},
            dual_am_headers)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        # The amendment remains AGREED (no mutation).
        a_after = validate_success(api.get_amendment(
            ws["pid"], ws["lid"], amendment["id"], am2_headers))
        assert a_after["status"] == "AGREED"

    def test_sod_alone_on_execute_with_fresh_version(self, api):
        """PRD §3.7: "segregation of duties — the executor's `X-User-ID` must
        differ from the agreeing counsel's, else `ERR_SOD_VIOLATION`"

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_occ_stale_version_on_amendment_execute
        """
        ws = setup_portfolio_with_contacts(name="P10b", region="WEST")
        dual = ws["am"]
        am2 = add_contact(ws["pid"], "AM P10b", "am2-p10b@x.com", "ASSET_MANAGER")
        am2_headers = make_am_headers(am2["id"])
        dual_am_headers = make_am_headers(dual["id"])
        dual_lc_headers = make_lc_headers(dual["id"])

        lease = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="OF-10b", rentable_square_feet=5000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150, holdover_tier2_pct=200),
            am2_headers))
        lease = get_success_data(api.activate_lease(
            ws["pid"], lease["id"], {}, am2_headers))
        ws["lease"] = lease
        ws["lid"] = lease["id"]
        ws["am_headers"] = am2_headers

        amendment = create_amendment(ws, kind="RENEWAL_TERM",
                                     new_expiration_date="2032-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=5500)
        propose_amendment(ws, amendment["id"])
        get_success_data(api.agree_amendment(
            ws["pid"], ws["lid"], amendment["id"], dual_lc_headers))
        # DUAL (the agreer) attempts to execute with the CURRENT (fresh) version.
        # Only SoD fails — confirming the SoD gate fires on its own.
        lease_now = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], am2_headers))
        resp = api.execute_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"expected_lease_version": lease_now["version"]},
            dual_am_headers)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)


class TestHoldoverSettlementGate:
    def test_holdover_settlement_rejected_when_not_in_holdover(self, api):
        """PRD §3.7: "Executing a `HOLDOVER_SETTLEMENT` is valid only while the
        lease is actually in `HOLDOVER` — otherwise `ERR_NOT_IN_HOLDOVER`"

        Design: Difficulty/cross_entity_state_dependency/holdover_settlement_gated_by_lease_holdover_state
        """
        ws = setup_active_lease(name="P14", region="WEST", with_lc=True)
        amendment = create_amendment(ws, kind="HOLDOVER_SETTLEMENT",
                                     new_expiration_date="2028-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=4500)
        propose_amendment(ws, amendment["id"])
        agree_amendment_to = get_success_data(api.agree_amendment(
            ws["pid"], ws["lid"], amendment["id"], ws["lc_headers"]))
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        resp = api.execute_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"expected_lease_version": lease["version"]}, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_IN_HOLDOVER)

    def test_holdover_settlement_gate_leaves_lease_and_amendment_untouched(self, api):
        """PRD §3.7: "Executing a `HOLDOVER_SETTLEMENT` is valid only while the
        lease is actually in `HOLDOVER` — otherwise `ERR_NOT_IN_HOLDOVER`"

        Design: Difficulty/cross_entity_state_dependency/holdover_settlement_gated_by_lease_holdover_state
        """
        ws = setup_active_lease(name="P14b", region="WEST", with_lc=True)
        amendment = create_amendment(ws, kind="HOLDOVER_SETTLEMENT",
                                     new_expiration_date="2028-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=4500)
        propose_amendment(ws, amendment["id"])
        get_success_data(api.agree_amendment(
            ws["pid"], ws["lid"], amendment["id"], ws["lc_headers"]))
        lease_before = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], ws["am_headers"]))
        resp = api.execute_amendment(
            ws["pid"], ws["lid"], amendment["id"],
            {"expected_lease_version": lease_before["version"]}, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_IN_HOLDOVER)
        lease_after = validate_success(api.get_lease(
            ws["pid"], ws["lid"], ws["am_headers"]))
        assert lease_after["status"] == "ACTIVE", "Lease stays ACTIVE (not HOLDOVER)"
        a_after = validate_success(api.get_amendment(
            ws["pid"], ws["lid"], amendment["id"], ws["am_headers"]))
        assert a_after["status"] == "AGREED", "Rejected execute leaves the amendment AGREED"
