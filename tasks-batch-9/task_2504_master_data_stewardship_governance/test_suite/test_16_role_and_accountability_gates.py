"""Role authorisation, per-domain accountability and segregation of duties.

Every request to the governance API declares a role and an acting identity, and
the platform gates writes on three separate things: the role must appear in the
authorised-role list of the endpoint, an entity-backed identity must additionally
be entitled on the target domain through an ACTIVE steward assignment covering
the logical clock, and a decision may never be taken by the same person who
raised the work being decided. The tests in this module exercise all three
gates, and in each case also confirm that the refused write left no trace.
"""

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    GOVERNANCE_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    add_change_request,
    add_consumer_subscription,
    add_master_record,
    api_client,
    assign_steward,
    change_request_payload,
    consumer_subscription_payload,
    create_domain,
    create_steward,
    domain_payload,
    is_iso8601_timestamp,
    list_findings,
    make_consumer_rep_headers,
    make_data_owner_headers,
    make_data_steward_headers,
    merge_proposal_payload,
    quality_rule_payload,
    read_domain,
    refresh_domain,
    run_scorecard,
    set_clock,
    setup_governed_domain,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# The auditor's read-only mandate
# ---------------------------------------------------------------------------


def test_auditor_is_refused_every_write_across_registry_and_action_endpoints(api):
    """PRD §2.1: "When `X-User-Role` is `Auditor`, `X-User-ID` is likewise an
    opaque identifier not tied to any persisted entity; an auditor may read
    every resource in the system, including master records and quality
    findings, and may mutate nothing."
    PRD §2.9: "The acting role appears in the endpoint's authorised-role list.
    Violation: `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    Design: Corner/RBAC/auditor_cannot_mutate_anything
    """
    set_clock("2026-08-01T00:00:00Z")
    domain = create_domain()
    steward = create_steward()
    assign_steward(domain["id"], steward["id"], "DATA_STEWARD")

    define_domain = api.create_domain(
        domain_payload(
            code="PRODUCT", name="Product Master", expected_attribute_count=4
        ),
        AUDITOR_HEADERS,
    )
    validate_error(define_domain, "ERR_UNAUTHORIZED")

    define_rule = api.create_quality_rule(
        quality_rule_payload(domain["id"], steward["id"]), AUDITOR_HEADERS
    )
    validate_error(define_rule, "ERR_UNAUTHORIZED")

    score = api.create_scorecard_run(
        domain["id"], {"basis": "PROVISIONAL", "measurements": []}, AUDITOR_HEADERS
    )
    validate_error(score, "ERR_UNAUTHORIZED")

    activate = api.activate_domain(domain["id"], AUDITOR_HEADERS)
    validate_error(activate, "ERR_UNAUTHORIZED")

    read = validate_success(api.get_domain(domain["id"], AUDITOR_HEADERS))
    assert read["status"] == "DRAFT", (
        "an auditor's refused writes must leave the domain in DRAFT, got "
        f"{read['status']}"
    )

    domains, meta = validate_paginated(api.list_domains(AUDITOR_HEADERS))
    assert meta["total_count"] == 1, (
        "the auditor's refused domain definition must not have created a row; "
        f"expected 1 domain, got {meta['total_count']}"
    )

    rules, rule_meta = validate_paginated(
        api.list_quality_rules(AUDITOR_HEADERS, params={"domain_id": domain["id"]})
    )
    assert rule_meta["total_count"] == 0, (
        "the auditor's refused rule definition must not have created a rule; "
        f"got {rule_meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Peer separation between the two stewardship roles and the governance office
# ---------------------------------------------------------------------------


def test_data_steward_is_refused_every_data_owner_decision_endpoint(api):
    """PRD §2.9: "The acting role appears in the endpoint's authorised-role list.
    Violation: `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.9: "Validations are evaluated in the following fifteen-step priority
    sequence, and the first failure determines the response — later checks are
    not reached and their errors are never returned in preference to an earlier
    one."
    PRD §2.9: "Every resource named in the path exists, checked left to right,
    yielding the specific 404 listed above."

    Design: Corner/RBAC/data_steward_holds_no_data_owner_exclusive
    """
    set_clock("2026-08-01T00:00:00Z")
    steward = create_steward()
    steward_headers = make_data_steward_headers(steward["id"])

    waive = api.waive_quality_finding(
        NON_EXISTENT_UUID,
        {"waiver_justification": "Accepted risk for this reporting period only"},
        steward_headers,
    )
    validate_error(waive, "ERR_UNAUTHORIZED")

    decide_merge = api.decide_merge_proposal(
        NON_EXISTENT_UUID, {"decision": "REJECT"}, steward_headers
    )
    validate_error(decide_merge, "ERR_UNAUTHORIZED")

    review_change = api.review_change_request(NON_EXISTENT_UUID, steward_headers)
    validate_error(review_change, "ERR_UNAUTHORIZED")

    decide_change = api.decide_change_request(
        NON_EXISTENT_UUID, {"decision": "APPROVE"}, steward_headers
    )
    validate_error(decide_change, "ERR_UNAUTHORIZED")

    schedule_change = api.schedule_change_request(
        NON_EXISTENT_UUID,
        {"scheduled_apply_at": "2026-09-01T00:00:00Z"},
        steward_headers,
    )
    validate_error(schedule_change, "ERR_UNAUTHORIZED")


def test_data_owner_is_refused_the_governance_office_registry_and_clock(api):
    """PRD §2.1: "When `X-User-Role` is `GovernanceAdmin`, `X-User-ID` is an
    opaque operator identifier not tied to any persisted entity; the governance
    office owns the registries — domain definitions, source systems, steward
    identities, source registrations, steward assignments and consumer
    subscriptions — plus source certification, domain activation, change
    application and the logical clock, and the server never compares its
    `X-User-ID` to any entity's `id`."
    PRD §2.9: "The acting role appears in the endpoint's authorised-role list.
    Violation: `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    Design: Corner/RBAC/stewards_hold_no_governance_admin_exclusive
    """
    set_clock("2026-08-01T00:00:00Z")
    domain = create_domain()
    owner = create_steward(
        full_name="Olivia Owner",
        email="olivia@mdm.test",
        certification_level="PRINCIPAL",
    )
    owner_headers = make_data_owner_headers(owner["id"])
    anchor_version = read_domain(domain["id"])["version"]

    define_domain = api.create_domain(
        domain_payload(
            code="VENDOR", name="Vendor Master", expected_attribute_count=4
        ),
        owner_headers,
    )
    validate_error(define_domain, "ERR_UNAUTHORIZED")

    certify = api.certify_source_system(NON_EXISTENT_UUID, owner_headers)
    validate_error(certify, "ERR_UNAUTHORIZED")

    assignment = api.create_steward_assignment(
        {
            "domain_id": domain["id"],
            "steward_id": owner["id"],
            "steward_role": "DATA_OWNER",
            "effective_from": "2026-08-01T00:00:00Z",
            "expected_domain_version": anchor_version,
        },
        owner_headers,
    )
    validate_error(assignment, "ERR_UNAUTHORIZED")

    apply_change = api.apply_change_request(NON_EXISTENT_UUID, owner_headers)
    validate_error(apply_change, "ERR_UNAUTHORIZED")

    move_clock = api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, owner_headers)
    validate_error(move_clock, "ERR_UNAUTHORIZED")

    domains, meta = validate_paginated(api.list_domains(GOVERNANCE_ADMIN_HEADERS))
    assert meta["total_count"] == 1, (
        "a data owner's refused registry writes must not create rows; expected "
        f"1 domain, got {meta['total_count']}"
    )

    assignments, assignment_meta = validate_paginated(
        api.list_steward_assignments(
            GOVERNANCE_ADMIN_HEADERS, params={"domain_id": domain["id"]}
        )
    )
    assert assignment_meta["total_count"] == 0, (
        "the refused accountability assignment must not exist, got "
        f"{assignment_meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Entitlement is per domain, not merely per role
# ---------------------------------------------------------------------------


def test_quality_rule_definition_requires_a_steward_assignment_on_that_domain(api):
    """PRD §2.1: "When `X-User-Role` is `DataSteward`, `X-User-ID` is likewise
    the `id` of the acting `Steward`, and the acting steward must hold an
    `ACTIVE` `StewardAssignment` on the target domain whose `steward_role` is
    either `DATA_STEWARD` or `CUSTODIAN` and whose interval covers the clock;
    failing that check yields `ERR_NOT_DOMAIN_STEWARD` (HTTP 403)."

    Design: Corner/RBAC/entitlement_requires_an_assignment_on_the_target_domain
    """
    ctx = setup_governed_domain(third_steward=True)
    unassigned = ctx["third"]

    response = api.create_quality_rule(
        quality_rule_payload(
            ctx["domain"]["id"],
            ctx["steward"]["id"],
            rule_code="QR9",
            dimension="VALIDITY",
            weight_points=10,
            threshold_pct=80.00,
            severity="LOW",
        ),
        make_data_steward_headers(unassigned["id"]),
    )
    validate_error(response, "ERR_NOT_DOMAIN_STEWARD")

    rules, meta = validate_paginated(
        api.list_quality_rules(
            GOVERNANCE_ADMIN_HEADERS, params={"domain_id": ctx["domain"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "a steward with no accountability on the domain must not add a rule; "
        f"expected only the domain's existing rule, got {meta['total_count']}"
    )


def test_change_request_review_requires_a_data_owner_assignment_on_that_domain(api):
    """PRD §2.1: "When `X-User-Role` is `DataOwner`, `X-User-ID` is the `id` of
    the acting `Steward`; ownership and accountability checks compare that
    identifier against the steward-identifier fields recorded on the target
    resource — for example a change request's `requester_steward_id` or a
    finding's `planned_by_steward_id` — and the acting steward must additionally
    hold an `ACTIVE` `StewardAssignment` on the target domain whose
    `steward_role` is `DATA_OWNER` and whose accountability interval covers the
    current logical clock. Failing that entitlement check yields
    `ERR_NOT_DOMAIN_OWNER` (HTTP 403)."

    Design: Corner/RBAC/entitlement_requires_an_assignment_on_the_target_domain
    """
    ctx = setup_governed_domain(third_steward=True)
    request = add_change_request(ctx, stage="DRAFT")

    unassigned_attempt = api.review_change_request(
        request["id"], make_data_owner_headers(ctx["third"]["id"])
    )
    validate_error(unassigned_attempt, "ERR_NOT_DOMAIN_OWNER")

    wrong_accountability_attempt = api.review_change_request(
        request["id"], make_data_owner_headers(ctx["steward"]["id"])
    )
    validate_error(wrong_accountability_attempt, "ERR_NOT_DOMAIN_OWNER")

    after = validate_success(
        api.get_change_request(request["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert after["status"] == "DRAFT", (
        f"a refused review must not move the request, got {after['status']}"
    )
    assert after["reviewer_steward_id"] is None, (
        "a refused review must leave no reviewer stamp, got "
        f"{after['reviewer_steward_id']!r}"
    )


def test_custodian_assignment_carries_the_data_steward_entitlement(api):
    """PRD §2.1: "When `X-User-Role` is `DataSteward`, `X-User-ID` is likewise
    the `id` of the acting `Steward`, and the acting steward must hold an
    `ACTIVE` `StewardAssignment` on the target domain whose `steward_role` is
    either `DATA_STEWARD` or `CUSTODIAN` and whose interval covers the clock;
    failing that check yields `ERR_NOT_DOMAIN_STEWARD` (HTTP 403)."
    PRD §3.3: "Rules are created in `status` `ACTIVE` and enter the scorecard
    denominator from the next run onward."

    Design: Corner/RBAC/custodian_satisfies_the_steward_entitlement_but_an_expired_assignment_does_not
    """
    set_clock("2026-08-05T00:00:00Z")
    domain = create_domain()
    custodian = create_steward(
        full_name="Nina Nomad", email="nina@mdm.test", certification_level="JUNIOR"
    )
    assignment = assign_steward(
        domain["id"],
        custodian["id"],
        "CUSTODIAN",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-10T00:00:00Z",
    )
    assert assignment["status"] == "ACTIVE", (
        f"a new accountability assignment is ACTIVE, got {assignment['status']}"
    )

    rule = validate_success(
        api.create_quality_rule(
            quality_rule_payload(
                domain["id"],
                custodian["id"],
                rule_code="QR1",
                dimension="VALIDITY",
                weight_points=10,
                threshold_pct=80.00,
                severity="LOW",
            ),
            make_data_steward_headers(custodian["id"]),
        ),
        201,
    )
    assert rule["status"] == "ACTIVE", (
        f"a rule defined by an entitled custodian is ACTIVE, got {rule['status']}"
    )


def test_custodian_entitlement_lapses_when_the_clock_reaches_effective_to(api):
    """PRD §3.1: "The governance office supplies the `domain_id`, the
    `steward_id`, the `steward_role` held — `DATA_OWNER`, `DATA_STEWARD` or
    `CUSTODIAN` — and a half-open accountability interval: `effective_from` is
    inclusive and `effective_to`, when supplied, is exclusive, so an assignment
    covers the clock when `effective_from` is at or before the current instant
    and either `effective_to` is null or the current instant falls strictly
    before it."
    PRD §2.1: "When `X-User-Role` is `DataSteward`, `X-User-ID` is likewise the
    `id` of the acting `Steward`, and the acting steward must hold an `ACTIVE`
    `StewardAssignment` on the target domain whose `steward_role` is either
    `DATA_STEWARD` or `CUSTODIAN` and whose interval covers the clock; failing
    that check yields `ERR_NOT_DOMAIN_STEWARD` (HTTP 403)."
    PRD §2.4: "Repositioning the clock mutates no entity and fires no scheduled
    action implicitly — nothing is applied, expired or notified as a side effect
    of moving time."

    Design: Corner/RBAC/custodian_satisfies_the_steward_entitlement_but_an_expired_assignment_does_not
    """
    set_clock("2026-08-05T00:00:00Z")
    domain = create_domain()
    custodian = create_steward(
        full_name="Nina Nomad", email="nina@mdm.test", certification_level="JUNIOR"
    )
    assignment = assign_steward(
        domain["id"],
        custodian["id"],
        "CUSTODIAN",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-10T00:00:00Z",
    )

    set_clock("2026-08-10T00:00:00Z")

    lapsed = api.create_quality_rule(
        quality_rule_payload(
            domain["id"],
            custodian["id"],
            rule_code="QR2",
            dimension="TIMELINESS",
            weight_points=10,
            threshold_pct=80.00,
            severity="LOW",
        ),
        make_data_steward_headers(custodian["id"]),
    )
    validate_error(lapsed, "ERR_NOT_DOMAIN_STEWARD")

    unchanged = validate_success(
        api.get_steward_assignment(assignment["id"], AUDITOR_HEADERS)
    )
    assert unchanged["status"] == "ACTIVE", (
        "moving the clock must not mutate the accountability row, got status "
        f"{unchanged['status']}"
    )

    rules, meta = validate_paginated(
        api.list_quality_rules(
            GOVERNANCE_ADMIN_HEADERS, params={"domain_id": domain["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "a rule refused for lapsed accountability must not exist, got "
        f"{meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# The consumer representative acts only on its own subscription
# ---------------------------------------------------------------------------


def test_consumer_representative_cannot_acknowledge_a_foreign_subscription(api):
    """PRD §2.1: "When `X-User-Role` is `ConsumerRep`, `X-User-ID` is the `id`
    of the acting `ConsumerSubscription` itself rather than of a steward; a
    consumer representative may act only on its own subscription, and any
    attempt to act on a subscription whose `id` differs from the supplied
    `X-User-ID` is rejected with `ERR_NOT_SUBSCRIPTION_OWNER` (HTTP 403)."

    Design: Corner/RBAC/consumer_rep_acknowledges_only_its_own_subscription
    """
    set_clock("2026-08-01T00:00:00Z")
    domain = create_domain()
    subscription_a = validate_success(
        api.create_consumer_subscription(
            consumer_subscription_payload(
                domain["id"],
                consumer_code="BI_A",
                reporting_asset_key="RPT_A",
                criticality="TIER1",
                required_lead_days=5,
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )
    subscription_b = validate_success(
        api.create_consumer_subscription(
            consumer_subscription_payload(
                domain["id"],
                consumer_code="BI_B",
                reporting_asset_key="RPT_B",
                criticality="TIER2",
                required_lead_days=5,
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )

    foreign = api.acknowledge_consumer_subscription(
        subscription_a["id"], make_consumer_rep_headers(subscription_b["id"])
    )
    validate_error(foreign, "ERR_NOT_SUBSCRIPTION_OWNER")

    untouched = validate_success(
        api.get_consumer_subscription(subscription_a["id"], AUDITOR_HEADERS)
    )
    assert untouched["acknowledged_at"] is None, (
        "a refused acknowledgement must not stamp acknowledged_at, got "
        f"{untouched['acknowledged_at']!r}"
    )


def test_consumer_representative_acknowledgement_needs_a_pending_notification(api):
    """PRD §3.9: "It requires a pending notification: a subscription whose
    `pending_change_request_id` is null has nothing to acknowledge and the
    attempt is rejected with `ERR_NO_PENDING_NOTIFICATION`."
    PRD §3.9: "A new subscription begins with `status` `ACTIVE` and
    `lineage_status` `UNDOCUMENTED`, an empty `lineage_path`, and
    `lineage_revision`, `lineage_documented_at`, `pending_change_request_id`,
    `notified_at`, `acknowledged_at`, `acknowledged_revision` and
    `suspended_reason` all null."

    Design: Corner/RBAC/consumer_rep_acknowledges_only_its_own_subscription
    """
    set_clock("2026-08-01T00:00:00Z")
    domain = create_domain()
    subscription = validate_success(
        api.create_consumer_subscription(
            consumer_subscription_payload(
                domain["id"],
                consumer_code="BI_A",
                reporting_asset_key="RPT_A",
                criticality="TIER1",
                required_lead_days=5,
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )
    assert subscription["pending_change_request_id"] is None, (
        "a brand-new subscription carries no pending notification, got "
        f"{subscription['pending_change_request_id']!r}"
    )

    own = api.acknowledge_consumer_subscription(
        subscription["id"], make_consumer_rep_headers(subscription["id"])
    )
    validate_error(own, "ERR_NO_PENDING_NOTIFICATION")


def test_consumer_representative_is_refused_the_internal_curation_reads(api):
    """PRD §2.9: "The acting role appears in the endpoint's authorised-role list.
    Violation: `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §4: "| GET | `/mdm/quality-rules/{rule_id}` | Read one quality rule |
    `GovernanceAdmin`, `DataOwner`, `DataSteward`, `Auditor` |"
    PRD §4: "| GET | `/mdm/master-records/{record_id}` | Read one master record |
    `GovernanceAdmin`, `DataOwner`, `DataSteward`, `Auditor` |"
    PRD §4: "| GET | `/mdm/stewards/{steward_id}` | Read one steward including
    the derived open_finding_load | `GovernanceAdmin`, `DataOwner`,
    `DataSteward`, `Auditor` |"
    PRD §4: "| GET | `/mdm/quality-findings` | List quality findings filtered by
    run, rule, assigned / planning / waiving steward or status |
    `GovernanceAdmin`, `DataOwner`, `DataSteward`, `Auditor` |"

    Design: Corner/RBAC/consumer_rep_read_surface_excludes_curation_data
    """
    ctx = setup_governed_domain()
    record = add_master_record(ctx, curate=False)
    subscription = add_consumer_subscription(ctx, criticality="TIER2")
    rep_headers = make_consumer_rep_headers(subscription["id"])
    rule = ctx["rules"]["QR1"]

    validate_error(api.get_quality_rule(rule["id"], rep_headers), "ERR_UNAUTHORIZED")
    validate_error(
        api.get_master_record(record["id"], rep_headers), "ERR_UNAUTHORIZED"
    )
    validate_error(
        api.get_steward(ctx["steward"]["id"], rep_headers), "ERR_UNAUTHORIZED"
    )
    validate_error(api.list_quality_findings(rep_headers), "ERR_UNAUTHORIZED")

    own_subscription = validate_success(
        api.get_consumer_subscription(subscription["id"], rep_headers)
    )
    assert own_subscription["consumer_code"] == subscription["consumer_code"], (
        "a consumer representative may read its own subscription, got "
        f"{own_subscription['consumer_code']}"
    )

    consumed_domain = validate_success(api.get_domain(ctx["domain"]["id"], rep_headers))
    assert consumed_domain["code"] == ctx["domain"]["code"], (
        "a consumer representative may read the domain it consumes, got "
        f"{consumed_domain['code']}"
    )

    audited_rule = validate_success(api.get_quality_rule(rule["id"], AUDITOR_HEADERS))
    assert audited_rule["rule_code"] == rule["rule_code"], (
        "the same rule must remain readable by an auditor, so the refusal is "
        f"role-scoped; got {audited_rule['rule_code']}"
    )


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------


def test_change_request_requester_cannot_take_their_own_request_under_review(api):
    """PRD §3.8: "`SUBMITTED → UNDER_REVIEW` requires the acting steward to hold
    an `ACTIVE` `DATA_OWNER` assignment on the domain covering the clock, and
    requires the acting `X-User-ID` to differ from `requester_steward_id`; a
    requester attempting to review their own request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/RBAC/change_request_requester_cannot_review_it
    """
    ctx = setup_governed_domain()
    own_request = validate_success(
        api.create_change_request(
            change_request_payload(
                ctx["domain"]["id"],
                title="Owner raised segment",
                proposed_values={"reference_value": "SEGMENT_SMB"},
            ),
            ctx["owner_headers"],
        ),
        201,
    )
    assert own_request["requester_steward_id"] == ctx["owner"]["id"], (
        "the raising owner must be recorded as requester, got "
        f"{own_request['requester_steward_id']}"
    )
    validate_success(
        api.submit_change_request(own_request["id"], ctx["owner_headers"])
    )

    self_review = api.review_change_request(own_request["id"], ctx["owner_headers"])
    validate_error(self_review, "ERR_SEGREGATION_OF_DUTIES")

    after = validate_success(api.get_change_request(own_request["id"], AUDITOR_HEADERS))
    assert after["status"] == "SUBMITTED", (
        f"a refused self-review must not move the request, got {after['status']}"
    )
    assert after["reviewer_steward_id"] is None, (
        "a refused self-review must leave no reviewer stamp, got "
        f"{after['reviewer_steward_id']!r}"
    )


def test_data_owner_may_review_a_change_request_raised_by_another_steward(api):
    """PRD §3.8: "`SUBMITTED → UNDER_REVIEW` requires the acting steward to hold
    an `ACTIVE` `DATA_OWNER` assignment on the domain covering the clock, and
    requires the acting `X-User-ID` to differ from `requester_steward_id`; a
    requester attempting to review their own request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "The transition records the acting `X-User-ID` as
    `reviewer_steward_id`."

    Design: Corner/RBAC/change_request_requester_cannot_review_it
    """
    ctx = setup_governed_domain()
    other_request = add_change_request(
        ctx,
        stage="SUBMITTED",
        title="Steward raised segment",
        proposed_values={"reference_value": "SEGMENT_ENT"},
    )
    assert other_request["requester_steward_id"] == ctx["steward"]["id"], (
        "the raising steward must be recorded as requester, got "
        f"{other_request['requester_steward_id']}"
    )

    reviewed = validate_success(
        api.review_change_request(other_request["id"], ctx["owner_headers"])
    )
    assert reviewed["status"] == "UNDER_REVIEW", (
        "an owner who did not raise the request may review it, expected "
        f"UNDER_REVIEW, got {reviewed['status']}"
    )
    assert reviewed["reviewer_steward_id"] == ctx["owner"]["id"], (
        "the reviewing owner must be recorded as reviewer, got "
        f"{reviewed['reviewer_steward_id']}"
    )


def test_finding_planner_cannot_waive_the_finding_they_planned(api):
    """PRD §3.5: "Only a `DataOwner` holding an `ACTIVE` `DATA_OWNER` assignment
    on the finding's domain covering the clock may waive, and the acting
    `X-User-ID` must differ from the finding's `planned_by_steward_id` — the
    person who planned the remediation may not be the person who excuses it,
    and an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.5: "On success the `assigned_steward_id`, `due_at` and `plan_note`
    are stored, `planned_by_steward_id` is set to the acting `X-User-ID`, and
    the assignee's `open_finding_load` is incremented by one."

    Design: Corner/RBAC/finding_planner_cannot_waive_the_same_finding
    """
    ctx = _setup_two_planned_findings()
    owner_planned = ctx["owner_planned_finding"]
    assert owner_planned["planned_by_steward_id"] == ctx["owner"]["id"], (
        "the acting owner must be recorded as the planner, got "
        f"{owner_planned['planned_by_steward_id']}"
    )
    assert owner_planned["assigned_steward_id"] == ctx["steward"]["id"], (
        "the nominated assignee must be the steward who will do the work, got "
        f"{owner_planned['assigned_steward_id']}"
    )

    refused = api.waive_quality_finding(
        owner_planned["id"],
        {"waiver_justification": "Accepted risk for the current reporting period"},
        ctx["owner_headers"],
    )
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES")

    after = validate_success(
        api.get_quality_finding(owner_planned["id"], AUDITOR_HEADERS)
    )
    assert after["status"] == "REMEDIATION_PLANNED", (
        "a refused waiver must leave the finding in the open set, got "
        f"{after['status']}"
    )
    assert after["waived_by_steward_id"] is None, (
        "a refused waiver must not record a waiver, got "
        f"{after['waived_by_steward_id']!r}"
    )


def test_data_owner_waives_a_finding_planned_by_another_steward(api):
    """PRD §3.5: "From `REMEDIATION_PLANNED → WAIVED`, the same fields are
    written and the same recomputations run, and additionally the assignee's
    `open_finding_load` is decremented by one."
    PRD §3.5: "From `OPEN → WAIVED`, the finding's `status` becomes `WAIVED`,
    `waived_by_steward_id` is set to the acting `X-User-ID`, `resolved_at` is
    stamped from the clock, no `open_finding_load` moves because none was
    charged, and both `open_finding_weight` and `governance_posture` are
    recomputed."
    PRD §2.8: "`Steward.open_finding_load` is the exact integer count of
    findings whose `assigned_steward_id` is that steward and whose `status` is
    `REMEDIATION_PLANNED` — note the filter is `REMEDIATION_PLANNED` only, so an
    `OPEN` finding never charges anyone's load."

    Design: Corner/RBAC/finding_planner_cannot_waive_the_same_finding
    """
    ctx = _setup_two_planned_findings()
    steward_planned = ctx["steward_planned_finding"]

    waived = validate_success(
        api.waive_quality_finding(
            steward_planned["id"],
            {"waiver_justification": "Accepted risk for the current reporting period"},
            ctx["owner_headers"],
        )
    )
    assert waived["status"] == "WAIVED", (
        "an owner who did not plan the remediation may waive it, expected "
        f"WAIVED, got {waived['status']}"
    )
    assert waived["waived_by_steward_id"] == ctx["owner"]["id"], (
        "the waiving owner must be recorded, got "
        f"{waived['waived_by_steward_id']}"
    )
    assert is_iso8601_timestamp(waived["resolved_at"]), (
        f"resolved_at must be stamped from the clock, got {waived['resolved_at']!r}"
    )

    assignee = validate_success(api.get_steward(ctx["steward"]["id"], AUDITOR_HEADERS))
    assert assignee["open_finding_load"] == 1, (
        "waiving one of the assignee's two planned findings must release exactly "
        f"one charge, expected 1, got {assignee['open_finding_load']}"
    )

    domain = refresh_domain(ctx)
    assert domain["open_finding_weight"] == pytest.approx(8.00, abs=0.01), (
        "the waived finding's weight must leave the open sum, leaving the single "
        f"remaining HIGH finding at 8.00, got {domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "OPEN", (
        "with 8.00 of open weight, an active authoritative source and no open "
        f"critical finding the posture is OPEN, got {domain['governance_posture']}"
    )


def test_merge_proposer_cannot_decide_their_own_proposal(api):
    """PRD §3.7: "In all three cases the proposal must actually be in
    `UNDER_REVIEW`, otherwise `ERR_PROPOSAL_NOT_UNDER_REVIEW`, and in all three
    cases the acting `X-User-ID` must differ from the proposal's
    `proposer_steward_id`, a self-decision being rejected with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "The transition `PROPOSED → UNDER_REVIEW` requires the proposal to
    be in `PROPOSED` status and requires the acting steward to hold an `ACTIVE`
    `StewardAssignment` on the proposal's domain covering the clock; it records
    the acting `X-User-ID` as `reviewer_steward_id`."

    Design: Corner/RBAC/merge_proposer_cannot_decide_the_same_proposal
    """
    ctx = setup_governed_domain()
    survivor = add_master_record(
        ctx,
        natural_key="CUST-A",
        attributes={
            "legal_name": "Lambda Co",
            "tax_id": "TX-14",
            "billing_city": "Boise",
            "contact_email": "a@lambda.test",
            "duns": "14-140",
        },
        last_verified_at="2026-08-01T00:00:00Z",
    )
    duplicate = add_master_record(
        ctx,
        natural_key="CUST-B",
        attributes={
            "legal_name": "Lambda Co",
            "tax_id": "TX-14",
            "billing_city": "Boise",
            "contact_email": "b@lambda.test",
            "duns": "14-140",
        },
        last_verified_at="2026-08-01T00:00:00Z",
    )

    proposal = validate_success(
        api.create_merge_proposal(
            merge_proposal_payload(
                survivor["id"],
                duplicate["id"],
                name_similarity_pct=100.00,
                key_overlap_pct=100.00,
            ),
            ctx["owner_headers"],
        ),
        201,
    )
    assert proposal["proposer_steward_id"] == ctx["owner"]["id"], (
        "the proposing owner must be recorded as proposer, got "
        f"{proposal['proposer_steward_id']}"
    )

    reviewed = validate_success(
        api.review_merge_proposal(proposal["id"], ctx["steward_headers"])
    )
    assert reviewed["reviewer_steward_id"] == ctx["steward"]["id"], (
        "a data steward may take a proposal under review, got reviewer "
        f"{reviewed['reviewer_steward_id']}"
    )

    self_decision = api.decide_merge_proposal(
        proposal["id"], {"decision": "REJECT"}, ctx["owner_headers"]
    )
    validate_error(self_decision, "ERR_SEGREGATION_OF_DUTIES")

    after = validate_success(api.get_merge_proposal(proposal["id"], AUDITOR_HEADERS))
    assert after["status"] == "UNDER_REVIEW", (
        f"a refused decision must not move the proposal, got {after['status']}"
    )
    assert after["decided_at"] is None, (
        f"a refused decision must not stamp decided_at, got {after['decided_at']!r}"
    )


# ---------------------------------------------------------------------------
# Local setup helper
# ---------------------------------------------------------------------------


def _setup_two_planned_findings():
    """Two HIGH-severity findings on one domain, one planned by the data owner
    and one planned by the data steward, both assigned to the steward."""
    ctx = setup_governed_domain(
        rules=[
            {
                "rule_code": "QR1",
                "dimension": "COMPLETENESS",
                "weight_points": 40,
                "threshold_pct": 90.00,
                "severity": "HIGH",
                "owner": "steward",
            },
            {
                "rule_code": "QR2",
                "dimension": "VALIDITY",
                "weight_points": 40,
                "threshold_pct": 90.00,
                "severity": "HIGH",
                "owner": "steward",
            },
        ]
    )
    run = run_scorecard(
        ctx,
        basis="PROVISIONAL",
        measurements=[
            {"rule_code": "QR1", "measured_pct": 50.00},
            {"rule_code": "QR2", "measured_pct": 50.00},
        ],
    )
    first = list_findings(
        ctx, scorecard_run_id=run["id"], quality_rule_id=ctx["rules"]["QR1"]["id"]
    )[0]
    second = list_findings(
        ctx, scorecard_run_id=run["id"], quality_rule_id=ctx["rules"]["QR2"]["id"]
    )[0]

    ctx["owner_planned_finding"] = validate_success(
        api_client.plan_finding_remediation(
            first["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": "Owner assigned the completeness gap to the steward",
            },
            ctx["owner_headers"],
        )
    )
    ctx["steward_planned_finding"] = validate_success(
        api_client.plan_finding_remediation(
            second["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": "Steward took the validity gap on themselves",
            },
            ctx["steward_headers"],
        )
    )
    return ctx
