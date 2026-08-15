"""Scores: entry ranges and precision, provisional computation at publish,
publication guards (rotation state, OCC), amendment lock, version increments,
and immediate read-after-write consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_entry,
    create_gymnast,
    create_judge,
    create_meet,
    create_score_payload,
    create_session,
    create_squad,
    generate_rotations,
    get_success_data,
    make_judge_panel_chief_headers,
    open_rotation,
    publish_meet,
    set_clock,
    setup_competition_ready,
    setup_published_score,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["meet_director_headers"]
REFEREE = TEST_USERS["meet_referee_headers"]


def _score_setup_with_rotation(api):
    """Minimal context for score-creation validation tests: an entry and its
    four generated rotations; meet published so nothing is posture-blocked."""
    set_clock()
    meet = create_meet()
    session = create_session(meet["id"])
    create_squad(session["id"], "A", "VAULT")
    entry = create_entry(session["id"], create_gymnast()["id"])
    judge = create_judge()
    publish_meet(meet["id"])
    rotations = generate_rotations(session["id"])
    return entry, rotations, judge


class TestScoreFieldRanges:
    def test_difficulty_out_of_range_rejected(self, api):
        """PRD §2.7: "The judged inputs to a routine are bounded: `difficulty_score` and
        `execution_score` each lie between 0.000 and 10.000 inclusive, and
        `neutral_deduction` lies between 0.000 and 5.000 inclusive. A value outside its
        declared range, or expressed at finer than three-decimal precision, is rejected with
        `ERR_SCORE_FIELD_RANGE` (HTTP 422)."

        Design: Corner/validations/score_field_range_violation_difficulty
        """
        entry, rotations, judge = _score_setup_with_rotation(api)
        chief = make_judge_panel_chief_headers(judge["id"])
        # Upper bound inclusive: exactly 10.000 is accepted.
        ok = api.create_score(entry["id"], create_score_payload(
            rotations[0]["id"], "VAULT", 10.0, 10.0), chief)
        validate_success(ok, 201)
        # Above the bound, over-precision, and an out-of-range deduction all fail.
        for bad in (create_score_payload(rotations[0]["id"], "VAULT", 10.001, 8.0),
                    create_score_payload(rotations[0]["id"], "VAULT", 5.0001, 8.0),
                    create_score_payload(rotations[0]["id"], "VAULT", 5.0, 8.0, 5.001)):
            res = api.create_score(entry["id"], bad, chief)
            validate_error(res, ApiErrorId.ERR_SCORE_FIELD_RANGE)


class TestProvisionalComputation:
    def test_publish_computes_provisional_total(self, api, meet_director_headers):
        """PRD §3.6: "Publication stamps `published_at`, computes the score's
        `provisional_total` as the difficulty score plus the execution score minus the
        neutral deduction — rounded half-up to three decimal places and floored at 0.000 —
        and pushes the result to the live scoring display."

        Design: Corner/entities/score_computed_provisional_total
        """
        ctx = setup_published_score(difficulty=6.0, execution=8.5, neutral_deduction=0.3)
        score = ctx["score"]
        assert score["score_state"] == "PUBLISHED"
        assert score["provisional_total"] == pytest.approx(14.2, abs=0.001), (
            f"provisional_total must be 6.0 + 8.5 - 0.3 = 14.200, got "
            f"{score['provisional_total']}")
        assert score.get("published_at"), "publication must stamp published_at"

    def test_provisional_total_floored_at_zero(self, api):
        """PRD §2.7: "A computed routine total can never be negative: any total that would
        fall below zero is floored at 0.000, because a routine cannot score less than
        nothing."

        Design: Corner/calculations/provisional_score_floor_at_zero
        """
        # raw = 2.0 + 1.0 - 5.0 = -2.0 -> floored to 0.000
        ctx = setup_published_score(difficulty=2.0, execution=1.0, neutral_deduction=5.0)
        assert ctx["score"]["provisional_total"] == pytest.approx(0.0, abs=0.001), (
            f"a negative raw total must be floored at 0.000, got "
            f"{ctx['score']['provisional_total']}")


class TestPublishGuards:
    def test_publish_rejected_while_rotation_pending(self, api, meet_director_headers):
        """PRD §3.6: "Publication — `DRAFT` → `PUBLISHED` — is the panel chief's act and is
        guarded three ways. The rotation the score was performed in must be
        `OPEN_FOR_SCORING`; the acting judge must hold a confirmed `PANEL_CHIEF` assignment
        on the panel for this apparatus and session; and the request must carry
        `expected_score_version` matching the score's current `version` under the
        optimistic-concurrency rule of §2.8."

        Design: Difficulty/cross_entity_state_dependency/score_publish_requires_rotation_open
        """
        # Panels staffed and meet published, but the clock never advances, so
        # every rotation is still PENDING.
        ctx = setup_competition_ready(num_athletes=1, advance_to_competition=False)
        rotation = ctx["rotations"][0]
        assert rotation["state"] == "PENDING"
        chief = make_judge_panel_chief_headers(ctx["chiefs"]["VAULT"])
        score = get_success_data(api.create_score(
            ctx["entries"][0]["id"],
            create_score_payload(rotation["id"], "VAULT", 5.0, 8.0), chief))
        res = api.publish_score(score["id"],
                                {"expected_score_version": score["version"]}, chief)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_score(score["id"], meet_director_headers))
        assert after["score_state"] == "DRAFT"

    def test_publish_rejected_while_rotation_warmup_held(self, api, meet_director_headers):
        """PRD §3.6: "Publication — `DRAFT` → `PUBLISHED` — is the panel chief's act and is
        guarded three ways. The rotation the score was performed in must be
        `OPEN_FOR_SCORING`; ..."
        PRD §3.5: "Once every block of the rotation has resolved to `COMPLETE` or `SKIPPED`,
        the rotation holds at `TIMED_WARMUP_HELD`."

        Design: Difficulty/cross_entity_state_dependency/score_publish_requires_rotation_open
        """
        # Clock advanced past every rotation start: rotations sit at
        # TIMED_WARMUP_HELD — past PENDING, but still not OPEN_FOR_SCORING.
        ctx = setup_competition_ready(num_athletes=1)
        rotation = ctx["rotations"][0]
        assert get_success_data(api.get_rotation(
            rotation["id"], meet_director_headers))["state"] == "TIMED_WARMUP_HELD"
        chief = make_judge_panel_chief_headers(ctx["chiefs"]["VAULT"])
        score = get_success_data(api.create_score(
            ctx["entries"][0]["id"],
            create_score_payload(rotation["id"], "VAULT", 5.0, 8.0), chief))
        res = api.publish_score(score["id"],
                                {"expected_score_version": score["version"]}, chief)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_score(score["id"], meet_director_headers))
        assert after["score_state"] == "DRAFT"

    def test_republish_of_published_score_rejected(self, api, meet_director_headers):
        """PRD §3.6: "Publication — `DRAFT` → `PUBLISHED` — is the panel chief's act ..."
        (the transition is defined only from `DRAFT`).
        PRD §2.9: "then the entity-specific state precondition of the requested transition
        (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/score_publish_idempotency_violation
        """
        ctx = setup_published_score()
        score = ctx["score"]
        chief = make_judge_panel_chief_headers(ctx["chiefs"]["VAULT"])
        res = api.publish_score(score["id"],
                                {"expected_score_version": score["version"]}, chief)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_score(score["id"], meet_director_headers))
        assert after["score_state"] == "PUBLISHED"

    def test_amend_after_publish_rejected(self, api, meet_director_headers):
        """PRD §3.6: "While a score remains in `DRAFT`, the panel chief may amend any of
        `difficulty_score`, `execution_score`, or `neutral_deduction`; each amendment
        increments the score's `version` by one. Once the score has left `DRAFT`, amendment
        is rejected with `ERR_SCORE_AMEND_AFTER_PUBLISH` (HTTP 409)."

        Design: Corner/endpoints/score_amend_after_publish_rejected
        """
        ctx = setup_published_score()
        chief = make_judge_panel_chief_headers(ctx["chiefs"]["VAULT"])
        res = api.amend_score(ctx["score"]["id"], {"execution_score": 9.0}, chief)
        validate_error(res, ApiErrorId.ERR_SCORE_AMEND_AFTER_PUBLISH)
        after = get_success_data(api.get_score(ctx["score"]["id"], meet_director_headers))
        assert after["execution_score"] == pytest.approx(8.0, abs=0.001)


class TestScoreOcc:
    def test_publish_with_stale_version_rejected(self, api, meet_director_headers):
        """PRD §2.8: "Publishing a score requires the request body to carry
        `expected_score_version`, the score's `version` as last observed by the panel chief.
        If another writer has since amended the score's inputs — a legitimate pre-publish
        amendment — the versions will not match, and the publish is rejected with
        `ERR_STALE_SCORE_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_score_version_occ
        """
        ctx = setup_competition_ready(num_athletes=1)
        rotation = ctx["rotations"][0]
        open_rotation(rotation["id"])
        chief = make_judge_panel_chief_headers(ctx["chiefs"]["VAULT"])
        score = get_success_data(api.create_score(
            ctx["entries"][0]["id"],
            create_score_payload(rotation["id"], "VAULT", 5.0, 8.0), chief))
        stale_version = score["version"]
        amended = get_success_data(api.amend_score(
            score["id"], {"execution_score": 8.5}, chief))
        assert amended["version"] == stale_version + 1
        res = api.publish_score(score["id"],
                                {"expected_score_version": stale_version}, chief)
        validate_error(res, ApiErrorId.ERR_STALE_SCORE_VERSION)
        after = get_success_data(api.get_score(score["id"], meet_director_headers))
        assert after["score_state"] == "DRAFT", "stale publish must not transition the score"

    def test_version_increments_on_every_score_mutation(self, api, meet_director_headers):
        """PRD §2.6: "`version` (integer): a system-managed integer that increments by one
        with every modification to the resource, including cascading side effects."
        PRD §3.6: "While a score remains in `DRAFT`, the panel chief may amend any of
        `difficulty_score`, `execution_score`, or `neutral_deduction`; each amendment
        increments the score's `version` by one."

        Design: Corner/cross_cutting/occ_version_increments_on_every_mutation
        """
        ctx = setup_competition_ready(num_athletes=1)
        rotation = ctx["rotations"][0]
        open_rotation(rotation["id"])
        chief = make_judge_panel_chief_headers(ctx["chiefs"]["VAULT"])
        created = get_success_data(api.create_score(
            ctx["entries"][0]["id"],
            create_score_payload(rotation["id"], "VAULT", 5.0, 8.0), chief))
        amended = get_success_data(api.amend_score(
            created["id"], {"execution_score": 8.5}, chief))
        assert amended["version"] == created["version"] + 1, (
            f"amendment must increment version by one: {created['version']} -> "
            f"{amended['version']}")
        published = get_success_data(api.publish_score(
            created["id"], {"expected_score_version": amended["version"]}, chief))
        assert published["version"] == amended["version"] + 1, (
            f"publication must increment version by one: {amended['version']} -> "
            f"{published['version']}")


class TestImmediateConsistency:
    def test_publish_result_immediately_visible(self, api, meet_director_headers):
        """PRD §3.6: "Publication stamps `published_at`, computes the score's
        `provisional_total` as the difficulty score plus the execution score minus the
        neutral deduction — rounded half-up to three decimal places and floored at 0.000 —
        and pushes the result to the live scoring display."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_score_publish_visible
        """
        ctx = setup_published_score(difficulty=5.2, execution=8.85, neutral_deduction=0.1)
        published = ctx["score"]
        assert published["score_state"] == "PUBLISHED"
        assert published["provisional_total"] == pytest.approx(13.95, abs=0.001)
        reread = get_success_data(api.get_score(published["id"], meet_director_headers))
        assert reread["score_state"] == "PUBLISHED"
        assert reread["provisional_total"] == pytest.approx(published["provisional_total"],
                                                            abs=0.0001), (
            "the computed provisional_total must be identical on immediate re-read")
