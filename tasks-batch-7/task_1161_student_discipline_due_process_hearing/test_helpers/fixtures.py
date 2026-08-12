"""Composite setup helpers for multi-step test prerequisites.

The server is restarted before every test, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Setup steps use
get_success_data() (lenient) so failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_student_payload,
    create_offense_code_payload,
    create_sanction_band_payload,
    create_case_payload,
    create_classify_payload,
    create_sanction_payload,
    create_notice_payload,
    create_conference_payload,
    create_conference_outcome_payload,
    create_appeal_payload,
    create_appeal_decision_payload,
    create_hearing_payload,
    create_evidence_payload,
    create_evidence_ruling_payload,
    create_hearing_decision_payload,
    create_mdr_schedule_payload,
    create_mdr_complete_payload,
    create_alt_ed_site_payload,
    create_placement_payload,
    create_placement_outcome_payload,
    create_re_entry_plan_payload,
    create_expungement_request_payload,
    create_expungement_decision_payload,
    create_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_district_admin_headers,
    make_school_admin_headers,
    make_hearing_officer_headers,
    make_parent_guardian_headers,
    make_student_services_headers,
)

ADMIN = TEST_USERS["district_admin_headers"]
REF = TEST_USERS["school_referrer_headers"]
CLS = TEST_USERS["school_classifier_headers"]
SSD = TEST_USERS["student_services_headers"]


# ─── Tier 0: clock + config primitives ────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4). Returns {current_utc}."""
    res = api_client.set_clock(create_clock_payload(to_iso8601), ADMIN)
    return get_success_data(res)


def create_offense_code(code="DISR-01", title="Disruption", category="DISRUPTION",
                        severity_level=2, expellable=False) -> dict:
    res = api_client.create_offense_code(
        create_offense_code_payload(code=code, title=title, category=category,
                                    severity_level=severity_level, expellable=expellable),
        ADMIN,
    )
    return get_success_data(res)


def add_sanction_band(offense_code_id: str, occurrence_index: int,
                      min_days: int, max_days: int) -> dict:
    res = api_client.create_sanction_band(
        offense_code_id,
        create_sanction_band_payload(occurrence_index, min_days, max_days),
        ADMIN,
    )
    return get_success_data(res)


def create_offense_code_with_bands(bands=((1, 1, 3),), **oc_kwargs) -> dict:
    """Offense code plus one sanction band per (index, min, max) tuple."""
    oc = create_offense_code(**oc_kwargs)
    for occurrence_index, min_days, max_days in bands:
        add_sanction_band(oc["id"], occurrence_index, min_days, max_days)
    return oc


def create_student(guardian_id="g1", disability_status=None, demographic_group="WHITE",
                   full_name="Stu Test", grade_level=9,
                   date_of_birth="2010-05-01T00:00:00Z", headers=None) -> dict:
    payload = create_student_payload(
        full_name=full_name, date_of_birth=date_of_birth, grade_level=grade_level,
        demographic_group=demographic_group, guardian_id=guardian_id,
    )
    if disability_status is not None:
        payload["disability_status"] = disability_status
    res = api_client.create_student(payload, headers or REF)
    return get_success_data(res)


def create_alt_ed_site(name="Site A", capacity=5) -> dict:
    res = api_client.create_alt_ed_site(create_alt_ed_site_payload(name, capacity), ADMIN)
    return get_success_data(res)


# ─── Tier 1: case state progression ───────────────────

def create_case(student_id, incident_date="2026-05-04T08:00:00Z",
                description="incident report", referrer_id="admin_ref_1") -> dict:
    """Create a referral; returns the case in SUBMITTED (referrer_id = X-User-ID)."""
    res = api_client.create_case(
        create_case_payload(student_id, incident_date, description=description),
        make_school_admin_headers(referrer_id),
    )
    return get_success_data(res)


def get_case(case_id, headers=None) -> dict:
    return get_success_data(api_client.get_case(case_id, headers or CLS))


