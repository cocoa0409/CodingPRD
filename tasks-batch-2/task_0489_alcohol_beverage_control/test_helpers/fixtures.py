"""Composite setup helpers for multi-step test prerequisites (PRD section 3).

Every test runs against a freshly restarted, empty server (the runner restarts
the API via start.sh before each test), so each fixture builds all of its own
state from PRD-declared endpoints. Setup calls use get_success_data() (lenient)
so a setup break surfaces as a clear "Setup step failed".

Identity threading: Applicant is entity_backed. Every ownership-gated call
(submit, pay-fee, withdraw, server-permits, activate, renew, pay-fine, contest,
compliance-reports, transfer-requests) passes make_applicant_headers(applicant_id)
with the real Applicant.id, never the shared constant.

The canonical pipeline that takes an application from DRAFT to an ISSUED License
spans ~16 calls; it is encapsulated here once and reused everywhere.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_license_class_payload,
    create_quota_region_payload,
    create_applicant_payload,
    create_premise_payload,
    create_application_payload,
    create_protest_payload,
    create_server_permit_payload,
    create_violation_payload,
)
from .test_users import (
    TEST_USERS,
    make_director_headers,
    make_examiner_headers,
    make_zoning_officer_headers,
    make_adjudication_officer_headers,
    make_investigator_headers,
    make_applicant_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
EXAMINER = TEST_USERS["examiner_headers"]
ZONING = TEST_USERS["zoning_officer_headers"]
ADJUDICATOR = TEST_USERS["adjudication_officer_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
ANON = TEST_USERS["anonymous_headers"]

CLOCK_START = "2026-01-01T00:00:00Z"
# After the 30-day protest window from a 2026-01-01 submit (ends 2026-01-31).
CLOCK_AFTER_PROTEST = "2026-02-01T00:00:00Z"


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(to_iso8601, headers=None):
    return get_success_data(api_client.set_clock(to_iso8601, headers or DIRECTOR))


# ─── Atomic reference-data builders ───────────────────────────────────────
def make_license_class(**overrides) -> dict:
    return get_success_data(
        api_client.create_license_class(create_license_class_payload(**overrides), DIRECTOR)
    )


def make_quota_region(**overrides) -> dict:
    return get_success_data(
        api_client.create_quota_region(create_quota_region_payload(**overrides), DIRECTOR)
    )


def make_applicant(**overrides) -> dict:
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(**overrides), DIRECTOR)
    )


def make_premise(applicant_id, **overrides) -> dict:
    payload = create_premise_payload(applicant_id=applicant_id, **overrides)
    return get_success_data(
        api_client.create_premise(payload, make_applicant_headers(applicant_id))
    )


def make_draft_application(applicant_id, premise_id, **overrides) -> dict:
    payload = create_application_payload(
        applicant_id=applicant_id, premise_id=premise_id, **overrides
    )
    return get_success_data(
        api_client.create_application(payload, make_applicant_headers(applicant_id))
    )


# ─── Tier 2: reference configuration ──────────────────────────────────────
def setup_reference_data(class_overrides=None, region_overrides=None, applicant_overrides=None):
    """Set clock to the start instant, then create the canonical ON_47 class, a
    quota region, an applicant, and a premise owned by that applicant.

    Returns a dict with keys: cls, region, applicant, premise, owner_id, region_version.
    """
    set_clock(CLOCK_START)
    cls = make_license_class(**(class_overrides or {}))
    region = make_quota_region(**(region_overrides or {}))
    applicant = make_applicant(**(applicant_overrides or {}))
    premise = make_premise(
        applicant["id"],
        region_code=region["region_code"],
        **({} if not region_overrides else {}),
    )
    return {
        "cls": cls,
        "region": region,
        "applicant": applicant,
        "premise": premise,
        "owner_id": applicant["id"],
        "region_version": region["version"],
    }


# ─── Tier 1/3: application state-progression shortcuts ─────────────────────
def create_submitted_application(
    ref=None,
    expected_region_version=None,
    submit_payload=None,
    class_overrides=None,
    region_overrides=None,
    applicant_overrides=None,
):
    """Create + submit an application. Returns (ref, app).

    `ref` is the reference-data dict from setup_reference_data (created here if
    None). For quota_managed classes the submit carries expected_region_version
    (defaults to the region's current version).
    """
    if ref is None:
        ref = setup_reference_data(
            class_overrides=class_overrides,
            region_overrides=region_overrides,
            applicant_overrides=applicant_overrides,
        )
    owner = make_applicant_headers(ref["owner_id"])
    app = make_draft_application(
        ref["owner_id"], ref["premise"]["id"],
        license_class_code=ref["cls"]["code"],
    )
    if submit_payload is None:
        if ref["cls"]["quota_managed"]:
            erv = expected_region_version
            if erv is None:
                erv = ref["region"]["version"]
            submit_payload = {"expected_region_version": erv}
        else:
            submit_payload = {}
    app = get_success_data(
        api_client.submit_application(app["id"], submit_payload, owner)
    )
    return ref, app


def get_background_check_id(app_id) -> str:
    data = get_success_data(
        api_client.list_application_background_checks(app_id, EXAMINER)
    )
    return data[0]["id"]


def get_zoning_review_id(app_id) -> str:
    data = get_success_data(
        api_client.list_application_zoning_reviews(app_id, ZONING)
    )
    return data[0]["id"]


def pass_background_check(app_id, examiner_user_id="exam-1"):
    bc_id = get_background_check_id(app_id)
    return get_success_data(
        api_client.resolve_background_check(
            bc_id, {"decision": "PASS"}, make_examiner_headers(examiner_user_id)
        )
    )


def clear_zoning_review(app_id, decision="CLEAR"):
    zr_id = get_zoning_review_id(app_id)
    return get_success_data(
        api_client.decide_zoning_review(zr_id, {"decision": decision}, ZONING)
    )


def advance_to_protest_period(ref, app, examiner_user_id="exam-1"):
    """From SUBMITTED: resolve background PASS, clear zoning (if a review exists),
    begin-review, open-protest-period. Returns the application in PROTEST_PERIOD.
    """
    examiner = make_examiner_headers(examiner_user_id)
    pass_background_check(app["id"], examiner_user_id)
    if app.get("zoning_review_id") or ref["cls"]["requires_zoning"]:
        # The review exists only for requires_zoning classes; list returns it.
        zr = get_success_data(api_client.list_application_zoning_reviews(app["id"], ZONING))
        if zr:
            clear_zoning_review(app["id"])
    get_success_data(api_client.begin_review(app["id"], examiner))
    get_success_data(api_client.open_protest_period(app["id"], examiner))
    return get_success_data(api_client.get_application(app["id"], DIRECTOR))


def approve_and_issue(
    ref, app, clock_after_protest=CLOCK_AFTER_PROTEST,
    fee_amount_cents=110000, director_user_id="dir-1",
):
    """From PROTEST_PERIOD: advance clock past the window, approve, pay the full
    fee, issue. Returns the issued License object (fetched via GET /licenses).
    """
    director = make_director_headers(director_user_id)
    owner = make_applicant_headers(ref["owner_id"])
    set_clock(clock_after_protest)
    get_success_data(api_client.approve_application(app["id"], director))
    get_success_data(api_client.pay_fee(app["id"], {"amount_cents": fee_amount_cents}, owner))
    get_success_data(api_client.issue_application(app["id"], director))
    licenses = get_success_data(
        api_client.list_licenses(DIRECTOR, params={"application_id": app["id"]})
    )
    return licenses[0]


def setup_issued_license(
    class_overrides=None, region_overrides=None, applicant_overrides=None,
    fee_amount_cents=110000,
):
    """Full pipeline DRAFT -> ISSUED. Returns a dict with keys:
    ref, app, license. The license is ACTIVE.
    """
    ref, app = create_submitted_application(
        class_overrides=class_overrides,
        region_overrides=region_overrides,
        applicant_overrides=applicant_overrides,
    )
    advance_to_protest_period(ref, app)
    app = get_success_data(api_client.get_application(app["id"], DIRECTOR))
    lic = approve_and_issue(ref, app, fee_amount_cents=fee_amount_cents)
    return {"ref": ref, "app": app, "license": lic}


# ─── Protest / hearing shortcuts ──────────────────────────────────────────
def file_protest(app_id, grounds="OVER_CONCENTRATION", protester_name="Neighbor Assoc",
                 headers=None):
    payload = create_protest_payload(
        application_id=app_id, grounds=grounds, protester_name=protester_name
    )
    return get_success_data(api_client.create_protest(payload, headers or ANON))


def setup_application_in_protest_period_with_filed_protest(
    grounds="OVER_CONCENTRATION", protester_name="Neighbor Assoc",
):
    """Application in PROTEST_PERIOD with one FILED protest. Returns
    (ref, app, protest). Clock is at CLOCK_START (still inside the window).
    """
    ref, app = create_submitted_application()
    advance_to_protest_period(ref, app)
    protest = file_protest(app["id"], grounds=grounds, protester_name=protester_name)
    app = get_success_data(api_client.get_application(app["id"], DIRECTOR))
    return ref, app, protest


def schedule_hearing(protest_id, room_code="RM-1",
                     starts_at="2026-01-10T09:00:00Z", ends_at="2026-01-10T11:00:00Z"):
    payload = {"room_code": room_code, "starts_at": starts_at, "ends_at": ends_at}
    return get_success_data(api_client.schedule_hearing(protest_id, payload, ADJUDICATOR))


def setup_application_in_protest_hearing(
    grounds="PUBLIC_NUISANCE", room_code="RM-1",
    starts_at="2026-01-10T09:00:00Z", ends_at="2026-01-10T11:00:00Z",
):
    """Application in PROTEST_HEARING: one SCHEDULED protest + PENDING hearing.
    Returns (ref, app, protest, hearing_id). Clock left at CLOCK_START.
    """
    ref, app, protest = setup_application_in_protest_period_with_filed_protest(grounds=grounds)
    protest = schedule_hearing(protest["id"], room_code=room_code,
                               starts_at=starts_at, ends_at=ends_at)
    app = get_success_data(api_client.get_application(app["id"], DIRECTOR))
    return ref, app, protest, protest["hearing_id"]


# ─── Server permit shortcuts ──────────────────────────────────────────────
def create_server_permit(license_id, owner_id, training_completed=True,
                         holder_name="Bartender A"):
    payload = create_server_permit_payload(
        license_id=license_id, holder_name=holder_name,
        training_completed=training_completed,
    )
    return get_success_data(
        api_client.create_server_permit(payload, make_applicant_headers(owner_id))
    )


def activate_server_permit(permit_id, owner_id, expected_license_version):
    return get_success_data(
        api_client.activate_server_permit(
            permit_id, {"expected_license_version": expected_license_version},
            make_applicant_headers(owner_id),
        )
    )


def setup_license_with_active_permit(holder_name="Bartender A"):
    """Issued ACTIVE license + one ACTIVE ServerPermit (active_server_count=1).
    Returns a dict: ref, app, license, permit. The license object is the
    POST-activation snapshot fetched fresh.
    """
    bundle = setup_issued_license()
    lic = bundle["license"]
    owner_id = bundle["ref"]["owner_id"]
    permit = create_server_permit(lic["id"], owner_id, training_completed=True,
                                  holder_name=holder_name)
    activate_server_permit(permit["id"], owner_id, lic["version"])
    lic = get_success_data(api_client.get_license(lic["id"], DIRECTOR))
    permit = get_success_data(api_client.get_server_permit(permit["id"], DIRECTOR))
    bundle["license"] = lic
    bundle["permit"] = permit
    return bundle


# ─── Violation / discipline shortcuts ─────────────────────────────────────
def file_violation(license_id, severity="SERIOUS", investigator_user_id="inv-1"):
    payload = create_violation_payload(license_id=license_id, severity=severity)
    return get_success_data(
        api_client.create_violation(payload, make_investigator_headers(investigator_user_id))
    )


def sustain_violation(violation_id, action_type="FINE", suspension_days=None,
                      adjudicator_user_id="adj-1"):
    payload = {"action_type": action_type}
    if suspension_days is not None:
        payload["suspension_days"] = suspension_days
    return get_success_data(
        api_client.sustain_violation(
            violation_id, payload, make_adjudication_officer_headers(adjudicator_user_id)
        )
    )


def file_and_sustain_violation(license_id, severity="SERIOUS", action_type="FINE",
                               suspension_days=None):
    """File a violation then sustain it. Returns (violation, action_id)."""
    vio = file_violation(license_id, severity=severity)
    sustained = sustain_violation(vio["id"], action_type=action_type,
                                  suspension_days=suspension_days)
    return sustained, sustained.get("action_id")


# ─── Quota helpers ────────────────────────────────────────────────────────
def get_quota_status(region_id, license_class_code="ON_47"):
    return get_success_data(
        api_client.quota_status(region_id, DIRECTOR, params={"license_class_code": license_class_code})
    )
