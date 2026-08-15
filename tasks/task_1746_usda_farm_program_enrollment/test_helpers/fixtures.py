"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. Setup calls use get_success_data() so that
a setup failure surfaces as a clear "Setup failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import OBSERVATION_YEARS, SAFE_CLOCK, TEST_DEFAULTS
from .factories import (
    compute_payment_payload,
    create_acreage_report_line_payload,
    create_acreage_report_payload,
    create_appeal_payload,
    create_disaster_application_payload,
    create_enrollment_payload,
    create_farm_payload,
    create_field_payload,
    create_membership_payload,
    create_producer_payload,
    create_program_election_payload,
    create_tract_payload,
    create_yield_record_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_county_committee_headers,
    make_producer_headers,
)

SPECIALIST = TEST_USERS["county_specialist_headers"]
CED = TEST_USERS["county_executive_director_headers"]


def _ok(resp, what: str):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed ({what}): expected object, got {data!r}"
    return data


def set_clock(to_iso8601: str = SAFE_CLOCK):
    """Advance the logical clock (PRD §2.9). Returns the clock payload."""
    return _ok(
        api_client.set_clock(set_clock_payload(to_iso8601), SPECIALIST),
        f"set_clock({to_iso8601})",
    )


# ---------------------------------------------------------------------------
# Tier 1/2: base records and the farm hierarchy
# ---------------------------------------------------------------------------

def create_farm(**overrides):
    return _ok(
        api_client.create_farm(create_farm_payload(**overrides), SPECIALIST),
        "create_farm",
    )


def create_producer(**overrides):
    return _ok(
        api_client.create_producer(create_producer_payload(**overrides), SPECIALIST),
        "create_producer",
    )


def add_membership(farm_id, producer_id, share_percent=100.00, is_spouse_pair=False):
    return _ok(
        api_client.create_membership(
            farm_id,
            create_membership_payload(
                producer_id=producer_id,
                share_percent=share_percent,
                is_spouse_pair=is_spouse_pair,
            ),
            SPECIALIST,
        ),
        "add_membership",
    )


def add_tract(farm_id, tract_number="T1", base_acres=100.00, cropland_acres=100.00):
    return _ok(
        api_client.create_tract(
            farm_id,
            create_tract_payload(
                tract_number=tract_number,
                base_acres=base_acres,
                cropland_acres=cropland_acres,
            ),
            SPECIALIST,
        ),
        "add_tract",
    )


def add_field(tract_id, field_number="1", acres=100.00):
    return _ok(
        api_client.create_field(
            tract_id,
            create_field_payload(field_number=field_number, acres=acres),
            SPECIALIST,
        ),
        "add_field",
    )


def get_farm_version(farm_id) -> int:
    farm = _ok(api_client.get_farm(farm_id, SPECIALIST), "get_farm")
    return farm["version"]


def create_farm_with_member(farm_overrides=None, producer_overrides=None, share=100.00):
    """Farm + producer + ACTIVE membership. Returns (farm, producer, membership)."""
    farm = create_farm(**(farm_overrides or {}))
    producer = create_producer(**(producer_overrides or {}))
    membership = add_membership(farm["id"], producer["id"], share_percent=share)
    return farm, producer, membership


# ---------------------------------------------------------------------------
# Tier 3: yield record lifecycle
# ---------------------------------------------------------------------------

def create_yield_record_with_observations(
    farm_id, commodity="CORN", yields=(180.0, 180.0, 180.0, 180.0, 180.0)
):
    """Yield record + one observation per trailing year.

    `yields` is a 5-tuple aligned to OBSERVATION_YEARS (2021..2025); a None
    entry appends an explicit null (plug-year) observation.
    Returns the YieldRecord."""
    record = _ok(
        api_client.create_yield_record(
            farm_id, create_yield_record_payload(commodity=commodity), SPECIALIST
        ),
        "create_yield_record",
    )
    for year, value in zip(OBSERVATION_YEARS, yields):
        payload = {"crop_year": year, "actual_yield_bu_per_acre": value}
        _ok(
            api_client.append_yield_observation(record["id"], payload, SPECIALIST),
            f"append_observation({year})",
        )
    return record


