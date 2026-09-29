"""Incident triage: the measurement gates and the capped, clamped risk sum."""

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import ADJUDICATOR, COMPLIANCE_OFFICER, PLATFORM_ADMIN


def _stay_in_progress(api, guest_name, guest_email):
    """An IN_STAY three-night booking, which is what an incident is filed against."""
    cast = fixtures.setup_waiver_listing(
        api, guest_name=guest_name, guest_email=guest_email
    )
    reservation = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )
    fixtures.confirm_stay(api, cast, reservation["id"])
    fixtures.check_in_stay(api, cast, reservation["id"], clock=constants.CHECK_IN_CLOCK_UTC)
    fixtures.set_clock(api, constants.IN_STAY_CLOCK_UTC)
    return cast, reservation


def test_a_quiet_noise_report_cannot_be_acknowledged_and_moves_nothing(api):
    """65 decibels against a 70-decibel threshold fails the measurement gate.

    The gate stands in front of the whole substantiation cascade, so the refusal has
    to leave the incident open, the guest's substantiated count at zero and the
    guest's score at its baseline rather than nine points higher. A sibling report at
    exactly the threshold is acknowledged, since the comparison is inclusive.

    PRD: "A `NOISE_VIOLATION` may be acknowledged only when `decibel_reading` is present and is greater than or equal to the `noise_threshold_db` of the jurisdiction bound to the reservation's listing; a null reading or one below the threshold is refused with `ERR_NOISE_BELOW_THRESHOLD`."
    PRD: "Acknowledgement moves `incident_state` from `OPEN` to `ACKNOWLEDGED` and sets `substantiated` to true, and from there a four-link cascade unrolls."
    PRD: "The changed count re-runs the risk score, adding 9 points for the new substantiation, subject to the joint 40-point cap it shares with escalations."

    Design: Corner/validations/incident_acknowledge_below_noise_threshold_rejected
    """
    cast, reservation = _stay_in_progress(api, "Quiet Guest", "quiet@guest.test")
    assert cast.jurisdiction_rule["noise_threshold_db"] == 70, (
        "the scenario is calibrated against a 70-decibel threshold"
    )
    guest_before = fixtures.read_guest(api, cast)
    assertions.assert_guest_risk(guest_before, 35, "ELEVATED")

    quiet = validate_success(
        api.create_incident(
            cast.host_headers,
            **factories.noise_incident_payload(reservation["id"], decibel_reading=65.0)
        ),
        expected_status=201,
    )
    assertions.assert_fields(quiet, "incident", incident_state="OPEN", substantiated=False)

    validate_error(
        api.acknowledge_incident(quiet["id"], ADJUDICATOR),
        ApiErrorId.ERR_NOISE_BELOW_THRESHOLD,
        expected_status=422,
    )

    unchanged = validate_success(api.get_incident(quiet["id"], cast.host_headers))
    assertions.assert_fields(
        unchanged, "incident", incident_state="OPEN", substantiated=False
    )
    guest_after = fixtures.read_guest(api, cast)
    assertions.assert_fields(guest_after, "guest", substantiated_incident_count=0)
    assertions.assert_guest_risk(guest_after, 35, "ELEVATED")
    assertions.assert_page(
        api.list_blocklist_entries(COMPLIANCE_OFFICER, guest_id=cast.guest_id),
        total_count=0,
    )

    at_threshold = validate_success(
        api.create_incident(
            cast.host_headers,
            **factories.noise_incident_payload(
                reservation["id"], decibel_reading=70.0, detected_at="2026-08-11T01:30:00Z"
            )
        ),
        expected_status=201,
    )
    acknowledged = validate_success(
        api.acknowledge_incident(at_threshold["id"], ADJUDICATOR)
    )
    assertions.assert_fields(
        acknowledged, "incident", incident_state="ACKNOWLEDGED", substantiated=True
    )


