"""Composite setup helpers.

These encapsulate the multi-step preambles that most WIC test claims require:
the application lifecycle (create -> determine-income -> assess-risk -> approve),
the certification cascade (Certification ACTIVE + Participant ACTIVE + EbtAccount
OPEN), and the food-prescription / redemption draw-down chain. Every helper uses
get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error.

Identity threading: EligibilityClerk and CPA are opaque, so their headers are
parameterized by an arbitrary operator id. Participant is entity-backed, so
redemption helpers build the participant's headers from the real participant id.
The approve step deliberately uses a CPA id distinct from the determine-income
clerk id so segregation of duties passes.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_clerk_headers, make_cpa_headers, make_participant_headers

CLERK = make_clerk_headers("clerk-1")
CPA = make_cpa_headers("cpa-1")


# ---------------------------------------------------------------------------
# Tier 1: primitives
# ---------------------------------------------------------------------------
def create_agency(caseload_cap=50, name="Setup Agency", state_code="CA"):
    """Create an agency. Clock defaults to epoch."""
    resp = api_client.create_agency(
        {"name": name, "state_code": state_code, "caseload_cap": caseload_cap}, CLERK
    )
    return get_success_data(resp)


def set_clock(agency_id, to_iso8601):
    """Advance an agency's deterministic clock."""
    resp = api_client.set_current_utc(agency_id, to_iso8601, CLERK)
    return get_success_data(resp)


def create_household(agency_id, household_size=3, pregnancy_count=0, adjunctive_program="SNAP"):
    resp = api_client.create_household(
        {
            "agency_id": agency_id,
            "household_size": household_size,
            "pregnancy_count": pregnancy_count,
            "adjunctive_program": adjunctive_program,
        },
        CLERK,
    )
    return get_success_data(resp)


def create_participant(household_id, full_name="Setup Person", ssn_last4="0001",
                       category="CHILD", **overrides):
    payload = {
        "household_id": household_id,
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "category": category,
    }
    payload.update(overrides)
    resp = api_client.create_participant(payload, CLERK)
    return get_success_data(resp)


def create_authorized_vendor(agency_id, legal_name="Setup Grocer", peer_group="MEDIUM"):
    """Register a vendor and walk it PENDING -> AUTHORIZED."""
    vendor = get_success_data(api_client.create_vendor(
        {"agency_id": agency_id, "legal_name": legal_name, "peer_group": peer_group}, CLERK
    ))
    get_success_data(api_client.authorize_vendor(vendor["id"], CLERK))
    return get_success_data(api_client.get_vendor(vendor["id"], CLERK))


