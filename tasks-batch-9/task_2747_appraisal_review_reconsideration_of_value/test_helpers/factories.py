"""
Request payload factories for the Lender Appraisal Review Desk API.

Every factory returns a valid request body built from the PRD field tables, with
keyword overrides for the one or two fields a test actually cares about. All
monetary amounts are plain Python integers (cents) and all basis-point values are
plain integers, never strings, because the PRD persists integer cents and integer
basis points.

Passing ``None`` explicitly for an optional field keeps the key with a null value;
omitting the keyword leaves the key out of the body entirely. Use
``drop=("field",)`` to remove a key that the factory would otherwise supply, which
is how a test exercises a missing required field.
"""

import itertools
from typing import Any, Dict, Iterable, List, Optional

from .constants import CLOCK_EPOCH, REQUIRED_SECTIONS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def _apply(body: Dict[str, Any], overrides: Dict[str, Any],
           drop: Iterable[str] = ()) -> Dict[str, Any]:
    body.update(overrides)
    for key in drop:
        body.pop(key, None)
    return body


# ---------------------------------------------------------------------------
# LoanFile (PRD 3.1)
# ---------------------------------------------------------------------------
def loan_file_payload(drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """A REFINANCE loan file; contract_price_cents is absent as REFINANCE requires."""
    body: Dict[str, Any] = {
        "loan_number": f"LN-{_seq():05d}",
        "loan_purpose": "REFINANCE",
        "market_type": "SUBURBAN",
        "risk_tier": "STANDARD",
        "loan_amount_cents": 30000000,
        "borrower_display_name": "Ada Borrower",
    }
    return _apply(body, overrides, drop)


def purchase_loan_file_payload(drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """A PURCHASE loan file, which must carry a positive contract_price_cents."""
    body: Dict[str, Any] = {
        "loan_number": f"LN-{_seq():05d}",
        "loan_purpose": "PURCHASE",
        "market_type": "SUBURBAN",
        "risk_tier": "STANDARD",
        "loan_amount_cents": 40000000,
        "contract_price_cents": 50000000,
        "borrower_display_name": "Ada Borrower",
    }
    return _apply(body, overrides, drop)


def underwriting_status_payload(target_status: str, **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"target_status": target_status}
    return _apply(body, overrides)


# ---------------------------------------------------------------------------
# Appraiser (PRD 3.2)
# ---------------------------------------------------------------------------
def appraiser_payload(drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    n = _seq()
    body: Dict[str, Any] = {
        "full_name": f"Appraiser {n}",
        "license_number": f"CA-LIC-{n:05d}",
        "license_state": "CA",
    }
    return _apply(body, overrides, drop)


def panel_review_payload(panel_action: str, expected_appraiser_version: int,
                         drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "panel_action": panel_action,
        "expected_appraiser_version": expected_appraiser_version,
    }
    return _apply(body, overrides, drop)


# ---------------------------------------------------------------------------
# AMC (PRD 3.2)
# ---------------------------------------------------------------------------
def amc_payload(drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """An AMC with every optional configuration field omitted so the declared
    defaults apply; pass keywords to pin any of them."""
    body: Dict[str, Any] = {"name": f"AMC {_seq():05d}"}
    return _apply(body, overrides, drop)


def panel_membership_payload(appraiser_id: str, amc_id: str,
                            expected_appraiser_version: int,
                            drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "appraiser_id": appraiser_id,
        "amc_id": amc_id,
        "coverage_state": "CA",
        "tier": "GENERAL",
        "expected_appraiser_version": expected_appraiser_version,
    }
    return _apply(body, overrides, drop)


# ---------------------------------------------------------------------------
# Appraisal (PRD 3.3)
# ---------------------------------------------------------------------------
COMPLETE_SECTIONS = list(REQUIRED_SECTIONS)
BENIGN_NARRATIVE = "Average condition, typical marketability for the market area."


def appraisal_payload(loan_file_id: str, appraiser_id: str, amc_id: str,
                      expected_loan_file_version: int,
                      drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "loan_file_id": loan_file_id,
        "appraiser_id": appraiser_id,
        "amc_id": amc_id,
        "report_form_type": "FORM_1004",
        "effective_date": "2026-07-15T00:00:00Z",
        "reported_value_cents": 40000000,
        "sections_present": list(COMPLETE_SECTIONS),
        "exhibit_count": 7,
        "narrative_text": BENIGN_NARRATIVE,
        "subject_census_tract_band": "A",
        "expected_loan_file_version": expected_loan_file_version,
    }
    return _apply(body, overrides, drop)


def comparable_payload(street_address: str, drop: Iterable[str] = (),
                       **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "street_address": street_address,
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
        "sale_status": "CLOSED",
        "dwelling_type": "SFR",
        "census_tract_band": "A",
    }
    return _apply(body, overrides, drop)


def version_payload(expected_appraisal_version: int, **overrides) -> Dict[str, Any]:
    """Body for the two appraisal-scoped run endpoints, which carry only the guard."""
    body: Dict[str, Any] = {"expected_appraisal_version": expected_appraisal_version}
    return _apply(body, overrides)


def communication_payload(recipient: str, intent: str, body_text: str,
                          drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "recipient": recipient,
        "intent": intent,
        "body": body_text,
    }
    return _apply(body, overrides, drop)


def adjudicate_payload(disposition: str, rationale: str,
                       drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"disposition": disposition, "rationale": rationale}
    return _apply(body, overrides, drop)


# ---------------------------------------------------------------------------
# DeskReview (PRD 3.6)
# ---------------------------------------------------------------------------
def desk_review_payload(appraisal_id: str, expected_appraisal_version: int,
                        drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "appraisal_id": appraisal_id,
        "expected_appraisal_version": expected_appraisal_version,
        "reviewer_note": "Opening desk review of the delivered report.",
    }
    return _apply(body, overrides, drop)


def desk_review_submit_payload(**overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"findings_note": "Grid and narrative reviewed."}
    return _apply(body, overrides)


def desk_review_decide_payload(decision_action: str, **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "decision_action": decision_action,
        "decision_note": "Panel authority decision recorded.",
    }
    return _apply(body, overrides)


# ---------------------------------------------------------------------------
# EscalationOrder (PRD 3.7)
# ---------------------------------------------------------------------------
def assign_payload(appraiser_id: str, window_start: str, window_end: str,
                   drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "assigned_appraiser_id": appraiser_id,
        "inspection_window_start": window_start,
        "inspection_window_end": window_end,
    }
    return _apply(body, overrides, drop)


def complete_order_payload(resulting_value_cents: int,
                           drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "resulting_value_cents": resulting_value_cents,
        "documentation_note": "Field work complete; value supported by the enclosed grid.",
    }
    return _apply(body, overrides, drop)


def cancel_order_payload(**overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"cancel_reason": "Escalation withdrawn by the panel authority."}
    return _apply(body, overrides)


# ---------------------------------------------------------------------------
# ROVRequest (PRD 3.8)
# ---------------------------------------------------------------------------
def rov_request_payload(loan_file_id: str, appraisal_id: str,
                        requested_value_cents: int = 42000000,
                        drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "loan_file_id": loan_file_id,
        "appraisal_id": appraisal_id,
        "borrower_statement": "The report omits two recent closed sales on my street.",
        "requested_value_cents": requested_value_cents,
        "intake_note": "Reconsideration of value opened at borrower request.",
    }
    return _apply(body, overrides, drop)


def evidence_payload(evidence_type: str, drop: Iterable[str] = (),
                     **overrides) -> Dict[str, Any]:
    """A CLOSED_SALE-shaped evidence item; other types drop the sale attributes."""
    body: Dict[str, Any] = {"evidence_type": evidence_type}
    if evidence_type in ("CLOSED_SALE", "ACTIVE_LISTING_WITH_CONTRACT"):
        body.update({
            "street_address": "10 Evidence Lane",
            "sale_price_cents": 42000000,
            "sale_date": "2026-06-01T00:00:00Z",
            "distance_miles": 1.0,
        })
    elif evidence_type == "DATA_ERROR_CITATION":
        body.update({
            "street_address": "10 Evidence Lane",
            "citation_note": "Gross living area transcribed from the wrong tax card.",
        })
    else:
        body.update({"street_address": "10 Evidence Lane"})
    return _apply(body, overrides, drop)


def rov_submit_payload(**overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"intake_note": "Evidence tally confirmed before routing."}
    return _apply(body, overrides)


def rov_response_payload(outcome: str, drop: Iterable[str] = (),
                         **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "outcome": outcome,
        "response_note": "Reconsideration evidence reviewed against the original grid.",
    }
    return _apply(body, overrides, drop)


def rov_next_round_payload(**overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"next_round_reason": "Borrower supplied further closed sales."}
    return _apply(body, overrides)


def rov_finalize_payload(**overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"closure_note": "Reconsideration channel closed."}
    return _apply(body, overrides)


# ---------------------------------------------------------------------------
# DisputeCase (PRD 3.9)
# ---------------------------------------------------------------------------
def dispute_payload(appraisal_id: str, amc_id: str, appraiser_id: str,
                    dispute_basis: str, slot_start: str, slot_end: str,
                    drop: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "appraisal_id": appraisal_id,
        "amc_id": amc_id,
        "appraiser_id": appraiser_id,
        "dispute_basis": dispute_basis,
        "review_slot_start": slot_start,
        "review_slot_end": slot_end,
    }
    return _apply(body, overrides, drop)


def amc_response_payload(appraiser_position: str, drop: Iterable[str] = (),
                         **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "appraiser_position": appraiser_position,
        "response_summary": "Appraiser reviewed the challenged grid and responded.",
    }
    return _apply(body, overrides, drop)


def resolve_dispute_payload(resolution: str, drop: Iterable[str] = (),
                            **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "resolution": resolution,
        "resolution_note": "Dispute resolved by the panel authority.",
    }
    return _apply(body, overrides, drop)


CLOCK_START = CLOCK_EPOCH
