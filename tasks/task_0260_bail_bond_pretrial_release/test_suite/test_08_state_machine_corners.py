"""Corner: state-machine invalid transitions, terminal lockdown, idempotency,
notify side effect, and the revoke discharge/release cascade.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    setup_active_surety_bond, setup_draft_surety_bond,
    pin_clock,
    TEST_USERS,
)

COURT = TEST_USERS["court_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# Corner/state_machines/revoke_already_active_bond_invalid_state
def test_revoke_active_bond_invalid_state(api):
    """PRD 3.2: "Revoking a `DRAFT` bond advances it `DRAFT → REVOKED`; revocation
    is defined only from `DRAFT`, and an attempt from any other status is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/revoke_already_active_bond_invalid_state
    """
    scen = setup_active_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    resp = api.revoke_bond(scen["def_id"], scen["bond_id"], scen["agent"])
    validate_error(resp, "ERR_INVALID_STATE")


# Corner/state_machines/terminal_appeared_court_date_locked
def test_record_fta_on_appeared_court_date_invalid_state(api):
    """PRD 3.5: "Of these outcomes, `APPEARED` and `CONTINUED` are terminal
    appearance results."
    PRD 3.5: "Recording a failure to appear advances the date to
    `FAILED_TO_APPEAR`; this is allowed when the date is `SCHEDULED` or `NOTIFIED`."

    An already-APPEARED date is terminal, so record-fta -> ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_appeared_court_date_locked
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_active_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    cd = get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-10T09:00:00Z", "duration_minutes": 60}, COURT))
    get_success_data(api_client.record_appearance(scen["def_id"], cd["id"], COURT))
    pin_clock("2026-07-11T00:00:00Z")
    resp = api.record_fta(scen["def_id"], cd["id"], COURT)
    validate_error(resp, "ERR_INVALID_STATE")


# Corner/state_machines/notify_side_effect_creates_notification_with_lead
def test_notify_advances_state_and_records_lead_hours(api):
    """PRD 3.5: "Dispatching a notification is the `Court`'s reminder action and
    advances the date `SCHEDULED → NOTIFIED`."
    PRD 3.5: "records a computed `lead_hours`: the whole number of hours between the
    moment of dispatch and the hearing's `scheduled_utc`, taken as the elapsed
    seconds divided by 3,600 and rounded down to a whole number."

    Gap of 12 hours -> lead_hours == 12.

    Design: Corner/state_machines/notify_side_effect_creates_notification_with_lead
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    cd = get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-01T12:00:00Z", "duration_minutes": 60}, COURT))
    notified = validate_success(api.notify_court_date(scen["def_id"], cd["id"], {"channel": "SMS"}, COURT))
    assert notified["status"] == "NOTIFIED", notified["status"]
    notifs, _ = validate_paginated(api.list_notifications(cd["id"], COURT))
    assert len(notifs) == 1, notifs
    assert notifs[0]["lead_hours"] == 12, notifs[0]["lead_hours"]


# Corner/state_machines/idempotent_appearance_second_call_invalid
def test_second_record_appearance_invalid_state(api):
    """PRD 3.5: "Recording an appearance advances the date to `APPEARED` and is
    allowed when the date is `SCHEDULED` or `NOTIFIED`."

    APPEARED is terminal; a second record-appearance -> ERR_INVALID_STATE.

    Design: Corner/state_machines/idempotent_appearance_second_call_invalid
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    cd = get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-10T09:00:00Z", "duration_minutes": 60}, COURT))
    get_success_data(api_client.record_appearance(scen["def_id"], cd["id"], COURT))
    resp = api.record_appearance(scen["def_id"], cd["id"], COURT)
    validate_error(resp, "ERR_INVALID_STATE")


# Corner/state_machines/revoke_cascades_discharge_and_release
def test_revoke_discharges_agreement_releases_collateral_no_ledger(api):
    """PRD 3.2: "Revocation discharges every pending indemnity agreement on the
    bond and releases every held collateral item, but writes no ledger entry —
    nothing was ever collected or earned, so there is nothing to refund."

    Design: Corner/state_machines/revoke_cascades_discharge_and_release
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000,
                                   collateral_value_cents=250_000)
    revoked = validate_success(api.revoke_bond(scen["def_id"], scen["bond_id"], scen["agent"]))
    assert revoked["coverage_status"] == "REVOKED", revoked["coverage_status"]
    agreements, _ = validate_paginated(api.list_bond_indemnity_agreements(scen["bond_id"], scen["agent"]))
    assert all(a["status"] == "DISCHARGED" for a in agreements), agreements
    items, _ = validate_paginated(api.list_collateral(scen["bond_id"], scen["agent"]))
    assert all(i["status"] == "RELEASED" for i in items), items
    ledger, _ = validate_paginated(api.list_ledger(scen["bond_id"], scen["agent"]))
    assert ledger == [], ledger
