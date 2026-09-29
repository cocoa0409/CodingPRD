"""Cascades that travel several rows deep from a single request.

Two chains are exercised here: the emergency remediation order that freezes the
project's posture and, through the freeze, suspends its active well and unwinds
the credit it had claimed; and the area-of-review delineation that re-screens the
project's legacy wellbores and, through the enlarged obligation set, re-sizes the
financial assurance requirement until the posted instrument no longer covers it.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.constants import (
    LCA_UPSTREAM_EMISSIONS_FACTOR,
    SURETY_BOND_FACE_AMOUNT_USD,
    TAX_YEAR,
    WELLBORE_CEMENTED_DOCUMENTED_FAR,
    WELLBORE_PARTIALLY_PLUGGED_MID,
    WELLBORE_SEAL_OPEN_HOLE_NEAR,
)
from test_helpers.factories import create_remediation_order_payload


def _project_with_submitted_claim(api):
    """An `INJECTION_ACTIVE` project whose 2027 credit claim is `SUBMITTED`."""
    ctx = fixtures.setup_project_with_ledger(api)
    return fixtures.setup_submitted_tax_credit_claim(
        api,
        ctx,
        tax_year=TAX_YEAR,
        claim_variant="REPORTED",
        lca_upstream_emissions_factor=LCA_UPSTREAM_EMISSIONS_FACTOR,
    )


def _project_with_out_of_aor_wellbores(api):
    """An accepted, simulated model, three screened-out wellbores and a bond."""
    ctx = fixtures.setup_project_with_accepted_model(api)
    ctx["wellbores"] = [
        fixtures.register_wellbore(
            api, ctx["project"]["id"], "15-001-00001", **WELLBORE_SEAL_OPEN_HOLE_NEAR
        ),
        fixtures.register_wellbore(
            api, ctx["project"]["id"], "15-001-00002", **WELLBORE_PARTIALLY_PLUGGED_MID
        ),
        fixtures.register_wellbore(
            api, ctx["project"]["id"], "15-001-00003", **WELLBORE_CEMENTED_DOCUMENTED_FAR
        ),
    ]
    ctx["instrument"] = fixtures.post_and_allocate_instrument(
        api,
        ctx["project"]["id"],
        instrument_type="SURETY_BOND",
        face_amount_usd=SURETY_BOND_FACE_AMOUNT_USD,
    )
    ctx["project"] = fixtures.refresh_project(api, ctx["project"]["id"])
    return ctx


def test_major_remediation_order_freezes_the_project_without_drawing_the_reserve(
    api, regulatory_reviewer_headers
):
    """Opening stamps `opened_at` with the logical clock, sets the order's `status`
    to `OPEN`, and computes its `reserve_draw_usd`. The draw is zero — exactly 0.00
    — for `MINOR` and `MAJOR` severity. When a draw does occur, that instrument's
    `drawn_usd` is set to the order's `reserve_draw_usd`, its
    `allocated_emergency_usd` is reduced by the drawn amount, its `status` moves
    `ALLOCATED → DRAWN`, the project's `allocated_assurance_usd` and
    `assurance_coverage_status` are recomputed, and both the instrument's `version`
    and the project's `version` increment. The project's `open_remediation_count`
    increments by one. When the `severity` is `MAJOR` or `CRITICAL`, the project's
    `operational_posture` is set to `FROZEN` — which then drives every `ACTIVE`
    permit of the project to `SUSPENDED` with its `authorized_injection_rate_tpy`
    zeroed, which in turn reverts every `SUBMITTED` claim of the project to `DRAFT`,
    which in turn forces a recomputation of the project's `pending_credit_usd`.

    Design: Difficulty/transitive_cascade/remediation_order_freeze_cascade_depth_four
    """
    ctx = _project_with_submitted_claim(api)
    project_pre = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project_pre["operational_posture"] == "OPEN"
    assert project_pre["pending_credit_usd"] == 38500000.00
    assert project_pre["open_remediation_count"] == 0

    order = validate_success(
        api.create_remediation_order(
            create_remediation_order_payload(
                ctx["project"]["id"],
                trigger_type="PLUME_EXCURSION",
                severity="MAJOR",
                narrative="monitoring detected plume outside the modelled footprint",
            ),
            regulatory_reviewer_headers,
        ),
        201,
    )
    assert order["status"] == "OPEN"
    assert order["reserve_draw_usd"] == 0

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["operational_posture"] == "FROZEN"
    assert project["open_remediation_count"] == 1
    assert project["status"] == "INJECTION_ACTIVE"

    instrument = fixtures.refresh_instrument(api, ctx["instrument"]["id"])
    assert instrument["status"] == "ALLOCATED"
    assert instrument["drawn_usd"] == 0.00


def test_freeze_suspends_the_active_well_and_reverts_the_submitted_credit_claim(
    api, regulatory_reviewer_headers
):
    """Whenever the project's `operational_posture` becomes `FROZEN`, and whenever
    the developer begins post-injection site care, every permit of that project
    whose `permit_status` is `ACTIVE` is driven `ACTIVE → SUSPENDED` with
    `authorized_injection_rate_tpy` reset to 0 and its `version` bumped.
    Suspension in turn cascades onto the project's credit claims: because the
    permit has left `ACTIVE`, every tax credit claim of the project whose `status`
    is `SUBMITTED` reverts `SUBMITTED → DRAFT`, each such claim's `version`
    increments, and the project's `pending_credit_usd` is recomputed over the
    claims whose `status` is `SUBMITTED` or `ALLOWED`. Reverted claims are *not*
    automatically resubmitted; the developer must submit them again.

    Design: Difficulty/transitive_cascade/remediation_order_freeze_cascade_depth_four
    """
    ctx = _project_with_submitted_claim(api)
    permit_pre = fixtures.refresh_permit(api, ctx["permit"]["id"])
    assert permit_pre["permit_status"] == "ACTIVE"
    assert permit_pre["authorized_injection_rate_tpy"] == 1000000
    claim_pre = fixtures.refresh_claim(api, ctx["claim"]["id"])
    assert claim_pre["status"] == "SUBMITTED"
    assert claim_pre["credit_amount_usd"] == 38500000.00

    validate_success(
        api.create_remediation_order(
            create_remediation_order_payload(
                ctx["project"]["id"],
                trigger_type="PLUME_EXCURSION",
                severity="MAJOR",
                narrative="monitoring detected plume outside the modelled footprint",
            ),
            regulatory_reviewer_headers,
        ),
        201,
    )

    permit = fixtures.refresh_permit(api, ctx["permit"]["id"])
    assert permit["permit_status"] == "SUSPENDED"
    assert permit["authorized_injection_rate_tpy"] == 0
    assert permit["construction_status"] == "COMPLETED"

    claim = fixtures.refresh_claim(api, ctx["claim"]["id"])
    assert claim["status"] == "DRAFT"

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["pending_credit_usd"] == 0.00


def test_finalize_aor_rescreens_the_out_of_aor_wellbores_onto_the_new_radius(
    api, project_developer_headers
):
    """When the project's `aor_radius_km` is 0, or when the wellbore's
    `distance_from_injector_km` exceeds the project's `aor_radius_km`, the wellbore
    begins at `OUT_OF_AOR` and waits for a future delineation to pull it in. The
    proximity factor is 0.20 flat whenever the project's `aor_radius_km` is zero or
    below, because an undelineated area of review carries no meaningful proximity
    signal; otherwise it is one minus the ratio of `distance_from_injector_km` to
    the project's `aor_radius_km`, clamped so that it is never above 1.00 and never
    below 0.20. The `risk_score` is 100.0 multiplied by the seal factor, multiplied
    by the plug factor, multiplied by the record factor, multiplied by the quantity
    0.40 plus 0.60 times the proximity factor, rounded half up to 2 decimal places
    — so 40 percent of the score is fixed by the wellbore's own condition and 60
    percent is modulated by how close it sits to the injector. The first link
    copies the model's computed `aor_radius_km` onto the project's `aor_radius_km`,
    publishing the delineation. The second link re-screens legacy wellbores:
    because the project's area of review has changed, every legacy wellbore of the
    project whose `corrective_action_status` is `OUT_OF_AOR` and whose
    `distance_from_injector_km` is less than or equal to the project's new
    `aor_radius_km` moves `OUT_OF_AOR → IDENTIFIED`, and every wellbore now inside
    the area of review has its `risk_score` and `ca_cost_estimate_usd` recomputed
    against the new radius. Immediately afterwards, each wellbore that has just
    reached `IDENTIFIED` and either has `penetrates_seal` true or carries a
    `risk_score` of at least 40.00 auto-advances `IDENTIFIED → CA_REQUIRED` in the
    same request — a wellbore that penetrates the confining zone is always
    obligated regardless of its score, and a wellbore that does not penetrate the
    seal is obligated only once its score reaches the 40.00 threshold.

    Design: Difficulty/transitive_cascade/finalize_aor_rescreen_cascade_depth_four
    """
    ctx = _project_with_out_of_aor_wellbores(api)
    wellbore_1, wellbore_2, wellbore_3 = ctx["wellbores"]
    assert wellbore_1["corrective_action_status"] == "OUT_OF_AOR"
    assert wellbore_1["risk_score"] == 52.00
    assert ctx["project"]["corrective_action_completion_pct"] == 100.00

    validate_success(
        api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers)
    )

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["aor_radius_km"] == 3.0

    screened_1 = fixtures.refresh_wellbore(api, wellbore_1["id"])
    assert screened_1["corrective_action_status"] == "CA_REQUIRED"
    assert screened_1["risk_score"] == 90.00

    screened_2 = fixtures.refresh_wellbore(api, wellbore_2["id"])
    assert screened_2["corrective_action_status"] == "CA_REQUIRED"
    assert screened_2["risk_score"] == 47.60

    screened_3 = fixtures.refresh_wellbore(api, wellbore_3["id"])
    assert screened_3["corrective_action_status"] == "IDENTIFIED"
    assert screened_3["risk_score"] == 7.65


def test_finalize_aor_resizes_the_assurance_requirement_into_underfunded(
    api, project_developer_headers
):
    """The third link recomputes the project's `corrective_action_completion_pct`
    and `required_financial_assurance_usd`, because the population of obligated
    wellbores has changed. Of the remaining in-area-of-review wellbores, those
    bearing `IDENTIFIED` are counted as in-scope for cost purposes but are not yet
    obligated; the obligated set is those whose status is `CA_REQUIRED`,
    `CA_SCHEDULED`, `CA_COMPLETE` or `CA_WAIVED`, and the closed set is the subset
    of those whose status is `CA_COMPLETE` or `CA_WAIVED`. Otherwise it is 100.0
    multiplied by the count of closed wellbores divided by the count of obligated
    wellbores, rounded half up to 2 decimal places. The project's
    `required_financial_assurance_usd` is the sum of
    those five already-rounded buckets, itself rounded half up to 2 decimal places.
    The fourth link re-compares the project's `allocated_assurance_usd` against the
    new requirement and resets `assurance_coverage_status` to `FUNDED` or
    `UNDERFUNDED` accordingly; when the outcome is `UNDERFUNDED` and the project's
    `status` is `INJECTION_AUTHORIZED` or `INJECTION_ACTIVE`, the project's
    `operational_posture` moves `OPEN → RESTRICTED`. `assurance_coverage_status` is
    then derived by comparing `allocated_assurance_usd` against
    `required_financial_assurance_usd`, and the tests are applied in this order:
    the status is `UNFUNDED` when `allocated_assurance_usd` is zero or below;
    otherwise it is `FUNDED` when `allocated_assurance_usd` is at least
    `required_financial_assurance_usd`; otherwise it is `UNDERFUNDED`.

    Design: Difficulty/transitive_cascade/finalize_aor_rescreen_cascade_depth_four
    """
    ctx = _project_with_out_of_aor_wellbores(api)
    assert ctx["project"]["required_financial_assurance_usd"] == 12500000.00
    assert ctx["project"]["assurance_coverage_status"] == "FUNDED"
    assert ctx["project"]["corrective_action_completion_pct"] == 100.00

    validate_success(
        api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers)
    )

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["corrective_action_completion_pct"] == 0.00
    assert project["required_financial_assurance_usd"] == 25857666.94
    assert project["allocated_assurance_usd"] == 12500000.00
    assert project["assurance_coverage_status"] == "UNDERFUNDED"
    assert project["operational_posture"] == "OPEN"

    instrument = fixtures.refresh_instrument(api, ctx["instrument"]["id"])
    assert instrument["allocated_pisc_usd"] == 10000000.00
    assert instrument["allocated_emergency_usd"] == 2500000.00
    assert instrument["unallocated_usd"] == 0.00
