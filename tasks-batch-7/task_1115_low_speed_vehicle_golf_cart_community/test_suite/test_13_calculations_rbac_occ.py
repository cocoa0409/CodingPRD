"""Calculation corners (charging-fee floor, points thresholds, dismissal
recompute), RBAC peer-role isolation, OCC stale-version rejection, and immediate
consistency (PRD §2.1, §2.5, §2.7, §3.8, §3.9).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, create_holder,
    deposit, get_holder, set_clock,
    setup_active_registration, setup_station, setup_reservation,
    create_violation_payload, create_full_equipment_lsv,
    create_draft_registration, finalize_inspection_for_registration,
    create_insurance, create_vehicle,
    create_inspection_payload, finalize_inspection_payload,
    create_charging_reservation_payload,
    wallet_deposit_payload,
    assert_instant_equal,
    COMMUNITY_ADMIN, INSPECTOR, OFFICER, ANON, ADMIN,
    ApiErrorId,
)


# ── calculations section ─────────────────────────────────────────────────

def test_charging_fee_min_charge_floor():
    """PRD §3.8: "The fee charged at booking is the reservation's duration in
    minutes — any fractional minute rounded up — multiplied by the station's
    `rate_cents_per_min`, subject to a minimum charge of 200 cents; the computed
    `fee_cents` is debited from the holder's wallet immediately, and a balance
    below the fee (equality is sufficient) is rejected with
    `ERR_INSUFFICIENT_FUNDS`."

    Design: Corner/calculations/charging_fee_min_charge_floor
    """
    community = create_community(name="C-MIN")
    holder = create_eligible_holder(community["id"], full_name="H MIN",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 1000, holder["version"])
    station = setup_station(community["id"], name="S-MIN", slot_count=2,
                            rate_cents_per_min=10)
    reservation = setup_reservation(
        station["id"], holder["id"], slot_index=0,
        start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T10:10:00Z")
    # max(200, 10 min * 10 c/min = 100) = 200: the floor binds.
    assert reservation["fee_cents"] == 200, (
        f"fee {reservation['fee_cents']} != 200 (floor binds over 100)")
    assert get_holder(holder["id"])["wallet_balance_cents"] == 800


def test_points_threshold_exactly_4_probation():
    """PRD §3.9: "Standing follows fixed thresholds — `BARRED` at 12 points or
    more (exactly 12 is `BARRED`), `PROBATION` at 4 through 11 points, and
    `GOOD_STANDING` at 3 or fewer — and the holder's `compliance_status` is
    rewritten accordingly."

    Design: Corner/calculations/points_threshold_exactly_4_probation
    """
    community = create_community(name="C-PT4")
    holder = create_eligible_holder(community["id"], full_name="H PT4",
                                    birth_date="2010-05-01")
    vio = get_success_data(api_client.create_violation(
        create_violation_payload(holder["id"], violation_code="PARKING_VIOLATION",
                                 points_assessed=4, fine_cents=3000,
                                 occurred_at="2026-04-15T00:00:00Z"), OFFICER))
    validate_success(api_client.uphold_violation(vio["id"], OFFICER), 200)
    after = get_holder(holder["id"])
    # 4 >= 4 inclusive -> PROBATION.
    assert after["points_balance"] == 4
    assert after["compliance_status"] == "PROBATION"


def test_points_recompute_on_dismiss():
    """PRD §3.9: "Dismissing moves a violation from either `FILED` or `UPHELD` to
    `DISMISSED` — dismissing an `UPHELD` violation is the appeal path — and when
    the dismissed violation had been `UPHELD`, the holder's `points_balance` and
    `compliance_status` are recomputed downward. A dismissal never reinstates
    registrations on its own: holders who drop out of `BARRED` must have each
    suspended registration reinstated individually."

    Design: Corner/calculations/points_recompute_on_dismiss
    """
    community = create_community(name="C-DIS")
    holder = create_eligible_holder(community["id"], full_name="H DIS",
                                    birth_date="2010-05-01")
    vio = get_success_data(api_client.create_violation(
        create_violation_payload(holder["id"], violation_code="OFF_ROUTE",
                                 points_assessed=4, fine_cents=3000,
                                 occurred_at="2026-04-15T00:00:00Z"), OFFICER))
    validate_success(api_client.uphold_violation(vio["id"], OFFICER), 200)
    dismissed = validate_success(api_client.dismiss_violation(vio["id"], OFFICER), 200)
    assert dismissed["status"] == "DISMISSED"
    after = get_holder(holder["id"])
    assert after["points_balance"] == 0
    assert after["compliance_status"] == "GOOD_STANDING"


# ── rbac section ─────────────────────────────────────────────────────────

def test_inspector_cannot_uphold_violation_forbidden():
    """PRD §2.6: "**Authorization** — the role is permitted for the endpoint, and
    for `PermitHolder`-role calls `X-User-ID` equals the owning holder of the
    target or payload resource. Failure: `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the violation-uphold endpoint lists "EnforcementOfficer" as its only
    authorized role.

    Design: Corner/rbac/inspector_cannot_uphold_violation_forbidden
    """
    community = create_community(name="C-RB1")
    holder = create_holder(community["id"], full_name="H RB1",
                           birth_date="2010-05-01")
    vio = get_success_data(api_client.create_violation(
        create_violation_payload(holder["id"], violation_code="OFF_ROUTE",
                                 points_assessed=3, fine_cents=2000,
                                 occurred_at="2026-04-15T00:00:00Z"), OFFICER))
    res = api_client.uphold_violation(vio["id"], INSPECTOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    vio_after = get_success_data(api_client.get_violation(vio["id"], OFFICER))
    assert vio_after["status"] == "FILED"
    assert get_holder(holder["id"])["points_balance"] == 0


def test_enforcement_officer_cannot_finalize_inspection_forbidden():
    """PRD §2.6: "**Authorization** — the role is permitted for the endpoint, and
    for `PermitHolder`-role calls `X-User-ID` equals the owning holder of the
    target or payload resource. Failure: `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the inspection-finalize endpoint lists "Inspector" as its only
    authorized role.

    Design: Corner/rbac/enforcement_officer_cannot_finalize_inspection_forbidden
    """
    community = create_community(name="C-RB2")
    holder = create_eligible_holder(community["id"], full_name="H RB2",
                                    birth_date="2010-05-01")
    vehicle = create_vehicle(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    inspection = get_success_data(api_client.create_inspection(
        create_inspection_payload(registration["id"]), INSPECTOR))
    res = api_client.finalize_inspection(
        inspection["id"], finalize_inspection_payload(score=90), OFFICER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    ins_after = get_success_data(
        api_client.get_inspection(inspection["id"], INSPECTOR))
    assert ins_after["status"] == "SCHEDULED"


# ── cross_cutting_layers section (OCC) ───────────────────────────────────

def test_occ_community_patch_stale_rejected():
    """PRD §2.7: "Updating a community's configuration requires the request body
    to carry `expected_community_version`, set to the community `version` the
    client last observed. If a prior accepted update has since advanced the
    community's `version` — so the fee-relevant thresholds and renewal windows the
    client read are stale — the update is rejected with `ERR_STALE_VERSION` (HTTP
    412) and must be re-based on a fresh read."
    PRD §3.1: "A `PlatformAdmin` may later update any of these configuration
    fields. Because fee thresholds and renewal windows feed live calculations, the
    update is guarded by optimistic concurrency as specified in §2.7 and increments
    the community's `version` by 1 on success."

    Design: Corner/cross_cutting_layers/occ_community_patch_stale_rejected
    """
    community = create_community(name="C-OCC1")
    captured_version = community["version"]  # 1 at creation
    updated = validate_success(api_client.update_community(
        community["id"],
        {"expected_community_version": captured_version, "min_driver_age": 17},
        ADMIN), 200)
    assert updated["version"] == 2
    assert updated["min_driver_age"] == 17
    # Replaying the same captured (now stale) version is rejected.
    res = api_client.update_community(
        community["id"],
        {"expected_community_version": captured_version, "min_driver_age": 18},
        ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = get_success_data(api_client.get_community(community["id"], ADMIN))
    assert after["min_driver_age"] == 17


def test_occ_wallet_deposit_stale_rejected():
    """PRD §2.7: "Depositing into a holder's wallet requires the request body to
    carry `expected_permit_holder_version`, set to the PermitHolder `version` the
    client last observed. Deposits are always semantically valid, so this
    stale-version check is the only guard against a lost update when another
    mutation — a fee debit, a cascade refund, a prior deposit — has advanced the
    holder's `version` since the client's last read. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field."
    PRD §3.2: "Holders fund their own wallets. A deposit names an `amount_cents`
    and must carry the OCC field described in §2.7; a successful deposit adds the
    amount to `wallet_balance_cents` and increments the holder's `version`."

    Design: Corner/cross_cutting_layers/occ_wallet_deposit_stale_rejected
    """
    community = create_community(name="C-OCC2")
    holder = create_eligible_holder(community["id"], full_name="H OCC2",
                                    birth_date="2010-05-01")
    captured_version = holder["version"]  # captured at verify-eligibility
    hh = make_permit_holder_headers(holder["id"])
    first = validate_success(api_client.deposit_wallet(
        holder["id"], wallet_deposit_payload(5000, captured_version), hh), 200)
    assert first["wallet_balance_cents"] == 5000
    res = api_client.deposit_wallet(
        holder["id"], wallet_deposit_payload(5000, captured_version), hh)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_holder(holder["id"])["wallet_balance_cents"] == 5000


# ── consistency_model section ────────────────────────────────────────────

def test_activation_visible_immediately_in_response():
    """PRD §2.5: "Every mutation — including all of its cascades — is applied
    atomically within the request and is fully visible in the response."
    PRD §3.5: "On success the wallet is debited by `total_due_cents`, the
    registration's `paid_cents` accumulates that same amount, `valid_from` is set
    to the activation instant, `expiry_date` is set 365 days after `valid_from`,
    and both the registration's and the holder's `version` increment by 1."
    PRD §2.4: "At server startup the logical clock reads exactly
    2026-05-01T00:00:00Z."

    Design: Corner/consistency_model/activation_visible_immediately_in_response
    """
    ctx_holder = create_community(name="C-CONS", fleet_program_enabled=True)
    holder = create_eligible_holder(ctx_holder["id"], full_name="H CONS",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 100000, holder["version"])
    vehicle = create_full_equipment_lsv(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    finalize_inspection_for_registration(registration["id"], score=90)
    create_insurance(holder["id"], vehicle["id"], policy_number="N-CONS")
    hh = make_permit_holder_headers(holder["id"])
    activated = validate_success(
        api_client.activate_registration(registration["id"], hh), 200)
    # Immediate consistency: status, paid_cents and window are in the response.
    assert activated["status"] == "ACTIVE"
    assert activated["paid_cents"] == 19000
    # PRD §3.5 pins the instants (valid_from = activation instant; expiry_date =
    # valid_from + 365 days), not their serialization — compare by instant.
    assert_instant_equal(activated["valid_from"], "2026-05-01T00:00:00Z")
    assert_instant_equal(activated["expiry_date"], "2027-05-01T00:00:00Z")
    # Follow-up read shows the debited wallet without lag.
    assert get_holder(holder["id"])["wallet_balance_cents"] == 81000
