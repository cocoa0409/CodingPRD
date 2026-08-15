"""Disposal recording, the four-link disposal cascade, reversal, and
filing-driven reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    audit_event_types,
    classify,
    create_asset_for,
    create_class_rule_for,
    create_client_account,
    create_disposal_payload,
    create_jurisdiction_account,
    file_it,
    find_rendition_line,
    generate,
    list_audit_events,
    new_analyst,
    new_manager,
    open_rendition,
    publish_forecast,
    setup_classified_asset,
    setup_draft_rendition,
    validate_success,
    validate_error,
)


def _setup_two_asset_draft(legal_name, tag1, tag2, with_forecast=False):
    """Client with two classified assets (1000000 acq 2025-03-10 -> 600000;
    500000 acq 2026-01-20 -> 350000) and a generated DRAFT 2027 rendition
    totaling 950000. Optionally publishes a RENDERED_CONSERVATIVE forecast."""
    client = create_client_account(legal_name=legal_name,
                                   contact_email=f"{tag1.lower()}@x.com")
    analyst = new_analyst()
    manager = new_manager()
    jurisdiction = create_jurisdiction_account(county_name="Disp County")
    create_class_rule_for(jurisdiction["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[80, 70, 60],
                          percent_good_floor_pct=30, de_minimis_line_cents=0)
    a1 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag=tag1, acquisition_cost_cents=1000000,
                          acquisition_date="2025-03-10", in_service_date="2025-04-01")
    a2 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag=tag2, acquisition_cost_cents=500000,
                          acquisition_date="2026-01-20", in_service_date="2026-02-01")
    classify(a1["id"], "TAXABLE", analyst["headers"])
    classify(a2["id"], "TAXABLE", analyst["headers"])
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])
    rendition = generate(rendition["id"], analyst["headers"])
    assert rendition["total_assessed_value_cents"] == 950000, "setup sanity"
    ctx = {"client": client, "analyst": analyst, "manager": manager,
           "jurisdiction": jurisdiction, "a1": a1, "a2": a2, "rendition": rendition}
    if with_forecast:
        ctx["forecast"] = publish_forecast(client["id"], 2027,
                                           "RENDERED_CONSERVATIVE", "2027-03-01",
                                           manager["headers"])
    return ctx


def test_disposal_cascade_excludes_line_and_recomputes_total(api):
    """PRD §3.3: "Recording a disposal is the first link of a four-link cascade.
    The asset's `lifecycle_status` moves from `ACTIVE` to `DISPOSED`, its
    `disposed_date` and `disposal_proceeds_cents` are set, and a disposal record
    is created in `RECORDED` status. Second, every rendition line referencing the
    asset on a rendition in `DRAFT` or `AMENDMENT_OPEN` whose tax year's lien date
    — January 1 of that tax year — falls strictly after the disposal date is
    excluded: `included` becomes false and `exclusion_reason` becomes `DISPOSED`.
    Lines whose lien date falls on or before the disposal date are left unchanged.
    Third, each rendition touched by that exclusion recomputes its
    `total_assessed_value_cents` per the aggregation rule and bumps its `version`."

    Design: Difficulty/transitive_cascade/disposal_cascade_asset_line_rendition_forecast
    """
    ctx = _setup_two_asset_draft("DispCo", "H1", "H2", with_forecast=True)
    disposal = validate_success(api.create_disposal(
        ctx["a1"]["id"],
        create_disposal_payload(disposal_date="2026-06-01",
                                disposal_proceeds_cents=10000),
        ctx["analyst"]["headers"]), 201)
    assert disposal["disposal_status"] == "RECORDED"

    asset = validate_success(api.get_asset(ctx["a1"]["id"],
                                           ctx["analyst"]["headers"]), 200)
    assert asset["lifecycle_status"] == "DISPOSED"

    rendition = validate_success(api.get_rendition(ctx["rendition"]["id"],
                                                   ctx["analyst"]["headers"]), 200)
    line = find_rendition_line(rendition, ctx["a1"]["id"])
    assert line["included"] is False
    assert line["exclusion_reason"] == "DISPOSED"
    assert rendition["total_assessed_value_cents"] == 350000, "950000 - 600000"


def test_disposal_cascade_flags_published_forecast(api):
    """PRD §3.3: "Fourth, every published accrual forecast for the same client
    whose tax year's lien date falls strictly after the disposal date is flagged
    with `needs_regeneration` true and a version bump, and each such flagging
    appends a `FORECAST_STALENESS_FLAGGED` audit event. The cascade closes by
    appending `DISPOSAL_RECORDED` to the client's audit trail."

    Design: Difficulty/transitive_cascade/disposal_cascade_asset_line_rendition_forecast
    """
    ctx = _setup_two_asset_draft("DispCo", "H1", "H2", with_forecast=True)
    forecast = ctx["forecast"]
    assert forecast["needs_regeneration"] is False

    validate_success(api.create_disposal(
        ctx["a1"]["id"],
        create_disposal_payload(disposal_date="2026-06-01",
                                disposal_proceeds_cents=10000),
        ctx["analyst"]["headers"]), 201)

    forecasts = validate_success(api.list_client_forecasts(
        ctx["client"]["id"], ctx["manager"]["headers"]), 200)
    flagged = [f for f in forecasts if f["id"] == forecast["id"]][0]
    assert flagged["needs_regeneration"] is True
    assert flagged["version"] > forecast["version"], "flagging bumps the version"

    events = list_audit_events(ctx["client"]["id"])
    assert "DISPOSAL_RECORDED" in audit_event_types(events)
    assert "FORECAST_STALENESS_FLAGGED" in audit_event_types(events)


def test_dispose_then_reverse_conserves_rendition_total(api):
    """PRD §3.3: "reversing restores the asset from `DISPOSED` to `ACTIVE`, clears
    `disposed_date` and `disposal_proceeds_cents`, moves the addressed record to
    `REVERSED`, and reinstates every line that had been excluded with
    `exclusion_reason` `DISPOSED` for this asset on a rendition still in `DRAFT`
    or `AMENDMENT_OPEN` — each restored line returns to `included` true with a
    null `exclusion_reason` and has its assessed value recomputed under the
    depreciation rule, after which each touched rendition recomputes its total
    and bumps its `version`."

    Design: Difficulty/compensating_invariant/dispose_reverse_conserves_rendition_total
    """
    ctx = _setup_two_asset_draft("InvCo", "H1", "H2")
    disposal = validate_success(api.create_disposal(
        ctx["a1"]["id"],
        create_disposal_payload(disposal_date="2026-06-01",
                                disposal_proceeds_cents=10000),
        ctx["analyst"]["headers"]), 201)
    mid = validate_success(api.get_rendition(ctx["rendition"]["id"],
                                             ctx["analyst"]["headers"]), 200)
    assert mid["total_assessed_value_cents"] == 350000

    validate_success(api.reverse_disposal(disposal["id"], ctx["analyst"]["headers"]), 200)

    restored = validate_success(api.get_rendition(ctx["rendition"]["id"],
                                                  ctx["analyst"]["headers"]), 200)
    assert restored["total_assessed_value_cents"] == 950000, (
        "disposal paired with its reversal leaves the assessed total conserved"
    )
    line = find_rendition_line(restored, ctx["a1"]["id"])
    assert line["included"] is True
    assert line.get("exclusion_reason") is None
    assert line["assessed_value_cents"] == 600000


def test_reverse_restores_asset_and_marks_record_reversed(api):
    """PRD §3.3: "reversing restores the asset from `DISPOSED` to `ACTIVE`, clears
    `disposed_date` and `disposal_proceeds_cents`, moves the addressed record to
    `REVERSED`" and "A `DISPOSAL_REVERSED` event is appended."

    Design: Difficulty/compensating_invariant/dispose_reverse_conserves_rendition_total
    """
    ctx = _setup_two_asset_draft("InvCo", "H1", "H2")
    disposal = validate_success(api.create_disposal(
        ctx["a1"]["id"],
        create_disposal_payload(disposal_date="2026-06-01",
                                disposal_proceeds_cents=10000),
        ctx["analyst"]["headers"]), 201)

    reversed_record = validate_success(api.reverse_disposal(
        disposal["id"], ctx["analyst"]["headers"]), 200)
    assert reversed_record["disposal_status"] == "REVERSED"

    asset = validate_success(api.get_asset(ctx["a1"]["id"],
                                           ctx["analyst"]["headers"]), 200)
    assert asset["lifecycle_status"] == "ACTIVE"
    assert asset.get("disposed_date") is None
    assert asset.get("disposal_proceeds_cents") is None

    events = list_audit_events(ctx["client"]["id"])
    assert "DISPOSAL_REVERSED" in audit_event_types(events)


def test_disposal_reverse_twice_rejected(api):
    """PRD §3.3: "Only a `RECORDED` disposal may be reversed; attempting to
    reverse a `RECONCILED` or already-`REVERSED` record is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/disposal_reverse_twice_rejected
    """
    ctx = setup_classified_asset(asset_overrides={"asset_tag": "RV1"})
    disposal = validate_success(api.create_disposal(
        ctx["asset"]["id"],
        create_disposal_payload(disposal_date="2026-07-15",
                                disposal_proceeds_cents=0),
        ctx["analyst"]["headers"]), 201)
    validate_success(api.reverse_disposal(disposal["id"], ctx["analyst"]["headers"]), 200)

    res = api.reverse_disposal(disposal["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    asset = validate_success(api.get_asset(ctx["asset"]["id"],
                                           ctx["analyst"]["headers"]), 200)
    assert asset["lifecycle_status"] == "ACTIVE"


def test_disposal_reconciled_when_excluding_rendition_files(api):
    """PRD §3.3: "When a rendition of the same client and the disposed asset's
    jurisdiction, with a lien date strictly after the disposal date, is filed with
    this asset's line excluded for `DISPOSED`, the disposal record moves from
    `RECORDED` to `RECONCILED` and a `DISPOSAL_RECONCILED` event is appended — the
    filing has formally removed the asset from the tax roll, closing the loop
    opened at recording."

    Design: Corner/state_machines/disposal_reconciled_when_excluding_rendition_files
    """
    client = create_client_account(legal_name="ReconCo", contact_email="recon@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Recon County")
    create_class_rule_for(jurisdiction["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[80, 70, 60],
                          percent_good_floor_pct=30, de_minimis_line_cents=0)
    a1 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag="R1", acquisition_cost_cents=1000000,
                          acquisition_date="2025-03-10", in_service_date="2025-04-01")
    a2 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag="R2", acquisition_cost_cents=500000,
                          acquisition_date="2026-01-20", in_service_date="2026-02-01")
    classify(a2["id"], "TAXABLE", analyst["headers"])
    disposal = validate_success(api.create_disposal(
        a1["id"],
        create_disposal_payload(disposal_date="2026-06-01",
                                disposal_proceeds_cents=5000),
        analyst["headers"]), 201)
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])
    generated = generate(rendition["id"], analyst["headers"])
    line = find_rendition_line(generated, a1["id"])
    assert line["included"] is False and line["exclusion_reason"] == "DISPOSED"

    filed = file_it(rendition["id"], analyst["headers"])
    assert filed["rendition_status"] == "FILED"
    assert filed["total_assessed_value_cents"] == 350000

    disposals = validate_success(api.list_disposals(a1["id"], analyst["headers"]), 200)
    record = [d for d in disposals if d["id"] == disposal["id"]][0]
    assert record["disposal_status"] == "RECONCILED"

    events = list_audit_events(client["id"])
    assert "DISPOSAL_RECONCILED" in audit_event_types(events)


def test_disposal_before_acquisition_rejected(api):
    """PRD §3.3: "The disposal date must fall on or after the date part of the
    asset's `acquisition_date` and on or before the current clock date; a date
    outside that window is rejected with `ERR_INVALID_DISPOSAL_DATE` (HTTP 422)."

    Design: Corner/validations/disposal_before_acquisition_rejected
    """
    ctx = setup_classified_asset(asset_overrides={"asset_tag": "DT1"},
                                 classify_asset=False)
    res = api.create_disposal(
        ctx["asset"]["id"],
        create_disposal_payload(disposal_date="2025-12-01",
                                disposal_proceeds_cents=0),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_DISPOSAL_DATE, expected_status=422)

    asset = validate_success(api.get_asset(ctx["asset"]["id"],
                                           ctx["analyst"]["headers"]), 200)
    assert asset["lifecycle_status"] == "ACTIVE"


def test_disposal_cascade_bumps_rendition_version(api):
    """PRD §3.3: "Third, each rendition touched by that exclusion recomputes its
    `total_assessed_value_cents` per the aggregation rule and bumps its
    `version`." and PRD §2.4: "`version`, an integer the server increments on
    every mutation of the resource, including mutations driven by system cascades
    such as rendition total recomputation or forecast staleness flagging."

    Design: Corner/cross_cutting_complexity_layers/disposal_cascade_bumps_rendition_version
    """
    ctx = setup_draft_rendition(
        rule_overrides={"percent_good_vector": [80, 70, 60]},
        asset_overrides={"asset_tag": "VR1", "acquisition_cost_cents": 1000000,
                         "acquisition_date": "2025-03-10",
                         "in_service_date": "2025-04-01"},
    )
    before = validate_success(api.get_rendition(ctx["rendition"]["id"],
                                                ctx["analyst"]["headers"]), 200)
    assert before["total_assessed_value_cents"] == 600000

    validate_success(api.create_disposal(
        ctx["asset"]["id"],
        create_disposal_payload(disposal_date="2026-06-01",
                                disposal_proceeds_cents=0),
        ctx["analyst"]["headers"]), 201)

    after = validate_success(api.get_rendition(ctx["rendition"]["id"],
                                               ctx["analyst"]["headers"]), 200)
    assert after["total_assessed_value_cents"] == 0, "single line excluded DISPOSED"
    assert after["version"] == before["version"] + 1, (
        "the disposal cascade mutates the rendition exactly once"
    )
    assert isinstance(after.get("updated_at"), str), "updated_at is refreshed"
