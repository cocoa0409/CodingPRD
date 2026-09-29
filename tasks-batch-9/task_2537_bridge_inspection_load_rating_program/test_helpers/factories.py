"""
Request-payload builders for the Bridge Inspection & Load Rating Program API.

Every builder emits PRD-exact field names and omits optional fields unless the
caller supplies them, so that a test which relies on a documented default
(`spans_water` false, `impact_im_factor` 1.33, `reserve_pct` 0.05, `speed_category`
`NORMAL`, `countermeasure_type` `NONE`, the three `initial_*` ratings 7) exercises
the server's default rather than restating it.
"""

from typing import Any, Dict, List, Optional

from .constants import ELEMENT_GROUP_OF


# ─── Personnel (PRD §3.1, §2.10) ───────────────────────────────────────────
def personnel_payload(
    full_name: str,
    nbis_refresher_expiry_date: str,
    agency: str = "State DOT District 4",
    team_leader_certified: Optional[bool] = None,
    underwater_diver_certified: Optional[bool] = None,
    fracture_critical_certified: Optional[bool] = None,
    load_rating_engineer_licensed: Optional[bool] = None,
    pe_license_number: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A roster registration payload. The four capability flags "each default to
    false" and `pe_license_number` is "left null for anyone unlicensed", so each
    is sent only when the caller asks for it.
    """
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "agency": agency,
        "nbis_refresher_expiry_date": nbis_refresher_expiry_date,
    }
    if team_leader_certified is not None:
        payload["team_leader_certified"] = team_leader_certified
    if underwater_diver_certified is not None:
        payload["underwater_diver_certified"] = underwater_diver_certified
    if fracture_critical_certified is not None:
        payload["fracture_critical_certified"] = fracture_critical_certified
    if load_rating_engineer_licensed is not None:
        payload["load_rating_engineer_licensed"] = load_rating_engineer_licensed
    if pe_license_number is not None:
        payload["pe_license_number"] = pe_license_number
    payload.update(extra)
    return payload


# ─── Bridges (PRD §3.1) ────────────────────────────────────────────────────
def bridge_payload(
    nbi_structure_number: str,
    name: str = "Cedar Creek Bridge",
    owner_agency: str = "State DOT District 4",
    structure_type: str = "GIRDER",
    deck_area_sqm: float = 1000,
    year_built: int = 1972,
    adt: int = 12000,
    detour_length_km: float = 8.5,
    spans_water: Optional[bool] = None,
    underwater_elements: Optional[bool] = None,
    fracture_critical: Optional[bool] = None,
    initial_deck_rating: Optional[int] = None,
    initial_superstructure_rating: Optional[int] = None,
    initial_substructure_rating: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A structure creation payload carrying the seven required inventory fields.
    The three special-feature flags and the three `initial_*` seeds are optional
    and are sent only when the caller supplies them.
    """
    payload: Dict[str, Any] = {
        "nbi_structure_number": nbi_structure_number,
        "name": name,
        "owner_agency": owner_agency,
        "structure_type": structure_type,
        "deck_area_sqm": deck_area_sqm,
        "year_built": year_built,
        "adt": adt,
        "detour_length_km": detour_length_km,
    }
    if spans_water is not None:
        payload["spans_water"] = spans_water
    if underwater_elements is not None:
        payload["underwater_elements"] = underwater_elements
    if fracture_critical is not None:
        payload["fracture_critical"] = fracture_critical
    if initial_deck_rating is not None:
        payload["initial_deck_rating"] = initial_deck_rating
    if initial_superstructure_rating is not None:
        payload["initial_superstructure_rating"] = initial_superstructure_rating
    if initial_substructure_rating is not None:
        payload["initial_substructure_rating"] = initial_substructure_rating
    payload.update(extra)
    return payload


# ─── Inspections (PRD §3.2) ────────────────────────────────────────────────
def inspection_payload(
    team_leader_id: str,
    field_window_start: str,
    field_window_end: str,
    inspection_type: str = "ROUTINE",
    qa_reviewer_id: Optional[str] = None,
    notes: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    An inspection creation payload. `field_window_end` must be strictly later
    than `field_window_start`; `qa_reviewer_id` and `notes` are optional.
    """
    payload: Dict[str, Any] = {
        "inspection_type": inspection_type,
        "team_leader_id": team_leader_id,
        "field_window_start": field_window_start,
        "field_window_end": field_window_end,
    }
    if qa_reviewer_id is not None:
        payload["qa_reviewer_id"] = qa_reviewer_id
    if notes is not None:
        payload["notes"] = notes
    payload.update(extra)
    return payload


def element_condition_payload(
    element_key: str,
    unit: str,
    total_quantity: float,
    cs1_qty: Optional[float] = None,
    cs2_qty: Optional[float] = None,
    cs3_qty: Optional[float] = None,
    cs4_qty: Optional[float] = None,
    photo_count: Optional[int] = None,
    defect_notes: Optional[str] = None,
    element_group: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    An element-condition payload. `element_group` is not a free choice — it is
    derived from `element_key` through the mandated grouping of PRD §3.2 unless
    the caller deliberately overrides it to test the disagreement rule.
    """
    payload: Dict[str, Any] = {
        "element_key": element_key,
        "element_group": (
            element_group if element_group is not None else ELEMENT_GROUP_OF[element_key]
        ),
        "unit": unit,
        "total_quantity": total_quantity,
    }
    for field, value in (
        ("cs1_qty", cs1_qty),
        ("cs2_qty", cs2_qty),
        ("cs3_qty", cs3_qty),
        ("cs4_qty", cs4_qty),
        ("photo_count", photo_count),
        ("defect_notes", defect_notes),
    ):
        if value is not None:
            payload[field] = value
    payload.update(extra)
    return payload


def element_update_payload(
    total_quantity: float,
    cs1_qty: float,
    cs2_qty: float,
    cs3_qty: float,
    cs4_qty: float,
    photo_count: Optional[int] = None,
    defect_notes: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A redistribution payload for PUT /element-conditions/{id}, "resupplying
    `total_quantity`, the four condition-state quantities and optionally
    `photo_count` and `defect_notes`" (PRD §3.2).
    """
    payload: Dict[str, Any] = {
        "total_quantity": total_quantity,
        "cs1_qty": cs1_qty,
        "cs2_qty": cs2_qty,
        "cs3_qty": cs3_qty,
        "cs4_qty": cs4_qty,
    }
    if photo_count is not None:
        payload["photo_count"] = photo_count
    if defect_notes is not None:
        payload["defect_notes"] = defect_notes
    payload.update(extra)
    return payload


# The baseline routine element set. Its four rows are the worked example of
# PRD §3.2 and §3.3: a deck at 82.00, a girder at 40.00, a bearing at 50.00 and
# an abutment at 95.00, which roll up to group indices of 82.00, 42.86 and 95.00,
# component ratings of 7, 3 and 8, and a bridge health index of 65.47.
BASELINE_DECK = element_condition_payload(
    "DECK", "SQM", 1000, 600, 200, 150, 50, photo_count=6, defect_notes="Deck spalling"
)
BASELINE_GIRDER = element_condition_payload(
    "GIRDER", "M", 300, 0, 100, 100, 100, photo_count=8, defect_notes="Girder section loss"
)
BASELINE_BEARING = element_condition_payload(
    "BEARING", "EA", 4, 0, 2, 1, 1, photo_count=4, defect_notes="Frozen bearing at pier 1"
)
BASELINE_ABUTMENT = element_condition_payload(
    "ABUTMENT", "EA", 4, 3, 1, 0, 0, photo_count=1, defect_notes="Minor map cracking"
)

BASELINE_ELEMENT_SET: List[Dict[str, Any]] = [
    BASELINE_DECK,
    BASELINE_GIRDER,
    BASELINE_BEARING,
    BASELINE_ABUTMENT,
]


def submit_payload(inspection_date: str, **extra: Any) -> Dict[str, Any]:
    """The submit payload of PRD §3.3, carrying the observation instant."""
    payload: Dict[str, Any] = {"inspection_date": inspection_date}
    payload.update(extra)
    return payload


def qa_decision_payload(
    decision: str, return_note: Optional[str] = None, **extra: Any
) -> Dict[str, Any]:
    """A QA decision payload: `decision` is `RETURN` or `ACCEPT` (PRD §3.3)."""
    payload: Dict[str, Any] = {"decision": decision}
    if return_note is not None:
        payload["return_note"] = return_note
    payload.update(extra)
    return payload


# ─── Critical findings (PRD §3.5) ──────────────────────────────────────────
def critical_finding_payload(
    bridge_id: str,
    source_inspection_id: str,
    severity: str,
    description: str = "Severe section loss observed at the girder web",
    element_condition_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A critical-finding payload. `element_condition_id` is optional for an
    `URGENT` finding and mandatory for an `IMMEDIATE` one (PRD §3.5).
    """
    payload: Dict[str, Any] = {
        "bridge_id": bridge_id,
        "source_inspection_id": source_inspection_id,
        "severity": severity,
        "description": description,
    }
    if element_condition_id is not None:
        payload["element_condition_id"] = element_condition_id
    payload.update(extra)
    return payload


def restriction_payload(
    action: str, authorized_by_id: str, **extra: Any
) -> Dict[str, Any]:
    """A restriction payload: `action` is `RESTRICT` or `CLOSE` (PRD §3.5)."""
    payload: Dict[str, Any] = {"action": action, "authorized_by_id": authorized_by_id}
    payload.update(extra)
    return payload


def notify_payload(
    tier: str,
    channel: str = "EMAIL",
    recipient_label: str = "County Bridge Owner",
    **extra: Any,
) -> Dict[str, Any]:
    """One link of the notification chain (PRD §3.5)."""
    payload: Dict[str, Any] = {
        "tier": tier,
        "channel": channel,
        "recipient_label": recipient_label,
    }
    payload.update(extra)
    return payload


# ─── Load ratings (PRD §3.4) ───────────────────────────────────────────────
def load_rating_payload(
    expected_bridge_version: int,
    source_inspection_id: str,
    capacity_c_kn_m: float = 2000,
    dead_load_dc_kn_m: float = 600,
    dead_load_dw_kn_m: float = 150,
    live_load_ll_kn_m: float = 500,
    method: str = "LRFR",
    rating_vehicle: str = "HL93",
    impact_im_factor: Optional[float] = None,
    system_factor_phi_s: Optional[float] = None,
    resistance_factor_phi: Optional[float] = None,
    rating_effective_date: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A load-rating creation payload. The default load effects are the first
    worked case of PRD §3.4 (capacity 2000, dead loads 600 and 150, live load
    500). The three resistance and allowance factors are omitted so the server
    applies its documented defaults of 1.33, 1.00 and 0.90.
    """
    payload: Dict[str, Any] = {
        "expected_bridge_version": expected_bridge_version,
        "source_inspection_id": source_inspection_id,
        "method": method,
        "rating_vehicle": rating_vehicle,
        "capacity_c_kn_m": capacity_c_kn_m,
        "dead_load_dc_kn_m": dead_load_dc_kn_m,
        "dead_load_dw_kn_m": dead_load_dw_kn_m,
        "live_load_ll_kn_m": live_load_ll_kn_m,
    }
    for field, value in (
        ("impact_im_factor", impact_im_factor),
        ("system_factor_phi_s", system_factor_phi_s),
        ("resistance_factor_phi", resistance_factor_phi),
        ("rating_effective_date", rating_effective_date),
    ):
        if value is not None:
            payload[field] = value
    payload.update(extra)
    return payload


def seal_payload(sealed_by_id: str, **extra: Any) -> Dict[str, Any]:
    """A seal payload; `sealed_by_id` "must be their own identifier" (PRD §3.4)."""
    payload: Dict[str, Any] = {"sealed_by_id": sealed_by_id}
    payload.update(extra)
    return payload


def approve_rating_payload(approved_by_id: str, **extra: Any) -> Dict[str, Any]:
    """An approval payload; `approved_by_id` equals the approver's own id."""
    payload: Dict[str, Any] = {"approved_by_id": approved_by_id}
    payload.update(extra)
    return payload


def reject_rating_payload(
    rejection_note: str = "Capacity assumption not supported by the plans", **extra: Any
) -> Dict[str, Any]:
    """A rejection payload recording the `rejection_note` of PRD §3.4."""
    payload: Dict[str, Any] = {"rejection_note": rejection_note}
    payload.update(extra)
    return payload


# ─── Permit applications (PRD §3.7) ────────────────────────────────────────
def permit_application_payload(
    permit_number: str,
    route_bridge_ids: List[str],
    axle_loads_tons: Optional[List[float]] = None,
    carrier_name: str = "Ridgeline Heavy Haul",
    speed_category: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A permit application payload. The default axle array is the worked example of
    PRD §3.7 — five axles of 8.25, 8.25, 8.25, 8.25 and 6.4 tons, which round per
    axle to 8.3, 8.3, 8.3, 8.3 and 6.4 and sum to a gross weight of 39.6 tons.
    `speed_category` is omitted so the documented `NORMAL` default applies.
    """
    payload: Dict[str, Any] = {
        "permit_number": permit_number,
        "carrier_name": carrier_name,
        "axle_loads_tons": (
            axle_loads_tons if axle_loads_tons is not None else [8.25, 8.25, 8.25, 8.25, 6.4]
        ),
        "route_bridge_ids": route_bridge_ids,
    }
    if speed_category is not None:
        payload["speed_category"] = speed_category
    payload.update(extra)
    return payload


def permit_decision_payload(
    decision: str, decision_note: Optional[str] = None, **extra: Any
) -> Dict[str, Any]:
    """A permit decision payload; the decision must equal the recommendation."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    payload.update(extra)
    return payload


# ─── Scour (PRD §3.6) ──────────────────────────────────────────────────────
def scour_evaluation_payload(
    evaluated_by_id: str,
    scour_code: int,
    evaluation_method: str = "HEC18_SCREENING",
    foundation_type: Optional[str] = None,
    observed_scour_depth_m: Optional[float] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A scour evaluation payload. `foundation_type` and `observed_scour_depth_m`
    are the two optional inputs of PRD §3.6, the latter defaulting to 0.
    """
    payload: Dict[str, Any] = {
        "evaluated_by_id": evaluated_by_id,
        "evaluation_method": evaluation_method,
        "scour_code": scour_code,
    }
    if foundation_type is not None:
        payload["foundation_type"] = foundation_type
    if observed_scour_depth_m is not None:
        payload["observed_scour_depth_m"] = observed_scour_depth_m
    payload.update(extra)
    return payload


def plan_of_action_payload(
    monitoring_frequency_months: int,
    closure_trigger_stage_m: float,
    countermeasure_type: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A plan-of-action draft payload. All three commitments of PRD §3.6 are
    accepted; `countermeasure_type` is omitted when the caller wants the
    documented `NONE` default.
    """
    payload: Dict[str, Any] = {
        "monitoring_frequency_months": monitoring_frequency_months,
        "closure_trigger_stage_m": closure_trigger_stage_m,
    }
    if countermeasure_type is not None:
        payload["countermeasure_type"] = countermeasure_type
    payload.update(extra)
    return payload


def plan_decision_payload(
    decision: str,
    approved_by_id: Optional[str] = None,
    return_note: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """A plan decision payload: `decision` is `APPROVE` or `RETURN` (PRD §3.6)."""
    payload: Dict[str, Any] = {"decision": decision}
    if approved_by_id is not None:
        payload["approved_by_id"] = approved_by_id
    if return_note is not None:
        payload["return_note"] = return_note
    payload.update(extra)
    return payload


# ─── Programming (PRD §3.8) ────────────────────────────────────────────────
def program_cycle_payload(
    fiscal_year: int = 2027,
    authorized_budget_cents: int = 10000000000,
    ranking_policy: Optional[str] = None,
    reserve_pct: Optional[float] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A cycle payload. The default authorised budget is the worked example of
    PRD §3.8 (10,000,000,000 cents). `ranking_policy` and `reserve_pct` are
    omitted so the documented `CONDITION_BASED` and 0.05 defaults apply.
    """
    payload: Dict[str, Any] = {
        "fiscal_year": fiscal_year,
        "authorized_budget_cents": authorized_budget_cents,
    }
    if ranking_policy is not None:
        payload["ranking_policy"] = ranking_policy
    if reserve_pct is not None:
        payload["reserve_pct"] = reserve_pct
    payload.update(extra)
    return payload


def candidate_payload(
    expected_program_cycle_version: int,
    bridge_id: str,
    source_inspection_id: Optional[str] = None,
    justification: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    A candidate identification payload. `source_inspection_id` is optional and
    "when omitted this defaults to the structure's latest `ACCEPTED` inspection".
    """
    payload: Dict[str, Any] = {
        "expected_program_cycle_version": expected_program_cycle_version,
        "bridge_id": bridge_id,
    }
    if source_inspection_id is not None:
        payload["source_inspection_id"] = source_inspection_id
    if justification is not None:
        payload["justification"] = justification
    payload.update(extra)
    return payload


# ─── Federal reporting (PRD §3.9) ──────────────────────────────────────────
def federal_submission_payload(
    submission_type: str = "NBI_ANNUAL", **extra: Any
) -> Dict[str, Any]:
    """A federal submission payload carrying the `submission_type` of PRD §3.9."""
    payload: Dict[str, Any] = {"submission_type": submission_type}
    payload.update(extra)
    return payload


def review_payload(decision: str, **extra: Any) -> Dict[str, Any]:
    """A review payload: `decision` is `ACCEPT` or `REJECT` (PRD §3.9)."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(extra)
    return payload
