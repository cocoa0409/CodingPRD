"""Declared and undeclared moves on the agreement, pool and physician machines."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_INVALID_STATE_TRANSITION,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    assert_fields,
    assert_pool_loss_position,
    assign_enrollee,
    build_approved_claim,
    create_active_agreement,
    create_active_physician,
    create_agreement,
    create_enrollee,
    create_physician,
    create_pool,
    credential_physician,
    pay_claim_state,
    read_agreement,
    read_enrollee,
    read_physician,
    read_pool,
    set_clock,
    state_payload,
)


def _a_draft_agreement(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    return create_agreement(
        api,
        payer_name="Corner Transition Health",
        professional_pool_share_bps=6000,
        institutional_pool_share_bps=4000,
        quality_withhold_bps=0,
    )


def _activate(api, agreement_id):
    return api.set_agreement_state(
        agreement_id, state_payload("ACTIVE"), IPA_ADMIN_HEADERS
    )


class TestAgreementActivation:
    def test_activation_sets_status_active_and_posture_current(self, api):
        """PRD §3.1: "Activation sets `status` to `ACTIVE`, sets
        `capitation_posture` to `CURRENT`, and derives the per-member capitation
        components for every enrollee already registered under the agreement as
        described in §3.3."

        Design: Corner/state_machines/agreement_draft_to_active_sets_posture_current
        """
        draft = _a_draft_agreement(api)
        assert_fields(draft, {"status": "DRAFT", "capitation_posture": "CURRENT"})

        activated = validate_success(_activate(api, draft["id"]), 200)
        assert_fields(activated, {"status": "ACTIVE", "capitation_posture": "CURRENT"})
        assert_fields(
            read_agreement(api, draft["id"]),
            {"status": "ACTIVE", "capitation_posture": "CURRENT"},
        )

    def test_activation_advances_the_agreement_version_by_exactly_one(self, api):
        """PRD §2.4: "Section 3 states, for each transition, which resources are
        touched; every resource named there has its `version` incremented by 1 and
        its `updated_at` refreshed as part of the same request."

        Design: Corner/state_machines/agreement_draft_to_active_sets_posture_current
        """
        draft = _a_draft_agreement(api)

        activated = validate_success(_activate(api, draft["id"]), 200)
        assert activated["version"] == draft["version"] + 1


def _an_active_agreement_with_a_calendar_2026_professional_pool(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Precondition Health", quality_withhold_bps=0
    )
    pool = create_pool(
        api,
        agreement["id"],
        pool_type="PROFESSIONAL",
        pool_year_start="2026-01-01T00:00:00Z",
        pool_year_end="2026-12-31T23:59:59Z",
    )
    return agreement, pool


def _close_incurral_response(api, pool_id):
    return api.set_risk_pool_state(
        pool_id, state_payload("CLOSED_FOR_INCURRAL"), IPA_ADMIN_HEADERS
    )


class TestPoolIncurralClose:
    def test_closing_incurral_before_pool_year_end_is_refused(self, api):
        """PRD §3.7: "Attempting to close early is refused with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/pool_close_for_incurral_before_pool_year_end_rejected
        """
        _agreement, pool = _an_active_agreement_with_a_calendar_2026_professional_pool(
            api
        )
        assert pool["status"] == "ACCUMULATING"

        validate_error(
            _close_incurral_response(api, pool["id"]), ERR_INVALID_STATE_TRANSITION, 409
        )
        assert read_pool(api, pool["id"])["status"] == "ACCUMULATING"

    def test_the_clock_at_exactly_pool_year_end_permits_the_close(self, api):
        """PRD §3.7: "Closing incurral is the first move: an `IpaAdmin` takes the
        pool `ACCUMULATING → CLOSED_FOR_INCURRAL`, permitted when `status` is
        `ACCUMULATING` and the logical clock has reached `pool_year_end`."

        Design: Corner/state_machines/pool_close_for_incurral_before_pool_year_end_rejected
        """
        _agreement, pool = _an_active_agreement_with_a_calendar_2026_professional_pool(
            api
        )
        validate_error(
            _close_incurral_response(api, pool["id"]), ERR_INVALID_STATE_TRANSITION, 409
        )

        set_clock(api, "2026-12-31T23:59:59Z")
        closed = validate_success(_close_incurral_response(api, pool["id"]), 200)
        assert closed["status"] == "CLOSED_FOR_INCURRAL"


def _an_agreement_with_one_open_and_one_closed_panel(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Suspend Health", quality_withhold_bps=0
    )
    open_physician = create_active_physician(
        api, agreement["id"], full_name="Suri Adeyemi"
    )
    closed_physician = create_active_physician(
        api, agreement["id"], full_name="Silas Boateng"
    )
    closed = validate_success(
        api.set_panel_status(
            closed_physician["id"],
            {"panel_status": "CLOSED_TO_NEW"},
            NETWORK_MANAGER_HEADERS,
        ),
        200,
    )
    assert open_physician["panel_status"] == "OPEN"
    assert closed["panel_status"] == "CLOSED_TO_NEW"
    return agreement, open_physician, closed_physician


def _list_panels(api, agreement_id, panel_status):
    return validate_paginated(
        api.list_agreement_physicians(
            agreement_id,
            NETWORK_MANAGER_HEADERS,
            {"panel_status": panel_status, "limit": 10, "offset": 0},
        )
    )


class TestSuspensionClosesOpenPanels:
    def test_suspension_closes_every_open_panel_of_the_agreement(self, api):
        """PRD §3.1: "Moving `ACTIVE → SUSPENDED` requires only that `status` is
        currently `ACTIVE`; the transition sets `status` to `SUSPENDED` and, as a
        second-order effect, closes the network — every physician of that agreement
        whose `panel_status` is `OPEN` is set to `CLOSED_TO_NEW`, and each such
        physician's `version` advances."

        Design: Corner/state_machines/agreement_suspend_closes_open_panels_and_reinstate_does_not_reopen
        """
        agreement, open_physician, _closed_physician = (
            _an_agreement_with_one_open_and_one_closed_panel(api)
        )

        suspended = validate_success(
            api.set_agreement_state(
                agreement["id"], state_payload("SUSPENDED"), IPA_ADMIN_HEADERS
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED"

        rows, meta = _list_panels(api, agreement["id"], "CLOSED_TO_NEW")
        assert meta["total_count"] == 2
        assert len(rows) == 2
        assert_fields(
            read_physician(api, open_physician["id"]),
            {"panel_status": "CLOSED_TO_NEW", "credential_status": "ACTIVE"},
        )

    def test_reinstatement_does_not_reopen_the_closed_panels(self, api):
        """PRD §3.1: "It deliberately does not reopen anything: panels closed by
        the suspension stay `CLOSED_TO_NEW` until a `NetworkManager` reopens them
        one at a time."

        Design: Corner/state_machines/agreement_suspend_closes_open_panels_and_reinstate_does_not_reopen
        """
        agreement, _open_physician, _closed_physician = (
            _an_agreement_with_one_open_and_one_closed_panel(api)
        )
        validate_success(
            api.set_agreement_state(
                agreement["id"], state_payload("SUSPENDED"), IPA_ADMIN_HEADERS
            ),
            200,
        )

        reinstated = validate_success(_activate(api, agreement["id"]), 200)
        assert reinstated["status"] == "ACTIVE"

        rows, meta = _list_panels(api, agreement["id"], "OPEN")
        assert meta["total_count"] == 0
        assert rows == []
        still_closed, closed_meta = _list_panels(api, agreement["id"], "CLOSED_TO_NEW")
        assert closed_meta["total_count"] == 2
        assert all(row["panel_status"] == "CLOSED_TO_NEW" for row in still_closed)


class TestAgreementUndeclaredTransition:
    def test_draft_straight_to_terminated_is_refused_and_bumps_nothing(self, api):
        """PRD §3.1: "From either `ACTIVE` or `SUSPENDED`, an agreement may move to
        `TERMINATED` only when no risk pool of that agreement is in
        `ACCUMULATING`, `CLOSED_FOR_INCURRAL`, `RESERVED` or
        `SETTLEMENT_PROPOSED` — in other words, every pool must already be
        `SETTLED`."

        Design: Corner/state_machines/agreement_draft_to_terminated_is_not_a_declared_transition
        """
        draft = _a_draft_agreement(api)

        response = api.set_agreement_state(
            draft["id"], state_payload("TERMINATED"), IPA_ADMIN_HEADERS
        )
        validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)

        after = read_agreement(api, draft["id"])
        assert_fields(after, {"status": "DRAFT", "version": draft["version"]})


def _a_terminated_agreement(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Terminal Health", quality_withhold_bps=0
    )
    terminated = validate_success(
        api.set_agreement_state(
            agreement["id"], state_payload("TERMINATED"), IPA_ADMIN_HEADERS
        ),
        200,
    )
    assert terminated["status"] == "TERMINATED"
    return agreement


class TestTerminatedAgreementLockdown:
    def test_a_terminated_agreement_refuses_reactivation(self, api):
        """PRD §3.1: "`TERMINATED` is terminal; no transition leads out of it."

        Design: Corner/state_machines/terminated_agreement_rejects_reactivation
        """
        agreement = _a_terminated_agreement(api)

        validate_error(
            _activate(api, agreement["id"]), ERR_INVALID_STATE_TRANSITION, 409
        )
        assert read_agreement(api, agreement["id"])["status"] == "TERMINATED"

    def test_a_terminated_agreement_also_refuses_suspension(self, api):
        """PRD §3.1: "Termination is a one-way door and it is gated on the risk
        pools."

        Design: Corner/state_machines/terminated_agreement_rejects_reactivation
        """
        agreement = _a_terminated_agreement(api)

        response = api.set_agreement_state(
            agreement["id"], state_payload("SUSPENDED"), IPA_ADMIN_HEADERS
        )
        validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)
        assert read_agreement(api, agreement["id"])["status"] == "TERMINATED"


def _a_credentialed_physician(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Idempotency Health", quality_withhold_bps=0
    )
    physician = create_physician(api, agreement["id"], full_name="Ines Kaburu")
    return credential_physician(api, physician["id"])


class TestPhysicianCredentialReplay:
    def test_replaying_credentialed_is_refused_rather_than_a_no_op(self, api):
        """PRD §3.2: "On the contracting dimension, a `NetworkManager` advances
        `APPLICANT → CREDENTIALED` — permitted when `credential_status` is
        `APPLICANT` and the parent agreement's `status` is `ACTIVE` — and then
        `CREDENTIALED → ACTIVE`, permitted when `credential_status` is
        `CREDENTIALED` and the agreement is again `ACTIVE`."

        Design: Corner/state_machines/second_credentialed_transition_rejected_as_not_idempotent
        """
        credentialed = _a_credentialed_physician(api)
        assert credentialed["credential_status"] == "CREDENTIALED"

        response = api.set_physician_state(
            credentialed["id"], state_payload("CREDENTIALED"), NETWORK_MANAGER_HEADERS
        )
        validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)

        after = read_physician(api, credentialed["id"])
        assert_fields(
            after,
            {
                "credential_status": "CREDENTIALED",
                "version": credentialed["version"],
            },
        )


def _an_unfunded_pool_holding_an_approved_claim(api):
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Conditional Health", quality_withhold_bps=0
    )
    physician = create_active_physician(api, agreement["id"], full_name="Noor Baptiste")
    pool = create_pool(
        api,
        agreement["id"],
        pool_type="PROFESSIONAL",
        pool_year_start="2026-01-01T00:00:00Z",
        pool_year_end="2026-12-31T23:59:59Z",
    )
    enrollee = create_enrollee(api, agreement["id"], external_member_id="S9-0001")
    assign_enrollee(api, enrollee["id"], physician["id"])
    claim = build_approved_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        50000,
        downstream_provider_name="Northside Cardiology",
        service_date="2026-06-15T00:00:00Z",
    )
    return agreement, physician, pool, enrollee, claim


class TestPaymentAgainstAnUnfundedPool:
    def test_an_unfunded_pool_reads_a_zero_loss_ratio_and_no_deficit(self, api):
        """PRD §3.5: "When `funded_cents` is zero, `loss_ratio_bps` is 0."

        Design: Corner/state_machines/paid_claim_against_unfunded_pool_leaves_capitation_posture_current
        """
        _agreement, _physician, pool, _enrollee, claim = (
            _an_unfunded_pool_holding_an_approved_claim(api)
        )
        assert pool["funded_cents"] == 0

        paid = pay_claim_state(api, claim["id"])
        assert_fields(paid, {"status": "PAID", "paid_cents": 50000})

        after = read_pool(api, pool["id"])
        assert after["funded_cents"] == 0
        assert after["paid_claims_cents"] == 50000
        assert_pool_loss_position(after, 0, False)

    def test_the_posture_and_the_panel_are_left_untouched_by_the_payment(self, api):
        """PRD §2.9: "When an agreement's `capitation_posture` leaves `CURRENT`,
        every physician of that agreement whose `panel_status` is `OPEN` is closed
        to new members."

        Design: Corner/state_machines/paid_claim_against_unfunded_pool_leaves_capitation_posture_current
        """
        agreement, physician, _pool, _enrollee, claim = (
            _an_unfunded_pool_holding_an_approved_claim(api)
        )
        pay_claim_state(api, claim["id"])

        assert read_agreement(api, agreement["id"])["capitation_posture"] == "CURRENT"
        assert read_physician(api, physician["id"])["panel_status"] == "OPEN"

    def test_the_enrollee_ledger_still_absorbs_the_payment(self, api):
        """PRD §3.6: "Third, because the pool's paid ledger moved, the enrollee's
        `cumulative_paid_claims_cents` increases by the same amount, and when that
        enrollee's paid total within this pool comes to strictly exceed the
        agreement's `stop_loss_attachment_cents` for the first time, the pool's
        `stop_loss_eligible_enrollee_count` increases by 1."

        Design: Corner/state_machines/paid_claim_against_unfunded_pool_leaves_capitation_posture_current
        """
        _agreement, _physician, pool, enrollee, claim = (
            _an_unfunded_pool_holding_an_approved_claim(api)
        )
        assert enrollee["cumulative_paid_claims_cents"] == 0

        pay_claim_state(api, claim["id"])

        assert read_enrollee(api, enrollee["id"])["cumulative_paid_claims_cents"] == 50000
        assert read_pool(api, pool["id"])["stop_loss_eligible_enrollee_count"] == 0
