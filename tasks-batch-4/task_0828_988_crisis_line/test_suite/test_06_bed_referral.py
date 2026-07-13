"""Bed referral: center-online precondition, referential-vs-capacity precedence,
aggregate window capacity, body validation, computed ledger, terminal lockdown, OCC."""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    create_bed_referral_payload, create_center_payload, TEST_USERS,
    create_dispatch_pending_contact, create_center,
    setup_held_referral, current_center_version,
)

SUP = TEST_USERS["supervisor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── cross_entity_state_dependency / bed_referral_create_requires_center_online ─

def test_bed_referral_against_diverted_center_rejected():
    """PRD §3.6: "Beyond OCC, referral creation checks that the contact is in `DISPATCH_PENDING` (else `ERR_CONTACT_NOT_DISPATCH_PENDING`), that the center is `ONLINE` (else `ERR_CENTER_OFFLINE`), that the center's `accepted_acuities` includes the referral's `acuity` (else `ERR_ACUITY_NOT_ACCEPTED`), and that the hold window does not exhaust the center's bed capacity."

    Design: Difficulty/cross_entity_state_dependency/bed_referral_create_requires_center_online
    """
    contact = create_dispatch_pending_contact("ce-b-01")
    center = create_center(name="Center F", bed_capacity=2, accepted_acuities=["HIGH"])
    validate_success(api.center_state(center["id"], {"to_status": "DIVERTED"}, DISPATCHER), 200)
    cv = current_center_version(center["id"])
    res = api.create_bed_referral(create_bed_referral_payload(
        contact["id"], center["id"], cv, acuity="HIGH"), DISPATCHER)
    validate_error(res, "ERR_CENTER_OFFLINE", expected_status=409)


def test_bed_referral_against_online_center_succeeds():
    """PRD §3.6: "A successful referral is created in `HELD`; the center's `held_beds` is incremented and its `version` is incremented; and the contact is driven from `DISPATCH_PENDING` to `REFERRAL_PENDING`."

    Positive control for the ONLINE precondition.

    Design: Difficulty/cross_entity_state_dependency/bed_referral_create_requires_center_online
    """
    contact = create_dispatch_pending_contact("ce-b-02")
    center = create_center(name="Center F2", bed_capacity=2, accepted_acuities=["HIGH"])
    res = api.create_bed_referral(create_bed_referral_payload(
        contact["id"], center["id"], center["version"], acuity="HIGH"), DISPATCHER)
    referral = validate_success(res, 201)
    assert referral["status"] == "HELD", f"expected HELD, got {referral['status']}"


# ─── priority_pair_validation_conflict / referential_beats_capacity_on_bed_referral ─

def test_acuity_check_beats_capacity_on_bed_referral():
    """PRD §2.8: "(8) cross-entity referential preconditions, yielding `ERR_CONTACT_NOT_DISPATCH_PENDING`, `ERR_CENTER_OFFLINE`, or `ERR_ACUITY_NOT_ACCEPTED`; (9) temporal-overlap checks, yielding `ERR_TEAM_WINDOW_CONFLICT` or `ERR_BED_WINDOW_CONFLICT`"
    PRD §2.8: "Earlier checks strictly precede later ones"
    PRD §3.6: "that the center's `accepted_acuities` includes the referral's `acuity` (else `ERR_ACUITY_NOT_ACCEPTED`)"

    A HIGH-acuity referral into a LOW-only center whose sole bed-window is full fails both
    the acuity check (8) and the window-capacity check (9); the earlier acuity check wins.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_capacity_on_bed_referral
    """
    _, center, _, _ = setup_held_referral(
        "pc-b-fill",
        center_kwargs={"name": "Center R", "bed_capacity": 1, "accepted_acuities": ["LOW"]},
        referral_kwargs={"acuity": "LOW", "window_start": "2026-03-01T00:00:00Z",
                         "window_end": "2026-03-01T01:00:00Z"},
    )
    c2 = create_dispatch_pending_contact("pc-b-trig")
    cv = current_center_version(center["id"])
    res = api.create_bed_referral(create_bed_referral_payload(
        c2["id"], center["id"], cv, acuity="HIGH",
        window_start="2026-03-01T00:30:00Z", window_end="2026-03-01T00:45:00Z"), DISPATCHER)
    validate_error(res, "ERR_ACUITY_NOT_ACCEPTED", expected_status=409)


def test_capacity_check_fires_when_acuity_accepted():
    """PRD §3.6: "This center window rule is aggregate-capacity and half-open with no buffer: the referral is rejected with `ERR_BED_WINDOW_CONFLICT` if adding the new hold would bring the count of the center's referrals in `HELD` or `ADMITTED` whose `[window_start, window_end)` interval overlaps the new interval to at least `bed_capacity`."

    Isolation control for the precedence pair: with the acuity accepted, only the temporal
    window-capacity check (9) can fail, surfacing ERR_BED_WINDOW_CONFLICT — the check the
    acuity error pre-empts in the conflict case above.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_capacity_on_bed_referral
    """
    _, center, _, _ = setup_held_referral(
        "pc-c-fill",
        center_kwargs={"name": "Center R2", "bed_capacity": 1, "accepted_acuities": ["HIGH"]},
        referral_kwargs={"acuity": "HIGH", "window_start": "2026-03-01T00:00:00Z",
                         "window_end": "2026-03-01T01:00:00Z"},
    )
    c2 = create_dispatch_pending_contact("pc-c-trig")
    cv = current_center_version(center["id"])
    res = api.create_bed_referral(create_bed_referral_payload(
        c2["id"], center["id"], cv, acuity="HIGH",
        window_start="2026-03-01T00:30:00Z", window_end="2026-03-01T00:45:00Z"), DISPATCHER)
    validate_error(res, "ERR_BED_WINDOW_CONFLICT", expected_status=409)


# ─── resource_temporal_overlap / bed_hold_window_aggregate_capacity_conflict ───

def test_overlapping_bed_window_exceeds_capacity():
    """PRD §3.6: "This center window rule is aggregate-capacity and half-open with no buffer: the referral is rejected with `ERR_BED_WINDOW_CONFLICT` if adding the new hold would bring the count of the center's referrals in `HELD` or `ADMITTED` whose `[window_start, window_end)` interval overlaps the new interval to at least `bed_capacity`."

    A second HELD window [00:30,01:30) overlaps the existing [00:00,01:00) on a capacity-1
    center -> conflict.

    Design: Difficulty/resource_temporal_overlap/bed_hold_window_aggregate_capacity_conflict
    """
    _, center, _, _ = setup_held_referral(
        "to-b-1",
        center_kwargs={"name": "Center B", "bed_capacity": 1, "accepted_acuities": ["HIGH"]},
        referral_kwargs={"acuity": "HIGH", "window_start": "2026-03-01T00:00:00Z",
                         "window_end": "2026-03-01T01:00:00Z"},
    )
    c2 = create_dispatch_pending_contact("to-b-2")
    cv = current_center_version(center["id"])
    res = api.create_bed_referral(create_bed_referral_payload(
        c2["id"], center["id"], cv, acuity="HIGH",
        window_start="2026-03-01T00:30:00Z", window_end="2026-03-01T01:30:00Z"), DISPATCHER)
    validate_error(res, "ERR_BED_WINDOW_CONFLICT", expected_status=409)


def test_touching_bed_window_does_not_overlap_allowed():
    """PRD §3.6: "Because the intervals are half-open, two holds that merely touch end-to-start do not overlap."

    A second HELD window [01:00,02:00) touches the existing [00:00,01:00) end-to-start on a
    capacity-1 center, so it does not overlap and is allowed.

    Design: Difficulty/resource_temporal_overlap/bed_hold_window_aggregate_capacity_conflict
    """
    _, center, _, _ = setup_held_referral(
        "to-b-3",
        center_kwargs={"name": "Center B2", "bed_capacity": 1, "accepted_acuities": ["HIGH"]},
        referral_kwargs={"acuity": "HIGH", "window_start": "2026-03-01T00:00:00Z",
                         "window_end": "2026-03-01T01:00:00Z"},
    )
    c2 = create_dispatch_pending_contact("to-b-4")
    cv = current_center_version(center["id"])
    res = api.create_bed_referral(create_bed_referral_payload(
        c2["id"], center["id"], cv, acuity="HIGH",
        window_start="2026-03-01T01:00:00Z", window_end="2026-03-01T02:00:00Z"), DISPATCHER)
    referral = validate_success(res, 201)
    assert referral["status"] == "HELD", f"expected HELD, got {referral['status']}"


# ─── Corner / bed_referral_window_invalid_returns_error ────────────────────────

def test_bed_referral_window_end_not_after_start_rejected():
    """PRD §2.4: "a window whose `window_end` is less than or equal to its `window_start` (and, for a team, a shift whose `shift_end` is less than or equal to its `shift_start`) is rejected at body validation with `ERR_WINDOW_INVALID`."

    Design: Corner/validations/bed_referral_window_invalid_returns_error
    """
    contact = create_dispatch_pending_contact("vd-e-01")
    center = create_center(name="Center W", bed_capacity=2, accepted_acuities=["HIGH"])
    res = api.create_bed_referral(create_bed_referral_payload(
        contact["id"], center["id"], center["version"], acuity="HIGH",
        window_start="2026-03-01T06:00:00Z", window_end="2026-03-01T02:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_WINDOW_INVALID", expected_status=422)


# ─── Corner / center_available_beds_computed_on_create ─────────────────────────

def test_center_available_beds_computed_on_create():
    """PRD §3.6: "A new center opens with `status` `ONLINE`, `held_beds` at 0, `occupied_beds` at 0, and `version` at 1; its `available_beds` follows the ledger in §2.9."
    PRD §2.9: "The center's `available_beds` is its `bed_capacity` minus `held_beds` minus `occupied_beds`."

    Design: Corner/entities/center_available_beds_computed_on_create
    """
    res = api.create_center(create_center_payload(
        name="Center X", bed_capacity=3, accepted_acuities=["LOW", "MODERATE", "HIGH"]), SUP)
    center = validate_success(res, 201)
    assert center["available_beds"] == 3, f"expected available_beds 3, got {center['available_beds']}"
    assert center["held_beds"] == 0, f"expected held_beds 0, got {center['held_beds']}"
    assert center["occupied_beds"] == 0, f"expected occupied_beds 0, got {center['occupied_beds']}"


# ─── Corner / admit_referral_from_voided_returns_invalid_state ─────────────────

def test_admit_voided_referral_returns_invalid_state():
    """PRD §3.6: "`DISCHARGED` and `VOIDED` are terminal; any transition attempted from an illegal from-state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/admit_referral_from_voided_returns_invalid_state
    """
    _, _, referral, _ = setup_held_referral("sm-d-01")
    validate_success(api.bed_referral_state(referral["id"], {"to_status": "VOIDED"}, DISPATCHER), 200)
    res = api.bed_referral_state(referral["id"], {"to_status": "ADMITTED"}, DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner / bed_referral_stale_center_version_returns_412 ────────────────────

def test_bed_referral_stale_center_version_returns_412():
    """PRD §2.7: "If that value does not equal the center's current `version` — meaning another writer has since created or voided a hold on that center and thereby advanced its version, leaving the current writer's view of bed availability stale — the create is rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting/bed_referral_stale_center_version_returns_412
    """
    center = create_center(name="Center OCC", bed_capacity=2, accepted_acuities=["HIGH"])
    stale_version = center["version"]
    c1 = create_dispatch_pending_contact("occ-c-1")
    validate_success(api.create_bed_referral(create_bed_referral_payload(
        c1["id"], center["id"], stale_version, acuity="HIGH",
        window_start="2026-03-01T02:00:00Z", window_end="2026-03-01T06:00:00Z"),
        DISPATCHER), 201)  # advances center.version 1 -> 2
    c2 = create_dispatch_pending_contact("occ-c-2")
    res = api.create_bed_referral(create_bed_referral_payload(
        c2["id"], center["id"], stale_version, acuity="HIGH",
        window_start="2026-03-01T07:00:00Z", window_end="2026-03-01T08:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
