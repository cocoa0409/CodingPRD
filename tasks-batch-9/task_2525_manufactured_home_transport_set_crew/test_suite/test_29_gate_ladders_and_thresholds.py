"""Gate ladders and inclusive thresholds on the claim, dispatch and set paths.

Each refusal below is staged so that exactly one rule of the priority ladder can
fire, and each clean run that follows a refusal proves the refused request wrote
nothing.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    FINAL_INSPECTOR_USER_ID,
    SITE_INSPECTOR_USER_ID,
    add_route_leg,
    adjudicate_damage_claim,
    adjudicate_damage_claim_payload,
    api_client,
    arrive_leg,
    assert_allocation_sums_exactly,
    assert_network_chargeback_conserved,
    book_set_job,
    certify_anchoring_package,
    create_damage_claim_payload,
    create_route_leg_payload,
    create_set_job_payload,
    current_order_version,
    depart_leg,
    dispute_damage_claim_payload,
    final_inspection_payload,
    inspect_site,
    make_claims_adjuster_headers,
    make_inspector_headers,
    make_network_admin_headers,
    make_permit_desk_headers,
    make_set_crew_lead_headers,
    make_transport_manager_headers,
    measure_and_release_section,
    open_damage_claim,
    open_order,
    pay_and_issue_permit,
    read_damage_claim,
    read_hauler,
    read_order,
    read_order_summary,
    read_plant,
    read_section,
    read_set_crew,
    read_set_job,
    record_marriage_joint,
    record_scope_split,
    record_section,
    record_utility_crossover,
    register_hauler,
    register_plant,
    register_set_crew,
    register_site,
    request_permit,
    reverse_damage_claim,
    review_damage_claim,
    set_logical_clock,
    setup_booked_set_job,
    setup_claim_under_review,
    setup_delivered_order,
    setup_dispatched_set_job,
    setup_job_ready_for_final_inspection,
    setup_order_with_ready_site,
    setup_set_complete_job,
    validate_error,
    validate_paginated,
    validate_success,
)

ADJUSTER_HEADERS = make_claims_adjuster_headers()
ADMIN_HEADERS = make_network_admin_headers()


def _carrier_suspended_at_exactly_the_threshold():
    """Settle one 555,556-cent claim against a carrier, on the stage basis.

    Ninety percent of 555,556 cents rounds half up to 500,000 cents, which is
    exactly the carrier suspension threshold, and the claim is settled before any
    corridor leg exists so nothing is on the road to be held.
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ", "TX"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=1)
    section = record_section(order["id"], plant["id"], section_index=1)
    measure_and_release_section(section["id"], plant["id"])
    permit = request_permit(section["id"], state_code="AZ", planned_leg_count=1)
    claim = open_damage_claim(
        order["id"],
        section["id"],
        hauler["id"],
        set_crew["id"],
        discovered_stage="IN_TRANSIT",
        claimed_amount_cents=555556,
    )
    review_damage_claim(claim["id"])
    claim = adjudicate_damage_claim(claim["id"], allocation_basis="STAGE")
    return {
        "plant": plant,
        "hauler": hauler,
        "set_crew": set_crew,
        "order": order,
        "section": section,
        "permit": permit,
        "claim": claim,
    }


def test_claim_one_cent_above_the_exposure_ceiling_is_refused_but_the_ceiling_is_accepted():
    """PRD §3.9: "`claimed_amount_cents`, the repair amount claimed before any
    haircut, which must be at least 1 cent and must not exceed the network's
    single-claim ceiling of twenty-five thousand dollars (2,500,000 cents) — a
    claim above the ceiling is refused with `ERR_CLAIM_AMOUNT_EXCEEDS_CAP`."
    PRD §2.10 priority 30: "the claimed amount does not exceed the network's
    single-claim exposure ceiling."  PRD §3.9 also pins the opening row: "A new
    claim opens at `status` `SUBMITTED` with `dispute_round` at 0,
    `allocation_basis` and `approved_amount_cents` null, and
    `plant_charge_cents`, `hauler_charge_cents` and `installer_charge_cents` all
    at 0."

    Design: Corner/errors/claim_cap_stage_and_evidence_errors_then_a_clean_evidence_adjudication
    """
    scenario = setup_delivered_order(section_count=1)
    set_crew = register_set_crew()
    order_id = scenario["order"]["id"]
    section_id = scenario["sections"][0]["id"]
    hauler_id = scenario["hauler"]["id"]

    over_ceiling = api_client.create_damage_claim(
        create_damage_claim_payload(
            order_id,
            section_id,
            hauler_id,
            set_crew["id"],
            discovered_stage="IN_TRANSIT",
            claimed_amount_cents=2500001,
        ),
        ADJUSTER_HEADERS,
    )
    validate_error(over_ceiling, ApiErrorId.ERR_CLAIM_AMOUNT_EXCEEDS_CAP, 422)

    at_ceiling = validate_success(
        api_client.create_damage_claim(
            create_damage_claim_payload(
                order_id,
                section_id,
                hauler_id,
                set_crew["id"],
                discovered_stage="IN_TRANSIT",
                claimed_amount_cents=2500000,
            ),
            ADJUSTER_HEADERS,
        ),
        201,
    )
    assert at_ceiling["claimed_amount_cents"] == 2500000, (
        "a claim sitting exactly on the 2,500,000-cent ceiling is accepted, got "
        f"{at_ceiling['claimed_amount_cents']}"
    )
    assert at_ceiling["status"] == "SUBMITTED", (
        f"a new claim opens SUBMITTED, got {at_ceiling['status']}"
    )
    assert at_ceiling["dispute_round"] == 0, (
        f"a new claim opens at dispute_round 0, got {at_ceiling['dispute_round']}"
    )
    assert at_ceiling["allocation_basis"] is None, (
        f"allocation_basis is null before adjudication, got {at_ceiling['allocation_basis']}"
    )
    assert at_ceiling["approved_amount_cents"] is None, (
        "approved_amount_cents is null before adjudication, got "
        f"{at_ceiling['approved_amount_cents']}"
    )
    for charge in ("plant_charge_cents", "hauler_charge_cents", "installer_charge_cents"):
        assert at_ceiling[charge] == 0, f"{charge} opens at 0, got {at_ceiling[charge]}"


