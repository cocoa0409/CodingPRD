"""Priority-pair conflict tests (PRD §2.6 fixed validation cascade)."""
import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    EST,
    FOREMAN,
    ApiErrorId,
    create_rom_bid,
    get_success_data,
    make_client_pm_headers,
    setup_accepted_production,
    setup_basic_scenario,
    setup_design_package,
    setup_in_build_production,
    submit_bid,
    accept_bid,
    validate_error,
    validate_success,
)


class TestStateBeforeSafety:
    def test_start_build_on_on_hold_returns_invalid_state_not_safety(self, api):
        """PRD §2.6 priority 4 ("State legality") precedes priority 5
        ("Safety and segregation"): a start-build on an `ON_HOLD` production
        fails the state gate. PRD §3.4: "complete-build is rejected while a
        production is `ON_HOLD`, because that transition is gated to
        `IN_BUILD`."  PRD §2.6: "the target entity must be in a state from
        which the requested transition exists (failures: `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/start_build_state_before_safety
        """
        shop, client, pkg, bid, production, rev_1, res = setup_in_build_production()
        # Add a second review and kick it back -> production ON_HOLD
        rev_2 = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 5000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        api.request_revision_engineering_review(
            rev_2["id"], {"revision_note": "Recheck"}, ENGINEER,
        )
        prod_now = get_success_data(api.get_production(production["id"], EST))
        assert prod_now["status"] == "ON_HOLD"
        # Both gates would fail; state wins
        resp = api.start_build(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_production_remains_on_hold_after_rejected_start(self, api):
        """PRD §3.4: "complete-build is rejected while a production is
        `ON_HOLD`" — and no side effect mutates the production.

        Design: Difficulty/priority_pair_validation_conflict/start_build_state_before_safety
        """
        shop, client, pkg, bid, production, rev_1, res = setup_in_build_production()
        rev_2 = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 5000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        api.request_revision_engineering_review(
            rev_2["id"], {"revision_note": "Recheck"}, ENGINEER,
        )
        api.start_build(production["id"], FOREMAN)  # rejected
        prod_after = get_success_data(api.get_production(production["id"], EST))
        assert prod_after["status"] == "ON_HOLD"


class TestReferentialBeforeFiscal:
    def test_stale_revision_accept_wins_over_credit_limit(self, api):
        """PRD §2.6 priority 6 ("Referential freshness", failure
        `ERR_STALE_DRAWING_REVISION`) precedes priority 9 ("Fiscal
        constraints", failure `ERR_CREDIT_LIMIT_EXCEEDED`). PRD §3.3:
        "still revision-fresh (package `CURRENT` and `pinned_drawing_revision`
        equal to the package's `drawing_revision`, else
        `ERR_STALE_DRAWING_REVISION`)".

        Design: Difficulty/priority_pair_validation_conflict/bid_accept_referential_before_fiscal
        """
        shop, client, pkg = setup_basic_scenario(credit_limit_cents=500000)
        bid = create_rom_bid(client["id"], pkg["id"], estimated_crew_hours=100)
        submit_bid(bid["id"])
        # Re-upload supersedes rev 1 -> rev 2; bid pinned at 1 becomes stale.
        setup_design_package(client["id"], show_title="Hamlet")
        resp = api.accept_bid(bid["id"], make_client_pm_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_DRAWING_REVISION, 409)

    def test_rejected_accept_creates_no_production(self, api):
        """PRD §3.3: the stale-revision check fires on accept. On rejection
        the bid stays SUBMITTED and no production is created.

        Design: Difficulty/priority_pair_validation_conflict/bid_accept_referential_before_fiscal
        """
        shop, client, pkg = setup_basic_scenario(credit_limit_cents=500000)
        bid = create_rom_bid(client["id"], pkg["id"], estimated_crew_hours=100)
        submit_bid(bid["id"])
        setup_design_package(client["id"], show_title="Hamlet")
        api.accept_bid(bid["id"], make_client_pm_headers(client["id"]))
        after = get_success_data(api.get_bid(bid["id"], EST))
        assert after["status"] == "SUBMITTED"
        assert after.get("production_id") is None


class TestCreditLimitBoundary:
    def test_accept_at_exact_credit_limit_passes(self, api):
        """PRD §3.3: "the client's `outstanding_cents` plus the bid's
        `price_cents` must be no greater than `credit_limit_cents`, with
        equality passing (else `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409)."

        Design: Corner/validations/accept_at_exact_credit_limit_passes_then_next_exceeds
        """
        shop, client, pkg = setup_basic_scenario(credit_limit_cents=900000)
        # ROM price 100 * 9000 = 900000 == limit -> equality passes
        bid = create_rom_bid(client["id"], pkg["id"], estimated_crew_hours=100)
        submit_bid(bid["id"])
        accepted = accept_bid(bid["id"], client["id"])
        assert accepted["status"] == "ACCEPTED"

    def test_second_accept_exceeding_limit_fails(self, api):
        """PRD §3.3: "credit-worthy — the client's `outstanding_cents` plus
        the bid's `price_cents` must be no greater than `credit_limit_cents`,
        with equality passing (else `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409)."

        Design: Corner/validations/accept_at_exact_credit_limit_passes_then_next_exceeds
        """
        from test_helpers import setup_second_package
        shop, client, pkg_a = setup_basic_scenario(credit_limit_cents=900000)
        pkg_b = setup_second_package(client["id"], show_title="Macbeth",
                                     load_in_at="2026-10-24T00:00:00Z",
                                     strike_at="2026-11-07T00:00:00Z")
        bid_a = create_rom_bid(client["id"], pkg_a["id"], estimated_crew_hours=100)
        submit_bid(bid_a["id"])
        # Second bid: 50 sqft * 9000 = 450000
        bid_b = create_rom_bid(client["id"], pkg_b["id"], floor_area_sqft=50,
                               estimated_crew_hours=50,
                               build_start_at="2026-10-01T00:00:00Z")
        submit_bid(bid_b["id"])
        # Accept A: 0 + 900000 <= 900000 (equality) — succeeds
        accept_bid(bid_a["id"], client["id"])
        # Accept B: 900000 + 450000 > 900000 — fails
        resp = api.accept_bid(bid_b["id"], make_client_pm_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 409)
        after = get_success_data(api.get_bid(bid_b["id"], EST))
        assert after["status"] == "SUBMITTED"
