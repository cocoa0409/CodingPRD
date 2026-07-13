"""Composite setup helpers.

Every test runs against a freshly-restarted, empty server, so each helper builds all
of its preconditions from scratch using only PRD-declared endpoints. Fixtures use the
lenient get_success_data() validator so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: the CarrierRep role is entity-backed on Carrier, so every
ownership-gated call (contest / settle / register-driver / duty-log) uses
make_carrier_rep_headers(carrier["id"]). EnforcementOfficer identity is recorded on
citations and drives segregation-of-duties, so distinct issuing/adjudicating officers
use make_officer_headers("officer-1") / make_officer_headers("officer-2").
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_carrier_payload,
    create_driver_payload,
    create_station_payload,
    create_bay_payload,
    create_screening_payload,
    create_inspection_payload,
    create_violation_payload,
    create_citation_payload,
    create_duty_log_payload,
)
from .test_users import (
    TEST_USERS,
    make_carrier_rep_headers,
    make_officer_headers,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
SCREENER = TEST_USERS["screener_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER_1 = make_officer_headers("officer-1")
OFFICER_2 = make_officer_headers("officer-2")


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: base entities
# ---------------------------------------------------------------------------
def create_carrier(**overrides):
    return get_success_data(api_client.create_carrier(create_carrier_payload(**overrides), ADMIN))


def create_station(**overrides):
    return get_success_data(api_client.create_station(create_station_payload(**overrides), ADMIN))


def create_bay(station_id, **overrides):
    return get_success_data(api_client.create_bay(station_id, create_bay_payload(**overrides), ADMIN))


def create_driver(carrier_id, **overrides):
    return get_success_data(
        api_client.create_driver(carrier_id, create_driver_payload(**overrides), ADMIN))


def create_screening(station_id, carrier_id, driver_id, **overrides):
    payload = create_screening_payload(station_id, carrier_id, driver_id, **overrides)
    return get_success_data(api_client.create_screening(payload, SCREENER))


def create_inspection(screening_id, bay_id, **overrides):
    payload = create_inspection_payload(screening_id, bay_id, **overrides)
    return get_success_data(api_client.create_inspection(payload, INSPECTOR))


def add_violation(inspection_id, **overrides):
    payload = create_violation_payload(**overrides)
    return get_success_data(api_client.create_violation(inspection_id, payload, INSPECTOR))


def finalize(inspection_id, result):
    return get_success_data(api_client.finalize_inspection(inspection_id, {"result": result}, INSPECTOR))


def issue_citation(inspection_id, carrier_id, kind="OVERWEIGHT", officer_id="officer-1", **overrides):
    payload = create_citation_payload(inspection_id, carrier_id, kind=kind, **overrides)
    return get_success_data(
        api_client.create_citation(payload, make_officer_headers(officer_id)))


def contest_citation(citation_id, carrier_id, reason="contested"):
    return get_success_data(
        api_client.contest_citation(citation_id, {"contest_reason": reason},
                                    make_carrier_rep_headers(carrier_id)))


def adjudicate_citation(citation_id, result, officer_id="officer-2", **payload_extra):
    payload = {"result": result}
    payload.update(payload_extra)
    return get_success_data(
        api_client.adjudicate_citation(citation_id, payload, make_officer_headers(officer_id)))


def add_duty_log(driver_id, **overrides):
    payload = create_duty_log_payload(**overrides)
    return get_success_data(api_client.create_duty_log(driver_id, payload, ADMIN))


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------
def setup_domain(carrier_overrides=None, station_overrides=None):
    """Active carrier + default-limit station + one bay + one driver.

    Returns dict(carrier, station, bay, driver). The most common preamble.
    """
    carrier = create_carrier(**(carrier_overrides or {}))
    station = create_station(**(station_overrides or {}))
    bay = create_bay(station["id"])
    driver = create_driver(carrier["id"])
    return {"carrier": carrier, "station": station, "bay": bay, "driver": driver}


def setup_referred_overweight_screening(carrier_overrides=None, station_overrides=None,
                                        screening_overrides=None):
    """setup_domain + one REFERRED overweight screening (gross 86000 / axle 21000).

    Returns dict(carrier, station, bay, driver, screening).
    """
    d = setup_domain(carrier_overrides, station_overrides)
    screening = create_screening(
        d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
        **(screening_overrides or {}))
    d["screening"] = screening
    return d


def setup_inspection_finalized_oos(severity_weight=5, category="WEIGHT",
                                   carrier_overrides=None, station_overrides=None,
                                   screening_overrides=None, level="LEVEL_I",
                                   scheduled_start="2026-03-02T10:00:00Z",
                                   scheduled_end="2026-03-02T11:00:00Z"):
    """Full chain: active carrier -> overweight screening -> inspection with one OOS
    violation -> finalized OOS. Ready for citation issuance / reinspection.

    Returns dict(carrier, station, bay, driver, screening, inspection, violation).
    """
    d = setup_referred_overweight_screening(carrier_overrides, station_overrides, screening_overrides)
    inspection = create_inspection(
        d["screening"]["id"], d["bay"]["id"], level=level,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    violation = add_violation(inspection["id"], category=category, severity_weight=severity_weight, oos=True)
    inspection = finalize(inspection["id"], "OOS")
    d["inspection"] = inspection
    d["violation"] = violation
    return d


def setup_overweight_citation_assessed(officer_id="officer-1", **kwargs):
    """setup_inspection_finalized_oos + an ASSESSED OVERWEIGHT citation.

    Returns dict(..., citation).
    """
    d = setup_inspection_finalized_oos(**kwargs)
    citation = issue_citation(d["inspection"]["id"], d["carrier"]["id"],
                              kind="OVERWEIGHT", officer_id=officer_id)
    d["citation"] = citation
    return d


def setup_overweight_citation_contested(reason="contested", officer_id="officer-1", **kwargs):
    """ASSESSED OVERWEIGHT citation moved to CONTESTED by the owning CarrierRep.

    Returns dict(..., citation) where citation is in CONTESTED.
    """
    d = setup_overweight_citation_assessed(officer_id=officer_id, **kwargs)
    d["citation"] = contest_citation(d["citation"]["id"], d["carrier"]["id"], reason=reason)
    return d
