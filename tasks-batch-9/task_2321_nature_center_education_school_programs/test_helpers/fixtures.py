"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database. Setup calls use
the lenient ``get_success_data`` validator so a broken precondition surfaces as
a setup failure rather than as a confusing assertion failure.

Identity threading: ``Naturalist`` headers are always built from the real
``Educator.id`` and ``TeacherContact`` headers from the real ``SchoolPartner.id``
(PRD §2.1), never from a shared constant.
"""

from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    assess_training_record_payload,
    create_animal_payload,
    create_booking_payload,
    create_curriculum_material_payload,
    create_educator_payload,
    create_equipment_manifest_payload,
    create_evaluation_report_payload,
    create_permit_payload,
    create_program_offering_payload,
    create_scholarship_fund_payload,
    create_school_payload,
    create_standard_alignment_payload,
    create_trail_segment_payload,
    create_training_record_payload,
)
from .test_users import (
    TEST_USERS,
    make_naturalist_headers,
    make_teacher_contact_headers,
)

ED = TEST_USERS["education_director_headers"]
CS = TEST_USERS["curriculum_specialist_headers"]
CS_ASSESSOR = TEST_USERS["curriculum_specialist_assessor_headers"]
BC = TEST_USERS["booking_coordinator_headers"]
SM = TEST_USERS["stewardship_manager_headers"]
GO = TEST_USERS["grants_officer_headers"]

DEFAULT_ALIGNMENTS = (
    {"standard_code": "3-LS4-3", "dimension": "DISCIPLINARY_CORE_IDEA"},
    {"standard_code": "3-LS4-4", "dimension": "SCIENCE_PRACTICE"},
)


# ======================================================================
# Clock
# ======================================================================

def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    """Move the logical clock. Returns the clock payload reporting ``current_utc``."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ED)
    )


# ======================================================================
# Re-read helpers
# ======================================================================

def refresh_offering(offering_id: str) -> dict:
    return get_success_data(api_client.get_program_offering(offering_id, CS))


def refresh_school(school_id: str) -> dict:
    return get_success_data(api_client.get_school(school_id, BC))


def refresh_educator(educator_id: str) -> dict:
    return get_success_data(api_client.get_educator(educator_id, ED))


def refresh_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, SM))


def refresh_animal(animal_id: str) -> dict:
    return get_success_data(api_client.get_animal(animal_id, SM))


def refresh_trail_segment(trail_segment_id: str) -> dict:
    return get_success_data(api_client.get_trail_segment(trail_segment_id, SM))


def refresh_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_booking(booking_id, BC))


def refresh_fund(fund_id: str) -> dict:
    return get_success_data(api_client.get_scholarship_fund(fund_id, GO))


def refresh_aid_application(aid_application_id: str) -> dict:
    return get_success_data(api_client.get_aid_application(aid_application_id, GO))


def find_training_record(educator_id: str, training_record_id: str) -> dict:
    body = get_success_data(api_client.list_training_records(educator_id, ED))
    rows = body if isinstance(body, list) else body.get("data", [])
    for row in rows:
        if row["id"] == training_record_id:
            return row
    raise AssertionError(
        f"Setup failed: training record {training_record_id} not listed for educator "
        f"{educator_id}"
    )


def find_material(offering_id: str, material_id: str) -> dict:
    body = get_success_data(api_client.list_curriculum_materials(offering_id, CS))
    rows = body if isinstance(body, list) else body.get("data", [])
    for row in rows:
        if row["id"] == material_id:
            return row
    raise AssertionError(
        f"Setup failed: material {material_id} not listed for offering {offering_id}"
    )


def find_manifest(booking_id: str, manifest_id: str) -> dict:
    body = get_success_data(api_client.list_equipment_manifests(booking_id, BC))
    rows = body if isinstance(body, list) else body.get("data", [])
    for row in rows:
        if row["id"] == manifest_id:
            return row
    raise AssertionError(
        f"Setup failed: manifest {manifest_id} not listed for booking {booking_id}"
    )


def find_evaluation_report(booking_id: str, report_id: str) -> dict:
    body = get_success_data(api_client.list_evaluation_reports(booking_id, ED))
    rows = body if isinstance(body, list) else body.get("data", [])
    for row in rows:
        if row["id"] == report_id:
            return row
    raise AssertionError(
        f"Setup failed: evaluation report {report_id} not listed for booking {booking_id}"
    )