def test_stage_adjudication_of_a_claim_of_unknown_origin_is_refused():
    """PRD §3.9: "A `discovered_stage` of `UNKNOWN` has deliberately **no**
    owning party, so a stage-based adjudication of such a claim is refused with
    `ERR_CLAIM_STAGE_MISMATCH`; a claim whose origin could not be established can
    only be settled on the evidence basis."

    Design: Corner/errors/claim_cap_stage_and_evidence_errors_then_a_clean_evidence_adjudication
    """
    scenario = setup_claim_under_review(
        claimed_amount_cents=2500000, discovered_stage="UNKNOWN"
    )
    claim_id = scenario["claim"]["id"]

    refusal = api_client.adjudicate_damage_claim(
        claim_id, adjudicate_damage_claim_payload("STAGE"), ADJUSTER_HEADERS
    )
    validate_error(refusal, ApiErrorId.ERR_CLAIM_STAGE_MISMATCH, 422)

    claim = read_damage_claim(claim_id)
    assert claim["status"] == "UNDER_REVIEW", (
        f"a refused adjudication leaves the claim UNDER_REVIEW, got {claim['status']}"
    )
    assert claim["approved_amount_cents"] is None, (
        "a refused adjudication computes no approved amount, got "
        f"{claim['approved_amount_cents']}"
    )
    assert claim["allocation_basis"] is None, (
        f"a refused adjudication posts no basis, got {claim['allocation_basis']}"
    )
    hauler = read_hauler(scenario["hauler"]["id"])
    assert hauler["chargeback_balance_cents"] == 0, (
        "a refused adjudication posts no chargeback, got "
        f"{hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "ACTIVE", (
        f"the carrier is untouched by a refused adjudication, got {hauler['status']}"
    )


def test_evidence_adjudication_with_no_scored_evidence_is_refused():
    """PRD §3.9: "The three point fields must sum to at least 1, since that sum
    is the divisor; a sum of zero is refused with `ERR_CLAIM_EVIDENCE_MISSING`."

    Design: Corner/errors/claim_cap_stage_and_evidence_errors_then_a_clean_evidence_adjudication
    """
    scenario = setup_claim_under_review(
        claimed_amount_cents=2500000,
        discovered_stage="UNKNOWN",
        claim_overrides={
            "plant_evidence_points": 0,
            "hauler_evidence_points": 0,
            "installer_evidence_points": 0,
        },
    )
    claim_id = scenario["claim"]["id"]

    refusal = api_client.adjudicate_damage_claim(
        claim_id, adjudicate_damage_claim_payload("EVIDENCE"), ADJUSTER_HEADERS
    )
    validate_error(refusal, ApiErrorId.ERR_CLAIM_EVIDENCE_MISSING, 422)

    claim = read_damage_claim(claim_id)
    assert claim["status"] == "UNDER_REVIEW", (
        f"an unscored evidence split leaves the claim UNDER_REVIEW, got {claim['status']}"
    )
    assert claim["approved_amount_cents"] is None, (
        "no approved amount is computed when the divisor would be zero, got "
        f"{claim['approved_amount_cents']}"
    )
    for charge in ("plant_charge_cents", "hauler_charge_cents", "installer_charge_cents"):
        assert claim[charge] == 0, f"{charge} stays 0 after the refusal, got {claim[charge]}"


def test_a_disputed_re_score_drives_the_evidence_split_onto_the_scored_party():
    """PRD §3.9: "The pushback carries a `reason_code` and may simultaneously
    re-score `plant_evidence_points`, `hauler_evidence_points` and
    `installer_evidence_points`, which changes the eventual evidence-based split;
    it moves the claim `UNDER_REVIEW → DISPUTED` and increments `dispute_round` by
    1."  PRD §3.9: "Whichever basis is chosen, the approved amount is computed the
    same way: the claimed amount less a ten percent approval haircut — that is,
    ninety percent of `claimed_amount_cents`, rounded half up to whole cents — and
    stored as `approved_amount_cents`."  PRD §3.9: "Each party's exact share is
    the approved amount multiplied by that party's points and divided by the total
    points, kept as an unrounded rational value."  PRD §3.1: "once the carrier's
    chargeback balance reaches five thousand dollars — at or above 500,000 cents —
    the carrier's `status` becomes `SUSPENDED`".

    Design: Corner/errors/claim_cap_stage_and_evidence_errors_then_a_clean_evidence_adjudication
    """
    scenario = setup_claim_under_review(
        claimed_amount_cents=2500000,
        discovered_stage="UNKNOWN",
        claim_overrides={
            "plant_evidence_points": 0,
            "hauler_evidence_points": 0,
            "installer_evidence_points": 0,
        },
    )
    claim_id = scenario["claim"]["id"]
    hauler_id = scenario["hauler"]["id"]

    disputed = validate_success(
        api_client.dispute_damage_claim(
            claim_id,
            dispute_damage_claim_payload(
                plant_evidence_points=0,
                hauler_evidence_points=3,
                installer_evidence_points=0,
            ),
            make_transport_manager_headers(hauler_id),
        )
    )
    assert disputed["status"] == "DISPUTED", (
        f"the carrier's pushback moves the claim to DISPUTED, got {disputed['status']}"
    )
    assert disputed["dispute_round"] == 1, (
        f"the pushback increments dispute_round to 1, got {disputed['dispute_round']}"
    )
    assert disputed["hauler_evidence_points"] == 3, (
        "the pushback re-scores the carrier's evidence points to 3, got "
        f"{disputed['hauler_evidence_points']}"
    )

    reviewed = review_damage_claim(claim_id)
    assert reviewed["status"] == "UNDER_REVIEW", (
        f"the adjuster's review re-entry closes the cycle, got {reviewed['status']}"
    )

    settled = validate_success(
        api_client.adjudicate_damage_claim(
            claim_id, adjudicate_damage_claim_payload("EVIDENCE"), ADJUSTER_HEADERS
        )
    )
    assert settled["status"] == "ADJUDICATED", (
        f"the settlement moves the claim to ADJUDICATED, got {settled['status']}"
    )
    assert settled["allocation_basis"] == "EVIDENCE", (
        f"the settlement records the EVIDENCE basis, got {settled['allocation_basis']}"
    )
    assert settled["approved_amount_cents"] == 2250000, (
        "ninety percent of 2,500,000 cents is 2,250,000 cents, got "
        f"{settled['approved_amount_cents']}"
    )
    assert settled["hauler_charge_cents"] == 2250000, (
        "the only party holding evidence points takes the whole approved amount, got "
        f"{settled['hauler_charge_cents']}"
    )
    assert settled["plant_charge_cents"] == 0, (
        f"the plant scored no points, got {settled['plant_charge_cents']}"
    )
    assert settled["installer_charge_cents"] == 0, (
        f"the installer scored no points, got {settled['installer_charge_cents']}"
    )
    assert_allocation_sums_exactly(settled)

    hauler = read_hauler(hauler_id)
    assert hauler["chargeback_balance_cents"] == 2250000, (
        "the carrier's balance is the sum of hauler_charge_cents over its adjudicated "
        f"claims, got {hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "SUSPENDED", (
        f"a balance at or above 500,000 cents suspends the carrier, got {hauler['status']}"
    )
    plant = read_plant(scenario["plant"]["id"])
    assert plant["chargeback_balance_cents"] == 0, (
        f"the plant is charged nothing, got {plant['chargeback_balance_cents']}"
    )
    installer = read_set_crew(scenario["set_crew"]["id"])
    assert installer["chargeback_balance_cents"] == 0, (
        f"the installer is charged nothing, got {installer['chargeback_balance_cents']}"
    )
    assert_network_chargeback_conserved(
        read_order_summary(scenario["order"]["id"]), 2250000
    )


