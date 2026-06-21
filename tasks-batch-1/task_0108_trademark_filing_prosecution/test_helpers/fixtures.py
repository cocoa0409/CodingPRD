"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through 5-15 API calls
to reach a specific lifecycle state. These helpers encapsulate those chains so
tests focus on assertions.

Uses get_success_data() (lenient validator) internally so a broken setup step
surfaces a clear "Setup step failed" error rather than a confusing assertion.

Identity threading: after creating an entity_backed Attorney/Applicant, every
ownership-gated call uses make_attorney_headers(att["id"]) /
make_applicant_headers(app["id"]) with the real entity id — never the shared
fallback constant.

NOTE: the test harness restarts the server (empty DB) before every test, so
every helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_attorney_payload,
    create_nice_class_payload,
    create_application_payload,
    create_goods_services_payload,
    create_office_action_payload,
    create_office_action_response_payload,
    create_ttab_proceeding_payload,
    create_madrid_application_payload,
)
from .test_users import (
    make_attorney_headers,
    make_applicant_headers,
    examiner_headers,
    ttab_clerk_headers,
)

# A fixed base instant used by most fixtures; tests that exercise time-gating
# advance the clock explicitly via set_clock().
BASE_CLOCK = "2026-01-01T00:00:00Z"

# Monotonic suffix so bar_numbers / mark_texts stay unique within a server run.
_seq = [0]


def _next() -> int:
    _seq[0] += 1
    return _seq[0]


# ─── Clock ─────────────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Set the server's current UTC clock (Examiner-only test-driving endpoint)."""
    return get_success_data(api_client.set_clock(iso, examiner_headers()))


# ─── Tier 0: base parties & reference data ──────────────────────────────────
def seed_nice_class(class_number: int, title: str = "Software") -> dict:
    return get_success_data(api_client.create_nice_class(
        create_nice_class_payload(class_number, title), examiner_headers()))


def create_attorney(bar_number: str = None) -> dict:
    bar = bar_number or f"BAR-{_next():05d}"
    # POST /attorneys is authorized for the Attorney role only (PRD §4). There
    # is no ownership gate on registering a new attorney, so a generic
    # Attorney-role header is the correct caller.
    return get_success_data(api_client.create_attorney(
        create_attorney_payload(bar_number=bar), make_attorney_headers("creator")))


def create_applicant(legal_name: str = "Acme US", country_code: str = "US",
                     acting_headers: dict = None) -> dict:
    """Create an Applicant. By default an Examiner-less actor is needed: POST
    /applicants is open to Attorney and Applicant. Pass acting_headers to use a
    specific caller; otherwise a generic Attorney-role header is used (no
    ownership gate on creation)."""
    headers = acting_headers or make_attorney_headers("creator")
    return get_success_data(api_client.create_applicant(
        create_applicant_payload(legal_name=legal_name, country_code=country_code),
        headers))


def setup_base_parties(clock: str = BASE_CLOCK, class_numbers=(9,)):
    """clock + N nice classes + one ACTIVE attorney + one US applicant.

    Returns dict: { attorney, applicant, nice_classes (list), att_headers,
    applicant_headers }.
    """
    set_clock(clock)
    nice_classes = [seed_nice_class(n, _title_for(n)) for n in class_numbers]
    attorney = create_attorney()
    att_headers = make_attorney_headers(attorney["id"])
    applicant = get_success_data(api_client.create_applicant(
        create_applicant_payload(), att_headers))
    return {
        "attorney": attorney,
        "applicant": applicant,
        "nice_classes": nice_classes,
        "att_headers": att_headers,
        "applicant_headers": make_applicant_headers(applicant["id"]),
    }


def _title_for(n: int) -> str:
    titles = {9: "Software", 25: "Clothing", 35: "Advertising", 42: "Tech services"}
    return titles.get(n, f"Class {n}")


# ─── Tier 1: draft / filed applications ─────────────────────────────────────
def create_draft_application(applicant_id, att_headers, attorney_id=None,
                             mark_text="MARK", filing_basis="USE",
                             filing_tier="TEAS_STANDARD", acting_headers=None) -> dict:
    headers = acting_headers or att_headers
    return get_success_data(api_client.create_application(
        create_application_payload(
            applicant_id=applicant_id, attorney_id=attorney_id, mark_text=mark_text,
            filing_basis=filing_basis, filing_tier=filing_tier),
        headers))


