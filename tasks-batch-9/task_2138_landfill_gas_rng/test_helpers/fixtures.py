"""Composite setup helpers.

Most interesting claims in this API need the system in a state that takes
between five and twenty calls to reach: a host landfill, a wellfield producing
enough collected flow to sustain upgrading, an upgrading skid, an active
offtake contract, a confirmed gas-day nomination, a batch of product gas walked
through spec analysis, attachment and injection, and only then the thing under
test. These helpers encapsulate those preambles.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only — the database is empty at the start of every test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    create_attribute_batch_payload,
    create_compliance_report_payload,
    create_injection_batch_payload,
    create_nomination_payload,
    create_offtake_contract_payload,
    create_plant_payload,
    create_royalty_statement_payload,
    create_site_payload,
    create_well_payload,
    create_work_order_payload,
    good_reading_payload,
)
from .test_users import (
    OFFICER_ALICE,
    OFFICER_BOB,
    TEST_USERS,
    make_compliance_officer_headers,
)

ADMIN = TEST_USERS["project_admin_headers"]
TECH = TEST_USERS["wellfield_technician_headers"]
OPERATOR = TEST_USERS["plant_operator_headers"]
SCHEDULER = TEST_USERS["commercial_scheduler_headers"]


# ─── Tier 0: single-call primitives ───────────────────

def set_clock(to_iso8601: str) -> None:
    """Move the logical clock. Mutates no entity."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_site(**overrides) -> dict:
    return get_success_data(
        api_client.create_site(create_site_payload(**overrides), ADMIN)
    )


def read_site(site_id: str) -> dict:
    return get_success_data(api_client.get_site(site_id, ADMIN))


def site_version(site_id: str) -> int:
    return read_site(site_id)["version"]


def create_plant(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_plant(create_plant_payload(site_id, **overrides), ADMIN)
    )


def read_plant(plant_id: str) -> dict:
    return get_success_data(api_client.get_plant(plant_id, ADMIN))


def create_well(site_id: str, well_code: str = "W-01", **overrides) -> dict:
    return get_success_data(
        api_client.create_well(
            create_well_payload(site_id, well_code=well_code, **overrides), ADMIN
        )
    )


def read_well(well_id: str) -> dict:
    return get_success_data(api_client.get_well(well_id, ADMIN))


def post_reading(well_id: str, payload: dict, headers: dict = None) -> dict:
    return get_success_data(
        api_client.create_reading(well_id, payload, headers or TECH)
    )


def post_good_reading(well_id: str, taken_at: str, flow_scfm: float = 480.0) -> dict:
    return post_reading(well_id, good_reading_payload(taken_at, flow_scfm=flow_scfm))


def set_well_state(well_id: str, to_state: str, reason: str = None) -> dict:
    payload = {"to_state": to_state}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.set_well_status(well_id, payload, TECH))


def set_plant_mode(plant_id: str, **dimensions) -> dict:
    """Advance either independent state dimension: process_mode, spec_status or both."""
    return get_success_data(
        api_client.set_plant_status(plant_id, dict(dimensions), OPERATOR)
    )


def read_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_offtake_contract(contract_id, SCHEDULER))


def contract_version(contract_id: str) -> int:
    return read_contract(contract_id)["version"]


def read_nomination(nomination_id: str) -> dict:
    return get_success_data(api_client.get_nomination(nomination_id, SCHEDULER))


def read_injection_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_injection_batch(batch_id, OPERATOR))


def read_attribute_batch(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_attribute_batch(batch_id, headers or ADMIN))


def read_compliance_report(report_id: str) -> dict:
    return get_success_data(api_client.get_compliance_report(report_id, ADMIN))


def read_royalty_statement(statement_id: str) -> dict:
    return get_success_data(api_client.get_royalty_statement(statement_id, ADMIN))


def read_energy_balance(site_id: str) -> dict:
    return get_success_data(api_client.get_energy_balance(site_id, ADMIN))


# ─── Tier 1: state progression ────────────────────────