def classify_case(case_id, offense_code_id, expected_version,
                  classifier_id="admin_adj_1") -> dict:
    res = api_client.classify_case(
        case_id,
        create_classify_payload(offense_code_id, expected_version),
        make_school_admin_headers(classifier_id),
    )
    return get_success_data(res)


def propose_sanction(case_id, sanction_days, expected_version,
                     sanction_type="OUT_OF_SCHOOL", override_justification=None,
                     admin_id="admin_adj_1") -> dict:
    payload = create_sanction_payload(sanction_days, expected_version,
                                      sanction_type=sanction_type)
    if override_justification is not None:
        payload["override_justification"] = override_justification
    res = api_client.propose_sanction(case_id, payload, make_school_admin_headers(admin_id))
    return get_success_data(res)


def issue_notice(case_id, delivery_method="EMAIL", admin_id="admin_adj_1") -> dict:
    """Issue the suspension notice; returns the SuspensionNotice (ISSUED)."""
    res = api_client.issue_notice(
        case_id, create_notice_payload(delivery_method),
        make_school_admin_headers(admin_id),
    )
    return get_success_data(res)


def confirm_case(case_id, admin_id="admin_adj_1") -> dict:
    res = api_client.confirm_case(case_id, {}, make_school_admin_headers(admin_id))
    return get_success_data(res)


def close_case(case_id, admin_id="admin_adj_1") -> dict:
    res = api_client.close_case(case_id, {}, make_school_admin_headers(admin_id))
    return get_success_data(res)


def refer_expulsion(case_id, admin_id="admin_adj_1") -> dict:
    res = api_client.refer_expulsion(case_id, {}, make_school_admin_headers(admin_id))
    return get_success_data(res)


def create_classified_case(student_id, offense_code_id,
                           incident_date="2026-05-04T08:00:00Z",
                           description="incident report", referrer_id="admin_ref_1",
                           classifier_id="admin_adj_1") -> dict:
    """Create a referral and classify it. Returns the case in CLASSIFIED."""
    case = create_case(student_id, incident_date, description, referrer_id)
    return classify_case(case["id"], offense_code_id, case["version"], classifier_id)


def create_sanctioned_case(student_id, offense_code_id,
                           incident_date="2026-05-04T08:00:00Z", *,
                           sanction_days=2, sanction_type="OUT_OF_SCHOOL",
                           override_justification=None, description="incident report",
                           referrer_id="admin_ref_1", classifier_id="admin_adj_1") -> dict:
    """Create -> classify -> propose. Returns the case in SANCTION_PROPOSED."""
    case = create_classified_case(student_id, offense_code_id, incident_date,
                                  description, referrer_id, classifier_id)
    return propose_sanction(case["id"], sanction_days, case["version"],
                            sanction_type, override_justification, classifier_id)


# ─── Tier 2: due-process window chains ────────────────

def setup_notice_issued_case(*, guardian_id="g1", disability_status=None,
                             demographic_group="WHITE", full_name="Stu Test",
                             grade_level=9, date_of_birth="2010-05-01T00:00:00Z",
                             offense_code="DISR-01", offense_title="Disruption",
                             category="DISRUPTION", severity_level=2, expellable=False,
                             bands=((1, 1, 3),), incident_date="2026-05-04T08:00:00Z",
                             clock="2026-05-04T09:00:00Z", sanction_days=2,
                             sanction_type="OUT_OF_SCHOOL", override_justification=None,
                             delivery_method="EMAIL", referrer_id="admin_ref_1",
                             classifier_id="admin_adj_1") -> dict:
    """Clock set -> offense code + bands -> student -> case -> classify ->
    sanction -> notice. Returns {student, offense_code, case, notice} with the
    case in NOTICE_ISSUED (case state refreshed after issuance)."""
    set_clock(clock)
    oc = create_offense_code_with_bands(
        bands=bands, code=offense_code, title=offense_title, category=category,
        severity_level=severity_level, expellable=expellable,
    )
    student = create_student(guardian_id=guardian_id, disability_status=disability_status,
                             demographic_group=demographic_group, full_name=full_name,
                             grade_level=grade_level, date_of_birth=date_of_birth)
    case = create_sanctioned_case(
        student["id"], oc["id"], incident_date,
        sanction_days=sanction_days, sanction_type=sanction_type,
        override_justification=override_justification,
        referrer_id=referrer_id, classifier_id=classifier_id,
    )
    notice = issue_notice(case["id"], delivery_method, classifier_id)
    case = get_case(case["id"])
    return {"student": student, "offense_code": oc, "case": case, "notice": notice}


