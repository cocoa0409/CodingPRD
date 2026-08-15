"""Discipline and cascades: package withdrawal contagion, broadcaster
suspension/bar cascades, breach termination side effects, and segregation
of duties between ComplianceOfficer and RightsManager."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_winning_bid,
    add_payment_milestone,
    add_production_obligation,
    advance_clock,
    create_accredited_broadcaster,
    create_package,
    create_rights_asset,
    execute_deal,
    file_bid,
    file_sublicense_request,
    get_bid,
    get_broadcaster,
    get_deal,
    get_milestone,
    get_obligation,
    get_package,
    get_sublicense,
    lock_asset_packages,
    setup_active_deal,
    setup_executed_deal,
    setup_open_market,
    setup_shortlisted_bid,
    setup_submitted_bid,
    submit_bid,
    validate_error,
    validate_success,
    walk_bid_to_shortlisted,
)

RM = TEST_USERS["rights_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestPackageWithdrawalCascade:
    def test_withdrawal_cascades_to_submitted_bid(self, api):
        """PRD §3.1: "Withdrawing a package is contagious: every bid on it
        that has not reached a terminal state is withdrawn along with it."

        Design: Difficulty/transitive_cascade/package_withdrawal_cascades_to_bid_withdrawal
        """
        bundle = setup_submitted_bid()
        package, bid = bundle["package"], bundle["bid"]
        withdrawn = validate_success(api.withdraw_package(package["id"], RM), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_bid(package["id"], bid["id"])["status"] == "WITHDRAWN"

    def test_withdrawal_cascades_to_draft_bid(self, api):
        """PRD §3.1: "Withdrawing a package is contagious: every bid on it
        that has not reached a terminal state is withdrawn along with it."

        A bid still in DRAFT is non-terminal and is withdrawn too.

        Design: Difficulty/transitive_cascade/package_withdrawal_cascades_to_bid_withdrawal
        """
        asset, package = setup_open_market()
        b1 = create_accredited_broadcaster(legal_name="Eurosport")
        b2 = create_accredited_broadcaster(
            legal_name="beIN Sports", credit_rating="SPECULATIVE"
        )
        bid_submitted = file_bid(package["id"], b1["id"])
        submit_bid(package["id"], bid_submitted["id"], b1["id"])
        bid_draft = file_bid(package["id"], b2["id"])
        assert bid_draft["status"] == "DRAFT"

        validate_success(api.withdraw_package(package["id"], RM), 200)
        assert get_package(package["id"])["status"] == "WITHDRAWN"
        assert get_bid(package["id"], bid_submitted["id"])["status"] == "WITHDRAWN"
        assert get_bid(package["id"], bid_draft["id"])["status"] == "WITHDRAWN"


class TestBroadcasterBarCascade:
    def _award_deal(self, api, asset, package, broadcaster):
        bid = file_bid(package["id"], broadcaster["id"])
        submit_bid(package["id"], bid["id"], broadcaster["id"])
        walk_bid_to_shortlisted(package["id"], bid["id"])
        return accept_winning_bid(package["id"], bid["id"])

    def test_bar_cascades_to_deals_and_milestones(self, api):
        """PRD §3.2: "Barring cascades through the broadcaster's entire
        book: every non-terminal deal naming the broadcaster moves to
        `TERMINATED_BREACH`, each such deal's `posture` falls to `FROZEN`,
        and its outstanding payment milestones move to `DEFAULTED`."
        PRD §3.2: "A `ComplianceOfficer` may bar only a broadcaster that is
        currently `SUSPENDED` (`ERR_BROADCASTER_NOT_SUSPENDED`), and only
        when at least one deal naming this broadcaster has already been
        terminated for breach — without such a deal the bar is rejected with
        `ERR_NO_BREACH_DEAL`."

        Design: Difficulty/transitive_cascade/broadcaster_bar_cascades_to_deal_termination_and_milestone_default
        """
        asset = create_rights_asset(total_package_pool=3)
        p1 = create_package(asset["id"], package_code="BAR-P1", territory_code="US")
        p2 = create_package(asset["id"], package_code="BAR-P2", territory_code="GB")
        lock_asset_packages(asset["id"])
        broadcaster = create_accredited_broadcaster()

        # Deal 1: four milestones (weights sum to 1.0). The first is paid on
        # time so the deal moves EXECUTED -> ACTIVE (§3.5) — breach
        # termination requires an ACTIVE deal (§3.9). The other three go
        # overdue once the clock passes their due dates -> delinquency 3.
        deal1 = self._award_deal(api, asset, p1, broadcaster)
        d1_ms = [
            add_payment_milestone(
                deal1["id"],
                season_index=1,
                sequence_in_season=i,
                due_date=due,
                milestone_weight=w,
            )
            for i, (due, w) in enumerate(
                [
                    ("2026-08-15T00:00:00Z", 0.25),
                    ("2026-09-01T00:00:00Z", 0.25),
                    ("2026-09-15T00:00:00Z", 0.25),
                    ("2026-10-01T00:00:00Z", 0.25),
                ],
                start=1,
            )
        ]
        add_production_obligation(deal1["id"], season_index=1)
        execute_deal(deal1["id"])
        for m in d1_ms:
            validate_success(api.invoice_milestone(deal1["id"], m["id"], FC), 200)
        validate_success(api.record_payment(deal1["id"], d1_ms[0]["id"], FC), 200)
        assert get_deal(deal1["id"])["status"] == "ACTIVE"

        # Deal 2: ACTIVE, with one outstanding INVOICED milestone and a
        # PENDING sublicense request.
        deal2 = self._award_deal(api, asset, p2, broadcaster)
        ms2a = add_payment_milestone(
            deal2["id"],
            season_index=1,
            sequence_in_season=1,
            due_date="2026-11-01T00:00:00Z",
            milestone_weight=0.5,
        )
        ms2b = add_payment_milestone(
            deal2["id"],
            season_index=1,
            sequence_in_season=2,
            due_date="2027-01-01T00:00:00Z",
            milestone_weight=0.5,
        )
        ob2 = add_production_obligation(deal2["id"], season_index=1)
        execute_deal(deal2["id"])
        validate_success(api.invoice_milestone(deal2["id"], ms2a["id"], FC), 200)
        validate_success(api.record_payment(deal2["id"], ms2a["id"], FC), 200)
        validate_success(api.invoice_milestone(deal2["id"], ms2b["id"], FC), 200)
        sub = file_sublicense_request(deal2["id"], broadcaster["id"])
        assert get_deal(deal2["id"])["status"] == "ACTIVE"

        # Deal 1 hits the breach threshold once the clock passes all dues.
        advance_clock("2026-10-15T00:00:00Z")
        assert get_deal(deal1["id"])["payment_delinquency_count"] == 3
        validate_success(api.terminate_breach(deal1["id"], CO), 200)
        assert get_broadcaster(broadcaster["id"])["status"] == "SUSPENDED"

        # The bar is now lawful: a TERMINATED_BREACH deal exists.
        validate_success(api.bar_broadcaster(broadcaster["id"], CO), 200)

        assert get_broadcaster(broadcaster["id"])["status"] == "BARRED"
        deal2_after = get_deal(deal2["id"])
        assert deal2_after["status"] == "TERMINATED_BREACH"
        assert deal2_after["posture"] == "FROZEN"
        assert get_milestone(deal2["id"], ms2b["id"])["status"] == "DEFAULTED"
        assert get_sublicense(deal2["id"], sub["id"])["status"] == "REJECTED"

    def test_terminate_breach_scorched_earth_side_effects(self, api):
        """PRD §3.9: "every payment milestone in `SCHEDULED`, `INVOICED`, or
        `OVERDUE` moves to `DEFAULTED`; every production obligation still
        `TRACKING` moves to `SHORTFALL_DECLARED` with `shortfall_games`
        fixed as required minus delivered; every `PENDING` sublicense
        request is rejected and every `APPROVED` one is revoked with reason
        TERMINATION; and the deal's broadcaster is suspended per §3.2."

        Design: Difficulty/transitive_cascade/broadcaster_bar_cascades_to_deal_termination_and_milestone_default
        """
        bundle = setup_executed_deal(
            milestone_specs=[
                (1, 1, "2026-09-01T00:00:00Z", 0.25),
                (1, 2, "2026-09-01T00:00:00Z", 0.25),
                (1, 3, "2026-09-01T00:00:00Z", 0.25),
                (1, 4, "2026-12-01T00:00:00Z", 0.25),
            ],
            package_overrides={"games_committed": 5},
            bid_overrides={"production_commitment_games": 5},
        )
        deal_id = bundle["deal"]["id"]
        broadcaster = bundle["broadcaster"]
        obligation = bundle["obligations"][0]
        for m in bundle["milestones"]:
            validate_success(api.invoice_milestone(deal_id, m["id"], FC), 200)
        # Fourth milestone paid on time -> deal ACTIVE.
        validate_success(
            api.record_payment(deal_id, bundle["milestones"][3]["id"], FC), 200
        )
        sub = file_sublicense_request(deal_id, broadcaster["id"])

        advance_clock("2026-09-02T00:00:00Z")
        deal = get_deal(deal_id)
        assert deal["status"] == "ACTIVE"
        assert deal["payment_delinquency_count"] == 3

        terminated = validate_success(api.terminate_breach(deal_id, CO), 200)
        assert terminated["status"] == "TERMINATED_BREACH"
        for m in bundle["milestones"][:3]:
            assert get_milestone(deal_id, m["id"])["status"] == "DEFAULTED"
        obligation_after = get_obligation(deal_id, obligation["id"])
        assert obligation_after["status"] == "SHORTFALL_DECLARED"
        assert obligation_after["shortfall_games"] == 5
        assert get_sublicense(deal_id, sub["id"])["status"] == "REJECTED"
        assert get_broadcaster(broadcaster["id"])["status"] == "SUSPENDED"


class TestSuspensionCascade:
    def test_suspend_rejects_pending_sublicense_requests(self, api):
        """PRD §3.2: "Suspending an `ACCREDITED` broadcaster
        (`ERR_BROADCASTER_NOT_ACCREDITED` in any other state) has immediate
        market consequences: every live bid that broadcaster has on packages
        still in `OPEN_FOR_BIDS` moves to `WITHDRAWN`, and every `PENDING`
        sublicense request attached to a deal where this broadcaster is the
        deal's broadcaster is rejected."

        Design: Corner/cross_cutting_complexity_layers/cascading_broadcaster_suspend_rejects_pending_sublicenses
        """
        bundle = setup_active_deal()
        deal_id = bundle["deal"]["id"]
        broadcaster = bundle["broadcaster"]
        sub = file_sublicense_request(deal_id, broadcaster["id"])
        assert sub["status"] == "PENDING"

        suspended = validate_success(
            api.suspend_broadcaster(broadcaster["id"], CO), 200
        )
        assert suspended["status"] == "SUSPENDED"
        assert get_sublicense(deal_id, sub["id"])["status"] == "REJECTED"


class TestSegregationOfDuties:
    def test_termination_powers_are_segregated(self, api):
        """PRD §2.1: "A `ComplianceOfficer` is the league compliance office
        and owns broadcaster discipline, blackout windows, sublicense
        revocation, exclusion of disputed measurements, and termination for
        breach."
        PRD §2.1: "an authenticated caller whose role is not authorized for
        the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/roles/segregation_of_duties_compliance_vs_rights_manager
        """
        bundle = setup_active_deal()
        deal_id = bundle["deal"]["id"]
        res1 = api.terminate_breach(deal_id, RM)
        validate_error(res1, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
        res2 = api.terminate_convenience(deal_id, CO)
        validate_error(res2, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
