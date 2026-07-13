"""Transfer requests: the submission gauntlet, the bounded EPP negotiation cycle."""
from test_helpers import (
    PLATFORM,
    ApiErrorId,
    get_domain,
    get_transfer_request,
    make_registrant_headers,
    report_under_review,
    setup_inbound_transfer,
    setup_outbound_transfer,
    validate_error,
    validate_success,
)


def _reject(api, transfer_id, reason="bad auth"):
    return api.registry_response(
        transfer_id, {"outcome": "REJECTED", "reason": reason}, PLATFORM
    )


# =========================================================================
# The negotiation cycle  (Difficulty/non_linear_state_machine)
# =========================================================================

def test_registry_rejection_then_retry_re_arms_the_request(api):
    """PRD §3.7: "When the registry rejects while `attempt_count` is still below the ceiling
    of three attempts, the request moves `PENDING_ACK → REJECTED` and stores the registry's
    `reason` in `rejection_reason`."
    PRD §3.7: "The `Registrant` may then retry, supplying a fresh `epp_auth_code`: the
    request moves `REJECTED → INITIATED`, the new code replaces the old one,
    `rejection_reason` is cleared back to null, and the whole submission gauntlet can be run
    again."

    Design: Difficulty/non_linear_state_machine/transfer_request_rejected_then_retried_then_completed_cycle
    """
    account, transfer = setup_inbound_transfer(epp_auth_code="EPP-WRONG-01")
    headers = make_registrant_headers(account["id"])

    submitted = validate_success(api.submit_transfer_request(transfer["id"], headers))
    assert submitted["status"] == "PENDING_ACK"
    assert submitted["attempt_count"] == 1

    rejected = validate_success(
        _reject(api, transfer["id"], "auth code rejected by losing registrar")
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "auth code rejected by losing registrar"

    retried = validate_success(
        api.retry_transfer_request(
            transfer["id"], {"epp_auth_code": "EPP-CORRECT-02"}, headers
        )
    )
    assert retried["status"] == "INITIATED"
    assert retried["epp_auth_code"] == "EPP-CORRECT-02"
    assert retried["rejection_reason"] is None


def test_inbound_approval_after_a_retry_completes_the_cycle_and_mints_the_domain(api):
    """PRD §3.7: "An approval on an inbound request moves it `PENDING_ACK → COMPLETED` and
    mints a brand-new `Domain` owned by the request's `account_id`: `lifecycle_status`
    `ACTIVE`, `lock_status` `LOCKED`, `registered_at` at the logical clock now, `expires_at`
    at now plus 365 days, a freshly minted `epp_auth_code`, and the request's `domain_id`
    pointed at it."
    PRD §3.7: "A submission that clears all five moves the request `INITIATED → PENDING_ACK`
    and increments `attempt_count` by one."

    Design: Difficulty/non_linear_state_machine/transfer_request_rejected_then_retried_then_completed_cycle
    """
    account, transfer = setup_inbound_transfer(epp_auth_code="EPP-WRONG-01")
    headers = make_registrant_headers(account["id"])

    validate_success(api.submit_transfer_request(transfer["id"], headers))
    _reject(api, transfer["id"])
    validate_success(
        api.retry_transfer_request(
            transfer["id"], {"epp_auth_code": "EPP-CORRECT-02"}, headers
        )
    )
    validate_success(api.submit_transfer_request(transfer["id"], headers))

    approved = validate_success(
        api.registry_response(transfer["id"], {"outcome": "APPROVED"}, PLATFORM)
    )
    assert approved["status"] == "COMPLETED"
    assert approved["attempt_count"] == 2, "attempt_count is incremented on each submit"
    assert approved["domain_id"] is not None

    minted = get_domain(approved["domain_id"], account)
    assert minted["lifecycle_status"] == "ACTIVE"
    assert minted["lock_status"] == "LOCKED"
    assert minted["account_id"] == account["id"]
    assert isinstance(minted["epp_auth_code"], str)


# =========================================================================
# Submission is gated on the lock dimension  (Difficulty/cross_entity)
# =========================================================================

def test_outbound_submit_on_a_locked_domain_is_rejected(api):
    """PRD §3.7: "Third: the domain's `lock_status` must be `UNLOCKED`, or the answer is
    `ERR_DOMAIN_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/transfer_out_submission_depends_on_domain_lock_status
    """
    account, domain, transfer = setup_outbound_transfer()
    headers = make_registrant_headers(account["id"])

    assert domain["lock_status"] == "LOCKED"

    resp = api.submit_transfer_request(transfer["id"], headers)
    validate_error(resp, ApiErrorId.ERR_DOMAIN_LOCKED.value, 409)

    unchanged = get_transfer_request(transfer["id"], account)
    assert unchanged["status"] == "INITIATED"
    assert unchanged["attempt_count"] == 0, "a rejected submit does not count as an attempt"


def test_unlocking_the_domain_lets_the_same_outbound_submit_through(api):
    """PRD §3.7: "Third: the domain's `lock_status` must be `UNLOCKED`, or the answer is
    `ERR_DOMAIN_LOCKED`."
    PRD §3.7: "A submission that clears all five moves the request `INITIATED → PENDING_ACK`
    and increments `attempt_count` by one."

    Design: Difficulty/cross_entity_state_dependency/transfer_out_submission_depends_on_domain_lock_status
    """
    account, domain, transfer = setup_outbound_transfer()
    headers = make_registrant_headers(account["id"])

    blocked = api.submit_transfer_request(transfer["id"], headers)
    assert blocked.status_code == 409

    unlocked = validate_success(
        api.update_domain_settings(domain["id"], {"locked": False}, headers)
    )
    assert unlocked["lock_status"] == "UNLOCKED"
    assert unlocked["lifecycle_status"] == "ACTIVE"

    submitted = validate_success(api.submit_transfer_request(transfer["id"], headers))
    assert submitted["status"] == "PENDING_ACK"
    assert submitted["attempt_count"] == 1


# =========================================================================
# Abuse hold beats the registrar lock  (Difficulty/priority_pair)
# =========================================================================

def test_abuse_hold_is_reported_ahead_of_the_registrar_lock(api):
    """PRD §3.7: "Second — **and this is checked before the lock** — the domain must be free
    of any abuse hold: a `suspension_reason` of `ABUSE`, or *any* `AbuseReport` on that domain
    whose `status` is `UNDER_REVIEW` or `UPHELD`, blocks the transfer with
    `ERR_ABUSE_HOLD_ACTIVE`."
    PRD §2.8: "Two orderings are called out explicitly there because they are easy to get
    backwards: on an outbound transfer submission the abuse hold is checked before the
    registrar lock, and inside the promotion engine the eligibility gate is checked before the
    minimum-subtotal gate."

    The domain is still LOCKED, so `ERR_DOMAIN_LOCKED` also applies — the abuse hold wins.

    Design: Difficulty/priority_pair_validation_conflict/abuse_hold_check_beats_registrar_lock_check_on_transfer_out
    """
    account, domain, transfer = setup_outbound_transfer()
    headers = make_registrant_headers(account["id"])
    report_under_review(domain, severity="HIGH", category="MALWARE")

    resp = api.submit_transfer_request(transfer["id"], headers)

    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ABUSE_HOLD_ACTIVE.value, 409)


