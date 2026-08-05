"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server (empty DB, clock reset to
2026-05-01T00:00:00Z) before every test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_registrant_headers
from .factories import (
    create_jurisdiction_payload,
    create_exclusion_zone_payload,
    create_registrant_payload,
    create_offense_payload,
    create_address_payload,
    create_verification_payload,
    create_flag_payload,
    create_travel_notice_payload,
    create_notification_payload,
    create_petition_payload,
)

_ADMIN = TEST_USERS["registry_admin_headers"]
_OFFICER = TEST_USERS["registration_officer_headers"]
_REVIEWER = TEST_USERS["compliance_reviewer_headers"]


# --- Primitive builders --------------------------------------------------

def set_clock(iso: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, _ADMIN))


def create_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), _ADMIN)
    )


def create_exclusion_zone(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_exclusion_zone(
            jurisdiction_id, create_exclusion_zone_payload(**overrides), _ADMIN
        )
    )


def create_registrant(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_registrant(
            create_registrant_payload(jurisdiction_id, **overrides), _OFFICER
        )
    )


def add_offense(registrant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_offense(
            registrant_id, create_offense_payload(**overrides), _OFFICER
        )
    )


def activate(registrant_id: str) -> dict:
    return get_success_data(api_client.activate_registrant(registrant_id, _OFFICER))


def add_address(registrant_id: str, expected_registrant_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_address(
            registrant_id,
            create_address_payload(expected_registrant_version, **overrides),
            _OFFICER,
        )
    )


def record_verification(registrant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_verification(
            registrant_id, create_verification_payload(**overrides), _OFFICER
        )
    )


def open_flag(registrant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_flag(
            registrant_id, create_flag_payload(**overrides), _OFFICER
        )
    )


def resolve_flag(flag_id: str) -> dict:
    return get_success_data(api_client.resolve_flag(flag_id, _OFFICER))


def submit_travel(registrant_id: str, destination_jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_travel_notice(
            registrant_id,
            create_travel_notice_payload(destination_jurisdiction_id, **overrides),
            _OFFICER,
        )
    )


def decide_travel(travel_notice_id: str, decision: str, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(api_client.decide_travel_notice(travel_notice_id, payload, _OFFICER))


def file_petition(registrant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_petition(
            registrant_id, create_petition_payload(**overrides), _OFFICER
        )
    )


def get_registrant(registrant_id: str) -> dict:
    return get_success_data(api_client.get_registrant(registrant_id, _OFFICER))


def get_jurisdiction(jurisdiction_id: str) -> dict:
    return get_success_data(api_client.get_jurisdiction(jurisdiction_id, _OFFICER))


def get_petition(petition_id: str) -> dict:
    return get_success_data(api_client.get_petition(petition_id, _REVIEWER))


# --- Composite scenarios -------------------------------------------------

def setup_active_registrant(offense=None, jurisdiction=None,
                            jurisdiction_overrides=None, full_name="Test Subject",
                            date_of_birth="1980-01-01T00:00:00Z"):
    """Jurisdiction + registrant + one offense + activation.

    Returns (jurisdiction, registrant) where the registrant is ACTIVE and
    reflects its post-activation version. Offense defaults to a single CLASS_B
    (tier_score 20 -> TIER_1). Pass offense=dict to control the offense payload.
    """
    jur = jurisdiction or create_jurisdiction(**(jurisdiction_overrides or {}))
    reg = create_registrant(jur["id"], full_name=full_name, date_of_birth=date_of_birth)
    add_offense(reg["id"], **(offense or {}))
    reg = activate(reg["id"])
    return jur, reg


def setup_registrant_with_residence(offense=None, jurisdiction_overrides=None,
                                    grid_x=4000, grid_y=4000, full_name="Res R"):
    """ACTIVE registrant with one VERIFIED RESIDENCE address.

    Returns (jurisdiction, registrant, address). The registrant dict is a fresh
    read after the residence was recorded, so its version reflects that mutation.
    """
    jur, reg = setup_active_registrant(offense=offense,
                                       jurisdiction_overrides=jurisdiction_overrides,
                                       full_name=full_name)
    addr = add_address(reg["id"], reg["version"], grid_x=grid_x, grid_y=grid_y,
                       line1="1 Home Rd")
    reg = get_registrant(reg["id"])
    return jur, reg, addr


def setup_registrant_with_pending_petition(offense=None, jurisdiction_overrides=None):
    """ACTIVE registrant with one PENDING DEREGISTER petition.

    Returns (jurisdiction, registrant, petition).
    """
    jur, reg = setup_active_registrant(offense=offense,
                                       jurisdiction_overrides=jurisdiction_overrides)
    pet = file_petition(reg["id"], petition_type="DEREGISTER")
    return jur, reg, pet


def setup_submitted_travel(offense=None, dest_status="ACTIVE",
                           departure="2026-06-01T00:00:00Z",
                           return_date="2026-06-10T00:00:00Z"):
    """ACTIVE registrant in home jurisdiction + a SUBMITTED TEMPORARY travel
    notice to a separate destination jurisdiction.

    Returns (home_jur, dest_jur, registrant, travel_notice).
    """
    home = create_jurisdiction(name="Home", state_code="CA")
    dest = create_jurisdiction(name="Dest", state_code="NV", status=dest_status)
    reg = create_registrant(home["id"], full_name="Trav T")
    add_offense(reg["id"], **(offense or {}))
    reg = activate(reg["id"])
    tn = submit_travel(reg["id"], dest["id"], departure_date=departure, return_date=return_date)
    return home, dest, reg, tn


def setup_approved_travel(offense=None,
                          departure="2026-06-01T00:00:00Z",
                          return_date="2026-06-10T00:00:00Z"):
    """ACTIVE registrant + APPROVED TEMPORARY travel notice to an ACTIVE
    destination (destination hold_count == 1).

    Returns (home_jur, dest_jur, registrant, travel_notice).
    """
    home, dest, reg, tn = setup_submitted_travel(
        offense=offense, departure=departure, return_date=return_date)
    decide_travel(tn["id"], "APPROVE")
    return home, dest, reg, tn
