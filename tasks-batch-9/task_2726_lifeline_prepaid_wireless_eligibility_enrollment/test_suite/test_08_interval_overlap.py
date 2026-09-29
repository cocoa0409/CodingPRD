"""Two opposite interval conventions: the half-open household slot and the closed reissue freeze."""

from test_helpers import (
    ApiErrorId,
    assert_device,
    assert_instant,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

PRIOR_START = "2026-05-01T00:00:00Z"
PRIOR_END = "2026-09-01T00:00:00Z"
ONE_MS_BEFORE_END = "2026-08-31T23:59:59.999Z"

FIRST_ISSUE_INSTANT = "2026-06-05T00:00:00Z"
FREEZE_BOUNDARY = "2027-07-05T00:00:00Z"
JUST_INSIDE_FREEZE = "2027-07-04T23:59:59.999Z"
JUST_PAST_FREEZE = "2027-07-05T00:00:00.001Z"


def _dwelling_with_one_closed_off_interval(api):
    """A dwelling whose single slot has already been consumed for 2026-05-01 to 2026-09-01."""
    fx.set_clock(api, PRIOR_START)
    provider = fx.register_provider(api)
    dwelling = fx.register_distinct_address(api, 1)
    first = fx.eligible_applicant(api, dwelling["id"])
    prior = fx.enroll(
        api,
        provider,
        first["subscriber"],
        first["check"],
        dwelling,
        service_type="VOICE",
        benefit_start_date=PRIOR_START,
    )

    fx.set_clock(api, PRIOR_END)
    ended = fx.de_enroll(
        api,
        prior["id"],
        reason="SUBSCRIBER_REQUEST",
        headers=fx.provider_headers(provider),
    )
    assert_instant(ended["benefit_end_date"], PRIOR_END, "benefit_end_date")

    successor = fx.eligible_applicant(api, dwelling["id"])
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "dwelling": dwelling,
        "prior": prior,
        "successor": successor,
    }


def test_a_start_one_millisecond_inside_the_closed_interval_is_refused(api):
    """The vacated interval is still occupied up to, but not including, its end.

    PRD: "Against a prior benefit occupying `2026-05-01T00:00:00Z` to
    `2026-09-01T00:00:00Z` at a dwelling with one permitted slot, a `benefit_start_date` of
    `2026-09-01T00:00:00Z` is accepted and a `benefit_start_date` of
    `2026-08-31T23:59:59.999Z` is refused; and against a prior benefit that is still being
    drawn, with a null `benefit_end_date`, every candidate start is refused."

    Design: Difficulty/resource_temporal_overlap/household_benefit_slot_half_open_interval_admits_adjacent_start
    """
    context = _dwelling_with_one_closed_off_interval(api)
    dwelling = fx.refresh_address(api, context["dwelling"]["id"])
    assert dwelling["max_permitted_benefit_slots"] == 1
    assert dwelling["occupied_benefit_slots"] == 0, (
        "the slot figure counts only benefits currently being drawn"
    )

    response = api.create_enrollment(
        f.enrollment_payload(
            subscriber_id=context["successor"]["subscriber"]["id"],
            provider_id=context["provider"]["id"],
            eligibility_check_id=context["successor"]["check"]["id"],
            certified_address_id=context["dwelling"]["id"],
            benefit_start_date=ONE_MS_BEFORE_END,
        ),
        context["agent"],
    )
    validate_error(response, ApiErrorId.ONE_PER_HOUSEHOLD_VIOLATION.value, 409)

    assert fx.refresh_address(api, context["dwelling"]["id"])["occupied_benefit_slots"] == 0
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 0
    assert (
        fx.refresh_subscriber(api, context["successor"]["subscriber"]["id"])["status"]
        == "VERIFIED_ELIGIBLE"
    )


def test_a_start_at_exactly_the_prior_end_instant_is_admitted(api):
    """Adjacency is permitted because the occupancy interval is open at its end.

    PRD: "**A household's benefit occupancy interval** is half-open, closed at its start and
    open at its end, so adjacency is permitted: a new benefit starting at exactly the instant
    a prior benefit ended does not overlap it."

    Design: Difficulty/resource_temporal_overlap/household_benefit_slot_half_open_interval_admits_adjacent_start
    """
    context = _dwelling_with_one_closed_off_interval(api)

    admitted = validate_success(
        api.create_enrollment(
            f.enrollment_payload(
                subscriber_id=context["successor"]["subscriber"]["id"],
                provider_id=context["provider"]["id"],
                eligibility_check_id=context["successor"]["check"]["id"],
                certified_address_id=context["dwelling"]["id"],
                benefit_start_date=PRIOR_END,
            ),
            context["agent"],
        ),
        201,
    )
    assert admitted["benefit_status"] == "ACTIVE"
    assert_instant(admitted["benefit_start_date"], PRIOR_END, "benefit_start_date")
    assert_instant(
        admitted["port_freeze_until"], "2026-10-31T00:00:00Z", "port_freeze_until"
    )

    assert fx.refresh_address(api, context["dwelling"]["id"])["occupied_benefit_slots"] == 1
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 1
    assert (
        fx.refresh_enrollment(api, context["prior"]["id"])["benefit_status"] == "DE_ENROLLED"
    ), "the earlier benefit is untouched by its successor"


