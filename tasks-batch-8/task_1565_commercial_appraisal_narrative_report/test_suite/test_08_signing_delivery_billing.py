"""Signature gates, the delivery cascade, and compensating fee write-off
(PRD §2.8, §2.9, §3.8)."""
from test_helpers import (
    TEST_USERS,
    assert_timestamp_prefix,
    create_draft_report,
    create_in_progress_engagement,
    create_parties,
    make_mai_signer_headers,
    setup_delivered_engagement,
    setup_report_final,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]


def test_signer_not_mai_on_final_report(api):
    """PRD §3.8: "Signing moves the report from `FINAL` to `SIGNED` and is
    performed by the `MAISigner` role under three gates: the signing
    appraiser's `designation` must be `MAI` (`ERR_SIGNER_NOT_MAI_DESIGNATED`),
    their `license_status` must be `ACTIVE` (`ERR_SIGNER_LICENSE_INACTIVE`),
    and the signer must not be the engagement's author
    (`ERR_SEGREGATION_OF_DUTIES`)." A CERTIFIED_GENERAL caller fails the
    designation gate.

    Design: Corner/rbac/signer_not_mai_on_final_report
    """
    parties = create_parties(
        with_signer=False,
        extra_appraisers=[("Carl General", "CERTIFIED_GENERAL")])
    bundle = setup_report_final(parties)
    carl = bundle["extras"][0]
    res = api.sign_report(
        bundle["report"]["id"], make_mai_signer_headers(carl["id"]))
    validate_error(res, "ERR_SIGNER_NOT_MAI_DESIGNATED", expected_status=409)


def test_signer_license_inactive_rejected(api):
    """PRD §3.8: "their `license_status` must be `ACTIVE`
    (`ERR_SIGNER_LICENSE_INACTIVE`)" — an MAI signatory whose license was
    suspended before signing is rejected.

    Design: Corner/rbac/signer_license_inactive_rejected
    """
    parties = create_parties(with_signer=True)
    bundle = setup_report_final(parties)
    validate_success(api.set_license_status(
        parties["signer"]["id"], {"status": "SUSPENDED"}, EM), 200)
    res = api.sign_report(bundle["report"]["id"], bundle["signer_headers"])
    validate_error(res, "ERR_SIGNER_LICENSE_INACTIVE", expected_status=409)


def test_sod_signer_is_author_rejected(api):
    """PRD §3.8: "the signer must not be the engagement's author
    (`ERR_SEGREGATION_OF_DUTIES`)" — even an MAI-designated appraiser cannot
    sign the report they authored.

    Design: Corner/rbac/sod_signer_is_author_rejected
    """
    parties = create_parties(author_designation="MAI")
    bundle = setup_report_final(parties)
    res = api.sign_report(
        bundle["report"]["id"], make_mai_signer_headers(parties["author"]["id"]))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)


def test_sign_state_beats_safety_error(api):
    """PRD §2.9: "When several checks apply to a single request, they are
    evaluated in one fixed order, and the first failing check produces the
    response" — "The target resource must stand in a from-state the
    transition allows — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"
    (state validity, step 8) precedes the professional-independence safety
    gates (step 10). A signing call on a `DRAFTING` report by a TRAINEE
    caller therefore reports the state error, not
    `ERR_SIGNER_NOT_MAI_DESIGNATED`.

    Design: Difficulty/priority_pair_validation_conflict/sign_state_beats_safety
    """
    parties = create_parties(
        extra_appraisers=[("Tim Trainee", "TRAINEE")])
    bundle = create_in_progress_engagement(parties)
    report = create_draft_report(bundle)
    trainee = parties["extras"][0]
    res = api.sign_report(report["id"], make_mai_signer_headers(trainee["id"]))
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_sign_state_beats_safety_report_unchanged(api):
    """PRD §3.8: "Signing moves the report from `FINAL` to `SIGNED`" — a
    rejected signing attempt against a `DRAFTING` report (state validity,
    §2.9 step 8) leaves the report standing in `DRAFTING`.

    Design: Difficulty/priority_pair_validation_conflict/sign_state_beats_safety
    """
    parties = create_parties(
        extra_appraisers=[("Tim Trainee", "TRAINEE")])
    bundle = create_in_progress_engagement(parties)
    report = create_draft_report(bundle)
    trainee = parties["extras"][0]
    api.sign_report(report["id"], make_mai_signer_headers(trainee["id"]))
    after = validate_success(api.get_report(report["id"], EM), 200)
    assert after["status"] == "DRAFTING"


