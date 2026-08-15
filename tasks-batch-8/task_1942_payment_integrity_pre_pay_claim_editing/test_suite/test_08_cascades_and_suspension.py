"""Overturn cascades: hit false-positive release, edit-version auto-suspension
at the inclusive fp_rate boundary, task cancellation and claim compensation."""
import pytest

from test_helpers import (
    TEST_USERS,
    decide_dispute_payload,
    drive_hit_resolution,
    get_claim,
    get_hit,
    get_version,
    list_claim_tasks,
    open_dispute_under_review,
    setup_provider_with_active_edit,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]
ADJUDICATOR = TEST_USERS["adjudicator_headers"]


def _setup_overturn_scenario(api, npi="NPI-C4", edit_code="CASC-DENY"):
    """Provider + ACTIVE DENY edit; claims c1..c4 upheld (4 CONFIRMED hits),
    claim c5 screened and left FIRED with its task PENDING; c4 disputed and
    under review. Returns the context dict."""
    provider, rule, version = setup_provider_with_active_edit(
        npi=npi, edit_code=edit_code)
    upheld = [
        drive_hit_resolution(provider["id"], 40000, f"C4{i}", f"M-C4{i}",
                             "uphold")
        for i in range(1, 5)
    ]
    ctx5 = drive_hit_resolution(provider["id"], 30000, "C45", "M-C45", "fired")
    assert ctx5["claim"]["status"] == "PENDED"
    dispute = open_dispute_under_review(provider["id"],
                                        upheld[3]["claim"]["id"],
                                        upheld[3]["hit"]["id"],
                                        reason="false positive")
    return {
        "provider": provider, "rule": rule, "version": version,
        "upheld": upheld, "c5": ctx5, "dispute": dispute,
    }


def test_dispute_overturn_cascades_hit_fp_and_version_suspension(api):
    """PRD §3.6: "`OVERTURNED` declares the hit a false positive: the hit
    becomes `RELEASED_FALSE_POSITIVE` with `released_cents` set to the full
    `attributed_savings_cents`, the released amount returns to the claim's
    `allowed_amount_cents` and leaves `denied_amount_cents`, the line is
    rebalanced, and the pinned edit version's false-positive accounting is
    recomputed — which can trip the automatic suspension of Section 3.2 when
    the version is `ACTIVE` and its `fp_rate` reaches 0.25 on at least four
    resolved hits"
    PRD §3.2: "When `fp_rate` reaches or exceeds 0.25 on a sample of at least
    four resolved hits — the boundary is inclusive, so a rate of exactly
    0.2500 with exactly four resolved hits suspends — an `ACTIVE` version
    auto-suspends."

    Design: Difficulty/transitive_cascade/dispute_overturn_cascades_to_edit_suspension
    """
    sc = _setup_overturn_scenario(api)
    validate_success(api.decide_dispute(
        sc["dispute"]["id"], decide_dispute_payload("OVERTURNED"),
        ADJUDICATOR))

    hit = get_hit(sc["upheld"][3]["hit"]["id"])
    assert hit["status"] == "RELEASED_FALSE_POSITIVE"
    assert hit["released_cents"] == 40000

    version = get_version(sc["version"]["id"])
    assert version["resolved_hits_count"] == 4
    assert version["fp_hits_count"] == 1
    assert version["fp_rate"] == pytest.approx(0.25, abs=1e-9), (
        "exactly 1/4 = 0.2500 — the inclusive suspension boundary"
    )
    assert version["status"] == "SUSPENDED", (
        "fp_rate 0.2500 on 4 resolved hits auto-suspends the ACTIVE version"
    )


def test_dispute_overturn_cascades_task_cancel_and_claim_compensation(api):
    """PRD §3.6: "cascading onward to cancel that version's open review tasks
    and supersede their hits with full release."
    PRD §3.5: "A `DENIED` verdict is not necessarily final: when a later
    release — a task override, a dispute outcome, or a suspension supersede —
    lifts `allowed_amount_cents` above zero while all gates are terminal, the
    claim compensates back to `READY_TO_PAY`."
    PRD §3.2: "every review task still `PENDING` or `IN_REVIEW` whose hit is
    pinned to the suspended version is `CANCELLED`; each of those hits becomes
    `SUPERSEDED` with its `released_cents` set to the full
    `attributed_savings_cents`"

    Design: Difficulty/transitive_cascade/dispute_overturn_cascades_to_edit_suspension
    """
    sc = _setup_overturn_scenario(api, npi="NPI-C4B", edit_code="CASC-DENY-2")
    validate_success(api.decide_dispute(
        sc["dispute"]["id"], decide_dispute_payload("OVERTURNED"),
        ADJUDICATOR))

    # Hop 4: the unrelated pending task pinned to the version is cancelled,
    # its hit superseded with full release.
    c5_tasks = list_claim_tasks(sc["c5"]["claim"]["id"])
    assert len(c5_tasks) == 1
    assert c5_tasks[0]["status"] == "CANCELLED"
    hit5 = get_hit(sc["c5"]["hit"]["id"])
    assert hit5["status"] == "SUPERSEDED"
    assert hit5["released_cents"] == 30000

    # Hop 5: both claims rebalance and bubble to READY_TO_PAY.
    claim5 = get_claim(sc["c5"]["claim"]["id"])
    assert claim5["status"] == "READY_TO_PAY"
    assert claim5["allowed_amount_cents"] == 30000
    assert claim5["denied_amount_cents"] == 0

    claim4 = get_claim(sc["upheld"][3]["claim"]["id"])
    assert claim4["status"] == "READY_TO_PAY"
    assert claim4["allowed_amount_cents"] == 40000
    assert claim4["denied_amount_cents"] == 0


