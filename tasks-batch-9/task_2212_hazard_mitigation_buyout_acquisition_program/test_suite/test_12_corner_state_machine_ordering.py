"""State machines: operations taken out of order on closings, cases and work orders."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]


# ─── The closing: two different 409s for the same call ────────────────────────

def _record_the_deed(api, state):
    return api.record_closing_deed(
        state["closing"]["id"],
        factories.record_deed_payload(
            state["closing"]["id"],
            recording_reference="BK-1-PG-1",
            maintenance_responsible_party="City of Riverbend Parks",
        ),
        make_subrecipient_coordinator_headers(state["project"]["id"]),
    )


def test_recording_the_deed_before_funding_is_refused_by_the_closing_state_gate(api):
    """The state gate is the binding precondition while the closing is still SCHEDULED.

    "A `SubrecipientCoordinator` records the deed on a closing that must be in
    `FUNDED`, otherwise `ERR_INVALID_CLOSING_STATE`, supplying a
    `recording_reference` and a `maintenance_responsible_party`."

    "State checks, in this order: `ERR_INVALID_PROJECT_STATE`,
    `ERR_PROJECT_NOT_APPROVED`, `ERR_INVALID_BCA_STATE`,
    `ERR_INVALID_APPRAISAL_STATE`, `ERR_INVALID_OFFER_STATE`,
    `ERR_INVALID_CASE_STATE`, `ERR_INVALID_CLOSING_STATE`."

    Design: Corner/state_machines/closing_actions_taken_out_of_order_report_closing_state_then_demolition_incomplete
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.parcel_with_scheduled_closing(api)
    assert state["closing"]["status"] == "SCHEDULED"

    validate_error(
        _record_the_deed(api, state),
        ApiErrorId.ERR_INVALID_CLOSING_STATE.value,
        409,
    )

    closing = validate_success(api.get_closing_record(state["closing"]["id"], ADMIN))
    assert closing["status"] == "SCHEDULED"
    assert closing["recording_reference"] is None


def test_funding_books_the_settlement_item_and_a_second_funding_is_refused(api):
    """One fund call moves three rows; the repeat of it returns to the state gate.

    "Funding moves the closing to `FUNDED`, stamps `funded_at` from the logical
    clock and `funded_by_user_id` with the acting `X-User-ID`, moves the parcel's
    `acquisition_status` from `OFFER_ACCEPTED` to `CLOSED`, recomputes the project's
    `federal_obligated_cents` to include the settlement-cost item."

    "A `ProgramAdministrator` funds a closing that must be in `SCHEDULED`,
    otherwise `ERR_INVALID_CLOSING_STATE`, and whose parcel must be at
    `acquisition_status` `OFFER_ACCEPTED` - a parcel elsewhere on the acquisition
    dimension is likewise refused with `ERR_INVALID_CLOSING_STATE`."

    Design: Corner/state_machines/closing_actions_taken_out_of_order_report_closing_state_then_demolition_incomplete
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.parcel_with_scheduled_closing(api)

    closing = validate_success(
        api.fund_closing_record(state["closing"]["id"], ADMIN)
    )
    assert closing["status"] == "FUNDED"
    assert closing["settlement_cost_cents"] == 400_000

    parcel = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert parcel["acquisition_status"] == "CLOSED"

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["federal_obligated_cents"] == 16_350_000

    validate_error(
        api.fund_closing_record(state["closing"]["id"], ADMIN),
        ApiErrorId.ERR_INVALID_CLOSING_STATE.value,
        409,
    )

    unchanged = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert unchanged["federal_obligated_cents"] == 16_350_000


def test_recording_after_funding_reports_the_physical_progress_gate_instead(api):
    """The identical body now passes the state gate and fails on the parcel's progress.

    "The parcel's `acquisition_status` must be `DEMOLISHED` - the perpetual
    restriction is recorded against cleared land, not against a standing house - and
    any other acquisition state is `ERR_DEMOLITION_NOT_COMPLETE`."

    "There is no create endpoint for a restriction: rows come into existence only
    as the side effect of recording a deed, described in §3.7."

    Design: Corner/state_machines/closing_actions_taken_out_of_order_report_closing_state_then_demolition_incomplete
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.parcel_closed(api)
    assert state["closing"]["status"] == "FUNDED"
    assert state["parcel"]["acquisition_status"] == "CLOSED"

    validate_error(
        _record_the_deed(api, state),
        ApiErrorId.ERR_DEMOLITION_NOT_COMPLETE.value,
        409,
    )

    closing = validate_success(api.get_closing_record(state["closing"]["id"], ADMIN))
    assert closing["status"] == "FUNDED"
    assert closing["recording_reference"] is None

    restrictions, meta = validate_paginated(
        api.list_deed_restrictions(ADMIN, params={"parcel_id": state["parcel"]["id"]})
    )
    assert meta["total_count"] == 0
    assert restrictions == []


