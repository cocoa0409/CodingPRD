"""Composite setup helpers for the FAFSA completion campaign tests.

Every fixture builds its preconditions from scratch through the public API
(the harness restarts the server before every test, so nothing carries over).
Entity-backed roles always thread the real resource id into their headers:
SchoolCoordinator calls use the acting school's id; StaffMember/Specialist
calls use the acting staff profile's id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_aid_record_payload,
    create_campaign_payload,
    create_completion_report_payload,
    create_consent_payload,
    create_event_payload,
    create_event_registration_payload,
    create_match_link_payload,
    create_school_payload,
    create_senior_record_payload,
    create_staff_assignment_payload,
    create_staff_profile_payload,
    create_support_case_payload,
)
from .test_users import (
    TEST_USERS,
    make_school_coordinator_headers,
    make_specialist_headers,
    make_staff_member_headers,
)

ADMIN = TEST_USERS["campaign_admin_headers"]
REVIEWER = TEST_USERS["match_reviewer_headers"]
IMPORTER = TEST_USERS["data_importer_headers"]


def _ok(response, what: str):
    """Lenient setup validator: any 2xx. Returns the data payload, which is a
    dict for single-resource endpoints and a list for list endpoints."""
    data = get_success_data(response)
    assert isinstance(data, (dict, list)), f"Setup failed ({what}): {response.text}"
    return data


def coord(school) -> dict:
    """Scope-correct coordinator headers for a school resource."""
    return make_school_coordinator_headers(school["id"])


# ---------------------------------------------------------------------------
# Tier 1: campaign / school progression
# ---------------------------------------------------------------------------
def create_campaign(**overrides) -> dict:
    """Create a campaign (starts DRAFT, budget counters zero)."""
    resp = api_client.create_campaign(create_campaign_payload(**overrides), ADMIN)
    return _ok(resp, "create campaign")


def create_open_campaign(**overrides) -> dict:
    """Create a campaign and activate it DRAFT -> OPEN."""
    campaign = create_campaign(**overrides)
    resp = api_client.activate_campaign(campaign["id"], ADMIN)
    return _ok(resp, "activate campaign")


def add_school(campaign, **overrides) -> dict:
    """Create a school (INVITED) under the campaign."""
    resp = api_client.create_school(create_school_payload(campaign["id"], **overrides), ADMIN)
    return _ok(resp, "create school")


def enroll_school(school) -> dict:
    resp = api_client.enroll_school(school["id"], ADMIN)
    return _ok(resp, "enroll school")


def setup_campaign_with_school(campaign_overrides=None, school_overrides=None):
    """OPEN campaign + one ENROLLED school. Returns (campaign, school)."""
    campaign = create_open_campaign(**(campaign_overrides or {}))
    school = add_school(campaign, **(school_overrides or {}))
    school = enroll_school(school)
    return campaign, school


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return _ok(resp, "advance clock")


# ---------------------------------------------------------------------------
# Tier 2: seniors, aid records, match links, consents
# ---------------------------------------------------------------------------
def add_senior(school, **overrides) -> dict:
    resp = api_client.create_senior_record(
        create_senior_record_payload(school["id"], **overrides), coord(school)
    )
    return _ok(resp, "create senior")


def add_aid_record(campaign, **overrides) -> dict:
    resp = api_client.create_aid_record(
        create_aid_record_payload(campaign["id"], **overrides), IMPORTER
    )
    return _ok(resp, "create aid record")


def fresh_senior(senior_id) -> dict:
    resp = api_client.get_senior_record(senior_id, ADMIN)
    return _ok(resp, "read senior")


def propose_link(senior_id, aid_record_id, expected_version=None) -> dict:
    """Propose a match link, carrying the senior's current version for OCC
    unless the caller pins a specific one (PRD §2.8)."""
    if expected_version is None:
        expected_version = fresh_senior(senior_id)["version"]
    resp = api_client.create_match_link(
        create_match_link_payload(senior_id, aid_record_id, expected_version), REVIEWER
    )
    return _ok(resp, "propose match link")


def grant_consent(school, senior_id, scopes, granted_by="PARENT", expires_at=None) -> dict:
    payload = create_consent_payload(
        senior_id, scopes=list(scopes), granted_by=granted_by
    )
    if expires_at is not None:
        payload["expires_at"] = expires_at
    resp = api_client.create_consent_record(payload, coord(school))
    return _ok(resp, "grant consent")


def create_matched_senior(
    campaign,
    school,
    *,
    student_ref,
    full_name,
    dob,
    home_language="en",
    aid_status="SUBMITTED",
    aid_effective_date="2027-01-10",
    aid_school_code=None,
    aid_district_code=None,
    aid_full_name=None,
    consent_scopes=None,
    consent_before_link=False,
    external_ref=None,
    **senior_overrides,
):
    """Senior + aid record + one match link (+ optional consent).

    Aid-record codes default to the school's own codes, so with equal name and
    dob the pair scores 1.00 and AUTO_CONFIRMED under default thresholds.
    Pass aid_school_code / aid_district_code / aid_full_name overrides to land
    in the SUGGESTED or AUTO_REJECTED band instead.
    Returns (senior, aid_record, link, consent_or_None).
    """
    senior = add_senior(
        school,
        student_ref=student_ref,
        full_name=full_name,
        dob=dob,
        home_language=home_language,
        **senior_overrides,
    )
    aid = add_aid_record(
        campaign,
        external_ref=external_ref or f"EXT-{student_ref}",
        full_name=aid_full_name if aid_full_name is not None else full_name,
        dob=dob,
        school_code=aid_school_code or school["school_code"],
        district_code=aid_district_code or school["district_code"],
        initial_status=aid_status,
        effective_date=aid_effective_date,
    )
    consent = None
    if consent_scopes and consent_before_link:
        consent = grant_consent(school, senior["id"], consent_scopes)
        senior = fresh_senior(senior["id"])
    link = propose_link(senior["id"], aid["id"], expected_version=senior["version"])
    if consent_scopes and not consent_before_link:
        consent = grant_consent(school, senior["id"], consent_scopes)
    return senior, aid, link, consent


def add_report_senior(
    campaign,
    school,
    *,
    student_ref,
    full_name,
    dob,
    home_language="en",
    aid_status,
    aid_effective_date="2027-01-10",
    scopes=("DATA_SHARE",),
    efc_band=None,
    subgroup_tags=None,
):
    """One fully matched (score 1.00) senior for reporting scenarios.

    Eligibility (PRD §3.10) needs match_status MATCHED + a GRANTED DATA_SHARE
    consent + an ENROLLED school; pass scopes=() to build a deliberately
    ineligible senior. Returns (senior, aid_record, link).
    """
    overrides = {}
    if efc_band is not None:
        overrides["efc_band"] = efc_band
    if subgroup_tags is not None:
        overrides["subgroup_tags"] = subgroup_tags
    senior, aid, link, _consent = create_matched_senior(
        campaign,
        school,
        student_ref=student_ref,
        full_name=full_name,
        dob=dob,
        home_language=home_language,
        aid_status=aid_status,
        aid_effective_date=aid_effective_date,
        external_ref=f"EXT-{school['school_code']}-{student_ref}",
        consent_scopes=list(scopes) if scopes else None,
        **overrides,
    )
    return senior, aid, link


# ---------------------------------------------------------------------------
# Tier 3: events, staff, assignments, registrations
# ---------------------------------------------------------------------------
def create_event(school, **overrides) -> dict:
    """Create a DRAFT event for the school."""
    resp = api_client.create_event(
        create_event_payload(school["id"], **overrides), coord(school)
    )
    return _ok(resp, "create event")


def publish_event(school, event_id) -> dict:
    resp = api_client.publish_event(event_id, coord(school))
    return _ok(resp, "publish event")


def create_staff(campaign, capabilities=None, languages=None, **overrides) -> dict:
    resp = api_client.create_staff_profile(
        create_staff_profile_payload(
            campaign["id"],
            capabilities=list(capabilities or ["EVENT_STAFF"]),
            languages=list(languages or ["en"]),
            **overrides,
        ),
        ADMIN,
    )
    return _ok(resp, "create staff profile")


def create_cleared_staff(campaign, capabilities=None, languages=None, **overrides) -> dict:
    staff = create_staff(campaign, capabilities, languages, **overrides)
    resp = api_client.record_background_check(staff["id"], "CLEARED", ADMIN)
    return _ok(resp, "clear background check")


def create_assignment(school, event_id, staff, role="VOLUNTEER") -> dict:
    resp = api_client.create_staff_assignment(
        create_staff_assignment_payload(event_id, staff["id"], assigned_role=role),
        coord(school),
    )
    return _ok(resp, "create assignment")


def accept_assignment(assignment_id, staff) -> dict:
    resp = api_client.accept_assignment(
        assignment_id, make_staff_member_headers(staff["id"])
    )
    return _ok(resp, "accept assignment")


def confirm_assignment(school, assignment_id) -> dict:
    resp = api_client.confirm_assignment(assignment_id, coord(school))
    return _ok(resp, "confirm assignment")


def create_confirmed_assignment(school, event_id, staff, role="VOLUNTEER") -> dict:
    """Full invitation lifecycle: create -> accept -> confirm."""
    assignment = create_assignment(school, event_id, staff, role)
    assignment = accept_assignment(assignment["id"], staff)
    return confirm_assignment(school, assignment["id"])


def get_staff(staff_id) -> dict:
    resp = api_client.get_staff_profile(staff_id, ADMIN)
    return _ok(resp, "read staff profile")


def get_campaign(campaign_id) -> dict:
    resp = api_client.get_campaign(campaign_id, ADMIN)
    return _ok(resp, "read campaign")


def get_event(event_id) -> dict:
    resp = api_client.get_event(event_id, ADMIN)
    return _ok(resp, "read event")


def register_senior(school, event_id, senior_id) -> dict:
    resp = api_client.create_event_registration(
        create_event_registration_payload(event_id, senior_id), coord(school)
    )
    return _ok(resp, "register senior")


def complete_running_event(school, event_id, actual_cost_cents, clock_iso) -> dict:
    """Advance the clock so the PUBLISHED event is IN_PROGRESS, then complete."""
    set_clock(clock_iso)
    resp = api_client.complete_event(event_id, actual_cost_cents, coord(school))
    return _ok(resp, "complete event")


# ---------------------------------------------------------------------------
# Tier 4: checklists and support cases
# ---------------------------------------------------------------------------
def get_checklist_for_senior(senior_id) -> dict:
    resp = api_client.list_document_checklists(
        ADMIN, params={"senior_record_id": senior_id}
    )
    data = _ok(resp, "list checklists")
    items = data if isinstance(data, list) else data.get("data", [])
    assert len(items) == 1, f"expected exactly one checklist for senior, got {items}"
    return items[0]


def get_checklist_items(checklist_id) -> list:
    resp = api_client.list_checklist_items(checklist_id, ADMIN)
    data = _ok(resp, "list checklist items")
    return data if isinstance(data, list) else data.get("data", [])


def receive_and_verify_item(school, item_id) -> dict:
    resp = api_client.receive_checklist_item(item_id, coord(school))
    _ok(resp, "receive item")
    resp = api_client.verify_checklist_item(item_id, coord(school))
    return _ok(resp, "verify item")


def verify_all_items(school, checklist_id) -> list:
    """Receive + verify every item of the checklist; returns final items."""
    items = get_checklist_items(checklist_id)
    for item in items:
        receive_and_verify_item(school, item["id"])
    return get_checklist_items(checklist_id)


def create_specialist(campaign, languages=None, name="Spec Sal") -> dict:
    return create_staff(
        campaign, capabilities=["CASE_SPECIALIST"], languages=languages or ["en"],
        full_name=name,
    )


def create_support_case(school, senior_id, case_type="SPECIAL_CIRCUMSTANCE", **overrides) -> dict:
    resp = api_client.create_support_case(
        create_support_case_payload(senior_id, case_type=case_type, **overrides),
        coord(school),
    )
    return _ok(resp, "create support case")


def accept_case(case, specialist) -> dict:
    resp = api_client.accept_support_case(
        case["id"], make_specialist_headers(specialist["id"])
    )
    return _ok(resp, "accept case")


def spec_headers(specialist) -> dict:
    return make_specialist_headers(specialist["id"])


def setup_case_scenario(consent_scopes=("STATUS_DETAIL",)):
    """Campaign OPEN + school ENROLLED + specialist + consented senior.

    Returns dict(campaign, school, specialist, senior, consent).
    """
    campaign, school = setup_campaign_with_school()
    specialist = create_specialist(campaign)
    senior = add_senior(school)
    consent = (
        grant_consent(school, senior["id"], consent_scopes) if consent_scopes else None
    )
    return {
        "campaign": campaign,
        "school": school,
        "specialist": specialist,
        "senior": senior,
        "consent": consent,
    }


def setup_verification_case(campaign_overrides=None, consent_before_link=True):
    """Senior AUTO_CONFIRMED-matched to a VERIFICATION_SELECTED aid record, so
    the verification cascade has auto-created a VERIFICATION_FOLLOWUP case.

    With consent_before_link=True the case is born OPEN and assigned to the
    campaign's specialist. Returns dict with the full graph.
    """
    campaign, school = setup_campaign_with_school(
        campaign_overrides=campaign_overrides
    )
    specialist = create_specialist(campaign)
    senior, aid, link, consent = create_matched_senior(
        campaign,
        school,
        student_ref="S1",
        full_name="Ana Lee",
        dob="2009-03-04",
        home_language="en",
        aid_status="VERIFICATION_SELECTED",
        consent_scopes=["STATUS_DETAIL"],
        consent_before_link=consent_before_link,
    )
    resp = api_client.list_support_cases(ADMIN, params={"senior_record_id": senior["id"]})
    data = _ok(resp, "list cases for senior")
    cases = data if isinstance(data, list) else data.get("data", [])
    assert len(cases) == 1, f"expected one auto-created case, got {cases}"
    case = cases[0]
    assert case["case_type"] == "VERIFICATION_FOLLOWUP"
    return {
        "campaign": campaign,
        "school": school,
        "specialist": specialist,
        "senior": senior,
        "aid_record": aid,
        "link": link,
        "consent": consent,
        "case": case,
    }


# ---------------------------------------------------------------------------
# Tier 5: reports
# ---------------------------------------------------------------------------
def generate_report(campaign, variant="SUBMISSION_BASED") -> dict:
    resp = api_client.create_completion_report(
        create_completion_report_payload(campaign["id"], variant=variant), ADMIN
    )
    return _ok(resp, "generate report")


def publish_report(campaign_id, report_id) -> dict:
    """Publish with the campaign's freshly-read version (PRD §2.8 OCC)."""
    version = get_campaign(campaign_id)["version"]
    resp = api_client.publish_completion_report(report_id, version, ADMIN)
    return _ok(resp, "publish report")


