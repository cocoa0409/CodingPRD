"""
State-machine journeys: legal edges walked end to end, the cascades a single
transition fires into neighbouring aggregates, and the refusals that guard
states no transition leaves from.
"""

from test_helpers import (
    PORTAL_ADMIN_HEADERS,
    assert_common_fields,
    assert_credit_buckets,
    assert_credit_conservation,
    assert_dataset_states,
    assert_money,
    assert_posture,
    assert_priority,
    assert_settlement,
    factories,
    find_showcase_app,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)

# A low-value dataset: 0.45*20 + 0.35*20 is 16.00 as declared, so TIER_3 from the start.
LIBRARY_DATASET = {
    "title": "Library Circulation Weekly",
    "slug": "library-circulation",
    "description": "Weekly circulation totals by branch.",
    "public_demand_score": 20,
    "policy_value_score": 20,
}

PARKS_DEPARTMENT = {
    "name": "City Parks Department",
    "code": "PARKS",
    "contact_email": "opendata@parks.city.gov",
}

# A MONTHLY dataset published on the same day is not due until 2026-08-31.
PARKS_DATASET = {
    "title": "Park Visitor Counts",
    "slug": "park-visitor-counts",
    "description": "Monthly gate counts for regional parks.",
    "update_frequency": "MONTHLY",
    "public_demand_score": 20,
    "policy_value_score": 20,
}

PARKS_METADATA = {"declared_update_frequency": "MONTHLY"}


def _moderate_showcase_entry(api, dataset_id, label, approve):
    """Moderate one inline showcase entry and return the moderation response data.

    §3.8 documents the moderation body as carrying a `decision` and pins the entry
    states it produces — `APPROVED` or `REJECTED` — without spelling the token that
    selects them, so both the imperative and the participle spelling are offered
    here. The rule under test is the ledger sync that follows the moderation, not
    the spelling of the token.
    """
    tokens = ("APPROVE", "APPROVED") if approve else ("REJECT", "REJECTED")
    response = api.decide_showcase_app(
        dataset_id, label, factories.decision_payload(tokens[0]), PORTAL_ADMIN_HEADERS
    )
    if response.status_code >= 400:
        response = api.decide_showcase_app(
            dataset_id, label, factories.decision_payload(tokens[1]), PORTAL_ADMIN_HEADERS
        )
    return validate_success(response)


def test_deferred_request_returns_to_open_with_its_votes_and_is_accepted_next_time(api):
    """The deferral cycle genuinely re-enters OPEN, and the second review needs no new vote.

    The PRD: "The programme office takes a sufficiently supported request under review,
    moving it `OPEN → UNDER_REVIEW`, which requires `weighted_vote_total` to have reached at
    least 4 — anything below that is refused with `ERR_INSUFFICIENT_DEMAND` — and which
    stores the optional `decision_note` supplied with it." and "A `DEFER` decision moves it
    `UNDER_REVIEW → OPEN`, deliberately preserving every stored vote so the request can be
    reviewed again once more demand accrues; the `OPEN → UNDER_REVIEW → OPEN` deferral cycle
    may repeat."

    Both members open at `reputation_score` 50.00, which carries `vote_weight` 2, so the two
    votes put `weighted_vote_total` at exactly the floor of 4 and `demand_signal` at 20.00.
    The deferral keeps both stored votes, so the second review clears that same floor without
    another vote, and "An `ACCEPT` decision moves the request `UNDER_REVIEW → ACCEPTED`."
    closes the walk. Seven mutations touch the row — the create, the two votes, two reviews,
    the deferral and the acceptance — and `version` is "a counter that starts at 1 on creation
    and increments by exactly 1 on every mutation of that row", so it lands on 7.
    `linked_dataset_id` stays null: it is fulfilment, not acceptance, that sets it.

    Design: Corner/state_machines/dataset_request_review_defer_and_accept_path
    """
    fixtures.reset_clock_to_start(api=api)
    first = fixtures.setup_member(api=api, email="ana@civic.example", display_name="Ana Reuser")
    second = fixtures.setup_member(api=api, email="bo@civic.example", display_name="Bo Steward")
    request_id = fixtures.open_dataset_request(first["member_id"], api=api)["id"]
    fixtures.cast_vote(request_id, first["member_id"], api=api)
    voted = fixtures.cast_vote(request_id, second["member_id"], api=api)

    assert voted["weighted_vote_total"] == 4, (
        f"Two votes of weight 2 must sum to weighted_vote_total 4, "
        f"got {voted['weighted_vote_total']}"
    )
    assert_money(voted["demand_signal"], 20.00, "demand_signal")

    under_review = validate_success(
        api.review_dataset_request(request_id, PORTAL_ADMIN_HEADERS, {"decision_note": "First pass"})
    )
    assert under_review["status"] == "UNDER_REVIEW", (
        f"The first review must move the request to UNDER_REVIEW, got {under_review['status']}"
    )
    assert under_review["decision_note"] == "First pass", (
        f"The review must store the supplied decision_note, got {under_review['decision_note']!r}"
    )

    deferred = fixtures.decide_request(
        request_id, "DEFER", api=api, decision_note="Revisit next quarter"
    )
    assert deferred["status"] == "OPEN", (
        f"A DEFER decision must return the request to OPEN, got {deferred['status']}"
    )
    assert deferred["decision_note"] == "Revisit next quarter", (
        f"The deferral note must be stored, got {deferred['decision_note']!r}"
    )
    assert deferred["weighted_vote_total"] == 4, (
        f"Deferral must preserve every stored vote, so weighted_vote_total stays 4, "
        f"got {deferred['weighted_vote_total']}"
    )
    assert_money(deferred["demand_signal"], 20.00, "demand_signal")

    reviewed_again = validate_success(
        api.review_dataset_request(
            request_id, PORTAL_ADMIN_HEADERS, {"decision_note": "Second pass"}
        )
    )
    assert reviewed_again["status"] == "UNDER_REVIEW", (
        f"The preserved votes must carry the request back into UNDER_REVIEW, "
        f"got {reviewed_again['status']}"
    )
    assert reviewed_again["decision_note"] == "Second pass", (
        f"The second review note must overwrite the first, "
        f"got {reviewed_again['decision_note']!r}"
    )

    accepted = fixtures.decide_request(
        request_id, "ACCEPT", api=api, decision_note="Accepted for the FY27 plan"
    )
    assert accepted["status"] == "ACCEPTED", (
        f"An ACCEPT decision must move the request to ACCEPTED, got {accepted['status']}"
    )
    assert accepted["decision_note"] == "Accepted for the FY27 plan", (
        f"The acceptance note must be stored, got {accepted['decision_note']!r}"
    )
    assert accepted["linked_dataset_id"] is None, (
        f"Acceptance alone links no dataset, got {accepted['linked_dataset_id']!r}"
    )
    assert accepted["weighted_vote_total"] == 4, (
        f"The two original votes must still stand, got {accepted['weighted_vote_total']}"
    )
    assert_common_fields(accepted, expected_version=7)


