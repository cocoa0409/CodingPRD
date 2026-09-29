"""Supplier qualification, lot disposition and certificate adjudication.

The incoming-material chain of PRD §3.7 runs supplier → lot → certificate, and
each link carries its own state guard, its own numeric bound and its own
conserved mass ledger.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AUDIT_SCORE_INSUFFICIENT,
    ERR_COA_NOT_ACCEPTABLE,
    ERR_COA_STATE_INVALID,
    ERR_IDENTITY_METHOD_NOT_APPROVED,
    ERR_LOT_CODE_DUPLICATE,
    ERR_LOT_IDENTITY_UNVERIFIED,
    ERR_LOT_NOT_FOUND,
    ERR_LOT_STATE_INVALID,
    ERR_REMEDIATION_REFERENCE_REQUIRED,
    ERR_SUPPLIER_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_instant,
    assert_lot_mass_identity,
    assert_money,
)
from test_helpers.constants import (
    COA_ACCEPTED,
    COA_RECEIVED,
    DECISION_ACCEPT,
    DECISION_PROBATION,
    DECISION_QUALIFY,
    DECISION_REINSTATE,
    DECISION_REJECT,
    IDENTITY_METHOD_HPLC,
    IDENTITY_METHOD_HPTLC,
    IDENTITY_METHOD_MASS_SPEC,
    LOT_QUARANTINED,
    SUPPLIER_PROBATION,
    SUPPLIER_QUALIFIED,
    SUPPLIER_UNQUALIFIED,
)
from test_helpers.factories import (
    coa_payload,
    ingredient_lot_payload,
    qualification_decision_payload,
    recall_payload,
    review_payload,
)
from test_helpers.fixtures import (
    make_coa,
    make_grandfathered_ingredient,
    make_lot,
    make_qualified_supplier,
    make_supplier,
)

PHANTOM_LOT_ID = "00000000-0000-4000-8000-000000000000"


def test_a_certificate_against_an_unknown_lot_reports_the_lot_404(api, quality_headers):
    """Referential existence is screened before the identity-method table.

    PRD §2.7 rank 5: "Then ``lot_id`` must name an existing lot
    (``ERR_LOT_NOT_FOUND``) on certificate intake." Because the method screen sits
    at rank 13 — "the approved identity-method screen at certificate intake" — a
    body naming no lot can never reach it, and there is no ingredient class to
    consult in any case.

    Design: Corner/entities/corner_coa_create_unknown_lot_id_returns_lot_not_found
    """
    response = api.create_coa(
        coa_payload(
            PHANTOM_LOT_ID,
            lab_name="Cascade Analytical",
            identity_test_method=IDENTITY_METHOD_HPTLC,
            identity_match=True,
            assay_percent_of_label=100.0,
            heavy_metals_pass=True,
            microbial_pass=True,
        ),
        quality_headers,
    )
    error = validate_error(response, ERR_LOT_NOT_FOUND, 404)
    assert error["error_id"] != ERR_IDENTITY_METHOD_NOT_APPROVED

    _rows, meta = validate_paginated(api.list_coas(quality_headers))
    assert meta["total_count"] == 0


def test_qualification_reads_the_audit_score_from_the_body_or_the_stored_row(
    api, quality_headers
):
    """A stored 65 blocks the decision; the same call carrying 72 clears it.

    PRD §3.7: "``QUALIFY`` is legal only from ``UNQUALIFIED`` and requires an
    ``audit_score`` — supplied in the request or already stored on the supplier — of
    at least 70; a missing or insufficient score is refused with
    ``ERR_AUDIT_SCORE_INSUFFICIENT`` (HTTP 422). It drives ``UNQUALIFIED →
    QUALIFIED``, records the score in ``audit_score``, and stamps
    ``last_decision_at``."

    Design: Corner/state_machines/corner_supplier_qualify_requires_audit_score_at_least_seventy
    """
    supplier = make_supplier(
        api,
        quality_headers,
        supplier_name="Riverbend Botanicals",
        country_code="US",
        audit_score=65,
    )
    assert supplier["qualification_status"] == SUPPLIER_UNQUALIFIED
    assert supplier["audit_score"] == 65

    refused = api.qualification_decision(
        supplier["id"], qualification_decision_payload(DECISION_QUALIFY), quality_headers
    )
    validate_error(refused, ERR_AUDIT_SCORE_INSUFFICIENT, 422)

    still_unqualified = validate_success(
        api.get_supplier(supplier["id"], quality_headers), 200
    )
    assert still_unqualified["qualification_status"] == SUPPLIER_UNQUALIFIED
    assert still_unqualified["last_decision_at"] is None

    qualified = validate_success(
        api.qualification_decision(
            supplier["id"],
            qualification_decision_payload(DECISION_QUALIFY, audit_score=72),
            quality_headers,
        ),
        200,
    )
    assert qualified["qualification_status"] == SUPPLIER_QUALIFIED
    assert qualified["audit_score"] == 72
    assert_instant(qualified["last_decision_at"], "2026-08-01T00:00:00Z")
    assert_money(qualified["total_released_kg"], 0.00)


def test_a_quarantined_lot_cannot_be_recalled(api, specialist_headers, quality_headers):
    """Recall compensates a release, so it is illegal before one has happened.

    PRD §3.7: "Recall is the compensating action for release. It requires the lot to
    be in ``RELEASED`` and a ``recall_reason``, drives ``RELEASED → RECALLED``,
    stamps ``recalled_at``". PRD §2.7 rank 9 adds that "A lot must be
    ``QUARANTINED`` to be released and ``RELEASED`` to be recalled, otherwise
    ``ERR_LOT_STATE_INVALID``".

    Design: Corner/state_machines/corner_recall_of_quarantined_lot_rejected
    """
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Baltic Extracts",
        country_code="LT",
        audit_score=88,
    )
    zinc = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Zinc Picolinate",
        ingredient_class="MINERAL",
        daily_intake_mg=15,
        rdi_mg=11,
    )
    lot = make_lot(
        api,
        supplier["id"],
        zinc["id"],
        quality_headers,
        lot_code="BE-2026-0007",
        quantity_kg=20.00,
    )
    assert lot["lot_status"] == LOT_QUARANTINED

    refused = api.recall_lot(
        lot["id"],
        recall_payload("Operator error - wrong lot selected."),
        quality_headers,
    )
    validate_error(refused, ERR_LOT_STATE_INVALID, 409)

    reread = validate_success(api.get_ingredient_lot(lot["id"], quality_headers), 200)
    assert reread["lot_status"] == LOT_QUARANTINED
    assert_money(reread["quarantined_quantity_kg"], 20.00)
    assert reread["recalled_at"] is None
    assert_lot_mass_identity(reread)

    supplier_after = validate_success(
        api.get_supplier(supplier["id"], quality_headers), 200
    )
    assert_money(supplier_after["total_released_kg"], 0.00)


def test_a_lot_code_is_unique_per_supplier_and_free_on_another(
    api, specialist_headers, quality_headers
):
    """The same printed code is refused on one supplier and accepted on another.

    PRD §3.7: "``lot_code`` must be unique per supplier across all of that
    supplier's lots regardless of their ``lot_status``, and a duplicate is refused
    with ``ERR_LOT_CODE_DUPLICATE`` (HTTP 409)."

    Design: Corner/validations/corner_lot_code_uniqueness_is_scoped_per_supplier
    """
    supplier_a = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Andes Botanica SA",
        country_code="PE",
        audit_score=91,
    )
    supplier_b = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Baltic Extracts",
        country_code="LT",
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
    first_lot = make_lot(
        api,
        supplier_a["id"],
        maca["id"],
        quality_headers,
        lot_code="SHARED-0001",
        quantity_kg=15.00,
    )

    duplicate = api.create_ingredient_lot(
        ingredient_lot_payload(
            supplier_a["id"], maca["id"], lot_code="SHARED-0001", quantity_kg=5.00
        ),
        quality_headers,
    )
    validate_error(duplicate, ERR_LOT_CODE_DUPLICATE, 409)

    reused = validate_success(
        api.create_ingredient_lot(
            ingredient_lot_payload(
                supplier_b["id"], maca["id"], lot_code="SHARED-0001", quantity_kg=5.00
            ),
            quality_headers,
        ),
        201,
    )
    assert reused["lot_status"] == LOT_QUARANTINED
    assert_money(reused["quarantined_quantity_kg"], 5.00)
    assert_lot_mass_identity(reused)

    rows_a, meta_a = validate_paginated(
        api.list_ingredient_lots(quality_headers, {"supplier_id": supplier_a["id"]})
    )
    assert meta_a["total_count"] == 1
    assert rows_a[0]["id"] == first_lot["id"]

    rows_b, meta_b = validate_paginated(
        api.list_ingredient_lots(quality_headers, {"supplier_id": supplier_b["id"]})
    )
    assert meta_b["total_count"] == 1
    assert rows_b[0]["id"] == reused["id"]


def test_the_assay_ceiling_is_inclusive_at_one_hundred_and_twenty(
    api, specialist_headers, quality_headers, quality_alt_headers
):
    """Exactly 120.0 is acceptable material; 120.1 is not.

    PRD §3.7: "``coa_acceptable`` is true exactly when all four of the following
    hold: ``identity_match`` is true, ``assay_percent_of_label`` is at least 95.0 and
    at most 120.0 with both bounds inclusive so that exactly 95.0 and exactly 120.0
    both pass, ``heavy_metals_pass`` is true, and ``microbial_pass`` is true." The
    same section pins the consequence: "An ``ACCEPT`` requires ``coa_acceptable`` to
    be true, and an acceptance of an unacceptable certificate is refused with
    ``ERR_COA_NOT_ACCEPTABLE`` (HTTP 409)".

    Design: Corner/calculations/corner_coa_assay_upper_bound_is_inclusive_at_120
    """
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Andes Botanica SA",
        country_code="PE",
        audit_score=91,
    )
    maca = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )
    lot_at_bound = make_lot(
        api,
        supplier["id"],
        maca["id"],
        quality_headers,
        lot_code="AB-2026-0501",
        quantity_kg=10.00,
    )
    lot_over_bound = make_lot(
        api,
        supplier["id"],
        maca["id"],
        quality_headers,
        lot_code="AB-2026-0502",
        quantity_kg=10.00,
    )
    coa_at_bound = make_coa(
        api,
        lot_at_bound["id"],
        quality_headers,
        lab_name="Cascade Analytical",
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=120.0,
    )
    assert coa_at_bound["coa_acceptable"] is True
    coa_over_bound = make_coa(
        api,
        lot_over_bound["id"],
        quality_headers,
        lab_name="Cascade Analytical",
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=120.1,
    )
    assert coa_over_bound["coa_acceptable"] is False

    accepted = validate_success(
        api.review_coa(
            coa_at_bound["id"], review_payload(DECISION_ACCEPT), quality_alt_headers
        ),
        200,
    )
    assert accepted["coa_status"] == COA_ACCEPTED

    verified = validate_success(
        api.get_ingredient_lot(lot_at_bound["id"], quality_headers), 200
    )
    assert verified["identity_verified"] is True

    refused = api.review_coa(
        coa_over_bound["id"], review_payload(DECISION_ACCEPT), quality_alt_headers
    )
    validate_error(refused, ERR_COA_NOT_ACCEPTABLE, 409)

    still_received = validate_success(
        api.get_coa(coa_over_bound["id"], quality_headers), 200
    )
    assert still_received["coa_status"] == COA_RECEIVED
    unverified = validate_success(
        api.get_ingredient_lot(lot_over_bound["id"], quality_headers), 200
    )
    assert unverified["identity_verified"] is False

    supplier_after = validate_success(
        api.get_supplier(supplier["id"], quality_headers), 200
    )
    assert supplier_after["coa_rejection_count"] == 0


def test_the_approved_method_table_is_keyed_by_the_lots_ingredient_class(
    api, specialist_headers, quality_headers
):
    """A method legal for a vitamin is illegal for a mineral.

    PRD §3.7: "The method must be one of ``HPTLC``, ``HPLC``, ``MASS_SPEC``,
    ``DNA_BARCODE``, ``MICROSCOPY`` or ``ORGANOLEPTIC``, and it must be **approved
    for the ingredient class of the certificate's lot** ... A ``VITAMIN`` accepts
    ``HPLC`` or ``MASS_SPEC``. A ``MINERAL`` accepts only ``MASS_SPEC``." A mismatch
    "is always refused with ``ERR_IDENTITY_METHOD_NOT_APPROVED`` (HTTP 422), as is
    any other class-method mismatch."

    Design: Corner/calculations/corner_identity_method_table_is_ingredient_class_specific
    """
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Baltic Extracts",
        country_code="LT",
        audit_score=88,
    )
    zinc = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Zinc Picolinate",
        ingredient_class="MINERAL",
        daily_intake_mg=15,
        rdi_mg=11,
    )
    lot = make_lot(
        api,
        supplier["id"],
        zinc["id"],
        quality_headers,
        lot_code="BE-2026-0100",
        quantity_kg=25.00,
    )

    refused = api.create_coa(
        coa_payload(
            lot["id"],
            lab_name="Cascade Analytical",
            identity_test_method=IDENTITY_METHOD_HPLC,
            assay_percent_of_label=99.5,
        ),
        quality_headers,
    )
    validate_error(refused, ERR_IDENTITY_METHOD_NOT_APPROVED, 422)

    _rows, meta = validate_paginated(
        api.list_coas(quality_headers, {"lot_id": lot["id"]})
    )
    assert meta["total_count"] == 0

    accepted_method = validate_success(
        api.create_coa(
            coa_payload(
                lot["id"],
                lab_name="Cascade Analytical",
                identity_test_method=IDENTITY_METHOD_MASS_SPEC,
                assay_percent_of_label=99.5,
            ),
            quality_headers,
        ),
        201,
    )
    assert accepted_method["coa_status"] == COA_RECEIVED
    assert accepted_method["coa_acceptable"] is True

    unverified = validate_success(api.get_ingredient_lot(lot["id"], quality_headers), 200)
    assert unverified["identity_verified"] is False


def test_release_needs_an_accepted_certificate_not_merely_a_filed_one(
    api, specialist_headers, quality_headers
):
    """An unreviewed certificate leaves identity unverified.

    PRD §3.7: "And the lot's ``identity_verified`` must be true, meaning at least one
    certificate on that lot has reached ``ACCEPTED`` with a confirmed identity; a lot
    with no accepted certificate is refused with ``ERR_LOT_IDENTITY_UNVERIFIED`` (HTTP
    409)." The same section confirms that acceptability alone changes nothing:
    "Acceptability is computed but does not by itself dispose of anything — the
    certificate still requires review."

    Design: Corner/errors/corner_release_without_accepted_certificate_rejected
    """
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Andes Botanica SA",
        country_code="PE",
        audit_score=91,
    )
    maca = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )
    lot = make_lot(
        api,
        supplier["id"],
        maca["id"],
        quality_headers,
        lot_code="AB-2026-0900",
        quantity_kg=18.00,
    )
    coa = make_coa(
        api,
        lot["id"],
        quality_headers,
        lab_name="Cascade Analytical",
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=100.0,
    )
    assert coa["coa_status"] == COA_RECEIVED
    assert coa["coa_acceptable"] is True
    assert coa["reviewed_at"] is None

    refused = api.release_lot(lot["id"], quality_headers)
    validate_error(refused, ERR_LOT_IDENTITY_UNVERIFIED, 409)

    reread = validate_success(api.get_ingredient_lot(lot["id"], quality_headers), 200)
    assert reread["lot_status"] == LOT_QUARANTINED
    assert reread["identity_verified"] is False
    assert_money(reread["quarantined_quantity_kg"], 18.00)
    assert_lot_mass_identity(reread)

    supplier_after = validate_success(
        api.get_supplier(supplier["id"], quality_headers), 200
    )
    assert_money(supplier_after["total_released_kg"], 0.00)


def test_reinstatement_demands_a_named_corrective_action_file(api, quality_headers):
    """``REINSTATE`` is the only decision carrying a document requirement.

    PRD §3.7: "``REINSTATE`` is legal only from ``PROBATION``, requires a non-empty
    ``remediation_reference`` naming the corrective-action file — a missing one is
    refused with ``ERR_REMEDIATION_REFERENCE_REQUIRED`` (HTTP 422) — and drives
    ``PROBATION → QUALIFIED``, recording the reference and resetting
    ``coa_rejection_count`` to 0."

    Design: Corner/errors/corner_reinstate_without_remediation_reference_rejected
    """
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Riverbend Botanicals",
        country_code="US",
        audit_score=80,
    )
    on_probation = validate_success(
        api.qualification_decision(
            supplier["id"],
            qualification_decision_payload(DECISION_PROBATION),
            quality_headers,
        ),
        200,
    )
    assert on_probation["qualification_status"] == SUPPLIER_PROBATION

    refused = api.qualification_decision(
        supplier["id"],
        qualification_decision_payload(DECISION_REINSTATE),
        quality_headers,
    )
    validate_error(refused, ERR_REMEDIATION_REFERENCE_REQUIRED, 422)

    reread = validate_success(api.get_supplier(supplier["id"], quality_headers), 200)
    assert reread["qualification_status"] == SUPPLIER_PROBATION
    assert reread["remediation_reference"] is None


def test_two_terminal_guards_on_the_quality_chain_hold_their_ground(
    api, specialist_headers, quality_headers, quality_alt_headers
):
    """An accepted certificate and a healthy supplier both refuse a second move.

    PRD §2.7 rank 9: "A supplier qualification decision must be legal from the
    supplier's current ``qualification_status`` — ``QUALIFY`` only from
    ``UNQUALIFIED``, ``PROBATION`` only from ``QUALIFIED``, and both ``REINSTATE``
    and ``DISQUALIFY`` only from ``PROBATION`` — otherwise
    ``ERR_SUPPLIER_STATE_INVALID``. ... And a certificate of analysis must be in
    ``RECEIVED`` to be reviewed, otherwise ``ERR_COA_STATE_INVALID``."

    Design: Corner/errors/corner_reinstate_from_qualified_and_second_coa_review_rejected
    """
    supplier = make_qualified_supplier(
        api,
        quality_headers,
        supplier_name="Andes Botanica SA",
        country_code="PE",
        audit_score=91,
    )
    maca = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )
    lot = make_lot(
        api,
        supplier["id"],
        maca["id"],
        quality_headers,
        lot_code="AB-2026-1000",
        quantity_kg=25.00,
    )
    coa = make_coa(
        api,
        lot["id"],
        quality_headers,
        lab_name="Cascade Analytical",
        identity_test_method=IDENTITY_METHOD_HPTLC,
        assay_percent_of_label=101.5,
    )
    accepted = validate_success(
        api.review_coa(coa["id"], review_payload(DECISION_ACCEPT), quality_alt_headers),
        200,
    )
    assert accepted["coa_status"] == COA_ACCEPTED

    second_review = api.review_coa(
        coa["id"],
        review_payload(
            DECISION_REJECT, rejection_reason="Second thoughts on the chromatogram."
        ),
        quality_alt_headers,
    )
    validate_error(second_review, ERR_COA_STATE_INVALID, 409)

    coa_after = validate_success(api.get_coa(coa["id"], quality_headers), 200)
    assert coa_after["coa_status"] == COA_ACCEPTED
    assert coa_after["review_decision"] == DECISION_ACCEPT
    assert coa_after["rejection_reason"] is None

    reinstate = api.qualification_decision(
        supplier["id"],
        qualification_decision_payload(
            DECISION_REINSTATE, remediation_reference="CAPA-2026-021"
        ),
        quality_headers,
    )
    validate_error(reinstate, ERR_SUPPLIER_STATE_INVALID, 409)

    supplier_after = validate_success(
        api.get_supplier(supplier["id"], quality_headers), 200
    )
    assert supplier_after["qualification_status"] == SUPPLIER_QUALIFIED
    assert supplier_after["coa_rejection_count"] == 0
    assert supplier_after["remediation_reference"] is None

    lot_after = validate_success(api.get_ingredient_lot(lot["id"], quality_headers), 200)
    assert lot_after["identity_verified"] is True
    assert lot_after["lot_status"] == LOT_QUARANTINED
