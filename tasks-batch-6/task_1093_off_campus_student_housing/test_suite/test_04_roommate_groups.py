"""Roommate matching, group lifecycle, placement cascade, and unit-version OCC.

Translates the group entries of the corner `state_machines` section, the
`occ_stale_unit_version_on_group_place_rejected` corner instance
(cross_cutting_complexity_layers), and two difficulty instances:
`roommate_pairwise_mean_vs_lead_anchored_mean_diverge` and
`group_placement_five_hop_cascade_to_property_posture` (queue A).
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import make_student_headers

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]

TERM = {"term_start_date": "2026-08-15", "term_end_date": "2027-08-01", "installment_count": 10}

# Attributes of the canonical four-student divergence fixture.
FOUR = [
    ("ava@su.edu", "Ava Lead", dict(cleanliness_level=4, noise_tolerance=3, sleep_schedule="EARLY", smoker=False)),
    ("ben@su.edu", "Ben Two", dict(cleanliness_level=3, noise_tolerance=4, sleep_schedule="EARLY", smoker=False)),
    ("cara@su.edu", "Cara Three", dict(cleanliness_level=5, noise_tolerance=2, sleep_schedule="LATE", smoker=False)),
    ("dan@su.edu", "Dan Four", dict(cleanliness_level=4, noise_tolerance=3, sleep_schedule="EARLY", smoker=False)),
]


def _four_verified(api, base):
    students = []
    for email, name, attrs in FOUR:
        students.append(fx.verified_student(api, base["uni"]["id"], email, full_name=name, **attrs))
    return students


def test_membership_and_group_match_scores_diverge(api):
    """PRD §3.3: "stamps its match_score as the lead-anchored pair score between
    the invitee and the lead." PRD §3.3: "The average_match_score is the
    pairwise-mean reading ... The lead_anchored_mean_score is the lead-anchored
    reading ... These two readings of the same member set diverge".

    Design: Difficulty/dual_variant_calc/roommate_pairwise_mean_vs_lead_anchored_mean_diverge
    """
    base = fx.base_property(api)
    s = _four_verified(api, base)
    group, memberships = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s[0]["id"], [s[1]["id"], s[2]["id"], s[3]["id"]], 4, name="Maple Four")
    assert memberships[0]["match_score"] == 80  # S1-S2
    assert memberships[1]["match_score"] == 55  # S1-S3
    assert memberships[2]["match_score"] == 100  # S1-S4
    locked = validate_success(api.lock_group(group["id"], make_student_headers(s[0]["id"])), 200)
    assert locked["average_match_score"] == 68
    assert locked["lead_anchored_mean_score"] == 84
    assert locked["average_match_score"] != locked["lead_anchored_mean_score"]


def test_group_lock_stamps_scores_and_locks(api):
    """PRD §3.3: "A successful lock moves the group FORMING -> LOCKED." PRD
    §3.3: "recomputing the group's accepted_member_count (which counts
    memberships in ACCEPTED or PLACED)."

    Design: Difficulty/dual_variant_calc/roommate_pairwise_mean_vs_lead_anchored_mean_diverge
    """
    base = fx.base_property(api)
    s = _four_verified(api, base)
    group, _ = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s[0]["id"], [s[1]["id"], s[2]["id"], s[3]["id"]], 4, name="Maple Four")
    locked = validate_success(api.lock_group(group["id"], make_student_headers(s[0]["id"])), 200)
    assert locked["status"] == "LOCKED"
    assert locked["accepted_member_count"] == 4


def test_group_membership_second_response_rejected(api):
    """PRD §3.3: "Responding while the group is not FORMING, or on a membership
    no longer INVITED, is refused - the latter with
    ERR_MEMBERSHIP_INVALID_STATE." PRD §3.3: "Inviting a student who already
    holds an INVITED, ACCEPTED, or PLACED membership on the group is refused
    with ERR_DUPLICATE_MEMBERSHIP".

    Design: Corner/state_machines/group_membership_second_response_rejected
    """
    base = fx.base_property(api)
    s1 = fx.create_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    s2 = fx.create_student(api, base["uni"]["id"], "ben@su.edu", full_name="Ben Two",
                           cleanliness_level=3, noise_tolerance=4)
    group = validate_success(api.create_roommate_group(
        {"property_id": base["prop"]["id"], "name": "Maple Two", "required_size": 2},
        make_student_headers(s1["id"])), 201)
    m2 = validate_success(api.invite_to_group(group["id"], {"student_id": s2["id"]},
                          make_student_headers(s1["id"])), 201)
    api.respond_membership(m2["id"], {"decision": "ACCEPT"}, make_student_headers(s2["id"]))
    validate_error(api.respond_membership(m2["id"], {"decision": "DECLINE"},
                   make_student_headers(s2["id"])), ApiErrorId.ERR_MEMBERSHIP_INVALID_STATE.value)
    m2r = api.get_membership(m2["id"], ADMIN).json()["data"]
    assert m2r["status"] == "ACCEPTED" and m2r["sequence_number"] == 2
    validate_error(api.invite_to_group(group["id"], {"student_id": s2["id"]},
                   make_student_headers(s1["id"])), ApiErrorId.ERR_DUPLICATE_MEMBERSHIP.value)
    assert api.get_roommate_group(group["id"], ADMIN).json()["data"]["accepted_member_count"] == 2
    _, meta = validate_paginated(api.list_memberships(ADMIN, params={"group_id": group["id"]}))
    assert meta["total_count"] == 2


def test_group_lock_requires_exact_accepted_member_count(api):
    """PRD §3.3: "The lead locks a FORMING group, which requires that
    accepted_member_count equals required_size (otherwise
    ERR_GROUP_SIZE_MISMATCH)." PRD §3.3: "Both average_match_score and
    lead_anchored_mean_score are null until the group is locked."

    Design: Corner/state_machines/group_lock_requires_exact_accepted_member_count
    """
    base = fx.base_property(api)
    s1 = fx.create_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    s4 = fx.create_student(api, base["uni"]["id"], "dan@su.edu", full_name="Dan Four")
    group, _ = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s1["id"], [s4["id"]], 3, name="Maple Three")
    validate_error(api.lock_group(group["id"], make_student_headers(s1["id"])),
                   ApiErrorId.ERR_GROUP_SIZE_MISMATCH.value)
    g = api.get_roommate_group(group["id"], ADMIN).json()["data"]
    assert g["status"] == "FORMING" and g["accepted_member_count"] == 2 and g["required_size"] == 3
    assert g["average_match_score"] is None and g["lead_anchored_mean_score"] is None


def test_group_lock_below_minimum_pairwise_score_rejected(api):
    """PRD §3.3: "The result is clamped to lie between 0 and 100." PRD §3.3:
    "The lock gate is on the pairwise mean: average_match_score must be at least
    55, or the lock is refused with ERR_GROUP_MATCH_SCORE_TOO_LOW."

    Design: Corner/state_machines/group_lock_below_minimum_pairwise_score_rejected
    """
    base = fx.base_property(api)
    s1 = fx.create_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    s2 = fx.create_student(api, base["uni"]["id"], "ben@su.edu", full_name="Ben Two",
                           cleanliness_level=3, noise_tolerance=4)
    s4 = fx.create_student(api, base["uni"]["id"], "dan@su.edu", full_name="Dan Four")
    s5 = fx.create_student(api, base["uni"]["id"], "eli@su.edu", full_name="Eli Five",
                           cleanliness_level=1, noise_tolerance=5, sleep_schedule="LATE", smoker=True)
    group = validate_success(api.create_roommate_group(
        {"property_id": base["prop"]["id"], "name": "Mismatch Four", "required_size": 4},
        make_student_headers(s1["id"])), 201)
    api.invite_to_group(group["id"], {"student_id": s2["id"]}, make_student_headers(s1["id"]))
    api.invite_to_group(group["id"], {"student_id": s4["id"]}, make_student_headers(s1["id"]))
    m5 = validate_success(api.invite_to_group(group["id"], {"student_id": s5["id"]},
                          make_student_headers(s1["id"])), 201)
    # PRD §3.3 kernel, lead(3/3/EARLY/no-smoke) vs s5(1/5/LATE/smoke):
    # 100 - 12*2 - 8*2 - 25 - 30 = 5 (positive, so no clamp).
    assert m5["match_score"] == 5
    # accept all three invitees
    ms, _ = validate_paginated(api.list_memberships(ADMIN, params={"group_id": group["id"]}))
    for m in ms:
        if m["status"] == "INVITED":
            api.respond_membership(m["id"], {"decision": "ACCEPT"},
                                   make_student_headers(m["student_id"]))
    validate_error(api.lock_group(group["id"], make_student_headers(s1["id"])),
                   ApiErrorId.ERR_GROUP_MATCH_SCORE_TOO_LOW.value)
    g = api.get_roommate_group(group["id"], ADMIN).json()["data"]
    assert g["status"] == "FORMING" and g["accepted_member_count"] == 4
    assert g["average_match_score"] is None


def test_group_place_state_scope_and_capacity_preconditions(api):
    """PRD §3.3: "Placing a group that is not LOCKED is ERR_GROUP_INVALID_STATE."
    PRD §3.3: "Placement requires that the unit's property_id equals the group's
    property_id (else ERR_UNIT_PROPERTY_MISMATCH) ... that the unit's
    available_bed_count is at least the group's required_size (else
    ERR_UNIT_CAPACITY_INSUFFICIENT)".

    Design: Corner/state_machines/group_place_state_scope_and_capacity_preconditions
    """
    base = fx.base_property(api)  # prop1 with 4-bed unit1
    unit3 = fx.create_unit(api, base["prop"]["id"], unit_number="103", floorplan_code="2x1",
                           bedroom_count=2, bathroom_count=1, bed_labels=["A", "B"],
                           base_rent_cents_per_bed_monthly=80000)
    prop2 = fx.create_property(api, base["uni"]["id"], name="Birch House")
    unitb = fx.create_unit(api, prop2["id"], unit_number="1", floorplan_code="2x1",
                           bedroom_count=2, bathroom_count=1, bed_labels=["A", "B"],
                           base_rent_cents_per_bed_monthly=70000)
    fx.list_property(api, prop2["id"])
    s = _four_verified(api, base)
    group, _ = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s[0]["id"], [s[1]["id"], s[2]["id"], s[3]["id"]], 4, name="Maple Four")
    api.lock_group(group["id"], make_student_headers(s[0]["id"]))
    # A FORMING second group.
    g2 = validate_success(api.create_roommate_group(
        {"property_id": base["prop"]["id"], "name": "Solo Pair", "required_size": 2},
        make_student_headers(s[1]["id"])), 201)
    unit1_v = fx.get_unit(api, base["unit"]["id"])["version"]
    unit3_v = fx.get_unit(api, unit3["id"])["version"]
    unitb_v = fx.get_unit(api, unitb["id"])["version"]
    # placing a FORMING group -> ERR_GROUP_INVALID_STATE
    validate_error(api.place_group(g2["id"], {"unit_id": base["unit"]["id"],
                   "expected_unit_version": unit1_v, **TERM}, MGR),
                   ApiErrorId.ERR_GROUP_INVALID_STATE.value)
    # placing LOCKED group into other property's unit -> ERR_UNIT_PROPERTY_MISMATCH
    validate_error(api.place_group(group["id"], {"unit_id": unitb["id"],
                   "expected_unit_version": unitb_v, **TERM}, MGR),
                   ApiErrorId.ERR_UNIT_PROPERTY_MISMATCH.value)
    # placing 4-member group into 2-bed same-property unit -> ERR_UNIT_CAPACITY_INSUFFICIENT
    validate_error(api.place_group(group["id"], {"unit_id": unit3["id"],
                   "expected_unit_version": unit3_v, **TERM}, MGR),
                   ApiErrorId.ERR_UNIT_CAPACITY_INSUFFICIENT.value)
    ok = validate_success(api.place_group(group["id"], {"unit_id": base["unit"]["id"],
                          "expected_unit_version": unit1_v, **TERM}, MGR), 200)
    assert ok["status"] == "PLACED" and ok["placed_unit_id"] == base["unit"]["id"]
    assert fx.get_unit(api, unit3["id"])["leased_bed_count"] == 0
    assert fx.get_unit(api, unitb["id"])["leased_bed_count"] == 0
    u1 = fx.get_unit(api, base["unit"]["id"])
    assert u1["occupancy_status"] == "FULLY_LEASED"
    prop1 = fx.get_property(api, base["prop"]["id"])
    assert prop1["available_bed_count"] == 2  # unit3 still free
    assert prop1["status"] == "LISTED"


def test_group_placement_cascade_mints_leases_and_allocates_beds(api):
    """PRD §3.3: "each ACCEPTED membership - walked in ascending sequence_number
    order and zipped against the unit's vacant bed labels in lexicographic
    ascending order - becomes PLACED and mints a Lease in DRAFT that is
    immediately driven into its bed-holding state ... Each minted lease records
    its roommate_group_id."

    Design: Difficulty/transitive_cascade/group_placement_five_hop_cascade_to_property_posture
    """
    base = fx.base_property(api)
    s = _four_verified(api, base)
    group, _ = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s[0]["id"], [s[1]["id"], s[2]["id"], s[3]["id"]], 4, name="Maple Four")
    api.lock_group(group["id"], make_student_headers(s[0]["id"]))
    unit1_v = fx.get_unit(api, base["unit"]["id"])["version"]
    placed = validate_success(api.place_group(group["id"], {"unit_id": base["unit"]["id"],
                              "expected_unit_version": unit1_v, **TERM}, MGR), 200)
    assert placed["status"] == "PLACED" and placed["placed_unit_id"] == base["unit"]["id"]
    members, mmeta = validate_paginated(api.list_memberships(ADMIN, params={"group_id": group["id"]}))
    assert mmeta["total_count"] == 4 and all(m["status"] == "PLACED" for m in members)
    leases, lmeta = validate_paginated(api.list_leases(ADMIN, params={"roommate_group_id": group["id"]}))
    assert lmeta["total_count"] == 4
    for lease in leases:
        assert lease["lease_status"] == "PENDING_SIGNATURE"
        assert lease["monthly_rent_cents"] == 90000
        assert lease["guarantor_required"] is False
        assert lease["quoted_total_cents"] == 1080000
    bed_by_student = {lease["student_id"]: lease["bed_label"] for lease in leases}
    assert bed_by_student[s[0]["id"]] == "A"
    assert bed_by_student[s[1]["id"]] == "B"
    assert bed_by_student[s[2]["id"]] == "C"
    assert bed_by_student[s[3]["id"]] == "D"


def test_group_placement_cascades_to_property_fully_committed(api):
    """PRD §3.3: "the unit's leased_bed_count, available_bed_count, and
    occupancy_status are recomputed; then the property's available_bed_count is
    recomputed; then, if it reached 0, the property auto-transitions LISTED ->
    FULLY_COMMITTED. Placement increments the unit version by 1."

    Design: Difficulty/transitive_cascade/group_placement_five_hop_cascade_to_property_posture
    """
    base = fx.base_property(api)
    s = _four_verified(api, base)
    group, _ = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s[0]["id"], [s[1]["id"], s[2]["id"], s[3]["id"]], 4, name="Maple Four")
    api.lock_group(group["id"], make_student_headers(s[0]["id"]))
    unit1_v = fx.get_unit(api, base["unit"]["id"])["version"]
    api.place_group(group["id"], {"unit_id": base["unit"]["id"],
                    "expected_unit_version": unit1_v, **TERM}, MGR)
    unit = fx.get_unit(api, base["unit"]["id"])
    assert unit["leased_bed_count"] == 4 and unit["available_bed_count"] == 0
    assert unit["occupancy_status"] == "FULLY_LEASED"
    assert unit["version"] > unit1_v
    prop = fx.get_property(api, base["prop"]["id"])
    assert prop["available_bed_count"] == 0 and prop["total_bed_count"] == 4
    assert prop["status"] == "FULLY_COMMITTED"


def test_occ_stale_unit_version_on_group_place_rejected(api):
    """PRD §2.7: "Placing a locked roommate group into a unit requires
    expected_unit_version in the request body ... if that value does not match
    the unit's current version, the placement is rejected with ERR_STALE_VERSION
    (HTTP 412) ... a four-bed unit can host two two-person groups ... so a
    request carrying an up-to-date token succeeds".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_on_group_place_rejected
    """
    base = fx.base_property(api)
    s = _four_verified(api, base)
    g1, _ = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s[0]["id"], [s[1]["id"]], 2, name="Pair One")
    api.lock_group(g1["id"], make_student_headers(s[0]["id"]))
    g2, _ = fx.build_group_with_accepted_members(
        api, base["prop"]["id"], s[2]["id"], [s[3]["id"]], 2, name="Pair Two")
    api.lock_group(g2["id"], make_student_headers(s[2]["id"]))
    stale_v = fx.get_unit(api, base["unit"]["id"])["version"]
    first = validate_success(api.place_group(g1["id"], {"unit_id": base["unit"]["id"],
                             "expected_unit_version": stale_v, **TERM}, MGR), 200)
    assert first["status"] == "PLACED"
    validate_error(api.place_group(g2["id"], {"unit_id": base["unit"]["id"],
                   "expected_unit_version": stale_v, **TERM}, MGR),
                   ApiErrorId.ERR_STALE_VERSION.value)
    assert api.get_roommate_group(g2["id"], ADMIN).json()["data"]["status"] == "LOCKED"
    fresh_v = fx.get_unit(api, base["unit"]["id"])["version"]
    ok = validate_success(api.place_group(g2["id"], {"unit_id": base["unit"]["id"],
                          "expected_unit_version": fresh_v, **TERM}, MGR), 200)
    assert ok["status"] == "PLACED"
    unit = fx.get_unit(api, base["unit"]["id"])
    assert unit["occupancy_status"] == "FULLY_LEASED"
    assert fx.get_property(api, base["prop"]["id"])["status"] == "FULLY_COMMITTED"
    _, lmeta = validate_paginated(api.list_leases(ADMIN, params={"unit_id": base["unit"]["id"]}))
    assert lmeta["total_count"] == 4
