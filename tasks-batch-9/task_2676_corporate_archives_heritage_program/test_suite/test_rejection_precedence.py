"""Which rung of the rejection ladder wins when two rules fail at once."""

from test_helpers import (
    OFFICER_B,
    PRESERV_B,
    factories as f,
    failed,
    fixtures as fx,
)
from test_helpers.api_errors import (
    ERR_FINDING_AID_NOT_PUBLISHED,
    ERR_JOB_STATE_INVALID,
)


def _fully_committed_plan(client):
    """A plan whose budget is exactly consumed by its one approved job."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 40, "condition_grade": "FAIR",
                     "original_format": "MAGNETIC_TAPE"}],
        zone_overrides={"temperature_c": 12.0, "relative_humidity_pct": 35.0,
                        "max_overlapping_migration_jobs": 2},
    )
    plan = fx.make_plan(client, holding.zone_id, budget_cents=175266)
    job = fx.make_job(
        client,
        plan["id"],
        holding.item_id,
        stage="APPROVED",
        units=40,
        target_format="PRESERVATION_MKV",
        approver=PRESERV_B,
    )
    return plan, job


def test_second_approval_of_one_job_reports_the_state_guard_not_the_budget(client):
    """PRD §2.6: "Rules are therefore evaluated in a fixed ladder, and the **first**
    rule that fails determines the response."
    PRD §2.6: "12. **State guard** — the target row must be in a state from which the
    requested transition is declared in §3."
    PRD §2.6: "36. **Preservation budget ceiling** — the plan's `budget_committed_cents`
    plus the job's `committed_cost_cents` must not exceed the plan's `budget_cents`;
    equality is permitted. Failure: `ERR_PRESERVATION_BUDGET_EXCEEDED` (422). Applies to
    `POST /migration-jobs/{id}/approve`."

    Design: Difficulty/priority_pair_validation_conflict/migration_approve_state_priority_beats_budget_fiscal_priority
    """
    _, job = _fully_committed_plan(client)
    assert job["status"] == "APPROVED"
    assert job["committed_cost_cents"] == 175266

    response = client.approve_migration_job(job["id"], PRESERV_B)
    failed(response, ERR_JOB_STATE_INVALID, 409)


def test_refused_second_approval_moves_no_money_on_the_plan(client):
    """PRD §2.10: "A preservation plan's `budget_committed_cents` must, after every
    single request including every cascade, equal the exact sum of `committed_cost_cents`
    over the migration jobs on that plan whose status is `APPROVED` or `IN_PROGRESS`."
    PRD §2.10: "Its `budget_spent_cents` must equal the exact sum of
    `committed_cost_cents` over the jobs on that plan whose status is `COMPLETED`."

    Design: Difficulty/priority_pair_validation_conflict/migration_approve_state_priority_beats_budget_fiscal_priority
    """
    plan, job = _fully_committed_plan(client)

    failed(client.approve_migration_job(job["id"], PRESERV_B), ERR_JOB_STATE_INVALID, 409)

    assert fx.read_job(client, job["id"])["status"] == "APPROVED"
    reloaded = fx.read_plan(client, plan["id"])
    assert reloaded["budget_committed_cents"] == 175266
    assert reloaded["budget_spent_cents"] == 0


def _high_risk_request_citing_a_draft_aid(client):
    """A screened MEDIA request at risk 80 citing an aid still in DRAFT."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "sensitivity_level": "CONFIDENTIAL"}],
        series_overrides={"sensitivity_ceiling": "CONFIDENTIAL"},
    )
    aid = fx.make_finding_aid(client, holding.accession_id)
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_FULL",
        redaction_required=False,
        finding_aid_id=aid["id"],
        requester_overrides={"requester_class": "MEDIA", "nda_on_file": False},
    )
    return aid, case


def test_unpublished_finding_aid_outranks_the_redaction_threshold(client):
    """PRD §2.6: "23. **Cited finding aid published** — when a request's
    `finding_aid_id` is not null, the referenced aid must be in `PUBLISHED` status.
    Failure: `ERR_FINDING_AID_NOT_PUBLISHED` (422). Applies to
    `POST /access-requests/{id}/approve`."
    PRD §2.6: "35. **Redaction required above the risk threshold** — a `FULL` approval
    requires the request's `post_screen_risk_score` to be strictly below the redaction
    threshold of 75; at or above it, only a `REDACTED` scope is permitted."

    Design: Difficulty/priority_pair_validation_conflict/access_approve_referential_priority_beats_risk_threshold_constraint
    """
    _, case = _high_risk_request_citing_a_draft_aid(client)
    assert case.request["post_screen_risk_score"] == 80

    response = client.approve_access_request(
        case.request_id, f.approve_request_payload("FULL"), OFFICER_B
    )
    failed(response, ERR_FINDING_AID_NOT_PUBLISHED, 422)


def test_refused_approval_leaves_the_request_unbilled_and_under_screening(client):
    """PRD §3.7: "Both branches stamp `decided_by` from `X-User-ID`, store the supplied
    `approval_scope`, and compute and store `service_fee_cents`."
    PRD §3.5: "The aid is created in `status` `DRAFT` with `described_item_count` and
    `stale_item_count` both 0, `revision_cycle_count` 0 and `published_at` null."

    Design: Difficulty/priority_pair_validation_conflict/access_approve_referential_priority_beats_risk_threshold_constraint
    """
    aid, case = _high_risk_request_citing_a_draft_aid(client)

    failed(
        client.approve_access_request(
            case.request_id, f.approve_request_payload("FULL"), OFFICER_B
        ),
        ERR_FINDING_AID_NOT_PUBLISHED,
        422,
    )

    request = fx.read_request(client, case.request_id)
    assert request["status"] == "SCREENING"
    assert request["service_fee_cents"] is None
    assert request["decided_by"] is None
    assert fx.read_finding_aid(client, aid["id"])["status"] == "DRAFT"
