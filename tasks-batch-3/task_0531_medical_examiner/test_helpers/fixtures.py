"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures. Entity-backed roles are
always threaded through make_<role>_headers(entity_id) so ownership/identity checks pass.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_investigator_payload,
    create_pathologist_payload,
    create_cooler_unit_payload,
    create_case_payload,
    triage_payload,
    create_body_payload,
    store_body_payload,
    create_autopsy_exam_payload,
    complete_autopsy_exam_payload,
    create_specimen_payload,
    create_tox_screen_payload,
    result_tox_screen_payload,
    create_death_certificate_payload,
    sign_death_certificate_payload,
    create_next_of_kin_payload,
    create_property_item_payload,
    create_property_release_payload,
    create_indigent_disposition_payload,
)
from .test_users import (
    TEST_USERS,
    make_investigator_headers,
    make_pathologist_headers,
    make_medical_examiner_headers,
    make_labtech_headers,
)
from .constants import SERVED_COUNTY, UNSERVED_COUNTY

ADMIN = TEST_USERS["admin_headers"]
LABTECH = TEST_USERS["labtech_headers"]

_badge_counter = [0]
_license_counter = [0]
_tag_counter = [0]
_label_counter = [0]


def _next_badge():
    _badge_counter[0] += 1
    return f"BADGE-{_badge_counter[0]}"


def _next_license():
    _license_counter[0] += 1
    return f"LIC-{_license_counter[0]}"


def _next_tag():
    _tag_counter[0] += 1
    return f"TAG-{_tag_counter[0]}"


def _next_label():
    _label_counter[0] += 1
    return f"COOLER-{_label_counter[0]}"


# ─── Actor / config setup ─────────────────────────────

def set_clock(iso8601: str):
    """Advance/rewind the logical clock to an absolute instant."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


def create_investigator(full_name="Inv", badge_no=None):
    payload = create_investigator_payload(full_name=full_name, badge_no=badge_no or _next_badge())
    return get_success_data(api_client.create_investigator(payload, ADMIN))


def create_pathologist(full_name="Path", license_no=None, is_medical_examiner=False):
    payload = create_pathologist_payload(
        full_name=full_name, license_no=license_no or _next_license(),
        is_medical_examiner=is_medical_examiner,
    )
    return get_success_data(api_client.create_pathologist(payload, ADMIN))


def create_cooler(slot_capacity=2, label=None, out_of_service=False):
    payload = create_cooler_unit_payload(
        label=label or _next_label(), slot_capacity=slot_capacity, out_of_service=out_of_service,
    )
    return get_success_data(api_client.create_cooler_unit(payload, ADMIN))


# ─── Case lifecycle ───────────────────────────────────

def create_reported_case(investigator, county=SERVED_COUNTY, **overrides):
    """Report a death -> Case in REPORTED. investigator is the lead Investigator dict."""
    inv_headers = make_investigator_headers(investigator["id"])
    payload = create_case_payload(
        investigator["id"], death_location_county=county, **overrides
    )
    return get_success_data(api_client.create_case(payload, inv_headers))


def create_accepted_case(investigator, case_type="NATURAL", county=SERVED_COUNTY, **overrides):
    """Report + triage -> Case ACCEPTED (served county) with lane assigned."""
    case = create_reported_case(investigator, county=county, **overrides)
    inv_headers = make_investigator_headers(investigator["id"])
    case = get_success_data(
        api_client.triage_case(case["id"], triage_payload(case_type=case_type), inv_headers)
    )
    return case


def create_investigating_case(investigator, case_type="NATURAL", tag_no=None, **overrides):
    """Report + triage + first body -> Case INVESTIGATING. Returns (case, body)."""
    case = create_accepted_case(investigator, case_type=case_type, **overrides)
    inv_headers = make_investigator_headers(investigator["id"])
    body = get_success_data(
        api_client.create_body(case["id"], create_body_payload(tag_no=tag_no or _next_tag()), inv_headers)
    )
    return case, body


def store_body(investigator, body, cooler):
    """Store a body into a cooler using the cooler's current version. Returns updated body."""
    inv_headers = make_investigator_headers(investigator["id"])
    fresh_cooler = get_success_data(api_client.get_cooler_unit(cooler["id"], inv_headers))
    res = api_client.store_body(
        body["id"],
        store_body_payload(cooler["id"], fresh_cooler["version"]),
        inv_headers,
    )
    return get_success_data(res)


def get_case_version(reader_headers, case_id):
    """Read the case and return its current version (for OCC on sign)."""
    return get_success_data(api_client.get_case(case_id, reader_headers))["version"]


def draft_certificate(me, case, cause_of_death="cause", manner_of_death="NATURAL"):
    """ME drafts a DeathCertificate (DRAFT) for the case. Returns the cert dict."""
    me_headers = make_medical_examiner_headers(me["id"])
    payload = create_death_certificate_payload(
        cause_of_death=cause_of_death, manner_of_death=manner_of_death
    )
    return get_success_data(api_client.create_death_certificate(case["id"], payload, me_headers))


