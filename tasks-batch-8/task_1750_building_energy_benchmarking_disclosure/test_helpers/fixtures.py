"""
Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts against
an empty database). Setup calls use the lenient get_success_data() validator so
a setup failure surfaces as a clear "Setup step failed" error.

Identity threading: entity-backed roles always use the per-instance builders
(make_owner_headers / make_tenant_rep_headers / make_verifier_headers) with the
actual entity id, never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_UNIT_SPECS
from .factories import (
    create_benchmark_report_payload,
    create_building_payload,
    create_cycle_payload,
    create_exemption_request_payload,
    create_owner_payload,
    create_tenant_unit_payload,
    create_usage_record_payload,
    create_utility_account_payload,
    create_verification_record_payload,
    create_verifier_payload,
    grant_consent_payload,
)
from .test_users import (
    TEST_USERS,
    make_owner_headers,
    make_tenant_rep_headers,
    make_verifier_headers,
)

OFFICER = TEST_USERS["officer_headers"]
OFFICER2 = TEST_USERS["officer2_headers"]
UTILITY = TEST_USERS["utility_agent_headers"]


# ─── Tier 0: single-call primitives ──────────────────────────────────────────

def create_owner(officer_headers=OFFICER, **overrides) -> dict:
    """Register a building owner (PRD §3.1)."""
    return get_success_data(
        api_client.create_owner(create_owner_payload(**overrides), officer_headers)
    )


def create_verifier(officer_headers=OFFICER, **overrides) -> dict:
    """Register an accredited data verifier (PRD §3.1)."""
    return get_success_data(
        api_client.create_verifier(create_verifier_payload(**overrides), officer_headers)
    )


def create_cycle(officer_headers=OFFICER, **overrides) -> dict:
    """Create a reporting cycle (stays SCHEDULED)."""
    return get_success_data(
        api_client.create_reporting_cycle(create_cycle_payload(**overrides), officer_headers)
    )


def open_cycle(cycle_id, officer_headers=OFFICER) -> dict:
    return get_success_data(api_client.open_reporting_cycle(cycle_id, officer_headers))


def create_and_open_cycle(officer_headers=OFFICER, **overrides) -> dict:
    """Create a reporting cycle and open it for filings (PRD §3.1)."""
    cycle = create_cycle(officer_headers, **overrides)
    return open_cycle(cycle["id"], officer_headers)


def create_building(owner_id, **overrides) -> dict:
    """Register a building; owner_id self-assigned from the caller header (PRD §3.2)."""
    return get_success_data(
        api_client.create_building(
            create_building_payload(**overrides), make_owner_headers(owner_id)
        )
    )


def add_tenant_units(building_id, owner_id, specs=None) -> list:
    """Add tenant units. specs: list of (unit_label, floor_area_sqft, space_type)."""
    specs = DEFAULT_UNIT_SPECS if specs is None else specs
    headers = make_owner_headers(owner_id)
    units = []
    for label, area, space_type in specs:
        units.append(
            get_success_data(
                api_client.create_tenant_unit(
                    building_id,
                    create_tenant_unit_payload(
                        unit_label=label, floor_area_sqft=area, space_type=space_type
                    ),
                    headers,
                )
            )
        )
    return units


def request_consent(unit_id, owner_id) -> dict:
    """Owner requests whole-building-aggregation consent for a unit (PRD §3.3)."""
    return get_success_data(
        api_client.create_consent_grant(unit_id, make_owner_headers(owner_id))
    )


def grant_consent(grant_id, unit_id, valid_from="2027-01-01", valid_to="2027-12-31") -> dict:
    """Tenant grants consent with a closed [valid_from, valid_to] window (PRD §3.3)."""
    return get_success_data(
        api_client.grant_consent(
            grant_id,
            grant_consent_payload(valid_from=valid_from, valid_to=valid_to),
            make_tenant_rep_headers(unit_id),
        )
    )


def request_and_grant_consent(
    unit_id, owner_id, valid_from="2027-01-01", valid_to="2027-12-31"
) -> dict:
    grant = request_consent(unit_id, owner_id)
    return grant_consent(grant["id"], unit_id, valid_from, valid_to)


def add_utility_account(building_id, owner_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_utility_account(
            building_id, create_utility_account_payload(**overrides), make_owner_headers(owner_id)
        )
    )


def upload_usage(account_id, period_start, period_end, consumption_value) -> dict:
    """Upload a usage record via the utility data feed role (PRD §3.4)."""
    return get_success_data(
        api_client.create_usage_record(
            account_id,
            create_usage_record_payload(
                period_start=period_start,
                period_end=period_end,
                consumption_value=consumption_value,
            ),
            UTILITY,
        )
    )


def create_report(building_id, cycle_id, owner_id) -> dict:
    """Create the DRAFT benchmark report for a covered building + OPEN cycle."""
    return get_success_data(
        api_client.create_benchmark_report(
            create_benchmark_report_payload(building_id, cycle_id), make_owner_headers(owner_id)
        )
    )


def submit_report(report_id, owner_id) -> dict:
    return get_success_data(api_client.submit_report(report_id, make_owner_headers(owner_id)))


def assign_verifier(report_id, verifier_id, owner_id) -> dict:
    return get_success_data(
        api_client.create_verification_record(
            report_id, create_verification_record_payload(verifier_id), make_owner_headers(owner_id)
        )
    )


def sign_off_verification(record_id, verifier_id) -> dict:
    return get_success_data(
        api_client.sign_off_verification(record_id, make_verifier_headers(verifier_id))
    )


def certify_report(report_id, officer_headers=OFFICER2) -> dict:
    return get_success_data(api_client.certify_report(report_id, officer_headers))


def set_clock(to_iso8601, officer_headers=OFFICER) -> dict:
    """Advance the server logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, officer_headers))


