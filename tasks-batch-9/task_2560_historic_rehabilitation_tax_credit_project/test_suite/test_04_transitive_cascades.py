"""Cascades that travel three and four rows deep from one request.

One concurrence resolves a finding, decrements a counter, completes an
application and advances a project. One audit disallowance re-runs the qualified
totals, raises a recapture event on the system's own initiative, moves the
compliance dimension and rewrites a claim that was already filed.
"""

from test_helpers import assertions, factories, fixtures, types, validate_success


def test_shpo_concurrence_resolves_the_finding_and_completes_the_application(api):
    """The concurrence joins immediately and clears the condition it addressed.

    Part 2 carries one CONDITION finding against Standard 6 and a CONDITIONAL
    determination, so it is parked with one unresolved condition. The submitted
    amendment addresses that finding with a 1000000 cost delta and a
    WINDOW_REPLACEMENT scope, neither of which needs the federal agency, so the
    state office alone disposes of it. Its CONCUR takes the amendment straight to
    CONCURRED, marks the finding RESOLVED, drops the unresolved count to zero and
    lets the application complete on its own with an APPROVED determination and no
    further reviewer action.

    PRD: "When `requires_nps_concurrence` is false, a `CONCUR` from an `ACTIVE` `SHPO` reviewer joins immediately: the amendment moves `SUBMITTED → CONCURRED` and `shpo_decision` becomes `CONCUR`."
    PRD: "The first hop sets that finding's `resolution_state` to `RESOLVED`, bumping the finding's `version`."
    PRD: "The third hop fires only when that count has thereby reached zero, the application's `unresolved_violation_count` is also zero, and the application's status is `CONDITIONAL`: the application then completes on its own, moving `CONDITIONAL → APPROVED` with its `determination` set to `APPROVED` and its `decision_at` stamped from the logical clock — no reviewer action is needed for this step."

    Design: Difficulty/transitive_cascade/amendment_concurrence_resolves_finding_then_auto_approves_part2_then_certifies_project
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    fixtures.walk_part_to_approved(api, cast, project["id"], 1)
    part2 = fixtures.create_part_application(
        api, cast, project["id"], 2, narrative="Rehabilitation plan."
    )
    fixtures.submit_part_application(api, cast, part2["id"])
    fixtures.shpo_recommend(api, cast, part2["id"])
    finding = fixtures.add_finding(
        api,
        cast,
        part2["id"],
        headers=cast.nps_headers,
        standard_number=6,
        severity="CONDITION",
        description=(
            "Replacement sash profile must match the historic muntin dimension."
        ),
    )
    conditional = fixtures.nps_determine(
        api, cast, part2["id"], determination="CONDITIONAL"
    )
    amendment = validate_success(
        api.create_amendment(
            cast.developer_headers,
            **factories.amendment_payload(
                project["id"],
                part2["id"],
                scope_category="WINDOW_REPLACEMENT",
                change_description=(
                    "Sash profile revised to match the historic muntin dimension."
                ),
                cost_delta_cents=1_000_000,
                addresses_finding_id=finding["id"],
            ),
        ),
        201,
    )
    validate_success(api.submit_amendment(amendment["id"], cast.developer_headers))
    types.assert_is_amendment(amendment)
    assertions.assert_fields(
        amendment, "drafted amendment", requires_nps_concurrence=False
    )
    assertions.assert_fields(
        conditional,
        "conditional part 2",
        status="CONDITIONAL",
        unresolved_condition_count=1,
    )

    concurred = validate_success(
        api.concur_amendment(
            amendment["id"],
            cast.shpo_headers,
            decision="CONCUR",
            concurrence_note="Revised profile meets Standard 6.",
        )
    )

    assertions.assert_fields(
        concurred, "concurred amendment", status="CONCURRED", shpo_decision="CONCUR"
    )
    resolved = validate_success(api.get_finding(finding["id"], cast.nps_headers))
    assertions.assert_fields(resolved, "addressed finding", resolution_state="RESOLVED")
    completed = validate_success(
        api.get_part_application(part2["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        completed,
        "completed part 2",
        status="APPROVED",
        determination="APPROVED",
        unresolved_condition_count=0,
        unresolved_violation_count=0,
    )
    assert completed["decision_at"] is not None, (
        "self-completion stamps decision_at from the clock"
    )


def test_the_same_concurrence_advances_the_project_certification_dimension(api):
    """The fourth hop follows the third and moves the project, not the compliance axis.

    Before the concurrence the project sits at PART1_CERTIFIED because Part 1 was
    approved and the CONDITIONAL determination on Part 2 expressly advanced
    nothing. Once the amendment's concurrence completes Part 2, the certification
    dimension advances to PART2_APPROVED exactly as an ordinary approval would have
    advanced it, while the compliance dimension stays at NOT_MONITORED.

    PRD: "The fourth hop follows the third: the project's certification dimension advances according to the completed application's `part_number`, exactly as an ordinary approval would advance it, bumping the project's `version`."
    PRD: "The project's certification dimension is expressly **not** advanced, and neither the property nor any cost line item is touched — the only row mutated is the application itself."
    PRD: "It begins at `NOT_MONITORED` and moves to `IN_SERVICE_MONITORING` when the building is declared placed in service; it oscillates to `CURE_PENDING` while a covenant is breached or a recapture balance is outstanding, and back to `IN_SERVICE_MONITORING` when both conditions clear."

    Design: Difficulty/transitive_cascade/amendment_concurrence_resolves_finding_then_auto_approves_part2_then_certifies_project
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    fixtures.walk_part_to_approved(api, cast, project["id"], 1)
    part2 = fixtures.create_part_application(
        api, cast, project["id"], 2, narrative="Rehabilitation plan."
    )
    fixtures.submit_part_application(api, cast, part2["id"])
    fixtures.shpo_recommend(api, cast, part2["id"])
    finding = fixtures.add_finding(
        api,
        cast,
        part2["id"],
        headers=cast.nps_headers,
        standard_number=6,
        severity="CONDITION",
    )
    fixtures.nps_determine(api, cast, part2["id"], determination="CONDITIONAL")
    amendment = validate_success(
        api.create_amendment(
            cast.developer_headers,
            **factories.amendment_payload(
                project["id"],
                part2["id"],
                cost_delta_cents=1_000_000,
                addresses_finding_id=finding["id"],
            ),
        ),
        201,
    )
    validate_success(api.submit_amendment(amendment["id"], cast.developer_headers))
    before = fixtures.read_project(api, cast, project["id"])
    assertions.assert_project_state(
        before, certification_status="PART1_CERTIFIED", compliance_status="NOT_MONITORED"
    )

    validate_success(
        api.concur_amendment(amendment["id"], cast.shpo_headers, decision="CONCUR")
    )

    after = fixtures.read_project(api, cast, project["id"])
    assertions.assert_project_state(
        after, certification_status="PART2_APPROVED", compliance_status="NOT_MONITORED"
    )
    assert after["version"] > before["version"], (
        "the fourth hop bumps the project version"
    )


