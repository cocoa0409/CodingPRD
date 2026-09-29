"""Non-linear state machines: the gate revision loop, the asset's two independent
dimensions, and the vendor QC fork."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSET_BUILD_STATE_INVALID,
    ERR_GATE_STATE_INVALID,
    ERR_PRODUCTION_PHASE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_cents, assert_two_decimal, assert_unchanged
from test_helpers.constants import (
    BUILD_BRIEFED,
    BUILD_MODELING,
    BUILD_PUBLISHED,
    GATE_CHANGES_REQUESTED,
    GATE_IN_REVIEW,
    GATE_LOCKED,
    LIBRARY_APPROVED,
    LIBRARY_CANDIDATE,
    LIBRARY_PRIVATE,
    PACKAGE_QC_FAILED,
    PACKAGE_QC_PASSED,
    PHASE_PRE_PRODUCTION,
    PHASE_PRODUCTION_ACTIVE,
    SHOT_IN_PRODUCTION,
    TASK_APPROVED,
    TASK_RETAKE,
    TASK_SUBMITTED,
)
from test_helpers.test_users import (
    ARTIST_HEADERS,
    ARTIST_USER_ID,
    DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SUPERVISOR_HEADERS,
    SUPERVISOR_USER_ID,
    make_supervisor_headers,
)

V1_URL = "s3://ad01/script/v1.pdf"
V2_URL = "s3://ad01/script/v2.pdf"
V3_URL = "s3://ad01/script/v3.pdf"


def _script_gate_bounced_once(client):
    """A single-gate show whose SCRIPT gate has been submitted and sent back once."""
    production = fx.open_production(
        client,
        title="Aurora Drift",
        production_code="AD01",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )
    gate = fx.gate_for_type(client, production["id"], "SCRIPT")
    validate_success(
        client.submit_gate(gate["id"], f.gate_submit_payload(V1_URL), PRODUCTION_MANAGER_HEADERS)
    )
    bounced = validate_success(
        client.decide_gate(
            gate["id"], f.gate_decision_payload(GATE_CHANGES_REQUESTED), DIRECTOR_HEADERS
        )
    )
    return production, bounced


class TestGateRevisionLoop:
    def test_the_loop_leaves_revision_count_as_its_only_residue(self, client):
        """Each director bounce adds one to the lifetime tally while the re-submission that
        follows it changes only the URL, so two round trips read revision_count 2 and never
        reset the counter.

        PRD: "A `CHANGES_REQUESTED` decision moves the gate `IN_REVIEW → CHANGES_REQUESTED`
        and adds 1 to its `revision_count`; the production manager then resubmits with a
        fresh `package_url`, moving it `CHANGES_REQUESTED → IN_REVIEW` and overwriting
        `submitted_by_user_id`."
        PRD: "This is a genuine loop: `DRAFT → IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW` may
        run any number of times, and `revision_count` is **never** reset, so it is a lifetime
        tally of how many times the director sent the artifact back."

        Design: Difficulty/non_linear_state_machine/gate_changes_requested_revision_cycle
        """
        production, bounced = _script_gate_bounced_once(client)
        assert bounced["status"] == GATE_CHANGES_REQUESTED
        assert bounced["revision_count"] == 1
        assert bounced["package_url"] == V1_URL

        resubmitted = validate_success(
            client.submit_gate(
                bounced["id"], f.gate_submit_payload(V2_URL), PRODUCTION_MANAGER_HEADERS
            )
        )
        assert resubmitted["status"] == GATE_IN_REVIEW
        assert resubmitted["revision_count"] == 1, (
            "a re-submission is not a revision; only the director's bounce counts"
        )
        assert resubmitted["package_url"] == V2_URL

        bounced_again = validate_success(
            client.decide_gate(
                bounced["id"],
                f.gate_decision_payload(GATE_CHANGES_REQUESTED),
                DIRECTOR_HEADERS,
            )
        )
        assert bounced_again["status"] == GATE_CHANGES_REQUESTED
        assert bounced_again["revision_count"] == 2

        second_resubmission = validate_success(
            client.submit_gate(
                bounced["id"], f.gate_submit_payload(V3_URL), PRODUCTION_MANAGER_HEADERS
            )
        )
        assert second_resubmission["status"] == GATE_IN_REVIEW
        assert second_resubmission["revision_count"] == 2
        assert second_resubmission["package_url"] == V3_URL
        assert (
            fx.read_production(client, production["id"])["phase"] == PHASE_PRE_PRODUCTION
        ), "the show cannot start while its only gate is still in the loop"

    def test_the_second_pass_approval_locks_the_gate_and_closes_the_endpoint(self, client):
        """Approving the re-submitted gate starts the show, so the gate reads LOCKED rather
        than APPROVED and the submit endpoint that was legal twice is now refused.

        PRD: "The moment every gate row of the production has `status` `APPROVED`, the system
        — with no separate request from anyone — moves the production `PRE_PRODUCTION →
        PRODUCTION_ACTIVE`, drives every one of its gates `APPROVED → LOCKED` (a locked gate
        is immutable, and any further submission attempt on it returns
        `ERR_GATE_STATE_INVALID`), recomputes every shot of the production from
        `BLOCKED_PREPROD` to `READY`, and adds 1 to the production's `version`."
        PRD: "Submitting a gate that is not in `DRAFT` or `CHANGES_REQUESTED` — one already
        `IN_REVIEW`, `APPROVED` or `LOCKED` — is refused with `ERR_GATE_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/gate_changes_requested_revision_cycle
        """
        production, bounced = _script_gate_bounced_once(client)
        opening_version = production["version"]

        validate_success(
            client.submit_gate(
                bounced["id"], f.gate_submit_payload(V2_URL), PRODUCTION_MANAGER_HEADERS
            )
        )
        validate_success(
            client.decide_gate(
                bounced["id"], f.gate_decision_payload("APPROVED"), DIRECTOR_HEADERS
            )
        )

        settled = validate_success(
            client.get_gate(bounced["id"], PRODUCTION_MANAGER_HEADERS)
        )
        assert settled["status"] == GATE_LOCKED, (
            "the last gate does not rest at APPROVED; the show starting locks it"
        )
        assert settled["revision_count"] == 1
        assert settled["package_url"] == V2_URL
        assert settled["decided_at"] is not None

        started = fx.read_production(client, production["id"])
        assert started["phase"] == PHASE_PRODUCTION_ACTIVE
        assert started["version"] == opening_version + 1

        # A gate only ever reaches `LOCKED` once the show has already left
        # `PRE_PRODUCTION`, so §3.1's `ERR_GATE_STATE_INVALID` for a locked gate and
        # §2.10's normative ordering (check 10, production phase, ahead of check 11,
        # target state) both describe this one request. Either 409 is PRD-faithful.
        refused = client.submit_gate(
            bounced["id"], f.gate_submit_payload(V3_URL), PRODUCTION_MANAGER_HEADERS
        )
        assert refused.status_code == 409, (
            f"a locked gate refuses further submission with 409, got {refused.status_code}"
        )
        validate_error_is_one_of(
            refused, [ERR_GATE_STATE_INVALID, ERR_PRODUCTION_PHASE_INVALID]
        )
        assert (
            validate_success(client.get_gate(bounced["id"], PRODUCTION_MANAGER_HEADERS))[
                "package_url"
            ]
            == V2_URL
        )


def _active_show(client, title="Aurora Drift", production_code="AD01"):
    return fx.active_production(
        client,
        title=title,
        production_code=production_code,
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )


def _hero_asset(client, production_id):
    return fx.create_asset(
        client,
        production_id,
        asset_code="AD01_CHAR_HERO",
        asset_type="CHARACTER_MODEL",
        base_complexity_points=200.00,
    )


class TestAssetTwoDimensions:
    def test_the_build_ladder_and_the_library_ladder_never_move_each_other(self, client):
        """Climbing to PUBLISHED leaves the asset PRIVATE, and the nomination plus approval
        that follow leave build_status pinned at PUBLISHED.

        PRD: "`build_status` tracks construction; `library_status` tracks whether the asset
        has been promoted into the studio's reuse library."
        PRD: "Neither dimension constrains the other except where this section says so
        explicitly, and an operation on one dimension never silently moves the other."
        PRD: "An artist nominates a published asset, which moves `library_status` `PRIVATE →
        LIBRARY_CANDIDATE` and records the nominator in `library_submitted_by_user_id`; the
        nomination requires `build_status` to be `PUBLISHED` (otherwise
        `ERR_ASSET_BUILD_STATE_INVALID`) and `library_status` to be `PRIVATE` (otherwise
        `ERR_ASSET_LIBRARY_STATE_INVALID`), and it leaves `build_status` completely untouched."
        PRD: "Each accepted step adds 1 to the asset's `version`."

        Design: Difficulty/non_linear_state_machine/asset_build_and_library_dimensions_advance_independently
        """
        production = _active_show(client)
        asset = _hero_asset(client, production["id"])
        assert asset["build_status"] == BUILD_BRIEFED
        assert asset["library_status"] == LIBRARY_PRIVATE
        assert_two_decimal(
            asset["effective_complexity_points"], 200.00, "effective_complexity_points"
        )
        assert asset["library_submitted_by_user_id"] is None
        assert asset["library_decided_by_user_id"] is None
        briefed_version = asset["version"]

        published = fx.publish_asset(client, asset["id"])
        assert published["build_status"] == BUILD_PUBLISHED
        assert published["library_status"] == LIBRARY_PRIVATE, (
            "four build steps must not touch the library dimension"
        )
        assert published["version"] == briefed_version + 4

        nominated = validate_success(
            client.library_submit_asset(asset["id"], {}, ARTIST_HEADERS)
        )
        assert nominated["build_status"] == BUILD_PUBLISHED
        assert nominated["library_status"] == LIBRARY_CANDIDATE
        assert nominated["library_submitted_by_user_id"] == ARTIST_USER_ID

        approved = validate_success(
            client.library_decide_asset(
                asset["id"], f.library_decision_payload("APPROVED"), SUPERVISOR_HEADERS
            )
        )
        assert approved["build_status"] == BUILD_PUBLISHED, (
            "the library decision must not move the build dimension"
        )
        assert approved["library_status"] == LIBRARY_APPROVED
        assert approved["library_decided_by_user_id"] == SUPERVISOR_USER_ID
        assert_two_decimal(
            approved["effective_complexity_points"], 200.00, "effective_complexity_points"
        )

    def test_a_skipped_rung_and_a_self_decided_nomination_are_both_refused(self, client):
        """Jumping from MODELING to SURFACING is refused, nominating an unpublished asset is
        refused on the build dimension, and the nominating artist may not decide their own
        candidate.

        PRD: "An artist supplies a `to_build_status`, and the value must be **exactly the
        immediate successor** of the current one along `BRIEFED → MODELING → RIGGING →
        SURFACING → PUBLISHED`; skipping a step, or going backwards, is refused with
        `ERR_ASSET_BUILD_STATE_INVALID`."
        PRD: "If the two are equal, the decision is refused with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403), and no counter, timestamp or state moves."

        Design: Difficulty/non_linear_state_machine/asset_build_and_library_dimensions_advance_independently
        """
        production = _active_show(client)
        asset = _hero_asset(client, production["id"])

        at_modeling = validate_success(
            client.advance_asset_build(
                asset["id"], f.advance_build_payload(BUILD_MODELING), ARTIST_HEADERS
            )
        )
        assert at_modeling["build_status"] == BUILD_MODELING

        validate_error(
            client.advance_asset_build(
                asset["id"], f.advance_build_payload("SURFACING"), ARTIST_HEADERS
            ),
            ERR_ASSET_BUILD_STATE_INVALID,
            409,
        )
        after_skip = fx.read_asset(client, asset["id"])
        assert_unchanged(at_modeling, after_skip, ["build_status", "library_status", "version"])

        validate_error(
            client.library_submit_asset(asset["id"], {}, ARTIST_HEADERS),
            ERR_ASSET_BUILD_STATE_INVALID,
            409,
        )
        assert fx.read_asset(client, asset["id"])["library_status"] == LIBRARY_PRIVATE

        for rung in ("RIGGING", "SURFACING", "PUBLISHED"):
            validate_success(
                client.advance_asset_build(
                    asset["id"], f.advance_build_payload(rung), ARTIST_HEADERS
                )
            )
        nominated = validate_success(
            client.library_submit_asset(asset["id"], {}, ARTIST_HEADERS)
        )
        assert nominated["library_status"] == LIBRARY_CANDIDATE

        validate_error(
            client.library_decide_asset(
                asset["id"],
                f.library_decision_payload("APPROVED"),
                make_supervisor_headers(ARTIST_USER_ID),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        after_self_decision = fx.read_asset(client, asset["id"])
        assert after_self_decision["library_status"] == LIBRARY_CANDIDATE
        assert after_self_decision["library_decided_by_user_id"] is None
        assert after_self_decision["build_status"] == BUILD_PUBLISHED
        assert_unchanged(nominated, after_self_decision, ["library_status", "version"])

        decided = validate_success(
            client.library_decide_asset(
                asset["id"], f.library_decision_payload("APPROVED"), SUPERVISOR_HEADERS
            )
        )
        assert decided["library_status"] == LIBRARY_APPROVED
        assert decided["library_decided_by_user_id"] == SUPERVISOR_USER_ID


def _two_delivered_packages(client):
    """Two shots, one LAYOUT task each, packaged out to one vendor and both delivered."""
    production = _active_show(client)
    shots = []
    tasks = []
    for shot_code in ("AD01_010_0010", "AD01_010_0020"):
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code=shot_code,
            sequence_code="010",
            frame_count=120,
            budget_cents=1000000,
            planned_start_at="2026-08-01T00:00:00Z",
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, task["id"])
        shots.append(shot)
        tasks.append(task)

    partner = fx.approved_partner(
        client,
        legal_name="Northwind Animation",
        security_certification_level="TIER1",
        mfa_enforced=False,
        watermark_required=False,
    )

    packages = []
    for package_code, task in zip(("AD01-PKG-A", "AD01-PKG-B"), tasks):
        package = fx.draft_package(
            client,
            production["id"],
            partner["id"],
            package_code=package_code,
            security_tier="TIER1",
            fee_cents=500000,
            stage_task_ids=[task["id"]],
            quality_min_score=50.00,
        )
        fx.issue_package(client, package["id"])
        fx.accept_package(client, package["id"], partner["id"])
        packages.append(
            fx.deliver_package(client, package["id"], partner["id"], watermark_applied=False)
        )

    return production, shots, tasks, partner, packages


class TestPackageQcFork:
    def test_pass_approves_the_scoped_task_while_fail_retakes_an_identical_one(self, client):
        """One endpoint, two decision arguments: the passing package's LAYOUT task lands
        APPROVED on revision 0 and earns 100000 cents, while the failing package's identical
        task lands RETAKE on revision 1 and earns nothing.

        PRD: "They differ in what they do to the scoped work: a first delivery moves every
        scoped stage task whose `status` is `IN_PROGRESS` to `SUBMITTED` with
        `submitted_by_user_id` set to the vendor's identifier, while a redelivery moves every
        scoped stage task whose `status` is `RETAKE` to `SUBMITTED`."
        PRD: "`PASS` moves the package `DELIVERED → QC_PASSED` and drives every scoped stage
        task whose `status` is `SUBMITTED` or `IN_REVIEW` to `APPROVED`, which lifts the
        shot's `bcwp_cents`, recomputes the shot's `status`, and recomputes the production's
        rollups."
        PRD: "`FAIL` moves the package `DELIVERED → QC_FAILED` and drives every scoped stage
        task whose `status` is `SUBMITTED`, `IN_REVIEW` **or** `APPROVED` to `RETAKE` with
        `revision_count` increased by 1, which recomputes the shot's `retake_count`,
        `escalation_flag` and `status` and the production's `total_retake_count`."

        Design: Difficulty/non_linear_state_machine/package_qc_fork_produces_divergent_side_effects
        """
        _, shots, tasks, _, packages = _two_delivered_packages(client)
        for task in tasks:
            assert fx.read_task(client, task["id"])["status"] == TASK_SUBMITTED

        passed = validate_success(
            client.qc_decide_package(
                packages[0]["id"],
                f.package_qc_payload("PASS", 90),
                SUPERVISOR_HEADERS,
            )
        )
        assert passed["status"] == PACKAGE_QC_PASSED
        assert passed["qc_score"] == 90

        failed = validate_success(
            client.qc_decide_package(
                packages[1]["id"],
                f.package_qc_payload("FAIL", 30),
                SUPERVISOR_HEADERS,
            )
        )
        assert failed["status"] == PACKAGE_QC_FAILED
        assert failed["qc_score"] == 30

        approved_task = fx.read_task(client, tasks[0]["id"])
        assert approved_task["status"] == TASK_APPROVED
        assert approved_task["revision_count"] == 0, "a pass consumes no revision"
        assert approved_task["escalated"] is False

        retaken_task = fx.read_task(client, tasks[1]["id"])
        assert retaken_task["status"] == TASK_RETAKE
        assert retaken_task["revision_count"] == 1
        assert retaken_task["escalated"] is False

        credited_shot = fx.read_shot(client, shots[0]["id"])
        assert_cents(credited_shot["bcwp_cents"], 100000, "bcwp_cents")
        assert credited_shot["status"] == SHOT_IN_PRODUCTION
        assert credited_shot["retake_count"] == 0

        debited_shot = fx.read_shot(client, shots[1]["id"])
        assert_cents(debited_shot["bcwp_cents"], 0, "bcwp_cents")
        assert debited_shot["retake_count"] == 1
        assert debited_shot["status"] == SHOT_IN_PRODUCTION
        assert debited_shot["escalation_flag"] is False

    def test_both_branches_pay_the_fee_and_feed_one_quality_average(self, client):
        """The 90.00 pass and the 30.00 failure both count at TIER1 weight inside the window,
        so the vendor reads 60.00 on both variants, and the failed package is still paid for.

        PRD: "Both branches store `qc_score` and stamp `qc_decided_at` from the logical clock,
        add 1 to the partner's `qc_decided_package_count`, recompute both
        `quality_score_rolling` and `quality_score_lifetime`, and leave `fee_committed_cents`
        at `fee_cents` — a failed package is still paid for, and only the vendor's quality is
        debited."
        PRD: "The score is the sum over the input set of each package's `qc_score` multiplied
        by its weight, divided by the sum of the weights, with the division performed once on
        the accumulated sums and the result rounded half-up to two decimal places — per-term
        rounding is not used, so nothing accumulates."
        PRD: "Independently of escalation, every retake recomputes the shot's `retake_count`
        as the sum of `revision_count` over its five tasks, and the production's
        `total_retake_count` as the sum of `retake_count` over its shots."

        Design: Difficulty/non_linear_state_machine/package_qc_fork_produces_divergent_side_effects
        """
        production, _, tasks, partner, packages = _two_delivered_packages(client)

        before = fx.read_partner(client, partner["id"])
        assert_two_decimal(before["quality_score_rolling"], 50.00, "quality_score_rolling")
        assert_two_decimal(before["quality_score_lifetime"], 50.00, "quality_score_lifetime")
        assert before["qc_decided_package_count"] == 0

        fx.qc_package(client, packages[0]["id"], "PASS", 90)
        failed = fx.qc_package(client, packages[1]["id"], "FAIL", 30)
        assert_cents(failed["fee_committed_cents"], 500000, "fee_committed_cents")

        scored = fx.read_partner(client, partner["id"])
        assert_two_decimal(scored["quality_score_rolling"], 60.00, "quality_score_rolling")
        assert_two_decimal(scored["quality_score_lifetime"], 60.00, "quality_score_lifetime")
        assert scored["qc_decided_package_count"] == 2

        rolled_up = fx.read_production(client, production["id"])
        assert rolled_up["total_retake_count"] == 1
        assert rolled_up["shot_count"] == 2
        assert rolled_up["completed_shot_count"] == 0
        assert rolled_up["at_risk_shot_count"] == 0
        assert_cents(rolled_up["direct_committed_cents"], 1000000, "direct_committed_cents")
