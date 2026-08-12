"""Rental turnovers, mail holds and the non-monotone false-alarm ladder."""

from test_helpers import (
    AUDITOR,
    DISPATCHER,
    FIELD_TECH,
    ApiErrorId,
    assert_same_instant,
    create_mail_hold_payload,
    lines_of,
    log_packages,
    new_mail_hold,
    new_owner,
    new_property,
    new_rental_turnover,
    new_security_incident,
    new_template,
    reclassify_false_alarm,
    refresh_incident,
    refresh_invoice,
    refresh_mail_hold,
    refresh_property,
    refresh_turnover,
    set_clock,
    setup_active_mail_hold,
    setup_draft_invoice,
    setup_investigating_incident,
    setup_subscribed_property,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


# --------------------------------------------------------------------------
# Rental turnovers
# --------------------------------------------------------------------------

def test_skipping_two_turnover_stages_is_refused(api):
    """PRD 3.9: "A single advance capability takes a `to_status` and drives the stage
    machine; an advance that targets a stage which is not the declared successor of the
    current one is rejected with `ERR_TURNOVER_STAGE_INVALID`."
    PRD 3.9: "`CLEANING` is reachable from `CHECKOUT` with no precondition and stamps
    `clean_started_at`."

    Design: Corner/errors/err_turnover_stage_invalid_when_skipping_cleaning_returns_409
    """
    set_clock("2026-06-10T12:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="SkipStage House", address_line="1 Jump Jct",
                        travel_distance_miles=5.0, rental_program_enrolled=True)
    turnover = new_rental_turnover(prop["id"], checkout_at="2026-06-10T11:00:00Z",
                                   checkin_at="2026-06-12T15:00:00Z", guest_reference="BK-9400")
    validate_success(
        api.advance_rental_turnover(turnover["id"], {"to_status": "CHECKOUT"}, DISPATCHER)
    )

    response = api.advance_rental_turnover(turnover["id"], {"to_status": "READY"}, DISPATCHER)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_TURNOVER_STAGE_INVALID.value,
         ApiErrorId.ERR_INVALID_STATE_TRANSITION.value],
    )
    reread = refresh_turnover(turnover["id"])
    assert reread["status"] == "CHECKOUT"
    assert reread["clean_started_at"] is None
    assert reread["ready_at"] is None


def test_the_third_failed_inspection_exhausts_the_reclean_cap(api):
    """PRD 3.9: "Failing an inspection is a separate capability that sends the turnover
    back from `INSPECTION` to `CLEANING`, requires `reclean_attempt_count` to be strictly
    less than two — a third attempt is rejected with `ERR_RECLEAN_ATTEMPTS_EXHAUSTED` —
    advances `reclean_attempt_count` by one, and clears `inspect_started_at` back to null."

    Design: Corner/state_machines/rental_turnover_reclean_cap_exhausted_returns_409
    """
    set_clock("2026-06-10T12:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Turn House", address_line="2 Clean Ct",
                        travel_distance_miles=5.0, rental_program_enrolled=True)
    turnover = new_rental_turnover(prop["id"], checkout_at="2026-06-10T11:00:00Z",
                                   checkin_at="2026-06-12T15:00:00Z", guest_reference="BK-9200")
    for stage in ("CHECKOUT", "CLEANING", "INSPECTION"):
        validate_success(
            api.advance_rental_turnover(turnover["id"], {"to_status": stage}, DISPATCHER)
        )
    for _ in range(2):
        validate_success(api.fail_inspection_rental_turnover(turnover["id"], {}, FIELD_TECH))
        validate_success(
            api.advance_rental_turnover(turnover["id"], {"to_status": "INSPECTION"}, DISPATCHER)
        )

    response = api.fail_inspection_rental_turnover(turnover["id"], {}, FIELD_TECH)
    validate_error(response, ApiErrorId.ERR_RECLEAN_ATTEMPTS_EXHAUSTED.value)
    reread = refresh_turnover(turnover["id"])
    assert reread["status"] == "INSPECTION"
    assert reread["reclean_attempt_count"] == 2


# --------------------------------------------------------------------------
# Mail holds
# --------------------------------------------------------------------------

