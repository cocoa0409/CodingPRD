"""Three refusals measured against a fixed number: a deadline, a map, and a count.

Each refusal is bracketed by the request that just clears the bar, so the boundary
itself is pinned rather than merely the rejection.
"""

from test_helpers import (
    HR_ADMIN,
    PRIVACY_OFFICER,
    VENDOR_MANAGER,
    ApiErrorId,
    accommodation_payload,
    accommodations_for_subject,
    assert_cents,
    assert_instant_equals,
    assert_is_null,
    baseline_with_active_asset,
    create_asset,
    create_data_subject,
    create_incident,
    create_jurisdiction,
    create_program,
    create_vendor,
    create_vendor_contract,
    read_contract,
    read_incident,
    read_subject,
    set_clock,
    validate_error,
    validate_success,
)

LATE_CERTIFICATE_REF = "cert-late-001"


def test_a_certificate_one_day_late_is_refused_and_one_at_the_deadline_stands(api):
    """The deletion deadline is inclusive; only the day past it closes the door.

    PRD §3.2: "The contract's `terminated_at` is stamped from the current logical clock
    and its `deletion_deadline_at` is set to `terminated_at` plus `deletion_deadline_days`."

    PRD §3.2: "Close-out is also time-bound: it is permitted only while the current
    logical clock is at or before `deletion_deadline_at`, and a clock strictly after that
    instant yields `ERR_DELETION_DEADLINE_MISSED`."

    PRD §3.2: "Successful close-out stores the certificate reference, recomputes
    `open_deletion_obligation_count` and recomputes `posture` — typically the step that
    lifts a program back out of `FROZEN`."

    Termination happens at the default clock, so the thirty contractual days land the
    deadline on 2026-08-31. The refused attempt leaves the engagement stuck in
    `TERMINATED` with no certificate — the permanent audit finding — and the identical
    request at the deadline instant itself is accepted, so the comparison is strict.

    Design: Corner/errors/closing_out_a_contract_after_the_deletion_deadline_rejected
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"], attestation_status="RECEIVED")
    contract = create_vendor_contract(
        api, vendor["id"], target_status="TERMINATED", deletion_deadline_days=30
    )
    assert_instant_equals(contract["terminated_at"], "2026-08-01T00:00:00.000Z", "terminated_at")
    assert_instant_equals(
        contract["deletion_deadline_at"], "2026-08-31T00:00:00.000Z", "deletion_deadline_at"
    )

    set_clock(api, "2026-09-01T00:00:00Z")

    late = api.transition_vendor_contract(
        contract["id"],
        {"to_status": "CLOSED_OUT", "deletion_certificate_ref": LATE_CERTIFICATE_REF},
        VENDOR_MANAGER,
    )

    validate_error(late, ApiErrorId.DELETION_DEADLINE_MISSED)
    unchanged = read_contract(api, contract["id"])
    assert unchanged["status"] == "TERMINATED"
    assert_is_null(
        unchanged["deletion_certificate_ref"], "deletion_certificate_ref after a late attempt"
    )

    set_clock(api, "2026-08-31T00:00:00Z")

    closed_out = validate_success(
        api.transition_vendor_contract(
            contract["id"],
            {"to_status": "CLOSED_OUT", "deletion_certificate_ref": LATE_CERTIFICATE_REF},
            VENDOR_MANAGER,
        )
    )
    assert closed_out["status"] == "CLOSED_OUT"
    assert closed_out["deletion_certificate_ref"] == LATE_CERTIFICATE_REF


def test_a_badge_pin_is_wrong_for_a_timekeeping_surface_even_though_it_is_a_real_method(api):
    """The surface map is single-valued, not a menu of acceptable alternatives.

    PRD §3.7: "A `TIMEKEEPING` surface maps to `MANUAL_TIMESHEET`. An `ACCESS_CONTROL`
    surface maps to `BADGE_PIN`. A `CUSTOMER_FACING` surface maps to `STAFFED_LANE`. A
    `SECURITY_CAMERA` surface maps to `MANUAL_LOG`. Any other pairing is rejected with
    `ERR_ACCOMMODATION_METHOD_NOT_PERMITTED`."

    PRD §3.7: "The request lands in `REQUESTED` with `origin` of `MANUAL`,
    `created_from_consent_id` null, `sla_breached` false, and `sla_due_at` set to five
    days after the current logical clock — the deadline for reaching `PROVISIONED`."

    PRD §2.9: "`active_accommodation_count` on a data subject is the count of its
    accommodations whose status is `PROVISIONED` or `ACTIVE`. `enrollment_status` on a
    data subject is derived in a strict priority order: it is `OPTED_OUT` if any of that
    subject's consent records is `DECLINED` or `REVOKED` and none is `GRANTED`; otherwise
    `ENROLLED` if any is `GRANTED`; otherwise `ALTERNATIVE` if any of the subject's
    accommodations is `PROVISIONED` or `ACTIVE`; otherwise `NOT_ENROLLED`."

    `BADGE_PIN` is a perfectly real method — it is the right answer for a door reader —
    yet it is refused here, so the rule is about the pairing rather than the vocabulary.
    The accepted request creates a merely `REQUESTED` row, which is why the individual is
    still counted as enrolled in nothing at all.

    Design: Corner/errors/accommodation_method_outside_the_category_map_rejected
    """
    ctx = baseline_with_active_asset(api, activation_clock=None)
    subject = create_data_subject(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        "EMP-0001",
        accommodation_needed=True,
    )

    wrong_method = api.create_accommodation(
        accommodation_payload(
            subject["id"],
            ctx["asset_id"],
            "2026-08-01T00:00:00Z",
            "2026-09-01T00:00:00Z",
            method="BADGE_PIN",
        ),
        HR_ADMIN,
    )

    validate_error(wrong_method, ApiErrorId.ACCOMMODATION_METHOD_NOT_PERMITTED)
    assert accommodations_for_subject(api, subject["id"]) == []

    permitted = validate_success(
        api.create_accommodation(
            accommodation_payload(
                subject["id"],
                ctx["asset_id"],
                "2026-08-01T00:00:00Z",
                "2026-09-01T00:00:00Z",
                method="MANUAL_TIMESHEET",
            ),
            HR_ADMIN,
        ),
        expected_status=201,
    )
    assert permitted["status"] == "REQUESTED"
    assert permitted["origin"] == "MANUAL"
    assert permitted["sla_breached"] is False
    assert_is_null(permitted["created_from_consent_id"], "created_from_consent_id on a manual row")
    assert_instant_equals(permitted["sla_due_at"], "2026-08-06T00:00:00.000Z", "sla_due_at")

    still_unenrolled = read_subject(api, subject["id"])
    assert still_unenrolled["active_accommodation_count"] == 0
    assert still_unenrolled["enrollment_status"] == "NOT_ENROLLED"


def test_notifying_nine_of_ten_exposed_individuals_is_refused_and_ten_is_accepted(api):
    """The notified count must reach the exposed count, and reaching it in time is timely.

    PRD §3.8: "That count must be present and must be at least `exposed_subject_count`; a
    shortfall is rejected with `ERR_NOTIFIED_COUNT_SHORTFALL`. The move stores the count,
    stamps `notified_at` from the current logical clock, and sets `late_notification` to
    true when `notified_at` is **strictly after** `notification_due_at` — notifying
    exactly at the deadline is timely."

    PRD §3.8: "`gross_notice_cents` is 425 cents (US$4.25) for every exposed individual
    plus 15,000 cents (US$150.00) for every non-default locale the notification must
    cover — that is, `exposed_subject_count` multiplied by 425, plus
    `translation_locale_count` multiplied by 15,000."

    PRD §3.8: "`regulator_surcharge_cents` is zero when the gross is below 50,000 cents
    (US$500.00)"

    PRD §3.8: "The indemnity pool is the sum of `indemnity_cap_cents` across those vendor
    contracts whose status is `EXECUTED` and whose vendor operates at least one of the
    affected collection points; contracts in `DRAFT`, `APPROVED`, `TERMINATED`,
    `CLOSED_OUT` or `VOID` contribute nothing, and affected points with a null
    `vendor_id` bring no pool with them."

    PRD §3.8: "`net_incident_cost_cents` is `gross_notice_cents` plus
    `regulator_surcharge_cents` minus `vendor_indemnity_credit_cents`."

    Ten fingerprint records over two translated locales prices at 34,250 cents, below the
    first surcharge floor, and the point is operated in house so no indemnity pool exists
    — the net is the bare gross. The refused notification leaves the case in `ASSESSED`
    with no timestamp, and the accepted one lands well inside the forty-five-day window.

    Design: Corner/errors/notifying_fewer_subjects_than_were_exposed_rejected
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    point = create_asset(api, program["id"], jurisdiction["id"])
    incident = create_incident(
        api,
        program["id"],
        [point["id"]],
        exposure_vector="VENDOR_BREACH",
        description="ten fingerprint templates exfiltrated",
        exposed_subject_count=10,
        translation_locale_count=2,
    )

    assessed = validate_success(
        api.transition_incident_notification(
            incident["id"], {"to_status": "ASSESSED"}, PRIVACY_OFFICER
        )
    )
    assert assessed["heightened_tier"] == "TIER_2"
    assert_instant_equals(
        assessed["notification_due_at"], "2026-09-15T00:00:00.000Z", "notification_due_at"
    )
    assert_cents(assessed["gross_notice_cents"], 34250, "gross_notice_cents")
    assert_cents(assessed["regulator_surcharge_cents"], 0, "regulator_surcharge_cents")
    assert_cents(assessed["vendor_indemnity_credit_cents"], 0, "vendor_indemnity_credit_cents")
    assert_cents(assessed["net_incident_cost_cents"], 34250, "net_incident_cost_cents")

    set_clock(api, "2026-08-20T00:00:00Z")

    shortfall = api.transition_incident_notification(
        incident["id"], {"to_status": "NOTIFIED", "notified_subject_count": 9}, PRIVACY_OFFICER
    )

    validate_error(shortfall, ApiErrorId.NOTIFIED_COUNT_SHORTFALL)
    unchanged = read_incident(api, incident["id"])
    assert unchanged["notification_status"] == "ASSESSED"
    assert_is_null(unchanged["notified_at"], "notified_at after a refused notification")

    notified = validate_success(
        api.transition_incident_notification(
            incident["id"], {"to_status": "NOTIFIED", "notified_subject_count": 10}, PRIVACY_OFFICER
        )
    )
    assert notified["notification_status"] == "NOTIFIED"
    assert notified["notified_subject_count"] == 10
    assert_instant_equals(notified["notified_at"], "2026-08-20T00:00:00.000Z", "notified_at")
    assert notified["late_notification"] is False
