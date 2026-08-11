"""Corner calculation tests: posture windows, calendar-mode deadline,
practice-verify thresholds, strength variant divergence."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_agreement,
    create_draft_agreement,
    create_information_request_payload,
    create_past_practice_payload,
    create_union,
    get_success_data,
    make_union_representative_headers,
    validate_error,
)

ADMIN = TEST_USERS["lr_admin_headers"]
MGR = TEST_USERS["lr_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / past_practice_strength_variant_divergence
# ---------------------------------------------------------------------------

def _setup_documented_practice(api, union_name="Union B", **overrides):
    union = create_union(name=union_name)
    practice = get_success_data(
        api.create_past_practice(
            create_past_practice_payload(
                union_id=union["id"],
                title="Holiday premium practice",
                description="Premium paid every December since 2023",
                first_observed_date="2023-05-01T00:00:00Z",
                last_observed_date="2025-05-01T00:00:00Z",
                occurrence_count=8,
                **overrides,
            ),
            MGR,
        )
    )
    documented = get_success_data(
        api.transition_past_practice(practice["id"], {"to_status": "DOCUMENTED"}, MGR)
    )
    return union, documented


def test_past_practice_strength_variants_diverge(api):
    """PRD §3.10: "The **LEGALISTIC** variant takes the recency component as
    0.85 raised to the power of the floor of the recency in years, then
    computes `strength_legalistic` as 0.6 times the recency component plus 0.4
    times the frequency, rounded half-up to 4 decimal places. The
    **OPERATIONAL** variant uses a step decay — the recency component is 1.0
    when the recency is less than 5 years, 0.5 otherwise — and computes
    `strength_operational` as 0.4 times the recency component plus 0.6 times
    the frequency, also rounded half-up to 4 decimal places."
    (recency 1 year, frequency 0.8: LEGALISTIC 0.6*0.85 + 0.4*0.8 = 0.8300;
    OPERATIONAL 0.4*1.0 + 0.6*0.8 = 0.8800.)

    Design: Difficulty/dual_variant_calc/past_practice_strength_variant_divergence
    """
    _, documented = _setup_documented_practice(api)
    assert documented["status"] == "DOCUMENTED"
    assert documented["strength_legalistic"] == pytest.approx(0.83, abs=1e-4)
    assert documented["strength_operational"] == pytest.approx(0.88, abs=1e-4)
    assert documented["strength_legalistic"] != pytest.approx(
        documented["strength_operational"], abs=1e-9
    )


def test_past_practice_only_legalistic_gates_verification(api):
    """PRD §3.10: "The LEGALISTIC variant is the verification gate; the
    OPERATIONAL variant is reported on reads for operational-leverage
    assessments." and "A `LegalCounsel` moves a `DOCUMENTED` practice to
    `VERIFIED` only when `occurrence_count` is at least 3 and
    `strength_legalistic` is at least 0.5000 — otherwise
    `ERR_PRACTICE_NOT_VERIFIABLE` (HTTP 422)."
    (Here occurrence_count 8 >= 3 and strength_legalistic 0.83 >= 0.5000, so
    verification succeeds even though the two variants diverge.)

    Design: Difficulty/dual_variant_calc/past_practice_strength_variant_divergence
    """
    _, documented = _setup_documented_practice(api)
    assert documented["strength_legalistic"] >= 0.5
    verified = get_success_data(
        api.transition_past_practice(documented["id"], {"to_status": "VERIFIED"}, LC)
    )
    assert verified["status"] == "VERIFIED"


# ---------------------------------------------------------------------------
# Corner: calculations / posture_window_day_boundaries
# ---------------------------------------------------------------------------

def _make_active_with_expiration(api, name, code, expiration):
    union = create_union(name=name, union_code=code)
    agreement = create_active_agreement(
        union["id"],
        title=f"CBA {code}",
        effective_date="2026-01-01T00:00:00Z",
        expiration_date=expiration,
        headcount_baseline=10,
        fte_projected=12,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    return agreement


def test_posture_sunset_boundary_days(api):
    """PRD §2.6: "An agreement in `ACTIVE` or `EXTENDED` computes `days_left`
    as the whole calendar days between the current clock and `expiration_date`,
    then maps: more than 180 days left yields `OPEN`; more than 30 days left
    but no more than 180 yields `SUNSET`; 30 days or fewer yields `CRITICAL`."
    (At the default clock 2026-05-01: expiration 2026-10-29 -> 181 days OPEN;
    2026-10-28 -> 180 days SUNSET.)

    Design: Corner/calculations/posture_window_day_boundaries
    """
    a181 = _make_active_with_expiration(api, "Union P1", "UPW-1", "2026-10-29T00:00:00Z")
    a180 = _make_active_with_expiration(api, "Union P2", "UPW-2", "2026-10-28T00:00:00Z")
    p181 = get_success_data(api.get_agreement(a181["id"], ADMIN))["posture"]
    p180 = get_success_data(api.get_agreement(a180["id"], ADMIN))["posture"]
    assert p181 == "OPEN", "181 days left > 180"
    assert p180 == "SUNSET", "exactly 180 is not > 180"


def test_posture_critical_boundary_days(api):
    """PRD §2.6: "more than 30 days left but no more than 180 yields `SUNSET`;
    30 days or fewer yields `CRITICAL`."
    (At the default clock 2026-05-01: expiration 2026-06-01 -> 31 days SUNSET;
    2026-05-31 -> 30 days CRITICAL.)

    Design: Corner/calculations/posture_window_day_boundaries
    """
    a31 = _make_active_with_expiration(api, "Union P3", "UPW-3", "2026-06-01T00:00:00Z")
    a30 = _make_active_with_expiration(api, "Union P4", "UPW-4", "2026-05-31T00:00:00Z")
    p31 = get_success_data(api.get_agreement(a31["id"], ADMIN))["posture"]
    p30 = get_success_data(api.get_agreement(a30["id"], ADMIN))["posture"]
    assert p31 == "SUNSET", "31 > 30"
    assert p30 == "CRITICAL", "exactly 30 is not > 30"


# ---------------------------------------------------------------------------
# Corner: calculations / calendar_mode_deadline_variant
# ---------------------------------------------------------------------------

def test_calendar_mode_deadline_counts_weekends(api):
    """PRD §3.11: "Under `CALENDAR`, the deadline advances 10 calendar days
    from the received date; `due_at` is that date at 17:00:00Z."

    Design: Corner/calculations/calendar_mode_deadline_variant
    """
    union = create_union(name="Union CQ")
    agreement = create_draft_agreement(
        union["id"], title="CBA CQ", deadline_mode="CALENDAR",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    request = get_success_data(
        api.create_information_request(
            create_information_request_payload(
                union_id=union["id"], agreement_id=agreement["id"],
                subject="Grievance log", received_at="2026-05-01T09:00:00Z",
            ),
            make_union_representative_headers(union["id"]),
        )
    )
    assert request["due_at"] == "2026-05-11T17:00:00Z", (
        f"CALENDAR-mode due_at mismatch: {request['due_at']}"
    )
    assert request["status"] == "RECEIVED"
    assert request["extension_count"] == 0


# ---------------------------------------------------------------------------
# Corner: calculations / practice_verify_threshold_gate
# ---------------------------------------------------------------------------

def test_practice_verify_occurrence_count_gate(api):
    """PRD §3.10: "A `LegalCounsel` moves a `DOCUMENTED` practice to `VERIFIED`
    only when `occurrence_count` is at least 3 and `strength_legalistic` is at
    least 0.5000 — otherwise `ERR_PRACTICE_NOT_VERIFIABLE` (HTTP 422)."

    Design: Corner/calculations/practice_verify_threshold_gate
    """
    union = create_union(name="Union CR")
    pp1 = get_success_data(
        api.create_past_practice(
            create_past_practice_payload(
                union_id=union["id"], title="Rare", description="Twice only",
                first_observed_date="2024-05-01T00:00:00Z",
                last_observed_date="2025-05-01T00:00:00Z",
                occurrence_count=2,
            ),
            MGR,
        )
    )
    get_success_data(api.transition_past_practice(pp1["id"], {"to_status": "DOCUMENTED"}, MGR))
    resp = api.transition_past_practice(pp1["id"], {"to_status": "VERIFIED"}, LC)
    validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_VERIFIABLE)


def test_practice_verify_strength_gate(api):
    """PRD §3.10: "A `LegalCounsel` moves a `DOCUMENTED` practice to `VERIFIED`
    only when `occurrence_count` is at least 3 and `strength_legalistic` is at
    least 0.5000 — otherwise `ERR_PRACTICE_NOT_VERIFIABLE` (HTTP 422)."
    (occurrence_count 3 with last_observed 2020-05-01 -> recency 6 years,
    LEGALISTIC 0.6*0.85^6 + 0.4*0.3 = 0.3463 < 0.5000, OPERATIONAL 0.4*0.5 +
    0.6*0.3 = 0.3800.)

    Design: Corner/calculations/practice_verify_threshold_gate
    """
    union = create_union(name="Union CR")
    pp2 = get_success_data(
        api.create_past_practice(
            create_past_practice_payload(
                union_id=union["id"], title="Stale", description="Old practice",
                first_observed_date="2018-05-01T00:00:00Z",
                last_observed_date="2020-05-01T00:00:00Z",
                occurrence_count=3,
            ),
            MGR,
        )
    )
    documented = get_success_data(
        api.transition_past_practice(pp2["id"], {"to_status": "DOCUMENTED"}, MGR)
    )
    assert documented["strength_legalistic"] == pytest.approx(0.3463, abs=1e-4)
    assert documented["strength_operational"] == pytest.approx(0.38, abs=1e-4)
    resp = api.transition_past_practice(pp2["id"], {"to_status": "VERIFIED"}, LC)
    validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_VERIFIABLE)
