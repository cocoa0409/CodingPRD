"""Two occupancy rules that disagree about their own endpoints.

A notification's waiting period is half-open, so a second filing made at the very
instant the first one closes is adjacent and legal. A panel's effective window is
closed on both ends and buffered besides, so a candidate that merely touches the
incumbent collides — and the only way in is to name the incumbent and retire it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_NDI_WINDOW_OVERLAP, ERR_PANEL_WINDOW_OVERLAP
from test_helpers.assertions import assert_calendar_date
from test_helpers.constants import (
    ELIGIBILITY_NDI_PENDING,
    NDI_STATUS_DRAFT,
    NDI_STATUS_SUBMITTED,
    PANEL_STATUS_DRAFT,
    PANEL_STATUS_SUPERSEDED,
    PANEL_STATUS_VALIDATED,
    WARNING_PEDIATRIC,
)
from test_helpers.factories import label_panel_payload, ndi_notification_payload
from test_helpers.fixtures import (
    make_grandfathered_ingredient,
    make_line,
    make_ndi_required_ingredient,
    make_product,
    make_submitted_notification,
    make_validated_panel,
    product_version,
    set_clock,
)


def _ingredient_with_one_live_window(api, specialist_headers):
    """One filed package occupying 2026-08-01 through 2026-10-15, plus two spare drafts."""
    ingredient = make_ndi_required_ingredient(
        api,
        specialist_headers,
        ingredient_name="Enzymatic Rice Peptide",
        ingredient_class="BOTANICAL",
        daily_intake_mg=400,
    )
    live = make_submitted_notification(
        api,
        ingredient["id"],
        specialist_headers,
        submitter_reference="NDI-2026-0201",
        safety_narrative="Initial dossier for the 400 mg daily intake.",
    )
    second = validate_success(
        api.create_ndi_notification(
            ndi_notification_payload(
                ingredient["id"],
                submitter_reference="NDI-2026-0202",
                safety_narrative="Amended dossier filed one day early.",
            ),
            specialist_headers,
        ),
        201,
    )
    third = validate_success(
        api.create_ndi_notification(
            ndi_notification_payload(
                ingredient["id"],
                submitter_reference="NDI-2026-0203",
                safety_narrative="Amended dossier filed on the closing instant.",
            ),
            specialist_headers,
        ),
        201,
    )
    return ingredient, live, second, third


def test_a_notification_filed_one_day_inside_the_live_window_collides(
    api, specialist_headers
):
    """With one day of the waiting period still to run, the second filing is refused.

    PRD §3.2: "Concretely, a collision exists when the filing instant falls strictly
    before an existing notification's ``waiting_period_end`` and that existing
    notification's ``submitted_at`` falls strictly before the filing instant plus 75
    days." The refused package keeps its opening shape, since PRD §3.2 mints those
    fields only on the successful edge: "``submitted_at`` is set to the logical clock,
    and ``waiting_period_end`` is set to exactly 75 days after ``submitted_at``".

    Design: Difficulty/resource_temporal_overlap/ndi_waiting_window_half_open_adjacency_admits_next_notification
    """
    _ingredient, live, second, _third = _ingredient_with_one_live_window(
        api, specialist_headers
    )
    assert live["notification_status"] == NDI_STATUS_SUBMITTED
    assert live["waiting_period_end"].startswith("2026-10-15T00:00:00")

    set_clock(api, "2026-10-14T00:00:00Z", specialist_headers)
    refused = api.submit_ndi_notification(second["id"], specialist_headers)
    validate_error(refused, ERR_NDI_WINDOW_OVERLAP, 409)

    held = validate_success(
        api.get_ndi_notification(second["id"], specialist_headers), 200
    )
    assert held["notification_status"] == NDI_STATUS_DRAFT
    assert held["submitted_at"] is None
    assert held["waiting_period_end"] is None


def test_a_notification_filed_at_the_exact_closing_instant_is_admitted(
    api, specialist_headers
):
    """The exclusive upper bound makes back-to-back waiting periods legal.

    PRD §3.2: "Because the upper bound is exclusive, a filing made at exactly the
    instant an existing notification's ``waiting_period_end`` falls is *adjacent*, not
    overlapping, and is accepted." The occupancy interval itself is stated the same way:
    "The notification then **occupies** the interval that begins at ``submitted_at``
    inclusive and ends at ``waiting_period_end`` exclusive, on its ingredient."

    Design: Difficulty/resource_temporal_overlap/ndi_waiting_window_half_open_adjacency_admits_next_notification
    """
    ingredient, live, second, third = _ingredient_with_one_live_window(
        api, specialist_headers
    )
    set_clock(api, "2026-10-14T00:00:00Z", specialist_headers)
    validate_error(
        api.submit_ndi_notification(second["id"], specialist_headers),
        ERR_NDI_WINDOW_OVERLAP,
        409,
    )

    set_clock(api, "2026-10-15T00:00:00Z", specialist_headers)
    adjacent = validate_success(
        api.submit_ndi_notification(third["id"], specialist_headers), 200
    )
    assert adjacent["notification_status"] == NDI_STATUS_SUBMITTED
    assert adjacent["submitted_at"].startswith("2026-10-15T00:00:00")
    assert adjacent["waiting_period_end"].startswith("2026-12-29T00:00:00")

    unchanged = validate_success(
        api.get_ingredient(ingredient["id"], specialist_headers), 200
    )
    assert unchanged["eligibility_status"] == ELIGIBILITY_NDI_PENDING

    rows, _meta = validate_paginated(
        api.list_ndi_notifications(
            specialist_headers, {"ingredient_id": ingredient["id"]}
        )
    )
    submitted = [
        row["id"] for row in rows if row["notification_status"] == NDI_STATUS_SUBMITTED
    ]
    assert sorted(submitted) == sorted([live["id"], third["id"]])


def _daily_c_with_a_validated_panel(api, specialist_headers):
    """A VALIDATED panel printed from 2026-09-01 through 2026-12-31, plus the version."""
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
    make_line(
        api,
        product["id"],
        ingredient["id"],
        specialist_headers,
        amount_per_serving_mg=45,
        panel_position=1,
    )
    incumbent = make_validated_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=30,
        effective_from="2026-09-01",
        effective_until="2026-12-31",
        declared_warning_codes=[WARNING_PEDIATRIC],
    )
    return product, incumbent, product_version(api, product["id"], specialist_headers)


def _touching_candidate(api, product_id, version, specialist_headers, **extra):
    """Offer a window whose first printed day is the incumbent's last printed day."""
    return api.create_label_panel(
        label_panel_payload(
            product_id,
            version,
            servings_per_container_declared=30,
            effective_from="2026-12-31",
            effective_until="2027-06-30",
            declared_warning_codes=[WARNING_PEDIATRIC],
            **extra,
        ),
        specialist_headers,
    )


