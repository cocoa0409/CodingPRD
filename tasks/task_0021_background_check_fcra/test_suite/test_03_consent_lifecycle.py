"""Consent grant idempotency, revoke cascade, revoke too late, open-interval
uniqueness, consent-not-granted gate at order creation.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_jurisdiction, create_applicant, create_application,
    application_in_submitted, application_in_conditional_offer,
    order_with_three_pending_verifications,
    make_applicant_headers, make_recruiter_headers,
    api_client,
)


def test_grant_consent_when_already_granted_returns_invalid_state(api):
    """Granting an already-GRANTED consent is rejected with ERR_INVALID_STATE
    because PRD §3.2 says granting is only valid from PENDING.

    PRD §3.2: "Granting is only valid from `PENDING`, and only when
    `signed_at` is at or before the system clock's `current_utc` (no
    future-dated grants). On success the consent advances from `PENDING`
    to `GRANTED`, its `version` is incremented, and an audit row with
    action `CONSENT_GRANT` is appended."
    PRD §2.9: "Then the target entity must be in a state from which the
    requested transition is legal (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/consent_grant_idempotency_rejects_second_attempt
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="RI")
    applicant = create_applicant(full_name="Rosalind Franklin", email="rosalind@example.com",
                                 date_of_birth="1920-07-25T00:00:00.000Z")
    app = create_application(applicant["id"], jur["id"], position_title="Scientist")
    c_resp = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:00.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    consent = validate_success(c_resp, 201)
    granted = validate_success(
        api.grant_consent(consent["id"],
                          {"expected_consent_disclosure_version": consent["version"]},
                          make_applicant_headers(applicant["id"])),
        200,
    )
    # Second grant on an already-GRANTED consent → ERR_INVALID_STATE.
    resp = api.grant_consent(
        consent["id"],
        {"expected_consent_disclosure_version": granted["version"]},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_revoke_consent_cascade_cancels_pending_order_and_pending_verifications(api):
    """Revoking a GRANTED consent while the child order is in PENDING
    cascades: the order moves to CANCELLED, each PENDING child Verification
    moves to RESOLVED with result=null.

    PRD §3.2: "When the revoke is permitted, the consent transitions from
    `GRANTED` to `REVOKED`; if a `PENDING` order existed against this
    consent, it cascade-cancels to `CANCELLED`, and each of that order's
    `PENDING` `Verification` children transitions to `RESOLVED` with
    `result` left null, with every touched row's `version` incremented."

    Design: Corner/state_machines/consent_revoke_cascade_cancels_pending_order
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(state_code="SC")
    # Read current consent version (grant bumped it once during fixture).
    consent_now = validate_success(api.get_consent(consent["id"],
                                                    make_applicant_headers(applicant["id"])),
                                    200)
    api.revoke_consent(
        consent["id"],
        {"expected_consent_disclosure_version": consent_now["version"]},
        make_applicant_headers(applicant["id"]),
    )
    order_after = validate_success(api.get_order(order["id"],
                                                  make_recruiter_headers("rec-001")), 200)
    assert order_after["status"] == "CANCELLED", \
        f"order must cascade to CANCELLED after consent revoke, got {order_after['status']!r}"
    crim_after = validate_success(api.get_verification(crim["id"],
                                                       make_recruiter_headers("rec-001")), 200)
    assert crim_after["status"] == "RESOLVED", \
        f"PENDING verifications must cascade to RESOLVED, got {crim_after['status']!r}"
    assert crim_after["result"] is None, \
        f"cascade-resolved verifications must have result=null, got {crim_after['result']!r}"


def test_revoke_consent_after_order_in_review_returns_too_late(api):
    """If a child BackgroundCheckOrder has reached IN_REVIEW (at least one
    Verification has reported) the consent revoke is rejected with
    ERR_CONSENT_REVOKE_TOO_LATE.

    PRD §3.2: "If any `BackgroundCheckOrder` tied to the consent has
    reached `IN_REVIEW` or `COMPLETE`, the revoke is rejected with
    `ERR_CONSENT_REVOKE_TOO_LATE`."

    Design: Corner/state_machines/consent_revoke_too_late_when_order_in_review
    """
    from test_helpers.fixtures import report_verification
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(state_code="KY")
    # Report ONE verification — drives order PENDING -> IN_REVIEW.
    report_verification(crim["id"], "PASS", crim["version"])
    # Re-fetch consent for its current version (grant bumped it once).
    consent_now = validate_success(
        api.get_consent(consent["id"], make_applicant_headers(applicant["id"])), 200,
    )
    resp = api.revoke_consent(
        consent["id"],
        {"expected_consent_disclosure_version": consent_now["version"]},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_REVOKE_TOO_LATE.value)


def test_open_consent_uniqueness_per_application_rejected_then_succeeds_after_revoke(api):
    """At most one consent per application may be open (PENDING or GRANTED)
    at a time. A second POST /consents while one is open returns
    ERR_CONSENT_ALREADY_OPEN. Once the first is revoked, a new consent
    succeeds.

    PRD §3.2: "At most one consent per `application_id` may be open at a
    time — that is, at most one consent with `consent_status` in `PENDING`
    or `GRANTED`. A second consent opened against an application that
    already has an open consent is rejected with `ERR_CONSENT_ALREADY_OPEN`."

    Design: Difficulty/resource_temporal_overlap/consent_open_interval_per_application_no_overlap
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="CO")
    applicant = create_applicant(full_name="John von Neumann", email="jvn@example.com",
                                 date_of_birth="1903-12-28T00:00:00.000Z")
    app = create_application(applicant["id"], jur["id"], position_title="Engineer")
    c1_resp = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:00.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    c1 = validate_success(c1_resp, 201)
    granted = validate_success(
        api.grant_consent(c1["id"],
                          {"expected_consent_disclosure_version": c1["version"]},
                          make_applicant_headers(applicant["id"])),
        200,
    )
    # Second consent while c1 is GRANTED → rejected.
    overlap = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:01.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(overlap, ApiErrorId.ERR_CONSENT_ALREADY_OPEN.value)
    # Revoke first, then second succeeds.
    api.revoke_consent(c1["id"],
                       {"expected_consent_disclosure_version": granted["version"]},
                       make_applicant_headers(applicant["id"]))
    c2_resp = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:02.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    c2 = validate_success(c2_resp, 201)
    assert c2["consent_status"] == "PENDING", \
        f"replacement consent must start PENDING, got {c2['consent_status']!r}"


