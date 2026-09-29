"""Payload factories — one per entity, client-supplied input fields only."""
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "CARRIER_NAME": "Atlas Mutual",
    "CARRIER_NAIC": "11111",
    "CARRIER_SHARE_BPS": 6000,
    "SECOND_CARRIER_NAME": "Beacon Casualty",
    "SECOND_CARRIER_NAIC": "22222",
    "SECOND_CARRIER_SHARE_BPS": 4000,
    "PRODUCER_NAME": "Harbor Agency",
    "PRODUCER_LICENSE": "PL-4471",
    "APPLICANT_NAME": "Owen Pike",
    "DRIVER_LICENSE": "D-99011",
    "VIN": "1HGCM82633A004360",
    "PERIOD_CODE": "2026-P3",
    "POLICY_NUMBER": "AR-100001",
    "NARRATIVE": "Acknowledgement and contact standards not met.",
}


def create_carrier_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": DEFAULTS["CARRIER_NAME"],
        "naic_code": DEFAULTS["CARRIER_NAIC"],
        "voluntary_market_share_bps": DEFAULTS["CARRIER_SHARE_BPS"],
        "licensed_territories": ["T02"],
    }
    payload.update(overrides)
    return payload


def create_producer_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": DEFAULTS["PRODUCER_NAME"],
        "license_number": DEFAULTS["PRODUCER_LICENSE"],
        "appointed_territories": ["T01", "T02", "T03"],
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": DEFAULTS["APPLICANT_NAME"],
        "driver_license_number": DEFAULTS["DRIVER_LICENSE"],
        "territory_code": "T02",
        "driver_class": "ADULT",
        "first_licensed_date": "2010-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "vin": DEFAULTS["VIN"],
        "vehicle_class_code": "PLEASURE",
        "garaging_territory_code": "T02",
        "model_year": 2019,
    }
    payload.update(overrides)
    return payload


def create_application_payload(applicant_id: str, producer_id: str, vehicle_id: str,
                               **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "producer_id": producer_id,
        "vehicle_id": vehicle_id,
        "requested_effective_date": "2026-09-15T00:00:00Z",
        "declared_violations": [],
    }
    payload.update(overrides)
    return payload


def create_market_rejection_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "rejecting_carrier_naic_code": DEFAULTS["CARRIER_NAIC"],
        "rejection_date": "2026-08-10T00:00:00Z",
        "reason_code": "UNACCEPTABLE_DRIVING_RECORD",
        "document_reference": "DEC-1",
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": amount_cents}


def create_mvr_verification_payload(verified_violations: Optional[List[Dict[str, Any]]] = None
                                    ) -> Dict[str, Any]:
    return {"verified_violations": verified_violations if verified_violations is not None else []}


def create_certification_payload(decision: str = "CERTIFY", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def create_cure_return_payload(cure_note: str = "Declination documentation is incomplete."
                               ) -> Dict[str, Any]:
    return {"cure_note": cure_note}


def create_resubmission_payload(**overrides) -> Dict[str, Any]:
    """A cured application is resubmitted with a revised requested_effective_date
    and, optionally, a corrected declared_violations array."""
    payload: Dict[str, Any] = {"requested_effective_date": "2026-09-15T00:00:00Z"}
    payload.update(overrides)
    return payload


def create_plan_period_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "period_code": DEFAULTS["PERIOD_CODE"],
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-11-30T00:00:00Z",
        "underserved_territories": ["T03"],
    }
    payload.update(overrides)
    return payload


def create_assignment_cycle_payload(plan_period_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_period_id": plan_period_id,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_rescission_payload(reason_code: str = "ASSIGNMENT_ERROR") -> Dict[str, Any]:
    return {"reason_code": reason_code}


def create_policy_payload(assignment_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "assignment_id": assignment_id,
        "policy_number": DEFAULTS["POLICY_NUMBER"],
        "effective_date": "2026-09-15T00:00:00Z",
        "expiration_date": "2027-09-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_reclassification_payload(expected_policy_version: int, reclassified_driver_class: str,
                                    reclassification_effective_date: str) -> Dict[str, Any]:
    return {
        "expected_policy_version": expected_policy_version,
        "reclassified_driver_class": reclassified_driver_class,
        "reclassification_effective_date": reclassification_effective_date,
    }


def create_cancellation_payload(cancellation_reason_code: str,
                                cancellation_effective_date: str) -> Dict[str, Any]:
    return {
        "cancellation_reason_code": cancellation_reason_code,
        "cancellation_effective_date": cancellation_effective_date,
    }


def create_non_renewal_payload(reason_note: str = "Loss experience outside plan appetite."
                               ) -> Dict[str, Any]:
    return {"reason_note": reason_note}


def create_voluntary_exit_payload(exit_note: str = "Applicant now acceptable to the voluntary market."
                                  ) -> Dict[str, Any]:
    return {"exit_note": exit_note}


def create_claim_payload(policy_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "policy_id": policy_id,
        "loss_date": "2026-09-20T00:00:00Z",
        "at_fault": False,
        "coverage_line": "PD",
        "reserve_cents": 50000,
    }
    payload.update(overrides)
    return payload


def create_claim_closure_payload(disposition: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_complaint_payload(policy_id: str, carrier_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "policy_id": policy_id,
        "carrier_id": carrier_id,
        "complaint_type": "CLAIM_HANDLING_DELAY",
        "narrative": DEFAULTS["NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def create_findings_payload(findings_note: str = "Carrier records confirm the delay.") -> Dict[str, Any]:
    return {"findings_note": findings_note}


def create_resolution_payload(disposition: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_quota_reconciliation_payload(carrier_id: str, plan_period_id: str, basis: str,
                                        expected_carrier_version: int) -> Dict[str, Any]:
    return {
        "carrier_id": carrier_id,
        "plan_period_id": plan_period_id,
        "basis": basis,
        "expected_carrier_version": expected_carrier_version,
    }


def create_exit_notice_payload(exit_effective_date: str) -> Dict[str, Any]:
    return {"exit_effective_date": exit_effective_date}


def create_licensing_amendment_payload(licensed_territories: List[str]) -> Dict[str, Any]:
    return {"licensed_territories": licensed_territories}


def create_clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
