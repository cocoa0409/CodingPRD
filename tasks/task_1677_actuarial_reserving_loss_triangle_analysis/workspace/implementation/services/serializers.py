"""Shape stored entities for response output.

- Common-fields resources: id, created_at, updated_at, version, plus own fields.
- ClaimTransaction is the append-only exception: only id and created_at are
  system-managed; updated_at/version are absent.
- Decimal values are emitted as JSON numbers via float().
"""
from decimal import Decimal

from db import db
from services.calculations import (
    claim_adequacy,
    matched_run_for_study,
    reconciliation_variance_pct,
)


def _num(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def segment_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "name": rec["name"],
        "line_of_business": rec["line_of_business"],
        "large_loss_threshold_cents": rec["large_loss_threshold_cents"],
        "max_range_width_pct": _num(rec["max_range_width_pct"]),
        "benchmark_open_severity_cents": rec["benchmark_open_severity_cents"],
        "last_closed_quarter": rec.get("last_closed_quarter"),
    }


def catastrophe_event_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "segment_id": rec["segment_id"],
        "name": rec["name"],
        "start_date": rec["start_date"],
        "end_date": rec["end_date"],
    }


def claim_view(rec):
    segment = db["segments"].get(rec["segment_id"])
    ard, arb = (None, None)
    if segment is not None:
        ard, arb = claim_adequacy(rec, segment)
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "segment_id": rec["segment_id"],
        "claim_number": rec["claim_number"],
        "accident_date": rec["accident_date"],
        "report_date": rec["report_date"],
        "catastrophe_event_id": rec.get("catastrophe_event_id"),
        "status": rec["status"],
        "paid_to_date_cents": rec["paid_to_date_cents"],
        "case_outstanding_cents": rec["case_outstanding_cents"],
        "reported_incurred_cents": rec["reported_incurred_cents"],
        "is_large_loss": rec["is_large_loss"],
        "is_segregated": rec["is_segregated"],
        "adequacy_ratio_development": _num(ard) if ard is not None else None,
        "adequacy_ratio_benchmark": _num(arb) if arb is not None else None,
    }


def claim_transaction_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "claim_id": rec["claim_id"],
        "type": rec["type"],
        "transaction_date": rec["transaction_date"],
        "effective_quarter": rec["effective_quarter"],
        "amount_cents": rec.get("amount_cents"),
        "case_value_cents": rec.get("case_value_cents"),
    }


def triangle_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "segment_id": rec["segment_id"],
        "basis": rec["basis"],
        "valuation_quarter": rec["valuation_quarter"],
        "cells": list(rec["cells"]),
        "large_loss_cells": list(rec["large_loss_cells"]),
        "is_stale": rec["is_stale"],
    }


def pattern_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "segment_id": rec["segment_id"],
        "basis": rec["basis"],
        "valuation_quarter": rec["valuation_quarter"],
        "effective_from_quarter": rec["effective_from_quarter"],
        "effective_to_quarter": rec["effective_to_quarter"],
        "selected_factors": [_num(f) for f in rec["selected_factors"]],
        "tail_factor": _num(rec["tail_factor"]),
        "status": rec["status"],
    }


def run_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "segment_id": rec["segment_id"],
        "development_pattern_id": rec.get("development_pattern_id"),
        "valuation_quarter": rec["valuation_quarter"],
        "method": rec["method"],
        "basis": rec["basis"],
        "earned_exposure_cents": rec.get("earned_exposure_cents"),
        "a_priori_loss_ratio": _num(rec["a_priori_loss_ratio"]) if rec.get("a_priori_loss_ratio") is not None else None,
        "ultimate_cents": rec["ultimate_cents"],
        "ibnr_cents": rec["ibnr_cents"],
        "range_low_cents": rec["range_low_cents"],
        "range_high_cents": rec["range_high_cents"],
        "ultimate_by_accident_quarter": list(rec["ultimate_by_accident_quarter"]),
        "is_stale": rec["is_stale"],
    }


def study_view(rec):
    matched = matched_run_for_study(rec)
    if matched is not None:
        su = matched["ultimate_cents"]
        si = matched["ibnr_cents"]
        srl = matched["range_low_cents"]
        srh = matched["range_high_cents"]
    else:
        su = si = srl = srh = None
    rvp = reconciliation_variance_pct(rec)
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "segment_id": rec["segment_id"],
        "valuation_quarter": rec["valuation_quarter"],
        "selected_method": rec["selected_method"],
        "selected_basis": rec["selected_basis"],
        "status": rec["status"],
        "stale_data_flag": rec["stale_data_flag"],
        "created_by_user_id": rec["created_by_user_id"],
        "reviewed_by_user_id": rec.get("reviewed_by_user_id"),
        "opinion_id": rec.get("opinion_id"),
        "selected_ultimate_cents": su,
        "selected_ibnr_cents": si,
        "selected_range_low_cents": srl,
        "selected_range_high_cents": srh,
        "reconciliation_variance_pct": _num(rvp) if rvp is not None else None,
    }


def opinion_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "statement_date": rec["statement_date"],
        "opinion_scope": rec["opinion_scope"],
        "status": rec["status"],
        "created_by_user_id": rec["created_by_user_id"],
        "signed_by_user_id": rec.get("signed_by_user_id"),
        "signed_at": rec.get("signed_at"),
        "filing_deadline_date": rec["filing_deadline_date"],
    }


def rollforward_view(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "segment_id": rec["segment_id"],
        "valuation_quarter": rec["valuation_quarter"],
        "prior_valuation_quarter": rec["prior_valuation_quarter"],
        "basis": rec["basis"],
        "expected_emergence_cents": rec["expected_emergence_cents"],
        "actual_emergence_cents": rec["actual_emergence_cents"],
        "ave_variance_cents": rec["ave_variance_cents"],
        "ave_variance_ratio": _num(rec["ave_variance_ratio"]) if rec["ave_variance_ratio"] is not None else None,
    }