def setup_dual_variant_scenario():
    """Three matched, DATA_SHARE-consented seniors with fafsa_status COMPLETE,
    VERIFICATION_SELECTED and SUBMITTED. Returns (campaign, school)."""
    campaign, school = setup_campaign_with_school(
        campaign_overrides={"min_subgroup_size": 1, "name": "C27"}
    )
    specs = [
        ("S1", "Ana Lee", "2009-03-04", "en", "COMPLETE", "2027-02-01"),
        ("S2", "Bob Kim", "2009-05-06", "es", "VERIFICATION_SELECTED", "2027-02-02"),
        ("S3", "Cat Diaz", "2009-07-08", "es", "SUBMITTED", "2027-02-03"),
    ]
    for student_ref, name, dob, lang, status, eff in specs:
        add_report_senior(
            campaign,
            school,
            student_ref=student_ref,
            full_name=name,
            dob=dob,
            home_language=lang,
            aid_status=status,
            aid_effective_date=eff,
        )
    return campaign, school


def setup_language_rate_scenario():
    """LANGUAGE/en: 5 eligible seniors, 1 completed; LANGUAGE/es: 6 eligible,
    1 completed (all matched + DATA_SHARE consented; min_subgroup_size 1).

    Row rates round to 20.0 and 16.7 while the totals-first overall rate is
    18.2 (2/11), which differs from the rounded average of row rates (18.4).
    """
    campaign, school = setup_campaign_with_school(
        campaign_overrides={"min_subgroup_size": 1, "name": "C27"}
    )
    en_specs = [("EN1", "En One", "SUBMITTED")] + [
        (f"EN{i}", f"En {name}", "STARTED")
        for i, name in enumerate(["Two", "Three", "Four", "Five"], start=2)
    ]
    es_specs = [("ES1", "Es One", "SUBMITTED")] + [
        (f"ES{i}", f"Es {name}", "STARTED")
        for i, name in enumerate(["Two", "Three", "Four", "Five", "Six"], start=2)
    ]
    dob_seq = iter(
        [f"2009-01-0{i}" for i in range(1, 6)] + [f"2009-02-0{i}" for i in range(1, 7)]
    )
    for lang, specs in (("en", en_specs), ("es", es_specs)):
        for student_ref, name, status in specs:
            add_report_senior(
                campaign,
                school,
                student_ref=student_ref,
                full_name=name,
                dob=next(dob_seq),
                home_language=lang,
                aid_status=status,
            )
    return campaign, school


