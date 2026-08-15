"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Standard timeline used across the fixtures: the rate schedule is created and
published while the logical clock is at its initial reading
(2026-08-01T00:00:00Z); the clock is then advanced to 2026-09-01 for adoption
(the thirty-day consultation minimum has elapsed and the countersign deadline
lands on 2026-10-01); activity is recorded at 2026-09-05 while the clock
stands at 2026-09-10; voting weights are snapshot with the clock at
2026-09-30 so the rolling twelve-month window contains the activity.

Identity threading: SignatoryAirline calls are entity-backed by Airline, so
every countersign / comment / vote / dispute / PFC call is made with
make_signatory_airline_headers(airline["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_AT_ACTIVITY,
    CLOCK_AT_ADOPT,
    CLOCK_AT_VOTING,
    CLOCK_PAST_DUE,
    DEFAULT_ACTIVITY_DATE,
)
from .factories import (
    create_activity_record_payload,
    create_airline_agreement_payload,
    create_airline_payload,
    create_capital_project_payload,
    create_fiscal_year_payload,
    create_rates_setting_payload,
    cast_vote_payload,
)
from .test_users import TEST_USERS, make_signatory_airline_headers

FINANCE = TEST_USERS["finance_headers"]
DIRECTOR = TEST_USERS["director_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and the logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock. Returns the reported current_utc dict."""
    return get_success_data(api_client.set_clock(to_iso8601, FINANCE))


def create_fiscal_year(year_label="FY2027", methodology="RESIDUAL", **overrides):
    payload = create_fiscal_year_payload(year_label=year_label,
                                         methodology=methodology, **overrides)
    return get_success_data(api_client.create_fiscal_year(payload, FINANCE))


def open_fiscal_year(fy_id):
    return get_success_data(api_client.open_fiscal_year(fy_id, FINANCE))


def create_and_open_fiscal_year(year_label="FY2027", methodology="RESIDUAL",
                                **overrides):
    """Create a fiscal year and transition it DRAFT -> OPEN."""
    fy = create_fiscal_year(year_label, methodology, **overrides)
    return open_fiscal_year(fy["id"])


def create_airline(iata_code, legal_name=None, carrier_class="PASSENGER",
                   pfc_approved=False):
    payload = create_airline_payload(
        iata_code=iata_code,
        legal_name=legal_name or f"{iata_code} Airlines",
        carrier_class=carrier_class,
        pfc_approved=pfc_approved,
    )
    return get_success_data(api_client.create_airline(payload, FINANCE))


def create_agreement(airline_id, fy_id, rented_space_sqft=0):
    payload = create_airline_agreement_payload(
        airline_id, fy_id, rented_space_sqft=rented_space_sqft)
    return get_success_data(api_client.create_airline_agreement(payload, FINANCE))


def create_rates_setting(fy_id):
    """Create a draft rate schedule, threading the year's current version (OCC)."""
    fy = get_success_data(api_client.get_fiscal_year(fy_id, FINANCE))
    payload = create_rates_setting_payload(fy["version"])
    return get_success_data(api_client.create_rates_setting(fy_id, payload,
                                                            FINANCE))


def publish_rates(rs_id):
    return get_success_data(api_client.publish_rates_setting(rs_id, FINANCE))


def adopt_rates(rs_id):
    return get_success_data(api_client.adopt_rates_setting(rs_id, DIRECTOR))


def countersign(agreement_id, airline_id):
    return get_success_data(api_client.countersign_agreement(
        agreement_id, make_signatory_airline_headers(airline_id)))


def add_activity(fy_id, airline_id, landed_weight_kg,
                 signature_status_at_activity="SIGNATORY",
                 activity_date=DEFAULT_ACTIVITY_DATE):
    """Record one landed-weight activity (clock first moved to 2026-09-10 so
    the activity date sits inside the year's window)."""
    set_clock(CLOCK_AT_ACTIVITY)
    payload = create_activity_record_payload(
        airline_id,
        activity_date=activity_date,
        landed_weight_kg=landed_weight_kg,
        signature_status_at_activity=signature_status_at_activity,
    )
    return get_success_data(api_client.create_activity_record(fy_id, payload,
                                                              FINANCE))


# ---------------------------------------------------------------------------
# Tier 2: the open-year workspace (year + carriers + adopted rate schedule)
# ---------------------------------------------------------------------------

def setup_open_year(year_label="FY2027", methodology="RESIDUAL",
                    airline_specs=(), **fy_overrides):
    """An OPEN fiscal year plus any requested carriers and their agreements.

    airline_specs: iterable of dicts with keys iata_code and optional
    legal_name / carrier_class / pfc_approved / rented_space_sqft.

    Returns a workspace dict: fy, airlines (iata -> airline), agreements
    (iata -> agreement), airline_headers (iata -> per-instance headers),
    rates_setting (None until adopt flow runs).
    """
    fy = create_and_open_fiscal_year(year_label, methodology, **fy_overrides)
    ws = {
        "fy": fy,
        "airlines": {},
        "agreements": {},
        "airline_headers": {},
        "rates_setting": None,
    }
    for spec in airline_specs:
        airline = create_airline(
            spec["iata_code"],
            legal_name=spec.get("legal_name"),
            carrier_class=spec.get("carrier_class", "PASSENGER"),
            pfc_approved=spec.get("pfc_approved", False),
        )
        ws["airlines"][airline["iata_code"]] = airline
        ws["airline_headers"][airline["iata_code"]] = (
            make_signatory_airline_headers(airline["id"]))
        ws["agreements"][airline["iata_code"]] = create_agreement(
            airline["id"], fy["id"],
            rented_space_sqft=spec.get("rented_space_sqft", 0))
    return ws


def adopt_rates_for_year(ws):
    """Create + publish a rate schedule on the workspace year, then adopt it
    after advancing the logical clock past the minimum consultation period."""
    rs = create_rates_setting(ws["fy"]["id"])
    rs = publish_rates(rs["id"])
    set_clock(CLOCK_AT_ADOPT)
    rs = adopt_rates(rs["id"])
    ws["rates_setting"] = rs
    return rs


def countersign_all(ws):
    """Countersign every agreement in the workspace (each as its own airline)."""
    for iata, agreement in ws["agreements"].items():
        ws["agreements"][iata] = countersign(agreement["id"],
                                             ws["airlines"][iata]["id"])
    return ws


def setup_signatory_year(year_label="FY2027", methodology="RESIDUAL",
                         airline_specs=(), **fy_overrides):
    """OPEN year + adopted rate schedule + every carrier countersigned."""
    ws = setup_open_year(year_label, methodology, airline_specs, **fy_overrides)
    adopt_rates_for_year(ws)
    countersign_all(ws)
    return ws


def setup_year_with_activity(year_label="FY2027", methodology="RESIDUAL",
                             airline_specs=(), activity_specs=(),
                             **fy_overrides):
    """Signatory workspace plus recorded activity.

    activity_specs: iterable of dicts with keys iata_code, landed_weight_kg and
    optional signature_status_at_activity / activity_date.
    """
    ws = setup_signatory_year(year_label, methodology, airline_specs,
                              **fy_overrides)
    ws["activity_records"] = []
    for spec in activity_specs:
        airline = ws["airlines"][spec["iata_code"]]
        record = add_activity(
            ws["fy"]["id"], airline["id"], spec["landed_weight_kg"],
            signature_status_at_activity=spec.get(
                "signature_status_at_activity", "SIGNATORY"),
            activity_date=spec.get("activity_date", DEFAULT_ACTIVITY_DATE),
        )
        ws["activity_records"].append(record)
    return ws


def refresh_fiscal_year(ws):
    ws["fy"] = get_success_data(api_client.get_fiscal_year(ws["fy"]["id"],
                                                           FINANCE))
    return ws["fy"]


def refresh_agreement(ws, iata):
    ws["agreements"][iata] = get_success_data(
        api_client.get_airline_agreement(ws["agreements"][iata]["id"], FINANCE))
    return ws["agreements"][iata]


# ---------------------------------------------------------------------------
# Tier 3: capital projects and majority-in-interest voting
# ---------------------------------------------------------------------------

def create_project(ws, project_name="Runway Rehab", cost_center="AIRFIELD",
                   budget_cents=5000000, mii_threshold_pct=50):
    payload = create_capital_project_payload(
        project_name=project_name, cost_center=cost_center,
        budget_cents=budget_cents, mii_threshold_pct=mii_threshold_pct)
    return get_success_data(api_client.create_capital_project(ws["fy"]["id"],
                                                              payload, FINANCE))


def open_voting(project_id):
    """Move a project to MII_VOTING. The clock is advanced to 2026-09-30 first
    so the rolling twelve-month activity window contains the recorded
    activity when voting weights are snapshot."""
    set_clock(CLOCK_AT_VOTING)
    return get_success_data(api_client.open_voting(project_id, FINANCE))


def cast_vote(ws, project_id, iata, ballot="APPROVE"):
    payload = cast_vote_payload(ws["airlines"][iata]["id"], ballot=ballot)
    return api_client.cast_mii_vote(project_id, payload,
                                    ws["airline_headers"][iata])


def setup_mii_voting(year_label="FY_MII", airline_specs=(), activity_specs=(),
                     mii_threshold_pct=50, project_name="Runway Rehab",
                     **fy_overrides):
    """Signatory workspace + activity + one project in MII_VOTING.

    Returns (workspace, project).
    """
    ws = setup_year_with_activity(year_label, "RESIDUAL", airline_specs,
                                  activity_specs, **fy_overrides)
    project = create_project(ws, project_name=project_name,
                             mii_threshold_pct=mii_threshold_pct)
    project = open_voting(project["id"])
    return ws, project


def get_project(project_id):
    return get_success_data(api_client.get_capital_project(project_id, FINANCE))


# ---------------------------------------------------------------------------
# Tier 4: settlement lifecycle
# ---------------------------------------------------------------------------

def compute_settlement(ws):
    settlement = get_success_data(api_client.compute_settlement(ws["fy"]["id"],
                                                                FINANCE))
    ws["settlement"] = settlement
    return settlement


def list_lines(settlement_id):
    return get_success_data(api_client.list_settlement_lines(settlement_id,
                                                             FINANCE))


def publish_review(ws):
    settlement = get_success_data(api_client.publish_review(
        ws["settlement"]["id"], FINANCE))
    ws["settlement"] = settlement
    ws["lines"] = list_lines(settlement["id"])
    return settlement


def setup_computed_settlement(year_label="FY_SET", airline_specs=(),
                              activity_specs=(), **fy_overrides):
    """Signatory workspace with activity and a COMPUTED settlement."""
    ws = setup_year_with_activity(year_label, "RESIDUAL", airline_specs,
                                  activity_specs, **fy_overrides)
    compute_settlement(ws)
    return ws


def setup_settlement_in_review(year_label="FY_REV", airline_specs=(),
                               activity_specs=(), **fy_overrides):
    """COMPUTED settlement published to the carriers (AIRLINE_REVIEW), with
    every line stamped PENDING."""
    ws = setup_computed_settlement(year_label, airline_specs, activity_specs,
                                   **fy_overrides)
    publish_review(ws)
    return ws


def pay_all_lines(ws, outcome="PAID"):
    """Record payment on every line of the workspace settlement."""
    ws["lines"] = list_lines(ws["settlement"]["id"])
    for line in ws["lines"]:
        get_success_data(api_client.record_payment(line["id"],
                                                   {"outcome": outcome},
                                                   FINANCE))
    ws["lines"] = list_lines(ws["settlement"]["id"])
    return ws["lines"]


def setup_finalized_year(year_label="FY_FIN", airline_specs=(),
                         activity_specs=(), **fy_overrides):
    """Full lifecycle through FINALIZED: settlement in AIRLINE_REVIEW, every
    line PAID, then finalized by the director (year closes)."""
    ws = setup_settlement_in_review(year_label, airline_specs, activity_specs,
                                    **fy_overrides)
    pay_all_lines(ws)
    settlement = get_success_data(api_client.finalize_settlement(
        ws["settlement"]["id"], DIRECTOR))
    ws["settlement"] = settlement
    return ws
