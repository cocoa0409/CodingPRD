"""Set-side state machines: the marriage line, fresh rows and the reversed claim.

Each test builds its own network and order, because the database is empty at the
start of every test.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    add_route_leg,
    adjudicate_damage_claim_payload,
    assert_damage_claim,
    assert_marriage_joint,
    assert_set_job,
    assert_version_incremented,
    book_set_job,
    create_marriage_joint_payload,
    dispute_damage_claim_payload,
    make_plant_dispatcher_headers,
    make_set_crew_lead_headers,
    measure_and_release_section,
    open_damage_claim,
    open_order,
    read_anchor_certification,
    read_damage_claim,
    read_escort_crew,
    read_hauler,
    read_set_job,
    record_marriage_joint,
    record_section,
    register_escort_crew,
    register_hauler,
    register_plant,
    register_set_crew,
    register_site,
    request_permit,
    reserve_escort,
    reverse_damage_claim,
    reverse_damage_claim_payload,
    review_damage_claim_payload,
    set_logical_clock,
    setup_adjudicated_claim,
    setup_dispatched_set_job,
    submit_anchor_certification,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]

# A two-section home needs exactly one joint on file before the line can close.
EXPECTED_JOINTS_ON_A_DOUBLE_WIDE = 1


def _dispatched_double_wide():
    """A dispatched set job on a two-section home with no joints on file."""
    return setup_dispatched_set_job(section_count=2)


class TestMarriageLineCloseRequiresExactJointCount:
    """The close precondition is an exact joint count, not a minimum."""

    def test_closing_a_double_wide_with_no_joints_is_refused(self, api):
        """PRD §3.7: "The number of joints recorded on the job must equal the
        order's `section_count` less one, or zero when the order declares a
        single section; any other count is refused with
        `ERR_MARRIAGE_JOINT_COUNT_MISMATCH`, so a three-section home needs
        exactly two joints on file."
        PRD §3.7: "Before any closure attempt the job reads `closure_status`
        `NOT_ASSESSED` with `closure_score` null."

        Design: Corner/state_machines/marriage_line_close_requires_exact_joint_count
        """
        scenario = _dispatched_double_wide()
        job = scenario["set_job"]
        crew_lead = make_set_crew_lead_headers(scenario["set_crew"]["id"])

        assert_set_job(job)
        assert job["progress_status"] == "DISPATCHED", (
            f"the dispatched job waits in DISPATCHED, got {job['progress_status']}"
        )
        assert job["closure_status"] == "NOT_ASSESSED", (
            f"an unclosed line reads NOT_ASSESSED, got {job['closure_status']}"
        )
        assert job["closure_score"] is None, (
            f"an unclosed line has a null closure_score, got {job['closure_score']}"
        )

        validate_error(
            api.close_marriage_line(job["id"], {}, crew_lead),
            ApiErrorId.ERR_MARRIAGE_JOINT_COUNT_MISMATCH,
            422,
        )

        after = read_set_job(job["id"])
        assert after["progress_status"] == "DISPATCHED", (
            "the refused close leaves the progress dimension in DISPATCHED, got "
            f"{after['progress_status']}"
        )
        assert after["closure_status"] == "NOT_ASSESSED", (
            "no verdict is written when the joint count is wrong, got "
            f"{after['closure_status']}"
        )
        assert after["version"] == job["version"], (
            f"a rejected close mutates nothing, got version {after['version']}"
        )

    def test_a_second_joint_on_the_same_index_is_refused(self, api):
        """PRD §3.7: "A repeated joint index on the same job is refused with
        `ERR_DUPLICATE_JOINT_INDEX`."
        PRD §3.7: "Each joint's `deviation_score` is computed at the moment it is
        recorded and is a penalty for exceeding tolerance rather than a measure of
        the raw reading: the gap contributes, at weight 1.0, however much the gap
        exceeds a quarter of an inch (0.25 inches), and nothing at all if the gap
        is 0.25 inches or less; the vertical offset contributes, at weight 0.6,
        however much the *absolute value* of the offset exceeds half an inch (0.5
        inches), and nothing at all if that absolute value is 0.5 inches or less;
        and the shim contributes its full thickness at weight 0.4, with no
        tolerance allowance."

        Design: Corner/state_machines/marriage_line_close_requires_exact_joint_count
        """
        scenario = _dispatched_double_wide()
        job = scenario["set_job"]
        crew_lead = make_set_crew_lead_headers(scenario["set_crew"]["id"])

        joint = validate_success(
            api.create_marriage_joint(
                create_marriage_joint_payload(
                    job["id"],
                    joint_index=1,
                    gap_in=0.0,
                    vertical_offset_in=0.0,
                    ridge_beam_shim_in=0.0,
                ),
                crew_lead,
            ),
            201,
        )
        assert_marriage_joint(joint)
        assert joint["deviation_score"] == pytest.approx(0.00, abs=0.01), (
            "a joint inside every tolerance scores 0.00, got "
            f"{joint['deviation_score']}"
        )

        validate_error(
            api.create_marriage_joint(
                create_marriage_joint_payload(
                    job["id"],
                    joint_index=1,
                    gap_in=0.1,
                    vertical_offset_in=0.1,
                    ridge_beam_shim_in=0.0,
                ),
                crew_lead,
            ),
            ApiErrorId.ERR_DUPLICATE_JOINT_INDEX,
            409,
        )

        _, meta = validate_paginated(
            api.list_marriage_joints(crew_lead, params={"set_job_id": job["id"]})
        )
        assert meta["total_count"] == EXPECTED_JOINTS_ON_A_DOUBLE_WIDE, (
            "the rejected duplicate leaves exactly one joint on file, got "
            f"{meta['total_count']}"
        )

    def test_the_single_correctly_indexed_joint_closes_the_line(self, api):
        """PRD §3.7: "The job's `SetCrewLead` closes the marriage line, which
        moves `progress_status` `DISPATCHED → SET_COMPLETE`."
        PRD §3.7: "The verdict lands in `closure_status`: `NOT_APPLICABLE` when
        the joint count is zero, otherwise `PASS` when the `closure_score` is at
        most 1.00, otherwise `FAIL`."
        PRD §3.7: "Closing raises the job's `version`, re-derives the order's
        posture, and leaves `scope_status` unchanged."

        Design: Corner/state_machines/marriage_line_close_requires_exact_joint_count
        """
        scenario = _dispatched_double_wide()
        job = scenario["set_job"]
        crew_lead = make_set_crew_lead_headers(scenario["set_crew"]["id"])

        record_marriage_joint(
            job["id"],
            scenario["set_crew"]["id"],
            joint_index=1,
            gap_in=0.0,
            vertical_offset_in=0.0,
            ridge_beam_shim_in=0.0,
        )

        closed = validate_success(api.close_marriage_line(job["id"], {}, crew_lead))
        assert closed["progress_status"] == "SET_COMPLETE", (
            f"closing moves DISPATCHED -> SET_COMPLETE, got {closed['progress_status']}"
        )
        assert closed["closure_score"] == pytest.approx(0.00, abs=0.01), (
            f"one 0.00 joint sums to a 0.00 closure score, got {closed['closure_score']}"
        )
        assert closed["closure_status"] == "PASS", (
            "a score at or under 1.00 with one joint on file is a PASS rather than "
            f"NOT_APPLICABLE, got {closed['closure_status']}"
        )
        assert closed["scope_status"] == job["scope_status"], (
            "closing the line leaves the scope dimension untouched at "
            f"{job['scope_status']}, got {closed['scope_status']}"
        )
        assert_version_incremented(closed["version"], job["version"])


class TestNewRowsStartInDeclaredInitialStates:
    """Every state-bearing row lands on its declared initial state at insert."""

    def test_a_new_floor_opens_at_plant(self, api):
        """PRD §3.2: "A floor's `transit_status` starts at `AT_PLANT` and walks a
        branching path with two hold branches: `AT_PLANT`, `MEASURED`,
        `PERMIT_PENDING`, `DISPATCH_READY`, `IN_TRANSIT`, `DELIVERED`, plus the
        holds `PERMIT_REVOKED_HOLD` and `DAMAGED_HOLD`."
        PRD §3.2: "Those measured figures are the whole point of the step — every
        final permit evaluation reads them in preference to the declared ones,
        falling back to the declared value only where a measured value is still
        null."

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        set_logical_clock()
        plant = register_plant()
        order = open_order(plant["id"])

        section = record_section(order["id"], plant["id"])

        assert section["transit_status"] == "AT_PLANT", (
            f"a freshly recorded floor sits at AT_PLANT, got {section['transit_status']}"
        )
        assert section["measured_width_in"] is None, (
            "no measurement has been taken yet, so measured_width_in is null, got "
            f"{section['measured_width_in']}"
        )
        assert section["measured_height_in"] is None, (
            "no measurement has been taken yet, so measured_height_in is null, got "
            f"{section['measured_height_in']}"
        )

    def test_a_new_site_opens_in_readiness_pending(self, api):
        """PRD §3.3: "A new site opens at `readiness_status` `READINESS_PENDING`,
        with `inspection_round` at 0, `blocking_defect_count` at 0 and
        `last_inspector_user_id` null."

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        set_logical_clock()
        plant = register_plant()
        order = open_order(plant["id"])

        site = register_site(order["id"])

        assert site["readiness_status"] == "READINESS_PENDING", (
            f"a new site awaits its inspection, got {site['readiness_status']}"
        )
        assert site["inspection_round"] == 0, (
            f"no inspection round has run yet, got {site['inspection_round']}"
        )
        assert site["blocking_defect_count"] == 0, (
            f"no defects have been counted yet, got {site['blocking_defect_count']}"
        )
        assert site["last_inspector_user_id"] is None, (
            "nobody has signed a verdict yet, got "
            f"{site['last_inspector_user_id']}"
        )

    def test_a_new_permit_opens_requested_and_unpaid(self, api):
        """PRD §3.4: "A new permit opens at `status` `REQUESTED` with
        `paid_amount_cents` at 0, `final_fee_cents` null and `valid_until_date`
        null, raises the floor's `version`, and re-derives the order's posture."

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        set_logical_clock()
        plant = register_plant()
        order = open_order(plant["id"])
        section = record_section(order["id"], plant["id"])
        measure_and_release_section(section["id"], plant["id"])

        permit = request_permit(section["id"])

        assert permit["status"] == "REQUESTED", (
            f"a new permit opens in REQUESTED, got {permit['status']}"
        )
        assert permit["paid_amount_cents"] == 0, (
            f"nothing has been remitted yet, got {permit['paid_amount_cents']}"
        )
        assert permit["final_fee_cents"] is None, (
            "the final fee is only computed at issuance, got "
            f"{permit['final_fee_cents']}"
        )
        assert permit["valid_until_date"] is None, (
            f"an unissued permit carries no validity date, got {permit['valid_until_date']}"
        )

    def test_a_new_leg_opens_scheduled_and_its_reservation_reserved(self, api):
        """PRD §3.5: "A new leg opens at `status` `SCHEDULED`; `ARRIVED` and
        `CANCELLED` are terminal."
        PRD §3.1: "A new crew starts with `reserved_minutes` at 0 and `status`
        `AVAILABLE`, and its `status` becomes `OVERBOOKED` the moment its booked
        `reserved_minutes` exceeds `max_reserved_minutes` — a crew sitting exactly
        at the ceiling is still `AVAILABLE`."
        PRD §3.5: "A crew's `reserved_minutes` is never incremented; it is
        recomputed in full as the sum of the frozen `reserved_minutes` of every
        one of that crew's reservations currently in `RESERVED` status. Released
        and completed reservations contribute nothing."
        PRD §3.5: "That recomputation runs on four occasions: when a reservation
        is created, when one is released by the carrier, when a leg's arrival
        consumes its reservations, and inside the revocation cascade of §3.4."

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        set_logical_clock()
        plant = register_plant()
        hauler = register_hauler()
        escort_crew = register_escort_crew()
        order = open_order(plant["id"])
        section = record_section(order["id"], plant["id"])
        measure_and_release_section(section["id"], plant["id"])
        permit = request_permit(section["id"])

        assert escort_crew["reserved_minutes"] == 0, (
            f"a fresh escort crew has no booked minutes, got {escort_crew['reserved_minutes']}"
        )
        assert escort_crew["status"] == "AVAILABLE", (
            f"a fresh escort crew is AVAILABLE, got {escort_crew['status']}"
        )

        leg = add_route_leg(permit["id"], hauler["id"])
        assert leg["status"] == "SCHEDULED", (
            f"a new corridor leg opens in SCHEDULED, got {leg['status']}"
        )

        assignment = reserve_escort(leg["id"], escort_crew["id"], hauler["id"])
        assert assignment["status"] == "RESERVED", (
            f"a new reservation opens in RESERVED, got {assignment['status']}"
        )
        assert assignment["reserved_minutes"] == 480, (
            "the 06:00Z-14:00Z window freezes 480 minutes on the reservation, got "
            f"{assignment['reserved_minutes']}"
        )

        crew_after = read_escort_crew(escort_crew["id"])
        assert crew_after["reserved_minutes"] == 480, (
            "the crew's total is the sum of its RESERVED reservations, so the new "
            f"row must count for 480, got {crew_after['reserved_minutes']}"
        )
        assert crew_after["status"] == "AVAILABLE", (
            f"480 minutes is under the 600-minute ceiling, got {crew_after['status']}"
        )

    def test_a_new_set_job_opens_on_both_dimensions_at_once(self, api):
        """PRD §3.7: "`progress_status` is the set-execution dimension and runs
        `SCHEDULED`, `DISPATCHED`, `SET_COMPLETE`, `CLOSED`, with `SUPERSEDED` as
        its retirement branch. `scope_status` is the scope-delivery dimension and
        runs `SCOPE_PENDING`, `SCOPE_SPLIT`, `SCOPE_DELIVERED`."
        PRD §3.6: "Booking a job on an order that already has a set job still
        sitting in `SCHEDULED` retires the old one: it moves `SCHEDULED →
        SUPERSEDED` and the order's posture is re-derived."
        PRD §3.7: "Who owns the skirting and the steps is a commercial argument
        between the dealer and the installer, and the job's `SetCrewLead` records
        the outcome, moving `scope_status` `SCOPE_PENDING → SCOPE_SPLIT`."
        PRD §3.7: "Before any closure attempt the job reads `closure_status`
        `NOT_ASSESSED` with `closure_score` null."
        PRD §3.8: "Before any inspection, `final_result` reads `PENDING`."

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        set_logical_clock()
        plant = register_plant()
        set_crew = register_set_crew()
        order = open_order(plant["id"])

        job = book_set_job(order["id"], set_crew["id"])

        assert_set_job(job)
        assert job["progress_status"] == "SCHEDULED", (
            "a booked job opens at the head of the progress dimension, got "
            f"{job['progress_status']}"
        )
        assert job["scope_status"] == "SCOPE_PENDING", (
            "a booked job opens at the head of the scope dimension, got "
            f"{job['scope_status']}"
        )
        assert job["closure_status"] == "NOT_ASSESSED", (
            f"no closure verdict has been reached yet, got {job['closure_status']}"
        )
        assert job["closure_score"] is None, (
            f"no closure score has been computed yet, got {job['closure_score']}"
        )
        assert job["final_result"] == "PENDING", (
            f"no final inspection has been signed yet, got {job['final_result']}"
        )

    def test_a_new_anchor_package_opens_submitted_at_revision_round_one(self, api):
        """PRD §3.8: "A new package opens at `status` `SUBMITTED` with
        `revision_round` at 1 and `certifier_user_id` null."

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        set_logical_clock()
        plant = register_plant()
        set_crew = register_set_crew()
        order = open_order(plant["id"])
        job = book_set_job(order["id"], set_crew["id"])

        package = submit_anchor_certification(job["id"], set_crew["id"])

        assert package["status"] == "SUBMITTED", (
            f"a new anchoring package awaits review, got {package['status']}"
        )
        assert package["revision_round"] == 1, (
            "the first submission is revision round 1 rather than 0, got "
            f"{package['revision_round']}"
        )
        assert package["certifier_user_id"] is None, (
            f"nobody has reviewed the package yet, got {package['certifier_user_id']}"
        )

        stored = read_anchor_certification(package["id"])
        assert stored["status"] == "SUBMITTED", (
            f"the stored row agrees with the creation response, got {stored['status']}"
        )
        assert stored["revision_round"] == 1, (
            f"the stored revision_round is 1, got {stored['revision_round']}"
        )

    def test_a_new_damage_claim_opens_submitted_with_no_allocation(self, api):
        """PRD §3.9: "A new claim opens at `status` `SUBMITTED` with
        `dispute_round` at 0, `allocation_basis` and `approved_amount_cents` null,
        and `plant_charge_cents`, `hauler_charge_cents` and
        `installer_charge_cents` all at 0."

        Design: Corner/state_machines/new_rows_start_in_declared_initial_states
        """
        set_logical_clock()
        plant = register_plant()
        hauler = register_hauler()
        set_crew = register_set_crew()
        order = open_order(plant["id"])
        section = record_section(order["id"], plant["id"])

        claim = open_damage_claim(
            order["id"], section["id"], hauler["id"], set_crew["id"]
        )

        assert_damage_claim(claim)
        assert claim["status"] == "SUBMITTED", (
            f"a new claim awaits an adjuster, got {claim['status']}"
        )
        assert claim["dispute_round"] == 0, (
            f"nobody has pushed back yet, so dispute_round is 0, got {claim['dispute_round']}"
        )
        assert claim["allocation_basis"] is None, (
            f"no basis has been chosen yet, got {claim['allocation_basis']}"
        )
        assert claim["approved_amount_cents"] is None, (
            f"nothing has been approved yet, got {claim['approved_amount_cents']}"
        )
        for field in (
            "plant_charge_cents",
            "hauler_charge_cents",
            "installer_charge_cents",
        ):
            assert claim[field] == 0, (
                f"an unadjudicated claim charges nobody, so {field} is 0, got "
                f"{claim[field]}"
            )


def _reversed_claim():
    """A 100,000-cent in-transit claim adjudicated on the stage basis, then reversed.

    The stage basis charges the whole 90,000-cent approved amount to the carrier,
    and the reversal takes it straight back off the carrier's ledger.
    """
    scenario = setup_adjudicated_claim(
        allocation_basis="STAGE",
        claim_overrides={"hauler_evidence_points": 1},
    )
    scenario["claim"] = reverse_damage_claim(
        scenario["claim"]["id"], reason_code="WRONG_PARTY"
    )
    scenario["hauler"] = read_hauler(scenario["hauler"]["id"])
    return scenario


def _assert_reversal_survived(scenario, claim_before):
    """No rejected trigger may resurrect the reversed allocation."""
    claim = read_damage_claim(claim_before["id"])
    hauler = read_hauler(scenario["hauler"]["id"])

    assert claim["status"] == "REVERSED", (
        f"the reversed claim stays REVERSED, got {claim['status']}"
    )
    assert claim["dispute_round"] == claim_before["dispute_round"], (
        "a rejected trigger may not advance the negotiation counter, expected "
        f"{claim_before['dispute_round']}, got {claim['dispute_round']}"
    )
    assert claim["hauler_charge_cents"] == 0, (
        "the reversal zeroed the carrier's charge and nothing may write it back, "
        f"got {claim['hauler_charge_cents']}"
    )
    assert claim["approved_amount_cents"] is None, (
        "the reversal cleared the approved amount back to null, got "
        f"{claim['approved_amount_cents']}"
    )
    assert claim["version"] == claim_before["version"], (
        f"a rejected call mutates nothing, expected version "
        f"{claim_before['version']}, got {claim['version']}"
    )
    assert hauler["chargeback_balance_cents"] == 0, (
        "the carrier's ledger must stay at 0 after the rejected trigger, got "
        f"{hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "ACTIVE", (
        f"a carrier owing nothing is ACTIVE, got {hauler['status']}"
    )


class TestReversedClaimIsLockedAgainstEveryFurtherTrigger:
    """`REVERSED` is terminal, so all four claim triggers are refused from it."""

    def test_reviewing_a_reversed_claim_is_refused(self, api):
        """PRD §3.9: "New evidence or a wrongly named party lets the
        `ClaimsAdjuster` reverse an adjudicated claim, supplying a `reason_code`;
        the claim moves `ADJUDICATED → REVERSED`, which is terminal."
        PRD §3.9: "The adjuster's review action is also the re-entry point, moving
        the claim `DISPUTED → UNDER_REVIEW` and closing the negotiation cycle
        `UNDER_REVIEW → DISPUTED → UNDER_REVIEW` on the same row."
        PRD §2.10: "**Priority 7** — the addressed row's current state permits the
        requested transition. Applies to every action endpoint. Violation:
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/reversed_claim_is_locked_against_every_further_trigger
        """
        scenario = _reversed_claim()
        claim_before = scenario["claim"]

        assert claim_before["status"] == "REVERSED", (
            f"the setup leaves the claim REVERSED, got {claim_before['status']}"
        )
        assert scenario["hauler"]["chargeback_balance_cents"] == 0, (
            "the reversal dropped the carrier's balance back to 0, got "
            f"{scenario['hauler']['chargeback_balance_cents']}"
        )

        validate_error(
            api.review_damage_claim(
                claim_before["id"],
                review_damage_claim_payload(notes="second look"),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        _assert_reversal_survived(scenario, claim_before)

    def test_disputing_a_reversed_claim_is_refused(self, api):
        """PRD §3.9: "New evidence or a wrongly named party lets the
        `ClaimsAdjuster` reverse an adjudicated claim, supplying a `reason_code`;
        the claim moves `ADJUDICATED → REVERSED`, which is terminal."
        PRD §3.9: "The pushback carries a `reason_code` and may simultaneously
        re-score `plant_evidence_points`, `hauler_evidence_points` and
        `installer_evidence_points`, which changes the eventual evidence-based
        split; it moves the claim `UNDER_REVIEW → DISPUTED` and increments
        `dispute_round` by 1."
        PRD §2.10: "**Priority 7** — the addressed row's current state permits the
        requested transition. Applies to every action endpoint. Violation:
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/reversed_claim_is_locked_against_every_further_trigger
        """
        scenario = _reversed_claim()
        claim_before = scenario["claim"]
        charged_plant = make_plant_dispatcher_headers(scenario["plant"]["id"])

        validate_error(
            api.dispute_damage_claim(
                claim_before["id"],
                dispute_damage_claim_payload(
                    reason_code="PLANT_DISAGREES", plant_evidence_points=3
                ),
                charged_plant,
            ),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        _assert_reversal_survived(scenario, claim_before)

    def test_readjudicating_a_reversed_claim_is_refused(self, api):
        """PRD §3.9: "New evidence or a wrongly named party lets the
        `ClaimsAdjuster` reverse an adjudicated claim, supplying a `reason_code`;
        the claim moves `ADJUDICATED → REVERSED`, which is terminal."
        PRD §3.9: "From `UNDER_REVIEW` a `ClaimsAdjuster` settles the claim by
        supplying an `allocation_basis` of either `STAGE` or `EVIDENCE`, moving it
        `UNDER_REVIEW → ADJUDICATED`."
        PRD §2.10: "**Priority 7** — the addressed row's current state permits the
        requested transition. Applies to every action endpoint. Violation:
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/reversed_claim_is_locked_against_every_further_trigger
        """
        scenario = _reversed_claim()
        claim_before = scenario["claim"]

        validate_error(
            api.adjudicate_damage_claim(
                claim_before["id"],
                adjudicate_damage_claim_payload("EVIDENCE"),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        _assert_reversal_survived(scenario, claim_before)

    def test_reversing_a_reversed_claim_is_refused(self, api):
        """PRD §3.9: "New evidence or a wrongly named party lets the
        `ClaimsAdjuster` reverse an adjudicated claim, supplying a `reason_code`;
        the claim moves `ADJUDICATED → REVERSED`, which is terminal."
        PRD §3.9: "Reversal must unwind adjudication with no residue."
        PRD §2.10: "All the specialised readiness rules below are evaluated only
        once the base transition is legal, so a row sitting in a terminal state
        always yields `ERR_INVALID_STATE` rather than a domain-specific
        complaint."

        Design: Corner/state_machines/reversed_claim_is_locked_against_every_further_trigger
        """
        scenario = _reversed_claim()
        claim_before = scenario["claim"]

        validate_error(
            api.reverse_damage_claim(
                claim_before["id"],
                reverse_damage_claim_payload(reason_code="WRONG_PARTY"),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        _assert_reversal_survived(scenario, claim_before)
