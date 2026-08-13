"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors. Ownership-gated calls use per-instance headers
from test_users (ClientContact is entity-backed by Client).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STARTUP_CLOCK
from .factories import (
    agreement_payload,
    assess_payload,
    clearance_search_payload,
    create_alert_payload,
    create_client_payload,
    create_record_payload,
    docket_deadline_payload,
    draft_letter_payload,
    evidence_payload,
    maintenance_filing_payload,
    propose_payload,
    recordation_payload,
    referral_payload,
    takedown_payload,
)
from .test_users import (
    TEST_USERS,
    make_associate_headers,
    make_client_contact_headers,
    make_paralegal_headers,
    make_partner_headers,
    make_watch_service_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PARA = TEST_USERS["paralegal_headers"]
ASSOC = TEST_USERS["associate_headers"]
PARTNER = TEST_USERS["partner_headers"]
WATCH = TEST_USERS["watch_service_headers"]


# ─── Tier 1: single-entity state progression ──────────

def create_client(budget=500000, name="Acme Brands", industry="consumer goods") -> dict:
    res = api_client.create_client(
        create_client_payload(name=name, industry=industry, enforcement_budget_cents=budget),
        ADMIN,
    )
    return get_success_data(res)


def get_client(client_id: str) -> dict:
    return get_success_data(api_client.get_client(client_id, PARA))


def create_record(client_id: str, mark_text="ACME", classes=(9,), app_no="US-901") -> dict:
    res = api_client.create_trademark_record(
        create_record_payload(
            client_id, mark_text=mark_text, nice_classes=list(classes), application_number=app_no
        ),
        PARA,
    )
    return get_success_data(res)


def publish_record(record_id: str, publication_date="2026-08-03T00:00:00Z") -> dict:
    res = api_client.publish_record(record_id, {"publication_date": publication_date}, PARA)
    return get_success_data(res)


def register_record(record_id: str, registration_date="2026-08-10T00:00:00Z") -> dict:
    res = api_client.register_record(record_id, {"registration_date": registration_date}, PARA)
    return get_success_data(res)


def get_record(record_id: str) -> dict:
    return get_success_data(api_client.get_trademark_record(record_id, PARA))


def setup_published_record(budget=500000, classes=(9,), publication_date="2026-08-03T00:00:00Z"):
    """Client + record in PUBLISHED. Returns (client, record)."""
    client = create_client(budget=budget)
    record = create_record(client["id"], classes=classes)
    record = publish_record(record["id"], publication_date)
    return client, record


def setup_registered_record(
    budget=500000,
    classes=(9,),
    registration_date="2026-08-10T00:00:00Z",
    publication_date="2026-08-03T00:00:00Z",
):
    """Client + record in REGISTERED. Returns (client, record)."""
    client, record = setup_published_record(budget=budget, classes=classes,
                                            publication_date=publication_date)
    record = register_record(record["id"], registration_date)
    return client, record


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_current_utc(to_iso8601, ADMIN))


# ─── Watch alerts ─────────────────────────────────────

def create_alert(record_id: str, similarity_mark=80, similarity_goods=70,
                 similarity_channels=60, source="WATCH_SERVICE",
                 conflicting_classes=(9,), conflicting_mark_text="AKME",
                 conflicting_owner="Rival Co", headers=None) -> dict:
    res = api_client.create_watch_alert(
        create_alert_payload(
            record_id,
            source=source,
            conflicting_mark_text=conflicting_mark_text,
            conflicting_owner=conflicting_owner,
            conflicting_classes=list(conflicting_classes),
            similarity_mark=similarity_mark,
            similarity_goods=similarity_goods,
            similarity_channels=similarity_channels,
        ),
        headers or WATCH,
    )
    return get_success_data(res)


def triage_alert(alert_id: str) -> dict:
    """NEW -> TRIAGED. Returns the alert (carries the post-triage version)."""
    return get_success_data(api_client.triage_alert(alert_id, PARA))


def assess_alert(alert_id: str, expected_version, weight_mark=0.6, weight_goods=0.3,
                 weight_channels=0.1, fame_adjustment=5, rationale="strong",
                 user_id="assoc_1") -> dict:
    """Record an attorney assessment (OCC-guarded). Returns the alert."""
    res = api_client.assess_alert(
        alert_id,
        assess_payload(
            expected_version,
            weight_mark=weight_mark,
            weight_goods=weight_goods,
            weight_channels=weight_channels,
            fame_adjustment=fame_adjustment,
            rationale=rationale,
        ),
        make_associate_headers(user_id),
    )
    return get_success_data(res)


