"""The qualifying gate that the first offer runs against the pinned performance."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    api_client,
    enroll_draft_invitation,
    offer_payload,
    read_invitation,
    register_agent,
    reject_performance,
    send_offer,
    setup_field_open_edition,
    validate_error,
    validate_paginated,
    verify_performance,
)

STANDARD_SECONDS = 8_100


def _edition_with_an_inclusive_standard():
    """A `FIELD_OPEN` edition whose ELITE MALE standard is 8,100 seconds and whose
    qualifying window is the default 24 months back from race day."""
    return setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "max_qualifying_seconds": STANDARD_SECONDS,
                    "bib_range_start": 11, "bib_range_end": 30}],
        name="Standard Boundary Marathon",
        race_date="2026-11-01",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )


def _draft(edition_id, agent, seconds, verified_seconds=None,
           performance_date="2026-03-01"):
    return enroll_draft_invitation(
        edition_id,
        agent=agent,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": seconds,
                               "performance_date": performance_date},
        verified_seconds=verified_seconds,
    )


def test_a_time_exactly_on_the_standard_qualifies_and_one_second_slower_does_not():
    """The qualifying comparison is inclusive at its upper bound.

    PRD §3.3: "The record's `verified_seconds` must be no slower than that
    standard's `max_qualifying_seconds`, so a time exactly equal to the standard
    still qualifies." A failure is reported thus: "Every failure of the record's
    verification state, its time, its date window or its timing technology is
    reported as `ERR_QUALIFYING_STANDARD_NOT_MET`."

    Design: Difficulty/boundary_precision_check/boundary_qualifying_standard_inclusive_and_window_edge_on_offer
    """
    scenario = _edition_with_an_inclusive_standard()
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Boundary Athletics")

    on_standard = _draft(edition_id, agent, STANDARD_SECONDS)
    offered = send_offer(on_standard["invitation"]["id"], **offer_payload())
    assert offered["status"] == "OFFERED", (
        "8,100 verified seconds against a standard of 8,100 satisfies it"
    )

    one_second_slow = _draft(edition_id, agent, 8_000,
                             verified_seconds=STANDARD_SECONDS + 1)
    response = api_client.send_offer(
        one_second_slow["invitation"]["id"], offer_payload(), DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_QUALIFYING_STANDARD_NOT_MET.value, 422)


def test_only_the_officially_verified_time_drives_eligibility():
    """The claimed time is ignored even when it would have qualified.

    PRD §3.2: "the claimed time is never used for anything"; verification sets
    "`verified_seconds` is set to that official figure, which may differ from what
    was claimed and is the only value any qualifying comparison ever reads."

    Design: Difficulty/boundary_precision_check/boundary_qualifying_standard_inclusive_and_window_edge_on_offer
    """
    scenario = _edition_with_an_inclusive_standard()
    agent = register_agent(agency_name="Boundary Athletics")
    corrected = _draft(scenario["edition"]["id"], agent, 8_000,
                       verified_seconds=STANDARD_SECONDS + 1)

    records, meta = validate_paginated(
        api_client.list_performance_records(corrected["athlete"]["id"], DIRECTOR)
    )
    assert meta["total_count"] == 1
    assert records[0]["performance_seconds"] == 8_000, "the athlete claimed 8,000"
    assert records[0]["verified_seconds"] == STANDARD_SECONDS + 1, (
        "the technical official corrected the time to 8,101"
    )

    response = api_client.send_offer(
        corrected["invitation"]["id"], offer_payload(), DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_QUALIFYING_STANDARD_NOT_MET.value, 422)


def test_the_qualifying_window_edge_is_inclusive_to_the_day():
    """A performance dated exactly the window's first day counts; one day earlier does not.

    PRD §3.3: "The `performance_date` must fall on or after the day obtained by
    subtracting the standard's `window_months` from the edition's `race_date`, and on
    or before the `race_date` itself; both endpoints are inclusive and the month
    subtraction keeps the same day of month, so with a two-year window a race dated
    the first of November 2026 accepts a performance run on the first of November
    2024."

    Design: Difficulty/boundary_precision_check/boundary_qualifying_standard_inclusive_and_window_edge_on_offer
    """
    scenario = _edition_with_an_inclusive_standard()
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Boundary Athletics")

    on_edge = _draft(edition_id, agent, 8_000, performance_date="2024-11-01")
    offered = send_offer(on_edge["invitation"]["id"], **offer_payload())
    assert offered["status"] == "OFFERED", (
        "2024-11-01 is exactly 24 months before race day and the edge is inclusive"
    )

    one_day_stale = _draft(edition_id, agent, 8_000, performance_date="2024-10-31")
    response = api_client.send_offer(
        one_day_stale["invitation"]["id"], offer_payload(), DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_QUALIFYING_STANDARD_NOT_MET.value, 422)


def _edition_with_unverified_drafts():
    """Two `DRAFT` invitations pinning performances that are still `SUBMITTED`,
    each fast enough on paper to clear the standard."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "max_qualifying_seconds": STANDARD_SECONDS,
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Verification Gate Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    agent = register_agent(agency_name="Gate Keeper Sports")
    scenario["agent"] = agent
    scenario["first"] = enroll_draft_invitation(
        scenario["edition"]["id"], agent=agent, verify=False,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900,
                               "performance_date": "2026-03-01"},
    )
    scenario["second"] = enroll_draft_invitation(
        scenario["edition"]["id"], agent=agent, verify=False,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900,
                               "performance_date": "2026-03-02"},
    )
    return scenario