# ======================================================================
# Tier 1 — single-entity creates and short state walks
# ======================================================================

def create_school(**overrides) -> dict:
    """Register a school partner. Opens ACTIVE with zero strikes."""
    return get_success_data(
        api_client.create_school(create_school_payload(**overrides), BC)
    )


def create_draft_offering(**overrides) -> dict:
    """Create a DRAFT program offering with no alignments and no materials."""
    return get_success_data(
        api_client.create_program_offering(create_program_offering_payload(**overrides), CS)
    )


def attach_alignments(offering_id: str, alignments=DEFAULT_ALIGNMENTS) -> list:
    """Attach the given standard-alignment claims to an offering."""
    created = []
    for spec in alignments:
        created.append(
            get_success_data(
                api_client.create_standard_alignment(
                    offering_id, create_standard_alignment_payload(**spec), CS
                )
            )
        )
    return created


def attach_materials(offering_id: str, slug_prefix: str = "pond", publish: bool = True) -> dict:
    """Attach one PRE_VISIT and one POST_VISIT material, optionally publishing both."""
    pre = get_success_data(
        api_client.create_curriculum_material(
            offering_id,
            create_curriculum_material_payload(
                phase="PRE_VISIT", url_slug=f"{slug_prefix}-pre"
            ),
            CS,
        )
    )
    post = get_success_data(
        api_client.create_curriculum_material(
            offering_id,
            create_curriculum_material_payload(
                phase="POST_VISIT", url_slug=f"{slug_prefix}-post"
            ),
            CS,
        )
    )
    if publish:
        get_success_data(api_client.publish_curriculum_material(pre["id"], CS))
        get_success_data(api_client.publish_curriculum_material(post["id"], CS))
    return {"pre_visit_material": pre, "post_visit_material": post}


def create_offering_under_review(
    alignments=DEFAULT_ALIGNMENTS,
    slug_prefix: str = "pond",
    publish_pre_visit: bool = True,
    publish_post_visit: bool = True,
    **overrides,
) -> dict:
    """DRAFT offering + alignments + both materials + submit-for-review.

    Returns ``{"offering", "alignments", "pre_visit_material", "post_visit_material"}``.
    """
    offering = create_draft_offering(**overrides)
    created_alignments = attach_alignments(offering["id"], alignments)
    materials = attach_materials(offering["id"], slug_prefix, publish=False)
    if publish_pre_visit:
        get_success_data(
            api_client.publish_curriculum_material(materials["pre_visit_material"]["id"], CS)
        )
    if publish_post_visit:
        get_success_data(
            api_client.publish_curriculum_material(materials["post_visit_material"]["id"], CS)
        )
    get_success_data(api_client.submit_offering_for_review(offering["id"], CS))
    return {
        "offering": refresh_offering(offering["id"]),
        "alignments": created_alignments,
        **materials,
    }


def create_published_offering(
    alignments=DEFAULT_ALIGNMENTS, slug_prefix: str = "pond", **overrides
) -> dict:
    """Walk a fresh offering all the way to PUBLISHED and return the offering row."""
    bundle = create_offering_under_review(
        alignments=alignments, slug_prefix=slug_prefix, **overrides
    )
    get_success_data(
        api_client.review_program_offering(
            bundle["offering"]["id"], {"decision": "PUBLISH"}, ED
        )
    )
    return refresh_offering(bundle["offering"]["id"])


def create_published_offering_bundle(
    alignments=DEFAULT_ALIGNMENTS, slug_prefix: str = "pond", **overrides
) -> dict:
    """Same as ``create_published_offering`` but keeps the child rows around."""
    bundle = create_offering_under_review(
        alignments=alignments, slug_prefix=slug_prefix, **overrides
    )
    get_success_data(
        api_client.review_program_offering(
            bundle["offering"]["id"], {"decision": "PUBLISH"}, ED
        )
    )
    bundle["offering"] = refresh_offering(bundle["offering"]["id"])
    return bundle


def create_permit(**overrides) -> dict:
    """Record a wildlife permit. Opens ACTIVE."""
    return get_success_data(
        api_client.create_permit(create_permit_payload(**overrides), SM)
    )


def create_animal(permit_id: str = None, **overrides) -> dict:
    """Register an animal ambassador under an ACTIVE permit (created if absent)."""
    if permit_id is None:
        permit_id = create_permit()["id"]
    return get_success_data(
        api_client.create_animal(create_animal_payload(permit_id, **overrides), SM)
    )