def get_report(report_id) -> dict:
    return get_success_data(api_client.get_benchmark_report(report_id, OFFICER))


def get_owner(owner_id) -> dict:
    return get_success_data(api_client.get_owner(owner_id, OFFICER))


def get_cycle(cycle_id) -> dict:
    return get_success_data(api_client.get_reporting_cycle(cycle_id, OFFICER))


def list_fines(**params) -> list:
    data, _meta = validate_paginated(api_client.list_fine_assessments(OFFICER, params=params))
    return data


def list_flags(**params) -> list:
    data, _meta = validate_paginated(api_client.list_anomaly_flags(OFFICER, params=params))
    return data


def list_publications(**params) -> list:
    data, _meta = validate_paginated(api_client.list_disclosure_publications(OFFICER, params=params))
    return data


# ─── Tier 2: entity hierarchy composites ─────────────────────────────────────

def setup_building_with_consents(
    owner=None,
    building_overrides=None,
    unit_specs=None,
    consent_indexes=(0, 1),
    consent_window=("2027-01-01", "2027-12-31"),
) -> dict:
    """Owner + building + units + GRANTED consents for the indexed units.

    With the default geometry (50000 sqft, units 20000/15000/5000) and the
    default two consents covering the cycle year, report completeness is 90.00.
    """
    owner = owner or create_owner()
    building = create_building(owner["id"], **(building_overrides or {}))
    units = add_tenant_units(building["id"], owner["id"], unit_specs)
    grants = [
        request_and_grant_consent(units[i]["id"], owner["id"], *consent_window)
        for i in consent_indexes
    ]
    return {"owner": owner, "building": building, "units": units, "grants": grants}


def setup_report_scenario(
    owner=None,
    cycle=None,
    building_overrides=None,
    unit_specs=None,
    consent_indexes=(0, 1),
    consent_window=("2027-01-01", "2027-12-31"),
    usage_records=None,
    account_overrides=None,
    cycle_overrides=None,
    officer_headers=OFFICER,
) -> dict:
    """OPEN cycle + building with consents + optional usage + DRAFT report.

    usage_records: list of {"period_start", "period_end", "consumption_value"}
    posted to a single utility account created for the building.
    """
    cycle = cycle or create_and_open_cycle(officer_headers, **(cycle_overrides or {}))
    ctx = setup_building_with_consents(
        owner=owner,
        building_overrides=building_overrides,
        unit_specs=unit_specs,
        consent_indexes=consent_indexes,
        consent_window=consent_window,
    )
    account = None
    records = []
    if usage_records:
        account = add_utility_account(
            ctx["building"]["id"], ctx["owner"]["id"], **(account_overrides or {})
        )
        for r in usage_records:
            records.append(
                upload_usage(account["id"], r["period_start"], r["period_end"], r["consumption_value"])
            )
    ctx.update(
        {
            "cycle": cycle,
            "account": account,
            "usage_records": records,
            "report": create_report(ctx["building"]["id"], cycle["id"], ctx["owner"]["id"]),
        }
    )
    return ctx


