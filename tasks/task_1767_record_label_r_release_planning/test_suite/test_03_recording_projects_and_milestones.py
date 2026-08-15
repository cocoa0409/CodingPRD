"""Recording projects, milestones, tracks: funding gate, budgets, OCC, lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_milestone,
    add_track,
    approve_milestone,
    create_and_start_project,
    create_artist,
    create_draft_memo,
    create_label,
    disburse_advance,
    get_recoupment_account,
    get_success_data,
    pay_milestone,
    sign_artist_via_memo,
    submit_and_approve_milestone,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_milestone_payload, create_track_payload
from test_helpers.fixtures import ADMIN, ANR, FIN


# ===========================================================================
# Queue A — cross_entity_state_dependency/project_start_requires_funded_contract
# ===========================================================================


class TestProjectStartFundingGate:
    def test_start_blocked_until_disbursed(self):
        """PRD §3.4: "Starting a project moves it from `PLANNED` to `RECORDING` and
        is where the funding gate bites: the contract must be in `ACTIVE`,
        `OPTION_WINDOW`, or `EXTENDED`, its `advance_status` must be `FUNDED`
        (`ERR_CONTRACT_NOT_FUNDED` while still `PENDING`) ..."

        Design: Difficulty/cross_entity_state_dependency/project_start_requires_funded_contract
        """
        label = create_label("Label X1")
        artist = create_artist(label["id"], "Artist X1")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=100_000)
        project = get_success_data(api_client.create_recording_project(
            contract["id"],
            {"title": "P-X1", "project_type": "SINGLE", "budget_cents": 100_000},
            ANR,
        ))
        r = api_client.start_project(project["id"], ANR)
        validate_error(r, ApiErrorId.ERR_CONTRACT_NOT_FUNDED)
        after = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert after["status"] == "PLANNED"

        # Disburse the advance and the same start succeeds.
        contract_after = get_success_data(api_client.disburse_advance(contract["id"], FIN))
        assert contract_after["advance_status"] == "FUNDED"
        account = get_recoupment_account(contract["id"])
        assert account["advance_balance_cents"] == 100_000

        started = get_success_data(api_client.start_project(project["id"], ANR))
        assert started["status"] == "RECORDING"

    def test_zero_advance_is_immediately_funded(self):
        """PRD §3.2: "The contract's `advance_status` is set to `FUNDED` immediately
        when the advance is zero, and to `PENDING` otherwise."

        Design: Difficulty/cross_entity_state_dependency/project_start_requires_funded_contract
        """
        label = create_label("Label X1z")
        artist = create_artist(label["id"], "Artist X1z")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        assert contract["advance_status"] == "FUNDED"
        project = get_success_data(api_client.create_recording_project(
            contract["id"],
            {"title": "P-X1z", "project_type": "SINGLE", "budget_cents": 100_000},
            ANR,
        ))
        started = get_success_data(api_client.start_project(project["id"], ANR))
        assert started["status"] == "RECORDING"


# ===========================================================================
# Queue A — boundary_precision_check/budget_exact_hundred_percent_pay
# ===========================================================================


class TestBudgetEqualityAllowed:
    def test_pay_reaches_exactly_budget_then_one_cent_over_rejected(self):
        """PRD §3.4: "the project's `spent_cents` plus this `payment_cents` not
        exceed `budget_cents` — equality is allowed — otherwise
        `ERR_PROJECT_BUDGET_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/budget_exact_hundred_percent_pay
        """
        label = create_label("Label B2")
        artist = create_artist(label["id"], "Artist B2")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-B2",
                                           project_type="ALBUM", budget_cents=1_000_000)
        m1 = add_milestone(project["id"], name="M1", sequence=1, payment_cents=600_000)
        submit_and_approve_milestone(m1["id"])
        pay_milestone(m1["id"])
        m2 = add_milestone(project["id"], name="M2", sequence=2, payment_cents=400_000)
        submit_and_approve_milestone(m2["id"])

        # After M2 approve: 600_000 spent + 400_000 committed = 1_000_000 >= 85% of 1_000_000
        proj_at_risk = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj_at_risk["budget_posture"] == "AT_RISK"

        # M2 pay brings spent to exactly 1_000_000 == budget_cents; allowed.
        paid = pay_milestone(m2["id"])
        assert paid["status"] == "PAID"
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj["spent_cents"] == 1_000_000
        assert proj["spent_cents"] == proj["budget_cents"]

        # One more cent breaches.
        m3 = add_milestone(project["id"], name="M3", sequence=3, payment_cents=1)
        submit_and_approve_milestone(m3["id"])
        r = api_client.pay_milestone(m3["id"], FIN)
        validate_error(r, ApiErrorId.ERR_PROJECT_BUDGET_EXCEEDED)
        proj_after = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj_after["spent_cents"] == 1_000_000

    def test_pay_at_budget_boundary_succeeds(self):
        """PRD §3.4: "the project's `spent_cents` plus this `payment_cents` not
        exceed `budget_cents` — equality is allowed".

        Design: Difficulty/boundary_precision_check/budget_exact_hundred_percent_pay
        """
        label = create_label("Label B2b")
        artist = create_artist(label["id"], "Artist B2b")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-B2b",
                                           project_type="ALBUM", budget_cents=500_000)
        m1 = add_milestone(project["id"], name="M1", sequence=1, payment_cents=500_000)
        submit_and_approve_milestone(m1["id"])
        paid = pay_milestone(m1["id"])
        assert paid["status"] == "PAID"
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj["spent_cents"] == 500_000


# ===========================================================================
# Queue A — priority_pair_validation_conflict/pay_rejected_milestone_beats_budget_exceeded
# ===========================================================================


class TestPayRejectedMilestoneBeatsBudget:
    def test_rejected_milestone_pay_returns_invalid_state(self):
        """PRD §2.9: "Seventh, the attempted state transition must be declared from
        the resource's current status — attempts from terminal states included
        (`ERR_INVALID_STATE`). ... Only after all seven general layers pass do the
        domain business rules run ... finally fiscal rules".
        PRD §3.4: "A `FinanceController` pays an `APPROVED` milestone".

        Design: Difficulty/priority_pair_validation_conflict/pay_rejected_milestone_beats_budget_exceeded
        """
        label = create_label("Label V3")
        artist = create_artist(label["id"], "Artist V3")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-V3",
                                           project_type="SINGLE", budget_cents=100_000)
        # Milestone with payment greater than budget — would also fail budget gate.
        m = add_milestone(project["id"], name="M1", sequence=1, payment_cents=200_000)
        get_success_data(api_client.submit_milestone(m["id"], {}, ANR))
        get_success_data(api_client.reject_milestone(m["id"], ADMIN))
        # Pay on REJECTED: state violation (priority 7) beats budget (fiscal).
        r = api_client.pay_milestone(m["id"], FIN)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_milestone(m["id"], ADMIN))
        assert after["status"] == "REJECTED"
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj["spent_cents"] == 0

    def test_rejected_milestone_pay_is_not_budget_error(self):
        """PRD §3.4: "Paying subtracts the amount from `committed_cents`, adds it to
        `spent_cents` ... `PAID` is terminal." A REJECTED milestone cannot be paid.

        Design: Difficulty/priority_pair_validation_conflict/pay_rejected_milestone_beats_budget_exceeded
        """
        label = create_label("Label V3b")
        artist = create_artist(label["id"], "Artist V3b")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-V3b",
                                           project_type="SINGLE", budget_cents=100_000)
        m = add_milestone(project["id"], name="M1", sequence=1, payment_cents=1_000)
        get_success_data(api_client.submit_milestone(m["id"], {}, ANR))
        get_success_data(api_client.reject_milestone(m["id"], ADMIN))
        r = api_client.pay_milestone(m["id"], FIN)
        # Must be state, not fiscal, regardless of the (small) amount.
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Queue B — milestone / project flow
# ===========================================================================


class TestMilestoneRejectResubmitCycle:
    def test_reject_resubmit_approve(self):
        """PRD §3.4: "Submission — from `PENDING`, or again from `REJECTED` as a
        resubmission — moves a milestone to `SUBMITTED` ... A `LabelAdmin` then
        approves or rejects: approval moves the milestone to `APPROVED`, adds its
        `payment_cents` to the project's `committed_cents` ...".

        Design: Corner/state_machines/milestone_reject_resubmit_cycle
        """
        label = create_label("Label S3")
        artist = create_artist(label["id"], "Artist S3")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-S3",
                                           project_type="SINGLE", budget_cents=100_000)
        m = add_milestone(project["id"], name="M1", sequence=1, payment_cents=50_000)
        s1 = get_success_data(api_client.submit_milestone(m["id"], {}, ANR))
        assert s1["status"] == "SUBMITTED"
        r1 = get_success_data(api_client.reject_milestone(m["id"], ADMIN))
        assert r1["status"] == "REJECTED"
        s2 = get_success_data(api_client.submit_milestone(
            m["id"], {"deliverable_note": "v2 mixes attached"}, ANR))
        assert s2["status"] == "SUBMITTED"
        approved = get_success_data(api_client.approve_milestone(m["id"], ADMIN))
        assert approved["status"] == "APPROVED"
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj["committed_cents"] == 50_000


class TestProjectDeliveredCompoundGate:
    def test_advance_blocked_then_succeeds(self):
        """PRD §3.4: "Advancing again from `POST_PRODUCTION` delivers the project,
        and the bar is higher: every non-`CANCELLED` milestone must be `PAID` and
        every track of the project must be `MASTERED` or `CLEARED` — any shortfall
        is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/project_delivered_compound_gate
        """
        label = create_label("Label S4")
        artist = create_artist(label["id"], "Artist S4")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-S4",
                                           project_type="SINGLE", budget_cents=100_000)
        m = add_milestone(project["id"], name="M1", sequence=1, payment_cents=50_000)
        submit_and_approve_milestone(m["id"])
        track = add_track(project["id"], isrc="USRC20000011", advance_to="MASTERED")
        # RECORDING -> POST_PRODUCTION (milestone is APPROVED, not PENDING/SUBMITTED)
        post = get_success_data(api_client.advance_project_stage(project["id"], ANR))
        assert post["status"] == "POST_PRODUCTION"

        # POST_PRODUCTION -> DELIVERED blocked: milestone APPROVED not PAID.
        r = api_client.advance_project_stage(project["id"], ANR)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)

        # After pay, delivery succeeds.
        pay_milestone(m["id"])
        delivered = get_success_data(api_client.advance_project_stage(project["id"], ANR))
        assert delivered["status"] == "DELIVERED"
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj["spent_cents"] == 50_000
        account = get_recoupment_account(contract["id"])
        assert account["recording_balance_cents"] == 50_000


class TestMilestoneSequenceConflict:
    def test_duplicate_sequence_rejected(self):
        """PRD §3.4: "a `sequence` that orders the milestone within the project and
        must be unique among the project's non-`CANCELLED` milestones
        (`ERR_MILESTONE_SEQUENCE_CONFLICT` on a duplicate)".

        Design: Corner/validations/milestone_sequence_conflict_rejected
        """
        label = create_label("Label Vb6")
        artist = create_artist(label["id"], "Artist Vb6")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb6",
                                           project_type="ALBUM", budget_cents=100_000)
        add_milestone(project["id"], name="M1", sequence=1, payment_cents=1_000)
        r = api_client.create_milestone(project["id"], create_milestone_payload(
            name="M1-dup", sequence=1, due_date="2026-09-02", payment_cents=2_000), ANR)
        validate_error(r, ApiErrorId.ERR_MILESTONE_SEQUENCE_CONFLICT)


class TestIsrcConflict:
    def test_duplicate_isrc_rejected(self):
        """PRD §3.4: "an `isrc` recording code that must be unique per label across
        all tracks (`ERR_ISRC_CONFLICT` on collision)".

        Design: Corner/validations/isrc_conflict_rejected
        """
        label = create_label("Label Vb5")
        artist = create_artist(label["id"], "Artist Vb5")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb5",
                                           project_type="ALBUM", budget_cents=100_000)
        add_track(project["id"], title="T1", isrc="USRC20000031")
        r = api_client.create_track(project["id"], create_track_payload(
            title="T2", duration_seconds=210, isrc="USRC20000031"), ANR)
        validate_error(r, ApiErrorId.ERR_ISRC_CONFLICT)
        _data, meta = validate_paginated(api_client.list_project_tracks(project["id"], ADMIN))
        assert meta["total_count"] == 1


class TestBudgetPostureThreshold:
    def test_posture_inclusive_at_85_percent(self):
        """PRD §3.4: "`budget_posture` is `AT_RISK` whenever the sum of spent and
        committed reaches at least 85 percent of `budget_cents` — the boundary is
        inclusive, so exactly 85 percent is already at risk — and `WITHIN_BUDGET`
        otherwise."

        Design: Corner/calculations/budget_posture_at_risk_threshold
        """
        label = create_label("Label C5")
        artist = create_artist(label["id"], "Artist C5")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-C5",
                                           project_type="ALBUM", budget_cents=1_000_000)
        m1 = add_milestone(project["id"], name="M1", sequence=1, payment_cents=840_000)
        submit_and_approve_milestone(m1["id"])
        proj1 = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj1["budget_posture"] == "WITHIN_BUDGET"

        m2 = add_milestone(project["id"], name="M2", sequence=2, payment_cents=10_000)
        submit_and_approve_milestone(m2["id"])
        proj2 = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        # committed 850_000 = 85% of 1_000_000 -> AT_RISK
        assert proj2["budget_posture"] == "AT_RISK"


class TestBudgetAmendValidation:
    def test_amend_below_spent_rejected_equality_allowed(self):
        """PRD §3.4: "The new budget must be at least the amount already spent —
        equality is allowed — otherwise the amendment is rejected with
        `ERR_BUDGET_BELOW_SPEND`."

        Design: Corner/validations/budget_below_spend_rejected
        """
        label = create_label("Label Vb12")
        artist = create_artist(label["id"], "Artist Vb12")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb12",
                                           project_type="ALBUM", budget_cents=1_000_000)
        m = add_milestone(project["id"], name="M1", sequence=1, payment_cents=600_000)
        submit_and_approve_milestone(m["id"])
        pay_milestone(m["id"])
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        v = proj["version"]
        r = api_client.amend_project_budget(project["id"], {
            "expected_recording_project_version": v, "budget_cents": 500_000}, ANR)
        validate_error(r, ApiErrorId.ERR_BUDGET_BELOW_SPEND)
        # Equality allowed.
        amended = get_success_data(api_client.amend_project_budget(project["id"], {
            "expected_recording_project_version": v, "budget_cents": 600_000}, ANR))
        assert amended["budget_cents"] == 600_000


class TestAmendBudgetOcc:
    def test_stale_amend_rejected(self):
        """PRD §2.8: "Amending a recording project's budget requires
        `expected_recording_project_version` to match the project's current
        `version`; ... a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_amend_budget_stale_version
        """
        label = create_label("Label L2")
        artist = create_artist(label["id"], "Artist L2")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-L2",
                                           project_type="ALBUM", budget_cents=1_000_000)
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        v = proj["version"]
        # First amend advances version.
        amended = get_success_data(api_client.amend_project_budget(project["id"], {
            "expected_recording_project_version": v, "budget_cents": 1_200_000}, ANR))
        assert amended["budget_cents"] == 1_200_000
        assert amended["version"] == v + 1
        # Stale amend carries the pre-amendment version.
        r = api_client.amend_project_budget(project["id"], {
            "expected_recording_project_version": v, "budget_cents": 1_100_000}, ANR)
        validate_error(r, ApiErrorId.ERR_STALE_VERSION)
        proj_after = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj_after["budget_cents"] == 1_200_000


class TestMilestoneApproveRbac:
    def test_finance_cannot_approve(self):
        """PRD §2.1: "A request whose role is not in the target endpoint's authorized
        role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 table: `POST /api/milestones/{id}/approve` — LabelAdmin.

        Design: Corner/rbac/finance_cannot_approve_milestone
        """
        label = create_label("Label R3")
        artist = create_artist(label["id"], "Artist R3")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-R3",
                                           project_type="SINGLE", budget_cents=100_000)
        m = add_milestone(project["id"], name="M1", sequence=1, payment_cents=1_000)
        get_success_data(api_client.submit_milestone(m["id"], {}, ANR))
        r = api_client.approve_milestone(m["id"], FIN)
        validate_error(r, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = get_success_data(api_client.get_milestone(m["id"], ADMIN))
        assert after["status"] == "SUBMITTED"


class TestRecoupmentComputedRead:
    def test_total_unrecouped_reconciles_immediately(self):
        """PRD §2.7: "Their sum is exposed as `total_unrecouped_cents`, recomputed
        whenever any bucket moves."
        PRD §3.4: "Paying ... adds the same amount to the recoupment account's
        `recording_balance_cents`, recomputing `total_unrecouped_cents`."

        Design: Corner/endpoints/computed_read_recoupment_account_totals
        """
        label = create_label("Label P3")
        artist = create_artist(label["id"], "Artist P3")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=100_000)
        get_success_data(api_client.disburse_advance(contract["id"], FIN))
        project = create_and_start_project(contract["id"], title="P-P3",
                                           project_type="SINGLE", budget_cents=100_000)
        m = add_milestone(project["id"], name="M1", sequence=1, payment_cents=50_000)
        submit_and_approve_milestone(m["id"])
        pay_milestone(m["id"])
        account = get_recoupment_account(contract["id"])
        assert account["recording_balance_cents"] == 50_000
        assert account["advance_balance_cents"] == 100_000
        assert account["total_unrecouped_cents"] == 150_000
        proj = get_success_data(api_client.get_recording_project(project["id"], ADMIN))
        assert proj["spent_cents"] == 50_000
        assert proj["committed_cents"] == 0
