"""Refusal-path compliance tests, third part: integration, programmes and funds.

These tests cover the integration-task refusals of PRD 3.8, the third-party
continuity refusal, the restricted-fund authority refusals of PRD 3.6 and the
eligibility refusal that a consummated merger leaves behind. Each one drives the
request that must be refused, names the exact error the PRD assigns to it, and
then proves the refusal changed nothing before walking the same request through
on its lawful terms.

The harness restarts the server and empties the registry before every test, so
each test registers its own organizations and walks its own deal forward.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DEPENDENCY_NOT_COMPLETE,
    ERR_DEPENDENCY_NOT_IN_SAME_DEAL,
    ERR_DONOR_CONSENT_REQUIRED,
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_TASK_STATE,
    ERR_ORGANIZATION_NOT_ELIGIBLE,
    ERR_PROGRAM_NOT_DEAL_PARTY_ASSET,
)
from test_helpers.assertions import (
    assert_field,
    assert_money_equals,
    assert_null,
    assert_status,
    assert_version_is,
    find_by_id,
)
from test_helpers.test_users import (
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_strategy_officer_headers,
)


def test_integration_task_dependency_rejects_a_foreign_deal_task_and_an_incomplete_predecessor(api):
    """A predecessor belonging to another deal is refused at creation, and a predecessor that
    exists on the same deal but is not yet COMPLETE is refused at start.

    PRD 3.8 requires a supplied depends_on_task_id to "belong to the same deal as the task
    being created and must not be the task itself, else ERR_DEPENDENCY_NOT_IN_SAME_DEAL",
    which is a different refusal from a predecessor identifier that resolves to nothing at
    all. It then states that starting a task requires the task to be PLANNED, the deal to
    have reached INTEGRATION, an APPROVED or DEEMED_APPROVED filing where the deal owes
    attorney-general review, and "where depends_on_task_id is set, that predecessor task
    must already be COMPLETE, else ERR_DEPENDENCY_NOT_COMPLETE". On success the task moves
    PLANNED to IN_PROGRESS and stamps started_at from the logical clock, which PRD 2.2 fixes
    at 2026-08-01T00:00:00Z, and completing an IN_PROGRESS task stamps completed_at the same
    way. Each transition raises the task's version by one and "touches nothing else", so the
    other deal's task is unaffected. PRD 3.8 also creates non-continuity tasks in PLANNED
    with held_reason null.

    Design: Corner/errors/integration_task_dependency_rejects_a_foreign_deal_task_and_an_incomplete_predecessor
    """
    one = fx.setup_deal_integration(api)
    deal_one = one["deal"]["id"]
    assert_status(one["deal"], "INTEGRATION")

    two = {
        "org_a": fx.create_organization(api),
        "org_b": fx.create_organization(api),
    }
    two = fx.setup_deal_exploratory(api, two)
    two = fx.setup_deal_rationale_built(api, two)
    two = fx.setup_deal_loi_negotiation(api, two)
    two = fx.setup_deal_diligence(api, two)
    two = fx.setup_deal_diligence_closed(api, two)
    two = fx.setup_deal_structure_selected(api, two)
    deal_two = two["deal"]["id"]
    foreign = fx.create_task(
        api,
        deal_two,
        workstream="SYSTEMS",
        title="Migrate the other deal's finance ledger",
        crew_code="CREW-B1",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-10",
    )
    assert_status(foreign, "PLANNED")

    validate_error(
        api.create_integration_task(
            f.integration_task_payload(
                deal_one,
                workstream="SYSTEMS",
                title="Depend on another deal's crew",
                crew_code="CREW-D1",
                planned_start_date="2026-09-01",
                planned_end_date="2026-09-10",
                depends_on_task_id=foreign["id"],
            ),
            INTEGRATION_MANAGER,
        ),
        ERR_DEPENDENCY_NOT_IN_SAME_DEAL,
    )
    rows, meta = validate_paginated(
        api.list_integration_tasks(INTEGRATION_MANAGER, {"restructuring_id": deal_one})
    )
    assert rows == [], f"the refused task must not be persisted, got {rows!r}"
    assert meta["total_count"] == 0, f"deal one holds no tasks yet, got {meta}"

    task_a = fx.create_task(
        api,
        deal_one,
        workstream="STAFFING",
        title="Harmonise the two staff handbooks",
        crew_code="CREW-A1",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-10",
    )
    task_b = fx.create_task(
        api,
        deal_one,
        workstream="BRANDING",
        title="Retire the target's public identity",
        crew_code="CREW-C1",
        planned_start_date="2026-09-11",
        planned_end_date="2026-09-20",
        depends_on_task_id=task_a["id"],
    )
    assert_status(task_a, "PLANNED")
    assert_status(task_b, "PLANNED")
    assert_null(task_b, "held_reason")
    assert_field(task_b, "depends_on_task_id", task_a["id"])

    validate_error(
        api.start_integration_task(task_b["id"], f.start_task_payload(), INTEGRATION_MANAGER),
        ERR_DEPENDENCY_NOT_COMPLETE,
    )
    held_back = validate_success(api.get_integration_task(task_b["id"], INTEGRATION_MANAGER))
    assert_status(held_back, "PLANNED")
    assert_null(held_back, "started_at")
    assert_version_is(held_back, 1, "task_b")

    started = validate_success(
        api.start_integration_task(task_a["id"], f.start_task_payload(), INTEGRATION_MANAGER)
    )
    assert_status(started, "IN_PROGRESS")
    assert_field(started, "started_at", "2026-08-01T00:00:00.000Z")
    completed = validate_success(
        api.complete_integration_task(task_a["id"], f.complete_task_payload(), INTEGRATION_MANAGER)
    )
    assert_status(completed, "COMPLETE")
    assert_field(completed, "completed_at", "2026-08-01T00:00:00.000Z")

    released = validate_success(
        api.start_integration_task(task_b["id"], f.start_task_payload(), INTEGRATION_MANAGER)
    )
    assert_status(released, "IN_PROGRESS")
    assert_field(released, "started_at", "2026-08-01T00:00:00.000Z")

    untouched = validate_success(api.get_integration_task(foreign["id"], INTEGRATION_MANAGER))
    assert_status(untouched, "PLANNED")
    assert_version_is(untouched, 1, "the other deal's task")


def test_completing_a_task_that_was_never_started_is_rejected(api):
    """A PLANNED task cannot be completed, and it cannot be started either while the deal is
    still only STRUCTURE_SELECTED, so the two refusals name different rows.

    PRD 3.8 permits task creation while the deal is STRUCTURE_SELECTED, BOARD_APPROVAL,
    REGULATORY_REVIEW or INTEGRATION, and states that completion applies to an IN_PROGRESS
    task, so a task that never started is refused with ERR_INVALID_TASK_STATE. Starting is
    ladder-ordered: the task must be PLANNED — which this one is — and then "the deal must
    have reached INTEGRATION, else ERR_INVALID_DEAL_STATE — planning may run early, but
    execution may not." PRD 3.8 creates a non-continuity task in PLANNED with held_reason
    null and both started_at and completed_at null, and PRD 2.4 starts every mutable entity
    at version 1; a refused request changes none of that.

    Design: Corner/errors/completing_a_task_that_was_never_started_is_rejected
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    assert_status(ctx["deal"], "STRUCTURE_SELECTED")

    task = fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        title="Map both payroll calendars",
        crew_code="CREW-A1",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-10",
    )
    assert_status(task, "PLANNED")
    assert_null(task, "held_reason")

    validate_error(
        api.complete_integration_task(task["id"], f.complete_task_payload(), INTEGRATION_MANAGER),
        ERR_INVALID_TASK_STATE,
    )
    validate_error(
        api.start_integration_task(task["id"], f.start_task_payload(), INTEGRATION_MANAGER),
        ERR_INVALID_DEAL_STATE,
    )

    read_back = validate_success(api.get_integration_task(task["id"], INTEGRATION_MANAGER))
    assert_status(read_back, "PLANNED")
    assert_null(read_back, "started_at")
    assert_null(read_back, "completed_at")
    assert_version_is(read_back, 1, "task")
    assert_status(fx.read_deal(api, deal_id), "STRUCTURE_SELECTED")


