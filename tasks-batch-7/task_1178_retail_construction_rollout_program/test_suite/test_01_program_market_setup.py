"""Program creation defaults, program completion gate, market bidding gate,
and authentication."""
from test_helpers import (
    ApiErrorId,
    assert_rollout_program,
    create_program_payload,
    create_site,
    is_iso8601_timestamp,
    is_valid_uuid,
    read_market,
    read_program,
    set_clock,
    setup_program_with_market,
    validate_error,
    validate_success,
)

DIRECTOR_KEY = "program_director_headers"
PROCUREMENT_KEY = "procurement_lead_headers"


class TestProgramMarketSetup:
    def test_program_create_applies_defaults(self, api, program_director_headers):
        """PRD §3.1: "A new program starts in `SETUP` with its computed
        aggregates zeroed: `committed_cents`, `actuals_cents`, and
        `contingency_reserved_cents` all read 0, `contingency_free_cents`
        equals the full pool, and `budget_posture` reads `WITHIN_PLAN`."

        Design: Corner/entities/c_program_create_applies_defaults
        """
        set_clock()
        resp = api.create_program(
            create_program_payload(total_budget_cents=500_000_000,
                                   contingency_pool_cents=250_000),
            headers=program_director_headers)
        program = validate_success(resp, expected_status=201)
        assert_rollout_program(program)
        assert program["status"] == "SETUP"
        assert program["committed_cents"] == 0
        assert program["actuals_cents"] == 0
        assert program["contingency_reserved_cents"] == 0
        assert program["contingency_free_cents"] == 250_000
        assert program["budget_posture"] == "WITHIN_PLAN"
        assert is_valid_uuid(program["id"])
        assert is_iso8601_timestamp(program["created_at"])

    def test_program_complete_with_active_sites_rejected(self, api,
                                                         program_director_headers):
        """PRD §3.1: "Completing the program moves it from `ACTIVE` to
        `COMPLETE` and is allowed only when every site of the program has
        reached `OPEN` or `REMOVED`; the attempt is rejected with
        `ERR_ACTIVE_SITES_REMAIN` while any site is still mid-flight."

        Design: Corner/errors/c_program_complete_with_active_sites_rejected
        """
        ctx = setup_program_with_market()
        # One LISTED site keeps the program from completing.
        create_site(ctx["program"]["id"], ctx["market"]["id"])

        resp = api.complete_program(ctx["program"]["id"],
                                    headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_SITES_REMAIN)
        assert read_program(ctx["program"]["id"])["status"] == "ACTIVE"

    def test_market_open_bidding_requires_active_program(self, api,
                                                         procurement_lead_headers):
        """PRD §3.1: "Opening bidding moves it from `REGISTERED` to `BIDDING`
        and requires the parent program to be `ACTIVE`, failing with
        `ERR_PROGRAM_NOT_ACTIVE` otherwise."

        Design: Corner/state_machines/c_market_open_bidding_requires_active_program
        """
        ctx = setup_program_with_market(activate=False)
        resp = api.open_market_bidding(ctx["market"]["id"],
                                       headers=procurement_lead_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        assert read_market(ctx["market"]["id"])["status"] == "REGISTERED"

    def test_missing_auth_header_returns_401(self, api):
        """PRD §2.1: "A request with a missing or unrecognized header or role
        is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/c_auth_missing_header_returns_401
        """
        set_clock()
        resp = api.create_program(
            create_program_payload(name="NoAuth Program", total_budget_cents=1000,
                                   contingency_pool_cents=100),
            headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
