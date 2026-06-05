"""Depth tests for validation-priority conflicts, cross-entity state dependencies,
and resource temporal-overlap / adjacency rules.

Queue A (Difficulty) translations for: priority_pair_validation_conflict,
cross_entity_state_dependency, and resource_temporal_overlap.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    make_producer_headers,
    setup_compliant_writer,
    create_quoted_policy,
    bind_policy,
    activate_policy,
    create_producer,
    create_license,
    setup_active_policy_no_split,
    setup_renewal_task_offered,
    set_clock,
    factories,
)

ADMIN = lambda: TEST_USERS["agency_admin_headers"]
MANAGER = lambda: TEST_USERS["account_manager_headers"]


# ===========================================================================
# Rule: priority_pair_validation_conflict / bind_state_beats_license_safety
# ===========================================================================
class TestBindStateBeatsLicenseSafety:
    def _bound_policy_with_lapsed_license(self):
        """A policy bound once while its producer's license was ACTIVE; then the clock is
        advanced past the license expiration so a second bind would also fail the safety
        check — but the policy is now BOUND (wrong state for bind)."""
        set_clock("2026-06-01T00:00:00Z")
        ctx = setup_compliant_writer(
            license_overrides={
                "effective_date": "2025-01-01T00:00:00Z",
                "expiration_date": "2026-06-15T00:00:00Z",
            }
        )
        policy = create_quoted_policy(
            ctx,
            annual_premium_cents=1_200_000,
            effective_date="2026-01-01T00:00:00Z",
            expiration_date="2027-01-01T00:00:00Z",
        )
        bound = bind_policy(ctx, policy["id"], policy["version"])
        set_clock("2026-07-01T00:00:00Z")  # license now EXPIRED.
        return ctx, bound

    def test_rebind_bound_policy_returns_invalid_state_not_license(self, api):
        """PRD §2.10: "then — for state-transition endpoints — whether the target is in a
        state from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409) ... Only
        after all of these pass are the domain-specific business rules (uniqueness, licensing,
        appointment, split allocation, temporal windows, fiscal floors, and the rest
        described throughout §3) evaluated."

        Design: Difficulty/priority_pair_validation_conflict/bind_state_beats_license_safety
        """
        ctx, bound = self._bound_policy_with_lapsed_license()
        resp = api.bind_policy(
            bound["id"], {"expected_policy_version": bound["version"]},
            make_producer_headers(ctx["producer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_rebind_leaves_policy_bound(self, api):
        """PRD §3.4: "A `QUOTED` policy created manually must be **bound** before it can come
        on risk, an action reserved to the `Producer` role. Binding transitions the policy
        `QUOTED → BOUND` and is gated by the full compliance check, evaluated against the
        writing producer named on the policy."
        A bind attempt against an already-BOUND policy is not a legal transition, so the
        policy stays BOUND.

        Design: Difficulty/priority_pair_validation_conflict/bind_state_beats_license_safety
        """
        ctx, bound = self._bound_policy_with_lapsed_license()
        api.bind_policy(
            bound["id"], {"expected_policy_version": bound["version"]},
            make_producer_headers(ctx["producer"]["id"]),
        )
        refreshed = get_success_data(
            api_client.get_policy(bound["id"], make_producer_headers(ctx["producer"]["id"]))
        )
        assert refreshed["status"] == "BOUND", refreshed


# ===========================================================================
# Rule: priority_pair_validation_conflict / cancel_temporal_beats_state
# ===========================================================================
class TestCancelStateBeatsTemporal:
    def _quoted_policy(self):
        set_clock("2026-06-01T00:00:00Z")
        ctx = setup_compliant_writer()
        policy = create_quoted_policy(
            ctx,
            annual_premium_cents=1_200_000,
            effective_date="2026-01-01T00:00:00Z",
            expiration_date="2027-01-01T00:00:00Z",
        )
        return ctx, policy

    def test_cancel_quoted_policy_returns_invalid_state_not_out_of_term(self, api):
        """PRD §2.10: "then — for state-transition endpoints — whether the target is in a
        state from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409) ... Only
        after all of these pass are the domain-specific business rules (uniqueness, licensing,
        appointment, split allocation, temporal windows, fiscal floors, and the rest
        described throughout §3) evaluated."

        Design: Difficulty/priority_pair_validation_conflict/cancel_temporal_beats_state
        """
        ctx, policy = self._quoted_policy()
        resp = api.cancel_policy(
            policy["id"],
            {
                "expected_policy_version": policy["version"],
                "cancellation_date": "2030-01-01T00:00:00Z",  # also out of term.
                "cancellation_reason": "INSURED_REQUEST",
            },
            MANAGER(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancel_quoted_leaves_policy_quoted(self, api):
        """PRD §3.6: "An `ACTIVE` (or `REINSTATED`) policy may be **cancelled** by an
        `AccountManager`, transitioning it to `CANCELLED`." A QUOTED policy is not cancellable,
        so it stays QUOTED.

        Design: Difficulty/priority_pair_validation_conflict/cancel_temporal_beats_state
        """
        ctx, policy = self._quoted_policy()
        api.cancel_policy(
            policy["id"],
            {
                "expected_policy_version": policy["version"],
                "cancellation_date": "2030-01-01T00:00:00Z",
                "cancellation_reason": "INSURED_REQUEST",
            },
            MANAGER(),
        )
        refreshed = get_success_data(
            api_client.get_policy(policy["id"], make_producer_headers(ctx["producer"]["id"]))
        )
        assert refreshed["status"] == "QUOTED", refreshed


# ===========================================================================
# Rule: cross_entity_state_dependency / bind_blocked_by_suspended_carrier
# ===========================================================================
class TestBindBlockedBySuspendedCarrier:
    def _quoted_with_suspended_carrier(self):
        set_clock("2026-06-01T00:00:00Z")
        ctx = setup_compliant_writer()
        policy = create_quoted_policy(
            ctx,
            annual_premium_cents=1_200_000,
            effective_date="2026-01-01T00:00:00Z",
            expiration_date="2027-01-01T00:00:00Z",
        )
        carrier = ctx["carrier"]
        get_success_data(
            api_client.suspend_carrier(
                carrier["id"], {"expected_carrier_version": carrier["version"]}, ADMIN()
            )
        )
        return ctx, policy

    def test_bind_with_suspended_carrier_returns_carrier_not_active(self, api):
        """PRD §3.4: "The carrier underwriting the policy's product must be `ACTIVE`; if it is
        not, the bind is rejected with `ERR_CARRIER_NOT_ACTIVE` (HTTP 422) — and recall that a
        `SUSPENDED` carrier blocks new binds for exactly this reason."

        Design: Difficulty/cross_entity_state_dependency/bind_blocked_by_suspended_carrier
        """
        ctx, policy = self._quoted_with_suspended_carrier()
        resp = api.bind_policy(
            policy["id"], {"expected_policy_version": policy["version"]},
            make_producer_headers(ctx["producer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_ACTIVE.value)

    def test_bind_blocked_leaves_policy_quoted(self, api):
        """PRD §3.4: "A `QUOTED` policy created manually must be **bound** before it can come
        on risk ... Binding transitions the policy `QUOTED → BOUND`". A blocked bind leaves
        the policy in QUOTED.

        Design: Difficulty/cross_entity_state_dependency/bind_blocked_by_suspended_carrier
        """
        ctx, policy = self._quoted_with_suspended_carrier()
        api.bind_policy(
            policy["id"], {"expected_policy_version": policy["version"]},
            make_producer_headers(ctx["producer"]["id"]),
        )
        refreshed = get_success_data(
            api_client.get_policy(policy["id"], make_producer_headers(ctx["producer"]["id"]))
        )
        assert refreshed["status"] == "QUOTED", refreshed


# ===========================================================================
# Rule: cross_entity_state_dependency / appointment_activate_blocked_by_expired_license
# ===========================================================================
class TestAppointmentActivateBlockedByExpiredLicense:
    def _approved_appt_with_expired_license(self):
        """ACTIVE carrier; producer with a CA AUTO license expiring 2026-06-15; an APPROVED
        appointment; clock advanced to 2026-07-01 so the license is EXPIRED."""
        set_clock("2026-06-01T00:00:00Z")
        # Build directly to control license expiration vs appointment lifecycle.
        carrier_obj = get_success_data(
            api_client.create_carrier(factories.create_carrier_payload(), ADMIN())
        )
        carrier_obj = get_success_data(
            api_client.activate_carrier(
                carrier_obj["id"], {"expected_carrier_version": carrier_obj["version"]}, ADMIN()
            )
        )
        producer = create_producer()
        create_license(
            producer["id"], state_code="CA", line_of_business="AUTO",
            effective_date="2025-01-01T00:00:00Z", expiration_date="2026-06-15T00:00:00Z",
        )
        appt = get_success_data(
            api_client.create_appointment(
                factories.create_appointment_payload(carrier_obj["id"], producer["id"], state_code="CA"),
                ADMIN(),
            )
        )
        approved = get_success_data(
            api_client.approve_appointment(
                appt["id"], {"expected_appointment_version": appt["version"]}, ADMIN()
            )
        )
        set_clock("2026-07-01T00:00:00Z")  # license now EXPIRED.
        return approved

    def test_activate_appointment_with_expired_license_returns_license_not_active(self, api):
        """PRD §3.2: "Activating an `APPROVED` appointment moves it `APPROVED → ACTIVE`, but
        only if the appointed producer holds a license in the appointment's `state_code` whose
        computed status is `ACTIVE` at the current moment — a cross-entity dependency on the
        producer's licenses; absent such a license the activation is rejected with
        `ERR_LICENSE_NOT_ACTIVE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/appointment_activate_blocked_by_expired_license
        """
        approved = self._approved_appt_with_expired_license()
        resp = api.activate_appointment(
            approved["id"], {"expected_appointment_version": approved["version"]}, ADMIN()
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value)

    def test_blocked_activate_leaves_appointment_approved(self, api):
        """PRD §3.2: "Activating an `APPROVED` appointment moves it `APPROVED → ACTIVE`".
        A blocked activation leaves the appointment in APPROVED.

        Design: Difficulty/cross_entity_state_dependency/appointment_activate_blocked_by_expired_license
        """
        approved = self._approved_appt_with_expired_license()
        api.activate_appointment(
            approved["id"], {"expected_appointment_version": approved["version"]}, ADMIN()
        )
        refreshed = get_success_data(api_client.get_appointment(approved["id"], ADMIN()))
        assert refreshed["status"] == "APPROVED", refreshed


# ===========================================================================
# Rule: resource_temporal_overlap / license_halfopen_interval_overlap_rejected
# ===========================================================================
class TestLicenseIntervalOverlap:
    def test_overlapping_license_interval_rejected(self, api):
        """PRD §3.2: "a producer may not hold two licenses for the same state and line of
        business whose validity intervals overlap: when a new license is recorded, its
        half-open interval from `effective_date` (inclusive) to `expiration_date` (exclusive)
        must not intersect that of any existing license for the same producer, state, and line
        of business. ... but any true intersection is rejected with `ERR_LICENSE_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/license_halfopen_interval_overlap_rejected
        """
        producer = create_producer()
        create_license(
            producer["id"], state_code="CA", line_of_business="AUTO",
            effective_date="2025-01-01T00:00:00Z", expiration_date="2026-01-01T00:00:00Z",
        )
        resp = api.create_license(
            factories.create_license_payload(
                producer["id"], state_code="CA", line_of_business="AUTO",
                effective_date="2025-12-15T00:00:00Z", expiration_date="2026-12-15T00:00:00Z",
            ),
            ADMIN(),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_OVERLAP.value)

    def test_boundary_touch_license_is_allowed(self, api):
        """PRD §3.2: "Touching at the boundary is explicitly permitted — if an existing
        license's `expiration_date` equals the new license's `effective_date`, the intervals
        merely abut and do not overlap".

        Design: Difficulty/resource_temporal_overlap/license_halfopen_interval_overlap_rejected
        """
        producer = create_producer()
        create_license(
            producer["id"], state_code="CA", line_of_business="AUTO",
            effective_date="2025-01-01T00:00:00Z", expiration_date="2026-01-01T00:00:00Z",
        )
        resp = api.create_license(
            factories.create_license_payload(
                producer["id"], state_code="CA", line_of_business="AUTO",
                effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
            ),
            ADMIN(),
        )
        validate_success(resp, 201)


# ===========================================================================
# Rule: resource_temporal_overlap / renewal_successor_term_must_be_adjacent
# ===========================================================================
class TestRenewalSuccessorAdjacency:
    def _offered_task(self):
        set_clock("2026-01-01T00:00:00Z")
        s = setup_renewal_task_offered(
            active_setup=setup_active_policy_no_split(
                policy_overrides={
                    "annual_premium_cents": 1_200_000,
                    "effective_date": "2026-01-01T00:00:00Z",
                    "expiration_date": "2027-01-01T00:00:00Z",
                }
            )
        )
        return s

    def test_non_adjacent_successor_term_rejected(self, api):
        """PRD §3.8: "The successor term must abut the expiring term exactly: the successor's
        `effective_date` must equal the expiring policy's `expiration_date` to the instant —
        adjacency, not mere non-overlap. A successor that would start before the prior term
        ends (an overlap) or after it ends (a gap) is rejected with
        `ERR_RENEWAL_TERM_NOT_ADJACENT` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/renewal_successor_term_must_be_adjacent
        """
        s = self._offered_task()
        task = s["task"]
        resp = api.complete_renewal_task(
            task["id"],
            {
                "expected_renewaltask_version": task["version"],
                "annual_premium_cents": 1_250_000,
                "effective_date": "2027-01-02T00:00:00Z",  # gap: not equal to 2027-01-01.
                "expiration_date": "2028-01-02T00:00:00Z",
            },
            MANAGER(),
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_TERM_NOT_ADJACENT.value)

    def test_rejected_completion_leaves_task_offered(self, api):
        """PRD §3.8: "**Completion** is available only from the `OFFERED` stage". A rejected
        completion leaves the task in OFFERED.

        Design: Difficulty/resource_temporal_overlap/renewal_successor_term_must_be_adjacent
        """
        s = self._offered_task()
        task = s["task"]
        api.complete_renewal_task(
            task["id"],
            {
                "expected_renewaltask_version": task["version"],
                "annual_premium_cents": 1_250_000,
                "effective_date": "2027-01-02T00:00:00Z",
                "expiration_date": "2028-01-02T00:00:00Z",
            },
            MANAGER(),
        )
        refreshed = get_success_data(api_client.get_renewal_task(task["id"], MANAGER()))
        assert refreshed["stage"] == "OFFERED", refreshed