def test_the_overflow_loop_returns_to_active_when_packages_are_collected(api):
    """PRD 3.9: "Overflow is reached when the new count is **at or above** six, so exactly
    six packages is already an overflow."
    PRD 3.9: "A positive delta that brings the count to at least six moves the hold from
    `ACTIVE` to `OVERFLOW` and advances `overflow_events` by one; **no security incident
    and no finding is created — overflow is a billing and scheduling signal only**. A
    negative delta that brings the count back below six moves the hold from `OVERFLOW` to
    `ACTIVE`, reducing `package_count` by the collected amount."

    Design: Corner/state_machines/mail_hold_overflow_loop_returns_to_active_on_collection
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Mail House", address_line="6 Post Rd",
                        travel_distance_miles=5.0)
    hold = new_mail_hold(prop["id"], start_on="2026-06-01T00:00:00Z",
                         end_on="2026-06-25T00:00:00Z")
    assert hold["hold_days"] == 24

    activated = log_packages(hold["id"], 0)
    assert activated["status"] == "ACTIVE"
    overflowed = log_packages(hold["id"], 6)
    assert overflowed["status"] == "OVERFLOW"
    assert overflowed["package_count"] == 6
    assert overflowed["overflow_events"] == 1

    collected = log_packages(hold["id"], -2)
    assert collected["status"] == "ACTIVE"
    assert collected["package_count"] == 4
    assert collected["overflow_events"] == 1
    _, meta = validate_paginated(
        api.list_security_incidents(headers=AUDITOR, params={"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0, "overflow creates no security incident"


def test_the_forward_fee_is_affine_in_the_package_count(api):
    """PRD 3.9: "On the **forward** branch the fee is an affine function of packages: a
    base of 1800 cents plus 250 cents for every package in `package_count`, so a forward
    with six packages costs 3300 cents and the fee grows without bound as packages
    accumulate."

    Design: Corner/calculations/mail_forward_fee_is_affine_in_package_count
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Fwd House", address_line="18 Route Rd",
                        travel_distance_miles=5.0)
    hold = setup_active_mail_hold(prop["id"], start_on="2026-06-01T00:00:00Z",
                                  end_on="2026-06-20T00:00:00Z",
                                  forwarding_address="88 North St, Duluth MN")
    log_packages(hold["id"], 6)

    forwarded = validate_success(api.forward_mail_hold(hold["id"], {}, DISPATCHER))
    assert forwarded["status"] == "FORWARDED"
    assert forwarded["disposition_fee_cents"] == 3300, "1800 base plus 250 per package"
    assert forwarded["package_count"] == 6