def update_and_certify_yield_record(record_id, producer_id):
    """One-time APH update by the member producer, then specialist certification."""
    _ok(
        api_client.trigger_yield_update(record_id, make_producer_headers(producer_id)),
        "trigger_yield_update",
    )
    return _ok(
        api_client.certify_yield_record(record_id, SPECIALIST),
        "certify_yield_record",
    )


# ---------------------------------------------------------------------------
# Tier 3: acreage report lifecycle
# ---------------------------------------------------------------------------

def create_certified_acreage_report(
    farm_id,
    producer_id,
    field_id,
    program_year=2026,
    crop_code="CORN",
    planted_acres=100.00,
    prevented_planted_acres=0.00,
    file_clock=SAFE_CLOCK,
    certify=True,
):
    """Open a report, add one line, file at `file_clock`, optionally certify.

    The clock is moved to `file_clock` for the filing and then restored to
    SAFE_CLOCK so downstream deadline-gated calls behave. Returns
    ``(report, filed_snapshot)`` — the report re-read after the last
    completed step, and the file-endpoint response capturing the status at
    filing time (FILED vs LATE_FILED per PRD §3.3) before any certification
    transition."""
    producer_headers = make_producer_headers(producer_id)
    report = _ok(
        api_client.create_acreage_report(
            farm_id, create_acreage_report_payload(program_year=program_year), producer_headers
        ),
        "create_acreage_report",
    )
    _ok(
        api_client.add_acreage_report_line(
            report["id"],
            create_acreage_report_line_payload(
                field_id=field_id,
                crop_code=crop_code,
                planted_acres=planted_acres,
                prevented_planted_acres=prevented_planted_acres,
            ),
            producer_headers,
        ),
        "add_acreage_report_line",
    )
    set_clock(file_clock)
    filed = _ok(
        api_client.file_acreage_report(report["id"], producer_headers),
        "file_acreage_report",
    )
    set_clock(SAFE_CLOCK)
    if certify:
        _ok(
            api_client.certify_acreage_report(report["id"], SPECIALIST),
            "certify_acreage_report",
        )
        report = _ok(
            api_client.get_acreage_report(report["id"], SPECIALIST),
            "get_acreage_report",
        )
    else:
        report = filed
    return report, filed


# ---------------------------------------------------------------------------
# Tier 3: program election
# ---------------------------------------------------------------------------

def create_active_election(
    farm_id, producer_id, program_year=2026, commodity="CORN", election_code="PLC"
):
    """Create an ACTIVE election, reading the live Farm.version first (OCC)."""
    version = get_farm_version(farm_id)
    return _ok(
        api_client.create_program_election(
            farm_id,
            create_program_election_payload(
                program_year=program_year,
                commodity=commodity,
                election_code=election_code,
                expected_farm_version=version,
            ),
            make_producer_headers(producer_id),
        ),
        "create_program_election",
    )


# ---------------------------------------------------------------------------
# Tier 3: producer compliance gates
# ---------------------------------------------------------------------------

def file_agi_attestation(producer_id, agi_cents=50_000_000):
    return _ok(
        api_client.file_agi_attestation(
            producer_id,
            {"adjusted_gross_income": agi_cents},
            make_producer_headers(producer_id),
        ),
        "file_agi_attestation",
    )


def verify_agi(producer_id):
    return _ok(
        api_client.verify_agi_attestation(producer_id, SPECIALIST),
        "verify_agi_attestation",
    )


def certify_conservation(producer_id):
    return _ok(
        api_client.file_conservation_certification(
            producer_id, {}, make_producer_headers(producer_id)
        ),
        "file_conservation_certification",
    )