# ─── The relocation case: a bad state versus a missing sibling ────────────────

def _case_opened_on_a_parcel_without_any_offer(api):
    project = fixtures.create_draft_project(api, grant_program="FMA")
    parcel = fixtures.create_parcel(
        api, project, apn="APN-SM-CASE-1", site_address="2501 River Rd"
    )
    case = fixtures.open_relocation_case(
        api, parcel["id"], household_reference="HH-SM-CASE-1",
        comparable_dwelling_price_cents=20_600_000,
    )
    return {"project": project, "parcel": parcel, "case": case}


def test_three_of_the_four_case_actions_are_state_illegal_from_opened(api):
    """Claim, resolution and appeal all demand a state the freshly opened case lacks.

    "A `RelocationSpecialist` submits the claim from `ELIGIBILITY_DETERMINED` or
    from `APPEALED`; any other state is `ERR_INVALID_CASE_STATE`."

    "The case must be in `CLAIM_SUBMITTED` or `APPEALED`, otherwise
    `ERR_INVALID_CASE_STATE`."

    "The case must be in `CLAIM_DENIED`, otherwise `ERR_INVALID_CASE_STATE`, and
    `appeal_count` must be **strictly less than** 2, otherwise
    `ERR_APPEAL_LIMIT_REACHED`."

    Design: Corner/state_machines/relocation_case_actions_from_opened_are_refused_and_eligibility_needs_an_accepted_offer
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _case_opened_on_a_parcel_without_any_offer(api)
    specialist = TEST_USERS["relocation_specialist_headers"]

    validate_error(
        api.submit_relocation_claim(state["case"]["id"], specialist),
        ApiErrorId.ERR_INVALID_CASE_STATE.value,
        409,
    )

    validate_error(
        api.resolve_relocation_claim(
            state["case"]["id"],
            factories.resolve_claim_payload(
                state["case"]["id"], "DENY", denial_reason="no claim on file"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_CASE_STATE.value,
        409,
    )

    validate_error(
        api.appeal_relocation_claim(
            state["case"]["id"],
            factories.appeal_payload(
                state["case"]["id"], appeal_basis="nothing to appeal"
            ),
            specialist,
        ),
        ApiErrorId.ERR_INVALID_CASE_STATE.value,
        409,
    )

    case = validate_success(api.get_relocation_case(state["case"]["id"], ADMIN))
    assert case["status"] == "OPENED"
    assert case["appeal_count"] == 0


def test_eligibility_passes_the_state_gate_and_fails_on_the_missing_accepted_offer(api):
    """The fourth action is admitted from OPENED and stops one step later with a 404.

    "A `RelocationSpecialist` determines eligibility on a case that must be in
    `OPENED`, otherwise `ERR_INVALID_CASE_STATE`. Exactly one `PurchaseOffer` on the
    case's parcel must have reached `ACCEPTED`; when no offer on the parcel has
    reached `ACCEPTED` the request is refused with `ERR_OFFER_NOT_FOUND`, because
    there is no acquisition price to compute against."

    "Determination snapshots `acquisition_price_cents` from that accepted offer's
    `net_offer_cents`, computes `rental_assistance_months`,
    `rental_assistance_end_date`, `replacement_housing_payment_cents`,
    `rental_assistance_cents` and `total_relocation_benefit_cents`, moves `status` to
    `ELIGIBILITY_DETERMINED`, and advances the case's `version` by 1."

    Design: Corner/state_machines/relocation_case_actions_from_opened_are_refused_and_eligibility_needs_an_accepted_offer
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _case_opened_on_a_parcel_without_any_offer(api)

    validate_error(
        api.determine_relocation_eligibility(
            state["case"]["id"], TEST_USERS["relocation_specialist_headers"]
        ),
        ApiErrorId.ERR_OFFER_NOT_FOUND.value,
        404,
    )

    case = validate_success(api.get_relocation_case(state["case"]["id"], ADMIN))
    assert case["status"] == "OPENED"
    assert case["acquisition_price_cents"] == 0
    assert case["total_relocation_benefit_cents"] == 0


