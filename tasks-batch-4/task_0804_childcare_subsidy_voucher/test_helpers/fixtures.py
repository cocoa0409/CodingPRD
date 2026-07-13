"""Composite setup helpers for the CCDF API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty database before each
test). Setup calls use get_success_data() (lenient) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: Provider is entity_backed, so every provider-owned call
(submitting/resubmitting attendance) uses make_provider_headers(provider_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_provider_headers
from .factories import (
    create_family_payload,
    create_parent_activity_payload,
    create_income_standard_payload,
    create_determination_payload,
    create_provider_payload,
    create_rate_ceiling_payload,
    create_authorization_payload,
    create_attendance_payload,
)

CW = TEST_USERS["caseworker_headers"]
PA = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Atomic building blocks
# ---------------------------------------------------------------------------
def publish_income_standard(household_size=3, entry_monthly_limit_cents=400_000,
                            exit_monthly_limit_cents=500_000, state_code="CA"):
    resp = api_client.create_income_standard(
        create_income_standard_payload(
            household_size=household_size,
            entry_monthly_limit_cents=entry_monthly_limit_cents,
            exit_monthly_limit_cents=exit_monthly_limit_cents,
            state_code=state_code,
        ), PA)
    return get_success_data(resp)


def publish_rate_ceiling(**overrides):
    resp = api_client.create_rate_ceiling(create_rate_ceiling_payload(**overrides), PA)
    return get_success_data(resp)


def create_family(gross=250_000, self_emp=0, household_size=3, state_code="CA",
                  applicant_name="A Fam"):
    resp = api_client.create_family(
        create_family_payload(
            applicant_name=applicant_name,
            household_size=household_size,
            monthly_gross_income_cents=gross,
            monthly_self_employment_income_cents=self_emp,
            state_code=state_code,
        ), CW)
    return get_success_data(resp)


def add_activity(family_id, activity_type="WORK", weekly_hours=40):
    resp = api_client.create_parent_activity(
        create_parent_activity_payload(family_id, activity_type=activity_type,
                                        weekly_hours=weekly_hours), CW)
    return get_success_data(resp)


def create_family_with_activity(gross=250_000, self_emp=0, household_size=3,
                                state_code="CA", weekly_hours=40,
                                activity_type="WORK", applicant_name="A Fam"):
    family = create_family(gross=gross, self_emp=self_emp, household_size=household_size,
                           state_code=state_code, applicant_name=applicant_name)
    add_activity(family["id"], activity_type=activity_type, weekly_hours=weekly_hours)
    return family


def open_determination(family_id, determination_type="INITIAL"):
    resp = api_client.create_determination(
        create_determination_payload(family_id, determination_type), CW)
    return get_success_data(resp)


def finalize_determination(determination_id):
    resp = api_client.finalize_determination(determination_id, CW)
    return get_success_data(resp)


def create_approved_determination(family_id, determination_type="INITIAL"):
    det = open_determination(family_id, determination_type)
    return finalize_determination(det["id"])


def register_provider(published=6_000, provider_type="CENTER", state_code="CA",
                      license_expiry="2027-01-01T00:00:00Z", name="Sunny Center"):
    resp = api_client.create_provider(
        create_provider_payload(name=name, provider_type=provider_type,
                                published_daily_rate_cents=published,
                                license_expiry_date=license_expiry,
                                state_code=state_code), PA)
    return get_success_data(resp)


def verify_provider(provider_id):
    resp = api_client.license_provider(provider_id, {"action": "VERIFY"}, PA)
    return get_success_data(resp)


def create_licensed_provider(published=6_000, provider_type="CENTER", state_code="CA",
                             license_expiry="2027-01-01T00:00:00Z", name="Sunny Center"):
    provider = register_provider(published=published, provider_type=provider_type,
                                 state_code=state_code, license_expiry=license_expiry,
                                 name=name)
    verify_provider(provider["id"])
    # Re-read so callers see the LICENSED status.
    return get_success_data(api_client.get_provider(provider["id"], PA))


def get_family_version(family_id):
    data = get_success_data(api_client.get_family(family_id, CW))
    return data["version"]


def create_pending_authorization(family_id, provider_id, determination_id,
                                 child_name="Kid One", care_level="TODDLER",
                                 start_date="2026-03-01T00:00:00Z",
                                 end_date="2026-09-01T00:00:00Z",
                                 authorized_days_per_month=22,
                                 expected_family_version=None):
    if expected_family_version is None:
        expected_family_version = get_family_version(family_id)
    resp = api_client.create_authorization(
        create_authorization_payload(
            family_id, provider_id, determination_id, expected_family_version,
            child_name=child_name, care_level=care_level, start_date=start_date,
            end_date=end_date, authorized_days_per_month=authorized_days_per_month), CW)
    return get_success_data(resp)


def activate_authorization(authorization_id):
    return get_success_data(api_client.activate_authorization(authorization_id, CW))


# ---------------------------------------------------------------------------
# Full scenario composites
# ---------------------------------------------------------------------------
def setup_active_authorization(gross=250_000, self_emp=0, published=6_000,
                               ceiling_max=5_000, care_level="TODDLER",
                               authorized_days_per_month=22, child_name="Kid One",
                               determination_type="INITIAL", household_size=3,
                               entry=400_000, exit_=500_000,
                               start_date="2026-03-01T00:00:00Z",
                               end_date="2026-09-01T00:00:00Z"):
    """Full chain to an ACTIVE Authorization on a LICENSED provider.

    Returns dict with keys: income_standard, rate_ceiling, family, determination,
    provider, authorization.
    """
    income_standard = publish_income_standard(
        household_size=household_size, entry_monthly_limit_cents=entry,
        exit_monthly_limit_cents=exit_)
    rate_ceiling = publish_rate_ceiling(care_level=care_level,
                                        max_daily_rate_cents=ceiling_max)
    family = create_family_with_activity(gross=gross, self_emp=self_emp,
                                         household_size=household_size)
    determination = create_approved_determination(family["id"], determination_type)
    provider = create_licensed_provider(published=published)
    authorization = create_pending_authorization(
        family["id"], provider["id"], determination["id"], child_name=child_name,
        care_level=care_level, start_date=start_date, end_date=end_date,
        authorized_days_per_month=authorized_days_per_month)
    activate_authorization(authorization["id"])
    authorization = get_success_data(api_client.get_authorization(authorization["id"], CW))
    return {
        "income_standard": income_standard,
        "rate_ceiling": rate_ceiling,
        "family": family,
        "determination": determination,
        "provider": provider,
        "authorization": authorization,
    }


def submit_attendance(authorization_id, provider_id, service_month="2026-03",
                      present_days=18, absent_days=3):
    resp = api_client.create_attendance_record(
        create_attendance_payload(authorization_id, service_month=service_month,
                                  present_days=present_days, absent_days=absent_days),
        make_provider_headers(provider_id))
    return get_success_data(resp)


def approve_attendance(attendance_id):
    return get_success_data(api_client.approve_attendance(attendance_id, CW))


def get_payment_for_attendance(attendance_id):
    data, _meta = _list(api_client.list_payments(CW, params={"attendance_record_id": attendance_id}))
    assert data, f"expected a payment for attendance {attendance_id}"
    return data[0]


def _list(resp):
    body = resp.json()
    return body["data"], body.get("meta", {})


def setup_paid_payment(gross=250_000, self_emp=0, published=6_000, ceiling_max=5_000,
                       authorized_days_per_month=22, present_days=18, absent_days=3,
                       service_month="2026-03", determination_type="INITIAL"):
    """ACTIVE Authorization -> submitted attendance -> approved -> PAID Payment.

    Returns dict adding: attendance, payment (on top of setup_active_authorization).
    """
    ctx = setup_active_authorization(
        gross=gross, self_emp=self_emp, published=published, ceiling_max=ceiling_max,
        authorized_days_per_month=authorized_days_per_month,
        determination_type=determination_type)
    attendance = submit_attendance(ctx["authorization"]["id"], ctx["provider"]["id"],
                                   service_month=service_month, present_days=present_days,
                                   absent_days=absent_days)
    attendance = approve_attendance(attendance["id"])
    payment = get_payment_for_attendance(attendance["id"])
    ctx["attendance"] = attendance
    ctx["payment"] = payment
    return ctx


def setup_open_overpayment_claim(**overrides):
    """Full chain to an OPEN OverpaymentClaim raised by a payment reversal.

    Returns dict adding: reversed_payment, claim.
    """
    ctx = setup_paid_payment(**overrides)
    reversed_payment = get_success_data(
        api_client.reverse_payment(ctx["payment"]["id"], PA, {"reason": "audit"}))
    data, _meta = _list(api_client.list_overpayment_claims(
        PA, params={"payment_id": ctx["payment"]["id"]}))
    assert data, "expected an overpayment claim after reversal"
    ctx["reversed_payment"] = reversed_payment
    ctx["claim"] = data[0]
    return ctx