def test_the_site_readiness_signer_may_not_also_sign_the_final_inspection():
    """PRD §2.10 priority 15: "the acting `X-User-ID` differs from the
    `last_inspector_user_id` recorded on the order's site."  PRD §3.8: "the acting
    `X-User-ID` must differ from the `last_inspector_user_id` stamped on the
    order's site, because whoever signed the site-readiness verdict may not also
    sign the final inspection (`ERR_SEGREGATION_OF_DUTIES`)".

    Design: Corner/errors/final_inspection_gate_ladder_sod_anchor_scope_then_crossover
    """
    scenario = setup_job_ready_for_final_inspection()
    job_id = scenario["set_job"]["id"]
    assert scenario["site"]["last_inspector_user_id"] == SITE_INSPECTOR_USER_ID, (
        "the readiness verdict stamps its signer onto the site, got "
        f"{scenario['site']['last_inspector_user_id']}"
    )

    refusal = api_client.final_inspection(
        job_id,
        final_inspection_payload(punch_item_count=0),
        make_inspector_headers(SITE_INSPECTOR_USER_ID),
    )
    validate_error(refusal, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)

    job = read_set_job(job_id)
    assert job["final_result"] == "PENDING", (
        f"a refused inspection leaves final_result PENDING, got {job['final_result']}"
    )
    assert job["progress_status"] == "SET_COMPLETE", (
        f"a refused inspection closes nothing, got {job['progress_status']}"
    )
    assert job["invoice_total_cents"] is None, (
        f"a refused inspection assembles no invoice, got {job['invoice_total_cents']}"
    )
    order = read_order(scenario["order"]["id"])
    assert order["warranty_start_date"] is None, (
        f"a refused inspection starts no warranty, got {order['warranty_start_date']}"
    )


def test_final_inspection_without_a_certified_anchoring_package_is_refused():
    """PRD §2.10 priority 18: "an anchoring certification in status `CERTIFIED`
    exists for the set job. Applies to
    `POST /installations/set-jobs/{id}/final-inspection`. Violation:
    `ERR_ANCHOR_NOT_CERTIFIED` (422)."

    Design: Corner/errors/final_inspection_gate_ladder_sod_anchor_scope_then_crossover
    """
    scenario = setup_set_complete_job(section_count=1)
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]
    record_scope_split(job_id, crew_id)
    record_utility_crossover(job_id, crew_id, crossover_count=1)

    staged = read_set_job(job_id)
    assert staged["scope_status"] == "SCOPE_DELIVERED", (
        f"the scope gate is satisfied before the anchor gate is tested, got "
        f"{staged['scope_status']}"
    )
    assert staged["crossover_recorded"] is True, (
        f"the crossover gate is satisfied too, got {staged['crossover_recorded']}"
    )

    refusal = api_client.final_inspection(
        job_id,
        final_inspection_payload(punch_item_count=0),
        make_inspector_headers(FINAL_INSPECTOR_USER_ID),
    )
    validate_error(refusal, ApiErrorId.ERR_ANCHOR_NOT_CERTIFIED, 422)

    job = read_set_job(job_id)
    assert job["final_result"] == "PENDING", (
        f"an uncertified home cannot be signed off, got {job['final_result']}"
    )
    assert job["progress_status"] == "SET_COMPLETE", (
        f"the job stays SET_COMPLETE, got {job['progress_status']}"
    )


