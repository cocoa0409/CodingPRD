"""Who may call, whose rows they may touch, and which decisions they may not take twice."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_ids_exactly,
    assert_null_fields,
    assert_page,
    assert_score,
)
from test_helpers.constants import (
    CANONICAL_JOB_ESTIMATE,
    ROUND_BID_RATES,
    ROUND_BID_UNIT_COST,
    U_FUNDING_1,
    U_FUNDING_2,
    U_PROCUREMENT,
)

RIVAL_BID_RATES = {
    "cement_per_sack_cents": 5000,
    "rig_day_rate_cents": 900000,
    "casing_per_ft_cents": 1500,
    "mobilization_fee_cents": 2600000,
}
RIVAL_BID_UNIT_COST = 8000000


def test_a_missing_role_an_unknown_role_and_a_missing_user_are_all_unauthenticated(api):
    """Authentication is answered before authorization and before any business rule.

    A request with no role header, a request naming a role the contract never declares,
    and a request omitting the actor identifier on an endpoint that records it all come
    back 401 rather than 403 or 422, and the refused production filing writes nothing.

    PRD: "when `X-User-Role` is absent or empty the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401), and the same error is returned when `X-User-Role`
    names anything other than one of the eight declared roles, or when `X-User-ID` is
    missing on an endpoint whose rules reference the acting user." ... "as
    `reported_by_user_id` on a production record"

    Design: Corner/rbac/missing_or_unknown_role_and_missing_user_are_unauthenticated
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    well = fx.make_well(api, operator["id"])

    validate_error(
        api.get_well(well["id"], users.headers_without_role("u_admin")),
        e.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_well(well["id"], users.headers_with_unknown_role("u_admin")),
        e.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.create_production_record(
            well["id"],
            f.production_payload("2026-07", oil_bbl=1.0, gas_mcf=0),
            users.headers_without_user("Operator"),
        ),
        e.ERR_UNAUTHENTICATED,
        401,
    )

    assert_page(
        api.list_production_records(well["id"], users.ADMIN), 0, expected_total=0
    )
    unchanged = fx.read_well(api, well["id"])
    assert_null_fields(unchanged, "last_production_month")
    assert_score(unchanged["cumulative_boe_60mo"], 0.00, "cumulative_boe_60mo")


