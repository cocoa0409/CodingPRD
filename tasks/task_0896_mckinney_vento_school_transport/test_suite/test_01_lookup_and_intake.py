"""Not-found lookups and student-intake behavior (corner: entities)."""
from test_helpers import (
    validate_error, validate_success, ApiErrorId, TEST_USERS,
    create_district, create_student,
)

SC = TEST_USERS["state_coordinator_headers"]

# UUIDs that resolve to nothing against an empty database.
NX = {
    "student": "00000000-0000-4000-8000-000000000001",
    "district": "00000000-0000-4000-8000-000000000002",
    "liaison": "00000000-0000-4000-8000-000000000003",
    "determination": "00000000-0000-4000-8000-000000000004",
    "plan": "00000000-0000-4000-8000-000000000005",
    "vehicle": "00000000-0000-4000-8000-000000000006",
    "trip": "00000000-0000-4000-8000-000000000007",
    "agreement": "00000000-0000-4000-8000-000000000008",
    "benefit": "00000000-0000-4000-8000-000000000009",
    "dispute": "00000000-0000-4000-8000-00000000000a",
    "referral": "00000000-0000-4000-8000-00000000000b",
    "ledger": "00000000-0000-4000-8000-00000000000c",
}

def test_get_nonexistent_student_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_LIAISON_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`"

    Design: Corner/entities/student_get_nonexistent_returns_not_found
    """
    resp = api.get_student(NX["student"], SC)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND.value, 404)


def test_get_nonexistent_district_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_DISTRICT_NOT_FOUND`, `ERR_LIAISON_NOT_FOUND`"

    Design: Corner/entities/district_get_nonexistent_returns_not_found
    """
    resp = api.get_district(NX["district"], SC)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_NOT_FOUND.value, 404)


def test_get_nonexistent_liaison_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_DISTRICT_NOT_FOUND`, `ERR_LIAISON_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`"

    Design: Corner/entities/liaison_get_nonexistent_returns_not_found
    """
    resp = api.get_liaison(NX["liaison"], SC)
    validate_error(resp, ApiErrorId.ERR_LIAISON_NOT_FOUND.value, 404)


def test_get_nonexistent_determination_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_STUDENT_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`"

    Design: Corner/entities/determination_get_nonexistent_returns_not_found
    """
    resp = api.get_determination(NX["determination"], SC)
    validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_FOUND.value, 404)


def test_get_nonexistent_plan_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_DETERMINATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`"

    Design: Corner/entities/plan_get_nonexistent_returns_not_found
    """
    resp = api.get_plan(NX["plan"], SC)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)


def test_get_nonexistent_vehicle_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_PLAN_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`"

    Design: Corner/entities/vehicle_get_nonexistent_returns_not_found
    """
    resp = api.get_vehicle(NX["vehicle"], SC)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND.value, 404)


def test_get_nonexistent_trip_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_VEHICLE_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`"

    Design: Corner/entities/trip_get_nonexistent_returns_not_found
    """
    resp = api.get_trip(NX["trip"], SC)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_FOUND.value, 404)


def test_get_nonexistent_agreement_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_TRIP_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_BENEFIT_LINK_NOT_FOUND`"

    Design: Corner/entities/agreement_get_nonexistent_returns_not_found
    """
    resp = api.get_agreement(NX["agreement"], SC)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value, 404)


def test_get_nonexistent_benefit_link_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_AGREEMENT_NOT_FOUND`, `ERR_BENEFIT_LINK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`"

    Design: Corner/entities/benefit_link_get_nonexistent_returns_not_found
    """
    resp = api.get_benefit_link(NX["benefit"], SC)
    validate_error(resp, ApiErrorId.ERR_BENEFIT_LINK_NOT_FOUND.value, 404)