def test_a_blocked_abuse_hold_submission_leaves_the_request_and_the_domain_untouched(api):
    """PRD §3.7: "Second — **and this is checked before the lock** — the domain must be free
    of any abuse hold: a `suspension_reason` of `ABUSE`, or *any* `AbuseReport` on that domain
    whose `status` is `UNDER_REVIEW` or `UPHELD`, blocks the transfer with
    `ERR_ABUSE_HOLD_ACTIVE`."
    PRD §3.9: "An `AbuseAnalyst` takes an `OPEN` report into review, moving it
    `OPEN → UNDER_REVIEW` and recording their own `X-User-ID` as the report's
    `reviewer_user_id`."

    Design: Difficulty/priority_pair_validation_conflict/abuse_hold_check_beats_registrar_lock_check_on_transfer_out
    """
    account, domain, transfer = setup_outbound_transfer()
    headers = make_registrant_headers(account["id"])
    report_under_review(domain, severity="HIGH", category="MALWARE")

    api.submit_transfer_request(transfer["id"], headers)

    unchanged = get_transfer_request(transfer["id"], account)
    assert unchanged["status"] == "INITIATED"
    assert unchanged["attempt_count"] == 0

    still = get_domain(domain["id"], account)
    assert still["lifecycle_status"] == "ACTIVE", (
        "an UNDER_REVIEW report does not suspend the domain — only an uphold does"
    )
    assert still["lock_status"] == "LOCKED"


