"""Composite state builders.

The harness restarts the server before every test, so each test begins against
an empty database and must build all of its state through PRD endpoints. These
builders do exactly that: they drive real requests, use ``get_success_data`` so
that a 200/201 difference never breaks a setup, and accept ``**overrides`` so a
caller can bend one field without forking the whole chain.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    DECISION_ACCEPT,
    DECISION_PROBATION,
    DECISION_QUALIFY,
    RESPONSE_ACKNOWLEDGE,
    RESPONSE_OBJECT,
    WARNING_PEDIATRIC,
)
from .test_users import CAO_HEADERS, QAM_HEADERS, RAS_HEADERS, REVIEWER_HEADERS

# A three-study evidence set whose screening score is 78.00 and whose frozen
# final score is 66.00 under the two variants of PRD §3.4.
THREE_STUDY_SET: List[Dict[str, Any]] = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Bone Metab Rev 2024;31:88-101",
    },
    {
        "study_type": "OBSERVATIONAL_HUMAN",
        "subject_count": 150,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Nutr Epidemiol 2025;9:14-27",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 60,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Clin Nutr Trials 2026;4:55-63",
    },
]

# A three-study set whose frozen final score is 78.00, comfortably above the
# 65.00 acceptance threshold of PRD §3.4.
STRONG_STUDY_SET: List[Dict[str, Any]] = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Hayashi 2021 Immunol Nutr 4:11",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 150,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Moreau 2022 Clin Nutr 19:87",
    },
    {
        "study_type": "OBSERVATIONAL_HUMAN",
        "subject_count": 100,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Ferreira 2020 Cohort Rev 2:5",
    },
]


# ----------------------------------------------------------------------
# Tier 1 — the logical clock and single rows
# ----------------------------------------------------------------------
def set_clock(api, current_utc: str, headers: Dict[str, str] = RAS_HEADERS) -> None:
    """Move the logical clock (PRD §2.5). Every role may drive the clock."""
    get_success_data(api.set_clock(current_utc, headers))


def make_ingredient(api, headers: Dict[str, str] = RAS_HEADERS, **overrides) -> Dict:
    """Register an ingredient; it opens in ``DRAFT_ASSESSMENT`` (PRD §3.1)."""
    return get_success_data(api.create_ingredient(f.ingredient_payload(**overrides), headers))


def make_grandfathered_ingredient(
    api, headers: Dict[str, str] = RAS_HEADERS, **overrides
) -> Dict:
    """Register an ingredient and settle it on ``GRANDFATHERED`` (PRD §3.1)."""
    ingredient = make_ingredient(api, headers, **overrides)
    return get_success_data(api.run_eligibility_determination(ingredient["id"], headers))


def make_ndi_required_ingredient(
    api, headers: Dict[str, str] = RAS_HEADERS, **overrides
) -> Dict:
    """Register an ingredient whose determination lands on ``NDI_REQUIRED``."""
    ingredient = get_success_data(
        api.create_ingredient(f.ndi_ingredient_payload(**overrides), headers)
    )
    return get_success_data(api.run_eligibility_determination(ingredient["id"], headers))


def make_submitted_notification(
    api, ingredient_id: str, headers: Dict[str, str] = RAS_HEADERS, **overrides
) -> Dict:
    """Draft and file a notification, minting the 75-day waiting period (PRD §3.2)."""
    notification = get_success_data(
        api.create_ndi_notification(
            f.ndi_notification_payload(ingredient_id, **overrides), headers
        )
    )
    return get_success_data(api.submit_ndi_notification(notification["id"], headers))


def make_ndi_pending_ingredient(
    api, headers: Dict[str, str] = RAS_HEADERS, **overrides
) -> Tuple[Dict, Dict]:
    """An ingredient in ``NDI_PENDING`` plus its ``SUBMITTED`` notification."""
    ingredient = make_ndi_required_ingredient(api, headers, **overrides)
    notification = make_submitted_notification(api, ingredient["id"], headers)
    ingredient = get_success_data(api.get_ingredient(ingredient["id"], headers))
    return ingredient, notification


def make_ndi_acknowledged_ingredient(
    api,
    headers: Dict[str, str] = RAS_HEADERS,
    acknowledge_at: str = "2026-10-15T00:00:00Z",
    **overrides,
) -> Tuple[Dict, Dict]:
    """Carry an ingredient all the way to ``NDI_ACKNOWLEDGED`` (PRD §3.2)."""
    ingredient, notification = make_ndi_pending_ingredient(api, headers, **overrides)
    set_clock(api, acknowledge_at, headers)
    notification = get_success_data(
        api.record_agency_response(
            notification["id"], f.agency_response_payload(RESPONSE_ACKNOWLEDGE), headers
        )
    )
    ingredient = get_success_data(api.get_ingredient(ingredient["id"], headers))
    return ingredient, notification


def make_objected_notification(
    api, notification_id: str, headers: Dict[str, str] = RAS_HEADERS
) -> Dict:
    """Record an agency objection, cascading the ingredient to ``NDI_OBJECTED``."""
    return get_success_data(
        api.record_agency_response(
            notification_id,
            f.agency_response_payload(
                RESPONSE_OBJECT,
                agency_objection_reason=(
                    "Safety narrative does not support the proposed daily intake"
                ),
            ),
            headers,
        )
    )


def make_product(api, headers: Dict[str, str] = RAS_HEADERS, **overrides) -> Dict:
    """Create a product; it opens ``DRAFT``/``OPEN`` with an index of 10 (PRD §3.3)."""
    return get_success_data(api.create_product(f.product_payload(**overrides), headers))


def make_line(
    api,
    product_id: str,
    ingredient_id: str,
    headers: Dict[str, str] = RAS_HEADERS,
    **overrides,
) -> Dict:
    """Add one supplement-facts line to a draft product (PRD §3.3)."""
    return get_success_data(
        api.create_product_ingredient(
            f.product_ingredient_payload(product_id, ingredient_id, **overrides), headers
        )
    )


def product_version(api, product_id: str, headers: Dict[str, str] = RAS_HEADERS) -> int:
    """Re-read the product's ``version`` for the panel-creation guard (PRD §2.6)."""
    return get_success_data(api.get_product(product_id, headers))["version"]