def create_permitted_animal(permit_overrides=None, **animal_overrides) -> dict:
    """Returns ``{"permit", "animal"}`` with the animal AVAILABLE and posture OPEN."""
    permit = create_permit(**(permit_overrides or {}))
    animal = create_animal(permit["id"], **animal_overrides)
    return {"permit": permit, "animal": animal}


def create_trail_segment(**overrides) -> dict:
    """Register a trail segment. Opens OPEN with visitors_this_week 0."""
    return get_success_data(
        api_client.create_trail_segment(create_trail_segment_payload(**overrides), SM)
    )


def create_fund(**overrides) -> dict:
    """Open a scholarship pool. Opens OPEN with available_cents == total_cents."""
    return get_success_data(
        api_client.create_scholarship_fund(create_scholarship_fund_payload(**overrides), GO)
    )


def create_educator(**overrides) -> dict:
    """Register an educator. Opens APPLICANT."""
    return get_success_data(
        api_client.create_educator(create_educator_payload(**overrides), ED)
    )


def enroll_training(educator_id: str, **overrides) -> dict:
    """Enrol an educator in a training track (enroller is cs-01)."""
    return get_success_data(
        api_client.create_training_record(
            educator_id, create_training_record_payload(**overrides), CS
        )
    )


def assess_training(training_record_id: str, **overrides) -> dict:
    """Record an assessment. The assessor (cs-02) differs from the enroller (cs-01)."""
    return get_success_data(
        api_client.assess_training_record(
            training_record_id, assess_training_record_payload(**overrides), CS_ASSESSOR
        )
    )


def create_onboarding_educator(**overrides) -> dict:
    """Educator advanced to ONBOARDING."""
    educator = create_educator(**overrides)
    get_success_data(
        api_client.advance_educator_hiring(
            educator["id"], {"action": "START_ONBOARDING"}, ED
        )
    )
    return refresh_educator(educator["id"])


def create_cleared_educator(
    grade_bands=("G3_5",),
    handling_tier: str = None,
    curriculum_score: int = 88,
    handling_score: int = 92,
    **overrides,
) -> dict:
    """Full staffing pipeline: APPLICANT → ONBOARDING → passing training → CLEARED.

    ``grade_bands`` produces one passing CURRICULUM record per band.
    ``handling_tier`` (``TIER_1``/``TIER_2``) adds a passing LIVE_ANIMAL_HANDLING record.
    Returns ``{"educator", "curriculum_records", "handling_record"}``.
    """
    educator = create_onboarding_educator(**overrides)
    curriculum_records = []
    for band in grade_bands:
        record = enroll_training(educator["id"], track="CURRICULUM", grade_band=band)
        assess_training(record["id"], outcome="PASS", score=curriculum_score)
        curriculum_records.append(find_training_record(educator["id"], record["id"]))

    handling_record = None
    if handling_tier is not None:
        record = enroll_training(
            educator["id"],
            track="LIVE_ANIMAL_HANDLING",
            handling_tier=handling_tier,
            grade_band=None,
        )
        assess_training(record["id"], outcome="PASS", score=handling_score)
        handling_record = find_training_record(educator["id"], record["id"])

    get_success_data(
        api_client.advance_educator_hiring(educator["id"], {"action": "CLEAR"}, ED)
    )
    return {
        "educator": refresh_educator(educator["id"]),
        "curriculum_records": curriculum_records,
        "handling_record": handling_record,
    }


def create_failed_training_record(educator_id: str = None, **overrides) -> dict:
    """A training record sitting at ASSESSED_FAIL with attempt_count 1."""
    if educator_id is None:
        educator_id = create_onboarding_educator()["id"]
    record = enroll_training(educator_id, **overrides)
    assess_training(record["id"], outcome="FAIL", score=None)
    return {
        "educator_id": educator_id,
        "training_record": find_training_record(educator_id, record["id"]),
    }


# ======================================================================
# Tier 2 — bookings and resource assignment
# ======================================================================

def create_booking(school_id: str, offering_id: str, headers=None, **overrides) -> dict:
    """Open a booking in REQUESTED / UNFUNDED."""
    return get_success_data(
        api_client.create_booking(
            create_booking_payload(school_id, offering_id, **overrides), headers or BC
        )
    )


