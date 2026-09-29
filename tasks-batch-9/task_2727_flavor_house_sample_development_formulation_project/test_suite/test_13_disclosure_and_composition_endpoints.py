"""Composition reads under the IP gate, grant issuance and component deletion."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_envelope_meta, assert_instant_equals
from test_helpers.factories import create_disclosure_grant_payload
from test_helpers.fixtures import (
    add_material_line,
    approve_formula,
    cost_formula,
    create_accepted_brief,
    create_formula,
    create_material,
    decide_batch,
    delete_component,
    issue_grant,
    list_data,
    read_batch,
    read_component,
    read_formula,
    read_grant,
    report_pilot_run,
    request_scale_up_batch,
    set_batch_tolerance,
    set_clock,
    submit_formula,
)
from test_helpers.test_users import ACCOUNT_MANAGER, DIRECTOR_APPROVER, FLAVORIST


def _costed_gum_base_formula(api, brief_tier="TIER_1_STANDARD", **formula_overrides):
    """Register GUM-BASE, accept BRF-0001 and cost a single-line formula on it."""
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001",
                                  confidentiality_tier=brief_tier)
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1",
                             **formula_overrides)
    component = add_material_line(api, formula["id"], material["id"], 100.0)
    costed = cost_formula(api, formula["id"])
    return {"material": material, "brief": brief, "formula": costed,
            "component": component}


def test_tier_one_composition_readable_without_a_grant(api):
    """An AccountManager reads a TIER_1_STANDARD composition with no grant at all.

    Section 2.9 says "Reading the component lines of a `TIER_1_STANDARD`
    formula needs nothing beyond a valid role", the endpoint table opens
    `GET /formulas/{formula_id}/composition` to "All roles", and the envelope's
    `response_type` is "either "object" for a single resource or "array" for a
    list".  The single line contributes 2000 x 100 / 100 = 2000 cents.

    Design: Corner/endpoints/tier_one_composition_readable_without_a_grant
    """
    scenario = _costed_gum_base_formula(api)

    response = api.get_formula_composition(scenario["formula"]["id"],
                                           ACCOUNT_MANAGER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert_envelope_meta(body, "array")

    rows = body["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == scenario["component"]["id"]
    assert rows[0]["component_type"] == "RAW_MATERIAL"
    assert rows[0]["raw_material_id"] == scenario["material"]["id"]
    assert float(rows[0]["weight_pct"]) == 100.0
    assert rows[0]["contribution_cents"] == 2000


def test_tier_two_composition_without_a_grant_forbidden(api):
    """The gate closes on the composition read while the formula header stays open.

    Section 2.9 requires for a `TIER_2_RESTRICTED` formula that "the caller ...
    name a disclosure grant through a `grant_id` query value", and "A missing
    grant, a grant issued for a different formula, or a grant whose tier does
    not reach the formula's tier are all reported as `ERR_IP_TIER_FORBIDDEN`
    (HTTP 403)".  That gate covers only the composition read: the formula is
    "opened under that brief inherits it unless the flavourist overrides it",
    and `GET /formulas/{formula_id}` carries no such gate.

    Design: Corner/endpoints/tier_two_composition_without_a_grant_forbidden
    """
    scenario = _costed_gum_base_formula(
        api, confidentiality_tier="TIER_2_RESTRICTED")
    formula_id = scenario["formula"]["id"]

    blocked = api.get_formula_composition(formula_id, ACCOUNT_MANAGER)
    validate_error(blocked, ApiErrorId.ERR_IP_TIER_FORBIDDEN.value, 403)

    header = get_success_data(api.get_formula(formula_id, ACCOUNT_MANAGER), 200)
    assert header["confidentiality_tier"] == "TIER_2_RESTRICTED"
    assert header["bench_cost_per_kg_cents"] == 2000


def test_grant_expiry_equality_flips_the_composition_read_to_forbidden(api):
    """A clock reading exactly expires_at already reads the grant as EXPIRED.

    Section 2.9: a grant's `status` "reads `ACTIVE` while the logical clock is
    strictly before `expires_at`, and `EXPIRED` from the instant the clock
    reaches `expires_at`.  The boundary is deliberate — a clock reading exactly
    equal to `expires_at` is already expired.  Presenting an expired grant is
    rejected with `ERR_DISCLOSURE_GRANT_EXPIRED` (HTTP 403)."

    Design: Corner/endpoints/grant_expiry_equality_flips_the_composition_read_to_forbidden
    """
    expires_at = "2026-08-15T00:00:00Z"
    scenario = _costed_gum_base_formula(api, brief_tier="TIER_2_RESTRICTED")
    formula_id = scenario["formula"]["id"]
    grant = issue_grant(api, scenario["brief"]["id"], formula_id,
                        disclosed_tier="TIER_2_RESTRICTED",
                        redaction_level="FULL", expires_at=expires_at)
    assert grant["status"] == "ACTIVE"

    live = api.get_formula_composition(formula_id, ACCOUNT_MANAGER,
                                       grant_id=grant["id"], disclose_full=True)
    rows = get_success_data(live, 200)
    assert float(rows[0]["weight_pct"]) == 100.0

    set_clock(api, expires_at)

    expired = api.get_formula_composition(formula_id, ACCOUNT_MANAGER,
                                          grant_id=grant["id"],
                                          disclose_full=True)
    validate_error(expired, ApiErrorId.ERR_DISCLOSURE_GRANT_EXPIRED.value, 403)

    stored = read_grant(api, grant["id"])
    assert stored["status"] == "EXPIRED"
    assert_instant_equals(stored["expires_at"], expires_at, "expires_at")


def test_disclose_full_with_a_redacted_grant_rejected(api):
    """The same live grant refuses the unredacted view and serves the redacted one.

    Section 2.9: "A composition read may ask for the unredacted view by setting
    `disclose_full` to true, but that request is only honoured when the supplied
    grant's `redaction_level` is `FULL`.  Asking a `REDACTED` grant to un-redact
    is rejected with `ERR_REDACTION_LEVEL_INSUFFICIENT` (HTTP 403)."  Section
    2.11 orders the gate "first the tier-and-grant check ... then the grant's
    live-ness ... then the redaction-level check", so a live REDACTED grant
    reaches exactly that third step.

    Design: Corner/endpoints/disclose_full_with_a_redacted_grant_rejected
    """
    scenario = _costed_gum_base_formula(api, brief_tier="TIER_2_RESTRICTED")
    formula_id = scenario["formula"]["id"]
    grant = issue_grant(api, scenario["brief"]["id"], formula_id,
                        disclosed_tier="TIER_2_RESTRICTED",
                        redaction_level="REDACTED",
                        expires_at="2026-12-31T00:00:00Z")

    refused = api.get_formula_composition(formula_id, ACCOUNT_MANAGER,
                                          grant_id=grant["id"],
                                          disclose_full=True)
    validate_error(refused, ApiErrorId.ERR_REDACTION_LEVEL_INSUFFICIENT.value, 403)

    redacted = api.get_formula_composition(formula_id, ACCOUNT_MANAGER,
                                           grant_id=grant["id"])
    rows = get_success_data(redacted, 200)
    assert len(rows) == 1

    stored = read_grant(api, grant["id"])
    assert stored["redaction_level"] == "REDACTED"
    assert stored["status"] == "ACTIVE"


def test_grant_naming_a_formula_of_another_brief_rejected(api):
    """A grant may not pair one brief with a formula belonging to another.

    Section 3.9 says of grant issuance that "the named formula must belong to
    the named brief, else `ERR_GRANT_FORMULA_MISMATCH`", alongside the rule that
    a grant "names the `brief_id` the engagement runs under, the single
    `formula_id` whose composition the grant opens".  Grants "can be listed and
    filtered by `brief_id` and by `formula_id`".

    Design: Corner/endpoints/grant_naming_a_formula_of_another_brief_rejected
    """
    first = create_accepted_brief(api, brief_code="BRF-0001",
                                 confidentiality_tier="TIER_2_RESTRICTED")
    second = create_accepted_brief(api, brief_code="BRF-0002",
                                   customer_name="Alpine Snacks",
                                   matrix_type="SAVOURY_SNACK",
                                   target_profile="SAVOURY_UMAMI",
                                   dosage_pct=0.2, annual_volume_kg=3000,
                                   cost_in_use_cap_cents_per_tonne=70000,
                                   confidentiality_tier="TIER_2_RESTRICTED")
    foreign = create_formula(api, second["id"], name="Umami Snack F1")

    response = api.create_disclosure_grant(
        create_disclosure_grant_payload(first["id"], foreign["id"],
                                        "TIER_2_RESTRICTED",
                                        "2026-12-31T00:00:00Z",
                                        redaction_level="FULL"),
        DIRECTOR_APPROVER)
    validate_error(response, ApiErrorId.ERR_GRANT_FORMULA_MISMATCH.value, 422)

    body = list_data(api, api.list_disclosure_grants, DIRECTOR_APPROVER,
                     brief_id=first["id"])
    assert body["meta"]["total_count"] == 0


def test_delete_component_from_a_costed_formula_reverts_it_to_draft(api):
    """The 204 deletion drops the line and unwinds the costing to null.

    Section 3.3 says of removing a line that "the row disappears", that
    "`component_count` and `total_weight_pct` are recomputed, and the same
    `COSTED → DRAFT` or `REWORK_REQUIRED → DRAFT` fallback fires with the same
    field clearing, including `contribution_cents` on every surviving line" —
    the fallback that "clears `bench_cost_per_kg_cents`,
    `bench_cost_in_use_cents_per_tonne` ... back to null".  The deleted row then
    answers its own not-found code.

    Design: Corner/endpoints/delete_component_from_a_costed_formula_reverts_it_to_draft
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    keep = add_material_line(api, formula["id"], material["id"], 60.0)
    drop = add_material_line(api, formula["id"], material["id"], 40.0)
    costed = cost_formula(api, formula["id"])
    assert costed["bench_cost_per_kg_cents"] == 2000
    assert costed["status"] == "COSTED"

    delete_component(api, drop["id"])

    gone = api.get_formula_component(drop["id"], FLAVORIST)
    validate_error(gone, ApiErrorId.ERR_COMPONENT_NOT_FOUND.value, 404)

    reverted = read_formula(api, formula["id"])
    assert reverted["status"] == "DRAFT"
    assert reverted["component_count"] == 1
    assert float(reverted["total_weight_pct"]) == 60.0
    assert reverted["bench_cost_per_kg_cents"] is None
    assert reverted["bench_cost_in_use_cents_per_tonne"] is None
    assert read_component(api, keep["id"])["contribution_cents"] is None