def get_alert(alert_id: str) -> dict:
    return get_success_data(api_client.get_watch_alert(alert_id, PARA))


def escalate_alert(alert_id: str, matter_type="INFRINGEMENT", user_id="assoc_1") -> dict:
    """UNDER_ASSESSMENT -> ESCALATED. Returns the created EnforcementMatter."""
    res = api_client.escalate_alert(alert_id, {"matter_type": matter_type},
                                    make_associate_headers(user_id))
    return get_success_data(res)


def setup_assessed_alert(budget=500000, classes=(9,),
                         similarity_mark=80, similarity_goods=70, similarity_channels=60,
                         weight_mark=0.6, weight_goods=0.3, weight_channels=0.1,
                         fame_adjustment=5, publication_date="2026-08-03T00:00:00Z"):
    """Client + PUBLISHED record + alert assessed once (UNDER_ASSESSMENT).

    Returns (client, record, alert)."""
    client, record = setup_published_record(budget=budget, classes=classes,
                                            publication_date=publication_date)
    alert = create_alert(record["id"], similarity_mark, similarity_goods,
                         similarity_channels, conflicting_classes=classes[:1])
    alert = triage_alert(alert["id"])
    alert = assess_alert(alert["id"], alert["version"], weight_mark, weight_goods,
                         weight_channels, fame_adjustment)
    return client, record, alert


def setup_escalated_matter(budget=500000, classes=(9,), matter_type="INFRINGEMENT",
                           publication_date="2026-08-03T00:00:00Z",
                           registration_date="2026-08-10T00:00:00Z"):
    """Client + record + alert ESCALATED into an ACTIVE matter.

    For OPPOSITION the record is left PUBLISHED (becomes UNDER_CHALLENGE);
    for CANCELLATION the record is REGISTERED first (becomes UNDER_CHALLENGE).
    Returns (client, record, alert, matter)."""
    if matter_type == "CANCELLATION":
        client, record = setup_registered_record(budget=budget, classes=classes,
                                                 registration_date=registration_date,
                                                 publication_date=publication_date)
    else:
        client, record = setup_published_record(budget=budget, classes=classes,
                                                publication_date=publication_date)
    alert = create_alert(record["id"], conflicting_classes=classes[:1])
    alert = triage_alert(alert["id"])
    alert = assess_alert(alert["id"], alert["version"])
    matter = escalate_alert(alert["id"], matter_type)
    return client, get_record(record["id"]), get_alert(alert["id"]), matter


def get_matter(matter_id: str) -> dict:
    return get_success_data(api_client.get_enforcement_matter(matter_id, PARA))


# ─── Deadlines ────────────────────────────────────────

def docket_deadline(matter_id: str, deadline_type="RESPONSE_DUE",
                    basis_date="2026-08-07T09:00:00Z", offset_days=5,
                    statutory_basis="37 CFR 2.196", user_id="para_1",
                    role="Paralegal", max_extensions=None) -> dict:
    payload = docket_deadline_payload(
        deadline_type=deadline_type, statutory_basis=statutory_basis,
        basis_date=basis_date, offset_days=offset_days,
    )
    if max_extensions is not None:
        payload["max_extensions"] = max_extensions
    headers = make_paralegal_headers(user_id) if role == "Paralegal" else make_associate_headers(user_id)
    res = api_client.docket_deadline(matter_id, payload, headers)
    return get_success_data(res)


def verify_deadline(deadline_id: str, user_id="assoc_2", role="AssociateAttorney") -> dict:
    headers = make_associate_headers(user_id) if role == "AssociateAttorney" else make_partner_headers(user_id)
    return get_success_data(api_client.verify_deadline(deadline_id, headers))


def satisfy_deadline(deadline_id: str, allow_late=None, user_id="para_1", role="Paralegal") -> dict:
    payload = {}
    if allow_late is not None:
        payload["allow_late"] = allow_late
    headers = make_paralegal_headers(user_id) if role == "Paralegal" else make_partner_headers(user_id)
    return get_success_data(api_client.satisfy_deadline(deadline_id, payload, headers))


def get_deadline(deadline_id: str) -> dict:
    return get_success_data(api_client.get_deadline(deadline_id, PARA))


# ─── Cease-and-desist letters ─────────────────────────

