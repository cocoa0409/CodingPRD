"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints —
the server seeds nothing, and the database is empty at the start of every test. Setup
calls use get_success_data()/validate_paginated() so a broken precondition surfaces as a
clear "Setup step failed" rather than a confusing downstream assertion error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .test_users import TEST_USERS, make_parcel_owner_headers
from .factories import (
    create_district_payload,
    create_parcel_payload,
    create_roll_payload,
    create_bond_payload,
    subdivide_payload,
    create_payment_payload,
    create_payoff_quote_payload,
    advance_foreclosure_payload,
    set_clock_payload,
)


def _admin():
    return TEST_USERS["admin_headers"]


def _treasurer():
    return TEST_USERS["treasurer_headers"]


def _auditor():
    return TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def create_district(api, name="Test District", formation_method="BENEFIT_UNITS",
                    total_project_cost_cents=1_000_000, **overrides):
    payload = create_district_payload(
        name=name, formation_method=formation_method,
        total_project_cost_cents=total_project_cost_cents, **overrides,
    )
    return get_success_data(api.create_district(payload, _admin()))


def add_parcel(api, district_id, apn, owner_name="Owner", **weights):
    payload = create_parcel_payload(apn=apn, owner_name=owner_name, **weights)
    return get_success_data(api.create_parcel(district_id, payload, _admin()))


def open_protest(api, district_id):
    return get_success_data(api.open_protest(district_id, _admin()))


def close_hearing(api, district_id):
    return get_success_data(api.close_hearing(district_id, _admin()))


def form_district(api, district_id):
    """Open the protest period then close the hearing with no protests → FORMED."""
    open_protest(api, district_id)
    return close_hearing(api, district_id)


def create_roll(api, district_id, method=None):
    payload = create_roll_payload(**({"method": method} if method else {}))
    return get_success_data(api.create_roll(district_id, payload, _admin()))


def confirm_roll(api, roll_id):
    return get_success_data(api.confirm_roll(roll_id, _admin()))


def authorize_bond(api, district_id, issuance_date="2026-07-01T00:00:00Z", **overrides):
    payload = create_bond_payload(issuance_date=issuance_date, **overrides)
    return get_success_data(api.create_bond(district_id, payload, _admin()))


def issue_bond(api, bond_id):
    return get_success_data(api.issue_bond(bond_id, _admin()))


def set_clock(api, iso, headers=None):
    return api.set_clock(set_clock_payload(iso), headers or _admin())


# ---------------------------------------------------------------------------
# Read / refresh helpers (many entities have no GET /{entity}/{id} route, so they
# are fetched via the parent-scoped list endpoints and located by id).
# ---------------------------------------------------------------------------
def refresh_parcel(api, parcel_id):
    return get_success_data(api.get_parcel(parcel_id, _auditor()))


def refresh_installment(api, installment_id):
    return get_success_data(api.get_installment(installment_id, _auditor()))


def get_bond(api, district_id, bond_id):
    data, _ = validate_paginated(api.list_bonds(district_id, _auditor(), params={"limit": 100}))
    for b in data:
        if b["id"] == bond_id:
            return b
    raise AssertionError(f"bond {bond_id} not found in district {district_id}")


def get_roll(api, district_id, roll_id):
    data, _ = validate_paginated(api.list_rolls(district_id, _auditor(), params={"limit": 100}))
    for r in data:
        if r["id"] == roll_id:
            return r
    raise AssertionError(f"roll {roll_id} not found in district {district_id}")


def get_foreclosure(api, parcel_id, foreclosure_id):
    data, _ = validate_paginated(api.list_foreclosures(parcel_id, _auditor(), params={"limit": 100}))
    for f in data:
        if f["id"] == foreclosure_id:
            return f
    raise AssertionError(f"foreclosure {foreclosure_id} not found on parcel {parcel_id}")


def list_parcel_installments(api, parcel_id):
    """All installments of a parcel, ordered created_at ascending (i.e. year order)."""
    data, _ = validate_paginated(
        api.list_installments(_auditor(), params={"parcel_id": parcel_id, "limit": 100})
    )
    return data


def get_parcel_installment(api, parcel_id, installment_year):
    data, _ = validate_paginated(
        api.list_installments(
            _auditor(),
            params={"parcel_id": parcel_id, "installment_year": installment_year, "limit": 100},
        )
    )
    assert data, f"no installment year {installment_year} for parcel {parcel_id}"
    return data[0]


def list_parcel_liens(api, parcel_id, **filters):
    params = {"limit": 100}
    params.update(filters)
    data, _ = validate_paginated(api.list_liens(parcel_id, _auditor(), params=params))
    return data


def list_parcel_children(api, parent_parcel_id):
    data, _ = validate_paginated(
        api.list_parcels(_auditor(), params={"parent_parcel_id": parent_parcel_id, "limit": 100})
    )
    return data


def parcel_version(api, parcel_id):
    return refresh_parcel(api, parcel_id)["version"]


