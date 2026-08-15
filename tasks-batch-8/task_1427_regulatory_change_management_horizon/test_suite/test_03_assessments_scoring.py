"""Impact assessments: assignment, scoring, revision loop, accept cascade."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    create_assessment,
    create_business_owner,
    create_change,
    create_triaged_change,
    get_owner,
    list_gaps_for_assessment,
    make_business_owner_headers,
    make_manager_headers,
    make_officer_headers,
    setup_accepted_assessment,
    start_assessment,
    submit_assessment,
    create_obligation,
    validate_error,
    validate_paginated,
    validate_success,
    MANAGER_1,
    OFFICER_A,
    OFFICER_B,
    api_client,
    get_change,
)


def _in_progress_assessment(citation, **kwargs):
    """Owner + triaged change + assessment in IN_PROGRESS. Returns (owner, change, assessment)."""
    owner = create_business_owner()
    change = create_triaged_change(citation=citation, **kwargs)
    assessment = create_assessment(change, owner["id"])
    start_assessment(assessment["id"], owner["id"])
    return owner, change, assessment


class TestAssessmentStates:
    def test_submit_before_start_rejected(self, api):
        """PRD §3.4: "Submitting is allowed only from `IN_PROGRESS` and carries the
        analytical payload: `likelihood_score` and `severity_score`, each an
        integer from 1 to 5; `affected_business_lines`, an integer of at least 1;
        and a free-text `findings_summary`."
        PRD §3.4: "Both `impact_rating_raw` and `impact_tier`, unset until this
        moment, are stored".

        Design: Corner/state_machines/sm_assessment_submit_before_start_rejected
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="SM-2")
        assessment = create_assessment(change, owner["id"])
        resp = api.submit_impact_assessment(
            assessment["id"],
            {"likelihood_score": 2, "severity_score": 2, "affected_business_lines": 1, "findings_summary": "f"},
            make_business_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_impact_assessment(assessment["id"], make_officer_headers(OFFICER_A)))
        assert data["status"] == "ASSIGNED"
        assert data["impact_rating_raw"] is None

    def test_return_cycle_counts(self, api, manager_1_headers):
        """PRD §3.4: "Returning it (`SUBMITTED` → `RETURNED`) carries `comments`
        for the owner and increments `return_count`, feeding the revision loop
        that re-enters `IN_PROGRESS` through the start transition."

        Design: Corner/state_machines/sm_assessment_return_cycle_counts
        """
        owner, _change, assessment = _in_progress_assessment("SM-4")
        submit_assessment(assessment["id"], owner["id"], likelihood_score=2, severity_score=2)
        resp = api.return_impact_assessment(
            assessment["id"], {"comments": "Expand scope analysis"}, manager_1_headers
        )
        returned = validate_success(resp, 200)
        assert returned["status"] == "RETURNED"
        assert returned["return_count"] == 1

        restarted = start_assessment(assessment["id"], owner["id"])
        assert restarted["status"] == "IN_PROGRESS"
        resubmitted = submit_assessment(assessment["id"], owner["id"], likelihood_score=3, severity_score=2)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["impact_rating_raw"] == 6.0, "3 x 2 x 1.0 = 6.0"


class TestConfirmedImpactRating:
    def test_scope_multiplier_step_flips_tier(self, api):
        """PRD §3.4: "the raw score is `likelihood_score` times `severity_score`
        times a scope multiplier that is 1.0 when exactly one business line is
        affected, 1.2 when two or three are affected, and 1.5 when four or more
        are affected".
        PRD §3.4: "The `impact_tier` follows the same bands as the provisional
        rating — below 5 is `LOW`, at least 5 but below 12 is `MEDIUM`, at least
        12 but below 20 is `HIGH`, and 20 or more is `CRITICAL`."

        Design: Difficulty/combinatorial_formula/cf_impact_rating_scope_multiplier_tiers
        """
        _owner_a, _ch_a, ia_a = _in_progress_assessment("CF-A", severity_hint="LOW")
        one_line = submit_assessment(
            ia_a["id"], ia_a["business_owner_id"], likelihood_score=4, severity_score=4, affected_business_lines=1
        )
        assert one_line["impact_rating_raw"] == 16.0, "4 x 4 x 1.0 = 16.0"
        assert one_line["impact_tier"] == "HIGH"

        _owner_b, _ch_b, ia_b = _in_progress_assessment("CF-B", severity_hint="LOW")
        four_lines = submit_assessment(
            ia_b["id"], ia_b["business_owner_id"], likelihood_score=4, severity_score=4, affected_business_lines=4
        )
        assert four_lines["impact_rating_raw"] == 24.0, "4 x 4 x 1.5 = 24.0"
        assert four_lines["impact_tier"] == "CRITICAL", "Multiplier step flips tier at identical scores"

    def test_raw_five_is_medium_boundary(self, api):
        """PRD §3.4: "The `impact_tier` follows the same bands as the provisional
        rating — below 5 is `LOW`, at least 5 but below 12 is `MEDIUM`, at least
        12 but below 20 is `HIGH`, and 20 or more is `CRITICAL`."

        Design: Difficulty/combinatorial_formula/cf_impact_rating_scope_multiplier_tiers
        """
        _owner, _ch, ia = _in_progress_assessment("CF-C", severity_hint="LOW")
        boundary = submit_assessment(
            ia["id"], ia["business_owner_id"], likelihood_score=1, severity_score=5, affected_business_lines=1
        )
        assert boundary["impact_rating_raw"] == 5.0, "1 x 5 x 1.0 = 5.0"
        assert boundary["impact_tier"] == "MEDIUM", "raw == 5.0 is inclusive of MEDIUM"