def create_clinic(agency_id, name="Setup Clinic", appointment_buffer_minutes=0):
    resp = api_client.create_clinic(
        {
            "agency_id": agency_id,
            "name": name,
            "appointment_buffer_minutes": appointment_buffer_minutes,
        },
        CLERK,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: application lifecycle helpers
# ---------------------------------------------------------------------------
def create_draft_application(participant_id, income_method=None):
    """Open a DRAFT application for a participant."""
    payload = {"participant_id": participant_id}
    if income_method is not None:
        payload["income_method"] = income_method
    return get_success_data(api_client.create_application(payload, CLERK))


def add_income_record(application_id, gross_amount_cents, pay_frequency="MONTHLY"):
    return get_success_data(api_client.create_income_record(
        {
            "application_id": application_id,
            "gross_amount_cents": gross_amount_cents,
            "pay_frequency": pay_frequency,
        },
        CLERK,
    ))


def create_application_with_income(participant_id, income_records, income_method=None):
    """Create a DRAFT application and attach a list of income records.

    income_records: list of (gross_amount_cents, pay_frequency) tuples, created
    in order so sequence_index follows the list order.
    """
    app = create_draft_application(participant_id, income_method=income_method)
    for gross, freq in income_records:
        add_income_record(app["id"], gross, freq)
    return app


def determine_income(application_id, clerk_id="clerk-1"):
    """Run income determination (DRAFT -> INCOME_DETERMINED). The acting clerk id
    is stamped as determined_by_user_id."""
    return get_success_data(
        api_client.determine_income(application_id, make_clerk_headers(clerk_id))
    )


def assess_risk(application_id, risk_factor_codes, cpa_id="cpa-1"):
    """Record the risk assessment (INCOME_DETERMINED -> RISK_ASSESSED)."""
    return get_success_data(
        api_client.assess_risk(application_id, risk_factor_codes, make_cpa_headers(cpa_id))
    )


def setup_risk_assessed_application(
    agency_id=None,
    caseload_cap=50,
    category="CHILD",
    adjunctive_program="SNAP",
    household_size=3,
    pregnancy_count=0,
    income_records=(("gross", 100000, "MONTHLY"),),
    income_method=None,
    risk_factor_codes=("ANEMIA",),
    full_name="Risk Person",
    ssn_last4="0001",
    clerk_id="clerk-1",
    cpa_id="cpa-1",
    clock_iso=None,
):
    """Build a complete agency/household/participant/application chain advanced to
    RISK_ASSESSED. Returns dict with agency, household, participant, application,
    plus an income_determined snapshot and risk_assessed snapshot.

    income_records may be a tuple of (label, gross_cents, freq) or (gross, freq).
    """
    if agency_id is None:
        agency = create_agency(caseload_cap=caseload_cap)
        agency_id = agency["id"]
    else:
        agency = get_success_data(api_client.get_agency(agency_id, CLERK))
    if clock_iso is not None:
        agency = set_clock(agency_id, clock_iso)

    household = create_household(
        agency_id, household_size=household_size,
        pregnancy_count=pregnancy_count, adjunctive_program=adjunctive_program,
    )
    participant = create_participant(
        household["id"], full_name=full_name, ssn_last4=ssn_last4, category=category,
    )
    application = create_draft_application(participant["id"], income_method=income_method)
    for rec in income_records:
        if len(rec) == 3:
            _, gross, freq = rec
        else:
            gross, freq = rec
        add_income_record(application["id"], gross, freq)
    income_determined = determine_income(application["id"], clerk_id=clerk_id)
    risk_assessed = assess_risk(
        application["id"], list(risk_factor_codes), cpa_id=cpa_id
    )
    return {
        "agency": agency,
        "agency_id": agency_id,
        "household": household,
        "participant": participant,
        "application": application,
        "income_determined": income_determined,
        "risk_assessed": risk_assessed,
    }


# ---------------------------------------------------------------------------
# Tier 3: certification cascade — approve through to ACTIVE cert + EBT
# ---------------------------------------------------------------------------
def setup_certified_participant(
    caseload_cap=50,
    category="PREGNANT",
    adjunctive_program="MEDICAID",
    household_size=2,
    pregnancy_count=1,
    risk_factor_codes=("GEST_DIABETES",),
    income_records=(("gross", 150000, "MONTHLY"),),
    income_method=None,
    full_name="Cert Person",
    ssn_last4="0001",
    clerk_id="clerk-1",
    cpa_id="cpa-1",
    clock_iso=None,
    agency_id=None,
):
    """Walk the full chain to an ACTIVE certification: approve cascade creates the
    Certification (ACTIVE), flips Participant to ACTIVE, debits the caseload, and
    opens the EbtAccount. Returns a dict with agency, household, participant,
    application, certification, ebt_account (each a freshly fetched snapshot).
    """
    ctx = setup_risk_assessed_application(
        agency_id=agency_id,
        caseload_cap=caseload_cap,
        category=category,
        adjunctive_program=adjunctive_program,
        household_size=household_size,
        pregnancy_count=pregnancy_count,
        income_records=income_records,
        income_method=income_method,
        risk_factor_codes=risk_factor_codes,
        full_name=full_name,
        ssn_last4=ssn_last4,
        clerk_id=clerk_id,
        cpa_id=cpa_id,
        clock_iso=clock_iso,
    )
    app_id = ctx["application"]["id"]
    p_id = ctx["participant"]["id"]
    get_success_data(api_client.approve_application(app_id, make_cpa_headers(cpa_id)))

    certs = get_success_data(
        api_client.list_certifications(CPA, params={"participant_id": p_id})
    )
    cert = certs[0] if certs else None
    participant = get_success_data(api_client.get_participant(p_id, CPA))
    ebts = get_success_data(
        api_client.list_ebt_accounts(CPA, params={"participant_id": p_id})
    )
    ebt = ebts[0] if ebts else None
    ctx.update({
        "certification": cert,
        "participant": participant,
        "ebt_account": ebt,
    })
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: food prescription issuance + EBT
# ---------------------------------------------------------------------------
def get_participant_version(participant_id):
    p = get_success_data(api_client.get_participant(participant_id, CPA))
    return p["version"]


def issue_food_prescription(certification_id, participant_id, line_items,
                            issuance_mode="FULL", cpa_id="cpa-1",
                            expected_participant_version=None):
    """Issue a food package, supplying the current participant version for OCC
    unless a specific (e.g. deliberately stale) version is passed."""
    if expected_participant_version is None:
        expected_participant_version = get_participant_version(participant_id)
    payload = {
        "certification_id": certification_id,
        "issuance_mode": issuance_mode,
        "line_items": line_items,
        "expected_participant_version": expected_participant_version,
    }
    return get_success_data(
        api_client.create_food_prescription(payload, make_cpa_headers(cpa_id))
    )


def setup_certified_with_prescription(
    line_items=None,
    issuance_mode="FULL",
    category="PREGNANT",
    clock_iso="2026-03-02T00:00:00.000Z",
    with_vendor=False,
    **cert_kwargs,
):
    """Certified participant plus one issued FoodPrescription (and optionally an
    AUTHORIZED vendor). Returns the setup_certified_participant context extended
    with prescription, ebt_account (refetched), and vendor when requested.
    """
    if line_items is None:
        line_items = [
            {"food_category": "MILK", "requested_units": 6},
            {"food_category": "EGGS", "requested_units": 2},
            {"food_category": "JUICE", "requested_units": 3},
        ]
    ctx = setup_certified_participant(category=category, clock_iso=clock_iso, **cert_kwargs)
    cert_id = ctx["certification"]["id"]
    p_id = ctx["participant"]["id"]
    rx = issue_food_prescription(cert_id, p_id, line_items, issuance_mode=issuance_mode)
    ebts = get_success_data(
        api_client.list_ebt_accounts(CPA, params={"participant_id": p_id})
    )
    ctx["prescription"] = rx
    ctx["ebt_account"] = ebts[0] if ebts else None
    if with_vendor:
        ctx["vendor"] = create_authorized_vendor(ctx["agency_id"])
    return ctx


def redeem(ebt_account_id, vendor_id, food_category, units, participant_id):
    """Record a redemption as the owning Participant (entity-backed identity)."""
    payload = {
        "ebt_account_id": ebt_account_id,
        "vendor_id": vendor_id,
        "food_category": food_category,
        "units": units,
    }
    return get_success_data(
        api_client.create_redemption(payload, make_participant_headers(participant_id))
    )


def setup_certified_with_prescription_and_redemption(
    line_items=None,
    redeem_category="MILK",
    redeem_units=4,
    category="PREGNANT",
    clock_iso="2026-03-02T00:00:00.000Z",
    **cert_kwargs,
):
    """Certified participant, one FULL prescription, an AUTHORIZED vendor, and a
    redemption drawing down `redeem_units` of `redeem_category`. Returns the
    extended context including vendor, prescription, ebt_account (refetched),
    and redemption.
    """
    ctx = setup_certified_with_prescription(
        line_items=line_items, category=category, clock_iso=clock_iso,
        with_vendor=True, **cert_kwargs,
    )
    p_id = ctx["participant"]["id"]
    redemption = redeem(
        ctx["ebt_account"]["id"], ctx["vendor"]["id"],
        redeem_category, redeem_units, p_id,
    )
    ebts = get_success_data(
        api_client.list_ebt_accounts(CPA, params={"participant_id": p_id})
    )
    ctx["redemption"] = redemption
    ctx["ebt_account"] = ebts[0] if ebts else None
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: vendor lifecycle, clinic & peer-session helpers
# ---------------------------------------------------------------------------
def setup_suspended_vendor(agency_id=None, points=100, peer_group="LARGE"):
    """Vendor authorized then driven to SUSPENDED via violation points."""
    if agency_id is None:
        agency_id = create_agency()["id"]
    vendor = get_success_data(api_client.create_vendor(
        {"agency_id": agency_id, "legal_name": "Susp Grocer", "peer_group": peer_group}, CLERK
    ))
    get_success_data(api_client.authorize_vendor(vendor["id"], CLERK))
    get_success_data(api_client.record_vendor_violation(vendor["id"], points, CLERK))
    return {
        "agency_id": agency_id,
        "vendor": get_success_data(api_client.get_vendor(vendor["id"], CLERK)),
    }


def setup_clinic_with_appointment(
    agency_id=None,
    clock_iso="2026-03-02T00:00:00.000Z",
    start_utc="2026-03-10T10:00:00.000Z",
    end_utc="2026-03-10T10:30:00.000Z",
    purpose="INITIAL_CERT",
    buffer_minutes=0,
    category="CHILD",
):
    """A clinic with one SCHEDULED appointment for a fresh APPLICANT participant.
    Returns agency_id, clinic, participant, appointment, and the post-schedule
    clinic version (clinic_version_after).
    """
    if agency_id is None:
        agency = create_agency()
        agency_id = agency["id"]
    if clock_iso is not None:
        set_clock(agency_id, clock_iso)
    clinic = create_clinic(agency_id, appointment_buffer_minutes=buffer_minutes)
    household = create_household(agency_id, household_size=3, adjunctive_program="SNAP")
    participant = create_participant(household["id"], category=category, ssn_last4="0010")
    clinic_v = get_success_data(api_client.get_clinic(clinic["id"], CLERK))["version"]
    appt = get_success_data(api_client.create_clinic_appointment(
        {
            "clinic_id": clinic["id"],
            "participant_id": participant["id"],
            "purpose": purpose,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "expected_clinic_version": clinic_v,
        },
        CLERK,
    ))
    clinic_after = get_success_data(api_client.get_clinic(clinic["id"], CLERK))
    return {
        "agency_id": agency_id,
        "clinic": clinic_after,
        "participant": participant,
        "appointment": appt,
        "clinic_version_pre": clinic_v,
        "clinic_version_after": clinic_after["version"],
    }


def setup_peer_session(
    agency_id=None,
    counselor_id="pc-1",
    start_utc="2026-03-10T10:00:00.000Z",
    end_utc="2026-03-10T10:30:00.000Z",
):
    """A single SCHEDULED peer-support session for a BREASTFEEDING participant.
    Returns agency_id, participant, session.
    """
    if agency_id is None:
        agency_id = create_agency()["id"]
    household = create_household(agency_id, household_size=2, adjunctive_program="SNAP")
    participant = create_participant(
        household["id"], category="BREASTFEEDING", ssn_last4="0020",
        breastfeeding_opt_in=True,
    )
    session = get_success_data(api_client.create_peer_session(
        {
            "participant_id": participant["id"],
            "peer_counselor_id": counselor_id,
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
        CPA,
    ))
    return {"agency_id": agency_id, "participant": participant, "session": session}
