"""Prescription lifecycle: revision loop, window overlap, ownership (PRD §3.3)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_forester_payload,
    create_landowner_payload,
    create_prescription_payload,
    make_forester_headers,
    make_landowner_headers,
    setup_active_prescription,
    setup_approved_prescription,
    setup_certified_cruise,
    setup_tract_and_stand,
)

ADMIN = TEST_USERS["admin_headers"]


def test_prescription_revision_cycle_status_and_fields(api):
    """PRD §3.3: "the forester may send it back through the revision loop
    `APPROVED → PROPOSED`, optionally applying new `window_start`,
    `window_end`, or `silvicultural_method` values in the same motion, and the
    cycle between `PROPOSED` and `APPROVED` may repeat without bound".

    Design: Difficulty/non_linear_state_machine/prescription_revision_cycle
    """
    base = setup_approved_prescription()
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    prescription = base["prescription"]
    v0 = prescription["version"]

    revised = validate_success(
        api.revise_prescription(prescription["id"], {"window_end": "2026-11-01"}, fh)
    )
    assert revised["status"] == "PROPOSED"
    assert revised["window_end"] == "2026-11-01"
    assert revised["version"] == v0 + 1

    reapproved = validate_success(api.approve_prescription(prescription["id"], lh))
    assert reapproved["status"] == "APPROVED"
    assert reapproved["version"] == v0 + 2


def test_prescription_revision_loop_unbounded(api):
    """PRD §3.3: "the cycle between `PROPOSED` and `APPROVED` may repeat
    without bound as conditions on the ground change."

    Design: Difficulty/non_linear_state_machine/prescription_revision_cycle
    """
    base = setup_approved_prescription()
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    prescription = base["prescription"]

    # Turn the loop a second time: APPROVED → PROPOSED → APPROVED again.
    revised = validate_success(
        api.revise_prescription(prescription["id"], {"silvicultural_method": "SELECTION"}, fh)
    )
    assert revised["status"] == "PROPOSED"
    assert revised["silvicultural_method"] == "SELECTION"
    reapproved = validate_success(api.approve_prescription(prescription["id"], lh))
    assert reapproved["status"] == "APPROVED"


def test_prescription_window_half_open_adjacency(api):
    """PRD §3.3: "`APPROVED → ACTIVE` is refused with
    `ERR_STAND_WINDOW_OVERLAP` (HTTP 409) if any *other* `ACTIVE` prescription
    exists on the same stand whose half-open window overlaps this one — and
    because both windows are half-open, windows that merely touch at an
    endpoint do not overlap and are allowed."

    Design: Difficulty/resource_temporal_overlap/prescription_window_half_open_adjacency
    """
    base = setup_active_prescription()
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    p1 = base["prescription"]
    assert p1["status"] == "ACTIVE"

    # Adjacent window [2026-10-01, 2027-02-01) touches P1's end -> allowed.
    p2 = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"],
                                    silvicultural_method="SELECTION",
                                    window_start="2026-10-01",
                                    window_end="2027-02-01"),
        fh,
    ))
    get_success_data(api.propose_prescription(p2["id"], fh))
    get_success_data(api.approve_prescription(p2["id"], lh))
    p2 = validate_success(api.activate_prescription(p2["id"], fh))
    assert p2["status"] == "ACTIVE"

    # Overlapping window [2026-09-30, ...) intersects P1 -> rejected.
    p3 = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"],
                                    silvicultural_method="COMMERCIAL_THINNING",
                                    window_start="2026-09-30",
                                    window_end="2027-01-01"),
        fh,
    ))
    get_success_data(api.propose_prescription(p3["id"], fh))
    get_success_data(api.approve_prescription(p3["id"], lh))
    resp = api.activate_prescription(p3["id"], fh)
    validate_error(resp, ApiErrorId.ERR_STAND_WINDOW_OVERLAP)


def test_prescription_window_overlap_blocks_second_activation(api):
    """PRD §3.3: "`APPROVED → ACTIVE` is refused with
    `ERR_STAND_WINDOW_OVERLAP` (HTTP 409) if any *other* `ACTIVE` prescription
    exists on the same stand whose half-open window overlaps this one".

    Design: Difficulty/resource_temporal_overlap/prescription_window_half_open_adjacency
    """
    base = setup_active_prescription()
    fh = base["forester_headers"]
    lh = base["landowner_headers"]

    # Overlapping window — interior intersection with P1.
    p_overlap = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"],
                                    silvicultural_method="SELECTION",
                                    window_start="2026-07-01",
                                    window_end="2026-11-01"),
        fh,
    ))
    get_success_data(api.propose_prescription(p_overlap["id"], fh))
    get_success_data(api.approve_prescription(p_overlap["id"], lh))
    resp = api.activate_prescription(p_overlap["id"], fh)
    validate_error(resp, ApiErrorId.ERR_STAND_WINDOW_OVERLAP)


def test_create_prescription_invalid_enum_rejected(api):
    """PRD §3.3: "the `silvicultural_method` — one of `CLEARCUT`,
    `SHELTERWOOD`, `SEED_TREE`, `SELECTION`, or `COMMERCIAL_THINNING`".

    Design: Corner/entities/create_prescription_invalid_enum_rejected
    """
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    cruise = get_success_data(api.create_cruise(
        {"stand_id": base["stand"]["id"], "cruise_date": "2026-03-01",
         "plots": [{"plot_number": 1, "species": "PINE", "volume_bf": 1165}]},
        fh,
    ))
    resp = api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=cruise["id"],
                                    silvicultural_method="CLEARCUTT"),
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_approve_prescription_by_foreign_landowner_denied(api):
    """PRD §2.1: "a landowner acting on anything rooted in a tract they do not
    own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/approve_prescription_by_foreign_landowner_denied
    """
    base = setup_tract_and_stand()
    fh = base["forester_headers"]
    # Second landowner (non-owner).
    other = get_success_data(api.create_landowner(
        create_landowner_payload(full_name="Mallory Other", email="m@x.com", tax_id="T-2"),
        ADMIN,
    ))
    other_headers = make_landowner_headers(other["id"])

    cruise = get_success_data(api.create_cruise(
        {"stand_id": base["stand"]["id"], "cruise_date": "2026-03-01",
         "plots": [{"plot_number": 1, "species": "PINE", "volume_bf": 1165}]},
        fh,
    ))
    prescription = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"], cruise_id=cruise["id"]),
        fh,
    ))
    get_success_data(api.propose_prescription(prescription["id"], fh))
    resp = api.approve_prescription(prescription["id"], other_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
