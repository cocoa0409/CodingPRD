"""Every derived money field is already correct in the response that wrote it."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_entry_status,
    assert_fee_status,
    assert_ledger,
    assert_ledger_conserved,
    assert_two_decimals,
)
from test_helpers.constants import (
    SEASON_ASSISTANCE_BUDGET_CENTS,
    STANDARD_ENTRY_FEE_CENTS,
)
from test_helpers.test_users import TOUR_ADMIN, member_headers
from test_helpers.types import ENTRY_APPLIED, FEE_AID_COVERED


class TestImmediateSettlementReads:
    def test_a_fully_assisted_entry_settles_inside_its_own_response(self, api):
        """The entry response and the very next season read already agree.

        PRD: "At submission the money dimension is set in one step from the
        settlement result." "In both award cases the ledger moves in the same
        way: the award is subtracted from the season's
        `assistance_available_cents`, added to its `assistance_committed_cents`,
        and added to the funding application's `consumed_cents`."

        Design: Corner/consistency model/an_assisted_entry_returns_every_derived_field_in_its_own_response
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)
        assert_ledger(
            season,
            available=SEASON_ASSISTANCE_BUDGET_CENTS,
            committed=0,
            disbursed=0,
        )
        member = fx.register_member(api, season["id"])
        fx.verify_member(api, member["id"])

        application = fx.approved_aid_application(api, member["id"], season["id"])
        assert_two_decimals(application["covered_pct"], 1.00, "covered_pct")

        tournament = fx.create_tournament(
            api, season["id"], name="Carolina Regional U17", field_size_limit=4
        )
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        entry = validate_success(
            api.submit_entry(
                f.entry_payload(
                    member["id"],
                    tournament["id"],
                    request_assistance=True,
                    aid_application_id=application["id"],
                ),
                member_headers(member["id"]),
            ),
            201,
        )
        assert_cents(entry["gross_fee_cents"], STANDARD_ENTRY_FEE_CENTS, "gross fee")
        assert_cents(entry["aid_award_cents"], STANDARD_ENTRY_FEE_CENTS, "award")
        assert_cents(entry["net_fee_due_cents"], 0, "net due")
        assert_fee_status(entry, FEE_AID_COVERED)
        assert_entry_status(entry, ENTRY_APPLIED)

        after = fx.read_season(api, season["id"])
        assert_ledger(
            after,
            available=SEASON_ASSISTANCE_BUDGET_CENTS - STANDARD_ENTRY_FEE_CENTS,
            committed=STANDARD_ENTRY_FEE_CENTS,
            disbursed=0,
        )
        assert_ledger_conserved(after, SEASON_ASSISTANCE_BUDGET_CENTS)

        drawn = validate_success(
            api.get_aid_application(application["id"], TOUR_ADMIN), 200
        )
        assert_cents(drawn["consumed_cents"], STANDARD_ENTRY_FEE_CENTS, "consumed")

        reread = fx.read_entry(api, entry["id"])
        assert_cents(reread["aid_award_cents"], entry["aid_award_cents"], "award")
        assert_cents(reread["net_fee_due_cents"], entry["net_fee_due_cents"], "net due")
        assert_fee_status(reread, entry["fee_status"])
