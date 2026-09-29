"""Identity, role authorization, segregation of duties and path resolution.

Every request is screened in a fixed order: the identity headers first, the
role's presence on the endpoint's authorized list second, and the existence of
the row named by the path third. On top of that ordering sit two identity
comparisons that bite even when the role is right, and one ownership scope that
confines a supplier's own representative to its own row.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AER_NOT_FOUND,
    ERR_COA_NOT_FOUND,
    ERR_DOSSIER_NOT_FOUND,
    ERR_NDI_NOTIFICATION_NOT_FOUND,
    ERR_PANEL_NOT_FOUND,
    ERR_PRODUCT_INGREDIENT_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUPPLIER_NOT_FOUND,
    ERR_SUPPLIER_SCOPE_VIOLATION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import assert_score
from test_helpers.constants import (
    DOSSIER_ACCEPTED,
    DOSSIER_UNDER_REVIEW,
    LOT_QUARANTINED,
    NOTIFICATION_NOT_DUE,
    ROLE_CLAIM_APPROVAL_OFFICER,
    ROLE_SUBSTANTIATION_REVIEWER,
    SUBSTANTIATION_APPROVED,
    SUBSTANTIATION_UNDER_REVIEW,
    SUPPLIER_QUALIFIED,
    SUPPLIER_UNQUALIFIED,
)
from test_helpers.factories import (
    ingredient_lot_payload,
    product_payload,
    qualification_decision_payload,
    review_payload,
    supplier_payload,
)
from test_helpers.fixtures import (
    make_claim_under_review,
    make_claim_with_accepted_dossier,
    make_grandfathered_ingredient,
    make_product,
    make_qualified_supplier,
)
from test_helpers.test_users import (
    USER_CAO_01,
    USER_RAS_01,
    USER_SR_01,
    headers_for_role,
    make_supplier_representative_headers,
)

# Three peer-reviewed human trials, all at the labelled dose: the frozen final
# score is 90.00, so nothing but the acting identity can be at fault.
THREE_RCT_STUDY_SET = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Immunol Nutr 2024;12:1-14",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 150,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "J Nutr Sci 2025;9:44-58",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 120,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Clin Nutr Rep 2025;4:88-97",
    },
]

PHANTOM_IDS = [
    "00000000-0000-4000-8000-00000000000{}".format(n) for n in range(1, 9)
]


def _immune_claim_record(api, specialist_headers):
    """One VITAMIN ingredient, one draft product, ready for a claim."""
    ingredient = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Daily C",
        net_quantity_g=60,
        servings_per_container=30,
    )
    return ingredient, product


def test_a_request_carrying_no_identity_at_all_never_reaches_the_body(api, specialist_headers):
    """The authentication screen fires before the URL is resolved.

    PRD §2.1: "If either header is missing, present but empty, or if
    ``X-User-Role`` holds a string outside the six roles enumerated below, the
    request is rejected with ``ERR_UNAUTHENTICATED`` (HTTP 401). This is the first
    check performed on any request, before the URL is resolved to a resource."

    Design: Corner/errors/corner_request_without_role_header_is_unauthenticated
    """
    anonymous = api.raw_post(
        "/products",
        product_payload(
            brand_name="NutraCore",
            product_name="Anonymous Blend",
            net_quantity_g=60,
            servings_per_container=30,
        ),
        None,
    )
    validate_error(anonymous, ERR_UNAUTHENTICATED, 401)

    rows, meta = validate_paginated(api.list_products(specialist_headers))
    assert meta["total_count"] == 0
    assert rows == []


def test_the_quality_role_runs_both_of_its_exclusive_supplier_operations(
    api, quality_headers
):
    """Supplier onboarding belongs to one role, and it owns both halves.

    PRD §2.1: "A ``QualityAssuranceManager`` owns the incoming-material and safety
    side: supplier registration and qualification decisions, lot release and
    recall, certificate-of-analysis review, and adverse event triage." PRD §3.7
    pins the opening row: "A new supplier opens in ``qualification_status``
    ``UNQUALIFIED`` with ``coa_rejection_count`` at 0, ``total_released_kg`` at
    0.00, ``remediation_reference`` null and ``last_decision_at`` null."

    Design: Corner/rbac/corner_quality_manager_exclusive_supplier_operations_succeed
    """
    created = validate_success(
        api.create_supplier(
            supplier_payload(
                supplier_name="Cascade Ingredients LLC", country_code="US", audit_score=88
            ),
            quality_headers,
        ),
        201,
    )
    assert created["qualification_status"] == SUPPLIER_UNQUALIFIED
    assert created["coa_rejection_count"] == 0
    assert_score(created["total_released_kg"], 0.00)
    assert created["remediation_reference"] is None
    assert created["last_decision_at"] is None
    assert created["version"] == 1

    decided = validate_success(
        api.qualification_decision(
            created["id"], qualification_decision_payload("QUALIFY"), quality_headers
        ),
        200,
    )
    assert decided["qualification_status"] == SUPPLIER_QUALIFIED
    assert decided["audit_score"] == 88
    assert decided["version"] == 2


def test_the_specialist_who_built_the_record_still_cannot_approve_the_claim(
    api, specialist_headers, reviewer_headers
):
    """Approval is exclusive, so the authoring role is refused at rank 2.

    PRD §2.7 rank 2: "**Authorization.** The acting role appears on the target
    endpoint's authorized-role list — otherwise ``ERR_UNAUTHORIZED``." PRD §3.4
    names the holder of that operation: "Approval is reserved to a
    ``ClaimApprovalOfficer`` and requires the claim to be in
    ``UNDER_SUBSTANTIATION_REVIEW``, the product not to be ``FROZEN``, and the
    claim to have exactly one dossier in ``ACCEPTED``".

    Design: Corner/rbac/corner_specialist_cannot_approve_a_claim_role_denied
    """
    ingredient, product = _immune_claim_record(api, specialist_headers)
    claim, dossier = make_claim_with_accepted_dossier(
        api,
        product["id"],
        ingredient["id"],
        THREE_RCT_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": "STRUCTURE_FUNCTION",
        },
    )
    assert dossier["dossier_status"] == DOSSIER_ACCEPTED

    refused = api.approve_claim(claim["id"], specialist_headers)
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    reread = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert reread["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW
    assert reread["approved_by_user_id"] is None

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["active_claim_count"] == 0


def test_the_oversight_role_may_read_the_collection_it_cannot_write(
    api, auditor_headers
):
    """Read-only means every write is refused and every read is allowed.

    PRD §2.1: "A ``ComplianceAuditor`` is a read-only oversight role with access to
    every fetch, list and computed-read endpoint and no mutating capability
    whatsoever." PRD §2.7 rank 2 supplies the code: "The acting role appears on the
    target endpoint's authorized-role list — otherwise ``ERR_UNAUTHORIZED``."

    Design: Corner/rbac/corner_auditor_cannot_create_a_product_read_only_role
    """
    refused = api.create_product(
        product_payload(
            brand_name="AuditCo",
            product_name="Unauthorised Blend",
            net_quantity_g=60,
            servings_per_container=30,
        ),
        auditor_headers,
    )
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    rows, meta = validate_paginated(api.list_products(auditor_headers))
    assert meta["total_count"] == 0
    assert rows == []


def test_an_author_wearing_the_reviewer_role_may_not_clear_its_own_evidence(
    api, specialist_headers, reviewer_headers
):
    """Segregation compares identifiers, not roles, so the right role still fails.

    PRD §2.10: "At dossier review time, the acting ``X-User-ID`` must differ from
    the dossier's own ``authored_by_user_id``: an author may not review its own
    evidence." PRD §3.4 confirms the score is not the obstacle: "the frozen
    ``final_score`` must be at least 65.00 — the competent-and-reliable evidence
    threshold".

    Design: Corner/rbac/corner_dossier_author_cannot_review_own_dossier
    """
    ingredient, product = _immune_claim_record(api, specialist_headers)
    claim, dossier = make_claim_under_review(
        api,
        product["id"],
        ingredient["id"],
        THREE_RCT_STUDY_SET,
        specialist_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": "STRUCTURE_FUNCTION",
        },
    )
    assert dossier["dossier_status"] == DOSSIER_UNDER_REVIEW
    assert dossier["authored_by_user_id"] == USER_RAS_01
    assert_score(dossier["final_score"], 90.00)

    self_review = api.review_dossier(
        dossier["id"],
        review_payload("ACCEPT"),
        headers_for_role(ROLE_SUBSTANTIATION_REVIEWER, USER_RAS_01),
    )
    validate_error(self_review, ERR_SEGREGATION_OF_DUTIES, 409)

    held = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert held["dossier_status"] == DOSSIER_UNDER_REVIEW
    assert held["reviewed_by_user_id"] is None

    independent = validate_success(
        api.review_dossier(dossier["id"], review_payload("ACCEPT"), reviewer_headers), 200
    )
    assert independent["dossier_status"] == DOSSIER_ACCEPTED
    assert independent["reviewed_by_user_id"] == USER_SR_01
    assert_score(independent["final_score"], 90.00)
    assert claim["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW


def test_the_reviewer_who_cleared_the_evidence_may_not_also_sign_the_claim(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """The second segregation edge spans two rows and needs a third principal.

    PRD §2.10: "At claim approval time, the acting ``X-User-ID`` must differ from
    the ``reviewed_by_user_id`` recorded on the accepted dossier backing the claim:
    the reviewer who cleared the evidence may not also sign off the claim." PRD
    §3.4 pins the successful path: "Approval drives ``UNDER_SUBSTANTIATION_REVIEW →
    APPROVED``, stamps ``approved_by_user_id`` from ``X-User-ID`` and
    ``approved_at`` from the logical clock, clears ``requires_recheck`` to false,
    advances the product's ``active_claim_count`` by 1, and advances the claim's
    ``version``."

    Design: Corner/rbac/corner_claim_approver_must_not_be_the_dossier_reviewer
    """
    ingredient, product = _immune_claim_record(api, specialist_headers)
    claim, dossier = make_claim_with_accepted_dossier(
        api,
        product["id"],
        ingredient["id"],
        THREE_RCT_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": "STRUCTURE_FUNCTION",
        },
    )
    assert dossier["reviewed_by_user_id"] == USER_SR_01

    conflicted = api.approve_claim(
        claim["id"], headers_for_role(ROLE_CLAIM_APPROVAL_OFFICER, USER_SR_01)
    )
    validate_error(conflicted, ERR_SEGREGATION_OF_DUTIES, 409)

    interim = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert interim["active_claim_count"] == 0

    approved = validate_success(api.approve_claim(claim["id"], officer_headers), 200)
    assert approved["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert approved["approved_by_user_id"] == USER_CAO_01
    assert approved["notification_status"] == NOTIFICATION_NOT_DUE
    assert approved["requires_recheck"] is False

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["active_claim_count"] == 1


def test_a_supplier_representative_is_confined_to_its_own_supplier_row(
    api, specialist_headers, quality_headers
):
    """The same body is refused for a sibling supplier and accepted for its own.

    PRD §2.1: "For ``SupplierRepresentative``, by contrast, ``X-User-ID`` **is** the
    ``id`` of the acting ``Supplier``. Ownership checks on any resource that
    references a ``Supplier`` compare the resource's supplier foreign key to
    ``X-User-ID``: when a ``SupplierRepresentative`` receives a lot, the
    ``supplier_id`` in the body must equal ``X-User-ID``". PRD §3.7 pins the
    accepted outcome: "A new lot opens in ``lot_status`` ``QUARANTINED`` with
    ``identity_verified`` false, its full ``quantity_kg`` sitting in
    ``quarantined_quantity_kg``".

    Design: Corner/rbac/corner_supplier_rep_cannot_receive_a_lot_for_another_supplier
    """
    supplier_a = make_qualified_supplier(
        api, quality_headers, supplier_name="Andes Botanica SA", country_code="PE", audit_score=91
    )
    supplier_b = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Riverbend Botanicals",
        country_code="US",
        audit_score=84,
    )
    maca = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )
    representative = make_supplier_representative_headers(supplier_a["id"])

    cross = api.create_ingredient_lot(
        ingredient_lot_payload(
            supplier_b["id"], maca["id"], lot_code="CROSS-2026-01", quantity_kg=10.00
        ),
        representative,
    )
    validate_error(cross, ERR_SUPPLIER_SCOPE_VIOLATION, 403)

    _rows, meta = validate_paginated(
        api.list_ingredient_lots(quality_headers, {"supplier_id": supplier_b["id"]})
    )
    assert meta["total_count"] == 0

    own = validate_success(
        api.create_ingredient_lot(
            ingredient_lot_payload(
                supplier_a["id"], maca["id"], lot_code="CROSS-2026-01", quantity_kg=10.00
            ),
            representative,
        ),
        201,
    )
    assert own["lot_status"] == LOT_QUARANTINED
    assert own["identity_verified"] is False
    assert own["lot_code"] == "CROSS-2026-01"
    assert_score(own["quarantined_quantity_kg"], 10.00)


def test_each_reader_family_answers_with_its_own_not_found_code(api, auditor_headers):
    """Eight well-formed unknown identifiers, eight distinct 404 codes.

    PRD §2.7 rank 3: "**Path resource existence.** The row named by the endpoint's
    single path identifier exists — otherwise the type-specific 404 from §2.4." PRD
    §2.7 explains why the distinction matters: "a caller cannot distinguish 'the
    panel is frozen' from 'the panel does not exist' if the order is not fixed."

    Design: Corner/errors/corner_phantom_ids_trigger_each_remaining_not_found_error
    """
    probes = [
        (api.get_product(PHANTOM_IDS[0], auditor_headers), ERR_PRODUCT_NOT_FOUND),
        (
            api.get_product_ingredient(PHANTOM_IDS[1], auditor_headers),
            ERR_PRODUCT_INGREDIENT_NOT_FOUND,
        ),
        (api.get_dossier(PHANTOM_IDS[2], auditor_headers), ERR_DOSSIER_NOT_FOUND),
        (api.get_label_panel(PHANTOM_IDS[3], auditor_headers), ERR_PANEL_NOT_FOUND),
        (
            api.get_ndi_notification(PHANTOM_IDS[4], auditor_headers),
            ERR_NDI_NOTIFICATION_NOT_FOUND,
        ),
        (
            api.get_adverse_event_report(PHANTOM_IDS[5], auditor_headers),
            ERR_AER_NOT_FOUND,
        ),
        (api.get_supplier(PHANTOM_IDS[6], auditor_headers), ERR_SUPPLIER_NOT_FOUND),
        (api.get_coa(PHANTOM_IDS[7], auditor_headers), ERR_COA_NOT_FOUND),
    ]

    for response, expected_error in probes:
        body = validate_error(response, expected_error, 404)
        assert isinstance(body["message"], str)
        assert body["message"].strip() != ""
