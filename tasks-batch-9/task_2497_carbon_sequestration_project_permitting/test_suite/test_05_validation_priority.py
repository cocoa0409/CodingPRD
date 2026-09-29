"""Which refusal a permitting request earns when two rules fail at once.

Activation, landowner responses and closure certification are each reachable in
a posture where two different rules are violated by the same call. These tests
pin the refusal the validation precedence ladder produces, and then re-reach the
lower-ranked rule on its own so that the ordering — rather than the mere
existence of one error — is what is under test.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    LANDOWNER_1_USER_ID,
    SECOND_REVIEWER_USER_ID,
    ApiErrorId,
    constants,
    factories,
    fixtures,
)


def test_activate_permit_in_draft_on_unfunded_project_reports_state_error(
    api, regulatory_reviewer_headers
):
    """The system evaluates checks in a fixed precedence ladder, and the first
    failing check produces the response; later checks are not evaluated. Reading
    the ladder from highest precedence to lowest:

    9. **State admissibility.** Each entity's own current state must admit the
    requested transition, and each entity has its own error code: the project's
    `status` or `unitization_status` yields `ERR_INVALID_PROJECT_STATE`; a
    geologic model's `status` or `plume_status` yields `ERR_INVALID_MODEL_STATE`;
    a wellbore's `corrective_action_status` yields
    `ERR_INVALID_WELLBORE_CA_STATE`; a tract's `lease_status` yields
    `ERR_INVALID_TRACT_STATE`; a permit's `permit_status` yields
    `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection period
    against a permit); the construction sequence yields
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test
    yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an
    already-closed review track yields `ERR_INVALID_PLAN_STATE` (this also
    guards adding or retiring a method); an instrument's `status` yields
    `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or
    remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.

    14. **Fiscal rules, last.** Assurance coverage
    (`ERR_ASSURANCE_INSUFFICIENT`, HTTP 402) precedes the
    allocation-requirement check (`ERR_ALLOCATION_EXCEEDS_FACE_AMOUNT`).

    It requires the permit's `permit_status` to be `APPROVED`, its
    `construction_status` to already be `COMPLETED` (otherwise
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`), its `last_mit_result` to be `PASS`
    (otherwise `ERR_MIT_NOT_PASSED`), the project's `status` to be
    `INJECTION_AUTHORIZED` or `INJECTION_ACTIVE`, the project's
    `operational_posture` not to be `FROZEN`, and the project's
    `assurance_coverage_status` to be `FUNDED` (otherwise
    `ERR_ASSURANCE_INSUFFICIENT`, HTTP 402).

    A project with nothing allocated therefore reads `UNFUNDED` even when its
    requirement happens to be zero.

    Design: Difficulty/priority_pair_validation_conflict/activate_permit_state_error_precedes_assurance_error
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(api, ctx["project"]["id"], ctx["model"]["id"])

    project_before = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project_before["status"] == "PERMITTING"
    assert project_before["assurance_coverage_status"] == "UNFUNDED"
    assert permit["permit_status"] == "DRAFT"
    assert permit["construction_status"] == "NOT_STARTED"

    response = api.activate_injection_well_permit(
        permit["id"],
        {"activation_note": "premature activation attempt"},
        regulatory_reviewer_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_PERMIT_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ASSURANCE_INSUFFICIENT.value
    assert response.status_code != 402

    permit_after = fixtures.refresh_permit(api, permit["id"])
    assert permit_after["permit_status"] == "DRAFT"
    assert permit_after["construction_status"] == "NOT_STARTED"
    assert permit_after["authorized_injection_rate_tpy"] == 0
    assert permit_after["activated_at"] is None

    project_after = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project_after["status"] == "PERMITTING"


def test_activate_permit_reports_assurance_error_once_permit_state_is_admissible(
    api, regulatory_reviewer_headers
):
    """It requires the permit's `permit_status` to be `APPROVED`, its
    `construction_status` to already be `COMPLETED` (otherwise
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`), its `last_mit_result` to be `PASS`
    (otherwise `ERR_MIT_NOT_PASSED`), the project's `status` to be
    `INJECTION_AUTHORIZED` or `INJECTION_ACTIVE`, the project's
    `operational_posture` not to be `FROZEN`, and the project's
    `assurance_coverage_status` to be `FUNDED` (otherwise
    `ERR_ASSURANCE_INSUFFICIENT`, HTTP 402).

    Either way, registration recomputes the project's
    `corrective_action_completion_pct` and `required_financial_assurance_usd`.

    `assurance_coverage_status` is then derived by comparing
    `allocated_assurance_usd` against `required_financial_assurance_usd`, and the
    tests are applied in this order: the status is `UNFUNDED` when
    `allocated_assurance_usd` is zero or below; otherwise it is `FUNDED` when
    `allocated_assurance_usd` is at least `required_financial_assurance_usd`;
    otherwise it is `UNDERFUNDED`.

    `RESTRICTED` does not itself block child mutations; the fiscal gates that
    care about funding test the assurance coverage status directly.

    Design: Difficulty/priority_pair_validation_conflict/activate_permit_state_error_precedes_assurance_error
    """
    ctx = fixtures.setup_authorized_project(api)
    fixtures.advance_construction_through(
        api, ctx["permit"]["id"], fixtures.CONSTRUCTION_SEQUENCE[:4]
    )
    fixtures.record_passing_mit(api, ctx["permit"]["id"])
    permit = fixtures.advance_construction_through(
        api, ctx["permit"]["id"], ["COMPLETED"]
    )
    assert permit["permit_status"] == "APPROVED"
    assert permit["construction_status"] == "COMPLETED"
    assert permit["last_mit_result"] == "PASS"

    # A newly screened in-area-of-review wellbore raises the requirement above
    # the amount already allocated, so only the fiscal rung can still fail.
    fixtures.register_wellbore(
        api,
        ctx["project"]["id"],
        "15-001-00003",
        **constants.WELLBORE_CEMENTED_DOCUMENTED_FAR,
    )
    project_before = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project_before["status"] == "INJECTION_AUTHORIZED"
    assert project_before["assurance_coverage_status"] == "UNDERFUNDED"

    response = api.activate_injection_well_permit(
        permit["id"],
        {"activation_note": "activation attempt against an underfunded project"},
        regulatory_reviewer_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_ASSURANCE_INSUFFICIENT.value, 402)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_PERMIT_STATE.value
    assert response.status_code != 409

    permit_after = fixtures.refresh_permit(api, permit["id"])
    assert permit_after["permit_status"] == "APPROVED"
    assert permit_after["authorized_injection_rate_tpy"] == 0
    assert permit_after["activated_at"] is None

    project_after = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project_after["status"] == "INJECTION_AUTHORIZED"


def test_respond_to_offer_by_stranger_on_unleased_tract_reports_landowner_error(
    api, stranger_landowner_headers
):
    """The system evaluates checks in a fixed precedence ladder, and the first
    failing check produces the response; later checks are not evaluated. Reading
    the ladder from highest precedence to lowest:

    3. **Tract ownership.** For a `Landowner` responding on a tract,
    `X-User-ID` equals the tract's `landowner_user_id` —
    `ERR_NOT_TRACT_LANDOWNER`.

    9. **State admissibility.** Each entity's own current state must admit the
    requested transition, and each entity has its own error code: the project's
    `status` or `unitization_status` yields `ERR_INVALID_PROJECT_STATE`; a
    geologic model's `status` or `plume_status` yields `ERR_INVALID_MODEL_STATE`;
    a wellbore's `corrective_action_status` yields
    `ERR_INVALID_WELLBORE_CA_STATE`; a tract's `lease_status` yields
    `ERR_INVALID_TRACT_STATE`; a permit's `permit_status` yields
    `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection period
    against a permit); the construction sequence yields
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test
    yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an
    already-closed review track yields `ERR_INVALID_PLAN_STATE` (this also
    guards adding or retiring a method); an instrument's `status` yields
    `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or
    remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.

    All three require the tract to be at `OFFER_SENT` and require the acting
    `X-User-ID` to equal the tract's `landowner_user_id`.

    A mismatch is rejected with `ERR_NOT_TRACT_LANDOWNER` (HTTP 403).

    Design: Difficulty/priority_pair_validation_conflict/tract_respond_landowner_auth_error_precedes_state_error
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    tract = fixtures.register_tract(
        api,
        project["id"],
        "T1",
        acreage=1000,
        ownership_pct=100,
        landowner_user_id=LANDOWNER_1_USER_ID,
    )
    assert tract["lease_status"] == "UNLEASED"

    response = api.respond_to_lease_offer(
        tract["id"], factories.accept_offer_payload(), stranger_landowner_headers
    )
    error = validate_error(response, ApiErrorId.ERR_NOT_TRACT_LANDOWNER.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_TRACT_STATE.value
    assert response.status_code != 409

    tract_after = fixtures.refresh_tract(api, tract["id"])
    assert tract_after["lease_status"] == "UNLEASED"
    assert tract_after["negotiation_round_count"] == 0
    assert tract_after["executed_bonus_per_acre_usd"] is None
    assert tract_after["net_acreage"] == 0

    project_after = fixtures.refresh_project(api, project["id"])
    assert project_after["secured_acreage"] == 0


def test_respond_to_offer_by_entitled_landowner_on_unleased_tract_reports_state_error(
    api, landowner_headers
):
    """All three require the tract to be at `OFFER_SENT` and require the acting
    `X-User-ID` to equal the tract's `landowner_user_id`.

    9. **State admissibility.** Each entity's own current state must admit the
    requested transition, and each entity has its own error code: the project's
    `status` or `unitization_status` yields `ERR_INVALID_PROJECT_STATE`; a
    geologic model's `status` or `plume_status` yields `ERR_INVALID_MODEL_STATE`;
    a wellbore's `corrective_action_status` yields
    `ERR_INVALID_WELLBORE_CA_STATE`; a tract's `lease_status` yields
    `ERR_INVALID_TRACT_STATE`; a permit's `permit_status` yields
    `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection period
    against a permit); the construction sequence yields
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test
    yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an
    already-closed review track yields `ERR_INVALID_PLAN_STATE` (this also
    guards adding or retiring a method); an instrument's `status` yields
    `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or
    remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.

    A new tract rests at `lease_status` `UNLEASED` with
    `negotiation_round_count`, `bonus_settlement_usd` and `net_acreage` all at 0.

    Design: Difficulty/priority_pair_validation_conflict/tract_respond_landowner_auth_error_precedes_state_error
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    tract = fixtures.register_tract(
        api,
        project["id"],
        "T1",
        acreage=1000,
        ownership_pct=100,
        landowner_user_id=LANDOWNER_1_USER_ID,
    )
    assert tract["lease_status"] == "UNLEASED"
    assert tract["landowner_user_id"] == LANDOWNER_1_USER_ID

    response = api.respond_to_lease_offer(
        tract["id"], factories.accept_offer_payload(), landowner_headers
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_TRACT_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_NOT_TRACT_LANDOWNER.value
    assert response.status_code != 403

    tract_after = fixtures.refresh_tract(api, tract["id"])
    assert tract_after["lease_status"] == "UNLEASED"
    assert tract_after["negotiation_round_count"] == 0
    assert tract_after["executed_bonus_per_acre_usd"] is None
    assert tract_after["net_acreage"] == 0

    project_after = fixtures.refresh_project(api, project["id"])
    assert project_after["secured_acreage"] == 0


def test_certify_closure_with_open_order_and_unelapsed_care_reports_order_error(
    api, project_developer_headers, other_reviewer_headers, program_admin_headers
):
    """The system evaluates checks in a fixed precedence ladder, and the first
    failing check produces the response; later checks are not evaluated. Reading
    the ladder from highest precedence to lowest:

    11. **Safety and referential business rules.** In this internal order: seal
    integrity (`ERR_SEAL_INTEGRITY_FAIL`), injection pressure
    (`ERR_INJECTION_PRESSURE_EXCEEDS_LIMIT`), construction standards
    (`ERR_CASING_PROGRAM_NONCOMPLIANT`), non-endangerment attestation
    (`ERR_NON_ENDANGERMENT_NOT_DEMONSTRATED`), monitoring plan approval status
    (`ERR_MRV_PLAN_NOT_APPROVED`), area-of-review delineation
    (`ERR_AOR_NOT_DELINEATED`), and open remediation orders
    (`ERR_OPEN_REMEDIATION_ORDER`).

    12. **Temporal business rules.** Injection period overlap
    (`ERR_INJECTION_PERIOD_OVERLAP`), corrective-action rig capacity
    (`ERR_CA_RIG_CAPACITY_EXCEEDED`), and post-injection elapsed time
    (`ERR_PISC_DURATION_NOT_ELAPSED`), in that order.

    It requires that no remediation order of the project have `status` `OPEN`
    (otherwise `ERR_OPEN_REMEDIATION_ORDER`). It requires `pisc_elapsed_years`
    to be at least `pisc_duration_years`; certifying early is refused with
    `ERR_PISC_DURATION_NOT_ELAPSED` (HTTP 422).

    A `MINOR` order increments the count and is recorded, but does not freeze the
    project.

    And it requires the acting `X-User-ID` to differ from the
    `technical_reviewer_user_id` of every injection well permit of the project.

    Design: Difficulty/priority_pair_validation_conflict/certify_closure_referential_error_precedes_temporal_error
    """
    ctx = fixtures.setup_injection_active_project(api)
    fixtures.set_logical_clock(api, constants.CLOCK_DURING_INJECTION_YEAR)
    project = validate_success(
        api.begin_pisc(ctx["project"]["id"], {}, project_developer_headers), 200
    )
    assert project["status"] == "PISC"
    assert project["pisc_duration_years"] == 50

    order = fixtures.open_remediation_order(
        api,
        project["id"],
        trigger_type="GROUNDWATER_IMPACT",
        severity="MINOR",
        narrative="elevated chloride in one shallow monitoring well",
    )
    assert order["status"] == "OPEN"

    project_before = fixtures.refresh_project(api, project["id"])
    assert project_before["pisc_elapsed_years"] == pytest.approx(0.000, abs=0.01)
    assert project_before["operational_posture"] == "OPEN"
    assert project_before["open_remediation_count"] == 1

    permit = fixtures.refresh_permit(api, ctx["permit"]["id"])
    assert permit["technical_reviewer_user_id"] == SECOND_REVIEWER_USER_ID

    response = api.certify_closure(
        project["id"],
        {"non_endangerment_demonstrated": True, "closure_note": "closure requested"},
        other_reviewer_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_OPEN_REMEDIATION_ORDER.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_PISC_DURATION_NOT_ELAPSED.value
    assert response.status_code != 422

    project_after = fixtures.refresh_project(api, project["id"])
    assert project_after["status"] == "PISC"
    assert project_after["closure_status"] == "NOT_REQUESTED"
    assert project_after["closure_certified_by_user_id"] is None

    instrument_after = fixtures.refresh_instrument(api, ctx["instrument"]["id"])
    assert instrument_after["status"] == "ALLOCATED"

    orders, _meta = validate_paginated(
        api.list_project_remediation_orders(project["id"], program_admin_headers)
    )
    assert [row["status"] for row in orders if row["id"] == order["id"]] == ["OPEN"]


def test_certify_closure_reports_duration_error_when_no_remediation_order_is_open(
    api, project_developer_headers, other_reviewer_headers
):
    """It requires `pisc_elapsed_years` to be at least `pisc_duration_years`;
    certifying early is refused with `ERR_PISC_DURATION_NOT_ELAPSED` (HTTP 422).

    When the alternative is not available, `pisc_duration_years` is the statutory
    default of 50 years.

    `pisc_elapsed_years` is the number of days between `pisc_start_at` and the
    current logical clock instant, divided by 365.25, rounded half up to 3 decimal
    places, and it is recomputed on every read of the project rather than being
    written by any mutation.

    It requires that no remediation order of the project have `status` `OPEN`
    (otherwise `ERR_OPEN_REMEDIATION_ORDER`).

    Design: Difficulty/priority_pair_validation_conflict/certify_closure_referential_error_precedes_temporal_error
    """
    ctx = fixtures.setup_injection_active_project(api)
    fixtures.set_logical_clock(api, constants.CLOCK_DURING_INJECTION_YEAR)
    project = validate_success(
        api.begin_pisc(ctx["project"]["id"], {}, project_developer_headers), 200
    )
    assert project["status"] == "PISC"

    project_before = fixtures.refresh_project(api, project["id"])
    assert project_before["open_remediation_count"] == 0
    assert project_before["pisc_duration_years"] == 50
    assert project_before["pisc_elapsed_years"] == pytest.approx(0.000, abs=0.01)

    response = api.certify_closure(
        project["id"],
        {"non_endangerment_demonstrated": True, "closure_note": "closure requested"},
        other_reviewer_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_PISC_DURATION_NOT_ELAPSED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_OPEN_REMEDIATION_ORDER.value
    assert response.status_code != 409

    project_after = fixtures.refresh_project(api, project["id"])
    assert project_after["status"] == "PISC"
    assert project_after["closure_status"] == "NOT_REQUESTED"
    assert project_after["closure_certified_by_user_id"] is None
    assert project_after["closure_certified_at"] is None

    instrument_after = fixtures.refresh_instrument(api, ctx["instrument"]["id"])
    assert instrument_after["status"] == "ALLOCATED"
