"""Endpoints: the CRUD round trip, the bodyless action, the portfolio sweep and scope links."""
from test_helpers import (
    AM,
    CO,
    FA,
    ApiErrorId,
    api_client,
    assert_credit_line,
    assert_pagination_meta,
    create_credit_line_payload,
    create_dealer,
    list_unit_obligations,
    observation_payload,
    read_dealer,
    read_unit,
    register_unit,
    run_curtailment,
    schedule_audit,
    set_clock,
    setup_floored_unit,
    setup_pending_line,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}


def test_a_facility_round_trips_through_create_read_and_filtered_list():
    """The create echoes the commercial terms and seeds the money fields; the reads never mutate.

    PRD: "A freshly established line sits in `PENDING` with `activated_at` null, `suspension_reason_code` null, `available_credit_cents` equal to `credit_limit_cents`, and `outstanding_principal_cents`, `charged_off_principal_cents`, `eligible_collateral_cents`, `borrowing_base_deficiency_cents`, `class_outstanding_cents_used` and `class_outstanding_cents_demonstrator` all zero. Its `version` is 1."

    PRD: "`curtailment_grace_days` is optional, must lie between 0 and 30 inclusive, and when the payload omits it the line is created with a grace period of 10 days."

    Design: Corner/endpoints/credit_line_create_and_read_round_trip_on_the_standard_crud_pair
    """
    set_clock("2026-08-01T00:00:00Z")
    dealer = create_dealer(legal_name="Corner Round Trip Motors LLC", state_code="OK")
    payload = create_credit_line_payload(dealer["id"])
    del payload["curtailment_grace_days"]

    created = validate_success(api_client.create_credit_line(payload, CO), 201)
    assert_credit_line(created)
    assert created["status"] == "PENDING"
    assert created["available_credit_cents"] == 500000000
    assert created["curtailment_grace_days"] == 10
    assert created["version"] == 1
    assert created["credit_limit_cents"] == 500000000
    assert created["advance_rate_bps_new"] == 10000
    assert created["advance_rate_bps_used"] == 9000
    assert created["advance_rate_bps_demonstrator"] == 8500
    assert created["max_unit_advance_cents_new"] == 20000000
    assert created["class_sublimit_cents_used"] == 100000000
    assert created["class_sublimit_cents_demonstrator"] == 50000000
    assert created["outstanding_principal_cents"] == 0
    assert created["charged_off_principal_cents"] == 0
    assert created["class_outstanding_cents_used"] == 0
    assert created["class_outstanding_cents_demonstrator"] == 0
    assert created["eligible_collateral_cents"] == 0
    assert created["borrowing_base_deficiency_cents"] == 0
    assert created["activated_at"] is None
    assert created["suspension_reason_code"] is None

    read_back = validate_success(api_client.get_credit_line(created["id"], CO))
    assert read_back["id"] == created["id"]
    assert read_back["status"] == "PENDING"
    assert read_back["available_credit_cents"] == 500000000
    assert read_back["version"] == 1

    rows, meta = validate_paginated(
        api_client.list_credit_lines(CO, params={"dealer_id": dealer["id"]})
    )
    assert_pagination_meta(meta, limit=10, offset=0, total=1, has_more=False)
    assert [row["id"] for row in rows] == [created["id"]]


def test_the_activation_action_drives_the_transition_and_opens_the_registration_gate():
    """One bodyless call activates the line, promotes the dealership and anchors the first audit date.

    PRD: "Activation stamps `activated_at` from the logical clock, recomputes the capacity figures of §2.11, advances the line `PENDING → ACTIVE`, and cascades: the dealership moves `PROSPECT → ACTIVE` and its `next_audit_due_at` is set to `activated_at` plus its current `audit_frequency_days` — 180 days out for a brand-new `A`-rated dealer. Both the line's `version` and the dealer's `version` advance by 1."

    Design: Corner/endpoints/the_activate_action_endpoint_drives_its_transition_and_side_effects
    """
    ctx = setup_pending_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Action Motors LLC", "state_code": "UT"},
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    assert ctx["dealer"]["status"] == "PROSPECT"
    assert ctx["dealer"]["next_audit_due_at"] is None

    activated = validate_success(api_client.activate_credit_line(line_id, CO))
    assert activated["status"] == "ACTIVE"
    assert str(activated["activated_at"]).startswith("2026-08-01T00:00:00")
    assert activated["version"] == 2
    assert activated["available_credit_cents"] == 500000000
    assert activated["suspension_reason_code"] is None

    dealer = read_dealer(dealer_id)
    assert dealer["status"] == "ACTIVE"
    assert str(dealer["next_audit_due_at"]).startswith("2027-01-28T00:00:00")
    assert dealer["audit_frequency_days"] == 180
    assert dealer["version"] == 2

    unit = register_unit(
        dealer_id,
        line_id,
        "CRNACTIONUNIT001",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
    )
    assert unit["funding_status"] == "REGISTERED"


