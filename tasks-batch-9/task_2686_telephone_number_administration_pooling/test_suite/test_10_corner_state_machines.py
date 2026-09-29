"""State machines: valid edges, refused edges, terminal locks and the cascades they fire."""
from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_USER_ID,
    CLOCK_PLUS_30,
    CLOCK_PLUS_181,
    DEFAULT_CLOCK,
    TEST_DEFAULTS,
    ApiErrorId,
    api_client,
    assert_pct,
    attest_readiness,
    create_eligible_carrier,
    create_filing,
    create_npa,
    create_rate_center,
    create_relief_plan,
    create_submitted_filing,
    declare_jeopardy,
    dispose_finding,
    file_allocation_request,
    grant_license,
    license_action,
    load_block,
    load_held_blocks,
    load_pool_blocks,
    make_carrier_representative_headers,
    open_audit_finding,
    pooling_transition,
    port_transition,
    rate_center_version,
    read_block,
    read_carrier,
    read_filing,
    read_finding,
    read_npa,
    read_order,
    read_port_request,
    read_rate_center,
    read_relief_plan,
    read_request,
    reclamation_transition,
    register_carrier,
    review_request,
    set_clock,
    setup_activation_deadline_order,
    setup_npa_with_rate_center,
    setup_plan_in_public_comment,
    setup_submitted_port_request,
    submit_filing,
    validate_error,
    validate_paginated,
)

LATER_EXPIRY = "2030-08-01T00:00:00Z"
NEW_ENTRANT_SWITCH_CLLI = "CLMBOH04DS0"
RESPONSE_DUE_AFTER_SWEEP = "2027-02-28T00:00:00Z"
AMENDMENT_CLOCK = "2026-09-01T00:00:00Z"

# The worked filing of Section 3.3: 4500 assignable numbers, 3100 of them in use.
SIXTY_EIGHT_POINT_EIGHT_NINE = dict(
    numbers_assigned=2500,
    numbers_intermediate=400,
    numbers_reserved=200,
    numbers_aging=200,
    numbers_administrative=300,
    blocks_held_at_period_end=5,
    forecast_quarters=[1800, 1800, 1800, 1800],
)

# One block held, 950 of its thousand numbers claimed as assigned.
NINETY_FIVE_POINT_ZERO_ZERO = dict(
    numbers_assigned=950,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=1,
    forecast_quarters=[200, 200, 200, 200],
)


def _fresh_carrier():
    """A registered carrier that has taken no licensing or readiness action."""
    set_clock()
    carrier = register_carrier("A")
    assert carrier["license_status"] == "NONE"
    assert carrier["facilities_readiness_status"] == "NOT_SUBMITTED"
    return carrier


class TestTheLicensingAxisOpensWithAGrant:
    """A grant moves the licensing axis and nothing else."""

    def test_the_grant_leaves_the_carrier_ineligible_on_the_facilities_axis(self):
        """The licence lands with its stored expiry, yet the carrier is still ineligible
        because the other axis has not started.

        it sets `license_status` to `GRANTED`, stores that expiry, recomputes

        `eligibility_status` — which becomes `ELIGIBLE` only if the facilities axis already reads `VERIFIED`

        Design: Corner/state_machines/carrier_license_grant_moves_none_to_granted
        """
        carrier = _fresh_carrier()

        granted = grant_license(carrier)

        assert granted["license_status"] == "GRANTED"
        assert granted["license_expires_on"] == TEST_DEFAULTS["LICENSE_EXPIRES_ON"]
        assert granted["facilities_readiness_status"] == "NOT_SUBMITTED"
        assert granted["eligibility_status"] == "INELIGIBLE"
        assert granted["version"] == 2


