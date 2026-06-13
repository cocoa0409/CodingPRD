"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so a broken setup step raises a clear
"Setup step failed" error rather than a confusing downstream assertion failure.

The test harness restarts the server and empties the database before every test, so
every fixture builds its preconditions from scratch using only PRD-declared endpoints.
The system clock is also reset; fixtures that depend on elapsed-day position set the
clock explicitly with api_client.set_clock().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_provider_payload,
    create_physician_payload,
    create_election_payload,
    create_certification_payload,
    create_care_plan_payload,
    create_care_day_payload,
    create_coverage_item_payload,
    create_bereavement_case_payload,
    CORE_IDG,
)
from .test_users import TEST_USERS, make_physician_headers

BILLING = TEST_USERS["billing_headers"]
INTAKE = TEST_USERS["intake_headers"]
CLINICAL = TEST_USERS["clinical_headers"]


# ─── Primitives ───────────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the server's logical UTC clock; available to BillingAdmin."""
    get_success_data(api_client.set_clock(iso, BILLING))


def create_provider(per_beneficiary_cap_cents=3490000, cap_year_start="2026-01-01T00:00:00Z",
                    name="Setup Hospice"):
    """Register a provider. Returns the Provider entity."""
    res = api_client.create_provider(
        create_provider_payload(name=name, cap_year_start=cap_year_start,
                                per_beneficiary_cap_cents=per_beneficiary_cap_cents),
        BILLING,
    )
    return get_success_data(res)


def create_medical_director(full_name="Dr Director"):
    """Register a medical-director Physician (sole certifier for an initial cert).
    Returns the Physician entity."""
    res = api_client.create_physician(
        create_physician_payload(full_name=full_name, is_medical_director=True), CLINICAL)
    return get_success_data(res)


def create_plain_physician(full_name="Dr Plain"):
    """Register a non-medical-director Physician. Returns the Physician entity."""
    res = api_client.create_physician(
        create_physician_payload(full_name=full_name, is_medical_director=False), CLINICAL)
    return get_success_data(res)


def create_election(provider_id, election_date="2026-01-01T00:00:00Z", patient_name="Setup Pt",
                    attending_physician_id="ext-att-setup"):
    """Elect the benefit. Returns the Election entity (status ELECTED, version 1)."""
    res = api_client.create_election(
        create_election_payload(provider_id, patient_name=patient_name,
                                election_date=election_date,
                                attending_physician_id=attending_physician_id),
        INTAKE,
    )
    return get_success_data(res)


# ─── Tier 2: Provider + election scaffolds ────────────────────────────

def setup_provider_and_election(per_beneficiary_cap_cents=3490000,
                                cap_year_start="2026-01-01T00:00:00Z",
                                election_date="2026-01-01T00:00:00Z",
                                clock=None, patient_name="Setup Pt",
                                attending_physician_id="ext-att-setup"):
    """Provider + clock + one ELECTED election.

    Returns (provider, election). The clock is set to `clock` (defaults to election_date)
    BEFORE the election is created so elapsed-day cursors are deterministic.
    """
    provider = create_provider(per_beneficiary_cap_cents=per_beneficiary_cap_cents,
                               cap_year_start=cap_year_start)
    set_clock(clock or election_date)
    election = create_election(provider["id"], election_date=election_date,
                               patient_name=patient_name,
                               attending_physician_id=attending_physician_id)
    return provider, election


# ─── Tier 3: care-day accumulation ────────────────────────────────────

def post_care_day(election_id, service_date, level_of_care, high_intensity=False):
    """Post one CareDay. Returns the CareDay entity."""
    res = api_client.create_care_day(
        create_care_day_payload(election_id, service_date, level_of_care, high_intensity),
        CLINICAL,
    )
    return get_success_data(res)


def post_gip_days(election_id, service_dates):
    """Post a GIP CareDay for each date in `service_dates`. Returns list of CareDays."""
    return [post_care_day(election_id, d, "GIP", high_intensity=False) for d in service_dates]


def post_respite_run(election_id, service_dates):
    """Post a RESPITE CareDay for each date. Returns list of CareDays."""
    return [post_care_day(election_id, d, "RESPITE", high_intensity=False) for d in service_dates]


