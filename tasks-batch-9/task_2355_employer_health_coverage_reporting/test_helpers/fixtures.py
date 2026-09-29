"""Composite setup helpers.

The harness empties the database and relaunches the server before every single
test, so every precondition here is rebuilt from scratch through the PRD's own
endpoints. Helpers use the lenient ``get_success_data`` validator: they exist to
*establish* state, and the assertions that matter belong in the tests.

Every helper accepts an explicit ``headers`` argument so a recipe can pin which
operator performed the setup step — segregation of duties (PRD §2.7) makes the
acting identity part of the state.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_STARTUP_UTC
from .test_users import (
    make_benefits_admin_headers,
    make_compliance_officer_headers,
    make_employee_self_service_headers,
    make_filing_agent_headers,
    make_preparer_headers,
    PREPARER_2_USER_ID,
)

CO = make_compliance_officer_headers()
BA = make_benefits_admin_headers()
PREPARER = make_preparer_headers()
PREPARER_2 = make_preparer_headers(PREPARER_2_USER_ID)
AGENT = make_filing_agent_headers()


# ---------------------------------------------------------------------------
# Tier 1: logical clock
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601, headers=CO):
    """Move the server's logical clock. Startup value is CLOCK_STARTUP_UTC."""
    return get_success_data(api.set_current_utc(f.clock_payload(to_iso8601), headers))


def reset_clock(api, headers=CO):
    return set_clock(api, CLOCK_STARTUP_UTC, headers)


# ---------------------------------------------------------------------------
# Tier 1: single-row creates
# ---------------------------------------------------------------------------
def create_filing_season(api, headers=CO, **overrides):
    return get_success_data(api.create_filing_season(f.filing_season_payload(**overrides), headers))


def create_controlled_group(api, filing_season_id, headers=CO, **overrides):
    return get_success_data(
        api.create_controlled_group(f.controlled_group_payload(filing_season_id, **overrides), headers)
    )


def create_group_member(api, controlled_group_id, ein="123456789", headers=CO, **overrides):
    return get_success_data(
        api.create_group_member(f.group_member_payload(controlled_group_id, ein, **overrides), headers)
    )


def create_employee(api, group_member_id, full_name="Dana Rivers", headers=BA, **overrides):
    return get_success_data(
        api.create_employee(f.employee_payload(group_member_id, full_name, **overrides), headers)
    )


def create_measurement_cycle(api, group_member_id, headers=CO, **overrides):
    return get_success_data(
        api.create_measurement_cycle(
            f.measurement_cycle_payload(group_member_id, **overrides), headers
        )
    )


def create_coverage_offer(api, employee_id, headers=BA, **overrides):
    return get_success_data(
        api.create_coverage_offer(f.coverage_offer_payload(employee_id, **overrides), headers)
    )


