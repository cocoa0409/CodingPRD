"""State-machine lifecycles: enrollment recertification cycle, subscription's
parallel service/billing axes, install reschedule self-loop, and terminal /
invalid-state transitions.

Covers Difficulty queue rule non_linear_state_machine and several Corner
state_machines instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_officer_headers,
    fixtures as fx,
)

ELIG = TEST_USERS["eligibility_worker_headers"]
CARE = TEST_USERS["customer_care_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
NOC = TEST_USERS["noc_operator_headers"]
ANY_READER = TEST_USERS["program_admin_headers"]


# =====================================================================
# Rule 3 — non_linear_state_machine / enrollment_recertification_cycle
# =====================================================================
class TestEnrollmentRecertificationCycle:
    def _recert_due_enrollment(self, api):
        fx.set_clock(api, "2026-06-01T00:00:00Z")
        grant = fx.create_grant(api)
        area = fx.create_area(api, grant["id"], homes_passed=100)
        subsidy = fx.create_subsidy_program(api, eligibility_fpl_pct=200)
        subscriber = fx.create_subscriber(api, area["id"])
        enrollment = fx.create_active_enrollment(api, subscriber["id"], subsidy["id"],
                                                 household_size=2, annual_income_cents=3_000_000)
        fx.set_clock(api, "2027-07-01T00:00:00Z")
        return enrollment

    def test_recertify_returns_recert_due_to_active(self, api):
        """PRD §3.4: "If the recomputed ratio is still at or below the ceiling, the
        enrollment returns `RECERT_DUE` to `ACTIVE` and `certification_expires_at` is
        reset to now plus 365 days, closing the loop."

        Design: Difficulty/non_linear_state_machine/enrollment_recertification_cycle
        """
        enrollment = self._recert_due_enrollment(api)
        recertified = validate_success(
            api.recertify_enrollment(enrollment["id"], ELIG, {"annual_income_cents": 3_000_000})
        )
        assert recertified["status"] == "ACTIVE", \
            f"still-eligible recertify returns to ACTIVE, got {recertified['status']}"
        assert recertified["fpl_pct"] == 147.49, \
            f"3000000 / 2034000 * 100 = 147.49, got {recertified['fpl_pct']}"

    def test_recertify_resets_certification_expiry(self, api):
        """PRD §3.4: "the enrollment returns `RECERT_DUE` to `ACTIVE` and
        `certification_expires_at` is reset to now plus 365 days, closing the loop."

        Design: Difficulty/non_linear_state_machine/enrollment_recertification_cycle
        """
        enrollment = self._recert_due_enrollment(api)
        recertified = validate_success(
            api.recertify_enrollment(enrollment["id"], ELIG, {"annual_income_cents": 3_000_000})
        )
        # now (2027-07-01T00:00:00Z) + 365 days = 2028-06-30 (2028 is a leap year).
        assert recertified["certification_expires_at"].startswith("2028-06-30"), \
            f"expiry should advance to 2028-06-30, got {recertified['certification_expires_at']}"


# =====================================================================
# Rule 3 — non_linear_state_machine / subscription_parallel_service_and_billing_axes
# =====================================================================
class TestSubscriptionParallelAxes:
    def test_suspend_moves_service_axis_only(self, api):
        """PRD §3.2: "A subscription evolves along two independent axes."
        PRD §3.2: "A `CustomerCare` operator may suspend an `ACTIVE` subscription to
        `SUSPENDED`, and the area-suspension cascade of §3.1 drives both `ACTIVE` and
        `PENDING_INSTALL` subscriptions to `SUSPENDED` without operator action."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_service_and_billing_axes
        """
        ctx = fx.setup_active_subscription(api)
        suspended = validate_success(api.suspend_subscription(ctx["subscription"]["id"], CARE))
        assert suspended["service_status"] == "SUSPENDED"

    def test_billing_axis_stays_current_when_service_suspended(self, api):
        """PRD §3.2: "The **billing axis**, `billing_status`, evolves independently
        and begins `CURRENT`."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_service_and_billing_axes
        """
        ctx = fx.setup_active_subscription(api)
        suspended = validate_success(api.suspend_subscription(ctx["subscription"]["id"], CARE))
        assert suspended["billing_status"] == "CURRENT", \
            f"billing axis is independent and stays CURRENT, got {suspended['billing_status']}"


# =====================================================================
# Corner — state_machines / install_reschedule_self_loop_increments_count
# =====================================================================
def test_reschedule_keeps_scheduled_and_increments_count(api):
    """PRD §3.3: "this is a self-loop that keeps the order `SCHEDULED`, re-derives
    `scheduled_end_at`, increments `reschedule_count` by one, and re-applies the same
    half-open overlap check against the technician's other `SCHEDULED` orders."

    Design: Corner/state_machines/install_reschedule_self_loop_increments_count
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    plan = fx.create_plan(api)
    subscriber = fx.create_subscriber(api, area["id"])
    subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
    tech = fx.create_technician(api)
    io = fx.schedule_install(api, subscription["id"], tech["id"], "2026-06-02T09:00:00Z")
    rescheduled = validate_success(
        api.reschedule_install_order(io["id"], {"scheduled_start_at": "2026-06-03T09:00:00Z"}, DISPATCH)
    )
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["reschedule_count"] == 1, \
        f"reschedule_count should be 1, got {rescheduled['reschedule_count']}"


