"""Lightweight typed shapes for the dictionaries the fixtures hand back."""

from typing import Any, Dict, List, Optional, TypedDict


class Envelope(TypedDict):
    meta: Dict[str, Any]
    response_type: str
    data: Any


class Scenario(TypedDict, total=False):
    """Ids captured while a fixture walks a request through the workflow."""

    fee_rule_id: str
    facility_id: str
    patient_id: str
    requester_id: str
    authorization_id: str
    request_id: str
    segment_ids: List[str]
    segment_id: Optional[str]
    invoice_id: Optional[str]
    delivery_id: Optional[str]
    denial_id: Optional[str]
    amendment_id: Optional[str]
    facility_admin_headers: Dict[str, str]
    requester_headers: Dict[str, str]


class SegmentSpec(TypedDict, total=False):
    """One compilation task to open and dispose of inside a fixture."""

    category: str
    page_count: int
    source_system: str
    disposition: str
    unavailable_reason: str
    legacy_job_start_at: str