def assign_resources(booking_id: str, expected_booking_version: int = None, **fields) -> dict:
    """Assign resources, reading the booking's live ``version`` when not supplied."""
    if expected_booking_version is None:
        expected_booking_version = refresh_booking(booking_id)["version"]
    payload = {"expected_booking_version": expected_booking_version}
    payload.update({k: v for k, v in fields.items() if v is not None})
    return get_success_data(api_client.assign_booking_resources(booking_id, payload, BC))


def confirm_booking(booking_id: str) -> dict:
    return get_success_data(api_client.confirm_booking(booking_id, BC))


def deliver_booking(
    booking_id: str,
    actual_student_count: int,
    actual_chaperone_count: int,
    actual_contact_minutes: int = None,
    headers=None,
) -> dict:
    payload = {
        "actual_student_count": actual_student_count,
        "actual_chaperone_count": actual_chaperone_count,
    }
    if actual_contact_minutes is not None:
        payload["actual_contact_minutes"] = actual_contact_minutes
    return get_success_data(
        api_client.deliver_booking(booking_id, payload, headers or BC)
    )


def setup_booking_scenario(
    student_count: int = 30,
    chaperone_count: int = 3,
    start_utc: str = TEST_DEFAULTS["BOOKING_START_UTC"],
    end_utc: str = TEST_DEFAULTS["BOOKING_END_UTC"],
    clock: str = DEFAULT_CLOCK,
    offering_overrides: dict = None,
    school_overrides: dict = None,
    educator_overrides: dict = None,
    grade_bands=("G3_5",),
    handling_tier: str = None,
    assign_educator: bool = True,
    alignments=DEFAULT_ALIGNMENTS,
    slug_prefix: str = "pond",
) -> dict:
    """The canonical scenario: clock pinned, PUBLISHED offering, registered school,
    CLEARED and certified educator, one REQUESTED booking with the educator attached.

    Returns ``{"offering", "school", "educator", "booking", "staffing"}``.
    """
    set_clock(clock)
    offering = create_published_offering(
        alignments=alignments, slug_prefix=slug_prefix, **(offering_overrides or {})
    )
    school = create_school(**(school_overrides or {}))
    staffing = create_cleared_educator(
        grade_bands=grade_bands, handling_tier=handling_tier, **(educator_overrides or {})
    )
    booking = create_booking(
        school["id"],
        offering["id"],
        start_utc=start_utc,
        end_utc=end_utc,
        student_count=student_count,
        chaperone_count=chaperone_count,
    )
    if assign_educator:
        booking = assign_resources(
            booking["id"], lead_educator_id=staffing["educator"]["id"]
        )
    return {
        "offering": offering,
        "school": school,
        "educator": refresh_educator(staffing["educator"]["id"]),
        "staffing": staffing,
        "booking": booking,
    }


def setup_confirmed_booking(**kwargs) -> dict:
    """``setup_booking_scenario`` carried through confirmation."""
    scenario = setup_booking_scenario(**kwargs)
    scenario["booking"] = confirm_booking(scenario["booking"]["id"])
    return scenario


def setup_animal_booking_scenario(
    student_count: int = 20,
    chaperone_count: int = 3,
    start_utc: str = TEST_DEFAULTS["BOOKING_START_UTC"],
    end_utc: str = TEST_DEFAULTS["BOOKING_END_UTC"],
    clock: str = DEFAULT_CLOCK,
    animal_overrides: dict = None,
    permit_overrides: dict = None,
    offering_overrides: dict = None,
    school_overrides: dict = None,
    handling_tier: str = "TIER_1",
    confirm: bool = False,
    slug_prefix: str = "raptor",
) -> dict:
    """A booking on an offering that requires a live animal, with an ACTIVE permit,
    an AVAILABLE ambassador and a handler-certified educator all attached.

    Returns ``{"permit", "animal", "offering", "school", "educator", "booking"}``.
    """
    set_clock(clock)
    animal_bundle = create_permitted_animal(
        permit_overrides=permit_overrides, **(animal_overrides or {})
    )
    offering_payload = {"requires_live_animal": True}
    offering_payload.update(offering_overrides or {})
    offering = create_published_offering(slug_prefix=slug_prefix, **offering_payload)
    school = create_school(**(school_overrides or {}))
    staffing = create_cleared_educator(handling_tier=handling_tier)
    booking = create_booking(
        school["id"],
        offering["id"],
        start_utc=start_utc,
        end_utc=end_utc,
        student_count=student_count,
        chaperone_count=chaperone_count,
    )
    booking = assign_resources(
        booking["id"],
        lead_educator_id=staffing["educator"]["id"],
        animal_id=animal_bundle["animal"]["id"],
    )
    if confirm:
        booking = confirm_booking(booking["id"])
    return {
        "permit": refresh_permit(animal_bundle["permit"]["id"]),
        "animal": refresh_animal(animal_bundle["animal"]["id"]),
        "offering": offering,
        "school": school,
        "educator": refresh_educator(staffing["educator"]["id"]),
        "staffing": staffing,
        "booking": booking,
    }