def test_get_nonexistent_dispute_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_BENEFIT_LINK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`"

    Design: Corner/entities/dispute_get_nonexistent_returns_not_found
    """
    resp = api.get_dispute(NX["dispute"], SC)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_FOUND.value, 404)


def test_get_nonexistent_referral_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_DISPUTE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, and `ERR_LEDGER_ENTRY_NOT_FOUND`"

    Design: Corner/entities/referral_get_nonexistent_returns_not_found
    """
    resp = api.get_referral(NX["referral"], SC)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_FOUND.value, 404)


def test_get_nonexistent_ledger_entry_returns_not_found(api):
    """PRD §2.7: "the first unresolved reference returns that resource's
    specific not-found code (404)."
    PRD §2.7: "`ERR_REFERRAL_NOT_FOUND`, and `ERR_LEDGER_ENTRY_NOT_FOUND`"

    Design: Corner/entities/ledger_entry_get_nonexistent_returns_not_found
    """
    resp = api.get_ledger_entry(NX["ledger"], SC)
    validate_error(resp, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND.value, 404)


def test_intake_missing_living_situation_rejected(api):
    """PRD §2.7: "required fields present, enum values in range, all quantity integers non-negative, and any `scheduled_end` strictly after its `scheduled_start`; otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/student_create_missing_required_living_situation
    """
    d = create_district()
    payload = {
        "first_name": "No", "last_name": "Sit", "birthdate": "2012-01-01",
        "enrolled_district_id": d["id"], "origin_district_id": d["id"],
    }
    resp = api.create_student(payload, SC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_intake_invalid_living_situation_enum_rejected(api):
    """PRD §2.7: "required fields present, enum values in range, all quantity integers non-negative, and any `scheduled_end` strictly after its `scheduled_start`; otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/student_create_invalid_enum_living_situation_rejected
    """
    d = create_district()
    payload = {
        "first_name": "Bad", "last_name": "Enum", "birthdate": "2012-01-01",
        "enrolled_district_id": d["id"], "origin_district_id": d["id"],
        "living_situation": "MANSION",
    }
    resp = api.create_student(payload, SC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_intake_defaults_applied(api):
    """PRD §3.2: "Intake may optionally include a `self_declared_category` and a `records_received` flag; when omitted, `self_declared_category` defaults to `NONE` and `records_received` defaults to false."

    Design: Corner/entities/student_create_defaults_applied
    """
    d = create_district()
    s = create_student(d["id"], living_situation="DOUBLED_UP")
    data = validate_success(api.get_student(s["id"], SC))
    assert data["records_received"] is False, "records_received must default to false"
    assert data["self_declared_category"] == "NONE", "self_declared_category must default to NONE"


def test_intake_system_fields_forced(api):
    """PRD §3.2: "A freshly intaken student starts with enrollment `status` of `INTAKE`, `eligibility_status` of `UNDETERMINED`, an unset `liaison_id`, and a provisional priority score (§3.3)."
    PRD §3.3: "The provisional variant, computed at intake from the self-reported `living_situation`, assigns 50 points for `UNSHELTERED`, 40 for `SHELTER`, 35 for `FOSTER_PLACEMENT`, 30 for `HOTEL_MOTEL`, 20 for `DOUBLED_UP`, and 0 for `HOUSED`."

    Design: Corner/entities/student_create_system_fields_ignored
    """
    d = create_district()
    s = create_student(d["id"], living_situation="HOTEL_MOTEL")
    assert s["status"] == "INTAKE"
    assert s["eligibility_status"] == "UNDETERMINED"
    assert s["priority_basis"] == "PROVISIONAL"
    assert s["priority_score"] == 30, "HOTEL_MOTEL provisional priority is 30"


def test_plan_computes_estimates_on_create(api):
    """PRD §3.5: "The `estimated_daily_cost_cents` is the route mileage multiplied by a per-mile rate of 155 cents plus a fixed per-trip base of 500 cents; the `estimated_monthly_cost_cents` is that daily estimate multiplied by 20 school days per month."

    Design: Corner/entities/plan_computed_estimates_on_create
    """
    d = create_district()
    s = create_student(d["id"])
    resp = api.create_plan(
        {"student_id": s["id"], "origin_district_id": d["id"],
         "serving_district_id": d["id"], "route_miles": 20}, SC)
    plan = validate_success(resp, 201)
    assert plan["estimated_daily_cost_cents"] == 3600
    assert plan["estimated_monthly_cost_cents"] == 72000
    assert plan["status"] == "DRAFT"


def test_plan_create_bad_student_fk_not_found(api):
    """PRD §2.7: "every id in the path and every foreign-key reference in the body must resolve, validated left to right; the first unresolved reference returns that resource's specific not-found code (404)."

    Design: Corner/entities/plan_create_bad_student_fk_returns_not_found
    """
    d = create_district()
    resp = api.create_plan(
        {"student_id": "00000000-0000-4000-8000-0000000000ff",
         "origin_district_id": d["id"], "serving_district_id": d["id"], "route_miles": 20}, SC)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND.value, 404)