# ---------------------------------------------------------------------------
# Tier 3/4/5: the full enrollment pipeline
# ---------------------------------------------------------------------------

def setup_enrollment_pipeline(
    *,
    farm_overrides=None,
    base_acres=100.00,
    field_acres=None,
    planted_acres=100.00,
    commodity="CORN",
    program_year=2026,
    yields=(180.0, 180.0, 180.0, 180.0, 180.0),
    election_code="PLC",
    agi_cents=50_000_000,
    file_agi=True,
    verify_agi_attestation=True,
    certify_conservation_status=True,
    certify_report=True,
    file_clock=SAFE_CLOCK,
    stop_at="certified",
    compute_inputs=None,
):
    """Full mainline setup: farm, two producers (appellant P + committee
    reviewer Q), membership, tract/field, certified yield record, acreage
    report, ACTIVE election, compliance gates, and an enrollment walked to
    `stop_at` ("created" | "submitted" | "ced_approved" | "certified" |
    "payment_computed").

    Returns a context dict with every entity and the headers to act as them.
    """
    set_clock(SAFE_CLOCK)
    farm = create_farm(
        **(farm_overrides or {"farm_number": "FX", "county_code": TEST_DEFAULTS["COUNTY_CODE"],
                              "program_year": program_year})
    )
    producer = create_producer(producer_name="Appellant Producer")
    reviewer = create_producer(producer_name="Committee Reviewer")
    add_membership(farm["id"], producer["id"], share_percent=100.00)
    tract = add_tract(farm["id"], base_acres=base_acres, cropland_acres=base_acres)
    field = add_field(tract["id"], acres=field_acres if field_acres is not None else base_acres)

    producer_headers = make_producer_headers(producer["id"])
    committee_headers = make_county_committee_headers(reviewer["id"])

    yield_record = create_yield_record_with_observations(
        farm["id"], commodity=commodity, yields=yields
    )
    update_and_certify_yield_record(yield_record["id"], producer["id"])
    yield_record = _ok(
        api_client.get_yield_record(yield_record["id"], SPECIALIST), "get_yield_record"
    )

    report, filed_report = create_certified_acreage_report(
        farm["id"],
        producer["id"],
        field["id"],
        program_year=program_year,
        crop_code=commodity,
        planted_acres=planted_acres,
        file_clock=file_clock,
        certify=certify_report,
    )

    election = create_active_election(
        farm["id"], producer["id"], program_year=program_year,
        commodity=commodity, election_code=election_code,
    )

    if file_agi:
        file_agi_attestation(producer["id"], agi_cents=agi_cents)
        if verify_agi_attestation:
            verify_agi(producer["id"])
    if certify_conservation_status:
        certify_conservation(producer["id"])

    enrollment = _ok(
        api_client.create_enrollment(
            farm["id"],
            create_enrollment_payload(program_year=program_year, commodity=commodity),
            producer_headers,
        ),
        "create_enrollment",
    )

    if stop_at in ("submitted", "ced_approved", "certified", "payment_computed"):
        enrollment = _ok(
            api_client.submit_enrollment(enrollment["id"], producer_headers),
            "submit_enrollment",
        )
    if stop_at in ("ced_approved", "certified", "payment_computed"):
        enrollment = _ok(
            api_client.ced_approve_enrollment(enrollment["id"], CED),
            "ced_approve_enrollment",
        )
    if stop_at in ("certified", "payment_computed"):
        enrollment = _ok(
            api_client.certify_enrollment(enrollment["id"], committee_headers),
            "certify_enrollment",
        )
    if stop_at == "payment_computed":
        enrollment = _ok(
            api_client.compute_payment(
                enrollment["id"],
                compute_inputs or compute_payment_payload(),
                SPECIALIST,
            ),
            "compute_payment",
        )

    return {
        "farm": farm,
        "producer": producer,
        "reviewer": reviewer,
        "producer_headers": producer_headers,
        "committee_headers": committee_headers,
        "specialist_headers": SPECIALIST,
        "ced_headers": CED,
        "tract": tract,
        "field": field,
        "yield_record": yield_record,
        "acreage_report": report,
        "acreage_report_at_filing": filed_report,
        "election": election,
        "enrollment": enrollment,
    }