def test_fp_rate_zero_before_boundary(api):
    """PRD §3.2: "`resolved_hits_count` counts the version's pinned hits in
    `CONFIRMED` or `RELEASED_FALSE_POSITIVE` (hits that ended `OVERRIDDEN` or
    `SUPERSEDED` are excluded from this edit-quality rate), `fp_hits_count`
    counts those in `RELEASED_FALSE_POSITIVE`, and `fp_rate` is their quotient
    rounded half-up to four decimal places, or zero when nothing has
    resolved."
    PRD §3.2: "When `fp_rate` reaches or exceeds 0.25 on a sample of at least
    four resolved hits — the boundary is inclusive, so a rate of exactly
    0.2500 with exactly four resolved hits suspends — an `ACTIVE` version
    auto-suspends."

    Design: Difficulty/boundary_precision_check/fp_rate_exact_quarter_suspends
    """
    provider, _rule, version = setup_provider_with_active_edit(
        npi="NPI-F6", edit_code="FP-DENY")
    for i in range(1, 5):
        drive_hit_resolution(provider["id"], 40000, f"F6{i}", f"M-F6{i}",
                             "uphold")

    state = get_version(version["id"])
    assert state["resolved_hits_count"] == 4
    assert state["fp_hits_count"] == 0
    assert state["fp_rate"] == 0, "0/4 confirmed-only keeps fp_rate at zero"
    assert state["status"] == "ACTIVE", (
        "sample met but rate below 0.25: the boundary is not crossed"
    )


def test_fp_rate_exact_quarter_suspends(api):
    """PRD §3.2: "When `fp_rate` reaches or exceeds 0.25 on a sample of at
    least four resolved hits — the boundary is inclusive, so a rate of exactly
    0.2500 with exactly four resolved hits suspends — an `ACTIVE` version
    auto-suspends."
    PRD §3.6: "`OVERTURNED` declares the hit a false positive: the hit becomes
    `RELEASED_FALSE_POSITIVE` with `released_cents` set to the full
    `attributed_savings_cents`"

    Design: Difficulty/boundary_precision_check/fp_rate_exact_quarter_suspends
    """
    provider, _rule, version = setup_provider_with_active_edit(
        npi="NPI-F6B", edit_code="FP-DENY-2")
    ctxs = [
        drive_hit_resolution(provider["id"], 40000, f"G6{i}", f"M-G6{i}",
                             "uphold")
        for i in range(1, 5)
    ]
    before = get_version(version["id"])
    assert before["status"] == "ACTIVE"
    assert before["fp_rate"] == 0

    dispute = open_dispute_under_review(provider["id"],
                                        ctxs[3]["claim"]["id"],
                                        ctxs[3]["hit"]["id"],
                                        reason="false positive")
    validate_success(api.decide_dispute(
        dispute["id"], decide_dispute_payload("OVERTURNED"), ADJUDICATOR))

    after = get_version(version["id"])
    assert after["resolved_hits_count"] == 4
    assert after["fp_hits_count"] == 1
    assert after["fp_rate"] == pytest.approx(0.25, abs=1e-9)
    assert after["status"] == "SUSPENDED", (
        "exactly 0.2500 on exactly 4 resolved hits: inclusive >= suspends"
    )


def test_fp_rate_one_fifth_does_not_suspend(api):
    """PRD §3.2: "When `fp_rate` reaches or exceeds 0.25 on a sample of at
    least four resolved hits — the boundary is inclusive, so a rate of exactly
    0.2500 with exactly four resolved hits suspends — an `ACTIVE` version
    auto-suspends."

    Design: Corner/calculations/fp_rate_one_fifth_does_not_suspend
    """
    provider, _rule, version = setup_provider_with_active_edit(
        npi="NPI-F5", edit_code="BELOW-DENY")
    ctxs = [
        drive_hit_resolution(provider["id"], 40000, f"G5{i}", f"M-G5{i}",
                             "uphold")
        for i in range(1, 6)
    ]
    dispute = open_dispute_under_review(provider["id"],
                                        ctxs[4]["claim"]["id"],
                                        ctxs[4]["hit"]["id"],
                                        reason="false positive")
    validate_success(api.decide_dispute(
        dispute["id"], decide_dispute_payload("OVERTURNED"), ADJUDICATOR))

    state = get_version(version["id"])
    assert state["resolved_hits_count"] == 5
    assert state["fp_hits_count"] == 1
    assert state["fp_rate"] == pytest.approx(0.20, abs=1e-9), (
        "1/5 = 0.2000 sits below the inclusive 0.25 boundary"
    )
    assert state["status"] == "ACTIVE", "no auto-suspension below 0.25"
