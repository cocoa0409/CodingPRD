"""Composite setup helpers.

The harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Setup
calls use get_success_data() so a setup failure surfaces clearly.

Identity threading: the Provider role is entity_backed, so every ownership /
segregation-gated clinical call uses make_provider_headers(<provider_id>) with
the *acting* provider's id — never the shared constant. ClinicAdmin is opaque.

Most "interesting" assertions need a session that is several state-machine hops
deep (plan PROPOSED -> ACTIVE, session BOOKED -> COMMITTED, etc.). The builders
below expose `**overrides` for the values tests control (membership discount,
list price, units, deposit, products, lot expiry, clock) and default the rest.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import make_clinic_admin_headers, make_provider_headers
from . import factories as F

ADMIN = make_clinic_admin_headers()
DEFAULT_EXP = "2026-12-01T00:00:00Z"


def _data(resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Set the logical server clock (§2.4)."""
    return _data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def make_injector(full_name="Test Injector", license_number="L-INJ"):
    return _data(api_client.create_provider(
        F.create_provider_payload(full_name=full_name, license_number=license_number,
                                  role_kind="INJECTOR"), ADMIN))


def make_director(full_name="Test Director", license_number="L-MD"):
    return _data(api_client.create_provider(
        F.create_provider_payload(full_name=full_name, license_number=license_number,
                                  role_kind="MEDICAL_DIRECTOR"), ADMIN))


def make_membership(tier="PLUS", member_discount_pct=0.15, loyalty_program="ALLE",
                    monthly_fee_cents=9900):
    return _data(api_client.create_membership_package(
        F.create_membership_package_payload(
            tier=tier, member_discount_pct=member_discount_pct,
            loyalty_program=loyalty_program, monthly_fee_cents=monthly_fee_cents), ADMIN))


def make_lot(product="BOTOX", lot_number="LOT-1", expiration_date=DEFAULT_EXP,
             total_units=100):
    return _data(api_client.create_injectable_lot(
        F.create_injectable_lot_payload(
            product=product, lot_number=lot_number,
            expiration_date=expiration_date, total_units=total_units), ADMIN))


def make_patient(full_name="Test Patient", membership_id=None,
                 date_of_birth="1990-01-01T00:00:00Z"):
    return _data(api_client.create_patient(
        F.create_patient_payload(full_name=full_name, membership_id=membership_id,
                                 date_of_birth=date_of_birth), ADMIN))


def make_loyalty_account(patient_id, program="ALLE"):
    return _data(api_client.create_loyalty_account(
        F.create_loyalty_account_payload(patient_id, program=program), ADMIN))


def sign_consent(patient_id, actor_provider_id, storage_uri="s3://consent"):
    """Record a signed CONSENT photo, flipping photo_consent_on_file to true (§3.5)."""
    return _data(api_client.create_consent_photo(
        F.create_consent_photo_payload(patient_id, kind="CONSENT",
                                       storage_uri=storage_uri, signed=True),
        make_provider_headers(actor_provider_id)))


def add_before_photo(patient_id, session_id, actor_provider_id, storage_uri="s3://before"):
    return _data(api_client.create_consent_photo(
        F.create_consent_photo_payload(patient_id, kind="BEFORE",
                                       storage_uri=storage_uri,
                                       treatment_session_id=session_id),
        make_provider_headers(actor_provider_id)))


def add_after_photo(patient_id, session_id, actor_provider_id, storage_uri="s3://after"):
    return _data(api_client.create_consent_photo(
        F.create_consent_photo_payload(patient_id, kind="AFTER",
                                       storage_uri=storage_uri,
                                       treatment_session_id=session_id),
        make_provider_headers(actor_provider_id)))


def make_consultation(patient_id, exam_provider_id, chief_complaint="lines"):
    return _data(api_client.create_consultation(
        F.create_consultation_payload(patient_id, exam_provider_id,
                                      chief_complaint=chief_complaint),
        make_provider_headers(exam_provider_id)))


def complete_exam(consultation_id, exam_provider_id):
    return _data(api_client.complete_exam(consultation_id,
                                          make_provider_headers(exam_provider_id)))


def make_standing_order(consultation_id, director_provider_id, product="BOTOX",
                        max_units_authorized=30, valid_until_utc=DEFAULT_EXP):
    return _data(api_client.create_standing_order(
        F.create_standing_order_payload(
            consultation_id, director_provider_id, product=product,
            max_units_authorized=max_units_authorized, valid_until_utc=valid_until_utc),
        make_provider_headers(director_provider_id)))


def revoke_standing_order(order_id, expected_version, director_provider_id):
    return _data(api_client.revoke_standing_order(
        order_id, {"expected_standing_order_version": expected_version},
        make_provider_headers(director_provider_id)))


