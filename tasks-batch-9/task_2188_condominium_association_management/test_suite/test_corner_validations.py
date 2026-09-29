"""Validation breadth probes: ladder priority and the boundary comparisons.

Each test here supplies two or more simultaneous defects, or sits exactly on a
comparison edge, so that the identifier returned pins the ladder position and
the inequality direction rather than merely "something was rejected".
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_instant_equals,
    read_association,
    read_budget,
    read_case,
    read_contract,
    read_meeting,
)
from test_helpers.factories import special_assessment_payload, work_order_payload
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    add_work_order,
    award_and_activate_contract,
    convene,
    create_association,
    draft_budget,
    notice_meeting,
    notice_violation_case,
    patch_association,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import (
    MANAGER_HEADERS,
    NO_AUTH_HEADERS,
    make_director_headers,
    make_owner_headers,
    make_treasurer_headers,
)

HARBOR_POINT = "Harbor Point Condominium Association"
BEACON_HILL = "Beacon Hill Condominium Association"

GHOST_ASSOCIATION_ID = "99999999-9999-4999-8999-999999999999"
GHOST_MEETING_ID = "88888888-8888-4888-8888-888888888888"
GHOST_OWNER_ID = "77777777-7777-4777-8777-777777777777"


def _one_owner_association(api):
    ctx = create_association(api, legal_name=HARBOR_POINT)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    return ctx


def _active_contract_board_of_one(api, *, element: dict, contract: dict):
    """Register one element, board-award and activate one contract over it.

    The board is a single seated director against ``board_quorum_seats`` 1, and
    the contract term opens at the clock epoch so that activation -- which
    demands the clock lie inside the term -- succeeds on the award day.
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_element(ctx, "el1", **element)
    add_contract(
        ctx,
        "ct1",
        "el1",
        insurance_cert_expires_at="2027-06-30T00:00:00Z",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-06-30T00:00:00Z",
        **contract,
    )
    schedule_meeting(
        ctx, "mtg_ca", ["CONTRACT_AWARD"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z"
    )
    notice_meeting(ctx, "mtg_ca")
    set_clock(api, "2026-08-05T10:00:00Z")
    convene(ctx, "mtg_ca", attending=("d1",))
    award_and_activate_contract(ctx, "ct1", "mtg_ca", voters=(("d1", "101"),))
    return ctx


# ======================================================================
# Identity and role rungs beat everything below them
# ======================================================================
def test_a_headerless_write_is_unauthenticated_before_any_body_inspection(api):
    """Three defects at once, and only the first rung may answer.

    The body names an owner that does not exist and carries an out-of-range
    `interest_bp` and `heated_sqft`, but the request has no identity headers at
    all, so rung 1 short-circuits and neither the 404 nor the 422 may leak.

    PRD 2.9: "Requests are validated in a single fixed order, and the **first**
    failing check determines the response."
    PRD 2.9: "Headers present and `X-User-Role` is one of the seven declared
    roles -- otherwise `ERR_UNAUTHENTICATED`, on every endpoint."
    PRD 2.9: "Body-supplied foreign keys exist, on every write endpoint that
    accepts them -- otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND`."
    PRD 2.9: "Field types, enum membership, and numeric ranges are valid --
    `interest_bp` between 1 and 10000 inclusive, `heated_sqft` at least 1,
    `installment_count` between 1 and 24 inclusive, `amount_cents` non-zero, a
    payment's `amount_cents` strictly greater than 0, `fiscal_year` between 2020
    and 2100 inclusive, `limit` between 1 and 100 inclusive, `offset` at least 0
    -- otherwise `ERR_VALIDATION`."

    Design: Corner/validations/missing_x_user_header_returns_unauthenticated_before_fk_and_range_checks
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)

    assert "X-User-ID" not in NO_AUTH_HEADERS
    assert "X-User-Role" not in NO_AUTH_HEADERS
    rejected = api.create_unit(
        ctx.association_id,
        {
            "current_owner_id": "11111111-1111-4111-8111-111111111111",
            "unit_label": "101",
            "interest_bp": 0,
            "heated_sqft": 0,
        },
        NO_AUTH_HEADERS,
    )
    error = validate_error(rejected, "ERR_UNAUTHENTICATED", 401)
    assert rejected.json()["response_type"] == "error"
    assert error["error_id"] == "ERR_UNAUTHENTICATED"

    _units, meta = validate_paginated(
        api.list_units(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    assert meta["total_count"] == 0


def test_an_unseated_director_is_unrecognized_before_the_state_hop_is_judged(api):
    """Actor recognition outranks transition legality.

    `DRAFT → DRAFT` is not a defined return-to-draft leg, so the call is doubly
    wrong; because the acting owner is recorded as a `DIRECTOR` who is not
    seated, rung 3 answers first and the budget state is never consulted.

    PRD 2.9: "For the entity-backed roles `UnitOwner`, `BoardDirector`, and
    `BoardTreasurer`, `X-User-ID` resolves to an existing owner row, and for
    `BoardDirector` or `BoardTreasurer` that owner's `board_role` is `DIRECTOR`,
    `PRESIDENT`, or `TREASURER` and `is_seated` is true -- otherwise
    `ERR_ACTOR_NOT_RECOGNIZED`."
    PRD 2.9: "The target resource is in a state from which the requested
    transition is defined -- otherwise `ERR_INVALID_STATE_TRANSITION`, on every
    action endpoint, except where a more specific identifier is declared:
    `ERR_INVALID_BUDGET_STATE`, `ERR_INVALID_CONTRACT_STATE`,
    `ERR_INVALID_WORK_ORDER_STATE`, `ERR_INVALID_CLAIM_STATE`,
    `ERR_INVALID_CERTIFICATE_STATE`, `ERR_INVALID_MEETING_STATE`, and
    `ERR_INVALID_BALLOT_STATE` are used for their respective entities."
    PRD 3.2: "The cycle is genuinely cyclic: a board may push a budget back to
    `DRAFT` from `PROPOSED`, from `NOTICED`, or from `REJECTED`, and each return
    increments `revision_round`, which starts at 0."

    Design: Corner/validations/unseated_director_returns_actor_not_recognized_before_the_state_check
    """
    ctx = _one_owner_association(api)
    unseated_id = add_owner(
        ctx,
        "hal",
        full_name="Hal Mercer",
        email="hal@example.test",
        board_role="DIRECTOR",
        is_seated=False,
    )
    add_unit(ctx, "101", "o1", 10_000)
    budget = draft_budget(ctx)

    rejected = api.return_budget_to_draft(
        budget["id"], make_director_headers(unseated_id)
    )
    error = validate_error(rejected, "ERR_ACTOR_NOT_RECOGNIZED", 403)
    assert error["error_id"] != "ERR_INVALID_BUDGET_STATE"

    still_draft = read_budget(api, budget["id"], MANAGER_HEADERS)
    assert still_draft["status"] == "DRAFT"
    assert still_draft["revision_round"] == 0


# ======================================================================
# Path resolution, then body keys, then ranges
# ======================================================================
def test_an_unknown_path_association_answers_before_the_unknown_body_meeting(api):
    """Two 404s compete and only the path one is correct.

    Both the association in the URL and the ratification meeting in the body are
    fictional; rung 4 resolves the path first, so the identifier must name the
    association and not the generic referenced-entity failure.

    PRD 2.9: "This ordering is normative: when two checks would both fail, the
    lower-numbered one wins, and a test that supplies two simultaneous defects
    expects the earlier error identifier."
    PRD 2.9: "Path resources exist, resolved left to right, on every endpoint
    that has path parameters -- otherwise the matching not-found identifier from
    §2.5."
    PRD 2.9: "Body-supplied foreign keys exist, on every write endpoint that
    accepts them -- otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND`."

    Design: Corner/validations/unknown_association_in_the_path_beats_the_unknown_meeting_reference
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    live_version = ctx.association_version()

    rejected = api.create_budget(
        GHOST_ASSOCIATION_ID,
        {
            "fiscal_year": 2026,
            "operating_total_cents": 12_000_000,
            "reserve_contribution_cents": 1_200_000,
            "ratification_meeting_id": GHOST_MEETING_ID,
            "expected_association_version": live_version,
        },
        MANAGER_HEADERS,
    )
    error = validate_error(rejected, "ERR_ASSOCIATION_NOT_FOUND", 404)
    assert error["error_id"] != "ERR_REFERENCED_ENTITY_NOT_FOUND"

    _budgets, meta = validate_paginated(
        api.list_budgets(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    assert meta["total_count"] == 0


def test_an_unknown_owner_reference_answers_before_the_interest_range(api):
    """A dangling body key is a 404 even when the numbers are also invalid.

    `interest_bp` 0 and `heated_sqft` 0 are both outside their ranges, but the
    owner reference is checked one rung earlier, so the single answer is the
    referenced-entity 404 and the association's derived interest stays untouched.

    PRD 2.9: "Body-supplied foreign keys exist, on every write endpoint that
    accepts them -- otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND`."
    PRD 2.9: "Field types, enum membership, and numeric ranges are valid --
    `interest_bp` between 1 and 10000 inclusive, `heated_sqft` at least 1,
    `installment_count` between 1 and 24 inclusive, `amount_cents` non-zero, a
    payment's `amount_cents` strictly greater than 0, `fiscal_year` between 2020
    and 2100 inclusive, `limit` between 1 and 100 inclusive, `offset` at least 0
    -- otherwise `ERR_VALIDATION`."
    PRD 2.10: "At registration the derived and custodial figures start from
    zero: `total_interest_bp` is 0, `operating_cash_cents` is 0,
    `reserve_balance_cents` is 0, `reserve_designated_cents` is 0,
    `restricted_sa_cash_cents` is 0, and `version` is 1."

    Design: Corner/validations/unknown_owner_reference_beats_the_interest_bp_range_error
    """
    ctx = _one_owner_association(api)

    rejected = api.create_unit(
        ctx.association_id,
        {
            "current_owner_id": GHOST_OWNER_ID,
            "unit_label": "101",
            "interest_bp": 0,
            "heated_sqft": 0,
        },
        MANAGER_HEADERS,
    )
    error = validate_error(rejected, "ERR_REFERENCED_ENTITY_NOT_FOUND", 404)
    assert error["error_id"] != "ERR_VALIDATION"

    _units, meta = validate_paginated(
        api.list_units(MANAGER_HEADERS, params={"association_id": ctx.association_id})
    )
    assert meta["total_count"] == 0
    assert read_association(api, ctx.association_id, MANAGER_HEADERS)[
        "total_interest_bp"
    ] == 0


def test_an_out_of_range_installment_count_answers_before_the_stale_version(api):
    """Field ranges outrank the concurrency guard on the same request.

    The captured association version is genuinely stale and `installment_count`
    25 is genuinely out of range; rung 6 precedes rung 9, so the answer is the
    422, and only once the count is legal does the same stale token surface the
    412.

    PRD 2.9: "Field types, enum membership, and numeric ranges are valid --
    `interest_bp` between 1 and 10000 inclusive, `heated_sqft` at least 1,
    `installment_count` between 1 and 24 inclusive, `amount_cents` non-zero, a
    payment's `amount_cents` strictly greater than 0, `fiscal_year` between 2020
    and 2100 inclusive, `limit` between 1 and 100 inclusive, `offset` at least 0
    -- otherwise `ERR_VALIDATION`."
    PRD 2.9: "The optimistic-concurrency guard from §2.6, on exactly three
    endpoints: budget creation with `expected_association_version` yielding
    `ERR_STALE_ASSOCIATION_VERSION`, resale-certificate request creation with
    `expected_unit_version` yielding `ERR_STALE_UNIT_VERSION`, and work-order
    creation with `expected_contract_version` yielding
    `ERR_STALE_CONTRACT_VERSION`."
    PRD 2.9: "Special-assessment creation carries
    `expected_association_version` under the same association rule."
    PRD 2.10: "Any such revision increments `Association.version` by 1, which
    invalidates any `expected_association_version` a client captured earlier."

    Design: Corner/validations/installment_count_out_of_range_beats_the_stale_association_version
    """
    ctx = _one_owner_association(api)
    treasurer_id = add_owner(
        ctx,
        "tr",
        full_name="Tina Cole",
        email="tina@example.test",
        board_role="TREASURER",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10_000)
    stale_version = ctx.association_version()
    patch_association(ctx, reserve_balance_cents=4_000_000)
    assert ctx.association_version() == stale_version + 1

    treasurer = make_treasurer_headers(treasurer_id)
    out_of_range = special_assessment_payload(
        stale_version,
        purpose="Roof replacement",
        total_amount_cents=4_000_000,
        installment_count=25,
    )
    error = validate_error(
        api.create_special_assessment(ctx.association_id, out_of_range, treasurer),
        "ERR_VALIDATION",
        422,
    )
    assert error["error_id"] != "ERR_STALE_ASSOCIATION_VERSION"

    _rows, meta = validate_paginated(
        api.list_special_assessments(
            MANAGER_HEADERS, params={"association_id": ctx.association_id}
        )
    )
    assert meta["total_count"] == 0

    in_range = dict(out_of_range, installment_count=24)
    validate_error(
        api.create_special_assessment(ctx.association_id, in_range, treasurer),
        "ERR_STALE_ASSOCIATION_VERSION",
        412,
    )


def test_the_interest_sum_check_answers_before_the_reserve_minimum(api):
    """Two 422s on one propose, and the lower rung must win.

    The roster sums to 9000 basis points and the reserve contribution is a
    twelfth of the statutory minimum, so both rung 35 and rung 43 would fail;
    the interest sum answers first, and only after the roster is completed does
    the reserve shortfall become visible.

    PRD 2.9: "The association's units' `interest_bp` sum to exactly 10000 --
    otherwise `ERR_INTEREST_SUM_INVALID`, on budget proposal, budget
    ratification, and ballot opening."
    PRD 2.9: "The reserve contribution meets the statutory minimum share of the
    operating total -- otherwise `ERR_RESERVE_CONTRIBUTION_TOO_LOW`, on budget
    proposal and budget ratification."
    PRD 3.2: "The `reserve_contribution_cents` must be at least the statutory
    minimum, computed as `operating_total_cents` multiplied by
    `reserve_contribution_min_bp` divided by 10000 and rounded half up -- with
    the default of 1000 basis points that is one tenth of the operating total --
    and a shortfall is refused with `ERR_RESERVE_CONTRIBUTION_TOO_LOW`."

    Design: Corner/validations/interest_sum_invalid_beats_reserve_contribution_too_low_on_propose
    """
    ctx = _one_owner_association(api)
    add_unit(ctx, "101", "o1", 9_000)
    budget = draft_budget(ctx, reserve_contribution_cents=100_000)

    error = validate_error(
        api.propose_budget(budget["id"], MANAGER_HEADERS),
        "ERR_INTEREST_SUM_INVALID",
        422,
    )
    assert error["error_id"] != "ERR_RESERVE_CONTRIBUTION_TOO_LOW"
    assert read_budget(api, budget["id"], MANAGER_HEADERS)["status"] == "DRAFT"

    add_owner(ctx, "o2", full_name="Nina Boyd", email="nina@example.test")
    add_unit(ctx, "102", "o2", 1_000)
    assert read_association(api, ctx.association_id, MANAGER_HEADERS)[
        "total_interest_bp"
    ] == 10_000
    validate_error(
        api.propose_budget(budget["id"], MANAGER_HEADERS),
        "ERR_RESERVE_CONTRIBUTION_TOO_LOW",
        422,
    )
    assert read_budget(api, budget["id"], MANAGER_HEADERS)["status"] == "DRAFT"


# ======================================================================
# Data scoping and tenancy
# ======================================================================
def test_a_foreign_owner_reading_a_statement_is_blocked_by_data_not_by_role(api):
    """`UnitOwner` is an authorized role here, so the refusal must be scoped.

    Owner 2 holds a unit of the same association and therefore passes the role
    rung; the statement still belongs to unit 101, so the answer is the
    owner-scoping refusal, while the owner of record and the manager both read
    it successfully.

    PRD 2.9: "Owner scoping: for an owner-scoped operation the acting owner must
    be the target unit's `current_owner_id` -- otherwise `ERR_NOT_UNIT_OWNER`."
    PRD 2.9: "This guards exactly three operations: appealing a fine, casting a
    vote or ballot, and reading a unit statement."
    PRD 3.1: "Separately, an owner statement capability returns the unit's
    per-bucket open balances together with its `oldest_unpaid_age_days`; because
    it is owner-scoped, a `UnitOwner` calling it for a unit they do not own is
    refused with `ERR_NOT_UNIT_OWNER`."

    Design: Corner/validations/foreign_owner_reading_a_unit_statement_returns_not_unit_owner
    """
    ctx = _one_owner_association(api)
    owner2_id = add_owner(ctx, "o2", full_name="Nina Boyd", email="nina@example.test")
    unit1_id = add_unit(ctx, "101", "o1", 5_000)
    add_unit(ctx, "102", "o2", 5_000)
    get_success_data(
        api.create_charge(
            unit1_id,
            {
                "entry_type": "ASSESSMENT",
                "amount_cents": 20_000,
                "due_on": "2026-08-15T00:00:00Z",
                "effective_period": "2026-08",
                "memo": "August assessment",
            },
            MANAGER_HEADERS,
        )
    )

    error = validate_error(
        api.get_unit_statement(unit1_id, make_owner_headers(owner2_id)),
        "ERR_NOT_UNIT_OWNER",
        403,
    )
    assert error["error_id"] != "ERR_ROLE_NOT_PERMITTED"

    own_statement = validate_success(
        api.get_unit_statement(unit1_id, make_owner_headers(ctx.owners["o1"]))
    )
    assert "oldest_unpaid_age_days" in own_statement
    validate_success(api.get_unit_statement(unit1_id, MANAGER_HEADERS))


def test_a_budget_naming_another_associations_meeting_is_a_scope_mismatch(api):
    """The referenced meeting exists, so the failure is tenancy and not lookup.

    Because rung 5 is satisfied by a real meeting id, the only remaining
    objection is that the meeting belongs to a different association, which is
    the 409 tenancy refusal rather than any 404.

    PRD 2.9: "Body-supplied foreign keys exist, on every write endpoint that
    accepts them -- otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND`."
    PRD 2.9: "Every referenced entity belongs to the same association as the
    target -- otherwise `ERR_ASSOCIATION_SCOPE_MISMATCH`, on every write
    endpoint accepting foreign keys."
    PRD 3.3: "Meeting `status` runs through `SCHEDULED`, `NOTICED`,
    `IN_SESSION`, `ADJOURNED`, and `CANCELLED`, starting at `SCHEDULED`, with
    `ADJOURNED` and `CANCELLED` terminal."

    Design: Corner/validations/budget_pointing_at_a_foreign_associations_meeting_returns_scope_mismatch
    """
    ctx_a = _one_owner_association(api)
    add_unit(ctx_a, "101", "o1", 10_000)

    ctx_b = create_association(api, legal_name=BEACON_HILL)
    meeting_b = schedule_meeting(
        ctx_b,
        "mtg_b",
        ["BUDGET_RATIFICATION"],
        "2026-09-15T10:00:00Z",
        "2026-09-15T12:00:00Z",
    )

    validate_error(
        api.create_budget(
            ctx_a.association_id,
            {
                "fiscal_year": 2026,
                "operating_total_cents": 12_000_000,
                "reserve_contribution_cents": 1_200_000,
                "ratification_meeting_id": meeting_b,
                "expected_association_version": ctx_a.association_version(),
            },
            MANAGER_HEADERS,
        ),
        "ERR_ASSOCIATION_SCOPE_MISMATCH",
        409,
    )

    _budgets, meta = validate_paginated(
        api.list_budgets(
            MANAGER_HEADERS, params={"association_id": ctx_a.association_id}
        )
    )
    assert meta["total_count"] == 0
    assert read_meeting(api, meeting_b, MANAGER_HEADERS)["status"] == "SCHEDULED"


# ======================================================================
# Closed intervals, half-open intervals, and inclusive caps
# ======================================================================
def test_a_window_starting_exactly_one_buffer_after_the_last_one_collides(api):
    """The outage buffer is a closed interval, so touching endpoints collide.

    The existing outage ends at 16:00 and the buffer is a full day, so a new
    window opening at 16:00 the next day still touches the widened interval and
    is refused; one hour later it clears, and the contract's committed figure
    only then rises.

    PRD 2.9: "The buffered outage window does not collide with another open
    order on the same element -- otherwise `ERR_ELEMENT_WINDOW_CONFLICT`, on
    work-order creation."
    PRD 3.6: "Concretely, the new order is rejected when its `window_start` is
    at or before an existing order's `window_end` advanced forward by the buffer
    **and** its `window_end` is at or after that existing order's `window_start`
    pushed back by the buffer."
    PRD 3.6: "The comparison is over existing work orders on the same element
    whose `status` is `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`, the intervals are
    closed, and **touching endpoints collide**."
    PRD 3.6: "On success `encumbered_cents` is set to `estimated_cost_cents`,
    the contract's `committed_cents` rises by the same amount, and
    `VendorContract.version` advances by 1."

    Design: Corner/validations/element_window_touching_the_24_hour_buffer_edge_returns_window_conflict
    """
    ctx = _active_contract_board_of_one(
        api,
        element={
            "name": "Passenger Elevator #1",
            "element_class": "ELEVATOR",
            "replacement_cost_cents": 30_000_000,
            "useful_life_years": 50,
            "effective_age_years": 25,
        },
        contract={"vendor_name": "Summit Elevator Co", "contract_cap_cents": 5_000_000},
    )
    contract_id = ctx.contracts["ct1"]
    add_work_order(
        ctx,
        "ct1",
        "el1",
        scope="Governor inspection",
        window_start="2026-09-10T08:00:00Z",
        window_end="2026-09-10T16:00:00Z",
        estimated_cost_cents=400_000,
    )

    touching = work_order_payload(
        contract_id,
        ctx.elements["el1"],
        ctx.contract_version("ct1"),
        scope="Door operator swap",
        window_start="2026-09-11T16:00:00Z",
        window_end="2026-09-11T20:00:00Z",
        estimated_cost_cents=300_000,
    )
    validate_error(
        api.create_work_order(touching, MANAGER_HEADERS),
        "ERR_ELEMENT_WINDOW_CONFLICT",
        409,
    )

    _orders, meta = validate_paginated(
        api.list_work_orders(MANAGER_HEADERS, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == 1
    assert read_contract(api, contract_id, MANAGER_HEADERS)["committed_cents"] == 400_000

    clear = work_order_payload(
        contract_id,
        ctx.elements["el1"],
        ctx.contract_version("ct1"),
        scope="Door operator swap",
        window_start="2026-09-11T17:00:00Z",
        window_end="2026-09-11T21:00:00Z",
        estimated_cost_cents=300_000,
    )
    validate_success(api.create_work_order(clear, MANAGER_HEADERS), 201)
    assert read_contract(api, contract_id, MANAGER_HEADERS)["committed_cents"] == 700_000


def test_a_third_case_claiming_a_held_half_open_slot_is_refused(api):
    """Adjacent slots coexist, an identical start does not, and 12:00 is outside.

    Two cases sit at 10:00 and 10:30 on one docket because the slot interval is
    half-open; a third case asking for 10:00 collides, the meeting's exclusive
    end instant is outside the window entirely, and only 11:00 lifts the docket
    count.

    PRD 2.9: "The requested half-open thirty-minute docket slot does not
    intersect an existing docketed slot on the same meeting -- otherwise
    `ERR_HEARING_SLOT_TAKEN`, on hearing docketing."
    PRD 2.9: "`hearing_slot_start` is aligned to a thirty-minute boundary and
    the whole slot lies inside the meeting window -- otherwise
    `ERR_SLOT_OUTSIDE_MEETING`, on hearing docketing."
    PRD 3.8: "The side effects are that `hearing_meeting_id` and
    `hearing_slot_start` are written, `hearing_round` is set to 1, the meeting's
    `hearing_slot_count` rises by 1 with `BoardMeeting.version` advancing by 1,
    and `ViolationCase.version` advances by 1."
    PRD 3.8: "Because the slot interval is half-open, a case starting exactly
    when another case's thirty-minute slot ends does **not** collide."

    Design: Corner/validations/second_case_claiming_the_same_thirty_minute_slot_returns_slot_taken
    """
    ctx = create_association(api, legal_name=HARBOR_POINT, board_quorum_seats=1)
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_owner(
        ctx,
        "d2",
        full_name="Rita Vance",
        email="rita@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 3_334)
    add_unit(ctx, "102", "o1", 3_333)
    add_unit(ctx, "103", "o1", 3_333)
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z"
    )
    case1 = notice_violation_case(ctx, "101", rule_code="R-14-PETS", reporter_label="d2")
    case2 = notice_violation_case(
        ctx, "102", rule_code="R-22-NOISE", reporter_label="d2"
    )
    case3 = notice_violation_case(
        ctx, "103", rule_code="R-31-PARKING", reporter_label="d2"
    )

    set_clock(api, "2026-08-16T00:00:00Z")
    docket_slot = {"hearing_meeting_id": meeting_id}
    get_success_data(
        api.schedule_hearing(
            case1["id"],
            dict(docket_slot, hearing_slot_start="2026-08-20T10:00:00Z"),
            ctx.director("d1"),
        )
    )
    get_success_data(
        api.schedule_hearing(
            case2["id"],
            dict(docket_slot, hearing_slot_start="2026-08-20T10:30:00Z"),
            ctx.director("d1"),
        )
    )

    validate_error(
        api.schedule_hearing(
            case3["id"],
            dict(docket_slot, hearing_slot_start="2026-08-20T10:00:00Z"),
            ctx.director("d1"),
        ),
        "ERR_HEARING_SLOT_TAKEN",
        409,
    )
    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["hearing_slot_count"] == 2
    untouched = read_case(api, case3["id"], MANAGER_HEADERS)
    assert untouched["status"] == "NOTICE_SENT"
    assert untouched["hearing_meeting_id"] is None

    validate_error(
        api.schedule_hearing(
            case3["id"],
            dict(docket_slot, hearing_slot_start="2026-08-20T12:00:00Z"),
            ctx.director("d1"),
        ),
        "ERR_SLOT_OUTSIDE_MEETING",
        422,
    )

    docketed = get_success_data(
        api.schedule_hearing(
            case3["id"],
            dict(docket_slot, hearing_slot_start="2026-08-20T11:00:00Z"),
            ctx.director("d1"),
        )
    )
    assert docketed["status"] == "HEARING_SCHEDULED"
    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["hearing_slot_count"] == 3


def test_an_estimate_one_cent_past_the_contract_cap_is_refused(api):
    """The cap admits equality, so the refusal must be at exactly one cent over.

    Each order is individually affordable against the million-cent
    authorization; only the aggregate matters, so 400001 on top of 600000
    committed is refused while 400000 is admitted and lands exactly on the cap.

    PRD 2.9: "The new encumbrance fits inside the contract cap -- otherwise
    `ERR_CONTRACT_CAP_EXCEEDED`, on work-order creation."
    PRD 3.6: "A new order is admitted only when `estimated_cost_cents` plus the
    contract's current `committed_cents` plus its `invoiced_cents` is less than
    or equal to `contract_cap_cents`."
    PRD 3.6: "Equality is allowed; one cent more is refused with
    `ERR_CONTRACT_CAP_EXCEEDED`."
    PRD 3.6: "On success `encumbered_cents` is set to `estimated_cost_cents`,
    the contract's `committed_cents` rises by the same amount, and
    `VendorContract.version` advances by 1."

    Design: Corner/validations/work_order_one_cent_past_the_contract_cap_is_rejected
    """
    ctx = _active_contract_board_of_one(
        api,
        element={
            "name": "Main Roof",
            "element_class": "ROOF",
            "replacement_cost_cents": 12_000_000,
            "useful_life_years": 40,
            "effective_age_years": 5,
        },
        contract={"vendor_name": "Ridgeline Roofing", "contract_cap_cents": 1_000_000},
    )
    contract_id = ctx.contracts["ct1"]
    add_work_order(
        ctx,
        "ct1",
        "el1",
        scope="Flashing repair",
        window_start="2026-09-10T08:00:00Z",
        window_end="2026-09-10T16:00:00Z",
        estimated_cost_cents=600_000,
    )

    over_by_one = work_order_payload(
        contract_id,
        ctx.elements["el1"],
        ctx.contract_version("ct1"),
        scope="Parapet coating",
        window_start="2026-11-10T08:00:00Z",
        window_end="2026-11-10T16:00:00Z",
        estimated_cost_cents=400_001,
    )
    validate_error(
        api.create_work_order(over_by_one, MANAGER_HEADERS),
        "ERR_CONTRACT_CAP_EXCEEDED",
        409,
    )
    held = read_contract(api, contract_id, MANAGER_HEADERS)
    assert held["committed_cents"] == 600_000
    assert held["invoiced_cents"] == 0
    _orders, meta = validate_paginated(
        api.list_work_orders(MANAGER_HEADERS, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == 1

    exactly_at_cap = dict(over_by_one, estimated_cost_cents=400_000)
    validate_success(api.create_work_order(exactly_at_cap, MANAGER_HEADERS), 201)
    filled = read_contract(api, contract_id, MANAGER_HEADERS)
    assert filled["committed_cents"] == 1_000_000
    assert filled["committed_cents"] + filled["invoiced_cents"] == filled[
        "contract_cap_cents"
    ]


# ======================================================================
# Strict deadlines
# ======================================================================
def test_docketing_at_the_cure_deadline_instant_is_still_too_early(api):
    """The docket gate is a strict inequality on the cure deadline.

    Notice on the first of August with a fourteen-day cure period puts the
    deadline at the fifteenth; the deadline instant itself still belongs to the
    owner, so docketing then is refused and one second later the identical call
    is accepted.

    PRD 2.9: "The cure period has expired before a hearing is docketed, and
    conversely a cure is not recorded after the deadline -- otherwise
    `ERR_CURE_PERIOD_ACTIVE`, on hearing docketing and cure recording."
    PRD 3.8: "It stamps `notice_sent_at` from the logical clock, sets
    `cure_deadline_at` to `notice_sent_at` advanced by `cure_period_days`,
    resolves `prior_case_id` to the most recent qualifying earlier case, and
    advances `ViolationCase.version` by 1."
    PRD 3.8: "From `NOTICE_SENT` the requirements are: the case is
    `NOTICE_SENT`; the logical clock is **strictly after** `cure_deadline_at`,
    since the deadline instant itself still belongs to the owner and a hearing
    docketed at or before it is refused with `ERR_CURE_PERIOD_ACTIVE`; the
    target meeting's `status` is `SCHEDULED` or `NOTICED` and its `agenda_kinds`
    contains `HEARING`, failing which the response is
    `ERR_AGENDA_KIND_MISSING`; the meeting's `hearing_slot_count` is strictly
    below `hearing_docket_capacity`, failing which the response is
    `ERR_HEARING_DOCKET_FULL`; `hearing_slot_start` sits on a thirty-minute
    boundary and the whole thirty-minute slot lies inside the meeting's window,
    which is inclusive of `scheduled_start` and exclusive of `scheduled_end`,
    failing which the response is `ERR_SLOT_OUTSIDE_MEETING`; no other case
    docketed to that meeting occupies the half-open thirty-minute slot beginning
    at `hearing_slot_start`, failing which the response is
    `ERR_HEARING_SLOT_TAKEN`; and at most one other case for the same `unit_id`
    is already docketed to that meeting, so a third case for one unit on one
    docket is refused with `ERR_UNIT_DOCKET_LIMIT`."
    PRD 3.8: "The case is born with `status` `OPEN`, `hearing_round` 0,
    `fine_tier` 0, and `fine_amount_cents` 0; `prior_case_id`,
    `decision_owner_id`, `hearing_meeting_id`, `notice_sent_at`,
    `cure_deadline_at`, `hearing_slot_start`, `fine_entry_id`, and
    `appeal_deadline_at` are all null."

    Design: Corner/validations/docketing_exactly_at_the_cure_deadline_returns_cure_period_active
    """
    ctx = create_association(
        api, legal_name=HARBOR_POINT, board_quorum_seats=1, cure_period_days=14
    )
    add_owner(ctx, "o1", full_name="Owen Pratt", email="owen@example.test")
    add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_owner(
        ctx,
        "d2",
        full_name="Rita Vance",
        email="rita@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    add_unit(ctx, "101", "o1", 10_000)
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["HEARING"], "2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z"
    )
    case = notice_violation_case(ctx, "101", rule_code="R-14-PETS", reporter_label="d2")
    assert_instant_equals(case["cure_deadline_at"], "2026-08-15T00:00:00Z")

    set_clock(api, "2026-08-15T00:00:00Z")
    slot = {
        "hearing_meeting_id": meeting_id,
        "hearing_slot_start": "2026-08-20T10:00:00Z",
    }
    validate_error(
        api.schedule_hearing(case["id"], slot, ctx.director("d1")),
        "ERR_CURE_PERIOD_ACTIVE",
        409,
    )
    still_open = read_case(api, case["id"], MANAGER_HEADERS)
    assert still_open["status"] == "NOTICE_SENT"
    assert_instant_equals(still_open["cure_deadline_at"], "2026-08-15T00:00:00Z")
    assert still_open["hearing_round"] == 0
    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["hearing_slot_count"] == 0

    set_clock(api, "2026-08-15T00:00:01Z")
    docketed = get_success_data(
        api.schedule_hearing(case["id"], slot, ctx.director("d1"))
    )
    assert docketed["status"] == "HEARING_SCHEDULED"
    assert docketed["hearing_round"] == 1


def test_a_ratification_meeting_twenty_nine_days_out_cannot_be_noticed(api):
    """The statutory notice period is measured to the meeting's start.

    A meeting starting on the thirtieth of August is only twenty-nine and a bit
    days away from the first, short of the thirty-day statutory notice, so the
    mailing is refused, the budget keeps its proposed figures, and the meeting
    is not promoted.

    PRD 2.9: "The statutory budget notice period is satisfied -- otherwise
    `ERR_NOTICE_PERIOD_NOT_SATISFIED`, on budget notice mailing and budget
    ratification."
    PRD 3.2: "The budget must be `PROPOSED`; its `ratification_meeting_id` must
    be set; the referenced meeting's `status` must be `SCHEDULED` or `NOTICED`;
    that meeting's `agenda_kinds` must contain `BUDGET_RATIFICATION`, failing
    which the response is `ERR_AGENDA_KIND_MISSING`; and the meeting's
    `scheduled_start` must be at least `budget_notice_days` days after the
    logical clock, failing which the response is
    `ERR_NOTICE_PERIOD_NOT_SATISFIED`."
    PRD 3.2: "With the default of thirty days, a ratification meeting scheduled
    twenty-nine days out cannot be noticed today."
    PRD 3.2: "On success the server computes `assessment_total_cents` as
    `operating_total_cents` plus `reserve_contribution_cents`, computes
    `monthly_assessable_cents` as `assessment_total_cents` divided by 12 and
    rounded half up, and advances `Budget.version` by 1."

    Design: Corner/validations/budget_notice_less_than_thirty_days_before_the_meeting_is_rejected
    """
    ctx = _one_owner_association(api)
    add_unit(ctx, "101", "o1", 10_000)
    meeting_id = schedule_meeting(
        ctx,
        "mtg_early",
        ["BUDGET_RATIFICATION"],
        "2026-08-30T10:00:00Z",
        "2026-08-30T12:00:00Z",
    )
    budget = draft_budget(ctx, ratification_meeting_id=meeting_id)
    get_success_data(api.propose_budget(budget["id"], MANAGER_HEADERS))

    validate_error(
        api.send_budget_notice(budget["id"], MANAGER_HEADERS),
        "ERR_NOTICE_PERIOD_NOT_SATISFIED",
        409,
    )

    unmailed = read_budget(api, budget["id"], MANAGER_HEADERS)
    assert unmailed["status"] == "PROPOSED"
    assert unmailed["notice_sent_at"] is None
    assert unmailed["assessment_total_cents"] == 13_200_000
    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["status"] == "SCHEDULED"


def test_two_seated_directors_and_an_unseated_third_never_reach_quorum(api):
    """Quorum counts seats, not bodies in the room.

    Against the statutory three seats an attendance list of two seated directors
    is short, and adding an unseated director changes nothing because the count
    only includes attendees who are seated with a board role.

    PRD 2.9: "The hosting board meeting has `quorum_met` true -- otherwise
    `ERR_BOARD_QUORUM_NOT_MET`, on meeting convening, budget ratification, and
    hearing decision recording."
    PRD 3.3: "Convening moves it `NOTICED → IN_SESSION` and requires that the
    meeting be `NOTICED`, that the logical clock have reached `scheduled_start`,
    and that the attendance list produce a `seated_director_count` of at least
    `board_quorum_seats`."
    PRD 3.3: "Attendance is supplied as `attending_owner_ids`; the count is the
    number of attending owners whose `is_seated` is true and whose `board_role`
    is not `NONE`."
    PRD 3.3: "A short list refuses the convene with `ERR_BOARD_QUORUM_NOT_MET`;
    with the default of three seats, two attending seated directors are not
    enough."
    PRD 3.3: "On creation `notice_sent_at` is null, `seated_director_count` is
    0, `quorum_met` is false, and `hearing_slot_count` is 0."

    Design: Corner/validations/convening_with_two_of_three_required_seats_returns_quorum_not_met
    """
    ctx = create_association(api, legal_name=HARBOR_POINT)
    director1 = add_owner(
        ctx,
        "d1",
        full_name="Dana Reed",
        email="dana@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    director2 = add_owner(
        ctx,
        "d2",
        full_name="Rita Vance",
        email="rita@example.test",
        board_role="DIRECTOR",
        is_seated=True,
    )
    unseated = add_owner(
        ctx,
        "hal",
        full_name="Hal Mercer",
        email="hal@example.test",
        board_role="DIRECTOR",
        is_seated=False,
    )
    meeting_id = schedule_meeting(
        ctx, "mtg1", ["REGULAR"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z"
    )
    notice_meeting(ctx, "mtg1")
    set_clock(api, "2026-08-10T10:00:00Z")

    validate_error(
        api.convene_meeting(
            meeting_id, {"attending_owner_ids": [director1, director2]}, MANAGER_HEADERS
        ),
        "ERR_BOARD_QUORUM_NOT_MET",
        409,
    )
    short = read_meeting(api, meeting_id, MANAGER_HEADERS)
    assert short["status"] == "NOTICED"
    assert short["quorum_met"] is False
    assert short["seated_director_count"] == 0

    validate_error(
        api.convene_meeting(
            meeting_id,
            {"attending_owner_ids": [director1, director2, unseated]},
            MANAGER_HEADERS,
        ),
        "ERR_BOARD_QUORUM_NOT_MET",
        409,
    )
    assert read_meeting(api, meeting_id, MANAGER_HEADERS)["status"] == "NOTICED"
