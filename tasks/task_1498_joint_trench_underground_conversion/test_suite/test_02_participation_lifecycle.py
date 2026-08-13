"""Participation lifecycle: listing filters, ownership, terminal lockdown,
install gate, immediate consistency, withdrawal cascade and share conservation.

PRD §3.1 (formation/withdrawal cascade), §2.1 (ownership), §2.10 (precedence).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_project,
    invite_participation,
    mobilize_participation,
    setup_mobilized_project,
    create_scheduled_segment,
    reserve_slot,
    make_coordinator_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]


class TestParticipationListing:
    def test_participations_filter_by_project_id(self, api):
        """PRD §3.1: "The participation listing may be filtered by `project_id`
        and `status`."

        Design: Corner/endpoints/participations_filter_by_project_id
        """
        proj_a = create_project(name="FA", rule20_credit_cents=0,
                                estimated_total_cost_cents=1000,
                                target_cutover_on="2026-12-31T00:00:00Z")
        proj_b = create_project(name="FB", rule20_credit_cents=0,
                                estimated_total_cost_cents=1000,
                                target_cutover_on="2026-12-31T00:00:00Z")
        pa = invite_participation(proj_a["id"], "UA", "ELECTRIC", 10000, 1)
        invite_participation(proj_b["id"], "UB", "TELECOM", 10000, 1)

        resp = api.list_participations(PM, params={"project_id": proj_a["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"expected exactly one participation, got {len(data)}"
        assert data[0]["id"] == pa["id"]
        assert meta["total_count"] == 1

    def test_get_participation_not_found_returns_404(self, api):
        """PRD §2.10: "Existence is then resolved left to right: path parameters
        and body references are checked in order, and the first reference that
        does not correspond to an existing resource is rejected with
        `ERR_NOT_FOUND` (HTTP 404) before any deeper validation runs."

        Design: Corner/entities/get_participation_not_found_returns_404
        """
        resp = api.get_participation(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestParticipationOwnership:
    def test_coordinator_cannot_transition_other_participation(self, api):
        """PRD §2.1: "This ownership rule applies to participation transitions,
        occupancy-slot creation and transitions (the slot's owning participation
        must match), and invoice payment and dispute (the invoice's owning
        participation must match); a mismatch is rejected with
        `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/validations/coordinator_cannot_transition_other_participation
        """
        project = create_project(name="V3", rule20_credit_cents=0,
                                 estimated_total_cost_cents=500000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        pa = invite_participation(project["id"], "UA", "ELECTRIC", 5000, 1)
        pb = invite_participation(project["id"], "UB", "TELECOM", 5000, 2)
        resp = api.transition_participation(
            pb["id"], {"to": "COMMITTED"}, make_coordinator_headers(pa["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)


class TestParticipationStates:
    def test_withdrawn_participation_terminal_lockdown(self, api):
        """PRD §2.10: "Every state machine in the system also observes terminal
        lockdown: once an entity reaches a terminal state, every further
        transition request on it is rejected with `ERR_INVALID_STATE`."
        PRD §3.1: "A utility may withdraw while its participation is `INVITED`,
        `COMMITTED`, or `MOBILIZED`; the same transition is unavailable once
        installed."

        Design: Corner/state_machines/withdrawn_participation_terminal_lockdown
        """
        project = create_project(name="SM2", rule20_credit_cents=0,
                                 estimated_total_cost_cents=500000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        p1 = invite_participation(project["id"], "U1", "ELECTRIC", 9999, 1)
        resp = api.transition_participation(
            p1["id"], {"to": "WITHDRAWN"}, make_coordinator_headers(p1["id"])
        )
        withdrawn = validate_success(resp, 200)
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.transition_participation(
            p1["id"], {"to": "COMMITTED"}, make_coordinator_headers(p1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_participation_installed_requires_slots_terminal(self, api):
        """PRD §3.4: "Once every slot a participation holds has reached
        `VERIFIED` or `RELEASED`, that participation may advance `MOBILIZED →
        INSTALLED`."
        A MOBILIZED participation whose only slot is still RESERVED therefore
        fails with `ERR_INVALID_STATE`.

        Design: Corner/state_machines/participation_installed_requires_slots_terminal
        """
        project, parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 9999, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 1, "sequence_order": 2},
            ],
            name="SM8", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        p1, _p2 = parts
        mobilize_participation(p1["id"])
        seg = create_scheduled_segment(project["id"])
        reserve_slot(seg["id"], p1["id"],
                     depth_top_inches=36, depth_bottom_inches=60,
                     install_start_at="2026-09-01T00:00:00Z",
                     install_end_at="2026-09-03T00:00:00Z")

        resp = api.transition_participation(
            p1["id"], {"to": "INSTALLED"}, make_coordinator_headers(p1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_transition_response_reflects_new_state_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one with every modification of the resource, and anchors
        the optimistic concurrency control described in §2.8."

        Design: Corner/consistency_model/transition_response_reflects_new_state_immediately
        """
        project = create_project(name="IM1", rule20_credit_cents=0,
                                 estimated_total_cost_cents=1000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        p1 = invite_participation(project["id"], "U1", "ELECTRIC", 9999, 1)
        created_version = p1["version"]

        resp = api.transition_participation(
            p1["id"], {"to": "COMMITTED"}, make_coordinator_headers(p1["id"])
        )
        data = validate_success(resp, 200)
        assert data["status"] == "COMMITTED", (
            f"the transition response itself must carry COMMITTED, got {data['status']}"
        )
        assert data["version"] == created_version + 1, (
            f"version must increment by one: {created_version} -> {data['version']}"
        )


class TestWithdrawalCascade:
    def _setup(self, api):
        """3-party mobilized project (est 1000001, bp 3333/3333/3334); P2
        MOBILIZED and holding one RESERVED slot (band 12-24)."""
        project, parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 3333, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3333, "sequence_order": 2},
                {"utility_name": "U3", "utility_type": "CATV", "cost_share_bp": 3334, "sequence_order": 3},
            ],
            name="Cascade Project", rule20_credit_cents=0,
            estimated_total_cost_cents=1000001,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        p1, p2, p3 = parts
        mobilize_participation(p2["id"])
        seg = create_scheduled_segment(project["id"])
        slot = reserve_slot(seg["id"], p2["id"],
                            depth_top_inches=12, depth_bottom_inches=24,
                            install_start_at="2026-09-01T00:00:00Z",
                            install_end_at="2026-09-03T00:00:00Z")
        return project, parts, seg, slot

    def test_withdrawal_releases_slots_and_recomputes_depth(self, api):
        """PRD §3.1: "Withdrawal fires a six-hop cascade. The participation
        moves to `WITHDRAWN`, records `withdrawn_on` as the clock timestamp,
        and its `provisional_share_cents` drops to zero. Every occupancy slot
        it holds in `RESERVED`, `INSTALLING`, or `INSTALL_FAILED` is released.
        Each affected segment then recomputes its occupied and available depth."

        Design: Difficulty/transitive_cascade/participation_withdrawal_cascade
        """
        project, parts, seg, slot = self._setup(api)
        _p1, p2, _p3 = parts

        resp = api.transition_participation(
            p2["id"], {"to": "WITHDRAWN"}, make_coordinator_headers(p2["id"])
        )
        validate_success(resp, 200)

        slot_after = validate_success(api.get_occupancy_slot(slot["id"], PM), 200)
        assert slot_after["status"] == "RELEASED", (
            f"withdrawal must release the RESERVED slot, got {slot_after['status']}"
        )
        seg_after = validate_success(api.get_trench_segment(seg["id"], PM), 200)
        assert seg_after["occupied_depth_inches"] == 0, (
            f"released slot must free the depth budget, occupied={seg_after['occupied_depth_inches']}"
        )
        assert seg_after["available_depth_inches"] == 60

    def test_withdrawal_rescales_shares_flags_and_posture(self, api):
        """PRD §3.1: "The remaining non-withdrawn participations rescale their
        `cost_share_bp` so the total returns to ten thousand: each surviving
        share becomes its current basis points multiplied by ten thousand and
        divided by the sum of the surviving shares, rounded half up, and any
        residual rounding drift is corrected by adjusting the participant with
        the lowest `sequence_order` — ties broken by earliest `created_at` —
        one basis point up or down. The provisional share waterfall then reruns
        for all non-withdrawn participants, each participant's `variance_flag`
        is refreshed, and the project posture is recomputed."
        PRD §2.7: "The derivation is ordered: the posture is `FROZEN` whenever
        any change order of the project is `APPROVED`; otherwise it is
        `CONDITIONAL` whenever any `TRENCH` easement on any parcel of the
        project is `REFUSED`, or whenever any participation's `variance_flag`
        is true; otherwise it is `CLEAR`."

        Design: Difficulty/transitive_cascade/participation_withdrawal_cascade
        """
        project, parts, _seg, _slot = self._setup(api)
        p1, p2, p3 = parts

        resp = api.transition_participation(
            p2["id"], {"to": "WITHDRAWN"}, make_coordinator_headers(p2["id"])
        )
        validate_success(resp, 200)

        p1_after = validate_success(api.get_participation(p1["id"], PM), 200)
        p3_after = validate_success(api.get_participation(p3["id"], PM), 200)
        assert p1_after["cost_share_bp"] == 4999, (
            f"round_half_up(3333*10000/6667) = 4999, got {p1_after['cost_share_bp']}"
        )
        assert p3_after["cost_share_bp"] == 5001, (
            f"round_half_up(3334*10000/6667) = 5001, got {p3_after['cost_share_bp']}"
        )
        assert p1_after["cost_share_bp"] + p3_after["cost_share_bp"] == 10000
        assert p1_after["provisional_share_cents"] == 499900
        assert p3_after["provisional_share_cents"] == 500101
        assert p1_after["provisional_share_cents"] + p3_after["provisional_share_cents"] == 1000001
        assert p1_after["variance_flag"] is True, (
            "|499900-333301| / 333301 ~= 49.99% >= 10% must raise the flag"
        )
        proj_after = validate_success(api.get_project(project["id"], PM), 200)
        assert proj_after["posture"] == "CONDITIONAL", (
            f"a raised variance_flag drops posture to CONDITIONAL, got {proj_after['posture']}"
        )


class TestShareConservationOnWithdrawal:
    def _setup(self, api):
        project, parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 3333, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3333, "sequence_order": 2},
                {"utility_name": "U3", "utility_type": "CATV", "cost_share_bp": 3334, "sequence_order": 3},
            ],
            name="Invariant Project", rule20_credit_cents=0,
            estimated_total_cost_cents=1000001,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        return project, parts

    def test_provisional_shares_conserve_estimate_before_withdrawal(self, api):
        """PRD §3.1: "The invariant after every run of this computation is that
        the provisional shares of the active participants sum exactly to the
        estimated total."

        Design: Difficulty/compensating_invariant/allocated_share_conservation_on_withdrawal
        """
        project, parts = self._setup(api)
        shares = []
        for p in parts:
            data = validate_success(api.get_participation(p["id"], PM), 200)
            shares.append(data["provisional_share_cents"])
        assert shares == [333301, 333300, 333400], (
            f"pinned-order rounding of 1000001 at bp 3333/3333/3334, got {shares}"
        )
        assert sum(shares) == 1000001 == project["estimated_total_cost_cents"]

    def test_provisional_shares_conserve_estimate_after_withdrawal(self, api):
        """PRD §3.1: "Withdrawn participants are excluded from the input set
        entirely and carry a share of zero; the input set is otherwise every
        participation in `COMMITTED`, `MOBILIZED`, `INSTALLED`, `BILLED`, or
        `SETTLED`."
        PRD §3.1: "The invariant after every run of this computation is that
        the provisional shares of the active participants sum exactly to the
        estimated total."

        Design: Difficulty/compensating_invariant/allocated_share_conservation_on_withdrawal
        """
        project, parts = self._setup(api)
        p1, p2, p3 = parts

        resp = api.transition_participation(
            p2["id"], {"to": "WITHDRAWN"}, make_coordinator_headers(p2["id"])
        )
        validate_success(resp, 200)

        b1 = validate_success(api.get_participation(p1["id"], PM), 200)["provisional_share_cents"]
        b2 = validate_success(api.get_participation(p2["id"], PM), 200)["provisional_share_cents"]
        b3 = validate_success(api.get_participation(p3["id"], PM), 200)["provisional_share_cents"]
        assert b2 == 0, f"withdrawn participant carries share zero, got {b2}"
        assert (b1, b3) == (499900, 500101), (
            f"rescaled shares on bp 4999/5001, got ({b1}, {b3})"
        )
        assert b1 + b3 == 1000001 == project["estimated_total_cost_cents"], (
            "the compensating rescale conserves the allocated total exactly"
        )