def test_a_continuity_decision_on_a_third_party_program_is_rejected(api):
    """A programme belonging to an organization that is not a party to the deal is refused on
    the asset-ownership ground, not as a missing programme.

    PRD 3.8 states that on a continuity decision the programme "must currently be ACTIVE, its
    org_id must be one of the deal's two party organizations — otherwise
    ERR_PROGRAM_NOT_DEAL_PARTY_ASSET". PRD 2.7 places the programme-existence check at rule 6
    and this ownership check at rule 27, so a programme that plainly exists but belongs to a
    stranger draws the ownership refusal rather than a not-found. A TRANSFER disposition on a
    party's own programme moves it ACTIVE to PLANNED_TRANSFER and raises its version by one,
    while PRD 3.1 leaves transferred_to_org_id null until the deal is consummated.

    Design: Corner/errors/a_continuity_decision_on_a_third_party_program_is_rejected
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]
    org_c = fx.create_organization(api, fx.ORG_C)["id"]

    prog_c = fx.create_program(
        api,
        org_c,
        name="Delta Saturday Mentors",
        service_category="YOUTH_MENTORING",
        county_code="CA-ALAMEDA",
        annual_expense_cents=6000000,
        clients_served=180,
    )
    prog_a = fx.create_program(
        api,
        org_a,
        name="Riverside Mentor Match",
        service_category="YOUTH_MENTORING",
        county_code="CA-ALAMEDA",
        annual_expense_cents=9000000,
        clients_served=240,
    )

    validate_error(
        api.continuity_decision(
            prog_c["id"],
            f.continuity_decision_payload(deal_id, disposition="TRANSFER"),
            INTEGRATION_MANAGER,
        ),
        ERR_PROGRAM_NOT_DEAL_PARTY_ASSET,
    )

    rows, meta = validate_paginated(api.list_organization_programs(org_c, PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"the stranger still owns exactly one programme, got {meta}"
    untouched = find_by_id(rows, prog_c["id"])
    assert untouched is not None, "the stranger's programme must remain listed"
    assert_field(untouched, "continuity_status", "ACTIVE")
    assert_version_is(untouched, 1, "prog_c")

    decided = validate_success(
        api.continuity_decision(
            prog_a["id"],
            f.continuity_decision_payload(deal_id, disposition="TRANSFER"),
            INTEGRATION_MANAGER,
        )
    )
    assert_field(decided, "continuity_status", "PLANNED_TRANSFER")
    assert_null(decided, "transferred_to_org_id")
    assert_version_is(decided, 2, "prog_a")


def test_filing_a_petition_before_asking_a_reachable_donor_is_rejected(api):
    """A court petition straight from HELD is admitted only where the donor is unreachable and
    the pleaded basis says so, and the resulting judicial authority cannot then be spent on a
    declared basis of donor consent.

    PRD 3.6 states that "filing straight from HELD is permitted only where
    donor_of_record_reachable is false *and* the pleaded petition_basis is
    DONOR_UNREACHABLE; a reachable donor must be asked before a court is, and a violation of
    either condition answers ERR_DONOR_CONSENT_REQUIRED". On success the fund moves to
    PETITION_FILED and stamps petition_filed_at from the logical clock, which PRD 2.2 fixes at
    2026-08-01T00:00:00Z. A GRANTED court decision moves the fund to MODIFIED and, for a
    TEMP_RESTRICTED fund, "the judicial rule releases the entire fund value, the same as
    consent would". At transfer "the declared basis must match the branch the fund actually
    travelled: DONOR_CONSENT requires the fund to be in CONSENT_GRANTED", and between the two
    refusals the PRD distinguishes them explicitly — ERR_DONOR_CONSENT_REQUIRED "names the
    missing authority", ERR_INVALID_FUND_STATE "the exhausted row" — and a MODIFIED fund is
    not exhausted, it simply holds no donor consent. On the lawful basis the transfer writes
    transferred_amount_cents equal to the fixed transferable amount, retained_amount_cents as
    the remainder and the counterparty as recipient, and PRD 2.8 leaves the party-pair
    restricted corpus unchanged. PRD 3.6 then leaves the posture RESTRICTED_PENDING while one
    party fund is still unresolved.

    Design: Corner/errors/filing_a_petition_before_asking_a_reachable_donor_is_rejected
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    fund_r = fx.create_fund(
        api,
        org_a,
        fund_name="Nakamura Family Program Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        historic_dollar_value_cents=0,
        restriction_purpose_code="AF-AFTERSCHOOL",
        donor_of_record_reachable=True,
    )
    fund_u = fx.create_fund(
        api,
        org_a,
        fund_name="Anonymous Scholarship Bequest",
        fund_type="TEMP_RESTRICTED",
        principal_cents=30000000,
        accumulated_appreciation_cents=0,
        historic_dollar_value_cents=0,
        restriction_purpose_code="SC-SCHOLARSHIPS",
        donor_of_record_reachable=False,
    )

    validate_error(
        api.file_petition(
            fund_r["id"],
            f.file_petition_payload(petition_basis="DONOR_UNREACHABLE"),
            TRUST_COUNSEL,
        ),
        ERR_DONOR_CONSENT_REQUIRED,
    )
    still_held = validate_success(api.get_restricted_fund(fund_r["id"], TRUST_COUNSEL))
    assert_field(still_held, "transfer_status", "HELD")
    assert_version_is(still_held, 1, "fund_r")

    validate_error(
        api.file_petition(
            fund_u["id"], f.file_petition_payload(petition_basis="IMPRACTICABLE"), TRUST_COUNSEL
        ),
        ERR_DONOR_CONSENT_REQUIRED,
    )
    assert_field(
        validate_success(api.get_restricted_fund(fund_u["id"], TRUST_COUNSEL)),
        "transfer_status",
        "HELD",
    )

    petitioned = validate_success(
        api.file_petition(
            fund_u["id"],
            f.file_petition_payload(petition_basis="DONOR_UNREACHABLE"),
            TRUST_COUNSEL,
        )
    )
    assert_field(petitioned, "transfer_status", "PETITION_FILED")
    assert_field(petitioned, "petition_filed_at", "2026-08-01T00:00:00.000Z")

    modified = validate_success(
        api.record_court_decision(
            fund_u["id"],
            f.court_decision_payload("GRANTED", modified_purpose_code="YS-YOUTHSERVICES"),
            TRUST_COUNSEL,
        )
    )
    assert_field(modified, "transfer_status", "MODIFIED")
    assert_money_equals(modified["transferable_amount_cents"], 30000000, "transferable_amount_cents")

    validate_error(
        api.transfer_restricted_fund(
            fund_u["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
        ),
        ERR_DONOR_CONSENT_REQUIRED,
    )
    assert_field(
        validate_success(api.get_restricted_fund(fund_u["id"], TRUST_COUNSEL)),
        "transfer_status",
        "MODIFIED",
    )

    moved = validate_success(
        api.transfer_restricted_fund(
            fund_u["id"], f.transfer_payload(deal_id, "JUDICIAL_MODIFICATION"), TRUST_COUNSEL
        )
    )
    assert_field(moved, "transfer_status", "TRANSFERRED")
    assert_money_equals(moved["transferred_amount_cents"], 30000000, "transferred_amount_cents")
    assert_money_equals(moved["retained_amount_cents"], 0, "retained_amount_cents")
    assert_field(moved, "transferred_to_org_id", org_b)
    assert_field(moved, "transfer_restructuring_id", deal_id)

    holder = validate_success(api.get_organization(org_a, PLATFORM_ADMIN))
    recipient = validate_success(api.get_organization(org_b, PLATFORM_ADMIN))
    assert_money_equals(holder["restricted_corpus_cents"], 62000000, "restricted_corpus_cents")
    assert_money_equals(recipient["restricted_corpus_cents"], 30000000, "restricted_corpus_cents")
    assert (
        holder["restricted_corpus_cents"] + recipient["restricted_corpus_cents"] == 92000000
    ), "the party-pair restricted corpus must be conserved by the transfer"

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "restricted_asset_posture", "RESTRICTED_PENDING")
    assert_field(deal, "unresolved_restricted_fund_count", 1)


