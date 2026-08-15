"""Advisor identity rules, the deceased-advisor succession cascade, and the
inactivity trigger boundary."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_fund_payload,
    create_agreement_payload,
    create_advisor_payload,
    create_contribution_payload,
    make_advisor_headers,
    set_logical_clock,
    get_fund,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
GIFT = TEST_USERS["gift_officer_headers"]


def _setup_inactive_fund_with_successor(api):
    """DAF fund, ACTIVE at 2026-01-15, with an ACTIVE primary advisor and an
    INVITED successor named on the EXECUTED agreement; clock then advanced so
    the fund lapses to INACTIVE (37 months past last activity, trigger 36)."""
    set_logical_clock("2026-01-15T00:00:00Z")
    fund = get_success_data(
        api.create_fund(create_fund_payload(fund_type="DONOR_ADVISED"), ADMIN)
    )
    primary = get_success_data(
        api.invite_advisor(fund["id"], create_advisor_payload(advisor_kind="PRIMARY"), ADMIN)
    )
    get_success_data(
        api.accept_advisor(primary["id"], make_advisor_headers(primary["id"]))
    )
    successor = get_success_data(
        api.invite_advisor(
            fund["id"], create_advisor_payload(advisor_kind="SUCCESSOR"), ADMIN
        )
    )
    agreement = get_success_data(
        api.create_agreement(
            fund["id"],
            create_agreement_payload(
                successor_advisor_id=successor["id"],
                inactivity_trigger_months=36,
                dormancy_trigger_months=24,
            ),
            ADMIN,
        )
    )
    get_success_data(api.execute_agreement(agreement["id"], ADMIN))
    contribution = get_success_data(
        api.create_contribution(
            create_contribution_payload(fund_id=fund["id"], declared_value=50000.00),
            GIFT,
        )
    )
    get_success_data(api.accept_contribution(contribution["id"], GIFT))
    get_success_data(api.activate_fund(fund["id"], ADMIN))
    # 37 whole months of inactivity (>= trigger 36, < dormancy 60).
    set_logical_clock("2029-03-01T00:00:00Z")
    fund_inactive = get_fund(fund["id"])
    assert fund_inactive["status"] == "INACTIVE"
    return fund["id"], primary, successor


def test_record_deceased_activates_named_successor(api):
    """PRD §3.2: "In the second hop, if the fund's `EXECUTED` agreement names a
    `successor_advisor_id` whose status is `INVITED`, that successor
    auto-transitions from `INVITED` to `ACTIVE` without any acceptance call —
    the executed agreement itself is the authorization."

    Design: Difficulty/transitive_cascade/advisor_deceased_succession_inactive_cascade
    """
    _, primary, successor = _setup_inactive_fund_with_successor(api)
    deceased = validate_success(api.record_advisor_deceased(primary["id"], ADMIN), 200)
    assert deceased["status"] == "DECEASED"
    successor_after = validate_success(api.get_advisor(successor["id"], ADMIN))
    assert successor_after["status"] == "ACTIVE"


def test_succession_reactivates_inactive_fund(api):
    """PRD §3.2: "In the third hop, the successor's auto-activation counts as an
    advisor succession event on the fund: it refreshes the fund's
    `last_activity_at`, and if the fund was `INACTIVE` it immediately
    auto-transitions back to `ACTIVE` per the fund lifecycle."

    Design: Difficulty/transitive_cascade/advisor_deceased_succession_inactive_cascade
    """
    fund_id, primary, successor = _setup_inactive_fund_with_successor(api)
    validate_success(api.record_advisor_deceased(primary["id"], ADMIN), 200)
    successor_after = validate_success(api.get_advisor(successor["id"], ADMIN))
    assert successor_after["status"] == "ACTIVE"
    fund_after = get_fund(fund_id)
    assert fund_after["status"] == "ACTIVE"


def test_advisor_accept_self_service_only(api):
    """PRD §3.2: "Acceptance is strictly self-service: the acting advisor's
    `X-User-ID` must equal the invited advisor row's `id`, and an acceptance
    attempted under any other identity is rejected with
    `ERR_NOT_THE_INVITED_ADVISOR` (HTTP 403)."
    PRD §3.2: "A successful acceptance moves the advisor from `INVITED` to
    `ACTIVE` and stamps `activated_at`."

    Design: Corner/roles/advisor_identity_self_service_accept
    """
    fund = get_success_data(
        api.create_fund(create_fund_payload(fund_type="DONOR_ADVISED"), ADMIN)
    )
    advisor = get_success_data(
        api.invite_advisor(fund["id"], create_advisor_payload(), ADMIN)
    )
    resp = api.accept_advisor(advisor["id"], make_advisor_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_NOT_THE_INVITED_ADVISOR)
    accepted = validate_success(
        api.accept_advisor(advisor["id"], make_advisor_headers(advisor["id"])), 200
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["activated_at"] is not None


def test_fund_inactive_flip_at_trigger_boundary(api):
    """PRD §3.2: "A fund's `inactivity_months` is the number of whole calendar
    months between `last_activity_at` and the current logical clock: take the
    difference in calendar years multiplied by twelve, add the difference in
    calendar months, and subtract one when the day-of-month of the clock is
    earlier than the day-of-month of `last_activity_at`."
    PRD §3.2: "When a clock advance pushes a `DONOR_ADVISED` fund's
    `inactivity_months` to at least the executed agreement's
    `inactivity_trigger_months` (thirty-six months by default), the fund lapses
    from `ACTIVE` to `INACTIVE`."

    Design: Corner/cross_cutting_layers/rate_threshold_inactivity_flip_at_boundary
    """
    set_logical_clock("2026-01-15T00:00:00Z")
    fund = get_success_data(
        api.create_fund(create_fund_payload(fund_type="DONOR_ADVISED"), ADMIN)
    )
    agreement = get_success_data(
        api.create_agreement(
            fund["id"], create_agreement_payload(inactivity_trigger_months=36), ADMIN
        )
    )
    get_success_data(api.execute_agreement(agreement["id"], ADMIN))
    contribution = get_success_data(
        api.create_contribution(
            create_contribution_payload(fund_id=fund["id"], declared_value=50000.00),
            GIFT,
        )
    )
    get_success_data(api.accept_contribution(contribution["id"], GIFT))
    get_success_data(api.activate_fund(fund["id"], ADMIN))

    # 2028-12-16: (2 years * 12) + 11 months = 35 whole months (day 16 >= day
    # 15, no subtraction) — still below the 36-month trigger.
    set_logical_clock("2028-12-16T00:00:00Z")
    assert get_fund(fund["id"])["status"] == "ACTIVE"

    # 2029-02-01: (3 years * 12) + 1 month = 37 raw, minus one because the
    # clock's day-of-month (1) is earlier than the baseline's (15) -> 36, which
    # reaches the trigger.
    set_logical_clock("2029-02-01T00:00:00Z")
    assert get_fund(fund["id"])["status"] == "INACTIVE"