def create_active_contract(site_id: str, **overrides) -> dict:
    """Create an offtake contract and activate it. Returns the ACTIVE contract,
    whose `version` has already advanced past creation."""
    contract = get_success_data(
        api_client.create_offtake_contract(
            create_offtake_contract_payload(site_id, **overrides), SCHEDULER
        )
    )
    return get_success_data(
        api_client.set_contract_status(contract["id"], {"to_status": "ACTIVE"}, SCHEDULER)
    )


def create_nomination(contract_id: str, plant_id: str, **overrides) -> dict:
    """Write a gas-day nomination, echoing the contract's current version."""
    expected = overrides.pop(
        "expected_contract_version", contract_version(contract_id)
    )
    return get_success_data(
        api_client.create_nomination(
            create_nomination_payload(contract_id, plant_id, expected, **overrides),
            SCHEDULER,
        )
    )


def create_confirmed_nomination(contract_id: str, plant_id: str, **overrides) -> dict:
    nomination = create_nomination(contract_id, plant_id, **overrides)
    return get_success_data(
        api_client.set_nomination_status(
            nomination["id"], {"to_status": "CONFIRMED"}, SCHEDULER
        )
    )


def create_batch(plant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_injection_batch(
            create_injection_batch_payload(plant_id, **overrides), OPERATOR
        )
    )


def analyse_batch(batch_id: str) -> dict:
    """DRAFT -> PENDING_ANALYSIS; the batch lands on ON_SPEC or OFF_SPEC in the
    same response."""
    return get_success_data(
        api_client.set_injection_batch_status(
            batch_id, {"to_status": "PENDING_ANALYSIS"}, OPERATOR
        )
    )


def attach_batch(batch_id: str, nomination_id: str) -> dict:
    return get_success_data(
        api_client.set_injection_batch_status(
            batch_id,
            {"to_status": "NOMINATED", "nomination_id": nomination_id},
            SCHEDULER,
        )
    )


def inject_batch(batch_id: str) -> dict:
    return get_success_data(
        api_client.set_injection_batch_status(
            batch_id, {"to_status": "INJECTED"}, OPERATOR
        )
    )


def divert_batch(batch_id: str) -> dict:
    return get_success_data(
        api_client.set_injection_batch_status(
            batch_id, {"to_status": "DIVERTED_TO_FLARE"}, OPERATOR
        )
    )


def generate_attribute_batch(
    injection_batch_id: str, officer: str = OFFICER_ALICE, **overrides
) -> dict:
    return get_success_data(
        api_client.create_attribute_batch(
            create_attribute_batch_payload(injection_batch_id, **overrides),
            make_compliance_officer_headers(officer),
        )
    )


def open_downtime_event(plant_id: str, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "start_at": "2026-08-02T00:00:00Z",
        "cause": "COMPRESSOR_TRIP",
        "disposition": "FLARED",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_downtime_event(payload, OPERATOR))


def close_downtime_event(event_id: str, end_at: str, **overrides) -> dict:
    payload = {"end_at": end_at}
    payload.update(overrides)
    return get_success_data(
        api_client.close_downtime_event(event_id, payload, OPERATOR)
    )


def create_closed_downtime(plant_id: str, start_at: str, end_at: str, **overrides) -> dict:
    """Open a downtime record and close it in one step."""
    close_overrides = {
        key: overrides.pop(key)
        for key in ("flared_mmbtu", "vented_mmbtu")
        if key in overrides
    }
    event = open_downtime_event(plant_id, start_at=start_at, **overrides)
    return close_downtime_event(event["id"], end_at, **close_overrides)


# ─── Tier 2: entity hierarchy ─────────────────────────