def add_item(application_id, nice_class_id, att_headers, description="downloadable software",
             pre_approved=None, acting_headers=None) -> dict:
    headers = acting_headers or att_headers
    return get_success_data(api_client.add_goods_services(
        application_id,
        create_goods_services_payload(nice_class_id, description, pre_approved),
        headers))


def setup_filed_application(clock: str = BASE_CLOCK, class_numbers=(9,),
                            filing_basis="USE", filing_tier="TEAS_STANDARD",
                            mark_text="FILED", pre_approved=None):
    """Base parties + a DRAFT app with one item per class + filed (DRAFT->FILED).

    For TEAS_PLUS, pre_approved defaults to True on every item unless overridden.
    Returns dict augmenting setup_base_parties with: application (post-file),
    items (list).
    """
    base = setup_base_parties(clock, class_numbers)
    att_headers = base["att_headers"]
    app = create_draft_application(
        base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
        mark_text=mark_text, filing_basis=filing_basis, filing_tier=filing_tier)
    pa = pre_approved
    if pa is None and filing_tier == "TEAS_PLUS":
        pa = True
    items = []
    for nc in base["nice_classes"]:
        items.append(add_item(app["id"], nc["id"], att_headers, pre_approved=pa))
    filed = get_success_data(api_client.file_application(app["id"], att_headers))
    base.update({"application": filed, "items": items})
    return base


# ─── Tier 2: examination-stage applications ─────────────────────────────────
def setup_examined_application(clock: str = BASE_CLOCK, class_numbers=(9,),
                               filing_basis="USE", filing_tier="TEAS_STANDARD",
                               mark_text="EXAM"):
    """Filed app advanced to UNDER_EXAMINATION."""
    base = setup_filed_application(clock, class_numbers, filing_basis, filing_tier, mark_text)
    examined = get_success_data(api_client.assign_examination(
        base["application"]["id"], examiner_headers()))
    base["application"] = examined
    return base


def issue_office_action(application_id, ground="MERELY_DESCRIPTIVE", is_final=False) -> dict:
    return get_success_data(api_client.create_office_action(
        create_office_action_payload(application_id, ground, is_final), examiner_headers()))


def respond_to_office_action(office_action_id, att_headers, argument_text="remarks",
                             amends_identification=None) -> dict:
    return get_success_data(api_client.create_office_action_response(
        create_office_action_response_payload(
            office_action_id, argument_text, amends_identification),
        att_headers))


def setup_application_with_outstanding_oa(clock: str = BASE_CLOCK, class_numbers=(9,),
                                          ground="MERELY_DESCRIPTIVE", is_final=False,
                                          filing_basis="USE", mark_text="OA"):
    """Examined app with one OUTSTANDING OfficeAction. Returns base dict +
    office_action."""
    base = setup_examined_application(clock, class_numbers, filing_basis, "TEAS_STANDARD", mark_text)
    oa = issue_office_action(base["application"]["id"], ground, is_final)
    base["office_action"] = oa
    return base


# ─── Tier 3: published / registered / allowed applications ──────────────────
def setup_published_application(clock: str = BASE_CLOCK, class_numbers=(9,),
                                filing_basis="USE", mark_text="PUB"):
    """App advanced to PUBLISHED (also opens the 30-day opposition window)."""
    base = setup_examined_application(clock, class_numbers, filing_basis, "TEAS_STANDARD", mark_text)
    published = get_success_data(api_client.approve_publication(
        base["application"]["id"], examiner_headers()))
    base["application"] = published
    return base


def setup_registered_application(clock: str = BASE_CLOCK, class_numbers=(9,),
                                 mark_text="REG"):
    """USE app walked all the way to REGISTERED. Returns base dict +
    registration (the new Registration resource)."""
    base = setup_published_application(clock, class_numbers, "USE", mark_text)
    reg = get_success_data(api_client.register_application(
        base["application"]["id"], examiner_headers()))
    base["registration"] = reg
    # Refresh the application so callers see REGISTERED status.
    base["application"] = get_success_data(api_client.get_application(
        base["application"]["id"], examiner_headers()))
    return base