def setup_recognition_scenario():
    """Four ENROLLED schools with 4 matched + DATA_SHARE-consented seniors each
    and SUBMITTED counts 4/3/2/1, giving SUBMISSION_BASED rates
    100.0 / 75.0 / 50.0 / 25.0 (min_recognition_seniors=4).

    Ascending rates [25, 50, 75, 100] with N=4 give cutoffs c70 = value at
    ceil(0.70*4)=3 -> 75.0 and c40 = value at ceil(0.40*4)=2 -> 50.0.
    Returns dict(campaign=..., schools={letter: school}).
    """
    campaign = create_open_campaign(name="C27", min_recognition_seniors=4)
    plan = [
        ("A", "Alpha HS", "D01", "SC0A", 4),
        ("B", "Beta HS", "D01", "SC0B", 3),
        ("C", "Gamma HS", "D02", "SC0C", 2),
        ("D", "Delta HS", "D02", "SC0D", 1),
    ]
    schools = {}
    for letter, name, district, school_code, submitted_count in plan:
        school = add_school(
            campaign, name=name, district_code=district, school_code=school_code
        )
        school = enroll_school(school)
        schools[letter] = school
        for i in range(1, 5):
            status = "SUBMITTED" if i <= submitted_count else "STARTED"
            add_report_senior(
                campaign,
                school,
                student_ref=f"{letter}{i}",
                full_name=f"{letter} {['One', 'Two', 'Three', 'Four'][i - 1]}",
                dob=f"2009-01-0{i}",
                home_language="en",
                aid_status=status,
            )
    return {"campaign": campaign, "schools": schools}
