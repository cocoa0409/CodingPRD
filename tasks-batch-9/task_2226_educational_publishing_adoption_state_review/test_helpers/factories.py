"""Payload builders with contract-valid defaults.

Each factory produces a request body that satisfies every field-level rule the
PRD states, so a test only has to name the one or two values it actually cares
about. Overrides are applied last, and passing ``None`` for a key removes it
entirely, which is how a test exercises a missing required field.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    ACCESSIBILITY_WCAG_2_1_AA,
    ADOPTION_MODEL_OPEN_TERRITORY,
    COMMENT_CATEGORY_OTHER,
    DEPTH_MASTERY,
    EDIT_TYPE_ADD_REQUIRED_TOPIC,
    INVENTORY_RECEIPT,
    ROSTERING_ONEROSTER_1_2,
    SEVERITY_MINOR,
    VOTE_RECOMMEND,
)

JsonDict = Dict[str, Any]

_isbn_counter = itertools.count(1)
_bundle_counter = itertools.count(1)
_district_counter = itertools.count(1)


def _merge(base: JsonDict, overrides: JsonDict) -> JsonDict:
    """Apply overrides to a base payload; a ``None`` value drops the key."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def next_isbn_base() -> str:
    """A fresh thirteen-character ISBN base, unique within the process."""
    return f"978{next(_isbn_counter):010d}"


def next_bundle_code() -> str:
    """A bundle code unique within the process."""
    return f"BND-{next(_bundle_counter):04d}"


def next_district_ref() -> str:
    """A district reference unique within the process."""
    return f"DIST-{next(_district_counter):04d}"


# ---------------------------------------------------------------------------
# States and frameworks
# ---------------------------------------------------------------------------


def state_profile_payload(state_code: str = "TX", **overrides: Any) -> JsonDict:
    """An open-territory state that imposes no sampling and a low coverage floor."""
    return _merge(
        {
            "state_code": state_code,
            "adoption_model": ADOPTION_MODEL_OPEN_TERRITORY,
            "sampling_copies_required": 0,
            "min_verified_coverage_pct": 50.00,
        },
        overrides,
    )