class TestProvisionalVsConfirmed:
    def test_provisional_tier_pinned_at_triage(self, api):
        """PRD §3.1: "The provisional rating maps the analyst's `severity_hint` to
        a severity score — `LOW` counts 1, `MEDIUM` counts 2, `HIGH` counts 4,
        `CRITICAL` counts 5 — multiplies that score by an assumed likelihood of 3
        and a scope multiplier fixed at 1.0, and tiers the resulting raw product
        as follows: below 5 is `LOW`, at least 5 but below 12 is `MEDIUM`, at
        least 12 but below 20 is `HIGH`, and 20 or more is `CRITICAL`."
        PRD §3.4: "On submit, the confirmed impact rating is computed: the raw
        score is `likelihood_score` times `severity_score` times a scope
        multiplier that is 1.0 when exactly one business line is affected".

        Design: Difficulty/dual_variant_calc/dvc_impact_rating_provisional_vs_confirmed
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="DVC-1", severity_hint="HIGH")
        assert change["provisional_risk_tier"] == "HIGH", "provisional: 4 x 3 x 1.0 = 12.0 -> HIGH"
        assessment = create_assessment(change, owner["id"])
        start_assessment(assessment["id"], owner["id"])
        submitted = submit_assessment(
            assessment["id"], owner["id"],
            likelihood_score=2, severity_score=3, affected_business_lines=1,
            findings_summary="Limited to one product line",
        )
        assert submitted["impact_rating_raw"] == 6.0, "confirmed: 2 x 3 x 1.0"
        assert submitted["impact_tier"] == "MEDIUM"

    def test_accept_stamps_confirmed_tier_diverging_from_provisional(self, api, manager_1_headers):
        """PRD §3.4: "First, the change's `risk_tier` is set to the assessment's
        `impact_tier`, advancing the change's `version`."

        Design: Difficulty/dual_variant_calc/dvc_impact_rating_provisional_vs_confirmed
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="DVC-1B", severity_hint="HIGH")
        assert change["provisional_risk_tier"] == "HIGH"
        assessment = create_assessment(change, owner["id"])
        start_assessment(assessment["id"], owner["id"])
        submit_assessment(
            assessment["id"], owner["id"], likelihood_score=2, severity_score=3, affected_business_lines=1
        )
        # Pin AFTER assignment: PRD §3.4 advances the change's version once at
        # assignment ("The change's `business_owner_id` is updated to the new
        # assignee and the change's `version` advances by one").
        pre_accept_version = get_change(change["id"])["version"]
        accept_assessment(assessment["id"])
        final = get_change(change["id"])
        assert final["risk_tier"] == "MEDIUM", "Confirmed tier replaces the provisional view"
        assert final["provisional_risk_tier"] == "HIGH", "Provisional tier stays pinned at triage"
        assert final["version"] == pre_accept_version + 1, "Accept advances the change's version"


