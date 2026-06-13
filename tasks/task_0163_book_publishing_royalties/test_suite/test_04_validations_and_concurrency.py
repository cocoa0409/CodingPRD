"""Validation rules, precedence pairs, temporal/range collisions, cross-entity
state dependencies, and the contract OCC check.

Covers depth instances under priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap, plus corner validation,
error, and OCC instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    fixtures,
    factories,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
)

PUB = TEST_USERS["publisher_headers"]


# ==========================================================================
# Queue A — priority_pair_validation_conflict
# ==========================================================================
def test_finalize_nonexistent_statement_is_not_found_before_state(api):
    """PRD §2.6: "The system validates every identifier in a path strictly left to
    right, and the first one that does not resolve to an existing resource fails
    the request with `ERR_NOT_FOUND` (HTTP 404) before any deeper check runs."

    PRD §2.10: "Resource existence follows: any unresolved path identifier or body
    foreign key yields `ERR_NOT_FOUND`."

    Finalizing a non-existent statement id returns ERR_NOT_FOUND, never
    ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_state_on_finalize
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    cv = contract["version"]

    resp = api.finalize_statement(NON_EXISTENT_UUID, {"expected_contract_version": cv}, PUB)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_close_with_unstatemented_earlier_period_is_sequence_violation(api):
    """PRD §3.3: "The Publisher closes an `OPEN` period ... only when every
    lower-`sequence` period of the same contract is already `STATEMENTED`; closing
    a period while an earlier-`sequence` sibling has not yet been statemented
    violates the ascending-sequence rule and is rejected with
    `ERR_PERIOD_SEQUENCE_VIOLATION` (HTTP 409)."

    Closing seq2 while seq1 is still OPEN (never statemented) yields the temporal
    rule's error.

    Design: Difficulty/priority_pair_validation_conflict/period_sequence_temporal_before_state_on_close
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    cid = base["contract"]["id"]

    fixtures.open_period(cid, "P1", 1)
    p2 = fixtures.open_period(cid, "P2", 2)

    resp = api.close_sales_period(p2["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_PERIOD_SEQUENCE_VIOLATION.value)


# ==========================================================================
# Queue A — cross_entity_state_dependency
# ==========================================================================
def test_period_close_requires_active_contract(api):
    """PRD §3.3: "The Publisher closes an `OPEN` period — transitioning its
    `status` from `OPEN` to `CLOSED` — only while the owning contract is `ACTIVE`
    and only when every lower-`sequence` period of the same contract is already
    `STATEMENTED`"

    A period on a still-DRAFT contract cannot be closed; the attempt yields
    ERR_INVALID_STATE and the period stays OPEN.

    Design: Difficulty/cross_entity_state_dependency/period_close_requires_contract_active
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0, reserve_pct=0, reserve_hold_periods=1)
    fixtures.add_tiers(contract["id"], fixtures.SINGLE_TIER)
    title = fixtures.add_title(contract["id"], name="Book Twelve")
    fixtures.add_format(title["id"], list_price_cents=3000)
    period = fixtures.open_period(contract["id"], "P1", 1)

    resp = api.close_sales_period(period["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    reread = validate_success(api.get_sales_period(period["id"], PUB))
    assert reread["status"] == "OPEN"


def test_sales_record_into_inactive_format_rejected(api):
    """PRD §3.3: "A record may be posted only into a period that is `OPEN` and
    whose owning contract is `ACTIVE`, and only against a format that is still
    `active`; a record aimed at a non-open period, an inactive format, or a
    non-active contract is rejected with `ERR_PERIOD_NOT_OPEN` (HTTP 409)."

    A format made inactive by retiring its title cannot receive sales records.

    Design: Difficulty/cross_entity_state_dependency/sales_record_requires_active_format
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    tid = base["title"]["id"]
    fid = base["format"]["id"]

    validate_success(api.retire_title(tid, PUB))
    period = fixtures.open_period(cid, "P1", 1)

    resp = api.create_sales_record(period["id"], {"format_id": fid, "units_sold": 5, "units_returned": 0}, PUB)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    formats = validate_success(api.list_formats(tid, PUB))
    assert next(f for f in formats if f["id"] == fid)["active"] is False


# ==========================================================================
# Queue A — resource_temporal_overlap
# ==========================================================================
def test_duplicate_period_sequence_collides(api):
    """PRD §3.3: "The `sequence` must be unique within the owning contract:
    opening a period whose `sequence` already occupies a point on the contract's
    timeline is a zero-width collision rejected with
    `ERR_DUPLICATE_PERIOD_SEQUENCE` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/period_sequence_point_occupation_collision
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    cid = base["contract"]["id"]
    fixtures.open_period(cid, "P1", 1)

    resp = api.create_sales_period(cid, {"label": "P1-dup", "sequence": 1}, PUB)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD_SEQUENCE.value)


def test_overlapping_royalty_tiers_rejected_on_activate(api):
    """PRD §3.1: "Two tiers overlap when their inclusive `[lower_unit, upper_unit]`
    ranges intersect ... A tier schedule that is not a gapless, non-overlapping
    cover from 1 with exactly one open top tier is rejected with
    `ERR_TIER_COVERAGE_INVALID` (HTTP 422)"

    Tiers [1..5000] and [5000..10000] share unit 5000, so their closed ranges
    intersect; activation is rejected and the contract stays DRAFT.

    Design: Difficulty/resource_temporal_overlap/royalty_tier_range_overlap_collision_on_activate
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0, reserve_pct=0, reserve_hold_periods=1)
    fixtures.add_tiers(
        contract["id"],
        [
            {"lower_unit": 1, "upper_unit": 5000, "rate": 0.10},
            {"lower_unit": 5000, "upper_unit": 10000, "rate": 0.125},
            {"lower_unit": 10001, "rate": 0.15},
        ],
    )
    title = fixtures.add_title(contract["id"], name="Book Fifteen")
    fixtures.add_format(title["id"], list_price_cents=3000)

    resp = api.activate_contract(contract["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_TIER_COVERAGE_INVALID.value)

    reread = validate_success(api.get_contract(contract["id"], PUB))
    assert reread["status"] == "DRAFT"


# ==========================================================================
# Queue B — corner validations / errors
# ==========================================================================
def test_duplicate_author_email_rejected(api):
    """PRD §3.1: "registering a second author or agent with an `email` already on
    file is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/validations/duplicate_author_email_rejected
    """
    email = factories._unique_email("dup")
    get_success_data(api.create_author({"full_name": "First", "email": email}, PUB))

    resp = api.create_author({"full_name": "Second", "email": email}, PUB)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_duplicate_agent_email_rejected(api):
    """PRD §3.1: "registering a second author or agent with an `email` already on
    file is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/errors/duplicate_email_for_agent
    """
    email = factories._unique_email("agdup")
    get_success_data(api.create_agent({"agency_name": "First Agency", "email": email}, PUB))

    resp = api.create_agent({"agency_name": "Second Agency", "email": email}, PUB)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_commission_without_agent_rejected(api):
    """PRD §3.1: "If a contract names no agent yet carries a non-zero
    `agent_commission_pct`, the create is rejected with
    `ERR_COMMISSION_WITHOUT_AGENT` (HTTP 422)"

    Design: Corner/validations/commission_without_agent_rejected
    """
    author = fixtures.create_author()
    resp = api.create_contract(
        {"author_id": author["id"], "advance_cents": 0, "agent_commission_pct": 0.15}, PUB
    )
    validate_error(resp, ApiErrorId.ERR_COMMISSION_WITHOUT_AGENT.value)


def test_cross_contract_sales_record_rejected(api):
    """PRD §2.6: "a sales record's `format_id` must name a format whose owning
    title belongs to the same contract as the sales record's period, since
    cross-contract sales are nonsensical; a violation is rejected with
    `ERR_CROSS_CONTRACT_REFERENCE` (HTTP 422)."

    Posting contract A's format into contract B's period is rejected.

    Design: Corner/validations/cross_contract_sales_record_rejected
    """
    a = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    format_a = a["format"]["id"]

    b = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    period_b = fixtures.open_period(b["contract"]["id"], "PB", 1)

    resp = api.create_sales_record(period_b["id"], {"format_id": format_a, "units_sold": 5, "units_returned": 0}, PUB)
    validate_error(resp, ApiErrorId.ERR_CROSS_CONTRACT_REFERENCE.value)


def test_terminate_with_held_reserve_rejected(api):
    """PRD §3.1: "A termination attempt against a contract with held reserves or
    unpaid statements is rejected with `ERR_OPEN_LIABILITIES` (HTTP 409)."

    A statement is finalized (creating a HELD reserve) and paid (so no unpaid
    statement remains), but the HELD reserve still blocks termination.

    Design: Corner/validations/terminate_with_held_reserve_rejected
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0.25, reserve_hold_periods=2
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 1000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)
    fixtures.pay_statement(s1["id"], cid)

    resp = api.terminate_contract(cid, PUB)
    validate_error(resp, ApiErrorId.ERR_OPEN_LIABILITIES.value)