def test_final_inspection_before_the_scope_split_is_refused():
    """PRD §2.10 priority 20: "the set job's `scope_status` is `SCOPE_DELIVERED`,
    which is reachable only by passing through `SCOPE_SPLIT`, and its
    `crossover_recorded` flag is true. Applies to
    `POST /installations/set-jobs/{id}/final-inspection`. Violation:
    `ERR_SCOPE_SPLIT_INCOMPLETE` when the scope split has not been recorded,
    `ERR_UTILITY_CROSSOVER_INCOMPLETE` when the crossover has not been recorded
    (both 422)."

    Design: Corner/errors/final_inspection_gate_ladder_sod_anchor_scope_then_crossover
    """
    scenario = setup_set_complete_job(section_count=1)
    job_id = scenario["set_job"]["id"]
    certify_anchoring_package(job_id, scenario["set_crew"]["id"], section_count=1)

    staged = read_set_job(job_id)
    assert staged["scope_status"] == "SCOPE_PENDING", (
        f"the scope dimension is untouched, got {staged['scope_status']}"
    )

    refusal = api_client.final_inspection(
        job_id,
        final_inspection_payload(punch_item_count=0),
        make_inspector_headers(FINAL_INSPECTOR_USER_ID),
    )
    validate_error(refusal, ApiErrorId.ERR_SCOPE_SPLIT_INCOMPLETE, 422)

    job = read_set_job(job_id)
    assert job["final_result"] == "PENDING", (
        f"an unsplit scope cannot be signed off, got {job['final_result']}"
    )
    assert job["invoice_total_cents"] is None, (
        f"no invoice is assembled, got {job['invoice_total_cents']}"
    )


def test_final_inspection_before_the_utility_crossover_is_refused():
    """PRD §3.8: "the scope work must be complete, meaning `scope_status` has
    reached `SCOPE_DELIVERED` (`ERR_SCOPE_SPLIT_INCOMPLETE` when it is still
    `SCOPE_PENDING`) and `crossover_recorded` is true
    (`ERR_UTILITY_CROSSOVER_INCOMPLETE` when it is not)."  PRD §3.7: "The step
    also sets `crossover_recorded` to true, and that boolean rather than the count
    is what the final-inspection gate reads — a genuine single-wide with zero
    crossovers must be distinguishable from a job whose crossover step was simply
    never performed."

    Design: Corner/errors/final_inspection_gate_ladder_sod_anchor_scope_then_crossover
    """
    scenario = setup_set_complete_job(section_count=1)
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]
    record_scope_split(job_id, crew_id)
    certify_anchoring_package(job_id, crew_id, section_count=1)

    staged = read_set_job(job_id)
    assert staged["scope_status"] == "SCOPE_SPLIT", (
        f"the split is recorded but the crossover is not, got {staged['scope_status']}"
    )
    assert staged["crossover_recorded"] is False, (
        f"crossover_recorded is still false, got {staged['crossover_recorded']}"
    )

    refusal = api_client.final_inspection(
        job_id,
        final_inspection_payload(punch_item_count=0),
        make_inspector_headers(FINAL_INSPECTOR_USER_ID),
    )
    validate_error(refusal, ApiErrorId.ERR_UTILITY_CROSSOVER_INCOMPLETE, 422)

    job = read_set_job(job_id)
    assert job["final_result"] == "PENDING", (
        f"an unfinished crossover cannot be signed off, got {job['final_result']}"
    )
    assert job["progress_status"] == "SET_COMPLETE", (
        f"the job stays SET_COMPLETE, got {job['progress_status']}"
    )


def test_a_punch_list_verdict_leaves_the_job_reinspectable_and_starts_no_warranty():
    """PRD §3.8: "When `punch_item_count` is 1 or greater, the job's
    `progress_status` stays at `SET_COMPLETE` — the row is re-inspectable —
    `final_result` is set to `PUNCH_LIST`, the acting `X-User-ID` is still stored
    in `final_inspector_user_id`, but `invoice_total_cents` remains null and the
    order's `warranty_start_date` remains null: no invoice is assembled and no
    warranty starts."

    Design: Corner/errors/final_inspection_gate_ladder_sod_anchor_scope_then_crossover
    """
    scenario = setup_job_ready_for_final_inspection(
        labor_base_cents=500000,
        scope_overrides={
            "skirting_owner": "INSTALLER",
            "steps_owner": "DEALER",
            "skirting_linear_ft": 20,
            "steps_count": 1,
        },
        crossover_count=1,
    )
    job_id = scenario["set_job"]["id"]

    verdict = validate_success(
        api_client.final_inspection(
            job_id,
            final_inspection_payload(punch_item_count=2),
            make_inspector_headers(FINAL_INSPECTOR_USER_ID),
        )
    )
    assert verdict["final_result"] == "PUNCH_LIST", (
        f"two outstanding punch items yield PUNCH_LIST, got {verdict['final_result']}"
    )
    assert verdict["progress_status"] == "SET_COMPLETE", (
        f"the punched job stays re-inspectable at SET_COMPLETE, got {verdict['progress_status']}"
    )
    assert verdict["final_inspector_user_id"] == FINAL_INSPECTOR_USER_ID, (
        "the signing inspector is stored even on the punch branch, got "
        f"{verdict['final_inspector_user_id']}"
    )
    assert verdict["invoice_total_cents"] is None, (
        f"no invoice is assembled on the punch branch, got {verdict['invoice_total_cents']}"
    )

    order = read_order(scenario["order"]["id"])
    assert order["warranty_start_date"] is None, (
        f"no warranty starts on the punch branch, got {order['warranty_start_date']}"
    )
    assert order["invoice_total_cents"] is None, (
        f"nothing is mirrored onto the order, got {order['invoice_total_cents']}"
    )


