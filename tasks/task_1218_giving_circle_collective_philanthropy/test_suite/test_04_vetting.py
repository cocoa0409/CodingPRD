"""Nomination and vetting: profile-weighted scoring, the information-request
loop, finalist gates, site-visit calendar semantics, and nomination uniqueness
(PRD §2.10, §3.4, §3.5).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_nonprofit,
    create_site_visit_payload,
    get_success_data,
    make_grantee_headers,
    make_member_headers,
    schedule_visit,
    set_clock,
    setup_nomination_in_vetting,
    setup_nomination_phase,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestVettingScoreProfiles:
    def test_balanced_profile_scores_69_and_fails_gate(self, api):
        """PRD §3.4: "Under `BALANCED`, the score is forty percent of
        `financial_health`, thirty percent of `mission_alignment`, and thirty
        percent of `org_capacity`."
        PRD §3.4: "the `vetting_score` must be at least 70, so a 69 fails with
        `ERR_VETTING_SCORE_BELOW_THRESHOLD`"

        Inputs 60/90/60 -> round_half_up(0.40*60 + 0.30*90 + 0.30*60) = 69.

        Design: Difficulty/dual_variant_calc/vetting_score_profile_changes_outcome
        """
        ctx = setup_nomination_in_vetting(
            "Circle Bal", vetting_profile="BALANCED", scores=(60, 90, 60), with_visit=True
        )
        nomination_id = ctx["nominations"][0]["id"]
        scored = ctx["scored_nomination"]
        assert scored["vetting_score"] == 69, (
            f"BALANCED weights on 60/90/60 must give 69, got {scored['vetting_score']}"
        )
        resp = api.advance_to_finalist(nomination_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VETTING_SCORE_BELOW_THRESHOLD)
        after = get_success_data(api.get_nomination(nomination_id, ADMIN))
        assert after["status"] == "VETTING"

    def test_equity_first_profile_scores_75_and_passes_gate(self, api):
        """PRD §3.4: "Under `EQUITY_FIRST`, the score is twenty-five percent of
        `financial_health`, fifty percent of `mission_alignment`, and
        twenty-five percent of `org_capacity` — the same inputs can therefore
        pass under one profile and fail under the other."

        Inputs 60/90/60 -> round_half_up(0.25*60 + 0.50*90 + 0.25*60) = 75 >= 70.

        Design: Difficulty/dual_variant_calc/vetting_score_profile_changes_outcome
        """
        ctx = setup_nomination_in_vetting(
            "Circle Eq", vetting_profile="EQUITY_FIRST", scores=(60, 90, 60), with_visit=True
        )
        nomination_id = ctx["nominations"][0]["id"]
        scored = ctx["scored_nomination"]
        assert scored["vetting_score"] == 75, (
            f"EQUITY_FIRST weights on 60/90/60 must give 75, got {scored['vetting_score']}"
        )
        finalist = validate_success(api.advance_to_finalist(nomination_id, ADMIN))
        assert finalist["status"] == "FINALIST"


class TestInfoRoundLoop:
    def test_info_round_loop_twice_succeeds(self, api):
        """PRD §3.4: "When the administration needs more from the grantee,
        requesting information moves `VETTING` → `NEEDS_INFO` and increments
        `info_rounds_used`, which starts at zero."
        PRD §3.4: "The grantee answers through a `GranteeContact` whose
        `X-User-ID` must equal the nomination's `nonprofit_id` (`ERR_FORBIDDEN`
        otherwise); submitting the requested information returns the nomination
        `NEEDS_INFO` → `VETTING`."

        Design: Difficulty/non_linear_state_machine/nomination_vetting_info_loop
        """
        ctx = setup_nomination_in_vetting("Circle NL1")
        nomination_id = ctx["nominations"][0]["id"]
        nonprofit_id = ctx["nonprofits"][0]["id"]

        first = validate_success(api.request_info(nomination_id, ADMIN))
        assert first["status"] == "NEEDS_INFO"
        assert first["info_rounds_used"] == 1
        back = validate_success(
            api.submit_info(nomination_id, make_grantee_headers(nonprofit_id))
        )
        assert back["status"] == "VETTING"

        second = validate_success(api.request_info(nomination_id, ADMIN))
        assert second["status"] == "NEEDS_INFO"
        assert second["info_rounds_used"] == 2
        back2 = validate_success(
            api.submit_info(nomination_id, make_grantee_headers(nonprofit_id))
        )
        assert back2["status"] == "VETTING"
        assert back2["info_rounds_used"] == 2

    def test_third_info_round_rejected(self, api):
        """PRD §3.4: "At most two information rounds exist per nomination: once
        `info_rounds_used` reaches two, a further request fails with
        `ERR_INFO_ROUND_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/nomination_vetting_info_loop
        """
        ctx = setup_nomination_in_vetting("Circle NL1B")
        nomination_id = ctx["nominations"][0]["id"]
        nonprofit_id = ctx["nonprofits"][0]["id"]
        for _ in range(2):
            validate_success(api.request_info(nomination_id, ADMIN))
            validate_success(
                api.submit_info(nomination_id, make_grantee_headers(nonprofit_id))
            )
        resp = api.request_info(nomination_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INFO_ROUND_EXHAUSTED)
        after = get_success_data(api.get_nomination(nomination_id, ADMIN))
        assert after["info_rounds_used"] == 2
        assert after["status"] == "VETTING"


class TestFinalistGate:
    def test_finalist_without_site_visit_rejected(self, api):
        """PRD §3.4: "at least one site visit of the nomination must have
        reached `COMPLETED`, failing with `ERR_SITE_VISIT_REQUIRED` otherwise."

        Design: Corner/state_machines/finalist_without_site_visit_rejected
        """
        # Passing score (80 >= 70) but no site visit exists.
        ctx = setup_nomination_in_vetting(
            "Circle SM3", scores=(80, 80, 80), with_visit=False
        )
        nomination_id = ctx["nominations"][0]["id"]
        resp = api.advance_to_finalist(nomination_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SITE_VISIT_REQUIRED)
        after = get_success_data(api.get_nomination(nomination_id, ADMIN))
        assert after["status"] == "VETTING"


class TestSiteVisitCalendar:
    def test_site_visit_adjacency_allowed(self, api):
        """PRD §2.10: "Site visits for the same nonprofit follow a half-open
        overlap rule: a new or rescheduled visit conflicts only with visits in
        `SCHEDULED` or `COMPLETED` whose intervals truly overlap it, and
        back-to-back adjacency — one visit's `ends_at` equal to another's
        `starts_at` — is allowed because the intervals are half-open."

        Design: Difficulty/resource_temporal_overlap/site_visit_halfopen_adjacency
        """
        ctx = setup_nomination_in_vetting("Circle TO1")
        nomination_id = ctx["nominations"][0]["id"]
        schedule_visit(nomination_id, "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
        adjacent = validate_success(
            api.create_site_visit(
                create_site_visit_payload(
                    nomination_id, "2026-06-10T11:00:00Z", "2026-06-10T12:00:00Z"
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert adjacent["status"] == "SCHEDULED", (
            "a visit starting exactly when another ends is allowed (half-open intervals)"
        )

    def test_site_visit_straddling_overlap_rejected(self, api):
        """PRD §2.10: "A conflict is rejected with `ERR_SITE_VISIT_OVERLAP`
        (HTTP 409), and the rule applies both when a visit is first scheduled
        and when it is rescheduled."

        Design: Difficulty/resource_temporal_overlap/site_visit_halfopen_adjacency
        """
        ctx = setup_nomination_in_vetting("Circle TO1B")
        nomination_id = ctx["nominations"][0]["id"]
        schedule_visit(nomination_id, "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
        validate_success(
            api.create_site_visit(
                create_site_visit_payload(
                    nomination_id, "2026-06-10T11:00:00Z", "2026-06-10T12:00:00Z"
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api.create_site_visit(
            create_site_visit_payload(
                nomination_id, "2026-06-10T10:30:00Z", "2026-06-10T11:30:00Z"
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_VISIT_OVERLAP)
        visits, meta = validate_paginated(
            api.list_site_visits(ADMIN, params={"nomination_id": nomination_id})
        )
        assert meta["total_count"] == 2, f"only the two non-overlapping visits persist, got {meta['total_count']}"

    def test_site_visit_auto_no_show_after_end(self, api):
        """PRD §3.5: "If the clock instead moves strictly past `ends_at` while
        the visit is still `SCHEDULED`, the visit flips automatically to
        `NO_SHOW`."
        PRD §2.4: "Every clock advance evaluates the time-driven transitions of
        §3: a grantee report whose `due_at` has passed while the report is
        still `DUE` flips to `OVERDUE` and fires the standing cascade of §3.8,
        and a site visit whose `ends_at` has passed while the visit is still
        `SCHEDULED` flips to `NO_SHOW` per §3.5."

        Design: Corner/state_machines/site_visit_auto_no_show_after_end
        """
        ctx = setup_nomination_in_vetting("Circle SM5")
        visit = schedule_visit(ctx["nominations"][0]["id"])
        set_clock("2026-06-12T00:00:00Z")
        after = get_success_data(api.get_site_visit(visit["id"], ADMIN))
        assert after["status"] == "NO_SHOW", (
            f"visit still SCHEDULED past ends_at must flip to NO_SHOW, got {after['status']}"
        )


class TestNominationOwnershipAndUniqueness:
    def test_grantee_cannot_submit_info_for_other_nonprofit(self, api):
        """PRD §3.4: "The grantee answers through a `GranteeContact` whose
        `X-User-ID` must equal the nomination's `nonprofit_id` (`ERR_FORBIDDEN`
        otherwise); submitting the requested information returns the nomination
        `NEEDS_INFO` → `VETTING`."

        Design: Corner/rbac/grantee_cannot_submit_info_for_other_nonprofit_forbidden
        """
        ctx = setup_nomination_in_vetting("Circle RB3")
        nomination_id = ctx["nominations"][0]["id"]
        validate_success(api.request_info(nomination_id, ADMIN))
        other = add_nonprofit(ctx, "NP Other")
        resp = api.submit_info(nomination_id, make_grantee_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_nomination(nomination_id, ADMIN))
        assert after["status"] == "NEEDS_INFO"

    def test_second_nomination_same_member_cycle_rejected(self, api):
        """PRD §3.4: "Each membership may nominate once per cycle: a second
        nomination by the same membership in the same cycle fails with
        `ERR_DUPLICATE_NOMINATION`."

        Design: Corner/errors/second_nomination_same_member_cycle_rejected
        """
        ctx = setup_nomination_phase(
            "Circle ER1", num_members=1, num_nominations=1
        )
        other = add_nonprofit(ctx, "NP B")
        resp = api.create_nomination(
            {
                "cycle_id": ctx["cycle"]["id"],
                "nonprofit_id": other["id"],
                "statement": "second",
            },
            make_member_headers(ctx["members"][0]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NOMINATION)