def setup_provider_with_two_beneficiaries(per_beneficiary_cap_cents=200000):
    """Provider with election E1 (3 GIP days = 330000) and election E2 (1 GIP day = 110000),
    both in the 2026 cap window. Returns (provider, e1, e2).

    Reproduces the cap-allowance order scenario: counted_beneficiaries 2,
    total_paid 440000, provisional liability 40000.
    """
    provider = create_provider(per_beneficiary_cap_cents=per_beneficiary_cap_cents,
                               cap_year_start="2026-01-01T00:00:00Z")
    set_clock("2026-01-02T00:00:00Z")
    e1 = create_election(provider["id"], election_date="2026-01-02T00:00:00Z",
                         patient_name="Ben One", attending_physician_id="ext-att-b1")
    post_gip_days(e1["id"], ["2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z"])
    e2 = create_election(provider["id"], election_date="2026-01-02T00:00:00Z",
                         patient_name="Ben Two", attending_physician_id="ext-att-b2")
    post_gip_days(e2["id"], ["2026-01-02T00:00:00Z"])
    return provider, e1, e2


def setup_provider_one_beneficiary_330000(per_beneficiary_cap_cents=200000):
    """Provider with one election having 3 GIP days (330000) in window. Returns (provider, election)."""
    provider = create_provider(per_beneficiary_cap_cents=per_beneficiary_cap_cents,
                               cap_year_start="2026-01-01T00:00:00Z")
    set_clock("2026-01-02T00:00:00Z")
    election = create_election(provider["id"], election_date="2026-01-02T00:00:00Z",
                               patient_name="Ben One", attending_physician_id="ext-att-c1b")
    post_gip_days(election["id"],
                  ["2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z"])
    return provider, election


# ─── Tier 3: certification / period progression ───────────────────────

def get_election(election_id, headers=CLINICAL):
    """Read back an election (recomputes derived fields). Returns the Election entity."""
    return get_success_data(api_client.get_election(election_id, headers))


def commit_certification(election_id, period_sequence, physician_id, expected_election_version,
                         narrative_present=True, face_to_face_physician_id=None,
                         face_to_face_date=None):
    """Commit a certification as the named physician. Returns the raw Response so callers
    can branch on success/failure. Uses make_physician_headers so X-User-ID is the
    acting physician entity id (entity-backed role)."""
    overrides = {
        "period_sequence": period_sequence,
        "narrative_present": narrative_present,
    }
    if face_to_face_physician_id is not None:
        overrides["face_to_face_physician_id"] = face_to_face_physician_id
    if face_to_face_date is not None:
        overrides["face_to_face_date"] = face_to_face_date
    payload = create_certification_payload(
        election_id, physician_id, expected_election_version, **overrides)
    return api_client.create_certification(payload, make_physician_headers(physician_id))


def setup_election_with_md_period1_pending(per_beneficiary_cap_cents=3490000,
                                           election_date="2026-01-01T00:00:00Z"):
    """Provider + clock + election (period 1 PENDING_CERT) + a medical-director physician.
    Returns (provider, election, md_physician)."""
    provider = create_provider(per_beneficiary_cap_cents=per_beneficiary_cap_cents)
    md = create_medical_director()
    set_clock(election_date)
    election = create_election(provider["id"], election_date=election_date,
                               patient_name="Cert Pt", attending_physician_id="ext-att-cert")
    return provider, election, md


def setup_election_period1_certified(election_date="2026-01-01T00:00:00Z"):
    """Election with period 1 CERTIFIED (period 2 materialized, PENDING_CERT).
    Returns (provider, election_after, md_physician, e_ver_after) where e_ver_after is
    the election version observed after the period-1 commit."""
    provider, election, md = setup_election_with_md_period1_pending(election_date=election_date)
    res = commit_certification(election["id"], 1, md["id"], election["version"])
    get_success_data(res)
    after = get_election(election["id"])
    return provider, after, md, after["version"]


# ─── Tier 3: care plans (revise loop / supersede) ─────────────────────

def create_care_plan(election_id, expected_election_version, supersedes_plan_id=None,
                     idg_members=None):
    """Create / revise a CarePlan. Returns the CarePlan entity."""
    overrides = {}
    if supersedes_plan_id is not None:
        overrides["supersedes_plan_id"] = supersedes_plan_id
    if idg_members is not None:
        overrides["idg_members"] = idg_members
    res = api_client.create_care_plan(
        create_care_plan_payload(election_id, expected_election_version, **overrides), CLINICAL)
    return get_success_data(res)


def setup_election_with_active_plan(election_date="2026-01-01T00:00:00Z"):
    """Election with one ACTIVE CarePlan (revision 1). Returns (provider, election, plan1).

    Note: creating the plan bumped the election's version; the returned election is the
    original (version 1) snapshot. Use get_election() to observe the advanced version.
    """
    provider, election = setup_provider_and_election(election_date=election_date,
                                                     patient_name="Plan Pt",
                                                     attending_physician_id="ext-att-plan")
    plan1 = create_care_plan(election["id"], election["version"])
    return provider, election, plan1