def setup_confirmed_case(*, confirm_clock="2026-05-11T00:00:00Z", **kwargs) -> dict:
    """setup_notice_issued_case + clock advanced past the appeal deadline +
    confirm. Returns the dict with the case in CONFIRMED and the notice.

    The default confirm_clock (2026-05-11) sits past both the conference
    deadline (issued 2026-05-04T09:00 + 3 days) and the appeal deadline
    (+5 days), so both confirmation gates pass on the clock alone (PRD §3.4).
    """
    bundle = setup_notice_issued_case(**kwargs)
    set_clock(confirm_clock)
    bundle["case"] = confirm_case(bundle["case"]["id"])
    return bundle


def setup_closed_case(*, confirm_clock="2026-05-11T00:00:00Z",
                      close_clock="2026-05-13T00:00:00Z", **kwargs) -> dict:
    """Full ordinary track through CLOSED. The default close_clock is exactly
    confirmed_at (2026-05-11) + sanction_days (2) days (PRD §3.8)."""
    bundle = setup_confirmed_case(confirm_clock=confirm_clock, **kwargs)
    set_clock(close_clock)
    bundle["case"] = close_case(bundle["case"]["id"])
    return bundle


def setup_appeal_filed_case(*, appeal_clock="2026-05-05T09:00:00Z",
                            grounds="appeal grounds", **kwargs) -> dict:
    """setup_notice_issued_case + guardian appeal FILED within the window.
    Returns the bundle with an extra 'appeal' entry."""
    bundle = setup_notice_issued_case(**kwargs)
    set_clock(appeal_clock)
    appeal = get_success_data(api_client.file_appeal(
        bundle["case"]["id"], create_appeal_payload(grounds),
        make_parent_guardian_headers(bundle["student"]["guardian_id"]),
    ))
    bundle["appeal"] = appeal
    return bundle


# ─── Tier 3: expulsion hearing chains ─────────────────

def setup_expulsion_referred_case(*, guardian_id="g4", disability_status=None,
                                  demographic_group="WHITE", full_name="Stu Exp",
                                  grade_level=11, date_of_birth="2008-05-01T00:00:00Z",
                                  offense_code="WEAP-01", offense_title="Weapon possession",
                                  category="WEAPONS", severity_level=4,
                                  incident_date="2026-05-01T00:00:00Z",
                                  clock="2026-05-04T00:00:00Z",
                                  referrer_id="admin_ref_1",
                                  classifier_id="admin_adj_1") -> dict:
    """Student + expellable offense + case classified + referred to the
    expulsion track. Returns {student, offense_code, case} with the case in
    EXPULSION_REFERRED."""
    set_clock(clock)
    oc = create_offense_code(code=offense_code, title=offense_title,
                             category=category, severity_level=severity_level,
                             expellable=True)
    student = create_student(guardian_id=guardian_id, disability_status=disability_status,
                             demographic_group=demographic_group, full_name=full_name,
                             grade_level=grade_level, date_of_birth=date_of_birth)
    case = create_classified_case(student["id"], oc["id"], incident_date,
                                  referrer_id=referrer_id, classifier_id=classifier_id)
    case = refer_expulsion(case["id"], classifier_id)
    return {"student": student, "offense_code": oc, "case": case}


