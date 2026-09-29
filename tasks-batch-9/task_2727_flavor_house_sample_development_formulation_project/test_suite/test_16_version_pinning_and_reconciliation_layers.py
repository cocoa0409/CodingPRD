"""Optimistic-concurrency pins, per-write version counters and derived-field reconciliation."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    brief_clarification_payload,
    brief_decision_payload,
    create_commercialization_forecast_payload,
    create_formula_revision_payload,
)
from test_helpers.fixtures import (
    add_material_line,
    approve_formula,
    build_approved_formula,
    components_of,
    cost_formula,
    create_accepted_brief,
    create_brief,
    create_formula,
    create_material,
    create_revision,
    delete_component,
    list_data,
    publish_forecast,
    read_batch,
    read_brief,
    read_component,
    read_formula,
    read_forecast,
    read_material,
    reprice_material,
    request_scale_up_batch,
    set_batch_tolerance,
    submit_formula,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER,
    DIRECTOR_APPROVER,
    FLAVORIST,
    TECHNICAL_DIRECTOR,
)


def test_stale_expected_formula_version_blocks_the_revision_then_the_current_one_supersedes(api):
    """The costing-era version is refused with 412; the approval-era version mints iteration 2.

    Section 2.7 requires `expected_formula_version` on a revision and says "Its
    value must equal the target formula's current `version`.  If any other writer
    has advanced that formula's `version` since the client last read it — an
    approval, a rework cascade, a reprice — the revision request is rejected with
    `ERR_STALE_FORMULA_VERSION` (HTTP 412).  The rejection is not a state-machine
    rejection ... nothing about the formula's own state blocks the second
    attempt."  Section 3.5 then supersedes the predecessor, sets
    `superseded_by_formula_id`, increments its `version` "by 1", and creates the
    successor "in `DRAFT` with `parent_formula_id` pointing back at the
    predecessor and `iteration_no` derived as one more than the number of
    formulas already recorded against the same brief"; the carried lines arrive
    uncosted.

    Design: Corner/complexity_layers/stale_expected_formula_version_blocks_the_revision_then_the_current_one_supersedes
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    assert formula["iteration_no"] == 1
    add_material_line(api, formula["id"], material["id"], 100.0)

    costed = cost_formula(api, formula["id"])
    submit_formula(api, formula["id"])
    approved = approve_formula(api, formula["id"])
    assert costed["version"] < approved["version"]

    stale = api.create_formula_revision(
        formula["id"],
        create_formula_revision_payload("Vanilla Cream F1 rev A",
                                        costed["version"],
                                        carry_components=True),
        FLAVORIST)
    validate_error(stale, ApiErrorId.ERR_STALE_FORMULA_VERSION.value, 412)

    intact = read_formula(api, formula["id"])
    assert intact["status"] == "APPROVED"
    assert intact["version"] == approved["version"]
    assert intact["superseded_by_formula_id"] is None
    assert list_data(api, api.list_formulas, FLAVORIST)["meta"]["total_count"] == 1

    successor = create_revision(api, formula["id"], approved["version"],
                                name="Vanilla Cream F1 rev A",
                                carry_components=True)
    assert successor["status"] == "DRAFT"
    assert successor["parent_formula_id"] == formula["id"]
    assert successor["iteration_no"] == 2

    carried = read_formula(api, successor["id"])
    assert carried["component_count"] == 1
    assert float(carried["total_weight_pct"]) == 100.0
    assert carried["bench_cost_per_kg_cents"] is None

    predecessor = read_formula(api, formula["id"])
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by_formula_id"] == successor["id"]
    assert predecessor["version"] == approved["version"] + 1