def setup_election_with_superseded_plan(election_date="2026-01-01T00:00:00Z"):
    """Election where CarePlan revision 1 has been SUPERSEDED by revision 2 (ACTIVE).
    Returns (provider, election, plan1, plan2)."""
    provider, election, plan1 = setup_election_with_active_plan(election_date=election_date)
    e_after = get_election(election["id"])
    plan2 = create_care_plan(election["id"], e_after["version"], supersedes_plan_id=plan1["id"])
    return provider, election, plan1, plan2


# ─── Tier 5: terminal-state elections / bereavement ───────────────────

def revoke_election(election_id, revocation_date):
    """Revoke an election. Returns the Election entity."""
    return get_success_data(
        api_client.revoke_election(election_id, {"revocation_date": revocation_date}, INTAKE))


def discharge_election(election_id, discharge_date, discharge_reason="DEATH"):
    """Discharge an election. Returns the Election entity."""
    return get_success_data(api_client.discharge_election(
        election_id, {"discharge_date": discharge_date, "discharge_reason": discharge_reason},
        CLINICAL))


def setup_revoked_election(election_date="2026-01-01T00:00:00Z",
                           revocation_date="2026-01-10T00:00:00Z"):
    """Election that has been REVOKED (not death). Returns (provider, election)."""
    provider, election = setup_provider_and_election(election_date=election_date,
                                                     patient_name="Rev Pt",
                                                     attending_physician_id="ext-att-rev")
    revoke_election(election["id"], revocation_date)
    return provider, election


def setup_death_discharged_election(election_date="2026-01-01T00:00:00Z",
                                    discharge_date="2026-01-05T00:00:00Z"):
    """Election DISCHARGED by DEATH (bereavement_required true). Returns (provider, election)."""
    provider, election = setup_provider_and_election(election_date=election_date,
                                                     clock=election_date,
                                                     patient_name="Death Pt",
                                                     attending_physician_id="ext-att-death")
    set_clock(discharge_date)
    discharge_election(election["id"], discharge_date, "DEATH")
    return provider, election


def open_bereavement_case(election_id, enrolled_date):
    """Open a bereavement case. Returns the BereavementCase entity."""
    return get_success_data(api_client.create_bereavement_case(
        create_bereavement_case_payload(election_id, enrolled_date), CLINICAL))


def setup_open_bereavement_case(election_date="2026-01-01T00:00:00Z",
                                discharge_date="2026-01-05T00:00:00Z",
                                enrolled_date="2026-01-06T00:00:00Z"):
    """Death-discharged election with an OPEN bereavement case.
    Returns (provider, election, bereavement_case)."""
    provider, election = setup_death_discharged_election(election_date=election_date,
                                                         discharge_date=discharge_date)
    bc = open_bereavement_case(election["id"], enrolled_date)
    return provider, election, bc


# ─── Tier 4: respite-run boundary targeting ───────────────────────────

def setup_respite_run_of_5(election_date="2026-01-01T00:00:00Z", clock="2026-01-10T00:00:00Z"):
    """Election with 5 consecutive RESPITE days (Jan 1-5) already posted (run reaches 5).
    Returns (provider, election, day5) where day5 is the 5th RESPITE CareDay."""
    provider, election = setup_provider_and_election(election_date=election_date,
                                                     clock=election_date,
                                                     patient_name="Respite Pt",
                                                     attending_physician_id="ext-att-respite")
    set_clock(clock)
    days = post_respite_run(election["id"], [
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z",
        "2026-01-04T00:00:00Z", "2026-01-05T00:00:00Z",
    ])
    return provider, election, days[-1]


# ─── Tier 5: settled provider ─────────────────────────────────────────

def setup_settled_provider(per_beneficiary_cap_cents=3490000):
    """Provider settled for the 2026 cap year after one election received a GIP day.
    Returns (provider_after_settle, election)."""
    provider = create_provider(per_beneficiary_cap_cents=per_beneficiary_cap_cents)
    set_clock("2026-01-02T00:00:00Z")
    election = create_election(provider["id"], election_date="2026-01-02T00:00:00Z",
                               patient_name="Lock Pt", attending_physician_id="ext-att-lock")
    post_care_day(election["id"], "2026-01-02T00:00:00Z", "GIP", high_intensity=False)
    set_clock("2026-01-10T00:00:00Z")
    settled = get_success_data(api_client.settle_cap(provider["id"], BILLING))
    return settled, election
