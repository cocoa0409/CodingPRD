"""Agreement lifecycle: review, amendment OCC, double-adoption, terminal
lockdown, renewal guards, and mile-pool conservation (PRD §2.8, §2.9, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_agreement,
    create_agreement,
    create_event,
    create_group,
    create_segment,
    get_metrics,
    make_coordinator_headers,
    make_group_leader_headers,
    setup_active_agreement,
    validate_error,
    validate_success,
)

COORD = make_coordinator_headers()


class TestEventCreateRequiresAgreementActive:
    def test_event_create_rejected_while_pending_then_allowed_after_approval(self, api):
        """PRD §3.3: "Under an `ACTIVE` agreement, the owning `GroupLeader`
        schedules a cleanup by supplying the `agreement_id` ... the
        agreement-state guard rejects a non-`ACTIVE` agreement with
        `ERR_AGREEMENT_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/event_create_requires_agreement_active
        """
        group = create_group()
        segment = create_segment()
        agreement = create_agreement(group, segment)
        gl = make_group_leader_headers(group["id"])

        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        approve_agreement(agreement["id"])
        resp2 = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl)
        data = validate_success(resp2, 201)
        assert data["status"] == "SCHEDULED"

    def test_event_create_rejected_on_pending_agreement(self, api):
        """PRD §3.3: "the agreement-state guard rejects a non-`ACTIVE`
        agreement with `ERR_AGREEMENT_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/event_create_requires_agreement_active
        """
        group = create_group()
        segment = create_segment()
        agreement = create_agreement(group, segment)
        gl = make_group_leader_headers(group["id"])
        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-20",
             "expected_volunteers": 5}, gl)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


class TestRejectedAgreementLockdown:
    def test_rejected_agreement_terminal_lockdown(self, api):
        """PRD §3.2: "The review is only meaningful on a `PENDING_REVIEW`
        agreement; anything else draws `ERR_AGREEMENT_NOT_PENDING`."
        PRD §3.2: "an agreement already in a terminal state refuses with
        `ERR_AGREEMENT_TERMINAL`."

        Design: Corner/state_machines/rejected_agreement_terminal_lockdown
        """
        group = create_group()
        segment = create_segment()
        agreement = create_agreement(group, segment)

        rejected = validate_success(
            api.review_decision(
                agreement["id"], {"decision": "REJECT", "note": "duplicate effort"},
                COORD), 200)
        assert rejected["status"] == "REJECTED"

        resp2 = api.review_decision(agreement["id"], {"decision": "APPROVE"}, COORD)
        validate_error(resp2, ApiErrorId.ERR_AGREEMENT_NOT_PENDING)

        resp3 = api.terminate_agreement(agreement["id"], {}, COORD)
        validate_error(resp3, ApiErrorId.ERR_AGREEMENT_TERMINAL)

        seg = validate_success(api.get_segment(segment["id"], COORD), 200)
        assert seg["status"] == "AVAILABLE"

    def test_rejected_agreement_segment_never_locked(self, api):
        """PRD §2.8: "A segment's `status` is entirely system-managed: it is
        `AVAILABLE` while no non-terminal agreement spans it, and `ADOPTED`
        while an agreement referencing it is in `PENDING_REVIEW`, `ACTIVE`,
        `SUSPENDED`, or `RENEWAL_REVIEW`."

        Design: Corner/state_machines/rejected_agreement_terminal_lockdown
        """
        group = create_group()
        segment = create_segment()
        agreement = create_agreement(group, segment)
        api.review_decision(agreement["id"], {"decision": "REJECT"}, COORD)
        after = validate_success(api.get_segment(segment["id"], COORD), 200)
        assert after["status"] == "AVAILABLE"


class TestRenewalGuards:
    def test_renewal_request_outside_window_rejected(self, api):
        """PRD §3.8: "The owning leader may request it only from `ACTIVE`
        (else `ERR_AGREEMENT_NOT_ACTIVE`) and only inside the renewal window —
        from 90 days before `term_end_date` through the term end date itself,
        both endpoints included; outside that window the request is refused
        with `ERR_RENEWAL_WINDOW_CLOSED`."

        Design: Corner/validations/renewal_request_outside_window_rejected
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        # Clock is at 2026-08-01: term_end is 2028-08-01, window opens 2028-05-03.
        resp = api.renewal_request(agreement["id"], gl)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)

    def test_renewal_decision_outside_review_state_rejected(self, api):
        """PRD §3.8: "The coordinator then records a `decision` of `APPROVE`
        or `DENY`, with an optional `note`; the decision is only meaningful
        from `RENEWAL_REVIEW`, else `ERR_AGREEMENT_NOT_IN_RENEWAL`."

        Design: Corner/validations/renewal_decision_outside_review_state_rejected
        """
        group, segment, agreement = setup_active_agreement()
        resp = api.renewal_decision(agreement["id"], {"decision": "APPROVE"}, COORD)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_RENEWAL)


