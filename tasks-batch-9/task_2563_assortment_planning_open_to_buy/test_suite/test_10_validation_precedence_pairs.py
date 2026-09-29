"""Requests that violate two ladder rules at once, and the ordering that decides them.

Each test translates one instance of the difficulty rule
``priority_pair_validation_conflict``.
"""
from test_helpers import (
    BUYER_HEADERS,
    ApiErrorId,
    cancel_commitment,
    commit_commitment,
    create_plan_month,
    create_vendor_authorization,
    get_month,
    get_plan,
    get_success_data,
    month_version,
    propose_commitment,
    propose_item,
    receipt_commitment_payload,
    setup_plan_scenario,
    setup_single_month_approved_plan,
    validate_error,
    validate_success,
)

MAY_WINDOW = {"ship_window_start": "2027-05-01T00:00:00Z",
              "ship_window_end": "2027-05-15T00:00:00Z"}


def _probe(api, month_id, item_id, vendor_id, **overrides):
    payload = receipt_commitment_payload(
        month_id, item_id, vendor_id, month_version(month_id), **overrides
    )
    return api.create_receipt_commitment(payload, BUYER_HEADERS)


def _frozen_plan(scenario_kwargs=None):
    """Drain both canonical months until the plan's posture is FROZEN."""
    scenario = setup_plan_scenario(approve=True, **(scenario_kwargs or {}))
    vendor_id = scenario["vendor"]["id"]
    item = propose_item(scenario["option_plan"]["id"], vendor_id,
                        sku_code="DRSS-CARRY-X", color_code="BLACK",
                        lifecycle_stage="CARRYOVER", unit_cost_cents=2600,
                        retail_price_cents=6900, prior_season_sell_through_bps=7100)
    rc1 = propose_commitment(scenario["m1"]["id"], item["id"], vendor_id,
                             units=7000, unit_cost_cents=2600)
    commit_commitment(rc1["id"])
    rc2 = propose_commitment(scenario["m2"]["id"], item["id"], vendor_id,
                             units=8000, unit_cost_cents=2500,
                             ship_window_start="2027-04-02T00:00:00Z",
                             ship_window_end="2027-04-16T00:00:00Z")
    commit_commitment(rc2["id"])
    return scenario, item, rc1, rc2


def test_frozen_posture_at_priority_16_beats_otb_exceeded_at_priority_37(
    api, buyer_headers
):
    """A request that trips both rules answers with the lower-numbered one.

    PRD: "the system evaluates rules **strictly in ascending priority order and the first
    rule that fails decides the response** ... a request that violates three of them
    returns the code of the lowest-numbered one." Rule 16 is "The governing plan's
    `otb_posture` is not `FROZEN` — `ERR_OTB_POSTURE_FROZEN` (409)" and rule 37 is "The
    commitment's cost does not exceed the month's open balance — `ERR_OTB_EXCEEDED` (422)".
    The 30_000_000 candidate exceeds M2's 1_970_000 open balance and the posture is
    `FROZEN`, so the 409 wins.

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_otb_exceeded
    """
    scenario, item, _rc1, rc2 = _frozen_plan()
    m2_id = scenario["m2"]["id"]
    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 490
    assert plan["otb_posture"] == "FROZEN"
    assert get_month(m2_id)["otb_open_cents"] == 1_970_000
    month_version_before = get_month(m2_id)["version"]

    resp = _probe(api, m2_id, item["id"], scenario["vendor"]["id"],
                  units=12000, unit_cost_cents=2500, **MAY_WINDOW)

    validate_error(resp, ApiErrorId.ERR_OTB_POSTURE_FROZEN, expected_status=409)

    listed = api.list_receipt_commitments(
        buyer_headers, params={"plan_month_id": m2_id, "limit": 50}
    )
    validate_success(listed)
    rows = get_success_data(listed)
    assert [row["id"] for row in rows] == [rc2["id"]]
    assert get_month(m2_id)["version"] == month_version_before