def create_employment_event(api, employee_id, event_type, effective_date, headers=BA, **overrides):
    return get_success_data(
        api.create_employment_event(
            f.employment_event_payload(employee_id, event_type, effective_date, **overrides),
            headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: batch ledger writes
# ---------------------------------------------------------------------------
def record_headcounts(api, group_member_id, months=None, headers=CO, **overrides):
    months = list(range(1, 13)) if months is None else months
    return get_success_data(
        api.create_monthly_headcounts(
            f.monthly_headcounts_payload(group_member_id, months, **overrides), headers
        )
    )


def record_hours(api, employee_id, measurement_year, months=None, headers=BA, **overrides):
    months = list(range(1, 13)) if months is None else months
    return get_success_data(
        api.create_hours_records(
            f.hours_records_payload(employee_id, measurement_year, months, **overrides), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: version-guarded actions (live version is read, never guessed)
# ---------------------------------------------------------------------------
def current_group_version(api, group_id, headers=CO):
    return get_success_data(api.get_controlled_group(group_id, headers))["version"]


def current_member_version(api, member_id, headers=CO):
    return get_success_data(api.get_group_member(member_id, headers))["version"]


def run_ale_determination(api, group_id, headers=CO, **overrides):
    payload = f.ale_determination_payload(current_group_version(api, group_id, headers), **overrides)
    return get_success_data(api.run_ale_determination(group_id, payload, headers))


def open_transmittal(api, group_member_id, headers=PREPARER, **overrides):
    payload = f.transmittal_payload(
        group_member_id, current_member_version(api, group_member_id, headers), **overrides
    )
    return get_success_data(api.create_transmittal(payload, headers))


# ---------------------------------------------------------------------------
# Tier 3: the shared prelude — a season with one determined-ALE member
# ---------------------------------------------------------------------------
def determined_ale_group(
    api,
    headers=CO,
    member_measurement_method="MONTHLY",
    season_overrides=None,
    member_overrides=None,
    headcount_overrides=None,
):
    """Season → controlled group → one member → twelve prior-year headcounts →
    aggregated determination. Returns the season, group and member rows plus the
    determination result.
    """
    season = create_filing_season(api, headers, **(season_overrides or {}))
    group = create_controlled_group(api, season["id"], headers)
    member_kwargs = {"measurement_method": member_measurement_method}
    member_kwargs.update(member_overrides or {})
    member = create_group_member(api, group["id"], headers=headers, **member_kwargs)
    record_headcounts(api, member["id"], headers=headers, **(headcount_overrides or {}))
    determined = run_ale_determination(api, group["id"], headers)
    return {
        "season": season,
        "group": group,
        "member": member,
        "determined_group": determined,
    }


def determined_ale_group_with_employee(
    api,
    employee_overrides=None,
    **prelude_kwargs,
):
    """The prelude plus one employee hired into the member."""
    ctx = determined_ale_group(api, **prelude_kwargs)
    ctx["employee"] = create_employee(
        api, ctx["member"]["id"], **(employee_overrides or {})
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: statements
# ---------------------------------------------------------------------------
def generate_form(api, employee_id, headers=PREPARER, **overrides):
    return get_success_data(
        api.create_form_1095c(f.form_1095c_payload(employee_id, **overrides), headers)
    )


def coverage_lines_for(api, form_id, headers=PREPARER):
    """Coverage lines are only reachable by filtering on ``form_1095c_id``."""
    response = api.list_monthly_coverage_lines(
        headers, params={"form_1095c_id": form_id, "limit": 100}
    )
    return get_success_data(response)


def furnish_form(api, form_id, delivery_channel="PAPER", headers=PREPARER_2, **overrides):
    """Furnishing is refused for the user in ``generated_by_user_id``, so the
    default actor here is a second preparer."""
    return get_success_data(
        api.furnish_form_1095c(form_id, f.furnish_payload(delivery_channel, **overrides), headers)
    )


def regenerate_form(api, form_id, headers=PREPARER, **overrides):
    return get_success_data(api.regenerate_form_1095c(form_id, headers, overrides or None))


# ---------------------------------------------------------------------------
# Tier 3: consent
# ---------------------------------------------------------------------------
def create_consent(api, employee_id, headers=BA, **overrides):
    return get_success_data(
        api.create_furnishing_consent(f.furnishing_consent_payload(employee_id, **overrides), headers)
    )


def granted_consent(api, employee_id, **overrides):
    """Create the consent as the benefits admin, then have the employee grant it
    (grant is an ``EmployeeSelfService`` action on their own consent)."""
    consent = create_consent(api, employee_id, **overrides)
    return get_success_data(
        api.grant_furnishing_consent(
            consent["id"], make_employee_self_service_headers(employee_id)
        )
    )


def withdraw_consent(api, consent_id, employee_id):
    return get_success_data(
        api.withdraw_furnishing_consent(
            consent_id, make_employee_self_service_headers(employee_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: submission pipeline
# ---------------------------------------------------------------------------
def attach_forms(api, transmittal_id, form_ids, headers=PREPARER):
    return get_success_data(
        api.attach_forms(transmittal_id, f.attach_forms_payload(form_ids), headers)
    )


def detach_form(api, transmittal_id, form_id, headers=PREPARER):
    return get_success_data(
        api.detach_form(transmittal_id, f.detach_form_payload(form_id), headers)
    )


def build_transmittal(api, transmittal_id, headers=PREPARER):
    return get_success_data(api.build_transmittal(transmittal_id, headers))


def transmit_transmittal(api, transmittal_id, channel="PAPER", headers=AGENT):
    return get_success_data(
        api.transmit_transmittal(transmittal_id, f.transmit_payload(channel), headers)
    )


def record_agency_response(api, transmittal_id, response_status, receipt_id, errors=None,
                           headers=AGENT):
    return get_success_data(
        api.record_agency_response(
            transmittal_id, f.agency_response_payload(response_status, receipt_id, errors), headers
        )
    )


def built_transmittal_with_forms(api, group_member_id, form_ids, **overrides):
    """Open a transmittal, attach the named statements and build it."""
    transmittal = open_transmittal(api, group_member_id, **overrides)
    attach_forms(api, transmittal["id"], form_ids)
    return build_transmittal(api, transmittal["id"])


def accepted_transmittal_with_forms(
    api, group_member_id, form_ids, channel="PAPER", receipt_id="AIR-2026-0001", **overrides
):
    """Carry statements all the way to ``FILED_ACCEPTED``: open → attach → build
    → transmit → clean agency acceptance."""
    built = built_transmittal_with_forms(api, group_member_id, form_ids, **overrides)
    transmit_transmittal(api, built["id"], channel)
    return record_agency_response(api, built["id"], "ACCEPTED", receipt_id)


# ---------------------------------------------------------------------------
# Tier 5: proposed-penalty response
# ---------------------------------------------------------------------------
def create_penalty_notice(
    api,
    controlled_group_id,
    notice_number,
    asserted_a_months=None,
    asserted_b_employee_months=None,
    headers=CO,
    **overrides,
):
    return get_success_data(
        api.create_penalty_notice(
            f.penalty_notice_payload(
                controlled_group_id,
                notice_number,
                asserted_a_months,
                asserted_b_employee_months,
                **overrides,
            ),
            headers,
        )
    )


def file_evidence(api, notice_id, evidence_type, month, headers=CO, **overrides):
    return get_success_data(
        api.create_penalty_evidence(
            notice_id, f.penalty_evidence_payload(evidence_type, month, **overrides), headers
        )
    )


def recompute_notice(api, notice_id, headers=CO):
    return get_success_data(api.recompute_penalty_notice(notice_id, headers))


def reset_allocation(api, notice_id, headers=CO):
    return get_success_data(api.reset_penalty_allocation(notice_id, headers))


def submit_response(api, notice_id, headers=CO):
    return get_success_data(api.submit_penalty_response(notice_id, headers))


# ---------------------------------------------------------------------------
# Read-back conveniences
# ---------------------------------------------------------------------------
def read_group(api, group_id, headers=CO):
    return get_success_data(api.get_controlled_group(group_id, headers))


def read_member(api, member_id, headers=CO):
    return get_success_data(api.get_group_member(member_id, headers))


def read_employee(api, employee_id, headers=BA):
    return get_success_data(api.get_employee(employee_id, headers))


def read_season(api, season_id, headers=CO):
    return get_success_data(api.get_filing_season(season_id, headers))


def read_form(api, form_id, headers=PREPARER):
    return get_success_data(api.get_form_1095c(form_id, headers))


def read_transmittal(api, transmittal_id, headers=PREPARER):
    return get_success_data(api.get_transmittal(transmittal_id, headers))


def read_consent(api, consent_id, headers=BA):
    return get_success_data(api.get_furnishing_consent(consent_id, headers))


def read_notice(api, notice_id, headers=CO):
    return get_success_data(api.get_penalty_notice(notice_id, headers))
