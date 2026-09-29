"""Ballot preconditions and the chair's tally over the eligible voter set."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    add_service_event,
    api_client,
    assert_cents,
    assert_committee_vote,
    assert_decimal,
    cast_vote,
    close_intake,
    make_asset,
    make_committee_member_headers,
    make_cycle,
    make_department,
    make_facility,
    make_member,
    make_request,
    open_intake,
    pin_clock,
    refresh_cycle,
    refresh_request,
    run_allocation,
    run_scoring,
    screen,
    submit,
    validate_error,
    validate_success,
    vote_rows,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]

CT_JUSTIFICATION = (
    "CT-16 scanner at end of service life; replacement restores stroke protocol throughput."
)


def _allocated_cycle(chair_conflicted=False):
    """A 2027 cycle driven to ALLOCATED with one SCORED request and a two-seat committee."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-16", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=240000000,
        oem_support_end_date="2029-01-01T00:00:00Z",
    )
    for event_date in ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"):
        add_service_event(asset["id"], event_date, "CORRECTIVE", downtime_hours=4.00)
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    cycle = open_intake(cycle["id"])
    chair_extras = {"department_id": department["id"]} if chair_conflicted else {}
    chair = make_member("CHAIR", 3, full_name="Dana Whitfield", **chair_extras)
    finance = make_member("FINANCE", 2, full_name="Roy Adeyemi")
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification=CT_JUSTIFICATION,
        current_annual_volume=1200, projected_annual_volume=1801,
        estimated_capital_cents=250000001, annual_service_contract_cents=12345678,
        disposable_unit_cents=1230, facility_modification_cents=60000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    return {
        "department": department, "cycle": refresh_cycle(cycle["id"]),
        "chair": chair, "finance": finance, "request": refresh_request(request["id"]),
    }


def _request_with_a_stale_version_in_hand():
    """The chair's ballot is cast after the version is read, so the read value is stale."""
    ctx = _allocated_cycle()
    stale_version = ctx["request"]["version"]
    cast_vote(ctx["request"]["id"], ctx["chair"]["id"], "APPROVE",
              expected_request_version=stale_version)
    ctx["stale_version"] = stale_version
    return ctx


def _sole_system_wide_voter_suspended():
    """The chair is conflicted out by department, and the only other seat is deactivated."""
    ctx = _allocated_cycle(chair_conflicted=True)
    cast_vote(ctx["request"]["id"], ctx["finance"]["id"], "APPROVE",
              rationale="Sole system-wide voter; the business case is sound.")
    validate_success(
        api_client.patch_committee_member(ctx["finance"]["id"], {"active": False}, _PLANNER)
    )
    return ctx


# ─── Which fault wins when a ballot breaks two rules ─────────────────


