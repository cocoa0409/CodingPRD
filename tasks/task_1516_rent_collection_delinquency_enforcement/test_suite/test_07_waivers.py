"""Waivers: state and fiscal guards, the monthly cap boundary, segregation of
duties, and the state-vs-fiscal priority pair."""
from test_helpers import (
    ApiErrorId,
    add_charge,
    list_charges,
    post_payment,
    record_payment,
    setup_property_tenant_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_property_manager_headers

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_waiver_exceeds_outstanding_rejected(api):
    """PRD 3.5: "And two fiscal limits apply, evaluated in order: the requested amount
    must not exceed the charge's outstanding balance (`ERR_WAIVER_EXCEEDS_OUTSTANDING`),
    and the waiver must fit within the property's calendar-month waiver budget
    (`ERR_WAIVER_CAP_EXCEEDED`)."

    Design: Corner/validations/waiver_exceeds_outstanding_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    response = api.waive_charge(charge["id"], {"amount_cents": 10001, "reason": "over the line"}, PM)
    validate_error(response, ApiErrorId.ERR_WAIVER_EXCEEDS_OUTSTANDING)

    reread = [c for c in list_charges(lease_id) if c["id"] == charge["id"]][0]
    assert reread["status"] == "OPEN"
    assert reread["outstanding_cents"] == 10000
    assert reread["waived_cents"] == 0


def test_waiver_monthly_cap_boundary(api):
    """PRD 3.5: "The monthly budget is computed across the whole property: the sum of
    all cents waived in the current calendar month, by the server's logical clock,
    across every charge of every lease belonging to the charge's property, plus the
    requested amount, must not exceed the property's `monthly_waiver_cap_cents`. A
    request that lands the month total exactly on the cap is permitted; only exceeding
    it fails."

    Design: Corner/calculations/waiver_monthly_cap_boundary
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    big = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=20000)
    small = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=5000)

    waived = validate_success(
        api.waive_charge(big["id"], {"amount_cents": 20000, "reason": "storm damage goodwill"}, PM)
    )
    assert waived["status"] == "WAIVED", "A month total landing exactly on the 20000 cap is permitted"

    response = api.waive_charge(small["id"], {"amount_cents": 1, "reason": "one cent over"}, PM)
    validate_error(response, ApiErrorId.ERR_WAIVER_CAP_EXCEEDED)


def test_waiver_creator_segregation_rejected(api):
    """PRD 3.5: "Segregation of duties forbids self-forgiveness: the caller's
    `X-User-ID` must differ from the charge's `created_by_user_id`, or the request is
    rejected with `ERR_SEGREGATION_OF_DUTIES` — charges created by the system itself,
    whose creator is the literal `system`, may be waived by any property manager."

    Design: Corner/validations/waiver_creator_segregation_rejected
    """
    pm1 = make_property_manager_headers("pm-1")
    pm2 = make_property_manager_headers("pm-2")
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, headers=pm1, kind="DAMAGE_FEE", amount_cents=8000)
    assert charge["created_by_user_id"] == "pm-1"

    response = api.waive_charge(charge["id"], {"amount_cents": 8000, "reason": "self waiver"}, pm1)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    waived = validate_success(
        api.waive_charge(charge["id"], {"amount_cents": 8000, "reason": "peer waiver"}, pm2)
    )
    assert waived["status"] == "WAIVED"


def test_waive_on_waived_charge_rejected(api):
    """PRD 3.5: "The target charge must be `OPEN` or `PARTIALLY_PAID`; waiving a
    charge that is `PAID`, `WAIVED`, or `VOID` is rejected with
    `ERR_CHARGE_NOT_WAIVABLE`."

    Design: Corner/state_machines/waive_on_waived_charge_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    waived = validate_success(api.waive_charge(charge["id"], {"amount_cents": 10000, "reason": "goodwill"}, PM))
    assert waived["status"] == "WAIVED"

    response = api.waive_charge(charge["id"], {"amount_cents": 1, "reason": "double waive probe"}, PM)
    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_WAIVABLE)


def test_waive_state_beats_fiscal_cap(api):
    """PRD 2.9: "Every request is evaluated against an ordered validation pipeline.
    The first failing check produces the error response; later checks are not
    evaluated."
    PRD 2.9 rule 7: "... a waiver target charge must be `OPEN` or `PARTIALLY_PAID`
    (`ERR_CHARGE_NOT_WAIVABLE`)."
    PRD 2.9 rule 16: "The waived amount must not exceed the charge's outstanding
    balance (`ERR_WAIVER_EXCEEDS_OUTSTANDING`), and the property's calendar-month
    waiver total must remain within its cap (`ERR_WAIVER_CAP_EXCEEDED`), evaluated in
    that order."

    Design: Difficulty/priority_pair_validation_conflict/waive_state_beats_fiscal_cap
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=20000)
    rent = add_charge(lease_id, amount_cents=200000)

    # Exhaust the 20000 monthly waiver cap.
    waived = validate_success(api.waive_charge(damage["id"], {"amount_cents": 20000, "reason": "goodwill"}, PM))
    assert waived["status"] == "WAIVED"

    # Drive the rent charge to PAID (a non-waivable state).
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=200000)
    post_payment(payment["id"])

    # Double failure: PAID target (state) AND exhausted month cap (fiscal); state wins.
    response = api.waive_charge(rent["id"], {"amount_cents": 1, "reason": "double failure probe"}, PM)
    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_WAIVABLE)


def test_waive_state_beats_fiscal_outstanding(api):
    """PRD 2.9: "Every request is evaluated against an ordered validation pipeline.
    The first failing check produces the error response; later checks are not
    evaluated."
    PRD 2.9 rule 7: "... a waiver target charge must be `OPEN` or `PARTIALLY_PAID`
    (`ERR_CHARGE_NOT_WAIVABLE`)."
    PRD 2.9 rule 16: "The waived amount must not exceed the charge's outstanding
    balance (`ERR_WAIVER_EXCEEDS_OUTSTANDING`), and the property's calendar-month
    waiver total must remain within its cap (`ERR_WAIVER_CAP_EXCEEDED`), evaluated in
    that order."

    Design: Difficulty/priority_pair_validation_conflict/waive_state_beats_fiscal_cap
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)

    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=200000)
    post_payment(payment["id"])

    # Double failure: PAID target (state, priority 7) AND amount above the now-zero
    # outstanding (fiscal, priority 16); the state check fires first.
    response = api.waive_charge(rent["id"], {"amount_cents": 5, "reason": "double failure probe"}, PM)
    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_WAIVABLE)