# ─── Tier 3: full lifecycle shortcuts ────────────────────────────────────────

def submit_ctx(ctx) -> dict:
    """Submit the context's report as its owner; refreshes ctx['report']."""
    ctx["report"] = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
    return ctx


def verify_report(ctx, verifier=None) -> dict:
    """Assign a verifier and sign off: report SUBMITTED -> VERIFIED (PRD §3.6)."""
    verifier = verifier or create_verifier()
    vr = assign_verifier(ctx["report"]["id"], verifier["id"], ctx["owner"]["id"])
    sign_off_verification(vr["id"], verifier["id"])
    ctx["verifier"] = verifier
    ctx["verification"] = vr
    ctx["report"] = get_report(ctx["report"]["id"])
    return ctx


def setup_submitted_report(**kwargs) -> dict:
    """DRAFT report submitted on time (default logical clock precedes the deadline)."""
    return submit_ctx(setup_report_scenario(**kwargs))


def setup_verified_report(verifier=None, **kwargs) -> dict:
    """Full flow through VERIFIED: submit -> assign -> sign-off."""
    ctx = setup_submitted_report(**kwargs)
    return verify_report(ctx, verifier)


# ─── Tier 4: late-fine accumulation ──────────────────────────────────────────

def setup_late_fine_scenario(submit_clock="2027-06-03T12:00:00Z", **kwargs) -> dict:
    """DRAFT report at submittable completeness; clock advanced past the deadline;
    late submit accrues a LATE_SUBMISSION fine. Returns ctx with ctx['fine']."""
    ctx = setup_report_scenario(**kwargs)
    set_clock(submit_clock)
    ctx["report"] = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
    fines = list_fines(building_id=ctx["building"]["id"])
    assert len(fines) == 1, f"expected exactly one late fine, got {len(fines)}"
    ctx["fine"] = fines[0]
    return ctx


def notice_fine(fine_id, officer_headers=OFFICER) -> dict:
    return get_success_data(api_client.notice_fine(fine_id, officer_headers))


def pay_fine(fine_id, owner_id, paid_amount_cents) -> dict:
    return get_success_data(
        api_client.pay_fine(fine_id, {"paid_amount_cents": paid_amount_cents}, make_owner_headers(owner_id))
    )


def waive_fine(fine_id, waive_reason, officer_headers=OFFICER) -> dict:
    return get_success_data(
        api_client.waive_fine(fine_id, {"waive_reason": waive_reason}, officer_headers)
    )


# ─── Tier 5: close-filing / publication terminal states ──────────────────────

def close_filing_cycle(cycle_id, officer_headers=OFFICER, past_deadline_clock="2027-06-02T00:00:00Z") -> dict:
    """Advance the clock strictly past the deadline and close filing (PRD §3.1)."""
    set_clock(past_deadline_clock)
    return get_success_data(api_client.close_filing(cycle_id, officer_headers))


def setup_published_cycle_with_verified_report(publish_officer=OFFICER, **kwargs) -> dict:
    """VERIFIED report -> close-filing -> DRAFT publication -> PUBLISHED.

    The default usage (1,200,000 kWh ELECTRICITY over the cycle year) keeps the
    verified site_eui at 81.89, below the performance-shortfall threshold.
    """
    kwargs.setdefault(
        "usage_records",
        [
            {
                "period_start": "2027-01-01T00:00:00Z",
                "period_end": "2028-01-01T00:00:00Z",
                "consumption_value": 1200000,
            }
        ],
    )
    ctx = setup_verified_report(**kwargs)
    ctx["cycle"] = close_filing_cycle(ctx["cycle"]["id"])
    publication = get_success_data(
        api_client.create_disclosure_publication(ctx["cycle"]["id"], publish_officer)
    )
    ctx["publication"] = get_success_data(
        api_client.publish_disclosure(publication["id"], publish_officer)
    )
    ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    return ctx


# ─── Exemption helpers ────────────────────────────────────────────────────────

def create_exemption(building_id, owner_id, cycle_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_exemption_request(
            building_id,
            create_exemption_request_payload(cycle_id, **overrides),
            make_owner_headers(owner_id),
        )
    )


def review_and_decide_exemption(request_id, decision, decision_note, officer_headers=OFFICER) -> dict:
    get_success_data(api_client.start_exemption_review(request_id, officer_headers))
    return get_success_data(
        api_client.decide_exemption(
            request_id, {"decision": decision, "decision_note": decision_note}, officer_headers
        )
    )