def claim_version(api, claim_id: str, headers: Dict[str, str] = RAS_HEADERS) -> int:
    """Re-read the claim's ``version`` for the dossier-creation guard (PRD §2.6)."""
    return get_success_data(api.get_claim(claim_id, headers))["version"]


# ----------------------------------------------------------------------
# Tier 2 — the product / line / panel hierarchy
# ----------------------------------------------------------------------
def make_product_with_line(
    api,
    headers: Dict[str, str] = RAS_HEADERS,
    ingredient_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    **product_overrides,
) -> Tuple[Dict, Dict, Dict]:
    """A DRAFT product with one ACTIVE line on a GRANDFATHERED ingredient."""
    ingredient = make_grandfathered_ingredient(api, headers, **(ingredient_overrides or {}))
    product = make_product(api, headers, **product_overrides)
    line = make_line(
        api, product["id"], ingredient["id"], headers, **(line_overrides or {})
    )
    return product, ingredient, line


def make_draft_panel(
    api,
    product_id: str,
    headers: Dict[str, str] = RAS_HEADERS,
    expected_version: Optional[int] = None,
    **overrides,
) -> Dict:
    """Draft a panel, re-reading the product version unless one is supplied."""
    version = (
        expected_version
        if expected_version is not None
        else product_version(api, product_id, headers)
    )
    return get_success_data(
        api.create_label_panel(f.label_panel_payload(product_id, version, **overrides), headers)
    )


def make_validated_panel(
    api, product_id: str, headers: Dict[str, str] = RAS_HEADERS, **overrides
) -> Dict:
    """Draft then validate a panel, persisting the four computed figures."""
    panel = make_draft_panel(api, product_id, headers, **overrides)
    return get_success_data(api.validate_label_panel(panel["id"], headers))


def make_locked_panel(
    api,
    product_id: str,
    headers: Dict[str, str] = RAS_HEADERS,
    lock_headers: Dict[str, str] = CAO_HEADERS,
    **overrides,
) -> Dict:
    """Validate then lock a panel, cascading the product to LABEL_LOCKED."""
    panel = make_validated_panel(api, product_id, headers, **overrides)
    return get_success_data(api.lock_label_panel(panel["id"], lock_headers))


def make_label_locked_product(
    api,
    headers: Dict[str, str] = RAS_HEADERS,
    lock_headers: Dict[str, str] = CAO_HEADERS,
    ingredient_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    panel_overrides: Optional[Dict[str, Any]] = None,
    **product_overrides,
) -> Tuple[Dict, Dict, Dict, Dict]:
    """Product + line + locked panel, so the product sits in LABEL_LOCKED."""
    product, ingredient, line = make_product_with_line(
        api,
        headers,
        ingredient_overrides=ingredient_overrides,
        line_overrides=line_overrides,
        **product_overrides,
    )
    panel = make_locked_panel(
        api, product["id"], headers, lock_headers, **(panel_overrides or {})
    )
    return product, ingredient, line, panel