class TestOccAmendment:
    def test_occ_stale_then_fresh_agreement_amendment(self, api):
        """PRD §2.9: "The amendment request must carry
        `expected_agreement_version`, a non-optional field holding the
        agreement `version` the client last observed. If the agreement's
        current `version` differs — because a review decision, a suspension, an
        automatic reinstatement, or a prior amendment has advanced it since the
        client last read the agreement — the amendment is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the
        agreement before retrying."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_then_fresh_agreement_amendment
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])

        observed = validate_success(api.get_agreement(agreement["id"], gl), 200)
        v_obs = observed["version"]

        # Fresh write succeeds and bumps the version.
        first = validate_success(
            api.amend_agreement(
                agreement["id"],
                {"expected_agreement_version": v_obs,
                 "contact_email": "new-lead@riverkeepers.org"},
                gl), 200)
        assert first["version"] == v_obs + 1
        assert first["contact_email"] == "new-lead@riverkeepers.org"

        # Replaying the stale version is rejected 412.
        stale = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": v_obs,
             "special_instructions": "stale write"},
            gl)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        # Re-read and write with the fresh version succeeds.
        final = validate_success(
            api.amend_agreement(
                agreement["id"],
                {"expected_agreement_version": first["version"],
                 "special_instructions": "bring extra bags"},
                gl), 200)
        assert final["version"] == v_obs + 2
        assert final["special_instructions"] == "bring extra bags"

    def test_occ_replay_rejected_after_review_decision_advanced_version(self, api):
        """PRD §2.9: "If the agreement's current `version` differs — because a
        review decision, a suspension, an automatic reinstatement, or a prior
        amendment has advanced it since the client last read the agreement —
        the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_then_fresh_agreement_amendment
        """
        group = create_group()
        segment = create_segment()
        agreement = create_agreement(group, segment)
        gl = make_group_leader_headers(group["id"])
        # Client observed version 1 (creation). Approval advances it.
        v_obs = agreement["version"]
        approve_agreement(agreement["id"])
        resp = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": v_obs, "contact_email": "x@x.org"},
            gl)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSegmentDoubleAdoption:
    def test_segment_double_adoption_rejected(self, api):
        """PRD §3.2: "The application is refused with
        `ERR_SEGMENT_NOT_AVAILABLE` when the segment is not `AVAILABLE`"
        PRD §3.2: "Approval additionally requires the segment to still be
        `AVAILABLE` — otherwise the decision fails with
        `ERR_SEGMENT_NOT_AVAILABLE`, which is how a double approval is caught."

        Design: Corner/validations/segment_double_adoption_rejected
        """
        # Create-time guard on an ADOPTED segment.
        ga = create_group(name="Group A", contact_email="a@a.org")
        sa = create_segment(route_name="Alpha Rd", segment_type="ROADWAY",
                            water_adjacent=False)
        aga = create_agreement(ga, sa, contact_email="a@a.org")
        approve_agreement(aga["id"])

        gb = create_group(name="Group B", org_type="SCHOOL", contact_email="b@b.org")
        glb = make_group_leader_headers(gb["id"])
        resp1 = api.create_agreement(
            {"group_id": gb["id"], "segment_id": sa["id"],
             "contact_email": "b@b.org"}, glb)
        validate_error(resp1, ApiErrorId.ERR_SEGMENT_NOT_AVAILABLE)

    def test_double_approval_caught_at_review_time(self, api):
        """PRD §3.2: "Approval additionally requires the segment to still be
        `AVAILABLE` — otherwise the decision fails with
        `ERR_SEGMENT_NOT_AVAILABLE`, which is how a double approval is caught."

        Design: Corner/validations/segment_double_adoption_rejected
        """
        ga = create_group(name="Group A", contact_email="a@a.org")
        gb = create_group(name="Group B", org_type="SCHOOL", contact_email="b@b.org")
        sb = create_segment(route_name="Beta Rd", mile_marker_start=8.0,
                            mile_marker_end=9.0, segment_type="ROADWAY",
                            water_adjacent=False)
        ag1 = create_agreement(ga, sb, contact_email="a@a.org")
        ag2 = create_agreement(gb, sb, contact_email="b@b.org")

        approve_agreement(ag1["id"])
        resp2 = api.review_decision(ag2["id"], {"decision": "APPROVE"}, COORD)
        validate_error(resp2, ApiErrorId.ERR_SEGMENT_NOT_AVAILABLE)


class TestMilePoolConservation:
    def test_mile_pool_conserved_across_adopt_terminate(self, api):
        """PRD §2.8: "After every segment creation and after every agreement
        approval, termination, expiry, or renewal denial, the miles carried by
        `AVAILABLE` segments plus the miles carried by `ADOPTED` segments must
        equal the total mapped mileage across all segments — a constant once
        the segment inventory is fixed. The compensating pair for this
        invariant: approving an agreement and later terminating it returns the
        program's available mileage to exactly its pre-approval value."

        Design: Difficulty/compensating_invariant/mile_pool_conserved_across_adopt_terminate
        """
        s1 = create_segment(route_name="River Rd", mile_marker_start=4.0,
                            mile_marker_end=6.0, segment_type="RIVERBANK",
                            water_adjacent=True)
        s2 = create_segment(route_name="Hill Rd", mile_marker_start=10.0,
                            mile_marker_end=11.5, segment_type="ROADWAY",
                            water_adjacent=False)
        m0 = get_metrics()
        assert m0["available_miles"] == 3.5
        assert m0["adopted_miles"] == 0.0

        g = create_group()
        ag = create_agreement(g, s1)
        approve_agreement(ag["id"])

        m1 = get_metrics()
        assert m1["available_miles"] == 1.5
        assert m1["adopted_miles"] == 2.0

        gl = make_group_leader_headers(g["id"])
        validate_success(
            api.terminate_agreement(ag["id"], {"reason": "group dissolved"}, gl),
            200)
        m2 = get_metrics()
        assert m2["available_miles"] == 3.5
        assert m2["adopted_miles"] == 0.0

        s1_after = validate_success(api.get_segment(s1["id"], COORD), 200)
        assert s1_after["status"] == "AVAILABLE"

    def test_mile_pool_sum_constant_across_approval(self, api):
        """PRD §2.8: "the miles carried by `AVAILABLE` segments plus the miles
        carried by `ADOPTED` segments must equal the total mapped mileage
        across all segments — a constant once the segment inventory is fixed."

        Design: Difficulty/compensating_invariant/mile_pool_conserved_across_adopt_terminate
        """
        create_segment(route_name="River Rd", mile_marker_start=4.0,
                       mile_marker_end=6.0, segment_type="RIVERBANK",
                       water_adjacent=True)
        s2 = create_segment(route_name="Hill Rd", mile_marker_start=10.0,
                            mile_marker_end=11.5, segment_type="ROADWAY",
                            water_adjacent=False)
        before = get_metrics()
        total_before = before["available_miles"] + before["adopted_miles"]

        g = create_group()
        ag = create_agreement(g, s2)
        approve_agreement(ag["id"])
        after = get_metrics()
        total_after = after["available_miles"] + after["adopted_miles"]
        assert total_before == pytest.approx(total_after, abs=1e-9)
        assert after["adopted_miles"] == pytest.approx(1.5, abs=1e-9)
