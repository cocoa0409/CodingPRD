"""License lifecycle cascades and derived-count reconciliation (PRD §3.1, §3.4,
§3.5, §3.6, §2.8).

Covers the mark-deceased depth-3 cascade, the grace-expiry delinquency cascade,
the net-vs-gross outstanding-penalty reading, active_license_count reconciliation,
and immediate consistency on tag issuance.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_owner_headers,
    set_clock,
    advance_clock,
    create_owner,
    create_pet,
    create_rabies_record,
    create_draft_license,
    setup_active_individual_license,
    setup_approved_individual_license,
    setup_expired_individual_license,
    drive_license_to_active,
)
from test_helpers import api_client

CLERK = TEST_USERS["clerk_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_pet_deceased_revokes_license_voids_tag_recounts_owner(api):
    """PRD §3.1: "every license of that pet currently in ACTIVE, GRACE, or
    APPROVED is forced to REVOKED, its currently issued tag is voided, and the
    owner's active_license_count together with any affected kennel's
    occupied_slots is recomputed to reflect the licenses that just left their
    counted states."

    Design: Difficulty/transitive_cascade/pet_deceased_revokes_license_voids_tag_recounts_owner
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lic = setup_active_individual_license(
        owner_overrides={"full_name": "Owner E", "email": "oe@x.com"},
        pet_overrides={"is_altered": True, "name": "Pax"},
    )
    # Confirm precondition: owner has 1 active license, tag is ISSUED.
    owner_before = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_before["active_license_count"] == 1

    deceased = validate_success(
        api.mark_pet_deceased(pet["id"], make_owner_headers(owner["id"])), 200
    )
    assert deceased["status"] == "DECEASED"

    lic_after = validate_success(api.get_license(lic["id"], CLERK), 200)
    assert lic_after["status"] == "REVOKED"

    tags, _ = _list_license_tags(api, lic["id"])
    assert any(t["status"] == "VOID" for t in tags), "the issued tag must be VOID"

    owner_after = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_after["active_license_count"] == 0


def test_grace_expiry_penalty_marks_owner_delinquent(api):
    """PRD §3.5: "Expiry stamps the late penalty onto late_penalty_cents
    (Section 3.6), sets penalty_paid to false, recomputes the owner's net
    outstanding_penalty_cents, and if that balance is now above zero sets the
    owner's status to DELINQUENT."

    Design: Difficulty/transitive_cascade/grace_expiry_penalty_marks_owner_delinquent
    """
    set_clock("2026-01-01T00:00:00Z")
    # Unaltered pet, final_fee 4000, issued 2026-01-01; advanced to 2027-02-10
    # → days_late=10 → penalty 2000.
    owner, pet, vr, lic = setup_expired_individual_license(
        pet_overrides={"is_altered": False, "name": "Duke"}
    )
    assert lic["status"] == "EXPIRED"
    assert lic["late_penalty_cents"] == 2000

    owner_after = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_after["outstanding_penalty_cents"] == 2000
    assert owner_after["status"] == "DELINQUENT"


