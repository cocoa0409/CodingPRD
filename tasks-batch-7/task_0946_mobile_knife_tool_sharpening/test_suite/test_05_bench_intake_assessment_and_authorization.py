"""Bench intake, the technician's verdict, re-authorization and the decline path."""
from test_helpers import (
    ApiErrorId, ADMIN,
    api_client, assess_item, build_config, make_account_owner_headers,
    make_technician_headers, read_bench_day, read_item, read_request,
    route_to_bench, route_to_van, stage_request, validate_error, validate_success,
    assert_request_item,
)


def _bench_world(item_class="CHEF_KNIFE", declared="ROUTINE_HONE", certs=None,
                 spec_overrides=None, bench_kwargs=None, account_kwargs=None):
    world = build_config(specs=(item_class,), spec_overrides=spec_overrides,
                         tech_certs=certs, bench_kwargs=bench_kwargs,
                         account_kwargs=account_kwargs)
    request, items = stage_request(world, [(item_class, declared)])
    route_to_bench(world, request["id"])
    return world, read_request(request["id"]), read_item(items[0]["id"])


def test_bench_capacity_refuses_an_intake_that_overshoots_the_day_budget():
    """PRD 3.7: "Capacity is then tested: the bench day's `booked_minutes` plus the sum of
    the incoming request's declared minutes must be at most its `bench_minute_budget`, with
    equality passing. A breach is `ERR_BENCH_CAPACITY_EXCEEDED`."
    PRD 2.6 rung 54: "The bench day's `booked_minutes` plus the incoming request's declared
    minutes is at most its `bench_minute_budget`; equality passes. Otherwise
    `ERR_BENCH_CAPACITY_EXCEEDED` (409). Applies to bench intake; pre-empts rungs 55–57."

    Design: Corner/validations/bench_capacity_exceeded_when_the_day_budget_is_too_small
    """
    world = build_config(bench_kwargs={"bench_date": "2026-05-01", "bench_minute_budget": 5})
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    route_to_van(world, request["id"])

    response = api_client.bench_intake_service_request(
        request["id"], {"bench_day_id": world["bench"]["id"]},
        make_technician_headers(world["tech"]["id"]))
    validate_error(response, ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED.value, 409)

    assert read_bench_day(world["bench"]["id"])["booked_minutes"] == 0
    item = read_item(items[0]["id"])
    assert item["custody_location"] == "VAN"
    assert item["bench_day_id"] is None


def test_bench_intake_onto_the_wrong_bench_day_is_refused_before_the_capacity_rung():
    """PRD 3.7: "The named bench day's `bench_date` must equal the logical clock's date, or
    the intake is `ERR_BENCH_DAY_DATE_MISMATCH`; that check sits above the capacity check so
    that a technician booking onto the wrong day is told so rather than being told the day is
    full."
    PRD 2.6 rung 20: "The `BenchDay` named by `bench_day_id` has a `bench_date` equal to the
    logical clock's date. Otherwise `ERR_BENCH_DAY_DATE_MISMATCH` (409)."

    Design: Corner/validations/bench_intake_on_the_wrong_bench_day_is_refused
    """
    world = build_config(bench_kwargs={"bench_date": "2026-05-02", "bench_minute_budget": 480})
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    route_to_van(world, request["id"])

    response = api_client.bench_intake_service_request(
        request["id"], {"bench_day_id": world["bench"]["id"]},
        make_technician_headers(world["tech"]["id"]))
    error = validate_error(response, ApiErrorId.ERR_BENCH_DAY_DATE_MISMATCH.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED.value
    assert read_item(items[0]["id"])["custody_location"] == "VAN"


def test_uncertified_technician_cannot_assess_a_salon_shear():
    """PRD 3.7: "the acting technician's `certifications` must contain the spec's
    `required_certification` unless that requirement is `NONE` — a gap there is
    `ERR_CERTIFICATION_MISSING`."
    PRD 2.6 rung 22: "The acting technician's `certifications` contain the
    `required_certification` of the item's `ItemClassSpec`, unless that requirement is `NONE`.
    Otherwise `ERR_CERTIFICATION_MISSING` (422). Applies to assessment and start-work;
    pre-empts rungs 23–57."

    Design: Corner/validations/uncertified_technician_cannot_assess_a_salon_shear
    """
    world, _request, item = _bench_world(
        item_class="SALON_SHEAR", certs=[],
        account_kwargs={"name": "Shear Bliss Salon", "account_type": "SALON",
                        "contact_email": "front@shearbliss.test"})

    response = api_client.assess_request_item(
        item["id"], {"assessed_damage_tier": "ROUTINE_HONE"},
        make_technician_headers(world["tech"]["id"]))
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_MISSING.value, 422)

    reread = read_item(item["id"])
    assert reread["custody_location"] == "BENCH"
    assert reread["service_status"] == "INTAKE_PENDING"
    assert read_bench_day(world["bench"]["id"])["booked_minutes"] == 18


