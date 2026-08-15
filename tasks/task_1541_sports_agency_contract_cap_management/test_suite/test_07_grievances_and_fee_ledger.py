"""Grievance adjudication, the open-grievance void gate, and ledger reads."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_certified_agent,
    create_contract,
    create_grievance,
    fee_entries_for_contract,
    list_fee_entries,
    make_agency_manager_headers,
    make_agent_headers,
    setup_negotiation_env,
    setup_signed_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

LEAGUE = TEST_USERS["league_officer_headers"]


def _drive_to_resolved(api, env, grievance_id, outcome="UPHELD"):
    """FILED -> UNDER_REVIEW -> ARBITRATION -> RESOLVED (contract is SIGNED)."""
    validate_success(api.start_review_grievance(
        env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
        grievance_id, LEAGUE))
    validate_success(api.escalate_grievance(
        env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
        grievance_id, LEAGUE))
    return validate_success(api.resolve_grievance(
        env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
        grievance_id, outcome, LEAGUE))


class TestGrievanceWorkflow:
    def test_grievance_terminal_state_lockdown(self, api):
        """PRD §3.9: "`RESOLVED` and `WITHDRAWN` are terminal."
        PRD §2.7: "Fourth, state: the target entity must be in the exact state
        the requested transition demands — a proposal must be in `DRAFT` to be
        submitted, a cap season in `OPEN` to be locked — else `ERR_INVALID_STATE`
        (409)."

        A RESOLVED grievance rejects any further transition.

        Design: Corner/state_machines/grievance_terminal_state_lockdown
        """
        env = setup_signed_contract(base_salary_cents=5_000_000, years=1)
        grievance = create_grievance(env, env["contract"]["id"],
                                     description="Missing check",
                                     claimed_amount_cents=500_000)
        resolved = _drive_to_resolved(api, env, grievance["id"])
        assert resolved["status"] == "RESOLVED"

        resp = api.start_review_grievance(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
            grievance["id"], LEAGUE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_grievance_under_review_to_filed_revert(self, api):
        """PRD §3.9: "From there the officer may return the filing for cure —
        `UNDER_REVIEW` back to `FILED`, a revert loop used to demand additional
        evidence — or escalate it to `ARBITRATION`, a move permitted only while
        the disputed contract stands `SIGNED`."

        Design: Corner/state_machines/grievance_under_review_to_filed_revert
        """
        env = setup_negotiation_env(agency_name="GRA")
        contract = create_contract(env, base_salary_cents=5_000_000,
                                   guaranteed_cents=5_000_000)
        env.setdefault("contract_clients", {})[contract["id"]] = env["client"]["id"]
        grievance = create_grievance(env, contract["id"], category="BONUS_DISPUTE",
                                     description="d", claimed_amount_cents=100_000)
        reviewed = validate_success(api.start_review_grievance(
            env["agency"]["id"], env["client"]["id"], contract["id"],
            grievance["id"], LEAGUE))
        assert reviewed["status"] == "UNDER_REVIEW"

        reverted = validate_success(api.return_for_cure_grievance(
            env["agency"]["id"], env["client"]["id"], contract["id"],
            grievance["id"], LEAGUE))
        assert reverted["status"] == "FILED", "revert loop returns the filing for cure"


class TestVoidGatedByOpenGrievance:
    def test_void_signed_contract_with_open_grievance_blocked(self, api):
        """PRD §3.6: "Once a contract is `SIGNED`, voiding is permitted only
        when no grievance on that contract sits in `FILED`, `UNDER_REVIEW`, or
        `ARBITRATION` — an open dispute freezes the paper, and the attempt is
        rejected with `ERR_OPEN_GRIEVANCE`."

        Design: Corner/validations/void_signed_contract_with_open_grievance_blocked
        """
        env = setup_signed_contract(base_salary_cents=5_000_000, years=1)
        create_grievance(env, env["contract"]["id"], claimed_amount_cents=100_000)

        resp = api.void_contract(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"],
            make_agency_manager_headers(env["manager"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_GRIEVANCE, expected_status=409)
        after = validate_success(api.get_contract(
            env["agency"]["id"], env["client"]["id"], env["contract"]["id"], LEAGUE))
        assert after["signing_status"] == "SIGNED", "blocked void leaves the contract signed"


class TestFeeLedgerReads:
    def test_fee_ledger_list_filter_by_agent(self, api):
        """PRD §3.9: "Entries are read through the agency-scoped ledger list,
        filterable by `agent_id`, `contract_id`, `endorsement_deal_id`, `kind`,
        and `status`."

        Only the signing agent has accrued a fee; the second certified agent's
        filtered view is empty.

        Design: Corner/endpoints/fee_ledger_list_filter_by_agent
        """
        env = setup_signed_contract(base_salary_cents=10_000_000, years=1)
        other_agent = add_certified_agent(env)

        data1, meta1 = validate_paginated(api.list_fee_ledger_entries(
            env["agency"]["id"], LEAGUE, params={"agent_id": env["agent"]["id"]}))
        assert meta1["total_count"] == 1
        assert data1[0]["kind"] == "PLAYING_CONTRACT"
        assert data1[0]["agent_id"] == env["agent"]["id"]

        data2, meta2 = validate_paginated(api.list_fee_ledger_entries(
            env["agency"]["id"], LEAGUE, params={"agent_id": other_agent["id"]}))
        assert meta2["total_count"] == 0
        assert data2 == []
