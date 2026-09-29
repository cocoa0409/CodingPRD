"""Every endpoint written down, called once, and read back through its own filters."""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_A_USER_ID,
    ApiErrorId,
    assert_case_state,
    assert_cents,
    assert_common_fields,
    assert_courier_gates,
    assert_order_states,
    assert_page_meta,
    assert_partner_gate,
    assert_plan_state,
    assert_score_equal,
    assert_units_equal,
    factories as f,
    fixtures as fx,
    ids_of,
    make_courier_headers,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

EPOCH = "2026-08-01T00:00:00Z"
AUGUST_LAST = "2026-08-31T00:00:00Z"
THIRTY_DAYS_ON = "2026-09-30T00:00:00"
NOVEMBER = "2026-11-01T00:00:00Z"
IDENTITY_HORIZON = "2026-10-30T00:00:00"
CLOCK = "2026-08-20T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
LATER_EVENING = "2026-08-20T19:00:00Z"
TOMORROW_EVENING = "2026-08-21T18:00:00Z"
CERTIFICATION_HORIZON = "2027-08-20T12:00:00"
FIRST_DEADLINE = "2026-09-01T12:00:00Z"
SECOND_DEADLINE = "2026-09-05T12:00:00Z"
PLAN_DUE = "2026-09-15T12:00:00Z"
GROCERY_HAMPER_SKU = "GROCERY-P"
PAGE = {"limit": 10, "offset": 0}


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def _page(params):
    """One declared filter plus the explicit page bounds of PRD 2.3."""
    merged = dict(PAGE)
    merged.update(params)
    return merged


def test_01_a_published_policy_reads_back_by_id_and_through_the_class_filter(api):
    """PRD 3.1: "`effective_from` and `effective_to` bound the closed calendar period over
    which the row governs, and a period sharing any date with an existing period for the
    same jurisdiction and class is rejected with `ERR_POLICY_PERIOD_OVERLAP`. A policy read
    against an unknown identifier reports `ERR_POLICY_NOT_FOUND`. Per-jurisdiction policy
    listings accept an optional `restriction_type` filter."

    Design: Corner/endpoints/corner_restriction_policy_crud_round_trips_through_read_and_list
    """
    fx.set_clock(api, EPOCH)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    alcohol = fx.create_policy(api, jurisdiction["id"])
    fx.create_policy(
        api,
        jurisdiction["id"],
        restriction_type="TOBACCO_VAPE",
        delivery_window_start_minute=540,
        delivery_window_end_minute=1260,
        unit_scale_factor=2.00,
        max_units_per_order=10.00,
        max_units_per_window=20.00,
        acceptable_document_types=["DRIVERS_LICENSE"],
    )

    stored = validate_success(api.get_restriction_policy(alcohol["id"], OFFICER_A_HEADERS))
    narrowed, meta = validate_paginated(
        api.list_jurisdiction_restriction_policies(
            jurisdiction["id"], OFFICER_A_HEADERS, {"restriction_type": "ALCOHOL"}
        )
    )

    assert stored["jurisdiction_id"] == jurisdiction["id"]
    assert stored["restriction_type"] == "ALCOHOL"
    assert stored["permissibility"] == "PERMITTED"
    assert stored["min_age_years"] == 21
    assert stored["delivery_window_start_minute"] == 600
    assert stored["delivery_window_end_minute"] == 1320
    assert_units_equal(stored["unit_scale_factor"], 1.00, "unit_scale_factor")
    assert stored["acceptable_document_types"] == ["DRIVERS_LICENSE", "PASSPORT"]
    assert stored["requires_scan"] is True
    assert stored["effective_from"] == "2026-08-01"
    assert stored["effective_to"] == "2026-08-31"
    assert_common_fields(stored, expected_version=1)
    assert_page_meta(meta, total_count=1)
    assert ids_of(narrowed) == [alcohol["id"]], (
        "the class filter must exclude the tobacco row; got "
        f"{len(narrowed)} rows for ALCOHOL"
    )
    reread = validate_success(api.get_jurisdiction(jurisdiction["id"], ADMIN_HEADERS))
    assert reread["active_policy_count"] == 2, (
        "the counter spans every effective period of the jurisdiction; got "
        f"{reread['active_policy_count']}"
    )


