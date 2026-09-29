"""
The two version guards of this API, each on its own parent counter: a structure snapshot
that an acceptance cascade moved on cannot be rated, a cycle snapshot that a cascade
moved on cannot take a candidate, and both refusals are decided before the state and
eligibility questions the same request would otherwise raise.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

# A second window three full days clear of the canonical 2026-09-02 field day, so a
# second report on the same structure opens without touching the access buffer or the
# team leader's capacity.
LATER_WINDOW_START = "2026-09-06T08:00:00Z"
LATER_WINDOW_END = "2026-09-06T16:00:00Z"

# The cost of the four-row baseline report, priced by PRD §3.8: 3,600,000 for the deck,
# 19,000,000 for the girder, 520,000 for the bearing and nothing for the abutment,
# mobilised at 1.15.
BASELINE_CANDIDATE_COST_CENTS = 26588000


def test_a_structure_snapshot_taken_before_the_acceptance_cascade_cannot_rate(
    client, roster, bridge
):
    """
    The engineer's snapshot was accurate when it was taken and is stale one cascade later,
    so the create is refused on the version alone — and re-reading the structure makes the
    same body succeed, which is the whole remedy the guard asks for.

    PRD §2.9: "If that value does not equal the structure's current `version`, the create
    is rejected with `ERR_STALE_BRIDGE_VERSION` (HTTP 412)."
    PRD §2.9: "because so many operations advance a structure's `version` — every rating
    create, every rating approval, every restriction, every finding, every acceptance
    cascade, every scour finalisation, every inventory attribute edit — a client that
    computed its rating inputs from a structure snapshot must re-read that structure
    before rating it again."
    PRD §3.3: "its `bridge_health_index` is copied from the report's, its
    `inventoried_quantity_total` is set to the sum of `total_quantity` across the report's
    element rows, its `deficiency_pct` is recomputed from that same data, and its
    `version` is incremented by one."

    Design: Corner/complexity_layers/load_rating_create_against_stale_bridge_version_returns_412
    """
    stale_version = bridge["version"]

    accepted = fx.accepted_report(client, bridge["id"], roster)
    source_id = accepted["inspection"]["id"]
    fresh_version = fx.read_bridge_version(client, bridge["id"])
    a.assert_version_advanced_by(fresh_version, stale_version, 1, "bridge")

    body = f.load_rating_payload(stale_version, source_id)
    refused = client.create_load_rating(bridge["id"], body, roster.engineer_headers)

    validate_error(refused, e.ERR_STALE_BRIDGE_VERSION, 412)
    assert fx.ratings_for_bridge(client, bridge["id"])["meta"]["total_count"] == 0

    created = get_success_data(
        client.create_load_rating(
            bridge["id"],
            dict(body, expected_bridge_version=fresh_version),
            roster.engineer_headers,
        ),
        201,
    )

    assert created["rating_status"] == "DRAFT"
    assert created["source_inspection_id"] == source_id
    assert fx.ratings_for_bridge(client, bridge["id"])["meta"]["total_count"] == 1
    a.assert_version_advanced_by(
        fx.read_bridge_version(client, bridge["id"]), fresh_version, 1, "bridge"
    )


def test_the_version_a_successful_rating_consumed_is_itself_stale_afterwards(
    client, roster, bridge, accepted
):
    """
    The create is a write against the structure, so it invalidates the very version it was
    authorised by: the first rating computes the PRD's worked case from the severe girder
    and bearing quantities, and an identical replay is refused.

    PRD §3.4: "A newly created rating is `DRAFT`, with every derived value computed
    immediately from the submitted inputs, and creating it increments the structure's
    `version` by one."
    PRD §3.4: "A worst of good or fair yields a factor of 1.00, a worst of poor yields
    0.95, and a worst of severe yields 0.85."
    PRD §3.4: "The operating denominator is 1.35 times 500 times 1.33, which is 897.75,
    giving 0.6182…, rounded to 0.618, and 22.248, rounded to 22.2 tons."
    PRD §3.4: "When posting is required, `posted_limit_tons` is `inventory_rating_tons`
    quantised *downward* to the nearest half ton: double the inventory tonnage, discard
    the fractional part, and halve the result."

    Design: Corner/complexity_layers/load_rating_create_against_stale_bridge_version_returns_412
    """
    source_id = accepted["inspection"]["id"]
    version = fx.read_bridge_version(client, bridge["id"])
    body = f.load_rating_payload(version, source_id)

    rating = get_success_data(
        client.create_load_rating(bridge["id"], body, roster.engineer_headers), 201
    )

    assert rating["condition_factor_phi_c"] == 0.85
    assert rating["rating_factor_operating"] == 0.618
    assert rating["rating_factor_inventory"] == 0.477
    a.assert_three_decimals(rating["rating_factor_operating"], "rating_factor_operating")
    a.assert_three_decimals(rating["rating_factor_inventory"], "rating_factor_inventory")
    assert rating["operating_rating_tons"] == 22.2
    assert rating["inventory_rating_tons"] == 17.2
    assert rating["posting_required"] is True
    assert rating["posted_limit_tons"] == 17.0
    a.assert_half_ton_step(rating["posted_limit_tons"], "posted_limit_tons")

    replay = client.create_load_rating(bridge["id"], body, roster.engineer_headers)

    validate_error(replay, e.ERR_STALE_BRIDGE_VERSION, 412)
    assert fx.ratings_for_bridge(client, bridge["id"])["meta"]["total_count"] == 1


def test_the_stale_structure_version_is_reported_before_the_source_report_is_judged(
    client, roster, bridge
):
    """
    One request breaks two rules — a superseded snapshot and a source report that never
    reached acceptance — and the version answer comes back, because freshness is check
    seven and source acceptance is check twenty-seven. Repairing only the version then
    exposes the second fault.

    PRD §2.8: "7. **Structure version freshness** — `expected_bridge_version` matches the
    structure's current `version`, else `ERR_STALE_BRIDGE_VERSION` (412). Applies to
    load-rating creation."
    PRD §2.8: "A stale version check outranks every state and business check, so a client
    that has fallen behind learns that fact before it learns anything about the target's
    state."
    PRD §3.4: "The source report must be an `ACCEPTED` inspection belonging to the same
    structure the rating is being written against; a report on a different structure, or
    one that has not been accepted, is rejected with `ERR_RATING_SOURCE_NOT_ACCEPTED`."

    Design: Corner/complexity_layers/load_rating_create_against_stale_bridge_version_returns_412
    """
    stale_version = bridge["version"]
    fx.accepted_report(client, bridge["id"], roster)
    # The second report carries the full baseline element set — girder and bearing among
    # them — so the source report satisfies PRD §3.4's "That report must also carry at
    # least one `SUPERSTRUCTURE` element row" and the only remaining fault beside the
    # stale version is that the report has never been accepted. PRD §2.8 evaluates
    # element-group coverage (check 17) before rating source acceptance (check 27), so a
    # source report without a superstructure row would answer on the coverage rule
    # instead of the acceptance rule this test is about.
    drafted = fx.draft_report_with_baseline(
        client,
        bridge["id"],
        roster,
        field_window_start=LATER_WINDOW_START,
        field_window_end=LATER_WINDOW_END,
    )
    still_drafting = drafted["inspection"]
    assert still_drafting["status"] == "DRAFT"

    body = f.load_rating_payload(stale_version, still_drafting["id"])
    refused = client.create_load_rating(bridge["id"], body, roster.engineer_headers)

    validate_error(refused, e.ERR_STALE_BRIDGE_VERSION, 412)
    assert refused.json()["data"]["error_id"] != e.ERR_RATING_SOURCE_NOT_ACCEPTED

    fresh_version = fx.read_bridge_version(client, bridge["id"])
    second = client.create_load_rating(
        bridge["id"],
        dict(body, expected_bridge_version=fresh_version),
        roster.engineer_headers,
    )

    validate_error(second, e.ERR_RATING_SOURCE_NOT_ACCEPTED, 422)
    assert fx.ratings_for_bridge(client, bridge["id"])["meta"]["total_count"] == 0


# ─── The cycle guard, on its own counter ────────────────────────────────────
def _a_cycle_the_acceptance_cascade_moved_on(client, roster, bridge):
    """
    A `PLANNING` cycle whose version the district engineer read before an acceptance
    published a poor superstructure rating into it. The cascade's own candidate insert
    advances the cycle, so the engineer's snapshot is one behind.
    """
    cycle = fx.create_cycle(client)
    stale_version = cycle["version"]
    accepted = fx.accepted_report(client, bridge["id"], roster)
    return {
        "cycle": cycle,
        "stale_version": stale_version,
        "source_id": accepted["inspection"]["id"],
    }


def test_a_cycle_snapshot_taken_before_the_cascade_candidate_cannot_identify(
    client, roster, bridge
):
    """
    Nothing the engineer did moved the cycle — the acceptance did, by inserting its own
    candidate — and the manual identification is refused on the counter alone, leaving the
    cycle exactly as the cascade left it.

    PRD §2.9: "If it does not equal the cycle's current `version`, the create is rejected
    with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
    PRD §3.3: "**Hop 5**, caused by the candidate insert in hop 4, refreshes the owning
    cycle: its `identified_count` and `unprogrammed_cost_cents` are recomputed and its
    `version` is incremented by one."
    PRD §3.8: "A source report with a deck at 150 poor plus 50 severe, a girder at 100
    poor plus 100 severe, a bearing at 1 poor plus 1 severe and an abutment with nothing
    deficient prices at 3,600,000 for the deck, 19,000,000 for the girder, 520,000 for the
    bearing and 0 for the abutment, a subtotal of 23,120,000, which multiplied by 1.15
    gives 26,588,000 cents."

    Design: Corner/complexity_layers/candidate_create_against_stale_cycle_version_returns_412
    """
    state = _a_cycle_the_acceptance_cascade_moved_on(client, roster, bridge)
    cycle_id = state["cycle"]["id"]

    after_cascade = fx.read_cycle(client, cycle_id)
    a.assert_version_advanced_by(
        after_cascade["version"], state["stale_version"], 1, "program cycle"
    )
    assert after_cascade["identified_count"] == 1
    assert after_cascade["unprogrammed_cost_cents"] == BASELINE_CANDIDATE_COST_CENTS
    seeded = fx.candidates_in_cycle(client, cycle_id)
    assert len(seeded) == 1
    assert seeded[0]["origin"] == "AUTO_FROM_INSPECTION"

    body = f.candidate_payload(
        state["stale_version"],
        bridge["id"],
        source_inspection_id=state["source_id"],
        justification="Superstructure rating 3",
    )
    refused = client.create_project_candidate(cycle_id, body, roster.district_headers)

    validate_error(refused, e.ERR_STALE_CYCLE_VERSION, 412)
    held = fx.read_cycle(client, cycle_id)
    assert held["status"] == "PLANNING"
    assert held["identified_count"] == 1
    assert held["unprogrammed_cost_cents"] == BASELINE_CANDIDATE_COST_CENTS
    assert held["version"] == after_cascade["version"]
    assert len(fx.candidates_in_cycle(client, cycle_id)) == 1


def test_the_same_identification_replayed_against_the_fresh_cycle_version_supersedes(
    client, roster, bridge
):
    """
    The refusal was a version comparison and nothing more, so the identical body with the
    re-read counter is accepted — and because identification supersedes, the cascade's own
    candidate is withdrawn rather than duplicated while the identified count holds at one.

    PRD §3.8: "Creation supersedes: any prior candidate for the *same* structure and the
    *same* cycle whose `status` is `IDENTIFIED` is moved to `WITHDRAWN` with
    `withdrawn_at` stamped, because the new estimate replaces the old one."
    PRD §3.8: "A candidate created through this route records `origin` `MANUAL`; one
    created by the acceptance cascade of §3.3 records `origin` `AUTO_FROM_INSPECTION`."
    PRD §3.8: "a rating of 3 or below yields `REPLACEMENT`"
    PRD §3.8: "Under `CONDITION_BASED` the score is 17.265 plus 20.00 plus 6.146, which is
    43.411, rounded to 43.41."

    Design: Corner/complexity_layers/candidate_create_against_stale_cycle_version_returns_412
    """
    state = _a_cycle_the_acceptance_cascade_moved_on(client, roster, bridge)
    cycle_id = state["cycle"]["id"]
    auto_id = fx.candidates_in_cycle(client, cycle_id)[0]["id"]
    body = f.candidate_payload(
        state["stale_version"],
        bridge["id"],
        source_inspection_id=state["source_id"],
        justification="Superstructure rating 3",
    )
    validate_error(
        client.create_project_candidate(cycle_id, body, roster.district_headers),
        e.ERR_STALE_CYCLE_VERSION,
        412,
    )
    fresh_version = fx.read_cycle(client, cycle_id)["version"]

    manual = get_success_data(
        client.create_project_candidate(
            cycle_id,
            dict(body, expected_program_cycle_version=fresh_version),
            roster.district_headers,
        ),
        201,
    )

    assert manual["origin"] == "MANUAL"
    assert manual["status"] == "IDENTIFIED"
    assert manual["program_cycle_id"] == cycle_id
    assert manual["work_type"] == "REPLACEMENT"
    assert manual["estimated_cost_cents"] == BASELINE_CANDIDATE_COST_CENTS
    assert manual["priority_score"] == 43.41
    assert manual["ranking_policy_applied"] == "CONDITION_BASED"

    superseded = fx.read_candidate(client, auto_id)
    assert superseded["status"] == "WITHDRAWN"
    assert superseded["withdrawn_at"] is not None
    settled = fx.read_cycle(client, cycle_id)
    assert settled["identified_count"] == 1
    assert settled["unprogrammed_cost_cents"] == BASELINE_CANDIDATE_COST_CENTS
    a.assert_version_advanced_by(settled["version"], fresh_version, 1, "program cycle")
    a.assert_budget_identity(settled)


def test_the_stale_cycle_version_outranks_both_the_eligibility_and_the_state_check(
    client, roster, bridge
):
    """
    Substituting a structure that has never had a report accepted, and then locking the
    cycle out of planning, adds faults the request would otherwise be refused for — and
    the version answer is returned every time, because freshness is check eight while
    state gating is nine and condition-data existence is thirty-three.

    PRD §2.8: "8. **Cycle version freshness** — `expected_program_cycle_version` matches
    the cycle's current `version`, else `ERR_STALE_CYCLE_VERSION` (412). Applies to
    candidate creation."
    PRD §2.8: "33. **Condition data existence** — `ERR_BRIDGE_NOT_INSPECTED` (422).
    Applies to candidate creation."
    PRD §3.8: "The cycle must be in `PLANNING`, and the structure must have at least one
    `ACCEPTED` inspection; a structure that has never had a report accepted cannot be
    programmed and the attempt fails with `ERR_BRIDGE_NOT_INSPECTED`."
    PRD §3.8: "While locked, candidate identification, programming, withdrawal and
    deferral are all blocked — every one of those actions requires `PLANNING`."

    Design: Corner/complexity_layers/candidate_create_against_stale_cycle_version_returns_412
    """
    state = _a_cycle_the_acceptance_cascade_moved_on(client, roster, bridge)
    cycle_id = state["cycle"]["id"]
    never_inspected = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000002",
            name="Willow Slough Bridge",
            structure_type="CULVERT",
            deck_area_sqm=600,
            year_built=1988,
            adt=3000,
            detour_length_km=2.0,
        ),
    )
    body = f.candidate_payload(state["stale_version"], never_inspected["id"])

    ineligible = client.create_project_candidate(
        cycle_id, body, roster.district_headers
    )

    validate_error(ineligible, e.ERR_STALE_CYCLE_VERSION, 412)
    assert ineligible.json()["data"]["error_id"] != e.ERR_BRIDGE_NOT_INSPECTED

    locked = fx.lock_cycle(client, cycle_id)
    assert locked["status"] == "LOCKED"
    while_locked = client.create_project_candidate(
        cycle_id, body, roster.district_headers
    )

    validate_error(while_locked, e.ERR_STALE_CYCLE_VERSION, 412)
    assert while_locked.json()["data"]["error_id"] != e.ERR_PROGRAM_STATE_INVALID
    assert len(fx.candidates_in_cycle(client, cycle_id)) == 1
