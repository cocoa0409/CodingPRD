"""Edges that exist, edges that do not, and the side effects an edge drags with it."""

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_A_USER_ID,
    OFFICER_B_HEADERS,
    OFFICER_B_USER_ID,
    ApiErrorId,
    assert_case_state,
    assert_cents,
    assert_courier_gates,
    assert_new_case_defaults,
    assert_page_meta,
    assert_partner_gate,
    assert_plan_state,
    assert_score_equal,
    factories as f,
    fixtures as fx,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
AUGUST_FIRST = "2026-08-01T00:00:00Z"
AUGUST_LAST = "2026-08-31T00:00:00Z"
ONE_YEAR_ON = "2027-08-01T00:00:00Z"
STALE_TRAINING = "2026-04-01"


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def test_01_a_second_submission_of_a_submitted_order_is_refused(api):
    """PRD 3.3: "An order with no lines at all cannot be submitted and reports
    `ERR_ORDER_HAS_NO_LINES`; an order whose `fulfillment_state` is anything other than
    `CREATED` reports `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/corner_second_submit_on_a_submitted_order_is_rejected
    """
    world = fx.build_unrestricted_world(api, clock=CLOCK, scheduled_delivery_at=EVENING)
    fx.submit_order(api, world["order"])

    response = api.submit_order(world["order"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.INVALID_ORDER_STATE.value)
    order = fx.read_order(api, world["order"]["id"])
    assert order["fulfillment_state"] == "SUBMITTED"
    assert order["compliance_state"] == "AUTO_CLEARED"
    assert _instant(order["submitted_at"]) == _instant(CLOCK), (
        "the first submission's stamp must survive the refused second one; got "
        f"{order['submitted_at']!r}"
    )
    assert_cents(order["charged_cents"], 2600, "charged_cents")


def _partner_under_one_audit_probe(api, scenario_type):
    """A partner, one of its couriers and a staged secret-shopper probe of that courier."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"])
    decoy = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    probe = fx.schedule_shopper_test(
        api, courier["id"], decoy["id"], scenario_type=scenario_type, scheduled_at=EVENING
    )
    return {"partner": partner, "courier": courier, "decoy": decoy, "probe": probe}


def test_02_a_manually_opened_case_lands_in_open_with_no_rounds_and_no_points(api):
    """PRD 3.9: "A new case opens with `state` `OPEN`, `investigation_rounds` 0,
    `risk_contribution` 0.00, and `assessed_severity`, `decided_at`,
    `substantiated_by_user_id`, `response_due_at`, `partner_response_text` and `notes` all
    null; opening it recounts the partner's `open_case_count` and
    `open_critical_case_count` and re-derives that partner's `posture`."

    Design: Corner/state_machines/corner_new_violation_case_starts_in_open_with_zero_rounds
    """
    world = _partner_under_one_audit_probe(api, "UNDERAGE_PRESENTER")

    response = api.create_violation_case(
        f.violation_case_payload(
            world["partner"]["id"],
            secret_shopper_test_id=world["probe"]["id"],
            severity="MAJOR",
            summary="Auditor observed the courier skipping the document scan.",
        ),
        OFFICER_A_HEADERS,
    )

    created = validate_success(response, expected_status=201)
    assert_case_state(created, "OPEN")
    assert created["origin"] == "MANUAL"
    assert created["delivery_attempt_id"] is None
    assert_new_case_defaults(created)
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]),
        posture="OPEN",
        open_case_count=1,
        open_critical_case_count=0,
        license_risk_score=0.00,
    )


def test_03_investigating_an_open_case_moves_it_on_and_counts_the_round(api):
    """PRD 3.9: "An officer opens the investigation, moving `OPEN → UNDER_INVESTIGATION`
    and incrementing `investigation_rounds`."

    Design: Corner/state_machines/corner_investigate_moves_case_open_to_under_investigation
    """
    world = _partner_under_one_audit_probe(api, "INTOXICATION_CUES")
    case = fx.open_manual_case(
        api,
        world["partner"]["id"],
        secret_shopper_test_id=world["probe"]["id"],
        severity="MAJOR",
        summary="Courier ignored visible intoxication cues.",
    )

    investigated = validate_success(api.investigate_case(case["id"], OFFICER_A_HEADERS))

    assert_case_state(investigated, "UNDER_INVESTIGATION")
    assert investigated["investigation_rounds"] == 1
    assert investigated["decided_at"] is None
    assert_score_equal(investigated["risk_contribution"], 0.00, "risk_contribution")
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]),
        open_case_count=1,
        license_risk_score=0.00,
    )


def test_04_dispatch_does_not_exist_as_an_edge_out_of_created(api):
    """PRD 3.4: "It is admissible along `SUBMITTED → DISPATCHED` — the first dispatch —
    and along `HELD_AT_HUB → DISPATCHED`, which is the release edge that closes the
    `DISPATCHED → HELD_AT_HUB → DISPATCHED` cycle and may be traversed any number of times
    without ever touching the compliance dimension on the way back."

    Design: Corner/state_machines/corner_dispatch_on_a_created_order_is_rejected
    """
    world = fx.build_unrestricted_world(api, clock=CLOCK, scheduled_delivery_at=EVENING)

    response = api.dispatch_order(
        world["order"]["id"], make_partner_manager_headers(world["partner"]["id"])
    )

    validate_error(response, ApiErrorId.INVALID_ORDER_STATE.value)
    order = fx.read_order(api, world["order"]["id"])
    assert order["fulfillment_state"] == "CREATED"
    assert order["compliance_state"] == "DRAFT_UNVERIFIED"
    assert order["dispatched_at"] is None


def _newly_hired_courier(api, clock=AUGUST_FIRST):
    """One partner and one courier, hired but not yet certified for anything."""
    fx.set_clock(api, clock)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"])
    return {"partner": partner, "courier": courier}


def test_05_issuing_a_certification_fires_every_declared_side_effect(api):
    """PRD 3.5: "On success the row stamps `issued_at` from the logical clock, computes
    `expires_at` as `issued_at` plus `valid_days` days, opens in `state` `ACTIVE` with
    `renewal_count` 0 and `revocation_reason` null, and triggers a re-derivation of the
    courier's `certification_state` and `dispatch_eligible`."

    Design: Corner/state_machines/corner_certification_issuance_derives_courier_gates
    """
    world = _newly_hired_courier(api)

    response = api.create_courier_certification(
        f.courier_certification_payload(world["courier"]["id"], valid_days=365),
        make_partner_manager_headers(world["partner"]["id"]),
    )

    certification = validate_success(response, expected_status=201)
    assert certification["state"] == "ACTIVE"
    assert _instant(certification["issued_at"]) == _instant(AUGUST_FIRST)
    assert _instant(certification["expires_at"]) == _instant(ONE_YEAR_ON), (
        "`expires_at` is `issued_at` plus the 365 supplied validity days; got "
        f"{certification['expires_at']!r}"
    )
    assert certification["renewal_count"] == 0
    assert certification["revocation_reason"] is None
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]),
        certification_state="CERTIFIED",
        dispatch_eligible=True,
        compliance_score=100.00,
        compliant_handover_count=0,
    )


def test_06_revoking_the_only_live_row_re_derives_the_courier_it_belonged_to(api):
    """PRD 3.5: "Beyond moving the `state` along `ACTIVE → REVOKED`,
    `SUSPENDED → REVOKED` or `EXPIRED → REVOKED` as the case may be, revocation re-derives
    the courier's `certification_state` and `dispatch_eligible` and aborts the courier's
    open delivery attempts in exactly the manner a suspension does — every attempt of
    that courier in `INITIATED`, `ID_VERIFIED` or `ID_REJECTED`, processed in
    `created_at` ascending order, moves `INITIATED → ABORTED`, `ID_VERIFIED → ABORTED`
    or `ID_REJECTED → ABORTED` according to where it stood, and each such order moves
    `OUT_FOR_DELIVERY → RETURN_IN_TRANSIT`."

    Design: Corner/state_machines/corner_courier_state_is_recomputed_when_its_last_certification_is_revoked
    """
    world = _newly_hired_courier(api)
    certification = fx.issue_certification(api, world["courier"], valid_days=365)

    revoked = validate_success(
        api.revoke_courier_certification(
            certification["id"],
            f.certification_revocation_payload(),
            OFFICER_A_HEADERS,
        )
    )

    assert revoked["state"] == "REVOKED"
    assert revoked["revocation_reason"] == "Falsified training record"
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]),
        certification_state="UNCERTIFIED",
        dispatch_eligible=False,
        compliance_score=100.00,
    )
    live, meta = validate_paginated(
        api.list_courier_certifications(
            world["courier"]["id"], ADMIN_HEADERS, {"state": "ACTIVE"}
        )
    )
    assert live == [], f"the courier keeps no live certification; got {len(live)}"
    assert_page_meta(meta, total_count=0)


def test_07_a_renewal_with_stale_training_is_refused_however_high_the_score(api):
    """PRD 3.5: "Both branches additionally demand freshness — the logical clock now
    minus `training_completed_at` must be no more than 90 days, and staler training reports
    `ERR_TRAINING_STALE`."

    Design: Corner/state_machines/corner_certification_renewal_with_stale_training_is_rejected
    """
    world = _newly_hired_courier(api)
    certification = fx.issue_certification(api, world["courier"], valid_days=30)
    sweep = fx.set_clock(api, AUGUST_LAST)
    assert sweep["expired_certification_count"] == 1, (
        "the clock advance must have carried the row past its expiry; got "
        f"{sweep['expired_certification_count']}"
    )

    response = api.renew_courier_certification(
        certification["id"],
        f.certification_renewal_payload(
            training_score=95, training_completed_at=STALE_TRAINING, valid_days=365
        ),
        make_partner_manager_headers(world["partner"]["id"]),
    )

    validate_error(response, ApiErrorId.TRAINING_STALE.value)
    unchanged = fx.read_certification(api, certification["id"])
    assert unchanged["state"] == "EXPIRED"
    assert unchanged["renewal_count"] == 0
    assert _instant(unchanged["expires_at"]) == _instant(AUGUST_LAST)
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]),
        certification_state="UNCERTIFIED",
        dispatch_eligible=False,
    )


def _critical_case_substantiated_with_a_plan_accepted(api):
    """A `CRITICAL` case substantiated by one officer with a plan accepted by another."""
    world = _partner_under_one_audit_probe(api, "UNDERAGE_PRESENTER")
    case = fx.build_substantiated_case(
        api,
        world["partner"]["id"],
        secret_shopper_test_id=world["probe"]["id"],
        severity="CRITICAL",
        assessed_severity="CRITICAL",
        officer_headers=OFFICER_A_HEADERS,
    )
    plan = fx.file_plan(api, case)
    accepted = fx.review_plan(api, plan["id"], "ACCEPT", OFFICER_B_HEADERS)
    world.update({"case": case, "plan": accepted})
    return world


def test_08_verifying_the_plan_closes_the_case_and_halves_the_partner_score(api):
    """PRD 3.9: "A `PASSED` outcome moves the plan `ACCEPTED → VERIFIED` and drives the
    parent case `SUBSTANTIATED → CLOSED_VERIFIED`, which halves that case's contribution
    through the verified-remediation credit factor of 0.50, recomputes both of the
    partner's risk-score variants, and re-derives the partner's `posture` — the mechanism
    by which a partner earns its way back from `SUSPENDED` to `RESTRICTED` or from
    `RESTRICTED` to `OPEN`."

    Design: Corner/state_machines/corner_plan_verification_bubbles_the_case_to_closed_verified
    """
    world = _critical_case_substantiated_with_a_plan_accepted(api)
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]),
        posture="RESTRICTED",
        license_risk_score=40.00,
    )

    verified = validate_success(
        api.verify_corrective_action_plan(
            world["plan"]["id"], f.plan_verify_payload("PASSED"), OFFICER_B_HEADERS
        )
    )

    assert_plan_state(verified, "VERIFIED")
    assert verified["verified_by_user_id"] == OFFICER_B_USER_ID
    assert verified["reviewed_by_user_id"] == OFFICER_B_USER_ID
    case = fx.read_case(api, world["case"]["id"])
    assert_case_state(case, "CLOSED_VERIFIED")
    assert case["substantiated_by_user_id"] == OFFICER_A_USER_ID
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]),
        posture="OPEN",
        open_case_count=0,
        license_risk_score=20.00,
        lifetime_risk_score=20.00,
    )


def test_09_a_closed_verified_case_refuses_to_reopen(api):
    """PRD 3.9: "Reopening is the compensating action, and it is admissible along
    `SUBSTANTIATED → UNDER_INVESTIGATION` and along `DISMISSED → UNDER_INVESTIGATION`, with
    a required `notes` narrative."

    Design: Corner/state_machines/corner_reopen_on_a_closed_verified_case_is_rejected
    """
    world = _critical_case_substantiated_with_a_plan_accepted(api)
    fx.verify_plan(api, world["plan"]["id"], "PASSED", OFFICER_B_HEADERS)

    response = api.reopen_case(
        world["case"]["id"],
        f.case_reopen_payload(notes="New complaint received."),
        OFFICER_A_HEADERS,
    )

    validate_error(response, ApiErrorId.INVALID_CASE_STATE.value)
    case = fx.read_case(api, world["case"]["id"])
    assert_case_state(case, "CLOSED_VERIFIED")
    assert case["investigation_rounds"] == 1, (
        "the refused reopen must not have counted a round; got "
        f"{case['investigation_rounds']}"
    )
    assert_plan_state(fx.read_plan(api, world["plan"]["id"]), "VERIFIED")
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]),
        posture="OPEN",
        license_risk_score=20.00,
    )