def test_outstanding_penalty_net_excludes_settled_in_window_license(api):
    """PRD §2.8: "A license that has been moved to EXPIRED but whose penalty has
    since been settled in place (so its penalty_paid is true) is excluded from
    that sum even though it is still EXPIRED; the naive reading that would ignore
    penalty_paid and keep counting an already-settled penalty is wrong and
    over-states the balance."
    PRD §3.5: "Settlement sets penalty_paid to true while the license stays
    EXPIRED, recomputes the owner's net outstanding_penalty_cents (this license
    now drops out of the net sum because its penalty is paid even though it is
    still EXPIRED)".

    Design: Difficulty/dual_variant_calc/owner_outstanding_penalty_net_vs_gross
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner B", email="ob@x.com", address_zip="10002")
    # pet2 (unaltered) → final 4000; pet1 (altered) → final 2000.
    pet1 = create_pet(owner["id"], name="Bo", is_altered=True, species="DOG")
    pet2 = create_pet(owner["id"], name="Cleo", is_altered=False, species="CAT")
    vr1 = create_rabies_record(owner["id"], pet1["id"], expires_on="2030-06-01T00:00:00Z")
    vr2 = create_rabies_record(owner["id"], pet2["id"], expires_on="2030-06-01T00:00:00Z")

    l1 = create_draft_license(owner["id"], pet2["id"], license_kind="INDIVIDUAL", term_years=1)
    drive_license_to_active(owner["id"], l1["id"], vr2["id"])
    l2 = create_draft_license(owner["id"], pet1["id"], license_kind="INDIVIDUAL", term_years=1)
    drive_license_to_active(owner["id"], l2["id"], vr1["id"])

    # Both expire with days_late=10 → each late_penalty 2000 (neither capped:
    # l1 final 4000, l2 final 2000; both penalties 2000 <= respective final).
    advance_clock("2027-02-10T00:00:00Z")
    l1_exp = validate_success(api.get_license(l1["id"], CLERK), 200)
    l2_exp = validate_success(api.get_license(l2["id"], CLERK), 200)
    assert l1_exp["late_penalty_cents"] == 2000
    assert l2_exp["late_penalty_cents"] == 2000

    # Settle L1's penalty in place; it stays EXPIRED with penalty_paid=true.
    paid = validate_success(
        api.pay_penalty(l1["id"], {"pay_penalty_cents": 2000}, make_owner_headers(owner["id"])),
        200,
    )
    assert paid["penalty_paid"] is True
    assert paid["status"] == "EXPIRED"

    l2_still = validate_success(api.get_license(l2["id"], CLERK), 200)
    assert l2_still["status"] == "EXPIRED"
    assert l2_still["penalty_paid"] is False

    # NET reading: only L2's unpaid 2000 counts (L1 excluded though still EXPIRED).
    owner_after = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_after["outstanding_penalty_cents"] == 2000
    assert owner_after["status"] == "DELINQUENT"


def test_active_license_count_reconciles_after_issue(api):
    """PRD §2.8: "An owner's active_license_count is the number of that owner's
    licenses currently in ACTIVE status."
    PRD §3.4: "The owner's active_license_count is recomputed now that this
    license is ACTIVE".

    Design: Corner/cross_cutting_complexity_layers/derived_active_license_count_after_issue
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lic = setup_approved_individual_license(
        owner_overrides={"full_name": "XX Owner", "email": "xx@x.com"},
        pet_overrides={"is_altered": True, "name": "Count"},
    )
    validate_success(api.issue_tag(lic["id"], CLERK), 200)

    owner_after = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_after["active_license_count"] == 1


def test_issue_tag_changes_visible_same_response(api):
    """PRD §3.4: "A LicensingClerk issues the tag that brings a license to life,
    advancing it APPROVED -> ACTIVE."
    PRD §3.4: "The license's own issued_on is set to the current time and its
    expires_on is set to that issued_on plus term_years."

    Design: Corner/consistency_model/issue_tag_changes_visible_same_response
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lic = setup_approved_individual_license(
        owner_overrides={"full_name": "YY Owner", "email": "yy@x.com"},
        pet_overrides={"is_altered": True, "name": "Imm"},
    )
    issued = validate_success(api.issue_tag(lic["id"], CLERK), 200)
    assert issued["status"] == "ACTIVE"
    assert issued["tag_serial"] is not None
    assert issued["issued_on"] is not None


def test_pet_deceased_revokes_approved_license_in_cascade(api):
    """PRD §3.1: "every license of that pet currently in ACTIVE, GRACE, or
    APPROVED is forced to REVOKED".
    PRD §3.1: "an action only the pet's owner may take, and only while the pet is
    ACTIVE (otherwise ERR_INVALID_STATE) - the pet moves ACTIVE -> DECEASED".

    Companion: the cascade reaches an APPROVED (not-yet-ACTIVE) license too, which
    a same-trigger cascade limited to ACTIVE licenses would miss.

    Design: Difficulty/transitive_cascade/pet_deceased_revokes_license_voids_tag_recounts_owner
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lic = setup_approved_individual_license(
        owner_overrides={"full_name": "Owner E2", "email": "oe2@x.com"},
        pet_overrides={"is_altered": True, "name": "Pax2"},
    )
    lic_before = validate_success(api.get_license(lic["id"], CLERK), 200)
    assert lic_before["status"] == "APPROVED"

    deceased = validate_success(
        api.mark_pet_deceased(pet["id"], make_owner_headers(owner["id"])), 200
    )
    assert deceased["status"] == "DECEASED"

    lic_after = validate_success(api.get_license(lic["id"], CLERK), 200)
    assert lic_after["status"] == "REVOKED"


