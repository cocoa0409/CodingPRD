"""Boil-water advisories: chlorine boundary, pass-count accumulation and reset,
20-hour sample spacing, lift preconditions, segregation of duties, and the
state-vs-safety priority ordering."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_advisory,
    issue_manual_advisory,
    record_sample,
    setup_advisory_with_passes,
    setup_confirmed_break,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import create_water_quality_test_payload


def _instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant-level comparison.

    PRD §3.5 requires `last_sample_at` to be updated to the test's
    `sampled_at` — an instant-level rule. PRD pins three-fractional-digit
    rendering only for server-generated `created_at`/`updated_at` (§2.5) and
    `api_request_timestamp` (§2.4), so client-supplied instants may be echoed
    verbatim or serialized canonically; compare instants, not strings.
    """
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

WQ1 = TEST_USERS["wq_officer_headers"]
WQ2 = TEST_USERS["wq_officer_2_headers"]


def _willow_advisory():
    """Confirmed break on MAIN-8-WILLOW + manual advisory issued by wq_officer_1
    at the startup clock 2026-08-01T00:00:00Z."""
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-WILLOW", material="PVC", diameter_inches=8,
        install_year=1990, break_type="CIRCUMFERENTIAL", severity="LOW",
        location_description="15 Willow Way",
    )
    adv = issue_manual_advisory(ctx["break"]["id"], WQ1)
    ctx["advisory"] = adv
    return ctx


# ---------------------------------------------------------------------------
# Difficulty: chlorine_boundary_inclusive_0_20 (2 tests)
# ---------------------------------------------------------------------------

def test_chlorine_exactly_0_20_passes(api):
    """PRD §3.5: "Each test's `test_outcome` is computed at recording: `PASS`
    when the coliform result is `PASS` and the chlorine residual is at least
    0.20 milligrams per liter — a reading of exactly 0.20 passes — and `FAIL`
    otherwise. Recording a test mutates its advisory: a `PASS` outcome
    increments `consecutive_pass_count` by 1, while any `FAIL` resets it to 0,
    and `last_sample_at` is updated to the test's `sampled_at`."

    Design: Difficulty/boundary_precision_check/chlorine_boundary_inclusive_0_20
    """
    ctx = _willow_advisory()
    adv = ctx["advisory"]
    resp = _api.create_water_quality_test(
        create_water_quality_test_payload(
            advisory_id=adv["id"], sampled_at="2026-08-02T00:00:00Z",
            chlorine_residual_mg_l=0.20, coliform_result="PASS",
        ),
        WQ1,
    )
    test = validate_success(resp, 201)
    assert test["test_outcome"] == "PASS", (
        f"chlorine exactly 0.20 with coliform PASS must pass; got {test['test_outcome']!r}"
    )
    adv_after = get_advisory(adv["id"])
    assert adv_after["consecutive_pass_count"] == 1
    assert _instant(adv_after["last_sample_at"]) == _instant("2026-08-02T00:00:00Z"), (
        "last_sample_at must be updated to the test's sampled_at instant; "
        f"got {adv_after['last_sample_at']!r}"
    )


def test_chlorine_0_19_fails_and_resets_count(api):
    """PRD §3.5: "Each test's `test_outcome` is computed at recording: `PASS`
    when the coliform result is `PASS` and the chlorine residual is at least
    0.20 milligrams per liter — a reading of exactly 0.20 passes — and `FAIL`
    otherwise. Recording a test mutates its advisory: a `PASS` outcome
    increments `consecutive_pass_count` by 1, while any `FAIL` resets it to 0,
    and `last_sample_at` is updated to the test's `sampled_at`."

    Design: Difficulty/boundary_precision_check/chlorine_boundary_inclusive_0_20
    """
    ctx = _willow_advisory()
    adv = ctx["advisory"]
    t1 = validate_success(
        _api.create_water_quality_test(
            create_water_quality_test_payload(
                advisory_id=adv["id"], sampled_at="2026-08-02T00:00:00Z",
                chlorine_residual_mg_l=0.20, coliform_result="PASS",
            ),
            WQ1,
        ),
        201,
    )
    assert t1["test_outcome"] == "PASS"
    assert get_advisory(adv["id"])["consecutive_pass_count"] == 1

    t2 = validate_success(
        _api.create_water_quality_test(
            create_water_quality_test_payload(
                advisory_id=adv["id"], sampled_at="2026-08-03T00:00:00Z",
                chlorine_residual_mg_l=0.19, coliform_result="PASS",
            ),
            WQ1,
        ),
        201,
    )
    assert t2["test_outcome"] == "FAIL", (
        f"chlorine 0.19 < 0.20 must fail even with coliform PASS; got {t2['test_outcome']!r}"
    )
    assert get_advisory(adv["id"])["consecutive_pass_count"] == 0, (
        "any FAIL resets the consecutive-pass counter to 0"
    )


