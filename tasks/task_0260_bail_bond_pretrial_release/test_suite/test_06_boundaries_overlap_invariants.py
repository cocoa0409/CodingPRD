"""Boundary precision (grace deadline inclusive vs strict; indemnity coverage
>=), resource temporal/capacity overlap (docket buffer vs device slot), and
compensating-invariant conservation (collateral value, indemnitor exposure).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    setup_active_surety_bond, setup_draft_surety_bond,
    setup_recovery_open_bond, setup_judgment_ready, enter_judgment_on,
    setup_active_bond_with_assigned_gps,
    pin_clock, find_ledger_entries,
    TEST_USERS,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
COURT = TEST_USERS["court_headers"]


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/grace_deadline_inclusive_reinstate_vs_strict_judgment
# ---------------------------------------------------------------------------
def test_grace_deadline_value_is_forfeit_plus_30_days(api):
    """PRD 3.6: "The proceeding stamps `forfeited_utc` to the system clock at
    declaration and derives `grace_deadline_utc` as `forfeited_utc` plus a grace
    period of 30 days."

    Forfeited at 2026-07-02T00:00:00Z -> grace_deadline_utc 2026-08-01T00:00:00Z.

    Design: Difficulty/boundary_precision_check/grace_deadline_inclusive_reinstate_vs_strict_judgment
    """
    scen = setup_recovery_open_bond(
        forfeit_clock="2026-07-01T00:00:00Z", court_date_utc="2026-07-02T00:00:00Z",
        fta_clock="2026-07-02T00:00:00Z", bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    deadline = scen["proceeding"]["grace_deadline_utc"]
    assert deadline.startswith("2026-08-01T00:00:00"), deadline


def test_reinstate_at_exact_grace_deadline_succeeds(api):
    """PRD 3.6: "reinstatement and recovery are permitted up to and including that
    instant, while judgment is permitted only strictly after it."

    With clock pinned exactly to the deadline (2026-08-01T00:00:00Z), reinstate
    SUCCEEDS (inclusive boundary) and the proceeding reaches REINSTATED.

    Design: Difficulty/boundary_precision_check/grace_deadline_inclusive_reinstate_vs_strict_judgment
    """
    scen = setup_recovery_open_bond(
        forfeit_clock="2026-07-01T00:00:00Z", court_date_utc="2026-07-02T00:00:00Z",
        fta_clock="2026-07-02T00:00:00Z", bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    pin_clock("2026-08-01T00:00:00Z")
    proc = validate_success(api.reinstate(scen["def_id"], scen["proc_id"], OFFICER))
    assert proc["status"] == "REINSTATED", proc["status"]


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/insufficient_indemnity_at_exact_coverage_boundary
# ---------------------------------------------------------------------------
def test_indemnity_one_cent_short_rejected(api):
    """PRD 3.2: "For a surety bond, the sum of `liability_share_cents` across the
    bond's pending indemnity agreements must be at least the bond's
    `bail_amount_cents` — full coverage — and a shortfall is rejected with
    `ERR_INSUFFICIENT_INDEMNITY` (HTTP 409)."

    1,000,000c bond with 999,999c pending indemnity (1c short) -> rejected.

    Design: Difficulty/boundary_precision_check/insufficient_indemnity_at_exact_coverage_boundary
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=999_999,
                                   collateral_value_cents=250_000)
    resp = api.activate_bond(scen["def_id"], scen["bond_id"], scen["agent"])
    validate_error(resp, "ERR_INSUFFICIENT_INDEMNITY")