def test_a_ballot_on_a_missing_request_reports_the_missing_row(api):
    """PRD §2.11: "3. A templated path identifier that resolves to no row — that entity's
    not-found error, 404."
    PRD §2.7: "Path parameters are resolved strictly left to right, and the first
    identifier that resolves to no row terminates the request with that entity's own
    not-found error: `ERR_FACILITY_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`,
    `ERR_CYCLE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_GPO_CONTRACT_NOT_FOUND`,
    `ERR_QUOTE_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND` or `ERR_AUDIT_NOT_FOUND`, each at HTTP
    404."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_stale_version_on_vote
    """
    ctx = _request_with_a_stale_version_in_hand()

    response = api.create_vote(
        UNKNOWN_UUID,
        {"vote": "APPROVE", "expected_request_version": ctx["stale_version"]},
        make_committee_member_headers(ctx["finance"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REQUEST_NOT_FOUND.value, 404)


def test_the_same_stale_version_on_the_real_request_reports_the_version(api):
    """PRD §2.8: "When the value does not match the request's current `version`, the ballot
    is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412)."
    PRD §2.11: "21. `expected_request_version` not matching the request's current `version`
    on ballot creation, and `expected_cycle_version` not matching the cycle's current
    `version` on an allocation run — `ERR_STALE_REQUEST_VERSION` and
    `ERR_STALE_CYCLE_VERSION` respectively, both 412."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_stale_version_on_vote
    """
    ctx = _request_with_a_stale_version_in_hand()

    response = api.create_vote(
        ctx["request"]["id"],
        {"vote": "APPROVE", "expected_request_version": ctx["stale_version"]},
        make_committee_member_headers(ctx["finance"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_REQUEST_VERSION.value, 412)


def test_neither_rejected_ballot_joins_the_one_that_already_landed(api):
    """PRD §3.7: "The first counted ballot performs `SCORED → IN_COMMITTEE`."
    PRD §3.7: "Every ballot increments the request's `version`, and every ballot pins
    `counted_weight` from the casting member's `voting_weight` at that instant."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_stale_version_on_vote
    """
    ctx = _request_with_a_stale_version_in_hand()
    finance_headers = make_committee_member_headers(ctx["finance"]["id"])
    ballot = {"vote": "APPROVE", "expected_request_version": ctx["stale_version"]}
    api.create_vote(UNKNOWN_UUID, ballot, finance_headers)
    api.create_vote(ctx["request"]["id"], ballot, finance_headers)

    assert refresh_request(ctx["request"]["id"])["status"] == "IN_COMMITTEE"

    rows = vote_rows(ctx["request"]["id"])
    assert len(rows) == 1, "only the chair's ballot was ever counted"
    assert_committee_vote(rows[0])
    assert rows[0]["member_id"] == ctx["chair"]["id"]
    assert rows[0]["vote"] == "APPROVE"
    assert rows[0]["counted_weight"] == 3
    assert rows[0]["superseded"] is False


# ─── The tally depends on a sibling entity's active flag ─────────────


def test_closing_voting_with_the_only_eligible_seat_suspended_reports_no_voters(api):
    """PRD §3.7: "Otherwise, if the eligible voter set is empty the call is rejected with
    `ERR_NO_ELIGIBLE_VOTERS`."
    PRD §3.7: "First the **eligible voter set** is derived over every committee member row
    using exactly the eligibility predicate above, and the quorum weight is the sum of
    `voting_weight` over that set."
    PRD §3.7: "Editing a member never rewrites ballots already cast — those keep the weight
    pinned on them — but a member who becomes inactive or newly conflicted drops out of
    both quorum and cast weight the next time a tally runs."

    Design: Difficulty/cross_entity_state_dependency/committee_decision_depends_on_member_active_flag
    """
    ctx = _sole_system_wide_voter_suspended()

    response = api.committee_decision(
        ctx["request"]["id"], make_committee_member_headers(ctx["chair"]["id"]),
        {"decision_note": "Closing voting with the finance seat suspended."},
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_VOTERS.value, 409)

    assert refresh_request(ctx["request"]["id"])["status"] == "IN_COMMITTEE"


def test_restoring_that_seat_lets_the_identical_close_land_on_approved(api):
    """PRD §3.7: "Otherwise the two-thirds approval bar is applied: when approve weight
    multiplied by three is at least cast weight multiplied by two, the request moves
    `IN_COMMITTEE → APPROVED`."
    PRD §3.7: "In both sums it is the weight pinned on the ballot that counts, never the
    member's current `voting_weight`."
    PRD §3.7: "Closing voting is the chair's act and carries only an optional
    `decision_note`."

    Design: Difficulty/cross_entity_state_dependency/committee_decision_depends_on_member_active_flag
    """
    ctx = _sole_system_wide_voter_suspended()
    chair_headers = make_committee_member_headers(ctx["chair"]["id"])
    validate_error(api.committee_decision(ctx["request"]["id"], chair_headers,
                                          {"decision_note": "Suspended seat."}),
                   ApiErrorId.ERR_NO_ELIGIBLE_VOTERS.value, 409)

    restored = validate_success(
        api.patch_committee_member(ctx["finance"]["id"], {"active": True}, _PLANNER)
    )
    assert restored["active"] is True
    assert restored["voting_weight"] == 2

    decided = validate_success(api.committee_decision(ctx["request"]["id"], chair_headers))
    assert decided["status"] == "APPROVED"

    rows = vote_rows(ctx["request"]["id"])
    assert len(rows) == 1
    assert rows[0]["member_id"] == ctx["finance"]["id"]
    assert rows[0]["counted_weight"] == 2
    assert rows[0]["superseded"] is False

    after = refresh_request(ctx["request"]["id"])
    assert_decimal(after["composite_score"], 66.18, "composite_score")
    assert_cents(after["funded_amount_cents"], 0, "funded_amount_cents")
