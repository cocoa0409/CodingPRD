"""Composite setup helpers.

Every interesting test claim in this PRD requires the registry to be in a
specific state reached through several API calls: a clock instant, a product,
a provider, a lot, a patient, then one or more recorded doses, evaluations,
certificates, recalls, or batch reports. These helpers encapsulate those
chains. Each test starts against an empty database (the harness restarts the
server before every test), so every helper builds its preconditions from
scratch using only PRD-declared endpoints.

All helpers use get_success_data() (lenient 2xx validator) so a setup failure
surfaces as a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_registrar_headers, make_clerk_headers, make_provider_headers,
)
from .factories import (
    create_patient_payload, create_provider_payload, create_product_payload,
    create_lot_payload, create_immunization_payload,
    create_allergy_record_payload, create_provider_report_payload,
    create_report_line_payload, create_adverse_event_payload,
    create_certificate_payload,
)
from .constants import DEFAULT_CLOCK


REG = make_registrar_headers()


# --------------------------------------------------------------------------
# Tier 0: primitives
# --------------------------------------------------------------------------
def set_clock(instant: str = DEFAULT_CLOCK):
    """Set the server's current UTC instant (drives age + as_of_date default)."""
    return get_success_data(api_client.set_clock(instant, REG))


def create_product(**overrides):
    """Create a VaccineProduct (registrar-only). Defaults to single-dose C1."""
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), REG))


def create_provider(**overrides):
    """Enroll a Provider (registrar-only)."""
    return get_success_data(
        api_client.create_provider(create_provider_payload(**overrides), REG))


def create_lot(product_id, **overrides):
    """Register a VaccineLot for a product (registrar-only)."""
    payload = create_lot_payload(product_id=product_id, **overrides)
    return get_success_data(api_client.create_lot(payload, REG))


def create_patient(**overrides):
    """Register a Patient."""
    return get_success_data(
        api_client.create_patient(create_patient_payload(**overrides), REG))


def record_dose(patient_id, lot_id, provider_id, administered_date, **overrides):
    """Record a directly administered dose; returns the Immunization."""
    payload = create_immunization_payload(
        patient_id=patient_id, lot_id=lot_id, provider_id=provider_id,
        administered_date=administered_date, **overrides)
    return get_success_data(api_client.create_immunization(payload, REG))


def create_allergy(patient_id, antigen, severity=None):
    """Create an AllergyRecord for a patient/antigen."""
    payload = create_allergy_record_payload(patient_id=patient_id, antigen=antigen)
    if severity is not None:
        payload["severity"] = severity
    return get_success_data(api_client.create_allergy_record(payload, REG))


# --------------------------------------------------------------------------
# Tier 1: standard catalogue + patient scaffolds
# --------------------------------------------------------------------------
def setup_catalog(product_overrides=None, provider_overrides=None,
                  lot_overrides=None, clock=DEFAULT_CLOCK):
    """Clock + one product + one provider authorized for it + one valid lot.

    Returns (product, provider, lot). The provider is authorized for the
    product's product_code unless provider_overrides specifies otherwise.
    """
    set_clock(clock)
    product = create_product(**(product_overrides or {}))
    prov_ov = dict(provider_overrides or {})
    prov_ov.setdefault("authorized_product_codes", [product["product_code"]])
    provider = create_provider(**prov_ov)
    lot = create_lot(product["id"], **(lot_overrides or {}))
    return product, provider, lot


def setup_catalog_and_patient(product_overrides=None, provider_overrides=None,
                              lot_overrides=None, patient_overrides=None,
                              clock=DEFAULT_CLOCK):
    """setup_catalog + one patient. Returns (product, provider, lot, patient)."""
    product, provider, lot = setup_catalog(
        product_overrides, provider_overrides, lot_overrides, clock)
    patient = create_patient(**(patient_overrides or {}))
    return product, provider, lot, patient