def setup_allowed_application(clock: str = BASE_CLOCK, class_numbers=(9,),
                              mark_text="ALLOW"):
    """INTENT app walked to ALLOWED (Notice of Allowance issued)."""
    base = setup_published_application(clock, class_numbers, "INTENT", mark_text)
    allowed = get_success_data(api_client.issue_allowance(
        base["application"]["id"], examiner_headers()))
    base["application"] = allowed
    return base


# ─── Tier 4: TTAB proceedings ───────────────────────────────────────────────
def institute_opposition(target_application_id, petitioner_applicant_id, att_headers):
    """Institute an OPPOSITION against a published application. att_headers must
    belong to the attorney of record for the petitioner (the corner/difficulty
    setups institute via the attorney of record)."""
    return get_success_data(api_client.create_ttab_proceeding(
        create_ttab_proceeding_payload(
            "OPPOSITION", petitioner_applicant_id,
            target_application_id=target_application_id),
        att_headers))


def institute_cancellation(target_registration_id, petitioner_applicant_id, att_headers):
    return get_success_data(api_client.create_ttab_proceeding(
        create_ttab_proceeding_payload(
            "CANCELLATION", petitioner_applicant_id,
            target_registration_id=target_registration_id),
        att_headers))


def setup_opposition_with_owner_and_rival(clock: str = BASE_CLOCK, class_numbers=(9,),
                                          mark_text="OPP"):
    """Published USE app owned by 'Owner Co'; an opposition instituted by a
    rival applicant. Returns dict: attorney, owner, rival, application,
    proceeding, att_headers.
    """
    set_clock(clock)
    nice = [seed_nice_class(n, _title_for(n)) for n in class_numbers]
    attorney = create_attorney()
    att_headers = make_attorney_headers(attorney["id"])
    owner = get_success_data(api_client.create_applicant(
        create_applicant_payload(legal_name="Owner Co"), att_headers))
    rival = get_success_data(api_client.create_applicant(
        create_applicant_payload(legal_name="Rival Co"), att_headers))
    app = create_draft_application(
        owner["id"], att_headers, attorney_id=attorney["id"],
        mark_text=mark_text, filing_basis="USE", filing_tier="TEAS_STANDARD")
    for nc in nice:
        add_item(app["id"], nc["id"], att_headers)
    get_success_data(api_client.file_application(app["id"], att_headers))
    get_success_data(api_client.assign_examination(app["id"], examiner_headers()))
    published = get_success_data(api_client.approve_publication(app["id"], examiner_headers()))
    proceeding = institute_opposition(published["id"], rival["id"], att_headers)
    return {
        "attorney": attorney,
        "owner": owner,
        "rival": rival,
        "application": published,
        "proceeding": proceeding,
        "att_headers": att_headers,
        "owner_headers": make_applicant_headers(owner["id"]),
        "rival_headers": make_applicant_headers(rival["id"]),
        "nice_classes": nice,
    }


def answer_proceeding(proceeding_id, defendant_headers):
    return get_success_data(api_client.answer_ttab_proceeding(proceeding_id, defendant_headers))


def set_for_trial(proceeding_id):
    return get_success_data(api_client.set_for_trial_ttab_proceeding(
        proceeding_id, ttab_clerk_headers()))


# ─── Tier 5: Madrid international applications ───────────────────────────────
def create_madrid(basic_application_id, designated_countries, att_headers):
    return get_success_data(api_client.create_madrid_application(
        create_madrid_application_payload(basic_application_id, designated_countries),
        att_headers))


def setup_registered_with_certified_madrid(clock: str = BASE_CLOCK, class_numbers=(9,),
                                           designated_countries=("FR", "DE", "JP"),
                                           mark_text="CENTRAL"):
    """USE app registered + a CERTIFIED Madrid app based on it, plus a rival
    applicant available to bring a cancellation. Returns dict.
    """
    base = setup_registered_application(clock, class_numbers, mark_text)
    att_headers = base["att_headers"]
    madrid = create_madrid(
        base["application"]["id"], list(designated_countries), att_headers)
    certified = get_success_data(api_client.certify_madrid_application(
        madrid["id"], examiner_headers()))
    rival = get_success_data(api_client.create_applicant(
        create_applicant_payload(legal_name="Rival Co"), att_headers))
    base.update({"madrid": certified, "rival": rival,
                 "rival_headers": make_applicant_headers(rival["id"])})
    return base