def test_declining_a_repriced_line_returns_it_unserviced_and_frees_bench_minutes():
    """PRD 3.7: "**Declining** is heavier: it moves `authorization_status` `PENDING →
    DECLINED` and `service_status` `ASSESSED → RETURNED_UNSERVICED`, zeroes both
    `charged_service_cents` and `part_fee_cents`, releases the item's minutes from the bench
    day's `booked_minutes`, and — when that item had already consumed a subscription allowance
    unit — appends an allowance ledger entry of kind `RESTORED` with `quantity` 1 and a
    `reason` naming the decline, raising `allowance_remaining` by exactly one."
    PRD 3.7: "the delta must be strictly greater than 1000 cents in absolute terms, and the
    delta must also be strictly greater than 25 percent of the quoted gross."

    Design: Corner/state_machines/declining_a_repriced_line_returns_it_unserviced_and_frees_bench_minutes
    """
    world, _request, item = _bench_world(
        item_class="MANDOLINE_BLADE", certs=["SLICER"],
        spec_overrides={"MANDOLINE_BLADE": {"list_price_cents": 1668}},
        account_kwargs={"name": "Deli Row", "account_type": "COMMERCIAL",
                        "contact_email": "ops@delirow.test"})
    assessed = assess_item(item["id"], "CHIP_REPAIR", world["tech"]["id"])
    assert assessed["requires_reauthorization"] is True

    declined = validate_success(api_client.decline_request_item(
        item["id"], make_account_owner_headers(world["account"]["id"])))
    assert_request_item(declined)
    assert declined["quoted_gross_cents"] == 1668
    assert declined["final_gross_cents"] == 2669
    assert declined["requires_reauthorization"] is True
    assert declined["authorization_status"] == "DECLINED"
    assert declined["service_status"] == "RETURNED_UNSERVICED"
    assert declined["charged_service_cents"] == 0
    assert declined["part_fee_cents"] == 0
    assert read_bench_day(world["bench"]["id"])["booked_minutes"] == 0


