"""Composite setup helpers for the gluten-free certification API.

Every test starts against an empty store, so all state is built from scratch
through the endpoints the PRD declares. The logical clock starts at
2026-08-01T00:00:00Z and only moves when it is set explicitly; clock-driven
change is materialised only by a surveillance run, so the fixtures always set
the clock and then sweep when they need time to have passed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import ApiClient
from .constants import CLOCK_START
from .factories import (
    applicant_payload,
    audit_payload,
    facility_payload,
    ingredient_payload,
    product_payload,
    sanitation_payload,
    supplier_document_payload,
    supplier_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_contact_headers,
    make_auditor_headers,
    make_decision_maker_headers,
    make_lab_technician_headers,
    make_reviewer_headers,
)
from .types import (
    AuditType,
    Decision,
    DocType,
    MarkTier,
    RiskClass,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# instant arithmetic (whole 24-hour periods, as the PRD requires)
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def format_instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def at(day: str, time_of_day: str = "00:00:00") -> str:
    """Build an instant from a ``YYYY-MM-DD`` day and an optional time."""
    return f"{day}T{time_of_day}Z"


def plus_days(instant: str, days: int) -> str:
    return format_instant(parse_instant(instant) + timedelta(days=days))


def plus_seconds(instant: str, seconds: int) -> str:
    return format_instant(parse_instant(instant) + timedelta(seconds=seconds))


# ---------------------------------------------------------------------------
# clock and sweep
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock. Advancing the clock alone changes nothing else."""
    return get_success_data(api.set_clock(instant, ADMIN))


def read_clock_after_set(api: ApiClient, instant: str) -> str:
    return set_clock(api, instant)["current_utc"]


def run_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run one surveillance sweep, which is what materialises clock-driven change."""
    return get_success_data(api.run_surveillance(ADMIN))


def advance_and_sweep(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Set the clock and then sweep, in that order."""
    set_clock(api, instant)
    return run_sweep(api)


# ---------------------------------------------------------------------------
# single-entity builders
# ---------------------------------------------------------------------------
def create_applicant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = applicant_payload(**overrides)
    return get_success_data(api.create_applicant(ADMIN, **payload))