def setup_trail_booking_scenario(
    student_count: int = 20,
    chaperone_count: int = 3,
    start_utc: str = TEST_DEFAULTS["BOOKING_START_UTC"],
    end_utc: str = TEST_DEFAULTS["BOOKING_END_UTC"],
    clock: str = DEFAULT_CLOCK,
    trail_overrides: dict = None,
    offering_overrides: dict = None,
    school_overrides: dict = None,
    confirm: bool = False,
    slug_prefix: str = "wetland",
) -> dict:
    """A booking on an offering that requires a trail segment, with an OPEN segment
    and a certified educator attached.

    Returns ``{"trail_segment", "offering", "school", "educator", "booking"}``.
    """
    set_clock(clock)
    trail = create_trail_segment(**(trail_overrides or {}))
    offering_payload = {
        "title": "Wetland Transect Walk",
        "requires_trail_segment": True,
    }
    offering_payload.update(offering_overrides or {})
    offering = create_published_offering(slug_prefix=slug_prefix, **offering_payload)
    school = create_school(**(school_overrides or {}))
    staffing = create_cleared_educator()
    booking = create_booking(
        school["id"],
        offering["id"],
        start_utc=start_utc,
        end_utc=end_utc,
        student_count=student_count,
        chaperone_count=chaperone_count,
    )
    booking = assign_resources(
        booking["id"],
        lead_educator_id=staffing["educator"]["id"],
        trail_segment_id=trail["id"],
    )
    if confirm:
        booking = confirm_booking(booking["id"])
    return {
        "trail_segment": refresh_trail_segment(trail["id"]),
        "offering": offering,
        "school": school,
        "educator": refresh_educator(staffing["educator"]["id"]),
        "staffing": staffing,
        "booking": booking,
    }


# ======================================================================
# Tier 3 — full lifecycle shortcuts
# ======================================================================

def setup_delivered_booking(
    actual_student_count: int = None,
    actual_chaperone_count: int = None,
    actual_contact_minutes: int = None,
    **kwargs,
) -> dict:
    """A booking walked through confirm and delivery, so funding is INVOICED."""
    scenario = setup_confirmed_booking(**kwargs)
    booking = scenario["booking"]
    scenario["booking"] = deliver_booking(
        booking["id"],
        actual_student_count if actual_student_count is not None else booking["student_count"],
        actual_chaperone_count
        if actual_chaperone_count is not None
        else booking["chaperone_count"],
        actual_contact_minutes,
    )
    return scenario


def apply_for_aid(
    booking_id: str,
    fund_id: str,
    requested_scholarship_cents: int,
    requested_transport_cents: int,
    expected_fund_version: int = None,
    headers=None,
) -> dict:
    """Create an aid application, reading the fund's live ``version`` when not supplied."""
    if expected_fund_version is None:
        expected_fund_version = refresh_fund(fund_id)["version"]
    payload = {
        "booking_id": booking_id,
        "fund_id": fund_id,
        "requested_scholarship_cents": requested_scholarship_cents,
        "requested_transport_cents": requested_transport_cents,
        "expected_fund_version": expected_fund_version,
    }
    return get_success_data(api_client.create_aid_application(payload, headers or BC))


def setup_booking_with_submitted_aid(
    requested_scholarship_cents: int = 33300,
    requested_transport_cents: int = 6500,
    fund_overrides: dict = None,
    **kwargs,
) -> dict:
    """Canonical booking plus one SUBMITTED aid application against an OPEN pool.

    Returns the booking scenario plus ``{"fund", "aid_application"}``.
    """
    scenario = setup_booking_scenario(**kwargs)
    fund = create_fund(**(fund_overrides or {}))
    aid = apply_for_aid(
        scenario["booking"]["id"],
        fund["id"],
        requested_scholarship_cents,
        requested_transport_cents,
    )
    scenario["fund"] = refresh_fund(fund["id"])
    scenario["aid_application"] = aid
    scenario["booking"] = refresh_booking(scenario["booking"]["id"])
    return scenario


