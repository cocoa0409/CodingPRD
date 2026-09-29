"""Multi-hop cascades: hold suspension, plan satisfaction, description staleness."""

from test_helpers import (
    COUNSEL_A,
    DIRECTOR_A,
    DIRECTOR_B,
    OFFICER_B,
    PRESERV_A,
    PRESERV_B,
    fixtures as fx,
    ok,
)


def _series_with_request_under_screening(client):
    """A live request with an OPEN screening, plus a DRAFT hold over its series."""
    holding = fx.make_holding(client)
    case = fx.make_access_request(client, holding)
    fx.drive_to_screening(client, case)
    fx.open_screening(client, case)
    hold = fx.make_hold(client, holding.series_id)
    return holding, case, hold


def test_hold_activation_suspends_the_series_and_blocks_its_live_request(client):
    """PRD §3.3: "Hop one suspends the series. Whichever of `ACTIVE`,
    `ELIGIBLE_FOR_DISPOSITION` or `PERMANENT` the series currently occupies is copied
    verbatim into `pre_hold_disposition_state`, the series moves to `SUSPENDED`,
    `legal_hold_active` is set true, and the series' `version` increments with
    `updated_at` refreshed."
    PRD §3.3: "Hop two blocks the series' live access requests. Every access request
    whose `record_series_id` is the suspended series and whose status is `SUBMITTED`,
    `SCREENING` or `CHANGES_REQUESTED` moves to `BLOCKED` with `legal_hold_blocked` set
    true, and each such move increments the series' `blocked_access_request_count` by 1."

    Design: Difficulty/transitive_cascade/legal_hold_activation_three_hop_suspension_cascade
    """
    holding, case, hold = _series_with_request_under_screening(client)

    activated = ok(client.activate_legal_hold(hold["id"], COUNSEL_A))
    assert activated["status"] == "ACTIVE"

    series = fx.read_series(client, holding.series_id)
    assert series["disposition_state"] == "SUSPENDED"
    assert series["pre_hold_disposition_state"] == "ACTIVE"
    assert series["legal_hold_active"] is True
    assert series["blocked_access_request_count"] == 1

    request = fx.read_request(client, case.request_id)
    assert request["status"] == "BLOCKED"
    assert request["legal_hold_blocked"] is True


def test_hold_activation_supersedes_the_screening_two_entities_away(client):
    """PRD §3.3: "Hop three cleans up the screenings underneath. For every request that
    hop two moved out of `SCREENING` specifically, each confidentiality screening on
    that request still in `OPEN` moves to `SUPERSEDED` with `superseded_reason` set to
    `LEGAL_HOLD_BLOCK`."
    PRD §3.3: "The number of requests moved is stamped onto the hold as
    `suspended_access_request_count`."

    Design: Difficulty/transitive_cascade/legal_hold_activation_three_hop_suspension_cascade
    """
    _, case, hold = _series_with_request_under_screening(client)

    activated = ok(client.activate_legal_hold(hold["id"], COUNSEL_A))
    assert activated["suspended_access_request_count"] == 1

    screening = fx.read_screening(client, case.screening_id)
    assert screening["status"] == "SUPERSEDED"
    assert screening["superseded_reason"] == "LEGAL_HOLD_BLOCK"