def create_hearing(case_id, officer_id="ho_1",
                   scheduled_start="2026-05-08T10:00:00Z",
                   scheduled_end="2026-05-08T12:00:00Z", admin_id="da_1") -> dict:
    res = api_client.create_hearing(
        create_hearing_payload(case_id, officer_id, scheduled_start, scheduled_end),
        make_district_admin_headers(admin_id),
    )
    return get_success_data(res)


def submit_evidence(hearing_id, item_type="DOCUMENT", description="incident report",
                    admin_id="admin_adj_1") -> dict:
    res = api_client.submit_evidence(
        hearing_id, create_evidence_payload(item_type, description),
        make_school_admin_headers(admin_id),
    )
    return get_success_data(res)


def rule_evidence(evidence_item_id, ruling, officer_id="ho_1") -> dict:
    res = api_client.rule_evidence(
        evidence_item_id, create_evidence_ruling_payload(ruling),
        make_hearing_officer_headers(officer_id),
    )
    return get_success_data(res)


def serve_packet(hearing_id, admin_id="admin_adj_1") -> dict:
    res = api_client.serve_packet(hearing_id, {}, make_school_admin_headers(admin_id))
    return get_success_data(res)


def convene_hearing(hearing_id, officer_id="ho_1") -> dict:
    res = api_client.convene_hearing(hearing_id, {}, make_hearing_officer_headers(officer_id))
    return get_success_data(res)


def decide_hearing(hearing_id, outcome, officer_id="ho_1", rationale=None) -> dict:
    res = api_client.decide_hearing(
        hearing_id, create_hearing_decision_payload(outcome, rationale),
        make_hearing_officer_headers(officer_id),
    )
    return get_success_data(res)


def create_hearing_with_admitted_evidence(case_id, officer_id="ho_1",
                                          scheduled_start="2026-05-08T10:00:00Z",
                                          scheduled_end="2026-05-08T12:00:00Z",
                                          item_type="DOCUMENT",
                                          description="incident report") -> dict:
    """Hearing + one evidence item ruled ADMITTED by the assigned officer.
    The caller must hold the clock at or before scheduled_start - 2 days if a
    packet service follows."""
    hearing = create_hearing(case_id, officer_id, scheduled_start, scheduled_end)
    evidence = submit_evidence(hearing["id"], item_type, description)
    evidence = rule_evidence(evidence["id"], "ADMITTED", officer_id)
    return {"hearing": hearing, "evidence": evidence}


def setup_hearing_held(case_id, officer_id="ho_1",
                       scheduled_start="2026-05-08T10:00:00Z",
                       scheduled_end="2026-05-08T12:00:00Z",
                       item_type="DOCUMENT", description="incident report") -> dict:
    """Hearing + admitted evidence + packet served (clock must be <= start - 2d
    at call time) + clock advanced to scheduled_end + convene. Returns
    {hearing, evidence} with the hearing in HELD."""
    bundle = create_hearing_with_admitted_evidence(
        case_id, officer_id, scheduled_start, scheduled_end, item_type, description)
    serve_packet(bundle["hearing"]["id"])
    set_clock(scheduled_end)
    bundle["hearing"] = convene_hearing(bundle["hearing"]["id"], officer_id)
    return bundle


