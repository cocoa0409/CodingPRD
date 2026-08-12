"""Referral marketing: campaign gate on event creation, budget and window
checks in pinned order, closed-interval adjacency, hold terminal lockdown, and
the compensating budget ledger."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_physician, create_case,
    create_campaign_payload, create_campaign_event_payload,
)

PM = TEST_USERS["practice_manager_headers"]


def _setup_campaign(budget_cents=1000000, name="Outreach", activate=True):
    physician = create_physician(specialty="PEDIATRICS", hire_type="NEW_GRAD")
    case = create_case(physician["id"])
    campaign = validate_success(
        api_client.create_referral_campaign(
            create_campaign_payload(case["id"], name=name, budget_cents=budget_cents), PM
        ),
        201,
    )
    if activate:
        campaign = validate_success(
            api_client.activate_referral_campaign(campaign["id"], PM), 200
        )
    return physician, case, campaign


def test_campaign_event_requires_active_campaign(api):
    """PRD §3.7: "Events are planned inside an `ACTIVE` campaign — planning against a campaign in any other state is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`."
    PRD §3.7: "A created event is `PLANNED`, and its `cost_cents` is immediately debited into the campaign's `spent_cents`."

    Design: Corner/validations/campaign_event_requires_active_campaign
    """
    _, _, campaign = _setup_campaign(budget_cents=500000, activate=False)
    payload = create_campaign_event_payload(
        campaign["id"], event_type="MEDIA",
        start_date="2027-04-01", end_date="2027-04-02", cost_cents=100000,
    )
    resp = api_client.create_campaign_event(payload, PM)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)

    validate_success(api_client.activate_referral_campaign(campaign["id"], PM), 200)
    data = validate_success(api_client.create_campaign_event(payload, PM), 201)
    assert data["status"] == "PLANNED"
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 100000


def test_event_budget_exceeded_without_overlap(api):
    """PRD §3.7: "The budget gate at creation therefore asks whether `spent_cents` plus the new event's `cost_cents` stays within `budget_cents`; if it would exceed the budget, creation is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/event_budget_exceeded_without_overlap
    """
    _, _, campaign = _setup_campaign(budget_cents=500000, name="Small")
    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], event_type="MEDIA",
                start_date="2027-04-01", end_date="2027-04-02", cost_cents=450000,
            ),
            PM,
        ),
        201,
    )
    resp = api_client.create_campaign_event(
        create_campaign_event_payload(
            campaign["id"], event_type="OPEN_HOUSE",
            start_date="2027-04-10", end_date="2027-04-10", cost_cents=100000,
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED)
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 450000, "a rejected event must not debit the budget"


def test_event_closed_interval_adjacency_conflicts(api):
    """PRD §3.7: "the closed window from `start_date` through `end_date` may not share any single date with any non-`CANCELLED` sibling event of the same campaign, and because the intervals are closed, even adjacent dates conflict — with violations rejected as `ERR_EVENT_WINDOW_OVERLAP` (HTTP 422)"

    Design: Difficulty/resource_temporal_overlap/event_closed_interval_adjacency_conflicts
    """
    _, _, campaign = _setup_campaign()
    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], start_date="2027-03-10", end_date="2027-03-12",
                cost_cents=600000, venue="Library",
            ),
            PM,
        ),
        201,
    )
    resp = api_client.create_campaign_event(
        create_campaign_event_payload(
            campaign["id"], event_type="OPEN_HOUSE",
            start_date="2027-03-12", end_date="2027-03-13", cost_cents=100000, venue="Clinic",
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)


def test_event_closed_interval_first_free_date_accepted(api):
    """PRD §3.7: "the closed window from `start_date` through `end_date` may not share any single date with any non-`CANCELLED` sibling event of the same campaign, and because the intervals are closed, even adjacent dates conflict"
    PRD §3.7: "The campaign's `spent_cents` is a strict ledger: it always equals the sum of `cost_cents` over the campaign's events in `PLANNED` or `HELD`."

    Design: Difficulty/resource_temporal_overlap/event_closed_interval_adjacency_conflicts
    """
    _, _, campaign = _setup_campaign()
    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], start_date="2027-03-10", end_date="2027-03-12",
                cost_cents=600000, venue="Library",
            ),
            PM,
        ),
        201,
    )
    resp = api_client.create_campaign_event(
        create_campaign_event_payload(
            campaign["id"], event_type="OPEN_HOUSE",
            start_date="2027-03-12", end_date="2027-03-13", cost_cents=100000, venue="Clinic",
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)

    data = validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], event_type="MEDIA",
                start_date="2027-03-13", end_date="2027-03-14", cost_cents=300000, venue="Studio",
            ),
            PM,
        ),
        201,
    )
    assert data["status"] == "PLANNED", "the first date past the closed window must be accepted"
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 900000, "600000 + 300000; the rejected event contributed nothing"


def test_event_overlap_beats_budget_priority(api):
    """PRD §3.7: "Two checks guard creation, in a pinned order: first the window check — the closed window from `start_date` through `end_date` may not share any single date with any non-`CANCELLED` sibling event of the same campaign, and because the intervals are closed, even adjacent dates conflict — with violations rejected as `ERR_EVENT_WINDOW_OVERLAP` (HTTP 422); then the budget check, described next."

    Design: Difficulty/priority_pair_validation_conflict/event_overlap_beats_budget_priority
    """
    _, _, campaign = _setup_campaign()
    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], start_date="2027-03-10", end_date="2027-03-12",
                cost_cents=600000, venue="Library",
            ),
            PM,
        ),
        201,
    )
    # Overlaps on 2027-03-12 AND overspends (600000 + 500000 > 1000000): the
    # temporal error must win because the window check runs first.
    resp = api_client.create_campaign_event(
        create_campaign_event_payload(
            campaign["id"], event_type="REFERRAL_DINNER",
            start_date="2027-03-12", end_date="2027-03-14", cost_cents=500000, venue="Bistro",
        ),
        PM,
    )
    error_data = validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)
    assert resp.status_code == 422
    assert error_data["error_id"] != ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED


def test_event_overlap_beats_budget_priority_no_debit(api):
    """PRD §3.7: "Two checks guard creation, in a pinned order: first the window check — the closed window from `start_date` through `end_date` may not share any single date with any non-`CANCELLED` sibling event of the same campaign, and because the intervals are closed, even adjacent dates conflict — with violations rejected as `ERR_EVENT_WINDOW_OVERLAP` (HTTP 422); then the budget check, described next."
    PRD §3.7: "The campaign's `spent_cents` is a strict ledger: it always equals the sum of `cost_cents` over the campaign's events in `PLANNED` or `HELD`."

    Design: Difficulty/priority_pair_validation_conflict/event_overlap_beats_budget_priority
    """
    _, _, campaign = _setup_campaign()
    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], start_date="2027-03-10", end_date="2027-03-12",
                cost_cents=600000, venue="Library",
            ),
            PM,
        ),
        201,
    )
    resp = api_client.create_campaign_event(
        create_campaign_event_payload(
            campaign["id"], event_type="REFERRAL_DINNER",
            start_date="2027-03-12", end_date="2027-03-14", cost_cents=500000, venue="Bistro",
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 600000, "no debit may occur when creation is rejected"


def test_held_event_cannot_be_cancelled(api):
    """PRD §3.7: "Cancelling a `PLANNED` event — from any other state, cancellation is rejected with `ERR_EVENT_NOT_PLANNED`"
    PRD §3.7: "Holding moves the event to `HELD`, adds `referrals_generated` into the campaign's `referrals_attributed`, and — when the case's panel is `OPEN` — flows the referrals into the census."

    Design: Corner/state_machines/held_event_cannot_be_cancelled
    """
    _, _, campaign = _setup_campaign()
    event = validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], event_type="OPEN_HOUSE",
                start_date="2027-04-05", end_date="2027-04-05", cost_cents=200000, venue="Clinic",
            ),
            PM,
        ),
        201,
    )
    data = validate_success(
        api_client.hold_campaign_event(event["id"], {"referrals_generated": 12}, PM), 200
    )
    assert data["status"] == "HELD"
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["referrals_attributed"] == 12

    resp = api_client.cancel_campaign_event(event["id"], PM)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PLANNED)
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 200000, "held event costs are sunk, not refunded"


def test_campaign_budget_conserved_by_cancel_debits(api):
    """PRD §3.7: "A created event is `PLANNED`, and its `cost_cents` is immediately debited into the campaign's `spent_cents`."
    PRD §3.7: "The campaign's `spent_cents` is a strict ledger: it always equals the sum of `cost_cents` over the campaign's events in `PLANNED` or `HELD`."

    Design: Difficulty/compensating_invariant/campaign_budget_conserved_by_cancel
    """
    _, _, campaign = _setup_campaign(name="Q3")
    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], event_type="REFERRAL_DINNER",
                start_date="2027-04-05", end_date="2027-04-05", cost_cents=400000, venue="Bistro",
            ),
            PM,
        ),
        201,
    )
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 400000, "creation debits cost_cents into spent_cents"

    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], event_type="MEDIA",
                start_date="2027-04-10", end_date="2027-04-11", cost_cents=250000, venue="Studio",
            ),
            PM,
        ),
        201,
    )
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 650000, "400000 + 250000 accumulated over PLANNED events"


def test_campaign_budget_conserved_by_cancel_refund(api):
    """PRD §3.7: "Cancelling a `PLANNED` event — from any other state, cancellation is rejected with `ERR_EVENT_NOT_PLANNED` — moves it to `CANCELLED` and refunds its `cost_cents` from `spent_cents`, so a create followed by a cancel of the same event leaves the ledger unchanged."

    Design: Difficulty/compensating_invariant/campaign_budget_conserved_by_cancel
    """
    _, _, campaign = _setup_campaign(name="Q3")
    event1 = validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], event_type="REFERRAL_DINNER",
                start_date="2027-04-05", end_date="2027-04-05", cost_cents=400000, venue="Bistro",
            ),
            PM,
        ),
        201,
    )
    validate_success(
        api_client.create_campaign_event(
            create_campaign_event_payload(
                campaign["id"], event_type="MEDIA",
                start_date="2027-04-10", end_date="2027-04-11", cost_cents=250000, venue="Studio",
            ),
            PM,
        ),
        201,
    )
    data = validate_success(api_client.cancel_campaign_event(event1["id"], PM), 200)
    assert data["status"] == "CANCELLED"
    campaign = get_success_data(api_client.get_referral_campaign(campaign["id"], PM))
    assert campaign["spent_cents"] == 250000, (
        "the cancel refunds exactly the cancelled event's 400000, not prorated"
    )