def make_plan(patient_id, consultation_id, injector_provider_id, product="BOTOX",
              planned_sessions=1, planned_units_per_session=20,
              list_price_per_unit_cents=1000, required_deposit_cents=0):
    return _data(api_client.create_treatment_plan(
        F.create_treatment_plan_payload(
            patient_id, consultation_id, product=product,
            planned_sessions=planned_sessions,
            planned_units_per_session=planned_units_per_session,
            list_price_per_unit_cents=list_price_per_unit_cents,
            required_deposit_cents=required_deposit_cents),
        make_provider_headers(injector_provider_id)))


def post_deposit(plan_id, amount_cents, expected_version):
    return _data(api_client.create_deposit(
        F.create_deposit_payload(plan_id, amount_cents, expected_version), ADMIN))


def activate_plan(plan_id, expected_version, injector_provider_id):
    return _data(api_client.activate_plan(
        plan_id, {"expected_treatment_plan_version": expected_version},
        make_provider_headers(injector_provider_id)))


def plan_version(plan_id, injector_provider_id):
    """Re-read a plan and return its current version (helper for OCC threading)."""
    return _data(api_client.get_treatment_plan(
        plan_id, make_provider_headers(injector_provider_id)))["version"]


def book_session(plan_id, standing_order_id, injector_provider_id, lot_id,
                 planned_units, expected_version, loyalty_points_redeemed=None):
    return _data(api_client.create_treatment_session(
        F.create_treatment_session_payload(
            plan_id, standing_order_id, injector_provider_id, lot_id,
            planned_units, expected_version,
            loyalty_points_redeemed=loyalty_points_redeemed),
        make_provider_headers(injector_provider_id)))


def commit_session(session_id, injector_provider_id, actual_units=None):
    payload = {} if actual_units is None else {"actual_units": actual_units}
    return _data(api_client.commit_session(
        session_id, payload, make_provider_headers(injector_provider_id)))