def create_facility(api: ApiClient, applicant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = facility_payload(applicant_id, **overrides)
    headers = make_applicant_contact_headers(applicant_id)
    return get_success_data(api.create_facility(headers, **payload))


def validate_sanitation(
    api: ApiClient,
    facility_id: str,
    *,
    auditor_user_id: str = "aud-1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = sanitation_payload(**overrides)
    return get_success_data(
        api.validate_sanitation(facility_id, make_auditor_headers(auditor_user_id), **payload)
    )


def create_supplier(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = supplier_payload(**overrides)
    return get_success_data(api.create_supplier(ADMIN, **payload))


def suspend_supplier(api: ApiClient, supplier_id: str, status: str = "SUSPENDED") -> Dict[str, Any]:
    return get_success_data(api.set_supplier_status(supplier_id, status, ADMIN))


def create_ingredient(
    api: ApiClient, applicant_id: str, supplier_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = ingredient_payload(applicant_id, supplier_id, **overrides)
    headers = make_applicant_contact_headers(applicant_id)
    return get_success_data(api.create_ingredient(headers, **payload))


def add_supplier_document(
    api: ApiClient,
    applicant_id: str,
    supplier_id: str,
    ingredient_id: str,
    *,
    verify: bool = True,
    reviewer_user_id: str = "rev-1",
    **overrides: Any,
) -> Dict[str, Any]:
    """Attach one supplier document to an ingredient, optionally verifying it."""
    payload = supplier_document_payload(supplier_id, ingredient_id, **overrides)
    headers = make_applicant_contact_headers(applicant_id)
    document = get_success_data(api.create_supplier_document(headers, **payload))
    if verify:
        document = get_success_data(
            api.verify_supplier_document(
                document["id"],
                make_reviewer_headers(reviewer_user_id),
                decision=Decision.APPROVE,
            )
        )
    return document


REQUIRED_DOC_ORDER = (DocType.ALLERGEN_STATEMENT, DocType.PROCESS_FLOW, DocType.COA)


def attach_required_documents(
    api: ApiClient,
    applicant_id: str,
    supplier_id: str,
    ingredient_id: str,
    risk_class: str,
    *,
    issued_on: str = "2026-07-01T00:00:00Z",
    expires_on: str = "2029-07-01T00:00:00Z",
    lab_ppm_claim: Optional[float] = None,
    verify: bool = True,
    reviewer_user_id: str = "rev-1",
) -> List[Dict[str, Any]]:
    """Attach exactly the document set the ingredient's risk class requires."""
    from .constants import MAX_COA_PPM_CLAIM, REQUIRED_DOC_TYPES

    required = REQUIRED_DOC_TYPES[risk_class]
    documents: List[Dict[str, Any]] = []
    for doc_type in REQUIRED_DOC_ORDER:
        if doc_type not in required:
            continue
        extra: Dict[str, Any] = {}
        if doc_type == DocType.COA:
            extra["lab_ppm_claim"] = (
                lab_ppm_claim if lab_ppm_claim is not None else MAX_COA_PPM_CLAIM[risk_class]
            )
        documents.append(
            add_supplier_document(
                api,
                applicant_id,
                supplier_id,
                ingredient_id,
                doc_type=doc_type,
                issued_on=issued_on,
                expires_on=expires_on,
                verify=verify,
                reviewer_user_id=reviewer_user_id,
                **extra,
            )
        )
    return documents


def submit_ingredient(api: ApiClient, applicant_id: str, ingredient_id: str) -> Dict[str, Any]:
    headers = make_applicant_contact_headers(applicant_id)
    return get_success_data(api.submit_ingredient(ingredient_id, headers))


def review_ingredient(
    api: ApiClient,
    ingredient_id: str,
    *,
    decision: str = Decision.APPROVE,
    reviewer_user_id: str = "rev-1",
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_ingredient(
            ingredient_id,
            make_reviewer_headers(reviewer_user_id),
            decision=decision,
            rejection_reason=rejection_reason,
        )
    )


def create_approved_ingredient(
    api: ApiClient,
    applicant_id: str,
    supplier_id: str,
    *,
    name: str = "Brown Rice Flour",
    risk_class: str = RiskClass.INHERENTLY_GF,
    issued_on: str = "2026-07-01T00:00:00Z",
    expires_on: str = "2029-07-01T00:00:00Z",
    lab_ppm_claim: Optional[float] = None,
    reviewer_user_id: str = "rev-1",
    parent_ingredient_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk an ingredient from declaration through document verification to APPROVED."""
    ingredient = create_ingredient(
        api,
        applicant_id,
        supplier_id,
        name=name,
        risk_class=risk_class,
        parent_ingredient_id=parent_ingredient_id,
    )
    attach_required_documents(
        api,
        applicant_id,
        supplier_id,
        ingredient["id"],
        risk_class,
        issued_on=issued_on,
        expires_on=expires_on,
        lab_ppm_claim=lab_ppm_claim,
        reviewer_user_id=reviewer_user_id,
    )
    submit_ingredient(api, applicant_id, ingredient["id"])
    return review_ingredient(
        api, ingredient["id"], decision=Decision.APPROVE, reviewer_user_id=reviewer_user_id
    )


def create_product(
    api: ApiClient, applicant_id: str, facility_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = product_payload(applicant_id, facility_id, **overrides)
    headers = make_applicant_contact_headers(applicant_id)
    return get_success_data(api.create_product(headers, **payload))


def link_ingredient(
    api: ApiClient,
    applicant_id: str,
    product_id: str,
    ingredient_id: str,
    inclusion_pct: float,
) -> Dict[str, Any]:
    headers = make_applicant_contact_headers(applicant_id)
    return get_success_data(
        api.link_product_ingredient(
            headers,
            product_id=product_id,
            ingredient_id=ingredient_id,
            inclusion_pct=inclusion_pct,
        ),
    )


def review_formula(
    api: ApiClient,
    product_id: str,
    *,
    decision: str = Decision.CLEAR,
    reviewer_user_id: str = "rev-1",
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_formula(
            product_id,
            make_reviewer_headers(reviewer_user_id),
            decision=decision,
            rejection_reason=rejection_reason,
        )
    )


def activate_testing_plan(
    api: ApiClient,
    product_id: str,
    expected_product_version: int,
    *,
    reviewer_user_id: str = "rev-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.activate_testing_plan(
            product_id,
            make_reviewer_headers(reviewer_user_id),
            expected_product_version=expected_product_version,
        )
    )


def review_label(
    api: ApiClient,
    product_id: str,
    *,
    decision: str = Decision.APPROVE,
    mark_tier_granted: Optional[str] = MarkTier.STANDARD,
    reviewer_user_id: str = "rev-1",
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_label(
            product_id,
            make_reviewer_headers(reviewer_user_id),
            decision=decision,
            mark_tier_granted=mark_tier_granted,
            rejection_reason=rejection_reason,
        )
    )


def record_lot_test(
    api: ApiClient, product_id: str, *, lab_user_id: str = "lab-1", **overrides: Any
) -> Dict[str, Any]:
    from .factories import lot_test_payload

    payload = lot_test_payload(product_id, **overrides)
    return get_success_data(
        api.create_lot_test(make_lab_technician_headers(lab_user_id), **payload)
    )


def schedule_audit(
    api: ApiClient, facility_id: str, *, auditor_user_id: str = "aud-1", **overrides: Any
) -> Dict[str, Any]:
    payload = audit_payload(facility_id, **overrides)
    return get_success_data(
        api.create_audit(make_auditor_headers(auditor_user_id), **payload)
    )


def start_audit(api: ApiClient, audit_id: str, *, auditor_user_id: str = "aud-1") -> Dict[str, Any]:
    return get_success_data(api.start_audit(audit_id, make_auditor_headers(auditor_user_id)))


def close_audit(
    api: ApiClient,
    audit_id: str,
    *,
    auditor_user_id: str = "aud-1",
    shared_equipment_verified: bool = True,
    air_handling_verified: bool = True,
    sanitation_validation_reviewed: bool = True,
) -> Dict[str, Any]:
    return get_success_data(
        api.close_audit(
            audit_id,
            make_auditor_headers(auditor_user_id),
            shared_equipment_verified=shared_equipment_verified,
            air_handling_verified=air_handling_verified,
            sanitation_validation_reviewed=sanitation_validation_reviewed,
        )
    )


def raise_nonconformance(
    api: ApiClient, applicant_id: str, *, raiser_user_id: str = "aud-1", role: str = "auditor", **overrides: Any
) -> Dict[str, Any]:
    from .factories import nonconformance_payload

    payload = nonconformance_payload(applicant_id, **overrides)
    headers = (
        make_auditor_headers(raiser_user_id)
        if role == "auditor"
        else make_reviewer_headers(raiser_user_id)
    )
    return get_success_data(api.create_nonconformance(headers, **payload))


def issue_certificate(
    api: ApiClient,
    product_id: str,
    expected_product_version: int,
    *,
    decision_maker_user_id: str = "dm-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.issue_certificate(
            make_decision_maker_headers(decision_maker_user_id),
            product_id=product_id,
            expected_product_version=expected_product_version,
        ),
    )


# ---------------------------------------------------------------------------
# composite setup: the certification chain
# ---------------------------------------------------------------------------
@dataclass
class IngredientSpec:
    """One formula line: the ingredient to build and the share it occupies."""

    name: str = "Brown Rice Flour"
    risk_class: str = RiskClass.INHERENTLY_GF
    inclusion_pct: float = 40
    lab_ppm_claim: Optional[float] = None
    doc_issued_on: str = "2026-07-01T00:00:00Z"
    doc_expires_on: str = "2029-07-01T00:00:00Z"


DEFAULT_INGREDIENTS = (IngredientSpec(),)


@dataclass
class CertificationContext:
    """Everything a certification-chain fixture built, in one bag."""

    applicant: Dict[str, Any]
    facility: Dict[str, Any]
    supplier: Dict[str, Any]
    ingredients: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    product: Optional[Dict[str, Any]] = None
    links: List[Dict[str, Any]] = field(default_factory=list)
    audit: Optional[Dict[str, Any]] = None
    certificate: Optional[Dict[str, Any]] = None
    product_version: Optional[int] = None
    formula_review: Optional[Dict[str, Any]] = None
    testing_plan: Optional[Dict[str, Any]] = None
    label_review: Optional[Dict[str, Any]] = None

    @property
    def applicant_id(self) -> str:
        return self.applicant["id"]

    @property
    def facility_id(self) -> str:
        return self.facility["id"]

    @property
    def supplier_id(self) -> str:
        return self.supplier["id"]

    @property
    def ingredient(self) -> Dict[str, Any]:
        return self.ingredients[0]

    @property
    def ingredient_id(self) -> str:
        return self.ingredients[0]["id"]

    @property
    def product_id(self) -> str:
        assert self.product is not None
        return self.product["id"]

    @property
    def audit_id(self) -> str:
        assert self.audit is not None
        return self.audit["id"]

    @property
    def certificate_id(self) -> str:
        assert self.certificate is not None
        return self.certificate["id"]

    @property
    def app_headers(self) -> Dict[str, str]:
        return make_applicant_contact_headers(self.applicant_id)


def setup_applicant_with_facility(
    api: ApiClient,
    *,
    clock: str = CLOCK_START,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
    sanitation_validated_on: Optional[str] = None,
    swab_ppm: float = 4.0,
    auditor_user_id: str = "aud-1",
) -> CertificationContext:
    """An applicant with one facility, optionally with its sanitation dimension
    already validated. Sanitation validity runs 365 days from validated_on."""
    set_clock(api, clock)
    applicant = create_applicant(api, **(applicant_overrides or {}))
    facility = create_facility(api, applicant["id"], **(facility_overrides or {}))
    if sanitation_validated_on is not None:
        facility = validate_sanitation(
            api,
            facility["id"],
            swab_ppm=swab_ppm,
            validated_on=sanitation_validated_on,
            auditor_user_id=auditor_user_id,
        )
    return CertificationContext(
        applicant=applicant, facility=facility, supplier={"id": None}
    )


def setup_approved_formula_lines(
    api: ApiClient,
    context: CertificationContext,
    *,
    supplier_overrides: Optional[Dict[str, Any]] = None,
    ingredients: Sequence[IngredientSpec] = DEFAULT_INGREDIENTS,
    reviewer_user_id: str = "rev-1",
) -> CertificationContext:
    """Create one supplier and walk every declared ingredient to APPROVED."""
    supplier = create_supplier(api, **(supplier_overrides or {}))
    context.supplier = supplier
    for spec in ingredients:
        context.ingredients.append(
            create_approved_ingredient(
                api,
                context.applicant_id,
                supplier["id"],
                name=spec.name,
                risk_class=spec.risk_class,
                issued_on=spec.doc_issued_on,
                expires_on=spec.doc_expires_on,
                lab_ppm_claim=spec.lab_ppm_claim,
                reviewer_user_id=reviewer_user_id,
            )
        )
    return context


def setup_passed_audit(
    api: ApiClient,
    facility_id: str,
    *,
    audit_type: str = AuditType.INITIAL,
    onsite_start_at: str = "2026-08-10T08:00:00Z",
    onsite_end_at: str = "2026-08-10T16:00:00Z",
    start_clock: str = "2026-08-10T09:00:00Z",
    close_clock: str = "2026-08-10T17:00:00Z",
    auditor_user_id: str = "aud-1",
    shared_equipment_verified: bool = True,
    air_handling_verified: bool = True,
    sanitation_validation_reviewed: bool = True,
) -> Dict[str, Any]:
    """Schedule, start and close one on-site audit with no findings raised, so the
    facility's last closed audit outcome becomes a pass."""
    audit = schedule_audit(
        api,
        facility_id,
        auditor_user_id=auditor_user_id,
        audit_type=audit_type,
        onsite_start_at=onsite_start_at,
        onsite_end_at=onsite_end_at,
    )
    set_clock(api, start_clock)
    start_audit(api, audit["id"], auditor_user_id=auditor_user_id)
    set_clock(api, close_clock)
    return close_audit(
        api,
        audit["id"],
        auditor_user_id=auditor_user_id,
        shared_equipment_verified=shared_equipment_verified,
        air_handling_verified=air_handling_verified,
        sanitation_validation_reviewed=sanitation_validation_reviewed,
    )


def setup_certification_ready_product(
    api: ApiClient,
    *,
    clock: str = CLOCK_START,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
    supplier_overrides: Optional[Dict[str, Any]] = None,
    ingredients: Sequence[IngredientSpec] = DEFAULT_INGREDIENTS,
    product_overrides: Optional[Dict[str, Any]] = None,
    sanitation_validated_on: Optional[str] = None,
    swab_ppm: float = 4.0,
    clear_formula: bool = True,
    activate_plan: bool = True,
    review_label_decision: Optional[str] = Decision.APPROVE,
    mark_tier_granted: Optional[str] = MarkTier.STANDARD,
    run_audit: bool = True,
    audit_type: str = AuditType.INITIAL,
    onsite_start_at: str = "2026-08-10T08:00:00Z",
    onsite_end_at: str = "2026-08-10T16:00:00Z",
    audit_start_clock: str = "2026-08-10T09:00:00Z",
    audit_close_clock: str = "2026-08-10T17:00:00Z",
    close_attestations: Optional[Dict[str, bool]] = None,
    reviewer_user_id: str = "rev-1",
    auditor_user_id: str = "aud-1",
) -> CertificationContext:
    """Build the full pre-issuance chain: applicant, facility with a validated
    sanitation dimension, supplier, approved ingredients, product with cleared
    formula, active testing plan, approved label and a closed on-site audit.

    ``sanitation_validated_on`` defaults to the starting clock instant.
    """
    context = setup_applicant_with_facility(
        api,
        clock=clock,
        applicant_overrides=applicant_overrides,
        facility_overrides=facility_overrides,
        sanitation_validated_on=(
            clock if sanitation_validated_on is None else sanitation_validated_on
        ),
        swab_ppm=swab_ppm,
        auditor_user_id=auditor_user_id,
    )
    setup_approved_formula_lines(
        api,
        context,
        supplier_overrides=supplier_overrides,
        ingredients=ingredients,
        reviewer_user_id=reviewer_user_id,
    )
    context.product = create_product(
        api, context.applicant_id, context.facility_id, **(product_overrides or {})
    )
    for spec, ingredient in zip(ingredients, context.ingredients):
        context.links.append(
            link_ingredient(
                api,
                context.applicant_id,
                context.product_id,
                ingredient["id"],
                spec.inclusion_pct,
            )
        )
    if clear_formula:
        context.formula_review = review_formula(
            api,
            context.product_id,
            decision=Decision.CLEAR,
            reviewer_user_id=reviewer_user_id,
        )
        context.product_version = context.formula_review["version"]
        if activate_plan:
            context.testing_plan = activate_testing_plan(
                api,
                context.product_id,
                context.product_version,
                reviewer_user_id=reviewer_user_id,
            )
            context.product_version = context.testing_plan["version"]
        if review_label_decision is not None:
            context.label_review = review_label(
                api,
                context.product_id,
                decision=review_label_decision,
                mark_tier_granted=mark_tier_granted,
                reviewer_user_id=reviewer_user_id,
            )
            context.product_version = context.label_review["version"]
    if run_audit:
        attestations = close_attestations or {}
        context.audit = setup_passed_audit(
            api,
            context.facility_id,
            audit_type=audit_type,
            onsite_start_at=onsite_start_at,
            onsite_end_at=onsite_end_at,
            start_clock=audit_start_clock,
            close_clock=audit_close_clock,
            auditor_user_id=auditor_user_id,
            shared_equipment_verified=attestations.get("shared_equipment_verified", True),
            air_handling_verified=attestations.get("air_handling_verified", True),
            sanitation_validation_reviewed=attestations.get(
                "sanitation_validation_reviewed", True
            ),
        )
    return context


def setup_issued_certificate(
    api: ApiClient,
    *,
    issue_clock: str = "2026-08-11T00:00:00Z",
    decision_maker_user_id: str = "dm-1",
    **kwargs: Any,
) -> CertificationContext:
    """The canonical certified product: the full pre-issuance chain plus one live
    certificate issued at ``issue_clock``."""
    context = setup_certification_ready_product(api, **kwargs)
    set_clock(api, issue_clock)
    context.certificate = issue_certificate(
        api,
        context.product_id,
        context.product_version,
        decision_maker_user_id=decision_maker_user_id,
    )
    return context


def add_certified_product(
    api: ApiClient,
    context: CertificationContext,
    *,
    name: str,
    sku: str,
    inclusion_pct: float = 60,
    requested_mark_tier: str = MarkTier.STANDARD,
    reviewer_user_id: str = "rev-1",
    ingredient_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a second product on the same facility that reuses an already approved
    ingredient, taking it all the way to an approved label. Returns a dict with
    the product row and the version to present at issuance."""
    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name=name,
        sku=sku,
        requested_mark_tier=requested_mark_tier,
    )
    link_ingredient(
        api,
        context.applicant_id,
        product["id"],
        ingredient_id or context.ingredient_id,
        inclusion_pct,
    )
    cleared = review_formula(
        api, product["id"], decision=Decision.CLEAR, reviewer_user_id=reviewer_user_id
    )
    planned = activate_testing_plan(
        api, product["id"], cleared["version"], reviewer_user_id=reviewer_user_id
    )
    labelled = review_label(
        api,
        product["id"],
        decision=Decision.APPROVE,
        mark_tier_granted=requested_mark_tier,
        reviewer_user_id=reviewer_user_id,
    )
    return {
        "product": labelled,
        "version": labelled["version"],
        "cleared_version": cleared["version"],
        "planned_version": planned["version"],
    }


def setup_active_testing_plan(
    api: ApiClient,
    *,
    clock: str = CLOCK_START,
    ingredients: Sequence[IngredientSpec] = DEFAULT_INGREDIENTS,
    **kwargs: Any,
) -> CertificationContext:
    """A product whose formula is cleared and whose testing plan is active, with no
    label review and no audit: the minimum state a lot test needs."""
    kwargs.setdefault("review_label_decision", None)
    kwargs.setdefault("run_audit", False)
    return setup_certification_ready_product(
        api, clock=clock, ingredients=ingredients, **kwargs
    )


def setup_open_nonconformance(
    api: ApiClient,
    *,
    severity: str = "MAJOR",
    category: str = "DOCUMENTATION",
    source_type: str = "AUDIT",
    raiser_user_id: str = "aud-1",
    link_certificate: bool = True,
    link_audit: bool = False,
    context: Optional[CertificationContext] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An issued certificate plus one open nonconformance against its applicant.

    Returns ``{"context": CertificationContext, "nonconformance": row}``.
    """
    context = context or setup_issued_certificate(api, **kwargs)
    nonconformance = raise_nonconformance(
        api,
        context.applicant_id,
        raiser_user_id=raiser_user_id,
        source_type=source_type,
        category=category,
        severity=severity,
        certificate_id=context.certificate_id if link_certificate else None,
        audit_id=context.audit_id if link_audit else None,
    )
    return {"context": context, "nonconformance": nonconformance}


def submit_corrective_action(
    api: ApiClient,
    applicant_id: str,
    nonconformance_id: str,
    expected_version: int,
    *,
    plan_text: str = "Retrain the line crew and re-issue the allergen control record.",
) -> Dict[str, Any]:
    headers = make_applicant_contact_headers(applicant_id)
    return get_success_data(
        api.submit_corrective_action_plan(
            nonconformance_id,
            headers,
            expected_nonconformance_version=expected_version,
            ca_plan_text=plan_text,
        )
    )


def decide_corrective_action(
    api: ApiClient,
    nonconformance_id: str,
    *,
    decision: str = Decision.ACCEPT,
    reviewer_user_id: str = "rev-2",
    ca_rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_corrective_action(
            nonconformance_id,
            make_reviewer_headers(reviewer_user_id),
            decision=decision,
            ca_rejection_reason=ca_rejection_reason,
        )
    )


def verify_corrective_action(
    api: ApiClient,
    nonconformance_id: str,
    *,
    effectiveness_confirmed: bool = True,
    auditor_user_id: str = "aud-2",
) -> Dict[str, Any]:
    return get_success_data(
        api.verify_nonconformance(
            nonconformance_id,
            make_auditor_headers(auditor_user_id),
            effectiveness_confirmed=effectiveness_confirmed,
        )
    )


def suspend_certificate(
    api: ApiClient,
    certificate_id: str,
    *,
    suspension_reason: str = "CHANGE_REQUIRES_RECERT",
    decision_maker_user_id: str = "dm-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_certificate(
            certificate_id,
            make_decision_maker_headers(decision_maker_user_id),
            suspension_reason=suspension_reason,
        )
    )


def reinstate_certificate(
    api: ApiClient, certificate_id: str, *, decision_maker_user_id: str = "dm-2"
) -> Dict[str, Any]:
    return get_success_data(
        api.reinstate_certificate(
            certificate_id, make_decision_maker_headers(decision_maker_user_id)
        )
    )


def revoke_certificate(
    api: ApiClient,
    certificate_id: str,
    *,
    revocation_reason: str = "VOLUNTARY_WITHDRAWAL",
    decision_maker_user_id: str = "dm-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.revoke_certificate(
            certificate_id,
            make_decision_maker_headers(decision_maker_user_id),
            revocation_reason=revocation_reason,
        )
    )


def file_complaint(
    api: ApiClient, certificate_id: str, **overrides: Any
) -> Dict[str, Any]:
    from .factories import complaint_payload

    payload = complaint_payload(certificate_id, **overrides)
    return get_success_data(api.create_complaint(ADMIN, **payload))


def triage_complaint(
    api: ApiClient, complaint_id: str, *, reviewer_user_id: str = "rev-1"
) -> Dict[str, Any]:
    return get_success_data(
        api.triage_complaint(complaint_id, make_reviewer_headers(reviewer_user_id))
    )


def record_investigation_outcome(
    api: ApiClient,
    complaint_id: str,
    *,
    outcome: str = "SUBSTANTIATED",
    outcome_evidence: str = "CROSS_CONTACT",
    reviewer_user_id: str = "rev-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.record_investigation_outcome(
            complaint_id,
            make_reviewer_headers(reviewer_user_id),
            outcome=outcome,
            outcome_evidence=outcome_evidence,
        )
    )


def file_change_notification(
    api: ApiClient, applicant_id: str, certificate_id: str, **overrides: Any
) -> Dict[str, Any]:
    from .factories import change_notification_payload

    payload = change_notification_payload(certificate_id, **overrides)
    headers = make_applicant_contact_headers(applicant_id)
    return get_success_data(api.create_change_notification(headers, **payload))


def assess_change_notification(
    api: ApiClient,
    notification_id: str,
    *,
    decision: str = Decision.ACCEPT,
    impact_level: str = "LOW",
    reviewer_user_id: str = "rev-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.assess_change_notification(
            notification_id,
            make_reviewer_headers(reviewer_user_id),
            decision=decision,
            impact_level=impact_level,
        )
    )


def read_applicant(api: ApiClient, applicant_id: str) -> Dict[str, Any]:
    return validate_success(api.get_applicant(applicant_id, ADMIN))


def read_facility(api: ApiClient, facility_id: str) -> Dict[str, Any]:
    return validate_success(api.get_facility(facility_id, ADMIN))


def read_supplier(api: ApiClient, supplier_id: str) -> Dict[str, Any]:
    return validate_success(api.get_supplier(supplier_id, ADMIN))


def read_supplier_document(api: ApiClient, document_id: str) -> Dict[str, Any]:
    return validate_success(api.get_supplier_document(document_id, ADMIN))


def read_ingredient(api: ApiClient, ingredient_id: str) -> Dict[str, Any]:
    return validate_success(api.get_ingredient(ingredient_id, ADMIN))


def read_product(api: ApiClient, product_id: str) -> Dict[str, Any]:
    return validate_success(api.get_product(product_id, ADMIN))


def read_lot_test(api: ApiClient, lot_test_id: str) -> Dict[str, Any]:
    return validate_success(api.get_lot_test(lot_test_id, ADMIN))


def read_audit(api: ApiClient, audit_id: str) -> Dict[str, Any]:
    return validate_success(api.get_audit(audit_id, ADMIN))


def read_certificate(api: ApiClient, certificate_id: str) -> Dict[str, Any]:
    return validate_success(api.get_certificate(certificate_id, ADMIN))


def read_nonconformance(api: ApiClient, nonconformance_id: str) -> Dict[str, Any]:
    return validate_success(api.get_nonconformance(nonconformance_id, ADMIN))


def read_complaint(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    return validate_success(api.get_complaint(complaint_id, ADMIN))


def read_change_notification(api: ApiClient, notification_id: str) -> Dict[str, Any]:
    return validate_success(api.get_change_notification(notification_id, ADMIN))
