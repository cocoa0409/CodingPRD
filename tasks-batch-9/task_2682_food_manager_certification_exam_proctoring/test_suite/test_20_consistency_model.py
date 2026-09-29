"""Immediate consistency: one write, and every derived projection is already correct
on the very next read with nothing in between."""
from test_helpers import (
    TEST_USERS,
    factories as f,
    get_success_data,
    read_batch,
    setup_sitting,
    validate_paginated,
)

_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]


def test_issuance_is_complete_in_its_own_response_and_in_every_next_read(api):
    """The POST answer already carries the projected window and the fee, and the four
    reads that follow it — with no intervening write and no clock move — already show
    the candidate, the ledger, the computed summary and the filtered list settled.

    PRD: "Consistency is immediate: there is no deferred queue, no eventual
    reconciliation, and no partial application."

    PRD: "`recert_window_opens_at` is `expires_at` moved back by 180 days."

    PRD: "`issuance_fee_cents` is set to 1,500 cents and that same amount is added to the
    `lifetime_charged_cents` of the provider named by the candidate's
    `training_provider_id`, with `credit_balance_cents` recomputed."

    PRD: "A dedicated computed read exposes the whole posture in one object for regulators
    and providers alike: it returns `candidate_id`, the current `compliance_status`, the
    `active_certificate_id`, that certificate's `certificate_expires_at` and
    `recert_window_opens_at`, the `local_registration_status` of its filing, the
    `reminder_tiers_sent` already dispatched against it, and an `open_incident_count`."

    Design: Corner/consistency_model/certificate_issuance_is_visible_in_its_own_response_and_in_every_immediate_read
    """
    env = setup_sitting(stage="CLOSED", start_at="2026-09-12T10:30:00Z",
                        scored_correct_count=60,
                        scoring_admin_headers=_SCORING_ADMIN)
    admin, candidate_id = env["admin_headers"], env["candidate"]["id"]
    report = env["score_report"]
    assert read_batch(env, env["batch"]["id"])["total_price_cents"] == 3762
    opening = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert opening["credit_balance_cents"] == 496238
    assert opening["lifetime_charged_cents"] == 3762
    assert report["status"] == "FINAL"
    assert report["provisional_scaled_score"] == 75
    assert report["final_scaled_score"] == 75
    assert report["pass_flag"] is True

    certificate = get_success_data(api.create_certificate(
        f.create_certificate_payload(report["id"]), admin), 201)

    assert certificate["status"] == "ISSUED"
    assert isinstance(certificate["certificate_number"], str)
    assert certificate["certificate_number"] != ""
    assert certificate["issued_at"] == "2026-09-12T10:30:00Z"
    assert certificate["expires_at"] == "2031-09-12T10:30:00Z"
    assert certificate["recert_window_opens_at"] == "2031-03-16T10:30:00Z"
    assert certificate["issuance_fee_cents"] == 1500
    assert certificate["reminder_tiers_sent"] == []

    assert get_success_data(api.get_candidate(
        candidate_id, admin))["compliance_status"] == "CERTIFIED"

    ledger = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert ledger["lifetime_credited_cents"] == 500000
    assert ledger["lifetime_charged_cents"] == 5262
    assert ledger["credit_balance_cents"] == 494738

    summary = get_success_data(api.get_compliance_summary(
        candidate_id, env["officer_headers"]))
    assert summary["candidate_id"] == candidate_id
    assert summary["compliance_status"] == "CERTIFIED"
    assert summary["active_certificate_id"] == certificate["id"]
    assert summary["certificate_expires_at"] == "2031-09-12T10:30:00Z"
    assert summary["recert_window_opens_at"] == "2031-03-16T10:30:00Z"
    assert summary["reminder_tiers_sent"] == []
    assert summary["open_incident_count"] == 0

    listed, meta = validate_paginated(api.list_certificates(
        admin, params={"candidate_id": candidate_id}))
    assert meta["total_count"] == 1
    assert listed[0]["id"] == certificate["id"]