def setup_booking_with_approved_aid(
    requested_scholarship_cents: int = 33300,
    requested_transport_cents: int = 6500,
    fund_overrides: dict = None,
    **kwargs,
) -> dict:
    """Canonical booking whose aid application has been approved by the grants officer."""
    scenario = setup_booking_with_submitted_aid(
        requested_scholarship_cents=requested_scholarship_cents,
        requested_transport_cents=requested_transport_cents,
        fund_overrides=fund_overrides,
        **kwargs,
    )
    get_success_data(
        api_client.review_aid_application(
            scenario["aid_application"]["id"], {"decision": "APPROVE"}, GO
        )
    )
    scenario["aid_application"] = refresh_aid_application(scenario["aid_application"]["id"])
    scenario["fund"] = refresh_fund(scenario["fund"]["id"])
    scenario["booking"] = refresh_booking(scenario["booking"]["id"])
    return scenario


def setup_outreach_booking_with_manifest(
    total_weight_kg: float = 320,
    kit_codes=("KIT-PELTS", "KIT-SKULLS"),
    load: bool = True,
    student_count: int = 30,
    chaperone_count: int = 3,
    **kwargs,
) -> dict:
    """An OUTREACH_AT_SCHOOL booking, confirmed, carrying an equipment manifest.

    Returns the booking scenario plus ``{"manifest"}``.
    """
    offering_overrides = {"delivery_mode": "OUTREACH_AT_SCHOOL", "title": "Owls in Your Classroom"}
    offering_overrides.update(kwargs.pop("offering_overrides", None) or {})
    scenario = setup_confirmed_booking(
        student_count=student_count,
        chaperone_count=chaperone_count,
        offering_overrides=offering_overrides,
        slug_prefix="owls",
        **kwargs,
    )
    manifest = get_success_data(
        api_client.create_equipment_manifest(
            scenario["booking"]["id"],
            create_equipment_manifest_payload(
                kit_codes=list(kit_codes), total_weight_kg=total_weight_kg
            ),
            BC,
        )
    )
    if load:
        manifest = get_success_data(
            api_client.advance_equipment_manifest(manifest["id"], {"action": "LOAD"}, BC)
        )
    scenario["manifest"] = manifest
    scenario["booking"] = refresh_booking(scenario["booking"]["id"])
    return scenario


def setup_evaluation_in_draft(
    report_overrides: dict = None,
    actual_student_count: int = None,
    actual_chaperone_count: int = None,
    **kwargs,
) -> dict:
    """A delivered booking whose school teacher has opened a DRAFT evaluation report."""
    scenario = setup_delivered_booking(
        actual_student_count=actual_student_count,
        actual_chaperone_count=actual_chaperone_count,
        **kwargs,
    )
    teacher = make_teacher_contact_headers(scenario["school"]["id"])
    report = get_success_data(
        api_client.create_evaluation_report(
            scenario["booking"]["id"],
            create_evaluation_report_payload(**(report_overrides or {})),
            teacher,
        )
    )
    scenario["evaluation_report"] = report
    scenario["teacher_headers"] = teacher
    return scenario


def setup_submitted_evaluation(**kwargs) -> dict:
    """A delivered booking whose evaluation report has been submitted (index computed)."""
    scenario = setup_evaluation_in_draft(**kwargs)
    scenario["evaluation_report"] = get_success_data(
        api_client.submit_evaluation_report(
            scenario["evaluation_report"]["id"], scenario["teacher_headers"]
        )
    )
    return scenario


def setup_accepted_evaluation(**kwargs) -> dict:
    """A submitted evaluation accepted by the education director."""
    scenario = setup_submitted_evaluation(**kwargs)
    get_success_data(
        api_client.review_evaluation_report(
            scenario["evaluation_report"]["id"], {"decision": "ACCEPT"}, ED
        )
    )
    scenario["evaluation_report"] = find_evaluation_report(
        scenario["booking"]["id"], scenario["evaluation_report"]["id"]
    )
    return scenario


# ======================================================================
# Tier 4 — accumulation and threshold targeting
# ======================================================================

