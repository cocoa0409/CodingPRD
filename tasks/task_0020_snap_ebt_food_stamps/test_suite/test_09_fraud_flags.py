"""FraudFlag lifecycle: terminal-state branching from OPEN/UNDER_REVIEW,
claiming-investigator segregation, and OCC stale-flag rejection.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_household_with_active_card,
    create_open_fraud_flag, claim_fraud_flag,
)

INV = TEST_USERS["fraud_investigator_headers"]
INV_B = TEST_USERS["fraud_investigator_b_headers"]


# ─── Difficulty / non_linear_state_machine / fraud_flag_under_review_branching ──

def test_under_review_substantiates_into_substantiated_branch(api):
    """One FraudFlag taken OPEN → claim → UNDER_REVIEW → substantiate lands
    in SUBSTANTIATED. PRD §3.9 names this branch explicitly.

    PRD §3.9: "A `FraudInvestigator` claims an `OPEN` flag, transitioning
    it to `UNDER_REVIEW`; on the claim, `investigator_id` is set to the
    calling `X-User-ID`. From `UNDER_REVIEW`, the same investigator who
    claimed the flag — and only that investigator — may substantiate or
    dismiss it. Substantiate transitions the flag from `UNDER_REVIEW` to
    `SUBSTANTIATED`; the request body carries the OCC pin
    `expected_fraudflag_version` and a non-empty `resolution_note`."

    Design: Difficulty/non_linear_state_machine/fraud_flag_under_review_branching
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="FL-600001", state_code="FL",
        clock_iso="2026-08-01T00:00:00Z",
    )
    ff_a = create_open_fraud_flag(hh["id"], trigger_rule="VELOCITY_SPIKE")
    claimed = claim_fraud_flag(ff_a["id"])
    resp = api.substantiate_fraud_flag(
        ff_a["id"],
        {"resolution_note": "Branch A confirmed",
         "expected_fraudflag_version": claimed["version"]},
        INV,
    )
    sub = validate_success(resp, 200)
    assert sub["status"] == "SUBSTANTIATED"


def test_open_dismisses_directly_bypassing_under_review(api):
    """A still-OPEN flag (no claimant) may be dismissed directly; PRD §3.9
    says the claiming-investigator check does not apply because there is
    no claimant yet. This is the asymmetric branch — OPEN → DISMISSED,
    bypassing UNDER_REVIEW entirely.

    PRD §3.9: "Dismissal transitions the flag from `UNDER_REVIEW` to
    `DISMISSED`; it requires a non-empty `resolution_note`. A flag that
    is still `OPEN` (no investigator has claimed it) may also be
    dismissed directly, again with a non-empty `resolution_note`; in
    that case the claiming-investigator segregation check does not apply
    because there is no claimant yet."

    Design: Difficulty/non_linear_state_machine/fraud_flag_under_review_branching
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="FL-600002", state_code="FL",
        clock_iso="2026-08-01T00:00:00Z",
    )
    ff_b = create_open_fraud_flag(hh["id"], trigger_rule="OUT_OF_STATE")
    assert ff_b["status"] == "OPEN"
    resp = api.dismiss_fraud_flag(
        ff_b["id"], {"resolution_note": "Branch B dismissed straight from OPEN"},
        INV,
    )
    dismissed = validate_success(resp, 200)
    assert dismissed["status"] == "DISMISSED"


# ─── Corner / state_machines / fraud_flag_not_claiming_investigator_substantiate_rejected ──

def test_substantiate_by_non_claiming_investigator_rejected(api):
    """A flag claimed by investigator A cannot be substantiated by
    investigator B per PRD §3.9. The check fires at priority 9 (PRD §2.8),
    BEFORE the OCC version check.

    PRD §3.9: "An attempt to substantiate or dismiss an `UNDER_REVIEW`
    flag by an investigator other than the one whose `X-User-ID` matches
    `investigator_id` is rejected with `ERR_NOT_CLAIMING_INVESTIGATOR`."
    PRD §2.8: "(9) the claiming-investigator segregation check on
    `FraudFlag` substantiate and dismiss while under review
    (`ERR_NOT_CLAIMING_INVESTIGATOR`, HTTP 403)"

    Design: Corner/state_machines/fraud_flag_not_claiming_investigator_substantiate_rejected
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="CA-900001", state_code="CA",
        clock_iso="2026-09-01T00:00:00Z",
    )
    ff = create_open_fraud_flag(hh["id"], trigger_rule="VELOCITY_SPIKE")
    claimed = claim_fraud_flag(ff["id"])
    # Investigator B (inv_002) attempts to substantiate a flag claimed by
    # inv_001 — must be rejected with ERR_NOT_CLAIMING_INVESTIGATOR.
    resp = api.substantiate_fraud_flag(
        ff["id"],
        {"resolution_note": "I'm not the claiming investigator",
         "expected_fraudflag_version": claimed["version"]},
        INV_B,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_CLAIMING_INVESTIGATOR.value)


# ─── Corner / cross_cutting_complexity_layers / occ_stale_fraudflag_version_on_substantiate ──

def test_occ_stale_fraudflag_version_on_substantiate(api):
    """The substantiate call requires expected_fraudflag_version to match
    the flag's current version. Passing a deliberately stale value (current
    - 1) must produce ERR_STALE_FRAUDFLAG_VERSION.

    PRD §2.5: "Substantiating a fraud flag requires `expected_fraudflag_version`
    in the request body. The value must match the target flag's current
    `version`. If a concurrent `/claim` or `/dismiss` by another investigator
    has advanced the flag's `version` since the substantiating investigator
    last read it, the substantiate is rejected with
    `ERR_STALE_FRAUDFLAG_VERSION` (HTTP 412). The investigator made a
    decision against an out-of-date case state, and the system refuses to
    apply it."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_fraudflag_version_on_substantiate
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="CA-900002", state_code="CA",
        clock_iso="2026-09-01T00:00:00Z",
    )
    ff = create_open_fraud_flag(hh["id"], trigger_rule="VELOCITY_SPIKE")
    claimed = claim_fraud_flag(ff["id"])
    stale_v = claimed["version"] - 1
    resp = api.substantiate_fraud_flag(
        ff["id"],
        {"resolution_note": "Confirmed",
         "expected_fraudflag_version": stale_v},
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_FRAUDFLAG_VERSION.value)