# =====================================================================
# Corner — state_machines / verify_ineligible_enrollment_denied
# =====================================================================
def test_verify_ineligible_enrollment_moves_to_denied(api):
    """PRD §3.4: "An ineligible verification — `fpl_pct` strictly above the ceiling —
    moves the enrollment `SUBMITTED` to the terminal `DENIED`."

    Design: Corner/state_machines/verify_ineligible_enrollment_denied
    """
    grant = fx.create_grant(api)
    area = fx.create_area(api, grant["id"], homes_passed=100)
    subsidy = fx.create_subsidy_program(api, eligibility_fpl_pct=200)
    subscriber = fx.create_subscriber(api, area["id"], full_name="Rich Doe", email="rich@x.com",
                                      service_address="9 Main St")
    enrollment = fx.create_enrollment(api, subscriber["id"], subsidy["id"],
                                      household_size=2, annual_income_cents=5_000_000)
    assert enrollment["fpl_pct"] == 245.82, \
        f"5000000 / 2034000 * 100 = 245.82, got {enrollment['fpl_pct']}"
    verified = validate_success(api.verify_enrollment(enrollment["id"], ELIG))
    assert verified["status"] == "DENIED", \
        f"fpl 245.82 > ceiling 200 is ineligible -> DENIED, got {verified['status']}"


# =====================================================================
# Corner — state_machines / cancel_already_cancelled_subscription_invalid_state
# =====================================================================
def test_cancel_already_cancelled_subscription_invalid_state(api):
    """PRD §3.2: "Cancellation moves a subscription in `PENDING_INSTALL`, `ACTIVE`,
    or `SUSPENDED` to the terminal `CANCELLED` state."
    PRD §2.5: "(4) whether the target resource is in a state that permits the
    requested transition, failing with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/cancel_already_cancelled_subscription_invalid_state
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    plan = fx.create_plan(api)
    subscriber = fx.create_subscriber(api, area["id"])
    subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
    validate_success(api.cancel_subscription(subscription["id"], CARE))
    validate_error(api.cancel_subscription(subscription["id"], CARE), ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_subscription(subscription["id"], ANY_READER))
    assert fetched["service_status"] == "CANCELLED"


# =====================================================================
# Corner — state_machines / approve_claim_from_draft_invalid_state
# =====================================================================
def test_approve_draft_claim_invalid_state(api):
    """PRD §3.7: "An officer then decides the `SUBMITTED` claim"
    PRD §2.5: "(4) whether the target resource is in a state that permits the
    requested transition, failing with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/approve_claim_from_draft_invalid_state
    """
    grant = fx.create_grant(api)
    g_v = grant["version"]
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    claim = fx.create_claim(api, grant["id"], [area["id"]], g_v)
    validate_error(api.approve_grant_claim(claim["id"], make_officer_headers("officer-1")),
                   ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_grant_claim(claim["id"], ANY_READER))
    assert fetched["status"] == "DRAFT"


# =====================================================================
# Corner — state_machines / outage_resolve_ended_before_started_invalid
# =====================================================================
def test_resolve_outage_ended_before_started_rejected(api):
    """PRD §3.6: "Resolving an outage requires an `ended_at` that is supplied and
    strictly later than `started_at`, failing otherwise with `ERR_OUTAGE_NOT_ENDED`;
    on success the outage moves `OPEN` to `RESOLVED`."

    Design: Corner/state_machines/outage_resolve_ended_before_started_invalid
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    outage = fx.report_outage(api, area["id"], "2026-06-01T06:00:00Z", severity="FULL")
    validate_error(api.resolve_outage(outage["id"], {"ended_at": "2026-06-01T05:00:00Z"}, NOC),
                   ApiErrorId.ERR_OUTAGE_NOT_ENDED)
    fetched = validate_success(api.get_outage(outage["id"], ANY_READER))
    assert fetched["status"] == "OPEN"