def test_a_clean_reinspection_closes_the_job_and_assembles_the_discounted_invoice():
    """PRD §3.8: "When `punch_item_count` is 0, the job's `progress_status` moves
    `SET_COMPLETE → CLOSED`, `final_result` is set to `PASS`, the acting
    `X-User-ID` is stored in `final_inspector_user_id`, the invoice is assembled
    into `invoice_total_cents` and mirrored onto the order's own
    `invoice_total_cents`, the order's `warranty_start_date` is set to the logical
    clock's current UTC date, and the order's posture is re-derived and lands on
    `CLOSED`."  PRD §3.8: "Third, the crossover line is waived: the billed
    crossover amount is zero whenever any discount applies, and equal to
    `crossover_fee_cents` when the discount is zero."  PRD §3.8: "Fifth, the volume
    discount in cents is the discount percentage applied to the **pre-discount
    total from the first step** — never to the billable base — rounded half up to
    whole cents."

    Design: Corner/errors/final_inspection_gate_ladder_sod_anchor_scope_then_crossover
    """
    scenario = setup_job_ready_for_final_inspection(
        labor_base_cents=500000,
        scope_overrides={
            "skirting_owner": "INSTALLER",
            "steps_owner": "DEALER",
            "skirting_linear_ft": 20,
            "steps_count": 1,
        },
        crossover_count=1,
    )
    job_id = scenario["set_job"]["id"]
    order_id = scenario["order"]["id"]

    validate_success(
        api_client.final_inspection(
            job_id,
            final_inspection_payload(punch_item_count=2),
            make_inspector_headers(FINAL_INSPECTOR_USER_ID),
        )
    )

    closed = validate_success(
        api_client.final_inspection(
            job_id,
            final_inspection_payload(punch_item_count=0),
            make_inspector_headers(FINAL_INSPECTOR_USER_ID),
        )
    )
    assert closed["final_result"] == "PASS", (
        f"a clean walk yields PASS, got {closed['final_result']}"
    )
    assert closed["progress_status"] == "CLOSED", (
        f"the passing branch closes the job, got {closed['progress_status']}"
    )
    assert closed["skirting_fee_cents"] == 37000, (
        "twenty linear feet at 1,850 cents per foot is 37,000 cents, got "
        f"{closed['skirting_fee_cents']}"
    )
    assert closed["steps_fee_cents"] == 0, (
        f"the dealer owns the steps, so the line is zero, got {closed['steps_fee_cents']}"
    )
    assert closed["crossover_fee_cents"] == 78000, (
        "60,000 cents of mobilisation plus 18,000 cents for one crossover is 78,000 "
        f"cents, got {closed['crossover_fee_cents']}"
    )
    assert closed["invoice_total_cents"] == 500100, (
        "a pre-discount total of 615,000 cents takes the six percent tier, waives the "
        "78,000-cent crossover line and subtracts 36,900 cents from a 537,000-cent "
        f"billable base, got {closed['invoice_total_cents']}"
    )

    order = read_order(order_id)
    assert order["invoice_total_cents"] == 500100, (
        f"the invoice is mirrored onto the order, got {order['invoice_total_cents']}"
    )
    assert order["warranty_start_date"] == "2026-08-01", (
        "the warranty starts on the logical clock's current UTC date, got "
        f"{order['warranty_start_date']}"
    )
    assert order["posture"] == "CLOSED", (
        f"the order's posture is re-derived to CLOSED, got {order['posture']}"
    )