def test_stale_expected_brief_version_blocks_the_forecast_then_the_current_one_creates_it(api):
    """The post-submit version is refused with 412; the post-decision version publishes.

    Section 2.7 requires `expected_brief_version` "likewise non-optional, and
    likewise required to equal the target brief's current `version` ... if the
    brief's `version` has advanced since the client observed it the create is
    rejected with `ERR_STALE_BRIEF_VERSION` (HTTP 412).  On success the validated
    value is retained on the new forecast as `pinned_brief_version`."  The gross
    figure 500 x 10000 is 5000000, and with no approved formula the risk-weighted
    value is 5000000 x 0.45 x 0.55 = 1237500.

    Design: Corner/complexity_layers/stale_expected_brief_version_blocks_the_forecast_then_the_current_one_creates_it
    """
    created = create_brief(api, brief_code="BRF-0001")
    assert created["version"] == 1

    submitted = get_success_data(
        api.submit_customer_brief(created["id"], ACCOUNT_MANAGER), 200)
    assert submitted["version"] == 2

    accepted = get_success_data(
        api.decide_customer_brief(created["id"],
                                  brief_decision_payload(
                                      "ACCEPTED",
                                      decision_note="brief is workable"),
                                  TECHNICAL_DIRECTOR),
        200)
    assert accepted["version"] == 3

    stale = api.create_commercialization_forecast(
        create_commercialization_forecast_payload(created["id"], 500, 10000,
                                                  submitted["version"]),
        ACCOUNT_MANAGER)
    validate_error(stale, ApiErrorId.ERR_STALE_BRIEF_VERSION.value, 412)
    assert list_data(api, api.list_commercialization_forecasts,
                     ACCOUNT_MANAGER)["meta"]["total_count"] == 0

    forecast = publish_forecast(api, created["id"], accepted["version"],
                               annual_volume_kg=500,
                               unit_price_cents_per_kg=10000)
    assert forecast["status"] == "ACTIVE"
    assert forecast["weighted_annual_value_cents"] == 1237500
    assert forecast["pinned_brief_version"] == 3

    stored = read_forecast(api, forecast["id"])
    assert stored["annual_volume_kg"] == 500
    assert stored["unit_price_cents_per_kg"] == 10000
    assert float(stored["stage_probability"]) == 0.45
    assert float(stored["technical_factor"]) == 0.55
    assert read_brief(api, created["id"])["version"] == 3


def test_brief_version_increments_once_per_write_and_child_creates_leave_it_alone(api):
    """Five brief writes give versions 1 to 5; a formula and a forecast both start at 1.

    Section 2.4 says `version` "starts at 1 when the resource is created and
    increments by 1 on every mutation of that resource".  Section 3.1 confirms each brief write is one such operation —
    submission "increments the brief's `version` by 1", a clarification request
    "increments `clarification_round_count` by 1, stores the supplied text into
    `clarification_note`, and increments the brief's `version`", and an
    `ACCEPTED` decision "records the note and increments `version`" — while
    creating a child formula or forecast is a write on the child, whose own
    `version` starts at 1.

    Design: Corner/complexity_layers/brief_version_increments_once_per_write_and_child_creates_leave_it_alone
    """
    create_material(api, material_code="GUM-BASE")

    brief = create_brief(api, brief_code="BRF-0001")
    assert brief["version"] == 1

    first_submit = get_success_data(
        api.submit_customer_brief(brief["id"], ACCOUNT_MANAGER), 200)
    assert first_submit["version"] == 2

    clarified = get_success_data(
        api.request_brief_clarification(
            brief["id"],
            brief_clarification_payload("confirm the dairy matrix pH"),
            TECHNICAL_DIRECTOR),
        200)
    assert clarified["version"] == 3
    assert clarified["clarification_round_count"] == 1

    second_submit = get_success_data(
        api.submit_customer_brief(brief["id"], ACCOUNT_MANAGER), 200)
    assert second_submit["version"] == 4
    assert second_submit["status"] == "SUBMITTED"

    accepted = get_success_data(
        api.decide_customer_brief(brief["id"], brief_decision_payload("ACCEPTED"),
                                  TECHNICAL_DIRECTOR),
        200)
    assert accepted["version"] == 5
    assert accepted["status"] == "ACCEPTED"

    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    assert formula["version"] == 1

    forecast = publish_forecast(api, brief["id"], 5, annual_volume_kg=500,
                               unit_price_cents_per_kg=10000)
    assert forecast["version"] == 1

    settled = read_brief(api, brief["id"])
    assert settled["status"] == "ACCEPTED"
    assert settled["version"] == 5