def test_void_statemented_right_rejected(api):
    """PRD §3.4: "A right that has already been carried onto a statement, however,
    is settled income and immutable: attempting to void a `STATEMENTED` (or
    already `VOID`) right is rejected with `ERR_RIGHT_ALREADY_SETTLED` (HTTP 409)."

    Design: Corner/errors/right_already_settled_void_rejected
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    right = get_success_data(
        api.create_subsidiary_right(
            cid, {"right_type": "FILM", "proceeds_cents": 500000, "author_share_pct": 0.5}, PUB
        )
    )
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    fixtures.finalize_statement(s1["id"], cid)

    resp = api.void_subsidiary_right(right["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_RIGHT_ALREADY_SETTLED.value)


# ==========================================================================
# Queue B — OCC (cross_cutting_complexity_layers)
# ==========================================================================
def test_finalize_with_stale_contract_version_rejected(api):
    """PRD §2.9: "When a statement is finalized, the request must carry an
    `expected_contract_version` field equal to the owning contract's current
    `version`; if a different statement for an earlier period was finalized after
    this client last read the contract ... the contract's `version` will have
    advanced, and the finalize is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412) because its recoupment and tier math were computed against a
    superseded baseline."

    Read version, finalize seq1 (bumps version), then try to finalize seq2 with
    the stale version: rejected, seq2 stays DRAFT.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_finalize
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(p1["id"], PUB))
    stale_version = fixtures.current_version(cid)
    # finalize s1 with the live version, bumping contract.version past stale_version
    get_success_data(api.finalize_statement(s1["id"], {"expected_contract_version": stale_version}, PUB))

    p2 = fixtures.run_period_to_closed(cid, fid, "P2", 2, 100, 0)
    s2 = get_success_data(api.generate_statement(p2["id"], PUB))

    resp = api.finalize_statement(s2["id"], {"expected_contract_version": stale_version}, PUB)
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)

    reread = validate_success(api.get_statement(s2["id"], PUB))
    assert reread["status"] == "DRAFT"
