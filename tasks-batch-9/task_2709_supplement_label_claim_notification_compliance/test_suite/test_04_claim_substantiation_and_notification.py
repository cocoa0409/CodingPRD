"""Claims, substantiation dossiers, evidence scoring and the FDA notification.

A claim carries two independent status dimensions. The substantiation dimension
runs the author / reviewer / approver gauntlet of PRD §3.4, while the notification
dimension is opened only by the launch machinery of PRD §3.6.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CLAIM_NOTIFICATION_NOT_DUE,
    ERR_CLAIM_NOT_FOUND,
    ERR_DISCLAIMER_MISSING,
    ERR_DOSSIER_STATE_INVALID,
    ERR_DUPLICATE_CLAIM_TEXT,
    ERR_PRODUCT_LABEL_FROZEN,
    ERR_STALE_CLAIM_VERSION,
)
from test_helpers.assertions import (
    assert_calendar_date,
    assert_instant,
    assert_posture,
    assert_risk_index,
    assert_score,
)
from test_helpers.constants import (
    BASIS_PRODUCT_LAUNCH,
    CLAIM_TYPE_STRUCTURE_FUNCTION,
    DECISION_DISQUALIFY,
    DECISION_PROBATION,
    DOSSIER_ACCEPTED,
    DOSSIER_DRAFT,
    DOSSIER_UNDER_REVIEW,
    FDA_DISCLAIMER_TEXT,
    IDENTITY_METHOD_HPTLC,
    LIFECYCLE_MARKETED,
    NOTIFICATION_NOT_DUE,
    NOTIFICATION_SUBMITTED_TIMELY,
    PANEL_FORMAT_STANDARD,
    PANEL_STATUS_LOCKED,
    PANEL_STATUS_SUPERSEDED,
    PANEL_STATUS_VALIDATED,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    SUBSTANTIATION_APPROVED,
    SUBSTANTIATION_DRAFT,
    SUBSTANTIATION_UNDER_REVIEW,
    SUPPLIER_DISQUALIFIED,
    WARNING_PEDIATRIC,
)
from test_helpers.factories import (
    claim_payload,
    dossier_payload,
    evidence_payload,
    notify_fda_payload,
    qualification_decision_payload,
    start_marketing_payload,
)
from test_helpers.fixtures import (
    claim_version,
    make_accepted_coa,
    make_approved_claim,
    make_claim,
    make_claim_under_review,
    make_dossier,
    make_draft_panel,
    make_grandfathered_ingredient,
    make_line,
    make_lot,
    make_product,
    make_qualified_supplier,
    set_clock,
)

PHANTOM_CLAIM_ID = "00000000-0000-4000-8000-000000000000"

# Freezes at a final score of 78.00: 30.00 + 30.00 + 18.00.
DISCLAIMER_STUDY_SET = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Immunol Nutr 2024;12:31-44",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 240,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Clin Nutr Trials 2025;7:90-102",
    },
    {
        "study_type": "OBSERVATIONAL_HUMAN",
        "subject_count": 1200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Nutr Epidemiol 2025;11:5-19",
    },
]

# Freezes at a final score of 90.00: three human trials at full credit.
THREE_RCT_STUDY_SET = [
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Immunol Nutr 2024;12:31-44",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 150,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "Clin Nutr Trials 2025;7:90-102",
    },
    {
        "study_type": "RCT_HUMAN",
        "subject_count": 120,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": "J Nutr Sci 2026;3:44-58",
    },
]


def test_fetching_an_unknown_claim_reports_the_claim_specific_404(api, auditor_headers):
    """The 404 code names the collection that was addressed.

    PRD §2.4: "When the identifier names no existing row, the request fails with
    404 and the type-specific code for the collection addressed:
    ``ERR_PRODUCT_NOT_FOUND``, ``ERR_INGREDIENT_NOT_FOUND``,
    ``ERR_PRODUCT_INGREDIENT_NOT_FOUND``, ``ERR_CLAIM_NOT_FOUND`` ..."

    Design: Corner/entities/corner_claim_get_unknown_id_returns_claim_not_found
    """
    response = api.get_claim(PHANTOM_CLAIM_ID, auditor_headers)
    error = validate_error(response, ERR_CLAIM_NOT_FOUND, 404)
    assert error["error_id"] == ERR_CLAIM_NOT_FOUND
    assert error["message"].strip() != ""


def test_claim_text_uniqueness_is_scoped_to_one_product(api, specialist_headers):
    """The same wording is refused on one product and welcomed on another.

    PRD §3.4: "``claim_text`` must be unique among the product's claims whose
    ``substantiation_status`` is anything other than ``WITHDRAWN``, checked both at
    drafting and at rewording; a duplicate is refused with
    ``ERR_DUPLICATE_CLAIM_TEXT`` (HTTP 409)."

    Design: Corner/validations/corner_duplicate_claim_text_on_same_product_rejected
    """
    ascorbic = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product_a = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Daily C",
        net_quantity_g=60,
        servings_per_container=30,
    )
    product_b = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Daily C Plus",
        net_quantity_g=90,
        servings_per_container=45,
    )
    text = "Supports immune function"

    make_claim(
        api,
        product_a["id"],
        ascorbic["id"],
        specialist_headers,
        claim_text=text,
        claim_type=CLAIM_TYPE_STRUCTURE_FUNCTION,
    )

    duplicate = api.create_claim(
        claim_payload(
            product_a["id"],
            ascorbic["id"],
            claim_text=text,
            claim_type=CLAIM_TYPE_STRUCTURE_FUNCTION,
        ),
        specialist_headers,
    )
    validate_error(duplicate, ERR_DUPLICATE_CLAIM_TEXT, 409)

    on_other_product = validate_success(
        api.create_claim(
            claim_payload(
                product_b["id"],
                ascorbic["id"],
                claim_text=text,
                claim_type=CLAIM_TYPE_STRUCTURE_FUNCTION,
            ),
            specialist_headers,
        ),
        201,
    )
    assert on_other_product["substantiation_status"] == SUBSTANTIATION_DRAFT
    assert on_other_product["revision_round"] == 0

    for product_id in (product_a["id"], product_b["id"]):
        reread = validate_success(api.get_product(product_id, specialist_headers), 200)
        assert reread["active_claim_count"] == 0


def test_each_evidence_append_recomputes_the_screening_score(api, specialist_headers):
    """The provisional score is recomputed from scratch on every append.

    PRD §3.4: "The **provisional screening score** is what ``screening_score``
    holds while the dossier is in ``DRAFT``, and it is recomputed from scratch on
    every evidence append. Every study in ``evidence_studies`` participates
    regardless of peer-review status, the human-study denominator is 50 subjects,
    and peer review is not enforced, so the peer factor is 1.0 for every study
    including those whose ``peer_reviewed`` is false."

    Design: Corner/endpoints/corner_evidence_append_recomputes_screening_score_each_time
    """
    ascorbic = make_grandfathered_ingredient(
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
    claim = make_claim(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        claim_text="Supports immune function",
        claim_type=CLAIM_TYPE_STRUCTURE_FUNCTION,
    )
    dossier = make_dossier(api, claim["id"], specialist_headers)
    assert dossier["dossier_status"] == DOSSIER_DRAFT
    assert dossier["study_count"] == 0
    assert_score(dossier["screening_score"], 0.00)

    after_first = get_success_data(
        api.append_evidence(
            dossier["id"],
            evidence_payload(
                study_type="RCT_HUMAN",
                subject_count=200,
                dose_match=True,
                peer_reviewed=True,
            ),
            specialist_headers,
        )
    )
    assert after_first["study_count"] == 1
    assert_score(after_first["screening_score"], 30.00)

    after_second = get_success_data(
        api.append_evidence(
            dossier["id"],
            evidence_payload(
                study_type="ANIMAL",
                subject_count=20,
                dose_match=False,
                peer_reviewed=False,
            ),
            specialist_headers,
        )
    )
    assert after_second["study_count"] == 2
    assert_score(after_second["screening_score"], 34.80)

    reread = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert reread["dossier_status"] == DOSSIER_DRAFT
    assert reread["final_score"] is None
    assert len(reread["evidence_studies"]) == 2


def test_evidence_cannot_be_appended_once_the_dossier_leaves_draft(
    api, specialist_headers
):
    """Submitting for review freezes the file as well as the score.

    PRD §3.4: "Appending to a dossier that has left ``DRAFT`` is refused with
    ``ERR_DOSSIER_STATE_INVALID``." The same section pins the frozen figure: the
    final score is "computed exactly once and frozen into ``final_score`` at the
    moment the claim enters substantiation review; it is never recomputed
    afterwards, no matter what happens to the dossier."

    Design: Corner/errors/corner_evidence_append_on_dossier_under_review_rejected
    """
    ascorbic = make_grandfathered_ingredient(
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
    claim, dossier = make_claim_under_review(
        api,
        product["id"],
        ascorbic["id"],
        [
            {
                "study_type": "RCT_HUMAN",
                "subject_count": 200,
                "dose_match": True,
                "peer_reviewed": True,
                "citation": "Immunol Nutr 2024;12:31-44",
            }
        ],
        specialist_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": CLAIM_TYPE_STRUCTURE_FUNCTION,
        },
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW
    assert dossier["dossier_status"] == DOSSIER_UNDER_REVIEW
    assert_score(dossier["final_score"], 30.00)

    refused = api.append_evidence(
        dossier["id"],
        evidence_payload(
            study_type="RCT_HUMAN",
            subject_count=300,
            dose_match=True,
            peer_reviewed=True,
        ),
        specialist_headers,
    )
    validate_error(refused, ERR_DOSSIER_STATE_INVALID, 409)

    reread = validate_success(api.get_dossier(dossier["id"], specialist_headers), 200)
    assert reread["study_count"] == 1
    assert_score(reread["final_score"], 30.00)
    assert reread["dossier_status"] == DOSSIER_UNDER_REVIEW

    claim_after = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert claim_after["substantiation_status"] == SUBSTANTIATION_UNDER_REVIEW


def test_dossier_creation_refuses_a_stale_claim_version(api, specialist_headers):
    """Rewording the claim invalidates the version the author had read.

    PRD §2.6: "A request that opens a dossier must carry
    ``expected_claim_version``, a non-optional field holding the ``version`` the
    client last read from the target ``StructureFunctionClaim``. If that value does
    not equal the claim's current ``version``, the request is rejected with
    ``ERR_STALE_CLAIM_VERSION`` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_dossier_create_with_stale_claim_version_rejected
    """
    ascorbic = make_grandfathered_ingredient(
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
    claim = make_claim(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        claim_text="Supports immune function",
        claim_type=CLAIM_TYPE_STRUCTURE_FUNCTION,
    )
    stale_version = claim["version"]
    assert stale_version == 1

    reworded = validate_success(
        api.patch_claim(
            claim["id"],
            {"claim_text": "Helps support normal immune function"},
            specialist_headers,
        ),
        200,
    )
    assert reworded["version"] == 2

    refused = api.create_dossier(
        dossier_payload(claim["id"], stale_version), specialist_headers
    )
    validate_error(refused, ERR_STALE_CLAIM_VERSION, 412)

    _rows, meta = validate_paginated(
        api.list_dossiers(specialist_headers, {"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 0

    fresh = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert fresh["version"] == 2
    assert fresh["claim_text"] == "Helps support normal immune function"

    created = validate_success(
        api.create_dossier(
            dossier_payload(claim["id"], claim_version(api, claim["id"], specialist_headers)),
            specialist_headers,
        ),
        201,
    )
    assert created["dossier_status"] == DOSSIER_DRAFT
    assert created["study_count"] == 0
    assert_score(created["screening_score"], 0.00)
    assert created["final_score"] is None


def test_the_disclaimer_becomes_mandatory_only_once_a_claim_is_approved(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """The same printed panel passes before approval and fails after it.

    PRD §3.5: "If the product has at least one claim whose ``substantiation_status``
    is ``APPROVED`` and whose ``claim_type`` is ``STRUCTURE_FUNCTION`` or
    ``GENERAL_WELLBEING``, then the panel's ``disclaimer_text`` must be present and
    must equal, verbatim, the sentence pair ... An absent or altered disclaimer in
    that circumstance is refused with ``ERR_DISCLAIMER_MISSING`` (HTTP 422). A
    product with no approved claim of either type, or with only an approved
    ``NUTRIENT_CONTENT`` claim, has no disclaimer obligation."

    Design: Corner/validations/corner_disclaimer_required_only_when_approved_claim_exists
    """
    ascorbic = make_grandfathered_ingredient(
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
    make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=45,
        panel_position=1,
    )

    first_panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=30,
    )
    assert first_panel["disclaimer_text"] is None
    cleared = validate_success(
        api.validate_label_panel(first_panel["id"], specialist_headers), 200
    )
    assert cleared["panel_status"] == PANEL_STATUS_VALIDATED
    assert cleared["panel_lines_required"] == 6
    assert cleared["required_warning_codes"] == [WARNING_PEDIATRIC]

    claim, dossier = make_approved_claim(
        api,
        product["id"],
        ascorbic["id"],
        DISCLAIMER_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        officer_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": CLAIM_TYPE_STRUCTURE_FUNCTION,
        },
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert dossier["dossier_status"] == DOSSIER_ACCEPTED
    assert_score(dossier["final_score"], 78.00)

    second_panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=30,
        supersedes_panel_id=first_panel["id"],
    )
    refused = api.validate_label_panel(second_panel["id"], specialist_headers)
    validate_error(refused, ERR_DISCLAIMER_MISSING, 422)

    printed = validate_success(
        api.patch_label_panel(
            second_panel["id"],
            {"disclaimer_text": FDA_DISCLAIMER_TEXT},
            specialist_headers,
        ),
        200,
    )
    assert printed["disclaimer_text"] == FDA_DISCLAIMER_TEXT

    accepted = validate_success(
        api.validate_label_panel(second_panel["id"], specialist_headers), 200
    )
    assert accepted["panel_status"] == PANEL_STATUS_VALIDATED
    assert accepted["panel_lines_required"] == 7
    assert accepted["panel_lines_allowed"] == 20

    retired = validate_success(
        api.get_label_panel(first_panel["id"], specialist_headers), 200
    )
    assert retired["panel_status"] == PANEL_STATUS_SUPERSEDED

    reread = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert reread["active_claim_count"] == 1


def test_a_notification_cannot_be_filed_before_the_launch_opens_the_window(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """Approval on an unlaunched product leaves the notification dimension shut.

    PRD §3.6: "Approval of a claim on a product still in ``DRAFT`` or
    ``LABEL_LOCKED`` leaves ``notification_status`` at ``NOT_DUE``, with
    ``notification_due_date`` and ``notification_due_basis`` both null, until the
    launch sweeps it up." The same section adds that "filing against a claim whose
    notification dimension is ``NOT_DUE``, ``SUBMITTED_TIMELY`` or
    ``SUBMITTED_LATE`` is refused with ``ERR_CLAIM_NOTIFICATION_NOT_DUE`` (HTTP
    409)".

    Design: Corner/errors/corner_notify_fda_while_notification_not_due_rejected
    """
    ascorbic = make_grandfathered_ingredient(
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
    make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=45,
        panel_position=1,
    )
    claim, dossier = make_approved_claim(
        api,
        product["id"],
        ascorbic["id"],
        THREE_RCT_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        officer_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": CLAIM_TYPE_STRUCTURE_FUNCTION,
        },
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert claim["notification_status"] == NOTIFICATION_NOT_DUE
    assert_score(dossier["final_score"], 90.00)

    refused = api.notify_fda(
        claim["id"], notify_fda_payload("FDA-SF-2026-0001"), officer_headers
    )
    validate_error(refused, ERR_CLAIM_NOTIFICATION_NOT_DUE, 409)

    reread = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert reread["notification_status"] == NOTIFICATION_NOT_DUE
    assert reread["notification_due_date"] is None
    assert reread["notification_due_basis"] is None
    assert reread["notified_at"] is None
    assert reread["submission_reference"] is None
    assert reread["substantiation_status"] == SUBSTANTIATION_APPROVED

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["active_claim_count"] == 1


def test_filing_on_exactly_the_due_date_is_still_timely(
    api, specialist_headers, reviewer_headers, officer_headers
):
    """The deadline comparison is inclusive on the final calendar day.

    PRD §3.6: "Timeliness is decided by comparing the logical clock's UTC calendar
    date against ``notification_due_date``, inclusively. On or before the due date
    the claim moves ``DUE → SUBMITTED_TIMELY``; strictly after it, ``DUE →
    SUBMITTED_LATE``. Filing on exactly the due date is timely." The window itself
    comes from the launch: "the basis is ``PRODUCT_LAUNCH_BASIS`` and
    ``notification_due_date`` is the product's ``marketing_start_date`` plus 30
    days".

    Design: Corner/calculations/corner_claim_notification_filed_on_exact_due_date_is_timely
    """
    ascorbic = make_grandfathered_ingredient(
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
    make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=45,
        panel_position=1,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        panel_format=PANEL_FORMAT_STANDARD,
        serving_size_text="1 capsule",
        serving_weight_g=2,
        servings_per_container_declared=30,
        effective_from="2026-09-01",
        effective_until="2027-08-31",
        disclaimer_text=FDA_DISCLAIMER_TEXT,
    )

    claim, dossier = make_approved_claim(
        api,
        product["id"],
        ascorbic["id"],
        DISCLAIMER_STUDY_SET,
        specialist_headers,
        reviewer_headers,
        officer_headers,
        claim_overrides={
            "claim_text": "Supports immune function",
            "claim_type": CLAIM_TYPE_STRUCTURE_FUNCTION,
        },
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_APPROVED
    assert_score(dossier["final_score"], 78.00)

    validated = validate_success(
        api.validate_label_panel(panel["id"], specialist_headers), 200
    )
    assert validated["panel_status"] == PANEL_STATUS_VALIDATED
    assert validated["panel_lines_required"] == 7
    locked = validate_success(api.lock_label_panel(panel["id"], officer_headers), 200)
    assert locked["panel_status"] == PANEL_STATUS_LOCKED

    set_clock(api, "2026-09-10T00:00:00Z", specialist_headers)
    marketed = validate_success(
        api.start_marketing(
            product["id"], start_marketing_payload("2026-09-10"), officer_headers
        ),
        200,
    )
    assert marketed["lifecycle_status"] == LIFECYCLE_MARKETED
    assert_calendar_date(marketed["marketing_start_date"], "2026-09-10")

    swept = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert swept["notification_due_basis"] == BASIS_PRODUCT_LAUNCH
    assert_calendar_date(swept["notification_due_date"], "2026-10-10")

    set_clock(api, "2026-10-10T23:59:59Z", specialist_headers)
    filed = validate_success(
        api.notify_fda(
            claim["id"], notify_fda_payload("SFC-2026-0777"), officer_headers
        ),
        200,
    )
    assert filed["notification_status"] == NOTIFICATION_SUBMITTED_TIMELY
    assert filed["submission_reference"] == "SFC-2026-0777"
    assert_instant(filed["notified_at"], "2026-10-10T23:59:59Z")
    assert_calendar_date(filed["notification_due_date"], "2026-10-10")
    assert filed["notification_due_basis"] == BASIS_PRODUCT_LAUNCH

    product_after = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert product_after["late_notification_count"] == 0
    assert product_after["lifecycle_status"] == LIFECYCLE_MARKETED
    assert_risk_index(product_after, 10)
    assert_posture(product_after, POSTURE_OPEN)


def test_a_frozen_label_stops_a_claim_before_its_evidence_is_examined(
    api, specialist_headers, quality_headers
):
    """The frozen gate is screened ahead of dossier readiness.

    PRD §2.9: "A ``FROZEN`` posture is an absolute stop on forward labelling and
    claim work: starting marketing, drafting a panel, validating a panel, locking a
    panel, submitting a claim for substantiation review and approving a claim are
    all refused with ``ERR_PRODUCT_LABEL_FROZEN`` (HTTP 409) while the governing
    product sits in ``FROZEN``." PRD §2.7 ranks that frozen-label gate at 11 and
    "dossier readiness at submission" at 16, so the posture is reported even though
    the claim also has no evidence file at all.

    Design: Corner/validations/corner_frozen_posture_blocks_claim_submission
    """
    maca = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Maca Boost",
        net_quantity_g=90,
        servings_per_container=30,
    )
    make_line(
        api,
        product["id"],
        maca["id"],
        specialist_headers,
        amount_per_serving_mg=1500,
        panel_position=1,
    )
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Andes Botanica SA",
        country_code="PE",
        audit_score=91,
    )
    lot = make_lot(
        api,
        supplier["id"],
        maca["id"],
        quality_headers,
        lot_code="AB-2026-0777",
        quantity_kg=30.00,
    )
    make_accepted_coa(
        api,
        lot["id"],
        quality_headers,
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=101.2,
    )
    validate_success(api.release_lot(lot["id"], quality_headers), 200)

    claim = make_claim(
        api,
        product["id"],
        maca["id"],
        specialist_headers,
        claim_text="Supports stamina",
        claim_type=CLAIM_TYPE_STRUCTURE_FUNCTION,
    )
    assert claim["substantiation_status"] == SUBSTANTIATION_DRAFT

    validate_success(
        api.qualification_decision(
            supplier["id"],
            qualification_decision_payload(
                DECISION_PROBATION,
                decision_note="Two open deviations from the last on-site audit.",
            ),
            quality_headers,
        ),
        200,
    )
    disqualified = validate_success(
        api.qualification_decision(
            supplier["id"],
            qualification_decision_payload(
                DECISION_DISQUALIFY,
                decision_note="Remediation window closed with no corrective action.",
            ),
            quality_headers,
        ),
        200,
    )
    assert disqualified["qualification_status"] == SUPPLIER_DISQUALIFIED

    frozen = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert_posture(frozen, POSTURE_FROZEN)

    refused = api.submit_claim_for_review(claim["id"], specialist_headers)
    validate_error(refused, ERR_PRODUCT_LABEL_FROZEN, 409)

    reread = validate_success(api.get_claim(claim["id"], specialist_headers), 200)
    assert reread["substantiation_status"] == SUBSTANTIATION_DRAFT
    assert reread["revision_round"] == 0