def test_delivery_cascade_completes_engagement_and_bills(api):
    """PRD §3.8: "Delivery fires a three-link cascade. First, the engagement
    itself moves from `IN_PROGRESS` to `COMPLETED` — the only path by which
    an engagement completes. Second, completion bills the client and opens
    the retention file: the client's `total_billed_cents` increases by the
    engagement's `final_fee_cents`, the client's `volume_discount_tier` is
    recomputed against the new total, and a RetentionRecord is created
    one-to-one with the engagement, standing `ACTIVE` with `completed_date`
    set to the calendar date of completion (at 00:00:00Z),
    `base_retain_until_date` set five years beyond that date — the USPAP
    retention floor — and `retain_until_date` initially equal to the base
    date." The STANDARD TIERED letter locks 450,000 cents, so the client
    moves 0 -> 450,000.

    Design: Difficulty/transitive_cascade/report_delivery_depth3_cascade
    """
    bundle = setup_delivered_engagement()
    report = validate_success(api.get_report(bundle["report"]["id"], EM), 200)
    assert report["status"] == "DELIVERED"
    eng = validate_success(
        api.get_engagement(bundle["engagement"]["id"], EM), 200)
    assert eng["status"] == "COMPLETED"
    client = validate_success(api.get_client(bundle["client"]["id"], EM), 200)
    assert client["total_billed_cents"] == 450000
    assert client["volume_discount_tier"] == "NONE"


def test_delivery_cascade_retention_record_and_workfile_freeze(api):
    """PRD §3.8: "a RetentionRecord is created one-to-one with the
    engagement, standing `ACTIVE` with `completed_date` set to the calendar
    date of completion (at 00:00:00Z), `base_retain_until_date` set five
    years beyond that date — the USPAP retention floor — and
    `retain_until_date` initially equal to the base date. Third, the workfile
    freezes: every data submission of the engagement still in `SUBMITTED` or
    `ACCEPTED` moves to `LOCKED`."

    Design: Difficulty/transitive_cascade/report_delivery_depth3_cascade
    """
    bundle = setup_delivered_engagement(extra_submission=True)
    record = bundle["retention_record"]
    assert record["status"] == "ACTIVE"
    assert_timestamp_prefix(record["completed_date"], "2026-08-01T00:00:00")
    assert_timestamp_prefix(record["base_retain_until_date"], "2031-08-01T00:00:00")
    assert_timestamp_prefix(record["retain_until_date"], "2031-08-01T00:00:00")
    sub = validate_success(
        api.get_data_submission(bundle["statement"]["id"], EM), 200)
    assert sub["status"] == "LOCKED", (
        "the ACCEPTED statement must freeze to LOCKED on completion")
    pending = validate_success(
        api.get_data_submission(bundle["pending_submission"]["id"], EM), 200)
    assert pending["status"] == "LOCKED", (
        "the still-SUBMITTED rent roll must freeze to LOCKED on completion")


def test_writeoff_roundtrip_conserves_billed_total(api):
    """PRD §3.8: "The `EngagementManager` may write off a completed
    engagement's fee, which subtracts `final_fee_cents` from the client's
    `total_billed_cents`, recomputes the volume tier, sets `fee_written_off`
    to true, and bumps the engagement's `version` — a field mutation on
    `COMPLETED`, not a state change." Delivery billed +450,000; the write-off
    returns the client to exactly 0.

    Design: Difficulty/compensating_invariant/client_billing_writeoff_roundtrip
    """
    bundle = setup_delivered_engagement()
    client_mid = validate_success(
        api.get_client(bundle["client"]["id"], EM), 200)
    assert client_mid["total_billed_cents"] == 450000

    eng_after = validate_success(
        api.write_off_fee(bundle["engagement"]["id"], EM), 200)
    assert eng_after["fee_written_off"] is True
    assert eng_after["status"] == "COMPLETED"
    client_end = validate_success(
        api.get_client(bundle["client"]["id"], EM), 200)
    assert client_end["total_billed_cents"] == 0, (
        "forward billing plus its compensating write-off must conserve the "
        f"client's billed total; expected 0, got {client_end['total_billed_cents']}")


def test_writeoff_fee_twice_rejected(api):
    """PRD §3.8: "A fee already written off rejects a second write-off with
    `ERR_FEE_ALREADY_WRITTEN_OFF`".

    Design: Difficulty/compensating_invariant/client_billing_writeoff_roundtrip
    """
    bundle = setup_delivered_engagement()
    validate_success(
        api.write_off_fee(bundle["engagement"]["id"], EM), 200)
    res = api.write_off_fee(bundle["engagement"]["id"], EM)
    validate_error(res, "ERR_FEE_ALREADY_WRITTEN_OFF", expected_status=409)