def test_the_incident_subtotal_is_capped_before_the_other_terms_join_the_sum(api):
    """Three substantiations plus one escalation are worth 40 points, not 52.

    Three acknowledgements alone come to 27 points, well inside the cap. Escalating
    one of them adds 25 more, which would make 52 — but the subtotal is capped at 40
    before it enters the sum, so the guest lands on exactly 75 rather than the 87 an
    uncapped subtotal would have produced.

    PRD: "Add an incident subtotal formed as 9 points for each substantiated incident plus 25 points for each escalated incident, then capped at 40 points."
    PRD: "The cap applies to this subtotal only — it never touches the chargeback or claim terms."
    PRD: "An escalated incident is necessarily also a substantiated one, so it contributes both its 9-point substantiation weight and its 25-point escalation weight — 34 points together — before the 40-point cap is applied."

    Design: Difficulty/combinatorial_formula/risk_score_incident_cap_applied_before_the_single_clamp
    """
    cast, reservation = _stay_in_progress(api, "Rex Calder", "rex@guest.test")
    threat = validate_success(
        api.create_incident(
            cast.host_headers,
            **factories.incident_payload(
                reservation["id"],
                incident_type="SAFETY_THREAT",
                severity="HIGH",
                detected_at="2026-08-11T01:00:00Z",
                description="Guest threatened a neighbour on the shared stairwell.",
            )
        ),
        expected_status=201,
    )
    for index, description in enumerate(
        ("Interior door frame split.", "Two window screens torn."), start=1
    ):
        damage = validate_success(
            api.create_incident(
                cast.host_headers,
                **factories.incident_payload(
                    reservation["id"],
                    detected_at="2026-08-11T01:{0}0:00Z".format(index),
                    description=description,
                )
            ),
            expected_status=201,
        )
        validate_success(api.acknowledge_incident(damage["id"], ADJUDICATOR))
    validate_success(api.acknowledge_incident(threat["id"], ADJUDICATOR))

    three_substantiations = fixtures.read_guest(api, cast)
    assertions.assert_fields(
        three_substantiations,
        "guest",
        substantiated_incident_count=3,
        escalated_incident_count=0,
    )
    assertions.assert_guest_risk(three_substantiations, 62, "HIGH")

    escalated = validate_success(
        api.escalate_incident(
            threat["id"], ADJUDICATOR, law_enforcement_ref="SFPD-2026-44182"
        )
    )
    assertions.assert_fields(
        escalated,
        "incident",
        incident_state="ESCALATED_LAW_ENFORCEMENT",
        escalated=True,
        law_enforcement_ref="SFPD-2026-44182",
    )

    capped = fixtures.read_guest(api, cast)
    assertions.assert_fields(
        capped, "guest", substantiated_incident_count=3, escalated_incident_count=1
    )
    assertions.assert_guest_risk(capped, 75, "CRITICAL")
    assert capped["risk_score"] != 87, (
        "87 is the score an uncapped incident subtotal of 52 would have produced"
    )


def test_the_clamp_lands_the_finished_sum_on_one_hundred_exactly_once(api):
    """A raw sum of 130 becomes 100, and the cap is still respected underneath it.

    On top of the capped 40-point incident subtotal the processor reports an adverse
    signal and five chargebacks, worth 30 and 25 points. The raw sum is 130; the
    clamp is applied once to that finished total, so the guest reads exactly 100 and
    the critical band fires the automatic platform ban.

    PRD: "Clamp the finished sum into the range 0 through 100 inclusive. The clamp is applied exactly once, to the total, never per term."
    PRD: "Add an incident subtotal formed as 9 points for each substantiated incident plus 25 points for each escalated incident, then capped at 40 points."
    PRD: "Recording a signal re-runs the risk score, which may re-band `risk_tier` and, if the re-band reaches the critical band, fire the automatic platform ban described in §3.9."

    Design: Difficulty/combinatorial_formula/risk_score_incident_cap_applied_before_the_single_clamp
    """
    cast, reservation = _stay_in_progress(api, "Rex Calder", "rex@guest.test")
    threat = fixtures.file_incident(
        api,
        cast,
        reservation["id"],
        incident_type="SAFETY_THREAT",
        severity="HIGH",
        detected_at="2026-08-11T01:00:00Z",
        description="Guest threatened a neighbour on the shared stairwell.",
    )
    fixtures.file_incident(
        api,
        cast,
        reservation["id"],
        detected_at="2026-08-11T01:10:00Z",
        description="Interior door frame split.",
    )
    fixtures.file_incident(
        api,
        cast,
        reservation["id"],
        severity="LOW",
        detected_at="2026-08-11T01:20:00Z",
        description="Two window screens torn.",
    )
    validate_success(
        api.escalate_incident(
            threat["id"], ADJUDICATOR, law_enforcement_ref="SFPD-2026-44182"
        )
    )
    assertions.assert_guest_risk(fixtures.read_guest(api, cast), 75, "CRITICAL")

    saturated = validate_success(
        api.record_payment_signal(
            cast.guest_id,
            PLATFORM_ADMIN,
            payment_risk_signal="ADVERSE",
            chargeback_count=5,
        )
    )
    assertions.assert_fields(
        saturated, "guest", payment_risk_signal="ADVERSE", chargeback_count=5
    )
    assertions.assert_guest_risk(saturated, 100, "CRITICAL")

    profile = validate_success(api.get_guest_risk_profile(cast.guest_id, ADJUDICATOR))
    assertions.assert_fields(
        profile,
        "risk_profile",
        substantiated_incident_count=3,
        escalated_incident_count=1,
        chargeback_count=5,
        risk_score=100,
        risk_tier="CRITICAL",
    )

    bans, _ = assertions.assert_page(
        api.list_blocklist_entries(COMPLIANCE_OFFICER, guest_id=cast.guest_id),
        total_count=1,
    )
    assertions.assert_fields(
        bans[0],
        "blocklist_entry",
        scope="PLATFORM",
        reason_code="RISK_TIER_CRITICAL",
        auto_generated=True,
        created_by_role="system",
        entry_state="ACTIVE",
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        stay_state="IN_STAY",
    )
