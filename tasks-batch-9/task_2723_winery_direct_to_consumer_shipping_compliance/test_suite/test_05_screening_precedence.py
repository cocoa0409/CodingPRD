"""Screening precedence: which of two simultaneously broken rules is recorded.

PRD §2.9 fixes one global evaluation order and, inside the final band, one fixed
ranking of the nineteen domain rules.  Every test in this file arranges a single
call that breaks two ranked rules at once and proves the higher-ranked one is the
one the system answers with, then removes the higher-ranked condition and proves
the lower-ranked rule was live the whole time.

Screening itself never raises: PRD §2.9 says the outcome is recorded in the
order's ``rejection_error_id`` and the call still answers HTTP 200, so the
screening tests assert on ``compliance_status`` and ``rejection_error_id`` rather
than on an error envelope.  The one pair that fires on a write endpoint —
labelling — does answer with error envelopes, and there the ranking is visible in
the status code itself.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_liters, assert_order_dimensions, assert_rejection
from test_helpers.fixtures import (
    build_landscape,
    create_prohibited_zip,
    decide_enrollment,
    set_clock,
)
from test_helpers.test_users import OFFICER_A

DRY_COUNTY_ZIP = "78702"
ALLOWED_ZIP = "78701"
CLOCK_JULY_1 = "2026-07-01T00:00:00Z"
CLOCK_AUG_1 = "2026-08-01T00:00:00Z"


# =========================================================================
# priority_pair_validation_conflict / prohibited_zip_beats_consumer_volume_limit
# =========================================================================
def _tiny_consumer_limit_landscape(api):
    """TX configured with a 1.000 L per-consumer ceiling and 78702 blocked.

    Any six-bottle order breaks the per-consumer volume rule, and an order aimed
    at 78702 breaks the prohibited-destination rule as well.
    """
    scape = build_landscape(
        api, state_rule_overrides={"per_consumer_limit_liters": 1.000}
    )
    create_prohibited_zip(
        api,
        scape.state_rule_id,
        zip_code=DRY_COUNTY_ZIP,
        reason="DRY_COUNTY",
        effective_from="2026-01-01",
    )
    return scape


def test_prohibited_zip_outranks_the_consumer_volume_limit_on_one_screen(api):
    """A screen that breaks both rules records the prohibited ZIP, not the volume rule.

    PRD §3.6: "Note that "highest-ranked" is what selects the recorded
    identifier: an order that both ships into a prohibited ZIP and exceeds its
    consumer limit is rejected outright on the ZIP, because the ZIP rule outranks
    the volume rule and the overridable rule is never reached."

    PRD §2.9: "It always answers HTTP 200 with the order body, and the outcome is
    expressed by moving the order's compliance dimension and writing the
    identifier of the *first* — that is, the highest-ranked — failing ladder rule
    into the order's `rejection_error_id`."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_zip_beats_consumer_volume_limit
    """
    scape = _tiny_consumer_limit_landscape(api)
    order = scape.create_order(ship_to_zip=DRY_COUNTY_ZIP)

    screened = validate_success(api.screen_order(order["id"], {}, OFFICER_A), 200)

    assert_liters(screened["total_liters"], 4.500, "total_liters")
    assert_rejection(screened, "ERR_PROHIBITED_DESTINATION")
    assert_order_dimensions(
        screened, compliance_status="REJECTED", fulfillment_status="UNFULFILLED"
    )
    assert screened["compliance_status"] != "OVERRIDE_PENDING", (
        "ERR_PROHIBITED_DESTINATION is not overridable, so the lower-ranked "
        "overridable breach must not soften the outcome"
    )

    stored = scape.read_order(order["id"])
    assert_rejection(stored, "ERR_PROHIBITED_DESTINATION")
    assert_order_dimensions(stored, compliance_status="REJECTED")


def test_consumer_volume_limit_surfaces_once_the_zip_block_is_not_hit(api):
    """With the same tiny ceiling but an allowed ZIP, the volume rule is recorded.

    PRD §3.6: "The consumer's accumulated rolling liters for the destination
    state, taken from `rolling_liters_by_state`, plus this order's
    `total_liters`, must be at most the state's `per_consumer_limit_liters`."

    PRD §3.6: "If the highest-ranked failing check *is* one of
    `ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED`, `ERR_WINERY_VOLUME_LIMIT_EXCEEDED` or
    `ERR_ELEVATED_RISK_REVIEW_REQUIRED`, the order moves to `OVERRIDE_PENDING`,
    which is an invitation to the exception workflow rather than a refusal."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_zip_beats_consumer_volume_limit
    """
    scape = _tiny_consumer_limit_landscape(api)
    order = scape.create_order(ship_to_zip=ALLOWED_ZIP)

    screened = validate_success(api.screen_order(order["id"], {}, OFFICER_A), 200)

    assert_liters(screened["total_liters"], 4.500, "total_liters")
    assert_rejection(screened, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")
    assert_order_dimensions(
        screened, compliance_status="OVERRIDE_PENDING", fulfillment_status="UNFULFILLED"
    )


def test_neither_the_rejected_nor_the_override_pending_screen_moves_volume(api):
    """Both arms in one world: the ZIP wins, and neither screen reserves liters.

    PRD §3.6: "A **`DRAFT` → `REJECTED`** outcome writes the failing identifier
    into `rejection_error_id` and does nothing else: no ledger entry is appended,
    and `Winery.excise_accrued_cents` is untouched."

    PRD §3.6: "A **`DRAFT` → `OVERRIDE_PENDING`** outcome likewise writes the
    overridable identifier into `rejection_error_id` and appends no ledger entry
    — the liters are not reserved while the exception is pending."

    Design: Difficulty/priority_pair_validation_conflict/prohibited_zip_beats_consumer_volume_limit
    """
    scape = _tiny_consumer_limit_landscape(api)

    control = scape.create_order(ship_to_zip=ALLOWED_ZIP)
    control_screened = validate_success(
        api.screen_order(control["id"], {}, OFFICER_A), 200
    )
    assert_rejection(control_screened, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")
    assert_order_dimensions(control_screened, compliance_status="OVERRIDE_PENDING")

    blocked = scape.create_order(ship_to_zip=DRY_COUNTY_ZIP)
    blocked_screened = validate_success(
        api.screen_order(blocked["id"], {}, OFFICER_A), 200
    )
    assert_rejection(blocked_screened, "ERR_PROHIBITED_DESTINATION")
    assert_order_dimensions(blocked_screened, compliance_status="REJECTED")

    rows = scape.ledger_rows(consumer_id=scape.consumer_id)
    assert len(rows) == 0, f"No ledger entry may exist, found {rows}"
    assert scape.read_winery()["excise_accrued_cents"] == 0
    assert scape.read_consumer()["rolling_liters_by_state"].get("TX", 0) == 0


# =========================================================================
# priority_pair_validation_conflict / order_not_cleared_beats_carrier_not_enrolled
# =========================================================================
def _suspended_enrollment_landscape(api):
    """One CLEARED order, then the carrier suspends the enrollment.

    Every later label request therefore breaks the carrier-enrollment rule, and a
    label drawn against a still-DRAFT order breaks the state precondition too.
    """
    scape = build_landscape(api)
    cleared = scape.create_cleared_order()
    decide_enrollment(api, scape.enrollment_id, "SUSPENDED")
    return scape, cleared


def test_order_not_cleared_outranks_the_suspended_enrollment_at_label_time(api):
    """A label for a DRAFT order answers 409, not the equally-true 422.

    PRD §2.9: "The full evaluation order, from first to last, is: header presence
    (`ERR_UNAUTHENTICATED`), role authorization (`ERR_UNAUTHORIZED`), ownership
    scoping (`ERR_FORBIDDEN_RESOURCE_OWNER`), path-identifier existence (the 404
    family), request-body shape (`ERR_INVALID_REQUEST`), body foreign-key
    existence (the 404 family again), optimistic concurrency
    (`ERR_STALE_VERSION`), state-transition legality (the 409 family:
    `ERR_INVALID_STATE_TRANSITION`, `ERR_ORDER_ALREADY_SCREENED`,
    `ERR_ORDER_NOT_CLEARED`, `ERR_EXCEPTION_ALREADY_DECIDED`,
    `ERR_ENROLLMENT_ALREADY_DECIDED`, `ERR_SHIPMENT_NOT_ACTIVE`), winery
    operating status (`ERR_WINERY_SUSPENDED`), compliance-reinstatement authority
    (`ERR_COMPLIANCE_REINSTATE_FORBIDDEN`), segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), and only then the domain rules of §3."

    PRD §3.7: "The order must be `CLEARED` on the compliance axis and either
    `UNFULFILLED` or — for a re-ship — `RETURNED` on the fulfillment axis; any
    other combination is refused with `ERR_ORDER_NOT_CLEARED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/order_not_cleared_beats_carrier_not_enrolled
    """
    scape, _cleared = _suspended_enrollment_landscape(api)
    draft = scape.create_order()

    response = api.create_shipment(
        f.shipment_payload(draft["id"], scape.enrollment_id), scape.operator
    )
    validate_error(response, "ERR_ORDER_NOT_CLEARED", 409)

    shipments, _meta = validate_paginated(
        api.list_shipments(scape.operator, {"order_id": draft["id"]})
    )
    assert shipments == [], f"No shipment may exist for the DRAFT order: {shipments}"
    stored = scape.read_order(draft["id"])
    assert_order_dimensions(
        stored, compliance_status="DRAFT", fulfillment_status="UNFULFILLED"
    )


def test_carrier_not_enrolled_surfaces_once_the_order_is_cleared(api):
    """Remove the state-precondition breach and the suspended enrollment answers 422.

    PRD §3.7: "The named enrollment must be in `APPROVED` status and must belong
    to the order's own winery, and the enrolled program's `states_served` must
    contain the order's `ship_to_state_code`; a suspended or foreign enrollment,
    or a program that does not serve the destination, is refused with
    `ERR_CARRIER_NOT_ENROLLED`."

    PRD §3.3: "While an enrollment sits in `SUSPENDED`, no new label may be drawn
    against it; the attempt is refused with `ERR_CARRIER_NOT_ENROLLED`."

    Design: Difficulty/priority_pair_validation_conflict/order_not_cleared_beats_carrier_not_enrolled
    """
    scape, cleared = _suspended_enrollment_landscape(api)
    assert_order_dimensions(
        cleared, compliance_status="CLEARED", fulfillment_status="UNFULFILLED"
    )

    response = api.create_shipment(
        f.shipment_payload(cleared["id"], scape.enrollment_id), scape.operator
    )
    validate_error(response, "ERR_CARRIER_NOT_ENROLLED", 422)

    shipments, _meta = validate_paginated(
        api.list_shipments(scape.operator, {"order_id": cleared["id"]})
    )
    assert shipments == [], f"The refused label must create nothing: {shipments}"


def test_both_label_rules_are_live_and_the_409_wins_the_pair(api):
    """One world, two label attempts: the DRAFT order answers 409, the CLEARED one 422.

    PRD §2.9: "Because a single request can violate several rules at once, the
    outcome the caller sees is determined entirely by which rule the server checks
    first."

    PRD §3.7: "The order must be `CLEARED` on the compliance axis and either
    `UNFULFILLED` or — for a re-ship — `RETURNED` on the fulfillment axis; any
    other combination is refused with `ERR_ORDER_NOT_CLEARED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/order_not_cleared_beats_carrier_not_enrolled
    """
    scape, cleared = _suspended_enrollment_landscape(api)
    draft = scape.create_order()

    both_broken = api.create_shipment(
        f.shipment_payload(draft["id"], scape.enrollment_id), scape.operator
    )
    validate_error(both_broken, "ERR_ORDER_NOT_CLEARED", 409)

    only_carrier_broken = api.create_shipment(
        f.shipment_payload(cleared["id"], scape.enrollment_id), scape.operator
    )
    validate_error(only_carrier_broken, "ERR_CARRIER_NOT_ENROLLED", 422)

    enrollment = validate_success(
        api.get_carrier_enrollment(scape.enrollment_id, scape.officer), 200
    )
    assert enrollment["status"] == "SUSPENDED"
    assert_order_dimensions(
        scape.read_order(cleared["id"]),
        compliance_status="CLEARED",
        fulfillment_status="UNFULFILLED",
    )
    assert_order_dimensions(
        scape.read_order(draft["id"]),
        compliance_status="DRAFT",
        fulfillment_status="UNFULFILLED",
    )


# =========================================================================
# priority_pair_validation_conflict / permit_expired_beats_winery_volume_limit
# =========================================================================
def _lapsed_permit_landscape(api):
    """A permit that expired on 2026-07-31 while the clock sits at 2026-08-01.

    The TX rule also carries a 1.000 L per-winery annual ceiling, so the winery
    volume rule is broken by the same 4.500 L order that meets the lapsed permit.
    """
    scape = build_landscape(
        api,
        clock=CLOCK_JULY_1,
        state_rule_overrides={"per_winery_annual_limit_liters": 1.000},
        permit_overrides={"expiration_date": "2026-07-31"},
    )
    set_clock(api, CLOCK_AUG_1)
    return scape


def test_permit_expired_outranks_the_winery_volume_limit_and_flips_the_permit(api):
    """The lapsed permit is recorded, the order is terminally REJECTED, permit EXPIRED.

    PRD §3.6: "The logical clock date must fall inside the permit's closed window
    — on or after `effective_date` and on or before `expiration_date`, both
    endpoints inclusive." and "Outside it, the outcome is `ERR_PERMIT_EXPIRED`,
    and if the lapse is being noticed for the first time the permit is driven
    `ACTIVE` → `EXPIRED` first, before the identifier is recorded."

    PRD §3.2: "Whenever the logical clock date has moved strictly past an `ACTIVE`
    permit's `expiration_date`, that permit is driven `ACTIVE` → `EXPIRED` — its
    `status` becomes `EXPIRED` and its `version` increments by 1 — at the moment
    the system next looks at it, which happens during order screening, during a
    wine-club run, and when the renewal calendar is rendered."

    Design: Difficulty/priority_pair_validation_conflict/permit_expired_beats_winery_volume_limit
    """
    scape = _lapsed_permit_landscape(api)
    order = scape.create_order()

    before = scape.read_permit()
    assert before["status"] == "ACTIVE", (
        "reading a permit is not one of the three observation points of PRD 3.2, "
        "so the lapse must still be unnoticed when the screen runs"
    )

    screened = validate_success(api.screen_order(order["id"], {}, OFFICER_A), 200)

    assert_liters(screened["total_liters"], 4.500, "total_liters")
    assert_rejection(screened, "ERR_PERMIT_EXPIRED")
    assert_order_dimensions(
        screened, compliance_status="REJECTED", fulfillment_status="UNFULFILLED"
    )
    assert screened["compliance_status"] != "OVERRIDE_PENDING", (
        "had the overridable winery volume rule been evaluated first the order "
        "would have been parked for review instead of rejected"
    )

    after = scape.read_permit()
    assert after["status"] == "EXPIRED"
    assert after["version"] == before["version"] + 1

    rows = scape.ledger_rows(winery_id=scape.winery_id)
    assert len(rows) == 0, f"A rejected screen appends no ledger entry: {rows}"
    assert scape.read_winery()["excise_accrued_cents"] == 0


def test_winery_volume_limit_surfaces_once_the_permit_is_still_in_force(api):
    """With an unlapsed permit the same 1.000 L ceiling parks the order for review.

    PRD §3.6: "The winery's calendar-year accumulated liters into the destination
    state plus this order's `total_liters` must be at most the state's
    `per_winery_annual_limit_liters`." and "Equality clears; exceeding fails with
    `ERR_WINERY_VOLUME_LIMIT_EXCEEDED`."

    PRD §3.6: "If the highest-ranked failing check *is* one of
    `ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED`, `ERR_WINERY_VOLUME_LIMIT_EXCEEDED` or
    `ERR_ELEVATED_RISK_REVIEW_REQUIRED`, the order moves to `OVERRIDE_PENDING`,
    which is an invitation to the exception workflow rather than a refusal."

    Design: Difficulty/priority_pair_validation_conflict/permit_expired_beats_winery_volume_limit
    """
    scape = build_landscape(
        api,
        clock=CLOCK_AUG_1,
        state_rule_overrides={"per_winery_annual_limit_liters": 1.000},
    )
    order = scape.create_order()

    screened = validate_success(api.screen_order(order["id"], {}, OFFICER_A), 200)

    assert_rejection(screened, "ERR_WINERY_VOLUME_LIMIT_EXCEEDED")
    assert_order_dimensions(
        screened, compliance_status="OVERRIDE_PENDING", fulfillment_status="UNFULFILLED"
    )
    assert scape.read_permit()["status"] == "ACTIVE"

    rows = scape.ledger_rows(winery_id=scape.winery_id)
    assert len(rows) == 0, f"An OVERRIDE_PENDING screen reserves no liters: {rows}"
    assert scape.read_winery()["excise_accrued_cents"] == 0
