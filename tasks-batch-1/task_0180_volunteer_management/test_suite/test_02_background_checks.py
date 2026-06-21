"""Background-check lifecycle and the tier ladder: clear/expiry divergence, the
IN_PROGRESS fork + EXPIRED->INITIATED renewal cycle, valid_until computation,
invalid-decision rejection, and tier conservation under a rejected check.

Queue A (Difficulty): dual_variant_calc, non_linear_state_machine, compensating_invariant.
Queue B (Corner): calculations, errors.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    create_organization, create_volunteer, set_clock, get_volunteer,
    create_cleared_background_check, create_in_progress_background_check,
)
from test_helpers.test_users import TEST_USERS

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_bg_tier_diverges_before_and_after_lazy_expiry(api):
    """PRD §3.2: "A volunteer's `bg_check_tier` is always the highest `requested_tier`,
    by rank, among that volunteer's background checks that are both `CLEARED` and not
    expired against the current clock; if no such check exists, the tier is `NONE`."
    PRD §3.2: "whenever a volunteer is read or their signup eligibility is being
    evaluated, any `CLEARED` check whose `valid_until` is now strictly before the
    current clock transitions from `CLEARED` to `EXPIRED`, after which the server
    recomputes the volunteer's `bg_check_tier` over the remaining cleared, non-expired
    checks — possibly lowering it — and increments the volunteer's `version`."

    Design: Difficulty/dual_variant_calc/bg_tier_before_vs_after_lazy_expiry_diverges_on_volunteer
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    # CLEARED STANDARD with validity 1 day at clock 2026-06-15 -> valid_until 2026-06-16.
    create_cleared_background_check(org, vol, "STANDARD", validity_days=1, admin=COMPLIANCE)

    before = get_volunteer(vol["id"], headers=COMPLIANCE)
    assert before["bg_check_tier"] == "STANDARD", \
        f"before expiry expected STANDARD, got {before['bg_check_tier']}"

    set_clock("2026-06-17T00:00:00Z", headers=COMPLIANCE)
    after = get_volunteer(vol["id"], headers=COMPLIANCE)
    assert after["bg_check_tier"] == "NONE", \
        f"after lazy expiry expected NONE, got {after['bg_check_tier']}"


def test_valid_until_computed_from_validity_days(api):
    """PRD §3.6/§3.2: "the server stamps `cleared_at` with the current clock and
    computes `valid_until` as `cleared_at` plus the validity window converted to
    seconds — that is, `validity_days` multiplied by 86,400 seconds per day, added to
    `cleared_at`, expressed in UTC to the millisecond."

    Design: Difficulty/dual_variant_calc/bg_tier_before_vs_after_lazy_expiry_diverges_on_volunteer
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    chk = create_cleared_background_check(org, vol, "BASIC", validity_days=365, admin=COMPLIANCE)
    assert chk["cleared_at"].startswith("2026-06-15T00:00:00"), \
        f"cleared_at should be the decide clock, got {chk['cleared_at']}"
    assert chk["valid_until"].startswith("2027-06-15T00:00:00"), \
        f"valid_until should be cleared_at + 365 days, got {chk['valid_until']}"


def test_bg_check_branch_and_renewal_cycle(api):
    """PRD §3.2: "An expired check is not dead: renewing it moves it from `EXPIRED`
    back to `INITIATED`, clearing both `cleared_at` and `valid_until` so the lifecycle
    can run again, and optionally accepting a fresh `validity_days`."

    Design: Difficulty/non_linear_state_machine/background_check_branch_and_renewal_cycle
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    chk = create_cleared_background_check(org, vol, "STANDARD", validity_days=1, admin=COMPLIANCE)

    # Advance past valid_until; lazy expiry triggers on the next read.
    set_clock("2026-06-17T00:00:00Z", headers=COMPLIANCE)
    get_volunteer(vol["id"], headers=COMPLIANCE)  # forces lazy expiry recompute
    expired = validate_success(api.get_background_check(chk["id"], COMPLIANCE))
    assert expired["status"] == "EXPIRED", f"expected EXPIRED, got {expired['status']}"

    renewed = validate_success(api.renew_background_check(chk["id"], {}, COMPLIANCE))
    assert renewed["status"] == "INITIATED", f"after renew expected INITIATED, got {renewed['status']}"
    assert renewed["cleared_at"] is None, "renew clears cleared_at"


