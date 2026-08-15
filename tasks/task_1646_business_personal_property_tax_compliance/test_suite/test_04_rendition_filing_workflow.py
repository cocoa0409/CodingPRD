"""Rendition filing gates, the amendment cycle, and filing authorization."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_rendition,
    create_amendment_payload,
    create_asset_for,
    create_disposal_payload,
    find_rendition_line,
    generate,
    new_manager,
    open_rendition,
    setup_draft_rendition,
    setup_filed_rendition,
    setup_classified_asset,
    validate_error,
    validate_success,
)


def test_file_blocked_by_unclassified_asset(api):
    """PRD §3.4: "Three gates guard it, in the order fixed by §2.9: every in-scope
    `ACTIVE` asset must have reached `CLASSIFIED` or `OVERRIDDEN` (otherwise
    `ERR_UNCLASSIFIED_ASSETS`, HTTP 422); at least one line must be included
    (otherwise `ERR_EMPTY_RENDITION`, HTTP 422); and lines must have been
    generated at least once."

    Design: Difficulty/cross_entity_state_dependency/file_blocked_by_unclassified_asset
    """
    ctx = setup_classified_asset(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "U1", "acquisition_cost_cents": 100000},
    )
    # Second in-scope asset deliberately left UNCLASSIFIED.
    create_asset_for(ctx["client"]["id"], ctx["jurisdiction"]["id"],
                     ctx["analyst"]["headers"],
                     asset_tag="U2", acquisition_cost_cents=100000)
    rendition = open_rendition(ctx["client"]["id"], ctx["jurisdiction"]["id"], 2027,
                               ctx["analyst"]["headers"])
    generate(rendition["id"], ctx["analyst"]["headers"])

    res = api.file_rendition(rendition["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_UNCLASSIFIED_ASSETS, expected_status=422)

    after = validate_success(api.get_rendition(rendition["id"],
                                               ctx["analyst"]["headers"]), 200)
    assert after["rendition_status"] == "DRAFT", "rejected filing must leave DRAFT"


def test_file_gate_ignores_assets_acquired_after_lien_date(api):
    """PRD §3.4: "The in-scope asset set is every asset of the rendition's client
    and jurisdiction, in any lifecycle status, whose `acquisition_date` is strictly
    before January 1 of the tax year: the asset must have been owned on the lien
    date." and "every in-scope `ACTIVE` asset must have reached `CLASSIFIED` or
    `OVERRIDDEN` (otherwise `ERR_UNCLASSIFIED_ASSETS`, HTTP 422)"

    Design: Difficulty/cross_entity_state_dependency/file_blocked_by_unclassified_asset
    """
    ctx = setup_classified_asset(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "U1", "acquisition_cost_cents": 100000},
    )
    # Acquired after the 2027 lien date (2027-01-01): out of scope, so its
    # UNCLASSIFIED state must not block filing.
    out_of_scope = create_asset_for(
        ctx["client"]["id"], ctx["jurisdiction"]["id"], ctx["analyst"]["headers"],
        asset_tag="U2", acquisition_cost_cents=100000,
        acquisition_date="2027-02-01", in_service_date="2027-02-05")
    rendition = open_rendition(ctx["client"]["id"], ctx["jurisdiction"]["id"], 2027,
                               ctx["analyst"]["headers"])
    generate(rendition["id"], ctx["analyst"]["headers"])

    filed = validate_success(api.file_rendition(rendition["id"],
                                                ctx["analyst"]["headers"]), 200)
    assert_rendition(filed)
    assert filed["rendition_status"] == "FILED"
    assert filed["filed_by_operator_id"] == ctx["analyst"]["id"]
    assert all(line["asset_id"] != out_of_scope["id"] for line in filed["lines"])


def test_amendment_open_moves_filed_to_amendment_open(api):
    """PRD §3.4: "After filing, only a `SeniorManager` may open an amendment,
    passing an `action` of `OPEN`, which moves the rendition from `FILED` to
    `AMENDMENT_OPEN`, records the opener in `amendment_opened_by_operator_id`,
    and appends `AMENDMENT_OPENED`; per §2.8 the opener must not be the operator
    recorded in `filed_by_operator_id`."

    Design: Difficulty/non_linear_state_machine/rendition_amendment_cycle
    """
    ctx = setup_filed_rendition(
        rule_overrides={"percent_good_vector": [80, 70, 60]},
        asset_overrides={"asset_tag": "C1", "acquisition_cost_cents": 1000000,
                         "acquisition_date": "2025-03-10",
                         "in_service_date": "2025-04-01"},
    )
    assert ctx["rendition"]["rendition_status"] == "FILED"

    opened = validate_success(api.amend_rendition(
        ctx["rendition"]["id"], create_amendment_payload("OPEN"),
        ctx["manager"]["headers"]), 200)
    assert opened["rendition_status"] == "AMENDMENT_OPEN"
    assert opened["amendment_opened_by_operator_id"] == ctx["manager"]["id"]

    # The workbench state permits line regeneration while the amendment is open.
    regenerated = validate_success(api.generate_lines(
        ctx["rendition"]["id"], ctx["analyst"]["headers"]), 200)
    assert regenerated["rendition_status"] == "AMENDMENT_OPEN"


def test_amendment_refile_closes_the_cycle(api):
    """PRD §3.4: "Re-filing an open amendment moves the rendition back to `FILED`,
    recomputes every lateness field from the `deadline_date` against the current
    clock date (lateness is recomputed at each filing, not carried forward),
    updates `filed_at` and `filed_by_operator_id`, clears
    `amendment_opened_by_operator_id`, flags published forecasts for the client
    and tax year, and appends another `RENDITION_FILED`."

    Design: Difficulty/non_linear_state_machine/rendition_amendment_cycle
    """
    ctx = setup_filed_rendition(
        rule_overrides={"percent_good_vector": [80, 70, 60]},
        asset_overrides={"asset_tag": "C1", "acquisition_cost_cents": 1000000,
                         "acquisition_date": "2025-03-10",
                         "in_service_date": "2025-04-01"},
    )
    validate_success(api.amend_rendition(ctx["rendition"]["id"],
                                         create_amendment_payload("OPEN"),
                                         ctx["manager"]["headers"]), 200)
    generate(ctx["rendition"]["id"], ctx["analyst"]["headers"])

    refiled = validate_success(api.file_rendition(ctx["rendition"]["id"],
                                                  ctx["analyst"]["headers"]), 200)
    assert refiled["rendition_status"] == "FILED", "the cycle returns to FILED"
    assert refiled.get("amendment_opened_by_operator_id") is None
    assert refiled["filed_by_operator_id"] == ctx["analyst"]["id"]
    assert refiled["filed_at"] is not None
    assert refiled["total_assessed_value_cents"] == 600000


def test_rendition_refile_without_amendment_rejected(api):
    """PRD §3.4: "Filing a rendition that is already `FILED` without an open
    amendment is rejected with `ERR_RENDITION_ALREADY_FILED` (HTTP 409)."

    Design: Corner/state_machines/rendition_refile_without_amendment_rejected
    """
    ctx = setup_filed_rendition(asset_overrides={"asset_tag": "RF1"})
    res = api.file_rendition(ctx["rendition"]["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_RENDITION_ALREADY_FILED, expected_status=409)

    after = validate_success(api.get_rendition(ctx["rendition"]["id"],
                                               ctx["analyst"]["headers"]), 200)
    assert after["rendition_status"] == "FILED"


def test_generate_lines_on_filed_rendition_rejected(api):
    """PRD §3.4: "Line generation — permitted only while the rendition is `DRAFT`
    or `AMENDMENT_OPEN`, otherwise `ERR_AMENDMENT_STATE_MISMATCH` — rebuilds the
    `lines` array from scratch."

    Design: Corner/state_machines/generate_lines_on_filed_rendition_rejected
    """
    ctx = setup_filed_rendition(asset_overrides={"asset_tag": "G1"})
    res = api.generate_lines(ctx["rendition"]["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_AMENDMENT_STATE_MISMATCH, expected_status=409)


def test_empty_rendition_file_rejected(api):
    """PRD §3.4: "Three gates guard it, in the order fixed by §2.9: every in-scope
    `ACTIVE` asset must have reached `CLASSIFIED` or `OVERRIDDEN` (otherwise
    `ERR_UNCLASSIFIED_ASSETS`, HTTP 422); at least one line must be included
    (otherwise `ERR_EMPTY_RENDITION`, HTTP 422); and lines must have been
    generated at least once." and PRD §3.3: "every rendition line referencing the
    asset on a rendition in `DRAFT` or `AMENDMENT_OPEN` whose tax year's lien date
    — January 1 of that tax year — falls strictly after the disposal date is
    excluded: `included` becomes false and `exclusion_reason` becomes `DISPOSED`."

    Design: Corner/validations/empty_rendition_file_rejected
    """
    # The only asset is disposed before the 2027 lien date, so its line is
    # excluded and no included line remains. A DISPOSED asset is not ACTIVE, so
    # the classification gate does not apply to it.
    ctx = setup_classified_asset(
        rule_overrides={"percent_good_vector": [80, 70, 60]},
        asset_overrides={"asset_tag": "EM1", "acquisition_cost_cents": 1000000,
                         "acquisition_date": "2025-03-10",
                         "in_service_date": "2025-04-01"},
        classify_asset=False,
    )
    validate_success(api.create_disposal(
        ctx["asset"]["id"],
        create_disposal_payload(disposal_date="2026-06-01", disposal_proceeds_cents=0),
        ctx["analyst"]["headers"]), 201)
    rendition = open_rendition(ctx["client"]["id"], ctx["jurisdiction"]["id"], 2027,
                               ctx["analyst"]["headers"])
    generated = generate(rendition["id"], ctx["analyst"]["headers"])
    line = find_rendition_line(generated, ctx["asset"]["id"])
    assert line["included"] is False and line["exclusion_reason"] == "DISPOSED"

    res = api.file_rendition(rendition["id"], ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_EMPTY_RENDITION, expected_status=422)

    after = validate_success(api.get_rendition(rendition["id"],
                                               ctx["analyst"]["headers"]), 200)
    assert after["rendition_status"] == "DRAFT"


def test_amendment_open_by_filing_operator_rejected(api):
    """PRD §2.8: "The `SeniorManager` who opens or withdraws a rendition amendment
    must not be the operator who most recently filed that rendition — the acting
    `X-User-ID` is compared against the rendition's `filed_by_operator_id`." and
    "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    and "Senior managers are permitted to file renditions and to import bills,
    but doing so bars them from the corresponding check on their own work."

    Design: Corner/state_machines/amendment_open_by_filing_operator_rejected
    """
    # The filing operator here is a senior manager (they may file renditions).
    ctx = setup_filed_rendition(filer="manager", asset_overrides={"asset_tag": "SD1"})
    assert ctx["filed_by"] == ctx["manager"]["id"]
    second_manager = new_manager("Manny Two")

    res = api.amend_rendition(ctx["rendition"]["id"], create_amendment_payload("OPEN"),
                              ctx["manager"]["headers"])
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    opened = validate_success(api.amend_rendition(
        ctx["rendition"]["id"], create_amendment_payload("OPEN"),
        second_manager["headers"]), 200)
    assert opened["rendition_status"] == "AMENDMENT_OPEN"
    assert opened["amendment_opened_by_operator_id"] == second_manager["id"]


def test_clerk_cannot_file_rendition_forbidden(api, assessor_clerk_headers):
    """PRD §2.1: "Authorization is then enforced per endpoint: a role outside the
    endpoint's permitted set, or a `Client` whose `X-User-ID` does not own the
    addressed resource through the foreign-key chain described below, is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)." and PRD §4: POST
    /bpp/renditions/{rendition_id}/file is authorized for "TaxAnalyst,
    SeniorManager".

    Design: Corner/rbac/clerk_cannot_file_rendition_forbidden
    """
    ctx = setup_draft_rendition(asset_overrides={"asset_tag": "CK1"})
    res = api.file_rendition(ctx["rendition"]["id"], assessor_clerk_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    after = validate_success(api.get_rendition(ctx["rendition"]["id"],
                                               ctx["analyst"]["headers"]), 200)
    assert after["rendition_status"] == "DRAFT"
