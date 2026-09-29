"""Two deep cascades from two different triggers: incident substantiation and
the compliance run's certificate-expiry phase."""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    resolve_incident,
    run_compliance,
    set_clock,
    setup_incident_under_review,
    setup_sitting,
)

_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]


def test_substantiation_cascades_four_levels_to_the_local_registration(api):
    """The trigger touches only the incident, yet the sitting, the report, the
    certificate and the health-department registration all move behind it.

    PRD: "The sitting moves `session_status` to `INVALIDATED` — from `SUBMITTED`
    or from `CLOSED`, whichever it held — and `proctoring_status` to
    `COMPROMISED`, which is terminal."

    PRD: "Any certificate issued from that report moves `ISSUED → REVOKED` with
    `revocation_reason` `SCORE_VOIDED`"

    PRD: "Every local registration of that certificate whose `status` is `FILED`,
    `POSTED`, `VERIFIED` or `DELINQUENT` moves to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/incident_substantiation_depth4_cascade_to_local_registration_withdrawal
    """
    env = setup_incident_under_review(stage="VERIFIED", severity="MAJOR")
    admin = env["admin_headers"]
    assert env["local_registration"]["status"] == "VERIFIED"

    incident = resolve_incident(env, env["incident"], outcome="SUBSTANTIATE",
                               admin_headers=_SECURITY_ADMIN)

    assert incident["status"] == "SUBSTANTIATED"
    assert incident["severity_weight"] == 3
    assert incident["resolved_by_user_id"] == "admin-security-1"

    session = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert (session["session_status"], session["proctoring_status"]) == (
        "INVALIDATED", "COMPROMISED")

    report = get_success_data(api.get_score_report(env["score_report"]["id"], admin))
    assert report["status"] == "VOIDED"
    assert report["pass_flag"] is False
    assert report["final_scaled_score"] == 75

    certificate = get_success_data(api.get_certificate(env["certificate"]["id"], admin))
    assert certificate["status"] == "REVOKED"
    assert certificate["revocation_reason"] == "SCORE_VOIDED"

    registration = get_success_data(api.get_local_registration(
        env["local_registration"]["id"], admin))
    assert registration["status"] == "WITHDRAWN"


def test_revocation_credits_the_issuance_fee_back_into_the_provider_ledger(api):
    """The revocation half of the compensating pair returns exactly 1500 cents.

    PRD: "and that certificate's `issuance_fee_cents` is added back to the
    provider's `lifetime_credited_cents` with `credit_balance_cents` recomputed"

    Design: Difficulty/transitive_cascade/incident_substantiation_depth4_cascade_to_local_registration_withdrawal
    """
    env = setup_incident_under_review(stage="VERIFIED", severity="MAJOR")
    admin = env["admin_headers"]
    before = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert before["credit_balance_cents"] == 494738

    resolve_incident(env, env["incident"], outcome="SUBSTANTIATE",
                     admin_headers=_SECURITY_ADMIN)

    after = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert after["lifetime_charged_cents"] == 5262
    assert after["lifetime_credited_cents"] == 501500
    assert after["credit_balance_cents"] == 496238


def test_a_substantiated_major_incident_taints_candidate_and_proctor(api):
    """The candidate goes NON_COMPLIANT without a hold, and the proctor's lifetime
    risk of 30.00 breaches the suspension gate.

    PRD: "their `security_hold` is set to true **only** when the incident's
    `severity` is `CRITICAL`, so a substantiated `MINOR` or `MAJOR` incident
    invalidates the sitting without barring the candidate from future scheduling"

    PRD: "if that recomputed score reaches 10.00 or more while the proctor is
    `REGISTERED`, the proctor moves `REGISTERED → SUSPENDED` with
    `suspended_reason` `RISK_THRESHOLD_BREACH`"

    Design: Difficulty/transitive_cascade/incident_substantiation_depth4_cascade_to_local_registration_withdrawal
    """
    env = setup_incident_under_review(stage="VERIFIED", severity="MAJOR")
    admin = env["admin_headers"]

    resolve_incident(env, env["incident"], outcome="SUBSTANTIATE",
                     admin_headers=_SECURITY_ADMIN)

    candidate = get_success_data(api.get_candidate(env["candidate"]["id"], admin))
    assert candidate["compliance_status"] == "NON_COMPLIANT"
    assert candidate["substantiated_incident_count"] == 1
    assert candidate["security_hold"] is False

    proctor = get_success_data(api.get_proctor(env["proctor"]["id"], admin))
    assert proctor["substantiated_incident_weight_total"] == 3
    assert float(proctor["risk_score"]) == 30.00
    assert proctor["risk_variant_applied"] == "LIFETIME_CUMULATIVE"
    assert proctor["registration_status"] == "SUSPENDED"
    assert proctor["suspended_reason"] == "RISK_THRESHOLD_BREACH"