def draft_letter(matter_id: str, user_id="assoc_1", role="AssociateAttorney", **fields) -> dict:
    headers = make_associate_headers(user_id) if role == "AssociateAttorney" else make_partner_headers(user_id)
    res = api_client.draft_letter(matter_id, draft_letter_payload(**fields), headers)
    return get_success_data(res)


def submit_letter_review(letter_id: str, user_id="assoc_1", role="AssociateAttorney") -> dict:
    headers = make_associate_headers(user_id) if role == "AssociateAttorney" else make_partner_headers(user_id)
    return get_success_data(api_client.submit_letter_review(letter_id, headers))


def approve_letter(letter_id: str, approver_id="partner_1", decision="APPROVED") -> dict:
    return get_success_data(
        api_client.approve_letter(letter_id, {"decision": decision}, make_partner_headers(approver_id))
    )


def issue_letter(letter_id: str, user_id="assoc_1") -> dict:
    return get_success_data(api_client.issue_letter(letter_id, make_associate_headers(user_id)))


def setup_approved_letter(budget=500000, **letter_fields):
    """Escalated INFRINGEMENT matter + letter in APPROVED (drafted by assoc_1,
    approved by partner_1). Returns (client, record, alert, matter, letter)."""
    client, record, alert, matter = setup_escalated_matter(budget=budget)
    letter = draft_letter(matter["id"], user_id="assoc_1", **letter_fields)
    submit_letter_review(letter["id"], user_id="assoc_1")
    letter = approve_letter(letter["id"], approver_id="partner_1")
    return client, record, alert, matter, letter


def setup_issued_letter(budget=500000, **letter_fields):
    """Letter walked to ISSUED (auto-dockets the response deadline).
    Returns (client, record, alert, matter, letter)."""
    client, record, alert, matter, letter = setup_approved_letter(budget=budget, **letter_fields)
    letter = issue_letter(letter["id"], user_id="assoc_1")
    return client, record, alert, matter, letter


def get_letter(letter_id: str) -> dict:
    return get_success_data(api_client.get_letter(letter_id, PARA))


# ─── Takedown filings ─────────────────────────────────

def create_takedown(alert_id: str, platform="META", basis="COUNTERFEIT",
                    listing_url=None) -> dict:
    payload = takedown_payload(platform=platform, basis=basis)
    if listing_url is not None:
        payload["listing_url"] = listing_url
    res = api_client.create_takedown_filing(alert_id, payload, PARA)
    return get_success_data(res)


def file_takedown(filing_id: str) -> dict:
    return get_success_data(api_client.file_takedown(filing_id, PARA))


def platform_response(filing_id: str, outcome: str) -> dict:
    return get_success_data(api_client.record_platform_response(filing_id, {"outcome": outcome}, PARA))


def setup_counterfeit_alert(budget=1000000):
    """Client + PUBLISHED record + TRIAGED alert primed for counterfeit filings.
    Returns (client, record, alert)."""
    client, record = setup_published_record(budget=budget, classes=(9, 25))
    alert = create_alert(record["id"], similarity_mark=95, similarity_goods=92,
                         similarity_channels=80, source="MARKETPLACE_SWEEP",
                         conflicting_classes=(25,), conflicting_mark_text="ACME",
                         conflicting_owner="FakeShop")
    alert = triage_alert(alert["id"])
    return client, record, alert


def add_removed_counterfeit_filing(alert_id: str, n: int) -> dict:
    """Create -> file -> platform REMOVED one COUNTERFEIT filing. Returns it."""
    filing = create_takedown(alert_id, platform="META", basis="COUNTERFEIT",
                             listing_url=f"https://meta.example/shop/{n}")
    file_takedown(filing["id"])
    return platform_response(filing["id"], "REMOVED")


def setup_alert_with_confirmed_counterfeits(removed_count: int, budget=1000000):
    """TRIAGED alert with `removed_count` COUNTERFEIT filings already REMOVED.
    Returns (client, record, alert, filing_ids)."""
    client, record, alert = setup_counterfeit_alert(budget=budget)
    filing_ids = []
    for i in range(removed_count):
        filing = add_removed_counterfeit_filing(alert["id"], i + 1)
        filing_ids.append(filing["id"])
    return client, record, get_alert(alert["id"]), filing_ids


# ─── Coexistence agreements ───────────────────────────

def create_agreement(record_id: str, user_id="assoc_1", **overrides) -> dict:
    res = api_client.create_coexistence_agreement(
        record_id, agreement_payload(**overrides), make_associate_headers(user_id)
    )
    return get_success_data(res)


