"""Safety inspection priority pair (queue A) and inspection corner cases
(queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_donor, make_bike, triage_bike, make_part, restock_part,
    make_apprentice, make_journeyman, make_lead_and_inspector, log_usage,
    full_checklist,
    TEST_USERS, make_volunteer_headers, make_volunteer,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _safety_review_bike(donor, lead, serial: str, part_name: str = "Pads",
                        part_cost: int = 100, part_category: str = "BRAKES"):
    """Bike driven to SAFETY_REVIEW under `lead` with one committed usage."""
    bike = make_bike(donor["id"], serial_number=serial)
    triage_bike(bike["id"], "B", False)
    validate_success(
        api_client.route_bike(
            bike["id"],
            {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead["id"]},
            COORD,
        )
    )
    part = make_part(name=part_name, category=part_category, unit_cost_cents=part_cost)
    part = restock_part(part["id"], 10)
    log_usage(bike["id"], part["id"], 1, part["version"], lead["id"])
    validate_success(
        api_client.submit_safety(bike["id"], make_volunteer_headers(lead["id"]))
    )
    return bike


def test_safety_beats_constraint_on_inspection():
    """PRD §2.7: "After state checks pass, the safety and segregation-of-duties
    rules run: `ERR_INSPECTOR_IS_REFURB_LEAD`, `ERR_CHECKLIST_INCONSISTENT`,
    `ERR_HELMET_REQUIRED` (all HTTP 422), and the two HTTP 403 duty-segregation
    codes `ERR_REVIEWER_IS_LOGGER` and `ERR_FULFILLER_IS_APPROVER`. Business
    constraints come next — uniqueness, grade routing, eligibility, capacity,
    enrollment, reservation, and quantity rules (detailed in §3)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_inspection
    """
    donor = make_donor(display_name="D SoD", donor_type="INDIVIDUAL", email="dsod@x.org")
    lead = make_apprentice()  # refurb lead is APPRENTICE — below JOURNEYMAN too
    bike = _safety_review_bike(donor, lead, serial="SN-SD", part_name="Brake pads",
                               part_cost=400)
    # the refurb lead (APPRENTICE, below JOURNEYMAN) inspects their own bike:
    # both ERR_INSPECTOR_IS_REFURB_LEAD and ERR_INSPECTOR_SKILL_INSUFFICIENT
    # hold; safety priority wins.
    r = api_client.create_safety_inspection(
        bike["id"],
        {"result": "PASS", "checklist": full_checklist(True)},
        make_volunteer_headers(lead["id"]),
    )
    validate_error(r, ApiErrorId.ERR_INSPECTOR_IS_REFURB_LEAD)
    bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
    assert bike_after["status"] == "SAFETY_REVIEW"
    lead_after = validate_success(api_client.get_volunteer(lead["id"], COORD))
    assert lead_after["inspections_conducted"] == 0


def test_safety_priority_pair_no_inspection_persisted():
    """PRD §3.4: "must not be the bike's refurb lead (else
    `ERR_INSPECTOR_IS_REFURB_LEAD`, per §2.9)" and PRD §2.7: "After state checks
    pass, the safety and segregation-of-duties rules run:
    `ERR_INSPECTOR_IS_REFURB_LEAD`, `ERR_CHECKLIST_INCONSISTENT`,
    `ERR_HELMET_REQUIRED` (all HTTP 422)". A rejected inspection creates no
    SafetyInspection row and leaves the bike in SAFETY_REVIEW.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_inspection
    """
    from test_helpers import validate_paginated
    donor = make_donor(display_name="D SoD2", donor_type="INDIVIDUAL",
                       email="dsod2@x.org")
    lead = make_apprentice()
    bike = _safety_review_bike(donor, lead, serial="SN-SD2", part_name="Brake pads 2",
                               part_cost=400)
    r = api_client.create_safety_inspection(
        bike["id"],
        {"result": "PASS", "checklist": full_checklist(True)},
        make_volunteer_headers(lead["id"]),
    )
    validate_error(r, ApiErrorId.ERR_INSPECTOR_IS_REFURB_LEAD)
    _, meta = validate_paginated(
        api_client.list_safety_inspections(COORD, params={"bike_id": bike["id"]})
    )
    assert meta["total_count"] == 0
    bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
    assert bike_after["status"] == "SAFETY_REVIEW"


def test_checklist_inconsistent_with_pass():
    """PRD §3.4: "A `PASS` result requires every checklist item to be true; a
    passing claim with any item false is rejected with
    `ERR_CHECKLIST_INCONSISTENT`." and "On `FAIL`, the bike loops back
    `SAFETY_REVIEW → IN_REFURBISHMENT` for rework".

    Design: Corner/validations/checklist_inconsistent_with_pass
    """
    donor = make_donor(display_name="D CK", donor_type="INDIVIDUAL", email="dck@x.org")
    lead, insp = make_lead_and_inspector()
    bike = _safety_review_bike(donor, lead, serial="SN-CK", part_name="Pads",
                               part_cost=100)
    bad_checklist = {"brakes": False, "steering": True, "tires": True,
                     "drivetrain": True, "reflectors": True}
    r = api_client.create_safety_inspection(
        bike["id"], {"result": "PASS", "checklist": bad_checklist},
        make_volunteer_headers(insp["id"]),
    )
    validate_error(r, ApiErrorId.ERR_CHECKLIST_INCONSISTENT)
    ok = validate_success(
        api_client.create_safety_inspection(
            bike["id"], {"result": "FAIL", "checklist": bad_checklist},
            make_volunteer_headers(insp["id"]),
        ),
        expected_status=201,
    )
    assert ok["result"] == "FAIL"
    bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
    assert bike_after["status"] == "IN_REFURBISHMENT"
    assert bike_after["rework_count"] == 1


def test_inspector_below_journeyman_alone():
    """PRD §3.4: "The inspector must hold `JOURNEYMAN` or `LEAD_MECHANIC` skill
    — anything less is rejected with `ERR_INSPECTOR_SKILL_INSUFFICIENT`".

    Design: Corner/validations/inspector_below_journeyman_alone
    """
    donor = make_donor(display_name="D IG", donor_type="INDIVIDUAL", email="dig@x.org")
    lead = make_apprentice()
    other_apprentice = make_apprentice()  # not the lead
    bike = _safety_review_bike(donor, lead, serial="SN-IG", part_name="Tube 27",
                               part_cost=100, part_category="TIRES")
    r = api_client.create_safety_inspection(
        bike["id"], {"result": "PASS", "checklist": full_checklist(True)},
        make_volunteer_headers(other_apprentice["id"]),
    )
    validate_error(r, ApiErrorId.ERR_INSPECTOR_SKILL_INSUFFICIENT)
    bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
    assert bike_after["status"] == "SAFETY_REVIEW"


def test_inspector_identity_taken_from_header():
    """PRD §3.4: "Inspection is performed by a volunteer caller whose own id
    becomes `inspector_volunteer_id`." and "Either way, the inspector's
    `inspections_conducted` count increases by 1."

    Design: Corner/rbac/inspector_identity_taken_from_header
    """
    donor = make_donor(display_name="D IH", donor_type="INDIVIDUAL", email="dih@x.org")
    lead, insp = make_lead_and_inspector()
    bike = _safety_review_bike(donor, lead, serial="SN-IH", part_name="Valve",
                               part_cost=60, part_category="TIRES")
    created = validate_success(
        api_client.create_safety_inspection(
            bike["id"], {"result": "PASS", "checklist": full_checklist(True)},
            make_volunteer_headers(insp["id"]),
        ),
        expected_status=201,
    )
    assert created["inspector_volunteer_id"] == insp["id"]
    insp_after = validate_success(api_client.get_volunteer(insp["id"], COORD))
    assert insp_after["inspections_conducted"] == 1
    bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
    assert bike_after["status"] == "READY_FOR_DISPOSITION"