def test_start_work_is_refused_while_authorization_is_pending_and_allowed_after_it():
    """PRD 3.7: "A `PENDING` item is frozen. Starting work requires `authorization_status` to
    be `NOT_REQUIRED` or `AUTHORIZED`, and a `PENDING` or `DECLINED` item refuses with
    `ERR_AUTHORIZATION_REQUIRED`."
    PRD 3.7: "**Authorizing** moves `authorization_status` `PENDING → AUTHORIZED` and nothing
    else."
    PRD 3.7: "Starting work moves `service_status` `ASSESSED → IN_WORK` and requires the item
    to be in `BENCH` custody, to be authorized, and the acting technician to hold the required
    certification — the same certification test as assessment, checked again because a
    different technician may pick the blade up."

    Design: Corner/state_machines/starting_work_on_a_pending_authorization_line_is_refused
    """
    world, _request, item = _bench_world(
        item_class="MANDOLINE_BLADE", certs=["SLICER"],
        spec_overrides={"MANDOLINE_BLADE": {"list_price_cents": 1668}},
        account_kwargs={"name": "Deli Row", "account_type": "COMMERCIAL",
                        "contact_email": "ops@delirow.test"})
    assess_item(item["id"], "CHIP_REPAIR", world["tech"]["id"])
    technician = make_technician_headers(world["tech"]["id"])

    blocked = api_client.start_work_request_item(item["id"], technician)
    validate_error(blocked, ApiErrorId.ERR_AUTHORIZATION_REQUIRED.value, 409)

    authorized = validate_success(api_client.authorize_request_item(
        item["id"], make_account_owner_headers(world["account"]["id"])))
    assert authorized["authorization_status"] == "AUTHORIZED"

    started = validate_success(api_client.start_work_request_item(item["id"], technician))
    assert started["service_status"] == "IN_WORK"
    assert read_bench_day(world["bench"]["id"])["booked_minutes"] == 15


def test_assessment_reprices_the_item_under_the_assessed_damage_tier():
    """PRD 3.3: "The assessed minutes, stored in `service_minutes_assessed`, are the spec's
    `base_service_minutes` plus the minutes supplement of the `assessed_damage_tier`; the
    assessed gross, stored in `final_gross_cents`, is `list_price_cents` multiplied by that
    tier's price multiplier, rounded half up."
    PRD 3.3: "Its **price multiplier** is 1.00, 1.60, 2.25 and 3.00 respectively. Its
    **minutes supplement** is 0, 6, 12 and 20 minutes respectively."

    Design: Difficulty/dual_variant_calc/item_price_quoted_vs_final_on_damage_tier_reassessment
    """
    world, _request, item = _bench_world()

    assessed = assess_item(item["id"], "CHIP_REPAIR", world["tech"]["id"])
    assert assessed["quoted_gross_cents"] == 900
    assert assessed["final_gross_cents"] == 1440
    assert assessed["service_minutes_declared"] == 6
    assert assessed["service_minutes_assessed"] == 12


def test_assessment_sets_the_parts_fee_of_the_assessed_tier_and_leaves_authorization_alone():
    """PRD 3.7: "On success the item records `assessed_damage_tier` and
    `assessed_by_technician_id`, recomputes `service_minutes_assessed`, recomputes
    `final_gross_cents` under the assessed flavour and `part_fee_cents` as the parts fee of
    the assessed tier, moves `service_status` `INTAKE_PENDING → ASSESSED`, and adjusts the
    bench day's `booked_minutes` by the difference between the assessed minutes and the
    declared minutes — which can be negative when the blade turned out to be in better shape
    than the customer thought."
    PRD 3.3: "And its **parts fee** is 0, 0, 400 and 900 cents respectively — only re-tipping
    and handle work consume parts, and the parts fee is a separate, non-taxable amount that is
    never folded into the service price."

    Design: Difficulty/dual_variant_calc/item_price_quoted_vs_final_on_damage_tier_reassessment
    """
    world, _request, item = _bench_world()

    assessed = assess_item(item["id"], "CHIP_REPAIR", world["tech"]["id"])
    assert assessed["part_fee_cents"] == 0
    assert assessed["requires_reauthorization"] is False
    assert assessed["authorization_status"] == "NOT_REQUIRED"
    assert assessed["service_status"] == "ASSESSED"
    assert assessed["assessed_by_technician_id"] == world["tech"]["id"]
    assert read_bench_day(world["bench"]["id"])["booked_minutes"] == 12


