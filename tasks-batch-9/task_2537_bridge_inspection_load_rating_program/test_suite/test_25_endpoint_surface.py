"""
The endpoint surface itself: the one fully mutable row type, the fan-out action that
materialises rows no client ever posts, the two computed projections, and the decision
that must agree with the analysis behind it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import (
    fhwa_reviewer_headers,
    permit_officer_headers,
    program_admin_headers,
)

FOUR_AXLES = [10.0, 10.0, 10.0, 6.0]
FIVE_AXLES = [8.25, 8.25, 8.25, 8.25, 6.4]

# The girder row after re-measurement: 100 good, 100 fair, 50 poor, 50 severe.
REMEASURED_GIRDER = f.element_update_payload(
    300,
    100,
    100,
    50,
    50,
    photo_count=8,
    defect_notes="Section loss re-measured after cleaning",
)


# ─── The one row type with a full CRUD surface ──────────────────────────────
def _deck_row_and_a_girder_row(client, roster, bridge):
    """A `DRAFT` report holding the deck row, plus a freshly created girder row."""
    inspection = fx.open_inspection(client, bridge["id"], roster)
    deck = fx.add_element(client, inspection["id"], roster, f.BASELINE_DECK)
    created = validate_success(
        client.create_element_condition(
            inspection["id"], f.BASELINE_GIRDER, roster.inspector_headers
        ),
        201,
    )
    return {"inspection": inspection, "deck": deck, "girder": created}


def test_the_created_row_reads_back_identically_to_any_role(client, roster, bridge):
    """
    Creation returns the fully derived row and the shared read grant lets a reviewer —
    not just the inspector who wrote it — fetch the same values back.

    PRD §4: "Read one element condition row".
    PRD §2.1: "Read access is broad: every retrieval and listing operation in the API
    is available to all seven roles."

    Design: Corner/endpoints/element_condition_create_read_update_delete_round_trip
    """
    setup = _deck_row_and_a_girder_row(client, roster, bridge)
    created = setup["girder"]

    assert created["element_health_index"] == 40.00
    assert created["reported_sum"] == 300
    assert created["balanced"] is True
    assert created["deficient_quantity"] == 200
    assert created["element_group"] == "SUPERSTRUCTURE"
    assert created["version"] == 1

    fetched = validate_success(
        client.get_element_condition(created["id"], roster.reviewer_headers), 200
    )
    assert fetched == created


def test_redistributing_the_row_recomputes_it_and_rerolls_the_report(
    client, roster, bridge
):
    """
    The update endpoint is the redistribution path: the row's index and deficient
    subtotal move, its version advances, and the parent report's rollups are refreshed
    in the same request.

    PRD §4: "Redistribute an element's condition-state quantities while the inspection
    is still DRAFT".
    PRD §3.2: "An inspector may redistribute quantities on an existing row while the
    report is still `DRAFT`, resupplying `total_quantity`, the four condition-state
    quantities and optionally `photo_count` and `defect_notes`; the row's four derived
    values and the report's five rollups are recomputed."

    Design: Corner/endpoints/element_condition_create_read_update_delete_round_trip
    """
    setup = _deck_row_and_a_girder_row(client, roster, bridge)

    updated = validate_success(
        client.update_element_condition(
            setup["girder"]["id"], REMEASURED_GIRDER, roster.inspector_headers
        ),
        200,
    )

    assert updated["element_health_index"] == 66.67
    assert updated["deficient_quantity"] == 100
    assert updated["defect_notes"] == "Section loss re-measured after cleaning"
    a.assert_version_advanced_by(
        updated["version"], setup["girder"]["version"], 1, "element condition"
    )

    report = fx.read_inspection(client, setup["inspection"]["id"])
    assert report["element_count"] == 2
    assert report["reported_quantity_total"] == 1300
    assert report["deficient_quantity_total"] == 300
    assert report["photo_count_total"] == 14


def test_deleting_the_row_rolls_the_report_back_to_the_line_that_remains(
    client, roster, bridge
):
    """
    Deletion is the only 204 in the API: the row becomes unreadable and the report's
    rollups fall back to the deck line alone, while the structure — which never saw any
    of this — is untouched.

    PRD §4: "Creation endpoints return HTTP 201, read and state-transition endpoints
    return HTTP 200, and the single deletion endpoint returns HTTP 204 with an empty
    data object."
    PRD §3.2: "An inspector may also delete a row from a `DRAFT` report, which likewise
    recomputes the report's rollups."

    Design: Corner/endpoints/element_condition_create_read_update_delete_round_trip
    """
    setup = _deck_row_and_a_girder_row(client, roster, bridge)

    response = client.delete_element_condition(
        setup["girder"]["id"], roster.inspector_headers
    )

    assert response.status_code == 204
    if response.content:
        assert response.json()["data"] == {}
    validate_error(
        client.get_element_condition(setup["girder"]["id"], program_admin_headers()),
        e.ERR_INSPECTION_RECORD_NOT_FOUND,
        404,
    )

    report = fx.read_inspection(client, setup["inspection"]["id"])
    assert report["element_count"] == 1
    assert report["reported_quantity_total"] == 1000
    assert report["deficient_quantity_total"] == 200
    assert report["photo_count_total"] == 6

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["version"] == 1
    assert structure["inventoried_quantity_total"] == 0


# ─── The analysis fan-out ───────────────────────────────────────────────────
def _two_unrated_structures(client):
    """Two structures, neither ever load-rated."""
    cedar = fx.create_bridge(client, f.bridge_payload("STR-000001", spans_water=True))
    willow = fx.create_bridge(
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
    return cedar, willow


def test_analysis_writes_one_row_per_route_entry_and_sinks_the_route(client):
    """
    Nobody posts an analysis row; the action materialises one per route entry. With no
    governing rating anywhere on the route, every row is refused for the same reason
    and a single denied structure sinks the recommendation.

    PRD §3.7: "It creates one analysis row per entry in `route_bridge_ids`, in array
    order, each carrying its `permit_application_id`, its `bridge_id`, a zero-based
    `sequence_index` recording its position in the route, and the
    `governing_load_rating_id` of the rating used."
    PRD §3.7: "Otherwise, if the structure has no governing rating,
    `rating_factor_permit` is null, `analysis_result` is `DENIED` and `result_reason` is
    `NO_APPROVED_RATING` — an unrated structure is not permissible, and the system never
    guesses a capacity."

    Design: Corner/endpoints/permit_analyze_action_materialises_one_row_per_route_bridge
    """
    cedar, willow = _two_unrated_structures(client)
    permit = fx.receive_permit(
        client,
        "OW-2026-0012",
        [cedar["id"], willow["id"]],
        axle_loads_tons=FOUR_AXLES,
        carrier_name="Northline Heavy Haul",
    )

    analysed = fx.analyze_permit(client, permit["id"])

    assert analysed["status"] == "ANALYZED"
    assert analysed["axle_count"] == 4
    assert analysed["gross_weight_tons"] == 36.0
    assert analysed["recommended_decision"] == "DENY"
    assert analysed["governing_analysis_min_rf"] is None
    assert analysed["decided_at"] is None
    assert analysed["revoked_at"] is None

    rows, meta = validate_paginated(
        client.list_permit_bridge_analyses(
            program_admin_headers(), {"permit_application_id": permit["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert {row["bridge_id"] for row in rows} == {cedar["id"], willow["id"]}
    for row in rows:
        assert row["governing_load_rating_id"] is None
        assert row["rating_factor_permit"] is None
        assert row["permit_live_load_kn_m"] is None
        assert row["analysis_result"] == "DENIED"
        assert row["result_reason"] == "NO_APPROVED_RATING"


def test_a_route_is_analysed_exactly_once(client):
    """
    The action is declared only from `RECEIVED`, so a second run is a state conflict
    and cannot duplicate the rows the first run wrote.

    PRD §3.7: "Running the analysis is a separate `PermitOfficer` action, permitted only
    from `RECEIVED`, so a route is analysed exactly once and cannot be re-analysed
    afterwards."
    PRD §2.8: "9. **State gating** — the target resource, and any parent whose state
    gates the operation, is in a state from which the requested transition is declared,
    else the family-scoped 409 conflict code".

    Design: Corner/endpoints/permit_analyze_action_materialises_one_row_per_route_bridge
    """
    cedar, willow = _two_unrated_structures(client)
    permit = fx.receive_permit(
        client,
        "OW-2026-0012",
        [cedar["id"], willow["id"]],
        axle_loads_tons=FOUR_AXLES,
        carrier_name="Northline Heavy Haul",
    )
    fx.analyze_permit(client, permit["id"])

    response = client.analyze_permit_application(permit["id"], permit_officer_headers())

    validate_error(response, e.ERR_PERMIT_STATE_INVALID, 409)
    assert validate_paginated(
        client.list_permit_bridge_analyses(
            program_admin_headers(), {"permit_application_id": permit["id"]}
        )
    )[1]["total_count"] == 2


# ─── The junction table, with a recrossing ──────────────────────────────────
def _out_and_back_route(client):
    """A movement that crosses the first structure, the second, then the first again."""
    cedar, willow = _two_unrated_structures(client)
    permit = fx.receive_permit(
        client,
        "OW-2026-0013",
        [cedar["id"], willow["id"], cedar["id"]],
        axle_loads_tons=FIVE_AXLES,
        carrier_name="Northline Heavy Haul",
    )
    analysed = fx.analyze_permit(client, permit["id"])
    return {"cedar": cedar, "willow": willow, "permit": analysed}


def test_a_recrossed_structure_earns_a_second_analysis_row(client):
    """
    The rows follow the array, not the set of distinct structures: a three-entry route
    over two structures produces three rows, one of them a second crossing of the
    first structure, and their zero-based positions preserve the route order.

    PRD §3.7: "Because the row is created per array entry rather than per distinct
    structure, a route that lists the same structure twice — a there-and-back movement,
    for example — produces two analysis rows for that structure, each with its own
    `sequence_index`, and both count in the aggregation."
    PRD §3.7: "Five axles of 8.25, 8.25, 8.25, 8.25 and 6.4 tons round individually to
    8.3, 8.3, 8.3, 8.3 and 6.4, which sum to 39.6 tons."

    Design: Corner/endpoints/permit_route_array_links_each_entry_including_repeats
    """
    setup = _out_and_back_route(client)
    permit = setup["permit"]

    assert permit["route_bridge_ids"] == [
        setup["cedar"]["id"],
        setup["willow"]["id"],
        setup["cedar"]["id"],
    ]
    assert permit["axle_count"] == 5
    assert permit["gross_weight_tons"] == 39.6

    rows, meta = validate_paginated(
        client.list_permit_bridge_analyses(
            program_admin_headers(), {"permit_application_id": permit["id"]}
        )
    )
    assert meta["total_count"] == 3
    by_sequence = sorted(rows, key=lambda row: row["sequence_index"])
    assert [row["sequence_index"] for row in by_sequence] == [0, 1, 2]
    assert [row["bridge_id"] for row in by_sequence] == [
        setup["cedar"]["id"],
        setup["willow"]["id"],
        setup["cedar"]["id"],
    ]


def test_the_junction_is_reachable_from_either_side(client):
    """
    Filtering by structure counts crossings rather than routes: the recrossed structure
    answers with both of its rows and the other with one.

    PRD §4: "List per-bridge permit analyses; the only discovery channel for rows
    created by the analyze cascade, and the reverse-reachability channel for
    permit_application_id, bridge_id and governing_load_rating_id".
    PRD §3.7: "Because the analysis rows are created by that run rather than by a client
    request, the per-bridge analysis list is the only way to discover them."

    Design: Corner/endpoints/permit_route_array_links_each_entry_including_repeats
    """
    setup = _out_and_back_route(client)

    recrossed, recrossed_meta = validate_paginated(
        client.list_permit_bridge_analyses(
            program_admin_headers(), {"bridge_id": setup["cedar"]["id"]}
        )
    )
    once, once_meta = validate_paginated(
        client.list_permit_bridge_analyses(
            program_admin_headers(), {"bridge_id": setup["willow"]["id"]}
        )
    )

    assert recrossed_meta["total_count"] == 2
    assert once_meta["total_count"] == 1
    assert {row["permit_application_id"] for row in recrossed + once} == {
        setup["permit"]["id"]
    }
    assert setup["permit"]["status"] == "ANALYZED"


# ─── The two computed projections ───────────────────────────────────────────
def test_the_compliance_projection_restates_the_settled_structure(
    client, roster, bridge
):
    """
    After the acceptance the projection is pure derivation over the structure's settled
    state: the poor superstructure rating pulls the cycle down to a year, and the due
    date is a calendar year past the observation date.

    PRD §2.11: "If the structure's `min_nbi_rating` is 4 or lower, the base is 12
    months."
    PRD §2.11: "`next_inspection_due_date` is `last_routine_inspection_date` advanced by
    `inspection_interval_months`; before the first routine acceptance the base date is
    the structure's creation date."

    Design: Corner/endpoints/bridge_compliance_summary_computed_read_after_acceptance
    """
    fx.accepted_report(client, bridge["id"], roster)

    summary = validate_success(
        client.get_compliance_summary(bridge["id"], fhwa_reviewer_headers()), 200
    )

    assert summary["bridge_id"] == bridge["id"]
    assert summary["min_nbi_rating"] == 3
    assert summary["bridge_health_index"] == 65.47
    assert summary["inspection_interval_months"] == 12
    a.assert_date_equals(
        summary["next_inspection_due_date"], "2027-09-02", "next_inspection_due_date"
    )
    assert summary["routine_overdue"] is False
    assert summary["underwater_overdue"] is False
    assert summary["next_underwater_due_date"] is None
    assert summary["poa_compliant"] is True
    assert summary["open_critical_finding_count"] == 0
    assert summary["service_posture"] == "OPEN"


def test_reading_the_projection_twice_changes_nothing(client, roster, bridge):
    """
    The projection is a read, not a write: a second identical call answers identically
    and the structure's version does not move between them.

    PRD §4: "Computed read: the structure's current NBIS compliance picture".
    PRD §2.5: "Any request that changes a resource's stored state — including
    reconciliation of derived fields caused by an operation on a *different* resource —
    refreshes that resource's `updated_at` and increments its `version`."

    Design: Corner/endpoints/bridge_compliance_summary_computed_read_after_acceptance
    """
    fx.accepted_report(client, bridge["id"], roster)
    before = fx.read_bridge(client, bridge["id"])

    first = fx.read_compliance(client, bridge["id"])
    second = fx.read_compliance(client, bridge["id"])

    assert first == second
    after = fx.read_bridge(client, bridge["id"])
    a.assert_version_unchanged(after["version"], before["version"], "structure")
    assert first["bridge_health_index"] == before["bridge_health_index"]
    assert first["min_nbi_rating"] == before["min_nbi_rating"]


def _one_identified_candidate_against_a_fresh_cycle(client, roster, bridge):
    """
    The canonical acceptance first, then the cycle, so the acceptance cascade found no
    planning cycle and the only candidate is the one the district files by hand.
    """
    accepted = fx.accepted_report(client, bridge["id"], roster)
    cycle = fx.create_cycle(client, fiscal_year=2027, ranking_policy="CONDITION_BASED")
    candidate = fx.identify_candidate(
        client,
        cycle["id"],
        bridge["id"],
        roster,
        source_inspection_id=accepted["inspection"]["id"],
        justification="Superstructure rating 3 with quantified CS4 girder loss",
    )
    return {"cycle": cycle, "candidate": candidate}


def test_the_allocation_projection_separates_the_pipeline_from_the_commitment(
    client, roster, bridge
):
    """
    An identified candidate is a priced intention, not a commitment: its estimate shows
    up as unprogrammed pipeline while the committed and remaining money stay exactly
    where the cycle opened them.

    PRD §3.8: "Alongside them, `unprogrammed_cost_cents` is the sum of
    `estimated_cost_cents` over the cycle's `IDENTIFIED` candidates."
    PRD §3.8: "A computed read exposes the whole picture in one shot: the cycle's
    `program_cycle_id`, its `authorized_budget_cents`, `reserve_cents`,
    `available_cents`, `committed_cents` and `remaining_cents`, its `identified_count`,
    `programmed_count` and `deferred_count`, its `unprogrammed_cost_cents`, and an
    `identity_holds` boolean reporting whether the budget identity currently balances."

    Design: Corner/endpoints/program_cycle_allocation_summary_computed_read
    """
    setup = _one_identified_candidate_against_a_fresh_cycle(client, roster, bridge)

    summary = fx.read_allocation(client, setup["cycle"]["id"])

    assert summary["authorized_budget_cents"] == 10000000000
    assert summary["reserve_cents"] == 500000000
    assert summary["available_cents"] == 9500000000
    assert summary["committed_cents"] == 0
    assert summary["remaining_cents"] == 9500000000
    assert summary["identified_count"] == 1
    assert summary["programmed_count"] == 0
    assert summary["deferred_count"] == 0
    assert summary["unprogrammed_cost_cents"] == 26588000
    assert summary["unprogrammed_cost_cents"] == setup["candidate"][
        "estimated_cost_cents"
    ]
    assert summary["identity_holds"] is True
    a.assert_allocation_summary_matches_cycle(
        summary, fx.read_cycle(client, setup["cycle"]["id"])
    )


def test_the_candidate_behind_the_projection_is_priced_and_ranked(
    client, roster, bridge
):
    """
    The pipeline figure is not a free-standing number: it is this candidate's estimate,
    priced from the deficient quantities of the accepted report and ranked under the
    cycle's own policy.

    PRD §3.8: "A source report with a deck at 150 poor plus 50 severe, a girder at 100
    poor plus 100 severe, a bearing at 1 poor plus 1 severe and an abutment with nothing
    deficient prices at 3,600,000 for the deck, 19,000,000 for the girder, 520,000 for
    the bearing and 0 for the abutment, a subtotal of 23,120,000, which multiplied by
    1.15 gives 26,588,000 cents."
    PRD §3.8: "The `CONDITION_BASED` variant is the default statewide preservation
    ranking and uses condition inputs only: 0.50 times the condition gap, plus 0.30
    times the rating gap, plus 0.20 times the structure's `deficiency_pct`."

    Design: Corner/endpoints/program_cycle_allocation_summary_computed_read
    """
    setup = _one_identified_candidate_against_a_fresh_cycle(client, roster, bridge)
    candidate = setup["candidate"]

    assert candidate["origin"] == "MANUAL"
    assert candidate["status"] == "IDENTIFIED"
    assert candidate["work_type"] == "REPLACEMENT"
    assert candidate["ranking_policy_applied"] == "CONDITION_BASED"
    assert candidate["estimated_cost_cents"] == 26588000
    assert candidate["priority_score"] == 43.41
    a.assert_two_decimals(candidate["priority_score"], "priority_score")
    assert candidate["program_cycle_id"] == setup["cycle"]["id"]


# ─── A decision that must agree with its analysis ────────────────────────────
def _one_analysed_route_the_analysis_denied(client):
    """A single-structure route over an unrated bridge, already analysed.

    The logical clock is pinned first, because PRD §3.7 stamps `decided_at` "from the
    logical clock" and PRD §2.4 says "Before any client sets it, the logical clock reads
    exactly `2026-08-01T00:00:00Z`" — an unpinned clock would leave the stamp at that
    startup default rather than at the instant this scenario means to read.
    """
    fx.pin_base_clock(client)
    cedar = fx.create_bridge(client, f.bridge_payload("STR-000001", spans_water=True))
    permit = fx.receive_permit(
        client,
        "OW-2026-0014",
        [cedar["id"]],
        axle_loads_tons=FOUR_AXLES,
        carrier_name="Northline Heavy Haul",
    )
    return fx.analyze_permit(client, permit["id"])


def test_the_officer_may_not_approve_what_the_analysis_denied(client):
    """
    The decision is not discretionary: against a `DENY` recommendation an approval is
    refused, and the application is left exactly as the analysis left it.

    PRD §3.7: "The decision **must equal** the analysis-derived `recommended_decision`;
    an officer may not approve a movement the analysis denied, nor deny one it approved,
    nor waive conditions the analysis attached. A mismatch is
    `ERR_PERMIT_DECISION_MISMATCH`."
    PRD §2.8: "29. **Permit decision agreement** — `ERR_PERMIT_DECISION_MISMATCH` (422).
    Applies to the permit decision."

    Design: Corner/endpoints/permit_decide_allowed_only_when_it_matches_the_recommendation
    """
    permit = _one_analysed_route_the_analysis_denied(client)
    assert permit["recommended_decision"] == "DENY"

    response = client.decide_permit_application(
        permit["id"],
        f.permit_decision_payload("APPROVE", decision_note="Carrier has an escort plan"),
        permit_officer_headers(),
    )

    validate_error(response, e.ERR_PERMIT_DECISION_MISMATCH, 422)
    unchanged = validate_success(
        client.get_permit_application(permit["id"], permit_officer_headers()), 200
    )
    assert unchanged["status"] == "ANALYZED"
    assert unchanged["decided_at"] is None
    assert unchanged["decision_note"] is None


def test_the_matching_denial_lands_and_is_terminal(client):
    """
    The decision that agrees with the analysis is accepted, stamped from the clock, and
    final: the same denial cannot be issued twice.

    PRD §3.7: "A matching decision moves the application `ANALYZED → APPROVED`,
    `ANALYZED → APPROVED_WITH_CONDITIONS` or `ANALYZED → DENIED`, stamps `decided_at`
    from the logical clock, and stores the `decision_note`. `DENIED` is terminal."
    PRD §2.8: "9. **State gating** — the target resource, and any parent whose state
    gates the operation, is in a state from which the requested transition is declared,
    else the family-scoped 409 conflict code".

    Design: Corner/endpoints/permit_decide_allowed_only_when_it_matches_the_recommendation
    """
    permit = _one_analysed_route_the_analysis_denied(client)

    decided = fx.decide_permit(
        client,
        permit["id"],
        "DENY",
        decision_note="No approved load rating on the route",
    )

    assert decided["status"] == "DENIED"
    assert decided["decision_note"] == "No approved load rating on the route"
    a.assert_instant_equals(decided["decided_at"], c.BASE_CLOCK, "decided_at")

    again = client.decide_permit_application(
        permit["id"],
        f.permit_decision_payload("DENY"),
        permit_officer_headers(),
    )
    validate_error(again, e.ERR_PERMIT_STATE_INVALID, 409)
    assert (
        validate_success(
            client.get_permit_application(permit["id"], permit_officer_headers()), 200
        )["status"]
        == "DENIED"
    )
