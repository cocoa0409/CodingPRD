"""State-machine fork/cycle and transitive-cascade difficulty tests.

Queue A:
  non_linear_state_machine:
    - blood_unit_reserve_unreserve_cycle
    - donation_collected_branch_fork_releasable_vs_discarded
  transitive_cascade:
    - recall_cascade_donation_unit_inventory_deferral_depth4
    - test_positive_cascade_donation_unit_deferral_depth3
"""
from test_helpers import (
    api_client,
    validate_success, get_success_data,
    create_test_result_payload, create_blood_unit_payload, create_recall_event_payload,
    create_inventory_bucket_payload, advance_clock_payload,
    setup_labeled_unit, setup_available_unit, setup_collected_donation,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]
LAB = TEST_USERS["lab_technician_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ─── blood_unit_reserve_unreserve_cycle ───────────────────────────────────────
def test_unit_returns_to_available_after_reserve_then_unreserve(api):
    """PRD §3.7: "Unreserving requires the unit to be RESERVED, else ERR_UNIT_NOT_RESERVED;
    it returns the unit to AVAILABLE, decrements reserved_count by one, and increments
    available_count by one."

    Reserve then unreserve an AVAILABLE unit; status returns to AVAILABLE (cycle closed).

    Design: Difficulty/non_linear_state_machine/blood_unit_reserve_unreserve_cycle
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(din="DIN-CYC-001")
    reserved = validate_success(api.reserve_blood_unit(unit["id"], INV), 200)
    assert reserved["status"] == "RESERVED"

    unreserved = validate_success(api.unreserve_blood_unit(unit["id"], INV), 200)
    assert unreserved["status"] == "AVAILABLE", "unreserve returns the unit to AVAILABLE (cycle closed)"


def test_reserve_decrements_available_and_unreserve_restores_bucket(api):
    """PRD §3.7: "A successful reservation moves the unit from AVAILABLE to RESERVED,
    decrements the bucket's available_count by one, and increments its reserved_count by one."
    PRD §3.7: "it returns the unit to AVAILABLE, decrements reserved_count by one, and
    increments available_count by one."

    The bucket counts track the AVAILABLE->RESERVED->AVAILABLE cycle and reconcile back.

    Design: Difficulty/non_linear_state_machine/blood_unit_reserve_unreserve_cycle
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        din="DIN-CYC-002", donor_overrides={"blood_type": "O_POS"})
    bucket = get_success_data(api.create_inventory_bucket(
        create_inventory_bucket_payload(center["id"], blood_type="O_POS", component="RBC"), INV))
    assert bucket["available_count"] == 1 and bucket["reserved_count"] == 0

    api.reserve_blood_unit(unit["id"], INV)
    mid = validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)
    assert mid["available_count"] == 0 and mid["reserved_count"] == 1

    api.unreserve_blood_unit(unit["id"], INV)
    after = validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)
    assert after["available_count"] == 1 and after["reserved_count"] == 0, (
        "available_count and reserved_count restored to pre-reserve values")


# ─── donation_collected_branch_fork_releasable_vs_discarded ───────────────────
def test_positive_test_forks_donation_to_discarded_with_unit_and_deferral_effects(api):
    """PRD §3.6: "When the panel is POSITIVE or INDETERMINATE, the donation transitions
    from COLLECTED to DISCARDED, and every QUARANTINED blood unit of that donation is
    discarded (moving to DISCARDED with no inventory change, as those units were never
    AVAILABLE). A POSITIVE result has one further cascade: a PERMANENT deferral of
    category INFECTIOUS_RISK is auto-raised for the donor, driving their
    eligibility_status to PERM_DEFERRED."

    Design: Difficulty/non_linear_state_machine/donation_collected_branch_fork_releasable_vs_discarded
    """
    center, donor, slot, appt, donation, unit = setup_labeled_unit(
        din="DIN-POS-001", donor_overrides={"blood_type": "AB_POS", "weight_kg": 72})
    validate_success(api.create_test_result(
        donation["id"], create_test_result_payload(panel_outcome="POSITIVE"), LAB), 201)

    don_after = validate_success(api.get_donation(donation["id"], LAB), 200)
    assert don_after["status"] == "DISCARDED", "POSITIVE branch -> DISCARDED, not RELEASABLE"
    unit_after = validate_success(api.get_blood_unit(unit["id"], LAB), 200)
    assert unit_after["status"] == "DISCARDED", "QUARANTINED unit discarded, never AVAILABLE"
    donor_after = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert donor_after["eligibility_status"] == "PERM_DEFERRED", "POSITIVE-branch permanent deferral"