def test_delete_component_of_an_approved_formula_rejected(api):
    """An approved formula's composition is frozen and the line survives.

    Section 3.3: "Deletion succeeds only while the owning formula is still
    editable: attempting it while the formula is `SUBMITTED`, `APPROVED`,
    `SUPERSEDED` or `ARCHIVED` is rejected with `ERR_FORMULA_STATE_INVALID`."

    Design: Corner/endpoints/delete_component_of_an_approved_formula_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    component = add_material_line(api, formula["id"], material["id"], 100.0)
    cost_formula(api, formula["id"])
    submit_formula(api, formula["id"])
    approved = approve_formula(api, formula["id"])
    assert approved["status"] == "APPROVED"

    response = api.delete_formula_component(component["id"], FLAVORIST)
    validate_error(response, ApiErrorId.ERR_FORMULA_STATE_INVALID.value, 409)

    unchanged = read_formula(api, formula["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["component_count"] == 1
    assert float(unchanged["total_weight_pct"]) == 100.0

    still_there = api.get_formula_component(component["id"], FLAVORIST)
    assert still_there.status_code == 200, still_there.text


def test_pilot_run_then_qualification_records_signed_yield_variance(api):
    """A 147 kg yield on a 150 kg target reports -2.00 and then qualifies.

    Section 3.9 computes "the signed `yield_variance_pct` as the measured yield
    minus the target, multiplied by 100, divided by the target, rounded half up
    to two decimal places; a batch that under-delivers therefore reports a
    negative variance", and "A `decision` of `QUALIFIED` drives `PILOT_RUN →
    QUALIFIED` and records the note".  The costing behind it: bench cost 2000 x
    0.90 + 4500 x 0.10 = 2250, so `material_cost_cents` is 2250 x 150 = 337500,
    which being "below 500000 cents selects a `compounding_fee_pct` of 12.0",
    giving 40500, then `batch_total_cents` adds "a flat QA release charge of
    25000 cents" to reach 403000 and `production_cost_per_kg_cents` is
    403000 / 150 rounded half up to 2687.  The tolerance entries follow §3.9's
    band rules: the 90 % standard line takes 1.8 x 1.0 x 0.8 = 1.44 "capped at a
    maximum band of 1.0000 percent", while the 10 % `HIGH_IMPACT` line takes
    0.2 x 0.5 x 0.8 = 0.0800 with 10.0000 of headroom.

    Design: Corner/endpoints/pilot_run_then_qualification_records_signed_yield_variance
    """
    gum_base = create_material(api, material_code="GUM-BASE")
    vanillin = create_material(api, material_code="HI-VANILLIN",
                               name="Vanillin Crystals",
                               cost_per_kg_cents=4500,
                               potency_class="HIGH_IMPACT",
                               max_use_ppm=200000)
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, formula["id"], gum_base["id"], 90.0)
    add_material_line(api, formula["id"], vanillin["id"], 10.0)
    costed = cost_formula(api, formula["id"])
    assert costed["bench_cost_per_kg_cents"] == 2250
    submit_formula(api, formula["id"])
    approved = approve_formula(api, formula["id"])

    batch = request_scale_up_batch(api, formula["id"], target_kg=150)
    assert batch["pinned_formula_version"] == approved["version"]
    toleranced = set_batch_tolerance(api, batch["id"])
    assert toleranced["batch_total_cents"] == 403000

    piloted = report_pilot_run(api, batch["id"], 147.0)
    assert float(piloted["yield_variance_pct"]) == -2.00
    assert float(piloted["measured_yield_kg"]) == 147.0

    qualified = decide_batch(api, batch["id"], "QUALIFIED",
                             decision_note="within band")
    assert qualified["status"] == "QUALIFIED"

    stored = read_batch(api, batch["id"])
    assert stored["decision_note"] == "within band"
    assert stored["material_cost_cents"] == 337500
    assert float(stored["compounding_fee_pct"]) == 12.0
    assert stored["compounding_fee_cents"] == 40500
    assert stored["production_cost_per_kg_cents"] == 2687
    assert float(stored["yield_variance_pct"]) == -2.00

    bands = [float(entry["band_pct"]) for entry in stored["tolerance_spec"]]
    assert bands == [1.0, 0.08]