def test_renew_non_expired_check_rejected(api):
    """PRD §3.2: "renewing a check that is not `EXPIRED` is rejected with
    `ERR_BG_CHECK_NOT_EXPIRED`."

    Design: Difficulty/non_linear_state_machine/background_check_branch_and_renewal_cycle
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    chk = create_cleared_background_check(org, vol, "STANDARD", validity_days=365, admin=COMPLIANCE)
    # Still CLEARED (well within validity) — renew must reject.
    resp = api.renew_background_check(chk["id"], {}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_BG_CHECK_NOT_EXPIRED.value)


def test_bg_reject_leaves_volunteer_tier_unchanged(api):
    """PRD §3.2: "When a check is decided `REJECTED` (moving `IN_PROGRESS` to
    `REJECTED`, a terminal state), the server still recomputes the volunteer's
    `bg_check_tier` — which is unchanged unless that check had been the sole source of
    a tier — and increments the volunteer's `version`."

    Design: Difficulty/compensating_invariant/bg_reject_leaves_volunteer_tier_unchanged
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    create_cleared_background_check(org, vol, "STANDARD", admin=COMPLIANCE)

    before = get_volunteer(vol["id"], headers=COMPLIANCE)
    assert before["bg_check_tier"] == "STANDARD", \
        f"after STANDARD clear expected STANDARD, got {before['bg_check_tier']}"

    # A second, lower BASIC check is opened then REJECTED.
    chk2 = create_in_progress_background_check(vol["id"], "BASIC", admin=COMPLIANCE)
    cur = get_volunteer(vol["id"], headers=COMPLIANCE)
    validate_success(api.decide_background_check(
        chk2["id"],
        {"decision": "REJECTED", "expected_volunteer_version": cur["version"]},
        COMPLIANCE))

    after = get_volunteer(vol["id"], headers=COMPLIANCE)
    assert after["bg_check_tier"] == "STANDARD", \
        f"rejected check must not drift the tier; expected STANDARD, got {after['bg_check_tier']}"


def test_bg_reject_at_lower_tier_keeps_max_rank(api):
    """PRD §3.2: "A volunteer's `bg_check_tier` is always the highest `requested_tier`,
    by rank, among that volunteer's background checks that are both `CLEARED` and not
    expired against the current clock."
    PRD §3.2: "the server still recomputes the volunteer's `bg_check_tier` — which is
    unchanged unless that check had been the sole source of a tier."

    Design: Difficulty/compensating_invariant/bg_reject_leaves_volunteer_tier_unchanged
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    # Cleared at ENHANCED (the max).
    create_cleared_background_check(org, vol, "ENHANCED", admin=COMPLIANCE)
    before = get_volunteer(vol["id"], headers=COMPLIANCE)
    assert before["bg_check_tier"] == "ENHANCED"

    # A lower BASIC check is opened then REJECTED; ENHANCED (max rank) is conserved.
    chk2 = create_in_progress_background_check(vol["id"], "BASIC", admin=COMPLIANCE)
    cur = get_volunteer(vol["id"], headers=COMPLIANCE)
    validate_success(api.decide_background_check(
        chk2["id"], {"decision": "REJECTED", "expected_volunteer_version": cur["version"]},
        COMPLIANCE))
    after = get_volunteer(vol["id"], headers=COMPLIANCE)
    assert after["bg_check_tier"] == "ENHANCED", \
        f"rejecting a lower check must keep the max-rank tier; expected ENHANCED, got {after['bg_check_tier']}"


def test_bg_check_expiry_valid_until_default_365(api):
    """PRD §3.2: "the server stamps `cleared_at` with the current clock and computes
    `valid_until` as `cleared_at` plus the validity window converted to seconds — that
    is, `validity_days` multiplied by 86,400 seconds per day, added to `cleared_at`,
    expressed in UTC to the millisecond."

    Design: Corner/calculations/bg_check_expiry_valid_until_computed
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    chk = create_cleared_background_check(org, vol, "BASIC", admin=COMPLIANCE)  # default 365
    assert chk["cleared_at"] == "2026-06-15T00:00:00.000Z", \
        f"expected cleared_at 2026-06-15T00:00:00.000Z, got {chk['cleared_at']}"
    assert chk["valid_until"] == "2027-06-15T00:00:00.000Z", \
        f"expected valid_until 2027-06-15T00:00:00.000Z, got {chk['valid_until']}"


def test_invalid_bg_decision_value_rejected(api):
    """PRD §3.2: "Deciding a check carries a `decision` field that must be either
    `CLEARED` or `REJECTED`; any other value is rejected with `ERR_INVALID_BG_DECISION`."

    Design: Corner/errors/invalid_bg_decision_value_rejected
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    chk = create_in_progress_background_check(vol["id"], "BASIC", admin=COMPLIANCE)
    cur = get_volunteer(vol["id"], headers=COMPLIANCE)
    resp = api.decide_background_check(
        chk["id"], {"decision": "MAYBE", "expected_volunteer_version": cur["version"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_BG_DECISION.value)
