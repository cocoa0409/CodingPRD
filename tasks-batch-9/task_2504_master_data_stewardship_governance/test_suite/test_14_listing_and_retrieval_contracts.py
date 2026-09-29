"""Retrieval, partial-revision and computed-read contracts of the governance graph.

The governance office and its stewards read far more often than they write, so
the read surface has to agree with the writes that produced it: a threshold
revision must leave the rest of the rule alone and still be there on the next
read, a merge review must name the steward who actually picked the proposal up,
the computed scorecard projection must agree with the measurements stored on the
domain's findings without recording a run of its own, lineage documentation must
tie the authoritative source to the consumer's reporting asset, and an
acknowledgement must have something pending to acknowledge.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    CLOCK,
    GOVERNANCE_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    add_consumer_subscription,
    add_master_record,
    add_merge_proposal,
    assert_instant_equals,
    consumer_subscription_payload,
    create_domain,
    make_consumer_rep_headers,
    make_data_steward_headers,
    open_finding,
    read_domain,
    set_clock,
    setup_draft_domain,
    validate_error,
    validate_success,
)

# Two ERP claims about the same customer, each carrying the five attribute keys
# the CUSTOMER domain expects, so both read as exactly complete.
THETA_PRIMARY_ATTRIBUTES = {
    "legal_name": "Theta Components",
    "tax_id": "TX-4410",
    "billing_city": "Twin Falls",
    "contact_email": "ap@theta.test",
    "duns": "11-400-9001",
}
THETA_SECONDARY_ATTRIBUTES = {
    "legal_name": "Theta Components Ltd",
    "tax_id": "TX-4410",
    "billing_city": "Twin Falls",
    "contact_email": "ar@theta.test",
    "duns": "11-400-9001",
}


def _theta_duplicate_pair(ctx):
    """Ingest and curate two ERP claims about one customer."""
    primary = add_master_record(
        ctx,
        source_code="ERP",
        natural_key="ERP-CUST-4410-A",
        attributes=THETA_PRIMARY_ATTRIBUTES,
        last_verified_at=CLOCK,
    )
    secondary = add_master_record(
        ctx,
        source_code="ERP",
        natural_key="ERP-CUST-4410-B",
        attributes=THETA_SECONDARY_ATTRIBUTES,
        last_verified_at=CLOCK,
    )
    return primary, secondary


# ---------------------------------------------------------------------------
# Revising a quality rule threshold
# ---------------------------------------------------------------------------


def test_revising_a_rule_threshold_leaves_the_rest_of_the_rule_alone(api):
    """A threshold revision touches the threshold and the version, nothing else.

    PRD §3.3: "Rules can be adjusted in flight. A steward may revise `threshold_pct`, revise `weight_points`, or move `status` to retire the rule, in any combination; a weight revision re-validates the hundred-point budget against the domain's `ACTIVE` rule set exactly as a creation does."
    PRD §3.3: "Rules are created in `status` `ACTIVE` and enter the scorecard denominator from the next run onward."
    PRD §2.4: "Almost every resource additionally carries `updated_at`, refreshed to the current instant whenever any of the resource's own fields change, and `version`, an integer that starts at 1 on creation and increments on mutation."

    Design: Corner/endpoints/patch_quality_rule_threshold_updates_in_place
    """
    ctx = setup_draft_domain()
    rule = ctx["rules"]["QR1"]
    assert rule["threshold_pct"] == 90.00, (
        f"the rule was defined with a 90.00 pass threshold, got {rule['threshold_pct']}"
    )
    assert rule["version"] == 1, (
        f"a newly defined rule starts at version 1, got {rule['version']}"
    )

    revised = validate_success(
        api.update_quality_rule(
            rule["id"], {"threshold_pct": 95.00}, ctx["steward_headers"]
        )
    )

    assert revised["id"] == rule["id"], "a revision updates the rule in place"
    assert revised["threshold_pct"] == 95.00, (
        f"the pass threshold must read 95.00 after the revision, got "
        f"{revised['threshold_pct']}"
    )
    assert revised["version"] == 2, (
        f"one mutation advances the rule from version 1 to 2, got {revised['version']}"
    )
    assert revised["weight_points"] == 40, (
        "a threshold-only revision leaves the rule's scorecard weight at 40, got "
        f"{revised['weight_points']}"
    )
    assert revised["dimension"] == "COMPLETENESS", (
        f"the measured dimension is untouched, got {revised['dimension']}"
    )
    assert revised["severity"] == "HIGH", (
        f"the finding severity is untouched, got {revised['severity']}"
    )
    assert revised["status"] == "ACTIVE", (
        f"a threshold revision does not retire the rule, got {revised['status']}"
    )


def test_a_revised_rule_threshold_is_what_the_next_read_returns(api):
    """The revised threshold and version survive to the next read of the rule.

    PRD §3.3: "Rules can be adjusted in flight. A steward may revise `threshold_pct`, revise `weight_points`, or move `status` to retire the rule, in any combination; a weight revision re-validates the hundred-point budget against the domain's `ACTIVE` rule set exactly as a creation does."
    PRD §2.4: "Almost every resource additionally carries `updated_at`, refreshed to the current instant whenever any of the resource's own fields change, and `version`, an integer that starts at 1 on creation and increments on mutation."

    Design: Corner/endpoints/patch_quality_rule_threshold_updates_in_place
    """
    ctx = setup_draft_domain()
    rule = ctx["rules"]["QR1"]
    validate_success(
        api.update_quality_rule(
            rule["id"], {"threshold_pct": 95.00}, ctx["steward_headers"]
        )
    )

    read_back = validate_success(api.get_quality_rule(rule["id"], AUDITOR_HEADERS))

    assert read_back["threshold_pct"] == 95.00, (
        f"the stored pass threshold must be 95.00, got {read_back['threshold_pct']}"
    )
    assert read_back["version"] == 2, (
        f"the stored rule must sit at version 2, got {read_back['version']}"
    )


# ---------------------------------------------------------------------------
# Taking a merge proposal under review
# ---------------------------------------------------------------------------


def test_merge_review_refuses_a_steward_with_no_assignment_on_the_domain(api):
    """A steward with no accountability on the domain cannot pick a proposal up.

    PRD §2.1: "When `X-User-Role` is `DataSteward`, `X-User-ID` is likewise the `id` of the acting `Steward`, and the acting steward must hold an `ACTIVE` `StewardAssignment` on the target domain whose `steward_role` is either `DATA_STEWARD` or `CUSTODIAN` and whose interval covers the clock; failing that check yields `ERR_NOT_DOMAIN_STEWARD` (HTTP 403)."
    PRD §3.7: "The transition `PROPOSED → UNDER_REVIEW` requires the proposal to be in `PROPOSED` status and requires the acting steward to hold an `ACTIVE` `StewardAssignment` on the proposal's domain covering the clock; it records the acting `X-User-ID` as `reviewer_steward_id`."

    Design: Corner/endpoints/merge_proposal_review_pins_the_acting_reviewer
    """
    ctx = setup_draft_domain(third_steward=True)
    primary, secondary = _theta_duplicate_pair(ctx)
    proposal = add_merge_proposal(
        ctx,
        primary,
        secondary,
        review=False,
        name_similarity_pct=92.00,
        key_overlap_pct=100.00,
    )
    unassigned = ctx["third"]

    response = api.review_merge_proposal(
        proposal["id"], make_data_steward_headers(unassigned["id"])
    )

    validate_error(response, "ERR_NOT_DOMAIN_STEWARD")

    untouched = validate_success(
        api.get_merge_proposal(proposal["id"], AUDITOR_HEADERS)
    )
    assert untouched["status"] == "PROPOSED", (
        f"a refused hand-off leaves the proposal PROPOSED, got {untouched['status']}"
    )
    assert untouched["reviewer_steward_id"] is None, (
        "a refused hand-off pins no reviewer, got "
        f"{untouched['reviewer_steward_id']!r}"
    )


def test_merge_review_pins_the_owner_who_picked_the_proposal_up(api):
    """Review records the acting data owner as the proposal's reviewer.

    PRD §3.7: "The transition `PROPOSED → UNDER_REVIEW` requires the proposal to be in `PROPOSED` status and requires the acting steward to hold an `ACTIVE` `StewardAssignment` on the proposal's domain covering the clock; it records the acting `X-User-ID` as `reviewer_steward_id`."
    PRD §3.7: "A new proposal is created in `status` `PROPOSED` with `reviewer_steward_id`, `effective_survivor_master_record_id`, `survivorship_variant`, `survivorship_field_map`, `override_justification` and `decided_at` all null, `survivor_swapped` false, and `rework_count` at 0."
    PRD §3.7: "The proposal's own `domain_id` is not supplied — it is copied from the survivor candidate's domain at creation — and `proposer_steward_id` is set from the acting `X-User-ID`."

    Design: Corner/endpoints/merge_proposal_review_pins_the_acting_reviewer
    """
    ctx = setup_draft_domain()
    primary, secondary = _theta_duplicate_pair(ctx)
    proposal = add_merge_proposal(
        ctx,
        primary,
        secondary,
        review=False,
        name_similarity_pct=92.00,
        key_overlap_pct=100.00,
    )
    assert proposal["status"] == "PROPOSED", (
        f"a new proposal opens as PROPOSED, got {proposal['status']}"
    )
    assert proposal["reviewer_steward_id"] is None, (
        f"a new proposal has no reviewer, got {proposal['reviewer_steward_id']!r}"
    )
    assert proposal["proposer_steward_id"] == ctx["steward"]["id"], (
        "the proposer is the steward who raised the proposal, got "
        f"{proposal['proposer_steward_id']}"
    )

    reviewed = validate_success(
        api.review_merge_proposal(proposal["id"], ctx["owner_headers"])
    )

    assert reviewed["status"] == "UNDER_REVIEW", (
        f"review drives the proposal to UNDER_REVIEW, got {reviewed['status']}"
    )
    assert reviewed["reviewer_steward_id"] == ctx["owner"]["id"], (
        "the reviewer must be the data owner who acted, expected "
        f"{ctx['owner']['id']}, got {reviewed['reviewer_steward_id']}"
    )


# ---------------------------------------------------------------------------
# The computed scorecard read
# ---------------------------------------------------------------------------


def test_computed_scorecard_read_agrees_with_the_measurements_on_the_findings(api):
    """The computed projection re-scores the domain from its stored findings.

    PRD §3.4: "Separately from recording a run, the same scoring logic is available as a pure read that creates nothing. That computed read accepts an optional `basis` query parameter and evaluates the domain against the measurements currently stored on its findings, returning a small projection rather than a resource: `domain_id`, the `basis` used, the `weighted_score`, `rules_evaluated_count`, `rules_failed_count`, the domain's current `open_finding_weight`, and its current `governance_posture`."
    PRD §3.4: "On a `CERTIFIED` basis the evaluated set is *every* `ACTIVE` rule of the domain, and an `ACTIVE` rule left unmeasured is treated as having a `measured_pct` of 0.00 — it stays in the denominator, earns zero points, and produces a finding."
    PRD §3.4: "The run's `weighted_score` is one hundred times the earned total divided by that denominator, rounded half up to two decimal places — a second and final rounding. `rules_evaluated_count` records how many rules entered the denominator and `rules_failed_count` how many of them had a `measured_pct` strictly below their `threshold_pct`."
    PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded sum of `severity_weight` over the domain's findings whose `status` is `OPEN` or `REMEDIATION_PLANNED`."

    Design: Corner/endpoints/scorecard_computed_read_agrees_with_stored_measurements
    """
    ctx = setup_draft_domain()
    run, finding = open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")
    assert run["weighted_score"] == 50.00, (
        "measuring a 40-point rule at 45.00 against a 90.00 threshold earns half "
        f"the budget, so the run scores 50.00, got {run['weighted_score']}"
    )
    assert run["posture_after"] == "OPEN", (
        f"eight points of quality debt keep the posture OPEN, got {run['posture_after']}"
    )
    assert finding["measured_pct"] == 45.00, (
        f"the finding stores the observed 45.00, got {finding['measured_pct']}"
    )

    projection = validate_success(
        api.get_domain_scorecard(
            ctx["domain"]["id"], ctx["steward_headers"], params={"basis": "CERTIFIED"}
        )
    )

    assert projection["domain_id"] == ctx["domain"]["id"], (
        f"the projection names the scored domain, got {projection['domain_id']}"
    )
    assert projection["basis"] == "CERTIFIED", (
        f"the projection echoes the requested basis, got {projection['basis']}"
    )
    assert projection["weighted_score"] == 50.00, (
        "re-scoring the stored 45.00 measurement against the 90.00 threshold gives "
        f"50.00, got {projection['weighted_score']}"
    )
    assert projection["rules_evaluated_count"] == 1, (
        "a certified basis evaluates every active rule, and the domain has one, got "
        f"{projection['rules_evaluated_count']}"
    )
    assert projection["rules_failed_count"] == 1, (
        f"the single rule is still breached, got {projection['rules_failed_count']}"
    )
    assert projection["open_finding_weight"] == 8.00, (
        "one open finding on a HIGH-severity rule at an OPEN posture carries eight "
        f"points of debt, got {projection['open_finding_weight']}"
    )
    assert projection["governance_posture"] == "OPEN", (
        f"the projection reports the live posture, got {projection['governance_posture']}"
    )


def test_computed_scorecard_read_records_no_run_and_writes_no_certified_score(api):
    """Reading the scorecard leaves the epoch counter and stored scores alone.

    PRD §3.4: "It creates no `ScorecardRun`, opens no finding, moves no counter and does not touch the domain's `version` or its posture."
    PRD §3.4: "A `PROVISIONAL` run writes its `weighted_score` to the domain's `quality_score_provisional`; a `CERTIFIED` run writes it to `quality_score_certified`. The other basis's stored score is not touched, so a domain that has only ever run provisionally keeps a null `quality_score_certified`."

    Design: Corner/endpoints/scorecard_computed_read_agrees_with_stored_measurements
    """
    ctx = setup_draft_domain()
    open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")

    validate_success(
        api.get_domain_scorecard(
            ctx["domain"]["id"], ctx["steward_headers"], params={"basis": "CERTIFIED"}
        )
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["scorecard_run_seq"] == 1, (
        "only the recorded provisional run advanced the scorecard epoch, got "
        f"{domain['scorecard_run_seq']}"
    )
    assert domain["quality_score_certified"] is None, (
        "a computed read on a certified basis stores nothing, so the certified "
        f"score stays null, got {domain['quality_score_certified']!r}"
    )
    assert domain["quality_score_provisional"] == 50.00, (
        "the provisional score written by the recorded run is untouched, got "
        f"{domain['quality_score_provisional']}"
    )


# ---------------------------------------------------------------------------
# Documenting a consumer's lineage
# ---------------------------------------------------------------------------


def test_lineage_documentation_refuses_an_unknown_subscription(api):
    """Documenting lineage on an identifier that resolves to nothing is a 404.

    PRD §2.9: "Path parameters are validated left to right, and the first identifier in the path that does not resolve to an existing row determines the 404 error returned. The parameter names and their corresponding errors are: `domain_id` → `ERR_DOMAIN_NOT_FOUND`; `source_system_id` → `ERR_SOURCE_SYSTEM_NOT_FOUND`; `steward_id` → `ERR_STEWARD_NOT_FOUND`; `registration_id` → `ERR_REGISTRATION_NOT_FOUND`; `assignment_id` → `ERR_ASSIGNMENT_NOT_FOUND`; `rule_id` → `ERR_QUALITY_RULE_NOT_FOUND`; `run_id` → `ERR_SCORECARD_RUN_NOT_FOUND`; `finding_id` → `ERR_FINDING_NOT_FOUND`; `record_id` → `ERR_MASTER_RECORD_NOT_FOUND`; `proposal_id` → `ERR_MERGE_PROPOSAL_NOT_FOUND`; `change_request_id` → `ERR_CHANGE_REQUEST_NOT_FOUND`; `subscription_id` → `ERR_SUBSCRIPTION_NOT_FOUND`."

    Design: Corner/endpoints/lineage_patch_links_authoritative_source_to_reporting_asset
    """
    ctx = setup_draft_domain()

    response = api.document_consumer_lineage(
        NON_EXISTENT_UUID,
        {"lineage_path": ["ERP", "STG_CUSTOMER", "DM_CUSTOMER", "RPT_A"]},
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_SUBSCRIPTION_NOT_FOUND")


def test_lineage_documentation_records_the_path_from_source_to_reporting_asset(api):
    """A documented path runs from the authoritative source to the consumer's asset.

    PRD §3.9: "A new subscription begins with `status` `ACTIVE` and `lineage_status` `UNDOCUMENTED`, an empty `lineage_path`, and `lineage_revision`, `lineage_documented_at`, `pending_change_request_id`, `notified_at`, `acknowledged_at`, `acknowledged_revision` and `suspended_reason` all null."
    PRD §3.9: "On success the supplied path replaces whatever was stored, `lineage_status` becomes `DOCUMENTED`, `lineage_documented_at` is stamped from the logical clock, and `lineage_revision` captures the domain's `reference_data_revision` as it stands at that instant — which is precisely what makes the documentation datable against later changes."

    Design: Corner/endpoints/lineage_patch_links_authoritative_source_to_reporting_asset
    """
    ctx = setup_draft_domain()
    subscription = add_consumer_subscription(
        ctx,
        consumer_code="BI_A",
        reporting_asset_key="RPT_A",
        clearance_level="INTERNAL",
        criticality="TIER1",
        required_lead_days=5,
    )
    assert subscription["lineage_status"] == "UNDOCUMENTED", (
        f"a new consumer starts undocumented, got {subscription['lineage_status']}"
    )
    assert subscription["lineage_revision"] is None, (
        f"a new consumer carries no lineage revision, got "
        f"{subscription['lineage_revision']!r}"
    )
    assert read_domain(ctx["domain"]["id"])["reference_data_revision"] == 0, (
        "no change has been applied yet, so the domain's reference data revision "
        "is still 0"
    )

    lineage_path = ["ERP", "STG_CUSTOMER", "DM_CUSTOMER", "RPT_A"]
    documented = validate_success(
        api.document_consumer_lineage(
            subscription["id"], {"lineage_path": lineage_path}, ctx["steward_headers"]
        )
    )

    assert documented["lineage_status"] == "DOCUMENTED", (
        f"documenting the flow marks it DOCUMENTED, got {documented['lineage_status']}"
    )
    assert documented["lineage_path"] == lineage_path, (
        f"the supplied path replaces whatever was stored, got "
        f"{documented['lineage_path']}"
    )
    assert documented["lineage_revision"] == 0, (
        "the documentation is dated against the domain's reference data revision, "
        f"which is still 0, got {documented['lineage_revision']}"
    )
    assert_instant_equals(
        documented["lineage_documented_at"], CLOCK, "lineage_documented_at"
    )


# ---------------------------------------------------------------------------
# Acknowledging a notification
# ---------------------------------------------------------------------------


def test_acknowledgement_refused_when_no_notification_is_pending(api):
    """A consumer with nothing pending has nothing to acknowledge.

    PRD §3.9: "It requires a pending notification: a subscription whose `pending_change_request_id` is null has nothing to acknowledge and the attempt is rejected with `ERR_NO_PENDING_NOTIFICATION`."

    Design: Corner/endpoints/acknowledge_requires_a_pending_notification
    """
    set_clock()
    domain = create_domain()
    subscription = validate_success(
        api.create_consumer_subscription(
            consumer_subscription_payload(
                domain["id"],
                consumer_code="BI_A",
                reporting_asset_key="RPT_A",
                clearance_level="INTERNAL",
                criticality="TIER1",
                required_lead_days=5,
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )
    assert subscription["pending_change_request_id"] is None, (
        "no change has been scheduled, so nothing is pending, got "
        f"{subscription['pending_change_request_id']!r}"
    )

    response = api.acknowledge_consumer_subscription(
        subscription["id"], make_consumer_rep_headers(subscription["id"])
    )

    validate_error(response, "ERR_NO_PENDING_NOTIFICATION")


def test_a_refused_acknowledgement_stamps_nothing_on_the_subscription(api):
    """A refused acknowledgement leaves the sign-off fields null and the consumer active.

    PRD §3.9: "It requires a pending notification: a subscription whose `pending_change_request_id` is null has nothing to acknowledge and the attempt is rejected with `ERR_NO_PENDING_NOTIFICATION`."
    PRD §3.9: "On success `acknowledged_at` is stamped from the logical clock and `acknowledged_revision` captures the domain's `reference_data_revision` at acknowledgement time, giving an auditable record of exactly which revision of the reference data the consumer signed off against."

    Design: Corner/endpoints/acknowledge_requires_a_pending_notification
    """
    set_clock()
    domain = create_domain()
    subscription = validate_success(
        api.create_consumer_subscription(
            consumer_subscription_payload(
                domain["id"],
                consumer_code="BI_A",
                reporting_asset_key="RPT_A",
                clearance_level="INTERNAL",
                criticality="TIER1",
                required_lead_days=5,
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )
    validate_error(
        api.acknowledge_consumer_subscription(
            subscription["id"], make_consumer_rep_headers(subscription["id"])
        ),
        "ERR_NO_PENDING_NOTIFICATION",
    )

    after = validate_success(
        api.get_consumer_subscription(subscription["id"], AUDITOR_HEADERS)
    )

    assert after["acknowledged_at"] is None, (
        f"a refused acknowledgement stamps nothing, got {after['acknowledged_at']!r}"
    )
    assert after["acknowledged_revision"] is None, (
        "a refused acknowledgement signs off against no revision, got "
        f"{after['acknowledged_revision']!r}"
    )
    assert after["status"] == "ACTIVE", (
        f"the consumer remains active, got {after['status']}"
    )
