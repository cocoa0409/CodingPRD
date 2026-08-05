"""The lazy sweeps and the escalation tier ladder."""

from test_helpers import (
    ApiErrorId,
    assert_offering_counters,
    assert_same_instant,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    PROGRAM_ADMIN,
    SUPERVISOR,
    SUPERVISOR_ID,
    SUPERVISOR_TWO,
    SUPERVISOR_TWO_ID,
)


def test_hold_expiry_sweep_returns_units_through_the_expired_bucket(api):
    """PRD §3.4: "The third route is different: an `ACCEPTED` referral whose
    `hold_expires_at` the clock has passed is lapsed by the hold-expiry sweep
    with `lapse_reason` of `HOLD_EXPIRED`, and its units are returned into
    `expired_units` rather than `released_units` — `allocated_units` falls,
    `available_units` rises, `expired_units` rises, and the offering's `version`
    increments."
    PRD §3.10: "A run of `OFFERING_HOLD_EXPIRY` visits referrals in `ACCEPTED`
    whose `hold_expires_at` the clock is strictly past and lapses each with
    `lapse_reason` of `HOLD_EXPIRED`, returning their units into
    `expired_units`."

    Design: Corner/state_machines/hold_expiry_sweep_moves_units_to_expired_bucket
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-017",
        mrn="MRN-C17", full_name="Expiry Case",
    )
    org, offering, partner_headers = fx.org_with_offering(capacity_total=4)
    referral = fx.accepted_referral(
        chw_headers, partner_headers, patient["id"], offering["id"], worker["id"],
        units_requested=2,
    )
    assert_same_instant(
        referral["hold_expires_at"], "2026-06-08T00:00:00Z", "hold_expires_at"
    )

    fx.set_clock("2026-06-08T00:00:01Z")
    validate_success(api.run_sweep("OFFERING_HOLD_EXPIRY", PROGRAM_ADMIN))

    lapsed = fx.read_referral(referral["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["lapse_reason"] == "HOLD_EXPIRED", (
        f"the expiry route stamps HOLD_EXPIRED, got {lapsed['lapse_reason']}"
    )

    after = fx.read_offering(offering["id"])
    assert_offering_counters(
        after, available=4, allocated=0, expired=2, released=0, lifetime=2
    )
    assert fx.read_patient(patient["id"])["unfulfilled_referral_count"] == 1


def test_referral_lapse_sweep_at_exactly_the_deadline_changes_nothing(api):
    """PRD §3.4: "A `SENT` referral whose `ack_deadline_at` the logical clock
    has passed — strictly after, never at — is lapsed by the referral-lapse
    sweep with `lapse_reason` of `ACK_SLA_EXPIRED`."
    PRD §3.10: "The response echoes the `sweep_type` and reports four counters:
    `referrals_lapsed`, the number of referrals moved to `LAPSED` by this run;
    `holds_expired`, the number of accepted holds this run expired;
    `escalations_promoted`, the number of tier promotions this run applied; and
    `units_returned`, the total number of offering units this run returned to
    `available_units`."

    Design: Corner/state_machines/referral_lapse_sweep_at_exact_deadline_changes_nothing
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-018",
        mrn="MRN-C18", full_name="Deadline Case",
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=4)
    referral = fx.send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"]
    )
    assert_same_instant(
        referral["ack_deadline_at"], "2026-06-04T00:00:00Z", "ROUTINE ack_deadline_at"
    )

    fx.set_clock("2026-06-04T00:00:00Z")
    on_deadline = validate_success(api.run_sweep("REFERRAL_LAPSE", PROGRAM_ADMIN))
    assert on_deadline["sweep_type"] == "REFERRAL_LAPSE"
    assert on_deadline["referrals_lapsed"] == 0, (
        "a sweep at exactly the deadline lapses nothing, because the comparison "
        f"is strictly after; got {on_deadline['referrals_lapsed']}"
    )
    assert fx.read_referral(referral["id"])["status"] == "SENT"

    fx.set_clock("2026-06-04T00:00:01Z")
    past_deadline = validate_success(api.run_sweep("REFERRAL_LAPSE", PROGRAM_ADMIN))
    assert past_deadline["referrals_lapsed"] == 1, (
        f"one second later the referral lapses, got {past_deadline['referrals_lapsed']}"
    )

    lapsed = fx.read_referral(referral["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["lapse_reason"] == "ACK_SLA_EXPIRED"
    assert_offering_counters(
        fx.read_offering(offering["id"]), available=4, allocated=0, released=1
    )


def test_tier_three_is_the_promotion_ceiling(api):
    """PRD §3.10: "When the escalation-promotion sweep runs and finds an
    escalation in `OPEN_TIER_1` whose `ack_deadline_at` the logical clock is
    **strictly** past, that escalation moves to `OPEN_TIER_2`, its
    `current_tier` becomes 2, its `tier_entered_at` is re-stamped with the
    current logical clock, its `promotion_count` increments by 1, and its
    `ack_deadline_at` is recomputed as the new `tier_entered_at` plus 24 hours."
    PRD §3.10: "The same sweep moves an over-deadline `OPEN_TIER_2` escalation
    to `OPEN_TIER_3`, setting `current_tier` to 3, re-stamping `tier_entered_at`,
    incrementing `promotion_count` and recomputing `ack_deadline_at` with 8
    hours."
    PRD §3.10: "Tier 3 is the ceiling: an `OPEN_TIER_3` escalation that is past
    its deadline is left entirely untouched by any later sweep — no state
    change, no field change and no `version` bump."
    PRD §3.10: "On a manual escalation the `source_flag` is always `MANUAL` and
    `opened_by_user_id` is the caller's own `X-User-ID`; on a cascade-opened
    escalation the `note` is null and `opened_by_user_id` is the literal string
    `SYSTEM` — with the single exception of the goal-not-met cascade, which
    records the acting caller's `X-User-ID` because a human closed the goal."

    Design: Corner/state_machines/escalation_tier3_is_the_promotion_ceiling
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-012",
        mrn="MRN-C12", full_name="Tier Case",
    )
    escalation = fx.open_manual_escalation(
        chw_headers, patient["id"], "Imminent eviction reported"
    )
    assert_same_instant(
        escalation["ack_deadline_at"], "2026-06-03T00:00:00Z", "tier-1 ack_deadline_at"
    )

    fx.set_clock("2026-06-03T00:00:01Z")
    first = validate_success(api.run_sweep("ESCALATION_PROMOTION", PROGRAM_ADMIN))
    assert first["escalations_promoted"] == 1

    fx.set_clock("2026-06-04T00:00:02Z")
    second = validate_success(api.run_sweep("ESCALATION_PROMOTION", PROGRAM_ADMIN))
    assert second["escalations_promoted"] == 1

    fx.set_clock("2026-06-10T00:00:00Z")
    third = validate_success(api.run_sweep("ESCALATION_PROMOTION", PROGRAM_ADMIN))
    assert third["escalations_promoted"] == 0, (
        "tier 3 is the ceiling, so a later sweep promotes nothing; got "
        f"{third['escalations_promoted']}"
    )
    assert third["referrals_lapsed"] == 0
    assert third["holds_expired"] == 0
    assert third["units_returned"] == 0

    final = fx.read_escalation(escalation["id"])
    assert final["status"] == "OPEN_TIER_3"
    assert final["current_tier"] == 3
    assert final["promotion_count"] == 2, (
        f"only two promotions ever applied, got {final['promotion_count']}"
    )
    assert_same_instant(
        final["tier_entered_at"], "2026-06-04T00:00:02Z", "tier_entered_at"
    )
    assert_same_instant(
        final["ack_deadline_at"], "2026-06-04T08:00:02Z",
        "tier-3 ack_deadline_at (8 hours after entry)",
    )
    assert final["opened_by_user_id"] == worker["id"], (
        "a manual escalation records the opening caller's own X-User-ID"
    )
    assert final["source_flag"] == "MANUAL"


def test_the_operator_who_opened_an_escalation_cannot_acknowledge_it(api):
    """PRD §2.1: "One further segregation rule is enforced at request time
    rather than by role membership: the operator acknowledging an escalation
    must not be the operator who opened it. If the acknowledging `X-User-ID`
    equals the escalation's `opened_by_user_id`, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.10: "Acknowledgement sets `status` to `ACKNOWLEDGED`, records the
    acting identifier in `acknowledged_by_user_id`, and freezes `current_tier`
    at whichever tier the escalation had reached — 1, 2 or 3 respectively."

    Design: Corner/validations/escalation_opener_cannot_acknowledge_own_escalation
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-046",
        mrn="MRN-C46", full_name="SoD Case",
    )
    escalation = fx.open_manual_escalation(
        SUPERVISOR, patient["id"], "Utility shutoff notice received"
    )
    assert escalation["opened_by_user_id"] == SUPERVISOR_ID

    refused = api.acknowledge_escalation(escalation["id"], SUPERVISOR)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    accepted = validate_success(
        api.acknowledge_escalation(escalation["id"], SUPERVISOR_TWO)
    )
    assert accepted["status"] == "ACKNOWLEDGED"
    assert accepted["acknowledged_by_user_id"] == SUPERVISOR_TWO_ID
    assert accepted["current_tier"] == 1, (
        "acknowledgement freezes current_tier at the tier the escalation had reached"
    )
