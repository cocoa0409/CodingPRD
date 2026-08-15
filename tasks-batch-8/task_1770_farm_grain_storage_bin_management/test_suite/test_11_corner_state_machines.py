"""Corner queue / state_machines section — initial states, terminal
lockdowns, invalid transitions, idempotency, valid transitions, side-effect
sweeps, cross-entity cascades, compensation."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_site_manager_headers, make_applicator_headers,
    make_safety_officer_headers,
    create_bin, create_lot, create_contract, create_applicator, create_policy,
    set_clock,
    setup_bin_lot_contract_loadout, setup_delivered_loadout,
    setup_settled_loadout, setup_confirmed_loss_claim,
    get_lot, get_contract, get_loadout, get_permit, get_bin, get_fumigation,
    create_hotspot_reading, get_first_alert_for_bin,
    assert_instant_equal,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_lot_payload, create_permit_payload, create_fumigation_payload,
    create_claim_payload, create_loadout_payload, deliver_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


def test_initial_states_on_create(api):
    """PRD section 3.1: "its `status` begins at `STORED`".
    PRD section 3.5: "A new contract is `OPEN`".
    PRD section 3.4: "The request is born `REQUESTED`".
    PRD section 3.3: "A created record is immediately `ACTIVE`, with
    `cleared_at` and `cleared_by_applicator_id` null."
    PRD section 3.8: "A new policy is `ACTIVE` with
    `remaining_coverage_cents` equal to its full `coverage_limit_cents`."
    PRD section 3.8: "A submitted claim copies the alert's `loss_bu` onto
    itself and begins in `SUBMITTED` status."

    Design: Corner/state_machines/initial_states_on_create
    """
    b = create_bin(name="BIN-I")
    lot = create_lot(b["id"], original_bu=100.00)
    assert lot["status"] == "STORED"
    assert lot["drawn_bu"] == pytest.approx(0.00, abs=1e-9)

    con = create_contract(contracted_bu=1000.00)
    assert con["status"] == "OPEN"

    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"]), make_site_manager_headers("mgr-1")))
    assert permit["status"] == "REQUESTED"

    # Fumigation on a second bin so the permit on BIN-I is not voided
    b2 = create_bin(name="BIN-I2")
    app = create_applicator()
    fum = get_success_data(api_client.create_fumigation(
        create_fumigation_payload(
            b2["id"], app["id"], product="SULFURYL_FLUORIDE",
            application_start="2026-08-01T00:00:00Z",
            application_end="2026-08-01T04:00:00Z"),
        make_applicator_headers(app["id"])))
    assert fum["status"] == "ACTIVE"

    pol = create_policy()
    assert pol["status"] == "ACTIVE"

    # CONFIRMED_LOSS alert on BIN-I -> claim
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 25.00}, SM))
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM))
    assert claim["status"] == "SUBMITTED"
    assert claim["loss_bu"] == pytest.approx(25.00, abs=1e-9)


def test_alert_close_from_terminal_rejected(api):
    """PRD section 3.2: "An alert that is no longer `OPEN` cannot be closed
    and yields `ERR_ALERT_NOT_OPEN`."

    Design: Corner/state_machines/alert_close_from_terminal_rejected
    """
    b = create_bin(name="BIN-AT")
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "RESOLVED"}, SM))

    resp = api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 10.00}, SM)
    validate_error(resp, ApiErrorId.ERR_ALERT_NOT_OPEN, expected_status=409)
    after = get_success_data(api_client.get_alert(alert["id"], SM))
    assert after["status"] == "RESOLVED"


def test_dispatch_from_delivered_rejected(api):
    """PRD section 3.6: "A `SiteManager` delivers a `DISPATCHED` load-out —
    any other transport state yields `ERR_LOADOUT_STATE`".
    PRD section 3.6: "the load-out's transport must be `SCHEDULED`
    (otherwise `ERR_LOADOUT_STATE`)".

    Dispatching an already-DELIVERED loadout fails; transport stays
    DELIVERED.

    Design: Corner/state_machines/dispatch_from_delivered_rejected
    """
    b, lot, con, lo = setup_delivered_loadout(
        bin_name="BIN-DD", original_bu=500.00, contracted_bu=2000.00,
        planned_bu=100.00,
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ],
    )
    resp = api_client.dispatch_loadout(lo["id"], SM)
    validate_error(resp, ApiErrorId.ERR_LOADOUT_STATE, expected_status=409)
    after = get_loadout(lo["id"])
    assert after["transport_status"] == "DELIVERED"


def test_confirm_before_deliver_rejected(api):
    """PRD section 3.6: "Confirming a settlement requires the transport to
    be `DELIVERED` (otherwise `ERR_LOADOUT_STATE`)".

    Confirm-settlement on a DISPATCHED loadout fails; settlement remains
    UNSETTLED.

    Design: Corner/state_machines/confirm_before_deliver_rejected
    """
    from test_helpers import setup_dispatched_loadout
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-CF", original_bu=500.00, contracted_bu=2000.00,
        planned_bu=100.00,
    )
    resp = api_client.confirm_settlement(lo["id"], SM)
    validate_error(resp, ApiErrorId.ERR_LOADOUT_STATE, expected_status=409)
    after = get_loadout(lo["id"])
    assert after["settlement_status"] == "UNSETTLED"


def test_void_settlement_when_unsettled_rejected(api):
    """PRD section 3.6: "A settlement can later be undone by voiding, which
    requires the settlement dimension to be `SETTLED` (otherwise
    `ERR_SETTLEMENT_STATE`)."

    Design: Corner/state_machines/void_settlement_when_unsettled_rejected
    """
    b, lot, con, lo = setup_delivered_loadout(
        bin_name="BIN-VS", original_bu=500.00, contracted_bu=2000.00,
        planned_bu=100.00,
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ],
    )
    resp = api_client.void_settlement(lo["id"], SM)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_STATE, expected_status=409)


def test_claim_approve_twice_rejected(api):
    """PRD section 3.8: "a claim that is not `SUBMITTED` yields
    `ERR_CLAIM_NOT_SUBMITTED`."

    A second approve is rejected; the policy is not debited twice.

    Design: Corner/state_machines/claim_approve_twice_rejected
    """
    b, alert, pol, claim = setup_confirmed_loss_claim(
        policy_kw={"valuation_clause": "SPOT"}, loss_bu=100.00,
        bin_name="BIN-CT")
    get_success_data(api_client.approve_claim(
        claim["id"], {"spot_price_cents_per_bu": 420}, FO))

    resp = api_client.approve_claim(
        claim["id"], {"spot_price_cents_per_bu": 420}, FO)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED,
                   expected_status=409)
    after = get_success_data(api_client.get_claim(claim["id"], FO))
    assert after["indemnity_cents"] == 37000


def test_permit_approve_twice_rejected(api):
    """PRD section 3.4: "the permit must still be `REQUESTED` (otherwise
    `ERR_PERMIT_NOT_REQUESTED`)".

    Design: Corner/state_machines/permit_approve_twice_rejected
    """
    b = create_bin(name="BIN-PT")
    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"]), make_site_manager_headers("mgr-1")))
    get_success_data(api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-1")))

    resp = api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-2"))
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_REQUESTED,
                   expected_status=409)


def test_fumigation_clear_twice_rejected(api):
    """PRD section 3.3: "a record that is not `ACTIVE` cannot be cleared and
    yields `ERR_FUMIGATION_NOT_ACTIVE`".
    PRD section 3.3: "`SULFURYL_FLUORIDE`, which carries a 24-hour
    interval".

    SULFURYL_FLUORIDE lockout_until = application_start + 24h.

    Design: Corner/state_machines/fumigation_clear_twice_rejected
    """
    b = create_bin(name="BIN-FT")
    app_a = create_applicator(name="Alice A", license_no="LIC-A")
    app_b = create_applicator(name="Bob B", license_no="LIC-B")
    fum = get_success_data(api_client.create_fumigation(
        create_fumigation_payload(
            b["id"], app_a["id"], product="SULFURYL_FLUORIDE",
            application_start="2026-08-01T00:00:00Z",
            application_end="2026-08-01T04:00:00Z"),
        make_applicator_headers(app_a["id"])))
    assert_instant_equal(fum["lockout_until"], "2026-08-02T00:00:00Z")
    set_clock("2026-08-02T00:00:00Z")
    get_success_data(api_client.clear_fumigation(
        fum["id"], make_applicator_headers(app_b["id"])))

    resp = api_client.clear_fumigation(
        fum["id"], make_applicator_headers(app_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FUMIGATION_NOT_ACTIVE,
                   expected_status=409)


def test_contract_auto_delivering_on_first_loadout(api):
    """PRD section 3.5: "Its creation adds `planned_bu` to the contract's
    `committed_bu`, increments the contract's `version`, and moves an `OPEN`
    contract to `DELIVERING` on its first non-expired load-out."

    Design: Corner/state_machines/contract_auto_delivering_on_first_loadout
    """
    b, lot = create_bin(name="BIN-AD"), None
    lot = create_lot(b["id"], original_bu=500.00)
    con = create_contract(contracted_bu=1000.00)
    assert con["status"] == "OPEN"
    assert con["version"] == 1

    lo = get_success_data(api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=250.00), SM))
    assert lo["transport_status"] == "SCHEDULED"
    assert lo["settlement_status"] == "UNSETTLED"

    after = get_contract(con["id"])
    assert after["status"] == "DELIVERING"
    assert after["committed_bu"] == pytest.approx(250.00, abs=1e-9)
    assert after["version"] == 2


def test_assessment_epoch_sweeps(api):
    """PRD section 3.7: "Contracts in `OPEN` or `DELIVERING` whose
    `window_end` lies before now are judged: those whose `delivered_bu`
    reaches at least 98 percent of `contracted_bu` move to `FULFILLED`, the
    rest move to `DEFAULTED`, and each swept contract's `version`
    increments. Load-outs in `SCHEDULED` or `HELD` whose `scheduled_end`
    lies before now move to `EXPIRED`, with the commitment release
    described in §3.6 applying to the `SCHEDULED` ones. Permits in
    `REQUESTED` or `APPROVED` whose `planned_end` lies before now move to
    `EXPIRED`. Insurance policies that are `ACTIVE` with a `period_end`
    before now move to `EXPIRED`."
    PRD section 3.8: "the policy must be `ACTIVE` (otherwise
    `ERR_POLICY_NOT_ACTIVE`)".
    PRD section 3.5: "The contract must be `OPEN` or `DELIVERING`
    (otherwise `ERR_CONTRACT_NOT_OPEN`)".

    One run at clock 2026-09-15 sweeps contract DEFAULTED, loadout EXPIRED
    (commitment released), permit EXPIRED, policy EXPIRED; a claim against
    the expired policy is rejected ERR_POLICY_NOT_ACTIVE, and a new
    loadout against the defaulted contract is rejected
    ERR_CONTRACT_NOT_OPEN.

    Design: Corner/state_machines/assessment_epoch_sweeps
    """
    b = create_bin(name="BIN-SW")
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    set_clock("2026-08-10T12:00:00Z")
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 10.00}, SM))
    con = create_contract(
        contracted_bu=1000.00,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-31T23:59:59Z",
    )
    lo = get_success_data(api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=100.00,
        scheduled_start="2026-08-20T08:00:00Z",
        scheduled_end="2026-08-20T12:00:00Z",
    ), SM))
    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"], planned_start="2026-08-12T08:00:00Z",
        planned_end="2026-08-12T10:00:00Z"),
        make_site_manager_headers("mgr-1")))
    get_success_data(api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-1")))
    pol = create_policy(
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-08-31T23:59:59Z",
    )
    set_clock("2026-09-15T00:00:00Z")

    asm = get_success_data(api_client.create_assessment(
        {"period": "2026-09"}, SM))
    assert asm["contracts_defaulted"] == 1
    assert asm["loadouts_expired"] == 1
    assert asm["permits_expired"] == 1
    assert asm["policies_expired"] == 1

    con_now = get_contract(con["id"])
    assert con_now["status"] == "DEFAULTED"
    assert con_now["committed_bu"] == pytest.approx(0.00, abs=1e-9)
    lo_now = get_loadout(lo["id"])
    assert lo_now["transport_status"] == "EXPIRED"
    per_now = get_permit(permit["id"])
    assert per_now["status"] == "EXPIRED"

    claim_resp = api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM)
    validate_error(claim_resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE,
                   expected_status=409)

    lo_resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con_now["version"], planned_bu=50.00,
        scheduled_start="2026-08-25T08:00:00Z",
        scheduled_end="2026-08-25T12:00:00Z",
    ), SM)
    validate_error(lo_resp, ApiErrorId.ERR_CONTRACT_NOT_OPEN,
                   expected_status=409)


def test_fumigation_create_cascade_voids_permits(api):
    """PRD section 2.7: "additionally, when the destination is
    `FUMIGATION_LOCKOUT`, every entry permit of the bin in `REQUESTED` or
    `APPROVED` status moves to `VOIDED`."
    PRD section 3.3: "Creation recomputes the bin's posture: if the
    `application_start` is already at or before now, the bin enters
    `FUMIGATION_LOCKOUT` and the gate cascade fires".

    Design: Corner/state_machines/fumigation_create_cascade_voids_permits
    """
    b = create_bin(name="BIN-FZ")
    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"]), make_site_manager_headers("mgr-1")))
    get_success_data(api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-1")))
    app = create_applicator()

    get_success_data(api_client.create_fumigation(
        create_fumigation_payload(b["id"], app["id"]),
        make_applicator_headers(app["id"])))
    assert get_permit(permit["id"])["status"] == "VOIDED"
    assert get_bin(b["id"])["posture"] == "FUMIGATION_LOCKOUT"


def test_lot_suspension_restores_drawn_state(api):
    """PRD section 2.7: "Entering `SOUND` or `WATCH` from `ALERT` or
    `FUMIGATION_LOCKOUT` fires the **release cascade**: suspended lots
    return to `STORED` if their `drawn_bu` is zero and to `PARTIALLY_DRAWN`
    otherwise".

    A PARTIALLY_DRAWN lot (drawn_bu 100.00) is SUSPENDED by a hotspot
    alert; on RESOLVED closure it returns to PARTIALLY_DRAWN, never STORED.

    Design: Corner/state_machines/lot_suspension_restores_drawn_state
    """
    b, lot, con, lo = setup_settled_loadout(
        bin_name="BIN-LS", original_bu=1000.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=100.00,
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ],
    )
    create_hotspot_reading(b["id"], recorded_at="2026-08-02T00:00:00Z")
    assert get_lot(lot["id"])["status"] == "SUSPENDED"

    alert = get_first_alert_for_bin(b["id"])
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "RESOLVED"}, SM))
    after = get_lot(lot["id"])
    assert after["status"] == "PARTIALLY_DRAWN"
    assert after["drawn_bu"] == pytest.approx(100.00, abs=1e-9)