def setup_patient_with_doses(dose_dates, product_overrides=None,
                             patient_overrides=None, lot_overrides=None,
                             provider_overrides=None,
                             clock=DEFAULT_CLOCK):
    """Catalog + patient + one recorded dose per date in `dose_dates`.

    Returns (product, provider, lot, patient, doses) where doses is the list of
    recorded Immunizations in the order of dose_dates.
    """
    product, provider, lot, patient = setup_catalog_and_patient(
        product_overrides, provider_overrides, lot_overrides,
        patient_overrides, clock)
    doses = [
        record_dose(patient["id"], lot["id"], provider["id"], d)
        for d in dose_dates
    ]
    return product, provider, lot, patient, doses


# --------------------------------------------------------------------------
# Tier 2: evaluation + certificate lifecycle
# --------------------------------------------------------------------------
def run_evaluation(patient_id, as_of_date):
    """Run the catch-up engine for a patient; returns the ScheduleEvaluation."""
    return get_success_data(api_client.create_evaluation(
        patient_id, {"as_of_date": as_of_date}, REG))


def issue_certificate(patient_id, evaluation_id, expected_patient_version,
                      headers=None):
    """Issue a SchoolComplianceCertificate (returns the raw response so the
    caller can assert success or a specific error)."""
    payload = create_certificate_payload(
        evaluation_id=evaluation_id,
        expected_patient_version=expected_patient_version)
    return api_client.create_certificate(patient_id, payload, headers or REG)


def setup_evaluated_patient(as_of_date, dose_dates, product_overrides=None,
                            patient_overrides=None, clock=DEFAULT_CLOCK):
    """Catalog + patient with the given valid doses + one evaluation.

    Returns (product, provider, lot, patient, doses, evaluation, patient_version)
    where patient_version is the Patient.version observed immediately after the
    evaluation (the value a certificate-issue OCC check must carry).
    """
    product, provider, lot, patient, doses = setup_patient_with_doses(
        dose_dates, product_overrides, patient_overrides, clock=clock)
    evaluation = run_evaluation(patient["id"], as_of_date)
    patient_after = get_success_data(
        api_client.get_patient(patient["id"], REG))
    return (product, provider, lot, patient, doses, evaluation,
            patient_after["version"])


def setup_certified_patient(as_of_date="2026-06-01", clock=DEFAULT_CLOCK):
    """A single-dose-compliant patient (UP_TO_DATE) with an issued COMPLETE
    certificate. Returns (product, provider, lot, patient, dose, evaluation,
    certificate).

    Uses single-dose C1 (min_age 0, min_interval 0) so one dose satisfies the
    only mandated antigen and the evaluation is UP_TO_DATE.
    """
    (product, provider, lot, patient, doses, evaluation, pv) = \
        setup_evaluated_patient(
            as_of_date, dose_dates=["2025-01-01"],
            product_overrides=create_product_payload(
                product_code="C1", antigen="C1", doses_in_series=1,
                min_age_days=0, recommended_age_days=0, min_interval_days=0),
            patient_overrides={"date_of_birth": "2024-01-01"},
            clock=clock)
    cert = get_success_data(
        issue_certificate(patient["id"], evaluation["id"], pv))
    return product, provider, lot, patient, doses[0], evaluation, cert


# --------------------------------------------------------------------------
# Tier 3: recall / reverse lifecycle
# --------------------------------------------------------------------------
def issue_recall(lot_id, reason="recall reason"):
    """Issue a LotRecall on a lot; returns the LotRecall."""
    return get_success_data(api_client.create_recall(lot_id, {"reason": reason}, REG))


def reverse_recall(lot_id, recall_id):
    """Reverse a recall; returns the LotRecall."""
    return get_success_data(api_client.reverse_recall(lot_id, recall_id, REG))


