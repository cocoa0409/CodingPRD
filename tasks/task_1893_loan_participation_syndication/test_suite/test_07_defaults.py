"""Default declaration cascades, lender voting, cure/waive/accelerate
resolution, and accrual re-rating (PRD §3.4, §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    cast_consent_vote,
    cast_default_vote,
    create_modification,
    create_payment,
    create_run,
    declare_default,
    demand_buyback,
    get_borrower,
    get_consent_vote,
    get_default_case,
    get_default_vote,
    get_facility,
    get_modification_request,
    get_participant,
    make_agent_headers,
    make_borrower_headers,
    set_clock,
    settle_buyback,
    setup_funded_facility,
    solicit_modification,
    validate_error,
    validate_success,
)

AGENT = make_agent_headers()

STANDARD_COMMITMENTS = [("P1", 6_000_000), ("P2", 3_000_000), ("P3", 1_000_000)]


class TestFacilityDefaultCycle:
    def test_facility_default_cure_cycle(self):
        """PRD §3.7: "Hop 1 moves the facility `ACTIVE` → `IN_DEFAULT`."
        PRD §3.7: "Curing moves the case `DECLARED` → `CURED` with no vote
        threshold: the addon stops accruing from the cure date, the facility
        returns `IN_DEFAULT` → `ACTIVE` — or goes straight to `CLOSED` if
        outstanding principal and accrued interest are both zero and at least one
        payment has been remitted — and the borrower is restored to `ACTIVE`
        provided no other `DECLARED` case remains on any of its facilities."

        Design: Difficulty/non_linear_state_machine/facility_default_cure_cycle
        """
        setup = setup_funded_facility(
            [("P1", 2_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 2_000_000},
        )
        facility = setup["facility"]
        borrower = setup["borrower"]

        dc1 = declare_default(facility["id"], "COVENANT_DEFAULT")
        assert get_facility(facility["id"])["status"] == "IN_DEFAULT"
        assert get_borrower(borrower["id"])["status"] == "DELINQUENT"

        cured = validate_success(api_client.cure_default_case(dc1["id"], AGENT))
        assert cured["status"] == "CURED"
        assert get_facility(facility["id"])["status"] == "ACTIVE"
        assert get_borrower(borrower["id"])["status"] == "ACTIVE"

        # The machine is cyclic: a second declaration repeats the revolution.
        dc2 = declare_default(facility["id"], "PAYMENT_DEFAULT")
        assert get_default_case(dc2["id"])["status"] == "DECLARED"
        assert get_facility(facility["id"])["status"] == "IN_DEFAULT"
        assert get_borrower(borrower["id"])["status"] == "DELINQUENT"
        assert get_default_case(dc1["id"])["status"] == "CURED"

    def test_insolvency_default_marks_borrower_insolvent(self):
        """PRD §3.7: "Hop 3 reconciles the facility's `accrued_interest_cents` as
        the sum over draws and marks the borrower: `ACTIVE` → `DELINQUENT` for
        any non-insolvency type, or `ACTIVE` → `INSOLVENT` when the type is
        `INSOLVENCY`."
        PRD §3.7: "A borrower leaves `DELINQUENT` or `INSOLVENT` for `ACTIVE`
        exactly when the last `DECLARED` case across all of its facilities has
        been cured or waived".

        Design: Difficulty/non_linear_state_machine/facility_default_cure_cycle
        """
        setup = setup_funded_facility(
            [("P1", 2_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 2_000_000},
        )
        facility = setup["facility"]
        borrower = setup["borrower"]

        dc = declare_default(facility["id"], "INSOLVENCY")
        assert get_facility(facility["id"])["status"] == "IN_DEFAULT"
        assert get_borrower(borrower["id"])["status"] == "INSOLVENT"

        validate_success(api_client.cure_default_case(dc["id"], AGENT))
        assert get_borrower(borrower["id"])["status"] == "ACTIVE"
        assert get_facility(facility["id"])["status"] == "ACTIVE"


class TestDefaultDeclarationCascade:
    def test_default_declaration_cascade_reprices_accrual(self):
        """PRD §3.7: "Hop 2 withdraws every `SOLICITING` modification request on
        the facility into `WITHDRAWN` and re-rates every settled draw's accrual,
        adding `default_interest_addon_bps` from the declared date forward
        (§3.4)."
        PRD §3.4: "At declaration, the stretch from `accrual_as_of_date` to the
        declared date stays at base rate and the stretch from the declared date
        onward carries the addon."

        Design: Difficulty/transitive_cascade/default_declaration_cascade_reprices_accrual
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 4_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]
        p1 = setup["participants"][0]

        mod = create_modification(
            facility["id"], borrower["id"], "COVENANT_WAIVER",
            {"waiver_text": "Waive leverage covenant Q3"},
        )
        solicit_modification(mod["id"])
        v1 = cast_consent_vote(mod["id"], p1["id"], "APPROVE")

        set_clock("2026-08-11T00:00:00Z")
        declare_default(facility["id"], "PAYMENT_DEFAULT")
        assert get_facility(facility["id"])["status"] == "IN_DEFAULT"
        assert get_borrower(borrower["id"])["status"] == "DELINQUENT"
        assert get_modification_request(mod["id"])["status"] == "WITHDRAWN"
        assert get_consent_vote(v1["id"])["status"] == "VOIDED"

        # REGULAR payments are still accepted while IN_DEFAULT; the run accrues
        # 10 base days (13,333) + 20 days at base+800bps (44,444) on 4,000,000.
        pay = create_payment(facility["id"], borrower["id"], 100_000, "2026-08-31")
        run = create_run(pay["id"])
        assert run["interest_pool_cents"] == 57_777
        assert run["servicing_fee_cents"] == 833
        assert get_facility(facility["id"])["accrued_interest_cents"] == 57_777

    def test_prepayment_blocked_while_in_default(self):
        """PRD §3.5: "Payments are accepted only while the facility is `ACTIVE`,
        `IN_DEFAULT`, or `ACCELERATED`; in any other status the recording is
        rejected with `ERR_INVALID_STATE_TRANSITION`, and a `PREPAYMENT`
        attempted while the facility is `IN_DEFAULT` or `ACCELERATED` is rejected
        with `ERR_FACILITY_IN_DEFAULT`."

        Design: Difficulty/transitive_cascade/default_declaration_cascade_reprices_accrual
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 4_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]
        declare_default(facility["id"], "PAYMENT_DEFAULT")

        resp = api_client.create_payment(
            {
                "facility_id": facility["id"],
                "payment_type": "PREPAYMENT",
                "amount_cents": 100_000,
                "value_date": "2026-08-31",
            },
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_IN_DEFAULT, expected_status=409)

        # REGULAR payments remain accepted in the same posture.
        pay = create_payment(facility["id"], borrower["id"], 100_000, "2026-08-31")
        assert pay["status"] == "RECEIVED"


class TestDefaultVotingAndResolution:
    def test_default_declare_with_active_case_rejected(self):
        """PRD §3.7: "Declaration requires the facility to be `ACTIVE` —
        otherwise `ERR_INVALID_STATE_TRANSITION` — and at most one `DECLARED`
        case may exist per facility at a time, a second attempt failing
        `ERR_DEFAULT_ALREADY_ACTIVE`."
        PRD §2.9: target-state legality (priority 6, ERR_INVALID_STATE_TRANSITION)
        is evaluated before the single-active-default rule (priority 9). A live
        DECLARED case holds its facility IN_DEFAULT (§3.7 hop 1), so the second
        declaration fails the facility-ACTIVE check first.

        Design: Corner/state_machines/default_declare_with_active_case_rejected
        """
        setup = setup_funded_facility(
            [("DP", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        facility = setup["facility"]
        declare_default(facility["id"], "PAYMENT_DEFAULT")
        resp = api_client.create_default_case(
            {"facility_id": facility["id"], "default_type": "COVENANT_DEFAULT"}, AGENT
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    def test_accelerate_below_threshold_rejected(self):
        """PRD §3.7: "Acceleration moves `DECLARED` → `ACCELERATED` and requires
        `accelerate_share_bps` to meet or exceed the facility's
        `supermajority_threshold_bps`, failing
        `ERR_ACCELERATION_THRESHOLD_NOT_MET`".

        Design: Corner/state_machines/accelerate_below_threshold_rejected
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 1_000_000)
        facility = setup["facility"]
        p2 = setup["participants"][1]
        dc = declare_default(facility["id"], "PAYMENT_DEFAULT")
        cast_default_vote(dc["id"], p2["id"], "ACCELERATE")  # 3000 bps < 6667

        resp = api_client.accelerate_default_case(dc["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_ACCELERATION_THRESHOLD_NOT_MET, expected_status=409)
        assert get_default_case(dc["id"])["status"] == "DECLARED"

    def test_waive_below_threshold_rejected(self):
        """PRD §3.7: "Waiving moves `DECLARED` → `WAIVED` and requires the
        `waive_share_bps` to meet or exceed the facility's
        `majority_threshold_bps`, failing `ERR_WAIVER_THRESHOLD_NOT_MET`".

        Design: Corner/state_machines/waive_below_threshold_rejected
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 1_000_000)
        facility = setup["facility"]
        p3 = setup["participants"][2]
        dc = declare_default(facility["id"], "COVENANT_DEFAULT")
        cast_default_vote(dc["id"], p3["id"], "WAIVE")  # 1000 bps < 5001

        resp = api_client.waive_default_case(dc["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_WAIVER_THRESHOLD_NOT_MET, expected_status=409)
        assert get_default_case(dc["id"])["status"] == "DECLARED"

    def test_default_waive_retroactive_addon_removal(self):
        """PRD §3.4: "At waiver, the addon is removed retroactively: the draw's
        entire accrual history is recomputed at base rate, so post-waiver accrued
        interest equals the value it would have had if the default had never
        happened."

        Design: Corner/calculations/default_waive_retroactive_addon_removal
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 4_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]
        p1 = setup["participants"][0]

        set_clock("2026-08-11T00:00:00Z")
        dc = declare_default(facility["id"], "COVENANT_DEFAULT")
        cast_default_vote(dc["id"], p1["id"], "WAIVE")  # 6000 bps >= 5001
        set_clock("2026-08-21T00:00:00Z")
        waived = validate_success(api_client.waive_default_case(dc["id"], AGENT))
        assert waived["status"] == "WAIVED"
        assert get_facility(facility["id"])["status"] == "ACTIVE"
        assert get_borrower(borrower["id"])["status"] == "ACTIVE"

        pay = create_payment(facility["id"], borrower["id"], 50_000, "2026-08-31")
        run = create_run(pay["id"])
        # Base-rate-only history, floored per segment: 13,333 + 13,333 + 13,333
        # == 39,999 (one cent below the unsegmented 40,000).
        assert run["interest_pool_cents"] == 39_999
        assert run["interest_pool_cents"] < 40_000

    def test_derived_field_reconciliation_on_cure(self):
        """PRD §3.4: "At cure, the addon applies only from declaration to the
        cure date, and base rate resumes thereafter — a two- or three-segment
        history."
        PRD §2.7: "`accrued_interest_cents` is unpaid accrued interest, equal to
        the sum of `accrued_unpaid_interest_cents` over the facility's settled
        draws, and is materialized at distribution-run creation, at default
        declaration, cure, waiver, and acceleration, and at buyback settlement."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_cure
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 4_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]

        set_clock("2026-08-11T00:00:00Z")
        dc = declare_default(facility["id"], "PAYMENT_DEFAULT")
        set_clock("2026-08-21T00:00:00Z")
        cured = validate_success(api_client.cure_default_case(dc["id"], AGENT))
        assert cured["status"] == "CURED"
        assert get_facility(facility["id"])["status"] == "ACTIVE"
        assert get_borrower(borrower["id"])["status"] == "ACTIVE"

        pay = create_payment(facility["id"], borrower["id"], 60_000, "2026-08-31")
        run = create_run(pay["id"])
        # 10 base days (13,333) + 10 days at 2000 bps (22,222) + 10 base days
        # (13,333) == 48,888 on the 4,000,000 draw.
        assert run["interest_pool_cents"] == 48_888


class TestBuybackVoteRebase:
    def test_buyback_settle_voids_votes_rebases_tally(self):
        """PRD §3.9: "Hop 3 recomputes `share_bps` for the remaining participants
        and voids the exited participant's live votes on soliciting requests and
        declared cases, recomputing those tallies."
        PRD §3.7: "The default tally uses the case's `voting_base_cents` minus
        the commitments of participants exited since declaration as its adjusted
        base".

        Design: Difficulty/transitive_cascade/buyback_settle_voids_votes_rebases_tally
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 5_000_000)
        facility = setup["facility"]
        p1, p2, _ = setup["participants"]

        set_clock("2026-08-11T00:00:00Z")
        dc = declare_default(facility["id"], "PAYMENT_DEFAULT")
        dv2 = cast_default_vote(dc["id"], p2["id"], "ACCELERATE")
        assert get_default_case(dc["id"])["accelerate_share_bps"] == 3000

        # P2 exits via buyback: its live default vote is voided and the tally
        # rebases. Price = 1,500,000 outstanding + 12,499 accrued share (accrual
        # re-rated with the addon through 2026-08-20: 16,666 + 25,000 == 41,666).
        demand = demand_buyback(facility["id"], p2["id"], "MISREPRESENTATION")
        acknowledged = validate_success(
            api_client.acknowledge_buyback_demand(demand["id"], AGENT)
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        set_clock("2026-08-20T00:00:00Z")
        settled = validate_success(api_client.settle_buyback_demand(demand["id"], AGENT))
        assert settled["status"] == "SETTLED"
        assert settled["repurchase_price_cents"] == 1_512_499

        assert get_default_vote(dv2["id"])["status"] == "VOIDED"
        rebased = get_default_case(dc["id"])
        assert rebased["accelerate_share_bps"] == 0
        assert get_facility(facility["id"])["committed_cents"] == 7_000_000

        # P1's vote against the adjusted 7,000,000 base: floor(10000*6/7) == 8571.
        cast_default_vote(dc["id"], p1["id"], "ACCELERATE")
        assert get_default_case(dc["id"])["accelerate_share_bps"] == 8571
        accelerated = validate_success(api_client.accelerate_default_case(dc["id"], AGENT))
        assert accelerated["status"] == "ACCELERATED"
        assert get_facility(facility["id"])["status"] == "ACCELERATED"
        assert get_participant(p2["id"])["status"] == "EXITED"
