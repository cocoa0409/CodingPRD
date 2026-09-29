"""Ingredient monographs, eligibility determination and NDI notification.

Every ingredient begins in ``DRAFT_ASSESSMENT`` and is settled by a single
decisive determination; an article that lands on ``NDI_REQUIRED`` then has to
travel the notification path of PRD §3.2 before it may be printed.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_INGREDIENT_INELIGIBLE_FOR_LABEL,
    ERR_INGREDIENT_STATE_INVALID,
    ERR_NDI_NOTIFICATION_STATE_INVALID,
    ERR_VALIDATION,
    ERR_WAITING_PERIOD_NOT_ELAPSED,
)
from test_helpers.constants import (
    ELIGIBILITY_GRANDFATHERED,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_NDI_OBJECTED,
    ELIGIBILITY_NDI_PENDING,
    NDI_STATUS_OBJECTED,
    NDI_STATUS_SUBMITTED,
    RESPONSE_ACKNOWLEDGE,
    RESPONSE_OBJECT,
)
from test_helpers.factories import (
    agency_response_payload,
    ingredient_payload,
    ndi_notification_payload,
    product_ingredient_payload,
)
from test_helpers.assertions import assert_instant
from test_helpers.fixtures import (
    make_ingredient,
    make_ndi_required_ingredient,
    make_product,
    make_submitted_notification,
    set_clock,
)


def test_ingredient_list_reports_total_count_across_two_windows(api, specialist_headers):
    """Three registered ingredients paginate through ``limit`` and ``offset``.

    PRD §2.3: "Every list response reports ``limit``, ``offset``, ``total_count``
    and ``has_more`` inside the ``meta`` object of the envelope, where
    ``total_count`` is the number of records matching the applied filters before
    the pagination window is taken and ``has_more`` indicates whether any
    matching record remains beyond the returned window." The same paragraph adds
    that "the alternate spellings ``page`` and ``page_size`` in particular carry
    no meaning in this API, because pagination is expressed only through
    ``limit`` and ``offset``", so the window is driven with those two names.

    Design: Corner/entities/corner_ingredient_list_paginates_with_total_count
    """
    first = make_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    second = make_ingredient(
        api,
        specialist_headers,
        ingredient_name="Zinc Picolinate",
        ingredient_class="MINERAL",
        daily_intake_mg=15,
        rdi_mg=11,
    )
    third = make_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )

    page_one, meta_one = validate_paginated(
        api.list_ingredients(specialist_headers, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_ingredients(specialist_headers, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2

    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(seen)) == 3
    assert set(seen) == {first["id"], second["id"], third["id"]}


def test_ingredient_registration_rejects_a_class_outside_the_taxonomy(
    api, specialist_headers
):
    """A made-up taxonomy class fails the body-shape screen.

    PRD §3.1: "The ``ingredient_class`` places the article in one of six taxonomy
    classes — ``VITAMIN``, ``MINERAL``, ``BOTANICAL``, ``AMINO_ACID``,
    ``PROBIOTIC`` or ``EXCLUDED_SUBSTANCE``". PRD §2.7 rank 4 requires that
    "every enum-typed field holds a value from its declared set" and reports a
    failure as ``ERR_VALIDATION`` (HTTP 422).

    Design: Corner/entities/corner_ingredient_create_rejects_unknown_ingredient_class
    """
    payload = ingredient_payload(
        ingredient_name="Mystery Superfood Blend",
        ingredient_class="SUPERFOOD",
        pre_dshea_marketed=True,
        chemical_alteration=False,
        daily_intake_mg=400,
    )
    response = api.create_ingredient(payload, specialist_headers)
    validate_error(response, ERR_VALIDATION, 422)

    rows, meta = validate_paginated(api.list_ingredients(specialist_headers))
    assert meta["total_count"] == 0
    assert rows == []


def test_second_eligibility_determination_on_a_settled_ingredient_is_refused(
    api, specialist_headers
):
    """The determination is a one-shot operation and never runs twice.

    PRD §3.1: "Attempting a second determination on an already-settled ingredient
    is refused with ``ERR_INGREDIENT_STATE_INVALID``", and the settled row keeps
    the ``determined_at`` stamp minted by the first run.

    Design: Corner/state_machines/corner_second_eligibility_determination_on_same_ingredient_rejected
    """
    ingredient = make_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        pre_dshea_marketed=True,
        chemical_alteration=False,
        daily_intake_mg=500,
        rdi_mg=90,
    )
    settled = validate_success(
        api.run_eligibility_determination(ingredient["id"], specialist_headers), 200
    )
    assert settled["eligibility_status"] == ELIGIBILITY_GRANDFATHERED
    assert settled["ndi_notification_required"] is False
    first_determined_at = settled["determined_at"]
    assert_instant(first_determined_at)

    response = api.run_eligibility_determination(ingredient["id"], specialist_headers)
    validate_error(response, ERR_INGREDIENT_STATE_INVALID, 409)

    reread = validate_success(api.get_ingredient(ingredient["id"], specialist_headers))
    assert reread["eligibility_status"] == ELIGIBILITY_GRANDFATHERED
    assert reread["determined_at"] == first_determined_at
    assert reread["ndi_notification_required"] is False


def test_premature_acknowledgement_is_refused_while_an_objection_is_exempt(
    api, specialist_headers
):
    """The waiting-period gate binds ``ACKNOWLEDGE`` alone.

    PRD §3.2: "An ``ACKNOWLEDGE`` may only be recorded once the waiting period has
    actually run — the logical clock must be at or after the package's
    ``waiting_period_end`` — and a premature acknowledgement is refused with
    ``ERR_WAITING_PERIOD_NOT_ELAPSED`` (HTTP 409). An ``OBJECT`` is exempt from
    that timing rule and may be recorded at any point after filing, because the
    agency is free to object early."

    Design: Corner/state_machines/corner_ndi_acknowledge_before_waiting_period_rejected_object_exempt
    """
    ingredient = make_ndi_required_ingredient(
        api,
        specialist_headers,
        ingredient_name="Synthetic Peptide K",
        ingredient_class="AMINO_ACID",
        pre_dshea_marketed=False,
        chemical_alteration=True,
        daily_intake_mg=300,
    )
    notification = make_submitted_notification(
        api,
        ingredient["id"],
        specialist_headers,
        submitter_reference="NDI-2026-0301",
    )
    assert notification["notification_status"] == NDI_STATUS_SUBMITTED
    assert_instant(notification["waiting_period_end"], "2026-10-15T00:00:00Z")

    set_clock(api, "2026-10-14T00:00:00Z", specialist_headers)
    premature = api.record_agency_response(
        notification["id"],
        agency_response_payload(RESPONSE_ACKNOWLEDGE),
        specialist_headers,
    )
    validate_error(premature, ERR_WAITING_PERIOD_NOT_ELAPSED, 409)
    still_open = validate_success(
        api.get_ndi_notification(notification["id"], specialist_headers)
    )
    assert still_open["notification_status"] == NDI_STATUS_SUBMITTED
    assert still_open["agency_response_at"] is None

    objected = validate_success(
        api.record_agency_response(
            notification["id"],
            agency_response_payload(
                RESPONSE_OBJECT,
                agency_objection_reason=(
                    "Safety narrative does not support the proposed daily intake."
                ),
            ),
            specialist_headers,
        ),
        200,
    )
    assert objected["notification_status"] == NDI_STATUS_OBJECTED
    assert_instant(objected["agency_response_at"], "2026-10-14T00:00:00Z")

    cascaded = validate_success(api.get_ingredient(ingredient["id"], specialist_headers))
    assert cascaded["eligibility_status"] == ELIGIBILITY_NDI_OBJECTED
    assert cascaded["ndi_notification_required"] is True


def test_a_submitted_notification_cannot_be_filed_a_second_time(api, specialist_headers):
    """The state screen, not the overlap screen, catches a repeated filing.

    PRD §3.2: "A filing attempted on a package that is not in ``DRAFT`` is refused
    with ``ERR_NDI_NOTIFICATION_STATE_INVALID``." PRD §2.7 ranks that resource
    state screen at 9, ahead of the temporal window checks at rank 14, so the
    already-``SUBMITTED`` package reports its state rather than a window overlap.

    Design: Corner/errors/corner_ndi_notification_cannot_be_submitted_twice
    """
    ingredient = make_ndi_required_ingredient(
        api,
        specialist_headers,
        ingredient_name="Synthetic Peptide K",
        ingredient_class="AMINO_ACID",
        pre_dshea_marketed=False,
        chemical_alteration=True,
        daily_intake_mg=300,
    )
    drafted = validate_success(
        api.create_ndi_notification(
            ndi_notification_payload(
                ingredient["id"], submitter_reference="NDI-2026-0401"
            ),
            specialist_headers,
        ),
        201,
    )
    filed = validate_success(
        api.submit_ndi_notification(drafted["id"], specialist_headers), 200
    )
    assert filed["notification_status"] == NDI_STATUS_SUBMITTED
    assert_instant(filed["submitted_at"], "2026-08-01T00:00:00Z")
    assert_instant(filed["waiting_period_end"], "2026-10-15T00:00:00Z")

    repeat = api.submit_ndi_notification(drafted["id"], specialist_headers)
    validate_error(repeat, ERR_NDI_NOTIFICATION_STATE_INVALID, 409)

    reread = validate_success(
        api.get_ndi_notification(drafted["id"], specialist_headers)
    )
    assert reread["notification_status"] == NDI_STATUS_SUBMITTED
    assert_instant(reread["submitted_at"], "2026-08-01T00:00:00Z")
    assert_instant(reread["waiting_period_end"], "2026-10-15T00:00:00Z")

    cascaded = validate_success(api.get_ingredient(ingredient["id"], specialist_headers))
    assert cascaded["eligibility_status"] == ELIGIBILITY_NDI_PENDING


def test_an_excluded_substance_can_never_be_printed_on_a_panel(api, specialist_headers):
    """An ``EXCLUDED_SUBSTANCE`` settles on ``INELIGIBLE`` and is barred from a line.

    PRD §3.1: "If the ``ingredient_class`` is ``EXCLUDED_SUBSTANCE``, the
    determination lands on ``DRAFT_ASSESSMENT → INELIGIBLE``: the article may
    never be printed on a panel, ``ndi_notification_required`` stays false, and no
    notification path is available to rescue it." PRD §3.3 closes the loop:
    "Adding a line whose ingredient has ``eligibility_status`` of ``INELIGIBLE``
    or ``NDI_OBJECTED`` is refused with ``ERR_INGREDIENT_INELIGIBLE_FOR_LABEL``
    (HTTP 409)."

    Design: Corner/errors/corner_excluded_substance_line_rejected_as_ineligible
    """
    ingredient = make_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ephedrine Alkaloids",
        ingredient_class="EXCLUDED_SUBSTANCE",
        pre_dshea_marketed=True,
        chemical_alteration=False,
        daily_intake_mg=20,
        rdi_mg=None,
    )
    settled = validate_success(
        api.run_eligibility_determination(ingredient["id"], specialist_headers), 200
    )
    assert settled["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert settled["ndi_notification_required"] is False

    product = make_product(
        api,
        specialist_headers,
        brand_name="EdgeLabs",
        product_name="Thermo Blend",
        net_quantity_g=45,
        servings_per_container=30,
    )
    refused = api.create_product_ingredient(
        product_ingredient_payload(
            product["id"], ingredient["id"], amount_per_serving_mg=20, panel_position=1
        ),
        specialist_headers,
    )
    validate_error(refused, ERR_INGREDIENT_INELIGIBLE_FOR_LABEL, 409)

    _rows, meta = validate_paginated(
        api.list_product_ingredients(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 0