# ---------------------------------------------------------------------------
# Composite lifecycle fixtures
# ---------------------------------------------------------------------------
def setup_formed_district(api, parcels, formation_method="BENEFIT_UNITS",
                          total_project_cost_cents=1_000_000, protest_threshold_pct=None,
                          name="Test District", **district_overrides):
    """Create a district, add each parcel, then form it (open-protest + close-hearing
    with no protests → FORMED).

    parcels: list of dicts, each passed as kwargs to add_parcel (apn, owner_name, weights).
    Returns (district_dict, [parcel_dict, ...]) with parcels in creation order.
    """
    ov = dict(district_overrides)
    if protest_threshold_pct is not None:
        ov["protest_threshold_pct"] = protest_threshold_pct
    district = create_district(
        api, name=name, formation_method=formation_method,
        total_project_cost_cents=total_project_cost_cents, **ov,
    )
    created = [add_parcel(api, district["id"], **spec) for spec in parcels]
    form_district(api, district["id"])
    district = get_success_data(api.get_district(district["id"], _auditor()))
    return district, created


def setup_confirmed_roll(api, parcels, formation_method="BENEFIT_UNITS",
                         total_project_cost_cents=1_000_000, roll_method=None,
                         name="Test District", **district_overrides):
    """Formed district + a DRAFT roll confirmed (apportionment run, ASSESSMENT liens
    recorded). Returns (district, [parcels refreshed], roll)."""
    district, created = setup_formed_district(
        api, parcels, formation_method, total_project_cost_cents,
        name=name, **district_overrides,
    )
    roll = create_roll(api, district["id"], method=roll_method)
    confirm_roll(api, roll["id"])
    refreshed = [refresh_parcel(api, p["id"]) for p in created]
    roll = get_roll(api, district["id"], roll["id"])
    district = get_success_data(api.get_district(district["id"], _auditor()))
    return district, refreshed, roll


def setup_issued_bond(api, parcels, formation_method="BENEFIT_UNITS",
                      total_project_cost_cents=1_000_000, roll_method=None,
                      bond=None, name="Test District", **district_overrides):
    """Formed district + confirmed roll + an ISSUED bond (per-parcel installment
    schedule generated). Returns (district, [parcels refreshed], roll, bond).

    bond: optional dict of bond overrides (issuance_date, coupon_rate_bps, term_years, ...).
    """
    district, refreshed, roll = setup_confirmed_roll(
        api, parcels, formation_method, total_project_cost_cents, roll_method,
        name=name, **district_overrides,
    )
    bond_entity = authorize_bond(api, district["id"], **(bond or {}))
    issue_bond(api, bond_entity["id"])
    bond_entity = get_bond(api, district["id"], bond_entity["id"])
    refreshed = [refresh_parcel(api, p["id"]) for p in refreshed]
    return district, refreshed, roll, bond_entity


def pay_installment(api, installment_id, amount_cents, payment_date, paid_by="Owner", headers=None):
    payload = create_payment_payload(amount_cents=amount_cents, payment_date=payment_date, paid_by=paid_by)
    return get_success_data(api.create_payment(installment_id, payload, headers or _treasurer()))


def mark_all_delinquent(api, parcel_id):
    """Mark every currently-DUE installment of a parcel DELINQUENT (treasurer action).
    Returns the list of installment ids marked."""
    marked = []
    for inst in list_parcel_installments(api, parcel_id):
        get_success_data(api.mark_delinquent(inst["id"], _treasurer()))
        marked.append(inst["id"])
    return marked


def setup_foreclosure_at_judgment(api):
    """Single-parcel district taken all the way to a foreclosure in JUDGMENT status.

    District cost 300000, one parcel (benefit_units 100), roll confirmed, a 3-year bond
    issued at 2026-07-01; clock advanced to 2029-09-01 so all three installments are past
    due + grace; all three marked DELINQUENT; foreclosure initiated then advanced through
    NOTICED to JUDGMENT.

    Returns (district, parcel, bond, foreclosure, [installments]).
    """
    district, parcels, roll, bond = setup_issued_bond(
        api,
        parcels=[{"apn": "F-1", "owner_name": "OF", "benefit_units": 100}],
        total_project_cost_cents=300_000,
        bond={"issuance_date": "2026-07-01T00:00:00Z", "coupon_rate_bps": 500,
              "term_years": 3, "reserve_fund_pct": 0.10},
    )
    parcel = parcels[0]
    set_clock(api, "2029-09-01T00:00:00Z")
    mark_all_delinquent(api, parcel["id"])
    foreclosure = get_success_data(api.create_foreclosure(parcel["id"], _admin()))
    get_success_data(api.advance_foreclosure(foreclosure["id"], advance_foreclosure_payload("NOTICED"), _admin()))
    get_success_data(api.advance_foreclosure(foreclosure["id"], advance_foreclosure_payload("JUDGMENT"), _admin()))
    foreclosure = get_foreclosure(api, parcel["id"], foreclosure["id"])
    installments = list_parcel_installments(api, parcel["id"])
    parcel = refresh_parcel(api, parcel["id"])
    return district, parcel, bond, foreclosure, installments


def create_payoff_quote(api, parcel_id, quote_mode, quote_date, expected_parcel_version, headers=None):
    payload = create_payoff_quote_payload(
        quote_mode=quote_mode, quote_date=quote_date,
        expected_parcel_version=expected_parcel_version,
    )
    return api.create_payoff_quote(parcel_id, payload, headers or _treasurer())