def test_order_create_with_pending_consent_returns_consent_not_granted(api):
    """An order created against a PENDING (not-yet-GRANTED) consent is
    rejected with ERR_CONSENT_NOT_GRANTED. Once the consent is granted,
    the same call succeeds.

    PRD §3.3: "The referenced consent must satisfy two conditions: its
    `consent_status` must be `GRANTED`, and its applicant chain — the
    consent's `application_id` resolves to an application whose
    `applicant_id` matches the order's application's `applicant_id` — must
    match the order's application. A consent that is not granted, or that
    belongs to a different applicant, is rejected with
    `ERR_CONSENT_NOT_GRANTED`."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_consent_granted_state
    """
    # Walk to CONDITIONAL_OFFER (NY, no BTB so no §3.3 ban-the-box gate fires).
    jur, applicant, app, consent = application_in_conditional_offer(
        state_code="NY", ban_the_box_enabled=False,
    )
    # The fixture has c1 in GRANTED; revoke it then open a fresh PENDING consent.
    consent_now = validate_success(api.get_consent(consent["id"],
                                                    make_applicant_headers(applicant["id"])),
                                    200)
    api.revoke_consent(consent["id"],
                       {"expected_consent_disclosure_version": consent_now["version"]},
                       make_applicant_headers(applicant["id"]))
    new_consent_resp = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:00.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    new_consent = validate_success(new_consent_resp, 201)
    # Order with the PENDING consent → ERR_CONSENT_NOT_GRANTED.
    bad_resp = api.create_order(
        {"application_id": app["id"], "consent_id": new_consent["id"],
         "expected_application_version": app["version"]},
        make_recruiter_headers("rec-jane"),
    )
    validate_error(bad_resp, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)
    # Grant the new consent, then retry → succeeds.
    granted = validate_success(
        api.grant_consent(new_consent["id"],
                          {"expected_consent_disclosure_version": new_consent["version"]},
                          make_applicant_headers(applicant["id"])),
        200,
    )
    ok = api.create_order(
        {"application_id": app["id"], "consent_id": new_consent["id"],
         "expected_application_version": app["version"]},
        make_recruiter_headers("rec-jane"),
    )
    order = validate_success(ok, 201)
    assert order["status"] == "PENDING", \
        f"order with GRANTED consent must start PENDING, got {order['status']!r}"
