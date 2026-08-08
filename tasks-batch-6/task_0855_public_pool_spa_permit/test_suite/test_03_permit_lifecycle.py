"""Permit application gating, the suspend/reinstate cycle, revocation and expiry."""

from test_helpers import (
    ADMIN,
    ADMIN_ONE_ID,
    ApiErrorId,
    advance_permit_to_under_review,
    apply_for_permit,
    assert_posture,
    fee_balance,
    issue_permit,
    read_facility,
    read_permit,
    set_clock,
    setup_facility_with_issued_permit,
    setup_operator_and_pool,
    setup_operator_with_two_pools,
    submit_plan_review,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Application-time gating
# --------------------------------------------------------------------------


def test_new_permit_starts_in_draft_and_cannot_be_issued_from_there(api):
    """PRD 3.3: The permit is created in `DRAFT` with `assessed_fee_cents` of 0
    and `fee_variant` of null; neither is populated before issuance.
    PRD 3.3: `term_end_date` is, for an annual permit, the day 364 days after
    `term_start_date`, giving a 365-day term counted inclusively; for a seasonal
    permit it is simply the facility's `season_end_date` as it stands at
    application time.
    PRD 2.6: **Permit state precondition**, including the guard that expiry
    requires the clock date to be strictly past `term_end_date` →
    `ERR_INVALID_PERMIT_STATE` (409), on `POST /permits/{id}/transition`.

    Design: Corner/state_machines/permit_starts_in_draft_and_issue_from_draft_rejected
    """
    ctx = setup_operator_and_pool()
    permit = apply_for_permit(ctx["facility_id"], ctx["op_headers"])

    assert permit["status"] == "DRAFT"
    assert permit["assessed_fee_cents"] == 0
    assert permit["fee_variant"] is None
    assert permit["term_end_date"] == "2027-04-30"
    assert permit["term_days"] == 365

    validate_error(
        api.transition_permit(permit["id"], {"action": "ISSUE"}, ADMIN),
        ApiErrorId.ERR_INVALID_PERMIT_STATE.value, 409,
    )

    assert read_permit(permit["id"])["status"] == "DRAFT"
    assert fee_balance(ctx["operator_id"]) == 0


def test_submitting_the_same_permit_twice_is_rejected(api):
    """PRD 3.3: From `DRAFT` the operator submits the application, advancing
    `DRAFT → SUBMITTED`.
    PRD 2.6: **Permit state precondition**, including the guard that expiry
    requires the clock date to be strictly past `term_end_date` →
    `ERR_INVALID_PERMIT_STATE` (409), on `POST /permits/{id}/transition`.

    Design: Corner/state_machines/permit_submit_twice_rejected_on_second_attempt
    """
    ctx = setup_operator_and_pool()
    permit = apply_for_permit(ctx["facility_id"], ctx["op_headers"])
    submitted = validate_success(
        api.transition_permit(permit["id"], {"action": "SUBMIT"}, ctx["op_headers"])
    )

    validate_error(
        api.transition_permit(permit["id"], {"action": "SUBMIT"}, ctx["op_headers"]),
        ApiErrorId.ERR_INVALID_PERMIT_STATE.value, 409,
    )

    after = read_permit(permit["id"])
    assert after["status"] == "SUBMITTED"
    assert after["version"] == submitted["version"], (
        "A rejected transition writes nothing, so the version must not move"
    )


def test_overlapping_permit_term_rejected(api):
    """PRD 3.3: The requested term may not intersect the term of any other
    permit of the same facility whose status is `SUBMITTED`, `UNDER_REVIEW` or
    `ISSUED`; both ends of both intervals are inclusive, so two terms that merely
    touch on a single shared day already conflict, and the application is
    rejected with `ERR_PERMIT_TERM_OVERLAP`.

    Design: Corner/validations/permit_term_overlap_rejected
    """
    ctx = setup_operator_and_pool()
    first = apply_for_permit(ctx["facility_id"], ctx["op_headers"])
    validate_success(
        api.transition_permit(first["id"], {"action": "SUBMIT"}, ctx["op_headers"])
    )

    validate_error(
        api.create_permit(
            {
                "facility_id": ctx["facility_id"],
                "permit_type": "ANNUAL",
                "term_start_date": "2026-06-01",
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_PERMIT_TERM_OVERLAP.value, 409,
    )

    rows, meta = validate_paginated(
        api.list_permits(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == first["id"]


def test_application_filed_beyond_the_renewal_window_rejected(api):
    """PRD 3.3: The `term_start_date` may be at most 60 days after the
    logical-clock date — an application filed further ahead than that is
    `ERR_RENEWAL_WINDOW_NOT_OPEN`.

    Design: Corner/validations/permit_filed_too_far_ahead_rejected
    """
    ctx = setup_operator_and_pool()

    validate_error(
        api.create_permit(
            {
                "facility_id": ctx["facility_id"],
                "permit_type": "ANNUAL",
                "term_start_date": "2026-08-01",
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value, 409,
    )

    rows, meta = validate_paginated(
        api.list_permits(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_seasonal_application_for_a_season_beyond_the_cap_rejected(api):
    """PRD 3.3: A `SEASONAL` application requires the facility to be seasonal and
    its declared season — counted inclusively from `season_start_date` to
    `season_end_date` — to run no longer than 183 days; otherwise
    `ERR_SEASON_TERM_TOO_LONG`.

    Design: Corner/validations/seasonal_permit_for_season_longer_than_the_cap_rejected
    """
    ctx = setup_operator_and_pool(
        operator_overrides={
            "legal_name": "Yearlong Swim Club",
            "contact_email": "club@yearlong.example",
        },
        name="Club Pool",
        is_seasonal=True,
        season_start_date="2026-01-01",
        season_end_date="2026-12-31",
    )

    validate_error(
        api.create_permit(
            {
                "facility_id": ctx["facility_id"],
                "permit_type": "SEASONAL",
                "term_start_date": "2026-05-01",
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_SEASON_TERM_TOO_LONG.value, 422,
    )

    rows, meta = validate_paginated(
        api.list_permits(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_application_naming_another_venues_plan_review_rejected(api):
    """PRD 3.3: That plan review must be filed for the same facility, or the
    application is rejected with `ERR_PLAN_REVIEW_FACILITY_MISMATCH`; and a
    facility that requires plan review with no `plan_review_id` on the
    application is rejected with `ERR_PLAN_REVIEW_NOT_APPROVED`.

    Design: Corner/validations/permit_application_referencing_another_facilitys_plan_review_rejected
    """
    ctx = setup_operator_with_two_pools(
        operator_overrides={
            "legal_name": "Twin Pools Trust",
            "contact_email": "ops@twinpools.example",
        }
    )
    review_for_a = submit_plan_review(
        ctx["facility_a_id"], ctx["op_headers"], project_type="ALTERATION",
        drawing_reference="DR-A",
    )

    validate_error(
        api.create_permit(
            {
                "facility_id": ctx["facility_b_id"],
                "permit_type": "ANNUAL",
                "term_start_date": "2026-05-01",
                "plan_review_id": review_for_a["id"],
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_PLAN_REVIEW_FACILITY_MISMATCH.value, 409,
    )

    rows, meta = validate_paginated(
        api.list_permits(ADMIN, params={"facility_id": ctx["facility_b_id"]})
    )
    assert meta["total_count"] == 0 and rows == []


# --------------------------------------------------------------------------
# Terminal states, expiry and refunds
# --------------------------------------------------------------------------


def test_revoked_permit_is_terminal(api):
    """PRD 3.4: `DENIED`, `REVOKED` and `EXPIRED` are terminal; nothing leaves
    them.
    PRD 3.4: Revocation without a refund posts nothing.
    PRD 2.9: The facility has permit records but none whose status is `ISSUED` →
    `CLOSED` with reason `PERMIT_NOT_ACTIVE`.

    Design: Corner/state_machines/permit_revoked_is_terminal_and_further_transitions_rejected
    """
    ctx = setup_facility_with_issued_permit()
    validate_success(
        api.transition_permit(
            ctx["permit_id"],
            {"action": "REVOKE", "reason": "Repeated non-compliance"},
            ADMIN,
        )
    )

    validate_error(
        api.transition_permit(ctx["permit_id"], {"action": "SUSPEND"}, ADMIN),
        ApiErrorId.ERR_INVALID_PERMIT_STATE.value, 409,
    )

    permit = read_permit(ctx["permit_id"])
    assert permit["status"] == "REVOKED"
    assert permit["refunded"] is False
    assert fee_balance(ctx["operator_id"]) == 40000
    assert_posture(read_facility(ctx["facility_id"]), "CLOSED", "PERMIT_NOT_ACTIVE")


def test_expiry_is_refused_until_the_clock_passes_the_term_end(api):
    """PRD 3.4: Expiry is likewise reachable from both `ISSUED` and `SUSPENDED`
    with identical behaviour, and carries one temporal guard: the logical-clock
    date must be strictly past the permit's `term_end_date`. An expiry requested
    on or before the last day of the term is rejected as an invalid permit state.

    Design: Corner/state_machines/permit_expire_before_term_end_rejected_then_allowed_after
    """
    ctx = setup_facility_with_issued_permit()

    validate_error(
        api.transition_permit(ctx["permit_id"], {"action": "EXPIRE"}, ADMIN),
        ApiErrorId.ERR_INVALID_PERMIT_STATE.value, 409,
    )

    set_clock("2027-05-01T00:00:00Z")
    expired = validate_success(
        api.transition_permit(ctx["permit_id"], {"action": "EXPIRE"}, ADMIN)
    )

    assert expired["status"] == "EXPIRED"
    assert_posture(read_facility(ctx["facility_id"]), "CLOSED", "PERMIT_NOT_ACTIVE")


def test_refund_outside_the_thirty_day_window_rejected(api):
    """PRD 3.4: When it is true, two conditions must hold: the permit's
    `refunded` flag must still be false, and the logical-clock date must be on or
    before the day 30 days after `term_start_date`. A request that fails either
    is rejected with `ERR_REFUND_NOT_ELIGIBLE`.

    Design: Corner/validations/refund_requested_after_the_refund_window_rejected
    """
    ctx = setup_facility_with_issued_permit(
        permit_overrides={"term_start_date": "2026-04-01"}
    )
    set_clock("2026-05-02T00:00:00Z")

    validate_error(
        api.transition_permit(
            ctx["permit_id"], {"action": "REVOKE", "refund_eligible": True}, ADMIN
        ),
        ApiErrorId.ERR_REFUND_NOT_ELIGIBLE.value, 409,
    )

    permit = read_permit(ctx["permit_id"])
    assert permit["status"] == "ISSUED", (
        "A refused refund leaves the revocation itself un-applied"
    )
    assert permit["refunded"] is False
    assert fee_balance(ctx["operator_id"]) == 50000


# --------------------------------------------------------------------------
# The ISSUED -> SUSPENDED -> ISSUED cycle
# --------------------------------------------------------------------------


class TestSuspendReinstateCycle:
    """A permit may re-enter a state it already occupied without losing history."""

    def test_suspension_records_the_administrative_reason_and_closes_the_venue(
        self, api
    ):
        """PRD 3.4: Suspending an issued permit sets `suspension_reason` to
        `ADMINISTRATIVE` when an administrator takes the action deliberately, and
        to `IMMINENT_HEALTH_HAZARD` when the suspension arrives instead through
        the inspection enforcement cascade described in Section 3.6.
        PRD 3.4: Either way the facility's `operating_posture` is recomputed —
        with no `ISSUED` permit remaining, clause 3 of the posture gate fires and
        the venue reads `CLOSED` with `posture_reason` of `PERMIT_NOT_ACTIVE` —
        along with `posture_reason` and `active_permit_id`, and the facility's
        `version` climbs by 1.

        Design: Difficulty/non_linear_state_machine/permit_issued_suspended_reinstated_cycle
        """
        ctx = setup_facility_with_issued_permit()
        assert ctx["permit"]["assessed_fee_cents"] == 40000

        suspended = validate_success(
            api.transition_permit(
                ctx["permit_id"],
                {
                    "action": "SUSPEND",
                    "reason": "Operator failed to file monthly chemistry logs",
                },
                ADMIN,
            )
        )

        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "ADMINISTRATIVE"
        assert_posture(
            read_facility(ctx["facility_id"]), "CLOSED", "PERMIT_NOT_ACTIVE"
        )

    def test_reinstatement_restores_the_permit_without_a_second_fee(self, api):
        """PRD 3.4: On success `suspension_reason` is cleared back to null and the
        facility's posture fields and `version` are refreshed.
        PRD 3.4: `issued_at` and `issued_by_user_id` are preserved across
        suspension; they are not cleared and not restamped.
        PRD 2.9: At least one signage type in the facility's
        `required_signage_types` has no compliance artifact of type `SIGNAGE` for
        this facility with that `signage_type` and status `ACTIVE` → `RESTRICTED`
        with reason `SIGNAGE_INCOMPLETE`.

        Design: Difficulty/non_linear_state_machine/permit_issued_suspended_reinstated_cycle
        """
        ctx = setup_facility_with_issued_permit()
        issued_at_before = ctx["permit"]["issued_at"]
        assert issued_at_before == "2026-05-01T00:00:00.000Z"

        validate_success(
            api.transition_permit(
                ctx["permit_id"], {"action": "SUSPEND"}, ADMIN
            )
        )
        reinstated = validate_success(
            api.transition_permit(ctx["permit_id"], {"action": "REINSTATE"}, ADMIN)
        )

        assert reinstated["status"] == "ISSUED"
        assert reinstated["suspension_reason"] is None
        assert reinstated["issued_at"] == issued_at_before
        assert reinstated["issued_by_user_id"] == ADMIN_ONE_ID
        assert reinstated["assessed_fee_cents"] == 40000
        assert_posture(
            read_facility(ctx["facility_id"]), "RESTRICTED", "SIGNAGE_INCOMPLETE"
        )

        rows, meta = validate_paginated(
            api.list_fee_ledger_entries(
                ADMIN, params={"operator_id": ctx["operator_id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "Neither suspension nor reinstatement posts a ledger entry"
        )
        assert rows[0]["entry_type"] == "PERMIT_FEE"
        assert fee_balance(ctx["operator_id"]) == 40000


# --------------------------------------------------------------------------
# Error precedence: state precondition outranks the drain-safety gate
# --------------------------------------------------------------------------


class TestIssueStateErrorOutranksVgbGate:
    """One request breaching both checks must report the earlier ladder rung."""

    @staticmethod
    def _setup():
        ctx = setup_facility_with_issued_permit(
            operator_overrides={
                "legal_name": "Harbour Club",
                "contact_email": "club@harbour.example",
            },
            name="Harbour Club Pool",
            water_volume_gallons=20000,
            max_depth_feet=9,
            drain_count=1,
        )
        set_clock("2026-06-15T00:00:00Z")
        return ctx

    def test_reissue_reports_the_state_error_rather_than_the_drain_safety_error(
        self, api
    ):
        """PRD 2.6: When a single request could fail several checks at once, the
        outcome is deterministic: checks run in the fixed order below and the
        first failure decides the response.
        PRD 2.6: **Permit state precondition**, including the guard that expiry
        requires the clock date to be strictly past `term_end_date` →
        `ERR_INVALID_PERMIT_STATE` (409), on `POST /permits/{id}/transition`.
        PRD 3.8: When the facility has no drain certification at all,
        `vgb_compliance_status` is `NONCOMPLIANT`.

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_error_outranks_vgb_safety_error
        """
        ctx = self._setup()

        response = api.transition_permit(
            ctx["permit_id"], {"action": "ISSUE"}, ADMIN
        )

        validate_error(response, ApiErrorId.ERR_INVALID_PERMIT_STATE.value, 409)
        assert response.json()["data"]["error_id"] != "ERR_VGB_NONCOMPLIANT"
        assert response.json()["data"]["error_id"] != "ERR_OUTSTANDING_FEES"

        # The drain-safety gate genuinely applies at this clock, which is what
        # makes the precedence observable.
        assert (
            read_facility(ctx["facility_id"])["vgb_compliance_status"]
            == "NONCOMPLIANT"
        )

    def test_rejected_reissue_leaves_the_permit_and_the_ledger_untouched(self, api):
        """PRD 3.3: Step one takes the base fee from the facility's class **as it
        stands at the instant of issuance** — 45000 cents for
        `CLASS_A_COMPETITION`, 30000 cents for `CLASS_B_PUBLIC`, 18000 cents for
        `CLASS_C_SEMI_PUBLIC` and 12000 cents for `SPA`
        PRD 3.3: **Fee assessment** runs exactly once, at issuance, and writes
        `assessed_fee_cents` and `fee_variant`.

        Design: Difficulty/priority_pair_validation_conflict/permit_issue_state_error_outranks_vgb_safety_error
        """
        ctx = self._setup()
        validate_error(
            api.transition_permit(ctx["permit_id"], {"action": "ISSUE"}, ADMIN),
            ApiErrorId.ERR_INVALID_PERMIT_STATE.value, 409,
        )

        permit = read_permit(ctx["permit_id"])
        assert permit["status"] == "ISSUED"
        assert permit["assessed_fee_cents"] == 30000
        assert fee_balance(ctx["operator_id"]) == 30000

        rows, meta = validate_paginated(
            api.list_fee_ledger_entries(
                ADMIN, params={"operator_id": ctx["operator_id"]}
            )
        )
        assert meta["total_count"] == 1, "No second PERMIT_FEE may be posted"
        assert rows[0]["amount_cents"] == 30000


# --------------------------------------------------------------------------
# Money is conserved across issuance and refund
# --------------------------------------------------------------------------


class TestRefundRestoresTheFeeBalance:
    """Issuing then refunding a late permit returns the balance with zero drift."""

    def test_late_application_assesses_the_quarter_penalty_on_top_of_the_subtotal(
        self, api
    ):
        """PRD 3.3: `is_late_application` is true when `applied_on` falls strictly
        after `term_start_date`, meaning the operator filed after the term had
        already begun.
        PRD 3.3: Step five applies the late penalty to the post-proration
        subtotal: when `is_late_application` is true the penalty is one quarter of
        the subtotal, rounded half up to whole cents; otherwise it is zero.

        Design: Difficulty/compensating_invariant/permit_refund_restores_operator_fee_balance_exactly
        """
        ctx = _setup_late_issued_permit()

        permit = ctx["permit"]
        assert permit["is_late_application"] is True
        assert permit["term_end_date"] == "2027-03-31"
        assert permit["assessed_fee_cents"] == 50000
        assert fee_balance(ctx["operator_id"]) == 50000

    def test_revoking_with_a_refund_returns_the_balance_to_its_pre_issuance_value(
        self, api
    ):
        """PRD 3.4: When the refund is honoured, a single ledger entry of
        `entry_type` `REFUND` is posted against this permit for the negation of
        the sum of that permit's own `PERMIT_FEE` and `LATE_PENALTY` postings,
        `refunded` is set to true, and the operator's `fee_balance_cents` is
        refreshed — returning the balance to exactly its pre-issuance value.
        PRD 2.8: An operator's `fee_balance_cents` is the sum of `amount_cents`
        over every ledger posting whose `operator_id` is that operator, with no
        status filter and no time filter — the whole append-only history is
        always in scope.

        Design: Difficulty/compensating_invariant/permit_refund_restores_operator_fee_balance_exactly
        """
        ctx = _setup_late_issued_permit()
        assert fee_balance(ctx["operator_id"]) == 50000

        revoked = validate_success(
            api.transition_permit(
                ctx["permit"]["id"],
                {
                    "action": "REVOKE",
                    "reason": "Operator surrendered the permit",
                    "refund_eligible": True,
                },
                ADMIN,
            )
        )

        assert revoked["status"] == "REVOKED"
        assert revoked["refunded"] is True

        rows, meta = validate_paginated(
            api.list_fee_ledger_entries(
                ADMIN, params={"operator_id": ctx["operator_id"]}
            )
        )
        assert meta["total_count"] == 3
        assert [row["amount_cents"] for row in rows] == [40000, 10000, -50000]

        balance = fee_balance(ctx["operator_id"])
        assert balance == 0
        assert balance == sum(row["amount_cents"] for row in rows)


def _setup_late_issued_permit():
    """A CLASS_B_PUBLIC pool whose annual term began a month before the clock."""
    ctx = setup_operator_and_pool()
    permit = apply_for_permit(
        ctx["facility_id"], ctx["op_headers"], term_start_date="2026-04-01"
    )
    ctx["permit"] = issue_permit(permit["id"], ctx["op_headers"])
    return ctx
