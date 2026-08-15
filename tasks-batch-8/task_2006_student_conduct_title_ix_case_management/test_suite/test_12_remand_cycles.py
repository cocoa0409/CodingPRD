"""Remand cycles: case loop closure, packet/item cascades, sanction conservation."""
from test_helpers import (
    ApiErrorId,
    assign_active_investigator,
    create_case,
    create_determination_draft,
    create_packet,
    drive_case_to_remanded,
    drive_round_two_to_deliberation,
    get_case,
    issue_determination,
    make_cast,
    make_coordinator_headers,
    resume_case,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def _remanded_case_with_pinned_item(cast):
    """SEXUAL_ASSAULT case: ISSUED (SUSPENSION 120d, score 50 TIER_3), one
    ACCEPTED pinned evidence item, then appeal decided REMANDED/INVESTIGATION."""
    case = create_case(cast, categories=["SEXUAL_ASSAULT"])
    stage = drive_case_to_remanded(case["id"], cast, with_evidence=True)
    return case, stage


class TestRemandReopensInvestigation:
    def test_case_remand_cycle_reopens_investigation(self, api):
        """PRD 3.6: "A `REMANDED` case resumes by coordinator action, and the
        destination is whatever the remanding appeal recorded in `remand_target`
        — a resumption inconsistent with it is `ERR_REMAND_SCOPE_MISMATCH`.
        Resuming into `INVESTIGATION` reopens the evidence base: the case's most
        recent `FINALIZED` packet moves to `SUPERSEDED` (appending
        `PACKET_SUPERSEDED`), each of that packet's pinned `ACCEPTED` evidence
        items returns to `UNDER_REVIEW` (one `EVIDENCE_REVIEW_STARTED` per item),
        `CASE_RESUMED` is appended, and the case `version` increments."
        PRD 3.3: "Creation lands in `DRAFT`, assigns the 1-based
        `packet_sequence` in creation order across the case".

        Design: Difficulty/non_linear_state_machine/case_remand_cycle_reopens_investigation
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "ao", "advc", "advr")
        case, stage = _remanded_case_with_pinned_item(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        remanded = get_case(case["id"], cast["coord"]["id"])
        assert remanded["status"] == "REMANDED"
        assert remanded["remand_target"] == "INVESTIGATION"

        resumed = resume_case(case["id"], cast["coord"]["id"])
        assert resumed["status"] == "INVESTIGATION", (
            "the cycle closes back to a working state"
        )

        # The cycled case accepts fresh investigation work.
        assign_active_investigator(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        packet2 = create_packet(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        assert packet2["status"] == "DRAFT"
        assert packet2["packet_sequence"] == 2, "1-based sequence in creation order"

    def test_remand_resume_supersedes_packet_and_unpins_items(self, api):
        """PRD 3.6: "Resuming into `INVESTIGATION` reopens the evidence base: the
        case's most recent `FINALIZED` packet moves to `SUPERSEDED` (appending
        `PACKET_SUPERSEDED`), each of that packet's pinned `ACCEPTED` evidence
        items returns to `UNDER_REVIEW` (one `EVIDENCE_REVIEW_STARTED` per
        item)".
        PRD 3.6: "The determination moves `ISSUED → SUPERSEDED`, its `ACTIVE`
        sanctions move to `STAYED`, and the case leaves `APPEAL_REVIEW` for
        `REMANDED` with its `remand_target` set to the appeal's `remand_scope`".

        Design: Difficulty/non_linear_state_machine/case_remand_cycle_reopens_investigation
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "ao", "advc", "advr")
        case, stage = _remanded_case_with_pinned_item(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        det_after = validate_success(api.get_determination(stage["determination"]["id"], coord_h))
        assert det_after["status"] == "SUPERSEDED"

        resume_case(case["id"], cast["coord"]["id"])
        packet_after = validate_success(api.get_evidence_packet(stage["packet"]["id"], coord_h))
        assert packet_after["status"] == "SUPERSEDED"
        item_after = validate_success(api.get_evidence_item(stage["item"]["id"], coord_h))
        assert item_after["status"] == "UNDER_REVIEW", (
            "the pinned ACCEPTED ruling is undone by the supersession"
        )


class TestRemandCascadeHops:
    def test_appeal_remand_cascade_decide_then_resume_hops(self, api):
        """PRD 3.6: "The determination moves `ISSUED → SUPERSEDED`, its `ACTIVE`
        sanctions move to `STAYED`, and the case leaves `APPEAL_REVIEW` for
        `REMANDED` with its `remand_target` set to the appeal's `remand_scope`;
        `APPEAL_DECIDED` is appended."
        PRD 3.6: "Resuming into `INVESTIGATION` reopens the evidence base: the
        case's most recent `FINALIZED` packet moves to `SUPERSEDED` (appending
        `PACKET_SUPERSEDED`), each of that packet's pinned `ACCEPTED` evidence
        items returns to `UNDER_REVIEW` (one `EVIDENCE_REVIEW_STARTED` per item),
        `CASE_RESUMED` is appended, and the case `version` increments."

        Design: Difficulty/transitive_cascade/appeal_remand_packet_supersede_item_rereview_cascade
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "ao", "advc", "advr")
        case, stage = _remanded_case_with_pinned_item(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        # Hop 1 (decide): case -> REMANDED, determination -> SUPERSEDED,
        # sanction -> STAYED.
        case_after_decide = get_case(case["id"], cast["coord"]["id"])
        assert case_after_decide["status"] == "REMANDED"
        assert case_after_decide["remand_target"] == "INVESTIGATION"
        det = validate_success(api.get_determination(stage["determination"]["id"], coord_h))
        assert det["status"] == "SUPERSEDED"
        sanctions, _ = validate_paginated(
            api.list_determination_sanctions(det["id"], coord_h)
        )
        assert len(sanctions) == 1 and sanctions[0]["status"] == "STAYED"

        # Hop 2 (resume, enabled by REMANDED): case -> INVESTIGATION,
        # packet -> SUPERSEDED.
        resumed = resume_case(case["id"], cast["coord"]["id"])
        assert resumed["status"] == "INVESTIGATION"
        packet = validate_success(api.get_evidence_packet(stage["packet"]["id"], coord_h))
        assert packet["status"] == "SUPERSEDED"

        # Hop 3 (packet supersession): pinned item ACCEPTED -> UNDER_REVIEW.
        item = validate_success(api.get_evidence_item(stage["item"]["id"], coord_h))
        assert item["status"] == "UNDER_REVIEW"

    def test_appeal_remand_stays_sanction_and_supersedes_determination(self, api):
        """PRD 3.6: "The determination moves `ISSUED → SUPERSEDED`, its `ACTIVE`
        sanctions move to `STAYED`, and the case leaves `APPEAL_REVIEW` for
        `REMANDED` with its `remand_target` set to the appeal's `remand_scope`".

        Design: Difficulty/transitive_cascade/appeal_remand_packet_supersede_item_rereview_cascade
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "ao", "advc", "advr")
        case, stage = _remanded_case_with_pinned_item(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        # Immediately after the decide (before any resume), the compensating
        # state changes are already visible.
        det = validate_success(api.get_determination(stage["determination"]["id"], coord_h))
        assert det["status"] == "SUPERSEDED"
        sanctions, _ = validate_paginated(
            api.list_determination_sanctions(det["id"], coord_h)
        )
        assert sanctions[0]["sanction_type"] == "SUSPENSION"
        assert sanctions[0]["status"] == "STAYED"
        assert sanctions[0]["duration_days"] == 120
        case_now = get_case(case["id"], cast["coord"]["id"])
        assert case_now["status"] == "REMANDED"


class TestSuspensionDaysConservation:
    def _two_round_suspension(self, cast):
        """Round 1: ISSUED SUSPENSION 120d. Appeal REMANDED/INVESTIGATION, resume.
        Round 2: fresh investigation/hearing, ISSUED SUSPENSION 120d again."""
        case = create_case(cast, categories=["SEXUAL_ASSAULT"])
        stage1 = drive_case_to_remanded(case["id"], cast)
        resume_case(case["id"], cast["coord"]["id"])
        stage2 = drive_round_two_to_deliberation(case["id"], cast)
        det2 = create_determination_draft(
            case["id"], cast["coord"]["id"], cast["dm"]["id"],
            aggravating_factor_count=1, mitigating_factor_count=0,
            prior_responsible_findings=0, rationale="Round two",
        )
        det2 = issue_determination(
            det2["id"], cast["dm"]["id"],
            [{"sanction_type": "SUSPENSION", "duration_days": 120}],
        )
        return case, stage1, det2

    def test_suspension_days_not_doubled_across_remand(self, api):
        """PRD 3.6: "The determination moves `ISSUED → SUPERSEDED`, its `ACTIVE`
        sanctions move to `STAYED`, and the case leaves `APPEAL_REVIEW` for
        `REMANDED` with its `remand_target` set to the appeal's `remand_scope`;
        `APPEAL_DECIDED` is appended."

        Design: Difficulty/compensating_invariant/suspension_days_not_doubled_across_remand
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "ao", "advc", "advr")
        case, stage1, det2 = self._two_round_suspension(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        det1 = stage1["determination"]

        sanctions1, _ = validate_paginated(api.list_determination_sanctions(det1["id"], coord_h))
        assert len(sanctions1) == 1
        assert sanctions1[0]["status"] == "STAYED"
        assert sanctions1[0]["duration_days"] == 120, (
            "the stayed sanction contributes 0 ACTIVE days after the remand compensation"
        )

        sanctions2, _ = validate_paginated(api.list_determination_sanctions(det2["id"], coord_h))
        assert len(sanctions2) == 1
        assert sanctions2[0]["status"] == "ACTIVE"
        assert sanctions2[0]["duration_days"] == 120

        # Conserved quantity: ACTIVE suspension days total 120, not 240.
        active_days = sum(
            s["duration_days"]
            for s in list(sanctions1) + list(sanctions2)
            if s["status"] == "ACTIVE" and s["sanction_type"] == "SUSPENSION"
        )
        assert active_days == 120, (
            "impose(120) + compensating stay(-120) + re-impose(120) conserves the total"
        )

    def test_remand_lineage_determination_statuses(self, api):
        """PRD 3.5: "On a `REMANDED` case, the new draft legitimately continues
        the lineage whose prior determinations the remand already superseded
        (§3.6)."
        PRD 3.6: "The determination moves `ISSUED → SUPERSEDED`, its `ACTIVE`
        sanctions move to `STAYED`".

        Design: Difficulty/compensating_invariant/suspension_days_not_doubled_across_remand
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "ao", "advc", "advr")
        case, stage1, det2 = self._two_round_suspension(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        det1_after = validate_success(
            api.get_determination(stage1["determination"]["id"], coord_h)
        )
        assert det1_after["status"] == "SUPERSEDED"
        det2_after = validate_success(api.get_determination(det2["id"], coord_h))
        assert det2_after["status"] == "ISSUED"

        # The remand lineage is visible on the case's determination list.
        dets, meta = validate_paginated(api.list_case_determinations(case["id"], coord_h))
        statuses = {d["id"]: d["status"] for d in dets}
        assert statuses[stage1["determination"]["id"]] == "SUPERSEDED"
        assert statuses[det2["id"]] == "ISSUED"
