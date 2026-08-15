"""Monthly agreements: pool capacity, proration, lifecycle cycles, waitlist,
and credential media lifecycle with deposit liability conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    create_facility,
    create_parker,
    get_facility,
    get_success_data,
    issue_credential,
    make_monthly_parker_headers,
    run_close_of_business,
    set_clock,
    submit_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]


class TestMonthlyPoolActivationBoundary:
    """With monthly_capacity 2 and exactly 2 ACTIVE, a third APPROVED
    agreement cannot activate — the equality boundary is exclusionary."""

    def _build(self, api):
        facility = create_facility(name="Pool Fac", monthly_capacity=2)
        agreements = []
        for i in range(3):
            parker = create_parker(full_name=f"A {'One Two Three'.split()[i]}",
                                   email=f"a{i + 1}@x.com")
            agreements.append(submit_agreement(facility["id"], parker["id"]))
        activate_agreement(agreements[0]["id"])
        activate_agreement(agreements[1]["id"])
        return facility, agreements

    def test_third_activation_rejected_at_capacity(self, api):
        """PRD: "Activation — moving an `APPROVED` agreement to `ACTIVE` —
        requires the same strict headroom and refuses with
        `ERR_MONTHLY_POOL_EXHAUSTED` when the facility already holds exactly
        `monthly_capacity` allocated agreements; the boundary is exclusionary,
        so equality blocks."

        Design: Difficulty/boundary_precision_check/monthly_pool_activation_at_capacity_rejected
        """
        facility, agreements = self._build(api)
        res = api.activate_agreement(agreements[2]["id"], ATT)
        validate_error(res, ApiErrorId.ERR_MONTHLY_POOL_EXHAUSTED)

    def test_rejected_activation_leaves_pool_unchanged(self, api):
        """PRD: "The *allocated* count is the agreements standing `ACTIVE` or
        `SUSPENDED`; the *committed* count adds those standing `APPROVED`."

        Design: Difficulty/boundary_precision_check/monthly_pool_activation_at_capacity_rejected
        """
        facility, agreements = self._build(api)
        validate_error(api.activate_agreement(agreements[2]["id"], ATT),
                       ApiErrorId.ERR_MONTHLY_POOL_EXHAUSTED)
        third = get_success_data(api.get_monthly_agreement(agreements[2]["id"], FM))
        assert third["agreement_status"] == "APPROVED"
        first = get_success_data(api.get_monthly_agreement(agreements[0]["id"], FM))
        second = get_success_data(api.get_monthly_agreement(agreements[1]["id"], FM))
        assert first["agreement_status"] == "ACTIVE"
        assert second["agreement_status"] == "ACTIVE"


class TestAgreementActiveSuspendedCycle:
    """The ACTIVE <-> SUSPENDED cyclic pair traversed twice on one agreement."""

    def _build_active(self, api):
        facility = create_facility(name="Cyc Fac")
        parker = create_parker(full_name="Cy Cled", email="cy@x.com")
        agreement = submit_agreement(facility["id"], parker["id"],
                                     monthly_rate_cents=15000)
        return activate_agreement(agreement["id"])

    def test_suspend_resume_cycle_traversed_twice(self, api):
        """PRD: "An `ACTIVE` agreement may be suspended by a `FacilityManager`
        (`ACTIVE` to `SUSPENDED`) and later resumed (`SUSPENDED` back to
        `ACTIVE`)"

        Design: Difficulty/non_linear_state_machine/monthly_agreement_active_suspended_cycle
        """
        agreement = self._build_active(api)
        assert validate_success(api.suspend_agreement(agreement["id"], FM))[
            "agreement_status"] == "SUSPENDED"
        assert validate_success(api.resume_agreement(agreement["id"], FM))[
            "agreement_status"] == "ACTIVE"
        assert validate_success(api.suspend_agreement(agreement["id"], FM))[
            "agreement_status"] == "SUSPENDED"
        final = validate_success(api.resume_agreement(agreement["id"], FM))
        assert final["agreement_status"] == "ACTIVE", "cycle traversed twice"

    def test_each_transition_increments_version_by_one(self, api):
        """PRD: "The `version` field is an integer that increments by one on
        every mutation of the resource, including mutations driven by a
        cascade from another resource"

        Design: Difficulty/non_linear_state_machine/monthly_agreement_active_suspended_cycle
        """
        agreement = self._build_active(api)
        v_active = agreement["version"]
        assert validate_success(api.suspend_agreement(agreement["id"], FM))[
            "version"] == v_active + 1
        assert validate_success(api.resume_agreement(agreement["id"], FM))[
            "version"] == v_active + 2
        assert validate_success(api.suspend_agreement(agreement["id"], FM))[
            "version"] == v_active + 3
        final = validate_success(api.resume_agreement(agreement["id"], FM))
        assert final["version"] == v_active + 4


class TestProrationComponentRounding:
    """Per-component round-half-up before summation is the pinned order."""

    def _build(self, api):
        facility = create_facility(name="Pro Fac")
        parker = create_parker(full_name="Pat Parker", email="pat@x.com")
        agreement = submit_agreement(facility["id"], parker["id"], tier="EV",
                                     monthly_rate_cents=19999,
                                     ev_surcharge_cents=2999)
        set_clock("2026-08-14T09:00:00Z")
        return agreement

    def test_first_invoice_rounds_per_component_then_sums(self, api):
        """PRD: "Summing the unrounded components and rounding once is
        explicitly not the rule — with a rate of 19,999 cents and an EV
        surcharge of 2,999 cents activated with 18 of 31 days remaining, the
        per-component order yields 11,612 plus 1,741 equals 13,353 cents,
        where sum-then-round would yield 13,354."
        PRD: "the remaining days be the days-in-month minus the day-of-month
        of activation plus one — the activation day itself counts."

        Design: Difficulty/combinatorial_formula/monthly_proration_component_rounding_mode_b
        """
        agreement = self._build(api)
        activated = validate_success(api.activate_agreement(agreement["id"], ATT), 200)
        assert activated["first_invoice_cents"] == 13353, (
            "round_half_up(19999*18/31)=11612 plus round_half_up(2999*18/31)=1741")
        assert activated["first_invoice_cents"] != 13354

    def test_activation_stamps_active_status_and_time(self, api):
        """PRD: "A successful activation stamps `activated_at` with the
        logical now and computes `first_invoice_cents` by proration."

        Design: Difficulty/combinatorial_formula/monthly_proration_component_rounding_mode_b
        """
        agreement = self._build(api)
        activated = validate_success(api.activate_agreement(agreement["id"], ATT), 200)
        assert activated["agreement_status"] == "ACTIVE"
        assert activated["activated_at"].startswith("2026-08-14T09:00")


def test_agreement_withdraw_from_waitlisted(api):
    """PRD: "A `WAITLISTED` agreement may instead be withdrawn to the terminal
    `WITHDRAWN` by a `FacilityManager`, a `ParkingAttendant`, or the owning
    `MonthlyParker`; a parker may withdraw only their own agreement, with
    ownership checked against the agreement's `parker_account_id`
    (`ERR_NOT_OWNER`)."
    PRD: "when the number of the facility's agreements standing `ACTIVE` or
    `SUSPENDED` is strictly below `monthly_capacity`, the new agreement is
    `APPROVED` on the spot; otherwise it falls to `WAITLISTED`."

    Design: Corner/state_machines/agreement_withdraw_from_waitlisted
    """
    facility = create_facility(name="WD Fac", monthly_capacity=1)
    p1 = create_parker(full_name="W One", email="w1@x.com")
    a1 = submit_agreement(facility["id"], p1["id"])
    activate_agreement(a1["id"])
    p2 = create_parker(full_name="W Two", email="w2@x.com")
    a2 = submit_agreement(facility["id"], p2["id"])
    assert a2["agreement_status"] == "WAITLISTED", "capacity 1 occupied by ACTIVE a1"

    withdrawn = validate_success(api.withdraw_agreement(
        a2["id"], make_monthly_parker_headers(p2["id"])), 200)
    assert withdrawn["agreement_status"] == "WITHDRAWN"


class TestCredentialIssueRequiresApprovedAgreement:
    """Issuance is gated on agreement state; a close-of-business promotion
    clears the gate."""

    def _build(self, api):
        facility = create_facility(name="Iss Fac", monthly_capacity=1)
        p1 = create_parker(full_name="I One", email="i1@x.com")
        a1 = submit_agreement(facility["id"], p1["id"])
        activate_agreement(a1["id"])
        p2 = create_parker(full_name="I Two", email="i2@x.com")
        a2 = submit_agreement(facility["id"], p2["id"])
        assert a2["agreement_status"] == "WAITLISTED"
        return facility, a1, a2

    def test_issuance_rejected_for_waitlisted_agreement(self, api):
        """PRD: "Issuance requires the agreement to stand `APPROVED` or
        `ACTIVE` (else `ERR_AGREEMENT_NOT_ISSUABLE`)"

        Design: Difficulty/cross_entity_state_dependency/credential_issue_requires_agreement_approved
        """
        facility, a1, a2 = self._build(api)
        res = api.create_credential(
            {"agreement_id": a2["id"], "credential_type": "BADGE",
             "deposit_cents": 5000}, ATT)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ISSUABLE)

    def test_issuance_succeeds_after_close_promotion(self, api):
        """PRD: "While the committed count is strictly below
        `monthly_capacity` and the waitlist is non-empty, the top-ranked
        `WAITLISTED` agreement promotes to `APPROVED` and the ranking
        recomputes."
        PRD: "A new credential stands `ACTIVE`, and the facility's
        `deposit_liability_cents` — the running sum of `deposit_cents` over
        all credentials standing `ACTIVE` or `LOST_REPORTED` — grows by the
        deposit."

        Design: Difficulty/cross_entity_state_dependency/credential_issue_requires_agreement_approved
        """
        facility, a1, a2 = self._build(api)
        validate_error(api.create_credential(
            {"agreement_id": a2["id"], "credential_type": "BADGE",
             "deposit_cents": 5000}, ATT), ApiErrorId.ERR_AGREEMENT_NOT_ISSUABLE)

        get_success_data(api.terminate_agreement(a1["id"], FM))
        set_clock("2026-08-01T23:00:00Z")
        summary = run_close_of_business(facility["id"])
        assert summary["agreements_promoted"] == 1
        promoted = get_success_data(api.get_monthly_agreement(a2["id"], FM))
        assert promoted["agreement_status"] == "APPROVED"

        credential = validate_success(api.create_credential(
            {"agreement_id": a2["id"], "credential_type": "BADGE",
             "deposit_cents": 5000}, ATT), 201)
        assert credential["credential_status"] == "ACTIVE"
        assert get_facility(facility["id"])["deposit_liability_cents"] == 5000


def test_credential_limit_two_per_agreement(api):
    """PRD: "an agreement may hold at most two credentials standing `ACTIVE`
    or `LOST_REPORTED` (else `ERR_CREDENTIAL_LIMIT`)"

    Design: Corner/validations/credential_limit_two_per_agreement
    """
    facility = create_facility(name="CL Fac")
    parker = create_parker(full_name="CL One", email="cl1@x.com")
    agreement = submit_agreement(facility["id"], parker["id"])
    issue_credential(agreement["id"], "BADGE", 1000)
    issue_credential(agreement["id"], "TRANSPONDER", 1000)

    res = api.create_credential(
        {"agreement_id": agreement["id"], "credential_type": "BADGE",
         "deposit_cents": 1000}, ATT)
    validate_error(res, ApiErrorId.ERR_CREDENTIAL_LIMIT)
    assert get_facility(facility["id"])["deposit_liability_cents"] == 2000, (
        "only the two issued credentials count")


def test_terminate_blocked_by_outstanding_credentials(api):
    """PRD: "Termination moves an agreement from `APPROVED`, `ACTIVE`, or
    `SUSPENDED` to the terminal `TERMINATED`, but only once no credential of
    the agreement still stands `ACTIVE` or `LOST_REPORTED` — outstanding media
    reject the termination with `ERR_CREDENTIALS_OUTSTANDING`."
    PRD: "Returning an `ACTIVE` or `LOST_REPORTED` credential moves it to the
    terminal `RETURNED` and refunds the deposit"

    Design: Corner/validations/terminate_blocked_by_outstanding_credentials
    """
    facility = create_facility(name="TC Fac")
    parker = create_parker(full_name="TC One", email="tc1@x.com")
    agreement = submit_agreement(facility["id"], parker["id"])
    activate_agreement(agreement["id"])
    credential = issue_credential(agreement["id"], "BADGE", 5000)

    res = api.terminate_agreement(agreement["id"], FM)
    validate_error(res, ApiErrorId.ERR_CREDENTIALS_OUTSTANDING)
    still = get_success_data(api.get_monthly_agreement(agreement["id"], FM))
    assert still["agreement_status"] == "ACTIVE"

    get_success_data(api.return_credential(credential["id"], ATT))
    terminated = validate_success(api.terminate_agreement(agreement["id"], FM), 200)
    assert terminated["agreement_status"] == "TERMINATED"


def test_credential_lost_found_cycle(api):
    """PRD: "The media lifecycle runs `ACTIVE` to `LOST_REPORTED` when the
    owning `MonthlyParker` or a `ParkingAttendant` reports the credential
    lost, and `LOST_REPORTED` back to `ACTIVE` when it is reported found;
    parker self-service is ownership-checked (`ERR_NOT_OWNER`)."
    PRD: "the facility's `deposit_liability_cents` — the running sum of
    `deposit_cents` over all credentials standing `ACTIVE` or `LOST_REPORTED`"

    Design: Corner/state_machines/credential_lost_found_cycle
    """
    facility = create_facility(name="LF Fac")
    parker = create_parker(full_name="LF One", email="lf1@x.com")
    agreement = submit_agreement(facility["id"], parker["id"])
    credential = issue_credential(agreement["id"], "BADGE", 5000)

    lost = validate_success(api.report_credential_lost(
        credential["id"], make_monthly_parker_headers(parker["id"])), 200)
    assert lost["credential_status"] == "LOST_REPORTED"
    found = validate_success(api.report_credential_found(
        credential["id"], make_monthly_parker_headers(parker["id"])), 200)
    assert found["credential_status"] == "ACTIVE"
    assert get_facility(facility["id"])["deposit_liability_cents"] == 5000, (
        "lost/found does not touch the liability: both states carry the deposit")


def test_credential_replace_links_self_reference(api):
    """PRD: "Replacement moves an `ACTIVE` or `LOST_REPORTED` credential to
    the terminal `REPLACED`: a successor credential is minted for the same
    agreement standing `ACTIVE` and carrying the same `deposit_cents` and the
    requested `credential_type`, the retired credential's
    `replaced_by_credential_id` points at its successor, the response presents
    the new credential"
    PRD: "The credential list filters by `agreement_id`, `credential_status`,
    or `replaced_by_credential_id`."

    Design: Corner/entities/credential_replace_links_self_reference
    """
    facility = create_facility(name="SelfRef Fac")
    parker = create_parker(full_name="SR One", email="sr1@x.com")
    agreement = submit_agreement(facility["id"], parker["id"])
    old = issue_credential(agreement["id"], "BADGE", 5000)

    new = validate_success(api.replace_credential(old["id"], "TRANSPONDER", ATT), 200)
    assert new["credential_status"] == "ACTIVE"
    assert new["id"] != old["id"]

    old_after = get_success_data(api.get_credential(old["id"], FM))
    assert old_after["credential_status"] == "REPLACED"
    assert old_after["replaced_by_credential_id"] == new["id"]

    data, meta = validate_paginated(api.list_credentials(
        FM, params={"replaced_by_credential_id": new["id"]}))
    assert [row["id"] for row in data] == [old["id"]]


class TestDepositLiabilityConservation:
    """Issue then return conserves deposit liability; replace holds it
    constant mid-cycle."""

    def _build(self, api):
        facility = create_facility(name="Inv3 Fac")
        parker = create_parker(full_name="Dep One", email="dep@x.com")
        agreement = submit_agreement(facility["id"], parker["id"])
        return facility, agreement

    def test_issue_grows_and_replace_holds_liability(self, api):
        """PRD: "A new credential stands `ACTIVE`, and the facility's
        `deposit_liability_cents` — the running sum of `deposit_cents` over
        all credentials standing `ACTIVE` or `LOST_REPORTED` — grows by the
        deposit."
        PRD: "the deposit liability is unchanged because the deposit carries
        over."

        Design: Difficulty/compensating_invariant/credential_issue_then_return_conserves_deposit_liability
        """
        facility, agreement = self._build(api)
        first = issue_credential(agreement["id"], "BADGE", 5000)
        assert get_facility(facility["id"])["deposit_liability_cents"] == 5000
        successor = validate_success(
            api.replace_credential(first["id"], "TRANSPONDER", ATT), 200)
        assert get_facility(facility["id"])["deposit_liability_cents"] == 5000, (
            "deposit carried to successor")

    def test_return_of_successor_restores_zero(self, api):
        """PRD: "Returning an `ACTIVE` or `LOST_REPORTED` credential moves it
        to the terminal `RETURNED` and refunds the deposit —
        `deposit_liability_cents` falls by `deposit_cents`."

        Design: Difficulty/compensating_invariant/credential_issue_then_return_conserves_deposit_liability
        """
        facility, agreement = self._build(api)
        first = issue_credential(agreement["id"], "BADGE", 5000)
        successor = validate_success(
            api.replace_credential(first["id"], "TRANSPONDER", ATT), 200)
        returned = validate_success(api.return_credential(successor["id"], ATT), 200)
        assert returned["credential_status"] == "RETURNED"
        assert get_facility(facility["id"])["deposit_liability_cents"] == 0, (
            "issue + return conserve the liability")


def test_waitlist_promotion_fifo_order(api):
    """PRD: "Ranking is chronological — earliest `created_at` first — with
    exact `created_at` ties broken by the lower `application_seq`; the record
    `id` is never a tiebreaker."
    PRD: "While the committed count is strictly below `monthly_capacity` and
    the waitlist is non-empty, the top-ranked `WAITLISTED` agreement promotes
    to `APPROVED` and the ranking recomputes."

    Design: Corner/calculations/waitlist_promotion_fifo_order
    """
    facility = create_facility(name="FIFO Fac", monthly_capacity=1)
    p1 = create_parker(full_name="F One", email="f1@x.com")
    a1 = submit_agreement(facility["id"], p1["id"])
    activate_agreement(a1["id"])

    set_clock("2026-08-01T10:00:00Z")
    p2 = create_parker(full_name="F Two", email="f2@x.com")
    a2 = submit_agreement(facility["id"], p2["id"])
    assert a2["agreement_status"] == "WAITLISTED"
    set_clock("2026-08-01T10:01:00Z")
    p3 = create_parker(full_name="F Three", email="f3@x.com")
    a3 = submit_agreement(facility["id"], p3["id"])
    assert a3["agreement_status"] == "WAITLISTED"

    get_success_data(api.terminate_agreement(a1["id"], FM))
    set_clock("2026-08-01T23:00:00Z")
    summary = run_close_of_business(facility["id"])
    assert summary["agreements_promoted"] == 1, "exactly one slot freed"

    a2_after = get_success_data(api.get_monthly_agreement(a2["id"], FM))
    a3_after = get_success_data(api.get_monthly_agreement(a3["id"], FM))
    assert a2_after["agreement_status"] == "APPROVED", "earlier created_at wins"
    assert a3_after["agreement_status"] == "WAITLISTED"
