"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the runner restarts the server before every test, so each test starts empty).
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    batch_payload,
    brand_owner_payload,
    complaint_case_payload,
    formula_ingredient_payload,
    formula_payload,
    ingredient_payload,
    lot_payload,
    nutrient_profile_payload,
    pairing_payload,
    recall_action_payload,
    state_registration_payload,
    supplier_payload,
    trial_protocol_payload,
)
from .test_users import TEST_USERS, make_regulatory_affairs_headers

ADMIN = TEST_USERS["platform_admin_headers"]
SCIENTIST = TEST_USERS["formulation_scientist_headers"]
QA = TEST_USERS["qa_approver_headers"]
ANALYST = TEST_USERS["quality_analyst_headers"]
TRIAL = TEST_USERS["trial_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]

DEFAULT_SCHEDULED_START = "2026-08-10T08:00:00Z"
DEFAULT_BEST_BY = "2027-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def create_brand_owner(**overrides) -> dict:
    resp = api_client.create_brand_owner(brand_owner_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_supplier(approve: bool = False, **overrides) -> dict:
    supplier = get_success_data(api_client.create_supplier(supplier_payload(**overrides), ADMIN))
    if approve:
        supplier = get_success_data(api_client.approve_supplier(supplier["id"], QA))
    return supplier


def create_ingredient(**overrides) -> dict:
    return get_success_data(api_client.create_ingredient(ingredient_payload(**overrides), SCIENTIST))


def create_pairing(
    supplier_id: str,
    ingredient_id: str,
    requester_user_id: str = "qa-requester-1",
    approve: bool = False,
    approver_user_id: str = "qa-approver-1",
    **overrides,
) -> dict:
    """Create a SupplierIngredientApproval; optionally approve it.

    The requester and approver user ids differ by default so the
    segregation-of-duties rule (PRD §3.2) is satisfied.
    """
    from prd_bench_local_runner.testing import build_user_headers

    requester = build_user_headers(requester_user_id, "QualityAnalyst")
    pairing = get_success_data(
        api_client.create_pairing(pairing_payload(supplier_id, ingredient_id, **overrides), requester)
    )
    if approve:
        approver = build_user_headers(approver_user_id, "QAApprover")
        pairing = get_success_data(api_client.approve_pairing(pairing["id"], approver))
    return pairing


def create_formula(brand_owner_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_formula(brand_owner_id, formula_payload(**overrides), SCIENTIST)
    )


def add_ingredient_line(formula_id: str, ingredient_id: str, inclusion_pct: float = 100.0,
                        **overrides) -> dict:
    return get_success_data(
        api_client.add_formula_ingredient(
            formula_id,
            formula_ingredient_payload(ingredient_id, inclusion_pct=inclusion_pct, **overrides),
            SCIENTIST,
        )
    )


def post_nutrient_profile(formula_id: str, **overrides) -> dict:
    """Post a nutrient profile; defaults satisfy DOG/ADULT AAFCO floors (PRD §3.3)."""
    return get_success_data(
        api_client.create_nutrient_profile(
            formula_id, nutrient_profile_payload(**overrides), SCIENTIST
        )
    )


def get_formula(formula_id: str) -> dict:
    return get_success_data(api_client.get_formula(formula_id, QA))


def get_brand(brand_owner_id: str) -> dict:
    return get_success_data(api_client.get_brand_owner(brand_owner_id, QA))


def get_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_batch(batch_id, QA))


def get_lot_by_id(batch_id: str, lot_id: str) -> dict:
    lots, _meta = _list_lots(batch_id)
    for lot in lots:
        if lot["id"] == lot_id:
            return lot
    raise AssertionError(f"Lot {lot_id} not found on batch {batch_id}")


def _list_lots(batch_id: str):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(api_client.list_lots(batch_id, ANALYST))


def get_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_state_registration(registration_id, REGULATOR))


def get_supplier(supplier_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_supplier(supplier_id, headers or QA))


def get_recall(recall_id: str) -> dict:
    return get_success_data(api_client.get_recall_action(recall_id, QA))


# ---------------------------------------------------------------------------
# Tier 2/3: formula lifecycle contexts
# ---------------------------------------------------------------------------

def setup_draft_formula(brand_owner_id: str = None, with_line: bool = False, **formula_over) -> dict:
    """Brand (+ optional ingredient line) + DRAFT formula."""
    ctx = {}
    ctx["brand"] = create_brand_owner() if brand_owner_id is None else get_brand(brand_owner_id)
    ctx["formula"] = create_formula(ctx["brand"]["id"], **formula_over)
    if with_line:
        ctx["ingredient"] = create_ingredient()
        ctx["line"] = add_ingredient_line(ctx["formula"]["id"], ctx["ingredient"]["id"])
        ctx["formula"] = get_formula(ctx["formula"]["id"])
    return ctx


