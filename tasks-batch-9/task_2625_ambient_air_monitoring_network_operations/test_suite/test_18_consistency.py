"""Read-after-write behaviour of the derived figures.

A write that moves a quarter's hour accounting must also move every figure that
hangs off it, and the very next read has to show all of them already settled.
"""

from test_helpers import (
    PM_HEADERS,
    QA_HEADERS,
    assert_hour_budget_conserved,
    assert_pct,
    get_success_data,
    invalidation_payload,
    open_package,
    twelve_validated_quarters,
    validate_success,
)


def test_every_derived_field_is_current_in_the_same_response(api):
    """One invalidation settles the quarter's counters and the annual rollup at once.

    PRD 3.4: "An accepted invalidation is created with `status` `APPLIED`, with `hours_affected` set to `end_hour_index` less `start_hour_index`, with `data_batch_id` naming the quarter, and with `applied_by_user_id` set to the calling `X-User-ID`."
    PRD 3.4: "Every certification package that had selected this quarter re-runs its rollup in the same request, so a package still in draft sees `included_batch_count`, `eligible_batch_count`, `rollup_completeness_pct` and `certification_ready` all move at once."
    PRD 3.8: "Finally, `certification_ready` is true exactly when `included_batch_count` is at least 1 **and** `eligible_batch_count` equals `included_batch_count`; a single member quarter below its pollutant's completeness threshold makes the whole package unready, as does a package with no members at all."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
    """
    env = twelve_validated_quarters(api)
    package = open_package(env, year=2025)
    assert package["included_batch_count"] == 4
    assert package["eligible_batch_count"] == 4
    assert package["certification_ready"] is True

    quarter = env.read_batch(2025, 1)
    assert quarter["scheduled_hour_count"] == 2160

    written = validate_success(
        api.create_invalidation(
            quarter["id"],
            invalidation_payload(0, 1080, "QC_FAILURE", quarter["version"]),
            QA_HEADERS,
        ),
        201,
    )
    assert written["hours_affected"] == 1080, "the write response must already carry the hour count"
    assert written["status"] == "APPLIED"
    assert written["data_batch_id"] == quarter["id"]
    assert written["applied_by_user_id"] == "qa-1"

    settled_quarter = get_success_data(api.get_data_batch(quarter["id"], QA_HEADERS))
    assert settled_quarter["id"] == quarter["id"]
    assert settled_quarter["invalidated_hour_count"] == 1080
    assert settled_quarter["valid_hour_count"] == 1080
    assert settled_quarter["adjusted_scheduled_hour_count"] == 2160
    assert_pct(settled_quarter["completeness_pct"], 50.0)
    assert settled_quarter["regulatory_use_eligible"] is False
    assert_hour_budget_conserved(settled_quarter)

    settled_package = get_success_data(api.get_package(env.package_id, PM_HEADERS))
    assert settled_package["id"] == package["id"]
    assert settled_package["included_batch_count"] == 4
    assert settled_package["eligible_batch_count"] == 3
    assert_pct(settled_package["rollup_completeness_pct"], 87.7)
    assert settled_package["certification_ready"] is False