# ---------------------------------------------------------------------------
# Difficulty: lift_conflict_state_beats_safety (2 tests)
# ---------------------------------------------------------------------------

def _lifted_advisory_by_other_officer():
    """Advisory issued by wq_officer_1, two PASS tests, then lifted by
    wq_officer_2. Returns (break ctx, advisory after lift)."""
    ctx = setup_advisory_with_passes(
        num_passes=2,
        break_kwargs=dict(
            segment_ref="MAIN-8-WILLOW", material="PVC", diameter_inches=8,
            install_year=1990, break_type="CIRCUMFERENTIAL", severity="LOW",
            location_description="15 Willow Way",
        ),
    )
    adv = ctx["advisory"]
    assert adv["consecutive_pass_count"] == 2
    lifted = validate_success(_api.lift_boil_water_advisory(adv["id"], WQ2), 200)
    assert lifted["advisory_status"] == "LIFTED"
    ctx["advisory"] = lifted
    return ctx


def test_second_lift_on_lifted_advisory_is_invalid_state(api):
    """PRD §2.7: "After state legality come the domain guard tiers: water-quality
    compliance (`ERR_ADVISORY_TESTS_INSUFFICIENT`, `ERR_SEGREGATION_OF_DUTIES`,
    `ERR_TEST_SAMPLE_TOO_SOON`), cross-aggregate referential integrity
    (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_SEGMENT_REPLACED`), temporal windows
    (`ERR_CLAIM_FILED_LATE`, `ERR_PERMIT_WINDOW_MISMATCH`, `ERR_PERMIT_OVERLAP`,
    `ERR_CREW_DOUBLE_BOOKED`, `ERR_CORRELATION_WINDOW`), structural constraints
    (`ERR_BREAK_NOT_ISOLATED`, `ERR_DUPLICATE_ACTIVE_WORK_ORDER`,
    `ERR_ADVISORY_ALREADY_OPEN`, `ERR_ADVISORY_STILL_ACTIVE`, `ERR_CLAIMS_OPEN`,
    `ERR_NO_CREW_AVAILABLE`), and finally fiscal rules (`ERR_INVALID_AMOUNT`
    with HTTP 400, and `ERR_AMOUNT_EXCEEDS_CLAIMED` with HTTP 409)."
    PRD §3.5: "A successful lift moves the advisory to `LIFTED` (terminal),
    stamps `lifted_at`, and records `lifted_by_user_id`."

    Design: Difficulty/priority_pair_validation_conflict/lift_conflict_state_beats_safety
    """
    ctx = _lifted_advisory_by_other_officer()
    adv = ctx["advisory"]
    # The second lift is attempted by the issuer (wq_officer_1): both the state
    # precondition (advisory no longer ISSUED) and segregation of duties are
    # violated; the state-tier error must surface.
    resp = _api.lift_boil_water_advisory(adv["id"], WQ1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_second_lift_does_not_surface_segregation_error(api):
    """PRD §2.7: "When several checks could reject the same request, they are
    evaluated in a fixed order so that the surfaced error is deterministic."
    PRD §2.7: "After state legality come the domain guard tiers: water-quality
    compliance (`ERR_ADVISORY_TESTS_INSUFFICIENT`, `ERR_SEGREGATION_OF_DUTIES`,
    `ERR_TEST_SAMPLE_TOO_SOON`), cross-aggregate referential integrity
    (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_SEGMENT_REPLACED`), temporal windows
    (`ERR_CLAIM_FILED_LATE`, `ERR_PERMIT_WINDOW_MISMATCH`, `ERR_PERMIT_OVERLAP`,
    `ERR_CREW_DOUBLE_BOOKED`, `ERR_CORRELATION_WINDOW`), structural constraints
    (`ERR_BREAK_NOT_ISOLATED`, `ERR_DUPLICATE_ACTIVE_WORK_ORDER`,
    `ERR_ADVISORY_ALREADY_OPEN`, `ERR_ADVISORY_STILL_ACTIVE`, `ERR_CLAIMS_OPEN`,
    `ERR_NO_CREW_AVAILABLE`), and finally fiscal rules (`ERR_INVALID_AMOUNT`
    with HTTP 400, and `ERR_AMOUNT_EXCEEDS_CLAIMED` with HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/lift_conflict_state_beats_safety
    """
    ctx = _lifted_advisory_by_other_officer()
    adv = ctx["advisory"]
    resp = _api.lift_boil_water_advisory(adv["id"], WQ1)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] != "ERR_SEGREGATION_OF_DUTIES", (
        "state-tier ERR_INVALID_STATE must win over the safety-tier "
        "ERR_SEGREGATION_OF_DUTIES when both apply"
    )
    after = get_advisory(adv["id"])
    assert after["advisory_status"] == "LIFTED"
    assert after["lifted_by_user_id"] == "wq_officer_2"


