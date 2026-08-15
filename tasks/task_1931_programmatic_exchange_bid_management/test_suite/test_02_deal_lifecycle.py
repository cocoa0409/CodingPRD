"""Deal lifecycle: review gate, renegotiation cycle, expiry, PG commitments."""
from test_helpers import (
    ApiErrorId,
    assert_deal,
    create_deal_for,
    create_deal_payload,
    create_package_for,
    create_publisher,
    fill_auction,
    get_deal,
    make_publisher_manager_headers,
    set_clock,
    setup_active_deal,
    submit_and_approve_deal,
    submit_deal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]


class TestRenegotiationCycle:
    def test_renegotiate_clears_pinned_floor_and_increments_count(self, api):
        """PRD §3.3: "Renegotiation sends an `ACTIVE` deal back to
        `RENEGOTIATING`, increments `renegotiation_count` by one, and clears
        `approved_floor_cpm_micros` to null until the next approval"
        PRD §3.3: "pins `approved_floor_cpm_micros` to the greater of the
        package's `effective_floor_cpm_micros` at that moment and the deal's own
        `floor_cpm_micros`"

        Design: Difficulty/non_linear_state_machine/deal_renegotiation_cycle_repins_approved_floor
        """
        sc = setup_active_deal(package_floor=2000000, deal_floor=1000000)
        deal = sc["deal"]
        assert deal["approved_floor_cpm_micros"] == 2000000, (
            "Approval pins max(package effective 2,000,000, deal 1,000,000)")
        assert deal["renegotiation_count"] == 0

        reneg = validate_success(
            api.renegotiate_deal(deal["id"], sc["manager_headers"]))
        assert reneg["status"] == "RENEGOTIATING"
        assert reneg["renegotiation_count"] == 1
        assert reneg["approved_floor_cpm_micros"] is None, (
            "Renegotiation clears the pinned floor until the next approval")

        # RENEGOTIATING is editable: a version-guarded PUT succeeds.
        edited = validate_success(api.update_deal(
            deal["id"],
            {"expected_deal_version": reneg["version"],
             "floor_cpm_micros": 2500000},
            sc["manager_headers"]))
        assert edited["floor_cpm_micros"] == 2500000

    def test_reapproval_after_renegotiation_repins_floor(self, api):
        """PRD §3.3: "the cycle `RENEGOTIATING` → `PENDING_REVIEW` → `ACTIVE`
        then replays the same gates."
        PRD §3.3: "pins `approved_floor_cpm_micros` to the greater of the
        package's `effective_floor_cpm_micros` at that moment and the deal's own
        `floor_cpm_micros`"

        Design: Difficulty/non_linear_state_machine/deal_renegotiation_cycle_repins_approved_floor
        """
        sc = setup_active_deal(package_floor=2000000, deal_floor=1000000)
        deal = sc["deal"]
        reneg = validate_success(
            api.renegotiate_deal(deal["id"], sc["manager_headers"]))
        validate_success(api.update_deal(
            deal["id"],
            {"expected_deal_version": reneg["version"],
             "floor_cpm_micros": 2500000},
            sc["manager_headers"]))
        submit_deal(deal["id"], sc["pub"]["id"])
        approved = validate_success(api.approve_deal(deal["id"], ADMIN))
        assert approved["status"] == "ACTIVE"
        assert approved["approved_floor_cpm_micros"] == 2500000, (
            "Re-approval re-pins max(package effective 2,000,000, edited "
            "2,500,000)")


