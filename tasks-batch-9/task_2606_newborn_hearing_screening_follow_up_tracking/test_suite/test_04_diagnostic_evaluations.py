"""The diagnostic evaluation lifecycle: draft, submission, attestation, finalization."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import make_program_admin_headers

ADMIN = make_program_admin_headers()


def _refer_then_open_diagnostic(client, registry, left="REFER", right="REFER"):
    """Refer a newborn at birth and put it on the direct diagnostic pathway."""
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-D",
        guardian_contact_phone="5553401",
    )
    fixtures.record_encounter(
        client,
        registry,
        infant["id"],
        clock.at(hours=4),
        encounter_type="BIRTH_ADMISSION",
        left_ear_result=left,
        right_ear_result=right,
    )
    rescreen = fixtures.episodes_of(client, infant["id"])[0]
    diagnostic = fixtures.open_episode(
        client,
        infant["id"],
        "DIAGNOSTIC",
        supersedes_episode_id=rescreen["id"],
        headers=registry.n1,
    )
    return infant, rescreen, diagnostic


def test_a_new_evaluation_opens_in_draft_with_nothing_inferred(client, registry):
    """Creation writes no thresholds, no outcome and no timeliness verdict.

    PRD: "A newly opened evaluation is in `DRAFT` with `left_ear_threshold_db`,
    `right_ear_threshold_db`, `outcome`, `attested_by_provider_id`,
    `attestation_note`, `finalized_at`, and `age_days_at_finalize` all null, and
    with both `timeliness_status` and `timeliness_status_chronological_basis` at
    `PENDING`."

    Design: Corner/state_machines/new_diagnostic_evaluation_starts_in_draft
    """
    infant, rescreen, diagnostic = _refer_then_open_diagnostic(
        client, registry, left="REFER", right="PASS"
    )

    evaluation = check.assert_created(
        client.create_evaluation(
            factories.evaluation_payload(
                infant_id=infant["id"],
                episode_id=diagnostic["id"],
                facility_id=registry.ac_id,
                performed_by_provider_id=registry.a1_id,
                evaluation_datetime=clock.at(hours=5),
                method="DIAGNOSTIC_ABR",
            ),
            headers=registry.a1,
        )
    )
    assert evaluation["status"] == "DRAFT"
    check.assert_nulls(
        evaluation,
        [
            "left_ear_threshold_db",
            "right_ear_threshold_db",
            "outcome",
            "attested_by_provider_id",
            "attestation_note",
            "finalized_at",
            "age_days_at_finalize",
        ],
    )
    assert evaluation["timeliness_status"] == "PENDING"
    assert evaluation["timeliness_status_chronological_basis"] == "PENDING"

    stored_diagnostic = fixtures.read_episode(client, diagnostic["id"])
    assert stored_diagnostic["episode_type"] == "DIAGNOSTIC"
    check.assert_episode_state(stored_diagnostic, "PENDING_SCHEDULING", benchmark_days=90)
    check.assert_instant_equals(stored_diagnostic["due_date"], "2026-10-30T00:00:00Z")

    check.assert_episode_state(
        fixtures.read_episode(client, rescreen["id"]), "SUPERSEDED", closure_reason="SUPERSEDED"
    )
    stored_infant = fixtures.read_infant(client, infant["id"])
    assert stored_infant["screening_status"] == "DIAGNOSTIC_IN_PROGRESS"
    assert stored_infant["version"] == 3


def test_no_loss_finalization_mints_neither_referral_nor_linkage_task(client, registry):
    """The cleared branch resolves the episode and creates nothing downstream.

    PRD: "`intervention_status` is left untouched at `NOT_APPLICABLE`: **no** early
    intervention referral and **no** `EI_LINKAGE` task is created on this branch."

    Design: Corner/state_machines/finalize_no_loss_fork_creates_no_referral_and_no_ei_task
    """
    infant, _, diagnostic = _refer_then_open_diagnostic(client, registry)
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], diagnostic["id"], clock.at(hours=5)
    )
    fixtures.submit_evaluation(client, registry, evaluation["id"], 20, 20, "NO_LOSS")
    fixtures.attest_evaluation(
        client, registry, evaluation["id"], "ACCEPT", note="second reader agrees"
    )

    finalized = check.assert_ok(
        client.finalize_evaluation(evaluation["id"], {}, headers=registry.a1)
    )
    assert finalized["status"] == "FINALIZED_NO_LOSS"
    check.assert_instant_equals(finalized["finalized_at"], clock.at(hours=6))
    assert finalized["age_days_at_finalize"] == 0
    assert finalized["timeliness_status"] == "ON_TIME"
    assert finalized["timeliness_status_chronological_basis"] == "ON_TIME"

    episode = fixtures.read_episode(client, diagnostic["id"])
    check.assert_episode_state(
        episode, "RESOLVED_NO_LOSS", closure_reason="DIAGNOSIS_NO_LOSS"
    )
    check.assert_instant_equals(episode["closed_at"], clock.at(hours=6))

    check.assert_infant_dimensions(
        fixtures.read_infant(client, infant["id"]), "DIAGNOSED_NO_LOSS", "NOT_APPLICABLE"
    )
    check.assert_total_count(client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 0)
    check.assert_total_count(client.list_tasks(headers=ADMIN, infant_id=infant["id"]), 0)
    check.assert_facility_ledger(
        fixtures.read_facility(client, registry.bh_id), navigation_budget_units_remaining=40
    )


def test_a_finalized_evaluation_accepts_no_further_action(client, registry):
    """Both remaining action endpoints are refused once the evaluation is finalized.

    PRD: "Only an `Audiologist` may finalize, the evaluation must be in `ATTESTED`,
    else `ERR_EVALUATION_INVALID_STATE`"

    Design: Corner/state_machines/finalized_evaluation_rejects_further_attest_and_submit
    """
    infant, _, diagnostic = _refer_then_open_diagnostic(client, registry)
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], diagnostic["id"], clock.at(hours=5), method="ASSR"
    )
    fixtures.submit_evaluation(client, registry, evaluation["id"], 20, 25, "NO_LOSS")
    fixtures.attest_evaluation(client, registry, evaluation["id"], "ACCEPT")
    fixtures.finalize_evaluation(client, registry, evaluation["id"])

    late_attest = client.attest_evaluation(
        evaluation["id"], {"decision": "RETURN", "note": "too late"}, headers=registry.a2
    )
    check.assert_error_envelope(late_attest, errors.ERR_EVALUATION_INVALID_STATE)

    late_submit = client.submit_evaluation(
        evaluation["id"],
        factories.submit_payload(80, 80, "BILATERAL_LOSS"),
        headers=registry.a1,
    )
    check.assert_error_envelope(late_submit, errors.ERR_EVALUATION_INVALID_STATE)

    stored = fixtures.read_evaluation(client, evaluation["id"])
    assert stored["status"] == "FINALIZED_NO_LOSS"
    assert stored["outcome"] == "NO_LOSS"
    assert stored["left_ear_threshold_db"] == 20
    assert stored["right_ear_threshold_db"] == 25
    assert stored["attestation_note"] is None
    assert fixtures.read_infant(client, infant["id"])["screening_status"] == "DIAGNOSED_NO_LOSS"
