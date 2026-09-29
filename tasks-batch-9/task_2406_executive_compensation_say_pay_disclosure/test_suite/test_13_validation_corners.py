"""Validation corners of the peer-group, program-approval and outreach gates.

These tests exercise the boundaries the PRD draws around admitting a candidate
peer (the closed size bands and the documented-rationale waiver), around
screening a group that has no `ACCEPTED` members left, around the delisting of a
company that is only later offered as a peer, around the metric-weight aggregate
checked at committee approval, and around the engagement window that may not
start before the logical now.
"""

from datetime import datetime

from test_helpers import (
    CHAIR,
    CONSULTANT,
    IR_LEAD,
    ApiErrorId,
    add_member_payload,
    add_peer_member,
    add_metric,
    api_client,
    assert_money,
    assert_peer_group_member,
    assert_ratio,
    create_company,
    create_engagement,
    create_peer_group,
    exclude_peer_member,
    peer_group_version,
    read_metric,
    read_metrics,
    read_pay_program,
    read_peer_group,
    read_peer_group_member,
    read_engagement,
    refresh_market_data,
    schedule_engagement_payload,
    set_clock,
    setup_issuer,
    setup_pay_program,
    validate_error,
    validate_success,
)


def _same_instant(actual: str, expected: str) -> bool:
    """Instant comparisons in this system are made at second granularity."""

    def normalise(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(microsecond=0)

    return normalise(actual) == normalise(expected)


def test_screening_refuses_a_group_whose_only_membership_has_been_excluded():
    """Screening counts ACCEPTED members, so an excluded row does not save the group.

    PRD: "It is refused on a group that is not in `DRAFT` with
    `ERR_PEER_GROUP_NOT_MUTABLE`, refused on a group with zero `ACCEPTED` members
    with `ERR_PEER_GROUP_EMPTY`, and refused with `ERR_PEER_OUTSIDE_SIZE_BAND`
    unless every `ACCEPTED` member either sits inside both bands or was admitted
    as a `BUSINESS_MODEL_ANALOG` — note that a `TALENT_COMPETITOR` peer whose
    ratios have since drifted out of band does block screening even though it was
    admissible at add time."

    PRD: "Only `ACCEPTED` members participate in the computation; excluded
    members never do, no matter when they were excluded."

    Design: Corner/validations/screening_a_group_whose_only_member_was_excluded_returns_peer_group_empty
    """
    env = setup_issuer()
    bravo = create_company("BRVO")
    group = create_peer_group(env["issuer"]["id"])

    # A brand-new group has no members at all.
    validate_error(
        api_client.screen_peer_group(group["id"], CONSULTANT),
        ApiErrorId.ERR_PEER_GROUP_EMPTY,
        422,
    )

    member = add_peer_member(group["id"], bravo["id"], "SIZE_MATCH")
    exclude_peer_member(member["id"])

    # The membership row still exists, but it no longer counts.
    validate_error(
        api_client.screen_peer_group(group["id"], CONSULTANT),
        ApiErrorId.ERR_PEER_GROUP_EMPTY,
        422,
    )

    excluded = read_peer_group_member(group["id"], member["id"])
    assert excluded is not None, "the excluded membership row must survive"
    assert excluded["status"] == "EXCLUDED"

    reread = read_peer_group(group["id"])
    assert reread["status"] == "DRAFT"
    assert reread["accepted_member_count"] == 0
    assert reread["median_revenue_usd"] is None
    assert reread["median_market_cap_usd"] is None
    assert reread["screened_at"] is None


def test_peer_inside_both_size_bands_is_accepted_on_a_plain_size_match():
    """A candidate inside both closed bands needs no documented waiver.

    PRD: "The membership's `in_size_band` is true only when the revenue ratio
    lies between 0.5 and 2.0 and the market-capitalisation ratio lies between
    0.25 and 4.0."

    Design: Corner/validations/a_peer_inside_both_declared_size_bands_is_accepted_under_size_match
    """
    env = setup_issuer()
    charlie = create_company("CHRL")
    group = create_peer_group(env["issuer"]["id"])

    response = api_client.add_peer_group_member(
        group["id"],
        add_member_payload(charlie["id"], peer_group_version(group["id"]), "SIZE_MATCH"),
        CONSULTANT,
    )
    member = validate_success(response, 201)

    assert_peer_group_member(member)
    assert member["status"] == "ACCEPTED"
    assert member["inclusion_reason"] == "SIZE_MATCH"
    # 12,000,000,000 / 10,000,000,000 and 30,000,000,000 / 20,000,000,000.
    assert_ratio(member["revenue_ratio"], 1.2000, "revenue_ratio")
    assert_ratio(member["market_cap_ratio"], 1.5000, "market_cap_ratio")
    assert member["in_size_band"] is True

    reread = read_peer_group(group["id"])
    assert reread["accepted_member_count"] == 1
    assert reread["version"] == 2


def test_program_approval_requires_metric_weights_to_total_exactly_one_hundred():
    """Each weight is individually legal; the collective sum is what gates approval.

    PRD: "For each vehicle that has at least one metric defined, the `weight_pct`
    values of that vehicle's metrics must sum to exactly 100.00, or the answer is
    `ERR_METRIC_WEIGHTS_NOT_100`; a vehicle with no metrics at all imposes no
    weight requirement."

    PRD: "When the committee approves the program design, every `DRAFT` metric of
    that program moves `DRAFT → LOCKED` and takes a snapshot:
    `locked_target_value` is set to the metric's `target_value` at that instant,
    and the snapshot never moves again."

    Design: Corner/validations/program_approval_requires_the_metric_weights_to_total_exactly_one_hundred
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR", "REVENUE_GROWTH_STEP"),
        metric_overrides=[{}, {"weight_pct": 30.00}],
        approve=False,
    )
    program_id = env["program"]["id"]

    # 60.00 + 30.00 == 90.00.
    validate_error(
        api_client.approve_pay_program(program_id, CHAIR),
        ApiErrorId.ERR_METRIC_WEIGHTS_NOT_100,
        422,
    )
    assert read_pay_program(program_id)["design_status"] == "DRAFT"
    for metric in env["metrics"]:
        assert read_metric(program_id, metric["id"])["status"] == "DRAFT"

    third = add_metric(program_id, "ADJ_EPS_LINEAR", metric_code="FCF", weight_pct=10.00)

    approved = validate_success(api_client.approve_pay_program(program_id, CHAIR), 200)
    assert approved["design_status"] == "COMMITTEE_APPROVED"

    locked = read_metrics(program_id)
    assert len(locked) == 3
    for metric in locked:
        assert metric["status"] == "LOCKED", (
            f"metric {metric['metric_code']} must lock on committee approval"
        )
    third_locked = read_metric(program_id, third["id"])
    assert_money(third_locked["locked_target_value"], 5.00, "locked_target_value")


def test_a_company_delisted_after_registration_cannot_be_added_as_a_peer():
    """Listing status is read at add time, not at registration time.

    PRD: "Delisting deliberately does *not* remove the company from peer groups
    that already reference it — existing memberships survive untouched, and only
    the creation of *new* memberships against a delisted peer is blocked, with
    `ERR_PEER_COMPANY_DELISTED`."

    Design: Corner/validations/a_company_delisted_after_registration_cannot_be_added_as_a_peer
    """
    env = setup_issuer()
    bravo = create_company("BRVO")
    charlie = create_company("CHRL")
    group = create_peer_group(env["issuer"]["id"])

    delisted = refresh_market_data(bravo["id"], listing_status="DELISTED")
    assert delisted["listing_status"] == "DELISTED"

    validate_error(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(bravo["id"], 1, "SIZE_MATCH"),
            CONSULTANT,
        ),
        ApiErrorId.ERR_PEER_COMPANY_DELISTED,
        422,
    )
    assert read_peer_group(group["id"])["version"] == 1, (
        "a rejected add must not mutate the group"
    )

    accepted = validate_success(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(charlie["id"], 1, "SIZE_MATCH"),
            CONSULTANT,
        ),
        201,
    )
    assert accepted["status"] == "ACCEPTED"
    assert read_peer_group(group["id"])["accepted_member_count"] == 1


def test_engagement_window_starting_before_now_is_refused_but_the_boundary_instant_is_not():
    """The window floor is at-or-after the logical now, not strictly after it.

    PRD: "An engagement that is not in `REQUESTED` is refused with
    `ERR_ENGAGEMENT_STATE_INVALID`, and a `window_start` strictly before the current
    logical time is refused with `ERR_ENGAGEMENT_WINDOW_IN_PAST`."

    Design: Corner/validations/an_engagement_window_starting_before_now_is_rejected_but_starting_exactly_now_is_not
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]
    engagement = create_engagement(program_id, "BlackRock", 20.00, "MEETING")

    set_clock("2027-03-10T00:00:00Z")

    validate_error(
        api_client.schedule_outreach_engagement(
            engagement["id"],
            schedule_engagement_payload("2027-03-01T00:00:00Z", "2027-03-12T00:00:00Z"),
            IR_LEAD,
        ),
        ApiErrorId.ERR_ENGAGEMENT_WINDOW_IN_PAST,
        422,
    )
    still_requested = read_engagement(program_id, engagement["id"])
    assert still_requested["engagement_status"] == "REQUESTED"
    assert still_requested.get("window_start") is None

    scheduled = validate_success(
        api_client.schedule_outreach_engagement(
            engagement["id"],
            schedule_engagement_payload("2027-03-10T00:00:00Z", "2027-03-12T00:00:00Z"),
            IR_LEAD,
        ),
        200,
    )
    assert scheduled["engagement_status"] == "SCHEDULED"
    assert _same_instant(scheduled["window_start"], "2027-03-10T00:00:00Z")
    assert _same_instant(scheduled["window_end"], "2027-03-12T00:00:00Z")

    # Scheduling alone contributes nothing to coverage.
    assert_money(
        read_pay_program(program_id)["outreach_coverage_pct"], 0.00, "outreach_coverage_pct"
    )