# ─── The work order and its children: gates keyed on the parent ───────────────

def _issued_work_order_on_a_draft_project(api):
    project = fixtures.create_draft_project(api, grant_program="FMA")
    parcel = fixtures.create_parcel(
        api, project, apn="APN-SM-WO-1", site_address="2601 River Rd",
        occupancy_type="VACANT",
    )
    contractor = fixtures.create_contractor(
        api, name="Riverbend Wrecking", license_no="DEM-1",
        asbestos_certified=True, max_concurrent_work_orders=2,
    )
    work_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"],
        asbestos_survey_status="CLEARED",
        scheduled_start="2026-09-01T08:00:00Z",
        scheduled_end="2026-09-03T17:00:00Z",
    )
    return {
        "project": project,
        "parcel": parcel,
        "contractor": contractor,
        "work_order": work_order,
    }


def test_an_issued_work_order_refuses_start_complete_and_fail_inspection(api):
    """All three demolition verbs need a state the work order has not reached yet.

    "The operation is admitted from `UTILITY_HOLD`, `READY` and
    `FAILED_INSPECTION`; from `ISSUED`, `IN_PROGRESS` or `COMPLETED` it is
    `ERR_INVALID_WORK_ORDER_STATE`."

    "A `SubrecipientCoordinator` completes a work order that must be
    `IN_PROGRESS`, otherwise `ERR_INVALID_WORK_ORDER_STATE`."

    "A `ComplianceMonitor` fails an inspection with an `inspection_note`. The work
    order must be `IN_PROGRESS`, otherwise `ERR_INVALID_WORK_ORDER_STATE`."

    Design: Corner/state_machines/work_order_and_disconnection_actions_outside_their_admissible_parent_states_are_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _issued_work_order_on_a_draft_project(api)
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])
    work_order_id = state["work_order"]["id"]
    assert state["work_order"]["status"] == "ISSUED"

    validate_error(
        api.start_demolition_work_order(work_order_id, coordinator),
        ApiErrorId.ERR_INVALID_WORK_ORDER_STATE.value,
        409,
    )

    validate_error(
        api.complete_demolition_work_order(
            work_order_id,
            factories.complete_work_order_payload(
                work_order_id, total_debris_tons=100.00, recycled_tons=30.00,
                disposal_manifest_no="MAN-1", disposal_facility_type="COMBINED",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_WORK_ORDER_STATE.value,
        409,
    )

    validate_error(
        api.fail_demolition_inspection(
            work_order_id,
            factories.fail_inspection_payload(
                work_order_id, inspection_note="not started yet"
            ),
            TEST_USERS["compliance_monitor_headers"],
        ),
        ApiErrorId.ERR_INVALID_WORK_ORDER_STATE.value,
        409,
    )

    unmoved = validate_success(api.get_demolition_work_order(work_order_id, ADMIN))
    assert unmoved["status"] == "ISSUED"
    assert unmoved["failed_inspection_count"] == 0
    assert unmoved["disposal_manifest_no"] is None


def _mobilized_work_order_with_four_confirmed_children(api):
    state = _issued_work_order_on_a_draft_project(api)
    state["disconnections"] = fixtures.order_all_utility_disconnections(
        api, state["project"], state["work_order"]["id"]
    )
    held = validate_success(
        api.get_demolition_work_order(state["work_order"]["id"], ADMIN)
    )
    assert held["status"] == "UTILITY_HOLD"
    fixtures.confirm_all_utility_disconnections(
        api, state["project"], state["disconnections"]
    )
    ready = validate_success(
        api.get_demolition_work_order(state["work_order"]["id"], ADMIN)
    )
    assert ready["status"] == "READY"
    assert ready["confirmed_utility_types"] == ["WATER", "ELECTRIC", "GAS", "SEWER"]
    state["work_order"] = validate_success(
        api.start_demolition_work_order(
            state["work_order"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    assert state["work_order"]["status"] == "IN_PROGRESS"
    return state


def test_a_mobilized_parent_refuses_a_further_disconnection_being_ordered(api):
    """The child-creation gate reads the parent's status, which has moved past READY.

    "The parent work order must be in `ISSUED`, `UTILITY_HOLD` or `READY`,
    otherwise `ERR_INVALID_WORK_ORDER_STATE`."

    "The parent is `READY` exactly when every `utility_type` listed in
    `required_utility_types` has a child with that `utility_type` in `status`
    `CONFIRMED`, and it cycles back to `UTILITY_HOLD` the moment any of those
    confirmations is revoked."

    "A successful start moves `status` to `IN_PROGRESS` and advances the work
    order's `version` by 1."

    Design: Corner/state_machines/work_order_and_disconnection_actions_outside_their_admissible_parent_states_are_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _mobilized_work_order_with_four_confirmed_children(api)

    validate_error(
        api.create_utility_disconnection(
            state["work_order"]["id"],
            factories.create_utility_disconnection_payload(
                state["work_order"]["id"], "WATER",
                provider_name="Riverbend Water Authority",
            ),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_WORK_ORDER_STATE.value,
        409,
    )

    children, meta = validate_paginated(
        api.list_utility_disconnections(
            ADMIN, params={"work_order_id": state["work_order"]["id"]}
        )
    )
    assert meta["total_count"] == 4
    assert len(children) == 4


def test_resolving_a_legal_child_under_a_mobilized_parent_reports_the_child_error(api):
    """The child's own CONFIRMED status is admissible; the refusal comes from the parent.

    "The gate here sits on the **parent**, not on the child: the parent work order
    must be in `UTILITY_HOLD` or `READY`, otherwise
    `ERR_INVALID_DISCONNECTION_STATE`. The child's own `status` is unconstrained, so
    a `PENDING`, a `CONFIRMED` and a `FAILED` disconnection may all be resolved
    again."

    "Every resolve stamps `resolved_at` from the logical clock, and every `FAILED`
    outcome increments `failed_attempt_count` by 1."

    Design: Corner/state_machines/work_order_and_disconnection_actions_outside_their_admissible_parent_states_are_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _mobilized_work_order_with_four_confirmed_children(api)
    water = state["disconnections"]["WATER"]

    validate_error(
        api.resolve_utility_disconnection(
            water["id"],
            factories.resolve_disconnection_payload(water["id"], "FAILED"),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_DISCONNECTION_STATE.value,
        409,
    )

    child = validate_success(api.get_utility_disconnection(water["id"], ADMIN))
    assert child["status"] == "CONFIRMED"
    assert child["failed_attempt_count"] == 0

    parent = validate_success(
        api.get_demolition_work_order(state["work_order"]["id"], ADMIN)
    )
    assert parent["status"] == "IN_PROGRESS"
    assert parent["confirmed_utility_types"] == ["WATER", "ELECTRIC", "GAS", "SEWER"]