class TestAcceptCascade:
    def test_accept_creates_gap_per_active_obligation(self, api, officer_a_headers):
        """PRD §3.4: "Second, for every `ACTIVE` obligation introduced by the
        change, a gap analysis is created in `OPEN` with its `requirement_points`
        snapshotted from the obligation's `criticality` as described in §3.5.
        Third, each newly created gap analysis immediately computes its
        `covered_points` and `residual_gap_points`, and any new gap whose residual
        equals its full requirement — zero effective coverage — on an obligation
        of `HIGH` or `CRITICAL` criticality spawns an escalation with
        `target_type` `OBLIGATION`, `trigger_rule` `ZERO_COVERAGE`, no business
        owner attached, and status `OPEN`."
        PRD §3.5: "`LOW` weighs 4 points, `MEDIUM` 8, `HIGH` 16, and `CRITICAL` 32".

        Design: Corner/endpoints/ep_accept_creates_gap_per_active_obligation
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="EP-1", severity_hint="HIGH")
        obl_h = create_obligation(change["id"], obligation_code="OBL-EP-1H", criticality="HIGH")
        obl_l = create_obligation(change["id"], obligation_code="OBL-EP-1L", criticality="LOW")
        create_obligation(change["id"], obligation_code="OBL-EP-1D", criticality="MEDIUM", activate=False)

        assessment = create_assessment(change, owner["id"])
        start_assessment(assessment["id"], owner["id"])
        submit_assessment(assessment["id"], owner["id"], likelihood_score=3, severity_score=3)
        accept_assessment(assessment["id"])

        gaps = list_gaps_for_assessment(assessment["id"])
        assert len(gaps) == 2, f"Exactly one gap per ACTIVE obligation; got {len(gaps)}"
        by_obligation = {g["obligation_id"]: g for g in gaps}
        assert set(by_obligation) == {obl_h["id"], obl_l["id"]}, "DRAFT obligation gets no gap"
        assert by_obligation[obl_h["id"]]["status"] == "OPEN"
        assert by_obligation[obl_l["id"]]["status"] == "OPEN"
        assert by_obligation[obl_h["id"]]["requirement_points"] == 16
        assert by_obligation[obl_l["id"]]["requirement_points"] == 4

        esc_h, _meta_h = validate_paginated(
            api.list_escalations(officer_a_headers, params={"target_id": obl_h["id"]})
        )
        assert len(esc_h) == 1
        assert esc_h[0]["trigger_rule"] == "ZERO_COVERAGE"
        assert esc_h[0]["target_type"] == "OBLIGATION"
        assert esc_h[0]["business_owner_id"] is None
        assert esc_h[0]["status"] == "OPEN"
        _esc_l, meta_l = validate_paginated(
            api.list_escalations(officer_a_headers, params={"target_id": obl_l["id"]})
        )
        assert meta_l["total_count"] == 0, "LOW zero-coverage gap spawns no escalation"


class TestOwnerCounters:
    def test_active_assessment_count_tracks_terminal_transition(self, api, officer_a_headers):
        """PRD §3.4: "`active_assessment_count`, the number of their assessments
        standing in `ASSIGNED`, `IN_PROGRESS`, `RETURNED`, or `SUBMITTED`".

        Design: Corner/entities/entity_owner_computed_assessment_count
        """
        owner, _change, assessment = _in_progress_assessment("CC-1")
        submit_assessment(assessment["id"], owner["id"], likelihood_score=2, severity_score=2)
        mid = get_owner(owner["id"])
        assert mid["active_assessment_count"] == 1, "SUBMITTED is non-terminal"
        accept_assessment(assessment["id"])
        after = get_owner(owner["id"])
        assert after["active_assessment_count"] == 0, "ACCEPTED is terminal"


class TestAssessmentGates:
    def test_due_date_in_past_rejected(self, api, officer_a_headers):
        """PRD §3.4: "a `due_date` lying strictly after the current logical clock
        (`ERR_DEADLINE_IN_PAST`)".

        Design: Corner/validations/val_assessment_due_date_in_past_rejected
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="VD-1")
        resp = api.create_impact_assessment(
            {
                "regulatory_change_id": change["id"],
                "business_owner_id": owner["id"],
                "due_date": "2026-07-01T00:00:00Z",
                "expected_regulatory_change_version": change["version"],
            },
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_IN_PAST)

    def test_create_on_non_applicable_change_rejected(self, api, officer_a_headers):
        """PRD §3.2: "The referenced change must be `TRIAGED_APPLICABLE`, or
        creation fails with `ERR_CHANGE_NOT_TRIAGED_APPLICABLE`".
        PRD §3.4: "The referenced change must indeed be `TRIAGED_APPLICABLE`
        (`ERR_CHANGE_NOT_TRIAGED_APPLICABLE`)".

        Design: Corner/errors/err_change_not_triaged_applicable
        """
        owner = create_business_owner()
        change = create_change(citation="NT-1")
        resp = api.create_obligation(
            {
                "obligation_code": "OBL-NT-1",
                "title": "Obl",
                "regulatory_change_id": change["id"],
                "criticality": "LOW",
            },
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGE_NOT_TRIAGED_APPLICABLE)
        resp = api.create_impact_assessment(
            {
                "regulatory_change_id": change["id"],
                "business_owner_id": owner["id"],
                "due_date": "2026-08-10T00:00:00Z",
                "expected_regulatory_change_version": change["version"],
            },
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGE_NOT_TRIAGED_APPLICABLE)

    def test_start_by_other_owner_rejected(self, api):
        """PRD §2.1: "ownership checks on any resource that references a
        BusinessOwner compare the resource's `business_owner_id` field to
        `X-User-ID`, and a mismatch on an owner-scoped action is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §3.4: "Starting it (`ASSIGNED` → `IN_PROGRESS`) — or resuming it after
        a return (`RETURNED` → `IN_PROGRESS`) — requires the caller to be the
        assigned owner (`ERR_NOT_RESOURCE_OWNER`)".

        Design: Corner/errors/err_not_resource_owner_on_start
        """
        owner_a = create_business_owner(name="Owner A", email="a@x.com")
        owner_b = create_business_owner(name="Owner B", email="b@x.com")
        change = create_triaged_change(citation="OW-1")
        assessment = create_assessment(change, owner_a["id"])
        resp = api.start_impact_assessment(assessment["id"], make_business_owner_headers(owner_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        data = validate_success(api.get_impact_assessment(assessment["id"], make_officer_headers(OFFICER_A)))
        assert data["status"] == "ASSIGNED"