def setup_site_with_wellfield(
    clock: str = BASE_CLOCK_UTC,
    site_overrides: dict = None,
    plant_overrides: dict = None,
    flows=(480.0, 470.0),
    reading_at: str = "2026-08-10T01:00:00Z",
    with_readings: bool = True,
    with_plant: bool = True,
) -> dict:
    """Host landfill + an upgrading skid still in STARTUP + a two-well wellfield.

    With the default flows each well takes one GOOD reading, so the site's
    collected_flow_scfm reaches 950.0 — above the plant's 900.0 minimum feed.
    Returns {"site", "plant", "wells"}.
    """
    set_clock(clock)
    site = create_site(**(site_overrides or {}))
    plant = create_plant(site["id"], **(plant_overrides or {})) if with_plant else None
    wells = [
        create_well(site["id"], well_code=f"W-{index:02d}")
        for index in range(1, len(flows) + 1)
    ]
    if with_readings:
        for well, flow in zip(wells, flows):
            post_good_reading(well["id"], reading_at, flow_scfm=flow)
    return {"site": site, "plant": plant, "wells": wells}


def setup_upgrading_plant(**kwargs) -> dict:
    """The wellfield above, with the skid moved into process_mode UPGRADING."""
    context = setup_site_with_wellfield(**kwargs)
    context["plant"] = set_plant_mode(
        context["plant"]["id"], process_mode="UPGRADING"
    )
    return context


def setup_commercial_desk(
    nomination_overrides: dict = None, contract_overrides: dict = None, **kwargs
) -> dict:
    """An upgrading skid plus an ACTIVE offtake contract and a CONFIRMED
    gas-day nomination against it. Returns the wellfield context extended with
    {"contract", "nomination"}."""
    context = setup_upgrading_plant(**kwargs)
    contract = create_active_contract(
        context["site"]["id"], **(contract_overrides or {})
    )
    nomination = create_confirmed_nomination(
        contract["id"], context["plant"]["id"], **(nomination_overrides or {})
    )
    context["contract"] = contract
    context["nomination"] = nomination
    return context


# ─── Tier 3: full product-gas lifecycle shortcuts ─────

def setup_on_spec_batch(batch_overrides: dict = None, **kwargs) -> dict:
    """Upgrading skid with one batch of product gas analysed to ON_SPEC.

    The canonical block — three hours of 115.0 mscf at 97.4 % methane — freezes
    gross_mmbtu at 340.14. Returns the context extended with {"batch"}.
    """
    context = setup_upgrading_plant(**kwargs)
    batch = create_batch(context["plant"]["id"], **(batch_overrides or {}))
    context["batch"] = analyse_batch(batch["id"])
    return context


def setup_nominated_batch(batch_overrides: dict = None, **kwargs) -> dict:
    """Commercial desk plus one ON_SPEC batch attached to the nomination."""
    context = setup_commercial_desk(**kwargs)
    batch = create_batch(context["plant"]["id"], **(batch_overrides or {}))
    analyse_batch(batch["id"])
    context["batch"] = attach_batch(batch["id"], context["nomination"]["id"])
    return context


def setup_injected_batch(batch_overrides: dict = None, **kwargs) -> dict:
    """The workhorse: one batch of product gas driven all the way to INJECTED.

    Walks site -> wellfield readings -> plant UPGRADING -> ACTIVE contract ->
    CONFIRMED nomination -> batch created -> analysed ON_SPEC -> attached ->
    injected. Afterwards the site's energy_injected_mmbtu and
    energy_produced_mmbtu both read the batch's gross_mmbtu.
    Returns {"site", "plant", "wells", "contract", "nomination", "batch"}.
    """
    context = setup_nominated_batch(batch_overrides=batch_overrides, **kwargs)
    context["batch"] = inject_batch(context["batch"]["id"])
    return context


def setup_diverted_batch(batch_overrides: dict = None, **kwargs) -> dict:
    """One batch analysed ON_SPEC and then sent to the flare, so the site's
    energy_flared_mmbtu carries it and no INJECTED batch exists."""
    context = setup_on_spec_batch(batch_overrides=batch_overrides, **kwargs)
    context["batch"] = divert_batch(context["batch"]["id"])
    return context