def test_lifting_the_freeze_lets_the_same_request_reach_the_fiscal_rule(api):
    """Only the posture changed, and the identical payload now fails on rule 37.

    PRD rule 37: "The commitment's cost does not exceed the month's open balance —
    `ERR_OTB_EXCEEDED` (422)". After the cancel the month's open balance is 21_970_000 and
    "a cost exactly equal to the open balance is accepted, and one cent more is refused
    with `ERR_OTB_EXCEEDED`" — 30_000_000 still exceeds it, so the priority-37 rule is now
    the first one to fail.

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_otb_exceeded
    """
    scenario, item, _rc1, rc2 = _frozen_plan()
    m2_id = scenario["m2"]["id"]

    cancel_commitment(rc2["id"], cancel_reason="release April dollars")
    assert get_month(m2_id)["otb_open_cents"] == 21_970_000
    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 5469
    assert plan["otb_posture"] == "OPEN"

    resp = _probe(api, m2_id, item["id"], scenario["vendor"]["id"],
                  units=12000, unit_cost_cents=2500, **MAY_WINDOW)

    validate_error(resp, ApiErrorId.ERR_OTB_EXCEEDED, expected_status=422)


OCTOBER_WINDOW = {"ship_window_start": "2026-10-01T00:00:00Z",
                  "ship_window_end": "2026-10-15T00:00:00Z"}
DECEMBER_WINDOW = {"ship_window_start": "2026-12-01T00:00:00Z",
                   "ship_window_end": "2026-12-15T00:00:00Z"}


def _long_lead_unauthorized_vendor():
    """An AUTHORIZED long-lead vendor with no authorization into the plan's category."""
    scenario = setup_single_month_approved_plan(
        authorize_category=False,
        vendor_overrides={"name": "Bluebird Weaving", "code": "BLUE",
                          "lead_time_days": 120, "weekly_unit_capacity": 12000,
                          "min_order_units": 1, "cancel_cutoff_days": 21},
    )
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-BLUE-01", color_code="SKY",
                        lifecycle_stage="CARRYOVER", unit_cost_cents=2500,
                        retail_price_cents=6900, prior_season_sell_through_bps=7100)
    return scenario, item


def test_missing_authorization_at_priority_19_beats_lead_time_at_priority_34(api):
    """Two 422s collide, so only the error id can tell a correct ladder from a wrong one.

    PRD rule 19: "An `ACTIVE` vendor authorization joins the commitment's vendor to the
    category of the plan that owns the target month —
    `ERR_VENDOR_NOT_AUTHORIZED_FOR_CATEGORY` (422)". PRD rule 34: "`ship_window_start` is
    no earlier than the logical clock plus the vendor's `lead_time_days` —
    `ERR_LEAD_TIME_INFEASIBLE` (422)". The October window sits inside the vendor's 120-day
    lead time from the startup clock and no authorization exists, so rule 19 decides.

    Design: Difficulty/priority_pair_validation_conflict/vendor_authorization_beats_lead_time_infeasible
    """
    scenario, item = _long_lead_unauthorized_vendor()

    resp = _probe(api, scenario["m1"]["id"], item["id"], scenario["vendor"]["id"],
                  units=100, unit_cost_cents=2500, **OCTOBER_WINDOW)

    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_AUTHORIZED_FOR_CATEGORY,
                   expected_status=422)


def test_granting_the_authorization_surfaces_the_lead_time_rule_then_a_valid_window(api):
    """Repairing the referential defect exposes the temporal one; moving the window passes.

    PRD: "the first rule that fails decides the response". With an `ACTIVE` authorization in
    place the priority-19 rule passes and rule 34 becomes the first failure. A window
    starting 2026-12-01 is on or after the startup clock advanced by 120 days, so the
    proposal is stored — and PRD: "Creating the commitment advances the target plan month's
    version by 1 even though a `PROPOSED` commitment has not yet entered the month's
    committed figure".

    Design: Difficulty/priority_pair_validation_conflict/vendor_authorization_beats_lead_time_infeasible
    """
    scenario, item = _long_lead_unauthorized_vendor()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]

    authorization = create_vendor_authorization(
        vendor_id, scenario["category"]["id"], max_open_units=5000
    )
    assert authorization["status"] == "ACTIVE"
    assert authorization["max_open_units"] == 5000

    resp = _probe(api, month_id, item["id"], vendor_id, units=100,
                  unit_cost_cents=2500, **OCTOBER_WINDOW)
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_INFEASIBLE, expected_status=422)

    ok = _probe(api, month_id, item["id"], vendor_id, units=100,
                unit_cost_cents=2500, **DECEMBER_WINDOW)
    validate_success(ok, expected_status=201)
    stored = get_success_data(ok)
    assert stored["commit_status"] == "PROPOSED"
    assert stored["fulfillment_status"] == "AWAITING_SHIP"
    assert stored["cost_cents"] == 250_000
    assert stored["open_cost_cents"] == 250_000

    month = get_month(month_id)
    assert month["otb_committed_cents"] == 0
    assert month["otb_open_cents"] == 18_200_000


