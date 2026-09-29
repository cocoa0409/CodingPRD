"""Breadth over the state machines: initial states, declared edges and terminal lockdown."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_amount,
    assert_common_fields,
    assert_estimate_totals_consistent,
)
from test_helpers.factories import (
    aerial_survey_payload,
    closure_cost_estimate_payload,
    gas_well_payload,
    host_community_agreement_payload,
    special_waste_approval_payload,
    treatment_agreement_payload,
)
from test_helpers.test_users import TEST_USERS, make_site_operator_headers

CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]
FINANCE_CERTIFIER = TEST_USERS["finance_certifier_headers"]

RESERVE_CELL = {"cell_code": "C-1", "design_airspace_cy": 1000000, "design_area_sf": 120001}
HAULING_ENVELOPE = {
    "facility_name": "Valley POTW",
    "daily_gallon_cap": 20000,
    "base_haul_fee": 350.00,
    "treatment_rate_per_kgal": 62.50,
    "expires_on": "2026-12-31T00:00:00Z",
    "concurrent_slot_capacity": 4,
}
INDUSTRIAL_PROFILE = {
    "generator_name": "Ridgeview Plating Co",
    "waste_code": "IS-4410",
    "profile_stream": "INDUSTRIAL_SPECIAL",
    "approved_tons_cap": 500,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2026-12-31T00:00:00Z",
}


def test_a_new_cell_begins_life_in_design():
    """The client cannot pick a starting state; the machine picks DESIGN.

    PRD: "Cells are created by the site's `SiteOperator`, one per lined footprint area, and a
    new cell begins life in `DESIGN`."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    landfill = fixtures.create_landfill()

    cell = fixtures.create_cell(landfill["id"], **RESERVE_CELL)

    assert cell["status"] == "DESIGN"
    assert_common_fields(cell, expected_version=1)


def test_a_new_special_waste_request_opens_in_requested():
    """An unconsumed, undecided permission slip is where every profile starts.

    PRD: "A new request opens in `REQUESTED` with `consumed_tons` at zero, `decision_reason`
    null and `version` at 1."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    landfill = fixtures.create_landfill()

    data = validate_success(
        api_client.create_special_waste_approval(
            special_waste_approval_payload(landfill["id"], **INDUSTRIAL_PROFILE), ENV_MANAGER
        ),
        201,
    )

    assert data["status"] == "REQUESTED"
    assert_amount(data["consumed_tons"], 0, "consumed tons")
    assert data["decision_reason"] is None
    assert_common_fields(data, expected_version=1)


def test_a_new_treatment_agreement_opens_active_with_an_empty_day():
    """The contract is live from the moment it is registered, with nothing booked.

    PRD: "A new agreement opens in `ACTIVE` with `scheduled_gallons_today` at zero,
    `suspension_reason` null and `version` at 1."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    landfill = fixtures.create_landfill()

    data = validate_success(
        api_client.create_treatment_agreement(
            treatment_agreement_payload(landfill["id"], **HAULING_ENVELOPE), ENV_MANAGER
        ),
        201,
    )

    assert data["status"] == "ACTIVE"
    assert_amount(data["scheduled_gallons_today"], 0, "scheduled gallons today")
    assert data["suspension_reason"] is None
    assert_common_fields(data, expected_version=1)


def test_a_filed_cost_update_opens_in_draft_with_no_instrument():
    """Filing prices the update immediately but posts no money against it.

    PRD: "A filed update opens in `DRAFT` with `instrument_type` null and `version` at 1,
    computes all four of its money fields immediately, and increments the landfill's
    `version` by 1."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    landfill = fixtures.create_landfill()

    data = validate_success(
        api_client.create_closure_cost_estimate(
            closure_cost_estimate_payload(landfill["id"], int(landfill["version"])),
            FINANCE_FILER,
        ),
        201,
    )

    assert data["status"] == "DRAFT"
    assert data["instrument_type"] is None
    assert_common_fields(data, expected_version=1)
    assert_estimate_totals_consistent(data)
    assert int(fixtures.read_landfill(landfill["id"])["version"]) == int(landfill["version"]) + 1


def test_a_drafted_host_agreement_opens_unamended():
    """A fee schedule starts as a draft with no amendment history at all.

    PRD: "A draft opens in `DRAFT` with `amendment_round` at 0, `amendment_reason` and
    `termination_reason` null, and `version` at 1."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    landfill = fixtures.create_landfill()

    data = validate_success(
        api_client.create_host_community_agreement(
            host_community_agreement_payload(landfill["id"]), FINANCE_FILER
        ),
        201,
    )

    assert data["status"] == "DRAFT"
    assert int(data["amendment_round"]) == 0
    assert data["amendment_reason"] is None
    assert data["termination_reason"] is None
    assert_common_fields(data, expected_version=1)


