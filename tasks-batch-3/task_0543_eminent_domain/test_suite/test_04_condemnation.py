"""Condemnation lifecycle: deposit floor boundary, validation precedence,
possession cascade, statutory-interest award, and utility scheduling gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock,
    setup_condemnation_filed, setup_condemnation_deposit_made,
    setup_condemnation_possessed, setup_cleared_appraised_parcel,
    setup_identified_utility,
    TEST_USERS,
)

AGENT = TEST_USERS["right_of_way_agent_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
UTILITY = TEST_USERS["utility_coordinator_headers"]


# ---- transitive_cascade / possession_to_parcel_to_utility_cascade ----------

def test_grant_possession_cascades_parcel_to_possessed(api):
    """PRD §3.5: "Granting possession moves the condemnation from `DEPOSIT_MADE`
    to `POSSESSED`, stamps `possession_at` from the logical clock, and cascades
    the parcel's `acquisition_status` from `IN_CONDEMNATION` to `POSSESSED`."

    Design: Difficulty/transitive_cascade/possession_to_parcel_to_utility_cascade
    """
    ctx = setup_condemnation_deposit_made(api=api)
    get_success_data(api.create_utility_relocation(
        ctx["parcel"]["id"], {"utility_type": "WATER"}, UTILITY))
    cond = validate_success(api.grant_possession(ctx["condemnation"]["id"], ADMIN))
    assert cond["status"] == "POSSESSED"
    parcel = validate_success(api.get_parcel(ctx["parcel"]["id"], AGENT))
    assert parcel["acquisition_status"] == "POSSESSED"


def test_grant_possession_flips_utility_possession_cleared(api):
    """PRD §3.5: "That parcel transition in turn flips the `possession_cleared`
    flag to true on every utility relocation of the parcel that was still
    awaiting possession (see §3.7)."

    Design: Difficulty/transitive_cascade/possession_to_parcel_to_utility_cascade
    """
    ctx = setup_condemnation_deposit_made(api=api)
    ur = get_success_data(api.create_utility_relocation(
        ctx["parcel"]["id"], {"utility_type": "WATER"}, UTILITY))
    assert ur["possession_cleared"] is False
    validate_success(api.grant_possession(ctx["condemnation"]["id"], ADMIN))
    ur_now = validate_success(api.get_utility_relocation(ur["id"], AGENT))
    assert ur_now["possession_cleared"] is True


# ---- priority_pair_validation_conflict / deposit_state_beats_fiscal --------

def test_second_deposit_below_floor_returns_state_not_fiscal(api):
    """PRD §2.11: "6. **State** — the target resource must be in a state that
    permits the transition, else the domain-specific state error (409). ...
    12. **Fiscal floors and ceilings** — offer floor, deposit floor, and budget
    ceiling (402)."
    PRD §3.5: "Depositing requires the condemnation to be in `FILED` (else
    `ERR_INVALID_CONDEMNATION_STATE`)".

    Design: Difficulty/priority_pair_validation_conflict/deposit_state_beats_fiscal
    """
    ctx = setup_condemnation_deposit_made(api=api)  # first deposit 28,000,000 accepted
    resp = api.deposit(ctx["condemnation"]["id"], {"deposit_amount_cents": 1}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_CONDEMNATION_STATE)


def test_second_deposit_at_floor_still_returns_state_error(api):
    """PRD §3.5: "Depositing requires the condemnation to be in `FILED` (else
    `ERR_INVALID_CONDEMNATION_STATE`) and requires the supplied
    `deposit_amount_cents` to be at least the `just_compensation_snapshot_cents`
    floor (else `ERR_DEPOSIT_BELOW_COMPENSATION`)."

    Design: Difficulty/priority_pair_validation_conflict/deposit_state_beats_fiscal
    """
    ctx = setup_condemnation_deposit_made(api=api)
    floor = ctx["condemnation"]["just_compensation_snapshot_cents"]
    resp = api.deposit(
        ctx["condemnation"]["id"], {"deposit_amount_cents": floor}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_CONDEMNATION_STATE)


# ---- boundary_precision_check / deposit_floor_inclusive_boundary -----------

def test_deposit_exactly_at_floor_is_accepted(api):
    """PRD §3.5: "requires the supplied `deposit_amount_cents` to be at least the
    `just_compensation_snapshot_cents` floor (else
    `ERR_DEPOSIT_BELOW_COMPENSATION`). A valid deposit records
    `deposit_amount_cents`, stamps `deposit_at` from the logical clock, and moves
    the condemnation to `DEPOSIT_MADE`."

    Design: Difficulty/boundary_precision_check/deposit_floor_inclusive_boundary
    """
    ctx = setup_condemnation_filed(api=api)
    floor = ctx["condemnation"]["just_compensation_snapshot_cents"]
    assert floor == 28_000_000
    resp = api.deposit(
        ctx["condemnation"]["id"], {"deposit_amount_cents": floor}, AGENT)
    data = validate_success(resp)
    assert data["status"] == "DEPOSIT_MADE"
    assert data["deposit_amount_cents"] == 28_000_000


def test_deposit_one_cent_below_floor_is_rejected(api):
    """PRD §3.5: "requires the supplied `deposit_amount_cents` to be at least the
    `just_compensation_snapshot_cents` floor (else
    `ERR_DEPOSIT_BELOW_COMPENSATION`)."

    Design: Difficulty/boundary_precision_check/deposit_floor_inclusive_boundary
    """
    ctx = setup_condemnation_filed(api=api)
    floor = ctx["condemnation"]["just_compensation_snapshot_cents"]
    resp = api.deposit(
        ctx["condemnation"]["id"], {"deposit_amount_cents": floor - 1}, AGENT)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_BELOW_COMPENSATION)


# ---- Corner: award computes statutory interest -----------------------------

def test_award_computes_statutory_interest_and_settlement(api):
    """PRD §3.5: "The `statutory_interest_cents` is then the quantity
    (`final_award_cents` minus `deposit_amount_cents`) multiplied by the statutory
    daily interest rate of 0.0001 (one hundredth of one percent per day)
    multiplied by that day count, with the resulting interest term rounded half up
    to a whole cent. The condemnation's `settlement_total_cents` is the
    `final_award_cents` plus the `statutory_interest_cents`."

    Design: Corner/state_machines/award_computes_statutory_interest_and_settlement
    """
    set_clock("2026-06-01T00:00:00Z", api=api)
    ctx = setup_condemnation_possessed(api=api)  # deposit 28,000,000, possession at 2026-06-01
    set_clock("2026-07-01T00:00:00Z", api=api)  # 30 whole days of possession
    resp = api.award(
        ctx["condemnation"]["id"], {"final_award_cents": 30_000_000}, ADMIN)
    data = validate_success(resp)
    assert data["status"] == "AWARDED"
    assert data["statutory_interest_cents"] == 6_000
    assert data["settlement_total_cents"] == 30_006_000


# ---- Corner: grant possession before deposit -------------------------------

def test_grant_possession_before_deposit_returns_invalid_state(api):
    """PRD §3.5: "Granting possession moves the condemnation from `DEPOSIT_MADE`
    to `POSSESSED`". PRD §3.5: "Depositing requires the condemnation to be in
    `FILED` (else `ERR_INVALID_CONDEMNATION_STATE`)".

    Design: Corner/state_machines/grant_possession_before_deposit_returns_invalid_state
    """
    ctx = setup_condemnation_filed(api=api)  # still FILED, no deposit
    resp = api.grant_possession(ctx["condemnation"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_CONDEMNATION_STATE)


# ---- Corner: utility schedule requires possession --------------------------

def test_schedule_utility_before_possession_returns_not_possessed(api):
    """PRD §3.7: "A schedule action is permitted only when `possession_cleared` is
    true — equivalently, when the parcel's `acquisition_status` is `POSSESSED` or
    `ACQUIRED`; a schedule attempted before then is rejected with
    `ERR_PARCEL_NOT_POSSESSED`."

    Design: Corner/state_machines/schedule_utility_before_possession_returns_not_possessed
    """
    ctx = setup_identified_utility(possessed=False, api=api)
    resp = api.schedule_utility(ctx["utility"]["id"], {
        "crew_name": "CX", "scheduled_start": "2026-05-10T09:00:00Z",
        "scheduled_end": "2026-05-10T10:00:00Z"}, UTILITY)
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_POSSESSED)