def test_grace_expiry_recomputes_owner_outstanding_penalty(api):
    """PRD §3.5: "Expiry stamps the late penalty onto late_penalty_cents
    (Section 3.6), sets penalty_paid to false, recomputes the owner's net
    outstanding_penalty_cents".
    PRD §3.6: "if the days late are at most 30, the rate is 2 dollars (200 cents)
    per day".

    Companion: this asserts the hop-1 derived-field side effect
    (outstanding_penalty_cents stamped equal to the license's penalty) on a
    distinct numeric value reached via a longer lateness window.

    Design: Difficulty/transitive_cascade/grace_expiry_penalty_marks_owner_delinquent
    """
    set_clock("2026-01-01T00:00:00Z")
    # days_late=20 → penalty 20*200 = 4000, capped at final_fee 4000 → 4000.
    owner, pet, vr, lic = setup_expired_individual_license(
        owner=create_owner(full_name="Owner F2", email="of2@x.com", address_zip="60002"),
        pet_overrides={"is_altered": False, "name": "Duke2"},
        expiry_clock="2027-02-20T00:00:00Z",
    )
    assert lic["status"] == "EXPIRED"
    assert lic["late_penalty_cents"] == 4000

    owner_after = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_after["outstanding_penalty_cents"] == 4000
    assert owner_after["status"] == "DELINQUENT"


def test_pay_penalty_clears_owner_to_active_via_net_reading(api):
    """PRD §3.5: "Settlement sets penalty_paid to true while the license stays
    EXPIRED, recomputes the owner's net outstanding_penalty_cents ... and clears
    the owner back to ACTIVE standing if that balance has reached zero."
    PRD §2.8: "An owner is DELINQUENT exactly when this net outstanding balance is
    greater than zero, and ACTIVE again the moment it returns to zero."

    Companion: the net reading drops the single settled license to zero, returning
    the owner to ACTIVE — the gross reading (still counting the settled penalty)
    would keep the owner DELINQUENT.

    Design: Difficulty/dual_variant_calc/owner_outstanding_penalty_net_vs_gross
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lic = setup_expired_individual_license(
        owner=create_owner(full_name="Owner B2", email="ob2@x.com", address_zip="10004"),
        pet_overrides={"is_altered": False, "name": "Solo"},
    )
    assert lic["late_penalty_cents"] == 2000
    owner_delinquent = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_delinquent["status"] == "DELINQUENT"
    assert owner_delinquent["outstanding_penalty_cents"] == 2000

    validate_success(
        api.pay_penalty(lic["id"], {"pay_penalty_cents": 2000}, make_owner_headers(owner["id"])),
        200,
    )
    owner_after = validate_success(api.get_owner(owner["id"], CLERK), 200)
    assert owner_after["outstanding_penalty_cents"] == 0
    assert owner_after["status"] == "ACTIVE"


def _list_license_tags(api, license_id):
    from test_helpers import validate_paginated
    res = api.list_license_tags(license_id, CLERK)
    # Tags list is paginated like every collection endpoint (PRD §2.3).
    return validate_paginated(res)