def test_02_renewal_revives_the_same_row_rather_than_minting_a_second(api):
    """PRD 3.5: "A successful renewal along `EXPIRED → ACTIVE` or `SUSPENDED → ACTIVE`
    re-stamps `issued_at` from the logical clock, recomputes `expires_at` from the new
    `valid_days`, increments `renewal_count` by one, and re-derives the courier's
    `certification_state` and `dispatch_eligible`."

    Design: Corner/endpoints/corner_certification_renew_revives_an_expired_row_and_bumps_the_counter
    """
    fx.set_clock(api, EPOCH)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    certification = fx.issue_certification(api, courier, valid_days=30)
    sweep = fx.set_clock(api, AUGUST_LAST)
    assert sweep["expired_certification_count"] == 1, (
        f"the advance must have lapsed the row; got {sweep['expired_certification_count']}"
    )

    renewed = validate_success(
        api.renew_courier_certification(
            certification["id"],
            f.certification_renewal_payload(
                training_score=95, training_completed_at="2026-08-25", valid_days=30
            ),
            make_partner_manager_headers(partner["id"]),
        )
    )

    assert renewed["id"] == certification["id"], (
        "renewal is an action on the existing row, not a second registration"
    )
    assert renewed["state"] == "ACTIVE"
    assert renewed["renewal_count"] == 1
    assert renewed["training_score"] == 95
    assert renewed["training_completed_at"] == "2026-08-25"
    assert _instant(renewed["issued_at"]) == _instant(AUGUST_LAST)
    assert _instant(renewed["expires_at"]) == THIRTY_DAYS_ON, (
        "`expires_at` is re-anchored on the clock, not on the stale expiry; got "
        f"{renewed['expires_at']!r}"
    )
    assert_courier_gates(
        fx.read_courier(api, courier["id"]),
        certification_state="CERTIFIED",
        dispatch_eligible=True,
    )
    rows, meta = validate_paginated(api.list_courier_certifications(courier["id"], ADMIN_HEADERS))
    assert_page_meta(meta, total_count=1)
    assert ids_of(rows) == [certification["id"]]


