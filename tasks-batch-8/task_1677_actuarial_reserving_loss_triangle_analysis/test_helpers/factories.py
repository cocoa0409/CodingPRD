"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "SEGMENT_NAME": "Test Book",
    "LINE_OF_BUSINESS": "COMMERCIAL_AUTO",
    "LARGE_LOSS_THRESHOLD_CENTS": 400000,
    "MAX_RANGE_WIDTH_PCT": 0.5,
    "BENCHMARK_OPEN_SEVERITY_CENTS": 50000,
    "CLAIM_NUMBER": "C-1",
    "ACCIDENT_DATE": "2025-01-15",
    "REPORT_DATE": "2025-01-20",
    "EVENT_NAME": "CAT-1",
    "START_DATE": "2025-01-01",
    "END_DATE": "2025-03-31",
    "TRANSACTION_DATE": "2025-02-01T00:00:00Z",
    "AMOUNT_CENTS": 100000,
    "CASE_VALUE_CENTS": 50000,
    "BASIS": "PAID",
    "VALUATION_QUARTER": "2025-Q3",
    "EFFECTIVE_FROM_QUARTER": "2025-Q3",
    "EFFECTIVE_TO_QUARTER": "2026-Q2",
    "METHOD": "CHAIN_LADDER",
    "EARNED_EXPOSURE_CENTS": 400000,
    "A_PRIORI_LOSS_RATIO": 0.8,
    "STATEMENT_DATE": "2025-09-30",
    "OPINION_SCOPE": "REASONABLE",
}


def create_segment_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SEGMENT_NAME"],
        "line_of_business": DEFAULTS["LINE_OF_BUSINESS"],
        "large_loss_threshold_cents": DEFAULTS["LARGE_LOSS_THRESHOLD_CENTS"],
        "max_range_width_pct": DEFAULTS["MAX_RANGE_WIDTH_PCT"],
        "benchmark_open_severity_cents": DEFAULTS["BENCHMARK_OPEN_SEVERITY_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_catastrophe_event_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "name": DEFAULTS["EVENT_NAME"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_claim_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "claim_number": DEFAULTS["CLAIM_NUMBER"],
        "accident_date": DEFAULTS["ACCIDENT_DATE"],
        "report_date": DEFAULTS["REPORT_DATE"],
    }
    payload.update(overrides)
    return payload


def payment_payload(**overrides) -> dict:
    payload = {
        "type": "PAYMENT",
        "transaction_date": DEFAULTS["TRANSACTION_DATE"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def payment_reversal_payload(**overrides) -> dict:
    payload = {
        "type": "PAYMENT_REVERSAL",
        "transaction_date": DEFAULTS["TRANSACTION_DATE"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def case_reserve_set_payload(**overrides) -> dict:
    payload = {
        "type": "CASE_RESERVE_SET",
        "transaction_date": DEFAULTS["TRANSACTION_DATE"],
        "case_value_cents": DEFAULTS["CASE_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_triangle_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "basis": DEFAULTS["BASIS"],
        "valuation_quarter": DEFAULTS["VALUATION_QUARTER"],
    }
    payload.update(overrides)
    return payload


def create_development_pattern_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "basis": DEFAULTS["BASIS"],
        "valuation_quarter": DEFAULTS["VALUATION_QUARTER"],
        "effective_from_quarter": DEFAULTS["EFFECTIVE_FROM_QUARTER"],
        "effective_to_quarter": DEFAULTS["EFFECTIVE_TO_QUARTER"],
    }
    payload.update(overrides)
    return payload


def create_reserve_run_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "valuation_quarter": DEFAULTS["VALUATION_QUARTER"],
        "method": DEFAULTS["METHOD"],
        "basis": DEFAULTS["BASIS"],
    }
    payload.update(overrides)
    return payload


def create_bf_run_payload(segment_id, **overrides) -> dict:
    payload = create_reserve_run_payload(
        segment_id, method="BORNHUETTER_FERGUSON", **overrides
    )
    payload.setdefault("earned_exposure_cents", DEFAULTS["EARNED_EXPOSURE_CENTS"])
    payload.setdefault("a_priori_loss_ratio", DEFAULTS["A_PRIORI_LOSS_RATIO"])
    return payload


def create_study_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "valuation_quarter": DEFAULTS["VALUATION_QUARTER"],
        "selected_method": DEFAULTS["METHOD"],
        "selected_basis": DEFAULTS["BASIS"],
    }
    payload.update(overrides)
    return payload


def patch_study_payload(expected_study_version, **overrides) -> dict:
    payload = {"expected_study_version": expected_study_version}
    payload.update(overrides)
    return payload


def review_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_opinion_payload(**overrides) -> dict:
    payload = {
        "statement_date": DEFAULTS["STATEMENT_DATE"],
        "opinion_scope": DEFAULTS["OPINION_SCOPE"],
    }
    payload.update(overrides)
    return payload


def create_roll_forward_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "valuation_quarter": "2025-Q4",
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601="2025-10-15T00:00:00Z") -> dict:
    return {"to_iso8601": to_iso8601}