def propose_agreement(agreement_id: str, expected_version, terms_text="terms",
                      user_id="assoc_1") -> dict:
    res = api_client.propose_agreement(
        agreement_id,
        propose_payload(expected_version, terms_text=terms_text),
        make_associate_headers(user_id),
    )
    return get_success_data(res)


def counter_agreement(agreement_id: str, counter_terms_text="counter", user_id="assoc_1") -> dict:
    res = api_client.counter_agreement(
        agreement_id, {"counter_terms_text": counter_terms_text}, make_associate_headers(user_id)
    )
    return get_success_data(res)


def execute_agreement(agreement_id: str, user_id="partner_1") -> dict:
    return get_success_data(api_client.execute_agreement(agreement_id, make_partner_headers(user_id)))


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_coexistence_agreement(agreement_id, PARA))


def setup_executed_agreement(budget=500000, territory_codes=("US",),
                             effective_start="2026-08-01T00:00:00Z",
                             effective_end="2027-08-01T00:00:00Z",
                             enforcement_matter_id=None):
    """Client + PUBLISHED record + agreement walked DRAFT -> PROPOSED -> EXECUTED.
    Returns (client, record, agreement)."""
    client, record = setup_published_record(budget=budget)
    overrides = {"territory_codes": list(territory_codes),
                 "effective_start": effective_start, "effective_end": effective_end}
    if enforcement_matter_id is not None:
        overrides["enforcement_matter_id"] = enforcement_matter_id
    agreement = create_agreement(record["id"], **overrides)
    propose_agreement(agreement["id"], agreement["version"], terms_text="terms")
    agreement = execute_agreement(agreement["id"])
    return client, record, agreement


# ─── Evidence and maintenance ─────────────────────────

def collect_evidence(record_id: str, nice_class=9, specimen_type="LABEL",
                     specimen_date="2031-06-01T00:00:00Z", user_id="para_1",
                     role="Paralegal") -> dict:
    headers = make_paralegal_headers(user_id) if role == "Paralegal" else make_associate_headers(user_id)
    res = api_client.collect_evidence(
        record_id,
        evidence_payload(nice_class=nice_class, specimen_type=specimen_type,
                         specimen_date=specimen_date),
        headers,
    )
    return get_success_data(res)


def verify_evidence(item_id: str, user_id="assoc_1", role="AssociateAttorney") -> dict:
    headers = make_associate_headers(user_id) if role == "AssociateAttorney" else make_partner_headers(user_id)
    return get_success_data(api_client.verify_evidence(item_id, headers))


def create_maintenance_filing(record_id: str, evidence_item_ids, filing_type="SECTION_8") -> dict:
    res = api_client.create_maintenance_filing(
        record_id,
        maintenance_filing_payload(filing_type=filing_type, evidence_item_ids=list(evidence_item_ids)),
        PARA,
    )
    return get_success_data(res)


def get_maintenance_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_maintenance_filing(filing_id, PARA))


def setup_record_with_verified_evidence(classes=(9,), specimen_date="2031-06-01T00:00:00Z",
                                        registration_date="2026-08-10T00:00:00Z",
                                        budget=500000):
    """REGISTERED record with one VERIFIED evidence item per class.
    Returns (client, record, evidence_ids)."""
    client, record = setup_registered_record(budget=budget, classes=classes,
                                             registration_date=registration_date)
    evidence_ids = []
    for cls in classes:
        item = collect_evidence(record["id"], nice_class=cls, specimen_date=specimen_date,
                                user_id="para_1")
        verify_evidence(item["id"], user_id="assoc_1")
        evidence_ids.append(item["id"])
    return client, get_record(record["id"]), evidence_ids


# ─── Clearance / customs / referrals ──────────────────

def create_clearance_search(client_id: str, as_owner=True, **overrides) -> dict:
    headers = make_client_contact_headers(client_id) if as_owner else PARA
    res = api_client.create_clearance_search(
        clearance_search_payload(client_id, **overrides), headers
    )
    return get_success_data(res)


def create_recordation(record_id: str, **overrides) -> dict:
    res = api_client.create_customs_recordation(record_id, recordation_payload(**overrides), PARA)
    return get_success_data(res)


def create_referral(alert_id: str, user_id="assoc_1", **overrides) -> dict:
    res = api_client.create_counterfeit_referral(
        alert_id, referral_payload(**overrides), make_associate_headers(user_id)
    )
    return get_success_data(res)