def test_deciding_an_untriaged_issue_is_refused_and_fires_no_hop_of_the_cascade(api):
    """A SUBMITTED issue cannot be accepted, so not one hop of the acceptance cascade runs.

    The PRD: "An `ACCEPT` decision moves the issue `TRIAGED → ACCEPTED`, is blocked when the
    department's posture is `SUSPENDED`, and heads a four-hop cascade." The only edge into
    `ACCEPTED` starts at `TRIAGED`, and §2.7 priority 13 governs an attempt from anywhere
    else: "Transition legality, on every state-changing endpoint: the target resource is in a
    state from which the requested transition exists." The refusal is
    `ERR_INVALID_STATE_TRANSITION` at 409 — the department's posture is `OPEN`, so the higher
    priority-33 posture gate cannot pre-empt it.

    Nothing may move: the issue stays `SUBMITTED` with no `accepted_at` and no
    `correction_due_at`, the dataset stays `PUBLISHED` because hop two never fires, the
    reporter keeps `accepted_issue_count` 0 and the base `reputation_score` of 50.00, and the
    department keeps `remediation_dataset_count` 0 and posture `OPEN`.

    Design: Corner/state_machines/issue_decide_from_submitted_without_triage_returns_4XX
    """
    ctx = fixtures.setup_published_dataset(api=api)
    member = fixtures.setup_member(api=api)
    issue = fixtures.file_quality_issue(
        ctx["dataset_id"], member["member_id"], severity="CRITICAL", category="PRIVACY", api=api
    )
    assert issue["status"] == "SUBMITTED", (
        f"A freshly filed issue must start SUBMITTED, got {issue['status']}"
    )

    validate_error(
        api.decide_quality_issue(
            issue["id"], factories.decision_payload("ACCEPT"), ctx["coordinator_headers"]
        ),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    unchanged = validate_success(api.get_quality_issue(issue["id"], PORTAL_ADMIN_HEADERS))
    assert unchanged["status"] == "SUBMITTED", (
        f"The refused decision must leave the issue SUBMITTED, got {unchanged['status']}"
    )
    assert unchanged.get("accepted_at") is None, (
        f"Hop one must not stamp accepted_at, got {unchanged.get('accepted_at')!r}"
    )
    assert unchanged.get("correction_due_at") is None, (
        f"Hop one must not set correction_due_at, got {unchanged.get('correction_due_at')!r}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED")
    assert dataset["public_access_suspended"] is False, (
        f"Hop two must not suspend public access, got {dataset['public_access_suspended']!r}"
    )

    reporter = fixtures.read_member(member["member_id"], api=api)
    assert reporter["accepted_issue_count"] == 0, (
        f"Expected accepted_issue_count 0, got {reporter['accepted_issue_count']}"
    )
    assert_money(reporter["reputation_score"], 50.00, "reputation_score")

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(department, remediation=0, risk_points=0, compliance_posture="OPEN")


def test_resubmitting_an_already_accepted_metadata_record_is_refused(api):
    """The submit edge starts at DRAFT only, so an ACCEPTED record cannot be resubmitted.

    The PRD: "Submitting the record moves it `DRAFT → SUBMITTED`; it requires that the acting
    coordinator own the dataset's department and that the dataset's `publication_status` be
    exactly `SCREENING`, and it recomputes `component_contributions` and `completeness_score`
    one final time before the reviewer sees them." Both of those preconditions still hold
    here — the coordinator owns the department and the dataset is still in `SCREENING` — so
    the only failing guard is §2.7 priority 13, "Transition legality, on every state-changing
    endpoint: the target resource is in a state from which the requested transition exists",
    which refuses with `ERR_INVALID_STATE_TRANSITION` at 409.

    The record's own figures must survive intact: 9 of 9 documented columns give 30.00, 24 of
    24 provenance lines give 20.00, an at-sign in the contact gives 15.00, a declared
    `WEEKLY` cadence matching the dataset gives 15.00, a live licence gives 10.00 and 6 of 6
    attribution elements give 10.00, summing to `completeness_score` 100.00. The rejected call
    is not a mutation, so it leaves `version` where the successful acceptance left it.

    Design: Corner/state_machines/metadata_submit_from_accepted_returns_4XX
    """
    ctx = fixtures.setup_screening_dataset(api=api)
    record = fixtures.land_accepted_metadata(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    assert record["status"] == "ACCEPTED", (
        f"The ladder must land the record in ACCEPTED, got {record['status']}"
    )
    version_before = record["version"]

    validate_error(
        api.submit_metadata_record(record["id"], ctx["coordinator_headers"]),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    unchanged = validate_success(api.get_metadata_record(record["id"], PORTAL_ADMIN_HEADERS))
    assert unchanged["status"] == "ACCEPTED", (
        f"The refused submission must leave the record ACCEPTED, got {unchanged['status']}"
    )
    assert_money(unchanged["completeness_score"], 100.00, "completeness_score")
    assert unchanged["version"] == version_before, (
        f"A rejected request is not a mutation, so version must stay {version_before}, "
        f"got {unchanged['version']}"
    )


def test_a_newly_inventoried_dataset_starts_inventoried_and_current(api):
    """Creation seeds both state dimensions at once, each at its own initial state.

    The PRD: "A newly inventoried dataset sits at `publication_status` `INVENTORIED` and
    `currency_status` `CURRENT`, with `public_access_suspended` and `high_value_committed`
    both false, `engagement_index` and `observed_demand_score` both 0.00, `usage_epochs` and
    `showcase_apps` both empty, `live_row_count` and `version_index_high_water` and
    `days_overdue` and `staleness_alert_count` all zero, and `last_published_at`,
    `next_due_at`, `last_staleness_alert_at` and `remediation_opened_at` all null."

    `next_due_at` is null here for the reason §3.9 gives — it "is null both when
    `update_frequency` is `IRREGULAR` and when the dataset has never been published" — which
    is what keeps the currency dimension at `CURRENT` on a dataset that has no freshness
    promise to keep yet.

    Design: Corner/state_machines/dataset_created_starts_inventoried_and_current
    """
    ctx = fixtures.setup_funded_department(api=api, credit_units=0)

    created = validate_success(
        api.create_dataset(
            factories.dataset_payload(ctx["department_id"]), ctx["coordinator_headers"]
        ),
        201,
    )

    assert_dataset_states(created, publication_status="INVENTORIED", currency_status="CURRENT")
    assert created["last_published_at"] is None, (
        f"A dataset that has never published must have last_published_at null, "
        f"got {created['last_published_at']!r}"
    )
    assert created["next_due_at"] is None, (
        f"A dataset that has never published must have next_due_at null, "
        f"got {created['next_due_at']!r}"
    )
    assert created["days_overdue"] == 0, (
        f"Expected days_overdue 0, got {created['days_overdue']}"
    )
    assert created["staleness_alert_count"] == 0, (
        f"Expected staleness_alert_count 0, got {created['staleness_alert_count']}"
    )
    assert created["public_access_suspended"] is False, (
        f"Expected public_access_suspended false, got {created['public_access_suspended']!r}"
    )
    assert created["remediation_opened_at"] is None, (
        f"Expected remediation_opened_at null, got {created['remediation_opened_at']!r}"
    )
    assert created["live_row_count"] == 0, (
        f"Expected live_row_count 0, got {created['live_row_count']}"
    )
    assert created["version_index_high_water"] == 0, (
        f"Expected version_index_high_water 0, got {created['version_index_high_water']}"
    )
    assert_common_fields(created, expected_version=1)


def test_publishing_a_retired_dataset_is_refused_by_the_terminal_lockdown(api):
    """RETIRED accepts nothing further, not even a second retirement.

    The PRD: "`RETIRED` is terminal; nothing moves a dataset out of it." §2.7 priority 13
    spells out the consequence: "Terminal states are locked down — a `RETIRED` dataset, a
    `CLOSED` or `REJECTED` quality issue, a `DECOMMISSIONED` pipeline, a `SUCCEEDED` or
    `SKIPPED` run, a `RETRACTED` version and a `DECLINED` or `FULFILLED` request all accept
    no further transitions." The refusal carries `ERR_INVALID_STATE_TRANSITION` at 409, and
    priority 13 outranks the readiness gate at 14 and the embargo gate at 19, so the
    lockdown — not a missing precondition — is what answers.

    Retirement already set `public_access_suspended` to true, and because no new version may
    be minted the row keeps the 50000 rows and the `version_index_high_water` of 1 that the
    single successful publication left behind.

    Design: Corner/state_machines/publish_attempt_on_retired_dataset_returns_4XX
    """
    ctx = fixtures.setup_published_dataset(api=api, initial_row_count=50000)
    retired = validate_success(
        api.retire_dataset(
            ctx["dataset_id"], ctx["coordinator_headers"], {"reason": "Superseded by a new series."}
        )
    )
    assert_dataset_states(retired, publication_status="RETIRED")

    validate_error(
        api.publish_dataset(
            ctx["dataset_id"], factories.publish_payload(initial_row_count=60000), ctx["coordinator_headers"]
        ),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    unchanged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(unchanged, publication_status="RETIRED")
    assert unchanged["public_access_suspended"] is True, (
        f"Retirement must leave public access suspended, "
        f"got {unchanged['public_access_suspended']!r}"
    )
    assert unchanged["live_row_count"] == 50000, (
        f"No version may be minted, so live_row_count stays 50000, "
        f"got {unchanged['live_row_count']}"
    )
    assert unchanged["version_index_high_water"] == 1, (
        f"No version may be minted, so version_index_high_water stays 1, "
        f"got {unchanged['version_index_high_water']}"
    )

    validate_error(
        api.retire_dataset(ctx["dataset_id"], ctx["coordinator_headers"]),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )


def test_screening_a_dataset_already_in_screening_is_refused(api):
    """The screening edge leaves INVENTORIED only, so it cannot be walked twice.

    The PRD: "Moving a dataset out of raw inventory is the coordinator's declaration that
    readiness review has started: the dataset advances `INVENTORIED → SCREENING`." A second
    call finds the dataset in a state that edge does not leave from, which §2.7 priority 13
    refuses: "Transition legality, on every state-changing endpoint: the target resource is
    in a state from which the requested transition exists." The error is
    `ERR_INVALID_STATE_TRANSITION` at 409 — and it outranks nothing else here, since the
    coordinator owns the department and the posture is `OPEN`.

    The one successful screening already did its work — it "re-scores `priority_score` under
    the `AS_DECLARED` variant and stamps `priority_score_variant` accordingly, makes the
    dataset eligible for catalog-page usage reporting, and increments the dataset's
    `version`" — so the row stands at `version` 2, the create plus that screening, and the
    refused call adds nothing.

    Design: Corner/state_machines/second_screen_call_on_screening_dataset_returns_4XX
    """
    ctx = fixtures.setup_screening_dataset(api=api)
    assert_dataset_states(ctx["dataset"], publication_status="SCREENING")

    validate_error(
        api.screen_dataset(ctx["dataset_id"], ctx["coordinator_headers"]),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )

    unchanged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(unchanged, publication_status="SCREENING")
    assert_priority(unchanged, priority_score_variant="AS_DECLARED")
    assert_common_fields(unchanged, expected_version=2)


def test_currency_ages_to_aging_while_the_publication_dimension_holds_at_published(api):
    """The two dataset dimensions move independently: currency drifts, publication does not.

    The PRD: currency "is `AGING` when `days_overdue` is greater than zero but no greater
    than the grace allowance; the boundary is inclusive, so a `days_overdue` exactly equal to
    the grace is still `AGING` and one day beyond it is `STALE`." The grace comes off the
    stored tier — "2 days for `TIER_1`, 7 days for `TIER_2`, 14 days for `TIER_3`" — and at
    publication "`engagement_index` is recomputed and then `priority_score` is recomputed
    under the `AS_OBSERVED` variant with `priority_score_variant` set to `AS_OBSERVED`", which
    with no usage reported at all gives 0.45 times 0.00 plus 0.35 times 20 plus nothing for
    community pressure: 7.00, so `TIER_3` and a grace of 14 days.

    Published on 2026-08-01 with a `WEEKLY` cadence, `next_due_at` is 2026-08-08, and a clock
    at 2026-08-20 puts the dataset 12 days overdue — inside the 14-day grace, so `AGING` and
    no more. The publication dimension is untouched, and because
    "A dataset that merely became `AGING` emits nothing", `staleness_alert_count` stays 0 and
    the department's `stale_dataset_count` stays 0, leaving `risk_points` 0 and the posture
    `OPEN`. The sweep
    reports the one currency change it made and no alert.

    Design: Corner/state_machines/currency_dimension_ages_while_publication_status_holds
    """
    ctx = fixtures.setup_published_dataset(
        api=api, dataset_overrides=LIBRARY_DATASET, initial_row_count=12000
    )
    published = ctx["dataset"]
    assert_priority(published, priority_score=7.00, priority_score_variant="AS_OBSERVED", priority_tier="TIER_3")
    assert_dataset_states(published, publication_status="PUBLISHED", currency_status="CURRENT")

    report = fixtures.advance_clock_and_sweep("2026-08-20T00:00:00Z", api=api)

    assert report["currency_transitions"] == 1, (
        f"Exactly one dataset changed currency in step one, so currency_transitions must be 1, "
        f"got {report['currency_transitions']}"
    )
    assert report["staleness_alerts_emitted"] == 0, (
        f"A dataset that merely became AGING emits nothing, so staleness_alerts_emitted must "
        f"be 0, got {report['staleness_alerts_emitted']}"
    )

    aged = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(aged, publication_status="PUBLISHED", currency_status="AGING")
    assert aged["days_overdue"] == 12, (
        f"2026-08-08 to 2026-08-20 is 12 whole days overdue, got {aged['days_overdue']}"
    )
    assert_priority(aged, priority_score=7.00, priority_score_variant="AS_OBSERVED", priority_tier="TIER_3")
    assert aged["staleness_alert_count"] == 0, (
        f"AGING emits no alert, so staleness_alert_count must stay 0, "
        f"got {aged['staleness_alert_count']}"
    )
    assert aged["last_staleness_alert_at"] is None, (
        f"AGING emits no alert, so last_staleness_alert_at must stay null, "
        f"got {aged['last_staleness_alert_at']!r}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(department, stale=0, breached=0, risk_points=0, compliance_posture="OPEN")


def test_retiring_a_published_dataset_decommissions_its_pipeline_and_skips_its_run(api):
    """One retirement walks three machines and hands the escrow back to the department.

    The PRD: "From `PUBLISHED` the transition `PUBLISHED → RETIRED` additionally cascades:
    every pipeline of the dataset whose `status` is `ARMED` or `SUSPENDED` becomes
    `DECOMMISSIONED` and releases its `escrowed_credit_units` back into the department's
    `credit_balance_units`, every run of those pipelines whose `status` is `SCHEDULED` or
    `RETRY_QUEUED` becomes `SKIPPED` with a `skip_reason` of `DATASET_RETIRED`, and the
    department's counters, `risk_points` and `compliance_posture` are re-derived." The edge
    the pipeline takes is the one §3.5 describes: "From `ARMED`, `ARMED → DECOMMISSIONED`
    releases the escrow — the pipeline's current `escrowed_credit_units` are added back to
    the department's `credit_balance_units` and subtracted from its `credits_escrowed_units`,
    and the pipeline's `escrowed_credit_units` is set to 0.00 — moves every `SCHEDULED` or
    `RETRY_QUEUED` run to `SKIPPED` with a `skip_reason` of `PIPELINE_DECOMMISSIONED`,
    decreases the runner's `armed_window_count` by 1, and increments the pipeline's
    `version`", with the reason resolved by §3.6 to
    "`DATASET_RETIRED` when the cascade came from the dataset being retired".

    A `WEEKLY` cadence over the thirty-day horizon implies 30 divided by 7 rounded up, so 5
    runs at 2 credits each: an escrow of 10.00 was taken from the 100.00 grant at arming
    time. No run ever settled, so the release restores the department exactly — balance
    100.00, escrowed 0.00, consumed 0.00 — and with no stale or remediating dataset left the
    posture stays `OPEN`.

    Design: Corner/state_machines/dataset_retire_cascades_pipeline_decommission_and_run_skip
    """
    ctx = fixtures.setup_armed_pipeline(api=api, credit_units=100.00)
    armed = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert_money(armed["escrowed_credit_units"], 10.00, "escrowed_credit_units")
    run = fixtures.schedule_run(ctx["pipeline_id"], "2026-08-01T09:00:00Z", api=api)
    assert run["status"] == "SCHEDULED", (
        f"The run must be waiting in SCHEDULED before the retirement, got {run['status']}"
    )

    retired = validate_success(
        api.retire_dataset(
            ctx["dataset_id"], ctx["coordinator_headers"], {"reason": "Series discontinued."}
        )
    )

    assert_dataset_states(retired, publication_status="RETIRED")
    assert retired["public_access_suspended"] is True, (
        f"Retirement must suspend public access, got {retired['public_access_suspended']!r}"
    )

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "DECOMMISSIONED", (
        f"The ARMED pipeline must be decommissioned by the cascade, got {pipeline['status']}"
    )
    assert_money(pipeline["escrowed_credit_units"], 0.00, "escrowed_credit_units")

    skipped = fixtures.read_run(run["id"], api=api)
    assert skipped["status"] == "SKIPPED", (
        f"The pending run must be skipped by the cascade, got {skipped['status']}"
    )
    assert skipped["skip_reason"] == "DATASET_RETIRED", (
        f"A cascade from a retired dataset must set skip_reason DATASET_RETIRED, "
        f"got {skipped['skip_reason']!r}"
    )

    runner = validate_success(api.get_ingest_runner(ctx["runner_id"], PORTAL_ADMIN_HEADERS))
    assert runner["armed_window_count"] == 0, (
        f"Leaving ARMED must decrease armed_window_count to 0, "
        f"got {runner['armed_window_count']}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=100.00, escrowed=0.00, consumed=0.00)
    assert_credit_conservation(department)
    assert_posture(department, stale=0, remediation=0, risk_points=0, compliance_posture="OPEN")


def test_approving_a_showcase_entry_credits_the_submitter_reputation_ledger(api):
    """Approving one entry syncs a ledger on another aggregate; rejecting the next credits nothing.

    The PRD: "The programme office then moderates the entry by addressing it by its label and
    supplying a `decision`, which sets that entry's `status` to `APPROVED` or `REJECTED` and
    stamps its `decided_at`. On approval the submitter's `approved_showcase_count` increases
    by 1 and their `reputation_score` and `vote_weight` are re-derived; a rejection credits
    nothing."

    The reputation figure follows §3.7: "The raw figure starts from a base of 50, adds 6
    points for each accepted issue in `accepted_issue_count`, subtracts 4 points for each
    rejected issue in `rejected_issue_count`, and adds 2 points for each approved showcase in
    `approved_showcase_count`." One approval gives 50 plus 2, and with the clock still at the
    member's own registration instant `decay_epochs` is 0, so the whole distance from the base
    survives: `reputation_score` 52.00, which sits in the band that carries `vote_weight` 2.
    The second entry's rejection moves neither figure, and the dataset's analytics read counts
    only the approved entry.

    Design: Corner/state_machines/showcase_approval_syncs_member_reputation_ledger
    """
    ctx = fixtures.setup_published_dataset(api=api)
    member_ctx = fixtures.setup_member(api=api)
    member_id = member_ctx["member_id"]
    registered_at = member_ctx["member"]["created_at"]
    fixtures.submit_showcase_app(
        ctx["dataset_id"], member_id, "corridor-map", api=api, name="Corridor Delay Map"
    )
    fixtures.submit_showcase_app(
        ctx["dataset_id"], member_id, "delay-widget", api=api, name="Delay Widget"
    )

    _moderate_showcase_entry(api, ctx["dataset_id"], "corridor-map", approve=True)

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    approved = find_showcase_app(dataset, "corridor-map")
    assert approved["status"] == "APPROVED", (
        f"The moderated entry must reach APPROVED, got {approved['status']}"
    )
    assert is_iso8601_timestamp(approved.get("decided_at") or ""), (
        f"Moderation must stamp decided_at, got {approved.get('decided_at')!r}"
    )

    credited = fixtures.read_member(member_id, api=api)
    assert credited["approved_showcase_count"] == 1, (
        f"One approval must raise approved_showcase_count to 1, "
        f"got {credited['approved_showcase_count']}"
    )
    assert_money(credited["reputation_score"], 52.00, "reputation_score")
    assert credited["vote_weight"] == 2, (
        f"A reputation of 52.00 sits in the vote_weight 2 band, got {credited['vote_weight']}"
    )
    assert credited["last_credited_at"] == registered_at, (
        f"With the clock still at the registration instant last_credited_at must read "
        f"{registered_at!r}, got {credited['last_credited_at']!r}"
    )

    _moderate_showcase_entry(api, ctx["dataset_id"], "delay-widget", approve=False)

    after_rejection = fixtures.read_dataset(ctx["dataset_id"], api=api)
    rejected = find_showcase_app(after_rejection, "delay-widget")
    assert rejected["status"] == "REJECTED", (
        f"The second entry must reach REJECTED, got {rejected['status']}"
    )

    uncredited = fixtures.read_member(member_id, api=api)
    assert uncredited["approved_showcase_count"] == 1, (
        f"A rejection credits nothing, so approved_showcase_count stays 1, "
        f"got {uncredited['approved_showcase_count']}"
    )
    assert_money(uncredited["reputation_score"], 52.00, "reputation_score")

    analytics = fixtures.read_analytics(ctx["dataset_id"], api=api)
    assert analytics["approved_showcase_count"] == 1, (
        f"Analytics counts approved entries only, so expected 1, "
        f"got {analytics['approved_showcase_count']}"
    )


def test_suspending_a_pipeline_skips_the_pending_run_and_spares_the_succeeded_one(api):
    """The skip cascade reads each child's own state: the SCHEDULED run goes, the SUCCEEDED one stays.

    The PRD: "The transition `ARMED → SUSPENDED` may be requested directly, in which case
    `suspend_reason` is `ADMIN_REQUEST`", and "However it arrives, its effects are the same:
    `escrowed_credit_units` are retained and remain counted in the department's
    `credits_escrowed_units`; the runner's `armed_window_count` decreases by 1 while the
    window itself stays reserved against the cooldown buffer; every run of the pipeline whose
    `status` is `SCHEDULED` or `RETRY_QUEUED` becomes `SKIPPED` with a `skip_reason` of
    `PIPELINE_SUSPENDED`; the dataset's `currency_status` takes the `STALE` floor and its
    `staleness_alert_count` increases by 1; the department's `stale_dataset_count`,
    `risk_points` and `compliance_posture` are re-derived; and the pipeline's `version`
    increments." The already-settled run is out of reach: "No credits are charged for a
    skipped run. `SUCCEEDED` and `SKIPPED` are both terminal."

    The settled charge is re-derived from §3.6: 45000 rows over 10000 rows per unit is 4.5,
    rounded up to 5 units at 4 credits each, so `compute_credits` 20.00 with no alert; a
    subtotal of 20.00 keys the 0.05 tier, giving a 1.00 discount and `total_charge_credits`
    19.00. The waterfall draws the pipeline's whole 10.00 escrow — a `WEEKLY` cadence over
    thirty days implies 5 runs at 2 credits — and the remaining 9.00 from the balance, so the
    department stands at 81.00 available, 0.00 escrowed and 19.00 consumed, and the pipeline
    has nothing left to retain. The suspension's `STALE` floor applies even though the run
    left the dataset fresh: `days_overdue` is 0 and the clock says `CURRENT`, but the more
    severe of the two verdicts is stored.

    Design: Corner/state_machines/pipeline_suspend_skips_scheduled_run_but_spares_succeeded_run
    """
    ctx = fixtures.setup_armed_pipeline(api=api, credit_units=100.00)
    fixtures.set_clock("2026-08-01T09:00:00Z", api=api)
    first_run = fixtures.schedule_run(ctx["pipeline_id"], "2026-08-01T09:00:00Z", api=api)
    second_run = fixtures.schedule_run(ctx["pipeline_id"], "2026-08-01T09:00:00Z", api=api)
    fixtures.start_run(first_run["id"], api=api)
    settled = fixtures.report_success(first_run["id"], 45000, api=api)
    assert settled["status"] == "SUCCEEDED", (
        f"The first run must settle successfully before the suspension, got {settled['status']}"
    )

    suspended = fixtures.suspend_pipeline(ctx["pipeline_id"], ctx["department_id"], api=api)

    assert suspended["status"] == "SUSPENDED", (
        f"A direct suspension must land the pipeline in SUSPENDED, got {suspended['status']}"
    )
    assert suspended["suspend_reason"] == "ADMIN_REQUEST", (
        f"A directly requested suspension carries suspend_reason ADMIN_REQUEST, "
        f"got {suspended['suspend_reason']!r}"
    )
    assert_money(suspended["escrowed_credit_units"], 0.00, "escrowed_credit_units")

    skipped = fixtures.read_run(second_run["id"], api=api)
    assert skipped["status"] == "SKIPPED", (
        f"The still-SCHEDULED run must be skipped, got {skipped['status']}"
    )
    assert skipped["skip_reason"] == "PIPELINE_SUSPENDED", (
        f"Expected skip_reason PIPELINE_SUSPENDED, got {skipped['skip_reason']!r}"
    )

    spared = fixtures.read_run(first_run["id"], api=api)
    assert spared["status"] == "SUCCEEDED", (
        f"SUCCEEDED is terminal, so the settled run must be untouched, got {spared['status']}"
    )
    assert spared["skip_reason"] is None, (
        f"The spared run must carry no skip_reason, got {spared['skip_reason']!r}"
    )
    assert_settlement(
        spared, total_charge_credits=19.00, escrow_drawn_units=10.00, balance_drawn_units=9.00
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="STALE")
    assert dataset["days_overdue"] == 0, (
        f"The clock is not past the due date, so days_overdue stays 0 under the pipeline "
        f"floor, got {dataset['days_overdue']}"
    )
    assert dataset["live_row_count"] == 45000, (
        f"The successful run rolled the dataset forward to 45000 rows, "
        f"got {dataset['live_row_count']}"
    )
    assert dataset["staleness_alert_count"] == 1, (
        f"The suspension raises staleness_alert_count to 1, "
        f"got {dataset['staleness_alert_count']}"
    )

    runner = validate_success(api.get_ingest_runner(ctx["runner_id"], PORTAL_ADMIN_HEADERS))
    assert runner["armed_window_count"] == 0, (
        f"Suspension releases the window count to 0, got {runner['armed_window_count']}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(department, issued=100.00, balance=81.00, escrowed=0.00, consumed=19.00)
    assert_credit_conservation(department)


def test_rejecting_an_issue_moves_the_reporter_counters_and_nothing_else(api):
    """Rejection is confined to the reporter: no dataset, pipeline or department effect fires.

    The PRD: "A `REJECT` decision requires a `reject_reason` of `NOT_REPRODUCIBLE`,
    `OUT_OF_SCOPE` or `DUPLICATE`, moves the issue `TRIAGED → REJECTED`, increases the
    reporter's `rejected_issue_count` by 1, sets the reporter's `last_credited_at` to the
    current logical instant, and re-derives the reporter's `reputation_score`, `vote_weight`
    and `status` — which is where a member can tip from `ACTIVE` into `THROTTLED`. No dataset
    or pipeline side effect fires at all."

    The raw figure "subtracts 4 points for each rejected issue in `rejected_issue_count`", so
    one rejection gives 50 minus 4 and, with `decay_epochs` 0, `reputation_score` 46.00 —
    still in the band that carries `vote_weight` 2. The member stays `ACTIVE` because
    `status` only becomes `THROTTLED` once rejections minus acceptances reaches 3, and this
    is 1. The `CRITICAL`/`PRIVACY` pair that would have driven the acceptance cascade four
    hops deep leaves the dataset `PUBLISHED` and publicly readable, the pipeline `ARMED`,
    the currency `CURRENT` and the department at `risk_points` 0 with posture `OPEN`.

    Design: Corner/state_machines/issue_rejection_adjusts_member_counters_without_touching_dataset
    """
    ctx = fixtures.setup_armed_pipeline(api=api, credit_units=100.00)
    member = fixtures.setup_member(api=api)
    issue = fixtures.file_and_triage_issue(
        ctx["dataset_id"],
        member["member_id"],
        ctx["department_id"],
        severity="CRITICAL",
        category="PRIVACY",
        api=api,
    )
    assert issue["status"] == "TRIAGED", (
        f"The issue must be TRIAGED before the decision, got {issue['status']}"
    )

    rejected = fixtures.reject_quality_issue(
        issue["id"], ctx["department_id"], reject_reason="NOT_REPRODUCIBLE", api=api
    )

    assert rejected["status"] == "REJECTED", (
        f"A REJECT decision must move the issue to REJECTED, got {rejected['status']}"
    )
    assert rejected["reject_reason"] == "NOT_REPRODUCIBLE", (
        f"The supplied reject_reason must be stored, got {rejected['reject_reason']!r}"
    )

    reporter = fixtures.read_member(member["member_id"], api=api)
    assert reporter["rejected_issue_count"] == 1, (
        f"Expected rejected_issue_count 1, got {reporter['rejected_issue_count']}"
    )
    assert reporter["accepted_issue_count"] == 0, (
        f"Expected accepted_issue_count 0, got {reporter['accepted_issue_count']}"
    )
    assert_money(reporter["reputation_score"], 46.00, "reputation_score")
    assert reporter["vote_weight"] == 2, (
        f"A reputation of 46.00 sits in the vote_weight 2 band, got {reporter['vote_weight']}"
    )
    assert reporter["status"] == "ACTIVE", (
        f"One net rejection is short of the throttling threshold of 3, "
        f"got {reporter['status']}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="PUBLISHED", currency_status="CURRENT")
    assert dataset["public_access_suspended"] is False, (
        f"No dataset side effect may fire, got public_access_suspended "
        f"{dataset['public_access_suspended']!r}"
    )
    assert dataset["remediation_opened_at"] is None, (
        f"No remediation may open, got remediation_opened_at {dataset['remediation_opened_at']!r}"
    )

    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "ARMED", (
        f"No pipeline side effect may fire, got {pipeline['status']}"
    )
    assert pipeline["suspend_reason"] is None, (
        f"The pipeline must carry no suspend_reason, got {pipeline['suspend_reason']!r}"
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_posture(department, remediation=0, stale=0, risk_points=0, compliance_posture="OPEN")


def test_one_department_staleness_leaves_the_peer_department_posture_untouched(api):
    """The recomputation travels child to parent and stops at the owning parent.

    The PRD: currency "is `STALE` when `days_overdue` exceeds the grace but does not exceed
    twice the grace", and the sweep's last step is where that reaches the parent: "Step five
    walks the departments in ascending `created_at` order — deliberately after every dataset
    has been recomputed in step one — re-deriving each department's four counters, its
    `risk_points` and its `compliance_posture`." The counter itself is scoped by ownership:
    "`stale_dataset_count` is the number of the department's datasets whose `currency_status`
    is `STALE` and whose `publication_status` is `PUBLISHED` or `UNDER_REMEDIATION`."

    The transport dataset publishes on 2026-08-01 with a `WEEKLY` cadence, so it is due on
    2026-08-08; publication re-scores it under `AS_OBSERVED`, where the observed demand of
    0.00 leaves 0.35 times 96, so 33.60 and `TIER_3` with a grace of 14 days. The first sweep
    at 2026-08-20 finds it 12 days overdue and only `AGING`. The second, at 2026-08-25, finds
    it 17 days overdue — past the grace but inside twice it — so `STALE`, and since "every
    dataset that is entering or remaining in `STALE` or `BREACHED` emits exactly one alert
    per sweep", one alert is emitted. "`risk_points` is then three points for each breached
    dataset, plus two points for each stale dataset, plus two points for each dataset under
    remediation, plus one point for each overdue correction", so transport lands on 2 points,
    and "From `risk_points` the posture follows on inclusive boundaries: at least 6 points is
    `SUSPENDED`, from 2 through 5 points is `RESTRICTED`, and 1 point or 0 points is `OPEN`."
    The parks dataset is `MONTHLY` and not due until 2026-08-31, so it stays `CURRENT` and its
    department keeps 0 points and `OPEN`.

    Design: Corner/state_machines/dataset_staleness_bubbles_up_only_to_its_own_department
    """
    transport = fixtures.setup_published_dataset(api=api)
    parks_department = fixtures.register_department(api=api, **PARKS_DEPARTMENT)
    parks_id = parks_department["id"]
    parks_dataset_id = fixtures.inventory_dataset(parks_id, api=api, **PARKS_DATASET)["id"]
    fixtures.screen_dataset(parks_dataset_id, parks_id, api=api)
    fixtures.land_accepted_metadata(
        parks_dataset_id, transport["license_id"], parks_id, api=api, **PARKS_METADATA
    )
    fixtures.land_cleared_assessment(parks_dataset_id, api=api)
    fixtures.mark_ready(parks_dataset_id, parks_id, api=api)
    fixtures.publish_dataset(parks_dataset_id, parks_id, initial_row_count=8000, api=api)
    assert_priority(
        fixtures.read_dataset(transport["dataset_id"], api=api),
        priority_score=33.60,
        priority_score_variant="AS_OBSERVED",
        priority_tier="TIER_3",
    )

    fixtures.advance_clock_and_sweep("2026-08-20T00:00:00Z", api=api)
    aging = fixtures.read_dataset(transport["dataset_id"], api=api)
    assert_dataset_states(aging, currency_status="AGING")
    assert aging["days_overdue"] == 12, (
        f"2026-08-08 to 2026-08-20 is 12 whole days overdue, got {aging['days_overdue']}"
    )
    assert_posture(
        fixtures.read_department(transport["department_id"], api=api),
        risk_points=0,
        compliance_posture="OPEN",
    )

    report = fixtures.advance_clock_and_sweep("2026-08-25T00:00:00Z", api=api)

    assert report["datasets_recomputed"] == 2, (
        f"Both published datasets participate in step one, got {report['datasets_recomputed']}"
    )
    assert report["currency_transitions"] == 1, (
        f"Only the transport dataset changed currency, so currency_transitions must be 1, "
        f"got {report['currency_transitions']}"
    )
    assert report["staleness_alerts_emitted"] == 1, (
        f"Only the dataset entering STALE alerts, got {report['staleness_alerts_emitted']}"
    )
    assert report["departments_recomputed"] == 2, (
        f"Step five walks both departments, got {report['departments_recomputed']}"
    )
    assert report["postures_changed"] == 1, (
        f"Only the owning department's posture moved, got {report['postures_changed']}"
    )

    stale = fixtures.read_dataset(transport["dataset_id"], api=api)
    assert_dataset_states(stale, publication_status="PUBLISHED", currency_status="STALE")
    assert stale["days_overdue"] == 17, (
        f"2026-08-08 to 2026-08-25 is 17 whole days overdue, got {stale['days_overdue']}"
    )
    assert stale["staleness_alert_count"] == 1, (
        f"The AGING sweep emitted nothing and the STALE sweep emitted once, "
        f"got {stale['staleness_alert_count']}"
    )

    owner = fixtures.read_department(transport["department_id"], api=api)
    assert_posture(
        owner, stale=1, breached=0, risk_points=2, compliance_posture="RESTRICTED"
    )

    peer_dataset = fixtures.read_dataset(parks_dataset_id, api=api)
    assert_dataset_states(peer_dataset, publication_status="PUBLISHED", currency_status="CURRENT")
    assert peer_dataset["days_overdue"] == 0, (
        f"The parks dataset is not due until 2026-08-31, got {peer_dataset['days_overdue']}"
    )
    assert peer_dataset["staleness_alert_count"] == 0, (
        f"The parks dataset alerts not at all, got {peer_dataset['staleness_alert_count']}"
    )

    peer = fixtures.read_department(parks_id, api=api)
    assert_posture(peer, stale=0, breached=0, risk_points=0, compliance_posture="OPEN")