def setup_nutrient_review_formula(**formula_over) -> dict:
    """DRAFT formula with one 100% ACTIVE ingredient line, submitted to review."""
    ctx = setup_draft_formula(with_line=True, **formula_over)
    ctx["formula"] = get_success_data(api_client.submit_nutrient_review(ctx["formula"]["id"], SCIENTIST))
    return ctx


def setup_substantiated_formula(
    species: str = "DOG",
    life_stage: str = "ADULT_MAINTENANCE",
    profile_overrides: dict = None,
    **formula_over,
) -> dict:
    """Full chain: brand, APPROVED supplier, ingredient, APPROVED pairing,
    formula + 100% line, COMPLIANT profile, submit, substantiate.

    Returns ctx with keys: brand, supplier, ingredient, pairing, formula, profile.
    """
    profile_over = dict(profile_overrides or {})
    formula_over.setdefault("species", species)
    formula_over.setdefault("life_stage", life_stage)
    ctx = {}
    ctx["brand"] = create_brand_owner()
    ctx["supplier"] = create_supplier(approve=True)
    ctx["ingredient"] = create_ingredient()
    ctx["pairing"] = create_pairing(
        ctx["supplier"]["id"], ctx["ingredient"]["id"], approve=True
    )
    ctx["formula"] = create_formula(ctx["brand"]["id"], **formula_over)
    ctx["line"] = add_ingredient_line(ctx["formula"]["id"], ctx["ingredient"]["id"])
    ctx["profile"] = post_nutrient_profile(ctx["formula"]["id"], **profile_over)
    ctx["formula"] = get_success_data(api_client.submit_nutrient_review(ctx["formula"]["id"], SCIENTIST))
    ctx["formula"] = get_success_data(api_client.substantiate_formula(ctx["formula"]["id"], QA))
    return ctx


def setup_locked_formula(**kw) -> dict:
    """setup_substantiated_formula + lock. Formula returned in LOCKED state."""
    ctx = setup_substantiated_formula(**kw)
    ctx["formula"] = get_success_data(api_client.lock_formula(ctx["formula"]["id"], QA))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: batch lifecycle
# ---------------------------------------------------------------------------

def create_production_batch(
    formula_id: str,
    planned_kg: float = 500.0,
    line_id: str = "LINE-1",
    scheduled_start: str = DEFAULT_SCHEDULED_START,
) -> dict:
    """Create a batch against a LOCKED formula, reading the current formula
    version first to satisfy the expected_formula_version check (PRD §2.7)."""
    version = get_formula(formula_id)["version"]
    return get_success_data(
        api_client.create_batch(
            formula_id,
            batch_payload(
                version,
                planned_kg=planned_kg,
                line_id=line_id,
                scheduled_start=scheduled_start,
            ),
            PLANNER,
        )
    )


