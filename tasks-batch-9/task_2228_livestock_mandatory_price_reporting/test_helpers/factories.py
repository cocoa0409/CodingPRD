"""Payload builders.

Each builder returns a valid payload for one operation, with keyword
overrides so a test can perturb exactly the field under examination.  Passing
``None`` for an optional field drops it from the payload entirely, which is
how the tests exercise "field omitted" as distinct from "field null".
"""

from . import constants as k
from .types import (
    BasisVariant,
    CommentStance,
    EntityType,
    ProductClass,
    PurchaseType,
    PurchaseTypeFilter,
    ReportCategory,
    ReportClass,
    ReviewDecision,
    SaleType,
    Species,
    SuspendedReason,
    ViolationType,
    WeightingVariant,
    WindowFrequency,
)

_OMIT = object()


def _prune(payload):
    """Drop keys whose value is the omission sentinel."""
    return {key: value for key, value in payload.items() if value is not _OMIT}


# ---------------------------------------------------------------------------
# Reporting entities (PRD §3.1)
# ---------------------------------------------------------------------------


def reporting_entity_payload(
    legal_name="Alpha Packing Company",
    entity_type=EntityType.PACKER.value,
    species_scope=Species.CATTLE.value,
    **overrides,
):
    payload = {
        "legal_name": legal_name,
        "entity_type": entity_type,
        "species_scope": species_scope,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Plants (PRD §3.1)
# ---------------------------------------------------------------------------


def plant_payload(
    reporting_entity_id,
    plant_code="EST-101",
    species=Species.CATTLE.value,
    annual_head_history=None,
    boxed_beef_volume_lbs_prior_year=_OMIT,
    forward_commitment_cap_head=_OMIT,
    status=_OMIT,
    **overrides,
):
    payload = {
        "reporting_entity_id": reporting_entity_id,
        "plant_code": plant_code,
        "species": species,
        "annual_head_history": (
            dict(k.HISTORY_ABOVE_CATTLE_FLOOR)
            if annual_head_history is None
            else annual_head_history
        ),
        "boxed_beef_volume_lbs_prior_year": boxed_beef_volume_lbs_prior_year,
        "forward_commitment_cap_head": forward_commitment_cap_head,
        "status": status,
    }
    payload.update(overrides)
    return _prune(payload)


def plant_patch_payload(**overrides):
    """Amendment payload: every field is individually optional."""
    return _prune(dict(overrides))


# ---------------------------------------------------------------------------
# Registrations (PRD §3.2)
# ---------------------------------------------------------------------------


def registration_payload(
    reporting_entity_id,
    determination_year=2026,
    basis_variant=_OMIT,
    **overrides,
):
    payload = {
        "reporting_entity_id": reporting_entity_id,
        "determination_year": determination_year,
        "basis_variant": basis_variant,
    }
    payload.update(overrides)
    return _prune(payload)


def appeal_payload(appeal_reason="Averaged basis understates our current scale.", **overrides):
    payload = {"appeal_reason": appeal_reason}
    payload.update(overrides)
    return _prune(payload)


def redetermine_payload(basis_variant=BasisVariant.PRIOR_YEAR_ACTUAL.value, **overrides):
    payload = {"basis_variant": basis_variant}
    payload.update(overrides)
    return _prune(payload)


def suspend_payload(suspended_reason=SuspendedReason.ADMIN_ACTION.value, **overrides):
    payload = {"suspended_reason": suspended_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Reporting windows (PRD §3.3)
# ---------------------------------------------------------------------------


def reporting_window_payload(
    species=Species.CATTLE.value,
    report_class=ReportClass.LIVE_ANIMAL.value,
    frequency=WindowFrequency.WEEKLY.value,
    period_start=k.WINDOW_PERIOD_START,
    period_end=k.WINDOW_PERIOD_END,
    submission_deadline_utc=k.WINDOW_SUBMISSION_DEADLINE,
    correction_deadline_utc=k.WINDOW_CORRECTION_DEADLINE,
    publication_release_utc=k.WINDOW_PUBLICATION_RELEASE,
    min_reporter_count=_OMIT,
    max_single_reporter_share_pct=_OMIT,
    min_reported_head=_OMIT,
    **overrides,
):
    payload = {
        "species": species,
        "report_class": report_class,
        "frequency": frequency,
        "period_start": period_start,
        "period_end": period_end,
        "submission_deadline_utc": submission_deadline_utc,
        "correction_deadline_utc": correction_deadline_utc,
        "publication_release_utc": publication_release_utc,
        "min_reporter_count": min_reporter_count,
        "max_single_reporter_share_pct": max_single_reporter_share_pct,
        "min_reported_head": min_reported_head,
    }
    payload.update(overrides)
    return _prune(payload)


def relaxed_guideline_window_payload(**overrides):
    """A window whose confidentiality guidelines a single reporter can clear.

    One reporter, a 100 percent share ceiling and a one-head floor, so the
    guideline sequence of PRD §3.6 passes on a one-filing window.
    """
    relaxed = {
        "min_reporter_count": 1,
        "max_single_reporter_share_pct": 100.00,
        "min_reported_head": 1,
    }
    relaxed.update(overrides)
    return reporting_window_payload(**relaxed)


# ---------------------------------------------------------------------------
# Submissions (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------


def submission_payload(
    plant_id,
    reporting_window_id,
    expected_window_version,
    supersedes_submission_id=_OMIT,
    **overrides,
):
    payload = {
        "plant_id": plant_id,
        "reporting_window_id": reporting_window_id,
        "expected_window_version": expected_window_version,
        "supersedes_submission_id": supersedes_submission_id,
    }
    payload.update(overrides)
    return _prune(payload)


def transaction_payload(
    purchase_type=PurchaseType.NEGOTIATED.value,
    head_count=100,
    avg_net_price_per_cwt=280.00,
    avg_carcass_weight_cwt=8.00,
    formula_base_reference=_OMIT,
    grid_premium_discount_per_cwt=_OMIT,
    forward_delivery_start=_OMIT,
    forward_delivery_end=_OMIT,
    **overrides,
):
    payload = {
        "purchase_type": purchase_type,
        "head_count": head_count,
        "avg_net_price_per_cwt": avg_net_price_per_cwt,
        "avg_carcass_weight_cwt": avg_carcass_weight_cwt,
        "formula_base_reference": formula_base_reference,
        "grid_premium_discount_per_cwt": grid_premium_discount_per_cwt,
        "forward_delivery_start": forward_delivery_start,
        "forward_delivery_end": forward_delivery_end,
    }
    payload.update(overrides)
    return _prune(payload)


def formula_transaction_payload(
    formula_base_reference="CME_LIVE_CATTLE_INDEX", **overrides
):
    return transaction_payload(
        purchase_type=PurchaseType.FORMULA.value,
        formula_base_reference=formula_base_reference,
        **overrides,
    )


def grid_transaction_payload(grid_premium_discount_per_cwt=3.25, **overrides):
    return transaction_payload(
        purchase_type=PurchaseType.NEGOTIATED_GRID.value,
        grid_premium_discount_per_cwt=grid_premium_discount_per_cwt,
        **overrides,
    )


def forward_transaction_payload(
    forward_delivery_start="2026-09-01T00:00:00Z",
    forward_delivery_end="2026-09-10T00:00:00Z",
    **overrides,
):
    return transaction_payload(
        purchase_type=PurchaseType.FORWARD_CONTRACT.value,
        forward_delivery_start=forward_delivery_start,
        forward_delivery_end=forward_delivery_end,
        **overrides,
    )


def packer_owned_transaction_payload(**overrides):
    return transaction_payload(purchase_type=PurchaseType.PACKER_OWNED.value, **overrides)


def wholesale_lot_payload(
    product_class=ProductClass.BOXED_BEEF_CHOICE_CUTOUT.value,
    sale_type=SaleType.NEGOTIATED.value,
    load_count=10,
    total_pounds=400000.00,
    price_per_cwt=285.50,
    **overrides,
):
    payload = {
        "product_class": product_class,
        "sale_type": sale_type,
        "load_count": load_count,
        "total_pounds": total_pounds,
        "price_per_cwt": price_per_cwt,
    }
    payload.update(overrides)
    return _prune(payload)


def review_payload(decision=ReviewDecision.ACCEPT.value, review_note=_OMIT, **overrides):
    payload = {"decision": decision, "review_note": review_note}
    payload.update(overrides)
    return _prune(payload)


def correction_payload(correction_reason="Head count restated by the plant.", **overrides):
    payload = {"correction_reason": correction_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Market reports (PRD §3.6)
# ---------------------------------------------------------------------------


def market_report_payload(
    reporting_window_id,
    category=ReportCategory.LIVE_STEER_HEIFER.value,
    weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
    purchase_type_filter=_OMIT,
    **overrides,
):
    payload = {
        "reporting_window_id": reporting_window_id,
        "category": category,
        "weighting_variant": weighting_variant,
        "purchase_type_filter": purchase_type_filter,
    }
    payload.update(overrides)
    return _prune(payload)


def negotiated_only_market_report_payload(reporting_window_id, **overrides):
    return market_report_payload(
        reporting_window_id,
        purchase_type_filter=PurchaseTypeFilter.NEGOTIATED_ONLY.value,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Audit cases (PRD §3.7)
# ---------------------------------------------------------------------------


def audit_case_payload(submission_id, materiality_pct=_OMIT, **overrides):
    payload = {"submission_id": submission_id, "materiality_pct": materiality_pct}
    payload.update(overrides)
    return _prune(payload)


def finalize_audit_payload(verified_head, verified_value_dollars, **overrides):
    payload = {
        "verified_head": verified_head,
        "verified_value_dollars": verified_value_dollars,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Penalty assessments (PRD §3.8)
# ---------------------------------------------------------------------------


def penalty_assessment_payload(
    reporting_entity_id,
    violation_type,
    expected_reporting_entity_version,
    submission_id=_OMIT,
    audit_case_id=_OMIT,
    **overrides,
):
    payload = {
        "reporting_entity_id": reporting_entity_id,
        "violation_type": violation_type,
        "expected_reporting_entity_version": expected_reporting_entity_version,
        "submission_id": submission_id,
        "audit_case_id": audit_case_id,
    }
    payload.update(overrides)
    return _prune(payload)


def non_registration_penalty_payload(
    reporting_entity_id, expected_reporting_entity_version, **overrides
):
    return penalty_assessment_payload(
        reporting_entity_id,
        ViolationType.NON_REGISTRATION.value,
        expected_reporting_entity_version,
        **overrides,
    )


def payment_payload(paid_amount_cents, **overrides):
    payload = {"paid_amount_cents": paid_amount_cents}
    payload.update(overrides)
    return _prune(payload)


def waiver_payload(waiver_reason="Assessment waived on administrative review.", **overrides):
    payload = {"waiver_reason": waiver_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Methodology changes (PRD §3.9)
# ---------------------------------------------------------------------------


def methodology_change_payload(
    change_code="MC-2026-01",
    affected_category=ReportCategory.LIVE_STEER_HEIFER.value,
    proposed_weighting_variant=WeightingVariant.WEIGHT_WEIGHTED.value,
    comment_period_end="2026-09-05T00:00:00Z",
    effective_from="2026-10-10T00:00:00Z",
    **overrides,
):
    payload = {
        "change_code": change_code,
        "affected_category": affected_category,
        "proposed_weighting_variant": proposed_weighting_variant,
        "comment_period_end": comment_period_end,
        "effective_from": effective_from,
    }
    payload.update(overrides)
    return _prune(payload)


def public_comment_payload(
    commenter_reference="Alpha Packing Company",
    comment_text="We support moving this category to a weight-weighted average.",
    stance=CommentStance.SUPPORT.value,
    **overrides,
):
    payload = {
        "commenter_reference": commenter_reference,
        "comment_text": comment_text,
        "stance": stance,
    }
    payload.update(overrides)
    return _prune(payload)