def _one_order_awaiting_review_and_one_already_cleared(api):
    """A purchaser whose identity banded `PARTIAL`, holding a wine order and a grocery one."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(api, jurisdiction["id"])
    wine = fx.create_product(api, f.wine_product_payload(name="Cabernet 750ml"))
    hamper = fx.create_product(
        api,
        f.grocery_product_payload(
            sku=GROCERY_HAMPER_SKU, name="Premium Pantry Hamper", list_price_cents=6800
        ),
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    fx.add_identity_check(
        api,
        customer["id"],
        provider="NATIONAL_ID_VENDOR",
        provided_dob=f.ADULT_DOB,
        source_dob="2000-03-16",
        source_signals=f.source_signals(mobile_carrier=True),
    )
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    restricted = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    fx.add_line(api, restricted, wine["id"], 2)
    unrestricted = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], LATER_EVENING, 600
    )
    fx.add_line(api, unrestricted, hamper["id"], 1)
    return {
        "customer": customer,
        "under_review": fx.submit_order(api, restricted),
        "auto_cleared": fx.submit_order(api, unrestricted),
    }


def test_03_clearance_answers_only_for_an_order_parked_in_review(api):
    """PRD 3.4: "Manual clearance is the `ComplianceOfficer`'s decision on an order parked
    in `PENDING_COMPLIANCE_REVIEW`; from any other compliance state the request reports
    `ERR_INVALID_ORDER_STATE`."

    Design: Corner/endpoints/corner_clearance_acts_only_on_an_order_pending_compliance_review
    """
    world = _one_order_awaiting_review_and_one_already_cleared(api)
    assert_order_states(world["under_review"], compliance_state="PENDING_COMPLIANCE_REVIEW")
    assert world["under_review"]["hold_reason"] is None, (
        "`hold_reason` belongs to the posture cascade, not to review routing; got "
        f"{world['under_review']['hold_reason']!r}"
    )
    assert_order_states(world["auto_cleared"], compliance_state="AUTO_CLEARED")

    refused = api.record_clearance(
        world["auto_cleared"]["id"], f.clearance_payload("CLEAR"), OFFICER_A_HEADERS
    )
    accepted = validate_success(
        api.record_clearance(
            world["under_review"]["id"], f.clearance_payload("CLEAR"), OFFICER_A_HEADERS
        )
    )

    validate_error(refused, ApiErrorId.INVALID_ORDER_STATE.value)
    untouched = fx.read_order(api, world["auto_cleared"]["id"])
    assert_order_states(untouched, compliance_state="AUTO_CLEARED")
    assert untouched["clearance_actor_user_id"] is None, (
        f"the refused clearance stored no actor; got {untouched['clearance_actor_user_id']!r}"
    )
    assert_order_states(
        accepted, compliance_state="COMPLIANCE_CLEARED", fulfillment_state="SUBMITTED"
    )
    assert accepted["clearance_actor_user_id"] == OFFICER_A_USER_ID, (
        "the acting officer's `X-User-ID` is stored verbatim; got "
        f"{accepted['clearance_actor_user_id']!r}"
    )


def test_04_a_staged_probe_is_reachable_from_the_courier_and_from_the_decoy_order(api):
    """PRD 3.8: "A newly scheduled test opens with `verdict` `PENDING`, and with
    `observed_outcome`, `findings` and `recorded_at` all null. Tests can be listed with
    `courier_id`, `order_id` and `verdict` filters, and an unknown identifier reports
    `ERR_SHOPPER_TEST_NOT_FOUND`."

    Design: Corner/endpoints/corner_secret_shopper_test_links_a_courier_and_an_order
    """
    world = fx.build_unrestricted_world(
        api, clock=CLOCK, scheduled_delivery_at=TOMORROW_EVENING, quantity=1
    )
    decoy = fx.submit_order(api, world["order"])

    created = validate_success(
        api.create_secret_shopper_test(
            f.secret_shopper_test_payload(
                world["courier"]["id"],
                decoy["id"],
                scenario_type="UNDERAGE_PRESENTER",
                scheduled_at=TOMORROW_EVENING,
                expected_outcome="REFUSAL",
            ),
            AUDITOR_HEADERS,
        ),
        expected_status=201,
    )

    assert created["verdict"] == "PENDING"
    for field in ("observed_outcome", "findings", "recorded_at"):
        assert created[field] is None, (
            f"a freshly staged probe's `{field}` must be null, got {created[field]!r}"
        )
    assert created["expected_outcome"] == "REFUSAL"
    assert created["scenario_type"] == "UNDERAGE_PRESENTER"
    by_courier, courier_meta = validate_paginated(
        api.list_secret_shopper_tests(AUDITOR_HEADERS, {"courier_id": world["courier"]["id"]})
    )
    by_order, order_meta = validate_paginated(
        api.list_secret_shopper_tests(AUDITOR_HEADERS, {"order_id": decoy["id"]})
    )
    assert_page_meta(courier_meta, total_count=1)
    assert_page_meta(order_meta, total_count=1)
    assert ids_of(by_courier) == [created["id"]] == ids_of(by_order), (
        "one row answers both parents' filters"
    )
    fetched = validate_success(api.get_secret_shopper_test(created["id"], OFFICER_A_HEADERS))
    assert fetched["courier_id"] == world["courier"]["id"]
    assert fetched["order_id"] == decoy["id"]
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]), compliance_score=100.00
    )


def test_05_the_evaluation_replays_the_battery_and_persists_nothing(api):
    """PRD 3.3: "It returns the `order_id` it evaluated, the `restriction_types` and
    `applied_policy_ids` it resolved, the `provisional_restricted_units` total and a
    `per_type_exposure` array breaking that total down per restriction class, the
    `window_units_consumed` figure from the rolling look-back, the `local_delivery_minute` it
    derived and the boolean `in_delivery_window` verdict for it, the `purchaser_age_years` it
    computed alongside the `min_age_required` it compared that age against, the
    `identity_result` of the newest valid check, the `would_route_to` compliance state the
    order would land in, and `first_blocking_error_id` — the identifier of the first
    objection the battery would raise, or null when the replay finds none."

    Design: Corner/endpoints/corner_compliance_evaluation_is_a_read_only_projection
    """
    world = fx.build_restricted_world(api, clock=CLOCK)
    built = fx.add_restricted_order(api, world, quantity=2, scheduled_delivery_at=EVENING)
    before = fx.read_order(api, built["order"]["id"])

    by_owner = api.get_compliance_evaluation(built["order"]["id"], world["customer_headers"])
    by_officer = api.get_compliance_evaluation(built["order"]["id"], OFFICER_A_HEADERS)

    projection = validate_success(by_owner)
    assert projection == validate_success(by_officer), (
        "the same replay answers the owning purchaser and the officer identically"
    )
    assert projection["order_id"] == built["order"]["id"]
    assert projection["restriction_types"] == ["ALCOHOL"]
    assert projection["applied_policy_ids"] == [world["policy"]["id"]]
    assert_units_equal(
        projection["provisional_restricted_units"], 3.00, "provisional_restricted_units"
    )
    assert len(projection["per_type_exposure"]) == 1, (
        "the breakdown carries one row per restriction class; got "
        f"{len(projection['per_type_exposure'])}"
    )
    assert_units_equal(projection["window_units_consumed"], 0.00, "window_units_consumed")
    assert projection["local_delivery_minute"] == 840, (
        "18:00Z at an offset of -240 minutes is local 14:00; got "
        f"{projection['local_delivery_minute']}"
    )
    assert projection["in_delivery_window"] is True
    assert projection["purchaser_age_years"] == 26
    assert projection["min_age_required"] == 21
    assert projection["identity_result"] == "MATCH"
    assert projection["would_route_to"] == "PREVERIFIED"
    assert projection["first_blocking_error_id"] is None
    after = fx.read_order(api, built["order"]["id"])
    assert_order_states(after, compliance_state="DRAFT_UNVERIFIED", fulfillment_state="CREATED")
    assert after["version"] == before["version"], (
        f"reading a diagnostic writes nothing; version moved to {after['version']}"
    )
    assert_cents(after["charged_cents"], 0, "charged_cents")
    assert after["submitted_at"] is None


def test_06_one_clock_advance_reports_each_sweep_step_on_its_own_counter(api):
    """PRD 2.5: "The response reports `current_utc` together with
    `expired_identity_check_count`, `expired_certification_count` and
    `repostured_partner_count`, the last counting partners whose `posture` value actually
    changed during step three."

    Design: Corner/endpoints/corner_clock_advance_reports_every_sweep_counter_it_touched
    """
    fx.set_clock(api, EPOCH)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    fx.add_identity_check(api, customer["id"], provided_dob=f.ADULT_DOB, validity_days=90)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    certification = fx.issue_certification(api, courier, valid_days=30)

    sweep = fx.set_clock(api, NOVEMBER)

    assert _instant(sweep["current_utc"]) == _instant(NOVEMBER)
    assert sweep["expired_identity_check_count"] == 1, (
        f"step one lapsed the pre-verification; got {sweep['expired_identity_check_count']}"
    )
    assert sweep["expired_certification_count"] == 1, (
        f"step two lapsed the credential; got {sweep['expired_certification_count']}"
    )
    assert sweep["repostured_partner_count"] == 0, (
        "no case exists, so step three changed nobody's posture; got "
        f"{sweep['repostured_partner_count']}"
    )
    lapsed, meta = validate_paginated(
        api.list_identity_checks(customer["id"], ADMIN_HEADERS, {"status": "EXPIRED"})
    )
    assert_page_meta(meta, total_count=1)
    assert _instant(lapsed[0]["expires_at"]) == IDENTITY_HORIZON, (
        f"`expires_at` is the issue instant plus 90 days; got {lapsed[0]['expires_at']!r}"
    )
    assert lapsed[0]["status"] == "EXPIRED"
    assert fx.read_certification(api, certification["id"])["state"] == "EXPIRED"
    assert_courier_gates(
        fx.read_courier(api, courier["id"]),
        certification_state="UNCERTIFIED",
        dispatch_eligible=False,
    )
    assert_partner_gate(fx.read_partner(api, partner["id"]), posture="OPEN")


def _one_case_under_investigation(api):
    """A major case opened off an audit probe and already walked into investigation."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    decoy = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], TOMORROW_EVENING, 600
    )
    probe = fx.schedule_shopper_test(
        api,
        courier["id"],
        decoy["id"],
        scenario_type="NO_ID_PRESENTED",
        scheduled_at=TOMORROW_EVENING,
    )
    case = fx.open_manual_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe["id"],
        severity="MAJOR",
        summary="Courier accepted a library card.",
    )
    fx.investigate_case(api, case["id"], OFFICER_A_HEADERS)
    return {"partner": partner, "case": case}


