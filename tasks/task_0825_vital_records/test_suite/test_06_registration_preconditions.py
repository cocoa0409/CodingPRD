"""Registration domain-precondition ordering: the certification gate is checked
before the delayed-registration packet gate, and the birth delayed-packet gate in
isolation."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_facility,
    create_certifier,
    create_vital_event,
    create_certification,
    certify,
    file_event,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / register_certification_required_outprioritizes_delayed
# ---------------------------------------------------------------------------
def test_register_no_cert_no_packet_returns_certification_required(api):
    """PRD §3.1: "If `certification_required` is true, the record's
    `MedicalCertification` must be in `CERTIFIED` status, otherwise the request is
    rejected with `ERR_CERTIFICATION_REQUIRED`. If `registration_type` is
    `DELAYED` or `FOREIGN`, an accepted delayed-registration packet must exist for
    the record, otherwise the request is rejected with
    `ERR_DELAYED_REGISTRATION_REQUIRED`; certification is checked before the
    packet requirement."

    Design: Difficulty/priority_pair_validation_conflict/register_certification_required_outprioritizes_delayed
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-14")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-02-20T00:00:00Z",
        jurisdiction_code="CTY-14", sex="MALE",
    )
    file_event(ev["id"], fac["id"])  # clock 2026-03-01 default → 9 days late → DELAYED
    resp = api.register_vital_event(ev["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)


def test_register_with_cert_but_no_packet_returns_delayed_required(api):
    """PRD §3.1: "If `registration_type` is `DELAYED` or `FOREIGN`, an accepted
    delayed-registration packet must exist for the record, otherwise the request
    is rejected with `ERR_DELAYED_REGISTRATION_REQUIRED`; certification is checked
    before the packet requirement."

    Design: Difficulty/priority_pair_validation_conflict/register_certification_required_outprioritizes_delayed
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-14")
    cer = create_certifier(jurisdiction_code="CTY-14")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-02-20T00:00:00Z",
        jurisdiction_code="CTY-14", sex="MALE",
    )
    cert = create_certification(ev["id"], cer["id"], cause_of_death="MI")
    certify(cert["id"], cer["id"])
    file_event(ev["id"], fac["id"])  # 9 days late → DELAYED, no packet accepted
    resp = api.register_vital_event(ev["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_DELAYED_REGISTRATION_REQUIRED)


# ---------------------------------------------------------------------------
# Corner: validations / register_delayed_birth_without_packet_returns_delayed_required
# ---------------------------------------------------------------------------
def test_register_delayed_birth_without_packet_returns_delayed_required(api):
    """PRD §3.1: "If `registration_type` is `DELAYED` or `FOREIGN`, an accepted
    delayed-registration packet must exist for the record, otherwise the request
    is rejected with `ERR_DELAYED_REGISTRATION_REQUIRED`; certification is checked
    before the packet requirement."

    Design: Corner/validations/register_delayed_birth_without_packet_returns_delayed_required
    """
    fac = create_facility(jurisdiction_code="CTY-49")
    ev = create_vital_event(
        fac["id"], event_type="BIRTH", event_date="2026-02-25T00:00:00Z",
        jurisdiction_code="CTY-49", sex="FEMALE",
    )
    set_clock("2026-03-17T00:00:00Z")  # 20 days late for BIRTH (window 10) → DELAYED
    file_event(ev["id"], fac["id"])
    resp = api.register_vital_event(ev["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_DELAYED_REGISTRATION_REQUIRED)