def test_a_newly_flown_survey_opens_in_recorded():
    """The first flight of the site is the recorded one, with nothing to void.

    PRD: "A newly recorded survey opens in `RECORDED` with `void_reason` null and `version`
    at 1, and — because at most one survey per site may be `RECORDED` at any time — the
    site's previously `RECORDED` survey is cascaded `RECORDED → SUPERSEDED` with its
    `version` incremented by 1."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    landfill = fixtures.create_landfill()

    data = validate_success(
        api_client.create_aerial_survey(
            aerial_survey_payload(
                landfill["id"],
                coverage_period_start="2026-05-01T00:00:00Z",
                coverage_period_end="2026-07-31T00:00:00Z",
            ),
            SURVEYOR,
        ),
        201,
    )

    assert data["status"] == "RECORDED"
    assert data["void_reason"] is None
    assert_common_fields(data, expected_version=1)


def test_a_new_gas_well_opens_drilled_with_no_readings():
    """Drilling records the hole; no wellhead reading exists until someone tunes it.

    PRD: "A new well opens in `DRILLED` with `last_vacuum_in_h2o`, `last_methane_pct`,
    `last_oxygen_pct`, `last_tuned_at` and `offline_reason` all null and `version` at 1."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell(landfill["id"], **RESERVE_CELL)

    data = validate_success(
        api_client.create_gas_well(gas_well_payload(cell["id"]), ENV_MANAGER), 201
    )

    assert data["status"] == "DRILLED"
    assert data["last_vacuum_in_h2o"] is None
    assert data["last_methane_pct"] is None
    assert data["last_oxygen_pct"] is None
    assert data["last_tuned_at"] is None
    assert data["offline_reason"] is None
    assert_common_fields(data, expected_version=1)


ASBESTOS_PROFILE = {
    "generator_name": "Harbour Abatement LLC",
    "waste_code": "IS-0002",
    "profile_stream": "ASBESTOS_SPECIAL",
    "approved_tons_cap": 300,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2026-12-31T00:00:00Z",
}
SOIL_PROFILE = {
    "generator_name": "Delta Remediation",
    "waste_code": "IS-0003",
    "profile_stream": "INDUSTRIAL_SPECIAL",
    "approved_tons_cap": 200,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2026-12-31T00:00:00Z",
}