def test_compliance_run_expiry_cascades_to_withdrawal_and_candidate_lapse(api):
    """Phase two fires on the inclusive boundary and drags the registration and
    the holder's compliance posture down with the certificate.

    PRD: "Every certificate whose `status` is `ISSUED` and whose `expires_at` is
    at or before `run_epoch` — the comparison is inclusive — moves `ISSUED →
    EXPIRED`; its holder's `compliance_status` drops to `LAPSED`, and its local
    registrations in `FILED`, `POSTED`, `VERIFIED` or `DELINQUENT` move to
    `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/compliance_run_certificate_expiry_depth3_cascade_to_candidate_lapse
    """
    env = setup_sitting(stage="VERIFIED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    certificate = env["certificate"]
    assert get_success_data(api.get_candidate(
        env["candidate"]["id"], admin))["compliance_status"] == "CERTIFIED"

    set_clock(certificate["expires_at"], admin)
    summary = run_compliance(env)

    assert summary["run_epoch"] == certificate["expires_at"]
    assert summary["certificates_expired_count"] == 1
    assert summary["batches_expired_count"] == 1
    assert summary["registrations_delinquent_count"] == 0

    expired = get_success_data(api.get_certificate(certificate["id"], admin))
    assert expired["status"] == "EXPIRED"
    assert expired["revocation_reason"] is None

    registration = get_success_data(api.get_local_registration(
        env["local_registration"]["id"], admin))
    assert registration["status"] == "WITHDRAWN"

    candidate = get_success_data(api.get_candidate(env["candidate"]["id"], admin))
    assert candidate["compliance_status"] == "LAPSED"
    assert candidate["security_hold"] is False
    assert candidate["substantiated_incident_count"] == 0


def test_phase_four_sends_the_lapsed_tier_because_phase_two_ran_first(api):
    """Reminder dispatch sees the world phase two produced, so the certificate it
    just expired is notified at T_LAPSED and never at T_30.

    PRD: "The due tier is chosen most-overdue-first, and exactly one is chosen:
    `T_LAPSED` when the logical clock is at or after `expires_at`; otherwise
    `T_30` when the clock is at or after 30 days before `expires_at`"

    PRD: "The run executes four phases in a pinned order, and each phase sees the
    world the earlier phases produced."

    Design: Difficulty/transitive_cascade/compliance_run_certificate_expiry_depth3_cascade_to_candidate_lapse
    """
    env = setup_sitting(stage="VERIFIED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    certificate = env["certificate"]
    assert certificate["reminder_tiers_sent"] == []

    set_clock(certificate["expires_at"], admin)
    summary = run_compliance(env)

    assert summary["reminder_notices_sent_count"] == 1
    assert summary["notified_certificate_ids"] == [certificate["id"]]
    refreshed = get_success_data(api.get_certificate(certificate["id"], admin))
    assert refreshed["reminder_tiers_sent"] == ["T_LAPSED"]


def test_compliance_run_expires_the_batch_and_leaves_the_ledger_untouched(api):
    """Phase one expires the stale batch; no phase of the run posts money.

    PRD: "Every batch whose `status` is `ACTIVE` or `DEPLETED` and whose
    `expires_at` falls strictly before `run_epoch` moves to `EXPIRED`."

    PRD: "No refund of any kind is posted for an expiry; only a deliberate void
    refunds money."

    Design: Difficulty/transitive_cascade/compliance_run_certificate_expiry_depth3_cascade_to_candidate_lapse
    """
    env = setup_sitting(stage="VERIFIED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    before = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert before["credit_balance_cents"] == 494738

    set_clock(env["certificate"]["expires_at"], admin)
    run_compliance(env)

    batch = get_success_data(api.get_access_code_batch(
        env["batch"]["id"], env["provider_headers"]))
    assert batch["status"] == "EXPIRED"
    assert batch["consumed_count"] == 1
    assert batch["available_count"] == 0
    assert batch["voided_count"] == 0

    after = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert after["credit_balance_cents"] == 494738
    assert after["lifetime_charged_cents"] == before["lifetime_charged_cents"]
    assert after["lifetime_credited_cents"] == before["lifetime_credited_cents"]
