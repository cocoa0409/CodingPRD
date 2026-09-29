"""Two interval families that disagree at their shared endpoint.

Sponsorship intervals are half-open, so a successor starting at the instant its
predecessor ended is legal. Plan-assignment intervals are closed at both ends,
so the very same adjacency is a collision. Both are exercised at the endpoint
itself and one step to either side of it.
"""
from datetime import datetime

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    assign_plan,
    claim_sponsorship,
    create_originator,
    get_license,
    get_originator,
    relinquish_sponsorship,
    set_clock,
    setup_approved_plan,
    setup_authorized_originator,
    take_loan,
)
from test_helpers.test_users import analyst_headers, officer_headers

BOUNDARY_INSTANT = "2026-08-10T00:00:00Z"


def _instant(value):
    """Parse an ISO 8601 UTC instant, tolerating the optional fractional part."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _plan(api, plan_id):
    """Read a plan back as the officer who assigns it."""
    return validate_success(api.get_compensation_plan(plan_id, officer_headers()))


def _licence_with_a_closed_sponsorship_interval(api):
    """A licence whose first sponsorship occupies [2026-08-01, 2026-08-10)."""
    context = setup_authorized_originator(api)
    set_clock(api, BOUNDARY_INSTANT)
    context["sponsorship"] = relinquish_sponsorship(api, context["sponsorship"]["id"])
    context["license"] = get_license(api, context["license"]["id"])
    return context


def _licence_handed_over_at_the_boundary(api):
    """The same licence, with a successor sponsorship starting at the exclusive end."""
    context = _licence_with_a_closed_sponsorship_interval(api)
    context["successor"] = claim_sponsorship(
        api,
        context["license"]["id"],
        context["license"]["version"],
        sponsoring_institution_code="INST-BETA",
        effective_at=BOUNDARY_INSTANT,
    )
    context["license"] = get_license(api, context["license"]["id"])
    return context


def _originator_with_two_approved_plans(api):
    """An originator carrying P1 over the closed interval [2026-08-01, 2026-09-30]."""
    originator = create_originator(api)
    first = setup_approved_plan(
        api, variable_type="LOAN_VOLUME_UNITS", plan_name="P1 150bps", base_basis_points=150
    )
    second = setup_approved_plan(
        api, variable_type="FILE_QUALITY_SCORE", plan_name="P2 175bps", base_basis_points=175
    )
    assert first["status"] == "ACTIVE" and second["status"] == "ACTIVE", (
        f"both plans must be approved before assignment: {first['status']}, {second['status']}"
    )
    originator = assign_plan(
        api,
        originator["id"],
        first["id"],
        originator["version"],
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-30T00:00:00Z",
    )
    assert originator["compensation_plan_id"] == first["id"], (
        f"the incumbent assignment must be P1, got {originator['compensation_plan_id']}"
    )
    return {"originator": originator, "first": first, "second": second}


def test_successor_sponsorship_at_the_exclusive_end_instant_is_accepted(api):
    """PRD 3.1: "Exact adjacency is legal and is the intended way to hand a licence from
    one institution to the next: an incoming `effective_at` equal to a previous row's
    `relinquished_at` is accepted."
    PRD 3.1: "The system stamps `relinquished_at` from the logical clock, clears the
    licence's `active_sponsoring_institution_code` and `active_sponsorship_effective_at`
    to null"
    PRD 3.1: "A successful claim creates a sponsorship row in `ACTIVE` with a null
    `relinquished_at`, copies `sponsoring_institution_code` and `effective_at` into the
    licence's `active_sponsoring_institution_code` and `active_sponsorship_effective_at`,
    recomputes the originator's `authorized_state_codes`, and increments the licence's
    `version` by one."

    Design: Difficulty/resource_temporal_overlap/sponsorship_half_open_adjacency_accepted_backdate_rejected
    """
    context = _licence_with_a_closed_sponsorship_interval(api)

    assert context["sponsorship"]["status"] == "RELINQUISHED", (
        f"got {context['sponsorship']['status']}"
    )
    assert _instant(context["sponsorship"]["relinquished_at"]) == _instant(BOUNDARY_INSTANT), (
        "relinquished_at is stamped from the logical clock, "
        f"got {context['sponsorship']['relinquished_at']}"
    )
    assert context["license"]["active_sponsoring_institution_code"] is None

    successor = claim_sponsorship(
        api,
        context["license"]["id"],
        context["license"]["version"],
        sponsoring_institution_code="INST-BETA",
        effective_at=BOUNDARY_INSTANT,
    )
    assert successor["status"] == "ACTIVE", (
        f"the adjacent claim is accepted and starts ACTIVE, got {successor['status']}"
    )
    assert _instant(successor["effective_at"]) == _instant(BOUNDARY_INSTANT), (
        f"the successor begins at the predecessor's exclusive end, got {successor['effective_at']}"
    )
    assert successor["relinquished_at"] is None

    licence = get_license(api, context["license"]["id"])
    assert licence["active_sponsoring_institution_code"] == "INST-BETA", (
        f"got {licence['active_sponsoring_institution_code']}"
    )
    assert _instant(licence["active_sponsorship_effective_at"]) == _instant(BOUNDARY_INSTANT), (
        f"got {licence['active_sponsorship_effective_at']}"
    )


def test_authority_holds_at_the_handover_instant_with_no_gap(api):
    """PRD 2.8: "A direct consequence of the half-open convention is that **adjacency is
    not a gap**. A sponsorship relinquished at a given instant, immediately followed by a
    new sponsorship effective at that same instant, leaves no unauthorised moment; an
    application taken at exactly that instant is covered by the new sponsorship rather
    than the old one."
    PRD 2.8: "That read evaluates at the instant supplied as `as_of_iso8601` when the
    caller supplies one, and otherwise at the current logical clock instant."
    PRD 3.4: "A successfully taken application stamps `application_taken_at` from the
    logical clock"

    Design: Difficulty/resource_temporal_overlap/sponsorship_half_open_adjacency_accepted_backdate_rejected
    """
    context = _licence_handed_over_at_the_boundary(api)
    originator_id = context["originator"]["id"]

    authority = validate_success(
        api.get_originator_authority(
            originator_id, officer_headers(), params={"as_of_iso8601": BOUNDARY_INSTANT}
        )
    )
    assert authority["authorized_state_codes"] == ["CA"], (
        "the successor's start instant is inside its own interval, so there is no "
        f"one-millisecond gap at the handover, got {authority['authorized_state_codes']}"
    )
    assert _instant(authority["as_of"]) == _instant(BOUNDARY_INSTANT), (
        f"the read echoes the instant it evaluated, got {authority['as_of']}"
    )
    assert authority["employment_status"] == "EMPLOYED"

    loan = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        borrower_reference="BW-2602-A1",
        requested_amount_cents=17_000_000,
        par_rate_bps=642,
    )
    assert _instant(loan["application_taken_at"]) == _instant(BOUNDARY_INSTANT), (
        f"got {loan['application_taken_at']}"
    )
    assert loan["authority_flag"] == "VERIFIED", (
        "the loan is authorised by the successor sponsorship, "
        f"got {loan['authority_flag']}"
    )


def test_back_dated_sponsorship_inside_the_closed_interval_is_rejected(api):
    """PRD 3.1: "An incoming `effective_at` is rejected with
    `ERR_SPONSORSHIP_PERIOD_OVERLAP` (HTTP 409) in two situations: when it falls inside
    the half-open interval of an already-closed sponsorship on the same licence — that
    is, when some row whose `status` is `RELINQUISHED` or `SUPERSEDED` has an
    `effective_at` at or before the incoming instant and a `relinquished_at` strictly
    after it — and when it is back-dated, meaning it falls strictly before the
    `effective_at` of some existing sponsorship row on that licence."

    Design: Difficulty/resource_temporal_overlap/sponsorship_half_open_adjacency_accepted_backdate_rejected
    """
    context = _licence_handed_over_at_the_boundary(api)
    licence = context["license"]

    response = api.create_sponsorship_transfer(
        licence["id"],
        factories.build_sponsorship_transfer(
            licence["version"],
            sponsoring_institution_code="INST-GAMMA",
            effective_at="2026-08-05T00:00:00Z",
        ),
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SPONSORSHIP_PERIOD_OVERLAP.value)

    rows = validate_success(
        api.list_sponsorship_transfers(
            analyst_headers(),
            params={"license_registration_id": licence["id"], "limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 2, f"the rejected claim wrote no row, got {len(rows)}: {rows}"
    by_id = {row["id"]: row for row in rows}
    assert by_id[context["sponsorship"]["id"]]["status"] == "RELINQUISHED"
    assert by_id[context["successor"]["id"]]["status"] == "ACTIVE"
    assert [row["sponsoring_institution_code"] for row in rows].count("INST-GAMMA") == 0, (
        f"no INST-GAMMA row may exist, got {rows}"
    )


def test_plan_assignment_at_the_shared_inclusive_endpoint_is_rejected(api):
    """PRD 3.3: "Assignment intervals on one originator may not intersect. Because both
    bounds are inclusive, the collision test is inclusive on both sides: the request is
    rejected with `ERR_PLAN_PERIOD_OVERLAP` (HTTP 409) when there exists a plan already
    assigned to this originator whose `status` is `ACTIVE` or `SUPERSEDED` and whose
    `assignment_effective_to` is at or after the incoming `effective_from` while its
    `assignment_effective_from` is at or before the incoming `effective_to`."
    PRD 3.3: "Note the deliberate contrast with sponsorship geometry in §3.1: here
    **adjacency is a collision** — an incoming `effective_from` exactly equal to an
    existing assignment's `assignment_effective_to` is rejected, because at most one
    assignment may cover any single instant."

    Design: Difficulty/resource_temporal_overlap/plan_assignment_closed_adjacency_rejected_next_day_accepted
    """
    context = _originator_with_two_approved_plans(api)
    originator = context["originator"]

    response = api.assign_compensation_plan(
        originator["id"],
        factories.build_plan_assignment(
            context["second"]["id"],
            originator["version"],
            effective_from="2026-09-30T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z",
        ),
        officer_headers(),
    )
    validate_error(response, ApiErrorId.ERR_PLAN_PERIOD_OVERLAP.value)

    unchanged = get_originator(api, originator["id"])
    assert unchanged["version"] == originator["version"], (
        "the rejected assignment bumped nothing, "
        f"got version {unchanged['version']} from {originator['version']}"
    )
    assert unchanged["compensation_plan_id"] == context["first"]["id"], (
        f"the incumbent plan still stands, got {unchanged['compensation_plan_id']}"
    )
    assert _plan(api, context["second"]["id"])["assigned_originator_id"] is None, (
        "the rejected plan was never bound to the originator"
    )


def test_plan_assignment_one_day_past_the_endpoint_is_accepted_and_supersedes(api):
    """PRD 3.3: "A successful assignment writes `assigned_originator_id`,
    `assignment_effective_from` and `assignment_effective_to` onto the plan, sets the
    originator's `compensation_plan_id` to the assigned plan, and increments the
    originator's `version` by one."
    PRD 3.3: "When the originator already carried an `ACTIVE` assigned plan, that plan
    moves `ACTIVE → SUPERSEDED`"

    Design: Difficulty/resource_temporal_overlap/plan_assignment_closed_adjacency_rejected_next_day_accepted
    """
    context = _originator_with_two_approved_plans(api)
    originator = context["originator"]

    reassigned = assign_plan(
        api,
        originator["id"],
        context["second"]["id"],
        originator["version"],
        effective_from="2026-10-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    assert reassigned["compensation_plan_id"] == context["second"]["id"], (
        "moving effective_from one day past the incumbent's inclusive end clears the "
        f"collision, got {reassigned['compensation_plan_id']}"
    )
    assert reassigned["version"] == originator["version"] + 1, (
        f"got version {reassigned['version']} from {originator['version']}"
    )
    assert _plan(api, context["first"]["id"])["status"] == "SUPERSEDED", (
        "the displaced incumbent moves ACTIVE to SUPERSEDED"
    )


def test_the_superseded_plan_keeps_its_own_assignment_interval(api):
    """PRD 3.3: "ledger lines already pinned to the superseded plan keep their own
    `compensation_plan_id` unchanged, because historic commission lines are never
    re-pointed at a newer plan."
    PRD 3.3: "A successful assignment writes `assigned_originator_id`,
    `assignment_effective_from` and `assignment_effective_to` onto the plan, sets the
    originator's `compensation_plan_id` to the assigned plan, and increments the
    originator's `version` by one."

    Design: Difficulty/resource_temporal_overlap/plan_assignment_closed_adjacency_rejected_next_day_accepted
    """
    context = _originator_with_two_approved_plans(api)
    originator = context["originator"]

    assign_plan(
        api,
        originator["id"],
        context["second"]["id"],
        originator["version"],
        effective_from="2026-10-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )

    first = _plan(api, context["first"]["id"])
    assert first["status"] == "SUPERSEDED"
    assert _instant(first["assignment_effective_from"]) == _instant("2026-08-01T00:00:00Z"), (
        f"the superseded plan keeps its own start, got {first['assignment_effective_from']}"
    )
    assert _instant(first["assignment_effective_to"]) == _instant("2026-09-30T00:00:00Z"), (
        f"the superseded plan keeps its own end, got {first['assignment_effective_to']}"
    )
    assert first["assigned_originator_id"] == originator["id"]

    second = _plan(api, context["second"]["id"])
    assert second["status"] == "ACTIVE", f"got {second['status']}"
    assert _instant(second["assignment_effective_from"]) == _instant("2026-10-01T00:00:00Z"), (
        f"got {second['assignment_effective_from']}"
    )
    assert _instant(second["assignment_effective_to"]) == _instant("2026-12-31T00:00:00Z"), (
        f"got {second['assignment_effective_to']}"
    )
    assert second["assigned_originator_id"] == originator["id"], (
        f"got {second['assigned_originator_id']}"
    )