def test_a_restructuring_with_a_dissolved_target_is_rejected(api):
    """An organization dissolved by a completed merger can neither be named as the target of a
    fresh deal nor open one itself, while the survivor remains free to restructure again.

    PRD 3.1 states that the two organizations "must be different ... and neither may already
    be DISSOLVED, DIVESTED or SUBSIDIARY, since an organization that has been dissolved,
    divested or absorbed cannot restructure again; those cases answer
    ERR_ORGANIZATION_NOT_ELIGIBLE" — and the rule bars the ineligible party on either side of
    the request. PRD 3.8 writes those roles at the close: "a MERGER makes the initiator
    SURVIVOR and the target DISSOLVED", and sets parent_org_id only on the PARENT_SUBSIDIARY
    route. PRD 3.1 also fixes the shape of a newly opened deal at EXPLORATORY with round_no 1,
    combined_board_seats and reserved_seat_pool 0, unrestricted_transfer_value_cents 0,
    restricted_asset_posture NOT_ASSESSED, structure_type null and version 1, and PRD 2.3
    counts only matching rows in a filtered listing.

    Design: Corner/errors/a_restructuring_with_a_dissolved_target_is_rejected
    """
    ctx = fx.setup_deal_integration(api)
    deal_id = ctx["deal"]["id"]
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    closed = validate_success(
        api.consummate(deal_id, f.consummate_payload(), make_strategy_officer_headers(org_a))
    )
    assert_status(closed, "CONSUMMATED")

    survivor = validate_success(api.get_organization(org_a, PLATFORM_ADMIN))
    dissolved = validate_success(api.get_organization(org_b, PLATFORM_ADMIN))
    assert_field(survivor, "affiliation_role", "SURVIVOR")
    assert_field(dissolved, "affiliation_role", "DISSOLVED")
    assert_null(survivor, "parent_org_id")
    assert_null(dissolved, "parent_org_id")

    org_c = fx.create_organization(api, fx.ORG_C)["id"]

    validate_error(
        api.create_restructuring(
            f.restructuring_payload(org_c, org_b), make_strategy_officer_headers(org_c)
        ),
        ERR_ORGANIZATION_NOT_ELIGIBLE,
    )
    validate_error(
        api.create_restructuring(
            f.restructuring_payload(org_b, org_c), make_strategy_officer_headers(org_b)
        ),
        ERR_ORGANIZATION_NOT_ELIGIBLE,
    )

    fresh = validate_success(
        api.create_restructuring(
            f.restructuring_payload(org_a, org_c), make_strategy_officer_headers(org_a)
        ),
        201,
    )
    assert_status(fresh, "EXPLORATORY")
    assert_field(fresh, "round_no", 1)
    assert_field(fresh, "combined_board_seats", 0)
    assert_field(fresh, "reserved_seat_pool", 0)
    assert_money_equals(
        fresh["unrestricted_transfer_value_cents"], 0, "unrestricted_transfer_value_cents"
    )
    assert_field(fresh, "restricted_asset_posture", "NOT_ASSESSED")
    assert_null(fresh, "structure_type")
    assert_version_is(fresh, 1, "the fresh deal")

    rows, meta = validate_paginated(
        api.list_restructurings(PLATFORM_ADMIN, {"initiator_org_id": org_b})
    )
    assert rows == [], f"a dissolved organization initiates nothing, got {rows!r}"
    assert meta["total_count"] == 0, f"filtered total_count expected 0, got {meta}"
