"""Credential findings, the remediation regression loop and the six-step
hygiene score."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_credential_finding, assert_same_instant, fixtures as fx,
)


def test_a_finding_cycles_open_remediated_open_and_the_score_follows(api):
    """PRD §3.7: "Findings move `OPEN → REMEDIATED` when the household fixes the credential
    — an action for the `AccountOwner` or a `Member`, stamping `remediated_at` — and back
    `REMEDIATED → OPEN` when a `PrivacyAgent` observes the credential weak again on a later
    sweep, which clears `remediated_at` to null."
    PRD §3.7: "The **raw penalty** is the sum of the per-type weights over every credential
    finding on this profile whose status is `OPEN`. The weights are 25 for
    `BREACHED_PASSWORD`, 18 for `WEAK_PASSWORD`, 12 for `REUSED_PASSWORD` and 7 for
    `STALE_PASSWORD`. Findings in `REMEDIATED` leave the input set entirely and are not
    partially credited."

    Design: Corner/state_machines/credential_finding_remediate_then_reopen_rescoring_cycle
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)
    finding = fx.add_credential_finding(profile["id"], "BREACHED_PASSWORD",
                                        detail="mail vault")
    assert_credential_finding(finding)

    before = fx.read_hygiene(profile["id"], household["owner"])
    # One OPEN BREACHED_PASSWORD: raw 25, cap min(25, 70) = 25, multiplier 1.00,
    # score 100 - 25.00 = 75.00, which is at or above 60 and below 80 -> MODERATE.
    assert before["open_finding_count"] == 1
    assert float(before["hygiene_score"]) == 75.00
    assert before["hygiene_band"] == "MODERATE"
    assert validate_success(
        api.get_credential_finding(finding["id"], household["owner"]))["weight"] == 25

    remediated = validate_success(api.remediate_finding(finding["id"],
                                                        household["owner"]))
    assert remediated["status"] == "REMEDIATED"
    assert_same_instant(remediated["remediated_at"], "2026-05-01T00:00:00Z",
                        "remediated_at")
    mid = fx.read_hygiene(profile["id"], household["owner"])
    assert mid["open_finding_count"] == 0
    assert float(mid["hygiene_score"]) == 100.00
    assert mid["hygiene_band"] == "STRONG"

    reopened = validate_success(api.reopen_finding(finding["id"], fx.AGENT))
    assert reopened["status"] == "OPEN"
    assert reopened["remediated_at"] is None
    assert reopened["weight"] == 25
    after = fx.read_hygiene(profile["id"], household["owner"])
    assert float(after["hygiene_score"]) == 75.00
    assert after["hygiene_band"] == "MODERATE"


def test_the_penalty_cap_bites_before_the_two_factor_multiplier(api):
    """PRD §3.7: "The **capped penalty** is the lesser of the raw penalty and 70."
    PRD §3.7: "Because the cap bites before the multiplier rather than after it, a
    household with a very large stack of open findings and a two-factor attestation is
    scored on 70 points of penalty reduced to 42, not on the full stack reduced by 40 per
    cent — and because the multiplier is applied to an already-capped figure, flipping the
    attestation on an identical finding set can move a profile across two band boundaries
    at once."

    Design: Corner/calculations/hygiene_penalty_cap_is_applied_before_the_two_factor_multiplier
    """
    household = fx.open_household()
    profile = fx.draft_profile(household, two_factor_attested=False)
    for detail in ("store A", "store B", "store C"):
        fx.add_credential_finding(profile["id"], "BREACHED_PASSWORD", detail=detail)

    without = validate_success(api.get_hygiene_score(profile["id"], household["owner"]))
    # raw = 3 * 25 = 75; capped = min(75, 70) = 70; multiplier 1.00 -> 70.00.
    assert without["raw_penalty"] == 75
    assert without["capped_penalty"] == 70
    assert float(without["adjusted_penalty"]) == 70.00
    assert float(without["hygiene_score"]) == 30.00
    assert without["hygiene_band"] == "CRITICAL"

    validate_success(api.patch_monitored_profile(profile["id"],
                                                 {"two_factor_attested": True},
                                                 household["owner"]))
    withattest = validate_success(api.get_hygiene_score(profile["id"],
                                                        household["owner"]))
    # Cap first: 70 * 0.60 = 42.00, so the score is 58.00.  Capping after the
    # multiplier would give min(75 * 0.60, 70) = 45.00 and a score of 55.00.
    assert withattest["raw_penalty"] == 75
    assert withattest["capped_penalty"] == 70
    assert float(withattest["adjusted_penalty"]) == 42.00
    assert float(withattest["hygiene_score"]) == 58.00
    # 58.00 is below 60 and at or above 40.
    assert withattest["hygiene_band"] == "WEAK"


def test_a_score_of_exactly_sixty_bands_as_moderate(api):
    """PRD §3.7: "The **hygiene band** is `STRONG` when the score is at least 80, otherwise
    `MODERATE` when it is at least 60, otherwise `WEAK` when it is at least 40, and
    `CRITICAL` in every remaining case."

    Design: Corner/calculations/hygiene_band_boundary_exactly_sixty_is_moderate
    """
    household = fx.open_household()
    profile = fx.draft_profile(household, two_factor_attested=False)
    for detail in ("s1", "s2", "s3", "s4"):
        fx.add_credential_finding(profile["id"], "STALE_PASSWORD", detail=detail)
    fx.add_credential_finding(profile["id"], "REUSED_PASSWORD", detail="r1")

    at_boundary = validate_success(api.get_hygiene_score(profile["id"],
                                                         household["owner"]))
    # raw = 4 * 7 + 12 = 40; capped 40; multiplier 1.00; score 100 - 40.00 = 60.00,
    # which is exactly the MODERATE floor and therefore MODERATE, not WEAK.
    assert at_boundary["open_finding_count"] == 5
    assert at_boundary["raw_penalty"] == 40
    assert at_boundary["capped_penalty"] == 40
    assert float(at_boundary["hygiene_score"]) == 60.00
    assert at_boundary["hygiene_band"] == "MODERATE"

    fx.add_credential_finding(profile["id"], "STALE_PASSWORD", detail="s5")
    below = validate_success(api.get_hygiene_score(profile["id"], household["owner"]))
    # raw = 47; score 100 - 47.00 = 53.00, which is below 60 and at or above 40.
    assert below["raw_penalty"] == 47
    assert float(below["hygiene_score"]) == 53.00
    assert below["hygiene_band"] == "WEAK"


def test_a_privacy_agent_may_not_remediate_a_credential_finding(api):
    """PRD §3.7: "Findings move `OPEN → REMEDIATED` when the household fixes the credential
    — an action for the `AccountOwner` or a `Member`, stamping `remediated_at` — and back
    `REMEDIATED → OPEN` when a `PrivacyAgent` observes the credential weak again on a later
    sweep, which clears `remediated_at` to null."
    PRD §2.1: "When the role is well-formed but the endpoint does not list it among its
    authorized roles, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/privacy_agent_cannot_remediate_a_credential_finding
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)
    finding = fx.add_credential_finding(profile["id"], "WEAK_PASSWORD",
                                        detail="router admin")

    response = api.remediate_finding(finding["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    row = validate_success(api.get_credential_finding(finding["id"], household["owner"]))
    assert row["status"] == "OPEN"
    # One OPEN WEAK_PASSWORD: 100 - 18.00 = 82.00.
    assert float(fx.read_profile(profile["id"])["hygiene_score"]) == 82.00

    validate_success(api.remediate_finding(finding["id"], household["owner"]))
    assert float(fx.read_profile(profile["id"])["hygiene_score"]) == 100.00