def test_the_extension_fee_is_linear_in_the_extension_count(api):
    """PRD 3.9: "On the **hold-extension** branch the fee is purely multiplicative in
    extensions with no base at all: 900 cents multiplied by `extension_count`, so a hold
    extended twice carries 1800 cents, and because extensions are capped at two the branch
    is capped at 1800."
    PRD 3.9: "The extension adds 15 days to `end_on`, advances `extension_count` by one,
    and runs the hold-extension fee branch."

    Design: Corner/calculations/hold_extension_fee_is_linear_in_extension_count_and_moves_end_on
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Ext House", address_line="15 Extend Ave",
                        travel_distance_miles=5.0)
    hold = setup_active_mail_hold(prop["id"], start_on="2026-06-01T00:00:00Z",
                                  end_on="2026-06-21T00:00:00Z")

    once = validate_success(api.extend_mail_hold(hold["id"], {}, DISPATCHER))
    assert once["extension_count"] == 1
    assert once["disposition_fee_cents"] == 900
    assert once["hold_days"] == 35

    twice = validate_success(api.extend_mail_hold(hold["id"], {}, DISPATCHER))
    assert twice["extension_count"] == 2
    assert twice["disposition_fee_cents"] == 1800
    assert twice["hold_days"] == 50
    assert_same_instant(twice["end_on"], "2026-07-21T00:00:00Z", "end_on")
    assert twice["status"] == "ACTIVE"


def test_a_third_extension_is_refused(api):
    """PRD 3.9: "Extending a hold requires `extension_count` to be strictly below two, an
    exhausted hold being rejected with `ERR_HOLD_EXTENSIONS_EXHAUSTED`."

    Design: Corner/errors/err_hold_extensions_exhausted_on_third_extend_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="MaxExt House", address_line="2 Cap Ct",
                        travel_distance_miles=5.0)
    hold = setup_active_mail_hold(prop["id"], start_on="2026-06-01T00:00:00Z",
                                  end_on="2026-06-21T00:00:00Z")
    validate_success(api.extend_mail_hold(hold["id"], {}, DISPATCHER))
    validate_success(api.extend_mail_hold(hold["id"], {}, DISPATCHER))

    response = api.extend_mail_hold(hold["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_HOLD_EXTENSIONS_EXHAUSTED.value)
    reread = refresh_mail_hold(hold["id"])
    assert reread["extension_count"] == 2
    assert_same_instant(reread["end_on"], "2026-07-21T00:00:00Z", "end_on")
    assert reread["disposition_fee_cents"] == 1800


def test_a_hold_longer_than_thirty_days_is_refused_at_creation(api):
    """PRD 3.9: "`hold_days` is the whole days between the two, taken as the floor of the
    elapsed seconds divided by 86400. A creation whose `hold_days` exceeds 30 is rejected
    with `ERR_HOLD_TOO_LONG`, and so is an extension whose resulting `hold_days` would
    exceed 60."

    Design: Corner/errors/err_hold_too_long_on_create_beyond_thirty_days_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Hold House", address_line="30 Cap Ct",
                        travel_distance_miles=5.0)
    response = api.create_property_mail_hold(
        prop["id"],
        create_mail_hold_payload(start_on="2026-06-01T00:00:00Z", end_on="2026-07-11T00:00:00Z"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_HOLD_TOO_LONG.value)
    _, meta = validate_paginated(
        api.list_mail_holds(headers=AUDITOR, params={"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0


def test_forwarding_without_an_address_is_refused(api):
    """PRD 3.9: "Forwarding a hold requires a non-null `forwarding_address`, a missing one
    being rejected with `ERR_FORWARDING_ADDRESS_MISSING`."

    Design: Corner/errors/err_forwarding_address_missing_on_forward_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="NoFwd House", address_line="1 Null Nook",
                        travel_distance_miles=5.0)
    hold = setup_active_mail_hold(prop["id"], start_on="2026-06-01T00:00:00Z",
                                  end_on="2026-06-20T00:00:00Z")

    response = api.forward_mail_hold(hold["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_FORWARDING_ADDRESS_MISSING.value)
    reread = refresh_mail_hold(hold["id"])
    assert reread["status"] == "ACTIVE"
    assert reread["disposition_fee_cents"] == 0


def test_logging_packages_before_the_hold_starts_is_refused(api):
    """PRD 3.9: "A logging call with a `package_delta` of exactly zero moves the hold from
    `REQUESTED` to `ACTIVE`, permitted only once the logical clock is at or after
    `start_on`; an earlier attempt is rejected with `ERR_MAIL_HOLD_NOT_STARTED`, and no fee
    is assessed."

    Design: Corner/errors/err_mail_hold_not_started_before_start_on_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Early House", address_line="1 Soon St",
                        travel_distance_miles=5.0)
    hold = new_mail_hold(prop["id"], start_on="2026-07-01T00:00:00Z",
                         end_on="2026-07-21T00:00:00Z")

    response = api.log_packages_mail_hold(hold["id"], {"package_delta": 0}, FIELD_TECH)
    validate_error(response, ApiErrorId.ERR_MAIL_HOLD_NOT_STARTED.value)
    reread = refresh_mail_hold(hold["id"])
    assert reread["status"] == "REQUESTED"
    assert reread["package_count"] == 0


def test_releasing_a_hold_with_packages_outstanding_is_refused(api):
    """PRD 3.9: "Releasing a hold is reachable from `ACTIVE` and requires `package_count`
    to be exactly zero, outstanding packages being rejected with
    `ERR_PACKAGES_OUTSTANDING`; `disposition_fee_cents` stays at whatever the extension
    ladder left it."

    Design: Corner/errors/err_packages_outstanding_on_release_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Pkg House", address_line="3 Parcel Pl",
                        travel_distance_miles=5.0)
    hold = setup_active_mail_hold(prop["id"], start_on="2026-06-01T00:00:00Z",
                                  end_on="2026-06-20T00:00:00Z")
    log_packages(hold["id"], 3)

    response = api.release_mail_hold(hold["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_PACKAGES_OUTSTANDING.value)
    reread = refresh_mail_hold(hold["id"])
    assert reread["status"] == "ACTIVE"
    assert reread["package_count"] == 3


# --------------------------------------------------------------------------
# Security incidents
# --------------------------------------------------------------------------

def _alarm_property():
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Alarm House", "address_line": "9 Siren St",
                            "travel_distance_miles": 18.0},
    )
    ctx = dict(ctx)
    ctx["alarm_template"] = new_template("ALARM_RESPONSE", item_codes=["PERIMETER"],
                                         critical_item_codes=[])
    return ctx


def _investigate_payload(ctx, day: str):
    return {
        "checklist_template_id": ctx["alarm_template"]["id"],
        "scheduled_start_at": f"2026-06-{day}T10:00:00Z",
        "scheduled_end_at": f"2026-06-{day}T12:00:00Z",
    }


def test_the_escalation_loop_counts_each_pass_and_forces_one_visit_only(api):
    """PRD 3.9: "Escalation moves the incident from `INVESTIGATING` to `ESCALATED`,
    requires a `severity` of `HIGH` or `CRITICAL` — a lower severity is rejected with
    `ERR_SEVERITY_TOO_LOW_TO_ESCALATE` — and advances `escalation_count` by one."
    PRD 3.9: "Investigation is also the return edge from `ESCALATED` back to
    `INVESTIGATING`, and on that and every later pass **no additional visit is created**."

    Design: Corner/state_machines/security_incident_escalation_loop_increments_counter_once_per_pass
    """
    ctx = _alarm_property()
    incident = setup_investigating_incident(
        ctx["property_id"], incident_type="ALARM_INTRUSION", severity="HIGH",
        investigate_payload=_investigate_payload(ctx, "01"),
    )
    first_visit = incident["triggered_visit_id"]
    assert first_visit is not None

    validate_success(api.escalate_security_incident(incident["id"], {}, DISPATCHER))
    validate_success(api.investigate_security_incident(incident["id"], {}, DISPATCHER))
    escalated = validate_success(api.escalate_security_incident(incident["id"], {}, DISPATCHER))

    assert escalated["status"] == "ESCALATED"
    assert escalated["escalation_count"] == 2
    assert escalated["triggered_visit_id"] == first_visit
    _, meta = validate_paginated(api.list_visits(
        headers=AUDITOR,
        params={"property_id": ctx["property_id"], "visit_type": "ALARM_RESPONSE"},
    ))
    assert meta["total_count"] == 1


def test_a_medium_incident_cannot_be_escalated(api):
    """PRD 3.9: "Escalation moves the incident from `INVESTIGATING` to `ESCALATED`,
    requires a `severity` of `HIGH` or `CRITICAL` — a lower severity is rejected with
    `ERR_SEVERITY_TOO_LOW_TO_ESCALATE` — and advances `escalation_count` by one."

    Design: Corner/errors/err_severity_too_low_to_escalate_returns_409
    """
    ctx = _alarm_property()
    incident = setup_investigating_incident(
        ctx["property_id"], incident_type="ALARM_SMOKE", severity="MEDIUM",
        investigate_payload=_investigate_payload(ctx, "02"),
    )

    response = api.escalate_security_incident(incident["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_SEVERITY_TOO_LOW_TO_ESCALATE.value)
    reread = refresh_incident(incident["id"])
    assert reread["status"] == "INVESTIGATING"
    assert reread["escalation_count"] == 0


def test_a_water_leak_cannot_be_reclassified_as_a_false_alarm(api):
    """PRD 3.9: "It is permitted only when `incident_type` is `ALARM_INTRUSION`,
    `ALARM_SMOKE`, `FREEZE_ALARM` or `UNAUTHORIZED_ACCESS`; a `WATER_LEAK` or `VANDALISM`
    incident is rejected with `ERR_INCIDENT_NOT_ALARM_CLASS`."

    Design: Corner/errors/err_incident_not_alarm_class_on_water_leak_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Leak House", address_line="1 Damp Dr",
                        travel_distance_miles=5.0)
    incident = setup_investigating_incident(prop["id"], incident_type="WATER_LEAK",
                                            severity="MEDIUM")

    response = api.reclassify_false_alarm_security_incident(
        incident["id"], {"resolution_note": "Not an alarm"}, DISPATCHER
    )
    validate_error(response, ApiErrorId.ERR_INCIDENT_NOT_ALARM_CLASS.value)
    reread = refresh_incident(incident["id"])
    assert reread["status"] == "INVESTIGATING"
    assert reread["false_alarm_sequence"] is None
    assert reread["false_alarm_fee_cents"] == 0


def test_the_municipal_false_alarm_ladder_is_not_monotone(api):
    """PRD 3.9: "It then computes `false_alarm_fee_cents` from that sequence, and **the
    municipal ladder is deliberately not monotone**: the first occurrence costs nothing,
    the second costs 5000 cents, the third costs 15000 cents, the fourth **drops** to
    10000 cents because it falls under a different citation class, and the fifth and every
    later occurrence costs 25000 cents."
    PRD 3.1: "`false_alarm_count_window` counts the property's incidents in status
    `FALSE_ALARM` whose `reported_at` lies within 365 days of the logical clock."

    Design: Corner/calculations/false_alarm_fee_ladder_is_non_monotone_across_four_occurrences
    """
    ctx = _alarm_property()
    expected = [(1, 0), (2, 5000), (3, 15000), (4, 10000)]
    for index, (sequence, fee) in enumerate(expected, start=1):
        day = f"{index:02d}"
        set_clock(f"2026-06-{day}T00:00:00Z")
        incident = setup_investigating_incident(
            ctx["property_id"], incident_type="ALARM_INTRUSION", severity="LOW",
            investigate_payload=_investigate_payload(ctx, day),
        )
        reclassified = reclassify_false_alarm(incident["id"], f"Occurrence {index}")
        assert reclassified["status"] == "FALSE_ALARM"
        assert reclassified["false_alarm_sequence"] == sequence
        assert reclassified["false_alarm_fee_cents"] == fee, (
            f"occurrence {sequence} must bill {fee}, got {reclassified['false_alarm_fee_cents']}"
        )

    assert refresh_property(ctx)["false_alarm_count_window"] == 4


def test_a_false_alarm_reclassification_reaches_the_draft_invoice(api):
    """PRD 3.9: "The reclassification then re-derives the property's
    `false_alarm_count_window`; appends an `ACTIVE` invoice line with `line_type`
    `FALSE_ALARM_FEE` and an `amount_cents` equal to `false_alarm_fee_cents` to the
    property's draft invoice when one exists **and the fee is strictly greater than
    zero**; and re-derives that invoice's `gross_service_cents`, `subtotal_cents`,
    `tax_cents` and `total_cents`."

    Design: Corner/cross_cutting_complexity_layers/cascading_false_alarm_reclassification_reaches_the_invoice
    """
    ctx = _alarm_property()
    ctx = setup_draft_invoice(ctx)
    assert refresh_invoice(ctx["invoice_id"])["total_cents"] == 21385

    first = setup_investigating_incident(
        ctx["property_id"], incident_type="ALARM_INTRUSION", severity="LOW",
        investigate_payload=_investigate_payload(ctx, "01"),
    )
    first_done = reclassify_false_alarm(first["id"], "Cat")
    assert first_done["false_alarm_fee_cents"] == 0
    assert refresh_invoice(ctx["invoice_id"])["total_cents"] == 21385, (
        "a zero fee appends no line"
    )

    set_clock("2026-06-02T00:00:00Z")
    second = setup_investigating_incident(
        ctx["property_id"], incident_type="ALARM_INTRUSION", severity="LOW",
        investigate_payload=_investigate_payload(ctx, "02"),
    )
    second_done = reclassify_false_alarm(second["id"], "Wind gust")

    assert second_done["status"] == "FALSE_ALARM"
    assert second_done["false_alarm_sequence"] == 2
    assert second_done["false_alarm_fee_cents"] == 5000
    assert refresh_property(ctx)["false_alarm_count_window"] == 2

    fee_lines, meta = validate_paginated(api.list_invoice_lines(
        headers=AUDITOR, params={"security_incident_id": second["id"]}
    ))
    assert meta["total_count"] == 1
    assert fee_lines[0]["line_type"] == "FALSE_ALARM_FEE"
    assert fee_lines[0]["amount_cents"] == 5000

    invoice = refresh_invoice(ctx["invoice_id"])
    assert invoice["gross_service_cents"] == 24986
    assert invoice["tax_cents"] == 1749
    assert invoice["total_cents"] == 26735
    assert len([ln for ln in lines_of(ctx["invoice_id"])
                if ln["line_type"] == "FALSE_ALARM_FEE"]) == 1