def test_audit_disallowance_of_a_locked_cost_flips_the_substantial_test(api):
    """The monitor's one-way move re-runs the totals and leaves the credit frozen.

    The project is certified through Part 3 on a single locked qualified cost of
    62500013, and its 2029 claim has been filed. A ComplianceMonitor disallows that
    cost, which is the only permitted direction for a locked item: it becomes
    LOCKED_NON_QRE with an exclusion reason of REVIEWER_DISALLOWED. The qualified
    total falls to zero and the non-qualified total takes the whole 62500013, so the
    substantial test flips to NOT_MET, but the annual instalment stays at the
    2500001 that Part 3 certification froze.

    PRD: "Only a `ComplianceMonitor` can move a locked item, and only in one direction: an audit disallowance takes it `LOCKED_QRE → LOCKED_NON_QRE`, raising `reclassification_count`, setting `exclusion_reason` to `REVIEWER_DISALLOWED`, and bumping both the item's and the project's `version`."
    PRD: "The disallowance recomputes `qre_total_final_cents`, `nonqualified_total_cents` and `classified_cost_total_cents` while `annual_credit_cents` stays frozen — and if the recomputation flips `substantial_test_status` from `MET` to `NOT_MET` on a project whose certification dimension is `PART3_CERTIFIED`, the system raises a recapture event of its own accord, as described in §3.8."

    Design: Difficulty/transitive_cascade/locked_cost_disallowance_flips_substantial_test_then_assesses_recapture_then_adjusts_filed_claim
    """
    scenario = fixtures.claim_filed_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
        tax_year=2029,
    )
    cast = scenario["cast"]
    cost_id = scenario["cost"]["id"]
    locked = validate_success(api.get_cost_line_item(cost_id, cast.developer_headers))
    assertions.assert_fields(locked, "locked cost", classification="LOCKED_QRE")
    assertions.assert_ledger(
        scenario["project"],
        credit_claimed_to_date_cents=2_500_001,
        recapture_balance_cents=0,
        substantial_test_status="MET",
    )

    disallowed = fixtures.classify_cost(
        api,
        cast,
        cost_id,
        "NON_QRE",
        exclusion_reason="REVIEWER_DISALLOWED",
        headers=fixtures.MONITOR,
    )

    types.assert_is_cost_line_item(disallowed)
    assertions.assert_fields(
        disallowed,
        "disallowed cost",
        classification="LOCKED_NON_QRE",
        exclusion_reason="REVIEWER_DISALLOWED",
    )
    project = fixtures.read_project(api, cast, scenario["project"]["id"])
    assertions.assert_ledger(
        project,
        qre_total_final_cents=0,
        nonqualified_total_cents=62_500_013,
        classified_cost_total_cents=62_500_013,
        substantial_test_status="NOT_MET",
        annual_credit_cents=2_500_001,
    )
    assertions.assert_classified_cost_conservation(project)