def test_07_the_partner_response_cycle_counts_a_round_every_time_it_is_traversed(api):
    """PRD 3.9: "The `PartnerManager` whose `X-User-ID` equals the case's
    `delivery_partner_id` answers with a `partner_response_text`, moving
    `PENDING_PARTNER_RESPONSE → UNDER_INVESTIGATION` and incrementing
    `investigation_rounds` again. This is the first of the case's two cycles and it may be
    traversed any number of times."

    Design: Corner/endpoints/corner_partner_response_cycle_bounces_the_case_and_counts_every_round
    """
    world = _one_case_under_investigation(api)
    case_id = world["case"]["id"]
    partner_headers = make_partner_manager_headers(world["partner"]["id"])

    asked = validate_success(
        api.request_partner_response(
            case_id,
            f.request_partner_response_payload(
                FIRST_DEADLINE, notes="Explain the document acceptance."
            ),
            OFFICER_A_HEADERS,
        )
    )
    assert_case_state(asked, "PENDING_PARTNER_RESPONSE")
    assert _instant(asked["response_due_at"]) == _instant(FIRST_DEADLINE)
    assert asked["investigation_rounds"] == 1

    premature = api.decide_case(
        case_id,
        f.case_decision_payload("SUBSTANTIATED", "MAJOR", notes="Premature decision."),
        OFFICER_A_HEADERS,
    )
    validate_error(premature, ApiErrorId.INVALID_CASE_STATE.value)
    waiting = fx.read_case(api, case_id)
    assert_case_state(waiting, "PENDING_PARTNER_RESPONSE")
    assert waiting["decided_at"] is None
    assert waiting["assessed_severity"] is None

    answered = validate_success(
        api.record_partner_response(
            case_id,
            f.partner_response_payload(
                partner_response_text="The courier misread the badge; retraining scheduled."
            ),
            partner_headers,
        )
    )
    assert_case_state(answered, "UNDER_INVESTIGATION")
    assert answered["investigation_rounds"] == 2
    assert (
        answered["partner_response_text"]
        == "The courier misread the badge; retraining scheduled."
    )

    asked_again = validate_success(
        api.request_partner_response(
            case_id,
            f.request_partner_response_payload(
                SECOND_DEADLINE, notes="Provide the retraining roster."
            ),
            OFFICER_A_HEADERS,
        )
    )
    assert_case_state(asked_again, "PENDING_PARTNER_RESPONSE")
    assert _instant(asked_again["response_due_at"]) == _instant(SECOND_DEADLINE)
    assert asked_again["investigation_rounds"] == 2, (
        "asking is not answering, so the round count holds; got "
        f"{asked_again['investigation_rounds']}"
    )

    answered_again = validate_success(
        api.record_partner_response(
            case_id,
            f.partner_response_payload(
                partner_response_text="Roster attached; four couriers retrained."
            ),
            partner_headers,
        )
    )
    assert answered_again["investigation_rounds"] == 3, (
        "the cycle edge was traversed twice, not collapsed; got "
        f"{answered_again['investigation_rounds']}"
    )
    assert answered_again["partner_response_text"] == "Roster attached; four couriers retrained."

    decided = validate_success(
        api.decide_case(
            case_id,
            f.case_decision_payload(
                "SUBSTANTIATED", "MAJOR", notes="Substantiated after two rounds."
            ),
            OFFICER_A_HEADERS,
        )
    )
    assert_case_state(decided, "SUBSTANTIATED")
    assert _instant(decided["decided_at"]) == _instant(CLOCK)
    assert decided["assessed_severity"] == "MAJOR"
    assert_score_equal(decided["risk_contribution"], 15.00, "risk_contribution")
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]), posture="OPEN", license_risk_score=15.00
    )
    assert fx.read_case(api, case_id)["investigation_rounds"] == 3