def test_out_of_band_peer_is_refused_under_size_match_but_admitted_under_the_analogue_waiver():
    """The band rule is conditional on the declared inclusion reason.

    PRD: "A candidate that fails either band is still admissible, but only on a
    documented rationale — an `inclusion_reason` of `BUSINESS_MODEL_ANALOG` or
    `TALENT_COMPETITOR` permits an out-of-band peer, whereas `SIZE_MATCH` or
    `INDUSTRY_MATCH` does not and the add is rejected with
    `ERR_PEER_OUTSIDE_SIZE_BAND`."

    Design: Corner/validations/an_out_of_band_peer_is_rejected_under_size_match_but_admitted_under_the_analogue_waiver
    """
    env = setup_issuer()
    foxtrot = create_company("FOXT")
    group = create_peer_group(env["issuer"]["id"])

    # 4,000,000,000 / 10,000,000,000 == 0.4000, below the 0.5 revenue floor.
    validate_error(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(foxtrot["id"], 1, "SIZE_MATCH"),
            CONSULTANT,
        ),
        ApiErrorId.ERR_PEER_OUTSIDE_SIZE_BAND,
        422,
    )

    waived = validate_success(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(foxtrot["id"], 1, "BUSINESS_MODEL_ANALOG"),
            CONSULTANT,
        ),
        201,
    )
    assert waived["inclusion_reason"] == "BUSINESS_MODEL_ANALOG"
    assert_ratio(waived["revenue_ratio"], 0.4000, "revenue_ratio")
    assert_ratio(waived["market_cap_ratio"], 0.4000, "market_cap_ratio")
    assert waived["in_size_band"] is False, (
        "the waiver suppresses the rejection without falsifying the measurement"
    )
    assert read_peer_group(group["id"])["accepted_member_count"] == 1