# ----------------------------------------------------------------------
# Tier 3 — claim, dossier and evidence chains
# ----------------------------------------------------------------------
def make_claim(
    api,
    product_id: str,
    ingredient_id: str,
    headers: Dict[str, str] = RAS_HEADERS,
    **overrides,
) -> Dict:
    """Draft a claim; it opens DRAFT / NOT_DUE with revision_round 0 (PRD §3.4)."""
    return get_success_data(
        api.create_claim(f.claim_payload(product_id, ingredient_id, **overrides), headers)
    )


def make_dossier(
    api, claim_id: str, headers: Dict[str, str] = RAS_HEADERS, **overrides
) -> Dict:
    """Open a dossier, re-reading the claim version for the §2.6 guard."""
    version = overrides.pop("expected_claim_version", None)
    if version is None:
        version = claim_version(api, claim_id, headers)
    return get_success_data(
        api.create_dossier(f.dossier_payload(claim_id, version, **overrides), headers)
    )


def append_studies(
    api,
    dossier_id: str,
    studies: List[Dict[str, Any]],
    headers: Dict[str, str] = RAS_HEADERS,
) -> Dict:
    """Append each study in order; the last response carries the running score."""
    data: Dict[str, Any] = {}
    for study in studies:
        data = get_success_data(
            api.append_evidence(dossier_id, f.evidence_payload(**study), headers)
        )
    return data


def make_dossier_with_studies(
    api,
    claim_id: str,
    studies: Optional[List[Dict[str, Any]]] = None,
    headers: Dict[str, str] = RAS_HEADERS,
    **overrides,
) -> Dict:
    """A DRAFT dossier already carrying its evidence set."""
    dossier = make_dossier(api, claim_id, headers, **overrides)
    append_studies(api, dossier["id"], studies or STRONG_STUDY_SET, headers)
    return get_success_data(api.get_dossier(dossier["id"], headers))


def make_claim_under_review(
    api,
    product_id: str,
    ingredient_id: str,
    studies: Optional[List[Dict[str, Any]]] = None,
    headers: Dict[str, str] = RAS_HEADERS,
    claim_overrides: Optional[Dict[str, Any]] = None,
    **dossier_overrides,
) -> Tuple[Dict, Dict]:
    """Claim in UNDER_SUBSTANTIATION_REVIEW with its dossier UNDER_REVIEW."""
    claim = make_claim(
        api, product_id, ingredient_id, headers, **(claim_overrides or {})
    )
    dossier = make_dossier_with_studies(
        api, claim["id"], studies, headers, **dossier_overrides
    )
    claim = get_success_data(api.submit_claim_for_review(claim["id"], headers))
    dossier = get_success_data(api.get_dossier(dossier["id"], headers))
    return claim, dossier


def make_claim_with_accepted_dossier(
    api,
    product_id: str,
    ingredient_id: str,
    studies: Optional[List[Dict[str, Any]]] = None,
    headers: Dict[str, str] = RAS_HEADERS,
    reviewer_headers: Dict[str, str] = REVIEWER_HEADERS,
    claim_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict, Dict]:
    """Claim under review whose dossier has been ACCEPTED by an independent reviewer."""
    claim, dossier = make_claim_under_review(
        api,
        product_id,
        ingredient_id,
        studies,
        headers,
        claim_overrides=claim_overrides,
    )
    dossier = get_success_data(
        api.review_dossier(dossier["id"], f.review_payload(DECISION_ACCEPT), reviewer_headers)
    )
    return claim, dossier


def make_approved_claim(
    api,
    product_id: str,
    ingredient_id: str,
    studies: Optional[List[Dict[str, Any]]] = None,
    headers: Dict[str, str] = RAS_HEADERS,
    reviewer_headers: Dict[str, str] = REVIEWER_HEADERS,
    approver_headers: Dict[str, str] = CAO_HEADERS,
    claim_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict, Dict]:
    """An APPROVED claim and its ACCEPTED dossier (PRD §3.4)."""
    claim, dossier = make_claim_with_accepted_dossier(
        api,
        product_id,
        ingredient_id,
        studies,
        headers,
        reviewer_headers,
        claim_overrides=claim_overrides,
    )
    claim = get_success_data(api.approve_claim(claim["id"], approver_headers))
    return claim, dossier


