"""Multi-hop cascades out of one write, and the gap ledger that comes back."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_ENGAGEMENT_RESTRICTED
from test_helpers.assertions import (
    assert_finding_ledger_identity,
    assert_money,
    assert_partition_counts,
    assert_percentage,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_segment_state,
    assert_total_count,
    assert_utc_millis_timestamp,
    find_row,
)
from test_helpers.constants import CLOCK_DEFAULT
from test_helpers.factories import (
    assign_payload,
    dispute_decision_payload,
    dispute_payload,
    reopen_payload,
    retest_payload,
    roc_payload,
)
from test_helpers.fixtures import (
    Scenario,
    add_component,
    build_approved_vendor_with_cycle,
    build_fieldwork_engagement,
    build_registry,
    complete_cycle,
    declare_segment,
    draw_plan,
    ok,
    open_engagement,
    plan_segmentation,
    publish_finding,
    read_engagement,
    record_verdict,
    requirement_concluded,
    validated_segment,
)
from test_helpers.test_users import make_asv_vendor_headers, make_lead_headers

DATA_CENTER = "DATA_CENTER"
RETAIL_STORE = "RETAIL_STORE"


def _store_subtree_awaiting_its_verdict(api) -> Scenario:
    """Build a two-deep retail subtree whose upper boundary is about to be tested.

    A validated cardholder zone holds three hosts at DC-EAST. Beneath a retail
    zone the client declared out of scope sit four terminals, and beneath that
    retail zone sits a back-office zone holding one network device. Only the
    cardholder hosts are eligible when the sample is drawn.
    """
    scenario = build_registry(api)
    lead_id = scenario["lead_id"]
    engagement = open_engagement(api, lead_id, qa_reviewer_id=scenario["qa_id"])
    scenario["engagement_id"] = engagement["id"]
    engagement_id = engagement["id"]

    cde = validated_segment(
        api,
        engagement_id,
        lead_id,
        name="CDE-CORE",
        segment_class="CDE",
        test_method="PEN_TEST",
        planned_date="2026-08-05",
    )
    components = {}
    for hostname, component_type, function_class, stores_chd in (
        ("app-01", "SERVER", "SECURITY_SERVICE", False),
        ("pay-01", "APPLICATION", "PAYMENT_APPLICATION", True),
        ("pay-02", "APPLICATION", "PAYMENT_APPLICATION", True),
    ):
        components[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            cde["id"],
            hostname,
            component_type=component_type,
            function_class=function_class,
            stores_chd=stores_chd,
            facility_name="DC-EAST",
            facility_type=DATA_CENTER,
        )

    store = declare_segment(
        api, engagement_id, lead_id, "STORE-POS", segment_class="OUT_OF_SCOPE"
    )
    plan_segmentation(
        api,
        store["id"],
        lead_id,
        test_method="TRAFFIC_ANALYSIS",
        planned_date="2026-08-06",
    )
    backoffice = declare_segment(
        api,
        engagement_id,
        lead_id,
        "STORE-BACKOFFICE",
        segment_class="OUT_OF_SCOPE",
        parent_segment_id=store["id"],
    )
    for hostname in ("pos-01", "pos-02", "pos-03", "pos-04"):
        components[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            store["id"],
            hostname,
            component_type="POS_TERMINAL",
            function_class="PAYMENT_APPLICATION",
            facility_name="RETAIL-12",
            facility_type=RETAIL_STORE,
        )
    components["net-01"] = add_component(
        api,
        engagement_id,
        lead_id,
        backoffice["id"],
        "net-01",
        component_type="NETWORK_DEVICE",
        function_class="CONNECTED_SUPPORT",
        facility_name="RETAIL-12",
        facility_type=RETAIL_STORE,
    )

    scenario["cde_segment_id"] = cde["id"]
    scenario["store_segment_id"] = store["id"]
    scenario["backoffice_segment_id"] = backoffice["id"]
    scenario["components"] = components
    scenario["component_ids"] = {name: row["id"] for name, row in components.items()}
    scenario["plan"] = draw_plan(api, engagement_id, lead_id, plan_variant="FINAL")
    scenario["plan_id"] = scenario["plan"]["id"]
    return scenario


class TestSegmentationFailureCascade:
    """One disproven boundary reaches five entity layers on a single call."""

    def test_failing_verdict_flips_the_zone_and_its_descendant_to_cardholder_class(
        self, api
    ):
        """The retail zone and the back-office zone beneath it both read CDE.

        PRD: **Second**, because that zone's `effective_class` became `CDE`, every
        zone in its descendant closure through `parent_segment_id` — children,
        grandchildren and onward, at any depth — also has `effective_class` set to
        `CDE`; their own declared `segment_class` values are left exactly as the
        client asserted them.

        Design: Difficulty/transitive_cascade/segmentation_failure_five_link_scope_cascade
        """
        scenario = _store_subtree_awaiting_its_verdict(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)

        failed = record_verdict(
            api,
            scenario["store_segment_id"],
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )

        # The tested zone itself latches the expansion flag.
        assert_segment_state(
            failed,
            segmentation_status="FAILED",
            effective_class="CDE",
            segment_class="OUT_OF_SCOPE",
            scope_expanded_by_failure=True,
        )
        # The zone beneath it is dragged along, yet only the tested zone latched.
        backoffice = validate_success(
            api.get_network_segment(scenario["backoffice_segment_id"], lead_headers)
        )
        assert_segment_state(
            backoffice,
            segmentation_status="DECLARED",
            effective_class="CDE",
            segment_class="OUT_OF_SCOPE",
            scope_expanded_by_failure=False,
        )
        # The proven cardholder zone is untouched by somebody else's failure.
        cde = validate_success(
            api.get_network_segment(scenario["cde_segment_id"], lead_headers)
        )
        assert_segment_state(
            cde,
            segmentation_status="VALIDATED",
            effective_class="CDE",
            segment_class="CDE",
            scope_expanded_by_failure=False,
        )
        assert_total_count(
            api.list_network_segments(
                lead_headers,
                {"engagement_id": scenario["engagement_id"], "effective_class": "CDE"},
            ),
            3,
        )
        assert_total_count(
            api.list_network_segments(
                lead_headers,
                {"engagement_id": scenario["engagement_id"], "segment_class": "OUT_OF_SCOPE"},
            ),
            2,
        )

    def test_failing_verdict_repartitions_the_inventory_and_stales_the_plan(self, api):
        """Every host under the failed boundary moves, and the draw goes stale.

        PRD: **Fourth**, because the component partition changed, the engagement's
        `cde_component_count`, `connected_component_count`,
        `out_of_scope_component_count` and `in_scope_component_count` are all
        recomputed, and the engagement's most recently created sampling plan — if
        that plan's `status` is `ACTIVE` — moves `ACTIVE → STALE`, which clears the
        engagement's `active_sampling_plan_id` to null and sets `active_plan_stale`
        to true.

        Design: Difficulty/transitive_cascade/segmentation_failure_five_link_scope_cascade
        """
        scenario = _store_subtree_awaiting_its_verdict(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        before = read_engagement(api, engagement_id, lead_id)
        assert_partition_counts(before, cde=3, connected=0, out_of_scope=5)

        record_verdict(
            api,
            scenario["store_segment_id"],
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )

        # A terminal and the back-office device both cross into the environment.
        for hostname in ("pos-01", "net-01"):
            row = validate_success(
                api.get_system_component(
                    scenario["component_ids"][hostname], lead_headers
                )
            )
            assert row["scope_class"] == "CDE"
            assert row["declared_scope_class"] == "OUT_OF_SCOPE"
        assert_total_count(
            api.list_system_components(
                lead_headers, {"engagement_id": engagement_id, "scope_class": "CDE"}
            ),
            8,
        )
        assert_total_count(
            api.list_system_components(
                lead_headers,
                {"engagement_id": engagement_id, "scope_class": "OUT_OF_SCOPE"},
            ),
            0,
        )
        # The client's original assertion is still readable beside the finding.
        assert_total_count(
            api.list_system_components(
                lead_headers,
                {"engagement_id": engagement_id, "declared_scope_class": "OUT_OF_SCOPE"},
            ),
            5,
        )

        after = read_engagement(api, engagement_id, lead_id)
        assert_partition_counts(after, cde=8, connected=0, out_of_scope=0)
        assert after["active_sampling_plan_id"] is None
        assert after["active_plan_stale"] is True
        retired = validate_success(
            api.get_sampling_plan(scenario["plan_id"], lead_headers)
        )
        assert retired["status"] == "STALE"
        assert retired["superseded_at"] is None
        # A verdict is not one of the writes that re-prices the engagement.
        assert after["estimated_hours"] == 226
        assert_money(after["assessment_fee_total"], 59189.40)

    def test_the_failed_boundary_restricts_the_engagement_and_blocks_scope_lock(
        self, api
    ):
        """The stale draw is what stops the lead from declaring scope final.

        PRD: **Fifth**, because `active_plan_stale` became true, the engagement's
        `posture` recomputes to `RESTRICTED`, which is what blocks scope lock and
        report creation until a fresh plan is drawn.

        Design: Difficulty/transitive_cascade/segmentation_failure_five_link_scope_cascade
        """
        scenario = _store_subtree_awaiting_its_verdict(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]

        record_verdict(
            api,
            scenario["store_segment_id"],
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["posture"] == "RESTRICTED"
        assert engagement["status"] == "SCOPING"
        assert engagement["active_plan_stale"] is True
        # A failed zone is still unvalidated, so both retail zones still count.
        assert engagement["unvalidated_segment_count"] == 2

        refused = api.lock_scope(engagement_id, lead_headers)
        validate_error(refused, ERR_ENGAGEMENT_RESTRICTED, 409)
        held = read_engagement(api, engagement_id, lead_id)
        assert held["scope_locked"] is False
        assert held["status"] == "SCOPING"


def _disputed_high_finding(api) -> Scenario:
    """Bring an engagement to a failing quarter with one contested high finding.

    The quarterly requirement 11.3.1 has already been concluded in place, the
    vendor has published a 7.5 finding on app-01 and closed the quarter, and the
    lead has argued the finding is a false positive.
    """
    scenario = build_fieldwork_engagement(api)
    lead_id = scenario["lead_id"]
    requirement = requirement_concluded(
        api,
        scenario["engagement_id"],
        lead_id,
        "11.3.1",
        "R11",
        scenario["component_ids"]["app-01"],
        conclusion="IN_PLACE",
        conclusion_rationale="Scans are run quarterly by an approved vendor.",
    )
    scenario["requirement"] = requirement
    scenario["requirement_id"] = requirement["id"]

    build_approved_vendor_with_cycle(api, scenario)
    vendor_id = scenario["vendor_id"]
    finding = publish_finding(
        api,
        scenario["cycle_id"],
        vendor_id,
        scenario["component_ids"]["app-01"],
        plugin_reference="PLG-40912",
        cvss_score=7.5,
    )
    complete_cycle(api, scenario["cycle_id"], vendor_id)
    scenario["finding"] = ok(
        api.dispute_scan_finding(
            finding["id"],
            dispute_payload(
                dispute_rationale="The plugin flags a backported patch level."
            ),
            make_lead_headers(lead_id),
        )
    )
    scenario["finding_id"] = finding["id"]
    return scenario


def _reject_the_dispute(api, scenario: Scenario):
    return ok(
        api.decide_scan_finding_dispute(
            scenario["finding_id"],
            dispute_decision_payload(
                decision="REJECT",
                decision_note="The patch level could not be corroborated.",
            ),
            make_asv_vendor_headers(scenario["vendor_id"]),
        )
    )


class TestRejectedScanDisputeCascade:
    """A rejected false-positive claim reaches out of scanning into fieldwork."""

    def test_rejected_claim_leaves_the_finding_standing_and_fails_the_quarter(
        self, api
    ):
        """The effective count holds at one, so the quarter cannot pass.

        PRD: **First**, the finding moves `DISPUTED → REJECTED` with `decided_at`
        and `decision_note` written and the cycle's `open_dispute_count`
        decremented; `effective_high_finding_count` does not change, because a
        rejected claim leaves the finding standing.

        Design: Difficulty/transitive_cascade/rejected_scan_dispute_five_link_gap_cascade
        """
        scenario = _disputed_high_finding(api)
        lead_headers = make_lead_headers(scenario["lead_id"])
        before = validate_success(
            api.get_scan_cycle(scenario["cycle_id"], lead_headers)
        )
        assert before["status"] == "DISPUTE_OPEN"
        assert before["open_dispute_count"] == 1

        decided = _reject_the_dispute(api, scenario)

        assert decided["dispute_status"] == "REJECTED"
        assert decided["severity_class"] == "HIGH_OR_ABOVE"
        assert decided["decision_note"] == "The patch level could not be corroborated."
        assert_utc_millis_timestamp(decided["decided_at"])
        assert_same_instant(decided["decided_at"], CLOCK_DEFAULT)

        cycle = validate_success(api.get_scan_cycle(scenario["cycle_id"], lead_headers))
        assert cycle["open_dispute_count"] == 0
        assert cycle["raw_high_finding_count"] == 1
        assert cycle["accepted_false_positive_count"] == 0
        assert cycle["effective_high_finding_count"] == 1
        assert_finding_ledger_identity(cycle)
        # The quarter returns to failing rather than passing.
        assert cycle["status"] == "FAILING"
        assert cycle["attestation_of_scan_compliance"] is False

    def test_rejected_claim_reverts_the_quarterly_scanning_requirement(self, api):
        """Requirement 11.3.1 loses its conclusion the moment the quarter fails.

        PRD: **Third**, because the cycle is failing, the engagement's
        `quarterly_scan_compliant` flag is recomputed to false — a cycle cannot
        recover scan compliance while any effective high finding stands — and every
        requirement assessment of that engagement whose `requirement_ref` is exactly
        `11.3.1` and whose `test_status` is `IN_PLACE` reverts to `IN_TESTING` with
        `remediation_status` moving to `GAP_OPEN`.

        Design: Difficulty/transitive_cascade/rejected_scan_dispute_five_link_gap_cascade
        """
        scenario = _disputed_high_finding(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        before = read_engagement(api, scenario["engagement_id"], lead_id)
        assert before["open_gap_count"] == 0
        assert_requirement_dimensions(
            scenario["requirement"], test_status="IN_PLACE", remediation_status="NONE"
        )

        _reject_the_dispute(api, scenario)

        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["quarterly_scan_compliant"] is False
        requirement = validate_success(
            api.get_requirement_assessment(scenario["requirement_id"], lead_headers)
        )
        assert_requirement_dimensions(
            requirement, test_status="IN_TESTING", remediation_status="GAP_OPEN"
        )
        assert requirement["requirement_ref"] == "11.3.1"
        # The single applicable requirement is no longer in place.
        assert_percentage(engagement["as_attested_compliance_percentage"], 0.00)

    def test_rejected_claim_mints_a_traceable_gap_and_blocks_the_report(self, api):
        """The gap the scan produced names the finding that caused it.

        PRD: **Fourth**, because that requirement reverted, a remediation item is
        minted with `source` `SCAN_FINDING_REJECTED` and `source_scan_finding_id`
        naming this finding, and the engagement's `open_gap_count` increments.

        Design: Difficulty/transitive_cascade/rejected_scan_dispute_five_link_gap_cascade
        """
        scenario = _disputed_high_finding(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]

        _reject_the_dispute(api, scenario)

        # A cascade-minted item is only reachable through the filtered listing.
        minted = assert_total_count(
            api.list_remediation_items(
                lead_headers,
                {"engagement_id": engagement_id, "source": "SCAN_FINDING_REJECTED"},
            ),
            1,
        )
        item = minted[0]
        assert item["source_scan_finding_id"] == scenario["finding_id"]
        assert item["requirement_assessment_id"] == scenario["requirement_id"]
        assert item["status"] == "OPEN"
        # R11 carries three risk points, which is a medium gap.
        assert item["severity"] == "MEDIUM"
        assert item["retest_count"] == 0
        assert item["owner_reference"] is None
        assert item["due_date"] is None
        by_finding = assert_total_count(
            api.list_remediation_items(
                lead_headers, {"source_scan_finding_id": scenario["finding_id"]}
            ),
            1,
        )
        assert by_finding[0]["id"] == item["id"]

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["open_gap_count"] == 1
        assert engagement["posture"] == "RESTRICTED"
        assert engagement["status"] == "FIELDWORK"
        refused = api.create_roc(engagement_id, roc_payload("v1.0"), lead_headers)
        validate_error(refused, ERR_ENGAGEMENT_RESTRICTED, 409)
        assert_total_count(
            api.list_rocs(lead_headers, {"engagement_id": engagement_id}), 0
        )


OPEN_GAP_STATUSES = ("OPEN", "IN_PROGRESS", "RETEST_FAILED")


def _two_requirements_in_place(api) -> Scenario:
    """A fieldwork engagement whose two applicable requirements are both in place."""
    scenario = build_fieldwork_engagement(api)
    lead_id = scenario["lead_id"]
    scenario["requirement_a"] = requirement_concluded(
        api,
        scenario["engagement_id"],
        lead_id,
        "1.2.1",
        "R1",
        scenario["component_ids"]["pay-01"],
        conclusion="IN_PLACE",
        conclusion_rationale="Rule set, interview and observation agree.",
    )
    scenario["requirement_b"] = requirement_concluded(
        api,
        scenario["engagement_id"],
        lead_id,
        "8.3.1",
        "R8",
        scenario["component_ids"]["app-01"],
        conclusion="IN_PLACE",
        conclusion_rationale="Multi-factor authentication observed on every path.",
    )
    scenario["requirement_a_id"] = scenario["requirement_a"]["id"]
    scenario["requirement_b_id"] = scenario["requirement_b"]["id"]
    return scenario


def _count_unclosed_gap_rows(api, engagement_id: str, headers) -> int:
    """Count the engagement's remediation items that still stand open."""
    total = 0
    for status in OPEN_GAP_STATUSES:
        rows = validate_success(
            api.list_remediation_items(
                headers, {"engagement_id": engagement_id, "status": status}
            )
        )
        total += len(rows)
    return total