def _plan_with_a_late_added_draft_month():
    """An APPROVED single-month plan that later gains a month, plus a 1400-cent option."""
    scenario = setup_single_month_approved_plan()
    late_month = create_plan_month(
        scenario["plan_id"], month_index=3, fiscal_month_label="2027-05",
        first_receipt_date="2027-05-07T00:00:00Z",
    )
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-CAPA-01", color_code="RED",
                        unit_cost_cents=1400, retail_price_cents=3900)
    return scenario, late_month, item


def test_draft_month_at_priority_10_beats_vendor_capacity_at_priority_31(api):
    """Both rules answer 409, so a swapped ladder is invisible except through the error id.

    PRD: "Months may be added while the plan sits at any governance status; a month added
    after an approval starts in `DRAFT` and remains `DRAFT` until a subsequent approval locks
    it." PRD rule 10: "The referenced plan month is in the status the operation requires —
    `ERR_PLAN_MONTH_NOT_OPEN` (409)... (which require `LOCKED_PLAN` or `IN_SEASON`)". The
    13000 units also exceed the vendor's 12000 `weekly_unit_capacity` of rule 31, but the
    month-status rule is consulted first.

    Design: Difficulty/priority_pair_validation_conflict/plan_month_state_beats_vendor_capacity
    """
    scenario, late_month, item = _plan_with_a_late_added_draft_month()
    assert late_month["status"] == "DRAFT"
    assert late_month["otb_planned_cents"] == 0

    resp = _probe(api, late_month["id"], item["id"], scenario["vendor"]["id"],
                  units=13000, unit_cost_cents=1400)

    validate_error(resp, ApiErrorId.ERR_PLAN_MONTH_NOT_OPEN, expected_status=409)
    assert month_version(late_month["id"]) == late_month["version"]


def test_the_same_body_against_the_locked_month_falls_through_to_vendor_capacity(api):
    """Retargeting the open month clears rule 10 and lands on the ship-window capacity test.

    PRD rule 31: "the candidate passes both the overlapping-ship-window capacity test against
    `weekly_unit_capacity` ... — `ERR_VENDOR_CAPACITY_EXCEEDED` (409)". 13000 units alone
    exceed the 12000 capacity, while 13000 * 1400 exactly equals the month's 18,200,000
    `otb_open_cents`, so the fiscal rule at priority 37 is not the one that fires. Trimming to
    12000 units satisfies capacity and the proposal is stored, leaving the month's open
    dollars untouched because PRD: "a `PROPOSED` commitment has not yet entered the month's
    committed figure".

    Design: Difficulty/priority_pair_validation_conflict/plan_month_state_beats_vendor_capacity
    """
    scenario, _late_month, item = _plan_with_a_late_added_draft_month()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]
    assert get_month(month_id)["status"] == "LOCKED_PLAN"
    assert get_month(month_id)["otb_open_cents"] == 18_200_000

    resp = _probe(api, month_id, item["id"], vendor_id,
                  units=13000, unit_cost_cents=1400)
    validate_error(resp, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED, expected_status=409)

    ok = _probe(api, month_id, item["id"], vendor_id,
                units=12000, unit_cost_cents=1400)
    validate_success(ok, expected_status=201)
    stored = get_success_data(ok)
    assert stored["units"] == 12000
    assert stored["cost_cents"] == 16_800_000

    month = get_month(month_id)
    assert month["otb_committed_cents"] == 0
    assert month["otb_open_cents"] == 18_200_000
    assert get_plan(scenario["plan_id"])["otb_posture"] == "OPEN"