def test_a_booking_whose_end_date_precedes_its_start_date_is_refused():
    """PRD §3.6: "An end date earlier than the start date is refused with
    `ERR_INVALID_WINDOW`."  PRD §2.10 priority 21: "interval well-formedness:
    `window_end` is strictly after `window_start`, and `scheduled_end_date` falls
    on or after `scheduled_start_date`."

    Design: Corner/errors/dispatch_gate_rejects_count_mismatch_then_undelivered_sections
    """
    scenario = setup_order_with_ready_site(section_count=1)
    order_id = scenario["order"]["id"]
    set_crew = register_set_crew()

    refusal = api_client.create_set_job(
        create_set_job_payload(
            order_id,
            set_crew["id"],
            current_order_version(order_id),
            scheduled_start_date="2026-08-11",
            scheduled_end_date="2026-08-10",
        ),
        ADMIN_HEADERS,
    )
    validate_error(refusal, ApiErrorId.ERR_INVALID_WINDOW, 422)

    single_day = validate_success(
        api_client.create_set_job(
            create_set_job_payload(
                order_id,
                set_crew["id"],
                current_order_version(order_id),
                scheduled_start_date="2026-08-10",
                scheduled_end_date="2026-08-10",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert single_day["scheduled_start_date"] == "2026-08-10", (
        f"the accepted booking keeps its start date, got {single_day['scheduled_start_date']}"
    )
    assert single_day["scheduled_end_date"] == "2026-08-10", (
        "an end date falling on the start date is well formed, got "
        f"{single_day['scheduled_end_date']}"
    )
    assert single_day["progress_status"] == "SCHEDULED", (
        f"a new set job opens SCHEDULED, got {single_day['progress_status']}"
    )


def test_dispatch_is_refused_while_fewer_floors_are_recorded_than_the_order_declares():
    """PRD §3.6: "The number of home sections recorded on the order equals the
    order's declared `section_count`, failing which the refusal is
    `ERR_SECTION_COUNT_MISMATCH`."

    Design: Corner/errors/dispatch_gate_rejects_count_mismatch_then_undelivered_sections
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=2)
    section = record_section(order["id"], plant["id"], section_index=1)
    measure_and_release_section(section["id"], plant["id"])
    permit = request_permit(section["id"], state_code="AZ", planned_leg_count=1)
    leg = add_route_leg(permit["id"], hauler["id"], sequence_no=1)
    pay_and_issue_permit(permit["id"], hauler["id"])
    depart_leg(leg["id"], hauler["id"])
    arrive_leg(leg["id"], hauler["id"])
    site = register_site(order["id"], pad_type="RUNNER", pier_count=12)
    ready_site = inspect_site(site["id"])
    assert ready_site["readiness_status"] == "READY", (
        f"the site gate must pass so the count gate is the one tested, got "
        f"{ready_site['readiness_status']}"
    )
    assert read_section(section["id"])["transit_status"] == "DELIVERED", (
        "the only recorded floor is on the pad, so the delivery gate is satisfied"
    )
    job = book_set_job(order["id"], set_crew["id"])

    refusal = api_client.dispatch_set_job(job["id"], {}, ADMIN_HEADERS)
    validate_error(refusal, ApiErrorId.ERR_SECTION_COUNT_MISMATCH, 422)

    assert read_set_job(job["id"])["progress_status"] == "SCHEDULED", (
        "a refused dispatch leaves the progress dimension at SCHEDULED"
    )


def test_dispatch_is_refused_while_one_recorded_floor_is_still_at_the_plant():
    """PRD §3.6: "And every one of those home sections has `transit_status`
    `DELIVERED`, failing which the refusal is `ERR_SECTIONS_NOT_DELIVERED` — no
    crew is sent to set a home whose floors are not all on the pad."

    Design: Corner/errors/dispatch_gate_rejects_count_mismatch_then_undelivered_sections
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=2)
    delivered = record_section(order["id"], plant["id"], section_index=1)
    measure_and_release_section(delivered["id"], plant["id"])
    permit = request_permit(delivered["id"], state_code="AZ", planned_leg_count=1)
    leg = add_route_leg(permit["id"], hauler["id"], sequence_no=1)
    pay_and_issue_permit(permit["id"], hauler["id"])
    depart_leg(leg["id"], hauler["id"])
    arrive_leg(leg["id"], hauler["id"])
    still_at_plant = record_section(order["id"], plant["id"], section_index=2)
    site = register_site(order["id"], pad_type="RUNNER", pier_count=12)
    ready_site = inspect_site(site["id"])
    assert ready_site["readiness_status"] == "READY", (
        f"the site gate must pass, got {ready_site['readiness_status']}"
    )
    assert read_section(delivered["id"])["transit_status"] == "DELIVERED", (
        "the first floor reached the pad"
    )
    assert read_section(still_at_plant["id"])["transit_status"] == "AT_PLANT", (
        "the second floor has not left the plant, got "
        f"{read_section(still_at_plant['id'])['transit_status']}"
    )
    job = book_set_job(order["id"], set_crew["id"])

    refusal = api_client.dispatch_set_job(job["id"], {}, ADMIN_HEADERS)
    validate_error(refusal, ApiErrorId.ERR_SECTIONS_NOT_DELIVERED, 422)

    assert read_set_job(job["id"])["progress_status"] == "SCHEDULED", (
        "a refused dispatch leaves the progress dimension at SCHEDULED"
    )


def test_a_blocking_claim_holds_the_floor_and_freezes_the_dispatch():
    """PRD §3.9: "When `blocks_set` is true the named floor is held: it moves
    `IN_TRANSIT → DAMAGED_HOLD` or `DELIVERED → DAMAGED_HOLD`, both the floor's
    and the order's `version` rise, and the order's posture is re-derived and lands
    on `TRANSPORT_BLOCKED`, freezing downstream set work."  PRD §2.8: "A dispatch
    attempt against an order whose posture is `TRANSPORT_BLOCKED` or `CLOSED` is
    rejected with `ERR_ORDER_POSTURE_BLOCKED`".

    Design: Corner/errors/posture_block_then_failing_marriage_line_verdict
    """
    scenario = setup_booked_set_job(section_count=2)
    order_id = scenario["order"]["id"]
    job_id = scenario["set_job"]["id"]
    held_section_id = scenario["sections"][0]["id"]

    open_damage_claim(
        order_id,
        held_section_id,
        scenario["hauler"]["id"],
        scenario["set_crew"]["id"],
        discovered_stage="IN_TRANSIT",
        claimed_amount_cents=100000,
        blocks_set=True,
    )

    assert read_section(held_section_id)["transit_status"] == "DAMAGED_HOLD", (
        "a blocking claim moves the delivered floor to DAMAGED_HOLD, got "
        f"{read_section(held_section_id)['transit_status']}"
    )
    assert read_order(order_id)["posture"] == "TRANSPORT_BLOCKED", (
        f"the held floor drives the posture to TRANSPORT_BLOCKED, got "
        f"{read_order(order_id)['posture']}"
    )
    assert scenario["site"]["readiness_status"] == "READY", (
        "the site gate still passes, so the posture gate is the one under test"
    )

    refusal = api_client.dispatch_set_job(job_id, {}, ADMIN_HEADERS)
    validate_error(refusal, ApiErrorId.ERR_ORDER_POSTURE_BLOCKED, 409)

    assert read_set_job(job_id)["progress_status"] == "SCHEDULED", (
        "a blocked dispatch leaves the job at SCHEDULED"
    )


def test_settling_the_blocking_claim_releases_the_floor_and_clears_the_dispatch():
    """PRD §3.9: "The floor is released — moving `DAMAGED_HOLD → DELIVERED` — as
    soon as no blocking claim naming that floor remains in `SUBMITTED`,
    `UNDER_REVIEW` or `DISPUTED`, which in practice means when the last such claim
    is adjudicated or reversed."  PRD §3.9: "Under the `STAGE` basis, the entire
    approved amount is charged to the single party that owns the stage at which the
    damage was discovered, and the other two charges stay at 0; evidence points are
    ignored completely."  PRD §3.6: "On success the job's `version` rises, the
    order's posture is re-derived and lands on `SET_IN_PROGRESS`, and the job's
    scope dimension is left byte-identical."

    Design: Corner/errors/posture_block_then_failing_marriage_line_verdict
    """
    scenario = setup_booked_set_job(section_count=2)
    order_id = scenario["order"]["id"]
    job_id = scenario["set_job"]["id"]
    held_section_id = scenario["sections"][0]["id"]
    hauler_id = scenario["hauler"]["id"]

    claim = open_damage_claim(
        order_id,
        held_section_id,
        hauler_id,
        scenario["set_crew"]["id"],
        discovered_stage="IN_TRANSIT",
        claimed_amount_cents=100000,
        blocks_set=True,
    )
    review_damage_claim(claim["id"])
    settled = adjudicate_damage_claim(claim["id"], allocation_basis="STAGE")

    assert settled["approved_amount_cents"] == 90000, (
        "ninety percent of 100,000 cents is 90,000 cents, got "
        f"{settled['approved_amount_cents']}"
    )
    assert settled["hauler_charge_cents"] == 90000, (
        f"damage found in transit belongs to the carrier, got {settled['hauler_charge_cents']}"
    )
    assert settled["plant_charge_cents"] == 0, (
        f"the plant is not charged on the stage basis, got {settled['plant_charge_cents']}"
    )
    assert settled["installer_charge_cents"] == 0, (
        "the installer is not charged on the stage basis, got "
        f"{settled['installer_charge_cents']}"
    )
    hauler = read_hauler(hauler_id)
    assert hauler["chargeback_balance_cents"] == 90000, (
        f"the carrier carries the 90,000-cent charge, got {hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "ACTIVE", (
        f"90,000 cents is far below the suspension line, got {hauler['status']}"
    )
    assert read_section(held_section_id)["transit_status"] == "DELIVERED", (
        "settling the last blocking claim releases the floor back to DELIVERED, got "
        f"{read_section(held_section_id)['transit_status']}"
    )
    assert read_order(order_id)["posture"] == "OPEN", (
        f"with no held floor and no dispatched job the posture falls back to OPEN, got "
        f"{read_order(order_id)['posture']}"
    )

    dispatched = validate_success(api_client.dispatch_set_job(job_id, {}, ADMIN_HEADERS))
    assert dispatched["progress_status"] == "DISPATCHED", (
        f"the unblocked dispatch now succeeds, got {dispatched['progress_status']}"
    )
    assert dispatched["scope_status"] == "SCOPE_PENDING", (
        f"the scope dimension is left untouched, got {dispatched['scope_status']}"
    )
    assert read_order(order_id)["posture"] == "SET_IN_PROGRESS", (
        f"a dispatched job drives the posture to SET_IN_PROGRESS, got "
        f"{read_order(order_id)['posture']}"
    )


def test_a_failing_marriage_line_verdict_refuses_to_close_and_records_nothing():
    """PRD §3.7: "the gap contributes, at weight 1.0, however much the gap exceeds
    a quarter of an inch (0.25 inches), and nothing at all if the gap is 0.25
    inches or less".  PRD §3.7: "The verdict lands in `closure_status`:
    `NOT_APPLICABLE` when the joint count is zero, otherwise `PASS` when the
    `closure_score` is at most 1.00, otherwise `FAIL`. A `FAIL` verdict does not
    close the line — the request is refused with `ERR_MARRIAGE_LINE_NOT_CLOSED`,
    and `closure_score` and `closure_status` are written only when the verdict is
    `PASS` or `NOT_APPLICABLE`."  PRD §3.7: "Before any closure attempt the job
    reads `closure_status` `NOT_ASSESSED` with `closure_score` null."

    Design: Corner/errors/posture_block_then_failing_marriage_line_verdict
    """
    scenario = setup_dispatched_set_job(section_count=2)
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]

    joint = record_marriage_joint(
        job_id,
        crew_id,
        joint_index=1,
        gap_in=1.5,
        vertical_offset_in=0.0,
        ridge_beam_shim_in=0.0,
    )
    assert joint["deviation_score"] == pytest.approx(1.25, abs=0.01), (
        "a 1.5-inch gap exceeds the quarter-inch tolerance by 1.25 inches at weight "
        f"1.0, got {joint['deviation_score']}"
    )

    refusal = api_client.close_marriage_line(
        job_id, {}, make_set_crew_lead_headers(crew_id)
    )
    validate_error(refusal, ApiErrorId.ERR_MARRIAGE_LINE_NOT_CLOSED, 422)

    job = read_set_job(job_id)
    assert job["closure_status"] == "NOT_ASSESSED", (
        f"a failing verdict writes no closure_status, got {job['closure_status']}"
    )
    assert job["closure_score"] is None, (
        f"a failing verdict writes no closure_score, got {job['closure_score']}"
    )
    assert job["progress_status"] == "DISPATCHED", (
        f"the line did not close, so the job stays DISPATCHED, got {job['progress_status']}"
    )


def test_a_settlement_landing_exactly_on_the_suspension_line_suspends_the_carrier():
    """PRD §3.9: "Whichever basis is chosen, the approved amount is computed the
    same way: the claimed amount less a ten percent approval haircut — that is,
    ninety percent of `claimed_amount_cents`, rounded half up to whole cents — and
    stored as `approved_amount_cents`."  PRD §3.9: "Third, threshold refresh on
    inclusive bounds: a hauler whose balance has reached five thousand dollars
    moves `ACTIVE → SUSPENDED`, and a plant whose balance has reached seven
    thousand five hundred dollars moves to `PROBATION`."

    Design: Corner/errors/hauler_suspension_at_exactly_the_threshold_then_leg_state_mismatch
    """
    scenario = _carrier_suspended_at_exactly_the_threshold()
    claim = scenario["claim"]

    assert claim["approved_amount_cents"] == 500000, (
        "ninety percent of 555,556 cents is 500,000.4 cents, which rounds half up to "
        f"500,000, got {claim['approved_amount_cents']}"
    )
    assert claim["hauler_charge_cents"] == 500000, (
        f"damage found in transit is charged to the carrier, got {claim['hauler_charge_cents']}"
    )
    assert claim["plant_charge_cents"] == 0, (
        f"the stage basis charges one party only, got {claim['plant_charge_cents']}"
    )
    assert claim["installer_charge_cents"] == 0, (
        f"the stage basis charges one party only, got {claim['installer_charge_cents']}"
    )
    assert_allocation_sums_exactly(claim)

    hauler = read_hauler(scenario["hauler"]["id"])
    assert hauler["chargeback_balance_cents"] == 500000, (
        f"the carrier's balance is exactly 500,000 cents, got "
        f"{hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "SUSPENDED", (
        "the suspension bound is inclusive, so a balance of exactly 500,000 cents "
        f"suspends the carrier, got {hauler['status']}"
    )
    plant = read_plant(scenario["plant"]["id"])
    assert plant["status"] == "ACTIVE", (
        f"the plant carries no charge and stays ACTIVE, got {plant['status']}"
    )


def test_a_suspended_carrier_cannot_be_booked_onto_a_new_corridor_leg():
    """PRD §3.5: "Because a permit authorises movement in exactly one state, a leg
    whose `state_code` differs from its permit's `state_code` is refused with
    `ERR_LEG_PERMIT_MISMATCH`, and a leg booked onto a carrier whose `status` is
    `SUSPENDED` is refused with `ERR_HAULER_SUSPENDED`."  PRD §2.10 priority 14:
    "the route leg's hauler has `status` `ACTIVE`. Applies to
    `POST /installations/route-legs` and `POST /installations/route-legs/{id}/depart`.
    Violation: `ERR_HAULER_SUSPENDED` (422). A chargeback-suspended carrier can
    neither take a new leg nor put an existing one on the road."

    Design: Corner/errors/hauler_suspension_at_exactly_the_threshold_then_leg_state_mismatch
    """
    scenario = _carrier_suspended_at_exactly_the_threshold()
    permit_id = scenario["permit"]["id"]
    hauler_id = scenario["hauler"]["id"]

    refusal = api_client.create_route_leg(
        create_route_leg_payload(permit_id, hauler_id, sequence_no=1, state_code="AZ"),
        make_permit_desk_headers(),
    )
    validate_error(refusal, ApiErrorId.ERR_HAULER_SUSPENDED, 422)

    legs, meta = validate_paginated(
        api_client.list_route_legs(ADMIN_HEADERS, params={"permit_id": permit_id})
    )
    assert meta["total_count"] == 0, (
        f"the refused booking wrote no leg, got {meta['total_count']}"
    )
    assert legs == [], f"the permit carries no legs, got {legs}"


def test_reversing_the_settlement_restores_the_carrier_and_empties_the_ledger():
    """PRD §3.9: "The three charge fields are zeroed, `allocation_basis` and
    `approved_amount_cents` are cleared back to null, and every party's
    `chargeback_balance_cents` is recomputed in full — dropping the reversed claim
    from every sum, which decreases each balance by exactly what the adjudication
    had added and restores the conserved network chargeback total of §2.9."  PRD
    §3.1: "When a reversal drops the balance back below five thousand dollars the
    carrier returns to `ACTIVE`."

    Design: Corner/errors/hauler_suspension_at_exactly_the_threshold_then_leg_state_mismatch
    """
    scenario = _carrier_suspended_at_exactly_the_threshold()
    hauler_id = scenario["hauler"]["id"]

    reversed_claim = reverse_damage_claim(scenario["claim"]["id"])
    assert reversed_claim["status"] == "REVERSED", (
        f"the reversal is terminal, got {reversed_claim['status']}"
    )
    for charge in ("plant_charge_cents", "hauler_charge_cents", "installer_charge_cents"):
        assert reversed_claim[charge] == 0, (
            f"{charge} is zeroed by the reversal, got {reversed_claim[charge]}"
        )
    assert reversed_claim["approved_amount_cents"] is None, (
        "approved_amount_cents is cleared back to null, got "
        f"{reversed_claim['approved_amount_cents']}"
    )
    assert reversed_claim["allocation_basis"] is None, (
        f"allocation_basis is cleared back to null, got {reversed_claim['allocation_basis']}"
    )

    hauler = read_hauler(hauler_id)
    assert hauler["chargeback_balance_cents"] == 0, (
        "a reversed claim contributes nothing to the carrier's balance, got "
        f"{hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "ACTIVE", (
        f"the restored carrier returns to ACTIVE, got {hauler['status']}"
    )
    assert_network_chargeback_conserved(read_order_summary(scenario["order"]["id"]), 0)


def test_a_corridor_leg_must_run_in_the_state_its_permit_authorises():
    """PRD §2.10 priority 16: "A route leg's `state_code` must equal the
    `state_code` of the transport permit it is filed under, because a permit
    authorises movement in exactly one state".  PRD §3.5: "A new leg opens at
    `status` `SCHEDULED`; `ARRIVED` and `CANCELLED` are terminal."

    Design: Corner/errors/hauler_suspension_at_exactly_the_threshold_then_leg_state_mismatch
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ", "TX"])
    order = open_order(plant["id"], section_count=1)
    section = record_section(order["id"], plant["id"], section_index=1)
    measure_and_release_section(section["id"], plant["id"])
    permit = request_permit(section["id"], state_code="AZ", planned_leg_count=1)

    refusal = api_client.create_route_leg(
        create_route_leg_payload(
            permit["id"],
            hauler["id"],
            sequence_no=1,
            state_code="TX",
            corridor_id="TX-I20",
        ),
        make_transport_manager_headers(hauler["id"]),
    )
    validate_error(refusal, ApiErrorId.ERR_LEG_PERMIT_MISMATCH, 422)
    assert "TX" in hauler["endorsed_states"], (
        "the carrier is endorsed in the leg's state, so only the permit's own state "
        "explains the refusal"
    )

    accepted = validate_success(
        api_client.create_route_leg(
            create_route_leg_payload(
                permit["id"], hauler["id"], sequence_no=1, state_code="AZ"
            ),
            make_transport_manager_headers(hauler["id"]),
        ),
        201,
    )
    assert accepted["state_code"] == "AZ", (
        f"the accepted leg runs in the permit's own state, got {accepted['state_code']}"
    )
    assert accepted["status"] == "SCHEDULED", (
        f"a new leg opens SCHEDULED, got {accepted['status']}"
    )
    assert accepted["sequence_no"] == 1, (
        f"the refused leg consumed no sequence number, got {accepted['sequence_no']}"
    )