def setup_school_with_strikes(
    strikes: int = 1,
    clock: str = DEFAULT_CLOCK,
    offering_overrides: dict = None,
    school_overrides: dict = None,
    extra_requested_bookings: int = 0,
) -> dict:
    """Accumulate ``strikes`` no-shows against one school so standing is recomputed.

    ``extra_requested_bookings`` leaves that many additional REQUESTED bookings in
    place so the suspension cascade has something to cancel.

    Returns ``{"offering", "school", "no_show_bookings", "requested_bookings"}``.
    """
    set_clock(clock)
    offering = create_published_offering(**(offering_overrides or {}))
    school = create_school(**(school_overrides or {}))
    # One calendar day per booking, walked with real date arithmetic so the slots
    # stay valid dates and stay inside the ISO program week of DEFAULT_CLOCK
    # (Monday 2026-09-28 through Sunday 2026-10-04).
    slots = [
        (date(2026, 9, 29) + timedelta(days=offset)).isoformat()
        for offset in range(extra_requested_bookings + max(strikes, 0) + 1)
    ]
    cursor = 0
    extra = []
    for _ in range(extra_requested_bookings):
        extra.append(
            create_booking(
                school["id"],
                offering["id"],
                start_utc=f"{slots[cursor]}T09:00:00Z",
                end_utc=f"{slots[cursor]}T11:00:00Z",
            )
        )
        cursor += 1
    no_shows = []
    for index in range(strikes):
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc=f"{slots[cursor]}T14:00:00Z",
            end_utc=f"{slots[cursor]}T16:00:00Z",
        )
        cursor += 1
        no_shows.append(
            get_success_data(
                api_client.no_show_booking(
                    booking["id"], {"note": f"Bus never arrived ({index + 1})"}, BC
                )
            )
        )
    return {
        "offering": offering,
        "school": refresh_school(school["id"]),
        "no_show_bookings": no_shows,
        "requested_bookings": [refresh_booking(b["id"]) for b in extra],
    }


def setup_animal_at_projected_exposure(
    target_minutes: int,
    weekly_exposure_cap_minutes: int = 240,
    duration_minutes: int = 120,
    clock: str = DEFAULT_CLOCK,
    animal_overrides: dict = None,
    student_count: int = 20,
    chaperone_count: int = 3,
) -> dict:
    """Confirm as many bookings as needed to push one ambassador's
    ``projected_exposure_minutes_7d`` to ``target_minutes``.

    Returns ``{"permit", "animal", "offering", "school", "educator", "bookings"}``.
    """
    assert target_minutes % duration_minutes == 0, (
        "target_minutes must be a whole multiple of duration_minutes"
    )
    set_clock(clock)
    overrides = {"weekly_exposure_cap_minutes": weekly_exposure_cap_minutes}
    overrides.update(animal_overrides or {})
    animal_bundle = create_permitted_animal(**overrides)
    offering = create_published_offering(
        requires_live_animal=True,
        duration_minutes=duration_minutes,
        slug_prefix="raptor",
        title="Raptor Adaptations",
    )
    school = create_school()
    bookings = []
    needed = target_minutes // duration_minutes
    # One calendar day per booking, walked with real date arithmetic; 2026-09-29
    # onwards all sit inside the ISO program week beginning 2026-09-28.
    for offset in range(needed):
        day = (date(2026, 9, 29) + timedelta(days=offset)).isoformat()
        staffing = create_cleared_educator(handling_tier="TIER_1")
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc=f"{day}T14:00:00Z",
            end_utc=f"{day}T16:00:00Z",
            student_count=student_count,
            chaperone_count=chaperone_count,
        )
        assign_resources(
            booking["id"],
            lead_educator_id=staffing["educator"]["id"],
            animal_id=animal_bundle["animal"]["id"],
        )
        bookings.append(confirm_booking(booking["id"]))
    return {
        "permit": refresh_permit(animal_bundle["permit"]["id"]),
        "animal": refresh_animal(animal_bundle["animal"]["id"]),
        "offering": offering,
        "school": school,
        "bookings": bookings,
    }


