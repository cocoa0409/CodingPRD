"""Three stated precedences, each proved with a dual violation and a single-violation control."""

from test_helpers import (
    ApiErrorId,
    assert_instant,
    assert_instant_null,
    factories as f,
    fixtures as fx,
    validate_error,
)


def _lapsed_and_fresh_certifications_at_an_unlicensed_carrier(api):
    """A carrier licensed only in NM, one lapsed TX certification and one fresh one."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    provider = fx.register_provider(api, licensed_state_codes=["NM"])

    lapsed_address = fx.register_distinct_address(api, 1)
    lapsed = fx.eligible_applicant(api, lapsed_address["id"])

    fx.set_clock(api, "2026-10-30T00:00:00.001Z")
    fresh_address = fx.register_distinct_address(api, 2)
    fresh = fx.eligible_applicant(api, fresh_address["id"])
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "lapsed_address": lapsed_address,
        "lapsed": lapsed,
        "fresh_address": fresh_address,
        "fresh": fresh,
    }


def test_lapsed_certification_outranks_the_unlicensed_state_constraint(api):
    """One request trips both the expiry check and the licensing check; expiry wins.

    PRD: "A request to enroll a subscriber whose eligibility certification has lapsed **and**
    whose carrier is not licensed in the address's state reports
    `ERR_ELIGIBILITY_CHECK_EXPIRED`, not `ERR_PROVIDER_NOT_LICENSED_IN_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/expired_check_state_error_outranks_unlicensed_state_business_constraint
    """
    context = _lapsed_and_fresh_certifications_at_an_unlicensed_carrier(api)
    check = fx.refresh_eligibility_check(api, context["lapsed"]["check"]["id"])
    assert_instant(check["expires_at"], "2026-10-30T00:00:00Z", "expires_at")
    assert check["status"] == "ELIGIBLE_CONFIRMED", (
        "the certification is still confirmed; only the clock has moved past it"
    )

    response = api.create_enrollment(
        f.enrollment_payload(
            subscriber_id=context["lapsed"]["subscriber"]["id"],
            provider_id=context["provider"]["id"],
            eligibility_check_id=check["id"],
            certified_address_id=context["lapsed_address"]["id"],
        ),
        context["agent"],
    )
    validate_error(response, ApiErrorId.ELIGIBILITY_CHECK_EXPIRED.value, 409)

    carrier = fx.refresh_provider(api, context["provider"]["id"])
    assert carrier["active_enrollment_count"] == 0, "the refused request created nothing"
    dwelling = fx.refresh_address(api, context["lapsed_address"]["id"])
    assert dwelling["occupied_benefit_slots"] == 0
    applicant = fx.refresh_subscriber(api, context["lapsed"]["subscriber"]["id"])
    assert applicant["status"] == "VERIFIED_ELIGIBLE", "the applicant posture is untouched"


def test_the_licensing_constraint_is_live_when_the_certification_is_fresh(api):
    """The control: the same carrier and the same state, but an unexpired certification.

    PRD: "The certification-validity check outranks every business check on enrollment
    creation."

    Design: Difficulty/priority_pair_validation_conflict/expired_check_state_error_outranks_unlicensed_state_business_constraint
    """
    context = _lapsed_and_fresh_certifications_at_an_unlicensed_carrier(api)

    response = api.create_enrollment(
        f.enrollment_payload(
            subscriber_id=context["fresh"]["subscriber"]["id"],
            provider_id=context["provider"]["id"],
            eligibility_check_id=context["fresh"]["check"]["id"],
            certified_address_id=context["fresh_address"]["id"],
        ),
        context["agent"],
    )
    validate_error(response, ApiErrorId.PROVIDER_NOT_LICENSED_IN_STATE.value, 409)

    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 0
    assert fx.refresh_address(api, context["fresh_address"]["id"])["occupied_benefit_slots"] == 0


def _saturated_carrier_with_an_occupied_dwelling(api):
    """A carrier capped at one benefit, one occupied dwelling and two waiting applicants."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    provider = fx.register_provider(api, enrollment_cap=1)

    dwelling = fx.register_distinct_address(api, 1)
    first = fx.eligible_applicant(api, dwelling["id"])
    enrollment = fx.enroll(
        api, provider, first["subscriber"], first["check"], dwelling
    )
    co_resident = fx.eligible_applicant(api, dwelling["id"])

    other_dwelling = fx.register_distinct_address(api, 2)
    stranger = fx.eligible_applicant(api, other_dwelling["id"])
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "dwelling": dwelling,
        "enrollment": enrollment,
        "co_resident": co_resident,
        "other_dwelling": other_dwelling,
        "stranger": stranger,
    }


def test_household_occupancy_outranks_the_enrollment_cap(api):
    """One request trips both the household slot and the cap; the safety rule wins.

    PRD: "A request to enroll that would both breach the household's permitted benefit
    occupancy **and** push the carrier past its enrollment cap reports
    `ERR_ONE_PER_HOUSEHOLD_VIOLATION`, not `ERR_PROVIDER_ENROLLMENT_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/one_per_household_safety_error_outranks_enrollment_cap_fiscal_error
    """
    context = _saturated_carrier_with_an_occupied_dwelling(api)
    dwelling = fx.refresh_address(api, context["dwelling"]["id"])
    assert dwelling["occupied_benefit_slots"] == 1
    assert dwelling["max_permitted_benefit_slots"] == 1
    assert dwelling["status"] == "UNVERIFIED", (
        f"a dwelling alone in its cohort is not flagged, got {dwelling['status']}"
    )
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 1

    response = api.create_enrollment(
        f.enrollment_payload(
            subscriber_id=context["co_resident"]["subscriber"]["id"],
            provider_id=context["provider"]["id"],
            eligibility_check_id=context["co_resident"]["check"]["id"],
            certified_address_id=context["dwelling"]["id"],
        ),
        context["agent"],
    )
    validate_error(response, ApiErrorId.ONE_PER_HOUSEHOLD_VIOLATION.value, 409)

    assert fx.refresh_address(api, context["dwelling"]["id"])["occupied_benefit_slots"] == 1
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 1
    assert (
        fx.refresh_subscriber(api, context["co_resident"]["subscriber"]["id"])["status"]
        == "VERIFIED_ELIGIBLE"
    )


def test_the_enrollment_cap_is_live_at_an_unoccupied_dwelling(api):
    """The control: a free household slot at the same saturated carrier reports the cap.

    PRD: "The one-benefit-per-household rule is the program's central safety constraint and
    outranks every fiscal check."

    Design: Difficulty/priority_pair_validation_conflict/one_per_household_safety_error_outranks_enrollment_cap_fiscal_error
    """
    context = _saturated_carrier_with_an_occupied_dwelling(api)

    response = api.create_enrollment(
        f.enrollment_payload(
            subscriber_id=context["stranger"]["subscriber"]["id"],
            provider_id=context["provider"]["id"],
            eligibility_check_id=context["stranger"]["check"]["id"],
            certified_address_id=context["other_dwelling"]["id"],
        ),
        context["agent"],
    )
    validate_error(response, ApiErrorId.PROVIDER_ENROLLMENT_CAP_EXCEEDED.value, 409)

    assert fx.refresh_address(api, context["other_dwelling"]["id"])["occupied_benefit_slots"] == 0
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 1
    assert (
        fx.refresh_subscriber(api, context["stranger"]["subscriber"]["id"])["status"]
        == "VERIFIED_ELIGIBLE"
    )


def _frozen_benefit_and_a_bare_benefit_sharing_an_empty_pool(api):
    """One handset, passed from E1 to E2, leaving E1 frozen and E3 bare with an empty pool."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    provider = fx.register_provider(api)
    device = fx.stock_device(api, provider)

    benefits = []
    for index in (1, 2, 3):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        benefits.append(
            fx.enroll(api, provider, applicant["subscriber"], applicant["check"], address)
        )

    fx.issue_device(api, benefits[0]["id"], provider, device_id=device["id"])
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    fx.return_device(api, device["id"], return_condition="GOOD")
    fx.issue_device(api, benefits[1]["id"], provider, device_id=device["id"])
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "device": device,
        "frozen": benefits[0],
        "holder": benefits[1],
        "bare": benefits[2],
    }