def _tape_migration_in_progress(client):
    """A started job over the only at-risk holding of an active plan."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 10, "condition_grade": "GOOD",
                     "original_format": "MAGNETIC_TAPE"}],
        zone_overrides={"temperature_c": 14.0, "relative_humidity_pct": 40.0},
    )
    plan = fx.make_plan(client, holding.zone_id, budget_cents=100000)
    job = fx.make_job(
        client,
        plan["id"],
        holding.item_id,
        stage="IN_PROGRESS",
        units=10,
        target_format="PRESERVATION_MKV",
        approver=PRESERV_B,
    )
    return holding, plan, job


def test_migration_completion_writes_the_surrogate_onto_the_item(client):
    """PRD §3.6: "Completion is declared only from `IN_PROGRESS` and drives the two-hop
    preservation cascade. Hop one returns the item `IN_TREATMENT → ACCESSIONED` with
    `preservation_format` set to the job's `target_format` and
    `digital_surrogate_available` set true."

    Design: Difficulty/transitive_cascade/migration_completion_two_hop_plan_satisfaction_cascade
    """
    holding, plan, job = _tape_migration_in_progress(client)
    assert job["committed_cost_cents"] == 46000
    assert fx.read_plan(client, plan["id"])["at_risk_unit_count"] == 10

    completed = ok(client.complete_migration_job(job["id"], PRESERV_A))
    assert completed["status"] == "COMPLETED"

    item = fx.read_item(client, holding.item_id)
    assert item["status"] == "ACCESSIONED"
    assert item["preservation_format"] == "PRESERVATION_MKV"
    assert item["digital_surrogate_available"] is True


def test_migration_completion_satisfies_the_plan_and_moves_the_money(client):
    """PRD §3.6: "Hop two re-runs the at-risk census on the plan covering that item's
    zone, because the newly created surrogate takes the item out of the at-risk
    population; if the recomputed `at_risk_unit_count` reaches exactly 0 while the plan
    is `ACTIVE`, the plan auto-transitions `ACTIVE → SATISFIED` and stamps `satisfied_at`
    from the logical clock."
    PRD §3.6: "Completion also moves the job's `committed_cost_cents` out of the plan's
    `budget_committed_cents` and into `budget_spent_cents`."

    Design: Difficulty/transitive_cascade/migration_completion_two_hop_plan_satisfaction_cascade
    """
    _, plan, job = _tape_migration_in_progress(client)

    ok(client.complete_migration_job(job["id"], PRESERV_A))

    reloaded = fx.read_plan(client, plan["id"])
    assert reloaded["at_risk_unit_count"] == 0
    assert reloaded["status"] == "SATISFIED"
    assert reloaded["satisfied_at"] is not None
    assert reloaded["budget_committed_cents"] == 0
    assert reloaded["budget_spent_cents"] == 46000


def _described_accession_with_approved_request(client):
    """A published aid, an approved request citing it, and a cleared proposal."""
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 2, "sensitivity_level": "INTERNAL"},
            {"unit_count": 4, "sensitivity_level": "PUBLIC"},
        ],
        series_overrides={"sensitivity_ceiling": "INTERNAL"},
    )
    aid = fx.published_finding_aid(client, holding.accession_id)
    case = fx.approved_case(
        client,
        holding,
        item_ids=[holding.items[0]["id"]],
        finding_aid_id=aid["id"],
        requester_overrides={"requester_class": "INTERNAL_BUSINESS"},
        approver=OFFICER_B,
    )
    proposal = fx.make_proposal(
        client, holding.items[1]["id"], units=4, stage="DUALLY_CLEARED",
        legal_clearer=COUNSEL_A, heritage_clearer=DIRECTOR_A,
    )
    return holding, aid, case, proposal


def test_deaccession_approval_marks_the_item_and_its_finding_aid_stale(client):
    """PRD §3.9: "Approval stamps `approved_by` from `X-User-ID` and runs the three-hop
    staleness cascade. Hop one moves the item `ACCESSIONED → PENDING_DISPOSITION`, with
    no unit movement yet."
    PRD §3.9: "Hop two takes every finding aid over that item's accession sitting in
    `PUBLISHED` and moves it to `NEEDS_REVISION`, incrementing each aid's
    `stale_item_count` by 1; the number of aids moved is recorded on the proposal as
    `stale_finding_aid_count`."

    Design: Difficulty/transitive_cascade/deaccession_approval_three_hop_description_staleness_cascade
    """
    holding, aid, _, proposal = _described_accession_with_approved_request(client)

    approved = ok(client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B))
    assert approved["status"] == "APPROVED"
    assert approved["stale_finding_aid_count"] == 1

    assert fx.read_item(client, holding.items[1]["id"])["status"] == "PENDING_DISPOSITION"
    assert fx.read_item(client, holding.items[0]["id"])["status"] == "ACCESSIONED"

    reloaded_aid = fx.read_finding_aid(client, aid["id"])
    assert reloaded_aid["status"] == "NEEDS_REVISION"
    assert reloaded_aid["stale_item_count"] == 1


def test_deaccession_approval_sends_the_citing_request_for_revalidation(client):
    """PRD §3.9: "Hop three takes every access request whose `finding_aid_id` names one
    of the aids hop two just moved and which sits in `APPROVED` or in
    `PARTIALLY_APPROVED`, and moves it to `REVALIDATION_REQUIRED`; both source statuses
    behave identically, and the number of requests moved is recorded on the proposal as
    `revalidated_request_count`."

    Design: Difficulty/transitive_cascade/deaccession_approval_three_hop_description_staleness_cascade
    """
    _, _, case, proposal = _described_accession_with_approved_request(client)
    assert case.request["status"] == "APPROVED"
    assert case.request["post_screen_risk_score"] == 25
    assert case.request["service_fee_cents"] == 2500

    approved = ok(client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B))
    assert approved["revalidated_request_count"] == 1

    request = fx.read_request(client, case.request_id)
    assert request["status"] == "REVALIDATION_REQUIRED"
    assert request["service_fee_cents"] == 2500
    assert request["post_screen_risk_score"] == 25