# ---------------------------------------------------------------------------
# Corner: pass_count_reset_blocks_lift
# ---------------------------------------------------------------------------

def test_pass_count_reset_blocks_lift(api):
    """PRD §3.5: "Recording a test mutates its advisory: a `PASS` outcome
    increments `consecutive_pass_count` by 1, while any `FAIL` resets it to 0,
    and `last_sample_at` is updated to the test's `sampled_at`."
    PRD §3.5: "A `WaterQualityOfficer` lifts an `ISSUED` advisory only when its
    `consecutive_pass_count` is at least 2 at the moment of lifting (otherwise
    `ERR_ADVISORY_TESTS_INSUFFICIENT`)…"

    Design: Corner/calculations/pass_count_reset_blocks_lift
    """
    ctx = _willow_advisory()
    adv = ctx["advisory"]
    record_sample(adv["id"], "2026-08-02T00:00:00Z", chlorine_residual_mg_l=0.30)
    record_sample(adv["id"], "2026-08-03T00:00:00Z", chlorine_residual_mg_l=0.25)
    t3 = record_sample(adv["id"], "2026-08-04T00:00:00Z",
                       chlorine_residual_mg_l=0.40, coliform_result="FAIL")
    assert t3["test_outcome"] == "FAIL", (
        "coliform FAIL must fail the test even with chlorine 0.40"
    )
    record_sample(adv["id"], "2026-08-05T00:00:00Z", chlorine_residual_mg_l=0.30)

    adv_after = get_advisory(adv["id"])
    assert adv_after["consecutive_pass_count"] == 1, (
        f"PASS,PASS,FAIL,PASS must leave the counter at 1, got "
        f"{adv_after['consecutive_pass_count']}"
    )
    resp = _api.lift_boil_water_advisory(adv["id"], WQ2)
    validate_error(resp, ApiErrorId.ERR_ADVISORY_TESTS_INSUFFICIENT)
    assert get_advisory(adv["id"])["advisory_status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Corner: test_sample_within_20h_rejected
# ---------------------------------------------------------------------------

def test_sample_within_20h_rejected(api):
    """PRD §3.5: "Two temporal rules guard sampling: `sampled_at` must not be
    earlier than the advisory's `issued_at` (otherwise `ERR_VALIDATION`), and
    when a previous sample exists, the new `sampled_at` must be at least 20
    hours after `last_sample_at` — sampling sooner is rejected with
    `ERR_TEST_SAMPLE_TOO_SOON`."

    Design: Corner/validations/test_sample_within_20h_rejected
    """
    ctx = _willow_advisory()
    adv = ctx["advisory"]
    record_sample(adv["id"], "2026-08-02T00:00:00Z", chlorine_residual_mg_l=0.30)

    too_soon = _api.create_water_quality_test(
        create_water_quality_test_payload(
            advisory_id=adv["id"], sampled_at="2026-08-02T10:00:00Z",
            chlorine_residual_mg_l=0.30, coliform_result="PASS",
        ),
        WQ1,
    )
    validate_error(too_soon, ApiErrorId.ERR_TEST_SAMPLE_TOO_SOON)

    exactly_20h = _api.create_water_quality_test(
        create_water_quality_test_payload(
            advisory_id=adv["id"], sampled_at="2026-08-02T20:00:00Z",
            chlorine_residual_mg_l=0.30, coliform_result="PASS",
        ),
        WQ1,
    )
    test2 = validate_success(exactly_20h, 201)
    assert test2["test_outcome"] == "PASS", (
        "a sample exactly 20 hours after the previous one must be accepted"
    )


# ---------------------------------------------------------------------------
# Corner: second_advisory_rejected_while_open
# ---------------------------------------------------------------------------

def test_second_advisory_rejected_while_open(api):
    """PRD §3.5: "The manual path lets a `WaterQualityOfficer` issue an
    advisory for a break by naming its `break_report_id`; the break must be in
    `CONFIRMED`, `ISOLATED`, `IN_REPAIR`, or `REPAIRED` status (otherwise
    `ERR_INVALID_STATE`), and if any advisory for the break is already `ISSUED`
    the manual issue is rejected with `ERR_ADVISORY_ALREADY_OPEN`."

    Design: Corner/validations/second_advisory_rejected_while_open
    """
    ctx = _willow_advisory()
    br, first = ctx["break"], ctx["advisory"]
    resp = _api.create_boil_water_advisory({"break_report_id": br["id"]}, WQ2)
    validate_error(resp, ApiErrorId.ERR_ADVISORY_ALREADY_OPEN)
    first_after = get_advisory(first["id"])
    assert first_after["advisory_status"] == "ISSUED", (
        "the rejected second issue must leave the first advisory untouched"
    )


# ---------------------------------------------------------------------------
# Corner: segregation_of_duties_advisory_lift
# ---------------------------------------------------------------------------

def test_segregation_of_duties_advisory_lift(api):
    """PRD §3.5: "A `WaterQualityOfficer` lifts an `ISSUED` advisory only when
    its `consecutive_pass_count` is at least 2 at the moment of lifting
    (otherwise `ERR_ADVISORY_TESTS_INSUFFICIENT`) and the lifting officer's
    `X-User-ID` differs from the advisory's `issued_by_user_id` (otherwise
    `ERR_SEGREGATION_OF_DUTIES`) — the issuer may never lift their own
    advisory, which is why auto-issued advisories, issued by the literal
    "system", can be lifted by any officer."

    Design: Corner/rbac/segregation_of_duties_advisory_lift
    """
    ctx = setup_advisory_with_passes(
        num_passes=2,
        break_kwargs=dict(
            segment_ref="MAIN-8-WILLOW", material="PVC", diameter_inches=8,
            install_year=1990, break_type="CIRCUMFERENTIAL", severity="LOW",
            location_description="15 Willow Way",
        ),
    )
    adv = ctx["advisory"]
    assert adv["consecutive_pass_count"] == 2

    resp = _api.lift_boil_water_advisory(adv["id"], WQ1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    lifted = validate_success(_api.lift_boil_water_advisory(adv["id"], WQ2), 200)
    assert lifted["advisory_status"] == "LIFTED"
    assert lifted["lifted_by_user_id"] == "wq_officer_2"
    assert lifted["lifted_at"] is not None