def _reopen(api, requirement_id: str, lead_id: str):
    return ok(
        api.reopen_requirement(
            requirement_id,
            reopen_payload(
                reason="A change-log entry showed the rule set was edited after testing."
            ),
            make_lead_headers(lead_id),
        )
    )


def _reopened_gap_item(api, scenario: Scenario):
    """Reopen the firewall requirement and hand back the gap the reopen minted."""
    _reopen(api, scenario["requirement_a_id"], scenario["lead_id"])
    lead_headers = make_lead_headers(scenario["lead_id"])
    rows = validate_success(
        api.list_remediation_items(
            lead_headers, {"engagement_id": scenario["engagement_id"]}
        )
    )
    return find_row(rows, source="REQUIREMENT_REOPEN")


class TestGapLedgerReopenThenRetest:
    """The open-gap ledger rises on a reopen and comes back on a passing retest."""

    def test_reopening_a_concluded_requirement_raises_the_ledger_to_one(self, api):
        """One reopen mints one gap, and the ledger agrees with the rows.

        PRD: **Third**, the engagement's `open_gap_count` rises by 1 and its
        `as_attested_compliance_percentage` falls.

        Design: Difficulty/compensating_invariant/gap_ledger_reopen_then_retest_restores_open_gap_count
        """
        scenario = _two_requirements_in_place(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]

        before = read_engagement(api, engagement_id, lead_id)
        assert before["posture"] == "OPEN"
        assert before["open_gap_count"] == 0
        assert before["applicable_requirement_count"] == 2
        assert_percentage(before["as_found_compliance_percentage"], 100.00)
        assert_percentage(before["as_attested_compliance_percentage"], 100.00)
        assert _count_unclosed_gap_rows(api, engagement_id, lead_headers) == 0

        reopened = _reopen(api, scenario["requirement_a_id"], lead_id)

        assert_requirement_dimensions(
            reopened, test_status="IN_TESTING", remediation_status="GAP_OPEN"
        )
        assert reopened["reopen_count"] == 1
        rows = assert_total_count(
            api.list_remediation_items(
                lead_headers, {"engagement_id": engagement_id}
            ),
            1,
        )
        item = rows[0]
        assert item["source"] == "REQUIREMENT_REOPEN"
        assert item["status"] == "OPEN"
        assert item["requirement_assessment_id"] == scenario["requirement_a_id"]
        assert item["source_scan_finding_id"] is None
        assert item["retest_count"] == 0
        assert item["closed_at"] is None

        after = read_engagement(api, engagement_id, lead_id)
        assert after["open_gap_count"] == 1
        assert after["posture"] == "RESTRICTED"
        assert _count_unclosed_gap_rows(api, engagement_id, lead_headers) == 1
        # Only the authentication requirement is still in place.
        assert_percentage(after["as_attested_compliance_percentage"], 50.00)
        assert_percentage(after["as_found_compliance_percentage"], 50.00)

    def test_assigning_the_gap_does_not_let_the_ledger_dip(self, api):
        """A gap handed to the client is still an open gap.

        PRD: Either way the item moves to `IN_PROGRESS`, the item's `version`
        advances by 1, and the item continues to count toward the engagement's
        `open_gap_count` — assigning a gap does not close it.

        Design: Difficulty/compensating_invariant/gap_ledger_reopen_then_retest_restores_open_gap_count
        """
        scenario = _two_requirements_in_place(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        item = _reopened_gap_item(api, scenario)

        assigned = ok(
            api.assign_remediation_item(
                item["id"],
                assign_payload(
                    owner_reference="Client network team", due_date="2026-08-20"
                ),
                lead_headers,
            )
        )

        assert assigned["status"] == "IN_PROGRESS"
        assert assigned["owner_reference"] == "Client network team"
        assert assigned["due_date"] == "2026-08-20"
        assert assigned["version"] == item["version"] + 1
        assert assigned["closed_at"] is None

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["open_gap_count"] == 1
        assert engagement["posture"] == "RESTRICTED"
        assert _count_unclosed_gap_rows(api, engagement_id, lead_headers) == 1
        assert_percentage(engagement["as_attested_compliance_percentage"], 50.00)

    def test_a_passing_retest_restores_the_ledger_but_never_the_as_found_figure(
        self, api
    ):
        """The counter comes back to zero; the as-found percentage stays down.

        PRD: **Fourth**, `posture` recomputes to `OPEN`, and
        `as_attested_compliance_percentage` returns to the literal value it held
        before the reopen while `as_found_compliance_percentage` stays lower —
        permanently.

        Design: Difficulty/compensating_invariant/gap_ledger_reopen_then_retest_restores_open_gap_count
        """
        scenario = _two_requirements_in_place(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        item = _reopened_gap_item(api, scenario)
        ok(
            api.assign_remediation_item(
                item["id"],
                assign_payload(
                    owner_reference="Client network team", due_date="2026-08-20"
                ),
                lead_headers,
            )
        )

        retested = ok(
            api.retest_remediation_item(
                item["id"],
                retest_payload(
                    outcome="PASS", note="The reverted rule set was re-observed."
                ),
                lead_headers,
            )
        )

        assert retested["status"] == "RETEST_PASSED"
        assert retested["retest_count"] == 1
        assert_utc_millis_timestamp(retested["closed_at"])
        assert_same_instant(retested["closed_at"], CLOCK_DEFAULT)

        requirement = validate_success(
            api.get_requirement_assessment(scenario["requirement_a_id"], lead_headers)
        )
        # The requirement is in place again, but the gap it carried is on record.
        assert_requirement_dimensions(
            requirement,
            test_status="IN_PLACE",
            remediation_status="GAP_REMEDIATED",
        )

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["open_gap_count"] == 0
        assert _count_unclosed_gap_rows(api, engagement_id, lead_headers) == 0
        assert engagement["posture"] == "OPEN"
        assert_percentage(engagement["as_attested_compliance_percentage"], 100.00)
        assert_percentage(engagement["as_found_compliance_percentage"], 50.00)
        # A reopened requirement sat in testing, which that counter never counted.
        assert engagement["unmet_requirement_count"] == 0
        # Nothing in the remediation round moved a fee driver.
        assert engagement["estimated_hours"] == 226
        assert_money(engagement["assessment_fee_total"], 59189.40)