def setup_recalled_lot(clock=DEFAULT_CLOCK, product_overrides=None):
    """Catalog + patient where the lot has been recalled (no dose recorded).

    Returns (product, provider, lot, patient, recall).
    """
    product, provider, lot, patient = setup_catalog_and_patient(
        product_overrides=product_overrides, clock=clock)
    recall = issue_recall(lot["id"], reason="recalled")
    return product, provider, lot, patient, recall


# --------------------------------------------------------------------------
# Tier 4: provider batch reports
# --------------------------------------------------------------------------
def open_report(provider_id, line_count, headers=None):
    """Open a DRAFT ProviderReport; returns the report."""
    payload = create_provider_report_payload(
        provider_id=provider_id, line_count=line_count)
    return get_success_data(
        api_client.create_provider_report(payload, headers or REG))


def add_line(report_id, patient_id, lot_id, administered_date, headers=None):
    """Attach one dose line to a draft report."""
    payload = create_report_line_payload(
        patient_id=patient_id, lot_id=lot_id, administered_date=administered_date)
    return get_success_data(
        api_client.add_report_line(report_id, payload, headers or REG))


def setup_submitted_report(lines, line_count=None, provider_overrides=None,
                           product_overrides=None, lot_overrides=None,
                           clock=DEFAULT_CLOCK, extra_lots=None,
                           patient_overrides=None):
    """Build a SUBMITTED report ready for adjudication.

    `lines` is a list of dicts each with keys (lot_key, administered_date) where
    lot_key indexes into the lots dict; "main" is the default catalogue lot.
    `extra_lots` is an optional dict {lot_key: lot_overrides} of additional lots
    to create against the same product (e.g. a recalled lot for partial-reject
    scenarios).

    Returns (product, provider, lots_by_key, patient, report). The report is
    submitted by the owning Provider (identity threaded as Provider.id).
    """
    product, provider, lot = setup_catalog(
        product_overrides=product_overrides,
        provider_overrides=provider_overrides,
        lot_overrides=lot_overrides, clock=clock)
    lots = {"main": lot}
    for key, ov in (extra_lots or {}).items():
        lots[key] = create_lot(product["id"], **(ov or {}))
    patient = create_patient(**(patient_overrides or {}))

    prov_headers = make_provider_headers(provider["id"])
    lc = line_count if line_count is not None else len(lines)
    report = open_report(provider["id"], lc, headers=prov_headers)
    for ln in lines:
        add_line(report["id"], patient["id"], lots[ln["lot_key"]]["id"],
                 ln["administered_date"], headers=prov_headers)
    report = get_success_data(
        api_client.submit_provider_report(report["id"], prov_headers))
    return product, provider, lots, patient, report


# --------------------------------------------------------------------------
# Tier 5: adverse-event lifecycle
# --------------------------------------------------------------------------
def file_adverse_event(immunization_id, seriousness, symptoms="symptoms"):
    """File a VAERS adverse-event report; returns the AdverseEvent."""
    payload = create_adverse_event_payload(
        immunization_id=immunization_id, seriousness=seriousness,
        symptoms=symptoms)
    return get_success_data(api_client.create_adverse_event(payload, REG))


def setup_adverse_event_under_review(seriousness, doses_in_series=1,
                                     clock=DEFAULT_CLOCK):
    """A patient with one recorded dose and a filed adverse event moved to
    UNDER_REVIEW (ready to confirm).

    Returns (product, provider, lot, patient, dose, adverse_event).
    """
    product, provider, lot, patient, doses = setup_patient_with_doses(
        dose_dates=["2025-01-01"],
        product_overrides=create_product_payload(
            product_code="C1", antigen="C1", doses_in_series=doses_in_series,
            min_age_days=0, recommended_age_days=0, min_interval_days=0),
        patient_overrides={"date_of_birth": "2024-01-01"},
        clock=clock)
    dose = doses[0]
    ae = file_adverse_event(dose["id"], seriousness)
    ae = get_success_data(api_client.review_adverse_event(ae["id"], REG))
    return product, provider, lot, patient, dose, ae