# ----------------------------------------------------------------------
# Tier 4 — the supply chain: supplier, lot, certificate of analysis
# ----------------------------------------------------------------------
def make_supplier(api, headers: Dict[str, str] = QAM_HEADERS, **overrides) -> Dict:
    """Register a supplier; it opens in ``UNQUALIFIED`` (PRD §3.7)."""
    return get_success_data(api.create_supplier(f.supplier_payload(**overrides), headers))


def make_qualified_supplier(
    api, headers: Dict[str, str] = QAM_HEADERS, **overrides
) -> Dict:
    """A supplier carried to ``QUALIFIED`` by a QUALIFY decision (PRD §3.7)."""
    supplier = make_supplier(api, headers, **overrides)
    return get_success_data(
        api.qualification_decision(
            supplier["id"], f.qualification_decision_payload(DECISION_QUALIFY), headers
        )
    )


def make_probation_supplier(
    api, headers: Dict[str, str] = QAM_HEADERS, **overrides
) -> Dict:
    """A supplier placed on ``PROBATION`` (PRD §3.7)."""
    supplier = make_qualified_supplier(api, headers, **overrides)
    return get_success_data(
        api.qualification_decision(
            supplier["id"],
            f.qualification_decision_payload(
                DECISION_PROBATION,
                decision_note="Two open deviations from the last on-site audit.",
            ),
            headers,
        )
    )


def make_lot(
    api,
    supplier_id: str,
    ingredient_id: str,
    headers: Dict[str, str] = QAM_HEADERS,
    **overrides,
) -> Dict:
    """Receive a lot; it opens ``QUARANTINED`` with its whole mass held (PRD §3.7)."""
    return get_success_data(
        api.create_ingredient_lot(
            f.ingredient_lot_payload(supplier_id, ingredient_id, **overrides), headers
        )
    )


def make_coa(
    api, lot_id: str, headers: Dict[str, str] = QAM_HEADERS, **overrides
) -> Dict:
    """File a certificate of analysis against a lot; it opens ``RECEIVED``."""
    return get_success_data(api.create_coa(f.coa_payload(lot_id, **overrides), headers))


def make_accepted_coa(
    api, lot_id: str, headers: Dict[str, str] = QAM_HEADERS, **overrides
) -> Dict:
    """A certificate reviewed to ``ACCEPTED`` (PRD §3.7)."""
    coa = make_coa(api, lot_id, headers, **overrides)
    return get_success_data(
        api.review_coa(coa["id"], f.review_payload(DECISION_ACCEPT), headers)
    )


def make_released_lot(
    api,
    supplier_id: str,
    ingredient_id: str,
    headers: Dict[str, str] = QAM_HEADERS,
    coa_overrides: Optional[Dict[str, Any]] = None,
    **lot_overrides,
) -> Tuple[Dict, Dict]:
    """A ``RELEASED`` lot with its accepted certificate (PRD §3.7)."""
    lot = make_lot(api, supplier_id, ingredient_id, headers, **lot_overrides)
    coa = make_accepted_coa(api, lot["id"], headers, **(coa_overrides or {}))
    lot = get_success_data(api.release_lot(lot["id"], headers))
    return lot, coa


def make_supply_chain(
    api,
    headers: Dict[str, str] = QAM_HEADERS,
    ingredient_headers: Dict[str, str] = RAS_HEADERS,
    ingredient_id: Optional[str] = None,
    supplier_overrides: Optional[Dict[str, Any]] = None,
    coa_overrides: Optional[Dict[str, Any]] = None,
    **lot_overrides,
) -> Tuple[Dict, Dict, Dict]:
    """Qualified supplier + released lot, the standard supply-side starting point."""
    if ingredient_id is None:
        ingredient_id = make_grandfathered_ingredient(api, ingredient_headers)["id"]
    supplier = make_qualified_supplier(api, headers, **(supplier_overrides or {}))
    lot, coa = make_released_lot(
        api,
        supplier["id"],
        ingredient_id,
        headers,
        coa_overrides=coa_overrides,
        **lot_overrides,
    )
    return supplier, lot, coa