def test_approving_a_request_moves_it_to_approved_and_records_the_reason():
    """The edge out of REQUESTED is chosen by the endpoint, not by the payload.

    PRD: "Approving the profile moves it `REQUESTED → APPROVED`, records the supplied
    `decision_reason`, and increments `version` by 1; the request must still be in
    `REQUESTED` and the owning site must not be `CLOSED`."

    Design: Corner/state_machines/special_waste_approval_reaches_each_declared_target_state
    """
    landfill = fixtures.create_landfill()
    request = fixtures.request_special_waste_approval(landfill["id"], **INDUSTRIAL_PROFILE)

    approved = validate_success(
        api_client.approve_special_waste_approval(
            request["id"], {"decision_reason": "Profile accepted after generator audit"},
            ENV_MANAGER,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["decision_reason"] == "Profile accepted after generator audit"
    assert int(approved["version"]) == 2
    assert_amount(approved["consumed_tons"], 0, "consumed tons")


def test_denying_a_request_stores_the_refusal_rationale():
    """The sibling edge out of the same source state lands on a different target.

    PRD: "Denying it moves it `REQUESTED → DENIED`, which is terminal, storing the supplied
    `decision_reason` as the refusal rationale and incrementing `version` by 1."

    Design: Corner/state_machines/special_waste_approval_reaches_each_declared_target_state
    """
    landfill = fixtures.create_landfill()
    request = fixtures.request_special_waste_approval(landfill["id"], **ASBESTOS_PROFILE)
    reason = "Friable asbestos handling not permitted at this site"

    denied = validate_success(
        api_client.deny_special_waste_approval(
            request["id"], {"decision_reason": reason}, ENV_MANAGER
        )
    )

    assert denied["status"] == "DENIED"
    assert denied["decision_reason"] == reason
    assert int(denied["version"]) == 2


def test_revoking_an_approved_profile_reaches_revoked_through_approved():
    """The revoke edge starts one state further along, so the row lands on version 3.

    PRD: "Revoking an approval — the generator's process changed, or the characterisation
    turned out to be wrong — moves it to `REVOKED`, also terminal, also storing
    `decision_reason` and incrementing `version` by 1; revocation is accepted from
    `APPROVED`, from `SUSPENDED` and from `EXHAUSTED`, so neither a site-wide suspension nor
    an exhausted cap blocks the withdrawal of an approval."

    Design: Corner/state_machines/special_waste_approval_reaches_each_declared_target_state
    """
    landfill = fixtures.create_landfill()
    request = fixtures.request_special_waste_approval(landfill["id"], **SOIL_PROFILE)
    approved = fixtures.approve_special_waste_approval(
        request["id"], "Soil analytics within limits"
    )
    assert approved["status"] == "APPROVED"

    revoked = validate_success(
        api_client.revoke_special_waste_approval(
            request["id"], {"decision_reason": "Generator lost its state permit"},
            ENV_MANAGER,
        )
    )

    assert revoked["status"] == "REVOKED"
    assert revoked["decision_reason"] == "Generator lost its state permit"
    assert int(revoked["version"]) == 3


def test_three_actions_addressed_to_the_wrong_source_state_stop_at_rung_nine():
    """Approve, reinstate and activate all report the same own-state refusal.

    A package that was never opened for review, an agreement that was never suspended and a
    cell still sitting in QA_REVIEW each fail rung 9, so no segregation-of-duties, score or
    funding check may be reported instead, and nothing may move.

    PRD: "9. **Own-state precondition** — on every action endpoint that drives a state
    transition: the addressed resource must currently sit in one of the states declared as a
    source for that action in §3. Failure: `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/transitions_whose_source_state_precondition_fails_are_rejected
    """
    landfill = fixtures.create_landfill()
    site_headers = make_site_operator_headers(landfill["id"])
    cell = fixtures.create_cell_under_construction(landfill["id"], **RESERVE_CELL)
    package = fixtures.submit_liner_qa_package(landfill["id"], cell["id"])
    agreement = fixtures.register_treatment_agreement(landfill["id"], **HAULING_ENVELOPE)

    validate_error(
        api_client.approve_liner_qa_package(
            package["id"], {"certification_reference": "CQA-2026-01"}, CQA_ENGINEER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    validate_error(
        api_client.reinstate_treatment_agreement(agreement["id"], ENV_MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    validate_error(
        api_client.activate_cell(cell["id"], site_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    unchanged_package = get_success_data(
        api_client.get_liner_qa_package(package["id"], CQA_ENGINEER)
    )
    assert unchanged_package["status"] == "SUBMITTED"
    assert unchanged_package["certification_reference"] is None
    unchanged_agreement = get_success_data(
        api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER)
    )
    assert unchanged_agreement["status"] == "ACTIVE"
    assert get_success_data(api_client.get_cell(cell["id"], AGENCY))["status"] == "QA_REVIEW"
    assert int(fixtures.read_landfill(landfill["id"])["active_cell_count"]) == 0


REJECTION_REASON = "Undeclared drum found on the tipping floor"


def _open_day_with_one_received_load():
    """The canonical chain to an OPEN day, plus one PENDING 40-ton MSW truck."""
    site = fixtures.setup_open_day(
        day_overrides={
            "operating_date": "2026-08-01T00:00:00Z",
            "working_face_area_sf": 5000,
            "cover_material_type": "ALTERNATIVE_TARP",
        }
    )
    site["load"] = fixtures.receive_load(
        site["landfill"]["id"], site["day"]["id"], manifest_tons=40.00, hauler_ref="H-1"
    )
    return site


def test_rejecting_a_truck_voids_its_billing_dimension():
    """The screening move drags the independent billing dimension to VOID with it.

    PRD: "On the same request the billing dimension is voided: `billing_status` becomes
    `VOID` and any `gate_charge_amount` already written is reset to null."

    Design: Corner/state_machines/a_rejected_waste_load_cannot_be_cleared_flagged_or_weighed
    """
    site = _open_day_with_one_received_load()

    rejected = fixtures.reject_load(
        site["landfill"]["id"], site["load"]["id"], REJECTION_REASON
    )

    assert rejected["screening_status"] == "REJECTED"
    assert rejected["billing_status"] == "VOID"
    assert rejected["gate_charge_amount"] is None
    assert rejected["screening_state_reason"] == REJECTION_REASON


def test_a_rejected_truck_refuses_clearance_flagging_and_weighing():
    """REJECTED is terminal on the screening dimension, so all three triggers fail.

    PRD: "The load moves to `REJECTED`, terminal on the screening dimension."

    Design: Corner/state_machines/a_rejected_waste_load_cannot_be_cleared_flagged_or_weighed
    """
    site = _open_day_with_one_received_load()
    load_id = site["load"]["id"]
    scale_headers = site["scale_headers"]
    fixtures.reject_load(site["landfill"]["id"], load_id, REJECTION_REASON)

    validate_error(
        api_client.clear_screening(load_id, None, scale_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    validate_error(
        api_client.flag_waste_load(
            load_id, {"screening_state_reason": "Second look"}, scale_headers
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    validate_error(
        api_client.certify_weight(load_id, {"certified_net_tons": 40.00}, scale_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    unchanged = get_success_data(api_client.get_waste_load(load_id, scale_headers))
    assert unchanged["screening_status"] == "REJECTED"
    assert unchanged["billing_status"] == "VOID"
    assert unchanged["certified_net_tons"] is None


def test_a_denied_profile_can_be_neither_approved_nor_revoked():
    """DENIED is outside the revoke edge's otherwise permissive source set.

    PRD: "Revoking an approval — the generator's process changed, or the characterisation
    turned out to be wrong — moves it to `REVOKED`, also terminal, also storing
    `decision_reason` and incrementing `version` by 1; revocation is accepted from
    `APPROVED`, from `SUSPENDED` and from `EXHAUSTED`, so neither a site-wide suspension nor
    an exhausted cap blocks the withdrawal of an approval."

    Design: Corner/state_machines/a_denied_approval_cannot_be_approved_or_revoked_afterwards
    """
    landfill = fixtures.create_landfill()
    request = fixtures.request_special_waste_approval(landfill["id"], **ASBESTOS_PROFILE)
    denied = validate_success(
        api_client.deny_special_waste_approval(
            request["id"], {"decision_reason": "Not permitted"}, ENV_MANAGER
        )
    )
    assert denied["status"] == "DENIED"

    validate_error(
        api_client.approve_special_waste_approval(
            request["id"], {"decision_reason": "Change of heart"}, ENV_MANAGER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    validate_error(
        api_client.revoke_special_waste_approval(
            request["id"], {"decision_reason": "Cleanup"}, ENV_MANAGER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    still_denied = get_success_data(
        api_client.get_special_waste_approval(request["id"], ENV_MANAGER)
    )
    assert still_denied["status"] == "DENIED"
    assert int(still_denied["version"]) == int(denied["version"])


def test_a_revoked_profile_refuses_a_second_revocation():
    """A terminal row cannot be re-entered by replaying the edge that reached it.

    PRD: "9. **Own-state precondition** — on every action endpoint that drives a state
    transition: the addressed resource must currently sit in one of the states declared as a
    source for that action in §3. Failure: `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/a_denied_approval_cannot_be_approved_or_revoked_afterwards
    """
    landfill = fixtures.create_landfill()
    request = fixtures.request_special_waste_approval(landfill["id"], **SOIL_PROFILE)
    fixtures.approve_special_waste_approval(request["id"], "Accepted")
    revoked = validate_success(
        api_client.revoke_special_waste_approval(
            request["id"], {"decision_reason": "Permit lost"}, ENV_MANAGER
        )
    )
    assert revoked["status"] == "REVOKED"

    validate_error(
        api_client.revoke_special_waste_approval(
            request["id"], {"decision_reason": "Again"}, ENV_MANAGER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    still_revoked = get_success_data(
        api_client.get_special_waste_approval(request["id"], ENV_MANAGER)
    )
    assert still_revoked["status"] == "REVOKED"
    assert still_revoked["decision_reason"] == "Permit lost"
    assert int(still_revoked["version"]) == int(revoked["version"])


def _scheduled_haul_of_eight_thousand_gallons():
    """An ACTIVE contract with four slots and one SCHEDULED 8,000-gallon tanker."""
    landfill = fixtures.create_landfill()
    agreement = fixtures.register_treatment_agreement(landfill["id"], **HAULING_ENVELOPE)
    shipment = fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=8000,
        window_start="2026-08-01T08:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    return landfill, agreement, shipment


def test_replaying_dispatch_is_refused_and_keeps_the_first_hauler_reference():
    """The action endpoint is not idempotent: the replay fails and changes nothing.

    PRD: "Dispatch takes it `SCHEDULED → DISPATCHED`, records the tanker's `hauler_ref` and
    increments `version` by 1; the agreement must be `ACTIVE`, else
    `ERR_AGREEMENT_NOT_ACTIVE`, and `scheduled_gallons_today` is unchanged because a
    dispatched shipment still occupies its gallons."

    Design: Corner/state_machines/dispatching_the_same_shipment_twice_is_rejected_on_the_second_call
    """
    landfill, agreement, shipment = _scheduled_haul_of_eight_thousand_gallons()
    site_headers = make_site_operator_headers(landfill["id"])

    dispatched = validate_success(
        api_client.dispatch_leachate_shipment(
            shipment["id"], {"hauler_ref": "TANKER-77"}, site_headers
        )
    )
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["hauler_ref"] == "TANKER-77"
    assert int(dispatched["version"]) == 2

    validate_error(
        api_client.dispatch_leachate_shipment(
            shipment["id"], {"hauler_ref": "TANKER-99"}, site_headers
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    unchanged = get_success_data(
        api_client.get_leachate_shipment(shipment["id"], ENV_MANAGER)
    )
    assert unchanged["hauler_ref"] == "TANKER-77"
    assert int(unchanged["version"]) == 2
    reread = get_success_data(api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 8000, "scheduled gallons today")


def test_replaying_confirm_acceptance_does_not_recompute_the_invoice():
    """Acceptance prices the haul once; the second call is refused outright.

    PRD: "Confirming acceptance takes it `DISPATCHED → ACCEPTED`, writes `invoice_total` from
    the stored `treatment_fee` and `surcharge_pct` per step five, and increments `version` by
    1; again `scheduled_gallons_today` is unchanged, because an accepted shipment remains
    inside the counted set."

    Design: Corner/state_machines/dispatching_the_same_shipment_twice_is_rejected_on_the_second_call
    """
    landfill, agreement, shipment = _scheduled_haul_of_eight_thousand_gallons()
    site_headers = make_site_operator_headers(landfill["id"])
    fixtures.dispatch_shipment(landfill["id"], shipment["id"], hauler_ref="TANKER-77")

    accepted = validate_success(
        api_client.confirm_leachate_acceptance(shipment["id"], site_headers)
    )
    assert accepted["status"] == "ACCEPTED"
    assert_amount(accepted["treatment_fee"], 500.00, "treatment fee")
    assert_amount(accepted["surcharge_pct"], 0.06, "surcharge pct")
    assert_amount(accepted["invoice_total"], 901.00, "invoice total")

    validate_error(
        api_client.confirm_leachate_acceptance(shipment["id"], site_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    unchanged = get_success_data(
        api_client.get_leachate_shipment(shipment["id"], ENV_MANAGER)
    )
    assert unchanged["status"] == "ACCEPTED"
    assert_amount(unchanged["invoice_total"], 901.00, "invoice total after the replay")
    assert int(unchanged["version"]) == int(accepted["version"])
    reread = get_success_data(api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 8000, "scheduled gallons today")


def _certified_estimate_over_one_certified_cell():
    """One QA_CERTIFIED cell of 120,001 sf, and a 2026 estimate certified with no money."""
    landfill = fixtures.create_landfill()
    certified = fixtures.setup_qa_certified_cell(
        landfill["id"], cell_overrides=RESERVE_CELL
    )
    estimate = fixtures.file_closure_estimate(landfill["id"])
    return landfill, certified["cell"], estimate


def test_certifying_with_an_empty_instrument_posts_a_shortfall_review():
    """The whole required amount is outstanding, so the site is not FUNDED.

    PRD: "The site's assurance posture is then set from the recomputed shortfall, and this is
    the one place where a *second consecutive* shortfall escalates: if `funding_shortfall` is
    zero the site's `financial_assurance_status` becomes `FUNDED`; otherwise, if the site was
    already sitting in `SHORTFALL_REVIEW`, its `financial_assurance_status` becomes `LAPSED`
    and its `operating_status` is set to `SUSPENDED_FINANCIAL`; otherwise its
    `financial_assurance_status` becomes `SHORTFALL_REVIEW`."

    Design: Corner/state_machines/fund_assurance_applies_its_whole_declared_side_effect_set
    """
    landfill, cell, estimate = _certified_estimate_over_one_certified_cell()

    certified = fixtures.certify_closure_estimate(estimate["id"])

    assert certified["status"] == "CERTIFIED"
    assert_amount(certified["closure_cost_total"], 222601.86, "closure cost total")
    assert_amount(certified["post_closure_cost_total"], 4519664.50, "post closure cost total")
    assert_amount(certified["required_assurance_amount"], 4742266.36, "required assurance")
    assert_amount(certified["funding_shortfall"], 4742266.36, "funding shortfall")
    assert_estimate_totals_consistent(certified)
    assert fixtures.read_landfill(landfill["id"])["financial_assurance_status"] == (
        "SHORTFALL_REVIEW"
    )
    assert get_success_data(api_client.get_cell(cell["id"], AGENCY))["status"] == "QA_CERTIFIED"


def test_posting_the_instrument_reruns_only_step_four_and_funds_the_site():
    """One call clears the shortfall to zero and flips the site's posture to FUNDED.

    PRD: "The instrument type is stored on the estimate, the landfill's
    `assurance_funded_amount` is set to the supplied `funded_amount`, and **only** step four
    is re-run: `funding_shortfall` is recomputed against the new funded amount while
    `closure_cost_total`, `post_closure_cost_total` and `required_assurance_amount` are left
    exactly as certification left them."

    Design: Corner/state_machines/fund_assurance_applies_its_whole_declared_side_effect_set
    """
    landfill, _cell, estimate = _certified_estimate_over_one_certified_cell()
    certified = fixtures.certify_closure_estimate(estimate["id"])

    funded = validate_success(
        api_client.fund_assurance(
            estimate["id"],
            {"instrument_type": "TRUST_FUND", "funded_amount": 4742266.36},
            FINANCE_CERTIFIER,
        )
    )

    assert funded["instrument_type"] == "TRUST_FUND"
    assert_amount(funded["funding_shortfall"], 0.00, "funding shortfall")
    for field in (
        "closure_cost_total",
        "post_closure_cost_total",
        "required_assurance_amount",
    ):
        assert_amount(funded[field], certified[field], field)
    site = fixtures.read_landfill(landfill["id"])
    assert site["financial_assurance_status"] == "FUNDED"
    assert_amount(site["assurance_funded_amount"], 4742266.36, "assurance funded amount")


def test_qa_approval_leaves_a_draft_estimate_alone_and_the_site_unfunded():
    """Links 1 and 2 fire; with nothing CERTIFIED on file links 3 and 4 are no-ops.

    PRD: "**Link 3**, caused by link 2, and only because the certified-airspace basis
    changed. If the site has a closure cost estimate sitting in `CERTIFIED`, that estimate is
    moved to `STALE` and its `version` is incremented by 1. When the site has no certified
    estimate yet, this link is a no-op."

    Design: Corner/state_machines/qa_approve_skips_cascade_links_three_and_four_when_no_estimate_is_certified
    """
    landfill = fixtures.create_landfill()
    estimate = fixtures.file_closure_estimate(landfill["id"])
    assert estimate["status"] == "DRAFT"
    cell = fixtures.create_cell_under_construction(landfill["id"], **RESERVE_CELL)
    package = fixtures.submit_liner_qa_package(landfill["id"], cell["id"])
    fixtures.begin_liner_review(package["id"])

    approved = fixtures.approve_liner_package(package["id"], "CQA-2026-01")

    assert approved["status"] == "APPROVED"
    assert get_success_data(api_client.get_cell(cell["id"], CQA_ENGINEER))["status"] == (
        "QA_CERTIFIED"
    )
    still_draft = get_success_data(
        api_client.get_closure_cost_estimate(estimate["id"], FINANCE_FILER)
    )
    assert still_draft["status"] == "DRAFT"
    assert int(still_draft["version"]) == int(estimate["version"])
    site = fixtures.read_landfill(landfill["id"])
    assert_amount(site["certified_airspace_cy"], 1000000, "certified airspace")
    assert_amount(site["remaining_life_years"], 3.00, "remaining life years")
    assert site["financial_assurance_status"] == "UNFUNDED"