def setup_expulsion_active_case(*, officer_id="ho_1",
                                referral_clock="2026-05-01T00:00:00Z",
                                incident_date="2026-05-01T00:00:00Z",
                                scheduled_start="2026-05-05T10:00:00Z",
                                scheduled_end="2026-05-05T11:00:00Z",
                                decision_clock=None, **case_kwargs) -> dict:
    """Full expulsion chain: referred case -> hearing -> admitted evidence ->
    packet served -> convene -> EXPULSION_ORDERED. Returns
    {student, offense_code, case, hearing, evidence} with the case in
    EXPULSION_ACTIVE and the student in ALT_ED_PENDING (PRD §3.5 cascade).

    Default timings keep the packet service (at referral_clock) ahead of the
    evidence deadline (scheduled_start - 2 days) and the hearing start inside
    the ten-day scheduling window.
    """
    bundle = setup_expulsion_referred_case(
        clock=referral_clock, incident_date=incident_date, **case_kwargs)
    evidence_bundle = create_hearing_with_admitted_evidence(
        bundle["case"]["id"], officer_id, scheduled_start, scheduled_end,
        item_type="DOCUMENT", description="hearing evidence")
    serve_packet(evidence_bundle["hearing"]["id"])
    set_clock(decision_clock or scheduled_end)
    convene_hearing(evidence_bundle["hearing"]["id"], officer_id)
    hearing = decide_hearing(evidence_bundle["hearing"]["id"], "EXPULSION_ORDERED",
                             officer_id)
    bundle["hearing"] = hearing
    bundle["evidence"] = evidence_bundle["evidence"]
    bundle["case"] = get_case(bundle["case"]["id"])
    return bundle


# ─── Tier 4: placements, re-entry, MDR ────────────────

def create_placement(case_id, site_id, start_date="2026-05-11T00:00:00Z",
                     planned_end_date="2026-05-29T00:00:00Z",
                     director_id="ssd_1") -> dict:
    res = api_client.create_placement(
        create_placement_payload(case_id, site_id, start_date, planned_end_date),
        make_student_services_headers(director_id),
    )
    return get_success_data(res)


def activate_placement(placement_id, director_id="ssd_1") -> dict:
    res = api_client.activate_placement(
        placement_id, {}, make_student_services_headers(director_id))
    return get_success_data(res)


def complete_placement(placement_id, outcome="COMPLETED", director_id="ssd_1") -> dict:
    res = api_client.complete_placement(
        placement_id, create_placement_outcome_payload(outcome),
        make_student_services_headers(director_id))
    return get_success_data(res)


def create_re_entry_plan(placement_id, conditions=None,
                         conference_date="2026-05-26T00:00:00Z",
                         director_id="ssd_1") -> dict:
    res = api_client.create_re_entry_plan(
        placement_id, create_re_entry_plan_payload(conditions, conference_date),
        make_student_services_headers(director_id))
    return get_success_data(res)


def list_open_mdrs(case_id, headers=None) -> list:
    data = get_success_data(api_client.list_manifestation_determinations(
        case_id, headers or SSD))
    return data


def setup_case_with_auto_mdr(*, disability_status="IEP", guardian_id="g8",
                             demographic_group="BLACK", confirmed_days=4,
                             proposed_days=7, bands=((1, 1, 3), (2, 2, 4)),
                             first_incident="2026-05-04T08:00:00Z",
                             second_incident="2026-05-12T00:00:00Z",
                             first_clock="2026-05-04T09:00:00Z",
                             confirm_clock="2026-05-11T00:00:00Z",
                             second_clock="2026-05-12T00:00:00Z") -> dict:
    """A disability-status student whose first case is CONFIRMED with
    `confirmed_days` days (override justification over the occurrence-1 band),
    and whose second case is classified (occurrence 2) and sanctioned with
    `proposed_days` (override) so that cumulative + proposed > 10 and an
    AUTO_THRESHOLD manifestation determination opens PENDING (PRD §3.3).

    Returns {student, offense_code, case1, notice1, case2, mdrs}.
    """
    set_clock(first_clock)
    oc = create_offense_code_with_bands(bands=bands, code="DISR-01",
                                        category="DISRUPTION", severity_level=2)
    student = create_student(guardian_id=guardian_id,
                             disability_status=disability_status,
                             demographic_group=demographic_group)
    case1 = create_sanctioned_case(
        student["id"], oc["id"], first_incident,
        sanction_days=confirmed_days, override_justification="aggravated disruption")
    notice1 = issue_notice(case1["id"])
    set_clock(confirm_clock)
    case1 = confirm_case(case1["id"])
    set_clock(second_clock)
    case2 = create_case(student["id"], second_incident, "second incident")
    case2 = classify_case(case2["id"], oc["id"], case2["version"])
    case2 = propose_sanction(case2["id"], proposed_days, case2["version"],
                             "OUT_OF_SCHOOL", "severe escalation")
    mdrs = list_open_mdrs(case2["id"])
    return {"student": student, "offense_code": oc, "case1": case1,
            "notice1": notice1, "case2": case2, "mdrs": mdrs}