def test_a_start_date_landing_on_the_incumbent_end_date_collides(
    api, specialist_headers
):
    """Both bounds are inclusive, so a shared day is a genuine overlap.

    PRD §3.5: "A panel **occupies** the closed calendar-date interval running from its
    ``effective_from`` through its ``effective_until``, both bounds inclusive, and only
    panels in ``DRAFT``, ``VALIDATED`` or ``LOCKED`` occupy anything — a ``SUPERSEDED``
    panel has vacated its window." The comparison is inclusive on both sides: "because
    both comparisons are inclusive, windows that merely touch do collide."

    Design: Difficulty/resource_temporal_overlap/panel_window_closed_interval_touching_end_date_collides
    """
    product, incumbent, version = _daily_c_with_a_validated_panel(
        api, specialist_headers
    )
    assert incumbent["panel_status"] == PANEL_STATUS_VALIDATED
    assert_calendar_date(incumbent["effective_until"], "2026-12-31")

    refused = _touching_candidate(api, product["id"], version, specialist_headers)
    validate_error(refused, ERR_PANEL_WINDOW_OVERLAP, 409)

    held = validate_success(
        api.get_label_panel(incumbent["id"], specialist_headers), 200
    )
    assert held["panel_status"] == PANEL_STATUS_VALIDATED
    assert product_version(api, product["id"], specialist_headers) == version


def test_naming_the_incumbent_vacates_the_window_for_the_identical_candidate(
    api, specialist_headers
):
    """The same body plus one superseding reference is accepted where the first was not.

    PRD §3.5: "The panel named by ``supersedes_panel_id`` is excluded from the
    comparison set, since it is being retired by this very request and vacates its
    window." The retirement is recorded on the named panel: "the named panel moves
    ``VALIDATED → SUPERSEDED`` or ``LOCKED → SUPERSEDED`` depending on where it stood,
    the product's ``version`` advances".

    Design: Difficulty/resource_temporal_overlap/panel_window_closed_interval_touching_end_date_collides
    """
    product, incumbent, version = _daily_c_with_a_validated_panel(
        api, specialist_headers
    )
    validate_error(
        _touching_candidate(api, product["id"], version, specialist_headers),
        ERR_PANEL_WINDOW_OVERLAP,
        409,
    )

    admitted = validate_success(
        _touching_candidate(
            api,
            product["id"],
            version,
            specialist_headers,
            supersedes_panel_id=incumbent["id"],
        ),
        201,
    )
    assert admitted["panel_status"] == PANEL_STATUS_DRAFT
    assert admitted["supersedes_panel_id"] == incumbent["id"]
    assert_calendar_date(admitted["effective_from"], "2026-12-31")
    assert_calendar_date(admitted["effective_until"], "2027-06-30")

    retired = validate_success(
        api.get_label_panel(incumbent["id"], specialist_headers), 200
    )
    assert retired["panel_status"] == PANEL_STATUS_SUPERSEDED

    rows, meta = validate_paginated(
        api.list_label_panels(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 2
    live = [row["id"] for row in rows if row["panel_status"] != PANEL_STATUS_SUPERSEDED]
    assert live == [admitted["id"]]
