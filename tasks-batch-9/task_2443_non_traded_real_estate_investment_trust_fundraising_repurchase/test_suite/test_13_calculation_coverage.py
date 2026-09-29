"""Breadth coverage of the PRD's arithmetic: tallies, accruals, caps, rounding,
lot ordering, price selection and coverage boundaries.

Every test builds the whole of its own state: the service restarts against an
empty database before each test and its logical clock reads 2026-08-01T00:00:00Z
(PRD §2.6) until the test moves it.
"""

from test_helpers import (
    BOARD,
    SPONSOR,
    TRANSFER_AGENT,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_total_count,
    declaration_payload,
    nav_record_payload,
    subscription_payload,
)
from test_helpers.fixtures import ReitWorld


# ─── shared setup builders (PRD §3.1–§3.5 chains) ──────────────────────


def _effective_zero_load_offering(
    world: ReitWorld,
    name: str,
    minimum_offering_amount_cents: int,
    firm_name: str,
    crd_number: str,
    max_commission_bps: int = 100,
    **offering_overrides,
) -> dict:
    """An EFFECTIVE offering priced at 1000 cents with one zero-load class I."""
    offering = world.offering(
        name=name,
        minimum_offering_amount_cents=minimum_offering_amount_cents,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        **offering_overrides,
    )
    share_class = world.share_class(
        offering["id"],
        class_code="I",
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(firm_name=firm_name, crd_number=crd_number)
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=max_commission_bps
    )
    world.activate_agreement(agreement["id"])
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "broker_dealer_id": firm["id"],
        "selling_agreement_id": agreement["id"],
    }