# ─── Tier 5: disproportionality / expungement scenarios ─

def make_confirmed_case(student_id, offense_code_id, *, incident_date,
                        sanction_days, work_clock, confirm_clock,
                        sanction_type="OUT_OF_SCHOOL", override_justification=None,
                        delivery_method="EMAIL", description="incident",
                        referrer_id="admin_ref_1", classifier_id="admin_adj_1") -> dict:
    """One full ordinary-track case ending CONFIRMED. The referral,
    classification, proposal and notice all happen at `work_clock` (so the
    notice sits inside the one-day window); the confirm happens at
    `confirm_clock`, which must sit past the appeal deadline (work_clock + 5d).
    Returns the CONFIRMED case."""
    set_clock(work_clock)
    case = create_sanctioned_case(
        student_id, offense_code_id, incident_date,
        sanction_days=sanction_days, sanction_type=sanction_type,
        override_justification=override_justification, description=description,
        referrer_id=referrer_id, classifier_id=classifier_id)
    issue_notice(case["id"], delivery_method, classifier_id)
    set_clock(confirm_clock)
    return confirm_case(case["id"], classifier_id)


def setup_disproportionality_scenario() -> dict:
    """Six BLACK students (b1..b6) and three WHITE students (w1..w3), all
    disability NONE; b1 and w1 each hold exactly one CONFIRMED 1-day IN_SCHOOL
    case (ATTENDANCE) with incident_date 2026-03-02, inside academic year
    2025-2026. Returns {offense_code, black: [...], white: [...], cases: {...}}.
    """
    set_clock("2026-03-01T00:00:00Z")
    oc = create_offense_code_with_bands(
        bands=((1, 1, 2),), code="TARD-01", title="Tardiness",
        category="ATTENDANCE", severity_level=1)
    black = [
        create_student(guardian_id=f"g_b{i}", demographic_group="BLACK",
                       full_name=f"B {i}", date_of_birth=f"2010-01-0{i}T00:00:00Z")
        for i in range(1, 7)
    ]
    white = [
        create_student(guardian_id=f"g_w{i}", demographic_group="WHITE",
                       full_name=f"W {i}", date_of_birth=f"2010-02-0{i}T00:00:00Z")
        for i in range(1, 4)
    ]
    case_b1 = make_confirmed_case(
        black[0]["id"], oc["id"], incident_date="2026-03-02T00:00:00Z",
        sanction_days=1, sanction_type="IN_SCHOOL",
        work_clock="2026-03-01T00:00:00Z", confirm_clock="2026-03-09T00:00:00Z",
        description="b1 case")
    case_w1 = make_confirmed_case(
        white[0]["id"], oc["id"], incident_date="2026-03-02T00:00:00Z",
        sanction_days=1, sanction_type="IN_SCHOOL",
        work_clock="2026-03-09T00:00:00Z", confirm_clock="2026-03-16T00:00:00Z",
        description="w1 case")
    return {"offense_code": oc, "black": black, "white": white,
            "cases": {"b1": case_b1, "w1": case_w1}}


def get_report(academic_year="2025-2026", reference_group="WHITE") -> dict:
    """DistrictAdmin-only disproportionality report; returns the data payload."""
    res = api_client.get_disproportionality_report(
        ADMIN, params={"academic_year": academic_year,
                       "reference_group": reference_group})
    return get_success_data(res)


def group_row(report: dict, demographic_group: str) -> dict:
    """Locate a group's row inside report['results']."""
    for row in report["results"]:
        if row.get("demographic_group") == demographic_group:
            return row
    raise AssertionError(
        f"No results row for group {demographic_group!r}: {report['results']!r}")