def test_offer_waits_on_the_pinned_record_reaching_verified():
    """The same offer request is refused, then admitted, purely because the record moved.

    PRD §3.2: "New records begin with `verification_status` at `SUBMITTED` and
    `verified_seconds` at null." PRD §3.3 makes the offer depend on that other
    entity: "It also runs the qualifying gate against exactly one performance record
    — the one pinned on the invitation." That record "must be in `VERIFIED`", and the
    comparison reads `verified_seconds`, which is null while the claim is only
    submitted.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_offer_blocked_until_performance_record_verified
    """
    scenario = _edition_with_unverified_drafts()
    invitation_id = scenario["first"]["invitation"]["id"]
    record_id = scenario["first"]["record"]["id"]

    refused = api_client.send_offer(invitation_id, offer_payload(), DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_QUALIFYING_STANDARD_NOT_MET.value, 422)

    verified = verify_performance(record_id, 7_900)
    assert verified["verification_status"] == "VERIFIED"
    assert verified["verified_seconds"] == 7_900

    offered = send_offer(invitation_id, **offer_payload())
    assert offered["status"] == "OFFERED", (
        "the identical request now succeeds because the pinned record is VERIFIED"
    )
    assert offered["current_appearance_fee_cents"] == 500_000
    assert offered["guaranteed_commitment_cents"] == 0, (
        "in every status other than ACCEPTED, guaranteed_commitment_cents reads zero"
    )


def test_offer_is_refused_when_the_pinned_record_was_rejected():
    """A rejected qualifying claim is no better than an unverified one.

    PRD §3.2: "A `decision` of `REJECTED` must be accompanied by a
    `rejection_reason`, which is stored; the record moves `SUBMITTED → REJECTED` and
    can never qualify an invitation again." The invitation is untouched by the
    refusal, and PRD §3.3 fixes its starting state: an invitation "is created in
    `DRAFT` by an `ElitesDirector`".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_offer_blocked_until_performance_record_verified
    """
    scenario = _edition_with_unverified_drafts()
    invitation_id = scenario["second"]["invitation"]["id"]

    rejected = reject_performance(scenario["second"]["record"]["id"],
                                 "sanctioning reference does not resolve")
    assert rejected["verification_status"] == "REJECTED"
    assert rejected["verified_seconds"] is None

    response = api_client.send_offer(invitation_id, offer_payload(), DIRECTOR)
    validate_error(response, ApiErrorId.ERR_QUALIFYING_STANDARD_NOT_MET.value, 422)

    assert read_invitation(invitation_id)["status"] == "DRAFT", (
        "the invitation never left the state it was created in"
    )