def test_an_exclusive_operation_is_refused_to_every_role_but_its_own(api):
    """The most powerful role is not a superset of the specialised ones.

    The administrator who registers operators and takes enforcement action is still
    refused the determination decision, the authoring inspector is refused it too, and the
    funding officer cannot register an operator; the rightful reviewer then succeeds on the
    very same row.

    PRD: "Once authentication succeeds, the role is checked against the set of roles
    authorized for the requested endpoint (see the table in §4); a role outside that set is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)." ... "It cannot decide orphan
    determinations, cannot evaluate or award bids, and cannot run funding commitments or
    disburse allocations." ... "It cannot decide the determinations it authors"

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    operator = fx.make_unbonded_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
    )
    well = fx.make_well(api, operator["id"])
    determination = fx.open_determination(api, well["id"])
    fx.submit_determination(api, determination["id"])

    decision = f.determination_decision_payload("CONFIRM", "criteria satisfied")
    validate_error(
        api.decide_orphan_determination(determination["id"], decision, users.ADMIN),
        e.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.decide_orphan_determination(determination["id"], decision, users.INSPECTOR),
        e.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_operator(
            f.operator_payload(
                name="Rogue Registrar Co",
                region_code="WY",
                financial_assurance_tier="INDIVIDUAL",
                bond_amount_cents=100000,
            ),
            users.FUNDING,
        ),
        e.ERR_UNAUTHORIZED,
        403,
    )

    still_submitted = fx.read_determination(api, determination["id"])
    assert_fields(still_submitted, status="SUBMITTED")
    assert_null_fields(still_submitted, "decided_at", "decided_by_user_id")
    assert_fields(fx.read_well(api, well["id"]), status="ORPHAN_CANDIDATE")
    registered = assert_page(api.list_operators(users.ADMIN), 1, expected_total=1)
    assert_ids_exactly(registered, [operator["id"]])

    confirmed = validate_success(
        api.decide_orphan_determination(determination["id"], decision, users.REVIEWER),
        200,
    )
    assert_fields(confirmed, status="CONFIRMED")
    assert_fields(fx.read_well(api, well["id"]), status="ORPHAN_CONFIRMED")


def test_an_operator_caller_reads_and_writes_only_its_own_wells(api):
    """The entity-backed operator is scoped by the id it acts under.

    The same single-well fetch that answers 200 for the owning operator answers 403 for the
    other one, the list read is narrowed to the caller's own inventory rather than refused,
    and the production filing lands only on the well the caller actually holds.

    PRD: "When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator`
    row; ownership checks on any resource that references an `Operator` compare the
    resource's operator foreign-key field to `X-User-ID`." ... "Five operations enforce
    ownership beyond the role check, and all five report `ERR_NOT_RESOURCE_OWNER` (HTTP
    403): the well list, the single-well fetch, the bid list, the single-bid fetch, and the
    filing of a plugging field report." ... "An `Operator`- or `Contractor`-scoped caller
    reaching outside its own data fails with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/entity_backed_callers_are_scoped_to_their_own_rows
    """
    first = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    second = fx.make_operator(
        api,
        name="Shoshone Shell Co",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    foreign_well = fx.make_well(api, first["id"])
    own_well = fx.make_well(api, second["id"])
    caller = users.make_operator_headers(second["id"])

    mine = validate_success(api.get_well(own_well["id"], caller), 200)
    assert_fields(mine, id=own_well["id"], operator_id=second["id"])

    validate_error(
        api.get_well(foreign_well["id"], caller), e.ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.create_production_record(
            foreign_well["id"],
            f.production_payload("2026-07", oil_bbl=5.0, gas_mcf=0),
            caller,
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    assert_null_fields(fx.read_well(api, foreign_well["id"]), "last_production_month")

    narrowed = assert_page(api.list_wells(caller), 1, expected_total=1)
    assert_ids_exactly(narrowed, [own_well["id"]])

    filed = validate_success(
        api.create_production_record(
            own_well["id"],
            f.production_payload("2026-07", oil_bbl=5.0, gas_mcf=0),
            caller,
        ),
        201,
    )
    assert_fields(filed, well_id=own_well["id"], reported_by_user_id=second["id"])

    updated_well = fx.read_well(api, own_well["id"])
    assert_fields(updated_well, last_production_month="2026-07")
    assert_score(updated_well["cumulative_boe_60mo"], 5.00, "cumulative_boe_60mo")
    assert_page(
        api.list_production_records(foreign_well["id"], users.ADMIN), 0, expected_total=0
    )


def test_a_contractor_caller_cannot_reach_another_contractors_bid(api):
    """The second entity-backed role is scoped on a different entity entirely.

    A contractor holding its own id is refused both the read of the rival's bid and a
    submission in the rival's name, its own bid list shows one row, and the solicitation
    both of them bid into stays readable because no contractor owns it.

    PRD: "When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting
    `Contractor` row; ownership checks on any resource that references a `Contractor`
    compare the resource's contractor foreign-key field to `X-User-ID`." ... "When the
    caller is acting in the `Contractor` role, `contractor_id` must equal its own
    `X-User-ID`." ... "An `Operator`- or `Contractor`-scoped caller reaching outside its own
    data fails with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/contractor_callers_cannot_read_another_contractors_bid
    """
    mine = fx.make_contractor(api, name="Bighorn Plugging")
    rival = fx.make_contractor(
        api, name="Laramie Well Services", performance_score=74
    )
    solicitation = fx.make_open_solicitation(api)
    caller = users.make_contractor_headers(mine["id"])
    rival_caller = users.make_contractor_headers(rival["id"])

    own_bid = fx.place_bid(
        api,
        solicitation["id"],
        mine["id"],
        rates=ROUND_BID_RATES,
        headers=caller,
    )
    rival_bid = fx.place_bid(
        api,
        solicitation["id"],
        rival["id"],
        rates=RIVAL_BID_RATES,
        technical_score=80,
        headers=rival_caller,
    )
    assert_cents(
        own_bid["evaluated_unit_cost_cents"],
        ROUND_BID_UNIT_COST,
        "own evaluated_unit_cost_cents",
    )
    assert_cents(
        rival_bid["evaluated_unit_cost_cents"],
        RIVAL_BID_UNIT_COST,
        "rival evaluated_unit_cost_cents",
    )

    validate_error(
        api.get_bid(rival_bid["id"], caller), e.ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.create_bid(
            solicitation["id"],
            f.bid_payload(
                rival["id"],
                rates={
                    "cement_per_sack_cents": 3000,
                    "rig_day_rate_cents": 700000,
                    "casing_per_ft_cents": 1000,
                    "mobilization_fee_cents": 2000000,
                },
                technical_score=95,
            ),
            caller,
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    every_bid = assert_page(
        api.list_bids(users.PROCUREMENT, {"solicitation_id": solicitation["id"]}),
        2,
        expected_total=2,
    )
    assert {row["id"] for row in every_bid} == {own_bid["id"], rival_bid["id"]}, (
        "the refused submission created a third bid: %r" % (every_bid,)
    )

    scoped = assert_page(
        api.list_bids(caller, {"solicitation_id": solicitation["id"]}),
        1,
        expected_total=1,
    )
    assert_ids_exactly(scoped, [own_bid["id"]])
    validate_success(api.get_bid(own_bid["id"], caller), 200)
    shared = validate_success(api.get_solicitation(solicitation["id"], caller), 200)
    assert_fields(shared, id=solicitation["id"], status="OPEN")


def test_the_officer_who_set_a_decision_up_may_not_take_it(api):
    """Two of the three self-dealing gates, each on a live chain of money.

    The procurement officer who drafted the solicitation is refused the award even while
    holding the award authority role, and the funding officer who committed the allocation
    is refused the disbursement even after the crew has filed its field report; in both
    cases a second person carries the same call through.

    PRD: "Three decisions are barred to the person who set them up, and all three report
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): deciding an orphan determination whose
    `created_by_user_id` equals the acting `X-User-ID`; awarding a solicitation whose
    `created_by_user_id` equals the acting `X-User-ID`; and disbursing a funding allocation
    whose `committed_by_user_id` equals the acting `X-User-ID`." ... "Only an
    `AwardAuthority` awards, only from `EVALUATING`, and never the officer who drafted the
    solicitation - an acting `X-User-ID` equal to the solicitation's `created_by_user_id` is
    rejected with `ERR_SEGREGATION_OF_DUTIES`." ... "the acting `X-User-ID` must differ from
    `committed_by_user_id`, or the call is rejected with `ERR_SEGREGATION_OF_DUTIES`; the
    job's `status` must be `FIELD_REPORTED`, `PLUGGED` or `RECLAIMED`, because work must be
    performed before it is paid for"

    Design: Corner/rbac/segregation_of_duties_blocks_the_creator_from_awarding_and_the_committer_from_disbursing
    """
    operator = fx.make_unbonded_operator(
        api, name="Salt Creek Legacy Holdings", region_code="WY"
    )
    orphan = fx.make_confirmed_orphan_well(api, operator=operator)
    well_id = orphan["well"]["id"]
    fx.authorize_site_access(api, well_id)

    contractor = fx.make_contractor(api, name="Teapot Dome Plugging")
    solicitation = fx.make_open_solicitation(
        api, scope_description="Salt Creek orphan well plugging"
    )
    assert_fields(solicitation, created_by_user_id=U_PROCUREMENT)
    bid = fx.place_bid(api, solicitation["id"], contractor["id"])
    fx.advance_solicitation(api, solicitation["id"], "CLOSE")
    fx.evaluate_bid(api, bid["id"], "RESPONSIVE")

    validate_error(
        api.award_solicitation(solicitation["id"], users.AWARD_AS_PROCUREMENT),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert_fields(fx.read_solicitation(api, solicitation["id"]), status="EVALUATING")
    assert_fields(fx.read_bid(api, bid["id"]), status="RESPONSIVE")
    assert_page(api.list_unit_cost_contracts(users.PROCUREMENT), 0, expected_total=0)

    contract = validate_success(
        api.award_solicitation(solicitation["id"], users.AWARD), 201
    )
    assert_fields(contract, status="ACTIVE", solicitation_id=solicitation["id"])
    assert_fields(fx.read_bid(api, bid["id"]), status="AWARDED")

    job = fx.make_plugging_job(api, well_id, contract["id"])
    assert_cents(
        job["plugging_cost_estimate_cents"],
        CANONICAL_JOB_ESTIMATE,
        "plugging_cost_estimate_cents",
    )
    source = fx.make_funding_source(
        api,
        kind="STATE_FUND",
        name="Wyoming orphan well account",
        authorized_cents=20000000,
    )
    allocations = fx.commit_funding(api, job["id"])
    assert len(allocations) == 1, "expected a single allocation: %r" % (allocations,)
    allocation = allocations[0]
    assert_fields(
        allocation,
        status="COMMITTED",
        source_id=source["id"],
        committed_by_user_id=U_FUNDING_1,
    )
    assert_cents(allocation["allocated_cents"], CANONICAL_JOB_ESTIMATE, "allocated_cents")

    fx.mobilize(api, job["id"])
    assert_fields(fx.file_field_report(api, job["id"]), status="FIELD_REPORTED")

    validate_error(
        api.transition_funding_allocation(
            allocation["id"],
            f.allocation_transition_payload("DISBURSE", CANONICAL_JOB_ESTIMATE),
            users.FUNDING,
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    held = fx.read_allocation(api, allocation["id"])
    assert_fields(held, status="COMMITTED")
    assert_null_fields(held, "disbursed_by_user_id", "disbursed_at")
    assert_cents(held["disbursed_cents"], 0, "allocation disbursed_cents")
    assert_cents(
        fx.read_source(api, source["id"])["disbursed_cents"], 0, "source disbursed_cents"
    )

    paid = fx.transition_allocation(
        api, allocation["id"], "DISBURSE", CANONICAL_JOB_ESTIMATE
    )
    assert_fields(
        paid,
        status="DISBURSED",
        disbursed_by_user_id=U_FUNDING_2,
        disbursed_at="2026-08-01T00:00:00Z",
    )
    assert_cents(paid["disbursed_cents"], CANONICAL_JOB_ESTIMATE, "disbursed_cents")

    settled = fx.read_source(api, source["id"])
    assert_cents(settled["committed_cents"], CANONICAL_JOB_ESTIMATE, "committed_cents")
    assert_cents(settled["disbursed_cents"], CANONICAL_JOB_ESTIMATE, "disbursed_cents")
