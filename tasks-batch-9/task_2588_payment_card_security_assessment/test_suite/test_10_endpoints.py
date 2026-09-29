"""Endpoint surfaces: partial roster amendment, the consolidated engagement
roll-up, the logical-clock control and the replaceable reviewer link."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_keys_exactly,
    assert_money,
    assert_percentage,
    assert_same_instant,
    assert_total_count,
    assert_version_bumped_by,
    assert_version_unchanged,
)
from test_helpers.constants import QA_EMAIL, QA_NAME
from test_helpers.fixtures import (
    Scenario,
    build_registry,
    complete_cycle,
    open_engagement,
    read_engagement,
    record_change,
    register_assessor,
    register_vendor,
    schedule_scan_cycle,
    set_clock,
)
from test_helpers.test_users import (
    admin_headers,
    client_rep_headers,
    make_asv_vendor_headers,
    make_lead_headers,
)

# The reviewer's certification is re-dated behind the startup clock so that the
# roster's derived standing has to move without the stored fields moving.
LAPSED_CERT_INSTANT = "2026-07-01T00:00:00Z"

# The 2026-Q3 window opens on the first of July and, ninety days on, closes
# exclusively at the end of September.
Q3_WINDOW_START = "2026-07-01T00:00:00Z"
Q3_WINDOW_END = "2026-09-29T00:00:00Z"
AFTER_Q3_WINDOW = "2026-10-01T00:00:00Z"
AFTER_LEAD_CERTIFICATION = "2027-07-01T00:00:00Z"

SUMMARY_KEYS = [
    "engagement_id",
    "posture",
    "cde_component_count",
    "connected_component_count",
    "out_of_scope_component_count",
    "total_component_count",
    "open_gap_count",
    "unvalidated_segment_count",
    "accepted_ccw_count",
    "estimated_hours",
    "assessment_fee_total",
    "as_found_compliance_percentage",
    "as_attested_compliance_percentage",
    "quarterly_scan_compliant",
    "scope_affecting_change_count",
    "reassessment_required",
]


def _record_five_changes(api, scenario: Scenario) -> None:
    """Log five in-year changes, three of which actually touch the environment.

    The patched payment application and the marketing host the client marked as
    not affecting scope are both recorded, but neither counts toward a
    reassessment.
    """
    engagement_id = scenario["engagement_id"]
    lead_id = scenario["lead_id"]
    record_change(
        api,
        engagement_id,
        lead_id,
        "COMPONENT_ADDED_TO_CDE",
        "A reporting server was joined to the cardholder network.",
        True,
        component_id=scenario["component_ids"]["app-01"],
    )
    record_change(
        api,
        engagement_id,
        lead_id,
        "APPLICATION_UPDATED",
        "Payment application patched to 4.2.1.",
        True,
        component_id=scenario["component_ids"]["pay-01"],
    )
    record_change(
        api,
        engagement_id,
        lead_id,
        "COMPONENT_ADDED_TO_CDE",
        "A marketing host was added to the office network.",
        False,
    )
    record_change(
        api,
        engagement_id,
        lead_id,
        "SEGMENT_RECLASSIFIED",
        "The warehouse VLAN was reclassified as connected.",
        True,
    )
    record_change(
        api,
        engagement_id,
        lead_id,
        "THIRD_PARTY_ADDED",
        "A managed hosting provider took over the DC-EAST cage.",
        True,
    )


def _passing_cycle_scenario(api) -> Scenario:
    """A SCOPING engagement whose 2026-Q3 scan closed with no findings at all."""
    scenario = build_registry(api)
    engagement = open_engagement(
        api, scenario["lead_id"], qa_reviewer_id=scenario["qa_id"]
    )
    scenario["engagement"] = engagement
    scenario["engagement_id"] = engagement["id"]
    vendor = register_vendor(api)
    scenario["vendor"] = vendor
    scenario["vendor_id"] = vendor["id"]
    cycle = schedule_scan_cycle(
        api,
        engagement["id"],
        scenario["lead_id"],
        vendor["id"],
        quarter_label="2026-Q3",
        window_start=Q3_WINDOW_START,
    )
    scenario["cycle"] = complete_cycle(api, cycle["id"], vendor["id"])
    scenario["cycle_id"] = cycle["id"]
    return scenario


class TestAssessorAmendmentIsPartial:
    """Amending a roster record touches only the fields the body names."""

    def test_amending_only_the_expiry_leaves_every_other_field_alone(
        self, api, registry
    ):
        """Re-dating the certificate lapses the standing and nothing else moves.

        PRD: An amendment may also revise `full_name`, `email` and `qa_qualified`,
        recomputes `certification_status` immediately, and advances the assessor's
        `version` by 1.

        Design: Corner/endpoints/endpoint_patch_assessor_is_a_partial_update_that_reprojects_certification
        """
        reviewer = registry["qa"]
        assert reviewer["certification_status"] == "ACTIVE"

        amended = validate_success(
            api.update_assessor(
                reviewer["id"],
                {"certification_expires_at": LAPSED_CERT_INSTANT},
                admin_headers(),
            )
        )

        assert_same_instant(amended["certification_expires_at"], LAPSED_CERT_INSTANT)
        # The new date sits behind the startup clock, so the certificate has lapsed.
        assert amended["certification_status"] == "LAPSED"
        assert amended["full_name"] == QA_NAME
        assert amended["email"] == QA_EMAIL
        assert amended["qa_qualified"] is True
        assert amended["status"] == "ACTIVE"
        assert_version_bumped_by(reviewer["version"], amended["version"])

        # An absent key is an unmentioned field, never a blanked one.
        held = validate_success(api.get_assessor(reviewer["id"], admin_headers()))
        assert held["full_name"] == QA_NAME
        assert held["email"] == QA_EMAIL
        assert held["qa_qualified"] is True
        assert held["status"] == "ACTIVE"
        assert held["certification_status"] == "LAPSED"
        assert held["version"] == amended["version"]

    def test_suspension_and_lapse_are_two_independent_positions(self, api, registry):
        """A second amendment suspends the individual without re-dating anything.

        PRD: `certification_status` reads `ACTIVE` while the logical clock is
        strictly earlier than `certification_expires_at` and `LAPSED` from that
        instant onward — the distinction from the administrative `status` field
        matters, because a currently certified individual may still be `SUSPENDED`
        and a never-suspended individual may still be `LAPSED`.

        Design: Corner/endpoints/endpoint_patch_assessor_is_a_partial_update_that_reprojects_certification
        """
        reviewer = registry["qa"]
        lapsed = validate_success(
            api.update_assessor(
                reviewer["id"],
                {"certification_expires_at": LAPSED_CERT_INSTANT},
                admin_headers(),
            )
        )

        suspended = validate_success(
            api.update_assessor(
                reviewer["id"], {"status": "SUSPENDED"}, admin_headers()
            )
        )

        assert suspended["status"] == "SUSPENDED"
        assert_same_instant(suspended["certification_expires_at"], LAPSED_CERT_INSTANT)
        assert suspended["certification_status"] == "LAPSED"
        assert suspended["qa_qualified"] is True
        assert_version_bumped_by(lapsed["version"], suspended["version"])
        assert suspended["version"] == reviewer["version"] + 2

        headers = admin_headers()
        # Both positions are separately filterable on the roster listing.
        by_status = assert_total_count(
            api.list_assessors(headers, {"status": "SUSPENDED"}), 1
        )
        assert by_status[0]["id"] == reviewer["id"]
        by_certification = assert_total_count(
            api.list_assessors(headers, {"certification_status": "LAPSED"}), 1
        )
        assert by_certification[0]["id"] == reviewer["id"]
        # The lead was never amended and is still certified and available.
        lead = validate_success(api.get_assessor(registry["lead_id"], headers))
        assert lead["status"] == "ACTIVE"
        assert lead["certification_status"] == "ACTIVE"
        # Neither amendment body mentioned the review qualification.
        qualified = assert_total_count(
            api.list_assessors(headers, {"qa_qualified": True}), 1
        )
        assert qualified[0]["id"] == reviewer["id"]


class TestEngagementSummaryProjection:
    """The consolidated roll-up is a flat projection with nothing behind it."""

    def test_the_roll_up_publishes_exactly_the_declared_positions(
        self, api, engagement_with_in_place_requirement
    ):
        """One request answers with the whole scope, fee, compliance and change position.

        PRD: A dedicated computed read assembles the engagement's whole position
        into a single flat payload: `engagement_id`, `posture`,
        `cde_component_count`, `connected_component_count`,
        `out_of_scope_component_count`, `total_component_count`, `open_gap_count`,
        `unvalidated_segment_count`, `accepted_ccw_count`, `estimated_hours`,
        `assessment_fee_total`, `as_found_compliance_percentage`,
        `as_attested_compliance_percentage`, `quarterly_scan_compliant`,
        `scope_affecting_change_count` and `reassessment_required`.

        Design: Corner/endpoints/endpoint_engagement_summary_is_a_side_effect_free_projection
        """
        scenario = engagement_with_in_place_requirement
        _record_five_changes(api, scenario)

        summary = validate_success(
            api.get_engagement_summary(scenario["engagement_id"], client_rep_headers())
        )

        assert_keys_exactly(summary, SUMMARY_KEYS)
        assert summary["engagement_id"] == scenario["engagement_id"]
        assert summary["posture"] == "OPEN"
        assert summary["cde_component_count"] == 3
        assert summary["connected_component_count"] == 0
        assert summary["out_of_scope_component_count"] == 0
        assert summary["total_component_count"] == 3
        assert summary["open_gap_count"] == 0
        assert summary["unvalidated_segment_count"] == 0
        assert summary["accepted_ccw_count"] == 0
        # Three sampled hosts at one data centre price the 226-hour example.
        assert summary["estimated_hours"] == 226
        assert_money(summary["assessment_fee_total"], 59189.40)
        assert_percentage(summary["as_found_compliance_percentage"], 100.00)
        assert_percentage(summary["as_attested_compliance_percentage"], 100.00)
        # No quarterly scan has ever been scheduled on this engagement.
        assert summary["quarterly_scan_compliant"] is False
        # The patched application and the host marked as not affecting scope
        # are logged but neither of them counts.
        assert summary["scope_affecting_change_count"] == 3
        assert summary["reassessment_required"] is True

    def test_reading_the_roll_up_twice_changes_nothing_at_all(
        self, api, engagement_with_in_place_requirement
    ):
        """Two readers on two different roles get the same numbers and leave no trace.

        PRD: Every one of those numbers is derived on read from the engagement's
        children, never stored by a caller.

        Design: Corner/endpoints/endpoint_engagement_summary_is_a_side_effect_free_projection
        """
        scenario = engagement_with_in_place_requirement
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        _record_five_changes(api, scenario)
        vendor = register_vendor(api)
        before = read_engagement(api, engagement_id, lead_id)

        first = validate_success(
            api.get_engagement_summary(engagement_id, client_rep_headers())
        )
        second = validate_success(
            api.get_engagement_summary(
                engagement_id, make_asv_vendor_headers(vendor["id"])
            )
        )

        # The roll-up carries no ownership gate, so unrelated readers agree.
        assert first == second
        after = read_engagement(api, engagement_id, lead_id)
        assert_version_unchanged(before["version"], after["version"])
        assert after["updated_at"] == before["updated_at"]

        # The projection restates the engagement's own derived positions.
        shared = [key for key in SUMMARY_KEYS if key in after]
        assert "posture" in shared and "assessment_fee_total" in shared
        for key in shared:
            assert first[key] == after[key], (
                "the roll-up disagrees with the engagement on %s: %r versus %r"
                % (key, first[key], after[key])
            )
        assert first["engagement_id"] == after["id"]


class TestLogicalClockReprojection:
    """Moving the clock re-derives every position that reads it."""

    def test_advancing_past_the_scan_window_drops_scan_compliance(self, api):
        """The passing quarter stops covering the engagement once the clock leaves it.

        PRD: An engagement's `quarterly_scan_compliant` flag and its
        `reassessment_required` flag are likewise recomputed against the current
        clock instant.

        Design: Corner/endpoints/endpoint_clock_action_reprojects_certification_and_scan_compliance
        """
        scenario = _passing_cycle_scenario(api)
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        cycle = scenario["cycle"]
        assert cycle["status"] == "PASSING"
        assert cycle["attestation_of_scan_compliance"] is True
        assert_same_instant(cycle["window_end"], Q3_WINDOW_END)
        before = read_engagement(api, engagement_id, lead_id)
        assert before["quarterly_scan_compliant"] is True

        moved = set_clock(api, AFTER_Q3_WINDOW)

        assert_same_instant(moved["current_utc"], AFTER_Q3_WINDOW)
        after = read_engagement(api, engagement_id, lead_id)
        # October stands outside the quarter's half-open window.
        assert after["quarterly_scan_compliant"] is False
        # Moving the clock persists nothing, so no version anywhere advances.
        assert_version_unchanged(before["version"], after["version"])
        held = validate_success(
            api.get_scan_cycle(scenario["cycle_id"], make_lead_headers(lead_id))
        )
        assert held["status"] == "PASSING"
        assert held["effective_high_finding_count"] == 0
        assert_same_instant(held["window_start"], Q3_WINDOW_START)
        assert_same_instant(held["window_end"], Q3_WINDOW_END)
        assert held["version"] == cycle["version"]
        summary = validate_success(
            api.get_engagement_summary(engagement_id, client_rep_headers())
        )
        assert summary["quarterly_scan_compliant"] is False
        assert summary["posture"] == before["posture"]

    def test_advancing_past_a_certificate_lapses_it_while_the_vendor_survives(self, api):
        """One clock move lapses both assessors and leaves the vendor approved.

        PRD: An assessor's `certification_status` is `ACTIVE` while the clock is
        strictly earlier than that assessor's `certification_expires_at`, and
        `LAPSED` from that instant onward.

        Design: Corner/endpoints/endpoint_clock_action_reprojects_certification_and_scan_compliance
        """
        scenario = _passing_cycle_scenario(api)
        headers = admin_headers()
        lead_before = validate_success(api.get_assessor(scenario["lead_id"], headers))
        assert lead_before["certification_status"] == "ACTIVE"

        first = set_clock(api, AFTER_Q3_WINDOW)
        second = set_clock(api, AFTER_LEAD_CERTIFICATION)

        assert_same_instant(first["current_utc"], AFTER_Q3_WINDOW)
        assert_same_instant(second["current_utc"], AFTER_LEAD_CERTIFICATION)
        lead = validate_success(api.get_assessor(scenario["lead_id"], headers))
        assert lead["certification_status"] == "LAPSED"
        # The administrative standing is a separate field and never moved.
        assert lead["status"] == "ACTIVE"
        assert lead["version"] == lead_before["version"]
        reviewer = validate_success(api.get_assessor(scenario["qa_id"], headers))
        assert reviewer["certification_status"] == "LAPSED"
        # The scanning vendor's approval runs to the end of 2027 and stands.
        vendor = validate_success(api.get_asv_vendor(scenario["vendor_id"], headers))
        assert vendor["effective_approval"] == "APPROVED"
        assert vendor["approval_status"] == "APPROVED"

        assert_total_count(
            api.list_assessors(headers, {"certification_status": "LAPSED"}), 2
        )
        assert_total_count(
            api.list_assessors(headers, {"certification_status": "ACTIVE"}), 0
        )
        assert_total_count(
            api.list_asv_vendors(headers, {"effective_approval": "APPROVED"}), 1
        )


def _engagement_without_a_reviewer(api) -> Scenario:
    """Open an engagement with no reviewer named and two qualified candidates."""
    scenario = build_registry(api)
    second_reviewer = register_assessor(
        api, "Lena Ortiz", "lena.ortiz@qsa.example", qa_qualified=True
    )
    scenario["second_reviewer"] = second_reviewer
    scenario["second_reviewer_id"] = second_reviewer["id"]
    engagement = open_engagement(api, scenario["lead_id"])
    scenario["engagement"] = engagement
    scenario["engagement_id"] = engagement["id"]
    return scenario


class TestQaReviewerNominationLink:
    """Nominating a reviewer links two existing rows and replaces the old link."""

    def test_a_second_nomination_replaces_the_first_reviewer(self, api):
        """The link is overwritten, not appended, and each nomination costs one version.

        PRD: Nominating the quality-assurance reviewer after the fact is a lead-only
        operation carrying just `qa_reviewer_id`; it runs the segregation-of-duties,
        qualification, active-status and certification checks in ladder order and
        advances the engagement's `version` by 1.

        Design: Corner/endpoints/endpoint_qa_reviewer_link_is_a_replaceable_cross_reference
        """
        scenario = _engagement_without_a_reviewer(api)
        engagement = scenario["engagement"]
        lead_headers = make_lead_headers(scenario["lead_id"])
        assert engagement["qa_reviewer_id"] is None

        first = validate_success(
            api.assign_qa_reviewer(
                engagement["id"], scenario["qa_id"], lead_headers
            )
        )
        second = validate_success(
            api.assign_qa_reviewer(
                engagement["id"], scenario["second_reviewer_id"], lead_headers
            )
        )

        assert first["qa_reviewer_id"] == scenario["qa_id"]
        assert_version_bumped_by(engagement["version"], first["version"])
        assert second["id"] == engagement["id"]
        assert second["qa_reviewer_id"] == scenario["second_reviewer_id"]
        assert_version_bumped_by(first["version"], second["version"])
        # The nomination links people; it is not a step in the engagement's life.
        assert second["status"] == "SCOPING"
        assert second["posture"] == "OPEN"
        assert second["lead_assessor_id"] == scenario["lead_id"]
        # Nothing was minted anywhere: the roster still holds its three people.
        assert_total_count(api.list_assessors(admin_headers()), 3)

    def test_the_reviewer_filter_follows_the_link_to_its_new_owner(self, api):
        """Listing by reviewer finds the engagement only under the current nominee.

        PRD: Engagements can be read one at a time — the payload carries `posture`,
        every scope and gap count, the fee figures and both compliance percentages —
        or listed with filters on `status`, `posture`, `lead_assessor_id`,
        `qa_reviewer_id`, `merchant_level` and `assessment_year`.

        Design: Corner/endpoints/endpoint_qa_reviewer_link_is_a_replaceable_cross_reference
        """
        scenario = _engagement_without_a_reviewer(api)
        engagement_id = scenario["engagement_id"]
        lead_headers = make_lead_headers(scenario["lead_id"])
        first_reviewer_id = scenario["qa_id"]
        second_reviewer_id = scenario["second_reviewer_id"]
        assert_total_count(
            api.list_engagements(lead_headers, {"qa_reviewer_id": first_reviewer_id}), 0
        )

        validate_success(
            api.assign_qa_reviewer(engagement_id, first_reviewer_id, lead_headers)
        )
        under_first = assert_total_count(
            api.list_engagements(lead_headers, {"qa_reviewer_id": first_reviewer_id}), 1
        )
        assert under_first[0]["id"] == engagement_id

        validate_success(
            api.assign_qa_reviewer(engagement_id, second_reviewer_id, lead_headers)
        )

        under_second = assert_total_count(
            api.list_engagements(lead_headers, {"qa_reviewer_id": second_reviewer_id}), 1
        )
        assert under_second[0]["id"] == engagement_id
        assert under_second[0]["qa_reviewer_id"] == second_reviewer_id
        # The replaced reviewer no longer reaches the engagement at all.
        assert_total_count(
            api.list_engagements(lead_headers, {"qa_reviewer_id": first_reviewer_id}), 0
        )
        # The lead's own link is untouched by the reviewer swap.
        under_lead = assert_total_count(
            api.list_engagements(
                lead_headers, {"lead_assessor_id": scenario["lead_id"]}
            ),
            1,
        )
        assert under_lead[0]["id"] == engagement_id