def test_repricing_the_material_stales_the_pin_and_only_a_fresh_batch_can_be_toleranced(api):
    """The pre-reprice batch is refused with 409; a batch raised after it costs 445000.

    Section 3.9 says of the tolerance step that "the batch's
    `pinned_formula_version` must still equal the formula's current `version`,
    else the step is refused with `ERR_PINNED_FORMULA_STALE` (HTTP 409) ... any
    reprice, approval or rework cascade that bumped the formula's `version` after
    the batch was requested invalidates the pin, and the batch must be
    re-requested rather than silently costed against a formula nobody quoted".
    Section 3.2 supplies the bump: an `APPROVED` formula "stays `APPROVED`, but
    its `cost_stale` flag is set to true ... and its `version` is incremented".
    At 2500 cents per kilogram the fresh batch costs 375000 in material, 12.0 %
    of that is 45000, and the flat 25000 QA charge brings the total to 445000
    with 2967 per kilogram.

    Design: Corner/complexity_layers/repricing_the_material_stales_the_pin_and_only_a_fresh_batch_can_be_toleranced
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    approved = build_approved_formula(api, brief["id"], material["id"], 100.0)

    stale_batch = request_scale_up_batch(api, approved["id"], target_kg=150)
    assert stale_batch["pinned_formula_version"] == approved["version"]

    reprice_material(api, material["id"], 2500)
    assert read_material(api, material["id"])["cost_per_kg_cents"] == 2500

    recosted = read_formula(api, approved["id"])
    assert recosted["status"] == "APPROVED"
    assert recosted["cost_stale"] is True
    assert recosted["bench_cost_per_kg_cents"] == 2500
    assert recosted["version"] == approved["version"] + 1

    refused = api.set_batch_tolerance(stale_batch["id"], DIRECTOR_APPROVER)
    validate_error(refused, ApiErrorId.ERR_PINNED_FORMULA_STALE.value, 409)

    untouched = read_batch(api, stale_batch["id"])
    assert untouched["status"] == "REQUESTED"
    assert untouched["material_cost_cents"] is None
    assert untouched["tolerance_spec"] == []

    fresh_batch = request_scale_up_batch(api, approved["id"], target_kg=150)
    assert fresh_batch["pinned_formula_version"] == approved["version"] + 1

    toleranced = set_batch_tolerance(api, fresh_batch["id"])
    assert toleranced["batch_total_cents"] == 445000
    assert toleranced["material_cost_cents"] == 375000
    assert float(toleranced["compounding_fee_pct"]) == 12.0
    assert toleranced["compounding_fee_cents"] == 45000
    assert toleranced["production_cost_per_kg_cents"] == 2967
    assert toleranced["status"] == "TOLERANCE_SET"


def test_component_count_and_weight_sum_reconcile_after_add_cost_delete_and_re_add(api):
    """Both derived aggregates track every add, the deletion and the re-add.

    Section 3.3 says "Every accepted addition recomputes the formula's
    `component_count`, which is simply the number of component lines it holds,
    and its `total_weight_pct`, which is the sum of its lines' `weight_pct`
    values carried to four decimal places", that "A formula sitting in `COSTED`
    falls back `COSTED → DRAFT` on the addition" clearing
    `bench_cost_per_kg_cents` and "`contribution_cents` to null on every one of
    the formula's component lines", and that on removal "the row disappears ...
    `component_count` and `total_weight_pct` are recomputed, and the same
    `COSTED → DRAFT` ... fallback fires with the same field clearing".  Both
    costings price 2000 x 60 / 100 = 1200 and 2000 x 40 / 100 = 800, summing to
    2000 cents per kilogram.

    Design: Corner/complexity_layers/component_count_and_weight_sum_reconcile_after_add_cost_delete_and_re_add
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    assert formula["component_count"] == 0
    assert float(formula["total_weight_pct"]) == 0.0

    keep = add_material_line(api, formula["id"], material["id"], 60.0)
    after_first = read_formula(api, formula["id"])
    assert after_first["component_count"] == 1
    assert float(after_first["total_weight_pct"]) == 60.0

    drop = add_material_line(api, formula["id"], material["id"], 40.0)
    after_second = read_formula(api, formula["id"])
    assert after_second["component_count"] == 2
    assert float(after_second["total_weight_pct"]) == 100.0

    first_costing = cost_formula(api, formula["id"])
    assert first_costing["bench_cost_per_kg_cents"] == 2000
    assert read_component(api, keep["id"])["contribution_cents"] == 1200
    assert read_component(api, drop["id"])["contribution_cents"] == 800

    delete_component(api, drop["id"])
    after_delete = read_formula(api, formula["id"])
    assert after_delete["status"] == "DRAFT"
    assert after_delete["component_count"] == 1
    assert float(after_delete["total_weight_pct"]) == 60.0
    assert after_delete["bench_cost_per_kg_cents"] is None
    assert read_component(api, keep["id"])["contribution_cents"] is None

    replacement = add_material_line(api, formula["id"], material["id"], 40.0)
    after_re_add = read_formula(api, formula["id"])
    assert after_re_add["component_count"] == 2
    assert float(after_re_add["total_weight_pct"]) == 100.0
    assert after_re_add["status"] == "DRAFT"

    second_costing = cost_formula(api, formula["id"])
    assert second_costing["bench_cost_per_kg_cents"] == 2000
    assert read_component(api, keep["id"])["contribution_cents"] == 1200
    assert read_component(api, replacement["id"])["contribution_cents"] == 800

    lines = components_of(api, formula["id"])
    assert len(lines) == 2
    body = list_data(api, api.list_formula_components, FLAVORIST,
                     formula_id=formula["id"])
    assert body["meta"]["total_count"] == 2