def setup_educator_at_weekly_load(
    target_minutes: int,
    employment_type: str = "SEASONAL_EDUCATOR",
    season_end_date: str = "2026-11-30T00:00:00Z",
    duration_minutes: int = 120,
    clock: str = DEFAULT_CLOCK,
    student_count: int = 20,
    chaperone_count: int = 3,
) -> dict:
    """Assign one educator to enough non-overlapping bookings inside the ISO week to
    reach ``delivery_load_minutes_this_week == target_minutes``.

    Returns ``{"offering", "school", "educator", "assigned_bookings", "next_day"}``.
    """
    assert target_minutes % duration_minutes == 0, (
        "target_minutes must be a whole multiple of duration_minutes"
    )
    set_clock(clock)
    offering = create_published_offering(duration_minutes=duration_minutes)
    school = create_school()
    educator_overrides = {"employment_type": employment_type, "full_name": "Wren Salix"}
    if season_end_date is not None:
        educator_overrides["season_end_date"] = season_end_date
    staffing = create_cleared_educator(**educator_overrides)
    assigned = []
    # 2026-09-29 through 2026-10-04 all sit inside the ISO week beginning 2026-09-28.
    days = [
        "2026-09-29",
        "2026-09-30",
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
    ]
    needed = target_minutes // duration_minutes
    assert needed <= len(days), "not enough distinct days inside the ISO program week"
    for day in days[:needed]:
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc=f"{day}T14:00:00Z",
            end_utc=f"{day}T16:00:00Z",
            student_count=student_count,
            chaperone_count=chaperone_count,
        )
        assign_resources(booking["id"], lead_educator_id=staffing["educator"]["id"])
        assigned.append(refresh_booking(booking["id"]))
    return {
        "offering": offering,
        "school": school,
        "educator": refresh_educator(staffing["educator"]["id"]),
        "staffing": staffing,
        "assigned_bookings": assigned,
        "free_days": days[needed:],
    }


def setup_trail_at_weekly_visitors(
    persons_per_booking: int = 23,
    bookings_to_confirm: int = 1,
    trail_overrides: dict = None,
    clock: str = DEFAULT_CLOCK,
) -> dict:
    """Confirm ``bookings_to_confirm`` non-overlapping bookings on one trail segment so
    ``visitors_this_week`` accumulates.

    ``persons_per_booking`` splits into 20 students plus 3 chaperones by default.
    Returns ``{"trail_segment", "offering", "school", "confirmed_bookings"}``.
    """
    set_clock(clock)
    trail = create_trail_segment(**(trail_overrides or {}))
    offering = create_published_offering(
        requires_trail_segment=True, title="Wetland Transect Walk", slug_prefix="wetland"
    )
    school = create_school()
    students = persons_per_booking - 3
    confirmed = []
    days = ["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]
    for day in days[:bookings_to_confirm]:
        staffing = create_cleared_educator()
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc=f"{day}T09:00:00Z",
            end_utc=f"{day}T11:00:00Z",
            student_count=students,
            chaperone_count=3,
        )
        assign_resources(
            booking["id"],
            lead_educator_id=staffing["educator"]["id"],
            trail_segment_id=trail["id"],
        )
        confirmed.append(confirm_booking(booking["id"]))
    return {
        "trail_segment": refresh_trail_segment(trail["id"]),
        "offering": offering,
        "school": school,
        "confirmed_bookings": confirmed,
        "free_days": days[bookings_to_confirm:],
    }


# ======================================================================
# Tier 5 — terminal states and settlement
# ======================================================================

def setup_settled_booking(**kwargs) -> dict:
    """A delivered booking paid in full, so funding reaches SETTLED."""
    scenario = setup_delivered_booking(**kwargs)
    booking = scenario["booking"]
    get_success_data(
        api_client.record_payment(
            booking["id"], {"amount_cents": booking["net_due_cents"]}, BC
        )
    )
    scenario["booking"] = refresh_booking(booking["id"])
    return scenario


def setup_closed_fund(**overrides) -> dict:
    """A scholarship pool moved to the terminal CLOSED state."""
    fund = create_fund(**overrides)
    get_success_data(
        api_client.set_scholarship_fund_status(fund["id"], {"status": "CLOSED"}, GO)
    )
    return refresh_fund(fund["id"])


def setup_retired_offering(**overrides) -> dict:
    """A PUBLISHED offering retired out of the catalog."""
    offering = create_published_offering(**overrides)
    get_success_data(api_client.retire_program_offering(offering["id"], ED))
    return refresh_offering(offering["id"])


def setup_naturalist_led_booking(**kwargs) -> dict:
    """A confirmed booking plus ``Naturalist`` headers bound to its lead educator."""
    scenario = setup_confirmed_booking(**kwargs)
    scenario["naturalist_headers"] = make_naturalist_headers(scenario["educator"]["id"])
    return scenario