def test_the_reissue_freeze_outranks_the_empty_stock_constraint(api):
    """One request trips both the freeze and the empty pool; the freeze wins.

    PRD: "A handset issuance request that falls inside the reissue freeze **and** faces an
    empty in-stock pool reports `ERR_DEVICE_FREEZE_ACTIVE`, not `ERR_NO_DEVICE_IN_STOCK`."

    Design: Difficulty/priority_pair_validation_conflict/device_freeze_temporal_error_outranks_empty_stock_business_constraint
    """
    context = _frozen_benefit_and_a_bare_benefit_sharing_an_empty_pool(api)
    carrier = fx.refresh_provider(api, context["provider"]["id"])
    assert carrier["devices_in_stock_count"] == 0, "the pool really is empty"
    assert carrier["devices_issued_count"] == 1
    assert carrier["devices_total_count"] == 1

    response = api.issue_device(
        context["frozen"]["id"], f.device_issuance_payload(), context["agent"]
    )
    validate_error(response, ApiErrorId.DEVICE_FREEZE_ACTIVE.value, 409)

    frozen = fx.refresh_enrollment(api, context["frozen"]["id"])
    assert frozen["device_status"] == "AWAITING_DEVICE"
    assert frozen["device_issuance_count"] == 1, "the returned handset still counts"
    assert_instant(
        frozen["last_device_issued_at"], "2026-08-01T00:00:00Z", "last_device_issued_at"
    )
    device = fx.refresh_device(api, context["device"]["id"])
    assert device["status"] == "ISSUED"
    assert device["issued_enrollment_id"] == context["holder"]["id"]


def test_the_empty_stock_constraint_is_live_for_a_benefit_that_never_held_a_handset(api):
    """The control: the same empty pool reports the inventory error when no freeze applies.

    PRD: "On handset issuance the ordering is: the enrollment's benefit is active; the
    enrollment is not already holding a handset; the reissue freeze is clear or waived; the
    subscriber holds no outstanding handset anywhere; a handset is available in stock."

    Design: Difficulty/priority_pair_validation_conflict/device_freeze_temporal_error_outranks_empty_stock_business_constraint
    """
    context = _frozen_benefit_and_a_bare_benefit_sharing_an_empty_pool(api)

    response = api.issue_device(
        context["bare"]["id"], f.device_issuance_payload(), context["agent"]
    )
    validate_error(response, ApiErrorId.NO_DEVICE_IN_STOCK.value, 409)

    bare = fx.refresh_enrollment(api, context["bare"]["id"])
    assert bare["device_status"] == "AWAITING_DEVICE"
    assert bare["device_issuance_count"] == 0, "this benefit never held a handset"
    assert_instant_null(bare["last_device_issued_at"], "last_device_issued_at")
    assert fx.refresh_provider(api, context["provider"]["id"])["devices_in_stock_count"] == 0
