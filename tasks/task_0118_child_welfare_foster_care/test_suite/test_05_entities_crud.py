"""Entity creation, required-field, type, not-found, and computed-field corners.

Queue B — corner section: entities.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    setup_workers, open_case_with_child, set_clock,
)


def test_create_referral_returns_201_received_version_1(api):
    """PRD §3.1: "A new referral is born in status `RECEIVED`. Its `response_priority`, `screening_score`, `screened_in_by`, and `linked_case_id` are all null at this point."
    PRD §2.4: "The `version` of a freshly created resource is its initial value".

    Design: Corner/entities/create_referral_returns_201_with_received_status
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    ref = validate_success(api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child N",
         "alleged_maltreatment": "NEGLECT", "priority_factors": []}, w.screener),
        expected_status=201)
    assert ref["status"] == "RECEIVED"
    assert ref["version"] == 1


def test_create_referral_missing_alleged_maltreatment_rejected(api):
    """PRD §2.3: "a request body that is structurally malformed — a required field absent, a field of the wrong type, or an enum field carrying a value outside its permitted set — is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.1: "the primary `alleged_maltreatment` (one of `PHYSICAL_ABUSE`, `SEXUAL_ABUSE`, `NEGLECT`, or `EMOTIONAL_ABUSE`)".

    Design: Corner/entities/create_referral_missing_required_alleged_maltreatment_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    resp = api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child N"}, w.screener)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_referral_invalid_reporter_type_enum_rejected(api):
    """PRD §2.3: "a request body that is structurally malformed — a required field absent, a field of the wrong type, or an enum field carrying a value outside its permitted set — is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.1: "who is calling via `reporter_type` (one of `MANDATED`, `ANONYMOUS`, `RELATIVE`, or `SELF`)".

    Design: Corner/entities/create_referral_invalid_enum_reporter_type_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    resp = api.create_referral(
        {"reporter_type": "GHOST", "child_name": "Child N",
         "alleged_maltreatment": "NEGLECT"}, w.screener)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_get_unknown_referral_returns_not_found(api):
    """PRD §2.6: "The first reference that resolves to nothing yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_referral_unknown_id_returns_not_found
    """
    w = setup_workers(need_licensing=False)
    resp = api.get_referral("00000000-0000-4000-8000-000000000001", w.screener)
    validate_error(resp, "ERR_NOT_FOUND")


def test_foster_home_bed_capacity_below_one_rejected(api):
    """PRD §3.4: "a `bed_capacity` (the maximum number of children that may hold an active bed at once, which must be at least 1)".
    PRD §3.4: "A `bed_capacity` below 1 or a `max_age_years` outside 0 to 21 is rejected with `ERR_VALIDATION_LIMIT`."

    Design: Corner/entities/foster_home_capacity_below_one_rejected
    """
    w = setup_workers()
    resp = api.create_foster_home(
        {"licensing_worker_id": w.licensing_id, "home_name": "Bad Home",
         "bed_capacity": 0, "max_age_years": 18, "accepts_maltreatment": ["NEGLECT"]}, w.licensing)
    validate_error(resp, "ERR_VALIDATION_LIMIT")


def test_child_age_years_computed_from_dob_and_clock(api):
    """PRD §3.3: "The child's `age_years` — whole years elapsed from `date_of_birth` to the current clock — is recomputed whenever the child is read."
    Born 2016-01-01, clock 2026-06-01 -> 10.

    Design: Corner/entities/child_age_years_computed_from_dob_and_clock
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-06-01T00:00:00Z")
    case, child = open_case_with_child(w, dob="2016-01-01T00:00:00Z")
    fetched = validate_success(api.get_child(child["id"], w.caseworker))
    assert fetched["age_years"] == 10, f"got {fetched['age_years']}"


def test_system_status_forced_on_referral_create(api):
    """PRD §3.1: "A new referral is born in status `RECEIVED`."
    A client-supplied status is ignored; the server forces RECEIVED on create.

    Design: Corner/entities/system_fields_ignored_on_referral_create
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    ref = validate_success(api.create_referral(
        {"reporter_type": "RELATIVE", "child_name": "Child Q",
         "alleged_maltreatment": "NEGLECT", "status": "SCREENED_IN"}, w.screener),
        expected_status=201)
    assert ref["status"] == "RECEIVED"