def test_a_sweep_without_a_dealer_filter_walks_every_eligible_dealership():
    """Two dealerships each mature one 300,000 cent rung, and the run reports the two sums separately added.

    PRD: "The checkpoint accepts an optional `dealer_id`, which restricts the sweep to a single dealership, and an optional `as_of_date`, which supplies the effective run date in place of the logical clock. Dealerships whose `status` is `ACTIVE` or `SUSPENDED` participate; a `PROSPECT`, `DEFAULTED` or `TERMINATED` dealership is skipped entirely."

    PRD: "`total_required_paydown_cents` is the sum of `required_principal_cents` across the obligations that matured to `DUE` in this sweep, and **the rounding order here is pinned**: round each obligation's requirement individually first, then add the already-rounded integers."

    Design: Corner/endpoints/a_curtailment_run_without_dealer_id_processes_every_eligible_dealer
    """
    first = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNPORTFOLIOUN01",
        unit_overrides={"invoice_amount_cents": 3000000},
        dealer_overrides={"legal_name": "Corner Portfolio One LLC", "state_code": "ID"},
    )
    second = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNPORTFOLIOUN02",
        unit_overrides={"invoice_amount_cents": 3000000},
        dealer_overrides={"legal_name": "Corner Portfolio Two LLC", "state_code": "ID"},
    )

    set_clock("2026-10-30T00:00:00Z")
    summary = run_curtailment()
    assert summary["obligations_marked_due_count"] == 2
    assert summary["total_required_paydown_cents"] == 600000
    assert summary["obligations_marked_delinquent_count"] == 0
    assert summary["units_flagged_delinquent_count"] == 0
    assert str(summary["run_completed_at"]).startswith("2026-10-30T00:00:00")
    assert sorted(summary["dealer_ids_processed"]) == sorted(
        [first["dealer"]["id"], second["dealer"]["id"]]
    )

    for ctx in (first, second):
        obligations = list_unit_obligations(ctx["unit"]["id"])
        assert len(obligations) == 1
        assert obligations[0]["status"] == "DUE"
        assert obligations[0]["required_principal_cents"] == 300000
        assert read_unit(ctx["unit"]["id"])["funding_status"] == "FLOORED"
        assert read_dealer(ctx["dealer"]["id"])["delinquent_unit_count"] == 0


def test_a_unit_belonging_to_another_dealership_can_never_be_counted():
    """The audit froze one dealership's lot, so a sibling dealership's floored unit is out of scope.

    PRD: "The named unit must belong to the audit's dealership and must have been inside the frozen scope at start time; otherwise the reading is refused with `ERR_UNIT_NOT_IN_AUDIT_SCOPE`."

    Design: Corner/endpoints/an_observation_for_a_unit_outside_the_audit_scope_is_refused
    """
    inside = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNINSCOPEUNIT01",
        unit_overrides={"invoice_amount_cents": 3000000},
        dealer_overrides={"legal_name": "Corner In Scope Motors LLC", "state_code": "NV"},
    )
    outside = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNOUTSCOPEUNT01",
        unit_overrides={"invoice_amount_cents": 3000000},
        dealer_overrides={"legal_name": "Corner Out Scope Motors LLC", "state_code": "NV"},
    )

    audit = schedule_audit(
        inside["dealer"]["id"], "2026-08-01", "2026-08-03", audit_type="UNANNOUNCED"
    )
    opened = start_audit(audit["id"])
    assert opened["units_in_scope_count"] == 1

    validate_error(
        api_client.record_observation(
            audit["id"], observation_payload(outside["unit"]["id"], "PRESENT", True), FA
        ),
        ApiErrorId.ERR_UNIT_NOT_IN_AUDIT_SCOPE,
        422,
    )

    _, observation_meta = validate_paginated(
        api_client.list_audit_observations(audit["id"], CO)
    )
    assert observation_meta["total_count"] == 0
    unchanged = validate_success(api_client.get_audit(audit["id"], AM))
    assert unchanged["units_verified_count"] == 0
    assert unchanged["units_exception_count"] == 0
    assert unchanged["units_unobserved_count"] == 1

    _, history_meta = validate_paginated(
        api_client.list_unit_audit_observations(outside["unit"]["id"], CO)
    )
    assert history_meta["total_count"] == 0

    accepted = validate_success(
        api_client.record_observation(
            audit["id"], observation_payload(inside["unit"]["id"], "PRESENT", True), FA
        ),
        201,
    )
    assert accepted["classification"] == "VERIFIED"