def state_standard_payload(
    standard_code: str,
    subject: str = "MATH",
    grade_low: int = 5,
    grade_high: int = 5,
    weight: int = 3,
    **overrides: Any,
) -> JsonDict:
    """One academic standard in a state's framework for a subject and grade band."""
    return _merge(
        {
            "subject": subject,
            "standard_code": standard_code,
            "grade_low": grade_low,
            "grade_high": grade_high,
            "weight": weight,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# The adoption calendar
# ---------------------------------------------------------------------------

#: The calendar every fixture reuses: the window opens 2026-09-01 and closes
#: 2026-10-01, committee review starts 2026-10-15, public comment runs through
#: November and the decision lands 2026-12-01.
STANDARD_CALENDAR = {
    "submission_open_at": "2026-09-01T00:00:00Z",
    "submission_deadline_at": "2026-10-01T00:00:00Z",
    "committee_review_at": "2026-10-15T00:00:00Z",
    "public_comment_start_at": "2026-11-01T00:00:00Z",
    "public_comment_end_at": "2026-11-15T00:00:00Z",
    "adoption_decision_at": "2026-12-01T00:00:00Z",
}


def adoption_cycle_payload(
    state_id: str,
    subject: str = "MATH",
    cycle_year: int = 2027,
    contract_term_years: int = 6,
    **overrides: Any,
) -> JsonDict:
    """A cycle on the standard calendar."""
    return _merge(
        {
            "state_id": state_id,
            "subject": subject,
            "cycle_year": cycle_year,
            "contract_term_years": contract_term_years,
            **STANDARD_CALENDAR,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def title_payload(
    subject: str = "MATH",
    grade_low: int = 5,
    grade_high: int = 5,
    page_count: int = 300,
    signature_page_capacity: int = 384,
    list_price_cents: int = 9000,
    isbn_base: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    """A draft print edition with room left in its signature budget."""
    return _merge(
        {
            "isbn_base": isbn_base or next_isbn_base(),
            "subject": subject,
            "grade_low": grade_low,
            "grade_high": grade_high,
            "copyright_year": 2026,
            "content_tags": ["NUMBER_SENSE"],
            "page_count": page_count,
            "signature_page_capacity": signature_page_capacity,
            "list_price_cents": list_price_cents,
        },
        overrides,
    )


def inventory_receipt_payload(units: int, **overrides: Any) -> JsonDict:
    """Receive print units into the warehouse."""
    return _merge(
        {
            "adjustment_type": INVENTORY_RECEIPT,
            "units": units,
            "reason": "Printing received into the warehouse.",
        },
        overrides,
    )


def ancillary_bundle_payload(
    component_count: int = 4,
    component_list_total_cents: int = 40000,
    digital_seat_price_cents: int = 1500,
    **overrides: Any,
) -> JsonDict:
    """A bundle that meets the default digital platform commitments."""
    return _merge(
        {
            "bundle_code": next_bundle_code(),
            "component_count": component_count,
            "component_list_total_cents": component_list_total_cents,
            "digital_seat_price_cents": digital_seat_price_cents,
            "rostering_standard": ROSTERING_ONEROSTER_1_2,
            "accessibility_conformance": ACCESSIBILITY_WCAG_2_1_AA,
            "privacy_addendum_signed": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Content editing
# ---------------------------------------------------------------------------


def content_edit_payload(
    title_id: str,
    state_id: str,
    topic_code: str = "DATA_LITERACY",
    pages_delta: int = 24,
    **overrides: Any,
) -> JsonDict:
    """A proposal to add a state-required topic to an edition."""
    return _merge(
        {
            "title_id": title_id,
            "state_id": state_id,
            "edit_type": EDIT_TYPE_ADD_REQUIRED_TOPIC,
            "topic_code": topic_code,
            "pages_delta": pages_delta,
            "rationale": "Adds the state-required strand to the affected unit.",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


def submission_payload(cycle_id: str, title_id: str, **overrides: Any) -> JsonDict:
    """Start a draft submission of one title into one cycle."""
    return _merge({"cycle_id": cycle_id, "title_id": title_id}, overrides)


def correlation_payload(
    standard_code: str,
    depth_level: str = DEPTH_MASTERY,
    **overrides: Any,
) -> JsonDict:
    """One correlation entry with an evidence citation of legal length."""
    return _merge(
        {
            "standard_code": standard_code,
            "depth_level": depth_level,
            "page_reference": "pp. 20-58",
            "evidence_citation": (
                "The unit develops and assesses the standard across its lessons."
            ),
        },
        overrides,
    )


def sampling_shipment_payload(units: int, **overrides: Any) -> JsonDict:
    """Ship print sample copies toward the state's sampling requirement."""
    return _merge(
        {"units": units, "carrier_ref": f"SAMPLE-{units:04d}"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Public comment
# ---------------------------------------------------------------------------


def public_comment_payload(
    commenter_ref: str = "parent-01",
    severity: str = SEVERITY_MINOR,
    category: str = COMMENT_CATEGORY_OTHER,
    **overrides: Any,
) -> JsonDict:
    """A public comment against a filed submission."""
    return _merge(
        {
            "commenter_ref": commenter_ref,
            "category": category,
            "severity": severity,
            "body": "The index omits three of the key vocabulary terms.",
        },
        overrides,
    )


def comment_response_payload(**overrides: Any) -> JsonDict:
    """The publisher's answer to a public comment."""
    return _merge(
        {"response_body": "The correction ships in the next printing."},
        overrides,
    )


# ---------------------------------------------------------------------------
# Panels, slots and ballots
# ---------------------------------------------------------------------------


def committee_panel_payload(
    cycle_id: str,
    panel_label: str = "Panel A",
    session_start_at: str = "2026-10-20T14:00:00Z",
    session_end_at: str = "2026-10-20T18:00:00Z",
    member_count: int = 3,
    quorum_required: int = 2,
    buffer_minutes: int = 10,
    **overrides: Any,
) -> JsonDict:
    """A four-hour panel sitting with a ten-minute turnover buffer."""
    return _merge(
        {
            "cycle_id": cycle_id,
            "panel_label": panel_label,
            "session_start_at": session_start_at,
            "session_end_at": session_end_at,
            "buffer_minutes": buffer_minutes,
            "member_count": member_count,
            "quorum_required": quorum_required,
        },
        overrides,
    )


def slot_payload(
    submission_id: str,
    expected_panel_version: Any,
    start_at: str = "2026-10-20T14:00:00Z",
    end_at: str = "2026-10-20T14:30:00Z",
    **overrides: Any,
) -> JsonDict:
    """A half-hour presentation slot inside the panel's sitting."""
    return _merge(
        {
            "submission_id": submission_id,
            "start_at": start_at,
            "end_at": end_at,
            "expected_panel_version": expected_panel_version,
        },
        overrides,
    )


def vote_payload(vote: str = VOTE_RECOMMEND, **overrides: Any) -> JsonDict:
    """One committee ballot with a rationale of legal length."""
    return _merge(
        {"vote": vote, "rationale": "The evidence supports this recommendation."},
        overrides,
    )


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def pricing_proposal_payload(
    submission_id: str,
    expected_submission_version: Any,
    base_price_cents: int = 9000,
    term_years: int = 1,
    annual_escalator_bps: int = 0,
    projected_adoption_units: int = 100,
    digital_seat_price_cents: int = 1500,
    **overrides: Any,
) -> JsonDict:
    """A price filing that earns no discount tier unless a test asks for one."""
    return _merge(
        {
            "submission_id": submission_id,
            "base_price_cents": base_price_cents,
            "term_years": term_years,
            "annual_escalator_bps": annual_escalator_bps,
            "projected_adoption_units": projected_adoption_units,
            "digital_seat_price_cents": digital_seat_price_cents,
            "expected_submission_version": expected_submission_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# District sales
# ---------------------------------------------------------------------------


def district_order_payload(
    state_id: str,
    title_id: str,
    print_units: int = 100,
    digital_seats: int = 0,
    district_ref: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    """A quote for one district against one released title."""
    return _merge(
        {
            "district_ref": district_ref or next_district_ref(),
            "state_id": state_id,
            "title_id": title_id,
            "print_units": print_units,
            "digital_seats": digital_seats,
        },
        overrides,
    )