def test_custody_rung_pre_empts_the_certification_rung_on_assessment():
    """PRD 2.6 rung 19: "Every `RequestItem` involved is in the `custody_location` the
    operation requires: `VAN` or `LOCKER` for bench intake, `BENCH` for assessment and
    start-work, `LOCKER` for locker release and locker abandonment. Otherwise
    `ERR_ITEM_NOT_IN_CUSTODY` (409). Applies to bench intake, assessment, start-work, locker
    release and locker abandonment; pre-empts rungs 20–57."
    PRD 2.6 rung 22: "The acting technician's `certifications` contain the
    `required_certification` of the item's `ItemClassSpec`, unless that requirement is `NONE`.
    Otherwise `ERR_CERTIFICATION_MISSING` (422)."

    Design: Difficulty/priority_pair_validation_conflict/item_not_in_custody_beats_certification_missing_on_assess
    """
    world = build_config(specs=("SALON_SHEAR",), tech_certs=[], with_bench=False,
                         account_kwargs={"name": "Shear Bliss Salon", "account_type": "SALON",
                                         "contact_email": "front@shearbliss.test"})
    request, items = stage_request(world, [("SALON_SHEAR", "ROUTINE_HONE")])
    route_to_van(world, request["id"])

    response = api_client.assess_request_item(
        items[0]["id"], {"assessed_damage_tier": "ROUTINE_HONE"},
        make_technician_headers(world["tech"]["id"]))
    error = validate_error(response, ApiErrorId.ERR_ITEM_NOT_IN_CUSTODY.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_CERTIFICATION_MISSING.value


def test_assessment_refused_in_van_custody_leaves_the_item_unassessed():
    """PRD 2.6 rung 19: "Every `RequestItem` involved is in the `custody_location` the
    operation requires: `VAN` or `LOCKER` for bench intake, `BENCH` for assessment and
    start-work, `LOCKER` for locker release and locker abandonment. Otherwise
    `ERR_ITEM_NOT_IN_CUSTODY` (409)."
    PRD 3.3: "Every item opens with `service_status` `INTAKE_PENDING`, `custody_location`
    `CUSTOMER`, `authorization_status` `NOT_REQUIRED`, `allowance_applied` false,
    `requires_reauthorization` false, and null values for `bench_day_id`,
    `rework_of_request_item_id`, `assessed_by_technician_id`, `assessed_damage_tier`,
    `service_minutes_assessed` and `delivered_at`."

    Design: Difficulty/priority_pair_validation_conflict/item_not_in_custody_beats_certification_missing_on_assess
    """
    world = build_config(specs=("SALON_SHEAR",), tech_certs=[], with_bench=False,
                         account_kwargs={"name": "Shear Bliss Salon", "account_type": "SALON",
                                         "contact_email": "front@shearbliss.test"})
    request, items = stage_request(world, [("SALON_SHEAR", "ROUTINE_HONE")])
    route_to_van(world, request["id"])
    api_client.assess_request_item(
        items[0]["id"], {"assessed_damage_tier": "ROUTINE_HONE"},
        make_technician_headers(world["tech"]["id"]))

    reread = read_item(items[0]["id"])
    assert reread["custody_location"] == "VAN"
    assert reread["service_status"] == "INTAKE_PENDING"
    assert reread["assessed_damage_tier"] is None


def test_reauthorization_does_not_trip_when_the_delta_ties_the_absolute_threshold():
    """PRD 3.7: "The system computes the delta between `final_gross_cents` and
    `quoted_gross_cents` and sets `requires_reauthorization` true only when the increase clears
    *both* of two thresholds: the delta must be strictly greater than 1000 cents in absolute
    terms, and the delta must also be strictly greater than 25 percent of the quoted gross."
    PRD 3.7: "Both comparisons are strict: a delta that merely ties either threshold does not
    trip the rule. When `requires_reauthorization` comes out true the item's
    `authorization_status` is set to `PENDING`; otherwise it stays `NOT_REQUIRED`."

    Design: Difficulty/boundary_precision_check/reauthorization_delta_exactly_at_absolute_threshold_does_not_trip
    """
    world, _request, item = _bench_world(
        item_class="MANDOLINE_BLADE", certs=["SLICER"],
        account_kwargs={"name": "Deli Row", "account_type": "COMMERCIAL",
                        "contact_email": "ops@delirow.test"})

    assessed = assess_item(item["id"], "CHIP_REPAIR", world["tech"]["id"])
    assert assessed["quoted_gross_cents"] == 1666
    assert assessed["final_gross_cents"] == 2666
    assert assessed["requires_reauthorization"] is False
    assert assessed["authorization_status"] == "NOT_REQUIRED"


def test_threshold_assessment_still_reprices_minutes_and_rebooks_the_bench_day():
    """PRD 3.3: "The assessed minutes, stored in `service_minutes_assessed`, are the spec's
    `base_service_minutes` plus the minutes supplement of the `assessed_damage_tier`; the
    assessed gross, stored in `final_gross_cents`, is `list_price_cents` multiplied by that
    tier's price multiplier, rounded half up."
    PRD 3.7: "`booked_minutes` is always, at any instant, the sum over every item whose
    `bench_day_id` names that day *and* whose `custody_location` is currently `BENCH` of that
    item's `service_minutes_assessed` when it is set and `service_minutes_declared` otherwise."

    Design: Difficulty/boundary_precision_check/reauthorization_delta_exactly_at_absolute_threshold_does_not_trip
    """
    world, _request, item = _bench_world(
        item_class="MANDOLINE_BLADE", certs=["SLICER"],
        account_kwargs={"name": "Deli Row", "account_type": "COMMERCIAL",
                        "contact_email": "ops@delirow.test"})

    assessed = assess_item(item["id"], "CHIP_REPAIR", world["tech"]["id"])
    assert assessed["service_minutes_declared"] == 9
    assert assessed["service_minutes_assessed"] == 15
    assert read_bench_day(world["bench"]["id"])["booked_minutes"] == 15


def test_assessment_is_refused_while_the_parent_request_is_still_draft():
    """PRD 2.6 rung 16: "The parent `ServiceRequest` is in a status that permits the item
    operation: `DRAFT` for item addition, and `IN_SERVICE` for assessment, start-work,
    complete-work and decline. Otherwise `ERR_REQUEST_NOT_MUTABLE` (409). Applies to item
    addition and to every per-item action endpoint; pre-empts rungs 17–57."

    Design: Difficulty/cross_entity_state_dependency/assess_blocked_because_parent_request_is_still_draft
    """
    world = build_config(with_bench=False, with_van=False)
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")], submit=False)

    response = api_client.assess_request_item(
        items[0]["id"], {"assessed_damage_tier": "CHIP_REPAIR"},
        make_technician_headers(world["tech"]["id"]))
    validate_error(response, ApiErrorId.ERR_REQUEST_NOT_MUTABLE.value, 409)
    assert read_request(request["id"])["status"] == "DRAFT"


def test_assessment_refused_on_a_draft_request_leaves_the_item_pricing_untouched():
    """PRD 2.6 rung 16: "The parent `ServiceRequest` is in a status that permits the item
    operation: `DRAFT` for item addition, and `IN_SERVICE` for assessment, start-work,
    complete-work and decline. Otherwise `ERR_REQUEST_NOT_MUTABLE` (409)."
    PRD 3.3: "`final_gross_cents` is set to the same value at creation and stays equal to
    `quoted_gross_cents` until an assessment replaces it."

    Design: Difficulty/cross_entity_state_dependency/assess_blocked_because_parent_request_is_still_draft
    """
    world = build_config(with_bench=False, with_van=False)
    _request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")], submit=False)
    api_client.assess_request_item(
        items[0]["id"], {"assessed_damage_tier": "CHIP_REPAIR"},
        make_technician_headers(world["tech"]["id"]))

    reread = validate_success(api_client.get_request_item(items[0]["id"], ADMIN))
    assert reread["service_status"] == "INTAKE_PENDING"
    assert reread["final_gross_cents"] == 900
    assert reread["assessed_damage_tier"] is None
