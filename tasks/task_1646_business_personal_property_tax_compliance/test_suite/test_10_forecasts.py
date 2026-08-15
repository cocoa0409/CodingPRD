"""Accrual forecast variants, input-set filtering, supersede semantics, and the
OCC / as-of-date gates on publication."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    classify,
    create_asset_for,
    create_class_rule_for,
    create_client_account,
    create_forecast_payload,
    create_jurisdiction_account,
    create_notice_payload,
    current_client_version,
    file_it,
    generate,
    new_analyst,
    new_manager,
    open_rendition,
    publish_forecast,
    api_client,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["assessor_clerk_headers"]


def _setup_two_jurisdiction_filings():
    """Client with a FILED 2027 rendition in a 0.02-rate FULL_YEAR jurisdiction
    (total 950000) and a FILED 2027 rendition in a 0.03-rate HALF_YEAR
    jurisdiction (total 1500000), each with an ACCEPTED notice equal to the
    rendition total."""
    client = create_client_account(legal_name="ForeCo", contact_email="fore@x.com")
    analyst = new_analyst()
    manager = new_manager()
    j_n1 = create_jurisdiction_account(county_name="North County", tax_rate=0.02)
    j_n2 = create_jurisdiction_account(county_name="South County", tax_rate=0.03)
    create_class_rule_for(j_n1["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[80, 70, 60],
                          percent_good_floor_pct=30, de_minimis_line_cents=0)
    create_class_rule_for(j_n2["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="HALF_YEAR",
                          percent_good_vector=[90, 75, 60, 45],
                          percent_good_floor_pct=20, de_minimis_line_cents=0)
    g1 = create_asset_for(client["id"], j_n1["id"], analyst["headers"],
                          asset_tag="G1", acquisition_cost_cents=1000000,
                          acquisition_date="2025-03-10", in_service_date="2025-04-01")
    g2 = create_asset_for(client["id"], j_n1["id"], analyst["headers"],
                          asset_tag="G2", acquisition_cost_cents=500000,
                          acquisition_date="2026-01-20", in_service_date="2026-02-01")
    g3 = create_asset_for(client["id"], j_n2["id"], analyst["headers"],
                          asset_tag="G3", acquisition_cost_cents=2000000,
                          acquisition_date="2025-02-01", in_service_date="2025-08-01")
    for asset in (g1, g2, g3):
        classify(asset["id"], "TAXABLE", analyst["headers"])

    filed = {}
    for jurisdiction, expected in ((j_n1, 950000), (j_n2, 1500000)):
        rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                                   analyst["headers"])
        rendition = generate(rendition["id"], analyst["headers"])
        assert rendition["total_assessed_value_cents"] == expected, "setup sanity"
        rendition = file_it(rendition["id"], analyst["headers"])
        notice = validate_success(api_client.create_notice(
            rendition["id"],
            create_notice_payload(notice_value_cents=expected),
            CLERK), 201)
        validate_success(api_client.accept_notice(notice["id"],
                                                  analyst["headers"]), 200)
        filed[jurisdiction["id"]] = rendition
    return {"client": client, "analyst": analyst, "manager": manager,
            "j_n1": j_n1, "j_n2": j_n2, "filed": filed}


def test_notice_based_variant_uses_county_values(api):
    """PRD §3.8: "Under the `NOTICE_BASED` variant — the optimistic reading,
    taking county values as noticed — each rendition contributes only when it has
    at least one assessment notice: the latest notice by `created_at` (the last
    one wins) supplies the value, which is its `final_value_cents` when the notice
    is `FINALIZED` and its `notice_value_cents` otherwise, and each contribution
    is that value multiplied by the rendition's jurisdiction `tax_rate`, rounded
    half-up to whole cents before being summed." and "The forecast's
    `component_count` records how many renditions made the input set."

    Design: Difficulty/dual_variant_calc/forecast_variant_notice_based_vs_rendered_conservative
    """
    ctx = _setup_two_jurisdiction_filings()
    forecast = publish_forecast(ctx["client"]["id"], 2027, "NOTICE_BASED",
                                "2027-03-01", ctx["manager"]["headers"])
    # 950000 * 0.02 + 1500000 * 0.03 = 19000 + 45000
    assert forecast["forecasted_liability_cents"] == 64000
    assert forecast["component_count"] == 2
    assert forecast["forecast_status"] == "PUBLISHED"
    assert forecast["needs_regeneration"] is False
    assert forecast["published_by_operator_id"] == ctx["manager"]["id"]


def test_rendered_conservative_variant_uplifts_rendered_values(api):
    """PRD §3.8: "Under the `RENDERED_CONSERVATIVE` variant — the pessimistic
    reading — each rendition contributes its `total_assessed_value_cents`,
    including renditions that have no notice at all; each contribution is the
    rendered value inflated by a ten percent uplift (multiplied by 110 and divided
    by 100), rounded half-up to whole cents, then multiplied by the jurisdiction's
    `tax_rate` and rounded half-up again before summing." and "Publication is a
    superseding write. The new forecast is created in `PUBLISHED` status with
    `needs_regeneration` false and the publisher's identity in
    `published_by_operator_id`; any prior `PUBLISHED` forecast for the same client
    and tax year moves to `SUPERSEDED` (superseded forecasts remain readable
    through the client's forecast sub-collection)"

    Design: Difficulty/dual_variant_calc/forecast_variant_notice_based_vs_rendered_conservative
    """
    ctx = _setup_two_jurisdiction_filings()
    first = publish_forecast(ctx["client"]["id"], 2027, "NOTICE_BASED",
                             "2027-03-01", ctx["manager"]["headers"])
    second = publish_forecast(ctx["client"]["id"], 2027, "RENDERED_CONSERVATIVE",
                              "2027-03-01", ctx["manager"]["headers"])
    # round(950000 * 1.10) * 0.02 + round(1500000 * 1.10) * 0.03
    # = 1045000 * 0.02 + 1650000 * 0.03 = 20900 + 49500
    assert second["forecasted_liability_cents"] == 70400
    assert second["forecasted_liability_cents"] != 64000, (
        "identical data yields different totals under the two variants"
    )

    forecasts = validate_success(api_client.list_client_forecasts(
        ctx["client"]["id"], ctx["manager"]["headers"]), 200)
    by_id = {f["id"]: f for f in forecasts}
    assert by_id[first["id"]]["forecast_status"] == "SUPERSEDED"
    assert by_id[second["id"]]["forecast_status"] == "PUBLISHED"


def test_forecast_input_set_excludes_draft_renditions(api):
    """PRD §3.8: "The forecast input set is the client's renditions in the given
    tax year whose `rendition_status` is `FILED`, `AMENDMENT_OPEN`, or `ACCEPTED`;
    `DRAFT` renditions are excluded entirely." and "each contribution is the
    rendered value inflated by a ten percent uplift (multiplied by 110 and divided
    by 100), rounded half-up to whole cents, then multiplied by the jurisdiction's
    `tax_rate` and rounded half-up again before summing."

    Design: Corner/calculations/forecast_input_set_excludes_draft_renditions
    """
    client = create_client_account(legal_name="FilterCo", contact_email="filt@x.com")
    analyst = new_analyst()
    manager = new_manager()
    j_fa = create_jurisdiction_account(county_name="FA County", tax_rate=0.02)
    j_fb = create_jurisdiction_account(county_name="FB County", tax_rate=0.03)
    create_class_rule_for(j_fa["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[80, 70, 60],
                          percent_good_floor_pct=30, de_minimis_line_cents=0)
    create_class_rule_for(j_fb["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="HALF_YEAR",
                          percent_good_vector=[90, 75, 60, 45],
                          percent_good_floor_pct=20, de_minimis_line_cents=0)
    a_fa = create_asset_for(client["id"], j_fa["id"], analyst["headers"],
                            asset_tag="FA1", acquisition_cost_cents=1000000,
                            acquisition_date="2025-03-10",
                            in_service_date="2025-04-01")
    a_fb = create_asset_for(client["id"], j_fb["id"], analyst["headers"],
                            asset_tag="FB1", acquisition_cost_cents=2000000,
                            acquisition_date="2025-02-01",
                            in_service_date="2025-08-01")
    classify(a_fa["id"], "TAXABLE", analyst["headers"])
    classify(a_fb["id"], "TAXABLE", analyst["headers"])

    r_filed = open_rendition(client["id"], j_fa["id"], 2027, analyst["headers"])
    r_filed = generate(r_filed["id"], analyst["headers"])
    assert r_filed["total_assessed_value_cents"] == 600000, "setup sanity"
    file_it(r_filed["id"], analyst["headers"])

    r_draft = open_rendition(client["id"], j_fb["id"], 2027, analyst["headers"])
    r_draft = generate(r_draft["id"], analyst["headers"])
    assert r_draft["total_assessed_value_cents"] == 1500000, "setup sanity"
    assert r_draft["rendition_status"] == "DRAFT"

    forecast = publish_forecast(client["id"], 2027, "RENDERED_CONSERVATIVE",
                                "2027-03-01", manager["headers"])
    assert forecast["component_count"] == 1, "the DRAFT rendition is excluded"
    assert forecast["forecasted_liability_cents"] == 13200, (
        "round(round(600000 * 1.10) * 0.02); the DRAFT rendition contributes nothing"
    )


def test_forecast_superseded_is_terminal(api):
    """PRD §3.8: "any prior `PUBLISHED` forecast for the same client and tax year
    moves to `SUPERSEDED` (superseded forecasts remain readable through the
    client's forecast sub-collection)" and PRD §3.1: "The account is created with
    its `forecast_sequence` at zero; this counter records how many forecasts have
    ever been published for the client and increments by one on each publication."

    Design: Corner/state_machines/forecast_superseded_is_terminal
    """
    client = create_client_account(legal_name="TermCo", contact_email="term@x.com")
    manager = new_manager()

    first = publish_forecast(client["id"], 2027, "NOTICE_BASED", "2027-03-01",
                             manager["headers"])
    assert first["component_count"] == 0, "no renditions exist yet"
    assert first["forecasted_liability_cents"] == 0
    second = publish_forecast(client["id"], 2027, "RENDERED_CONSERVATIVE",
                              "2027-03-02", manager["headers"])

    forecasts = validate_success(api_client.list_client_forecasts(
        client["id"], manager["headers"]), 200)
    by_id = {f["id"]: f for f in forecasts}
    assert by_id[first["id"]]["forecast_status"] == "SUPERSEDED"
    assert by_id[first["id"]]["forecasted_liability_cents"] == 0
    assert by_id[first["id"]]["component_count"] == 0
    assert by_id[second["id"]]["forecast_status"] == "PUBLISHED"

    account = validate_success(api_client.get_client(client["id"],
                                                     manager["headers"]), 200)
    assert account["forecast_sequence"] == 2


def test_forecast_occ_stale_version_rejected(api):
    """PRD §2.7: "Publishing an accrual forecast requires the request to carry
    `expected_client_version` equal to the client account's current `version`;
    because publishing supersedes the prior published forecast for the same tax
    year, a writer holding a stale client view is rejected with
    `ERR_STALE_VERSION` (HTTP 412) instead of superseding a forecast it never
    saw." and PRD §3.8: "the client account's `version` increments by one and its
    `forecast_sequence` increments by one"

    Design: Corner/cross_cutting_complexity_layers/forecast_occ_stale_version_rejected
    """
    client = create_client_account(legal_name="OccForeCo", contact_email="ocf@x.com")
    manager = new_manager()
    observed_version = client["version"]

    first = validate_success(api_client.publish_forecast(
        client["id"],
        create_forecast_payload(2027, "NOTICE_BASED", "2027-03-01",
                                observed_version),
        manager["headers"]), 201)
    assert first["forecast_status"] == "PUBLISHED"

    account = validate_success(api_client.get_client(client["id"],
                                                     manager["headers"]), 200)
    assert account["version"] == observed_version + 1
    assert account["forecast_sequence"] == 1

    # A different tax year (so no supersede logic is involved), still stale.
    res = api_client.publish_forecast(
        client["id"],
        create_forecast_payload(2028, "NOTICE_BASED", "2028-01-05",
                                observed_version),
        manager["headers"])
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    account = validate_success(api_client.get_client(client["id"],
                                                     manager["headers"]), 200)
    assert account["forecast_sequence"] == 1, "the rejected publish changes nothing"


def test_forecast_as_of_before_tax_year_rejected(api):
    """PRD §3.8: "an `as_of_date` that must fall on or after January 1 of the
    forecast year (an earlier date is rejected with `ERR_FORECAST_INPUT_INVALID`,
    HTTP 422)"

    Design: Corner/validations/forecast_as_of_before_tax_year_rejected
    """
    client = create_client_account(legal_name="AsOfCo", contact_email="asof@x.com")
    manager = new_manager()

    res = api_client.publish_forecast(
        client["id"],
        create_forecast_payload(2027, "NOTICE_BASED", "2026-12-31",
                                client["version"]),
        manager["headers"])
    validate_error(res, ApiErrorId.ERR_FORECAST_INPUT_INVALID, expected_status=422)