def open_complication(session_id, injector_provider_id, severity="MODERATE"):
    return _data(api_client.create_complication_case(
        F.create_complication_case_payload(session_id, severity=severity),
        make_provider_headers(injector_provider_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenario builders
# ---------------------------------------------------------------------------
class Scenario:
    """A bag of ids captured while building a treatment scenario, so tests can
    reference exactly what they need without re-threading every fk."""

    def __init__(self):
        self.membership_id = None
        self.loyalty_account_id = None
        self.injector_id = None
        self.director_id = None
        self.lot_id = None
        self.patient_id = None
        self.consultation_id = None
        self.standing_order_id = None
        self.plan_id = None
        self.plan_version = None
        self.session_id = None
        self.case_id = None


def setup_active_plan(*, member=False, member_discount_pct=0.15, loyalty_program="ALLE",
                      product="BOTOX", list_price_per_unit_cents=1000,
                      planned_sessions=1, planned_units_per_session=20,
                      max_units_authorized=30, required_deposit_cents=0,
                      lot_units=100, lot_expiration=DEFAULT_EXP,
                      valid_until_utc=DEFAULT_EXP, open_loyalty=False,
                      sign_consent_photo=True) -> Scenario:
    """Build an ACTIVE plan with all booking prerequisites in place.

    Registers a distinct injector and director (segregation-safe), intakes one
    lot, registers a patient (member if requested), optionally signs CONSENT,
    runs consultation -> complete-exam, signs a standing order, proposes the
    plan, funds the required deposit if any, and activates. Returns a Scenario.
    """
    sc = Scenario()
    if member:
        sc.membership_id = make_membership(
            member_discount_pct=member_discount_pct, loyalty_program=loyalty_program)["id"]

    sc.injector_id = make_injector(license_number="L-INJ-A")["id"]
    sc.director_id = make_director(license_number="L-MD-A")["id"]
    sc.lot_id = make_lot(product=product, total_units=lot_units,
                         expiration_date=lot_expiration)["id"]
    sc.patient_id = make_patient(membership_id=sc.membership_id)["id"]
    if open_loyalty:
        sc.loyalty_account_id = make_loyalty_account(sc.patient_id, program=loyalty_program)["id"]
    if sign_consent_photo:
        sign_consent(sc.patient_id, sc.injector_id)

    sc.consultation_id = make_consultation(sc.patient_id, sc.injector_id)["id"]
    complete_exam(sc.consultation_id, sc.injector_id)
    sc.standing_order_id = make_standing_order(
        sc.consultation_id, sc.director_id, product=product,
        max_units_authorized=max_units_authorized, valid_until_utc=valid_until_utc)["id"]

    plan = make_plan(sc.patient_id, sc.consultation_id, sc.injector_id, product=product,
                     planned_sessions=planned_sessions,
                     planned_units_per_session=planned_units_per_session,
                     list_price_per_unit_cents=list_price_per_unit_cents,
                     required_deposit_cents=required_deposit_cents)
    sc.plan_id = plan["id"]
    pv = plan["version"]
    if required_deposit_cents > 0:
        post_deposit(sc.plan_id, required_deposit_cents, pv)
        pv = plan_version(sc.plan_id, sc.injector_id)
    activated = activate_plan(sc.plan_id, pv, sc.injector_id)
    sc.plan_version = activated["version"]
    return sc


def setup_proposed_plan(*, product="BOTOX", planned_sessions=1,
                        planned_units_per_session=20, list_price_per_unit_cents=1000,
                        required_deposit_cents=0, max_units_authorized=30,
                        sign_consent_photo=True, sign_order=True) -> Scenario:
    """Build a PROPOSED (not yet activated) plan with prerequisites in place."""
    sc = Scenario()
    sc.injector_id = make_injector(license_number="L-INJ-P")["id"]
    sc.director_id = make_director(license_number="L-MD-P")["id"]
    sc.lot_id = make_lot(product=product)["id"]
    sc.patient_id = make_patient()["id"]
    if sign_consent_photo:
        sign_consent(sc.patient_id, sc.injector_id)
    sc.consultation_id = make_consultation(sc.patient_id, sc.injector_id)["id"]
    complete_exam(sc.consultation_id, sc.injector_id)
    if sign_order:
        sc.standing_order_id = make_standing_order(
            sc.consultation_id, sc.director_id, product=product,
            max_units_authorized=max_units_authorized)["id"]
    plan = make_plan(sc.patient_id, sc.consultation_id, sc.injector_id, product=product,
                     planned_sessions=planned_sessions,
                     planned_units_per_session=planned_units_per_session,
                     list_price_per_unit_cents=list_price_per_unit_cents,
                     required_deposit_cents=required_deposit_cents)
    sc.plan_id = plan["id"]
    sc.plan_version = plan["version"]
    return sc


def setup_booked_session(*, member=False, member_discount_pct=0.15,
                         list_price_per_unit_cents=1000, planned_units=20,
                         max_units_authorized=30, planned_sessions=1,
                         planned_units_per_session=None, required_deposit_cents=0,
                         loyalty_points_redeemed=None, open_loyalty=False,
                         add_before=True) -> Scenario:
    """ACTIVE plan + one BOOKED session, with BEFORE photo on file by default."""
    if planned_units_per_session is None:
        planned_units_per_session = planned_units
    sc = setup_active_plan(member=member, member_discount_pct=member_discount_pct,
                           list_price_per_unit_cents=list_price_per_unit_cents,
                           planned_sessions=planned_sessions,
                           planned_units_per_session=planned_units_per_session,
                           max_units_authorized=max_units_authorized,
                           required_deposit_cents=required_deposit_cents,
                           open_loyalty=open_loyalty)
    session = book_session(sc.plan_id, sc.standing_order_id, sc.injector_id, sc.lot_id,
                           planned_units, sc.plan_version,
                           loyalty_points_redeemed=loyalty_points_redeemed)
    sc.session_id = session["id"]
    sc.plan_version = plan_version(sc.plan_id, sc.injector_id)
    if add_before:
        add_before_photo(sc.patient_id, sc.session_id, sc.injector_id)
    return sc


def setup_committed_session(*, member=False, member_discount_pct=0.15,
                            list_price_per_unit_cents=1000, planned_units=20,
                            actual_units=None, max_units_authorized=30,
                            planned_sessions=1, planned_units_per_session=None,
                            required_deposit_cents=0, loyalty_points_redeemed=None,
                            open_loyalty=False, add_after=False) -> Scenario:
    """ACTIVE plan + one COMMITTED session (BEFORE photo consumed at commit).

    Optionally records an AFTER photo so a subsequent resolve can succeed.
    """
    sc = setup_booked_session(member=member, member_discount_pct=member_discount_pct,
                              list_price_per_unit_cents=list_price_per_unit_cents,
                              planned_units=planned_units,
                              max_units_authorized=max_units_authorized,
                              planned_sessions=planned_sessions,
                              planned_units_per_session=planned_units_per_session,
                              required_deposit_cents=required_deposit_cents,
                              loyalty_points_redeemed=loyalty_points_redeemed,
                              open_loyalty=open_loyalty, add_before=True)
    commit_session(sc.session_id, sc.injector_id, actual_units=actual_units)
    sc.plan_version = plan_version(sc.plan_id, sc.injector_id)
    if add_after:
        add_after_photo(sc.patient_id, sc.session_id, sc.injector_id)
    return sc


def setup_open_complication(*, severity="MODERATE", add_after=False,
                            planned_units=20, max_units_authorized=30) -> Scenario:
    """COMMITTED session that has had a ComplicationCase opened (case OPEN,
    session COMPLICATION_OPEN)."""
    sc = setup_committed_session(planned_units=planned_units,
                                 max_units_authorized=max_units_authorized,
                                 add_after=add_after)
    case = open_complication(sc.session_id, sc.injector_id, severity=severity)
    sc.case_id = case["id"]
    return sc
