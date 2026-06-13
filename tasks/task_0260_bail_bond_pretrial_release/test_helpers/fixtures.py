"""Composite setup helpers for the Bail Bond & Pretrial Release API.

Every test runs against a fresh, empty database (the harness restarts the server
before each test). These helpers build the multi-step preconditions each test
needs, using only PRD-declared endpoints. They use the lenient get_success_data()
validator internally, so a broken setup step surfaces as a clear failure rather
than a confusing assertion later.

All five roles are opaque (PRD §2.1); X-User-ID is never an entity id. The only
cross-operation use of X-User-ID is segregation of duties on exoneration: the
activating BondsAgent id is retained and compared against the exonerating
ComplianceOfficer id. The default BondsAgent (agent-1) and ComplianceOfficer
(officer-1) ids differ, so the default exoneration path passes SoD; helpers that
need to force same-user expose explicit user-id parameters.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_bonds_agent_headers, make_court_headers,
    make_compliance_officer_headers, make_recovery_agent_headers,
    make_system_admin_headers,
)
from . import factories

AGENT = TEST_USERS["bonds_agent_headers"]
COURT = TEST_USERS["court_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
RECOVERY = TEST_USERS["recovery_agent_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


# ===========================================================================
# Low-level building blocks
# ===========================================================================
def pin_clock(to_iso8601: str):
    """Pin the server's logical UTC clock (PRD §3.9)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, ADMIN))


def create_defendant(**overrides) -> dict:
    return get_success_data(
        api_client.create_defendant(factories.create_defendant_payload(**overrides), AGENT)
    )


def create_bail_order(defendant_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bail_order(
            defendant_id, factories.create_bail_order_payload(**overrides), COURT
        )
    )


def create_bond(defendant_id, order_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bond(
            defendant_id, order_id, factories.create_bond_payload(**overrides), AGENT
        )
    )


def create_indemnitor(**overrides) -> dict:
    return get_success_data(
        api_client.create_indemnitor(factories.create_indemnitor_payload(**overrides), AGENT)
    )


def attach_indemnity(defendant_id, bond_id, indemnitor_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_indemnity_agreement(
            defendant_id, bond_id,
            factories.create_indemnity_agreement_payload(indemnitor_id, **overrides),
            AGENT,
        )
    )


def pledge_collateral(defendant_id, bond_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_collateral(
            defendant_id, bond_id, factories.create_collateral_payload(**overrides), AGENT
        )
    )


def schedule_court_date(defendant_id, bond_id, scheduled_utc, **overrides) -> dict:
    return get_success_data(
        api_client.create_court_date(
            defendant_id, bond_id,
            factories.create_court_date_payload(scheduled_utc, **overrides),
            COURT,
        )
    )


def get_bond(bond_id) -> dict:
    return get_success_data(api_client.get_bond(bond_id, OFFICER))


def bond_version(bond_id) -> int:
    return get_bond(bond_id)["version"]


def get_proceeding_for_bond(bond_id) -> dict:
    """Return the (first / only) forfeiture proceeding for a bond."""
    data, _ = _paginated(api_client.list_bond_forfeitures(bond_id, OFFICER))
    assert data, f"expected a forfeiture proceeding for bond {bond_id}"
    return data[0]


def get_ledger(bond_id) -> list:
    data, _ = _paginated(api_client.list_ledger(bond_id, OFFICER))
    return data


def get_collateral_list(bond_id) -> list:
    data, _ = _paginated(api_client.list_collateral(bond_id, OFFICER))
    return data


def get_indemnity_list(bond_id) -> list:
    data, _ = _paginated(api_client.list_bond_indemnity_agreements(bond_id, OFFICER))
    return data


def _paginated(response):
    """Lenient extraction of (data_list, meta) from a list response."""
    body = response.json()
    return body["data"], body.get("meta", {})


