"""Cycle phase-advance guards: per-hop preconditions, optimistic concurrency,
and the role gate on the advance operation (PRD §2.8, §3.1, §3.4, §3.6, §3.8).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_active_member,
    advance_cycle,
    create_circle_and_cycle,
    create_nomination_payload,
    create_nonprofit_payload,
    get_success_data,
    make_member_headers,
    setup_award,
    setup_nomination_in_vetting,
    setup_nomination_phase,
    setup_pooling,
    try_advance_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCycleAdvanceGuards:
    def test_advance_recruitment_to_pooling_without_active_members(self, api):
        """PRD §3.1: "Moving `RECRUITMENT` → `POOLING` requires at least one
        membership of the circle to be `ACTIVE`; with zero active memberships
        the advance fails with `ERR_NO_ACTIVE_MEMBERS`."

        Design: Corner/errors/advance_pooling_without_active_members_rejected
        """
        ctx = create_circle_and_cycle("Circle ER7")
        member = get_success_data(
            api.create_member(
                {"full_name": "M One", "email": "m1.er7@example.org"}, ADMIN
            )
        )
        # Membership is created (INVITED) but never accepted.
        get_success_data(
            api.create_membership(
                {"member_id": member["id"], "circle_id": ctx["circle"]["id"], "tier": "STANDARD"},
                ADMIN,
            )
        )
        advance_cycle(ctx["cycle"]["id"])  # DRAFT -> RECRUITMENT
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_MEMBERS)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "RECRUITMENT"

    def test_advance_pooling_to_nomination_without_received_contribution(self, api):
        """PRD §3.1: "Moving `POOLING` → `NOMINATION` requires money actually
        received: if `received_total_cents` is zero the advance fails with
        `ERR_EMPTY_POOL`."

        Design: Corner/state_machines/advance_without_received_contribution_rejected
        """
        # One PLEDGED (never received) contribution: pledged funds do not count.
        ctx = setup_pooling("Circle SM1", num_members=1, funding=[(0, 100000, False)])
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_EMPTY_POOL)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "POOLING"

    def test_advance_nomination_to_vetting_without_nominations(self, api):
        """PRD §3.4: "Closing the nomination slate is itself a cycle advance:
        `NOMINATION` → `VETTING` requires at least one nomination of the cycle
        in `SUBMITTED`, failing with `ERR_NO_NOMINATIONS` otherwise."

        Design: Corner/errors/advance_vetting_without_nominations_rejected
        """
        ctx = setup_nomination_phase("Circle ER8", num_members=1, num_nominations=0)
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_NO_NOMINATIONS)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "NOMINATION"

    def test_advance_vetting_to_voting_without_finalists(self, api):
        """PRD §3.6: "Moving `VETTING` → `VOTING` requires at least one
        nomination of the cycle in `FINALIST` (`ERR_NO_FINALISTS` otherwise)"

        Design: Corner/errors/advance_voting_without_finalists_rejected
        """
        # Nomination started vetting but was never advanced to FINALIST.
        ctx = setup_nomination_in_vetting("Circle ER9", scores=None)
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_NO_FINALISTS)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "VETTING"

    def test_advance_award_to_reporting_without_release(self, api):
        """PRD §3.8: "Moving `AWARD` → `REPORTING` requires at least one payout
        of the cycle's award in `RELEASED`, failing with `ERR_NO_PAYOUT_RELEASED`
        before the first dollar has moved."

        Design: Corner/errors/advance_reporting_without_release_rejected
        """
        ctx = setup_award("Circle ER10", num_members=1)
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_NO_PAYOUT_RELEASED)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "AWARD"

    def test_advance_with_stale_cycle_version_rejected(self, api):
        """PRD §2.8: "Advancing a cycle requires the request to carry
        `expected_cycle_version`, holding the cycle `version` the caller last
        observed. If that value does not match the cycle's current `version` —
        because an earlier advance, a contribution receipt, a payout release, or
        any cascaded ledger recompute has moved the version since the caller
        read it — the advance is rejected with `ERR_STALE_VERSION` (HTTP 412),
        so a caller never advances a cycle it has not observed."

        Design: Corner/complexity_layers/advance_with_stale_cycle_version_rejected
        """
        ctx = create_circle_and_cycle("Circle CL1")
        add_active_member(ctx, "M One")
        stale_version = ctx["cycle"]["version"]
        # First advance succeeds (DRAFT -> RECRUITMENT) and bumps the version.
        resp = api.advance_cycle(
            ctx["cycle"]["id"], {"expected_cycle_version": stale_version}, ADMIN
        )
        advanced = validate_success(resp)
        assert advanced["phase"] == "RECRUITMENT"
        assert advanced["version"] != stale_version

        # Replaying the previously observed version is rejected.
        resp = api.advance_cycle(
            ctx["cycle"]["id"], {"expected_cycle_version": stale_version}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "RECRUITMENT"

    def test_member_cannot_advance_cycle_forbidden(self, api):
        """PRD §3.1: "Only a `CircleAdmin` may advance a cycle."
        PRD §2.1: "Each write endpoint restricts which roles may invoke it
        (Section 4); a caller whose role is not listed for that endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/member_cannot_advance_cycle_forbidden
        """
        ctx = create_circle_and_cycle("Circle RB1")
        member, _membership = add_active_member(ctx, "M One")
        current = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        resp = api.advance_cycle(
            ctx["cycle"]["id"],
            {"expected_cycle_version": current["version"]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "DRAFT"

    def test_nomination_create_wrong_phase_rejected(self, api):
        """PRD §3.4: "Nomination requires the cycle to be in `NOMINATION`
        (`ERR_CYCLE_PHASE`), the membership to be `ACTIVE`
        (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the nonprofit's `standing` to be
        `GOOD` (`ERR_NONPROFIT_SUSPENDED`)."

        Design: Corner/validations/nomination_create_wrong_phase_rejected
        """
        ctx = setup_pooling("Circle VA1", num_members=1)
        nonprofit = get_success_data(
            api.create_nonprofit(create_nonprofit_payload(legal_name="NP Phase"), ADMIN)
        )
        resp = api.create_nomination(
            create_nomination_payload(ctx["cycle"]["id"], nonprofit["id"], "too early"),
            make_member_headers(ctx["members"][0]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_PHASE)
        data, meta = validate_paginated(
            api.list_nominations(ADMIN, params={"cycle_id": ctx["cycle"]["id"]})
        )
        assert meta["total_count"] == 0
        assert data == []