def sign_certificate(me, case_id, cert_id):
    """ME signs a certificate reading the case's current version for OCC. Returns cert dict."""
    me_headers = make_medical_examiner_headers(me["id"])
    case_v = get_case_version(me_headers, case_id)
    res = api_client.sign_death_certificate(
        cert_id, sign_death_certificate_payload(case_v), me_headers
    )
    return get_success_data(res)


# ─── Autopsy setup ────────────────────────────────────

def schedule_autopsy(pathologist, case, scheduled_for, duration_minutes):
    """Schedule an autopsy exam under a case. Returns the exam dict."""
    path_headers = make_pathologist_headers(pathologist["id"])
    payload = create_autopsy_exam_payload(pathologist["id"], scheduled_for, duration_minutes)
    return get_success_data(api_client.create_autopsy_exam(case["id"], payload, path_headers))


def complete_autopsy(pathologist, exam, primary_finding="finding", cause_of_death="cause"):
    """Complete a scheduled autopsy exam. Returns the completed exam dict."""
    path_headers = make_pathologist_headers(pathologist["id"])
    res = api_client.complete_autopsy_exam(
        exam["id"], complete_autopsy_exam_payload(primary_finding, cause_of_death), path_headers
    )
    return get_success_data(res)


# ─── Specimen / tox setup ─────────────────────────────

def collect_specimen(pathologist, body, specimen_type="BLOOD"):
    path_headers = make_pathologist_headers(pathologist["id"])
    return get_success_data(
        api_client.create_specimen(body["id"], create_specimen_payload(specimen_type), path_headers)
    )


def send_specimen_to_lab(pathologist, specimen):
    path_headers = make_pathologist_headers(pathologist["id"])
    return get_success_data(api_client.send_specimen_to_lab(specimen["id"], path_headers))


def order_tox_screen(specimen, panel="BASIC"):
    return get_success_data(
        api_client.create_tox_screen(specimen["id"], create_tox_screen_payload(panel), LABTECH)
    )


def result_tox_screen(tox, ethanol_mg_dl):
    return get_success_data(
        api_client.result_tox_screen(tox["id"], result_tox_screen_payload(ethanol_mg_dl), LABTECH)
    )


def setup_specimen_in_lab(investigator, pathologist, case_type="NATURAL", specimen_type="BLOOD"):
    """Full chain: investigating case + body + specimen SENT_TO_LAB. Returns (case, body, specimen)."""
    case, body = create_investigating_case(investigator, case_type=case_type)
    specimen = collect_specimen(pathologist, body, specimen_type)
    specimen = send_specimen_to_lab(pathologist, specimen)
    return case, body, specimen


def setup_ordered_tox(investigator, pathologist, case_type="NATURAL", panel="BASIC"):
    """Specimen SENT_TO_LAB with a ToxScreen ORDERED. Returns (case, body, specimen, tox)."""
    case, body, specimen = setup_specimen_in_lab(investigator, pathologist, case_type=case_type)
    tox = order_tox_screen(specimen, panel=panel)
    return case, body, specimen, tox


# ─── Property / kin / indigent setup ──────────────────

def add_property_item(investigator, case, description="item", valuation_cents=0):
    inv_headers = make_investigator_headers(investigator["id"])
    return get_success_data(
        api_client.create_property_item(
            case["id"], create_property_item_payload(description, valuation_cents), inv_headers
        )
    )


def add_next_of_kin(investigator, case, full_name="Kin", relationship="CHILD", verify=False):
    inv_headers = make_investigator_headers(investigator["id"])
    kin = get_success_data(
        api_client.create_next_of_kin(
            case["id"], create_next_of_kin_payload(full_name, relationship), inv_headers
        )
    )
    if verify:
        kin = get_success_data(api_client.verify_next_of_kin(kin["id"], inv_headers))
    return kin


def request_property_release(investigator, case, kin):
    inv_headers = make_investigator_headers(investigator["id"])
    return get_success_data(
        api_client.create_property_release(
            case["id"], create_property_release_payload(kin["id"]), inv_headers
        )
    )


def declare_indigent(investigator, case, statutory_allowance_cents, itemized_cost_cents):
    inv_headers = make_investigator_headers(investigator["id"])
    return get_success_data(
        api_client.create_indigent_disposition(
            case["id"],
            create_indigent_disposition_payload(statutory_allowance_cents, itemized_cost_cents),
            inv_headers,
        )
    )


# ─── Composite: certified case ────────────────────────

def setup_certified_case_natural(investigator, me, cooler=None, tag_no=None):
    """
    NATURAL case driven to CERTIFIED. Optionally stores the body in a cooler first
    (so the signed cert clears release_blocked). Returns (case, body).
    """
    case, body = create_investigating_case(investigator, case_type="NATURAL", tag_no=tag_no)
    if cooler is not None:
        body = store_body(investigator, body, cooler)
    cert = draft_certificate(me, case, manner_of_death="NATURAL")
    sign_certificate(me, case["id"], cert["id"])
    inv_headers = make_investigator_headers(investigator["id"])
    case = get_success_data(api_client.get_case(case["id"], inv_headers))
    body = get_success_data(api_client.get_body(body["id"], inv_headers))
    return case, body