class TestSubmitGate:
    def test_deal_submit_from_active_is_invalid_transition(self, api):
        """PRD §3.3: "Submission by the owning manager moves a deal from `DRAFT`
        — or, in the renegotiation loop, from `RENEGOTIATING` — to
        `PENDING_REVIEW`"
        PRD §2.8: "any other state-precondition failure surfaces as
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/deal_submit_from_active_is_invalid_transition
        """
        sc = setup_active_deal()
        deal = sc["deal"]
        assert deal["status"] == "ACTIVE"
        resp = api.submit_deal(deal["id"], sc["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_deal(deal["id"])
        assert after["status"] == "ACTIVE", "A rejected transition changes nothing"

    def test_deal_submit_gated_by_package_state(self, api):
        """PRD §3.3: "Submission by the owning manager moves a deal from `DRAFT`
        — or, in the renegotiation loop, from `RENEGOTIATING` — to
        `PENDING_REVIEW`, and is permitted only while the package, the publisher,
        and the demand partner are all `ACTIVE`; a suspended publisher surfaces
        `ERR_PUBLISHER_SUSPENDED`, a non-active package
        `ERR_PACKAGE_NOT_ACTIVE`, and a non-active partner
        `ERR_PARTNER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/deal_submit_gated_by_package_state
        """
        pub = create_publisher()
        sc = setup_active_deal()
        # Build a DRAFT deal on a package we then pause.
        pkg = create_package_for(pub["id"])
        deal = create_deal_for(pub["id"], pkg["id"], sc["partner"]["id"])
        validate_success(api.pause_package(pkg["id"],
                                           make_publisher_manager_headers(pub["id"])))
        resp = api.submit_deal(deal["id"], make_publisher_manager_headers(pub["id"]))
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ACTIVE)
        after = get_deal(deal["id"])
        assert after["status"] == "DRAFT", "Deal stays DRAFT when its package is PAUSED"

    def test_deal_submit_recovers_after_package_resume(self, api):
        """PRD §3.3: "is permitted only while the package, the publisher, and
        the demand partner are all `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/deal_submit_gated_by_package_state
        """
        pub = create_publisher()
        sc = setup_active_deal()
        pkg = create_package_for(pub["id"])
        deal = create_deal_for(pub["id"], pkg["id"], sc["partner"]["id"])
        mgr = make_publisher_manager_headers(pub["id"])
        validate_success(api.pause_package(pkg["id"], mgr))
        validate_error(api.submit_deal(deal["id"], mgr),
                       ApiErrorId.ERR_PACKAGE_NOT_ACTIVE)
        validate_success(api.resume_package(pkg["id"], mgr))
        submitted = validate_success(api.submit_deal(deal["id"], mgr))
        assert submitted["status"] == "PENDING_REVIEW", (
            "Once the package is ACTIVE again the same submit succeeds")


class TestDealExpiry:
    def test_deal_expiry_is_terminal_via_clock_sweep(self, api):
        """PRD §2.4: "Independently of both, every deal still `ACTIVE` whose
        `end_at` is at or before the new time transitions to `EXPIRED`."
        PRD §3.3: "`EXPIRED` is terminal: the deal's commercial terms become
        immutable and it never leaves that state."

        Design: Corner/state_machines/deal_expiry_is_terminal_via_clock_sweep
        """
        sc = setup_active_deal(end_at="2026-08-10T00:00:00Z")
        deal = sc["deal"]
        set_clock("2026-08-10T00:00:00Z")
        expired = get_deal(deal["id"])
        assert expired["status"] == "EXPIRED", (
            "end_at is exclusive: the clock reaching end_at expires the deal")
        resp = api.pause_deal(deal["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_deal(deal["id"])["status"] == "EXPIRED"

    def test_paused_deal_resume_after_window_closed(self, api):
        """PRD §3.3: "a resume attempted when the clock is outside the window
        from `start_at` to `end_at` is rejected with `ERR_DEAL_WINDOW_CLOSED`,
        and the deal must instead be expired."

        Design: Corner/state_machines/paused_deal_resume_after_window_closed
        """
        sc = setup_active_deal(end_at="2026-08-10T00:00:00Z")
        deal = sc["deal"]
        validate_success(api.pause_deal(deal["id"], sc["manager_headers"]))
        set_clock("2026-08-15T00:00:00Z")
        resp = api.resume_deal(deal["id"], sc["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_DEAL_WINDOW_CLOSED)
        after = get_deal(deal["id"])
        assert after["status"] == "PAUSED", (
            "The expiry sweep touches only ACTIVE deals; a PAUSED deal outlives "
            "its flight and stays PAUSED")


class TestProgrammaticGuaranteedTerms:
    def test_pg_commitment_required_iff_programmatic_guaranteed(self, api):
        """PRD §3.3: "`committed_impressions` is required and must be greater
        than zero exactly when `deal_type` is `PROGRAMMATIC_GUARANTEED`, and is
        forbidden on every other deal type; violating either direction is
        rejected with `ERR_PG_COMMITMENT_MISMATCH`."
        PRD §3.3: "its `is_exclusive` flag is computed — true for
        `PMP_EXCLUSIVE` and `PROGRAMMATIC_GUARANTEED` deals, false otherwise."

        Design: Corner/entities/deal_pg_commitment_required_iff_programmatic_guaranteed
        """
        pub = create_publisher()
        sc = setup_active_deal()
        pkg = create_package_for(pub["id"])
        mgr = make_publisher_manager_headers(pub["id"])

        # committed_impressions on PMP_STANDARD is forbidden.
        bad = create_deal_payload(pkg["id"], sc["partner"]["id"],
                                  deal_type="PMP_STANDARD",
                                  committed_impressions=1000)
        validate_error(api.create_deal(bad, mgr),
                       ApiErrorId.ERR_PG_COMMITMENT_MISMATCH)

        # PG with a positive commitment succeeds and computes the derived fields.
        good = create_deal_payload(pkg["id"], sc["partner"]["id"],
                                   deal_type="PROGRAMMATIC_GUARANTEED",
                                   committed_impressions=5000)
        pg = validate_success(api.create_deal(good, mgr), 201)
        assert_deal(pg)
        assert pg["committed_impressions"] == 5000
        assert pg["remaining_committed_impressions"] == 5000, (
            "Nothing delivered yet: remaining tracks the full commitment")
        assert pg["is_exclusive"] is True

    def test_pg_commitment_not_lowerable_below_delivered(self, api):
        """PRD §3.3: "The edit re-checks the guaranteed-commitment rule, and
        additionally forbids lowering `committed_impressions` below the
        impressions already delivered, again with
        `ERR_PG_COMMITMENT_MISMATCH`."

        Design: Corner/validations/pg_commitment_not_lowerable_below_delivered
        """
        sc = setup_active_deal(deal_type="PROGRAMMATIC_GUARANTEED",
                               committed_impressions=1000)
        deal = sc["deal"]
        fill_auction(sc["pub"]["id"], impression_count=1000)
        assert get_deal(deal["id"])["delivered_impressions"] == 1000

        reneg = validate_success(
            api.renegotiate_deal(deal["id"], sc["manager_headers"]))
        resp = api.update_deal(
            deal["id"],
            {"expected_deal_version": reneg["version"],
             "committed_impressions": 500},
            sc["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_PG_COMMITMENT_MISMATCH)
        after = get_deal(deal["id"])
        assert after["status"] == "RENEGOTIATING"
        assert after["committed_impressions"] == 1000, (
            "committed 500 < delivered 1000: the edit is rejected wholesale")


class TestDealEditValidationOrder:
    def test_active_deal_edit_with_bad_time_range_reports_state_gate(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline,
        and the request fails at the first check that does not pass — later
        checks never mask earlier ones."
        PRD §2.8: "7. Deal editability: commercial edits to a deal are allowed
        only while it is in `DRAFT` or `RENEGOTIATING`, and its `auction_type`
        and `deal_type` are immutable once first approved, else
        `ERR_DEAL_NOT_EDITABLE`."

        Design: Difficulty/priority_pair_validation_conflict/deal_edit_state_gate_beats_time_range
        """
        sc = setup_active_deal()
        deal = sc["deal"]
        resp = api.update_deal(
            deal["id"],
            {"expected_deal_version": deal["version"],
             "start_at": "2026-12-31T00:00:00Z",
             "end_at": "2026-08-01T00:00:00Z"},
            sc["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_DEAL_NOT_EDITABLE)

    def test_rejected_edit_leaves_deal_unchanged(self, api):
        """PRD §2.8: "and a state failure always surfaces before any
        business-temporal or business-fiscal rule on the same endpoint."
        PRD §3.3: "an edit attempting to change them, or any edit outside
        `DRAFT` and `RENEGOTIATING`, is rejected with `ERR_DEAL_NOT_EDITABLE`."

        Design: Difficulty/priority_pair_validation_conflict/deal_edit_state_gate_beats_time_range
        """
        sc = setup_active_deal()
        deal = sc["deal"]
        resp = api.update_deal(
            deal["id"],
            {"expected_deal_version": deal["version"],
             "start_at": "2026-12-31T00:00:00Z",
             "end_at": "2026-08-01T00:00:00Z"},
            sc["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_DEAL_NOT_EDITABLE)
        after = get_deal(deal["id"])
        assert after["status"] == "ACTIVE"
        assert after["start_at"] == deal["start_at"]
        assert after["end_at"] == deal["end_at"]
        assert after["version"] == deal["version"], (
            "A rejected edit does not mutate the deal")