def test_indemnity_exactly_full_coverage_activates(api):
    """PRD 3.2: "the sum of `liability_share_cents` across the bond's pending
    indemnity agreements must be at least the bond's `bail_amount_cents` — full
    coverage."

    Exactly equal (1,000,000 == 1,000,000) passes the >= boundary and activates.

    Design: Difficulty/boundary_precision_check/insufficient_indemnity_at_exact_coverage_boundary
    """
    scen = setup_active_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000,
                                    collateral_value_cents=250_000)
    assert scen["bond"]["coverage_status"] == "ACTIVE", scen["bond"]["coverage_status"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/docket_overlap_buffered_closed_interval
# ---------------------------------------------------------------------------
def test_docket_overlap_within_buffer_rejected(api):
    """PRD 3.5: "Before testing for collision, each existing interval is inflated
    by a mandatory inter-hearing buffer of 30 minutes on both ends. The new hearing
    collides if its start is at or before the buffered end of an existing hearing
    and the buffered start of that existing hearing is at or before the new
    hearing's end."

    Existing [09:00, 10:00]; new start 10:20 is within the 30-minute buffered end
    (10:30) -> ERR_DOCKET_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/docket_overlap_buffered_closed_interval
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-10T09:00:00Z", "duration_minutes": 60}, COURT))
    resp = api.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-10T10:20:00Z", "duration_minutes": 60}, COURT)
    validate_error(resp, "ERR_DOCKET_OVERLAP")


def test_docket_clear_gap_beyond_buffer_allowed(api):
    """PRD 3.5: "two hearings that merely touch at the buffer boundary are treated
    as colliding — adjacency at the boundary is a collision, not a clean fit."

    Existing [09:00, 10:00], buffered end 10:30; a new hearing starting at 10:31
    (strictly beyond the buffer) is a clean fit and is created (201).

    Design: Difficulty/resource_temporal_overlap/docket_overlap_buffered_closed_interval
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-10T09:00:00Z", "duration_minutes": 60}, COURT))
    cd2 = validate_success(api.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-10T10:31:00Z", "duration_minutes": 60}, COURT),
        expected_status=201)
    assert cd2["status"] == "SCHEDULED", cd2["status"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/device_slot_aggregate_capacity_one
# ---------------------------------------------------------------------------
def test_second_device_on_occupied_bond_rejected(api):
    """PRD 3.8: "a bond's monitoring slot admits at most one non-returned device:
    the system counts the devices currently referencing this bond whose status is
    `ASSIGNED`, `ACTIVE`, or `TAMPER`, and if that count is already at or above the
    capacity of one, the assignment is rejected with `ERR_DEVICE_SLOT_OCCUPIED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/device_slot_aggregate_capacity_one
    """
    scen = setup_active_bond_with_assigned_gps(bail_amount_cents=1_000_000, liability_share_cents=1_000_000,
                                               serial_number="GPS-OCC-1")
    dev2 = get_success_data(api_client.create_gps_device({"serial_number": "GPS-OCC-2"}, scen["agent"]))
    resp = api.assign_gps(scen["def_id"], scen["bond_id"], {"device_id": dev2["id"]}, scen["agent"])
    validate_error(resp, "ERR_DEVICE_SLOT_OCCUPIED")


def test_device_slot_no_time_buffer_pure_capacity(api):
    """PRD 3.8: "This is a pure point-in-time occupancy count with capacity one —
    there is no buffer and no time arithmetic, distinguishing it from the
    docket-overlap rule."

    Even a second assignment with no overlapping time semantics is rejected purely
    on the capacity-1 count.

    Design: Difficulty/resource_temporal_overlap/device_slot_aggregate_capacity_one
    """
    scen = setup_active_bond_with_assigned_gps(bail_amount_cents=1_000_000, liability_share_cents=1_000_000,
                                               serial_number="GPS-CAP-1")
    dev2 = get_success_data(api_client.create_gps_device({"serial_number": "GPS-CAP-2"}, scen["agent"]))
    resp = api.assign_gps(scen["def_id"], scen["bond_id"], {"device_id": dev2["id"]}, scen["agent"])
    validate_error(resp, "ERR_DEVICE_SLOT_OCCUPIED")


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/collateral_conservation_on_exonerate
# ---------------------------------------------------------------------------
def test_collateral_value_conserved_on_exoneration(api):
    """PRD 3.4: "the refund for an item is its `pledged_value_cents` reduced by a
    flat processing fee the agency retains, which is 25 dollars (2,500 cents) per
    item."

    Conservation: pledged 500,000 == refund magnitude 497,500 + retained fee 2,500,
    and collateral_held_cents drops to 0.

    Design: Difficulty/compensating_invariant/collateral_conservation_on_exonerate
    """
    scen = setup_active_surety_bond(bail_amount_cents=2_000_000, liability_share_cents=2_000_000,
                                    collateral_value_cents=500_000)
    exon = validate_success(api.exonerate_bond(scen["def_id"], scen["bond_id"], OFFICER))
    assert exon["collateral_held_cents"] == 0, exon["collateral_held_cents"]
    entries, _ = validate_paginated(api.list_ledger(scen["bond_id"], OFFICER))
    refunds = find_ledger_entries(entries, "COLLATERAL_REFUND")
    refund_magnitude = -sum(e["amount_cents"] for e in refunds)
    assert refund_magnitude + 2_500 == 500_000, (refund_magnitude, refunds)


def test_collateral_value_conserved_across_two_items(api):
    """PRD 3.4: "the refund for an item is its `pledged_value_cents` reduced by a
    flat processing fee the agency retains, which is 25 dollars (2,500 cents) per
    item."

    Two HELD items (300,000 + 200,000); on exoneration the conserved-value invariant
    holds across both: total pledged 500,000 == total refund magnitude + per-item fee
    (2,500 * 2 == 5,000), so refunds total 495,000.

    Design: Difficulty/compensating_invariant/collateral_conservation_on_exonerate
    """
    # Collateral can only be pledged on a DRAFT bond, so build a draft with two
    # HELD items, then activate and exonerate.
    draft = setup_draft_surety_bond(bail_amount_cents=2_000_000, liability_share_cents=2_000_000,
                                    collateral_value_cents=300_000)
    get_success_data(api_client.create_collateral(
        draft["def_id"], draft["bond_id"], {"kind": "VEHICLE_TITLE", "pledged_value_cents": 200_000}, draft["agent"]))
    get_success_data(api_client.activate_bond(draft["def_id"], draft["bond_id"], draft["agent"]))
    validate_success(api.exonerate_bond(draft["def_id"], draft["bond_id"], OFFICER))
    entries, _ = validate_paginated(api.list_ledger(draft["bond_id"], OFFICER))
    refunds = find_ledger_entries(entries, "COLLATERAL_REFUND")
    assert len(refunds) == 2, refunds
    refund_magnitude = -sum(e["amount_cents"] for e in refunds)
    assert refund_magnitude + 2_500 * 2 == 500_000, (refund_magnitude, refunds)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/indemnity_exposure_conservation_on_judgment
# ---------------------------------------------------------------------------
def test_indemnitor_exposure_conserved_through_judgment(api):
    """PRD 3.3: "When the bond activates, every `PENDING` agreement on it becomes
    `BINDING`, lifting the indemnitor's exposure by that agreement's share."
    PRD 3.3: "when a forfeiture judgment is entered, every `BINDING` agreement
    becomes `CALLED` — the agency is collecting against the cosigner — and the
    indemnitor's exposure again drops by that agreement's share."

    Exposure 1,000,000 while BINDING -> 0 after the agreement is CALLED at judgment.

    Design: Difficulty/compensating_invariant/indemnity_exposure_conservation_on_judgment
    """
    scen = setup_judgment_ready(open_recovery=False, bail_amount_cents=1_000_000,
                                liability_share_cents=1_000_000, collateral_value_cents=250_000)
    ind_id = scen["indemnitor"]["id"]
    bound = validate_success(api.get_indemnitor(ind_id, OFFICER))
    assert bound["total_exposure_cents"] == 1_000_000, bound["total_exposure_cents"]
    enter_judgment_on(scen)
    after = validate_success(api.get_indemnitor(ind_id, OFFICER))
    assert after["total_exposure_cents"] == 0, after["total_exposure_cents"]


def test_agreement_called_at_judgment_drives_exposure_drop(api):
    """PRD 3.3: "And when a forfeiture judgment is entered, every `BINDING`
    agreement becomes `CALLED` — the agency is collecting against the cosigner — and
    the indemnitor's exposure again drops by that agreement's share."

    The mechanism behind the conserved exposure drop: the agreement transitions
    BINDING -> CALLED at judgment, and because CALLED is no longer in the BINDING
    sum the indemnitor's total_exposure_cents reconciles to 0.

    Design: Difficulty/compensating_invariant/indemnity_exposure_conservation_on_judgment
    """
    scen = setup_judgment_ready(open_recovery=False, bail_amount_cents=1_000_000,
                                liability_share_cents=1_000_000, collateral_value_cents=250_000)
    enter_judgment_on(scen)
    agreements, _ = validate_paginated(api.list_bond_indemnity_agreements(scen["bond_id"], OFFICER))
    assert len(agreements) == 1, agreements
    assert agreements[0]["status"] == "CALLED", agreements[0]["status"]