def _benefit_that_returned_its_handset_in_good_condition(api):
    """A benefit whose only handset was issued at 2026-06-05 and returned GOOD the next day."""
    fx.set_clock(api, FIRST_ISSUE_INSTANT)
    provider = fx.register_provider(api)
    basic, standard = fx.stock_devices(api, provider, [("BASIC", 2100), ("STANDARD", 1200)])
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    enrollment = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=FIRST_ISSUE_INSTANT,
    )
    fx.issue_device(api, enrollment["id"], provider)
    issued = fx.refresh_enrollment(api, enrollment["id"])
    assert_instant(
        issued["last_device_issued_at"], FIRST_ISSUE_INSTANT, "last_device_issued_at"
    )

    fx.set_clock(api, "2026-06-06T00:00:00Z")
    fx.return_device(api, basic["id"], return_condition="GOOD")
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "basic": basic,
        "standard": standard,
        "enrollment": enrollment,
    }


def test_the_reissue_freeze_is_closed_at_its_upper_boundary_instant(api):
    """A request at exactly last_device_issued_at plus 395 days is still refused.

    PRD: "With `last_device_issued_at` at `2026-06-05T00:00:00Z` the boundary is
    `2027-07-05T00:00:00Z`: a request at `2027-07-04T23:59:59.999Z` is refused, a request at
    exactly `2027-07-05T00:00:00Z` is also refused, and a request at
    `2027-07-05T00:00:00.001Z` succeeds."

    Design: Difficulty/resource_temporal_overlap/device_reissue_closed_interval_rejects_exact_boundary_instant
    """
    context = _benefit_that_returned_its_handset_in_good_condition(api)
    assert fx.refresh_device(api, context["basic"]["id"])["status"] == "IN_STOCK", (
        "a GOOD return re-enters stock without waiving the freeze"
    )

    for instant in (JUST_INSIDE_FREEZE, FREEZE_BOUNDARY):
        fx.set_clock(api, instant)
        response = api.issue_device(
            context["enrollment"]["id"], f.device_issuance_payload(), context["agent"]
        )
        validate_error(response, ApiErrorId.DEVICE_FREEZE_ACTIVE.value, 409)

    frozen = fx.refresh_enrollment(api, context["enrollment"]["id"])
    assert frozen["device_status"] == "AWAITING_DEVICE"
    assert frozen["device_issuance_count"] == 1, "no second handset was issued"
    assert_instant(
        frozen["last_device_issued_at"], FIRST_ISSUE_INSTANT, "last_device_issued_at"
    )


def test_one_millisecond_past_the_boundary_reissues_the_ranked_handset(api):
    """The first acceptable instant issues rank one of the pool, tier before cost.

    PRD: "Otherwise the pool is ranked by `model_tier` ascending along the fixed ladder
    `BASIC`, then `STANDARD`, then `SMART`; ties broken by `unit_cost_cents` ascending; and
    remaining ties broken by `created_at` ascending as the final key."

    Design: Difficulty/resource_temporal_overlap/device_reissue_closed_interval_rejects_exact_boundary_instant
    """
    context = _benefit_that_returned_its_handset_in_good_condition(api)

    fx.set_clock(api, JUST_PAST_FREEZE)
    validate_success(
        api.issue_device(
            context["enrollment"]["id"], f.device_issuance_payload(), context["agent"]
        )
    )
    reissued = fx.refresh_enrollment(api, context["enrollment"]["id"])
    assert reissued["device_status"] == "DEVICE_ISSUED"
    assert reissued["device_issuance_count"] == 2, (
        f"the count is every handset ever issued, got {reissued['device_issuance_count']}"
    )
    assert_instant(
        reissued["last_device_issued_at"], JUST_PAST_FREEZE, "last_device_issued_at"
    )
    assert reissued["audit_risk_score"] == 20, (
        f"two handsets at 10 each, capped at two, got {reissued['audit_risk_score']}"
    )

    chosen = fx.refresh_device(api, context["basic"]["id"])
    assert_device(chosen)
    assert chosen["status"] == "ISSUED", (
        "the 2100-cent BASIC handset outranks the cheaper STANDARD one"
    )
    assert chosen["issued_enrollment_id"] == context["enrollment"]["id"]
    assert_instant(chosen["issued_at"], JUST_PAST_FREEZE, "issued_at")
    assert fx.refresh_device(api, context["standard"]["id"])["status"] == "IN_STOCK", (
        "the STANDARD handset was never selected"
    )

    carrier = fx.refresh_provider(api, context["provider"]["id"])
    assert carrier["devices_total_count"] == 2, "issuance does not create hardware"
    assert carrier["devices_in_stock_count"] == 1
    assert carrier["devices_issued_count"] == 1