class TestASecondGrantIsRefused:
    """GRANT exists only from NONE; extending an expiry is RENEW's job."""

    def test_a_second_grant_is_refused_and_does_not_overwrite_the_expiry(self):
        """The stored expiry survives an attempt to push it out by re-granting.

        Granting a licence with `GRANT` requires the carrier to still be at `license_status` `NONE`

        a `RENEW` action on a carrier already at `GRANTED` extends `license_expires_on`

        Design: Corner/state_machines/carrier_second_grant_returns_invalid_state_transition
        """
        carrier = _fresh_carrier()
        grant_license(carrier)

        validate_error(
            api_client.create_license_action(
                carrier["id"],
                {"action": "GRANT", "license_expires_on": LATER_EXPIRY},
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        unchanged = read_carrier(carrier["id"])
        assert unchanged["license_status"] == "GRANTED"
        assert unchanged["license_expires_on"] == TEST_DEFAULTS["LICENSE_EXPIRES_ON"]
        assert unchanged["version"] == 2


class TestVerificationRequiresInterconnection:
    """An attestation that admits it cannot interconnect cannot be verified."""

    def test_a_carrier_that_attested_without_interconnection_cannot_be_verified(self):
        """The attestation is accepted exactly as filed, and the inspection that follows
        is refused on the flag the carrier itself supplied.

        `ATTEST` sets `facilities_readiness_status` to `ATTESTED`, copies `switch_clli` and `interconnection_ready` from the payload

        `VERIFY` moves `ATTESTED → VERIFIED`, and is accepted only when `interconnection_ready` reads true

        Design: Corner/state_machines/carrier_verify_without_interconnection_ready_is_refused
        """
        carrier = _fresh_carrier()
        grant_license(carrier)

        attested = attest_readiness(carrier, interconnection_ready=False)
        assert attested["facilities_readiness_status"] == "ATTESTED"
        assert attested["switch_clli"] == TEST_DEFAULTS["SWITCH_CLLI_A"]
        assert attested["interconnection_ready"] is False

        validate_error(
            api_client.create_readiness_event(
                carrier["id"], {"event": "VERIFY"}, ADMIN_HEADERS
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        unchanged = read_carrier(carrier["id"])
        assert unchanged["facilities_readiness_status"] == "ATTESTED"
        assert unchanged["eligibility_status"] == "INELIGIBLE"
        assert unchanged["license_status"] == "GRANTED"


def _new_entrant_with_no_inventory():
    """A verified carrier that holds nothing anywhere, plus a pristine rate center."""
    set_clock()
    carrier = create_eligible_carrier(
        "A",
        switch_clli=NEW_ENTRANT_SWITCH_CLLI,
        ocn="3456",
        legal_name="Olentangy Wireless LLC",
        carrier_type="WIRELESS",
        months_in_operation=3,
    )
    npa, rate_center = setup_npa_with_rate_center()
    return carrier, npa, rate_center


def _first_request_of_a_new_entrant(carrier, rate_center):
    """The entrant's opening request for a single block."""
    return file_allocation_request(
        carrier, rate_center, request_type="INITIAL", requested_block_count=1,
        justification="First block for a new entrant in COLUMBUS",
    )


class TestAFreshRequestOpensInTheQueue:
    """A newly filed request carries no decision history at all."""

    def test_the_new_request_has_no_reviewer_no_grant_and_no_information_cycle(self):
        """Every decision field is still null on arrival, and the rate center's queue depth
        and version both move by one.

        A newly filed request opens at `status` `PENDING_REVIEW` with `info_request_count` at 0,

        `granted_block_count` at 0, an empty `assigned_block_ids` array, and `reviewer_user_id`,

        The rate center's `pending_request_count` is incremented by 1 and the rate center's

        Design: Corner/state_machines/allocation_request_starts_at_pending_review_with_zero_info_cycles
        """
        carrier, _npa, rate_center = _new_entrant_with_no_inventory()
        version_before = rate_center_version(rate_center["id"])
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 0

        request = _first_request_of_a_new_entrant(carrier, rate_center)

        assert request["status"] == "PENDING_REVIEW"
        assert request["info_request_count"] == 0
        assert request["granted_block_count"] == 0
        assert request["assigned_block_ids"] == []
        assert request["reviewer_user_id"] is None
        assert request["approver_user_id"] is None
        assert request["decided_at"] is None
        assert request["denial_reason"] is None
        assert request["superseded_by_request_id"] is None

        queued = read_rate_center(rate_center["id"])
        assert queued["pending_request_count"] == 1
        assert queued["version"] == version_before + 1


class TestSubmissionComputesBothUtilizationBases:
    """One submission stamps the clock and fills in three percentages."""

    def test_the_submission_stamps_the_clock_and_both_bases_at_once(self):
        """The worked example of the specification: 4500 assignable numbers, 3100 of them
        claimed and 2500 of them strictly assigned.

        Submission stamps `submitted_at` at the current logical clock, recomputes both

        the denominator is 4500, the claimed numerator is 3100 giving 68.89

        recomputes the rate center's `aggregate_utilization_pct` from the newly effective filing

        Design: Corner/state_machines/filing_submission_stamps_submitted_at_and_claimed_utilization
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_held_blocks(npa, rate_center, carrier, 5, nxx_code="555")
        filing = create_filing(carrier, rate_center, **SIXTY_EIGHT_POINT_EIGHT_NINE)
        assert filing["status"] == "DRAFT"
        assert filing["submitted_at"] is None
        version_before = rate_center_version(rate_center["id"])

        submitted = submit_filing(carrier, filing)

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == DEFAULT_CLOCK
        assert_pct(submitted["claimed_utilization_pct"], 68.89, "claimed_utilization_pct")
        assert_pct(submitted["strict_utilization_pct"], 55.56, "strict_utilization_pct")
        assert submitted["audited_utilization_pct"] is None
        assert submitted["amendment_count"] == 0
        assert submitted["version"] == 2

        pooled = read_rate_center(rate_center["id"])
        assert_pct(pooled["aggregate_utilization_pct"], 68.89, "aggregate_utilization_pct")
        assert pooled["version"] == version_before + 1


class TestARejectedFindingCostsTheCarrierNothing:
    """A thrown-away finding leaves the audit open and the carrier clean."""

    def test_rejecting_a_referral_grade_finding_applies_none_of_its_penalty(self):
        """The finding was severe enough to earn a reclamation referral, yet rejecting it
        leaves the strike count, the probation stamp and the filing untouched.

        A filing claiming 95.00 that audits down to 60.00 produces a difference of 35.00

        `disposed_by_user_id` is set to the acting `X-User-ID`, the finding's `status` becomes `ACCEPTED` or `REJECTED`

        Rejecting a finding throws it away. No penalty is applied, `reclamation_strike_count` and

        the parent filing stays exactly where it is at `UNDER_AUDIT`, and `audited_utilization_pct` is not stamped

        Design: Corner/state_machines/audit_finding_reject_leaves_filing_under_audit_with_no_penalty
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        filing = create_submitted_filing(
            carrier, rate_center, **NINETY_FIVE_POINT_ZERO_ZERO
        )
        assert_pct(filing["claimed_utilization_pct"], 95.00, "claimed_utilization_pct")

        finding = open_audit_finding(
            filing, "OVERSTATED_UTILIZATION", adjusted_numbers_assigned=600
        )
        assert finding["status"] == "OPEN"
        assert_pct(finding["adjusted_utilization_pct"], 60.00, "adjusted_utilization_pct")
        assert finding["penalty_action"] == "RECLAMATION_REFERRAL"
        assert read_filing(filing["id"])["status"] == "UNDER_AUDIT"

        dispose_finding(finding, "REJECT", disposition_note="Carrier's evidence accepted")

        disposed = read_finding(finding["id"])
        assert disposed["status"] == "REJECTED"
        assert disposed["disposed_by_user_id"] == APPROVER_USER_ID
        assert disposed["penalty_action"] == "RECLAMATION_REFERRAL"

        still_open = read_filing(filing["id"])
        assert still_open["status"] == "UNDER_AUDIT"
        assert still_open["audited_utilization_pct"] is None

        unpunished = read_carrier(carrier["id"])
        assert unpunished["reclamation_strike_count"] == 0
        assert unpunished["probation_until"] is None
        assert unpunished["eligibility_status"] == "ELIGIBLE"


class TestWithdrawalReleasesThePendingCounter:
    """The carrier's own exit is pure bookkeeping."""

    def test_the_withdrawal_frees_the_queue_slot_and_moves_no_block(self):
        """The five available blocks are exactly where they were before the request was
        filed, and the rate center's queue is empty again.

        It sets `status` to `WITHDRAWN`, stamps `decided_at` at the logical clock, decrements the

        It touches no inventory at all.

        Design: Corner/state_machines/allocation_request_withdraw_decrements_pending_request_count
        """
        carrier, npa, rate_center = _new_entrant_with_no_inventory()
        load_pool_blocks(npa, rate_center, 5, nxx_code="556")
        request = _first_request_of_a_new_entrant(carrier, rate_center)
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 1

        withdrawn = review_request(
            request, "WITHDRAW", make_carrier_representative_headers(carrier["id"])
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["decided_at"] == DEFAULT_CLOCK
        assert withdrawn["granted_block_count"] == 0
        assert withdrawn["assigned_block_ids"] == []
        assert withdrawn["version"] == 2

        emptied = read_rate_center(rate_center["id"])
        assert emptied["pending_request_count"] == 0
        assert emptied["available_block_count"] == 5
        assert emptied["assigned_block_count"] == 0
        assert read_carrier(carrier["id"])["blocks_held_count"] == 0


class TestASecondRequestDisplacesTheFirst:
    """One carrier cannot keep two open requests for one rate center."""

    def test_the_older_row_is_superseded_and_the_queue_depth_is_unchanged(self):
        """The second filing points the first one at itself, and the two counter movements
        cancel out so the queue still shows a single open request.

        setting the older row's `status` to `SUPERSEDED`, stamping its `superseded_by_request_id` with the id of the new request

        is decremented by 1 for the displaced row and incremented by 1 for the new row

        Every accepted filing advances the rate center's `version` (its pending-request counter changes)

        Design: Corner/state_machines/newer_request_from_same_carrier_supersedes_the_open_request
        """
        carrier, _npa, rate_center = _new_entrant_with_no_inventory()
        version_before = rate_center_version(rate_center["id"])
        first = _first_request_of_a_new_entrant(carrier, rate_center)

        second = _first_request_of_a_new_entrant(carrier, rate_center)

        displaced = read_request(first["id"])
        assert displaced["status"] == "SUPERSEDED"
        assert displaced["superseded_by_request_id"] == second["id"]
        assert displaced["decided_at"] == DEFAULT_CLOCK
        assert displaced["version"] == 2

        assert second["status"] == "PENDING_REVIEW"
        assert second["superseded_by_request_id"] is None
        assert second["info_request_count"] == 0

        queued = read_rate_center(rate_center["id"])
        assert queued["pending_request_count"] == 1
        assert queued["version"] == version_before + 2


def _issued_order_over_an_unactivated_block():
    """An order the sweep served on a block that was reserved and then forgotten."""
    carrier, _npa, _rate_center, block, order = setup_activation_deadline_order(
        sweep_at=CLOCK_PLUS_181
    )
    assert order["status"] == "ISSUED"
    assert order["reason"] == "ACTIVATION_DEADLINE_MISSED"
    assert order["issued_at"] == CLOCK_PLUS_181
    assert order["response_due_at"] == RESPONSE_DUE_AFTER_SWEEP
    assert block["allocation_status"] == "RECLAMATION_PENDING"
    assert block["activated_at"] is None
    return carrier, block, order


class TestWithdrawingAnOrderRestoresTheBlock:
    """The administrator's reversal compensates the sweep and costs no strike."""

    def test_a_block_that_was_never_activated_returns_to_reserved(self):
        """The reversal puts the block back on the reservation it never took up, and the
        carrier's strike count never moves.

        `issued_at` at the sweep instant, `response_due_at` 30 days after the sweep instant

        a block whose `activated_at` was set returns to `ASSIGNED`, and a block that had never been

        The order's `executed_at` stays null and `strike_applied` stays false

        Design: Corner/state_machines/reclamation_order_withdraw_restores_the_reserved_block
        """
        carrier, block, order = _issued_order_over_an_unactivated_block()

        reclamation_transition(order, "WITHDRAW")

        reversed_order = read_order(order["id"])
        assert reversed_order["status"] == "WITHDRAWN"
        assert reversed_order["executed_at"] is None
        assert reversed_order["strike_applied"] is False
        assert reversed_order["issued_at"] == CLOCK_PLUS_181
        assert reversed_order["response_due_at"] == RESPONSE_DUE_AFTER_SWEEP

        restored = read_block(block["id"])
        assert restored["allocation_status"] == "RESERVED"
        assert restored["holder_carrier_id"] == carrier["id"]
        assert restored["activated_at"] is None
        assert restored["aging_release_at"] is None

        unpunished = read_carrier(carrier["id"])
        assert unpunished["reclamation_strike_count"] == 0
        assert unpunished["blocks_held_count"] == 1
        assert unpunished["eligibility_status"] == "ELIGIBLE"


class TestExecutionWaitsForTheResponseDeadline:
    """Silence only counts as silence once the deadline has genuinely passed."""

    def test_executing_a_silent_order_on_the_sweep_instant_is_refused(self):
        """The carrier has neither surrendered nor appealed, so the order cannot be executed
        a month before its response deadline.

        an order the carrier has neither surrendered nor appealed may be executed only once the logical clock is

        the requested transition exists from the current state and every cross-entity precondition of that transition holds

        Design: Corner/state_machines/reclamation_order_execute_before_response_deadline_is_refused
        """
        carrier, block, order = _issued_order_over_an_unactivated_block()

        validate_error(
            api_client.create_reclamation_transition(
                order["id"], {"action": "EXECUTE"}, ADMIN_HEADERS
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        untouched_order = read_order(order["id"])
        assert untouched_order["status"] == "ISSUED"
        assert untouched_order["executed_at"] is None
        assert untouched_order["strike_applied"] is False

        untouched_block = read_block(block["id"])
        assert untouched_block["allocation_status"] == "RECLAMATION_PENDING"
        assert untouched_block["holder_carrier_id"] == carrier["id"]
        assert untouched_block["aging_release_at"] is None
        assert read_carrier(carrier["id"])["reclamation_strike_count"] == 0


class TestCommentWindowNeedsATroubledCode:
    """The plan may be ready for consultation while its area code is not."""

    def test_opening_comment_over_a_healthy_code_is_refused(self):
        """The plan sits correctly in planning, yet the consultation cannot open because the
        area code is not in trouble.

        It requires the area code to be genuinely in trouble — its `status` must read

        It stamps `comment_window_open_at` at the logical clock and `comment_window_close_at` at

        Design: Corner/state_machines/relief_plan_open_comment_on_active_npa_is_refused
        """
        set_clock()
        npa = create_npa(npa_type="GEOGRAPHIC")
        assert read_npa(npa["id"])["status"] == "ACTIVE"
        plan = create_relief_plan(npa, comment_window_days=30)
        assert plan["status"] == "PLANNING"

        validate_error(
            api_client.create_relief_transition(
                plan["id"], {"action": "OPEN_COMMENT"}, ADMIN_HEADERS
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        unopened = read_relief_plan(plan["id"])
        assert unopened["status"] == "PLANNING"
        assert unopened["comment_window_open_at"] is None
        assert unopened["comment_window_close_at"] is None
        assert unopened["window_end_at"] is None
        assert unopened["comment_count"] == 0

        untroubled = read_npa(npa["id"])
        assert untroubled["status"] == "ACTIVE"
        assert untroubled["jeopardy_declared_at"] is None


class TestClosureWaitsForTheWindowToClose:
    """A consultation cannot be closed on the day it opened."""

    def test_closing_thirty_days_early_stamps_no_recommendation(self):
        """The window has just opened, so the closure is refused and none of the tally
        fields are written.

        `CLOSE_AND_RECOMMEND` belongs to the `NumberingAdministrator` and requires the logical clock to be at or after

        and `comment_window_close_at` at `comment_window_days` after that instant

        Design: Corner/state_machines/relief_plan_close_and_recommend_before_window_close_is_refused
        """
        set_clock()
        _npa, plan = setup_plan_in_public_comment(comment_window_days=30)
        assert plan["comment_window_open_at"] == DEFAULT_CLOCK
        assert plan["comment_window_close_at"] == CLOCK_PLUS_30

        validate_error(
            api_client.create_relief_transition(
                plan["id"], {"action": "CLOSE_AND_RECOMMEND"}, ADMIN_HEADERS
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        still_consulting = read_relief_plan(plan["id"])
        assert still_consulting["status"] == "PUBLIC_COMMENT"
        assert still_consulting["comment_window_close_at"] == CLOCK_PLUS_30
        assert still_consulting["recommended_relief_type"] is None
        assert still_consulting["recommender_user_id"] is None
        assert still_consulting["support_overlay_weight"] is None
        assert still_consulting["support_split_weight"] is None
        assert still_consulting["comment_count"] == 0


class TestJeopardyDeclarationFansOutToEveryRateCenter:
    """One declaration reaches every child of the code and no further."""

    def test_both_children_are_flagged_while_another_code_is_untouched(self):
        """COLUMBUS and DUBLIN both stop taking initial demand on the strength of a single
        declaration, while MARION under a different code carries on.

        A manual declaration is accepted only on a code currently at `ACTIVE` and produces side effects identical

        `jeopardy_flag` is set on every rate center under the code so that `accepts_initial_requests` turns false

        Design: Corner/state_machines/npa_jeopardy_declaration_flags_every_rate_center_under_the_code
        """
        set_clock()
        npa, columbus = setup_npa_with_rate_center()
        dublin = create_rate_center(npa, name=TEST_DEFAULTS["SIBLING_RATE_CENTER_NAME"])
        other_npa = create_npa(npa_code="380", npa_type="GEOGRAPHIC")
        marion = create_rate_center(other_npa, name="MARION")

        declared = declare_jeopardy(
            npa, reason="NRUF forecasts consume the remaining inventory within four quarters"
        )

        assert declared["status"] == "JEOPARDY"
        assert declared["jeopardy_declared_at"] == DEFAULT_CLOCK

        for child in (columbus, dublin):
            flagged = read_rate_center(child["id"])
            assert flagged["jeopardy_flag"] is True
            assert flagged["accepts_initial_requests"] is False
            assert flagged["version"] == 2

        untouched = read_rate_center(marion["id"])
        assert untouched["jeopardy_flag"] is False
        assert untouched["accepts_initial_requests"] is True
        assert untouched["version"] == 1
        assert read_npa(other_npa["id"])["status"] == "ACTIVE"


class TestPostureCyclesWithInventory:
    """The posture axis is a loop the inventory drives in both directions."""

    def test_the_first_block_declares_jeopardy_and_the_fifth_lifts_it(self):
        """Loading blocks one at a time walks the code into jeopardy and back out again,
        clearing both the declaration stamp and the child rate center's flag.

        Moving `ACTIVE → JEOPARDY` — which happens when the available count lands strictly above zero

        Recovering `JEOPARDY → ACTIVE` — which happens when the available count rises strictly above

        every rate center under the code has `jeopardy_flag` cleared to false, restoring `accepts_initial_requests`

        Design: Corner/state_machines/npa_posture_cycles_jeopardy_then_back_to_active_as_inventory_loads
        """
        set_clock()
        npa, rate_center = setup_npa_with_rate_center()

        for digit in range(4):
            load_block(npa, rate_center, nxx_code="554", thousands_digit=digit)
            loading = read_npa(npa["id"])
            assert loading["status"] == "JEOPARDY"
            assert loading["available_block_count"] == digit + 1
        assert read_npa(npa["id"])["jeopardy_declared_at"] == DEFAULT_CLOCK
        assert read_rate_center(rate_center["id"])["jeopardy_flag"] is True

        load_block(npa, rate_center, nxx_code="554", thousands_digit=4)

        recovered = read_npa(npa["id"])
        assert recovered["status"] == "ACTIVE"
        assert recovered["jeopardy_declared_at"] is None
        assert recovered["available_block_count"] == 5

        relieved = read_rate_center(rate_center["id"])
        assert relieved["jeopardy_flag"] is False
        assert relieved["accepts_initial_requests"] is True
        assert relieved["available_block_count"] == 5


class TestRevocationFansOutAcrossThreeEntityTypes:
    """One licence action reaches the blocks, the orders and the open queue."""

    def test_the_revocation_issues_one_order_per_block_and_denies_the_open_request(self):
        """Two held blocks produce two orders rather than one, and the growth request
        nobody had reviewed is closed as a probation denial.

        moves to `RECLAMATION_PENDING`, walked in `created_at` ascending order

        one reclamation order is created per block with `reason` of `LICENSE_REVOKED`, `status` of `ISSUED`

        every allocation request of this carrier sitting in `PENDING_REVIEW` or `INFO_REQUESTED` moves to `DENIED`

        Design: Corner/state_machines/license_revoke_issues_one_reclamation_order_per_held_block
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        blocks = load_held_blocks(npa, rate_center, carrier, 2, nxx_code="554")
        create_submitted_filing(carrier, rate_center, **SIXTY_EIGHT_POINT_EIGHT_NINE)
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="Sales pipeline for Q3 exhausts the current inventory",
        )
        assert request["status"] == "PENDING_REVIEW"

        revoked = license_action(
            carrier, "REVOKE", reason="Commission revocation docket 26-114"
        )

        assert revoked["license_status"] == "REVOKED"
        assert revoked["eligibility_status"] == "SUSPENDED"
        # Section 2.9 counts RESERVED, ASSIGNED *and* RECLAMATION_PENDING blocks,
        # so the two blocks the cascade moved are still held by this carrier.
        assert revoked["blocks_held_count"] == 2
        assert revoked["reclamation_strike_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_reclamation_orders(
                ADMIN_HEADERS, params={"carrier_id": carrier["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        assert {row["number_block_id"] for row in rows} == {
            blocks[0]["id"], blocks[1]["id"]
        }
        for row in rows:
            assert row["reason"] == "LICENSE_REVOKED"
            assert row["status"] == "ISSUED"
            assert row["issued_at"] == DEFAULT_CLOCK
            assert row["response_due_at"] == CLOCK_PLUS_30

        for block in blocks:
            pending = read_block(block["id"])
            assert pending["allocation_status"] == "RECLAMATION_PENDING"
            assert pending["holder_carrier_id"] == carrier["id"]
            assert pending["activated_at"] == DEFAULT_CLOCK

        denied = read_request(request["id"])
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "CARRIER_PROBATION"
        assert denied["decided_at"] == DEFAULT_CLOCK
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 0


class TestActivationConfirmationIsNotReentrant:
    """The holder may call, and the call still fails on the block's own state."""

    def test_a_second_confirmation_on_an_assigned_block_is_refused(self):
        """The caller really is the holder, so the refusal is about the block having already
        been activated rather than about ownership.

        a `CarrierRepresentative` whose `X-User-ID` equals the block's `holder_carrier_id` may call

        The block's `allocation_status` must be `RESERVED`, and the logical clock must be at or before `activation_due_at`

        Design: Corner/state_machines/block_second_activation_confirmation_is_refused
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        block = load_block(
            npa, rate_center, nxx_code="554", thousands_digit=0,
            holder_carrier_id=carrier["id"], mark_activated=True,
        )
        assert block["allocation_status"] == "ASSIGNED"
        assert block["activated_at"] == DEFAULT_CLOCK

        error = validate_error(
            api_client.create_activation_confirmation(
                block["id"],
                {"activated_number_count": 120},
                make_carrier_representative_headers(carrier["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_NOT_RESOURCE_OWNER.value

        unchanged = read_block(block["id"])
        assert unchanged["allocation_status"] == "ASSIGNED"
        assert unchanged["activated_at"] == DEFAULT_CLOCK
        assert unchanged["holder_carrier_id"] == carrier["id"]


class TestARejectedPortIsClosedForGood:
    """Rejection is one of the port's terminal states."""

    def test_concurring_after_a_rejection_is_refused_and_routing_is_undisturbed(self):
        """The losing carrier cannot change its mind, and the block's routing posture is
        exactly what it was before the port was ever filed.

        `REJECT` moves `SUBMITTED` to `REJECTED`, stamps `closed_at` and stores `reject_reason` from the payload

        `SNAPPED_BACK`, `REJECTED` and `CANCELLED` for a port request

        Design: Corner/state_machines/port_request_rejected_is_terminal_and_refuses_concur
        """
        from_carrier, _to_carrier, _npa, _rate_center, block, port_request = (
            setup_submitted_port_request(desired_due_at="2026-09-01T00:00:00Z")
        )
        losing_headers = make_carrier_representative_headers(from_carrier["id"])
        rejected = port_transition(
            port_request, "REJECT", losing_headers,
            reject_reason="Account number mismatch on the customer service record",
        )
        assert rejected["status"] == "REJECTED"

        validate_error(
            api_client.create_port_transition(
                port_request["id"], {"action": "CONCUR"}, losing_headers
            ),
            ApiErrorId.ERR_TERMINAL_STATE,
            409,
        )

        closed = read_port_request(port_request["id"])
        assert closed["status"] == "REJECTED"
        assert closed["concurred_at"] is None
        assert closed["activated_at"] is None
        assert closed["closed_at"] == DEFAULT_CLOCK

        undisturbed = read_block(block["id"])
        assert undisturbed["routing_status"] == "LERG_PUBLISHED"
        assert undisturbed["current_lrn"] == "6145580000"
        assert undisturbed["npac_db_version"] == 1


class TestRevertRestoresInitialAcceptance:
    """The pooling transition is reversible while it is still transitional."""

    def test_beginning_and_reverting_pooling_returns_the_rate_center_to_taking_demand(self):
        """Starting the transition closes the rate center to initial demand, and reverting
        opens it again without touching the jeopardy flag.

        the immediate consequence is that computed `accepts_initial_requests` flips to false

        `REVERT` moves it back from `TRANSITIONAL` to `NON_POOLED` and increments `version` by 1

        Design: Corner/state_machines/rate_center_revert_from_transitional_restores_initial_acceptance
        """
        set_clock()
        _npa, rate_center = setup_npa_with_rate_center()
        assert rate_center["pooling_status"] == "NON_POOLED"
        assert rate_center["accepts_initial_requests"] is True

        transitional = pooling_transition(rate_center, "BEGIN_POOLING")
        assert transitional["pooling_status"] == "TRANSITIONAL"
        assert transitional["accepts_initial_requests"] is False
        assert transitional["jeopardy_flag"] is False
        assert transitional["version"] == 2

        reverted = pooling_transition(rate_center, "REVERT")

        assert reverted["pooling_status"] == "NON_POOLED"
        assert reverted["accepts_initial_requests"] is True
        assert reverted["jeopardy_flag"] is False
        assert reverted["pooling_effective_at"] is None
        assert reverted["version"] == 3
        assert read_rate_center(rate_center["id"])["pooling_status"] == "NON_POOLED"


class TestAnAmendmentReopensTheAuditedFiling:
    """A rejected filing loops back to submitted, and the strike stays behind."""

    def test_the_amendment_counts_itself_and_clears_the_audited_figure(self):
        """The referral cost the carrier a strike on the way in, and the amendment that
        follows re-opens the filing without giving that strike back.

        a `RECLAMATION_REFERRAL` additionally increments the carrier's `reclamation_strike_count` by 1

        it additionally requires an `amendment_note` in the payload, increments `amendment_count` by 1

        re-stamps `submitted_at` at the current instant, and recomputes `claimed_utilization_pct` from the amended counts

        Design: Corner/state_machines/filing_amendment_after_rejection_increments_amendment_count
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        filing = create_submitted_filing(
            carrier, rate_center, **NINETY_FIVE_POINT_ZERO_ZERO
        )
        finding = open_audit_finding(
            filing, "OVERSTATED_UTILIZATION", adjusted_numbers_assigned=600
        )
        assert finding["penalty_action"] == "RECLAMATION_REFERRAL"
        dispose_finding(finding, "ACCEPT")

        struck = read_carrier(carrier["id"])
        assert struck["reclamation_strike_count"] == 1
        rejected = read_filing(filing["id"])
        assert rejected["status"] == "REJECTED"
        assert_pct(rejected["audited_utilization_pct"], 60.00, "audited_utilization_pct")
        assert rejected["amendment_count"] == 0

        set_clock(AMENDMENT_CLOCK)
        amended = submit_filing(
            carrier, filing, amendment_note="Administrative numbers were misclassified"
        )

        assert amended["status"] == "SUBMITTED"
        assert amended["amendment_count"] == 1
        assert amended["audited_utilization_pct"] is None
        assert amended["submitted_at"] == AMENDMENT_CLOCK
        assert_pct(amended["claimed_utilization_pct"], 95.00, "claimed_utilization_pct")
        assert read_carrier(carrier["id"])["reclamation_strike_count"] == 1