def setup_batch_in_state(
    target_state: str,
    planned_kg: float = 500.0,
    actual_kg: float = None,
    line_id: str = "LINE-1",
    scheduled_start: str = DEFAULT_SCHEDULED_START,
    with_lot: bool = False,
    **formula_kw,
) -> dict:
    """Locked formula + batch walked to target_state.

    target_state in {SCHEDULED, RELEASED_FOR_PRODUCTION, IN_PROCESS, ON_HOLD,
    COMPLETED}. When with_lot and the batch is COMPLETED, also cuts one lot.
    Returns ctx with keys: brand, supplier, ingredient, pairing, formula,
    profile, batch (+ lot when with_lot).
    """
    ctx = setup_locked_formula(**formula_kw)
    ctx["batch"] = create_production_batch(
        ctx["formula"]["id"], planned_kg=planned_kg, line_id=line_id,
        scheduled_start=scheduled_start,
    )
    batch_id = ctx["batch"]["id"]
    order = ["SCHEDULED", "RELEASED_FOR_PRODUCTION", "IN_PROCESS", "ON_HOLD", "COMPLETED"]
    if target_state not in order:
        raise ValueError(f"Unsupported target_state {target_state}")
    if target_state == "SCHEDULED":
        pass
    else:
        ctx["batch"] = get_success_data(api_client.release_batch(batch_id, PLANNER))
        if target_state == "RELEASED_FOR_PRODUCTION":
            pass
        else:
            ctx["batch"] = get_success_data(api_client.start_run(batch_id, OPERATOR))
            if target_state == "IN_PROCESS":
                pass
            elif target_state == "ON_HOLD":
                ctx["batch"] = get_success_data(api_client.hold_batch(batch_id, ANALYST))
            elif target_state == "COMPLETED":
                ctx["batch"] = get_success_data(
                    api_client.complete_batch(
                        batch_id, {"actual_kg": actual_kg or planned_kg}, OPERATOR
                    )
                )
                if with_lot:
                    ctx["lot"] = get_success_data(
                        api_client.create_lot(batch_id, lot_payload(), OPERATOR)
                    )
    ctx["formula"] = get_formula(ctx["formula"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: feeding-trial lifecycle
# ---------------------------------------------------------------------------

def setup_trial_protocol(
    target_state: str = "PLANNED",
    animal_count: int = 8,
    duration_days: int = 26,
    enroll_deltas=None,
    completed_count: int = None,
) -> dict:
    """FEEDING_TRIAL-basis formula (DRAFT) + protocol walked to target_state.

    target_state in {PLANNED, ENROLLING, RUNNING, ANALYSIS, PASSED, FAILED}.
    enroll_deltas defaults to a single event filling the planned animal_count.
    """
    ctx = setup_draft_formula(adequacy_basis="FEEDING_TRIAL")
    ctx["protocol"] = get_success_data(
        api_client.create_trial_protocol(
            ctx["formula"]["id"],
            trial_protocol_payload(animal_count=animal_count, duration_days=duration_days),
            TRIAL,
        )
    )
    pid = ctx["protocol"]["id"]
    if target_state == "PLANNED":
        return ctx
    ctx["protocol"] = get_success_data(api_client.open_enrollment(pid, TRIAL))
    deltas = enroll_deltas if enroll_deltas is not None else [animal_count]
    for d in deltas:
        ctx["protocol"] = get_success_data(api_client.enroll(pid, {"enrolled_delta": d}, TRIAL))
    if target_state == "ENROLLING":
        return ctx
    ctx["protocol"] = get_success_data(api_client.start_trial(pid, TRIAL))
    if target_state == "RUNNING":
        return ctx
    ctx["protocol"] = get_success_data(
        api_client.complete_observation(
            pid, {"completed_count": completed_count if completed_count is not None else animal_count},
            TRIAL,
        )
    )
    if target_state == "ANALYSIS":
        return ctx
    ctx["protocol"] = get_success_data(api_client.record_verdict(pid, QA))
    if target_state in ("PASSED", "FAILED"):
        assert ctx["protocol"]["status"] == target_state, (
            f"Protocol routed to {ctx['protocol']['status']}, expected {target_state}"
        )
        return ctx
    raise ValueError(f"Unsupported target_state {target_state}")


# ---------------------------------------------------------------------------
# Tier 3: state registration lifecycle
# ---------------------------------------------------------------------------

def setup_registration(
    target_state: str = "SUBMITTED",
    state_code: str = "CA",
    tonnage_tier: float = 3.0,
    label_revision_ref: int = 1,
    locked: bool = False,
    **formula_kw,
) -> dict:
    """Substantiated (or locked) formula + registration walked to target_state.

    target_state in {SUBMITTED, UNDER_REVIEW, APPROVED, REJECTED}.
    The RegulatoryAffairs calls carry the owning brand's id (PRD §2.1).
    """
    ctx = setup_locked_formula(**formula_kw) if locked else setup_substantiated_formula(**formula_kw)
    ra_headers = make_regulatory_affairs_headers(ctx["brand"]["id"])
    ctx["registration"] = get_success_data(
        api_client.create_state_registration(
            ctx["formula"]["id"],
            state_registration_payload(
                state_code=state_code,
                label_revision_ref=label_revision_ref,
                tonnage_tier=tonnage_tier,
            ),
            ra_headers,
        )
    )
    rid = ctx["registration"]["id"]
    if target_state == "SUBMITTED":
        return ctx
    ctx["registration"] = get_success_data(api_client.accept_registration_for_review(rid, REGULATOR))
    if target_state == "UNDER_REVIEW":
        return ctx
    if target_state == "APPROVED":
        version = get_formula(ctx["formula"]["id"])["version"]
        ctx["registration"] = get_success_data(
            api_client.approve_registration(rid, {"expected_formula_version": version}, REGULATOR)
        )
        return ctx
    if target_state == "REJECTED":
        ctx["registration"] = get_success_data(api_client.reject_registration(rid, REGULATOR))
        return ctx
    raise ValueError(f"Unsupported target_state {target_state}")


# ---------------------------------------------------------------------------
# Complaints and recalls
# ---------------------------------------------------------------------------

def create_complaint(
    brand_owner_id: str,
    formula_id: str,
    severity: str = "MINOR",
    category: str = "PALATABILITY",
    adverse_event_flag: bool = None,
) -> dict:
    over = {"severity": severity, "category": category}
    if adverse_event_flag is not None:
        over["adverse_event_flag"] = adverse_event_flag
    return get_success_data(
        api_client.create_complaint_case(
            complaint_case_payload(brand_owner_id, formula_id, **over), ANALYST
        )
    )


def triage_complaint(case_id: str, confirm_flag: bool = False) -> dict:
    return get_success_data(
        api_client.triage_complaint(case_id, {"confirm_adverse_event_flag": confirm_flag}, ANALYST)
    )


def initiate_recall(
    formula_id: str,
    scope_batch_ids,
    recall_class: str = "CLASS_III",
    reason: str = "Test recall",
) -> dict:
    return get_success_data(
        api_client.create_recall_action(
            recall_action_payload(
                formula_id,
                scope_batch_ids=list(scope_batch_ids),
                recall_class=recall_class,
                reason=reason,
            ),
            QA,
        )
    )
