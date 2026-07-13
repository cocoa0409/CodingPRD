"""Re-entry access credential activation preconditions (zone posture and validity window)."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_active_incident, create_zone, order_zone, create_registrant, create_credential,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_credential_activate_zone_not_reentry_rejected(api):
    """PRD 3.6: "Activating a credential — moving `ISSUED → ACTIVE`, or reactivating `SUSPENDED → ACTIVE` — requires the owning zone to be at `order_level` `RE_ENTRY_ALLOWED` (else `ERR_ZONE_NOT_REENTRY`) and the current clock to fall within the validity window, `valid_from_utc` at or before now and now strictly before `valid_until_utc` (else `ERR_CREDENTIAL_WINDOW_INVALID`)."

    Design: Corner/state_machines/credential_activate_zone_not_reentry_rejected
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    reg = create_registrant(zone["id"], party_size=2)
    order_zone(zone["id"], "MANDATORY")
    cred = create_credential(zone["id"], reg["id"],
                             valid_from_utc="2026-02-01T00:00:00Z",
                             valid_until_utc="2026-12-01T00:00:00Z")

    resp = api.set_access_credential_status(cred["id"], {"state": "ACTIVE"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_REENTRY)


def test_credential_activate_outside_window_rejected(api):
    """PRD 3.6: "Activating a credential — moving `ISSUED → ACTIVE`, or reactivating `SUSPENDED → ACTIVE` — requires the owning zone to be at `order_level` `RE_ENTRY_ALLOWED` (else `ERR_ZONE_NOT_REENTRY`) and the current clock to fall within the validity window, `valid_from_utc` at or before now and now strictly before `valid_until_utc` (else `ERR_CREDENTIAL_WINDOW_INVALID`)."

    Design: Corner/state_machines/credential_activate_outside_window_rejected
    """
    inc = create_active_incident(name="Delta Flood", jurisdiction="Sacramento", hazard_type="FLOOD")
    zone = create_zone(inc["id"])
    reg = create_registrant(zone["id"], party_size=2)
    order_zone(zone["id"], "MANDATORY")
    order_zone(zone["id"], "RE_ENTRY_ALLOWED")
    # Future validity window while the clock is at the default 2026-03-01T00:00:00Z.
    cred = create_credential(zone["id"], reg["id"],
                             valid_from_utc="2026-06-01T00:00:00Z",
                             valid_until_utc="2026-07-01T00:00:00Z")

    resp = api.set_access_credential_status(cred["id"], {"state": "ACTIVE"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_WINDOW_INVALID)