# ===========================================================================
# Tier 1 + 2: DRAFT bond with full indemnity + collateral
# ===========================================================================
def setup_draft_surety_bond(
    bail_amount_cents=1_000_000,
    risk_tier="MEDIUM",
    premium_rate_bps=1000,
    liability_share_cents=None,
    collateral_value_cents=250_000,
    gps_required=False,
    condition_codes=None,
    with_indemnity=True,
    with_collateral=True,
    bond_type_allowed="SURETY",
    agent_user_id="agent-1",
):
    """Create defendant + bail order + DRAFT SURETY bond, optionally fully
    indemnified and collateralized so it can later activate cleanly.

    Returns a dict with keys: defendant, order, bond, indemnitor, agreement,
    collateral, def_id, order_id, bond_id, agent (the BondsAgent headers used,
    so the same identity can drive activation for SoD purposes).
    """
    agent = make_bonds_agent_headers(agent_user_id)
    order_overrides = {
        "bail_amount_cents": bail_amount_cents,
        "bond_type_allowed": bond_type_allowed,
        "gps_required": gps_required,
    }
    if condition_codes is not None:
        order_overrides["condition_codes"] = condition_codes

    defendant = get_success_data(
        api_client.create_defendant(
            factories.create_defendant_payload(risk_tier=risk_tier), agent
        )
    )
    order = get_success_data(
        api_client.create_bail_order(
            defendant["id"], factories.create_bail_order_payload(**order_overrides), COURT
        )
    )
    bond = get_success_data(
        api_client.create_bond(
            defendant["id"], order["id"],
            factories.create_bond_payload(bond_type="SURETY", premium_rate_bps=premium_rate_bps),
            agent,
        )
    )

    indemnitor = agreement = collateral = None
    if with_indemnity:
        share = liability_share_cents if liability_share_cents is not None else bail_amount_cents
        # Size the cosigner's credit limit so it always covers the liability share
        # being pledged here; otherwise a large-face bond would trip the PRD's
        # ERR_CREDIT_LIMIT_EXCEEDED gate during setup. The default 5,000,000 is too
        # small for faces above 5,000,000.
        credit_limit = max(share, 5_000_000)
        indemnitor = get_success_data(
            api_client.create_indemnitor(
                factories.create_indemnitor_payload(credit_limit_cents=credit_limit), agent
            )
        )
        agreement = get_success_data(
            api_client.create_indemnity_agreement(
                defendant["id"], bond["id"],
                factories.create_indemnity_agreement_payload(indemnitor["id"], liability_share_cents=share),
                agent,
            )
        )
    if with_collateral:
        collateral = get_success_data(
            api_client.create_collateral(
                defendant["id"], bond["id"],
                factories.create_collateral_payload(pledged_value_cents=collateral_value_cents),
                agent,
            )
        )

    return {
        "defendant": defendant, "order": order, "bond": bond,
        "indemnitor": indemnitor, "agreement": agreement, "collateral": collateral,
        "def_id": defendant["id"], "order_id": order["id"], "bond_id": bond["id"],
        "agent": agent,
    }


def setup_active_surety_bond(**kwargs):
    """setup_draft_surety_bond then activate. Returns the same dict plus the
    activated bond under 'bond' and the activate response under 'activated'."""
    scen = setup_draft_surety_bond(**kwargs)
    activated = get_success_data(
        api_client.activate_bond(scen["def_id"], scen["bond_id"], scen["agent"])
    )
    scen["bond"] = activated
    scen["activated"] = activated
    return scen


# ===========================================================================
# Tier 3: forfeited / recovery / judgment lifecycle
# ===========================================================================
def setup_forfeited_bond(
    forfeit_clock="2026-07-01T00:00:00Z",
    court_date_utc="2026-07-02T09:00:00Z",
    fta_clock="2026-07-02T10:00:00Z",
    **bond_kwargs,
):
    """Active SURETY bond whose only court date has been recorded FTA, driving
    the bond ACTIVE -> FORFEITED and opening a proceeding.

    Returns the setup_active_surety_bond dict plus: court_date, proceeding,
    proc_id, court_date_id.
    """
    pin_clock(forfeit_clock)
    scen = setup_active_surety_bond(**bond_kwargs)
    cd = schedule_court_date(scen["def_id"], scen["bond_id"], court_date_utc)
    pin_clock(fta_clock)
    get_success_data(api_client.record_fta(scen["def_id"], cd["id"], COURT))
    proceeding = get_proceeding_for_bond(scen["bond_id"])
    scen["court_date"] = cd
    scen["court_date_id"] = cd["id"]
    scen["proceeding"] = proceeding
    scen["proc_id"] = proceeding["id"]
    return scen