# ----------------------------------------------------------------------
# Tier 5 — adverse events and risk accumulation
# ----------------------------------------------------------------------
def make_aer(
    api, product_id: str, headers: Dict[str, str] = QAM_HEADERS, **overrides
) -> Dict:
    """Intake a report; it opens ``RECEIVED`` with seriousness undecided (PRD §3.8)."""
    return get_success_data(
        api.create_adverse_event_report(
            f.adverse_event_payload(product_id, **overrides), headers
        )
    )


def make_triaged_serious_aer(
    api,
    product_id: str,
    headers: Dict[str, str] = QAM_HEADERS,
    serious_override: Optional[bool] = None,
    **overrides,
) -> Dict:
    """A report driven onto the serious branch, minting its filing deadline."""
    report = make_aer(api, product_id, headers, **overrides)
    return get_success_data(
        api.triage_adverse_event_report(
            report["id"], headers, f.triage_payload(serious_override)
        )
    )


def make_triaged_nonserious_aer(
    api, product_id: str, headers: Dict[str, str] = QAM_HEADERS, **overrides
) -> Dict:
    """A report triaged onto the non-serious branch, which mints no deadline."""
    payload = {"outcome_codes": ["OTHER"]}
    payload.update(overrides)
    report = make_aer(api, product_id, headers, **payload)
    return get_success_data(
        api.triage_adverse_event_report(report["id"], headers, f.triage_payload())
    )


def accumulate_serious_aers(
    api, product_id: str, count: int, headers: Dict[str, str] = QAM_HEADERS
) -> List[Dict]:
    """Drive ``count`` serious reports onto a product to raise its risk index."""
    return [make_triaged_serious_aer(api, product_id, headers) for _ in range(count)]


def accumulate_nonserious_aers(
    api, product_id: str, count: int, headers: Dict[str, str] = QAM_HEADERS
) -> List[Dict]:
    """Drive ``count`` non-serious reports onto a product."""
    return [make_triaged_nonserious_aer(api, product_id, headers) for _ in range(count)]


# ----------------------------------------------------------------------
# Tier 6 — going to market and the notification window
# ----------------------------------------------------------------------
def make_marketed_product(
    api,
    headers: Dict[str, str] = RAS_HEADERS,
    officer_headers: Dict[str, str] = CAO_HEADERS,
    marketing_start_date: str = "2026-09-10",
    ingredient_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    panel_overrides: Optional[Dict[str, Any]] = None,
    **product_overrides,
) -> Tuple[Dict, Dict, Dict, Dict]:
    """Carry a product to ``MARKETED``.

    PRD §3.6 stores the UTC calendar date of the logical clock at the instant the
    transition fires, so the clock is moved to ``marketing_start_date`` first.
    """
    product, ingredient, line, panel = make_label_locked_product(
        api,
        headers,
        officer_headers,
        ingredient_overrides=ingredient_overrides,
        line_overrides=line_overrides,
        panel_overrides=panel_overrides,
        **product_overrides,
    )
    set_clock(api, f"{marketing_start_date}T00:00:00Z", headers)
    product = get_success_data(
        api.start_marketing(
            product["id"], f.start_marketing_payload(marketing_start_date), officer_headers
        )
    )
    return product, ingredient, line, panel


def make_marketed_product_with_due_claim(
    api,
    headers: Dict[str, str] = RAS_HEADERS,
    reviewer_headers: Dict[str, str] = REVIEWER_HEADERS,
    officer_headers: Dict[str, str] = CAO_HEADERS,
    marketing_start_date: str = "2026-09-10",
    studies: Optional[List[Dict[str, Any]]] = None,
    **product_overrides,
) -> Tuple[Dict, Dict, Dict]:
    """A marketed product whose approved claim was swept into ``DUE``.

    The claim is approved while the product is still ``LABEL_LOCKED``, so the
    launch anchors its window on ``PRODUCT_LAUNCH_BASIS`` (PRD §3.6).
    """
    product, ingredient, line, panel = make_label_locked_product(
        api, headers, officer_headers, **product_overrides
    )
    claim, _dossier = make_approved_claim(
        api,
        product["id"],
        ingredient["id"],
        studies,
        headers,
        reviewer_headers,
        officer_headers,
    )
    set_clock(api, f"{marketing_start_date}T00:00:00Z", headers)
    product = get_success_data(
        api.start_marketing(
            product["id"], f.start_marketing_payload(marketing_start_date), officer_headers
        )
    )
    claim = get_success_data(api.get_claim(claim["id"], headers))
    return product, claim, ingredient