def test_the_disallowance_raises_a_system_recapture_and_adjusts_the_filed_claim(api):
    """One disallowance assesses the whole credit and rewrites the filed claim.

    The flip to NOT_MET on a PART3_CERTIFIED project is the single situation in
    which the system raises its own recapture event. Exactly one such row appears,
    typed SUBSTANTIAL_TEST_FAILURE and sourced SYSTEM_DERIVED, and because a failed
    rehabilitation test claws back everything its percentage is 1.00 and its amount
    is the whole 2500001 claimed to date. That amount becomes the project's
    outstanding balance, the compliance dimension moves to CURE_PENDING, and the
    already-filed 2029 claim moves to ADJUSTED with its net figure deliberately
    left alone.

    PRD: "That event carries `event_type` of `SUBSTANTIAL_TEST_FAILURE` and `source` of `SYSTEM_DERIVED`, assesses the whole of `credit_claimed_to_date_cents`, raises `recapture_balance_cents` by that amount, moves the compliance dimension `IN_SERVICE_MONITORING → CURE_PENDING`, and moves every `FILED` claim of the project to `ADJUSTED`."
    PRD: "For an event of type `SUBSTANTIAL_TEST_FAILURE`, `recapture_pct` is exactly 1.00 — a failed substantial rehabilitation test claws back the entire credit claimed to date however long the building has been in service."
    PRD: "When a `SUBSTANTIAL_TEST_FAILURE` event is assessed against the project, every `FILED` claim moves `FILED → ADJUSTED` and its `version` increments, but its `net_claim_cents` is deliberately left unchanged — the obligation is carried on the project's `recapture_balance_cents` and worked off against future claims rather than rewritten into the history of past ones."

    Design: Difficulty/transitive_cascade/locked_cost_disallowance_flips_substantial_test_then_assesses_recapture_then_adjusts_filed_claim
    """
    scenario = fixtures.claim_filed_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
        tax_year=2029,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]

    fixtures.classify_cost(
        api,
        cast,
        scenario["cost"]["id"],
        "NON_QRE",
        exclusion_reason="REVIEWER_DISALLOWED",
        headers=fixtures.MONITOR,
    )

    events, _ = assertions.assert_page(
        api.list_project_recapture_events(
            project_id, fixtures.MONITOR, event_type="SUBSTANTIAL_TEST_FAILURE"
        ),
        total_count=1,
    )
    types.assert_is_recapture_event(events[0])
    assertions.assert_fields(
        events[0],
        "system-derived recapture event",
        event_type="SUBSTANTIAL_TEST_FAILURE",
        source="SYSTEM_DERIVED",
        recapture_pct=1.00,
        recapture_amount_cents=2_500_001,
        status="ASSESSED",
    )
    project = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(project, recapture_balance_cents=2_500_001)
    assertions.assert_project_state(project, compliance_status="CURE_PENDING")
    adjusted = validate_success(
        api.get_credit_claim(scenario["claim"]["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        adjusted,
        "previously filed claim",
        status="ADJUSTED",
        net_claim_cents=scenario["claim"]["net_claim_cents"],
    )