def _documented_investor(
    world: ReitWorld, legal_name: str, email: str, documentation_reference: str
) -> dict:
    investor = world.investor(
        legal_name=legal_name,
        email=email,
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(investor["id"], documentation_reference)
    return investor


def _fund_and_break_escrow(
    world: ReitWorld, base: dict, investor_id: str, gross_investment_cents: int
) -> dict:
    subscription = world.subscription(
        base["offering_id"],
        base["share_class_id"],
        investor_id,
        base["selling_agreement_id"],
        gross_investment_cents,
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(base["offering_id"])
    return subscription


def _vote_ready_offering(world: ReitWorld) -> dict:
    """Two equal holders of 150000000 e4, a vote open, one FOR and one ABSTAIN."""
    base = _effective_zero_load_offering(
        world, "Halcyon Income REIT", 30000000, "Halcyon Placement", "CRD-310001"
    )
    investor_a = _documented_investor(
        world, "Ada Kwon", "ada.kwon@example.com", "SUIT-ADA-2026-08"
    )
    investor_b = _documented_investor(
        world, "Bo Ferreira", "bo.ferreira@example.com", "SUIT-BO-2026-08"
    )
    for investor in (investor_a, investor_b):
        subscription = world.subscription(
            base["offering_id"],
            base["share_class_id"],
            investor["id"],
            base["selling_agreement_id"],
            15000000,
        )
        world.escrow_subscription(subscription["id"])
    world.break_escrow(base["offering_id"])

    event = world.liquidity_event(
        base["offering_id"], event_type="LISTING", proposed_effective_date="2026-12-01"
    )
    world.drive_liquidity_event(event["id"], "BOARD_APPROVE", BOARD)
    opened = world.drive_liquidity_event(event["id"], "OPEN_VOTE", SPONSOR)
    base.update(
        {
            "event_id": event["id"],
            "opened": opened,
            "ballot_for": world.cast_vote(event["id"], investor_a["id"], choice="FOR"),
            "ballot_abstain": world.cast_vote(
                event["id"], investor_b["id"], choice="ABSTAIN"
            ),
        }
    )
    return base


def _offering_with_three_declarations(world: ReitWorld) -> dict:
    """One 100000000 e4 class plus a DECLARED, a CANCELLED and a later declaration."""
    base = _effective_zero_load_offering(
        world, "Meridian Core REIT", 10000000, "Meridian Placement", "CRD-310002"
    )
    investor = _documented_investor(
        world, "Cleo Marsh", "cleo.marsh@example.com", "SUIT-CLEO-2026-08"
    )
    _fund_and_break_escrow(world, base, investor["id"], 10000000)

    inside = world.declaration(
        base["offering_id"],
        record_date="2026-08-05",
        payment_date="2026-08-20",
        declared_per_share_cents=3,
        gaap_net_income_cents=30000,
        adjusted_cash_flow_cents=30000,
    )
    cancelled = world.declaration(
        base["offering_id"],
        record_date="2026-08-06",
        payment_date="2026-08-21",
        declared_per_share_cents=5,
        gaap_net_income_cents=50000,
        adjusted_cash_flow_cents=50000,
    )
    cancelled = world.cancel_declaration(cancelled["id"])
    later = world.declaration(
        base["offering_id"],
        record_date="2026-09-10",
        payment_date="2026-09-25",
        declared_per_share_cents=7,
        gaap_net_income_cents=70000,
        adjusted_cash_flow_cents=70000,
    )
    world.set_clock("2026-09-01T00:00:00Z")
    base.update(
        {
            "investor_id": investor["id"],
            "declaration_inside": inside,
            "declaration_cancelled": cancelled,
            "declaration_later": later,
        }
    )
    return base


def _priced_offering_with_open_period(world: ReitWorld) -> dict:
    """A 1000000000 e4 class with a PUBLISHED July valuation and one August tender."""
    base = _effective_zero_load_offering(
        world, "Cascadia Yield REIT", 100000000, "Cascadia Placement", "CRD-310003"
    )
    investor = world.investor(
        legal_name="Dov Ranieri",
        email="dov.ranieri@example.com",
        state_code="TX",
        net_worth_cents=9000000000,
        annual_income_cents=2000000000,
    )
    world.document_suitability(investor["id"], "SUIT-DOV-2026-08")
    _fund_and_break_escrow(world, base, investor["id"], 100000000)

    nav_record = world.published_nav(
        base["share_class_id"], "2026-07-01", "2026-07-31", 100000000
    )
    period = world.repurchase_period(
        base["offering_id"],
        period_month="2026-08",
        opens_at="2026-08-01T00:00:00Z",
        request_cutoff_at="2026-08-26T00:00:00Z",
        settlement_date="2026-08-30",
    )
    request = world.tender(period["id"], base["share_class_id"], 10000000, investor["id"])
    world.set_clock("2026-08-26T00:00:00Z")
    base.update(
        {
            "investor_id": investor["id"],
            "nav_record": nav_record,
            "period_id": period["id"],
            "request_id": request["id"],
        }
    )
    return base


def _two_lot_offering_with_open_period(world: ReitWorld) -> dict:
    """An older 2500000 e4 lot and a newer 1000000000 e4 lot of the same holder."""
    base = _effective_zero_load_offering(
        world,
        "Northgate Total Return REIT",
        250000,
        "Northgate Placement",
        "CRD-310005",
        rescission_window_days=5,
    )
    investor = _documented_investor(
        world, "Faye Okonjo", "faye.okonjo@example.com", "SUIT-FAYE-2026-08"
    )
    subscription_a = _fund_and_break_escrow(world, base, investor["id"], 250000)

    world.set_clock("2026-08-02T00:00:00Z")
    world.published_nav(base["share_class_id"], "2026-07-01", "2026-07-31", 250000)

    world.set_clock("2026-08-05T00:00:00Z")
    subscription_b = world.subscription(
        base["offering_id"],
        base["share_class_id"],
        investor["id"],
        base["selling_agreement_id"],
        100000000,
    )
    world.accept_subscription(subscription_b["id"])

    period = world.repurchase_period(
        base["offering_id"],
        period_month="2026-08",
        opens_at="2026-08-01T00:00:00Z",
        request_cutoff_at="2026-08-26T00:00:00Z",
        settlement_date="2026-08-30",
    )
    request = world.tender(period["id"], base["share_class_id"], 30000000, investor["id"])
    world.set_clock("2026-08-26T00:00:00Z")
    base.update(
        {
            "investor_id": investor["id"],
            "subscription_a_id": subscription_a["id"],
            "subscription_b": subscription_b,
            "period_id": period["id"],
            "request_id": request["id"],
        }
    )
    return base


def _offering_with_published_accrued_valuation(world: ReitWorld) -> dict:
    """A class whose PUBLISHED August valuation splits 1000 pre-accrual from 997."""
    base = _effective_zero_load_offering(
        world, "Solstice Income REIT", 10000000, "Solstice Placement", "CRD-310006"
    )
    investor = _documented_investor(
        world, "Gita Halloran", "gita.halloran@example.com", "SUIT-GITA-2026-08"
    )
    subscription_a = world.subscription(
        base["offering_id"],
        base["share_class_id"],
        investor["id"],
        base["selling_agreement_id"],
        10000000,
    )
    world.escrow_subscription(subscription_a["id"])
    world.break_escrow(base["offering_id"])

    declaration = world.declaration(
        base["offering_id"],
        record_date="2026-08-05",
        payment_date="2026-08-20",
        declared_per_share_cents=3,
        gaap_net_income_cents=30000,
        adjusted_cash_flow_cents=30000,
    )
    world.set_clock("2026-09-01T00:00:00Z")
    nav_record = world.nav_record(
        base["share_class_id"], "2026-08-01", "2026-08-31", 10000000
    )
    world.submit_nav_for_review(nav_record["id"])
    world.confirm_nav(nav_record["id"])
    published = world.publish_nav_record(nav_record["id"])
    base.update(
        {
            "investor_id": investor["id"],
            "subscription_a": subscription_a,
            "declaration": declaration,
            "nav_record": nav_record,
            "published_nav": published,
        }
    )
    return base


def _offering_ready_for_declaration(world: ReitWorld) -> dict:
    """A 100000000 e4 class, so 15 cents per share declares 150000 cents."""
    base = _effective_zero_load_offering(
        world, "Bellwether Core REIT", 10000000, "Bellwether Placement", "CRD-310007"
    )
    investor = _documented_investor(
        world, "Hana Delacroix", "hana.delacroix@example.com", "SUIT-HANA-2026-08"
    )
    _fund_and_break_escrow(world, base, investor["id"], 10000000)
    base["investor_id"] = investor["id"]
    return base


# ─── Vote tally (PRD §3.9) ─────────────────────────────────────────────


class TestVoteTallyAtTheQuorumBoundary:
    def test_for_shares_at_exactly_half_meet_quorum_but_reject_the_event(
        self, api, world
    ):
        """A FOR block of exactly half the record-date shares makes quorum yet rejects.

        PRD §3.9: "`CLOSE_VOTE`, driven by the `SponsorOperator`, tallies `votes_for_e4`, `votes_against_e4` and `votes_abstain_e4` as the sums of `voting_shares_e4` over the ballots choosing `FOR`, `AGAINST` and `ABSTAIN` respectively."
        PRD §3.9: "The shares cast are the three tallies added together, and `quorum_met` is true when the shares cast reach or exceed half of `record_date_shares_e4`, that half being the record-date share count divided by two and floored."
        PRD §3.9: "An abstention therefore helps a vote reach quorum while never helping it pass — an event that draws exactly half its record-date shares in favour and the rest in abstentions meets quorum and is still rejected, because twice half is not strictly greater than the whole."

        Design: Corner/calculations/vote_tally_rejects_with_quorum_when_for_shares_are_exactly_half
        """
        base = _vote_ready_offering(world)
        assert base["opened"]["record_date_shares_e4"] == 300000000
        assert base["ballot_for"]["voting_shares_e4"] == 150000000
        assert base["ballot_abstain"]["voting_shares_e4"] == 150000000

        closed = assert_ok(
            api.drive_liquidity_event(
                base["event_id"], {"action": "CLOSE_VOTE"}, SPONSOR
            )
        )

        assert_fields(
            closed,
            votes_for_e4=150000000,
            votes_against_e4=0,
            votes_abstain_e4=150000000,
            quorum_met=True,
            status="REJECTED",
        )
        assert world.read_liquidity_event(base["event_id"])["status"] == "REJECTED"

    def test_rejected_close_leaves_the_repurchase_plan_active(self, api, world):
        """Only an approving close suspends the plan, so a rejection leaves it ACTIVE.

        PRD §3.9: "When `CLOSE_VOTE` resolves to `APPROVED`, the offering's `repurchase_plan_status` is moved to `SUSPENDED` with `repurchase_plan_suspension_reason` recorded as `LIQUIDITY_EVENT_APPROVED`, which in turn holds the plan's open periods and queued tenders exactly as an ordinary compliance suspension would."
        PRD §2.10: "A change on one axis never implies a change on another unless a rule in §3 says so explicitly."

        Design: Corner/calculations/vote_tally_rejects_with_quorum_when_for_shares_are_exactly_half
        """
        base = _vote_ready_offering(world)

        closed = assert_ok(
            api.drive_liquidity_event(
                base["event_id"], {"action": "CLOSE_VOTE"}, SPONSOR
            )
        )
        assert closed["status"] == "REJECTED"

        offering = world.read_offering(base["offering_id"])
        assert_fields(
            offering,
            repurchase_plan_status="ACTIVE",
            repurchase_plan_suspension_reason=None,
        )


# ─── Valuation accrual scope (PRD §3.6, §3.7) ──────────────────────────


class TestValuationAccrualScope:
    def test_accrual_counts_only_declared_rows_dated_within_the_period(self, api, world):
        """A cancelled declaration and one dated after the period end are both excluded.

        PRD §3.6: "The record snapshots `shares_outstanding_e4_snapshot` from the class's `shares_outstanding_e4` at the instant of creation, and computes `accrued_distribution_payable_cents` as the sum of `total_declared_cents` across every declaration of the class's offering that is currently `DECLARED` and whose `record_date` falls on or before this record's `period_end_date`."
        PRD §3.6: "Otherwise `nav_per_share_pre_accrual_cents` is the pre-accrual net assets multiplied by 10,000, divided by the snapshotted share count and rounded half up to a whole cent, while `nav_per_share_cents` is the post-accrual net assets multiplied by 10,000, divided by the same snapshotted share count and rounded half up."
        PRD §3.7: "A `BoardCommittee` may cancel a declaration that is still `DECLARED`, moving it to the terminal `CANCELLED`, incrementing its `version` and removing it from the `accrued_distribution_payable_cents` of every valuation record prepared thereafter."

        Design: Corner/calculations/nav_accrual_counts_only_declared_declarations_dated_within_the_period
        """
        base = _offering_with_three_declarations(world)
        assert base["declaration_inside"]["total_declared_cents"] == 30000
        assert base["declaration_cancelled"]["total_declared_cents"] == 50000
        assert base["declaration_cancelled"]["status"] == "CANCELLED"
        assert base["declaration_later"]["total_declared_cents"] == 70000

        record = assert_created(
            api.create_nav_record(
                nav_record_payload(
                    base["share_class_id"],
                    world.share_class_version(base["share_class_id"]),
                    period_start_date="2026-08-01",
                    period_end_date="2026-08-31",
                    gross_asset_value_cents=10000000,
                    other_liabilities_cents=0,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            record,
            shares_outstanding_e4_snapshot=100000000,
            accrued_distribution_payable_cents=30000,
            nav_per_share_cents=997,
            status="DRAFT",
        )

    def test_pre_accrual_variant_ignores_declared_but_unpaid_distributions(
        self, api, world
    ):
        """The disclosure variant stays at 1000 while the official variant falls to 997.

        PRD §3.6: "Net assets before the distribution accrual are the gross asset value less the other liabilities; net assets after it are that same figure less the accrued distribution payable."
        PRD §3.6: "The first figure is the disclosure variant — the number published as "NAV before distribution accrual" — and it ignores declared-but-unpaid distributions entirely."

        Design: Corner/calculations/nav_accrual_counts_only_declared_declarations_dated_within_the_period
        """
        base = _offering_with_three_declarations(world)

        record = assert_created(
            api.create_nav_record(
                nav_record_payload(
                    base["share_class_id"],
                    world.share_class_version(base["share_class_id"]),
                    period_start_date="2026-08-01",
                    period_end_date="2026-08-31",
                    gross_asset_value_cents=10000000,
                    other_liabilities_cents=0,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            record,
            nav_per_share_pre_accrual_cents=1000,
            nav_per_share_cents=997,
        )


# ─── Repurchase capacity constants (PRD §3.8) ──────────────────────────


class TestRepurchaseCapacityConstants:
    def test_captured_caps_read_two_hundred_and_five_hundred_basis_points(
        self, api, world
    ):
        """Both cap legs are taken from the same aggregate valuation at processing.

        PRD §3.8: "`monthly_cap_cents` is two percent of it — the aggregate multiplied by 200 basis points, divided by 10,000, floored."
        PRD §3.8: "The quarterly leg is measured against a five percent ceiling: the quarter's usage is the sum of `settled_amount_cents` across the offering's *other* periods that share this period's `quarter_key` and have already reached `PROCESSED`, and `quarterly_remaining_cents` is the greater of zero and the aggregate multiplied by 500 basis points, divided by 10,000, floored, less that usage."
        PRD §3.8: "`capacity_cents` is the lesser of the monthly cap and the quarterly remainder."

        Design: Corner/calculations/repurchase_cap_constants_bind_at_two_hundred_bps_monthly_leg
        """
        base = _priced_offering_with_open_period(world)
        assert base["nav_record"]["nav_per_share_cents"] == 1000
        assert world.read_offering(base["offering_id"])["aggregate_nav_cents"] == 100000000

        period = assert_ok(
            api.process_repurchase_period(base["period_id"], None, TRANSFER_AGENT)
        )

        assert_fields(
            period,
            monthly_cap_cents=2000000,
            quarterly_remaining_cents=5000000,
            capacity_cents=2000000,
            settled_amount_cents=1000000,
            prorated=False,
            status="PROCESSED",
        )

    def test_fully_covered_tender_settles_with_the_early_repurchase_deduction(
        self, api, world
    ):
        """A tender inside capacity is granted in full and bears the 200 bps deduction.

        PRD §3.8: "Each `QUEUED` tender is then valued: `requested_value_cents` is the `shares_requested_e4` multiplied by the transaction price of the tender's class, divided by 10,000 and rounded half up."
        PRD §3.8: "A tender whose approved value equals its requested value becomes `FULFILLED`; one whose approved value is zero becomes `REJECTED`, consuming no lot and paying nothing; anything in between becomes `PARTIALLY_FULFILLED`."
        PRD §3.8: "The lot's holding period is the whole number of days from the calendar date of its `issued_date` to the period's `settlement_date`; where that count is fewer than 365 days the lot bears a deduction of two percent of its own gross proceeds — the lot gross multiplied by 200 basis points, divided by 10,000 and rounded half up — and where it is 365 days or more the lot bears no deduction at all."

        Design: Corner/calculations/repurchase_cap_constants_bind_at_two_hundred_bps_monthly_leg
        """
        base = _priced_offering_with_open_period(world)

        assert_ok(api.process_repurchase_period(base["period_id"], None, TRANSFER_AGENT))

        request = world.read_request(base["request_id"])
        assert_fields(
            request,
            requested_value_cents=1000000,
            approved_value_cents=1000000,
            approved_shares_e4=10000000,
            early_repurchase_deduction_cents=20000,
            net_proceeds_cents=980000,
            status="FULFILLED",
        )


# ─── Half-cent tie and the aggregate (PRD §2.5, §3.6) ──────────────────


class TestValuationHalfCentTie:
    def test_exact_half_cent_per_share_rounds_up(self, api, world):
        """19010000 cents over 200000000 e4 divides to 950.5 and must store 951.

        PRD §2.5: "Rounding **half up** takes a rational value to the nearest integer, resolving an exact tie away from zero."
        PRD §3.6: "Otherwise `nav_per_share_pre_accrual_cents` is the pre-accrual net assets multiplied by 10,000, divided by the snapshotted share count and rounded half up to a whole cent, while `nav_per_share_cents` is the post-accrual net assets multiplied by 10,000, divided by the same snapshotted share count and rounded half up."
        PRD §3.6: "When no prior published record exists, `variance_bps` is zero."

        Design: Corner/calculations/nav_per_share_half_cent_tie_rounds_up_and_reprices_aggregate
        """
        base = _effective_zero_load_offering(
            world, "Ridgeline Equity REIT", 20000000, "Ridgeline Placement", "CRD-310004"
        )
        investor = _documented_investor(
            world, "Esme Bittar", "esme.bittar@example.com", "SUIT-ESME-2026-08"
        )
        _fund_and_break_escrow(world, base, investor["id"], 20000000)

        record = assert_created(
            api.create_nav_record(
                nav_record_payload(
                    base["share_class_id"],
                    world.share_class_version(base["share_class_id"]),
                    period_start_date="2026-07-01",
                    period_end_date="2026-07-31",
                    gross_asset_value_cents=19010000,
                    other_liabilities_cents=0,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            record,
            shares_outstanding_e4_snapshot=200000000,
            nav_per_share_pre_accrual_cents=951,
            nav_per_share_cents=951,
            variance_bps=0,
        )

    def test_publication_reprices_the_aggregate_at_the_rounded_price(self, api, world):
        """The aggregate rebuilds from the 951-cent price, not from raw net assets.

        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share class of the offering, of each class's transaction price multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up — each class's contribution rounded to a whole cent on its own before the contributions are added."
        PRD §3.6: "Publication increments the record's `version`, drives the class's previously `PUBLISHED` record to the terminal `SUPERSEDED` with its own `version` incremented, and recomputes the offering's `aggregate_nav_cents` from the new transaction price."

        Design: Corner/calculations/nav_per_share_half_cent_tie_rounds_up_and_reprices_aggregate
        """
        base = _effective_zero_load_offering(
            world, "Ridgeline Equity REIT", 20000000, "Ridgeline Placement", "CRD-310004"
        )
        investor = _documented_investor(
            world, "Esme Bittar", "esme.bittar@example.com", "SUIT-ESME-2026-08"
        )
        _fund_and_break_escrow(world, base, investor["id"], 20000000)
        assert world.read_offering(base["offering_id"])["aggregate_nav_cents"] == 20000000

        published = world.published_nav(
            base["share_class_id"], "2026-07-01", "2026-07-31", 19010000
        )
        assert published["nav_per_share_cents"] == 951

        offering = world.read_offering(base["offering_id"])
        assert offering["aggregate_nav_cents"] == 19020000, (
            "the aggregate must be round_half_up(951 * 200000000 / 10000), "
            f"got {offering['aggregate_nav_cents']}"
        )


# ─── Oldest-lot-first settlement (PRD §3.8) ────────────────────────────


class TestFifoSettlement:
    def test_settlement_exhausts_the_older_lot_before_touching_the_newer_one(
        self, api, world
    ):
        """The 2026-08-01 lot closes to zero and the balance comes from the 2026-08-05 lot.

        PRD §3.8: "For each tender, the price is the transaction price of the tender's class, and the stockholder's `OPEN` lots in that class are visited in ascending `issued_date` order with ascending `created_at` breaking a tie — oldest first."
        PRD §3.8: "The lot's `remaining_shares_e4` is reduced by the units taken and, if it falls to zero, the lot moves to the terminal `CLOSED` with its `version` incremented and drops out of both `shares_outstanding_e4` and `total_shares_e4`."

        Design: Corner/calculations/fifo_settlement_consumes_the_older_lot_before_the_newer_one
        """
        base = _two_lot_offering_with_open_period(world)
        assert base["subscription_b"]["transaction_price_cents"] == 1000
        assert base["subscription_b"]["shares_issued_e4"] == 1000000000

        assert_ok(api.process_repurchase_period(base["period_id"], None, TRANSFER_AGENT))

        older = assert_total_count(
            api.list_share_lots({"subscription_id": base["subscription_a_id"]}, TRANSFER_AGENT),
            1,
        )[0]
        newer = assert_total_count(
            api.list_share_lots(
                {"subscription_id": base["subscription_b"]["id"]}, TRANSFER_AGENT
            ),
            1,
        )[0]

        assert older["issued_date"].startswith("2026-08-01"), older["issued_date"]
        assert newer["issued_date"].startswith("2026-08-05"), newer["issued_date"]
        assert_fields(
            older,
            original_shares_e4=2500000,
            remaining_shares_e4=0,
            status="CLOSED",
        )
        assert_fields(
            newer,
            original_shares_e4=1000000000,
            remaining_shares_e4=982450000,
            status="OPEN",
        )

    def test_deduction_is_accumulated_per_lot_across_the_two_consumed_lots(
        self, api, world
    ):
        """The 40100-cent deduction splits 5000 on lot A and 35100 on lot B.

        PRD §3.8: "Each lot's gross and each lot's deduction are rounded to a whole cent on their own before being accumulated, which is why the request's totals can differ from a single deduction taken on the aggregate."
        PRD §3.8: "The request records `early_repurchase_deduction_cents` as the sum of its per-lot deductions and `net_proceeds_cents` as the sum of its per-lot gross amounts each less that lot's deduction, and the deduction total is added to the stockholder's `cumulative_early_repurchase_deduction_cents`."
        PRD §3.8: "Otherwise each tier-two tender is granted the remainder multiplied by its own requested value, divided by the tier-two total, and floored; the flooring leaves a shortfall of a few cents against the remainder, and that leftover is distributed one cent at a time to tier-two tenders in ascending `created_at` order until it is exhausted."

        Design: Corner/calculations/fifo_settlement_consumes_the_older_lot_before_the_newer_one
        """
        base = _two_lot_offering_with_open_period(world)

        period = assert_ok(
            api.process_repurchase_period(base["period_id"], None, TRANSFER_AGENT)
        )

        assert_fields(
            period, capacity_cents=2005000, settled_amount_cents=2005000, prorated=True
        )
        assert_fields(
            world.read_request(base["request_id"]),
            approved_value_cents=2005000,
            approved_shares_e4=20050000,
            early_repurchase_deduction_cents=40100,
            net_proceeds_cents=1964900,
            status="PARTIALLY_FULFILLED",
        )
        assert_fields(
            world.read_investor(base["investor_id"]),
            total_shares_e4=982450000,
            cumulative_early_repurchase_deduction_cents=40100,
            account_status="ACTIVE",
        )


# ─── Which variant becomes the price (PRD §3.4, §3.6) ──────────────────


class TestPublishedVariantBecomesThePrice:
    def test_new_subscription_prices_at_the_official_variant(self, api, world):
        """A ticket written after publication prices at 997, not the 1000 disclosure figure.

        PRD §3.6: "The second is the official variant, and once the record is published it becomes the class's transaction price."
        PRD §3.4: "If there are some, the winner is the one whose `period_end_date` is the greatest, and where two published records share that end date the one created earliest wins; the price is that record's `nav_per_share_cents`."
        PRD §3.4: "`shares_issued_e4` is the net invested amount multiplied by 10,000 and divided by the pinned transaction price, floored to a whole share unit — a stockholder is never issued a fraction of a ten-thousandth of a share."

        Design: Corner/calculations/published_official_variant_becomes_the_next_subscription_price
        """
        base = _offering_with_published_accrued_valuation(world)
        assert base["published_nav"]["nav_per_share_pre_accrual_cents"] == 1000
        assert base["published_nav"]["nav_per_share_cents"] == 997

        subscription = assert_created(
            api.create_subscription(
                subscription_payload(
                    base["offering_id"],
                    base["share_class_id"],
                    base["investor_id"],
                    base["selling_agreement_id"],
                    gross_investment_cents=1000000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            subscription,
            transaction_price_cents=997,
            net_invested_cents=1000000,
            shares_issued_e4=10030090,
            unapplied_cash_cents=1,
            status="PENDING",
        )

    def test_first_ticket_uses_the_initial_offering_price_until_a_nav_is_published(
        self, api, world
    ):
        """Before any publication the price is the offering's own initial price of 1000.

        PRD §3.4: "Consider the valuation records for the share class that are currently `PUBLISHED`. If there are none, the price is the offering's `initial_offering_price_cents`."
        PRD §3.7: "The declared total is built class by class: `total_declared_cents` is the sum, over every share class of the offering, of the `declared_per_share_cents` multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up to a whole cent — again each class's contribution rounded independently before summation."

        Design: Corner/calculations/published_official_variant_becomes_the_next_subscription_price
        """
        base = _offering_with_published_accrued_valuation(world)

        assert base["subscription_a"]["transaction_price_cents"] == 1000
        assert base["declaration"]["total_declared_cents"] == 30000
        offering = world.read_offering(base["offering_id"])
        assert offering["aggregate_nav_cents"] == 9970000, (
            "publication at 997 cents must reprice the aggregate, "
            f"got {offering['aggregate_nav_cents']}"
        )


# ─── Coverage at the full-coverage boundary (PRD §3.7) ─────────────────


class TestCashCoverageBoundary:
    def test_coverage_at_exactly_full_needs_no_board_acknowledgement(self, api, world):
        """Adjusted cash flow equal to the declared total clears the gate untouched.

        PRD §3.7: "`coverage_ratio_cash_bps` is `adjusted_cash_flow_cents` multiplied by 10,000, divided by the same total and floored."
        PRD §3.7: "A coverage ratio landing on exactly 10,000 basis points is fully covered, produces a `return_of_capital_bps` of zero, and needs no acknowledgement."
        PRD §3.7: "A new declaration opens `DECLARED` with `total_distribution_fee_accrued_cents` at zero."

        Design: Corner/calculations/cash_coverage_exactly_at_full_coverage_bps_needs_no_acknowledgement
        """
        base = _offering_ready_for_declaration(world)

        declaration = assert_created(
            api.create_distribution_declaration(
                declaration_payload(
                    base["offering_id"],
                    world.offering_version(base["offering_id"]),
                    record_date="2026-08-05",
                    payment_date="2026-08-20",
                    declared_per_share_cents=15,
                    gaap_net_income_cents=150000,
                    adjusted_cash_flow_cents=150000,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            declaration,
            total_declared_cents=150000,
            coverage_ratio_cash_bps=10000,
            coverage_ratio_gaap_bps=10000,
            return_of_capital_bps=0,
            gaap_return_of_capital_bps=0,
            board_uncovered_acknowledgement=False,
            total_distribution_fee_accrued_cents=0,
            status="DECLARED",
        )

    def test_one_cent_short_of_full_coverage_needs_the_acknowledgement(self, api, world):
        """149999 against 150000 floors to 9999 bps and blocks until the board says so.

        PRD §3.7: "When `coverage_ratio_cash_bps` is below 10,000 basis points the distribution is not fully covered by adjusted cash flow, and the board must have said so: if `board_uncovered_acknowledgement` is false the declaration is refused with `ERR_UNCOVERED_DISTRIBUTION_UNACKNOWLEDGED`."
        PRD §3.7: "Full coverage is 10,000 basis points, so the disclosed return of capital on each basis is what the coverage falls short of full: `return_of_capital_bps` is the greater of zero and 10,000 less `coverage_ratio_cash_bps`, while `gaap_return_of_capital_bps` is the greater of zero and 10,000 less `coverage_ratio_gaap_bps`."

        Design: Corner/calculations/cash_coverage_exactly_at_full_coverage_bps_needs_no_acknowledgement
        """
        base = _offering_ready_for_declaration(world)
        covered = assert_created(
            api.create_distribution_declaration(
                declaration_payload(
                    base["offering_id"],
                    world.offering_version(base["offering_id"]),
                    record_date="2026-08-05",
                    payment_date="2026-08-20",
                    declared_per_share_cents=15,
                    gaap_net_income_cents=150000,
                    adjusted_cash_flow_cents=150000,
                ),
                SPONSOR,
            )
        )
        offering_version = world.offering_version(base["offering_id"])

        assert_error(
            api.create_distribution_declaration(
                declaration_payload(
                    base["offering_id"],
                    offering_version,
                    record_date="2026-08-06",
                    payment_date="2026-08-21",
                    declared_per_share_cents=15,
                    gaap_net_income_cents=150000,
                    adjusted_cash_flow_cents=149999,
                ),
                SPONSOR,
            ),
            ApiErrorId.UNCOVERED_DISTRIBUTION_UNACKNOWLEDGED,
            422,
        )
        assert_total_count(
            api.list_distribution_declarations({"offering_id": base["offering_id"]}, SPONSOR),
            1,
        )

        acknowledged = assert_created(
            api.create_distribution_declaration(
                declaration_payload(
                    base["offering_id"],
                    offering_version,
                    record_date="2026-08-06",
                    payment_date="2026-08-21",
                    declared_per_share_cents=15,
                    gaap_net_income_cents=150000,
                    adjusted_cash_flow_cents=149999,
                    board_uncovered_acknowledgement=True,
                ),
                SPONSOR,
            )
        )

        assert_fields(
            acknowledged,
            coverage_ratio_cash_bps=9999,
            return_of_capital_bps=1,
            gaap_return_of_capital_bps=0,
            status="DECLARED",
        )
        assert world.read_declaration(covered["id"])["status"] == "DECLARED", (
            "a declaration for a different record_date must not be superseded"
        )
