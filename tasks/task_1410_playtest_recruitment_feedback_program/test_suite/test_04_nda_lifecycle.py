"""NDA signatures: signing bubble-up, expiry boundary, re-papering cascade."""
from test_helpers import (
    ApiErrorId,
    apply_to_study,
    approve_application,
    assert_instant_equals,
    create_nda,
    enroll_participant,
    get_pending_signature,
    get_study,
    get_success_data,
    make_participant_headers,
    register_participant,
    set_clock,
    setup_enrolled_participant,
    setup_study_with_published_nda,
    sign_signature,
    start_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]
LEGAL = TEST_USERS["legal_headers"]


def _setup_approved_with_pending_signature(email="sig-p@x.com"):
    """Participant APPROVED in a RECRUITING study; PENDING signature exists.

    Returns dict(study, nda, participant, application, signature)."""
    set_clock("2026-08-01T00:00:00Z")
    study, nda = setup_study_with_published_nda()
    participant = register_participant(email=email)
    app = start_review(apply_to_study(study["id"], participant["id"])["id"])
    app = approve_application(app["id"])
    sig = get_pending_signature(participant["id"])
    return {"study": study, "nda": nda, "participant": participant,
            "application": app, "signature": sig}


def test_sign_bubbles_application_to_enrolled(api):
    """PRD §3.3: "A successful signing moves the signature `PENDING` →
    `SIGNED`, stamps `signed_at`, and bubbles the gated application `APPROVED`
    → `ENROLLED`, incrementing the study's `enrolled_count` by one."
    PRD §3.2: "Enrollment itself is automatic: when the application's pending
    signature is signed (§3.3), the application bubbles `APPROVED` → `ENROLLED`
    and the study's `enrolled_count` increases by one."

    Design: Corner/state_machines/sign_bubbles_application_to_enrolled
    """
    ctx = _setup_approved_with_pending_signature(email="se2-p@x.com")
    pid = ctx["participant"]["id"]
    signed = sign_signature(ctx["signature"]["id"], pid)
    assert signed["status"] == "SIGNED"
    # signed_at is the signing instant, read from the logical clock (PRD §2.4).
    assert_instant_equals(signed["signed_at"], "2026-08-01T00:00:00Z", "signed_at")
    app = get_success_data(api.get_application(ctx["application"]["id"], RESEARCHER))
    assert app["status"] == "ENROLLED"
    assert get_study(ctx["study"]["id"])["enrolled_count"] == 1


def test_sign_signature_twice_returns_invalid_state(api):
    """PRD §3.3: "A successful signing moves the signature `PENDING` →
    `SIGNED`, stamps `signed_at`, and bubbles the gated application `APPROVED`
    → `ENROLLED`, incrementing the study's `enrolled_count` by one."
    PRD §2.9: "The generic rejection is `ERR_INVALID_STATE`"

    Design: Corner/state_machines/sign_signature_twice_returns_invalid_state
    """
    ctx = _setup_approved_with_pending_signature(email="id1-p@x.com")
    pid = ctx["participant"]["id"]
    signed = sign_signature(ctx["signature"]["id"], pid)
    assert signed["status"] == "SIGNED"
    resp = api.sign_nda_signature(ctx["signature"]["id"],
                                  make_participant_headers(pid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_study(ctx["study"]["id"])["enrolled_count"] == 1, (
        "the enrollment bubble-up fired exactly once")


def test_sign_at_exact_signature_expiry_rejected(api):
    """PRD §3.3: "the signing instant must fall strictly before `expires_at`,
    with an instant exactly equal to `expires_at` treated as expired
    (`ERR_SIGNATURE_EXPIRED`)"

    Design: Corner/validations/sign_at_exact_signature_expiry_rejected
    """
    ctx = _setup_approved_with_pending_signature(email="sx-p@x.com")
    # Signature created at 2026-08-01T00:00:00Z expires at +7 days.
    set_clock("2026-08-08T00:00:00Z")
    resp = api.sign_nda_signature(ctx["signature"]["id"],
                                  make_participant_headers(ctx["participant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SIGNATURE_EXPIRED)
    current = get_success_data(api.get_nda_signature(ctx["signature"]["id"], LEGAL))
    assert current["status"] == "PENDING", (
        "the failed sign changes nothing; only the expiry sweep flips it")


class TestNdaRepublishRepaperCascade:
    def test_republish_retires_old_agreement_and_voids_its_signature(self, api):
        """PRD §3.3: "The publish cascade runs three links: the previously
        `PUBLISHED` agreement for the same study, if any, becomes `RETIRED`
        (the only way an agreement leaves `PUBLISHED`); every signature on that
        retired agreement in `PENDING` or `SIGNED` becomes `VOIDED`"

        Design: Difficulty/transitive_cascade/nda_republish_repaper_cascade
        """
        ctx = setup_enrolled_participant(email="tc2-p@x.com")
        nda_v2 = create_nda(ctx["study"]["id"], version_label="v2",
                            body_text="NDA text v2 with tightened streaming clause")
        get_success_data(api.publish_nda_agreement(nda_v2["id"], LEGAL))
        old = get_success_data(api.get_nda_agreement(ctx["nda"]["id"], LEGAL))
        assert old["status"] == "RETIRED", "cascade link 1: prior published retires"
        old_sig = get_success_data(api.get_nda_signature(ctx["signature"]["id"], LEGAL))
        assert old_sig["status"] == "VOIDED", "cascade link 2: retired agreement's SIGNED signature voids"

    def test_republish_repapers_enrolled_application_to_approved(self, api):
        """PRD §3.3: "every application in `ENROLLED` whose signed signature
        was just voided reverts `ENROLLED` → `APPROVED`, decrementing the
        study's `enrolled_count` by one per reverted application, switching its
        `pinned_nda_agreement_id` to the newly published agreement, and
        receiving a fresh `PENDING` signature on the new version with a
        seven-day `expires_at`."

        Design: Difficulty/transitive_cascade/nda_republish_repaper_cascade
        """
        ctx = setup_enrolled_participant(email="tc2-p@x.com")
        assert get_study(ctx["study"]["id"])["enrolled_count"] == 1
        nda_v2 = create_nda(ctx["study"]["id"], version_label="v2",
                            body_text="NDA text v2 with tightened streaming clause")
        get_success_data(api.publish_nda_agreement(nda_v2["id"], LEGAL))
        app = get_success_data(api.get_application(ctx["application"]["id"], RESEARCHER))
        assert app["status"] == "APPROVED", "cascade link 3: ENROLLED reverts for re-papering"
        assert app["pinned_nda_agreement_id"] == nda_v2["id"], (
            "the pin switches to the newly published version")
        assert get_study(ctx["study"]["id"])["enrolled_count"] == 0
        fresh = get_pending_signature(ctx["participant"]["id"])
        assert fresh["agreement_id"] == nda_v2["id"]
        assert fresh["application_id"] == ctx["application"]["id"]
        assert fresh["status"] == "PENDING"