def setup_recovery_open_bond(**kwargs):
    """Forfeited bond with recovery opened (proceeding RECOVERY_OPEN)."""
    scen = setup_forfeited_bond(**kwargs)
    get_success_data(api_client.open_recovery(scen["def_id"], scen["proc_id"], RECOVERY))
    scen["proceeding"] = get_proceeding_for_bond(scen["bond_id"])
    return scen


def setup_judgment_ready(
    open_recovery=False,
    judgment_clock="2026-08-15T00:00:00Z",
    **kwargs,
):
    """Forfeited bond advanced past the 30-day grace window, ready for judgment.

    If open_recovery is True the proceeding passes through RECOVERY_OPEN first
    (so the judgment will carry the recovery credit). Captures the bond version
    immediately before judgment in 'bond_version_before'.
    """
    if open_recovery:
        scen = setup_recovery_open_bond(**kwargs)
    else:
        scen = setup_forfeited_bond(**kwargs)
    pin_clock(judgment_clock)
    scen["bond_version_before"] = bond_version(scen["bond_id"])
    return scen


def enter_judgment_on(scen, expected_bond_version=None, officer_headers=None):
    """Enter judgment on a judgment-ready scenario. Returns the proceeding."""
    version = expected_bond_version if expected_bond_version is not None else scen["bond_version_before"]
    headers = officer_headers or OFFICER
    return get_success_data(
        api_client.enter_judgment(
            scen["def_id"], scen["proc_id"],
            factories.enter_judgment_payload(version), headers,
        )
    )


# ===========================================================================
# Tier: GPS device assigned / active
# ===========================================================================
def setup_active_bond_with_active_gps(serial_number=None, **kwargs):
    """Active GPS-required SURETY bond with a device ASSIGNED then ACTIVE.

    Returns setup_active_surety_bond dict plus: device, device_id.
    """
    kwargs.setdefault("gps_required", True)
    kwargs.setdefault("condition_codes", ["GPS"])
    scen = setup_active_surety_bond(**kwargs)
    serial = serial_number or factories._next_serial()
    device = get_success_data(
        api_client.create_gps_device(factories.create_gps_device_payload(serial_number=serial), scen["agent"])
    )
    get_success_data(
        api_client.assign_gps(
            scen["def_id"], scen["bond_id"],
            factories.assign_gps_payload(device["id"]), scen["agent"]
        )
    )
    activated_device = get_success_data(
        api_client.activate_gps(scen["def_id"], device["id"], scen["agent"])
    )
    scen["device"] = activated_device
    scen["device_id"] = device["id"]
    return scen


def setup_active_bond_with_assigned_gps(serial_number=None, **kwargs):
    """Active GPS-required SURETY bond with a device only ASSIGNED (not activated).

    Returns setup_active_surety_bond dict plus: device, device_id.
    """
    kwargs.setdefault("gps_required", True)
    scen = setup_active_surety_bond(**kwargs)
    serial = serial_number or factories._next_serial()
    device = get_success_data(
        api_client.create_gps_device(factories.create_gps_device_payload(serial_number=serial), scen["agent"])
    )
    assigned = get_success_data(
        api_client.assign_gps(
            scen["def_id"], scen["bond_id"],
            factories.assign_gps_payload(device["id"]), scen["agent"]
        )
    )
    scen["device"] = assigned
    scen["device_id"] = device["id"]
    return scen
