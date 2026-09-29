"""Lifecycle entry points, refused transitions and terminal lockdown.

Covers the states a governance resource is born into, the transitions the
governance office and its stewards may take from there, and the transitions the
system refuses: certifying a source twice, decertifying one that was never
certified, activating a domain that nobody has made measurable, deciding or
rescoring a merge that has already been rejected. Also covers the two places
where a transition's bookkeeping is deliberately narrower than it looks —
planning a remediation charges the assignee rather than the planner and leaves
the domain's quality debt alone, and a master record's curation and publication
dimensions advance without disturbing one another.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    CLOCK,
    GOVERNANCE_ADMIN_HEADERS,
    ApiErrorId,
    add_master_record,
    add_merge_proposal,
    api_client,
    assert_change_request,
    assert_instant_equals,
    assert_master_record,
    assert_quality_finding,
    assert_source_system,
    change_request_payload,
    create_source_system,
    get_success_data,
    open_finding,
    read_domain,
    set_clock,
    setup_draft_domain,
    setup_governed_domain,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _rejected_merge_proposal():
    """Two curated same-source candidates whose merge proposal was rejected.

    Returns (context, survivor candidate, duplicate candidate, proposal).
    """
    ctx = setup_governed_domain()
    survivor = add_master_record(
        ctx,
        source_code="ERP",
        curate=True,
        natural_key="ERP-CUST-3001",
        attributes={
            "legal_name": "Gamma Ltd",
            "tax_id": "TX-30",
            "billing_city": "Boise",
            "contact_email": "ops@gamma.test",
            "duns": "30-300",
        },
        last_verified_at=CLOCK,
    )
    duplicate = add_master_record(
        ctx,
        source_code="ERP",
        curate=True,
        natural_key="ERP-CUST-3002",
        attributes={
            "legal_name": "Gamma Limited",
            "tax_id": "TX-30",
            "billing_city": "Boise",
            "contact_email": "ap@gamma.test",
            "duns": "30-300",
        },
        last_verified_at=CLOCK,
    )
    proposal = add_merge_proposal(
        ctx,
        survivor,
        duplicate,
        review=True,
        name_similarity_pct=90.00,
        key_overlap_pct=100.00,
    )
    rejected = get_success_data(
        api_client.decide_merge_proposal(
            proposal["id"], {"decision": "REJECT"}, ctx["owner_headers"]
        )
    )
    return ctx, survivor, duplicate, rejected


def test_new_change_request_is_born_a_draft_with_no_workflow_history(api):
    """A change request a steward has only just raised records its originator
    and nothing else: no reviewer, no submission, no schedule, no impact.

    PRD §3.8: "A new request is created in `status` `DRAFT` with
    `requester_steward_id` taken from the acting `X-User-ID`,
    `reviewer_steward_id` null, `impact_consumer_count` and `required_lead_days`
    at 0, `revision_cycle_count` at 0, and `submitted_at`, `earliest_apply_at`,
    `scheduled_apply_at`, `freeze_window_start`, `freeze_window_end`,
    `applied_at`, `review_note` and `withdraw_reason` all null."

    PRD §4: "Operations that create a brand-new resource — a domain, a source
    system, a steward, a source registration, a steward assignment, a quality
    rule, a scorecard run, a master record, a merge proposal, a change request
    or a consumer subscription — respond with HTTP 201 and return the created
    resource in `data`."

    Design: Corner/state_machines/change_request_starts_in_draft
    """
    ctx = setup_governed_domain()

    response = api.create_change_request(
        change_request_payload(ctx["domain"]["id"]), ctx["steward_headers"]
    )
    request = validate_success(response, expected_status=201)
    assert_change_request(request)

    assert request["status"] == "DRAFT", (
        f"a newly raised request must be a DRAFT, got {request['status']}"
    )
    assert request["requester_steward_id"] == ctx["steward"]["id"], (
        "the requester must be the acting steward, got "
        f"{request['requester_steward_id']!r}"
    )
    assert request["reviewer_steward_id"] is None, (
        f"reviewer_steward_id must start null, got {request['reviewer_steward_id']!r}"
    )
    assert request["impact_consumer_count"] == 0, (
        "no impact has been assessed yet, got "
        f"{request['impact_consumer_count']!r}"
    )
    assert request["required_lead_days"] == 0, (
        f"no lead time has been computed yet, got {request['required_lead_days']!r}"
    )
    assert request["revision_cycle_count"] == 0, (
        f"no revision cycle has run yet, got {request['revision_cycle_count']!r}"
    )
    for field in (
        "submitted_at",
        "earliest_apply_at",
        "scheduled_apply_at",
        "freeze_window_start",
        "freeze_window_end",
        "applied_at",
        "review_note",
        "withdraw_reason",
    ):
        assert request[field] is None, (
            f"{field} must start null on a draft request, got {request[field]!r}"
        )


def test_structural_flag_is_derived_from_the_change_type(api):
    """Whether a change is structural is decided by the system from the change
    type, not declared by the steward raising it.

    PRD §3.8: "The derived boolean `structural` is true for exactly the two
    non-additive types, `HIERARCHY_RESTRUCTURE` and `CLASSIFICATION_UPLIFT`, and
    false for `REFERENCE_VALUE_ADD`; it is never supplied by the client."

    Design: Corner/state_machines/change_request_starts_in_draft
    """
    ctx = setup_governed_domain()

    restructure = validate_success(
        api.create_change_request(
            change_request_payload(
                ctx["domain"]["id"],
                change_type="HIERARCHY_RESTRUCTURE",
                title="Split the EMEA sales hierarchy",
                proposed_values={
                    "parent_node_key": "GLOBAL",
                    "child_node_key": "EMEA_SALES",
                },
            ),
            ctx["steward_headers"],
        ),
        expected_status=201,
    )
    addition = validate_success(
        api.create_change_request(
            change_request_payload(ctx["domain"]["id"]),
            ctx["steward_headers"],
        ),
        expected_status=201,
    )
    assert_change_request(restructure)
    assert_change_request(addition)

    assert restructure["change_type"] == "HIERARCHY_RESTRUCTURE", (
        f"the declared change type must be stored, got {restructure['change_type']}"
    )
    assert restructure["structural"] is True, (
        "re-parenting a hierarchy node is a structural change, got "
        f"{restructure['structural']!r}"
    )
    assert addition["change_type"] == "REFERENCE_VALUE_ADD", (
        f"the declared change type must be stored, got {addition['change_type']}"
    )
    assert addition["structural"] is False, (
        "adding a reference value is not a structural change, got "
        f"{addition['structural']!r}"
    )


def test_certifying_a_registered_source_stamps_the_certification_instant(api):
    """Certification takes a registered source system to certified and records
    the instant from the logical clock, advancing the row's version.

    PRD §3.1: "Certification is the gate that lets a source become authoritative
    and contribute curated records: the transition `REGISTERED → CERTIFIED` is
    available only while the system is still `REGISTERED` (attempting it on an
    already-certified or `DECERTIFIED` system is `ERR_INVALID_STATE_TRANSITION`),
    it stamps `certified_at` from the logical clock, and — because certification
    can be the missing ingredient that a domain's posture was waiting on — it
    also recomputes the `governance_posture` of every domain that already holds
    an `ACTIVE` `AUTHORITATIVE` registration on the newly certified system."

    PRD §2.4: "Almost every resource additionally carries `updated_at`,
    refreshed to the current instant whenever any of the resource's own fields
    change, and `version`, an integer that starts at 1 on creation and increments
    on mutation."

    Design: Corner/state_machines/source_system_certify_moves_registered_to_certified
    """
    set_clock(CLOCK)
    system = create_source_system(
        certify=False, code="CRM", name="CRM Cloud", trust_tier=3
    )

    assert system["status"] == "REGISTERED", (
        f"a newly registered system must be REGISTERED, got {system['status']}"
    )
    assert system["version"] == 1, (
        f"version must start at 1 on creation, got {system['version']!r}"
    )

    certified = validate_success(
        api.certify_source_system(system["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert_source_system(certified)

    assert certified["status"] == "CERTIFIED", (
        f"certification must move the system to CERTIFIED, got {certified['status']}"
    )
    assert_instant_equals(certified["certified_at"], CLOCK, "certified_at")
    assert certified["version"] == 2, (
        f"certification mutates the row, so version must advance to 2, got "
        f"{certified['version']!r}"
    )


def test_activating_a_domain_with_no_quality_rule_is_refused(api):
    """A domain nobody has made measurable cannot start governing data, and the
    refusal leaves it a draft.

    PRD §3.1: "Activation is the moment a domain stops being a sketch and starts
    governing data, and the governance office may only perform it once four
    independent readiness conditions all hold."

    PRD §3.1: "The domain must have at least one quality rule in `ACTIVE`
    status, otherwise `ERR_NO_QUALITY_RULES`."

    PRD §3.1: "When all four hold, the `DRAFT → ACTIVE` transition sets `status`
    to `ACTIVE`, stamps `activated_at` from the logical clock, recomputes
    `governance_posture`, and advances the domain's `version` by one."

    Design: Corner/state_machines/activate_without_active_quality_rule_rejected
    """
    ctx = setup_draft_domain(rules=[])
    before = read_domain(ctx["domain"]["id"])

    response = api.activate_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_NO_QUALITY_RULES)

    after = read_domain(ctx["domain"]["id"])
    assert after["status"] == "DRAFT", (
        f"a refused activation must leave the domain in DRAFT, got {after['status']}"
    )
    assert after["activated_at"] is None, (
        f"a refused activation must stamp no activation instant, got {after['activated_at']!r}"
    )
    assert after["version"] == before["version"], (
        "a refused activation must not advance the domain version, got "
        f"{after['version']!r} after {before['version']!r}"
    )


def test_decertifying_a_source_that_was_never_certified_is_refused(api):
    """Decertification is reachable only from a certified source system, so a
    system still merely registered cannot be decertified and nothing of the
    five-hop cascade is written.

    PRD §3.2: "It is available only from `CERTIFIED`, and the caller supplies a
    `reason` string."

    PRD §3.2: "**Hop 1** moves the source system `CERTIFIED → DECERTIFIED`,
    stamps `decertified_at` from the clock, and stores the supplied reason as
    `decertification_reason`."

    PRD §2.9: "The generic violation is `ERR_INVALID_STATE_TRANSITION` (409);
    where a specialised identifier exists it is used instead —
    `ERR_DOMAIN_NOT_DRAFT`, `ERR_DOMAIN_NOT_ACTIVE`, `ERR_SOURCE_NOT_CERTIFIED`,
    `ERR_FINDING_ALREADY_CLOSED`, `ERR_RECORD_NOT_CURATED`,
    `ERR_RECORD_ALREADY_PUBLISHED`, `ERR_PROPOSAL_NOT_UNDER_REVIEW`,
    `ERR_CHANGE_REQUEST_NOT_SCHEDULED`, `ERR_RULE_HAS_OPEN_FINDINGS` and
    `ERR_NO_PENDING_NOTIFICATION`."

    Design: Corner/state_machines/decertify_from_registered_is_an_invalid_transition
    """
    set_clock(CLOCK)
    system = create_source_system(
        certify=False, code="CRM", name="CRM Cloud", trust_tier=3
    )

    response = api.decertify_source_system(
        system["id"],
        {"reason": "Vendor contract terminated"},
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            ApiErrorId.ERR_SOURCE_NOT_CERTIFIED,
        ],
    )
    assert response.status_code == 409, (
        "an unreachable transition is a conflict, got "
        f"HTTP {response.status_code}"
    )

    stored = validate_success(api.get_source_system(system["id"], AUDITOR_HEADERS))
    assert_source_system(stored)

    assert stored["status"] == "REGISTERED", (
        f"the refused decertification must leave the system REGISTERED, got {stored['status']}"
    )
    assert stored["decertified_at"] is None, (
        f"no decertification instant may be stamped, got {stored['decertified_at']!r}"
    )
    assert stored["decertification_reason"] is None, (
        "the supplied reason must not be stored, got "
        f"{stored['decertification_reason']!r}"
    )
    assert stored["certified_at"] is None, (
        f"a never-certified system has no certification instant, got {stored['certified_at']!r}"
    )
    assert stored["version"] == 1, (
        f"a refused decertification must not mutate the row, got version {stored['version']!r}"
    )


def test_certifying_an_already_certified_source_is_refused(api):
    """Certification is available only from the registered state, so a replayed
    certification is refused and the original stamp stands unchanged.

    PRD §3.1: "Certification is the gate that lets a source become authoritative
    and contribute curated records: the transition `REGISTERED → CERTIFIED` is
    available only while the system is still `REGISTERED` (attempting it on an
    already-certified or `DECERTIFIED` system is `ERR_INVALID_STATE_TRANSITION`),
    it stamps `certified_at` from the logical clock, and — because certification
    can be the missing ingredient that a domain's posture was waiting on — it
    also recomputes the `governance_posture` of every domain that already holds
    an `ACTIVE` `AUTHORITATIVE` registration on the newly certified system."

    PRD §2.4: "Almost every resource additionally carries `updated_at`,
    refreshed to the current instant whenever any of the resource's own fields
    change, and `version`, an integer that starts at 1 on creation and increments
    on mutation."

    Design: Corner/state_machines/certify_twice_is_rejected_on_the_second_attempt
    """
    set_clock("2026-08-01T00:00:00Z")
    system = create_source_system(
        certify=True, code="CRM", name="CRM Cloud", trust_tier=3
    )

    assert system["status"] == "CERTIFIED", (
        f"the first certification must succeed, got {system['status']}"
    )

    set_clock("2026-08-05T00:00:00Z")
    response = api.certify_source_system(system["id"], GOVERNANCE_ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    stored = validate_success(api.get_source_system(system["id"], AUDITOR_HEADERS))
    assert_source_system(stored)

    assert stored["status"] == "CERTIFIED", (
        f"the system must remain CERTIFIED, got {stored['status']}"
    )
    assert_instant_equals(
        stored["certified_at"], "2026-08-01T00:00:00Z", "certified_at"
    )
    assert stored["version"] == 2, (
        "the refused replay must not mutate the row a second time, got version "
        f"{stored['version']!r}"
    )


def test_rejected_merge_proposal_cannot_be_decided_again(api):
    """Rejection is terminal: the proposal is locked down and a later decision
    on it is refused because it is no longer under review.

    PRD §3.7: "`REJECT` drives `UNDER_REVIEW → REJECTED`, stamps `decided_at`
    from the clock, and mutates no record whatsoever:
    `effective_survivor_master_record_id` stays null and `survivor_swapped` stays
    false."

    PRD §3.7: "In all three cases the proposal must actually be in
    `UNDER_REVIEW`, otherwise `ERR_PROPOSAL_NOT_UNDER_REVIEW`, and in all three
    cases the acting `X-User-ID` must differ from the proposal's
    `proposer_steward_id`, a self-decision being rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/rejected_merge_proposal_is_locked_down
    """
    ctx, _survivor, _duplicate, rejected = _rejected_merge_proposal()

    assert rejected["status"] == "REJECTED", (
        f"the rejection must move the proposal to REJECTED, got {rejected['status']}"
    )
    assert_instant_equals(rejected["decided_at"], CLOCK, "decided_at")
    assert rejected["effective_survivor_master_record_id"] is None, (
        "a rejection selects no survivor, got "
        f"{rejected['effective_survivor_master_record_id']!r}"
    )
    assert rejected["survivor_swapped"] is False, (
        f"a rejection swaps no survivor, got {rejected['survivor_swapped']!r}"
    )

    response = api.decide_merge_proposal(
        rejected["id"], {"decision": "MERGE"}, ctx["owner_headers"]
    )

    validate_error(response, ApiErrorId.ERR_PROPOSAL_NOT_UNDER_REVIEW)

    stored = validate_success(
        api.get_merge_proposal(rejected["id"], AUDITOR_HEADERS)
    )
    assert stored["status"] == "REJECTED", (
        f"the refused decision must leave the proposal REJECTED, got {stored['status']}"
    )
    assert stored["effective_survivor_master_record_id"] is None, (
        "the refused decision must select no survivor, got "
        f"{stored['effective_survivor_master_record_id']!r}"
    )


def test_rejected_merge_proposal_cannot_be_rescored(api):
    """Rescoring is reachable only from rework, so a rejected proposal cannot be
    re-matched and both candidate records stay exactly as they were.

    PRD §3.7: "It requires the proposal to be in `REWORK` — rescoring a proposal
    that is still `PROPOSED` or already decided is
    `ERR_INVALID_STATE_TRANSITION` — and it requires both candidate records to
    still have a `curation_status` of `CANDIDATE` or `CURATED`, since a record
    that has since been merged away or quarantined can no longer participate."

    PRD §3.7: "On success `match_score` and `match_confidence` are recomputed
    from the new percentages by exactly the formula above, including the
    intra-source discount and the 45.00 floor, the `status` returns to
    `PROPOSED`, and `rework_count` is incremented by one so the audit trail
    records how many loops the proposal has been through."

    Design: Corner/state_machines/rejected_merge_proposal_is_locked_down
    """
    ctx, survivor, duplicate, rejected = _rejected_merge_proposal()

    response = api.rescore_merge_proposal(
        rejected["id"],
        {"name_similarity_pct": 99.00, "key_overlap_pct": 100.00},
        ctx["steward_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    stored = validate_success(
        api.get_merge_proposal(rejected["id"], AUDITOR_HEADERS)
    )
    assert stored["status"] == "REJECTED", (
        f"the refused rescore must leave the proposal REJECTED, got {stored['status']}"
    )
    assert stored["rework_count"] == 0, (
        f"the refused rescore must not count a rework loop, got {stored['rework_count']!r}"
    )
    assert stored["match_score"] == rejected["match_score"], (
        "the refused rescore must not recompute the match score, got "
        f"{stored['match_score']!r} after {rejected['match_score']!r}"
    )

    for candidate in (survivor, duplicate):
        after = validate_success(
            api.get_master_record(candidate["id"], AUDITOR_HEADERS)
        )
        assert_master_record(after)
        assert after["curation_status"] == "CURATED", (
            "neither candidate may be disturbed by a refused rescore, got "
            f"{after['curation_status']}"
        )
        assert after["superseded_by_master_record_id"] is None, (
            "neither candidate may be superseded by a refused rescore, got "
            f"{after['superseded_by_master_record_id']!r}"
        )


def test_planning_a_remediation_charges_the_assignee_not_the_planner(api):
    """Planning moves an open finding into remediation, records who planned it
    and who must do the work, and charges the workload of the assignee alone.

    PRD §3.5: "Planning a remediation drives the finding `OPEN →
    REMEDIATION_PLANNED`."

    PRD §3.5: "On success the `assigned_steward_id`, `due_at` and `plan_note`
    are stored, `planned_by_steward_id` is set to the acting `X-User-ID`, and the
    assignee's `open_finding_load` is incremented by one."

    PRD §2.8: "`Steward.open_finding_load` is the exact integer count of
    findings whose `assigned_steward_id` is that steward and whose `status` is
    `REMEDIATION_PLANNED` — note the filter is `REMEDIATION_PLANNED` only, so an
    `OPEN` finding never charges anyone's load."

    Design: Corner/state_machines/plan_remediation_charges_the_assigned_steward_load
    """
    ctx = setup_draft_domain()
    _run, finding = open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")

    assert finding["status"] == "OPEN", (
        f"a breach must open a finding, got {finding['status']}"
    )

    unplanned_assignee = validate_success(
        api.get_steward(ctx["steward"]["id"], AUDITOR_HEADERS)
    )
    assert unplanned_assignee["open_finding_load"] == 0, (
        "an open finding charges nobody's load before it is planned, got "
        f"{unplanned_assignee['open_finding_load']!r}"
    )

    planned = validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": "Backfill the missing billing attributes from the ERP extract",
            },
            ctx["owner_headers"],
        )
    )
    assert_quality_finding(planned)

    assert planned["status"] == "REMEDIATION_PLANNED", (
        f"planning must move the finding to REMEDIATION_PLANNED, got {planned['status']}"
    )
    assert planned["assigned_steward_id"] == ctx["steward"]["id"], (
        f"the nominated assignee must be stored, got {planned['assigned_steward_id']!r}"
    )
    assert planned["planned_by_steward_id"] == ctx["owner"]["id"], (
        "the planner must be recorded as the acting user, got "
        f"{planned['planned_by_steward_id']!r}"
    )
    assert_instant_equals(planned["due_at"], "2026-08-20T00:00:00Z", "due_at")
    assert planned["plan_note"] == (
        "Backfill the missing billing attributes from the ERP extract"
    ), f"the supplied plan note must be stored, got {planned['plan_note']!r}"

    assignee = validate_success(
        api.get_steward(ctx["steward"]["id"], AUDITOR_HEADERS)
    )
    planner = validate_success(api.get_steward(ctx["owner"]["id"], AUDITOR_HEADERS))

    assert assignee["open_finding_load"] == 1, (
        "the assignee must be charged one planned finding, got "
        f"{assignee['open_finding_load']!r}"
    )
    assert planner["open_finding_load"] == 0, (
        "the planner is not the assignee and must carry no load, got "
        f"{planner['open_finding_load']!r}"
    )


def test_planning_a_remediation_leaves_the_domain_quality_debt_untouched(api):
    """Planning re-labels quality debt rather than reducing it: the finding keeps
    the weight it was pinned with and the domain's open finding weight and
    posture do not move.

    PRD §3.4: "The base points come from the breached rule's `severity`: a
    `LOW`-severity rule contributes 1 point, `MEDIUM` contributes 3, `HIGH`
    contributes 8 and `CRITICAL` contributes 20."

    PRD §3.4: "Those base points are then multiplied by a posture multiplier:
    1.00 when the domain's posture was `OPEN`, 1.25 when it was `RESTRICTED` and
    1.50 when it was `FROZEN`."

    PRD §3.4: "Each finding's `severity_weight` is the base points times that
    multiplier, rounded half up to two decimal places, and it is frozen on the
    finding row forever after — nothing recomputes it."

    PRD §3.5: "The domain's `open_finding_weight` does not change: the finding's
    `severity_weight` was pinned at creation and the finding remains in the open
    set, so planning merely re-labels the debt rather than reducing it."

    PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded
    sum of `severity_weight` over the domain's findings whose `status` is `OPEN`
    or `REMEDIATION_PLANNED`."

    Design: Corner/state_machines/plan_remediation_charges_the_assigned_steward_load
    """
    ctx = setup_draft_domain()
    run, finding = open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")

    assert run["posture_multiplier_applied"] == 1.00, (
        "a run that began at an OPEN posture must weight its findings at 1.00, "
        f"got {run['posture_multiplier_applied']!r}"
    )
    assert finding["severity_weight"] == 8.00, (
        "a HIGH-severity breach at an OPEN posture must be pinned at eight "
        f"points, got {finding['severity_weight']!r}"
    )
    assert finding["measured_pct"] == 45.00, (
        f"the observed percentage must be carried, got {finding['measured_pct']!r}"
    )

    before = read_domain(ctx["domain"]["id"])
    assert before["open_finding_weight"] == 8.00, (
        "the domain's quality debt is the single pinned weight, got "
        f"{before['open_finding_weight']!r}"
    )

    planned = validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": "Backfill the missing billing attributes from the ERP extract",
            },
            ctx["owner_headers"],
        )
    )

    assert planned["severity_weight"] == 8.00, (
        "the pinned weight is never recomputed, got "
        f"{planned['severity_weight']!r}"
    )

    after = read_domain(ctx["domain"]["id"])
    assert after["open_finding_weight"] == 8.00, (
        "a planned finding stays in the open set, so the domain's quality debt "
        f"must not move, got {after['open_finding_weight']!r}"
    )
    assert after["governance_posture"] == before["governance_posture"], (
        "planning must not move the governance posture, got "
        f"{after['governance_posture']} after {before['governance_posture']}"
    )


def test_curating_a_record_advances_only_the_curation_dimension(api):
    """A steward's endorsement moves the record's curation dimension and leaves
    its publication dimension exactly where it was.

    PRD §3.6: "A newly ingested record begins with `curation_status`
    `CANDIDATE` and `publication_status` `UNPUBLISHED`, and with
    `superseded_by_master_record_id`, `published_at` and `quarantine_reason` all
    null."

    PRD §3.6: "Either way the record's `curation_status` becomes `CURATED` and
    its `survivorship_score` is recomputed against the new verification instant."

    PRD §3.6: "It bears emphasising that a master record runs two state
    dimensions independently on the same row."

    PRD §3.6: "Publishing never changes `curation_status`, and curating never
    changes `publication_status`."

    Design: Corner/state_machines/publication_and_curation_dimensions_advance_independently
    """
    ctx = setup_governed_domain()
    record = add_master_record(
        ctx,
        source_code="ERP",
        curate=False,
        natural_key="ERP-CUST-4001",
        attributes={
            "legal_name": "Delta Foods",
            "tax_id": "TX-40",
            "billing_city": "Fargo",
            "contact_email": "ops@delta.test",
            "duns": "40-400",
        },
        last_verified_at=CLOCK,
    )
    assert_master_record(record)

    assert record["curation_status"] == "CANDIDATE", (
        f"a newly ingested record must be a CANDIDATE, got {record['curation_status']}"
    )
    assert record["publication_status"] == "UNPUBLISHED", (
        f"a newly ingested record must be UNPUBLISHED, got {record['publication_status']}"
    )

    curated = validate_success(
        api.curate_master_record(record["id"], ctx["steward_headers"])
    )
    assert_master_record(curated)

    assert curated["curation_status"] == "CURATED", (
        f"curation must move the curation dimension to CURATED, got {curated['curation_status']}"
    )
    assert curated["publication_status"] == "UNPUBLISHED", (
        "curating never changes the publication dimension, got "
        f"{curated['publication_status']}"
    )
    assert curated["published_at"] is None, (
        f"curating stamps no publication instant, got {curated['published_at']!r}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["published_master_record_count"] == 0, (
        "curating publishes nothing, so the domain's published count must stay "
        f"at zero, got {domain['published_master_record_count']!r}"
    )


def test_publishing_a_record_advances_only_the_publication_dimension(api):
    """Releasing a curated record downstream moves its publication dimension and
    counts it on the domain, without re-labelling its curation dimension.

    PRD §3.6: "On success `publication_status` becomes `PUBLISHED`,
    `published_at` is stamped from the logical clock, the domain's
    `published_master_record_count` is incremented by one, and the domain's
    `version` advances by one."

    PRD §3.6: "It bears emphasising that a master record runs two state
    dimensions independently on the same row."

    PRD §3.6: "Publishing never changes `curation_status`, and curating never
    changes `publication_status`."

    PRD §2.8: "`Domain.published_master_record_count` is the exact integer count
    of the domain's master records whose `publication_status` is `PUBLISHED`."

    Design: Corner/state_machines/publication_and_curation_dimensions_advance_independently
    """
    ctx = setup_governed_domain()
    record = add_master_record(
        ctx,
        source_code="ERP",
        curate=True,
        natural_key="ERP-CUST-4001",
        attributes={
            "legal_name": "Delta Foods",
            "tax_id": "TX-40",
            "billing_city": "Fargo",
            "contact_email": "ops@delta.test",
            "duns": "40-400",
        },
        last_verified_at=CLOCK,
    )

    assert record["curation_status"] == "CURATED", (
        f"the record must be endorsed before publication, got {record['curation_status']}"
    )
    before = read_domain(ctx["domain"]["id"])

    published = validate_success(
        api.publish_master_record(record["id"], ctx["steward_headers"])
    )
    assert_master_record(published)

    assert published["publication_status"] == "PUBLISHED", (
        "publication must move the publication dimension to PUBLISHED, got "
        f"{published['publication_status']}"
    )
    assert_instant_equals(published["published_at"], CLOCK, "published_at")
    assert published["curation_status"] == "CURATED", (
        "publishing never changes the curation dimension, got "
        f"{published['curation_status']}"
    )

    after = read_domain(ctx["domain"]["id"])
    assert after["published_master_record_count"] == 1, (
        "the domain must count its one published record, got "
        f"{after['published_master_record_count']!r}"
    )
    assert after["version"] == before["version"] + 1, (
        "publication advances the domain version by exactly one, got "
        f"{after['version']!r} after {before['version']!r}"
    )