def setup_off_spec_plant(**kwargs) -> dict:
    """A batch whose methane content is below the injection spec is analysed to
    OFF_SPEC, which pushes the plant's spec dimension to OFF_SPEC too.
    Returns the context extended with {"off_spec_batch"}."""
    context = kwargs.pop("context", None) or setup_upgrading_plant(**kwargs)
    batch = get_success_data(
        api_client.create_injection_batch(
            {
                "plant_id": context["plant"]["id"],
                "interval_start": "2026-08-10T06:00:00Z",
                "interval_end": "2026-08-10T08:00:00Z",
                "hourly_volumes_mscf": [110.0, 110.0],
                "methane_pct": 94.0,
                "oxygen_pct": 0.1,
                "co2_pct": 1.4,
            },
            OPERATOR,
        )
    )
    context["off_spec_batch"] = analyse_batch(batch["id"])
    context["plant"] = read_plant(context["plant"]["id"])
    return context


# ─── Tier 4: maintenance and condensate ───────────────

def setup_work_order_in_progress(
    well_id: str,
    work_type: str = "SUMP_PUMP_SERVICE",
    window_start: str = "2026-08-09T00:00:00Z",
    window_end: str = "2026-08-11T00:00:00Z",
) -> dict:
    """Plan a maintenance job whose window contains the logical clock and start
    it, which locks the well out."""
    work_order = get_success_data(
        api_client.create_work_order(
            create_work_order_payload(
                well_id,
                work_type=work_type,
                window_start=window_start,
                window_end=window_end,
            ),
            TECH,
        )
    )
    return get_success_data(
        api_client.set_work_order_status(
            work_order["id"], {"to_status": "IN_PROGRESS"}, TECH
        )
    )


# ─── Tier 5: compliance filings and settlement ────────

def create_compliance_report(
    site_id: str, officer: str = OFFICER_ALICE, **overrides
) -> dict:
    return get_success_data(
        api_client.create_compliance_report(
            create_compliance_report_payload(site_id, **overrides),
            make_compliance_officer_headers(officer),
        )
    )


def drive_report(report_id: str, officer: str, **payload) -> dict:
    return get_success_data(
        api_client.set_compliance_report_status(
            report_id, dict(payload), make_compliance_officer_headers(officer)
        )
    )


def setup_report_under_review(
    site_id: str,
    preparer: str = OFFICER_ALICE,
    reviewer: str = OFFICER_BOB,
    **overrides,
) -> dict:
    """Open a filing, submit it as its preparer, and take it under review as a
    different officer — segregation of duties forbids the same seat twice."""
    report = create_compliance_report(site_id, officer=preparer, **overrides)
    drive_report(report["id"], preparer, to_status="SUBMITTED")
    return drive_report(report["id"], reviewer, to_status="UNDER_REVIEW")


def setup_accepted_report(
    site_id: str,
    preparer: str = OFFICER_ALICE,
    reviewer: str = OFFICER_BOB,
    **overrides,
) -> dict:
    """Walk a filing all the way to ACCEPTED, which is what unlocks separation
    for the site's attribute batches of that period."""
    report = setup_report_under_review(
        site_id, preparer=preparer, reviewer=reviewer, **overrides
    )
    return drive_report(report["id"], reviewer, to_status="ACCEPTED")


def create_royalty_statement(site_id: str, **overrides) -> dict:
    """Raise a settlement statement, echoing the site's current version."""
    expected = overrides.pop("expected_site_version", site_version(site_id))
    return get_success_data(
        api_client.create_royalty_statement(
            create_royalty_statement_payload(site_id, expected, **overrides), ADMIN
        )
    )


def issue_royalty_statement(statement_id: str) -> dict:
    return get_success_data(
        api_client.set_royalty_statement_status(
            statement_id, {"to_status": "ISSUED"}, ADMIN
        )
    )


def setup_issued_statement(site_id: str, **overrides) -> dict:
    statement = create_royalty_statement(site_id, **overrides)
    return issue_royalty_statement(statement["id"])


# ─── Convenience over the standard defaults ───────────

DEFAULT_MIN_FEED_SCFM = TEST_DEFAULTS["MIN_FEED_SCFM"]
DEFAULT_TARGET_FLOW_SCFM = TEST_DEFAULTS["WELL_TARGET_FLOW_SCFM"]
