"""Payload factories - one per write endpoint, input fields only."""
import itertools

from .constants import CLOCK_DEFAULT_NOW, DEFAULTS, TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so uniqueness-scoped names never collide by accident."""
    return f"{next(_counter):04d}"


def set_clock_payload(to_iso8601: str = CLOCK_DEFAULT_NOW, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_advertiser_payload(**overrides) -> dict:
    payload = {
        "name": f"Northwind Media {unique_suffix()}",
        "credit_cap_cents": TEST_DEFAULTS["CREDIT_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_publisher_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "name": f"Beacon Digital {suffix}",
        "primary_domain": f"beacon{suffix}.example.com",
        "sourced_traffic_pct": DEFAULTS["PUBLISHER_SOURCED_TRAFFIC_PCT"],
    }
    payload.update(overrides)
    return payload


def change_publisher_status_payload(new_status: str, **overrides) -> dict:
    payload = {"new_status": new_status}
    payload.update(overrides)
    return payload


def create_methodology_version_payload(
    standard_family: str = "VIEWABILITY",
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: str = "2027-01-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "standard_family": standard_family,
        "version_code": f"{standard_family[:4]}-{unique_suffix()}",
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def conclude_audit_payload(outcome: str = "PASSED", **overrides) -> dict:
    payload = {"outcome": outcome, "audit_finding_rate": 0.01}
    if outcome == "DEFICIENT":
        payload["deficiency_note"] = "Sampling plan does not cover mobile web"
        payload["audit_finding_rate"] = 0.30
    payload.update(overrides)
    return payload


def create_campaign_payload(advertiser_id: str, **overrides) -> dict:
    payload = {
        "advertiser_id": advertiser_id,
        "name": f"Q3 Display {unique_suffix()}",
        "cpm_cents": TEST_DEFAULTS["CPM_CENTS"],
        "min_suitability_tier": "MEDIUM_RISK",
        "format": "DISPLAY",
        "target_coverage_rate": DEFAULTS["CAMPAIGN_TARGET_COVERAGE_RATE"],
    }
    payload.update(overrides)
    return payload


def create_inventory_list_payload(advertiser_id: str, **overrides) -> dict:
    payload = {
        "advertiser_id": advertiser_id,
        "list_type": "EXCLUSION",
        "name": f"Q3 blocks {unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def create_list_entry_payload(
    entry_type: str = "DOMAIN", entry_value: str = "other.example.com", **overrides
) -> dict:
    payload = {"entry_type": entry_type, "entry_value": entry_value}
    payload.update(overrides)
    return payload


def create_pre_bid_segment_payload(campaign_id: str, **overrides) -> dict:
    payload = {"campaign_id": campaign_id, "suitability_floor_tier": "MEDIUM_RISK"}
    payload.update(overrides)
    return payload


def create_page_payload(publisher_id: str, url: str = None, **overrides) -> dict:
    payload = {
        "publisher_id": publisher_id,
        "url": url or f"https://beacon.example.com/story-{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def create_page_classification_payload(
    page_id: str, methodology_version_id: str, expected_page_version: int, **overrides
) -> dict:
    payload = {
        "page_id": page_id,
        "methodology_version_id": methodology_version_id,
        "expected_page_version": expected_page_version,
        "classifier_kind": "MODEL",
        "category_codes": ["GENERAL"],
        "ad_density_ratio": 0.10,
        "refresh_seconds": 0,
        "originality_score": 90,
    }
    payload.update(overrides)
    return payload


def review_classification_payload(decision: str = "CONFIRM", **overrides) -> dict:
    payload = {"decision": decision}
    if decision == "CONFIRM":
        payload["review_note"] = "Tier accepted as scored"
    payload.update(overrides)
    return payload


def create_appeal_payload(classification_id: str, **overrides) -> dict:
    payload = {
        "classification_id": classification_id,
        "reason_code": "CATEGORY_MISREAD",
        "evidence_note": "The article is a news report, not weapons promotion.",
    }
    payload.update(overrides)
    return payload


def submit_evidence_payload(**overrides) -> dict:
    payload = {"evidence_note": f"Further evidence round {unique_suffix()}"}
    payload.update(overrides)
    return payload


def decide_appeal_payload(outcome: str = "UPHELD", **overrides) -> dict:
    payload = {"outcome": outcome, "decision_note": f"Decision {outcome}"}
    payload.update(overrides)
    return payload


def create_measurement_batch_payload(
    campaign_id: str,
    publisher_id: str,
    page_id: str,
    methodology_version_id: str,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-01T01:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "publisher_id": publisher_id,
        "page_id": page_id,
        "methodology_version_id": methodology_version_id,
        "format": "DISPLAY",
        "window_start": window_start,
        "window_end": window_end,
        "measured_impressions": TEST_DEFAULTS["MEASURED_IMPRESSIONS"],
        "measurable_impressions": TEST_DEFAULTS["MEASURABLE_IMPRESSIONS"],
        "in_view_impressions": TEST_DEFAULTS["IN_VIEW_IMPRESSIONS"],
        "avg_in_view_seconds": TEST_DEFAULTS["AVG_IN_VIEW_SECONDS"],
        "avg_in_view_pixel_pct": TEST_DEFAULTS["AVG_IN_VIEW_PIXEL_PCT"],
    }
    payload.update(overrides)
    return payload


def create_ivt_finding_payload(batch_id: str, **overrides) -> dict:
    payload = {
        "batch_id": batch_id,
        "ivt_class": "DATACENTER",
        "flagged_impressions": 400,
        "confidence": 0.90,
    }
    payload.update(overrides)
    return payload


def retract_finding_payload(**overrides) -> dict:
    payload = {"retract_reason": "Detector signature withdrawn"}
    payload.update(overrides)
    return payload


def create_refund_claim_payload(
    campaign_id: str, publisher_id: str, batch_ids: list, expected_campaign_version: int,
    **overrides,
) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "publisher_id": publisher_id,
        "batch_ids": list(batch_ids),
        "expected_campaign_version": expected_campaign_version,
    }
    payload.update(overrides)
    return payload


def reject_claim_payload(reject_reason_code: str = "EVIDENCE_INSUFFICIENT", **overrides) -> dict:
    payload = {"reject_reason_code": reject_reason_code}
    payload.update(overrides)
    return payload


def reverse_claim_payload(**overrides) -> dict:
    payload = {"reversal_reason": "Settlement disputed by the publisher"}
    payload.update(overrides)
    return payload