# =========================================================================
# Corner instances
# =========================================================================

def test_third_registry_rejection_lands_the_request_in_terminal_failed(api):
    """PRD §3.7: "When the registry rejects a request whose `attempt_count` has already
    reached three, the request does not become `REJECTED` at all — it goes straight to
    `FAILED`, which is terminal and cannot be retried, with the `reason` recorded in
    `rejection_reason`."
    PRD §3.7: "Retrying from any state other than `REJECTED` is `ERR_TRANSFER_INVALID_STATE`,
    and retrying once `attempt_count` has reached three is refused with
    `ERR_TRANSFER_MAX_ATTEMPTS`."

    Design: Corner/state_machines/transfer_request_reaches_failed_after_third_rejection
    """
    account, transfer = setup_inbound_transfer(epp_auth_code="EPP-1")
    headers = make_registrant_headers(account["id"])

    for code in ("EPP-2", "EPP-3"):
        validate_success(api.submit_transfer_request(transfer["id"], headers))
        validate_success(_reject(api, transfer["id"]))
        validate_success(
            api.retry_transfer_request(transfer["id"], {"epp_auth_code": code}, headers)
        )

    third = validate_success(api.submit_transfer_request(transfer["id"], headers))
    assert third["attempt_count"] == 3

    failed = validate_success(_reject(api, transfer["id"], "final rejection"))
    assert failed["status"] == "FAILED"
    assert failed["attempt_count"] == 3
    assert failed["rejection_reason"] == "final rejection"

    resp = api.retry_transfer_request(
        transfer["id"], {"epp_auth_code": "EPP-4"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_TRANSFER_MAX_ATTEMPTS.value, 409)

    assert get_transfer_request(transfer["id"], account)["status"] == "FAILED"


def test_outbound_submit_with_the_wrong_epp_auth_code_is_rejected(api):
    """PRD §3.7: "Fifth: the `epp_auth_code` on the request must equal the domain's own
    `epp_auth_code`, or the answer is `ERR_EPP_AUTH_MISMATCH`."

    Design: Corner/validations/transfer_out_with_wrong_epp_auth_code_rejected
    """
    account, domain, transfer = setup_outbound_transfer(
        unlock=True, epp_auth_code="EPP-BOGUS"
    )
    headers = make_registrant_headers(account["id"])

    resp = api.submit_transfer_request(transfer["id"], headers)
    validate_error(resp, ApiErrorId.ERR_EPP_AUTH_MISMATCH.value, 409)

    unchanged = get_transfer_request(transfer["id"], account)
    assert unchanged["status"] == "INITIATED"
    assert unchanged["attempt_count"] == 0
    assert get_domain(domain["id"], account)["lifecycle_status"] == "ACTIVE"


def test_retrying_an_initiated_transfer_request_is_rejected(api):
    """PRD §3.7: "Retrying from any state other than `REJECTED` is
    `ERR_TRANSFER_INVALID_STATE`, and retrying once `attempt_count` has reached three is
    refused with `ERR_TRANSFER_MAX_ATTEMPTS`."

    Design: Corner/errors/error_transfer_invalid_state_trigger
    """
    account, transfer = setup_inbound_transfer(epp_auth_code="EPP-1")
    headers = make_registrant_headers(account["id"])

    resp = api.retry_transfer_request(
        transfer["id"], {"epp_auth_code": "EPP-2"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE.value, 409)

    unchanged = get_transfer_request(transfer["id"], account)
    assert unchanged["status"] == "INITIATED"
    assert unchanged["epp_auth_code"] == "EPP-1"
    assert unchanged["attempt_count"] == 0