def test_negative_test_forks_donation_to_releasable_with_unit_available(api):
    """PRD §3.6: "When the panel is NEGATIVE and no severe reaction blocks it, the
    donation transitions from COLLECTED to RELEASABLE, and every QUARANTINED blood unit
    of that donation is released to AVAILABLE ..."

    The opposite fork: a NEGATIVE panel sends the donation to RELEASABLE and its unit to
    AVAILABLE — the divergent branch side-effect set from the POSITIVE case.

    Design: Difficulty/non_linear_state_machine/donation_collected_branch_fork_releasable_vs_discarded
    """
    center, donor, slot, appt, donation, unit = setup_labeled_unit(
        din="DIN-NEG-001", donor_overrides={"blood_type": "AB_POS", "weight_kg": 72})
    validate_success(api.create_test_result(
        donation["id"], create_test_result_payload(panel_outcome="NEGATIVE"), LAB), 201)

    don_after = validate_success(api.get_donation(donation["id"], LAB), 200)
    assert don_after["status"] == "RELEASABLE", "NEGATIVE branch -> RELEASABLE"
    unit_after = validate_success(api.get_blood_unit(unit["id"], LAB), 200)
    assert unit_after["status"] == "AVAILABLE", "released unit becomes AVAILABLE"


# ─── recall_cascade_donation_unit_inventory_deferral_depth4 ───────────────────
def test_recall_positive_retest_cascades_four_hops(api):
    """PRD §3.8: "Second, each in-scope donation that is not already DISCARDED is moved to
    DISCARDED. Third, each non-terminal blood unit of those donations — those in
    QUARANTINED, AVAILABLE, or RESERVED status — is transitioned to RECALLED; for each
    such unit that was AVAILABLE the matching bucket's available_count is decremented ...
    Fourth, if the reason is POSITIVE_RETEST, a PERMANENT deferral of category
    INFECTIOUS_RISK is auto-raised for the donor and their eligibility_status is driven
    to PERM_DEFERRED."

    A donor's one AVAILABLE O_POS/RBC unit (bucket available_count 1) is recalled by a
    POSITIVE_RETEST event whose 60-day lookback covers the 2025-01-01 donation.

    Design: Difficulty/transitive_cascade/recall_cascade_donation_unit_inventory_deferral_depth4
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        din="DIN-REC-001", donor_overrides={"blood_type": "O_POS", "weight_kg": 78})
    bucket = get_success_data(api.create_inventory_bucket(
        create_inventory_bucket_payload(center["id"], blood_type="O_POS", component="RBC"), INV))
    assert bucket["available_count"] == 1
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-01-31T00:00:00.000Z"), ADMIN))

    recall = validate_success(api.create_recall_event(
        create_recall_event_payload(center["id"], donor["id"], reason="POSITIVE_RETEST", lookback_days=60), INV), 201)
    assert recall["donations_in_scope_count"] == 1
    assert recall["units_recalled_count"] == 1

    assert validate_success(api.get_donation(donation["id"], INV), 200)["status"] == "DISCARDED"  # hop1
    assert validate_success(api.get_blood_unit(unit["id"], INV), 200)["status"] == "RECALLED"     # hop2
    assert validate_success(api.get_inventory_bucket(bucket["id"], INV), 200)["available_count"] == 0  # hop3
    assert validate_success(api.get_donor(donor["id"], NURSE), 200)["eligibility_status"] == "PERM_DEFERRED"  # hop4


def test_recall_closes_after_cascade(api):
    """PRD §3.8: "The recall runs its cascade synchronously and then closes; its status
    moves from OPEN to CLOSED in a single operation."
    PRD §3.8: "for each such unit that was AVAILABLE the matching bucket's available_count
    is decremented ... and units_recalled_count is incremented accordingly."

    The recall event ends CLOSED with units_recalled_count reflecting the one AVAILABLE
    unit moved to RECALLED.

    Design: Difficulty/transitive_cascade/recall_cascade_donation_unit_inventory_deferral_depth4
    """
    center, donor, slot, appt, donation, unit = setup_available_unit(
        din="DIN-REC-002", donor_overrides={"blood_type": "O_POS", "weight_kg": 78})
    get_success_data(api.create_inventory_bucket(
        create_inventory_bucket_payload(center["id"], blood_type="O_POS", component="RBC"), INV))
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-01-31T00:00:00.000Z"), ADMIN))

    recall = validate_success(api.create_recall_event(
        create_recall_event_payload(center["id"], donor["id"], reason="POSITIVE_RETEST", lookback_days=60), INV), 201)
    assert recall["status"] == "CLOSED"
    assert recall["units_recalled_count"] == 1


# ─── test_positive_cascade_donation_unit_deferral_depth3 ──────────────────────
def test_positive_test_result_cascades_three_hops(api):
    """PRD §3.6: "When the panel is POSITIVE or INDETERMINATE, the donation transitions
    from COLLECTED to DISCARDED, and every QUARANTINED blood unit of that donation is
    discarded ... A POSITIVE result has one further cascade: a PERMANENT deferral of
    category INFECTIOUS_RISK is auto-raised for the donor, driving their
    eligibility_status to PERM_DEFERRED."

    Recording a POSITIVE panel drives donation DISCARDED (hop1) -> QUARANTINED unit
    DISCARDED (hop2) -> PERMANENT INFECTIOUS_RISK deferral, donor PERM_DEFERRED (hop3).

    Design: Difficulty/transitive_cascade/test_positive_cascade_donation_unit_deferral_depth3
    """
    center, donor, slot, appt, donation, unit = setup_labeled_unit(
        donation_type="WHOLE", component="PLASMA", din="DIN-TP-001",
        donor_overrides={"blood_type": "B_NEG", "weight_kg": 68})
    validate_success(api.create_test_result(
        donation["id"], create_test_result_payload(panel_outcome="POSITIVE"), LAB), 201)

    assert validate_success(api.get_donation(donation["id"], LAB), 200)["status"] == "DISCARDED"  # hop1
    assert validate_success(api.get_blood_unit(unit["id"], LAB), 200)["status"] == "DISCARDED"    # hop2
    assert validate_success(api.get_donor(donor["id"], NURSE), 200)["eligibility_status"] == "PERM_DEFERRED"  # hop3


def test_positive_test_result_raises_permanent_infectious_deferral(api):
    """PRD §3.6: "A POSITIVE result has one further cascade: a PERMANENT deferral of
    category INFECTIOUS_RISK is auto-raised for the donor, driving their
    eligibility_status to PERM_DEFERRED."

    The cascade's deferral leg: a donor-scoped deferral exists with category
    INFECTIOUS_RISK and kind PERMANENT after the POSITIVE test.

    Design: Difficulty/transitive_cascade/test_positive_cascade_donation_unit_deferral_depth3
    """
    center, donor, slot, appt, donation, unit = setup_labeled_unit(
        donation_type="WHOLE", component="PLASMA", din="DIN-TP-002",
        donor_overrides={"blood_type": "B_NEG", "weight_kg": 68})
    validate_success(api.create_test_result(
        donation["id"], create_test_result_payload(panel_outcome="POSITIVE"), LAB), 201)

    deferrals = validate_success(api.list_deferrals(NURSE, params={"donor_id": donor["id"]}), 200)
    assert any(d["category"] == "INFECTIOUS_RISK" and d["kind"] == "PERMANENT" for d in deferrals), (
        "POSITIVE cascade auto-raises a PERMANENT INFECTIOUS_RISK deferral")
