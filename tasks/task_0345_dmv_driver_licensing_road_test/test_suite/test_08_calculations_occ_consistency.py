"""Point-window calculations, OCC on renewal, immediate consistency.

Queue B (Corner): calculations, cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    create_driver_record,
    active_licensed_record,
    capture_fee,
    get_record_version,
    renew_license_payload,
)

CLERK = make_clerk_headers("clerk-1")
OFFICER = make_officer_headers("officer-1")


# ===========================================================================
# Corner/calculations/point_balance_excludes_out_of_window_violation
# ===========================================================================
def test_point_balance_excludes_expired_violation(api):
    """PRD §3.7: "Violations in DISMISSED or EXPIRED status never contribute."
    PRD §2.5: "Any Violation still in ACTIVE status whose age — the current period
    minus its occurred_period — has grown strictly greater than the point window
    is moved to EXPIRED, and every affected driver record's point_balance is
    recomputed so the expired violation no longer contributes."
    PRD §3.7: "The window spans 730 day-periods."

    A 6-point violation at period 0, clock advanced to 731 (diff 731 > 730) ->
    EXPIRED, point_balance back to 0.

    Design: Corner/calculations/point_balance_excludes_out_of_window_violation
    """
    record = create_driver_record(full_name="Lou Win", date_of_birth="1986-01-01")
    get_success_data(
        api.create_violation(
            {"driver_record_id": record["id"], "code": "SPEEDING_15_OVER",
             "points": 6, "occurred_period": 0}, OFFICER,
        )
    )
    rec0 = validate_success(api.get_driver_record(record["id"], OFFICER), 200)
    assert rec0["point_balance"] == 6
    api.advance_clock(731, OFFICER)
    rec1 = validate_success(api.get_driver_record(record["id"], OFFICER), 200)
    assert rec1["point_balance"] == 0, f"got {rec1['point_balance']}"


# ===========================================================================
# Corner/calculations/point_balance_window_boundary_inclusive
# ===========================================================================
def test_point_balance_window_boundary_inclusive(api):
    """PRD §3.7: "the current period minus the violation's occurred_period is no
    greater than the window, where the window boundary is inclusive (a difference
    exactly equal to the window still counts). The window spans 730 day-periods."

    A 6-point violation at period 0, clock advanced to exactly 730 (diff 730 ==
    window) still counts -> point_balance == 6.

    Design: Corner/calculations/point_balance_window_boundary_inclusive
    """
    record = create_driver_record(full_name="Mia Bound", date_of_birth="1986-01-01")
    get_success_data(
        api.create_violation(
            {"driver_record_id": record["id"], "code": "SPEEDING_15_OVER",
             "points": 6, "occurred_period": 0}, OFFICER,
        )
    )
    api.advance_clock(730, OFFICER)
    rec = validate_success(api.get_driver_record(record["id"], OFFICER), 200)
    assert rec["point_balance"] == 6, f"got {rec['point_balance']}"


# ===========================================================================
# Corner/calculations/renewal_late_penalty_capped_on_renew
# ===========================================================================
def test_renewal_late_penalty_capped_on_renew(api):
    """PRD §3.6: "A late component applies on renewals: the number of days late is
    the current period minus the prior license's expiry_period, but never less
    than zero ...; the late penalty is the days late multiplied by 100 cents per
    day, capped at 5000 cents."
    PRD §3.6: "The base is the per-class fee for the chosen license_class: ... and
    5500 for C."

    Class C base 5500, far past expiry so the late penalty saturates at its 5000
    cap -> fee_cents == 10500.

    Design: Corner/calculations/renewal_late_penalty_capped_on_renew
    """
    ctx = active_licensed_record(
        license_class="C", examiner_classes=["C"], opaque_user_id="exu-c",
        full_name="Ned Late",
    )
    record = ctx["record"]
    # Push the clock far beyond expiry so days_late >= 50 (cap territory).
    api.advance_clock(100000, OFFICER)
    capture_fee(record["id"], "RENEWAL", 10500)
    version = get_record_version(record["id"])
    renewed = validate_success(
        api.renew_license(
            renew_license_payload(record["id"], version, license_class="C"), CLERK,
        ),
        201,
    )
    assert renewed["fee_cents"] == 10500, f"got {renewed['fee_cents']}"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_correct_version_renew_succeeds
# ===========================================================================
def test_occ_correct_version_renew_succeeds(api):
    """PRD §2.7: "When a license is renewed, the request must carry
    expected_driver_record_version, and this value must equal the target driver
    record's current version."
    PRD §3.6: "On success a new license is minted in ISSUED status and the record's
    previously current license moves to RENEWED."

    A renewal carrying the current version succeeds (201), new license ISSUED.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_renew_succeeds
    """
    ctx = active_licensed_record(
        license_class="D", opaque_user_id="exu-occ", full_name="Ada Occ",
    )
    record = ctx["record"]
    capture_fee(record["id"], "RENEWAL", 4000)
    version = get_record_version(record["id"])
    renewed = validate_success(
        api.renew_license(
            renew_license_payload(record["id"], version, license_class="D"), CLERK,
        ),
        201,
    )
    assert renewed["status"] == "ISSUED"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_version_renew_rejected
# ===========================================================================
def test_occ_stale_version_renew_rejected(api):
    """PRD §2.7: "if another writer has already renewed or otherwise advanced the
    record's version since the client last read it, the client's view of which
    license is current is stale, and the renewal is rejected with
    ERR_STALE_RECORD_VERSION (HTTP 412)."

    A renewal carrying a version read before an intervening opt-in bumped it ->
    ERR_STALE_RECORD_VERSION 412.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_renew_rejected
    """
    ctx = active_licensed_record(
        license_class="D", opaque_user_id="exu-stl", full_name="Ben Stale",
    )
    record = ctx["record"]
    stale_version = get_record_version(record["id"])
    # Intervening mutation bumps the record version.
    validate_success(api.opt_in(record["id"], {"organ_donor": True}, CLERK), 200)
    capture_fee(record["id"], "RENEWAL", 4000)
    resp = api.renew_license(
        renew_license_payload(record["id"], stale_version, license_class="D"), CLERK,
    )
    validate_error(resp, "ERR_STALE_RECORD_VERSION", expected_status=412)


# ===========================================================================
# Corner/consistency_model/license_issuance_visible_in_same_response_immediate
# ===========================================================================
def test_license_issuance_immediately_visible(api):
    """PRD §3.6: "On success the system mints the license in ISSUED status ...
    advances the record's licensing_status from ELIGIBLE to ACTIVE."
    PRD §2.6: "a state change on the driver record ... propagates to its
    dependents immediately and atomically — the caller never observes a
    half-applied cascade."

    The issued license is ISSUED and a same-turn record read shows ACTIVE — no lag.

    Design: Corner/consistency_model/license_issuance_visible_in_same_response_immediate
    """
    ctx = active_licensed_record(
        license_class="D", opaque_user_id="exu-imm", full_name="Cas Imm",
    )
    assert ctx["license"]["status"] == "ISSUED"
    rec = validate_success(api.get_driver_record(ctx["record"]["id"], CLERK), 200)
    assert rec["licensing_status"] == "ACTIVE"
