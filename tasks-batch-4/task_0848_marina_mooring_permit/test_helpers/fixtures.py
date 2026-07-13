"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server is restarted (empty DB) before every test. Setup
calls use the lenient get_success_data() validator so a setup break surfaces as
a clear "Setup failed" rather than an assertion error.

Setup runs as Harbormaster, which the PRD authorizes for every shared operation
on any resource. Ownership-gated Boater flows are threaded explicitly in tests
via make_boater_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS
from . import factories as f

HARBOR = TEST_USERS["harbormaster_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(api, iso, headers=HARBOR):
    return api.set_clock(iso, headers)


def create_marina(api, headers=HARBOR, **overrides) -> dict:
    return get_success_data(api.create_marina(f.create_marina_payload(**overrides), headers))


def create_berth(api, marina_id, headers=HARBOR, **overrides) -> dict:
    return get_success_data(
        api.create_berth(f.create_berth_payload(marina_id, **overrides), headers)
    )


def create_boater(api, headers=HARBOR, **overrides) -> dict:
    return get_success_data(api.create_boater(f.create_boater_payload(**overrides), headers))


def create_vessel(api, boater_id, headers=HARBOR, **overrides) -> dict:
    return get_success_data(
        api.create_vessel(f.create_vessel_payload(boater_id, **overrides), headers)
    )


def apply_permit(api, marina_id, boater_id, vessel_id, headers=HARBOR, **overrides) -> dict:
    return get_success_data(
        api.create_permit(
            f.create_permit_payload(marina_id, boater_id, vessel_id, **overrides), headers
        )
    )


def pay(api, invoice_id, amount_cents, headers=HARBOR) -> dict:
    return get_success_data(api.pay_invoice(invoice_id, {"amount_cents": amount_cents}, headers))


def get_permit(api, permit_id, headers=HARBOR) -> dict:
    return get_success_data(api.get_permit(permit_id, headers))


def get_invoice(api, invoice_id, headers=HARBOR) -> dict:
    return get_success_data(api.get_invoice(invoice_id, headers))


def get_berth(api, berth_id, headers=HARBOR) -> dict:
    return get_success_data(api.get_berth(berth_id, headers))


def get_marina(api, marina_id, headers=HARBOR) -> dict:
    return get_success_data(api.get_marina(marina_id, headers))


def get_vessel(api, vessel_id, headers=HARBOR) -> dict:
    return get_success_data(api.get_vessel(vessel_id, headers))


# ---------------------------------------------------------------------------
# Tier 1/2: a boater + a registered vessel
# ---------------------------------------------------------------------------
def setup_boater_with_vessel(
    api, clock=None, boater_overrides=None, vessel_overrides=None
) -> dict:
    if clock:
        set_clock(api, clock)
    boater = create_boater(api, **(boater_overrides or {}))
    vessel = create_vessel(api, boater["id"], **(vessel_overrides or {}))
    return {"boater": boater, "vessel": vessel}


# ---------------------------------------------------------------------------
# Tier 2/3: an OFFERED permit on a reserved berth
# ---------------------------------------------------------------------------
def setup_offered_permit(
    api,
    clock=None,
    marina_overrides=None,
    berth_overrides=None,
    boater_overrides=None,
    vessel_overrides=None,
    permit_overrides=None,
) -> dict:
    """Marina + one AVAILABLE berth + registered vessel + an OFFERED permit
    (berth RESERVED, provisional invoice issued). Returns all ids/objects."""
    if clock:
        set_clock(api, clock)
    marina = create_marina(api, **(marina_overrides or {}))
    berth = create_berth(api, marina["id"], **(berth_overrides or {}))
    boater = create_boater(api, **(boater_overrides or {}))
    vessel = create_vessel(api, boater["id"], **(vessel_overrides or {}))
    permit = apply_permit(
        api, marina["id"], boater["id"], vessel["id"], **(permit_overrides or {})
    )
    return {
        "marina": marina,
        "berth": berth,
        "boater": boater,
        "vessel": vessel,
        "permit": permit,
        "invoice_id": permit.get("invoice_id"),
    }


# ---------------------------------------------------------------------------
# Tier 3: an ACTIVE permit (offer paid in full)
# ---------------------------------------------------------------------------
def setup_active_permit(
    api,
    clock=None,
    activate_clock=None,
    marina_overrides=None,
    berth_overrides=None,
    boater_overrides=None,
    vessel_overrides=None,
    permit_overrides=None,
) -> dict:
    """OFFERED permit, then pay its provisional invoice in full → ACTIVE.

    If activate_clock is given, the clock is advanced to it before paying so the
    activation date (and prorated final fee) land on that instant.
    Returns the setup bundle plus the refreshed ACTIVE permit and its invoice.
    """
    bundle = setup_offered_permit(
        api,
        clock=clock,
        marina_overrides=marina_overrides,
        berth_overrides=berth_overrides,
        boater_overrides=boater_overrides,
        vessel_overrides=vessel_overrides,
        permit_overrides=permit_overrides,
    )
    if activate_clock:
        set_clock(api, activate_clock)
    invoice_id = bundle["invoice_id"]
    amount = bundle["permit"]["provisional_fee_cents"]
    pay(api, invoice_id, amount)
    bundle["permit"] = get_permit(api, bundle["permit"]["id"])
    bundle["invoice"] = get_invoice(api, invoice_id)
    return bundle


def permit_version(api, permit_id) -> int:
    return get_permit(api, permit_id)["version"]


# ---------------------------------------------------------------------------
# Tier 4: derelict report served (ready to close)
# ---------------------------------------------------------------------------
def setup_served_derelict(api, clock, vessel_id) -> dict:
    """File a derelict report on vessel_id and serve notice. Returns the report
    (NOTICE_SERVED) and its DERELICT invoice id."""
    set_clock(api, clock)
    report = get_success_data(
        api.create_derelict_report(f.create_derelict_report_payload(vessel_id), HARBOR)
    )
    served = get_success_data(api.serve_notice(report["id"], HARBOR))
    return {"report": served, "invoice_id": served.get("invoice_id")}


# ---------------------------------------------------------------------------
# Tier 5: an OPEN lottery round with entries
# ---------------------------------------------------------------------------
def setup_open_round(api, clock, marina_overrides=None, round_overrides=None) -> dict:
    """Marina + one SLIP berth + an OPEN lottery round awarding that berth."""
    set_clock(api, clock)
    marina = create_marina(api, **(marina_overrides or {}))
    berth = create_berth(api, marina["id"])
    rnd = get_success_data(
        api.create_lottery_round(
            f.create_lottery_round_payload(marina["id"], [berth["id"]], **(round_overrides or {})),
            HARBOR,
        )
    )
    return {"marina": marina, "berth": berth, "round": rnd}


def enter_lottery(api, round_id, boater_id, vessel_id) -> dict:
    return get_success_data(
        api.create_lottery_entry(
            f.create_lottery_entry_payload(round_id, boater_id, vessel_id), HARBOR
        )
    )