def setup_certified_enrollment(**kwargs):
    """Pipeline through CERTIFIED (election + yield record pinned and LOCKED)."""
    kwargs["stop_at"] = "certified"
    return setup_enrollment_pipeline(**kwargs)


def setup_payment_computed_enrollment(**kwargs):
    """Pipeline through PAYMENT_COMPUTED with the given market inputs."""
    kwargs["stop_at"] = "payment_computed"
    return setup_enrollment_pipeline(**kwargs)


# ---------------------------------------------------------------------------
# Tier 5: disaster applications
# ---------------------------------------------------------------------------

def setup_disaster_under_review(
    ctx=None,
    *,
    loss_acres=40.00,
    disaster_type="DROUGHT",
    qualifying_commodity="CORN",
    documentation_complete=True,
    pipeline_kwargs=None,
):
    """A disaster application walked to UNDER_REVIEW.

    Reuses an existing pipeline context when given, otherwise builds a minimal
    farm + certified acreage report scenario. Returns (ctx, application)."""
    if ctx is None:
        set_clock(SAFE_CLOCK)
        farm, producer, _membership = create_farm_with_member()
        reviewer = create_producer(producer_name="Committee Reviewer")
        tract = add_tract(farm["id"])
        field = add_field(tract["id"])
        producer_headers = make_producer_headers(producer["id"])
        report, _filed = create_certified_acreage_report(
            farm["id"], producer["id"], field["id"]
        )
        ctx = {
            "farm": farm,
            "producer": producer,
            "reviewer": reviewer,
            "producer_headers": producer_headers,
            "committee_headers": make_county_committee_headers(reviewer["id"]),
            "specialist_headers": SPECIALIST,
            "ced_headers": CED,
            "tract": tract,
            "field": field,
            "acreage_report": report,
        }
    application = _ok(
        api_client.create_disaster_application(
            ctx["farm"]["id"],
            create_disaster_application_payload(
                disaster_type=disaster_type,
                loss_acres=loss_acres,
                qualifying_commodity=qualifying_commodity,
                documentation_complete=documentation_complete,
            ),
            ctx["producer_headers"],
        ),
        "create_disaster_application",
    )
    _ok(
        api_client.file_disaster_application(application["id"], ctx["producer_headers"]),
        "file_disaster_application",
    )
    application = _ok(
        api_client.assign_disaster_reviewer(application["id"], CED),
        "assign_disaster_reviewer",
    )
    return ctx, application


# ---------------------------------------------------------------------------
# Tier 5: appeals
# ---------------------------------------------------------------------------

def setup_appeal_at_committee(ctx, ground_code="FACTUAL_ERROR"):
    """File an appeal against the ctx enrollment and walk it to
    COMMITTEE_HEARING with the ctx reviewer assigned. Returns the appeal."""
    appeal = _ok(
        api_client.file_appeal(
            create_appeal_payload(
                farm_id=ctx["farm"]["id"],
                enrollment_id=ctx["enrollment"]["id"],
                ground_code=ground_code,
                filed_by_producer_id=ctx["producer"]["id"],
            ),
            ctx["producer_headers"],
        ),
        "file_appeal",
    )
    _ok(api_client.assign_appeal_ced(appeal["id"], CED), "assign_appeal_ced")
    appeal = _ok(
        api_client.refer_appeal_to_committee(
            appeal["id"],
            {"assigned_reviewer_producer_id": ctx["reviewer"]["id"]},
            CED,
        ),
        "refer_appeal_to_committee",
    )
    return appeal