def _one_populated_database(api):
    """One row in every collection the API exposes, reachable through every read."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    hamper = fx.create_product(
        api,
        f.grocery_product_payload(
            sku=GROCERY_HAMPER_SKU, name="Premium Pantry Hamper", list_price_cents=6800
        ),
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    identity_check = fx.add_identity_check(api, customer["id"], provided_dob=f.ADULT_DOB)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    certification = fx.issue_certification(api, courier, valid_days=365)
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    line = fx.add_line(api, order, hamper["id"], 1)
    fx.dispatch_order(api, fx.submit_order(api, order))
    fx.set_clock(api, EVENING)
    attempt = fx.open_attempt(api, order, courier, EVENING)
    case = fx.open_manual_case(
        api,
        partner["id"],
        delivery_attempt_id=attempt["id"],
        severity="MAJOR",
        summary="Late arrival with an unsealed tote.",
    )
    fx.investigate_case(api, case["id"], OFFICER_A_HEADERS)
    fx.decide_case(api, case["id"], "SUBSTANTIATED", assessed_severity="MAJOR")
    plan = fx.file_plan(
        api, case, remediation_items=["Seal every tote at the hub"], due_at=PLAN_DUE
    )
    return {
        "jurisdiction": jurisdiction,
        "hamper": hamper,
        "customer": customer,
        "identity_check": identity_check,
        "partner": partner,
        "courier": courier,
        "certification": certification,
        "order": order,
        "line": line,
        "attempt": attempt,
        "case": case,
        "plan": plan,
    }


def test_08_every_remaining_read_returns_its_row_and_honours_its_filter(api):
    """PRD 2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true exactly when rows remain beyond the
    returned page."

    Design: Corner/endpoints/corner_every_remaining_read_endpoint_round_trips_with_its_filters
    """
    w = _one_populated_database(api)
    partner_headers = make_partner_manager_headers(w["partner"]["id"])
    courier_headers = make_courier_headers(w["courier"]["id"])

    jurisdiction = validate_success(api.get_jurisdiction(w["jurisdiction"]["id"], ADMIN_HEADERS))
    assert jurisdiction["code"] == "US-NY"
    assert jurisdiction["dry_status"] == "WET"
    assert jurisdiction["utc_offset_minutes"] == -240

    rows, meta = validate_paginated(
        api.list_jurisdictions(OFFICER_A_HEADERS, _page({"dry_status": "WET"}))
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["jurisdiction"]["id"]]

    customer = validate_success(api.get_customer(w["customer"]["id"], ADMIN_HEADERS))
    assert customer["attestation_state"] == "ATTESTED"
    assert customer["attested_dob"] == f.ADULT_DOB
    assert customer["latest_identity_check_result"] == "MATCH"
    assert customer["refusal_strikes"] == 0

    rows, meta = validate_paginated(
        api.list_customers(OFFICER_A_HEADERS, _page({"attestation_state": "ATTESTED"}))
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["customer"]["id"]]

    rows, meta = validate_paginated(
        api.list_identity_checks(w["customer"]["id"], ADMIN_HEADERS, _page({"status": "VALID"}))
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["identity_check"]["id"]]
    assert rows[0]["result"] == "MATCH"

    line = validate_success(api.get_order_line(w["line"]["id"], ADMIN_HEADERS))
    assert line["order_id"] == w["order"]["id"]
    assert line["product_id"] == w["hamper"]["id"]
    assert line["quantity"] == 1
    assert_cents(line["unit_price_cents"], 6800, "unit_price_cents")
    assert_cents(line["line_total_cents"], 6800, "line_total_cents")
    assert_units_equal(line["line_restricted_units"], 0.00, "line_restricted_units")

    rows, meta = validate_paginated(
        api.list_order_lines(ADMIN_HEADERS, _page({"order_id": w["order"]["id"]}))
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["line"]["id"]]

    partner = validate_success(api.get_delivery_partner(w["partner"]["id"], partner_headers))
    assert partner["contract_tier"] == "STANDARD"
    assert_partner_gate(
        partner,
        posture="OPEN",
        open_case_count=0,
        license_risk_score=15.00,
        lifetime_risk_score=15.00,
    )

    rows, meta = validate_paginated(
        api.list_delivery_partners(OFFICER_A_HEADERS, _page({"posture": "OPEN"}))
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["partner"]["id"]]

    rows, meta = validate_paginated(
        api.list_couriers(
            partner_headers,
            _page(
                {
                    "delivery_partner_id": w["partner"]["id"],
                    "certification_state": "CERTIFIED",
                }
            ),
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["courier"]["id"]]

    certification = validate_success(
        api.get_courier_certification(w["certification"]["id"], courier_headers)
    )
    assert certification["courier_id"] == w["courier"]["id"]
    assert certification["restriction_type"] == "ALCOHOL"
    assert certification["state"] == "ACTIVE"
    assert _instant(certification["issued_at"]) == _instant(CLOCK)
    assert _instant(certification["expires_at"]) == CERTIFICATION_HORIZON, (
        f"365 days after the issue instant; got {certification['expires_at']!r}"
    )

    rows, meta = validate_paginated(
        api.list_courier_certifications(w["courier"]["id"], partner_headers, _page({"state": "ACTIVE"}))
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["certification"]["id"]]

    rows, meta = validate_paginated(
        api.list_delivery_attempts(
            OFFICER_A_HEADERS,
            _page({"courier_id": w["courier"]["id"], "state": "INITIATED"}),
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["attempt"]["id"]]
    assert rows[0]["order_id"] == w["order"]["id"]

    rows, meta = validate_paginated(
        api.list_corrective_action_plans(
            w["case"]["id"], OFFICER_A_HEADERS, _page({"state": "SUBMITTED"})
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [w["plan"]["id"]]
    assert rows[0]["revision_round"] == 0, (
        f"a newly filed plan opens on round 0; got {rows[0]['revision_round']}"
    )

    plan = validate_success(api.get_corrective_action_plan(w["plan"]["id"], partner_headers))
    assert plan["violation_case_id"] == w["case"]["id"]
    assert_plan_state(plan, "SUBMITTED")
    assert plan["remediation_items"] == ["Seal every tote at the hub"]
    assert _instant(plan["due_at"]) == _instant(PLAN_DUE)
