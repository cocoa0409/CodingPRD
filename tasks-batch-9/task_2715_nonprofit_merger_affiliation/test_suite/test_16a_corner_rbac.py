"""Role-based access control compliance tests.

Every test in this module builds its own preconditions through the API, because
the harness restarts the server and empties the database before each test.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NOT_DEAL_PARTY, ERR_ROLE_NOT_PERMITTED
from test_helpers.assertions import (
    assert_field,
    assert_money_equals,
    assert_version_is,
    find_by_id,
)
from test_helpers.test_users import (
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)


def test_platform_admin_owns_the_registry_and_the_clock_but_no_deal_write(api):
    """A PlatformAdmin may run the registry, the clock and the sweep, but every deal
    write it attempts is refused with ERR_ROLE_NOT_PERMITTED before any later rule speaks.

    PRD 2.1 makes the PlatformAdmin the registry operator that "onboards
    organizations, programs and restricted funds, runs the periodic regulatory sweep,
    and drives the logical clock", and states it "is never a party to a deal and never
    votes". PRD 4 authorises it for POST /organizations, POST /programs,
    POST /restricted-funds, the financial restatement, POST /_clock/set_current_utc and
    POST /regulatory-sweeps, and lists it for none of the deal writes. PRD 2.7 evaluates
    the endpoint role check at rule 2, "strictly in ascending order", so it answers
    before the self-restructuring rule at 23 and before every existence rule, and a
    request refused by any validation "increments nothing and mutates nothing" (PRD 2.5).
    PRD 3.1 recomputes monthly_expense_cents as the annual figure divided by twelve and
    rounded half up.

    Design: Corner/rbac/platform_admin_owns_the_registry_and_the_clock_but_no_deal_write
    """
    org_a = validate_success(
        api.create_organization(f.organization_payload(ein="11-1111111"), PLATFORM_ADMIN), 201
    )
    validate_success(
        api.create_program(
            f.program_payload(
                org_a["id"],
                name="Riverside Mentor Match",
                county_code="CA-ALAMEDA",
                annual_expense_cents=9000000,
                clients_served=240,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    fund = validate_success(
        api.create_restricted_fund(
            f.restricted_fund_payload(
                org_a["id"],
                fund_name="Mentor Scholarship Fund",
                restriction_purpose_code="SC-SCHOLARSHIPS",
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    restated = validate_success(
        api.financial_restatement(
            org_a["id"],
            f.financial_restatement_payload(
                annual_expense_cents=120000006,
                unrestricted_net_assets_cents=60000000,
                restatement_reason="FY2026 audited figures",
            ),
            PLATFORM_ADMIN,
        )
    )
    # 120000006 / 12 is 10000000.5 and the half-up step carries it to 10000001.
    assert_money_equals(restated["monthly_expense_cents"], 10000001, "monthly_expense_cents")

    clock = validate_success(api.set_clock(f.clock_payload("2026-08-15T00:00:00.000Z"), PLATFORM_ADMIN))
    assert_field(clock, "current_utc", "2026-08-15T00:00:00.000Z")

    sweep = validate_success(api.run_regulatory_sweep({}, PLATFORM_ADMIN))
    assert sweep["deemed_approved_filing_ids"] == []
    assert sweep["lapsed_letter_of_intent_ids"] == []
    assert sweep["expired_exclusivity_letter_of_intent_ids"] == []

    validate_success(api.get_organization(org_a["id"], PLATFORM_ADMIN))
    rows, _meta = validate_paginated(api.list_restricted_funds(PLATFORM_ADMIN, {"org_id": org_a["id"]}))
    assert [row["id"] for row in rows] == [fund["id"]]

    # Rule 2 answers before rule 23: this body names the same organization twice.
    validate_error(
        api.create_restructuring(f.restructuring_payload(org_a["id"], org_a["id"]), PLATFORM_ADMIN),
        ERR_ROLE_NOT_PERMITTED,
    )
    # Rule 2 answers before every existence rule: the deal reference is fabricated.
    validate_error(
        api.transfer_restricted_fund(fund["id"], f.transfer_payload(NON_EXISTENT_UUID), PLATFORM_ADMIN),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_diligence_request(
            f.diligence_request_payload(
                NON_EXISTENT_UUID, severity="LOW", summary="admin probe", exposure_cents=0
            ),
            PLATFORM_ADMIN,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    unchanged = validate_success(api.get_restricted_fund(fund["id"], PLATFORM_ADMIN))
    assert_field(unchanged, "transfer_status", "HELD")
    assert_version_is(unchanged, 1, "restricted fund")


def test_strategy_officer_drives_the_deal_and_is_barred_from_the_board_vote(api):
    """A StrategyOfficer drives its own deal but is refused with ERR_ROLE_NOT_PERMITTED on
    the board vote, the diligence desk and the registry, while a right-role/wrong-party
    call is refused with the distinct ERR_NOT_DEAL_PARTY.

    PRD 2.1 says a StrategyOfficer "opens exploratory conversations, negotiates letters of
    intent, selects the legal structure, and consummates or abandons the transaction", and
    PRD 4 additionally authorises it for POST /programs, the financial restatement and the
    dossier read while listing it for none of POST /board-approvals, POST /diligence-requests,
    POST /organizations or the restricted-fund transfer. PRD 2.7 places the endpoint role
    check at rule 2 and deal-party ownership at rule 13, so the role refusal answers before
    both the existence rules and the deal-state rule at 16; PRD 3.3 gives withdrawal to the
    initiator, and PRD 2.7 rule 13 refuses "the other party" with ERR_NOT_DEAL_PARTY.
    PRD 3.3 also moves a withdrawn letter to WITHDRAWN with exclusivity_status RELEASED.

    Design: Corner/rbac/strategy_officer_drives_the_deal_and_is_barred_from_the_board_vote
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    org_a, org_b, deal, loi = ctx["org_a"], ctx["org_b"], ctx["deal"], ctx["loi"]
    so_a = make_strategy_officer_headers(org_a["id"])
    so_b = make_strategy_officer_headers(org_b["id"])

    validate_success(
        api.create_program(
            f.program_payload(
                org_a["id"],
                name="Riverside Mentor Match",
                county_code="CA-ALAMEDA",
                annual_expense_cents=9000000,
                clients_served=240,
            ),
            so_a,
        ),
        201,
    )
    validate_success(
        api.financial_restatement(
            org_a["id"],
            f.financial_restatement_payload(
                annual_expense_cents=100000002,
                unrestricted_net_assets_cents=61000000,
                restatement_reason="Pledge reclassified as unrestricted",
            ),
            so_a,
        )
    )
    validate_success(api.get_dossier(deal["id"], so_a))

    version = fx.deal_version(api, deal["id"], so_a)
    validate_error(
        api.create_board_approval(
            f.board_approval_payload(
                deal["id"],
                version,
                "INITIATOR",
                recusals=0,
                votes_for=12,
                votes_against=0,
                conflict_disclosures_count=0,
            ),
            so_a,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal["id"], workstream="CONTRACTS", severity="LOW", summary="officer probe", exposure_cents=0
            ),
            so_a,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_organization(
            f.organization_payload(legal_name="Officer Registered Entity", ein="66-6666666"), so_a
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    # Fabricated fund id: the role refusal at rule 2 still answers first.
    validate_error(
        api.transfer_restricted_fund(NON_EXISTENT_UUID, f.transfer_payload(deal["id"]), so_a),
        ERR_ROLE_NOT_PERMITTED,
    )

    # Right role, wrong party: withdrawal belongs to the initiator only.
    validate_error(
        api.withdraw_letter_of_intent(loi["id"], f.withdraw_payload(withdrawal_reason="Terms revisited"), so_b),
        ERR_NOT_DEAL_PARTY,
    )

    withdrawn = validate_success(
        api.withdraw_letter_of_intent(loi["id"], f.withdraw_payload(withdrawal_reason="Terms revisited"), so_a)
    )
    assert_field(withdrawn, "status", "WITHDRAWN")
    assert_field(withdrawn, "exclusivity_status", "RELEASED")


def test_board_secretary_may_certify_only_its_own_partys_approval(api):
    """Certification is scoped to the organization the approval's approving_party resolves
    to: the counterparty secretary and a stranger organization both answer
    ERR_NOT_DEAL_PARTY, a non-secretary role answers the earlier ERR_ROLE_NOT_PERMITTED,
    and only the owning party's secretary draws the seats.

    PRD 2.1 makes BoardSecretary an entity-backed role whose X-User-ID "is the id of the
    acting Organization". PRD 2.7 rule 13 requires that "recording a board approval and its
    certify and rescind actions require the organization resolved from approving_party",
    otherwise ERR_NOT_DEAL_PARTY, while rule 2 refuses an unauthorized role first with
    ERR_ROLE_NOT_PERMITTED; PRD 4 authorises only BoardSecretary for the certify action and
    only StrategyOfficer for consummation. PRD 3.5 says certification "draws the party's
    seats from the reserved pool": the seats due for INITIATOR are the governing letter's
    board_seat_split_initiator, "subtracted from the deal's reserved_seat_pool, and written
    to governance_seats on the approving party's organization", and the deal only advances
    BOARD_APPROVAL to REGULATORY_REVIEW once both parties hold a CERTIFIED resolution.

    Design: Corner/rbac/board_secretary_may_certify_only_its_own_partys_approval
    """
    ctx = fx.setup_deal_board_approval(api)
    org_a, org_b, deal = ctx["org_a"], ctx["org_b"], ctx["deal"]
    ba_i = ctx["approval_initiator"]
    org_c = fx.create_organization(api, fx.ORG_C)

    # Both parties, but the target's secretary does not own the initiator's minutes.
    validate_error(
        api.certify_board_approval(ba_i["id"], f.certify_payload(), make_board_secretary_headers(org_b["id"])),
        ERR_NOT_DEAL_PARTY,
    )
    validate_error(
        api.certify_board_approval(ba_i["id"], f.certify_payload(), make_board_secretary_headers(org_c["id"])),
        ERR_NOT_DEAL_PARTY,
    )
    # Rule 2 answers before rule 13.
    validate_error(
        api.certify_board_approval(ba_i["id"], f.certify_payload(), INTEGRATION_MANAGER),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.consummate(
            deal["id"],
            f.consummate_payload(closing_memo_ref="CLOSE-9999"),
            make_board_secretary_headers(org_a["id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    rows, _meta = validate_paginated(api.list_deal_board_approvals(deal["id"], PLATFORM_ADMIN))
    untouched = find_by_id(rows, ba_i["id"])
    assert_field(untouched, "status", "RECORDED")
    assert_version_is(untouched, 1, "board approval")
    assert_field(fx.read_deal(api, deal["id"]), "reserved_seat_pool", 15)

    certified = validate_success(
        api.certify_board_approval(
            ba_i["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-A-1", certifying_secretary_ref="SEC-A-2"),
            make_board_secretary_headers(org_a["id"]),
        )
    )
    assert_field(certified, "status", "CERTIFIED")
    assert_field(certified, "allocated_seats", 8)
    assert_field(validate_success(api.get_organization(org_a["id"], PLATFORM_ADMIN)), "governance_seats", 8)
    after = fx.read_deal(api, deal["id"])
    assert_field(after, "reserved_seat_pool", 7)
    # The bubble-up still waits for the target's certification.
    assert_field(after, "status", "BOARD_APPROVAL")
